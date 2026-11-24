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

"""Unit tests for cfgupgrade's migration of stored VLANs to the strict
format.

Bare-number VLANs (e.g. "174" or "174:200") can be stored in instance
NICs, cluster-level nicparams, and nodegroup network netparams, because
those values were never validated on write. cfgupgrade rewrites them
to the canonical dot-prefixed form (".174", ".174:200"); already
canonical specs are left untouched.
"""

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


def _config(instances=None, cluster_nicparams=None, group_networks=None):
  return {
    "cluster": {
      "ipolicy": None,
      "hvparams": {constants.HT_KVM: {constants.HV_KERNEL_PATH: ""}},
      "nicparams": cluster_nicparams or {},
    },
    "networks": {},
    "nodegroups": {
      "g1": {"networks": group_networks or {}},
    },
    "instances": instances or {},
  }


class TestUpgradeVlans:
  """_UpgradeNicVlan migrates every stored VLAN location."""

  def test_instance_nic_bare_vlan(self):
    cfg = _config(instances={"i1": {
      "hypervisor": constants.HT_KVM,
      "hvparams": {},
      "nics": [{"nicparams": {constants.NIC_VLAN: "174"}}],
      "disks": [],
    }})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    assert cfg["instances"]["i1"]["nics"][0]["nicparams"][
      constants.NIC_VLAN] == ".174"

  def test_instance_nic_bare_hybrid(self):
    cfg = _config(instances={"i1": {
      "hypervisor": constants.HT_KVM,
      "hvparams": {},
      "nics": [{"nicparams": {constants.NIC_VLAN: "174:200"}}],
      "disks": [],
    }})
    up = _make_upgrader(cfg)
    up.UpgradeInstances()
    assert cfg["instances"]["i1"]["nics"][0]["nicparams"][
      constants.NIC_VLAN] == ".174:200"

  def test_cluster_nicparams_bare_vlan(self):
    cfg = _config(cluster_nicparams={
      constants.PP_DEFAULT: {constants.NIC_VLAN: "174"},
    })
    up = _make_upgrader(cfg)
    up.UpgradeCluster()
    assert cfg["cluster"]["nicparams"][constants.PP_DEFAULT][
      constants.NIC_VLAN] == ".174"

  def test_group_network_bare_vlan(self):
    cfg = _config(group_networks={
      "n1": {constants.NIC_VLAN: "174:200"},
    })
    up = _make_upgrader(cfg)
    up.UpgradeGroups()
    assert cfg["nodegroups"]["g1"]["networks"]["n1"][
      constants.NIC_VLAN] == ".174:200"

  def test_canonical_vlans_untouched(self):
    for vlan in (".174", ":174", ".174:200", ":174:200"):
      cfg = _config(instances={"i1": {
        "hypervisor": constants.HT_KVM,
        "hvparams": {},
        "nics": [{"nicparams": {constants.NIC_VLAN: vlan}}],
        "disks": [],
      }})
      up = _make_upgrader(cfg)
      up.UpgradeInstances()
      assert cfg["instances"]["i1"]["nics"][0]["nicparams"][
        constants.NIC_VLAN] == vlan

  def test_missing_or_empty_vlan_untouched(self):
    for nic in ({"nicparams": {}}, {}, {"nicparams": {"vlan": ""}}):
      cfg = _config(instances={"i1": {
        "hypervisor": constants.HT_KVM,
        "hvparams": {},
        "nics": [dict(nic)],
        "disks": [],
      }})
      up = _make_upgrader(cfg)
      up.UpgradeInstances()
      assert cfg["instances"]["i1"]["nics"][0] == nic
