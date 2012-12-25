#!/usr/bin/python
#

# Copyright (C) 2008, 2009, 2010 Google Inc.
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


"""Script for unittesting the workerpool module"""

import unittest
import threading
import time
import sys
import zlib
import random

from ganeti import workerpool
from ganeti import errors
from ganeti import utils
from ganeti import compat

import testutils


class CountingContext(object):
  def __init__(self):
    self._lock = threading.Condition(threading.Lock())
    self.done = 0

  def DoneTask(self):
    self._lock.acquire()
    try:
      self.done += 1
    finally:
      self._lock.release()

  def GetDoneTasks(self):
    self._lock.acquire()
    try:
      return self.done
    finally:
      self._lock.release()

  @staticmethod
  def UpdateChecksum(current, value):
    return zlib.adler32(str(value), current)


class CountingBaseWorker(workerpool.BaseWorker):
  def RunTask(self, ctx, text):
    ctx.DoneTask()


class ChecksumContext:
  CHECKSUM_START = zlib.adler32("")

  def __init__(self):
    self.lock = threading.Condition(threading.Lock())
    self.checksum = self.CHECKSUM_START

  @staticmethod
  def UpdateChecksum(current, value):
    return zlib.adler32(str(value), current)


class ChecksumBaseWorker(workerpool.BaseWorker):
  def RunTask(self, ctx, number):
    name = "number%s" % number
    self.SetTaskName(name)

    # This assertion needs to be checked before updating the checksum. A
    # failing assertion will then cause the result to be wrong.
    assert self.getName() == ("%s/%s" % (self._worker_id, name))

    ctx.lock.acquire()
    try:
      ctx.checksum = ctx.UpdateChecksum(ctx.checksum, number)
    finally:
      ctx.lock.release()


class ListBuilderContext:
  def __init__(self):
    self.lock = threading.Lock()
    self.result = []
    self.prioresult = {}


class ListBuilderWorker(workerpool.BaseWorker):
  def RunTask(self, ctx, data):
    ctx.lock.acquire()
    try:
      ctx.result.append((self.GetCurrentPriority(), data))
      ctx.prioresult.setdefault(self.GetCurrentPriority(), []).append(data)
    finally:
      ctx.lock.release()


class DeferringTaskContext:
  def __init__(self):
    self.lock = threading.Lock()
    self.prioresult = {}
    self.samepriodefer = {}
    self.num2ordertaskid = {}


class DeferringWorker(workerpool.BaseWorker):
  def RunTask(self, ctx, num, targetprio):
    ctx.lock.acquire()
    try:
      otilst = ctx.num2ordertaskid.setdefault(num, [])
      otilst.append(self._GetCurrentOrderAndTaskId())

      if num in ctx.samepriodefer:
        del ctx.samepriodefer[num]
        raise workerpool.DeferTask()

      if self.GetCurrentPriority() > targetprio:
        raise workerpool.DeferTask(priority=self.GetCurrentPriority() - 1)

      ctx.prioresult.setdefault(self.GetCurrentPriority(), set()).add(num)
    finally:
      ctx.lock.release()


class PriorityContext:
  def __init__(self):
    self.lock = threading.Lock()
    self.result = []


class PriorityWorker(workerpool.BaseWorker):
  def RunTask(self, ctx, data):
    ctx.lock.acquire()
    try:
      ctx.result.append((self.GetCurrentPriority(), data))
    finally:
      ctx.lock.release()


class NotImplementedWorker(workerpool.BaseWorker):
  def RunTask(self):
    raise NotImplementedError


class TestWorkerpool(unittest.TestCase):
  """Workerpool tests"""

  def testCounting(self):
    ctx = CountingContext()
    wp = workerpool.WorkerPool("Test", 3, CountingBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)

      for i in range(10):
        wp.AddTask((ctx, "Hello world %s" % i))

      wp.Quiesce()
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

    self.assertEquals(ctx.GetDoneTasks(), 10)

  def testNoTasks(self):
    wp = workerpool.WorkerPool("Test", 3, CountingBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)
      self._CheckNoTasks(wp)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testNoTasksQuiesce(self):
    wp = workerpool.WorkerPool("Test", 3, CountingBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)
      self._CheckNoTasks(wp)
      wp.Quiesce()
      self._CheckNoTasks(wp)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testActive(self):
    ctx = CountingContext()
    wp = workerpool.WorkerPool("TestActive", 5, CountingBaseWorker)
    try:
      self._CheckWorkerCount(wp, 5)
      self.assertTrue(wp._active)

      # Process some tasks
      for _ in range(10):
        wp.AddTask((ctx, None))

      wp.Quiesce()
      self._CheckNoTasks(wp)
      self.assertEquals(ctx.GetDoneTasks(), 10)

      # Repeat a few times
      for count in range(10):
        # Deactivate pool
        wp.SetActive(False)
        self._CheckNoTasks(wp)

        # Queue some more tasks
        for _ in range(10):
          wp.AddTask((ctx, None))

        for _ in range(5):
          # Short delays to give other threads a chance to cause breakage
          time.sleep(.01)
          wp.AddTask((ctx, "Hello world %s" % 999))
          self.assertFalse(wp._active)

        self.assertEquals(ctx.GetDoneTasks(), 10 + (count * 15))

        # Start processing again
        wp.SetActive(True)
        self.assertTrue(wp._active)

        # Wait for tasks to finish
        wp.Quiesce()
        self._CheckNoTasks(wp)
        self.assertEquals(ctx.GetDoneTasks(), 10 + (count * 15) + 15)

        self._CheckWorkerCount(wp, 5)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testChecksum(self):
    # Tests whether all tasks are run and, since we're only using a single
    # thread, whether everything is started in order.
    wp = workerpool.WorkerPool("Test", 1, ChecksumBaseWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = ChecksumContext()
      checksum = ChecksumContext.CHECKSUM_START
      for i in range(1, 100):
        checksum = ChecksumContext.UpdateChecksum(checksum, i)
        wp.AddTask((ctx, i))

      wp.Quiesce()

      self._CheckNoTasks(wp)

      # Check sum
      ctx.lock.acquire()
      try:
        self.assertEqual(checksum, ctx.checksum)
      finally:
        ctx.lock.release()
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testAddManyTasks(self):
    ctx = CountingContext()
    wp = workerpool.WorkerPool("Test", 3, CountingBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)

      wp.AddManyTasks([(ctx, "Hello world %s" % i, ) for i in range(10)])
      wp.AddTask((ctx, "A separate hello"))
      wp.AddTask((ctx, "Once more, hi!"))
      wp.AddManyTasks([(ctx, "Hello world %s" % i, ) for i in range(10)])

      wp.Quiesce()

      self._CheckNoTasks(wp)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

    self.assertEquals(ctx.GetDoneTasks(), 22)

  def testManyTasksSequence(self):
    ctx = CountingContext()
    wp = workerpool.WorkerPool("Test", 3, CountingBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)
      self.assertRaises(AssertionError, wp.AddManyTasks,
                        ["Hello world %s" % i for i in range(10)])
      self.assertRaises(AssertionError, wp.AddManyTasks,
                        [i for i in range(10)])
      self.assertRaises(AssertionError, wp.AddManyTasks, [], task_id=0)

      wp.AddManyTasks([(ctx, "Hello world %s" % i, ) for i in range(10)])
      wp.AddTask((ctx, "A separate hello"))

      wp.Quiesce()

      self._CheckNoTasks(wp)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

    self.assertEquals(ctx.GetDoneTasks(), 11)

  def _CheckNoTasks(self, wp):
    wp._lock.acquire()
    try:
      # The task queue must be empty now
      self.assertFalse(wp._tasks)
      self.assertFalse(wp._taskdata)
    finally:
      wp._lock.release()

  def _CheckWorkerCount(self, wp, num_workers):
    wp._lock.acquire()
    try:
      self.assertEqual(len(wp._workers), num_workers)
    finally:
      wp._lock.release()

  def testPriorityChecksum(self):
    # Tests whether all tasks are run and, since we're only using a single
    # thread, whether everything is started in order and respects the priority
    wp = workerpool.WorkerPool("Test", 1, ChecksumBaseWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = ChecksumContext()

      data = {}
      tasks = []
      priorities = []
      for i in range(1, 333):
        prio = i % 7
        tasks.append((ctx, i))
        priorities.append(prio)
        data.setdefault(prio, []).append(i)

      wp.AddManyTasks(tasks, priority=priorities)

      wp.Quiesce()

      self._CheckNoTasks(wp)

      # Check sum
      ctx.lock.acquire()
      try:
        checksum = ChecksumContext.CHECKSUM_START
        for priority in sorted(data.keys()):
          for i in data[priority]:
            checksum = ChecksumContext.UpdateChecksum(checksum, i)

        self.assertEqual(checksum, ctx.checksum)
      finally:
        ctx.lock.release()

      self._CheckWorkerCount(wp, 1)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testPriorityListManyTasks(self):
    # Tests whether all tasks are run and, since we're only using a single
    # thread, whether everything is started in order and respects the priority
    wp = workerpool.WorkerPool("Test", 1, ListBuilderWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = ListBuilderContext()

      # Use static seed for this test
      rnd = random.Random(0)

      data = {}
      tasks = []
      priorities = []
      for i in range(1, 333):
        prio = int(rnd.random() * 10)
        tasks.append((ctx, i))
        priorities.append(prio)
        data.setdefault(prio, []).append((prio, i))

      wp.AddManyTasks(tasks, priority=priorities)

      self.assertRaises(errors.ProgrammerError, wp.AddManyTasks,
                        [("x", ), ("y", )], priority=[1] * 5)
      self.assertRaises(errors.ProgrammerError, wp.AddManyTasks,
                        [("x", ), ("y", )], task_id=[1] * 5)

      wp.Quiesce()

      self._CheckNoTasks(wp)

      # Check result
      ctx.lock.acquire()
      try:
        expresult = []
        for priority in sorted(data.keys()):
          expresult.extend(data[priority])

        self.assertEqual(expresult, ctx.result)
      finally:
        ctx.lock.release()

      self._CheckWorkerCount(wp, 1)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testPriorityListSingleTasks(self):
    # Tests whether all tasks are run and, since we're only using a single
    # thread, whether everything is started in order and respects the priority
    wp = workerpool.WorkerPool("Test", 1, ListBuilderWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = ListBuilderContext()

      # Use static seed for this test
      rnd = random.Random(26279)

      data = {}
      for i in range(1, 333):
        prio = int(rnd.random() * 30)
        wp.AddTask((ctx, i), priority=prio)
        data.setdefault(prio, []).append(i)

        # Cause some distortion
        if i % 11 == 0:
          time.sleep(.001)
        if i % 41 == 0:
          wp.Quiesce()

      wp.Quiesce()

      self._CheckNoTasks(wp)

      # Check result
      ctx.lock.acquire()
      try:
        self.assertEqual(data, ctx.prioresult)
      finally:
        ctx.lock.release()

      self._CheckWorkerCount(wp, 1)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testDeferTask(self):
    # Tests whether all tasks are run and, since we're only using a single
    # thread, whether everything is started in order and respects the priority
    wp = workerpool.WorkerPool("Test", 1, DeferringWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = DeferringTaskContext()

      # Use static seed for this test
      rnd = random.Random(14921)

      data = {}
      num2taskid = {}
      for i in range(1, 333):
        ctx.lock.acquire()
        try:
          if i % 5 == 0:
            ctx.samepriodefer[i] = True
        finally:
          ctx.lock.release()

        prio = int(rnd.random() * 30)
        num2taskid[i] = 1000 * i
        wp.AddTask((ctx, i, prio), priority=50,
                   task_id=num2taskid[i])
        data.setdefault(prio, set()).add(i)

        # Cause some distortion
        if i % 24 == 0:
          time.sleep(.001)
        if i % 31 == 0:
          wp.Quiesce()

      wp.Quiesce()

      self._CheckNoTasks(wp)

      # Check result
      ctx.lock.acquire()
      try:
        self.assertEqual(data, ctx.prioresult)

        all_order_ids = []

        for (num, numordertaskid) in ctx.num2ordertaskid.items():
          order_ids = map(compat.fst, numordertaskid)
          self.assertFalse(utils.FindDuplicates(order_ids),
                           msg="Order ID has been reused")
          all_order_ids.extend(order_ids)

          for task_id in map(compat.snd, numordertaskid):
            self.assertEqual(task_id, num2taskid[num],
                             msg=("Task %s used different task IDs" % num))

        self.assertFalse(utils.FindDuplicates(all_order_ids),
                         msg="Order ID has been reused")
      finally:
        ctx.lock.release()

      self._CheckWorkerCount(wp, 1)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testChangeTaskPriority(self):
    wp = workerpool.WorkerPool("Test", 1, PriorityWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = PriorityContext()

      # Use static seed for this test
      rnd = random.Random(4727)

      # Disable processing of tasks
      wp.SetActive(False)

      # No task ID
      self.assertRaises(workerpool.NoSuchTask, wp.ChangeTaskPriority,
                        None, 0)

      # Pre-generate task IDs and priorities
      count = 100
      task_ids = range(0, count)
      priorities = range(200, 200 + count) * 2

      rnd.shuffle(task_ids)
      rnd.shuffle(priorities)

      # Make sure there are some duplicate priorities, but not all
      priorities[count * 2 - 10:count * 2 - 1] = \
        priorities[count - 10: count - 1]

      assert len(priorities) == 2 * count
      assert priorities[0:(count - 1)] != priorities[count:(2 * count - 1)]

      # Add some tasks; this loop consumes the first half of all previously
      # generated priorities
      for (idx, task_id) in enumerate(task_ids):
        wp.AddTask((ctx, idx),
                   priority=priorities.pop(),
                   task_id=task_id)

      self.assertEqual(len(wp._tasks), len(task_ids))
      self.assertEqual(len(wp._taskdata), len(task_ids))

      # Tasks have been added, so half of the priorities should have been
      # consumed
      assert len(priorities) == len(task_ids)

      # Change task priority
      expected = []
      for ((idx, task_id), prio) in zip(enumerate(task_ids), priorities):
        wp.ChangeTaskPriority(task_id, prio)
        expected.append((prio, idx))

      self.assertEqual(len(wp._taskdata), len(task_ids))

      # Half the entries are now abandoned tasks
      self.assertEqual(len(wp._tasks), len(task_ids) * 2)

      assert len(priorities) == count
      assert len(task_ids) == count

      # Start processing
      wp.SetActive(True)

      # Wait for tasks to finish
      wp.Quiesce()

      self._CheckNoTasks(wp)

      for task_id in task_ids:
        # All tasks are done
        self.assertRaises(workerpool.NoSuchTask, wp.ChangeTaskPriority,
                          task_id, 0)

      # Check result
      ctx.lock.acquire()
      try:
        self.assertEqual(ctx.result, sorted(expected))
      finally:
        ctx.lock.release()

      self._CheckWorkerCount(wp, 1)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testChangeTaskPriorityInteralStructures(self):
    wp = workerpool.WorkerPool("Test", 1, NotImplementedWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      # Use static seed for this test
      rnd = random.Random(643)

      (num1, num2) = rnd.sample(range(1000), 2)

      # Disable processing of tasks
      wp.SetActive(False)

      self.assertFalse(wp._tasks)
      self.assertFalse(wp._taskdata)

      # No priority or task ID
      wp.AddTask(())
      self.assertEqual(wp._tasks, [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        ])
      self.assertFalse(wp._taskdata)

      # No task ID
      wp.AddTask((), priority=7413)
      self.assertEqual(wp._tasks, [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [7413, 1, None, ()],
        ])
      self.assertFalse(wp._taskdata)

      # Start adding real tasks
      wp.AddTask((), priority=10267659, task_id=num1)
      self.assertEqual(wp._tasks, [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [7413, 1, None, ()],
        [10267659, 2, num1, ()],
        ])
      self.assertEqual(wp._taskdata, {
        num1: [10267659, 2, num1, ()],
        })

      wp.AddTask((), priority=123, task_id=num2)
      self.assertEqual(sorted(wp._tasks), [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [123, 3, num2, ()],
        [7413, 1, None, ()],
        [10267659, 2, num1, ()],
        ])
      self.assertEqual(wp._taskdata, {
        num1: [10267659, 2, num1, ()],
        num2: [123, 3, num2, ()],
        })

      wp.ChangeTaskPriority(num1, 100)
      self.assertEqual(sorted(wp._tasks), [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [100, 2, num1, ()],
        [123, 3, num2, ()],
        [7413, 1, None, ()],
        [10267659, 2, num1, None],
        ])
      self.assertEqual(wp._taskdata, {
        num1: [100, 2, num1, ()],
        num2: [123, 3, num2, ()],
        })

      wp.ChangeTaskPriority(num2, 91337)
      self.assertEqual(sorted(wp._tasks), [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [100, 2, num1, ()],
        [123, 3, num2, None],
        [7413, 1, None, ()],
        [91337, 3, num2, ()],
        [10267659, 2, num1, None],
        ])
      self.assertEqual(wp._taskdata, {
        num1: [100, 2, num1, ()],
        num2: [91337, 3, num2, ()],
        })

      wp.ChangeTaskPriority(num1, 10139)
      self.assertEqual(sorted(wp._tasks), [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [100, 2, num1, None],
        [123, 3, num2, None],
        [7413, 1, None, ()],
        [10139, 2, num1, ()],
        [91337, 3, num2, ()],
        [10267659, 2, num1, None],
        ])
      self.assertEqual(wp._taskdata, {
        num1: [10139, 2, num1, ()],
        num2: [91337, 3, num2, ()],
        })

      # Change to the same priority once again
      wp.ChangeTaskPriority(num1, 10139)
      self.assertEqual(sorted(wp._tasks), [
        [workerpool._DEFAULT_PRIORITY, 0, None, ()],
        [100, 2, num1, None],
        [123, 3, num2, None],
        [7413, 1, None, ()],
        [10139, 2, num1, None],
        [10139, 2, num1, ()],
        [91337, 3, num2, ()],
        [10267659, 2, num1, None],
        ])
      self.assertEqual(wp._taskdata, {
        num1: [10139, 2, num1, ()],
        num2: [91337, 3, num2, ()],
        })

      self._CheckWorkerCount(wp, 1)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
