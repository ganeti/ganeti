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

"""Unit tests for the Disk.role field and boot_type config upgrades."""

from ganeti import constants
from ganeti import objects


class TestDiskRole:
  def test_role_roundtrips_through_dict(self):
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=32,
                        role=constants.DR_ROLE_FIRMWARE)
    restored = objects.Disk.FromDict(disk.ToDict())
    assert restored.role == constants.DR_ROLE_FIRMWARE

  def test_default_role_is_data(self):
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=32)
    disk.UpgradeConfig()
    assert disk.role == constants.DR_ROLE_DATA

  def test_pre_3_2_disk_without_role_upgrades_to_data(self):
    # A disk dict predating the boot_type feature carries no 'role' key.
    disk = objects.Disk.FromDict({"dev_type": constants.DT_PLAIN, "size": 1})
    disk.UpgradeConfig()
    assert disk.role == constants.DR_ROLE_DATA


def _kvm_instance(**hvparams):
  return objects.Instance(name="i1", hypervisor=constants.HT_KVM,
                          hvparams=hvparams, nics=[], disks=[], beparams={},
                          osparams={}, admin_state=constants.ADMINST_DOWN)


class TestInstanceBootTypeSynthesis:
  """Instance.UpgradeConfig synthesizes boot_type only from explicit
  kernel_path overrides (instance hvparams hold overrides only)."""

  def test_explicit_kernel_path_gives_direct_kernel(self):
    inst = _kvm_instance(**{constants.HV_KERNEL_PATH: "/boot/vmlinuz"})
    inst.UpgradeConfig()
    assert (inst.hvparams[constants.HV_BOOT_TYPE]
            == constants.HT_BOOT_DIRECT_KERNEL)

  def test_explicit_empty_kernel_path_gives_bios(self):
    inst = _kvm_instance(**{constants.HV_KERNEL_PATH: ""})
    inst.UpgradeConfig()
    assert inst.hvparams[constants.HV_BOOT_TYPE] == constants.HT_BOOT_BIOS

  def test_no_kernel_path_override_leaves_boot_type_unset(self):
    # Without an explicit override the cluster/group value must be inherited,
    # so boot_type stays absent at the instance level.
    inst = _kvm_instance()
    inst.UpgradeConfig()
    assert constants.HV_BOOT_TYPE not in inst.hvparams

  def test_non_kvm_instance_is_untouched(self):
    inst = objects.Instance(name="x", hypervisor=constants.HT_XEN_PVM,
                            hvparams={constants.HV_KERNEL_PATH: "/k"}, nics=[],
                            disks=[], beparams={}, osparams={},
                            admin_state=constants.ADMINST_DOWN)
    inst.UpgradeConfig()
    assert constants.HV_BOOT_TYPE not in inst.hvparams
