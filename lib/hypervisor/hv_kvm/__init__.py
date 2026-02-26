#
#

# Copyright (C) 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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


"""KVM hypervisor

"""

import errno
import os
import os.path
import re
import tempfile
import time
import logging
import pwd
import shlex
import shutil
import urllib.request, urllib.error, urllib.parse
from bitarray import bitarray

from ganeti.hypervisor.hv_kvm.bus_manager import BusAllocatorManager, \
  BusAllocation, PCIAllocator, SCSIAllocator

try:
  import psutil   # pylint: disable=F0401
  if psutil.version_info < (2, 0, 0):
    # The psutil version seems too old, we ignore it
    psutil_err = \
        "too old (2.x.x or newer needed, %s found)" % psutil.__version__
    psutil = None
  else:
    psutil_err = "<no error>"
except ImportError:
  psutil_err = "not found"
  psutil = None

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import uidpool
from ganeti import ssconf
from ganeti import netutils
from ganeti import pathutils
from ganeti.hypervisor import hv_base
from ganeti.utils import wrapper as utils_wrapper

from ganeti.hypervisor.hv_kvm.monitor import QmpConnection, QmpMessage
from ganeti.hypervisor.hv_kvm.netdev import OpenTap

from ganeti.hypervisor.hv_kvm.kvm_runtime import KVMRuntime

from ganeti.hypervisor.hv_kvm.validation import check_boot_parameters, \
                                                check_console_parameters, \
                                                check_disk_cache_parameters, \
                                                check_security_model,\
                                                check_spice_parameters, \
                                                check_vnc_parameters, \
                                                validate_machine_version, \
                                                validate_security_model, \
                                                validate_spice_parameters, \
                                                validate_vnc_parameters, \
                                                validate_disk_parameters

from ganeti.hypervisor.hv_kvm import kvm_utils

_KVM_NETWORK_SCRIPT = pathutils.CONF_DIR + "/kvm-vif-bridge"
_KVM_START_PAUSED_FLAG = "-S"

# below constants show the format of runtime file
# the nics are in second possition, while the disks in 4th (last)
# moreover disk entries are stored as a list of in tuples
# (L{objects.Disk}, link_name, uri)
_KVM_NICS_RUNTIME_INDEX = 1
_KVM_DISKS_RUNTIME_INDEX = 3
_DEVICE_RUNTIME_INDEX = {
  constants.HOTPLUG_TARGET_DISK: _KVM_DISKS_RUNTIME_INDEX,
  constants.HOTPLUG_TARGET_NIC: _KVM_NICS_RUNTIME_INDEX
  }
_FIND_RUNTIME_ENTRY = {
  constants.HOTPLUG_TARGET_NIC:
    lambda nic, kvm_nics: [n for n in kvm_nics if n.uuid == nic.uuid],
  constants.HOTPLUG_TARGET_DISK:
    lambda disk, kvm_disks: [(d, l, u) for (d, l, u) in kvm_disks
                             if d.uuid == disk.uuid]
  }
_RUNTIME_DEVICE = {
  constants.HOTPLUG_TARGET_NIC: lambda d: d,
  constants.HOTPLUG_TARGET_DISK: lambda d_e_x: d_e_x[0]
  }
_RUNTIME_ENTRY = {
  constants.HOTPLUG_TARGET_NIC: lambda d, e: d,
  constants.HOTPLUG_TARGET_DISK: lambda d, e: (d, e[0], e[1])
  }

_DEVICE_TYPE = {
  constants.HOTPLUG_TARGET_NIC: lambda hvp: hvp[constants.HV_NIC_TYPE],
  constants.HOTPLUG_TARGET_DISK: lambda hvp: hvp[constants.HV_DISK_TYPE],
  }

_DEVICE_DRIVER = {
  constants.HOTPLUG_TARGET_NIC:
    lambda ht: "virtio-net-pci" if ht == constants.HT_NIC_PARAVIRTUAL else ht,
  constants.HOTPLUG_TARGET_DISK:
    lambda ht: "virtio-blk-pci" if ht == constants.HT_DISK_PARAVIRTUAL else ht,
  }


# NICs and paravirtual disks
# show up as devices on the PCI bus (one slot per device).
# SCSI disks will be placed on the SCSI bus.
_DEVICE_BUS = {
  constants.HOTPLUG_TARGET_NIC:
    lambda _: _PCI_BUS,
  constants.HOTPLUG_TARGET_DISK:
    lambda ht: _SCSI_BUS if ht in constants.HT_SCSI_DEVICE_TYPES else _PCI_BUS
  }

_HOTPLUGGABLE_DEVICE_TYPES = {
  # All available NIC types except for ne2k_isa
  constants.HOTPLUG_TARGET_NIC: [
    constants.HT_NIC_E1000,
    constants.HT_NIC_I82551,
    constants.HT_NIC_I8259ER,
    constants.HT_NIC_I85557B,
    constants.HT_NIC_NE2K_PCI,
    constants.HT_NIC_PARAVIRTUAL,
    constants.HT_NIC_PCNET,
    constants.HT_NIC_RTL8139,
    ],
  constants.HOTPLUG_TARGET_DISK: [
    constants.HT_DISK_PARAVIRTUAL,
    constants.HT_DISK_SCSI_BLOCK,
    constants.HT_DISK_SCSI_GENERIC,
    constants.HT_DISK_SCSI_HD,
    constants.HT_DISK_SCSI_CD,
    ]
  }

_PCI_BUS = "pci.0"
_SCSI_BUS = "scsi.0"

_MAX_IDE_DEVICES = 4


def _GetIDEBusUnit(slot):
  """Return the IDE bus and unit for a given slot index.

  IDE controllers have two buses with two units each:
    slot 0 -> ide.0, unit 0 (primary-master)
    slot 1 -> ide.0, unit 1 (primary-slave)
    slot 2 -> ide.1, unit 0 (secondary-master)
    slot 3 -> ide.1, unit 1 (secondary-slave)

  @type slot: int
  @param slot: IDE slot index (0-3)
  @rtype: tuple of (str, int)
  @return: (bus, unit)
  @raise errors.HypervisorError: if slot >= 4

  """
  if slot >= _MAX_IDE_DEVICES:
    raise errors.HypervisorError(
      "Too many IDE devices: slot %d exceeds maximum of %d"
      % (slot, _MAX_IDE_DEVICES))
  bus = "ide.%d" % (slot // 2)
  unit = slot % 2
  return (bus, unit)

_MIGRATION_CAPS_DELIM = ":"

# in future make dirty_sync_count configurable
_POSTCOPY_SYNC_COUNT_THRESHOLD = 2 # Precopy passes before enabling postcopy

def _with_qmp(fn):
  """Wrapper used on hotplug related methods"""
  def wrapper(self, *args, **kwargs):
    """Create a QmpConnection and run the wrapped method"""
    if not getattr(self, "qmp", None):
      for arg in args:
        if isinstance(arg, objects.Instance):
          instance = arg
          break
      else:
        raise(RuntimeError("QMP decorator could not find"
                           " a valid ganeti instance object"))
      filename = self._InstanceQmpMonitor(instance.name)# pylint: disable=W0212
      self.qmp = QmpConnection(filename)
    return fn(self, *args, **kwargs)
  return wrapper


def _GetDriveURI(disk, link, uri):
  """Helper function to get the drive uri to be used in -blockdev kvm option

  Invoked during startup and disk hot-add. In latter case and if no userspace
  access mode is used it will be overriden with /dev/fdset/<fdset-id> (see
  HotAddDisk() and AddFd() of QmpConnection).

  @type disk: L{objects.Disk}
  @param disk: A disk configuration object
  @type link: string
  @param link: The device link as returned by _SymlinkBlockDev()
  @type uri: string
  @param uri: The drive uri as returned by _CalculateDeviceURI()

  @return: The drive uri to use in kvm option

  """
  access_mode = disk.params.get(constants.LDP_ACCESS,
                                constants.DISK_KERNELSPACE)
  # If uri is available, use it during startup/hot-add
  if uri and access_mode == constants.DISK_USERSPACE:
    drive_uri = uri
  # Otherwise use the link previously created
  else:
    drive_uri = link

  return drive_uri


def _GenerateDeviceKVMId(dev_type, dev):
  """Helper function to generate a unique device name used by KVM

  QEMU monitor commands use names to identify devices. Since the UUID
  is too long for a device ID (36 chars vs. 30), we choose to use
  only the part until the third '-' with a disk/nic prefix.
  For example if a disk has UUID '932df160-7a22-4067-a566-7e0ca8386133'
  the resulting device ID would be 'disk-932df160-7a22-4067'.

  @type dev_type: string
  @param dev_type: device type of param dev (HOTPLUG_TARGET_DISK|NIC)
  @type dev: L{objects.Disk} or L{objects.NIC}
  @param dev: the device object for which we generate a kvm name

  """
  return "%s-%s" % (dev_type.lower(), dev.uuid.rsplit("-", 2)[0])


def _GenerateDeviceHVInfoStr(hvinfo):
  """Construct the -device option string for hvinfo dict

  PV disk: virtio-blk-pci,id=disk-1234,bus=pci.0,addr=0x9
  PV NIC:  virtio-net-pci,id=nic-1234,bus=pci.0,addr=0x9
  SG disk: scsi-generic,id=disk-1234,bus=scsi.0,channel=0,scsi-id=1,lun=0

  @type hvinfo: dict
  @param hvinfo: dictionary created by _GenerateDeviceHVInfo()

  @rtype: string
  @return: The constructed string to be passed along with a -device option

  """

  # work on a copy
  d = dict(hvinfo)
  hvinfo_str = d.pop("driver")
  for k, v in d.items():
    hvinfo_str += ",%s=%s" % (k, v)

  return hvinfo_str


def _GenerateDeviceHVInfo(dev_type, kvm_devid, hv_dev_type,
                          allocation: BusAllocation):
  """Helper function to generate hvinfo of a device (disk, NIC)

  hvinfo will hold all necessary info for generating the -device QEMU option.
  We have two main buses: a PCI bus and a SCSI bus (created by a SCSI
  controller on the PCI bus).

  In case of PCI devices we add them on a free PCI slot (addr) on the first PCI
  bus (pci.0), and in case of SCSI devices we decide to put each disk on a
  different SCSI target (scsi-id) on the first SCSI bus (scsi.0).

  @type dev_type: string
  @param dev_type: either HOTPLUG_TARGET_DISK or HOTPLUG_TARGET_NIC
  @type kvm_devid: string
  @param kvm_devid: the id of the device
  @type hv_dev_type: string
  @param hv_dev_type: either disk_type or nic_type hvparam
  @param allocation: device allocation by the BusAllocationManager

  @rtype: dict
  @return: dict including all necessary info (driver, id, bus and bus location)
           for generating a -device QEMU option for either a disk or a NIC

  """
  driver = _DEVICE_DRIVER[dev_type](hv_dev_type)

  hvinfo = {
    "driver": driver,
    "id": kvm_devid,
    }

  # add allocation
  hvinfo.update(allocation.to_kvm_info())

  return hvinfo


def _GetExistingDeviceInfo(dev_type, device, runtime):
  """Helper function to get an existing device inside the runtime file

  Used when an instance is running. Load kvm runtime file and search
  for a device based on its type and uuid.

  @type dev_type: sting
  @param dev_type: device type of param dev
  @type device: L{objects.Disk} or L{objects.NIC}
  @param device: the device object for which we generate a kvm name
  @type runtime: tuple (cmd, nics, hvparams, disks)
  @param runtime: the runtime data to search for the device
  @raise errors.HotplugError: in case the requested device does not
    exist (e.g. device has been added without --hotplug option)

  """
  index = _DEVICE_RUNTIME_INDEX[dev_type]
  found = _FIND_RUNTIME_ENTRY[dev_type](device, runtime[index])
  if not found:
    raise errors.HotplugError("Cannot find runtime info for %s with UUID %s" %
                              (dev_type, device.uuid))

  return found[0]


class HeadRequest(urllib.request.Request):
  def get_method(self):
    return "HEAD"


def _CheckUrl(url):
  """Check if a given URL exists on the server

  """
  try:
    urllib.request.urlopen(HeadRequest(url))
    return True
  except urllib.error.URLError:
    return False


class KVMHypervisor(hv_base.BaseHypervisor):
  """KVM hypervisor interface

  """
  CAN_MIGRATE = True

  _ROOT_DIR = pathutils.RUN_DIR + "/kvm-hypervisor"
  _PIDS_DIR = _ROOT_DIR + "/pid" # contains live instances pids
  _UIDS_DIR = _ROOT_DIR + "/uid" # contains instances reserved uids
  _CTRL_DIR = _ROOT_DIR + "/ctrl" # contains instances control sockets
  _CONF_DIR = _ROOT_DIR + "/conf" # contains instances startup data
  _NICS_DIR = _ROOT_DIR + "/nic" # contains instances nic <-> tap associations
  # KVM instances with chroot enabled are started in empty chroot directories.
  _CHROOT_DIR = _ROOT_DIR + "/chroot" # for empty chroot directories
  # After an instance is stopped, its chroot directory is removed.
  # If the chroot directory is not empty, it can't be removed.
  # A non-empty chroot directory indicates a possible security incident.
  # To support forensics, the non-empty chroot directory is quarantined in
  # a separate directory, called 'chroot-quarantine'.
  _CHROOT_QUARANTINE_DIR = _ROOT_DIR + "/chroot-quarantine"
  _DIRS = [_ROOT_DIR, _PIDS_DIR, _UIDS_DIR, _CTRL_DIR, _CONF_DIR, _NICS_DIR,
           _CHROOT_DIR, _CHROOT_QUARANTINE_DIR]

  PARAMETERS = {
    constants.HV_KVM_PATH: hv_base.REQ_FILE_CHECK,
    constants.HV_KERNEL_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_INITRD_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_ROOT_PATH: hv_base.NO_CHECK,
    constants.HV_KERNEL_ARGS: hv_base.NO_CHECK,
    constants.HV_ACPI: hv_base.NO_CHECK,
    constants.HV_SERIAL_CONSOLE: hv_base.NO_CHECK,
    constants.HV_SERIAL_SPEED: hv_base.NO_CHECK,
    constants.HV_VNC_BIND_ADDRESS: hv_base.NO_CHECK, # will be checked later
    constants.HV_VNC_TLS: hv_base.NO_CHECK,
    constants.HV_VNC_X509: hv_base.OPT_DIR_CHECK,
    constants.HV_VNC_X509_VERIFY: hv_base.NO_CHECK,
    constants.HV_VNC_PASSWORD_FILE: hv_base.OPT_FILE_CHECK,
    constants.HV_KVM_SPICE_BIND: hv_base.NO_CHECK, # will be checked later
    constants.HV_KVM_SPICE_IP_VERSION:
      (False, lambda x: (x == constants.IFACE_NO_IP_VERSION_SPECIFIED or
                         x in constants.VALID_IP_VERSIONS),
       "The SPICE IP version should be 4 or 6",
       None, None),
    constants.HV_KVM_SPICE_PASSWORD_FILE: hv_base.OPT_FILE_CHECK,
    constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_LOSSLESS_IMG_COMPR_OPTIONS),
    constants.HV_KVM_SPICE_JPEG_IMG_COMPR:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_LOSSY_IMG_COMPR_OPTIONS),
    constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_LOSSY_IMG_COMPR_OPTIONS),
    constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION:
      hv_base.ParamInSet(
        False, constants.HT_KVM_SPICE_VALID_VIDEO_STREAM_DETECTION_OPTIONS),
    constants.HV_KVM_SPICE_AUDIO_COMPR: hv_base.NO_CHECK,
    constants.HV_KVM_SPICE_USE_TLS: hv_base.NO_CHECK,
    constants.HV_KVM_SPICE_TLS_CIPHERS: hv_base.NO_CHECK,
    constants.HV_KVM_SPICE_USE_VDAGENT: hv_base.NO_CHECK,
    constants.HV_KVM_FLOPPY_IMAGE_PATH: hv_base.OPT_FILE_CHECK,
    constants.HV_CDROM_IMAGE_PATH: hv_base.OPT_FILE_OR_URL_CHECK,
    constants.HV_KVM_CDROM2_IMAGE_PATH: hv_base.OPT_FILE_OR_URL_CHECK,
    constants.HV_BOOT_ORDER:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_BO_TYPES),
    constants.HV_NIC_TYPE:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_NIC_TYPES),
    constants.HV_DISK_TYPE:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_DISK_TYPES),
    constants.HV_KVM_SCSI_CONTROLLER_TYPE:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_SCSI_CONTROLLER_TYPES),
    constants.HV_DISK_DISCARD:
      hv_base.ParamInSet(False, constants.HT_VALID_DISCARD_TYPES),
    constants.HV_KVM_CDROM_DISK_TYPE:
      hv_base.ParamInSet(False, constants.HT_KVM_VALID_DISK_TYPES),
    constants.HV_USB_MOUSE:
      hv_base.ParamInSet(False, constants.HT_KVM_VALID_MOUSE_TYPES),
    constants.HV_KEYMAP: hv_base.NO_CHECK,
    constants.HV_MIGRATION_PORT: hv_base.REQ_NET_PORT_CHECK,
    constants.HV_MIGRATION_BANDWIDTH: hv_base.REQ_NONNEGATIVE_INT_CHECK,
    constants.HV_MIGRATION_DOWNTIME: hv_base.REQ_NONNEGATIVE_INT_CHECK,
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    constants.HV_USE_GUEST_AGENT: hv_base.NO_CHECK,
    constants.HV_USE_LOCALTIME: hv_base.NO_CHECK,
    constants.HV_DISK_CACHE:
      hv_base.ParamInSet(True, constants.HT_VALID_CACHE_TYPES),
    constants.HV_KVM_DISK_AIO:
      hv_base.ParamInSet(False, constants.HT_KVM_VALID_AIO_TYPES),
    constants.HV_SECURITY_MODEL:
      hv_base.ParamInSet(True, constants.HT_KVM_VALID_SM_TYPES),
    constants.HV_SECURITY_DOMAIN: hv_base.NO_CHECK,
    constants.HV_KVM_FLAG:
      hv_base.ParamInSet(False, constants.HT_KVM_FLAG_VALUES),
    constants.HV_VHOST_NET: hv_base.NO_CHECK,
    constants.HV_VIRTIO_NET_QUEUES: hv_base.OPT_VIRTIO_NET_QUEUES_CHECK,
    constants.HV_KVM_USE_CHROOT: hv_base.NO_CHECK,
    constants.HV_KVM_USER_SHUTDOWN: hv_base.NO_CHECK,
    constants.HV_MEM_PATH: hv_base.OPT_DIR_CHECK,
    constants.HV_REBOOT_BEHAVIOR:
      hv_base.ParamInSet(True, constants.REBOOT_BEHAVIORS),
    constants.HV_CPU_MASK: hv_base.OPT_MULTI_CPU_MASK_CHECK,
    constants.HV_CPU_TYPE: hv_base.NO_CHECK,
    constants.HV_CPU_CORES: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    constants.HV_CPU_THREADS: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    constants.HV_CPU_SOCKETS: hv_base.OPT_NONNEGATIVE_INT_CHECK,
    constants.HV_SOUNDHW: hv_base.NO_CHECK,
    constants.HV_USB_DEVICES: hv_base.NO_CHECK,
    constants.HV_VGA: hv_base.NO_CHECK,
    constants.HV_KVM_EXTRA: hv_base.NO_CHECK,
    constants.HV_KVM_MACHINE_VERSION: hv_base.NO_CHECK,
    constants.HV_KVM_MIGRATION_CAPS: hv_base.NO_CHECK,
    constants.HV_KVM_PCI_RESERVATIONS:
      (False, lambda x: (x >= 0 and x <= constants.QEMU_PCI_SLOTS),
       "The number of PCI slots managed by QEMU (max: %s)" %
       constants.QEMU_PCI_SLOTS,
       None, None),
    constants.HV_VNET_HDR: hv_base.NO_CHECK,
    }

  _VIRTIO = "virtio"
  _VIRTIO_NET_PCI = "virtio-net-pci"
  _VIRTIO_BLK_PCI = "virtio-blk-pci"

  _MIGRATION_INFO_MAX_BAD_ANSWERS = 5
  _MIGRATION_INFO_RETRY_DELAY = 2

  _VERSION_RE = re.compile(r"\b(\d+)\.(\d+)(\.(\d+))?\b")

  _DEFAULT_MACHINE_VERSION_RE = re.compile(r"^(\S+).*\(default\)", re.M)

  _QMP_RE = re.compile(r"^-qmp\s", re.M)

  _VHOST_RE = re.compile(r"^-netdev\stap.*,vhost=on\|off", re.M | re.S)
  _VIRTIO_NET_QUEUES_RE = re.compile(r"^-netdev\stap.*,fds=x:y:...:z", re.M)
  _ENABLE_KVM_RE = re.compile(r"^-enable-kvm\s", re.M)
  _DISABLE_KVM_RE = re.compile(r"^-disable-kvm\s", re.M)
  _NETDEV_RE = re.compile(r"^-netdev\s", re.M)
  _DISPLAY_RE = re.compile(r"^-display\s", re.M)
  _MACHINE_RE = re.compile(r"^-machine\s", re.M)
  _DEVICE_DRIVER_SUPPORTED = \
    staticmethod(lambda drv, devlist:
                 re.compile(r"^name \"%s\"" % drv, re.M).search(devlist))
  # match  -drive.*boot=on|off on different lines, but in between accept only
  # dashes not preceeded by a new line (which would mean another option
  # different than -drive is starting)
  _BOOT_RE = re.compile(r"^-(drive|blockdev)\s([^-]|(?<!^)-)*,boot=on\|off",
                        re.M | re.S)
  _UUID_RE = re.compile(r"^-uuid\s", re.M)
  # The auto-read-only option is on the -blockdev, Ganeti uses this at -drive
  _AUTO_RO_RE = \
    re.compile(r"^-blockdev\s([^-]|(?<!^)-)*,auto-read-only=on\|off",
               re.M | re.S)
  _RUNWITH_RE = re.compile(r"^-run-with\s.*chroot=.*user=", re.M)
  _ACPI_RE = re.compile(r"^-no-acpi\s", re.M)
  _SOUND_RE = re.compile(r"^-soundhw\s", re.M)

  # Slot 0 for Host bridge, Slot 1 for ISA bridge, Slot 2 for VGA controller
  # and the rest up to slot 11 will be used by QEMU implicitly.
  # Ganeti will add disks and NICs from slot 12 onwards.
  # NOTE: This maps to the default PCI bus created by pc machine type
  # by default (pci.0). The q35 creates a PCIe bus that is not hotpluggable
  # and should be handled differently (pcie.0).
  # NOTE: This bitarray here is defined for more fine-grained control.
  # Currently the number of slots is QEMU_PCI_SLOTS and the reserved
  # ones are the first QEMU_DEFAULT_PCI_RESERVATIONS.
  # If the above constants change without updating _DEFAULT_PCI_RESERVATIONS
  # properly, TestGenerateDeviceHVInfo() will probably break.
  _DEFAULT_PCI_RESERVATIONS = "11111111111100000000000000000000"
  _DEFAULT_PCI_RESERVED_SLOTS = 12
  _DEFAULT_PCI_SLOTS = 32
  # The SCSI bus is created on demand or automatically and is empty.
  # For simplicity we decide to use a different target (scsi-id)
  # for each SCSI disk. Here we support 16 SCSI disks which is
  # actually the current hard limit (constants.MAX_DISKS).
  # NOTE: Max device counts depend on the SCSI controller type;
  # Just for the record, lsi supports up to 7, megasas 64,
  # and virtio-scsi-pci 255.
  _DEFAULT_SCSI_RESERVATIONS = "0000000000000000"
  _DEFAULT_SCSI_SLOTS = 16

  ANCILLARY_FILES = [
    _KVM_NETWORK_SCRIPT,
    ]
  ANCILLARY_FILES_OPT = [
    _KVM_NETWORK_SCRIPT,
    ]

  # Supported kvm options to get output from
  _KVMOPT_HELP = "help"
  _KVMOPT_MLIST = "mlist"
  _KVMOPT_DEVICELIST = "devicelist"

  # Command to execute to get the output from kvm, and whether to
  # accept the output even on failure.
  _KVMOPTS_CMDS = {
    _KVMOPT_HELP: (["--help"], False),
    _KVMOPT_MLIST: (["-machine", "?"], False),
    _KVMOPT_DEVICELIST: (["-device", "?"], True),
  }

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    # Let's make sure the directories we need exist, even if the RUN_DIR lives
    # in a tmpfs filesystem or has been otherwise wiped out.
    dirs = [(dname, constants.RUN_DIRS_MODE) for dname in self._DIRS]
    utils.EnsureDirs(dirs)
    self.qmp = None

  @staticmethod
  def VersionsSafeForMigration(src, target):
    """Predict if migration is safe between those versions

    """
    # Actually, it is not that easy. However, with the kvm machine_version
    # feature, migration suceeds in most cases. So we try not to block
    # legitimate migrations.
    return True

  @classmethod
  def _InstancePidFile(cls, instance_name):
    """Returns the instance pidfile.

    """
    return utils.PathJoin(cls._PIDS_DIR, instance_name)

  @classmethod
  def _InstanceUidFile(cls, instance_name):
    """Returns the instance uidfile.

    """
    return utils.PathJoin(cls._UIDS_DIR, instance_name)

  @classmethod
  def _InstancePidInfo(cls, pid):
    """Check pid file for instance information.

    Check that a pid file is associated with an instance, and retrieve
    information from its command line.

    @type pid: string or int
    @param pid: process id of the instance to check
    @rtype: tuple
    @return: (instance_name, memory, vcpus)
    @raise errors.HypervisorError: when an instance cannot be found

    """
    alive = utils.IsProcessAlive(pid)
    if not alive:
      raise errors.HypervisorError("Cannot get info for pid %s" % pid)

    cmdline_file = utils.PathJoin("/proc", str(pid), "cmdline")
    try:
      cmdline = utils.ReadFile(cmdline_file)
    except EnvironmentError as err:
      raise errors.HypervisorError("Can't open cmdline file for pid %s: %s" %
                                   (pid, err))

    instance = None
    memory = 0
    vcpus = 0

    arg_list = cmdline.split("\x00")
    while arg_list:
      arg = arg_list.pop(0)
      if arg == "-name":
        # Qemu supports additional parameters which are appended
        # comma-separated to the -name parameter. While Ganeti
        # does not use this _now_, we need to be aware of future
        # Ganeti versions which might (see #1820 for the whole story)
        instance = arg_list.pop(0).split(",")[0]
      elif arg == "-m":
        memory = int(arg_list.pop(0))
      elif arg == "-smp":
        vcpus = int(arg_list.pop(0).split(",")[0])

    if instance is None:
      raise errors.HypervisorError("Pid %s doesn't contain a ganeti kvm"
                                   " instance" % pid)

    return (instance, memory, vcpus)

  @classmethod
  def _InstancePidAlive(cls, instance_name):
    """Returns the instance pidfile, pid, and liveness.

    @type instance_name: string
    @param instance_name: instance name
    @rtype: tuple
    @return: (pid file name, pid, liveness)

    """
    pidfile = cls._InstancePidFile(instance_name)
    pid = utils.ReadPidFile(pidfile)

    alive = False
    try:
      cmd_instance = cls._InstancePidInfo(pid)[0]
      alive = (cmd_instance == instance_name)
    except errors.HypervisorError:
      pass

    return (pidfile, pid, alive)

  @classmethod
  def _CheckDown(cls, instance_name):
    """Raises an error unless the given instance is down.

    """
    alive = cls._InstancePidAlive(instance_name)[2]
    if alive:
      raise errors.HypervisorError("Failed to start instance %s: %s" %
                                   (instance_name, "already running"))

  @classmethod
  def _InstanceMonitor(cls, instance_name):
    """Returns the instance monitor socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.monitor" % instance_name)

  @classmethod
  def _InstanceSerial(cls, instance_name):
    """Returns the instance serial socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.serial" % instance_name)

  @classmethod
  def _InstanceQmpMonitor(cls, instance_name):
    """Returns the instance serial QMP socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.qmp" % instance_name)

  @classmethod
  def _InstanceQemuGuestAgentMonitor(cls, instance_name):
    """Returns the instance serial QEMU Guest Agent socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.qga" % instance_name)

  @classmethod
  def _InstanceKvmdMonitor(cls, instance_name):
    """Returns the instance kvm daemon socket name

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.kvmd" % instance_name)

  @classmethod
  def _InstanceShutdownMonitor(cls, instance_name):
    """Returns the instance QMP output filename

    """
    return utils.PathJoin(cls._CTRL_DIR, "%s.shutdown" % instance_name)

  @staticmethod
  def _SocatUnixConsoleParams():
    """Returns the correct parameters for socat

    If we have a new-enough socat we can use raw mode with an escape character.

    """
    if constants.SOCAT_USE_ESCAPE:
      return "raw,echo=0,escape=%s" % constants.SOCAT_ESCAPE_CODE
    else:
      return "echo=0,icanon=0"

  @classmethod
  def _InstanceKVMRuntime(cls, instance_name):
    """Returns the instance KVM runtime filename

    """
    return utils.PathJoin(cls._CONF_DIR, "%s.runtime" % instance_name)

  @classmethod
  def _InstanceChrootDir(cls, instance_name):
    """Returns the name of the KVM chroot dir of the instance

    """
    return utils.PathJoin(cls._CHROOT_DIR, instance_name)

  @classmethod
  def _InstanceNICDir(cls, instance_name):
    """Returns the name of the directory holding the tap device files for a
    given instance.

    """
    return utils.PathJoin(cls._NICS_DIR, instance_name)

  @classmethod
  def _InstanceNICFile(cls, instance_name, seq):
    """Returns the name of the file containing the tap device for a given NIC

    """
    return utils.PathJoin(cls._InstanceNICDir(instance_name), str(seq))

  @classmethod
  def _TryReadUidFile(cls, uid_file):
    """Try to read a uid file

    """
    if os.path.exists(uid_file):
      try:
        uid = int(utils.ReadOneLineFile(uid_file))
        return uid
      except EnvironmentError:
        logging.warning("Can't read uid file", exc_info=True)
      except (TypeError, ValueError):
        logging.warning("Can't parse uid file contents", exc_info=True)
    return None

  @classmethod
  def _RemoveInstanceRuntimeFiles(cls, pidfile, instance_name):
    """Removes an instance's rutime sockets/files/dirs.

    """
    utils.RemoveFile(pidfile)
    utils.RemoveFile(cls._InstanceMonitor(instance_name))
    utils.RemoveFile(cls._InstanceSerial(instance_name))
    utils.RemoveFile(cls._InstanceQmpMonitor(instance_name))
    utils.RemoveFile(cls._InstanceQemuGuestAgentMonitor(instance_name))
    utils.RemoveFile(cls._InstanceKVMRuntime(instance_name))
    uid_file = cls._InstanceUidFile(instance_name)
    uid = cls._TryReadUidFile(uid_file)
    utils.RemoveFile(uid_file)
    if uid is not None:
      uidpool.ReleaseUid(uid)
    try:
      shutil.rmtree(cls._InstanceNICDir(instance_name))
    except OSError as err:
      if err.errno != errno.ENOENT:
        raise
    try:
      chroot_dir = cls._InstanceChrootDir(instance_name)
      utils.RemoveDir(chroot_dir)
    except OSError as err:
      if err.errno == errno.ENOTEMPTY:
        # The chroot directory is expected to be empty, but it isn't.
        new_chroot_dir = tempfile.mkdtemp(dir=cls._CHROOT_QUARANTINE_DIR,
                                          prefix="%s-%s-" %
                                          (instance_name,
                                           utils.TimestampForFilename()))
        logging.warning("The chroot directory of instance %s can not be"
                        " removed as it is not empty. Moving it to the"
                        " quarantine instead. Please investigate the"
                        " contents (%s) and clean up manually",
                        instance_name, new_chroot_dir)
        utils.RenameFile(chroot_dir, new_chroot_dir)
      else:
        raise

  @staticmethod
  def _ConfigureNIC(instance, seq, nic, tap):
    """Run the network configuration script for a specified NIC

    See L{hv_base.ConfigureNIC}.

    @param instance: instance we're acting on
    @type instance: instance object
    @param seq: nic sequence number
    @type seq: int
    @param nic: nic we're acting on
    @type nic: nic object
    @param tap: the host's tap interface this NIC corresponds to
    @type tap: str

    """
    hv_base.ConfigureNIC([pathutils.KVM_IFUP, tap], instance, seq, nic, tap)

  @classmethod
  def _SetProcessAffinity(cls, process_id, cpus):
    """Sets the affinity of a process to the given CPUs.

    @type process_id: int
    @type cpus: list of int
    @param cpus: The list of CPUs the process ID may use.

    """
    if psutil is None:
      raise errors.HypervisorError("psutil Python package %s"
                                   "; cannot use CPU pinning"
                                   " under KVM" % psutil_err)

    target_process = psutil.Process(process_id)
    if cpus == constants.CPU_PINNING_OFF:
      # we checked this at import time
      # pylint: disable=E1101
      target_process.cpu_affinity(range(psutil.cpu_count()))
    else:
      target_process.cpu_affinity(cpus)

  @classmethod
  def _AssignCpuAffinity(cls, cpu_mask, process_id, thread_dict):
    """Change CPU affinity for running VM according to given CPU mask.

    @param cpu_mask: CPU mask as given by the user. e.g. "0-2,4:all:1,3"
    @type cpu_mask: string
    @param process_id: process ID of KVM process. Used to pin entire VM
                       to physical CPUs.
    @type process_id: int
    @param thread_dict: map of virtual CPUs to KVM thread IDs
    @type thread_dict: dict int:int

    """
    # Convert the string CPU mask to a list of list of int's
    cpu_list = utils.ParseMultiCpuMask(cpu_mask)

    if len(cpu_list) == 1:
      all_cpu_mapping = cpu_list[0]
      if all_cpu_mapping == constants.CPU_PINNING_OFF:
        # If CPU pinning has 1 entry that's "all", then do nothing
        pass
      else:
        # If CPU pinning has one non-all entry, map the entire VM to
        # one set of physical CPUs
        cls._SetProcessAffinity(process_id, all_cpu_mapping)
    else:
      # The number of vCPUs mapped should match the number of vCPUs
      # reported by KVM. This was already verified earlier, so
      # here only as a sanity check.
      assert len(thread_dict) == len(cpu_list)

      # For each vCPU, map it to the proper list of physical CPUs
      for i, vcpu in enumerate(cpu_list):
        cls._SetProcessAffinity(thread_dict[i], vcpu)

  @_with_qmp
  def _GetVcpuThreadIds(self, instance):
    """Get a mapping of vCPU no. to thread IDs for the instance

    @type instance: L{objects.Instance} object
    @param instance: instance in question
    @rtype: dictionary of int:int
    @return: a dictionary mapping vCPU numbers to thread IDs

    """
    result = {}
    cpu_info = self.qmp.GetCpuInformation()

    for cpu in cpu_info:
      result[cpu["cpu-index"]] = cpu["thread-id"]

    return result

  def _ExecuteCpuAffinity(self, instance, cpu_mask):
    """Complete CPU pinning.

    @type instance: L{objects.Instance} object
    @param instance: instance in question
    @type cpu_mask: string
    @param cpu_mask: CPU pinning mask as entered by user

    """
    # Get KVM process ID, to be used if need to pin entire VM
    _, pid, _ = self._InstancePidAlive(instance.name)
    # Get vCPU thread IDs, to be used if need to pin vCPUs separately
    thread_dict = self._GetVcpuThreadIds(instance)
    # Run CPU pinning, based on configured mask
    self._AssignCpuAffinity(cpu_mask, pid, thread_dict)

  @_with_qmp
  def _SetInstanceMigrationCapabilities(self, instance):
    """Set all migration capabilities configured for an instance

    @type instance: L{objects.Instance} object
    @param instance: the VM this command acts upon
    """
    migration_caps = instance.hvparams[constants.HV_KVM_MIGRATION_CAPS]
    if migration_caps:
      migration_caps_list = migration_caps.split(_MIGRATION_CAPS_DELIM)
      self.qmp.SetMigrationCapabilities(migration_caps_list, True)

  @_with_qmp
  def _ClearInstanceMigrationCapabilities(self, instance):
    """Clear all migration capabilities configured for an instance

    @type instance: L{objects.Instance} object
    @param instance: the VM this command acts upon
    """
    migration_caps = instance.hvparams[constants.HV_KVM_MIGRATION_CAPS]
    if migration_caps:
      migration_caps_list = migration_caps.split(_MIGRATION_CAPS_DELIM)
      self.qmp.SetMigrationCapabilities(migration_caps_list, False)

  def ListInstances(self, hvparams=None):
    """Get the list of running instances.

    We can do this by listing our live instances directory and
    checking whether the associated kvm process is still alive.

    """
    result = []
    for name in os.listdir(self._PIDS_DIR):
      if self._InstancePidAlive(name)[2]:
        result.append(name)
    return result

  @classmethod
  def _IsUserShutdown(cls, instance_name):
    return os.path.exists(cls._InstanceShutdownMonitor(instance_name))

  @classmethod
  def _ClearUserShutdown(cls, instance_name):
    utils.RemoveFile(cls._InstanceShutdownMonitor(instance_name))

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be used with this instance
    @rtype: tuple of strings
    @return: (name, id, memory, vcpus, stat, times)

    """
    _, pid, alive = self._InstancePidAlive(instance_name)
    if not alive:
      if self._IsUserShutdown(instance_name):
        return (instance_name, -1, 0, 0, hv_base.HvInstanceState.SHUTDOWN, 0)
      else:
        return None

    _, memory, vcpus = self._InstancePidInfo(pid)
    istat = hv_base.HvInstanceState.RUNNING
    times = 0

    try:
      socket_path = self._InstanceQmpMonitor(instance_name)
      qmp = QmpConnection(socket_path)
      qmp.connect()
      vcpus = len(qmp.execute_qmp("query-cpus-fast"))
      # Will fail if ballooning is not enabled, but we can then just resort to
      # the value above.
      mem_bytes = qmp.execute_qmp("query-balloon")[qmp.ACTUAL_KEY]
      memory = mem_bytes // 1048576
      qmp.close()
    except errors.HypervisorError:
      pass
    # during instance shutdown it may happen, that qemu has already exited
    # in the middle of talking to it via QMP
    except BrokenPipeError:
      logging.debug("Error: Broken pipe. The QMP socket %s has shut down." %
                    socket_path)
    except ConnectionError:
      logging.debug("Error: Unable to connect to the QMP socket %s." %
                    socket_path)

    return (instance_name, pid, memory, vcpus, istat, times)

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters
    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    data = []
    for entry in os.listdir(self._CONF_DIR):
      name, _ = os.path.splitext(entry)
      try:
        info = self.GetInstanceInfo(name)
      except errors.HypervisorError:
        # Ignore exceptions due to instances being shut down
        continue
      if info:
        data.append(info)
    return data

  @staticmethod
  def _GenerateKVMBlockDevice(target, disk_info, hvp, kvm_devid):
    _, direct, no_flush = kvm_utils.GetCacheSettings(
      hvp[constants.HV_DISK_CACHE], disk_info.dev_type)
    access_mode = disk_info.params.get(constants.LDP_ACCESS,
                                       constants.DISK_KERNELSPACE)

    if access_mode == constants.DISK_USERSPACE:
      driver = kvm_utils.ParseStorageUriToBlockdevParam(target)
    else:
      driver = {
        "driver": "file" if disk_info.dev_type in constants.DTS_FILEBASED
          else "host_device",
        "filename": target,
        "aio": hvp[constants.HV_KVM_DISK_AIO]
      }

    return {
      "driver": "raw",
      "node-name": kvm_devid,
      "discard": hvp[constants.HV_DISK_DISCARD],
      "cache": {
        "direct": direct,
        "no-flush": no_flush
      },
      "file": driver
    }

  def _GenerateKVMBlockDevicesOptions(self, up_hvp, kvm_disks,
                                      kvmhelp, devlist,
                                      ide_start_slot=0):
    """Generate KVM options regarding instance's block devices.

    @type up_hvp: dict
    @param up_hvp: the instance's runtime hypervisor parameters
    @type kvm_disks: list of tuples
    @param kvm_disks: list of tuples [(disk, link_name, uri)..]
    @type kvmhelp: string
    @param kvmhelp: output of kvm --help
    @type devlist: string
    @param devlist: output of kvm -device ?
    @rtype: list
    @return: list of command line options eventually used by kvm executable

    """
    kernel_path = up_hvp[constants.HV_KERNEL_PATH]
    if kernel_path:
      boot_disk = False
    else:
      boot_disk = up_hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_DISK

    dev_opts = []
    disk_type = up_hvp[constants.HV_DISK_TYPE]

    if disk_type == constants.HT_DISK_PARAVIRTUAL:
      driver = self._VIRTIO_BLK_PCI
    elif disk_type == constants.HT_DISK_IDE:
      driver = "ide-hd"
    else:
      driver = disk_type

    # Check if a specific driver is supported by QEMU device model.
    if not self._DEVICE_DRIVER_SUPPORTED(driver, devlist):
      raise errors.HypervisorError("QEMU does not support disk driver '%s'"
                                   % driver)

    ide_slot = ide_start_slot
    for cfdev, link_name, uri in kvm_disks:
      if cfdev.mode != constants.DISK_RDWR:
        raise errors.HypervisorError("Instance has read-only disks which"
                                     " are not supported by KVM")

      drive_uri = _GetDriveURI(cfdev, link_name, uri)

      kvm_devid = cfdev.hvinfo["id"]

      writeback, direct, no_flush = kvm_utils.GetCacheSettings(
        up_hvp[constants.HV_DISK_CACHE], cfdev.dev_type)

      blockdevice = self._GenerateKVMBlockDevice(drive_uri, cfdev, up_hvp,
                                                 kvm_devid)

      dev_val = ""

      if disk_type == constants.HT_DISK_IDE:
        ide_bus, ide_unit = _GetIDEBusUnit(ide_slot)
        dev_val += "ide-hd,bus={},unit={},drive={},write-cache={}".format(
          ide_bus, ide_unit,
          kvm_devid, kvm_utils.TranslateBoolToOnOff(writeback)
        )
        ide_slot += 1
      else:
        # hvinfo will exist for paravirtual devices either due to
        # _UpgradeSerializedRuntime() for old instances or due to
        # _GenerateKVMRuntime() for new instances.

        # Add driver, id, bus, and addr or channel, scsi-id, lun if any.
        dev_val += _GenerateDeviceHVInfoStr(cfdev.hvinfo)
        dev_val += ",drive={},write-cache={}".format(
          kvm_devid, kvm_utils.TranslateBoolToOnOff(writeback)
        )

      # TODO: handle FD_LOOP and FD_BLKTAP
      # add bootindex property to the first disk if disk boot is enabled
      if boot_disk:
        dev_val += ",bootindex=1"
        boot_disk = False

      dev_opts.extend(["-device", dev_val])

      # QEMU 4.0 introduced dynamic auto-read-only for file-backed drives. This
      # is unhandled in Ganeti and breaks live migration with
      # security_model=user|pool, disable it here. See also
      # HotAddDevice/drive_add_fn which solves a similar problem for hotplugged
      # disks
      if self._AUTO_RO_RE.search(kvmhelp):
        blockdevice["auto-read-only"] = False

      blockdev_str = kvm_utils.DictToQemuStringNotation(blockdevice)

      dev_opts.extend(["-blockdev", blockdev_str])

    return dev_opts

  def _FloppyOption(self, kvm_cmd, floppy_image, boot_floppy):
    """Extens L{kvm_cmd} with the '-blockdev/-device' options for a floppy, and
    optionally the '-boot' option

    @type kvm_cmd: list of str
    @param kvm_cmd: KVM command line

    @type floppy_image: str
    @param floppy_image: path to floppy image file

    @type boot_floppy: bool
    @param boot_floppy: set boot device to floppy

    """
    bdev_opts = [
      "driver=raw",
      "node-name=floppy1",
      "file.driver=file",
      "file.filename=%s" % floppy_image
    ]

    dev_opts = [
      "floppy",
      "drive=floppy1"
    ]

    if boot_floppy:
      dev_opts.append("bootindex=1")

    kvm_cmd.extend(["-blockdev", ",".join(bdev_opts),
                    "-device",   ",".join(dev_opts)])

  def _CdromOption(self, kvm_cmd, cdrom_disk_type, cdrom_image, cdrom_boot,
                   cdrom_id, ide_slot=None):
    """Extends L{kvm_cmd} with the '-blockdev/-device' options for a cdrom, and
    optionally the '-boot' option.

    @type kvm_cmd: list of str
    @param kvm_cmd: KVM command line

    @type cdrom_disk_type: str
    @param cdrom_disk_type:

    @type cdrom_image: str
    @param cdrom_image:

    @type cdrom_boot: bool
    @param cdrom_boot:

    @type cdrom_id: str
    @param cdrom_id:

    @type ide_slot: int or None
    @param ide_slot: IDE slot index for bus/unit assignment (IDE CDROMs only)

    """
    # Check that the ISO image is accessible
    # See https://bugs.launchpad.net/qemu/+bug/597575
    if utils.IsUrl(cdrom_image) and not _CheckUrl(cdrom_image):
      raise errors.HypervisorError("Cdrom ISO image '%s' is not accessible" %
                                   cdrom_image)

    bdev_opts = [
      "driver=raw",
      "cache.direct=off",
      "cache.no-flush=on",
      "read-only=on",
      "node-name=%s" % cdrom_id
    ]
    if utils.IsUrl(cdrom_image):
      if cdrom_image.lower().startswith("https://"):
        bdev_opts.append("file.driver=https")
      else:
        bdev_opts.append("file.driver=http")
      bdev_opts.append("file.url=%s" % cdrom_image)
    else:
      bdev_opts.append("file.driver=file")
      bdev_opts.append("file.filename=%s" % cdrom_image)

    dev_opts = []
    if cdrom_disk_type == constants.HT_DISK_IDE:
      dev_opts.append("ide-cd")
      if ide_slot is not None:
        ide_bus, ide_unit = _GetIDEBusUnit(ide_slot)
        dev_opts.append("bus=%s" % ide_bus)
        dev_opts.append("unit=%d" % ide_unit)
    elif cdrom_disk_type == constants.HT_DISK_PARAVIRTUAL:
      dev_opts.append(self._VIRTIO_BLK_PCI)
    elif cdrom_disk_type == constants.HT_DISK_SCSI_CD:
      dev_opts.append("scsi-cd")
    else:
      raise errors.HypervisorError("Unsupported cdrom disk type: %s" %
                                   cdrom_disk_type)

    dev_opts.append("drive=%s" % cdrom_id)
    # set boot flag, if needed
    if cdrom_boot:
      dev_opts.append("bootindex=1")

    # build '-drive' option
    kvm_cmd.extend(["-blockdev", ",".join(bdev_opts),
                    "-device",   ",".join(dev_opts)])

  def _GenerateKVMRuntime(self, instance, block_devices, startup_paused,
                          kvmhelp) -> KVMRuntime:
    """Generate KVM information to start an instance.

    @type kvmhelp: string
    @param kvmhelp: output of kvm --help
    @attention: this function must not have any side-effects; for
        example, it must not write to the filesystem, or read values
        from the current system the are expected to differ between
        nodes, since it is only run once at instance startup;
        actions/kvm arguments that can vary between systems should be
        done in L{_ExecuteKVMRuntime}

    """
    # pylint: disable=R0912,R0914,R0915
    hvp = instance.hvparams
    self.ValidateParameters(hvp)

    pidfile = self._InstancePidFile(instance.name)
    kvm = hvp[constants.HV_KVM_PATH]
    kvm_cmd = [kvm]
    # used just by the vnc server, if enabled
    kvm_cmd.extend(["-name", instance.name])
    kvm_cmd.extend(["-m", instance.beparams[constants.BE_MAXMEM]])

    smp_list = ["%s" % instance.beparams[constants.BE_VCPUS]]
    if hvp[constants.HV_CPU_CORES]:
      smp_list.append("cores=%s" % hvp[constants.HV_CPU_CORES])
    if hvp[constants.HV_CPU_THREADS]:
      smp_list.append("threads=%s" % hvp[constants.HV_CPU_THREADS])
    if hvp[constants.HV_CPU_SOCKETS]:
      smp_list.append("sockets=%s" % hvp[constants.HV_CPU_SOCKETS])

    kvm_cmd.extend(["-smp", ",".join(smp_list)])

    kvm_cmd.extend(["-pidfile", pidfile])

    bus_manager = self._get_bus_manager(hvp)

    if hvp[constants.HV_DISK_TYPE] in constants.HT_SCSI_DEVICE_TYPES \
            or hvp[constants.HV_KVM_CDROM_DISK_TYPE]\
            in constants.HT_SCSI_DEVICE_TYPES:
      # In case a SCSI disk is given, QEMU adds a SCSI contorller
      # (LSI Logic / Symbios Logic 53c895a) implicitly.
      # Here, we add the controller explicitly with the default id.
      kvm_cmd.extend([
        "-device",
        "%s,id=scsi" % hvp[constants.HV_KVM_SCSI_CONTROLLER_TYPE]
        ])

    kvm_cmd.extend(["-device", "virtio-balloon"])
    kvm_cmd.extend(["-daemonize"])
    # logfile for qemu
    qemu_logfile = utils.PathJoin(pathutils.LOG_KVM_DIR,
                                  "%s.log" % instance.name)
    kvm_cmd.extend(["-D", qemu_logfile])

    if instance.hvparams[constants.HV_REBOOT_BEHAVIOR] == \
        constants.INSTANCE_REBOOT_EXIT:
      kvm_cmd.extend(["-no-reboot"])

    machine_params = []
    mversion = hvp[constants.HV_KVM_MACHINE_VERSION]
    if not mversion:
      mversion = self._GetDefaultMachineVersion(kvm)
    machine_params.append(mversion)

    if not instance.hvparams[constants.HV_ACPI]:
      if self._ACPI_RE.search(kvmhelp):
        # this parameter has been replaced starting with Qemu 9.0
        kvm_cmd.extend(["-no-acpi"])
      else:
        machine_params.append("acpi=off")

    if hvp[constants.HV_KVM_FLAG] == constants.HT_KVM_ENABLED:
      machine_params.append("accel=kvm")

    kvm_cmd.extend(["-machine", ",".join(machine_params)])

    kernel_path = hvp[constants.HV_KERNEL_PATH]
    if kernel_path:
      boot_cdrom = boot_floppy = False
    else:
      boot_cdrom = hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_CDROM
      boot_floppy = hvp[constants.HV_BOOT_ORDER] == constants.HT_BO_FLOPPY

    if startup_paused:
      kvm_cmd.extend([_KVM_START_PAUSED_FLAG])

    disk_type = hvp[constants.HV_DISK_TYPE]

    # Now we can specify a different device type for CDROM devices.
    cdrom_disk_type = hvp[constants.HV_KVM_CDROM_DISK_TYPE]
    if not cdrom_disk_type:
      cdrom_disk_type = disk_type

    # Track IDE slot allocation: hard drives get first slots, CDROMs follow.
    ide_disk_count = len(block_devices) \
      if disk_type == constants.HT_DISK_IDE else 0
    ide_slot = ide_disk_count

    cdrom_image1 = hvp[constants.HV_CDROM_IMAGE_PATH]
    if cdrom_image1:
      cdrom1_ide_slot = None
      if cdrom_disk_type == constants.HT_DISK_IDE:
        cdrom1_ide_slot = ide_slot
        ide_slot += 1
      self._CdromOption(kvm_cmd, cdrom_disk_type, cdrom_image1, boot_cdrom,
                        "cdrom1", ide_slot=cdrom1_ide_slot)

    cdrom_image2 = hvp[constants.HV_KVM_CDROM2_IMAGE_PATH]
    if cdrom_image2:
      cdrom2_ide_slot = None
      if cdrom_disk_type == constants.HT_DISK_IDE:
        cdrom2_ide_slot = ide_slot
        ide_slot += 1
      self._CdromOption(kvm_cmd, cdrom_disk_type, cdrom_image2, False,
                        "cdrom2", ide_slot=cdrom2_ide_slot)

    # Validate total IDE device count
    if ide_slot > _MAX_IDE_DEVICES:
      raise errors.HypervisorError(
        "Too many IDE devices: %d IDE disks + %d IDE CDROMs exceeds"
        " maximum of %d" % (ide_disk_count, ide_slot - ide_disk_count,
                            _MAX_IDE_DEVICES))

    floppy_image = hvp[constants.HV_KVM_FLOPPY_IMAGE_PATH]
    if floppy_image:
      self._FloppyOption(kvm_cmd, floppy_image, boot_floppy)

    if kernel_path:
      kvm_cmd.extend(["-kernel", kernel_path])
      initrd_path = hvp[constants.HV_INITRD_PATH]
      if initrd_path:
        kvm_cmd.extend(["-initrd", initrd_path])
      root_append = ["root=%s" % hvp[constants.HV_ROOT_PATH],
                     hvp[constants.HV_KERNEL_ARGS]]
      if hvp[constants.HV_SERIAL_CONSOLE]:
        serial_speed = hvp[constants.HV_SERIAL_SPEED]
        root_append.append("console=ttyS0,%s" % serial_speed)
      kvm_cmd.extend(["-append", " ".join(root_append)])

    mem_path = hvp[constants.HV_MEM_PATH]
    if mem_path:
      kvm_cmd.extend(["-mem-path", mem_path, "-mem-prealloc"])

    monitor_dev = ("unix:%s,server,nowait" %
                   self._InstanceMonitor(instance.name))
    kvm_cmd.extend(["-monitor", monitor_dev])
    if hvp[constants.HV_SERIAL_CONSOLE]:
      serial_dev = ("unix:%s,server,nowait" %
                    self._InstanceSerial(instance.name))
      kvm_cmd.extend(["-serial", serial_dev])
    else:
      kvm_cmd.extend(["-serial", "none"])

    mouse_type = hvp[constants.HV_USB_MOUSE]
    vnc_bind_address = hvp[constants.HV_VNC_BIND_ADDRESS]
    spice_bind = hvp[constants.HV_KVM_SPICE_BIND]
    spice_ip_version = None

    kvm_cmd.extend(["-usb"])

    if mouse_type:
      kvm_cmd.extend(["-usbdevice", mouse_type])
    elif vnc_bind_address:
      kvm_cmd.extend(["-usbdevice", constants.HT_MOUSE_TABLET])

    if vnc_bind_address:
      if netutils.IsValidInterface(vnc_bind_address):
        if_addresses = netutils.GetInterfaceIpAddresses(vnc_bind_address)
        if_ip4_addresses = if_addresses[constants.IP4_VERSION]
        if len(if_ip4_addresses) < 1:
          logging.error("Could not determine IPv4 address of interface %s",
                        vnc_bind_address)
        else:
          vnc_bind_address = if_ip4_addresses[0]
      if (netutils.IP4Address.IsValid(vnc_bind_address) or
          netutils.IP6Address.IsValid(vnc_bind_address)):
        if instance.network_port > constants.VNC_BASE_PORT:
          display = instance.network_port - constants.VNC_BASE_PORT
          if vnc_bind_address == constants.IP4_ADDRESS_ANY:
            vnc_arg = ":%d" % (display)
          elif netutils.IP6Address.IsValid(vnc_bind_address):
            vnc_arg = "[%s]:%d" % (vnc_bind_address, display)
          else:
            vnc_arg = "%s:%d" % (vnc_bind_address, display)
        else:
          logging.error("Network port is not a valid VNC display (%d < %d),"
                        " not starting VNC",
                        instance.network_port, constants.VNC_BASE_PORT)
          vnc_arg = "none"

        # Only allow tls and other option when not binding to a file, for now.
        # kvm/qemu gets confused otherwise about the filename to use.
        vnc_append = ""
        if hvp[constants.HV_VNC_TLS]:
          vnc_append = "%s,tls-creds=vnctls0" % vnc_append
          tls_obj = "tls-creds-anon"
          tls_obj_options = ["id=vnctls0", "endpoint=server"]
          if hvp[constants.HV_VNC_X509_VERIFY]:
            tls_obj = "tls-creds-x509"
            tls_obj_options.extend(["dir=%s" %
                                    hvp[constants.HV_VNC_X509],
                                    "verify-peer=yes"])
          elif hvp[constants.HV_VNC_X509]:
            tls_obj = "tls-creds-x509"
            tls_obj_options.extend(["dir=%s" %
                                    hvp[constants.HV_VNC_X509],
                                    "verify-peer=no"])
          kvm_cmd.extend(["-object",
                          "%s,%s" % (tls_obj, ",".join(tls_obj_options))])
        if hvp[constants.HV_VNC_PASSWORD_FILE]:
          vnc_append = "%s,password" % vnc_append

        vnc_arg = "%s%s" % (vnc_arg, vnc_append)

      else:
        vnc_arg = "unix:%s/%s.vnc" % (vnc_bind_address, instance.name)

      kvm_cmd.extend(["-vnc", vnc_arg])
    elif spice_bind:
      # FIXME: this is wrong here; the iface ip address differs
      # between systems, so it should be done in _ExecuteKVMRuntime
      if netutils.IsValidInterface(spice_bind):
        # The user specified a network interface, we have to figure out the IP
        # address.
        addresses = netutils.GetInterfaceIpAddresses(spice_bind)
        spice_ip_version = hvp[constants.HV_KVM_SPICE_IP_VERSION]

        # if the user specified an IP version and the interface does not
        # have that kind of IP addresses, throw an exception
        if spice_ip_version != constants.IFACE_NO_IP_VERSION_SPECIFIED:
          if not addresses[spice_ip_version]:
            raise errors.HypervisorError("SPICE: Unable to get an IPv%s address"
                                         " for %s" % (spice_ip_version,
                                                      spice_bind))

        # the user did not specify an IP version, we have to figure it out
        elif (addresses[constants.IP4_VERSION] and
              addresses[constants.IP6_VERSION]):
          # we have both ipv4 and ipv6, let's use the cluster default IP
          # version
          cluster_family = ssconf.SimpleStore().GetPrimaryIPFamily()
          spice_ip_version = \
            netutils.IPAddress.GetVersionFromAddressFamily(cluster_family)
        elif addresses[constants.IP4_VERSION]:
          spice_ip_version = constants.IP4_VERSION
        elif addresses[constants.IP6_VERSION]:
          spice_ip_version = constants.IP6_VERSION
        else:
          raise errors.HypervisorError("SPICE: Unable to get an IP address"
                                       " for %s" % (spice_bind))

        spice_address = addresses[spice_ip_version][0]

      else:
        # spice_bind is known to be a valid IP address, because
        # ValidateParameters checked it.
        spice_address = spice_bind

      spice_arg = "addr=%s" % spice_address
      if hvp[constants.HV_KVM_SPICE_USE_TLS]:
        spice_arg = ("%s,tls-port=%s,x509-cacert-file=%s" %
                     (spice_arg, instance.network_port,
                      pathutils.SPICE_CACERT_FILE))
        spice_arg = ("%s,x509-key-file=%s,x509-cert-file=%s" %
                     (spice_arg, pathutils.SPICE_CERT_FILE,
                      pathutils.SPICE_CERT_FILE))
        tls_ciphers = hvp[constants.HV_KVM_SPICE_TLS_CIPHERS]
        if tls_ciphers:
          spice_arg = "%s,tls-ciphers=%s" % (spice_arg, tls_ciphers)
      else:
        spice_arg = "%s,port=%s" % (spice_arg, instance.network_port)

      if not hvp[constants.HV_KVM_SPICE_PASSWORD_FILE]:
        spice_arg = "%s,disable-ticketing" % spice_arg

      if spice_ip_version:
        spice_arg = "%s,ipv%s" % (spice_arg, spice_ip_version)

      # Image compression options
      img_lossless = hvp[constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR]
      img_jpeg = hvp[constants.HV_KVM_SPICE_JPEG_IMG_COMPR]
      img_zlib_glz = hvp[constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR]
      if img_lossless:
        spice_arg = "%s,image-compression=%s" % (spice_arg, img_lossless)
      if img_jpeg:
        spice_arg = "%s,jpeg-wan-compression=%s" % (spice_arg, img_jpeg)
      if img_zlib_glz:
        spice_arg = "%s,zlib-glz-wan-compression=%s" % (spice_arg, img_zlib_glz)

      # Video stream detection
      video_streaming = hvp[constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION]
      if video_streaming:
        spice_arg = "%s,streaming-video=%s" % (spice_arg, video_streaming)

      # Audio compression, by default in qemu-kvm it is on
      if not hvp[constants.HV_KVM_SPICE_AUDIO_COMPR]:
        spice_arg = "%s,playback-compression=off" % spice_arg
      if not hvp[constants.HV_KVM_SPICE_USE_VDAGENT]:
        spice_arg = "%s,agent-mouse=off" % spice_arg
      else:
        # Enable the spice agent communication channel between the host and the
        # agent.
        kvm_cmd.extend(["-device", "virtio-serial-pci,id=spice"])
        kvm_cmd.extend([
          "-device",
          "virtserialport,chardev=spicechannel0,name=com.redhat.spice.0",
          ])
        kvm_cmd.extend(["-chardev", "spicevmc,id=spicechannel0,name=vdagent"])

      logging.info("KVM: SPICE will listen on port %s", instance.network_port)
      kvm_cmd.extend(["-spice", spice_arg])

    else:
      # From qemu 1.4 -nographic is incompatible with -daemonize. The new way
      # also works in earlier versions though (tested with 1.1 and 1.3)
      if self._DISPLAY_RE.search(kvmhelp):
        kvm_cmd.extend(["-display", "none"])
      else:
        kvm_cmd.extend(["-nographic"])

    # As requested by music lovers
    if hvp[constants.HV_SOUNDHW]:
      soundhw = hvp[constants.HV_SOUNDHW]
      if self._SOUND_RE.search(kvmhelp):
        kvm_cmd.extend(["-soundhw", soundhw])
      else:
        # Qemu versions >= 7.1 do not support -soundhw anymore
        # also, we need to pick a host backend/driver. we'll use
        # spice if that is configured, otherwise there will be
        # no sound output
        if spice_bind:
          driver = "spice"
        else:
          driver = "none"
        kvm_cmd.extend(["-audio", "driver={},model={},id=soundhw"
                       .format(driver, soundhw)])

    if hvp[constants.HV_USE_LOCALTIME]:
      kvm_cmd.extend(["-rtc", "base=localtime"])

    # Add qemu-KVM -cpu param
    if hvp[constants.HV_CPU_TYPE]:
      kvm_cmd.extend(["-cpu", hvp[constants.HV_CPU_TYPE]])

    # Pass a -vga option if requested, or if spice is used, for backwards
    # compatibility.
    if hvp[constants.HV_VGA]:
      kvm_cmd.extend(["-vga", hvp[constants.HV_VGA]])
    elif spice_bind:
      kvm_cmd.extend(["-vga", "qxl"])

    # Various types of usb devices, comma separated
    if hvp[constants.HV_USB_DEVICES]:
      for dev in hvp[constants.HV_USB_DEVICES].split(","):
        kvm_cmd.extend(["-usbdevice", dev])

    # Set system UUID to instance UUID
    if self._UUID_RE.search(kvmhelp):
      kvm_cmd.extend(["-uuid", instance.uuid])

    # Add guest agent socket
    if hvp[constants.HV_USE_GUEST_AGENT]:
      qga_path = self._InstanceQemuGuestAgentMonitor(instance.name)
      logging.info("KVM: Guest Agent available at %s", qga_path)
      # The 'qga0' identified can change, but the 'org.qemu.guest_agent.0'
      # string is the default expected by the Guest Agent.
      kvm_cmd.extend([
        "-chardev", "socket,path=%s,server,nowait,id=qga0" % qga_path,
        "-device", "virtio-serial,id=qga0",
        "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
        ])

    if hvp[constants.HV_KVM_EXTRA]:
      kvm_cmd.extend(
        shlex.split(hvp[constants.HV_KVM_EXTRA])
      )

    def _generate_kvm_device(dev_type, dev, bus_manager: BusAllocatorManager):
      """Helper for generating a kvm device out of a Ganeti device."""
      kvm_devid = _GenerateDeviceKVMId(dev_type, dev)
      hv_dev_type = _DEVICE_TYPE[dev_type](hvp)
      allocation = bus_manager.get_next_allocation(dev_type, hv_dev_type)
      dev.hvinfo = _GenerateDeviceHVInfo(dev_type, kvm_devid,
                                         hv_dev_type, allocation)
      bus_manager.commit(allocation)

    kvm_disks = []
    for disk, link_name, uri in block_devices:
      _generate_kvm_device(constants.HOTPLUG_TARGET_DISK, disk, bus_manager)
      kvm_disks.append((disk, link_name, uri))

    kvm_nics = []
    for nic in instance.nics:
      _generate_kvm_device(constants.HOTPLUG_TARGET_NIC, nic, bus_manager)
      kvm_nics.append(nic)

    hvparams = hvp

    return KVMRuntime([kvm_cmd, kvm_nics, hvparams, kvm_disks])

  def _WriteKVMRuntime(self, instance_name, data):
    """Write an instance's KVM runtime

    """
    try:
      utils.WriteFile(self._InstanceKVMRuntime(instance_name),
                      data=data)
    except EnvironmentError as err:
      raise errors.HypervisorError("Failed to save KVM runtime file: %s" % err)

  def _ReadKVMRuntime(self, instance_name):
    """Read an instance's KVM runtime

    """
    try:
      file_content = utils.ReadFile(self._InstanceKVMRuntime(instance_name))
    except EnvironmentError as err:
      raise errors.HypervisorError("Failed to load KVM runtime file: %s" % err)
    return file_content

  def _SaveKVMRuntime(self, instance, kvm_runtime: KVMRuntime):
    """Save an instance's KVM runtime

    """

    self._WriteKVMRuntime(instance.name, kvm_runtime.serialize())

  def _LoadKVMRuntime(self, instance, serialized_runtime=None) -> KVMRuntime:
    """Load an instance's KVM runtime

    """
    if not serialized_runtime:
      serialized_runtime = self._ReadKVMRuntime(instance.name)

    return KVMRuntime.from_serialized(serialized_runtime)

  def _RunKVMCmd(self, name, kvm_cmd, tap_fds=None):
    """Run the KVM cmd and check for errors

    @type name: string
    @param name: instance name
    @type kvm_cmd: list of strings
    @param kvm_cmd: runcmd input for kvm
    @type tap_fds: list of int
    @param tap_fds: fds of tap devices opened by Ganeti

    """
    try:
      result = utils.RunCmd(kvm_cmd, noclose_fds=tap_fds)
    finally:
      for fd in tap_fds:
        utils_wrapper.CloseFdNoError(fd)

    if result.failed:
      raise errors.HypervisorError("Failed to start instance %s: %s (%s)" %
                                   (name, result.fail_reason, result.output))
    if not self._InstancePidAlive(name)[2]:
      raise errors.HypervisorError("Failed to start instance %s" % name)

  @staticmethod
  def _GenerateKvmTapName(nic):
    """Generate a TAP network interface name for a NIC.

    See L{hv_base.GenerateTapName}.

    For the case of the empty string, see L{OpenTap}

    @type nic: ganeti.objects.NIC
    @param nic: NIC object for the name should be generated

    @rtype: string
    @return: TAP network interface name, or the empty string if the
             NIC is not used in instance communication

    """
    if nic.name is None or not \
          nic.name.startswith(constants.INSTANCE_COMMUNICATION_NIC_PREFIX):
      return ""

    return hv_base.GenerateTapName()

  def _GetNetworkDeviceFeatures(self, up_hvp, devlist, kvmhelp):
    """Get network device options to properly enable supported features.

    Return a dict of supported and enabled tap features with nic_model along
    with the extra strings to be appended to the --netdev and --device options.
    This function is called before opening a new tap device.

    Currently the features_dict includes the following attributes:
      - vhost (boolean)
      - vnet_hdr (boolean)
      - mq (boolean, int)

    @rtype: (dict, str, str) tuple
    @return: The supported features,
             the string to be appended to the --netdev option,
             the string to be appended to the --device option

    """
    nic_type = up_hvp[constants.HV_NIC_TYPE]
    nic_extra_str = ""
    tap_extra_str = ""
    features = {
      "vhost": False,
      "vnet_hdr": False,
      "mq": (False, 1)
      }
    update_features = {}
    if nic_type == constants.HT_NIC_PARAVIRTUAL:
      if self._DEVICE_DRIVER_SUPPORTED(self._VIRTIO_NET_PCI, devlist):
        nic_model = self._VIRTIO_NET_PCI
        update_features["vnet_hdr"] = up_hvp[constants.HV_VNET_HDR]
      else:
        # Older versions of kvm don't support DEVICE_LIST, but they don't
        # have new virtio syntax either.
        nic_model = self._VIRTIO

      if up_hvp[constants.HV_VHOST_NET]:
        # Check for vhost_net support.
        if self._VHOST_RE.search(kvmhelp):
          update_features["vhost"] = True
          tap_extra_str = ",vhost=on"
        else:
          raise errors.HypervisorError("vhost_net is configured"
                                       " but it is not available")
        virtio_net_queues = up_hvp.get(constants.HV_VIRTIO_NET_QUEUES, 1)
        if virtio_net_queues > 1:
          # Check for multiqueue virtio-net support.
          if self._VIRTIO_NET_QUEUES_RE.search(kvmhelp):
            # As advised at http://www.linux-kvm.org/page/Multiqueue formula
            # for calculating vector size is: vectors=2*N+2 where N is the
            # number of queues (HV_VIRTIO_NET_QUEUES).
            nic_extra_str = ",mq=on,vectors=%d" % (2 * virtio_net_queues + 2)
            update_features["mq"] = (True, virtio_net_queues)
          else:
            raise errors.HypervisorError("virtio_net_queues is configured"
                                         " but it is not available")
    else:
      nic_model = nic_type

    update_features["driver"] = nic_model
    features.update(update_features)

    return features, tap_extra_str, nic_extra_str

  def _GenerateRunwith(self, username=None, chroot_dir=None, kvmhelp=None):
    args = []
    if self._RUNWITH_RE.search(kvmhelp):
      if username:
        args.append("user=%s" % username)
      if chroot_dir:
        args.append("chroot=%s" % chroot_dir)
      return(["-run-with", ",".join(args)])
    else:
      if username:
        args.extend(["-runas", username])
      if chroot_dir:
        args.extend(["-chroot", chroot_dir])
      return(args)

    # nothing to do
    return([])

  # too many local variables
  # pylint: disable=R0914
  @_with_qmp
  def _ExecuteKVMRuntime(self, instance, kvm_runtime: KVMRuntime,
                         kvmhelp, incoming=None):
    """Execute a KVM cmd, after completing it with some last minute data.

    @type instance: L{objects.Instance} object
    @param instance: the VM this command acts upon
    @type kvm_runtime: tuple of (list of str, list of L{objects.NIC} objects,
        dict of hypervisor options, list of tuples (L{objects.Disk}, str, str)
    @param kvm_runtime: (kvm command, NICs of the instance, options at startup
        of the instance, [(disk, link_name, uri)..])
    @type incoming: tuple of strings
    @param incoming: (target_host_ip, port) for migration.
    @type kvmhelp: string
    @param kvmhelp: output of kvm --help

    """
    # Small _ExecuteKVMRuntime hv parameters programming howto:
    #  - conf_hvp contains the parameters as configured on ganeti. they might
    #    have changed since the instance started; only use them if the change
    #    won't affect the inside of the instance (which hasn't been rebooted).
    #  - up_hvp contains the parameters as they were when the instance was
    #    started, plus any new parameter which has been added between ganeti
    #    versions: it is paramount that those default to a value which won't
    #    affect the inside of the instance as well.
    conf_hvp = instance.hvparams
    name = instance.name
    self._CheckDown(name)

    self._ClearUserShutdown(instance.name)
    self._StartKvmd(instance.hvparams)

    temp_files = []

    kvm_cmd = kvm_runtime.kvm_cmd
    kvm_nics = kvm_runtime.kvm_nics
    up_hvp = kvm_runtime.up_hvp
    kvm_disks = kvm_runtime.kvm_disks

    # the first element of kvm_cmd is always the path to the kvm binary
    kvm_path = kvm_cmd[0]
    up_hvp = objects.FillDict(conf_hvp, up_hvp)

    # the VNC keymap
    keymap = conf_hvp[constants.HV_KEYMAP]
    if keymap:
      kvm_cmd.extend(["-k", keymap])

    # We have reasons to believe changing something like the nic driver/type
    # upon migration won't exactly fly with the instance kernel, so for nic
    # related parameters we'll use up_hvp
    tapfds = []
    taps = []
    devlist = self._GetKVMOutput(kvm_path, self._KVMOPT_DEVICELIST)

    kernel_path = up_hvp[constants.HV_KERNEL_PATH]
    if kernel_path:
      boot_network = False
    else:
      boot_network = (up_hvp.get(constants.HV_BOOT_ORDER, '') ==
                      constants.HT_BO_NETWORK)

    if not kvm_nics:
      kvm_cmd.extend(["-net", "none"])
    else:
      features, tap_extra, nic_extra = \
          self._GetNetworkDeviceFeatures(up_hvp, devlist, kvmhelp)
      nic_model = features["driver"]
      kvm_supports_netdev = self._NETDEV_RE.search(kvmhelp)
      for nic_seq, nic in enumerate(kvm_nics):
        tapname, nic_tapfds, nic_vhostfds = \
          OpenTap(features=features, name=self._GenerateKvmTapName(nic))

        tapfds.extend(nic_tapfds)
        tapfds.extend(nic_vhostfds)
        taps.append(tapname)
        tapfd = "%s%s" % ("fds=" if len(nic_tapfds) > 1 else "fd=",
                          ":".join(str(fd) for fd in nic_tapfds))

        if nic_vhostfds:
          vhostfd = "%s%s" % (",vhostfds="
                              if len(nic_vhostfds) > 1 else ",vhostfd=",
                              ":".join(str(fd) for fd in nic_vhostfds))
        else:
          vhostfd = ""

        if kvm_supports_netdev:
          dev_opts = []

          # Non paravirtual NICs hvinfo is empty
          if "id" in nic.hvinfo:
            nic_val = _GenerateDeviceHVInfoStr(nic.hvinfo)
            netdev = nic.hvinfo["id"]
          else:
            nic_val = "%s" % nic_model
            netdev = "netdev%d" % nic_seq

          nic_val += (",netdev=%s,mac=%s%s" % (netdev, nic.mac, nic_extra))
          tap_val = ("type=tap,id=%s,%s%s%s" %
                     (netdev, tapfd, vhostfd, tap_extra))
          dev_opts.append(nic_val)

          # add bootindex property to the first nic if network boot is enabled
          if boot_network:
            dev_opts.append("bootindex=1")
            boot_network = False

          kvm_cmd.extend(["-netdev", tap_val, "-device", ','.join(dev_opts)])
        else:
          nic_val = "nic,vlan=%s,macaddr=%s,model=%s" % (nic_seq,
                                                         nic.mac, nic_model)
          tap_val = "tap,vlan=%s,%s" % (nic_seq, tapfd)
          kvm_cmd.extend(["-net", tap_val, "-net", nic_val])

    if incoming:
      target, port = incoming
      kvm_cmd.extend(["-incoming", "tcp:%s:%s" % (target, port)])

    # Changing the vnc password doesn't bother the guest that much. At most it
    # will surprise people who connect to it. Whether positively or negatively
    # it's debatable.
    vnc_pwd_file = conf_hvp[constants.HV_VNC_PASSWORD_FILE]
    vnc_pwd = None
    if vnc_pwd_file:
      try:
        vnc_pwd = utils.ReadOneLineFile(vnc_pwd_file, strict=True)
      except EnvironmentError as err:
        raise errors.HypervisorError("Failed to open VNC password file %s: %s"
                                     % (vnc_pwd_file, err))

    if conf_hvp[constants.HV_KVM_USE_CHROOT]:
      utils.EnsureDirs([(self._InstanceChrootDir(name),
                         constants.SECURE_DIR_MODE)])

    # Automatically enable QMP if version is >= 0.14
    if self._QMP_RE.search(kvmhelp):
      logging.debug("Enabling QMP")
      kvm_cmd.extend(["-qmp", "unix:%s,server,nowait" %
                      self._InstanceQmpMonitor(instance.name)])
      # Add a second monitor for kvmd
      kvm_cmd.extend(["-qmp", "unix:%s,server,nowait" %
                      self._InstanceKvmdMonitor(instance.name)])

    # Configure the network now for starting instances and bridged/OVS
    # interfaces, during FinalizeMigration for incoming instances' routed
    # interfaces.
    for nic_seq, nic in enumerate(kvm_nics):
      if (incoming and
          nic.nicparams[constants.NIC_MODE] == constants.NIC_MODE_ROUTED):
        continue
      self._ConfigureNIC(instance, nic_seq, nic, taps[nic_seq])

    bdev_opts = self._GenerateKVMBlockDevicesOptions(up_hvp,
                                                     kvm_disks,
                                                     kvmhelp,
                                                     devlist)
    kvm_cmd.extend(bdev_opts)
    # CPU affinity requires kvm to start paused, so we set this flag if the
    # instance is not already paused and if we are not going to accept a
    # migrating instance. In the latter case, pausing is not needed.
    start_kvm_paused = not (_KVM_START_PAUSED_FLAG in kvm_cmd) and not incoming
    if start_kvm_paused:
      kvm_cmd.extend([_KVM_START_PAUSED_FLAG])

    # Note: CPU pinning is using up_hvp since changes take effect
    # during instance startup anyway, and to avoid problems when soft
    # rebooting the instance.
    cpu_pinning = False
    if up_hvp.get(constants.HV_CPU_MASK, None) \
        and up_hvp[constants.HV_CPU_MASK] != constants.CPU_PINNING_ALL:
      cpu_pinning = True

    # chroot and user are combind into -runwith since qemu-9.0
    chroot_dir = None
    security_model = conf_hvp[constants.HV_SECURITY_MODEL]
    if conf_hvp[constants.HV_KVM_USE_CHROOT]:
      chroot_dir = self._InstanceChrootDir(instance.name)
      # only chroot is set, no run user
      if security_model == constants.HT_SM_NONE:
        kvm_cmd.extend(
          self._GenerateRunwith(chroot_dir=chroot_dir,
                           kvmhelp=kvmhelp)
        )

    if security_model == constants.HT_SM_USER:
      username = conf_hvp[constants.HV_SECURITY_DOMAIN]
      kvm_cmd.extend(
        self._GenerateRunwith(chroot_dir=chroot_dir,
                         username=username,
                         kvmhelp=kvmhelp)
      )

    if security_model == constants.HT_SM_POOL:
      ss = ssconf.SimpleStore()
      uid_pool = uidpool.ParseUidPool(ss.GetUidPool(), separator="\n")
      all_uids = set(uidpool.ExpandUidPool(uid_pool))
      uid = uidpool.RequestUnusedUid(all_uids)
      try:
        username = pwd.getpwuid(uid.GetUid()).pw_name
        kvm_cmd.extend(
          self._GenerateRunwith(chroot_dir=chroot_dir,
                           username=username,
                           kvmhelp=kvmhelp)
        )
        self._RunKVMCmd(name, kvm_cmd, tapfds)
      except:
        uidpool.ReleaseUid(uid)
        raise
      else:
        uid.Unlock()
        utils.WriteFile(self._InstanceUidFile(name), data=uid.AsStr())
    else:
      self._RunKVMCmd(name, kvm_cmd, tapfds)

    utils.EnsureDirs([(self._InstanceNICDir(instance.name),
                       constants.RUN_DIRS_MODE)])
    for nic_seq, tap in enumerate(taps):
      utils.WriteFile(self._InstanceNICFile(instance.name, nic_seq), data=tap)

    if vnc_pwd:
      self.qmp.SetVNCPassword(vnc_pwd)

    # Setting SPICE password. We are not vulnerable to malicious passwordless
    # connection attempts because SPICE by default does not allow connections
    # if neither a password nor the "disable_ticketing" options are specified.
    # As soon as we send the password via QMP, that password is a valid ticket
    # for connection.
    spice_password_file = conf_hvp[constants.HV_KVM_SPICE_PASSWORD_FILE]
    if spice_password_file:
      spice_pwd = ""
      try:
        spice_pwd = utils.ReadOneLineFile(spice_password_file, strict=True)
      except EnvironmentError as err:
        raise errors.HypervisorError("Failed to open SPICE password file %s: %s"
                                     % (spice_password_file, err))

      self.qmp.SetSpicePassword(spice_pwd)

    for filename in temp_files:
      utils.RemoveFile(filename)

    # If requested, set CPU affinity and resume instance execution
    if cpu_pinning:
      self._ExecuteCpuAffinity(instance, up_hvp[constants.HV_CPU_MASK])

    start_memory = self._InstanceStartupMemory(instance)
    if start_memory < instance.beparams[constants.BE_MAXMEM]:
      self.BalloonInstanceMemory(instance, start_memory)

    if start_kvm_paused:
      # To control CPU pinning, ballooning, and vnc/spice passwords
      # the VM was started in a frozen state. If freezing was not
      # explicitly requested resume the vm status.
      self.qmp.ContinueGuestEmulation()

  @staticmethod
  def _StartKvmd(hvparams):
    """Ensure that the Kvm daemon is running.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters

    """
    if hvparams is None \
          or not hvparams[constants.HV_KVM_USER_SHUTDOWN] \
          or utils.IsDaemonAlive(constants.KVMD):
      return

    result = utils.RunCmd([pathutils.DAEMON_UTIL, "start", constants.KVMD])

    if result.failed:
      raise errors.HypervisorError("Failed to start KVM daemon")

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    """
    self._CheckDown(instance.name)
    kvmpath = instance.hvparams[constants.HV_KVM_PATH]
    kvmhelp = self._GetKVMOutput(kvmpath, self._KVMOPT_HELP)
    kvm_runtime = self._GenerateKVMRuntime(instance, block_devices,
                                           startup_paused, kvmhelp)
    self._SaveKVMRuntime(instance, kvm_runtime)
    self._ExecuteKVMRuntime(instance, kvm_runtime, kvmhelp)

  @_with_qmp
  def VerifyHotplugSupport(self, instance, action, dev_type):
    """Verifies that hotplug is supported.

    Hotplug is not supported if:

      - the instance is not running
      - the device type is not hotplug-able
      - the QMP version does not support the corresponding commands

    @raise errors.HypervisorError: if one of the above applies

    """
    runtime = self._LoadKVMRuntime(instance)
    device_type = _DEVICE_TYPE[dev_type](runtime[2])
    if device_type not in _HOTPLUGGABLE_DEVICE_TYPES[dev_type]:
      msg = "Hotplug is not supported for device type %s" % device_type
      raise errors.HypervisorError(msg)

    if dev_type == constants.HOTPLUG_TARGET_DISK:
      if action == constants.HOTPLUG_ACTION_ADD:
        self.qmp.CheckDiskHotAddSupport()
    if dev_type == constants.HOTPLUG_TARGET_NIC:
      if action == constants.HOTPLUG_ACTION_ADD:
        self.qmp.CheckNicHotAddSupport()


  @_with_qmp
  def ResizeDisk(self, instance, disk, new_size):
    """ Notify the HV about a disk change.
    """

    disk_id = _GenerateDeviceKVMId('disk', disk)

    self.qmp.ResizeBlockDevice(disk_id, new_size)


  @_with_qmp
  def HotplugSupported(self, instance):
    """Checks if hotplug is generally supported.

    Hotplug is *not* supported in case of:
     - qemu versions < 1.7 (where all qmp related commands are supported)
     - for stopped instances

    @raise errors.HypervisorError: in one of the previous cases

    """

    try:
      version = self.qmp.GetVersion()
    except errors.HypervisorError:
      raise errors.HotplugError("Instance is probably down")

    #TODO: delegate more fine-grained checks to VerifyHotplugSupport
    if version < (1, 7, 0):
      raise errors.HotplugError("Hotplug not supported for qemu versions < 1.7")

  def _get_bus_manager(self, hvp=None, runtime: KVMRuntime=None) -> (
          BusAllocatorManager):
    """
    Helper function to get the bus manager.
    """

    scsi_allocator = SCSIAllocator(max_slots=self._DEFAULT_SCSI_SLOTS,
                                   reserved_slots=0)

    reserved_pci_slots = self._DEFAULT_PCI_RESERVED_SLOTS
    if hvp and constants.HV_KVM_PCI_RESERVATIONS in hvp:
      reserved_pci_slots = hvp[constants.HV_KVM_PCI_RESERVATIONS]

    pci_allocator = PCIAllocator(max_slots=constants.QEMU_PCI_SLOTS,
                                 reserved_slots=reserved_pci_slots)

    # during hot-add
    if runtime:
      nics = runtime.kvm_nics
      disks = [d for d, _, _ in runtime.kvm_disks]
      dev_infos = [info.hvinfo for info in (disks + nics)]
      pci_allocator.initialize_from_device_info(dev_infos)
      scsi_allocator.initialize_from_device_info(dev_infos)

    return BusAllocatorManager([pci_allocator, scsi_allocator])

  def _GetBusSlots(self, hvp=None, runtime: KVMRuntime=None):
    """Helper function to get the slots of PCI and SCSI QEMU buses.

    This will return the status of the first PCI and SCSI buses. By default
    QEMU boots with one PCI bus (pci.0) and occupies the first 3 PCI slots. If
    a SCSI disk is found then a SCSI controller is added on the PCI bus and a
    SCSI bus (scsi.0) is created.

    During hotplug we could query QEMU via info qtree HMP command but parsing
    the result is too complicated. Instead we use the info stored in runtime
    files. We parse NIC and disk entries and based on their hvinfo we reserve
    the corresponding slots.

    The runtime argument is a tuple as returned by _LoadKVMRuntime(). Obtain
    disks and NICs from it. In case a runtime file is not available (see
    _GenerateKVMRuntime()) we return the bus slots that QEMU boots with by
    default.

    """
    # This is by default and returned during _GenerateKVMRuntime()
    bus_slots = {
      _PCI_BUS: bitarray(self._DEFAULT_PCI_RESERVATIONS),
      _SCSI_BUS: bitarray(self._DEFAULT_SCSI_RESERVATIONS),
      }

    # Adjust the empty slots depending of the corresponding hvparam
    if hvp and constants.HV_KVM_PCI_RESERVATIONS in hvp:
      res = hvp[constants.HV_KVM_PCI_RESERVATIONS]
      pci = bitarray(constants.QEMU_PCI_SLOTS)
      pci.setall(False) # pylint: disable=E1101
      pci[0:res:1] = True
      bus_slots[_PCI_BUS] = pci

    # This is during hot-add
    if runtime:
      nics = runtime.kvm_nics
      disks = [d for d, _, _ in runtime.kvm_disks]
      for d in disks + nics:
        if not d.hvinfo or "bus" not in d.hvinfo:
          continue
        bus = d.hvinfo["bus"]
        slots = bus_slots[bus]
        if bus == _PCI_BUS:
          slot = d.hvinfo["addr"]
          slots[int(slot, 16)] = True
        elif bus == _SCSI_BUS:
          slot = d.hvinfo["scsi-id"]
          slots[slot] = True

    return bus_slots

  @_with_qmp
  def _VerifyHotplugCommand(self, _instance, kvm_devid, should_exist):
    """Checks if a previous hotplug command has succeeded.

    Depending on the should_exist value, verifies that an entry identified by
    device ID is present or not.

    @raise errors.HypervisorError: if result is not the expected one

    """
    for i in range(5):
      found = self.qmp.HasDevice(kvm_devid)
      logging.info("Verifying hotplug command (retry %s): %s", i, found)
      if found and should_exist:
        break
      if not found and not should_exist:
        break
      time.sleep(1)

    if found and not should_exist:
      msg = "Device %s should have been removed but is still there" % kvm_devid
      raise errors.HypervisorError(msg)

    if not found and should_exist:
      msg = "Device %s should have been added but is missing" % kvm_devid
      raise errors.HypervisorError(msg)

    logging.info("Device %s has been correctly hot-plugged", kvm_devid)

  @_with_qmp
  def HotAddDevice(self, instance, dev_type, device, extra, seq):
    """ Helper method to hot-add a new device

    It generates the device ID and hvinfo, and invokes the
    device-specific method.

    """
    kvm_devid = _GenerateDeviceKVMId(dev_type, device)
    runtime = self._LoadKVMRuntime(instance)
    up_hvp = runtime[2]
    device_type = _DEVICE_TYPE[dev_type](up_hvp)
    bus_manager = self._get_bus_manager(up_hvp, runtime)
    allocation = bus_manager.get_next_allocation(dev_type=dev_type,
                                                 hv_dev_type=device_type)
    # in case of hot-mod this is given
    if not device.hvinfo:
      device.hvinfo = _GenerateDeviceHVInfo(dev_type, kvm_devid,
                                            device_type, allocation)

    new_runtime_entry = _RUNTIME_ENTRY[dev_type](device, extra)
    if dev_type == constants.HOTPLUG_TARGET_DISK:
      disk_info = new_runtime_entry[0]
      access_mode = disk_info.params.get(constants.LDP_ACCESS,
                                         constants.DISK_KERNELSPACE)

      writeback, direct, no_flush = kvm_utils.GetCacheSettings(
        up_hvp[constants.HV_DISK_CACHE], disk_info.dev_type)

      target = _GetDriveURI(device, extra[0], extra[1])

      blockdevice = self._GenerateKVMBlockDevice(target, disk_info, up_hvp,
                                                 kvm_devid)

      self.qmp.HotAddDisk(device, access_mode, writeback, direct, blockdevice)
    elif dev_type == constants.HOTPLUG_TARGET_NIC:
      kvmpath = instance.hvparams[constants.HV_KVM_PATH]
      is_chrooted = instance.hvparams[constants.HV_KVM_USE_CHROOT]
      kvmhelp = self._GetKVMOutput(kvmpath, self._KVMOPT_HELP)
      devlist = self._GetKVMOutput(kvmpath, self._KVMOPT_DEVICELIST)
      features, _, _ = self._GetNetworkDeviceFeatures(up_hvp, devlist, kvmhelp)
      (tap, tapfds, vhostfds) = OpenTap(features=features)
      self._ConfigureNIC(instance, seq, device, tap)
      self.qmp.HotAddNic(device, kvm_devid, tapfds, vhostfds, features,
                         is_chrooted)
      utils.WriteFile(self._InstanceNICFile(instance.name, seq), data=tap)

    self._VerifyHotplugCommand(instance, kvm_devid, True)
    # commit the allocation if hotplug was successful
    bus_manager.commit(allocation)

    # update relevant entries in runtime file
    index = _DEVICE_RUNTIME_INDEX[dev_type]
    runtime[index].append(new_runtime_entry)
    self._SaveKVMRuntime(instance, runtime)

  @_with_qmp
  def HotDelDevice(self, instance, dev_type, device, _, seq):
    """ Helper method for hot-del device

    It gets device info from runtime file, generates the device name and
    invokes the device-specific method.

    """
    runtime = self._LoadKVMRuntime(instance)
    entry = _GetExistingDeviceInfo(dev_type, device, runtime)
    kvm_device = _RUNTIME_DEVICE[dev_type](entry)
    kvm_devid = _GenerateDeviceKVMId(dev_type, kvm_device)
    if dev_type == constants.HOTPLUG_TARGET_DISK:
      self.qmp.HotDelDisk(kvm_devid)
    elif dev_type == constants.HOTPLUG_TARGET_NIC:
      self.qmp.HotDelNic(kvm_devid)
      utils.RemoveFile(self._InstanceNICFile(instance.name, seq))
    self._VerifyHotplugCommand(instance, kvm_devid, False)
    index = _DEVICE_RUNTIME_INDEX[dev_type]
    runtime[index].remove(entry)
    self._SaveKVMRuntime(instance, runtime)

    return kvm_device.hvinfo

  def HotModDevice(self, instance, dev_type, device, _, seq):
    """ Helper method for hot-mod device

    It gets device info from runtime file, generates the device name and
    invokes the device-specific method. Currently only NICs support hot-mod

    """
    if dev_type == constants.HOTPLUG_TARGET_NIC:
      # putting it back in the same bus and slot
      device.hvinfo = self.HotDelDevice(instance, dev_type, device, _, seq)
      self.HotAddDevice(instance, dev_type, device, _, seq)

  @classmethod
  def _ParseKVMVersion(cls, text):
    """Parse the KVM version from the --help output.

    @type text: string
    @param text: output of kvm --help
    @return: (version, v_maj, v_min, v_rev)
    @raise errors.HypervisorError: when the KVM version cannot be retrieved

    """
    match = cls._VERSION_RE.search(text.splitlines()[0])
    if not match:
      raise errors.HypervisorError("Unable to get KVM version")

    v_all = match.group(0)
    v_maj = int(match.group(1))
    v_min = int(match.group(2))
    if match.group(4):
      v_rev = int(match.group(4))
    else:
      v_rev = 0
    return (v_all, v_maj, v_min, v_rev)

  @classmethod
  def _GetKVMOutput(cls, kvm_path, option):
    """Return the output of a kvm invocation

    @type kvm_path: string
    @param kvm_path: path to the kvm executable
    @type option: a key of _KVMOPTS_CMDS
    @param option: kvm option to fetch the output from
    @return: output a supported kvm invocation
    @raise errors.HypervisorError: when the KVM help output cannot be retrieved

    """
    assert option in cls._KVMOPTS_CMDS, "Invalid output option"

    optlist, can_fail = cls._KVMOPTS_CMDS[option]

    result = utils.RunCmd([kvm_path] + optlist)
    if result.failed and not can_fail:
      raise errors.HypervisorError("Unable to get KVM %s output" %
                                    " ".join(optlist))
    return result.output

  @classmethod
  def _GetKVMVersion(cls, kvm_path):
    """Return the installed KVM version.

    @return: (version, v_maj, v_min, v_rev)
    @raise errors.HypervisorError: when the KVM version cannot be retrieved

    """
    return cls._ParseKVMVersion(cls._GetKVMOutput(kvm_path, cls._KVMOPT_HELP))

  @classmethod
  def _GetDefaultMachineVersion(cls, kvm_path):
    """Return the default hardware revision (e.g. pc-1.1)

    """
    output = cls._GetKVMOutput(kvm_path, cls._KVMOPT_MLIST)
    match = cls._DEFAULT_MACHINE_VERSION_RE.search(output)
    if match:
      return match.group(1)
    else:
      return "pc"

  @_with_qmp
  def _StopInstance(self, instance, force=False, name=None, timeout=None):
    """Stop an instance.

    """
    assert(timeout is None or force is not None)

    if name is not None and not force:
      raise errors.HypervisorError("Cannot shutdown cleanly by name only")
    if name is None:
      name = instance.name
      acpi = instance.hvparams[constants.HV_ACPI]
    else:
      acpi = False
    _, pid, alive = self._InstancePidAlive(name)
    if pid > 0 and alive:
      if force or not acpi:
        utils.KillProcess(pid)
      else:
        self.qmp.Powerdown()

    self._ClearUserShutdown(instance.name)

  def StopInstance(self, instance, force=False, retry=False, name=None,
                   timeout=None):
    """Stop an instance.

    """
    self._StopInstance(instance, force, name=name, timeout=timeout)

  def CleanupInstance(self, instance_name):
    """Cleanup after a stopped instance

    """
    pidfile, pid, alive = self._InstancePidAlive(instance_name)
    if pid > 0 and alive:
      raise errors.HypervisorError("Cannot cleanup a live instance")
    self._RemoveInstanceRuntimeFiles(pidfile, instance_name)
    self._ClearUserShutdown(instance_name)

  def RebootInstance(self, instance):
    """Reboot an instance.

    """
    # For some reason if we do a 'send-key ctrl-alt-delete' to the control
    # socket the instance will stop, but now power up again. So we'll resort
    # to shutdown and restart.
    _, _, alive = self._InstancePidAlive(instance.name)
    if not alive:
      raise errors.HypervisorError("Failed to reboot instance %s:"
                                   " not running" % instance.name)
    # StopInstance will delete the saved KVM runtime so:
    # ...first load it...
    kvm_runtime = self._LoadKVMRuntime(instance)
    # ...now we can safely call StopInstance...
    if not self.StopInstance(instance):
      self.StopInstance(instance, force=True)
    # ...and finally we can save it again, and execute it...
    self._SaveKVMRuntime(instance, kvm_runtime)
    kvmpath = instance.hvparams[constants.HV_KVM_PATH]
    kvmhelp = self._GetKVMOutput(kvmpath, self._KVMOPT_HELP)
    self._ExecuteKVMRuntime(instance, kvm_runtime, kvmhelp)

  def MigrationInfo(self, instance):
    """Get instance information to perform a migration.

    @type instance: L{objects.Instance}
    @param instance: instance to be migrated
    @rtype: string
    @return: content of the KVM runtime file

    """
    return self._ReadKVMRuntime(instance.name)

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string
    @param info: content of the KVM runtime file on the source node
    @type target: string
    @param target: target host (usually ip), on this node

    """
    kvm_runtime = self._LoadKVMRuntime(instance, serialized_runtime=info)
    incoming_address = (target, instance.hvparams[constants.HV_MIGRATION_PORT])
    kvmpath = instance.hvparams[constants.HV_KVM_PATH]
    kvmhelp = self._GetKVMOutput(kvmpath, self._KVMOPT_HELP)
    self._ExecuteKVMRuntime(instance, kvm_runtime, kvmhelp,
                            incoming=incoming_address)
    self._SetInstanceMigrationCapabilities(instance)

  def _ConfigureRoutedNICs(self, instance, info):
    """Configures all NICs in routed mode

    @type instance: L{objects.Instance}
    @param instance: the instance to be configured
    @type info: string
    @param info: serialized KVM runtime info
    """
    kvm_runtime = self._LoadKVMRuntime(instance, serialized_runtime=info)
    kvm_nics = kvm_runtime[1]

    for nic_seq, nic in enumerate(kvm_nics):
      if nic.nicparams[constants.NIC_MODE] != constants.NIC_MODE_ROUTED:
        # Bridged/OVS interfaces have already been configured
        continue
      try:
        tap = utils.ReadFile(self._InstanceNICFile(instance.name, nic_seq))
      except EnvironmentError as err:
        logging.warning("Failed to find host interface for %s NIC #%d: %s",
                        instance.name, nic_seq, str(err))
        continue
      try:
        self._ConfigureNIC(instance, nic_seq, nic, tap)
      except errors.HypervisorError as err:
        logging.warning(str(err))

  def FinalizeMigrationDst(self, instance, info, success):
    """Finalize the instance migration on the target node.

    Stop the incoming mode KVM.

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being finalized

    """
    if success:
      self._ConfigureRoutedNICs(instance, info)
      self._WriteKVMRuntime(instance.name, info)
      self._ClearInstanceMigrationCapabilities(instance)
    else:
      self.StopInstance(instance, force=True)

  @_with_qmp
  def MigrateInstance(self, cluster_name, instance, target, live_migration):
    """Migrate an instance to a target node.

    The migration will not be attempted if the instance is not
    currently running.

    @type cluster_name: string
    @param cluster_name: name of the cluster
    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: ip address of the target node
    @type live_migration: boolean
    @param live_migration: perform a live migration

    """
    instance_name = instance.name
    port = instance.hvparams[constants.HV_MIGRATION_PORT]
    _, _, alive = self._InstancePidAlive(instance_name)
    if not alive:
      raise errors.HypervisorError("Instance not running, cannot migrate")

    if not live_migration:
      self.qmp.StopGuestEmulation()

    max_bandwidth_in_bytes = \
        instance.hvparams[constants.HV_MIGRATION_BANDWIDTH] * 1024 * 1024
    self.qmp.SetMigrationParameters(max_bandwidth_in_bytes,
        instance.hvparams[constants.HV_MIGRATION_DOWNTIME])

    self._SetInstanceMigrationCapabilities(instance)
    self.qmp.StartMigration(target, port)

  @_with_qmp
  def FinalizeMigrationSource(self, instance, success, _):
    """Finalize the instance migration on the source node.

    @type instance: L{objects.Instance}
    @param instance: the instance that was migrated
    @type success: bool
    @param success: whether the migration succeeded or not

    """
    if success:
      pidfile, pid, _ = self._InstancePidAlive(instance.name)
      utils.KillProcess(pid)
      self._RemoveInstanceRuntimeFiles(pidfile, instance.name)
      self._ClearUserShutdown(instance.name)
    else:
      # Detect if PID is alive rather than deciding if we were to perform a live
      # migration.
      _, _, alive = self._InstancePidAlive(instance.name)
      if alive:
        self.qmp.ContinueGuestEmulation()
        self._ClearInstanceMigrationCapabilities(instance)
      else:
        self.CleanupInstance(instance.name)

  @_with_qmp
  def GetMigrationStatus(self, instance):
    """Get the migration status

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """

    for _ in range(self._MIGRATION_INFO_MAX_BAD_ANSWERS):
      query_migrate = self.qmp.GetMigrationStatus()

      if "status" in query_migrate:
        if query_migrate["status"] in constants.HV_KVM_MIGRATION_VALID_STATUSES:
          migration_status = objects.MigrationStatus(status=
                                                     query_migrate["status"])
          if "ram" in query_migrate:
            migration_status.transferred_ram = \
                query_migrate["ram"]["transferred"]
            migration_status.total_ram = query_migrate["ram"]["total"]

            migration_status.postcopy_status = None
            migration_caps = instance.hvparams[constants.HV_KVM_MIGRATION_CAPS]
            # migration_caps is a ':' delimited string, so checking
            # if 'postcopy-ram' is a substring also covers using
            # x-postcopy-ram for QEMU 2.5
            if migration_caps and "postcopy-ram" in migration_caps:
              dirty_sync_count = query_migrate["ram"]["dirty-sync-count"]
              if (migration_status.status == constants.HV_MIGRATION_ACTIVE
                  and dirty_sync_count >= _POSTCOPY_SYNC_COUNT_THRESHOLD):
                self.qmp.StartPostcopyMigration()
                logging.info("switched live migration for instance %s to"
                             " postcopy mode", instance.name)
                # qmp.StartPostcopyMigration() seems asynchronous. Doing
                # qmp.GetMigrationStatus() right after, the ["status"] won't be
                # HV_KVM_MIGRATION_POSTCOPY_ACTIVE. This is why an extra field
                # ["postcopy_status"] is introduced
                migration_status.postcopy_status = \
                    constants.HV_KVM_MIGRATION_POSTCOPY_ACTIVE

          return migration_status
        else:
          logging.warning("KVM: unknown migration status '%s'",
                          query_migrate["status"])
      else:
        logging.warning("KVM: unknown 'query-migrate' result: %s",
                        query_migrate)

      time.sleep(self._MIGRATION_INFO_RETRY_DELAY)

    return objects.MigrationStatus(status=constants.HV_MIGRATION_FAILED)

  @_with_qmp
  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    self.qmp.SetBalloonMemory(mem)

  def GetNodeInfo(self, hvparams=None):
    """Return information about the node.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters, not used in this class

    @return: a dict as returned by L{BaseHypervisor.GetLinuxNodeInfo} plus
        the following keys:
          - hv_version: the hypervisor version in the form (major, minor,
                        revision)

    """
    result = self.GetLinuxNodeInfo()
    kvmpath = constants.KVM_PATH
    if hvparams is not None:
      kvmpath = hvparams.get(constants.HV_KVM_PATH, constants.KVM_PATH)
    _, v_major, v_min, v_rev = self._GetKVMVersion(kvmpath)
    result[constants.HV_NODEINFO_KEY_VERSION] = (v_major, v_min, v_rev)
    return result

  @classmethod
  def GetInstanceConsole(cls, instance, primary_node, node_group,
                         hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    if hvparams[constants.HV_SERIAL_CONSOLE]:
      cmd = [pathutils.KVM_CONSOLE_WRAPPER,
             constants.SOCAT_PATH, utils.ShellQuote(instance.name),
             utils.ShellQuote(cls._InstanceMonitor(instance.name)),
             "STDIO,%s" % cls._SocatUnixConsoleParams(),
             "UNIX-CONNECT:%s" % cls._InstanceSerial(instance.name)]
      ndparams = node_group.FillND(primary_node)
      return objects.InstanceConsole(instance=instance.name,
                                     kind=constants.CONS_SSH,
                                     host=primary_node.name,
                                     port=ndparams.get(constants.ND_SSH_PORT),
                                     user=constants.SSH_CONSOLE_USER,
                                     command=cmd)

    vnc_bind_address = hvparams[constants.HV_VNC_BIND_ADDRESS]
    if vnc_bind_address and instance.network_port > constants.VNC_BASE_PORT:
      display = instance.network_port - constants.VNC_BASE_PORT
      return objects.InstanceConsole(instance=instance.name,
                                     kind=constants.CONS_VNC,
                                     host=vnc_bind_address,
                                     port=instance.network_port,
                                     display=display)

    spice_bind = hvparams[constants.HV_KVM_SPICE_BIND]
    if spice_bind:
      return objects.InstanceConsole(instance=instance.name,
                                     kind=constants.CONS_SPICE,
                                     host=spice_bind,
                                     port=instance.network_port)

    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_MESSAGE,
                                   message=("No serial shell for instance %s" %
                                            instance.name))

  def Verify(self, hvparams=None):
    """Verify the hypervisor.

    Check that the required binaries exist.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be verified against, not used here

    @return: Problem description if something is wrong, C{None} otherwise

    """
    msgs = []
    kvmpath = constants.KVM_PATH
    if hvparams is not None:
      kvmpath = hvparams.get(constants.HV_KVM_PATH, constants.KVM_PATH)
    if not os.path.exists(kvmpath):
      msgs.append("The KVM binary ('%s') does not exist" % kvmpath)
    if not os.path.exists(constants.SOCAT_PATH):
      msgs.append("The socat binary ('%s') does not exist" %
                  constants.SOCAT_PATH)

    return self._FormatVerifyResults(msgs)

  @classmethod
  def CheckParameterSyntax(cls, hvparams):
    """Check the given parameters for validity.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters
    @raise errors.HypervisorError: when a parameter is not valid

    """
    super(KVMHypervisor, cls).CheckParameterSyntax(hvparams)

    check_boot_parameters(hvparams)
    check_security_model(hvparams)
    check_console_parameters(hvparams)
    check_vnc_parameters(hvparams)
    check_spice_parameters(hvparams)
    check_disk_cache_parameters(hvparams)

  @classmethod
  def ValidateParameters(cls, hvparams):
    """Check the given parameters for validity.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters
    @raise errors.HypervisorError: when a parameter is not valid

    """
    super(KVMHypervisor, cls).ValidateParameters(hvparams)

    validate_security_model(hvparams)
    validate_vnc_parameters(hvparams)

    kvm_path = hvparams[constants.HV_KVM_PATH]

    kvm_output = cls._GetKVMOutput(kvm_path, cls._KVMOPT_HELP)
    validate_spice_parameters(hvparams, kvm_output)

    kvmpath = constants.KVM_PATH
    kvm_version = cls._GetKVMVersion(kvmpath)
    validate_disk_parameters(hvparams, kvm_version)

    kvm_output = cls._GetKVMOutput(kvm_path, cls._KVMOPT_MLIST)
    validate_machine_version(hvparams, kvm_output)

  @classmethod
  def AssessParameters(cls, hvparams):
    """Check the given parameters for uncommon/suboptimal values

    This should check the passed set of parameters for suboptimal
    values.

    @type hvparams: dict
    @param hvparams: dictionary with parameter names/value

    """

    warnings = []

    cpu_type = hvparams[constants.HV_CPU_TYPE]
    if not cpu_type:
      warnings.append("cpu_type is currently unset and defaults to 'qemu64'"
                      ", please read the gnt-instance man page on the security"
                      " and performance implications of this parameter.")
    elif cpu_type in ("qemu32", "qemu64", "kvm32", "kvm64"):
      warnings.append("cpu_type is currently set to '%s'"
                      ", please read the gnt-instance man page on the security"
                      " and performance implications of this parameter." %
                      cpu_type)
    elif cpu_type == "host":
      warnings.append("cpu_type is currently set to 'host', please make"
                      " sure all your cluster nodes have the exact same"
                      " CPU type to allow live migrations.")

    vhost_net = hvparams[constants.HV_VHOST_NET]
    if not vhost_net:
      warnings.append("vhost_net should be enabled for paravirtual NICs to"
                      " improve network latency and throughput.")

    migration_bandwidth = hvparams[constants.HV_MIGRATION_BANDWIDTH]
    default_migration_bw = constants.HVC_DEFAULTS[constants.HT_KVM]\
      [constants.HV_MIGRATION_BANDWIDTH]
    if migration_bandwidth == default_migration_bw:
      warnings.append("migration_bandwidth is still set to its default value"
                      "(%s MiB/s), please consider adjusting it to a higher "
                      "value that leverages todays network speeds."
                      % default_migration_bw)

    disk_type = hvparams[constants.HV_DISK_TYPE]
    if disk_type != "paravirtual":
      warnings.append("disk_type is set to '%s' instead of 'paravirtual'"
                      ", please consider virtio-based disks for the best"
                      " performance." % disk_type)

    nic_type = hvparams[constants.HV_NIC_TYPE]
    if nic_type != "paravirtual":
      warnings.append("nic_type is set to '%s' instead of 'paravirtual'"
                      ", please consider virtio-based networking for the"
                      " best performance." % nic_type)

    vnc_bind_address = hvparams[constants.HV_VNC_BIND_ADDRESS]
    vnc_tls_enabled = hvparams[constants.HV_VNC_TLS]

    if vnc_bind_address and vnc_bind_address != "127.0.0.1" \
            and not vnc_tls_enabled:
      warnings.append("VNC is configured but without TLS, please"
                      " consider setting vnc_tls to 'true'"
                      " for additional security.")

    spice_bind_address = hvparams[constants.HV_KVM_SPICE_BIND]
    spice_tls_enabled = hvparams[constants.HV_KVM_SPICE_USE_TLS]

    if spice_bind_address and spice_bind_address != "127.0.0.1" \
            and not spice_tls_enabled:
      warnings.append("Spice is configured but without TLS, please"
                      " consider setting spice_use_tls to 'true'"
                      " for additional security.")

    machine_version = hvparams[constants.HV_KVM_MACHINE_VERSION]
    if not machine_version:
      warnings.append("machine_version is not explicitly configured so "
                      "Ganeti will autodetect the default value from "
                      "'kvm -M ?', this might produce unexpected results.")
    if machine_version == "pc":
      warnings.append("machine_version is set to the 'pc' type which "
                      "could cause problems during live migration")

    if machine_version.startswith("q35"):
      warnings.append("machine_version is set to the 'q35' type which "
                      "is currently not properly supported.")

    if machine_version in ["none", "microvm", "isapc", "x-remote"]:
      warnings.append("machine_version is set to %s which is unsupported "
                      "in Ganeti." % machine_version)

    return warnings

  @classmethod
  def PowercycleNode(cls, hvparams=None):
    """KVM powercycle, just a wrapper over Linux powercycle.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be used on this node

    """
    cls.LinuxPowercycle()
