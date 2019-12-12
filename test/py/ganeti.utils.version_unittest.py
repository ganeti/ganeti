#!/usr/bin/python3
#

# Copyright (C) 2013 Google Inc.
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


"""Script for unittesting the version utility functions"""

import unittest

from ganeti.utils import version

import testutils

class ParseVersionTest(unittest.TestCase):
    def testParseVersion(self):
        self.assertEqual(version.ParseVersion("2.10"), (2, 10, 0))
        self.assertEqual(version.ParseVersion("2.10.1"), (2, 10, 1))
        self.assertEqual(version.ParseVersion("2.10.1~beta2"), (2, 10, 1))
        self.assertEqual(version.ParseVersion("2.10.1-3"), (2, 10, 1))
        self.assertEqual(version.ParseVersion("2"), None)
        self.assertEqual(version.ParseVersion("pink bunny"), None)

class UpgradeRangeTest(unittest.TestCase):
    def testUpgradeRange(self):
        self.assertEqual(version.UpgradeRange((2,11,0), current=(2,10,0)),
                          None)
        self.assertEqual(version.UpgradeRange((2,10,0), current=(2,10,0)),
                          None)
        self.assertEqual(version.UpgradeRange((2,11,3), current=(2,12,0)),
                          None)
        self.assertEqual(version.UpgradeRange((2,11,3), current=(2,12,99)),
                          None)
        self.assertEqual(version.UpgradeRange((3,0,0), current=(2,12,0)),
                          "different major versions")
        self.assertEqual(version.UpgradeRange((2,12,0), current=(3,0,0)),
                          "different major versions")
        self.assertEqual(version.UpgradeRange((2,10,0), current=(2,12,0)),
                          "can only downgrade one minor version at a time")
        self.assertEqual(version.UpgradeRange((2,9,0), current=(2,10,0)),
                          "automatic upgrades only supported from 2.10 onwards")
        self.assertEqual(version.UpgradeRange((2,10,0), current=(2,9,0)),
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

class IsEqualTest(unittest.TestCase):
    def testIsEqual(self):
        self.assertTrue(version.IsEqual((2, 10, 0), 2, 10, 0))
        self.assertFalse(version.IsEqual((2, 10, 0), 2, 10, 2))
        self.assertFalse(version.IsEqual((2, 10, 0), 2, 12, 0))
        self.assertFalse(version.IsEqual((2, 10, 0), 3, 10, 0))
        self.assertTrue(version.IsEqual((2, 10, 0), 2, 10, None))
        self.assertTrue(version.IsEqual((2, 10, 5), 2, 10, None))
        self.assertFalse(version.IsEqual((2, 11, 5), 2, 10, None))
        self.assertFalse(version.IsEqual((3, 10, 5), 2, 10, None))

if __name__ == "__main__":
  testutils.GanetiTestProgram()
