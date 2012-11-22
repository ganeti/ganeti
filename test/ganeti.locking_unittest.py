#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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


"""Script for unittesting the locking module"""


import os
import unittest
import time
import Queue
import threading
import random
import gc
import itertools

from ganeti import constants
from ganeti import locking
from ganeti import errors
from ganeti import utils
from ganeti import compat
from ganeti import objects
from ganeti import query

import testutils


# This is used to test the ssynchronize decorator.
# Since it's passed as input to a decorator it must be declared as a global.
_decoratorlock = locking.SharedLock("decorator lock")

#: List for looping tests
ITERATIONS = range(8)


def _Repeat(fn):
  """Decorator for executing a function many times"""
  def wrapper(*args, **kwargs):
    for i in ITERATIONS:
      fn(*args, **kwargs)
  return wrapper


def SafeSleep(duration):
  start = time.time()
  while True:
    delay = start + duration - time.time()
    if delay <= 0.0:
      break
    time.sleep(delay)


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
    self.assertFalse(self.cond._is_owned())
    self.assertRaises(RuntimeError, self.cond.wait, None)
    self.assertRaises(RuntimeError, self.cond.notifyAll)

    self.cond.acquire()
    self.assert_(self.cond._is_owned())
    self.cond.notifyAll()
    self.assert_(self.cond._is_owned())
    self.cond.release()

    self.assertFalse(self.cond._is_owned())
    self.assertRaises(RuntimeError, self.cond.wait, None)
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
    self.cond.wait(None)
    self.assertEqual(self.done.get(True, 1), "NA")
    self.assertEqual(self.done.get(True, 1), "NN")
    self.assert_(self.cond._is_owned())
    self.cond.release()
    self.assertFalse(self.cond._is_owned())


class TestSingleNotifyPipeCondition(_ConditionTestCase):
  """SingleNotifyPipeCondition tests"""

  def setUp(self):
    _ConditionTestCase.setUp(self, locking.SingleNotifyPipeCondition)

  def testAcquireRelease(self):
    self._testAcquireRelease()

  def testNotification(self):
    self._testNotification()

  def testWaitReuse(self):
    self.cond.acquire()
    self.cond.wait(0)
    self.cond.wait(0.1)
    self.cond.release()

  def testNoNotifyReuse(self):
    self.cond.acquire()
    self.cond.notifyAll()
    self.assertRaises(RuntimeError, self.cond.wait, None)
    self.assertRaises(RuntimeError, self.cond.notifyAll)
    self.cond.release()


class TestPipeCondition(_ConditionTestCase):
  """PipeCondition tests"""

  def setUp(self):
    _ConditionTestCase.setUp(self, locking.PipeCondition)

  def testAcquireRelease(self):
    self._testAcquireRelease()

  def testNotification(self):
    self._testNotification()

  def _TestWait(self, fn):
    threads = [
      self._addThread(target=fn),
      self._addThread(target=fn),
      self._addThread(target=fn),
      ]

    # Wait for threads to be waiting
    for _ in threads:
      self.assertEqual(self.done.get(True, 1), "A")

    self.assertRaises(Queue.Empty, self.done.get_nowait)

    self.cond.acquire()
    self.assertEqual(len(self.cond._waiters), 3)
    self.assertEqual(self.cond._waiters, set(threads))

    self.assertTrue(repr(self.cond).startswith("<"))
    self.assertTrue("waiters=" in repr(self.cond))

    # This new thread can't acquire the lock, and thus call wait, before we
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
      self.cond.wait(None)
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


class TestSharedLock(_ThreadedTestCase):
  """SharedLock tests"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self.sl = locking.SharedLock("TestSharedLock")

    self.assertTrue(repr(self.sl).startswith("<"))
    self.assertTrue("name=TestSharedLock" in repr(self.sl))

  def testSequenceAndOwnership(self):
    self.assertFalse(self.sl.is_owned())
    self.sl.acquire(shared=1)
    self.assert_(self.sl.is_owned())
    self.assert_(self.sl.is_owned(shared=1))
    self.assertFalse(self.sl.is_owned(shared=0))
    self.sl.release()
    self.assertFalse(self.sl.is_owned())
    self.sl.acquire()
    self.assert_(self.sl.is_owned())
    self.assertFalse(self.sl.is_owned(shared=1))
    self.assert_(self.sl.is_owned(shared=0))
    self.sl.release()
    self.assertFalse(self.sl.is_owned())
    self.sl.acquire(shared=1)
    self.assert_(self.sl.is_owned())
    self.assert_(self.sl.is_owned(shared=1))
    self.assertFalse(self.sl.is_owned(shared=0))
    self.sl.release()
    self.assertFalse(self.sl.is_owned())

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
      self.done.put("SHR")
      self.sl.release()
    except errors.LockError:
      self.done.put("ERR")

  def _doItExclusive(self):
    try:
      self.sl.acquire()
      self.done.put("EXC")
      self.sl.release()
    except errors.LockError:
      self.done.put("ERR")

  def _doItDelete(self):
    try:
      self.sl.delete()
      self.done.put("DEL")
    except errors.LockError:
      self.done.put("ERR")

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
    self.failUnlessEqual(self.done.get_nowait(), "EXC")

  @_Repeat
  def testExclusiveBlocksDelete(self):
    self.sl.acquire()
    self._addThread(target=self._doItDelete)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), "DEL")
    self.sl = locking.SharedLock(self.sl.name)

  @_Repeat
  def testExclusiveBlocksSharer(self):
    self.sl.acquire()
    self._addThread(target=self._doItSharer)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), "SHR")

  @_Repeat
  def testSharerBlocksExclusive(self):
    self.sl.acquire(shared=1)
    self._addThread(target=self._doItExclusive)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), "EXC")

  @_Repeat
  def testSharerBlocksDelete(self):
    self.sl.acquire(shared=1)
    self._addThread(target=self._doItDelete)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), "DEL")
    self.sl = locking.SharedLock(self.sl.name)

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
    self.failUnlessEqual(self.done.get_nowait(), "EXC")
    self.failUnlessEqual(self.done.get_nowait(), "SHR")

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
    self.assertEqual(self.done.get_nowait(), "SHR")
    self.assertEqual(self.done.get_nowait(), "EXC")

  def testDelete(self):
    self.sl.delete()
    self.assertRaises(errors.LockError, self.sl.acquire)
    self.assertRaises(errors.LockError, self.sl.acquire, shared=1)
    self.assertRaises(errors.LockError, self.sl.delete)

  def testDeleteTimeout(self):
    self.assertTrue(self.sl.delete(timeout=60))

  def testDeleteTimeoutFail(self):
    ready = threading.Event()
    finish = threading.Event()

    def fn():
      self.sl.acquire(shared=0)
      ready.set()

      finish.wait()
      self.sl.release()

    self._addThread(target=fn)
    ready.wait()

    # Test if deleting a lock owned in exclusive mode by another thread fails
    # to delete when a timeout is used
    self.assertFalse(self.sl.delete(timeout=0.02))

    finish.set()
    self._waitThreads()

    self.assertTrue(self.sl.delete())
    self.assertRaises(errors.LockError, self.sl.acquire)

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
      self.assertEqual(self.done.get_nowait(), "ERR")
    self.sl = locking.SharedLock(self.sl.name)

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
    self.assertEqual(self.done.get_nowait(), "ERR")
    self.assertEqual(self.done.get_nowait(), "ERR")
    self.assertEqual(self.done.get_nowait(), "ERR")
    self.assertEqual(self.done.get_nowait(), "ERR")
    self.sl = locking.SharedLock(self.sl.name)

  @_Repeat
  def testExclusiveAcquireTimeout(self):
    for shared in [0, 1]:
      on_queue = threading.Event()
      release_exclusive = threading.Event()

      def _LockExclusive():
        self.sl.acquire(shared=0, test_notify=on_queue.set)
        self.done.put("A: start wait")
        release_exclusive.wait()
        self.done.put("A: end wait")
        self.sl.release()

      # Start thread to hold lock in exclusive mode
      self._addThread(target=_LockExclusive)

      # Wait for wait to begin
      self.assertEqual(self.done.get(timeout=60), "A: start wait")

      # Wait up to 60s to get lock, but release exclusive lock as soon as we're
      # on the queue
      self.failUnless(self.sl.acquire(shared=shared, timeout=60,
                                      test_notify=release_exclusive.set))

      self.done.put("got 2nd")
      self.sl.release()

      self._waitThreads()

      self.assertEqual(self.done.get_nowait(), "A: end wait")
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
      for i in range(11):
        self._addThread(target=_AcquireWithTimeout,
                        args=(shared, i * 2.0 / 1000.0))

      # Wait for threads to finish (makes sure the acquire timeout expires
      # before releasing the lock)
      self._waitThreads()

      # Release lock
      self.sl.release()

      for _ in range(11):
        self.assertEqual(self.done.get_nowait(), "timeout")

      self.assertRaises(Queue.Empty, self.done.get_nowait)

  @_Repeat
  def testSharedSkipExclusiveAcquires(self):
    # Tests whether shared acquires jump in front of exclusive acquires in the
    # queue.

    def _Acquire(shared, name, notify_ev, wait_ev):
      if notify_ev:
        notify_fn = notify_ev.set
      else:
        notify_fn = None

      if wait_ev:
        wait_ev.wait()

      if not self.sl.acquire(shared=shared, test_notify=notify_fn):
        return

      self.done.put(name)
      self.sl.release()

    # Get exclusive lock while we fill the queue
    self.sl.acquire()

    shrcnt1 = 5
    shrcnt2 = 7
    shrcnt3 = 9
    shrcnt4 = 2

    # Add acquires using threading.Event for synchronization. They'll be
    # acquired exactly in the order defined in this list.
    acquires = (shrcnt1 * [(1, "shared 1")] +
                3 * [(0, "exclusive 1")] +
                shrcnt2 * [(1, "shared 2")] +
                shrcnt3 * [(1, "shared 3")] +
                shrcnt4 * [(1, "shared 4")] +
                3 * [(0, "exclusive 2")])

    ev_cur = None
    ev_prev = None

    for args in acquires:
      ev_cur = threading.Event()
      self._addThread(target=_Acquire, args=args + (ev_cur, ev_prev))
      ev_prev = ev_cur

    # Wait for last acquire to start
    ev_prev.wait()

    # Expect 6 pending exclusive acquires and 1 for all shared acquires
    # together
    self.assertEqual(self.sl._count_pending(), 7)

    # Release exclusive lock and wait
    self.sl.release()

    self._waitThreads()

    # Check sequence
    for _ in range(shrcnt1 + shrcnt2 + shrcnt3 + shrcnt4):
      # Shared locks aren't guaranteed to be notified in order, but they'll be
      # first
      tmp = self.done.get_nowait()
      if tmp == "shared 1":
        shrcnt1 -= 1
      elif tmp == "shared 2":
        shrcnt2 -= 1
      elif tmp == "shared 3":
        shrcnt3 -= 1
      elif tmp == "shared 4":
        shrcnt4 -= 1
    self.assertEqual(shrcnt1, 0)
    self.assertEqual(shrcnt2, 0)
    self.assertEqual(shrcnt3, 0)
    self.assertEqual(shrcnt3, 0)

    for _ in range(3):
      self.assertEqual(self.done.get_nowait(), "exclusive 1")

    for _ in range(3):
      self.assertEqual(self.done.get_nowait(), "exclusive 2")

    self.assertRaises(Queue.Empty, self.done.get_nowait)

  def testIllegalDowngrade(self):
    # Not yet acquired
    self.assertRaises(AssertionError, self.sl.downgrade)

    # Acquire in shared mode, downgrade should be no-op
    self.assertTrue(self.sl.acquire(shared=1))
    self.assertTrue(self.sl.is_owned(shared=1))
    self.assertTrue(self.sl.downgrade())
    self.assertTrue(self.sl.is_owned(shared=1))
    self.sl.release()

  def testDowngrade(self):
    self.assertTrue(self.sl.acquire())
    self.assertTrue(self.sl.is_owned(shared=0))
    self.assertTrue(self.sl.downgrade())
    self.assertTrue(self.sl.is_owned(shared=1))
    self.sl.release()

  @_Repeat
  def testDowngradeJumpsAheadOfExclusive(self):
    def _KeepExclusive(ev_got, ev_downgrade, ev_release):
      self.assertTrue(self.sl.acquire())
      self.assertTrue(self.sl.is_owned(shared=0))
      ev_got.set()
      ev_downgrade.wait()
      self.assertTrue(self.sl.is_owned(shared=0))
      self.assertTrue(self.sl.downgrade())
      self.assertTrue(self.sl.is_owned(shared=1))
      ev_release.wait()
      self.assertTrue(self.sl.is_owned(shared=1))
      self.sl.release()

    def _KeepExclusive2(ev_started, ev_release):
      self.assertTrue(self.sl.acquire(test_notify=ev_started.set))
      self.assertTrue(self.sl.is_owned(shared=0))
      ev_release.wait()
      self.assertTrue(self.sl.is_owned(shared=0))
      self.sl.release()

    def _KeepShared(ev_started, ev_got, ev_release):
      self.assertTrue(self.sl.acquire(shared=1, test_notify=ev_started.set))
      self.assertTrue(self.sl.is_owned(shared=1))
      ev_got.set()
      ev_release.wait()
      self.assertTrue(self.sl.is_owned(shared=1))
      self.sl.release()

    # Acquire lock in exclusive mode
    ev_got_excl1 = threading.Event()
    ev_downgrade_excl1 = threading.Event()
    ev_release_excl1 = threading.Event()
    th_excl1 = self._addThread(target=_KeepExclusive,
                               args=(ev_got_excl1, ev_downgrade_excl1,
                                     ev_release_excl1))
    ev_got_excl1.wait()

    # Start a second exclusive acquire
    ev_started_excl2 = threading.Event()
    ev_release_excl2 = threading.Event()
    th_excl2 = self._addThread(target=_KeepExclusive2,
                               args=(ev_started_excl2, ev_release_excl2))
    ev_started_excl2.wait()

    # Start shared acquires, will jump ahead of second exclusive acquire when
    # first exclusive acquire downgrades
    ev_shared = [(threading.Event(), threading.Event()) for _ in range(5)]
    ev_release_shared = threading.Event()

    th_shared = [self._addThread(target=_KeepShared,
                                 args=(ev_started, ev_got, ev_release_shared))
                 for (ev_started, ev_got) in ev_shared]

    # Wait for all shared acquires to start
    for (ev, _) in ev_shared:
      ev.wait()

    # Check lock information
    self.assertEqual(self.sl.GetLockInfo(set([query.LQ_MODE, query.LQ_OWNER])),
                     [(self.sl.name, "exclusive", [th_excl1.getName()], None)])
    [(_, _, _, pending), ] = self.sl.GetLockInfo(set([query.LQ_PENDING]))
    self.assertEqual([(pendmode, sorted(waiting))
                      for (pendmode, waiting) in pending],
                     [("exclusive", [th_excl2.getName()]),
                      ("shared", sorted(th.getName() for th in th_shared))])

    # Shared acquires won't start until the exclusive lock is downgraded
    ev_downgrade_excl1.set()

    # Wait for all shared acquires to be successful
    for (_, ev) in ev_shared:
      ev.wait()

    # Check lock information again
    self.assertEqual(self.sl.GetLockInfo(set([query.LQ_MODE,
                                              query.LQ_PENDING])),
                     [(self.sl.name, "shared", None,
                       [("exclusive", [th_excl2.getName()])])])
    [(_, _, owner, _), ] = self.sl.GetLockInfo(set([query.LQ_OWNER]))
    self.assertEqual(set(owner), set([th_excl1.getName()] +
                                     [th.getName() for th in th_shared]))

    ev_release_excl1.set()
    ev_release_excl2.set()
    ev_release_shared.set()

    self._waitThreads()

    self.assertEqual(self.sl.GetLockInfo(set([query.LQ_MODE, query.LQ_OWNER,
                                              query.LQ_PENDING])),
                     [(self.sl.name, None, None, [])])

  @_Repeat
  def testMixedAcquireTimeout(self):
    sync = threading.Event()

    def _AcquireShared(ev):
      if not self.sl.acquire(shared=1, timeout=None):
        return

      self.done.put("shared")

      # Notify main thread
      ev.set()

      # Wait for notification from main thread
      sync.wait()

      # Release lock
      self.sl.release()

    acquires = []
    for _ in range(3):
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
    exclsync = threading.Event()
    exclev = threading.Event()

    def _AcquireExclusive():
      if not self.sl.acquire(shared=0):
        return

      self.done.put("exclusive")

      # Notify main thread
      exclev.set()

      # Wait for notification from main thread
      exclsync.wait()

      self.sl.release()

    self._addThread(target=_AcquireExclusive)

    # Try to get exclusive lock
    self.failIf(self.sl.acquire(shared=0, timeout=0.02))

    # Make all shared holders release their locks
    sync.set()

    # Wait for exclusive acquire to succeed
    exclev.wait()

    self.assertEqual(self.sl._count_pending(), 0)

    # Try to get exclusive lock
    self.failIf(self.sl.acquire(shared=0, timeout=0.02))

    def _AcquireSharedSimple():
      if self.sl.acquire(shared=1, timeout=None):
        self.done.put("shared2")
        self.sl.release()

    for _ in range(10):
      self._addThread(target=_AcquireSharedSimple)

    # Tell exclusive lock to release
    exclsync.set()

    # Wait for everything to finish
    self._waitThreads()

    self.assertEqual(self.sl._count_pending(), 0)

    # Check sequence
    for _ in range(3):
      self.assertEqual(self.done.get_nowait(), "shared")

    self.assertEqual(self.done.get_nowait(), "exclusive")

    for _ in range(10):
      self.assertEqual(self.done.get_nowait(), "shared2")

    self.assertRaises(Queue.Empty, self.done.get_nowait)

  def testPriority(self):
    # Acquire in exclusive mode
    self.assert_(self.sl.acquire(shared=0))

    # Queue acquires
    def _Acquire(prev, next, shared, priority, result):
      prev.wait()
      self.sl.acquire(shared=shared, priority=priority, test_notify=next.set)
      try:
        self.done.put(result)
      finally:
        self.sl.release()

    counter = itertools.count(0)
    priorities = range(-20, 30)
    first = threading.Event()
    prev = first

    # Data structure:
    # {
    #   priority:
    #     [(shared/exclusive, set(acquire names), set(pending threads)),
    #      (shared/exclusive, ...),
    #      ...,
    #     ],
    # }
    perprio = {}

    # References shared acquire per priority in L{perprio}. Data structure:
    # {
    #   priority: (shared=1, set(acquire names), set(pending threads)),
    # }
    prioshared = {}

    for seed in [4979, 9523, 14902, 32440]:
      # Use a deterministic random generator
      rnd = random.Random(seed)
      for priority in [rnd.choice(priorities) for _ in range(30)]:
        modes = [0, 1]
        rnd.shuffle(modes)
        for shared in modes:
          # Unique name
          acqname = "%s/shr=%s/prio=%s" % (counter.next(), shared, priority)

          ev = threading.Event()
          thread = self._addThread(target=_Acquire,
                                   args=(prev, ev, shared, priority, acqname))
          prev = ev

          # Record expected aqcuire, see above for structure
          data = (shared, set([acqname]), set([thread]))
          priolist = perprio.setdefault(priority, [])
          if shared:
            priosh = prioshared.get(priority, None)
            if priosh:
              # Shared acquires are merged
              for i, j in zip(priosh[1:], data[1:]):
                i.update(j)
              assert data[0] == priosh[0]
            else:
              prioshared[priority] = data
              priolist.append(data)
          else:
            priolist.append(data)

    # Start all acquires and wait for them
    first.set()
    prev.wait()

    # Check lock information
    self.assertEqual(self.sl.GetLockInfo(set()),
                     [(self.sl.name, None, None, None)])
    self.assertEqual(self.sl.GetLockInfo(set([query.LQ_MODE, query.LQ_OWNER])),
                     [(self.sl.name, "exclusive",
                       [threading.currentThread().getName()], None)])

    self._VerifyPrioPending(self.sl.GetLockInfo(set([query.LQ_PENDING])),
                            perprio)

    # Let threads acquire the lock
    self.sl.release()

    # Wait for everything to finish
    self._waitThreads()

    self.assert_(self.sl._check_empty())

    # Check acquires by priority
    for acquires in [perprio[i] for i in sorted(perprio.keys())]:
      for (_, names, _) in acquires:
        # For shared acquires, the set will contain 1..n entries. For exclusive
        # acquires only one.
        while names:
          names.remove(self.done.get_nowait())
      self.assertFalse(compat.any(names for (_, names, _) in acquires))

    self.assertRaises(Queue.Empty, self.done.get_nowait)

  def _VerifyPrioPending(self, ((name, mode, owner, pending), ), perprio):
    self.assertEqual(name, self.sl.name)
    self.assert_(mode is None)
    self.assert_(owner is None)

    self.assertEqual([(pendmode, sorted(waiting))
                      for (pendmode, waiting) in pending],
                     [(["exclusive", "shared"][int(bool(shared))],
                       sorted(t.getName() for t in threads))
                      for acquires in [perprio[i]
                                       for i in sorted(perprio.keys())]
                      for (shared, _, threads) in acquires])

  class _FakeTimeForSpuriousNotifications:
    def __init__(self, now, check_end):
      self.now = now
      self.check_end = check_end

      # Deterministic random number generator
      self.rnd = random.Random(15086)

    def time(self):
      # Advance time if the random number generator thinks so (this is to test
      # multiple notifications without advancing the time)
      if self.rnd.random() < 0.3:
        self.now += self.rnd.random()

      self.check_end(self.now)

      return self.now

  @_Repeat
  def testAcquireTimeoutWithSpuriousNotifications(self):
    ready = threading.Event()
    locked = threading.Event()
    req = Queue.Queue(0)

    epoch = 4000.0
    timeout = 60.0

    def check_end(now):
      self.assertFalse(locked.isSet())

      # If we waited long enough (in virtual time), tell main thread to release
      # lock, otherwise tell it to notify once more
      req.put(now < (epoch + (timeout * 0.8)))

    time_fn = self._FakeTimeForSpuriousNotifications(epoch, check_end).time

    sl = locking.SharedLock("test", _time_fn=time_fn)

    # Acquire in exclusive mode
    sl.acquire(shared=0)

    def fn():
      self.assertTrue(sl.acquire(shared=0, timeout=timeout,
                                 test_notify=ready.set))
      locked.set()
      sl.release()
      self.done.put("success")

    # Start acquire with timeout and wait for it to be ready
    self._addThread(target=fn)
    ready.wait()

    # The separate thread is now waiting to acquire the lock, so start sending
    # spurious notifications.

    # Wait for separate thread to ask for another notification
    count = 0
    while req.get():
      # After sending the notification, the lock will take a short amount of
      # time to notice and to retrieve the current time
      sl._notify_topmost()
      count += 1

    self.assertTrue(count > 100, "Not enough notifications were sent")

    self.assertFalse(locked.isSet())

    # Some notifications have been sent, now actually release the lock
    sl.release()

    # Wait for lock to be acquired
    locked.wait()

    self._waitThreads()

    self.assertEqual(self.done.get_nowait(), "success")
    self.assertRaises(Queue.Empty, self.done.get_nowait)


class TestSharedLockInCondition(_ThreadedTestCase):
  """SharedLock as a condition lock tests"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self.sl = locking.SharedLock("TestSharedLockInCondition")
    self.setCondition()

  def setCondition(self):
    self.cond = threading.Condition(self.sl)

  def testKeepMode(self):
    self.cond.acquire(shared=1)
    self.assert_(self.sl.is_owned(shared=1))
    self.cond.wait(0)
    self.assert_(self.sl.is_owned(shared=1))
    self.cond.release()
    self.cond.acquire(shared=0)
    self.assert_(self.sl.is_owned(shared=0))
    self.cond.wait(0)
    self.assert_(self.sl.is_owned(shared=0))
    self.cond.release()


class TestSharedLockInPipeCondition(TestSharedLockInCondition):
  """SharedLock as a pipe condition lock tests"""

  def setCondition(self):
    self.cond = locking.PipeCondition(self.sl)


class TestSSynchronizedDecorator(_ThreadedTestCase):
  """Shared Lock Synchronized decorator test"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)

  @locking.ssynchronized(_decoratorlock)
  def _doItExclusive(self):
    self.assert_(_decoratorlock.is_owned())
    self.done.put("EXC")

  @locking.ssynchronized(_decoratorlock, shared=1)
  def _doItSharer(self):
    self.assert_(_decoratorlock.is_owned(shared=1))
    self.done.put("SHR")

  def testDecoratedFunctions(self):
    self._doItExclusive()
    self.assertFalse(_decoratorlock.is_owned())
    self._doItSharer()
    self.assertFalse(_decoratorlock.is_owned())

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
    self.failUnlessEqual(self.done.get_nowait(), "EXC")

  @_Repeat
  def testExclusiveBlocksSharer(self):
    _decoratorlock.acquire()
    self._addThread(target=self._doItSharer)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), "SHR")

  @_Repeat
  def testSharerBlocksExclusive(self):
    _decoratorlock.acquire(shared=1)
    self._addThread(target=self._doItExclusive)
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), "EXC")


class TestLockSet(_ThreadedTestCase):
  """LockSet tests"""

  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self._setUpLS()

  def _setUpLS(self):
    """Helper to (re)initialize the lock set"""
    self.resources = ["one", "two", "three"]
    self.ls = locking.LockSet(self.resources, "TestLockSet")

  def testResources(self):
    self.assertEquals(self.ls._names(), set(self.resources))
    newls = locking.LockSet([], "TestLockSet.testResources")
    self.assertEquals(newls._names(), set())

  def testCheckOwnedUnknown(self):
    self.assertFalse(self.ls.check_owned("certainly-not-owning-this-one"))
    for shared in [-1, 0, 1, 6378, 24255]:
      self.assertFalse(self.ls.check_owned("certainly-not-owning-this-one",
                                           shared=shared))

  def testCheckOwnedUnknownWhileHolding(self):
    self.assertFalse(self.ls.check_owned([]))
    self.ls.acquire("one", shared=1)
    self.assertRaises(errors.LockError, self.ls.check_owned, "nonexist")
    self.assertTrue(self.ls.check_owned("one", shared=1))
    self.assertFalse(self.ls.check_owned("one", shared=0))
    self.assertFalse(self.ls.check_owned(["one", "two"]))
    self.assertRaises(errors.LockError, self.ls.check_owned,
                      ["one", "nonexist"])
    self.assertRaises(errors.LockError, self.ls.check_owned, "")
    self.ls.release()
    self.assertFalse(self.ls.check_owned([]))
    self.assertFalse(self.ls.check_owned("one"))

  def testAcquireRelease(self):
    self.assertFalse(self.ls.check_owned(self.ls._names()))
    self.assert_(self.ls.acquire("one"))
    self.assertEquals(self.ls.list_owned(), set(["one"]))
    self.assertTrue(self.ls.check_owned("one"))
    self.assertTrue(self.ls.check_owned("one", shared=0))
    self.assertFalse(self.ls.check_owned("one", shared=1))
    self.ls.release()
    self.assertEquals(self.ls.list_owned(), set())
    self.assertFalse(self.ls.check_owned(self.ls._names()))
    self.assertEquals(self.ls.acquire(["one"]), set(["one"]))
    self.assertEquals(self.ls.list_owned(), set(["one"]))
    self.ls.release()
    self.assertEquals(self.ls.list_owned(), set())
    self.ls.acquire(["one", "two", "three"])
    self.assertEquals(self.ls.list_owned(), set(["one", "two", "three"]))
    self.assertTrue(self.ls.check_owned(self.ls._names()))
    self.assertTrue(self.ls.check_owned(self.ls._names(), shared=0))
    self.assertFalse(self.ls.check_owned(self.ls._names(), shared=1))
    self.ls.release("one")
    self.assertFalse(self.ls.check_owned(["one"]))
    self.assertTrue(self.ls.check_owned(["two", "three"]))
    self.assertTrue(self.ls.check_owned(["two", "three"], shared=0))
    self.assertFalse(self.ls.check_owned(["two", "three"], shared=1))
    self.assertEquals(self.ls.list_owned(), set(["two", "three"]))
    self.ls.release(["three"])
    self.assertEquals(self.ls.list_owned(), set(["two"]))
    self.ls.release()
    self.assertEquals(self.ls.list_owned(), set())
    self.assertEquals(self.ls.acquire(["one", "three"]), set(["one", "three"]))
    self.assertEquals(self.ls.list_owned(), set(["one", "three"]))
    self.ls.release()
    self.assertEquals(self.ls.list_owned(), set())
    for name in self.ls._names():
      self.assertFalse(self.ls.check_owned(name))

  def testNoDoubleAcquire(self):
    self.ls.acquire("one")
    self.assertRaises(AssertionError, self.ls.acquire, "one")
    self.assertRaises(AssertionError, self.ls.acquire, ["two"])
    self.assertRaises(AssertionError, self.ls.acquire, ["two", "three"])
    self.ls.release()
    self.ls.acquire(["one", "three"])
    self.ls.release("one")
    self.assertRaises(AssertionError, self.ls.acquire, ["two"])
    self.ls.release("three")

  def testNoWrongRelease(self):
    self.assertRaises(AssertionError, self.ls.release)
    self.ls.acquire("one")
    self.assertRaises(AssertionError, self.ls.release, "two")

  def testAddRemove(self):
    self.ls.add("four")
    self.assertEquals(self.ls.list_owned(), set())
    self.assert_("four" in self.ls._names())
    self.ls.add(["five", "six", "seven"], acquired=1)
    self.assert_("five" in self.ls._names())
    self.assert_("six" in self.ls._names())
    self.assert_("seven" in self.ls._names())
    self.assertEquals(self.ls.list_owned(), set(["five", "six", "seven"]))
    self.assertEquals(self.ls.remove(["five", "six"]), ["five", "six"])
    self.assert_("five" not in self.ls._names())
    self.assert_("six" not in self.ls._names())
    self.assertEquals(self.ls.list_owned(), set(["seven"]))
    self.assertRaises(AssertionError, self.ls.add, "eight", acquired=1)
    self.ls.remove("seven")
    self.assert_("seven" not in self.ls._names())
    self.assertEquals(self.ls.list_owned(), set([]))
    self.ls.acquire(None, shared=1)
    self.assertRaises(AssertionError, self.ls.add, "eight")
    self.ls.release()
    self.ls.acquire(None)
    self.ls.add("eight", acquired=1)
    self.assert_("eight" in self.ls._names())
    self.assert_("eight" in self.ls.list_owned())
    self.ls.add("nine")
    self.assert_("nine" in self.ls._names())
    self.assert_("nine" not in self.ls.list_owned())
    self.ls.release()
    self.ls.remove(["two"])
    self.assert_("two" not in self.ls._names())
    self.ls.acquire("three")
    self.assertEquals(self.ls.remove(["three"]), ["three"])
    self.assert_("three" not in self.ls._names())
    self.assertEquals(self.ls.remove("three"), [])
    self.assertEquals(self.ls.remove(["one", "three", "six"]), ["one"])
    self.assert_("one" not in self.ls._names())

  def testRemoveNonBlocking(self):
    self.ls.acquire("one")
    self.assertEquals(self.ls.remove("one"), ["one"])
    self.ls.acquire(["two", "three"])
    self.assertEquals(self.ls.remove(["two", "three"]),
                      ["two", "three"])

  def testNoDoubleAdd(self):
    self.assertRaises(errors.LockError, self.ls.add, "two")
    self.ls.add("four")
    self.assertRaises(errors.LockError, self.ls.add, "four")

  def testNoWrongRemoves(self):
    self.ls.acquire(["one", "three"], shared=1)
    # Cannot remove "two" while holding something which is not a superset
    self.assertRaises(AssertionError, self.ls.remove, "two")
    # Cannot remove "three" as we are sharing it
    self.assertRaises(AssertionError, self.ls.remove, "three")

  def testAcquireSetLock(self):
    # acquire the set-lock exclusively
    self.assertEquals(self.ls.acquire(None), set(["one", "two", "three"]))
    self.assertEquals(self.ls.list_owned(), set(["one", "two", "three"]))
    self.assertEquals(self.ls.is_owned(), True)
    self.assertEquals(self.ls._names(), set(["one", "two", "three"]))
    # I can still add/remove elements...
    self.assertEquals(self.ls.remove(["two", "three"]), ["two", "three"])
    self.assert_(self.ls.add("six"))
    self.ls.release()
    # share the set-lock
    self.assertEquals(self.ls.acquire(None, shared=1), set(["one", "six"]))
    # adding new elements is not possible
    self.assertRaises(AssertionError, self.ls.add, "five")
    self.ls.release()

  def testAcquireWithRepetitions(self):
    self.assertEquals(self.ls.acquire(["two", "two", "three"], shared=1),
                      set(["two", "two", "three"]))
    self.ls.release(["two", "two"])
    self.assertEquals(self.ls.list_owned(), set(["three"]))

  def testEmptyAcquire(self):
    # Acquire an empty list of locks...
    self.assertEquals(self.ls.acquire([]), set())
    self.assertEquals(self.ls.list_owned(), set())
    # New locks can still be addded
    self.assert_(self.ls.add("six"))
    # "re-acquiring" is not an issue, since we had really acquired nothing
    self.assertEquals(self.ls.acquire([], shared=1), set())
    self.assertEquals(self.ls.list_owned(), set())
    # We haven't really acquired anything, so we cannot release
    self.assertRaises(AssertionError, self.ls.release)

  def _doLockSet(self, names, shared):
    try:
      self.ls.acquire(names, shared=shared)
      self.done.put("DONE")
      self.ls.release()
    except errors.LockError:
      self.done.put("ERR")

  def _doAddSet(self, names):
    try:
      self.ls.add(names, acquired=1)
      self.done.put("DONE")
      self.ls.release()
    except errors.LockError:
      self.done.put("ERR")

  def _doRemoveSet(self, names):
    self.done.put(self.ls.remove(names))

  @_Repeat
  def testConcurrentSharedAcquire(self):
    self.ls.acquire(["one", "two"], shared=1)
    self._addThread(target=self._doLockSet, args=(["one", "two"], 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doLockSet, args=(["one", "two", "three"], 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doLockSet, args=("three", 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doLockSet, args=(["one", "two"], 0))
    self._addThread(target=self._doLockSet, args=(["two", "three"], 0))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.assertEqual(self.done.get_nowait(), "DONE")

  @_Repeat
  def testConcurrentExclusiveAcquire(self):
    self.ls.acquire(["one", "two"])
    self._addThread(target=self._doLockSet, args=("three", 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doLockSet, args=("three", 0))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self._addThread(target=self._doLockSet, args=(["one", "two"], 0))
    self._addThread(target=self._doLockSet, args=(["one", "two"], 1))
    self._addThread(target=self._doLockSet, args=("one", 0))
    self._addThread(target=self._doLockSet, args=("one", 1))
    self._addThread(target=self._doLockSet, args=(["two", "three"], 0))
    self._addThread(target=self._doLockSet, args=(["two", "three"], 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    for _ in range(6):
      self.failUnlessEqual(self.done.get_nowait(), "DONE")

  @_Repeat
  def testSimpleAcquireTimeoutExpiring(self):
    names = sorted(self.ls._names())
    self.assert_(len(names) >= 3)

    # Get name of first lock
    first = names[0]

    # Get name of last lock
    last = names.pop()

    checks = [
      # Block first and try to lock it again
      (first, first),

      # Block last and try to lock all locks
      (None, first),

      # Block last and try to lock it again
      (last, last),
      ]

    for (wanted, block) in checks:
      # Lock in exclusive mode
      self.assert_(self.ls.acquire(block, shared=0))

      def _AcquireOne():
        # Try to get the same lock again with a timeout (should never succeed)
        acquired = self.ls.acquire(wanted, timeout=0.1, shared=0)
        if acquired:
          self.done.put("acquired")
          self.ls.release()
        else:
          self.assert_(acquired is None)
          self.assertFalse(self.ls.list_owned())
          self.assertFalse(self.ls.is_owned())
          self.done.put("not acquired")

      self._addThread(target=_AcquireOne)

      # Wait for timeout in thread to expire
      self._waitThreads()

      # Release exclusive lock again
      self.ls.release()

      self.assertEqual(self.done.get_nowait(), "not acquired")
      self.assertRaises(Queue.Empty, self.done.get_nowait)

  @_Repeat
  def testDelayedAndExpiringLockAcquire(self):
    self._setUpLS()
    self.ls.add(["five", "six", "seven", "eight", "nine"])

    for expire in (False, True):
      names = sorted(self.ls._names())
      self.assertEqual(len(names), 8)

      lock_ev = dict([(i, threading.Event()) for i in names])

      # Lock all in exclusive mode
      self.assert_(self.ls.acquire(names, shared=0))

      if expire:
        # We'll wait at least 300ms per lock
        lockwait = len(names) * [0.3]

        # Fail if we can't acquire all locks in 400ms. There are 8 locks, so
        # this gives us up to 2.4s to fail.
        lockall_timeout = 0.4
      else:
        # This should finish rather quickly
        lockwait = None
        lockall_timeout = len(names) * 5.0

      def _LockAll():
        def acquire_notification(name):
          if not expire:
            self.done.put("getting %s" % name)

          # Kick next lock
          lock_ev[name].set()

        if self.ls.acquire(names, shared=0, timeout=lockall_timeout,
                           test_notify=acquire_notification):
          self.done.put("got all")
          self.ls.release()
        else:
          self.done.put("timeout on all")

        # Notify all locks
        for ev in lock_ev.values():
          ev.set()

      t = self._addThread(target=_LockAll)

      for idx, name in enumerate(names):
        # Wait for actual acquire on this lock to start
        lock_ev[name].wait(10.0)

        if expire and t.isAlive():
          # Wait some time after getting the notification to make sure the lock
          # acquire will expire
          SafeSleep(lockwait[idx])

        self.ls.release(names=name)

      self.assertFalse(self.ls.list_owned())

      self._waitThreads()

      if expire:
        # Not checking which locks were actually acquired. Doing so would be
        # too timing-dependant.
        self.assertEqual(self.done.get_nowait(), "timeout on all")
      else:
        for i in names:
          self.assertEqual(self.done.get_nowait(), "getting %s" % i)
        self.assertEqual(self.done.get_nowait(), "got all")
      self.assertRaises(Queue.Empty, self.done.get_nowait)

  @_Repeat
  def testConcurrentRemove(self):
    self.ls.add("four")
    self.ls.acquire(["one", "two", "four"])
    self._addThread(target=self._doLockSet, args=(["one", "four"], 0))
    self._addThread(target=self._doLockSet, args=(["one", "four"], 1))
    self._addThread(target=self._doLockSet, args=(["one", "two"], 0))
    self._addThread(target=self._doLockSet, args=(["one", "two"], 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.remove("one")
    self.ls.release()
    self._waitThreads()
    for i in range(4):
      self.failUnlessEqual(self.done.get_nowait(), "ERR")
    self.ls.add(["five", "six"], acquired=1)
    self._addThread(target=self._doLockSet, args=(["three", "six"], 1))
    self._addThread(target=self._doLockSet, args=(["three", "six"], 0))
    self._addThread(target=self._doLockSet, args=(["four", "six"], 1))
    self._addThread(target=self._doLockSet, args=(["four", "six"], 0))
    self.ls.remove("five")
    self.ls.release()
    self._waitThreads()
    for i in range(4):
      self.failUnlessEqual(self.done.get_nowait(), "DONE")
    self.ls.acquire(["three", "four"])
    self._addThread(target=self._doRemoveSet, args=(["four", "six"], ))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.remove("four")
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), ["six"])
    self._addThread(target=self._doRemoveSet, args=(["two"]))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), ["two"])
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
    self.assertEqual(self.done.get_nowait(), "DONE")
    # ...or just share some elements
    self._addThread(target=self._doLockSet, args=(["one", "three"], 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    # ...but not add new ones or remove any
    t = self._addThread(target=self._doAddSet, args=(["nine"]))
    self._addThread(target=self._doRemoveSet, args=(["two"], ))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    # this just releases the set-lock
    self.ls.release([])
    t.join(60)
    self.assertEqual(self.done.get_nowait(), "DONE")
    # release the lock on the actual elements so remove() can proceed too
    self.ls.release()
    self._waitThreads()
    self.failUnlessEqual(self.done.get_nowait(), ["two"])
    # reset lockset
    self._setUpLS()

  @_Repeat
  def testConcurrentExclusiveSetLock(self):
    # acquire the set-lock...
    self.ls.acquire(None, shared=0)
    # ...no one can do anything else
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._addThread(target=self._doLockSet, args=(None, 0))
    self._addThread(target=self._doLockSet, args=(["three"], 0))
    self._addThread(target=self._doLockSet, args=(["two"], 1))
    self._addThread(target=self._doAddSet, args=(["nine"]))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    for _ in range(5):
      self.assertEqual(self.done.get(True, 1), "DONE")
    # cleanup
    self._setUpLS()

  @_Repeat
  def testConcurrentSetLockAdd(self):
    self.ls.acquire("one")
    # Another thread wants the whole SetLock
    self._addThread(target=self._doLockSet, args=(None, 0))
    self._addThread(target=self._doLockSet, args=(None, 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.assertRaises(AssertionError, self.ls.add, "four")
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.ls.acquire(None)
    self._addThread(target=self._doLockSet, args=(None, 0))
    self._addThread(target=self._doLockSet, args=(None, 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.add("four")
    self.ls.add("five", acquired=1)
    self.ls.add("six", acquired=1, shared=1)
    self.assertEquals(self.ls.list_owned(),
      set(["one", "two", "three", "five", "six"]))
    self.assertEquals(self.ls.is_owned(), True)
    self.assertEquals(self.ls._names(),
      set(["one", "two", "three", "four", "five", "six"]))
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._setUpLS()

  @_Repeat
  def testEmptyLockSet(self):
    # get the set-lock
    self.assertEqual(self.ls.acquire(None), set(["one", "two", "three"]))
    # now empty it...
    self.ls.remove(["one", "two", "three"])
    # and adds/locks by another thread still wait
    self._addThread(target=self._doAddSet, args=(["nine"]))
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._addThread(target=self._doLockSet, args=(None, 0))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    for _ in range(3):
      self.assertEqual(self.done.get_nowait(), "DONE")
    # empty it again...
    self.assertEqual(self.ls.remove(["nine"]), ["nine"])
    # now share it...
    self.assertEqual(self.ls.acquire(None, shared=1), set())
    # other sharers can go, adds still wait
    self._addThread(target=self._doLockSet, args=(None, 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doAddSet, args=(["nine"]))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.ls.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._setUpLS()

  def testAcquireWithNamesDowngrade(self):
    self.assertEquals(self.ls.acquire("two", shared=0), set(["two"]))
    self.assertTrue(self.ls.is_owned())
    self.assertFalse(self.ls._get_lock().is_owned())
    self.ls.release()
    self.assertFalse(self.ls.is_owned())
    self.assertFalse(self.ls._get_lock().is_owned())
    # Can't downgrade after releasing
    self.assertRaises(AssertionError, self.ls.downgrade, "two")

  def testDowngrade(self):
    # Not owning anything, must raise an exception
    self.assertFalse(self.ls.is_owned())
    self.assertRaises(AssertionError, self.ls.downgrade)

    self.assertFalse(compat.any(i.is_owned()
                                for i in self.ls._get_lockdict().values()))
    self.assertFalse(self.ls.check_owned(self.ls._names()))
    for name in self.ls._names():
      self.assertFalse(self.ls.check_owned(name))

    self.assertEquals(self.ls.acquire(None, shared=0),
                      set(["one", "two", "three"]))
    self.assertRaises(AssertionError, self.ls.downgrade, "unknown lock")

    self.assertTrue(self.ls.check_owned(self.ls._names(), shared=0))
    for name in self.ls._names():
      self.assertTrue(self.ls.check_owned(name))
      self.assertTrue(self.ls.check_owned(name, shared=0))
      self.assertFalse(self.ls.check_owned(name, shared=1))

    self.assertTrue(self.ls._get_lock().is_owned(shared=0))
    self.assertTrue(compat.all(i.is_owned(shared=0)
                               for i in self.ls._get_lockdict().values()))

    # Start downgrading locks
    self.assertTrue(self.ls.downgrade(names=["one"]))
    self.assertTrue(self.ls._get_lock().is_owned(shared=0))
    self.assertTrue(compat.all(lock.is_owned(shared=[0, 1][int(name == "one")])
                               for name, lock in
                                 self.ls._get_lockdict().items()))

    self.assertFalse(self.ls.check_owned("one", shared=0))
    self.assertTrue(self.ls.check_owned("one", shared=1))
    self.assertTrue(self.ls.check_owned("two", shared=0))
    self.assertTrue(self.ls.check_owned("three", shared=0))

    # Downgrade second lock
    self.assertTrue(self.ls.downgrade(names="two"))
    self.assertTrue(self.ls._get_lock().is_owned(shared=0))
    should_share = lambda name: [0, 1][int(name in ("one", "two"))]
    self.assertTrue(compat.all(lock.is_owned(shared=should_share(name))
                               for name, lock in
                                 self.ls._get_lockdict().items()))

    self.assertFalse(self.ls.check_owned("one", shared=0))
    self.assertTrue(self.ls.check_owned("one", shared=1))
    self.assertFalse(self.ls.check_owned("two", shared=0))
    self.assertTrue(self.ls.check_owned("two", shared=1))
    self.assertTrue(self.ls.check_owned("three", shared=0))

    # Downgrading the last exclusive lock to shared must downgrade the
    # lockset-internal lock too
    self.assertTrue(self.ls.downgrade(names="three"))
    self.assertTrue(self.ls._get_lock().is_owned(shared=1))
    self.assertTrue(compat.all(i.is_owned(shared=1)
                               for i in self.ls._get_lockdict().values()))

    # Verify owned locks
    for name in self.ls._names():
      self.assertTrue(self.ls.check_owned(name, shared=1))

    # Downgrading a shared lock must be a no-op
    self.assertTrue(self.ls.downgrade(names=["one", "three"]))
    self.assertTrue(self.ls._get_lock().is_owned(shared=1))
    self.assertTrue(compat.all(i.is_owned(shared=1)
                               for i in self.ls._get_lockdict().values()))

    self.ls.release()

  def testDowngradeEverything(self):
    self.assertEqual(self.ls.acquire(locking.ALL_SET, shared=0),
                     set(["one", "two", "three"]))

    # Ensure all locks are now owned in exclusive mode
    for name in self.ls._names():
      self.assertTrue(self.ls.check_owned(name, shared=0))

    # Downgrade everything
    self.assertTrue(self.ls.downgrade())

    # Ensure all locks are now owned in shared mode
    for name in self.ls._names():
      self.assertTrue(self.ls.check_owned(name, shared=1))

  def testPriority(self):
    def _Acquire(prev, next, name, priority, success_fn):
      prev.wait()
      self.assert_(self.ls.acquire(name, shared=0,
                                   priority=priority,
                                   test_notify=lambda _: next.set()))
      try:
        success_fn()
      finally:
        self.ls.release()

    # Get all in exclusive mode
    self.assert_(self.ls.acquire(locking.ALL_SET, shared=0))

    done_two = Queue.Queue(0)

    first = threading.Event()
    prev = first

    acquires = [("one", prio, self.done) for prio in range(1, 33)]
    acquires.extend([("two", prio, done_two) for prio in range(1, 33)])

    # Use a deterministic random generator
    random.Random(741).shuffle(acquires)

    for (name, prio, done) in acquires:
      ev = threading.Event()
      self._addThread(target=_Acquire,
                      args=(prev, ev, name, prio,
                            compat.partial(done.put, "Prio%s" % prio)))
      prev = ev

    # Start acquires
    first.set()

    # Wait for last acquire to start
    prev.wait()

    # Let threads acquire locks
    self.ls.release()

    # Wait for threads to finish
    self._waitThreads()

    for i in range(1, 33):
      self.assertEqual(self.done.get_nowait(), "Prio%s" % i)
      self.assertEqual(done_two.get_nowait(), "Prio%s" % i)

    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.assertRaises(Queue.Empty, done_two.get_nowait)


class TestGanetiLockManager(_ThreadedTestCase):
  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self.nodes = ["n1", "n2"]
    self.nodegroups = ["g1", "g2"]
    self.instances = ["i1", "i2", "i3"]
    self.networks = ["net1", "net2", "net3"]
    self.GL = locking.GanetiLockManager(self.nodes, self.nodegroups,
                                        self.instances, self.networks)

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
    self.assertRaises(AssertionError, locking.GanetiLockManager, [], [], [], [])

  def testLockNames(self):
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(["BGL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE_ALLOC), set(["NAL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set(self.nodes))
    self.assertEqual(self.GL._names(locking.LEVEL_NODEGROUP),
                     set(self.nodegroups))
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE),
                     set(self.instances))
    self.assertEqual(self.GL._names(locking.LEVEL_NETWORK),
                     set(self.networks))

  def testInitAndResources(self):
    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager([], [], [], [])
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(["BGL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE_ALLOC), set(["NAL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_NODEGROUP), set())
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_NETWORK), set())

    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager(self.nodes, self.nodegroups, [], [])
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(["BGL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE_ALLOC), set(["NAL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set(self.nodes))
    self.assertEqual(self.GL._names(locking.LEVEL_NODEGROUP),
                                    set(self.nodegroups))
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_NETWORK), set())

    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager([], [], self.instances, [])
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(["BGL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE_ALLOC), set(["NAL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_NODEGROUP), set())
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE),
                     set(self.instances))

    locking.GanetiLockManager._instance = None
    self.GL = locking.GanetiLockManager([], [], [], self.networks)
    self.assertEqual(self.GL._names(locking.LEVEL_CLUSTER), set(["BGL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE_ALLOC), set(["NAL"]))
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_NODEGROUP), set())
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE), set())
    self.assertEqual(self.GL._names(locking.LEVEL_NETWORK),
                     set(self.networks))

  def testAcquireRelease(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
    self.assertEquals(self.GL.list_owned(locking.LEVEL_CLUSTER), set(["BGL"]))
    self.GL.acquire(locking.LEVEL_INSTANCE, ["i1"])
    self.GL.acquire(locking.LEVEL_NODEGROUP, ["g2"])
    self.GL.acquire(locking.LEVEL_NODE, ["n1", "n2"], shared=1)
    self.assertTrue(self.GL.check_owned(locking.LEVEL_NODE, ["n1", "n2"],
                                        shared=1))
    self.assertFalse(self.GL.check_owned(locking.LEVEL_INSTANCE, ["i1", "i3"]))
    self.GL.release(locking.LEVEL_NODE, ["n2"])
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODE), set(["n1"]))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODEGROUP), set(["g2"]))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_INSTANCE), set(["i1"]))
    self.GL.release(locking.LEVEL_NODE)
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODE), set())
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODEGROUP), set(["g2"]))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_INSTANCE), set(["i1"]))
    self.GL.release(locking.LEVEL_NODEGROUP)
    self.GL.release(locking.LEVEL_INSTANCE)
    self.assertRaises(errors.LockError, self.GL.acquire,
                      locking.LEVEL_INSTANCE, ["i5"])
    self.GL.acquire(locking.LEVEL_INSTANCE, ["i3"], shared=1)
    self.assertEquals(self.GL.list_owned(locking.LEVEL_INSTANCE), set(["i3"]))

  def testAcquireWholeSets(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
    self.assertEquals(self.GL.acquire(locking.LEVEL_INSTANCE, None),
                      set(self.instances))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_INSTANCE),
                      set(self.instances))
    self.assertEquals(self.GL.acquire(locking.LEVEL_NODEGROUP, None),
                      set(self.nodegroups))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODEGROUP),
                      set(self.nodegroups))
    self.assertEquals(self.GL.acquire(locking.LEVEL_NODE, None, shared=1),
                      set(self.nodes))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODE),
                      set(self.nodes))
    self.GL.release(locking.LEVEL_NODE)
    self.GL.release(locking.LEVEL_NODEGROUP)
    self.GL.release(locking.LEVEL_INSTANCE)
    self.GL.release(locking.LEVEL_CLUSTER)

  def testAcquireWholeAndPartial(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
    self.assertEquals(self.GL.acquire(locking.LEVEL_INSTANCE, None),
                      set(self.instances))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_INSTANCE),
                      set(self.instances))
    self.assertEquals(self.GL.acquire(locking.LEVEL_NODE, ["n2"], shared=1),
                      set(["n2"]))
    self.assertEquals(self.GL.list_owned(locking.LEVEL_NODE),
                      set(["n2"]))
    self.GL.release(locking.LEVEL_NODE)
    self.GL.release(locking.LEVEL_INSTANCE)
    self.GL.release(locking.LEVEL_CLUSTER)

  def testBGLDependency(self):
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_NODE, ["n1", "n2"])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_INSTANCE, ["i3"])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_NODEGROUP, ["g1"])
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
    self.GL.acquire(locking.LEVEL_NODE, ["n1"])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER, ["BGL"])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER)
    self.GL.release(locking.LEVEL_NODE)
    self.GL.acquire(locking.LEVEL_INSTANCE, ["i1", "i2"])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER, ["BGL"])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER)
    self.GL.release(locking.LEVEL_INSTANCE)
    self.GL.acquire(locking.LEVEL_NODEGROUP, None)
    self.GL.release(locking.LEVEL_NODEGROUP, ["g1"])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER, ["BGL"])
    self.assertRaises(AssertionError, self.GL.release,
                      locking.LEVEL_CLUSTER)
    self.GL.release(locking.LEVEL_NODEGROUP)
    self.GL.release(locking.LEVEL_CLUSTER)

  def testWrongOrder(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
    self.GL.acquire(locking.LEVEL_NODE, ["n2"])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_NODE, ["n1"])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_NODEGROUP, ["g1"])
    self.assertRaises(AssertionError, self.GL.acquire,
                      locking.LEVEL_INSTANCE, ["i2"])

  def testModifiableLevels(self):
    self.assertRaises(AssertionError, self.GL.add, locking.LEVEL_CLUSTER,
                      ["BGL2"])
    self.assertRaises(AssertionError, self.GL.add, locking.LEVEL_NODE_ALLOC,
                      ["NAL2"])
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"])
    self.GL.add(locking.LEVEL_INSTANCE, ["i4"])
    self.GL.remove(locking.LEVEL_INSTANCE, ["i3"])
    self.GL.remove(locking.LEVEL_INSTANCE, ["i1"])
    self.assertEqual(self.GL._names(locking.LEVEL_INSTANCE), set(["i2", "i4"]))
    self.GL.add(locking.LEVEL_NODE, ["n3"])
    self.GL.remove(locking.LEVEL_NODE, ["n1"])
    self.assertEqual(self.GL._names(locking.LEVEL_NODE), set(["n2", "n3"]))
    self.GL.add(locking.LEVEL_NODEGROUP, ["g3"])
    self.GL.remove(locking.LEVEL_NODEGROUP, ["g2"])
    self.GL.remove(locking.LEVEL_NODEGROUP, ["g1"])
    self.assertEqual(self.GL._names(locking.LEVEL_NODEGROUP), set(["g3"]))
    self.assertRaises(AssertionError, self.GL.remove, locking.LEVEL_CLUSTER,
                      ["BGL2"])

  # Helper function to run as a thread that shared the BGL and then acquires
  # some locks at another level.
  def _doLock(self, level, names, shared):
    try:
      self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
      self.GL.acquire(level, names, shared=shared)
      self.done.put("DONE")
      self.GL.release(level)
      self.GL.release(locking.LEVEL_CLUSTER)
    except errors.LockError:
      self.done.put("ERR")

  @_Repeat
  def testConcurrency(self):
    self.GL.acquire(locking.LEVEL_CLUSTER, ["BGL"], shared=1)
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, "i1", 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.GL.acquire(locking.LEVEL_INSTANCE, ["i3"])
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, "i1", 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, "i3", 1))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.GL.release(locking.LEVEL_INSTANCE)
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self.GL.acquire(locking.LEVEL_INSTANCE, ["i2"], shared=1)
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, "i2", 1))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DONE")
    self._addThread(target=self._doLock,
                    args=(locking.LEVEL_INSTANCE, "i2", 0))
    self.assertRaises(Queue.Empty, self.done.get_nowait)
    self.GL.release(locking.LEVEL_INSTANCE)
    self._waitThreads()
    self.assertEqual(self.done.get(True, 1), "DONE")
    self.GL.release(locking.LEVEL_CLUSTER, ["BGL"])


class TestLockMonitor(_ThreadedTestCase):
  def setUp(self):
    _ThreadedTestCase.setUp(self)
    self.lm = locking.LockMonitor()

  def testSingleThread(self):
    locks = []

    for i in range(100):
      name = "TestLock%s" % i
      locks.append(locking.SharedLock(name, monitor=self.lm))

    self.assertEqual(len(self.lm._locks), len(locks))
    result = objects.QueryResponse.FromDict(self.lm.QueryLocks(["name"]))
    self.assertEqual(len(result.fields), 1)
    self.assertEqual(len(result.data), 100)

    # Delete all locks
    del locks[:]

    # The garbage collector might needs some time
    def _CheckLocks():
      if self.lm._locks:
        raise utils.RetryAgain()

    utils.Retry(_CheckLocks, 0.1, 30.0)

    self.assertFalse(self.lm._locks)

  def testMultiThread(self):
    locks = []

    def _CreateLock(prev, next, name):
      prev.wait()
      locks.append(locking.SharedLock(name, monitor=self.lm))
      if next:
        next.set()

    expnames = []

    first = threading.Event()
    prev = first

    # Use a deterministic random generator
    for i in random.Random(4263).sample(range(100), 33):
      name = "MtTestLock%s" % i
      expnames.append(name)

      ev = threading.Event()
      self._addThread(target=_CreateLock, args=(prev, ev, name))
      prev = ev

    # Add locks
    first.set()
    self._waitThreads()

    # Check order in which locks were added
    self.assertEqual([i.name for i in locks], expnames)

    # Check query result
    result = self.lm.QueryLocks(["name", "mode", "owner", "pending"])
    self.assert_(isinstance(result, dict))
    response = objects.QueryResponse.FromDict(result)
    self.assertEqual(response.data,
                     [[(constants.RS_NORMAL, name),
                       (constants.RS_NORMAL, None),
                       (constants.RS_NORMAL, None),
                       (constants.RS_NORMAL, [])]
                      for name in utils.NiceSort(expnames)])
    self.assertEqual(len(response.fields), 4)
    self.assertEqual(["name", "mode", "owner", "pending"],
                     [fdef.name for fdef in response.fields])

    # Test exclusive acquire
    for tlock in locks[::4]:
      tlock.acquire(shared=0)
      try:
        def _GetExpResult(name):
          if tlock.name == name:
            return [(constants.RS_NORMAL, name),
                    (constants.RS_NORMAL, "exclusive"),
                    (constants.RS_NORMAL,
                     [threading.currentThread().getName()]),
                    (constants.RS_NORMAL, [])]
          return [(constants.RS_NORMAL, name),
                  (constants.RS_NORMAL, None),
                  (constants.RS_NORMAL, None),
                  (constants.RS_NORMAL, [])]

        result = self.lm.QueryLocks(["name", "mode", "owner", "pending"])
        self.assertEqual(objects.QueryResponse.FromDict(result).data,
                         [_GetExpResult(name)
                          for name in utils.NiceSort(expnames)])
      finally:
        tlock.release()

    # Test shared acquire
    def _Acquire(lock, shared, ev, notify):
      lock.acquire(shared=shared)
      try:
        notify.set()
        ev.wait()
      finally:
        lock.release()

    for tlock1 in locks[::11]:
      for tlock2 in locks[::-15]:
        if tlock2 == tlock1:
          # Avoid deadlocks
          continue

        for tlock3 in locks[::10]:
          if tlock3 in (tlock2, tlock1):
            # Avoid deadlocks
            continue

          releaseev = threading.Event()

          # Acquire locks
          acquireev = []
          tthreads1 = []
          for i in range(3):
            ev = threading.Event()
            tthreads1.append(self._addThread(target=_Acquire,
                                             args=(tlock1, 1, releaseev, ev)))
            acquireev.append(ev)

          ev = threading.Event()
          tthread2 = self._addThread(target=_Acquire,
                                     args=(tlock2, 1, releaseev, ev))
          acquireev.append(ev)

          ev = threading.Event()
          tthread3 = self._addThread(target=_Acquire,
                                     args=(tlock3, 0, releaseev, ev))
          acquireev.append(ev)

          # Wait for all locks to be acquired
          for i in acquireev:
            i.wait()

          # Check query result
          result = self.lm.QueryLocks(["name", "mode", "owner"])
          response = objects.QueryResponse.FromDict(result)
          for (name, mode, owner) in response.data:
            (name_status, name_value) = name
            (owner_status, owner_value) = owner

            self.assertEqual(name_status, constants.RS_NORMAL)
            self.assertEqual(owner_status, constants.RS_NORMAL)

            if name_value == tlock1.name:
              self.assertEqual(mode, (constants.RS_NORMAL, "shared"))
              self.assertEqual(set(owner_value),
                               set(i.getName() for i in tthreads1))
              continue

            if name_value == tlock2.name:
              self.assertEqual(mode, (constants.RS_NORMAL, "shared"))
              self.assertEqual(owner_value, [tthread2.getName()])
              continue

            if name_value == tlock3.name:
              self.assertEqual(mode, (constants.RS_NORMAL, "exclusive"))
              self.assertEqual(owner_value, [tthread3.getName()])
              continue

            self.assert_(name_value in expnames)
            self.assertEqual(mode, (constants.RS_NORMAL, None))
            self.assert_(owner_value is None)

          # Release locks again
          releaseev.set()

          self._waitThreads()

          result = self.lm.QueryLocks(["name", "mode", "owner"])
          self.assertEqual(objects.QueryResponse.FromDict(result).data,
                           [[(constants.RS_NORMAL, name),
                             (constants.RS_NORMAL, None),
                             (constants.RS_NORMAL, None)]
                            for name in utils.NiceSort(expnames)])

  def testDelete(self):
    lock = locking.SharedLock("TestLock", monitor=self.lm)

    self.assertEqual(len(self.lm._locks), 1)
    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data,
                     [[(constants.RS_NORMAL, lock.name),
                       (constants.RS_NORMAL, None),
                       (constants.RS_NORMAL, None)]])

    lock.delete()

    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data,
                     [[(constants.RS_NORMAL, lock.name),
                       (constants.RS_NORMAL, "deleted"),
                       (constants.RS_NORMAL, None)]])
    self.assertEqual(len(self.lm._locks), 1)

  def testPending(self):
    def _Acquire(lock, shared, prev, next):
      prev.wait()

      lock.acquire(shared=shared, test_notify=next.set)
      try:
        pass
      finally:
        lock.release()

    lock = locking.SharedLock("ExcLock", monitor=self.lm)

    for shared in [0, 1]:
      lock.acquire()
      try:
        self.assertEqual(len(self.lm._locks), 1)
        result = self.lm.QueryLocks(["name", "mode", "owner"])
        self.assertEqual(objects.QueryResponse.FromDict(result).data,
                         [[(constants.RS_NORMAL, lock.name),
                           (constants.RS_NORMAL, "exclusive"),
                           (constants.RS_NORMAL,
                            [threading.currentThread().getName()])]])

        threads = []

        first = threading.Event()
        prev = first

        for i in range(5):
          ev = threading.Event()
          threads.append(self._addThread(target=_Acquire,
                                          args=(lock, shared, prev, ev)))
          prev = ev

        # Start acquires
        first.set()

        # Wait for last acquire to start waiting
        prev.wait()

        # NOTE: This works only because QueryLocks will acquire the
        # lock-internal lock again and won't be able to get the information
        # until it has the lock. By then the acquire should be registered in
        # SharedLock.__pending (otherwise it's a bug).

        # All acquires are waiting now
        if shared:
          pending = [("shared", utils.NiceSort(t.getName() for t in threads))]
        else:
          pending = [("exclusive", [t.getName()]) for t in threads]

        result = self.lm.QueryLocks(["name", "mode", "owner", "pending"])
        self.assertEqual(objects.QueryResponse.FromDict(result).data,
                         [[(constants.RS_NORMAL, lock.name),
                           (constants.RS_NORMAL, "exclusive"),
                           (constants.RS_NORMAL,
                            [threading.currentThread().getName()]),
                           (constants.RS_NORMAL, pending)]])

        self.assertEqual(len(self.lm._locks), 1)
      finally:
        lock.release()

      self._waitThreads()

      # No pending acquires
      result = self.lm.QueryLocks(["name", "mode", "owner", "pending"])
      self.assertEqual(objects.QueryResponse.FromDict(result).data,
                       [[(constants.RS_NORMAL, lock.name),
                         (constants.RS_NORMAL, None),
                         (constants.RS_NORMAL, None),
                         (constants.RS_NORMAL, [])]])

      self.assertEqual(len(self.lm._locks), 1)

  def testDeleteAndRecreate(self):
    lname = "TestLock101923193"

    # Create some locks with the same name and keep all references
    locks = [locking.SharedLock(lname, monitor=self.lm)
             for _ in range(5)]

    self.assertEqual(len(self.lm._locks), len(locks))

    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data,
                     [[(constants.RS_NORMAL, lname),
                       (constants.RS_NORMAL, None),
                       (constants.RS_NORMAL, None)]] * 5)

    locks[2].delete()

    # Check information order
    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data,
                     [[(constants.RS_NORMAL, lname),
                       (constants.RS_NORMAL, None),
                       (constants.RS_NORMAL, None)]] * 2 +
                     [[(constants.RS_NORMAL, lname),
                       (constants.RS_NORMAL, "deleted"),
                       (constants.RS_NORMAL, None)]] +
                     [[(constants.RS_NORMAL, lname),
                       (constants.RS_NORMAL, None),
                       (constants.RS_NORMAL, None)]] * 2)

    locks[1].acquire(shared=0)

    last_status = [
      [(constants.RS_NORMAL, lname),
       (constants.RS_NORMAL, None),
       (constants.RS_NORMAL, None)],
      [(constants.RS_NORMAL, lname),
       (constants.RS_NORMAL, "exclusive"),
       (constants.RS_NORMAL, [threading.currentThread().getName()])],
      [(constants.RS_NORMAL, lname),
       (constants.RS_NORMAL, "deleted"),
       (constants.RS_NORMAL, None)],
      [(constants.RS_NORMAL, lname),
       (constants.RS_NORMAL, None),
       (constants.RS_NORMAL, None)],
      [(constants.RS_NORMAL, lname),
       (constants.RS_NORMAL, None),
       (constants.RS_NORMAL, None)],
      ]

    # Check information order
    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data, last_status)

    self.assertEqual(len(set(self.lm._locks.values())), len(locks))
    self.assertEqual(len(self.lm._locks), len(locks))

    # Check lock deletion
    for idx in range(len(locks)):
      del locks[0]
      assert gc.isenabled()
      gc.collect()
      self.assertEqual(len(self.lm._locks), len(locks))
      result = self.lm.QueryLocks(["name", "mode", "owner"])
      self.assertEqual(objects.QueryResponse.FromDict(result).data,
                       last_status[idx + 1:])

    # All locks should have been deleted
    assert not locks
    self.assertFalse(self.lm._locks)

    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data, [])

  class _FakeLock:
    def __init__(self):
      self._info = []

    def AddResult(self, *args):
      self._info.append(args)

    def CountPending(self):
      return len(self._info)

    def GetLockInfo(self, requested):
      (exp_requested, result) = self._info.pop(0)

      if exp_requested != requested:
        raise Exception("Requested information (%s) does not match"
                        " expectations (%s)" % (requested, exp_requested))

      return result

  def testMultipleResults(self):
    fl1 = self._FakeLock()
    fl2 = self._FakeLock()

    self.lm.RegisterLock(fl1)
    self.lm.RegisterLock(fl2)

    # Empty information
    for i in [fl1, fl2]:
      i.AddResult(set([query.LQ_MODE, query.LQ_OWNER]), [])
    result = self.lm.QueryLocks(["name", "mode", "owner"])
    self.assertEqual(objects.QueryResponse.FromDict(result).data, [])
    for i in [fl1, fl2]:
      self.assertEqual(i.CountPending(), 0)

    # Check ordering
    for fn in [lambda x: x, reversed, sorted]:
      fl1.AddResult(set(), list(fn([
        ("aaa", None, None, None),
        ("bbb", None, None, None),
        ])))
      fl2.AddResult(set(), [])
      result = self.lm.QueryLocks(["name"])
      self.assertEqual(objects.QueryResponse.FromDict(result).data, [
        [(constants.RS_NORMAL, "aaa")],
        [(constants.RS_NORMAL, "bbb")],
        ])
      for i in [fl1, fl2]:
        self.assertEqual(i.CountPending(), 0)

      for fn2 in [lambda x: x, reversed, sorted]:
        fl1.AddResult(set([query.LQ_MODE]), list(fn([
          # Same name, but different information
          ("aaa", "mode0", None, None),
          ("aaa", "mode1", None, None),
          ("aaa", "mode2", None, None),
          ("aaa", "mode3", None, None),
          ])))
        fl2.AddResult(set([query.LQ_MODE]), [
          ("zzz", "end", None, None),
          ("000", "start", None, None),
          ] + list(fn2([
          ("aaa", "b200", None, None),
          ("aaa", "b300", None, None),
          ])))
        result = self.lm.QueryLocks(["name", "mode"])
        self.assertEqual(objects.QueryResponse.FromDict(result).data, [
          [(constants.RS_NORMAL, "000"), (constants.RS_NORMAL, "start")],
          ] + list(fn([
          # Name is the same, so order must be equal to incoming order
          [(constants.RS_NORMAL, "aaa"), (constants.RS_NORMAL, "mode0")],
          [(constants.RS_NORMAL, "aaa"), (constants.RS_NORMAL, "mode1")],
          [(constants.RS_NORMAL, "aaa"), (constants.RS_NORMAL, "mode2")],
          [(constants.RS_NORMAL, "aaa"), (constants.RS_NORMAL, "mode3")],
          ])) + list(fn2([
          [(constants.RS_NORMAL, "aaa"), (constants.RS_NORMAL, "b200")],
          [(constants.RS_NORMAL, "aaa"), (constants.RS_NORMAL, "b300")],
          ])) + [
          [(constants.RS_NORMAL, "zzz"), (constants.RS_NORMAL, "end")],
          ])
        for i in [fl1, fl2]:
          self.assertEqual(i.CountPending(), 0)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
