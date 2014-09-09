#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Script for testing ganeti.utils.wrapper"""

import errno
import fcntl
import os
import socket
import tempfile
import unittest
import shutil

from ganeti import constants
from ganeti import utils

import testutils


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


class TestIsExecutable(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testNonExisting(self):
    fname = utils.PathJoin(self.tmpdir, "file")
    assert not os.path.exists(fname)
    self.assertFalse(utils.IsExecutable(fname))

  def testNoFile(self):
    path = utils.PathJoin(self.tmpdir, "something")
    os.mkdir(path)
    assert os.path.isdir(path)
    self.assertFalse(utils.IsExecutable(path))

  def testExecutable(self):
    fname = utils.PathJoin(self.tmpdir, "file")
    utils.WriteFile(fname, data="#!/bin/bash", mode=0700)
    assert os.path.exists(fname)
    self.assertTrue(utils.IsExecutable(fname))

    self.assertTrue(self._TestSymlink(fname))

  def testFileNotExecutable(self):
    fname = utils.PathJoin(self.tmpdir, "file")
    utils.WriteFile(fname, data="#!/bin/bash", mode=0600)
    assert os.path.exists(fname)
    self.assertFalse(utils.IsExecutable(fname))

    self.assertFalse(self._TestSymlink(fname))

  def _TestSymlink(self, fname):
    assert os.path.exists(fname)

    linkname = utils.PathJoin(self.tmpdir, "cmd")
    os.symlink(fname, linkname)

    assert os.path.islink(linkname)

    return utils.IsExecutable(linkname)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
