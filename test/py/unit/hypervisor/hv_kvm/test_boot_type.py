#
#

# Copyright (C) 2026 the Ganeti project
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

"""Unit tests for boot_type / UEFI-OVMF support in the KVM hypervisor."""

from unittest import mock

import pytest

from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti.hypervisor import hv_kvm
from ganeti.hypervisor.hv_kvm import firmware
from ganeti.hypervisor.hv_kvm.validation import check_boot_parameters


# Representative OVMF template sizes (both sector multiples).
_CODE_SIZE = 1966080
_VARS_SIZE = 540672


def _run_ok(stdout=""):
  """Return a fake successful utils.RunCmd result."""
  return mock.Mock(failed=False, stdout=stdout, output="", exit_code=0)


def _run_fail(output="boom"):
  """Return a fake failed utils.RunCmd result."""
  return mock.Mock(failed=True, stdout="", output=output, exit_code=1)


def _kvm_hypervisor():
  with mock.patch("ganeti.utils.EnsureDirs"):
    return hv_kvm.KVMHypervisor()


# -----------------------------------------------------------------------------
# firmware layout module (superblock + region geometry)
# -----------------------------------------------------------------------------
class TestFirmwareLayout:
  def test_compute_layout_alignment_and_order(self):
    layout = firmware.ComputeLayout(_CODE_SIZE, _VARS_SIZE)
    code_off, code_size = layout[firmware.REGION_CODE]
    vars_off, vars_size = layout[firmware.REGION_VARS]
    # sizes are exactly the template sizes
    assert code_size == _CODE_SIZE
    assert vars_size == _VARS_SIZE
    # offsets are 1 MiB aligned and the code region comes first
    assert code_off == firmware.ALIGNMENT
    assert vars_off % firmware.ALIGNMENT == 0
    assert vars_off >= code_off + code_size

  def test_required_disk_size_fits_in_fixed_disk(self):
    layout = firmware.ComputeLayout(_CODE_SIZE, _VARS_SIZE)
    required = firmware.RequiredDiskSize(layout)
    disk_bytes = constants.OVMF_FIRMWARE_DISK_SIZE * 1024 * 1024
    assert required <= disk_bytes

  def test_superblock_roundtrip(self):
    layout = firmware.ComputeLayout(_CODE_SIZE, _VARS_SIZE)
    blob = firmware.PackSuperblock(layout)
    assert len(blob) == firmware.SECTOR_SIZE
    parsed = firmware.UnpackSuperblock(blob)
    assert dict(parsed) == dict(layout)

  def test_unpack_bad_magic_raises(self):
    with pytest.raises(errors.HypervisorError, match="magic"):
      firmware.UnpackSuperblock(b"\x00" * firmware.SECTOR_SIZE)


# -----------------------------------------------------------------------------
# deterministic, node-portable device-mapper names
# -----------------------------------------------------------------------------
class TestFirmwareDmNaming:
  def test_dm_name_is_deterministic_per_instance_and_region(self):
    name = hv_kvm.KVMHypervisor._FirmwareDmName("inst1.example.com",
                                                firmware.REGION_CODE)
    assert name == "inst1.example.com-ovmf-code"

  def test_dm_path_matches_name(self):
    path = hv_kvm.KVMHypervisor._FirmwareDmPath("inst1.example.com",
                                                firmware.REGION_VARS)
    assert path == "/dev/mapper/inst1.example.com-ovmf-vars"


# -----------------------------------------------------------------------------
# locating the firmware disk by role
# -----------------------------------------------------------------------------
class TestFindFirmwareDisk:
  def test_returns_firmware_tuple(self):
    data = objects.Disk(dev_type=constants.DT_PLAIN, size=10,
                        role=constants.DR_ROLE_DATA)
    fw = objects.Disk(dev_type=constants.DT_PLAIN, size=32,
                      role=constants.DR_ROLE_FIRMWARE)
    block_devices = [(data, "/dev/d0", None), (fw, "/dev/fw", None)]
    found = hv_kvm.KVMHypervisor._FindFirmwareDisk(block_devices)
    assert found is not None
    assert found[0] is fw
    assert found[1] == "/dev/fw"

  def test_returns_none_without_firmware(self):
    data = objects.Disk(dev_type=constants.DT_PLAIN, size=10,
                        role=constants.DR_ROLE_DATA)
    assert hv_kvm.KVMHypervisor._FindFirmwareDisk([(data, "/d", None)]) is None


# -----------------------------------------------------------------------------
# region exposure via device-mapper linear targets
# -----------------------------------------------------------------------------
class TestExposeFirmwareRegion:
  def test_code_region_table_is_readonly_and_correct(self):
    with mock.patch("ganeti.utils.RunCmd",
                    return_value=_run_ok()) as run:
      dev = hv_kvm.KVMHypervisor._ExposeFirmwareRegion(
          "inst1", firmware.REGION_CODE, "/dev/drbd0",
          firmware.ALIGNMENT, _CODE_SIZE, ro=True)
    assert dev == "/dev/mapper/inst1-ovmf-code"
    cmd = run.call_args[0][0]
    assert cmd[:3] == ["dmsetup", "create", "inst1-ovmf-code"]
    assert "--readonly" in cmd
    table = cmd[cmd.index("--table") + 1]
    # "0 <size_sectors> linear <base> <offset_sectors>"
    expected = "0 %d linear /dev/drbd0 %d" % (
        _CODE_SIZE // firmware.SECTOR_SIZE,
        firmware.ALIGNMENT // firmware.SECTOR_SIZE)
    assert table == expected

  def test_vars_region_is_writable(self):
    with mock.patch("ganeti.utils.RunCmd", return_value=_run_ok()) as run:
      hv_kvm.KVMHypervisor._ExposeFirmwareRegion(
          "inst1", firmware.REGION_VARS, "/dev/drbd0",
          2 * firmware.ALIGNMENT, _VARS_SIZE, ro=False)
    cmd = run.call_args[0][0]
    assert "--readonly" not in cmd

  def test_failure_raises(self):
    with mock.patch("ganeti.utils.RunCmd", return_value=_run_fail()):
      with pytest.raises(errors.HypervisorError):
        hv_kvm.KVMHypervisor._ExposeFirmwareRegion(
            "inst1", firmware.REGION_CODE, "/dev/drbd0",
            firmware.ALIGNMENT, _CODE_SIZE, ro=True)


# -----------------------------------------------------------------------------
# choosing the local backing for the regions
# -----------------------------------------------------------------------------
class TestFirmwareRegionBase:
  def test_block_backed_uses_link_directly(self):
    disk = objects.Disk(dev_type=constants.DT_DRBD8, size=32,
                        role=constants.DR_ROLE_FIRMWARE)
    with mock.patch("ganeti.utils.RunCmd") as run:
      base = hv_kvm.KVMHypervisor._FirmwareRegionBase(disk, "/dev/drbd0")
    assert base == "/dev/drbd0"
    run.assert_not_called()  # no loop device for block-backed templates

  def test_file_backed_attaches_loop(self):
    disk = objects.Disk(dev_type=constants.DT_FILE, size=32,
                        role=constants.DR_ROLE_FIRMWARE)
    with mock.patch("ganeti.utils.RunCmd",
                    return_value=_run_ok(stdout="/dev/loop3\n")) as run:
      base = hv_kvm.KVMHypervisor._FirmwareRegionBase(disk, "/srv/fw.img")
    assert base == "/dev/loop3"
    cmd = run.call_args[0][0]
    assert cmd == ["losetup", "-f", "--show", "/srv/fw.img"]


# -----------------------------------------------------------------------------
# teardown is idempotent and detaches file-backed loop devices
# -----------------------------------------------------------------------------
class TestCleanupFirmwareDisk:
  def test_noop_when_mappings_absent(self):
    with mock.patch("os.path.exists", return_value=False):
      with mock.patch("ganeti.utils.RunCmd") as run:
        hv_kvm.KVMHypervisor._CleanupFirmwareDisk("inst1")
    run.assert_not_called()

  def test_removes_mappings_and_detaches_loop(self):
    calls = []

    def fake_run(cmd, **_kwargs):
      calls.append(cmd)
      if cmd[:2] == ["dmsetup", "deps"]:
        return _run_ok(stdout="1 dependencies : (loop5)\n")
      return _run_ok()

    with mock.patch("os.path.exists", return_value=True):
      with mock.patch("ganeti.utils.RunCmd", side_effect=fake_run):
        hv_kvm.KVMHypervisor._CleanupFirmwareDisk("inst1")

    verbs = [c[:2] for c in calls]
    assert ["dmsetup", "remove"] in verbs
    # the loop device discovered via `dmsetup deps` is detached exactly once
    assert ["losetup", "-d"] in verbs
    detach = [c for c in calls if c[:2] == ["losetup", "-d"]]
    assert detach == [["losetup", "-d", "/dev/loop5"]]


# -----------------------------------------------------------------------------
# the firmware disk is excluded from the guest block-device path
# -----------------------------------------------------------------------------
class TestBlockDevicesOptionsSkipsFirmware:
  def _hvp(self, boot_type=constants.HT_BOOT_BIOS):
    return {
      constants.HV_BOOT_TYPE: boot_type,
      constants.HV_BOOT_ORDER: constants.HT_BO_DISK,
      constants.HV_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL,
      constants.HV_DISK_CACHE: constants.HT_CACHE_NONE,
      constants.HV_KVM_DISK_AIO: constants.HT_KVM_AIO_THREADS,
    }

  def test_firmware_disk_emits_no_device(self):
    hyp = _kvm_hypervisor()
    fw = objects.Disk(dev_type=constants.DT_PLAIN, size=32,
                      role=constants.DR_ROLE_FIRMWARE, mode=constants.DISK_RDWR)
    kvm_disks = [(fw, "/dev/mapper/inst1.disk1", None)]
    # devlist/kvmhelp only need to advertise virtio-blk-pci for the driver
    # support check; the firmware disk is skipped before that anyway.
    devlist = "name \"virtio-blk-pci\"\n"
    opts = hyp._GenerateKVMBlockDevicesOptions(self._hvp(), kvm_disks,
                                               "", devlist)
    # No -device / -drive emitted for the firmware-role disk.
    assert opts == []


# -----------------------------------------------------------------------------
# master-side boot-parameter validation (boot_type authoritative)
# -----------------------------------------------------------------------------
def _boot_hvp(**over):
  hvp = {
    constants.HV_BOOT_TYPE: constants.HT_BOOT_DIRECT_KERNEL,
    constants.HV_BOOT_ORDER: constants.HT_BO_DISK,
    constants.HV_CDROM_IMAGE_PATH: "",
    constants.HV_KERNEL_PATH: "/boot/vmlinuz",
    constants.HV_ROOT_PATH: "/dev/vda1",
  }
  hvp.update(over)
  return hvp


class TestCheckBootParameters:
  def test_direct_kernel_ok(self):
    assert check_boot_parameters(_boot_hvp()) is True

  def test_direct_kernel_without_root_raises(self):
    hvp = _boot_hvp(**{constants.HV_ROOT_PATH: ""})
    with pytest.raises(errors.HypervisorError, match="root partition"):
      check_boot_parameters(hvp)

  def test_direct_kernel_ignores_cdrom_without_iso(self):
    # boot_order is irrelevant under direct_kernel, so no error.
    hvp = _boot_hvp(**{constants.HV_BOOT_ORDER: constants.HT_BO_CDROM})
    assert check_boot_parameters(hvp) is True

  def test_bios_cdrom_without_iso_raises(self):
    hvp = _boot_hvp(**{constants.HV_BOOT_TYPE: constants.HT_BOOT_BIOS,
                       constants.HV_BOOT_ORDER: constants.HT_BO_CDROM})
    with pytest.raises(errors.HypervisorError, match="cdrom"):
      check_boot_parameters(hvp)

  def test_bios_cdrom_with_iso_ok(self):
    hvp = _boot_hvp(**{constants.HV_BOOT_TYPE: constants.HT_BOOT_BIOS,
                       constants.HV_BOOT_ORDER: constants.HT_BO_CDROM,
                       constants.HV_CDROM_IMAGE_PATH: "/x.iso"})
    assert check_boot_parameters(hvp) is True

  def test_uefi_floppy_raises(self):
    hvp = _boot_hvp(**{constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI,
                       constants.HV_BOOT_ORDER: constants.HT_BO_FLOPPY})
    with pytest.raises(errors.HypervisorError, match="UEFI"):
      check_boot_parameters(hvp)

  def test_uefi_disk_ok(self):
    hvp = _boot_hvp(**{constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI,
                       constants.HV_BOOT_ORDER: constants.HT_BO_DISK})
    assert check_boot_parameters(hvp) is True
