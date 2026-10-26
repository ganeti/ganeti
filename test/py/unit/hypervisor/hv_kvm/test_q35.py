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

from unittest import mock

import pytest

from ganeti import constants
from ganeti import errors
from ganeti.hypervisor import hv_kvm
from ganeti.hypervisor.hv_kvm.bus_manager import (
  PCIAllocator, PCIeNicAllocator, PCIeDiskAllocator,
  Q35_NIC_POOL_SLOTS, Q35_DISK_POOL_SLOTS, Q35_STATIC_SLOT,
)
from ganeti.hypervisor.hv_kvm.validation import (
  is_q35, validate_q35_capability,
)


# `kvm -machine ?` output from QEMU 10.2 - used by the capability check
# in validate_q35_capability to assert a pc-q35-* entry exists.
KVM_MACHINE_OUTPUT_PATH = "test/data/kvm_10.2_machine.txt"


@pytest.fixture
def kvm_machine_output() -> str:
  with open(KVM_MACHINE_OUTPUT_PATH) as fh:
    return fh.read()


# -----------------------------------------------------------------------------
# is_q35
# -----------------------------------------------------------------------------
class TestIsQ35:
  @pytest.mark.parametrize("machine_version", [
    "pc-q35-10.2", "pc-q35-6.2", "q35",
  ])
  def test_q35_names(self, machine_version):
    assert is_q35(machine_version) is True

  @pytest.mark.parametrize("machine_version", [
    "pc-i440fx-10.2", "pc", "", None, "microvm",
  ])
  def test_non_q35_names(self, machine_version):
    assert is_q35(machine_version) is False


# -----------------------------------------------------------------------------
# validate_q35_capability
# -----------------------------------------------------------------------------
def _q35_hvparams(**overrides):
  """Default hvparams dict for q35 validation tests."""
  hvp = {
    constants.HV_KVM_MACHINE_VERSION: "pc-q35-10.2",
    constants.HV_KVM_SCSI_CONTROLLER_TYPE:
      constants.HT_SCSI_CONTROLLER_VIRTIO,
    # Default cdrom_disk_type is "" (unset) in real hvparam defaults; the
    # q35 path then defaults to ide via _GenerateKVMRuntime's override.
    constants.HV_KVM_CDROM_DISK_TYPE: "",
    constants.HV_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL,
    constants.HV_KVM_FLOPPY_IMAGE_PATH: None,
    constants.HV_VGA: "std",
    constants.HV_SOUNDHW: "",
  }
  hvp.update(overrides)
  return hvp


class TestValidateQ35Capability:
  def test_i440fx_path_returns_no_warnings(self, kvm_machine_output):
    hvp = _q35_hvparams()
    hvp[constants.HV_KVM_MACHINE_VERSION] = "pc-i440fx-10.2"
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_clean_q35_emits_no_warnings(self, kvm_machine_output):
    assert validate_q35_capability(_q35_hvparams(),
                                   kvm_machine_output) == []

  def test_lsi_warning(self, kvm_machine_output):
    hvp = _q35_hvparams(
      **{constants.HV_KVM_SCSI_CONTROLLER_TYPE:
         constants.HT_SCSI_CONTROLLER_LSI})
    warnings = validate_q35_capability(hvp, kvm_machine_output)
    assert any("virtio-scsi-pci" in w for w in warnings)

  def test_ide_disk_type_raises(self, kvm_machine_output):
    hvp = _q35_hvparams(
      **{constants.HV_DISK_TYPE: constants.HT_DISK_IDE})
    with pytest.raises(errors.HypervisorError, match="disk_type='ide'"):
      validate_q35_capability(hvp, kvm_machine_output)

  def test_ide_cdrom_accepted_on_q35(self, kvm_machine_output):
    # ide-cd on q35 routes to the chipset ich9-ahci controller's ATAPI
    # bus; there is no legacy ICH9 IDE controller to worry about, so
    # cdrom_disk_type='ide' is valid (and SeaBIOS-bootable).
    hvp = _q35_hvparams(
      **{constants.HV_KVM_CDROM_DISK_TYPE: constants.HT_DISK_IDE})
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_paravirtual_cdrom_rejected_on_q35(self, kvm_machine_output):
    # virtio-blk-pci CD-ROMs are not bootable from SeaBIOS; q35 must
    # reject them explicitly.
    hvp = _q35_hvparams(
      **{constants.HV_KVM_CDROM_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL})
    with pytest.raises(errors.HypervisorError,
                       match="cdrom_disk_type='paravirtual'"):
      validate_q35_capability(hvp, kvm_machine_output)

  def test_paravirtual_cdrom_accepted_on_i440fx(self, kvm_machine_output):
    # The rejection is q35-specific; paravirtual cdroms work on i440fx.
    hvp = _q35_hvparams(**{
      constants.HV_KVM_MACHINE_VERSION: "pc-i440fx-10.2",
      constants.HV_KVM_CDROM_DISK_TYPE: constants.HT_DISK_PARAVIRTUAL,
    })
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_floppy_raises(self, kvm_machine_output):
    hvp = _q35_hvparams(
      **{constants.HV_KVM_FLOPPY_IMAGE_PATH: "/tmp/floppy.img"})
    with pytest.raises(errors.HypervisorError, match="floppy"):
      validate_q35_capability(hvp, kvm_machine_output)

  def test_ne2k_isa_nic_type_raises(self, kvm_machine_output):
    # The ISA NE2000 model is the only KVM NIC type that doesn't work
    # on q35; the rest (paravirtual, e1000, rtl8139, ne2k_pci, ...) are
    # all PCI(e)-compatible and pin onto the NIC root-port pool.
    hvp = _q35_hvparams(
      **{constants.HV_NIC_TYPE: constants.HT_NIC_NE2K_ISA})
    with pytest.raises(errors.HypervisorError, match="nic_type='ne2k_isa'"):
      validate_q35_capability(hvp, kvm_machine_output)

  def test_ne2k_isa_nic_type_accepted_on_i440fx(self, kvm_machine_output):
    # The restriction is q35-specific; i440fx still accepts the ISA model.
    hvp = _q35_hvparams(**{
      constants.HV_KVM_MACHINE_VERSION: "pc-i440fx-10.2",
      constants.HV_NIC_TYPE: constants.HT_NIC_NE2K_ISA,
    })
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_cirrus_vga_warning(self, kvm_machine_output):
    hvp = _q35_hvparams(**{constants.HV_VGA: "cirrus"})
    warnings = validate_q35_capability(hvp, kvm_machine_output)
    assert any("cirrus" in w.lower() for w in warnings)

  def test_empty_vga_warning(self, kvm_machine_output):
    hvp = _q35_hvparams(**{constants.HV_VGA: ""})
    warnings = validate_q35_capability(hvp, kvm_machine_output)
    assert any("cirrus" in w.lower() for w in warnings)

  def test_soundhw_ac97_accepted(self, kvm_machine_output):
    hvp = _q35_hvparams(**{constants.HV_SOUNDHW: "ac97"})
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_soundhw_hda_accepted(self, kvm_machine_output):
    hvp = _q35_hvparams(**{constants.HV_SOUNDHW: "hda"})
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_soundhw_empty_accepted(self, kvm_machine_output):
    # The default `""` (no sound card) must remain valid on q35.
    hvp = _q35_hvparams(**{constants.HV_SOUNDHW: ""})
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  @pytest.mark.parametrize("model",
                           ["es1370", "sb16", "adlib", "gus", "cs4231a",
                            "pcspk", "intel-hda"])
  def test_soundhw_other_models_raise(self, kvm_machine_output, model):
    # The error message must name the offending model and steer the
    # operator toward i440fx (the supported escape hatch for niche
    # sound models).
    hvp = _q35_hvparams(**{constants.HV_SOUNDHW: model})
    with pytest.raises(errors.HypervisorError,
                       match=r"soundhw=.* is not supported on the q35"):
      validate_q35_capability(hvp, kvm_machine_output)

  def test_soundhw_is_not_validated_on_i440fx(self, kvm_machine_output):
    # The restriction is q35-specific: i440fx still passes anything
    # straight through to QEMU.
    hvp = _q35_hvparams(**{
      constants.HV_KVM_MACHINE_VERSION: "pc-i440fx-10.2",
      constants.HV_SOUNDHW: "es1370",
    })
    assert validate_q35_capability(hvp, kvm_machine_output) == []

  def test_raises_when_no_q35_machine_available(self):
    # Fake QEMU build that supports neither `q35` aliases nor any
    # pc-q35-* machine type. The resolver still resolves "pc-q35-10.2"
    # to "q35" by name, so the capability check should raise.
    minimal_output = (
      "Supported machines are:\n"
      "pc-i440fx-10.2       Standard PC (i440FX + PIIX, 1996)\n"
      "pc                   Standard PC (alias of pc-i440fx-10.2)\n"
    )
    with pytest.raises(errors.HypervisorError):
      validate_q35_capability(_q35_hvparams(), minimal_output)


# -----------------------------------------------------------------------------
# _get_bus_manager chipset selection
# -----------------------------------------------------------------------------
class TestGetBusManagerByChipset:
  def test_i440fx_chipset_uses_pci_allocator(self):
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="i440fx")
    pci = bus_manager.allocators[PCIAllocator.BUS_TYPE]
    assert type(pci) is PCIAllocator  # not PCIe
    # On i440fx there is no per-pool PCIe allocator.
    assert PCIeNicAllocator.BUS_TYPE not in bus_manager.allocators
    assert PCIeDiskAllocator.BUS_TYPE not in bus_manager.allocators

  def test_q35_chipset_uses_separate_pcie_pools(self):
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="q35")
    nic_allocator = bus_manager.allocators[PCIeNicAllocator.BUS_TYPE]
    disk_allocator = bus_manager.allocators[PCIeDiskAllocator.BUS_TYPE]
    assert isinstance(nic_allocator, PCIeNicAllocator)
    assert isinstance(disk_allocator, PCIeDiskAllocator)
    # The flat PCIAllocator is not used on q35.
    assert PCIAllocator.BUS_TYPE not in bus_manager.allocators


# -----------------------------------------------------------------------------
# Cold-boot kvm_cmd: pre-allocated pool of pcie-root-ports on pcie.0,
# leaves attached as bus=rp<slot>,addr=0x0. pcie.0 is not hot-pluggable
# so the pool must exist at machine start.
# -----------------------------------------------------------------------------
class TestQ35RuntimeEmission:
  def test_first_nic_lands_on_lowest_pool_slot(self):
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="q35")
    allocation = bus_manager.get_next_allocation(
      constants.HOTPLUG_TARGET_NIC, constants.HT_NIC_PARAVIRTUAL)
    leaf_hv = hv_kvm._GenerateDeviceHVInfo(
      constants.HOTPLUG_TARGET_NIC, "nic-test",
      constants.HT_NIC_PARAVIRTUAL, allocation)
    leaf_str = hv_kvm._GenerateDeviceHVInfoStr(leaf_hv)
    # First pool slot is 0x03; the leaf attaches to rp3 with
    # acpi-index=1 on the NIC -device.
    assert leaf_str.startswith("virtio-net-pci")
    assert "bus=rp3" in leaf_str
    assert "addr=0x0" in leaf_str
    assert "acpi-index=1" in leaf_str

  def test_nic_leaf_acpi_index_tracks_pool_position(self):
    # Allocating the full NIC pool yields acpi-index 1..MAX_NICS on
    # the NIC leaves, in pool-position order.
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="q35")
    for expected in range(1, constants.MAX_NICS + 1):
      allocation = bus_manager.get_next_allocation(
        constants.HOTPLUG_TARGET_NIC, constants.HT_NIC_PARAVIRTUAL)
      assert allocation.device_params["acpi-index"] == expected
      bus_manager.commit(allocation)

  def test_disk_leaf_carries_no_acpi_index(self):
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="q35")
    allocation = bus_manager.get_next_allocation(
      constants.HOTPLUG_TARGET_DISK, constants.HT_DISK_PARAVIRTUAL)
    assert "acpi-index" not in allocation.device_params

  def test_first_disk_lands_on_lowest_disk_pool_slot(self):
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="q35")
    allocation = bus_manager.get_next_allocation(
      constants.HOTPLUG_TARGET_DISK, constants.HT_DISK_PARAVIRTUAL)
    # Disk pool starts at slot 0x0b; first paravirtual disk attaches
    # to rp11, never to the NIC pool.
    assert allocation.bus == "rp11"
    assert int(allocation.bus[2:]) in Q35_DISK_POOL_SLOTS
    assert int(allocation.bus[2:]) not in Q35_NIC_POOL_SLOTS

  def test_disk_does_not_displace_second_nic_slot(self):
    # End-to-end check of the bug this refactor fixes: with the old
    # shared pool, NIC1 -> 0x03, disk -> 0x04, NIC2 -> 0x05 (eno3).
    # With split pools NIC2 must land on 0x04 (eno2) regardless of
    # disks already allocated.
    with mock.patch("ganeti.utils.EnsureDirs"):
      hypervisor = hv_kvm.KVMHypervisor()
      bus_manager = hypervisor._get_bus_manager(chipset="q35")
    nic1 = bus_manager.get_next_allocation(
      constants.HOTPLUG_TARGET_NIC, constants.HT_NIC_PARAVIRTUAL)
    bus_manager.commit(nic1)
    disk = bus_manager.get_next_allocation(
      constants.HOTPLUG_TARGET_DISK, constants.HT_DISK_PARAVIRTUAL)
    bus_manager.commit(disk)
    nic2 = bus_manager.get_next_allocation(
      constants.HOTPLUG_TARGET_NIC, constants.HT_NIC_PARAVIRTUAL)
    assert nic1.bus == "rp3"
    assert nic2.bus == "rp4"
    assert int(disk.bus[2:]) in Q35_DISK_POOL_SLOTS


# -----------------------------------------------------------------------------
# Cold-boot fixed PCI devices on q35 are packed into a single multifunction
# slot (Q35_STATIC_SLOT) on pcie.0, with each device living at a fixed
# function number. This keeps them out of both per-device pcie-root-port
# pools and consumes only one pcie.0 slot for the entire set.
# -----------------------------------------------------------------------------
class TestQ35StaticMultifunctionGroup:
  def test_static_addr_function_zero_marks_multifunction(self):
    # Function 0 anchors the multifunction slot - QEMU only treats the
    # slot as multifunction when its function-0 device carries
    # multifunction=on.
    s = hv_kvm._Q35StaticAddr(0)
    assert ",bus=pcie.0," in s
    assert ",addr=0x2.0" in s
    assert ",multifunction=on" in s

  def test_static_addr_nonzero_function_no_multifunction(self):
    # Functions >= 1 just join the slot - no multifunction= flag.
    for fn in [1, 2, 3, 4, 5, 6]:
      s = hv_kvm._Q35StaticAddr(fn)
      assert s == f",bus=pcie.0,addr=0x2.{fn}"
      assert "multifunction" not in s

  def test_q35_static_slot_is_not_in_root_port_pool(self):
    # The kvm_cmd builder pre-allocates a pcie-root-port at every pool
    # slot. If the static-MF slot 0x02 were also in either pool, the
    # builder would emit a conflicting -device line and QEMU would
    # refuse to start.
    assert Q35_STATIC_SLOT not in Q35_NIC_POOL_SLOTS
    assert Q35_STATIC_SLOT not in Q35_DISK_POOL_SLOTS

  def test_function_constants_are_distinct_and_in_range(self):
    fns = {hv_kvm._Q35_FN_BALLOON, hv_kvm._Q35_FN_SCSI_CTRL,
           hv_kvm._Q35_FN_USB_XHCI, hv_kvm._Q35_FN_SPICE_VSERIAL,
           hv_kvm._Q35_FN_QGA_VSERIAL, hv_kvm._Q35_FN_SOUND}
    # No two devices share a function within the multifunction slot.
    assert len(fns) == 6
    # PCIe limits a slot to 8 functions (0..7); fn=6 is intentionally
    # free for future cold-boot devices.
    assert all(0 <= fn <= 7 for fn in fns)
    assert 6 not in fns
    # Balloon must be function 0 - it's the always-emitted device that
    # anchors multifunction=on.
    assert hv_kvm._Q35_FN_BALLOON == 0

  def test_cdrom_ide_q35_lands_on_ahci_channel_0(self):
    # On q35, ide-cd attaches to the chipset ich9-ahci controller; cdrom1
    # is pinned to channel 0 (bus=ide.0). This is what gives SeaBIOS a
    # deterministic boot target and avoids QEMU auto-placement surprises.
    with mock.patch("ganeti.utils.EnsureDirs"):
      hyp = hv_kvm.KVMHypervisor()
    cmd = []
    hyp._CdromOption(cmd, constants.HT_DISK_IDE,
                     "/nonexistent/iso.iso", False, "cdrom1",
                     chipset="q35", cdrom_index=0)
    device_line = cmd[3]
    assert device_line.startswith("ide-cd")
    assert "bus=ide.0" in device_line
    assert "drive=cdrom1" in device_line
    # The cdrom is NOT on pcie.0 - it's behind the AHCI controller at 0x1f.2.
    assert "bus=pcie.0" not in device_line

  def test_cdrom_ide_q35_cdrom2_lands_on_ahci_channel_1(self):
    with mock.patch("ganeti.utils.EnsureDirs"):
      hyp = hv_kvm.KVMHypervisor()
    cmd = []
    hyp._CdromOption(cmd, constants.HT_DISK_IDE,
                     "/nonexistent/iso.iso", False, "cdrom2",
                     chipset="q35", cdrom_index=1)
    device_line = cmd[3]
    assert device_line.startswith("ide-cd")
    assert "bus=ide.1" in device_line
    assert "drive=cdrom2" in device_line

  def test_cdrom_ide_i440fx_no_bus_pinned(self):
    # On i440fx the legacy PIIX3 IDE bus is auto-attached by QEMU - we
    # must NOT inject bus=ide.0 there or we'd preempt QEMU's placement.
    with mock.patch("ganeti.utils.EnsureDirs"):
      hyp = hv_kvm.KVMHypervisor()
    cmd = []
    hyp._CdromOption(cmd, constants.HT_DISK_IDE,
                     "/nonexistent/iso.iso", False, "cdrom1",
                     chipset="i440fx", cdrom_index=0)
    device_line = cmd[3]
    assert device_line.startswith("ide-cd")
    assert "bus=" not in device_line

  def test_cdrom_paravirtual_i440fx_still_works(self):
    # Paravirtual cdroms are still valid on i440fx (only q35 forbids
    # them at validation time).
    with mock.patch("ganeti.utils.EnsureDirs"):
      hyp = hv_kvm.KVMHypervisor()
    cmd = []
    hyp._CdromOption(cmd, constants.HT_DISK_PARAVIRTUAL,
                     "/nonexistent/iso.iso", False, "cdrom1",
                     chipset="i440fx")
    device_line = cmd[3]
    assert device_line.startswith("virtio-blk-pci")
    assert "bus=pcie.0" not in device_line
    assert "addr=0x" not in device_line

  def test_cdrom_scsi_not_on_pcie_even_on_q35(self):
    # SCSI CD-ROMs sit on scsi.0 (behind the SCSI controller), not pcie.0.
    with mock.patch("ganeti.utils.EnsureDirs"):
      hyp = hv_kvm.KVMHypervisor()
    cmd = []
    hyp._CdromOption(cmd, constants.HT_DISK_SCSI_CD,
                     "/nonexistent/iso.iso", False, "cdrom1",
                     chipset="q35", cdrom_index=0)
    device_line = cmd[3]
    assert device_line.startswith("scsi-cd")
    assert "bus=pcie.0" not in device_line
    assert "bus=ide" not in device_line

# -----------------------------------------------------------------------------
# Sound cards: PCI sound models (ac97/es1370/hda) must carry an explicit
# address on q35 or QEMU auto-places them onto pcie.0 slot 0x02 and collides
# with the static multifunction group (balloon, SCSI controller, ...). The
# legacy i440fx path is unaffected.
# -----------------------------------------------------------------------------
# Fragment of `qemu --help` containing the (legacy) -soundhw option; used to
# stub the kvmhelp regex when we want to exercise the pre-7.1 branch.
_KVMHELP_WITH_SOUNDHW = "-soundhw c1,c2,...\n"
# Fragment WITHOUT -soundhw, matching QEMU 7.1+.
_KVMHELP_NO_SOUNDHW = "-audio driver=...\n"


def _kvm_hypervisor():
  with mock.patch("ganeti.utils.EnsureDirs"):
    return hv_kvm.KVMHypervisor()


class TestQ35Soundhw:
  def test_ac97_on_q35_pins_to_static_slot_fn7(self):
    hyp = _kvm_hypervisor()
    cmd = []
    hyp._SoundhwOption(cmd, "ac97", spice_bind="",
                       chipset="q35", kvmhelp=_KVMHELP_NO_SOUNDHW)
    # Expect: -audiodev none,id=soundhw-dev
    #         -device AC97,id=soundhw,audiodev=soundhw-dev,
    #                 bus=pcie.0,addr=0x2.5
    assert cmd[0] == "-audiodev"
    assert cmd[1] == "none,id=soundhw-dev"
    assert cmd[2] == "-device"
    device = cmd[3]
    assert device.startswith("AC97,")
    assert "id=soundhw" in device
    assert "audiodev=soundhw-dev" in device
    assert "bus=pcie.0" in device
    assert "addr=0x2.5" in device
    # Sound card is not at fn=0, so multifunction= must NOT appear here.
    assert "multifunction" not in device

  def test_hda_on_q35_emits_controller_plus_codec(self):
    hyp = _kvm_hypervisor()
    cmd = []
    hyp._SoundhwOption(cmd, "hda", spice_bind="",
                       chipset="q35", kvmhelp=_KVMHELP_NO_SOUNDHW)
    # Expect three -* pairs: audiodev, intel-hda controller, hda-duplex codec.
    assert cmd[0] == "-audiodev"
    assert cmd[1] == "none,id=soundhw-dev"
    assert cmd[2] == "-device"
    controller = cmd[3]
    assert controller.startswith("intel-hda,")
    assert "id=soundhw" in controller
    assert "bus=pcie.0" in controller
    assert "addr=0x2.5" in controller
    assert cmd[4] == "-device"
    codec = cmd[5]
    assert codec.startswith("hda-duplex,")
    # The codec rides on the intel-hda controller's internal bus, NOT pcie.0.
    assert "bus=soundhw.0" in codec
    assert "audiodev=soundhw-dev" in codec
    assert "bus=pcie.0" not in codec

  def test_spice_backend_selected_when_spice_bind_set(self):
    hyp = _kvm_hypervisor()
    cmd = []
    hyp._SoundhwOption(cmd, "ac97", spice_bind="127.0.0.1",
                       chipset="q35", kvmhelp=_KVMHELP_NO_SOUNDHW)
    assert cmd[1] == "spice,id=soundhw-dev"

  def test_legacy_qemu_with_soundhw_flag_uses_soundhw(self):
    # On i440fx, if `qemu --help` still advertises -soundhw (pre-7.1
    # QEMU), prefer it. The q35 path never reaches this branch because
    # PCI sound on q35 always takes the pinned `-device` path above.
    hyp = _kvm_hypervisor()
    cmd = []
    hyp._SoundhwOption(cmd, "ac97", spice_bind="",
                       chipset="i440fx", kvmhelp=_KVMHELP_WITH_SOUNDHW)
    assert cmd == ["-soundhw", "ac97"]

  def test_ac97_on_i440fx_uses_audio_shortcut(self):
    # i440fx is unaffected by the q35 collision; keep using -audio.
    hyp = _kvm_hypervisor()
    cmd = []
    hyp._SoundhwOption(cmd, "ac97", spice_bind="",
                       chipset="i440fx", kvmhelp=_KVMHELP_NO_SOUNDHW)
    assert cmd == ["-audio", "driver=none,model=ac97,id=soundhw"]
