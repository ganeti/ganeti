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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
