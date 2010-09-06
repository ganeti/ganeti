#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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

from ganeti import constants
from ganeti import utils
from ganeti import errors
from ganeti import jqueue

import testutils


class _FakeJob:
  def __init__(self, job_id, status):
    self.id = job_id
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
    return _FakeJob(2614226563, constants.JOB_STATUS_WAITLOCK)

  def _LoadLostJob(self):
    return None

  def testNoChanges(self):
    wfjc = jqueue._WaitForJobChangesHelper()

    # No change
    self.assertEqual(wfjc(self.filename, self._LoadWaitingJob, ["status"],
                          [constants.JOB_STATUS_WAITLOCK], None, 0.1),
                     constants.JOB_NOTCHANGED)

    # No previous information
    self.assertEqual(wfjc(self.filename, self._LoadWaitingJob,
                          ["status"], None, None, 1.0),
                     ([constants.JOB_STATUS_WAITLOCK], []))

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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
