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
import shutil

import testutils
import mocks

from ganeti import constants
from ganeti import utils
from ganeti import ssh
from ganeti import errors


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


class TestGetUserFiles(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  @staticmethod
  def _GetNoHomedir(_):
    return None

  def _GetTempHomedir(self, _):
    return self.tmpdir

  def testNonExistantUser(self):
    for kind in constants.SSHK_ALL:
      self.assertRaises(errors.OpExecError, ssh.GetUserFiles, "example",
                        kind=kind, _homedir_fn=self._GetNoHomedir)

  def testUnknownKind(self):
    kind = "something-else"
    assert kind not in constants.SSHK_ALL
    self.assertRaises(errors.ProgrammerError, ssh.GetUserFiles, "example4645",
                      kind=kind, _homedir_fn=self._GetTempHomedir)

    self.assertEqual(os.listdir(self.tmpdir), [])

  def testNoSshDirectory(self):
    for kind in constants.SSHK_ALL:
      self.assertRaises(errors.OpExecError, ssh.GetUserFiles, "example29694",
                        kind=kind, _homedir_fn=self._GetTempHomedir)
      self.assertEqual(os.listdir(self.tmpdir), [])

  def testSshIsFile(self):
    utils.WriteFile(os.path.join(self.tmpdir, ".ssh"), data="")
    for kind in constants.SSHK_ALL:
      self.assertRaises(errors.OpExecError, ssh.GetUserFiles, "example26237",
                        kind=kind, _homedir_fn=self._GetTempHomedir)
      self.assertEqual(os.listdir(self.tmpdir), [".ssh"])

  def testMakeSshDirectory(self):
    sshdir = os.path.join(self.tmpdir, ".ssh")

    self.assertEqual(os.listdir(self.tmpdir), [])

    for kind in constants.SSHK_ALL:
      ssh.GetUserFiles("example20745", mkdir=True, kind=kind,
                       _homedir_fn=self._GetTempHomedir)
      self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
      self.assertEqual(os.stat(sshdir).st_mode & 0777, 0700)

  def testFilenames(self):
    sshdir = os.path.join(self.tmpdir, ".ssh")

    os.mkdir(sshdir)

    for kind in constants.SSHK_ALL:
      result = ssh.GetUserFiles("example15103", mkdir=False, kind=kind,
                                _homedir_fn=self._GetTempHomedir)
      self.assertEqual(result, [
        os.path.join(self.tmpdir, ".ssh", "id_%s" % kind),
        os.path.join(self.tmpdir, ".ssh", "id_%s.pub" % kind),
        os.path.join(self.tmpdir, ".ssh", "authorized_keys"),
        ])

      self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
      self.assertEqual(os.listdir(sshdir), [])

  def testNoDirCheck(self):
    self.assertEqual(os.listdir(self.tmpdir), [])

    for kind in constants.SSHK_ALL:
      ssh.GetUserFiles("example14528", mkdir=False, dircheck=False, kind=kind,
                       _homedir_fn=self._GetTempHomedir)
      self.assertEqual(os.listdir(self.tmpdir), [])

  def testGetAllUserFiles(self):
    result = ssh.GetAllUserFiles("example7475", mkdir=False, dircheck=False,
                                 _homedir_fn=self._GetTempHomedir)
    self.assertEqual(result,
      (os.path.join(self.tmpdir, ".ssh", "authorized_keys"), {
        constants.SSHK_RSA:
          (os.path.join(self.tmpdir, ".ssh", "id_rsa"),
           os.path.join(self.tmpdir, ".ssh", "id_rsa.pub")),
        constants.SSHK_DSA:
          (os.path.join(self.tmpdir, ".ssh", "id_dsa"),
           os.path.join(self.tmpdir, ".ssh", "id_dsa.pub")),
      }))
    self.assertEqual(os.listdir(self.tmpdir), [])

  def testGetAllUserFilesNoDirectoryNoMkdir(self):
    self.assertRaises(errors.OpExecError, ssh.GetAllUserFiles,
                      "example17270", mkdir=False, dircheck=True,
                      _homedir_fn=self._GetTempHomedir)
    self.assertEqual(os.listdir(self.tmpdir), [])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
