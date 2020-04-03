#!/usr/bin/python3
#

# Copyright (C) 2012 Google Inc.
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


KNOWN_UNUSED_LUXI = compat.UniqueFrozenset([
  luxi.REQ_SUBMIT_MANY_JOBS,
  luxi.REQ_SUBMIT_JOB_TO_DRAINED_QUEUE,
  luxi.REQ_ARCHIVE_JOB,
  luxi.REQ_AUTO_ARCHIVE_JOBS,
  luxi.REQ_CHANGE_JOB_PRIORITY,
  luxi.REQ_PICKUP_JOB,
  luxi.REQ_QUERY_EXPORTS,
  luxi.REQ_QUERY_CONFIG_VALUES,
  luxi.REQ_QUERY_NETWORKS,
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

  def testGetFilters(self):
    self.assertTrue(self.cl.GetFilters() is NotImplemented)

  def testGetFilter(self):
    result = self.cl.GetFilter("4364c043-f232-41e3-837f-f1ce846f21d2")
    self.assertTrue(result is NotImplemented)

  def testReplaceFilter(self):
    self.assertTrue(self.cl.ReplaceFilter(
      uuid="c6a70f02-facb-4e37-b344-54f146dd0396",
      priority=1,
      predicates=[["jobid", [">", "id", "watermark"]]],
      action="CONTINUE",
      reason_trail=["testReplaceFilter", "myreason", utils.EpochNano()],
    ) is NotImplemented)

  def testAddFilter(self):
    self.assertTrue(self.cl.AddFilter(
      priority=1,
      predicates=[["jobid", [">", "id", "watermark"]]],
      action="CONTINUE",
      reason_trail=["testAddFilter", "myreason", utils.EpochNano()],
    ) is NotImplemented)

  def testDeleteFilter(self):
    self.assertTrue(self.cl.DeleteFilter(
      uuid="c6a70f02-facb-4e37-b344-54f146dd0396",
    ) is NotImplemented)

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
