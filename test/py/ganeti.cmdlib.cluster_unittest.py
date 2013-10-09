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


"""Script for unittesting the cmdlib module 'cluster'"""


import unittest

from ganeti.cmdlib import cluster
from ganeti import constants
from ganeti import errors

import testutils
import mock


class TestCheckFileStoragePath(unittest.TestCase):

  def setUp(self):
    unittest.TestCase.setUp(self)
    self.log_warning = mock.Mock()

  def enableFileStorage(self, file_storage_enabled):
    if file_storage_enabled:
      self.enabled_disk_templates = [constants.DT_FILE]
    else:
      # anything != 'file' would do here
      self.enabled_disk_templates = [constants.DT_DISKLESS]

  def testNone(self):
    self.enableFileStorage(True)
    self.assertRaises(
        errors.ProgrammerError,
        cluster.CheckFileStoragePathVsEnabledDiskTemplates,
        self.log_warning, None, self.enabled_disk_templates)

  def testNotEmptyAndEnabled(self):
    self.enableFileStorage(True)
    cluster.CheckFileStoragePathVsEnabledDiskTemplates(
        self.log_warning, "/some/path", self.enabled_disk_templates)

  def testNotEnabled(self):
    self.enableFileStorage(False)
    cluster.CheckFileStoragePathVsEnabledDiskTemplates(
        self.log_warning, "/some/path", self.enabled_disk_templates)
    self.assertTrue(self.log_warning.called)

  def testEmptyAndEnabled(self):
    self.enableFileStorage(True)
    self.assertRaises(
        errors.OpPrereqError,
        cluster.CheckFileStoragePathVsEnabledDiskTemplates,
        self.log_warning, "", self.enabled_disk_templates)

  def testEmptyAndDisabled(self):
    self.enableFileStorage(False)
    cluster.CheckFileStoragePathVsEnabledDiskTemplates(
        NotImplemented, "", self.enabled_disk_templates)


class TestGetEnabledDiskTemplates(unittest.TestCase):

  def testNoNew(self):
    op_dts = [constants.DT_DISKLESS]
    old_dts = [constants.DT_DISKLESS]
    (enabled_dts, new_dts, disabled_dts) =\
        cluster.LUClusterSetParams._GetDiskTemplateSetsInner(
            op_dts, old_dts)
    self.assertEqual(enabled_dts, old_dts)
    self.assertEqual(new_dts, [])
    self.assertEqual(disabled_dts, [])

  def testValid(self):
    op_dts = [constants.DT_PLAIN, constants.DT_DRBD8]
    old_dts = [constants.DT_DISKLESS, constants.DT_PLAIN]
    (enabled_dts, new_dts, disabled_dts) =\
        cluster.LUClusterSetParams._GetDiskTemplateSetsInner(
            op_dts, old_dts)
    self.assertEqual(enabled_dts, op_dts)
    self.assertEqual(new_dts, [constants.DT_DRBD8])
    self.assertEqual(disabled_dts, [constants.DT_DISKLESS])



if __name__ == "__main__":
  testutils.GanetiTestProgram()
