#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Utilities for unit testing"""

import os
import stat
import tempfile
import unittest

from ganeti import utils


def GetSourceDir():
  return os.environ.get("TOP_SRCDIR", ".")


class GanetiTestCase(unittest.TestCase):
  """Helper class for unittesting.

  This class defines a few utility functions that help in building
  unittests. Child classes must call the parent setup and cleanup.

  """
  def setUp(self):
    self._temp_files = []

  def tearDown(self):
    while self._temp_files:
      try:
        utils.RemoveFile(self._temp_files.pop())
      except EnvironmentError, err:
        pass

  def assertFileContent(self, file_name, expected_content):
    """Checks that the content of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_content: str
    @param expected_content: the content we expect

    """
    actual_content = utils.ReadFile(file_name)
    self.assertEqual(actual_content, expected_content)

  def assertFileMode(self, file_name, expected_mode):
    """Checks that the mode of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_mode: int
    @param expected_mode: the mode we expect

    """
    st = os.stat(file_name)
    actual_mode = stat.S_IMODE(st.st_mode)
    self.assertEqual(actual_mode, expected_mode)

  @staticmethod
  def _TestDataFilename(name):
    """Returns the filename of a given test data file.

    @type name: str
    @param name: the 'base' of the file name, as present in
        the test/data directory
    @rtype: str
    @return: the full path to the filename, such that it can
        be used in 'make distcheck' rules

    """
    return "%s/test/data/%s" % (GetSourceDir(), name)

  @classmethod
  def _ReadTestData(cls, name):
    """Returns the contents of a test data file.

    This is just a very simple wrapper over utils.ReadFile with the
    proper test file name.

    """

    return utils.ReadFile(cls._TestDataFilename(name))

  def _CreateTempFile(self):
    """Creates a temporary file and adds it to the internal cleanup list.

    This method simplifies the creation and cleanup of temporary files
    during tests.

    """
    fh, fname = tempfile.mkstemp(prefix="ganeti-test", suffix=".tmp")
    os.close(fh)
    self._temp_files.append(fname)
    return fname
