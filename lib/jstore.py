#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""Module implementing the job queue handling."""

import errno
import os

from ganeti import constants
from ganeti import errors
from ganeti import runtime
from ganeti import utils
from ganeti import pathutils


JOBS_PER_ARCHIVE_DIRECTORY = constants.JSTORE_JOBS_PER_ARCHIVE_DIRECTORY


def _ReadNumericFile(file_name):
  """Reads a file containing a number.

  @rtype: None or int
  @return: None if file is not found, otherwise number

  """
  try:
    contents = utils.ReadFile(file_name)
  except EnvironmentError as err:
    if err.errno in (errno.ENOENT, ):
      return None
    raise

  try:
    return int(contents)
  except (ValueError, TypeError) as err:
    # Couldn't convert to int
    raise errors.JobQueueError("Content of file '%s' is not numeric: %s" %
                               (file_name, err))


def ReadSerial():
  """Read the serial file.

  The queue should be locked while this function is called.

  """
  return _ReadNumericFile(pathutils.JOB_QUEUE_SERIAL_FILE)


def ReadVersion():
  """Read the queue version.

  The queue should be locked while this function is called.

  """
  return _ReadNumericFile(pathutils.JOB_QUEUE_VERSION_FILE)


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
  queue_lock = utils.FileLock.Open(pathutils.JOB_QUEUE_LOCK_FILE)
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
        utils.WriteFile(pathutils.JOB_QUEUE_VERSION_FILE,
                        uid=getents.masterd_uid, gid=getents.daemons_gid,
                        mode=constants.JOB_QUEUE_FILES_PERMS,
                        data="%s\n" % constants.JOB_QUEUE_VERSION)

        # Read again
        version = ReadVersion()

      if version != constants.JOB_QUEUE_VERSION:
        raise errors.JobQueueError("Found job queue version %s, expected %s",
                                   version, constants.JOB_QUEUE_VERSION)

      serial = ReadSerial()
      if serial is None:
        # Write new serial file
        utils.WriteFile(pathutils.JOB_QUEUE_SERIAL_FILE,
                        uid=getents.masterd_uid, gid=getents.daemons_gid,
                        mode=constants.JOB_QUEUE_FILES_PERMS,
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


def CheckDrainFlag():
  """Check if the queue is marked to be drained.

  This currently uses the queue drain file, which makes it a per-node flag.
  In the future this can be moved to the config file.

  @rtype: boolean
  @return: True if the job queue is marked drained

  """
  return os.path.exists(pathutils.JOB_QUEUE_DRAIN_FILE)


def SetDrainFlag(drain_flag):
  """Sets the drain flag for the queue.

  @type drain_flag: boolean
  @param drain_flag: Whether to set or unset the drain flag
  @attention: This function should only called the current holder of the queue
    lock

  """
  getents = runtime.GetEnts()

  if drain_flag:
    utils.WriteFile(pathutils.JOB_QUEUE_DRAIN_FILE, data="",
                    uid=getents.masterd_uid, gid=getents.daemons_gid,
                    mode=constants.JOB_QUEUE_FILES_PERMS)
  else:
    utils.RemoveFile(pathutils.JOB_QUEUE_DRAIN_FILE)

  assert (not drain_flag) ^ CheckDrainFlag()


def FormatJobID(job_id):
  """Convert a job ID to int format.

  Currently this just is a no-op that performs some checks, but if we
  want to change the job id format this will abstract this change.

  @type job_id: int or long
  @param job_id: the numeric job id
  @rtype: int
  @return: the formatted job id

  """
  if not isinstance(job_id, int):
    raise errors.ProgrammerError("Job ID '%s' not numeric" % job_id)
  if job_id < 0:
    raise errors.ProgrammerError("Job ID %s is negative" % job_id)

  return job_id


def GetArchiveDirectory(job_id):
  """Returns the archive directory for a job.

  @type job_id: str
  @param job_id: Job identifier
  @rtype: str
  @return: Directory name

  """
  return str(ParseJobId(job_id) // JOBS_PER_ARCHIVE_DIRECTORY)


def ParseJobId(job_id):
  """Parses a job ID and converts it to integer.

  """
  try:
    return int(job_id)
  except (ValueError, TypeError):
    raise errors.ParameterError("Invalid job ID '%s'" % job_id)
