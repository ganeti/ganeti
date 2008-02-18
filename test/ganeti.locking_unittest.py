#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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
# 0.0510-1301, USA.


"""Script for unittesting the locking module"""


import os
import unittest
import time
import Queue

from ganeti import locking
from threading import Thread


class TestSharedLock(unittest.TestCase):
  """SharedLock tests"""

  def setUp(self):
    self.sl = locking.SharedLock()
    # helper threads use the 'done' queue to tell the master they finished.
    self.done = Queue.Queue(0)

  def testSequenceAndOwnership(self):
    self.assert_(not self.sl._is_owned())
    self.sl.acquire(shared=1)
    self.assert_(self.sl._is_owned())
    self.assert_(self.sl._is_owned(shared=1))
    self.assert_(not self.sl._is_owned(shared=0))
    self.sl.release()
    self.assert_(not self.sl._is_owned())
    self.sl.acquire()
    self.assert_(self.sl._is_owned())
    self.assert_(not self.sl._is_owned(shared=1))
    self.assert_(self.sl._is_owned(shared=0))
    self.sl.release()
    self.assert_(not self.sl._is_owned())
    self.sl.acquire(shared=1)
    self.assert_(self.sl._is_owned())
    self.assert_(self.sl._is_owned(shared=1))
    self.assert_(not self.sl._is_owned(shared=0))
    self.sl.release()
    self.assert_(not self.sl._is_owned())

  def testBooleanValue(self):
    # semaphores are supposed to return a true value on a successful acquire
    self.assert_(self.sl.acquire(shared=1))
    self.sl.release()
    self.assert_(self.sl.acquire())
    self.sl.release()

  def testDoubleLockingStoE(self):
    self.sl.acquire(shared=1)
    self.assertRaises(AssertionError, self.sl.acquire)

  def testDoubleLockingEtoS(self):
    self.sl.acquire()
    self.assertRaises(AssertionError, self.sl.acquire, shared=1)

  def testDoubleLockingStoS(self):
    self.sl.acquire(shared=1)
    self.assertRaises(AssertionError, self.sl.acquire, shared=1)

  def testDoubleLockingEtoE(self):
    self.sl.acquire()
    self.assertRaises(AssertionError, self.sl.acquire)

  # helper functions: called in a separate thread they acquire the lock, send
  # their identifier on the done queue, then release it.
  def _doItSharer(self):
    self.sl.acquire(shared=1)
    self.done.put('SHR')
    self.sl.release()

  def _doItExclusive(self):
    self.sl.acquire()
    self.done.put('EXC')
    self.sl.release()

  def testSharersCanCoexist(self):
    self.sl.acquire(shared=1)
    Thread(target=self._doItSharer).start()
    self.assert_(self.done.get(True, 1))
    self.sl.release()

  def testExclusiveBlocksExclusive(self):
    self.sl.acquire()
    Thread(target=self._doItExclusive).start()
    # give it a bit of time to check that it's not actually doing anything
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.sl.release()
    self.assert_(self.done.get(True, 1))

  def testExclusiveBlocksSharer(self):
    self.sl.acquire()
    Thread(target=self._doItSharer).start()
    time.sleep(0.05)
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.sl.release()
    self.assert_(self.done.get(True, 1))

  def testSharerBlocksExclusive(self):
    self.sl.acquire(shared=1)
    Thread(target=self._doItExclusive).start()
    time.sleep(0.05)
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.sl.release()
    self.assert_(self.done.get(True, 1))

  def testWaitingExclusiveBlocksSharer(self):
    self.sl.acquire(shared=1)
    # the lock is acquired in shared mode...
    Thread(target=self._doItExclusive).start()
    # ...but now an exclusive is waiting...
    time.sleep(0.05)
    Thread(target=self._doItSharer).start()
    # ...so the sharer should be blocked as well
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.sl.release()
    # The exclusive passed before
    self.assertEqual(self.done.get(True, 1), 'EXC')
    self.assertEqual(self.done.get(True, 1), 'SHR')

  def testWaitingSharerBlocksExclusive(self):
    self.sl.acquire()
    # the lock is acquired in exclusive mode...
    Thread(target=self._doItSharer).start()
    # ...but now a sharer is waiting...
    time.sleep(0.05)
    Thread(target=self._doItExclusive).start()
    # ...the exclusive is waiting too...
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.sl.release()
    # The sharer passed before
    self.assertEqual(self.done.get(True, 1), 'SHR')
    self.assertEqual(self.done.get(True, 1), 'EXC')


if __name__ == '__main__':
  unittest.main()
  #suite = unittest.TestLoader().loadTestsFromTestCase(TestSharedLock)
  #unittest.TextTestRunner(verbosity=2).run(suite)
