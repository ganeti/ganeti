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

import os

import pytest

from ganeti.hypervisor.hv_kvm.kvm_runtime import KVMRuntime, \
  _upgrade_serialized_runtime
from ganeti import constants
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


class TestUpgradeBootType:
  """boot_type synthesis when upgrading old serialized runtimes."""

  def _upgrade(self, hvparams):
    runtime = [list(kvm_cmd), [], hvparams, []]
    _upgrade_serialized_runtime(runtime)
    return runtime[2]

  def test_kernel_path_set_becomes_direct_kernel(self):
    hvparams = self._upgrade({constants.HV_KERNEL_PATH: "/boot/vmlinuz"})
    assert (hvparams[constants.HV_BOOT_TYPE]
            == constants.HT_BOOT_DIRECT_KERNEL)

  def test_empty_kernel_path_becomes_bios(self):
    hvparams = self._upgrade({constants.HV_KERNEL_PATH: ""})
    assert hvparams[constants.HV_BOOT_TYPE] == constants.HT_BOOT_BIOS

  def test_missing_kernel_path_becomes_bios(self):
    hvparams = self._upgrade({})
    assert hvparams[constants.HV_BOOT_TYPE] == constants.HT_BOOT_BIOS

  def test_existing_boot_type_unchanged(self):
    hvparams = self._upgrade({
      constants.HV_KERNEL_PATH: "/boot/vmlinuz",
      constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI,
    })
    assert hvparams[constants.HV_BOOT_TYPE] == constants.HT_BOOT_UEFI
