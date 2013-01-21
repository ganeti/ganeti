#!/usr/bin/python
#

# Copyright (C) 2011, 2013 Google Inc.
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


"""Script for testing ganeti.hypervisor.hv_lxc"""

import unittest

from ganeti import constants
from ganeti import objects
from ganeti import hypervisor
from ganeti import utils
from ganeti import errors
from ganeti import compat

from ganeti.hypervisor import hv_xen

import testutils


class TestConsole(unittest.TestCase):
  def test(self):
    for cls in [hv_xen.XenPvmHypervisor, hv_xen.XenHvmHypervisor]:
      instance = objects.Instance(name="xen.example.com",
                                  primary_node="node24828")
      cons = cls.GetInstanceConsole(instance, {}, {})
      self.assertTrue(cons.Validate())
      self.assertEqual(cons.kind, constants.CONS_SSH)
      self.assertEqual(cons.host, instance.primary_node)
      self.assertEqual(cons.command[-1], instance.name)


class TestCreateConfigCpus(unittest.TestCase):
  def testEmpty(self):
    for cpu_mask in [None, ""]:
      self.assertEqual(hv_xen._CreateConfigCpus(cpu_mask),
                       "cpus = [  ]")

  def testAll(self):
    self.assertEqual(hv_xen._CreateConfigCpus(constants.CPU_PINNING_ALL),
                     None)

  def testOne(self):
    self.assertEqual(hv_xen._CreateConfigCpus("9"), "cpu = \"9\"")

  def testMultiple(self):
    self.assertEqual(hv_xen._CreateConfigCpus("0-2,4,5-5:3:all"),
                     ("cpus = [ \"0,1,2,4,5\", \"3\", \"%s\" ]" %
                      constants.CPU_PINNING_ALL_XEN))


class TestParseXmList(testutils.GanetiTestCase):
  def test(self):
    data = testutils.ReadTestData("xen-xm-list-4.0.1-dom0-only.txt")

    # Exclude node
    self.assertEqual(hv_xen._ParseXmList(data.splitlines(), False), [])

    # Include node
    result = hv_xen._ParseXmList(data.splitlines(), True)
    self.assertEqual(len(result), 1)
    self.assertEqual(len(result[0]), 6)

    # Name
    self.assertEqual(result[0][0], hv_xen._DOM0_NAME)

    # ID
    self.assertEqual(result[0][1], 0)

    # Memory
    self.assertEqual(result[0][2], 1023)

    # VCPUs
    self.assertEqual(result[0][3], 1)

    # State
    self.assertEqual(result[0][4], "r-----")

    # Time
    self.assertAlmostEqual(result[0][5], 121152.6)

  def testWrongLineFormat(self):
    tests = [
      ["three fields only"],
      ["name InvalidID 128 1 r----- 12345"],
      ]

    for lines in tests:
      try:
        hv_xen._ParseXmList(["Header would be here"] + lines, False)
      except errors.HypervisorError, err:
        self.assertTrue("Can't parse output of xm list" in str(err))
      else:
        self.fail("Exception was not raised")


class TestGetXmList(testutils.GanetiTestCase):
  def _Fail(self):
    return utils.RunResult(constants.EXIT_FAILURE, None,
                           "stdout", "stderr", None,
                           NotImplemented, NotImplemented)

  def testTimeout(self):
    fn = testutils.CallCounter(self._Fail)
    try:
      hv_xen._GetXmList(fn, False, _timeout=0.1)
    except errors.HypervisorError, err:
      self.assertTrue("timeout exceeded" in str(err))
    else:
      self.fail("Exception was not raised")

    self.assertTrue(fn.Count() < 10,
                    msg="'xm list' was called too many times")

  def _Success(self, stdout):
    return utils.RunResult(constants.EXIT_SUCCESS, None, stdout, "", None,
                           NotImplemented, NotImplemented)

  def testSuccess(self):
    data = testutils.ReadTestData("xen-xm-list-4.0.1-four-instances.txt")

    fn = testutils.CallCounter(compat.partial(self._Success, data))

    result = hv_xen._GetXmList(fn, True, _timeout=0.1)

    self.assertEqual(len(result), 4)

    self.assertEqual(map(compat.fst, result), [
      "Domain-0",
      "server01.example.com",
      "web3106215069.example.com",
      "testinstance.example.com",
      ])

    self.assertEqual(fn.Count(), 1)


class TestParseNodeInfo(testutils.GanetiTestCase):
  def testEmpty(self):
    self.assertEqual(hv_xen._ParseNodeInfo(""), {})

  def testUnknownInput(self):
    data = "\n".join([
      "foo bar",
      "something else goes",
      "here",
      ])
    self.assertEqual(hv_xen._ParseNodeInfo(data), {})

  def testBasicInfo(self):
    data = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    result = hv_xen._ParseNodeInfo(data)
    self.assertEqual(result, {
      "cpu_nodes": 1,
      "cpu_sockets": 2,
      "cpu_total": 4,
      "hv_version": (4, 0),
      "memory_free": 8004,
      "memory_total": 16378,
      })


class TestMergeInstanceInfo(testutils.GanetiTestCase):
  def testEmpty(self):
    self.assertEqual(hv_xen._MergeInstanceInfo({}, lambda _: []), {})

  def _FakeXmList(self, include_node):
    self.assertTrue(include_node)
    return [
      (hv_xen._DOM0_NAME, NotImplemented, 4096, 7, NotImplemented,
       NotImplemented),
      ("inst1.example.com", NotImplemented, 2048, 4, NotImplemented,
       NotImplemented),
      ]

  def testMissingNodeInfo(self):
    result = hv_xen._MergeInstanceInfo({}, self._FakeXmList)
    self.assertEqual(result, {
      "memory_dom0": 4096,
      "dom0_cpus": 7,
      })

  def testWithNodeInfo(self):
    info = testutils.ReadTestData("xen-xm-info-4.0.1.txt")
    result = hv_xen._GetNodeInfo(info, self._FakeXmList)
    self.assertEqual(result, {
      "cpu_nodes": 1,
      "cpu_sockets": 2,
      "cpu_total": 4,
      "dom0_cpus": 7,
      "hv_version": (4, 0),
      "memory_dom0": 4096,
      "memory_free": 8004,
      "memory_hv": 2230,
      "memory_total": 16378,
      })


if __name__ == "__main__":
  testutils.GanetiTestProgram()
