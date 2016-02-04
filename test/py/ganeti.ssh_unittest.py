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
        constants.SSHK_ECDSA:
          (os.path.join(self.tmpdir, ".ssh", "id_ecdsa"),
           os.path.join(self.tmpdir, ".ssh", "id_ecdsa.pub")),
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

  def testHasAuthorizedKey(self):
    self.assertTrue(ssh.HasAuthorizedKey(self.tmpname, self.KEY_A))
    self.assertFalse(ssh.HasAuthorizedKey(
      self.tmpname, "I am the key of the pink bunny!"))

  def testAddingNewKey(self):
    ssh.AddAuthorizedKey(self.tmpname,
                         "ssh-dss AAAAB3NzaC1kc3MAAACB root@test")

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n")

  def testAddingDuplicateKeys(self):
    ssh.AddAuthorizedKey(self.tmpname,
                         "ssh-dss AAAAB3NzaC1kc3MAAACB root@test")
    ssh.AddAuthorizedKeys(self.tmpname,
                          ["ssh-dss AAAAB3NzaC1kc3MAAACB root@test",
                           "ssh-dss AAAAB3NzaC1kc3MAAACB root@test"])

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n")

  def testAddingSeveralKeysAtOnce(self):
    ssh.AddAuthorizedKeys(self.tmpname, ["aaa", "bbb", "ccc"])
    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "aaa\nbbb\nccc\n")
    ssh.AddAuthorizedKeys(self.tmpname, ["bbb", "ddd", "eee"])
    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "aaa\nbbb\nccc\nddd\neee\n")

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

  def testAddingNewKeys(self):
    ssh.AddAuthorizedKeys(self.tmpname,
                          ["ssh-dss AAAAB3NzaC1kc3MAAACB root@test"])
    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n")

    ssh.AddAuthorizedKeys(self.tmpname,
                          ["ssh-dss AAAAB3asdfasdfaYTUCB laracroft@test",
                           "ssh-dss AasdfliuobaosfMAAACB frodo@test"])
    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n"
      "ssh-dss AAAAB3asdfasdfaYTUCB laracroft@test\n"
      "ssh-dss AasdfliuobaosfMAAACB frodo@test\n")

  def testOtherKeyTypes(self):
    key_rsa = "ssh-rsa AAAAimnottypingallofthathere0jfJs22 test@test"
    key_ed25519 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOlcZ6cpQTGow0LZECRHWn9"\
                  "7Yvn16J5un501T/RcbfuF fast@secure"
    key_ecdsa = "ecdsa-sha2-nistp256 AAAAE2VjZHNtoolongk/TNhVbEg= secure@secure"

    def _ToFileContent(keys):
      return '\n'.join(keys) + '\n'

    ssh.AddAuthorizedKeys(self.tmpname, [key_rsa, key_ed25519, key_ecdsa])
    self.assertFileContent(self.tmpname,
                           _ToFileContent([self.KEY_A, self.KEY_B, key_rsa,
                                           key_ed25519, key_ecdsa]))

    ssh.RemoveAuthorizedKey(self.tmpname, key_ed25519)
    self.assertFileContent(self.tmpname,
                           _ToFileContent([self.KEY_A, self.KEY_B, key_rsa,
                                           key_ecdsa]))

    ssh.RemoveAuthorizedKey(self.tmpname, key_rsa)
    ssh.RemoveAuthorizedKey(self.tmpname, key_ecdsa)
    self.assertFileContent(self.tmpname,
                           _ToFileContent([self.KEY_A, self.KEY_B]))


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

    # Query all keys
    target_uuids = None
    result = ssh.QueryPubKeyFile(target_uuids, key_file=pub_key_file)
    self.assertEquals([self.KEY_A], result[self.UUID_1])
    self.assertEquals([self.KEY_B], result[self.UUID_2])

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

  def testClearPubKeyFile(self):
    pub_key_file = self._CreateTempFile()
    ssh.AddPublicKey(self.UUID_2, self.KEY_A, key_file=pub_key_file)
    ssh.ClearPubKeyFile(key_file=pub_key_file)
    self.assertFileContent(pub_key_file, "")

  def testOverridePubKeyFile(self):
    pub_key_file = self._CreateTempFile()
    key_map = {self.UUID_1: [self.KEY_A, self.KEY_B],
               self.UUID_2: [self.KEY_A]}
    ssh.OverridePubKeyFile(key_map, key_file=pub_key_file)
    self.assertFileContent(pub_key_file,
      "123-456 ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      "123-456 ssh-dss BAasjkakfa234SFSFDA345462AAAB root@key-b\n"
      "789-ABC ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n")


class TestGetUserFiles(testutils.GanetiTestCase):

  _PRIV_KEY = "my private key"
  _PUB_KEY = "my public key"
  _AUTH_KEYS = "a\nb\nc"

  def _setUpFakeKeys(self):
    ssh_tmpdir = os.path.join(self.tmpdir, ".ssh")
    os.makedirs(ssh_tmpdir)

    self.priv_filename = os.path.join(ssh_tmpdir, "id_dsa")
    utils.WriteFile(self.priv_filename, data=self._PRIV_KEY)

    self.pub_filename = os.path.join(ssh_tmpdir, "id_dsa.pub")
    utils.WriteFile(self.pub_filename, data=self._PUB_KEY)

    self.auth_filename = os.path.join(ssh_tmpdir, "authorized_keys")
    utils.WriteFile(self.auth_filename, data=self._AUTH_KEYS)

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()
    self._setUpFakeKeys()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _GetTempHomedir(self, _):
    return self.tmpdir

  def testNewKeysOverrideOldKeys(self):
    ssh.InitSSHSetup("dsa", 1024, _homedir_fn=self._GetTempHomedir)
    self.assertFileContentNotEqual(self.priv_filename, self._PRIV_KEY)
    self.assertFileContentNotEqual(self.pub_filename, self._PUB_KEY)

  def testSuffix(self):
    suffix = "_pinkbunny"
    ssh.InitSSHSetup("dsa", 1024, _homedir_fn=self._GetTempHomedir,
                     _suffix=suffix)
    self.assertFileContent(self.priv_filename, self._PRIV_KEY)
    self.assertFileContent(self.pub_filename, self._PUB_KEY)
    self.assertTrue(os.path.exists(self.priv_filename + suffix))
    self.assertTrue(os.path.exists(self.priv_filename + suffix + ".pub"))


class TestDetermineKeyBits(testutils.GanetiTestCase):
  def testCompleteness(self):
    self.assertEquals(constants.SSHK_ALL,
                      frozenset(ssh.SSH_KEY_VALID_BITS.keys()))

  def testAdoptDefault(self):
    self.assertEquals(2048, ssh.DetermineKeyBits("rsa", None, None, None))
    self.assertEquals(1024, ssh.DetermineKeyBits("dsa", None, None, None))

  def testAdoptOldKeySize(self):
    self.assertEquals(4098, ssh.DetermineKeyBits("rsa", None, "rsa", 4098))
    self.assertEquals(2048, ssh.DetermineKeyBits("rsa", None, "dsa", 1024))

  def testDsaSpecificValues(self):
    self.assertRaises(errors.OpPrereqError, ssh.DetermineKeyBits, "dsa", 2048,
                      None, None)
    self.assertRaises(errors.OpPrereqError, ssh.DetermineKeyBits, "dsa", 512,
                      None, None)
    self.assertEquals(1024, ssh.DetermineKeyBits("dsa", None, None, None))

  def testEcdsaSpecificValues(self):
    self.assertRaises(errors.OpPrereqError, ssh.DetermineKeyBits, "ecdsa", 2048,
                      None, None)
    for b in [256, 384, 521]:
      self.assertEquals(b, ssh.DetermineKeyBits("ecdsa", b, None, None))

  def testRsaSpecificValues(self):
    self.assertRaises(errors.OpPrereqError, ssh.DetermineKeyBits, "dsa", 766,
                      None, None)
    for b in [768, 769, 2048, 2049, 4096]:
      self.assertEquals(b, ssh.DetermineKeyBits("rsa", b, None, None))


class TestManageLocalSshPubKeys(testutils.GanetiTestCase):
  """Test class for several methods handling local SSH keys.

  Methods covered are:
  - GetSshKeyFilenames
  - GetSshPubKeyFilename
  - ReplaceSshKeys
  - ReadLocalSshPubKeys

  These methods are covered in one test, because the preparations for
  their tests is identical and thus can be reused.

  """
  VISIBILITY_PRIVATE = "private"
  VISIBILITY_PUBLIC = "public"
  VISIBILITIES = frozenset([VISIBILITY_PRIVATE, VISIBILITY_PUBLIC])

  def _GenerateKey(self, key_id, visibility):
    assert visibility in self.VISIBILITIES
    return "I am the %s %s SSH key." % (visibility, key_id)

  def _GetKeyPath(self, key_file_basename):
     return os.path.join(self.tmpdir, key_file_basename)

  def _SetUpKeys(self):
    """Creates a fake SSH key for each type and with/without suffix."""
    self._key_file_dict = {}
    for key_type in constants.SSHK_ALL:
      for suffix in ["", self._suffix]:
        pub_key_filename = "id_%s%s.pub" % (key_type, suffix)
        priv_key_filename = "id_%s%s" % (key_type, suffix)

        pub_key_path = self._GetKeyPath(pub_key_filename)
        priv_key_path = self._GetKeyPath(priv_key_filename)

        utils.WriteFile(
            priv_key_path,
            data=self._GenerateKey(key_type + suffix, self.VISIBILITY_PRIVATE))

        utils.WriteFile(
            pub_key_path,
            data=self._GenerateKey(key_type + suffix, self.VISIBILITY_PUBLIC))

        # Fill key dict only for non-suffix keys
        # (as this is how it will be in the code)
        if not suffix:
          self._key_file_dict[key_type] = \
            (priv_key_path, pub_key_path)

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()
    self._suffix = "_suffix"
    self._SetUpKeys()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testReadAllPublicKeyFiles(self, mock_getalluserfiles):
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    keys = ssh.ReadLocalSshPubKeys([], suffix="")

    self.assertEqual(len(constants.SSHK_ALL), len(keys))
    for key_type in constants.SSHK_ALL:
      self.assertTrue(
          self._GenerateKey(key_type, self.VISIBILITY_PUBLIC) in keys)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testReadOnePublicKeyFile(self, mock_getalluserfiles):
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    keys = ssh.ReadLocalSshPubKeys([constants.SSHK_DSA], suffix="")

    self.assertEqual(1, len(keys))
    self.assertEqual(
        self._GenerateKey(constants.SSHK_DSA, self.VISIBILITY_PUBLIC),
        keys[0])

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testReadPublicKeyFilesWithSuffix(self, mock_getalluserfiles):
    key_types = [constants.SSHK_DSA, constants.SSHK_ECDSA]

    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    keys = ssh.ReadLocalSshPubKeys(key_types, suffix=self._suffix)

    self.assertEqual(2, len(keys))
    for key_id in [key_type + self._suffix for key_type in key_types]:
      self.assertTrue(
          self._GenerateKey(key_id, self.VISIBILITY_PUBLIC) in keys)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testGetSshKeyFilenames(self, mock_getalluserfiles):
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    priv, pub = ssh.GetSshKeyFilenames(constants.SSHK_DSA)

    self.assertEqual("id_dsa", os.path.basename(priv))
    self.assertNotEqual("id_dsa", priv)
    self.assertEqual("id_dsa.pub", os.path.basename(pub))
    self.assertNotEqual("id_dsa.pub", pub)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testGetSshKeyFilenamesWithSuffix(self, mock_getalluserfiles):
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    priv, pub = ssh.GetSshKeyFilenames(constants.SSHK_RSA, suffix=self._suffix)

    self.assertEqual("id_rsa_suffix", os.path.basename(priv))
    self.assertNotEqual("id_rsa_suffix", priv)
    self.assertEqual("id_rsa_suffix.pub", os.path.basename(pub))
    self.assertNotEqual("id_rsa_suffix.pub", pub)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testGetPubSshKeyFilename(self, mock_getalluserfiles):
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    pub = ssh.GetSshPubKeyFilename(constants.SSHK_DSA)
    pub_suffix = ssh.GetSshPubKeyFilename(
        constants.SSHK_DSA, suffix=self._suffix)

    self.assertEqual("id_dsa.pub", os.path.basename(pub))
    self.assertNotEqual("id_dsa.pub", pub)
    self.assertEqual("id_dsa_suffix.pub", os.path.basename(pub_suffix))
    self.assertNotEqual("id_dsa_suffix.pub", pub_suffix)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testReplaceSshKeys(self, mock_getalluserfiles):
    """Replace SSH keys without suffixes.

    Note: usually it does not really make sense to replace the DSA key
    by the RSA key. This is just to test the function without suffixes.

    """
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    ssh.ReplaceSshKeys(constants.SSHK_RSA, constants.SSHK_DSA)

    priv_key = utils.ReadFile(self._key_file_dict[constants.SSHK_DSA][0])
    pub_key = utils.ReadFile(self._key_file_dict[constants.SSHK_DSA][1])

    self.assertEqual("I am the private rsa SSH key.", priv_key)
    self.assertEqual("I am the public rsa SSH key.", pub_key)

  @testutils.patch_object(ssh, "GetAllUserFiles")
  def testReplaceSshKeysBySuffixedKeys(self, mock_getalluserfiles):
    """Replace SSH keys with keys from suffixed files.

    Note: usually it does not really make sense to replace the DSA key
    by the RSA key. This is just to test the function without suffixes.

    """
    mock_getalluserfiles.return_value = (None, self._key_file_dict)

    ssh.ReplaceSshKeys(constants.SSHK_DSA, constants.SSHK_DSA,
                       src_key_suffix=self._suffix)

    priv_key = utils.ReadFile(self._key_file_dict[constants.SSHK_DSA][0])
    pub_key = utils.ReadFile(self._key_file_dict[constants.SSHK_DSA][1])

    self.assertEqual("I am the private dsa_suffix SSH key.", priv_key)
    self.assertEqual("I am the public dsa_suffix SSH key.", pub_key)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
