#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Script for testing ganeti.utils.filelock"""

import os
import tempfile
import unittest

from ganeti import constants
from ganeti import utils
from ganeti import errors

import testutils


class _BaseFileLockTest:
  """Test case for the FileLock class"""

  def testSharedNonblocking(self):
    self.lock.Shared(blocking=False)
    self.lock.Close()

  def testExclusiveNonblocking(self):
    self.lock.Exclusive(blocking=False)
    self.lock.Close()

  def testUnlockNonblocking(self):
    self.lock.Unlock(blocking=False)
    self.lock.Close()

  def testSharedBlocking(self):
    self.lock.Shared(blocking=True)
    self.lock.Close()

  def testExclusiveBlocking(self):
    self.lock.Exclusive(blocking=True)
    self.lock.Close()

  def testUnlockBlocking(self):
    self.lock.Unlock(blocking=True)
    self.lock.Close()

  def testSharedExclusiveUnlock(self):
    self.lock.Shared(blocking=False)
    self.lock.Exclusive(blocking=False)
    self.lock.Unlock(blocking=False)
    self.lock.Close()

  def testExclusiveSharedUnlock(self):
    self.lock.Exclusive(blocking=False)
    self.lock.Shared(blocking=False)
    self.lock.Unlock(blocking=False)
    self.lock.Close()

  def testSimpleTimeout(self):
    # These will succeed on the first attempt, hence a short timeout
    self.lock.Shared(blocking=True, timeout=10.0)
    self.lock.Exclusive(blocking=False, timeout=10.0)
    self.lock.Unlock(blocking=True, timeout=10.0)
    self.lock.Close()

  @staticmethod
  def _TryLockInner(filename, shared, blocking):
    lock = utils.FileLock.Open(filename)

    if shared:
      fn = lock.Shared
    else:
      fn = lock.Exclusive

    try:
      # The timeout doesn't really matter as the parent process waits for us to
      # finish anyway.
      fn(blocking=blocking, timeout=0.01)
    except errors.LockError, err:
      return False

    return True

  def _TryLock(self, *args):
    return utils.RunInSeparateProcess(self._TryLockInner, self.tmpfile.name,
                                      *args)

  def testTimeout(self):
    for blocking in [True, False]:
      self.lock.Exclusive(blocking=True)
      self.failIf(self._TryLock(False, blocking))
      self.failIf(self._TryLock(True, blocking))

      self.lock.Shared(blocking=True)
      self.assert_(self._TryLock(True, blocking))
      self.failIf(self._TryLock(False, blocking))

  def testCloseShared(self):
    self.lock.Close()
    self.assertRaises(AssertionError, self.lock.Shared, blocking=False)

  def testCloseExclusive(self):
    self.lock.Close()
    self.assertRaises(AssertionError, self.lock.Exclusive, blocking=False)

  def testCloseUnlock(self):
    self.lock.Close()
    self.assertRaises(AssertionError, self.lock.Unlock, blocking=False)


class TestFileLockWithFilename(testutils.GanetiTestCase, _BaseFileLockTest):
  TESTDATA = "Hello World\n" * 10

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpfile = tempfile.NamedTemporaryFile()
    utils.WriteFile(self.tmpfile.name, data=self.TESTDATA)
    self.lock = utils.FileLock.Open(self.tmpfile.name)

    # Ensure "Open" didn't truncate file
    self.assertFileContent(self.tmpfile.name, self.TESTDATA)

  def tearDown(self):
    self.assertFileContent(self.tmpfile.name, self.TESTDATA)

    testutils.GanetiTestCase.tearDown(self)


class TestFileLockWithFileObject(unittest.TestCase, _BaseFileLockTest):
  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    self.lock = utils.FileLock(open(self.tmpfile.name, "w"), self.tmpfile.name)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
