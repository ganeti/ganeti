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

from ganeti import utils
from ganeti import errors
from ganeti import qlang

import testutils


class TestReadSimpleFilter(unittest.TestCase):
  def _Test(self, filter_, expected):
    self.assertEqual(qlang.ReadSimpleFilter("name", filter_), expected)

  def test(self):
    self._Test(None, [])
    self._Test(["|", ["=", "name", "xyz"]], ["xyz"])

    for i in [1, 3, 10, 25, 140]:
      self._Test(["|"] + [["=", "name", "node%s" % j] for j in range(i)],
                 ["node%s" % j for j in range(i)])

  def testErrors(self):
    for i in [123, True, False, "", "Hello World", "a==b",
              [], ["x"], ["x", "y", "z"], ["|"],
              ["|", ["="]], ["|", "x"], ["|", 123],
              ["|", ["=", "otherfield", "xyz"]],
              ["|", ["=", "name", "xyz"], "abc"],
              ["|", ["=", "name", "xyz", "too", "long"]],
              ["|", ["=", "name", []]],
              ["|", ["=", "name", 999]],
              ["|", ["=", "name", "abc"], ["=", "otherfield", "xyz"]]]:
      self.assertRaises(errors.ParameterError, qlang.ReadSimpleFilter,
                        "name", i)


class TestMakeSimpleFilter(unittest.TestCase):
  def _Test(self, field, names, expected, parse_exp=None):
    if parse_exp is None:
      parse_exp = names

    filter_ = qlang.MakeSimpleFilter(field, names)
    self.assertEqual(filter_, expected)
    self.assertEqual(qlang.ReadSimpleFilter(field, filter_), parse_exp)

  def test(self):
    self._Test("name", None, None, parse_exp=[])
    self._Test("name", [], None)
    self._Test("name", ["node1.example.com"],
               ["|", ["=", "name", "node1.example.com"]])
    self._Test("xyz", ["a", "b", "c"],
               ["|", ["=", "xyz", "a"], ["=", "xyz", "b"], ["=", "xyz", "c"]])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
