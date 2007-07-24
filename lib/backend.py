#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Functions used by the node daemon"""


import os
import os.path
import shutil
import time
import tempfile
import stat
import errno
import re
import subprocess

from ganeti import logger
from ganeti import errors
from ganeti import utils
from ganeti import ssh
from ganeti import hypervisor
from ganeti import constants
from ganeti import bdev
from ganeti import objects
from ganeti import ssconf


def ListConfigFiles():
  """Return a list of the config files present on the local node.
  """

  configfiles = []

  for testfile in constants.MASTER_CONFIGFILES:
    if os.path.exists(testfile):
      configfiles.append(testfile)

  for testfile in constants.NODE_CONFIGFILES:
    if os.path.exists(testfile):
      configfiles.append(testfile)

  return configfiles


def StartMaster():
  """Activate local node as master node.

  There are two needed steps for this:
    - run the master script
    - register the cron script

  """
  result = utils.RunCmd([constants.MASTER_SCRIPT, "-d", "start"])

  if result.failed:
    logger.Error("could not activate cluster interface with command %s,"
                 " error: '%s'" % (result.cmd, result.output))
    return False

  utils.RemoveFile(constants.MASTER_CRON_LINK)
  os.symlink(constants.MASTER_CRON_FILE, constants.MASTER_CRON_LINK)
  return True


def StopMaster():
  """Deactivate this node as master.

  This does two things:
    - run the master stop script
    - remove link to master cron script.

  """
  result = utils.RunCmd([constants.MASTER_SCRIPT, "-d", "stop"])

  if result.failed:
    logger.Error("could not deactivate cluster interface with command %s,"
                 " error: '%s'" % (result.cmd, result.output))
    return False

  utils.RemoveFile(constants.MASTER_CRON_LINK)

  return True


def AddNode(dsa, dsapub, rsa, rsapub, ssh, sshpub):
  """ adds the node to the cluster
      - updates the hostkey
      - adds the ssh-key
      - sets the node id
      - sets the node status to installed
  """

  f = open("/etc/ssh/ssh_host_rsa_key", 'w')
  f.write(rsa)
  f.close()

  f = open("/etc/ssh/ssh_host_rsa_key.pub", 'w')
  f.write(rsapub)
  f.close()

  f = open("/etc/ssh/ssh_host_dsa_key", 'w')
  f.write(dsa)
  f.close()

  f = open("/etc/ssh/ssh_host_dsa_key.pub", 'w')
  f.write(dsapub)
  f.close()

  if not os.path.isdir("/root/.ssh"):
    os.mkdir("/root/.ssh")

  f = open("/root/.ssh/id_dsa", 'w')
  f.write(ssh)
  f.close()

  f = open("/root/.ssh/id_dsa.pub", 'w')
  f.write(sshpub)
  f.close()

  f = open('/root/.ssh/id_dsa.pub', 'r')
  try:
    utils.AddAuthorizedKey('/root/.ssh/authorized_keys', f.read(8192))
  finally:
    f.close()

  utils.RunCmd(["/etc/init.d/ssh", "restart"])

  utils.RemoveFile("/root/.ssh/known_hosts")
  return True


def LeaveCluster():
  """Cleans up the current node and prepares it to be removed from the cluster.

  """
  if os.path.exists(constants.DATA_DIR):
    for dirpath, dirnames, filenames in os.walk(constants.DATA_DIR):
      if dirpath == constants.DATA_DIR:
        for i in filenames:
          os.unlink(os.path.join(dirpath, i))

  f = open('/root/.ssh/id_dsa.pub', 'r')
  try:
    utils.RemoveAuthorizedKey('/root/.ssh/authorized_keys', f.read(8192))
  finally:
    f.close()

  utils.RemoveFile('/root/.ssh/id_dsa')
  utils.RemoveFile('/root/.ssh/id_dsa.pub')


def GetNodeInfo(vgname):
  """ gives back a hash with different informations
  about the node

  Returns:
    { 'vg_size' : xxx,  'vg_free' : xxx, 'memory_domain0': xxx,
      'memory_free' : xxx, 'memory_total' : xxx }
    where
    vg_size is the size of the configured volume group in MiB
    vg_free is the free size of the volume group in MiB
    memory_dom0 is the memory allocated for domain0 in MiB
    memory_free is the currently available (free) ram in MiB
    memory_total is the total number of ram in MiB
  """

  outputarray = {}
  vginfo = _GetVGInfo(vgname)
  outputarray['vg_size'] = vginfo['vg_size']
  outputarray['vg_free'] = vginfo['vg_free']

  hyper = hypervisor.GetHypervisor()
  hyp_info = hyper.GetNodeInfo()
  if hyp_info is not None:
    outputarray.update(hyp_info)

  return outputarray


def VerifyNode(what):
  """Verify the status of the local node.

  Args:
    what - a dictionary of things to check:
      'filelist' : list of files for which to compute checksums
      'nodelist' : list of nodes we should check communication with
      'hypervisor': run the hypervisor-specific verify

  Requested files on local node are checksummed and the result returned.

  The nodelist is traversed, with the following checks being made
  for each node:
  - known_hosts key correct
  - correct resolving of node name (target node returns its own hostname
    by ssh-execution of 'hostname', result compared against name in list.

  """

  result = {}

  if 'hypervisor' in what:
    result['hypervisor'] = hypervisor.GetHypervisor().Verify()

  if 'filelist' in what:
    result['filelist'] = utils.FingerprintFiles(what['filelist'])

  if 'nodelist' in what:
    result['nodelist'] = {}
    for node in what['nodelist']:
      success, message = ssh.VerifyNodeHostname(node)
      if not success:
        result['nodelist'][node] = message
  return result


def GetVolumeList(vg_name):
  """Compute list of logical volumes and their size.

  Returns:
    dictionary of all partions (key) with their size:
    test1: 20.06MiB

  """
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m",
                         "-oname,size", vg_name])
  if result.failed:
    logger.Error("Failed to list logical volumes, lvs output: %s" %
                 result.output)
    return {}

  lvlist = [line.split() for line in result.output.splitlines()]
  return dict(lvlist)


def ListVolumeGroups():
  """List the volume groups and their size

  Returns:
    Dictionary with keys volume name and values the size of the volume

  """
  return utils.ListVolumeGroups()


def NodeVolumes():
  """List all volumes on this node.

  """
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m", "--nosuffix",
                         "--separator=|",
                         "--options=lv_name,lv_size,devices,vg_name"])
  if result.failed:
    logger.Error("Failed to list logical volumes, lvs output: %s" %
                 result.output)
    return {}

  def parse_dev(dev):
    if '(' in dev:
      return dev.split('(')[0]
    else:
      return dev

  def map_line(line):
    return {
      'name': line[0].strip(),
      'size': line[1].strip(),
      'dev': parse_dev(line[2].strip()),
      'vg': line[3].strip(),
    }

  return [map_line(line.split('|')) for line in result.output.splitlines()]


def BridgesExist(bridges_list):
  """Check if a list of bridges exist on the current node

  Returns:
    True if all of them exist, false otherwise

  """
  for bridge in bridges_list:
    if not utils.BridgeExists(bridge):
      return False

  return True


def GetInstanceList():
  """ provides a list of instances

  Returns:
    A list of all running instances on the current node
    - instance1.example.com
    - instance2.example.com
  """

  try:
    names = hypervisor.GetHypervisor().ListInstances()
  except errors.HypervisorError, err:
    logger.Error("error enumerating instances: %s" % str(err))
    raise

  return names


def GetInstanceInfo(instance):
  """ gives back the informations about an instance
  as a dictonary

  Args:
    instance: name of the instance (ex. instance1.example.com)

  Returns:
    { 'memory' : 511, 'state' : '-b---', 'time' : 3188.8, }
    where
    memory: memory size of instance (int)
    state: xen state of instance (string)
    time: cpu time of instance (float)
  """

  output = {}

  iinfo = hypervisor.GetHypervisor().GetInstanceInfo(instance)
  if iinfo is not None:
    output['memory'] = iinfo[2]
    output['state'] = iinfo[4]
    output['time'] = iinfo[5]

  return output


def GetAllInstancesInfo():
  """Gather data about all instances.

  This is the equivalent of `GetInstanceInfo()`, except that it
  computes data for all instances at once, thus being faster if one
  needs data about more than one instance.

  Returns: a dictionary of dictionaries, keys being the instance name,
    and with values:
    { 'memory' : 511, 'state' : '-b---', 'time' : 3188.8, }
    where
    memory: memory size of instance (int)
    state: xen state of instance (string)
    time: cpu time of instance (float)
    vcpus: the number of cpus
  """

  output = {}

  iinfo = hypervisor.GetHypervisor().GetAllInstancesInfo()
  if iinfo:
    for name, id, memory, vcpus, state, times in iinfo:
      output[name] = {
        'memory': memory,
        'vcpus': vcpus,
        'state': state,
        'time': times,
        }

  return output


def AddOSToInstance(instance, os_disk, swap_disk):
  """Add an os to an instance.

  Args:
    instance: the instance object
    os_disk: the instance-visible name of the os device
    swap_disk: the instance-visible name of the swap device

  """
  inst_os = OSFromDisk(instance.os)

  create_script = inst_os.create_script

  for os_device in instance.disks:
    if os_device.iv_name == os_disk:
      break
  else:
    logger.Error("Can't find this device-visible name '%s'" % os_disk)
    return False

  for swap_device in instance.disks:
    if swap_device.iv_name == swap_disk:
      break
  else:
    logger.Error("Can't find this device-visible name '%s'" % swap_disk)
    return False

  real_os_dev = _RecursiveFindBD(os_device)
  if real_os_dev is None:
    raise errors.BlockDeviceError("Block device '%s' is not set up" %
                                  str(os_device))
  real_os_dev.Open()

  real_swap_dev = _RecursiveFindBD(swap_device)
  if real_swap_dev is None:
    raise errors.BlockDeviceError("Block device '%s' is not set up" %
                                  str(swap_device))
  real_swap_dev.Open()

  logfile = "%s/add-%s-%s-%d.log" % (constants.LOG_OS_DIR, instance.os,
                                     instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)

  command = utils.BuildShellCmd("cd %s; %s -i %s -b %s -s %s &>%s",
                                inst_os.path, create_script, instance.name,
                                real_os_dev.dev_path, real_swap_dev.dev_path,
                                logfile)

  result = utils.RunCmd(command)

  if result.failed:
    logger.Error("os create command '%s' returned error: %s"
                 " output: %s" %
                 (command, result.fail_reason, result.output))
    return False

  return True


def _GetVGInfo(vg_name):
  """Get informations about the volume group.

  Args:
    vg_name: the volume group

  Returns:
    { 'vg_size' : xxx, 'vg_free' : xxx, 'pv_count' : xxx }
    where
    vg_size is the total size of the volume group in MiB
    vg_free is the free size of the volume group in MiB
    pv_count are the number of physical disks in that vg

  """
  retval = utils.RunCmd(["vgs", "-ovg_size,vg_free,pv_count", "--noheadings",
                         "--nosuffix", "--units=m", "--separator=:", vg_name])

  if retval.failed:
    errmsg = "volume group %s not present" % vg_name
    logger.Error(errmsg)
    raise errors.LVMError(errmsg)
  valarr = retval.stdout.strip().split(':')
  retdic = {
    "vg_size": int(round(float(valarr[0]), 0)),
    "vg_free": int(round(float(valarr[1]), 0)),
    "pv_count": int(valarr[2]),
    }
  return retdic


def _GatherBlockDevs(instance):
  """Set up an instance's block device(s).

  This is run on the primary node at instance startup. The block
  devices must be already assembled.

  """
  block_devices = []
  for disk in instance.disks:
    device = _RecursiveFindBD(disk)
    if device is None:
      raise errors.BlockDeviceError("Block device '%s' is not set up." %
                                    str(disk))
    device.Open()
    block_devices.append((disk, device))
  return block_devices


def StartInstance(instance, extra_args):
  """Start an instance.

  Args:
    instance - name of instance to start.
  """

  running_instances = GetInstanceList()

  if instance.name in running_instances:
    return True

  block_devices = _GatherBlockDevs(instance)
  hyper = hypervisor.GetHypervisor()

  try:
    hyper.StartInstance(instance, block_devices, extra_args)
  except errors.HypervisorError, err:
    logger.Error("Failed to start instance: %s" % err)
    return False

  return True


def ShutdownInstance(instance):
  """Shut an instance down.

  Args:
    instance - name of instance to shutdown.
  """

  running_instances = GetInstanceList()

  if instance.name not in running_instances:
    return True

  hyper = hypervisor.GetHypervisor()
  try:
    hyper.StopInstance(instance)
  except errors.HypervisorError, err:
    logger.Error("Failed to stop instance: %s" % err)
    return False

  # test every 10secs for 2min
  shutdown_ok = False

  time.sleep(1)
  for dummy in range(11):
    if instance.name not in GetInstanceList():
      break
    time.sleep(10)
  else:
    # the shutdown did not succeed
    logger.Error("shutdown of '%s' unsuccessful, using destroy" % instance)

    try:
      hyper.StopInstance(instance, force=True)
    except errors.HypervisorError, err:
      logger.Error("Failed to stop instance: %s" % err)
      return False

    time.sleep(1)
    if instance.name in GetInstanceList():
      logger.Error("could not shutdown instance '%s' even by destroy")
      return False

  return True


def CreateBlockDevice(disk, size, on_primary):
  """Creates a block device for an instance.

  Args:
   bdev: a ganeti.objects.Disk object
   size: the size of the physical underlying devices
   do_open: if the device should be `Assemble()`-d and
            `Open()`-ed after creation

  Returns:
    the new unique_id of the device (this can sometime be
    computed only after creation), or None. On secondary nodes,
    it's not required to return anything.

  """
  clist = []
  if disk.children:
    for child in disk.children:
      crdev = _RecursiveAssembleBD(child, on_primary)
      if on_primary or disk.AssembleOnSecondary():
        # we need the children open in case the device itself has to
        # be assembled
        crdev.Open()
      else:
        crdev.Close()
      clist.append(crdev)
  try:
    device = bdev.FindDevice(disk.dev_type, disk.physical_id, clist)
    if device is not None:
      logger.Info("removing existing device %s" % disk)
      device.Remove()
  except errors.BlockDeviceError, err:
    pass

  device = bdev.Create(disk.dev_type, disk.physical_id,
                       clist, size)
  if device is None:
    raise ValueError("Can't create child device for %s, %s" %
                     (disk, size))
  if on_primary or disk.AssembleOnSecondary():
    device.Assemble()
    device.SetSyncSpeed(30*1024)
    if on_primary or disk.OpenOnSecondary():
      device.Open(force=True)
  physical_id = device.unique_id
  return physical_id


def RemoveBlockDevice(disk):
  """Remove a block device.

  This is intended to be called recursively.

  """
  try:
    # since we are removing the device, allow a partial match
    # this allows removal of broken mirrors
    rdev = _RecursiveFindBD(disk, allow_partial=True)
  except errors.BlockDeviceError, err:
    # probably can't attach
    logger.Info("Can't attach to device %s in remove" % disk)
    rdev = None
  if rdev is not None:
    result = rdev.Remove()
  else:
    result = True
  if disk.children:
    for child in disk.children:
      result = result and RemoveBlockDevice(child)
  return result


def _RecursiveAssembleBD(disk, as_primary):
  """Activate a block device for an instance.

  This is run on the primary and secondary nodes for an instance.

  This function is called recursively.

  Args:
    disk: a objects.Disk object
    as_primary: if we should make the block device read/write

  Returns:
    the assembled device or None (in case no device was assembled)

  If the assembly is not successful, an exception is raised.

  """
  children = []
  if disk.children:
    for chld_disk in disk.children:
      children.append(_RecursiveAssembleBD(chld_disk, as_primary))

  if as_primary or disk.AssembleOnSecondary():
    r_dev = bdev.AttachOrAssemble(disk.dev_type, disk.physical_id, children)
    r_dev.SetSyncSpeed(30*1024)
    result = r_dev
    if as_primary or disk.OpenOnSecondary():
      r_dev.Open()
    else:
      r_dev.Close()
  else:
    result = True
  return result


def AssembleBlockDevice(disk, as_primary):
  """Activate a block device for an instance.

  This is a wrapper over _RecursiveAssembleBD.

  Returns:
    a /dev path for primary nodes
    True for secondary nodes

  """
  result = _RecursiveAssembleBD(disk, as_primary)
  if isinstance(result, bdev.BlockDev):
    result = result.dev_path
  return result


def ShutdownBlockDevice(disk):
  """Shut down a block device.

  First, if the device is assembled (can `Attach()`), then the device
  is shutdown. Then the children of the device are shutdown.

  This function is called recursively. Note that we don't cache the
  children or such, as oppossed to assemble, shutdown of different
  devices doesn't require that the upper device was active.

  """
  r_dev = _RecursiveFindBD(disk)
  if r_dev is not None:
    result = r_dev.Shutdown()
  else:
    result = True
  if disk.children:
    for child in disk.children:
      result = result and ShutdownBlockDevice(child)
  return result


def MirrorAddChild(md_cdev, new_cdev):
  """Extend an MD raid1 array.

  """
  md_bdev = _RecursiveFindBD(md_cdev, allow_partial=True)
  if md_bdev is None:
    logger.Error("Can't find md device")
    return False
  new_bdev = _RecursiveFindBD(new_cdev)
  if new_bdev is None:
    logger.Error("Can't find new device to add")
    return False
  new_bdev.Open()
  md_bdev.AddChild(new_bdev)
  return True


def MirrorRemoveChild(md_cdev, new_cdev):
  """Reduce an MD raid1 array.

  """
  md_bdev = _RecursiveFindBD(md_cdev)
  if md_bdev is None:
    return False
  new_bdev = _RecursiveFindBD(new_cdev)
  if new_bdev is None:
    return False
  new_bdev.Open()
  md_bdev.RemoveChild(new_bdev.dev_path)
  return True


def GetMirrorStatus(disks):
  """Get the mirroring status of a list of devices.

  Args:
    disks: list of `objects.Disk`

  Returns:
    list of (mirror_done, estimated_time) tuples, which
    are the result of bdev.BlockDevice.CombinedSyncStatus()

  """
  stats = []
  for dsk in disks:
    rbd = _RecursiveFindBD(dsk)
    if rbd is None:
      raise errors.BlockDeviceError, "Can't find device %s" % str(dsk)
    stats.append(rbd.CombinedSyncStatus())
  return stats


def _RecursiveFindBD(disk, allow_partial=False):
  """Check if a device is activated.

  If so, return informations about the real device.

  Args:
    disk: the objects.Disk instance
    allow_partial: don't abort the find if a child of the
                   device can't be found; this is intended to be
                   used when repairing mirrors

  Returns:
    None if the device can't be found
    otherwise the device instance

  """
  children = []
  if disk.children:
    for chdisk in disk.children:
      children.append(_RecursiveFindBD(chdisk))

  return bdev.FindDevice(disk.dev_type, disk.physical_id, children)


def FindBlockDevice(disk):
  """Check if a device is activated.

  If so, return informations about the real device.

  Args:
    disk: the objects.Disk instance
  Returns:
    None if the device can't be found
    (device_path, major, minor, sync_percent, estimated_time, is_degraded)

  """
  rbd = _RecursiveFindBD(disk)
  if rbd is None:
    return rbd
  sync_p, est_t, is_degr = rbd.GetSyncStatus()
  return rbd.dev_path, rbd.major, rbd.minor, sync_p, est_t, is_degr


def UploadFile(file_name, data, mode, uid, gid, atime, mtime):
  """Write a file to the filesystem.

  This allows the master to overwrite(!) a file. It will only perform
  the operation if the file belongs to a list of configuration files.

  """
  if not os.path.isabs(file_name):
    logger.Error("Filename passed to UploadFile is not absolute: '%s'" %
                 file_name)
    return False

  allowed_files = [constants.CLUSTER_CONF_FILE, "/etc/hosts",
                   "/etc/ssh/ssh_known_hosts"]
  allowed_files.extend(ssconf.SimpleStore().GetFileList())
  if file_name not in allowed_files:
    logger.Error("Filename passed to UploadFile not in allowed"
                 " upload targets: '%s'" % file_name)
    return False

  dir_name, small_name = os.path.split(file_name)
  fd, new_name = tempfile.mkstemp('.new', small_name, dir_name)
  # here we need to make sure we remove the temp file, if any error
  # leaves it in place
  try:
    os.chown(new_name, uid, gid)
    os.chmod(new_name, mode)
    os.write(fd, data)
    os.fsync(fd)
    os.utime(new_name, (atime, mtime))
    os.rename(new_name, file_name)
  finally:
    os.close(fd)
    utils.RemoveFile(new_name)
  return True

def _ErrnoOrStr(err):
  """Format an EnvironmentError exception.

  If the `err` argument has an errno attribute, it will be looked up
  and converted into a textual EXXXX description. Otherwise the string
  representation of the error will be returned.

  """
  if hasattr(err, 'errno'):
    detail = errno.errorcode[err.errno]
  else:
    detail = str(err)
  return detail


def _OSOndiskVersion(name, os_dir=None):
  """Compute and return the api version of a given OS.

  This function will try to read the api version of the os given by
  the 'name' parameter. By default, it wil use the constants.OS_DIR
  as top-level directory for OSes, but this can be overriden by the
  use of the os_dir parameter. Return value will be either an
  integer denoting the version or None in the case when this is not
  a valid OS name.

  """
  if os_dir is None:
    os_dir = os.path.sep.join([constants.OS_DIR, name])

  api_file = os.path.sep.join([os_dir, "ganeti_api_version"])

  try:
    st = os.stat(api_file)
  except EnvironmentError, err:
    raise errors.InvalidOS, (name, "'ganeti_api_version' file not"
                             " found (%s)" % _ErrnoOrStr(err))

  if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
    raise errors.InvalidOS, (name, "'ganeti_api_version' file is not"
                             " a regular file")

  try:
    f = open(api_file)
    try:
      api_version = f.read(256)
    finally:
      f.close()
  except EnvironmentError, err:
    raise errors.InvalidOS, (name, "error while reading the"
                             " API version (%s)" % _ErrnoOrStr(err))

  api_version = api_version.strip()
  try:
    api_version = int(api_version)
  except (TypeError, ValueError), err:
    raise errors.InvalidOS, (name, "API version is not integer (%s)" %
                             str(err))

  return api_version

def DiagnoseOS(top_dir=None):
  """Compute the validity for all OSes.

  For each name in the give top_dir parameter (if not given, defaults
  to constants.OS_DIR), it will return an object. If this is a valid
  os, the object will be an instance of the object.OS class. If not,
  it will be an instance of errors.InvalidOS and this signifies that
  this name does not correspond to a valid OS.

  Returns:
    list of objects

  """
  if top_dir is None:
    top_dir = constants.OS_DIR

  try:
    f_names = os.listdir(top_dir)
  except EnvironmentError, err:
    logger.Error("Can't list the OS directory: %s" % str(err))
    return False
  result = []
  for name in f_names:
    try:
      os_inst = OSFromDisk(name, os.path.sep.join([top_dir, name]))
      result.append(os_inst)
    except errors.InvalidOS, err:
      result.append(err)

  return result


def OSFromDisk(name, os_dir=None):
  """Create an OS instance from disk.

  This function will return an OS instance if the given name is a
  valid OS name. Otherwise, it will raise an appropriate
  `errors.InvalidOS` exception, detailing why this is not a valid
  OS.

  """
  if os_dir is None:
    os_dir = os.path.sep.join([constants.OS_DIR, name])

  api_version = _OSOndiskVersion(name, os_dir)

  if api_version != constants.OS_API_VERSION:
    raise errors.InvalidOS, (name, "API version mismatch (found %s want %s)"
                             % (api_version, constants.OS_API_VERSION))

  # OS Scripts dictionary, we will populate it with the actual script names
  os_scripts = {'create': '', 'export': '', 'import': ''}

  for script in os_scripts:
    os_scripts[script] = os.path.sep.join([os_dir, script])

    try:
      st = os.stat(os_scripts[script])
    except EnvironmentError, err:
      raise errors.InvalidOS, (name, "'%s' script missing (%s)" %
                               (script, _ErrnoOrStr(err)))

    if stat.S_IMODE(st.st_mode) & stat.S_IXUSR != stat.S_IXUSR:
      raise errors.InvalidOS, (name, "'%s' script not executable" % script)

    if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
      raise errors.InvalidOS, (name, "'%s' is not a regular file" % script)


  return objects.OS(name=name, path=os_dir,
                    create_script=os_scripts['create'],
                    export_script=os_scripts['export'],
                    import_script=os_scripts['import'],
                    api_version=api_version)


def SnapshotBlockDevice(disk):
  """Create a snapshot copy of a block device.

  This function is called recursively, and the snapshot is actually created
  just for the leaf lvm backend device.

  Args:
    disk: the disk to be snapshotted

  Returns:
    a config entry for the actual lvm device snapshotted.
  """

  if disk.children:
    if len(disk.children) == 1:
      # only one child, let's recurse on it
      return SnapshotBlockDevice(disk.children[0])
    else:
      # more than one child, choose one that matches
      for child in disk.children:
        if child.size == disk.size:
          # return implies breaking the loop
          return SnapshotBlockDevice(child)
  elif disk.dev_type == "lvm":
    r_dev = _RecursiveFindBD(disk)
    if r_dev is not None:
      # let's stay on the safe side and ask for the full size, for now
      return r_dev.Snapshot(disk.size)
    else:
      return None
  else:
    raise errors.ProgrammerError, ("Cannot snapshot non-lvm block device"
                                   "'%s' of type '%s'" %
                                   (disk.unique_id, disk.dev_type))


def ExportSnapshot(disk, dest_node, instance):
  """Export a block device snapshot to a remote node.

  Args:
    disk: the snapshot block device
    dest_node: the node to send the image to
    instance: instance being exported

  Returns:
    True if successful, False otherwise.
  """

  inst_os = OSFromDisk(instance.os)
  export_script = inst_os.export_script

  logfile = "%s/exp-%s-%s-%s.log" % (constants.LOG_OS_DIR, inst_os.name,
                                     instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)

  real_os_dev = _RecursiveFindBD(disk)
  if real_os_dev is None:
    raise errors.BlockDeviceError("Block device '%s' is not set up" %
                                  str(disk))
  real_os_dev.Open()

  destdir = os.path.join(constants.EXPORT_DIR, instance.name + ".new")
  destfile = disk.physical_id[1]

  # the target command is built out of three individual commands,
  # which are joined by pipes; we check each individual command for
  # valid parameters

  expcmd = utils.BuildShellCmd("cd %s; %s -i %s -b %s 2>%s", inst_os.path,
                               export_script, instance.name,
                               real_os_dev.dev_path, logfile)

  comprcmd = "gzip"

  remotecmd = utils.BuildShellCmd("ssh -q -oStrictHostKeyChecking=yes"
                                  " -oBatchMode=yes -oEscapeChar=none"
                                  " %s 'mkdir -p %s; cat > %s/%s'",
                                  dest_node, destdir, destdir, destfile)

  # all commands have been checked, so we're safe to combine them
  command = '|'.join([expcmd, comprcmd, remotecmd])

  result = utils.RunCmd(command)

  if result.failed:
    logger.Error("os snapshot export command '%s' returned error: %s"
                 " output: %s" %
                 (command, result.fail_reason, result.output))
    return False

  return True


def FinalizeExport(instance, snap_disks):
  """Write out the export configuration information.

  Args:
    instance: instance configuration
    snap_disks: snapshot block devices

  Returns:
    False in case of error, True otherwise.
  """

  destdir = os.path.join(constants.EXPORT_DIR, instance.name + ".new")
  finaldestdir = os.path.join(constants.EXPORT_DIR, instance.name)

  config = objects.SerializableConfigParser()

  config.add_section(constants.INISECT_EXP)
  config.set(constants.INISECT_EXP, 'version', '0')
  config.set(constants.INISECT_EXP, 'timestamp', '%d' % int(time.time()))
  config.set(constants.INISECT_EXP, 'source', instance.primary_node)
  config.set(constants.INISECT_EXP, 'os', instance.os)
  config.set(constants.INISECT_EXP, 'compression', 'gzip')

  config.add_section(constants.INISECT_INS)
  config.set(constants.INISECT_INS, 'name', instance.name)
  config.set(constants.INISECT_INS, 'memory', '%d' % instance.memory)
  config.set(constants.INISECT_INS, 'vcpus', '%d' % instance.vcpus)
  config.set(constants.INISECT_INS, 'disk_template', instance.disk_template)
  for nic_count, nic in enumerate(instance.nics):
    config.set(constants.INISECT_INS, 'nic%d_mac' %
               nic_count, '%s' % nic.mac)
    config.set(constants.INISECT_INS, 'nic%d_ip' % nic_count, '%s' % nic.ip)
  # TODO: redundant: on load can read nics until it doesn't exist
  config.set(constants.INISECT_INS, 'nic_count' , '%d' % nic_count)

  for disk_count, disk in enumerate(snap_disks):
    config.set(constants.INISECT_INS, 'disk%d_ivname' % disk_count,
               ('%s' % disk.iv_name))
    config.set(constants.INISECT_INS, 'disk%d_dump' % disk_count,
               ('%s' % disk.physical_id[1]))
    config.set(constants.INISECT_INS, 'disk%d_size' % disk_count,
               ('%d' % disk.size))
  config.set(constants.INISECT_INS, 'disk_count' , '%d' % disk_count)

  cff = os.path.join(destdir, constants.EXPORT_CONF_FILE)
  cfo = open(cff, 'w')
  try:
    config.write(cfo)
  finally:
    cfo.close()

  shutil.rmtree(finaldestdir, True)
  shutil.move(destdir, finaldestdir)

  return True


def ExportInfo(dest):
  """Get export configuration information.

  Args:
    dest: directory containing the export

  Returns:
    A serializable config file containing the export info.

  """

  cff = os.path.join(dest, constants.EXPORT_CONF_FILE)

  config = objects.SerializableConfigParser()
  config.read(cff)

  if (not config.has_section(constants.INISECT_EXP) or
      not config.has_section(constants.INISECT_INS)):
    return None

  return config


def ImportOSIntoInstance(instance, os_disk, swap_disk, src_node, src_image):
  """Import an os image into an instance.

  Args:
    instance: the instance object
    os_disk: the instance-visible name of the os device
    swap_disk: the instance-visible name of the swap device
    src_node: node holding the source image
    src_image: path to the source image on src_node

  Returns:
    False in case of error, True otherwise.

  """

  inst_os = OSFromDisk(instance.os)
  import_script = inst_os.import_script

  for os_device in instance.disks:
    if os_device.iv_name == os_disk:
      break
  else:
    logger.Error("Can't find this device-visible name '%s'" % os_disk)
    return False

  for swap_device in instance.disks:
    if swap_device.iv_name == swap_disk:
      break
  else:
    logger.Error("Can't find this device-visible name '%s'" % swap_disk)
    return False

  real_os_dev = _RecursiveFindBD(os_device)
  if real_os_dev is None:
    raise errors.BlockDeviceError, ("Block device '%s' is not set up" %
                                    str(os_device))
  real_os_dev.Open()

  real_swap_dev = _RecursiveFindBD(swap_device)
  if real_swap_dev is None:
    raise errors.BlockDeviceError, ("Block device '%s' is not set up" %
                                    str(swap_device))
  real_swap_dev.Open()

  logfile = "%s/import-%s-%s-%s.log" % (constants.LOG_OS_DIR, instance.os,
                                        instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)

  remotecmd = utils.BuildShellCmd("ssh -q -oStrictHostKeyChecking=yes"
                                  " -oBatchMode=yes -oEscapeChar=none"
                                  " %s 'cat %s'", src_node, src_image)

  comprcmd = "gunzip"
  impcmd = utils.BuildShellCmd("(cd %s; %s -i %s -b %s -s %s &>%s)",
                               inst_os.path, import_script, instance.name,
                               real_os_dev.dev_path, real_swap_dev.dev_path,
                               logfile)

  command = '|'.join([remotecmd, comprcmd, impcmd])

  result = utils.RunCmd(command)

  if result.failed:
    logger.Error("os import command '%s' returned error: %s"
                 " output: %s" %
                 (command, result.fail_reason, result.output))
    return False

  return True


def ListExports():
  """Return a list of exports currently available on this machine.
  """
  if os.path.isdir(constants.EXPORT_DIR):
    return os.listdir(constants.EXPORT_DIR)
  else:
    return []


def RemoveExport(export):
  """Remove an existing export from the node.

  Args:
    export: the name of the export to remove

  Returns:
    False in case of error, True otherwise.
  """

  target = os.path.join(constants.EXPORT_DIR, export)

  shutil.rmtree(target)
  # TODO: catch some of the relevant exceptions and provide a pretty
  # error message if rmtree fails.

  return True


class HooksRunner(object):
  """Hook runner.

  This class is instantiated on the node side (ganeti-noded) and not on
  the master side.

  """
  RE_MASK = re.compile("^[a-zA-Z0-9_-]+$")

  def __init__(self, hooks_base_dir=None):
    """Constructor for hooks runner.

    Args:
      - hooks_base_dir: if not None, this overrides the
        constants.HOOKS_BASE_DIR (useful for unittests)
      - logs_base_dir: if not None, this overrides the
        constants.LOG_HOOKS_DIR (useful for unittests)
      - logging: enable or disable logging of script output

    """
    if hooks_base_dir is None:
      hooks_base_dir = constants.HOOKS_BASE_DIR
    self._BASE_DIR = hooks_base_dir

  @staticmethod
  def ExecHook(script, env):
    """Exec one hook script.

    Args:
     - phase: the phase
     - script: the full path to the script
     - env: the environment with which to exec the script

    """
    # exec the process using subprocess and log the output
    fdstdin = None
    try:
      fdstdin = open("/dev/null", "r")
      child = subprocess.Popen([script], stdin=fdstdin, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, close_fds=True,
                               shell=False, cwd="/",env=env)
      output = ""
      try:
        output = child.stdout.read(4096)
        child.stdout.close()
      except EnvironmentError, err:
        output += "Hook script error: %s" % str(err)

      while True:
        try:
          result = child.wait()
          break
        except EnvironmentError, err:
          if err.errno == errno.EINTR:
            continue
          raise
    finally:
      # try not to leak fds
      for fd in (fdstdin, ):
        if fd is not None:
          try:
            fd.close()
          except EnvironmentError, err:
            # just log the error
            #logger.Error("While closing fd %s: %s" % (fd, err))
            pass

    return result == 0, output

  def RunHooks(self, hpath, phase, env):
    """Run the scripts in the hooks directory.

    This method will not be usually overriden by child opcodes.

    """
    if phase == constants.HOOKS_PHASE_PRE:
      suffix = "pre"
    elif phase == constants.HOOKS_PHASE_POST:
      suffix = "post"
    else:
      raise errors.ProgrammerError, ("Unknown hooks phase: '%s'" % phase)
    rr = []

    subdir = "%s-%s.d" % (hpath, suffix)
    dir_name = "%s/%s" % (self._BASE_DIR, subdir)
    try:
      dir_contents = os.listdir(dir_name)
    except OSError, err:
      # must log
      return rr

    # we use the standard python sort order,
    # so 00name is the recommended naming scheme
    dir_contents.sort()
    for relname in dir_contents:
      fname = os.path.join(dir_name, relname)
      if not (os.path.isfile(fname) and os.access(fname, os.X_OK) and
          self.RE_MASK.match(relname) is not None):
        rrval = constants.HKR_SKIP
        output = ""
      else:
        result, output = self.ExecHook(fname, env)
        if not result:
          rrval = constants.HKR_FAIL
        else:
          rrval = constants.HKR_SUCCESS
      rr.append(("%s/%s" % (subdir, relname), rrval, output))

    return rr
