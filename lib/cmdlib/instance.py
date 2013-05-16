#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Logical units dealing with instances."""

import OpenSSL
import copy
import itertools
import logging
import operator
import os
import time

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import ht
from ganeti import hypervisor
from ganeti import locking
from ganeti.masterd import iallocator
from ganeti import masterd
from ganeti import netutils
from ganeti import objects
from ganeti import opcodes
from ganeti import pathutils
from ganeti import qlang
from ganeti import rpc
from ganeti import utils
from ganeti import query

from ganeti.cmdlib.base import NoHooksLU, LogicalUnit, _QueryBase, \
  ResultWithJobs, Tasklet

from ganeti.cmdlib.common import INSTANCE_ONLINE, INSTANCE_DOWN, \
  INSTANCE_NOT_RUNNING, CAN_CHANGE_INSTANCE_OFFLINE, _CheckNodeOnline, \
  _ShareAll, _GetDefaultIAllocator, _CheckInstanceNodeGroups, \
  _LoadNodeEvacResult, _CheckIAllocatorOrNode, _CheckParamsNotGlobal, \
  _IsExclusiveStorageEnabledNode, _CheckHVParams, _CheckOSParams, \
  _GetWantedInstances, _CheckInstancesNodeGroups, _AnnotateDiskParams, \
  _GetUpdatedParams, _ExpandInstanceName, _ComputeIPolicySpecViolation, \
  _CheckInstanceState, _ExpandNodeName
from ganeti.cmdlib.instance_storage import _CreateDisks, \
  _CheckNodesFreeDiskPerVG, _WipeDisks, _WaitForSync, _CheckDiskConsistency, \
  _IsExclusiveStorageEnabledNodeName, _CreateSingleBlockDev, _ComputeDisks, \
  _CheckRADOSFreeSpace, _ComputeDiskSizePerVG, _GenerateDiskTemplate, \
  _CreateBlockDev, _StartInstanceDisks, _ShutdownInstanceDisks, \
  _AssembleInstanceDisks, _ExpandCheckDisks
from ganeti.cmdlib.instance_utils import _BuildInstanceHookEnvByObject, \
  _GetClusterDomainSecret, _BuildInstanceHookEnv, _NICListToTuple, \
  _NICToTuple, _CheckNodeNotDrained, _RemoveInstance, _CopyLockList, \
  _ReleaseLocks, _CheckNodeVmCapable, _CheckTargetNodeIPolicy, \
  _GetInstanceInfoText, _RemoveDisks

import ganeti.masterd.instance


#: Type description for changes as returned by L{ApplyContainerMods}'s
#: callbacks
_TApplyContModsCbChanges = \
  ht.TMaybeListOf(ht.TAnd(ht.TIsLength(2), ht.TItems([
    ht.TNonEmptyString,
    ht.TAny,
    ])))


def _CheckHostnameSane(lu, name):
  """Ensures that a given hostname resolves to a 'sane' name.

  The given name is required to be a prefix of the resolved hostname,
  to prevent accidental mismatches.

  @param lu: the logical unit on behalf of which we're checking
  @param name: the name we should resolve and check
  @return: the resolved hostname object

  """
  hostname = netutils.GetHostname(name=name)
  if hostname.name != name:
    lu.LogInfo("Resolved given name '%s' to '%s'", name, hostname.name)
  if not utils.MatchNameComponent(name, [hostname.name]):
    raise errors.OpPrereqError(("Resolved hostname '%s' does not look the"
                                " same as given hostname '%s'") %
                               (hostname.name, name), errors.ECODE_INVAL)
  return hostname


def _CheckOpportunisticLocking(op):
  """Generate error if opportunistic locking is not possible.

  """
  if op.opportunistic_locking and not op.iallocator:
    raise errors.OpPrereqError("Opportunistic locking is only available in"
                               " combination with an instance allocator",
                               errors.ECODE_INVAL)


def _CreateInstanceAllocRequest(op, disks, nics, beparams, node_whitelist):
  """Wrapper around IAReqInstanceAlloc.

  @param op: The instance opcode
  @param disks: The computed disks
  @param nics: The computed nics
  @param beparams: The full filled beparams
  @param node_whitelist: List of nodes which should appear as online to the
    allocator (unless the node is already marked offline)

  @returns: A filled L{iallocator.IAReqInstanceAlloc}

  """
  spindle_use = beparams[constants.BE_SPINDLE_USE]
  return iallocator.IAReqInstanceAlloc(name=op.instance_name,
                                       disk_template=op.disk_template,
                                       tags=op.tags,
                                       os=op.os_type,
                                       vcpus=beparams[constants.BE_VCPUS],
                                       memory=beparams[constants.BE_MAXMEM],
                                       spindle_use=spindle_use,
                                       disks=disks,
                                       nics=[n.ToDict() for n in nics],
                                       hypervisor=op.hypervisor,
                                       node_whitelist=node_whitelist)


def _ComputeFullBeParams(op, cluster):
  """Computes the full beparams.

  @param op: The instance opcode
  @param cluster: The cluster config object

  @return: The fully filled beparams

  """
  default_beparams = cluster.beparams[constants.PP_DEFAULT]
  for param, value in op.beparams.iteritems():
    if value == constants.VALUE_AUTO:
      op.beparams[param] = default_beparams[param]
  objects.UpgradeBeParams(op.beparams)
  utils.ForceDictType(op.beparams, constants.BES_PARAMETER_TYPES)
  return cluster.SimpleFillBE(op.beparams)


def _ComputeNics(op, cluster, default_ip, cfg, ec_id):
  """Computes the nics.

  @param op: The instance opcode
  @param cluster: Cluster configuration object
  @param default_ip: The default ip to assign
  @param cfg: An instance of the configuration object
  @param ec_id: Execution context ID

  @returns: The build up nics

  """
  nics = []
  for nic in op.nics:
    nic_mode_req = nic.get(constants.INIC_MODE, None)
    nic_mode = nic_mode_req
    if nic_mode is None or nic_mode == constants.VALUE_AUTO:
      nic_mode = cluster.nicparams[constants.PP_DEFAULT][constants.NIC_MODE]

    net = nic.get(constants.INIC_NETWORK, None)
    link = nic.get(constants.NIC_LINK, None)
    ip = nic.get(constants.INIC_IP, None)

    if net is None or net.lower() == constants.VALUE_NONE:
      net = None
    else:
      if nic_mode_req is not None or link is not None:
        raise errors.OpPrereqError("If network is given, no mode or link"
                                   " is allowed to be passed",
                                   errors.ECODE_INVAL)

    # ip validity checks
    if ip is None or ip.lower() == constants.VALUE_NONE:
      nic_ip = None
    elif ip.lower() == constants.VALUE_AUTO:
      if not op.name_check:
        raise errors.OpPrereqError("IP address set to auto but name checks"
                                   " have been skipped",
                                   errors.ECODE_INVAL)
      nic_ip = default_ip
    else:
      # We defer pool operations until later, so that the iallocator has
      # filled in the instance's node(s) dimara
      if ip.lower() == constants.NIC_IP_POOL:
        if net is None:
          raise errors.OpPrereqError("if ip=pool, parameter network"
                                     " must be passed too",
                                     errors.ECODE_INVAL)

      elif not netutils.IPAddress.IsValid(ip):
        raise errors.OpPrereqError("Invalid IP address '%s'" % ip,
                                   errors.ECODE_INVAL)

      nic_ip = ip

    # TODO: check the ip address for uniqueness
    if nic_mode == constants.NIC_MODE_ROUTED and not nic_ip:
      raise errors.OpPrereqError("Routed nic mode requires an ip address",
                                 errors.ECODE_INVAL)

    # MAC address verification
    mac = nic.get(constants.INIC_MAC, constants.VALUE_AUTO)
    if mac not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
      mac = utils.NormalizeAndValidateMac(mac)

      try:
        # TODO: We need to factor this out
        cfg.ReserveMAC(mac, ec_id)
      except errors.ReservationError:
        raise errors.OpPrereqError("MAC address %s already in use"
                                   " in cluster" % mac,
                                   errors.ECODE_NOTUNIQUE)

    #  Build nic parameters
    nicparams = {}
    if nic_mode_req:
      nicparams[constants.NIC_MODE] = nic_mode
    if link:
      nicparams[constants.NIC_LINK] = link

    check_params = cluster.SimpleFillNIC(nicparams)
    objects.NIC.CheckParameterSyntax(check_params)
    net_uuid = cfg.LookupNetwork(net)
    name = nic.get(constants.INIC_NAME, None)
    if name is not None and name.lower() == constants.VALUE_NONE:
      name = None
    nic_obj = objects.NIC(mac=mac, ip=nic_ip, name=name,
                          network=net_uuid, nicparams=nicparams)
    nic_obj.uuid = cfg.GenerateUniqueID(ec_id)
    nics.append(nic_obj)

  return nics


def _CheckForConflictingIp(lu, ip, node):
  """In case of conflicting IP address raise error.

  @type ip: string
  @param ip: IP address
  @type node: string
  @param node: node name

  """
  (conf_net, _) = lu.cfg.CheckIPInNodeGroup(ip, node)
  if conf_net is not None:
    raise errors.OpPrereqError(("The requested IP address (%s) belongs to"
                                " network %s, but the target NIC does not." %
                                (ip, conf_net)),
                               errors.ECODE_STATE)

  return (None, None)


def _ComputeIPolicyInstanceSpecViolation(
  ipolicy, instance_spec, disk_template,
  _compute_fn=_ComputeIPolicySpecViolation):
  """Compute if instance specs meets the specs of ipolicy.

  @type ipolicy: dict
  @param ipolicy: The ipolicy to verify against
  @param instance_spec: dict
  @param instance_spec: The instance spec to verify
  @type disk_template: string
  @param disk_template: the disk template of the instance
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{_ComputeIPolicySpecViolation}

  """
  mem_size = instance_spec.get(constants.ISPEC_MEM_SIZE, None)
  cpu_count = instance_spec.get(constants.ISPEC_CPU_COUNT, None)
  disk_count = instance_spec.get(constants.ISPEC_DISK_COUNT, 0)
  disk_sizes = instance_spec.get(constants.ISPEC_DISK_SIZE, [])
  nic_count = instance_spec.get(constants.ISPEC_NIC_COUNT, 0)
  spindle_use = instance_spec.get(constants.ISPEC_SPINDLE_USE, None)

  return _compute_fn(ipolicy, mem_size, cpu_count, disk_count, nic_count,
                     disk_sizes, spindle_use, disk_template)


def _CheckOSVariant(os_obj, name):
  """Check whether an OS name conforms to the os variants specification.

  @type os_obj: L{objects.OS}
  @param os_obj: OS object to check
  @type name: string
  @param name: OS name passed by the user, to check for validity

  """
  variant = objects.OS.GetVariant(name)
  if not os_obj.supported_variants:
    if variant:
      raise errors.OpPrereqError("OS '%s' doesn't support variants ('%s'"
                                 " passed)" % (os_obj.name, variant),
                                 errors.ECODE_INVAL)
    return
  if not variant:
    raise errors.OpPrereqError("OS name must include a variant",
                               errors.ECODE_INVAL)

  if variant not in os_obj.supported_variants:
    raise errors.OpPrereqError("Unsupported OS variant", errors.ECODE_INVAL)


def _CheckNodeHasOS(lu, node, os_name, force_variant):
  """Ensure that a node supports a given OS.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @param os_name: the OS to query about
  @param force_variant: whether to ignore variant errors
  @raise errors.OpPrereqError: if the node is not supporting the OS

  """
  result = lu.rpc.call_os_get(node, os_name)
  result.Raise("OS '%s' not in supported OS list for node %s" %
               (os_name, node),
               prereq=True, ecode=errors.ECODE_INVAL)
  if not force_variant:
    _CheckOSVariant(result.payload, os_name)


def _CheckNicsBridgesExist(lu, target_nics, target_node):
  """Check that the brigdes needed by a list of nics exist.

  """
  cluster = lu.cfg.GetClusterInfo()
  paramslist = [cluster.SimpleFillNIC(nic.nicparams) for nic in target_nics]
  brlist = [params[constants.NIC_LINK] for params in paramslist
            if params[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED]
  if brlist:
    result = lu.rpc.call_bridges_exist(target_node, brlist)
    result.Raise("Error checking bridges on destination node '%s'" %
                 target_node, prereq=True, ecode=errors.ECODE_ENVIRON)


def _CheckNodeFreeMemory(lu, node, reason, requested, hypervisor_name):
  """Checks if a node has enough free memory.

  This function checks if a given node has the needed amount of free
  memory. In case the node has less memory or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type node: C{str}
  @param node: the node to check
  @type reason: C{str}
  @param reason: string to use in the error message
  @type requested: C{int}
  @param requested: the amount of memory in MiB to check for
  @type hypervisor_name: C{str}
  @param hypervisor_name: the hypervisor to ask for memory stats
  @rtype: integer
  @return: node current free memory
  @raise errors.OpPrereqError: if the node doesn't have enough memory, or
      we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info([node], None, [hypervisor_name], False)
  nodeinfo[node].Raise("Can't get data from node %s" % node,
                       prereq=True, ecode=errors.ECODE_ENVIRON)
  (_, _, (hv_info, )) = nodeinfo[node].payload

  free_mem = hv_info.get("memory_free", None)
  if not isinstance(free_mem, int):
    raise errors.OpPrereqError("Can't compute free memory on node %s, result"
                               " was '%s'" % (node, free_mem),
                               errors.ECODE_ENVIRON)
  if requested > free_mem:
    raise errors.OpPrereqError("Not enough memory on node %s for %s:"
                               " needed %s MiB, available %s MiB" %
                               (node, reason, requested, free_mem),
                               errors.ECODE_NORES)
  return free_mem


class LUInstanceCreate(LogicalUnit):
  """Create an instance.

  """
  HPATH = "instance-add"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    # do not require name_check to ease forward/backward compatibility
    # for tools
    if self.op.no_install and self.op.start:
      self.LogInfo("No-installation mode selected, disabling startup")
      self.op.start = False
    # validate/normalize the instance name
    self.op.instance_name = \
      netutils.Hostname.GetNormalizedName(self.op.instance_name)

    if self.op.ip_check and not self.op.name_check:
      # TODO: make the ip check more flexible and not depend on the name check
      raise errors.OpPrereqError("Cannot do IP address check without a name"
                                 " check", errors.ECODE_INVAL)

    # check nics' parameter names
    for nic in self.op.nics:
      utils.ForceDictType(nic, constants.INIC_PARAMS_TYPES)
    # check that NIC's parameters names are unique and valid
    utils.ValidateDeviceNames("NIC", self.op.nics)

    # check that disk's names are unique and valid
    utils.ValidateDeviceNames("disk", self.op.disks)

    cluster = self.cfg.GetClusterInfo()
    if not self.op.disk_template in cluster.enabled_disk_templates:
      raise errors.OpPrereqError("Cannot create an instance with disk template"
                                 " '%s', because it is not enabled in the"
                                 " cluster. Enabled disk templates are: %s." %
                                 (self.op.disk_template,
                                  ",".join(cluster.enabled_disk_templates)))

    # check disks. parameter names and consistent adopt/no-adopt strategy
    has_adopt = has_no_adopt = False
    for disk in self.op.disks:
      if self.op.disk_template != constants.DT_EXT:
        utils.ForceDictType(disk, constants.IDISK_PARAMS_TYPES)
      if constants.IDISK_ADOPT in disk:
        has_adopt = True
      else:
        has_no_adopt = True
    if has_adopt and has_no_adopt:
      raise errors.OpPrereqError("Either all disks are adopted or none is",
                                 errors.ECODE_INVAL)
    if has_adopt:
      if self.op.disk_template not in constants.DTS_MAY_ADOPT:
        raise errors.OpPrereqError("Disk adoption is not supported for the"
                                   " '%s' disk template" %
                                   self.op.disk_template,
                                   errors.ECODE_INVAL)
      if self.op.iallocator is not None:
        raise errors.OpPrereqError("Disk adoption not allowed with an"
                                   " iallocator script", errors.ECODE_INVAL)
      if self.op.mode == constants.INSTANCE_IMPORT:
        raise errors.OpPrereqError("Disk adoption not allowed for"
                                   " instance import", errors.ECODE_INVAL)
    else:
      if self.op.disk_template in constants.DTS_MUST_ADOPT:
        raise errors.OpPrereqError("Disk template %s requires disk adoption,"
                                   " but no 'adopt' parameter given" %
                                   self.op.disk_template,
                                   errors.ECODE_INVAL)

    self.adopt_disks = has_adopt

    # instance name verification
    if self.op.name_check:
      self.hostname1 = _CheckHostnameSane(self, self.op.instance_name)
      self.op.instance_name = self.hostname1.name
      # used in CheckPrereq for ip ping check
      self.check_ip = self.hostname1.ip
    else:
      self.check_ip = None

    # file storage checks
    if (self.op.file_driver and
        not self.op.file_driver in constants.FILE_DRIVER):
      raise errors.OpPrereqError("Invalid file driver name '%s'" %
                                 self.op.file_driver, errors.ECODE_INVAL)

    if self.op.disk_template == constants.DT_FILE:
      opcodes.RequireFileStorage()
    elif self.op.disk_template == constants.DT_SHARED_FILE:
      opcodes.RequireSharedFileStorage()

    ### Node/iallocator related checks
    _CheckIAllocatorOrNode(self, "iallocator", "pnode")

    if self.op.pnode is not None:
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        if self.op.snode is None:
          raise errors.OpPrereqError("The networked disk templates need"
                                     " a mirror node", errors.ECODE_INVAL)
      elif self.op.snode:
        self.LogWarning("Secondary node will be ignored on non-mirrored disk"
                        " template")
        self.op.snode = None

    _CheckOpportunisticLocking(self.op)

    self._cds = _GetClusterDomainSecret()

    if self.op.mode == constants.INSTANCE_IMPORT:
      # On import force_variant must be True, because if we forced it at
      # initial install, our only chance when importing it back is that it
      # works again!
      self.op.force_variant = True

      if self.op.no_install:
        self.LogInfo("No-installation mode has no effect during import")

    elif self.op.mode == constants.INSTANCE_CREATE:
      if self.op.os_type is None:
        raise errors.OpPrereqError("No guest OS specified",
                                   errors.ECODE_INVAL)
      if self.op.os_type in self.cfg.GetClusterInfo().blacklisted_os:
        raise errors.OpPrereqError("Guest OS '%s' is not allowed for"
                                   " installation" % self.op.os_type,
                                   errors.ECODE_STATE)
      if self.op.disk_template is None:
        raise errors.OpPrereqError("No disk template specified",
                                   errors.ECODE_INVAL)

    elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
      # Check handshake to ensure both clusters have the same domain secret
      src_handshake = self.op.source_handshake
      if not src_handshake:
        raise errors.OpPrereqError("Missing source handshake",
                                   errors.ECODE_INVAL)

      errmsg = masterd.instance.CheckRemoteExportHandshake(self._cds,
                                                           src_handshake)
      if errmsg:
        raise errors.OpPrereqError("Invalid handshake: %s" % errmsg,
                                   errors.ECODE_INVAL)

      # Load and check source CA
      self.source_x509_ca_pem = self.op.source_x509_ca
      if not self.source_x509_ca_pem:
        raise errors.OpPrereqError("Missing source X509 CA",
                                   errors.ECODE_INVAL)

      try:
        (cert, _) = utils.LoadSignedX509Certificate(self.source_x509_ca_pem,
                                                    self._cds)
      except OpenSSL.crypto.Error, err:
        raise errors.OpPrereqError("Unable to load source X509 CA (%s)" %
                                   (err, ), errors.ECODE_INVAL)

      (errcode, msg) = utils.VerifyX509Certificate(cert, None, None)
      if errcode is not None:
        raise errors.OpPrereqError("Invalid source X509 CA (%s)" % (msg, ),
                                   errors.ECODE_INVAL)

      self.source_x509_ca = cert

      src_instance_name = self.op.source_instance_name
      if not src_instance_name:
        raise errors.OpPrereqError("Missing source instance name",
                                   errors.ECODE_INVAL)

      self.source_instance_name = \
        netutils.GetHostname(name=src_instance_name).name

    else:
      raise errors.OpPrereqError("Invalid instance creation mode %r" %
                                 self.op.mode, errors.ECODE_INVAL)

  def ExpandNames(self):
    """ExpandNames for CreateInstance.

    Figure out the right locks for instance creation.

    """
    self.needed_locks = {}

    instance_name = self.op.instance_name
    # this is just a preventive check, but someone might still add this
    # instance in the meantime, and creation will fail at lock-add time
    if instance_name in self.cfg.GetInstanceList():
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 instance_name, errors.ECODE_EXISTS)

    self.add_locks[locking.LEVEL_INSTANCE] = instance_name

    if self.op.iallocator:
      # TODO: Find a solution to not lock all nodes in the cluster, e.g. by
      # specifying a group on instance creation and then selecting nodes from
      # that group
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

      if self.op.opportunistic_locking:
        self.opportunistic_locks[locking.LEVEL_NODE] = True
        self.opportunistic_locks[locking.LEVEL_NODE_RES] = True
    else:
      self.op.pnode = _ExpandNodeName(self.cfg, self.op.pnode)
      nodelist = [self.op.pnode]
      if self.op.snode is not None:
        self.op.snode = _ExpandNodeName(self.cfg, self.op.snode)
        nodelist.append(self.op.snode)
      self.needed_locks[locking.LEVEL_NODE] = nodelist

    # in case of import lock the source node too
    if self.op.mode == constants.INSTANCE_IMPORT:
      src_node = self.op.src_node
      src_path = self.op.src_path

      if src_path is None:
        self.op.src_path = src_path = self.op.instance_name

      if src_node is None:
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET
        self.op.src_node = None
        if os.path.isabs(src_path):
          raise errors.OpPrereqError("Importing an instance from a path"
                                     " requires a source node option",
                                     errors.ECODE_INVAL)
      else:
        self.op.src_node = src_node = _ExpandNodeName(self.cfg, src_node)
        if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
          self.needed_locks[locking.LEVEL_NODE].append(src_node)
        if not os.path.isabs(src_path):
          self.op.src_path = src_path = \
            utils.PathJoin(pathutils.EXPORT_DIR, src_path)

    self.needed_locks[locking.LEVEL_NODE_RES] = \
      _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    if self.op.opportunistic_locking:
      # Only consider nodes for which a lock is held
      node_whitelist = list(self.owned_locks(locking.LEVEL_NODE))
    else:
      node_whitelist = None

    #TODO Export network to iallocator so that it chooses a pnode
    #     in a nodegroup that has the desired network connected to
    req = _CreateInstanceAllocRequest(self.op, self.disks,
                                      self.nics, self.be_full,
                                      node_whitelist)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      # When opportunistic locks are used only a temporary failure is generated
      if self.op.opportunistic_locking:
        ecode = errors.ECODE_TEMP_NORES
      else:
        ecode = errors.ECODE_NORES

      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 ecode)

    self.op.pnode = ial.result[0]
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(ial.result))

    assert req.RequiredNodes() in (1, 2), "Wrong node count from iallocator"

    if req.RequiredNodes() == 2:
      self.op.snode = ial.result[1]

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "ADD_MODE": self.op.mode,
      }
    if self.op.mode == constants.INSTANCE_IMPORT:
      env["SRC_NODE"] = self.op.src_node
      env["SRC_PATH"] = self.op.src_path
      env["SRC_IMAGES"] = self.src_images

    env.update(_BuildInstanceHookEnv(
      name=self.op.instance_name,
      primary_node=self.op.pnode,
      secondary_nodes=self.secondaries,
      status=self.op.start,
      os_type=self.op.os_type,
      minmem=self.be_full[constants.BE_MINMEM],
      maxmem=self.be_full[constants.BE_MAXMEM],
      vcpus=self.be_full[constants.BE_VCPUS],
      nics=_NICListToTuple(self, self.nics),
      disk_template=self.op.disk_template,
      disks=[(d[constants.IDISK_NAME], d[constants.IDISK_SIZE],
              d[constants.IDISK_MODE]) for d in self.disks],
      bep=self.be_full,
      hvp=self.hv_full,
      hypervisor_name=self.op.hypervisor,
      tags=self.op.tags,
      ))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.op.pnode] + self.secondaries
    return nl, nl

  def _ReadExportInfo(self):
    """Reads the export information from disk.

    It will override the opcode source node and path with the actual
    information, if these two were not specified before.

    @return: the export information

    """
    assert self.op.mode == constants.INSTANCE_IMPORT

    src_node = self.op.src_node
    src_path = self.op.src_path

    if src_node is None:
      locked_nodes = self.owned_locks(locking.LEVEL_NODE)
      exp_list = self.rpc.call_export_list(locked_nodes)
      found = False
      for node in exp_list:
        if exp_list[node].fail_msg:
          continue
        if src_path in exp_list[node].payload:
          found = True
          self.op.src_node = src_node = node
          self.op.src_path = src_path = utils.PathJoin(pathutils.EXPORT_DIR,
                                                       src_path)
          break
      if not found:
        raise errors.OpPrereqError("No export found for relative path %s" %
                                   src_path, errors.ECODE_INVAL)

    _CheckNodeOnline(self, src_node)
    result = self.rpc.call_export_info(src_node, src_path)
    result.Raise("No export or invalid export found in dir %s" % src_path)

    export_info = objects.SerializableConfigParser.Loads(str(result.payload))
    if not export_info.has_section(constants.INISECT_EXP):
      raise errors.ProgrammerError("Corrupted export config",
                                   errors.ECODE_ENVIRON)

    ei_version = export_info.get(constants.INISECT_EXP, "version")
    if (int(ei_version) != constants.EXPORT_VERSION):
      raise errors.OpPrereqError("Wrong export version %s (wanted %d)" %
                                 (ei_version, constants.EXPORT_VERSION),
                                 errors.ECODE_ENVIRON)
    return export_info

  def _ReadExportParams(self, einfo):
    """Use export parameters as defaults.

    In case the opcode doesn't specify (as in override) some instance
    parameters, then try to use them from the export information, if
    that declares them.

    """
    self.op.os_type = einfo.get(constants.INISECT_EXP, "os")

    if self.op.disk_template is None:
      if einfo.has_option(constants.INISECT_INS, "disk_template"):
        self.op.disk_template = einfo.get(constants.INISECT_INS,
                                          "disk_template")
        if self.op.disk_template not in constants.DISK_TEMPLATES:
          raise errors.OpPrereqError("Disk template specified in configuration"
                                     " file is not one of the allowed values:"
                                     " %s" %
                                     " ".join(constants.DISK_TEMPLATES),
                                     errors.ECODE_INVAL)
      else:
        raise errors.OpPrereqError("No disk template specified and the export"
                                   " is missing the disk_template information",
                                   errors.ECODE_INVAL)

    if not self.op.disks:
      disks = []
      # TODO: import the disk iv_name too
      for idx in range(constants.MAX_DISKS):
        if einfo.has_option(constants.INISECT_INS, "disk%d_size" % idx):
          disk_sz = einfo.getint(constants.INISECT_INS, "disk%d_size" % idx)
          disks.append({constants.IDISK_SIZE: disk_sz})
      self.op.disks = disks
      if not disks and self.op.disk_template != constants.DT_DISKLESS:
        raise errors.OpPrereqError("No disk info specified and the export"
                                   " is missing the disk information",
                                   errors.ECODE_INVAL)

    if not self.op.nics:
      nics = []
      for idx in range(constants.MAX_NICS):
        if einfo.has_option(constants.INISECT_INS, "nic%d_mac" % idx):
          ndict = {}
          for name in list(constants.NICS_PARAMETERS) + ["ip", "mac"]:
            v = einfo.get(constants.INISECT_INS, "nic%d_%s" % (idx, name))
            ndict[name] = v
          nics.append(ndict)
        else:
          break
      self.op.nics = nics

    if not self.op.tags and einfo.has_option(constants.INISECT_INS, "tags"):
      self.op.tags = einfo.get(constants.INISECT_INS, "tags").split()

    if (self.op.hypervisor is None and
        einfo.has_option(constants.INISECT_INS, "hypervisor")):
      self.op.hypervisor = einfo.get(constants.INISECT_INS, "hypervisor")

    if einfo.has_section(constants.INISECT_HYP):
      # use the export parameters but do not override the ones
      # specified by the user
      for name, value in einfo.items(constants.INISECT_HYP):
        if name not in self.op.hvparams:
          self.op.hvparams[name] = value

    if einfo.has_section(constants.INISECT_BEP):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_BEP):
        if name not in self.op.beparams:
          self.op.beparams[name] = value
        # Compatibility for the old "memory" be param
        if name == constants.BE_MEMORY:
          if constants.BE_MAXMEM not in self.op.beparams:
            self.op.beparams[constants.BE_MAXMEM] = value
          if constants.BE_MINMEM not in self.op.beparams:
            self.op.beparams[constants.BE_MINMEM] = value
    else:
      # try to read the parameters old style, from the main section
      for name in constants.BES_PARAMETERS:
        if (name not in self.op.beparams and
            einfo.has_option(constants.INISECT_INS, name)):
          self.op.beparams[name] = einfo.get(constants.INISECT_INS, name)

    if einfo.has_section(constants.INISECT_OSP):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_OSP):
        if name not in self.op.osparams:
          self.op.osparams[name] = value

  def _RevertToDefaults(self, cluster):
    """Revert the instance parameters to the default values.

    """
    # hvparams
    hv_defs = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type, {})
    for name in self.op.hvparams.keys():
      if name in hv_defs and hv_defs[name] == self.op.hvparams[name]:
        del self.op.hvparams[name]
    # beparams
    be_defs = cluster.SimpleFillBE({})
    for name in self.op.beparams.keys():
      if name in be_defs and be_defs[name] == self.op.beparams[name]:
        del self.op.beparams[name]
    # nic params
    nic_defs = cluster.SimpleFillNIC({})
    for nic in self.op.nics:
      for name in constants.NICS_PARAMETERS:
        if name in nic and name in nic_defs and nic[name] == nic_defs[name]:
          del nic[name]
    # osparams
    os_defs = cluster.SimpleFillOS(self.op.os_type, {})
    for name in self.op.osparams.keys():
      if name in os_defs and os_defs[name] == self.op.osparams[name]:
        del self.op.osparams[name]

  def _CalculateFileStorageDir(self):
    """Calculate final instance file storage dir.

    """
    # file storage dir calculation/check
    self.instance_file_storage_dir = None
    if self.op.disk_template in constants.DTS_FILEBASED:
      # build the full file storage dir path
      joinargs = []

      if self.op.disk_template == constants.DT_SHARED_FILE:
        get_fsd_fn = self.cfg.GetSharedFileStorageDir
      else:
        get_fsd_fn = self.cfg.GetFileStorageDir

      cfg_storagedir = get_fsd_fn()
      if not cfg_storagedir:
        raise errors.OpPrereqError("Cluster file storage dir not defined",
                                   errors.ECODE_STATE)
      joinargs.append(cfg_storagedir)

      if self.op.file_storage_dir is not None:
        joinargs.append(self.op.file_storage_dir)

      joinargs.append(self.op.instance_name)

      # pylint: disable=W0142
      self.instance_file_storage_dir = utils.PathJoin(*joinargs)

  def CheckPrereq(self): # pylint: disable=R0914
    """Check prerequisites.

    """
    self._CalculateFileStorageDir()

    if self.op.mode == constants.INSTANCE_IMPORT:
      export_info = self._ReadExportInfo()
      self._ReadExportParams(export_info)
      self._old_instance_name = export_info.get(constants.INISECT_INS, "name")
    else:
      self._old_instance_name = None

    if (not self.cfg.GetVGName() and
        self.op.disk_template not in constants.DTS_NOT_LVM):
      raise errors.OpPrereqError("Cluster does not support lvm-based"
                                 " instances", errors.ECODE_STATE)

    if (self.op.hypervisor is None or
        self.op.hypervisor == constants.VALUE_AUTO):
      self.op.hypervisor = self.cfg.GetHypervisorType()

    cluster = self.cfg.GetClusterInfo()
    enabled_hvs = cluster.enabled_hypervisors
    if self.op.hypervisor not in enabled_hvs:
      raise errors.OpPrereqError("Selected hypervisor (%s) not enabled in the"
                                 " cluster (%s)" %
                                 (self.op.hypervisor, ",".join(enabled_hvs)),
                                 errors.ECODE_STATE)

    # Check tag validity
    for tag in self.op.tags:
      objects.TaggableObject.ValidateTag(tag)

    # check hypervisor parameter syntax (locally)
    utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
    filled_hvp = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type,
                                      self.op.hvparams)
    hv_type = hypervisor.GetHypervisorClass(self.op.hypervisor)
    hv_type.CheckParameterSyntax(filled_hvp)
    self.hv_full = filled_hvp
    # check that we don't specify global parameters on an instance
    _CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS, "hypervisor",
                          "instance", "cluster")

    # fill and remember the beparams dict
    self.be_full = _ComputeFullBeParams(self.op, cluster)

    # build os parameters
    self.os_full = cluster.SimpleFillOS(self.op.os_type, self.op.osparams)

    # now that hvp/bep are in final format, let's reset to defaults,
    # if told to do so
    if self.op.identify_defaults:
      self._RevertToDefaults(cluster)

    # NIC buildup
    self.nics = _ComputeNics(self.op, cluster, self.check_ip, self.cfg,
                             self.proc.GetECId())

    # disk checks/pre-build
    default_vg = self.cfg.GetVGName()
    self.disks = _ComputeDisks(self.op, default_vg)

    if self.op.mode == constants.INSTANCE_IMPORT:
      disk_images = []
      for idx in range(len(self.disks)):
        option = "disk%d_dump" % idx
        if export_info.has_option(constants.INISECT_INS, option):
          # FIXME: are the old os-es, disk sizes, etc. useful?
          export_name = export_info.get(constants.INISECT_INS, option)
          image = utils.PathJoin(self.op.src_path, export_name)
          disk_images.append(image)
        else:
          disk_images.append(False)

      self.src_images = disk_images

      if self.op.instance_name == self._old_instance_name:
        for idx, nic in enumerate(self.nics):
          if nic.mac == constants.VALUE_AUTO:
            nic_mac_ini = "nic%d_mac" % idx
            nic.mac = export_info.get(constants.INISECT_INS, nic_mac_ini)

    # ENDIF: self.op.mode == constants.INSTANCE_IMPORT

    # ip ping checks (we use the same ip that was resolved in ExpandNames)
    if self.op.ip_check:
      if netutils.TcpPing(self.check_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (self.check_ip, self.op.instance_name),
                                   errors.ECODE_NOTUNIQUE)

    #### mac address generation
    # By generating here the mac address both the allocator and the hooks get
    # the real final mac address rather than the 'auto' or 'generate' value.
    # There is a race condition between the generation and the instance object
    # creation, which means that we know the mac is valid now, but we're not
    # sure it will be when we actually add the instance. If things go bad
    # adding the instance will abort because of a duplicate mac, and the
    # creation job will fail.
    for nic in self.nics:
      if nic.mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        nic.mac = self.cfg.GenerateMAC(nic.network, self.proc.GetECId())

    #### allocator run

    if self.op.iallocator is not None:
      self._RunAllocator()

    # Release all unneeded node locks
    keep_locks = filter(None, [self.op.pnode, self.op.snode, self.op.src_node])
    _ReleaseLocks(self, locking.LEVEL_NODE, keep=keep_locks)
    _ReleaseLocks(self, locking.LEVEL_NODE_RES, keep=keep_locks)
    _ReleaseLocks(self, locking.LEVEL_NODE_ALLOC)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES)), \
      "Node locks differ from node resource locks"

    #### node related checks

    # check primary node
    self.pnode = pnode = self.cfg.GetNodeInfo(self.op.pnode)
    assert self.pnode is not None, \
      "Cannot retrieve locked node %s" % self.op.pnode
    if pnode.offline:
      raise errors.OpPrereqError("Cannot use offline primary node '%s'" %
                                 pnode.name, errors.ECODE_STATE)
    if pnode.drained:
      raise errors.OpPrereqError("Cannot use drained primary node '%s'" %
                                 pnode.name, errors.ECODE_STATE)
    if not pnode.vm_capable:
      raise errors.OpPrereqError("Cannot use non-vm_capable primary node"
                                 " '%s'" % pnode.name, errors.ECODE_STATE)

    self.secondaries = []

    # Fill in any IPs from IP pools. This must happen here, because we need to
    # know the nic's primary node, as specified by the iallocator
    for idx, nic in enumerate(self.nics):
      net_uuid = nic.network
      if net_uuid is not None:
        nobj = self.cfg.GetNetwork(net_uuid)
        netparams = self.cfg.GetGroupNetParams(net_uuid, self.pnode.name)
        if netparams is None:
          raise errors.OpPrereqError("No netparams found for network"
                                     " %s. Propably not connected to"
                                     " node's %s nodegroup" %
                                     (nobj.name, self.pnode.name),
                                     errors.ECODE_INVAL)
        self.LogInfo("NIC/%d inherits netparams %s" %
                     (idx, netparams.values()))
        nic.nicparams = dict(netparams)
        if nic.ip is not None:
          if nic.ip.lower() == constants.NIC_IP_POOL:
            try:
              nic.ip = self.cfg.GenerateIp(net_uuid, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("Unable to get a free IP for NIC %d"
                                         " from the address pool" % idx,
                                         errors.ECODE_STATE)
            self.LogInfo("Chose IP %s from network %s", nic.ip, nobj.name)
          else:
            try:
              self.cfg.ReserveIp(net_uuid, nic.ip, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("IP address %s already in use"
                                         " or does not belong to network %s" %
                                         (nic.ip, nobj.name),
                                         errors.ECODE_NOTUNIQUE)

      # net is None, ip None or given
      elif self.op.conflicts_check:
        _CheckForConflictingIp(self, nic.ip, self.pnode.name)

    # mirror node verification
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.snode == pnode.name:
        raise errors.OpPrereqError("The secondary node cannot be the"
                                   " primary node", errors.ECODE_INVAL)
      _CheckNodeOnline(self, self.op.snode)
      _CheckNodeNotDrained(self, self.op.snode)
      _CheckNodeVmCapable(self, self.op.snode)
      self.secondaries.append(self.op.snode)

      snode = self.cfg.GetNodeInfo(self.op.snode)
      if pnode.group != snode.group:
        self.LogWarning("The primary and secondary nodes are in two"
                        " different node groups; the disk parameters"
                        " from the first disk's node group will be"
                        " used")

    if not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      nodes = [pnode]
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        nodes.append(snode)
      has_es = lambda n: _IsExclusiveStorageEnabledNode(self.cfg, n)
      if compat.any(map(has_es, nodes)):
        raise errors.OpPrereqError("Disk template %s not supported with"
                                   " exclusive storage" % self.op.disk_template,
                                   errors.ECODE_STATE)

    nodenames = [pnode.name] + self.secondaries

    if not self.adopt_disks:
      if self.op.disk_template == constants.DT_RBD:
        # _CheckRADOSFreeSpace() is just a placeholder.
        # Any function that checks prerequisites can be placed here.
        # Check if there is enough space on the RADOS cluster.
        _CheckRADOSFreeSpace()
      elif self.op.disk_template == constants.DT_EXT:
        # FIXME: Function that checks prereqs if needed
        pass
      else:
        # Check lv size requirements, if not adopting
        req_sizes = _ComputeDiskSizePerVG(self.op.disk_template, self.disks)
        _CheckNodesFreeDiskPerVG(self, nodenames, req_sizes)

    elif self.op.disk_template == constants.DT_PLAIN: # Check the adoption data
      all_lvs = set(["%s/%s" % (disk[constants.IDISK_VG],
                                disk[constants.IDISK_ADOPT])
                     for disk in self.disks])
      if len(all_lvs) != len(self.disks):
        raise errors.OpPrereqError("Duplicate volume names given for adoption",
                                   errors.ECODE_INVAL)
      for lv_name in all_lvs:
        try:
          # FIXME: lv_name here is "vg/lv" need to ensure that other calls
          # to ReserveLV uses the same syntax
          self.cfg.ReserveLV(lv_name, self.proc.GetECId())
        except errors.ReservationError:
          raise errors.OpPrereqError("LV named %s used by another instance" %
                                     lv_name, errors.ECODE_NOTUNIQUE)

      vg_names = self.rpc.call_vg_list([pnode.name])[pnode.name]
      vg_names.Raise("Cannot get VG information from node %s" % pnode.name)

      node_lvs = self.rpc.call_lv_list([pnode.name],
                                       vg_names.payload.keys())[pnode.name]
      node_lvs.Raise("Cannot get LV information from node %s" % pnode.name)
      node_lvs = node_lvs.payload

      delta = all_lvs.difference(node_lvs.keys())
      if delta:
        raise errors.OpPrereqError("Missing logical volume(s): %s" %
                                   utils.CommaJoin(delta),
                                   errors.ECODE_INVAL)
      online_lvs = [lv for lv in all_lvs if node_lvs[lv][2]]
      if online_lvs:
        raise errors.OpPrereqError("Online logical volumes found, cannot"
                                   " adopt: %s" % utils.CommaJoin(online_lvs),
                                   errors.ECODE_STATE)
      # update the size of disk based on what is found
      for dsk in self.disks:
        dsk[constants.IDISK_SIZE] = \
          int(float(node_lvs["%s/%s" % (dsk[constants.IDISK_VG],
                                        dsk[constants.IDISK_ADOPT])][0]))

    elif self.op.disk_template == constants.DT_BLOCK:
      # Normalize and de-duplicate device paths
      all_disks = set([os.path.abspath(disk[constants.IDISK_ADOPT])
                       for disk in self.disks])
      if len(all_disks) != len(self.disks):
        raise errors.OpPrereqError("Duplicate disk names given for adoption",
                                   errors.ECODE_INVAL)
      baddisks = [d for d in all_disks
                  if not d.startswith(constants.ADOPTABLE_BLOCKDEV_ROOT)]
      if baddisks:
        raise errors.OpPrereqError("Device node(s) %s lie outside %s and"
                                   " cannot be adopted" %
                                   (utils.CommaJoin(baddisks),
                                    constants.ADOPTABLE_BLOCKDEV_ROOT),
                                   errors.ECODE_INVAL)

      node_disks = self.rpc.call_bdev_sizes([pnode.name],
                                            list(all_disks))[pnode.name]
      node_disks.Raise("Cannot get block device information from node %s" %
                       pnode.name)
      node_disks = node_disks.payload
      delta = all_disks.difference(node_disks.keys())
      if delta:
        raise errors.OpPrereqError("Missing block device(s): %s" %
                                   utils.CommaJoin(delta),
                                   errors.ECODE_INVAL)
      for dsk in self.disks:
        dsk[constants.IDISK_SIZE] = \
          int(float(node_disks[dsk[constants.IDISK_ADOPT]]))

    # Verify instance specs
    spindle_use = self.be_full.get(constants.BE_SPINDLE_USE, None)
    ispec = {
      constants.ISPEC_MEM_SIZE: self.be_full.get(constants.BE_MAXMEM, None),
      constants.ISPEC_CPU_COUNT: self.be_full.get(constants.BE_VCPUS, None),
      constants.ISPEC_DISK_COUNT: len(self.disks),
      constants.ISPEC_DISK_SIZE: [disk[constants.IDISK_SIZE]
                                  for disk in self.disks],
      constants.ISPEC_NIC_COUNT: len(self.nics),
      constants.ISPEC_SPINDLE_USE: spindle_use,
      }

    group_info = self.cfg.GetNodeGroup(pnode.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    res = _ComputeIPolicyInstanceSpecViolation(ipolicy, ispec,
                                               self.op.disk_template)
    if not self.op.ignore_ipolicy and res:
      msg = ("Instance allocation to group %s (%s) violates policy: %s" %
             (pnode.group, group_info.name, utils.CommaJoin(res)))
      raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

    _CheckHVParams(self, nodenames, self.op.hypervisor, self.op.hvparams)

    _CheckNodeHasOS(self, pnode.name, self.op.os_type, self.op.force_variant)
    # check OS parameters (remotely)
    _CheckOSParams(self, True, nodenames, self.op.os_type, self.os_full)

    _CheckNicsBridgesExist(self, self.nics, self.pnode.name)

    #TODO: _CheckExtParams (remotely)
    # Check parameters for extstorage

    # memory check on primary node
    #TODO(dynmem): use MINMEM for checking
    if self.op.start:
      _CheckNodeFreeMemory(self, self.pnode.name,
                           "creating instance %s" % self.op.instance_name,
                           self.be_full[constants.BE_MAXMEM],
                           self.op.hypervisor)

    self.dry_run_result = list(nodenames)

  def Exec(self, feedback_fn):
    """Create and add the instance to the cluster.

    """
    instance = self.op.instance_name
    pnode_name = self.pnode.name

    assert not (self.owned_locks(locking.LEVEL_NODE_RES) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Node locks differ from node resource locks"
    assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

    ht_kind = self.op.hypervisor
    if ht_kind in constants.HTS_REQ_PORT:
      network_port = self.cfg.AllocatePort()
    else:
      network_port = None

    # This is ugly but we got a chicken-egg problem here
    # We can only take the group disk parameters, as the instance
    # has no disks yet (we are generating them right here).
    node = self.cfg.GetNodeInfo(pnode_name)
    nodegroup = self.cfg.GetNodeGroup(node.group)
    disks = _GenerateDiskTemplate(self,
                                  self.op.disk_template,
                                  instance, pnode_name,
                                  self.secondaries,
                                  self.disks,
                                  self.instance_file_storage_dir,
                                  self.op.file_driver,
                                  0,
                                  feedback_fn,
                                  self.cfg.GetGroupDiskParams(nodegroup))

    iobj = objects.Instance(name=instance, os=self.op.os_type,
                            primary_node=pnode_name,
                            nics=self.nics, disks=disks,
                            disk_template=self.op.disk_template,
                            admin_state=constants.ADMINST_DOWN,
                            network_port=network_port,
                            beparams=self.op.beparams,
                            hvparams=self.op.hvparams,
                            hypervisor=self.op.hypervisor,
                            osparams=self.op.osparams,
                            )

    if self.op.tags:
      for tag in self.op.tags:
        iobj.AddTag(tag)

    if self.adopt_disks:
      if self.op.disk_template == constants.DT_PLAIN:
        # rename LVs to the newly-generated names; we need to construct
        # 'fake' LV disks with the old data, plus the new unique_id
        tmp_disks = [objects.Disk.FromDict(v.ToDict()) for v in disks]
        rename_to = []
        for t_dsk, a_dsk in zip(tmp_disks, self.disks):
          rename_to.append(t_dsk.logical_id)
          t_dsk.logical_id = (t_dsk.logical_id[0], a_dsk[constants.IDISK_ADOPT])
          self.cfg.SetDiskID(t_dsk, pnode_name)
        result = self.rpc.call_blockdev_rename(pnode_name,
                                               zip(tmp_disks, rename_to))
        result.Raise("Failed to rename adoped LVs")
    else:
      feedback_fn("* creating instance disks...")
      try:
        _CreateDisks(self, iobj)
      except errors.OpExecError:
        self.LogWarning("Device creation failed")
        self.cfg.ReleaseDRBDMinors(instance)
        raise

    feedback_fn("adding instance %s to cluster config" % instance)

    self.cfg.AddInstance(iobj, self.proc.GetECId())

    # Declare that we don't want to remove the instance lock anymore, as we've
    # added the instance to the config
    del self.remove_locks[locking.LEVEL_INSTANCE]

    if self.op.mode == constants.INSTANCE_IMPORT:
      # Release unused nodes
      _ReleaseLocks(self, locking.LEVEL_NODE, keep=[self.op.src_node])
    else:
      # Release all nodes
      _ReleaseLocks(self, locking.LEVEL_NODE)

    disk_abort = False
    if not self.adopt_disks and self.cfg.GetClusterInfo().prealloc_wipe_disks:
      feedback_fn("* wiping instance disks...")
      try:
        _WipeDisks(self, iobj)
      except errors.OpExecError, err:
        logging.exception("Wiping disks failed")
        self.LogWarning("Wiping instance disks failed (%s)", err)
        disk_abort = True

    if disk_abort:
      # Something is already wrong with the disks, don't do anything else
      pass
    elif self.op.wait_for_sync:
      disk_abort = not _WaitForSync(self, iobj)
    elif iobj.disk_template in constants.DTS_INT_MIRROR:
      # make sure the disks are not degraded (still sync-ing is ok)
      feedback_fn("* checking mirrors status")
      disk_abort = not _WaitForSync(self, iobj, oneshot=True)
    else:
      disk_abort = False

    if disk_abort:
      _RemoveDisks(self, iobj)
      self.cfg.RemoveInstance(iobj.name)
      # Make sure the instance lock gets removed
      self.remove_locks[locking.LEVEL_INSTANCE] = iobj.name
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance")

    # Release all node resource locks
    _ReleaseLocks(self, locking.LEVEL_NODE_RES)

    if iobj.disk_template != constants.DT_DISKLESS and not self.adopt_disks:
      # we need to set the disks ID to the primary node, since the
      # preceding code might or might have not done it, depending on
      # disk template and other options
      for disk in iobj.disks:
        self.cfg.SetDiskID(disk, pnode_name)
      if self.op.mode == constants.INSTANCE_CREATE:
        if not self.op.no_install:
          pause_sync = (iobj.disk_template in constants.DTS_INT_MIRROR and
                        not self.op.wait_for_sync)
          if pause_sync:
            feedback_fn("* pausing disk sync to install instance OS")
            result = self.rpc.call_blockdev_pause_resume_sync(pnode_name,
                                                              (iobj.disks,
                                                               iobj), True)
            for idx, success in enumerate(result.payload):
              if not success:
                logging.warn("pause-sync of instance %s for disk %d failed",
                             instance, idx)

          feedback_fn("* running the instance OS create scripts...")
          # FIXME: pass debug option from opcode to backend
          os_add_result = \
            self.rpc.call_instance_os_add(pnode_name, (iobj, None), False,
                                          self.op.debug_level)
          if pause_sync:
            feedback_fn("* resuming disk sync")
            result = self.rpc.call_blockdev_pause_resume_sync(pnode_name,
                                                              (iobj.disks,
                                                               iobj), False)
            for idx, success in enumerate(result.payload):
              if not success:
                logging.warn("resume-sync of instance %s for disk %d failed",
                             instance, idx)

          os_add_result.Raise("Could not add os for instance %s"
                              " on node %s" % (instance, pnode_name))

      else:
        if self.op.mode == constants.INSTANCE_IMPORT:
          feedback_fn("* running the instance OS import scripts...")

          transfers = []

          for idx, image in enumerate(self.src_images):
            if not image:
              continue

            # FIXME: pass debug option from opcode to backend
            dt = masterd.instance.DiskTransfer("disk/%s" % idx,
                                               constants.IEIO_FILE, (image, ),
                                               constants.IEIO_SCRIPT,
                                               (iobj.disks[idx], idx),
                                               None)
            transfers.append(dt)

          import_result = \
            masterd.instance.TransferInstanceData(self, feedback_fn,
                                                  self.op.src_node, pnode_name,
                                                  self.pnode.secondary_ip,
                                                  iobj, transfers)
          if not compat.all(import_result):
            self.LogWarning("Some disks for instance %s on node %s were not"
                            " imported successfully" % (instance, pnode_name))

          rename_from = self._old_instance_name

        elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
          feedback_fn("* preparing remote import...")
          # The source cluster will stop the instance before attempting to make
          # a connection. In some cases stopping an instance can take a long
          # time, hence the shutdown timeout is added to the connection
          # timeout.
          connect_timeout = (constants.RIE_CONNECT_TIMEOUT +
                             self.op.source_shutdown_timeout)
          timeouts = masterd.instance.ImportExportTimeouts(connect_timeout)

          assert iobj.primary_node == self.pnode.name
          disk_results = \
            masterd.instance.RemoteImport(self, feedback_fn, iobj, self.pnode,
                                          self.source_x509_ca,
                                          self._cds, timeouts)
          if not compat.all(disk_results):
            # TODO: Should the instance still be started, even if some disks
            # failed to import (valid for local imports, too)?
            self.LogWarning("Some disks for instance %s on node %s were not"
                            " imported successfully" % (instance, pnode_name))

          rename_from = self.source_instance_name

        else:
          # also checked in the prereq part
          raise errors.ProgrammerError("Unknown OS initialization mode '%s'"
                                       % self.op.mode)

        # Run rename script on newly imported instance
        assert iobj.name == instance
        feedback_fn("Running rename script for %s" % instance)
        result = self.rpc.call_instance_run_rename(pnode_name, iobj,
                                                   rename_from,
                                                   self.op.debug_level)
        if result.fail_msg:
          self.LogWarning("Failed to run rename script for %s on node"
                          " %s: %s" % (instance, pnode_name, result.fail_msg))

    assert not self.owned_locks(locking.LEVEL_NODE_RES)

    if self.op.start:
      iobj.admin_state = constants.ADMINST_UP
      self.cfg.Update(iobj, feedback_fn)
      logging.info("Starting instance %s on node %s", instance, pnode_name)
      feedback_fn("* starting instance...")
      result = self.rpc.call_instance_start(pnode_name, (iobj, None, None),
                                            False, self.op.reason)
      result.Raise("Could not start instance")

    return list(iobj.all_nodes)


class LUInstanceRename(LogicalUnit):
  """Rename an instance.

  """
  HPATH = "instance-rename"
  HTYPE = constants.HTYPE_INSTANCE

  def CheckArguments(self):
    """Check arguments.

    """
    if self.op.ip_check and not self.op.name_check:
      # TODO: make the ip check more flexible and not depend on the name check
      raise errors.OpPrereqError("IP address check requires a name check",
                                 errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["INSTANCE_NEW_NAME"] = self.op.new_name
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    self.op.instance_name = _ExpandInstanceName(self.cfg,
                                                self.op.instance_name)
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None
    _CheckNodeOnline(self, instance.primary_node)
    _CheckInstanceState(self, instance, INSTANCE_NOT_RUNNING,
                        msg="cannot rename")
    self.instance = instance

    new_name = self.op.new_name
    if self.op.name_check:
      hostname = _CheckHostnameSane(self, new_name)
      new_name = self.op.new_name = hostname.name
      if (self.op.ip_check and
          netutils.TcpPing(hostname.ip, constants.DEFAULT_NODED_PORT)):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (hostname.ip, new_name),
                                   errors.ECODE_NOTUNIQUE)

    instance_list = self.cfg.GetInstanceList()
    if new_name in instance_list and new_name != instance.name:
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 new_name, errors.ECODE_EXISTS)

  def Exec(self, feedback_fn):
    """Rename the instance.

    """
    inst = self.instance
    old_name = inst.name

    rename_file_storage = False
    if (inst.disk_template in constants.DTS_FILEBASED and
        self.op.new_name != inst.name):
      old_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])
      rename_file_storage = True

    self.cfg.RenameInstance(inst.name, self.op.new_name)
    # Change the instance lock. This is definitely safe while we hold the BGL.
    # Otherwise the new lock would have to be added in acquired mode.
    assert self.REQ_BGL
    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER)
    self.glm.remove(locking.LEVEL_INSTANCE, old_name)
    self.glm.add(locking.LEVEL_INSTANCE, self.op.new_name)

    # re-read the instance from the configuration after rename
    inst = self.cfg.GetInstanceInfo(self.op.new_name)

    if rename_file_storage:
      new_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])
      result = self.rpc.call_file_storage_dir_rename(inst.primary_node,
                                                     old_file_storage_dir,
                                                     new_file_storage_dir)
      result.Raise("Could not rename on node %s directory '%s' to '%s'"
                   " (but the instance has been renamed in Ganeti)" %
                   (inst.primary_node, old_file_storage_dir,
                    new_file_storage_dir))

    _StartInstanceDisks(self, inst, None)
    # update info on disks
    info = _GetInstanceInfoText(inst)
    for (idx, disk) in enumerate(inst.disks):
      for node in inst.all_nodes:
        self.cfg.SetDiskID(disk, node)
        result = self.rpc.call_blockdev_setinfo(node, disk, info)
        if result.fail_msg:
          self.LogWarning("Error setting info on node %s for disk %s: %s",
                          node, idx, result.fail_msg)
    try:
      result = self.rpc.call_instance_run_rename(inst.primary_node, inst,
                                                 old_name, self.op.debug_level)
      msg = result.fail_msg
      if msg:
        msg = ("Could not run OS rename script for instance %s on node %s"
               " (but the instance has been renamed in Ganeti): %s" %
               (inst.name, inst.primary_node, msg))
        self.LogWarning(msg)
    finally:
      _ShutdownInstanceDisks(self, inst)

    return inst.name


class LUInstanceRemove(LogicalUnit):
  """Remove an instance.

  """
  HPATH = "instance-remove"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["SHUTDOWN_TIMEOUT"] = self.op.shutdown_timeout
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()]
    nl_post = list(self.instance.all_nodes) + nl
    return (nl, nl_post)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

  def Exec(self, feedback_fn):
    """Remove the instance.

    """
    instance = self.instance
    logging.info("Shutting down instance %s on node %s",
                 instance.name, instance.primary_node)

    result = self.rpc.call_instance_shutdown(instance.primary_node, instance,
                                             self.op.shutdown_timeout,
                                             self.op.reason)
    msg = result.fail_msg
    if msg:
      if self.op.ignore_failures:
        feedback_fn("Warning: can't shutdown instance: %s" % msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, instance.primary_node, msg))

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))
    assert not (set(instance.all_nodes) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Not owning correct locks"

    _RemoveInstance(self, feedback_fn, instance, self.op.ignore_failures)


def _CheckInstanceBridgesExist(lu, instance, node=None):
  """Check that the brigdes needed by an instance exist.

  """
  if node is None:
    node = instance.primary_node
  _CheckNicsBridgesExist(lu, instance.nics, node)


class LUInstanceMove(LogicalUnit):
  """Move an instance by data-copying.

  """
  HPATH = "instance-move"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    target_node = _ExpandNodeName(self.cfg, self.op.target_node)
    self.op.target_node = target_node
    self.needed_locks[locking.LEVEL_NODE] = [target_node]
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes(primary_only=True)
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "TARGET_NODE": self.op.target_node,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [
      self.cfg.GetMasterNode(),
      self.instance.primary_node,
      self.op.target_node,
      ]
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if instance.disk_template not in constants.DTS_COPYABLE:
      raise errors.OpPrereqError("Disk template %s not suitable for copying" %
                                 instance.disk_template, errors.ECODE_STATE)

    node = self.cfg.GetNodeInfo(self.op.target_node)
    assert node is not None, \
      "Cannot retrieve locked node %s" % self.op.target_node

    self.target_node = target_node = node.name

    if target_node == instance.primary_node:
      raise errors.OpPrereqError("Instance %s is already on the node %s" %
                                 (instance.name, target_node),
                                 errors.ECODE_STATE)

    bep = self.cfg.GetClusterInfo().FillBE(instance)

    for idx, dsk in enumerate(instance.disks):
      if dsk.dev_type not in (constants.LD_LV, constants.LD_FILE):
        raise errors.OpPrereqError("Instance disk %d has a complex layout,"
                                   " cannot copy" % idx, errors.ECODE_STATE)

    _CheckNodeOnline(self, target_node)
    _CheckNodeNotDrained(self, target_node)
    _CheckNodeVmCapable(self, target_node)
    cluster = self.cfg.GetClusterInfo()
    group_info = self.cfg.GetNodeGroup(node.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    _CheckTargetNodeIPolicy(self, ipolicy, instance, node, self.cfg,
                            ignore=self.op.ignore_ipolicy)

    if instance.admin_state == constants.ADMINST_UP:
      # check memory requirements on the secondary node
      _CheckNodeFreeMemory(self, target_node,
                           "failing over instance %s" %
                           instance.name, bep[constants.BE_MAXMEM],
                           instance.hypervisor)
    else:
      self.LogInfo("Not checking memory on the secondary node as"
                   " instance will not be started")

    # check bridge existance
    _CheckInstanceBridgesExist(self, instance, node=target_node)

  def Exec(self, feedback_fn):
    """Move an instance.

    The move is done by shutting it down on its present node, copying
    the data over (slow) and starting it on the new node.

    """
    instance = self.instance

    source_node = instance.primary_node
    target_node = self.target_node

    self.LogInfo("Shutting down instance %s on source node %s",
                 instance.name, source_node)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    result = self.rpc.call_instance_shutdown(source_node, instance,
                                             self.op.shutdown_timeout,
                                             self.op.reason)
    msg = result.fail_msg
    if msg:
      if self.op.ignore_consistency:
        self.LogWarning("Could not shutdown instance %s on node %s."
                        " Proceeding anyway. Please make sure node"
                        " %s is down. Error details: %s",
                        instance.name, source_node, source_node, msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, source_node, msg))

    # create the target disks
    try:
      _CreateDisks(self, instance, target_node=target_node)
    except errors.OpExecError:
      self.LogWarning("Device creation failed")
      self.cfg.ReleaseDRBDMinors(instance.name)
      raise

    cluster_name = self.cfg.GetClusterInfo().cluster_name

    errs = []
    # activate, get path, copy the data over
    for idx, disk in enumerate(instance.disks):
      self.LogInfo("Copying data for disk %d", idx)
      result = self.rpc.call_blockdev_assemble(target_node, (disk, instance),
                                               instance.name, True, idx)
      if result.fail_msg:
        self.LogWarning("Can't assemble newly created disk %d: %s",
                        idx, result.fail_msg)
        errs.append(result.fail_msg)
        break
      dev_path = result.payload
      result = self.rpc.call_blockdev_export(source_node, (disk, instance),
                                             target_node, dev_path,
                                             cluster_name)
      if result.fail_msg:
        self.LogWarning("Can't copy data over for disk %d: %s",
                        idx, result.fail_msg)
        errs.append(result.fail_msg)
        break

    if errs:
      self.LogWarning("Some disks failed to copy, aborting")
      try:
        _RemoveDisks(self, instance, target_node=target_node)
      finally:
        self.cfg.ReleaseDRBDMinors(instance.name)
        raise errors.OpExecError("Errors during disk copy: %s" %
                                 (",".join(errs),))

    instance.primary_node = target_node
    self.cfg.Update(instance, feedback_fn)

    self.LogInfo("Removing the disks on the original node")
    _RemoveDisks(self, instance, target_node=source_node)

    # Only start the instance if it's marked as up
    if instance.admin_state == constants.ADMINST_UP:
      self.LogInfo("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, _ = _AssembleInstanceDisks(self, instance,
                                           ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      result = self.rpc.call_instance_start(target_node,
                                            (instance, None, None), False,
                                            self.op.reason)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (instance.name, target_node, msg))


def _GetInstanceConsole(cluster, instance):
  """Returns console information for an instance.

  @type cluster: L{objects.Cluster}
  @type instance: L{objects.Instance}
  @rtype: dict

  """
  hyper = hypervisor.GetHypervisorClass(instance.hypervisor)
  # beparams and hvparams are passed separately, to avoid editing the
  # instance and then saving the defaults in the instance itself.
  hvparams = cluster.FillHV(instance)
  beparams = cluster.FillBE(instance)
  console = hyper.GetInstanceConsole(instance, hvparams, beparams)

  assert console.instance == instance.name
  assert console.Validate()

  return console.ToDict()


class _InstanceQuery(_QueryBase):
  FIELDS = query.INSTANCE_FIELDS

  def ExpandNames(self, lu):
    lu.needed_locks = {}
    lu.share_locks = _ShareAll()

    if self.names:
      self.wanted = _GetWantedInstances(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = (self.use_locking and
                       query.IQ_LIVE in self.requested_data)
    if self.do_locking:
      lu.needed_locks[locking.LEVEL_INSTANCE] = self.wanted
      lu.needed_locks[locking.LEVEL_NODEGROUP] = []
      lu.needed_locks[locking.LEVEL_NODE] = []
      lu.needed_locks[locking.LEVEL_NETWORK] = []
      lu.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

    self.do_grouplocks = (self.do_locking and
                          query.IQ_NODES in self.requested_data)

  def DeclareLocks(self, lu, level):
    if self.do_locking:
      if level == locking.LEVEL_NODEGROUP and self.do_grouplocks:
        assert not lu.needed_locks[locking.LEVEL_NODEGROUP]

        # Lock all groups used by instances optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        lu.needed_locks[locking.LEVEL_NODEGROUP] = \
          set(group_uuid
              for instance_name in lu.owned_locks(locking.LEVEL_INSTANCE)
              for group_uuid in lu.cfg.GetInstanceNodeGroups(instance_name))
      elif level == locking.LEVEL_NODE:
        lu._LockInstancesNodes() # pylint: disable=W0212

      elif level == locking.LEVEL_NETWORK:
        lu.needed_locks[locking.LEVEL_NETWORK] = \
          frozenset(net_uuid
                    for instance_name in lu.owned_locks(locking.LEVEL_INSTANCE)
                    for net_uuid in lu.cfg.GetInstanceNetworks(instance_name))

  @staticmethod
  def _CheckGroupLocks(lu):
    owned_instances = frozenset(lu.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(lu.owned_locks(locking.LEVEL_NODEGROUP))

    # Check if node groups for locked instances are still correct
    for instance_name in owned_instances:
      _CheckInstanceNodeGroups(lu.cfg, instance_name, owned_groups)

  def _GetQueryData(self, lu):
    """Computes the list of instances and their attributes.

    """
    if self.do_grouplocks:
      self._CheckGroupLocks(lu)

    cluster = lu.cfg.GetClusterInfo()
    all_info = lu.cfg.GetAllInstancesInfo()

    instance_names = self._GetNames(lu, all_info.keys(), locking.LEVEL_INSTANCE)

    instance_list = [all_info[name] for name in instance_names]
    nodes = frozenset(itertools.chain(*(inst.all_nodes
                                        for inst in instance_list)))
    hv_list = list(set([inst.hypervisor for inst in instance_list]))
    bad_nodes = []
    offline_nodes = []
    wrongnode_inst = set()

    # Gather data as requested
    if self.requested_data & set([query.IQ_LIVE, query.IQ_CONSOLE]):
      live_data = {}
      node_data = lu.rpc.call_all_instances_info(nodes, hv_list)
      for name in nodes:
        result = node_data[name]
        if result.offline:
          # offline nodes will be in both lists
          assert result.fail_msg
          offline_nodes.append(name)
        if result.fail_msg:
          bad_nodes.append(name)
        elif result.payload:
          for inst in result.payload:
            if inst in all_info:
              if all_info[inst].primary_node == name:
                live_data.update(result.payload)
              else:
                wrongnode_inst.add(inst)
            else:
              # orphan instance; we don't list it here as we don't
              # handle this case yet in the output of instance listing
              logging.warning("Orphan instance '%s' found on node %s",
                              inst, name)
              # else no instance is alive
    else:
      live_data = {}

    if query.IQ_DISKUSAGE in self.requested_data:
      gmi = ganeti.masterd.instance
      disk_usage = dict((inst.name,
                         gmi.ComputeDiskSize(inst.disk_template,
                                             [{constants.IDISK_SIZE: disk.size}
                                              for disk in inst.disks]))
                        for inst in instance_list)
    else:
      disk_usage = None

    if query.IQ_CONSOLE in self.requested_data:
      consinfo = {}
      for inst in instance_list:
        if inst.name in live_data:
          # Instance is running
          consinfo[inst.name] = _GetInstanceConsole(cluster, inst)
        else:
          consinfo[inst.name] = None
      assert set(consinfo.keys()) == set(instance_names)
    else:
      consinfo = None

    if query.IQ_NODES in self.requested_data:
      node_names = set(itertools.chain(*map(operator.attrgetter("all_nodes"),
                                            instance_list)))
      nodes = dict(lu.cfg.GetMultiNodeInfo(node_names))
      groups = dict((uuid, lu.cfg.GetNodeGroup(uuid))
                    for uuid in set(map(operator.attrgetter("group"),
                                        nodes.values())))
    else:
      nodes = None
      groups = None

    if query.IQ_NETWORKS in self.requested_data:
      net_uuids = itertools.chain(*(lu.cfg.GetInstanceNetworks(i.name)
                                    for i in instance_list))
      networks = dict((uuid, lu.cfg.GetNetwork(uuid)) for uuid in net_uuids)
    else:
      networks = None

    return query.InstanceQueryData(instance_list, lu.cfg.GetClusterInfo(),
                                   disk_usage, offline_nodes, bad_nodes,
                                   live_data, wrongnode_inst, consinfo,
                                   nodes, groups, networks)


class LUInstanceQuery(NoHooksLU):
  """Logical unit for querying instances.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.iq = _InstanceQuery(qlang.MakeSimpleFilter("name", self.op.names),
                             self.op.output_fields, self.op.use_locking)

  def ExpandNames(self):
    self.iq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.iq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.iq.OldStyleQuery(self)


class LUInstanceQueryData(NoHooksLU):
  """Query runtime instance data.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

    # Use locking if requested or when non-static information is wanted
    if not (self.op.static or self.op.use_locking):
      self.LogWarning("Non-static data requested, locks need to be acquired")
      self.op.use_locking = True

    if self.op.instances or not self.op.use_locking:
      # Expand instance names right here
      self.wanted_names = _GetWantedInstances(self, self.op.instances)
    else:
      # Will use acquired locks
      self.wanted_names = None

    if self.op.use_locking:
      self.share_locks = _ShareAll()

      if self.wanted_names is None:
        self.needed_locks[locking.LEVEL_INSTANCE] = locking.ALL_SET
      else:
        self.needed_locks[locking.LEVEL_INSTANCE] = self.wanted_names

      self.needed_locks[locking.LEVEL_NODEGROUP] = []
      self.needed_locks[locking.LEVEL_NODE] = []
      self.needed_locks[locking.LEVEL_NETWORK] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if self.op.use_locking:
      owned_instances = self.owned_locks(locking.LEVEL_INSTANCE)
      if level == locking.LEVEL_NODEGROUP:

        # Lock all groups used by instances optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        self.needed_locks[locking.LEVEL_NODEGROUP] = \
          frozenset(group_uuid
                    for instance_name in owned_instances
                    for group_uuid in
                    self.cfg.GetInstanceNodeGroups(instance_name))

      elif level == locking.LEVEL_NODE:
        self._LockInstancesNodes()

      elif level == locking.LEVEL_NETWORK:
        self.needed_locks[locking.LEVEL_NETWORK] = \
          frozenset(net_uuid
                    for instance_name in owned_instances
                    for net_uuid in
                    self.cfg.GetInstanceNetworks(instance_name))

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))
    owned_networks = frozenset(self.owned_locks(locking.LEVEL_NETWORK))

    if self.wanted_names is None:
      assert self.op.use_locking, "Locking was not used"
      self.wanted_names = owned_instances

    instances = dict(self.cfg.GetMultiInstanceInfo(self.wanted_names))

    if self.op.use_locking:
      _CheckInstancesNodeGroups(self.cfg, instances, owned_groups, owned_nodes,
                                None)
    else:
      assert not (owned_instances or owned_groups or
                  owned_nodes or owned_networks)

    self.wanted_instances = instances.values()

  def _ComputeBlockdevStatus(self, node, instance, dev):
    """Returns the status of a block device

    """
    if self.op.static or not node:
      return None

    self.cfg.SetDiskID(dev, node)

    result = self.rpc.call_blockdev_find(node, dev)
    if result.offline:
      return None

    result.Raise("Can't compute disk status for %s" % instance.name)

    status = result.payload
    if status is None:
      return None

    return (status.dev_path, status.major, status.minor,
            status.sync_percent, status.estimated_time,
            status.is_degraded, status.ldisk_status)

  def _ComputeDiskStatus(self, instance, snode, dev):
    """Compute block device status.

    """
    (anno_dev,) = _AnnotateDiskParams(instance, [dev], self.cfg)

    return self._ComputeDiskStatusInner(instance, snode, anno_dev)

  def _ComputeDiskStatusInner(self, instance, snode, dev):
    """Compute block device status.

    @attention: The device has to be annotated already.

    """
    if dev.dev_type in constants.LDS_DRBD:
      # we change the snode then (otherwise we use the one passed in)
      if dev.logical_id[0] == instance.primary_node:
        snode = dev.logical_id[1]
      else:
        snode = dev.logical_id[0]

    dev_pstatus = self._ComputeBlockdevStatus(instance.primary_node,
                                              instance, dev)
    dev_sstatus = self._ComputeBlockdevStatus(snode, instance, dev)

    if dev.children:
      dev_children = map(compat.partial(self._ComputeDiskStatusInner,
                                        instance, snode),
                         dev.children)
    else:
      dev_children = []

    return {
      "iv_name": dev.iv_name,
      "dev_type": dev.dev_type,
      "logical_id": dev.logical_id,
      "physical_id": dev.physical_id,
      "pstatus": dev_pstatus,
      "sstatus": dev_sstatus,
      "children": dev_children,
      "mode": dev.mode,
      "size": dev.size,
      "name": dev.name,
      "uuid": dev.uuid,
      }

  def Exec(self, feedback_fn):
    """Gather and return data"""
    result = {}

    cluster = self.cfg.GetClusterInfo()

    node_names = itertools.chain(*(i.all_nodes for i in self.wanted_instances))
    nodes = dict(self.cfg.GetMultiNodeInfo(node_names))

    groups = dict(self.cfg.GetMultiNodeGroupInfo(node.group
                                                 for node in nodes.values()))

    group2name_fn = lambda uuid: groups[uuid].name
    for instance in self.wanted_instances:
      pnode = nodes[instance.primary_node]

      if self.op.static or pnode.offline:
        remote_state = None
        if pnode.offline:
          self.LogWarning("Primary node %s is marked offline, returning static"
                          " information only for instance %s" %
                          (pnode.name, instance.name))
      else:
        remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                  instance.name,
                                                  instance.hypervisor)
        remote_info.Raise("Error checking node %s" % instance.primary_node)
        remote_info = remote_info.payload
        if remote_info and "state" in remote_info:
          remote_state = "up"
        else:
          if instance.admin_state == constants.ADMINST_UP:
            remote_state = "down"
          else:
            remote_state = instance.admin_state

      disks = map(compat.partial(self._ComputeDiskStatus, instance, None),
                  instance.disks)

      snodes_group_uuids = [nodes[snode_name].group
                            for snode_name in instance.secondary_nodes]

      result[instance.name] = {
        "name": instance.name,
        "config_state": instance.admin_state,
        "run_state": remote_state,
        "pnode": instance.primary_node,
        "pnode_group_uuid": pnode.group,
        "pnode_group_name": group2name_fn(pnode.group),
        "snodes": instance.secondary_nodes,
        "snodes_group_uuids": snodes_group_uuids,
        "snodes_group_names": map(group2name_fn, snodes_group_uuids),
        "os": instance.os,
        # this happens to be the same format used for hooks
        "nics": _NICListToTuple(self, instance.nics),
        "disk_template": instance.disk_template,
        "disks": disks,
        "hypervisor": instance.hypervisor,
        "network_port": instance.network_port,
        "hv_instance": instance.hvparams,
        "hv_actual": cluster.FillHV(instance, skip_globals=True),
        "be_instance": instance.beparams,
        "be_actual": cluster.FillBE(instance),
        "os_instance": instance.osparams,
        "os_actual": cluster.SimpleFillOS(instance.os, instance.osparams),
        "serial_no": instance.serial_no,
        "mtime": instance.mtime,
        "ctime": instance.ctime,
        "uuid": instance.uuid,
        }

    return result


class LUInstanceStartup(LogicalUnit):
  """Starts an instance.

  """
  HPATH = "instance-start"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    # extra beparams
    if self.op.beparams:
      # fill the beparams dict
      objects.UpgradeBeParams(self.op.beparams)
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE_RES:
      self._LockInstancesNodes(primary_only=True, level=locking.LEVEL_NODE_RES)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "FORCE": self.op.force,
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    # extra hvparams
    if self.op.hvparams:
      # check hypervisor parameter syntax (locally)
      cluster = self.cfg.GetClusterInfo()
      utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
      filled_hvp = cluster.FillHV(instance)
      filled_hvp.update(self.op.hvparams)
      hv_type = hypervisor.GetHypervisorClass(instance.hypervisor)
      hv_type.CheckParameterSyntax(filled_hvp)
      _CheckHVParams(self, instance.all_nodes, instance.hypervisor, filled_hvp)

    _CheckInstanceState(self, instance, INSTANCE_ONLINE)

    self.primary_offline = self.cfg.GetNodeInfo(instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")

      if self.op.hvparams or self.op.beparams:
        self.LogWarning("Overridden parameters are ignored")
    else:
      _CheckNodeOnline(self, instance.primary_node)

      bep = self.cfg.GetClusterInfo().FillBE(instance)
      bep.update(self.op.beparams)

      # check bridges existence
      _CheckInstanceBridgesExist(self, instance)

      remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                instance.name,
                                                instance.hypervisor)
      remote_info.Raise("Error checking node %s" % instance.primary_node,
                        prereq=True, ecode=errors.ECODE_ENVIRON)
      if not remote_info.payload: # not running already
        _CheckNodeFreeMemory(self, instance.primary_node,
                             "starting instance %s" % instance.name,
                             bep[constants.BE_MINMEM], instance.hypervisor)

  def Exec(self, feedback_fn):
    """Start the instance.

    """
    instance = self.instance
    force = self.op.force
    reason = self.op.reason

    if not self.op.no_remember:
      self.cfg.MarkInstanceUp(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as started")
    else:
      node_current = instance.primary_node

      _StartInstanceDisks(self, instance, force)

      result = \
        self.rpc.call_instance_start(node_current,
                                     (instance, self.op.hvparams,
                                      self.op.beparams),
                                     self.op.startup_paused, reason)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance: %s" % msg)


class LUInstanceShutdown(LogicalUnit):
  """Shutdown an instance.

  """
  HPATH = "instance-stop"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["TIMEOUT"] = self.op.timeout
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if not self.op.force:
      _CheckInstanceState(self, self.instance, INSTANCE_ONLINE)
    else:
      self.LogWarning("Ignoring offline instance check")

    self.primary_offline = \
      self.cfg.GetNodeInfo(self.instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")
    else:
      _CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Shutdown the instance.

    """
    instance = self.instance
    node_current = instance.primary_node
    timeout = self.op.timeout
    reason = self.op.reason

    # If the instance is offline we shouldn't mark it as down, as that
    # resets the offline flag.
    if not self.op.no_remember and instance.admin_state in INSTANCE_ONLINE:
      self.cfg.MarkInstanceDown(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as stopped")
    else:
      result = self.rpc.call_instance_shutdown(node_current, instance, timeout,
                                               reason)
      msg = result.fail_msg
      if msg:
        self.LogWarning("Could not shutdown instance: %s", msg)

      _ShutdownInstanceDisks(self, instance)


class LUInstanceReinstall(LogicalUnit):
  """Reinstall an instance.

  """
  HPATH = "instance-reinstall"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    return _BuildInstanceHookEnvByObject(self, self.instance)

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node, "Instance primary node"
                     " offline, cannot reinstall")

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name,
                                 errors.ECODE_INVAL)
    _CheckInstanceState(self, instance, INSTANCE_DOWN, msg="cannot reinstall")

    if self.op.os_type is not None:
      # OS verification
      pnode = _ExpandNodeName(self.cfg, instance.primary_node)
      _CheckNodeHasOS(self, pnode, self.op.os_type, self.op.force_variant)
      instance_os = self.op.os_type
    else:
      instance_os = instance.os

    nodelist = list(instance.all_nodes)

    if self.op.osparams:
      i_osdict = _GetUpdatedParams(instance.osparams, self.op.osparams)
      _CheckOSParams(self, True, nodelist, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = None

    self.instance = instance

  def Exec(self, feedback_fn):
    """Reinstall the instance.

    """
    inst = self.instance

    if self.op.os_type is not None:
      feedback_fn("Changing OS to '%s'..." % self.op.os_type)
      inst.os = self.op.os_type
      # Write to configuration
      self.cfg.Update(inst, feedback_fn)

    _StartInstanceDisks(self, inst, None)
    try:
      feedback_fn("Running the instance OS create scripts...")
      # FIXME: pass debug option from opcode to backend
      result = self.rpc.call_instance_os_add(inst.primary_node,
                                             (inst, self.os_inst), True,
                                             self.op.debug_level)
      result.Raise("Could not install OS for instance %s on node %s" %
                   (inst.name, inst.primary_node))
    finally:
      _ShutdownInstanceDisks(self, inst)


class LUInstanceReboot(LogicalUnit):
  """Reboot an instance.

  """
  HPATH = "instance-reboot"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "IGNORE_SECONDARIES": self.op.ignore_secondaries,
      "REBOOT_TYPE": self.op.reboot_type,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckInstanceState(self, instance, INSTANCE_ONLINE)
    _CheckNodeOnline(self, instance.primary_node)

    # check bridges existence
    _CheckInstanceBridgesExist(self, instance)

  def Exec(self, feedback_fn):
    """Reboot the instance.

    """
    instance = self.instance
    ignore_secondaries = self.op.ignore_secondaries
    reboot_type = self.op.reboot_type
    reason = self.op.reason

    remote_info = self.rpc.call_instance_info(instance.primary_node,
                                              instance.name,
                                              instance.hypervisor)
    remote_info.Raise("Error checking node %s" % instance.primary_node)
    instance_running = bool(remote_info.payload)

    node_current = instance.primary_node

    if instance_running and reboot_type in [constants.INSTANCE_REBOOT_SOFT,
                                            constants.INSTANCE_REBOOT_HARD]:
      for disk in instance.disks:
        self.cfg.SetDiskID(disk, node_current)
      result = self.rpc.call_instance_reboot(node_current, instance,
                                             reboot_type,
                                             self.op.shutdown_timeout, reason)
      result.Raise("Could not reboot instance")
    else:
      if instance_running:
        result = self.rpc.call_instance_shutdown(node_current, instance,
                                                 self.op.shutdown_timeout,
                                                 reason)
        result.Raise("Could not shutdown instance for full reboot")
        _ShutdownInstanceDisks(self, instance)
      else:
        self.LogInfo("Instance %s was already stopped, starting now",
                     instance.name)
      _StartInstanceDisks(self, instance, ignore_secondaries)
      result = self.rpc.call_instance_start(node_current,
                                            (instance, None, None), False,
                                            reason)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance for"
                                 " full reboot: %s" % msg)

    self.cfg.MarkInstanceUp(instance.name)


class LUInstanceConsole(NoHooksLU):
  """Connect to an instance's console.

  This is somewhat special in that it returns the command line that
  you need to run on the master node in order to connect to the
  console.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = _ShareAll()
    self._ExpandAndLockInstance()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Connect to the console of an instance

    """
    instance = self.instance
    node = instance.primary_node

    node_insts = self.rpc.call_instance_list([node],
                                             [instance.hypervisor])[node]
    node_insts.Raise("Can't get node information from %s" % node)

    if instance.name not in node_insts.payload:
      if instance.admin_state == constants.ADMINST_UP:
        state = constants.INSTST_ERRORDOWN
      elif instance.admin_state == constants.ADMINST_DOWN:
        state = constants.INSTST_ADMINDOWN
      else:
        state = constants.INSTST_ADMINOFFLINE
      raise errors.OpExecError("Instance %s is not running (state %s)" %
                               (instance.name, state))

    logging.debug("Connecting to console of %s on %s", instance.name, node)

    return _GetInstanceConsole(self.cfg.GetClusterInfo(), instance)


def _DeclareLocksForMigration(lu, level):
  """Declares locks for L{TLMigrateInstance}.

  @type lu: L{LogicalUnit}
  @param level: Lock level

  """
  if level == locking.LEVEL_NODE_ALLOC:
    assert lu.op.instance_name in lu.owned_locks(locking.LEVEL_INSTANCE)

    instance = lu.cfg.GetInstanceInfo(lu.op.instance_name)

    # Node locks are already declared here rather than at LEVEL_NODE as we need
    # the instance object anyway to declare the node allocation lock.
    if instance.disk_template in constants.DTS_EXT_MIRROR:
      if lu.op.target_node is None:
        lu.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        lu.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET
      else:
        lu.needed_locks[locking.LEVEL_NODE] = [instance.primary_node,
                                               lu.op.target_node]
      del lu.recalculate_locks[locking.LEVEL_NODE]
    else:
      lu._LockInstancesNodes() # pylint: disable=W0212

  elif level == locking.LEVEL_NODE:
    # Node locks are declared together with the node allocation lock
    assert (lu.needed_locks[locking.LEVEL_NODE] or
            lu.needed_locks[locking.LEVEL_NODE] is locking.ALL_SET)

  elif level == locking.LEVEL_NODE_RES:
    # Copy node locks
    lu.needed_locks[locking.LEVEL_NODE_RES] = \
      _CopyLockList(lu.needed_locks[locking.LEVEL_NODE])


def _ExpandNamesForMigration(lu):
  """Expands names for use with L{TLMigrateInstance}.

  @type lu: L{LogicalUnit}

  """
  if lu.op.target_node is not None:
    lu.op.target_node = _ExpandNodeName(lu.cfg, lu.op.target_node)

  lu.needed_locks[locking.LEVEL_NODE] = []
  lu.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  lu.needed_locks[locking.LEVEL_NODE_RES] = []
  lu.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  # The node allocation lock is actually only needed for externally replicated
  # instances (e.g. sharedfile or RBD) and if an iallocator is used.
  lu.needed_locks[locking.LEVEL_NODE_ALLOC] = []


class LUInstanceFailover(LogicalUnit):
  """Failover an instance.

  """
  HPATH = "instance-failover"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check the arguments.

    """
    self.iallocator = getattr(self.op, "iallocator", None)
    self.target_node = getattr(self.op, "target_node", None)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    _ExpandNamesForMigration(self)

    self._migrater = \
      TLMigrateInstance(self, self.op.instance_name, False, True, False,
                        self.op.ignore_consistency, True,
                        self.op.shutdown_timeout, self.op.ignore_ipolicy)

    self.tasklets = [self._migrater]

  def DeclareLocks(self, level):
    _DeclareLocksForMigration(self, level)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    instance = self._migrater.instance
    source_node = instance.primary_node
    target_node = self.op.target_node
    env = {
      "IGNORE_CONSISTENCY": self.op.ignore_consistency,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      "OLD_PRIMARY": source_node,
      "NEW_PRIMARY": target_node,
      }

    if instance.disk_template in constants.DTS_INT_MIRROR:
      env["OLD_SECONDARY"] = instance.secondary_nodes[0]
      env["NEW_SECONDARY"] = source_node
    else:
      env["OLD_SECONDARY"] = env["NEW_SECONDARY"] = ""

    env.update(_BuildInstanceHookEnvByObject(self, instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self._migrater.instance
    nl = [self.cfg.GetMasterNode()] + list(instance.secondary_nodes)
    return (nl, nl + [instance.primary_node])


class LUInstanceMigrate(LogicalUnit):
  """Migrate an instance.

  This is migration without shutting down, compared to the failover,
  which is done with shutdown.

  """
  HPATH = "instance-migrate"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    _ExpandNamesForMigration(self)

    self._migrater = \
      TLMigrateInstance(self, self.op.instance_name, self.op.cleanup,
                        False, self.op.allow_failover, False,
                        self.op.allow_runtime_changes,
                        constants.DEFAULT_SHUTDOWN_TIMEOUT,
                        self.op.ignore_ipolicy)

    self.tasklets = [self._migrater]

  def DeclareLocks(self, level):
    _DeclareLocksForMigration(self, level)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    instance = self._migrater.instance
    source_node = instance.primary_node
    target_node = self.op.target_node
    env = _BuildInstanceHookEnvByObject(self, instance)
    env.update({
      "MIGRATE_LIVE": self._migrater.live,
      "MIGRATE_CLEANUP": self.op.cleanup,
      "OLD_PRIMARY": source_node,
      "NEW_PRIMARY": target_node,
      "ALLOW_RUNTIME_CHANGES": self.op.allow_runtime_changes,
      })

    if instance.disk_template in constants.DTS_INT_MIRROR:
      env["OLD_SECONDARY"] = target_node
      env["NEW_SECONDARY"] = source_node
    else:
      env["OLD_SECONDARY"] = env["NEW_SECONDARY"] = None

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self._migrater.instance
    snodes = list(instance.secondary_nodes)
    nl = [self.cfg.GetMasterNode(), instance.primary_node] + snodes
    return (nl, nl)


class LUInstanceMultiAlloc(NoHooksLU):
  """Allocates multiple instances at the same time.

  """
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    nodes = []
    for inst in self.op.instances:
      if inst.iallocator is not None:
        raise errors.OpPrereqError("iallocator are not allowed to be set on"
                                   " instance objects", errors.ECODE_INVAL)
      nodes.append(bool(inst.pnode))
      if inst.disk_template in constants.DTS_INT_MIRROR:
        nodes.append(bool(inst.snode))

    has_nodes = compat.any(nodes)
    if compat.all(nodes) ^ has_nodes:
      raise errors.OpPrereqError("There are instance objects providing"
                                 " pnode/snode while others do not",
                                 errors.ECODE_INVAL)

    if self.op.iallocator is None:
      default_iallocator = self.cfg.GetDefaultIAllocator()
      if default_iallocator and has_nodes:
        self.op.iallocator = default_iallocator
      else:
        raise errors.OpPrereqError("No iallocator or nodes on the instances"
                                   " given and no cluster-wide default"
                                   " iallocator found; please specify either"
                                   " an iallocator or nodes on the instances"
                                   " or set a cluster-wide default iallocator",
                                   errors.ECODE_INVAL)

    _CheckOpportunisticLocking(self.op)

    dups = utils.FindDuplicates([op.instance_name for op in self.op.instances])
    if dups:
      raise errors.OpPrereqError("There are duplicate instance names: %s" %
                                 utils.CommaJoin(dups), errors.ECODE_INVAL)

  def ExpandNames(self):
    """Calculate the locks.

    """
    self.share_locks = _ShareAll()
    self.needed_locks = {
      # iallocator will select nodes and even if no iallocator is used,
      # collisions with LUInstanceCreate should be avoided
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    if self.op.iallocator:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
      self.needed_locks[locking.LEVEL_NODE_RES] = locking.ALL_SET

      if self.op.opportunistic_locking:
        self.opportunistic_locks[locking.LEVEL_NODE] = True
        self.opportunistic_locks[locking.LEVEL_NODE_RES] = True
    else:
      nodeslist = []
      for inst in self.op.instances:
        inst.pnode = _ExpandNodeName(self.cfg, inst.pnode)
        nodeslist.append(inst.pnode)
        if inst.snode is not None:
          inst.snode = _ExpandNodeName(self.cfg, inst.snode)
          nodeslist.append(inst.snode)

      self.needed_locks[locking.LEVEL_NODE] = nodeslist
      # Lock resources of instance's primary and secondary nodes (copy to
      # prevent accidential modification)
      self.needed_locks[locking.LEVEL_NODE_RES] = list(nodeslist)

  def CheckPrereq(self):
    """Check prerequisite.

    """
    cluster = self.cfg.GetClusterInfo()
    default_vg = self.cfg.GetVGName()
    ec_id = self.proc.GetECId()

    if self.op.opportunistic_locking:
      # Only consider nodes for which a lock is held
      node_whitelist = list(self.owned_locks(locking.LEVEL_NODE))
    else:
      node_whitelist = None

    insts = [_CreateInstanceAllocRequest(op, _ComputeDisks(op, default_vg),
                                         _ComputeNics(op, cluster, None,
                                                      self.cfg, ec_id),
                                         _ComputeFullBeParams(op, cluster),
                                         node_whitelist)
             for op in self.op.instances]

    req = iallocator.IAReqMultiInstanceAlloc(instances=insts)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)

    self.ia_result = ial.result

    if self.op.dry_run:
      self.dry_run_result = objects.FillDict(self._ConstructPartialResult(), {
        constants.JOB_IDS_KEY: [],
        })

  def _ConstructPartialResult(self):
    """Contructs the partial result.

    """
    (allocatable, failed) = self.ia_result
    return {
      opcodes.OpInstanceMultiAlloc.ALLOCATABLE_KEY:
        map(compat.fst, allocatable),
      opcodes.OpInstanceMultiAlloc.FAILED_KEY: failed,
      }

  def Exec(self, feedback_fn):
    """Executes the opcode.

    """
    op2inst = dict((op.instance_name, op) for op in self.op.instances)
    (allocatable, failed) = self.ia_result

    jobs = []
    for (name, nodes) in allocatable:
      op = op2inst.pop(name)

      if len(nodes) > 1:
        (op.pnode, op.snode) = nodes
      else:
        (op.pnode,) = nodes

      jobs.append([op])

    missing = set(op2inst.keys()) - set(failed)
    assert not missing, \
      "Iallocator did return incomplete result: %s" % utils.CommaJoin(missing)

    return ResultWithJobs(jobs, **self._ConstructPartialResult())


class _InstNicModPrivate:
  """Data structure for network interface modifications.

  Used by L{LUInstanceSetParams}.

  """
  def __init__(self):
    self.params = None
    self.filled = None


def PrepareContainerMods(mods, private_fn):
  """Prepares a list of container modifications by adding a private data field.

  @type mods: list of tuples; (operation, index, parameters)
  @param mods: List of modifications
  @type private_fn: callable or None
  @param private_fn: Callable for constructing a private data field for a
    modification
  @rtype: list

  """
  if private_fn is None:
    fn = lambda: None
  else:
    fn = private_fn

  return [(op, idx, params, fn()) for (op, idx, params) in mods]


def _CheckNodesPhysicalCPUs(lu, nodenames, requested, hypervisor_name):
  """Checks if nodes have enough physical CPUs

  This function checks if all given nodes have the needed number of
  physical CPUs. In case any node has less CPUs or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type nodenames: C{list}
  @param nodenames: the list of node names to check
  @type requested: C{int}
  @param requested: the minimum acceptable number of physical CPUs
  @raise errors.OpPrereqError: if the node doesn't have enough CPUs,
      or we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info(nodenames, None, [hypervisor_name], None)
  for node in nodenames:
    info = nodeinfo[node]
    info.Raise("Cannot get current information from node %s" % node,
               prereq=True, ecode=errors.ECODE_ENVIRON)
    (_, _, (hv_info, )) = info.payload
    num_cpus = hv_info.get("cpu_total", None)
    if not isinstance(num_cpus, int):
      raise errors.OpPrereqError("Can't compute the number of physical CPUs"
                                 " on node %s, result was '%s'" %
                                 (node, num_cpus), errors.ECODE_ENVIRON)
    if requested > num_cpus:
      raise errors.OpPrereqError("Node %s has %s physical CPUs, but %s are "
                                 "required" % (node, num_cpus, requested),
                                 errors.ECODE_NORES)


def GetItemFromContainer(identifier, kind, container):
  """Return the item refered by the identifier.

  @type identifier: string
  @param identifier: Item index or name or UUID
  @type kind: string
  @param kind: One-word item description
  @type container: list
  @param container: Container to get the item from

  """
  # Index
  try:
    idx = int(identifier)
    if idx == -1:
      # Append
      absidx = len(container) - 1
    elif idx < 0:
      raise IndexError("Not accepting negative indices other than -1")
    elif idx > len(container):
      raise IndexError("Got %s index %s, but there are only %s" %
                       (kind, idx, len(container)))
    else:
      absidx = idx
    return (absidx, container[idx])
  except ValueError:
    pass

  for idx, item in enumerate(container):
    if item.uuid == identifier or item.name == identifier:
      return (idx, item)

  raise errors.OpPrereqError("Cannot find %s with identifier %s" %
                             (kind, identifier), errors.ECODE_NOENT)


def ApplyContainerMods(kind, container, chgdesc, mods,
                       create_fn, modify_fn, remove_fn):
  """Applies descriptions in C{mods} to C{container}.

  @type kind: string
  @param kind: One-word item description
  @type container: list
  @param container: Container to modify
  @type chgdesc: None or list
  @param chgdesc: List of applied changes
  @type mods: list
  @param mods: Modifications as returned by L{PrepareContainerMods}
  @type create_fn: callable
  @param create_fn: Callback for creating a new item (L{constants.DDM_ADD});
    receives absolute item index, parameters and private data object as added
    by L{PrepareContainerMods}, returns tuple containing new item and changes
    as list
  @type modify_fn: callable
  @param modify_fn: Callback for modifying an existing item
    (L{constants.DDM_MODIFY}); receives absolute item index, item, parameters
    and private data object as added by L{PrepareContainerMods}, returns
    changes as list
  @type remove_fn: callable
  @param remove_fn: Callback on removing item; receives absolute item index,
    item and private data object as added by L{PrepareContainerMods}

  """
  for (op, identifier, params, private) in mods:
    changes = None

    if op == constants.DDM_ADD:
      # Calculate where item will be added
      # When adding an item, identifier can only be an index
      try:
        idx = int(identifier)
      except ValueError:
        raise errors.OpPrereqError("Only possitive integer or -1 is accepted as"
                                   " identifier for %s" % constants.DDM_ADD,
                                   errors.ECODE_INVAL)
      if idx == -1:
        addidx = len(container)
      else:
        if idx < 0:
          raise IndexError("Not accepting negative indices other than -1")
        elif idx > len(container):
          raise IndexError("Got %s index %s, but there are only %s" %
                           (kind, idx, len(container)))
        addidx = idx

      if create_fn is None:
        item = params
      else:
        (item, changes) = create_fn(addidx, params, private)

      if idx == -1:
        container.append(item)
      else:
        assert idx >= 0
        assert idx <= len(container)
        # list.insert does so before the specified index
        container.insert(idx, item)
    else:
      # Retrieve existing item
      (absidx, item) = GetItemFromContainer(identifier, kind, container)

      if op == constants.DDM_REMOVE:
        assert not params

        if remove_fn is not None:
          remove_fn(absidx, item, private)

        changes = [("%s/%s" % (kind, absidx), "remove")]

        assert container[absidx] == item
        del container[absidx]
      elif op == constants.DDM_MODIFY:
        if modify_fn is not None:
          changes = modify_fn(absidx, item, params, private)
      else:
        raise errors.ProgrammerError("Unhandled operation '%s'" % op)

    assert _TApplyContModsCbChanges(changes)

    if not (chgdesc is None or changes is None):
      chgdesc.extend(changes)


def _UpdateIvNames(base_index, disks):
  """Updates the C{iv_name} attribute of disks.

  @type disks: list of L{objects.Disk}

  """
  for (idx, disk) in enumerate(disks):
    disk.iv_name = "disk/%s" % (base_index + idx, )


class LUInstanceSetParams(LogicalUnit):
  """Modifies an instances's parameters.

  """
  HPATH = "instance-modify"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  @staticmethod
  def _UpgradeDiskNicMods(kind, mods, verify_fn):
    assert ht.TList(mods)
    assert not mods or len(mods[0]) in (2, 3)

    if mods and len(mods[0]) == 2:
      result = []

      addremove = 0
      for op, params in mods:
        if op in (constants.DDM_ADD, constants.DDM_REMOVE):
          result.append((op, -1, params))
          addremove += 1

          if addremove > 1:
            raise errors.OpPrereqError("Only one %s add or remove operation is"
                                       " supported at a time" % kind,
                                       errors.ECODE_INVAL)
        else:
          result.append((constants.DDM_MODIFY, op, params))

      assert verify_fn(result)
    else:
      result = mods

    return result

  @staticmethod
  def _CheckMods(kind, mods, key_types, item_fn):
    """Ensures requested disk/NIC modifications are valid.

    """
    for (op, _, params) in mods:
      assert ht.TDict(params)

      # If 'key_types' is an empty dict, we assume we have an
      # 'ext' template and thus do not ForceDictType
      if key_types:
        utils.ForceDictType(params, key_types)

      if op == constants.DDM_REMOVE:
        if params:
          raise errors.OpPrereqError("No settings should be passed when"
                                     " removing a %s" % kind,
                                     errors.ECODE_INVAL)
      elif op in (constants.DDM_ADD, constants.DDM_MODIFY):
        item_fn(op, params)
      else:
        raise errors.ProgrammerError("Unhandled operation '%s'" % op)

  @staticmethod
  def _VerifyDiskModification(op, params):
    """Verifies a disk modification.

    """
    if op == constants.DDM_ADD:
      mode = params.setdefault(constants.IDISK_MODE, constants.DISK_RDWR)
      if mode not in constants.DISK_ACCESS_SET:
        raise errors.OpPrereqError("Invalid disk access mode '%s'" % mode,
                                   errors.ECODE_INVAL)

      size = params.get(constants.IDISK_SIZE, None)
      if size is None:
        raise errors.OpPrereqError("Required disk parameter '%s' missing" %
                                   constants.IDISK_SIZE, errors.ECODE_INVAL)

      try:
        size = int(size)
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid disk size parameter: %s" % err,
                                   errors.ECODE_INVAL)

      params[constants.IDISK_SIZE] = size
      name = params.get(constants.IDISK_NAME, None)
      if name is not None and name.lower() == constants.VALUE_NONE:
        params[constants.IDISK_NAME] = None

    elif op == constants.DDM_MODIFY:
      if constants.IDISK_SIZE in params:
        raise errors.OpPrereqError("Disk size change not possible, use"
                                   " grow-disk", errors.ECODE_INVAL)
      if len(params) > 2:
        raise errors.OpPrereqError("Disk modification doesn't support"
                                   " additional arbitrary parameters",
                                   errors.ECODE_INVAL)
      name = params.get(constants.IDISK_NAME, None)
      if name is not None and name.lower() == constants.VALUE_NONE:
        params[constants.IDISK_NAME] = None

  @staticmethod
  def _VerifyNicModification(op, params):
    """Verifies a network interface modification.

    """
    if op in (constants.DDM_ADD, constants.DDM_MODIFY):
      ip = params.get(constants.INIC_IP, None)
      name = params.get(constants.INIC_NAME, None)
      req_net = params.get(constants.INIC_NETWORK, None)
      link = params.get(constants.NIC_LINK, None)
      mode = params.get(constants.NIC_MODE, None)
      if name is not None and name.lower() == constants.VALUE_NONE:
        params[constants.INIC_NAME] = None
      if req_net is not None:
        if req_net.lower() == constants.VALUE_NONE:
          params[constants.INIC_NETWORK] = None
          req_net = None
        elif link is not None or mode is not None:
          raise errors.OpPrereqError("If network is given"
                                     " mode or link should not",
                                     errors.ECODE_INVAL)

      if op == constants.DDM_ADD:
        macaddr = params.get(constants.INIC_MAC, None)
        if macaddr is None:
          params[constants.INIC_MAC] = constants.VALUE_AUTO

      if ip is not None:
        if ip.lower() == constants.VALUE_NONE:
          params[constants.INIC_IP] = None
        else:
          if ip.lower() == constants.NIC_IP_POOL:
            if op == constants.DDM_ADD and req_net is None:
              raise errors.OpPrereqError("If ip=pool, parameter network"
                                         " cannot be none",
                                         errors.ECODE_INVAL)
          else:
            if not netutils.IPAddress.IsValid(ip):
              raise errors.OpPrereqError("Invalid IP address '%s'" % ip,
                                         errors.ECODE_INVAL)

      if constants.INIC_MAC in params:
        macaddr = params[constants.INIC_MAC]
        if macaddr not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
          macaddr = utils.NormalizeAndValidateMac(macaddr)

        if op == constants.DDM_MODIFY and macaddr == constants.VALUE_AUTO:
          raise errors.OpPrereqError("'auto' is not a valid MAC address when"
                                     " modifying an existing NIC",
                                     errors.ECODE_INVAL)

  def CheckArguments(self):
    if not (self.op.nics or self.op.disks or self.op.disk_template or
            self.op.hvparams or self.op.beparams or self.op.os_name or
            self.op.offline is not None or self.op.runtime_mem or
            self.op.pnode):
      raise errors.OpPrereqError("No changes submitted", errors.ECODE_INVAL)

    if self.op.hvparams:
      _CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS,
                            "hypervisor", "instance", "cluster")

    self.op.disks = self._UpgradeDiskNicMods(
      "disk", self.op.disks, opcodes.OpInstanceSetParams.TestDiskModifications)
    self.op.nics = self._UpgradeDiskNicMods(
      "NIC", self.op.nics, opcodes.OpInstanceSetParams.TestNicModifications)

    if self.op.disks and self.op.disk_template is not None:
      raise errors.OpPrereqError("Disk template conversion and other disk"
                                 " changes not supported at the same time",
                                 errors.ECODE_INVAL)

    if (self.op.disk_template and
        self.op.disk_template in constants.DTS_INT_MIRROR and
        self.op.remote_node is None):
      raise errors.OpPrereqError("Changing the disk template to a mirrored"
                                 " one requires specifying a secondary node",
                                 errors.ECODE_INVAL)

    # Check NIC modifications
    self._CheckMods("NIC", self.op.nics, constants.INIC_PARAMS_TYPES,
                    self._VerifyNicModification)

    if self.op.pnode:
      self.op.pnode = _ExpandNodeName(self.cfg, self.op.pnode)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODEGROUP] = []
    # Can't even acquire node locks in shared mode as upcoming changes in
    # Ganeti 2.6 will start to modify the node object on disk conversion
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE
    # Look node group to look up the ipolicy
    self.share_locks[locking.LEVEL_NODEGROUP] = 1

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]
      # Acquire locks for the instance's nodegroups optimistically. Needs
      # to be verified in CheckPrereq
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetInstanceNodeGroups(self.op.instance_name)
    elif level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
      if self.op.disk_template and self.op.remote_node:
        self.op.remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)
        self.needed_locks[locking.LEVEL_NODE].append(self.op.remote_node)
    elif level == locking.LEVEL_NODE_RES and self.op.disk_template:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, primary and secondaries.

    """
    args = {}
    if constants.BE_MINMEM in self.be_new:
      args["minmem"] = self.be_new[constants.BE_MINMEM]
    if constants.BE_MAXMEM in self.be_new:
      args["maxmem"] = self.be_new[constants.BE_MAXMEM]
    if constants.BE_VCPUS in self.be_new:
      args["vcpus"] = self.be_new[constants.BE_VCPUS]
    # TODO: export disk changes. Note: _BuildInstanceHookEnv* don't export disk
    # information at all.

    if self._new_nics is not None:
      nics = []

      for nic in self._new_nics:
        n = copy.deepcopy(nic)
        nicparams = self.cluster.SimpleFillNIC(n.nicparams)
        n.nicparams = nicparams
        nics.append(_NICToTuple(self, n))

      args["nics"] = nics

    env = _BuildInstanceHookEnvByObject(self, self.instance, override=args)
    if self.op.disk_template:
      env["NEW_DISK_TEMPLATE"] = self.op.disk_template
    if self.op.runtime_mem:
      env["RUNTIME_MEMORY"] = self.op.runtime_mem

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def _PrepareNicModification(self, params, private, old_ip, old_net_uuid,
                              old_params, cluster, pnode):

    update_params_dict = dict([(key, params[key])
                               for key in constants.NICS_PARAMETERS
                               if key in params])

    req_link = update_params_dict.get(constants.NIC_LINK, None)
    req_mode = update_params_dict.get(constants.NIC_MODE, None)

    new_net_uuid = None
    new_net_uuid_or_name = params.get(constants.INIC_NETWORK, old_net_uuid)
    if new_net_uuid_or_name:
      new_net_uuid = self.cfg.LookupNetwork(new_net_uuid_or_name)
      new_net_obj = self.cfg.GetNetwork(new_net_uuid)

    if old_net_uuid:
      old_net_obj = self.cfg.GetNetwork(old_net_uuid)

    if new_net_uuid:
      netparams = self.cfg.GetGroupNetParams(new_net_uuid, pnode)
      if not netparams:
        raise errors.OpPrereqError("No netparams found for the network"
                                   " %s, probably not connected" %
                                   new_net_obj.name, errors.ECODE_INVAL)
      new_params = dict(netparams)
    else:
      new_params = _GetUpdatedParams(old_params, update_params_dict)

    utils.ForceDictType(new_params, constants.NICS_PARAMETER_TYPES)

    new_filled_params = cluster.SimpleFillNIC(new_params)
    objects.NIC.CheckParameterSyntax(new_filled_params)

    new_mode = new_filled_params[constants.NIC_MODE]
    if new_mode == constants.NIC_MODE_BRIDGED:
      bridge = new_filled_params[constants.NIC_LINK]
      msg = self.rpc.call_bridges_exist(pnode, [bridge]).fail_msg
      if msg:
        msg = "Error checking bridges on node '%s': %s" % (pnode, msg)
        if self.op.force:
          self.warn.append(msg)
        else:
          raise errors.OpPrereqError(msg, errors.ECODE_ENVIRON)

    elif new_mode == constants.NIC_MODE_ROUTED:
      ip = params.get(constants.INIC_IP, old_ip)
      if ip is None:
        raise errors.OpPrereqError("Cannot set the NIC IP address to None"
                                   " on a routed NIC", errors.ECODE_INVAL)

    elif new_mode == constants.NIC_MODE_OVS:
      # TODO: check OVS link
      self.LogInfo("OVS links are currently not checked for correctness")

    if constants.INIC_MAC in params:
      mac = params[constants.INIC_MAC]
      if mac is None:
        raise errors.OpPrereqError("Cannot unset the NIC MAC address",
                                   errors.ECODE_INVAL)
      elif mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        # otherwise generate the MAC address
        params[constants.INIC_MAC] = \
          self.cfg.GenerateMAC(new_net_uuid, self.proc.GetECId())
      else:
        # or validate/reserve the current one
        try:
          self.cfg.ReserveMAC(mac, self.proc.GetECId())
        except errors.ReservationError:
          raise errors.OpPrereqError("MAC address '%s' already in use"
                                     " in cluster" % mac,
                                     errors.ECODE_NOTUNIQUE)
    elif new_net_uuid != old_net_uuid:

      def get_net_prefix(net_uuid):
        mac_prefix = None
        if net_uuid:
          nobj = self.cfg.GetNetwork(net_uuid)
          mac_prefix = nobj.mac_prefix

        return mac_prefix

      new_prefix = get_net_prefix(new_net_uuid)
      old_prefix = get_net_prefix(old_net_uuid)
      if old_prefix != new_prefix:
        params[constants.INIC_MAC] = \
          self.cfg.GenerateMAC(new_net_uuid, self.proc.GetECId())

    # if there is a change in (ip, network) tuple
    new_ip = params.get(constants.INIC_IP, old_ip)
    if (new_ip, new_net_uuid) != (old_ip, old_net_uuid):
      if new_ip:
        # if IP is pool then require a network and generate one IP
        if new_ip.lower() == constants.NIC_IP_POOL:
          if new_net_uuid:
            try:
              new_ip = self.cfg.GenerateIp(new_net_uuid, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("Unable to get a free IP"
                                         " from the address pool",
                                         errors.ECODE_STATE)
            self.LogInfo("Chose IP %s from network %s",
                         new_ip,
                         new_net_obj.name)
            params[constants.INIC_IP] = new_ip
          else:
            raise errors.OpPrereqError("ip=pool, but no network found",
                                       errors.ECODE_INVAL)
        # Reserve new IP if in the new network if any
        elif new_net_uuid:
          try:
            self.cfg.ReserveIp(new_net_uuid, new_ip, self.proc.GetECId())
            self.LogInfo("Reserving IP %s in network %s",
                         new_ip, new_net_obj.name)
          except errors.ReservationError:
            raise errors.OpPrereqError("IP %s not available in network %s" %
                                       (new_ip, new_net_obj.name),
                                       errors.ECODE_NOTUNIQUE)
        # new network is None so check if new IP is a conflicting IP
        elif self.op.conflicts_check:
          _CheckForConflictingIp(self, new_ip, pnode)

      # release old IP if old network is not None
      if old_ip and old_net_uuid:
        try:
          self.cfg.ReleaseIp(old_net_uuid, old_ip, self.proc.GetECId())
        except errors.AddressPoolError:
          logging.warning("Release IP %s not contained in network %s",
                          old_ip, old_net_obj.name)

    # there are no changes in (ip, network) tuple and old network is not None
    elif (old_net_uuid is not None and
          (req_link is not None or req_mode is not None)):
      raise errors.OpPrereqError("Not allowed to change link or mode of"
                                 " a NIC that is connected to a network",
                                 errors.ECODE_INVAL)

    private.params = new_params
    private.filled = new_filled_params

  def _PreCheckDiskTemplate(self, pnode_info):
    """CheckPrereq checks related to a new disk template."""
    # Arguments are passed to avoid configuration lookups
    instance = self.instance
    pnode = instance.primary_node
    cluster = self.cluster
    if instance.disk_template == self.op.disk_template:
      raise errors.OpPrereqError("Instance already has disk template %s" %
                                 instance.disk_template, errors.ECODE_INVAL)

    if (instance.disk_template,
        self.op.disk_template) not in self._DISK_CONVERSIONS:
      raise errors.OpPrereqError("Unsupported disk template conversion from"
                                 " %s to %s" % (instance.disk_template,
                                                self.op.disk_template),
                                 errors.ECODE_INVAL)
    _CheckInstanceState(self, instance, INSTANCE_DOWN,
                        msg="cannot change disk template")
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.remote_node == pnode:
        raise errors.OpPrereqError("Given new secondary node %s is the same"
                                   " as the primary node of the instance" %
                                   self.op.remote_node, errors.ECODE_STATE)
      _CheckNodeOnline(self, self.op.remote_node)
      _CheckNodeNotDrained(self, self.op.remote_node)
      # FIXME: here we assume that the old instance type is DT_PLAIN
      assert instance.disk_template == constants.DT_PLAIN
      disks = [{constants.IDISK_SIZE: d.size,
                constants.IDISK_VG: d.logical_id[0]}
               for d in instance.disks]
      required = _ComputeDiskSizePerVG(self.op.disk_template, disks)
      _CheckNodesFreeDiskPerVG(self, [self.op.remote_node], required)

      snode_info = self.cfg.GetNodeInfo(self.op.remote_node)
      snode_group = self.cfg.GetNodeGroup(snode_info.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              snode_group)
      _CheckTargetNodeIPolicy(self, ipolicy, instance, snode_info, self.cfg,
                              ignore=self.op.ignore_ipolicy)
      if pnode_info.group != snode_info.group:
        self.LogWarning("The primary and secondary nodes are in two"
                        " different node groups; the disk parameters"
                        " from the first disk's node group will be"
                        " used")

    if not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      # Make sure none of the nodes require exclusive storage
      nodes = [pnode_info]
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        assert snode_info
        nodes.append(snode_info)
      has_es = lambda n: _IsExclusiveStorageEnabledNode(self.cfg, n)
      if compat.any(map(has_es, nodes)):
        errmsg = ("Cannot convert disk template from %s to %s when exclusive"
                  " storage is enabled" % (instance.disk_template,
                                           self.op.disk_template))
        raise errors.OpPrereqError(errmsg, errors.ECODE_STATE)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    assert self.op.instance_name in self.owned_locks(locking.LEVEL_INSTANCE)
    instance = self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)

    cluster = self.cluster = self.cfg.GetClusterInfo()
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    pnode = instance.primary_node

    self.warn = []

    if (self.op.pnode is not None and self.op.pnode != pnode and
        not self.op.force):
      # verify that the instance is not up
      instance_info = self.rpc.call_instance_info(pnode, instance.name,
                                                  instance.hypervisor)
      if instance_info.fail_msg:
        self.warn.append("Can't get instance runtime information: %s" %
                         instance_info.fail_msg)
      elif instance_info.payload:
        raise errors.OpPrereqError("Instance is still running on %s" % pnode,
                                   errors.ECODE_STATE)

    assert pnode in self.owned_locks(locking.LEVEL_NODE)
    nodelist = list(instance.all_nodes)
    pnode_info = self.cfg.GetNodeInfo(pnode)
    self.diskparams = self.cfg.GetInstanceDiskParams(instance)

    #_CheckInstanceNodeGroups(self.cfg, self.op.instance_name, owned_groups)
    assert pnode_info.group in self.owned_locks(locking.LEVEL_NODEGROUP)
    group_info = self.cfg.GetNodeGroup(pnode_info.group)

    # dictionary with instance information after the modification
    ispec = {}

    # Check disk modifications. This is done here and not in CheckArguments
    # (as with NICs), because we need to know the instance's disk template
    if instance.disk_template == constants.DT_EXT:
      self._CheckMods("disk", self.op.disks, {},
                      self._VerifyDiskModification)
    else:
      self._CheckMods("disk", self.op.disks, constants.IDISK_PARAMS_TYPES,
                      self._VerifyDiskModification)

    # Prepare disk/NIC modifications
    self.diskmod = PrepareContainerMods(self.op.disks, None)
    self.nicmod = PrepareContainerMods(self.op.nics, _InstNicModPrivate)

    # Check the validity of the `provider' parameter
    if instance.disk_template in constants.DT_EXT:
      for mod in self.diskmod:
        ext_provider = mod[2].get(constants.IDISK_PROVIDER, None)
        if mod[0] == constants.DDM_ADD:
          if ext_provider is None:
            raise errors.OpPrereqError("Instance template is '%s' and parameter"
                                       " '%s' missing, during disk add" %
                                       (constants.DT_EXT,
                                        constants.IDISK_PROVIDER),
                                       errors.ECODE_NOENT)
        elif mod[0] == constants.DDM_MODIFY:
          if ext_provider:
            raise errors.OpPrereqError("Parameter '%s' is invalid during disk"
                                       " modification" %
                                       constants.IDISK_PROVIDER,
                                       errors.ECODE_INVAL)
    else:
      for mod in self.diskmod:
        ext_provider = mod[2].get(constants.IDISK_PROVIDER, None)
        if ext_provider is not None:
          raise errors.OpPrereqError("Parameter '%s' is only valid for"
                                     " instances of type '%s'" %
                                     (constants.IDISK_PROVIDER,
                                      constants.DT_EXT),
                                     errors.ECODE_INVAL)

    # OS change
    if self.op.os_name and not self.op.force:
      _CheckNodeHasOS(self, instance.primary_node, self.op.os_name,
                      self.op.force_variant)
      instance_os = self.op.os_name
    else:
      instance_os = instance.os

    assert not (self.op.disk_template and self.op.disks), \
      "Can't modify disk template and apply disk changes at the same time"

    if self.op.disk_template:
      self._PreCheckDiskTemplate(pnode_info)

    # hvparams processing
    if self.op.hvparams:
      hv_type = instance.hypervisor
      i_hvdict = _GetUpdatedParams(instance.hvparams, self.op.hvparams)
      utils.ForceDictType(i_hvdict, constants.HVS_PARAMETER_TYPES)
      hv_new = cluster.SimpleFillHV(hv_type, instance.os, i_hvdict)

      # local check
      hypervisor.GetHypervisorClass(hv_type).CheckParameterSyntax(hv_new)
      _CheckHVParams(self, nodelist, instance.hypervisor, hv_new)
      self.hv_proposed = self.hv_new = hv_new # the new actual values
      self.hv_inst = i_hvdict # the new dict (without defaults)
    else:
      self.hv_proposed = cluster.SimpleFillHV(instance.hypervisor, instance.os,
                                              instance.hvparams)
      self.hv_new = self.hv_inst = {}

    # beparams processing
    if self.op.beparams:
      i_bedict = _GetUpdatedParams(instance.beparams, self.op.beparams,
                                   use_none=True)
      objects.UpgradeBeParams(i_bedict)
      utils.ForceDictType(i_bedict, constants.BES_PARAMETER_TYPES)
      be_new = cluster.SimpleFillBE(i_bedict)
      self.be_proposed = self.be_new = be_new # the new actual values
      self.be_inst = i_bedict # the new dict (without defaults)
    else:
      self.be_new = self.be_inst = {}
      self.be_proposed = cluster.SimpleFillBE(instance.beparams)
    be_old = cluster.FillBE(instance)

    # CPU param validation -- checking every time a parameter is
    # changed to cover all cases where either CPU mask or vcpus have
    # changed
    if (constants.BE_VCPUS in self.be_proposed and
        constants.HV_CPU_MASK in self.hv_proposed):
      cpu_list = \
        utils.ParseMultiCpuMask(self.hv_proposed[constants.HV_CPU_MASK])
      # Verify mask is consistent with number of vCPUs. Can skip this
      # test if only 1 entry in the CPU mask, which means same mask
      # is applied to all vCPUs.
      if (len(cpu_list) > 1 and
          len(cpu_list) != self.be_proposed[constants.BE_VCPUS]):
        raise errors.OpPrereqError("Number of vCPUs [%d] does not match the"
                                   " CPU mask [%s]" %
                                   (self.be_proposed[constants.BE_VCPUS],
                                    self.hv_proposed[constants.HV_CPU_MASK]),
                                   errors.ECODE_INVAL)

      # Only perform this test if a new CPU mask is given
      if constants.HV_CPU_MASK in self.hv_new:
        # Calculate the largest CPU number requested
        max_requested_cpu = max(map(max, cpu_list))
        # Check that all of the instance's nodes have enough physical CPUs to
        # satisfy the requested CPU mask
        _CheckNodesPhysicalCPUs(self, instance.all_nodes,
                                max_requested_cpu + 1, instance.hypervisor)

    # osparams processing
    if self.op.osparams:
      i_osdict = _GetUpdatedParams(instance.osparams, self.op.osparams)
      _CheckOSParams(self, True, nodelist, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = {}

    #TODO(dynmem): do the appropriate check involving MINMEM
    if (constants.BE_MAXMEM in self.op.beparams and not self.op.force and
        be_new[constants.BE_MAXMEM] > be_old[constants.BE_MAXMEM]):
      mem_check_list = [pnode]
      if be_new[constants.BE_AUTO_BALANCE]:
        # either we changed auto_balance to yes or it was from before
        mem_check_list.extend(instance.secondary_nodes)
      instance_info = self.rpc.call_instance_info(pnode, instance.name,
                                                  instance.hypervisor)
      nodeinfo = self.rpc.call_node_info(mem_check_list, None,
                                         [instance.hypervisor], False)
      pninfo = nodeinfo[pnode]
      msg = pninfo.fail_msg
      if msg:
        # Assume the primary node is unreachable and go ahead
        self.warn.append("Can't get info from primary node %s: %s" %
                         (pnode, msg))
      else:
        (_, _, (pnhvinfo, )) = pninfo.payload
        if not isinstance(pnhvinfo.get("memory_free", None), int):
          self.warn.append("Node data from primary node %s doesn't contain"
                           " free memory information" % pnode)
        elif instance_info.fail_msg:
          self.warn.append("Can't get instance runtime information: %s" %
                           instance_info.fail_msg)
        else:
          if instance_info.payload:
            current_mem = int(instance_info.payload["memory"])
          else:
            # Assume instance not running
            # (there is a slight race condition here, but it's not very
            # probable, and we have no other way to check)
            # TODO: Describe race condition
            current_mem = 0
          #TODO(dynmem): do the appropriate check involving MINMEM
          miss_mem = (be_new[constants.BE_MAXMEM] - current_mem -
                      pnhvinfo["memory_free"])
          if miss_mem > 0:
            raise errors.OpPrereqError("This change will prevent the instance"
                                       " from starting, due to %d MB of memory"
                                       " missing on its primary node" %
                                       miss_mem, errors.ECODE_NORES)

      if be_new[constants.BE_AUTO_BALANCE]:
        for node, nres in nodeinfo.items():
          if node not in instance.secondary_nodes:
            continue
          nres.Raise("Can't get info from secondary node %s" % node,
                     prereq=True, ecode=errors.ECODE_STATE)
          (_, _, (nhvinfo, )) = nres.payload
          if not isinstance(nhvinfo.get("memory_free", None), int):
            raise errors.OpPrereqError("Secondary node %s didn't return free"
                                       " memory information" % node,
                                       errors.ECODE_STATE)
          #TODO(dynmem): do the appropriate check involving MINMEM
          elif be_new[constants.BE_MAXMEM] > nhvinfo["memory_free"]:
            raise errors.OpPrereqError("This change will prevent the instance"
                                       " from failover to its secondary node"
                                       " %s, due to not enough memory" % node,
                                       errors.ECODE_STATE)

    if self.op.runtime_mem:
      remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                instance.name,
                                                instance.hypervisor)
      remote_info.Raise("Error checking node %s" % instance.primary_node)
      if not remote_info.payload: # not running already
        raise errors.OpPrereqError("Instance %s is not running" %
                                   instance.name, errors.ECODE_STATE)

      current_memory = remote_info.payload["memory"]
      if (not self.op.force and
           (self.op.runtime_mem > self.be_proposed[constants.BE_MAXMEM] or
            self.op.runtime_mem < self.be_proposed[constants.BE_MINMEM])):
        raise errors.OpPrereqError("Instance %s must have memory between %d"
                                   " and %d MB of memory unless --force is"
                                   " given" %
                                   (instance.name,
                                    self.be_proposed[constants.BE_MINMEM],
                                    self.be_proposed[constants.BE_MAXMEM]),
                                   errors.ECODE_INVAL)

      delta = self.op.runtime_mem - current_memory
      if delta > 0:
        _CheckNodeFreeMemory(self, instance.primary_node,
                             "ballooning memory for instance %s" %
                             instance.name, delta, instance.hypervisor)

    if self.op.disks and instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Disk operations not supported for"
                                 " diskless instances", errors.ECODE_INVAL)

    def _PrepareNicCreate(_, params, private):
      self._PrepareNicModification(params, private, None, None,
                                   {}, cluster, pnode)
      return (None, None)

    def _PrepareNicMod(_, nic, params, private):
      self._PrepareNicModification(params, private, nic.ip, nic.network,
                                   nic.nicparams, cluster, pnode)
      return None

    def _PrepareNicRemove(_, params, __):
      ip = params.ip
      net = params.network
      if net is not None and ip is not None:
        self.cfg.ReleaseIp(net, ip, self.proc.GetECId())

    # Verify NIC changes (operating on copy)
    nics = instance.nics[:]
    ApplyContainerMods("NIC", nics, None, self.nicmod,
                       _PrepareNicCreate, _PrepareNicMod, _PrepareNicRemove)
    if len(nics) > constants.MAX_NICS:
      raise errors.OpPrereqError("Instance has too many network interfaces"
                                 " (%d), cannot add more" % constants.MAX_NICS,
                                 errors.ECODE_STATE)

    def _PrepareDiskMod(_, disk, params, __):
      disk.name = params.get(constants.IDISK_NAME, None)

    # Verify disk changes (operating on a copy)
    disks = copy.deepcopy(instance.disks)
    ApplyContainerMods("disk", disks, None, self.diskmod, None, _PrepareDiskMod,
                       None)
    utils.ValidateDeviceNames("disk", disks)
    if len(disks) > constants.MAX_DISKS:
      raise errors.OpPrereqError("Instance has too many disks (%d), cannot add"
                                 " more" % constants.MAX_DISKS,
                                 errors.ECODE_STATE)
    disk_sizes = [disk.size for disk in instance.disks]
    disk_sizes.extend(params["size"] for (op, idx, params, private) in
                      self.diskmod if op == constants.DDM_ADD)
    ispec[constants.ISPEC_DISK_COUNT] = len(disk_sizes)
    ispec[constants.ISPEC_DISK_SIZE] = disk_sizes

    if self.op.offline is not None and self.op.offline:
      _CheckInstanceState(self, instance, CAN_CHANGE_INSTANCE_OFFLINE,
                          msg="can't change to offline")

    # Pre-compute NIC changes (necessary to use result in hooks)
    self._nic_chgdesc = []
    if self.nicmod:
      # Operate on copies as this is still in prereq
      nics = [nic.Copy() for nic in instance.nics]
      ApplyContainerMods("NIC", nics, self._nic_chgdesc, self.nicmod,
                         self._CreateNewNic, self._ApplyNicMods, None)
      # Verify that NIC names are unique and valid
      utils.ValidateDeviceNames("NIC", nics)
      self._new_nics = nics
      ispec[constants.ISPEC_NIC_COUNT] = len(self._new_nics)
    else:
      self._new_nics = None
      ispec[constants.ISPEC_NIC_COUNT] = len(instance.nics)

    if not self.op.ignore_ipolicy:
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)

      # Fill ispec with backend parameters
      ispec[constants.ISPEC_SPINDLE_USE] = \
        self.be_new.get(constants.BE_SPINDLE_USE, None)
      ispec[constants.ISPEC_CPU_COUNT] = self.be_new.get(constants.BE_VCPUS,
                                                         None)

      # Copy ispec to verify parameters with min/max values separately
      if self.op.disk_template:
        new_disk_template = self.op.disk_template
      else:
        new_disk_template = instance.disk_template
      ispec_max = ispec.copy()
      ispec_max[constants.ISPEC_MEM_SIZE] = \
        self.be_new.get(constants.BE_MAXMEM, None)
      res_max = _ComputeIPolicyInstanceSpecViolation(ipolicy, ispec_max,
                                                     new_disk_template)
      ispec_min = ispec.copy()
      ispec_min[constants.ISPEC_MEM_SIZE] = \
        self.be_new.get(constants.BE_MINMEM, None)
      res_min = _ComputeIPolicyInstanceSpecViolation(ipolicy, ispec_min,
                                                     new_disk_template)

      if (res_max or res_min):
        # FIXME: Improve error message by including information about whether
        # the upper or lower limit of the parameter fails the ipolicy.
        msg = ("Instance allocation to group %s (%s) violates policy: %s" %
               (group_info, group_info.name,
                utils.CommaJoin(set(res_max + res_min))))
        raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

  def _ConvertPlainToDrbd(self, feedback_fn):
    """Converts an instance from plain to drbd.

    """
    feedback_fn("Converting template to drbd")
    instance = self.instance
    pnode = instance.primary_node
    snode = self.op.remote_node

    assert instance.disk_template == constants.DT_PLAIN

    # create a fake disk info for _GenerateDiskTemplate
    disk_info = [{constants.IDISK_SIZE: d.size, constants.IDISK_MODE: d.mode,
                  constants.IDISK_VG: d.logical_id[0],
                  constants.IDISK_NAME: d.name}
                 for d in instance.disks]
    new_disks = _GenerateDiskTemplate(self, self.op.disk_template,
                                      instance.name, pnode, [snode],
                                      disk_info, None, None, 0, feedback_fn,
                                      self.diskparams)
    anno_disks = rpc.AnnotateDiskParams(constants.DT_DRBD8, new_disks,
                                        self.diskparams)
    p_excl_stor = _IsExclusiveStorageEnabledNodeName(self.cfg, pnode)
    s_excl_stor = _IsExclusiveStorageEnabledNodeName(self.cfg, snode)
    info = _GetInstanceInfoText(instance)
    feedback_fn("Creating additional volumes...")
    # first, create the missing data and meta devices
    for disk in anno_disks:
      # unfortunately this is... not too nice
      _CreateSingleBlockDev(self, pnode, instance, disk.children[1],
                            info, True, p_excl_stor)
      for child in disk.children:
        _CreateSingleBlockDev(self, snode, instance, child, info, True,
                              s_excl_stor)
    # at this stage, all new LVs have been created, we can rename the
    # old ones
    feedback_fn("Renaming original volumes...")
    rename_list = [(o, n.children[0].logical_id)
                   for (o, n) in zip(instance.disks, new_disks)]
    result = self.rpc.call_blockdev_rename(pnode, rename_list)
    result.Raise("Failed to rename original LVs")

    feedback_fn("Initializing DRBD devices...")
    # all child devices are in place, we can now create the DRBD devices
    try:
      for disk in anno_disks:
        for (node, excl_stor) in [(pnode, p_excl_stor), (snode, s_excl_stor)]:
          f_create = node == pnode
          _CreateSingleBlockDev(self, node, instance, disk, info, f_create,
                                excl_stor)
    except errors.GenericError, e:
      feedback_fn("Initializing of DRBD devices failed;"
                  " renaming back original volumes...")
      for disk in new_disks:
        self.cfg.SetDiskID(disk, pnode)
      rename_back_list = [(n.children[0], o.logical_id)
                          for (n, o) in zip(new_disks, instance.disks)]
      result = self.rpc.call_blockdev_rename(pnode, rename_back_list)
      result.Raise("Failed to rename LVs back after error %s" % str(e))
      raise

    # at this point, the instance has been modified
    instance.disk_template = constants.DT_DRBD8
    instance.disks = new_disks
    self.cfg.Update(instance, feedback_fn)

    # Release node locks while waiting for sync
    _ReleaseLocks(self, locking.LEVEL_NODE)

    # disks are created, waiting for sync
    disk_abort = not _WaitForSync(self, instance,
                                  oneshot=not self.op.wait_for_sync)
    if disk_abort:
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance, please cleanup manually")

    # Node resource locks will be released by caller

  def _ConvertDrbdToPlain(self, feedback_fn):
    """Converts an instance from drbd to plain.

    """
    instance = self.instance

    assert len(instance.secondary_nodes) == 1
    assert instance.disk_template == constants.DT_DRBD8

    pnode = instance.primary_node
    snode = instance.secondary_nodes[0]
    feedback_fn("Converting template to plain")

    old_disks = _AnnotateDiskParams(instance, instance.disks, self.cfg)
    new_disks = [d.children[0] for d in instance.disks]

    # copy over size, mode and name
    for parent, child in zip(old_disks, new_disks):
      child.size = parent.size
      child.mode = parent.mode
      child.name = parent.name

    # this is a DRBD disk, return its port to the pool
    # NOTE: this must be done right before the call to cfg.Update!
    for disk in old_disks:
      tcp_port = disk.logical_id[2]
      self.cfg.AddTcpUdpPort(tcp_port)

    # update instance structure
    instance.disks = new_disks
    instance.disk_template = constants.DT_PLAIN
    _UpdateIvNames(0, instance.disks)
    self.cfg.Update(instance, feedback_fn)

    # Release locks in case removing disks takes a while
    _ReleaseLocks(self, locking.LEVEL_NODE)

    feedback_fn("Removing volumes on the secondary node...")
    for disk in old_disks:
      self.cfg.SetDiskID(disk, snode)
      msg = self.rpc.call_blockdev_remove(snode, disk).fail_msg
      if msg:
        self.LogWarning("Could not remove block device %s on node %s,"
                        " continuing anyway: %s", disk.iv_name, snode, msg)

    feedback_fn("Removing unneeded volumes on the primary node...")
    for idx, disk in enumerate(old_disks):
      meta = disk.children[1]
      self.cfg.SetDiskID(meta, pnode)
      msg = self.rpc.call_blockdev_remove(pnode, meta).fail_msg
      if msg:
        self.LogWarning("Could not remove metadata for disk %d on node %s,"
                        " continuing anyway: %s", idx, pnode, msg)

  def _CreateNewDisk(self, idx, params, _):
    """Creates a new disk.

    """
    instance = self.instance

    # add a new disk
    if instance.disk_template in constants.DTS_FILEBASED:
      (file_driver, file_path) = instance.disks[0].logical_id
      file_path = os.path.dirname(file_path)
    else:
      file_driver = file_path = None

    disk = \
      _GenerateDiskTemplate(self, instance.disk_template, instance.name,
                            instance.primary_node, instance.secondary_nodes,
                            [params], file_path, file_driver, idx,
                            self.Log, self.diskparams)[0]

    info = _GetInstanceInfoText(instance)

    logging.info("Creating volume %s for instance %s",
                 disk.iv_name, instance.name)
    # Note: this needs to be kept in sync with _CreateDisks
    #HARDCODE
    for node in instance.all_nodes:
      f_create = (node == instance.primary_node)
      try:
        _CreateBlockDev(self, node, instance, disk, f_create, info, f_create)
      except errors.OpExecError, err:
        self.LogWarning("Failed to create volume %s (%s) on node '%s': %s",
                        disk.iv_name, disk, node, err)

    if self.cluster.prealloc_wipe_disks:
      # Wipe new disk
      _WipeDisks(self, instance,
                 disks=[(idx, disk, 0)])

    return (disk, [
      ("disk/%d" % idx, "add:size=%s,mode=%s" % (disk.size, disk.mode)),
      ])

  @staticmethod
  def _ModifyDisk(idx, disk, params, _):
    """Modifies a disk.

    """
    changes = []
    mode = params.get(constants.IDISK_MODE, None)
    if mode:
      disk.mode = mode
      changes.append(("disk.mode/%d" % idx, disk.mode))

    name = params.get(constants.IDISK_NAME, None)
    disk.name = name
    changes.append(("disk.name/%d" % idx, disk.name))

    return changes

  def _RemoveDisk(self, idx, root, _):
    """Removes a disk.

    """
    (anno_disk,) = _AnnotateDiskParams(self.instance, [root], self.cfg)
    for node, disk in anno_disk.ComputeNodeTree(self.instance.primary_node):
      self.cfg.SetDiskID(disk, node)
      msg = self.rpc.call_blockdev_remove(node, disk).fail_msg
      if msg:
        self.LogWarning("Could not remove disk/%d on node '%s': %s,"
                        " continuing anyway", idx, node, msg)

    # if this is a DRBD disk, return its port to the pool
    if root.dev_type in constants.LDS_DRBD:
      self.cfg.AddTcpUdpPort(root.logical_id[2])

  def _CreateNewNic(self, idx, params, private):
    """Creates data structure for a new network interface.

    """
    mac = params[constants.INIC_MAC]
    ip = params.get(constants.INIC_IP, None)
    net = params.get(constants.INIC_NETWORK, None)
    name = params.get(constants.INIC_NAME, None)
    net_uuid = self.cfg.LookupNetwork(net)
    #TODO: not private.filled?? can a nic have no nicparams??
    nicparams = private.filled
    nobj = objects.NIC(mac=mac, ip=ip, network=net_uuid, name=name,
                       nicparams=nicparams)
    nobj.uuid = self.cfg.GenerateUniqueID(self.proc.GetECId())

    return (nobj, [
      ("nic.%d" % idx,
       "add:mac=%s,ip=%s,mode=%s,link=%s,network=%s" %
       (mac, ip, private.filled[constants.NIC_MODE],
       private.filled[constants.NIC_LINK],
       net)),
      ])

  def _ApplyNicMods(self, idx, nic, params, private):
    """Modifies a network interface.

    """
    changes = []

    for key in [constants.INIC_MAC, constants.INIC_IP, constants.INIC_NAME]:
      if key in params:
        changes.append(("nic.%s/%d" % (key, idx), params[key]))
        setattr(nic, key, params[key])

    new_net = params.get(constants.INIC_NETWORK, nic.network)
    new_net_uuid = self.cfg.LookupNetwork(new_net)
    if new_net_uuid != nic.network:
      changes.append(("nic.network/%d" % idx, new_net))
      nic.network = new_net_uuid

    if private.filled:
      nic.nicparams = private.filled

      for (key, val) in nic.nicparams.items():
        changes.append(("nic.%s/%d" % (key, idx), val))

    return changes

  def Exec(self, feedback_fn):
    """Modifies an instance.

    All parameters take effect only at the next restart of the instance.

    """
    # Process here the warnings from CheckPrereq, as we don't have a
    # feedback_fn there.
    # TODO: Replace with self.LogWarning
    for warn in self.warn:
      feedback_fn("WARNING: %s" % warn)

    assert ((self.op.disk_template is None) ^
            bool(self.owned_locks(locking.LEVEL_NODE_RES))), \
      "Not owning any node resource locks"

    result = []
    instance = self.instance

    # New primary node
    if self.op.pnode:
      instance.primary_node = self.op.pnode

    # runtime memory
    if self.op.runtime_mem:
      rpcres = self.rpc.call_instance_balloon_memory(instance.primary_node,
                                                     instance,
                                                     self.op.runtime_mem)
      rpcres.Raise("Cannot modify instance runtime memory")
      result.append(("runtime_memory", self.op.runtime_mem))

    # Apply disk changes
    ApplyContainerMods("disk", instance.disks, result, self.diskmod,
                       self._CreateNewDisk, self._ModifyDisk, self._RemoveDisk)
    _UpdateIvNames(0, instance.disks)

    if self.op.disk_template:
      if __debug__:
        check_nodes = set(instance.all_nodes)
        if self.op.remote_node:
          check_nodes.add(self.op.remote_node)
        for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
          owned = self.owned_locks(level)
          assert not (check_nodes - owned), \
            ("Not owning the correct locks, owning %r, expected at least %r" %
             (owned, check_nodes))

      r_shut = _ShutdownInstanceDisks(self, instance)
      if not r_shut:
        raise errors.OpExecError("Cannot shutdown instance disks, unable to"
                                 " proceed with disk template conversion")
      mode = (instance.disk_template, self.op.disk_template)
      try:
        self._DISK_CONVERSIONS[mode](self, feedback_fn)
      except:
        self.cfg.ReleaseDRBDMinors(instance.name)
        raise
      result.append(("disk_template", self.op.disk_template))

      assert instance.disk_template == self.op.disk_template, \
        ("Expected disk template '%s', found '%s'" %
         (self.op.disk_template, instance.disk_template))

    # Release node and resource locks if there are any (they might already have
    # been released during disk conversion)
    _ReleaseLocks(self, locking.LEVEL_NODE)
    _ReleaseLocks(self, locking.LEVEL_NODE_RES)

    # Apply NIC changes
    if self._new_nics is not None:
      instance.nics = self._new_nics
      result.extend(self._nic_chgdesc)

    # hvparams changes
    if self.op.hvparams:
      instance.hvparams = self.hv_inst
      for key, val in self.op.hvparams.iteritems():
        result.append(("hv/%s" % key, val))

    # beparams changes
    if self.op.beparams:
      instance.beparams = self.be_inst
      for key, val in self.op.beparams.iteritems():
        result.append(("be/%s" % key, val))

    # OS change
    if self.op.os_name:
      instance.os = self.op.os_name

    # osparams changes
    if self.op.osparams:
      instance.osparams = self.os_inst
      for key, val in self.op.osparams.iteritems():
        result.append(("os/%s" % key, val))

    if self.op.offline is None:
      # Ignore
      pass
    elif self.op.offline:
      # Mark instance as offline
      self.cfg.MarkInstanceOffline(instance.name)
      result.append(("admin_state", constants.ADMINST_OFFLINE))
    else:
      # Mark instance as online, but stopped
      self.cfg.MarkInstanceDown(instance.name)
      result.append(("admin_state", constants.ADMINST_DOWN))

    self.cfg.Update(instance, feedback_fn, self.proc.GetECId())

    assert not (self.owned_locks(locking.LEVEL_NODE_RES) or
                self.owned_locks(locking.LEVEL_NODE)), \
      "All node locks should have been released by now"

    return result

  _DISK_CONVERSIONS = {
    (constants.DT_PLAIN, constants.DT_DRBD8): _ConvertPlainToDrbd,
    (constants.DT_DRBD8, constants.DT_PLAIN): _ConvertDrbdToPlain,
    }


class LUInstanceChangeGroup(LogicalUnit):
  HPATH = "instance-change-group"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = _ShareAll()

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    self._ExpandAndLockInstance()

    if self.op.target_groups:
      self.req_target_uuids = map(self.cfg.LookupNodeGroup,
                                  self.op.target_groups)
    else:
      self.req_target_uuids = None

    self.op.iallocator = _GetDefaultIAllocator(self.cfg, self.op.iallocator)

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      if self.req_target_uuids:
        lock_groups = set(self.req_target_uuids)

        # Lock all groups used by instance optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        instance_groups = self.cfg.GetInstanceNodeGroups(self.op.instance_name)
        lock_groups.update(instance_groups)
      else:
        # No target groups, need to lock all of them
        lock_groups = locking.ALL_SET

      self.needed_locks[locking.LEVEL_NODEGROUP] = lock_groups

    elif level == locking.LEVEL_NODE:
      if self.req_target_uuids:
        # Lock all nodes used by instances
        self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
        self._LockInstancesNodes()

        # Lock all nodes in all potential target groups
        lock_groups = (frozenset(self.owned_locks(locking.LEVEL_NODEGROUP)) -
                       self.cfg.GetInstanceNodeGroups(self.op.instance_name))
        member_nodes = [node_name
                        for group in lock_groups
                        for node_name in self.cfg.GetNodeGroup(group).members]
        self.needed_locks[locking.LEVEL_NODE].extend(member_nodes)
      else:
        # Lock all nodes as all groups are potential targets
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def CheckPrereq(self):
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert (self.req_target_uuids is None or
            owned_groups.issuperset(self.req_target_uuids))
    assert owned_instances == set([self.op.instance_name])

    # Get instance information
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)

    # Check if node groups for locked instance are still correct
    assert owned_nodes.issuperset(self.instance.all_nodes), \
      ("Instance %s's nodes changed while we kept the lock" %
       self.op.instance_name)

    inst_groups = _CheckInstanceNodeGroups(self.cfg, self.op.instance_name,
                                           owned_groups)

    if self.req_target_uuids:
      # User requested specific target groups
      self.target_uuids = frozenset(self.req_target_uuids)
    else:
      # All groups except those used by the instance are potential targets
      self.target_uuids = owned_groups - inst_groups

    conflicting_groups = self.target_uuids & inst_groups
    if conflicting_groups:
      raise errors.OpPrereqError("Can't use group(s) '%s' as targets, they are"
                                 " used by the instance '%s'" %
                                 (utils.CommaJoin(conflicting_groups),
                                  self.op.instance_name),
                                 errors.ECODE_INVAL)

    if not self.target_uuids:
      raise errors.OpPrereqError("There are no possible target groups",
                                 errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    assert self.target_uuids

    env = {
      "TARGET_GROUPS": " ".join(self.target_uuids),
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    instances = list(self.owned_locks(locking.LEVEL_INSTANCE))

    assert instances == [self.op.instance_name], "Instance not locked"

    req = iallocator.IAReqGroupChange(instances=instances,
                                      target_groups=list(self.target_uuids))
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute solution for changing group of"
                                 " instance '%s' using iallocator '%s': %s" %
                                 (self.op.instance_name, self.op.iallocator,
                                  ial.info), errors.ECODE_NORES)

    jobs = _LoadNodeEvacResult(self, ial.result, self.op.early_release, False)

    self.LogInfo("Iallocator returned %s job(s) for changing group of"
                 " instance '%s'", len(jobs), self.op.instance_name)

    return ResultWithJobs(jobs)


class TLMigrateInstance(Tasklet):
  """Tasklet class for instance migration.

  @type live: boolean
  @ivar live: whether the migration will be done live or non-live;
      this variable is initalized only after CheckPrereq has run
  @type cleanup: boolean
  @ivar cleanup: Wheater we cleanup from a failed migration
  @type iallocator: string
  @ivar iallocator: The iallocator used to determine target_node
  @type target_node: string
  @ivar target_node: If given, the target_node to reallocate the instance to
  @type failover: boolean
  @ivar failover: Whether operation results in failover or migration
  @type fallback: boolean
  @ivar fallback: Whether fallback to failover is allowed if migration not
                  possible
  @type ignore_consistency: boolean
  @ivar ignore_consistency: Wheter we should ignore consistency between source
                            and target node
  @type shutdown_timeout: int
  @ivar shutdown_timeout: In case of failover timeout of the shutdown
  @type ignore_ipolicy: bool
  @ivar ignore_ipolicy: If true, we can ignore instance policy when migrating

  """

  # Constants
  _MIGRATION_POLL_INTERVAL = 1      # seconds
  _MIGRATION_FEEDBACK_INTERVAL = 10 # seconds

  def __init__(self, lu, instance_name, cleanup, failover, fallback,
               ignore_consistency, allow_runtime_changes, shutdown_timeout,
               ignore_ipolicy):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_name = instance_name
    self.cleanup = cleanup
    self.live = False # will be overridden later
    self.failover = failover
    self.fallback = fallback
    self.ignore_consistency = ignore_consistency
    self.shutdown_timeout = shutdown_timeout
    self.ignore_ipolicy = ignore_ipolicy
    self.allow_runtime_changes = allow_runtime_changes

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    instance_name = _ExpandInstanceName(self.lu.cfg, self.instance_name)
    instance = self.cfg.GetInstanceInfo(instance_name)
    assert instance is not None
    self.instance = instance
    cluster = self.cfg.GetClusterInfo()

    if (not self.cleanup and
        not instance.admin_state == constants.ADMINST_UP and
        not self.failover and self.fallback):
      self.lu.LogInfo("Instance is marked down or offline, fallback allowed,"
                      " switching to failover")
      self.failover = True

    if instance.disk_template not in constants.DTS_MIRRORED:
      if self.failover:
        text = "failovers"
      else:
        text = "migrations"
      raise errors.OpPrereqError("Instance's disk layout '%s' does not allow"
                                 " %s" % (instance.disk_template, text),
                                 errors.ECODE_STATE)

    if instance.disk_template in constants.DTS_EXT_MIRROR:
      _CheckIAllocatorOrNode(self.lu, "iallocator", "target_node")

      if self.lu.op.iallocator:
        assert locking.NAL in self.lu.owned_locks(locking.LEVEL_NODE_ALLOC)
        self._RunAllocator()
      else:
        # We set set self.target_node as it is required by
        # BuildHooksEnv
        self.target_node = self.lu.op.target_node

      # Check that the target node is correct in terms of instance policy
      nodeinfo = self.cfg.GetNodeInfo(self.target_node)
      group_info = self.cfg.GetNodeGroup(nodeinfo.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)
      _CheckTargetNodeIPolicy(self.lu, ipolicy, instance, nodeinfo, self.cfg,
                              ignore=self.ignore_ipolicy)

      # self.target_node is already populated, either directly or by the
      # iallocator run
      target_node = self.target_node
      if self.target_node == instance.primary_node:
        raise errors.OpPrereqError("Cannot migrate instance %s"
                                   " to its primary (%s)" %
                                   (instance.name, instance.primary_node),
                                   errors.ECODE_STATE)

      if len(self.lu.tasklets) == 1:
        # It is safe to release locks only when we're the only tasklet
        # in the LU
        _ReleaseLocks(self.lu, locking.LEVEL_NODE,
                      keep=[instance.primary_node, self.target_node])
        _ReleaseLocks(self.lu, locking.LEVEL_NODE_ALLOC)

    else:
      assert not self.lu.glm.is_owned(locking.LEVEL_NODE_ALLOC)

      secondary_nodes = instance.secondary_nodes
      if not secondary_nodes:
        raise errors.ConfigurationError("No secondary node but using"
                                        " %s disk template" %
                                        instance.disk_template)
      target_node = secondary_nodes[0]
      if self.lu.op.iallocator or (self.lu.op.target_node and
                                   self.lu.op.target_node != target_node):
        if self.failover:
          text = "failed over"
        else:
          text = "migrated"
        raise errors.OpPrereqError("Instances with disk template %s cannot"
                                   " be %s to arbitrary nodes"
                                   " (neither an iallocator nor a target"
                                   " node can be passed)" %
                                   (instance.disk_template, text),
                                   errors.ECODE_INVAL)
      nodeinfo = self.cfg.GetNodeInfo(target_node)
      group_info = self.cfg.GetNodeGroup(nodeinfo.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)
      _CheckTargetNodeIPolicy(self.lu, ipolicy, instance, nodeinfo, self.cfg,
                              ignore=self.ignore_ipolicy)

    i_be = cluster.FillBE(instance)

    # check memory requirements on the secondary node
    if (not self.cleanup and
         (not self.failover or instance.admin_state == constants.ADMINST_UP)):
      self.tgt_free_mem = _CheckNodeFreeMemory(self.lu, target_node,
                                               "migrating instance %s" %
                                               instance.name,
                                               i_be[constants.BE_MINMEM],
                                               instance.hypervisor)
    else:
      self.lu.LogInfo("Not checking memory on the secondary node as"
                      " instance will not be started")

    # check if failover must be forced instead of migration
    if (not self.cleanup and not self.failover and
        i_be[constants.BE_ALWAYS_FAILOVER]):
      self.lu.LogInfo("Instance configured to always failover; fallback"
                      " to failover")
      self.failover = True

    # check bridge existance
    _CheckInstanceBridgesExist(self.lu, instance, node=target_node)

    if not self.cleanup:
      _CheckNodeNotDrained(self.lu, target_node)
      if not self.failover:
        result = self.rpc.call_instance_migratable(instance.primary_node,
                                                   instance)
        if result.fail_msg and self.fallback:
          self.lu.LogInfo("Can't migrate, instance offline, fallback to"
                          " failover")
          self.failover = True
        else:
          result.Raise("Can't migrate, please use failover",
                       prereq=True, ecode=errors.ECODE_STATE)

    assert not (self.failover and self.cleanup)

    if not self.failover:
      if self.lu.op.live is not None and self.lu.op.mode is not None:
        raise errors.OpPrereqError("Only one of the 'live' and 'mode'"
                                   " parameters are accepted",
                                   errors.ECODE_INVAL)
      if self.lu.op.live is not None:
        if self.lu.op.live:
          self.lu.op.mode = constants.HT_MIGRATION_LIVE
        else:
          self.lu.op.mode = constants.HT_MIGRATION_NONLIVE
        # reset the 'live' parameter to None so that repeated
        # invocations of CheckPrereq do not raise an exception
        self.lu.op.live = None
      elif self.lu.op.mode is None:
        # read the default value from the hypervisor
        i_hv = cluster.FillHV(self.instance, skip_globals=False)
        self.lu.op.mode = i_hv[constants.HV_MIGRATION_MODE]

      self.live = self.lu.op.mode == constants.HT_MIGRATION_LIVE
    else:
      # Failover is never live
      self.live = False

    if not (self.failover or self.cleanup):
      remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                instance.name,
                                                instance.hypervisor)
      remote_info.Raise("Error checking instance on node %s" %
                        instance.primary_node)
      instance_running = bool(remote_info.payload)
      if instance_running:
        self.current_mem = int(remote_info.payload["memory"])

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    assert locking.NAL in self.lu.owned_locks(locking.LEVEL_NODE_ALLOC)

    # FIXME: add a self.ignore_ipolicy option
    req = iallocator.IAReqRelocate(name=self.instance_name,
                                   relocate_from=[self.instance.primary_node])
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.lu.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.lu.op.iallocator, ial.info),
                                 errors.ECODE_NORES)
    self.target_node = ial.result[0]
    self.lu.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                    self.instance_name, self.lu.op.iallocator,
                    utils.CommaJoin(ial.result))

  def _WaitUntilSync(self):
    """Poll with custom rpc for disk sync.

    This uses our own step-based rpc call.

    """
    self.feedback_fn("* wait until resync is done")
    all_done = False
    while not all_done:
      all_done = True
      result = self.rpc.call_drbd_wait_sync(self.all_nodes,
                                            self.nodes_ip,
                                            (self.instance.disks,
                                             self.instance))
      min_percent = 100
      for node, nres in result.items():
        nres.Raise("Cannot resync disks on node %s" % node)
        node_done, node_percent = nres.payload
        all_done = all_done and node_done
        if node_percent is not None:
          min_percent = min(min_percent, node_percent)
      if not all_done:
        if min_percent < 100:
          self.feedback_fn("   - progress: %.1f%%" % min_percent)
        time.sleep(2)

  def _EnsureSecondary(self, node):
    """Demote a node to secondary.

    """
    self.feedback_fn("* switching node %s to secondary mode" % node)

    for dev in self.instance.disks:
      self.cfg.SetDiskID(dev, node)

    result = self.rpc.call_blockdev_close(node, self.instance.name,
                                          self.instance.disks)
    result.Raise("Cannot change disk to secondary on node %s" % node)

  def _GoStandalone(self):
    """Disconnect from the network.

    """
    self.feedback_fn("* changing into standalone mode")
    result = self.rpc.call_drbd_disconnect_net(self.all_nodes, self.nodes_ip,
                                               self.instance.disks)
    for node, nres in result.items():
      nres.Raise("Cannot disconnect disks node %s" % node)

  def _GoReconnect(self, multimaster):
    """Reconnect to the network.

    """
    if multimaster:
      msg = "dual-master"
    else:
      msg = "single-master"
    self.feedback_fn("* changing disks into %s mode" % msg)
    result = self.rpc.call_drbd_attach_net(self.all_nodes, self.nodes_ip,
                                           (self.instance.disks, self.instance),
                                           self.instance.name, multimaster)
    for node, nres in result.items():
      nres.Raise("Cannot change disks config on node %s" % node)

  def _ExecCleanup(self):
    """Try to cleanup after a failed migration.

    The cleanup is done by:
      - check that the instance is running only on one node
        (and update the config if needed)
      - change disks on its secondary node to secondary
      - wait until disks are fully synchronized
      - disconnect from the network
      - change disks into single-master mode
      - wait again until disks are fully synchronized

    """
    instance = self.instance
    target_node = self.target_node
    source_node = self.source_node

    # check running on only one node
    self.feedback_fn("* checking where the instance actually runs"
                     " (if this hangs, the hypervisor might be in"
                     " a bad state)")
    ins_l = self.rpc.call_instance_list(self.all_nodes, [instance.hypervisor])
    for node, result in ins_l.items():
      result.Raise("Can't contact node %s" % node)

    runningon_source = instance.name in ins_l[source_node].payload
    runningon_target = instance.name in ins_l[target_node].payload

    if runningon_source and runningon_target:
      raise errors.OpExecError("Instance seems to be running on two nodes,"
                               " or the hypervisor is confused; you will have"
                               " to ensure manually that it runs only on one"
                               " and restart this operation")

    if not (runningon_source or runningon_target):
      raise errors.OpExecError("Instance does not seem to be running at all;"
                               " in this case it's safer to repair by"
                               " running 'gnt-instance stop' to ensure disk"
                               " shutdown, and then restarting it")

    if runningon_target:
      # the migration has actually succeeded, we need to update the config
      self.feedback_fn("* instance running on secondary node (%s),"
                       " updating config" % target_node)
      instance.primary_node = target_node
      self.cfg.Update(instance, self.feedback_fn)
      demoted_node = source_node
    else:
      self.feedback_fn("* instance confirmed to be running on its"
                       " primary node (%s)" % source_node)
      demoted_node = target_node

    if instance.disk_template in constants.DTS_INT_MIRROR:
      self._EnsureSecondary(demoted_node)
      try:
        self._WaitUntilSync()
      except errors.OpExecError:
        # we ignore here errors, since if the device is standalone, it
        # won't be able to sync
        pass
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()

    self.feedback_fn("* done")

  def _RevertDiskStatus(self):
    """Try to revert the disk status after a failed migration.

    """
    target_node = self.target_node
    if self.instance.disk_template in constants.DTS_EXT_MIRROR:
      return

    try:
      self._EnsureSecondary(target_node)
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()
    except errors.OpExecError, err:
      self.lu.LogWarning("Migration failed and I can't reconnect the drives,"
                         " please try to recover the instance manually;"
                         " error '%s'" % str(err))

  def _AbortMigration(self):
    """Call the hypervisor code to abort a started migration.

    """
    instance = self.instance
    target_node = self.target_node
    source_node = self.source_node
    migration_info = self.migration_info

    abort_result = self.rpc.call_instance_finalize_migration_dst(target_node,
                                                                 instance,
                                                                 migration_info,
                                                                 False)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on target node %s: %s",
                    target_node, abort_msg)
      # Don't raise an exception here, as we stil have to try to revert the
      # disk status, even if this step failed.

    abort_result = self.rpc.call_instance_finalize_migration_src(
      source_node, instance, False, self.live)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on source node %s: %s",
                    source_node, abort_msg)

  def _ExecMigration(self):
    """Migrate an instance.

    The migrate is done by:
      - change the disks into dual-master mode
      - wait until disks are fully synchronized again
      - migrate the instance
      - change disks on the new secondary node (the old primary) to secondary
      - wait until disks are fully synchronized
      - change disks into single-master mode

    """
    instance = self.instance
    target_node = self.target_node
    source_node = self.source_node

    # Check for hypervisor version mismatch and warn the user.
    nodeinfo = self.rpc.call_node_info([source_node, target_node],
                                       None, [self.instance.hypervisor], False)
    for ninfo in nodeinfo.values():
      ninfo.Raise("Unable to retrieve node information from node '%s'" %
                  ninfo.node)
    (_, _, (src_info, )) = nodeinfo[source_node].payload
    (_, _, (dst_info, )) = nodeinfo[target_node].payload

    if ((constants.HV_NODEINFO_KEY_VERSION in src_info) and
        (constants.HV_NODEINFO_KEY_VERSION in dst_info)):
      src_version = src_info[constants.HV_NODEINFO_KEY_VERSION]
      dst_version = dst_info[constants.HV_NODEINFO_KEY_VERSION]
      if src_version != dst_version:
        self.feedback_fn("* warning: hypervisor version mismatch between"
                         " source (%s) and target (%s) node" %
                         (src_version, dst_version))

    self.feedback_fn("* checking disk consistency between source and target")
    for (idx, dev) in enumerate(instance.disks):
      if not _CheckDiskConsistency(self.lu, instance, dev, target_node, False):
        raise errors.OpExecError("Disk %s is degraded or not fully"
                                 " synchronized on target node,"
                                 " aborting migration" % idx)

    if self.current_mem > self.tgt_free_mem:
      if not self.allow_runtime_changes:
        raise errors.OpExecError("Memory ballooning not allowed and not enough"
                                 " free memory to fit instance %s on target"
                                 " node %s (have %dMB, need %dMB)" %
                                 (instance.name, target_node,
                                  self.tgt_free_mem, self.current_mem))
      self.feedback_fn("* setting instance memory to %s" % self.tgt_free_mem)
      rpcres = self.rpc.call_instance_balloon_memory(instance.primary_node,
                                                     instance,
                                                     self.tgt_free_mem)
      rpcres.Raise("Cannot modify instance runtime memory")

    # First get the migration information from the remote node
    result = self.rpc.call_migration_info(source_node, instance)
    msg = result.fail_msg
    if msg:
      log_err = ("Failed fetching source migration information from %s: %s" %
                 (source_node, msg))
      logging.error(log_err)
      raise errors.OpExecError(log_err)

    self.migration_info = migration_info = result.payload

    if self.instance.disk_template not in constants.DTS_EXT_MIRROR:
      # Then switch the disks to master/master mode
      self._EnsureSecondary(target_node)
      self._GoStandalone()
      self._GoReconnect(True)
      self._WaitUntilSync()

    self.feedback_fn("* preparing %s to accept the instance" % target_node)
    result = self.rpc.call_accept_instance(target_node,
                                           instance,
                                           migration_info,
                                           self.nodes_ip[target_node])

    msg = result.fail_msg
    if msg:
      logging.error("Instance pre-migration failed, trying to revert"
                    " disk status: %s", msg)
      self.feedback_fn("Pre-migration failed, aborting")
      self._AbortMigration()
      self._RevertDiskStatus()
      raise errors.OpExecError("Could not pre-migrate instance %s: %s" %
                               (instance.name, msg))

    self.feedback_fn("* migrating instance to %s" % target_node)
    result = self.rpc.call_instance_migrate(source_node, instance,
                                            self.nodes_ip[target_node],
                                            self.live)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration failed, trying to revert"
                    " disk status: %s", msg)
      self.feedback_fn("Migration failed, aborting")
      self._AbortMigration()
      self._RevertDiskStatus()
      raise errors.OpExecError("Could not migrate instance %s: %s" %
                               (instance.name, msg))

    self.feedback_fn("* starting memory transfer")
    last_feedback = time.time()
    while True:
      result = self.rpc.call_instance_get_migration_status(source_node,
                                                           instance)
      msg = result.fail_msg
      ms = result.payload   # MigrationStatus instance
      if msg or (ms.status in constants.HV_MIGRATION_FAILED_STATUSES):
        logging.error("Instance migration failed, trying to revert"
                      " disk status: %s", msg)
        self.feedback_fn("Migration failed, aborting")
        self._AbortMigration()
        self._RevertDiskStatus()
        if not msg:
          msg = "hypervisor returned failure"
        raise errors.OpExecError("Could not migrate instance %s: %s" %
                                 (instance.name, msg))

      if result.payload.status != constants.HV_MIGRATION_ACTIVE:
        self.feedback_fn("* memory transfer complete")
        break

      if (utils.TimeoutExpired(last_feedback,
                               self._MIGRATION_FEEDBACK_INTERVAL) and
          ms.transferred_ram is not None):
        mem_progress = 100 * float(ms.transferred_ram) / float(ms.total_ram)
        self.feedback_fn("* memory transfer progress: %.2f %%" % mem_progress)
        last_feedback = time.time()

      time.sleep(self._MIGRATION_POLL_INTERVAL)

    result = self.rpc.call_instance_finalize_migration_src(source_node,
                                                           instance,
                                                           True,
                                                           self.live)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed"
                    " on the source node: %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    instance.primary_node = target_node

    # distribute new instance config to the other nodes
    self.cfg.Update(instance, self.feedback_fn)

    result = self.rpc.call_instance_finalize_migration_dst(target_node,
                                                           instance,
                                                           migration_info,
                                                           True)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed"
                    " on the target node: %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    if self.instance.disk_template not in constants.DTS_EXT_MIRROR:
      self._EnsureSecondary(source_node)
      self._WaitUntilSync()
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()

    # If the instance's disk template is `rbd' or `ext' and there was a
    # successful migration, unmap the device from the source node.
    if self.instance.disk_template in (constants.DT_RBD, constants.DT_EXT):
      disks = _ExpandCheckDisks(instance, instance.disks)
      self.feedback_fn("* unmapping instance's disks from %s" % source_node)
      for disk in disks:
        result = self.rpc.call_blockdev_shutdown(source_node, (disk, instance))
        msg = result.fail_msg
        if msg:
          logging.error("Migration was successful, but couldn't unmap the"
                        " block device %s on source node %s: %s",
                        disk.iv_name, source_node, msg)
          logging.error("You need to unmap the device %s manually on %s",
                        disk.iv_name, source_node)

    self.feedback_fn("* done")

  def _ExecFailover(self):
    """Failover an instance.

    The failover is done by shutting it down on its present node and
    starting it on the secondary.

    """
    instance = self.instance
    primary_node = self.cfg.GetNodeInfo(instance.primary_node)

    source_node = instance.primary_node
    target_node = self.target_node

    if instance.admin_state == constants.ADMINST_UP:
      self.feedback_fn("* checking disk consistency between source and target")
      for (idx, dev) in enumerate(instance.disks):
        # for drbd, these are drbd over lvm
        if not _CheckDiskConsistency(self.lu, instance, dev, target_node,
                                     False):
          if primary_node.offline:
            self.feedback_fn("Node %s is offline, ignoring degraded disk %s on"
                             " target node %s" %
                             (primary_node.name, idx, target_node))
          elif not self.ignore_consistency:
            raise errors.OpExecError("Disk %s is degraded on target node,"
                                     " aborting failover" % idx)
    else:
      self.feedback_fn("* not checking disk consistency as instance is not"
                       " running")

    self.feedback_fn("* shutting down instance on source node")
    logging.info("Shutting down instance %s on node %s",
                 instance.name, source_node)

    result = self.rpc.call_instance_shutdown(source_node, instance,
                                             self.shutdown_timeout,
                                             self.lu.op.reason)
    msg = result.fail_msg
    if msg:
      if self.ignore_consistency or primary_node.offline:
        self.lu.LogWarning("Could not shutdown instance %s on node %s,"
                           " proceeding anyway; please make sure node"
                           " %s is down; error details: %s",
                           instance.name, source_node, source_node, msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, source_node, msg))

    self.feedback_fn("* deactivating the instance's disks on source node")
    if not _ShutdownInstanceDisks(self.lu, instance, ignore_primary=True):
      raise errors.OpExecError("Can't shut down the instance's disks")

    instance.primary_node = target_node
    # distribute new instance config to the other nodes
    self.cfg.Update(instance, self.feedback_fn)

    # Only start the instance if it's marked as up
    if instance.admin_state == constants.ADMINST_UP:
      self.feedback_fn("* activating the instance's disks on target node %s" %
                       target_node)
      logging.info("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, _ = _AssembleInstanceDisks(self.lu, instance,
                                           ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self.lu, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      self.feedback_fn("* starting the instance on the target node %s" %
                       target_node)
      result = self.rpc.call_instance_start(target_node, (instance, None, None),
                                            False, self.lu.op.reason)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self.lu, instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (instance.name, target_node, msg))

  def Exec(self, feedback_fn):
    """Perform the migration.

    """
    self.feedback_fn = feedback_fn
    self.source_node = self.instance.primary_node

    # FIXME: if we implement migrate-to-any in DRBD, this needs fixing
    if self.instance.disk_template in constants.DTS_INT_MIRROR:
      self.target_node = self.instance.secondary_nodes[0]
      # Otherwise self.target_node has been populated either
      # directly, or through an iallocator.

    self.all_nodes = [self.source_node, self.target_node]
    self.nodes_ip = dict((name, node.secondary_ip) for (name, node)
                         in self.cfg.GetMultiNodeInfo(self.all_nodes))

    if self.failover:
      feedback_fn("Failover instance %s" % self.instance.name)
      self._ExecFailover()
    else:
      feedback_fn("Migrating instance %s" % self.instance.name)

      if self.cleanup:
        return self._ExecCleanup()
      else:
        return self._ExecMigration()
