#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.rapi.testutils"""

import unittest

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import opcodes
from ganeti import luxi
from ganeti import rapi
from ganeti import utils

import ganeti.rapi.testutils
import ganeti.rapi.client

import testutils


KNOWN_UNUSED_LUXI = frozenset([
  luxi.REQ_SUBMIT_MANY_JOBS,
  luxi.REQ_ARCHIVE_JOB,
  luxi.REQ_AUTO_ARCHIVE_JOBS,
  luxi.REQ_CHANGE_JOB_PRIORITY,
  luxi.REQ_QUERY_EXPORTS,
  luxi.REQ_QUERY_CONFIG_VALUES,
  luxi.REQ_QUERY_TAGS,
  luxi.REQ_SET_DRAIN_FLAG,
  luxi.REQ_SET_WATCHER_PAUSE,
  ])


# Global variable for storing used LUXI calls
_used_luxi_calls = None


class TestHideInternalErrors(unittest.TestCase):
  def test(self):
    def inner():
      raise errors.GenericError("error")

    fn = rapi.testutils._HideInternalErrors(inner)

    self.assertRaises(rapi.testutils.VerificationError, fn)


class TestVerifyOpInput(unittest.TestCase):
  def testUnknownOpId(self):
    voi = rapi.testutils.VerifyOpInput

    self.assertRaises(rapi.testutils.VerificationError, voi, "UNK_OP_ID", None)

  def testUnknownParameter(self):
    voi = rapi.testutils.VerifyOpInput

    self.assertRaises(rapi.testutils.VerificationError, voi,
      opcodes.OpClusterRename.OP_ID, {
      "unk": "unk",
      })

  def testWrongParameterValue(self):
    voi = rapi.testutils.VerifyOpInput
    self.assertRaises(rapi.testutils.VerificationError, voi,
      opcodes.OpClusterRename.OP_ID, {
      "name": object(),
      })

  def testSuccess(self):
    voi = rapi.testutils.VerifyOpInput
    voi(opcodes.OpClusterRename.OP_ID, {
      "name": "new-name.example.com",
      })


class TestVerifyOpResult(unittest.TestCase):
  def testSuccess(self):
    vor = rapi.testutils.VerifyOpResult

    vor(opcodes.OpClusterVerify.OP_ID, {
      constants.JOB_IDS_KEY: [
        (False, "error message"),
        ],
      })

  def testWrongResult(self):
    vor = rapi.testutils.VerifyOpResult

    self.assertRaises(rapi.testutils.VerificationError, vor,
      opcodes.OpClusterVerify.OP_ID, [])

  def testNoResultCheck(self):
    vor = rapi.testutils.VerifyOpResult

    assert opcodes.OpTestDummy.OP_RESULT is None

    vor(opcodes.OpTestDummy.OP_ID, None)


class TestInputTestClient(unittest.TestCase):
  def setUp(self):
    self.cl = rapi.testutils.InputTestClient()

  def tearDown(self):
    _used_luxi_calls.update(self.cl._GetLuxiCalls())

  def testGetInfo(self):
    self.assertTrue(self.cl.GetInfo() is NotImplemented)

  def testPrepareExport(self):
    result = self.cl.PrepareExport("inst1.example.com",
                                   constants.EXPORT_MODE_LOCAL)
    self.assertTrue(result is NotImplemented)
    self.assertRaises(rapi.testutils.VerificationError, self.cl.PrepareExport,
                      "inst1.example.com", "###invalid###")

  def testGetJobs(self):
    self.assertTrue(self.cl.GetJobs() is NotImplemented)

  def testQuery(self):
    result = self.cl.Query(constants.QR_NODE, ["name"])
    self.assertTrue(result is NotImplemented)

  def testQueryFields(self):
    result = self.cl.QueryFields(constants.QR_INSTANCE)
    self.assertTrue(result is NotImplemented)

  def testCancelJob(self):
    self.assertTrue(self.cl.CancelJob("1") is NotImplemented)

  def testGetNodes(self):
    self.assertTrue(self.cl.GetNodes() is NotImplemented)

  def testGetInstances(self):
    self.assertTrue(self.cl.GetInstances() is NotImplemented)

  def testGetGroups(self):
    self.assertTrue(self.cl.GetGroups() is NotImplemented)

  def testWaitForJobChange(self):
    result = self.cl.WaitForJobChange("1", ["id"], None, None)
    self.assertTrue(result is NotImplemented)


class CustomTestRunner(unittest.TextTestRunner):
  def run(self, *args):
    global _used_luxi_calls
    assert _used_luxi_calls is None

    diff = (KNOWN_UNUSED_LUXI - luxi.REQ_ALL)
    assert not diff, "Non-existing LUXI calls listed as unused: %s" % diff

    _used_luxi_calls = set()
    try:
      # Run actual tests
      result = unittest.TextTestRunner.run(self, *args)

      diff = _used_luxi_calls & KNOWN_UNUSED_LUXI
      if diff:
        raise AssertionError("LUXI methods marked as unused were called: %s" %
                             utils.CommaJoin(diff))

      diff = (luxi.REQ_ALL - KNOWN_UNUSED_LUXI - _used_luxi_calls)
      if diff:
        raise AssertionError("The following LUXI methods were not used: %s" %
                             utils.CommaJoin(diff))
    finally:
      # Reset global variable
      _used_luxi_calls = None

    return result


if __name__ == "__main__":
  testutils.GanetiTestProgram(testRunner=CustomTestRunner)
