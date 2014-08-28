#
#

# Copyright (C) 2010, 2013 Google Inc.
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


"""LXC hypervisor

"""

import errno
import os
import os.path
import logging
import sys
import re

from ganeti import constants
from ganeti import errors # pylint: disable=W0611
from ganeti import utils
from ganeti import objects
from ganeti import pathutils
from ganeti import serializer
from ganeti.hypervisor import hv_base
from ganeti.errors import HypervisorError


class LXCHypervisor(hv_base.BaseHypervisor):
  """LXC-based virtualization.

  TODO:
    - move hardcoded parameters into hypervisor parameters, once we
      have the container-parameter support

  Problems/issues:
    - LXC is very temperamental; in daemon mode, it succeeds or fails
      in launching the instance silently, without any error
      indication, and when failing it can leave network interfaces
      around, and future successful startups will list the instance
      twice

  """
  _ROOT_DIR = pathutils.RUN_DIR + "/lxc"
  _LOG_DIR = pathutils.LOG_DIR + "/lxc"
  _CGROUP_ROOT_DIR = _ROOT_DIR + "/cgroup"
  _PROC_CGROUPS_FILE = "/proc/cgroups"
  _PROC_SELF_CGROUP_FILE = "/proc/self/cgroup"

  _LXC_MIN_VERSION_REQUIRED = "1.0.0"
  _LXC_COMMANDS_REQUIRED = [
    "lxc-console",
    "lxc-ls",
    "lxc-start",
    "lxc-stop",
    "lxc-wait",
    ]

  _DIR_MODE = 0755
  _UNIQ_SUFFIX = ".conf"
  _STASH_KEY_ALLOCATED_LOOP_DEV = "allocated_loopdev"

  PARAMETERS = {
    constants.HV_CPU_MASK: hv_base.OPT_CPU_MASK_CHECK,
    constants.HV_LXC_CGROUP_USE: hv_base.NO_CHECK,
    constants.HV_LXC_DEVICES: hv_base.NO_CHECK,
    constants.HV_LXC_DROP_CAPABILITIES: hv_base.NO_CHECK,
    constants.HV_LXC_STARTUP_WAIT: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    }

  # Let beta version following micro version, but don't care about it
  _LXC_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
  _REBOOT_TIMEOUT = 120 # secs
  _REQUIRED_CGROUP_SUBSYSTEMS = [
    "cpuset",
    "memory",
    "devices",
    ]

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    self._EnsureDirectoryExistence()

  @staticmethod
  def _GetMountSubdirs(path):
    """Return the list of mountpoints under a given path.

    """
    result = []
    for _, mountpoint, _, _ in utils.GetMounts():
      if (mountpoint.startswith(path) and
          mountpoint != path):
        result.append(mountpoint)

    result.sort(key=lambda x: x.count("/"), reverse=True)
    return result

  @classmethod
  def _InstanceDir(cls, instance_name):
    """Return the root directory for an instance.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name)

  @classmethod
  def _InstanceConfFilePath(cls, instance_name):
    """Return the configuration file for an instance.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name + ".conf")

  @classmethod
  def _InstanceLogFilePath(cls, instance):
    """Return the log file for an instance.

    @type instance: L{objects.Instance}

    """
    filename = "%s.%s.log" % (instance.name, instance.uuid)
    return utils.PathJoin(cls._LOG_DIR, filename)

  @classmethod
  def _InstanceStashFilePath(cls, instance_name):
    """Return the stash file path for an instance.

    The stash file is used to keep information needed to clean up after the
    destruction of the instance.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name + ".stash")

  def _EnsureDirectoryExistence(self):
    """Ensures all the directories needed for LXC use exist.

    """
    utils.EnsureDirs([
      (self._ROOT_DIR, self._DIR_MODE),
      (self._LOG_DIR, 0750),
      ])

  def _SaveInstanceStash(self, instance_name, data):
    """Save data to the instance stash file in serialized format.

    """
    stash_file = self._InstanceStashFilePath(instance_name)
    serialized = serializer.Dump(data)
    try:
      utils.WriteFile(stash_file, data=serialized,
                      mode=constants.SECURE_FILE_MODE)
    except EnvironmentError, err:
      raise HypervisorError("Failed to save instance stash file %s : %s" %
                            (stash_file, err))

  def _LoadInstanceStash(self, instance_name):
    """Load information stashed in file which was created by
    L{_SaveInstanceStash}.

    """
    stash_file = self._InstanceStashFilePath(instance_name)
    try:
      return serializer.Load(utils.ReadFile(stash_file))
    except (EnvironmentError, ValueError), err:
      raise HypervisorError("Failed to load instance stash file %s : %s" %
                            (stash_file, err))

  @classmethod
  def _MountCgroupSubsystem(cls, subsystem):
    """Mount the cgroup subsystem fs under the cgroup root dir.

    @type subsystem: string
    @param subsystem: cgroup subsystem name to mount
    @rtype string
    @return path of subsystem mount point

    """
    subsys_dir = utils.PathJoin(cls._GetCgroupMountPoint(), subsystem)
    if not os.path.isdir(subsys_dir):
      try:
        os.makedirs(subsys_dir)
      except EnvironmentError, err:
        raise HypervisorError("Failed to create directory %s: %s" %
                              (subsys_dir, err))

    mount_cmd = ["mount", "-t", "cgroup", "-o", subsystem, subsystem,
                 subsys_dir]
    result = utils.RunCmd(mount_cmd)
    if result.failed:
      raise HypervisorError("Failed to mount cgroup subsystem '%s': %s" %
                            (subsystem, result.output))

    return subsys_dir

  def _CleanupInstance(self, instance_name, stash):
    """Actual implementation of the instance cleanup procedure.

    @type instance_name: string
    @param instance_name: instance name
    @type stash: dict(string:any)
    @param stash: dict that contains desired information for instance cleanup

    """
    try:
      if self._STASH_KEY_ALLOCATED_LOOP_DEV in stash:
        loop_dev_path = stash[self._STASH_KEY_ALLOCATED_LOOP_DEV]
        utils.ReleaseBdevPartitionMapping(loop_dev_path)
    except errors.CommandError, err:
      raise HypervisorError("Failed to cleanup partition mapping : %s" % err)

    utils.RemoveFile(self._InstanceStashFilePath(instance_name))

  def CleanupInstance(self, instance_name):
    """Cleanup after a stopped instance.

    """
    stash = self._LoadInstanceStash(instance_name)
    self._CleanupInstance(instance_name, stash)

  @classmethod
  def _GetCgroupMountPoint(cls):
    """Return the directory that should be the base of cgroup fs.

    """
    return cls._CGROUP_ROOT_DIR

  @classmethod
  def _GetOrPrepareCgroupSubsysMountPoint(cls, subsystem):
    """Prepare cgroup subsystem mount point.

    @type subsystem: string
    @param subsystem: cgroup subsystem name to mount
    @rtype string
    @return path of subsystem mount point

    """
    for _, mpoint, fstype, options in utils.GetMounts():
      if fstype == "cgroup" and subsystem in options.split(","):
        return mpoint

    return cls._MountCgroupSubsystem(subsystem)

  @classmethod
  def _GetCurrentCgroupSubsysGroups(cls):
    """Return the dict of cgroup subsystem hierarchies this process belongs to.

    The dictionary has the cgroup subsystem as a key and its hierarchy as a
    value.
    Information is read from /proc/self/cgroup.

    """
    try:
      cgroup_list = utils.ReadFile(cls._PROC_SELF_CGROUP_FILE)
    except EnvironmentError, err:
      raise HypervisorError("Failed to read %s : %s" %
                            (cls._PROC_SELF_CGROUP_FILE, err))

    cgroups = {}
    for line in filter(None, cgroup_list.split("\n")):
      _, subsystems, hierarchy = line.split(":")
      for subsys in subsystems.split(","):
        cgroups[subsys] = hierarchy[1:] # discard first '/'

    return cgroups

  @classmethod
  def _GetCgroupInstanceSubsysDir(cls, instance_name, subsystem):
    """Return the directory of the cgroup subsystem for the instance.

    @type instance_name: string
    @param instance_name: instance name
    @type subsystem: string
    @param subsystem: cgroup subsystem name
    @rtype string
    @return path of the instance hierarchy directory for the subsystem

    """
    subsys_dir = cls._GetOrPrepareCgroupSubsysMountPoint(subsystem)
    base_group = cls._GetCurrentCgroupSubsysGroups().get(subsystem, "")

    return utils.PathJoin(subsys_dir, base_group, "lxc", instance_name)

  @classmethod
  def _GetCgroupInstanceParamPath(cls, instance_name, param_name):
    """Return the path of the specified cgroup parameter file.

    @type instance_name: string
    @param instance_name: instance name
    @type param_name: string
    @param param_name: cgroup subsystem parameter name
    @rtype string
    @return path of the cgroup subsystem parameter file

    """
    subsystem = param_name.split(".", 1)[0]
    subsys_dir = cls._GetCgroupInstanceSubsysDir(instance_name, subsystem)
    return utils.PathJoin(subsys_dir, param_name)

  @classmethod
  def _GetCgroupInstanceValue(cls, instance_name, param_name):
    """Return the value of the specified cgroup parameter.

    @type instance_name: string
    @param instance_name: instance name
    @type param_name: string
    @param param_name: cgroup subsystem parameter name
    @rtype string
    @return value read from cgroup subsystem fs

    """
    param_path = cls._GetCgroupInstanceParamPath(instance_name, param_name)
    return utils.ReadFile(param_path).rstrip("\n")

  @classmethod
  def _SetCgroupInstanceValue(cls, instance_name, param_name, param_value):
    """Set the value to the specified instance cgroup parameter.

    @type instance_name: string
    @param instance_name: instance name
    @type param_name: string
    @param param_name: cgroup subsystem parameter name
    @type param_value: string
    @param param_value: cgroup subsystem parameter value to be set

    """
    param_path = cls._GetCgroupInstanceParamPath(instance_name, param_name)
    # When interacting with cgroup fs, errno is quite important information
    # to see what happened when setting a cgroup parameter, so just throw
    # an error to the upper level.
    # e.g., we could know that the container can't reclaim its memory by
    #       checking if the errno is EBUSY when setting the
    #       memory.memsw.limit_in_bytes.
    fd = -1
    try:
      fd = os.open(param_path, os.O_WRONLY)
      os.write(fd, param_value)
    finally:
      if fd != -1:
        os.close(fd)

  @classmethod
  def _GetCgroupCpuList(cls, instance_name):
    """Return the list of CPU ids for an instance.

    """
    try:
      cpumask = cls._GetCgroupInstanceValue(instance_name, "cpuset.cpus")
    except EnvironmentError, err:
      raise errors.HypervisorError("Getting CPU list for instance"
                                   " %s failed: %s" % (instance_name, err))

    return utils.ParseCpuMask(cpumask)

  @classmethod
  def _GetCgroupMemoryLimit(cls, instance_name):
    """Return the memory limit for an instance

    """
    try:
      mem_limit = cls._GetCgroupInstanceValue(instance_name,
                                              "memory.limit_in_bytes")
      mem_limit = int(mem_limit)
    except EnvironmentError:
      # memory resource controller may be disabled, ignore
      mem_limit = 0

    return mem_limit

  def ListInstances(self, hvparams=None):
    """Get the list of running instances.

    """
    return [iinfo[0] for iinfo in self.GetAllInstancesInfo()]

  @classmethod
  def _IsInstanceAlive(cls, instance_name):
    """Return True if instance is alive.

    """
    result = utils.RunCmd(["lxc-ls", "--running"])
    if result.failed:
      raise HypervisorError("Failed to get running LXC containers list: %s" %
                            result.output)

    return instance_name in result.stdout.split()

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: hvparams to be used with this instance
    @rtype: tuple of strings
    @return: (name, id, memory, vcpus, stat, times)

    """
    # TODO: read container info from the cgroup mountpoint

    if not self._IsInstanceAlive(instance_name):
      return None

    cpu_list = self._GetCgroupCpuList(instance_name)
    memory = self._GetCgroupMemoryLimit(instance_name) / (1024 ** 2)
    return (instance_name, 0, memory, len(cpu_list),
            hv_base.HvInstanceState.RUNNING, 0)

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameter
    @return: [(name, id, memory, vcpus, stat, times),...]

    """
    data = []
    for filename in os.listdir(self._ROOT_DIR):
      if not filename.endswith(self._UNIQ_SUFFIX):
        # listing all files in root directory will include instance root
        # directories, console files, etc, so use .conf as a filter of instance
        # listings.
        continue
      try:
        info = self.GetInstanceInfo(filename[0:-len(self._UNIQ_SUFFIX)])
      except errors.HypervisorError:
        continue
      if info:
        data.append(info)
    return data

  @classmethod
  def _GetInstanceDropCapabilities(cls, hvparams):
    """Get and parse the drop capabilities list from the instance hvparams.

    @type hvparams: dict of strings
    @param hvparams: instance hvparams
    @rtype list(string)
    @return list of drop capabilities

    """
    drop_caps = hvparams[constants.HV_LXC_DROP_CAPABILITIES]
    return drop_caps.split(",")

  def _CreateConfigFile(self, instance, sda_dev_path):
    """Create an lxc.conf file for an instance.

    """
    out = []
    # hostname
    out.append("lxc.utsname = %s" % instance.name)

    # separate pseudo-TTY instances
    out.append("lxc.pts = 255")
    # standard TTYs
    out.append("lxc.tty = 6")
    # console log file
    console_log = utils.PathJoin(self._ROOT_DIR, instance.name + ".console")
    try:
      utils.WriteFile(console_log, data="", mode=constants.SECURE_FILE_MODE)
    except EnvironmentError, err:
      raise errors.HypervisorError("Creating console log file %s for"
                                   " instance %s failed: %s" %
                                   (console_log, instance.name, err))
    out.append("lxc.console = %s" % console_log)

    # root FS
    out.append("lxc.rootfs = %s" % sda_dev_path)

    # TODO: additional mounts, if we disable CAP_SYS_ADMIN

    # CPUs
    if instance.hvparams[constants.HV_CPU_MASK]:
      cpu_list = utils.ParseCpuMask(instance.hvparams[constants.HV_CPU_MASK])
      cpus_in_mask = len(cpu_list)
      if cpus_in_mask != instance.beparams["vcpus"]:
        raise errors.HypervisorError("Number of VCPUs (%d) doesn't match"
                                     " the number of CPUs in the"
                                     " cpu_mask (%d)" %
                                     (instance.beparams["vcpus"],
                                      cpus_in_mask))
      out.append("lxc.cgroup.cpuset.cpus = %s" %
                 instance.hvparams[constants.HV_CPU_MASK])

    # Memory
    # Conditionally enable, memory resource controller might be disabled
    cgroup = self._GetOrPrepareCgroupSubsysMountPoint("memory")
    if os.path.exists(utils.PathJoin(cgroup, "memory.limit_in_bytes")):
      out.append("lxc.cgroup.memory.limit_in_bytes = %dM" %
                 instance.beparams[constants.BE_MAXMEM])

    if os.path.exists(utils.PathJoin(cgroup, "memory.memsw.limit_in_bytes")):
      out.append("lxc.cgroup.memory.memsw.limit_in_bytes = %dM" %
                 instance.beparams[constants.BE_MAXMEM])

    # Device control
    # deny direct device access
    out.append("lxc.cgroup.devices.deny = a")
    dev_specs = instance.hvparams[constants.HV_LXC_DEVICES]
    for dev_spec in dev_specs.split(","):
      out.append("lxc.cgroup.devices.allow = %s" % dev_spec)

    # Networking
    for idx, nic in enumerate(instance.nics):
      out.append("# NIC %d" % idx)
      mode = nic.nicparams[constants.NIC_MODE]
      link = nic.nicparams[constants.NIC_LINK]
      if mode == constants.NIC_MODE_BRIDGED:
        out.append("lxc.network.type = veth")
        out.append("lxc.network.link = %s" % link)
      else:
        raise errors.HypervisorError("LXC hypervisor only supports"
                                     " bridged mode (NIC %d has mode %s)" %
                                     (idx, mode))
      out.append("lxc.network.hwaddr = %s" % nic.mac)
      out.append("lxc.network.flags = up")

    # Capabilities
    for cap in self._GetInstanceDropCapabilities(instance.hvparams):
      out.append("lxc.cap.drop = %s" % cap)

    return "\n".join(out) + "\n"

  @classmethod
  def _GetCgroupEnabledKernelSubsystems(cls):
    """Return cgroup subsystems list that are enabled in current kernel.

    """
    try:
      subsys_table = utils.ReadFile(cls._PROC_CGROUPS_FILE)
    except EnvironmentError, err:
      raise HypervisorError("Failed to read cgroup info from %s: %s"
                            % (cls._PROC_CGROUPS_FILE, err))
    return [x.split(None, 1)[0] for x in subsys_table.split("\n")
            if x and not x.startswith("#")]

  @classmethod
  def _EnsureCgroupMounts(cls, hvparams=None):
    """Ensures all cgroup subsystems required to run LXC container are mounted.

    """
    # Check cgroup subsystems required by the Ganeti LXC hypervisor
    for subsystem in cls._REQUIRED_CGROUP_SUBSYSTEMS:
      cls._GetOrPrepareCgroupSubsysMountPoint(subsystem)

    # Check cgroup subsystems required by the LXC
    if hvparams is None or not hvparams[constants.HV_LXC_CGROUP_USE]:
      enable_subsystems = cls._GetCgroupEnabledKernelSubsystems()
    else:
      enable_subsystems = hvparams[constants.HV_LXC_CGROUP_USE].split(",")

    for subsystem in enable_subsystems:
      cls._GetOrPrepareCgroupSubsysMountPoint(subsystem)

  @classmethod
  def _PrepareInstanceRootFsBdev(cls, storage_path, stash):
    """Return mountable path for storage_path.

    This function creates a partition mapping for storage_path and returns the
    first partition device path as a rootfs partition, and stashes the loopback
    device path.
    If storage_path is not a multi-partition block device, just return
    storage_path.

    """
    try:
      ret = utils.CreateBdevPartitionMapping(storage_path)
    except errors.CommandError, err:
      raise HypervisorError("Failed to create partition mapping for %s"
                            ": %s" % (storage_path, err))

    if ret is None:
      return storage_path
    else:
      loop_dev_path, dm_dev_paths = ret
      stash[cls._STASH_KEY_ALLOCATED_LOOP_DEV] = loop_dev_path
      return dm_dev_paths[0]

  @classmethod
  def _WaitForInstanceState(cls, instance_name, state, timeout):
    """Wait for an instance state transition within timeout

    Return True if an instance state changed to the desired state within
    timeout secs.

    """
    result = utils.RunCmd(["lxc-wait", "-n", instance_name, "-s", state],
                          timeout=timeout)
    if result.failed_by_timeout:
      return False
    elif result.failed:
      raise HypervisorError("Failure while waiting for instance state"
                            " transition: %s" % result.output)
    else:
      return True

  def _SpawnLXC(self, instance, log_file, conf_file):
    """Execute lxc-start and wait until container health is confirmed.

    """
    lxc_start_cmd = [
      "lxc-start",
      "-n", instance.name,
      "-o", log_file,
      "-l", "DEBUG",
      "-f", conf_file,
      "-d"
      ]

    result = utils.RunCmd(lxc_start_cmd)
    if result.failed:
      raise HypervisorError("Failed to start instance %s : %s" %
                            (instance.name, result.output))

    lxc_startup_wait = instance.hvparams[constants.HV_LXC_STARTUP_WAIT]
    if not self._WaitForInstanceState(instance.name,
                                      constants.LXC_STATE_RUNNING,
                                      lxc_startup_wait):
      raise HypervisorError("Instance %s state didn't change to RUNNING within"
                            " %s secs" % (instance.name, lxc_startup_wait))

    # Ensure that the instance is running correctly after being daemonized
    if not self._IsInstanceAlive(instance.name):
      raise HypervisorError("Failed to start instance %s :"
                            " lxc process exited after being daemonized" %
                            instance.name)

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    For LXC, we try to mount the block device and execute 'lxc-start'.
    We use volatile containers.

    """
    stash = {}

    # Since LXC version >= 1.0.0, the LXC strictly requires all cgroup
    # subsystems mounted before starting a container.
    # Try to mount all cgroup subsystems needed to start a LXC container.
    self._EnsureCgroupMounts(instance.hvparams)

    root_dir = self._InstanceDir(instance.name)
    try:
      utils.EnsureDirs([(root_dir, self._DIR_MODE)])
    except errors.GenericError, err:
      raise HypervisorError("Creating instance directory failed: %s", str(err))

    log_file = self._InstanceLogFilePath(instance)
    if not os.path.exists(log_file):
      try:
        utils.WriteFile(log_file, data="", mode=constants.SECURE_FILE_MODE)
      except EnvironmentError, err:
        raise errors.HypervisorError("Creating hypervisor log file %s for"
                                     " instance %s failed: %s" %
                                     (log_file, instance.name, err))

    try:
      if not block_devices:
        raise HypervisorError("LXC needs at least one disk")

      sda_dev_path = block_devices[0][1]
      # LXC needs to use partition mapping devices to access each partition
      # of the storage
      sda_dev_path = self._PrepareInstanceRootFsBdev(sda_dev_path, stash)
      conf_file = self._InstanceConfFilePath(instance.name)
      conf = self._CreateConfigFile(instance, sda_dev_path)
      utils.WriteFile(conf_file, data=conf)

      logging.info("Starting LXC container")
      try:
        self._SpawnLXC(instance, log_file, conf_file)
      except:
        logging.error("Failed to start instance %s. Please take a look at %s to"
                      " see LXC errors.", instance.name, log_file)
        raise
    except:
      # Save the original error
      exc_info = sys.exc_info()
      try:
        self._CleanupInstance(instance.name, stash)
      except HypervisorError, err:
        logging.warn("Cleanup for instance %s incomplete: %s",
                     instance.name, err)
      raise exc_info[0], exc_info[1], exc_info[2]

    self._SaveInstanceStash(instance.name, stash)

  def StopInstance(self, instance, force=False, retry=False, name=None,
                   timeout=None):
    """Stop an instance.

    """
    assert(timeout is None or force is not None)

    if name is None:
      name = instance.name

    if self._IsInstanceAlive(instance.name):
      lxc_stop_cmd = ["lxc-stop", "-n", name]

      if force:
        lxc_stop_cmd.append("--kill")
        result = utils.RunCmd(lxc_stop_cmd, timeout=timeout)
        if result.failed:
          raise HypervisorError("Failed to kill instance %s: %s" %
                                (name, result.output))
      else:
        # The --timeout=-1 option is needed to prevent lxc-stop performs
        # hard-stop(kill) for the container after the default timing out.
        lxc_stop_cmd.extend(["--nokill", "--timeout", "-1"])
        result = utils.RunCmd(lxc_stop_cmd, timeout=timeout)
        if result.failed:
          logging.error("Failed to stop instance %s: %s", name, result.output)

  def RebootInstance(self, instance):
    """Reboot an instance.

    """
    if "sys_boot" in self._GetInstanceDropCapabilities(instance.hvparams):
      raise HypervisorError("The LXC container can't perform a reboot with the"
                            " SYS_BOOT capability dropped.")

    # We can't use the --timeout=-1 approach as same as the StopInstance due to
    # the following patch was applied in lxc-1.0.5 and we are supporting
    # LXC >= 1.0.0.
    # http://lists.linuxcontainers.org/pipermail/lxc-devel/2014-July/009742.html
    result = utils.RunCmd(["lxc-stop", "-n", instance.name, "--reboot",
                           "--timeout", str(self._REBOOT_TIMEOUT)])
    if result.failed:
      raise HypervisorError("Failed to reboot instance %s: %s" %
                            (instance.name, result.output))

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    mem_in_bytes = mem * 1024 ** 2
    current_mem_usage = self._GetCgroupMemoryLimit(instance.name)
    shrinking = mem_in_bytes <= current_mem_usage

    # memory.memsw.limit_in_bytes is the superlimit of the memory.limit_in_bytes
    # so the order of setting these parameters is quite important.
    cgparams = ["memory.memsw.limit_in_bytes", "memory.limit_in_bytes"]
    if shrinking:
      cgparams.reverse()

    for i, cgparam in enumerate(cgparams):
      try:
        self._SetCgroupInstanceValue(instance.name, cgparam, str(mem_in_bytes))
      except EnvironmentError, err:
        if shrinking and err.errno == errno.EBUSY:
          logging.warn("Unable to reclaim memory or swap usage from instance"
                       " %s", instance.name)
        # Restore changed parameters for an atomicity
        for restore_param in cgparams[0:i]:
          try:
            self._SetCgroupInstanceValue(instance.name, restore_param,
                                         str(current_mem_usage))
          except EnvironmentError, restore_err:
            logging.warn("Can't restore the cgroup parameter %s of %s: %s",
                         restore_param, instance.name, restore_err)

        raise HypervisorError("Failed to balloon the memory of %s, can't set"
                              " cgroup parameter %s: %s" %
                              (instance.name, cgparam, err))

  def GetNodeInfo(self, hvparams=None):
    """Return information about the node.

    See L{BaseHypervisor.GetLinuxNodeInfo}.

    """
    return self.GetLinuxNodeInfo()

  @classmethod
  def GetInstanceConsole(cls, instance, primary_node, node_group,
                         hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    ndparams = node_group.FillND(primary_node)
    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_SSH,
                                   host=primary_node.name,
                                   port=ndparams.get(constants.ND_SSH_PORT),
                                   user=constants.SSH_CONSOLE_USER,
                                   command=["lxc-console", "-n", instance.name])

  @classmethod
  def _ParseLXCVersion(cls, version_string):
    """Return a parsed result of lxc version string.

    @return: tuple of major, minor and micro version number
    @rtype: tuple(int, int, int)

    """
    match = cls._LXC_VERSION_RE.match(version_string)
    return tuple(map(int, match.groups())) if match else None

  @classmethod
  def _VerifyLXCCommands(cls):
    """Verify the validity of lxc command line tools.

    @rtype: list(str)
    @return: list of problem descriptions. the blank list will be returned if
             there is no problem.

    """
    version_required = cls._ParseLXCVersion(cls._LXC_MIN_VERSION_REQUIRED)
    msgs = []
    for cmd in cls._LXC_COMMANDS_REQUIRED:
      try:
        # lxc-ls needs special checking procedure.
        # there are two different version of lxc-ls, one is written in python
        # and the other is written in shell script.
        # we have to ensure the python version of lxc-ls is installed.
        if cmd == "lxc-ls":
          help_string = utils.RunCmd(["lxc-ls", "--help"]).output
          if "--running" not in help_string:
            # shell script version has no --running switch
            msgs.append("The python version of 'lxc-ls' is required."
                        " Maybe lxc was installed without --enable-python")
        else:
          result = utils.RunCmd([cmd, "--version"])
          if result.failed:
            msgs.append("Can't get version info from %s: %s" %
                        (cmd, result.output))
          else:
            version_str = result.stdout.strip()
            version = cls._ParseLXCVersion(version_str)
            if version:
              if version < version_required:
                msgs.append("LXC version >= %s is required but command %s has"
                            " version %s" %
                            (cls._LXC_MIN_VERSION_REQUIRED, cmd, version_str))
            else:
              msgs.append("Can't parse version info from %s output: %s" %
                          (cmd, version_str))
      except errors.OpExecError:
        msgs.append("Required command %s not found" % cmd)

    return msgs

  def Verify(self, hvparams=None):
    """Verify the hypervisor.

    For the LXC manager, it just checks the existence of the base dir.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be verified against; not used here

    @return: Problem description if something is wrong, C{None} otherwise

    """
    msgs = []

    if not os.path.exists(self._ROOT_DIR):
      msgs.append("The required directory '%s' does not exist" %
                  self._ROOT_DIR)

    try:
      self._EnsureCgroupMounts(hvparams)
    except errors.HypervisorError, err:
      msgs.append(str(err))

    msgs.extend(self._VerifyLXCCommands())

    return self._FormatVerifyResults(msgs)

  @classmethod
  def PowercycleNode(cls, hvparams=None):
    """LXC powercycle, just a wrapper over Linux powercycle.

    @type hvparams: dict of strings
    @param hvparams: hypervisor params to be used on this node

    """
    cls.LinuxPowercycle()

  def MigrateInstance(self, cluster_name, instance, target, live):
    """Migrate an instance.

    @type cluster_name: string
    @param cluster_name: name of the cluster
    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: hostname (usually ip) of the target node
    @type live: boolean
    @param live: whether to do a live or non-live migration

    """
    raise HypervisorError("Migration is not supported by the LXC hypervisor")

  def GetMigrationStatus(self, instance):
    """Get the migration status

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    raise HypervisorError("Migration is not supported by the LXC hypervisor")
