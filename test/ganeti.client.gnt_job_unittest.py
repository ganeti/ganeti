#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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

  def CancelJob(self, job_id):
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
    opts = optparse.Values(dict(status_filter=frozenset()))
    try:
      gnt_job.CancelJobs(opts, ["a"], cl=NotImplemented,
                         _stdout_fn=NotImplemented, _ask_fn=NotImplemented)
    except errors.OpPrereqError, err:
      self.assertEqual(err.args[1], errors.ECODE_INVAL)
    else:
      self.fail("Did not raise exception")

  def _TestArguments(self, force):
    opts = optparse.Values(dict(status_filter=None, force=force))

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
    opts = optparse.Values(dict(status_filter=None, force=True))

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
                                force=False))

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
