#!/usr/bin/python
#

# Copyright (C) 2008 Google Inc.
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

from ganeti import workerpool


class DummyBaseWorker(workerpool.BaseWorker):
  def RunTask(self, text):
    pass


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
    ctx.lock.acquire()
    try:
      ctx.checksum = ctx.UpdateChecksum(ctx.checksum, number)
    finally:
      ctx.lock.release()


class TestWorkerpool(unittest.TestCase):
  """Workerpool tests"""

  def testDummy(self):
    wp = workerpool.WorkerPool(3, DummyBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)

      for i in range(10):
        wp.AddTask("Hello world %s" % i)

      wp.Quiesce()
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testNoTasks(self):
    wp = workerpool.WorkerPool(3, DummyBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)
      self._CheckNoTasks(wp)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testNoTasksQuiesce(self):
    wp = workerpool.WorkerPool(3, DummyBaseWorker)
    try:
      self._CheckWorkerCount(wp, 3)
      self._CheckNoTasks(wp)
      wp.Quiesce()
      self._CheckNoTasks(wp)
    finally:
      wp.TerminateWorkers()
      self._CheckWorkerCount(wp, 0)

  def testChecksum(self):
    # Tests whether all tasks are run and, since we're only using a single
    # thread, whether everything is started in order.
    wp = workerpool.WorkerPool(1, ChecksumBaseWorker)
    try:
      self._CheckWorkerCount(wp, 1)

      ctx = ChecksumContext()
      checksum = ChecksumContext.CHECKSUM_START
      for i in range(1, 100):
        checksum = ChecksumContext.UpdateChecksum(checksum, i)
        wp.AddTask(ctx, i)

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

  def _CheckNoTasks(self, wp):
    wp._lock.acquire()
    try:
      # The task queue must be empty now
      self.failUnless(not wp._tasks)
    finally:
      wp._lock.release()

  def _CheckWorkerCount(self, wp, num_workers):
    wp._lock.acquire()
    try:
      self.assertEqual(len(wp._workers), num_workers)
    finally:
      wp._lock.release()


if __name__ == '__main__':
  unittest.main()
