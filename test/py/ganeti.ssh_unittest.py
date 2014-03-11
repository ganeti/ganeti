#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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
        "%s ssh-rsa %s\n%s ssh-dss %s\n" %
        (cfg.GetClusterName(), mocks.FAKE_CLUSTER_KEY,
         cfg.GetClusterName(), mocks.FAKE_CLUSTER_KEY))


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


class TestSshKeys(testutils.GanetiTestCase):
  """Test case for the AddAuthorizedKey function"""

  KEY_A = "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a"
  KEY_B = ('command="/usr/bin/fooserver -t --verbose",from="198.51.100.4" '
           "ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b")

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpname = self._CreateTempFile()
    handle = open(self.tmpname, "w")
    try:
      handle.write("%s\n" % TestSshKeys.KEY_A)
      handle.write("%s\n" % TestSshKeys.KEY_B)
    finally:
      handle.close()

  def testAddingNewKey(self):
    ssh.AddAuthorizedKey(self.tmpname,
                         "ssh-dss AAAAB3NzaC1kc3MAAACB root@test")

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n")

  def testAddingAlmostButNotCompletelyTheSameKey(self):
    ssh.AddAuthorizedKey(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@test")

    # Only significant fields are compared, therefore the key won't be
    # updated/added
    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")

  def testAddingExistingKeyWithSomeMoreSpaces(self):
    ssh.AddAuthorizedKey(self.tmpname,
      "ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a")
    ssh.AddAuthorizedKey(self.tmpname,
      "ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22")

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22\n")

  def testRemovingExistingKeyWithSomeMoreSpaces(self):
    ssh.RemoveAuthorizedKey(self.tmpname,
      "ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a")

    self.assertFileContent(self.tmpname,
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")

  def testRemovingNonExistingKey(self):
    ssh.RemoveAuthorizedKey(self.tmpname,
      "ssh-dss  AAAAB3Nsdfj230xxjxJjsjwjsjdjU   root@test")

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")


class TestPublicSshKeys(testutils.GanetiTestCase):
  """Test case for the handling of the list of public ssh keys."""

  KEY_A = "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a"
  KEY_B = "ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b"
  UUID_1 = "123-456"
  UUID_2 = "789-ABC"

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

  def testAddingAndRemovingPubKey(self):
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_1, self.KEY_A, key_file=pub_key_file)
    ssh.AddPublicKey(self.UUID_2, self.KEY_B, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "789-ABC ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

    ssh.RemovePublicKey(self.UUID_2, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n")

  def testAddingExistingPubKey(self):
    expected_file_content = \
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n" + \
      "789-ABC ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n"
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_1, self.KEY_A, key_file=pub_key_file)
    ssh.AddPublicKey(self.UUID_2, self.KEY_B, key_file=pub_key_file)
    self.assertFileContent(pub_key_file, expected_file_content)

    ssh.AddPublicKey(self.UUID_1, self.KEY_A, key_file=pub_key_file)
    self.assertFileContent(pub_key_file, expected_file_content)

    ssh.AddPublicKey(self.UUID_1, self.KEY_B, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "789-ABC ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n"
      "123-456 ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

  def testRemoveNonexistingKey(self):
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_1, self.KEY_B, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

    ssh.RemovePublicKey(self.UUID_2, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

  def testRemoveAllExistingKeys(self):
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_1, self.KEY_A, key_file=pub_key_file)
    ssh.AddPublicKey(self.UUID_1, self.KEY_B, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "123-456 ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

    ssh.RemovePublicKey(self.UUID_1, key_file=pub_key_file)
    self.assertFileContent(pub_key_file, "")

  def testRemoveKeyFromEmptyFile(self):
    pub_key_file = self._CreateTempFile()
    ssh.RemovePublicKey(self.UUID_2, key_file=pub_key_file)
    self.assertFileContent(pub_key_file, "")

  def testRetrieveKeys(self):
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_1, self.KEY_A, key_file=pub_key_file)
    ssh.AddPublicKey(self.UUID_2, self.KEY_B, key_file=pub_key_file)
    result = ssh.QueryPubKeyFile(self.UUID_1, key_file=pub_key_file)
    self.assertEquals([self.KEY_A], result[self.UUID_1])

    target_uuids = [self.UUID_1, self.UUID_2, "non-existing-UUID"]
    result = ssh.QueryPubKeyFile(target_uuids, key_file=pub_key_file)
    self.assertEquals([self.KEY_A], result[self.UUID_1])
    self.assertEquals([self.KEY_B], result[self.UUID_2])
    self.assertEquals(2, len(result))

  def testReplaceNameByUuid(self):
    pub_key_file = self._CreateTempFile()
    name = "my.precious.node"
    ssh.AddPublicKey(name, self.KEY_A, key_file=pub_key_file)
    ssh.AddPublicKey(self.UUID_2, self.KEY_A, key_file=pub_key_file)
    ssh.AddPublicKey(name, self.KEY_B, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "my.precious.node ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "789-ABC ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "my.precious.node ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

    ssh.ReplaceNameByUuid(self.UUID_1, name, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "789-ABC ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "123-456 ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n")

  def testParseEmptyLines(self):
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_1, self.KEY_A, key_file=pub_key_file)

    # Add an empty line
    fd = open(pub_key_file, 'a')
    fd.write("\n")
    fd.close()

    ssh.AddPublicKey(self.UUID_2, self.KEY_B, key_file=pub_key_file)

    # Add a whitespace line
    fd = open(pub_key_file, 'a')
    fd.write("    \n")
    fd.close()

    result = ssh.QueryPubKeyFile(self.UUID_1, key_file=pub_key_file)
    self.assertEquals([self.KEY_A], result[self.UUID_1])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
