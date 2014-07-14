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
    self.assertEqual(storage_type, constants.ST_SHARED_FILE)
    self.assertEqual(storage_key, self._cluster.shared_file_storage_dir)

  def testGetDefaultStorageUnitForDiskTemplateGluster(self):
    (storage_type, storage_key) = \
        storage._GetDefaultStorageUnitForDiskTemplate(self._cfg,
                                                      constants.DT_GLUSTER)
    self.assertEqual(storage_type, constants.ST_GLUSTER)
    self.assertEqual(storage_key, self._cluster.gluster_storage_dir)

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
    sts_non_reporting = \
      storage.GetDiskTemplatesOfStorageTypes(constants.ST_GLUSTER,
                                             constants.ST_SHARED_FILE)
    disk_templates = constants.DTS_FILEBASED - frozenset(sts_non_reporting)
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


class TestGetDiskLabels(unittest.TestCase):

  def setUp(self):
    pass

  def testNormalPrefix(self):
    labels = ["/dev/sda", "/dev/sdb", "/dev/sdc", "/dev/sdd",
              "/dev/sde", "/dev/sdf", "/dev/sdg", "/dev/sdh",
              "/dev/sdi", "/dev/sdj", "/dev/sdk", "/dev/sdl",
              "/dev/sdm", "/dev/sdn", "/dev/sdo", "/dev/sdp",
              "/dev/sdq", "/dev/sdr", "/dev/sds", "/dev/sdt",
              "/dev/sdu", "/dev/sdv", "/dev/sdw", "/dev/sdx",
              "/dev/sdy", "/dev/sdz", "/dev/sdaa", "/dev/sdab",
              "/dev/sdac", "/dev/sdad", "/dev/sdae", "/dev/sdaf",
              "/dev/sdag", "/dev/sdah", "/dev/sdai", "/dev/sdaj",
              "/dev/sdak", "/dev/sdal", "/dev/sdam", "/dev/sdan",
              "/dev/sdao", "/dev/sdap", "/dev/sdaq", "/dev/sdar",
              "/dev/sdas", "/dev/sdat", "/dev/sdau", "/dev/sdav",
              "/dev/sdaw", "/dev/sdax", "/dev/sday", "/dev/sdaz",
              "/dev/sdba", "/dev/sdbb", "/dev/sdbc", "/dev/sdbd",
              "/dev/sdbe", "/dev/sdbf", "/dev/sdbg", "/dev/sdbh"]
    result = list(storage.GetDiskLabels("/dev/sd", 60))
    self.assertEqual(labels, result)

  def testEmptyPrefix(self):
    labels = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k",
              "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v",
              "w", "x", "y", "z", "aa", "ab", "ac", "ad", "ae", "af",
              "ag", "ah", "ai", "aj", "ak", "al", "am", "an", "ao",
              "ap", "aq", "ar", "as", "at", "au", "av", "aw", "ax",
              "ay", "az", "ba", "bb", "bc", "bd", "be", "bf", "bg",
              "bh"]
    result = list(storage.GetDiskLabels("", 60))
    self.assertEqual(labels, result)

  def testWrapAt2To3(self):
    start1 = 27
    start2 = 703
    result1 = list(storage.GetDiskLabels("", start1))
    result2 = \
        map(lambda x: x[1:],
            list(storage.GetDiskLabels("", start2, start=start2 - start1)))
    self.assertEqual(result1, result2)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
