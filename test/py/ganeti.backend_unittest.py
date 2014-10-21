#!/usr/bin/python
#

# Copyright (C) 2010, 2013 Google Inc.
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


"""Script for testing ganeti.backend"""

import copy
import mock
import os
import shutil
import tempfile
import testutils
import unittest

from ganeti import backend
from ganeti import constants
from ganeti import errors
from ganeti import hypervisor
from ganeti import netutils
from ganeti import objects
from ganeti import pathutils
from ganeti import ssh
from ganeti import utils


class TestX509Certificates(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def test(self):
    (name, cert_pem) = backend.CreateX509Certificate(300, cryptodir=self.tmpdir)

    self.assertEqual(utils.ReadFile(os.path.join(self.tmpdir, name,
                                                 backend._X509_CERT_FILE)),
                     cert_pem)
    self.assert_(0 < os.path.getsize(os.path.join(self.tmpdir, name,
                                                  backend._X509_KEY_FILE)))

    (name2, cert_pem2) = \
      backend.CreateX509Certificate(300, cryptodir=self.tmpdir)

    backend.RemoveX509Certificate(name, cryptodir=self.tmpdir)
    backend.RemoveX509Certificate(name2, cryptodir=self.tmpdir)

    self.assertEqual(utils.ListVisibleFiles(self.tmpdir), [])

  def testNonEmpty(self):
    (name, _) = backend.CreateX509Certificate(300, cryptodir=self.tmpdir)

    utils.WriteFile(utils.PathJoin(self.tmpdir, name, "hello-world"),
                    data="Hello World")

    self.assertRaises(backend.RPCFail, backend.RemoveX509Certificate,
                      name, cryptodir=self.tmpdir)

    self.assertEqual(utils.ListVisibleFiles(self.tmpdir), [name])


class TestGetCryptoTokens(testutils.GanetiTestCase):

  def setUp(self):
    self._get_digest_fn_orig = utils.GetCertificateDigest
    self._create_digest_fn_orig = utils.GenerateNewSslCert
    self._ssl_digest = "12345"
    utils.GetCertificateDigest = mock.Mock(
      return_value=self._ssl_digest)
    utils.GenerateNewSslCert = mock.Mock()

  def tearDown(self):
    utils.GetCertificateDigest = self._get_digest_fn_orig
    utils.GenerateNewSslCert = self._create_digest_fn_orig

  def testGetSslToken(self):
    result = backend.GetCryptoTokens(
      [(constants.CRYPTO_TYPE_SSL_DIGEST, constants.CRYPTO_ACTION_GET, None)])
    self.assertTrue((constants.CRYPTO_TYPE_SSL_DIGEST, self._ssl_digest)
                    in result)

  def testCreateSslToken(self):
    result = backend.GetCryptoTokens(
      [(constants.CRYPTO_TYPE_SSL_DIGEST, constants.CRYPTO_ACTION_CREATE,
        {constants.CRYPTO_OPTION_SERIAL_NO: 42})])
    self.assertTrue((constants.CRYPTO_TYPE_SSL_DIGEST, self._ssl_digest)
                    in result)
    self.assertTrue(utils.GenerateNewSslCert.assert_calls().once())

  def testCreateSslTokenDifferentFilename(self):
    result = backend.GetCryptoTokens(
      [(constants.CRYPTO_TYPE_SSL_DIGEST, constants.CRYPTO_ACTION_CREATE,
        {constants.CRYPTO_OPTION_CERT_FILE:
          pathutils.NODED_CLIENT_CERT_FILE_TMP,
         constants.CRYPTO_OPTION_SERIAL_NO: 42})])
    self.assertTrue((constants.CRYPTO_TYPE_SSL_DIGEST, self._ssl_digest)
                    in result)
    self.assertTrue(utils.GenerateNewSslCert.assert_calls().once())

  def testCreateSslTokenSerialNo(self):
    result = backend.GetCryptoTokens(
      [(constants.CRYPTO_TYPE_SSL_DIGEST, constants.CRYPTO_ACTION_CREATE,
        {constants.CRYPTO_OPTION_SERIAL_NO: 42})])
    self.assertTrue((constants.CRYPTO_TYPE_SSL_DIGEST, self._ssl_digest)
                    in result)
    self.assertTrue(utils.GenerateNewSslCert.assert_calls().once())

  def testUnknownTokenType(self):
    self.assertRaises(errors.ProgrammerError,
                      backend.GetCryptoTokens,
                      [("pink_bunny", constants.CRYPTO_ACTION_GET, None)])

  def testUnknownAction(self):
    self.assertRaises(errors.ProgrammerError,
                      backend.GetCryptoTokens,
                      [(constants.CRYPTO_TYPE_SSL_DIGEST, "illuminate", None)])


class TestNodeVerify(testutils.GanetiTestCase):

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self._mock_hv = None

  def _GetHypervisor(self, hv_name):
    self._mock_hv = hypervisor.GetHypervisor(hv_name)
    self._mock_hv.ValidateParameters = mock.Mock()
    self._mock_hv.Verify = mock.Mock()
    return self._mock_hv

  def testMasterIPLocalhost(self):
    # this a real functional test, but requires localhost to be reachable
    local_data = (netutils.Hostname.GetSysName(),
                  constants.IP4_ADDRESS_LOCALHOST)
    result = backend.VerifyNode({constants.NV_MASTERIP: local_data},
                                None, {}, {}, {})
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failUnless(result[constants.NV_MASTERIP], "Cannot reach localhost")

  def testMasterIPUnreachable(self):
    # Network 192.0.2.0/24 is reserved for test/documentation as per
    # RFC 5737
    bad_data =  ("master.example.com", "192.0.2.1")
    # we just test that whatever TcpPing returns, VerifyNode returns too
    netutils.TcpPing = lambda a, b, source=None: False
    result = backend.VerifyNode({constants.NV_MASTERIP: bad_data},
                                None, {}, {}, {})
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failIf(result[constants.NV_MASTERIP],
                "Result from netutils.TcpPing corrupted")

  def testVerifyHvparams(self):
    test_hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    test_what = {constants.NV_HVPARAMS: \
        [("mynode", constants.HT_XEN_PVM, test_hvparams)]}
    result = {}
    backend._VerifyHvparams(test_what, True, result,
                            get_hv_fn=self._GetHypervisor)
    self._mock_hv.ValidateParameters.assert_called_with(test_hvparams)

  def testVerifyHypervisors(self):
    hvname = constants.HT_XEN_PVM
    hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    all_hvparams = {hvname: hvparams}
    test_what = {constants.NV_HYPERVISOR: [hvname]}
    result = {}
    backend._VerifyHypervisors(
        test_what, True, result, all_hvparams=all_hvparams,
        get_hv_fn=self._GetHypervisor)
    self._mock_hv.Verify.assert_called_with(hvparams=hvparams)

  @testutils.patch_object(utils, "VerifyCertificate")
  def testVerifyClientCertificateSuccess(self, verif_cert):
    # mock the underlying x509 verification because the test cert is expired
    verif_cert.return_value = (None, None)
    cert_file = testutils.TestDataFilename("cert2.pem")
    (errcode, digest) = backend._VerifyClientCertificate(cert_file=cert_file)
    self.assertEqual(None, errcode)
    self.assertTrue(isinstance(digest, str))

  @testutils.patch_object(utils, "VerifyCertificate")
  def testVerifyClientCertificateFailed(self, verif_cert):
    expected_errcode = 666
    verif_cert.return_value = (expected_errcode,
                               "The devil created this certificate.")
    cert_file = testutils.TestDataFilename("cert2.pem")
    (errcode, digest) = backend._VerifyClientCertificate(cert_file=cert_file)
    self.assertEqual(expected_errcode, errcode)

  def testVerifyClientCertificateNoCert(self):
    cert_file = testutils.TestDataFilename("cert-that-does-not-exist.pem")
    (errcode, digest) = backend._VerifyClientCertificate(cert_file=cert_file)
    self.assertEqual(constants.CV_ERROR, errcode)


def _DefRestrictedCmdOwner():
  return (os.getuid(), os.getgid())


class TestVerifyRestrictedCmdName(unittest.TestCase):
  def testAcceptableName(self):
    for i in ["foo", "bar", "z1", "000first", "hello-world"]:
      for fn in [lambda s: s, lambda s: s.upper(), lambda s: s.title()]:
        (status, msg) = backend._VerifyRestrictedCmdName(fn(i))
        self.assertTrue(status)
        self.assertTrue(msg is None)

  def testEmptyAndSpace(self):
    for i in ["", " ", "\t", "\n"]:
      (status, msg) = backend._VerifyRestrictedCmdName(i)
      self.assertFalse(status)
      self.assertEqual(msg, "Missing command name")

  def testNameWithSlashes(self):
    for i in ["/", "./foo", "../moo", "some/name"]:
      (status, msg) = backend._VerifyRestrictedCmdName(i)
      self.assertFalse(status)
      self.assertEqual(msg, "Invalid command name")

  def testForbiddenCharacters(self):
    for i in ["#", ".", "..", "bash -c ls", "'"]:
      (status, msg) = backend._VerifyRestrictedCmdName(i)
      self.assertFalse(status)
      self.assertEqual(msg, "Command name contains forbidden characters")


class TestVerifyRestrictedCmdDirectory(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCanNotStat(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    self.assertFalse(os.path.exists(tmpname))
    (status, msg) = \
      backend._VerifyRestrictedCmdDirectory(tmpname, _owner=NotImplemented)
    self.assertFalse(status)
    self.assertTrue(msg.startswith("Can't stat(2) '"))

  def testTooPermissive(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    os.mkdir(tmpname)

    for mode in [0777, 0706, 0760, 0722]:
      os.chmod(tmpname, mode)
      self.assertTrue(os.path.isdir(tmpname))
      (status, msg) = \
        backend._VerifyRestrictedCmdDirectory(tmpname, _owner=NotImplemented)
      self.assertFalse(status)
      self.assertTrue(msg.startswith("Permissions on '"))

  def testNoDirectory(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    utils.WriteFile(tmpname, data="empty\n")
    self.assertTrue(os.path.isfile(tmpname))
    (status, msg) = \
      backend._VerifyRestrictedCmdDirectory(tmpname,
                                            _owner=_DefRestrictedCmdOwner())
    self.assertFalse(status)
    self.assertTrue(msg.endswith("is not a directory"))

  def testNormal(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    os.mkdir(tmpname)
    os.chmod(tmpname, 0755)
    self.assertTrue(os.path.isdir(tmpname))
    (status, msg) = \
      backend._VerifyRestrictedCmdDirectory(tmpname,
                                            _owner=_DefRestrictedCmdOwner())
    self.assertTrue(status)
    self.assertTrue(msg is None)


class TestVerifyRestrictedCmd(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCanNotStat(self):
    tmpname = utils.PathJoin(self.tmpdir, "helloworld")
    self.assertFalse(os.path.exists(tmpname))
    (status, msg) = \
      backend._VerifyRestrictedCmd(self.tmpdir, "helloworld",
                                   _owner=NotImplemented)
    self.assertFalse(status)
    self.assertTrue(msg.startswith("Can't stat(2) '"))

  def testNotExecutable(self):
    tmpname = utils.PathJoin(self.tmpdir, "cmdname")
    utils.WriteFile(tmpname, data="empty\n")
    (status, msg) = \
      backend._VerifyRestrictedCmd(self.tmpdir, "cmdname",
                                   _owner=_DefRestrictedCmdOwner())
    self.assertFalse(status)
    self.assertTrue(msg.startswith("access(2) thinks '"))

  def testExecutable(self):
    tmpname = utils.PathJoin(self.tmpdir, "cmdname")
    utils.WriteFile(tmpname, data="empty\n", mode=0700)
    (status, executable) = \
      backend._VerifyRestrictedCmd(self.tmpdir, "cmdname",
                                   _owner=_DefRestrictedCmdOwner())
    self.assertTrue(status)
    self.assertEqual(executable, tmpname)


class TestPrepareRestrictedCmd(unittest.TestCase):
  _TEST_PATH = "/tmp/some/test/path"

  def testDirFails(self):
    def fn(path):
      self.assertEqual(path, self._TEST_PATH)
      return (False, "test error 31420")

    (status, msg) = \
      backend._PrepareRestrictedCmd(self._TEST_PATH, "cmd21152",
                                    _verify_dir=fn,
                                    _verify_name=NotImplemented,
                                    _verify_cmd=NotImplemented)
    self.assertFalse(status)
    self.assertEqual(msg, "test error 31420")

  def testNameFails(self):
    def fn(cmd):
      self.assertEqual(cmd, "cmd4617")
      return (False, "test error 591")

    (status, msg) = \
      backend._PrepareRestrictedCmd(self._TEST_PATH, "cmd4617",
                                    _verify_dir=lambda _: (True, None),
                                    _verify_name=fn,
                                    _verify_cmd=NotImplemented)
    self.assertFalse(status)
    self.assertEqual(msg, "test error 591")

  def testCommandFails(self):
    def fn(path, cmd):
      self.assertEqual(path, self._TEST_PATH)
      self.assertEqual(cmd, "cmd17577")
      return (False, "test error 25524")

    (status, msg) = \
      backend._PrepareRestrictedCmd(self._TEST_PATH, "cmd17577",
                                    _verify_dir=lambda _: (True, None),
                                    _verify_name=lambda _: (True, None),
                                    _verify_cmd=fn)
    self.assertFalse(status)
    self.assertEqual(msg, "test error 25524")

  def testSuccess(self):
    def fn(path, cmd):
      return (True, utils.PathJoin(path, cmd))

    (status, executable) = \
      backend._PrepareRestrictedCmd(self._TEST_PATH, "cmd22633",
                                    _verify_dir=lambda _: (True, None),
                                    _verify_name=lambda _: (True, None),
                                    _verify_cmd=fn)
    self.assertTrue(status)
    self.assertEqual(executable, utils.PathJoin(self._TEST_PATH, "cmd22633"))


def _SleepForRestrictedCmd(duration):
  assert duration > 5


def _GenericRestrictedCmdError(cmd):
  return "Executing command '%s' failed" % cmd


class TestRunRestrictedCmd(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExistantLockDirectory(self):
    lockfile = utils.PathJoin(self.tmpdir, "does", "not", "exist")
    sleep_fn = testutils.CallCounter(_SleepForRestrictedCmd)
    self.assertFalse(os.path.exists(lockfile))
    self.assertRaises(backend.RPCFail,
                      backend.RunRestrictedCmd, "test",
                      _lock_timeout=NotImplemented,
                      _lock_file=lockfile,
                      _path=NotImplemented,
                      _sleep_fn=sleep_fn,
                      _prepare_fn=NotImplemented,
                      _runcmd_fn=NotImplemented,
                      _enabled=True)
    self.assertEqual(sleep_fn.Count(), 1)

  @staticmethod
  def _TryLock(lockfile):
    sleep_fn = testutils.CallCounter(_SleepForRestrictedCmd)

    result = False
    try:
      backend.RunRestrictedCmd("test22717",
                               _lock_timeout=0.1,
                               _lock_file=lockfile,
                               _path=NotImplemented,
                               _sleep_fn=sleep_fn,
                               _prepare_fn=NotImplemented,
                               _runcmd_fn=NotImplemented,
                               _enabled=True)
    except backend.RPCFail, err:
      assert str(err) == _GenericRestrictedCmdError("test22717"), \
             "Did not fail with generic error message"
      result = True

    assert sleep_fn.Count() == 1

    return result

  def testLockHeldByOtherProcess(self):
    lockfile = utils.PathJoin(self.tmpdir, "lock")

    lock = utils.FileLock.Open(lockfile)
    lock.Exclusive(blocking=True, timeout=1.0)
    try:
      self.assertTrue(utils.RunInSeparateProcess(self._TryLock, lockfile))
    finally:
      lock.Close()

  @staticmethod
  def _PrepareRaisingException(path, cmd):
    assert cmd == "test23122"
    raise Exception("test")

  def testPrepareRaisesException(self):
    lockfile = utils.PathJoin(self.tmpdir, "lock")

    sleep_fn = testutils.CallCounter(_SleepForRestrictedCmd)
    prepare_fn = testutils.CallCounter(self._PrepareRaisingException)

    try:
      backend.RunRestrictedCmd("test23122",
                               _lock_timeout=1.0, _lock_file=lockfile,
                               _path=NotImplemented, _runcmd_fn=NotImplemented,
                               _sleep_fn=sleep_fn, _prepare_fn=prepare_fn,
                               _enabled=True)
    except backend.RPCFail, err:
      self.assertEqual(str(err), _GenericRestrictedCmdError("test23122"))
    else:
      self.fail("Didn't fail")

    self.assertEqual(sleep_fn.Count(), 1)
    self.assertEqual(prepare_fn.Count(), 1)

  @staticmethod
  def _PrepareFails(path, cmd):
    assert cmd == "test29327"
    return ("some error message", None)

  def testPrepareFails(self):
    lockfile = utils.PathJoin(self.tmpdir, "lock")

    sleep_fn = testutils.CallCounter(_SleepForRestrictedCmd)
    prepare_fn = testutils.CallCounter(self._PrepareFails)

    try:
      backend.RunRestrictedCmd("test29327",
                               _lock_timeout=1.0, _lock_file=lockfile,
                               _path=NotImplemented, _runcmd_fn=NotImplemented,
                               _sleep_fn=sleep_fn, _prepare_fn=prepare_fn,
                               _enabled=True)
    except backend.RPCFail, err:
      self.assertEqual(str(err), _GenericRestrictedCmdError("test29327"))
    else:
      self.fail("Didn't fail")

    self.assertEqual(sleep_fn.Count(), 1)
    self.assertEqual(prepare_fn.Count(), 1)

  @staticmethod
  def _SuccessfulPrepare(path, cmd):
    return (True, utils.PathJoin(path, cmd))

  def testRunCmdFails(self):
    lockfile = utils.PathJoin(self.tmpdir, "lock")

    def fn(args, env=NotImplemented, reset_env=NotImplemented,
           postfork_fn=NotImplemented):
      self.assertEqual(args, [utils.PathJoin(self.tmpdir, "test3079")])
      self.assertEqual(env, {})
      self.assertTrue(reset_env)
      self.assertTrue(callable(postfork_fn))

      trylock = utils.FileLock.Open(lockfile)
      try:
        # See if lockfile is still held
        self.assertRaises(EnvironmentError, trylock.Exclusive, blocking=False)

        # Call back to release lock
        postfork_fn(NotImplemented)

        # See if lockfile can be acquired
        trylock.Exclusive(blocking=False)
      finally:
        trylock.Close()

      # Simulate a failed command
      return utils.RunResult(constants.EXIT_FAILURE, None,
                             "stdout", "stderr406328567",
                             utils.ShellQuoteArgs(args),
                             NotImplemented, NotImplemented)

    sleep_fn = testutils.CallCounter(_SleepForRestrictedCmd)
    prepare_fn = testutils.CallCounter(self._SuccessfulPrepare)
    runcmd_fn = testutils.CallCounter(fn)

    try:
      backend.RunRestrictedCmd("test3079",
                               _lock_timeout=1.0, _lock_file=lockfile,
                               _path=self.tmpdir, _runcmd_fn=runcmd_fn,
                               _sleep_fn=sleep_fn, _prepare_fn=prepare_fn,
                               _enabled=True)
    except backend.RPCFail, err:
      self.assertTrue(str(err).startswith("Restricted command 'test3079'"
                                          " failed:"))
      self.assertTrue("stderr406328567" in str(err),
                      msg="Error did not include output")
    else:
      self.fail("Didn't fail")

    self.assertEqual(sleep_fn.Count(), 0)
    self.assertEqual(prepare_fn.Count(), 1)
    self.assertEqual(runcmd_fn.Count(), 1)

  def testRunCmdSucceeds(self):
    lockfile = utils.PathJoin(self.tmpdir, "lock")

    def fn(args, env=NotImplemented, reset_env=NotImplemented,
           postfork_fn=NotImplemented):
      self.assertEqual(args, [utils.PathJoin(self.tmpdir, "test5667")])
      self.assertEqual(env, {})
      self.assertTrue(reset_env)

      # Call back to release lock
      postfork_fn(NotImplemented)

      # Simulate a successful command
      return utils.RunResult(constants.EXIT_SUCCESS, None, "stdout14463", "",
                             utils.ShellQuoteArgs(args),
                             NotImplemented, NotImplemented)

    sleep_fn = testutils.CallCounter(_SleepForRestrictedCmd)
    prepare_fn = testutils.CallCounter(self._SuccessfulPrepare)
    runcmd_fn = testutils.CallCounter(fn)

    result = backend.RunRestrictedCmd("test5667",
                                      _lock_timeout=1.0, _lock_file=lockfile,
                                      _path=self.tmpdir, _runcmd_fn=runcmd_fn,
                                      _sleep_fn=sleep_fn,
                                      _prepare_fn=prepare_fn,
                                      _enabled=True)
    self.assertEqual(result, "stdout14463")

    self.assertEqual(sleep_fn.Count(), 0)
    self.assertEqual(prepare_fn.Count(), 1)
    self.assertEqual(runcmd_fn.Count(), 1)

  def testCommandsDisabled(self):
    try:
      backend.RunRestrictedCmd("test",
                               _lock_timeout=NotImplemented,
                               _lock_file=NotImplemented,
                               _path=NotImplemented,
                               _sleep_fn=NotImplemented,
                               _prepare_fn=NotImplemented,
                               _runcmd_fn=NotImplemented,
                               _enabled=False)
    except backend.RPCFail, err:
      self.assertEqual(str(err),
                       "Restricted commands disabled at configure time")
    else:
      self.fail("Did not raise exception")


class TestSetWatcherPause(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()
    self.filename = utils.PathJoin(self.tmpdir, "pause")

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testUnsetNonExisting(self):
    self.assertFalse(os.path.exists(self.filename))
    backend.SetWatcherPause(None, _filename=self.filename)
    self.assertFalse(os.path.exists(self.filename))

  def testSetNonNumeric(self):
    for i in ["", [], {}, "Hello World", "0", "1.0"]:
      self.assertFalse(os.path.exists(self.filename))

      try:
        backend.SetWatcherPause(i, _filename=self.filename)
      except backend.RPCFail, err:
        self.assertEqual(str(err), "Duration must be numeric")
      else:
        self.fail("Did not raise exception")

      self.assertFalse(os.path.exists(self.filename))

  def testSet(self):
    self.assertFalse(os.path.exists(self.filename))

    for i in range(10):
      backend.SetWatcherPause(i, _filename=self.filename)
      self.assertEqual(utils.ReadFile(self.filename), "%s\n" % i)
      self.assertEqual(os.stat(self.filename).st_mode & 0777, 0644)


class TestGetBlockDevSymlinkPath(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _Test(self, name, idx):
    self.assertEqual(backend._GetBlockDevSymlinkPath(name, idx,
                                                     _dir=self.tmpdir),
                     ("%s/%s%s%s" % (self.tmpdir, name,
                                     constants.DISK_SEPARATOR, idx)))

  def test(self):
    for idx in range(100):
      self._Test("inst1.example.com", idx)


class TestGetInstanceList(unittest.TestCase):

  def setUp(self):
    self._test_hv = self._TestHypervisor()
    self._test_hv.ListInstances = mock.Mock(
      return_value=["instance1", "instance2", "instance3"] )

  class _TestHypervisor(hypervisor.hv_base.BaseHypervisor):
    def __init__(self):
      hypervisor.hv_base.BaseHypervisor.__init__(self)

  def _GetHypervisor(self, name):
    return self._test_hv

  def testHvparams(self):
    fake_hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    hvparams = {constants.HT_FAKE: fake_hvparams}
    backend.GetInstanceList([constants.HT_FAKE], all_hvparams=hvparams,
                            get_hv_fn=self._GetHypervisor)
    self._test_hv.ListInstances.assert_called_with(hvparams=fake_hvparams)


class TestInstanceConsoleInfo(unittest.TestCase):

  def setUp(self):
    self._test_hv_a = self._TestHypervisor()
    self._test_hv_a.GetInstanceConsole = mock.Mock(
      return_value = objects.InstanceConsole(instance="inst", kind="aHy")
    )
    self._test_hv_b = self._TestHypervisor()
    self._test_hv_b.GetInstanceConsole = mock.Mock(
      return_value = objects.InstanceConsole(instance="inst", kind="bHy")
    )

  class _TestHypervisor(hypervisor.hv_base.BaseHypervisor):
    def __init__(self):
      hypervisor.hv_base.BaseHypervisor.__init__(self)

  def _GetHypervisor(self, name):
    if name == "a":
      return self._test_hv_a
    else:
      return self._test_hv_b

  def testRightHypervisor(self):
    dictMaker = lambda hyName: {
      "instance":{"hypervisor":hyName},
      "node":{},
      "group":{},
      "hvParams":{},
      "beParams":{},
    }

    call = {
      'i1':dictMaker("a"),
      'i2':dictMaker("b"),
    }

    res = backend.GetInstanceConsoleInfo(call, get_hv_fn=self._GetHypervisor)

    self.assertTrue(res["i1"]["kind"] == "aHy")
    self.assertTrue(res["i2"]["kind"] == "bHy")


class TestGetHvInfo(unittest.TestCase):

  def setUp(self):
    self._test_hv = self._TestHypervisor()
    self._test_hv.GetNodeInfo = mock.Mock()

  class _TestHypervisor(hypervisor.hv_base.BaseHypervisor):
    def __init__(self):
      hypervisor.hv_base.BaseHypervisor.__init__(self)

  def _GetHypervisor(self, name):
    return self._test_hv

  def testGetHvInfoAllNone(self):
    result = backend._GetHvInfoAll(None)
    self.assertTrue(result is None)

  def testGetHvInfoAll(self):
    hvname = constants.HT_XEN_PVM
    hvparams = {constants.HV_XEN_CMD: constants.XEN_CMD_XL}
    hv_specs = [(hvname, hvparams)]

    backend._GetHvInfoAll(hv_specs, self._GetHypervisor)
    self._test_hv.GetNodeInfo.assert_called_with(hvparams=hvparams)


class TestApplyStorageInfoFunction(unittest.TestCase):

  _STORAGE_KEY = "some_key"
  _SOME_ARGS = ["some_args"]

  def setUp(self):
    self.mock_storage_fn = mock.Mock()

  def testApplyValidStorageType(self):
    storage_type = constants.ST_LVM_VG
    info_fn_orig = backend._STORAGE_TYPE_INFO_FN
    backend._STORAGE_TYPE_INFO_FN = {
        storage_type: self.mock_storage_fn
      }

    backend._ApplyStorageInfoFunction(
        storage_type, self._STORAGE_KEY, self._SOME_ARGS)

    self.mock_storage_fn.assert_called_with(self._STORAGE_KEY, self._SOME_ARGS)
    backend._STORAGE_TYPE_INFO_FN = info_fn_orig

  def testApplyInValidStorageType(self):
    storage_type = "invalid_storage_type"
    info_fn_orig = backend._STORAGE_TYPE_INFO_FN
    backend._STORAGE_TYPE_INFO_FN = {}

    self.assertRaises(KeyError, backend._ApplyStorageInfoFunction,
                      storage_type, self._STORAGE_KEY, self._SOME_ARGS)
    backend._STORAGE_TYPE_INFO_FN = info_fn_orig

  def testApplyNotImplementedStorageType(self):
    storage_type = "not_implemented_storage_type"
    info_fn_orig = backend._STORAGE_TYPE_INFO_FN
    backend._STORAGE_TYPE_INFO_FN = {storage_type: None}

    self.assertRaises(NotImplementedError,
                      backend._ApplyStorageInfoFunction,
                      storage_type, self._STORAGE_KEY, self._SOME_ARGS)
    backend._STORAGE_TYPE_INFO_FN = info_fn_orig


class TestGetLvmVgSpaceInfo(unittest.TestCase):

  def testValid(self):
    path = "somepath"
    excl_stor = True
    orig_fn = backend._GetVgInfo
    backend._GetVgInfo = mock.Mock()
    backend._GetLvmVgSpaceInfo(path, [excl_stor])
    backend._GetVgInfo.assert_called_with(path, excl_stor)
    backend._GetVgInfo = orig_fn

  def testNoExclStorageNotBool(self):
    path = "somepath"
    excl_stor = "123"
    self.assertRaises(errors.ProgrammerError, backend._GetLvmVgSpaceInfo,
                      path, [excl_stor])

  def testNoExclStorageNotInList(self):
    path = "somepath"
    excl_stor = "123"
    self.assertRaises(errors.ProgrammerError, backend._GetLvmVgSpaceInfo,
                      path, excl_stor)

class TestGetLvmPvSpaceInfo(unittest.TestCase):

  def testValid(self):
    path = "somepath"
    excl_stor = True
    orig_fn = backend._GetVgSpindlesInfo
    backend._GetVgSpindlesInfo = mock.Mock()
    backend._GetLvmPvSpaceInfo(path, [excl_stor])
    backend._GetVgSpindlesInfo.assert_called_with(path, excl_stor)
    backend._GetVgSpindlesInfo = orig_fn


class TestCheckStorageParams(unittest.TestCase):

  def testParamsNone(self):
    self.assertRaises(errors.ProgrammerError, backend._CheckStorageParams,
                      None, NotImplemented)

  def testParamsWrongType(self):
    self.assertRaises(errors.ProgrammerError, backend._CheckStorageParams,
                      "string", NotImplemented)

  def testParamsEmpty(self):
    backend._CheckStorageParams([], 0)

  def testParamsValidNumber(self):
    backend._CheckStorageParams(["a", True], 2)

  def testParamsInvalidNumber(self):
    self.assertRaises(errors.ProgrammerError, backend._CheckStorageParams,
                      ["b", False], 3)


class TestGetVgSpindlesInfo(unittest.TestCase):

  def setUp(self):
    self.vg_free = 13
    self.vg_size = 31
    self.mock_fn = mock.Mock(return_value=(self.vg_free, self.vg_size))

  def testValidInput(self):
    name = "myvg"
    excl_stor = True
    result = backend._GetVgSpindlesInfo(name, excl_stor, info_fn=self.mock_fn)
    self.mock_fn.assert_called_with(name)
    self.assertEqual(name, result["name"])
    self.assertEqual(constants.ST_LVM_PV, result["type"])
    self.assertEqual(self.vg_free, result["storage_free"])
    self.assertEqual(self.vg_size, result["storage_size"])

  def testNoExclStor(self):
    name = "myvg"
    excl_stor = False
    result = backend._GetVgSpindlesInfo(name, excl_stor, info_fn=self.mock_fn)
    self.mock_fn.assert_not_called()
    self.assertEqual(name, result["name"])
    self.assertEqual(constants.ST_LVM_PV, result["type"])
    self.assertEqual(0, result["storage_free"])
    self.assertEqual(0, result["storage_size"])


class TestGetVgSpindlesInfo(unittest.TestCase):

  def testValidInput(self):
    self.vg_free = 13
    self.vg_size = 31
    self.mock_fn = mock.Mock(return_value=[(self.vg_free, self.vg_size)])
    name = "myvg"
    excl_stor = True
    result = backend._GetVgInfo(name, excl_stor, info_fn=self.mock_fn)
    self.mock_fn.assert_called_with([name], excl_stor)
    self.assertEqual(name, result["name"])
    self.assertEqual(constants.ST_LVM_VG, result["type"])
    self.assertEqual(self.vg_free, result["storage_free"])
    self.assertEqual(self.vg_size, result["storage_size"])

  def testNoExclStor(self):
    name = "myvg"
    excl_stor = True
    self.mock_fn = mock.Mock(return_value=None)
    result = backend._GetVgInfo(name, excl_stor, info_fn=self.mock_fn)
    self.mock_fn.assert_called_with([name], excl_stor)
    self.assertEqual(name, result["name"])
    self.assertEqual(constants.ST_LVM_VG, result["type"])
    self.assertEqual(None, result["storage_free"])
    self.assertEqual(None, result["storage_size"])


class TestGetNodeInfo(unittest.TestCase):

  _SOME_RESULT = None

  def testApplyStorageInfoFunction(self):
    orig_fn = backend._ApplyStorageInfoFunction
    backend._ApplyStorageInfoFunction = mock.Mock(
        return_value=self._SOME_RESULT)
    storage_units = [(st, st + "_key", [st + "_params"]) for st in
                     constants.STORAGE_TYPES]

    backend.GetNodeInfo(storage_units, None)

    call_args_list = backend._ApplyStorageInfoFunction.call_args_list
    self.assertEqual(len(constants.STORAGE_TYPES), len(call_args_list))
    for call in call_args_list:
      storage_type, storage_key, storage_params = call[0]
      self.assertEqual(storage_type + "_key", storage_key)
      self.assertEqual([storage_type + "_params"], storage_params)
      self.assertTrue(storage_type in constants.STORAGE_TYPES)
    backend._ApplyStorageInfoFunction = orig_fn


class TestSpaceReportingConstants(unittest.TestCase):
  """Ensures consistency between STS_REPORT and backend.

  These tests ensure, that the constant 'STS_REPORT' is consistent
  with the implementation of invoking space reporting functions
  in backend.py. Once space reporting is available for all types,
  the constant can be removed and these tests as well.

  """

  REPORTING = set(constants.STS_REPORT)
  NOT_REPORTING = set(constants.STORAGE_TYPES) - REPORTING

  def testAllReportingTypesHaveAReportingFunction(self):
    for storage_type in TestSpaceReportingConstants.REPORTING:
      self.assertTrue(backend._STORAGE_TYPE_INFO_FN[storage_type] is not None)

  def testAllNotReportingTypesDontHaveFunction(self):
    for storage_type in TestSpaceReportingConstants.NOT_REPORTING:
      self.assertEqual(None, backend._STORAGE_TYPE_INFO_FN[storage_type])


class TestAddRemoveGenerateNodeSshKey(testutils.GanetiTestCase):

  _CLUSTER_NAME = "mycluster"
  _SSH_PORT = 22

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self._ssh_add_authorized_patcher = testutils \
      .patch_object(ssh, "AddAuthorizedKeys")
    self._ssh_remove_authorized_patcher = testutils \
      .patch_object(ssh, "RemoveAuthorizedKeys")
    self._ssh_add_authorized_mock = self._ssh_add_authorized_patcher.start()

    self._ssconf_mock = mock.Mock()
    self._ssconf_mock.GetNodeList = mock.Mock()
    self._ssconf_mock.GetMasterNode = mock.Mock()
    self._ssconf_mock.GetClusterName = mock.Mock()

    self._run_cmd_mock = mock.Mock()

    self._ssh_remove_authorized_mock = \
      self._ssh_remove_authorized_patcher.start()
    self.noded_cert_file = testutils.TestDataFilename("cert1.pem")

  def tearDown(self):
    super(testutils.GanetiTestCase, self).tearDown()
    self._ssh_add_authorized_patcher.stop()
    self._ssh_remove_authorized_patcher.stop()

  def _SetupTestData(self, number_of_nodes=15, number_of_pot_mcs=5,
                     number_of_mcs=5):
    """Sets up consistent test data for a cluster with a couple of nodes.

    """
    self._pub_key_file = self._CreateTempFile()
    self._all_nodes = []
    self._potential_master_candidates = []
    self._master_candidate_uuids = []
    self._ssh_port_map = {}

    self._ssconf_mock.reset_mock()
    self._ssconf_mock.GetNodeList.reset_mock()
    self._ssconf_mock.GetMasterNode.reset_mock()
    self._ssconf_mock.GetClusterName.reset_mock()
    self._run_cmd_mock.reset_mock()

    for i in range(number_of_nodes):
      node_name = "node_name_%s" % i
      node_uuid = "node_uuid_%s" % i
      self._ssh_port_map[node_name] = self._SSH_PORT
      self._all_nodes.append(node_name)

      if i in range(number_of_mcs + number_of_pot_mcs):
        ssh.AddPublicKey("node_uuid_%s" % i, "key%s" % i,
                         key_file=self._pub_key_file)
        self._potential_master_candidates.append(node_name)

      if i in range(number_of_mcs):
        self._master_candidate_uuids.append(node_uuid)

    self._master_node = "node_name_%s" % (number_of_mcs / 2)
    self._ssconf_mock.GetNodeList.return_value = self._all_nodes

  def _TearDownTestData(self):
    os.remove(self._pub_key_file)

  def _KeyOperationExecuted(self, key_data, node_name, expected_type,
                            expected_key, action_types):
    if not node_name in key_data:
      return False
    for data in key_data[node_name]:
      if expected_type in data:
        (action, key_dict) = data[expected_type]
        if action in action_types:
          for key_list in key_dict.values():
            if expected_key in key_list:
              return True
    return False

  def _KeyReceived(self, key_data, node_name, expected_type,
                   expected_key):
    return self._KeyOperationExecuted(
      key_data, node_name, expected_type, expected_key,
      [constants.SSHS_ADD, constants.SSHS_OVERRIDE,
       constants.SSHS_REPLACE_OR_ADD])

  def _KeyRemoved(self, key_data, node_name, expected_type,
                  expected_key):
    if self._KeyOperationExecuted(
        key_data, node_name, expected_type, expected_key,
        [constants.SSHS_REMOVE]):
      return True
    else:
      if not node_name in key_data:
        return False
      for data in key_data[node_name]:
        if expected_type in data:
          (action, key_dict) = data[expected_type]
          if action == constants.SSHS_CLEAR:
            return True
    return False

  def _GetCallsPerNode(self):
    calls_per_node = {}
    for (pos, keyword) in self._run_cmd_mock.call_args_list:
      (cluster_name, node, _, _, data) = pos
      if not node in calls_per_node:
        calls_per_node[node] = []
      calls_per_node[node].append(data)
    return calls_per_node

  def testGenerateKey(self):
    test_node_name = "node_name_7"
    test_node_uuid = "node_uuid_7"

    self._SetupTestData()

    backend._GenerateNodeSshKey(test_node_uuid, test_node_name,
                                self._ssh_port_map,
                                pub_key_file=self._pub_key_file,
                                ssconf_store=self._ssconf_mock,
                                noded_cert_file=self.noded_cert_file,
                                run_cmd_fn=self._run_cmd_mock)

    calls_per_node = self._GetCallsPerNode()
    for node, calls in calls_per_node.items():
      self.assertEquals(node, test_node_name)
      for call in calls:
        self.assertTrue(constants.SSHS_GENERATE in call)

  def testAddNodeSshKeyValid(self):
    new_node_name = "new_node_name"
    new_node_uuid = "new_node_uuid"
    new_node_key1 = "new_node_key1"
    new_node_key2 = "new_node_key2"

    for (to_authorized_keys, to_public_keys, get_public_keys) in \
        [(True, True, False), (False, True, False),
         (True, True, True), (False, True, True)]:

      self._SetupTestData()

      # set up public key file, ssconf store, and node lists
      if to_public_keys:
        for key in [new_node_key1, new_node_key2]:
          ssh.AddPublicKey(new_node_name, key, key_file=self._pub_key_file)
        self._potential_master_candidates.append(new_node_name)

      self._ssh_port_map[new_node_name] = self._SSH_PORT

      backend.AddNodeSshKey(new_node_uuid, new_node_name,
                            self._potential_master_candidates,
                            self._ssh_port_map,
                            to_authorized_keys=to_authorized_keys,
                            to_public_keys=to_public_keys,
                            get_public_keys=get_public_keys,
                            pub_key_file=self._pub_key_file,
                            ssconf_store=self._ssconf_mock,
                            noded_cert_file=self.noded_cert_file,
                            run_cmd_fn=self._run_cmd_mock)

      calls_per_node = self._GetCallsPerNode()

      # one sample node per type (master candidate, potential master candidate,
      # normal node)
      mc_idx = 3
      pot_mc_idx = 7
      normal_idx = 12
      sample_nodes = [mc_idx, pot_mc_idx, normal_idx]
      pot_sample_nodes = [mc_idx, pot_mc_idx]

      if to_authorized_keys:
        for node_idx in sample_nodes:
          self.assertTrue(self._KeyReceived(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_AUTHORIZED_KEYS, new_node_key1),
            "Node %i did not receive authorized key '%s' although it should"
            " have." % (node_idx, new_node_key1))
      else:
        for node_idx in sample_nodes:
          self.assertFalse(self._KeyReceived(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_AUTHORIZED_KEYS, new_node_key1),
            "Node %i received authorized key '%s', although it should not have."
            % (node_idx, new_node_key1))

      if to_public_keys:
        for node_idx in pot_sample_nodes:
          self.assertTrue(self._KeyReceived(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_PUBLIC_KEYS, new_node_key1),
            "Node %i did not receive public key '%s', although it should have."
             % (node_idx, new_node_key1))
      else:
        for node_idx in sample_nodes:
          self.assertFalse(self._KeyReceived(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_PUBLIC_KEYS, new_node_key1),
            "Node %i did receive public key '%s', although it should have."
             % (node_idx, new_node_key1))

      if get_public_keys:
        for node_idx in sample_nodes:
          if node_idx in pot_sample_nodes:
            self.assertTrue(self._KeyReceived(
              calls_per_node, new_node_name,
              constants.SSHS_SSH_PUBLIC_KEYS, "key%s" % node_idx),
              "The new node '%s' did not receive public key of node %i,"
              " although it should have." %
              (new_node_name, node_idx))
          else:
            self.assertFalse(self._KeyReceived(
              calls_per_node, new_node_name,
              constants.SSHS_SSH_PUBLIC_KEYS, "key%s" % node_idx),
              "The new node '%s' did receive public key of node %i,"
              " although it should not have." %
              (new_node_name, node_idx))
      else:
        new_node_name not in calls_per_node

      self._TearDownTestData()

  def testRemoveNodeSshKeyValid(self):
    node_name = "node_name"
    node_uuid = "node_uuid"
    node_key1 = "node_key1"
    node_key2 = "node_key2"

    for (from_authorized_keys, from_public_keys,
         clear_authorized_keys, clear_public_keys) in \
       [(True, True, False, False),
        (True, False, False, False),
        (False, True, False, False),
        (False, True, True, False),
        (False, False, True, False),
        (True, True, True, False),
        (True, True, True, True),
       ]:

      self._SetupTestData()

      # set up public key file, ssconf store, and node lists
      if from_public_keys or from_authorized_keys:
        for key in [node_key1, node_key2]:
          ssh.AddPublicKey(node_uuid, key, key_file=self._pub_key_file)
        self._potential_master_candidates.append(node_name)
      if from_authorized_keys:
        ssh.AddAuthorizedKeys(self._pub_key_file, [node_key1, node_key2])

      self._ssh_port_map[node_name] = self._SSH_PORT

      if from_authorized_keys:
        self._master_candidate_uuids.append(node_uuid)

      backend.RemoveNodeSshKey(node_uuid, node_name,
                               self._master_candidate_uuids,
                               self._potential_master_candidates,
                               self._ssh_port_map,
                               from_authorized_keys=from_authorized_keys,
                               from_public_keys=from_public_keys,
                               clear_authorized_keys=clear_authorized_keys,
                               clear_public_keys=clear_public_keys,
                               pub_key_file=self._pub_key_file,
                               ssconf_store=self._ssconf_mock,
                               noded_cert_file=self.noded_cert_file,
                               run_cmd_fn=self._run_cmd_mock)

      calls_per_node = self._GetCallsPerNode()

      # one sample node per type (master candidate, potential master candidate,
      # normal node)
      mc_idx = 3
      pot_mc_idx = 7
      normal_idx = 12
      sample_nodes = [mc_idx, pot_mc_idx, normal_idx]
      pot_sample_nodes = [mc_idx, pot_mc_idx]

      if from_authorized_keys:
        for node_idx in sample_nodes:
          self.assertTrue(self._KeyRemoved(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_AUTHORIZED_KEYS, node_key1),
            "Node %i did not get request to remove authorized key '%s'"
            " although it should have." % (node_idx, node_key1))
      else:
        for node_idx in sample_nodes:
          self.assertFalse(self._KeyRemoved(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_AUTHORIZED_KEYS, node_key1),
            "Node %i got requested to remove authorized key '%s', although it"
            " should not have." % (node_idx, node_key1))

      if from_public_keys:
        for node_idx in pot_sample_nodes:
          self.assertTrue(self._KeyRemoved(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_PUBLIC_KEYS, node_key1),
            "Node %i did not receive request to remove public key '%s',"
            " although it should have." % (node_idx, node_key1))
        self.assertTrue(self._KeyRemoved(
          calls_per_node, node_name,
          constants.SSHS_SSH_PUBLIC_KEYS, node_key1),
          "Node %s did not receive request to remove its own public key '%s',"
          " although it should have." % (node_name, node_key1))
        for node_idx in list(set(sample_nodes) - set(pot_sample_nodes)):
          self.assertFalse(self._KeyRemoved(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_PUBLIC_KEYS, node_key1),
            "Node %i received a request to remove public key '%s',"
            " although it should not have." % (node_idx, node_key1))
      else:
        for node_idx in sample_nodes:
          self.assertFalse(self._KeyRemoved(
            calls_per_node, "node_name_%i" % node_idx,
            constants.SSHS_SSH_PUBLIC_KEYS, node_key1),
            "Node %i received a request to remove public key '%s',"
            " although it should not have." % (node_idx, node_key1))

      if clear_authorized_keys:
        for node_idx in list(set(sample_nodes) - set([mc_idx])):
          key = "key%s" % node_idx
          self.assertFalse(self._KeyRemoved(
            calls_per_node, node_name,
            constants.SSHS_SSH_AUTHORIZED_KEYS, key),
            "Node %s did receive request to remove authorized key '%s',"
            " although it should not have." % (node_name, key))
        mc_key = "key%s" % mc_idx
        self.assertTrue(self._KeyRemoved(
          calls_per_node, node_name,
          constants.SSHS_SSH_AUTHORIZED_KEYS, mc_key),
          "Node %s did not receive request to remove authorized key '%s',"
          " although it should have." % (node_name, mc_key))
      else:
        for node_idx in sample_nodes:
          key = "key%s" % node_idx
          self.assertFalse(self._KeyRemoved(
            calls_per_node, node_name,
            constants.SSHS_SSH_AUTHORIZED_KEYS, key),
            "Node %s did receive request to remove authorized key '%s',"
            " although it should not have." % (node_name, key))

      if clear_public_keys:
        # Checks if the node is cleared of all other potential master candidate
        # nodes' public keys
        for node_idx in pot_sample_nodes:
          key = "key%s" % node_idx
          self.assertTrue(self._KeyRemoved(
            calls_per_node, node_name,
            constants.SSHS_SSH_PUBLIC_KEYS, mc_key),
            "Node %s did not receive request to remove public key '%s',"
            " although it should have." % (node_name, key))


class TestVerifySshSetup(testutils.GanetiTestCase):

  _NODE1_UUID = "uuid1"
  _NODE2_UUID = "uuid2"
  _NODE3_UUID = "uuid3"
  _NODE1_NAME = "name1"
  _NODE2_NAME = "name2"
  _NODE3_NAME = "name3"
  _NODE1_KEYS = ["key11", "key12"]
  _NODE2_KEYS = ["key21"]
  _NODE3_KEYS = ["key31"]

  _NODE_STATUS_LIST = [
    (_NODE1_UUID, _NODE1_NAME, True, True),
    (_NODE2_UUID, _NODE2_NAME, False, True),
    (_NODE3_UUID, _NODE3_NAME, False, False),
    ]

  _PUB_KEY_RESULT = {
    _NODE1_UUID: _NODE1_KEYS,
    _NODE2_UUID: _NODE2_KEYS,
    _NODE3_UUID: _NODE3_KEYS,
    }

  _AUTH_RESULT = {
    _NODE1_KEYS[0]: True,
    _NODE1_KEYS[1]: True,
    _NODE2_KEYS[0]: False,
    _NODE3_KEYS[0]: False,
  }

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self._has_authorized_patcher = testutils \
      .patch_object(ssh, "HasAuthorizedKey")
    self._has_authorized_mock = self._has_authorized_patcher.start()
    self._query_patcher = testutils \
      .patch_object(ssh, "QueryPubKeyFile")
    self._query_mock = self._query_patcher.start()
    self._read_file_patcher = testutils \
      .patch_object(utils, "ReadFile")
    self._read_file_mock = self._read_file_patcher.start()
    self._read_file_mock.return_value = self._NODE1_KEYS[0]

  def tearDown(self):
    super(testutils.GanetiTestCase, self).tearDown()
    self._has_authorized_patcher.stop()
    self._query_patcher.stop()
    self._read_file_patcher.stop()

  def testValidData(self):
    self._has_authorized_mock.side_effect = \
      lambda _, key : self._AUTH_RESULT[key]
    self._query_mock.return_value = self._PUB_KEY_RESULT
    result = backend._VerifySshSetup(self._NODE_STATUS_LIST,
                                     self._NODE1_NAME)
    self.assertEqual(result, [])

  def testMissingKey(self):
    self._has_authorized_mock.side_effect = \
      lambda _, key : self._AUTH_RESULT[key]
    pub_key_missing = copy.deepcopy(self._PUB_KEY_RESULT)
    del pub_key_missing[self._NODE2_UUID]
    self._query_mock.return_value = pub_key_missing
    result = backend._VerifySshSetup(self._NODE_STATUS_LIST,
                                     self._NODE1_NAME)
    self.assertTrue(self._NODE2_UUID in result[0])

  def testUnknownKey(self):
    self._has_authorized_mock.side_effect = \
      lambda _, key : self._AUTH_RESULT[key]
    pub_key_missing = copy.deepcopy(self._PUB_KEY_RESULT)
    pub_key_missing["unkownnodeuuid"] = "pinkbunny"
    self._query_mock.return_value = pub_key_missing
    result = backend._VerifySshSetup(self._NODE_STATUS_LIST,
                                     self._NODE1_NAME)
    self.assertTrue("unkownnodeuuid" in result[0])

  def testMissingMasterCandidate(self):
    auth_result = copy.deepcopy(self._AUTH_RESULT)
    auth_result["key12"] = False
    self._has_authorized_mock.side_effect = \
      lambda _, key : auth_result[key]
    self._query_mock.return_value = self._PUB_KEY_RESULT
    result = backend._VerifySshSetup(self._NODE_STATUS_LIST,
                                     self._NODE1_NAME)
    self.assertTrue(self._NODE1_UUID in result[0])

  def testSuperfluousNormalNode(self):
    auth_result = copy.deepcopy(self._AUTH_RESULT)
    auth_result["key31"] = True
    self._has_authorized_mock.side_effect = \
      lambda _, key : auth_result[key]
    self._query_mock.return_value = self._PUB_KEY_RESULT
    result = backend._VerifySshSetup(self._NODE_STATUS_LIST,
                                     self._NODE1_NAME)
    self.assertTrue(self._NODE3_UUID in result[0])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
