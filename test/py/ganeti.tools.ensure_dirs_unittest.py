#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.tools.ensure_dirs"""

import unittest
import os.path

from ganeti import utils
from ganeti.tools import ensure_dirs

import testutils


class TestGetPaths(unittest.TestCase):
  def testEntryOrder(self):
    paths = [(path[0], path[1]) for path in ensure_dirs.GetPaths()]

    # Directories for which permissions have been set
    seen = set()

    # Current directory (changes when an entry of type C{DIR} or C{QUEUE_DIR}
    # is encountered)
    current_dir = None

    for (path, pathtype) in paths:
      self.assertTrue(pathtype in ensure_dirs.ALL_TYPES)
      self.assertTrue(utils.IsNormAbsPath(path),
                      msg=("Path '%s' is not absolute and/or normalized" %
                           path))

      dirname = os.path.dirname(path)

      if pathtype == ensure_dirs.DIR:
        self.assertFalse(path in seen,
                         msg=("Directory '%s' was seen before" % path))
        current_dir = path
        seen.add(path)

      elif pathtype == ensure_dirs.QUEUE_DIR:
        self.assertTrue(dirname in seen,
                        msg=("Queue directory '%s' was not seen before" %
                             path))
        current_dir = path

      elif pathtype == ensure_dirs.FILE:
        self.assertFalse(current_dir is None)
        self.assertTrue(dirname in seen,
                        msg=("Directory '%s' of path '%s' has not been seen"
                             " yet" % (dirname, path)))
        self.assertTrue((utils.IsBelowDir(current_dir, path) and
                         current_dir == dirname),
                        msg=("File '%s' not below current directory '%s'" %
                             (path, current_dir)))

      else:
        self.fail("Unknown path type '%s'" % (pathtype, ))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
