#!/usr/bin/python
#

# Copyright (C) 2014 Google Inc.
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
from ganeti import cli_opts
from ganeti import errors
from ganeti import utils
from ganeti import objects
from ganeti import qlang
from ganeti.errors import OpPrereqError, ParameterError


class TestSplitKeyVal(unittest.TestCase):
  """Testing case for cli_opts._SplitKeyVal"""
  DATA = "a=b,c,no_d,-e"
  RESULT = {"a": "b", "c": True, "d": False, "e": None}
  RESULT_NOPREFIX = {"a": "b", "c": {}, "no_d": {}, "-e": {}}

  def testSplitKeyVal(self):
    """Test splitting"""
    self.failUnlessEqual(cli_opts._SplitKeyVal("option", self.DATA, True),
                         self.RESULT)

  def testDuplicateParam(self):
    """Test duplicate parameters"""
    for data in ("a=1,a=2", "a,no_a"):
      self.failUnlessRaises(ParameterError, cli_opts._SplitKeyVal,
                            "option", data, True)

  def testEmptyData(self):
    """Test how we handle splitting an empty string"""
    self.failUnlessEqual(cli_opts._SplitKeyVal("option", "", True), {})


class TestIdentKeyVal(unittest.TestCase):
  """Testing case for cli_opts.check_ident_key_val"""

  def testIdentKeyVal(self):
    """Test identkeyval"""
    def cikv(value):
      return cli_opts.check_ident_key_val("option", "opt", value)

    self.assertEqual(cikv("foo:bar"), ("foo", {"bar": True}))
    self.assertEqual(cikv("foo:bar=baz"), ("foo", {"bar": "baz"}))
    self.assertEqual(cikv("bar:b=c,c=a"), ("bar", {"b": "c", "c": "a"}))
    self.assertEqual(cikv("no_bar"), ("bar", False))
    self.assertRaises(ParameterError, cikv, "no_bar:foo")
    self.assertRaises(ParameterError, cikv, "no_bar:foo=baz")
    self.assertRaises(ParameterError, cikv, "bar:foo=baz,foo=baz")
    self.assertEqual(cikv("-foo"), ("foo", None))
    self.assertRaises(ParameterError, cikv, "-foo:a=c")

    # Check negative numbers
    self.assertEqual(cikv("-1:remove"), ("-1", {
      "remove": True,
      }))
    self.assertEqual(cikv("-29447:add,size=4G"), ("-29447", {
      "add": True,
      "size": "4G",
      }))
    for i in ["-:", "-"]:
      self.assertEqual(cikv(i), ("", None))

  @staticmethod
  def _csikv(value):
    return cli_opts._SplitIdentKeyVal("opt", value, False)

  def testIdentKeyValNoPrefix(self):
    """Test identkeyval without prefixes"""
    test_cases = [
      ("foo:bar", None),
      ("foo:no_bar", None),
      ("foo:bar=baz,bar=baz", None),
      ("foo",
       ("foo", {})),
      ("foo:bar=baz",
       ("foo", {"bar": "baz"})),
      ("no_foo:-1=baz,no_op=3",
       ("no_foo", {"-1": "baz", "no_op": "3"})),
      ]
    for (arg, res) in test_cases:
      if res is None:
        self.assertRaises(ParameterError, self._csikv, arg)
      else:
        self.assertEqual(self._csikv(arg), res)


class TestMultilistIdentKeyVal(unittest.TestCase):
  """Test for cli_opts.check_multilist_ident_key_val()"""

  @staticmethod
  def _cmikv(value):
    return cli_opts.check_multilist_ident_key_val("option", "opt", value)

  def testListIdentKeyVal(self):
    test_cases = [
      ("",
       None),
      ("foo", [
        {"foo": {}}
        ]),
      ("foo:bar=baz", [
        {"foo": {"bar": "baz"}}
        ]),
      ("foo:bar=baz/foo:bat=bad",
       None),
      ("foo:abc=42/bar:def=11", [
        {"foo": {"abc": "42"},
         "bar": {"def": "11"}}
        ]),
      ("foo:abc=42/bar:def=11,ghi=07", [
        {"foo": {"abc": "42"},
         "bar": {"def": "11", "ghi": "07"}}
        ]),
      ("foo:abc=42/bar:def=11//",
       None),
      ("foo:abc=42/bar:def=11,ghi=07//foobar", [
        {"foo": {"abc": "42"},
         "bar": {"def": "11", "ghi": "07"}},
        {"foobar": {}}
        ]),
      ("foo:abc=42/bar:def=11,ghi=07//foobar:xyz=88", [
        {"foo": {"abc": "42"},
         "bar": {"def": "11", "ghi": "07"}},
        {"foobar": {"xyz": "88"}}
        ]),
      ("foo:abc=42/bar:def=11,ghi=07//foobar:xyz=88/foo:uvw=314", [
        {"foo": {"abc": "42"},
         "bar": {"def": "11", "ghi": "07"}},
        {"foobar": {"xyz": "88"},
         "foo": {"uvw": "314"}}
        ]),
      ]
    for (arg, res) in test_cases:
      if res is None:
        self.assertRaises(ParameterError, self._cmikv, arg)
      else:
        self.assertEqual(res, self._cmikv(arg))


class TestConstants(unittest.TestCase):
  def testPriority(self):
    self.assertEqual(set(cli_opts._PRIONAME_TO_VALUE.values()),
                     set(constants.OP_PRIO_SUBMIT_VALID))
    self.assertEqual(list(value for _, value in cli_opts._PRIORITY_NAMES),
                     sorted(constants.OP_PRIO_SUBMIT_VALID, reverse=True))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
