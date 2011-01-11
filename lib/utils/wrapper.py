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

"""Utility functions wrapping other functions.

"""

import time
import socket
import errno
import tempfile
import fcntl
import os
import select
import logging


def TestDelay(duration):
  """Sleep for a fixed amount of time.

  @type duration: float
  @param duration: the sleep duration
  @rtype: boolean
  @return: False for negative value, True otherwise

  """
  if duration < 0:
    return False, "Invalid sleep duration"
  time.sleep(duration)
  return True, None


def CloseFdNoError(fd, retries=5):
  """Close a file descriptor ignoring errors.

  @type fd: int
  @param fd: the file descriptor
  @type retries: int
  @param retries: how many retries to make, in case we get any
      other error than EBADF

  """
  try:
    os.close(fd)
  except OSError, err:
    if err.errno != errno.EBADF:
      if retries > 0:
        CloseFdNoError(fd, retries - 1)
    # else either it's closed already or we're out of retries, so we
    # ignore this and go on


def SetCloseOnExecFlag(fd, enable):
  """Sets or unsets the close-on-exec flag on a file descriptor.

  @type fd: int
  @param fd: File descriptor
  @type enable: bool
  @param enable: Whether to set or unset it.

  """
  flags = fcntl.fcntl(fd, fcntl.F_GETFD)

  if enable:
    flags |= fcntl.FD_CLOEXEC
  else:
    flags &= ~fcntl.FD_CLOEXEC

  fcntl.fcntl(fd, fcntl.F_SETFD, flags)


def SetNonblockFlag(fd, enable):
  """Sets or unsets the O_NONBLOCK flag on on a file descriptor.

  @type fd: int
  @param fd: File descriptor
  @type enable: bool
  @param enable: Whether to set or unset it

  """
  flags = fcntl.fcntl(fd, fcntl.F_GETFL)

  if enable:
    flags |= os.O_NONBLOCK
  else:
    flags &= ~os.O_NONBLOCK

  fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def RetryOnSignal(fn, *args, **kwargs):
  """Calls a function again if it failed due to EINTR.

  """
  while True:
    try:
      return fn(*args, **kwargs)
    except EnvironmentError, err:
      if err.errno != errno.EINTR:
        raise
    except (socket.error, select.error), err:
      # In python 2.6 and above select.error is an IOError, so it's handled
      # above, in 2.5 and below it's not, and it's handled here.
      if not (err.args and err.args[0] == errno.EINTR):
        raise


def IgnoreProcessNotFound(fn, *args, **kwargs):
  """Ignores ESRCH when calling a process-related function.

  ESRCH is raised when a process is not found.

  @rtype: bool
  @return: Whether process was found

  """
  try:
    fn(*args, **kwargs)
  except EnvironmentError, err:
    # Ignore ESRCH
    if err.errno == errno.ESRCH:
      return False
    raise

  return True


def IgnoreSignals(fn, *args, **kwargs):
  """Tries to call a function ignoring failures due to EINTR.

  """
  try:
    return fn(*args, **kwargs)
  except EnvironmentError, err:
    if err.errno == errno.EINTR:
      return None
    else:
      raise
  except (select.error, socket.error), err:
    # In python 2.6 and above select.error is an IOError, so it's handled
    # above, in 2.5 and below it's not, and it's handled here.
    if err.args and err.args[0] == errno.EINTR:
      return None
    else:
      raise


def GetClosedTempfile(*args, **kwargs):
  """Creates a temporary file and returns its path.

  """
  (fd, path) = tempfile.mkstemp(*args, **kwargs)
  CloseFdNoError(fd)
  return path


def ResetTempfileModule():
  """Resets the random name generator of the tempfile module.

  This function should be called after C{os.fork} in the child process to
  ensure it creates a newly seeded random generator. Otherwise it would
  generate the same random parts as the parent process. If several processes
  race for the creation of a temporary file, this could lead to one not getting
  a temporary name.

  """
  # pylint: disable-msg=W0212
  if hasattr(tempfile, "_once_lock") and hasattr(tempfile, "_name_sequence"):
    tempfile._once_lock.acquire()
    try:
      # Reset random name generator
      tempfile._name_sequence = None
    finally:
      tempfile._once_lock.release()
  else:
    logging.critical("The tempfile module misses at least one of the"
                     " '_once_lock' and '_name_sequence' attributes")
