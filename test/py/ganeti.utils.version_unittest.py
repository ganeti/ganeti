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
        self.assertEquals(version.ParseVersion("2"), None)
        self.assertEquals(version.ParseVersion("pink bunny"), None)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
