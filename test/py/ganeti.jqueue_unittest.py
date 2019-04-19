#!/usr/bin/python3
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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


"""Script for testing ganeti.jqueue"""

import os
import sys
import unittest
import tempfile
import shutil
import errno
import itertools
import random

try:
  # pylint: disable=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import jqueue
from ganeti import opcodes
from ganeti import compat
from ganeti import mcpu
from ganeti import query
from ganeti import workerpool

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

  def GetLogEntries(self, newer_than):
    assert newer_than is None or newer_than >= 0

    if newer_than is None:
      return self._log

    return self._log[newer_than:]


class TestEncodeOpError(unittest.TestCase):
  def test(self):
    encerr = jqueue._EncodeOpError(errors.LockError("Test 1"))
    self.assertTrue(isinstance(encerr, tuple))
    self.assertRaises(errors.LockError, errors.MaybeRaise, encerr)

    encerr = jqueue._EncodeOpError(errors.GenericError("Test 2"))
    self.assertTrue(isinstance(encerr, tuple))
    self.assertRaises(errors.GenericError, errors.MaybeRaise, encerr)

    encerr = jqueue._EncodeOpError(NotImplementedError("Foo"))
    self.assertTrue(isinstance(encerr, tuple))
    self.assertRaises(errors.OpExecError, errors.MaybeRaise, encerr)

    encerr = jqueue._EncodeOpError("Hello World")
    self.assertTrue(isinstance(encerr, tuple))
    self.assertRaises(errors.OpExecError, errors.MaybeRaise, encerr)


class TestQueuedOpCode(unittest.TestCase):
  def testDefaults(self):
    def _Check(op):
      self.assertFalse(op.input.dry_run)
      self.assertEqual(op.priority, constants.OP_PRIO_DEFAULT)
      self.assertFalse(op.log)
      self.assertTrue(op.start_timestamp is None)
      self.assertTrue(op.exec_timestamp is None)
      self.assertTrue(op.end_timestamp is None)
      self.assertTrue(op.result is None)
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
  def testNoOpCodes(self):
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
      self.assertTrue(job.received_timestamp)
      self.assertTrue(job.start_timestamp is None)
      self.assertTrue(job.end_timestamp is None)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
      self.assertTrue(repr(job).startswith("<"))
      self.assertEqual(len(job.ops), len(ops))
      self.assertTrue(compat.all(inp.__getstate__() == op.input.__getstate__()
                              for (inp, op) in zip(ops, job.ops)))
      self.assertFalse(job.archived)

    job1 = jqueue._QueuedJob(None, job_id, ops, True)
    _Check(job1)
    job2 = jqueue._QueuedJob.Restore(None, job1.Serialize(), True, False)
    _Check(job2)
    self.assertEqual(job1.Serialize(), job2.Serialize())

  def testWritable(self):
    job = jqueue._QueuedJob(None, 1, [opcodes.OpTestDelay()], False)
    self.assertFalse(job.writable)

    job = jqueue._QueuedJob(None, 1, [opcodes.OpTestDelay()], True)
    self.assertTrue(job.writable)

  def testArchived(self):
    job = jqueue._QueuedJob(None, 1, [opcodes.OpTestDelay()], False)
    self.assertFalse(job.archived)

    newjob = jqueue._QueuedJob.Restore(None, job.Serialize(), True, True)
    self.assertTrue(newjob.archived)

    newjob2 = jqueue._QueuedJob.Restore(None, newjob.Serialize(), True, False)
    self.assertFalse(newjob2.archived)

  def testPriority(self):
    job_id = 4283
    ops = [
      opcodes.OpTagsGet(priority=constants.OP_PRIO_DEFAULT),
      opcodes.OpTestDelay(),
      ]

    def _Check(job):
      self.assertEqual(job.id, job_id)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertTrue(repr(job).startswith("<"))

    job = jqueue._QueuedJob(None, job_id, ops, True)
    _Check(job)
    self.assertTrue(compat.all(op.priority == constants.OP_PRIO_DEFAULT
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

  def _JobForPriority(self, job_id):
    ops = [
      opcodes.OpTagsGet(),
      opcodes.OpTestDelay(),
      opcodes.OpTagsGet(),
      opcodes.OpTestDelay(),
      ]

    job = jqueue._QueuedJob(None, job_id, ops, True)

    self.assertTrue(compat.all(op.priority == constants.OP_PRIO_DEFAULT
                               for op in job.ops))
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)

    return job

  def testChangePriorityAllQueued(self):
    job = self._JobForPriority(24984)
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
    self.assertTrue(compat.all(op.status == constants.OP_STATUS_QUEUED
                               for op in job.ops))
    result = job.ChangePriority(-10)
    self.assertEqual(job.CalcPriority(), -10)
    self.assertTrue(compat.all(op.priority == -10 for op in job.ops))
    self.assertEqual(result,
                     (True, ("Priorities of pending opcodes for job 24984 have"
                             " been changed to -10")))

  def testChangePriorityAllFinished(self):
    job = self._JobForPriority(16405)

    for (idx, op) in enumerate(job.ops):
      if idx > 2:
        op.status = constants.OP_STATUS_ERROR
      else:
        op.status = constants.OP_STATUS_SUCCESS

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_ERROR)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    result = job.ChangePriority(-10)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    self.assertTrue(compat.all(op.priority == constants.OP_PRIO_DEFAULT
                               for op in job.ops))
    self.assertEqual([op.status for op in job.ops], [
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_ERROR,
      ])
    self.assertEqual(result, (False, "Job 16405 is finished"))

  def testChangePriorityCancelling(self):
    job = self._JobForPriority(31572)

    for (idx, op) in enumerate(job.ops):
      if idx > 1:
        op.status = constants.OP_STATUS_CANCELING
      else:
        op.status = constants.OP_STATUS_SUCCESS

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELING)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    result = job.ChangePriority(5)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    self.assertTrue(compat.all(op.priority == constants.OP_PRIO_DEFAULT
                               for op in job.ops))
    self.assertEqual([op.status for op in job.ops], [
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_CANCELING,
      constants.OP_STATUS_CANCELING,
      ])
    self.assertEqual(result, (False, "Job 31572 is cancelling"))

  def testChangePriorityFirstRunning(self):
    job = self._JobForPriority(1716215889)

    for (idx, op) in enumerate(job.ops):
      if idx == 0:
        op.status = constants.OP_STATUS_RUNNING
      else:
        op.status = constants.OP_STATUS_QUEUED

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    result = job.ChangePriority(7)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    self.assertEqual([op.priority for op in job.ops],
                     [constants.OP_PRIO_DEFAULT, 7, 7, 7])
    self.assertEqual([op.status for op in job.ops], [
      constants.OP_STATUS_RUNNING,
      constants.OP_STATUS_QUEUED,
      constants.OP_STATUS_QUEUED,
      constants.OP_STATUS_QUEUED,
      ])
    self.assertEqual(result,
                     (True, ("Priorities of pending opcodes for job"
                             " 1716215889 have been changed to 7")))

  def testChangePriorityLastRunning(self):
    job = self._JobForPriority(1308)

    for (idx, op) in enumerate(job.ops):
      if idx == (len(job.ops) - 1):
        op.status = constants.OP_STATUS_RUNNING
      else:
        op.status = constants.OP_STATUS_SUCCESS

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    result = job.ChangePriority(-3)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    self.assertTrue(compat.all(op.priority == constants.OP_PRIO_DEFAULT
                               for op in job.ops))
    self.assertEqual([op.status for op in job.ops], [
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_RUNNING,
      ])
    self.assertEqual(result, (False, "Job 1308 had no pending opcodes"))

  def testChangePrioritySecondOpcodeRunning(self):
    job = self._JobForPriority(27701)

    self.assertEqual(len(job.ops), 4)
    job.ops[0].status = constants.OP_STATUS_SUCCESS
    job.ops[1].status = constants.OP_STATUS_RUNNING
    job.ops[2].status = constants.OP_STATUS_QUEUED
    job.ops[3].status = constants.OP_STATUS_QUEUED

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
    result = job.ChangePriority(-19)
    self.assertEqual(job.CalcPriority(), -19)
    self.assertEqual([op.priority for op in job.ops],
                     [constants.OP_PRIO_DEFAULT, constants.OP_PRIO_DEFAULT,
                      -19, -19])
    self.assertEqual([op.status for op in job.ops], [
      constants.OP_STATUS_SUCCESS,
      constants.OP_STATUS_RUNNING,
      constants.OP_STATUS_QUEUED,
      constants.OP_STATUS_QUEUED,
      ])
    self.assertEqual(result,
                     (True, ("Priorities of pending opcodes for job"
                             " 27701 have been changed to -19")))

  def testChangePriorityWithInconsistentJob(self):
    job = self._JobForPriority(30097)

    self.assertEqual(len(job.ops), 4)

    # This job is invalid (as it has two opcodes marked as running) and make
    # the call fail because an unprocessed opcode precedes a running one (which
    # should never happen in reality)
    job.ops[0].status = constants.OP_STATUS_SUCCESS
    job.ops[1].status = constants.OP_STATUS_RUNNING
    job.ops[2].status = constants.OP_STATUS_QUEUED
    job.ops[3].status = constants.OP_STATUS_RUNNING

    self.assertRaises(AssertionError, job.ChangePriority, 19)

  def testCalcStatus(self):
    def _Queued(ops):
      # The default status is "queued"
      self.assertTrue(compat.all(op.status == constants.OP_STATUS_QUEUED
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
      self.assertTrue(compat.all(op.status == constants.OP_STATUS_QUEUED
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
    self._updates = []
    self._submitted = []

    self._submit_count = itertools.count(1000)

    if depmgr:
      self.depmgr = depmgr
    else:
      self.depmgr = _DisabledFakeDependencyManager()

  def GetNextUpdate(self):
    return self._updates.pop(0)

  def GetNextSubmittedJob(self):
    return self._submitted.pop(0)

  def UpdateJobUnlocked(self, job, replicate=True):
    self._updates.append((job, bool(replicate)))

  def SubmitManyJobs(self, jobs):
    job_ids = [next(self._submit_count) for _ in jobs]
    self._submitted.extend(zip(job_ids, jobs))
    return job_ids


class _FakeExecOpCodeForProc:
  def __init__(self, queue, before_start, after_start):
    self._queue = queue
    self._before_start = before_start
    self._after_start = after_start

  def __call__(self, op, cbs, timeout=None):
    assert isinstance(op, opcodes.OpTestDummy)

    if self._before_start:
      self._before_start(timeout, cbs.CurrentPriority())

    cbs.NotifyStart()

    if self._after_start:
      self._after_start(op, cbs)

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
    self.assertTrue(compat.all(op.input == inp
                            for (op, inp) in zip(job.ops, ops)))
    return job


class TestJobProcessor(unittest.TestCase, _JobProcessorTestUtils):
  def _GenericCheckJob(self, job):
    assert compat.all(isinstance(op.input, opcodes.OpTestDummy)
                      for op in job.ops)

    self.assertTrue(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
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
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
        self.assertFalse(job.cur_opctx)

      def _AfterStart(op, cbs):
        self.assertEqual(queue.GetNextUpdate(), (job, True))
        self.assertRaises(IndexError, queue.GetNextUpdate)

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
          self.assertTrue(job.start_timestamp)
          self.assertFalse(job.end_timestamp)

      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
      self.assertTrue(compat.all(op.start_timestamp and op.end_timestamp
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
      job = self._CreateJob(queue, str(job_id), ops)

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

      # Check opcode status
      self.assertTrue(compat.all(op.start_timestamp and op.end_timestamp
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
    self.assertTrue(success)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    self.assertFalse(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assertTrue(compat.all(op.status == constants.OP_STATUS_CANCELED
                            for op in job.ops))

    # Serialize to check for differences
    before_proc = job.Serialize()

    # Simulate processor called in workerpool
    opexec = _FakeExecOpCodeForProc(queue, None, None)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertFalse(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assertFalse(compat.any(op.start_timestamp or op.end_timestamp
                                for op in job.ops))

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
    self.assertTrue(success)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    self.assertTrue(compat.all(op.status == constants.OP_STATUS_CANCELING
                            for op in job.ops))

    opexec = _FakeExecOpCodeForProc(queue, None, None)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertFalse(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assertFalse(compat.any(op.start_timestamp or op.end_timestamp
                                for op in job.ops))

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
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

      # Mark as cancelled
      (success, _) = job.Cancel()
      self.assertTrue(success)

      self.assertTrue(compat.all(op.status == constants.OP_STATUS_CANCELING
                              for op in job.ops))
      self.assertRaises(IndexError, queue.GetNextUpdate)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertRaises(IndexError, queue.GetNextUpdate)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertEqual(queue.GetNextUpdate(), (job, True))
    self.assertRaises(IndexError, queue.GetNextUpdate)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertTrue(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assertFalse(compat.all(op.start_timestamp and op.end_timestamp
                                for op in job.ops))

  def _TestCancelWhileSomething(self, cb):
    queue = _FakeQueueForProc()

    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(5)]

    # Create job
    job_id = 24314
    job = self._CreateJob(queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    def _BeforeStart(timeout, priority):
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

      # Mark as cancelled
      (success, _) = job.Cancel()
      self.assertTrue(success)

      self.assertTrue(compat.all(op.status == constants.OP_STATUS_CANCELING
                              for op in job.ops))

      cb(queue)

    def _AfterStart(op, cbs):
      self.fail("Should not reach this")

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
    self.assertTrue(job.start_timestamp)
    self.assertTrue(job.end_timestamp)
    self.assertFalse(compat.all(op.start_timestamp and op.end_timestamp
                                for op in job.ops))
    return queue

  def testCancelWhileWaitlockWithTimeout(self):
    def fn(_):
      # Fake an acquire attempt timing out
      raise mcpu.LockAcquireTimeout()

    self._TestCancelWhileSomething(fn)

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

    # Mark as cancelled
    (success, _) = job.Cancel()
    self.assertTrue(success)

    # Try processing another opcode (this will actually cancel the job)
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    # Check result
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)

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
      self.assertTrue(job.ops_iter)

      # Serialize and restore (simulates program restart)
      newjob = jqueue._QueuedJob.Restore(queue, job.Serialize(), True, False)
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
    self.assertTrue(compat.all(op.start_timestamp and op.end_timestamp
                            for op in job.ops))

    self._GenericCheckJob(job)

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, queue.GetNextUpdate)

    # ... also after being restored
    job2 = jqueue._QueuedJob.Restore(queue, job.Serialize(), True, False)
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
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)
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
    logmsgcount = sum(len(m) for m in messages.values())

    self._CheckLogMessages(job, logmsgcount)

    # Serialize and restore (simulates program restart)
    newjob = jqueue._QueuedJob.Restore(queue, job.Serialize(), True, False)
    self._CheckLogMessages(newjob, logmsgcount)

  def _CheckLogMessages(self, job, count):
    # Check serial
    self.assertEqual(job.log_serial, count)

    # Filter with serial
    assert count > 3
    self.assertTrue(job.GetLogEntries(3))

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
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

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
        self.assertTrue(job.start_timestamp)
        self.assertFalse(job.end_timestamp)

    self.assertRaises(IndexError, queue.GetNextUpdate)

    for idx, submitted_ops in enumerate(job_ops
                                        for op in ops
                                        for job_ops in op.submit_jobs):
      self.assertEqual(queue.GetNextSubmittedJob(),
                       (1000 + idx, submitted_ops))
    self.assertRaises(IndexError, queue.GetNextSubmittedJob)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)

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
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    counter = itertools.count()
    while True:
      attempt = next(counter)

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
        self.assertTrue(job.start_timestamp)
        self.assertFalse(job.end_timestamp)
        continue

      if result == jqueue._JobProcessor.FINISHED:
        # Last opcode
        self.assertFalse(job.cur_opctx)
        break

      self.assertRaises(IndexError, depmgr.GetNextNotification)

      self.assertEqual(result, jqueue._JobProcessor.DEFER)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertTrue(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
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
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    counter = itertools.count()
    while True:
      attempt = next(counter)

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
        self.assertTrue(job.start_timestamp)
        self.assertFalse(job.end_timestamp)
        continue

      if result == jqueue._JobProcessor.FINISHED:
        # Last opcode
        self.assertFalse(job.cur_opctx)
        break

      self.assertRaises(IndexError, depmgr.GetNextNotification)

      self.assertEqual(result, jqueue._JobProcessor.DEFER)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertTrue(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_CANCELED)
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
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)
      self.assertFalse(job.cur_opctx)

    def _AfterStart(op, cbs):
      self.assertEqual(queue.GetNextUpdate(), (job, True))
      self.assertRaises(IndexError, queue.GetNextUpdate)

      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)
      self.assertFalse(job.cur_opctx)

      # Job is running, cancelling shouldn't be possible
      (success, _) = job.Cancel()
      self.assertFalse(success)

    opexec = _FakeExecOpCodeForProc(queue, _BeforeStart, _AfterStart)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    counter = itertools.count()
    while True:
      attempt = next(counter)

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
        self.assertTrue(job.start_timestamp)
        self.assertFalse(job.end_timestamp)
        continue

      if result == jqueue._JobProcessor.FINISHED:
        # Last opcode
        self.assertFalse(job.cur_opctx)
        break

      self.assertRaises(IndexError, depmgr.GetNextNotification)

      self.assertEqual(result, jqueue._JobProcessor.DEFER)
      self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
      self.assertTrue(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_ERROR)

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

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

    ts = self.timeout_strategy

    self.assertTrue(timeout is None or isinstance(timeout, (int, float)))
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
      self.assertTrue(timeout is not None)
      self.retries -= 1
      self.gave_lock = False
      raise mcpu.LockAcquireTimeout()

    if job.ops[self.curop].priority == constants.OP_PRIO_HIGHEST:
      assert self.retries == 0, "Didn't exhaust all retries at highest priority"
      assert not ts.timeouts
      self.assertTrue(timeout is None)

  def _AfterStart(self, op, cbs):
    job = self.job

    # Setting to "running" requires an update
    self.assertEqual(self.queue.GetNextUpdate(), (job, True))
    self.assertRaises(IndexError, self.queue.GetNextUpdate)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_RUNNING)

    # Job is running, cancelling shouldn't be possible
    (success, _) = job.Cancel()
    self.assertFalse(success)

  def _NextOpcode(self):
    self.curop = next(self.opcounter)
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
      self.assertTrue(self.done_lock_before_blocking)

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
        self.assertTrue(job.ops[self.curop].exec_timestamp)

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
        self.assertTrue(job.cur_opctx)
        self.assertEqual(job.cur_opctx._timeout_strategy._fn,
                         self.timeout_strategy.NextAttempt)
        self.assertFalse(job.ops[self.curop].exec_timestamp)
        self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_WAITING)

        # If priority has changed since acquiring locks, the job must've been
        # updated
        if self.lock_acq_prio != job.ops[self.curop].priority:
          self.assertEqual(self.queue.GetNextUpdate(), (job, True))

      self.assertRaises(IndexError, self.queue.GetNextUpdate)

      self.assertTrue(job.start_timestamp)
      self.assertFalse(job.end_timestamp)

    self.assertEqual(self.curop, len(job.ops) - 1)
    self.assertEqual(self.job, job)
    self.assertEqual(next(self.opcounter), len(job.ops))
    self.assertTrue(self.done_lock_before_blocking)

    self.assertRaises(IndexError, self.queue.GetNextUpdate)
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertTrue(compat.all(op.start_timestamp and op.end_timestamp
                            for op in job.ops))

    # Calling the processor on a finished job should be a no-op
    self.assertEqual(jqueue._JobProcessor(self.queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)
    self.assertRaises(IndexError, self.queue.GetNextUpdate)


class TestJobProcessorChangePriority(unittest.TestCase, _JobProcessorTestUtils):
  def setUp(self):
    self.queue = _FakeQueueForProc()
    self.opexecprio = []

  def _BeforeStart(self, timeout, priority):
    self.opexecprio.append(priority)

  def testChangePriorityWhileRunning(self):
    # Tests changing the priority on a job while it has finished opcodes
    # (successful) and more, unprocessed ones
    ops = [opcodes.OpTestDummy(result="Res%s" % i, fail=False)
           for i in range(3)]

    # Create job
    job_id = 3499
    job = self._CreateJob(self.queue, job_id, ops)

    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)

    opexec = _FakeExecOpCodeForProc(self.queue, self._BeforeStart, None)

    # Run first opcode
    self.assertEqual(jqueue._JobProcessor(self.queue, opexec, job)(),
                     jqueue._JobProcessor.DEFER)

    # Job goes back to queued
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)

    self.assertEqual(self.opexecprio.pop(0), constants.OP_PRIO_DEFAULT)
    self.assertRaises(IndexError, self.opexecprio.pop, 0)

    # Change priority
    self.assertEqual(job.ChangePriority(-10),
                     (True,
                      ("Priorities of pending opcodes for job 3499 have"
                       " been changed to -10")))
    self.assertEqual(job.CalcPriority(), -10)

    # Process second opcode
    self.assertEqual(jqueue._JobProcessor(self.queue, opexec, job)(),
                     jqueue._JobProcessor.DEFER)

    self.assertEqual(self.opexecprio.pop(0), -10)
    self.assertRaises(IndexError, self.opexecprio.pop, 0)

    # Check status
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_QUEUED)
    self.assertEqual(job.CalcPriority(), -10)

    # Change priority once more
    self.assertEqual(job.ChangePriority(5),
                     (True,
                      ("Priorities of pending opcodes for job 3499 have"
                       " been changed to 5")))
    self.assertEqual(job.CalcPriority(), 5)

    # Process third opcode
    self.assertEqual(jqueue._JobProcessor(self.queue, opexec, job)(),
                     jqueue._JobProcessor.FINISHED)

    self.assertEqual(self.opexecprio.pop(0), 5)
    self.assertRaises(IndexError, self.opexecprio.pop, 0)

    # Check status
    self.assertEqual(job.CalcStatus(), constants.JOB_STATUS_SUCCESS)
    self.assertEqual(job.CalcPriority(), constants.OP_PRIO_DEFAULT)
    self.assertEqual([op.priority for op in job.ops],
                     [constants.OP_PRIO_DEFAULT, -10, 5])


class _IdOnlyFakeJob:
  def __init__(self, job_id, priority=NotImplemented):
    self.id = str(job_id)
    self._priority = priority

  def CalcPriority(self):
    return self._priority


class TestJobDependencyManager(unittest.TestCase):
  def setUp(self):
    self._status = []
    self._queue = []
    self.jdm = jqueue._JobDependencyManager(self._GetStatus)

  def _GetStatus(self, job_id):
    (exp_job_id, result) = self._status.pop(0)
    self.assertEqual(exp_job_id, job_id)
    return result

  def testNotFinalizedThenCancel(self):
    job = _IdOnlyFakeJob(17697)
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

    self._status.append((job_id, constants.JOB_STATUS_CANCELED))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, [])
    self.assertEqual(result, self.jdm.CANCEL)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))

  def testNotFinalizedThenQueued(self):
    # This can happen on a queue shutdown
    job = _IdOnlyFakeJob(1320)
    job_id = str(22971)

    for i in range(5):
      if i > 2:
        self._status.append((job_id, constants.JOB_STATUS_QUEUED))
      else:
        self._status.append((job_id, constants.JOB_STATUS_RUNNING))
      (result, _) = self.jdm.CheckAndRegister(job, job_id, [])
      self.assertEqual(result, self.jdm.WAIT)
      self.assertFalse(self._status)
      self.assertFalse(self._queue)
      self.assertTrue(self.jdm.JobWaiting(job))
      self.assertEqual(self.jdm._waiters, {
        job_id: set([job]),
        })

  def testRequireCancel(self):
    job = _IdOnlyFakeJob(5278)
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

    self._status.append((job_id, constants.JOB_STATUS_CANCELED))
    (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
    self.assertEqual(result, self.jdm.CONTINUE)
    self.assertFalse(self._status)
    self.assertFalse(self._queue)
    self.assertFalse(self.jdm.JobWaiting(job))

  def testRequireError(self):
    job = _IdOnlyFakeJob(21459)
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

  def testRequireMultiple(self):
    dep_status = list(constants.JOBS_FINALIZED)

    for end_status in dep_status:
      job = _IdOnlyFakeJob(21343)
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

      self._status.append((job_id, end_status))
      (result, _) = self.jdm.CheckAndRegister(job, job_id, dep_status)
      self.assertEqual(result, self.jdm.CONTINUE)
      self.assertFalse(self._status)
      self.assertFalse(self._queue)
      self.assertFalse(self.jdm.JobWaiting(job))

  def testWrongStatus(self):
    job = _IdOnlyFakeJob(10102)
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
    job = _IdOnlyFakeJob(24273)
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
    job = _IdOnlyFakeJob(224)
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

  def testSelfDependency(self):
    job = _IdOnlyFakeJob(18937)

    self._status.append((job.id, constants.JOB_STATUS_SUCCESS))
    (result, _) = self.jdm.CheckAndRegister(job, job.id, [])
    self.assertEqual(result, self.jdm.ERROR)

  def testJobDisappears(self):
    job = _IdOnlyFakeJob(30540)
    job_id = str(23769)

    def _FakeStatus(_):
      raise errors.JobLost("#msg#")

    jdm = jqueue._JobDependencyManager(_FakeStatus)
    (result, _) = jdm.CheckAndRegister(job, job_id, [])
    self.assertEqual(result, self.jdm.ERROR)
    self.assertFalse(jdm.JobWaiting(job))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
