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
import logging
from cStringIO import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti.hypervisor import hv_base


class XenHypervisor(hv_base.BaseHypervisor):
  """Xen generic hypervisor interface

  This is the Xen base class used for both Xen PVM and HVM. It contains
  all the functionality that is identical for both.

  """

  @classmethod
  def _WriteConfigFile(cls, instance, block_devices, extra_args):
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

    If the include_node argument is True, then we return information
    for dom0 also, otherwise we filter that from the return value.

    @return: list of (name, id, memory, vcpus, state, time spent)

    """
    for dummy in range(5):
      result = utils.RunCmd(["xm", "list"])
      if not result.failed:
        break
      logging.error("xm list failed (%s): %s", result.fail_reason,
                    result.output)
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

    @param instance_name: the instance name

    @return: tuple (name, id, memory, vcpus, stat, times)

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

    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    xm_list = self._GetXMList(False)
    return xm_list

  def StartInstance(self, instance, block_devices, extra_args):
    """Start an instance.

    """
    self._WriteConfigFile(instance, block_devices, extra_args)
    result = utils.RunCmd(["xm", "create", instance.name])

    if result.failed:
      raise errors.HypervisorError("Failed to start instance %s: %s (%s)" %
                                   (instance.name, result.fail_reason,
                                    result.output))

  def StopInstance(self, instance, force=False):
    """Stop an instance.

    """
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
    """Reboot an instance.

    """
    result = utils.RunCmd(["xm", "reboot", instance.name])

    if result.failed:
      raise errors.HypervisorError("Failed to reboot instance %s: %s" %
                                   (instance.name, result.fail_reason))

  def GetNodeInfo(self):
    """Return information about the node.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available

    """
    # note: in xen 3, memory has changed to total_memory
    result = utils.RunCmd(["xm", "info"])
    if result.failed:
      logging.error("Can't run 'xm info' (%s): %s", result.fail_reason,
                    result.output)
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
    return "xm console %s" % instance.name


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

    @param disk_template: string containing instance disk template
    @param block_devices: list of tuples (cfdev, rldev):
        - cfdev: dict containing ganeti config disk part
        - rldev: ganeti.bdev.BlockDev object

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
    # FIXME: instead of this hardcoding here, each of PVM/HVM should
    # directly export their info (currently HVM will just sed this info)
    namespace = ["sd" + chr(i + ord('a')) for i in range(24)]
    for sd_name, (cfdev, dev_path) in zip(namespace, block_devices):
      if cfdev.dev_type == constants.LD_FILE:
        line = "'%s:%s,%s,w'" % (FILE_DRIVER_MAP[cfdev.physical_id[0]],
                                 dev_path, sd_name)
      else:
        line = "'phy:%s,%s,w'" % (dev_path, sd_name)
      disk_data.append(line)

    return disk_data

  def MigrateInstance(self, instance, target, live):
    """Migrate an instance to a target node.

    Arguments:
      - instance: the name of the instance
      - target: the ip of the target node
      - live: whether to do live migration or not

    Returns: none, errors will be signaled by exception.

    The migration will not be attempted if the instance is not
    currently running.

    """
    if self.GetInstanceInfo(instance) is None:
      raise errors.HypervisorError("Instance not running, cannot migrate")
    args = ["xm", "migrate"]
    if live:
      args.append("-l")
    args.extend([instance, target])
    result = utils.RunCmd(args)
    if result.failed:
      raise errors.HypervisorError("Failed to migrate instance %s: %s" %
                                   (instance, result.output))


class XenPvmHypervisor(XenHypervisor):
  """Xen PVM hypervisor interface"""

  PARAMETERS = [
    constants.HV_KERNEL_PATH,
    constants.HV_INITRD_PATH,
    ]

  @classmethod
  def CheckParameterSyntax(cls, hvparams):
    """Check the given parameters for validity.

    For the PVM hypervisor, this only check the existence of the
    kernel.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    super(XenPvmHypervisor, cls).CheckParameterSyntax(hvparams)

    if not hvparams[constants.HV_KERNEL_PATH]:
      raise errors.HypervisorError("Need a kernel for the instance")

    if not os.path.isabs(hvparams[constants.HV_KERNEL_PATH]):
      raise errors.HypervisorError("The kernel path must an absolute path")

    if hvparams[constants.HV_INITRD_PATH]:
      if not os.path.isabs(hvparams[constants.HV_INITRD_PATH]):
        raise errors.HypervisorError("The initrd path must an absolute path"
                                     ", if defined")

  def ValidateParameters(self, hvparams):
    """Check the given parameters for validity.

    For the PVM hypervisor, this only check the existence of the
    kernel.

    """
    super(XenPvmHypervisor, self).ValidateParameters(hvparams)

    kernel_path = hvparams[constants.HV_KERNEL_PATH]
    if not os.path.isfile(kernel_path):
      raise errors.HypervisorError("Instance kernel '%s' not found or"
                                   " not a file" % kernel_path)
    initrd_path = hvparams[constants.HV_INITRD_PATH]
    if initrd_path and not os.path.isfile(initrd_path):
      raise errors.HypervisorError("Instance initrd '%s' not found or"
                                   " not a file" % initrd_path)

  @classmethod
  def _WriteConfigFile(cls, instance, block_devices, extra_args):
    """Write the Xen config file for the instance.

    """
    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")

    # kernel handling
    kpath = instance.hvparams[constants.HV_KERNEL_PATH]
    config.write("kernel = '%s'\n" % kpath)

    # initrd handling
    initrd_path = instance.hvparams[constants.HV_INITRD_PATH]
    if initrd_path:
      config.write("ramdisk = '%s'\n" % initrd_path)

    # rest of the settings
    config.write("memory = %d\n" % instance.beparams[constants.BE_MEMORY])
    config.write("vcpus = %d\n" % instance.beparams[constants.BE_VCPUS])
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


class XenHvmHypervisor(XenHypervisor):
  """Xen HVM hypervisor interface"""

  PARAMETERS = [
    constants.HV_ACPI,
    constants.HV_BOOT_ORDER,
    constants.HV_CDROM_IMAGE_PATH,
    constants.HV_DISK_TYPE,
    constants.HV_NIC_TYPE,
    constants.HV_PAE,
    constants.HV_VNC_BIND_ADDRESS,
    ]

  @classmethod
  def CheckParameterSyntax(cls, hvparams):
    """Check the given parameter syntax.

    """
    super(XenHvmHypervisor, cls).CheckParameterSyntax(hvparams)
    # boot order verification
    boot_order = hvparams[constants.HV_BOOT_ORDER]
    if len(boot_order.strip("acdn")) != 0:
      raise errors.HypervisorError("Invalid boot order '%s' specified,"
                                   " must be one or more of [acdn]" %
                                   boot_order)
    # device type checks
    nic_type = hvparams[constants.HV_NIC_TYPE]
    if nic_type not in constants.HT_HVM_VALID_NIC_TYPES:
      raise errors.HypervisorError("Invalid NIC type %s specified for Xen HVM"
                                   " hypervisor" % nic_type)
    disk_type = hvparams[constants.HV_DISK_TYPE]
    if disk_type not in constants.HT_HVM_VALID_DISK_TYPES:
      raise errors.HypervisorError("Invalid disk type %s specified for Xen HVM"
                                   " hypervisor" % disk_type)
    # vnc_bind_address verification
    vnc_bind_address = hvparams[constants.HV_VNC_BIND_ADDRESS]
    if vnc_bind_address is not None:
      if not utils.IsValidIP(vnc_bind_address):
        raise errors.OpPrereqError("given VNC bind address '%s' doesn't look"
                                   " like a valid IP address" %
                                   vnc_bind_address)

    iso_path = hvparams[constants.HV_CDROM_IMAGE_PATH]
    if iso_path and not os.path.isabs(iso_path):
      raise errors.HypervisorError("The path to the HVM CDROM image must"
                                   " be an absolute path or None, not %s" %
                                   iso_path)

  def ValidateParameters(self, hvparams):
    """Check the given parameters for validity.

    For the PVM hypervisor, this only check the existence of the
    kernel.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    super(XenHvmHypervisor, self).ValidateParameters(hvparams)

    # hvm_cdrom_image_path verification
    iso_path = hvparams[constants.HV_CDROM_IMAGE_PATH]
    if iso_path and not os.path.isfile(iso_path):
      raise errors.HypervisorError("The HVM CDROM image must either be a"
                                   " regular file or a symlink pointing to"
                                   " an existing regular file, not %s" %
                                   iso_path)

  @classmethod
  def _WriteConfigFile(cls, instance, block_devices, extra_args):
    """Create a Xen 3.1 HVM config file.

    """
    config = StringIO()
    config.write("# this is autogenerated by Ganeti, please do not edit\n#\n")
    config.write("kernel = '/usr/lib/xen/boot/hvmloader'\n")
    config.write("builder = 'hvm'\n")
    config.write("memory = %d\n" % instance.beparams[constants.BE_MEMORY])
    config.write("vcpus = %d\n" % instance.beparams[constants.BE_VCPUS])
    config.write("name = '%s'\n" % instance.name)
    if instance.hvparams[constants.HV_PAE]:
      config.write("pae = 1\n")
    else:
      config.write("pae = 0\n")
    if instance.hvparams[constants.HV_ACPI]:
      config.write("acpi = 1\n")
    else:
      config.write("acpi = 0\n")
    config.write("apic = 1\n")
    arch = os.uname()[4]
    if '64' in arch:
      config.write("device_model = '/usr/lib64/xen/bin/qemu-dm'\n")
    else:
      config.write("device_model = '/usr/lib/xen/bin/qemu-dm'\n")
    if instance.hvparams[constants.HV_BOOT_ORDER] is None:
      config.write("boot = '%s'\n" % constants.HT_HVM_DEFAULT_BOOT_ORDER)
    else:
      config.write("boot = '%s'\n" % instance.hvparams["boot_order"])
    config.write("sdl = 0\n")
    config.write("usb = 1\n")
    config.write("usbdevice = 'tablet'\n")
    config.write("vnc = 1\n")
    if instance.hvparams[constants.HV_VNC_BIND_ADDRESS] is None:
      config.write("vnclisten = '%s'\n" % constants.VNC_DEFAULT_BIND_ADDRESS)
    else:
      config.write("vnclisten = '%s'\n" %
                   instance.hvparams["vnc_bind_address"])

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
    nic_type = instance.hvparams[constants.HV_NIC_TYPE]
    if nic_type is None:
      # ensure old instances don't change
      nic_type_str = ", type=ioemu"
    elif nic_type == constants.HT_HVM_DEV_PARAVIRTUAL:
      nic_type_str = ", type=paravirtualized"
    else:
      nic_type_str = ", model=%s, type=ioemu" % nic_type
    for nic in instance.nics:
      nic_str = "mac=%s, bridge=%s%s" % (nic.mac, nic.bridge, nic_type_str)
      ip = getattr(nic, "ip", None)
      if ip is not None:
        nic_str += ", ip=%s" % ip
      vif_data.append("'%s'" % nic_str)

    config.write("vif = [%s]\n" % ",".join(vif_data))
    disk_data = cls._GetConfigFileDiskData(instance.disk_template,
                                            block_devices)
    disk_type = instance.hvparams[constants.HV_DISK_TYPE]
    if disk_type in (None, constants.HT_HVM_DEV_IOEMU):
      replacement = ",ioemu:hd"
    else:
      replacement = ",hd"
    disk_data = [line.replace(",sd", replacement) for line in disk_data]
    iso_path = instance.hvparams[constants.HV_CDROM_IMAGE_PATH]
    if iso_path:
      iso = "'file:%s,hdc:cdrom,r'" % iso_path
      disk_data.append(iso)

    config.write("disk = [%s]\n" % (",".join(disk_data)))

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
