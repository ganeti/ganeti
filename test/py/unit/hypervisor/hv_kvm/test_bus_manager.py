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

from ganeti.hypervisor.hv_kvm.bus_manager import PCIAllocator, SCSIAllocator, \
  BusAllocatorManager


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
  def test_get_next_allocation(self):
    pci_alloc = PCIAllocator(max_slots=32, reserved_slots=12)
    scsi_alloc = SCSIAllocator(16, reserved_slots=0)
    bus_manager = BusAllocatorManager([pci_alloc, scsi_alloc])

    alloc_pci = bus_manager.get_next_allocation("nic", "paravirtual")

    assert alloc_pci.bus_type == "pci"
    assert alloc_pci.bus == PCIAllocator._PCI_BUS

    alloc_scsi = bus_manager.get_next_allocation("disk", "scsi-block")

    assert alloc_scsi.bus_type == "scsi"
    assert alloc_scsi.bus == SCSIAllocator._SCSI_BUS
