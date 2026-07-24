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

from ganeti import constants
from ganeti.tools.cfgupgrade import CfgUpgrade


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


class TestDowngradeBootType:
  def test_strips_boot_type_and_ovmf_code(self):
    cfg = {
      "cluster": {
        "hvparams": {
          constants.HT_KVM: {
            constants.HV_KERNEL_PATH: "",
            constants.HV_BOOT_TYPE: constants.HT_BOOT_BIOS,
            constants.HV_OVMF_CODE: "/usr/share/OVMF/OVMF_CODE.fd",
          },
        },
      },
      "instances": {
        "inst1": {
          "hvparams": {
            constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI,
            constants.HV_OVMF_CODE: "/custom/OVMF_CODE.fd",
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
    # kernel_path (a pre-4.0 parameter) must survive the downgrade
    assert constants.HV_KERNEL_PATH in kvm

    inst1 = cfg["instances"]["inst1"]["hvparams"]
    assert constants.HV_BOOT_TYPE not in inst1
    assert constants.HV_OVMF_CODE not in inst1
