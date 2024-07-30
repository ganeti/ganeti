#!/usr/bin/python3
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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
    except errors.LockError as err:
      return False

    return True

  def _TryLock(self, *args):
    return utils.RunInSeparateProcess(self._TryLockInner, self.tmpfile.name,
                                      *args)

  def testTimeout(self):
    for blocking in [True, False]:
      self.lock.Exclusive(blocking=True)
      self.assertFalse(self._TryLock(False, blocking))
      self.assertFalse(self._TryLock(True, blocking))

      self.lock.Shared(blocking=True)
      self.assertTrue(self._TryLock(True, blocking))
      self.assertFalse(self._TryLock(False, blocking))

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
