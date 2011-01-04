#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.rapi.baserlib"""

import unittest

from ganeti import errors
from ganeti import opcodes
from ganeti import ht
from ganeti import http
from ganeti.rapi import baserlib

import testutils


class TestFillOpcode(unittest.TestCase):
  class _TestOp(opcodes.OpCode):
    OP_ID = "RAPI_TEST_OP"
    OP_PARAMS = [
      ("test", None, ht.TMaybeString),
      ]

  def test(self):
    for static in [None, {}]:
      op = baserlib.FillOpcode(self._TestOp, {}, static)
      self.assertTrue(isinstance(op, self._TestOp))
      self.assertFalse(hasattr(op, "test"))

  def testStatic(self):
    op = baserlib.FillOpcode(self._TestOp, {}, {"test": "abc"})
    self.assertTrue(isinstance(op, self._TestOp))
    self.assertEqual(op.test, "abc")

    # Overwrite static parameter
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self._TestOp, {"test": 123}, {"test": "abc"})

  def testType(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self._TestOp, {"test": [1, 2, 3]}, {})

  def testStaticType(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self._TestOp, {}, {"test": [1, 2, 3]})

  def testUnicode(self):
    op = baserlib.FillOpcode(self._TestOp, {u"test": "abc"}, {})
    self.assertTrue(isinstance(op, self._TestOp))
    self.assertEqual(op.test, "abc")

    op = baserlib.FillOpcode(self._TestOp, {}, {u"test": "abc"})
    self.assertTrue(isinstance(op, self._TestOp))
    self.assertEqual(op.test, "abc")

  def testUnknownParameter(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self._TestOp, {"othervalue": 123}, None)

  def testInvalidBody(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self._TestOp, "", None)
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self._TestOp, range(10), None)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
