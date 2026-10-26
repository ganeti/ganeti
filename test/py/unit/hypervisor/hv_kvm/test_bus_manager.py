#
#

# Copyright (C) 2025 the Ganeti project
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

import pytest

from ganeti import constants
from ganeti.hypervisor.hv_kvm.bus_manager import PCIAllocator, \
  PCIeAllocator, PCIeNicAllocator, PCIeDiskAllocator, \
  SCSIAllocator, BusAllocatorManager, \
  Q35_NIC_POOL_SLOTS, Q35_DISK_POOL_SLOTS, Q35_STATIC_SLOT


class TestPCIAllocator:
  TEST_DEVICE_INFO = [
    {
      "bus": "pci.0",
      "addr": "0xc"
    },
    {
      "bus": "pci.0",
      "addr": "0xd"
    },
    {
      "bus": "pci.0",
      "addr": "0xf"
    }
  ]

  def test_get_next_allocation(self):
    alloc = PCIAllocator(max_slots=32, reserved_slots=12)

    a1 = alloc.get_next_allocation()  # slot 12
    a2 = alloc.get_next_allocation()  # slot 12

    assert a1.bus == "pci.0"
    assert a1.device_params["addr"] == hex(12)

    assert a1.device_params["addr"] == a2.device_params["addr"]

    alloc.reserve(a1)
    a3 = alloc.get_next_allocation()  # slot 13
    assert a3.device_params["addr"] == hex(13)

    alloc.reserve(a3)
    a4 = alloc.get_next_allocation()  # slot 14
    assert a4.device_params["addr"] == hex(14)

  def test_release(self):
    alloc = PCIAllocator(max_slots=32, reserved_slots=12)

    a1 = alloc.get_next_allocation()  # slot 12
    alloc.reserve(a1)

    a2 = alloc.get_next_allocation()  # slot 13
    alloc.reserve(a2)

    alloc.release(a1)

    a3 = alloc.get_next_allocation()  # slot 12
    assert a3.device_params["addr"] == hex(12)

  def test_reserve(self):
    alloc = PCIAllocator(max_slots=32, reserved_slots=12)

    a1 = alloc.get_next_allocation()  # slot 12
    a2 = alloc.get_next_allocation()  # slot 12

    assert a1.device_params["addr"] == a2.device_params["addr"]

    alloc.reserve(a1)

    a3 = alloc.get_next_allocation()  # slot 13
    assert a1.device_params["addr"] < a3.device_params["addr"]

  def test_initialize_from_device_info(self):
    alloc = PCIAllocator(max_slots=32, reserved_slots=12)
    a1 = alloc.get_next_allocation()  # slot 12
    assert a1.device_params["addr"] == hex(12)

    alloc.initialize_from_device_info(self.TEST_DEVICE_INFO)
    # slot 12 and 13 musst be reserved

    a2 = alloc.get_next_allocation()  # slot 14
    assert a2.device_params["addr"] == hex(14)
    alloc.reserve(a2)

    a3 = alloc.get_next_allocation()  # slot 16
    assert a3.device_params["addr"] == hex(16)


class TestQ35Pools:
  """Shape of the two disjoint q35 root-port pools."""

  def test_nic_pool_size_matches_max_nics(self):
    assert len(Q35_NIC_POOL_SLOTS) == constants.MAX_NICS

  def test_disk_pool_size_matches_max_disks(self):
    assert len(Q35_DISK_POOL_SLOTS) == constants.MAX_DISKS

  def test_pools_are_disjoint(self):
    assert not set(Q35_NIC_POOL_SLOTS) & set(Q35_DISK_POOL_SLOTS)

  def test_pools_exclude_chipset_slots(self):
    union = set(Q35_NIC_POOL_SLOTS) | set(Q35_DISK_POOL_SLOTS)
    # QEMU's q35 only auto-instantiates 0x00 (MCH) and 0x1f
    # (ICH9 LPC/SATA/SMBus); 0x01 is reserved for the integrated VGA
    # and 0x02 hosts the static-device multifunction group. None of
    # those may appear in either pool.
    for chipset_slot in (0x00, 0x01, Q35_STATIC_SLOT, 0x1f):
      assert chipset_slot not in union

  def test_nic_pool_is_contiguous_low_range(self):
    # Stable eno<N> naming relies on NIC pool slots being the lowest
    # eight contiguous pcie.0 slots (0x03..0x0a), so acpi-index 1..8
    # maps cleanly onto pool position.
    assert Q35_NIC_POOL_SLOTS == list(range(0x03, 0x0b))


class _PCIeAllocatorBehaviourMixin:
  """Behaviour shared by L{PCIeNicAllocator} and L{PCIeDiskAllocator}.

  Subclasses set C{ALLOCATOR_CLS}, C{POOL_SLOTS} and C{BUS_TYPE}.
  """

  ALLOCATOR_CLS = None
  POOL_SLOTS: list = []
  BUS_TYPE = ""

  def test_first_allocation_lands_on_lowest_pool_slot(self):
    alloc = self.ALLOCATOR_CLS()
    a = alloc.get_next_allocation()
    assert a.bus == f"rp{self.POOL_SLOTS[0]}"
    assert a.bus_type == self.BUS_TYPE
    assert a.device_params["addr"] == "0x0"

  def test_pool_capacity(self):
    # Allocate exactly the pool size; the next one must raise.
    alloc = self.ALLOCATOR_CLS()
    used_slots = []
    for _ in range(len(self.POOL_SLOTS)):
      a = alloc.get_next_allocation()
      used_slots.append(int(a.bus[2:]))
      alloc.reserve(a)
    assert len(set(used_slots)) == len(self.POOL_SLOTS)
    assert set(used_slots) == set(self.POOL_SLOTS)
    with pytest.raises(RuntimeError):
      alloc.get_next_allocation()

  def test_allocation_stays_inside_pool(self):
    alloc = self.ALLOCATOR_CLS()
    used_slots = set()
    for _ in range(len(self.POOL_SLOTS)):
      a = alloc.get_next_allocation()
      used_slots.add(int(a.bus[2:]))
      alloc.reserve(a)
    assert used_slots == set(self.POOL_SLOTS)

  def test_initialize_from_device_info_round_trips(self):
    first, second = self.POOL_SLOTS[0], self.POOL_SLOTS[1]
    runtime_infos = [
      {"bus": f"rp{first}", "addr": "0x0"},
      {"bus": f"rp{second}", "addr": "0x0"},
    ]
    alloc = self.ALLOCATOR_CLS()
    alloc.initialize_from_device_info(runtime_infos)
    a = alloc.get_next_allocation()
    assert int(a.bus[2:]) == self.POOL_SLOTS[2]

  def test_initialize_ignores_foreign_pool_slots(self):
    # A leaf on a slot that belongs to the *other* PCIe pool must be
    # ignored, so disk leaves never accidentally reserve NIC slots
    # (and vice versa) when the manager reconstructs state.
    other_pool = (Q35_DISK_POOL_SLOTS
                  if self.POOL_SLOTS == Q35_NIC_POOL_SLOTS
                  else Q35_NIC_POOL_SLOTS)
    alloc = self.ALLOCATOR_CLS()
    alloc.initialize_from_device_info([
      {"bus": f"rp{other_pool[0]}", "addr": "0x0"},
      {"bus": "pci.0", "addr": "0x5"},
      {"bus": f"rp{self.POOL_SLOTS[0]}", "addr": "0x0"},
    ])
    a = alloc.get_next_allocation()
    # Only the in-pool leaf marked rp<first> occupied.
    assert int(a.bus[2:]) == self.POOL_SLOTS[1]

  def test_reserve_release_uses_root_port_slot(self):
    alloc = self.ALLOCATOR_CLS()
    a = alloc.get_next_allocation()
    slot = int(a.bus[2:])
    alloc.reserve(a)
    b = alloc.get_next_allocation()
    assert int(b.bus[2:]) != slot
    alloc.release(a)
    c = alloc.get_next_allocation()
    assert int(c.bus[2:]) == slot


class TestPCIeNicAllocator(_PCIeAllocatorBehaviourMixin):
  ALLOCATOR_CLS = PCIeNicAllocator
  POOL_SLOTS = Q35_NIC_POOL_SLOTS
  BUS_TYPE = "pcie-nic"


class TestPCIeDiskAllocator(_PCIeAllocatorBehaviourMixin):
  ALLOCATOR_CLS = PCIeDiskAllocator
  POOL_SLOTS = Q35_DISK_POOL_SLOTS
  BUS_TYPE = "pcie-disk"


class TestPCIeAllocatorBase:
  """The base L{PCIeAllocator} still accepts an explicit pool list (used
  by subclasses and tests that want a custom pool)."""

  def test_explicit_pool_slots(self):
    alloc = PCIeAllocator(pool_slots=[10, 11, 12])
    a1 = alloc.get_next_allocation()
    alloc.reserve(a1)
    a2 = alloc.get_next_allocation()
    alloc.reserve(a2)
    a3 = alloc.get_next_allocation()
    alloc.reserve(a3)
    assert {int(x.bus[2:]) for x in (a1, a2, a3)} == {10, 11, 12}
    with pytest.raises(RuntimeError):
      alloc.get_next_allocation()


class TestSCSIAllocator:
  TEST_DEVICE_INFO = [
    {
      "bus": "scsi.0",
      "channel": 0,
      "scsi-id": 0,
      "lun": 0,
    },
    {
      "bus": "scsi.0",
      "channel": 0,
      "scsi-id": 1,
      "lun": 0,
    },
    {
      "bus": "scsi.0",
      "channel": 0,
      "scsi-id": 3,
      "lun": 0,
    }
  ]

  def test_get_next_allocation(self):
    alloc = SCSIAllocator(16, reserved_slots=0)

    a1 = alloc.get_next_allocation()  # Slot 0
    a2 = alloc.get_next_allocation()  # Slot 0

    assert a1.bus == "scsi.0"
    assert a1.device_params["scsi-id"] == 0

    assert a1.device_params["scsi-id"] == a2.device_params["scsi-id"]

    alloc.reserve(a1)
    a3 = alloc.get_next_allocation()  # Slot 1
    assert a3.device_params["scsi-id"] == 1

    alloc.reserve(a3)
    a4 = alloc.get_next_allocation()  # Slot 2
    assert a4.device_params["scsi-id"] == 2

  def test_initialize_from_device_info(self):
    alloc = SCSIAllocator(16, reserved_slots=0)
    a1 = alloc.get_next_allocation()  # Slot 0
    assert a1.device_params["scsi-id"] == 0

    alloc.initialize_from_device_info(self.TEST_DEVICE_INFO)

    a2 = alloc.get_next_allocation()  # slot 2
    assert a2.device_params["scsi-id"] == 2
    alloc.reserve(a2)

    a3 = alloc.get_next_allocation()  # slot 4
    assert a3.device_params["scsi-id"] == 4


class TestBusAllocatorManager:
  def test_i440fx_dispatch(self):
    pci_alloc = PCIAllocator(max_slots=32, reserved_slots=12)
    scsi_alloc = SCSIAllocator(16, reserved_slots=0)
    bus_manager = BusAllocatorManager([pci_alloc, scsi_alloc])

    alloc_pci = bus_manager.get_next_allocation("nic", "paravirtual")

    assert alloc_pci.bus_type == "pci"
    assert alloc_pci.bus == PCIAllocator._PCI_BUS

    alloc_scsi = bus_manager.get_next_allocation("disk", "scsi-block")

    assert alloc_scsi.bus_type == "scsi"
    assert alloc_scsi.bus == SCSIAllocator._SCSI_BUS

  def test_q35_dispatch_routes_nic_and_disk_to_separate_pools(self):
    pcie_nic = PCIeNicAllocator()
    pcie_disk = PCIeDiskAllocator()
    scsi_alloc = SCSIAllocator(16, reserved_slots=0)
    bus_manager = BusAllocatorManager([pcie_nic, pcie_disk, scsi_alloc])

    alloc_nic = bus_manager.get_next_allocation("nic", "paravirtual")
    assert alloc_nic.bus_type == "pcie-nic"
    assert int(alloc_nic.bus[2:]) in Q35_NIC_POOL_SLOTS
    assert alloc_nic.device_params["addr"] == "0x0"

    alloc_disk = bus_manager.get_next_allocation("disk", "paravirtual")
    assert alloc_disk.bus_type == "pcie-disk"
    assert int(alloc_disk.bus[2:]) in Q35_DISK_POOL_SLOTS
    assert alloc_disk.device_params["addr"] == "0x0"

    alloc_scsi = bus_manager.get_next_allocation("disk", "scsi-block")
    assert alloc_scsi.bus_type == "scsi"
    assert alloc_scsi.bus == "scsi.0"

  def test_q35_disk_never_consumes_nic_slot(self):
    # The original bug: an allocated disk would eat the next NIC's pool
    # slot (and its acpi-index). With separate pools, a disk allocation
    # must not affect the NIC pool's lowest free slot.
    pcie_nic = PCIeNicAllocator()
    pcie_disk = PCIeDiskAllocator()
    scsi_alloc = SCSIAllocator(16, reserved_slots=0)
    bus_manager = BusAllocatorManager([pcie_nic, pcie_disk, scsi_alloc])

    nic1 = bus_manager.get_next_allocation("nic", "paravirtual")
    bus_manager.commit(nic1)
    disk = bus_manager.get_next_allocation("disk", "paravirtual")
    bus_manager.commit(disk)
    nic2 = bus_manager.get_next_allocation("nic", "paravirtual")

    # NIC2 must land on the second NIC pool slot, regardless of the
    # disk that was committed in between.
    assert int(nic2.bus[2:]) == Q35_NIC_POOL_SLOTS[1]
    # Disk lands in disk pool.
    assert int(disk.bus[2:]) in Q35_DISK_POOL_SLOTS

  def test_q35_commit_release_round_trips_through_dispatcher(self):
    pcie_nic = PCIeNicAllocator()
    pcie_disk = PCIeDiskAllocator()
    bus_manager = BusAllocatorManager(
      [pcie_nic, pcie_disk, SCSIAllocator(16, reserved_slots=0)])

    nic = bus_manager.get_next_allocation("nic", "paravirtual")
    bus_manager.commit(nic)
    bus_manager.release(nic)
    # Slot returns to the NIC pool.
    nic2 = bus_manager.get_next_allocation("nic", "paravirtual")
    assert nic2.bus == nic.bus
