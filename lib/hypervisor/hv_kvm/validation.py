#
#

# Copyright (C) 2022 the Ganeti project
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


"""KVM hypervisor parameter/syntax validation helpers

"""

import re
import pwd

from ganeti import constants
from ganeti import netutils
from ganeti import errors
from ganeti import utils

#: SPICE parameters which depend on L{constants.HV_KVM_SPICE_BIND}
_SPICE_ADDITIONAL_PARAMS = frozenset([
  constants.HV_KVM_SPICE_IP_VERSION,
  constants.HV_KVM_SPICE_PASSWORD_FILE,
  constants.HV_KVM_SPICE_LOSSLESS_IMG_COMPR,
  constants.HV_KVM_SPICE_JPEG_IMG_COMPR,
  constants.HV_KVM_SPICE_ZLIB_GLZ_IMG_COMPR,
  constants.HV_KVM_SPICE_STREAMING_VIDEO_DETECTION,
  constants.HV_KVM_SPICE_USE_TLS,
  ])

_SPICE_RE = re.compile(r"^-spice\s", re.M)
_CHECK_MACHINE_VERSION_RE = [lambda x: re.compile(r"^(%s)[ ]+.*PC" % x, re.M)]
_VERSION_RE = re.compile(r"\b(\d+)\.(\d+)(\.(\d+))?\b")

# Match any pc-q35-* machine type entry in `kvm -machine ?` output.
_Q35_MACHINE_RE = re.compile(r"^pc-q35-\S+", re.M)

# Sound models officially supported on q35. Both are PCI(e)-compatible
# and pin cleanly to the static-device multifunction group. Other
# soundhw values (es1370, sb16, adlib, gus, cs4231a, pcspk, ...) are
# rejected on q35: i440fx remains available for those.
_Q35_VALID_SOUNDHW = frozenset(["", "ac97", "hda"])


def is_q35(machine_version):
  """Return True iff C{machine_version} names a q35 machine type.

  Substring check on the user-supplied C{machine_version}; mirrors how
  the rest of Ganeti treats this hvparam as a literal token (see
  L{AssessParameters}). Versioned names (C{pc-q35-X.Y}) and the bare
  C{q35} alias both match; C{pc-i440fx-X.Y} and the bare C{pc} alias
  both do not.

  @type machine_version: str
  @param machine_version: the C{machine_version} hvparam value
  @rtype: bool
  @return: whether the value names a q35 machine type

  """
  return "q35" in (machine_version or "")


def validate_q35_capability(hvparams, kvm_machine_output):
  """Validate q35 chipset prerequisites and hvparam compatibility.

  No-op when the resolved chipset is i440fx.

  Raises L{errors.HypervisorError} if:

  - no ``pc-q35-*`` machine type is available in this QEMU build, or
  - ``disk_type`` is ``ide`` (ide-hd on AHCI is suboptimal; use
    ``paravirtual`` or ``scsi`` for regular disks), or
  - ``cdrom_disk_type`` is ``paravirtual`` (virtio-blk-pci CD-ROMs are
    not bootable from SeaBIOS; use ``ide`` to land on the chipset SATA
    controller, or ``scsi-cd``), or
  - ``floppy_image_path`` is set (q35 has no ISA floppy controller), or
  - ``nic_type`` is ``ne2k_isa`` (the ISA NE2000 model does not work on
    q35; pick any of the remaining KVM NIC types), or
  - ``soundhw`` is anything other than ``""``, ``"ac97"``, or ``"hda"``
    (other models are not supported on q35; switch to an
    ``pc-i440fx-*`` machine version if you need them).

  Note: ``cdrom_disk_type=ide`` IS supported on q35 - the ``ide-cd``
  device attaches to the chipset ich9-ahci controller's ATAPI bus
  (SATA underneath); there is no legacy ICH9 IDE controller on q35.

  Returns a list of warning strings for suboptimal but accepted
  combinations (lsi SCSI controller, cirrus/default VGA).

  @rtype: list of str
  @return: warning messages; empty list on the i440fx path or a clean
      q35 configuration
  """
  machine_version = hvparams[constants.HV_KVM_MACHINE_VERSION]
  if not is_q35(machine_version):
    return []

  if not _Q35_MACHINE_RE.search(kvm_machine_output):
    raise errors.HypervisorError(
      "q35 requested but no pc-q35-* machine type available in this"
      " QEMU build")

  disk_type = hvparams.get(constants.HV_DISK_TYPE)
  if disk_type == constants.HT_DISK_IDE:
    raise errors.HypervisorError(
      "disk_type='ide' is not supported on the q35 machine type;"
      " use 'paravirtual' or 'scsi' instead")

  cdrom_disk_type = hvparams.get(constants.HV_KVM_CDROM_DISK_TYPE)
  if cdrom_disk_type == constants.HT_DISK_PARAVIRTUAL:
    raise errors.HypervisorError(
      "cdrom_disk_type='paravirtual' is not supported on the q35 machine"
      " type: virtio-blk-pci CD-ROMs are not bootable from SeaBIOS. Use"
      " 'ide' (lands on the chipset SATA controller) or 'scsi-cd'"
      " instead")

  if hvparams.get(constants.HV_KVM_FLOPPY_IMAGE_PATH):
    raise errors.HypervisorError(
      "floppy_image_path is not supported on the q35 machine type;"
      " q35 has no ISA floppy controller")

  if hvparams.get(constants.HV_NIC_TYPE) == constants.HT_NIC_NE2K_ISA:
    raise errors.HypervisorError(
      "nic_type='ne2k_isa' is not supported on the q35 machine type;"
      " pick one of the remaining KVM NIC types (e.g. 'paravirtual',"
      " 'e1000', 'rtl8139', 'ne2k_pci', ...).")

  soundhw = hvparams.get(constants.HV_SOUNDHW) or ""
  if soundhw not in _Q35_VALID_SOUNDHW:
    supported = ", ".join(f"'{m}'" for m in sorted(_Q35_VALID_SOUNDHW) if m)
    raise errors.HypervisorError(
      f"soundhw={soundhw!r} is not supported on the q35 machine type;"
      f" only {supported} are available. Switch to a pc-i440fx-* machine"
      " version if you need a different sound model.")

  warnings = []

  scsi_ctrl = hvparams.get(constants.HV_KVM_SCSI_CONTROLLER_TYPE)
  if scsi_ctrl == constants.HT_SCSI_CONTROLLER_LSI:
    warnings.append(
      "q35: scsi_controller_type='lsi' is suboptimal on q35; consider"
      " 'virtio-scsi-pci' for better performance and broader guest"
      " support.")

  vga = hvparams.get(constants.HV_VGA)
  if not vga or vga == "cirrus":
    warnings.append(
      "q35: cirrus VGA is suboptimal on q35; consider 'std', 'qxl' or"
      " 'virtio'.")

  return warnings


def check_spice_parameters(hvparams):
    spice_bind = hvparams[constants.HV_KVM_SPICE_BIND]
    spice_ip_version = hvparams[constants.HV_KVM_SPICE_IP_VERSION]
    if spice_bind:
      if spice_ip_version != constants.IFACE_NO_IP_VERSION_SPECIFIED:
        # if an IP version is specified, the spice_bind parameter must be an
        # IP of that family
        if (netutils.IP4Address.IsValid(spice_bind) and
            spice_ip_version != constants.IP4_VERSION):
          raise errors.HypervisorError("SPICE: Got an IPv4 address (%s), but"
                                       " the specified IP version is %s" %
                                       (spice_bind, spice_ip_version))

        if (netutils.IP6Address.IsValid(spice_bind) and
            spice_ip_version != constants.IP6_VERSION):
          raise errors.HypervisorError("SPICE: Got an IPv6 address (%s), but"
                                       " the specified IP version is %s" %
                                       (spice_bind, spice_ip_version))
    else:
      # All the other SPICE parameters depend on spice_bind being set. Raise an
      # error if any of them is set without it.
      for param in _SPICE_ADDITIONAL_PARAMS:
        if hvparams[param]:
          raise errors.HypervisorError("SPICE: %s requires %s to be set" %
                                       (param, constants.HV_KVM_SPICE_BIND))
    return True


def validate_spice_parameters(hvparams, kvm_help_output):
    spice_bind = hvparams[constants.HV_KVM_SPICE_BIND]
    if spice_bind:
      # only one of VNC and SPICE can be used currently.
      if hvparams[constants.HV_VNC_BIND_ADDRESS]:
        raise errors.HypervisorError("Both SPICE and VNC are configured, but"
                                     " only one of them can be used at a"
                                     " given time")

      # check that KVM supports SPICE

      if not _SPICE_RE.search(kvm_help_output):
        raise errors.HypervisorError("SPICE is configured, but it is not"
                                     " supported according to 'kvm --help'")

      # if spice_bind is not an IP address, it must be a valid interface
      bound_to_addr = (netutils.IP4Address.IsValid(spice_bind) or
                       netutils.IP6Address.IsValid(spice_bind))
      if not bound_to_addr and not netutils.IsValidInterface(spice_bind):
        raise errors.HypervisorError("SPICE: The %s parameter must be either"
                                     " a valid IP address or interface name" %
                                     constants.HV_KVM_SPICE_BIND)
    return True


def check_vnc_parameters(hvparams):
    if (hvparams[constants.HV_VNC_X509_VERIFY] and
        not hvparams[constants.HV_VNC_X509]):
      raise errors.HypervisorError("%s must be defined, if %s is" %
                                   (constants.HV_VNC_X509,
                                    constants.HV_VNC_X509_VERIFY))
    return True


def validate_vnc_parameters(hvparams):
    vnc_bind_address = hvparams[constants.HV_VNC_BIND_ADDRESS]
    if vnc_bind_address:
      bound_to_addr = (netutils.IP4Address.IsValid(vnc_bind_address) or
                       netutils.IP6Address.IsValid(vnc_bind_address))
      is_interface = netutils.IsValidInterface(vnc_bind_address)
      is_path = utils.IsNormAbsPath(vnc_bind_address)
      if not bound_to_addr and not is_interface and not is_path:
        raise errors.HypervisorError("VNC: The %s parameter must be either"
                                     " a valid IP address, an interface name,"
                                     " or an absolute path" %
                                     constants.HV_VNC_BIND_ADDRESS)
    return True


def check_security_model(hvparams):
    security_model = hvparams[constants.HV_SECURITY_MODEL]
    if security_model == constants.HT_SM_USER:
        if not hvparams[constants.HV_SECURITY_DOMAIN]:
            raise errors.HypervisorError(
                "A security domain (user to run kvm as)"
                " must be specified")
    elif (security_model == constants.HT_SM_NONE or
          security_model == constants.HT_SM_POOL):
        if hvparams[constants.HV_SECURITY_DOMAIN]:
            raise errors.HypervisorError(
                "Cannot have a security domain when the"
                " security model is 'none' or 'pool'")
    return True


def validate_security_model(hvparams):
    security_model = hvparams[constants.HV_SECURITY_MODEL]
    if security_model == constants.HT_SM_USER:
        username = hvparams[constants.HV_SECURITY_DOMAIN]
        try:
            pwd.getpwnam(username)
        except KeyError:
            raise errors.HypervisorError("Unknown security domain user %s"
                                         % username)
    return True


def check_boot_parameters(hvparams):
    boot_order = hvparams[constants.HV_BOOT_ORDER]
    if (boot_order == constants.HT_BO_CDROM and
        not hvparams[constants.HV_CDROM_IMAGE_PATH]):
      raise errors.HypervisorError("Cannot boot from cdrom without an"
                                   " ISO path")
    kernel_path = hvparams[constants.HV_KERNEL_PATH]
    if kernel_path:
      if not hvparams[constants.HV_ROOT_PATH]:
        raise errors.HypervisorError("Need a root partition for the instance,"
                                     " if a kernel is defined")
    return True


def check_console_parameters(hvparams):
    if hvparams[constants.HV_SERIAL_CONSOLE]:
      serial_speed = hvparams[constants.HV_SERIAL_SPEED]
      valid_speeds = constants.VALID_SERIAL_SPEEDS
      if not serial_speed or serial_speed not in valid_speeds:
        raise errors.HypervisorError("Invalid serial console speed, must be"
                                     " one of: %s" %
                                     utils.CommaJoin(valid_speeds))
    return True


def validate_machine_version(hvparams, kvm_machine_output):
    machine_version = hvparams[constants.HV_KVM_MACHINE_VERSION]
    if machine_version:
      for test in _CHECK_MACHINE_VERSION_RE:
        if not test(machine_version).search(kvm_machine_output):
            raise errors.HypervisorError("Unsupported machine version: %s" %
                                         machine_version)
    return True


def check_disk_cache_parameters(hvparams):
    disk_aio = hvparams[constants.HV_KVM_DISK_AIO]
    disk_cache = hvparams[constants.HV_DISK_CACHE]
    if disk_aio == constants.HT_KVM_AIO_NATIVE and \
            disk_cache != constants.HT_CACHE_NONE:
        raise errors.HypervisorError("When 'disk_aio' is set to 'native', the "
                                     "only supported value for 'disk_cache' is "
                                     "'none'.")
    return True


def validate_disk_parameters(hvparams, kvm_version):
    v_all, v_maj, v_min, v_rev = kvm_version

    disk_aio = hvparams[constants.HV_KVM_DISK_AIO]
    if disk_aio == constants.HT_KVM_AIO_IO_URING:
        if v_maj < 5:
            raise errors.HypervisorError("At least QEMU 5.0 required to use"
                                         "'disk_aio=io_uring'.")
