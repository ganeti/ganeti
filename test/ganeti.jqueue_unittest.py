#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
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


"""Script for testing ganeti.jqueue"""

import os
import sys
import unittest
import tempfile
import shutil
import errno
import itertools
import random

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import jqueue
from ganeti import opcodes
from ganeti import compat
from ganeti import mcpu
from ganeti import query

import testutils


class _FakeJob:
  def __init__(self, job_id, status):
    self.id = job_id
    self.writable = False
    self._status = status
    self._log = []

  def SetStatus(self, status):
    self._status = status

  def AddLogEntry(self, msg):
    self._log.append((len(self._log), msg))

  def CalcStatus(self):
    return self._status

  def GetInfo(self, fields):
    result = []

    for name in fields:
      if name == "status":
        result.append(self._status)
      else:
        raise Exception("Unknown field")

    return result

  def GetLogEntries(self, newer_than):
    assert newer_than is None or newer_than >= 0

    if newer_than is None:
      return self._log

    return self._log[newer_than:]


class TestJobChangesChecker(unittest.TestCase):
  def testStatus(self):
    job = _FakeJob(9094, constants.JOB_STATUS_QUEUED)
    checker = jqueue._JobChangesChecker(["status"], None, None)
    self.assertEqual(checker(job), ([constants.JOB_STATUS_QUEUED], []))

    job.SetStatus(constants.JOB_STATUS_RUNNING)
    self.assertEqual(checker(job), ([constants.JOB_STATUS_RUNNING], []))

    job.SetStatus(constants.JOB_STATUS_SUCCESS)
    self.assertEqual(checker(job), ([constants.JOB_STATUS_SUCCESS], []))

    # job.id is used by checker
    self.assertEqual(job.id, 9094)

  def testStatusWithPrev(self):
    job = _FakeJob(12807, constants.JOB_STATUS_QUEUED)
    checker = jqueue._JobChangesChecker(["status"],
                                        [constants.JOB_STATUS_QUEUED], None)
    self.assert_(checker(job) is None)

    job.SetStatus(constants.JOB_STATUS_RUNNING)
    self.assertEqual(checker(job), ([constants.JOB_STATUS_RUNNING], []))

  def testFinalStatus(self):
    for status in constants.JOBS_FINALIZED:
      job = _FakeJob(2178711, status)
      checker = jqueue._JobChangesChecker(["status"], [status], None)
      # There won't be any changes in this status, hence it should signal
      # a change immediately
      self.assertEqual(checker(job), ([status], []))

  def testLog(self):
    job = _FakeJob(9094, constants.JOB_STATUS_RUNNING)
    checker = jqueue._JobChangesChecker(["status"], None, None)
    self.assertEqual(checker(job), ([constants.JOB_STATUS_RUNNING], []))

    job.AddLogEntry("Hello World")
    (job_info, log_entries) = checker(job)
    self.assertEqual(job_info, [constants.JOB_STATUS_RUNNING])
    self.assertEqual(log_entries, [[0, "Hello World"]])

    checker2 = jqueue._JobChangesChecker(["status"], job_info, len(log_entries))
    self.assert_(checker2(job) is None)

    job.AddLogEntry("Foo Bar")
    job.SetStatus(constants.JOB_STATUS_ERROR)

    (job_info, log_entries) = checker2(job)
    self.assertEqual(job_info, [constants.JOB_STATUS_ERROR])
    self.assertEqual(log_entries, [[1, "Foo Bar"]])

    checker3 = jqueue._JobChangesChecker(["status"], None, None)
    (job_info, log_entries) = checker3(job)
    self.assertEqual(job_info, [constants.JOB_STATUS_ERROR])
    self.assertEqual(log_entries, [[0, "Hello World"], [1, "Foo Bar"]])


class TestJobChangesWaiter(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.filename = utils.PathJoin(self.tmpdir, "job-1")
    utils.WriteFile(self.filename, data="")

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _EnsureNotifierClosed(self, notifier):
    try:
      os.fstat(notifier._fd)
    except EnvironmentError, err:
      self.assertEqual(err.errno, errno.EBADF)
    else:
      self.fail("File descriptor wasn't closed")

  def testClose(self):
    for wait in [False, True]:
      waiter = jqueue._JobFileChangesWaiter(self.filename)
      try:
        if wait:
          waiter.Wait(0.001)
      finally:
        waiter.Close()

      # Ensure file descriptor was closed
      self._EnsureNotifierClosed(waiter._notifier)

  def testChangingFile(self):
    waiter = jqueue._JobFileChangesWaiter(self.filename)
    try:
      self.assertFalse(waiter.Wait(0.1))
      utils.WriteFile(self.filename, data="changed")
      self.assert_(waiter.Wait(60))
    finally:
      waiter.Close()

    self._EnsureNotifierClosed(waiter._notifier)

  def testChangingFile2(self):
    waiter = jqueue._JobChangesWaiter(self.filename)
    try:
      self.assertFalse(waiter._filewaiter)
      self.assert_(waiter.Wait(0.1))
      self.assert_(waiter._filewaiter)

      # File waiter is now used, but there have been no changes
      self.assertFalse(waiter.Wait(0.1))
      utils.WriteFile(self.filename, data="changed")
      self.assert_(waiter.Wait(60))
    finally:
      waiter.Close()

    self._EnsureNotifierClosed(waiter._filewaiter._notifier)


class TestWaitForJobChangesHelper(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.filename = utils.PathJoin(self.tmpdir, "job-2614226563")
    utils.WriteFile(self.filename, data="")

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _LoadWaitingJob(self):
    return _FakeJob(2614226563, constants.JOB_STATUS_WAITING)

  def _LoadLostJob(self):
    return None

  def testNoChanges(self):
    wfjc = jqueue._WaitForJobChangesHelper()

    # No change
    self.assertEqual(wfjc(self.filename, self._LoadWaitingJob, ["status"],
                          [constants.JOB_STATUS_WAITING], None, 0.1),
                     constants.JOB_NOTCHANGED)

    # No previous information
    self.assertEqual(wfjc(self.filename, self._LoadWaitingJob,
                          ["status"], None, None, 1.0),
                     ([constants.JOB_STATUS_WAITING], []))

  def testLostJob(self):
    wfjc = jqueue._WaitForJobChangesHelper()
    self.assert_(wfjc(self.filename, self._LoadLostJob,
                      ["status"], None, None, 1.0) is None)


class TestEncodeOpError(unittest.TestCase):
  def test(self):
    encerr = jqueue._EncodeOpError(errors.LockError("Test 1"))
    self.assert_(isinstance(encerr, tuple))
    self.assertRaises(errors.LockError, errors.MaybeRaise, encerr)

    encerr = jqueue._EncodeOpError(errors.GenericError("Test 2"))
    self.assert_(isinstance(encerr, tuple))
    self.assertRaises(errors.GenericError, errors.MaybeRaise, encerr)

    encerr = jqueue._EncodeOpError(NotImplementedError("Foo"))
    self.assert_(isinstance(encerr, tuple))
    self.assertRaises(errors.OpExecError, errors.MaybeRaise, encerr)

    encerr = jqueue._EncodeOpError("Hello World")
    self.assert_(isinstance(encerr, tuple))
    self.assertRaises(errors.OpExecError, errors.MaybeRaise, encerr)


class TestQueuedOpCode(unittest.TestCase):
  def testDefaults(self):
    def _Check(op):
      self.assertFalse(hasattr(op.input, "dry_run"))
      self.assertEqual(op.priority, constants.OP_PRIO_DEFAULT)
      self.assertFalse(op.log)
      self.assert_(op.start_timestamp is None)
      self.assert_(op.exec_timestamp is None)
      self.assert_(op.end_timestamp is None)
      self.assert_(op.result is None)
      self.assertEqual(op.status, constants.OP_STATUS_QUEUED)

    op1 = jqueue._QueuedOpCode(opcodes.OpTestDelay())
    _Check(op1)
    op2 = jqueue._QueuedOpCode.Restore(op1.Serialize())
    _Check(op2)
    self.assertEqual(op1.Serialize(), op2.Serialize())

  def testPriority(self):
    def _Check(op):
      assert constants.OP_PRIO_DEFAULT != constants.OP_PRIO_HIGH, \
             "Default priority equals high priority; test can't work"
      self.assertEqual(op.priority, constants.OP_PRIO_HIGH)
      self.assertEqual(op.status, constants.OP_STATUS_QUEUED)

    inpop = opcodes.OpTagsGet(priority=constants.OP_PRIO_HIGH)
    op1 = jqueue._QueuedOpCode(inpop)
    _Check(op1)
    op2 = jqueue._QueuedOpCode.Restore(op1.Serialize())
    _Check(op2)
    self.assertEqual(op1.Serialize(), op2.Serialize())


class TestQueuedJob(unittest.TestCase):
  def test(self):
    self.assertRaises(errors.GenericError, jqueue._QueuedJob,
                      None, 1, [], False)

  def testDefaults(self):
    job_id = 4260
    ops = [
      opcodes.OpTagsGet(),
      opcodes.OpTestDelay(),
      ]

    def _Check(job):
      self.assertTrue(job.writable)
      self.assertEqual(job.id, job_id)
      self.assertEqual(job.log_serial, 0)
      self.assert_(job.received_timestamp)
      self.assert_(job.start_timestamp is None)
      self.assert_(job.end_timestamp is None)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
      self.assert_(repr(job).startswith("<"))
      self.assertEqual(len(job.ops), len(ops))
      self.assert_(compat.all(inp.__getstate__() == op.input.__getstate__()
                              for (inp, op) in zip(ops, job.ops)))
      self.assertRaises(errors.OpExecError, job.GetInfo,
                        ["unknown-field"])
      self.assertEqual(job.GetInfo(["summary"]),
                       [[op.input.Summary() for op in job.ops]])

    job1 = jqueue._QueuedJob(None, job_id, ops, True)
    _Check(job1)
    job2 = jqueue._QueuedJob.Restore(None, job1.Serialize(), True)
    _Check(job2)
    self.assertEqual(job1.Serialize(), job2.Serialize())

  def testWritable(self):
    job = jqueue._QueuedJob(None, 1, [opcodes.OpTestDelay()], False)
    self.assertFalse(job.writable)

    job = jqueue._QueuedJob(None, 1, [opcodes.OpTestDelay()], True)
    self.assertTrue(job.writable)

  def testPriority(self):
    job_id = 4283
    ops = [
      opcodes.OpTagsGet(priority=constants.OP_PRIO_DEFAULT),
      opcodes.OpTestDelay(),
      ]

    def _Check(job):
      self.assertEqual(job.id, job_id)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assert_(repr(job).startswith("<"))

    job = jqueue._QueuedJob(None, job_id, ops, True)
    _Check(job)
    self.assert_(compat.all(op.priority == constants.OP_PRIO_DEFAULT
                            for op in job.ops))
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)

    # Increase first
    job.ops[0].priority -= 1
    _Check(job)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT - 1)

    # Mark opcode as finished
    job.ops[0].status = constants.OP_STATUS_SUCCESS
    _Check(job)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)

    # Increase second
    job.ops[1].priority -= 10
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT - 10)

    # Test increasing first
    job.ops[0].status = constants.OP_STATUS_RUNNING
    job.ops[0].priority -= 19
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT - 20)

  def testCalcStatus(self):
    def _Queued(ops):
      # The default status is "queued"
      self.assert_(compat.all(op.status == constants.OP_STATUS_QUEUED
                              for op in ops))

    def _Waitlock1(ops):
      ops[0].status = constants.OP_STATUS_WAITING

    def _Waitlock2(ops):
      ops[0].status = constants.OP_STATUS_SUCCESS
      ops[1].status = constants.OP_STATUS_SUCCESS
      ops[2].status = constants.OP_STATUS_WAITING

    def _Running(ops):
      ops[0].status = constants.OP_STATUS_SUCCESS
      ops[1].status = constants.OP_STATUS_RUNNING
      for op in ops[2:]:
        op.status = constants.OP_STATUS_QUEUED

    def _Canceling1(ops):
      ops[0].status = constants.OP_STATUS_SUCCESS
      ops[1].status = constants.OP_STATUS_SUCCESS
      for op in ops[2:]:
        op.status = constants.OP_STATUS_CANCELING

    def _Canceling2(ops):
      for op in ops:
        op.status = constants.OP_STATUS_CANCELING

    def _Canceled(ops):
      for op in ops:
        op.status = constants.OP_STATUS_CANCELED

    def _Error1(ops):
      for idx, op in enumerate(ops):
        if idx > 3:
          op.status = constants.OP_STATUS_ERROR
        else:
          op.status = constants.OP_STATUS_SUCCESS

    def _Error2(ops):
      for op in ops:
        op.status = constants.OP_STATUS_ERROR

    def _Success(ops):
      for op in ops:
        op.status = constants.OP_STATUS_SUCCESS

    tests = {
      constants.JOB_STATUS_QUEUED: [_Queued],
      constants.JOB_STATUS_WAITING: [_Waitlock1, _Waitlock2],
      constants.JOB_STATUS_RUNNING: [_Running],
      constants.JOB_STATUS_CANCELING: [_Canceling1, _Canceling2],
      constants.JOB_STATUS_CANCELED: [_Canceled],
      constants.JOB_STATUS_ERROR: [_Error1, _Error2],
      constants.JOB_STATUS_SUCCESS: [_Success],
      }

    def _NewJob():
      job = jqueue._QueuedJob(None, 1,
                              [opcodes.OpTestDelay() for _ in range(10)],
                              True)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assert_(compat.all(op.status == constants.OP_STATUS_QUEUED
                              for op in job.ops))
      return job

    for status in constants.JOB_STATUS_ALL:
      sttests = tests[status]
      assert sttests
      for fn in sttests:
        job = _NewJob()
        fn(job.ops)
        self.assertEqual(job.CalcStatus(), status)


class _FakeDependencyManager:
  def __init__(self):
    self._checks = []
    self._notifications = []
    self._waiting = set()

  def AddCheckResult(self, job, dep_job_id, dep_status, result):
    self._checks.append((job, dep_job_id, dep_status, result))

  def CountPendingResults(self):
    return len(self._checks)

  def CountWaitingJobs(self):
    return len(self._waiting)

  def GetNextNotification(self):
    return self._notifications.pop(0)

  def JobWaiting(self, job):
    return job in self._waiting

  def CheckAndRegister(self, job, dep_job_id, dep_status):
    (exp_job, exp_dep_job_id, exp_dep_status, result) = self._checks.pop(0)

    assert exp_job == job
    assert exp_dep_job_id == dep_job_id
    assert exp_dep_status == dep_status

    (result_status, _) = result

    if result_status == jqueue._JobDependencyManager.WAIT:
      self._waiting.add(job)
    elif result_status == jqueue._JobDependencyManager.CONTINUE:
      self._waiting.remove(job)

    return result

  def NotifyWaiters(self, job_id):
    self._notifications.append(job_id)


class _DisabledFakeDependencyManager:
  def JobWaiting(self, _):
    return False

  def CheckAndRegister(self, *args):
    assert False, "Should not be called"

  def NotifyWaiters(self, _):
    pass


class _FakeQueueForProc:
  def __init__(self, depmgr=None):
    self._acquired = False
    self._updates = []
    self._submitted = []

    self._submit_count = itertools.count(1000)

    if depmgr:
      self.depmgr = depmgr
    else:
      self.depmgr = _DisabledFakeDependencyManager()

  def IsAcquired(self):
    return self._acquired

  def GetNextUpdate(self):
    return self._updates.pop(0)

  def GetNextSubmittedJob(self):
    return self._submitted.pop(0)

  def acquire(self, shared=0):
    assert shared == 1
    self._acquired = True

  def release(self):
    assert self._acquired
    self._acquired = False

  def UpdateJobUnlocked(self, job, replicate=True):
    assert self._acquired, "Lock not acquired while updating job"
    self._updates.append((job, bool(replicate)))

  def SubmitManyJobs(self, jobs):
    assert not self._acquired, "Lock acquired while submitting jobs"
    job_ids = [self._submit_count.next() for _ in jobs]
    self._submitted.extend(zip(job_ids, jobs))
    return job_ids


class _FakeExecOpCodeForProc:
  def __init__(self, queue, before_start, after_start):
    self._queue = queue
    self._before_start = before_start
    self._after_start = after_start

  def __call__(self, op, cbs, timeout=None, priority=None):
    assert isinstance(op, opcodes.OpTestDummy)
    assert not self._queue.IsAcquired(), \
           "Queue lock not released when executing opcode"

    if self._before_start:
      self._before_start(timeout, priority)

    cbs.NotifyStart()

    if self._after_start:
      self._after_start(op, cbs)

    # Check again after the callbacks
    assert not self._queue.IsAcquired()

    if op.fail:
      raise errors.OpExecError("Error requested (%s)" % op.result)

    if hasattr(op, "submit_jobs") and op.submit_jobs is not None:
      return cbs.SubmitManyJobs(op.submit_jobs)

    return op.result


class _JobProcessorTestUtils:
  def _CreateJob(self, queue, job_id, ops):
    job = jqueue._QueuedJob(queue, job_id, ops, True)
    self.assertFalse(job.start_timestamp)
    self.assertFalse(job.end_timestamp)
    self.assertEqual(len(ops), len(job.ops))
    self.assert_(compat.all(op.input == inp
                            for (op, inp) in zip(job.ops, ops)))
    self.assertEqual(job.GetInfo(["ops"]), [[op.__getstate__() for op in ops]])
    return job


class TestJobProcessor(unittest.TestCase, _JobProcessorTestUtils):
  def _GenericCheckJob(self, job):
    assert compat.all(isinstance(op.input, opcodes.OpTestDummy)
                      for op in job.ops)

    self.assertEqual(job.GetInfo(["opstart", "opexec", "opend"]),
                     [[op.start_timestamp for op in job.ops],
                      [op.exec_timestamp for op in job.ops],
                      [op.end_timestamp for op in job.ops]])
    self.assertEqual(job.GetInfo(["received_ts", "start_ts", "end_ts"]),
                     [job.received_timestamp,
                      job.start_timestamp,
                      job.end_timestamp])
    self.assert_(job.start_timestamp)
    self.assert_(job.end_timestamp)
    self.assertEqual(job.start_timestamp, job.ops[0].start_timestamp)

  def testSuccess(self):
    queue = _FakeQueueForProc()

    for (job_id, opcount) in [(25351, 1), (6637, 3),
                              (24644, 10), (32207, 100)]:
      ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
             for i in range(opcount)]

      # Create job
      job = self._CreateJob(queue, job_id, ops)

      def _BeforeStart(timeout, priority):
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        self.assertRaises(IndexError, queue.GetNextUpdate)
        self.assertFalse(queue.IsAcquired())
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
        self.assertFalse(job.cur_opctx)

      def _AfterStart(op, cbs):
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        self.assertRaises(IndexError, queue.GetNextUpdate)

        self.assertFalse(queue.IsAcquired())
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
        self.assertFalse(job.cur_opctx)

        # Job is running, cancelling shouldn't be possible
        (success, _) = job.Cancel()
        self.assertFalse(success)

      opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

      for idx in range(len(ops)):
        self.assertRaises(IndexError, queue.GetNextUpdate)
        result = jqueue._JobProcessor(queue, opexec, job)()
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        self.assertRaises(IndexError, queue.GetNextUpdate)
        if idx == len(ops) - 1:
          # Last opcode
          self.assertEqual(result, jqueue._JobProcessor.FINISHED)
        else:
          self.assertEqual(result, jqueue._JobProcessor.DEFER)

          self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
          self.assert_(job.start_timestamp)
          self.assertFalse(job.end_timestamp)

      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
      self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_SUCCESS])
      self.assertEqual(job.GetInfo(["opresult"]),
                       [[op.input.result for op in job.ops]])
      self.assertEqual(job.GetInfo(["opstatus"]),
                       [len(job.ops) * [constants.OP_STATUS_SUCCESS]])
      self.assert_(compat.all(op.start_timestamp and op.end_timestamp
                              for op in job.ops))

      self._GenericCheckJob(job)

      # Calling the processor on a finished job should be a no-op
      self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                       jqueue._JobProcessor.FINISHED)
      self.assertRaises(IndexError, queue.GetNextUpdate)

  def testOpcodeError(self):
    queue = _FakeQueueForProc()

    testdata = [
      (17077, 1, 0, 0),
      (1782, 5, 2, 2),
      (18179, 10, 9, 9),
      (4744, 10, 3, 8),
      (23816, 100, 39, 45),
      ]

    for (job_id, opcount, failfrom, failto) in testdata:
      # Prepare opcodes
      ops = [opcodes.OpTestDummy(result="Res%s" % i,
                                 fail=(failfrom <= i and
                                       i <= failto))
             for i in range(opcount)]

      # Create job
      job = self._CreateJob(queue, job_id, ops)

      opexec = _FakeExecOpCodeForProc(queue, None, None)

      for idx in range(len(ops)):
        self.assertRaises(IndexError, queue.GetNextUpdate)
        result = jqueue._JobProcessor(queue, opexec, job)()
        # queued to waitlock
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        # waitlock to running
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        # Opcode result
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        self.assertRaises(IndexError, queue.GetNextUpdate)

        if idx in (failfrom, len(ops) - 1):
          # Last opcode
          self.assertEqual(result, jqueue._JobProcessor.FINISHED)
          break

        self.assertEqual(result, jqueue._JobProcessor.DEFER)

        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

      self.assertRaises(IndexError, queue.GetNextUpdate)

      # Check job status
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_ERROR)
      self.assertEqual(job.GetInfo(["id"]), [job_id])
      self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_ERROR])

      # Check opcode status
      data = zip(job.ops,
                 job.GetInfo(["opstatus"])[0],
                 job.GetInfo(["opresult"])[0])

      for idx, (op, opstatus, opresult) in enumerate(data):
        if idx < failfrom:
          assert not op.input.fail
          self.assertEqual(opstatus, constants.OP_STATUS_SUCCESS)
          self.assertEqual(opresult, op.input.result)
        elif idx <= failto:
          assert op.input.fail
          self.assertEqual(opstatus, constants.OP_STATUS_ERROR)
          self.assertRaises(errors.OpExecError, errors.MaybeRaise, opresult)
        else:
          assert not op.input.fail
          self.assertEqual(opstatus, constants.OP_STATUS_ERROR)
          self.assertRaises(errors.OpExecError, errors.MaybeRaise, opresult)

      self.assert_(compat.all(op.start_timestamp and op.end_timestamp
                              for op in job.ops[:failfrom]))

      self._GenericCheckJob(job)

      # Calling the processor on a finished job should be a no-op
      self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                       jqueue._JobProcessor.FINISHED)
      self.assertRaises(IndexError, queue.GetNextUpdate)

  def testCancelWhileInQueue(self):
    queue = _FakeQueueForProc()

    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(5)]

    # Create job
    job_id = 17045
    job = self._CreateJob(queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    # Mark as cancelled
    (success, _) = job.Cancel()
    self.assert_(success)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    self.assertFalse(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assert_(compat.all(op.status == constants.OP_STATUS_CANCELED
                            for op in job.ops))

    # Serialize to check for differences
    before_proc = job.Serialize()

    # Simulate processor called in workerpool
    opexec = _FakeExecOpCodeForProc(queue, None, None)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_CANCELED])
    self.assertFalse(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assertFalse(compat.any(op.start_timestamp or op.end_timestamp
                                for op in job.ops))
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_CANCELED for _ in job.ops],
                      ["Job canceled by request" for _ in job.ops]])

    # Must not have changed or written
    self.assertEqual(before_proc, job.Serialize())
    self.assertRaises(IndexError, queue.GetNextUpdate)

  def testCancelWhileWaitlockInQueue(self):
    queue = _FakeQueueForProc()

    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(5)]

    # Create job
    job_id = 8645
    job = self._CreateJob(queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    job.ops[0].status = constants.OP_STATUS_WAITING

    assert len(job.ops) == 5

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

    # Mark as cancelling
    (success, _) = job.Cancel()
    self.assert_(success)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    self.assert_(compat.all(op.status == constants.OP_STATUS_CANCELING
                            for op in job.ops))

    opexec = _FakeExecOpCodeForProc(queue, None, None)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_CANCELED])
    self.assertFalse(job.start_timestamp)
    self.assert_(job.end_timestamp)
    self.assertFalse(compat.any(op.start_timestamp or op.end_timestamp
                                for op in job.ops))
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_CANCELED for _ in job.ops],
                      ["Job canceled by request" for _ in job.ops]])

  def testCancelWhileWaitlock(self):
    queue = _FakeQueueForProc()

    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(5)]

    # Create job
    job_id = 11009
    job = self._CreateJob(queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    def _BeforeStart(timeout, priority):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

      # Mark as cancelled
      (success, _) = job.Cancel()
      self.assert_(success)

      self.assert_(compat.all(op.status == constants.OP_STATUS_CANCELING
                              for op in job.ops))
      self.assertRaises(IndexError, queue.GetNextUpdate)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertRaises(IndexError, queue.GetNextUpdate)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertEqual(queue.GetNextUpdate(), (job, True))
    self.assertRaises(IndexError, queue.GetNextUpdate)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_CANCELED])
    self.assert_(job.start_timestamp)
    self.assert_(job.end_timestamp)
    self.assertFalse(compat.all(op.start_timestamp and op.end_timestamp
                                for op in job.ops))
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_CANCELED for _ in job.ops],
                      ["Job canceled by request" for _ in job.ops]])

  def testCancelWhileWaitlockWithTimeout(self):
    queue = _FakeQueueForProc()

    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(5)]

    # Create job
    job_id = 24314
    job = self._CreateJob(queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    def _BeforeStart(timeout, priority):
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

      # Mark as cancelled
      (success, _) = job.Cancel()
      self.assert_(success)

      self.assert_(compat.all(op.status == constants.OP_STATUS_CANCELING
                              for op in job.ops))

      # Fake an acquire attempt timing out
      raise mcpu.LockAcquireTimeout()

    def _AfterStart(op, cbs):
      self.fail("Should not reach this")

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_CANCELED])
    self.assert_(job.start_timestamp)
    self.assert_(job.end_timestamp)
    self.assertFalse(compat.all(op.start_timestamp and op.end_timestamp
                                for op in job.ops))
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_CANCELED for _ in job.ops],
                      ["Job canceled by request" for _ in job.ops]])

  def testCancelWhileRunning(self):
    # Tests canceling a job with finished opcodes and more, unprocessed ones
    queue = _FakeQueueForProc()

    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(3)]

    # Create job
    job_id = 28492
    job = self._CreateJob(queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    opexec = _FakeExecOpCodeForProc(queue, None, None)

    # Run one opcode
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.DEFER)

    # Job goes back to queued
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_SUCCESS,
                       constants.OP_STATUS_QUEUED,
                       constants.OP_STATUS_QUEUED],
                      ["Res0", None, None]])

    # Mark as cancelled
    (success, _) = job.Cancel()
    self.assert_(success)

    # Try processing another opcode (this will actually cancel the job)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertEqual(job.GetInfo(["id"]), [job_id])
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_CANCELED])
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_SUCCESS,
                       constants.OP_STATUS_CANCELED,
                       constants.OP_STATUS_CANCELED],
                      ["Res0", "Job canceled by request",
                       "Job canceled by request"]])

  def testPartiallyRun(self):
    # Tests calling the processor on a job that's been partially run before the
    # program was restarted
    queue = _FakeQueueForProc()

    opexec = _FakeExecOpCodeForProc(queue, None, None)

    for job_id, successcount in [(30697, 1), (2552, 4), (12489, 9)]:
      ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
             for i in range(10)]

      # Create job
      job = self._CreateJob(queue, job_id, ops)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

      for _ in range(successcount):
        self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                         jqueue._JobProcessor.DEFER)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertEqual(job.GetInfo(["opstatus"]),
                       [[constants.OP_STATUS_SUCCESS
                         for _ in range(successcount)] +
                        [constants.OP_STATUS_QUEUED
                         for _ in range(len(ops) - successcount)]])

      self.assert_(job.ops_iter)

      # Serialize and restore (simulates program restart)
      newjob = jqueue._QueuedJob.Restore(queue, job.Serialize(), True)
      self.assertFalse(newjob.ops_iter)
      self._TestPartial(newjob, successcount)

  def _TestPartial(self, job, successcount):
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
    self.assertEqual(job.start_timestamp, job.ops[0].start_timestamp)

    queue = _FakeQueueForProc()
    opexec = _FakeExecOpCodeForProc(queue, None, None)

    for remaining in reversed(range(len(job.ops) - successcount)):
      result = jqueue._JobProcessor(queue, opexec, job)()
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      if remaining == 0:
        # Last opcode
        self.assertEqual(result, jqueue._JobProcessor.FINISHED)
        break

      self.assertEqual(result, jqueue._JobProcessor.DEFER)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    self.assertRaises(IndexError, queue.GetNextUpdate)
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(job.GetInfo(["opresult"]),
                     [[op.input.result for op in job.ops]])
    self.assertEqual(job.GetInfo(["opstatus"]),
                     [[constants.OP_STATUS_SUCCESS for _ in job.ops]])
    self.assert_(compat.all(op.start_timestamp and op.end_timestamp
                            for op in job.ops))

    self._GenericCheckJob(job)

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)

    # ... also after being restored
    job2 = jqueue._QueuedJob.Restore(queue, job.Serialize(), True)
    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job2)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)

  def testProcessorOnRunningJob(self):
    ops = [opcodes.OpTestDummy(result="result", fail=False)]

    queue = _FakeQueueForProc()
    opexec = _FakeExecOpCodeForProc(queue, None, None)

    # Create job
    job = self._CreateJob(queue, 9571, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    job.ops[0].status = constants.OP_STATUS_RUNNING

    assert len(job.ops) == 1

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)

    # Calling on running job must fail
    self.assertRaises(errors.ProgrammerError,
                      jqueue._JobProcessor(queue, opexec, job))

  def testLogMessages(self):
    # Tests the "Feedback" callback function
    queue = _FakeQueueForProc()

    messages = {
      1: [
        (None, "Hello"),
        (None, "World"),
        (constants.ELOG_MESSAGE, "there"),
        ],
      4: [
        (constants.ELOG_JQUEUE_TEST, (1, 2, 3)),
        (constants.ELOG_JQUEUE_TEST, ("other", "type")),
        ],
      }
    ops = [opcodes.OpTestDummy(result="Logtest%s" % i, fail=False,
                               messages=messages.get(i, []))
           for i in range(5)]

    # Create job
    job = self._CreateJob(queue, 29386, ops)

    def _BeforeStart(timeout, priority):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)

      self.assertRaises(AssertionError, cbs.Feedback,
                        "too", "many", "arguments")

      for (log_type, msg) in op.messages:
        self.assertRaises(IndexError, queue.GetNextUpdate)
        if log_type:
          cbs.Feedback(log_type, msg)
        else:
          cbs.Feedback(msg)
        # Check for job update without replication
        self.assertEqual(queue.GetNextUpdate(), (job, False))
        self.assertRaises(IndexError, queue.GetNextUpdate)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    for remaining in reversed(range(len(job.ops))):
      self.assertRaises(IndexError, queue.GetNextUpdate)
      result = jqueue._JobProcessor(queue, opexec, job)()
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      if remaining == 0:
        # Last opcode
        self.assertEqual(result, jqueue._JobProcessor.FINISHED)
        break

      self.assertEqual(result, jqueue._JobProcessor.DEFER)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertEqual(job.GetInfo(["opresult"]),
                     [[op.input.result for op in job.ops]])

    logmsgcount = sum(len(m) for m in messages.values())

    self._CheckLogMessages(job, logmsgcount)

    # Serialize and restore (simulates program restart)
    newjob = jqueue._QueuedJob.Restore(queue, job.Serialize(), True)
    self._CheckLogMessages(newjob, logmsgcount)

    # Check each message
    prevserial = -1
    for idx, oplog in enumerate(job.GetInfo(["oplog"])[0]):
      for (serial, timestamp, log_type, msg) in oplog:
        (exptype, expmsg) = messages.get(idx).pop(0)
        if exptype:
          self.assertEqual(log_type, exptype)
        else:
          self.assertEqual(log_type, constants.ELOG_MESSAGE)
        self.assertEqual(expmsg, msg)
        self.assert_(serial > prevserial)
        prevserial = serial

  def _CheckLogMessages(self, job, count):
    # Check serial
    self.assertEqual(job.log_serial, count)

    # No filter
    self.assertEqual(job.GetLogEntries(None),
                     [entry for entries in job.GetInfo(["oplog"])[0] if entries
                      for entry in entries])

    # Filter with serial
    assert count > 3
    self.assert_(job.GetLogEntries(3))
    self.assertEqual(job.GetLogEntries(3),
                     [entry for entries in job.GetInfo(["oplog"])[0] if entries
                      for entry in entries][3:])

    # No log message after highest serial
    self.assertFalse(job.GetLogEntries(count))
    self.assertFalse(job.GetLogEntries(count + 3))

  def testSubmitManyJobs(self):
    queue = _FakeQueueForProc()

    job_id = 15656
    ops = [
      opcodes.OpTestDummy(result="Res0", fail=False,
                          submit_jobs=[]),
      opcodes.OpTestDummy(result="Res1", fail=False,
                          submit_jobs=[
                            [opcodes.OpTestDummy(result="r1j0", fail=False)],
                            ]),
      opcodes.OpTestDummy(result="Res2", fail=False,
                          submit_jobs=[
                            [opcodes.OpTestDummy(result="r2j0o0", fail=False),
                             opcodes.OpTestDummy(result="r2j0o1", fail=False),
                             opcodes.OpTestDummy(result="r2j0o2", fail=False),
                             opcodes.OpTestDummy(result="r2j0o3", fail=False)],
                            [opcodes.OpTestDummy(result="r2j1", fail=False)],
                            [opcodes.OpTestDummy(result="r2j3o0", fail=False),
                             opcodes.OpTestDummy(result="r2j3o1", fail=False)],
                            ]),
      ]

    # Create job
    job = self._CreateJob(queue, job_id, ops)

    def _BeforeStart(timeout, priority):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    for idx in range(len(ops)):
      self.assertRaises(IndexError, queue.GetNextUpdate)
      result = jqueue._JobProcessor(queue, opexec, job)()
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      if idx == len(ops) - 1:
        # Last opcode
        self.assertEqual(result, jqueue._JobProcessor.FINISHED)
      else:
        self.assertEqual(result, jqueue._JobProcessor.DEFER)

        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
        self.assert_(job.start_timestamp)
        self.assertFalse(job.end_timestamp)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    for idx, submitted_ops in enumerate(job_ops
                                        for op in ops
                                        for job_ops in op.submit_jobs):
      self.assertEqual(queue.GetNextSubmittedJob(),
                       (1000 + idx, submitted_ops))
    self.assertRaises(IndexError, queue.GetNextSubmittedJob)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(job.GetInfo(["opresult"]),
                     [[[], [1000], [1001, 1002, 1003]]])
    self.assertEqual(job.GetInfo(["opstatus"]),
                     [len(job.ops) * [constants.OP_STATUS_SUCCESS]])

    self._GenericCheckJob(job)

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)

  def testJobDependency(self):
    depmgr = _FakeDependencyManager()
    queue = _FakeQueueForProc(depmgr=depmgr)

    self.assertEqual(queue.depmgr, depmgr)

    prev_job_id = 22113
    prev_job_id2 = 28102
    job_id = 29929
    ops = [
      opcodes.OpTestDummy(result="Res0", fail=False,
                          depends=[
                            [prev_job_id2, None],
                            [prev_job_id, None],
                            ]),
      opcodes.OpTestDummy(result="Res1", fail=False),
      ]

    # Create job
    job = self._CreateJob(queue, job_id, ops)

    def _BeforeStart(timeout, priority):
      if attempt == 0 or attempt > 5:
        # Job should only be updated when it wasn't waiting for another job
        self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    counter = itertools.count()
    while True:
      attempt = counter.next()

      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertRaises(IndexError, depmgr.GetNextNotification)

      if attempt < 2:
        depmgr.AddCheckResult(job, prev_job_id2, None,
                              (jqueue._JobDependencyManager.WAIT, "wait2"))
      elif attempt == 2:
        depmgr.AddCheckResult(job, prev_job_id2, None,
                              (jqueue._JobDependencyManager.CONTINUE, "cont"))
        # The processor will ask for the next dependency immediately
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.WAIT, "wait"))
      elif attempt < 5:
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.WAIT, "wait"))
      elif attempt == 5:
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.CONTINUE, "cont"))
      if attempt == 2:
        self.assertEqual(depmgr.CountPendingResults(), 2)
      elif attempt > 5:
        self.assertEqual(depmgr.CountPendingResults(), 0)
      else:
        self.assertEqual(depmgr.CountPendingResults(), 1)

      result = jqueue._JobProcessor(queue, opexec, job)()
      if attempt == 0 or attempt >= 5:
        # Job should only be updated if there was an actual change
        self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(depmgr.CountPendingResults())

      if attempt < 5:
        # Simulate waiting for other job
        self.assertEqual(result, jqueue._JobProcessor.WAITDEP)
        self.assertTrue(job.cur_opctx)
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
        self.assertRaises(IndexError, depmgr.GetNextNotification)
        self.assert_(job.start_timestamp)
        self.assertFalse(job.end_timestamp)
        continue

      if result == jqueue._JobProcessor.FINISHED:
        # Last opcode
        self.assertFalse(job.cur_opctx)
        break

      self.assertRaises(IndexError, depmgr.GetNextNotification)

      self.assertEqual(result, jqueue._JobProcessor.DEFER)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assert_(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(job.GetInfo(["opresult"]),
                     [[op.input.result for op in job.ops]])
    self.assertEqual(job.GetInfo(["opstatus"]),
                     [len(job.ops) * [constants.OP_STATUS_SUCCESS]])
    self.assertTrue(compat.all(op.start_timestamp and op.end_timestamp
                               for op in job.ops))

    self._GenericCheckJob(job)

    self.assertRaises(IndexError, queue.GetNextUpdate)
    self.assertRaises(IndexError, depmgr.GetNextNotification)
    self.assertFalse(depmgr.CountPendingResults())
    self.assertFalse(depmgr.CountWaitingJobs())

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)

  def testJobDependencyCancel(self):
    depmgr = _FakeDependencyManager()
    queue = _FakeQueueForProc(depmgr=depmgr)

    self.assertEqual(queue.depmgr, depmgr)

    prev_job_id = 13623
    job_id = 30876
    ops = [
      opcodes.OpTestDummy(result="Res0", fail=False),
      opcodes.OpTestDummy(result="Res1", fail=False,
                          depends=[
                            [prev_job_id, None],
                            ]),
      opcodes.OpTestDummy(result="Res2", fail=False),
      ]

    # Create job
    job = self._CreateJob(queue, job_id, ops)

    def _BeforeStart(timeout, priority):
      if attempt == 0 or attempt > 5:
        # Job should only be updated when it wasn't waiting for another job
        self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    counter = itertools.count()
    while True:
      attempt = counter.next()

      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertRaises(IndexError, depmgr.GetNextNotification)

      if attempt == 0:
        # This will handle the first opcode
        pass
      elif attempt < 4:
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.WAIT, "wait"))
      elif attempt == 4:
        # Other job was cancelled
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.CANCEL, "cancel"))

      if attempt == 0:
        self.assertEqual(depmgr.CountPendingResults(), 0)
      else:
        self.assertEqual(depmgr.CountPendingResults(), 1)

      result = jqueue._JobProcessor(queue, opexec, job)()
      if attempt <= 1 or attempt >= 4:
        # Job should only be updated if there was an actual change
        self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(depmgr.CountPendingResults())

      if attempt > 0 and attempt < 4:
        # Simulate waiting for other job
        self.assertEqual(result, jqueue._JobProcessor.WAITDEP)
        self.assertTrue(job.cur_opctx)
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
        self.assertRaises(IndexError, depmgr.GetNextNotification)
        self.assert_(job.start_timestamp)
        self.assertFalse(job.end_timestamp)
        continue

      if result == jqueue._JobProcessor.FINISHED:
        # Last opcode
        self.assertFalse(job.cur_opctx)
        break

      self.assertRaises(IndexError, depmgr.GetNextNotification)

      self.assertEqual(result, jqueue._JobProcessor.DEFER)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assert_(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_CANCELED])
    self.assertEqual(job.GetInfo(["opstatus", "opresult"]),
                     [[constants.OP_STATUS_SUCCESS,
                       constants.OP_STATUS_CANCELED,
                       constants.OP_STATUS_CANCELED],
                      ["Res0", "Job canceled by request",
                       "Job canceled by request"]])

    self._GenericCheckJob(job)

    self.assertRaises(IndexError, queue.GetNextUpdate)
    self.assertRaises(IndexError, depmgr.GetNextNotification)
    self.assertFalse(depmgr.CountPendingResults())

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)

  def testJobDependencyWrongstatus(self):
    depmgr = _FakeDependencyManager()
    queue = _FakeQueueForProc(depmgr=depmgr)

    self.assertEqual(queue.depmgr, depmgr)

    prev_job_id = 9741
    job_id = 11763
    ops = [
      opcodes.OpTestDummy(result="Res0", fail=False),
      opcodes.OpTestDummy(result="Res1", fail=False,
                          depends=[
                            [prev_job_id, None],
                            ]),
      opcodes.OpTestDummy(result="Res2", fail=False),
      ]

    # Create job
    job = self._CreateJob(queue, job_id, ops)

    def _BeforeStart(timeout, priority):
      if attempt == 0 or attempt > 5:
        # Job should only be updated when it wasn't waiting for another job
        self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertFalse(queue.IsAcquired())
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    counter = itertools.count()
    while True:
      attempt = counter.next()

      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertRaises(IndexError, depmgr.GetNextNotification)

      if attempt == 0:
        # This will handle the first opcode
        pass
      elif attempt < 4:
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.WAIT, "wait"))
      elif attempt == 4:
        # Other job failed
        depmgr.AddCheckResult(job, prev_job_id, None,
                              (jqueue._JobDependencyManager.WRONGSTATUS, "w"))

      if attempt == 0:
        self.assertEqual(depmgr.CountPendingResults(), 0)
      else:
        self.assertEqual(depmgr.CountPendingResults(), 1)

      result = jqueue._JobProcessor(queue, opexec, job)()
      if attempt <= 1 or attempt >= 4:
        # Job should only be updated if there was an actual change
        self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertFalse(depmgr.CountPendingResults())

      if attempt > 0 and attempt < 4:
        # Simulate waiting for other job
        self.assertEqual(result, jqueue._JobProcessor.WAITDEP)
        self.assertTrue(job.cur_opctx)
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
        self.assertRaises(IndexError, depmgr.GetNextNotification)
        self.assert_(job.start_timestamp)
        self.assertFalse(job.end_timestamp)
        continue

      if result == jqueue._JobProcessor.FINISHED:
        # Last opcode
        self.assertFalse(job.cur_opctx)
        break

      self.assertRaises(IndexError, depmgr.GetNextNotification)

      self.assertEqual(result, jqueue._JobProcessor.DEFER)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assert_(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_ERROR)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_ERROR])
    self.assertEqual(job.GetInfo(["opstatus"]),
                     [[constants.OP_STATUS_SUCCESS,
                       constants.OP_STATUS_ERROR,
                       constants.OP_STATUS_ERROR]]),

    (opresult, ) = job.GetInfo(["opresult"])
    self.assertEqual(len(opresult), len(ops))
    self.assertEqual(opresult[0], "Res0")
    self.assertTrue(errors.GetEncodedError(opresult[1]))
    self.assertTrue(errors.GetEncodedError(opresult[2]))

    self._GenericCheckJob(job)

    self.assertRaises(IndexError, queue.GetNextUpdate)
    self.assertRaises(IndexError, depmgr.GetNextNotification)
    self.assertFalse(depmgr.CountPendingResults())

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)


class _FakeTimeoutStrategy:
  def __init__(self, timeouts):
    self.timeouts = timeouts
    self.attempts = 0
    self.last_timeout = None

  def NextAttempt(self):
    self.attempts += 1
    if self.timeouts:
      timeout = self.timeouts.pop(0)
    else:
      timeout = None
    self.last_timeout = timeout
    return timeout


class TestJobProcessorTimeouts(unittest.TestCase, _JobProcessorTestUtils):
  def setUp(self):
    self.queue = _FakeQueueForProc()
    self.job = None
    self.curop = None
    self.opcounter = None
    self.timeout_strategy = None
    self.retries = 0
    self.prev_tsop = None
    self.prev_prio = None
    self.prev_status = None
    self.lock_acq_prio = None
    self.gave_lock = None
    self.done_lock_before_blocking = False

  def _BeforeStart(self, timeout, priority):
    job = self.job

    # If status has changed, job must've been written
    if self.prev_status != self.job.ops[self.curop].status:
      self.assertEqual(self.queue.GetNextUpdate(), (job, True))
    self.assertRaises(IndexError, self.queue.GetNextUpdate)

    self.assertFalse(self.queue.IsAcquired())
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

    ts = self.timeout_strategy

    self.assert_(timeout is None or isinstance(timeout, (int, float)))
    self.assertEqual(timeout, ts.last_timeout)
    self.assertEqual(priority, job.ops[self.curop].priority)

    self.gave_lock = True
    self.lock_acq_prio = priority

    if (self.curop == 3 and
        job.ops[self.curop].priority == constants.OP_PRIO_HIGHEST + 3):
      # Give locks before running into blocking acquire
      assert self.retries == 7
      self.retries = 0
      self.done_lock_before_blocking = True
      return

    if self.retries > 0:
      self.assert_(timeout is not None)
      self.retries -= 1
      self.gave_lock = False
      raise mcpu.LockAcquireTimeout()

    if job.ops[self.curop].priority == constants.OP_PRIO_HIGHEST:
      assert self.retries == 0, "Didn't exhaust all retries at highest priority"
      assert not ts.timeouts
      self.assert_(timeout is None)

  def _AfterStart(self, op, cbs):
    job = self.job

    # Setting to "running" requires an update
    self.assertEqual(self.queue.GetNextUpdate(), (job, True))
    self.assertRaises(IndexError, self.queue.GetNextUpdate)

    self.assertFalse(self.queue.IsAcquired())
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)

    # Job is running, cancelling shouldn't be possible
    (success, _) = job.Cancel()
    self.assertFalse(success)

  def _NextOpcode(self):
    self.curop = self.opcounter.next()
    self.prev_prio = self.job.ops[self.curop].priority
    self.prev_status = self.job.ops[self.curop].status

  def _NewTimeoutStrategy(self):
    job = self.job

    self.assertEqual(self.retries, 0)

    if self.prev_tsop == self.curop:
      # Still on the same opcode, priority must've been increased
      self.assertEqual(self.prev_prio, job.ops[self.curop].priority + 1)

    if self.curop == 1:
      # Normal retry
      timeouts = range(10, 31, 10)
      self.retries = len(timeouts) - 1

    elif self.curop == 2:
      # Let this run into a blocking acquire
      timeouts = range(11, 61, 12)
      self.retries = len(timeouts)

    elif self.curop == 3:
      # Wait for priority to increase, but give lock before blocking acquire
      timeouts = range(12, 100, 14)
      self.retries = len(timeouts)

      self.assertFalse(self.done_lock_before_blocking)

    elif self.curop == 4:
      self.assert_(self.done_lock_before_blocking)

      # Timeouts, but no need to retry
      timeouts = range(10, 31, 10)
      self.retries = 0

    elif self.curop == 5:
      # Normal retry
      timeouts = range(19, 100, 11)
      self.retries = len(timeouts)

    else:
      timeouts = []
      self.retries = 0

    assert len(job.ops) == 10
    assert self.retries <= len(timeouts)

    ts = _FakeTimeoutStrategy(timeouts)

    self.timeout_strategy = ts
    self.prev_tsop = self.curop
    self.prev_prio = job.ops[self.curop].priority

    return ts

  def testTimeout(self):
    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(10)]

    # Create job
    job_id = 15801
    job = self._CreateJob(self.queue, job_id, ops)
    self.job = job

    self.opcounter = itertools.count(0)

    opexec = _FakeExecOpCodeForProc(self.queue, self._BeforeStart,
                                    self._AfterStart)
    tsf = self._NewTimeoutStrategy

    self.assertFalse(self.done_lock_before_blocking)

    while True:
      proc = jqueue._JobProcessor(self.queue, opexec, job,
                                  _timeout_strategy_factory=tsf)

      self.assertRaises(IndexError, self.queue.GetNextUpdate)

      if self.curop is not None:
        self.prev_status = self.job.ops[self.curop].status

      self.lock_acq_prio = None

      result = proc(_nextop_fn=self._NextOpcode)
      assert self.curop is not None

      if result == jqueue._JobProcessor.FINISHED or self.gave_lock:
        # Got lock and/or job is done, result must've been written
        self.assertFalse(job.cur_opctx)
        self.assertEqual(self.queue.GetNextUpdate(), (job, True))
        self.assertRaises(IndexError, self.queue.GetNextUpdate)
        self.assertEqual(self.lock_acq_prio, job.ops[self.curop].priority)
        self.assert_(job.ops[self.curop].exec_timestamp)

      if result == jqueue._JobProcessor.FINISHED:
        self.assertFalse(job.cur_opctx)
        break

      self.assertEqual(result, jqueue._JobProcessor.DEFER)

      if self.curop == 0:
        self.assertEqual(job.ops[self.curop].start_timestamp,
                         job.start_timestamp)

      if self.gave_lock:
        # Opcode finished, but job not yet done
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      else:
        # Did not get locks
        self.assert_(job.cur_opctx)
        self.assertEqual(job.cur_opctx._timeout_strategy._fn,
                         self.timeout_strategy.NextAttempt)
        self.assertFalse(job.ops[self.curop].exec_timestamp)
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

        # If priority has changed since acquiring locks, the job must've been
        # updated
        if self.lock_acq_prio != job.ops[self.curop].priority:
          self.assertEqual(self.queue.GetNextUpdate(), (job, True))

      self.assertRaises(IndexError, self.queue.GetNextUpdate)

      self.assert_(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(self.curop, len(job.ops) - 1)
    self.assertEqual(self.job, job)
    self.assertEqual(self.opcounter.next(), len(job.ops))
    self.assert_(self.done_lock_before_blocking)

    self.assertRaises(IndexError, self.queue.GetNextUpdate)
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertEqual(job.GetInfo(["status"]), [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(job.GetInfo(["opresult"]),
                     [[op.input.result for op in job.ops]])
    self.assertEqual(job.GetInfo(["opstatus"]),
                     [len(job.ops) * [constants.OP_STATUS_SUCCESS]])
    self.assert_(compat.all(op.start_timestamp and op.end_timestamp
                            for op in job.ops))

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(self.queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, self.queue.GetNextUpdate)


class TestJobDependencyManager(unittest.TestCase):
  class _FakeJob:
    def __init__(self, job_id):
      self.id = str(job_id)

  def setUp(self):
    self._status = []
    self._queue = []
    self.jdm = jqueue._JobDependencyManager(self._GetStatus, self._Enqueue)

  def _GetStatus(self, job_id):
    (exp_job_id, result) = self._status.pop(0)
    self.assertEqual(exp_job_id, job_id)
    return result

  def _Enqueue(self, jobs):
    self.assertFalse(self.jdm._lock.is_owned(),
                     msg=("Must not own manager lock while re-adding jobs"
                          " (potential deadlock)"))
    self._queue.append(jobs)

  def testNotFinalizedThenCancel(self):
    job = self._FakeJob(17697)
    job_id = str(28625)

    self._status.append((job_id, constants.JOB_STATUS_RUNNING))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, [])
    self.assertEqual(result, self.jdm.WAIT)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertTrue(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set([job]),
      })
    self.assertEqual(self.jdm.GetLockInfo([query.LQ_PENDING]), [
      ("job/28625", None, None, [("job", [job.id])])
      ])

    self._status.append((job_id, constants.JOB_STATUS_CANCELED))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, [])
    self.assertEqual(result, self.jdm.CANCEL)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))
    self.assertFalse(self.jdm.GetLockInfo([query.LQ_PENDING]))

  def testRequireCancel(self):
    job = self._FakeJob(5278)
    job_id = str(9610)
    dep_status = [constants.JOB_STATUS_CANCELED]

    self._status.append((job_id, constants.JOB_STATUS_WAITING))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
    self.assertEqual(result, self.jdm.WAIT)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertTrue(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set([job]),
      })
    self.assertEqual(self.jdm.GetLockInfo([query.LQ_PENDING]), [
      ("job/9610", None, None, [("job", [job.id])])
      ])

    self._status.append((job_id, constants.JOB_STATUS_CANCELED))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
    self.assertEqual(result, self.jdm.CONTINUE)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))
    self.assertFalse(self.jdm.GetLockInfo([query.LQ_PENDING]))

  def testRequireError(self):
    job = self._FakeJob(21459)
    job_id = str(25519)
    dep_status = [constants.JOB_STATUS_ERROR]

    self._status.append((job_id, constants.JOB_STATUS_WAITING))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
    self.assertEqual(result, self.jdm.WAIT)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertTrue(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set([job]),
      })

    self._status.append((job_id, constants.JOB_STATUS_ERROR))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
    self.assertEqual(result, self.jdm.CONTINUE)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))
    self.assertFalse(self.jdm.GetLockInfo([query.LQ_PENDING]))

  def testRequireMultiple(self):
    dep_status = list(constants.JOBS_FINALIZED)

    for end_status in dep_status:
      job = self._FakeJob(21343)
      job_id = str(14609)

      self._status.append((job_id, constants.JOB_STATUS_WAITING))
      (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
      self.assertEqual(result, self.jdm.WAIT)
      self.assertFalse(self._status)
      self.assertFalse(self._queue)
      self.assertTrue(self.jdm.JobWaiting(job))
      self.assertEqual(self.jdm._waiters, {
        job_id: set([job]),
        })
      self.assertEqual(self.jdm.GetLockInfo([query.LQ_PENDING]), [
        ("job/14609", None, None, [("job", [job.id])])
        ])

      self._status.append((job_id, end_status))
      (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
      self.assertEqual(result, self.jdm.CONTINUE)
      self.assertFalse(self._status)
      self.assertFalse(self._queue)
      self.assertFalse(self.jdm.JobWaiting(job))
      self.assertFalse(self.jdm.GetLockInfo([query.LQ_PENDING]))

  def testNotify(self):
    job = self._FakeJob(8227)
    job_id = str(4113)

    self._status.append((job_id, constants.JOB_STATUS_RUNNING))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, [])
    self.assertEqual(result, self.jdm.WAIT)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertTrue(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set([job]),
      })

    self.jdm.NotifyWaiters(job_id)
    self.assertFalse(self._status)
    self.assertFalse(self.jdm._waiters)
    self.assertFalse(self.jdm.JobWaiting(job))
    self.assertEqual(self._queue, [set([job])])

  def testWrongStatus(self):
    job = self._FakeJob(10102)
    job_id = str(1271)

    self._status.append((job_id, constants.JOB_STATUS_QUEUED))
    (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                            [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(result, self.jdm.WAIT)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertTrue(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set([job]),
      })

    self._status.append((job_id, constants.JOB_STATUS_ERROR))
    (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                            [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(result, self.jdm.WRONGSTATUS)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))

  def testCorrectStatus(self):
    job = self._FakeJob(24273)
    job_id = str(23885)

    self._status.append((job_id, constants.JOB_STATUS_QUEUED))
    (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                            [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(result, self.jdm.WAIT)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertTrue(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set([job]),
      })

    self._status.append((job_id, constants.JOB_STATUS_SUCCESS))
    (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                            [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(result, self.jdm.CONTINUE)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))

  def testFinalizedRightAway(self):
    job = self._FakeJob(224)
    job_id = str(3081)

    self._status.append((job_id, constants.JOB_STATUS_SUCCESS))
    (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                            [constants.JOB_STATUS_SUCCESS])
    self.assertEqual(result, self.jdm.CONTINUE)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))
    self.assertEqual(self.jdm._waiters, {
      job_id: set(),
      })

    # Force cleanup
    self.jdm.NotifyWaiters("0")
    self.assertFalse(self.jdm._waiters)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)

  def testMultipleWaiting(self):
    # Use a deterministic random generator
    rnd = random.Random(21402)

    job_ids = map(str, rnd.sample(range(1, 10000), 150))

    waiters = dict((job_ids.pop(),
                    set(map(self._FakeJob,
                            [job_ids.pop()
                             for _ in range(rnd.randint(1, 20))])))
                   for _ in range(10))

    # Ensure there are no duplicate job IDs
    assert not utils.FindDuplicates(waiters.keys() +
                                    [job.id
                                     for jobs in waiters.values()
                                     for job in jobs])

    # Register all jobs as waiters
    for job_id, job in [(job_id, job)
                        for (job_id, jobs) in waiters.items()
                        for job in jobs]:
      self._status.append((job_id, constants.JOB_STATUS_QUEUED))
      (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                              [constants.JOB_STATUS_SUCCESS])
      self.assertEqual(result, self.jdm.WAIT)
      self.assertFalse(self._status)
      self.assertFalse(self._queue)
      self.assertTrue(self.jdm.JobWaiting(job))

    self.assertEqual(self.jdm._waiters, waiters)

    def _MakeSet((name, mode, owner_names, pending)):
      return (name, mode, owner_names,
              [(pendmode, set(pend)) for (pendmode, pend) in pending])

    def _CheckLockInfo():
      info = self.jdm.GetLockInfo([query.LQ_PENDING])
      self.assertEqual(sorted(map(_MakeSet, info)), sorted([
        ("job/%s" % job_id, None, None,
         [("job", set([job.id for job in jobs]))])
        for job_id, jobs in waiters.items()
        if jobs
        ]))

    _CheckLockInfo()

    # Notify in random order
    for job_id in rnd.sample(waiters, len(waiters)):
      # Remove from pending waiter list
      jobs = waiters.pop(job_id)
      for job in jobs:
        self._status.append((job_id, constants.JOB_STATUS_SUCCESS))
        (result, _) = self.jdm.CheckAndRegister(job, job_id,
                                                [constants.JOB_STATUS_SUCCESS])
        self.assertEqual(result, self.jdm.CONTINUE)
        self.assertFalse(self._status)
        self.assertFalse(self._queue)
        self.assertFalse(self.jdm.JobWaiting(job))

      _CheckLockInfo()

    self.assertFalse(self.jdm.GetLockInfo([query.LQ_PENDING]))

    assert not waiters

  def testSelfDependency(self):
    job = self._FakeJob(18937)

    self._status.append((job.id, constants.JOB_STATUS_SUCCESS))
    (result, _) = self.jdm.CheckAndRegister(job, job.id, [])
    self.assertEqual(result, self.jdm.ERROR)

  def testJobDisappears(self):
    job = self._FakeJob(30540)
    job_id = str(23769)

    def _FakeStatus(_):
      raise errors.JobLost("#msg#")

    jdm = jqueue._JobDependencyManager(_FakeStatus, None)
    (result, _) = jdm.CheckAndRegister(job, job_id, [])
    self.assertEqual(result, self.jdm.ERROR)
    self.assertFalse(jdm.JobWaiting(job))
    self.assertFalse(jdm.GetLockInfo([query.LQ_PENDING]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
