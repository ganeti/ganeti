#
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Module implementing the job queue handling."""

import os
import logging
import errno
import re

from ganeti import constants
from ganeti import errors
from ganeti import utils


def _ReadNumericFile(file_name):
  """Reads a file containing a number.

  @rtype: None or int
  @return: None if file is not found, otherwise number

  """
  try:
    fd = open(file_name, "r")
  except IOError, err:
    if err.errno in (errno.ENOENT, ):
      return None
    raise

  try:
    return int(fd.read(128))
  finally:
    fd.close()


def ReadSerial():
  """Read the serial file.

  The queue should be locked while this function is called.

  """
  return _ReadNumericFile(constants.JOB_QUEUE_SERIAL_FILE)


def ReadVersion():
  """Read the queue version.

  The queue should be locked while this function is called.

  """
  return _ReadNumericFile(constants.JOB_QUEUE_VERSION_FILE)


def InitAndVerifyQueue(exclusive):
  """Open and lock job queue.

  If necessary, the queue is automatically initialized.

  @type exclusive: bool
  @param exclusive: Whether to lock the queue in exclusive mode. Shared
                    mode otherwise.
  @rtype: utils.FileLock
  @return: Lock object for the queue. This can be used to change the
           locking mode.

  """
  # Make sure our directories exists
  for path in (constants.QUEUE_DIR, constants.JOB_QUEUE_ARCHIVE_DIR):
    try:
      os.mkdir(path, 0700)
    except OSError, err:
      if err.errno not in (errno.EEXIST, ):
        raise

  # Lock queue
  queue_lock = utils.FileLock(constants.JOB_QUEUE_LOCK_FILE)
  try:
    # Determine locking function and call it
    if exclusive:
      fn = queue_lock.Exclusive
    else:
      fn = queue_lock.Shared

    fn(blocking=False)

    # Verify version
    version = ReadVersion()
    if version is None:
      # Write new version file
      utils.WriteFile(constants.JOB_QUEUE_VERSION_FILE,
                      data="%s\n" % constants.JOB_QUEUE_VERSION)

      # Read again
      version = ReadVersion()

    if version != constants.JOB_QUEUE_VERSION:
      raise errors.JobQueueError("Found job queue version %s, expected %s",
                                 version, constants.JOB_QUEUE_VERSION)

    serial = ReadSerial()
    if serial is None:
      # Write new serial file
      utils.WriteFile(constants.JOB_QUEUE_SERIAL_FILE,
                      data="%s\n" % 0)

      # Read again
      serial = ReadSerial()

    if serial is None:
      # There must be a serious problem
      raise errors.JobQueueError("Can't read/parse the job queue serial file")

  except:
    queue_lock.Close()
    raise

  return queue_lock
