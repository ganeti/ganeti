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


"""Script for testing ganeti.masterd.instance"""

import os
import sys
import unittest

from ganeti import utils
from ganeti import masterd

from ganeti.masterd.instance import \
  ImportExportTimeouts, _TimeoutExpired, _DiskImportExportBase

import testutils


class TestMisc(unittest.TestCase):
  def testTimeouts(self):
    tmo = ImportExportTimeouts(0)
    self.assertEqual(tmo.connect, 0)
    self.assertEqual(tmo.listen, ImportExportTimeouts.DEFAULT_LISTEN_TIMEOUT)
    self.assertEqual(tmo.ready, ImportExportTimeouts.DEFAULT_READY_TIMEOUT)
    self.assertEqual(tmo.error, ImportExportTimeouts.DEFAULT_ERROR_TIMEOUT)

    tmo = ImportExportTimeouts(999)
    self.assertEqual(tmo.connect, 999)

  def testTimeoutExpired(self):
    self.assert_(_TimeoutExpired(100, 300, _time_fn=lambda: 500))
    self.assertFalse(_TimeoutExpired(100, 300, _time_fn=lambda: 0))
    self.assertFalse(_TimeoutExpired(100, 300, _time_fn=lambda: 100))
    self.assertFalse(_TimeoutExpired(100, 300, _time_fn=lambda: 400))

  def testDiskImportExportBaseDirect(self):
    self.assertRaises(AssertionError, _DiskImportExportBase,
                      None, None, None, None, None, None, None)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
