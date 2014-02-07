#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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


"""Ganeti node daemon"""

# pylint: disable=C0103,W0142

# C0103: Functions in this module need to have a given name structure,
# and the name of the daemon doesn't match

# W0142: Used * or ** magic, since we do use it extensively in this
# module

import os
import sys
import logging
import signal
import codecs

from optparse import OptionParser

from ganeti import backend
from ganeti import constants
from ganeti import objects
from ganeti import errors
from ganeti import jstore
from ganeti import daemon
from ganeti import http
from ganeti import utils
from ganeti.storage import container
from ganeti import serializer
from ganeti import netutils
from ganeti import pathutils
from ganeti import ssconf

import ganeti.http.server # pylint: disable=W0611


queue_lock = None


def _extendReasonTrail(trail, source, reason=""):
  """Extend the reason trail with noded information

  The trail is extended by appending the name of the noded functionality
  """
  assert trail is not None
  trail_source = "%s:%s" % (constants.OPCODE_REASON_SRC_NODED, source)
  trail.append((trail_source, reason, utils.EpochNano()))


def _PrepareQueueLock():
  """Try to prepare the queue lock.

  @return: None for success, otherwise an exception object

  """
  global queue_lock # pylint: disable=W0603

  if queue_lock is not None:
    return None

  # Prepare job queue
  try:
    queue_lock = jstore.InitAndVerifyQueue(must_lock=False)
    return None
  except EnvironmentError, err:
    return err


def _RequireJobQueueLock(fn):
  """Decorator for job queue manipulating functions.

  """
  QUEUE_LOCK_TIMEOUT = 10

  def wrapper(*args, **kwargs):
    # Locking in exclusive, blocking mode because there could be several
    # children running at the same time. Waiting up to 10 seconds.
    if _PrepareQueueLock() is not None:
      raise errors.JobQueueError("Job queue failed initialization,"
                                 " cannot update jobs")
    queue_lock.Exclusive(blocking=True, timeout=QUEUE_LOCK_TIMEOUT)
    try:
      return fn(*args, **kwargs)
    finally:
      queue_lock.Unlock()

  return wrapper


def _DecodeImportExportIO(ieio, ieioargs):
  """Decodes import/export I/O information.

  """
  if ieio == constants.IEIO_RAW_DISK:
    assert len(ieioargs) == 1
    return (objects.Disk.FromDict(ieioargs[0]), )

  if ieio == constants.IEIO_SCRIPT:
    assert len(ieioargs) == 2
    return (objects.Disk.FromDict(ieioargs[0]), ieioargs[1])

  return ieioargs


def _DefaultAlternative(value, default):
  """Returns value or, if evaluating to False, a default value.

  Returns the given value, unless it evaluates to False. In the latter case the
  default value is returned.

  @param value: Value to return if it doesn't evaluate to False
  @param default: Default value
  @return: Given value or the default

  """
  if value:
    return value

  return default


class MlockallRequestExecutor(http.server.HttpServerRequestExecutor):
  """Subclass ensuring request handlers are locked in RAM.

  """
  def __init__(self, *args, **kwargs):
    utils.Mlockall()

    http.server.HttpServerRequestExecutor.__init__(self, *args, **kwargs)


class NodeRequestHandler(http.server.HttpServerHandler):
  """The server implementation.

  This class holds all methods exposed over the RPC interface.

  """
  # too many public methods, and unused args - all methods get params
  # due to the API
  # pylint: disable=R0904,W0613
  def __init__(self):
    http.server.HttpServerHandler.__init__(self)
    self.noded_pid = os.getpid()

  def HandleRequest(self, req):
    """Handle a request.

    """

    if req.request_method.upper() != http.HTTP_POST:
      raise http.HttpBadRequest("Only the POST method is supported")

    path = req.request_path
    if path.startswith("/"):
      path = path[1:]

    method = getattr(self, "perspective_%s" % path, None)
    if method is None:
      raise http.HttpNotFound()

    try:
      result = (True, method(serializer.LoadJson(req.request_body)))

    except backend.RPCFail, err:
      # our custom failure exception; str(err) works fine if the
      # exception was constructed with a single argument, and in
      # this case, err.message == err.args[0] == str(err)
      result = (False, str(err))
    except errors.QuitGanetiException, err:
      # Tell parent to quit
      logging.info("Shutting down the node daemon, arguments: %s",
                   str(err.args))
      os.kill(self.noded_pid, signal.SIGTERM)
      # And return the error's arguments, which must be already in
      # correct tuple format
      result = err.args
    except Exception, err:
      logging.exception("Error in RPC call")
      result = (False, "Error while executing backend function: %s" % str(err))

    return serializer.DumpJson(result)

  # the new block devices  --------------------------

  @staticmethod
  def perspective_blockdev_create(params):
    """Create a block device.

    """
    (bdev_s, size, owner, on_primary, info, excl_stor) = params
    bdev = objects.Disk.FromDict(bdev_s)
    if bdev is None:
      raise ValueError("can't unserialize data!")
    return backend.BlockdevCreate(bdev, size, owner, on_primary, info,
                                  excl_stor)

  @staticmethod
  def perspective_blockdev_pause_resume_sync(params):
    """Pause/resume sync of a block device.

    """
    disks_s, pause = params
    disks = [objects.Disk.FromDict(bdev_s) for bdev_s in disks_s]
    return backend.BlockdevPauseResumeSync(disks, pause)

  @staticmethod
  def perspective_blockdev_wipe(params):
    """Wipe a block device.

    """
    bdev_s, offset, size = params
    bdev = objects.Disk.FromDict(bdev_s)
    return backend.BlockdevWipe(bdev, offset, size)

  @staticmethod
  def perspective_blockdev_remove(params):
    """Remove a block device.

    """
    bdev_s = params[0]
    bdev = objects.Disk.FromDict(bdev_s)
    return backend.BlockdevRemove(bdev)

  @staticmethod
  def perspective_blockdev_rename(params):
    """Remove a block device.

    """
    devlist = [(objects.Disk.FromDict(ds), uid) for ds, uid in params[0]]
    return backend.BlockdevRename(devlist)

  @staticmethod
  def perspective_blockdev_assemble(params):
    """Assemble a block device.

    """
    bdev_s, owner, on_primary, idx = params
    bdev = objects.Disk.FromDict(bdev_s)
    if bdev is None:
      raise ValueError("can't unserialize data!")
    return backend.BlockdevAssemble(bdev, owner, on_primary, idx)

  @staticmethod
  def perspective_blockdev_shutdown(params):
    """Shutdown a block device.

    """
    bdev_s = params[0]
    bdev = objects.Disk.FromDict(bdev_s)
    if bdev is None:
      raise ValueError("can't unserialize data!")
    return backend.BlockdevShutdown(bdev)

  @staticmethod
  def perspective_blockdev_addchildren(params):
    """Add a child to a mirror device.

    Note: this is only valid for mirror devices. It's the caller's duty
    to send a correct disk, otherwise we raise an error.

    """
    bdev_s, ndev_s = params
    bdev = objects.Disk.FromDict(bdev_s)
    ndevs = [objects.Disk.FromDict(disk_s) for disk_s in ndev_s]
    if bdev is None or ndevs.count(None) > 0:
      raise ValueError("can't unserialize data!")
    return backend.BlockdevAddchildren(bdev, ndevs)

  @staticmethod
  def perspective_blockdev_removechildren(params):
    """Remove a child from a mirror device.

    This is only valid for mirror devices, of course. It's the callers
    duty to send a correct disk, otherwise we raise an error.

    """
    bdev_s, ndev_s = params
    bdev = objects.Disk.FromDict(bdev_s)
    ndevs = [objects.Disk.FromDict(disk_s) for disk_s in ndev_s]
    if bdev is None or ndevs.count(None) > 0:
      raise ValueError("can't unserialize data!")
    return backend.BlockdevRemovechildren(bdev, ndevs)

  @staticmethod
  def perspective_blockdev_getmirrorstatus(params):
    """Return the mirror status for a list of disks.

    """
    disks = [objects.Disk.FromDict(dsk_s)
             for dsk_s in params[0]]
    return [status.ToDict()
            for status in backend.BlockdevGetmirrorstatus(disks)]

  @staticmethod
  def perspective_blockdev_getmirrorstatus_multi(params):
    """Return the mirror status for a list of disks.

    """
    (node_disks, ) = params

    disks = [objects.Disk.FromDict(dsk_s) for dsk_s in node_disks]

    result = []

    for (success, status) in backend.BlockdevGetmirrorstatusMulti(disks):
      if success:
        result.append((success, status.ToDict()))
      else:
        result.append((success, status))

    return result

  @staticmethod
  def perspective_blockdev_find(params):
    """Expose the FindBlockDevice functionality for a disk.

    This will try to find but not activate a disk.

    """
    disk = objects.Disk.FromDict(params[0])

    result = backend.BlockdevFind(disk)
    if result is None:
      return None

    return result.ToDict()

  @staticmethod
  def perspective_blockdev_snapshot(params):
    """Create a snapshot device.

    Note that this is only valid for LVM disks, if we get passed
    something else we raise an exception. The snapshot device can be
    remove by calling the generic block device remove call.

    """
    cfbd = objects.Disk.FromDict(params[0])
    return backend.BlockdevSnapshot(cfbd)

  @staticmethod
  def perspective_blockdev_grow(params):
    """Grow a stack of devices.

    """
    if len(params) < 5:
      raise ValueError("Received only %s parameters in blockdev_grow,"
                       " old master?" % len(params))
    cfbd = objects.Disk.FromDict(params[0])
    amount = params[1]
    dryrun = params[2]
    backingstore = params[3]
    excl_stor = params[4]
    return backend.BlockdevGrow(cfbd, amount, dryrun, backingstore, excl_stor)

  @staticmethod
  def perspective_blockdev_close(params):
    """Closes the given block devices.

    """
    disks = [objects.Disk.FromDict(cf) for cf in params[1]]
    return backend.BlockdevClose(params[0], disks)

  @staticmethod
  def perspective_blockdev_getdimensions(params):
    """Compute the sizes of the given block devices.

    """
    disks = [objects.Disk.FromDict(cf) for cf in params[0]]
    return backend.BlockdevGetdimensions(disks)

  @staticmethod
  def perspective_blockdev_setinfo(params):
    """Sets metadata information on the given block device.

    """
    (disk, info) = params
    disk = objects.Disk.FromDict(disk)
    return backend.BlockdevSetInfo(disk, info)

  # blockdev/drbd specific methods ----------

  @staticmethod
  def perspective_drbd_disconnect_net(params):
    """Disconnects the network connection of drbd disks.

    Note that this is only valid for drbd disks, so the members of the
    disk list must all be drbd devices.

    """
    (disks,) = params
    disks = [objects.Disk.FromDict(disk) for disk in disks]
    return backend.DrbdDisconnectNet(disks)

  @staticmethod
  def perspective_drbd_attach_net(params):
    """Attaches the network connection of drbd disks.

    Note that this is only valid for drbd disks, so the members of the
    disk list must all be drbd devices.

    """
    disks, instance_name, multimaster = params
    disks = [objects.Disk.FromDict(disk) for disk in disks]
    return backend.DrbdAttachNet(disks, instance_name, multimaster)

  @staticmethod
  def perspective_drbd_wait_sync(params):
    """Wait until DRBD disks are synched.

    Note that this is only valid for drbd disks, so the members of the
    disk list must all be drbd devices.

    """
    (disks,) = params
    disks = [objects.Disk.FromDict(disk) for disk in disks]
    return backend.DrbdWaitSync(disks)

  @staticmethod
  def perspective_drbd_needs_activation(params):
    """Checks if the drbd devices need activation

    Note that this is only valid for drbd disks, so the members of the
    disk list must all be drbd devices.

    """
    (disks,) = params
    disks = [objects.Disk.FromDict(disk) for disk in disks]
    return backend.DrbdNeedsActivation(disks)

  @staticmethod
  def perspective_drbd_helper(_):
    """Query drbd helper.

    """
    return backend.GetDrbdUsermodeHelper()

  # export/import  --------------------------

  @staticmethod
  def perspective_finalize_export(params):
    """Expose the finalize export functionality.

    """
    instance = objects.Instance.FromDict(params[0])

    snap_disks = []
    for disk in params[1]:
      if isinstance(disk, bool):
        snap_disks.append(disk)
      else:
        snap_disks.append(objects.Disk.FromDict(disk))

    return backend.FinalizeExport(instance, snap_disks)

  @staticmethod
  def perspective_export_info(params):
    """Query information about an existing export on this node.

    The given path may not contain an export, in which case we return
    None.

    """
    path = params[0]
    return backend.ExportInfo(path)

  @staticmethod
  def perspective_export_list(params):
    """List the available exports on this node.

    Note that as opposed to export_info, which may query data about an
    export in any path, this only queries the standard Ganeti path
    (pathutils.EXPORT_DIR).

    """
    return backend.ListExports()

  @staticmethod
  def perspective_export_remove(params):
    """Remove an export.

    """
    export = params[0]
    return backend.RemoveExport(export)

  # block device ---------------------
  @staticmethod
  def perspective_bdev_sizes(params):
    """Query the list of block devices

    """
    devices = params[0]
    return backend.GetBlockDevSizes(devices)

  # volume  --------------------------

  @staticmethod
  def perspective_lv_list(params):
    """Query the list of logical volumes in a given volume group.

    """
    vgname = params[0]
    return backend.GetVolumeList(vgname)

  @staticmethod
  def perspective_vg_list(params):
    """Query the list of volume groups.

    """
    return backend.ListVolumeGroups()

  # Storage --------------------------

  @staticmethod
  def perspective_storage_list(params):
    """Get list of storage units.

    """
    (su_name, su_args, name, fields) = params
    return container.GetStorage(su_name, *su_args).List(name, fields)

  @staticmethod
  def perspective_storage_modify(params):
    """Modify a storage unit.

    """
    (su_name, su_args, name, changes) = params
    return container.GetStorage(su_name, *su_args).Modify(name, changes)

  @staticmethod
  def perspective_storage_execute(params):
    """Execute an operation on a storage unit.

    """
    (su_name, su_args, name, op) = params
    return container.GetStorage(su_name, *su_args).Execute(name, op)

  # bridge  --------------------------

  @staticmethod
  def perspective_bridges_exist(params):
    """Check if all bridges given exist on this node.

    """
    bridges_list = params[0]
    return backend.BridgesExist(bridges_list)

  # instance  --------------------------

  @staticmethod
  def perspective_instance_os_add(params):
    """Install an OS on a given instance.

    """
    inst_s = params[0]
    inst = objects.Instance.FromDict(inst_s)
    reinstall = params[1]
    debug = params[2]
    return backend.InstanceOsAdd(inst, reinstall, debug)

  @staticmethod
  def perspective_instance_run_rename(params):
    """Runs the OS rename script for an instance.

    """
    inst_s, old_name, debug = params
    inst = objects.Instance.FromDict(inst_s)
    return backend.RunRenameInstance(inst, old_name, debug)

  @staticmethod
  def perspective_instance_shutdown(params):
    """Shutdown an instance.

    """
    instance = objects.Instance.FromDict(params[0])
    timeout = params[1]
    trail = params[2]
    _extendReasonTrail(trail, "shutdown")
    return backend.InstanceShutdown(instance, timeout, trail)

  @staticmethod
  def perspective_instance_start(params):
    """Start an instance.

    """
    (instance_name, startup_paused, trail) = params
    instance = objects.Instance.FromDict(instance_name)
    _extendReasonTrail(trail, "start")
    return backend.StartInstance(instance, startup_paused, trail)

  @staticmethod
  def perspective_hotplug_device(params):
    """Hotplugs device to a running instance.

    """
    (idict, action, dev_type, ddict, extra, seq) = params
    instance = objects.Instance.FromDict(idict)
    if dev_type == constants.HOTPLUG_TARGET_DISK:
      device = objects.Disk.FromDict(ddict)
    elif dev_type == constants.HOTPLUG_TARGET_NIC:
      device = objects.NIC.FromDict(ddict)
    else:
      assert dev_type in constants.HOTPLUG_ALL_TARGETS
    return backend.HotplugDevice(instance, action, dev_type, device, extra, seq)

  @staticmethod
  def perspective_hotplug_supported(params):
    """Checks if hotplug is supported.

    """
    instance = objects.Instance.FromDict(params[0])
    return backend.HotplugSupported(instance)

  @staticmethod
  def perspective_migration_info(params):
    """Gather information about an instance to be migrated.

    """
    instance = objects.Instance.FromDict(params[0])
    return backend.MigrationInfo(instance)

  @staticmethod
  def perspective_accept_instance(params):
    """Prepare the node to accept an instance.

    """
    instance, info, target = params
    instance = objects.Instance.FromDict(instance)
    return backend.AcceptInstance(instance, info, target)

  @staticmethod
  def perspective_instance_finalize_migration_dst(params):
    """Finalize the instance migration on the destination node.

    """
    instance, info, success = params
    instance = objects.Instance.FromDict(instance)
    return backend.FinalizeMigrationDst(instance, info, success)

  @staticmethod
  def perspective_instance_migrate(params):
    """Migrates an instance.

    """
    cluster_name, instance, target, live = params
    instance = objects.Instance.FromDict(instance)
    return backend.MigrateInstance(cluster_name, instance, target, live)

  @staticmethod
  def perspective_instance_finalize_migration_src(params):
    """Finalize the instance migration on the source node.

    """
    instance, success, live = params
    instance = objects.Instance.FromDict(instance)
    return backend.FinalizeMigrationSource(instance, success, live)

  @staticmethod
  def perspective_instance_get_migration_status(params):
    """Reports migration status.

    """
    instance = objects.Instance.FromDict(params[0])
    return backend.GetMigrationStatus(instance).ToDict()

  @staticmethod
  def perspective_instance_reboot(params):
    """Reboot an instance.

    """
    instance = objects.Instance.FromDict(params[0])
    reboot_type = params[1]
    shutdown_timeout = params[2]
    trail = params[3]
    _extendReasonTrail(trail, "reboot")
    return backend.InstanceReboot(instance, reboot_type, shutdown_timeout,
                                  trail)

  @staticmethod
  def perspective_instance_balloon_memory(params):
    """Modify instance runtime memory.

    """
    instance_dict, memory = params
    instance = objects.Instance.FromDict(instance_dict)
    return backend.InstanceBalloonMemory(instance, memory)

  @staticmethod
  def perspective_instance_info(params):
    """Query instance information.

    """
    (instance_name, hypervisor_name, hvparams) = params
    return backend.GetInstanceInfo(instance_name, hypervisor_name, hvparams)

  @staticmethod
  def perspective_instance_migratable(params):
    """Query whether the specified instance can be migrated.

    """
    instance = objects.Instance.FromDict(params[0])
    return backend.GetInstanceMigratable(instance)

  @staticmethod
  def perspective_all_instances_info(params):
    """Query information about all instances.

    """
    (hypervisor_list, all_hvparams) = params
    return backend.GetAllInstancesInfo(hypervisor_list, all_hvparams)

  @staticmethod
  def perspective_instance_console_info(params):
    """Query information on how to get console access to instances

    """
    return backend.GetInstanceConsoleInfo(params)

  @staticmethod
  def perspective_instance_list(params):
    """Query the list of running instances.

    """
    (hypervisor_list, hvparams) = params
    return backend.GetInstanceList(hypervisor_list, hvparams)

  # node --------------------------

  @staticmethod
  def perspective_node_has_ip_address(params):
    """Checks if a node has the given ip address.

    """
    return netutils.IPAddress.Own(params[0])

  @staticmethod
  def perspective_node_info(params):
    """Query node information.

    """
    (storage_units, hv_specs) = params
    return backend.GetNodeInfo(storage_units, hv_specs)

  @staticmethod
  def perspective_etc_hosts_modify(params):
    """Modify a node entry in /etc/hosts.

    """
    backend.EtcHostsModify(params[0], params[1], params[2])

    return True

  @staticmethod
  def perspective_node_verify(params):
    """Run a verify sequence on this node.

    """
    (what, cluster_name, hvparams, node_groups, groups_cfg) = params
    return backend.VerifyNode(what, cluster_name, hvparams,
                              node_groups, groups_cfg)

  @classmethod
  def perspective_node_verify_light(cls, params):
    """Run a light verify sequence on this node.

    This call is meant to perform a less strict verification of the node in
    certain situations. Right now, it is invoked only when a node is just about
    to be added to a cluster, and even then, it performs the same checks as
    L{perspective_node_verify}.
    """
    return cls.perspective_node_verify(params)

  @staticmethod
  def perspective_node_start_master_daemons(params):
    """Start the master daemons on this node.

    """
    return backend.StartMasterDaemons(params[0])

  @staticmethod
  def perspective_node_activate_master_ip(params):
    """Activate the master IP on this node.

    """
    master_params = objects.MasterNetworkParameters.FromDict(params[0])
    return backend.ActivateMasterIp(master_params, params[1])

  @staticmethod
  def perspective_node_deactivate_master_ip(params):
    """Deactivate the master IP on this node.

    """
    master_params = objects.MasterNetworkParameters.FromDict(params[0])
    return backend.DeactivateMasterIp(master_params, params[1])

  @staticmethod
  def perspective_node_stop_master(params):
    """Stops master daemons on this node.

    """
    return backend.StopMasterDaemons()

  @staticmethod
  def perspective_node_change_master_netmask(params):
    """Change the master IP netmask.

    """
    return backend.ChangeMasterNetmask(params[0], params[1], params[2],
                                       params[3])

  @staticmethod
  def perspective_node_leave_cluster(params):
    """Cleanup after leaving a cluster.

    """
    return backend.LeaveCluster(params[0])

  @staticmethod
  def perspective_node_volumes(params):
    """Query the list of all logical volume groups.

    """
    return backend.NodeVolumes()

  @staticmethod
  def perspective_node_demote_from_mc(params):
    """Demote a node from the master candidate role.

    """
    return backend.DemoteFromMC()

  @staticmethod
  def perspective_node_powercycle(params):
    """Tries to powercycle the node.

    """
    (hypervisor_type, hvparams) = params
    return backend.PowercycleNode(hypervisor_type, hvparams)

  @staticmethod
  def perspective_node_configure_ovs(params):
    """Sets up OpenvSwitch on the node.

    """
    (ovs_name, ovs_link) = params
    return backend.ConfigureOVS(ovs_name, ovs_link)

  @staticmethod
  def perspective_node_crypto_tokens(params):
    """Gets the node's public crypto tokens.

    """
    token_requests = params[0]
    return backend.GetCryptoTokens(token_requests)

  # cluster --------------------------

  @staticmethod
  def perspective_version(params):
    """Query version information.

    """
    return constants.PROTOCOL_VERSION

  @staticmethod
  def perspective_upload_file(params):
    """Upload a file.

    Note that the backend implementation imposes strict rules on which
    files are accepted.

    """
    return backend.UploadFile(*(params[0]))

  @staticmethod
  def perspective_master_node_name(params):
    """Returns the master node name.

    """
    return backend.GetMasterNodeName()

  @staticmethod
  def perspective_run_oob(params):
    """Runs oob on node.

    """
    output = backend.RunOob(params[0], params[1], params[2], params[3])
    if output:
      result = serializer.LoadJson(output)
    else:
      result = None
    return result

  @staticmethod
  def perspective_restricted_command(params):
    """Runs a restricted command.

    """
    (cmd, ) = params

    return backend.RunRestrictedCmd(cmd)

  @staticmethod
  def perspective_write_ssconf_files(params):
    """Write ssconf files.

    """
    (values,) = params
    return ssconf.WriteSsconfFiles(values)

  @staticmethod
  def perspective_get_watcher_pause(params):
    """Get watcher pause end.

    """
    return utils.ReadWatcherPauseFile(pathutils.WATCHER_PAUSEFILE)

  @staticmethod
  def perspective_set_watcher_pause(params):
    """Set watcher pause.

    """
    (until, ) = params
    return backend.SetWatcherPause(until)

  # os -----------------------

  @staticmethod
  def perspective_os_diagnose(params):
    """Query detailed information about existing OSes.

    """
    return backend.DiagnoseOS()

  @staticmethod
  def perspective_os_get(params):
    """Query information about a given OS.

    """
    name = params[0]
    os_obj = backend.OSFromDisk(name)
    return os_obj.ToDict()

  @staticmethod
  def perspective_os_validate(params):
    """Run a given OS' validation routine.

    """
    required, name, checks, params = params
    return backend.ValidateOS(required, name, checks, params)

  # extstorage -----------------------

  @staticmethod
  def perspective_extstorage_diagnose(params):
    """Query detailed information about existing extstorage providers.

    """
    return backend.DiagnoseExtStorage()

  # hooks -----------------------

  @staticmethod
  def perspective_hooks_runner(params):
    """Run hook scripts.

    """
    hpath, phase, env = params
    hr = backend.HooksRunner()
    return hr.RunHooks(hpath, phase, env)

  # iallocator -----------------

  @staticmethod
  def perspective_iallocator_runner(params):
    """Run an iallocator script.

    """
    name, idata, ial_params_dict = params
    ial_params = []
    for ial_param in ial_params_dict.items():
      ial_params.append("--" + ial_param[0] + "=" + ial_param[1])
    iar = backend.IAllocatorRunner()
    return iar.Run(name, idata, ial_params)

  # test -----------------------

  @staticmethod
  def perspective_test_delay(params):
    """Run test delay.

    """
    duration = params[0]
    status, rval = utils.TestDelay(duration)
    if not status:
      raise backend.RPCFail(rval)
    return rval

  # file storage ---------------

  @staticmethod
  def perspective_file_storage_dir_create(params):
    """Create the file storage directory.

    """
    file_storage_dir = params[0]
    return backend.CreateFileStorageDir(file_storage_dir)

  @staticmethod
  def perspective_file_storage_dir_remove(params):
    """Remove the file storage directory.

    """
    file_storage_dir = params[0]
    return backend.RemoveFileStorageDir(file_storage_dir)

  @staticmethod
  def perspective_file_storage_dir_rename(params):
    """Rename the file storage directory.

    """
    old_file_storage_dir = params[0]
    new_file_storage_dir = params[1]
    return backend.RenameFileStorageDir(old_file_storage_dir,
                                        new_file_storage_dir)

  # jobs ------------------------

  @staticmethod
  @_RequireJobQueueLock
  def perspective_jobqueue_update(params):
    """Update job queue.

    """
    (file_name, content) = params
    return backend.JobQueueUpdate(file_name, content)

  @staticmethod
  @_RequireJobQueueLock
  def perspective_jobqueue_purge(params):
    """Purge job queue.

    """
    return backend.JobQueuePurge()

  @staticmethod
  @_RequireJobQueueLock
  def perspective_jobqueue_rename(params):
    """Rename a job queue file.

    """
    # TODO: What if a file fails to rename?
    return [backend.JobQueueRename(old, new) for old, new in params[0]]

  @staticmethod
  @_RequireJobQueueLock
  def perspective_jobqueue_set_drain_flag(params):
    """Set job queue's drain flag.

    """
    (flag, ) = params

    return jstore.SetDrainFlag(flag)

  # hypervisor ---------------

  @staticmethod
  def perspective_hypervisor_validate_params(params):
    """Validate the hypervisor parameters.

    """
    (hvname, hvparams) = params
    return backend.ValidateHVParams(hvname, hvparams)

  # Crypto

  @staticmethod
  def perspective_x509_cert_create(params):
    """Creates a new X509 certificate for SSL/TLS.

    """
    (validity, ) = params
    return backend.CreateX509Certificate(validity)

  @staticmethod
  def perspective_x509_cert_remove(params):
    """Removes a X509 certificate.

    """
    (name, ) = params
    return backend.RemoveX509Certificate(name)

  # Import and export

  @staticmethod
  def perspective_import_start(params):
    """Starts an import daemon.

    """
    (opts_s, instance, component, (dest, dest_args)) = params

    opts = objects.ImportExportOptions.FromDict(opts_s)

    return backend.StartImportExportDaemon(constants.IEM_IMPORT, opts,
                                           None, None,
                                           objects.Instance.FromDict(instance),
                                           component, dest,
                                           _DecodeImportExportIO(dest,
                                                                 dest_args))

  @staticmethod
  def perspective_export_start(params):
    """Starts an export daemon.

    """
    (opts_s, host, port, instance, component, (source, source_args)) = params

    opts = objects.ImportExportOptions.FromDict(opts_s)

    return backend.StartImportExportDaemon(constants.IEM_EXPORT, opts,
                                           host, port,
                                           objects.Instance.FromDict(instance),
                                           component, source,
                                           _DecodeImportExportIO(source,
                                                                 source_args))

  @staticmethod
  def perspective_impexp_status(params):
    """Retrieves the status of an import or export daemon.

    """
    return backend.GetImportExportStatus(params[0])

  @staticmethod
  def perspective_impexp_abort(params):
    """Aborts an import or export.

    """
    return backend.AbortImportExport(params[0])

  @staticmethod
  def perspective_impexp_cleanup(params):
    """Cleans up after an import or export.

    """
    return backend.CleanupImportExport(params[0])


def CheckNoded(_, args):
  """Initial checks whether to run or exit with a failure.

  """
  if args: # noded doesn't take any arguments
    print >> sys.stderr, ("Usage: %s [-f] [-d] [-p port] [-b ADDRESS]" %
                          sys.argv[0])
    sys.exit(constants.EXIT_FAILURE)
  try:
    codecs.lookup("string-escape")
  except LookupError:
    print >> sys.stderr, ("Can't load the string-escape code which is part"
                          " of the Python installation. Is your installation"
                          " complete/correct? Aborting.")
    sys.exit(constants.EXIT_FAILURE)


def SSLVerifyPeer(conn, cert, errnum, errdepth, ok):
  """Callback function to verify a peer against the candidate cert map.

  Note that we have a chicken-and-egg problem during cluster init and upgrade.
  This method checks whether the incoming connection comes from a master
  candidate by comparing it to the master certificate map in the cluster
  configuration. However, during cluster init and cluster upgrade there
  are various RPC calls done to the master node itself, before the candidate
  certificate list is established and the cluster configuration is written.
  In this case, we cannot check against the master candidate map.

  This problem is solved by checking whether the candidate map is empty. An
  initialized 2.11 or higher cluster has at least one entry for the master
  node in the candidate map. If the map is empty, we know that we are still
  in the bootstrap/upgrade phase. In this case, we read the server certificate
  digest and compare it to the incoming request.

  This means that after an upgrade of Ganeti, the system continues to operate
  like before, using server certificates only. After the client certificates
  are generated with ``gnt-cluster renew-crypto --new-node-certificates``,
  RPC communication is switched to using client certificates and the trick of
  using server certificates does not work anymore.

  @type conn: C{OpenSSL.SSL.Connection}
  @param conn: the OpenSSL connection object
  @type cert: C{OpenSSL.X509}
  @param cert: the peer's SSL certificate

  """
  # some parameters are unused, but this is the API
  # pylint: disable=W0613
  _BOOTSTRAP = "bootstrap"
  sstore = ssconf.SimpleStore()
  try:
    candidate_certs = sstore.GetMasterCandidatesCertMap()
  except errors.ConfigurationError:
    logging.info("No candidate certificates found. Switching to "
                 "bootstrap/update mode.")
    candidate_certs = None
  if not candidate_certs:
    candidate_certs = {
      _BOOTSTRAP: utils.GetCertificateDigest(
        cert_filename=pathutils.NODED_CERT_FILE)}
  return cert.digest("sha1") in candidate_certs.values()
  # pylint: enable=W0613


def PrepNoded(options, _):
  """Preparation node daemon function, executed with the PID file held.

  """
  if options.mlock:
    request_executor_class = MlockallRequestExecutor
    try:
      utils.Mlockall()
    except errors.NoCtypesError:
      logging.warning("Cannot set memory lock, ctypes module not found")
      request_executor_class = http.server.HttpServerRequestExecutor
  else:
    request_executor_class = http.server.HttpServerRequestExecutor

  # Read SSL certificate
  if options.ssl:
    ssl_params = http.HttpSslParams(ssl_key_path=options.ssl_key,
                                    ssl_cert_path=options.ssl_cert)
  else:
    ssl_params = None

  err = _PrepareQueueLock()
  if err is not None:
    # this might be some kind of file-system/permission error; while
    # this breaks the job queue functionality, we shouldn't prevent
    # startup of the whole node daemon because of this
    logging.critical("Can't init/verify the queue, proceeding anyway: %s", err)

  handler = NodeRequestHandler()

  mainloop = daemon.Mainloop()
  server = \
    http.server.HttpServer(mainloop, options.bind_address, options.port,
                           handler, ssl_params=ssl_params, ssl_verify_peer=True,
                           request_executor_class=request_executor_class,
                           ssl_verify_callback=SSLVerifyPeer)
  server.Start()

  return (mainloop, server)


def ExecNoded(options, args, prep_data): # pylint: disable=W0613
  """Main node daemon function, executed with the PID file held.

  """
  (mainloop, server) = prep_data
  try:
    mainloop.Run()
  finally:
    server.Stop()


def Main():
  """Main function for the node daemon.

  """
  parser = OptionParser(description="Ganeti node daemon",
                        usage=("%prog [-f] [-d] [-p port] [-b ADDRESS]"
                               " [-i INTERFACE]"),
                        version="%%prog (ganeti) %s" %
                        constants.RELEASE_VERSION)
  parser.add_option("--no-mlock", dest="mlock",
                    help="Do not mlock the node memory in ram",
                    default=True, action="store_false")

  daemon.GenericMain(constants.NODED, parser, CheckNoded, PrepNoded, ExecNoded,
                     default_ssl_cert=pathutils.NODED_CERT_FILE,
                     default_ssl_key=pathutils.NODED_CERT_FILE,
                     console_logging=True,
                     warn_breach=True)
