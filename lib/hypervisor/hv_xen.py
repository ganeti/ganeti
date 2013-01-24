#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""Xen hypervisors

"""

import logging
from cStringIO import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti.hypervisor import hv_base
from ganeti import netutils
from ganeti import objects
from ganeti import pathutils
from ganeti import ssconf


XEND_CONFIG_FILE = utils.PathJoin(pathutils.XEN_CONFIG_DIR, "xend-config.sxp")
XL_CONFIG_FILE = utils.PathJoin(pathutils.XEN_CONFIG_DIR, "xen/xl.conf")
VIF_BRIDGE_SCRIPT = utils.PathJoin(pathutils.XEN_CONFIG_DIR,
                                   "scripts/vif-bridge")
_DOM0_NAME = "Domain-0"


def _CreateConfigCpus(cpu_mask):
  """Create a CPU config string for Xen's config file.

  """
  # Convert the string CPU mask to a list of list of int's
  cpu_list = utils.ParseMultiCpuMask(cpu_mask)

  if len(cpu_list) == 1:
    all_cpu_mapping = cpu_list[0]
    if all_cpu_mapping == constants.CPU_PINNING_OFF:
      # If CPU pinning has 1 entry that's "all", then remove the
      # parameter from the config file
      return None
    else:
      # If CPU pinning has one non-all entry, mapping all vCPUS (the entire
      # VM) to one physical CPU, using format 'cpu = "C"'
      return "cpu = \"%s\"" % ",".join(map(str, all_cpu_mapping))
  else:

    def _GetCPUMap(vcpu):
      if vcpu[0] == constants.CPU_PINNING_ALL_VAL:
        cpu_map = constants.CPU_PINNING_ALL_XEN
      else:
        cpu_map = ",".join(map(str, vcpu))
      return "\"%s\"" % cpu_map

    # build the result string in format 'cpus = [ "c", "c", "c" ]',
    # where each c is a physical CPU number, a range, a list, or any
    # combination
    return "cpus = [ %s ]" % ", ".join(map(_GetCPUMap, cpu_list))


class XenHypervisor(hv_base.BaseHypervisor):
  """Xen generic hypervisor interface

  This is the Xen base class used for both Xen PVM and HVM. It contains
  all the functionality that is identical for both.

  """
  CAN_MIGRATE = True
  REBOOT_RETRY_COUNT = 60
  REBOOT_RETRY_INTERVAL = 10

  ANCILLARY_FILES = [
    XEND_CONFIG_FILE,
    XL_CONFIG_FILE,
    VIF_BRIDGE_SCRIPT,
    ]
  ANCILLARY_FILES_OPT = [
    XL_CONFIG_FILE,
    ]

  @staticmethod
  def _ConfigFileName(instance_name):
    """Get the config file name for an instance.

    @param instance_name: instance name
    @type instance_name: str
    @return: fully qualified path to instance config file
    @rtype: str

    """
    return utils.PathJoin(pathutils.XEN_CONFIG_DIR, instance_name)

  @classmethod
  def _WriteConfigFile(cls, instance, startup_memory, block_devices):
    """Write the Xen config file for the instance.

    """
    raise NotImplementedError

  @staticmethod
  def _WriteConfigFileStatic(instance_name, data):
    """Write the Xen config file for the instance.

    This version of the function just writes the config file from static data.

    """
    # just in case it exists
    utils.RemoveFile(utils.PathJoin(pathutils.XEN_CONFIG_DIR, "auto",
                                    instance_name))

    cfg_file = XenHypervisor._ConfigFileName(instance_name)
    try:
      utils.WriteFile(cfg_file, data=data)
    except EnvironmentError, err:
      raise errors.HypervisorError("Cannot write Xen instance configuration"
                                   " file %s: %s" % (cfg_file, err))

  @staticmethod
  def _ReadConfigFile(instance_name):
    """Returns the contents of the instance config file.

    """
    filename = XenHypervisor._ConfigFileName(instance_name)

    try:
      file_content = utils.ReadFile(filename)
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to load Xen config file: %s" % err)

    return file_content

  @staticmethod
  def _RemoveConfigFile(instance_name):
    """Remove the xen configuration file.

    """
    utils.RemoveFile(XenHypervisor._ConfigFileName(instance_name))

  @staticmethod
  def _RunXmList(xmlist_errors):
    """Helper function for L{_GetXMList} to run "xm list".

    """
    result = utils.RunCmd([constants.XEN_CMD, "list"])
    if result.failed:
      logging.error("xm list failed (%s): %s", result.fail_reason,
                    result.output)
      xmlist_errors.append(result)
      raise utils.RetryAgain()

    # skip over the heading
    return result.stdout.splitlines()[1:]

  @classmethod
  def _GetXMList(cls, include_node):
    """Return the list of running instances.

    If the include_node argument is True, then we return information
    for dom0 also, otherwise we filter that from the return value.

    @return: list of (name, id, memory, vcpus, state, time spent)

    """
    xmlist_errors = []
    try:
      lines = utils.Retry(cls._RunXmList, 1, 5, args=(xmlist_errors, ))
    except utils.RetryTimeout:
      if xmlist_errors:
        xmlist_result = xmlist_errors.pop()

        errmsg = ("xm list failed, timeout exceeded (%s): %s" %
                  (xmlist_result.fail_reason, xmlist_result.output))
      else:
        errmsg = "xm list failed"

      raise errors.HypervisorError(errmsg)

    result = []
    for line in lines:
      # The format of lines is:
      # Name      ID Mem(MiB) VCPUs State  Time(s)
      # Domain-0   0  3418     4 r-----    266.2
      data = line.split()
      if len(data) != 6:
        raise errors.HypervisorError("Can't parse output of xm list,"
                                     " line: %s" % line)
      try:
        data[1] = int(data[1])
        data[2] = int(data[2])
        data[3] = int(data[3])
        data[5] = float(data[5])
      except (TypeError, ValueError), err:
        raise errors.HypervisorError("Can't parse output of xm list,"
                                     " line: %s, error: %s" % (line, err))

      # skip the Domain-0 (optional)
      if include_node or data[0] != _DOM0_NAME:
        result.append(data)

    return result

  def ListInstances(self):
    """Get the list of running instances.

    """
    xm_list = self._GetXMList(False)
    names = [info[0] for info in xm_list]
    return names

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    @param instance_name: the instance name

    @return: tuple (name, id, memory, vcpus, stat, times)

    """
    xm_list = self._GetXMList(instance_name == _DOM0_NAME)
    result = None
    for data in xm_list:
      if data[0] == instance_name:
        result = data
        break
    return result

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    xm_list = self._GetXMList(False)
    return xm_list

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    """
    startup_memory = self._InstanceStartupMemory(instance)
    self._WriteConfigFile(instance, startup_memory, block_devices)
    cmd = [constants.XEN_CMD, "create"]
    if startup_paused:
      cmd.extend(["-p"])
    cmd.extend([self._ConfigFileName(instance.name)])
    result = utils.RunCmd(cmd)

    if result.failed:
      raise errors.HypervisorError("Failed to start instance %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))

  def StopInstance(self, instance, force=False, retry=False, name=None):
    """Stop an instance.

    """
    if name is None:
      name = instance.name

    if force:
      command = [constants.XEN_CMD, "destroy", name]
    else:
      command = [constants.XEN_CMD, "shutdown", name]
    result = utils.RunCmd(command)

    if result.failed:
      raise errors.HypervisorError("Failed to stop instance %s: %s, %s" %
                                   (name, result.fail_reason, result.output))

    # Remove configuration file if stopping/starting instance was successful
    self._RemoveConfigFile(name)

  def RebootInstance(self, instance):
    """Reboot an instance.

    """
    ini_info = self.GetInstanceInfo(instance.name)

    if ini_info is None:
      raise errors.HypervisorError("Failed to reboot instance %s,"
                                   " not running" % instance.name)

    result = utils.RunCmd([constants.XEN_CMD, "reboot", instance.name])
    if result.failed:
      raise errors.HypervisorError("Failed to reboot instance %s: %s, %s" %
                                   (instance.name, result.fail_reason,
                                    result.output))

    def _CheckInstance():
      new_info = self.GetInstanceInfo(instance.name)

      # check if the domain ID has changed or the run time has decreased
      if (new_info is not None and
          (new_info[1] != ini_info[1] or new_info[5] < ini_info[5])):
        return

      raise utils.RetryAgain()

    try:
      utils.Retry(_CheckInstance, self.REBOOT_RETRY_INTERVAL,
                  self.REBOOT_RETRY_INTERVAL * self.REBOOT_RETRY_COUNT)
    except utils.RetryTimeout:
      raise errors.HypervisorError("Failed to reboot instance %s: instance"
                                   " did not reboot in the expected interval" %
                                   (instance.name, ))

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    cmd = [constants.XEN_CMD, "mem-set", instance.name, mem]
    result = utils.RunCmd(cmd)
    if result.failed:
      raise errors.HypervisorError("Failed to balloon instance %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))
    cmd = ["sed", "-ie", "s/^memory.*$/memory = %s/" % mem]
    cmd.append(XenHypervisor._ConfigFileName(instance.name))
    result = utils.RunCmd(cmd)
    if result.failed:
      raise errors.HypervisorError("Failed to update memory for %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))

  def GetNodeInfo(self):
    """Return information about the node.

    @return: a dict with the following keys (memory values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available
          - nr_cpus: total number of CPUs
          - nr_nodes: in a NUMA system, the number of domains
          - nr_sockets: the number of physical CPU sockets in the node
          - hv_version: the hypervisor version in the form (major, minor)

    """
    result = utils.RunCmd([constants.XEN_CMD, "info"])
    if result.failed:
      logging.error("Can't run 'xm info' (%s): %s", result.fail_reason,
                    result.output)
      return None

    xmoutput = result.stdout.splitlines()
    result = {}
    cores_per_socket = threads_per_core = nr_cpus = None
    xen_major, xen_minor = None, None
    memory_total = None
    memory_free = None

    for line in xmoutput:
      splitfields = line.split(":", 1)

      if len(splitfields) > 1:
        key = splitfields[0].strip()
        val = splitfields[1].strip()

        # note: in xen 3, memory has changed to total_memory
        if key == "memory" or key == "total_memory":
          memory_total = int(val)
        elif key == "free_memory":
          memory_free = int(val)
        elif key == "nr_cpus":
          nr_cpus = result["cpu_total"] = int(val)
        elif key == "nr_nodes":
          result["cpu_nodes"] = int(val)
        elif key == "cores_per_socket":
          cores_per_socket = int(val)
        elif key == "threads_per_core":
          threads_per_core = int(val)
        elif key == "xen_major":
          xen_major = int(val)
        elif key == "xen_minor":
          xen_minor = int(val)

    if None not in [cores_per_socket, threads_per_core, nr_cpus]:
      result["cpu_sockets"] = nr_cpus / (cores_per_socket * threads_per_core)

    total_instmem = 0
    for (name, _, mem, vcpus, _, _) in self._GetXMList(True):
      if name == _DOM0_NAME:
        result["memory_dom0"] = mem
        result["dom0_cpus"] = vcpus

      # Include Dom0 in total memory usage
      total_instmem += mem

    if memory_free is not None:
      result["memory_free"] = memory_free

    if memory_total is not None:
      result["memory_total"] = memory_total

    # Calculate memory used by hypervisor
    if None not in [memory_total, memory_free, total_instmem]:
      result["memory_hv"] = memory_total - memory_free - total_instmem

    if not (xen_major is None or xen_minor is None):
      result[constants.HV_NODEINFO_KEY_VERSION] = (xen_major, xen_minor)

    return result

  @classmethod
  def GetInstanceConsole(cls, instance, hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_SSH,
                                   host=instance.primary_node,
                                   user=constants.SSH_CONSOLE_USER,
                                   command=[pathutils.XEN_CONSOLE_WRAPPER,
                                            constants.XEN_CMD, instance.name])

  def Verify(self):
    """Verify the hypervisor.

    For Xen, this verifies that the xend process is running.

    @return: Problem description if something is wrong, C{None} otherwise

    """
    result = utils.RunCmd([constants.XEN_CMD, "info"])
    if result.failed:
      return "'xm info' failed: %s, %s" % (result.fail_reason, result.output)

    return None

  @staticmethod
  def _GetConfigFileDiskData(block_devices, blockdev_prefix):
    """Get disk directive for xen config file.

    This method builds the xen config disk directive according to the
    given disk_template and block_devices.

    @param block_devices: list of tuples (cfdev, rldev):
        - cfdev: dict containing ganeti config disk part
        - rldev: ganeti.bdev.BlockDev object
    @param blockdev_prefix: a string containing blockdevice prefix,
                            e.g. "sd" for /dev/sda

    @return: string containing disk directive for xen instance config file

    """
    FILE_DRIVER_MAP = {
      constants.FD_LOOP: "file",
      constants.FD_BLKTAP: "tap:aio",
      }
    disk_data = []
    if len(block_devices) > 24:
      # 'z' - 'a' = 24
      raise errors.HypervisorError("Too many disks")
    namespace = [blockdev_prefix + chr(i + ord("a")) for i in range(24)]
    for sd_name, (cfdev, dev_path) in zip(namespace, block_devices):
      if cfdev.mode == constants.DISK_RDWR:
        mode = "w"
      else:
        mode = "r"
      if cfdev.dev_type == constants.LD_FILE:
        line = "'%s:%s,%s,%s'" % (FILE_DRIVER_MAP[cfdev.physical_id[0]],
                                  dev_path, sd_name, mode)
      else:
        line = "'phy:%s,%s,%s'" % (dev_path, sd_name, mode)
      disk_data.append(line)

    return disk_data

  def MigrationInfo(self, instance):
    """Get instance information to perform a migration.

    @type instance: L{objects.Instance}
    @param instance: instance to be migrated
    @rtype: string
    @return: content of the xen config file

    """
    return self._ReadConfigFile(instance.name)

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string
    @param info: content of the xen config file on the source node
    @type target: string
    @param target: target host (usually ip), on this node

    """
    pass

  def FinalizeMigrationDst(self, instance, info, success):
    """Finalize an instance migration.

    After a successful migration we write the xen config file.
    We do nothing on a failure, as we did not change anything at accept time.

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being finalized
    @type info: string
    @param info: content of the xen config file on the source node
    @type success: boolean
    @param success: whether the migration was a success or a failure

    """
    if success:
      self._WriteConfigFileStatic(instance.name, info)

  def MigrateInstance(self, instance, target, live):
    """Migrate an instance to a target node.

    The migration will not be attempted if the instance is not
    currently running.

    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: ip address of the target node
    @type live: boolean
    @param live: perform a live migration

    """
    if self.GetInstanceInfo(instance.name) is None:
      raise errors.HypervisorError("Instance not running, cannot migrate")

    port = instance.hvparams[constants.HV_MIGRATION_PORT]

    if (constants.XEN_CMD == constants.XEN_CMD_XM and
        not netutils.TcpPing(target, port, live_port_needed=True)):
      raise errors.HypervisorError("Remote host %s not listening on port"
                                   " %s, cannot migrate" % (target, port))

    args = [constants.XEN_CMD, "migrate"]
    if constants.XEN_CMD == constants.XEN_CMD_XM:
      args.extend(["-p", "%d" % port])
      if live:
        args.append("-l")
    elif constants.XEN_CMD == constants.XEN_CMD_XL:
      cluster_name = ssconf.SimpleStore().GetClusterName()
      args.extend(["-s", constants.XL_SSH_CMD % cluster_name])
      args.extend(["-C", self._ConfigFileName(instance.name)])
    else:
      raise errors.HypervisorError("Unsupported xen command: %s" %
                                   constants.XEN_CMD)

    args.extend([instance.name, target])
    result = utils.RunCmd(args)
    if result.failed:
      raise errors.HypervisorError("Failed to migrate instance %s: %s" %
                                   (instance.name, result.output))

  def FinalizeMigrationSource(self, instance, success, live):
    """Finalize the instance migration on the source node.

    @type instance: L{objects.Instance}
    @param instance: the instance that was migrated
    @type success: bool
    @param success: whether the migration succeeded or not
    @type live: bool
    @param live: whether the user requested a live migration or not

    """
    # pylint: disable=W0613
    if success:
      # remove old xen file after migration succeeded
      try:
        self._RemoveConfigFile(instance.name)
      except EnvironmentError:
        logging.exception("Failure while removing instance config file")

  def GetMigrationStatus(self, instance):
    """Get the migration status

    As MigrateInstance for Xen is still blocking, if this method is called it
    means that MigrateInstance has completed successfully. So we can safely
    assume that the migration was successful and notify this fact to the client.

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    return objects.MigrationStatus(status=constants.HV_MIGRATION_COMPLETED)

  @classmethod
  def PowercycleNode(cls):
    """Xen-specific powercycle.

    This first does a Linux reboot (which triggers automatically a Xen
    reboot), and if that fails it tries to do a Xen reboot. The reason
    we don't try a Xen reboot first is that the xen reboot launches an
    external command which connects to the Xen hypervisor, and that
    won't work in case the root filesystem is broken and/or the xend
    daemon is not working.

    """
    try:
      cls.LinuxPowercycle()
    finally:
      utils.RunCmd([constants.XEN_CMD, "debug", "R"])


class XenPvmHypervisor(XenHypervisor):
  """Xen PVM hypervisor interface"""

  PARAMETERS = {
    constants.HV_USE_BOOTLOADER: hv_base.NO_CHECK,
    constants.HV_BOOTLOADER_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_BOOTLOADER_ARGS: hv_base.NO_CHECK,
    constants.HV_KERNEL_PATH: hv_base.REQ_FILE_CHECK,
    constants.HV_INITRD_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_ROOT_PATH: hv_base.NO_CHECK,
    constants.HV_KERNEL_ARGS: hv_base.NO_CHECK,
    constants.HV_MIGRATION_PORT: hv_base.REQ_NET_PORT_CHECK,
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    # TODO: Add a check for the blockdev prefix (matching [a-z:] or similar).
    constants.HV_BLOCKDEV_PREFIX: hv_base.NO_CHECK,
    constants.HV_REBOOT_BEHAVIOR:
      hv_base.ParamInSet(True, constants.REBOOT_BEHAVIORS),
    constants.HV_CPU_MASK: hv_base.OPT_MULTI_CPU_MASK_CHECK,
    constants.HV_CPU_CAP: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    constants.HV_CPU_WEIGHT:
      (False, lambda x: 0 < x < 65536, "invalid weight", None, None),
    }

  @classmethod
  def _WriteConfigFile(cls, instance, startup_memory, block_devices):
    """Write the Xen config file for the instance.

    """
    hvp = instance.hvparams
    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")

    # if bootloader is True, use bootloader instead of kernel and ramdisk
    # parameters.
    if hvp[constants.HV_USE_BOOTLOADER]:
      # bootloader handling
      bootloader_path = hvp[constants.HV_BOOTLOADER_PATH]
      if bootloader_path:
        config.write("bootloader = '%s'\n" % bootloader_path)
      else:
        raise errors.HypervisorError("Bootloader enabled, but missing"
                                     " bootloader path")

      bootloader_args = hvp[constants.HV_BOOTLOADER_ARGS]
      if bootloader_args:
        config.write("bootargs = '%s'\n" % bootloader_args)
    else:
      # kernel handling
      kpath = hvp[constants.HV_KERNEL_PATH]
      config.write("kernel = '%s'\n" % kpath)

      # initrd handling
      initrd_path = hvp[constants.HV_INITRD_PATH]
      if initrd_path:
        config.write("ramdisk = '%s'\n" % initrd_path)

    # rest of the settings
    config.write("memory = %d\n" % startup_memory)
    config.write("maxmem = %d\n" % instance.beparams[constants.BE_MAXMEM])
    config.write("vcpus = %d\n" % instance.beparams[constants.BE_VCPUS])
    cpu_pinning = _CreateConfigCpus(hvp[constants.HV_CPU_MASK])
    if cpu_pinning:
      config.write("%s\n" % cpu_pinning)
    cpu_cap = hvp[constants.HV_CPU_CAP]
    if cpu_cap:
      config.write("cpu_cap=%d\n" % cpu_cap)
    cpu_weight = hvp[constants.HV_CPU_WEIGHT]
    if cpu_weight:
      config.write("cpu_weight=%d\n" % cpu_weight)

    config.write("name = '%s'\n" % instance.name)

    vif_data = []
    for nic in instance.nics:
      nic_str = "mac=%s" % (nic.mac)
      ip = getattr(nic, "ip", None)
      if ip is not None:
        nic_str += ", ip=%s" % ip
      if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
        nic_str += ", bridge=%s" % nic.nicparams[constants.NIC_LINK]
      vif_data.append("'%s'" % nic_str)

    disk_data = cls._GetConfigFileDiskData(block_devices,
                                           hvp[constants.HV_BLOCKDEV_PREFIX])

    config.write("vif = [%s]\n" % ",".join(vif_data))
    config.write("disk = [%s]\n" % ",".join(disk_data))

    if hvp[constants.HV_ROOT_PATH]:
      config.write("root = '%s'\n" % hvp[constants.HV_ROOT_PATH])
    config.write("on_poweroff = 'destroy'\n")
    if hvp[constants.HV_REBOOT_BEHAVIOR] == constants.INSTANCE_REBOOT_ALLOWED:
      config.write("on_reboot = 'restart'\n")
    else:
      config.write("on_reboot = 'destroy'\n")
    config.write("on_crash = 'restart'\n")
    config.write("extra = '%s'\n" % hvp[constants.HV_KERNEL_ARGS])
    cls._WriteConfigFileStatic(instance.name, config.getvalue())

    return True


class XenHvmHypervisor(XenHypervisor):
  """Xen HVM hypervisor interface"""

  ANCILLARY_FILES = XenHypervisor.ANCILLARY_FILES + [
    pathutils.VNC_PASSWORD_FILE,
    ]
  ANCILLARY_FILES_OPT = XenHypervisor.ANCILLARY_FILES_OPT + [
    pathutils.VNC_PASSWORD_FILE,
    ]

  PARAMETERS = {
    constants.HV_ACPI: hv_base.NO_CHECK,
    constants.HV_BOOT_ORDER: (True, ) +
      (lambda x: x and len(x.strip("acdn")) == 0,
       "Invalid boot order specified, must be one or more of [acdn]",
       None, None),
    constants.HV_CDROM_IMAGE_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_DISK_TYPE:
      hv_base.ParamInSet(True, constants.HT_HVM_VALID_DISK_TYPES),
    constants.HV_NIC_TYPE:
      hv_base.ParamInSet(True, constants.HT_HVM_VALID_NIC_TYPES),
    constants.HV_PAE: hv_base.NO_CHECK,
    constants.HV_VNC_BIND_ADDRESS:
      (False, netutils.IP4Address.IsValid,
       "VNC bind address is not a valid IP address", None, None),
    constants.HV_KERNEL_PATH: hv_base.REQ_FILE_CHECK,
    constants.HV_DEVICE_MODEL: hv_base.REQ_FILE_CHECK,
    constants.HV_VNC_PASSWORD_FILE: hv_base.REQ_FILE_CHECK,
    constants.HV_MIGRATION_PORT: hv_base.REQ_NET_PORT_CHECK,
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    constants.HV_USE_LOCALTIME: hv_base.NO_CHECK,
    # TODO: Add a check for the blockdev prefix (matching [a-z:] or similar).
    constants.HV_BLOCKDEV_PREFIX: hv_base.NO_CHECK,
    # Add PCI passthrough
    constants.HV_PASSTHROUGH: hv_base.NO_CHECK,
    constants.HV_REBOOT_BEHAVIOR:
      hv_base.ParamInSet(True, constants.REBOOT_BEHAVIORS),
    constants.HV_CPU_MASK: hv_base.OPT_MULTI_CPU_MASK_CHECK,
    constants.HV_CPU_CAP: hv_base.NO_CHECK,
    constants.HV_CPU_WEIGHT:
      (False, lambda x: 0 < x < 65535, "invalid weight", None, None),
    }

  @classmethod
  def _WriteConfigFile(cls, instance, startup_memory, block_devices):
    """Create a Xen 3.1 HVM config file.

    """
    hvp = instance.hvparams

    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")

    # kernel handling
    kpath = hvp[constants.HV_KERNEL_PATH]
    config.write("kernel = '%s'\n" % kpath)

    config.write("builder = 'hvm'\n")
    config.write("memory = %d\n" % startup_memory)
    config.write("maxmem = %d\n" % instance.beparams[constants.BE_MAXMEM])
    config.write("vcpus = %d\n" % instance.beparams[constants.BE_VCPUS])
    cpu_pinning = _CreateConfigCpus(hvp[constants.HV_CPU_MASK])
    if cpu_pinning:
      config.write("%s\n" % cpu_pinning)
    cpu_cap = hvp[constants.HV_CPU_CAP]
    if cpu_cap:
      config.write("cpu_cap=%d\n" % cpu_cap)
    cpu_weight = hvp[constants.HV_CPU_WEIGHT]
    if cpu_weight:
      config.write("cpu_weight=%d\n" % cpu_weight)

    config.write("name = '%s'\n" % instance.name)
    if hvp[constants.HV_PAE]:
      config.write("pae = 1\n")
    else:
      config.write("pae = 0\n")
    if hvp[constants.HV_ACPI]:
      config.write("acpi = 1\n")
    else:
      config.write("acpi = 0\n")
    config.write("apic = 1\n")
    config.write("device_model = '%s'\n" % hvp[constants.HV_DEVICE_MODEL])
    config.write("boot = '%s'\n" % hvp[constants.HV_BOOT_ORDER])
    config.write("sdl = 0\n")
    config.write("usb = 1\n")
    config.write("usbdevice = 'tablet'\n")
    config.write("vnc = 1\n")
    if hvp[constants.HV_VNC_BIND_ADDRESS] is None:
      config.write("vnclisten = '%s'\n" % constants.VNC_DEFAULT_BIND_ADDRESS)
    else:
      config.write("vnclisten = '%s'\n" % hvp[constants.HV_VNC_BIND_ADDRESS])

    if instance.network_port > constants.VNC_BASE_PORT:
      display = instance.network_port - constants.VNC_BASE_PORT
      config.write("vncdisplay = %s\n" % display)
      config.write("vncunused = 0\n")
    else:
      config.write("# vncdisplay = 1\n")
      config.write("vncunused = 1\n")

    vnc_pwd_file = hvp[constants.HV_VNC_PASSWORD_FILE]
    try:
      password = utils.ReadFile(vnc_pwd_file)
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to open VNC password file %s: %s" %
                                   (vnc_pwd_file, err))

    config.write("vncpasswd = '%s'\n" % password.rstrip())

    config.write("serial = 'pty'\n")
    if hvp[constants.HV_USE_LOCALTIME]:
      config.write("localtime = 1\n")

    vif_data = []
    nic_type = hvp[constants.HV_NIC_TYPE]
    if nic_type is None:
      # ensure old instances don't change
      nic_type_str = ", type=ioemu"
    elif nic_type == constants.HT_NIC_PARAVIRTUAL:
      nic_type_str = ", type=paravirtualized"
    else:
      nic_type_str = ", model=%s, type=ioemu" % nic_type
    for nic in instance.nics:
      nic_str = "mac=%s%s" % (nic.mac, nic_type_str)
      ip = getattr(nic, "ip", None)
      if ip is not None:
        nic_str += ", ip=%s" % ip
      if nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
        nic_str += ", bridge=%s" % nic.nicparams[constants.NIC_LINK]
      vif_data.append("'%s'" % nic_str)

    config.write("vif = [%s]\n" % ",".join(vif_data))

    disk_data = cls._GetConfigFileDiskData(block_devices,
                                           hvp[constants.HV_BLOCKDEV_PREFIX])

    iso_path = hvp[constants.HV_CDROM_IMAGE_PATH]
    if iso_path:
      iso = "'file:%s,hdc:cdrom,r'" % iso_path
      disk_data.append(iso)

    config.write("disk = [%s]\n" % (",".join(disk_data)))
    # Add PCI passthrough
    pci_pass_arr = []
    pci_pass = hvp[constants.HV_PASSTHROUGH]
    if pci_pass:
      pci_pass_arr = pci_pass.split(";")
      config.write("pci = %s\n" % pci_pass_arr)
    config.write("on_poweroff = 'destroy'\n")
    if hvp[constants.HV_REBOOT_BEHAVIOR] == constants.INSTANCE_REBOOT_ALLOWED:
      config.write("on_reboot = 'restart'\n")
    else:
      config.write("on_reboot = 'destroy'\n")
    config.write("on_crash = 'restart'\n")
    cls._WriteConfigFileStatic(instance.name, config.getvalue())

    return True
