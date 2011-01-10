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

from ganeti import mcpu
from ganeti import opcodes

import testutils


class TestLockAttemptTimeoutStrategy(unittest.TestCase):
  def testConstants(self):
    tpa = mcpu.LockAttemptTimeoutStrategy._TIMEOUT_PER_ATTEMPT
    self.assert_(len(tpa) > 10)
    self.assert_(sum(tpa) >= 150.0)

  def testSimple(self):
    strat = mcpu.LockAttemptTimeoutStrategy(_random_fn=lambda: 0.5,
                                            _time_fn=lambda: 0.0)

    prev = None
    for i in range(len(strat._TIMEOUT_PER_ATTEMPT)):
      timeout = strat.NextAttempt()
      self.assert_(timeout is not None)

      self.assert_(timeout <= 10.0)
      self.assert_(timeout >= 0.0)
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
