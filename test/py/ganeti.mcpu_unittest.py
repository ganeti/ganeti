#!/usr/bin/python
#

# Copyright (C) 2009, 2011 Google Inc.
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


"""Script for unittesting the mcpu module"""


import unittest
import itertools
import mocks
from cmdlib.testsupport.rpc_runner_mock import CreateRpcRunnerMock

from ganeti import compat
from ganeti import errors
from ganeti import mcpu
from ganeti import opcodes
from ganeti import cmdlib
from ganeti import locking
from ganeti import serializer
from ganeti import ht
from ganeti import constants
from ganeti.constants import \
    LOCK_ATTEMPTS_TIMEOUT, \
    LOCK_ATTEMPTS_MAXWAIT, \
    LOCK_ATTEMPTS_MINWAIT

import testutils


# FIXME: Document what BGL whitelist means
REQ_BGL_WHITELIST = compat.UniqueFrozenset([
  opcodes.OpClusterActivateMasterIp,
  opcodes.OpClusterDeactivateMasterIp,
  opcodes.OpClusterDestroy,
  opcodes.OpClusterPostInit,
  opcodes.OpClusterRename,
  opcodes.OpNodeAdd,
  opcodes.OpNodeRemove,
  opcodes.OpTestAllocator,
  ])


class TestLockAttemptTimeoutStrategy(unittest.TestCase):
  def testConstants(self):
    tpa = mcpu.LockAttemptTimeoutStrategy._TIMEOUT_PER_ATTEMPT
    self.assertTrue(len(tpa) > LOCK_ATTEMPTS_TIMEOUT / LOCK_ATTEMPTS_MAXWAIT)
    self.assertTrue(sum(tpa) >= LOCK_ATTEMPTS_TIMEOUT)

    self.assertTrue(LOCK_ATTEMPTS_TIMEOUT >= 1800,
                    msg="Waiting less than half an hour per priority")
    self.assertTrue(LOCK_ATTEMPTS_TIMEOUT <= 3600,
                    msg="Waiting more than an hour per priority")

  def testSimple(self):
    strat = mcpu.LockAttemptTimeoutStrategy(_random_fn=lambda: 0.5,
                                            _time_fn=lambda: 0.0)

    prev = None
    for i in range(len(strat._TIMEOUT_PER_ATTEMPT)):
      timeout = strat.NextAttempt()
      self.assertTrue(timeout is not None)

      self.assertTrue(timeout <= LOCK_ATTEMPTS_MAXWAIT)
      self.assertTrue(timeout >= LOCK_ATTEMPTS_MINWAIT)
      self.assertTrue(prev is None or timeout >= prev)

      prev = timeout

    for _ in range(10):
      self.assertTrue(strat.NextAttempt() is None)


class TestDispatchTable(unittest.TestCase):
  def test(self):
    for opcls in opcodes.OP_MAPPING.values():
      if not opcls.WITH_LU:
        continue
      self.assertTrue(opcls in mcpu.Processor.DISPATCH_TABLE,
                      msg="%s missing handler class" % opcls)

      # Check against BGL whitelist
      lucls = mcpu.Processor.DISPATCH_TABLE[opcls]
      if lucls.REQ_BGL:
        self.assertTrue(opcls in REQ_BGL_WHITELIST,
                        msg=("%s not whitelisted for BGL" % opcls.OP_ID))
      else:
        self.assertFalse(opcls in REQ_BGL_WHITELIST,
                         msg=("%s whitelisted for BGL, but doesn't use it" %
                              opcls.OP_ID))


class TestProcessResult(unittest.TestCase):
  def setUp(self):
    self._submitted = []
    self._count = itertools.count(200)

  def _Submit(self, jobs):
    job_ids = [next(self._count) for _ in jobs]
    self._submitted.extend(zip(job_ids, jobs))
    return job_ids

  def testNoJobs(self):
    for i in [object(), [], False, True, None, 1, 929, {}]:
      self.assertEqual(mcpu._ProcessResult(NotImplemented, NotImplemented, i),
                       i)

  def testDefaults(self):
    src = opcodes.OpTestDummy()

    res = mcpu._ProcessResult(self._Submit, src, cmdlib.ResultWithJobs([[
      opcodes.OpTestDelay(),
      opcodes.OpTestDelay(),
      ], [
      opcodes.OpTestDelay(),
      ]]))

    self.assertEqual(res, {
      constants.JOB_IDS_KEY: [200, 201],
      })

    (_, (op1, op2)) = self._submitted.pop(0)
    (_, (op3, )) = self._submitted.pop(0)
    self.assertRaises(IndexError, self._submitted.pop)

    for op in [op1, op2, op3]:
      self.assertTrue("OP_TEST_DUMMY" in op.comment)

  def testParams(self):
    src = opcodes.OpTestDummy(priority=constants.OP_PRIO_HIGH,
                              debug_level=3)

    res = mcpu._ProcessResult(self._Submit, src, cmdlib.ResultWithJobs([[
      opcodes.OpTestDelay(priority=constants.OP_PRIO_LOW),
      ], [
      opcodes.OpTestDelay(comment="foobar", debug_level=10),
      ]], other=True, value=range(10)))

    self.assertEqual(res, {
      constants.JOB_IDS_KEY: [200, 201],
      "other": True,
      "value": range(10),
      })

    (_, (op1, )) = self._submitted.pop(0)
    (_, (op2, )) = self._submitted.pop(0)
    self.assertRaises(IndexError, self._submitted.pop)

    self.assertEqual(op1.priority, constants.OP_PRIO_LOW)
    self.assertTrue("OP_TEST_DUMMY" in op1.comment)
    self.assertEqual(op1.debug_level, 3)

    # FIXME: as priority is mandatory, there is no way
    # of specifying "just inherit the priority".
    self.assertEqual(op2.comment, "foobar")
    self.assertEqual(op2.debug_level, 3)

class TestExecLU(unittest.TestCase):
  class OpTest(opcodes.OpCode):
    OP_DSC_FIELD = "data"
    OP_PARAMS = [
      ("data", ht.NoDefault, ht.TString, None),
    ]

  def setUp(self):
    self.ctx = mocks.FakeContext()
    self.cfg = self.ctx.GetConfig("ec_id")
    self.rpc = CreateRpcRunnerMock()
    self.proc = mcpu.Processor(self.ctx, "ec_id", enable_locks = False)
    self.op = self.OpTest()
    self.calc_timeout = lambda: 42

  def testRunLU(self):
    lu = mocks.FakeLU(self.proc, self.op, self.cfg, self.rpc, None)
    self.proc._ExecLU(lu)

  def testRunLUWithPrereqError(self):
    prereq = errors.OpPrereqError(self.op, errors.ECODE_INVAL)
    lu = mocks.FakeLU(self.proc, self.op, self.cfg, self.rpc, prereq)
    self.assertRaises(errors.OpPrereqError, self.proc._LockAndExecLU,
        lu, locking.LEVEL_CLUSTER, self.calc_timeout)

  def testRunLUWithPrereqErrorMissingECode(self):
    prereq = errors.OpPrereqError(self.op)
    lu = mocks.FakeLU(self.proc, self.op, self.cfg, self.rpc, prereq)
    self.assertRaises(errors.OpPrereqError, self.proc._LockAndExecLU,
        lu, locking.LEVEL_CLUSTER, self.calc_timeout)


class TestSecretParams(unittest.TestCase):
  def testSecretParamsCheckNoError(self):
    op = opcodes.OpInstanceCreate(
      instance_name="plain.example.com",
      pnode="master.example.com",
      disk_template=constants.DT_PLAIN,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      osparams_secret= serializer.PrivateDict({"foo":"bar", "foo2":"bar2"}),
      os_type="debian-image")

    try:
      mcpu._CheckSecretParameters(op)
    except errors.OpPrereqError:
      self.fail("OpPrereqError raised unexpectedly in _CheckSecretParameters")

  def testSecretParamsCheckWithError(self):
    op = opcodes.OpInstanceCreate(
      instance_name="plain.example.com",
      pnode="master.example.com",
      disk_template=constants.DT_PLAIN,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      osparams_secret= serializer.PrivateDict({"foo":"bar",
                                              "secret_param":"<redacted>"}),
      os_type="debian-image")

    self.assertRaises(errors.OpPrereqError, mcpu._CheckSecretParameters, op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
