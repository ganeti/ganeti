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


"""Script for testing ganeti.bootstrap"""

import shutil
import tempfile
import unittest

from ganeti import bootstrap
from ganeti import constants
from ganeti import errors

import testutils


class TestPrepareFileStorage(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testFileStorageEnabled(self):
    enabled_disk_templates = [constants.DT_FILE]
    file_storage_dir = bootstrap._PrepareFileStorage(
        enabled_disk_templates, self.tmpdir)
    self.assertEqual(self.tmpdir, file_storage_dir)

  def testFileStorageDisabled(self):
    # anything != DT_FILE would do here
    enabled_disk_templates = [constants.DT_PLAIN]
    file_storage_dir = bootstrap._PrepareFileStorage(
        enabled_disk_templates, self.tmpdir)
    self.assertEqual('', file_storage_dir)


class TestInitCheckEnabledDiskTemplates(unittest.TestCase):
  def testValidTemplates(self):
    enabled_disk_templates = list(constants.DISK_TEMPLATES)
    bootstrap._InitCheckEnabledDiskTemplates(enabled_disk_templates)

  def testInvalidTemplates(self):
    enabled_disk_templates = ["pinkbunny"]
    self.assertRaises(errors.OpPrereqError,
        bootstrap._InitCheckEnabledDiskTemplates, enabled_disk_templates)

  def testEmptyTemplates(self):
    enabled_disk_templates = []
    self.assertRaises(errors.OpPrereqError,
        bootstrap._InitCheckEnabledDiskTemplates, enabled_disk_templates)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
