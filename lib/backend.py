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
import stat
import errno
import re
import subprocess
import random
import logging
import tempfile

from ganeti import errors
from ganeti import utils
from ganeti import ssh
from ganeti import hypervisor
from ganeti import constants
from ganeti import bdev
from ganeti import objects
from ganeti import ssconf


def _GetConfig():
  """Simple wrapper to return a ConfigReader.

  @rtype: L{ssconf.SimpleConfigReader}
  @return: a SimpleConfigReader instance

  """
  return ssconf.SimpleConfigReader()


def _GetSshRunner(cluster_name):
  """Simple wrapper to return an SshRunner.

  @type cluster_name: str
  @param cluster_name: the cluster name, which is needed
      by the SshRunner constructor
  @rtype: L{ssh.SshRunner}
  @return: an SshRunner instance

  """
  return ssh.SshRunner(cluster_name)


def _CleanDirectory(path, exclude=[]):
  """Removes all regular files in a directory.

  @type path: str
  @param path: the directory to clean
  @type exclude: list
  @param exclude: list of files to be excluded, defaults
      to the empty list
  @rtype: None

  """
  if not os.path.isdir(path):
    return

  # Normalize excluded paths
  exclude = [os.path.normpath(i) for i in exclude]

  for rel_name in utils.ListVisibleFiles(path):
    full_name = os.path.normpath(os.path.join(path, rel_name))
    if full_name in exclude:
      continue
    if os.path.isfile(full_name) and not os.path.islink(full_name):
      utils.RemoveFile(full_name)


def JobQueuePurge():
  """Removes job queue files and archived jobs.

  @rtype: None

  """
  _CleanDirectory(constants.QUEUE_DIR, exclude=[constants.JOB_QUEUE_LOCK_FILE])
  _CleanDirectory(constants.JOB_QUEUE_ARCHIVE_DIR)


def GetMasterInfo():
  """Returns master information.

  This is an utility function to compute master information, either
  for consumption here or from the node daemon.

  @rtype: tuple
  @return: (master_netdev, master_ip, master_name) if we have a good
      configuration, otherwise (None, None, None)

  """
  try:
    cfg = _GetConfig()
    master_netdev = cfg.GetMasterNetdev()
    master_ip = cfg.GetMasterIP()
    master_node = cfg.GetMasterNode()
  except errors.ConfigurationError, err:
    logging.exception("Cluster configuration incomplete")
    return (None, None, None)
  return (master_netdev, master_ip, master_node)


def StartMaster(start_daemons):
  """Activate local node as master node.

  The function will always try activate the IP address of the master
  (unless someone else has it). It will also start the master daemons,
  based on the start_daemons parameter.

  @type start_daemons: boolean
  @param start_daemons: whther to also start the master
      daemons (ganeti-masterd and ganeti-rapi)
  @rtype: None

  """
  ok = True
  master_netdev, master_ip, _ = GetMasterInfo()
  if not master_netdev:
    return False

  if utils.TcpPing(master_ip, constants.DEFAULT_NODED_PORT):
    if utils.OwnIpAddress(master_ip):
      # we already have the ip:
      logging.debug("Already started")
    else:
      logging.error("Someone else has the master ip, not activating")
      ok = False
  else:
    result = utils.RunCmd(["ip", "address", "add", "%s/32" % master_ip,
                           "dev", master_netdev, "label",
                           "%s:0" % master_netdev])
    if result.failed:
      logging.error("Can't activate master IP: %s", result.output)
      ok = False

    result = utils.RunCmd(["arping", "-q", "-U", "-c 3", "-I", master_netdev,
                           "-s", master_ip, master_ip])
    # we'll ignore the exit code of arping

  # and now start the master and rapi daemons
  if start_daemons:
    for daemon in 'ganeti-masterd', 'ganeti-rapi':
      result = utils.RunCmd([daemon])
      if result.failed:
        logging.error("Can't start daemon %s: %s", daemon, result.output)
        ok = False
  return ok


def StopMaster(stop_daemons):
  """Deactivate this node as master.

  The function will always try to deactivate the IP address of the
  master. It will also stop the master daemons depending on the
  stop_daemons parameter.

  @type stop_daemons: boolean
  @param stop_daemons: whether to also stop the master daemons
      (ganeti-masterd and ganeti-rapi)
  @rtype: None

  """
  master_netdev, master_ip, _ = GetMasterInfo()
  if not master_netdev:
    return False

  result = utils.RunCmd(["ip", "address", "del", "%s/32" % master_ip,
                         "dev", master_netdev])
  if result.failed:
    logging.error("Can't remove the master IP, error: %s", result.output)
    # but otherwise ignore the failure

  if stop_daemons:
    # stop/kill the rapi and the master daemon
    for daemon in constants.RAPI_PID, constants.MASTERD_PID:
      utils.KillProcess(utils.ReadPidFile(utils.DaemonPidFileName(daemon)))

  return True


def AddNode(dsa, dsapub, rsa, rsapub, sshkey, sshpub):
  """Joins this node to the cluster.

  This does the following:
      - updates the hostkeys of the machine (rsa and dsa)
      - adds the ssh private key to the user
      - adds the ssh public key to the users' authorized_keys file

  @type dsa: str
  @param dsa: the DSA private key to write
  @type dsapub: str
  @param dsapub: the DSA public key to write
  @type rsa: str
  @param rsa: the RSA private key to write
  @type rsapub: str
  @param rsapub: the RSA public key to write
  @type sshkey: str
  @param sshkey: the SSH private key to write
  @type sshpub: str
  @param sshpub: the SSH public key to write
  @rtype: boolean
  @return: the success of the operation

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
    logging.exception("Error while processing user ssh files")
    return False

  for name, content in [(priv_key, sshkey), (pub_key, sshpub)]:
    utils.WriteFile(name, data=content, mode=0600)

  utils.AddAuthorizedKey(auth_keys, sshpub)

  utils.RunCmd([constants.SSH_INITD_SCRIPT, "restart"])

  return True


def LeaveCluster():
  """Cleans up and remove the current node.

  This function cleans up and prepares the current node to be removed
  from the cluster.

  If processing is successful, then it raises an
  L{errors.GanetiQuitException} which is used as a special case to
  shutdown the node daemon.

  """
  _CleanDirectory(constants.DATA_DIR)
  JobQueuePurge()

  try:
    priv_key, pub_key, auth_keys = ssh.GetUserFiles(constants.GANETI_RUNAS)
  except errors.OpExecError:
    logging.exception("Error while processing ssh files")
    return

  f = open(pub_key, 'r')
  try:
    utils.RemoveAuthorizedKey(auth_keys, f.read(8192))
  finally:
    f.close()

  utils.RemoveFile(priv_key)
  utils.RemoveFile(pub_key)

  # Return a reassuring string to the caller, and quit
  raise errors.QuitGanetiException(False, 'Shutdown scheduled')


def GetNodeInfo(vgname, hypervisor_type):
  """Gives back a hash with different informations about the node.

  @type vgname: C{string}
  @param vgname: the name of the volume group to ask for disk space information
  @type hypervisor_type: C{str}
  @param hypervisor_type: the name of the hypervisor to ask for
      memory information
  @rtype: C{dict}
  @return: dictionary with the following keys:
      - vg_size is the size of the configured volume group in MiB
      - vg_free is the free size of the volume group in MiB
      - memory_dom0 is the memory allocated for domain0 in MiB
      - memory_free is the currently available (free) ram in MiB
      - memory_total is the total number of ram in MiB

  """
  outputarray = {}
  vginfo = _GetVGInfo(vgname)
  outputarray['vg_size'] = vginfo['vg_size']
  outputarray['vg_free'] = vginfo['vg_free']

  hyper = hypervisor.GetHypervisor(hypervisor_type)
  hyp_info = hyper.GetNodeInfo()
  if hyp_info is not None:
    outputarray.update(hyp_info)

  f = open("/proc/sys/kernel/random/boot_id", 'r')
  try:
    outputarray["bootid"] = f.read(128).rstrip("\n")
  finally:
    f.close()

  return outputarray


def VerifyNode(what, cluster_name):
  """Verify the status of the local node.

  Based on the input L{what} parameter, various checks are done on the
  local node.

  If the I{filelist} key is present, this list of
  files is checksummed and the file/checksum pairs are returned.

  If the I{nodelist} key is present, we check that we have
  connectivity via ssh with the target nodes (and check the hostname
  report).

  If the I{node-net-test} key is present, we check that we have
  connectivity to the given nodes via both primary IP and, if
  applicable, secondary IPs.

  @type what: C{dict}
  @param what: a dictionary of things to check:
      - filelist: list of files for which to compute checksums
      - nodelist: list of nodes we should check ssh communication with
      - node-net-test: list of nodes we should check node daemon port
        connectivity with
      - hypervisor: list with hypervisors to run the verify for
  @rtype: dict
  @return: a dictionary with the same keys as the input dict, and
      values representing the result of the checks

  """
  result = {}

  if 'hypervisor' in what:
    result['hypervisor'] = my_dict = {}
    for hv_name in what['hypervisor']:
      my_dict[hv_name] = hypervisor.GetHypervisor(hv_name).Verify()

  if 'filelist' in what:
    result['filelist'] = utils.FingerprintFiles(what['filelist'])

  if 'nodelist' in what:
    result['nodelist'] = {}
    random.shuffle(what['nodelist'])
    for node in what['nodelist']:
      success, message = _GetSshRunner(cluster_name).VerifyNodeHostname(node)
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
      port = utils.GetNodeDaemonPort()
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

  @type vg_name: str
  @param vg_name: the volume group whose LVs we should list
  @rtype: dict
  @return:
      dictionary of all partions (key) with value being a tuple of
      their size (in MiB), inactive and online status::

        {'test1': ('20.06', True, True)}

      in case of errors, a string is returned with the error
      details.

  """
  lvs = {}
  sep = '|'
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m", "--nosuffix",
                         "--separator=%s" % sep,
                         "-olv_name,lv_size,lv_attr", vg_name])
  if result.failed:
    logging.error("Failed to list logical volumes, lvs output: %s",
                  result.output)
    return result.output

  valid_line_re = re.compile("^ *([^|]+)\|([0-9.]+)\|([^|]{6})\|?$")
  for line in result.stdout.splitlines():
    line = line.strip()
    match = valid_line_re.match(line)
    if not match:
      logging.error("Invalid line returned from lvs output: '%s'", line)
      continue
    name, size, attr = match.groups()
    inactive = attr[4] == '-'
    online = attr[5] == 'o'
    lvs[name] = (size, inactive, online)

  return lvs


def ListVolumeGroups():
  """List the volume groups and their size.

  @rtype: dict
  @return: dictionary with keys volume name and values the
      size of the volume

  """
  return utils.ListVolumeGroups()


def NodeVolumes():
  """List all volumes on this node.

  @rtype: list
  @return:
    A list of dictionaries, each having four keys:
      - name: the logical volume name,
      - size: the size of the logical volume
      - dev: the physical device on which the LV lives
      - vg: the volume group to which it belongs

    In case of errors, we return an empty list and log the
    error.

    Note that since a logical volume can live on multiple physical
    volumes, the resulting list might include a logical volume
    multiple times.

  """
  result = utils.RunCmd(["lvs", "--noheadings", "--units=m", "--nosuffix",
                         "--separator=|",
                         "--options=lv_name,lv_size,devices,vg_name"])
  if result.failed:
    logging.error("Failed to list logical volumes, lvs output: %s",
                  result.output)
    return []

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

  return [map_line(line.split('|')) for line in result.stdout.splitlines()
          if line.count('|') >= 3]


def BridgesExist(bridges_list):
  """Check if a list of bridges exist on the current node.

  @rtype: boolean
  @return: C{True} if all of them exist, C{False} otherwise

  """
  for bridge in bridges_list:
    if not utils.BridgeExists(bridge):
      return False

  return True


def GetInstanceList(hypervisor_list):
  """Provides a list of instances.

  @type hypervisor_list: list
  @param hypervisor_list: the list of hypervisors to query information

  @rtype: list
  @return: a list of all running instances on the current node
    - instance1.example.com
    - instance2.example.com

  """
  results = []
  for hname in hypervisor_list:
    try:
      names = hypervisor.GetHypervisor(hname).ListInstances()
      results.extend(names)
    except errors.HypervisorError, err:
      logging.exception("Error enumerating instances for hypevisor %s", hname)
      # FIXME: should we somehow not propagate this to the master?
      raise

  return results


def GetInstanceInfo(instance, hname):
  """Gives back the informations about an instance as a dictionary.

  @type instance: string
  @param instance: the instance name
  @type hname: string
  @param hname: the hypervisor type of the instance

  @rtype: dict
  @return: dictionary with the following keys:
      - memory: memory size of instance (int)
      - state: xen state of instance (string)
      - time: cpu time of instance (float)

  """
  output = {}

  iinfo = hypervisor.GetHypervisor(hname).GetInstanceInfo(instance)
  if iinfo is not None:
    output['memory'] = iinfo[2]
    output['state'] = iinfo[4]
    output['time'] = iinfo[5]

  return output


def GetAllInstancesInfo(hypervisor_list):
  """Gather data about all instances.

  This is the equivalent of L{GetInstanceInfo}, except that it
  computes data for all instances at once, thus being faster if one
  needs data about more than one instance.

  @type hypervisor_list: list
  @param hypervisor_list: list of hypervisors to query for instance data

  @rtype: dict of dicts
  @return: dictionary of instance: data, with data having the following keys:
      - memory: memory size of instance (int)
      - state: xen state of instance (string)
      - time: cpu time of instance (float)
      - vcpus: the number of vcpus

  """
  output = {}

  for hname in hypervisor_list:
    iinfo = hypervisor.GetHypervisor(hname).GetAllInstancesInfo()
    if iinfo:
      for name, inst_id, memory, vcpus, state, times in iinfo:
        value = {
          'memory': memory,
          'vcpus': vcpus,
          'state': state,
          'time': times,
          }
        if name in output and output[name] != value:
          raise errors.HypervisorError("Instance %s running duplicate"
                                       " with different parameters" % name)
        output[name] = value

  return output


def AddOSToInstance(instance):
  """Add an OS to an instance.

  @type instance: L{objects.Instance}
  @param instance: Instance whose OS is to be installed
  @rtype: boolean
  @return: the success of the operation

  """
  inst_os = OSFromDisk(instance.os)

  create_env = OSEnvironment(instance)

  logfile = "%s/add-%s-%s-%d.log" % (constants.LOG_OS_DIR, instance.os,
                                     instance.name, int(time.time()))

  result = utils.RunCmd([inst_os.create_script], env=create_env,
                        cwd=inst_os.path, output=logfile,)
  if result.failed:
    logging.error("os create command '%s' returned error: %s, logfile: %s,"
                  " output: %s", result.cmd, result.fail_reason, logfile,
                  result.output)
    return False

  return True


def RunRenameInstance(instance, old_name):
  """Run the OS rename script for an instance.

  @type instance: L{objects.Instance}
  @param instance: Instance whose OS is to be installed
  @type old_name: string
  @param old_name: previous instance name
  @rtype: boolean
  @return: the success of the operation

  """
  inst_os = OSFromDisk(instance.os)

  rename_env = OSEnvironment(instance)
  rename_env['OLD_INSTANCE_NAME'] = old_name

  logfile = "%s/rename-%s-%s-%s-%d.log" % (constants.LOG_OS_DIR, instance.os,
                                           old_name,
                                           instance.name, int(time.time()))

  result = utils.RunCmd([inst_os.rename_script], env=rename_env,
                        cwd=inst_os.path, output=logfile)

  if result.failed:
    logging.error("os create command '%s' returned error: %s output: %s",
                  result.cmd, result.fail_reason, result.output)
    return False

  return True


def _GetVGInfo(vg_name):
  """Get informations about the volume group.

  @type vg_name: str
  @param vg_name: the volume group which we query
  @rtype: dict
  @return:
    A dictionary with the following keys:
      - C{vg_size} is the total size of the volume group in MiB
      - C{vg_free} is the free size of the volume group in MiB
      - C{pv_count} are the number of physical disks in that VG

    If an error occurs during gathering of data, we return the same dict
    with keys all set to None.

  """
  retdic = dict.fromkeys(["vg_size", "vg_free", "pv_count"])

  retval = utils.RunCmd(["vgs", "-ovg_size,vg_free,pv_count", "--noheadings",
                         "--nosuffix", "--units=m", "--separator=:", vg_name])

  if retval.failed:
    logging.error("volume group %s not present", vg_name)
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
      logging.exception("Fail to parse vgs output")
  else:
    logging.error("vgs output has the wrong number of fields (expected"
                  " three): %s", str(valarr))
  return retdic


def _GatherBlockDevs(instance):
  """Set up an instance's block device(s).

  This is run on the primary node at instance startup. The block
  devices must be already assembled.

  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we shoul assemble
  @rtype: list of L{bdev.BlockDev}
  @return: list of the block devices

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

  @type instance: L{objects.Instance}
  @param instance: the instance object
  @rtype: boolean
  @return: whether the startup was successful or not

  """
  running_instances = GetInstanceList([instance.hypervisor])

  if instance.name in running_instances:
    return True

  block_devices = _GatherBlockDevs(instance)
  hyper = hypervisor.GetHypervisor(instance.hypervisor)

  try:
    hyper.StartInstance(instance, block_devices, extra_args)
  except errors.HypervisorError, err:
    logging.exception("Failed to start instance")
    return False

  return True


def ShutdownInstance(instance):
  """Shut an instance down.

  @note: this functions uses polling with a hardcoded timeout.

  @type instance: L{objects.Instance}
  @param instance: the instance object
  @rtype: boolean
  @return: whether the startup was successful or not

  """
  hv_name = instance.hypervisor
  running_instances = GetInstanceList([hv_name])

  if instance.name not in running_instances:
    return True

  hyper = hypervisor.GetHypervisor(hv_name)
  try:
    hyper.StopInstance(instance)
  except errors.HypervisorError, err:
    logging.error("Failed to stop instance")
    return False

  # test every 10secs for 2min
  shutdown_ok = False

  time.sleep(1)
  for dummy in range(11):
    if instance.name not in GetInstanceList([hv_name]):
      break
    time.sleep(10)
  else:
    # the shutdown did not succeed
    logging.error("shutdown of '%s' unsuccessful, using destroy", instance)

    try:
      hyper.StopInstance(instance, force=True)
    except errors.HypervisorError, err:
      logging.exception("Failed to stop instance")
      return False

    time.sleep(1)
    if instance.name in GetInstanceList([hv_name]):
      logging.error("could not shutdown instance '%s' even by destroy",
                    instance.name)
      return False

  return True


def RebootInstance(instance, reboot_type, extra_args):
  """Reboot an instance.

  @type instance: L{objects.Instance}
  @param instance: the instance object to reboot
  @type reboot_type: str
  @param reboot_type: the type of reboot, one the following
    constants:
      - L{constants.INSTANCE_REBOOT_SOFT}: only reboot the
        instance OS, do not recreate the VM
      - L{constants.INSTANCE_REBOOT_HARD}: tear down and
        restart the VM (at the hypervisor level)
      - the other reboot type (L{constants.INSTANCE_REBOOT_HARD})
        is not accepted here, since that mode is handled
        differently
  @rtype: boolean
  @return: the success of the operation

  """
  running_instances = GetInstanceList([instance.hypervisor])

  if instance.name not in running_instances:
    logging.error("Cannot reboot instance that is not running")
    return False

  hyper = hypervisor.GetHypervisor(instance.hypervisor)
  if reboot_type == constants.INSTANCE_REBOOT_SOFT:
    try:
      hyper.RebootInstance(instance)
    except errors.HypervisorError, err:
      logging.exception("Failed to soft reboot instance")
      return False
  elif reboot_type == constants.INSTANCE_REBOOT_HARD:
    try:
      ShutdownInstance(instance)
      StartInstance(instance, extra_args)
    except errors.HypervisorError, err:
      logging.exception("Failed to hard reboot instance")
      return False
  else:
    raise errors.ParameterError("reboot_type invalid")

  return True


def MigrateInstance(instance, target, live):
  """Migrates an instance to another node.

  @type instance: L{objects.Instance}
  @param instance: the instance definition
  @type target: string
  @param target: the target node name
  @type live: boolean
  @param live: whether the migration should be done live or not (the
      interpretation of this parameter is left to the hypervisor)
  @rtype: tuple
  @return: a tuple of (success, msg) where:
      - succes is a boolean denoting the success/failure of the operation
      - msg is a string with details in case of failure

  """
  hyper = hypervisor.GetHypervisor(instance.hypervisor_name)

  try:
    hyper.MigrateInstance(instance.name, target, live)
  except errors.HypervisorError, err:
    msg = "Failed to migrate instance: %s" % str(err)
    logging.error(msg)
    return (False, msg)
  return (True, "Migration successfull")


def CreateBlockDevice(disk, size, owner, on_primary, info):
  """Creates a block device for an instance.

  @type disk: L{objects.Disk}
  @param disk: the object describing the disk we should create
  @type size: int
  @param size: the size of the physical underlying device, in MiB
  @type owner: str
  @param owner: the name of the instance for which disk is created,
      used for device cache data
  @type on_primary: boolean
  @param on_primary:  indicates if it is the primary node or not
  @type info: string
  @param info: string that will be sent to the physical device
      creation, used for example to set (LVM) tags on LVs

  @return: the new unique_id of the device (this can sometime be
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
      logging.info("removing existing device %s", disk)
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
      logging.error(errorstring)
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

  @note: This is intended to be called recursively.

  @type disk: L{objects.disk}
  @param disk: the disk object we should remove
  @rtype: boolean
  @return: the success of the operation

  """
  try:
    # since we are removing the device, allow a partial match
    # this allows removal of broken mirrors
    rdev = _RecursiveFindBD(disk, allow_partial=True)
  except errors.BlockDeviceError, err:
    # probably can't attach
    logging.info("Can't attach to device %s in remove", disk)
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

  @note: this function is called recursively.

  @type disk: L{objects.Disk}
  @param disk: the disk we try to assemble
  @type owner: str
  @param owner: the name of the instance which owns the disk
  @type as_primary: boolean
  @param as_primary: if we should make the block device
      read/write

  @return: the assembled device or None (in case no device
      was assembled)
  @raise errors.BlockDeviceError: in case there is an error
      during the activation of the children or the device
      itself

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
        logging.debug("Error in child activation: %s", str(err))
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

  @rtype: str or boolean
  @return: a C{/dev/...} path for primary nodes, and
      C{True} for secondary nodes

  """
  result = _RecursiveAssembleBD(disk, owner, as_primary)
  if isinstance(result, bdev.BlockDev):
    result = result.dev_path
  return result


def ShutdownBlockDevice(disk):
  """Shut down a block device.

  First, if the device is assembled (can L{Attach()}), then the device
  is shutdown. Then the children of the device are shutdown.

  This function is called recursively. Note that we don't cache the
  children or such, as oppossed to assemble, shutdown of different
  devices doesn't require that the upper device was active.

  @type disk: L{objects.Disk}
  @param disk: the description of the disk we should
      shutdown
  @rtype: boolean
  @return: the success of the operation

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

  @type parent_cdev: L{objects.Disk}
  @param parent_cdev: the disk to which we should add children
  @type new_cdevs: list of L{objects.Disk}
  @param new_cdevs: the list of children which we should add
  @rtype: boolean
  @return: the success of the operation

  """
  parent_bdev = _RecursiveFindBD(parent_cdev, allow_partial=True)
  if parent_bdev is None:
    logging.error("Can't find parent device")
    return False
  new_bdevs = [_RecursiveFindBD(disk) for disk in new_cdevs]
  if new_bdevs.count(None) > 0:
    logging.error("Can't find new device(s) to add: %s:%s",
                  new_bdevs, new_cdevs)
    return False
  parent_bdev.AddChildren(new_bdevs)
  return True


def MirrorRemoveChildren(parent_cdev, new_cdevs):
  """Shrink a mirrored block device.

  @type parent_cdev: L{objects.Disk}
  @param parent_cdev: the disk from which we should remove children
  @type new_cdevs: list of L{objects.Disk}
  @param new_cdevs: the list of children which we should remove
  @rtype: boolean
  @return: the success of the operation

  """
  parent_bdev = _RecursiveFindBD(parent_cdev)
  if parent_bdev is None:
    logging.error("Can't find parent in remove children: %s", parent_cdev)
    return False
  devs = []
  for disk in new_cdevs:
    rpath = disk.StaticDevPath()
    if rpath is None:
      bd = _RecursiveFindBD(disk)
      if bd is None:
        logging.error("Can't find dynamic device %s while removing children",
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

  @type disks: list of L{objects.Disk}
  @param disks: the list of disks which we should query
  @rtype: disk
  @return:
      a list of (mirror_done, estimated_time) tuples, which
      are the result of L{bdev.BlockDevice.CombinedSyncStatus}
  @raise errors.BlockDeviceError: if any of the disks cannot be
      found

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

  @type disk: L{objects.Disk}
  @param disk: the disk object we need to find
  @type allow_partial: boolean
  @param allow_partial: if true, don't abort the find if a
      child of the device can't be found; this is intended
      to be used when repairing mirrors

  @return: None if the device can't be found,
      otherwise the device instance

  """
  children = []
  if disk.children:
    for chdisk in disk.children:
      children.append(_RecursiveFindBD(chdisk))

  return bdev.FindDevice(disk.dev_type, disk.physical_id, children)


def FindBlockDevice(disk):
  """Check if a device is activated.

  If it is, return informations about the real device.

  @type disk: L{objects.Disk}
  @param disk: the disk to find
  @rtype: None or tuple
  @return: None if the disk cannot be found, otherwise a
      tuple (device_path, major, minor, sync_percent,
      estimated_time, is_degraded)

  """
  rbd = _RecursiveFindBD(disk)
  if rbd is None:
    return rbd
  return (rbd.dev_path, rbd.major, rbd.minor) + rbd.GetSyncStatus()


def UploadFile(file_name, data, mode, uid, gid, atime, mtime):
  """Write a file to the filesystem.

  This allows the master to overwrite(!) a file. It will only perform
  the operation if the file belongs to a list of configuration files.

  @type file_name: str
  @param file_name: the target file name
  @type data: str
  @param data: the new contents of the file
  @type mode: int
  @param mode: the mode to give the file (can be None)
  @type uid: int
  @param uid: the owner of the file (can be -1 for default)
  @type gid: int
  @param gid: the group of the file (can be -1 for default)
  @type atime: float
  @param atime: the atime to set on the file (can be None)
  @type mtime: float
  @param mtime: the mtime to set on the file (can be None)
  @rtype: boolean
  @return: the success of the operation; errors are logged
      in the node daemon log

  """
  if not os.path.isabs(file_name):
    logging.error("Filename passed to UploadFile is not absolute: '%s'",
                  file_name)
    return False

  allowed_files = [
    constants.CLUSTER_CONF_FILE,
    constants.ETC_HOSTS,
    constants.SSH_KNOWN_HOSTS_FILE,
    constants.VNC_PASSWORD_FILE,
    ]

  if file_name not in allowed_files:
    logging.error("Filename passed to UploadFile not in allowed"
                 " upload targets: '%s'", file_name)
    return False

  utils.WriteFile(file_name, data=data, mode=mode, uid=uid, gid=gid,
                  atime=atime, mtime=mtime)
  return True


def WriteSsconfFiles():
  ssconf.WriteSsconfFiles(constants.CLUSTER_CONF_FILE)


def _ErrnoOrStr(err):
  """Format an EnvironmentError exception.

  If the L{err} argument has an errno attribute, it will be looked up
  and converted into a textual C{E...} description. Otherwise the
  string representation of the error will be returned.

  @type err: L{EnvironmentError}
  @param err: the exception to format

  """
  if hasattr(err, 'errno'):
    detail = errno.errorcode[err.errno]
  else:
    detail = str(err)
  return detail


def _OSOndiskVersion(name, os_dir):
  """Compute and return the API version of a given OS.

  This function will try to read the API version of the OS given by
  the 'name' parameter and residing in the 'os_dir' directory.

  @type name: str
  @param name: the OS name we should look for
  @type os_dir: str
  @param os_dir: the directory inwhich we should look for the OS
  @rtype: int or None
  @return:
      Either an integer denoting the version or None in the
      case when this is not a valid OS name.
  @raise errors.InvalidOS: if the OS cannot be found

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
      api_versions = f.readlines()
    finally:
      f.close()
  except EnvironmentError, err:
    raise errors.InvalidOS(name, os_dir, "error while reading the"
                           " API version (%s)" % _ErrnoOrStr(err))

  api_versions = [version.strip() for version in api_versions]
  try:
    api_versions = [int(version) for version in api_versions]
  except (TypeError, ValueError), err:
    raise errors.InvalidOS(name, os_dir,
                           "API version is not integer (%s)" % str(err))

  return api_versions


def DiagnoseOS(top_dirs=None):
  """Compute the validity for all OSes.

  @type top_dirs: list
  @param top_dirs: the list of directories in which to
      search (if not given defaults to
      L{constants.OS_SEARCH_PATH})
  @rtype: list of L{objects.OS}
  @return: an OS object for each name in all the given
      directories

  """
  if top_dirs is None:
    top_dirs = constants.OS_SEARCH_PATH

  result = []
  for dir_name in top_dirs:
    if os.path.isdir(dir_name):
      try:
        f_names = utils.ListVisibleFiles(dir_name)
      except EnvironmentError, err:
        logging.exception("Can't list the OS directory %s", dir_name)
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
  L{errors.InvalidOS} exception, detailing why this is not a valid OS.

  @type base_dir: string
  @keyword base_dir: Base directory containing OS installations.
                     Defaults to a search in all the OS_SEARCH_PATH dirs.
  @rtype: L{objects.OS}
  @return: the OS instance if we find a valid one
  @raise errors.InvalidOS: if we don't find a valid OS

  """
  if base_dir is None:
    os_dir = utils.FindFile(name, constants.OS_SEARCH_PATH, os.path.isdir)
    if os_dir is None:
      raise errors.InvalidOS(name, None, "OS dir not found in search path")
  else:
    os_dir = os.path.sep.join([base_dir, name])

  api_versions = _OSOndiskVersion(name, os_dir)

  if constants.OS_API_VERSION not in api_versions:
    raise errors.InvalidOS(name, os_dir, "API version mismatch"
                           " (found %s want %s)"
                           % (api_versions, constants.OS_API_VERSION))

  # OS Scripts dictionary, we will populate it with the actual script names
  os_scripts = dict.fromkeys(constants.OS_SCRIPTS)

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
                    create_script=os_scripts[constants.OS_SCRIPT_CREATE],
                    export_script=os_scripts[constants.OS_SCRIPT_EXPORT],
                    import_script=os_scripts[constants.OS_SCRIPT_IMPORT],
                    rename_script=os_scripts[constants.OS_SCRIPT_RENAME],
                    api_versions=api_versions)

def OSEnvironment(instance, debug=0):
  """Calculate the environment for an os script.

  @type instance: L{objects.Instance}
  @param instance: target instance for the os script run
  @type debug: integer
  @param debug: debug level (0 or 1, for OS Api 10)
  @rtype: dict
  @return: dict of environment variables
  @raise errors.BlockDeviceError: if the block device
      cannot be found

  """
  result = {}
  result['OS_API_VERSION'] = '%d' % constants.OS_API_VERSION
  result['INSTANCE_NAME'] = instance.name
  result['HYPERVISOR'] = instance.hypervisor
  result['DISK_COUNT'] = '%d' % len(instance.disks)
  result['NIC_COUNT'] = '%d' % len(instance.nics)
  result['DEBUG_LEVEL'] = '%d' % debug
  for idx, disk in enumerate(instance.disks):
    real_disk = _RecursiveFindBD(disk)
    if real_disk is None:
      raise errors.BlockDeviceError("Block device '%s' is not set up" %
                                    str(disk))
    real_disk.Open()
    result['DISK_%d_PATH' % idx] = real_disk.dev_path
    # FIXME: When disks will have read-only mode, populate this
    result['DISK_%d_ACCESS' % idx] = 'W'
    if constants.HV_DISK_TYPE in instance.hvparams:
      result['DISK_%d_FRONTEND_TYPE' % idx] = \
        instance.hvparams[constants.HV_DISK_TYPE]
    if disk.dev_type in constants.LDS_BLOCK:
      result['DISK_%d_BACKEND_TYPE' % idx] = 'block'
    elif disk.dev_type == constants.LD_FILE:
      result['DISK_%d_BACKEND_TYPE' % idx] = \
        'file:%s' % disk.physical_id[0]
  for idx, nic in enumerate(instance.nics):
    result['NIC_%d_MAC' % idx] = nic.mac
    if nic.ip:
      result['NIC_%d_IP' % idx] = nic.ip
    result['NIC_%d_BRIDGE' % idx] = nic.bridge
    if constants.HV_NIC_TYPE in instance.hvparams:
      result['NIC_%d_FRONTEND_TYPE' % idx] = \
        instance.hvparams[constants.HV_NIC_TYPE]

  return result

def GrowBlockDevice(disk, amount):
  """Grow a stack of block devices.

  This function is called recursively, with the childrens being the
  first ones to resize.

  @type disk: L{objects.Disk}
  @param disk: the disk to be grown
  @rtype: (status, result)
  @return: a tuple with the status of the operation
      (True/False), and the errors message if status
      is False

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

  @type disk: L{objects.Disk}
  @param disk: the disk to be snapshotted
  @rtype: string
  @return: snapshot disk path

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


def ExportSnapshot(disk, dest_node, instance, cluster_name, idx):
  """Export a block device snapshot to a remote node.

  @type disk: L{objects.Disk}
  @param disk: the description of the disk to export
  @type dest_node: str
  @param dest_node: the destination node to export to
  @type instance: L{objects.Instance}
  @param instance: the instance object to whom the disk belongs
  @type cluster_name: str
  @param cluster_name: the cluster name, needed for SSH hostalias
  @type idx: int
  @param idx: the index of the disk in the instance's disk list,
      used to export to the OS scripts environment
  @rtype: boolean
  @return: the success of the operation

  """
  export_env = OSEnvironment(instance)

  inst_os = OSFromDisk(instance.os)
  export_script = inst_os.export_script

  logfile = "%s/exp-%s-%s-%s.log" % (constants.LOG_OS_DIR, inst_os.name,
                                     instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)
  real_disk = _RecursiveFindBD(disk)
  if real_disk is None:
    raise errors.BlockDeviceError("Block device '%s' is not set up" %
                                  str(disk))
  real_disk.Open()

  export_env['EXPORT_DEVICE'] = real_disk.dev_path
  export_env['EXPORT_INDEX'] = str(idx)

  destdir = os.path.join(constants.EXPORT_DIR, instance.name + ".new")
  destfile = disk.physical_id[1]

  # the target command is built out of three individual commands,
  # which are joined by pipes; we check each individual command for
  # valid parameters
  expcmd = utils.BuildShellCmd("cd %s; %s 2>%s", inst_os.path,
                               export_script, logfile)

  comprcmd = "gzip"

  destcmd = utils.BuildShellCmd("mkdir -p %s && cat > %s/%s",
                                destdir, destdir, destfile)
  remotecmd = _GetSshRunner(cluster_name).BuildCmd(dest_node,
                                                   constants.GANETI_RUNAS,
                                                   destcmd)

  # all commands have been checked, so we're safe to combine them
  command = '|'.join([expcmd, comprcmd, utils.ShellQuoteArgs(remotecmd)])

  result = utils.RunCmd(command, env=export_env)

  if result.failed:
    logging.error("os snapshot export command '%s' returned error: %s"
                  " output: %s", command, result.fail_reason, result.output)
    return False

  return True


def FinalizeExport(instance, snap_disks):
  """Write out the export configuration information.

  @type instance: L{objects.Instance}
  @param instance: the instance which we export, used for
      saving configuration
  @type snap_disks: list of L{objects.Disk}
  @param snap_disks: list of snapshot block devices, which
      will be used to get the actual name of the dump file

  @rtype: boolean
  @return: the success of the operation

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
  config.set(constants.INISECT_INS, 'memory', '%d' %
             instance.beparams[constants.BE_MEMORY])
  config.set(constants.INISECT_INS, 'vcpus', '%d' %
             instance.beparams[constants.BE_VCPUS])
  config.set(constants.INISECT_INS, 'disk_template', instance.disk_template)

  nic_count = 0
  for nic_count, nic in enumerate(instance.nics):
    config.set(constants.INISECT_INS, 'nic%d_mac' %
               nic_count, '%s' % nic.mac)
    config.set(constants.INISECT_INS, 'nic%d_ip' % nic_count, '%s' % nic.ip)
    config.set(constants.INISECT_INS, 'nic%d_bridge' % nic_count,
               '%s' % nic.bridge)
  # TODO: redundant: on load can read nics until it doesn't exist
  config.set(constants.INISECT_INS, 'nic_count' , '%d' % nic_count)

  disk_count = 0
  for disk_count, disk in enumerate(snap_disks):
    if disk:
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

  @type dest: str
  @param dest: directory containing the export

  @rtype: L{objects.SerializableConfigParser}
  @return: a serializable config file containing the
      export info

  """
  cff = os.path.join(dest, constants.EXPORT_CONF_FILE)

  config = objects.SerializableConfigParser()
  config.read(cff)

  if (not config.has_section(constants.INISECT_EXP) or
      not config.has_section(constants.INISECT_INS)):
    return None

  return config


def ImportOSIntoInstance(instance, src_node, src_images, cluster_name):
  """Import an os image into an instance.

  @type instance: L{objects.Instance}
  @param instance: instance to import the disks into
  @type src_node: string
  @param src_node: source node for the disk images
  @type src_images: list of string
  @param src_images: absolute paths of the disk images
  @rtype: list of boolean
  @return: each boolean represent the success of importing the n-th disk

  """
  import_env = OSEnvironment(instance)
  inst_os = OSFromDisk(instance.os)
  import_script = inst_os.import_script

  logfile = "%s/import-%s-%s-%s.log" % (constants.LOG_OS_DIR, instance.os,
                                        instance.name, int(time.time()))
  if not os.path.exists(constants.LOG_OS_DIR):
    os.mkdir(constants.LOG_OS_DIR, 0750)

  comprcmd = "gunzip"
  impcmd = utils.BuildShellCmd("(cd %s; %s >%s 2>&1)", inst_os.path,
                               import_script, logfile)

  final_result = []
  for idx, image in enumerate(src_images):
    if image:
      destcmd = utils.BuildShellCmd('cat %s', image)
      remotecmd = _GetSshRunner(cluster_name).BuildCmd(src_node,
                                                       constants.GANETI_RUNAS,
                                                       destcmd)
      command = '|'.join([utils.ShellQuoteArgs(remotecmd), comprcmd, impcmd])
      import_env['IMPORT_DEVICE'] = import_env['DISK_%d_PATH' % idx]
      import_env['IMPORT_INDEX'] = str(idx)
      result = utils.RunCmd(command, env=import_env)
      if result.failed:
        logging.error("disk import command '%s' returned error: %s"
                      " output: %s", command, result.fail_reason, result.output)
        final_result.append(False)
      else:
        final_result.append(True)
    else:
      final_result.append(True)

  return final_result


def ListExports():
  """Return a list of exports currently available on this machine.

  @rtype: list
  @return: list of the exports

  """
  if os.path.isdir(constants.EXPORT_DIR):
    return utils.ListVisibleFiles(constants.EXPORT_DIR)
  else:
    return []


def RemoveExport(export):
  """Remove an existing export from the node.

  @type export: str
  @param export: the name of the export to remove
  @rtype: boolean
  @return: the success of the operation

  """
  target = os.path.join(constants.EXPORT_DIR, export)

  shutil.rmtree(target)
  # TODO: catch some of the relevant exceptions and provide a pretty
  # error message if rmtree fails.

  return True


def RenameBlockDevices(devlist):
  """Rename a list of block devices.

  @type devlist: list of tuples
  @param devlist: list of tuples of the form  (disk,
      new_logical_id, new_physical_id); disk is an
      L{objects.Disk} object describing the current disk,
      and new logical_id/physical_id is the name we
      rename it to
  @rtype: boolean
  @return: True if all renames succeeded, False otherwise

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
      logging.exception("Can't rename device '%s' to '%s'", dev, unique_id)
      result = False
  return result


def _TransformFileStorageDir(file_storage_dir):
  """Checks whether given file_storage_dir is valid.

  Checks wheter the given file_storage_dir is within the cluster-wide
  default file_storage_dir stored in SimpleStore. Only paths under that
  directory are allowed.

  @type file_storage_dir: str
  @param file_storage_dir: the path to check

  @return: the normalized path if valid, None otherwise

  """
  cfg = _GetConfig()
  file_storage_dir = os.path.normpath(file_storage_dir)
  base_file_storage_dir = cfg.GetFileStorageDir()
  if (not os.path.commonprefix([file_storage_dir, base_file_storage_dir]) ==
      base_file_storage_dir):
    logging.error("file storage directory '%s' is not under base file"
                  " storage directory '%s'",
                  file_storage_dir, base_file_storage_dir)
    return None
  return file_storage_dir


def CreateFileStorageDir(file_storage_dir):
  """Create file storage directory.

  @type file_storage_dir: str
  @param file_storage_dir: directory to create

  @rtype: tuple
  @return: tuple with first element a boolean indicating wheter dir
      creation was successful or not

  """
  file_storage_dir = _TransformFileStorageDir(file_storage_dir)
  result = True,
  if not file_storage_dir:
    result = False,
  else:
    if os.path.exists(file_storage_dir):
      if not os.path.isdir(file_storage_dir):
        logging.error("'%s' is not a directory", file_storage_dir)
        result = False,
    else:
      try:
        os.makedirs(file_storage_dir, 0750)
      except OSError, err:
        logging.error("Cannot create file storage directory '%s': %s",
                      file_storage_dir, err)
        result = False,
  return result


def RemoveFileStorageDir(file_storage_dir):
  """Remove file storage directory.

  Remove it only if it's empty. If not log an error and return.

  @type file_storage_dir: str
  @param file_storage_dir: the directory we should cleanup
  @rtype: tuple (success,)
  @return: tuple of one element, C{success}, denoting
      whether the operation was successfull

  """
  file_storage_dir = _TransformFileStorageDir(file_storage_dir)
  result = True,
  if not file_storage_dir:
    result = False,
  else:
    if os.path.exists(file_storage_dir):
      if not os.path.isdir(file_storage_dir):
        logging.error("'%s' is not a directory", file_storage_dir)
        result = False,
      # deletes dir only if empty, otherwise we want to return False
      try:
        os.rmdir(file_storage_dir)
      except OSError, err:
        logging.exception("Cannot remove file storage directory '%s'",
                          file_storage_dir)
        result = False,
  return result


def RenameFileStorageDir(old_file_storage_dir, new_file_storage_dir):
  """Rename the file storage directory.

  @type old_file_storage_dir: str
  @param old_file_storage_dir: the current path
  @type new_file_storage_dir: str
  @param new_file_storage_dir: the name we should rename to
  @rtype: tuple (success,)
  @return: tuple of one element, C{success}, denoting
      whether the operation was successful

  """
  old_file_storage_dir = _TransformFileStorageDir(old_file_storage_dir)
  new_file_storage_dir = _TransformFileStorageDir(new_file_storage_dir)
  result = True,
  if not old_file_storage_dir or not new_file_storage_dir:
    result = False,
  else:
    if not os.path.exists(new_file_storage_dir):
      if os.path.isdir(old_file_storage_dir):
        try:
          os.rename(old_file_storage_dir, new_file_storage_dir)
        except OSError, err:
          logging.exception("Cannot rename '%s' to '%s'",
                            old_file_storage_dir, new_file_storage_dir)
          result =  False,
      else:
        logging.error("'%s' is not a directory", old_file_storage_dir)
        result = False,
    else:
      if os.path.exists(old_file_storage_dir):
        logging.error("Cannot rename '%s' to '%s'. Both locations exist.",
                      old_file_storage_dir, new_file_storage_dir)
        result = False,
  return result


def _IsJobQueueFile(file_name):
  """Checks whether the given filename is in the queue directory.

  @type file_name: str
  @param file_name: the file name we should check
  @rtype: boolean
  @return: whether the file is under the queue directory

  """
  queue_dir = os.path.normpath(constants.QUEUE_DIR)
  result = (os.path.commonprefix([queue_dir, file_name]) == queue_dir)

  if not result:
    logging.error("'%s' is not a file in the queue directory",
                  file_name)

  return result


def JobQueueUpdate(file_name, content):
  """Updates a file in the queue directory.

  This is just a wrapper over L{utils.WriteFile}, with proper
  checking.

  @type file_name: str
  @param file_name: the job file name
  @type content: str
  @param content: the new job contents
  @rtype: boolean
  @return: the success of the operation

  """
  if not _IsJobQueueFile(file_name):
    return False

  # Write and replace the file atomically
  utils.WriteFile(file_name, data=content)

  return True


def JobQueueRename(old, new):
  """Renames a job queue file.

  This is just a wrapper over L{os.rename} with proper checking.

  @type old: str
  @param old: the old (actual) file name
  @type new: str
  @param new: the desired file name
  @rtype: boolean
  @return: the success of the operation

  """
  if not (_IsJobQueueFile(old) and _IsJobQueueFile(new)):
    return False

  os.rename(old, new)

  return True


def JobQueueSetDrainFlag(drain_flag):
  """Set the drain flag for the queue.

  This will set or unset the queue drain flag.

  @type drain_flag: boolean
  @param drain_flag: if True, will set the drain flag, otherwise reset it.
  @rtype: boolean
  @return: always True
  @warning: the function always returns True

  """
  if drain_flag:
    utils.WriteFile(constants.JOB_QUEUE_DRAIN_FILE, data="", close=True)
  else:
    utils.RemoveFile(constants.JOB_QUEUE_DRAIN_FILE)

  return True


def CloseBlockDevices(disks):
  """Closes the given block devices.

  This means they will be switched to secondary mode (in case of
  DRBD).

  @type disks: list of L{objects.Disk}
  @param disks: the list of disks to be closed
  @rtype: tuple (success, message)
  @return: a tuple of success and message, where success
      indicates the succes of the operation, and message
      which will contain the error details in case we
      failed

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
  if msg:
    return (False, "Can't make devices secondary: %s" % ",".join(msg))
  else:
    return (True, "All devices secondary")


def ValidateHVParams(hvname, hvparams):
  """Validates the given hypervisor parameters.

  @type hvname: string
  @param hvname: the hypervisor name
  @type hvparams: dict
  @param hvparams: the hypervisor parameters to be validated
  @rtype: tuple (success, message)
  @return: a tuple of success and message, where success
      indicates the succes of the operation, and message
      which will contain the error details in case we
      failed

  """
  try:
    hv_type = hypervisor.GetHypervisor(hvname)
    hv_type.ValidateParameters(hvparams)
    return (True, "Validation passed")
  except errors.HypervisorError, err:
    return (False, str(err))


class HooksRunner(object):
  """Hook runner.

  This class is instantiated on the node side (ganeti-noded) and not
  on the master side.

  """
  RE_MASK = re.compile("^[a-zA-Z0-9_-]+$")

  def __init__(self, hooks_base_dir=None):
    """Constructor for hooks runner.

    @type hooks_base_dir: str or None
    @param hooks_base_dir: if not None, this overrides the
        L{constants.HOOKS_BASE_DIR} (useful for unittests)

    """
    if hooks_base_dir is None:
      hooks_base_dir = constants.HOOKS_BASE_DIR
    self._BASE_DIR = hooks_base_dir

  @staticmethod
  def ExecHook(script, env):
    """Exec one hook script.

    @type script: str
    @param script: the full path to the script
    @type env: dict
    @param env: the environment with which to exec the script
    @rtype: tuple (success, message)
    @return: a tuple of success and message, where success
        indicates the succes of the operation, and message
        which will contain the error details in case we
        failed

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
            #logging.exception("Error while closing fd %s", fd)
            pass

    return result == 0, output

  def RunHooks(self, hpath, phase, env):
    """Run the scripts in the hooks directory.

    @type hpath: str
    @param hpath: the path to the hooks directory which
        holds the scripts
    @type phase: str
    @param phase: either L{constants.HOOKS_PHASE_PRE} or
        L{constants.HOOKS_PHASE_POST}
    @type env: dict
    @param env: dictionary with the environment for the hook
    @rtype: list
    @return: list of 3-element tuples:
      - script path
      - script result, either L{constants.HKR_SUCCESS} or
        L{constants.HKR_FAIL}
      - output of the script

    @raise errors.ProgrammerError: for invalid input
        parameters

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
      # FIXME: must log output in case of failures
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

    @type name: str
    @param name: the iallocator script name
    @type idata: str
    @param idata: the allocator input data

    @rtype: tuple
    @return: four element tuple of:
       - run status (one of the IARUN_ constants)
       - stdout
       - stderr
       - fail reason (as from L{utils.RunResult})

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
    prefix. It then returns the full path to the cache file.

    @type dev_path: str
    @param dev_path: the C{/dev/} path name
    @rtype: str
    @return: the converted path name

    """
    if dev_path.startswith(cls._DEV_PREFIX):
      dev_path = dev_path[len(cls._DEV_PREFIX):]
    dev_path = dev_path.replace("/", "_")
    fpath = "%s/bdev_%s" % (cls._ROOT_DIR, dev_path)
    return fpath

  @classmethod
  def UpdateCache(cls, dev_path, owner, on_primary, iv_name):
    """Updates the cache information for a given device.

    @type dev_path: str
    @param dev_path: the pathname of the device
    @type owner: str
    @param owner: the owner (instance name) of the device
    @type on_primary: bool
    @param on_primary: whether this is the primary
        node nor not
    @type iv_name: str
    @param iv_name: the instance-visible name of the
        device, as in L{objects.Disk.iv_name}

    @rtype: None

    """
    if dev_path is None:
      logging.error("DevCacheManager.UpdateCache got a None dev_path")
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
      logging.exception("Can't update bdev cache for %s", dev_path)

  @classmethod
  def RemoveCache(cls, dev_path):
    """Remove data for a dev_path.

    This is just a wrapper over L{utils.RemoveFile} with a converted
    path name and logging.

    @type dev_path: str
    @param dev_path: the pathname of the device

    @rtype: None

    """
    if dev_path is None:
      logging.error("DevCacheManager.RemoveCache got a None dev_path")
      return
    fpath = cls._ConvertPath(dev_path)
    try:
      utils.RemoveFile(fpath)
    except EnvironmentError, err:
      logging.exception("Can't update bdev cache for %s", dev_path)
