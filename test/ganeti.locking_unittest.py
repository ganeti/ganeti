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
from ganeti import errors
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

  def testExclusiveBlocksDelete(self):
    self.sl.acquire()
    Thread(target=self._doItDelete).start()
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

  def testSharerBlocksDelete(self):
    self.sl.acquire(shared=1)
    Thread(target=self._doItDelete).start()
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

  def testNoNonBlocking(self):
    self.assertRaises(NotImplementedError, self.sl.acquire, blocking=0)
    self.assertRaises(NotImplementedError, self.sl.delete, blocking=0)
    self.sl.acquire()
    self.sl.delete(blocking=0) # Fine, because the lock is already acquired

  def testDelete(self):
    self.sl.delete()
    self.assertRaises(errors.LockError, self.sl.acquire)
    self.assertRaises(errors.LockError, self.sl.acquire, shared=1)
    self.assertRaises(errors.LockError, self.sl.delete)

  def testNoDeleteIfSharer(self):
    self.sl.acquire(shared=1)
    self.assertRaises(AssertionError, self.sl.delete)

  def testDeletePendingSharersExclusiveDelete(self):
    self.sl.acquire()
    Thread(target=self._doItSharer).start()
    Thread(target=self._doItSharer).start()
    time.sleep(0.05)
    Thread(target=self._doItExclusive).start()
    Thread(target=self._doItDelete).start()
    time.sleep(0.05)
    self.sl.delete()
    # The two threads who were pending return both ERR
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')

  def testDeletePendingDeleteExclusiveSharers(self):
    self.sl.acquire()
    Thread(target=self._doItDelete).start()
    Thread(target=self._doItExclusive).start()
    time.sleep(0.05)
    Thread(target=self._doItSharer).start()
    Thread(target=self._doItSharer).start()
    time.sleep(0.05)
    self.sl.delete()
    # The two threads who were pending return both ERR
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')


class TestLockSet(unittest.TestCase):
  """LockSet tests"""

  def setUp(self):
    self.resources = ['one', 'two', 'three']
    self.ls = locking.LockSet(self.resources)
    # helper threads use the 'done' queue to tell the master they finished.
    self.done = Queue.Queue(0)

  def testResources(self):
    self.assertEquals(self.ls._names(), set(self.resources))
    newls = locking.LockSet()
    self.assertEquals(newls._names(), set())

  def testAcquireRelease(self):
    self.ls.acquire('one')
    self.assertEquals(self.ls._list_owned(), set(['one']))
    self.ls.release()
    self.assertEquals(self.ls._list_owned(), set())
    self.ls.acquire(['one'])
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
    self.ls.acquire(['one', 'three'])
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
    self.ls.remove(['five', 'six'])
    self.assert_('five' not in self.ls._names())
    self.assert_('six' not in self.ls._names())
    self.assertEquals(self.ls._list_owned(), set(['seven']))
    self.ls.add('eight', acquired=1, shared=1)
    self.assert_('eight' in self.ls._names())
    self.assertEquals(self.ls._list_owned(), set(['seven', 'eight']))
    self.ls.remove('seven')
    self.assert_('seven' not in self.ls._names())
    self.assertEquals(self.ls._list_owned(), set(['eight']))
    self.ls.release()
    self.ls.remove(['two'])
    self.assert_('two' not in self.ls._names())
    self.ls.acquire('three')
    self.ls.remove(['three'])
    self.assert_('three' not in self.ls._names())
    self.assertEquals(self.ls.remove('three'), ['three'])
    self.assertEquals(self.ls.remove(['one', 'three', 'six']), ['three', 'six'])
    self.assert_('one' not in self.ls._names())

  def testRemoveNonBlocking(self):
    self.assertRaises(NotImplementedError, self.ls.remove, 'one', blocking=0)
    self.ls.acquire('one')
    self.assertEquals(self.ls.remove('one', blocking=0), [])
    self.ls.acquire(['two', 'three'])
    self.assertEquals(self.ls.remove(['two', 'three'], blocking=0), [])

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

  def _doLockSet(self, set, shared):
    try:
      self.ls.acquire(set, shared=shared)
      self.done.put('DONE')
      self.ls.release()
    except errors.LockError:
      self.done.put('ERR')

  def _doRemoveSet(self, set):
    self.done.put(self.ls.remove(set))

  def testConcurrentSharedAcquire(self):
    self.ls.acquire(['one', 'two'], shared=1)
    Thread(target=self._doLockSet, args=(['one', 'two'], 1)).start()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    Thread(target=self._doLockSet, args=(['one', 'two', 'three'], 1)).start()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    Thread(target=self._doLockSet, args=('three', 1)).start()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    Thread(target=self._doLockSet, args=(['one', 'two'], 0)).start()
    Thread(target=self._doLockSet, args=(['two', 'three'], 0)).start()
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.ls.release()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')

  def testConcurrentExclusiveAcquire(self):
    self.ls.acquire(['one', 'two'])
    Thread(target=self._doLockSet, args=('three', 1)).start()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    Thread(target=self._doLockSet, args=('three', 0)).start()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    Thread(target=self._doLockSet, args=(['one', 'two'], 0)).start()
    Thread(target=self._doLockSet, args=(['one', 'two'], 1)).start()
    Thread(target=self._doLockSet, args=('one', 0)).start()
    Thread(target=self._doLockSet, args=('one', 1)).start()
    Thread(target=self._doLockSet, args=(['two', 'three'], 0)).start()
    Thread(target=self._doLockSet, args=(['two', 'three'], 1)).start()
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.ls.release()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')

  def testConcurrentRemove(self):
    self.ls.add('four')
    self.ls.acquire(['one', 'two', 'four'])
    Thread(target=self._doLockSet, args=(['one', 'four'], 0)).start()
    Thread(target=self._doLockSet, args=(['one', 'four'], 1)).start()
    Thread(target=self._doLockSet, args=(['one', 'two'], 0)).start()
    Thread(target=self._doLockSet, args=(['one', 'two'], 1)).start()
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.ls.remove('one')
    self.ls.release()
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.assertEqual(self.done.get(True, 1), 'ERR')
    self.ls.add(['five', 'six'], acquired=1)
    Thread(target=self._doLockSet, args=(['three', 'six'], 1)).start()
    Thread(target=self._doLockSet, args=(['three', 'six'], 0)).start()
    Thread(target=self._doLockSet, args=(['four', 'six'], 1)).start()
    Thread(target=self._doLockSet, args=(['four', 'six'], 0)).start()
    self.ls.remove('five')
    self.ls.release()
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.assertEqual(self.done.get(True, 1), 'DONE')
    self.ls.acquire(['three', 'four'])
    Thread(target=self._doRemoveSet, args=(['four', 'six'], )).start()
    self.assertRaises(Queue.Empty, self.done.get, True, 0.2)
    self.ls.remove('four')
    self.assertEqual(self.done.get(True, 1), ['four'])
    Thread(target=self._doRemoveSet, args=(['two'])).start()
    self.assertEqual(self.done.get(True, 1), [])
    self.ls.release()


if __name__ == '__main__':
  unittest.main()
  #suite = unittest.TestLoader().loadTestsFromTestCase(TestSharedLock)
  #unittest.TextTestRunner(verbosity=2).run(suite)
