#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Script for unittesting the utils module"""

import errno
import fcntl
import glob
import os
import os.path
import re
import shutil
import signal
import socket
import stat
import tempfile
import time
import unittest
import warnings
import random
import operator

import testutils
from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import errors
from ganeti.utils import RunCmd, \
     FirstFree, \
     RunParts, \
     SetEtcHostsEntry, RemoveEtcHostsEntry


class TestIsProcessAlive(unittest.TestCase):
  """Testing case for IsProcessAlive"""

  def testExists(self):
    mypid = os.getpid()
    self.assert_(utils.IsProcessAlive(mypid), "can't find myself running")

  def testNotExisting(self):
    pid_non_existing = os.fork()
    if pid_non_existing == 0:
      os._exit(0)
    elif pid_non_existing < 0:
      raise SystemError("can't fork")
    os.waitpid(pid_non_existing, 0)
    self.assertFalse(utils.IsProcessAlive(pid_non_existing),
                     "nonexisting process detected")


class TestGetProcStatusPath(unittest.TestCase):
  def test(self):
    self.assert_("/1234/" in utils._GetProcStatusPath(1234))
    self.assertNotEqual(utils._GetProcStatusPath(1),
                        utils._GetProcStatusPath(2))


class TestIsProcessHandlingSignal(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testParseSigsetT(self):
    self.assertEqual(len(utils._ParseSigsetT("0")), 0)
    self.assertEqual(utils._ParseSigsetT("1"), set([1]))
    self.assertEqual(utils._ParseSigsetT("1000a"), set([2, 4, 17]))
    self.assertEqual(utils._ParseSigsetT("810002"), set([2, 17, 24, ]))
    self.assertEqual(utils._ParseSigsetT("0000000180000202"),
                     set([2, 10, 32, 33]))
    self.assertEqual(utils._ParseSigsetT("0000000180000002"),
                     set([2, 32, 33]))
    self.assertEqual(utils._ParseSigsetT("0000000188000002"),
                     set([2, 28, 32, 33]))
    self.assertEqual(utils._ParseSigsetT("000000004b813efb"),
                     set([1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 17,
                          24, 25, 26, 28, 31]))
    self.assertEqual(utils._ParseSigsetT("ffffff"), set(range(1, 25)))

  def testGetProcStatusField(self):
    for field in ["SigCgt", "Name", "FDSize"]:
      for value in ["", "0", "cat", "  1234 KB"]:
        pstatus = "\n".join([
          "VmPeak: 999 kB",
          "%s: %s" % (field, value),
          "TracerPid: 0",
          ])
        result = utils._GetProcStatusField(pstatus, field)
        self.assertEqual(result, value.strip())

  def test(self):
    sp = utils.PathJoin(self.tmpdir, "status")

    utils.WriteFile(sp, data="\n".join([
      "Name:   bash",
      "State:  S (sleeping)",
      "SleepAVG:       98%",
      "Pid:    22250",
      "PPid:   10858",
      "TracerPid:      0",
      "SigBlk: 0000000000010000",
      "SigIgn: 0000000000384004",
      "SigCgt: 000000004b813efb",
      "CapEff: 0000000000000000",
      ]))

    self.assert_(utils.IsProcessHandlingSignal(1234, 10, status_path=sp))

  def testNoSigCgt(self):
    sp = utils.PathJoin(self.tmpdir, "status")

    utils.WriteFile(sp, data="\n".join([
      "Name:   bash",
      ]))

    self.assertRaises(RuntimeError, utils.IsProcessHandlingSignal,
                      1234, 10, status_path=sp)

  def testNoSuchFile(self):
    sp = utils.PathJoin(self.tmpdir, "notexist")

    self.assertFalse(utils.IsProcessHandlingSignal(1234, 10, status_path=sp))

  @staticmethod
  def _TestRealProcess():
    signal.signal(signal.SIGUSR1, signal.SIG_DFL)
    if utils.IsProcessHandlingSignal(os.getpid(), signal.SIGUSR1):
      raise Exception("SIGUSR1 is handled when it should not be")

    signal.signal(signal.SIGUSR1, lambda signum, frame: None)
    if not utils.IsProcessHandlingSignal(os.getpid(), signal.SIGUSR1):
      raise Exception("SIGUSR1 is not handled when it should be")

    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    if utils.IsProcessHandlingSignal(os.getpid(), signal.SIGUSR1):
      raise Exception("SIGUSR1 is not handled when it should be")

    signal.signal(signal.SIGUSR1, signal.SIG_DFL)
    if utils.IsProcessHandlingSignal(os.getpid(), signal.SIGUSR1):
      raise Exception("SIGUSR1 is handled when it should not be")

    return True

  def testRealProcess(self):
    self.assert_(utils.RunInSeparateProcess(self._TestRealProcess))


class TestRunCmd(testutils.GanetiTestCase):
  """Testing case for the RunCmd function"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.magic = time.ctime() + " ganeti test"
    self.fname = self._CreateTempFile()
    self.fifo_tmpdir = tempfile.mkdtemp()
    self.fifo_file = os.path.join(self.fifo_tmpdir, "ganeti_test_fifo")
    os.mkfifo(self.fifo_file)

  def tearDown(self):
    shutil.rmtree(self.fifo_tmpdir)
    testutils.GanetiTestCase.tearDown(self)

  def testOk(self):
    """Test successful exit code"""
    result = RunCmd("/bin/sh -c 'exit 0'")
    self.assertEqual(result.exit_code, 0)
    self.assertEqual(result.output, "")

  def testFail(self):
    """Test fail exit code"""
    result = RunCmd("/bin/sh -c 'exit 1'")
    self.assertEqual(result.exit_code, 1)
    self.assertEqual(result.output, "")

  def testStdout(self):
    """Test standard output"""
    cmd = 'echo -n "%s"' % self.magic
    result = RunCmd("/bin/sh -c '%s'" % cmd)
    self.assertEqual(result.stdout, self.magic)
    result = RunCmd("/bin/sh -c '%s'" % cmd, output=self.fname)
    self.assertEqual(result.output, "")
    self.assertFileContent(self.fname, self.magic)

  def testStderr(self):
    """Test standard error"""
    cmd = 'echo -n "%s"' % self.magic
    result = RunCmd("/bin/sh -c '%s' 1>&2" % cmd)
    self.assertEqual(result.stderr, self.magic)
    result = RunCmd("/bin/sh -c '%s' 1>&2" % cmd, output=self.fname)
    self.assertEqual(result.output, "")
    self.assertFileContent(self.fname, self.magic)

  def testCombined(self):
    """Test combined output"""
    cmd = 'echo -n "A%s"; echo -n "B%s" 1>&2' % (self.magic, self.magic)
    expected = "A" + self.magic + "B" + self.magic
    result = RunCmd("/bin/sh -c '%s'" % cmd)
    self.assertEqual(result.output, expected)
    result = RunCmd("/bin/sh -c '%s'" % cmd, output=self.fname)
    self.assertEqual(result.output, "")
    self.assertFileContent(self.fname, expected)

  def testSignal(self):
    """Test signal"""
    result = RunCmd(["python", "-c", "import os; os.kill(os.getpid(), 15)"])
    self.assertEqual(result.signal, 15)
    self.assertEqual(result.output, "")

  def testTimeoutClean(self):
    cmd = "trap 'exit 0' TERM; read < %s" % self.fifo_file
    result = RunCmd(["/bin/sh", "-c", cmd], timeout=0.2)
    self.assertEqual(result.exit_code, 0)

  def testTimeoutKill(self):
    cmd = ["/bin/sh", "-c", "trap '' TERM; read < %s" % self.fifo_file]
    timeout = 0.2
    out, err, status, ta = utils._RunCmdPipe(cmd, {}, False, "/", False,
                                             timeout, _linger_timeout=0.2)
    self.assert_(status < 0)
    self.assertEqual(-status, signal.SIGKILL)

  def testTimeoutOutputAfterTerm(self):
    cmd = "trap 'echo sigtermed; exit 1' TERM; read < %s" % self.fifo_file
    result = RunCmd(["/bin/sh", "-c", cmd], timeout=0.2)
    self.assert_(result.failed)
    self.assertEqual(result.stdout, "sigtermed\n")

  def testListRun(self):
    """Test list runs"""
    result = RunCmd(["true"])
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 0)
    result = RunCmd(["/bin/sh", "-c", "exit 1"])
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 1)
    result = RunCmd(["echo", "-n", self.magic])
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 0)
    self.assertEqual(result.stdout, self.magic)

  def testFileEmptyOutput(self):
    """Test file output"""
    result = RunCmd(["true"], output=self.fname)
    self.assertEqual(result.signal, None)
    self.assertEqual(result.exit_code, 0)
    self.assertFileContent(self.fname, "")

  def testLang(self):
    """Test locale environment"""
    old_env = os.environ.copy()
    try:
      os.environ["LANG"] = "en_US.UTF-8"
      os.environ["LC_ALL"] = "en_US.UTF-8"
      result = RunCmd(["locale"])
      for line in result.output.splitlines():
        key, value = line.split("=", 1)
        # Ignore these variables, they're overridden by LC_ALL
        if key == "LANG" or key == "LANGUAGE":
          continue
        self.failIf(value and value != "C" and value != '"C"',
            "Variable %s is set to the invalid value '%s'" % (key, value))
    finally:
      os.environ = old_env

  def testDefaultCwd(self):
    """Test default working directory"""
    self.failUnlessEqual(RunCmd(["pwd"]).stdout.strip(), "/")

  def testCwd(self):
    """Test default working directory"""
    self.failUnlessEqual(RunCmd(["pwd"], cwd="/").stdout.strip(), "/")
    self.failUnlessEqual(RunCmd(["pwd"], cwd="/tmp").stdout.strip(), "/tmp")
    cwd = os.getcwd()
    self.failUnlessEqual(RunCmd(["pwd"], cwd=cwd).stdout.strip(), cwd)

  def testResetEnv(self):
    """Test environment reset functionality"""
    self.failUnlessEqual(RunCmd(["env"], reset_env=True).stdout.strip(), "")
    self.failUnlessEqual(RunCmd(["env"], reset_env=True,
                                env={"FOO": "bar",}).stdout.strip(), "FOO=bar")

  def testNoFork(self):
    """Test that nofork raise an error"""
    self.assertFalse(utils._no_fork)
    utils.DisableFork()
    try:
      self.assertTrue(utils._no_fork)
      self.assertRaises(errors.ProgrammerError, RunCmd, ["true"])
    finally:
      utils._no_fork = False

  def testWrongParams(self):
    """Test wrong parameters"""
    self.assertRaises(errors.ProgrammerError, RunCmd, ["true"],
                      output="/dev/null", interactive=True)


class TestRunParts(testutils.GanetiTestCase):
  """Testing case for the RunParts function"""

  def setUp(self):
    self.rundir = tempfile.mkdtemp(prefix="ganeti-test", suffix=".tmp")

  def tearDown(self):
    shutil.rmtree(self.rundir)

  def testEmpty(self):
    """Test on an empty dir"""
    self.failUnlessEqual(RunParts(self.rundir, reset_env=True), [])

  def testSkipWrongName(self):
    """Test that wrong files are skipped"""
    fname = os.path.join(self.rundir, "00test.dot")
    utils.WriteFile(fname, data="")
    os.chmod(fname, stat.S_IREAD | stat.S_IEXEC)
    relname = os.path.basename(fname)
    self.failUnlessEqual(RunParts(self.rundir, reset_env=True),
                         [(relname, constants.RUNPARTS_SKIP, None)])

  def testSkipNonExec(self):
    """Test that non executable files are skipped"""
    fname = os.path.join(self.rundir, "00test")
    utils.WriteFile(fname, data="")
    relname = os.path.basename(fname)
    self.failUnlessEqual(RunParts(self.rundir, reset_env=True),
                         [(relname, constants.RUNPARTS_SKIP, None)])

  def testError(self):
    """Test error on a broken executable"""
    fname = os.path.join(self.rundir, "00test")
    utils.WriteFile(fname, data="")
    os.chmod(fname, stat.S_IREAD | stat.S_IEXEC)
    (relname, status, error) = RunParts(self.rundir, reset_env=True)[0]
    self.failUnlessEqual(relname, os.path.basename(fname))
    self.failUnlessEqual(status, constants.RUNPARTS_ERR)
    self.failUnless(error)

  def testSorted(self):
    """Test executions are sorted"""
    files = []
    files.append(os.path.join(self.rundir, "64test"))
    files.append(os.path.join(self.rundir, "00test"))
    files.append(os.path.join(self.rundir, "42test"))

    for fname in files:
      utils.WriteFile(fname, data="")

    results = RunParts(self.rundir, reset_env=True)

    for fname in sorted(files):
      self.failUnlessEqual(os.path.basename(fname), results.pop(0)[0])

  def testOk(self):
    """Test correct execution"""
    fname = os.path.join(self.rundir, "00test")
    utils.WriteFile(fname, data="#!/bin/sh\n\necho -n ciao")
    os.chmod(fname, stat.S_IREAD | stat.S_IEXEC)
    (relname, status, runresult) = RunParts(self.rundir, reset_env=True)[0]
    self.failUnlessEqual(relname, os.path.basename(fname))
    self.failUnlessEqual(status, constants.RUNPARTS_RUN)
    self.failUnlessEqual(runresult.stdout, "ciao")

  def testRunFail(self):
    """Test correct execution, with run failure"""
    fname = os.path.join(self.rundir, "00test")
    utils.WriteFile(fname, data="#!/bin/sh\n\nexit 1")
    os.chmod(fname, stat.S_IREAD | stat.S_IEXEC)
    (relname, status, runresult) = RunParts(self.rundir, reset_env=True)[0]
    self.failUnlessEqual(relname, os.path.basename(fname))
    self.failUnlessEqual(status, constants.RUNPARTS_RUN)
    self.failUnlessEqual(runresult.exit_code, 1)
    self.failUnless(runresult.failed)

  def testRunMix(self):
    files = []
    files.append(os.path.join(self.rundir, "00test"))
    files.append(os.path.join(self.rundir, "42test"))
    files.append(os.path.join(self.rundir, "64test"))
    files.append(os.path.join(self.rundir, "99test"))

    files.sort()

    # 1st has errors in execution
    utils.WriteFile(files[0], data="#!/bin/sh\n\nexit 1")
    os.chmod(files[0], stat.S_IREAD | stat.S_IEXEC)

    # 2nd is skipped
    utils.WriteFile(files[1], data="")

    # 3rd cannot execute properly
    utils.WriteFile(files[2], data="")
    os.chmod(files[2], stat.S_IREAD | stat.S_IEXEC)

    # 4th execs
    utils.WriteFile(files[3], data="#!/bin/sh\n\necho -n ciao")
    os.chmod(files[3], stat.S_IREAD | stat.S_IEXEC)

    results = RunParts(self.rundir, reset_env=True)

    (relname, status, runresult) = results[0]
    self.failUnlessEqual(relname, os.path.basename(files[0]))
    self.failUnlessEqual(status, constants.RUNPARTS_RUN)
    self.failUnlessEqual(runresult.exit_code, 1)
    self.failUnless(runresult.failed)

    (relname, status, runresult) = results[1]
    self.failUnlessEqual(relname, os.path.basename(files[1]))
    self.failUnlessEqual(status, constants.RUNPARTS_SKIP)
    self.failUnlessEqual(runresult, None)

    (relname, status, runresult) = results[2]
    self.failUnlessEqual(relname, os.path.basename(files[2]))
    self.failUnlessEqual(status, constants.RUNPARTS_ERR)
    self.failUnless(runresult)

    (relname, status, runresult) = results[3]
    self.failUnlessEqual(relname, os.path.basename(files[3]))
    self.failUnlessEqual(status, constants.RUNPARTS_RUN)
    self.failUnlessEqual(runresult.output, "ciao")
    self.failUnlessEqual(runresult.exit_code, 0)
    self.failUnless(not runresult.failed)

  def testMissingDirectory(self):
    nosuchdir = utils.PathJoin(self.rundir, "no/such/directory")
    self.assertEqual(RunParts(nosuchdir), [])


class TestStartDaemon(testutils.GanetiTestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp(prefix="ganeti-test")
    self.tmpfile = os.path.join(self.tmpdir, "test")

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testShell(self):
    utils.StartDaemon("echo Hello World > %s" % self.tmpfile)
    self._wait(self.tmpfile, 60.0, "Hello World")

  def testShellOutput(self):
    utils.StartDaemon("echo Hello World", output=self.tmpfile)
    self._wait(self.tmpfile, 60.0, "Hello World")

  def testNoShellNoOutput(self):
    utils.StartDaemon(["pwd"])

  def testNoShellNoOutputTouch(self):
    testfile = os.path.join(self.tmpdir, "check")
    self.failIf(os.path.exists(testfile))
    utils.StartDaemon(["touch", testfile])
    self._wait(testfile, 60.0, "")

  def testNoShellOutput(self):
    utils.StartDaemon(["pwd"], output=self.tmpfile)
    self._wait(self.tmpfile, 60.0, "/")

  def testNoShellOutputCwd(self):
    utils.StartDaemon(["pwd"], output=self.tmpfile, cwd=os.getcwd())
    self._wait(self.tmpfile, 60.0, os.getcwd())

  def testShellEnv(self):
    utils.StartDaemon("echo \"$GNT_TEST_VAR\"", output=self.tmpfile,
                      env={ "GNT_TEST_VAR": "Hello World", })
    self._wait(self.tmpfile, 60.0, "Hello World")

  def testNoShellEnv(self):
    utils.StartDaemon(["printenv", "GNT_TEST_VAR"], output=self.tmpfile,
                      env={ "GNT_TEST_VAR": "Hello World", })
    self._wait(self.tmpfile, 60.0, "Hello World")

  def testOutputFd(self):
    fd = os.open(self.tmpfile, os.O_WRONLY | os.O_CREAT)
    try:
      utils.StartDaemon(["pwd"], output_fd=fd, cwd=os.getcwd())
    finally:
      os.close(fd)
    self._wait(self.tmpfile, 60.0, os.getcwd())

  def testPid(self):
    pid = utils.StartDaemon("echo $$ > %s" % self.tmpfile)
    self._wait(self.tmpfile, 60.0, str(pid))

  def testPidFile(self):
    pidfile = os.path.join(self.tmpdir, "pid")
    checkfile = os.path.join(self.tmpdir, "abort")

    pid = utils.StartDaemon("while sleep 5; do :; done", pidfile=pidfile,
                            output=self.tmpfile)
    try:
      fd = os.open(pidfile, os.O_RDONLY)
      try:
        # Check file is locked
        self.assertRaises(errors.LockError, utils.LockFile, fd)

        pidtext = os.read(fd, 100)
      finally:
        os.close(fd)

      self.assertEqual(int(pidtext.strip()), pid)

      self.assert_(utils.IsProcessAlive(pid))
    finally:
      # No matter what happens, kill daemon
      utils.KillProcess(pid, timeout=5.0, waitpid=False)
      self.failIf(utils.IsProcessAlive(pid))

    self.assertEqual(utils.ReadFile(self.tmpfile), "")

  def _wait(self, path, timeout, expected):
    # Due to the asynchronous nature of daemon processes, polling is necessary.
    # A timeout makes sure the test doesn't hang forever.
    def _CheckFile():
      if not (os.path.isfile(path) and
              utils.ReadFile(path).strip() == expected):
        raise utils.RetryAgain()

    try:
      utils.Retry(_CheckFile, (0.01, 1.5, 1.0), timeout)
    except utils.RetryTimeout:
      self.fail("Apparently the daemon didn't run in %s seconds and/or"
                " didn't write the correct output" % timeout)

  def testError(self):
    self.assertRaises(errors.OpExecError, utils.StartDaemon,
                      ["./does-NOT-EXIST/here/0123456789"])
    self.assertRaises(errors.OpExecError, utils.StartDaemon,
                      ["./does-NOT-EXIST/here/0123456789"],
                      output=os.path.join(self.tmpdir, "DIR/NOT/EXIST"))
    self.assertRaises(errors.OpExecError, utils.StartDaemon,
                      ["./does-NOT-EXIST/here/0123456789"],
                      cwd=os.path.join(self.tmpdir, "DIR/NOT/EXIST"))
    self.assertRaises(errors.OpExecError, utils.StartDaemon,
                      ["./does-NOT-EXIST/here/0123456789"],
                      output=os.path.join(self.tmpdir, "DIR/NOT/EXIST"))

    fd = os.open(self.tmpfile, os.O_WRONLY | os.O_CREAT)
    try:
      self.assertRaises(errors.ProgrammerError, utils.StartDaemon,
                        ["./does-NOT-EXIST/here/0123456789"],
                        output=self.tmpfile, output_fd=fd)
    finally:
      os.close(fd)


class TestParseCpuMask(unittest.TestCase):
  """Test case for the ParseCpuMask function."""

  def testWellFormed(self):
    self.assertEqual(utils.ParseCpuMask(""), [])
    self.assertEqual(utils.ParseCpuMask("1"), [1])
    self.assertEqual(utils.ParseCpuMask("0-2,4,5-5"), [0,1,2,4,5])

  def testInvalidInput(self):
    for data in ["garbage", "0,", "0-1-2", "2-1", "1-a"]:
      self.assertRaises(errors.ParseError, utils.ParseCpuMask, data)


class TestEtcHosts(testutils.GanetiTestCase):
  """Test functions modifying /etc/hosts"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpname = self._CreateTempFile()
    handle = open(self.tmpname, 'w')
    try:
      handle.write('# This is a test file for /etc/hosts\n')
      handle.write('127.0.0.1\tlocalhost\n')
      handle.write('192.0.2.1 router gw\n')
    finally:
      handle.close()

  def testSettingNewIp(self):
    SetEtcHostsEntry(self.tmpname, '198.51.100.4', 'myhost.example.com',
                     ['myhost'])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router gw\n"
      "198.51.100.4\tmyhost.example.com myhost\n")
    self.assertFileMode(self.tmpname, 0644)

  def testSettingExistingIp(self):
    SetEtcHostsEntry(self.tmpname, '192.0.2.1', 'myhost.example.com',
                     ['myhost'])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1\tmyhost.example.com myhost\n")
    self.assertFileMode(self.tmpname, 0644)

  def testSettingDuplicateName(self):
    SetEtcHostsEntry(self.tmpname, '198.51.100.4', 'myhost', ['myhost'])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router gw\n"
      "198.51.100.4\tmyhost\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingExistingHost(self):
    RemoveEtcHostsEntry(self.tmpname, 'router')

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 gw\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingSingleExistingHost(self):
    RemoveEtcHostsEntry(self.tmpname, 'localhost')

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "192.0.2.1 router gw\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingNonExistingHost(self):
    RemoveEtcHostsEntry(self.tmpname, 'myhost')

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router gw\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingAlias(self):
    RemoveEtcHostsEntry(self.tmpname, 'gw')

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router\n")
    self.assertFileMode(self.tmpname, 0644)


class TestGetMounts(unittest.TestCase):
  """Test case for GetMounts()."""

  TESTDATA = (
    "rootfs /     rootfs rw 0 0\n"
    "none   /sys  sysfs  rw,nosuid,nodev,noexec,relatime 0 0\n"
    "none   /proc proc   rw,nosuid,nodev,noexec,relatime 0 0\n")

  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    utils.WriteFile(self.tmpfile.name, data=self.TESTDATA)

  def testGetMounts(self):
    self.assertEqual(utils.GetMounts(filename=self.tmpfile.name),
      [
        ("rootfs", "/", "rootfs", "rw"),
        ("none", "/sys", "sysfs", "rw,nosuid,nodev,noexec,relatime"),
        ("none", "/proc", "proc", "rw,nosuid,nodev,noexec,relatime"),
      ])

class TestNewUUID(unittest.TestCase):
  """Test case for NewUUID"""

  def runTest(self):
    self.failUnless(utils.UUID_RE.match(utils.NewUUID()))


class TestFirstFree(unittest.TestCase):
  """Test case for the FirstFree function"""

  def test(self):
    """Test FirstFree"""
    self.failUnlessEqual(FirstFree([0, 1, 3]), 2)
    self.failUnlessEqual(FirstFree([]), None)
    self.failUnlessEqual(FirstFree([3, 4, 6]), 0)
    self.failUnlessEqual(FirstFree([3, 4, 6], base=3), 5)
    self.failUnlessRaises(AssertionError, FirstFree, [0, 3, 4, 6], base=3)


class TestTimeFunctions(unittest.TestCase):
  """Test case for time functions"""

  def runTest(self):
    self.assertEqual(utils.SplitTime(1), (1, 0))
    self.assertEqual(utils.SplitTime(1.5), (1, 500000))
    self.assertEqual(utils.SplitTime(1218448917.4809151), (1218448917, 480915))
    self.assertEqual(utils.SplitTime(123.48012), (123, 480120))
    self.assertEqual(utils.SplitTime(123.9996), (123, 999600))
    self.assertEqual(utils.SplitTime(123.9995), (123, 999500))
    self.assertEqual(utils.SplitTime(123.9994), (123, 999400))
    self.assertEqual(utils.SplitTime(123.999999999), (123, 999999))

    self.assertRaises(AssertionError, utils.SplitTime, -1)

    self.assertEqual(utils.MergeTime((1, 0)), 1.0)
    self.assertEqual(utils.MergeTime((1, 500000)), 1.5)
    self.assertEqual(utils.MergeTime((1218448917, 500000)), 1218448917.5)

    self.assertEqual(round(utils.MergeTime((1218448917, 481000)), 3),
                     1218448917.481)
    self.assertEqual(round(utils.MergeTime((1, 801000)), 3), 1.801)

    self.assertRaises(AssertionError, utils.MergeTime, (0, -1))
    self.assertRaises(AssertionError, utils.MergeTime, (0, 1000000))
    self.assertRaises(AssertionError, utils.MergeTime, (0, 9999999))
    self.assertRaises(AssertionError, utils.MergeTime, (-1, 0))
    self.assertRaises(AssertionError, utils.MergeTime, (-9999, 0))


class FieldSetTestCase(unittest.TestCase):
  """Test case for FieldSets"""

  def testSimpleMatch(self):
    f = utils.FieldSet("a", "b", "c", "def")
    self.failUnless(f.Matches("a"))
    self.failIf(f.Matches("d"), "Substring matched")
    self.failIf(f.Matches("defghi"), "Prefix string matched")
    self.failIf(f.NonMatching(["b", "c"]))
    self.failIf(f.NonMatching(["a", "b", "c", "def"]))
    self.failUnless(f.NonMatching(["a", "d"]))

  def testRegexMatch(self):
    f = utils.FieldSet("a", "b([0-9]+)", "c")
    self.failUnless(f.Matches("b1"))
    self.failUnless(f.Matches("b99"))
    self.failIf(f.Matches("b/1"))
    self.failIf(f.NonMatching(["b12", "c"]))
    self.failUnless(f.NonMatching(["a", "1"]))

class TestForceDictType(unittest.TestCase):
  """Test case for ForceDictType"""
  KEY_TYPES = {
    "a": constants.VTYPE_INT,
    "b": constants.VTYPE_BOOL,
    "c": constants.VTYPE_STRING,
    "d": constants.VTYPE_SIZE,
    "e": constants.VTYPE_MAYBE_STRING,
    }

  def _fdt(self, dict, allowed_values=None):
    if allowed_values is None:
      utils.ForceDictType(dict, self.KEY_TYPES)
    else:
      utils.ForceDictType(dict, self.KEY_TYPES, allowed_values=allowed_values)

    return dict

  def testSimpleDict(self):
    self.assertEqual(self._fdt({}), {})
    self.assertEqual(self._fdt({'a': 1}), {'a': 1})
    self.assertEqual(self._fdt({'a': '1'}), {'a': 1})
    self.assertEqual(self._fdt({'a': 1, 'b': 1}), {'a':1, 'b': True})
    self.assertEqual(self._fdt({'b': 1, 'c': 'foo'}), {'b': True, 'c': 'foo'})
    self.assertEqual(self._fdt({'b': 1, 'c': False}), {'b': True, 'c': ''})
    self.assertEqual(self._fdt({'b': 'false'}), {'b': False})
    self.assertEqual(self._fdt({'b': 'False'}), {'b': False})
    self.assertEqual(self._fdt({'b': False}), {'b': False})
    self.assertEqual(self._fdt({'b': 'true'}), {'b': True})
    self.assertEqual(self._fdt({'b': 'True'}), {'b': True})
    self.assertEqual(self._fdt({'d': '4'}), {'d': 4})
    self.assertEqual(self._fdt({'d': '4M'}), {'d': 4})
    self.assertEqual(self._fdt({"e": None, }), {"e": None, })
    self.assertEqual(self._fdt({"e": "Hello World", }), {"e": "Hello World", })
    self.assertEqual(self._fdt({"e": False, }), {"e": '', })
    self.assertEqual(self._fdt({"b": "hello", }, ["hello"]), {"b": "hello"})

  def testErrors(self):
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'a': 'astring'})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"b": "hello"})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'c': True})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'d': 'astring'})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {'d': '4 L'})
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"e": object(), })
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"e": [], })
    self.assertRaises(errors.TypeEnforcementError, self._fdt, {"x": None, })
    self.assertRaises(errors.TypeEnforcementError, self._fdt, [])
    self.assertRaises(errors.ProgrammerError, utils.ForceDictType,
                      {"b": "hello"}, {"b": "no-such-type"})


class RunInSeparateProcess(unittest.TestCase):
  def test(self):
    for exp in [True, False]:
      def _child():
        return exp

      self.assertEqual(exp, utils.RunInSeparateProcess(_child))

  def testArgs(self):
    for arg in [0, 1, 999, "Hello World", (1, 2, 3)]:
      def _child(carg1, carg2):
        return carg1 == "Foo" and carg2 == arg

      self.assert_(utils.RunInSeparateProcess(_child, "Foo", arg))

  def testPid(self):
    parent_pid = os.getpid()

    def _check():
      return os.getpid() == parent_pid

    self.failIf(utils.RunInSeparateProcess(_check))

  def testSignal(self):
    def _kill():
      os.kill(os.getpid(), signal.SIGTERM)

    self.assertRaises(errors.GenericError,
                      utils.RunInSeparateProcess, _kill)

  def testException(self):
    def _exc():
      raise errors.GenericError("This is a test")

    self.assertRaises(errors.GenericError,
                      utils.RunInSeparateProcess, _exc)


class TestValidateServiceName(unittest.TestCase):
  def testValid(self):
    testnames = [
      0, 1, 2, 3, 1024, 65000, 65534, 65535,
      "ganeti",
      "gnt-masterd",
      "HELLO_WORLD_SVC",
      "hello.world.1",
      "0", "80", "1111", "65535",
      ]

    for name in testnames:
      self.assertEqual(utils.ValidateServiceName(name), name)

  def testInvalid(self):
    testnames = [
      -15756, -1, 65536, 133428083,
      "", "Hello World!", "!", "'", "\"", "\t", "\n", "`",
      "-8546", "-1", "65536",
      (129 * "A"),
      ]

    for name in testnames:
      self.assertRaises(errors.OpPrereqError, utils.ValidateServiceName, name)


class TestReadLockedPidFile(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExistent(self):
    path = utils.PathJoin(self.tmpdir, "nonexist")
    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testUnlocked(self):
    path = utils.PathJoin(self.tmpdir, "pid")
    utils.WriteFile(path, data="123")
    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testLocked(self):
    path = utils.PathJoin(self.tmpdir, "pid")
    utils.WriteFile(path, data="123")

    fl = utils.FileLock.Open(path)
    try:
      fl.Exclusive(blocking=True)

      self.assertEqual(utils.ReadLockedPidFile(path), 123)
    finally:
      fl.Close()

    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testError(self):
    path = utils.PathJoin(self.tmpdir, "foobar", "pid")
    utils.WriteFile(utils.PathJoin(self.tmpdir, "foobar"), data="")
    # open(2) should return ENOTDIR
    self.assertRaises(EnvironmentError, utils.ReadLockedPidFile, path)


class TestFindMatch(unittest.TestCase):
  def test(self):
    data = {
      "aaaa": "Four A",
      "bb": {"Two B": True},
      re.compile(r"^x(foo|bar|bazX)([0-9]+)$"): (1, 2, 3),
      }

    self.assertEqual(utils.FindMatch(data, "aaaa"), ("Four A", []))
    self.assertEqual(utils.FindMatch(data, "bb"), ({"Two B": True}, []))

    for i in ["foo", "bar", "bazX"]:
      for j in range(1, 100, 7):
        self.assertEqual(utils.FindMatch(data, "x%s%s" % (i, j)),
                         ((1, 2, 3), [i, str(j)]))

  def testNoMatch(self):
    self.assert_(utils.FindMatch({}, "") is None)
    self.assert_(utils.FindMatch({}, "foo") is None)
    self.assert_(utils.FindMatch({}, 1234) is None)

    data = {
      "X": "Hello World",
      re.compile("^(something)$"): "Hello World",
      }

    self.assert_(utils.FindMatch(data, "") is None)
    self.assert_(utils.FindMatch(data, "Hello World") is None)


class TimeMock:
  def __init__(self, values):
    self.values = values

  def __call__(self):
    return self.values.pop(0)


class TestRunningTimeout(unittest.TestCase):
  def setUp(self):
    self.time_fn = TimeMock([0.0, 0.3, 4.6, 6.5])

  def testRemainingFloat(self):
    timeout = utils.RunningTimeout(5.0, True, _time_fn=self.time_fn)
    self.assertAlmostEqual(timeout.Remaining(), 4.7)
    self.assertAlmostEqual(timeout.Remaining(), 0.4)
    self.assertAlmostEqual(timeout.Remaining(), -1.5)

  def testRemaining(self):
    self.time_fn = TimeMock([0, 2, 4, 5, 6])
    timeout = utils.RunningTimeout(5, True, _time_fn=self.time_fn)
    self.assertEqual(timeout.Remaining(), 3)
    self.assertEqual(timeout.Remaining(), 1)
    self.assertEqual(timeout.Remaining(), 0)
    self.assertEqual(timeout.Remaining(), -1)

  def testRemainingNonNegative(self):
    timeout = utils.RunningTimeout(5.0, False, _time_fn=self.time_fn)
    self.assertAlmostEqual(timeout.Remaining(), 4.7)
    self.assertAlmostEqual(timeout.Remaining(), 0.4)
    self.assertEqual(timeout.Remaining(), 0.0)

  def testNegativeTimeout(self):
    self.assertRaises(ValueError, utils.RunningTimeout, -1.0, True)


class TestTryConvert(unittest.TestCase):
  def test(self):
    for src, fn, result in [
      ("1", int, 1),
      ("a", int, "a"),
      ("", bool, False),
      ("a", bool, True),
      ]:
      self.assertEqual(utils.TryConvert(fn, src), result)


class TestIsValidShellParam(unittest.TestCase):
  def test(self):
    for val, result in [
      ("abc", True),
      ("ab;cd", False),
      ]:
      self.assertEqual(utils.IsValidShellParam(val), result)


class TestBuildShellCmd(unittest.TestCase):
  def test(self):
    self.assertRaises(errors.ProgrammerError, utils.BuildShellCmd,
                      "ls %s", "ab;cd")
    self.assertEqual(utils.BuildShellCmd("ls %s", "ab"), "ls ab")


if __name__ == '__main__':
  testutils.GanetiTestProgram()
