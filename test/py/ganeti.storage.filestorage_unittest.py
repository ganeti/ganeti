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
    """Tests that an error is raised when the given file is not existing.

    """
    self.assertRaises(errors.CommandError, filestorage.GetSpaceInfo,
                      "/path/does/not/exist/")

  def testSpaceInfoPathValid(self):
    """Tests that the 'df' command is run if the file is valid.

    """
    info = filestorage.GetSpaceInfo("/")

  def testParseDfOutputValidInput(self):
    """Tests that parsing of the output of 'df' works correctly.

    """
    valid_df_output = \
      "Filesystem             1M-blocks   Used Available Use% Mounted on\n" \
      "/dev/mapper/sysvg-root   161002M 58421M    94403M  39% /"
    expected_size = 161002
    expected_free = 94403

    (size, free) = filestorage._ParseDfResult(valid_df_output)
    self.assertEqual(expected_size, size,
                     "Calculation of total size is incorrect.")
    self.assertEqual(expected_free, free,
                     "Calculation of free space is incorrect.")


  def testParseDfOutputInvalidInput(self):
    """Tests that parsing of the output of 'df' works correctly when invalid
       input is given.

    """
    invalid_output_header_missing = \
      "/dev/mapper/sysvg-root   161002M 58421M    94403M  39% /"
    invalid_output_dataline_missing = \
      "Filesystem             1M-blocks   Used Available Use% Mounted on\n"
    invalid_output_wrong_num_columns = \
      "Filesystem             1M-blocks Available\n" \
      "/dev/mapper/sysvg-root   161002M    94403M"
    invalid_output_units_wrong = \
      "Filesystem             1M-blocks   Used Available Use% Mounted on\n" \
      "/dev/mapper/sysvg-root   161002G 58421G    94403G  39% /"
    invalid_output_units_missing = \
      "Filesystem             1M-blocks   Used Available Use% Mounted on\n" \
      "/dev/mapper/sysvg-root    161002  58421     94403  39% /"
    invalid_outputs = [invalid_output_header_missing,
                       invalid_output_dataline_missing,
                       invalid_output_wrong_num_columns,
                       invalid_output_units_wrong,
                       invalid_output_units_missing]

    for output in invalid_outputs:
      self.assertRaises(errors.CommandError, filestorage._ParseDfResult, output)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
