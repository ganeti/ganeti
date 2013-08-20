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
from ganeti.storage import drbd
from ganeti import errors
from ganeti import pathutils

import testutils
import mock


class TestPrepareFileStorage(unittest.TestCase):
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def enableFileStorage(self, enable):
    self.enabled_disk_templates = []
    if enable:
      self.enabled_disk_templates.append(constants.DT_FILE)
    else:
      # anything != DT_FILE would do here
      self.enabled_disk_templates.append(constants.DT_DISKLESS)

  def testFallBackToDefaultPathAcceptedFileStorageEnabled(self):
    expected_file_storage_dir = pathutils.DEFAULT_FILE_STORAGE_DIR
    acceptance_fn = mock.Mock()
    init_fn = mock.Mock(return_value=expected_file_storage_dir)
    self.enableFileStorage(True)
    file_storage_dir = bootstrap._PrepareFileStorage(
        self.enabled_disk_templates, None, acceptance_fn=acceptance_fn,
        init_fn=init_fn)
    self.assertEqual(expected_file_storage_dir, file_storage_dir)
    acceptance_fn.assert_called_with(expected_file_storage_dir)
    init_fn.assert_called_with(expected_file_storage_dir)

  def testPathAcceptedFileStorageEnabled(self):
    acceptance_fn = mock.Mock()
    init_fn = mock.Mock(return_value=self.tmpdir)
    self.enableFileStorage(True)
    file_storage_dir = bootstrap._PrepareFileStorage(
        self.enabled_disk_templates, self.tmpdir, acceptance_fn=acceptance_fn,
        init_fn=init_fn)
    self.assertEqual(self.tmpdir, file_storage_dir)
    acceptance_fn.assert_called_with(self.tmpdir)
    init_fn.assert_called_with(self.tmpdir)

  def testPathAcceptedFileStorageDisabled(self):
    acceptance_fn = mock.Mock()
    init_fn = mock.Mock()
    self.enableFileStorage(False)
    file_storage_dir = bootstrap._PrepareFileStorage(
        self.enabled_disk_templates, self.tmpdir, acceptance_fn=acceptance_fn,
        init_fn=init_fn)
    self.assertEqual(self.tmpdir, file_storage_dir)
    self.assertFalse(init_fn.called)
    self.assertFalse(acceptance_fn.called)

  def testPathNotAccepted(self):
    acceptance_fn = mock.Mock()
    acceptance_fn.side_effect = errors.FileStoragePathError
    init_fn = mock.Mock()
    self.enableFileStorage(True)
    self.assertRaises(errors.OpPrereqError, bootstrap._PrepareFileStorage,
        self.enabled_disk_templates, self.tmpdir, acceptance_fn=acceptance_fn,
        init_fn=init_fn)
    acceptance_fn.assert_called_with(self.tmpdir)


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


class TestRestrictIpolicyToEnabledDiskTemplates(unittest.TestCase):

  def testNoRestriction(self):
    allowed_disk_templates = list(constants.DISK_TEMPLATES)
    ipolicy = {constants.IPOLICY_DTS: allowed_disk_templates}
    enabled_disk_templates = list(constants.DISK_TEMPLATES)
    bootstrap._RestrictIpolicyToEnabledDiskTemplates(
        ipolicy, enabled_disk_templates)
    self.assertEqual(ipolicy[constants.IPOLICY_DTS], allowed_disk_templates)

  def testRestriction(self):
    allowed_disk_templates = [constants.DT_DRBD8, constants.DT_PLAIN]
    ipolicy = {constants.IPOLICY_DTS: allowed_disk_templates}
    enabled_disk_templates = [constants.DT_PLAIN, constants.DT_FILE]
    bootstrap._RestrictIpolicyToEnabledDiskTemplates(
        ipolicy, enabled_disk_templates)
    self.assertEqual(ipolicy[constants.IPOLICY_DTS], [constants.DT_PLAIN])


class TestInitCheckDrbdHelper(unittest.TestCase):

  @testutils.patch_object(drbd.DRBD8, "GetUsermodeHelper")
  def testNoDrbd(self, drbd_mock_get_usermode_helper):
    drbd_enabled = False
    drbd_helper = None
    bootstrap._InitCheckDrbdHelper(drbd_helper, drbd_enabled)

  @testutils.patch_object(drbd.DRBD8, "GetUsermodeHelper")
  def testHelperNone(self, drbd_mock_get_usermode_helper):
    drbd_enabled = True
    current_helper = "/bin/helper"
    drbd_helper = None
    drbd_mock_get_usermode_helper.return_value = current_helper
    bootstrap._InitCheckDrbdHelper(drbd_helper, drbd_enabled)

  @testutils.patch_object(drbd.DRBD8, "GetUsermodeHelper")
  def testHelperOk(self, drbd_mock_get_usermode_helper):
    drbd_enabled = True
    current_helper = "/bin/helper"
    drbd_helper = "/bin/helper"
    drbd_mock_get_usermode_helper.return_value = current_helper
    bootstrap._InitCheckDrbdHelper(drbd_helper, drbd_enabled)

  @testutils.patch_object(drbd.DRBD8, "GetUsermodeHelper")
  def testWrongHelper(self, drbd_mock_get_usermode_helper):
    drbd_enabled = True
    current_helper = "/bin/otherhelper"
    drbd_helper = "/bin/helper"
    drbd_mock_get_usermode_helper.return_value = current_helper
    self.assertRaises(errors.OpPrereqError,
        bootstrap._InitCheckDrbdHelper, drbd_helper, drbd_enabled)

  @testutils.patch_object(drbd.DRBD8, "GetUsermodeHelper")
  def testHelperCheckFails(self, drbd_mock_get_usermode_helper):
    drbd_enabled = True
    drbd_helper = "/bin/helper"
    drbd_mock_get_usermode_helper.side_effect=errors.BlockDeviceError
    self.assertRaises(errors.OpPrereqError,
        bootstrap._InitCheckDrbdHelper, drbd_helper, drbd_enabled)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
