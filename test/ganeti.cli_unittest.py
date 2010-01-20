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


"""Script for unittesting the cli module"""

import unittest
from cStringIO import StringIO

import ganeti
import testutils

from ganeti import constants
from ganeti import cli
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
  """Thes the ToStream functions"""

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


if __name__ == '__main__':
  testutils.GanetiTestProgram()
