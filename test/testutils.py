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
import unittest

from ganeti import utils


class GanetiTestCase(unittest.TestCase):
  def assertFileContent(self, file_name, expected_content):
    """Checks the content of a file is what we expect.

    @type file_name: str
    @param file_name: the file whose contents we should check
    @type expected_content: str
    @param expected_content: the content we expect

    """
    actual_content = utils.ReadFile(file_name)
    self.assertEqual(actual_content, expected_content)

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
    prefix = os.environ.get("srcdir", "")
    if prefix:
      prefix = prefix + "/test/"
    return "%sdata/%s" % (prefix, name)

  @classmethod
  def _ReadTestData(cls, name):
    """Returns the contents of a test data file.

    This is just a very simple wrapper over utils.ReadFile with the
    proper test file name.

    """

    return utils.ReadFile(cls._TestDataFilename(name))
