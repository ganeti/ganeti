#!/usr/bin/python
#

# Copyright (C) 2010, 2013 Google Inc.
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


"""Script for testing ganeti.backend"""

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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
