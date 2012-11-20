#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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

import os
import sys
import shutil
import tempfile
import unittest

from ganeti import utils
from ganeti import constants
from ganeti import backend
from ganeti import netutils
from ganeti import errors

import testutils
import mocks


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
  def testMasterIPLocalhost(self):
    # this a real functional test, but requires localhost to be reachable
    local_data = (netutils.Hostname.GetSysName(),
                  constants.IP4_ADDRESS_LOCALHOST)
    result = backend.VerifyNode({constants.NV_MASTERIP: local_data}, None)
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failUnless(result[constants.NV_MASTERIP], "Cannot reach localhost")

  def testMasterIPUnreachable(self):
    # Network 192.0.2.0/24 is reserved for test/documentation as per
    # RFC 5737
    bad_data =  ("master.example.com", "192.0.2.1")
    # we just test that whatever TcpPing returns, VerifyNode returns too
    netutils.TcpPing = lambda a, b, source=None: False
    result = backend.VerifyNode({constants.NV_MASTERIP: bad_data}, None)
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failIf(result[constants.NV_MASTERIP],
                "Result from netutils.TcpPing corrupted")


def _DefRemoteCommandOwner():
  return (os.getuid(), os.getgid())


class TestVerifyRemoteCommandName(unittest.TestCase):
  def testAcceptableName(self):
    for i in ["foo", "bar", "z1", "000first", "hello-world"]:
      for fn in [lambda s: s, lambda s: s.upper(), lambda s: s.title()]:
        (status, msg) = backend._VerifyRemoteCommandName(fn(i))
        self.assertTrue(status)
        self.assertTrue(msg is None)

  def testEmptyAndSpace(self):
    for i in ["", " ", "\t", "\n"]:
      (status, msg) = backend._VerifyRemoteCommandName(i)
      self.assertFalse(status)
      self.assertEqual(msg, "Missing command name")

  def testNameWithSlashes(self):
    for i in ["/", "./foo", "../moo", "some/name"]:
      (status, msg) = backend._VerifyRemoteCommandName(i)
      self.assertFalse(status)
      self.assertEqual(msg, "Invalid command name")

  def testForbiddenCharacters(self):
    for i in ["#", ".", "..", "bash -c ls", "'"]:
      (status, msg) = backend._VerifyRemoteCommandName(i)
      self.assertFalse(status)
      self.assertEqual(msg, "Command name contains forbidden characters")


class TestVerifyRemoteCommandDirectory(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCanNotStat(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    self.assertFalse(os.path.exists(tmpname))
    (status, msg) = \
      backend._VerifyRemoteCommandDirectory(tmpname, _owner=NotImplemented)
    self.assertFalse(status)
    self.assertTrue(msg.startswith("Can't stat(2) '"))

  def testTooPermissive(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    os.mkdir(tmpname)

    for mode in [0777, 0706, 0760, 0722]:
      os.chmod(tmpname, mode)
      self.assertTrue(os.path.isdir(tmpname))
      (status, msg) = \
        backend._VerifyRemoteCommandDirectory(tmpname, _owner=NotImplemented)
      self.assertFalse(status)
      self.assertTrue(msg.startswith("Permissions on '"))

  def testNoDirectory(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    utils.WriteFile(tmpname, data="empty\n")
    self.assertTrue(os.path.isfile(tmpname))
    (status, msg) = \
      backend._VerifyRemoteCommandDirectory(tmpname,
                                            _owner=_DefRemoteCommandOwner())
    self.assertFalse(status)
    self.assertTrue(msg.endswith("is not a directory"))

  def testNormal(self):
    tmpname = utils.PathJoin(self.tmpdir, "foobar")
    os.mkdir(tmpname)
    self.assertTrue(os.path.isdir(tmpname))
    (status, msg) = \
      backend._VerifyRemoteCommandDirectory(tmpname,
                                            _owner=_DefRemoteCommandOwner())
    self.assertTrue(status)
    self.assertTrue(msg is None)


class TestVerifyRemoteCommand(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testCanNotStat(self):
    tmpname = utils.PathJoin(self.tmpdir, "helloworld")
    self.assertFalse(os.path.exists(tmpname))
    (status, msg) = \
      backend._VerifyRemoteCommand(self.tmpdir, "helloworld",
                                   _owner=NotImplemented)
    self.assertFalse(status)
    self.assertTrue(msg.startswith("Can't stat(2) '"))

  def testNotExecutable(self):
    tmpname = utils.PathJoin(self.tmpdir, "cmdname")
    utils.WriteFile(tmpname, data="empty\n")
    (status, msg) = \
      backend._VerifyRemoteCommand(self.tmpdir, "cmdname",
                                   _owner=_DefRemoteCommandOwner())
    self.assertFalse(status)
    self.assertTrue(msg.startswith("access(2) thinks '"))

  def testExecutable(self):
    tmpname = utils.PathJoin(self.tmpdir, "cmdname")
    utils.WriteFile(tmpname, data="empty\n", mode=0700)
    (status, executable) = \
      backend._VerifyRemoteCommand(self.tmpdir, "cmdname",
                                   _owner=_DefRemoteCommandOwner())
    self.assertTrue(status)
    self.assertEqual(executable, tmpname)


class TestPrepareRemoteCommand(unittest.TestCase):
  _TEST_PATH = "/tmp/some/test/path"

  def testDirFails(self):
    def fn(path):
      self.assertEqual(path, self._TEST_PATH)
      return (False, "test error 31420")

    (status, msg) = \
      backend._PrepareRemoteCommand(self._TEST_PATH, "cmd21152",
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
      backend._PrepareRemoteCommand(self._TEST_PATH, "cmd4617",
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
      backend._PrepareRemoteCommand(self._TEST_PATH, "cmd17577",
                                    _verify_dir=lambda _: (True, None),
                                    _verify_name=lambda _: (True, None),
                                    _verify_cmd=fn)
    self.assertFalse(status)
    self.assertEqual(msg, "test error 25524")

  def testSuccess(self):
    def fn(path, cmd):
      return (True, utils.PathJoin(path, cmd))

    (status, executable) = \
      backend._PrepareRemoteCommand(self._TEST_PATH, "cmd22633",
                                    _verify_dir=lambda _: (True, None),
                                    _verify_name=lambda _: (True, None),
                                    _verify_cmd=fn)
    self.assertTrue(status)
    self.assertEqual(executable, utils.PathJoin(self._TEST_PATH, "cmd22633"))


def _SleepForRemoteCommand(duration):
  assert duration > 5


def _GenericRemoteCommandError(cmd):
  return "Executing command '%s' failed" % cmd


class TestRunRestrictedCmd(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExistantLockDirectory(self):
    lockfile = utils.PathJoin(self.tmpdir, "does", "not", "exist")
    sleep_fn = testutils.CallCounter(_SleepForRemoteCommand)
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
    sleep_fn = testutils.CallCounter(_SleepForRemoteCommand)

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
      assert str(err) == _GenericRemoteCommandError("test22717"), \
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

    sleep_fn = testutils.CallCounter(_SleepForRemoteCommand)
    prepare_fn = testutils.CallCounter(self._PrepareRaisingException)

    try:
      backend.RunRestrictedCmd("test23122",
                               _lock_timeout=1.0, _lock_file=lockfile,
                               _path=NotImplemented, _runcmd_fn=NotImplemented,
                               _sleep_fn=sleep_fn, _prepare_fn=prepare_fn,
                               _enabled=True)
    except backend.RPCFail, err:
      self.assertEqual(str(err), _GenericRemoteCommandError("test23122"))
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

    sleep_fn = testutils.CallCounter(_SleepForRemoteCommand)
    prepare_fn = testutils.CallCounter(self._PrepareFails)

    try:
      backend.RunRestrictedCmd("test29327",
                               _lock_timeout=1.0, _lock_file=lockfile,
                               _path=NotImplemented, _runcmd_fn=NotImplemented,
                               _sleep_fn=sleep_fn, _prepare_fn=prepare_fn,
                               _enabled=True)
    except backend.RPCFail, err:
      self.assertEqual(str(err), _GenericRemoteCommandError("test29327"))
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

    sleep_fn = testutils.CallCounter(_SleepForRemoteCommand)
    prepare_fn = testutils.CallCounter(self._SuccessfulPrepare)
    runcmd_fn = testutils.CallCounter(fn)

    try:
      backend.RunRestrictedCmd("test3079",
                               _lock_timeout=1.0, _lock_file=lockfile,
                               _path=self.tmpdir, _runcmd_fn=runcmd_fn,
                               _sleep_fn=sleep_fn, _prepare_fn=prepare_fn,
                               _enabled=True)
    except backend.RPCFail, err:
      self.assertTrue(str(err).startswith("Remote command 'test3079' failed:"))
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

    sleep_fn = testutils.CallCounter(_SleepForRemoteCommand)
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
      self.assertEqual(str(err), "Remote commands disabled at configure time")
    else:
      self.fail("Did not raise exception")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
