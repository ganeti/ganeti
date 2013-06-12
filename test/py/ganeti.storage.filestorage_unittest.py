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
    info = filestorage.GetFileStorageSpaceInfo("/")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
