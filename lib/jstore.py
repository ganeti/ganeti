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

import errno

from ganeti import constants
from ganeti import errors
from ganeti import runtime
from ganeti import utils


def _ReadNumericFile(file_name):
  """Reads a file containing a number.

  @rtype: None or int
  @return: None if file is not found, otherwise number

  """
  try:
    return int(utils.ReadFile(file_name))
  except EnvironmentError, err:
    if err.errno in (errno.ENOENT, ):
      return None
    raise


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


def InitAndVerifyQueue(must_lock):
  """Open and lock job queue.

  If necessary, the queue is automatically initialized.

  @type must_lock: bool
  @param must_lock: Whether an exclusive lock must be held.
  @rtype: utils.FileLock
  @return: Lock object for the queue. This can be used to change the
           locking mode.

  """
  getents = runtime.GetEnts()

  # Lock queue
  queue_lock = utils.FileLock.Open(constants.JOB_QUEUE_LOCK_FILE)
  try:
    # The queue needs to be locked in exclusive mode to write to the serial and
    # version files.
    if must_lock:
      queue_lock.Exclusive(blocking=True)
      holding_lock = True
    else:
      try:
        queue_lock.Exclusive(blocking=False)
        holding_lock = True
      except errors.LockError:
        # Ignore errors and assume the process keeping the lock checked
        # everything.
        holding_lock = False

    if holding_lock:
      # Verify version
      version = ReadVersion()
      if version is None:
        # Write new version file
        utils.WriteFile(constants.JOB_QUEUE_VERSION_FILE,
                        uid=getents.masterd_uid, gid=getents.masterd_gid,
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
                        uid=getents.masterd_uid, gid=getents.masterd_gid,
                        data="%s\n" % 0)

        # Read again
        serial = ReadSerial()

      if serial is None:
        # There must be a serious problem
        raise errors.JobQueueError("Can't read/parse the job queue"
                                   " serial file")

      if not must_lock:
        # There's no need for more error handling. Closing the lock
        # file below in case of an error will unlock it anyway.
        queue_lock.Unlock()

  except:
    queue_lock.Close()
    raise

  return queue_lock
