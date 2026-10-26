#!/usr/bin/python3
#

# Copyright (C) 2011 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


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
