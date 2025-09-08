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
from typing import Dict, Set, NamedTuple, Any, List

from ganeti import constants


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
  _DISK_TARGET = constants.HOTPLUG_TARGET_DISK
  _SCSI_DEVICE_TYPES = constants.HT_SCSI_DEVICE_TYPES

  def __init__(self, allocators: List[BusAllocator]):
    self.allocators = dict()
    for allocator in allocators:
      self.allocators[allocator.bus_type] = allocator

  def get_next_allocation(self, dev_type: str, hv_dev_type: str) -> (
          BusAllocation):
    allocator: BusAllocator = self.allocators[PCIAllocator.BUS_TYPE]
    if dev_type == self._DISK_TARGET and hv_dev_type in self._SCSI_DEVICE_TYPES:
      allocator = self.allocators[SCSIAllocator.BUS_TYPE]

    return allocator.get_next_allocation()

  def commit(self, allocation: BusAllocation) -> None:
    self._get_allocator(allocation).reserve(allocation)

  def release(self, allocation: BusAllocation) -> None:
    self._get_allocator(allocation).release(allocation)

  def _get_allocator(self, allocation: BusAllocation) -> BusAllocator:
    if allocation.bus_type in self.allocators:
      return self.allocators[allocation.bus_type]
    else:
      raise RuntimeError(f"{allocation.bus_type} allocator is not available")
