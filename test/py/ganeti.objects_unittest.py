#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008, 2010, 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.


"""Script for unittesting the objects module"""


import unittest

from ganeti import constants
from ganeti import objects
from ganeti import errors

import testutils


class SimpleObject(objects.ConfigObject):
  __slots__ = ["a", "b"]


class TestDictState(unittest.TestCase):
  """Simple dict tansformation tests"""

  def testSimpleObjectToDict(self):
    o1 = SimpleObject(a="1")
    self.assertEquals(o1.ToDict(), {"a": "1"})
    self.assertEquals(o1.__getstate__(), {"a": "1"})
    self.assertEquals(o1.__getstate__(), o1.ToDict())
    o1.a = 2
    o1.b = 5
    self.assertEquals(o1.ToDict(), {"a": 2, "b": 5})
    o2 = SimpleObject.FromDict(o1.ToDict())
    self.assertEquals(o1.ToDict(), {"a": 2, "b": 5})


class TestClusterObject(unittest.TestCase):
  """Tests done on a L{objects.Cluster}"""

  def setUp(self):
    hvparams = {
      constants.HT_FAKE: {
        "foo": "bar",
        "bar": "foo",
        "foobar": "barfoo",
        },
      }
    os_hvp = {
      "lenny-image": {
        constants.HT_FAKE: {
          "foo": "baz",
          "foobar": "foobar",
          "blah": "blibb",
          "blubb": "blah",
          },
        constants.HT_XEN_PVM: {
          "root_path": "/dev/sda5",
          "foo": "foobar",
          },
        },
      "ubuntu-hardy": {
        },
      }
    ndparams = {
        constants.ND_OOB_PROGRAM: "/bin/cluster-oob",
        constants.ND_SPINDLE_COUNT: 1,
        constants.ND_EXCLUSIVE_STORAGE: False,
        }

    self.fake_cl = objects.Cluster(hvparams=hvparams, os_hvp=os_hvp,
                                   ndparams=ndparams)
    self.fake_cl.UpgradeConfig()

  def testGetHVDefaults(self):
    cl = self.fake_cl
    self.failUnlessEqual(cl.GetHVDefaults(constants.HT_FAKE),
                         cl.hvparams[constants.HT_FAKE])
    self.failUnlessEqual(cl.GetHVDefaults(None), {})
    self.failUnlessEqual(cl.GetHVDefaults(constants.HT_XEN_PVM,
                                          os_name="lenny-image"),
                         cl.os_hvp["lenny-image"][constants.HT_XEN_PVM])


  def testFillHvFullMerge(self):
    inst_hvparams = {
      "blah": "blubb",
      }

    fake_dict = {
      "foo": "baz",
      "bar": "foo",
      "foobar": "foobar",
      "blah": "blubb",
      "blubb": "blah",
      }
    fake_inst = objects.Instance(name="foobar",
                                 os="lenny-image",
                                 hypervisor=constants.HT_FAKE,
                                 hvparams=inst_hvparams)
    self.assertEqual(fake_dict, self.fake_cl.FillHV(fake_inst))

  def testFillHvGlobalParams(self):
    fake_inst = objects.Instance(name="foobar",
                                 os="ubuntu-hardy",
                                 hypervisor=constants.HT_FAKE,
                                 hvparams={})
    self.assertEqual(self.fake_cl.hvparams[constants.HT_FAKE],
                     self.fake_cl.FillHV(fake_inst))

  def testFillHvInstParams(self):
    inst_hvparams = {
      "blah": "blubb",
      }
    fake_inst = objects.Instance(name="foobar",
                                 os="ubuntu-hardy",
                                 hypervisor=constants.HT_XEN_PVM,
                                 hvparams=inst_hvparams)
    self.assertEqual(inst_hvparams, self.fake_cl.FillHV(fake_inst))

  def testFillHvEmptyParams(self):
    fake_inst = objects.Instance(name="foobar",
                                 os="ubuntu-hardy",
                                 hypervisor=constants.HT_XEN_PVM,
                                 hvparams={})
    self.assertEqual({}, self.fake_cl.FillHV(fake_inst))

  def testFillHvPartialParams(self):
    os = "lenny-image"
    fake_inst = objects.Instance(name="foobar",
                                 os=os,
                                 hypervisor=constants.HT_XEN_PVM,
                                 hvparams={})
    self.assertEqual(self.fake_cl.os_hvp[os][constants.HT_XEN_PVM],
                     self.fake_cl.FillHV(fake_inst))

  def testFillNdParamsCluster(self):
    fake_node = objects.Node(name="test",
                             ndparams={},
                             group="testgroup")
    fake_group = objects.NodeGroup(name="testgroup",
                                   ndparams={})
    self.assertEqual(self.fake_cl.ndparams,
                     self.fake_cl.FillND(fake_node, fake_group))

  def testFillNdParamsNodeGroup(self):
    fake_node = objects.Node(name="test",
                             ndparams={},
                             group="testgroup")
    group_ndparams = {
        constants.ND_OOB_PROGRAM: "/bin/group-oob",
        constants.ND_SPINDLE_COUNT: 10,
        constants.ND_EXCLUSIVE_STORAGE: True,
        }
    fake_group = objects.NodeGroup(name="testgroup",
                                   ndparams=group_ndparams)
    self.assertEqual(group_ndparams,
                     self.fake_cl.FillND(fake_node, fake_group))

  def testFillNdParamsNode(self):
    node_ndparams = {
        constants.ND_OOB_PROGRAM: "/bin/node-oob",
        constants.ND_SPINDLE_COUNT: 2,
        constants.ND_EXCLUSIVE_STORAGE: True,
        }
    fake_node = objects.Node(name="test",
                             ndparams=node_ndparams,
                             group="testgroup")
    fake_group = objects.NodeGroup(name="testgroup",
                                   ndparams={})
    self.assertEqual(node_ndparams,
                     self.fake_cl.FillND(fake_node, fake_group))

  def testFillNdParamsAll(self):
    node_ndparams = {
        constants.ND_OOB_PROGRAM: "/bin/node-oob",
        constants.ND_SPINDLE_COUNT: 5,
        constants.ND_EXCLUSIVE_STORAGE: True,
        }
    fake_node = objects.Node(name="test",
                             ndparams=node_ndparams,
                             group="testgroup")
    group_ndparams = {
        constants.ND_OOB_PROGRAM: "/bin/group-oob",
        constants.ND_SPINDLE_COUNT: 4,
        }
    fake_group = objects.NodeGroup(name="testgroup",
                                   ndparams=group_ndparams)
    self.assertEqual(node_ndparams,
                     self.fake_cl.FillND(fake_node, fake_group))

  def testPrimaryHypervisor(self):
    assert self.fake_cl.enabled_hypervisors is None
    self.fake_cl.enabled_hypervisors = [constants.HT_XEN_HVM]
    self.assertEqual(self.fake_cl.primary_hypervisor, constants.HT_XEN_HVM)

    self.fake_cl.enabled_hypervisors = [constants.HT_XEN_PVM, constants.HT_KVM]
    self.assertEqual(self.fake_cl.primary_hypervisor, constants.HT_XEN_PVM)

    self.fake_cl.enabled_hypervisors = sorted(constants.HYPER_TYPES)
    self.assertEqual(self.fake_cl.primary_hypervisor, constants.HT_CHROOT)

  def testUpgradeConfig(self):
    # FIXME: This test is incomplete
    cluster = objects.Cluster()
    cluster.UpgradeConfig()
    cluster = objects.Cluster(ipolicy={"unknown_key": None})
    self.assertRaises(errors.ConfigurationError, cluster.UpgradeConfig)


class TestOS(unittest.TestCase):
  ALL_DATA = [
    "debootstrap",
    "debootstrap+default",
    "debootstrap++default",
    ]

  def testSplitNameVariant(self):
    for name in self.ALL_DATA:
      self.assertEqual(len(objects.OS.SplitNameVariant(name)), 2)

  def testVariant(self):
    self.assertEqual(objects.OS.GetVariant("debootstrap"), "")
    self.assertEqual(objects.OS.GetVariant("debootstrap+default"), "default")


class TestInstance(unittest.TestCase):
  def _GenericCheck(self, inst):
    for i in [inst.all_nodes, inst.secondary_nodes]:
      self.assertTrue(isinstance(inst.all_nodes, (list, tuple)),
                      msg="Data type doesn't guarantee order")

    self.assertTrue(inst.primary_node not in inst.secondary_nodes)
    self.assertEqual(inst.all_nodes[0], inst.primary_node,
                     msg="Primary node not first node in list")

  def testNodesNoDisks(self):
    inst = objects.Instance(name="fakeinst.example.com",
      primary_node="pnode.example.com",
      disks=[
        ])

    self._GenericCheck(inst)
    self.assertEqual(len(inst.secondary_nodes), 0)
    self.assertEqual(set(inst.all_nodes), set([inst.primary_node]))
    self.assertEqual(inst.MapLVsByNode(), {
      inst.primary_node: [],
      })

  def testNodesPlainDisks(self):
    inst = objects.Instance(name="fakeinstplain.example.com",
      primary_node="node3.example.com",
      disks=[
        objects.Disk(dev_type=constants.LD_LV, size=128,
                     logical_id=("myxenvg", "disk25494")),
        objects.Disk(dev_type=constants.LD_LV, size=512,
                     logical_id=("myxenvg", "disk29071")),
        ])

    self._GenericCheck(inst)
    self.assertEqual(len(inst.secondary_nodes), 0)
    self.assertEqual(set(inst.all_nodes), set([inst.primary_node]))
    self.assertEqual(inst.MapLVsByNode(), {
      inst.primary_node: ["myxenvg/disk25494", "myxenvg/disk29071"],
      })

  def testNodesDrbdDisks(self):
    inst = objects.Instance(name="fakeinstdrbd.example.com",
      primary_node="node10.example.com",
      disks=[
        objects.Disk(dev_type=constants.LD_DRBD8, size=786432,
          logical_id=("node10.example.com", "node15.example.com",
                      12300, 0, 0, "secret"),
          children=[
            objects.Disk(dev_type=constants.LD_LV, size=786432,
                         logical_id=("myxenvg", "disk0")),
            objects.Disk(dev_type=constants.LD_LV, size=128,
                         logical_id=("myxenvg", "meta0"))
          ],
          iv_name="disk/0")
        ])

    self._GenericCheck(inst)
    self.assertEqual(set(inst.secondary_nodes), set(["node15.example.com"]))
    self.assertEqual(set(inst.all_nodes),
                     set([inst.primary_node, "node15.example.com"]))
    self.assertEqual(inst.MapLVsByNode(), {
      inst.primary_node: ["myxenvg/disk0", "myxenvg/meta0"],
      "node15.example.com": ["myxenvg/disk0", "myxenvg/meta0"],
      })

    self.assertEqual(inst.FindDisk(0), inst.disks[0])
    self.assertRaises(errors.OpPrereqError, inst.FindDisk, "hello")
    self.assertRaises(errors.OpPrereqError, inst.FindDisk, 100)
    self.assertRaises(errors.OpPrereqError, inst.FindDisk, 1)


class TestNode(unittest.TestCase):
  def testEmpty(self):
    self.assertEqual(objects.Node().ToDict(), {})
    self.assertTrue(isinstance(objects.Node.FromDict({}), objects.Node))

  def testHvState(self):
    node = objects.Node(name="node18157.example.com", hv_state={
      constants.HT_XEN_HVM: objects.NodeHvState(cpu_total=64),
      constants.HT_KVM: objects.NodeHvState(cpu_node=1),
      })

    node2 = objects.Node.FromDict(node.ToDict())

    # Make sure nothing can reference it anymore
    del node

    self.assertEqual(node2.name, "node18157.example.com")
    self.assertEqual(frozenset(node2.hv_state), frozenset([
      constants.HT_XEN_HVM,
      constants.HT_KVM,
      ]))
    self.assertEqual(node2.hv_state[constants.HT_KVM].cpu_node, 1)
    self.assertEqual(node2.hv_state[constants.HT_XEN_HVM].cpu_total, 64)

  def testDiskState(self):
    node = objects.Node(name="node32087.example.com", disk_state={
      constants.LD_LV: {
        "lv32352": objects.NodeDiskState(total=128),
        "lv2082": objects.NodeDiskState(total=512),
        },
      })

    node2 = objects.Node.FromDict(node.ToDict())

    # Make sure nothing can reference it anymore
    del node

    self.assertEqual(node2.name, "node32087.example.com")
    self.assertEqual(frozenset(node2.disk_state), frozenset([
      constants.LD_LV,
      ]))
    self.assertEqual(frozenset(node2.disk_state[constants.LD_LV]), frozenset([
      "lv32352",
      "lv2082",
      ]))
    self.assertEqual(node2.disk_state[constants.LD_LV]["lv2082"].total, 512)
    self.assertEqual(node2.disk_state[constants.LD_LV]["lv32352"].total, 128)

  def testFilterEsNdp(self):
    node1 = objects.Node(name="node11673.example.com", ndparams={
      constants.ND_EXCLUSIVE_STORAGE: True,
      })
    node2 = objects.Node(name="node11674.example.com", ndparams={
      constants.ND_SPINDLE_COUNT: 3,
      constants.ND_EXCLUSIVE_STORAGE: False,
      })
    self.assertTrue(constants.ND_EXCLUSIVE_STORAGE in node1.ndparams)
    node1.UpgradeConfig()
    self.assertFalse(constants.ND_EXCLUSIVE_STORAGE in node1.ndparams)
    self.assertTrue(constants.ND_EXCLUSIVE_STORAGE in node2.ndparams)
    self.assertTrue(constants.ND_SPINDLE_COUNT in node2.ndparams)
    node2.UpgradeConfig()
    self.assertFalse(constants.ND_EXCLUSIVE_STORAGE in node2.ndparams)
    self.assertTrue(constants.ND_SPINDLE_COUNT in node2.ndparams)


class TestInstancePolicy(unittest.TestCase):
  def setUp(self):
    # Policies are big, and we want to see the difference in case of an error
    self.maxDiff = None

  def _AssertIPolicyIsFull(self, policy):
    self.assertEqual(frozenset(policy.keys()), constants.IPOLICY_ALL_KEYS)
    for key in constants.IPOLICY_ISPECS:
      spec = policy[key]
      self.assertEqual(frozenset(spec.keys()), constants.ISPECS_PARAMETERS)

  def testDefaultIPolicy(self):
    objects.InstancePolicy.CheckParameterSyntax(constants.IPOLICY_DEFAULTS,
                                                True)
    self._AssertIPolicyIsFull(constants.IPOLICY_DEFAULTS)

  def testFillIPolicyEmpty(self):
    policy = objects.FillIPolicy(constants.IPOLICY_DEFAULTS, {})
    objects.InstancePolicy.CheckParameterSyntax(policy, True)
    self.assertEqual(policy, constants.IPOLICY_DEFAULTS)

  def _AssertISpecsMerged(self, default_spec, diff_spec, merged_spec):
    for (param, value) in merged_spec.items():
      if param in diff_spec:
        self.assertEqual(value, diff_spec[param])
      else:
        self.assertEqual(value, default_spec[param])

  def _AssertIPolicyMerged(self, default_pol, diff_pol, merged_pol):
    for (key, value) in merged_pol.items():
      if key in diff_pol:
        if key in constants.IPOLICY_ISPECS:
          self._AssertISpecsMerged(default_pol[key], diff_pol[key], value)
        else:
          self.assertEqual(value, diff_pol[key])
      else:
        self.assertEqual(value, default_pol[key])

  def testFillIPolicy(self):
    partial_policies = [
      {constants.IPOLICY_VCPU_RATIO: 3.14},
      {constants.IPOLICY_SPINDLE_RATIO: 2.72},
      {constants.IPOLICY_DTS: []},
      {constants.IPOLICY_DTS: [constants.DT_FILE]},
      ]
    for diff_pol in partial_policies:
      policy = objects.FillIPolicy(constants.IPOLICY_DEFAULTS, diff_pol)
      objects.InstancePolicy.CheckParameterSyntax(policy, True)
      self._AssertIPolicyIsFull(policy)
      self._AssertIPolicyMerged(constants.IPOLICY_DEFAULTS, diff_pol, policy)

  def testFillIPolicySpecs(self):
    partial_policies = [
      {constants.ISPECS_MIN: {constants.ISPEC_MEM_SIZE: 32},
       constants.ISPECS_MAX: {constants.ISPEC_CPU_COUNT: 1024}},
      {constants.ISPECS_STD: {constants.ISPEC_DISK_SIZE: 2048},
       constants.ISPECS_MAX: {
          constants.ISPEC_DISK_COUNT: constants.MAX_DISKS - 1,
          constants.ISPEC_NIC_COUNT: constants.MAX_NICS - 1,
          }},
      {constants.ISPECS_STD: {constants.ISPEC_SPINDLE_USE: 3}},
      ]
    for diff_pol in partial_policies:
      policy = objects.FillIPolicy(constants.IPOLICY_DEFAULTS, diff_pol)
      objects.InstancePolicy.CheckParameterSyntax(policy, True)
      self._AssertIPolicyIsFull(policy)
      self._AssertIPolicyMerged(constants.IPOLICY_DEFAULTS, diff_pol, policy)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
