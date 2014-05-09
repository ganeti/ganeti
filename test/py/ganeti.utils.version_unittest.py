#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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


"""Script for unittesting the version utility functions"""

import unittest

from ganeti.utils import version

import testutils

class ParseVersionTest(unittest.TestCase):
    def testParseVersion(self):
        self.assertEquals(version.ParseVersion("2.10"), (2, 10, 0))
        self.assertEquals(version.ParseVersion("2.10.1"), (2, 10, 1))
        self.assertEquals(version.ParseVersion("2.10.1~beta2"), (2, 10, 1))
        self.assertEquals(version.ParseVersion("2.10.1-3"), (2, 10, 1))
        self.assertEquals(version.ParseVersion("2"), None)
        self.assertEquals(version.ParseVersion("pink bunny"), None)

class UpgradeRangeTest(unittest.TestCase):
    def testUpgradeRange(self):
        self.assertEquals(version.UpgradeRange((2,11,0), current=(2,10,0)),
                          None)
        self.assertEquals(version.UpgradeRange((2,10,0), current=(2,10,0)),
                          None)
        self.assertEquals(version.UpgradeRange((2,11,3), current=(2,12,0)),
                          None)
        self.assertEquals(version.UpgradeRange((2,11,3), current=(2,12,99)),
                          None)
        self.assertEquals(version.UpgradeRange((3,0,0), current=(2,12,0)),
                          "different major versions")
        self.assertEquals(version.UpgradeRange((2,12,0), current=(3,0,0)),
                          "different major versions")
        self.assertEquals(version.UpgradeRange((2,10,0), current=(2,12,0)),
                          "can only downgrade one minor version at a time")
        self.assertEquals(version.UpgradeRange((2,9,0), current=(2,10,0)),
                          "automatic upgrades only supported from 2.10 onwards")
        self.assertEquals(version.UpgradeRange((2,10,0), current=(2,9,0)),
                          "automatic upgrades only supported from 2.10 onwards")

class ShouldCfgdowngradeTest(unittest.TestCase):
    def testShouldCfgDowngrade(self):
        self.assertTrue(version.ShouldCfgdowngrade((2,9,3), current=(2,10,0)))
        self.assertTrue(version.ShouldCfgdowngrade((2,9,0), current=(2,10,4)))
        self.assertFalse(version.ShouldCfgdowngrade((2,9,0), current=(2,11,0)))
        self.assertFalse(version.ShouldCfgdowngrade((2,9,0), current=(3,10,0)))
        self.assertFalse(version.ShouldCfgdowngrade((2,10,0), current=(3,10,0)))


class IsCorrectConfigVersionTest(unittest.TestCase):
    def testIsCorrectConfigVersion(self):
        self.assertTrue(version.IsCorrectConfigVersion((2,10,1), (2,10,0)))
        self.assertFalse(version.IsCorrectConfigVersion((2,11,0), (2,10,0)))
        self.assertFalse(version.IsCorrectConfigVersion((3,10,0), (2,10,0)))


class IsBeforeTest(unittest.TestCase):
    def testIsBefore(self):
        self.assertTrue(version.IsBefore(None, 2, 10, 0))
        self.assertFalse(version.IsBefore((2, 10, 0), 2, 10, 0))
        self.assertTrue(version.IsBefore((2, 10, 0), 2, 10, 1))
        self.assertFalse(version.IsBefore((2, 10, 1), 2, 10, 0))
        self.assertTrue(version.IsBefore((2, 10, 1), 2, 11, 0))
        self.assertFalse(version.IsBefore((2, 11, 0), 2, 10, 3))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
