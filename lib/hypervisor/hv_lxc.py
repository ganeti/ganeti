#
#

# Copyright (C) 2010 Google Inc.
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

import os
import os.path
import time
import logging

from ganeti import constants
from ganeti import errors # pylint: disable-msg=W0611
from ganeti import utils
from ganeti import objects
from ganeti.hypervisor import hv_base
from ganeti.errors import HypervisorError


class LXCHypervisor(hv_base.BaseHypervisor):
  """LXC-based virtualization.

  Since current (Spring 2010) distributions are not yet ready for
  running under a container, the following changes must be done
  manually:
    - remove udev
    - disable the kernel log component of sysklogd/rsyslog/etc.,
      otherwise they will fail to read the log, and at least rsyslog
      will fill the filesystem with error messages

  TODO:
    - move hardcoded parameters into hypervisor parameters, once we
      have the container-parameter support
    - implement memory limits, but only optionally, depending on host
      kernel support

  Problems/issues:
    - LXC is very temperamental; in daemon mode, it succeeds or fails
      in launching the instance silently, without any error
      indication, and when failing it can leave network interfaces
      around, and future successful startups will list the instance
      twice
    - shutdown sequence of containers leaves the init 'dead', and the
      container effectively stopped, but LXC still believes the
      container to be running; need to investigate using the
      notify_on_release and release_agent feature of cgroups

  """
  _ROOT_DIR = constants.RUN_GANETI_DIR + "/lxc"
  _DEVS = [
    "c 1:3",   # /dev/null
    "c 1:5",   # /dev/zero
    "c 1:7",   # /dev/full
    "c 1:8",   # /dev/random
    "c 1:9",   # /dev/urandom
    "c 1:10",  # /dev/aio
    "c 5:0",   # /dev/tty
    "c 5:1",   # /dev/console
    "c 5:2",   # /dev/ptmx
    "c 136:*", # first block of Unix98 PTY slaves
    ]
  _DENIED_CAPABILITIES = [
    "mac_override",    # Allow MAC configuration or state changes
    # TODO: remove sys_admin too, for safety
    #"sys_admin",       # Perform  a range of system administration operations
    "sys_boot",        # Use reboot(2) and kexec_load(2)
    "sys_module",      # Load  and  unload kernel modules
    "sys_time",        # Set  system  clock, set real-time (hardware) clock
    ]
  _DIR_MODE = 0755

  PARAMETERS = {
    constants.HV_CPU_MASK: hv_base.OPT_CPU_MASK_CHECK,
    }

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    utils.EnsureDirs([(self._ROOT_DIR, self._DIR_MODE)])

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
  def _InstanceConfFile(cls, instance_name):
    """Return the configuration file for an instance.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name + ".conf")

  @classmethod
  def _InstanceLogFile(cls, instance_name):
    """Return the log file for an instance.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name + ".log")

  @classmethod
  def _GetCgroupMountPoint(cls):
    for _, mountpoint, fstype, _ in utils.GetMounts():
      if fstype == "cgroup":
        return mountpoint
    raise errors.HypervisorError("The cgroup filesystem is not mounted")

  @classmethod
  def _GetCgroupCpuList(cls, instance_name):
    """Return the list of CPU ids for an instance.

    """
    cgroup = cls._GetCgroupMountPoint()
    try:
      cpus = utils.ReadFile(utils.PathJoin(cgroup,
                                           instance_name,
                                           "cpuset.cpus"))
    except EnvironmentError, err:
      raise errors.HypervisorError("Getting CPU list for instance"
                                   " %s failed: %s" % (instance_name, err))

    return utils.ParseCpuMask(cpus)

  def ListInstances(self):
    """Get the list of running instances.

    """
    result = utils.RunCmd(["lxc-ls"])
    if result.failed:
      raise errors.HypervisorError("Running lxc-ls failed: %s" % result.output)
    return result.stdout.splitlines()

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name

    @return: (name, id, memory, vcpus, stat, times)

    """
    # TODO: read container info from the cgroup mountpoint

    result = utils.RunCmd(["lxc-info", "-n", instance_name])
    if result.failed:
      raise errors.HypervisorError("Running lxc-info failed: %s" %
                                   result.output)
    # lxc-info output examples:
    # 'ganeti-lxc-test1' is STOPPED
    # 'ganeti-lxc-test1' is RUNNING
    _, state = result.stdout.rsplit(None, 1)
    if state != "RUNNING":
      return None

    cpu_list = self._GetCgroupCpuList(instance_name)
    return (instance_name, 0, 0, len(cpu_list), 0, 0)

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    @return: [(name, id, memory, vcpus, stat, times),...]

    """
    data = []
    for name in self.ListInstances():
      data.append(self.GetInstanceInfo(name))
    return data

  def _CreateConfigFile(self, instance, root_dir):
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
    out.append("lxc.rootfs = %s" % root_dir)

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

    # Device control
    # deny direct device access
    out.append("lxc.cgroup.devices.deny = a")
    for devinfo in self._DEVS:
      out.append("lxc.cgroup.devices.allow = %s rw" % devinfo)

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
    for cap in self._DENIED_CAPABILITIES:
      out.append("lxc.cap.drop = %s" % cap)

    return "\n".join(out) + "\n"

  def StartInstance(self, instance, block_devices):
    """Start an instance.

    For LCX, we try to mount the block device and execute 'lxc-start'.
    We use volatile containers.

    """
    root_dir = self._InstanceDir(instance.name)
    try:
      utils.EnsureDirs([(root_dir, self._DIR_MODE)])
    except errors.GenericError, err:
      raise HypervisorError("Creating instance directory failed: %s", str(err))

    conf_file = self._InstanceConfFile(instance.name)
    utils.WriteFile(conf_file, data=self._CreateConfigFile(instance, root_dir))

    log_file = self._InstanceLogFile(instance.name)
    if not os.path.exists(log_file):
      try:
        utils.WriteFile(log_file, data="", mode=constants.SECURE_FILE_MODE)
      except EnvironmentError, err:
        raise errors.HypervisorError("Creating hypervisor log file %s for"
                                     " instance %s failed: %s" %
                                     (log_file, instance.name, err))

    if not os.path.ismount(root_dir):
      if not block_devices:
        raise HypervisorError("LXC needs at least one disk")

      sda_dev_path = block_devices[0][1]
      result = utils.RunCmd(["mount", sda_dev_path, root_dir])
      if result.failed:
        raise HypervisorError("Mounting the root dir of LXC instance %s"
                              " failed: %s" % (instance.name, result.output))
    result = utils.RunCmd(["lxc-start", "-n", instance.name,
                           "-o", log_file,
                           "-l", "DEBUG",
                           "-f", conf_file, "-d"])
    if result.failed:
      raise HypervisorError("Running the lxc-start script failed: %s" %
                            result.output)

  def StopInstance(self, instance, force=False, retry=False, name=None):
    """Stop an instance.

    This method has complicated cleanup tests, as we must:
      - try to kill all leftover processes
      - try to unmount any additional sub-mountpoints
      - finally unmount the instance dir

    """
    if name is None:
      name = instance.name

    root_dir = self._InstanceDir(name)
    if not os.path.exists(root_dir):
      return

    if name in self.ListInstances():
      # Signal init to shutdown; this is a hack
      if not retry and not force:
        result = utils.RunCmd(["chroot", root_dir, "poweroff"])
        if result.failed:
          raise HypervisorError("Running 'poweroff' on the instance"
                                " failed: %s" % result.output)
      time.sleep(2)
      result = utils.RunCmd(["lxc-stop", "-n", name])
      if result.failed:
        logging.warning("Error while doing lxc-stop for %s: %s", name,
                        result.output)

    for mpath in self._GetMountSubdirs(root_dir):
      result = utils.RunCmd(["umount", mpath])
      if result.failed:
        logging.warning("Error while umounting subpath %s for instance %s: %s",
                        mpath, name, result.output)

    result = utils.RunCmd(["umount", root_dir])
    if result.failed and force:
      msg = ("Processes still alive in the chroot: %s" %
             utils.RunCmd("fuser -vm %s" % root_dir).output)
      logging.error(msg)
      raise HypervisorError("Unmounting the chroot dir failed: %s (%s)" %
                            (result.output, msg))

  def RebootInstance(self, instance):
    """Reboot an instance.

    This is not (yet) implemented (in Ganeti) for the LXC hypervisor.

    """
    # TODO: implement reboot
    raise HypervisorError("The LXC hypervisor doesn't implement the"
                          " reboot functionality")

  def GetNodeInfo(self):
    """Return information about the node.

    This is just a wrapper over the base GetLinuxNodeInfo method.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available

    """
    return self.GetLinuxNodeInfo()

  @classmethod
  def GetInstanceConsole(cls, instance, hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_SSH,
                                   host=instance.primary_node,
                                   user=constants.GANETI_RUNAS,
                                   command=["lxc-console", "-n", instance.name])

  def Verify(self):
    """Verify the hypervisor.

    For the chroot manager, it just checks the existence of the base dir.

    """
    if not os.path.exists(self._ROOT_DIR):
      return "The required directory '%s' does not exist." % self._ROOT_DIR

  @classmethod
  def PowercycleNode(cls):
    """LXC powercycle, just a wrapper over Linux powercycle.

    """
    cls.LinuxPowercycle()

  def MigrateInstance(self, instance, target, live):
    """Migrate an instance.

    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: hostname (usually ip) of the target node
    @type live: boolean
    @param live: whether to do a live or non-live migration

    """
    raise HypervisorError("Migration is not supported by the LXC hypervisor")
