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

from abc import ABC, abstractmethod
from dataclasses import field
from typing import Dict, Set, NamedTuple, Any, List, Optional

from ganeti import constants


# pcie.0 slot for the q35 static-device multifunction group; must be
# excluded from the root-port pool so PCIeAllocator never assigns it.
Q35_STATIC_SLOT = 0x02


# pcie.0 slots pre-allocated as empty pcie-root-ports on q35, split into
# two disjoint pools so disk allocations cannot consume NIC slots (and
# the per-slot acpi-index that drives stable eno<N> names).
# QEMU's q35 machine only auto-instantiates slot 0x00 (MCH) and slot
# 0x1f (ICH9 LPC/SATA/SMBus); slot 0x01 is reserved for the integrated
# VGA and slot 0x02 hosts our static-device multifunction group, so the
# pools occupy the contiguous range 0x03..0x1a.
# Sizes match MAX_NICS (8) and MAX_DISKS (16) respectively.
Q35_NIC_POOL_SLOTS: List[int] = list(range(0x03, 0x0b))
Q35_DISK_POOL_SLOTS: List[int] = list(range(0x0b, 0x1b))


class BusAllocation(NamedTuple):
  bus: str
  bus_type: str
  device_params: Dict[str, Any] = field(default_factory=dict)

  def to_kvm_info(self) -> Dict[str, Any]:
    # bus_type is not needed for KVM Info
    return {
      "bus": self.bus,
      **self.device_params
    }


class BusAllocator(ABC):
  """
  Abstract interface for bus-type-specific allocators.
  """

  @property
  @abstractmethod
  def bus_type(self) -> str:
    pass

  @abstractmethod
  def initialize_from_device_info(self, device_infos: List[Dict]):
    """
    Initialize the allocator using a list of kvm device information.
    """
    pass

  @abstractmethod
  def get_next_allocation(self) -> BusAllocation:
    """
    Return next available bus slot address for device.
    """
    pass

  @abstractmethod
  def release(self, allocation: BusAllocation) -> None:
    """
    Releases an allocation (e.g. after HotDel).
    """
    pass

  @abstractmethod
  def reserve(self, allocation: BusAllocation) -> None:
    """
    Mark an allocation as reserved.
    """
    pass


class PCIAllocator(BusAllocator):
  _PCI_BUS = "pci.0"
  BUS_TYPE = "pci"

  def __init__(self, max_slots: int, reserved_slots: int):
    """
    @param max_slots: total number of slots on the bus
    @param reserved_slots: slots [0, reserved_slots) are skipped
    """
    self._max_slots = max_slots
    self._reserved_slots = reserved_slots
    self._occupied_slots: Set[int] = set()

  @property
  def bus_type(self) -> str:
    return self.BUS_TYPE

  def get_next_allocation(self) -> BusAllocation:
    slot = self._find_free_slot()
    return BusAllocation(
      bus=self._PCI_BUS,
      bus_type=self.bus_type,
      device_params={
        "addr": hex(slot),
      }
    )

  def release(self, allocation: BusAllocation) -> None:
    slot = allocation.device_params["addr"]
    self._occupied_slots.remove(int(slot, 16))

  def reserve(self, allocation: BusAllocation) -> None:
    slot = allocation.device_params["addr"]
    # mark slot as occupied
    self._occupied_slots.add(int(slot, 16))

  def _find_free_slot(self):
    for slot in range(self._reserved_slots, self._max_slots):
      if slot not in self._occupied_slots:
        return slot
    raise RuntimeError("No free slots available")

  def initialize_from_device_info(self, device_infos: List[Dict]):
    for device_info in device_infos:
      if "bus" in device_info and device_info["bus"] == self._PCI_BUS:
        slot = device_info["addr"]
        slot = int(slot, 16)
        self._occupied_slots.add(slot)


class PCIeAllocator(BusAllocator):
  """Base allocator for a q35 pre-allocated pcie-root-port pool.

  Tracks which pool slots are occupied. Leaf devices attach as
  C{bus=rp<slot>,addr=0x0}. Subclasses set L{POOL_SLOTS} and L{BUS_TYPE}
  to define a disjoint slot range; the L{BusAllocatorManager} dispatches
  to the right subclass based on device kind so disk allocations cannot
  consume NIC slots (and the per-slot acpi-index that drives stable
  C{eno<N>} names).
  """

  BUS_TYPE = "pcie"
  POOL_SLOTS: List[int] = []

  def __init__(self, pool_slots: Optional[List[int]] = None):
    """
    @param pool_slots: pcie.0 slots pre-allocated as root-ports. Defaults
        to the subclass's L{POOL_SLOTS}.
    """
    if pool_slots is None:
      pool_slots = list(self.POOL_SLOTS)
    self._pool_slots: List[int] = list(pool_slots)
    self._pool_set: Set[int] = set(pool_slots)
    self._occupied_slots: Set[int] = set()

  @property
  def bus_type(self) -> str:
    return self.BUS_TYPE

  def get_next_allocation(self) -> BusAllocation:
    for slot in self._pool_slots:
      if slot not in self._occupied_slots:
        return BusAllocation(
          bus=f"rp{slot}",
          bus_type=self.bus_type,
          device_params=self._device_params_for_slot(slot),
        )
    raise RuntimeError(
      f"No free pcie-root-port slots available ({self.BUS_TYPE} pool"
      f" exhausted: {len(self._occupied_slots)} in use)")

  def _device_params_for_slot(self, slot: int) -> Dict[str, Any]:
    """Per-slot device params for the leaf attached to this root-port."""
    return {"addr": "0x0"}

  def reserve(self, allocation: BusAllocation) -> None:
    # The pcie.0 slot number is encoded in the bus name ("rp<slot>").
    slot = self._slot_from_leaf(allocation)
    self._occupied_slots.add(slot)

  def release(self, allocation: BusAllocation) -> None:
    slot = self._slot_from_leaf(allocation)
    self._occupied_slots.discard(slot)

  @staticmethod
  def _slot_from_leaf(allocation: BusAllocation) -> int:
    bus = allocation.bus
    if not (isinstance(bus, str) and bus.startswith("rp")):
      raise RuntimeError(
        f"PCIeAllocator: unexpected bus '{bus}' in allocation")
    return int(bus[2:])

  def initialize_from_device_info(self, device_infos: List[Dict]):
    for device_info in device_infos:
      bus = device_info.get("bus")
      if isinstance(bus, str) and bus.startswith("rp"):
        try:
          slot = int(bus[2:])
        except ValueError:
          continue
        if slot in self._pool_set:
          self._occupied_slots.add(slot)


class PCIeNicAllocator(PCIeAllocator):
  """q35 root-port allocator restricted to the NIC pool.

  Each NIC leaf carries C{acpi-index=N}, where N is the slot's 1-based
  position in L{POOL_SLOTS}; the index drives stable C{eno<N>} naming
  in the guest.
  """

  BUS_TYPE = "pcie-nic"
  POOL_SLOTS = list(Q35_NIC_POOL_SLOTS)

  def _device_params_for_slot(self, slot: int) -> Dict[str, Any]:
    params = super()._device_params_for_slot(slot)
    # Pool position is fixed per slot, so a NIC hot-added into a slot
    # freed by an earlier hot-remove inherits the same eno<N> name.
    params["acpi-index"] = self._pool_slots.index(slot) + 1
    return params


class PCIeDiskAllocator(PCIeAllocator):
  """q35 root-port allocator restricted to the disk pool.

  Disk-pool root-ports carry no C{acpi-index}; the slot a disk lands on
  does not influence guest naming.
  """

  BUS_TYPE = "pcie-disk"
  POOL_SLOTS = list(Q35_DISK_POOL_SLOTS)


class SCSIAllocator(PCIAllocator):
  _SCSI_BUS = "scsi.0"
  BUS_TYPE = "scsi"

  @property
  def bus_type(self) -> str:
    return self.BUS_TYPE

  def get_next_allocation(self) -> BusAllocation:
    slot = self._find_free_slot()
    return BusAllocation(
      bus=self._SCSI_BUS,
      bus_type=self.bus_type,
      device_params={
        "channel": 0,
        "scsi-id": slot,
        "lun": 0,
      }
    )

  def reserve(self, allocation: BusAllocation) -> None:
    slot = allocation.device_params["scsi-id"]
    # mark slot as occupied
    self._occupied_slots.add(slot)

  def initialize_from_device_info(self, device_infos: List[Dict]):
    for device_info in device_infos:
      if "bus" in device_info and device_info["bus"] == self._SCSI_BUS:
        slot = device_info["scsi-id"]
        self._occupied_slots.add(slot)


class BusAllocatorManager:
  _NIC_TARGET = constants.HOTPLUG_TARGET_NIC
  _DISK_TARGET = constants.HOTPLUG_TARGET_DISK
  _SCSI_DEVICE_TYPES = constants.HT_SCSI_DEVICE_TYPES

  def __init__(self, allocators: List[BusAllocator]):
    self.allocators = dict()
    for allocator in allocators:
      self.allocators[allocator.bus_type] = allocator

  def get_next_allocation(self, dev_type: str,
                          hv_dev_type: str) -> BusAllocation:
    # SCSI disks have their own bus regardless of chipset.
    if dev_type == self._DISK_TARGET and hv_dev_type in self._SCSI_DEVICE_TYPES:
      return self.allocators[SCSIAllocator.BUS_TYPE].get_next_allocation()
    # q35: route NIC and paravirtual disk to dedicated pools so disks
    # can never consume a NIC's acpi-indexed slot.
    if (dev_type == self._NIC_TARGET
        and PCIeNicAllocator.BUS_TYPE in self.allocators):
      return self.allocators[PCIeNicAllocator.BUS_TYPE].get_next_allocation()
    if (dev_type == self._DISK_TARGET
        and PCIeDiskAllocator.BUS_TYPE in self.allocators):
      return self.allocators[PCIeDiskAllocator.BUS_TYPE].get_next_allocation()
    # i440fx fallback: flat pci.0 bus shared by NICs and paravirtual disks.
    return self.allocators[PCIAllocator.BUS_TYPE].get_next_allocation()

  def commit(self, allocation: BusAllocation) -> None:
    self._get_allocator(allocation).reserve(allocation)

  def release(self, allocation: BusAllocation) -> None:
    self._get_allocator(allocation).release(allocation)

  def _get_allocator(self, allocation: BusAllocation) -> BusAllocator:
    if allocation.bus_type in self.allocators:
      return self.allocators[allocation.bus_type]
    else:
      raise RuntimeError(f"{allocation.bus_type} allocator is not available")
