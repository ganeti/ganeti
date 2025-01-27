#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Logical unit setting parameters of a single instance."""

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
from ganeti import netutils
from ganeti import objects
from ganeti import utils
import ganeti.rpc.node as rpc

from ganeti.cmdlib.base import LogicalUnit

from ganeti.cmdlib.common import INSTANCE_DOWN, \
  INSTANCE_NOT_RUNNING, CheckNodeOnline, \
  CheckParamsNotGlobal, \
  IsExclusiveStorageEnabledNode, CheckHVParams, CheckOSParams, \
  GetUpdatedParams, CheckInstanceState, ExpandNodeUuidAndName, \
  IsValidDiskAccessModeCombination, AnnotateDiskParams, \
  CheckIAllocatorOrNode
from ganeti.cmdlib.instance_storage import CalculateFileStorageDir, \
  CheckDiskExtProvider, CheckNodesFreeDiskPerVG, CheckRADOSFreeSpace, \
  CheckSpindlesExclusiveStorage, ComputeDiskSizePerVG, ComputeDisksInfo, \
  CreateDisks, CreateSingleBlockDev, GenerateDiskTemplate, \
  IsExclusiveStorageEnabledNodeUuid, ShutdownInstanceDisks, \
  WaitForSync, WipeOrCleanupDisks, AssembleInstanceDisks
from ganeti.cmdlib.instance_utils import BuildInstanceHookEnvByObject, \
  NICToTuple, CheckNodeNotDrained, CopyLockList, \
  ReleaseLocks, CheckNodeVmCapable, CheckTargetNodeIPolicy, \
  GetInstanceInfoText, RemoveDisks, CheckNodeFreeMemory, \
  UpdateMetadata, CheckForConflictingIp, \
  PrepareContainerMods, ComputeInstanceCommunicationNIC, \
  ApplyContainerMods, ComputeIPolicyInstanceSpecViolation, \
  CheckNodesPhysicalCPUs
import ganeti.masterd.instance


class InstNicModPrivate(object):
  """Data structure for network interface modifications.

  Used by L{LUInstanceSetParams}.

  """
  def __init__(self):
    self.params = None
    self.filled = None


class LUInstanceSetParams(LogicalUnit):
  """Modifies an instances's parameters.

  """
  HPATH = "instance-modify"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def GenericGetDiskInfo(self, uuid=None, name=None):
    """Find a disk object using the provided params.

    Accept arguments as keywords and use the GetDiskInfo/GetDiskInfoByName
    config functions to retrieve the disk info based on these arguments.

    In case of an error, raise the appropriate exceptions.
    """
    if uuid:
      disk = self.cfg.GetDiskInfo(uuid)
      if disk is None:
        raise errors.OpPrereqError("No disk was found with this UUID: %s" %
                                   uuid, errors.ECODE_INVAL)
    elif name:
      disk = self.cfg.GetDiskInfoByName(name)
      if disk is None:
        raise errors.OpPrereqError("No disk was found with this name: %s" %
                                   name, errors.ECODE_INVAL)
    else:
      raise errors.ProgrammerError("No disk UUID or name was given")

    return disk

  @staticmethod
  def _UpgradeDiskNicMods(kind, mods, verify_fn):
    assert ht.TList(mods)
    assert not mods or len(mods[0]) in (2, 3)

    if mods and len(mods[0]) == 2:
      result = []

      addremove = 0
      for op, params in mods:
        if op in (constants.DDM_ADD, constants.DDM_ATTACH,
                  constants.DDM_REMOVE, constants.DDM_DETACH):
          result.append((op, -1, params))
          addremove += 1

          if addremove > 1:
            raise errors.OpPrereqError("Only one %s add/attach/remove/detach "
                                       "operation is supported at a time" %
                                       kind, errors.ECODE_INVAL)
        else:
          result.append((constants.DDM_MODIFY, op, params))

      assert verify_fn(result)
    else:
      result = mods
    return result

  @staticmethod
  def _CheckMods(kind, mods, key_types, item_fn):
    """Ensures requested disk/NIC modifications are valid.

    Note that the 'attach' action needs a way to refer to the UUID of the disk,
    since the disk name is not unique cluster-wide. However, the UUID of the
    disk is not settable but rather generated by Ganeti automatically,
    therefore it cannot be passed as an IDISK parameter. For this reason, this
    function will override the checks to accept uuid parameters solely for the
    attach action.
    """
    # Create a key_types copy with the 'uuid' as a valid key type.
    key_types_attach = key_types.copy()
    key_types_attach['uuid'] = 'string'

    for (op, _, params) in mods:
      assert ht.TDict(params)

      # If 'key_types' is an empty dict, we assume we have an
      # 'ext' template and thus do not ForceDictType
      if key_types:
        utils.ForceDictType(params, (key_types if op != constants.DDM_ATTACH
                                     else key_types_attach))

      if op not in (constants.DDM_ADD, constants.DDM_ATTACH,
                    constants.DDM_MODIFY, constants.DDM_REMOVE,
                    constants.DDM_DETACH):
        raise errors.ProgrammerError("Unhandled operation '%s'" % op)

      if op in (constants.DDM_REMOVE, constants.DDM_DETACH):
        if params:
          raise errors.OpPrereqError("No settings should be passed when"
                                     " removing or detaching a %s" % kind,
                                     errors.ECODE_INVAL)

      item_fn(op, params)

  def _VerifyDiskModification(self, op, params, excl_stor, group_access_types):
    """Verifies a disk modification.

    """
    disk_type = params.get(
        constants.IDISK_TYPE,
        self.cfg.GetInstanceDiskTemplate(self.instance.uuid))

    if op == constants.DDM_ADD:
      params[constants.IDISK_TYPE] = disk_type

      if disk_type == constants.DT_DISKLESS:
        raise errors.OpPrereqError(
            "Must specify disk type on diskless instance", errors.ECODE_INVAL)

      if disk_type != constants.DT_EXT:
        utils.ForceDictType(params, constants.IDISK_PARAMS_TYPES)

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

    # These checks are necessary when adding and attaching disks
    if op in (constants.DDM_ADD, constants.DDM_ATTACH):
      CheckSpindlesExclusiveStorage(params, excl_stor, True)
      # If the disk is added we need to check for ext provider
      if op == constants.DDM_ADD:
        CheckDiskExtProvider(params, disk_type)

      # Make sure we do not add syncing disks to instances with inactive disks
      if not self.op.wait_for_sync and not self.instance.disks_active:
        raise errors.OpPrereqError("Can't %s a disk to an instance with"
                                   " deactivated disks and --no-wait-for-sync"
                                   " given" % op, errors.ECODE_INVAL)

      # Check disk access param (only for specific disks)
      if disk_type in constants.DTS_HAVE_ACCESS:
        access_type = params.get(constants.IDISK_ACCESS,
                                 group_access_types[disk_type])
        if not IsValidDiskAccessModeCombination(self.instance.hypervisor,
                                                disk_type, access_type):
          raise errors.OpPrereqError("Selected hypervisor (%s) cannot be"
                                     " used with %s disk access param" %
                                     (self.instance.hypervisor, access_type),
                                      errors.ECODE_STATE)

    if op == constants.DDM_ATTACH:
      if len(params) != 1 or ('uuid' not in params and
                              constants.IDISK_NAME not in params):
        raise errors.OpPrereqError("Only one argument is permitted in %s op,"
                                   " either %s or uuid" % (constants.DDM_ATTACH,
                                                           constants.IDISK_NAME,
                                                           ),
                                   errors.ECODE_INVAL)
      self._CheckAttachDisk(params)

    elif op == constants.DDM_MODIFY:
      if constants.IDISK_SIZE in params:
        raise errors.OpPrereqError("Disk size change not possible, use"
                                   " grow-disk", errors.ECODE_INVAL)

      disk_info = self.cfg.GetInstanceDisks(self.instance.uuid)

      # Disk modification supports changing only the disk name and mode.
      # Changing arbitrary parameters is allowed only for ext disk template",
      if not utils.AllDiskOfType(disk_info, [constants.DT_EXT]):
        utils.ForceDictType(params, constants.MODIFIABLE_IDISK_PARAMS_TYPES)
      else:
        # We have to check that the 'access' and 'disk_provider' parameters
        # cannot be modified
        for param in [constants.IDISK_ACCESS, constants.IDISK_PROVIDER]:
          if param in params:
            raise errors.OpPrereqError("Disk '%s' parameter change is"
                                       " not possible" % param,
                                       errors.ECODE_INVAL)

      name = params.get(constants.IDISK_NAME, None)
      if name is not None and name.lower() == constants.VALUE_NONE:
        params[constants.IDISK_NAME] = None

    if op == constants.DDM_REMOVE and not self.op.hotplug:
      CheckInstanceState(self, self.instance, INSTANCE_NOT_RUNNING,
                         msg="can't remove volume from a running instance"
                             " without using hotplug")

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

  def _LookupDiskIndex(self, idx):
    """Looks up uuid or name of disk if necessary."""
    try:
      return int(idx)
    except ValueError:
      pass
    for i, d in enumerate(self.cfg.GetInstanceDisks(self.instance.uuid)):
      if d.name == idx or d.uuid == idx:
        return i
    raise errors.OpPrereqError("Lookup of disk %r failed" % idx)

  def _LookupDiskMods(self):
    """Looks up uuid or name of disk if necessary."""
    return [(op, self._LookupDiskIndex(idx), params)
            for op, idx, params in self.op.disks]

  def CheckArguments(self):
    if not (self.op.nics or self.op.disks or self.op.disk_template or
            self.op.hvparams or self.op.beparams or self.op.os_name or
            self.op.osparams or self.op.offline is not None or
            self.op.runtime_mem or self.op.pnode or self.op.osparams_private or
            self.op.instance_communication is not None):
      raise errors.OpPrereqError("No changes submitted", errors.ECODE_INVAL)

    if self.op.hvparams:
      CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS,
                           "hypervisor", "instance", "cluster")

    self.op.disks = self._UpgradeDiskNicMods(
      "disk", self.op.disks,
      ht.TSetParamsMods(ht.TIDiskParams))
    self.op.nics = self._UpgradeDiskNicMods(
      "NIC", self.op.nics, ht.TSetParamsMods(ht.TINicParams))

    # Check disk template modifications
    if self.op.disk_template:
      if self.op.disks:
        raise errors.OpPrereqError("Disk template conversion and other disk"
                                   " changes not supported at the same time",
                                   errors.ECODE_INVAL)

      # mirrored template node checks
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        CheckIAllocatorOrNode(self, "iallocator", "remote_node")
      elif self.op.remote_node:
        self.LogWarning("Changing the disk template to a non-mirrored one,"
                        " the secondary node will be ignored")
        # the secondary node must be cleared in order to be ignored, otherwise
        # the operation will fail, in the GenerateDiskTemplate method
        self.op.remote_node = None

      # file-based template checks
      if self.op.disk_template in constants.DTS_FILEBASED:
        self._FillFileDriver()

    # Check NIC modifications
    self._CheckMods("NIC", self.op.nics, constants.INIC_PARAMS_TYPES,
                    self._VerifyNicModification)

    if self.op.pnode:
      (self.op.pnode_uuid, self.op.pnode) = \
        ExpandNodeUuidAndName(self.cfg, self.op.pnode_uuid, self.op.pnode)

  def _CheckAttachDisk(self, params):
    """Check if disk can be attached to an instance.

    Check if the disk and instance have the same template. Also, check if the
    disk nodes are visible from the instance.
    """
    uuid = params.get("uuid", None)
    name = params.get(constants.IDISK_NAME, None)

    disk = self.GenericGetDiskInfo(uuid, name)
    instance_template = self.cfg.GetInstanceDiskTemplate(self.instance.uuid)
    if (disk.dev_type != instance_template and
        instance_template != constants.DT_DISKLESS):
      raise errors.OpPrereqError("Instance has '%s' template while disk has"
                                 " '%s' template" %
                                 (instance_template, disk.dev_type),
                                 errors.ECODE_INVAL)

    instance_nodes = self.cfg.GetInstanceNodes(self.instance.uuid)
    # Make sure we do not attach disks to instances on wrong nodes. If the
    # instance is diskless, that instance is associated only to the primary
    # node, whereas the disk can be associated to two nodes in the case of DRBD,
    # hence, we have a subset check here.
    if disk.nodes and not set(instance_nodes).issubset(set(disk.nodes)):
      raise errors.OpPrereqError("Disk nodes are %s while the instance's nodes"
                                 " are %s" %
                                 (disk.nodes, instance_nodes),
                                 errors.ECODE_INVAL)
    # Make sure a DRBD disk has the same primary node as the instance where it
    # will be attached to.
    disk_primary = disk.GetPrimaryNode(self.instance.primary_node)
    if self.instance.primary_node != disk_primary:
      raise errors.OpExecError("The disks' primary node is %s whereas the "
                               "instance's primary node is %s."
                               % (disk_primary, self.instance.primary_node))

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
    self.dont_collate_locks[locking.LEVEL_NODEGROUP] = True
    self.dont_collate_locks[locking.LEVEL_NODE] = True
    self.dont_collate_locks[locking.LEVEL_NODE_RES] = True

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
      elif self.op.disk_template in constants.DTS_INT_MIRROR:
        # If we have to find the secondary node for a conversion to DRBD,
        # close node locks to the whole node group.
        self.needed_locks[locking.LEVEL_NODE] = \
          list(self.cfg.GetNodeGroupMembersByNodes(
            self.needed_locks[locking.LEVEL_NODE]))
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
    nl = [self.cfg.GetMasterNode()] + \
        list(self.cfg.GetInstanceNodes(self.instance.uuid))
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
      if ip is None and not new_net_uuid:
        raise errors.OpPrereqError("Cannot set the NIC IP address to None"
                                   " on a routed NIC if not attached to a"
                                   " network", errors.ECODE_INVAL)

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
            self.cfg.ReserveIp(new_net_uuid, new_ip, self.proc.GetECId(),
                               check=self.op.conflicts_check)
            self.LogInfo("Reserving IP %s in network %s",
                         new_ip, new_net_obj.name)
          except errors.ReservationError:
            raise errors.OpPrereqError("IP %s not available in network %s" %
                                       (new_ip, new_net_obj.name),
                                       errors.ECODE_NOTUNIQUE)
        # new network is None so check if new IP is a conflicting IP
        elif self.op.conflicts_check:
          CheckForConflictingIp(self, new_ip, pnode_uuid)

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

    # TODO make sure heterogeneous disk types can be converted.
    disk_template = self.cfg.GetInstanceDiskTemplate(self.instance.uuid)
    if disk_template == constants.DT_MIXED:
      raise errors.OpPrereqError(
          "Conversion from mixed is not yet supported.")

    inst_disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    if utils.AnyDiskOfType(inst_disks, constants.DTS_NOT_CONVERTIBLE_FROM):
      raise errors.OpPrereqError(
          "Conversion from the '%s' disk template is not supported"
          % self.cfg.GetInstanceDiskTemplate(self.instance.uuid),
          errors.ECODE_INVAL)

    elif self.op.disk_template in constants.DTS_NOT_CONVERTIBLE_TO:
      raise errors.OpPrereqError("Conversion to the '%s' disk template is"
                                 " not supported" % self.op.disk_template,
                                 errors.ECODE_INVAL)

    if (self.op.disk_template != constants.DT_EXT and
        utils.AllDiskOfType(inst_disks, [self.op.disk_template])):
      raise errors.OpPrereqError("Instance already has disk template %s" %
                                 self.op.disk_template, errors.ECODE_INVAL)

    if not self.cluster.IsDiskTemplateEnabled(self.op.disk_template):
      enabled_dts = utils.CommaJoin(self.cluster.enabled_disk_templates)
      raise errors.OpPrereqError("Disk template '%s' is not enabled for this"
                                 " cluster (enabled templates: %s)" %
                                 (self.op.disk_template, enabled_dts),
                                  errors.ECODE_STATE)

    default_vg = self.cfg.GetVGName()
    if (not default_vg and
        self.op.disk_template not in constants.DTS_NOT_LVM):
      raise errors.OpPrereqError("Disk template conversions to lvm-based"
                                 " instances are not supported by the cluster",
                                 errors.ECODE_STATE)

    CheckInstanceState(self, self.instance, INSTANCE_DOWN,
                       msg="cannot change disk template")

    # compute new disks' information
    self.disks_info = ComputeDisksInfo(inst_disks, self.op.disk_template,
                                       default_vg, self.op.ext_params)

    # mirror node verification
    if self.op.disk_template in constants.DTS_INT_MIRROR \
        and self.op.remote_node_uuid:
      if self.op.remote_node_uuid == pnode_uuid:
        raise errors.OpPrereqError("Given new secondary node %s is the same"
                                   " as the primary node of the instance" %
                                   self.op.remote_node, errors.ECODE_STATE)
      CheckNodeOnline(self, self.op.remote_node_uuid)
      CheckNodeNotDrained(self, self.op.remote_node_uuid)
      CheckNodeVmCapable(self, self.op.remote_node_uuid)

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

    # check that the template is in the primary node group's allowed templates
    pnode_group = self.cfg.GetNodeGroup(pnode_info.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(self.cluster,
                                                            pnode_group)
    allowed_dts = ipolicy[constants.IPOLICY_DTS]
    if self.op.disk_template not in allowed_dts:
      raise errors.OpPrereqError("Disk template '%s' in not allowed (allowed"
                                 " templates: %s)" % (self.op.disk_template,
                                 utils.CommaJoin(allowed_dts)),
                                 errors.ECODE_STATE)

    if not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      # Make sure none of the nodes require exclusive storage
      nodes = [pnode_info]
      if self.op.disk_template in constants.DTS_INT_MIRROR \
          and self.op.remote_node_uuid:
        assert snode_info
        nodes.append(snode_info)
      has_es = lambda n: IsExclusiveStorageEnabledNode(self.cfg, n)
      if compat.any(map(has_es, nodes)):
        errmsg = ("Cannot convert disk template from %s to %s when exclusive"
                  " storage is enabled" % (
                      self.cfg.GetInstanceDiskTemplate(self.instance.uuid),
                      self.op.disk_template))
        raise errors.OpPrereqError(errmsg, errors.ECODE_STATE)

    # TODO remove setting the disk template after DiskSetParams exists.
    # node capacity checks
    if (self.op.disk_template == constants.DT_PLAIN and
        utils.AllDiskOfType(inst_disks, [constants.DT_DRBD8])):
      # we ensure that no capacity checks will be made for conversions from
      # the 'drbd' to the 'plain' disk template
      pass
    elif (self.op.disk_template == constants.DT_DRBD8 and
          utils.AllDiskOfType(inst_disks, [constants.DT_PLAIN])):
      # for conversions from the 'plain' to the 'drbd' disk template, check
      # only the remote node's capacity
      if self.op.remote_node_uuid:
        req_sizes = ComputeDiskSizePerVG(self.op.disk_template, self.disks_info)
        CheckNodesFreeDiskPerVG(self, [self.op.remote_node_uuid], req_sizes)
    elif self.op.disk_template in constants.DTS_LVM:
      # rest lvm-based capacity checks
      node_uuids = [pnode_uuid]
      if self.op.remote_node_uuid:
        node_uuids.append(self.op.remote_node_uuid)
      req_sizes = ComputeDiskSizePerVG(self.op.disk_template, self.disks_info)
      CheckNodesFreeDiskPerVG(self, node_uuids, req_sizes)
    elif self.op.disk_template == constants.DT_RBD:
      # CheckRADOSFreeSpace() is simply a placeholder
      CheckRADOSFreeSpace()
    elif self.op.disk_template == constants.DT_EXT:
      # FIXME: Capacity checks for extstorage template, if exists
      pass
    else:
      # FIXME: Checks about other non lvm-based disk templates
      pass

  def _PreCheckDisks(self, ispec):
    """CheckPrereq checks related to disk changes.

    @type ispec: dict
    @param ispec: instance specs to be updated with the new disks

    """
    self.diskparams = self.cfg.GetInstanceDiskParams(self.instance)

    inst_nodes = self.cfg.GetInstanceNodes(self.instance.uuid)
    excl_stor = compat.any(
      list(rpc.GetExclusiveStorageForNodes(self.cfg, inst_nodes).values())
      )

    # Get the group access type
    node_info = self.cfg.GetNodeInfo(self.instance.primary_node)
    node_group = self.cfg.GetNodeGroup(node_info.group)
    group_disk_params = self.cfg.GetGroupDiskParams(node_group)

    group_access_types = dict(
        (dt, group_disk_params[dt].get(
            constants.RBD_ACCESS, constants.DISK_KERNELSPACE))
        for dt in constants.DISK_TEMPLATES)

    # Check disk modifications. This is done here and not in CheckArguments
    # (as with NICs), because we need to know the instance's disk template
    ver_fn = lambda op, par: self._VerifyDiskModification(op, par, excl_stor,
                                                          group_access_types)
    # Don't enforce param types here in case it's an ext disk added. The check
    # happens inside _VerifyDiskModification.
    self._CheckMods("disk", self.op.disks, {}, ver_fn)

    self.diskmod = PrepareContainerMods(self.op.disks, None)

    def _PrepareDiskMod(_, disk, params, __):
      disk.name = params.get(constants.IDISK_NAME, None)

    # Verify disk changes (operating on a copy)
    inst_disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    disks = copy.deepcopy(inst_disks)
    ApplyContainerMods("disk", disks, None, self.diskmod, None, None,
                       _PrepareDiskMod, None, None)
    utils.ValidateDeviceNames("disk", disks)
    if len(disks) > constants.MAX_DISKS:
      raise errors.OpPrereqError("Instance has too many disks (%d), cannot add"
                                 " more" % constants.MAX_DISKS,
                                 errors.ECODE_STATE)
    disk_sizes = [disk.size for disk in inst_disks]
    disk_sizes.extend(params["size"] for (op, idx, params, private) in
                      self.diskmod if op == constants.DDM_ADD)
    ispec[constants.ISPEC_DISK_COUNT] = len(disk_sizes)
    ispec[constants.ISPEC_DISK_SIZE] = disk_sizes

    # either --online or --offline was passed
    if self.op.offline is not None:
      if self.op.offline:
        msg = "can't change to offline without being down first"
      else:
        msg = "can't change to online (down) without being offline first"
      CheckInstanceState(self, self.instance, INSTANCE_NOT_RUNNING,
                         msg=msg)

  @staticmethod
  def _InstanceCommunicationDDM(cfg, instance_communication, instance):
    """Create a NIC mod that adds or removes the instance
    communication NIC to a running instance.

    The NICS are dynamically created using the Dynamic Device
    Modification (DDM).  This function produces a NIC modification
    (mod) that inserts an additional NIC meant for instance
    communication in or removes an existing instance communication NIC
    from a running instance, using DDM.

    @type cfg: L{config.ConfigWriter}
    @param cfg: cluster configuration

    @type instance_communication: boolean
    @param instance_communication: whether instance communication is
                                   enabled or disabled

    @type instance: L{objects.Instance}
    @param instance: instance to which the NIC mod will be applied to

    @rtype: (L{constants.DDM_ADD}, -1, parameters) or
            (L{constants.DDM_REMOVE}, -1, parameters) or
            L{None}
    @return: DDM mod containing an action to add or remove the NIC, or
             None if nothing needs to be done

    """
    nic_name = ComputeInstanceCommunicationNIC(instance.name)

    instance_communication_nic = None

    for nic in instance.nics:
      if nic.name == nic_name:
        instance_communication_nic = nic
        break

    if instance_communication and not instance_communication_nic:
      action = constants.DDM_ADD
      params = {constants.INIC_NAME: nic_name,
                constants.INIC_MAC: constants.VALUE_GENERATE,
                constants.INIC_IP: constants.NIC_IP_POOL,
                constants.INIC_NETWORK:
                  cfg.GetInstanceCommunicationNetwork()}
    elif not instance_communication and instance_communication_nic:
      action = constants.DDM_REMOVE
      params = None
    else:
      action = None
      params = None

    if action is not None:
      return (action, -1, params)
    else:
      return None

  def _GetInstanceInfo(self, cluster_hvparams):
    pnode_uuid = self.instance.primary_node
    instance_info = self.rpc.call_instance_info(
        pnode_uuid, self.instance.name, self.instance.hypervisor,
        cluster_hvparams)
    return instance_info

  def _CheckHotplug(self):
    if self.op.hotplug:
      result = self.rpc.call_hotplug_supported(self.instance.primary_node,
                                               self.instance)
      if result.fail_msg:
          self.LogWarning(result.fail_msg)
          self.op.hotplug = False
          self.LogInfo("Modification will take place without hotplugging.")
      else:
        self.op.hotplug = True

  def _PrepareNicCommunication(self):
    # add or remove NIC for instance communication
    if self.op.instance_communication is not None:
      mod = self._InstanceCommunicationDDM(self.cfg,
                                           self.op.instance_communication,
                                           self.instance)
      if mod is not None:
        self.op.nics.append(mod)

    self.nicmod = PrepareContainerMods(self.op.nics, InstNicModPrivate)

  def _ProcessHVParams(self, node_uuids):
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

  def _ProcessBeParams(self):
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
    return self.cluster.FillBE(self.instance)

  def _ValidateCpuParams(self):
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
      if constants.HV_CPU_MASK in self.hv_new and cpu_list:
        # Calculate the largest CPU number requested
        max_requested_cpu = max(map(max, cpu_list))
        # Check that all of the instance's nodes have enough physical CPUs to
        # satisfy the requested CPU mask
        hvspecs = [(self.instance.hypervisor,
                    self.cfg.GetClusterInfo()
                      .hvparams[self.instance.hypervisor])]
        CheckNodesPhysicalCPUs(self,
                               self.cfg.GetInstanceNodes(self.instance.uuid),
                               max_requested_cpu + 1,
                               hvspecs)

  def _ProcessOsParams(self, node_uuids):
    # osparams processing
    instance_os = (self.op.os_name
                   if self.op.os_name and not self.op.force
                   else self.instance.os)

    if self.op.osparams or self.op.osparams_private:
      public_parms = self.op.osparams or {}
      private_parms = self.op.osparams_private or {}
      dupe_keys = utils.GetRepeatedKeys(public_parms, private_parms)

      if dupe_keys:
        raise errors.OpPrereqError("OS parameters repeated multiple times: %s" %
                                   utils.CommaJoin(dupe_keys))

      self.os_inst = GetUpdatedParams(self.instance.osparams,
                                      public_parms)
      self.os_inst_private = GetUpdatedParams(self.instance.osparams_private,
                                              private_parms)

      CheckOSParams(self, True, node_uuids, instance_os,
                    objects.FillDict(self.os_inst,
                                     self.os_inst_private),
                    self.op.force_variant)

    else:
      self.os_inst = {}
      self.os_inst_private = {}

  def _ProcessMem(self, cluster_hvparams, be_old, pnode_uuid):
    #TODO(dynmem): do the appropriate check involving MINMEM
    if (constants.BE_MAXMEM in self.op.beparams and not self.op.force and
        self.be_new[constants.BE_MAXMEM] > be_old[constants.BE_MAXMEM]):
      mem_check_list = [pnode_uuid]
      if self.be_new[constants.BE_AUTO_BALANCE]:
        # either we changed auto_balance to yes or it was from before
        mem_check_list.extend(
          self.cfg.GetInstanceSecondaryNodes(self.instance.uuid))
      instance_info = self._GetInstanceInfo(cluster_hvparams)
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
          miss_mem = (self.be_new[constants.BE_MAXMEM] - current_mem -
                      pnhvinfo["memory_free"])
          if miss_mem > 0:
            raise errors.OpPrereqError("This change will prevent the instance"
                                       " from starting, due to %d MB of memory"
                                       " missing on its primary node" %
                                       miss_mem, errors.ECODE_NORES)

      if self.be_new[constants.BE_AUTO_BALANCE]:
        secondary_nodes = \
          self.cfg.GetInstanceSecondaryNodes(self.instance.uuid)
        for node_uuid, nres in nodeinfo.items():
          if node_uuid not in secondary_nodes:
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
          elif self.be_new[constants.BE_MAXMEM] > nhvinfo["memory_free"]:
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
                        self.cfg.GetNodeName(self.instance.primary_node),
                        prereq=True)
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

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    assert self.op.instance_name in self.owned_locks(locking.LEVEL_INSTANCE)
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    self.cluster = self.cfg.GetClusterInfo()
    cluster_hvparams = self.cluster.hvparams[self.instance.hypervisor]

    self.op.disks = self._LookupDiskMods()

    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    self.warn = []

    if (self.op.pnode_uuid is not None and
        self.op.pnode_uuid != self.instance.primary_node and
        not self.op.force):
      instance_info = self._GetInstanceInfo(cluster_hvparams)

      if instance_info.fail_msg:
        self.warn.append("Can't get instance runtime information: %s" %
                         instance_info.fail_msg)
      elif instance_info.payload:
        raise errors.OpPrereqError(
            "Instance is still running on %s" %
            self.cfg.GetNodeName(self.instance.primary_node),
            errors.ECODE_STATE)
    pnode_uuid = self.instance.primary_node
    assert pnode_uuid in self.owned_locks(locking.LEVEL_NODE)

    node_uuids = list(self.cfg.GetInstanceNodes(self.instance.uuid))
    pnode_info = self.cfg.GetNodeInfo(pnode_uuid)

    assert pnode_info.group in self.owned_locks(locking.LEVEL_NODEGROUP)
    group_info = self.cfg.GetNodeGroup(pnode_info.group)

    # dictionary with instance information after the modification
    ispec = {}

    self._CheckHotplug()

    self._PrepareNicCommunication()

    # disks processing
    assert not (self.op.disk_template and self.op.disks), \
      "Can't modify disk template and apply disk changes at the same time"

    if self.op.disk_template:
      self._PreCheckDiskTemplate(pnode_info)

    self._PreCheckDisks(ispec)

    self._ProcessHVParams(node_uuids)
    be_old = self._ProcessBeParams()

    self._ValidateCpuParams()
    self._ProcessOsParams(node_uuids)
    self._ProcessMem(cluster_hvparams, be_old, pnode_uuid)

    # make self.cluster visible in the functions below
    cluster = self.cluster

    def _PrepareNicCreate(_, params, private):
      self._PrepareNicModification(params, private, None, None,
                                   {}, cluster, pnode_uuid)
      return (None, None)

    def _PrepareNicAttach(_, __, ___):
      raise errors.OpPrereqError("Attach operation is not supported for NICs",
                                 errors.ECODE_INVAL)

    def _PrepareNicMod(_, nic, params, private):
      self._PrepareNicModification(params, private, nic.ip, nic.network,
                                   nic.nicparams, cluster, pnode_uuid)
      return None

    def _PrepareNicRemove(_, params, __):
      ip = params.ip
      net = params.network
      if net is not None and ip is not None:
        self.cfg.ReleaseIp(net, ip, self.proc.GetECId())

    def _PrepareNicDetach(_, __, ___):
      raise errors.OpPrereqError("Detach operation is not supported for NICs",
                                 errors.ECODE_INVAL)

    # Verify NIC changes (operating on copy)
    nics = [nic.Copy() for nic in self.instance.nics]
    ApplyContainerMods("NIC", nics, None, self.nicmod, _PrepareNicCreate,
                       _PrepareNicAttach, _PrepareNicMod, _PrepareNicRemove,
                       _PrepareNicDetach)
    if len(nics) > constants.MAX_NICS:
      raise errors.OpPrereqError("Instance has too many network interfaces"
                                 " (%d), cannot add more" % constants.MAX_NICS,
                                 errors.ECODE_STATE)

    # Pre-compute NIC changes (necessary to use result in hooks)
    self._nic_chgdesc = []
    if self.nicmod:
      # Operate on copies as this is still in prereq
      nics = [nic.Copy() for nic in self.instance.nics]
      ApplyContainerMods("NIC", nics, self._nic_chgdesc, self.nicmod,
                         self._CreateNewNic, None, self._ApplyNicMods,
                         self._RemoveNic, None)
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
        count = ispec[constants.ISPEC_DISK_COUNT]
        new_disk_types = [self.op.disk_template] * count
      else:
        old_disks = self.cfg.GetInstanceDisks(self.instance.uuid)
        add_disk_count = ispec[constants.ISPEC_DISK_COUNT] - len(old_disks)
        dev_type = self.cfg.GetInstanceDiskTemplate(self.instance.uuid)
        if dev_type == constants.DT_DISKLESS and add_disk_count != 0:
          raise errors.ProgrammerError(
              "Conversion from diskless instance not possible and should have"
              " been caught")

        new_disk_types = ([d.dev_type for d in old_disks] +
                          [dev_type] * add_disk_count)
      ispec_max = ispec.copy()
      ispec_max[constants.ISPEC_MEM_SIZE] = \
        self.be_new.get(constants.BE_MAXMEM, None)
      res_max = ComputeIPolicyInstanceSpecViolation(ipolicy, ispec_max,
                                                    new_disk_types)
      ispec_min = ispec.copy()
      ispec_min[constants.ISPEC_MEM_SIZE] = \
        self.be_new.get(constants.BE_MINMEM, None)
      res_min = ComputeIPolicyInstanceSpecViolation(ipolicy, ispec_min,
                                                    new_disk_types)

      if res_max or res_min:
        # FIXME: Improve error message by including information about whether
        # the upper or lower limit of the parameter fails the ipolicy.
        msg = ("Instance allocation to group %s (%s) violates policy: %s" %
               (group_info, group_info.name,
                utils.CommaJoin(set(res_max + res_min))))
        raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

  def _ConvertInstanceDisks(self, feedback_fn):
    """Converts the disks of an instance to another type.

    This function converts the disks of an instance. It supports
    conversions among all the available disk types except conversions
    between the LVM-based disk types, that use their separate code path.
    Also, this method does not support conversions that include the 'diskless'
    template and those targeting the 'blockdev' template.

    @type feedback_fn: callable
    @param feedback_fn: function used to send feedback back to the caller

    @rtype: NoneType
    @return: None
    @raise errors.OpPrereqError: in case of failure

    """
    template_info = self.op.disk_template
    if self.op.disk_template == constants.DT_EXT:
      template_info = ":".join([self.op.disk_template,
                                self.op.ext_params["provider"]])

    old_template = self.cfg.GetInstanceDiskTemplate(self.instance.uuid)
    feedback_fn("Converting disk template from '%s' to '%s'" %
                (old_template, template_info))

    assert not (old_template in constants.DTS_NOT_CONVERTIBLE_FROM or
                self.op.disk_template in constants.DTS_NOT_CONVERTIBLE_TO), \
      ("Unsupported disk template conversion from '%s' to '%s'" %
       (old_template, self.op.disk_template))

    pnode_uuid = self.instance.primary_node
    snode_uuid = []
    if self.op.remote_node_uuid:
      snode_uuid = [self.op.remote_node_uuid]

    old_disks = self.cfg.GetInstanceDisks(self.instance.uuid)

    feedback_fn("Generating new '%s' disk template..." % template_info)
    file_storage_dir = CalculateFileStorageDir(
        self.op.disk_template, self.cfg, self.instance.name,
        file_storage_dir=self.op.file_storage_dir)
    new_disks = GenerateDiskTemplate(self,
                                     self.op.disk_template,
                                     self.instance.uuid,
                                     pnode_uuid,
                                     snode_uuid,
                                     self.disks_info,
                                     file_storage_dir,
                                     self.op.file_driver,
                                     0,
                                     feedback_fn,
                                     self.diskparams)

    # Create the new block devices for the instance.
    feedback_fn("Creating new empty disks of type '%s'..." % template_info)
    try:
      CreateDisks(self, self.instance, disk_template=self.op.disk_template,
                  disks=new_disks)
    except errors.OpExecError:
      self.LogWarning("Device creation failed")
      for disk in new_disks:
        self.cfg.ReleaseDRBDMinors(disk.uuid)
      raise

    # Transfer the data from the old to the newly created disks of the instance.
    feedback_fn("Populating the new empty disks of type '%s'..." %
                template_info)
    for idx, (old, new) in enumerate(zip(old_disks, new_disks)):
      feedback_fn(" - copying data from disk %s (%s), size %s" %
                  (idx, old.dev_type,
                   utils.FormatUnit(new.size, "h")))
      if old.dev_type == constants.DT_DRBD8:
        old = old.children[0]
      result = self.rpc.call_blockdev_convert(pnode_uuid, (old, self.instance),
                                              (new, self.instance))
      msg = result.fail_msg
      if msg:
        # A disk failed to copy. Abort the conversion operation and rollback
        # the modifications to the previous state. The instance will remain
        # intact.
        if self.op.disk_template == constants.DT_DRBD8:
          new = new.children[0]
        self.Log(" - ERROR: Could not copy disk '%s' to '%s'" %
                 (old.logical_id[1], new.logical_id[1]))
        try:
          self.LogInfo("Some disks failed to copy")
          self.LogInfo("The instance will not be affected, aborting operation")
          self.LogInfo("Removing newly created disks of type '%s'..." %
                       template_info)
          RemoveDisks(self, self.instance, disks=new_disks)
          self.LogInfo("Newly created disks removed successfully")
        finally:
          for disk in new_disks:
            self.cfg.ReleaseDRBDMinors(disk.uuid)
          result.Raise("Error while converting the instance's template")

    # In case of DRBD disk, return its port to the pool
    for disk in old_disks:
      if disk.dev_type == constants.DT_DRBD8:
        tcp_port = disk.logical_id[2]
        self.cfg.AddTcpUdpPort(tcp_port)

    # Remove old disks from the instance.
    feedback_fn("Detaching old disks (%s) from the instance and removing"
                " them from cluster config" % old_template)
    for old_disk in old_disks:
      self.cfg.RemoveInstanceDisk(self.instance.uuid, old_disk.uuid)

    # Attach the new disks to the instance.
    feedback_fn("Adding new disks (%s) to cluster config and attaching"
                " them to the instance" % template_info)
    for (idx, new_disk) in enumerate(new_disks):
      self.cfg.AddInstanceDisk(self.instance.uuid, new_disk, idx=idx)

    # Re-read the instance from the configuration.
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

    # Release node locks while waiting for sync and disks removal.
    ReleaseLocks(self, locking.LEVEL_NODE)

    disk_abort = not WaitForSync(self, self.instance,
                                 oneshot=not self.op.wait_for_sync)
    if disk_abort:
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance, please cleanup manually")

    feedback_fn("Removing old block devices of type '%s'..." % old_template)
    RemoveDisks(self, self.instance, disks=old_disks)

    # Node resource locks will be released by the caller.

  def _ConvertPlainToDrbd(self, feedback_fn):
    """Converts an instance from plain to drbd.

    """
    feedback_fn("Converting disk template from 'plain' to 'drbd'")

    if not self.op.remote_node_uuid:
      feedback_fn("Using %s to choose new secondary" % self.op.iallocator)

      req = iallocator.IAReqInstanceAllocateSecondary(
        name=self.op.instance_name)
      ial = iallocator.IAllocator(self.cfg, self.rpc, req)
      ial.Run(self.op.iallocator)

      if not ial.success:
        raise errors.OpPrereqError("Can's find secondary node using"
                                   " iallocator %s: %s" %
                                   (self.op.iallocator, ial.info),
                                   errors.ECODE_NORES)
      feedback_fn("%s choose %s as new secondary"
                  % (self.op.iallocator, ial.result))
      self.op.remote_node = ial.result
      self.op.remote_node_uuid = self.cfg.GetNodeInfoByName(ial.result).uuid

    pnode_uuid = self.instance.primary_node
    snode_uuid = self.op.remote_node_uuid
    old_disks = self.cfg.GetInstanceDisks(self.instance.uuid)

    assert utils.AnyDiskOfType(old_disks, [constants.DT_PLAIN])

    new_disks = GenerateDiskTemplate(self, self.op.disk_template,
                                     self.instance.uuid, pnode_uuid,
                                     [snode_uuid], self.disks_info,
                                     None, None, 0,
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
                   for (o, n) in zip(old_disks, new_disks)]
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
    except errors.GenericError as e:
      feedback_fn("Initializing of DRBD devices failed;"
                  " renaming back original volumes...")
      rename_back_list = [(n.children[0], o.logical_id)
                          for (n, o) in zip(new_disks, old_disks)]
      result = self.rpc.call_blockdev_rename(pnode_uuid, rename_back_list)
      result.Raise("Failed to rename LVs back after error %s" % str(e))
      raise

    # Remove the old disks from the instance
    for old_disk in old_disks:
      self.cfg.RemoveInstanceDisk(self.instance.uuid, old_disk.uuid)

    # Attach the new disks to the instance
    for (idx, new_disk) in enumerate(new_disks):
      self.cfg.AddInstanceDisk(self.instance.uuid, new_disk, idx=idx)

    # re-read the instance from the configuration
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

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
    secondary_nodes = self.cfg.GetInstanceSecondaryNodes(self.instance.uuid)
    disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    assert len(secondary_nodes) == 1
    assert utils.AnyDiskOfType(disks, [constants.DT_DRBD8])

    feedback_fn("Converting disk template from 'drbd' to 'plain'")

    old_disks = AnnotateDiskParams(self.instance, disks, self.cfg)
    new_disks = [d.children[0] for d in disks]

    # copy over size, mode and name and set the correct nodes
    for parent, child in zip(old_disks, new_disks):
      child.size = parent.size
      child.mode = parent.mode
      child.name = parent.name
      child.nodes = [self.instance.primary_node]

    # this is a DRBD disk, return its port to the pool
    for disk in old_disks:
      tcp_port = disk.logical_id[2]
      self.cfg.AddTcpUdpPort(tcp_port)

    # Remove the old disks from the instance
    for old_disk in old_disks:
      self.cfg.RemoveInstanceDisk(self.instance.uuid, old_disk.uuid)

    # Attach the new disks to the instance
    for (idx, new_disk) in enumerate(new_disks):
      self.cfg.AddInstanceDisk(self.instance.uuid, new_disk, idx=idx)

    # re-read the instance from the configuration
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

    # Release locks in case removing disks takes a while
    ReleaseLocks(self, locking.LEVEL_NODE)

    feedback_fn("Removing volumes on the secondary node...")
    RemoveDisks(self, self.instance, disks=old_disks,
                target_node_uuid=secondary_nodes[0])

    feedback_fn("Removing unneeded volumes on the primary node...")
    meta_disks = []
    for idx, disk in enumerate(old_disks):
      meta_disks.append(disk.children[1])
    RemoveDisks(self, self.instance, disks=meta_disks)

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

  def _FillFileDriver(self):
    if not self.op.file_driver:
      self.op.file_driver = constants.FD_DEFAULT
    elif self.op.file_driver not in constants.FILE_DRIVER:
      raise errors.OpPrereqError("Invalid file driver name '%s'" %
                                 self.op.file_driver, errors.ECODE_INVAL)

  def _GenerateDiskTemplateWrapper(self, idx, disk_type, params):
    file_path = CalculateFileStorageDir(
        disk_type, self.cfg, self.instance.name,
        file_storage_dir=self.op.file_storage_dir)

    self._FillFileDriver()

    secondary_nodes = self.cfg.GetInstanceSecondaryNodes(self.instance.uuid)
    return \
      GenerateDiskTemplate(self, disk_type, self.instance.uuid,
                           self.instance.primary_node, secondary_nodes,
                           [params], file_path, self.op.file_driver, idx,
                           self.Log, self.diskparams)[0]

  def _CreateNewDisk(self, idx, params, _):
    """Creates a new disk.

    """
    # add a new disk
    disk_template = self.cfg.GetInstanceDiskTemplate(self.instance.uuid)
    disk = self._GenerateDiskTemplateWrapper(idx, disk_template,
                                             params)
    new_disks = CreateDisks(self, self.instance, disks=[disk])
    self.cfg.AddInstanceDisk(self.instance.uuid, disk, idx)

    # re-read the instance from the configuration
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

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
                                               self.instance, True, idx)
      if result.fail_msg:
        changes.append(("disk/%d" % idx, "assemble:failed"))
        self.LogWarning("Can't assemble newly created disk %d: %s",
                        idx, result.fail_msg)
      else:
        _, link_name, uri = result.payload
        msg = self._HotplugDevice(constants.HOTPLUG_ACTION_ADD,
                                  constants.HOTPLUG_TARGET_DISK,
                                  disk, (link_name, uri), idx)
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

  def _AttachDisk(self, idx, params, _):
    """Attaches an existing disk to an instance.

    """
    uuid = params.get("uuid", None)
    name = params.get(constants.IDISK_NAME, None)

    disk = self.GenericGetDiskInfo(uuid, name)

    # Rename disk before attaching (if disk is filebased)
    if disk.dev_type in constants.DTS_INSTANCE_DEPENDENT_PATH:
      # Add disk size/mode, else GenerateDiskTemplate will not work.
      params[constants.IDISK_SIZE] = disk.size
      params[constants.IDISK_MODE] = str(disk.mode)
      dummy_disk = self._GenerateDiskTemplateWrapper(idx, disk.dev_type, params)
      new_logical_id = dummy_disk.logical_id
      result = self.rpc.call_blockdev_rename(self.instance.primary_node,
                                             [(disk, new_logical_id)])
      result.Raise("Failed before attach")
      self.cfg.SetDiskLogicalID(disk.uuid, new_logical_id)
      disk.logical_id = new_logical_id

    # Attach disk to instance
    self.cfg.AttachInstanceDisk(self.instance.uuid, disk.uuid, idx)

    # re-read the instance from the configuration
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

    changes = [
      ("disk/%d" % idx,
       "attach:size=%s,mode=%s" % (disk.size, disk.mode)),
      ]

    disks_ok, _, payloads = AssembleInstanceDisks(self, self.instance,
                                                  disks=[disk])
    if not disks_ok:
      changes.append(("disk/%d" % idx, "assemble:failed"))
      return disk, changes

    if self.op.hotplug:
      _, link_name, uri = payloads[0]
      msg = self._HotplugDevice(constants.HOTPLUG_ACTION_ADD,
                                constants.HOTPLUG_TARGET_DISK,
                                disk, (link_name, uri), idx)
      changes.append(("disk/%d" % idx, msg))

    return (disk, changes)

  def _ModifyDisk(self, idx, disk, params, _):
    """Modifies a disk.

    """
    changes = []
    if constants.IDISK_MODE in params:
      disk.mode = params.get(constants.IDISK_MODE)
      changes.append(("disk.mode/%d" % idx, disk.mode))

    if constants.IDISK_NAME in params:
      disk.name = params.get(constants.IDISK_NAME)
      changes.append(("disk.name/%d" % idx, disk.name))

    # Modify arbitrary params in case instance template is ext

    for key, value in params.items():
      if (key not in constants.MODIFIABLE_IDISK_PARAMS and
          disk.dev_type == constants.DT_EXT):
        # stolen from GetUpdatedParams: default means reset/delete
        if value.lower() == constants.VALUE_DEFAULT:
          try:
            del disk.params[key]
          except KeyError:
            pass
        else:
          disk.params[key] = value
        changes.append(("disk.params:%s/%d" % (key, idx), value))

    # Update disk object
    self.cfg.Update(disk, self.feedback_fn)

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

    RemoveDisks(self, self.instance, disks=[root])

    # if this is a DRBD disk, return its port to the pool
    if root.dev_type in constants.DTS_DRBD:
      self.cfg.AddTcpUdpPort(root.logical_id[2])

    # Remove disk from config
    self.cfg.RemoveInstanceDisk(self.instance.uuid, root.uuid)

    # re-read the instance from the configuration
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

    return hotmsg

  def _DetachDisk(self, idx, root, _):
    """Detaches a disk from an instance.

    """
    hotmsg = ""
    if self.op.hotplug:
      hotmsg = self._HotplugDevice(constants.HOTPLUG_ACTION_REMOVE,
                                   constants.HOTPLUG_TARGET_DISK,
                                   root, None, idx)

    # Always shutdown the disk before detaching.
    ShutdownInstanceDisks(self, self.instance, [root])

    # Rename detached disk.
    #
    # Transform logical_id from:
    #   <file_storage_dir>/<instance_name>/<disk_name>
    # to
    #   <file_storage_dir>/<disk_name>
    if root.dev_type in (constants.DT_FILE, constants.DT_SHARED_FILE):
      file_driver = root.logical_id[0]
      instance_path, disk_name = os.path.split(root.logical_id[1])
      new_path = os.path.join(os.path.dirname(instance_path), disk_name)
      new_logical_id = (file_driver, new_path)
      result = self.rpc.call_blockdev_rename(self.instance.primary_node,
                                             [(root, new_logical_id)])
      result.Raise("Failed before detach")
      # Update logical_id
      self.cfg.SetDiskLogicalID(root.uuid, new_logical_id)

    # Remove disk from config
    self.cfg.DetachInstanceDisk(self.instance.uuid, root.uuid)

    # re-read the instance from the configuration
    self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

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
    self.feedback_fn = feedback_fn
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
    inst_disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    ApplyContainerMods("disk", inst_disks, result, self.diskmod,
                       self._CreateNewDisk, self._AttachDisk, self._ModifyDisk,
                       self._RemoveDisk, self._DetachDisk,
                       post_add_fn=self._PostAddDisk)

    if self.op.disk_template:
      if __debug__:
        check_nodes = set(self.cfg.GetInstanceNodes(self.instance.uuid))
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
      #TODO make heterogeneous conversions work
      mode = (self.cfg.GetInstanceDiskTemplate(self.instance.uuid),
              self.op.disk_template)
      try:
        if mode in self._DISK_CONVERSIONS:
          self._DISK_CONVERSIONS[mode](self, feedback_fn)
        else:
          self._ConvertInstanceDisks(feedback_fn)
      except:
        for disk in inst_disks:
          self.cfg.ReleaseDRBDMinors(disk.uuid)
        raise
      result.append(("disk_template", self.op.disk_template))

      disk_info = self.cfg.GetInstanceDisks(self.instance.uuid)
      assert utils.AllDiskOfType(disk_info, [self.op.disk_template]), \
        ("Expected disk template '%s', found '%s'" %
         (self.op.disk_template,
          self.cfg.GetInstanceDiskTemplate(self.instance.uuid)))

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
      for key, val in self.op.hvparams.items():
        result.append(("hv/%s" % key, val))

    # beparams changes
    if self.op.beparams:
      self.instance.beparams = self.be_inst
      for key, val in self.op.beparams.items():
        result.append(("be/%s" % key, val))

    # OS change
    if self.op.os_name:
      self.instance.os = self.op.os_name

    # osparams changes
    if self.op.osparams:
      self.instance.osparams = self.os_inst
      for key, val in self.op.osparams.items():
        result.append(("os/%s" % key, val))

    if self.op.osparams_private:
      self.instance.osparams_private = self.os_inst_private
      for key, val in self.op.osparams_private.items():
        # Show the Private(...) blurb.
        result.append(("os_private/%s" % key, repr(val)))

    self.cfg.Update(self.instance, feedback_fn, self.proc.GetECId())

    if self.op.offline is None:
      # Ignore
      pass
    elif self.op.offline:
      # Mark instance as offline
      self.instance = self.cfg.MarkInstanceOffline(self.instance.uuid)
      result.append(("admin_state", constants.ADMINST_OFFLINE))
    else:
      # Mark instance as online, but stopped
      self.instance = self.cfg.MarkInstanceDown(self.instance.uuid)
      result.append(("admin_state", constants.ADMINST_DOWN))

    UpdateMetadata(feedback_fn, self.rpc, self.instance)

    assert not (self.owned_locks(locking.LEVEL_NODE_RES) or
                self.owned_locks(locking.LEVEL_NODE)), \
      "All node locks should have been released by now"

    return result

  _DISK_CONVERSIONS = {
    (constants.DT_PLAIN, constants.DT_DRBD8): _ConvertPlainToDrbd,
    (constants.DT_DRBD8, constants.DT_PLAIN): _ConvertDrbdToPlain,
    }
