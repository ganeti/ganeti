#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.client.gnt_job"""

import unittest
import optparse

from ganeti.client import gnt_job
from ganeti import utils
from ganeti import errors
from ganeti import query
from ganeti import qlang
from ganeti import objects
from ganeti import compat
from ganeti import constants

import testutils


class _ClientForCancelJob:
  def __init__(self, cancel_cb, query_cb):
    self.cancelled = []
    self._cancel_cb = cancel_cb
    self._query_cb = query_cb

  def CancelJob(self, job_id, kill=False):
    self.cancelled.append(job_id)
    return self._cancel_cb(job_id)

  def Query(self, kind, selected, qfilter):
    assert kind == constants.QR_JOB
    assert selected == ["id", "status", "summary"]

    fields = query.GetAllFields(query._GetQueryFields(query.JOB_FIELDS,
                                                      selected))

    return objects.QueryResponse(data=self._query_cb(qfilter),
                                 fields=fields)


class TestCancelJob(unittest.TestCase):
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.stdout = []

  def _ToStdout(self, line):
    self.stdout.append(line)

  def _Ask(self, answer, question):
    self.assertTrue(question.endswith("?"))
    return answer

  def testStatusFilterAndArguments(self):
    opts = optparse.Values(dict(status_filter=frozenset(), force=False,
                                kill=False))
    try:
      gnt_job.CancelJobs(opts, ["a"], cl=NotImplemented,
                         _stdout_fn=NotImplemented, _ask_fn=NotImplemented)
    except errors.OpPrereqError, err:
      self.assertEqual(err.args[1], errors.ECODE_INVAL)
    else:
      self.fail("Did not raise exception")

  def _TestArguments(self, force):
    opts = optparse.Values(dict(status_filter=None, force=force, kill=False))

    def _CancelCb(job_id):
      self.assertTrue(job_id in ("24185", "3252"))
      return (True, "%s will be cancelled" % job_id)

    cl = _ClientForCancelJob(_CancelCb, NotImplemented)
    self.assertEqual(gnt_job.CancelJobs(opts, ["24185", "3252"], cl=cl,
                                        _stdout_fn=self._ToStdout,
                                        _ask_fn=NotImplemented),
                     constants.EXIT_SUCCESS)
    self.assertEqual(cl.cancelled, ["24185", "3252"])
    self.assertEqual(self.stdout, [
      "24185 will be cancelled",
      "3252 will be cancelled",
      ])

  def testArgumentsWithForce(self):
    self._TestArguments(True)

  def testArgumentsNoForce(self):
    self._TestArguments(False)

  def testArgumentsWithError(self):
    opts = optparse.Values(dict(status_filter=None, force=True, kill=False))

    def _CancelCb(job_id):
      if job_id == "10788":
        return (False, "error %s" % job_id)
      else:
        return (True, "%s will be cancelled" % job_id)

    cl = _ClientForCancelJob(_CancelCb, NotImplemented)
    self.assertEqual(gnt_job.CancelJobs(opts, ["203", "10788", "30801"], cl=cl,
                                        _stdout_fn=self._ToStdout,
                                        _ask_fn=NotImplemented),
                     constants.EXIT_FAILURE)
    self.assertEqual(cl.cancelled, ["203", "10788", "30801"])
    self.assertEqual(self.stdout, [
      "203 will be cancelled",
      "error 10788",
      "30801 will be cancelled",
      ])

  def testFilterPending(self):
    opts = optparse.Values(dict(status_filter=constants.JOBS_PENDING,
                                force=False, kill=False))

    def _Query(qfilter):
      # Need to sort as constants.JOBS_PENDING has no stable order
      assert isinstance(constants.JOBS_PENDING, frozenset)
      self.assertEqual(sorted(qfilter),
                       sorted(qlang.MakeSimpleFilter("status",
                                                     constants.JOBS_PENDING)))

      return [
        [(constants.RS_UNAVAIL, None),
         (constants.RS_UNAVAIL, None),
         (constants.RS_UNAVAIL, None)],
        [(constants.RS_NORMAL, 32532),
         (constants.RS_NORMAL, constants.JOB_STATUS_QUEUED),
         (constants.RS_NORMAL, ["op1", "op2", "op3"])],
        ]

    cl = _ClientForCancelJob(NotImplemented, _Query)

    result = gnt_job.CancelJobs(opts, [], cl=cl,
                                _stdout_fn=self._ToStdout,
                                _ask_fn=compat.partial(self._Ask, False))
    self.assertEqual(result, constants.EXIT_CONFIRMATION)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
