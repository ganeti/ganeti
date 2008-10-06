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

import ganeti
import testutils
from ganeti import constants
from ganeti import cli
from ganeti.errors import OpPrereqError

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


if __name__ == '__main__':
  unittest.main()
