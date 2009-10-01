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
import threading

from ganeti import locking
from ganeti import errors


# This is used to test the ssynchronize decorator.
# Since it's passed as input to a decorator it must be declared as a global.
_decoratorlock = locking.SharedLock()

#: List for looping tests
ITERATIONS = range(8)


def _Repeat(fn):
  """Decorator for executing a function many times"""
  def wrapper(*args, **kwargs):
    for i in ITERATIONS:
      fn(*args, **kwargs)
  return wrapper


class _ThreadedTestCase(unittest.TestCase):
  """Test class that supports adding/waiting on threads"""
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.done = Queue.Queue(0)
    self.threads = []

  def _addThread(self, *args, **kwargs):
    """Create and remember a new thread"""
    t = threading.Thread(*args, **kwargs)
    self.threads.append(t)
    t.start()
    return t

  def _waitThreads(self):
    """Wait for all our threads to finish"""
    for t in self.threads:
      t.join(60)
      self.failIf(t.isAlive())
    self.threads = []


class _ConditionTestCase(_ThreadedTestCase):
  """Common test case for conditions"""

  def setUp(self, cls):
    _ThreadedTestCase.setUp(self)
    self.lock = threading.Lock()
    self.cond = cls(self.lock)

  def _testAcquireRelease(self):
    self.assert_(not self.cond._is_owned())
    self.assertRaises(RuntimeError, self.cond.wait)
    self.assertRaises(RuntimeError, self.cond.notifyAll)

    self.cond.acquire()
    self.assert_(self.cond._is_owned())
    self.cond.notifyAll()
    self.assert_(self.cond._is_owned())
    self.cond.release()

    self.assert_(not self.cond._is_owned())
    self.assertRaises(RuntimeError, self.cond.wait)
    self.assertRaises(RuntimeError, self.cond.notifyAll)

  def _testNotification(self):
    def _NotifyAll():
      self.done.put("NE")
      self.cond.acquire()
      self.done.put("NA")
      self.cond.notifyAll()
      self.done.put("NN")
      self.cond.release()

    self.cond.acquire()
    self._addThread(target=_NotifyAll)
    self.assertEqual(self.done.get(True, 1), "NE")
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.cond.wait()
    self.assertEqual(self.done.get(True, 1), "NA")
    self.assertEqual(self.done.get(True, 1), "NN")
    self.assert_(self.cond._is_owned())
    self.cond.release()
    self.assert_(not self.cond._is_owned())


class TestPipeCondition(_ConditionTestCase):
  """_PipeCondition tests"""

  def setUp(self):
    _ConditionTestCase.setUp(self, locking._PipeCondition)

  def testAcquireRelease(self):
    self._testAcquireRelease()

  def testNotification(self):
    self._testNotification()

  def _TestWait(self, fn):
    self._addThread(target=fn)
    self._addThread(target=fn)
    self._addThread(target=fn)

    # Wait for threads to be waiting
    self.assertEqual(self.done.get(True, 1), "A")
    self.assertEqual(self.done.get(True, 1), "A")
    self.assertEqual(self.done.get(True, 1), "A")

    self.assertRaises(Queue.Empty, self.done.get_nowait)

    self.cond.acquire()
    self.assertEqual(self.cond._nwaiters, 3)
    # This new thread can"t acquire the lock, and thus call wait, before we
    # release it
    self._addThread(target=fn)
    self.cond.notifyAll()
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.cond.release()

    # We should now get 3 W and 1 A (for the new thread) in whatever order
    w = 0
    a = 0
    for i in range(4):
      got = self.done.get(True, 1)
      if got == "W":
        w += 1
      elif got == "A":
        a += 1
      else:
        self.fail("Got %s on the done queue" % got)

    self.assertEqual(w, 3)
    self.assertEqual(a, 1)

    self.cond.acquire()
    self.cond.notifyAll()
    self.cond.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "W")
    self.assertRaises(Queue.Empty, self.done.get_nowait)

  def testBlockingWait(self):
    def _BlockingWait():
      self.cond.acquire()
      self.done.put("A")
      self.cond.wait()
      self.cond.release()
      self.done.put("W")

    self._TestWait(_BlockingWait)

  def testLongTimeoutWait(self):
    def _Helper():
      self.cond.acquire()
      self.done.put("A")
      self.cond.wait(15.0)
      self.cond.release()
      self.done.put("W")

    self._TestWait(_Helper)

  def _TimeoutWait(self, timeout, check):
    self.cond.acquire()
    self.cond.wait(timeout)
    self.cond.release()
    self.done.put(check)

  def testShortTimeoutWait(self):
    self._addThread(target=self._TimeoutWait, args=(0.1, "T1"))
    self._addThread(target=self._TimeoutWait, args=(0.1, "T1"))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "T1")
    self.assertEqual(self.done.get_nowait(), "T1")
    self.assertRaises(Queue.Empty, self.done.get_nowait)

  def testZeroTimeoutWait(self):
    self._addThread(target=self._TimeoutWait, args=(0, "T0"))
    self._addThread(target=self._TimeoutWait, args=(0, "T0"))
    self._addThread(target=self._TimeoutWait, args=(0, "T0"))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "T0")
    self.assertEqual(self.done.get_nowait(), "T0")
    self.assertEqual(self.done.get_nowait(), "T0")
    self.assertRaises(Queue.Empty, self.done.get_nowait)


class TestSingleActionPipeCondition(unittest.TestCase):
  """_SingleActionPipeCondition tests"""

  def setUp(self):
    self.cond = locking._SingleActionPipeCondition()

  def testInitialization(self):
    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is not None)
    self.assert_(self.cond._poller is not None)
    self.assertEqual(self.cond._nwaiters, 0)

  def testUsageCount(self):
    self.cond.StartWaiting()
    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is not None)
    self.assert_(self.cond._poller is not None)
    self.assertEqual(self.cond._nwaiters, 1)

    # use again
    self.cond.StartWaiting()
    self.assertEqual(self.cond._nwaiters, 2)

    # there is more than one user
    self.assert_(not self.cond.DoneWaiting())
    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is not None)
    self.assert_(self.cond._poller is not None)
    self.assertEqual(self.cond._nwaiters, 1)

    self.assert_(self.cond.DoneWaiting())
    self.assertEqual(self.cond._nwaiters, 0)
    self.assert_(self.cond._read_fd is None)
    self.assert_(self.cond._write_fd is None)
    self.assert_(self.cond._poller is None)

  def testNotify(self):
    wait1 = self.cond.StartWaiting()
    wait2 = self.cond.StartWaiting()

    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is not None)
    self.assert_(self.cond._poller is not None)

    self.cond.notifyAll()

    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is None)
    self.assert_(self.cond._poller is not None)

    self.assert_(not self.cond.DoneWaiting())

    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is None)
    self.assert_(self.cond._poller is not None)

    self.assert_(self.cond.DoneWaiting())

    self.assert_(self.cond._read_fd is None)
    self.assert_(self.cond._write_fd is None)
    self.assert_(self.cond._poller is None)

  def testReusage(self):
    self.cond.StartWaiting()
    self.assert_(self.cond._read_fd is not None)
    self.assert_(self.cond._write_fd is not None)
    self.assert_(self.cond._poller is not None)

    self.assert_(self.cond.DoneWaiting())

    self.assertRaises(RuntimeError, self.cond.StartWaiting)
    self.assert_(self.cond._read_fd is None)
    self.assert_(self.cond._write_fd is None)
    self.assert_(self.cond._poller is None)

  def testNotifyTwice(self):
    self.cond.notifyAll()
    self.assertRaises(RuntimeError, self.cond.notifyAll)


class TestSharedLock(_ThreadedTestCase):
  """SharedLock tests"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self.sl = locking.SharedLock()

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
    try:
      self.sl.acquire(shared=1)
      self.done.put('SHR')
      self.sl.release()
    except errors.LockError:
      self.done.put('ERR')

  def _doItExclusive(self):
    try:
      self.sl.acquire()
      self.done.put('EXC')
      self.sl.release()
    except errors.LockError:
      self.done.put('ERR')

  def _doItDelete(self):
    try:
      self.sl.delete()
      self.done.put('DEL')
    except errors.LockError:
      self.done.put('ERR')

  def testSharersCanCoexist(self):
    self.sl.acquire(shared=1)
    threading.Thread(target=self._doItSharer).start()
    self.assert_(self.done.get(True, 1))
    self.sl.release()

  @_Repeat
  def testExclusiveBlocksExclusive(self):
    self.sl.acquire()
    self._addThread(target=self._doItExclusive)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'EXC')

  @_Repeat
  def testExclusiveBlocksDelete(self):
    self.sl.acquire()
    self._addThread(target=self._doItDelete)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'DEL')
    self.sl = locking.SharedLock()

  @_Repeat
  def testExclusiveBlocksSharer(self):
    self.sl.acquire()
    self._addThread(target=self._doItSharer)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'SHR')

  @_Repeat
  def testSharerBlocksExclusive(self):
    self.sl.acquire(shared=1)
    self._addThread(target=self._doItExclusive)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'EXC')

  @_Repeat
  def testSharerBlocksDelete(self):
    self.sl.acquire(shared=1)
    self._addThread(target=self._doItDelete)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'DEL')
    self.sl = locking.SharedLock()

  @_Repeat
  def testWaitingExclusiveBlocksSharer(self):
    """SKIPPED testWaitingExclusiveBlockSharer"""
    return

    self.sl.acquire(shared=1)
    # the lock is acquired in shared mode...
    self._addThread(target=self._doItExclusive)
    # ...but now an exclusive is waiting...
    self._addThread(target=self._doItSharer)
    # ...so the sharer should be blocked as well
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    # The exclusive passed before
    self.failUnlessEqual(self.done.get_nowait(), 'EXC')
    self.failUnlessEqual(self.done.get_nowait(), 'SHR')

  @_Repeat
  def testWaitingSharerBlocksExclusive(self):
    """SKIPPED testWaitingSharerBlocksExclusive"""
    return

    self.sl.acquire()
    # the lock is acquired in exclusive mode...
    self._addThread(target=self._doItSharer)
    # ...but now a sharer is waiting...
    self._addThread(target=self._doItExclusive)
    # ...the exclusive is waiting too...
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    # The sharer passed before
    self.assertEqual(self.done.get_nowait(), 'SHR')
    self.assertEqual(self.done.get_nowait(), 'EXC')

  def testDelete(self):
    self.sl.delete()
    self.assertRaises(errors.LockError, self.sl.acquire)
    self.assertRaises(errors.LockError, self.sl.acquire, shared=1)
    self.assertRaises(errors.LockError, self.sl.delete)

  def testDeleteTimeout(self):
    self.sl.delete(timeout=60)

  def testNoDeleteIfSharer(self):
    self.sl.acquire(shared=1)
    self.assertRaises(AssertionError, self.sl.delete)

  @_Repeat
  def testDeletePendingSharersExclusiveDelete(self):
    self.sl.acquire()
    self._addThread(target=self._doItSharer)
    self._addThread(target=self._doItSharer)
    self._addThread(target=self._doItExclusive)
    self._addThread(target=self._doItDelete)
    self.sl.delete()
    self._waitThreads()
    # The threads who were pending return ERR
    for _ in range(4):
      self.assertEqual(self.done.get_nowait(), 'ERR')
    self.sl = locking.SharedLock()

  @_Repeat
  def testDeletePendingDeleteExclusiveSharers(self):
    self.sl.acquire()
    self._addThread(target=self._doItDelete)
    self._addThread(target=self._doItExclusive)
    self._addThread(target=self._doItSharer)
    self._addThread(target=self._doItSharer)
    self.sl.delete()
    self._waitThreads()
    # The two threads who were pending return both ERR
    self.assertEqual(self.done.get_nowait(), 'ERR')
    self.assertEqual(self.done.get_nowait(), 'ERR')
    self.assertEqual(self.done.get_nowait(), 'ERR')
    self.assertEqual(self.done.get_nowait(), 'ERR')
    self.sl = locking.SharedLock()

  @_Repeat
  def testExclusiveAcquireTimeout(self):
    def _LockExclusive(wait):
      self.sl.acquire(shared=0)
      self.done.put("A: start sleep")
      time.sleep(wait)
      self.done.put("A: end sleep")
      self.sl.release()

    for shared in [0, 1]:
      # Start thread to hold lock for 20 ms
      self._addThread(target=_LockExclusive, args=(20.0 / 1000.0, ))

      # Wait for sleep to begin
      self.assertEqual(self.done.get(), "A: start sleep")

      # Wait up to 100 ms to get lock
      self.failUnless(self.sl.acquire(shared=shared, timeout=0.1))
      self.done.put("got 2nd")
      self.sl.release()

      self._waitThreads()

      self.assertEqual(self.done.get_nowait(), "A: end sleep")
      self.assertEqual(self.done.get_nowait(), "got 2nd")
      self.assertRaises(Queue.Empty, self.done.get_nowait)

  @_Repeat
  def testAcquireExpiringTimeout(self):
    def _AcquireWithTimeout(shared, timeout):
      if not self.sl.acquire(shared=shared, timeout=timeout):
        self.done.put("timeout")

    for shared in [0, 1]:
      # Lock exclusively
      self.sl.acquire()

      # Start shared acquires with timeout between 0 and 20 ms
      for i in xrange(11):
        self._addThread(target=_AcquireWithTimeout,
                        args=(shared, i * 2.0 / 1000.0))

      # Wait for threads to finish (makes sure the acquire timeout expires
      # before releasing the lock)
      self._waitThreads()

      # Release lock
      self.sl.release()

      for _ in xrange(11):
        self.assertEqual(self.done.get_nowait(), "timeout")

      self.assertRaises(Queue.Empty, self.done.get_nowait)

  @_Repeat
  def testSharedSkipExclusiveAcquires(self):
    # Tests whether shared acquires jump in front of exclusive acquires in the
    # queue.

    # Get exclusive lock while we fill the queue
    self.sl.acquire()

    def _Acquire(shared, name):
      if not self.sl.acquire(shared=shared):
        return

      self.done.put(name)
      self.sl.release()

    # Start shared acquires
    for _ in xrange(5):
      self._addThread(target=_Acquire, args=(1, "shared A"))

    # Start exclusive acquires
    for _ in xrange(3):
      self._addThread(target=_Acquire, args=(0, "exclusive B"))

    # More shared acquires
    for _ in xrange(5):
      self._addThread(target=_Acquire, args=(1, "shared C"))

    # More exclusive acquires
    for _ in xrange(3):
      self._addThread(target=_Acquire, args=(0, "exclusive D"))

    # Expect 6 pending exclusive acquires and 1 for all shared acquires
    # together. There's no way to wait for SharedLock.acquire to start
    # its work. Hence the timeout of 2 seconds.
    pending = 0
    end_time = time.time() + 2.0
    while time.time() < end_time:
      pending = self.sl._count_pending()
      self.assert_(pending >= 0 and pending <= 7)
      if pending == 7:
        break
      time.sleep(0.05)
    self.assertEqual(pending, 7)

    # Release exclusive lock and wait
    self.sl.release()

    self._waitThreads()

    # Check sequence
    shr_a = 0
    shr_c = 0
    for _ in xrange(10):
      # Shared locks aren't guaranteed to be notified in order, but they'll be
      # first
      tmp = self.done.get_nowait()
      if tmp == "shared A":
        shr_a += 1
      elif tmp == "shared C":
        shr_c += 1
    self.assertEqual(shr_a, 5)
    self.assertEqual(shr_c, 5)

    for _ in xrange(3):
      self.assertEqual(self.done.get_nowait(), "exclusive B")

    for _ in xrange(3):
      self.assertEqual(self.done.get_nowait(), "exclusive D")

    self.assertRaises(Queue.Empty, self.done.get_nowait)

  @_Repeat
  def testMixedAcquireTimeout(self):
    sync = threading.Condition()

    def _AcquireShared(ev):
      if not self.sl.acquire(shared=1, timeout=None):
        return

      self.done.put("shared")

      # Notify main thread
      ev.set()

      # Wait for notification
      sync.acquire()
      try:
        sync.wait()
      finally:
        sync.release()

      # Release lock
      self.sl.release()

    acquires = []
    for _ in xrange(3):
      ev = threading.Event()
      self._addThread(target=_AcquireShared, args=(ev, ))
      acquires.append(ev)

    # Wait for all acquires to finish
    for i in acquires:
      i.wait()

    self.assertEqual(self.sl._count_pending(), 0)

    # Try to get exclusive lock
    self.failIf(self.sl.acquire(shared=0, timeout=0.02))

    # Acquire exclusive without timeout
    exclsync = threading.Condition()
    exclev = threading.Event()

    def _AcquireExclusive():
      if not self.sl.acquire(shared=0):
        return

      self.done.put("exclusive")

      # Notify main thread
      exclev.set()

      exclsync.acquire()
      try:
        exclsync.wait()
      finally:
        exclsync.release()

      self.sl.release()

    self._addThread(target=_AcquireExclusive)

    # Try to get exclusive lock
    self.failIf(self.sl.acquire(shared=0, timeout=0.02))

    # Make all shared holders release their locks
    sync.acquire()
    try:
      sync.notifyAll()
    finally:
      sync.release()

    # Wait for exclusive acquire to succeed
    exclev.wait()

    self.assertEqual(self.sl._count_pending(), 0)

    # Try to get exclusive lock
    self.failIf(self.sl.acquire(shared=0, timeout=0.02))

    def _AcquireSharedSimple():
      if self.sl.acquire(shared=1, timeout=None):
        self.done.put("shared2")
        self.sl.release()

    for _ in xrange(10):
      self._addThread(target=_AcquireSharedSimple)

    # Tell exclusive lock to release
    exclsync.acquire()
    try:
      exclsync.notifyAll()
    finally:
      exclsync.release()

    # Wait for everything to finish
    self._waitThreads()

    self.assertEqual(self.sl._count_pending(), 0)

    # Check sequence
    for _ in xrange(3):
      self.assertEqual(self.done.get_nowait(), "shared")

    self.assertEqual(self.done.get_nowait(), "exclusive")

    for _ in xrange(10):
      self.assertEqual(self.done.get_nowait(), "shared2")

    self.assertRaises(Queue.Empty, self.done.get_nowait)


class TestSSynchronizedDecorator(_ThreadedTestCase):
  """Shared Lock Synchronized decorator test"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)

  @locking.ssynchronized(_decoratorlock)
  def _doItExclusive(self):
    self.assert_(_decoratorlock._is_owned())
    self.done.put('EXC')

  @locking.ssynchronized(_decoratorlock, shared=1)
  def _doItSharer(self):
    self.assert_(_decoratorlock._is_owned(shared=1))
    self.done.put('SHR')

  def testDecoratedFunctions(self):
    self._doItExclusive()
    self.assert_(not _decoratorlock._is_owned())
    self._doItSharer()
    self.assert_(not _decoratorlock._is_owned())

  def testSharersCanCoexist(self):
    _decoratorlock.acquire(shared=1)
    threading.Thread(target=self._doItSharer).start()
    self.assert_(self.done.get(True, 1))
    _decoratorlock.release()

  @_Repeat
  def testExclusiveBlocksExclusive(self):
    _decoratorlock.acquire()
    self._addThread(target=self._doItExclusive)
    # give it a bit of time to check that it's not actually doing anything
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'EXC')

  @_Repeat
  def testExclusiveBlocksSharer(self):
    _decoratorlock.acquire()
    self._addThread(target=self._doItSharer)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'SHR')

  @_Repeat
  def testSharerBlocksExclusive(self):
    _decoratorlock.acquire(shared=1)
    self._addThread(target=self._doItExclusive)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), 'EXC')


class TestLockSet(_ThreadedTestCase):
  """LockSet tests"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self._setUpLS()

  def _setUpLS(self):
    """Helper to (re)initialize the lock set"""
    self.resources = ['one', 'two', 'three']
    self.ls = locking.LockSet(members=self.resources)

  def testResources(self):
    self.assertEquals(self.ls._names(), set(self.resources))
    newls = locking.LockSet()
    self.assertEquals(newls._names(), set())

  def testAcquireRelease(self):
    self.assert_(self.ls.acquire('one'))
    self.assertEquals(self.ls._list_owned(), set(['one']))
    self.ls.release()
    self.assertEquals(self.ls._list_owned(), set())
    self.assertEquals(self.ls.acquire(['one']), set(['one']))
    self.assertEquals(self.ls._list_owned(), set(['one']))
    self.ls.release()
    self.assertEquals(self.ls._list_owned(), set())
    self.ls.acquire(['one', 'two', 'three'])
    self.assertEquals(self.ls._list_owned(), set(['one', 'two', 'three']))
    self.ls.release('one')
    self.assertEquals(self.ls._list_owned(), set(['two', 'three']))
    self.ls.release(['three'])
    self.assertEquals(self.ls._list_owned(), set(['two']))
    self.ls.release()
    self.assertEquals(self.ls._list_owned(), set())
    self.assertEquals(self.ls.acquire(['one', 'three']), set(['one', 'three']))
    self.assertEquals(self.ls._list_owned(), set(['one', 'three']))
    self.ls.release()
    self.assertEquals(self.ls._list_owned(), set())

  def testNoDoubleAcquire(self):
    self.ls.acquire('one')
    self.assertRaises(AssertionError, self.ls.acquire, 'one')
    self.assertRaises(AssertionError, self.ls.acquire, ['two'])
    self.assertRaises(AssertionError, self.ls.acquire, ['two', 'three'])
    self.ls.release()
    self.ls.acquire(['one', 'three'])
    self.ls.release('one')
    self.assertRaises(AssertionError, self.ls.acquire, ['two'])
    self.ls.release('three')

  def testNoWrongRelease(self):
    self.assertRaises(AssertionError, self.ls.release)
    self.ls.acquire('one')
    self.assertRaises(AssertionError, self.ls.release, 'two')

  def testAddRemove(self):
    self.ls.add('four')
    self.assertEquals(self.ls._list_owned(), set())
    self.assert_('four' in self.ls._names())
    self.ls.add(['five', 'six', 'seven'], acquired=1)
    self.assert_('five' in self.ls._names())
    self.assert_('six' in self.ls._names())
    self.assert_('seven' in self.ls._names())
    self.assertEquals(self.ls._list_owned(), set(['five', 'six', 'seven']))
    self.assertEquals(self.ls.remove(['five', 'six']), ['five', 'six'])
    self.assert_('five' not in self.ls._names())
    self.assert_('six' not in self.ls._names())
    self.assertEquals(self.ls._list_owned(), set(['seven']))
    self.assertRaises(AssertionError, self.ls.add, 'eight', acquired=1)
    self.ls.remove('seven')
    self.assert_('seven' not in self.ls._names())
    self.assertEquals(self.ls._list_owned(), set([]))
    self.ls.acquire(None, shared=1)
    self.assertRaises(AssertionError, self.ls.add, 'eight')
    self.ls.release()
    self.ls.acquire(None)
    self.ls.add('eight', acquired=1)
    self.assert_('eight' in self.ls._names())
    self.assert_('eight' in self.ls._list_owned())
    self.ls.add('nine')
    self.assert_('nine' in self.ls._names())
    self.assert_('nine' not in self.ls._list_owned())
    self.ls.release()
    self.ls.remove(['two'])
    self.assert_('two' not in self.ls._names())
    self.ls.acquire('three')
    self.assertEquals(self.ls.remove(['three']), ['three'])
    self.assert_('three' not in self.ls._names())
    self.assertEquals(self.ls.remove('three'), [])
    self.assertEquals(self.ls.remove(['one', 'three', 'six']), ['one'])
    self.assert_('one' not in self.ls._names())

  def testRemoveNonBlocking(self):
    self.ls.acquire('one')
    self.assertEquals(self.ls.remove('one'), ['one'])
    self.ls.acquire(['two', 'three'])
    self.assertEquals(self.ls.remove(['two', 'three']),
                      ['two', 'three'])

  def testNoDoubleAdd(self):
    self.assertRaises(errors.LockError, self.ls.add, 'two')
    self.ls.add('four')
    self.assertRaises(errors.LockError, self.ls.add, 'four')

  def testNoWrongRemoves(self):
    self.ls.acquire(['one', 'three'], shared=1)
    # Cannot remove 'two' while holding something which is not a superset
    self.assertRaises(AssertionError, self.ls.remove, 'two')
    # Cannot remove 'three' as we are sharing it
    self.assertRaises(AssertionError, self.ls.remove, 'three')

  def testAcquireSetLock(self):
    # acquire the set-lock exclusively
    self.assertEquals(self.ls.acquire(None), set(['one', 'two', 'three']))
    self.assertEquals(self.ls._list_owned(), set(['one', 'two', 'three']))
    self.assertEquals(self.ls._is_owned(), True)
    self.assertEquals(self.ls._names(), set(['one', 'two', 'three']))
    # I can still add/remove elements...
    self.assertEquals(self.ls.remove(['two', 'three']), ['two', 'three'])
    self.assert_(self.ls.add('six'))
    self.ls.release()
    # share the set-lock
    self.assertEquals(self.ls.acquire(None, shared=1), set(['one', 'six']))
    # adding new elements is not possible
    self.assertRaises(AssertionError, self.ls.add, 'five')
    self.ls.release()

  def testAcquireWithRepetitions(self):
    self.assertEquals(self.ls.acquire(['two', 'two', 'three'], shared=1),
                      set(['two', 'two', 'three']))
    self.ls.release(['two', 'two'])
    self.assertEquals(self.ls._list_owned(), set(['three']))

  def testEmptyAcquire(self):
    # Acquire an empty list of locks...
    self.assertEquals(self.ls.acquire([]), set())
    self.assertEquals(self.ls._list_owned(), set())
    # New locks can still be addded
    self.assert_(self.ls.add('six'))
    # "re-acquiring" is not an issue, since we had really acquired nothing
    self.assertEquals(self.ls.acquire([], shared=1), set())
    self.assertEquals(self.ls._list_owned(), set())
    # We haven't really acquired anything, so we cannot release
    self.assertRaises(AssertionError, self.ls.release)

  def _doLockSet(self, names, shared):
    try:
      self.ls.acquire(names, shared=shared)
      self.done.put('DONE')
      self.ls.release()
    except errors.LockError:
      self.done.put('ERR')

  def _doAddSet(self, names):
    try:
      self.ls.add(names, acquired=1)
      self.done.put('DONE')
      self.ls.release()
    except errors.LockError:
      self.done.put('ERR')

  def _doRemoveSet(self, names):
    self.done.put(self.ls.remove(names))

  @_Repeat
  def testConcurrentSharedAcquire(self):
    self.ls.acquire(['one', 'two'], shared=1)
    self._addThread(target=self._doLockSet, args=(['one', 'two'], 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doLockSet, args=(['one', 'two', 'three'], 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doLockSet, args=('three', 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doLockSet, args=(['one', 'two'], 0))
    self._addThread(target=self._doLockSet, args=(['two', 'three'], 0))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.assertEqual(self.done.get_nowait(), 'DONE')

  @_Repeat
  def testConcurrentExclusiveAcquire(self):
    self.ls.acquire(['one', 'two'])
    self._addThread(target=self._doLockSet, args=('three', 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doLockSet, args=('three', 0))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self._addThread(target=self._doLockSet, args=(['one', 'two'], 0))
    self._addThread(target=self._doLockSet, args=(['one', 'two'], 1))
    self._addThread(target=self._doLockSet, args=('one', 0))
    self._addThread(target=self._doLockSet, args=('one', 1))
    self._addThread(target=self._doLockSet, args=(['two', 'three'], 0))
    self._addThread(target=self._doLockSet, args=(['two', 'three'], 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    for _ in range(6):
      self.failUnlessEqual(self.done.get_nowait(), 'DONE')

  @_Repeat
  def testConcurrentRemove(self):
    self.ls.add('four')
    self.ls.acquire(['one', 'two', 'four'])
    self._addThread(target=self._doLockSet, args=(['one', 'four'], 0))
    self._addThread(target=self._doLockSet, args=(['one', 'four'], 1))
    self._addThread(target=self._doLockSet, args=(['one', 'two'], 0))
    self._addThread(target=self._doLockSet, args=(['one', 'two'], 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.remove('one')
    self.ls.release()
    self._waitThreads()
    for i in range(4):
      self.failUnlessEqual(self.done.get_nowait(), 'ERR')
    self.ls.add(['five', 'six'], acquired=1)
    self._addThread(target=self._doLockSet, args=(['three', 'six'], 1))
    self._addThread(target=self._doLockSet, args=(['three', 'six'], 0))
    self._addThread(target=self._doLockSet, args=(['four', 'six'], 1))
    self._addThread(target=self._doLockSet, args=(['four', 'six'], 0))
    self.ls.remove('five')
    self.ls.release()
    self._waitThreads()
    for i in range(4):
      self.failUnlessEqual(self.done.get_nowait(), 'DONE')
    self.ls.acquire(['three', 'four'])
    self._addThread(target=self._doRemoveSet, args=(['four', 'six'], ))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.remove('four')
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), ['six'])
    self._addThread(target=self._doRemoveSet, args=(['two']))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), ['two'])
    self.ls.release()
    # reset lockset
    self._setUpLS()

  @_Repeat
  def testConcurrentSharedSetLock(self):
    # share the set-lock...
    self.ls.acquire(None, shared=1)
    # ...another thread can share it too
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    # ...or just share some elements
    self._addThread(target=self._doLockSet, args=(['one', 'three'], 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    # ...but not add new ones or remove any
    t = self._addThread(target=self._doAddSet, args=(['nine']))
    self._addThread(target=self._doRemoveSet, args=(['two'], ))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    # this just releases the set-lock
    self.ls.release([])
    t.join(60)
    self.assertEqual(self.done.get_nowait(), 'DONE')
    # release the lock on the actual elements so remove() can proceed too
    self.ls.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), ['two'])
    # reset lockset
    self._setUpLS()

  @_Repeat
  def testConcurrentExclusiveSetLock(self):
    # acquire the set-lock...
    self.ls.acquire(None, shared=0)
    # ...no one can do anything else
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._addThread(target=self._doLockSet, args=(None, 0))
    self._addThread(target=self._doLockSet, args=(['three'], 0))
    self._addThread(target=self._doLockSet, args=(['two'], 1))
    self._addThread(target=self._doAddSet, args=(['nine']))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    for _ in range(5):
      self.assertEqual(self.done.get(True, 1), 'DONE')
    # cleanup
    self._setUpLS()

  @_Repeat
  def testConcurrentSetLockAdd(self):
    self.ls.acquire('one')
    # Another thread wants the whole SetLock
    self._addThread(target=self._doLockSet, args=(None, 0))
    self._addThread(target=self._doLockSet, args=(None, 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.assertRaises(AssertionError, self.ls.add, 'four')
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.ls.acquire(None)
    self._addThread(target=self._doLockSet, args=(None, 0))
    self._addThread(target=self._doLockSet, args=(None, 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.add('four')
    self.ls.add('five', acquired=1)
    self.ls.add('six', acquired=1, shared=1)
    self.assertEquals(self.ls._list_owned(),
      set(['one', 'two', 'three', 'five', 'six']))
    self.assertEquals(self.ls._is_owned(), True)
    self.assertEquals(self.ls._names(),
      set(['one', 'two', 'three', 'four', 'five', 'six']))
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._setUpLS()

  @_Repeat
  def testEmptyLockSet(self):
    # get the set-lock
    self.assertEqual(self.ls.acquire(None), set(['one', 'two', 'three']))
    # now empty it...
    self.ls.remove(['one', 'two', 'three'])
    # and adds/locks by another thread still wait
    self._addThread(target=self._doAddSet, args=(['nine']))
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._addThread(target=self._doLockSet, args=(None, 0))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    for _ in range(3):
      self.assertEqual(self.done.get_nowait(), 'DONE')
    # empty it again...
    self.assertEqual(self.ls.remove(['nine']), ['nine'])
    # now share it...
    self.assertEqual(self.ls.acquire(None, shared=1), set())
    # other sharers can go, adds still wait
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doAddSet, args=(['nine']))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._setUpLS()


class TestGanetiLockManager(_ThreadedTestCase):

  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self.nodes=['n1', 'n2']
    self.instances=['i1', 'i2', 'i3']
    self.GL = locking.GanetiLockManager(nodes=self.nodes,
                                        instances=self.instances)

  def tearDown(self):
    # Don't try this at home...
    locking.GanetiLockManager._instance = None

  def testLockingConstants(self):
    # The locking library internally cheats by assuming its constants have some
    # relationships with each other. Check those hold true.
    # This relationship is also used in the Processor to recursively acquire
    # the right locks. Again, please don't break it.
    for i in range(len(locking.LEVELS)):
      self.assertEqual(i, locking.LEVELS[i])

  def testDoubleGLFails(self):
    self.assertRaises(AssertionError, locking.GanetiLockManager)

  def testLockNames(self):
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(['BGL']))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set(self.nodes))
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE),
                     set(self.instances))

  def testInitAndResources(self):
    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager()
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(['BGL']))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE), set())

    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager(nodes=self.nodes)
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(['BGL']))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set(self.nodes))
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE), set())

    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager(instances=self.instances)
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(['BGL']))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE),
                     set(self.instances))

  def testAcquireRelease(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
    self.assertEquals(self.GL._list_owned(locking.LEVEL_CLUSTER), set(['BGL']))
    self.GL.acquire(locking.LEVEL_INSTANCE, ['i1'])
    self.GL.acquire(locking.LEVEL_NODE, ['n1', 'n2'], shared=1)
    self.GL.release(locking.LEVEL_NODE, ['n2'])
    self.assertEquals(self.GL._list_owned(locking.LEVEL_NODE), set(['n1']))
    self.assertEquals(self.GL._list_owned(locking.LEVEL_INSTANCE), set(['i1']))
    self.GL.release(locking.LEVEL_NODE)
    self.assertEquals(self.GL._list_owned(locking.LEVEL_NODE), set())
    self.assertEquals(self.GL._list_owned(locking.LEVEL_INSTANCE), set(['i1']))
    self.GL.release(locking.LEVEL_INSTANCE)
    self.assertRaises(errors.LockError, self.GL.acquire,
                      locking.LEVEL_INSTANCE, ['i5'])
    self.GL.acquire(locking.LEVEL_INSTANCE, ['i3'], shared=1)
    self.assertEquals(self.GL._list_owned(locking.LEVEL_INSTANCE), set(['i3']))

  def testAcquireWholeSets(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
    self.assertEquals(self.GL.acquire(locking.LEVEL_INSTANCE, None),
                      set(self.instances))
    self.assertEquals(self.GL._list_owned(locking.LEVEL_INSTANCE),
                      set(self.instances))
    self.assertEquals(self.GL.acquire(locking.LEVEL_NODE, None, shared=1),
                      set(self.nodes))
    self.assertEquals(self.GL._list_owned(locking.LEVEL_NODE),
                      set(self.nodes))
    self.GL.release(locking.LEVEL_NODE)
    self.GL.release(locking.LEVEL_INSTANCE)
    self.GL.release(locking.LEVEL_CLUSTER)

  def testAcquireWholeAndPartial(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
    self.assertEquals(self.GL.acquire(locking.LEVEL_INSTANCE, None),
                      set(self.instances))
    self.assertEquals(self.GL._list_owned(locking.LEVEL_INSTANCE),
                      set(self.instances))
    self.assertEquals(self.GL.acquire(locking.LEVEL_NODE, ['n2'], shared=1),
                      set(['n2']))
    self.assertEquals(self.GL._list_owned(locking.LEVEL_NODE),
                      set(['n2']))
    self.GL.release(locking.LEVEL_NODE)
    self.GL.release(locking.LEVEL_INSTANCE)
    self.GL.release(locking.LEVEL_CLUSTER)

  def testBGLDependency(self):
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_NODE, ['n1', 'n2'])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_INSTANCE, ['i3'])
    self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
    self.GL.acquire(locking.LEVEL_NODE, ['n1'])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER, ['BGL'])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER)
    self.GL.release(locking.LEVEL_NODE)
    self.GL.acquire(locking.LEVEL_INSTANCE, ['i1', 'i2'])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER, ['BGL'])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER)
    self.GL.release(locking.LEVEL_INSTANCE)

  def testWrongOrder(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
    self.GL.acquire(locking.LEVEL_NODE, ['n2'])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_NODE, ['n1'])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_INSTANCE, ['i2'])

  # Helper function to run as a thread that shared the BGL and then acquires
  # some locks at another level.
  def _doLock(self, level, names, shared):
    try:
      self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
      self.GL.acquire(level, names, shared=shared)
      self.done.put('DONE')
      self.GL.release(level)
      self.GL.release(locking.LEVEL_CLUSTER)
    except errors.LockError:
      self.done.put('ERR')

  @_Repeat
  def testConcurrency(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ['BGL'], shared=1)
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, 'i1', 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.GL.acquire(locking.LEVEL_INSTANCE, ['i3'])
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, 'i1', 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, 'i3', 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.GL.release(locking.LEVEL_INSTANCE)
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self.GL.acquire(locking.LEVEL_INSTANCE, ['i2'], shared=1)
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, 'i2', 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), 'DONE')
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, 'i2', 0))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.GL.release(locking.LEVEL_INSTANCE)
    self._waitThreads()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.GL.release(locking.LEVEL_CLUSTER, ['BGL'])


if __name__ == '__main__':
  unittest.main()
  #suite = unittest.TestLoader().loadTestsFromTestCase(TestSharedLock)
  #unittest.TextTestRunner(verbosity=2).run(suite)
