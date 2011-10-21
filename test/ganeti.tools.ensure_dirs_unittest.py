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

from ganeti.tools import ensure_dirs

import testutils


class TestEnsureDirsFunctions(unittest.TestCase):
  def testPaths(self):
    paths = [(path[0], path[1]) for path in ensure_dirs.GetPaths()]

    seen = []
    last_dirname = ""
    for path, pathtype in paths:
      self.assertTrue(pathtype in ensure_dirs.ALL_TYPES)
      dirname = os.path.dirname(path)
      if dirname != last_dirname or pathtype == ensure_dirs.DIR:
        if pathtype == ensure_dirs.FILE:
          self.assertFalse(dirname in seen,
                           msg="path %s; dirname %s seen in %s" % (path,
                                                                   dirname,
                                                                   seen))
          last_dirname = dirname
          seen.append(dirname)
        elif pathtype == ensure_dirs.DIR:
          self.assertFalse(path in seen)
          last_dirname = path
          seen.append(path)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
