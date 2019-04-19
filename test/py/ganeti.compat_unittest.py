#!/usr/bin/python3
#

# Copyright (C) 2010 Google Inc.
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


"""Script for unittesting the compat module"""

import inspect
import unittest

from ganeti import compat

import testutils


class TestPartial(testutils.GanetiTestCase):
  def test(self):
    # Test standard version
    self._Test(compat.partial)

    # Test our version
    self._Test(compat._partial)

  def _Test(self, fn):
    def _TestFunc1(x, power=2):
      return x ** power

    cubic = fn(_TestFunc1, power=3)
    self.assertEqual(cubic(1), 1)
    self.assertEqual(cubic(3), 27)
    self.assertEqual(cubic(4), 64)

    def _TestFunc2(*args, **kwargs):
      return (args, kwargs)

    self.assertEqualValues(fn(_TestFunc2, "Hello", "World")("Foo"),
                           (("Hello", "World", "Foo"), {}))

    self.assertEqualValues(fn(_TestFunc2, "Hello", xyz=123)("Foo"),
                           (("Hello", "Foo"), {"xyz": 123}))

    self.assertEqualValues(fn(_TestFunc2, xyz=123)("Foo", xyz=999),
                           (("Foo", ), {"xyz": 999,}))


class TestTryToRoman(testutils.GanetiTestCase):
  """test the compat.TryToRoman function"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    # Save the compat.roman module so we can alter it with a fake...
    self.compat_roman_module = compat.roman

  def tearDown(self):
    # ...and restore it at the end of the test
    compat.roman = self.compat_roman_module
    testutils.GanetiTestCase.tearDown(self)

  def testAFewIntegers(self):
    # This test only works is the roman module is installed
    if compat.roman is not None:
      self.assertEqual(compat.TryToRoman(0), 0)
      self.assertEqual(compat.TryToRoman(1), "I")
      self.assertEqual(compat.TryToRoman(4), "IV")
      self.assertEqual(compat.TryToRoman(5), "V")

  def testWithNoRoman(self):
    # compat.roman is saved/restored in setUp/tearDown
    compat.roman = None
    self.assertEqual(compat.TryToRoman(0), 0)
    self.assertEqual(compat.TryToRoman(1), 1)
    self.assertEqual(compat.TryToRoman(4), 4)
    self.assertEqual(compat.TryToRoman(5), 5)

  def testStrings(self):
    self.assertEqual(compat.TryToRoman("astring"), "astring")
    self.assertEqual(compat.TryToRoman("5"), "5")

  def testDontConvert(self):
    self.assertEqual(compat.TryToRoman(0, convert=False), 0)
    self.assertEqual(compat.TryToRoman(1, convert=False), 1)
    self.assertEqual(compat.TryToRoman(7, convert=False), 7)
    self.assertEqual(compat.TryToRoman("astring", convert=False), "astring")
    self.assertEqual(compat.TryToRoman("19", convert=False), "19")


class TestUniqueFrozenset(unittest.TestCase):
  def testDuplicates(self):
    for values in [["", ""], ["Hello", "World", "Hello"]]:
      self.assertRaises(ValueError, compat.UniqueFrozenset, values)

  def testEmpty(self):
    self.assertEqual(compat.UniqueFrozenset([]), frozenset([]))

  def testUnique(self):
    self.assertEqual(compat.UniqueFrozenset([1, 2, 3]), frozenset([1, 2, 3]))

  def testGenerator(self):
    seq = ("Foo%s" % i for i in range(10))
    self.assertTrue(inspect.isgenerator(seq))
    self.assertFalse(isinstance(seq, (list, tuple)))
    self.assertEqual(compat.UniqueFrozenset(seq),
                     frozenset(["Foo%s" % i for i in range(10)]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
