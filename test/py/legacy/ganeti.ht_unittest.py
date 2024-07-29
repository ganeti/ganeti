#!/usr/bin/python3
#

# Copyright (C) 2011, 2012 Google Inc.
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


"""Script for testing ganeti.ht"""

import unittest

from ganeti import constants
from ganeti import ht

import testutils


class TestTypeChecks(unittest.TestCase):
  def testNone(self):
    self.assertFalse(ht.TNotNone(None))
    self.assertTrue(ht.TNone(None))

    for val in [0, True, "", "Hello World", [], range(5)]:
      self.assertTrue(ht.TNotNone(val))
      self.assertFalse(ht.TNone(val))

  def testBool(self):
    self.assertTrue(ht.TBool(True))
    self.assertTrue(ht.TBool(False))

    for val in [0, None, "", [], "Hello"]:
      self.assertFalse(ht.TBool(val))

    for val in [True, -449, 1, 3, "x", "abc", [1, 2]]:
      self.assertTrue(ht.TTrue(val))

    for val in [False, 0, None, []]:
      self.assertFalse(ht.TTrue(val))

  def testInt(self):
    for val in [-100, -3, 0, 16, 128, 923874]:
      self.assertTrue(ht.TInt(val))
      self.assertTrue(ht.TNumber(val))

    for val in [False, True, None, "", [], "Hello", 0.0, 0.23, -3818.163]:
      self.assertFalse(ht.TInt(val))

    for val in range(0, 100, 4):
      self.assertTrue(ht.TNonNegativeInt(val))
      neg = -(val + 1)
      self.assertFalse(ht.TNonNegativeInt(neg))
      self.assertFalse(ht.TPositiveInt(neg))

      self.assertFalse(ht.TNonNegativeInt(0.1 + val))
      self.assertFalse(ht.TPositiveInt(0.1 + val))

    for val in [0, 0.1, 0.9, -0.3]:
      self.assertFalse(ht.TPositiveInt(val))

    for val in range(1, 100, 4):
      self.assertTrue(ht.TPositiveInt(val))
      self.assertFalse(ht.TPositiveInt(0.1 + val))

  def testFloat(self):
    for val in [-100.21, -3.0, 0.0, 16.12, 128.3433, 923874.928]:
      self.assertTrue(ht.TFloat(val))
      self.assertTrue(ht.TNumber(val))

    for val in [False, True, None, "", [], "Hello", 0, 28, -1, -3281]:
      self.assertFalse(ht.TFloat(val))

  def testNumber(self):
    for val in [-100, -3, 0, 16, 128, 923874,
                -100.21, -3.0, 0.0, 16.12, 128.3433, 923874.928]:
      self.assertTrue(ht.TNumber(val))

    for val in [False, True, None, "", [], "Hello", "1"]:
      self.assertFalse(ht.TNumber(val))

  def testString(self):
    for val in ["", "abc", "Hello World", "123",
                "", "\u272C", "abc"]:
      self.assertTrue(ht.TString(val))

    for val in [False, True, None, [], 0, 1, 5, -193, 93.8582]:
      self.assertFalse(ht.TString(val))

  def testElemOf(self):
    fn = ht.TElemOf(range(10))
    self.assertTrue(fn(0))
    self.assertTrue(fn(3))
    self.assertTrue(fn(9))
    self.assertFalse(fn(-1))
    self.assertFalse(fn(100))

    fn = ht.TElemOf([])
    self.assertFalse(fn(0))
    self.assertFalse(fn(100))
    self.assertFalse(fn(True))

    fn = ht.TElemOf(["Hello", "World"])
    self.assertTrue(fn("Hello"))
    self.assertTrue(fn("World"))
    self.assertFalse(fn("e"))

  def testList(self):
    for val in [[], list(range(10)), ["Hello", "World", "!"]]:
      self.assertTrue(ht.TList(val))

    for val in [False, True, None, {}, 0, 1, 5, -193, 93.8582]:
      self.assertFalse(ht.TList(val))

  def testDict(self):
    for val in [{}, dict.fromkeys(range(10)), {"Hello": [], "World": "!"}]:
      self.assertTrue(ht.TDict(val))

    for val in [False, True, None, [], 0, 1, 5, -193, 93.8582]:
      self.assertFalse(ht.TDict(val))

  def testIsLength(self):
    fn = ht.TIsLength(10)
    self.assertTrue(fn(range(10)))
    self.assertFalse(fn(range(1)))
    self.assertFalse(fn(range(100)))

  def testAnd(self):
    fn = ht.TAnd(ht.TNotNone, ht.TString)
    self.assertTrue(fn(""))
    self.assertFalse(fn(1))
    self.assertFalse(fn(None))

  def testOr(self):
    fn = ht.TMaybe(ht.TAnd(ht.TString, ht.TIsLength(5)))
    self.assertTrue(fn("12345"))
    self.assertTrue(fn(None))
    self.assertFalse(fn(1))
    self.assertFalse(fn(""))
    self.assertFalse(fn("abc"))

  def testMap(self):
    self.assertTrue(ht.TMap(str, ht.TString)(123))
    self.assertTrue(ht.TMap(int, ht.TInt)("9999"))
    self.assertFalse(ht.TMap(lambda x: x + 100, ht.TString)(123))

  def testNonEmptyString(self):
    self.assertTrue(ht.TNonEmptyString("xyz"))
    self.assertTrue(ht.TNonEmptyString("Hello World"))
    self.assertFalse(ht.TNonEmptyString(""))
    self.assertFalse(ht.TNonEmptyString(None))
    self.assertFalse(ht.TNonEmptyString([]))

  def testMaybeString(self):
    self.assertTrue(ht.TMaybeString("xyz"))
    self.assertTrue(ht.TMaybeString("Hello World"))
    self.assertTrue(ht.TMaybeString(None))
    self.assertFalse(ht.TMaybeString(""))
    self.assertFalse(ht.TMaybeString([]))

  def testMaybeBool(self):
    self.assertTrue(ht.TMaybeBool(False))
    self.assertTrue(ht.TMaybeBool(True))
    self.assertTrue(ht.TMaybeBool(None))
    self.assertFalse(ht.TMaybeBool([]))
    self.assertFalse(ht.TMaybeBool("0"))
    self.assertFalse(ht.TMaybeBool("False"))

  def testListOf(self):
    fn = ht.TListOf(ht.TNonEmptyString)
    self.assertTrue(fn([]))
    self.assertTrue(fn(["x"]))
    self.assertTrue(fn(["Hello", "World"]))
    self.assertFalse(fn(None))
    self.assertFalse(fn(False))
    self.assertFalse(fn(range(3)))
    self.assertFalse(fn(["x", None]))

  def testDictOf(self):
    fn = ht.TDictOf(ht.TNonEmptyString, ht.TInt)
    self.assertTrue(fn({}))
    self.assertTrue(fn({"x": 123, "y": 999}))
    self.assertFalse(fn(None))
    self.assertFalse(fn({1: "x"}))
    self.assertFalse(fn({"x": ""}))
    self.assertFalse(fn({"x": None}))
    self.assertFalse(fn({"": 8234}))

  def testStrictDictRequireAllExclusive(self):
    fn = ht.TStrictDict(True, True, { "a": ht.TInt, })
    self.assertFalse(fn(1))
    self.assertFalse(fn(None))
    self.assertFalse(fn({}))
    self.assertFalse(fn({"a": "Hello", }))
    self.assertFalse(fn({"unknown": 999,}))
    self.assertFalse(fn({"unknown": None,}))

    self.assertTrue(fn({"a": 123, }))
    self.assertTrue(fn({"a": -5, }))

    fn = ht.TStrictDict(True, True, { "a": ht.TInt, "x": ht.TString, })
    self.assertFalse(fn({}))
    self.assertFalse(fn({"a": -5, }))
    self.assertTrue(fn({"a": 123, "x": "", }))
    self.assertFalse(fn({"a": 123, "x": None, }))

  def testStrictDictExclusive(self):
    fn = ht.TStrictDict(False, True, { "a": ht.TInt, "b": ht.TList, })
    self.assertTrue(fn({}))
    self.assertTrue(fn({"a": 123, }))
    self.assertTrue(fn({"b": list(range(4)), }))
    self.assertFalse(fn({"b": 123, }))

    self.assertFalse(fn({"foo": {}, }))
    self.assertFalse(fn({"bar": object(), }))

  def testStrictDictRequireAll(self):
    fn = ht.TStrictDict(True, False, { "a": ht.TInt, "m": ht.TInt, })
    self.assertTrue(fn({"a": 1, "m": 2, "bar": object(), }))
    self.assertFalse(fn({}))
    self.assertFalse(fn({"a": 1, "bar": object(), }))
    self.assertFalse(fn({"a": 1, "m": [], "bar": object(), }))

  def testStrictDict(self):
    fn = ht.TStrictDict(False, False, { "a": ht.TInt, })
    self.assertTrue(fn({}))
    self.assertFalse(fn({"a": ""}))
    self.assertTrue(fn({"a": 11}))
    self.assertTrue(fn({"other": 11}))
    self.assertTrue(fn({"other": object()}))

  def testJobId(self):
    for i in [0, 1, 4395, 2347625220]:
      self.assertTrue(ht.TJobId(i))
      self.assertTrue(ht.TJobId(str(i)))
      self.assertFalse(ht.TJobId(-(i + 1)))

    for i in ["", "-", ".", ",", "a", "99j", "job-123", "\t", " 83 ",
              None, [], {}, object()]:
      self.assertFalse(ht.TJobId(i))

  def testRelativeJobId(self):
    for i in [-1, -93, -4395]:
      self.assertTrue(ht.TRelativeJobId(i))
      self.assertFalse(ht.TRelativeJobId(str(i)))

    for i in [0, 1, 2, 10, 9289, "", "0", "-1", "-999"]:
      self.assertFalse(ht.TRelativeJobId(i))
      self.assertFalse(ht.TRelativeJobId(str(i)))

  def testItems(self):
    self.assertRaises(AssertionError, ht.TItems, [])

    fn = ht.TItems([ht.TString])
    self.assertFalse(fn([0]))
    self.assertFalse(fn([None]))
    self.assertTrue(fn(["Hello"]))
    self.assertTrue(fn(["Hello", "World"]))
    self.assertTrue(fn(["Hello", 0, 1, 2, "anything"]))

    fn = ht.TItems([ht.TAny, ht.TInt, ht.TAny])
    self.assertTrue(fn(["Hello", 0, []]))
    self.assertTrue(fn(["Hello", 893782]))
    self.assertTrue(fn([{}, -938210858947, None]))
    self.assertFalse(fn(["Hello", []]))

  def testInstanceOf(self):
    fn = ht.TInstanceOf(self.__class__)
    self.assertTrue(fn(self))
    self.assertTrue(str(fn).startswith("Instance of "))

    self.assertFalse(fn(None))

  def testMaybeValueNone(self):
    fn = ht.TMaybeValueNone(ht.TInt)

    self.assertTrue(fn(None))
    self.assertTrue(fn(0))
    self.assertTrue(fn(constants.VALUE_NONE))

    self.assertFalse(fn(""))
    self.assertFalse(fn([]))
    self.assertFalse(fn(constants.VALUE_DEFAULT))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
