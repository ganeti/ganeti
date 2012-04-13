#!/usr/bin/python
#

# Copyright (C) 2009, 2011 Google Inc.
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


"""Script for unittesting the mcpu module"""


import unittest
import itertools

from ganeti import mcpu
from ganeti import opcodes
from ganeti import cmdlib
from ganeti import constants
from ganeti.constants import \
    LOCK_ATTEMPTS_TIMEOUT, \
    LOCK_ATTEMPTS_MAXWAIT, \
    LOCK_ATTEMPTS_MINWAIT

import testutils


REQ_BGL_WHITELIST = frozenset([
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
