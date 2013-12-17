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


"""Logical units dealing with storage of instances."""

import itertools
import logging
import os
import time

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import ht
from ganeti import locking
from ganeti.masterd import iallocator
from ganeti import objects
from ganeti import utils
from ganeti import rpc
from ganeti.cmdlib.base import LogicalUnit, NoHooksLU, Tasklet
from ganeti.cmdlib.common import INSTANCE_DOWN, INSTANCE_NOT_RUNNING, \
  AnnotateDiskParams, CheckIAllocatorOrNode, ExpandNodeUuidAndName, \
  CheckNodeOnline, CheckInstanceNodeGroups, CheckInstanceState, \
  IsExclusiveStorageEnabledNode, FindFaultyInstanceDisks, GetWantedNodes, \
  CheckDiskTemplateEnabled
from ganeti.cmdlib.instance_utils import GetInstanceInfoText, \
  CopyLockList, ReleaseLocks, CheckNodeVmCapable, \
  BuildInstanceHookEnvByObject, CheckNodeNotDrained, CheckTargetNodeIPolicy

import ganeti.masterd.instance


_DISK_TEMPLATE_NAME_PREFIX = {
  constants.DT_PLAIN: "",
  constants.DT_RBD: ".rbd",
  constants.DT_EXT: ".ext",
  }


def CreateSingleBlockDev(lu, node_uuid, instance, device, info, force_open,
                         excl_stor):
  """Create a single block device on a given node.

  This will not recurse over children of the device, so they must be
  created in advance.

  @param lu: the lu on whose behalf we execute
  @param node_uuid: the node on which to create the device
  @type instance: L{objects.Instance}
  @param instance: the instance which owns the device
  @type device: L{objects.Disk}
  @param device: the device to create
  @param info: the extra 'metadata' we should attach to the device
      (this will be represented as a LVM tag)
  @type force_open: boolean
  @param force_open: this parameter will be passes to the
      L{backend.BlockdevCreate} function where it specifies
      whether we run on primary or not, and it affects both
      the child assembly and the device own Open() execution
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active for the node

  """
  result = lu.rpc.call_blockdev_create(node_uuid, (device, instance),
                                       device.size, instance.name, force_open,
                                       info, excl_stor)
  result.Raise("Can't create block device %s on"
               " node %s for instance %s" % (device,
                                             lu.cfg.GetNodeName(node_uuid),
                                             instance.name))


def _CreateBlockDevInner(lu, node_uuid, instance, device, force_create,
                         info, force_open, excl_stor):
  """Create a tree of block devices on a given node.

  If this device type has to be created on secondaries, create it and
  all its children.

  If not, just recurse to children keeping the same 'force' value.

  @attention: The device has to be annotated already.

  @param lu: the lu on whose behalf we execute
  @param node_uuid: the node on which to create the device
  @type instance: L{objects.Instance}
  @param instance: the instance which owns the device
  @type device: L{objects.Disk}
  @param device: the device to create
  @type force_create: boolean
  @param force_create: whether to force creation of this device; this
      will be change to True whenever we find a device which has
      CreateOnSecondary() attribute
  @param info: the extra 'metadata' we should attach to the device
      (this will be represented as a LVM tag)
  @type force_open: boolean
  @param force_open: this parameter will be passes to the
      L{backend.BlockdevCreate} function where it specifies
      whether we run on primary or not, and it affects both
      the child assembly and the device own Open() execution
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active for the node

  @return: list of created devices
  """
  created_devices = []
  try:
    if device.CreateOnSecondary():
      force_create = True

    if device.children:
      for child in device.children:
        devs = _CreateBlockDevInner(lu, node_uuid, instance, child,
                                    force_create, info, force_open, excl_stor)
        created_devices.extend(devs)

    if not force_create:
      return created_devices

    CreateSingleBlockDev(lu, node_uuid, instance, device, info, force_open,
                         excl_stor)
    # The device has been completely created, so there is no point in keeping
    # its subdevices in the list. We just add the device itself instead.
    created_devices = [(node_uuid, device)]
    return created_devices

  except errors.DeviceCreationError, e:
    e.created_devices.extend(created_devices)
    raise e
  except errors.OpExecError, e:
    raise errors.DeviceCreationError(str(e), created_devices)


def IsExclusiveStorageEnabledNodeUuid(cfg, node_uuid):
  """Whether exclusive_storage is in effect for the given node.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type node_uuid: string
  @param node_uuid: The node UUID
  @rtype: bool
  @return: The effective value of exclusive_storage
  @raise errors.OpPrereqError: if no node exists with the given name

  """
  ni = cfg.GetNodeInfo(node_uuid)
  if ni is None:
    raise errors.OpPrereqError("Invalid node UUID %s" % node_uuid,
                               errors.ECODE_NOENT)
  return IsExclusiveStorageEnabledNode(cfg, ni)


def _CreateBlockDev(lu, node_uuid, instance, device, force_create, info,
                    force_open):
  """Wrapper around L{_CreateBlockDevInner}.

  This method annotates the root device first.

  """
  (disk,) = AnnotateDiskParams(instance, [device], lu.cfg)
  excl_stor = IsExclusiveStorageEnabledNodeUuid(lu.cfg, node_uuid)
  return _CreateBlockDevInner(lu, node_uuid, instance, disk, force_create, info,
                              force_open, excl_stor)


def _UndoCreateDisks(lu, disks_created, instance):
  """Undo the work performed by L{CreateDisks}.

  This function is called in case of an error to undo the work of
  L{CreateDisks}.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @param disks_created: the result returned by L{CreateDisks}
  @type instance: L{objects.Instance}
  @param instance: the instance for which disks were created

  """
  for (node_uuid, disk) in disks_created:
    result = lu.rpc.call_blockdev_remove(node_uuid, (disk, instance))
    result.Warn("Failed to remove newly-created disk %s on node %s" %
                (disk, lu.cfg.GetNodeName(node_uuid)), logging.warning)


def CreateDisks(lu, instance, to_skip=None, target_node_uuid=None, disks=None):
  """Create all disks for an instance.

  This abstracts away some work from AddInstance.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should create
  @type to_skip: list
  @param to_skip: list of indices to skip
  @type target_node_uuid: string
  @param target_node_uuid: if passed, overrides the target node for creation
  @type disks: list of {objects.Disk}
  @param disks: the disks to create; if not specified, all the disks of the
      instance are created
  @return: information about the created disks, to be used to call
      L{_UndoCreateDisks}
  @raise errors.OpPrereqError: in case of error

  """
  info = GetInstanceInfoText(instance)
  if target_node_uuid is None:
    pnode_uuid = instance.primary_node
    all_node_uuids = instance.all_nodes
  else:
    pnode_uuid = target_node_uuid
    all_node_uuids = [pnode_uuid]

  if disks is None:
    disks = instance.disks

  CheckDiskTemplateEnabled(lu.cfg.GetClusterInfo(), instance.disk_template)

  if instance.disk_template in constants.DTS_FILEBASED:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    result = lu.rpc.call_file_storage_dir_create(pnode_uuid, file_storage_dir)

    result.Raise("Failed to create directory '%s' on"
                 " node %s" % (file_storage_dir,
                               lu.cfg.GetNodeName(pnode_uuid)))

  disks_created = []
  for idx, device in enumerate(disks):
    if to_skip and idx in to_skip:
      continue
    logging.info("Creating disk %s for instance '%s'", idx, instance.name)
    for node_uuid in all_node_uuids:
      f_create = node_uuid == pnode_uuid
      try:
        _CreateBlockDev(lu, node_uuid, instance, device, f_create, info,
                        f_create)
        disks_created.append((node_uuid, device))
      except errors.DeviceCreationError, e:
        logging.warning("Creating disk %s for instance '%s' failed",
                        idx, instance.name)
        disks_created.extend(e.created_devices)
        _UndoCreateDisks(lu, disks_created, instance)
        raise errors.OpExecError(e.message)
  return disks_created


def ComputeDiskSizePerVG(disk_template, disks):
  """Compute disk size requirements in the volume group

  """
  def _compute(disks, payload):
    """Universal algorithm.

    """
    vgs = {}
    for disk in disks:
      vgs[disk[constants.IDISK_VG]] = \
        vgs.get(constants.IDISK_VG, 0) + disk[constants.IDISK_SIZE] + payload

    return vgs

  # Required free disk space as a function of disk and swap space
  req_size_dict = {
    constants.DT_DISKLESS: {},
    constants.DT_PLAIN: _compute(disks, 0),
    # 128 MB are added for drbd metadata for each disk
    constants.DT_DRBD8: _compute(disks, constants.DRBD_META_SIZE),
    constants.DT_FILE: {},
    constants.DT_SHARED_FILE: {},
    constants.DT_GLUSTER: {},
    }

  if disk_template not in req_size_dict:
    raise errors.ProgrammerError("Disk template '%s' size requirement"
                                 " is unknown" % disk_template)

  return req_size_dict[disk_template]


def ComputeDisks(op, default_vg):
  """Computes the instance disks.

  @param op: The instance opcode
  @param default_vg: The default_vg to assume

  @return: The computed disks

  """
  disks = []
  for disk in op.disks:
    mode = disk.get(constants.IDISK_MODE, constants.DISK_RDWR)
    if mode not in constants.DISK_ACCESS_SET:
      raise errors.OpPrereqError("Invalid disk access mode '%s'" %
                                 mode, errors.ECODE_INVAL)
    size = disk.get(constants.IDISK_SIZE, None)
    if size is None:
      raise errors.OpPrereqError("Missing disk size", errors.ECODE_INVAL)
    try:
      size = int(size)
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid disk size '%s'" % size,
                                 errors.ECODE_INVAL)

    ext_provider = disk.get(constants.IDISK_PROVIDER, None)
    if ext_provider and op.disk_template != constants.DT_EXT:
      raise errors.OpPrereqError("The '%s' option is only valid for the %s"
                                 " disk template, not %s" %
                                 (constants.IDISK_PROVIDER, constants.DT_EXT,
                                  op.disk_template), errors.ECODE_INVAL)

    data_vg = disk.get(constants.IDISK_VG, default_vg)
    name = disk.get(constants.IDISK_NAME, None)
    if name is not None and name.lower() == constants.VALUE_NONE:
      name = None
    new_disk = {
      constants.IDISK_SIZE: size,
      constants.IDISK_MODE: mode,
      constants.IDISK_VG: data_vg,
      constants.IDISK_NAME: name,
      }

    for key in [
      constants.IDISK_METAVG,
      constants.IDISK_ADOPT,
      constants.IDISK_SPINDLES,
      ]:
      if key in disk:
        new_disk[key] = disk[key]

    # For extstorage, demand the `provider' option and add any
    # additional parameters (ext-params) to the dict
    if op.disk_template == constants.DT_EXT:
      if ext_provider:
        new_disk[constants.IDISK_PROVIDER] = ext_provider
        for key in disk:
          if key not in constants.IDISK_PARAMS:
            new_disk[key] = disk[key]
      else:
        raise errors.OpPrereqError("Missing provider for template '%s'" %
                                   constants.DT_EXT, errors.ECODE_INVAL)

    disks.append(new_disk)

  return disks


def CheckRADOSFreeSpace():
  """Compute disk size requirements inside the RADOS cluster.

  """
  # For the RADOS cluster we assume there is always enough space.
  pass


def _GenerateDRBD8Branch(lu, primary_uuid, secondary_uuid, size, vgnames, names,
                         iv_name, p_minor, s_minor):
  """Generate a drbd8 device complete with its children.

  """
  assert len(vgnames) == len(names) == 2
  port = lu.cfg.AllocatePort()
  shared_secret = lu.cfg.GenerateDRBDSecret(lu.proc.GetECId())

  dev_data = objects.Disk(dev_type=constants.DT_PLAIN, size=size,
                          logical_id=(vgnames[0], names[0]),
                          params={})
  dev_data.uuid = lu.cfg.GenerateUniqueID(lu.proc.GetECId())
  dev_meta = objects.Disk(dev_type=constants.DT_PLAIN,
                          size=constants.DRBD_META_SIZE,
                          logical_id=(vgnames[1], names[1]),
                          params={})
  dev_meta.uuid = lu.cfg.GenerateUniqueID(lu.proc.GetECId())
  drbd_dev = objects.Disk(dev_type=constants.DT_DRBD8, size=size,
                          logical_id=(primary_uuid, secondary_uuid, port,
                                      p_minor, s_minor,
                                      shared_secret),
                          children=[dev_data, dev_meta],
                          iv_name=iv_name, params={})
  drbd_dev.uuid = lu.cfg.GenerateUniqueID(lu.proc.GetECId())
  return drbd_dev


def GenerateDiskTemplate(
  lu, template_name, instance_uuid, primary_node_uuid, secondary_node_uuids,
  disk_info, file_storage_dir, file_driver, base_index,
  feedback_fn, full_disk_params):
  """Generate the entire disk layout for a given template type.

  """
  vgname = lu.cfg.GetVGName()
  disk_count = len(disk_info)
  disks = []

  CheckDiskTemplateEnabled(lu.cfg.GetClusterInfo(), template_name)

  if template_name == constants.DT_DISKLESS:
    pass
  elif template_name == constants.DT_DRBD8:
    if len(secondary_node_uuids) != 1:
      raise errors.ProgrammerError("Wrong template configuration")
    remote_node_uuid = secondary_node_uuids[0]
    minors = lu.cfg.AllocateDRBDMinor(
      [primary_node_uuid, remote_node_uuid] * len(disk_info), instance_uuid)

    (drbd_params, _, _) = objects.Disk.ComputeLDParams(template_name,
                                                       full_disk_params)
    drbd_default_metavg = drbd_params[constants.LDP_DEFAULT_METAVG]

    names = []
    for lv_prefix in _GenerateUniqueNames(lu, [".disk%d" % (base_index + i)
                                               for i in range(disk_count)]):
      names.append(lv_prefix + "_data")
      names.append(lv_prefix + "_meta")
    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      data_vg = disk.get(constants.IDISK_VG, vgname)
      meta_vg = disk.get(constants.IDISK_METAVG, drbd_default_metavg)
      disk_dev = _GenerateDRBD8Branch(lu, primary_node_uuid, remote_node_uuid,
                                      disk[constants.IDISK_SIZE],
                                      [data_vg, meta_vg],
                                      names[idx * 2:idx * 2 + 2],
                                      "disk/%d" % disk_index,
                                      minors[idx * 2], minors[idx * 2 + 1])
      disk_dev.mode = disk[constants.IDISK_MODE]
      disk_dev.name = disk.get(constants.IDISK_NAME, None)
      disks.append(disk_dev)
  else:
    if secondary_node_uuids:
      raise errors.ProgrammerError("Wrong template configuration")

    name_prefix = _DISK_TEMPLATE_NAME_PREFIX.get(template_name, None)
    if name_prefix is None:
      names = None
    else:
      names = _GenerateUniqueNames(lu, ["%s.disk%s" %
                                        (name_prefix, base_index + i)
                                        for i in range(disk_count)])

    if template_name == constants.DT_PLAIN:

      def logical_id_fn(idx, _, disk):
        vg = disk.get(constants.IDISK_VG, vgname)
        return (vg, names[idx])

    elif template_name in constants.DTS_FILEBASED:
      logical_id_fn = \
        lambda _, disk_index, disk: (file_driver,
                                     "%s/disk%d" % (file_storage_dir,
                                                    disk_index))
    elif template_name == constants.DT_BLOCK:
      logical_id_fn = \
        lambda idx, disk_index, disk: (constants.BLOCKDEV_DRIVER_MANUAL,
                                       disk[constants.IDISK_ADOPT])
    elif template_name == constants.DT_RBD:
      logical_id_fn = lambda idx, _, disk: ("rbd", names[idx])
    elif template_name == constants.DT_EXT:
      def logical_id_fn(idx, _, disk):
        provider = disk.get(constants.IDISK_PROVIDER, None)
        if provider is None:
          raise errors.ProgrammerError("Disk template is %s, but '%s' is"
                                       " not found", constants.DT_EXT,
                                       constants.IDISK_PROVIDER)
        return (provider, names[idx])
    else:
      raise errors.ProgrammerError("Unknown disk template '%s'" % template_name)

    dev_type = template_name

    for idx, disk in enumerate(disk_info):
      params = {}
      # Only for the Ext template add disk_info to params
      if template_name == constants.DT_EXT:
        params[constants.IDISK_PROVIDER] = disk[constants.IDISK_PROVIDER]
        for key in disk:
          if key not in constants.IDISK_PARAMS:
            params[key] = disk[key]
      disk_index = idx + base_index
      size = disk[constants.IDISK_SIZE]
      feedback_fn("* disk %s, size %s" %
                  (disk_index, utils.FormatUnit(size, "h")))
      disk_dev = objects.Disk(dev_type=dev_type, size=size,
                              logical_id=logical_id_fn(idx, disk_index, disk),
                              iv_name="disk/%d" % disk_index,
                              mode=disk[constants.IDISK_MODE],
                              params=params,
                              spindles=disk.get(constants.IDISK_SPINDLES))
      disk_dev.name = disk.get(constants.IDISK_NAME, None)
      disk_dev.uuid = lu.cfg.GenerateUniqueID(lu.proc.GetECId())
      disks.append(disk_dev)

  return disks


def CheckSpindlesExclusiveStorage(diskdict, es_flag, required):
  """Check the presence of the spindle options with exclusive_storage.

  @type diskdict: dict
  @param diskdict: disk parameters
  @type es_flag: bool
  @param es_flag: the effective value of the exlusive_storage flag
  @type required: bool
  @param required: whether spindles are required or just optional
  @raise errors.OpPrereqError when spindles are given and they should not

  """
  if (not es_flag and constants.IDISK_SPINDLES in diskdict and
      diskdict[constants.IDISK_SPINDLES] is not None):
    raise errors.OpPrereqError("Spindles in instance disks cannot be specified"
                               " when exclusive storage is not active",
                               errors.ECODE_INVAL)
  if (es_flag and required and (constants.IDISK_SPINDLES not in diskdict or
                                diskdict[constants.IDISK_SPINDLES] is None)):
    raise errors.OpPrereqError("You must specify spindles in instance disks"
                               " when exclusive storage is active",
                               errors.ECODE_INVAL)


class LUInstanceRecreateDisks(LogicalUnit):
  """Recreate an instance's missing disks.

  """
  HPATH = "instance-recreate-disks"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  _MODIFYABLE = compat.UniqueFrozenset([
    constants.IDISK_SIZE,
    constants.IDISK_MODE,
    constants.IDISK_SPINDLES,
    ])

  # New or changed disk parameters may have different semantics
  assert constants.IDISK_PARAMS == (_MODIFYABLE | frozenset([
    constants.IDISK_ADOPT,

    # TODO: Implement support changing VG while recreating
    constants.IDISK_VG,
    constants.IDISK_METAVG,
    constants.IDISK_PROVIDER,
    constants.IDISK_NAME,
    ]))

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    be_full = self.cfg.GetClusterInfo().FillBE(self.instance)

    # FIXME
    # The allocator should actually run in "relocate" mode, but current
    # allocators don't support relocating all the nodes of an instance at
    # the same time. As a workaround we use "allocate" mode, but this is
    # suboptimal for two reasons:
    # - The instance name passed to the allocator is present in the list of
    #   existing instances, so there could be a conflict within the
    #   internal structures of the allocator. This doesn't happen with the
    #   current allocators, but it's a liability.
    # - The allocator counts the resources used by the instance twice: once
    #   because the instance exists already, and once because it tries to
    #   allocate a new instance.
    # The allocator could choose some of the nodes on which the instance is
    # running, but that's not a problem. If the instance nodes are broken,
    # they should be already be marked as drained or offline, and hence
    # skipped by the allocator. If instance disks have been lost for other
    # reasons, then recreating the disks on the same nodes should be fine.
    disk_template = self.instance.disk_template
    spindle_use = be_full[constants.BE_SPINDLE_USE]
    disks = [{
      constants.IDISK_SIZE: d.size,
      constants.IDISK_MODE: d.mode,
      constants.IDISK_SPINDLES: d.spindles,
      } for d in self.instance.disks]
    req = iallocator.IAReqInstanceAlloc(name=self.op.instance_name,
                                        disk_template=disk_template,
                                        tags=list(self.instance.GetTags()),
                                        os=self.instance.os,
                                        nics=[{}],
                                        vcpus=be_full[constants.BE_VCPUS],
                                        memory=be_full[constants.BE_MAXMEM],
                                        spindle_use=spindle_use,
                                        disks=disks,
                                        hypervisor=self.instance.hypervisor,
                                        node_whitelist=None)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    assert req.RequiredNodes() == len(self.instance.all_nodes)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using iallocator '%s':"
                                 " %s" % (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)

    (self.op.node_uuids, self.op.nodes) = GetWantedNodes(self, ial.result)
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(self.op.nodes))

  def CheckArguments(self):
    if self.op.disks and ht.TNonNegativeInt(self.op.disks[0]):
      # Normalize and convert deprecated list of disk indices
      self.op.disks = [(idx, {}) for idx in sorted(frozenset(self.op.disks))]

    duplicates = utils.FindDuplicates(map(compat.fst, self.op.disks))
    if duplicates:
      raise errors.OpPrereqError("Some disks have been specified more than"
                                 " once: %s" % utils.CommaJoin(duplicates),
                                 errors.ECODE_INVAL)

    # We don't want _CheckIAllocatorOrNode selecting the default iallocator
    # when neither iallocator nor nodes are specified
    if self.op.iallocator or self.op.nodes:
      CheckIAllocatorOrNode(self, "iallocator", "nodes")

    for (idx, params) in self.op.disks:
      utils.ForceDictType(params, constants.IDISK_PARAMS_TYPES)
      unsupported = frozenset(params.keys()) - self._MODIFYABLE
      if unsupported:
        raise errors.OpPrereqError("Parameters for disk %s try to change"
                                   " unmodifyable parameter(s): %s" %
                                   (idx, utils.CommaJoin(unsupported)),
                                   errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

    if self.op.nodes:
      (self.op.node_uuids, self.op.nodes) = GetWantedNodes(self, self.op.nodes)
      self.needed_locks[locking.LEVEL_NODE] = list(self.op.node_uuids)
    else:
      self.needed_locks[locking.LEVEL_NODE] = []
      if self.op.iallocator:
        # iallocator will select a new node in the same group
        self.needed_locks[locking.LEVEL_NODEGROUP] = []
        self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

    self.needed_locks[locking.LEVEL_NODE_RES] = []

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert self.op.iallocator is not None
      assert not self.op.nodes
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]
      self.share_locks[locking.LEVEL_NODEGROUP] = 1
      # Lock the primary group used by the instance optimistically; this
      # requires going via the node before it's locked, requiring
      # verification later on
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetInstanceNodeGroups(self.op.instance_uuid, primary_only=True)

    elif level == locking.LEVEL_NODE:
      # If an allocator is used, then we lock all the nodes in the current
      # instance group, as we don't know yet which ones will be selected;
      # if we replace the nodes without using an allocator, locks are
      # already declared in ExpandNames; otherwise, we need to lock all the
      # instance nodes for disk re-creation
      if self.op.iallocator:
        assert not self.op.nodes
        assert not self.needed_locks[locking.LEVEL_NODE]
        assert len(self.owned_locks(locking.LEVEL_NODEGROUP)) == 1

        # Lock member nodes of the group of the primary node
        for group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP):
          self.needed_locks[locking.LEVEL_NODE].extend(
            self.cfg.GetNodeGroup(group_uuid).members)

        assert locking.NAL in self.owned_locks(locking.LEVEL_NODE_ALLOC)
      elif not self.op.nodes:
        self._LockInstancesNodes(primary_only=False)
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    return BuildInstanceHookEnvByObject(self, self.instance)

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    if self.op.node_uuids:
      if len(self.op.node_uuids) != len(instance.all_nodes):
        raise errors.OpPrereqError("Instance %s currently has %d nodes, but"
                                   " %d replacement nodes were specified" %
                                   (instance.name, len(instance.all_nodes),
                                    len(self.op.node_uuids)),
                                   errors.ECODE_INVAL)
      assert instance.disk_template != constants.DT_DRBD8 or \
             len(self.op.node_uuids) == 2
      assert instance.disk_template != constants.DT_PLAIN or \
             len(self.op.node_uuids) == 1
      primary_node = self.op.node_uuids[0]
    else:
      primary_node = instance.primary_node
    if not self.op.iallocator:
      CheckNodeOnline(self, primary_node)

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name, errors.ECODE_INVAL)

    # Verify if node group locks are still correct
    owned_groups = self.owned_locks(locking.LEVEL_NODEGROUP)
    if owned_groups:
      # Node group locks are acquired only for the primary node (and only
      # when the allocator is used)
      CheckInstanceNodeGroups(self.cfg, instance.uuid, owned_groups,
                              primary_only=True)

    # if we replace nodes *and* the old primary is offline, we don't
    # check the instance state
    old_pnode = self.cfg.GetNodeInfo(instance.primary_node)
    if not ((self.op.iallocator or self.op.node_uuids) and old_pnode.offline):
      CheckInstanceState(self, instance, INSTANCE_NOT_RUNNING,
                         msg="cannot recreate disks")

    if self.op.disks:
      self.disks = dict(self.op.disks)
    else:
      self.disks = dict((idx, {}) for idx in range(len(instance.disks)))

    maxidx = max(self.disks.keys())
    if maxidx >= len(instance.disks):
      raise errors.OpPrereqError("Invalid disk index '%s'" % maxidx,
                                 errors.ECODE_INVAL)

    if ((self.op.node_uuids or self.op.iallocator) and
         sorted(self.disks.keys()) != range(len(instance.disks))):
      raise errors.OpPrereqError("Can't recreate disks partially and"
                                 " change the nodes at the same time",
                                 errors.ECODE_INVAL)

    self.instance = instance

    if self.op.iallocator:
      self._RunAllocator()
      # Release unneeded node and node resource locks
      ReleaseLocks(self, locking.LEVEL_NODE, keep=self.op.node_uuids)
      ReleaseLocks(self, locking.LEVEL_NODE_RES, keep=self.op.node_uuids)
      ReleaseLocks(self, locking.LEVEL_NODE_ALLOC)

    assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

    if self.op.node_uuids:
      node_uuids = self.op.node_uuids
    else:
      node_uuids = instance.all_nodes
    excl_stor = compat.any(
      rpc.GetExclusiveStorageForNodes(self.cfg, node_uuids).values()
      )
    for new_params in self.disks.values():
      CheckSpindlesExclusiveStorage(new_params, excl_stor, False)

  def Exec(self, feedback_fn):
    """Recreate the disks.

    """
    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    to_skip = []
    mods = [] # keeps track of needed changes

    for idx, disk in enumerate(self.instance.disks):
      try:
        changes = self.disks[idx]
      except KeyError:
        # Disk should not be recreated
        to_skip.append(idx)
        continue

      # update secondaries for disks, if needed
      if self.op.node_uuids and disk.dev_type == constants.DT_DRBD8:
        # need to update the nodes and minors
        assert len(self.op.node_uuids) == 2
        assert len(disk.logical_id) == 6 # otherwise disk internals
                                         # have changed
        (_, _, old_port, _, _, old_secret) = disk.logical_id
        new_minors = self.cfg.AllocateDRBDMinor(self.op.node_uuids,
                                                self.instance.uuid)
        new_id = (self.op.node_uuids[0], self.op.node_uuids[1], old_port,
                  new_minors[0], new_minors[1], old_secret)
        assert len(disk.logical_id) == len(new_id)
      else:
        new_id = None

      mods.append((idx, new_id, changes))

    # now that we have passed all asserts above, we can apply the mods
    # in a single run (to avoid partial changes)
    for idx, new_id, changes in mods:
      disk = self.instance.disks[idx]
      if new_id is not None:
        assert disk.dev_type == constants.DT_DRBD8
        disk.logical_id = new_id
      if changes:
        disk.Update(size=changes.get(constants.IDISK_SIZE, None),
                    mode=changes.get(constants.IDISK_MODE, None),
                    spindles=changes.get(constants.IDISK_SPINDLES, None))

    # change primary node, if needed
    if self.op.node_uuids:
      self.instance.primary_node = self.op.node_uuids[0]
      self.LogWarning("Changing the instance's nodes, you will have to"
                      " remove any disks left on the older nodes manually")

    if self.op.node_uuids:
      self.cfg.Update(self.instance, feedback_fn)

    # All touched nodes must be locked
    mylocks = self.owned_locks(locking.LEVEL_NODE)
    assert mylocks.issuperset(frozenset(self.instance.all_nodes))
    new_disks = CreateDisks(self, self.instance, to_skip=to_skip)

    # TODO: Release node locks before wiping, or explain why it's not possible
    if self.cfg.GetClusterInfo().prealloc_wipe_disks:
      wipedisks = [(idx, disk, 0)
                   for (idx, disk) in enumerate(self.instance.disks)
                   if idx not in to_skip]
      WipeOrCleanupDisks(self, self.instance, disks=wipedisks,
                         cleanup=new_disks)


def _PerformNodeInfoCall(lu, node_uuids, vg):
  """Prepares the input and performs a node info call.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type node_uuids: list of string
  @param node_uuids: list of node UUIDs to perform the call for
  @type vg: string
  @param vg: the volume group's name

  """
  lvm_storage_units = [(constants.ST_LVM_VG, vg)]
  storage_units = rpc.PrepareStorageUnitsForNodes(lu.cfg, lvm_storage_units,
                                                  node_uuids)
  hvname = lu.cfg.GetHypervisorType()
  hvparams = lu.cfg.GetClusterInfo().hvparams
  nodeinfo = lu.rpc.call_node_info(node_uuids, storage_units,
                                   [(hvname, hvparams[hvname])])
  return nodeinfo


def _CheckVgCapacityForNode(node_name, node_info, vg, requested):
  """Checks the vg capacity for a given node.

  @type node_info: tuple (_, list of dicts, _)
  @param node_info: the result of the node info call for one node
  @type node_name: string
  @param node_name: the name of the node
  @type vg: string
  @param vg: volume group name
  @type requested: int
  @param requested: the amount of disk in MiB to check for
  @raise errors.OpPrereqError: if the node doesn't have enough disk,
      or we cannot check the node

  """
  (_, space_info, _) = node_info
  lvm_vg_info = utils.storage.LookupSpaceInfoByStorageType(
      space_info, constants.ST_LVM_VG)
  if not lvm_vg_info:
    raise errors.OpPrereqError("Can't retrieve storage information for LVM")
  vg_free = lvm_vg_info.get("storage_free", None)
  if not isinstance(vg_free, int):
    raise errors.OpPrereqError("Can't compute free disk space on node"
                               " %s for vg %s, result was '%s'" %
                               (node_name, vg, vg_free), errors.ECODE_ENVIRON)
  if requested > vg_free:
    raise errors.OpPrereqError("Not enough disk space on target node %s"
                               " vg %s: required %d MiB, available %d MiB" %
                               (node_name, vg, requested, vg_free),
                               errors.ECODE_NORES)


def _CheckNodesFreeDiskOnVG(lu, node_uuids, vg, requested):
  """Checks if nodes have enough free disk space in the specified VG.

  This function checks if all given nodes have the needed amount of
  free disk. In case any node has less disk or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type node_uuids: C{list}
  @param node_uuids: the list of node UUIDs to check
  @type vg: C{str}
  @param vg: the volume group to check
  @type requested: C{int}
  @param requested: the amount of disk in MiB to check for
  @raise errors.OpPrereqError: if the node doesn't have enough disk,
      or we cannot check the node

  """
  nodeinfo = _PerformNodeInfoCall(lu, node_uuids, vg)
  for node_uuid in node_uuids:
    node_name = lu.cfg.GetNodeName(node_uuid)
    info = nodeinfo[node_uuid]
    info.Raise("Cannot get current information from node %s" % node_name,
               prereq=True, ecode=errors.ECODE_ENVIRON)
    _CheckVgCapacityForNode(node_name, info.payload, vg, requested)


def CheckNodesFreeDiskPerVG(lu, node_uuids, req_sizes):
  """Checks if nodes have enough free disk space in all the VGs.

  This function checks if all given nodes have the needed amount of
  free disk. In case any node has less disk or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type node_uuids: C{list}
  @param node_uuids: the list of node UUIDs to check
  @type req_sizes: C{dict}
  @param req_sizes: the hash of vg and corresponding amount of disk in
      MiB to check for
  @raise errors.OpPrereqError: if the node doesn't have enough disk,
      or we cannot check the node

  """
  for vg, req_size in req_sizes.items():
    _CheckNodesFreeDiskOnVG(lu, node_uuids, vg, req_size)


def _DiskSizeInBytesToMebibytes(lu, size):
  """Converts a disk size in bytes to mebibytes.

  Warns and rounds up if the size isn't an even multiple of 1 MiB.

  """
  (mib, remainder) = divmod(size, 1024 * 1024)

  if remainder != 0:
    lu.LogWarning("Disk size is not an even multiple of 1 MiB; rounding up"
                  " to not overwrite existing data (%s bytes will not be"
                  " wiped)", (1024 * 1024) - remainder)
    mib += 1

  return mib


def _CalcEta(time_taken, written, total_size):
  """Calculates the ETA based on size written and total size.

  @param time_taken: The time taken so far
  @param written: amount written so far
  @param total_size: The total size of data to be written
  @return: The remaining time in seconds

  """
  avg_time = time_taken / float(written)
  return (total_size - written) * avg_time


def WipeDisks(lu, instance, disks=None):
  """Wipes instance disks.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should create
  @type disks: None or list of tuple of (number, L{objects.Disk}, number)
  @param disks: Disk details; tuple contains disk index, disk object and the
    start offset

  """
  node_uuid = instance.primary_node
  node_name = lu.cfg.GetNodeName(node_uuid)

  if disks is None:
    disks = [(idx, disk, 0)
             for (idx, disk) in enumerate(instance.disks)]

  logging.info("Pausing synchronization of disks of instance '%s'",
               instance.name)
  result = lu.rpc.call_blockdev_pause_resume_sync(node_uuid,
                                                  (map(compat.snd, disks),
                                                   instance),
                                                  True)
  result.Raise("Failed to pause disk synchronization on node '%s'" % node_name)

  for idx, success in enumerate(result.payload):
    if not success:
      logging.warn("Pausing synchronization of disk %s of instance '%s'"
                   " failed", idx, instance.name)

  try:
    for (idx, device, offset) in disks:
      # The wipe size is MIN_WIPE_CHUNK_PERCENT % of the instance disk but
      # MAX_WIPE_CHUNK at max. Truncating to integer to avoid rounding errors.
      wipe_chunk_size = \
        int(min(constants.MAX_WIPE_CHUNK,
                device.size / 100.0 * constants.MIN_WIPE_CHUNK_PERCENT))

      size = device.size
      last_output = 0
      start_time = time.time()

      if offset == 0:
        info_text = ""
      else:
        info_text = (" (from %s to %s)" %
                     (utils.FormatUnit(offset, "h"),
                      utils.FormatUnit(size, "h")))

      lu.LogInfo("* Wiping disk %s%s", idx, info_text)

      logging.info("Wiping disk %d for instance %s on node %s using"
                   " chunk size %s", idx, instance.name, node_name,
                   wipe_chunk_size)

      while offset < size:
        wipe_size = min(wipe_chunk_size, size - offset)

        logging.debug("Wiping disk %d, offset %s, chunk %s",
                      idx, offset, wipe_size)

        result = lu.rpc.call_blockdev_wipe(node_uuid, (device, instance),
                                           offset, wipe_size)
        result.Raise("Could not wipe disk %d at offset %d for size %d" %
                     (idx, offset, wipe_size))

        now = time.time()
        offset += wipe_size
        if now - last_output >= 60:
          eta = _CalcEta(now - start_time, offset, size)
          lu.LogInfo(" - done: %.1f%% ETA: %s",
                     offset / float(size) * 100, utils.FormatSeconds(eta))
          last_output = now
  finally:
    logging.info("Resuming synchronization of disks for instance '%s'",
                 instance.name)

    result = lu.rpc.call_blockdev_pause_resume_sync(node_uuid,
                                                    (map(compat.snd, disks),
                                                     instance),
                                                    False)

    if result.fail_msg:
      lu.LogWarning("Failed to resume disk synchronization on node '%s': %s",
                    node_name, result.fail_msg)
    else:
      for idx, success in enumerate(result.payload):
        if not success:
          lu.LogWarning("Resuming synchronization of disk %s of instance '%s'"
                        " failed", idx, instance.name)


def WipeOrCleanupDisks(lu, instance, disks=None, cleanup=None):
  """Wrapper for L{WipeDisks} that handles errors.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should wipe
  @param disks: see L{WipeDisks}
  @param cleanup: the result returned by L{CreateDisks}, used for cleanup in
      case of error
  @raise errors.OpPrereqError: in case of failure

  """
  try:
    WipeDisks(lu, instance, disks=disks)
  except errors.OpExecError:
    logging.warning("Wiping disks for instance '%s' failed",
                    instance.name)
    _UndoCreateDisks(lu, cleanup, instance)
    raise


def ExpandCheckDisks(instance, disks):
  """Return the instance disks selected by the disks list

  @type disks: list of L{objects.Disk} or None
  @param disks: selected disks
  @rtype: list of L{objects.Disk}
  @return: selected instance disks to act on

  """
  if disks is None:
    return instance.disks
  else:
    if not set(disks).issubset(instance.disks):
      raise errors.ProgrammerError("Can only act on disks belonging to the"
                                   " target instance: expected a subset of %r,"
                                   " got %r" % (instance.disks, disks))
    return disks


def WaitForSync(lu, instance, disks=None, oneshot=False):
  """Sleep and poll for an instance's disk to sync.

  """
  if not instance.disks or disks is not None and not disks:
    return True

  disks = ExpandCheckDisks(instance, disks)

  if not oneshot:
    lu.LogInfo("Waiting for instance %s to sync disks", instance.name)

  node_uuid = instance.primary_node
  node_name = lu.cfg.GetNodeName(node_uuid)

  # TODO: Convert to utils.Retry

  retries = 0
  degr_retries = 10 # in seconds, as we sleep 1 second each time
  while True:
    max_time = 0
    done = True
    cumul_degraded = False
    rstats = lu.rpc.call_blockdev_getmirrorstatus(node_uuid, (disks, instance))
    msg = rstats.fail_msg
    if msg:
      lu.LogWarning("Can't get any data from node %s: %s", node_name, msg)
      retries += 1
      if retries >= 10:
        raise errors.RemoteError("Can't contact node %s for mirror data,"
                                 " aborting." % node_name)
      time.sleep(6)
      continue
    rstats = rstats.payload
    retries = 0
    for i, mstat in enumerate(rstats):
      if mstat is None:
        lu.LogWarning("Can't compute data for node %s/%s",
                      node_name, disks[i].iv_name)
        continue

      cumul_degraded = (cumul_degraded or
                        (mstat.is_degraded and mstat.sync_percent is None))
      if mstat.sync_percent is not None:
        done = False
        if mstat.estimated_time is not None:
          rem_time = ("%s remaining (estimated)" %
                      utils.FormatSeconds(mstat.estimated_time))
          max_time = mstat.estimated_time
        else:
          rem_time = "no time estimate"
        lu.LogInfo("- device %s: %5.2f%% done, %s",
                   disks[i].iv_name, mstat.sync_percent, rem_time)

    # if we're done but degraded, let's do a few small retries, to
    # make sure we see a stable and not transient situation; therefore
    # we force restart of the loop
    if (done or oneshot) and cumul_degraded and degr_retries > 0:
      logging.info("Degraded disks found, %d retries left", degr_retries)
      degr_retries -= 1
      time.sleep(1)
      continue

    if done or oneshot:
      break

    time.sleep(min(60, max_time))

  if done:
    lu.LogInfo("Instance %s's disks are in sync", instance.name)

  return not cumul_degraded


def ShutdownInstanceDisks(lu, instance, disks=None, ignore_primary=False):
  """Shutdown block devices of an instance.

  This does the shutdown on all nodes of the instance.

  If the ignore_primary is false, errors on the primary node are
  ignored.

  """
  all_result = True

  if disks is None:
    # only mark instance disks as inactive if all disks are affected
    lu.cfg.MarkInstanceDisksInactive(instance.uuid)
  disks = ExpandCheckDisks(instance, disks)

  for disk in disks:
    for node_uuid, top_disk in disk.ComputeNodeTree(instance.primary_node):
      result = lu.rpc.call_blockdev_shutdown(node_uuid, (top_disk, instance))
      msg = result.fail_msg
      if msg:
        lu.LogWarning("Could not shutdown block device %s on node %s: %s",
                      disk.iv_name, lu.cfg.GetNodeName(node_uuid), msg)
        if ((node_uuid == instance.primary_node and not ignore_primary) or
            (node_uuid != instance.primary_node and not result.offline)):
          all_result = False
  return all_result


def _SafeShutdownInstanceDisks(lu, instance, disks=None):
  """Shutdown block devices of an instance.

  This function checks if an instance is running, before calling
  _ShutdownInstanceDisks.

  """
  CheckInstanceState(lu, instance, INSTANCE_DOWN, msg="cannot shutdown disks")
  ShutdownInstanceDisks(lu, instance, disks=disks)


def AssembleInstanceDisks(lu, instance, disks=None, ignore_secondaries=False,
                          ignore_size=False):
  """Prepare the block devices for an instance.

  This sets up the block devices on all nodes.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance for whose disks we assemble
  @type disks: list of L{objects.Disk} or None
  @param disks: which disks to assemble (or all, if None)
  @type ignore_secondaries: boolean
  @param ignore_secondaries: if true, errors on secondary nodes
      won't result in an error return from the function
  @type ignore_size: boolean
  @param ignore_size: if true, the current known size of the disk
      will not be used during the disk activation, useful for cases
      when the size is wrong
  @return: False if the operation failed, otherwise a list of
      (host, instance_visible_name, node_visible_name)
      with the mapping from node devices to instance devices

  """
  device_info = []
  disks_ok = True

  if disks is None:
    # only mark instance disks as active if all disks are affected
    lu.cfg.MarkInstanceDisksActive(instance.uuid)

  disks = ExpandCheckDisks(instance, disks)

  # With the two passes mechanism we try to reduce the window of
  # opportunity for the race condition of switching DRBD to primary
  # before handshaking occured, but we do not eliminate it

  # The proper fix would be to wait (with some limits) until the
  # connection has been made and drbd transitions from WFConnection
  # into any other network-connected state (Connected, SyncTarget,
  # SyncSource, etc.)

  # 1st pass, assemble on all nodes in secondary mode
  for idx, inst_disk in enumerate(disks):
    for node_uuid, node_disk in inst_disk.ComputeNodeTree(
                                  instance.primary_node):
      if ignore_size:
        node_disk = node_disk.Copy()
        node_disk.UnsetSize()
      result = lu.rpc.call_blockdev_assemble(node_uuid, (node_disk, instance),
                                             instance.name, False, idx)
      msg = result.fail_msg
      if msg:
        is_offline_secondary = (node_uuid in instance.secondary_nodes and
                                result.offline)
        lu.LogWarning("Could not prepare block device %s on node %s"
                      " (is_primary=False, pass=1): %s",
                      inst_disk.iv_name, lu.cfg.GetNodeName(node_uuid), msg)
        if not (ignore_secondaries or is_offline_secondary):
          disks_ok = False

  # FIXME: race condition on drbd migration to primary

  # 2nd pass, do only the primary node
  for idx, inst_disk in enumerate(disks):
    dev_path = None

    for node_uuid, node_disk in inst_disk.ComputeNodeTree(
                                  instance.primary_node):
      if node_uuid != instance.primary_node:
        continue
      if ignore_size:
        node_disk = node_disk.Copy()
        node_disk.UnsetSize()
      result = lu.rpc.call_blockdev_assemble(node_uuid, (node_disk, instance),
                                             instance.name, True, idx)
      msg = result.fail_msg
      if msg:
        lu.LogWarning("Could not prepare block device %s on node %s"
                      " (is_primary=True, pass=2): %s",
                      inst_disk.iv_name, lu.cfg.GetNodeName(node_uuid), msg)
        disks_ok = False
      else:
        dev_path, _ = result.payload

    device_info.append((lu.cfg.GetNodeName(instance.primary_node),
                        inst_disk.iv_name, dev_path))

  if not disks_ok:
    lu.cfg.MarkInstanceDisksInactive(instance.uuid)

  return disks_ok, device_info


def StartInstanceDisks(lu, instance, force):
  """Start the disks of an instance.

  """
  disks_ok, _ = AssembleInstanceDisks(lu, instance,
                                      ignore_secondaries=force)
  if not disks_ok:
    ShutdownInstanceDisks(lu, instance)
    if force is not None and not force:
      lu.LogWarning("",
                    hint=("If the message above refers to a secondary node,"
                          " you can retry the operation using '--force'"))
    raise errors.OpExecError("Disk consistency error")


class LUInstanceGrowDisk(LogicalUnit):
  """Grow a disk of an instance.

  """
  HPATH = "disk-grow"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE
    self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    env = {
      "DISK": self.op.disk,
      "AMOUNT": self.op.amount,
      "ABSOLUTE": self.op.absolute,
      }
    env.update(BuildInstanceHookEnvByObject(self, self.instance))
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
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    node_uuids = list(self.instance.all_nodes)
    for node_uuid in node_uuids:
      CheckNodeOnline(self, node_uuid)
    self.node_es_flags = rpc.GetExclusiveStorageForNodes(self.cfg, node_uuids)

    if self.instance.disk_template not in constants.DTS_GROWABLE:
      raise errors.OpPrereqError("Instance's disk layout does not support"
                                 " growing", errors.ECODE_INVAL)

    self.disk = self.instance.FindDisk(self.op.disk)

    if self.op.absolute:
      self.target = self.op.amount
      self.delta = self.target - self.disk.size
      if self.delta < 0:
        raise errors.OpPrereqError("Requested size (%s) is smaller than "
                                   "current disk size (%s)" %
                                   (utils.FormatUnit(self.target, "h"),
                                    utils.FormatUnit(self.disk.size, "h")),
                                   errors.ECODE_STATE)
    else:
      self.delta = self.op.amount
      self.target = self.disk.size + self.delta
      if self.delta < 0:
        raise errors.OpPrereqError("Requested increment (%s) is negative" %
                                   utils.FormatUnit(self.delta, "h"),
                                   errors.ECODE_INVAL)

    self._CheckDiskSpace(node_uuids, self.disk.ComputeGrowth(self.delta))

  def _CheckDiskSpace(self, node_uuids, req_vgspace):
    template = self.instance.disk_template
    if (template not in (constants.DTS_NO_FREE_SPACE_CHECK) and
        not any(self.node_es_flags.values())):
      # TODO: check the free disk space for file, when that feature will be
      # supported
      # With exclusive storage we need to do something smarter than just looking
      # at free space, which, in the end, is basically a dry run. So we rely on
      # the dry run performed in Exec() instead.
      CheckNodesFreeDiskPerVG(self, node_uuids, req_vgspace)

  def Exec(self, feedback_fn):
    """Execute disk grow.

    """
    assert set([self.instance.name]) == self.owned_locks(locking.LEVEL_INSTANCE)
    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    wipe_disks = self.cfg.GetClusterInfo().prealloc_wipe_disks

    disks_ok, _ = AssembleInstanceDisks(self, self.instance, disks=[self.disk])
    if not disks_ok:
      raise errors.OpExecError("Cannot activate block device to grow")

    feedback_fn("Growing disk %s of instance '%s' by %s to %s" %
                (self.op.disk, self.instance.name,
                 utils.FormatUnit(self.delta, "h"),
                 utils.FormatUnit(self.target, "h")))

    # First run all grow ops in dry-run mode
    for node_uuid in self.instance.all_nodes:
      result = self.rpc.call_blockdev_grow(node_uuid,
                                           (self.disk, self.instance),
                                           self.delta, True, True,
                                           self.node_es_flags[node_uuid])
      result.Raise("Dry-run grow request failed to node %s" %
                   self.cfg.GetNodeName(node_uuid))

    if wipe_disks:
      # Get disk size from primary node for wiping
      result = self.rpc.call_blockdev_getdimensions(
                 self.instance.primary_node, [([self.disk], self.instance)])
      result.Raise("Failed to retrieve disk size from node '%s'" %
                   self.instance.primary_node)

      (disk_dimensions, ) = result.payload

      if disk_dimensions is None:
        raise errors.OpExecError("Failed to retrieve disk size from primary"
                                 " node '%s'" % self.instance.primary_node)
      (disk_size_in_bytes, _) = disk_dimensions

      old_disk_size = _DiskSizeInBytesToMebibytes(self, disk_size_in_bytes)

      assert old_disk_size >= self.disk.size, \
        ("Retrieved disk size too small (got %s, should be at least %s)" %
         (old_disk_size, self.disk.size))
    else:
      old_disk_size = None

    # We know that (as far as we can test) operations across different
    # nodes will succeed, time to run it for real on the backing storage
    for node_uuid in self.instance.all_nodes:
      result = self.rpc.call_blockdev_grow(node_uuid,
                                           (self.disk, self.instance),
                                           self.delta, False, True,
                                           self.node_es_flags[node_uuid])
      result.Raise("Grow request failed to node %s" %
                   self.cfg.GetNodeName(node_uuid))

    # And now execute it for logical storage, on the primary node
    node_uuid = self.instance.primary_node
    result = self.rpc.call_blockdev_grow(node_uuid, (self.disk, self.instance),
                                         self.delta, False, False,
                                         self.node_es_flags[node_uuid])
    result.Raise("Grow request failed to node %s" %
                 self.cfg.GetNodeName(node_uuid))

    self.disk.RecordGrow(self.delta)
    self.cfg.Update(self.instance, feedback_fn)

    # Changes have been recorded, release node lock
    ReleaseLocks(self, locking.LEVEL_NODE)

    # Downgrade lock while waiting for sync
    self.glm.downgrade(locking.LEVEL_INSTANCE)

    assert wipe_disks ^ (old_disk_size is None)

    if wipe_disks:
      assert self.instance.disks[self.op.disk] == self.disk

      # Wipe newly added disk space
      WipeDisks(self, self.instance,
                disks=[(self.op.disk, self.disk, old_disk_size)])

    if self.op.wait_for_sync:
      disk_abort = not WaitForSync(self, self.instance, disks=[self.disk])
      if disk_abort:
        self.LogWarning("Disk syncing has not returned a good status; check"
                        " the instance")
      if not self.instance.disks_active:
        _SafeShutdownInstanceDisks(self, self.instance, disks=[self.disk])
    elif not self.instance.disks_active:
      self.LogWarning("Not shutting down the disk even if the instance is"
                      " not supposed to be running because no wait for"
                      " sync mode was requested")

    assert self.owned_locks(locking.LEVEL_NODE_RES)
    assert set([self.instance.name]) == self.owned_locks(locking.LEVEL_INSTANCE)


class LUInstanceReplaceDisks(LogicalUnit):
  """Replace the disks of an instance.

  """
  HPATH = "mirrors-replace"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    if self.op.mode == constants.REPLACE_DISK_CHG:
      if self.op.remote_node is None and self.op.iallocator is None:
        raise errors.OpPrereqError("When changing the secondary either an"
                                   " iallocator script must be used or the"
                                   " new node given", errors.ECODE_INVAL)
      else:
        CheckIAllocatorOrNode(self, "iallocator", "remote_node")

    elif self.op.remote_node is not None or self.op.iallocator is not None:
      # Not replacing the secondary
      raise errors.OpPrereqError("The iallocator and new node options can"
                                 " only be used when changing the"
                                 " secondary node", errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    assert locking.LEVEL_NODE not in self.needed_locks
    assert locking.LEVEL_NODE_RES not in self.needed_locks
    assert locking.LEVEL_NODEGROUP not in self.needed_locks

    assert self.op.iallocator is None or self.op.remote_node is None, \
      "Conflicting options"

    if self.op.remote_node is not None:
      (self.op.remote_node_uuid, self.op.remote_node) = \
        ExpandNodeUuidAndName(self.cfg, self.op.remote_node_uuid,
                              self.op.remote_node)

      # Warning: do not remove the locking of the new secondary here
      # unless DRBD8Dev.AddChildren is changed to work in parallel;
      # currently it doesn't since parallel invocations of
      # FindUnusedMinor will conflict
      self.needed_locks[locking.LEVEL_NODE] = [self.op.remote_node_uuid]
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
    else:
      self.needed_locks[locking.LEVEL_NODE] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

      if self.op.iallocator is not None:
        # iallocator will select a new node in the same group
        self.needed_locks[locking.LEVEL_NODEGROUP] = []
        self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

    self.needed_locks[locking.LEVEL_NODE_RES] = []

    self.replacer = TLReplaceDisks(self, self.op.instance_uuid,
                                   self.op.instance_name, self.op.mode,
                                   self.op.iallocator, self.op.remote_node_uuid,
                                   self.op.disks, self.op.early_release,
                                   self.op.ignore_ipolicy)

    self.tasklets = [self.replacer]

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert self.op.remote_node_uuid is None
      assert self.op.iallocator is not None
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      self.share_locks[locking.LEVEL_NODEGROUP] = 1
      # Lock all groups used by instance optimistically; this requires going
      # via the node before it's locked, requiring verification later on
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetInstanceNodeGroups(self.op.instance_uuid)

    elif level == locking.LEVEL_NODE:
      if self.op.iallocator is not None:
        assert self.op.remote_node_uuid is None
        assert not self.needed_locks[locking.LEVEL_NODE]
        assert locking.NAL in self.owned_locks(locking.LEVEL_NODE_ALLOC)

        # Lock member nodes of all locked groups
        self.needed_locks[locking.LEVEL_NODE] = \
          [node_uuid
           for group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)
           for node_uuid in self.cfg.GetNodeGroup(group_uuid).members]
      else:
        assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

        self._LockInstancesNodes()

    elif level == locking.LEVEL_NODE_RES:
      # Reuse node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        self.needed_locks[locking.LEVEL_NODE]

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    instance = self.replacer.instance
    env = {
      "MODE": self.op.mode,
      "NEW_SECONDARY": self.op.remote_node,
      "OLD_SECONDARY": self.cfg.GetNodeName(instance.secondary_nodes[0]),
      }
    env.update(BuildInstanceHookEnvByObject(self, instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self.replacer.instance
    nl = [
      self.cfg.GetMasterNode(),
      instance.primary_node,
      ]
    if self.op.remote_node_uuid is not None:
      nl.append(self.op.remote_node_uuid)
    return nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    """
    assert (self.glm.is_owned(locking.LEVEL_NODEGROUP) or
            self.op.iallocator is None)

    # Verify if node group locks are still correct
    owned_groups = self.owned_locks(locking.LEVEL_NODEGROUP)
    if owned_groups:
      CheckInstanceNodeGroups(self.cfg, self.op.instance_uuid, owned_groups)

    return LogicalUnit.CheckPrereq(self)


class LUInstanceActivateDisks(NoHooksLU):
  """Bring up an instance's disks.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Activate the disks.

    """
    disks_ok, disks_info = \
              AssembleInstanceDisks(self, self.instance,
                                    ignore_size=self.op.ignore_size)
    if not disks_ok:
      raise errors.OpExecError("Cannot activate block devices")

    if self.op.wait_for_sync:
      if not WaitForSync(self, self.instance):
        self.cfg.MarkInstanceDisksInactive(self.instance.uuid)
        raise errors.OpExecError("Some disks of the instance are degraded!")

    return disks_info


class LUInstanceDeactivateDisks(NoHooksLU):
  """Shutdown an instance's disks.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

  def Exec(self, feedback_fn):
    """Deactivate the disks

    """
    if self.op.force:
      ShutdownInstanceDisks(self, self.instance)
    else:
      _SafeShutdownInstanceDisks(self, self.instance)


def _CheckDiskConsistencyInner(lu, instance, dev, node_uuid, on_primary,
                               ldisk=False):
  """Check that mirrors are not degraded.

  @attention: The device has to be annotated already.

  The ldisk parameter, if True, will change the test from the
  is_degraded attribute (which represents overall non-ok status for
  the device(s)) to the ldisk (representing the local storage status).

  """
  result = True

  if on_primary or dev.AssembleOnSecondary():
    rstats = lu.rpc.call_blockdev_find(node_uuid, (dev, instance))
    msg = rstats.fail_msg
    if msg:
      lu.LogWarning("Can't find disk on node %s: %s",
                    lu.cfg.GetNodeName(node_uuid), msg)
      result = False
    elif not rstats.payload:
      lu.LogWarning("Can't find disk on node %s", lu.cfg.GetNodeName(node_uuid))
      result = False
    else:
      if ldisk:
        result = result and rstats.payload.ldisk_status == constants.LDS_OKAY
      else:
        result = result and not rstats.payload.is_degraded

  if dev.children:
    for child in dev.children:
      result = result and _CheckDiskConsistencyInner(lu, instance, child,
                                                     node_uuid, on_primary)

  return result


def CheckDiskConsistency(lu, instance, dev, node_uuid, on_primary, ldisk=False):
  """Wrapper around L{_CheckDiskConsistencyInner}.

  """
  (disk,) = AnnotateDiskParams(instance, [dev], lu.cfg)
  return _CheckDiskConsistencyInner(lu, instance, disk, node_uuid, on_primary,
                                    ldisk=ldisk)


def _BlockdevFind(lu, node_uuid, dev, instance):
  """Wrapper around call_blockdev_find to annotate diskparams.

  @param lu: A reference to the lu object
  @param node_uuid: The node to call out
  @param dev: The device to find
  @param instance: The instance object the device belongs to
  @returns The result of the rpc call

  """
  (disk,) = AnnotateDiskParams(instance, [dev], lu.cfg)
  return lu.rpc.call_blockdev_find(node_uuid, (disk, instance))


def _GenerateUniqueNames(lu, exts):
  """Generate a suitable LV name.

  This will generate a logical volume name for the given instance.

  """
  results = []
  for val in exts:
    new_id = lu.cfg.GenerateUniqueID(lu.proc.GetECId())
    results.append("%s%s" % (new_id, val))
  return results


class TLReplaceDisks(Tasklet):
  """Replaces disks for an instance.

  Note: Locking is not within the scope of this class.

  """
  def __init__(self, lu, instance_uuid, instance_name, mode, iallocator_name,
               remote_node_uuid, disks, early_release, ignore_ipolicy):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_uuid = instance_uuid
    self.instance_name = instance_name
    self.mode = mode
    self.iallocator_name = iallocator_name
    self.remote_node_uuid = remote_node_uuid
    self.disks = disks
    self.early_release = early_release
    self.ignore_ipolicy = ignore_ipolicy

    # Runtime data
    self.instance = None
    self.new_node_uuid = None
    self.target_node_uuid = None
    self.other_node_uuid = None
    self.remote_node_info = None
    self.node_secondary_ip = None

  @staticmethod
  def _RunAllocator(lu, iallocator_name, instance_uuid,
                    relocate_from_node_uuids):
    """Compute a new secondary node using an IAllocator.

    """
    req = iallocator.IAReqRelocate(
          inst_uuid=instance_uuid,
          relocate_from_node_uuids=list(relocate_from_node_uuids))
    ial = iallocator.IAllocator(lu.cfg, lu.rpc, req)

    ial.Run(iallocator_name)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using iallocator '%s':"
                                 " %s" % (iallocator_name, ial.info),
                                 errors.ECODE_NORES)

    remote_node_name = ial.result[0]
    remote_node = lu.cfg.GetNodeInfoByName(remote_node_name)

    if remote_node is None:
      raise errors.OpPrereqError("Node %s not found in configuration" %
                                 remote_node_name, errors.ECODE_NOENT)

    lu.LogInfo("Selected new secondary for instance '%s': %s",
               instance_uuid, remote_node_name)

    return remote_node.uuid

  def _FindFaultyDisks(self, node_uuid):
    """Wrapper for L{FindFaultyInstanceDisks}.

    """
    return FindFaultyInstanceDisks(self.cfg, self.rpc, self.instance,
                                   node_uuid, True)

  def _CheckDisksActivated(self, instance):
    """Checks if the instance disks are activated.

    @param instance: The instance to check disks
    @return: True if they are activated, False otherwise

    """
    node_uuids = instance.all_nodes

    for idx, dev in enumerate(instance.disks):
      for node_uuid in node_uuids:
        self.lu.LogInfo("Checking disk/%d on %s", idx,
                        self.cfg.GetNodeName(node_uuid))

        result = _BlockdevFind(self, node_uuid, dev, instance)

        if result.offline:
          continue
        elif result.fail_msg or not result.payload:
          return False

    return True

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.instance_name

    if self.instance.disk_template != constants.DT_DRBD8:
      raise errors.OpPrereqError("Can only run replace disks for DRBD8-based"
                                 " instances", errors.ECODE_INVAL)

    if len(self.instance.secondary_nodes) != 1:
      raise errors.OpPrereqError("The instance has a strange layout,"
                                 " expected one secondary but found %d" %
                                 len(self.instance.secondary_nodes),
                                 errors.ECODE_FAULT)

    secondary_node_uuid = self.instance.secondary_nodes[0]

    if self.iallocator_name is None:
      remote_node_uuid = self.remote_node_uuid
    else:
      remote_node_uuid = self._RunAllocator(self.lu, self.iallocator_name,
                                            self.instance.uuid,
                                            self.instance.secondary_nodes)

    if remote_node_uuid is None:
      self.remote_node_info = None
    else:
      assert remote_node_uuid in self.lu.owned_locks(locking.LEVEL_NODE), \
             "Remote node '%s' is not locked" % remote_node_uuid

      self.remote_node_info = self.cfg.GetNodeInfo(remote_node_uuid)
      assert self.remote_node_info is not None, \
        "Cannot retrieve locked node %s" % remote_node_uuid

    if remote_node_uuid == self.instance.primary_node:
      raise errors.OpPrereqError("The specified node is the primary node of"
                                 " the instance", errors.ECODE_INVAL)

    if remote_node_uuid == secondary_node_uuid:
      raise errors.OpPrereqError("The specified node is already the"
                                 " secondary node of the instance",
                                 errors.ECODE_INVAL)

    if self.disks and self.mode in (constants.REPLACE_DISK_AUTO,
                                    constants.REPLACE_DISK_CHG):
      raise errors.OpPrereqError("Cannot specify disks to be replaced",
                                 errors.ECODE_INVAL)

    if self.mode == constants.REPLACE_DISK_AUTO:
      if not self._CheckDisksActivated(self.instance):
        raise errors.OpPrereqError("Please run activate-disks on instance %s"
                                   " first" % self.instance_name,
                                   errors.ECODE_STATE)
      faulty_primary = self._FindFaultyDisks(self.instance.primary_node)
      faulty_secondary = self._FindFaultyDisks(secondary_node_uuid)

      if faulty_primary and faulty_secondary:
        raise errors.OpPrereqError("Instance %s has faulty disks on more than"
                                   " one node and can not be repaired"
                                   " automatically" % self.instance_name,
                                   errors.ECODE_STATE)

      if faulty_primary:
        self.disks = faulty_primary
        self.target_node_uuid = self.instance.primary_node
        self.other_node_uuid = secondary_node_uuid
        check_nodes = [self.target_node_uuid, self.other_node_uuid]
      elif faulty_secondary:
        self.disks = faulty_secondary
        self.target_node_uuid = secondary_node_uuid
        self.other_node_uuid = self.instance.primary_node
        check_nodes = [self.target_node_uuid, self.other_node_uuid]
      else:
        self.disks = []
        check_nodes = []

    else:
      # Non-automatic modes
      if self.mode == constants.REPLACE_DISK_PRI:
        self.target_node_uuid = self.instance.primary_node
        self.other_node_uuid = secondary_node_uuid
        check_nodes = [self.target_node_uuid, self.other_node_uuid]

      elif self.mode == constants.REPLACE_DISK_SEC:
        self.target_node_uuid = secondary_node_uuid
        self.other_node_uuid = self.instance.primary_node
        check_nodes = [self.target_node_uuid, self.other_node_uuid]

      elif self.mode == constants.REPLACE_DISK_CHG:
        self.new_node_uuid = remote_node_uuid
        self.other_node_uuid = self.instance.primary_node
        self.target_node_uuid = secondary_node_uuid
        check_nodes = [self.new_node_uuid, self.other_node_uuid]

        CheckNodeNotDrained(self.lu, remote_node_uuid)
        CheckNodeVmCapable(self.lu, remote_node_uuid)

        old_node_info = self.cfg.GetNodeInfo(secondary_node_uuid)
        assert old_node_info is not None
        if old_node_info.offline and not self.early_release:
          # doesn't make sense to delay the release
          self.early_release = True
          self.lu.LogInfo("Old secondary %s is offline, automatically enabling"
                          " early-release mode", secondary_node_uuid)

      else:
        raise errors.ProgrammerError("Unhandled disk replace mode (%s)" %
                                     self.mode)

      # If not specified all disks should be replaced
      if not self.disks:
        self.disks = range(len(self.instance.disks))

    # TODO: This is ugly, but right now we can't distinguish between internal
    # submitted opcode and external one. We should fix that.
    if self.remote_node_info:
      # We change the node, lets verify it still meets instance policy
      new_group_info = self.cfg.GetNodeGroup(self.remote_node_info.group)
      cluster = self.cfg.GetClusterInfo()
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              new_group_info)
      CheckTargetNodeIPolicy(self, ipolicy, self.instance,
                             self.remote_node_info, self.cfg,
                             ignore=self.ignore_ipolicy)

    for node_uuid in check_nodes:
      CheckNodeOnline(self.lu, node_uuid)

    touched_nodes = frozenset(node_uuid for node_uuid in [self.new_node_uuid,
                                                          self.other_node_uuid,
                                                          self.target_node_uuid]
                              if node_uuid is not None)

    # Release unneeded node and node resource locks
    ReleaseLocks(self.lu, locking.LEVEL_NODE, keep=touched_nodes)
    ReleaseLocks(self.lu, locking.LEVEL_NODE_RES, keep=touched_nodes)
    ReleaseLocks(self.lu, locking.LEVEL_NODE_ALLOC)

    # Release any owned node group
    ReleaseLocks(self.lu, locking.LEVEL_NODEGROUP)

    # Check whether disks are valid
    for disk_idx in self.disks:
      self.instance.FindDisk(disk_idx)

    # Get secondary node IP addresses
    self.node_secondary_ip = dict((uuid, node.secondary_ip) for (uuid, node)
                                  in self.cfg.GetMultiNodeInfo(touched_nodes))

  def Exec(self, feedback_fn):
    """Execute disk replacement.

    This dispatches the disk replacement to the appropriate handler.

    """
    if __debug__:
      # Verify owned locks before starting operation
      owned_nodes = self.lu.owned_locks(locking.LEVEL_NODE)
      assert set(owned_nodes) == set(self.node_secondary_ip), \
          ("Incorrect node locks, owning %s, expected %s" %
           (owned_nodes, self.node_secondary_ip.keys()))
      assert (self.lu.owned_locks(locking.LEVEL_NODE) ==
              self.lu.owned_locks(locking.LEVEL_NODE_RES))
      assert not self.lu.glm.is_owned(locking.LEVEL_NODE_ALLOC)

      owned_instances = self.lu.owned_locks(locking.LEVEL_INSTANCE)
      assert list(owned_instances) == [self.instance_name], \
          "Instance '%s' not locked" % self.instance_name

      assert not self.lu.glm.is_owned(locking.LEVEL_NODEGROUP), \
          "Should not own any node group lock at this point"

    if not self.disks:
      feedback_fn("No disks need replacement for instance '%s'" %
                  self.instance.name)
      return

    feedback_fn("Replacing disk(s) %s for instance '%s'" %
                (utils.CommaJoin(self.disks), self.instance.name))
    feedback_fn("Current primary node: %s" %
                self.cfg.GetNodeName(self.instance.primary_node))
    feedback_fn("Current seconary node: %s" %
                utils.CommaJoin(self.cfg.GetNodeNames(
                                  self.instance.secondary_nodes)))

    activate_disks = not self.instance.disks_active

    # Activate the instance disks if we're replacing them on a down instance
    if activate_disks:
      StartInstanceDisks(self.lu, self.instance, True)

    try:
      # Should we replace the secondary node?
      if self.new_node_uuid is not None:
        fn = self._ExecDrbd8Secondary
      else:
        fn = self._ExecDrbd8DiskOnly

      result = fn(feedback_fn)
    finally:
      # Deactivate the instance disks if we're replacing them on a
      # down instance
      if activate_disks:
        _SafeShutdownInstanceDisks(self.lu, self.instance)

    assert not self.lu.owned_locks(locking.LEVEL_NODE)

    if __debug__:
      # Verify owned locks
      owned_nodes = self.lu.owned_locks(locking.LEVEL_NODE_RES)
      nodes = frozenset(self.node_secondary_ip)
      assert ((self.early_release and not owned_nodes) or
              (not self.early_release and not (set(owned_nodes) - nodes))), \
        ("Not owning the correct locks, early_release=%s, owned=%r,"
         " nodes=%r" % (self.early_release, owned_nodes, nodes))

    return result

  def _CheckVolumeGroup(self, node_uuids):
    self.lu.LogInfo("Checking volume groups")

    vgname = self.cfg.GetVGName()

    # Make sure volume group exists on all involved nodes
    results = self.rpc.call_vg_list(node_uuids)
    if not results:
      raise errors.OpExecError("Can't list volume groups on the nodes")

    for node_uuid in node_uuids:
      res = results[node_uuid]
      res.Raise("Error checking node %s" % self.cfg.GetNodeName(node_uuid))
      if vgname not in res.payload:
        raise errors.OpExecError("Volume group '%s' not found on node %s" %
                                 (vgname, self.cfg.GetNodeName(node_uuid)))

  def _CheckDisksExistence(self, node_uuids):
    # Check disk existence
    for idx, dev in enumerate(self.instance.disks):
      if idx not in self.disks:
        continue

      for node_uuid in node_uuids:
        self.lu.LogInfo("Checking disk/%d on %s", idx,
                        self.cfg.GetNodeName(node_uuid))

        result = _BlockdevFind(self, node_uuid, dev, self.instance)

        msg = result.fail_msg
        if msg or not result.payload:
          if not msg:
            msg = "disk not found"
          if not self._CheckDisksActivated(self.instance):
            extra_hint = ("\nDisks seem to be not properly activated. Try"
                          " running activate-disks on the instance before"
                          " using replace-disks.")
          else:
            extra_hint = ""
          raise errors.OpExecError("Can't find disk/%d on node %s: %s%s" %
                                   (idx, self.cfg.GetNodeName(node_uuid), msg,
                                    extra_hint))

  def _CheckDisksConsistency(self, node_uuid, on_primary, ldisk):
    for idx, dev in enumerate(self.instance.disks):
      if idx not in self.disks:
        continue

      self.lu.LogInfo("Checking disk/%d consistency on node %s" %
                      (idx, self.cfg.GetNodeName(node_uuid)))

      if not CheckDiskConsistency(self.lu, self.instance, dev, node_uuid,
                                  on_primary, ldisk=ldisk):
        raise errors.OpExecError("Node %s has degraded storage, unsafe to"
                                 " replace disks for instance %s" %
                                 (self.cfg.GetNodeName(node_uuid),
                                  self.instance.name))

  def _CreateNewStorage(self, node_uuid):
    """Create new storage on the primary or secondary node.

    This is only used for same-node replaces, not for changing the
    secondary node, hence we don't want to modify the existing disk.

    """
    iv_names = {}

    disks = AnnotateDiskParams(self.instance, self.instance.disks, self.cfg)
    for idx, dev in enumerate(disks):
      if idx not in self.disks:
        continue

      self.lu.LogInfo("Adding storage on %s for disk/%d",
                      self.cfg.GetNodeName(node_uuid), idx)

      lv_names = [".disk%d_%s" % (idx, suffix) for suffix in ["data", "meta"]]
      names = _GenerateUniqueNames(self.lu, lv_names)

      (data_disk, meta_disk) = dev.children
      vg_data = data_disk.logical_id[0]
      lv_data = objects.Disk(dev_type=constants.DT_PLAIN, size=dev.size,
                             logical_id=(vg_data, names[0]),
                             params=data_disk.params)
      vg_meta = meta_disk.logical_id[0]
      lv_meta = objects.Disk(dev_type=constants.DT_PLAIN,
                             size=constants.DRBD_META_SIZE,
                             logical_id=(vg_meta, names[1]),
                             params=meta_disk.params)

      new_lvs = [lv_data, lv_meta]
      old_lvs = [child.Copy() for child in dev.children]
      iv_names[dev.iv_name] = (dev, old_lvs, new_lvs)
      excl_stor = IsExclusiveStorageEnabledNodeUuid(self.lu.cfg, node_uuid)

      # we pass force_create=True to force the LVM creation
      for new_lv in new_lvs:
        try:
          _CreateBlockDevInner(self.lu, node_uuid, self.instance, new_lv, True,
                               GetInstanceInfoText(self.instance), False,
                               excl_stor)
        except errors.DeviceCreationError, e:
          raise errors.OpExecError("Can't create block device: %s" % e.message)

    return iv_names

  def _CheckDevices(self, node_uuid, iv_names):
    for name, (dev, _, _) in iv_names.iteritems():
      result = _BlockdevFind(self, node_uuid, dev, self.instance)

      msg = result.fail_msg
      if msg or not result.payload:
        if not msg:
          msg = "disk not found"
        raise errors.OpExecError("Can't find DRBD device %s: %s" %
                                 (name, msg))

      if result.payload.is_degraded:
        raise errors.OpExecError("DRBD device %s is degraded!" % name)

  def _RemoveOldStorage(self, node_uuid, iv_names):
    for name, (_, old_lvs, _) in iv_names.iteritems():
      self.lu.LogInfo("Remove logical volumes for %s", name)

      for lv in old_lvs:
        msg = self.rpc.call_blockdev_remove(node_uuid, (lv, self.instance)) \
                .fail_msg
        if msg:
          self.lu.LogWarning("Can't remove old LV: %s", msg,
                             hint="remove unused LVs manually")

  def _ExecDrbd8DiskOnly(self, feedback_fn): # pylint: disable=W0613
    """Replace a disk on the primary or secondary for DRBD 8.

    The algorithm for replace is quite complicated:

      1. for each disk to be replaced:

        1. create new LVs on the target node with unique names
        1. detach old LVs from the drbd device
        1. rename old LVs to name_replaced.<time_t>
        1. rename new LVs to old LVs
        1. attach the new LVs (with the old names now) to the drbd device

      1. wait for sync across all devices

      1. for each modified disk:

        1. remove old LVs (which have the name name_replaces.<time_t>)

    Failures are not very well handled.

    """
    steps_total = 6

    # Step: check device activation
    self.lu.LogStep(1, steps_total, "Check device existence")
    self._CheckDisksExistence([self.other_node_uuid, self.target_node_uuid])
    self._CheckVolumeGroup([self.target_node_uuid, self.other_node_uuid])

    # Step: check other node consistency
    self.lu.LogStep(2, steps_total, "Check peer consistency")
    self._CheckDisksConsistency(
      self.other_node_uuid, self.other_node_uuid == self.instance.primary_node,
      False)

    # Step: create new storage
    self.lu.LogStep(3, steps_total, "Allocate new storage")
    iv_names = self._CreateNewStorage(self.target_node_uuid)

    # Step: for each lv, detach+rename*2+attach
    self.lu.LogStep(4, steps_total, "Changing drbd configuration")
    for dev, old_lvs, new_lvs in iv_names.itervalues():
      self.lu.LogInfo("Detaching %s drbd from local storage", dev.iv_name)

      result = self.rpc.call_blockdev_removechildren(self.target_node_uuid,
                                                     (dev, self.instance),
                                                     (old_lvs, self.instance))
      result.Raise("Can't detach drbd from local storage on node"
                   " %s for device %s" %
                   (self.cfg.GetNodeName(self.target_node_uuid), dev.iv_name))
      #dev.children = []
      #cfg.Update(instance)

      # ok, we created the new LVs, so now we know we have the needed
      # storage; as such, we proceed on the target node to rename
      # old_lv to _old, and new_lv to old_lv; note that we rename LVs
      # using the assumption that logical_id == unique_id on that node

      # FIXME(iustin): use a better name for the replaced LVs
      temp_suffix = int(time.time())
      ren_fn = lambda d, suff: (d.logical_id[0],
                                d.logical_id[1] + "_replaced-%s" % suff)

      # Build the rename list based on what LVs exist on the node
      rename_old_to_new = []
      for to_ren in old_lvs:
        result = self.rpc.call_blockdev_find(self.target_node_uuid,
                                             (to_ren, self.instance))
        if not result.fail_msg and result.payload:
          # device exists
          rename_old_to_new.append((to_ren, ren_fn(to_ren, temp_suffix)))

      self.lu.LogInfo("Renaming the old LVs on the target node")
      result = self.rpc.call_blockdev_rename(self.target_node_uuid,
                                             rename_old_to_new)
      result.Raise("Can't rename old LVs on node %s" %
                   self.cfg.GetNodeName(self.target_node_uuid))

      # Now we rename the new LVs to the old LVs
      self.lu.LogInfo("Renaming the new LVs on the target node")
      rename_new_to_old = [(new, old.logical_id)
                           for old, new in zip(old_lvs, new_lvs)]
      result = self.rpc.call_blockdev_rename(self.target_node_uuid,
                                             rename_new_to_old)
      result.Raise("Can't rename new LVs on node %s" %
                   self.cfg.GetNodeName(self.target_node_uuid))

      # Intermediate steps of in memory modifications
      for old, new in zip(old_lvs, new_lvs):
        new.logical_id = old.logical_id

      # We need to modify old_lvs so that removal later removes the
      # right LVs, not the newly added ones; note that old_lvs is a
      # copy here
      for disk in old_lvs:
        disk.logical_id = ren_fn(disk, temp_suffix)

      # Now that the new lvs have the old name, we can add them to the device
      self.lu.LogInfo("Adding new mirror component on %s",
                      self.cfg.GetNodeName(self.target_node_uuid))
      result = self.rpc.call_blockdev_addchildren(self.target_node_uuid,
                                                  (dev, self.instance),
                                                  (new_lvs, self.instance))
      msg = result.fail_msg
      if msg:
        for new_lv in new_lvs:
          msg2 = self.rpc.call_blockdev_remove(self.target_node_uuid,
                                               (new_lv, self.instance)).fail_msg
          if msg2:
            self.lu.LogWarning("Can't rollback device %s: %s", dev, msg2,
                               hint=("cleanup manually the unused logical"
                                     "volumes"))
        raise errors.OpExecError("Can't add local storage to drbd: %s" % msg)

    cstep = itertools.count(5)

    if self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node_uuid, iv_names)
      # TODO: Check if releasing locks early still makes sense
      ReleaseLocks(self.lu, locking.LEVEL_NODE_RES)
    else:
      # Release all resource locks except those used by the instance
      ReleaseLocks(self.lu, locking.LEVEL_NODE_RES,
                   keep=self.node_secondary_ip.keys())

    # Release all node locks while waiting for sync
    ReleaseLocks(self.lu, locking.LEVEL_NODE)

    # TODO: Can the instance lock be downgraded here? Take the optional disk
    # shutdown in the caller into consideration.

    # Wait for sync
    # This can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its return value
    self.lu.LogStep(cstep.next(), steps_total, "Sync devices")
    WaitForSync(self.lu, self.instance)

    # Check all devices manually
    self._CheckDevices(self.instance.primary_node, iv_names)

    # Step: remove old storage
    if not self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node_uuid, iv_names)

  def _ExecDrbd8Secondary(self, feedback_fn):
    """Replace the secondary node for DRBD 8.

    The algorithm for replace is quite complicated:
      - for all disks of the instance:
        - create new LVs on the new node with same names
        - shutdown the drbd device on the old secondary
        - disconnect the drbd network on the primary
        - create the drbd device on the new secondary
        - network attach the drbd on the primary, using an artifice:
          the drbd code for Attach() will connect to the network if it
          finds a device which is connected to the good local disks but
          not network enabled
      - wait for sync across all devices
      - remove all disks from the old secondary

    Failures are not very well handled.

    """
    steps_total = 6

    pnode = self.instance.primary_node

    # Step: check device activation
    self.lu.LogStep(1, steps_total, "Check device existence")
    self._CheckDisksExistence([self.instance.primary_node])
    self._CheckVolumeGroup([self.instance.primary_node])

    # Step: check other node consistency
    self.lu.LogStep(2, steps_total, "Check peer consistency")
    self._CheckDisksConsistency(self.instance.primary_node, True, True)

    # Step: create new storage
    self.lu.LogStep(3, steps_total, "Allocate new storage")
    disks = AnnotateDiskParams(self.instance, self.instance.disks, self.cfg)
    excl_stor = IsExclusiveStorageEnabledNodeUuid(self.lu.cfg,
                                                  self.new_node_uuid)
    for idx, dev in enumerate(disks):
      self.lu.LogInfo("Adding new local storage on %s for disk/%d" %
                      (self.cfg.GetNodeName(self.new_node_uuid), idx))
      # we pass force_create=True to force LVM creation
      for new_lv in dev.children:
        try:
          _CreateBlockDevInner(self.lu, self.new_node_uuid, self.instance,
                               new_lv, True, GetInstanceInfoText(self.instance),
                               False, excl_stor)
        except errors.DeviceCreationError, e:
          raise errors.OpExecError("Can't create block device: %s" % e.message)

    # Step 4: dbrd minors and drbd setups changes
    # after this, we must manually remove the drbd minors on both the
    # error and the success paths
    self.lu.LogStep(4, steps_total, "Changing drbd configuration")
    minors = self.cfg.AllocateDRBDMinor([self.new_node_uuid
                                         for _ in self.instance.disks],
                                        self.instance.uuid)
    logging.debug("Allocated minors %r", minors)

    iv_names = {}
    for idx, (dev, new_minor) in enumerate(zip(self.instance.disks, minors)):
      self.lu.LogInfo("activating a new drbd on %s for disk/%d" %
                      (self.cfg.GetNodeName(self.new_node_uuid), idx))
      # create new devices on new_node; note that we create two IDs:
      # one without port, so the drbd will be activated without
      # networking information on the new node at this stage, and one
      # with network, for the latter activation in step 4
      (o_node1, o_node2, o_port, o_minor1, o_minor2, o_secret) = dev.logical_id
      if self.instance.primary_node == o_node1:
        p_minor = o_minor1
      else:
        assert self.instance.primary_node == o_node2, "Three-node instance?"
        p_minor = o_minor2

      new_alone_id = (self.instance.primary_node, self.new_node_uuid, None,
                      p_minor, new_minor, o_secret)
      new_net_id = (self.instance.primary_node, self.new_node_uuid, o_port,
                    p_minor, new_minor, o_secret)

      iv_names[idx] = (dev, dev.children, new_net_id)
      logging.debug("Allocated new_minor: %s, new_logical_id: %s", new_minor,
                    new_net_id)
      new_drbd = objects.Disk(dev_type=constants.DT_DRBD8,
                              logical_id=new_alone_id,
                              children=dev.children,
                              size=dev.size,
                              params={})
      (anno_new_drbd,) = AnnotateDiskParams(self.instance, [new_drbd],
                                            self.cfg)
      try:
        CreateSingleBlockDev(self.lu, self.new_node_uuid, self.instance,
                             anno_new_drbd,
                             GetInstanceInfoText(self.instance), False,
                             excl_stor)
      except errors.GenericError:
        self.cfg.ReleaseDRBDMinors(self.instance.uuid)
        raise

    # We have new devices, shutdown the drbd on the old secondary
    for idx, dev in enumerate(self.instance.disks):
      self.lu.LogInfo("Shutting down drbd for disk/%d on old node", idx)
      msg = self.rpc.call_blockdev_shutdown(self.target_node_uuid,
                                            (dev, self.instance)).fail_msg
      if msg:
        self.lu.LogWarning("Failed to shutdown drbd for disk/%d on old"
                           "node: %s" % (idx, msg),
                           hint=("Please cleanup this device manually as"
                                 " soon as possible"))

    self.lu.LogInfo("Detaching primary drbds from the network (=> standalone)")
    result = self.rpc.call_drbd_disconnect_net(
               [pnode], (self.instance.disks, self.instance))[pnode]

    msg = result.fail_msg
    if msg:
      # detaches didn't succeed (unlikely)
      self.cfg.ReleaseDRBDMinors(self.instance.uuid)
      raise errors.OpExecError("Can't detach the disks from the network on"
                               " old node: %s" % (msg,))

    # if we managed to detach at least one, we update all the disks of
    # the instance to point to the new secondary
    self.lu.LogInfo("Updating instance configuration")
    for dev, _, new_logical_id in iv_names.itervalues():
      dev.logical_id = new_logical_id

    self.cfg.Update(self.instance, feedback_fn)

    # Release all node locks (the configuration has been updated)
    ReleaseLocks(self.lu, locking.LEVEL_NODE)

    # and now perform the drbd attach
    self.lu.LogInfo("Attaching primary drbds to new secondary"
                    " (standalone => connected)")
    result = self.rpc.call_drbd_attach_net([self.instance.primary_node,
                                            self.new_node_uuid],
                                           (self.instance.disks, self.instance),
                                           self.instance.name,
                                           False)
    for to_node, to_result in result.items():
      msg = to_result.fail_msg
      if msg:
        self.lu.LogWarning("Can't attach drbd disks on node %s: %s",
                           self.cfg.GetNodeName(to_node), msg,
                           hint=("please do a gnt-instance info to see the"
                                 " status of disks"))

    cstep = itertools.count(5)

    if self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node_uuid, iv_names)
      # TODO: Check if releasing locks early still makes sense
      ReleaseLocks(self.lu, locking.LEVEL_NODE_RES)
    else:
      # Release all resource locks except those used by the instance
      ReleaseLocks(self.lu, locking.LEVEL_NODE_RES,
                   keep=self.node_secondary_ip.keys())

    # TODO: Can the instance lock be downgraded here? Take the optional disk
    # shutdown in the caller into consideration.

    # Wait for sync
    # This can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its return value
    self.lu.LogStep(cstep.next(), steps_total, "Sync devices")
    WaitForSync(self.lu, self.instance)

    # Check all devices manually
    self._CheckDevices(self.instance.primary_node, iv_names)

    # Step: remove old storage
    if not self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node_uuid, iv_names)
