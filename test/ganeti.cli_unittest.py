#!/usr/bin/python
#

# Copyright (C) 2008, 2011 Google Inc.
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


"""Script for unittesting the cli module"""

import unittest
from cStringIO import StringIO

import ganeti
import testutils

from ganeti import constants
from ganeti import cli
from ganeti import errors
from ganeti import utils
from ganeti import objects
from ganeti.errors import OpPrereqError, ParameterError


class TestParseTimespec(unittest.TestCase):
  """Testing case for ParseTimespec"""

  def testValidTimes(self):
    """Test valid timespecs"""
    test_data = [
      ('1s', 1),
      ('1', 1),
      ('1m', 60),
      ('1h', 60 * 60),
      ('1d', 60 * 60 * 24),
      ('1w', 60 * 60 * 24 * 7),
      ('4h', 4 * 60 * 60),
      ('61m', 61 * 60),
      ]
    for value, expected_result in test_data:
      self.failUnlessEqual(cli.ParseTimespec(value), expected_result)

  def testInvalidTime(self):
    """Test invalid timespecs"""
    test_data = [
      '1y',
      '',
      'aaa',
      's',
      ]
    for value in test_data:
      self.failUnlessRaises(OpPrereqError, cli.ParseTimespec, value)


class TestSplitKeyVal(unittest.TestCase):
  """Testing case for cli._SplitKeyVal"""
  DATA = "a=b,c,no_d,-e"
  RESULT = {"a": "b", "c": True, "d": False, "e": None}

  def testSplitKeyVal(self):
    """Test splitting"""
    self.failUnlessEqual(cli._SplitKeyVal("option", self.DATA), self.RESULT)

  def testDuplicateParam(self):
    """Test duplicate parameters"""
    for data in ("a=1,a=2", "a,no_a"):
      self.failUnlessRaises(ParameterError, cli._SplitKeyVal,
                            "option", data)

  def testEmptyData(self):
    """Test how we handle splitting an empty string"""
    self.failUnlessEqual(cli._SplitKeyVal("option", ""), {})

class TestIdentKeyVal(unittest.TestCase):
  """Testing case for cli.check_ident_key_val"""

  def testIdentKeyVal(self):
    """Test identkeyval"""
    def cikv(value):
      return cli.check_ident_key_val("option", "opt", value)

    self.assertEqual(cikv("foo:bar"), ("foo", {"bar": True}))
    self.assertEqual(cikv("foo:bar=baz"), ("foo", {"bar": "baz"}))
    self.assertEqual(cikv("bar:b=c,c=a"), ("bar", {"b": "c", "c": "a"}))
    self.assertEqual(cikv("no_bar"), ("bar", False))
    self.assertRaises(ParameterError, cikv, "no_bar:foo")
    self.assertRaises(ParameterError, cikv, "no_bar:foo=baz")
    self.assertEqual(cikv("-foo"), ("foo", None))
    self.assertRaises(ParameterError, cikv, "-foo:a=c")


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
      self.failUnlessEqual(buf.getvalue(), data+'\n')

  def testParams(self):
      buf = StringIO()
      cli._ToStream(buf, "foo %s", 1)
      self.failUnlessEqual(buf.getvalue(), "foo 1\n")
      buf = StringIO()
      cli._ToStream(buf, "foo %s", (15,16))
      self.failUnlessEqual(buf.getvalue(), "foo (15, 16)\n")
      buf = StringIO()
      cli._ToStream(buf, "foo %s %s", "a", "b")
      self.failUnlessEqual(buf.getvalue(), "foo a b\n")


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
                           prev_job_info, prev_log_serial):
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

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    self.tc.assertEqual(job_id, self.job_id)
    self.tc.assertEqualValues((serial, timestamp, log_type, log_msg),
                              self._expect_log.pop(0))

  def ReportNotChanged(self, job_id, status):
    self.tc.assertEqual(job_id, self.job_id)
    self.tc.assert_(self._expect_notchanged)
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
    self.assertRaises(errors.OpExecError, cli.GenericPollJob, job_id, cbs, cbs)
    cbs.CheckEmpty()


class TestFormatLogMessage(unittest.TestCase):
  def test(self):
    self.assertEqual(cli.FormatLogMessage(constants.ELOG_MESSAGE,
                                          "Hello World"),
                     "Hello World")
    self.assertRaises(TypeError, cli.FormatLogMessage,
                      constants.ELOG_MESSAGE, [1, 2, 3])

    self.assert_(cli.FormatLogMessage("some other type", (1, 2, 3)))


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


class TestConstants(unittest.TestCase):
  def testPriority(self):
    self.assertEqual(set(cli._PRIONAME_TO_VALUE.values()),
                     set(constants.OP_PRIO_SUBMIT_VALID))
    self.assertEqual(list(value for _, value in cli._PRIORITY_NAMES),
                     sorted(constants.OP_PRIO_SUBMIT_VALID, reverse=True))


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


if __name__ == '__main__':
  testutils.GanetiTestProgram()
