#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.backend (tests requiring root access)"""

import os
import tempfile
import shutil
import errno

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import backend

import testutils


class TestWriteFile(testutils.GanetiTestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _PrepareTest(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    os.mkdir(tmpname)
    os.chmod(tmpname, 0700)
    return tmpname

  def testCorrectOwner(self):
    tmpname = self._PrepareTest()

    os.chown(tmpname, 0, 0)
    (status, value) = backend._CommonRemoteCommandCheck(tmpname, None)
    self.assertTrue(status)
    self.assertTrue(value)

  def testWrongOwner(self):
    tmpname = self._PrepareTest()

    tests = [
      (1, 0),
      (0, 1),
      (100, 50),
      ]

    for (uid, gid) in tests:
      self.assertFalse(uid == os.getuid() and gid == os.getgid())
      os.chown(tmpname, uid, gid)

      (status, errmsg) = backend._CommonRemoteCommandCheck(tmpname, None)
      self.assertFalse(status)
      self.assertTrue("foobar' is not owned by " in errmsg)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
