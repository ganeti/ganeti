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

"""Unit tests for the cfgupgrade boot_type synthesis and downgrade."""

from unittest import mock

import pytest

from ganeti import constants
from ganeti.utils import version
from ganeti.tools.cfgupgrade import CfgUpgrade, Error


def _make_upgrader(config_data):
  upgrader = CfgUpgrade.__new__(CfgUpgrade)
  upgrader.opts = mock.Mock()
  upgrader.args = []
  upgrader.errors = []
  upgrader.config_data = config_data
  return upgrader


def _cluster(kvm_hvparams):
  return {
    "cluster": {
      "ipolicy": None,
      "hvparams": {constants.HT_KVM: dict(kvm_hvparams)},
    },
  }


class TestUpgradeClusterBootType:
  def test_nonempty_kernel_path_gives_direct_kernel(self):
    cfg = _cluster({constants.HV_KERNEL_PATH: "/boot/vmlinuz"})
    up = _make_upgrader(cfg)
    up.UpgradeCluster()
    kvm = cfg["cluster"]["hvparams"][constants.HT_KVM]
    assert kvm[constants.HV_BOOT_TYPE] == constants.HT_BOOT_DIRECT_KERNEL

  def test_empty_kernel_path_gives_bios(self):
    cfg = _cluster({constants.HV_KERNEL_PATH: ""})
    up = _make_upgrader(cfg)
    up.UpgradeCluster()
    kvm = cfg["cluster"]["hvparams"][constants.HT_KVM]
    assert kvm[constants.HV_BOOT_TYPE] == constants.HT_BOOT_BIOS

  def test_existing_boot_type_is_idempotent(self):
    cfg = _cluster({constants.HV_KERNEL_PATH: "/boot/vmlinuz",
                    constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})
    up = _make_upgrader(cfg)
    up.UpgradeCluster()
    kvm = cfg["cluster"]["hvparams"][constants.HT_KVM]
    assert kvm[constants.HV_BOOT_TYPE] == constants.HT_BOOT_UEFI


def _instance(hypervisor=constants.HT_KVM, name=None, **hvparams):
  iobj = {
    "hypervisor": hypervisor,
    "hvparams": dict(hvparams),
    "nics": [],
    "disks": [],
  }
  if name is not None:
    iobj["name"] = name
  return iobj

def _config_with_instances(cluster_kvm_hvparams, instances):
  cfg = _cluster(cluster_kvm_hvparams)
  cfg["config_version"] = 0
  cfg["networks"] = {}
  cfg["instances"] = instances
  return cfg


class TestSynthesisNeverYieldsDirectKernelUefi:
  """Pre-4.0 had no OVMF support, so boot_type synthesis must only ever
  produce direct_kernel or bios."""

  VALID = (constants.HT_BOOT_DIRECT_KERNEL, constants.HT_BOOT_BIOS)

  def test_cluster_synthesis(self):
    for kernel_path in ("/boot/vmlinuz", ""):
      cfg = _cluster({constants.HV_KERNEL_PATH: kernel_path})
      up = _make_upgrader(cfg)
      up.UpgradeCluster()
      kvm = cfg["cluster"]["hvparams"][constants.HT_KVM]
      assert kvm[constants.HV_BOOT_TYPE] in self.VALID

  def test_instance_synthesis(self):
    for cluster_kernel in ("/boot/vmlinuz", ""):
      for instance_kernel in ("/boot/vmlinuz", ""):
        cfg = _config_with_instances(
          {constants.HV_KERNEL_PATH: cluster_kernel},
          {"i1": _instance(**{constants.HV_KERNEL_PATH: instance_kernel})})
        up = _make_upgrader(cfg)
        up.UpgradeInstances()
        hv = cfg["instances"]["i1"]["hvparams"]
        assert hv[constants.HV_BOOT_TYPE] in self.VALID


class TestUpgradeInstancesBootType:
  """Every pre-4.0 KVM instance is pinned from its *effective*
  kernel_path (instance override if present, else the cluster KVM
  default) - the seed model leaves nothing to inherit."""

  def test_instance_override_pins_from_override(self):
    cfg = _config_with_instances(
      {constants.HV_KERNEL_PATH: ""},
      {"i1": _instance(**{constants.HV_KERNEL_PATH: "/boot/vmlinuz"})})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    hv = cfg["instances"]["i1"]["hvparams"]
    assert hv[constants.HV_BOOT_TYPE] == constants.HT_BOOT_DIRECT_KERNEL

  def test_no_override_pins_from_cluster_kernel_path(self):
    cfg = _config_with_instances(
      {constants.HV_KERNEL_PATH: "/boot/vmlinuz"},
      {"i1": _instance()})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    hv = cfg["instances"]["i1"]["hvparams"]
    assert hv[constants.HV_BOOT_TYPE] == constants.HT_BOOT_DIRECT_KERNEL

  def test_no_override_empty_cluster_kernel_path_gives_bios(self):
    cfg = _config_with_instances(
      {constants.HV_KERNEL_PATH: ""},
      {"i1": _instance()})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    hv = cfg["instances"]["i1"]["hvparams"]
    assert hv[constants.HV_BOOT_TYPE] == constants.HT_BOOT_BIOS

  def test_explicit_empty_override_beats_cluster_default(self):
    cfg = _config_with_instances(
      {constants.HV_KERNEL_PATH: "/boot/vmlinuz"},
      {"i1": _instance(**{constants.HV_KERNEL_PATH: ""})})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    hv = cfg["instances"]["i1"]["hvparams"]
    assert hv[constants.HV_BOOT_TYPE] == constants.HT_BOOT_BIOS

  def test_existing_boot_type_is_idempotent(self):
    cfg = _config_with_instances(
      {constants.HV_KERNEL_PATH: "/boot/vmlinuz"},
      {"i1": _instance(**{constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    hv = cfg["instances"]["i1"]["hvparams"]
    assert hv[constants.HV_BOOT_TYPE] == constants.HT_BOOT_UEFI

  def test_non_kvm_instance_is_untouched(self):
    cfg = _config_with_instances(
      {constants.HV_KERNEL_PATH: "/boot/vmlinuz"},
      {"i1": _instance(hypervisor=constants.HT_XEN_PVM,
                       **{constants.HV_KERNEL_PATH: "/k"})})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    hv = cfg["instances"]["i1"]["hvparams"]
    assert constants.HV_BOOT_TYPE not in hv


class TestDowngradeBootType:
  def test_strips_boot_type_and_ovmf_code(self):
    cfg = {
      "cluster": {
        "hvparams": {
          constants.HT_KVM: {
            constants.HV_KERNEL_PATH: "",
            constants.HV_BOOT_TYPE: constants.HT_BOOT_BIOS,
            constants.HV_OVMF_CODE: "/usr/share/OVMF/OVMF_CODE.fd",
            constants.HV_OVMF_VARS: "/usr/share/OVMF/OVMF_VARS.fd",
          },
        },
      },
      "instances": {
        "inst1": {
          "hvparams": {
            constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI,
            constants.HV_OVMF_CODE: "/custom/OVMF_CODE.fd",
            constants.HV_OVMF_VARS: "/custom/OVMF_VARS.fd",
          },
        },
        "inst2": {"hvparams": {}},
      },
    }
    up = _make_upgrader(cfg)
    up.DowngradeBootType()
    kvm = cfg["cluster"]["hvparams"][constants.HT_KVM]
    assert constants.HV_BOOT_TYPE not in kvm
    assert constants.HV_OVMF_CODE not in kvm
    assert constants.HV_OVMF_VARS not in kvm
    # kernel_path (a pre-4.0 parameter) must survive the downgrade
    assert constants.HV_KERNEL_PATH in kvm

    inst1 = cfg["instances"]["inst1"]["hvparams"]
    assert constants.HV_BOOT_TYPE not in inst1
    assert constants.HV_OVMF_CODE not in inst1
    assert constants.HV_OVMF_VARS not in inst1

  def test_strips_disk_role(self):
    # Disk.role is rejected by pre-4.0 object loading (unknown slot), so a
    # downgraded configuration must not carry it any more. Children (e.g.
    # a DRBD disk's data/meta volumes) are loaded recursively and carry
    # the field as well.
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "inst1": {"hvparams": {}, "disks": ["disk-uuid-1", "disk-uuid-2"]},
      },
      "disks": {
        "disk-uuid-1": {"role": constants.DR_ROLE_DATA},
        "disk-uuid-2": {
          "dev_type": constants.DT_DRBD8,
          "role": constants.DR_ROLE_DATA,
          "children": [
            {"dev_type": constants.DT_PLAIN, "role": constants.DR_ROLE_DATA},
            {"dev_type": constants.DT_PLAIN, "role": constants.DR_ROLE_DATA},
          ],
        },
      },
    }
    up = _make_upgrader(cfg)
    up.DowngradeBootType()
    for disk in cfg["disks"].values():
      assert "role" not in disk
    for child in cfg["disks"]["disk-uuid-2"]["children"]:
      assert "role" not in child
    # instance disks hold UUIDs only; nothing to strip, but must not crash
    assert cfg["instances"]["inst1"]["disks"] == ["disk-uuid-1",
                                                  "disk-uuid-2"]

  def test_strips_disk_role_in_legacy_instance_disk_list(self):
    # Configurations predating the top-level disks dict keep disk dicts in
    # the instances' disk lists; those must be stripped as well.
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "inst1": {"hvparams": {}, "disks": [{"role":
                                             constants.DR_ROLE_DATA}]},
      },
    }
    up = _make_upgrader(cfg)
    up.DowngradeBootType()
    assert "role" not in cfg["instances"]["inst1"]["disks"][0]


class TestCheckDowngradeUefi:
  """The downgrade to 3.1 must be refused while OVMF features are in use:
  3.1 has no UEFI support, so an OVMF instance would silently fall back to
  BIOS boot and a firmware disk would lose its role (and, on re-upgrade,
  its ipolicy exemption)."""

  def _check(self, cfg):
    up = _make_upgrader(cfg)
    up.CheckDowngradeUefi()

  def test_accepts_bios_and_direct_kernel_instances(self):
    cfg = _config_with_instances(
      {constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI},
      {"i1": _instance(**{constants.HV_BOOT_TYPE:
                           constants.HT_BOOT_BIOS}),
       "i2": _instance(**{constants.HV_BOOT_TYPE:
                          constants.HT_BOOT_DIRECT_KERNEL})})
    self._check(cfg)  # must not raise

  def test_accepts_uefi_cluster_default_without_instances(self):
    # boot_type is a creation-time seed; a uefi cluster default is not
    # inherited by instances and must not block the downgrade.
    cfg = _cluster({constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})
    self._check(cfg)  # must not raise

  @pytest.mark.parametrize("boot_type", [constants.HT_BOOT_UEFI,
                                         constants.HT_BOOT_DIRECT_KERNEL_UEFI])
  def test_refuses_uefi_instances(self, boot_type):
    cfg = _config_with_instances(
      {},
      {"i1": _instance(name="vm1.example.com",
                       **{constants.HV_BOOT_TYPE: boot_type}),
       "i2": _instance(name="vm2.example.com",
                       **{constants.HV_BOOT_TYPE:
                          constants.HT_BOOT_BIOS})})
    with pytest.raises(Error, match="vm1.example.com"):
      self._check(cfg)

  def test_refusal_names_offenders_and_keeps_configuration(self):
    cfg = _config_with_instances(
      {},
      {"i1": _instance(name="vm1.example.com",
                       **{constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})})
    up = _make_upgrader(cfg)
    with pytest.raises(Error, match="boot type.*vm1.example.com"):
      up.CheckDowngradeUefi()
    # The refusal happens before any parameter is stripped, so the
    # operator can fix the instances and re-run the downgrade.
    assert (cfg["instances"]["i1"]["hvparams"][constants.HV_BOOT_TYPE] ==
            constants.HT_BOOT_UEFI)

  def test_non_kvm_instance_does_not_block(self):
    # Only KVM knows boot_type; a same-named hvparam on another
    # hypervisor is not an OVMF instance.
    cfg = _config_with_instances(
      {},
      {"i1": _instance(hypervisor=constants.HT_XEN_PVM,
                       name="vm1.example.com",
                       **{constants.HV_BOOT_TYPE:
                          constants.HT_BOOT_UEFI})})
    self._check(cfg)  # must not raise

  def test_refuses_firmware_disk_via_top_level_disks(self):
    # Current layout: instance disks reference the top-level disks dict
    # by UUID; the firmware disk (and its children) block the downgrade
    # even after the instance switched to bios boot.
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "i1": {"name": "vm1.example.com", "hvparams": {}, "disks": ["fw-1"]},
      },
      "disks": {
        "fw-1": {"uuid": "fw-1",
                 "role": constants.DR_ROLE_FIRMWARE},
      },
    }
    with pytest.raises(Error, match="vm1.example.com"):
      self._check(cfg)

  def test_refuses_firmware_disk_child(self):
    # A firmware DRBD disk's data/meta children load recursively in 3.1;
    # the role must be found on the root regardless of children roles.
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "i1": {"name": "vm1.example.com", "hvparams": {}, "disks": ["fw-1"]},
      },
      "disks": {
        "fw-1": {"uuid": "fw-1", "dev_type": constants.DT_DRBD8,
                 "role": constants.DR_ROLE_FIRMWARE,
                 "children": [{"dev_type": constants.DT_PLAIN,
                               "role": constants.DR_ROLE_DATA}]},
      },
    }
    with pytest.raises(Error, match="vm1.example.com"):
      self._check(cfg)

  def test_refuses_firmware_disk_in_legacy_instance_disk_list(self):
    # Configurations predating the top-level disks dict keep disk dicts
    # (possibly without a uuid) inline in the instance's disk list.
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "i1": {"name": "vm1.example.com", "hvparams": {},
               "disks": [{"role": constants.DR_ROLE_FIRMWARE}]},
      },
    }
    with pytest.raises(Error, match="vm1.example.com"):
      self._check(cfg)

  def test_refuses_orphan_firmware_disk(self):
    # A firmware disk detached from every instance still holds NVRAM;
    # it must not slip through the per-instance scan.
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "i1": {"name": "vm1.example.com", "hvparams": {},
               "disks": ["data-1"]},
      },
      "disks": {
        "data-1": {"uuid": "data-1", "role": constants.DR_ROLE_DATA},
        "fw-1": {"uuid": "fw-1", "role": constants.DR_ROLE_FIRMWARE},
      },
    }
    with pytest.raises(Error, match="fw-1"):
      self._check(cfg)

  def test_data_disks_do_not_block(self):
    cfg = {
      "cluster": {"hvparams": {}},
      "instances": {
        "i1": {"name": "vm1.example.com", "hvparams": {},
               "disks": ["data-1", "data-2"]},
      },
      "disks": {
        "data-1": {"uuid": "data-1", "role": constants.DR_ROLE_DATA},
        "data-2": {"uuid": "data-2", "dev_type": constants.DT_DRBD8,
                   "role": constants.DR_ROLE_DATA,
                   "children": [{"dev_type": constants.DT_PLAIN,
                                 "role": constants.DR_ROLE_DATA}]},
      },
    }
    self._check(cfg)  # must not raise


class TestDowngradeRefusesUefi:
  """_Downgrade() runs the OVMF guard before DowngradeAll() so the
  configuration stays untouched when the downgrade is refused."""

  def test_guard_runs_before_downgrade_all(self):
    cfg = _config_with_instances(
      {},
      {"i1": _instance(name="vm1.example.com",
                       **{constants.HV_BOOT_TYPE:
                          constants.HT_BOOT_UEFI})})
    cfg["version"] = version.BuildVersion(
      constants.CONFIG_MAJOR, constants.CONFIG_MINOR, 0)
    up = _make_upgrader(cfg)
    with pytest.raises(Error, match="vm1.example.com"):
      up._Downgrade(constants.CONFIG_MAJOR, constants.CONFIG_MINOR,
                    cfg["version"], 0)
    # Nothing was stripped on the way out.
    assert (cfg["instances"]["i1"]["hvparams"][constants.HV_BOOT_TYPE] ==
            constants.HT_BOOT_UEFI)

