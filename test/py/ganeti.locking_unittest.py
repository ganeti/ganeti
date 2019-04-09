#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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


"""Script for unittesting the locking module"""


import os
import unittest
import time
import queue
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
    self.done = queue.Queue(0)
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
      self.assertFalse(t.is_alive())
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
    self.assertTrue(self.cond._is_owned())
    self.cond.notifyAll()
    self.assertTrue(self.cond._is_owned())
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
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.cond.wait(None)
    self.assertEqual(self.done.get(True, 1), "NA")
    self.assertEqual(self.done.get(True, 1), "NN")
    self.assertTrue(self.cond._is_owned())
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

    self.assertRaises(queue.Empty, self.done.get_nowait)

    self.cond.acquire()
    self.assertEqual(len(self.cond._waiters), 3)
    self.assertEqual(self.cond._waiters, set(threads))

    self.assertTrue(repr(self.cond).startswith("<"))
    self.assertTrue("waiters=" in repr(self.cond))

    # This new thread can't acquire the lock, and thus call wait, before we
    # release it
    self._addThread(target=fn)
    self.cond.notifyAll()
    self.assertRaises(queue.Empty, self.done.get_nowait)
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
    self.assertRaises(queue.Empty, self.done.get_nowait)

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
    self.assertRaises(queue.Empty, self.done.get_nowait)

  def testZeroTimeoutWait(self):
    self._addThread(target=self._TimeoutWait, args=(0, "T0"))
    self._addThread(target=self._TimeoutWait, args=(0, "T0"))
    self._addThread(target=self._TimeoutWait, args=(0, "T0"))
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "T0")
    self.assertEqual(self.done.get_nowait(), "T0")
    self.assertEqual(self.done.get_nowait(), "T0")
    self.assertRaises(queue.Empty, self.done.get_nowait)


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
    self.assertTrue(self.sl.is_owned())
    self.assertTrue(self.sl.is_owned(shared=1))
    self.assertFalse(self.sl.is_owned(shared=0))
    self.sl.release()
    self.assertFalse(self.sl.is_owned())
    self.sl.acquire()
    self.assertTrue(self.sl.is_owned())
    self.assertFalse(self.sl.is_owned(shared=1))
    self.assertTrue(self.sl.is_owned(shared=0))
    self.sl.release()
    self.assertFalse(self.sl.is_owned())
    self.sl.acquire(shared=1)
    self.assertTrue(self.sl.is_owned())
    self.assertTrue(self.sl.is_owned(shared=1))
    self.assertFalse(self.sl.is_owned(shared=0))
    self.sl.release()
    self.assertFalse(self.sl.is_owned())

  def testBooleanValue(self):
    # semaphores are supposed to return a true value on a successful acquire
    self.assertTrue(self.sl.acquire(shared=1))
    self.sl.release()
    self.assertTrue(self.sl.acquire())
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
    self.assertTrue(self.done.get(True, 1))
    self.sl.release()

  @_Repeat
  def testExclusiveBlocksExclusive(self):
    self.sl.acquire()
    self._addThread(target=self._doItExclusive)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "EXC")

  @_Repeat
  def testExclusiveBlocksDelete(self):
    self.sl.acquire()
    self._addThread(target=self._doItDelete)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DEL")
    self.sl = locking.SharedLock(self.sl.name)

  @_Repeat
  def testExclusiveBlocksSharer(self):
    self.sl.acquire()
    self._addThread(target=self._doItSharer)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "SHR")

  @_Repeat
  def testSharerBlocksExclusive(self):
    self.sl.acquire(shared=1)
    self._addThread(target=self._doItExclusive)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "EXC")

  @_Repeat
  def testSharerBlocksDelete(self):
    self.sl.acquire(shared=1)
    self._addThread(target=self._doItDelete)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "DEL")
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
    self.assertRaises(queue.Empty, self.done.get_nowait)
    self.sl.release()
    self._waitThreads()
    # The exclusive passed before
    self.assertEqual(self.done.get_nowait(), "EXC")
    self.assertEqual(self.done.get_nowait(), "SHR")

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
    self.assertRaises(queue.Empty, self.done.get_nowait)
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
      self.assertTrue(self.sl.acquire(shared=shared, timeout=60,
                                      test_notify=release_exclusive.set))

      self.done.put("got 2nd")
      self.sl.release()

      self._waitThreads()

      self.assertEqual(self.done.get_nowait(), "A: end wait")
      self.assertEqual(self.done.get_nowait(), "got 2nd")
      self.assertRaises(queue.Empty, self.done.get_nowait)

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

      self.assertRaises(queue.Empty, self.done.get_nowait)

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

    self.assertRaises(queue.Empty, self.done.get_nowait)

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
    self.assertFalse(self.sl.acquire(shared=0, timeout=0.02))

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
    self.assertFalse(self.sl.acquire(shared=0, timeout=0.02))

    # Make all shared holders release their locks
    sync.set()

    # Wait for exclusive acquire to succeed
    exclev.wait()

    self.assertEqual(self.sl._count_pending(), 0)

    # Try to get exclusive lock
    self.assertFalse(self.sl.acquire(shared=0, timeout=0.02))

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

    self.assertRaises(queue.Empty, self.done.get_nowait)

  def testPriority(self):
    # Acquire in exclusive mode
    self.assertTrue(self.sl.acquire(shared=0))

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
          acqname = "%s/shr=%s/prio=%s" % (next(counter), shared, priority)

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

    self.assertTrue(self.sl._check_empty())

    # Check acquires by priority
    for acquires in [perprio[i] for i in sorted(perprio.keys())]:
      for (_, names, _) in acquires:
        # For shared acquires, the set will contain 1..n entries. For exclusive
        # acquires only one.
        while names:
          names.remove(self.done.get_nowait())
      self.assertFalse(compat.any(names for (_, names, _) in acquires))

    self.assertRaises(queue.Empty, self.done.get_nowait)

  def _VerifyPrioPending(self, lockinfo, perprio):
    ((name, mode, owner, pending), ) = lockinfo
    self.assertEqual(name, self.sl.name)
    self.assertTrue(mode is None)
    self.assertTrue(owner is None)

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
    req = queue.Queue(0)

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
    self.assertRaises(queue.Empty, self.done.get_nowait)


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
    self.assertTrue(self.sl.is_owned(shared=1))
    self.cond.wait(0)
    self.assertTrue(self.sl.is_owned(shared=1))
    self.cond.release()
    self.cond.acquire(shared=0)
    self.assertTrue(self.sl.is_owned(shared=0))
    self.cond.wait(0)
    self.assertTrue(self.sl.is_owned(shared=0))
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
    self.assertTrue(_decoratorlock.is_owned())
    self.done.put("EXC")

  @locking.ssynchronized(_decoratorlock, shared=1)
  def _doItSharer(self):
    self.assertTrue(_decoratorlock.is_owned(shared=1))
    self.done.put("SHR")

  def testDecoratedFunctions(self):
    self._doItExclusive()
    self.assertFalse(_decoratorlock.is_owned())
    self._doItSharer()
    self.assertFalse(_decoratorlock.is_owned())

  def testSharersCanCoexist(self):
    _decoratorlock.acquire(shared=1)
    threading.Thread(target=self._doItSharer).start()
    self.assertTrue(self.done.get(True, 1))
    _decoratorlock.release()

  @_Repeat
  def testExclusiveBlocksExclusive(self):
    _decoratorlock.acquire()
    self._addThread(target=self._doItExclusive)
    # give it a bit of time to check that it's not actually doing anything
    self.assertRaises(queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "EXC")

  @_Repeat
  def testExclusiveBlocksSharer(self):
    _decoratorlock.acquire()
    self._addThread(target=self._doItSharer)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "SHR")

  @_Repeat
  def testSharerBlocksExclusive(self):
    _decoratorlock.acquire(shared=1)
    self._addThread(target=self._doItExclusive)
    self.assertRaises(queue.Empty, self.done.get_nowait)
    _decoratorlock.release()
    self._waitThreads()
    self.assertEqual(self.done.get_nowait(), "EXC")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
