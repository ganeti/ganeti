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


"""Script for unittesting the ganeti.utils.storage module"""

import mock

import unittest

from ganeti import constants
from ganeti.utils import storage

import testutils


class TestGetStorageUnitForDiskTemplate(unittest.TestCase):

  def setUp(self):
    self._default_vg_name = "some_vg_name"
    self._cluster = mock.Mock()
    self._cluster.file_storage_dir = "my/file/storage/dir"
    self._cluster.shared_file_storage_dir = "my/shared/file/storage/dir"
    self._cfg = mock.Mock()
    self._cfg.GetVGName = mock.Mock(return_value=self._default_vg_name)
    self._cfg.GetClusterInfo = mock.Mock(return_value=self._cluster)

  def testGetDefaultStorageUnitForDiskTemplateLvm(self):
    for disk_template in [constants.DT_DRBD8, constants.DT_PLAIN]:
      (storage_type, storage_key) = \
          storage._GetDefaultStorageUnitForDiskTemplate(self._cfg,
                                                        disk_template)
      self.assertEqual(storage_type, constants.ST_LVM_VG)
      self.assertEqual(storage_key, self._default_vg_name)

  def testGetDefaultStorageUnitForDiskTemplateFile(self):
    (storage_type, storage_key) = \
        storage._GetDefaultStorageUnitForDiskTemplate(self._cfg,
                                                      constants.DT_FILE)
    self.assertEqual(storage_type, constants.ST_FILE)
    self.assertEqual(storage_key, self._cluster.file_storage_dir)

  def testGetDefaultStorageUnitForDiskTemplateSharedFile(self):
    (storage_type, storage_key) = \
        storage._GetDefaultStorageUnitForDiskTemplate(self._cfg,
                                                      constants.DT_SHARED_FILE)
    self.assertEqual(storage_type, constants.ST_FILE)
    self.assertEqual(storage_key, self._cluster.shared_file_storage_dir)

  def testGetDefaultStorageUnitForDiskTemplateDiskless(self):
    (storage_type, storage_key) = \
        storage._GetDefaultStorageUnitForDiskTemplate(self._cfg,
                                                      constants.DT_DISKLESS)
    self.assertEqual(storage_type, constants.ST_DISKLESS)
    self.assertEqual(storage_key, None)


class TestGetStorageUnits(unittest.TestCase):

  def setUp(self):
    storage._GetDefaultStorageUnitForDiskTemplate = \
        mock.Mock(return_value=("foo", "bar"))
    self._cfg = mock.Mock()

  def testGetStorageUnits(self):
    disk_templates = constants.DTS_FILEBASED
    storage_units = storage.GetStorageUnits(self._cfg, disk_templates)
    self.assertEqual(len(storage_units), len(disk_templates))

  def testGetStorageUnitsLvm(self):
    disk_templates = [constants.DT_PLAIN, constants.DT_DRBD8]
    storage_units = storage.GetStorageUnits(self._cfg, disk_templates)
    self.assertEqual(len(storage_units), len(disk_templates))


class TestLookupSpaceInfoByStorageType(unittest.TestCase):

  def setUp(self):
    self._space_info = [
        {"type": st, "name": st + "_key", "storage_size": 0, "storage_free": 0}
        for st in constants.STORAGE_TYPES]

  def testValidLookup(self):
    query_type = constants.ST_LVM_PV
    result = storage.LookupSpaceInfoByStorageType(self._space_info, query_type)
    self.assertEqual(query_type, result["type"])

  def testNotInList(self):
    result = storage.LookupSpaceInfoByStorageType(self._space_info,
                                                  "non_existing_type")
    self.assertEqual(None, result)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
