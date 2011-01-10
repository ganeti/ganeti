#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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

import distutils.version
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
import string
import tempfile
import time
import unittest
import warnings
import OpenSSL
import random
import operator

import testutils
from ganeti import constants
from ganeti import compat
from ganeti import utils
from ganeti import errors
from ganeti.utils import RunCmd, RemoveFile, \
     ListVisibleFiles, FirstFree, \
     TailFile, RunParts, PathJoin, \
     ReadOneLineFile, SetEtcHostsEntry, RemoveEtcHostsEntry


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
    sp = PathJoin(self.tmpdir, "status")

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
    sp = PathJoin(self.tmpdir, "status")

    utils.WriteFile(sp, data="\n".join([
      "Name:   bash",
      ]))

    self.assertRaises(RuntimeError, utils.IsProcessHandlingSignal,
                      1234, 10, status_path=sp)

  def testNoSuchFile(self):
    sp = PathJoin(self.tmpdir, "notexist")

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


class TestPidFileFunctions(unittest.TestCase):
  """Tests for WritePidFile, RemovePidFile and ReadPidFile"""

  def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.f_dpn = lambda name: os.path.join(self.dir, "%s.pid" % name)
    utils.DaemonPidFileName = self.f_dpn

  def testPidFileFunctions(self):
    pid_file = self.f_dpn('test')
    fd = utils.WritePidFile(self.f_dpn('test'))
    self.failUnless(os.path.exists(pid_file),
                    "PID file should have been created")
    read_pid = utils.ReadPidFile(pid_file)
    self.failUnlessEqual(read_pid, os.getpid())
    self.failUnless(utils.IsProcessAlive(read_pid))
    self.failUnlessRaises(errors.LockError, utils.WritePidFile,
                          self.f_dpn('test'))
    os.close(fd)
    utils.RemovePidFile('test')
    self.failIf(os.path.exists(pid_file),
                "PID file should not exist anymore")
    self.failUnlessEqual(utils.ReadPidFile(pid_file), 0,
                         "ReadPidFile should return 0 for missing pid file")
    fh = open(pid_file, "w")
    fh.write("blah\n")
    fh.close()
    self.failUnlessEqual(utils.ReadPidFile(pid_file), 0,
                         "ReadPidFile should return 0 for invalid pid file")
    # but now, even with the file existing, we should be able to lock it
    fd = utils.WritePidFile(self.f_dpn('test'))
    os.close(fd)
    utils.RemovePidFile('test')
    self.failIf(os.path.exists(pid_file),
                "PID file should not exist anymore")

  def testKill(self):
    pid_file = self.f_dpn('child')
    r_fd, w_fd = os.pipe()
    new_pid = os.fork()
    if new_pid == 0: #child
      utils.WritePidFile(self.f_dpn('child'))
      os.write(w_fd, 'a')
      signal.pause()
      os._exit(0)
      return
    # else we are in the parent
    # wait until the child has written the pid file
    os.read(r_fd, 1)
    read_pid = utils.ReadPidFile(pid_file)
    self.failUnlessEqual(read_pid, new_pid)
    self.failUnless(utils.IsProcessAlive(new_pid))
    utils.KillProcess(new_pid, waitpid=True)
    self.failIf(utils.IsProcessAlive(new_pid))
    utils.RemovePidFile('child')
    self.failUnlessRaises(errors.ProgrammerError, utils.KillProcess, 0)

  def tearDown(self):
    for name in os.listdir(self.dir):
      os.unlink(os.path.join(self.dir, name))
    os.rmdir(self.dir)


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
    assert not utils.no_fork
    utils.no_fork = True
    try:
      self.assertRaises(errors.ProgrammerError, RunCmd, ["true"])
    finally:
      utils.no_fork = False

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


class TestSetCloseOnExecFlag(unittest.TestCase):
  """Tests for SetCloseOnExecFlag"""

  def setUp(self):
    self.tmpfile = tempfile.TemporaryFile()

  def testEnable(self):
    utils.SetCloseOnExecFlag(self.tmpfile.fileno(), True)
    self.failUnless(fcntl.fcntl(self.tmpfile.fileno(), fcntl.F_GETFD) &
                    fcntl.FD_CLOEXEC)

  def testDisable(self):
    utils.SetCloseOnExecFlag(self.tmpfile.fileno(), False)
    self.failIf(fcntl.fcntl(self.tmpfile.fileno(), fcntl.F_GETFD) &
                fcntl.FD_CLOEXEC)


class TestSetNonblockFlag(unittest.TestCase):
  def setUp(self):
    self.tmpfile = tempfile.TemporaryFile()

  def testEnable(self):
    utils.SetNonblockFlag(self.tmpfile.fileno(), True)
    self.failUnless(fcntl.fcntl(self.tmpfile.fileno(), fcntl.F_GETFL) &
                    os.O_NONBLOCK)

  def testDisable(self):
    utils.SetNonblockFlag(self.tmpfile.fileno(), False)
    self.failIf(fcntl.fcntl(self.tmpfile.fileno(), fcntl.F_GETFL) &
                os.O_NONBLOCK)


class TestRemoveFile(unittest.TestCase):
  """Test case for the RemoveFile function"""

  def setUp(self):
    """Create a temp dir and file for each case"""
    self.tmpdir = tempfile.mkdtemp('', 'ganeti-unittest-')
    fd, self.tmpfile = tempfile.mkstemp('', '', self.tmpdir)
    os.close(fd)

  def tearDown(self):
    if os.path.exists(self.tmpfile):
      os.unlink(self.tmpfile)
    os.rmdir(self.tmpdir)

  def testIgnoreDirs(self):
    """Test that RemoveFile() ignores directories"""
    self.assertEqual(None, RemoveFile(self.tmpdir))

  def testIgnoreNotExisting(self):
    """Test that RemoveFile() ignores non-existing files"""
    RemoveFile(self.tmpfile)
    RemoveFile(self.tmpfile)

  def testRemoveFile(self):
    """Test that RemoveFile does remove a file"""
    RemoveFile(self.tmpfile)
    if os.path.exists(self.tmpfile):
      self.fail("File '%s' not removed" % self.tmpfile)

  def testRemoveSymlink(self):
    """Test that RemoveFile does remove symlinks"""
    symlink = self.tmpdir + "/symlink"
    os.symlink("no-such-file", symlink)
    RemoveFile(symlink)
    if os.path.exists(symlink):
      self.fail("File '%s' not removed" % symlink)
    os.symlink(self.tmpfile, symlink)
    RemoveFile(symlink)
    if os.path.exists(symlink):
      self.fail("File '%s' not removed" % symlink)


class TestRemoveDir(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    try:
      shutil.rmtree(self.tmpdir)
    except EnvironmentError:
      pass

  def testEmptyDir(self):
    utils.RemoveDir(self.tmpdir)
    self.assertFalse(os.path.isdir(self.tmpdir))

  def testNonEmptyDir(self):
    self.tmpfile = os.path.join(self.tmpdir, "test1")
    open(self.tmpfile, "w").close()
    self.assertRaises(EnvironmentError, utils.RemoveDir, self.tmpdir)


class TestRename(unittest.TestCase):
  """Test case for RenameFile"""

  def setUp(self):
    """Create a temporary directory"""
    self.tmpdir = tempfile.mkdtemp()
    self.tmpfile = os.path.join(self.tmpdir, "test1")

    # Touch the file
    open(self.tmpfile, "w").close()

  def tearDown(self):
    """Remove temporary directory"""
    shutil.rmtree(self.tmpdir)

  def testSimpleRename1(self):
    """Simple rename 1"""
    utils.RenameFile(self.tmpfile, os.path.join(self.tmpdir, "xyz"))
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "xyz")))

  def testSimpleRename2(self):
    """Simple rename 2"""
    utils.RenameFile(self.tmpfile, os.path.join(self.tmpdir, "xyz"),
                     mkdir=True)
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "xyz")))

  def testRenameMkdir(self):
    """Rename with mkdir"""
    utils.RenameFile(self.tmpfile, os.path.join(self.tmpdir, "test/xyz"),
                     mkdir=True)
    self.assert_(os.path.isdir(os.path.join(self.tmpdir, "test")))
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "test/xyz")))

    utils.RenameFile(os.path.join(self.tmpdir, "test/xyz"),
                     os.path.join(self.tmpdir, "test/foo/bar/baz"),
                     mkdir=True)
    self.assert_(os.path.isdir(os.path.join(self.tmpdir, "test")))
    self.assert_(os.path.isdir(os.path.join(self.tmpdir, "test/foo/bar")))
    self.assert_(os.path.isfile(os.path.join(self.tmpdir, "test/foo/bar/baz")))


class TestReadFile(testutils.GanetiTestCase):

  def testReadAll(self):
    data = utils.ReadFile(self._TestDataFilename("cert1.pem"))
    self.assertEqual(len(data), 814)

    h = compat.md5_hash()
    h.update(data)
    self.assertEqual(h.hexdigest(), "a491efb3efe56a0535f924d5f8680fd4")

  def testReadSize(self):
    data = utils.ReadFile(self._TestDataFilename("cert1.pem"),
                          size=100)
    self.assertEqual(len(data), 100)

    h = compat.md5_hash()
    h.update(data)
    self.assertEqual(h.hexdigest(), "893772354e4e690b9efd073eed433ce7")

  def testError(self):
    self.assertRaises(EnvironmentError, utils.ReadFile,
                      "/dev/null/does-not-exist")


class TestReadOneLineFile(testutils.GanetiTestCase):

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

  def testDefault(self):
    data = ReadOneLineFile(self._TestDataFilename("cert1.pem"))
    self.assertEqual(len(data), 27)
    self.assertEqual(data, "-----BEGIN CERTIFICATE-----")

  def testNotStrict(self):
    data = ReadOneLineFile(self._TestDataFilename("cert1.pem"), strict=False)
    self.assertEqual(len(data), 27)
    self.assertEqual(data, "-----BEGIN CERTIFICATE-----")

  def testStrictFailure(self):
    self.assertRaises(errors.GenericError, ReadOneLineFile,
                      self._TestDataFilename("cert1.pem"), strict=True)

  def testLongLine(self):
    dummydata = (1024 * "Hello World! ")
    myfile = self._CreateTempFile()
    utils.WriteFile(myfile, data=dummydata)
    datastrict = ReadOneLineFile(myfile, strict=True)
    datalax = ReadOneLineFile(myfile, strict=False)
    self.assertEqual(dummydata, datastrict)
    self.assertEqual(dummydata, datalax)

  def testNewline(self):
    myfile = self._CreateTempFile()
    myline = "myline"
    for nl in ["", "\n", "\r\n"]:
      dummydata = "%s%s" % (myline, nl)
      utils.WriteFile(myfile, data=dummydata)
      datalax = ReadOneLineFile(myfile, strict=False)
      self.assertEqual(myline, datalax)
      datastrict = ReadOneLineFile(myfile, strict=True)
      self.assertEqual(myline, datastrict)

  def testWhitespaceAndMultipleLines(self):
    myfile = self._CreateTempFile()
    for nl in ["", "\n", "\r\n"]:
      for ws in [" ", "\t", "\t\t  \t", "\t "]:
        dummydata = (1024 * ("Foo bar baz %s%s" % (ws, nl)))
        utils.WriteFile(myfile, data=dummydata)
        datalax = ReadOneLineFile(myfile, strict=False)
        if nl:
          self.assert_(set("\r\n") & set(dummydata))
          self.assertRaises(errors.GenericError, ReadOneLineFile,
                            myfile, strict=True)
          explen = len("Foo bar baz ") + len(ws)
          self.assertEqual(len(datalax), explen)
          self.assertEqual(datalax, dummydata[:explen])
          self.assertFalse(set("\r\n") & set(datalax))
        else:
          datastrict = ReadOneLineFile(myfile, strict=True)
          self.assertEqual(dummydata, datastrict)
          self.assertEqual(dummydata, datalax)

  def testEmptylines(self):
    myfile = self._CreateTempFile()
    myline = "myline"
    for nl in ["\n", "\r\n"]:
      for ol in ["", "otherline"]:
        dummydata = "%s%s%s%s%s%s" % (nl, nl, myline, nl, ol, nl)
        utils.WriteFile(myfile, data=dummydata)
        self.assert_(set("\r\n") & set(dummydata))
        datalax = ReadOneLineFile(myfile, strict=False)
        self.assertEqual(myline, datalax)
        if ol:
          self.assertRaises(errors.GenericError, ReadOneLineFile,
                            myfile, strict=True)
        else:
          datastrict = ReadOneLineFile(myfile, strict=True)
          self.assertEqual(myline, datastrict)

  def testEmptyfile(self):
    myfile = self._CreateTempFile()
    self.assertRaises(errors.GenericError, ReadOneLineFile, myfile)


class TestTimestampForFilename(unittest.TestCase):
  def test(self):
    self.assert_("." not in utils.TimestampForFilename())
    self.assert_(":" not in utils.TimestampForFilename())


class TestCreateBackup(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)

    shutil.rmtree(self.tmpdir)

  def testEmpty(self):
    filename = PathJoin(self.tmpdir, "config.data")
    utils.WriteFile(filename, data="")
    bname = utils.CreateBackup(filename)
    self.assertFileContent(bname, "")
    self.assertEqual(len(glob.glob("%s*" % filename)), 2)
    utils.CreateBackup(filename)
    self.assertEqual(len(glob.glob("%s*" % filename)), 3)
    utils.CreateBackup(filename)
    self.assertEqual(len(glob.glob("%s*" % filename)), 4)

    fifoname = PathJoin(self.tmpdir, "fifo")
    os.mkfifo(fifoname)
    self.assertRaises(errors.ProgrammerError, utils.CreateBackup, fifoname)

  def testContent(self):
    bkpcount = 0
    for data in ["", "X", "Hello World!\n" * 100, "Binary data\0\x01\x02\n"]:
      for rep in [1, 2, 10, 127]:
        testdata = data * rep

        filename = PathJoin(self.tmpdir, "test.data_")
        utils.WriteFile(filename, data=testdata)
        self.assertFileContent(filename, testdata)

        for _ in range(3):
          bname = utils.CreateBackup(filename)
          bkpcount += 1
          self.assertFileContent(bname, testdata)
          self.assertEqual(len(glob.glob("%s*" % filename)), 1 + bkpcount)


class TestParseCpuMask(unittest.TestCase):
  """Test case for the ParseCpuMask function."""

  def testWellFormed(self):
    self.assertEqual(utils.ParseCpuMask(""), [])
    self.assertEqual(utils.ParseCpuMask("1"), [1])
    self.assertEqual(utils.ParseCpuMask("0-2,4,5-5"), [0,1,2,4,5])

  def testInvalidInput(self):
    for data in ["garbage", "0,", "0-1-2", "2-1", "1-a"]:
      self.assertRaises(errors.ParseError, utils.ParseCpuMask, data)


class TestSshKeys(testutils.GanetiTestCase):
  """Test case for the AddAuthorizedKey function"""

  KEY_A = 'ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a'
  KEY_B = ('command="/usr/bin/fooserver -t --verbose",from="198.51.100.4" '
           'ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b')

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpname = self._CreateTempFile()
    handle = open(self.tmpname, 'w')
    try:
      handle.write("%s\n" % TestSshKeys.KEY_A)
      handle.write("%s\n" % TestSshKeys.KEY_B)
    finally:
      handle.close()

  def testAddingNewKey(self):
    utils.AddAuthorizedKey(self.tmpname,
                           'ssh-dss AAAAB3NzaC1kc3MAAACB root@test')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1kc3MAAACB root@test\n")

  def testAddingAlmostButNotCompletelyTheSameKey(self):
    utils.AddAuthorizedKey(self.tmpname,
        'ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@test')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n"
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@test\n")

  def testAddingExistingKeyWithSomeMoreSpaces(self):
    utils.AddAuthorizedKey(self.tmpname,
        'ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")

  def testRemovingExistingKeyWithSomeMoreSpaces(self):
    utils.RemoveAuthorizedKey(self.tmpname,
        'ssh-dss  AAAAB3NzaC1w5256closdj32mZaQU   root@key-a')

    self.assertFileContent(self.tmpname,
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")

  def testRemovingNonExistingKey(self):
    utils.RemoveAuthorizedKey(self.tmpname,
        'ssh-dss  AAAAB3Nsdfj230xxjxJjsjwjsjdjU   root@test')

    self.assertFileContent(self.tmpname,
      "ssh-dss AAAAB3NzaC1w5256closdj32mZaQU root@key-a\n"
      'command="/usr/bin/fooserver -t --verbose",from="198.51.100.4"'
      " ssh-dss AAAAB3NzaC1w520smc01ms0jfJs22 root@key-b\n")


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


class TestListVisibleFiles(unittest.TestCase):
  """Test case for ListVisibleFiles"""

  def setUp(self):
    self.path = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.path)

  def _CreateFiles(self, files):
    for name in files:
      utils.WriteFile(os.path.join(self.path, name), data="test")

  def _test(self, files, expected):
    self._CreateFiles(files)
    found = ListVisibleFiles(self.path)
    self.assertEqual(set(found), set(expected))

  def testAllVisible(self):
    files = ["a", "b", "c"]
    expected = files
    self._test(files, expected)

  def testNoneVisible(self):
    files = [".a", ".b", ".c"]
    expected = []
    self._test(files, expected)

  def testSomeVisible(self):
    files = ["a", "b", ".c"]
    expected = ["a", "b"]
    self._test(files, expected)

  def testNonAbsolutePath(self):
    self.failUnlessRaises(errors.ProgrammerError, ListVisibleFiles, "abc")

  def testNonNormalizedPath(self):
    self.failUnlessRaises(errors.ProgrammerError, ListVisibleFiles,
                          "/bin/../tmp")


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


class TestTailFile(testutils.GanetiTestCase):
  """Test case for the TailFile function"""

  def testEmpty(self):
    fname = self._CreateTempFile()
    self.failUnlessEqual(TailFile(fname), [])
    self.failUnlessEqual(TailFile(fname, lines=25), [])

  def testAllLines(self):
    data = ["test %d" % i for i in range(30)]
    for i in range(30):
      fname = self._CreateTempFile()
      fd = open(fname, "w")
      fd.write("\n".join(data[:i]))
      if i > 0:
        fd.write("\n")
      fd.close()
      self.failUnlessEqual(TailFile(fname, lines=i), data[:i])

  def testPartialLines(self):
    data = ["test %d" % i for i in range(30)]
    fname = self._CreateTempFile()
    fd = open(fname, "w")
    fd.write("\n".join(data))
    fd.write("\n")
    fd.close()
    for i in range(1, 30):
      self.failUnlessEqual(TailFile(fname, lines=i), data[-i:])

  def testBigFile(self):
    data = ["test %d" % i for i in range(30)]
    fname = self._CreateTempFile()
    fd = open(fname, "w")
    fd.write("X" * 1048576)
    fd.write("\n")
    fd.write("\n".join(data))
    fd.write("\n")
    fd.close()
    for i in range(1, 30):
      self.failUnlessEqual(TailFile(fname, lines=i), data[-i:])


class _BaseFileLockTest:
  """Test case for the FileLock class"""

  def testSharedNonblocking(self):
    self.lock.Shared(blocking=False)
    self.lock.Close()

  def testExclusiveNonblocking(self):
    self.lock.Exclusive(blocking=False)
    self.lock.Close()

  def testUnlockNonblocking(self):
    self.lock.Unlock(blocking=False)
    self.lock.Close()

  def testSharedBlocking(self):
    self.lock.Shared(blocking=True)
    self.lock.Close()

  def testExclusiveBlocking(self):
    self.lock.Exclusive(blocking=True)
    self.lock.Close()

  def testUnlockBlocking(self):
    self.lock.Unlock(blocking=True)
    self.lock.Close()

  def testSharedExclusiveUnlock(self):
    self.lock.Shared(blocking=False)
    self.lock.Exclusive(blocking=False)
    self.lock.Unlock(blocking=False)
    self.lock.Close()

  def testExclusiveSharedUnlock(self):
    self.lock.Exclusive(blocking=False)
    self.lock.Shared(blocking=False)
    self.lock.Unlock(blocking=False)
    self.lock.Close()

  def testSimpleTimeout(self):
    # These will succeed on the first attempt, hence a short timeout
    self.lock.Shared(blocking=True, timeout=10.0)
    self.lock.Exclusive(blocking=False, timeout=10.0)
    self.lock.Unlock(blocking=True, timeout=10.0)
    self.lock.Close()

  @staticmethod
  def _TryLockInner(filename, shared, blocking):
    lock = utils.FileLock.Open(filename)

    if shared:
      fn = lock.Shared
    else:
      fn = lock.Exclusive

    try:
      # The timeout doesn't really matter as the parent process waits for us to
      # finish anyway.
      fn(blocking=blocking, timeout=0.01)
    except errors.LockError, err:
      return False

    return True

  def _TryLock(self, *args):
    return utils.RunInSeparateProcess(self._TryLockInner, self.tmpfile.name,
                                      *args)

  def testTimeout(self):
    for blocking in [True, False]:
      self.lock.Exclusive(blocking=True)
      self.failIf(self._TryLock(False, blocking))
      self.failIf(self._TryLock(True, blocking))

      self.lock.Shared(blocking=True)
      self.assert_(self._TryLock(True, blocking))
      self.failIf(self._TryLock(False, blocking))

  def testCloseShared(self):
    self.lock.Close()
    self.assertRaises(AssertionError, self.lock.Shared, blocking=False)

  def testCloseExclusive(self):
    self.lock.Close()
    self.assertRaises(AssertionError, self.lock.Exclusive, blocking=False)

  def testCloseUnlock(self):
    self.lock.Close()
    self.assertRaises(AssertionError, self.lock.Unlock, blocking=False)


class TestFileLockWithFilename(testutils.GanetiTestCase, _BaseFileLockTest):
  TESTDATA = "Hello World\n" * 10

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpfile = tempfile.NamedTemporaryFile()
    utils.WriteFile(self.tmpfile.name, data=self.TESTDATA)
    self.lock = utils.FileLock.Open(self.tmpfile.name)

    # Ensure "Open" didn't truncate file
    self.assertFileContent(self.tmpfile.name, self.TESTDATA)

  def tearDown(self):
    self.assertFileContent(self.tmpfile.name, self.TESTDATA)

    testutils.GanetiTestCase.tearDown(self)


class TestFileLockWithFileObject(unittest.TestCase, _BaseFileLockTest):
  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    self.lock = utils.FileLock(open(self.tmpfile.name, "w"), self.tmpfile.name)


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


class TestIsNormAbsPath(unittest.TestCase):
  """Testing case for IsNormAbsPath"""

  def _pathTestHelper(self, path, result):
    if result:
      self.assert_(utils.IsNormAbsPath(path),
          "Path %s should result absolute and normalized" % path)
    else:
      self.assertFalse(utils.IsNormAbsPath(path),
          "Path %s should not result absolute and normalized" % path)

  def testBase(self):
    self._pathTestHelper('/etc', True)
    self._pathTestHelper('/srv', True)
    self._pathTestHelper('etc', False)
    self._pathTestHelper('/etc/../root', False)
    self._pathTestHelper('/etc/', False)


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


class TestFingerprintFiles(unittest.TestCase):
  def setUp(self):
    self.tmpfile = tempfile.NamedTemporaryFile()
    self.tmpfile2 = tempfile.NamedTemporaryFile()
    utils.WriteFile(self.tmpfile2.name, data="Hello World\n")
    self.results = {
      self.tmpfile.name: "da39a3ee5e6b4b0d3255bfef95601890afd80709",
      self.tmpfile2.name: "648a6a6ffffdaa0badb23b8baf90b6168dd16b3a",
      }

  def testSingleFile(self):
    self.assertEqual(utils._FingerprintFile(self.tmpfile.name),
                     self.results[self.tmpfile.name])

    self.assertEqual(utils._FingerprintFile("/no/such/file"), None)

  def testBigFile(self):
    self.tmpfile.write("A" * 8192)
    self.tmpfile.flush()
    self.assertEqual(utils._FingerprintFile(self.tmpfile.name),
                     "35b6795ca20d6dc0aff8c7c110c96cd1070b8c38")

  def testMultiple(self):
    all_files = self.results.keys()
    all_files.append("/no/such/file")
    self.assertEqual(utils.FingerprintFiles(self.results.keys()), self.results)


class TestGenerateSelfSignedX509Cert(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _checkRsaPrivateKey(self, key):
    lines = key.splitlines()
    return ("-----BEGIN RSA PRIVATE KEY-----" in lines and
            "-----END RSA PRIVATE KEY-----" in lines)

  def _checkCertificate(self, cert):
    lines = cert.splitlines()
    return ("-----BEGIN CERTIFICATE-----" in lines and
            "-----END CERTIFICATE-----" in lines)

  def test(self):
    for common_name in [None, ".", "Ganeti", "node1.example.com"]:
      (key_pem, cert_pem) = utils.GenerateSelfSignedX509Cert(common_name, 300)
      self._checkRsaPrivateKey(key_pem)
      self._checkCertificate(cert_pem)

      key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                           key_pem)
      self.assert_(key.bits() >= 1024)
      self.assertEqual(key.bits(), constants.RSA_KEY_BITS)
      self.assertEqual(key.type(), OpenSSL.crypto.TYPE_RSA)

      x509 = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                             cert_pem)
      self.failIf(x509.has_expired())
      self.assertEqual(x509.get_issuer().CN, common_name)
      self.assertEqual(x509.get_subject().CN, common_name)
      self.assertEqual(x509.get_pubkey().bits(), constants.RSA_KEY_BITS)

  def testLegacy(self):
    cert1_filename = os.path.join(self.tmpdir, "cert1.pem")

    utils.GenerateSelfSignedSslCert(cert1_filename, validity=1)

    cert1 = utils.ReadFile(cert1_filename)

    self.assert_(self._checkRsaPrivateKey(cert1))
    self.assert_(self._checkCertificate(cert1))


class TestPathJoin(unittest.TestCase):
  """Testing case for PathJoin"""

  def testBasicItems(self):
    mlist = ["/a", "b", "c"]
    self.failUnlessEqual(PathJoin(*mlist), "/".join(mlist))

  def testNonAbsPrefix(self):
    self.failUnlessRaises(ValueError, PathJoin, "a", "b")

  def testBackTrack(self):
    self.failUnlessRaises(ValueError, PathJoin, "/a", "b/../c")

  def testMultiAbs(self):
    self.failUnlessRaises(ValueError, PathJoin, "/a", "/b")


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


class TestParseAsn1Generalizedtime(unittest.TestCase):
  def test(self):
    # UTC
    self.assertEqual(utils._ParseAsn1Generalizedtime("19700101000000Z"), 0)
    self.assertEqual(utils._ParseAsn1Generalizedtime("20100222174152Z"),
                     1266860512)
    self.assertEqual(utils._ParseAsn1Generalizedtime("20380119031407Z"),
                     (2**31) - 1)

    # With offset
    self.assertEqual(utils._ParseAsn1Generalizedtime("20100222174152+0000"),
                     1266860512)
    self.assertEqual(utils._ParseAsn1Generalizedtime("20100223131652+0000"),
                     1266931012)
    self.assertEqual(utils._ParseAsn1Generalizedtime("20100223051808-0800"),
                     1266931088)
    self.assertEqual(utils._ParseAsn1Generalizedtime("20100224002135+1100"),
                     1266931295)
    self.assertEqual(utils._ParseAsn1Generalizedtime("19700101000000-0100"),
                     3600)

    # Leap seconds are not supported by datetime.datetime
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime,
                      "19841231235960+0000")
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime,
                      "19920630235960+0000")

    # Errors
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime, "")
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime, "invalid")
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime,
                      "20100222174152")
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime,
                      "Mon Feb 22 17:47:02 UTC 2010")
    self.assertRaises(ValueError, utils._ParseAsn1Generalizedtime,
                      "2010-02-22 17:42:02")


class TestGetX509CertValidity(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    pyopenssl_version = distutils.version.LooseVersion(OpenSSL.__version__)

    # Test whether we have pyOpenSSL 0.7 or above
    self.pyopenssl0_7 = (pyopenssl_version >= "0.7")

    if not self.pyopenssl0_7:
      warnings.warn("This test requires pyOpenSSL 0.7 or above to"
                    " function correctly")

  def _LoadCert(self, name):
    return OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           self._ReadTestData(name))

  def test(self):
    validity = utils.GetX509CertValidity(self._LoadCert("cert1.pem"))
    if self.pyopenssl0_7:
      self.assertEqual(validity, (1266919967, 1267524767))
    else:
      self.assertEqual(validity, (None, None))


class TestSignX509Certificate(unittest.TestCase):
  KEY = "My private key!"
  KEY_OTHER = "Another key"

  def test(self):
    # Generate certificate valid for 5 minutes
    (_, cert_pem) = utils.GenerateSelfSignedX509Cert(None, 300)

    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           cert_pem)

    # No signature at all
    self.assertRaises(errors.GenericError,
                      utils.LoadSignedX509Certificate, cert_pem, self.KEY)

    # Invalid input
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Signature: \n", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Sign: $1234$abcdef\n", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Signature: $1234567890$abcdef\n", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Signature: $1234$abc\n\n" + cert_pem, self.KEY)

    # Invalid salt
    for salt in list("-_@$,:;/\\ \t\n"):
      self.assertRaises(errors.GenericError, utils.SignX509Certificate,
                        cert_pem, self.KEY, "foo%sbar" % salt)

    for salt in ["HelloWorld", "salt", string.letters, string.digits,
                 utils.GenerateSecret(numbytes=4),
                 utils.GenerateSecret(numbytes=16),
                 "{123:456}".encode("hex")]:
      signed_pem = utils.SignX509Certificate(cert, self.KEY, salt)

      self._Check(cert, salt, signed_pem)

      self._Check(cert, salt, "X-Another-Header: with a value\n" + signed_pem)
      self._Check(cert, salt, (10 * "Hello World!\n") + signed_pem)
      self._Check(cert, salt, (signed_pem + "\n\na few more\n"
                               "lines----\n------ at\nthe end!"))

  def _Check(self, cert, salt, pem):
    (cert2, salt2) = utils.LoadSignedX509Certificate(pem, self.KEY)
    self.assertEqual(salt, salt2)
    self.assertEqual(cert.digest("sha1"), cert2.digest("sha1"))

    # Other key
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      pem, self.KEY_OTHER)


class TestMakedirs(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExisting(self):
    path = PathJoin(self.tmpdir, "foo")
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))

  def testExisting(self):
    path = PathJoin(self.tmpdir, "foo")
    os.mkdir(path)
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))

  def testRecursiveNonExisting(self):
    path = PathJoin(self.tmpdir, "foo/bar/baz")
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))

  def testRecursiveExisting(self):
    path = PathJoin(self.tmpdir, "B/moo/xyz")
    self.assertFalse(os.path.exists(path))
    os.mkdir(PathJoin(self.tmpdir, "B"))
    utils.Makedirs(path)
    self.assert_(os.path.isdir(path))


class TestReadLockedPidFile(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExistent(self):
    path = PathJoin(self.tmpdir, "nonexist")
    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testUnlocked(self):
    path = PathJoin(self.tmpdir, "pid")
    utils.WriteFile(path, data="123")
    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testLocked(self):
    path = PathJoin(self.tmpdir, "pid")
    utils.WriteFile(path, data="123")

    fl = utils.FileLock.Open(path)
    try:
      fl.Exclusive(blocking=True)

      self.assertEqual(utils.ReadLockedPidFile(path), 123)
    finally:
      fl.Close()

    self.assert_(utils.ReadLockedPidFile(path) is None)

  def testError(self):
    path = PathJoin(self.tmpdir, "foobar", "pid")
    utils.WriteFile(PathJoin(self.tmpdir, "foobar"), data="")
    # open(2) should return ENOTDIR
    self.assertRaises(EnvironmentError, utils.ReadLockedPidFile, path)


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    cert_pem = utils.ReadFile(self._TestDataFilename("cert1.pem"))
    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           cert_pem)

    # Not checking return value as this certificate is expired
    utils.VerifyX509Certificate(cert, 30, 7)


class TestVerifyCertificateInner(unittest.TestCase):
  def test(self):
    vci = utils._VerifyCertificateInner

    # Valid
    self.assertEqual(vci(False, 1263916313, 1298476313, 1266940313, 30, 7),
                     (None, None))

    # Not yet valid
    (errcode, msg) = vci(False, 1266507600, 1267544400, 1266075600, 30, 7)
    self.assertEqual(errcode, utils.CERT_WARNING)

    # Expiring soon
    (errcode, msg) = vci(False, 1266507600, 1267544400, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(False, 1266507600, 1267544400, 1266939600, 30, 1)
    self.assertEqual(errcode, utils.CERT_WARNING)

    (errcode, msg) = vci(False, 1266507600, None, 1266939600, 30, 7)
    self.assertEqual(errcode, None)

    # Expired
    (errcode, msg) = vci(True, 1266507600, 1267544400, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(True, None, 1267544400, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(True, 1266507600, None, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(True, None, None, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)


class TestHmacFunctions(unittest.TestCase):
  # Digests can be checked with "openssl sha1 -hmac $key"
  def testSha1Hmac(self):
    self.assertEqual(utils.Sha1Hmac("", ""),
                     "fbdb1d1b18aa6c08324b7d64b71fb76370690e1d")
    self.assertEqual(utils.Sha1Hmac("3YzMxZWE", "Hello World"),
                     "ef4f3bda82212ecb2f7ce868888a19092481f1fd")
    self.assertEqual(utils.Sha1Hmac("TguMTA2K", ""),
                     "f904c2476527c6d3e6609ab683c66fa0652cb1dc")

    longtext = 1500 * "The quick brown fox jumps over the lazy dog\n"
    self.assertEqual(utils.Sha1Hmac("3YzMxZWE", longtext),
                     "35901b9a3001a7cdcf8e0e9d7c2e79df2223af54")

  def testSha1HmacSalt(self):
    self.assertEqual(utils.Sha1Hmac("TguMTA2K", "", salt="abc0"),
                     "4999bf342470eadb11dfcd24ca5680cf9fd7cdce")
    self.assertEqual(utils.Sha1Hmac("TguMTA2K", "", salt="abc9"),
                     "17a4adc34d69c0d367d4ffbef96fd41d4df7a6e8")
    self.assertEqual(utils.Sha1Hmac("3YzMxZWE", "Hello World", salt="xyz0"),
                     "7f264f8114c9066afc9bb7636e1786d996d3cc0d")

  def testVerifySha1Hmac(self):
    self.assert_(utils.VerifySha1Hmac("", "", ("fbdb1d1b18aa6c08324b"
                                               "7d64b71fb76370690e1d")))
    self.assert_(utils.VerifySha1Hmac("TguMTA2K", "",
                                      ("f904c2476527c6d3e660"
                                       "9ab683c66fa0652cb1dc")))

    digest = "ef4f3bda82212ecb2f7ce868888a19092481f1fd"
    self.assert_(utils.VerifySha1Hmac("3YzMxZWE", "Hello World", digest))
    self.assert_(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      digest.lower()))
    self.assert_(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      digest.upper()))
    self.assert_(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      digest.title()))

  def testVerifySha1HmacSalt(self):
    self.assert_(utils.VerifySha1Hmac("TguMTA2K", "",
                                      ("17a4adc34d69c0d367d4"
                                       "ffbef96fd41d4df7a6e8"),
                                      salt="abc9"))
    self.assert_(utils.VerifySha1Hmac("3YzMxZWE", "Hello World",
                                      ("7f264f8114c9066afc9b"
                                       "b7636e1786d996d3cc0d"),
                                      salt="xyz0"))


class TestIgnoreSignals(unittest.TestCase):
  """Test the IgnoreSignals decorator"""

  @staticmethod
  def _Raise(exception):
    raise exception

  @staticmethod
  def _Return(rval):
    return rval

  def testIgnoreSignals(self):
    sock_err_intr = socket.error(errno.EINTR, "Message")
    sock_err_inval = socket.error(errno.EINVAL, "Message")

    env_err_intr = EnvironmentError(errno.EINTR, "Message")
    env_err_inval = EnvironmentError(errno.EINVAL, "Message")

    self.assertRaises(socket.error, self._Raise, sock_err_intr)
    self.assertRaises(socket.error, self._Raise, sock_err_inval)
    self.assertRaises(EnvironmentError, self._Raise, env_err_intr)
    self.assertRaises(EnvironmentError, self._Raise, env_err_inval)

    self.assertEquals(utils.IgnoreSignals(self._Raise, sock_err_intr), None)
    self.assertEquals(utils.IgnoreSignals(self._Raise, env_err_intr), None)
    self.assertRaises(socket.error, utils.IgnoreSignals, self._Raise,
                      sock_err_inval)
    self.assertRaises(EnvironmentError, utils.IgnoreSignals, self._Raise,
                      env_err_inval)

    self.assertEquals(utils.IgnoreSignals(self._Return, True), True)
    self.assertEquals(utils.IgnoreSignals(self._Return, 33), 33)


class TestEnsureDirs(unittest.TestCase):
  """Tests for EnsureDirs"""

  def setUp(self):
    self.dir = tempfile.mkdtemp()
    self.old_umask = os.umask(0777)

  def testEnsureDirs(self):
    utils.EnsureDirs([
        (PathJoin(self.dir, "foo"), 0777),
        (PathJoin(self.dir, "bar"), 0000),
        ])
    self.assertEquals(os.stat(PathJoin(self.dir, "foo"))[0] & 0777, 0777)
    self.assertEquals(os.stat(PathJoin(self.dir, "bar"))[0] & 0777, 0000)

  def tearDown(self):
    os.rmdir(PathJoin(self.dir, "foo"))
    os.rmdir(PathJoin(self.dir, "bar"))
    os.rmdir(self.dir)
    os.umask(self.old_umask)


class TestIgnoreProcessNotFound(unittest.TestCase):
  @staticmethod
  def _WritePid(fd):
    os.write(fd, str(os.getpid()))
    os.close(fd)
    return True

  def test(self):
    (pid_read_fd, pid_write_fd) = os.pipe()

    # Start short-lived process which writes its PID to pipe
    self.assert_(utils.RunInSeparateProcess(self._WritePid, pid_write_fd))
    os.close(pid_write_fd)

    # Read PID from pipe
    pid = int(os.read(pid_read_fd, 1024))
    os.close(pid_read_fd)

    # Try to send signal to process which exited recently
    self.assertFalse(utils.IgnoreProcessNotFound(os.kill, pid, 0))


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


class TestFileID(testutils.GanetiTestCase):
  def testEquality(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    self.failUnless(utils.VerifyFileID(oldi, oldi))

  def testUpdate(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    os.utime(name, None)
    fd = os.open(name, os.O_RDWR)
    try:
      newi = utils.GetFileID(fd=fd)
      self.failUnless(utils.VerifyFileID(oldi, newi))
      self.failUnless(utils.VerifyFileID(newi, oldi))
    finally:
      os.close(fd)

  def testWriteFile(self):
    name = self._CreateTempFile()
    oldi = utils.GetFileID(path=name)
    mtime = oldi[2]
    os.utime(name, (mtime + 10, mtime + 10))
    self.assertRaises(errors.LockError, utils.SafeWriteFile, name,
                      oldi, data="")
    os.utime(name, (mtime - 10, mtime - 10))
    utils.SafeWriteFile(name, oldi, data="")
    oldi = utils.GetFileID(path=name)
    mtime = oldi[2]
    os.utime(name, (mtime + 10, mtime + 10))
    # this doesn't raise, since we passed None
    utils.SafeWriteFile(name, None, data="")

  def testError(self):
    t = tempfile.NamedTemporaryFile()
    self.assertRaises(errors.ProgrammerError, utils.GetFileID,
                      path=t.name, fd=t.fileno())


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


class TestWriteFile(unittest.TestCase):
  def setUp(self):
    self.tfile = tempfile.NamedTemporaryFile()
    self.did_pre = False
    self.did_post = False
    self.did_write = False

  def markPre(self, fd):
    self.did_pre = True

  def markPost(self, fd):
    self.did_post = True

  def markWrite(self, fd):
    self.did_write = True

  def testWrite(self):
    data = "abc"
    utils.WriteFile(self.tfile.name, data=data)
    self.assertEqual(utils.ReadFile(self.tfile.name), data)

  def testErrors(self):
    self.assertRaises(errors.ProgrammerError, utils.WriteFile,
                      self.tfile.name, data="test", fn=lambda fd: None)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile, self.tfile.name)
    self.assertRaises(errors.ProgrammerError, utils.WriteFile,
                      self.tfile.name, data="test", atime=0)

  def testCalls(self):
    utils.WriteFile(self.tfile.name, fn=self.markWrite,
                    prewrite=self.markPre, postwrite=self.markPost)
    self.assertTrue(self.did_pre)
    self.assertTrue(self.did_post)
    self.assertTrue(self.did_write)

  def testDryRun(self):
    orig = "abc"
    self.tfile.write(orig)
    self.tfile.flush()
    utils.WriteFile(self.tfile.name, data="hello", dry_run=True)
    self.assertEqual(utils.ReadFile(self.tfile.name), orig)

  def testTimes(self):
    f = self.tfile.name
    for at, mt in [(0, 0), (1000, 1000), (2000, 3000),
                   (int(time.time()), 5000)]:
      utils.WriteFile(f, data="hello", atime=at, mtime=mt)
      st = os.stat(f)
      self.assertEqual(st.st_atime, at)
      self.assertEqual(st.st_mtime, mt)


  def testNoClose(self):
    data = "hello"
    self.assertEqual(utils.WriteFile(self.tfile.name, data="abc"), None)
    fd = utils.WriteFile(self.tfile.name, data=data, close=False)
    try:
      os.lseek(fd, 0, 0)
      self.assertEqual(os.read(fd, 4096), data)
    finally:
      os.close(fd)


if __name__ == '__main__':
  testutils.GanetiTestProgram()
