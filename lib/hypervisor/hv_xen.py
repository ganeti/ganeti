#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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

import os
import os.path
import time
from cStringIO import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import logger
from ganeti import utils
from ganeti.hypervisor import hv_base


class XenHypervisor(hv_base.BaseHypervisor):
  """Xen generic hypervisor interface

  This is the Xen base class used for both Xen PVM and HVM. It contains
  all the functionality that is identical for both.

  """

  @staticmethod
  def _WriteConfigFile(instance, block_devices, extra_args):
    """Write the Xen config file for the instance.

    """
    raise NotImplementedError

  @staticmethod
  def _RemoveConfigFile(instance):
    """Remove the xen configuration file.

    """
    utils.RemoveFile("/etc/xen/%s" % instance.name)

  @staticmethod
  def _GetXMList(include_node):
    """Return the list of running instances.

    If the `include_node` argument is True, then we return information
    for dom0 also, otherwise we filter that from the return value.

    The return value is a list of (name, id, memory, vcpus, state, time spent)

    """
    for dummy in range(5):
      result = utils.RunCmd(["xm", "list"])
      if not result.failed:
        break
      logger.Error("xm list failed (%s): %s" % (result.fail_reason,
                                                result.output))
      time.sleep(1)

    if result.failed:
      raise errors.HypervisorError("xm list failed, retries"
                                   " exceeded (%s): %s" %
                                   (result.fail_reason, result.stderr))

    # skip over the heading
    lines = result.stdout.splitlines()[1:]
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
      except ValueError, err:
        raise errors.HypervisorError("Can't parse output of xm list,"
                                     " line: %s, error: %s" % (line, err))

      # skip the Domain-0 (optional)
      if include_node or data[0] != 'Domain-0':
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

    Args:
      instance_name: the instance name

    Returns:
      (name, id, memory, vcpus, stat, times)
    """
    xm_list = self._GetXMList(instance_name=="Domain-0")
    result = None
    for data in xm_list:
      if data[0] == instance_name:
        result = data
        break
    return result

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    Returns:
      [(name, id, memory, vcpus, stat, times),...]
    """
    xm_list = self._GetXMList(False)
    return xm_list

  def StartInstance(self, instance, block_devices, extra_args):
    """Start an instance."""
    self._WriteConfigFile(instance, block_devices, extra_args)
    result = utils.RunCmd(["xm", "create", instance.name])

    if result.failed:
      raise errors.HypervisorError("Failed to start instance %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))

  def StopInstance(self, instance, force=False):
    """Stop an instance."""
    self._RemoveConfigFile(instance)
    if force:
      command = ["xm", "destroy", instance.name]
    else:
      command = ["xm", "shutdown", instance.name]
    result = utils.RunCmd(command)

    if result.failed:
      raise errors.HypervisorError("Failed to stop instance %s: %s" %
                                   (instance.name, result.fail_reason))

  def RebootInstance(self, instance):
    """Reboot an instance."""
    result = utils.RunCmd(["xm", "reboot", instance.name])

    if result.failed:
      raise errors.HypervisorError("Failed to reboot instance %s: %s" %
                                   (instance.name, result.fail_reason))

  def GetNodeInfo(self):
    """Return information about the node.

    The return value is a dict, which has to have the following items:
      (all values in MiB)
      - memory_total: the total memory size on the node
      - memory_free: the available memory on the node for instances
      - memory_dom0: the memory used by the node itself, if available

    """
    # note: in xen 3, memory has changed to total_memory
    result = utils.RunCmd(["xm", "info"])
    if result.failed:
      logger.Error("Can't run 'xm info': %s" % result.fail_reason)
      return None

    xmoutput = result.stdout.splitlines()
    result = {}
    for line in xmoutput:
      splitfields = line.split(":", 1)

      if len(splitfields) > 1:
        key = splitfields[0].strip()
        val = splitfields[1].strip()
        if key == 'memory' or key == 'total_memory':
          result['memory_total'] = int(val)
        elif key == 'free_memory':
          result['memory_free'] = int(val)
        elif key == 'nr_cpus':
          result['cpu_total'] = int(val)
    dom0_info = self.GetInstanceInfo("Domain-0")
    if dom0_info is not None:
      result['memory_dom0'] = dom0_info[2]

    return result

  @staticmethod
  def GetShellCommandForConsole(instance):
    """Return a command for connecting to the console of an instance.

    """
    raise NotImplementedError

  def Verify(self):
    """Verify the hypervisor.

    For Xen, this verifies that the xend process is running.

    """
    result = utils.RunCmd(["xm", "info"])
    if result.failed:
      return "'xm info' failed: %s" % result.fail_reason

  @staticmethod
  def _GetConfigFileDiskData(disk_template, block_devices):
    """Get disk directive for xen config file.

    This method builds the xen config disk directive according to the
    given disk_template and block_devices.

    Args:
      disk_template: String containing instance disk template
      block_devices: List[tuple1,tuple2,...]
        tuple: (cfdev, rldev)
          cfdev: dict containing ganeti config disk part
          rldev: ganeti.bdev.BlockDev object

    Returns:
      String containing disk directive for xen instance config file

    """
    FILE_DRIVER_MAP = {
      constants.FD_LOOP: "file",
      constants.FD_BLKTAP: "tap:aio",
      }
    disk_data = []
    for cfdev, rldev in block_devices:
      if cfdev.dev_type == constants.LD_FILE:
        line = "'%s:%s,%s,w'" % (FILE_DRIVER_MAP[cfdev.physical_id[0]],
                                 rldev.dev_path, cfdev.iv_name)
      else:
        line = "'phy:%s,%s,w'" % (rldev.dev_path, cfdev.iv_name)
      disk_data.append(line)

    return disk_data


class XenPvmHypervisor(XenHypervisor):
  """Xen PVM hypervisor interface"""

  @classmethod
  def _WriteConfigFile(cls, instance, block_devices, extra_args):
    """Write the Xen config file for the instance.

    """
    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")

    # kernel handling
    if instance.kernel_path in (None, constants.VALUE_DEFAULT):
      kpath = constants.XEN_KERNEL
    else:
      if not os.path.exists(instance.kernel_path):
        raise errors.HypervisorError("The kernel %s for instance %s is"
                                     " missing" % (instance.kernel_path,
                                                   instance.name))
      kpath = instance.kernel_path
    config.write("kernel = '%s'\n" % kpath)

    # initrd handling
    if instance.initrd_path in (None, constants.VALUE_DEFAULT):
      if os.path.exists(constants.XEN_INITRD):
        initrd_path = constants.XEN_INITRD
      else:
        initrd_path = None
    elif instance.initrd_path == constants.VALUE_NONE:
      initrd_path = None
    else:
      if not os.path.exists(instance.initrd_path):
        raise errors.HypervisorError("The initrd %s for instance %s is"
                                     " missing" % (instance.initrd_path,
                                                   instance.name))
      initrd_path = instance.initrd_path

    if initrd_path:
      config.write("ramdisk = '%s'\n" % initrd_path)

    # rest of the settings
    config.write("memory = %d\n" % instance.memory)
    config.write("vcpus = %d\n" % instance.vcpus)
    config.write("name = '%s'\n" % instance.name)

    vif_data = []
    for nic in instance.nics:
      nic_str = "mac=%s, bridge=%s" % (nic.mac, nic.bridge)
      ip = getattr(nic, "ip", None)
      if ip is not None:
        nic_str += ", ip=%s" % ip
      vif_data.append("'%s'" % nic_str)

    config.write("vif = [%s]\n" % ",".join(vif_data))
    config.write("disk = [%s]\n" % ",".join(
                 cls._GetConfigFileDiskData(instance.disk_template,
                                            block_devices)))
    config.write("root = '/dev/sda ro'\n")
    config.write("on_poweroff = 'destroy'\n")
    config.write("on_reboot = 'restart'\n")
    config.write("on_crash = 'restart'\n")
    if extra_args:
      config.write("extra = '%s'\n" % extra_args)
    # just in case it exists
    utils.RemoveFile("/etc/xen/auto/%s" % instance.name)
    try:
      f = open("/etc/xen/%s" % instance.name, "w")
      try:
        f.write(config.getvalue())
      finally:
        f.close()
    except IOError, err:
      raise errors.OpExecError("Cannot write Xen instance confile"
                               " file /etc/xen/%s: %s" % (instance.name, err))
    return True

  @staticmethod
  def GetShellCommandForConsole(instance):
    """Return a command for connecting to the console of an instance.

    """
    return "xm console %s" % instance.name


class XenHvmHypervisor(XenHypervisor):
  """Xen HVM hypervisor interface"""

  @classmethod
  def _WriteConfigFile(cls, instance, block_devices, extra_args):
    """Create a Xen 3.1 HVM config file.

    """
    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")
    config.write("kernel = '/usr/lib/xen/boot/hvmloader'\n")
    config.write("builder = 'hvm'\n")
    config.write("memory = %d\n" % instance.memory)
    config.write("vcpus = %d\n" % instance.vcpus)
    config.write("name = '%s'\n" % instance.name)
    config.write("pae = 1\n")
    config.write("acpi = 1\n")
    config.write("apic = 1\n")
    arch = os.uname()[4]
    if '64' in arch:
      config.write("device_model = '/usr/lib64/xen/bin/qemu-dm'\n")
    else:
      config.write("device_model = '/usr/lib/xen/bin/qemu-dm'\n")
    if instance.hvm_boot_order is None:
      config.write("boot = '%s'\n" % constants.HT_HVM_DEFAULT_BOOT_ORDER)
    else:
      config.write("boot = '%s'\n" % instance.hvm_boot_order)
    config.write("sdl = 0\n")
    config.write("usb = 1\n");
    config.write("usbdevice = 'tablet'\n");
    config.write("vnc = 1\n")
    config.write("vnclisten = '0.0.0.0'\n")

    if instance.network_port > constants.HT_HVM_VNC_BASE_PORT:
      display = instance.network_port - constants.HT_HVM_VNC_BASE_PORT
      config.write("vncdisplay = %s\n" % display)
      config.write("vncunused = 0\n")
    else:
      config.write("# vncdisplay = 1\n")
      config.write("vncunused = 1\n")

    try:
      password_file = open(constants.VNC_PASSWORD_FILE, "r")
      try:
        password = password_file.readline()
      finally:
        password_file.close()
    except IOError:
      raise errors.OpExecError("failed to open VNC password file %s " %
                               constants.VNC_PASSWORD_FILE)

    config.write("vncpasswd = '%s'\n" % password.rstrip())

    config.write("serial = 'pty'\n")
    config.write("localtime = 1\n")

    vif_data = []
    for nic in instance.nics:
      nic_str = "mac=%s, bridge=%s, type=ioemu" % (nic.mac, nic.bridge)
      ip = getattr(nic, "ip", None)
      if ip is not None:
        nic_str += ", ip=%s" % ip
      vif_data.append("'%s'" % nic_str)

    config.write("vif = [%s]\n" % ",".join(vif_data))
    iso = "'file:/srv/ganeti/iso/hvm-install.iso,hdc:cdrom,r'"
    config.write("disk = [%s, %s]\n" % (",".join(
                 cls._GetConfigFileDiskData(instance.disk_template,
                                            block_devices)), iso))
    config.write("on_poweroff = 'destroy'\n")
    config.write("on_reboot = 'restart'\n")
    config.write("on_crash = 'restart'\n")
    if extra_args:
      config.write("extra = '%s'\n" % extra_args)
    # just in case it exists
    utils.RemoveFile("/etc/xen/auto/%s" % instance.name)
    try:
      f = open("/etc/xen/%s" % instance.name, "w")
      try:
        f.write(config.getvalue())
      finally:
        f.close()
    except IOError, err:
      raise errors.OpExecError("Cannot write Xen instance confile"
                               " file /etc/xen/%s: %s" % (instance.name, err))
    return True

  @staticmethod
  def GetShellCommandForConsole(instance):
    """Return a command for connecting to the console of an instance.

    """
    if instance.network_port is None:
      raise errors.OpExecError("no console port defined for %s"
                               % instance.name)
    else:
      raise errors.OpExecError("no PTY console, connect to %s:%s via VNC"
                               % (instance.primary_node,
                                  instance.network_port))
