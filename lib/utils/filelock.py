#
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

"""Utility functions for file-based locks.

"""

import fcntl
import errno
import os
import logging

from ganeti import errors
from ganeti.utils import retry


def LockFile(fd):
  """Locks a file using POSIX locks.

  @type fd: int
  @param fd: the file descriptor we need to lock

  """
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except IOError, err:
    if err.errno == errno.EAGAIN:
      raise errors.LockError("File already locked")
    raise


class FileLock(object):
  """Utility class for file locks.

  """
  def __init__(self, fd, filename):
    """Constructor for FileLock.

    @type fd: file
    @param fd: File object
    @type filename: str
    @param filename: Path of the file opened at I{fd}

    """
    self.fd = fd
    self.filename = filename

  @classmethod
  def Open(cls, filename):
    """Creates and opens a file to be used as a file-based lock.

    @type filename: string
    @param filename: path to the file to be locked

    """
    # Using "os.open" is necessary to allow both opening existing file
    # read/write and creating if not existing. Vanilla "open" will truncate an
    # existing file -or- allow creating if not existing.
    return cls(os.fdopen(os.open(filename, os.O_RDWR | os.O_CREAT, 0664), "w+"),
               filename)

  def __del__(self):
    self.Close()

  def Close(self):
    """Close the file and release the lock.

    """
    if hasattr(self, "fd") and self.fd:
      self.fd.close()
      self.fd = None

  def _flock(self, flag, blocking, timeout, errmsg):
    """Wrapper for fcntl.flock.

    @type flag: int
    @param flag: operation flag
    @type blocking: bool
    @param blocking: whether the operation should be done in blocking mode.
    @type timeout: None or float
    @param timeout: for how long the operation should be retried (implies
                    non-blocking mode).
    @type errmsg: string
    @param errmsg: error message in case operation fails.

    """
    assert self.fd, "Lock was closed"
    assert timeout is None or timeout >= 0, \
      "If specified, timeout must be positive"
    assert not (flag & fcntl.LOCK_NB), "LOCK_NB must not be set"

    # When a timeout is used, LOCK_NB must always be set
    if not (timeout is None and blocking):
      flag |= fcntl.LOCK_NB

    if timeout is None:
      self._Lock(self.fd, flag, timeout)
    else:
      try:
        retry.Retry(self._Lock, (0.1, 1.2, 1.0), timeout,
                    args=(self.fd, flag, timeout))
      except retry.RetryTimeout:
        raise errors.LockError(errmsg)

  @staticmethod
  def _Lock(fd, flag, timeout):
    try:
      fcntl.flock(fd, flag)
    except IOError, err:
      if timeout is not None and err.errno == errno.EAGAIN:
        raise retry.RetryAgain()

      logging.exception("fcntl.flock failed")
      raise

  def Exclusive(self, blocking=False, timeout=None):
    """Locks the file in exclusive mode.

    @type blocking: boolean
    @param blocking: whether to block and wait until we
        can lock the file or return immediately
    @type timeout: int or None
    @param timeout: if not None, the duration to wait for the lock
        (in blocking mode)

    """
    self._flock(fcntl.LOCK_EX, blocking, timeout,
                "Failed to lock %s in exclusive mode" % self.filename)

  def Shared(self, blocking=False, timeout=None):
    """Locks the file in shared mode.

    @type blocking: boolean
    @param blocking: whether to block and wait until we
        can lock the file or return immediately
    @type timeout: int or None
    @param timeout: if not None, the duration to wait for the lock
        (in blocking mode)

    """
    self._flock(fcntl.LOCK_SH, blocking, timeout,
                "Failed to lock %s in shared mode" % self.filename)

  def Unlock(self, blocking=True, timeout=None):
    """Unlocks the file.

    According to C{flock(2)}, unlocking can also be a nonblocking
    operation::

      To make a non-blocking request, include LOCK_NB with any of the above
      operations.

    @type blocking: boolean
    @param blocking: whether to block and wait until we
        can lock the file or return immediately
    @type timeout: int or None
    @param timeout: if not None, the duration to wait for the lock
        (in blocking mode)

    """
    self._flock(fcntl.LOCK_UN, blocking, timeout,
                "Failed to unlock %s" % self.filename)
