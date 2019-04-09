#
#

# Copyright (C) 2010, 2013, 2014, 2015 Google Inc.
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


def _CreateBlankFile(path, mode):
  """Create blank file.

  Create a blank file for the path with specified mode.
  An existing file will be overwritten.

  """
  try:
    utils.WriteFile(path, data="", mode=mode)
  except EnvironmentError as err:
    raise HypervisorError("Failed to create file %s: %s" % (path, err))


class LXCVersion(tuple):
  """LXC version class.

  """
  # Let beta version following micro version, but don't care about it
  _VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")

  @classmethod
  def _Parse(cls, version_string):
    """Parse a passed string as an LXC version string.

    @param version_string: a valid LXC version string
    @type version_string: string
    @raise ValueError: if version_string is an invalid LXC version string
    @rtype tuple(int, int, int)
    @return (major_num, minor_num, micro_num)

    """
    match = cls._VERSION_RE.match(version_string)
    if match:
      return tuple(map(int, match.groups()))
    else:
      raise ValueError("'%s' is not a valid LXC version string" %
                       version_string)

  def __new__(cls, version_string):
    version = super(LXCVersion, cls).__new__(cls, cls._Parse(version_string))
    version.original_string = version_string
    return version

  def __str__(self):
    return self.original_string


class LXCHypervisor(hv_base.BaseHypervisor):
  """LXC-based virtualization.

  """
  _ROOT_DIR = pathutils.RUN_DIR + "/lxc"
  _LOG_DIR = pathutils.LOG_DIR + "/lxc"

  # The instance directory has to be structured in a way that would allow it to
  # be passed as an argument of the --lxcpath option in lxc- commands.
  # This means that:
  # Each LXC instance should have a directory carrying their name under this
  # directory.
  # Each instance directory should contain the "config" file that contains the
  # LXC container configuration of an instance.
  #
  # Therefore the structure of the directory tree should be:
  #
  #   _INSTANCE_DIR
  #   \_ instance1
  #      \_ config
  #   \_ instance2
  #      \_ config
  #
  # Other instance specific files can also be placed under an instance
  # directory.
  _INSTANCE_DIR = _ROOT_DIR + "/instance"

  _CGROUP_ROOT_DIR = _ROOT_DIR + "/cgroup"
  _PROC_CGROUPS_FILE = "/proc/cgroups"
  _PROC_SELF_CGROUP_FILE = "/proc/self/cgroup"

  _LXC_MIN_VERSION_REQUIRED = LXCVersion("1.0.0")
  _LXC_COMMANDS_REQUIRED = [
    "lxc-console",
    "lxc-ls",
    "lxc-start",
    "lxc-stop",
    "lxc-wait",
    ]

  _DIR_MODE = 0o755
  _STASH_KEY_ALLOCATED_LOOP_DEV = "allocated_loopdev"

  _MEMORY_PARAMETER = "memory.limit_in_bytes"
  _MEMORY_SWAP_PARAMETER = "memory.memsw.limit_in_bytes"

  PARAMETERS = {
    constants.HV_CPU_MASK: hv_base.OPT_CPU_MASK_CHECK,
    constants.HV_LXC_DEVICES: hv_base.NO_CHECK,
    constants.HV_LXC_DROP_CAPABILITIES: hv_base.NO_CHECK,
    constants.HV_LXC_EXTRA_CGROUPS: hv_base.NO_CHECK,
    constants.HV_LXC_EXTRA_CONFIG: hv_base.NO_CHECK,
    constants.HV_LXC_NUM_TTYS: hv_base.REQ_NONNEGATIVE_INT_CHECK,
    constants.HV_LXC_STARTUP_TIMEOUT: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    }

  _REBOOT_TIMEOUT = 120 # secs
  _REQUIRED_CGROUP_SUBSYSTEMS = [
    "cpuset",
    "memory",
    "devices",
    "cpuacct",
    ]

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    self._EnsureDirectoryExistence()

  @classmethod
  def _InstanceDir(cls, instance_name):
    """Return the root directory for an instance.

    """
    return utils.PathJoin(cls._INSTANCE_DIR, instance_name)

  @classmethod
  def _InstanceConfFilePath(cls, instance_name):
    """Return the configuration file for an instance.

    """
    return utils.PathJoin(cls._InstanceDir(instance_name), "config")

  @classmethod
  def _InstanceLogFilePath(cls, instance):
    """Return the log file for an instance.

    @type instance: L{objects.Instance}

    """
    filename = "%s.%s.log" % (instance.name, instance.uuid)
    return utils.PathJoin(cls._LOG_DIR, filename)

  @classmethod
  def _InstanceConsoleLogFilePath(cls, instance_name):
    """Return the console log file path for an instance.

    """
    return utils.PathJoin(cls._InstanceDir(instance_name), "console.log")

  @classmethod
  def _InstanceStashFilePath(cls, instance_name):
    """Return the stash file path for an instance.

    The stash file is used to keep information needed to clean up after the
    destruction of the instance.

    """
    return utils.PathJoin(cls._InstanceDir(instance_name), "stash")

  def _EnsureDirectoryExistence(self):
    """Ensures all the directories needed for LXC use exist.

    """
    utils.EnsureDirs([
      (self._ROOT_DIR, self._DIR_MODE),
      (self._LOG_DIR, 0o750),
      (self._INSTANCE_DIR, 0o750),
      ])

  def _SaveInstanceStash(self, instance_name, data):
    """Save data to the instance stash file in serialized format.

    """
    stash_file = self._InstanceStashFilePath(instance_name)
    serialized = serializer.Dump(data)
    try:
      utils.WriteFile(stash_file, data=serialized,
                      mode=constants.SECURE_FILE_MODE)
    except EnvironmentError as err:
      raise HypervisorError("Failed to save instance stash file %s : %s" %
                            (stash_file, err))

  def _LoadInstanceStash(self, instance_name):
    """Load information stashed in file which was created by
    L{_SaveInstanceStash}.

    """
    stash_file = self._InstanceStashFilePath(instance_name)
    try:
      return serializer.Load(utils.ReadFile(stash_file))
    except (EnvironmentError, ValueError) as err:
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
      except EnvironmentError as err:
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
    except errors.CommandError as err:
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
    except EnvironmentError as err:
      raise HypervisorError("Failed to read %s : %s" %
                            (cls._PROC_SELF_CGROUP_FILE, err))

    cgroups = {}
    for line in filter(None, cgroup_list.split("\n")):
      _, subsystems, hierarchy = line.split(":")
      for subsys in subsystems.split(","):
        cgroups[subsys] = hierarchy[1:] # discard first '/'

    return cgroups

  @classmethod
  def _GetCgroupSubsysDir(cls, subsystem):
    """Return the directory of the cgroup subsystem we use.

    @type subsystem: string
    @param subsystem: cgroup subsystem name
    @rtype: string
    @return: path of the hierarchy directory for the subsystem

    """
    subsys_dir = cls._GetOrPrepareCgroupSubsysMountPoint(subsystem)
    base_group = cls._GetCurrentCgroupSubsysGroups().get(subsystem, "")

    return utils.PathJoin(subsys_dir, base_group, "lxc")

  @classmethod
  def _GetCgroupParamPath(cls, param_name, instance_name=None):
    """Return the path of the specified cgroup parameter file.

    @type param_name: string
    @param param_name: cgroup subsystem parameter name
    @rtype: string
    @return: path of the cgroup subsystem parameter file

    """
    subsystem = param_name.split(".", 1)[0]
    subsys_dir = cls._GetCgroupSubsysDir(subsystem)
    if instance_name is not None:
      return utils.PathJoin(subsys_dir, instance_name, param_name)
    else:
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
    param_path = cls._GetCgroupParamPath(param_name,
                                         instance_name=instance_name)
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
    param_path = cls._GetCgroupParamPath(param_name,
                                         instance_name=instance_name)
    # When interacting with cgroup fs, errno is quite important information
    # to see what happened when setting a cgroup parameter, so just throw
    # an error to the upper level.
    # e.g., we could know that the container can't reclaim its memory by
    #       checking if the errno is EBUSY when setting the
    #       memory.memsw.limit_in_bytes.
    fd = -1
    try:
      fd = os.open(param_path, os.O_WRONLY)
      os.write(fd, param_value.encode("ascii"))
    finally:
      if fd != -1:
        os.close(fd)

  @classmethod
  def _IsCgroupParameterPresent(cls, parameter, hvparams=None):
    """Return whether a cgroup parameter can be used.

    This is checked by seeing whether there is a file representation of the
    parameter in the location where the cgroup is mounted.

    @type parameter: string
    @param parameter: The name of the parameter.
    @param hvparams: dict
    @param hvparams: The hypervisor parameters, optional.
    @rtype: boolean

    """
    cls._EnsureCgroupMounts(hvparams)
    param_path = cls._GetCgroupParamPath(parameter)

    return os.path.exists(param_path)

  @classmethod
  def _GetCgroupCpuList(cls, instance_name):
    """Return the list of CPU ids for an instance.

    """
    try:
      cpumask = cls._GetCgroupInstanceValue(instance_name, "cpuset.cpus")
    except EnvironmentError as err:
      raise errors.HypervisorError("Getting CPU list for instance"
                                   " %s failed: %s" % (instance_name, err))

    return utils.ParseCpuMask(cpumask)

  @classmethod
  def _GetCgroupCpuUsage(cls, instance_name):
    """Return the CPU usage of an instance.

    """
    try:
      cputime_ns = cls._GetCgroupInstanceValue(instance_name, "cpuacct.usage")
    except EnvironmentError as err:
      raise HypervisorError("Failed to get the cpu usage of %s: %s" %
                            (instance_name, err))

    return float(cputime_ns) / 10 ** 9 # nano secs to float secs

  @classmethod
  def _GetCgroupMemoryLimit(cls, instance_name):
    """Return the memory limit for an instance

    """
    try:
      mem_limit = cls._GetCgroupInstanceValue(instance_name,
                                              "memory.limit_in_bytes")
      return int(mem_limit)
    except EnvironmentError as err:
      raise HypervisorError("Can't get instance memory limit of %s: %s" %
                            (instance_name, err))

  def ListInstances(self, hvparams=None):
    """Get the list of running instances.

    """
    return self._ListAliveInstances()

  @classmethod
  def _IsInstanceAlive(cls, instance_name):
    """Return True if instance is alive.

    """
    result = utils.RunCmd(["lxc-ls", "--running", re.escape(instance_name)])
    if result.failed:
      raise HypervisorError("Failed to get running LXC containers list: %s" %
                            result.output)

    return instance_name in result.stdout.split()

  @classmethod
  def _ListAliveInstances(cls):
    """Return list of alive instances.

    """
    result = utils.RunCmd(["lxc-ls", "--running"])
    if result.failed:
      raise HypervisorError("Failed to get running LXC containers list: %s" %
                            result.output)

    return result.stdout.split()

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: hvparams to be used with this instance
    @rtype: tuple of strings
    @return: (name, id, memory, vcpus, stat, times)

    """
    if not self._IsInstanceAlive(instance_name):
      return None

    return self._GetInstanceInfoInner(instance_name)

  def _GetInstanceInfoInner(self, instance_name):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @rtype: tuple of strings
    @return: (name, id, memory, vcpus, stat, times)

    """

    cpu_list = self._GetCgroupCpuList(instance_name)
    memory = self._GetCgroupMemoryLimit(instance_name) // (1024 ** 2)
    cputime = self._GetCgroupCpuUsage(instance_name)
    return (instance_name, 0, memory, len(cpu_list),
            hv_base.HvInstanceState.RUNNING, cputime)

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameter
    @return: [(name, id, memory, vcpus, stat, times),...]

    """
    data = []
    running_instances = self._ListAliveInstances()
    filter_fn = lambda x: os.path.isdir(utils.PathJoin(self._INSTANCE_DIR, x))
    for dirname in filter(filter_fn, os.listdir(self._INSTANCE_DIR)):
      if dirname not in running_instances:
        continue
      try:
        info = self._GetInstanceInfoInner(dirname)
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
    num_ttys = instance.hvparams[constants.HV_LXC_NUM_TTYS]
    if num_ttys: # if it is the number greater than 0
      out.append("lxc.tty = %s" % num_ttys)

    # console log file
    # After the following patch was applied, we lost the console log file output
    # until the lxc.console.logfile parameter was introduced in 1.0.6.
    # https://
    # lists.linuxcontainers.org/pipermail/lxc-devel/2014-March/008470.html
    lxc_version = self._GetLXCVersionFromCmd("lxc-start")
    if lxc_version >= LXCVersion("1.0.6"):
      console_log_path = self._InstanceConsoleLogFilePath(instance.name)
      _CreateBlankFile(console_log_path, constants.SECURE_FILE_MODE)
      out.append("lxc.console.logfile = %s" % console_log_path)
    else:
      logging.warn("Console log file is not supported in LXC version %s,"
                   " disabling.", lxc_version)

    # root FS
    out.append("lxc.rootfs = %s" % sda_dev_path)

    # Necessary file systems
    out.append("lxc.mount.entry = proc proc proc nodev,noexec,nosuid 0 0")
    out.append("lxc.mount.entry = sysfs sys sysfs defaults 0 0")

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
    out.append("lxc.cgroup.memory.limit_in_bytes = %dM" %
               instance.beparams[constants.BE_MAXMEM])
    if LXCHypervisor._IsCgroupParameterPresent(self._MEMORY_SWAP_PARAMETER,
                                               instance.hvparams):
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

    # Extra config
    # TODO: Currently a configuration parameter that includes comma
    # in its value can't be added via this parameter.
    # Make this parameter able to read from a file once the
    # "parameter from a file" feature added.
    extra_configs = instance.hvparams[constants.HV_LXC_EXTRA_CONFIG]
    if extra_configs:
      out.append("# User defined configs")
      out.extend(extra_configs.split(","))

    return "\n".join(out) + "\n"

  @classmethod
  def _GetCgroupEnabledKernelSubsystems(cls):
    """Return cgroup subsystems list that are enabled in current kernel.

    """
    try:
      subsys_table = utils.ReadFile(cls._PROC_CGROUPS_FILE)
    except EnvironmentError as err:
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
    if hvparams is None or not hvparams[constants.HV_LXC_EXTRA_CGROUPS]:
      enable_subsystems = cls._GetCgroupEnabledKernelSubsystems()
    else:
      enable_subsystems = hvparams[constants.HV_LXC_EXTRA_CGROUPS].split(",")

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
    except errors.CommandError as err:
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

    lxc_startup_timeout = instance.hvparams[constants.HV_LXC_STARTUP_TIMEOUT]
    if not self._WaitForInstanceState(instance.name,
                                      constants.LXC_STATE_RUNNING,
                                      lxc_startup_timeout):
      raise HypervisorError("Instance %s state didn't change to RUNNING within"
                            " %s secs" % (instance.name, lxc_startup_timeout))

    # Ensure that the instance is running correctly after being daemonized
    if not self._IsInstanceAlive(instance.name):
      raise HypervisorError("Failed to start instance %s :"
                            " lxc process exited after being daemonized" %
                            instance.name)

  @classmethod
  def _VerifyDiskRequirements(cls, block_devices):
    """Insures that the disks provided work with the current implementation.

    """
    if len(block_devices) == 0:
      raise HypervisorError("LXC cannot have diskless instances.")

    if len(block_devices) > 1:
      raise HypervisorError("At the moment, LXC cannot support more than one"
                            " disk attached to it. Please create this"
                            " instance anew with fewer disks.")

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    For LXC, we try to mount the block device and execute 'lxc-start'.
    We use volatile containers.

    """
    LXCHypervisor._VerifyDiskRequirements(block_devices)

    stash = {}

    # Since LXC version >= 1.0.0, the LXC strictly requires all cgroup
    # subsystems mounted before starting a container.
    # Try to mount all cgroup subsystems needed to start a LXC container.
    self._EnsureCgroupMounts(instance.hvparams)

    root_dir = self._InstanceDir(instance.name)
    try:
      utils.EnsureDirs([(root_dir, self._DIR_MODE)])
    except errors.GenericError as err:
      raise HypervisorError("Creating instance directory failed: %s", str(err))

    log_file = self._InstanceLogFilePath(instance)
    if not os.path.exists(log_file):
      _CreateBlankFile(log_file, constants.SECURE_FILE_MODE)

    try:
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
      except HypervisorError as err:
        logging.warn("Cleanup for instance %s incomplete: %s",
                     instance.name, err)
      raise exc_info[0](exc_info[1]).with_traceback(exc_info[2])

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

    # The memsw.limit_in_bytes parameter might be present depending on kernel
    # parameters.
    # If present, it has to be modified at the same time as limit_in_bytes.
    if LXCHypervisor._IsCgroupParameterPresent(self._MEMORY_SWAP_PARAMETER,
                                               instance.hvparams):
      # memory.memsw.limit_in_bytes is the superlimit of memory.limit_in_bytes
      # so the order of setting these parameters is quite important.
      cgparams = [self._MEMORY_SWAP_PARAMETER, self._MEMORY_PARAMETER]
    else:
      cgparams = [self._MEMORY_PARAMETER]

    if shrinking:
      cgparams.reverse()

    for i, cgparam in enumerate(cgparams):
      try:
        self._SetCgroupInstanceValue(instance.name, cgparam, str(mem_in_bytes))
      except EnvironmentError as err:
        if shrinking and err.errno == errno.EBUSY:
          logging.warn("Unable to reclaim memory or swap usage from instance"
                       " %s", instance.name)
        # Restore changed parameters for an atomicity
        for restore_param in cgparams[0:i]:
          try:
            self._SetCgroupInstanceValue(instance.name, restore_param,
                                         str(current_mem_usage))
          except EnvironmentError as restore_err:
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
  def _GetLXCVersionFromCmd(cls, from_cmd):
    """Return the LXC version currently used in the system.

    Version information will be retrieved by command specified by from_cmd.

    @param from_cmd: the lxc command used to retrieve version information
    @type from_cmd: string
    @rtype: L{LXCVersion}
    @return: a version object which represents the version retrieved from the
             command

    """
    result = utils.RunCmd([from_cmd, "--version"])
    if result.failed:
      raise HypervisorError("Failed to get version info from command %s: %s" %
                            (from_cmd, result.output))

    try:
      return LXCVersion(result.stdout.strip())
    except ValueError as err:
      raise HypervisorError("Can't parse LXC version from %s: %s" %
                            (from_cmd, err))

  @classmethod
  def _VerifyLXCCommands(cls):
    """Verify the validity of lxc command line tools.

    @rtype: list(str)
    @return: list of problem descriptions. the blank list will be returned if
             there is no problem.

    """
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
          try:
            version = cls._GetLXCVersionFromCmd(cmd)
          except HypervisorError as err:
            msgs.append(str(err))
            continue

          if version < cls._LXC_MIN_VERSION_REQUIRED:
            msgs.append("LXC version >= %s is required but command %s has"
                        " version %s" %
                        (cls._LXC_MIN_VERSION_REQUIRED, cmd, version))
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
    except errors.HypervisorError as err:
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
