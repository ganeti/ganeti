import os

import pytest

from ganeti.hypervisor.hv_kvm.kvm_runtime import KVMRuntime
from ganeti import objects
from ganeti import serializer

kvm_cmd = ['/usr/bin/kvm', 'dummy']

up_hvp = {
  'acpi': True,
  'boot_order': 'disk'
}


class TestKVMRuntime:

  @pytest.fixture
  def kvm_disks(self):
    # Get the list for disks from the json because of complexity
    with open("./test/py/unit/test_data/serialized_disks.json") as file:
      data = serializer.LoadJson(file.read())
      disks = [(objects.Disk.FromDict(sdisk), link, uri)
               for sdisk, link, uri in data]
      yield disks

  @pytest.fixture
  def kvm_nics(self):
    # Get the list for nics from the json because of complexity
    with open("./test/py/unit/test_data/serialized_nics.json") as file:
      data = serializer.LoadJson(file.read())
      nics = [objects.NIC.FromDict(nic) for nic in data]
      yield nics

  def test_properties(self, kvm_disks, kvm_nics):
    kvm_runtime = KVMRuntime([kvm_cmd, kvm_nics, up_hvp, kvm_disks])

    assert kvm_runtime.kvm_cmd == kvm_cmd
    assert kvm_runtime.kvm_nics == kvm_nics
    assert kvm_runtime.up_hvp == up_hvp
    assert kvm_runtime.kvm_disks == kvm_disks

  def test_serialize(self, kvm_disks, kvm_nics):
    kvm_runtime = KVMRuntime([kvm_cmd, kvm_nics, up_hvp, kvm_disks])
    serialized_runtime = kvm_runtime.serialize()

    # do not update the runtime fpr equality check
    deserialized_runtime = KVMRuntime.from_serialized(serialized_runtime, False)

    assert deserialized_runtime.kvm_cmd == kvm_runtime.kvm_cmd
    assert deserialized_runtime.up_hvp == kvm_runtime.up_hvp

    # check only the uuid for disks and nics
    # because the equal operator is not implemented
    for index in range(len(kvm_nics)):
      assert (deserialized_runtime.kvm_nics[index].uuid
              == kvm_runtime.kvm_nics[index].uuid)
    for index in range(len(kvm_disks)):
      assert (deserialized_runtime.kvm_disks[index][0].uuid ==
              kvm_runtime.kvm_disks[index][0].uuid)

    # assert deserialized_runtime.kvm_nics == kvm_runtime.kvm_nics
    # assert deserialized_runtime.kvm_disks == kvm_runtime.kvm_disks
