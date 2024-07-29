#!/usr/bin/python3
#

# Copyright (C) 2014 Google Inc.
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


"""Script for testing ganeti.tools.ssh_update"""

import unittest
import shutil
import tempfile
import os.path

from ganeti import constants
from ganeti import utils
from ganeti.tools import ssh_update

import testutils


_JoinError = ssh_update.SshUpdateError
_DATA_CHECK = ssh_update._DATA_CHECK


class TestUpdateAuthorizedKeys(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()
    self.sshdir = utils.PathJoin(self.tmpdir, ".ssh")

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def _GetHomeDir(self, user):
    self.assertEqual(user, constants.SSH_LOGIN_USER)
    return self.tmpdir

  def testNoop(self):
    data_empty_keys = {}

    for data in [{}, data_empty_keys]:
      for dry_run in [False, True]:
        ssh_update.UpdateAuthorizedKeys(data, dry_run,
                                        _homedir_fn=NotImplemented)
    self.assertEqual(os.listdir(self.tmpdir), [])

  def testDryRun(self):
    data = {
      constants.SSHS_SSH_AUTHORIZED_KEYS: (constants.SSHS_ADD, {
        "node1" : ["key11", "key12", "key13"],
        "node2" : ["key21", "key22"]}),
      }

    ssh_update.UpdateAuthorizedKeys(data, True,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
    self.assertEqual(os.listdir(self.sshdir), [])

  def testAddAndRemove(self):
    data = {
      constants.SSHS_SSH_AUTHORIZED_KEYS: (constants.SSHS_ADD, {
        "node1": ["key11", "key12"],
        "node2": ["key21"]}),
      }

    ssh_update.UpdateAuthorizedKeys(data, False,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
    self.assertEqual(sorted(os.listdir(self.sshdir)),
                     sorted(["authorized_keys"]))
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.sshdir,
                                                   "authorized_keys")),
                     "key11\nkey12\nkey21\n")
    data = {
      constants.SSHS_SSH_AUTHORIZED_KEYS: (constants.SSHS_REMOVE, {
        "node1": ["key12"],
        "node2": ["key21"]}),
      }
    ssh_update.UpdateAuthorizedKeys(data, False,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.sshdir,
                                                   "authorized_keys")),
                     "key11\n")

  def testAddAndRemoveDuplicates(self):
    data = {
      constants.SSHS_SSH_AUTHORIZED_KEYS: (constants.SSHS_ADD, {
        "node1": ["key11", "key12"],
        "node2": ["key12"]}),
      }

    ssh_update.UpdateAuthorizedKeys(data, False,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
    self.assertEqual(sorted(os.listdir(self.sshdir)),
                     sorted(["authorized_keys"]))
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.sshdir,
                                                   "authorized_keys")),
                     "key11\nkey12\nkey12\n")
    data = {
      constants.SSHS_SSH_AUTHORIZED_KEYS: (constants.SSHS_REMOVE, {
        "node1": ["key12"]}),
      }
    ssh_update.UpdateAuthorizedKeys(data, False,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.sshdir,
                                                   "authorized_keys")),
                     "key11\n")


class TestUpdatePubKeyFile(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

  def testNoKeys(self):
    pub_key_file = self._CreateTempFile()
    data_empty_keys = {}

    for data in [{}, data_empty_keys]:
      for dry_run in [False, True]:
        ssh_update.UpdatePubKeyFile(data, dry_run,
                                    key_file=pub_key_file)
    self.assertEqual(utils.ReadFile(pub_key_file), "")

  def testAddAndRemoveKeys(self):
    pub_key_file = self._CreateTempFile()
    data = {
      constants.SSHS_SSH_PUBLIC_KEYS: (constants.SSHS_OVERRIDE, {
        "node1": ["key11", "key12"],
        "node2": ["key21"]}),
      }
    ssh_update.UpdatePubKeyFile(data, False, key_file=pub_key_file)
    self.assertEqual(utils.ReadFile(pub_key_file),
      "node1 key11\nnode1 key12\nnode2 key21\n")
    data = {
      constants.SSHS_SSH_PUBLIC_KEYS: (constants.SSHS_REMOVE, {
        "node1": ["key12"],
        "node3": ["key21"],
        "node4": ["key33"]}),
      }
    ssh_update.UpdatePubKeyFile(data, False, key_file=pub_key_file)
    self.assertEqual(utils.ReadFile(pub_key_file),
     "node2 key21\n")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
