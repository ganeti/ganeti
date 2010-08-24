#!/usr/bin/python
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


"""Script for unittesting the ssh module"""

import os
import tempfile
import unittest

import testutils
import mocks

from ganeti import constants
from ganeti import utils
from ganeti import ssh


class TestKnownHosts(testutils.GanetiTestCase):
  """Test case for function writing the known_hosts file"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpfile = self._CreateTempFile()

  def test(self):
    cfg = mocks.FakeConfig()
    ssh.WriteKnownHostsFile(cfg, self.tmpfile)
    self.assertFileContent(self.tmpfile,
        "%s ssh-rsa %s\n" % (cfg.GetClusterName(),
                             mocks.FAKE_CLUSTER_KEY))

  def testFormatParamikoFingerprintCorrect(self):
    self.assertEqual(ssh.FormatParamikoFingerprint("C0Ffee"), "c0:ff:ee")

  def testFormatParamikoFingerprintNotDividableByTwo(self):
    self.assertRaises(AssertionError, ssh.FormatParamikoFingerprint, "C0Ffe")


if __name__ == '__main__':
  testutils.GanetiTestProgram()
