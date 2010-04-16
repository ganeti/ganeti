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
# 0.0510-1301, USA.


"""Script for unittesting the uidpool module"""


import unittest

from ganeti import constants
from ganeti import uidpool
from ganeti import errors

import testutils


class TestUidPool(testutils.GanetiTestCase):
  """Uid-pool tests"""

  def setUp(self):
    self.old_uid_min = constants.UIDPOOL_UID_MIN
    self.old_uid_max = constants.UIDPOOL_UID_MAX
    constants.UIDPOOL_UID_MIN = 1
    constants.UIDPOOL_UID_MAX = 10

  def tearDown(self):
    constants.UIDPOOL_UID_MIN = self.old_uid_min
    constants.UIDPOOL_UID_MAX = self.old_uid_max

  def testParseUidPool(self):
    self.assertEqualValues(
        uidpool.ParseUidPool("1-100,200,"),
        [(1, 100), (200, 200)])
    self.assertEqualValues(
        uidpool.ParseUidPool("1000:2000-2500", separator=":"),
        [(1000, 1000), (2000, 2500)])
    self.assertEqualValues(
        uidpool.ParseUidPool("1000\n2000-2500", separator="\n"),
        [(1000, 1000), (2000, 2500)])

  def testCheckUidPool(self):
    # UID < UIDPOOL_UID_MIN
    self.assertRaises(errors.OpPrereqError,
                      uidpool.CheckUidPool,
                      [(0, 0)])
    # UID > UIDPOOL_UID_MAX
    self.assertRaises(errors.OpPrereqError,
                      uidpool.CheckUidPool,
                      [(11, 11)])
    # lower boundary > higher boundary
    self.assertRaises(errors.OpPrereqError,
                      uidpool.CheckUidPool,
                      [(2, 1)])

  def testFormatUidPool(self):
    self.assertEqualValues(
        uidpool.FormatUidPool([(1, 100), (200, 200)]),
        "1-100, 200")
    self.assertEqualValues(
        uidpool.FormatUidPool([(1, 100), (200, 200)], separator=":"),
        "1-100:200")
    self.assertEqualValues(
        uidpool.FormatUidPool([(1, 100), (200, 200)], separator="\n"),
        "1-100\n200")


if __name__ == '__main__':
  testutils.GanetiTestProgram()
