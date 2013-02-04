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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
