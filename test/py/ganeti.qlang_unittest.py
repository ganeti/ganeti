#!/usr/bin/python
#

# Copyright (C) 2010, 2011 Google Inc.
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

    qfilter = qlang.MakeSimpleFilter(field, names)
    self.assertEqual(qfilter, expected)

  def test(self):
    self._Test("name", None, None, parse_exp=[])
    self._Test("name", [], None)
    self._Test("name", ["node1.example.com"],
               ["|", ["==", "name", "node1.example.com"]])
    self._Test("xyz", ["a", "b", "c"],
               ["|",
                ["==", "xyz", "a"], ["==", "xyz", "b"], ["==", "xyz", "c"]])


class TestParseFilter(unittest.TestCase):
  def setUp(self):
    self.parser = qlang.BuildFilterParser()

  def _Test(self, qfilter, expected, expect_filter=True):
    self.assertEqual(qlang.MakeFilter([qfilter], not expect_filter), expected)
    self.assertEqual(qlang.ParseFilter(qfilter, parser=self.parser), expected)

  def test(self):
    self._Test("name==\"foobar\"", [qlang.OP_EQUAL, "name", "foobar"])
    self._Test("name=='foobar'", [qlang.OP_EQUAL, "name", "foobar"])

    # Legacy "="
    self._Test("name=\"foobar\"", [qlang.OP_EQUAL, "name", "foobar"])
    self._Test("name='foobar'", [qlang.OP_EQUAL, "name", "foobar"])

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

    self._Test("name =* '*.site'",
               [qlang.OP_REGEXP, "name", utils.DnsNameGlobPattern("*.site")])
    self._Test("field !* '*.example.*'",
               [qlang.OP_NOT, [qlang.OP_REGEXP, "field",
                               utils.DnsNameGlobPattern("*.example.*")]])

    self._Test("ctime < 1234", [qlang.OP_LT, "ctime", 1234])
    self._Test("ctime > 1234", [qlang.OP_GT, "ctime", 1234])
    self._Test("mtime <= 9999", [qlang.OP_LE, "mtime", 9999])
    self._Test("mtime >= 9999", [qlang.OP_GE, "mtime", 9999])

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

    # Invalid operators
    tests.append("name <> value")
    tests.append("name => value")
    tests.append("name =< value")

    for qfilter in tests:
      try:
        qlang.ParseFilter(qfilter, parser=self.parser)
      except errors.QueryFilterParseError, err:
        self.assertEqual(len(err.GetDetails()), 3)
      else:
        self.fail("Invalid filter '%s' did not raise exception" % qfilter)


class TestMakeFilter(unittest.TestCase):
  def testNoNames(self):
    self.assertEqual(qlang.MakeFilter([], False), None)
    self.assertEqual(qlang.MakeFilter(None, False), None)

  def testPlainNames(self):
    self.assertEqual(qlang.MakeFilter(["web1", "web2"], False),
                     [qlang.OP_OR, [qlang.OP_EQUAL, "name", "web1"],
                                   [qlang.OP_EQUAL, "name", "web2"]])

  def testPlainNamesOtherNamefield(self):
    self.assertEqual(qlang.MakeFilter(["mailA", "mailB"], False,
                                      namefield="id"),
                     [qlang.OP_OR, [qlang.OP_EQUAL, "id", "mailA"],
                                   [qlang.OP_EQUAL, "id", "mailB"]])

  def testForcedFilter(self):
    for i in [None, [], ["1", "2"], ["", "", ""], ["a", "b", "c", "d"]]:
      self.assertRaises(errors.OpPrereqError, qlang.MakeFilter, i, True)

    # Glob pattern shouldn't parse as filter
    self.assertRaises(errors.QueryFilterParseError,
                      qlang.MakeFilter, ["*.site"], True)

    # Plain name parses as boolean filter
    self.assertEqual(qlang.MakeFilter(["web1"], True), [qlang.OP_TRUE, "web1"])

  def testFilter(self):
    self.assertEqual(qlang.MakeFilter(["foo/bar"], False),
                     [qlang.OP_TRUE, "foo/bar"])
    self.assertEqual(qlang.MakeFilter(["foo=='bar'"], False),
                     [qlang.OP_EQUAL, "foo", "bar"])
    self.assertEqual(qlang.MakeFilter(["field=*'*.site'"], False),
                     [qlang.OP_REGEXP, "field",
                      utils.DnsNameGlobPattern("*.site")])

    # Plain name parses as name filter, not boolean
    for name in ["node1", "n-o-d-e", "n_o_d_e", "node1.example.com",
                 "node1.example.com."]:
      self.assertEqual(qlang.MakeFilter([name], False),
                       [qlang.OP_OR, [qlang.OP_EQUAL, "name", name]])

    # Invalid filters
    for i in ["foo==bar", "foo+=1"]:
      self.assertRaises(errors.QueryFilterParseError,
                        qlang.MakeFilter, [i], False)

  def testGlob(self):
    self.assertEqual(qlang.MakeFilter(["*.site"], False),
                     [qlang.OP_OR, [qlang.OP_REGEXP, "name",
                                    utils.DnsNameGlobPattern("*.site")]])
    self.assertEqual(qlang.MakeFilter(["web?.example"], False),
                     [qlang.OP_OR, [qlang.OP_REGEXP, "name",
                                    utils.DnsNameGlobPattern("web?.example")]])
    self.assertEqual(qlang.MakeFilter(["*.a", "*.b", "?.c"], False),
                     [qlang.OP_OR,
                      [qlang.OP_REGEXP, "name",
                       utils.DnsNameGlobPattern("*.a")],
                      [qlang.OP_REGEXP, "name",
                       utils.DnsNameGlobPattern("*.b")],
                      [qlang.OP_REGEXP, "name",
                       utils.DnsNameGlobPattern("?.c")]])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
