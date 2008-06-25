#
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
import random

from ganeti import logger
from ganeti import errors
from ganeti import utils
from ganeti import ssh
from ganeti import hypervisor
from ganeti import constants
from ganeti import bdev
from ganeti import objects
from ganeti import ssconf


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

  return True


def StopMaster():
  """Deactivate this node as master.

  This runs the master stop script.

  """
  result = utils.RunCmd([constants.MASTER_SCRIPT, "-d", "stop"])

  if result.failed:
    logger.Error("could not deactivate cluster interface with command %s,"
                 " error: '%s'" % (result.cmd, result.output))
    return False

  return True


def AddNode(dsa, dsapub, rsa, rsapub, sshkey, sshpub):
  """Joins this node to the cluster.

  This does the following:
      - updates the hostkeys of the machine (rsa and dsa)
      - adds the ssh private key to the user
      - adds the ssh public key to the users' authorized_keys file

  """
  sshd_keys =  [(constants.SSH_HOST_RSA_PRIV, rsa, 0600),
                (constants.SSH_HOST_RSA_PUB, rsapub, 0644),
                (constants.SSH_HOST_DSA_PRIV, dsa, 0600),
                (constants.SSH_HOST_DSA_PUB, dsapub, 0644)]
  for name, content, mode in sshd_keys:
    utils.WriteFile(name, data=content, mode=mode)

  try:
    priv_key, pub_key, auth_keys = ssh.GetUserFiles(constants.GANETI_RUNAS,
                                                    mkdir=True)
  except errors.OpExecError, err:
    logger.Error("Error while processing user ssh files: %s" % err)
    return False

  for name, content in [(priv_key, sshkey), (pub_key, sshpub)]:
    utils.WriteFile(name, data=content, mode=0600)

  utils.AddAuthorizedKey(auth_keys, sshpub)

  utils.RunCmd([constants.SSH_INITD_SCRIPT, "restart"])

  return True


def LeaveCluster():
  """Cleans up the current node and prepares it to be removed from the cluster.

  """
  if os.path.isdir(constants.DATA_DIR):
    for rel_name in utils.ListVisibleFiles(constants.DATA_DIR):
      full_name = os.path.join(constants.DATA_DIR, rel_name)
      if os.path.isfile(full_name) and not os.path.islink(full_name):
        utils.RemoveFile(full_name)

  try:
    priv_key, pub_key, auth_keys = ssh.GetUserFiles(constants.GANETI_RUNAS)
  except errors.OpExecError, err:
    logger.Error("Error while processing ssh files: %s" % err)
    return

  f = open(pub_key, 'r')
  try:
    utils.RemoveAuthorizedKey(auth_keys, f.read(8192))
  finally:
    f.close()

  utils.RemoveFile(priv_key)
  utils.RemoveFile(pub_key)


def GetNodeInfo(vgname):
  """Gives back a hash with different informations about the node.

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

  f = open("/proc/sys/kernel/random/boot_id", 'r')
  try:
    outputarray["bootid"] = f.read(128).rstrip("\n")
  finally:
    f.close()

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
    random.shuffle(what['nodelist'])
    for node in what['nodelist']:
      success, message = ssh.VerifyNodeHostname(node)
      if not success:
        result['nodelist'][node] = message
  if 'node-net-test' in what:
    result['node-net-test'] = {}
    my_name = utils.HostInfo().name
    my_pip = my_sip = None
    for name, pip, sip in what['node-net-test']:
      if name == my_name:
        my_pip = pip
        my_sip = sip
        break
    if not my_pip:
      result['node-net-test'][my_name] = ("Can't find my own"
                                          " primary/secondary IP"
                                          " in the node list")
    else:
      port = ssconf.SimpleStore().GetNodeDaemonPort()
      for name, pip, sip in what['node-net-test']:
        fail = []
        if not utils.TcpPing(pip, port, source=my_pip):
          fail.append("primary")
        if sip != pip:
          if not utils.TcpPing(sip, port, source=my_sip):
            fail.append("secondary")
        if fail:
          result['node-net-test'][name] = ("failure using the %s"
                                           " interface(s)" %
                                           " and ".join(fail))

  return result


def GetVolumeList(vg_name):
  """Compute list of logical volumes and their size.

  Returns:
    dictionary of all partions (key) with their size (in MiB), inactive
    and online status:
    {'test1': ('20.06', True, True)}

  """
  lvs = {}
  sep = '|'
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m", "--nosuffix",
                         "--separator=%s" % sep,
                         "-olv_name,lv_size,lv_attr", vg_name])
  if result.failed:
    logger.Error("Failed to list logical volumes, lvs output: %s" %
                 result.output)
    return result.output

  for line in result.stdout.splitlines():
    line = line.strip().rstrip(sep)
    name, size, attr = line.split(sep)
    if len(attr) != 6:
      attr = '------'
    inactive = attr[4] == '-'
    online = attr[5] == 'o'
    lvs[name] = (size, inactive, online)

  return lvs


def ListVolumeGroups():
  """List the volume groups and their size.

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

  return [map_line(line.split('|')) for line in result.stdout.splitlines()]


def BridgesExist(bridges_list):
  """Check if a list of bridges exist on the current node.

  Returns:
    True if all of them exist, false otherwise

  """
  for bridge in bridges_list:
    if not utils.BridgeExists(bridge):
      return False

  return True


def GetInstanceList():
  """Provides a list of instances.

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
  """Gives back the informations about an instance as a dictionary.

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


def GetInstanceMigratable(instance):
  """Gives whether an instance can be migrated.

  Args:
    instance - object representing the instance to be checked.

  Returns:
    (result, description)
      result - whether the instance can be migrated or not
      description - a description of the issue, if relevant

  """
  hyper = hypervisor.GetHypervisor()
  if instance.name not in hyper.ListInstances():
    return (False, 'not running')

  for disk in instance.disks:
    link_name = _GetBlockDevSymlinkPath(instance.name, disk.iv_name)
    if not os.path.islink(link_name):
      return (False, 'not restarted since ganeti 1.2.5')

  return (True, '')


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
    for name, inst_id, memory, vcpus, state, times in iinfo:
      output[name] = {
        'memory': memory,
        'vcpus': vcpus,
        'state': state,
        'time': times,
        }

  return output


def AddOSToInstance(instance, os_disk, swap_disk):
  """Add an OS to an instance.

  Args:
    instance: the instance object
    os_disk: the instance-visible name of the os device
    swap_disk: the instance-visible name of the swap device

  """
  inst_os = OSFromDisk(instance.os)

  create_script = inst_os.create_script

  os_device = instance.FindDisk(os_disk)
  if os_device is None:
    logger.Error("Can't find this device-visible name '%s'" % os_disk)
    return False

  swap_device = instance.FindDisk(swap_disk)
  if swap_device is None:
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

  command = utils.BuildShellCmd("cd %s && %s -i %s -b %s -s %s &>%s",
                                inst_os.path, create_script, instance.name,
                                real_os_dev.dev_path, real_swap_dev.dev_path,
                                logfile)

  result = utils.RunCmd(command)
  if result.failed:
    logger.Error("os create command '%s' returned error: %s, logfile: %s,"
                 " output: %s" %
                 (command, result.fail_reason, logfile, result.output))
    return False

  return True


def RunRenameInstance(instance, old_name, os_disk, swap_disk):
  """Run the OS rename script for an instance.

  Args:
    instance: the instance object
    old_name: the old name of the instance
    os_disk: the instance-visible name of the os device
    swap_disk: the instance-visible name of the swap device

  """
  inst_os = OSFromDisk(instance.os)

  script = inst_os.rename_script

  os_device = instance.FindDisk(os_disk)
  if os_device is None:
    logger.Error("Can't find this device-visible name '%s'" % os_disk)
    return False

  swap_device = instance.FindDisk(swap_disk)
  if swap_device is None:
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

  logfile = "%s/rename-%s-%s-%s-%d.log" % (constants.LOG_OS_DIR, instance.os,
                                           old_name,
                                           instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)

  command = utils.BuildShellCmd("cd %s && %s -o %s -n %s -b %s -s %s &>%s",
                                inst_os.path, script, old_name, instance.name,
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

  If an error occurs during gathering of data, we return the same dict
  with keys all set to None.

  """
  retdic = dict.fromkeys(["vg_size", "vg_free", "pv_count"])

  retval = utils.RunCmd(["vgs", "-ovg_size,vg_free,pv_count", "--noheadings",
                         "--nosuffix", "--units=m", "--separator=:", vg_name])

  if retval.failed:
    errmsg = "volume group %s not present" % vg_name
    logger.Error(errmsg)
    return retdic
  valarr = retval.stdout.strip().rstrip(':').split(':')
  if len(valarr) == 3:
    try:
      retdic = {
        "vg_size": int(round(float(valarr[0]), 0)),
        "vg_free": int(round(float(valarr[1]), 0)),
        "pv_count": int(valarr[2]),
        }
    except ValueError, err:
      logger.Error("Fail to parse vgs output: %s" % str(err))
  else:
    logger.Error("vgs output has the wrong number of fields (expected"
                 " three): %s" % str(valarr))
  return retdic


def _GetBlockDevSymlinkPath(instance_name, device_name):
  return os.path.join(constants.DISK_LINKS_DIR,
                      "%s:%s" % (instance_name, device_name))


def _SymlinkBlockDev(instance_name, device_path, device_name):
  """Set up symlinks to a instance's block device.

  This is an auxiliary function run when an instance is start (on the primary
  node) or when an instance is migrated (on the target node).

  Args:
    instance_name: the name of the target instance
    device_path: path of the physical block device, on the node
    device_name: 'virtual' name of the device

  Returns:
    absolute path to the disk's symlink

  """
  link_name = _GetBlockDevSymlinkPath(instance_name, device_name)
  try:
    os.symlink(device_path, link_name)
  except OSError, err:
    if err.errno == errno.EEXIST:
      if (not os.path.islink(link_name) or
          os.readlink(link_name) != device_path):
        os.remove(link_name)
        os.symlink(device_path, link_name)
    else:
      raise

  return link_name


def _RemoveBlockDevLinks(instance_name, disks):
  """Remove the block device symlinks belonging to the given instance.

  """
  for disk in disks:
    link_name = _GetBlockDevSymlinkPath(instance_name, disk.iv_name)
    if os.path.islink(link_name):
      try:
        os.remove(link_name)
      except OSError, err:
        logger.Error("Can't remove symlink '%s': %s" % (link_name, err))


def _GatherAndLinkBlockDevs(instance):
  """Set up an instance's block device(s).

  This is run on the primary node at instance startup. The block
  devices must be already assembled.

  Returns:
    A list of (block_device, disk_name) tuples.

  """
  block_devices = []
  for disk in instance.disks:
    device = _RecursiveFindBD(disk)
    if device is None:
      raise errors.BlockDeviceError("Block device '%s' is not set up." %
                                    str(disk))
    device.Open()
    try:
      link_name = _SymlinkBlockDev(instance.name, device.dev_path,
                                   disk.iv_name)
    except OSError, e:
      raise errors.BlockDeviceError("Cannot create block device symlink: %s" %
                                    e.strerror)

    block_devices.append((link_name, disk.iv_name))

  return block_devices


def StartInstance(instance, extra_args):
  """Start an instance.

  Args:
    instance - object representing the instance to be started.

  """
  running_instances = GetInstanceList()

  if instance.name in running_instances:
    return True

  try:
    block_devices = _GatherAndLinkBlockDevs(instance)
    hyper = hypervisor.GetHypervisor()
    hyper.StartInstance(instance, block_devices, extra_args)
  except errors.BlockDeviceError, err:
    logger.Error("Failed to start instance: %s" % err)
    return False
  except errors.HypervisorError, err:
    logger.Error("Failed to start instance: %s" % err)
    _RemoveBlockDevLinks(instance.name, instance.disks)
    return False

  return True


def ShutdownInstance(instance):
  """Shut an instance down.

  Args:
    instance - object representing the instance to be shutdown.

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

  _RemoveBlockDevLinks(instance.name, instance.disks)

  return True


def RebootInstance(instance, reboot_type, extra_args):
  """Reboot an instance.

  Args:
    instance    - object representing the instance to be reboot.
    reboot_type - how to reboot [soft,hard,full]

  """
  running_instances = GetInstanceList()

  if instance.name not in running_instances:
    logger.Error("Cannot reboot instance that is not running")
    return False

  hyper = hypervisor.GetHypervisor()
  if reboot_type == constants.INSTANCE_REBOOT_SOFT:
    try:
      hyper.RebootInstance(instance)
    except errors.HypervisorError, err:
      logger.Error("Failed to soft reboot instance: %s" % err)
      return False
  elif reboot_type == constants.INSTANCE_REBOOT_HARD:
    try:
      ShutdownInstance(instance)
      StartInstance(instance, extra_args)
    except errors.HypervisorError, err:
      logger.Error("Failed to hard reboot instance: %s" % err)
      return False
  else:
    raise errors.ParameterError("reboot_type invalid")


  return True


def MigrateInstance(instance, target, live):
  """Migrates an instance to another node.

  Args:
    instance - name of the instance to be migrated.
    target   - node to send the instance to.
    live     - whether to perform a live migration.

  """
  hyper = hypervisor.GetHypervisor()

  try:
    hyper.MigrateInstance(instance, target, live)
  except errors.HypervisorError, err:
    msg = str(err)
    logger.Error(msg)
    return (False, msg)
  return (True, "Migration successfull")


def CreateBlockDevice(disk, size, owner, on_primary, info):
  """Creates a block device for an instance.

  Args:
   disk: a ganeti.objects.Disk object
   size: the size of the physical underlying device
   owner: a string with the name of the instance
   on_primary: a boolean indicating if it is the primary node or not
   info: string that will be sent to the physical device creation

  Returns:
    the new unique_id of the device (this can sometime be
    computed only after creation), or None. On secondary nodes,
    it's not required to return anything.

  """
  clist = []
  if disk.children:
    for child in disk.children:
      crdev = _RecursiveAssembleBD(child, owner, on_primary)
      if on_primary or disk.AssembleOnSecondary():
        # we need the children open in case the device itself has to
        # be assembled
        crdev.Open()
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
    if not device.Assemble():
      errorstring = "Can't assemble device after creation"
      logger.Error(errorstring)
      raise errors.BlockDeviceError("%s, very unusual event - check the node"
                                    " daemon logs" % errorstring)
    device.SetSyncSpeed(constants.SYNC_SPEED)
    if on_primary or disk.OpenOnSecondary():
      device.Open(force=True)
    DevCacheManager.UpdateCache(device.dev_path, owner,
                                on_primary, disk.iv_name)

  device.SetInfo(info)

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
    r_path = rdev.dev_path
    result = rdev.Remove()
    if result:
      DevCacheManager.RemoveCache(r_path)
  else:
    result = True
  if disk.children:
    for child in disk.children:
      result = result and RemoveBlockDevice(child)
  return result


def _RecursiveAssembleBD(disk, owner, as_primary):
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
    mcn = disk.ChildrenNeeded()
    if mcn == -1:
      mcn = 0 # max number of Nones allowed
    else:
      mcn = len(disk.children) - mcn # max number of Nones
    for chld_disk in disk.children:
      try:
        cdev = _RecursiveAssembleBD(chld_disk, owner, as_primary)
      except errors.BlockDeviceError, err:
        if children.count(None) >= mcn:
          raise
        cdev = None
        logger.Debug("Error in child activation: %s" % str(err))
      children.append(cdev)

  if as_primary or disk.AssembleOnSecondary():
    r_dev = bdev.AttachOrAssemble(disk.dev_type, disk.physical_id, children)
    r_dev.SetSyncSpeed(constants.SYNC_SPEED)
    result = r_dev
    if as_primary or disk.OpenOnSecondary():
      r_dev.Open()
    DevCacheManager.UpdateCache(r_dev.dev_path, owner,
                                as_primary, disk.iv_name)

  else:
    result = True
  return result


def AssembleBlockDevice(disk, owner, as_primary):
  """Activate a block device for an instance.

  This is a wrapper over _RecursiveAssembleBD.

  Returns:
    a /dev path for primary nodes
    True for secondary nodes

  """
  result = _RecursiveAssembleBD(disk, owner, as_primary)
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
    r_path = r_dev.dev_path
    result = r_dev.Shutdown()
    if result:
      DevCacheManager.RemoveCache(r_path)
  else:
    result = True
  if disk.children:
    for child in disk.children:
      result = result and ShutdownBlockDevice(child)
  return result


def MirrorAddChildren(parent_cdev, new_cdevs):
  """Extend a mirrored block device.

  """
  parent_bdev = _RecursiveFindBD(parent_cdev, allow_partial=True)
  if parent_bdev is None:
    logger.Error("Can't find parent device")
    return False
  new_bdevs = [_RecursiveFindBD(disk) for disk in new_cdevs]
  if new_bdevs.count(None) > 0:
    logger.Error("Can't find new device(s) to add: %s:%s" %
                 (new_bdevs, new_cdevs))
    return False
  parent_bdev.AddChildren(new_bdevs)
  return True


def MirrorRemoveChildren(parent_cdev, new_cdevs):
  """Shrink a mirrored block device.

  """
  parent_bdev = _RecursiveFindBD(parent_cdev)
  if parent_bdev is None:
    logger.Error("Can't find parent in remove children: %s" % parent_cdev)
    return False
  devs = []
  for disk in new_cdevs:
    rpath = disk.StaticDevPath()
    if rpath is None:
      bd = _RecursiveFindBD(disk)
      if bd is None:
        logger.Error("Can't find dynamic device %s while removing children" %
                     disk)
        return False
      else:
        devs.append(bd.dev_path)
    else:
      devs.append(rpath)
  parent_bdev.RemoveChildren(devs)
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
      raise errors.BlockDeviceError("Can't find device %s" % str(dsk))
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
  return (rbd.dev_path, rbd.major, rbd.minor) + rbd.GetSyncStatus()


def UploadFile(file_name, data, mode, uid, gid, atime, mtime):
  """Write a file to the filesystem.

  This allows the master to overwrite(!) a file. It will only perform
  the operation if the file belongs to a list of configuration files.

  """
  if not os.path.isabs(file_name):
    logger.Error("Filename passed to UploadFile is not absolute: '%s'" %
                 file_name)
    return False

  allowed_files = [
    constants.CLUSTER_CONF_FILE,
    constants.ETC_HOSTS,
    constants.SSH_KNOWN_HOSTS_FILE,
    ]
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


def _OSOndiskVersion(name, os_dir):
  """Compute and return the API version of a given OS.

  This function will try to read the API version of the os given by
  the 'name' parameter and residing in the 'os_dir' directory.

  Return value will be either an integer denoting the version or None in the
  case when this is not a valid OS name.

  """
  api_file = os.path.sep.join([os_dir, "ganeti_api_version"])

  try:
    st = os.stat(api_file)
  except EnvironmentError, err:
    raise errors.InvalidOS(name, os_dir, "'ganeti_api_version' file not"
                           " found (%s)" % _ErrnoOrStr(err))

  if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
    raise errors.InvalidOS(name, os_dir, "'ganeti_api_version' file is not"
                           " a regular file")

  try:
    f = open(api_file)
    try:
      api_version = f.read(256)
    finally:
      f.close()
  except EnvironmentError, err:
    raise errors.InvalidOS(name, os_dir, "error while reading the"
                           " API version (%s)" % _ErrnoOrStr(err))

  api_version = api_version.strip()
  try:
    api_version = int(api_version)
  except (TypeError, ValueError), err:
    raise errors.InvalidOS(name, os_dir,
                           "API version is not integer (%s)" % str(err))

  return api_version


def DiagnoseOS(top_dirs=None):
  """Compute the validity for all OSes.

  Returns an OS object for each name in all the given top directories
  (if not given defaults to constants.OS_SEARCH_PATH)

  Returns:
    list of OS objects

  """
  if top_dirs is None:
    top_dirs = constants.OS_SEARCH_PATH

  result = []
  for dir_name in top_dirs:
    if os.path.isdir(dir_name):
      try:
        f_names = utils.ListVisibleFiles(dir_name)
      except EnvironmentError, err:
        logger.Error("Can't list the OS directory %s: %s" %
                     (dir_name, str(err)))
        break
      for name in f_names:
        try:
          os_inst = OSFromDisk(name, base_dir=dir_name)
          result.append(os_inst)
        except errors.InvalidOS, err:
          result.append(objects.OS.FromInvalidOS(err))

  return result


def OSFromDisk(name, base_dir=None):
  """Create an OS instance from disk.

  This function will return an OS instance if the given name is a
  valid OS name. Otherwise, it will raise an appropriate
  `errors.InvalidOS` exception, detailing why this is not a valid
  OS.

  Args:
    os_dir: Directory containing the OS scripts. Defaults to a search
            in all the OS_SEARCH_PATH directories.

  """

  if base_dir is None:
    os_dir = utils.FindFile(name, constants.OS_SEARCH_PATH, os.path.isdir)
    if os_dir is None:
      raise errors.InvalidOS(name, None, "OS dir not found in search path")
  else:
    os_dir = os.path.sep.join([base_dir, name])

  api_version = _OSOndiskVersion(name, os_dir)

  if api_version != constants.OS_API_VERSION:
    raise errors.InvalidOS(name, os_dir, "API version mismatch"
                           " (found %s want %s)"
                           % (api_version, constants.OS_API_VERSION))

  # OS Scripts dictionary, we will populate it with the actual script names
  os_scripts = {'create': '', 'export': '', 'import': '', 'rename': ''}

  for script in os_scripts:
    os_scripts[script] = os.path.sep.join([os_dir, script])

    try:
      st = os.stat(os_scripts[script])
    except EnvironmentError, err:
      raise errors.InvalidOS(name, os_dir, "'%s' script missing (%s)" %
                             (script, _ErrnoOrStr(err)))

    if stat.S_IMODE(st.st_mode) & stat.S_IXUSR != stat.S_IXUSR:
      raise errors.InvalidOS(name, os_dir, "'%s' script not executable" %
                             script)

    if not stat.S_ISREG(stat.S_IFMT(st.st_mode)):
      raise errors.InvalidOS(name, os_dir, "'%s' is not a regular file" %
                             script)


  return objects.OS(name=name, path=os_dir, status=constants.OS_VALID_STATUS,
                    create_script=os_scripts['create'],
                    export_script=os_scripts['export'],
                    import_script=os_scripts['import'],
                    rename_script=os_scripts['rename'],
                    api_version=api_version)


def GrowBlockDevice(disk, amount):
  """Grow a stack of block devices.

  This function is called recursively, with the childrens being the
  first one resize.

  Args:
    disk: the disk to be grown

  Returns: a tuple of (status, result), with:
    status: the result (true/false) of the operation
    result: the error message if the operation failed, otherwise not used

  """
  r_dev = _RecursiveFindBD(disk)
  if r_dev is None:
    return False, "Cannot find block device %s" % (disk,)

  try:
    r_dev.Grow(amount)
  except errors.BlockDeviceError, err:
    return False, str(err)

  return True, None


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
  elif disk.dev_type == constants.LD_LV:
    r_dev = _RecursiveFindBD(disk)
    if r_dev is not None:
      # let's stay on the safe side and ask for the full size, for now
      return r_dev.Snapshot(disk.size)
    else:
      return None
  else:
    raise errors.ProgrammerError("Cannot snapshot non-lvm block device"
                                 " '%s' of type '%s'" %
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

  destcmd = utils.BuildShellCmd("mkdir -p %s && cat > %s/%s",
                                destdir, destdir, destfile)
  remotecmd = ssh.BuildSSHCmd(dest_node, constants.GANETI_RUNAS, destcmd)



  # all commands have been checked, so we're safe to combine them
  command = '|'.join([expcmd, comprcmd, utils.ShellQuoteArgs(remotecmd)])

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
    config.set(constants.INISECT_INS, 'nic%d_bridge' % nic_count,
               '%s' % nic.bridge)
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

  os_device = instance.FindDisk(os_disk)
  if os_device is None:
    logger.Error("Can't find this device-visible name '%s'" % os_disk)
    return False

  swap_device = instance.FindDisk(swap_disk)
  if swap_device is None:
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

  logfile = "%s/import-%s-%s-%s.log" % (constants.LOG_OS_DIR, instance.os,
                                        instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)

  destcmd = utils.BuildShellCmd('cat %s', src_image)
  remotecmd = ssh.BuildSSHCmd(src_node, constants.GANETI_RUNAS, destcmd)

  comprcmd = "gunzip"
  impcmd = utils.BuildShellCmd("(cd %s; %s -i %s -b %s -s %s &>%s)",
                               inst_os.path, import_script, instance.name,
                               real_os_dev.dev_path, real_swap_dev.dev_path,
                               logfile)

  command = '|'.join([utils.ShellQuoteArgs(remotecmd), comprcmd, impcmd])

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
    return utils.ListVisibleFiles(constants.EXPORT_DIR)
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


def RenameBlockDevices(devlist):
  """Rename a list of block devices.

  The devlist argument is a list of tuples (disk, new_logical,
  new_physical). The return value will be a combined boolean result
  (True only if all renames succeeded).

  """
  result = True
  for disk, unique_id in devlist:
    dev = _RecursiveFindBD(disk)
    if dev is None:
      result = False
      continue
    try:
      old_rpath = dev.dev_path
      dev.Rename(unique_id)
      new_rpath = dev.dev_path
      if old_rpath != new_rpath:
        DevCacheManager.RemoveCache(old_rpath)
        # FIXME: we should add the new cache information here, like:
        # DevCacheManager.UpdateCache(new_rpath, owner, ...)
        # but we don't have the owner here - maybe parse from existing
        # cache? for now, we only lose lvm data when we rename, which
        # is less critical than DRBD or MD
    except errors.BlockDeviceError, err:
      logger.Error("Can't rename device '%s' to '%s': %s" %
                   (dev, unique_id, err))
      result = False
  return result


def CloseBlockDevices(instance_name, disks):
  """Closes the given block devices.

  This means they will be switched to secondary mode (in case of DRBD).

  Args:
    - instance_name: if the argument is not false, then the symlinks
                     belonging to the instance are removed, in order
                     to keep only the 'active' devices symlinked
    - disks: a list of objects.Disk instances

  """
  bdevs = []
  for cf in disks:
    rd = _RecursiveFindBD(cf)
    if rd is None:
      return (False, "Can't find device %s" % cf)
    bdevs.append(rd)

  msg = []
  for rd in bdevs:
    try:
      rd.Close()
    except errors.BlockDeviceError, err:
      msg.append(str(err))
  if instance_name:
    _RemoveBlockDevLinks(instance_name, disks)
  if msg:
    return (False, "Can't make devices secondary: %s" % ",".join(msg))
  else:
    return (True, "All devices secondary")


def DrbdReconfigNet(instance_name, disks, nodes_ip, multimaster):
  """Tune the network settings on a list of drbd devices.

  """
  my_name = utils.HostInfo().name
  bdevs = []
  for cf in disks:
    cf.SetPhysicalID(my_name, nodes_ip)
    rd = _RecursiveFindBD(cf)
    if rd is None:
      return (False, "Can't find device %s" % cf)
    if multimaster:
      try:
        _SymlinkBlockDev(instance_name, rd.dev_path, cf.iv_name)
      except EnvironmentError, err:
        return (False, "Can't create symlink: %s" % str(err))
    bdevs.append(rd)

  # switch to new master configuration and if needed primary mode
  for rd in bdevs:
    rd.ReAttachNet(multimaster)
  # wait until the disks are connected; we need to retry the re-attach
  # if the device becomes standalone, as this might happen if the one
  # node disconnects and reconnects in a different mode before the
  # other node reconnects; in this case, one or both of the nodes will
  # decide it has wrong configuration and switch to standalone
  RECONNECT_TIMEOUT = 2 * 60
  timeout_limit = time.time() + RECONNECT_TIMEOUT
  notyet = True
  while notyet and time.time() < timeout_limit:
    notyet = False
    for rd in bdevs:
      stats = rd.GetProcStatus()
      if not (stats.is_connected or stats.is_in_resync):
        notyet = True
      if stats.is_standalone:
        # peer had different config info and this node became standalone
        rd.ReAttachNet(multimaster)
    if not notyet:
      break
    time.sleep(5)
  if notyet:
    return (False, "Timeout in disk reconnecting")
  if multimaster:
    # change to primary mode
    for rd in bdevs:
      rd.Open()
  if multimaster:
    msg = "multi-master and primary"
  else:
    msg = "single-master"
  return (True, "Disks are now configured as %s" % msg)


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

    """
    if hooks_base_dir is None:
      hooks_base_dir = constants.HOOKS_BASE_DIR
    self._BASE_DIR = hooks_base_dir

  @staticmethod
  def ExecHook(script, env):
    """Exec one hook script.

    Args:
     - script: the full path to the script
     - env: the environment with which to exec the script

    """
    # exec the process using subprocess and log the output
    fdstdin = None
    try:
      fdstdin = open("/dev/null", "r")
      child = subprocess.Popen([script], stdin=fdstdin, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, close_fds=True,
                               shell=False, cwd="/", env=env)
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
      raise errors.ProgrammerError("Unknown hooks phase: '%s'" % phase)
    rr = []

    subdir = "%s-%s.d" % (hpath, suffix)
    dir_name = "%s/%s" % (self._BASE_DIR, subdir)
    try:
      dir_contents = utils.ListVisibleFiles(dir_name)
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


class IAllocatorRunner(object):
  """IAllocator runner.

  This class is instantiated on the node side (ganeti-noded) and not on
  the master side.

  """
  def Run(self, name, idata):
    """Run an iallocator script.

    Return value: tuple of:
       - run status (one of the IARUN_ constants)
       - stdout
       - stderr
       - fail reason (as from utils.RunResult)

    """
    alloc_script = utils.FindFile(name, constants.IALLOCATOR_SEARCH_PATH,
                                  os.path.isfile)
    if alloc_script is None:
      return (constants.IARUN_NOTFOUND, None, None, None)

    fd, fin_name = tempfile.mkstemp(prefix="ganeti-iallocator.")
    try:
      os.write(fd, idata)
      os.close(fd)
      result = utils.RunCmd([alloc_script, fin_name])
      if result.failed:
        return (constants.IARUN_FAILURE, result.stdout, result.stderr,
                result.fail_reason)
    finally:
      os.unlink(fin_name)

    return (constants.IARUN_SUCCESS, result.stdout, result.stderr, None)


class DevCacheManager(object):
  """Simple class for managing a cache of block device information.

  """
  _DEV_PREFIX = "/dev/"
  _ROOT_DIR = constants.BDEV_CACHE_DIR

  @classmethod
  def _ConvertPath(cls, dev_path):
    """Converts a /dev/name path to the cache file name.

    This replaces slashes with underscores and strips the /dev
    prefix. It then returns the full path to the cache file

    """
    if dev_path.startswith(cls._DEV_PREFIX):
      dev_path = dev_path[len(cls._DEV_PREFIX):]
    dev_path = dev_path.replace("/", "_")
    fpath = "%s/bdev_%s" % (cls._ROOT_DIR, dev_path)
    return fpath

  @classmethod
  def UpdateCache(cls, dev_path, owner, on_primary, iv_name):
    """Updates the cache information for a given device.

    """
    if dev_path is None:
      logger.Error("DevCacheManager.UpdateCache got a None dev_path")
      return
    fpath = cls._ConvertPath(dev_path)
    if on_primary:
      state = "primary"
    else:
      state = "secondary"
    if iv_name is None:
      iv_name = "not_visible"
    fdata = "%s %s %s\n" % (str(owner), state, iv_name)
    try:
      utils.WriteFile(fpath, data=fdata)
    except EnvironmentError, err:
      logger.Error("Can't update bdev cache for %s, error %s" %
                   (dev_path, str(err)))

  @classmethod
  def RemoveCache(cls, dev_path):
    """Remove data for a dev_path.

    """
    if dev_path is None:
      logger.Error("DevCacheManager.RemoveCache got a None dev_path")
      return
    fpath = cls._ConvertPath(dev_path)
    try:
      utils.RemoveFile(fpath)
    except EnvironmentError, err:
      logger.Error("Can't update bdev cache for %s, error %s" %
                   (dev_path, str(err)))
