#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


class TestCommonRestrictedCmdCheck(testutils.GanetiTestCase):
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
    (status, value) = backend._CommonRestrictedCmdCheck(tmpname, None)
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

      (status, errmsg) = backend._CommonRestrictedCmdCheck(tmpname, None)
      self.assertFalse(status)
      self.assertTrue("foobar' is not owned by " in errmsg)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
