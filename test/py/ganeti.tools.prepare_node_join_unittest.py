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


"""Script for testing ganeti.tools.prepare_node_join"""

import unittest
import shutil
import tempfile
import os.path

from ganeti import errors
from ganeti import constants
from ganeti import serializer
from ganeti import pathutils
from ganeti import compat
from ganeti import utils
from ganeti.tools import prepare_node_join
from ganeti.tools import common

import testutils


_JoinError = prepare_node_join.JoinError
_DATA_CHECK = prepare_node_join._DATA_CHECK

class TestLoadData(unittest.TestCase):
  def testNoJson(self):
    self.assertRaises(errors.ParseError, common.LoadData, "", _DATA_CHECK)
    self.assertRaises(errors.ParseError, common.LoadData, "}", _DATA_CHECK)

  def testInvalidDataStructure(self):
    raw = serializer.DumpJson({
      "some other thing": False,
      })
    self.assertRaises(errors.ParseError, common.LoadData, raw, _DATA_CHECK)

    raw = serializer.DumpJson([])
    self.assertRaises(errors.ParseError, common.LoadData, raw, _DATA_CHECK)

  def testEmptyDict(self):
    raw = serializer.DumpJson({})
    self.assertEqual(common.LoadData(raw, _DATA_CHECK), {})

  def testValidData(self):
    key_list = [[constants.SSHK_DSA, "private foo", "public bar"]]
    data_dict = {
      constants.SSHS_CLUSTER_NAME: "Skynet",
      constants.SSHS_SSH_HOST_KEY: key_list,
      constants.SSHS_SSH_ROOT_KEY: key_list,
      constants.SSHS_SSH_AUTHORIZED_KEYS:
        {"nodeuuid01234": ["foo"],
         "nodeuuid56789": ["bar"]}}
    raw = serializer.DumpJson(data_dict)
    self.assertEqual(common.LoadData(raw, _DATA_CHECK), data_dict)


class TestVerifyCertificate(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoCert(self):
    common.VerifyCertificate({}, error_fn=prepare_node_join.JoinError,
                             _verify_fn=NotImplemented)

  def testGivenPrivateKey(self):
    cert_filename = testutils.TestDataFilename("cert2.pem")
    cert_pem = utils.ReadFile(cert_filename)

    self.assertRaises(_JoinError, common._VerifyCertificate,
                      cert_pem, _JoinError, _check_fn=NotImplemented)

  def testInvalidCertificate(self):
    self.assertRaises(errors.X509CertError,
                      common._VerifyCertificate,
                      "Something that's not a certificate",
                      _JoinError, _check_fn=NotImplemented)

  @staticmethod
  def _Check(cert):
    assert cert.get_subject()

  def testSuccessfulCheck(self):
    cert_filename = testutils.TestDataFilename("cert1.pem")
    cert_pem = utils.ReadFile(cert_filename)
    common._VerifyCertificate(cert_pem, _JoinError,
      _check_fn=self._Check)


class TestVerifyClusterName(unittest.TestCase):
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoName(self):
    self.assertRaises(_JoinError, common.VerifyClusterName,
                      {}, _JoinError, _verify_fn=NotImplemented)

  @staticmethod
  def _FailingVerify(name):
    assert name == "cluster.example.com"
    raise errors.GenericError()

  def testFailingVerification(self):
    data = {
      constants.SSHS_CLUSTER_NAME: "cluster.example.com",
      }

    self.assertRaises(errors.GenericError, common.VerifyClusterName,
                      data, _JoinError, _verify_fn=self._FailingVerify)


class TestUpdateSshDaemon(unittest.TestCase):
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

    self.keyfiles = {
      constants.SSHK_RSA:
        (utils.PathJoin(self.tmpdir, "rsa.private"),
         utils.PathJoin(self.tmpdir, "rsa.public")),
      constants.SSHK_DSA:
        (utils.PathJoin(self.tmpdir, "dsa.private"),
         utils.PathJoin(self.tmpdir, "dsa.public")),
      }

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoKeys(self):
    data_empty_keys = {
      constants.SSHS_SSH_HOST_KEY: [],
      }

    for data in [{}, data_empty_keys]:
      for dry_run in [False, True]:
        prepare_node_join.UpdateSshDaemon(data, dry_run,
                                          _runcmd_fn=NotImplemented,
                                          _keyfiles=NotImplemented)
    self.assertEqual(os.listdir(self.tmpdir), [])

  def _TestDryRun(self, data):
    prepare_node_join.UpdateSshDaemon(data, True, _runcmd_fn=NotImplemented,
                                      _keyfiles=self.keyfiles)
    self.assertEqual(os.listdir(self.tmpdir), [])

  def testDryRunRsa(self):
    self._TestDryRun({
      constants.SSHS_SSH_HOST_KEY: [
        (constants.SSHK_RSA, "rsapriv", "rsapub"),
        ],
      })

  def testDryRunDsa(self):
    self._TestDryRun({
      constants.SSHS_SSH_HOST_KEY: [
        (constants.SSHK_DSA, "dsapriv", "dsapub"),
        ],
      })

  def _RunCmd(self, fail, cmd, interactive=NotImplemented):
    self.assertTrue(interactive)
    self.assertEqual(cmd, [pathutils.DAEMON_UTIL, "reload-ssh-keys"])
    if fail:
      exit_code = constants.EXIT_FAILURE
    else:
      exit_code = constants.EXIT_SUCCESS
    return utils.RunResult(exit_code, None, "stdout", "stderr",
                           utils.ShellQuoteArgs(cmd),
                           NotImplemented, NotImplemented)

  def _TestUpdate(self, failcmd):
    data = {
      constants.SSHS_SSH_HOST_KEY: [
        (constants.SSHK_DSA, "dsapriv", "dsapub"),
        (constants.SSHK_RSA, "rsapriv", "rsapub"),
        ],
      }
    runcmd_fn = compat.partial(self._RunCmd, failcmd)
    if failcmd:
      self.assertRaises(_JoinError, prepare_node_join.UpdateSshDaemon,
                        data, False, _runcmd_fn=runcmd_fn,
                        _keyfiles=self.keyfiles)
    else:
      prepare_node_join.UpdateSshDaemon(data, False, _runcmd_fn=runcmd_fn,
                                        _keyfiles=self.keyfiles)
    self.assertEqual(sorted(os.listdir(self.tmpdir)), sorted([
      "rsa.public", "rsa.private",
      "dsa.public", "dsa.private",
      ]))
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.tmpdir, "rsa.public")),
                     "rsapub")
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.tmpdir, "rsa.private")),
                     "rsapriv")
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.tmpdir, "dsa.public")),
                     "dsapub")
    self.assertEqual(utils.ReadFile(utils.PathJoin(self.tmpdir, "dsa.private")),
                     "dsapriv")

  def testSuccess(self):
    self._TestUpdate(False)

  def testFailure(self):
    self._TestUpdate(True)


class TestUpdateSshRoot(unittest.TestCase):
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()
    self.sshdir = utils.PathJoin(self.tmpdir, ".ssh")

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def _GetHomeDir(self, user):
    self.assertEqual(user, constants.SSH_LOGIN_USER)
    return self.tmpdir

  def testDryRun(self):
    data = {
      constants.SSHS_SSH_ROOT_KEY: [
        (constants.SSHK_RSA, "aaa", "bbb"),
        ]
      }

    prepare_node_join.UpdateSshRoot(data, True,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
    self.assertEqual(os.listdir(self.sshdir), [])

  def testUpdate(self):
    data = {
      constants.SSHS_SSH_ROOT_KEY: [
        (constants.SSHK_DSA, "privatedsa", "ssh-dss pubdsa"),
        ]
      }

    prepare_node_join.UpdateSshRoot(data, False,
                                    _homedir_fn=self._GetHomeDir)
    self.assertEqual(os.listdir(self.tmpdir), [".ssh"])
    self.assertEqual(sorted(os.listdir(self.sshdir)),
                     sorted(["authorized_keys", "id_dsa", "id_dsa.pub"]))
    self.assertTrue(utils.ReadFile(utils.PathJoin(self.sshdir, "id_dsa"))
                    is not None)
    pub_key = utils.ReadFile(utils.PathJoin(self.sshdir, "id_dsa.pub"))
    self.assertTrue(pub_key is not None)
    self.assertEquals(utils.ReadFile(utils.PathJoin(self.sshdir,
                                                    "authorized_keys")),
                      pub_key)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
