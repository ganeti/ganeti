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


"""Script for unittesting the ganeti.storage.file module"""

import os
import shutil
import tempfile
import unittest

from ganeti import errors
from ganeti.storage import filestorage

import testutils


class TestFileStorageSpaceInfo(unittest.TestCase):

  def testSpaceInfoPathInvalid(self):
    """Tests that an error is raised when the given path is not existing.

    """
    self.assertRaises(errors.CommandError, filestorage.GetFileStorageSpaceInfo,
                      "/path/does/not/exist/")

  def testSpaceInfoPathValid(self):
    """Smoke test run on a directory that exists for sure.

    """
    filestorage.GetFileStorageSpaceInfo("/")


class TestCheckFileStoragePath(unittest.TestCase):
  def _WriteAllowedFile(self, allowed_paths_filename, allowed_paths):
    allowed_paths_file = open(allowed_paths_filename, 'w')
    allowed_paths_file.write('\n'.join(allowed_paths))
    allowed_paths_file.close()

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.allowed_paths = [os.path.join(self.tmpdir, "allowed")]
    for path in self.allowed_paths:
      os.mkdir(path)
    self.allowed_paths_filename = os.path.join(self.tmpdir, "allowed-path-file")
    self._WriteAllowedFile(self.allowed_paths_filename, self.allowed_paths)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCheckFileStoragePathExistance(self):
    filestorage._CheckFileStoragePathExistance(self.tmpdir)

  def testCheckFileStoragePathExistanceFail(self):
    path = os.path.join(self.tmpdir, "does/not/exist")
    self.assertRaises(errors.FileStoragePathError,
        filestorage._CheckFileStoragePathExistance, path)

  def testCheckFileStoragePathNotWritable(self):
    path = os.path.join(self.tmpdir, "isnotwritable/")
    os.mkdir(path)
    os.chmod(path, 0)
    self.assertRaises(errors.FileStoragePathError,
        filestorage._CheckFileStoragePathExistance, path)
    os.chmod(path, 777)

  def testCheckFileStoragePath(self):
    path = os.path.join(self.allowed_paths[0], "allowedsubdir")
    os.mkdir(path)
    result = filestorage.CheckFileStoragePath(
        path, _allowed_paths_file=self.allowed_paths_filename)
    self.assertEqual(None, result)

  def testCheckFileStoragePathNotAllowed(self):
    path = os.path.join(self.tmpdir, "notallowed")
    result = filestorage.CheckFileStoragePath(
        path, _allowed_paths_file=self.allowed_paths_filename)
    self.assertTrue("not acceptable" in result)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
