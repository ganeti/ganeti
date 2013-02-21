#!/usr/bin/python
#

# Copyright (C) 2012, 2013 Google Inc.
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


"""Script for testing qa.qa_config"""

import unittest
import tempfile
import shutil
import os
import operator

from ganeti import utils
from ganeti import serializer
from ganeti import constants
from ganeti import compat

from qa import qa_config
from qa import qa_error

import testutils


class TestTestEnabled(unittest.TestCase):
  def testSimple(self):
    for name in ["test", ["foobar"], ["a", "b"]]:
      self.assertTrue(qa_config.TestEnabled(name, _cfg={}))

    for default in [False, True]:
      self.assertFalse(qa_config.TestEnabled("foo", _cfg={
        "tests": {
          "default": default,
          "foo": False,
          },
        }))

      self.assertTrue(qa_config.TestEnabled("bar", _cfg={
        "tests": {
          "default": default,
          "bar": True,
          },
        }))

  def testEitherWithDefault(self):
    names = qa_config.Either("one")

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        },
      }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": False,
        },
      }))

  def testEither(self):
    names = [qa_config.Either(["one", "two"]),
             qa_config.Either("foo"),
             "hello",
             ["bar", "baz"]]

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        },
      }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": False,
        },
      }))

    for name in ["foo", "bar", "baz", "hello"]:
      self.assertFalse(qa_config.TestEnabled(names, _cfg={
        "tests": {
          "default": True,
          name: False,
          },
        }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        "one": False,
        "two": False,
        },
      }))

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        "one": False,
        "two": True,
        },
      }))

    self.assertFalse(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        "one": True,
        "two": True,
        "foo": False,
        },
      }))

  def testEitherNestedWithAnd(self):
    names = qa_config.Either([["one", "two"], "foo"])

    self.assertTrue(qa_config.TestEnabled(names, _cfg={
      "tests": {
        "default": True,
        },
      }))

    for name in ["one", "two"]:
      self.assertFalse(qa_config.TestEnabled(names, _cfg={
        "tests": {
          "default": True,
          "foo": False,
          name: False,
          },
        }))

  def testCallable(self):
    self.assertTrue(qa_config.TestEnabled([lambda: True], _cfg={}))

    for value in [None, False, "", 0]:
      self.assertFalse(qa_config.TestEnabled(lambda: value, _cfg={}))


class TestQaConfigLoad(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testLoadNonExistent(self):
    filename = utils.PathJoin(self.tmpdir, "does.not.exist")
    self.assertRaises(EnvironmentError, qa_config._QaConfig.Load, filename)

  @staticmethod
  def _WriteConfig(filename, data):
    utils.WriteFile(filename, data=serializer.DumpJson(data))

  def _CheckLoadError(self, filename, data, expected):
    self._WriteConfig(filename, data)

    try:
      qa_config._QaConfig.Load(filename)
    except qa_error.Error, err:
      self.assertTrue(str(err).startswith(expected))
    else:
      self.fail("Exception was not raised")

  def testFailsValidation(self):
    filename = utils.PathJoin(self.tmpdir, "qa.json")
    testconfig = {}

    check_fn = compat.partial(self._CheckLoadError, filename, testconfig)

    # No cluster name
    check_fn("Cluster name is required")

    testconfig["name"] = "cluster.example.com"

    # No nodes
    check_fn("Need at least one node")

    testconfig["nodes"] = [
      {
        "primary": "xen-test-0",
        "secondary": "192.0.2.1",
        },
      ]

    # No instances
    check_fn("Need at least one instance")

    testconfig["instances"] = [
      {
        "name": "xen-test-inst1",
        },
      ]

    # Missing "disk" and "disk-growth"
    check_fn("Config options 'disk' and 'disk-growth' ")

    testconfig["disk"] = []
    testconfig["disk-growth"] = testconfig["disk"]

    # Minimal accepted configuration
    self._WriteConfig(filename, testconfig)
    result = qa_config._QaConfig.Load(filename)
    self.assertTrue(result.get("nodes"))

    # Non-existent instance check script
    testconfig[qa_config._INSTANCE_CHECK_KEY] = \
      utils.PathJoin(self.tmpdir, "instcheck")
    check_fn("Can't find instance check script")
    del testconfig[qa_config._INSTANCE_CHECK_KEY]

    # No enabled hypervisor
    testconfig[qa_config._ENABLED_HV_KEY] = None
    check_fn("No hypervisor is enabled")

    # Unknown hypervisor
    testconfig[qa_config._ENABLED_HV_KEY] = ["#unknownhv#"]
    check_fn("Unknown hypervisor(s) enabled:")
    del testconfig[qa_config._ENABLED_HV_KEY]

    # Invalid path for virtual cluster base directory
    testconfig[qa_config._VCLUSTER_MASTER_KEY] = "value"
    testconfig[qa_config._VCLUSTER_BASEDIR_KEY] = "./not//normalized/"
    check_fn("Path given in option 'vcluster-basedir' must be")

    # Inconsistent virtual cluster settings
    testconfig.pop(qa_config._VCLUSTER_MASTER_KEY)
    testconfig[qa_config._VCLUSTER_BASEDIR_KEY] = "/tmp"
    check_fn("All or none of the")

    testconfig[qa_config._VCLUSTER_MASTER_KEY] = "master.example.com"
    testconfig.pop(qa_config._VCLUSTER_BASEDIR_KEY)
    check_fn("All or none of the")

    # Accepted virtual cluster settings
    testconfig[qa_config._VCLUSTER_MASTER_KEY] = "master.example.com"
    testconfig[qa_config._VCLUSTER_BASEDIR_KEY] = "/tmp"

    self._WriteConfig(filename, testconfig)
    result = qa_config._QaConfig.Load(filename)
    self.assertEqual(result.GetVclusterSettings(),
                     ("master.example.com", "/tmp"))


class TestQaConfigWithSampleConfig(unittest.TestCase):
  """Tests using C{qa-sample.json}.

  This test case serves two purposes:

    - Ensure shipped C{qa-sample.json} file is considered a valid QA
      configuration
    - Test some functions of L{qa_config._QaConfig} without having to
      mock a whole configuration file

  """
  def setUp(self):
    filename = "%s/qa/qa-sample.json" % testutils.GetSourceDir()

    self.config = qa_config._QaConfig.Load(filename)

  def testGetEnabledHypervisors(self):
    self.assertEqual(self.config.GetEnabledHypervisors(),
                     [constants.DEFAULT_ENABLED_HYPERVISOR])

  def testGetDefaultHypervisor(self):
    self.assertEqual(self.config.GetDefaultHypervisor(),
                     constants.DEFAULT_ENABLED_HYPERVISOR)

  def testGetInstanceCheckScript(self):
    self.assertTrue(self.config.GetInstanceCheckScript() is None)

  def testGetAndGetItem(self):
    self.assertEqual(self.config["nodes"], self.config.get("nodes"))

  def testGetMasterNode(self):
    self.assertEqual(self.config.GetMasterNode(), self.config["nodes"][0])

  def testGetVclusterSettings(self):
    # Shipped default settings should be to not use a virtual cluster
    self.assertEqual(self.config.GetVclusterSettings(), (None, None))

    self.assertFalse(qa_config.UseVirtualCluster(_cfg=self.config))


class TestQaConfig(unittest.TestCase):
  def setUp(self):
    filename = \
      testutils.TestDataFilename("qa-minimal-nodes-instances-only.json")

    self.config = qa_config._QaConfig.Load(filename)

  def testExclusiveStorage(self):
    self.assertRaises(AssertionError, self.config.GetExclusiveStorage)

    for value in [False, True, 0, 1, 30804, ""]:
      self.config.SetExclusiveStorage(value)
      self.assertEqual(self.config.GetExclusiveStorage(), bool(value))

      for template in constants.DISK_TEMPLATES:
        if value and template not in constants.DTS_EXCL_STORAGE:
          self.assertFalse(self.config.IsTemplateSupported(template))
        else:
          self.assertTrue(self.config.IsTemplateSupported(template))

  def testInstanceConversion(self):
    self.assertTrue(isinstance(self.config["instances"][0],
                               qa_config._QaInstance))

  def testNodeConversion(self):
    self.assertTrue(isinstance(self.config["nodes"][0],
                               qa_config._QaNode))

  def testAcquireAndReleaseInstance(self):
    self.assertFalse(compat.any(map(operator.attrgetter("used"),
                                    self.config["instances"])))

    inst = qa_config.AcquireInstance(_cfg=self.config)
    self.assertTrue(inst.used)
    self.assertTrue(inst.disk_template is None)

    inst.Release()

    self.assertFalse(inst.used)
    self.assertTrue(inst.disk_template is None)

    self.assertFalse(compat.any(map(operator.attrgetter("used"),
                                    self.config["instances"])))

  def testAcquireInstanceTooMany(self):
    # Acquire all instances
    for _ in range(len(self.config["instances"])):
      inst = qa_config.AcquireInstance(_cfg=self.config)
      self.assertTrue(inst.used)
      self.assertTrue(inst.disk_template is None)

    # The next acquisition must fail
    self.assertRaises(qa_error.OutOfInstancesError,
                      qa_config.AcquireInstance, _cfg=self.config)

  def testAcquireNodeNoneAdded(self):
    self.assertFalse(compat.any(map(operator.attrgetter("added"),
                                    self.config["nodes"])))

    # First call must return master node
    node = qa_config.AcquireNode(_cfg=self.config)
    self.assertEqual(node, self.config.GetMasterNode())

    # Next call with exclusion list fails
    self.assertRaises(qa_error.OutOfNodesError, qa_config.AcquireNode,
                      exclude=[node], _cfg=self.config)

  def testAcquireNodeTooMany(self):
    # Mark all nodes as marked (master excluded)
    for node in self.config["nodes"]:
      if node != self.config.GetMasterNode():
        node.MarkAdded()

    nodecount = len(self.config["nodes"])

    self.assertTrue(nodecount > 1)

    acquired = []

    for _ in range(nodecount):
      node = qa_config.AcquireNode(exclude=acquired, _cfg=self.config)
      if node == self.config.GetMasterNode():
        self.assertFalse(node.added)
      else:
        self.assertTrue(node.added)
      self.assertEqual(node.use_count, 1)
      acquired.append(node)

    self.assertRaises(qa_error.OutOfNodesError, qa_config.AcquireNode,
                      exclude=acquired, _cfg=self.config)

  def testAcquireNodeOrder(self):
    # Mark all nodes as marked (master excluded)
    for node in self.config["nodes"]:
      if node != self.config.GetMasterNode():
        node.MarkAdded()

    nodecount = len(self.config["nodes"])

    for iterations in [0, 1, 3, 100, 127, 7964]:
      acquired = []

      for i in range(iterations):
        node = qa_config.AcquireNode(_cfg=self.config)
        self.assertTrue(node.use_count > 0)
        self.assertEqual(node.use_count, (i / nodecount + 1))
        acquired.append((node.use_count, node.primary, node))

      # Check if returned nodes were in correct order
      key_fn = lambda (a, b, c): (a, utils.NiceSortKey(b), c)
      self.assertEqual(acquired, sorted(acquired, key=key_fn))

      # Release previously acquired nodes
      qa_config.ReleaseManyNodes(map(operator.itemgetter(2), acquired))

      # Check if nodes were actually released
      for node in self.config["nodes"]:
        self.assertEqual(node.use_count, 0)
        self.assertTrue(node.added or node == self.config.GetMasterNode())


class TestRepresentation(unittest.TestCase):
  def _Check(self, target, part):
    self.assertTrue(part in repr(target).split())

  def testQaInstance(self):
    inst = qa_config._QaInstance("inst1.example.com", [])
    self._Check(inst, "name=inst1.example.com")
    self._Check(inst, "nicmac=[]")

    # Default values
    self._Check(inst, "disk_template=None")
    self._Check(inst, "used=None")

    # Use instance
    inst.Use()
    self._Check(inst, "used=True")

    # Disk template
    inst.SetDiskTemplate(constants.DT_DRBD8)
    self._Check(inst, "disk_template=%s" % constants.DT_DRBD8)

    # Release instance
    inst.Release()
    self._Check(inst, "used=False")
    self._Check(inst, "disk_template=None")

  def testQaNode(self):
    node = qa_config._QaNode("primary.example.com", "192.0.2.1")
    self._Check(node, "primary=primary.example.com")
    self._Check(node, "secondary=192.0.2.1")
    self._Check(node, "added=False")
    self._Check(node, "use_count=0")

    # Mark as added
    node.MarkAdded()
    self._Check(node, "added=True")

    # Use node
    for i in range(1, 5):
      node.Use()
      self._Check(node, "use_count=%s" % i)

    # Release node
    for i in reversed(range(1, 5)):
      node.Release()
      self._Check(node, "use_count=%s" % (i - 1))

    self._Check(node, "use_count=0")

    # Mark as added
    node.MarkRemoved()
    self._Check(node, "added=False")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
