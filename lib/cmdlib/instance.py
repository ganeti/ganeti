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
import logging
import os

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
from ganeti import pathutils
from ganeti import rpc
from ganeti import utils

from ganeti.cmdlib.base import NoHooksLU, LogicalUnit, ResultWithJobs

from ganeti.cmdlib.common import INSTANCE_DOWN, \
  INSTANCE_NOT_RUNNING, CAN_CHANGE_INSTANCE_OFFLINE, CheckNodeOnline, \
  ShareAll, GetDefaultIAllocator, CheckInstanceNodeGroups, \
  LoadNodeEvacResult, CheckIAllocatorOrNode, CheckParamsNotGlobal, \
  IsExclusiveStorageEnabledNode, CheckHVParams, CheckOSParams, \
  AnnotateDiskParams, GetUpdatedParams, ExpandInstanceUuidAndName, \
  ComputeIPolicySpecViolation, CheckInstanceState, ExpandNodeUuidAndName, \
  CheckDiskTemplateEnabled, IsValidDiskAccessModeCombination
from ganeti.cmdlib.instance_storage import CreateDisks, \
  CheckNodesFreeDiskPerVG, WipeDisks, WipeOrCleanupDisks, WaitForSync, \
  IsExclusiveStorageEnabledNodeUuid, CreateSingleBlockDev, ComputeDisks, \
  CheckRADOSFreeSpace, ComputeDiskSizePerVG, GenerateDiskTemplate, \
  StartInstanceDisks, ShutdownInstanceDisks, AssembleInstanceDisks, \
  CheckSpindlesExclusiveStorage
from ganeti.cmdlib.instance_utils import BuildInstanceHookEnvByObject, \
  GetClusterDomainSecret, BuildInstanceHookEnv, NICListToTuple, \
  NICToTuple, CheckNodeNotDrained, RemoveInstance, CopyLockList, \
  ReleaseLocks, CheckNodeVmCapable, CheckTargetNodeIPolicy, \
  GetInstanceInfoText, RemoveDisks, CheckNodeFreeMemory, \
  CheckInstanceBridgesExist, CheckNicsBridgesExist, CheckNodeHasOS

import ganeti.masterd.instance


#: Type description for changes as returned by L{_ApplyContainerMods}'s
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


def _CreateInstanceAllocRequest(op, disks, nics, beparams, node_name_whitelist):
  """Wrapper around IAReqInstanceAlloc.

  @param op: The instance opcode
  @param disks: The computed disks
  @param nics: The computed nics
  @param beparams: The full filled beparams
  @param node_name_whitelist: List of nodes which should appear as online to the
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
                                       node_whitelist=node_name_whitelist)


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
    vlan = nic.get(constants.INIC_VLAN, None)

    if net is None or net.lower() == constants.VALUE_NONE:
      net = None
    else:
      if nic_mode_req is not None or link is not None:
        raise errors.OpPrereqError("If network is given, no mode or link"
                                   " is allowed to be passed",
                                   errors.ECODE_INVAL)

    if vlan is not None and nic_mode != constants.NIC_MODE_OVS:
      raise errors.OpPrereqError("VLAN is given, but network mode is not"
                                 " openvswitch", errors.ECODE_INVAL)

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
    if vlan:
      nicparams[constants.NIC_VLAN] = vlan

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


def _CheckForConflictingIp(lu, ip, node_uuid):
  """In case of conflicting IP address raise error.

  @type ip: string
  @param ip: IP address
  @type node_uuid: string
  @param node_uuid: node UUID

  """
  (conf_net, _) = lu.cfg.CheckIPInNodeGroup(ip, node_uuid)
  if conf_net is not None:
    raise errors.OpPrereqError(("The requested IP address (%s) belongs to"
                                " network %s, but the target NIC does not." %
                                (ip, conf_net)),
                               errors.ECODE_STATE)

  return (None, None)


def _ComputeIPolicyInstanceSpecViolation(
  ipolicy, instance_spec, disk_template,
  _compute_fn=ComputeIPolicySpecViolation):
  """Compute if instance specs meets the specs of ipolicy.

  @type ipolicy: dict
  @param ipolicy: The ipolicy to verify against
  @param instance_spec: dict
  @param instance_spec: The instance spec to verify
  @type disk_template: string
  @param disk_template: the disk template of the instance
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{ComputeIPolicySpecViolation}

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


class LUInstanceCreate(LogicalUnit):
  """Create an instance.

  """
  HPATH = "instance-add"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def _CheckDiskTemplateValid(self):
    """Checks validity of disk template.

    """
    cluster = self.cfg.GetClusterInfo()
    if self.op.disk_template is None:
      # FIXME: It would be better to take the default disk template from the
      # ipolicy, but for the ipolicy we need the primary node, which we get from
      # the iallocator, which wants the disk template as input. To solve this
      # chicken-and-egg problem, it should be possible to specify just a node
      # group from the iallocator and take the ipolicy from that.
      self.op.disk_template = cluster.enabled_disk_templates[0]
    CheckDiskTemplateEnabled(cluster, self.op.disk_template)

  def _CheckDiskArguments(self):
    """Checks validity of disk-related arguments.

    """
    # check that disk's names are unique and valid
    utils.ValidateDeviceNames("disk", self.op.disks)

    self._CheckDiskTemplateValid()

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

  def _CheckVLANArguments(self):
    """ Check validity of VLANs if given

    """
    for nic in self.op.nics:
      vlan = nic.get(constants.INIC_VLAN, None)
      if vlan:
        if vlan[0] == ".":
          # vlan starting with dot means single untagged vlan,
          # might be followed by trunk (:)
          if not vlan[1:].isdigit():
            vlanlist = vlan[1:].split(':')
            for vl in vlanlist:
              if not vl.isdigit():
                raise errors.OpPrereqError("Specified VLAN parameter is "
                                           "invalid : %s" % vlan,
                                             errors.ECODE_INVAL)
        elif vlan[0] == ":":
          # Trunk - tagged only
          vlanlist = vlan[1:].split(':')
          for vl in vlanlist:
            if not vl.isdigit():
              raise errors.OpPrereqError("Specified VLAN parameter is invalid"
                                           " : %s" % vlan, errors.ECODE_INVAL)
        elif vlan.isdigit():
          # This is the simplest case. No dots, only single digit
          # -> Create untagged access port, dot needs to be added
          nic[constants.INIC_VLAN] = "." + vlan
        else:
          raise errors.OpPrereqError("Specified VLAN parameter is invalid"
                                       " : %s" % vlan, errors.ECODE_INVAL)

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

    self._CheckVLANArguments()

    self._CheckDiskArguments()
    assert self.op.disk_template is not None

    # instance name verification
    if self.op.name_check:
      self.hostname = _CheckHostnameSane(self, self.op.instance_name)
      self.op.instance_name = self.hostname.name
      # used in CheckPrereq for ip ping check
      self.check_ip = self.hostname.ip
    else:
      self.check_ip = None

    # file storage checks
    if (self.op.file_driver and
        not self.op.file_driver in constants.FILE_DRIVER):
      raise errors.OpPrereqError("Invalid file driver name '%s'" %
                                 self.op.file_driver, errors.ECODE_INVAL)

    # set default file_driver if unset and required
    if (not self.op.file_driver and
        self.op.disk_template in constants.DTS_FILEBASED):
      self.op.file_driver = constants.FD_LOOP

    ### Node/iallocator related checks
    CheckIAllocatorOrNode(self, "iallocator", "pnode")

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
    elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
      self._cds = GetClusterDomainSecret()

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

    # this is just a preventive check, but someone might still add this
    # instance in the meantime, and creation will fail at lock-add time
    if self.op.instance_name in\
      [inst.name for inst in self.cfg.GetAllInstancesInfo().values()]:
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 self.op.instance_name, errors.ECODE_EXISTS)

    self.add_locks[locking.LEVEL_INSTANCE] = self.op.instance_name

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
      (self.op.pnode_uuid, self.op.pnode) = \
        ExpandNodeUuidAndName(self.cfg, self.op.pnode_uuid, self.op.pnode)
      nodelist = [self.op.pnode_uuid]
      if self.op.snode is not None:
        (self.op.snode_uuid, self.op.snode) = \
          ExpandNodeUuidAndName(self.cfg, self.op.snode_uuid, self.op.snode)
        nodelist.append(self.op.snode_uuid)
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
        (self.op.src_node_uuid, self.op.src_node) = (_, src_node) = \
          ExpandNodeUuidAndName(self.cfg, self.op.src_node_uuid, src_node)
        if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
          self.needed_locks[locking.LEVEL_NODE].append(self.op.src_node_uuid)
        if not os.path.isabs(src_path):
          self.op.src_path = \
            utils.PathJoin(pathutils.EXPORT_DIR, src_path)

    self.needed_locks[locking.LEVEL_NODE_RES] = \
      CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    if self.op.opportunistic_locking:
      # Only consider nodes for which a lock is held
      node_name_whitelist = self.cfg.GetNodeNames(
        self.owned_locks(locking.LEVEL_NODE))
    else:
      node_name_whitelist = None

    req = _CreateInstanceAllocRequest(self.op, self.disks,
                                      self.nics, self.be_full,
                                      node_name_whitelist)
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

    (self.op.pnode_uuid, self.op.pnode) = \
      ExpandNodeUuidAndName(self.cfg, None, ial.result[0])
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(ial.result))

    assert req.RequiredNodes() in (1, 2), "Wrong node count from iallocator"

    if req.RequiredNodes() == 2:
      (self.op.snode_uuid, self.op.snode) = \
        ExpandNodeUuidAndName(self.cfg, None, ial.result[1])

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

    env.update(BuildInstanceHookEnv(
      name=self.op.instance_name,
      primary_node_name=self.op.pnode,
      secondary_node_names=self.cfg.GetNodeNames(self.secondaries),
      status=self.op.start,
      os_type=self.op.os_type,
      minmem=self.be_full[constants.BE_MINMEM],
      maxmem=self.be_full[constants.BE_MAXMEM],
      vcpus=self.be_full[constants.BE_VCPUS],
      nics=NICListToTuple(self, self.nics),
      disk_template=self.op.disk_template,
      disks=[(d[constants.IDISK_NAME], d.get("uuid", ""),
              d[constants.IDISK_SIZE], d[constants.IDISK_MODE])
             for d in self.disks],
      bep=self.be_full,
      hvp=self.hv_full,
      hypervisor_name=self.op.hypervisor,
      tags=self.op.tags,
      ))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.op.pnode_uuid] + self.secondaries
    return nl, nl

  def _ReadExportInfo(self):
    """Reads the export information from disk.

    It will override the opcode source node and path with the actual
    information, if these two were not specified before.

    @return: the export information

    """
    assert self.op.mode == constants.INSTANCE_IMPORT

    if self.op.src_node_uuid is None:
      locked_nodes = self.owned_locks(locking.LEVEL_NODE)
      exp_list = self.rpc.call_export_list(locked_nodes)
      found = False
      for node_uuid in exp_list:
        if exp_list[node_uuid].fail_msg:
          continue
        if self.op.src_path in exp_list[node_uuid].payload:
          found = True
          self.op.src_node = self.cfg.GetNodeInfo(node_uuid).name
          self.op.src_node_uuid = node_uuid
          self.op.src_path = utils.PathJoin(pathutils.EXPORT_DIR,
                                            self.op.src_path)
          break
      if not found:
        raise errors.OpPrereqError("No export found for relative path %s" %
                                   self.op.src_path, errors.ECODE_INVAL)

    CheckNodeOnline(self, self.op.src_node_uuid)
    result = self.rpc.call_export_info(self.op.src_node_uuid, self.op.src_path)
    result.Raise("No export or invalid export found in dir %s" %
                 self.op.src_path)

    export_info = objects.SerializableConfigParser.Loads(str(result.payload))
    if not export_info.has_section(constants.INISECT_EXP):
      raise errors.ProgrammerError("Corrupted export config",
                                   errors.ECODE_ENVIRON)

    ei_version = export_info.get(constants.INISECT_EXP, "version")
    if int(ei_version) != constants.EXPORT_VERSION:
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
            nic_param_name = "nic%d_%s" % (idx, name)
            if einfo.has_option(constants.INISECT_INS, nic_param_name):
              v = einfo.get(constants.INISECT_INS, nic_param_name)
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
    CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS, "hypervisor",
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
    self.disks = ComputeDisks(self.op, default_vg)

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
    keep_locks = filter(None, [self.op.pnode_uuid, self.op.snode_uuid,
                               self.op.src_node_uuid])
    ReleaseLocks(self, locking.LEVEL_NODE, keep=keep_locks)
    ReleaseLocks(self, locking.LEVEL_NODE_RES, keep=keep_locks)
    ReleaseLocks(self, locking.LEVEL_NODE_ALLOC)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES)), \
      "Node locks differ from node resource locks"

    #### node related checks

    # check primary node
    self.pnode = pnode = self.cfg.GetNodeInfo(self.op.pnode_uuid)
    assert self.pnode is not None, \
      "Cannot retrieve locked node %s" % self.op.pnode_uuid
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
        netparams = self.cfg.GetGroupNetParams(net_uuid, self.pnode.uuid)
        if netparams is None:
          raise errors.OpPrereqError("No netparams found for network"
                                     " %s. Probably not connected to"
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
        _CheckForConflictingIp(self, nic.ip, self.pnode.uuid)

    # mirror node verification
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.snode_uuid == pnode.uuid:
        raise errors.OpPrereqError("The secondary node cannot be the"
                                   " primary node", errors.ECODE_INVAL)
      CheckNodeOnline(self, self.op.snode_uuid)
      CheckNodeNotDrained(self, self.op.snode_uuid)
      CheckNodeVmCapable(self, self.op.snode_uuid)
      self.secondaries.append(self.op.snode_uuid)

      snode = self.cfg.GetNodeInfo(self.op.snode_uuid)
      if pnode.group != snode.group:
        self.LogWarning("The primary and secondary nodes are in two"
                        " different node groups; the disk parameters"
                        " from the first disk's node group will be"
                        " used")

    nodes = [pnode]
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      nodes.append(snode)
    has_es = lambda n: IsExclusiveStorageEnabledNode(self.cfg, n)
    excl_stor = compat.any(map(has_es, nodes))
    if excl_stor and not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      raise errors.OpPrereqError("Disk template %s not supported with"
                                 " exclusive storage" % self.op.disk_template,
                                 errors.ECODE_STATE)
    for disk in self.disks:
      CheckSpindlesExclusiveStorage(disk, excl_stor, True)

    node_uuids = [pnode.uuid] + self.secondaries

    if not self.adopt_disks:
      if self.op.disk_template == constants.DT_RBD:
        # _CheckRADOSFreeSpace() is just a placeholder.
        # Any function that checks prerequisites can be placed here.
        # Check if there is enough space on the RADOS cluster.
        CheckRADOSFreeSpace()
      elif self.op.disk_template == constants.DT_EXT:
        # FIXME: Function that checks prereqs if needed
        pass
      elif self.op.disk_template in constants.DTS_LVM:
        # Check lv size requirements, if not adopting
        req_sizes = ComputeDiskSizePerVG(self.op.disk_template, self.disks)
        CheckNodesFreeDiskPerVG(self, node_uuids, req_sizes)
      else:
        # FIXME: add checks for other, non-adopting, non-lvm disk templates
        pass

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

      vg_names = self.rpc.call_vg_list([pnode.uuid])[pnode.uuid]
      vg_names.Raise("Cannot get VG information from node %s" % pnode.name)

      node_lvs = self.rpc.call_lv_list([pnode.uuid],
                                       vg_names.payload.keys())[pnode.uuid]
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

      node_disks = self.rpc.call_bdev_sizes([pnode.uuid],
                                            list(all_disks))[pnode.uuid]
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

    # Check disk access param to be compatible with specified hypervisor
    node_info = self.cfg.GetNodeInfo(self.op.pnode_uuid)
    node_group = self.cfg.GetNodeGroup(node_info.group)
    disk_params = self.cfg.GetGroupDiskParams(node_group)
    access_type = disk_params[self.op.disk_template].get(
      constants.RBD_ACCESS, constants.DISK_KERNELSPACE
    )

    if not IsValidDiskAccessModeCombination(self.op.hypervisor,
                                            self.op.disk_template,
                                            access_type):
      raise errors.OpPrereqError("Selected hypervisor (%s) cannot be"
                                 " used with %s disk access param" %
                                 (self.op.hypervisor, access_type),
                                  errors.ECODE_STATE)

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

    CheckHVParams(self, node_uuids, self.op.hypervisor, self.op.hvparams)

    CheckNodeHasOS(self, pnode.uuid, self.op.os_type, self.op.force_variant)
    # check OS parameters (remotely)
    CheckOSParams(self, True, node_uuids, self.op.os_type, self.os_full)

    CheckNicsBridgesExist(self, self.nics, self.pnode.uuid)

    #TODO: _CheckExtParams (remotely)
    # Check parameters for extstorage

    # memory check on primary node
    #TODO(dynmem): use MINMEM for checking
    if self.op.start:
      hvfull = objects.FillDict(cluster.hvparams.get(self.op.hypervisor, {}),
                                self.op.hvparams)
      CheckNodeFreeMemory(self, self.pnode.uuid,
                          "creating instance %s" % self.op.instance_name,
                          self.be_full[constants.BE_MAXMEM],
                          self.op.hypervisor, hvfull)

    self.dry_run_result = list(node_uuids)

  def Exec(self, feedback_fn):
    """Create and add the instance to the cluster.

    """
    assert not (self.owned_locks(locking.LEVEL_NODE_RES) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Node locks differ from node resource locks"
    assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

    ht_kind = self.op.hypervisor
    if ht_kind in constants.HTS_REQ_PORT:
      network_port = self.cfg.AllocatePort()
    else:
      network_port = None

    instance_uuid = self.cfg.GenerateUniqueID(self.proc.GetECId())

    # This is ugly but we got a chicken-egg problem here
    # We can only take the group disk parameters, as the instance
    # has no disks yet (we are generating them right here).
    nodegroup = self.cfg.GetNodeGroup(self.pnode.group)
    disks = GenerateDiskTemplate(self,
                                 self.op.disk_template,
                                 instance_uuid, self.pnode.uuid,
                                 self.secondaries,
                                 self.disks,
                                 self.instance_file_storage_dir,
                                 self.op.file_driver,
                                 0,
                                 feedback_fn,
                                 self.cfg.GetGroupDiskParams(nodegroup))

    iobj = objects.Instance(name=self.op.instance_name,
                            uuid=instance_uuid,
                            os=self.op.os_type,
                            primary_node=self.pnode.uuid,
                            nics=self.nics, disks=disks,
                            disk_template=self.op.disk_template,
                            disks_active=False,
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
        result = self.rpc.call_blockdev_rename(self.pnode.uuid,
                                               zip(tmp_disks, rename_to))
        result.Raise("Failed to rename adoped LVs")
    else:
      feedback_fn("* creating instance disks...")
      try:
        CreateDisks(self, iobj)
      except errors.OpExecError:
        self.LogWarning("Device creation failed")
        self.cfg.ReleaseDRBDMinors(self.op.instance_name)
        raise

    feedback_fn("adding instance %s to cluster config" % self.op.instance_name)

    self.cfg.AddInstance(iobj, self.proc.GetECId())

    # Declare that we don't want to remove the instance lock anymore, as we've
    # added the instance to the config
    del self.remove_locks[locking.LEVEL_INSTANCE]

    if self.op.mode == constants.INSTANCE_IMPORT:
      # Release unused nodes
      ReleaseLocks(self, locking.LEVEL_NODE, keep=[self.op.src_node_uuid])
    else:
      # Release all nodes
      ReleaseLocks(self, locking.LEVEL_NODE)

    disk_abort = False
    if not self.adopt_disks and self.cfg.GetClusterInfo().prealloc_wipe_disks:
      feedback_fn("* wiping instance disks...")
      try:
        WipeDisks(self, iobj)
      except errors.OpExecError, err:
        logging.exception("Wiping disks failed")
        self.LogWarning("Wiping instance disks failed (%s)", err)
        disk_abort = True

    if disk_abort:
      # Something is already wrong with the disks, don't do anything else
      pass
    elif self.op.wait_for_sync:
      disk_abort = not WaitForSync(self, iobj)
    elif iobj.disk_template in constants.DTS_INT_MIRROR:
      # make sure the disks are not degraded (still sync-ing is ok)
      feedback_fn("* checking mirrors status")
      disk_abort = not WaitForSync(self, iobj, oneshot=True)
    else:
      disk_abort = False

    if disk_abort:
      RemoveDisks(self, iobj)
      self.cfg.RemoveInstance(iobj.uuid)
      # Make sure the instance lock gets removed
      self.remove_locks[locking.LEVEL_INSTANCE] = iobj.name
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance")

    # instance disks are now active
    iobj.disks_active = True

    # Release all node resource locks
    ReleaseLocks(self, locking.LEVEL_NODE_RES)

    if iobj.disk_template != constants.DT_DISKLESS and not self.adopt_disks:
      if self.op.mode == constants.INSTANCE_CREATE:
        if not self.op.no_install:
          pause_sync = (iobj.disk_template in constants.DTS_INT_MIRROR and
                        not self.op.wait_for_sync)
          if pause_sync:
            feedback_fn("* pausing disk sync to install instance OS")
            result = self.rpc.call_blockdev_pause_resume_sync(self.pnode.uuid,
                                                              (iobj.disks,
                                                               iobj), True)
            for idx, success in enumerate(result.payload):
              if not success:
                logging.warn("pause-sync of instance %s for disk %d failed",
                             self.op.instance_name, idx)

          feedback_fn("* running the instance OS create scripts...")
          # FIXME: pass debug option from opcode to backend
          os_add_result = \
            self.rpc.call_instance_os_add(self.pnode.uuid, (iobj, None), False,
                                          self.op.debug_level)
          if pause_sync:
            feedback_fn("* resuming disk sync")
            result = self.rpc.call_blockdev_pause_resume_sync(self.pnode.uuid,
                                                              (iobj.disks,
                                                               iobj), False)
            for idx, success in enumerate(result.payload):
              if not success:
                logging.warn("resume-sync of instance %s for disk %d failed",
                             self.op.instance_name, idx)

          os_add_result.Raise("Could not add os for instance %s"
                              " on node %s" % (self.op.instance_name,
                                               self.pnode.name))

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
                                               ((iobj.disks[idx], iobj), idx),
                                               None)
            transfers.append(dt)

          import_result = \
            masterd.instance.TransferInstanceData(self, feedback_fn,
                                                  self.op.src_node_uuid,
                                                  self.pnode.uuid,
                                                  self.pnode.secondary_ip,
                                                  self.op.compress,
                                                  iobj, transfers)
          if not compat.all(import_result):
            self.LogWarning("Some disks for instance %s on node %s were not"
                            " imported successfully" % (self.op.instance_name,
                                                        self.pnode.name))

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

          assert iobj.primary_node == self.pnode.uuid
          disk_results = \
            masterd.instance.RemoteImport(self, feedback_fn, iobj, self.pnode,
                                          self.source_x509_ca,
                                          self._cds, self.op.compress, timeouts)
          if not compat.all(disk_results):
            # TODO: Should the instance still be started, even if some disks
            # failed to import (valid for local imports, too)?
            self.LogWarning("Some disks for instance %s on node %s were not"
                            " imported successfully" % (self.op.instance_name,
                                                        self.pnode.name))

          rename_from = self.source_instance_name

        else:
          # also checked in the prereq part
          raise errors.ProgrammerError("Unknown OS initialization mode '%s'"
                                       % self.op.mode)

        # Run rename script on newly imported instance
        assert iobj.name == self.op.instance_name
        feedback_fn("Running rename script for %s" % self.op.instance_name)
        result = self.rpc.call_instance_run_rename(self.pnode.uuid, iobj,
                                                   rename_from,
                                                   self.op.debug_level)
        result.Warn("Failed to run rename script for %s on node %s" %
                    (self.op.instance_name, self.pnode.name), self.LogWarning)

    assert not self.owned_locks(locking.LEVEL_NODE_RES)

    if self.op.start:
      iobj.admin_state = constants.ADMINST_UP
      self.cfg.Update(iobj, feedback_fn)
      logging.info("Starting instance %s on node %s", self.op.instance_name,
                   self.pnode.name)
      feedback_fn("* starting instance...")
      result = self.rpc.call_instance_start(self.pnode.uuid, (iobj, None, None),
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
    env = BuildInstanceHookEnvByObject(self, self.instance)
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
    (self.op.instance_uuid, self.op.instance_name) = \
      ExpandInstanceUuidAndName(self.cfg, self.op.instance_uuid,
                                self.op.instance_name)
    instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert instance is not None

    # It should actually not happen that an instance is running with a disabled
    # disk template, but in case it does, the renaming of file-based instances
    # will fail horribly. Thus, we test it before.
    if (instance.disk_template in constants.DTS_FILEBASED and
        self.op.new_name != instance.name):
      CheckDiskTemplateEnabled(self.cfg.GetClusterInfo(),
                               instance.disk_template)

    CheckNodeOnline(self, instance.primary_node)
    CheckInstanceState(self, instance, INSTANCE_NOT_RUNNING,
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

    instance_names = [inst.name for
                      inst in self.cfg.GetAllInstancesInfo().values()]
    if new_name in instance_names and new_name != instance.name:
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 new_name, errors.ECODE_EXISTS)

  def Exec(self, feedback_fn):
    """Rename the instance.

    """
    old_name = self.instance.name

    rename_file_storage = False
    if (self.instance.disk_template in constants.DTS_FILEBASED and
        self.op.new_name != self.instance.name):
      old_file_storage_dir = os.path.dirname(
                               self.instance.disks[0].logical_id[1])
      rename_file_storage = True

    self.cfg.RenameInstance(self.instance.uuid, self.op.new_name)
    # Change the instance lock. This is definitely safe while we hold the BGL.
    # Otherwise the new lock would have to be added in acquired mode.
    assert self.REQ_BGL
    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER)
    self.glm.remove(locking.LEVEL_INSTANCE, old_name)
    self.glm.add(locking.LEVEL_INSTANCE, self.op.new_name)

    # re-read the instance from the configuration after rename
    renamed_inst = self.cfg.GetInstanceInfo(self.instance.uuid)

    if rename_file_storage:
      new_file_storage_dir = os.path.dirname(
                               renamed_inst.disks[0].logical_id[1])
      result = self.rpc.call_file_storage_dir_rename(renamed_inst.primary_node,
                                                     old_file_storage_dir,
                                                     new_file_storage_dir)
      result.Raise("Could not rename on node %s directory '%s' to '%s'"
                   " (but the instance has been renamed in Ganeti)" %
                   (self.cfg.GetNodeName(renamed_inst.primary_node),
                    old_file_storage_dir, new_file_storage_dir))

    StartInstanceDisks(self, renamed_inst, None)
    # update info on disks
    info = GetInstanceInfoText(renamed_inst)
    for (idx, disk) in enumerate(renamed_inst.disks):
      for node_uuid in renamed_inst.all_nodes:
        result = self.rpc.call_blockdev_setinfo(node_uuid,
                                                (disk, renamed_inst), info)
        result.Warn("Error setting info on node %s for disk %s" %
                    (self.cfg.GetNodeName(node_uuid), idx), self.LogWarning)
    try:
      result = self.rpc.call_instance_run_rename(renamed_inst.primary_node,
                                                 renamed_inst, old_name,
                                                 self.op.debug_level)
      result.Warn("Could not run OS rename script for instance %s on node %s"
                  " (but the instance has been renamed in Ganeti)" %
                  (renamed_inst.name,
                   self.cfg.GetNodeName(renamed_inst.primary_node)),
                  self.LogWarning)
    finally:
      ShutdownInstanceDisks(self, renamed_inst)

    return renamed_inst.name


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
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = BuildInstanceHookEnvByObject(self, self.instance)
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
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

  def Exec(self, feedback_fn):
    """Remove the instance.

    """
    logging.info("Shutting down instance %s on node %s", self.instance.name,
                 self.cfg.GetNodeName(self.instance.primary_node))

    result = self.rpc.call_instance_shutdown(self.instance.primary_node,
                                             self.instance,
                                             self.op.shutdown_timeout,
                                             self.op.reason)
    if self.op.ignore_failures:
      result.Warn("Warning: can't shutdown instance", feedback_fn)
    else:
      result.Raise("Could not shutdown instance %s on node %s" %
                   (self.instance.name,
                    self.cfg.GetNodeName(self.instance.primary_node)))

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))
    assert not (set(self.instance.all_nodes) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Not owning correct locks"

    RemoveInstance(self, feedback_fn, self.instance, self.op.ignore_failures)


class LUInstanceMove(LogicalUnit):
  """Move an instance by data-copying.

  """
  HPATH = "instance-move"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    (self.op.target_node_uuid, self.op.target_node) = \
      ExpandNodeUuidAndName(self.cfg, self.op.target_node_uuid,
                            self.op.target_node)
    self.needed_locks[locking.LEVEL_NODE] = [self.op.target_node_uuid]
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes(primary_only=True)
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and target nodes of the instance.

    """
    env = {
      "TARGET_NODE": self.op.target_node,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }
    env.update(BuildInstanceHookEnvByObject(self, self.instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [
      self.cfg.GetMasterNode(),
      self.instance.primary_node,
      self.op.target_node_uuid,
      ]
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if self.instance.disk_template not in constants.DTS_COPYABLE:
      raise errors.OpPrereqError("Disk template %s not suitable for copying" %
                                 self.instance.disk_template,
                                 errors.ECODE_STATE)

    target_node = self.cfg.GetNodeInfo(self.op.target_node_uuid)
    assert target_node is not None, \
      "Cannot retrieve locked node %s" % self.op.target_node

    self.target_node_uuid = target_node.uuid
    if target_node.uuid == self.instance.primary_node:
      raise errors.OpPrereqError("Instance %s is already on the node %s" %
                                 (self.instance.name, target_node.name),
                                 errors.ECODE_STATE)

    cluster = self.cfg.GetClusterInfo()
    bep = cluster.FillBE(self.instance)

    for idx, dsk in enumerate(self.instance.disks):
      if dsk.dev_type not in (constants.DT_PLAIN, constants.DT_FILE,
                              constants.DT_SHARED_FILE):
        raise errors.OpPrereqError("Instance disk %d has a complex layout,"
                                   " cannot copy" % idx, errors.ECODE_STATE)

    CheckNodeOnline(self, target_node.uuid)
    CheckNodeNotDrained(self, target_node.uuid)
    CheckNodeVmCapable(self, target_node.uuid)
    group_info = self.cfg.GetNodeGroup(target_node.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    CheckTargetNodeIPolicy(self, ipolicy, self.instance, target_node, self.cfg,
                           ignore=self.op.ignore_ipolicy)

    if self.instance.admin_state == constants.ADMINST_UP:
      # check memory requirements on the target node
      CheckNodeFreeMemory(
          self, target_node.uuid, "failing over instance %s" %
          self.instance.name, bep[constants.BE_MAXMEM],
          self.instance.hypervisor,
          cluster.hvparams[self.instance.hypervisor])
    else:
      self.LogInfo("Not checking memory on the secondary node as"
                   " instance will not be started")

    # check bridge existance
    CheckInstanceBridgesExist(self, self.instance, node_uuid=target_node.uuid)

  def Exec(self, feedback_fn):
    """Move an instance.

    The move is done by shutting it down on its present node, copying
    the data over (slow) and starting it on the new node.

    """
    source_node = self.cfg.GetNodeInfo(self.instance.primary_node)
    target_node = self.cfg.GetNodeInfo(self.target_node_uuid)

    self.LogInfo("Shutting down instance %s on source node %s",
                 self.instance.name, source_node.name)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    result = self.rpc.call_instance_shutdown(source_node.uuid, self.instance,
                                             self.op.shutdown_timeout,
                                             self.op.reason)
    if self.op.ignore_consistency:
      result.Warn("Could not shutdown instance %s on node %s. Proceeding"
                  " anyway. Please make sure node %s is down. Error details" %
                  (self.instance.name, source_node.name, source_node.name),
                  self.LogWarning)
    else:
      result.Raise("Could not shutdown instance %s on node %s" %
                   (self.instance.name, source_node.name))

    # create the target disks
    try:
      CreateDisks(self, self.instance, target_node_uuid=target_node.uuid)
    except errors.OpExecError:
      self.LogWarning("Device creation failed")
      self.cfg.ReleaseDRBDMinors(self.instance.uuid)
      raise

    errs = []
    transfers = []
    # activate, get path, create transfer jobs
    for idx, disk in enumerate(self.instance.disks):
      # FIXME: pass debug option from opcode to backend
      dt = masterd.instance.DiskTransfer("disk/%s" % idx,
                                         constants.IEIO_RAW_DISK,
                                         (disk, self.instance),
                                         constants.IEIO_RAW_DISK,
                                         (disk, self.instance),
                                         None)
      transfers.append(dt)

    import_result = \
      masterd.instance.TransferInstanceData(self, feedback_fn,
                                            source_node.uuid,
                                            target_node.uuid,
                                            target_node.secondary_ip,
                                            self.op.compress,
                                            self.instance, transfers)
    if not compat.all(import_result):
      errs.append("Failed to transfer instance data")

    if errs:
      self.LogWarning("Some disks failed to copy, aborting")
      try:
        RemoveDisks(self, self.instance, target_node_uuid=target_node.uuid)
      finally:
        self.cfg.ReleaseDRBDMinors(self.instance.uuid)
        raise errors.OpExecError("Errors during disk copy: %s" %
                                 (",".join(errs),))

    self.instance.primary_node = target_node.uuid
    self.cfg.Update(self.instance, feedback_fn)

    self.LogInfo("Removing the disks on the original node")
    RemoveDisks(self, self.instance, target_node_uuid=source_node.uuid)

    # Only start the instance if it's marked as up
    if self.instance.admin_state == constants.ADMINST_UP:
      self.LogInfo("Starting instance %s on node %s",
                   self.instance.name, target_node.name)

      disks_ok, _ = AssembleInstanceDisks(self, self.instance,
                                          ignore_secondaries=True)
      if not disks_ok:
        ShutdownInstanceDisks(self, self.instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      result = self.rpc.call_instance_start(target_node.uuid,
                                            (self.instance, None, None), False,
                                            self.op.reason)
      msg = result.fail_msg
      if msg:
        ShutdownInstanceDisks(self, self.instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (self.instance.name, target_node.name, msg))


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

    if not has_nodes and self.op.iallocator is None:
      default_iallocator = self.cfg.GetDefaultIAllocator()
      if default_iallocator:
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
    self.share_locks = ShareAll()
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
        (inst.pnode_uuid, inst.pnode) = \
          ExpandNodeUuidAndName(self.cfg, inst.pnode_uuid, inst.pnode)
        nodeslist.append(inst.pnode_uuid)
        if inst.snode is not None:
          (inst.snode_uuid, inst.snode) = \
            ExpandNodeUuidAndName(self.cfg, inst.snode_uuid, inst.snode)
          nodeslist.append(inst.snode_uuid)

      self.needed_locks[locking.LEVEL_NODE] = nodeslist
      # Lock resources of instance's primary and secondary nodes (copy to
      # prevent accidential modification)
      self.needed_locks[locking.LEVEL_NODE_RES] = list(nodeslist)

  def CheckPrereq(self):
    """Check prerequisite.

    """
    if self.op.iallocator:
      cluster = self.cfg.GetClusterInfo()
      default_vg = self.cfg.GetVGName()
      ec_id = self.proc.GetECId()

      if self.op.opportunistic_locking:
        # Only consider nodes for which a lock is held
        node_whitelist = self.cfg.GetNodeNames(
                           list(self.owned_locks(locking.LEVEL_NODE)))
      else:
        node_whitelist = None

      insts = [_CreateInstanceAllocRequest(op, ComputeDisks(op, default_vg),
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
    if self.op.iallocator:
      (allocatable, failed_insts) = self.ia_result
      allocatable_insts = map(compat.fst, allocatable)
    else:
      allocatable_insts = [op.instance_name for op in self.op.instances]
      failed_insts = []

    return {
      constants.ALLOCATABLE_KEY: allocatable_insts,
      constants.FAILED_KEY: failed_insts,
      }

  def Exec(self, feedback_fn):
    """Executes the opcode.

    """
    jobs = []
    if self.op.iallocator:
      op2inst = dict((op.instance_name, op) for op in self.op.instances)
      (allocatable, failed) = self.ia_result

      for (name, node_names) in allocatable:
        op = op2inst.pop(name)

        (op.pnode_uuid, op.pnode) = \
          ExpandNodeUuidAndName(self.cfg, None, node_names[0])
        if len(node_names) > 1:
          (op.snode_uuid, op.snode) = \
            ExpandNodeUuidAndName(self.cfg, None, node_names[1])

          jobs.append([op])

        missing = set(op2inst.keys()) - set(failed)
        assert not missing, \
          "Iallocator did return incomplete result: %s" % \
          utils.CommaJoin(missing)
    else:
      jobs.extend([op] for op in self.op.instances)

    return ResultWithJobs(jobs, **self._ConstructPartialResult())


class _InstNicModPrivate:
  """Data structure for network interface modifications.

  Used by L{LUInstanceSetParams}.

  """
  def __init__(self):
    self.params = None
    self.filled = None


def _PrepareContainerMods(mods, private_fn):
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


def _CheckNodesPhysicalCPUs(lu, node_uuids, requested, hypervisor_specs):
  """Checks if nodes have enough physical CPUs

  This function checks if all given nodes have the needed number of
  physical CPUs. In case any node has less CPUs or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type node_uuids: C{list}
  @param node_uuids: the list of node UUIDs to check
  @type requested: C{int}
  @param requested: the minimum acceptable number of physical CPUs
  @type hypervisor_specs: list of pairs (string, dict of strings)
  @param hypervisor_specs: list of hypervisor specifications in
      pairs (hypervisor_name, hvparams)
  @raise errors.OpPrereqError: if the node doesn't have enough CPUs,
      or we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info(node_uuids, None, hypervisor_specs)
  for node_uuid in node_uuids:
    info = nodeinfo[node_uuid]
    node_name = lu.cfg.GetNodeName(node_uuid)
    info.Raise("Cannot get current information from node %s" % node_name,
               prereq=True, ecode=errors.ECODE_ENVIRON)
    (_, _, (hv_info, )) = info.payload
    num_cpus = hv_info.get("cpu_total", None)
    if not isinstance(num_cpus, int):
      raise errors.OpPrereqError("Can't compute the number of physical CPUs"
                                 " on node %s, result was '%s'" %
                                 (node_name, num_cpus), errors.ECODE_ENVIRON)
    if requested > num_cpus:
      raise errors.OpPrereqError("Node %s has %s physical CPUs, but %s are "
                                 "required" % (node_name, num_cpus, requested),
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


def _ApplyContainerMods(kind, container, chgdesc, mods,
                        create_fn, modify_fn, remove_fn,
                        post_add_fn=None):
  """Applies descriptions in C{mods} to C{container}.

  @type kind: string
  @param kind: One-word item description
  @type container: list
  @param container: Container to modify
  @type chgdesc: None or list
  @param chgdesc: List of applied changes
  @type mods: list
  @param mods: Modifications as returned by L{_PrepareContainerMods}
  @type create_fn: callable
  @param create_fn: Callback for creating a new item (L{constants.DDM_ADD});
    receives absolute item index, parameters and private data object as added
    by L{_PrepareContainerMods}, returns tuple containing new item and changes
    as list
  @type modify_fn: callable
  @param modify_fn: Callback for modifying an existing item
    (L{constants.DDM_MODIFY}); receives absolute item index, item, parameters
    and private data object as added by L{_PrepareContainerMods}, returns
    changes as list
  @type remove_fn: callable
  @param remove_fn: Callback on removing item; receives absolute item index,
    item and private data object as added by L{_PrepareContainerMods}
  @type post_add_fn: callable
  @param post_add_fn: Callable for post-processing a newly created item after
    it has been put into the container. It receives the index of the new item
    and the new item as parameters.

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

      if post_add_fn is not None:
        post_add_fn(addidx, item)

    else:
      # Retrieve existing item
      (absidx, item) = GetItemFromContainer(identifier, kind, container)

      if op == constants.DDM_REMOVE:
        assert not params

        changes = [("%s/%s" % (kind, absidx), "remove")]

        if remove_fn is not None:
          msg = remove_fn(absidx, item, private)
          if msg:
            changes.append(("%s/%s" % (kind, absidx), msg))

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
  def _VerifyDiskModification(op, params, excl_stor):
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
      size = int(size)

      params[constants.IDISK_SIZE] = size
      name = params.get(constants.IDISK_NAME, None)
      if name is not None and name.lower() == constants.VALUE_NONE:
        params[constants.IDISK_NAME] = None

      CheckSpindlesExclusiveStorage(params, excl_stor, True)

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
            self.op.osparams or self.op.offline is not None or
            self.op.runtime_mem or self.op.pnode):
      raise errors.OpPrereqError("No changes submitted", errors.ECODE_INVAL)

    if self.op.hvparams:
      CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS,
                           "hypervisor", "instance", "cluster")

    self.op.disks = self._UpgradeDiskNicMods(
      "disk", self.op.disks, ht.TSetParamsMods(ht.TIDiskParams))
    self.op.nics = self._UpgradeDiskNicMods(
      "NIC", self.op.nics, ht.TSetParamsMods(ht.TINicParams))

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
      (self.op.pnode_uuid, self.op.pnode) = \
        ExpandNodeUuidAndName(self.cfg, self.op.pnode_uuid, self.op.pnode)

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
        self.cfg.GetInstanceNodeGroups(self.op.instance_uuid)
    elif level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
      if self.op.disk_template and self.op.remote_node:
        (self.op.remote_node_uuid, self.op.remote_node) = \
          ExpandNodeUuidAndName(self.cfg, self.op.remote_node_uuid,
                                self.op.remote_node)
        self.needed_locks[locking.LEVEL_NODE].append(self.op.remote_node_uuid)
    elif level == locking.LEVEL_NODE_RES and self.op.disk_template:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

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
        nics.append(NICToTuple(self, n))

      args["nics"] = nics

    env = BuildInstanceHookEnvByObject(self, self.instance, override=args)
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
                              old_params, cluster, pnode_uuid):

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
      netparams = self.cfg.GetGroupNetParams(new_net_uuid, pnode_uuid)
      if not netparams:
        raise errors.OpPrereqError("No netparams found for the network"
                                   " %s, probably not connected" %
                                   new_net_obj.name, errors.ECODE_INVAL)
      new_params = dict(netparams)
    else:
      new_params = GetUpdatedParams(old_params, update_params_dict)

    utils.ForceDictType(new_params, constants.NICS_PARAMETER_TYPES)

    new_filled_params = cluster.SimpleFillNIC(new_params)
    objects.NIC.CheckParameterSyntax(new_filled_params)

    new_mode = new_filled_params[constants.NIC_MODE]
    if new_mode == constants.NIC_MODE_BRIDGED:
      bridge = new_filled_params[constants.NIC_LINK]
      msg = self.rpc.call_bridges_exist(pnode_uuid, [bridge]).fail_msg
      if msg:
        msg = "Error checking bridges on node '%s': %s" % \
                (self.cfg.GetNodeName(pnode_uuid), msg)
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
          _CheckForConflictingIp(self, new_ip, pnode_uuid)

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
    pnode_uuid = self.instance.primary_node
    if self.instance.disk_template == self.op.disk_template:
      raise errors.OpPrereqError("Instance already has disk template %s" %
                                 self.instance.disk_template,
                                 errors.ECODE_INVAL)

    if not self.cluster.IsDiskTemplateEnabled(self.op.disk_template):
      raise errors.OpPrereqError("Disk template '%s' is not enabled for this"
                                 " cluster." % self.op.disk_template)

    if (self.instance.disk_template,
        self.op.disk_template) not in self._DISK_CONVERSIONS:
      raise errors.OpPrereqError("Unsupported disk template conversion from"
                                 " %s to %s" % (self.instance.disk_template,
                                                self.op.disk_template),
                                 errors.ECODE_INVAL)
    CheckInstanceState(self, self.instance, INSTANCE_DOWN,
                       msg="cannot change disk template")
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.remote_node_uuid == pnode_uuid:
        raise errors.OpPrereqError("Given new secondary node %s is the same"
                                   " as the primary node of the instance" %
                                   self.op.remote_node, errors.ECODE_STATE)
      CheckNodeOnline(self, self.op.remote_node_uuid)
      CheckNodeNotDrained(self, self.op.remote_node_uuid)
      # FIXME: here we assume that the old instance type is DT_PLAIN
      assert self.instance.disk_template == constants.DT_PLAIN
      disks = [{constants.IDISK_SIZE: d.size,
                constants.IDISK_VG: d.logical_id[0]}
               for d in self.instance.disks]
      required = ComputeDiskSizePerVG(self.op.disk_template, disks)
      CheckNodesFreeDiskPerVG(self, [self.op.remote_node_uuid], required)

      snode_info = self.cfg.GetNodeInfo(self.op.remote_node_uuid)
      snode_group = self.cfg.GetNodeGroup(snode_info.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(self.cluster,
                                                              snode_group)
      CheckTargetNodeIPolicy(self, ipolicy, self.instance, snode_info, self.cfg,
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
      has_es = lambda n: IsExclusiveStorageEnabledNode(self.cfg, n)
      if compat.any(map(has_es, nodes)):
        errmsg = ("Cannot convert disk template from %s to %s when exclusive"
                  " storage is enabled" % (self.instance.disk_template,
                                           self.op.disk_template))
        raise errors.OpPrereqError(errmsg, errors.ECODE_STATE)

  def _PreCheckDisks(self, ispec):
    """CheckPrereq checks related to disk changes.

    @type ispec: dict
    @param ispec: instance specs to be updated with the new disks

    """
    self.diskparams = self.cfg.GetInstanceDiskParams(self.instance)

    excl_stor = compat.any(
      rpc.GetExclusiveStorageForNodes(self.cfg,
                                      self.instance.all_nodes).values()
      )

    # Check disk modifications. This is done here and not in CheckArguments
    # (as with NICs), because we need to know the instance's disk template
    ver_fn = lambda op, par: self._VerifyDiskModification(op, par, excl_stor)
    if self.instance.disk_template == constants.DT_EXT:
      self._CheckMods("disk", self.op.disks, {}, ver_fn)
    else:
      self._CheckMods("disk", self.op.disks, constants.IDISK_PARAMS_TYPES,
                      ver_fn)

    self.diskmod = _PrepareContainerMods(self.op.disks, None)

    # Check the validity of the `provider' parameter
    if self.instance.disk_template in constants.DT_EXT:
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

    if not self.op.wait_for_sync and self.instance.disks_active:
      for mod in self.diskmod:
        if mod[0] == constants.DDM_ADD:
          raise errors.OpPrereqError("Can't add a disk to an instance with"
                                     " activated disks and"
                                     " --no-wait-for-sync given.",
                                     errors.ECODE_INVAL)

    if self.op.disks and self.instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Disk operations not supported for"
                                 " diskless instances", errors.ECODE_INVAL)

    def _PrepareDiskMod(_, disk, params, __):
      disk.name = params.get(constants.IDISK_NAME, None)

    # Verify disk changes (operating on a copy)
    disks = copy.deepcopy(self.instance.disks)
    _ApplyContainerMods("disk", disks, None, self.diskmod, None,
                        _PrepareDiskMod, None)
    utils.ValidateDeviceNames("disk", disks)
    if len(disks) > constants.MAX_DISKS:
      raise errors.OpPrereqError("Instance has too many disks (%d), cannot add"
                                 " more" % constants.MAX_DISKS,
                                 errors.ECODE_STATE)
    disk_sizes = [disk.size for disk in self.instance.disks]
    disk_sizes.extend(params["size"] for (op, idx, params, private) in
                      self.diskmod if op == constants.DDM_ADD)
    ispec[constants.ISPEC_DISK_COUNT] = len(disk_sizes)
    ispec[constants.ISPEC_DISK_SIZE] = disk_sizes

    if self.op.offline is not None and self.op.offline:
      CheckInstanceState(self, self.instance, CAN_CHANGE_INSTANCE_OFFLINE,
                         msg="can't change to offline")

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    assert self.op.instance_name in self.owned_locks(locking.LEVEL_INSTANCE)
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    self.cluster = self.cfg.GetClusterInfo()
    cluster_hvparams = self.cluster.hvparams[self.instance.hypervisor]

    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    pnode_uuid = self.instance.primary_node

    self.warn = []

    if (self.op.pnode_uuid is not None and self.op.pnode_uuid != pnode_uuid and
        not self.op.force):
      # verify that the instance is not up
      instance_info = self.rpc.call_instance_info(
          pnode_uuid, self.instance.name, self.instance.hypervisor,
          cluster_hvparams)
      if instance_info.fail_msg:
        self.warn.append("Can't get instance runtime information: %s" %
                         instance_info.fail_msg)
      elif instance_info.payload:
        raise errors.OpPrereqError("Instance is still running on %s" %
                                   self.cfg.GetNodeName(pnode_uuid),
                                   errors.ECODE_STATE)

    assert pnode_uuid in self.owned_locks(locking.LEVEL_NODE)
    node_uuids = list(self.instance.all_nodes)
    pnode_info = self.cfg.GetNodeInfo(pnode_uuid)

    #_CheckInstanceNodeGroups(self.cfg, self.op.instance_name, owned_groups)
    assert pnode_info.group in self.owned_locks(locking.LEVEL_NODEGROUP)
    group_info = self.cfg.GetNodeGroup(pnode_info.group)

    # dictionary with instance information after the modification
    ispec = {}

    if self.op.hotplug:
      result = self.rpc.call_hotplug_supported(self.instance.primary_node,
                                               self.instance)
      result.Raise("Hotplug is not supported.")

    # Prepare NIC modifications
    self.nicmod = _PrepareContainerMods(self.op.nics, _InstNicModPrivate)

    # OS change
    if self.op.os_name and not self.op.force:
      CheckNodeHasOS(self, self.instance.primary_node, self.op.os_name,
                     self.op.force_variant)
      instance_os = self.op.os_name
    else:
      instance_os = self.instance.os

    assert not (self.op.disk_template and self.op.disks), \
      "Can't modify disk template and apply disk changes at the same time"

    if self.op.disk_template:
      self._PreCheckDiskTemplate(pnode_info)

    self._PreCheckDisks(ispec)

    # hvparams processing
    if self.op.hvparams:
      hv_type = self.instance.hypervisor
      i_hvdict = GetUpdatedParams(self.instance.hvparams, self.op.hvparams)
      utils.ForceDictType(i_hvdict, constants.HVS_PARAMETER_TYPES)
      hv_new = self.cluster.SimpleFillHV(hv_type, self.instance.os, i_hvdict)

      # local check
      hypervisor.GetHypervisorClass(hv_type).CheckParameterSyntax(hv_new)
      CheckHVParams(self, node_uuids, self.instance.hypervisor, hv_new)
      self.hv_proposed = self.hv_new = hv_new # the new actual values
      self.hv_inst = i_hvdict # the new dict (without defaults)
    else:
      self.hv_proposed = self.cluster.SimpleFillHV(self.instance.hypervisor,
                                                   self.instance.os,
                                                   self.instance.hvparams)
      self.hv_new = self.hv_inst = {}

    # beparams processing
    if self.op.beparams:
      i_bedict = GetUpdatedParams(self.instance.beparams, self.op.beparams,
                                  use_none=True)
      objects.UpgradeBeParams(i_bedict)
      utils.ForceDictType(i_bedict, constants.BES_PARAMETER_TYPES)
      be_new = self.cluster.SimpleFillBE(i_bedict)
      self.be_proposed = self.be_new = be_new # the new actual values
      self.be_inst = i_bedict # the new dict (without defaults)
    else:
      self.be_new = self.be_inst = {}
      self.be_proposed = self.cluster.SimpleFillBE(self.instance.beparams)
    be_old = self.cluster.FillBE(self.instance)

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
        hvspecs = [(self.instance.hypervisor,
                    self.cfg.GetClusterInfo()
                      .hvparams[self.instance.hypervisor])]
        _CheckNodesPhysicalCPUs(self, self.instance.all_nodes,
                                max_requested_cpu + 1,
                                hvspecs)

    # osparams processing
    if self.op.osparams:
      i_osdict = GetUpdatedParams(self.instance.osparams, self.op.osparams)
      CheckOSParams(self, True, node_uuids, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = {}

    #TODO(dynmem): do the appropriate check involving MINMEM
    if (constants.BE_MAXMEM in self.op.beparams and not self.op.force and
        be_new[constants.BE_MAXMEM] > be_old[constants.BE_MAXMEM]):
      mem_check_list = [pnode_uuid]
      if be_new[constants.BE_AUTO_BALANCE]:
        # either we changed auto_balance to yes or it was from before
        mem_check_list.extend(self.instance.secondary_nodes)
      instance_info = self.rpc.call_instance_info(
          pnode_uuid, self.instance.name, self.instance.hypervisor,
          cluster_hvparams)
      hvspecs = [(self.instance.hypervisor,
                  cluster_hvparams)]
      nodeinfo = self.rpc.call_node_info(mem_check_list, None,
                                         hvspecs)
      pninfo = nodeinfo[pnode_uuid]
      msg = pninfo.fail_msg
      if msg:
        # Assume the primary node is unreachable and go ahead
        self.warn.append("Can't get info from primary node %s: %s" %
                         (self.cfg.GetNodeName(pnode_uuid), msg))
      else:
        (_, _, (pnhvinfo, )) = pninfo.payload
        if not isinstance(pnhvinfo.get("memory_free", None), int):
          self.warn.append("Node data from primary node %s doesn't contain"
                           " free memory information" %
                           self.cfg.GetNodeName(pnode_uuid))
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
        for node_uuid, nres in nodeinfo.items():
          if node_uuid not in self.instance.secondary_nodes:
            continue
          nres.Raise("Can't get info from secondary node %s" %
                     self.cfg.GetNodeName(node_uuid), prereq=True,
                     ecode=errors.ECODE_STATE)
          (_, _, (nhvinfo, )) = nres.payload
          if not isinstance(nhvinfo.get("memory_free", None), int):
            raise errors.OpPrereqError("Secondary node %s didn't return free"
                                       " memory information" %
                                       self.cfg.GetNodeName(node_uuid),
                                       errors.ECODE_STATE)
          #TODO(dynmem): do the appropriate check involving MINMEM
          elif be_new[constants.BE_MAXMEM] > nhvinfo["memory_free"]:
            raise errors.OpPrereqError("This change will prevent the instance"
                                       " from failover to its secondary node"
                                       " %s, due to not enough memory" %
                                       self.cfg.GetNodeName(node_uuid),
                                       errors.ECODE_STATE)

    if self.op.runtime_mem:
      remote_info = self.rpc.call_instance_info(
         self.instance.primary_node, self.instance.name,
         self.instance.hypervisor,
         cluster_hvparams)
      remote_info.Raise("Error checking node %s" %
                        self.cfg.GetNodeName(self.instance.primary_node))
      if not remote_info.payload: # not running already
        raise errors.OpPrereqError("Instance %s is not running" %
                                   self.instance.name, errors.ECODE_STATE)

      current_memory = remote_info.payload["memory"]
      if (not self.op.force and
           (self.op.runtime_mem > self.be_proposed[constants.BE_MAXMEM] or
            self.op.runtime_mem < self.be_proposed[constants.BE_MINMEM])):
        raise errors.OpPrereqError("Instance %s must have memory between %d"
                                   " and %d MB of memory unless --force is"
                                   " given" %
                                   (self.instance.name,
                                    self.be_proposed[constants.BE_MINMEM],
                                    self.be_proposed[constants.BE_MAXMEM]),
                                   errors.ECODE_INVAL)

      delta = self.op.runtime_mem - current_memory
      if delta > 0:
        CheckNodeFreeMemory(
            self, self.instance.primary_node,
            "ballooning memory for instance %s" % self.instance.name, delta,
            self.instance.hypervisor,
            self.cfg.GetClusterInfo().hvparams[self.instance.hypervisor])

    # make self.cluster visible in the functions below
    cluster = self.cluster

    def _PrepareNicCreate(_, params, private):
      self._PrepareNicModification(params, private, None, None,
                                   {}, cluster, pnode_uuid)
      return (None, None)

    def _PrepareNicMod(_, nic, params, private):
      self._PrepareNicModification(params, private, nic.ip, nic.network,
                                   nic.nicparams, cluster, pnode_uuid)
      return None

    def _PrepareNicRemove(_, params, __):
      ip = params.ip
      net = params.network
      if net is not None and ip is not None:
        self.cfg.ReleaseIp(net, ip, self.proc.GetECId())

    # Verify NIC changes (operating on copy)
    nics = self.instance.nics[:]
    _ApplyContainerMods("NIC", nics, None, self.nicmod,
                        _PrepareNicCreate, _PrepareNicMod, _PrepareNicRemove)
    if len(nics) > constants.MAX_NICS:
      raise errors.OpPrereqError("Instance has too many network interfaces"
                                 " (%d), cannot add more" % constants.MAX_NICS,
                                 errors.ECODE_STATE)

    # Pre-compute NIC changes (necessary to use result in hooks)
    self._nic_chgdesc = []
    if self.nicmod:
      # Operate on copies as this is still in prereq
      nics = [nic.Copy() for nic in self.instance.nics]
      _ApplyContainerMods("NIC", nics, self._nic_chgdesc, self.nicmod,
                          self._CreateNewNic, self._ApplyNicMods,
                          self._RemoveNic)
      # Verify that NIC names are unique and valid
      utils.ValidateDeviceNames("NIC", nics)
      self._new_nics = nics
      ispec[constants.ISPEC_NIC_COUNT] = len(self._new_nics)
    else:
      self._new_nics = None
      ispec[constants.ISPEC_NIC_COUNT] = len(self.instance.nics)

    if not self.op.ignore_ipolicy:
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(self.cluster,
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
        new_disk_template = self.instance.disk_template
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
    pnode_uuid = self.instance.primary_node
    snode_uuid = self.op.remote_node_uuid

    assert self.instance.disk_template == constants.DT_PLAIN

    # create a fake disk info for _GenerateDiskTemplate
    disk_info = [{constants.IDISK_SIZE: d.size, constants.IDISK_MODE: d.mode,
                  constants.IDISK_VG: d.logical_id[0],
                  constants.IDISK_NAME: d.name}
                 for d in self.instance.disks]
    new_disks = GenerateDiskTemplate(self, self.op.disk_template,
                                     self.instance.uuid, pnode_uuid,
                                     [snode_uuid], disk_info, None, None, 0,
                                     feedback_fn, self.diskparams)
    anno_disks = rpc.AnnotateDiskParams(new_disks, self.diskparams)
    p_excl_stor = IsExclusiveStorageEnabledNodeUuid(self.cfg, pnode_uuid)
    s_excl_stor = IsExclusiveStorageEnabledNodeUuid(self.cfg, snode_uuid)
    info = GetInstanceInfoText(self.instance)
    feedback_fn("Creating additional volumes...")
    # first, create the missing data and meta devices
    for disk in anno_disks:
      # unfortunately this is... not too nice
      CreateSingleBlockDev(self, pnode_uuid, self.instance, disk.children[1],
                           info, True, p_excl_stor)
      for child in disk.children:
        CreateSingleBlockDev(self, snode_uuid, self.instance, child, info, True,
                             s_excl_stor)
    # at this stage, all new LVs have been created, we can rename the
    # old ones
    feedback_fn("Renaming original volumes...")
    rename_list = [(o, n.children[0].logical_id)
                   for (o, n) in zip(self.instance.disks, new_disks)]
    result = self.rpc.call_blockdev_rename(pnode_uuid, rename_list)
    result.Raise("Failed to rename original LVs")

    feedback_fn("Initializing DRBD devices...")
    # all child devices are in place, we can now create the DRBD devices
    try:
      for disk in anno_disks:
        for (node_uuid, excl_stor) in [(pnode_uuid, p_excl_stor),
                                       (snode_uuid, s_excl_stor)]:
          f_create = node_uuid == pnode_uuid
          CreateSingleBlockDev(self, node_uuid, self.instance, disk, info,
                               f_create, excl_stor)
    except errors.GenericError, e:
      feedback_fn("Initializing of DRBD devices failed;"
                  " renaming back original volumes...")
      rename_back_list = [(n.children[0], o.logical_id)
                          for (n, o) in zip(new_disks, self.instance.disks)]
      result = self.rpc.call_blockdev_rename(pnode_uuid, rename_back_list)
      result.Raise("Failed to rename LVs back after error %s" % str(e))
      raise

    # at this point, the instance has been modified
    self.instance.disk_template = constants.DT_DRBD8
    self.instance.disks = new_disks
    self.cfg.Update(self.instance, feedback_fn)

    # Release node locks while waiting for sync
    ReleaseLocks(self, locking.LEVEL_NODE)

    # disks are created, waiting for sync
    disk_abort = not WaitForSync(self, self.instance,
                                 oneshot=not self.op.wait_for_sync)
    if disk_abort:
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance, please cleanup manually")

    # Node resource locks will be released by caller

  def _ConvertDrbdToPlain(self, feedback_fn):
    """Converts an instance from drbd to plain.

    """
    assert len(self.instance.secondary_nodes) == 1
    assert self.instance.disk_template == constants.DT_DRBD8

    pnode_uuid = self.instance.primary_node
    snode_uuid = self.instance.secondary_nodes[0]
    feedback_fn("Converting template to plain")

    old_disks = AnnotateDiskParams(self.instance, self.instance.disks, self.cfg)
    new_disks = [d.children[0] for d in self.instance.disks]

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
    self.instance.disks = new_disks
    self.instance.disk_template = constants.DT_PLAIN
    _UpdateIvNames(0, self.instance.disks)
    self.cfg.Update(self.instance, feedback_fn)

    # Release locks in case removing disks takes a while
    ReleaseLocks(self, locking.LEVEL_NODE)

    feedback_fn("Removing volumes on the secondary node...")
    for disk in old_disks:
      result = self.rpc.call_blockdev_remove(snode_uuid, (disk, self.instance))
      result.Warn("Could not remove block device %s on node %s,"
                  " continuing anyway" %
                  (disk.iv_name, self.cfg.GetNodeName(snode_uuid)),
                  self.LogWarning)

    feedback_fn("Removing unneeded volumes on the primary node...")
    for idx, disk in enumerate(old_disks):
      meta = disk.children[1]
      result = self.rpc.call_blockdev_remove(pnode_uuid, (meta, self.instance))
      result.Warn("Could not remove metadata for disk %d on node %s,"
                  " continuing anyway" %
                  (idx, self.cfg.GetNodeName(pnode_uuid)),
                  self.LogWarning)

  def _HotplugDevice(self, action, dev_type, device, extra, seq):
    self.LogInfo("Trying to hotplug device...")
    msg = "hotplug:"
    result = self.rpc.call_hotplug_device(self.instance.primary_node,
                                          self.instance, action, dev_type,
                                          (device, self.instance),
                                          extra, seq)
    if result.fail_msg:
      self.LogWarning("Could not hotplug device: %s" % result.fail_msg)
      self.LogInfo("Continuing execution..")
      msg += "failed"
    else:
      self.LogInfo("Hotplug done.")
      msg += "done"
    return msg

  def _CreateNewDisk(self, idx, params, _):
    """Creates a new disk.

    """
    # add a new disk
    if self.instance.disk_template in constants.DTS_FILEBASED:
      (file_driver, file_path) = self.instance.disks[0].logical_id
      file_path = os.path.dirname(file_path)
    else:
      file_driver = file_path = None

    disk = \
      GenerateDiskTemplate(self, self.instance.disk_template,
                           self.instance.uuid, self.instance.primary_node,
                           self.instance.secondary_nodes, [params], file_path,
                           file_driver, idx, self.Log, self.diskparams)[0]

    new_disks = CreateDisks(self, self.instance, disks=[disk])

    if self.cluster.prealloc_wipe_disks:
      # Wipe new disk
      WipeOrCleanupDisks(self, self.instance,
                         disks=[(idx, disk, 0)],
                         cleanup=new_disks)

    changes = [
      ("disk/%d" % idx,
       "add:size=%s,mode=%s" % (disk.size, disk.mode)),
      ]
    if self.op.hotplug:
      result = self.rpc.call_blockdev_assemble(self.instance.primary_node,
                                               (disk, self.instance),
                                               self.instance.name, True, idx)
      if result.fail_msg:
        changes.append(("disk/%d" % idx, "assemble:failed"))
        self.LogWarning("Can't assemble newly created disk %d: %s",
                        idx, result.fail_msg)
      else:
        _, link_name = result.payload
        msg = self._HotplugDevice(constants.HOTPLUG_ACTION_ADD,
                                  constants.HOTPLUG_TARGET_DISK,
                                  disk, link_name, idx)
        changes.append(("disk/%d" % idx, msg))

    return (disk, changes)

  def _PostAddDisk(self, _, disk):
    if not WaitForSync(self, self.instance, disks=[disk],
                       oneshot=not self.op.wait_for_sync):
      raise errors.OpExecError("Failed to sync disks of %s" %
                               self.instance.name)

    # the disk is active at this point, so deactivate it if the instance disks
    # are supposed to be inactive
    if not self.instance.disks_active:
      ShutdownInstanceDisks(self, self.instance, disks=[disk])

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
    hotmsg = ""
    if self.op.hotplug:
      hotmsg = self._HotplugDevice(constants.HOTPLUG_ACTION_REMOVE,
                                   constants.HOTPLUG_TARGET_DISK,
                                   root, None, idx)
      ShutdownInstanceDisks(self, self.instance, [root])

    (anno_disk,) = AnnotateDiskParams(self.instance, [root], self.cfg)
    for node_uuid, disk in anno_disk.ComputeNodeTree(
                             self.instance.primary_node):
      msg = self.rpc.call_blockdev_remove(node_uuid, (disk, self.instance)) \
              .fail_msg
      if msg:
        self.LogWarning("Could not remove disk/%d on node '%s': %s,"
                        " continuing anyway", idx,
                        self.cfg.GetNodeName(node_uuid), msg)

    # if this is a DRBD disk, return its port to the pool
    if root.dev_type in constants.DTS_DRBD:
      self.cfg.AddTcpUdpPort(root.logical_id[2])

    return hotmsg

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

    changes = [
      ("nic.%d" % idx,
       "add:mac=%s,ip=%s,mode=%s,link=%s,network=%s" %
       (mac, ip, private.filled[constants.NIC_MODE],
       private.filled[constants.NIC_LINK], net)),
      ]

    if self.op.hotplug:
      msg = self._HotplugDevice(constants.HOTPLUG_ACTION_ADD,
                                constants.HOTPLUG_TARGET_NIC,
                                nobj, None, idx)
      changes.append(("nic.%d" % idx, msg))

    return (nobj, changes)

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

    if self.op.hotplug:
      msg = self._HotplugDevice(constants.HOTPLUG_ACTION_MODIFY,
                                constants.HOTPLUG_TARGET_NIC,
                                nic, None, idx)
      changes.append(("nic/%d" % idx, msg))

    return changes

  def _RemoveNic(self, idx, nic, _):
    if self.op.hotplug:
      return self._HotplugDevice(constants.HOTPLUG_ACTION_REMOVE,
                                 constants.HOTPLUG_TARGET_NIC,
                                 nic, None, idx)

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

    # New primary node
    if self.op.pnode_uuid:
      self.instance.primary_node = self.op.pnode_uuid

    # runtime memory
    if self.op.runtime_mem:
      rpcres = self.rpc.call_instance_balloon_memory(self.instance.primary_node,
                                                     self.instance,
                                                     self.op.runtime_mem)
      rpcres.Raise("Cannot modify instance runtime memory")
      result.append(("runtime_memory", self.op.runtime_mem))

    # Apply disk changes
    _ApplyContainerMods("disk", self.instance.disks, result, self.diskmod,
                        self._CreateNewDisk, self._ModifyDisk,
                        self._RemoveDisk, post_add_fn=self._PostAddDisk)
    _UpdateIvNames(0, self.instance.disks)

    if self.op.disk_template:
      if __debug__:
        check_nodes = set(self.instance.all_nodes)
        if self.op.remote_node_uuid:
          check_nodes.add(self.op.remote_node_uuid)
        for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
          owned = self.owned_locks(level)
          assert not (check_nodes - owned), \
            ("Not owning the correct locks, owning %r, expected at least %r" %
             (owned, check_nodes))

      r_shut = ShutdownInstanceDisks(self, self.instance)
      if not r_shut:
        raise errors.OpExecError("Cannot shutdown instance disks, unable to"
                                 " proceed with disk template conversion")
      mode = (self.instance.disk_template, self.op.disk_template)
      try:
        self._DISK_CONVERSIONS[mode](self, feedback_fn)
      except:
        self.cfg.ReleaseDRBDMinors(self.instance.uuid)
        raise
      result.append(("disk_template", self.op.disk_template))

      assert self.instance.disk_template == self.op.disk_template, \
        ("Expected disk template '%s', found '%s'" %
         (self.op.disk_template, self.instance.disk_template))

    # Release node and resource locks if there are any (they might already have
    # been released during disk conversion)
    ReleaseLocks(self, locking.LEVEL_NODE)
    ReleaseLocks(self, locking.LEVEL_NODE_RES)

    # Apply NIC changes
    if self._new_nics is not None:
      self.instance.nics = self._new_nics
      result.extend(self._nic_chgdesc)

    # hvparams changes
    if self.op.hvparams:
      self.instance.hvparams = self.hv_inst
      for key, val in self.op.hvparams.iteritems():
        result.append(("hv/%s" % key, val))

    # beparams changes
    if self.op.beparams:
      self.instance.beparams = self.be_inst
      for key, val in self.op.beparams.iteritems():
        result.append(("be/%s" % key, val))

    # OS change
    if self.op.os_name:
      self.instance.os = self.op.os_name

    # osparams changes
    if self.op.osparams:
      self.instance.osparams = self.os_inst
      for key, val in self.op.osparams.iteritems():
        result.append(("os/%s" % key, val))

    if self.op.offline is None:
      # Ignore
      pass
    elif self.op.offline:
      # Mark instance as offline
      self.cfg.MarkInstanceOffline(self.instance.uuid)
      result.append(("admin_state", constants.ADMINST_OFFLINE))
    else:
      # Mark instance as online, but stopped
      self.cfg.MarkInstanceDown(self.instance.uuid)
      result.append(("admin_state", constants.ADMINST_DOWN))

    self.cfg.Update(self.instance, feedback_fn, self.proc.GetECId())

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
    self.share_locks = ShareAll()

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

    self.op.iallocator = GetDefaultIAllocator(self.cfg, self.op.iallocator)

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      if self.req_target_uuids:
        lock_groups = set(self.req_target_uuids)

        # Lock all groups used by instance optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        instance_groups = self.cfg.GetInstanceNodeGroups(self.op.instance_uuid)
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
                       self.cfg.GetInstanceNodeGroups(self.op.instance_uuid))
        member_nodes = [node_uuid
                        for group in lock_groups
                        for node_uuid in self.cfg.GetNodeGroup(group).members]
        self.needed_locks[locking.LEVEL_NODE].extend(member_nodes)
      else:
        # Lock all nodes as all groups are potential targets
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def CheckPrereq(self):
    owned_instance_names = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert (self.req_target_uuids is None or
            owned_groups.issuperset(self.req_target_uuids))
    assert owned_instance_names == set([self.op.instance_name])

    # Get instance information
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)

    # Check if node groups for locked instance are still correct
    assert owned_nodes.issuperset(self.instance.all_nodes), \
      ("Instance %s's nodes changed while we kept the lock" %
       self.op.instance_name)

    inst_groups = CheckInstanceNodeGroups(self.cfg, self.op.instance_uuid,
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

    env.update(BuildInstanceHookEnvByObject(self, self.instance))

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

    jobs = LoadNodeEvacResult(self, ial.result, self.op.early_release, False)

    self.LogInfo("Iallocator returned %s job(s) for changing group of"
                 " instance '%s'", len(jobs), self.op.instance_name)

    return ResultWithJobs(jobs)
