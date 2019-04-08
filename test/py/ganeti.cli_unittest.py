#!/usr/bin/python
#

# Copyright (C) 2008, 2011, 2012, 2013 Google Inc.
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


"""Script for unittesting the cli module"""

import copy
import testutils
import time
import unittest
import yaml
from io import StringIO

from ganeti import constants
from ganeti import cli
from ganeti import errors
from ganeti import utils
from ganeti import objects
from ganeti import qlang
from ganeti.errors import OpPrereqError, ParameterError


class TestParseTimespec(unittest.TestCase):
  """Testing case for ParseTimespec"""

  def testValidTimes(self):
    """Test valid timespecs"""
    test_data = [
      ("1s", 1),
      ("1", 1),
      ("1m", 60),
      ("1h", 60 * 60),
      ("1d", 60 * 60 * 24),
      ("1w", 60 * 60 * 24 * 7),
      ("4h", 4 * 60 * 60),
      ("61m", 61 * 60),
      ]
    for value, expected_result in test_data:
      self.assertEqual(cli.ParseTimespec(value), expected_result)

  def testInvalidTime(self):
    """Test invalid timespecs"""
    test_data = [
      "1y",
      "",
      "aaa",
      "s",
      ]
    for value in test_data:
      self.assertRaises(OpPrereqError, cli.ParseTimespec, value)


class TestToStream(unittest.TestCase):
  """Test the ToStream functions"""

  def testBasic(self):
    for data in ["foo",
                 "foo %s",
                 "foo %(test)s",
                 "foo %s %s",
                 "",
                 ]:
      buf = StringIO()
      cli._ToStream(buf, data)
      self.assertEqual(buf.getvalue(), data + "\n")

  def testParams(self):
      buf = StringIO()
      cli._ToStream(buf, "foo %s", 1)
      self.assertEqual(buf.getvalue(), "foo 1\n")
      buf = StringIO()
      cli._ToStream(buf, "foo %s", (15,16))
      self.assertEqual(buf.getvalue(), "foo (15, 16)\n")
      buf = StringIO()
      cli._ToStream(buf, "foo %s %s", "a", "b")
      self.assertEqual(buf.getvalue(), "foo a b\n")


class TestGenerateTable(unittest.TestCase):
  HEADERS = dict([("f%s" % i, "Field%s" % i) for i in range(5)])

  FIELDS1 = ["f1", "f2"]
  DATA1 = [
    ["abc", 1234],
    ["foobar", 56],
    ["b", -14],
    ]

  def _test(self, headers, fields, separator, data,
            numfields, unitfields, units, expected):
    table = cli.GenerateTable(headers, fields, separator, data,
                              numfields=numfields, unitfields=unitfields,
                              units=units)
    self.assertEqual(table, expected)

  def testPlain(self):
    exp = [
      "Field1 Field2",
      "abc    1234",
      "foobar 56",
      "b      -14",
      ]
    self._test(self.HEADERS, self.FIELDS1, None, self.DATA1,
               None, None, "m", exp)

  def testNoFields(self):
    self._test(self.HEADERS, [], None, [[], []],
               None, None, "m", ["", "", ""])
    self._test(None, [], None, [[], []],
               None, None, "m", ["", ""])

  def testSeparator(self):
    for sep in ["#", ":", ",", "^", "!", "%", "|", "###", "%%", "!!!", "||"]:
      exp = [
        "Field1%sField2" % sep,
        "abc%s1234" % sep,
        "foobar%s56" % sep,
        "b%s-14" % sep,
        ]
      self._test(self.HEADERS, self.FIELDS1, sep, self.DATA1,
                 None, None, "m", exp)

  def testNoHeader(self):
    exp = [
      "abc    1234",
      "foobar 56",
      "b      -14",
      ]
    self._test(None, self.FIELDS1, None, self.DATA1,
               None, None, "m", exp)

  def testUnknownField(self):
    headers = {
      "f1": "Field1",
      }
    exp = [
      "Field1 UNKNOWN",
      "abc    1234",
      "foobar 56",
      "b      -14",
      ]
    self._test(headers, ["f1", "UNKNOWN"], None, self.DATA1,
               None, None, "m", exp)

  def testNumfields(self):
    fields = ["f1", "f2", "f3"]
    data = [
      ["abc", 1234, 0],
      ["foobar", 56, 3],
      ["b", -14, "-"],
      ]
    exp = [
      "Field1 Field2 Field3",
      "abc      1234      0",
      "foobar     56      3",
      "b         -14      -",
      ]
    self._test(self.HEADERS, fields, None, data,
               ["f2", "f3"], None, "m", exp)

  def testUnitfields(self):
    expnosep = [
      "Field1 Field2 Field3",
      "abc      1234     0M",
      "foobar     56     3M",
      "b         -14      -",
      ]

    expsep = [
      "Field1:Field2:Field3",
      "abc:1234:0M",
      "foobar:56:3M",
      "b:-14:-",
      ]

    for sep, expected in [(None, expnosep), (":", expsep)]:
      fields = ["f1", "f2", "f3"]
      data = [
        ["abc", 1234, 0],
        ["foobar", 56, 3],
        ["b", -14, "-"],
        ]
      self._test(self.HEADERS, fields, sep, data,
                 ["f2", "f3"], ["f3"], "h", expected)

  def testUnusual(self):
    data = [
      ["%", "xyz"],
      ["%%", "abc"],
      ]
    exp = [
      "Field1 Field2",
      "%      xyz",
      "%%     abc",
      ]
    self._test(self.HEADERS, ["f1", "f2"], None, data,
               None, None, "m", exp)


class TestFormatQueryResult(unittest.TestCase):
  def test(self):
    fields = [
      objects.QueryFieldDefinition(name="name", title="Name",
                                   kind=constants.QFT_TEXT),
      objects.QueryFieldDefinition(name="size", title="Size",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="act", title="Active",
                                   kind=constants.QFT_BOOL),
      objects.QueryFieldDefinition(name="mem", title="Memory",
                                   kind=constants.QFT_UNIT),
      objects.QueryFieldDefinition(name="other", title="SomeList",
                                   kind=constants.QFT_OTHER),
      ]

    response = objects.QueryResponse(fields=fields, data=[
      [(constants.RS_NORMAL, "nodeA"), (constants.RS_NORMAL, 128),
       (constants.RS_NORMAL, False), (constants.RS_NORMAL, 1468006),
       (constants.RS_NORMAL, [])],
      [(constants.RS_NORMAL, "other"), (constants.RS_NORMAL, 512),
       (constants.RS_NORMAL, True), (constants.RS_NORMAL, 16),
       (constants.RS_NORMAL, [1, 2, 3])],
      [(constants.RS_NORMAL, "xyz"), (constants.RS_NORMAL, 1024),
       (constants.RS_NORMAL, True), (constants.RS_NORMAL, 4096),
       (constants.RS_NORMAL, [{}, {}])],
      ])

    self.assertEqual(cli.FormatQueryResult(response, unit="h", header=True),
      (cli.QR_NORMAL, [
      "Name  Size Active Memory SomeList",
      "nodeA  128 N        1.4T []",
      "other  512 Y         16M [1, 2, 3]",
      "xyz   1024 Y        4.0G [{}, {}]",
      ]))

  def testTimestampAndUnit(self):
    fields = [
      objects.QueryFieldDefinition(name="name", title="Name",
                                   kind=constants.QFT_TEXT),
      objects.QueryFieldDefinition(name="size", title="Size",
                                   kind=constants.QFT_UNIT),
      objects.QueryFieldDefinition(name="mtime", title="ModTime",
                                   kind=constants.QFT_TIMESTAMP),
      ]

    response = objects.QueryResponse(fields=fields, data=[
      [(constants.RS_NORMAL, "a"), (constants.RS_NORMAL, 1024),
       (constants.RS_NORMAL, 0)],
      [(constants.RS_NORMAL, "b"), (constants.RS_NORMAL, 144996),
       (constants.RS_NORMAL, 1291746295)],
      ])

    self.assertEqual(cli.FormatQueryResult(response, unit="m", header=True),
      (cli.QR_NORMAL, [
      "Name   Size ModTime",
      "a      1024 %s" % utils.FormatTime(0),
      "b    144996 %s" % utils.FormatTime(1291746295),
      ]))

  def testOverride(self):
    fields = [
      objects.QueryFieldDefinition(name="name", title="Name",
                                   kind=constants.QFT_TEXT),
      objects.QueryFieldDefinition(name="cust", title="Custom",
                                   kind=constants.QFT_OTHER),
      objects.QueryFieldDefinition(name="xt", title="XTime",
                                   kind=constants.QFT_TIMESTAMP),
      ]

    response = objects.QueryResponse(fields=fields, data=[
      [(constants.RS_NORMAL, "x"), (constants.RS_NORMAL, ["a", "b", "c"]),
       (constants.RS_NORMAL, 1234)],
      [(constants.RS_NORMAL, "y"), (constants.RS_NORMAL, range(10)),
       (constants.RS_NORMAL, 1291746295)],
      ])

    override = {
      "cust": (utils.CommaJoin, False),
      "xt": (hex, True),
      }

    self.assertEqual(cli.FormatQueryResult(response, unit="h", header=True,
                                           format_override=override),
      (cli.QR_NORMAL, [
      "Name Custom                            XTime",
      "x    a, b, c                           0x4d2",
      "y    0, 1, 2, 3, 4, 5, 6, 7, 8, 9 0x4cfe7bf7",
      ]))

  def testSeparator(self):
    fields = [
      objects.QueryFieldDefinition(name="name", title="Name",
                                   kind=constants.QFT_TEXT),
      objects.QueryFieldDefinition(name="count", title="Count",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="desc", title="Description",
                                   kind=constants.QFT_TEXT),
      ]

    response = objects.QueryResponse(fields=fields, data=[
      [(constants.RS_NORMAL, "instance1.example.com"),
       (constants.RS_NORMAL, 21125), (constants.RS_NORMAL, "Hello World!")],
      [(constants.RS_NORMAL, "mail.other.net"),
       (constants.RS_NORMAL, -9000), (constants.RS_NORMAL, "a,b,c")],
      ])

    for sep in [":", "|", "#", "|||", "###", "@@@", "@#@"]:
      for header in [None, "Name%sCount%sDescription" % (sep, sep)]:
        exp = []
        if header:
          exp.append(header)
        exp.extend([
          "instance1.example.com%s21125%sHello World!" % (sep, sep),
          "mail.other.net%s-9000%sa,b,c" % (sep, sep),
          ])

        self.assertEqual(cli.FormatQueryResult(response, separator=sep,
                                               header=bool(header)),
                         (cli.QR_NORMAL, exp))

  def testStatusWithUnknown(self):
    fields = [
      objects.QueryFieldDefinition(name="id", title="ID",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="unk", title="unk",
                                   kind=constants.QFT_UNKNOWN),
      objects.QueryFieldDefinition(name="unavail", title="Unavail",
                                   kind=constants.QFT_BOOL),
      objects.QueryFieldDefinition(name="nodata", title="NoData",
                                   kind=constants.QFT_TEXT),
      objects.QueryFieldDefinition(name="offline", title="OffLine",
                                   kind=constants.QFT_TEXT),
      ]

    response = objects.QueryResponse(fields=fields, data=[
      [(constants.RS_NORMAL, 1), (constants.RS_UNKNOWN, None),
       (constants.RS_NORMAL, False), (constants.RS_NORMAL, ""),
       (constants.RS_OFFLINE, None)],
      [(constants.RS_NORMAL, 2), (constants.RS_UNKNOWN, None),
       (constants.RS_NODATA, None), (constants.RS_NORMAL, "x"),
       (constants.RS_OFFLINE, None)],
      [(constants.RS_NORMAL, 3), (constants.RS_UNKNOWN, None),
       (constants.RS_NORMAL, False), (constants.RS_UNAVAIL, None),
       (constants.RS_OFFLINE, None)],
      ])

    self.assertEqual(cli.FormatQueryResult(response, header=True,
                                           separator="|", verbose=True),
      (cli.QR_UNKNOWN, [
      "ID|unk|Unavail|NoData|OffLine",
      "1|(unknown)|N||(offline)",
      "2|(unknown)|(nodata)|x|(offline)",
      "3|(unknown)|N|(unavail)|(offline)",
      ]))
    self.assertEqual(cli.FormatQueryResult(response, header=True,
                                           separator="|", verbose=False),
      (cli.QR_UNKNOWN, [
      "ID|unk|Unavail|NoData|OffLine",
      "1|??|N||*",
      "2|??|?|x|*",
      "3|??|N|-|*",
      ]))

  def testNoData(self):
    fields = [
      objects.QueryFieldDefinition(name="id", title="ID",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="name", title="Name",
                                   kind=constants.QFT_TEXT),
      ]

    response = objects.QueryResponse(fields=fields, data=[])

    self.assertEqual(cli.FormatQueryResult(response, header=True),
                     (cli.QR_NORMAL, ["ID Name"]))

  def testNoDataWithUnknown(self):
    fields = [
      objects.QueryFieldDefinition(name="id", title="ID",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="unk", title="unk",
                                   kind=constants.QFT_UNKNOWN),
      ]

    response = objects.QueryResponse(fields=fields, data=[])

    self.assertEqual(cli.FormatQueryResult(response, header=False),
                     (cli.QR_UNKNOWN, []))

  def testStatus(self):
    fields = [
      objects.QueryFieldDefinition(name="id", title="ID",
                                   kind=constants.QFT_NUMBER),
      objects.QueryFieldDefinition(name="unavail", title="Unavail",
                                   kind=constants.QFT_BOOL),
      objects.QueryFieldDefinition(name="nodata", title="NoData",
                                   kind=constants.QFT_TEXT),
      objects.QueryFieldDefinition(name="offline", title="OffLine",
                                   kind=constants.QFT_TEXT),
      ]

    response = objects.QueryResponse(fields=fields, data=[
      [(constants.RS_NORMAL, 1), (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, ""), (constants.RS_OFFLINE, None)],
      [(constants.RS_NORMAL, 2), (constants.RS_NODATA, None),
       (constants.RS_NORMAL, "x"), (constants.RS_NORMAL, "abc")],
      [(constants.RS_NORMAL, 3), (constants.RS_NORMAL, False),
       (constants.RS_UNAVAIL, None), (constants.RS_OFFLINE, None)],
      ])

    self.assertEqual(cli.FormatQueryResult(response, header=False,
                                           separator="|", verbose=True),
      (cli.QR_INCOMPLETE, [
      "1|N||(offline)",
      "2|(nodata)|x|abc",
      "3|N|(unavail)|(offline)",
      ]))
    self.assertEqual(cli.FormatQueryResult(response, header=False,
                                           separator="|", verbose=False),
      (cli.QR_INCOMPLETE, [
      "1|N||*",
      "2|?|x|abc",
      "3|N|-|*",
      ]))

  def testInvalidFieldType(self):
    fields = [
      objects.QueryFieldDefinition(name="x", title="x",
                                   kind="#some#other#type"),
      ]

    response = objects.QueryResponse(fields=fields, data=[])

    self.assertRaises(NotImplementedError, cli.FormatQueryResult, response)

  def testInvalidFieldStatus(self):
    fields = [
      objects.QueryFieldDefinition(name="x", title="x",
                                   kind=constants.QFT_TEXT),
      ]

    response = objects.QueryResponse(fields=fields, data=[[(-1, None)]])
    self.assertRaises(NotImplementedError, cli.FormatQueryResult, response)

    response = objects.QueryResponse(fields=fields, data=[[(-1, "x")]])
    self.assertRaises(AssertionError, cli.FormatQueryResult, response)

  def testEmptyFieldTitle(self):
    fields = [
      objects.QueryFieldDefinition(name="x", title="",
                                   kind=constants.QFT_TEXT),
      ]

    response = objects.QueryResponse(fields=fields, data=[])
    self.assertRaises(AssertionError, cli.FormatQueryResult, response)


class _MockJobPollCb(cli.JobPollCbBase, cli.JobPollReportCbBase):
  def __init__(self, tc, job_id):
    self.tc = tc
    self.job_id = job_id
    self._wfjcr = []
    self._jobstatus = []
    self._expect_notchanged = False
    self._expect_log = []

  def CheckEmpty(self):
    self.tc.assertFalse(self._wfjcr)
    self.tc.assertFalse(self._jobstatus)
    self.tc.assertFalse(self._expect_notchanged)
    self.tc.assertFalse(self._expect_log)

  def AddWfjcResult(self, *args):
    self._wfjcr.append(args)

  def AddQueryJobsResult(self, *args):
    self._jobstatus.append(args)

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial,
                           timeout=constants.DEFAULT_WFJC_TIMEOUT):
    self.tc.assertEqual(job_id, self.job_id)
    self.tc.assertEqualValues(fields, ["status"])
    self.tc.assertFalse(self._expect_notchanged)
    self.tc.assertFalse(self._expect_log)

    (exp_prev_job_info, exp_prev_log_serial, result) = self._wfjcr.pop(0)
    self.tc.assertEqualValues(prev_job_info, exp_prev_job_info)
    self.tc.assertEqual(prev_log_serial, exp_prev_log_serial)

    if result == constants.JOB_NOTCHANGED:
      self._expect_notchanged = True
    elif result:
      (_, logmsgs) = result
      if logmsgs:
        self._expect_log.extend(logmsgs)

    return result

  def QueryJobs(self, job_ids, fields):
    self.tc.assertEqual(job_ids, [self.job_id])
    self.tc.assertEqualValues(fields, ["status", "opstatus", "opresult"])
    self.tc.assertFalse(self._expect_notchanged)
    self.tc.assertFalse(self._expect_log)

    result = self._jobstatus.pop(0)
    self.tc.assertEqual(len(fields), len(result))
    return [result]

  def CancelJob(self, job_id):
    self.tc.assertEqual(job_id, self.job_id)

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    self.tc.assertEqual(job_id, self.job_id)
    self.tc.assertEqualValues((serial, timestamp, log_type, log_msg),
                              self._expect_log.pop(0))

  def ReportNotChanged(self, job_id, status):
    self.tc.assertEqual(job_id, self.job_id)
    self.tc.assertTrue(self._expect_notchanged)
    self._expect_notchanged = False


class TestGenericPollJob(testutils.GanetiTestCase):
  def testSuccessWithLog(self):
    job_id = 29609
    cbs = _MockJobPollCb(self, job_id)

    cbs.AddWfjcResult(None, None, constants.JOB_NOTCHANGED)

    cbs.AddWfjcResult(None, None,
                      ((constants.JOB_STATUS_QUEUED, ), None))

    cbs.AddWfjcResult((constants.JOB_STATUS_QUEUED, ), None,
                      constants.JOB_NOTCHANGED)

    cbs.AddWfjcResult((constants.JOB_STATUS_QUEUED, ), None,
                      ((constants.JOB_STATUS_RUNNING, ),
                       [(1, utils.SplitTime(1273491611.0),
                         constants.ELOG_MESSAGE, "Step 1"),
                        (2, utils.SplitTime(1273491615.9),
                         constants.ELOG_MESSAGE, "Step 2"),
                        (3, utils.SplitTime(1273491625.02),
                         constants.ELOG_MESSAGE, "Step 3"),
                        (4, utils.SplitTime(1273491635.05),
                         constants.ELOG_MESSAGE, "Step 4"),
                        (37, utils.SplitTime(1273491645.0),
                         constants.ELOG_MESSAGE, "Step 5"),
                        (203, utils.SplitTime(127349155.0),
                         constants.ELOG_MESSAGE, "Step 6")]))

    cbs.AddWfjcResult((constants.JOB_STATUS_RUNNING, ), 203,
                      ((constants.JOB_STATUS_RUNNING, ),
                       [(300, utils.SplitTime(1273491711.01),
                         constants.ELOG_MESSAGE, "Step X"),
                        (302, utils.SplitTime(1273491815.8),
                         constants.ELOG_MESSAGE, "Step Y"),
                        (303, utils.SplitTime(1273491925.32),
                         constants.ELOG_MESSAGE, "Step Z")]))

    cbs.AddWfjcResult((constants.JOB_STATUS_RUNNING, ), 303,
                      ((constants.JOB_STATUS_SUCCESS, ), None))

    cbs.AddQueryJobsResult(constants.JOB_STATUS_SUCCESS,
                           [constants.OP_STATUS_SUCCESS,
                            constants.OP_STATUS_SUCCESS],
                           ["Hello World", "Foo man bar"])

    self.assertEqual(["Hello World", "Foo man bar"],
                     cli.GenericPollJob(job_id, cbs, cbs))
    cbs.CheckEmpty()

  def testJobLost(self):
    job_id = 13746

    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, constants.JOB_NOTCHANGED)
    cbs.AddWfjcResult(None, None, None)
    self.assertRaises(errors.JobLost, cli.GenericPollJob, job_id, cbs, cbs)
    cbs.CheckEmpty()

  def testError(self):
    job_id = 31088

    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, constants.JOB_NOTCHANGED)
    cbs.AddWfjcResult(None, None, ((constants.JOB_STATUS_ERROR, ), None))
    cbs.AddQueryJobsResult(constants.JOB_STATUS_ERROR,
                           [constants.OP_STATUS_SUCCESS,
                            constants.OP_STATUS_ERROR],
                           ["Hello World", "Error code 123"])
    self.assertRaises(errors.OpExecError, cli.GenericPollJob, job_id, cbs, cbs)
    cbs.CheckEmpty()

  def testError2(self):
    job_id = 22235

    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, ((constants.JOB_STATUS_ERROR, ), None))
    encexc = errors.EncodeException(errors.LockError("problem"))
    cbs.AddQueryJobsResult(constants.JOB_STATUS_ERROR,
                           [constants.OP_STATUS_ERROR], [encexc])
    self.assertRaises(errors.LockError, cli.GenericPollJob, job_id, cbs, cbs)
    cbs.CheckEmpty()

  def testWeirdError(self):
    job_id = 28847

    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, ((constants.JOB_STATUS_ERROR, ), None))
    cbs.AddQueryJobsResult(constants.JOB_STATUS_ERROR,
                           [constants.OP_STATUS_RUNNING,
                            constants.OP_STATUS_RUNNING],
                           [None, None])
    self.assertRaises(errors.OpExecError, cli.GenericPollJob, job_id, cbs, cbs)
    cbs.CheckEmpty()

  def testCancel(self):
    job_id = 4275

    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, constants.JOB_NOTCHANGED)
    cbs.AddWfjcResult(None, None, ((constants.JOB_STATUS_CANCELING, ), None))
    cbs.AddQueryJobsResult(constants.JOB_STATUS_CANCELING,
                           [constants.OP_STATUS_CANCELING,
                            constants.OP_STATUS_CANCELING],
                           [None, None])
    self.assertRaises(errors.JobCanceled, cli.GenericPollJob, job_id, cbs, cbs)
    cbs.CheckEmpty()

  def testNegativeUpdateFreqParameter(self):
    job_id = 12345

    cbs = _MockJobPollCb(self, job_id)
    self.assertRaises(errors.ParameterError, cli.GenericPollJob, job_id, cbs,
                      cbs, update_freq=-30)

  def testZeroUpdateFreqParameter(self):
    job_id = 12345

    cbs = _MockJobPollCb(self, job_id)
    self.assertRaises(errors.ParameterError, cli.GenericPollJob, job_id, cbs,
                      cbs, update_freq=0)

  def testShouldCancel(self):
    job_id = 12345

    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, constants.JOB_NOTCHANGED)
    self.assertRaises(errors.JobCanceled, cli.GenericPollJob, job_id, cbs, cbs,
                      cancel_fn=(lambda: True))

  def testIgnoreCancel(self):
    job_id = 12345
    cbs = _MockJobPollCb(self, job_id)
    cbs.AddWfjcResult(None, None, ((constants.JOB_STATUS_SUCCESS, ), None))
    cbs.AddQueryJobsResult(constants.JOB_STATUS_SUCCESS,
                           [constants.OP_STATUS_SUCCESS,
                            constants.OP_STATUS_SUCCESS],
                           ["Hello World", "Foo man bar"])
    self.assertEqual(["Hello World", "Foo man bar"],
                     cli.GenericPollJob(
                         job_id, cbs, cbs, cancel_fn=(lambda: False)))
    cbs.CheckEmpty()

class TestFormatLogMessage(unittest.TestCase):
  def test(self):
    self.assertEqual(cli.FormatLogMessage(constants.ELOG_MESSAGE,
                                          "Hello World"),
                     "Hello World")
    self.assertRaises(TypeError, cli.FormatLogMessage,
                      constants.ELOG_MESSAGE, [1, 2, 3])

    self.assertTrue(cli.FormatLogMessage("some other type", (1, 2, 3)))


class TestParseFields(unittest.TestCase):
  def test(self):
    self.assertEqual(cli.ParseFields(None, []), [])
    self.assertEqual(cli.ParseFields("name,foo,hello", []),
                     ["name", "foo", "hello"])
    self.assertEqual(cli.ParseFields(None, ["def", "ault", "fields", "here"]),
                     ["def", "ault", "fields", "here"])
    self.assertEqual(cli.ParseFields("name,foo", ["def", "ault"]),
                     ["name", "foo"])
    self.assertEqual(cli.ParseFields("+name,foo", ["def", "ault"]),
                     ["def", "ault", "name", "foo"])


class TestParseNicOption(unittest.TestCase):
  def test(self):
    self.assertEqual(cli.ParseNicOption([("0", { "link": "eth0", })]),
                     [{ "link": "eth0", }])
    self.assertEqual(cli.ParseNicOption([("5", { "ip": "192.0.2.7", })]),
                     [{}, {}, {}, {}, {}, { "ip": "192.0.2.7", }])

  def testErrors(self):
    for i in [None, "", "abc", "zero", "Hello World", "\0", []]:
      self.assertRaises(errors.OpPrereqError, cli.ParseNicOption,
                        [(i, { "link": "eth0", })])
      self.assertRaises(errors.OpPrereqError, cli.ParseNicOption,
                        [("0", i)])

    self.assertRaises(errors.TypeEnforcementError, cli.ParseNicOption,
                      [(0, { True: False, })])

    self.assertRaises(errors.TypeEnforcementError, cli.ParseNicOption,
                      [(3, { "mode": [], })])


class TestFormatResultError(unittest.TestCase):
  def testNormal(self):
    for verbose in [False, True]:
      self.assertRaises(AssertionError, cli.FormatResultError,
                        constants.RS_NORMAL, verbose)

  def testUnknown(self):
    for verbose in [False, True]:
      self.assertRaises(NotImplementedError, cli.FormatResultError,
                        "#some!other!status#", verbose)

  def test(self):
    for status in constants.RS_ALL:
      if status == constants.RS_NORMAL:
        continue

      self.assertNotEqual(cli.FormatResultError(status, False),
                          cli.FormatResultError(status, True))

      result = cli.FormatResultError(status, True)
      self.assertTrue(result.startswith("("))
      self.assertTrue(result.endswith(")"))


class TestGetOnlineNodes(unittest.TestCase):
  class _FakeClient:
    def __init__(self):
      self._query = []

    def AddQueryResult(self, *args):
      self._query.append(args)

    def CountPending(self):
      return len(self._query)

    def Query(self, res, fields, qfilter):
      if res != constants.QR_NODE:
        raise Exception("Querying wrong resource")

      (exp_fields, check_filter, result) = self._query.pop(0)

      if exp_fields != fields:
        raise Exception("Expected fields %s, got %s" % (exp_fields, fields))

      if not (qfilter is None or check_filter(qfilter)):
        raise Exception("Filter doesn't match expectations")

      return objects.QueryResponse(fields=None, data=result)

  def testEmpty(self):
    cl = self._FakeClient()

    cl.AddQueryResult(["name", "offline", "sip"], None, [])
    self.assertEqual(cli.GetOnlineNodes(None, cl=cl), [])
    self.assertEqual(cl.CountPending(), 0)

  def testNoSpecialFilter(self):
    cl = self._FakeClient()

    cl.AddQueryResult(["name", "offline", "sip"], None, [
      [(constants.RS_NORMAL, "master.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.1")],
      [(constants.RS_NORMAL, "node2.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.2")],
      ])
    self.assertEqual(cli.GetOnlineNodes(None, cl=cl),
                     ["master.example.com", "node2.example.com"])
    self.assertEqual(cl.CountPending(), 0)

  def testNoMaster(self):
    cl = self._FakeClient()

    def _CheckFilter(qfilter):
      self.assertEqual(qfilter, [qlang.OP_NOT, [qlang.OP_TRUE, "master"]])
      return True

    cl.AddQueryResult(["name", "offline", "sip"], _CheckFilter, [
      [(constants.RS_NORMAL, "node2.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.2")],
      ])
    self.assertEqual(cli.GetOnlineNodes(None, cl=cl, filter_master=True),
                     ["node2.example.com"])
    self.assertEqual(cl.CountPending(), 0)

  def testSecondaryIpAddress(self):
    cl = self._FakeClient()

    cl.AddQueryResult(["name", "offline", "sip"], None, [
      [(constants.RS_NORMAL, "master.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.1")],
      [(constants.RS_NORMAL, "node2.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.2")],
      ])
    self.assertEqual(cli.GetOnlineNodes(None, cl=cl, secondary_ips=True),
                     ["192.0.2.1", "192.0.2.2"])
    self.assertEqual(cl.CountPending(), 0)

  def testNoMasterFilterNodeName(self):
    cl = self._FakeClient()

    def _CheckFilter(qfilter):
      self.assertEqual(qfilter,
        [qlang.OP_AND,
         [qlang.OP_OR] + [[qlang.OP_EQUAL, "name", name]
                          for name in ["node2", "node3"]],
         [qlang.OP_NOT, [qlang.OP_TRUE, "master"]]])
      return True

    cl.AddQueryResult(["name", "offline", "sip"], _CheckFilter, [
      [(constants.RS_NORMAL, "node2.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.12")],
      [(constants.RS_NORMAL, "node3.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.13")],
      ])
    self.assertEqual(cli.GetOnlineNodes(["node2", "node3"], cl=cl,
                                        secondary_ips=True, filter_master=True),
                     ["192.0.2.12", "192.0.2.13"])
    self.assertEqual(cl.CountPending(), 0)

  def testOfflineNodes(self):
    cl = self._FakeClient()

    cl.AddQueryResult(["name", "offline", "sip"], None, [
      [(constants.RS_NORMAL, "master.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.1")],
      [(constants.RS_NORMAL, "node2.example.com"),
       (constants.RS_NORMAL, True),
       (constants.RS_NORMAL, "192.0.2.2")],
      [(constants.RS_NORMAL, "node3.example.com"),
       (constants.RS_NORMAL, True),
       (constants.RS_NORMAL, "192.0.2.3")],
      ])
    self.assertEqual(cli.GetOnlineNodes(None, cl=cl, nowarn=True),
                     ["master.example.com"])
    self.assertEqual(cl.CountPending(), 0)

  def testNodeGroup(self):
    cl = self._FakeClient()

    def _CheckFilter(qfilter):
      self.assertEqual(qfilter,
        [qlang.OP_OR, [qlang.OP_EQUAL, "group", "foobar"],
                      [qlang.OP_EQUAL, "group.uuid", "foobar"]])
      return True

    cl.AddQueryResult(["name", "offline", "sip"], _CheckFilter, [
      [(constants.RS_NORMAL, "master.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.1")],
      [(constants.RS_NORMAL, "node3.example.com"),
       (constants.RS_NORMAL, False),
       (constants.RS_NORMAL, "192.0.2.3")],
      ])
    self.assertEqual(cli.GetOnlineNodes(None, cl=cl, nodegroup="foobar"),
                     ["master.example.com", "node3.example.com"])
    self.assertEqual(cl.CountPending(), 0)


class TestFormatTimestamp(unittest.TestCase):
  def testGood(self):
    self.assertEqual(cli.FormatTimestamp((0, 1)),
                     time.strftime("%F %T", time.localtime(0)) + ".000001")
    self.assertEqual(cli.FormatTimestamp((1332944009, 17376)),
                     (time.strftime("%F %T", time.localtime(1332944009)) +
                      ".017376"))

  def testWrong(self):
    for i in [0, [], {}, "", [1]]:
      self.assertEqual(cli.FormatTimestamp(i), "?")


class TestFormatUsage(unittest.TestCase):
  def test(self):
    binary = "gnt-unittest"
    commands = {
      "cmdA":
        (NotImplemented, NotImplemented, NotImplemented, NotImplemented,
         "description of A"),
      "bbb":
        (NotImplemented, NotImplemented, NotImplemented, NotImplemented,
         "Hello World," * 10),
      "longname":
        (NotImplemented, NotImplemented, NotImplemented, NotImplemented,
         "Another description"),
      }

    self.assertEqual(list(cli._FormatUsage(binary, commands)), [
      "Usage: gnt-unittest {command} [options...] [argument...]",
      "gnt-unittest <command> --help to see details, or man gnt-unittest",
      "",
      "Commands:",
      (" bbb      - Hello World,Hello World,Hello World,Hello World,Hello"
       " World,Hello"),
      "            World,Hello World,Hello World,Hello World,Hello World,",
      " cmdA     - description of A",
      " longname - Another description",
      "",
      ])


class TestParseArgs(unittest.TestCase):
  def testNoArguments(self):
    for argv in [[], ["gnt-unittest"]]:
      try:
        cli._ParseArgs("gnt-unittest", argv, {}, {}, set())
      except cli._ShowUsage as err:
        self.assertTrue(err.exit_error)
      else:
        self.fail("Did not raise exception")

  def testVersion(self):
    for argv in [["test", "--version"], ["test", "--version", "somethingelse"]]:
      try:
        cli._ParseArgs("test", argv, {}, {}, set())
      except cli._ShowVersion:
        pass
      else:
        self.fail("Did not raise exception")

  def testHelp(self):
    for argv in [["test", "--help"], ["test", "--help", "somethingelse"]]:
      try:
        cli._ParseArgs("test", argv, {}, {}, set())
      except cli._ShowUsage as err:
        self.assertFalse(err.exit_error)
      else:
        self.fail("Did not raise exception")

  def testUnknownCommandOrAlias(self):
    for argv in [["test", "list"], ["test", "somethingelse", "--help"]]:
      try:
        cli._ParseArgs("test", argv, {}, {}, set())
      except cli._ShowUsage as err:
        self.assertTrue(err.exit_error)
      else:
        self.fail("Did not raise exception")

  def testInvalidAliasList(self):
    cmd = {
      "list": NotImplemented,
      "foo": NotImplemented,
      }
    aliases = {
      "list": NotImplemented,
      "foo": NotImplemented,
      }
    assert sorted(cmd.keys()) == sorted(aliases.keys())
    self.assertRaises(AssertionError, cli._ParseArgs, "test",
                      ["test", "list"], cmd, aliases, set())

  def testAliasForNonExistantCommand(self):
    cmd = {}
    aliases = {
      "list": NotImplemented,
      }
    self.assertRaises(errors.ProgrammerError, cli._ParseArgs, "test",
                      ["test", "list"], cmd, aliases, set())


class TestQftNames(unittest.TestCase):
  def testComplete(self):
    self.assertEqual(frozenset(cli._QFT_NAMES), constants.QFT_ALL)

  def testUnique(self):
    lcnames = [s.lower() for s in cli._QFT_NAMES.values()]
    self.assertFalse(utils.FindDuplicates(lcnames))

  def testUppercase(self):
    for name in cli._QFT_NAMES.values():
      self.assertEqual(name[0], name[0].upper())


class TestFieldDescValues(unittest.TestCase):
  def testKnownKind(self):
    fdef = objects.QueryFieldDefinition(name="aname",
                                        title="Atitle",
                                        kind=constants.QFT_TEXT,
                                        doc="aaa doc aaa")
    self.assertEqual(cli._FieldDescValues(fdef),
                     ["aname", "Text", "Atitle", "aaa doc aaa"])

  def testUnknownKind(self):
    kind = "#foo#"

    self.assertFalse(kind in constants.QFT_ALL)
    self.assertFalse(kind in cli._QFT_NAMES)

    fdef = objects.QueryFieldDefinition(name="zname", title="Ztitle",
                                        kind=kind, doc="zzz doc zzz")
    self.assertEqual(cli._FieldDescValues(fdef),
                     ["zname", kind, "Ztitle", "zzz doc zzz"])


class TestSerializeGenericInfo(unittest.TestCase):
  """Test case for cli._SerializeGenericInfo"""
  def _RunTest(self, data, expected):
    buf = StringIO()
    cli._SerializeGenericInfo(buf, data, 0)
    self.assertEqual(buf.getvalue(), expected)

  def testSimple(self):
    test_samples = [
      ("abc", "abc\n"),
      ([], "\n"),
      ({}, "\n"),
      (["1", "2", "3"], "- 1\n- 2\n- 3\n"),
      ([("z", "26")], "z: 26\n"),
      ({"z": "26"}, "z: 26\n"),
      ([("z", "26"), ("a", "1")], "z: 26\na: 1\n"),
      ({"z": "26", "a": "1"}, "a: 1\nz: 26\n"),
      ]
    for (data, expected) in test_samples:
      self._RunTest(data, expected)

  def testLists(self):
    adict = {
      "aa": "11",
      "bb": "22",
      "cc": "33",
      }
    adict_exp = ("- aa: 11\n"
                 "  bb: 22\n"
                 "  cc: 33\n")
    anobj = [
      ("zz", "11"),
      ("ww", "33"),
      ("xx", "22"),
      ]
    anobj_exp = ("- zz: 11\n"
                 "  ww: 33\n"
                 "  xx: 22\n")
    alist = ["aa", "cc", "bb"]
    alist_exp = ("- - aa\n"
                 "  - cc\n"
                 "  - bb\n")
    test_samples = [
      (adict, adict_exp),
      (anobj, anobj_exp),
      (alist, alist_exp),
      ]
    for (base_data, base_expected) in test_samples:
      for k in range(1, 4):
        data = k * [base_data]
        expected = k * base_expected
        self._RunTest(data, expected)

  def testDictionaries(self):
    data = [
      ("aaa", ["x", "y"]),
      ("bbb", {
          "w": "1",
          "z": "2",
          }),
      ("ccc", [
          ("xyz", "123"),
          ("efg", "456"),
          ]),
      ]
    expected = ("aaa: \n"
                "  - x\n"
                "  - y\n"
                "bbb: \n"
                "  w: 1\n"
                "  z: 2\n"
                "ccc: \n"
                "  xyz: 123\n"
                "  efg: 456\n")
    self._RunTest(data, expected)
    self._RunTest(dict(data), expected)


class TestFormatPolicyInfo(unittest.TestCase):
  """Test case for cli.FormatPolicyInfo.

  These tests rely on cli._SerializeGenericInfo (tested elsewhere).

  """
  def setUp(self):
    # Policies are big, and we want to see the difference in case of an error
    self.maxDiff = None

  def _RenameDictItem(self, parsed, old, new):
    self.assertTrue(old in parsed)
    self.assertTrue(new not in parsed)
    parsed[new] = parsed[old]
    del parsed[old]

  def _TranslateParsedNames(self, parsed):
    for (pretty, raw) in [
      ("bounds specs", constants.ISPECS_MINMAX),
      ("allowed disk templates", constants.IPOLICY_DTS)
      ]:
      self._RenameDictItem(parsed, pretty, raw)
    for minmax in parsed[constants.ISPECS_MINMAX]:
      for key in minmax:
        keyparts = key.split("/", 1)
        if len(keyparts) > 1:
          self._RenameDictItem(minmax, key, keyparts[0])
    self.assertTrue(constants.IPOLICY_DTS in parsed)
    parsed[constants.IPOLICY_DTS] = yaml.load("[%s]" %
                                              parsed[constants.IPOLICY_DTS])

  @staticmethod
  def _PrintAndParsePolicy(custom, effective, iscluster):
    formatted = cli.FormatPolicyInfo(custom, effective, iscluster)
    buf = StringIO()
    cli._SerializeGenericInfo(buf, formatted, 0)
    return yaml.load(buf.getvalue())

  def _PrintAndCheckParsed(self, policy):
    parsed = self._PrintAndParsePolicy(policy, NotImplemented, True)
    self._TranslateParsedNames(parsed)
    self.assertEqual(parsed, policy)

  def _CompareClusterGroupItems(self, cluster, group, skip=None):
    if isinstance(group, dict):
      self.assertTrue(isinstance(cluster, dict))
      if skip is None:
        skip = frozenset()
      self.assertEqual(frozenset(cluster).difference(skip),
                       frozenset(group))
      for key in group:
        self._CompareClusterGroupItems(cluster[key], group[key])
    elif isinstance(group, list):
      self.assertTrue(isinstance(cluster, list))
      self.assertEqual(len(cluster), len(group))
      for (cval, gval) in zip(cluster, group):
        self._CompareClusterGroupItems(cval, gval)
    else:
      self.assertTrue(isinstance(group, str))
      self.assertEqual("default (%s)" % cluster, group)

  def _TestClusterVsGroup(self, policy):
    cluster = self._PrintAndParsePolicy(policy, NotImplemented, True)
    group = self._PrintAndParsePolicy({}, policy, False)
    self._CompareClusterGroupItems(cluster, group, ["std"])

  def testWithDefaults(self):
    self._PrintAndCheckParsed(constants.IPOLICY_DEFAULTS)
    self._TestClusterVsGroup(constants.IPOLICY_DEFAULTS)


class TestCreateIPolicyFromOpts(unittest.TestCase):
  """Test case for cli.CreateIPolicyFromOpts."""
  def setUp(self):
    # Policies are big, and we want to see the difference in case of an error
    self.maxDiff = None

  def _RecursiveCheckMergedDicts(self, default_pol, diff_pol, merged_pol,
                                 merge_minmax=False):
    self.assertTrue(type(default_pol) is dict)
    self.assertTrue(type(diff_pol) is dict)
    self.assertTrue(type(merged_pol) is dict)
    self.assertEqual(frozenset(default_pol),
                     frozenset(merged_pol))
    for (key, val) in merged_pol.items():
      if key in diff_pol:
        if type(val) is dict:
          self._RecursiveCheckMergedDicts(default_pol[key], diff_pol[key], val)
        elif (merge_minmax and key == "minmax" and type(val) is list and
              len(val) == 1):
          self.assertEqual(len(default_pol[key]), 1)
          self.assertEqual(len(diff_pol[key]), 1)
          self._RecursiveCheckMergedDicts(default_pol[key][0],
                                          diff_pol[key][0], val[0])
        else:
          self.assertEqual(val, diff_pol[key])
      else:
        self.assertEqual(val, default_pol[key])

  def testClusterPolicy(self):
    pol0 = cli.CreateIPolicyFromOpts(
      ispecs_mem_size={},
      ispecs_cpu_count={},
      ispecs_disk_count={},
      ispecs_disk_size={},
      ispecs_nic_count={},
      ipolicy_disk_templates=None,
      ipolicy_vcpu_ratio=None,
      ipolicy_spindle_ratio=None,
      fill_all=True
      )
    self.assertEqual(pol0, constants.IPOLICY_DEFAULTS)

    exp_pol1 = {
      constants.ISPECS_MINMAX: [
        {
          constants.ISPECS_MIN: {
            constants.ISPEC_CPU_COUNT: 2,
            constants.ISPEC_DISK_COUNT: 1,
            },
          constants.ISPECS_MAX: {
            constants.ISPEC_MEM_SIZE: 12*1024,
            constants.ISPEC_DISK_COUNT: 2,
            },
          },
        ],
      constants.ISPECS_STD: {
        constants.ISPEC_CPU_COUNT: 2,
        constants.ISPEC_DISK_COUNT: 2,
        },
      constants.IPOLICY_VCPU_RATIO: 3.1,
      }
    pol1 = cli.CreateIPolicyFromOpts(
      ispecs_mem_size={"max": "12g"},
      ispecs_cpu_count={"min": 2, "std": 2},
      ispecs_disk_count={"min": 1, "max": 2, "std": 2},
      ispecs_disk_size={},
      ispecs_nic_count={},
      ipolicy_disk_templates=None,
      ipolicy_vcpu_ratio=3.1,
      ipolicy_spindle_ratio=None,
      fill_all=True
      )
    self._RecursiveCheckMergedDicts(constants.IPOLICY_DEFAULTS,
                                    exp_pol1, pol1, merge_minmax=True)

    exp_pol2 = {
      constants.ISPECS_MINMAX: [
        {
          constants.ISPECS_MIN: {
            constants.ISPEC_DISK_SIZE: 512,
            constants.ISPEC_NIC_COUNT: 2,
            },
          constants.ISPECS_MAX: {
            constants.ISPEC_NIC_COUNT: 3,
            },
          },
        ],
      constants.ISPECS_STD: {
        constants.ISPEC_CPU_COUNT: 2,
        constants.ISPEC_NIC_COUNT: 3,
        },
      constants.IPOLICY_SPINDLE_RATIO: 1.3,
      constants.IPOLICY_DTS: ["templates"],
      }
    pol2 = cli.CreateIPolicyFromOpts(
      ispecs_mem_size={},
      ispecs_cpu_count={"std": 2},
      ispecs_disk_count={},
      ispecs_disk_size={"min": "0.5g"},
      ispecs_nic_count={"min": 2, "max": 3, "std": 3},
      ipolicy_disk_templates=["templates"],
      ipolicy_vcpu_ratio=None,
      ipolicy_spindle_ratio=1.3,
      fill_all=True
      )
    self._RecursiveCheckMergedDicts(constants.IPOLICY_DEFAULTS,
                                      exp_pol2, pol2, merge_minmax=True)

    for fill_all in [False, True]:
      exp_pol3 = {
        constants.ISPECS_STD: {
          constants.ISPEC_CPU_COUNT: 2,
          constants.ISPEC_NIC_COUNT: 3,
          },
        }
      pol3 = cli.CreateIPolicyFromOpts(
        std_ispecs={
          constants.ISPEC_CPU_COUNT: "2",
          constants.ISPEC_NIC_COUNT: "3",
          },
        ipolicy_disk_templates=None,
        ipolicy_vcpu_ratio=None,
        ipolicy_spindle_ratio=None,
        fill_all=fill_all
        )
      if fill_all:
        self._RecursiveCheckMergedDicts(constants.IPOLICY_DEFAULTS,
                                        exp_pol3, pol3, merge_minmax=True)
      else:
        self.assertEqual(pol3, exp_pol3)

  def testPartialPolicy(self):
    exp_pol0 = objects.MakeEmptyIPolicy()
    pol0 = cli.CreateIPolicyFromOpts(
      minmax_ispecs=None,
      std_ispecs=None,
      ipolicy_disk_templates=None,
      ipolicy_vcpu_ratio=None,
      ipolicy_spindle_ratio=None,
      fill_all=False
      )
    self.assertEqual(pol0, exp_pol0)

    exp_pol1 = {
      constants.IPOLICY_VCPU_RATIO: 3.1,
      }
    pol1 = cli.CreateIPolicyFromOpts(
      minmax_ispecs=None,
      std_ispecs=None,
      ipolicy_disk_templates=None,
      ipolicy_vcpu_ratio=3.1,
      ipolicy_spindle_ratio=None,
      fill_all=False
      )
    self.assertEqual(pol1, exp_pol1)

    exp_pol2 = {
      constants.IPOLICY_SPINDLE_RATIO: 1.3,
      constants.IPOLICY_DTS: ["templates"],
      }
    pol2 = cli.CreateIPolicyFromOpts(
      minmax_ispecs=None,
      std_ispecs=None,
      ipolicy_disk_templates=["templates"],
      ipolicy_vcpu_ratio=None,
      ipolicy_spindle_ratio=1.3,
      fill_all=False
      )
    self.assertEqual(pol2, exp_pol2)

  def _TestInvalidISpecs(self, minmax_ispecs, std_ispecs, fail=True):
    for fill_all in [False, True]:
      if fail:
        self.assertRaises((errors.OpPrereqError,
                           errors.UnitParseError,
                           errors.TypeEnforcementError),
                          cli.CreateIPolicyFromOpts,
                          minmax_ispecs=minmax_ispecs,
                          std_ispecs=std_ispecs,
                          fill_all=fill_all)
      else:
        cli.CreateIPolicyFromOpts(minmax_ispecs=minmax_ispecs,
                                  std_ispecs=std_ispecs,
                                  fill_all=fill_all)

  def testInvalidPolicies(self):
    self.assertRaises(AssertionError, cli.CreateIPolicyFromOpts,
                      std_ispecs={constants.ISPEC_MEM_SIZE: 1024},
                      ipolicy_disk_templates=None, ipolicy_vcpu_ratio=None,
                      ipolicy_spindle_ratio=None, group_ipolicy=True)
    self.assertRaises(errors.OpPrereqError, cli.CreateIPolicyFromOpts,
                      ispecs_mem_size={"wrong": "x"}, ispecs_cpu_count={},
                      ispecs_disk_count={}, ispecs_disk_size={},
                      ispecs_nic_count={}, ipolicy_disk_templates=None,
                      ipolicy_vcpu_ratio=None, ipolicy_spindle_ratio=None,
                      fill_all=True)
    self.assertRaises(errors.TypeEnforcementError, cli.CreateIPolicyFromOpts,
                      ispecs_mem_size={}, ispecs_cpu_count={"min": "default"},
                      ispecs_disk_count={}, ispecs_disk_size={},
                      ispecs_nic_count={}, ipolicy_disk_templates=None,
                      ipolicy_vcpu_ratio=None, ipolicy_spindle_ratio=None,
                      fill_all=True)

    good_mmspecs = [
      constants.ISPECS_MINMAX_DEFAULTS,
      constants.ISPECS_MINMAX_DEFAULTS,
      ]
    self._TestInvalidISpecs(good_mmspecs, None, fail=False)
    broken_mmspecs = copy.deepcopy(good_mmspecs)
    for minmaxpair in broken_mmspecs:
      for key in constants.ISPECS_MINMAX_KEYS:
        for par in constants.ISPECS_PARAMETERS:
          old = minmaxpair[key][par]
          del minmaxpair[key][par]
          self._TestInvalidISpecs(broken_mmspecs, None)
          minmaxpair[key][par] = "invalid"
          self._TestInvalidISpecs(broken_mmspecs, None)
          minmaxpair[key][par] = old
        minmaxpair[key]["invalid_key"] = None
        self._TestInvalidISpecs(broken_mmspecs, None)
        del minmaxpair[key]["invalid_key"]
      minmaxpair["invalid_key"] = None
      self._TestInvalidISpecs(broken_mmspecs, None)
      del minmaxpair["invalid_key"]
      assert broken_mmspecs == good_mmspecs

    good_stdspecs = constants.IPOLICY_DEFAULTS[constants.ISPECS_STD]
    self._TestInvalidISpecs(None, good_stdspecs, fail=False)
    broken_stdspecs = copy.deepcopy(good_stdspecs)
    for par in constants.ISPECS_PARAMETERS:
      old = broken_stdspecs[par]
      broken_stdspecs[par] = "invalid"
      self._TestInvalidISpecs(None, broken_stdspecs)
      broken_stdspecs[par] = old
    broken_stdspecs["invalid_key"] = None
    self._TestInvalidISpecs(None, broken_stdspecs)
    del broken_stdspecs["invalid_key"]
    assert broken_stdspecs == good_stdspecs

  def testAllowedValues(self):
    allowedv = "blah"
    exp_pol1 = {
      constants.ISPECS_MINMAX: allowedv,
      constants.IPOLICY_DTS: allowedv,
      constants.IPOLICY_VCPU_RATIO: allowedv,
      constants.IPOLICY_SPINDLE_RATIO: allowedv,
      }
    pol1 = cli.CreateIPolicyFromOpts(minmax_ispecs=[{allowedv: {}}],
                                     std_ispecs=None,
                                     ipolicy_disk_templates=allowedv,
                                     ipolicy_vcpu_ratio=allowedv,
                                     ipolicy_spindle_ratio=allowedv,
                                     allowed_values=[allowedv])
    self.assertEqual(pol1, exp_pol1)

  @staticmethod
  def _ConvertSpecToStrings(spec):
    ret = {}
    for (par, val) in spec.items():
      ret[par] = str(val)
    return ret

  def _CheckNewStyleSpecsCall(self, exp_ipolicy, minmax_ispecs, std_ispecs,
                              group_ipolicy, fill_all):
    ipolicy = cli.CreateIPolicyFromOpts(minmax_ispecs=minmax_ispecs,
                                        std_ispecs=std_ispecs,
                                        group_ipolicy=group_ipolicy,
                                        fill_all=fill_all)
    self.assertEqual(ipolicy, exp_ipolicy)

  def _TestFullISpecsInner(self, skel_exp_ipol, exp_minmax, exp_std,
                           group_ipolicy, fill_all):
    exp_ipol = skel_exp_ipol.copy()
    if exp_minmax is not None:
      minmax_ispecs = []
      for exp_mm_pair in exp_minmax:
        mmpair = {}
        for (key, spec) in exp_mm_pair.items():
          mmpair[key] = self._ConvertSpecToStrings(spec)
        minmax_ispecs.append(mmpair)
      exp_ipol[constants.ISPECS_MINMAX] = exp_minmax
    else:
      minmax_ispecs = None
    if exp_std is not None:
      std_ispecs = self._ConvertSpecToStrings(exp_std)
      exp_ipol[constants.ISPECS_STD] = exp_std
    else:
      std_ispecs = None

    self._CheckNewStyleSpecsCall(exp_ipol, minmax_ispecs, std_ispecs,
                                 group_ipolicy, fill_all)
    if minmax_ispecs:
      for mmpair in minmax_ispecs:
        for (key, spec) in mmpair.items():
          for par in [constants.ISPEC_MEM_SIZE, constants.ISPEC_DISK_SIZE]:
            if par in spec:
              spec[par] += "m"
              self._CheckNewStyleSpecsCall(exp_ipol, minmax_ispecs, std_ispecs,
                                           group_ipolicy, fill_all)
    if std_ispecs:
      for par in [constants.ISPEC_MEM_SIZE, constants.ISPEC_DISK_SIZE]:
        if par in std_ispecs:
          std_ispecs[par] += "m"
          self._CheckNewStyleSpecsCall(exp_ipol, minmax_ispecs, std_ispecs,
                                       group_ipolicy, fill_all)

  def testFullISpecs(self):
    exp_minmax1 = [
      {
        constants.ISPECS_MIN: {
          constants.ISPEC_MEM_SIZE: 512,
          constants.ISPEC_CPU_COUNT: 2,
          constants.ISPEC_DISK_COUNT: 2,
          constants.ISPEC_DISK_SIZE: 512,
          constants.ISPEC_NIC_COUNT: 2,
          constants.ISPEC_SPINDLE_USE: 2,
          },
        constants.ISPECS_MAX: {
          constants.ISPEC_MEM_SIZE: 768*1024,
          constants.ISPEC_CPU_COUNT: 7,
          constants.ISPEC_DISK_COUNT: 6,
          constants.ISPEC_DISK_SIZE: 2048*1024,
          constants.ISPEC_NIC_COUNT: 3,
          constants.ISPEC_SPINDLE_USE: 3,
          },
        },
      ]
    exp_minmax2 = [
      {
        constants.ISPECS_MIN: {
          constants.ISPEC_MEM_SIZE: 512,
          constants.ISPEC_CPU_COUNT: 2,
          constants.ISPEC_DISK_COUNT: 2,
          constants.ISPEC_DISK_SIZE: 512,
          constants.ISPEC_NIC_COUNT: 2,
          constants.ISPEC_SPINDLE_USE: 2,
          },
        constants.ISPECS_MAX: {
          constants.ISPEC_MEM_SIZE: 768*1024,
          constants.ISPEC_CPU_COUNT: 7,
          constants.ISPEC_DISK_COUNT: 6,
          constants.ISPEC_DISK_SIZE: 2048*1024,
          constants.ISPEC_NIC_COUNT: 3,
          constants.ISPEC_SPINDLE_USE: 3,
          },
        },
      {
        constants.ISPECS_MIN: {
          constants.ISPEC_MEM_SIZE: 1024*1024,
          constants.ISPEC_CPU_COUNT: 3,
          constants.ISPEC_DISK_COUNT: 3,
          constants.ISPEC_DISK_SIZE: 256,
          constants.ISPEC_NIC_COUNT: 4,
          constants.ISPEC_SPINDLE_USE: 5,
          },
        constants.ISPECS_MAX: {
          constants.ISPEC_MEM_SIZE: 2048*1024,
          constants.ISPEC_CPU_COUNT: 5,
          constants.ISPEC_DISK_COUNT: 5,
          constants.ISPEC_DISK_SIZE: 1024*1024,
          constants.ISPEC_NIC_COUNT: 5,
          constants.ISPEC_SPINDLE_USE: 7,
          },
        },
      ]
    exp_std1 = {
      constants.ISPEC_MEM_SIZE: 768*1024,
      constants.ISPEC_CPU_COUNT: 7,
      constants.ISPEC_DISK_COUNT: 6,
      constants.ISPEC_DISK_SIZE: 2048*1024,
      constants.ISPEC_NIC_COUNT: 3,
      constants.ISPEC_SPINDLE_USE: 1,
      }
    for fill_all in [False, True]:
      if fill_all:
        skel_ipolicy = constants.IPOLICY_DEFAULTS
      else:
        skel_ipolicy = {}
      self._TestFullISpecsInner(skel_ipolicy, None, exp_std1,
                                False, fill_all)
      for exp_minmax in [exp_minmax1, exp_minmax2]:
        self._TestFullISpecsInner(skel_ipolicy, exp_minmax, exp_std1,
                                  False, fill_all)
        self._TestFullISpecsInner(skel_ipolicy, exp_minmax, None,
                                  False, fill_all)


class TestPrintIPolicyCommand(unittest.TestCase):
  """Test case for cli.PrintIPolicyCommand"""
  _SPECS1 = {
    "par1": 42,
    "par2": "xyz",
    }
  _SPECS1_STR = "par1=42,par2=xyz"
  _SPECS2 = {
    "param": 10,
    "another_param": 101,
    }
  _SPECS2_STR = "another_param=101,param=10"
  _SPECS3 = {
    "par1": 1024,
    "param": "abc",
    }
  _SPECS3_STR = "par1=1024,param=abc"

  def _CheckPrintIPolicyCommand(self, ipolicy, isgroup, expected):
    buf = StringIO()
    cli.PrintIPolicyCommand(buf, ipolicy, isgroup)
    self.assertEqual(buf.getvalue(), expected)

  def testIgnoreStdForGroup(self):
    self._CheckPrintIPolicyCommand({"std": self._SPECS1}, True, "")

  def testIgnoreEmpty(self):
    policies = [
      {},
      {"std": {}},
      {"minmax": []},
      {"minmax": [{}]},
      {"minmax": [{
        "min": {},
        "max": {},
        }]},
      {"minmax": [{
        "min": self._SPECS1,
        "max": {},
        }]},
      ]
    for pol in policies:
      self._CheckPrintIPolicyCommand(pol, False, "")

  def testFullPolicies(self):
    cases = [
      ({"std": self._SPECS1},
       " %s %s" % (cli.IPOLICY_STD_SPECS_STR, self._SPECS1_STR)),
      ({"minmax": [{
        "min": self._SPECS1,
        "max": self._SPECS2,
        }]},
       " %s min:%s/max:%s" % (cli.IPOLICY_BOUNDS_SPECS_STR,
                              self._SPECS1_STR, self._SPECS2_STR)),
      ({"minmax": [
        {
          "min": self._SPECS1,
          "max": self._SPECS2,
          },
        {
          "min": self._SPECS2,
          "max": self._SPECS3,
          },
        ]},
       " %s min:%s/max:%s//min:%s/max:%s" %
       (cli.IPOLICY_BOUNDS_SPECS_STR, self._SPECS1_STR, self._SPECS2_STR,
        self._SPECS2_STR, self._SPECS3_STR)),
      ]
    for (pol, exp) in cases:
      self._CheckPrintIPolicyCommand(pol, False, exp)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
