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


"""Script for unittesting the compat module"""

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
      self.assertEquals(compat.TryToRoman(0), 0)
      self.assertEquals(compat.TryToRoman(1), "I")
      self.assertEquals(compat.TryToRoman(4), "IV")
      self.assertEquals(compat.TryToRoman(5), "V")

  def testWithNoRoman(self):
    # compat.roman is saved/restored in setUp/tearDown
    compat.roman = None
    self.assertEquals(compat.TryToRoman(0), 0)
    self.assertEquals(compat.TryToRoman(1), 1)
    self.assertEquals(compat.TryToRoman(4), 4)
    self.assertEquals(compat.TryToRoman(5), 5)

  def testStrings(self):
    self.assertEquals(compat.TryToRoman("astring"), "astring")
    self.assertEquals(compat.TryToRoman("5"), "5")

  def testDontConvert(self):
    self.assertEquals(compat.TryToRoman(0, convert=False), 0)
    self.assertEquals(compat.TryToRoman(1, convert=False), 1)
    self.assertEquals(compat.TryToRoman(7, convert=False), 7)
    self.assertEquals(compat.TryToRoman("astring", convert=False), "astring")
    self.assertEquals(compat.TryToRoman("19", convert=False), "19")


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
    self.assertTrue(callable(seq.next))
    self.assertFalse(isinstance(seq, (list, tuple)))
    self.assertEqual(compat.UniqueFrozenset(seq),
                     frozenset(["Foo%s" % i for i in range(10)]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
