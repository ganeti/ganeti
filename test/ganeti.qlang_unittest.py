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


"""Script for testing ganeti.qlang"""

import unittest
import string

from ganeti import utils
from ganeti import errors
from ganeti import qlang
from ganeti import query

import testutils


class TestMakeSimpleFilter(unittest.TestCase):
  def _Test(self, field, names, expected, parse_exp=None):
    if parse_exp is None:
      parse_exp = names

    filter_ = qlang.MakeSimpleFilter(field, names)
    self.assertEqual(filter_, expected)

  def test(self):
    self._Test("name", None, None, parse_exp=[])
    self._Test("name", [], None)
    self._Test("name", ["node1.example.com"],
               ["|", ["=", "name", "node1.example.com"]])
    self._Test("xyz", ["a", "b", "c"],
               ["|", ["=", "xyz", "a"], ["=", "xyz", "b"], ["=", "xyz", "c"]])


class TestParseFilter(unittest.TestCase):
  def setUp(self):
    self.parser = qlang.BuildFilterParser()

  def _Test(self, filter_, expected, expect_filter=True):
    if expect_filter:
      self.assertTrue(qlang.MaybeFilter(filter_),
                      msg="'%s' was not recognized as a filter" % filter_)
    else:
      self.assertFalse(qlang.MaybeFilter(filter_),
                       msg=("'%s' should not be recognized as a filter" %
                            filter_))
    self.assertEqual(qlang.ParseFilter(filter_, parser=self.parser), expected)

  def test(self):
    self._Test("name==\"foobar\"", [qlang.OP_EQUAL, "name", "foobar"])
    self._Test("name=='foobar'", [qlang.OP_EQUAL, "name", "foobar"])

    self._Test("valA==1 and valB==2 or valC==3",
               [qlang.OP_OR,
                [qlang.OP_AND, [qlang.OP_EQUAL, "valA", 1],
                               [qlang.OP_EQUAL, "valB", 2]],
                [qlang.OP_EQUAL, "valC", 3]])

    self._Test(("(name\n==\"foobar\") and (xyz==\"va)ue\" and k == 256 or"
                " x ==\t\"y\"\n) and mc"),
               [qlang.OP_AND,
                [qlang.OP_EQUAL, "name", "foobar"],
                [qlang.OP_OR,
                 [qlang.OP_AND, [qlang.OP_EQUAL, "xyz", "va)ue"],
                                [qlang.OP_EQUAL, "k", 256]],
                 [qlang.OP_EQUAL, "x", "y"]],
                [qlang.OP_TRUE, "mc"]])

    self._Test("(xyz==\"v\" or k == 256 and x == \"y\")",
               [qlang.OP_OR,
                [qlang.OP_EQUAL, "xyz", "v"],
                [qlang.OP_AND, [qlang.OP_EQUAL, "k", 256],
                               [qlang.OP_EQUAL, "x", "y"]]])

    self._Test("valA==1 and valB==2 and valC==3",
               [qlang.OP_AND, [qlang.OP_EQUAL, "valA", 1],
                              [qlang.OP_EQUAL, "valB", 2],
                              [qlang.OP_EQUAL, "valC", 3]])
    self._Test("master or field",
               [qlang.OP_OR, [qlang.OP_TRUE, "master"],
                             [qlang.OP_TRUE, "field"]])
    self._Test("mem == 128", [qlang.OP_EQUAL, "mem", 128])
    self._Test("negfield != -1", [qlang.OP_NOT_EQUAL, "negfield", -1])
    self._Test("master", [qlang.OP_TRUE, "master"],
               expect_filter=False)
    self._Test("not master", [qlang.OP_NOT, [qlang.OP_TRUE, "master"]])
    for op in ["not", "and", "or"]:
      self._Test("%sxyz" % op, [qlang.OP_TRUE, "%sxyz" % op],
                 expect_filter=False)
      self._Test("not %sxyz" % op,
                 [qlang.OP_NOT, [qlang.OP_TRUE, "%sxyz" % op]])
      self._Test("  not \t%sfoo" % op,
                 [qlang.OP_NOT, [qlang.OP_TRUE, "%sfoo" % op]])
      self._Test("%sname =~ m/abc/" % op,
                 [qlang.OP_REGEXP, "%sname" % op, "abc"])
    self._Test("master and not other",
               [qlang.OP_AND, [qlang.OP_TRUE, "master"],
                              [qlang.OP_NOT, [qlang.OP_TRUE, "other"]]])
    self._Test("not (master or other == 4)",
               [qlang.OP_NOT,
                [qlang.OP_OR, [qlang.OP_TRUE, "master"],
                              [qlang.OP_EQUAL, "other", 4]]])
    self._Test("some==\"val\\\"ue\"", [qlang.OP_EQUAL, "some", "val\\\"ue"])
    self._Test("123 in ips", [qlang.OP_CONTAINS, "ips", 123])
    self._Test("99 not in ips", [qlang.OP_NOT, [qlang.OP_CONTAINS, "ips", 99]])
    self._Test("\"a\" in valA and \"b\" not in valB",
               [qlang.OP_AND, [qlang.OP_CONTAINS, "valA", "a"],
                              [qlang.OP_NOT, [qlang.OP_CONTAINS, "valB", "b"]]])

    self._Test("name =~ m/test/", [qlang.OP_REGEXP, "name", "test"])
    self._Test("name =~ m/^node.*example.com$/i",
               [qlang.OP_REGEXP, "name", "(?i)^node.*example.com$"])
    self._Test("(name =~ m/^node.*example.com$/s and master) or pip =~ |^3.*|",
               [qlang.OP_OR,
                [qlang.OP_AND,
                 [qlang.OP_REGEXP, "name", "(?s)^node.*example.com$"],
                 [qlang.OP_TRUE, "master"]],
                [qlang.OP_REGEXP, "pip", "^3.*"]])
    for flags in ["si", "is", "ssss", "iiiisiii"]:
      self._Test("name =~ m/gi/%s" % flags,
                 [qlang.OP_REGEXP, "name", "(?%s)gi" % "".join(sorted(flags))])

    for i in qlang._KNOWN_REGEXP_DELIM:
      self._Test("name =~ m%stest%s" % (i, i),
                 [qlang.OP_REGEXP, "name", "test"])
      self._Test("name !~ m%stest%s" % (i, i),
                 [qlang.OP_NOT, [qlang.OP_REGEXP, "name", "test"]])
      self._Test("not\tname =~ m%stest%s" % (i, i),
                 [qlang.OP_NOT, [qlang.OP_REGEXP, "name", "test"]])
      self._Test("notname =~ m%stest%s" % (i, i),
                 [qlang.OP_REGEXP, "notname", "test"])

  def testAllFields(self):
    for name in frozenset(i for d in query.ALL_FIELD_LISTS for i in d.keys()):
      self._Test("%s == \"value\"" % name, [qlang.OP_EQUAL, name, "value"])

  def testError(self):
    # Invalid field names, meaning no boolean check is done
    tests = ["#invalid!filter#", "m/x/,"]

    # Unknown regexp flag
    tests.append("name=~m#a#g")

    # Incomplete regexp group
    tests.append("name=~^[^")

    # Valid flag, but in uppercase
    tests.append("asdf =~ m|abc|I")

    # Non-matching regexp delimiters
    tests.append("name =~ /foobarbaz#")

    for filter_ in tests:
      try:
        qlang.ParseFilter(filter_, parser=self.parser)
      except errors.QueryFilterParseError, err:
        self.assertEqual(len(err.GetDetails()), 3)
      else:
        self.fail("Invalid filter '%s' did not raise exception" % filter_)


class TestMaybeFilter(unittest.TestCase):
  def test(self):
    self.assertTrue(qlang.MaybeFilter(""))
    self.assertTrue(qlang.MaybeFilter("foo/bar"))
    self.assertTrue(qlang.MaybeFilter("foo==bar"))

    for i in set("()!~" + string.whitespace) | qlang.FILTER_DETECTION_CHARS:
      self.assertTrue(qlang.MaybeFilter(i),
                      msg="%r not recognized as filter" % i)

    self.assertFalse(qlang.MaybeFilter("node1"))
    self.assertFalse(qlang.MaybeFilter("n-o-d-e"))
    self.assertFalse(qlang.MaybeFilter("n_o_d_e"))
    self.assertFalse(qlang.MaybeFilter("node1.example.com"))
    self.assertFalse(qlang.MaybeFilter("node1.example.com."))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
