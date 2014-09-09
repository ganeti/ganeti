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

from ganeti import compat
from ganeti import mcpu
from ganeti import opcodes
from ganeti import cmdlib
from ganeti import locking
from ganeti import constants
from ganeti.constants import \
    LOCK_ATTEMPTS_TIMEOUT, \
    LOCK_ATTEMPTS_MAXWAIT, \
    LOCK_ATTEMPTS_MINWAIT

import testutils


REQ_BGL_WHITELIST = compat.UniqueFrozenset([
  opcodes.OpClusterActivateMasterIp,
  opcodes.OpClusterDeactivateMasterIp,
  opcodes.OpClusterDestroy,
  opcodes.OpClusterPostInit,
  opcodes.OpClusterRename,
  opcodes.OpInstanceRename,
  opcodes.OpNodeAdd,
  opcodes.OpNodeRemove,
  opcodes.OpTestAllocator,
  ])


class TestLockAttemptTimeoutStrategy(unittest.TestCase):
  def testConstants(self):
    tpa = mcpu.LockAttemptTimeoutStrategy._TIMEOUT_PER_ATTEMPT
    self.assert_(len(tpa) > LOCK_ATTEMPTS_TIMEOUT / LOCK_ATTEMPTS_MAXWAIT)
    self.assert_(sum(tpa) >= LOCK_ATTEMPTS_TIMEOUT)

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
      self.assert_(timeout is not None)

      self.assert_(timeout <= LOCK_ATTEMPTS_MAXWAIT)
      self.assert_(timeout >= LOCK_ATTEMPTS_MINWAIT)
      self.assert_(prev is None or timeout >= prev)

      prev = timeout

    for _ in range(10):
      self.assert_(strat.NextAttempt() is None)


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
    job_ids = [self._count.next() for _ in jobs]
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
      self.assertFalse(hasattr(op, "priority"))
      self.assertFalse(hasattr(op, "debug_level"))

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

    self.assertEqual(op2.priority, constants.OP_PRIO_HIGH)
    self.assertEqual(op2.comment, "foobar")
    self.assertEqual(op2.debug_level, 3)


class _FakeLuWithLocks:
  def __init__(self, needed_locks, share_locks):
    self.needed_locks = needed_locks
    self.share_locks = share_locks


class _FakeGlm:
  def __init__(self, owning_nal):
    self._owning_nal = owning_nal

  def check_owned(self, level, names):
    assert level == locking.LEVEL_NODE_ALLOC
    assert names == locking.NAL
    return self._owning_nal

  def owning_all(self, level):
    return False


class TestVerifyLocks(unittest.TestCase):
  def testNoLocks(self):
    lu = _FakeLuWithLocks({}, {})
    glm = _FakeGlm(False)
    mcpu._VerifyLocks(lu, glm,
                      _mode_whitelist=NotImplemented,
                      _nal_whitelist=NotImplemented)

  def testNotAllSameMode(self):
    for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
      lu = _FakeLuWithLocks({
        level: ["foo"],
        }, {
        level: 0,
        locking.LEVEL_NODE_ALLOC: 0,
        })
      glm = _FakeGlm(False)
      mcpu._VerifyLocks(lu, glm, _mode_whitelist=[], _nal_whitelist=[])

  def testDifferentMode(self):
    for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
      lu = _FakeLuWithLocks({
        level: ["foo"],
        }, {
        level: 0,
        locking.LEVEL_NODE_ALLOC: 1,
        })
      glm = _FakeGlm(False)
      try:
        mcpu._VerifyLocks(lu, glm, _mode_whitelist=[], _nal_whitelist=[])
      except AssertionError, err:
        self.assertTrue("using the same mode as nodes" in str(err))
      else:
        self.fail("Exception not raised")

      # Once more with the whitelist
      mcpu._VerifyLocks(lu, glm, _mode_whitelist=[_FakeLuWithLocks],
                        _nal_whitelist=[])

  def testSameMode(self):
    for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
      lu = _FakeLuWithLocks({
        level: ["foo"],
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }, {
        level: 1,
        locking.LEVEL_NODE_ALLOC: 1,
        })
      glm = _FakeGlm(True)

      try:
        mcpu._VerifyLocks(lu, glm, _mode_whitelist=[_FakeLuWithLocks],
                          _nal_whitelist=[])
      except AssertionError, err:
        self.assertTrue("whitelisted to use different modes" in str(err))
      else:
        self.fail("Exception not raised")

      # Once more without the whitelist
      mcpu._VerifyLocks(lu, glm, _mode_whitelist=[], _nal_whitelist=[])

  def testAllWithoutAllocLock(self):
    for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
      lu = _FakeLuWithLocks({
        level: locking.ALL_SET,
        }, {
        level: 0,
        locking.LEVEL_NODE_ALLOC: 0,
        })
      glm = _FakeGlm(False)
      try:
        mcpu._VerifyLocks(lu, glm, _mode_whitelist=[], _nal_whitelist=[])
      except AssertionError, err:
        self.assertTrue("allocation lock must be used if" in str(err))
      else:
        self.fail("Exception not raised")

      # Once more with the whitelist
      mcpu._VerifyLocks(lu, glm, _mode_whitelist=[],
                        _nal_whitelist=[_FakeLuWithLocks])

  def testAllWithAllocLock(self):
    for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
      lu = _FakeLuWithLocks({
        level: locking.ALL_SET,
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }, {
        level: 0,
        locking.LEVEL_NODE_ALLOC: 0,
        })
      glm = _FakeGlm(True)

      try:
        mcpu._VerifyLocks(lu, glm, _mode_whitelist=[],
                          _nal_whitelist=[_FakeLuWithLocks])
      except AssertionError, err:
        self.assertTrue("whitelisted for not acquiring" in str(err))
      else:
        self.fail("Exception not raised")

      # Once more without the whitelist
      mcpu._VerifyLocks(lu, glm, _mode_whitelist=[], _nal_whitelist=[])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
