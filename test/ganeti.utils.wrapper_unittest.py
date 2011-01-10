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


"""Script for testing ganeti.utils.wrapper"""

import errno
import fcntl
import os
import socket
import tempfile
import unittest

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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
