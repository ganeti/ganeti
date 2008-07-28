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
import threading
import errno
import re
import time

from ganeti import constants
from ganeti import serializer
from ganeti import workerpool
from ganeti import opcodes
from ganeti import errors
from ganeti import mcpu
from ganeti import utils
from ganeti import rpc


JOBQUEUE_THREADS = 5


class _QueuedOpCode(object):
  """Encasulates an opcode object.

  Access is synchronized by the '_lock' attribute.

  The 'log' attribute holds the execution log and consists of tuples
  of the form (timestamp, level, message).

  """
  def __init__(self, op):
    self.__Setup(op, constants.OP_STATUS_QUEUED, None, [])

  def __Setup(self, input_, status, result, log):
    self._lock = threading.Lock()
    self.input = input_
    self.status = status
    self.result = result
    self.log = log

  @classmethod
  def Restore(cls, state):
    obj = object.__new__(cls)
    obj.__Setup(opcodes.OpCode.LoadOpCode(state["input"]),
                state["status"], state["result"], state["log"])
    return obj

  @utils.LockedMethod
  def Serialize(self):
    return {
      "input": self.input.__getstate__(),
      "status": self.status,
      "result": self.result,
      "log": self.log,
      }

  @utils.LockedMethod
  def GetInput(self):
    """Returns the original opcode.

    """
    return self.input

  @utils.LockedMethod
  def SetStatus(self, status, result):
    """Update the opcode status and result.

    """
    self.status = status
    self.result = result

  @utils.LockedMethod
  def GetStatus(self):
    """Get the opcode status.

    """
    return self.status

  @utils.LockedMethod
  def GetResult(self):
    """Get the opcode result.

    """
    return self.result

  @utils.LockedMethod
  def Log(self, *args):
    """Append a log entry.

    """
    assert len(args) < 2

    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      log_type, log_msg = args
    self.log.append((time.time(), log_type, log_msg))

  @utils.LockedMethod
  def RetrieveLog(self, start_at=0):
    """Retrieve (a part of) the execution log.

    """
    return self.log[start_at:]


class _QueuedJob(object):
  """In-memory job representation.

  This is what we use to track the user-submitted jobs.

  """
  def __init__(self, storage, job_id, ops):
    if not ops:
      # TODO
      raise Exception("No opcodes")

    self.__Setup(storage, job_id, [_QueuedOpCode(op) for op in ops], -1)

  def __Setup(self, storage, job_id, ops, run_op_index):
    self._lock = threading.Lock()
    self.storage = storage
    self.id = job_id
    self._ops = ops
    self.run_op_index = run_op_index

  @classmethod
  def Restore(cls, storage, state):
    obj = object.__new__(cls)
    op_list = [_QueuedOpCode.Restore(op_state) for op_state in state["ops"]]
    obj.__Setup(storage, state["id"], op_list, state["run_op_index"])
    return obj

  def Serialize(self):
    return {
      "id": self.id,
      "ops": [op.Serialize() for op in self._ops],
      "run_op_index": self.run_op_index,
      }

  def _SetStatus(self, status, msg):
    try:
      for op in self._ops:
        op.SetStatus(status, msg)
    finally:
      self.storage.UpdateJob(self)

  def SetUnclean(self, msg):
    return self._SetStatus(constants.OP_STATUS_ERROR, msg)

  def SetCanceled(self, msg):
    return self._SetStatus(constants.JOB_STATUS_CANCELED, msg)

  def GetStatus(self):
    status = constants.JOB_STATUS_QUEUED

    all_success = True
    for op in self._ops:
      op_status = op.GetStatus()
      if op_status == constants.OP_STATUS_SUCCESS:
        continue

      all_success = False

      if op_status == constants.OP_STATUS_QUEUED:
        pass
      elif op_status == constants.OP_STATUS_RUNNING:
        status = constants.JOB_STATUS_RUNNING
      elif op_status == constants.OP_STATUS_ERROR:
        status = constants.JOB_STATUS_ERROR
        # The whole job fails if one opcode failed
        break
      elif op_status == constants.OP_STATUS_CANCELED:
        status = constants.OP_STATUS_CANCELED
        break

    if all_success:
      status = constants.JOB_STATUS_SUCCESS

    return status

  @utils.LockedMethod
  def GetRunOpIndex(self):
    return self.run_op_index

  def Run(self, proc):
    """Job executor.

    This functions processes a this job in the context of given processor
    instance.

    Args:
    - proc: Ganeti Processor to run the job with

    """
    try:
      count = len(self._ops)
      for idx, op in enumerate(self._ops):
        try:
          logging.debug("Op %s/%s: Starting %s", idx + 1, count, op)

          self._lock.acquire()
          try:
            self.run_op_index = idx
          finally:
            self._lock.release()

          op.SetStatus(constants.OP_STATUS_RUNNING, None)
          self.storage.UpdateJob(self)

          result = proc.ExecOpCode(op.input, op.Log)

          op.SetStatus(constants.OP_STATUS_SUCCESS, result)
          self.storage.UpdateJob(self)
          logging.debug("Op %s/%s: Successfully finished %s",
                        idx + 1, count, op)
        except Exception, err:
          try:
            op.SetStatus(constants.OP_STATUS_ERROR, str(err))
            logging.debug("Op %s/%s: Error in %s", idx + 1, count, op)
          finally:
            self.storage.UpdateJob(self)
          raise

    except errors.GenericError, err:
      logging.error("ganeti exception %s", exc_info=err)
    except Exception, err:
      logging.error("unhandled exception %s", exc_info=err)
    except:
      logging.error("unhandled unknown exception %s", exc_info=err)


class _JobQueueWorker(workerpool.BaseWorker):
  def RunTask(self, job):
    logging.debug("Worker %s processing job %s",
                  self.worker_id, job.id)
    # TODO: feedback function
    proc = mcpu.Processor(self.pool.context)
    try:
      job.Run(proc)
    finally:
      logging.debug("Worker %s finished job %s, status = %s",
                    self.worker_id, job.id, job.GetStatus())


class _JobQueueWorkerPool(workerpool.WorkerPool):
  def __init__(self, context):
    super(_JobQueueWorkerPool, self).__init__(JOBQUEUE_THREADS,
                                              _JobQueueWorker)
    self.context = context


class JobStorageBase(object):
  def __init__(self, id_prefix):
    self.id_prefix = id_prefix

    if id_prefix:
      prefix_pattern = re.escape("%s-" % id_prefix)
    else:
      prefix_pattern = ""

    # Apart from the prefix, all job IDs are numeric
    self._re_job_id = re.compile(r"^%s\d+$" % prefix_pattern)

  def OwnsJobId(self, job_id):
    return self._re_job_id.match(job_id)

  def FormatJobID(self, job_id):
    if not isinstance(job_id, (int, long)):
      raise errors.ProgrammerError("Job ID '%s' not numeric" % job_id)
    if job_id < 0:
      raise errors.ProgrammerError("Job ID %s is negative" % job_id)

    if self.id_prefix:
      prefix = "%s-" % self.id_prefix
    else:
      prefix = ""

    return "%s%010d" % (prefix, job_id)

  def _ShouldJobBeArchivedUnlocked(self, job):
    if job.GetStatus() not in (constants.JOB_STATUS_CANCELED,
                               constants.JOB_STATUS_SUCCESS,
                               constants.JOB_STATUS_ERROR):
      logging.debug("Job %s is not yet done", job.id)
      return False
    return True


class DiskJobStorage(JobStorageBase):
  _RE_JOB_FILE = re.compile(r"^job-(%s)$" % constants.JOB_ID_TEMPLATE)

  def __init__(self, id_prefix):
    JobStorageBase.__init__(self, id_prefix)

    self._lock = threading.Lock()
    self._memcache = {}
    self._my_hostname = utils.HostInfo().name

    # Make sure our directories exists
    for path in (constants.QUEUE_DIR, constants.JOB_QUEUE_ARCHIVE_DIR):
      try:
        os.mkdir(path, 0700)
      except OSError, err:
        if err.errno not in (errno.EEXIST, ):
          raise

    # Get queue lock
    self.lock_fd = open(constants.JOB_QUEUE_LOCK_FILE, "w")
    try:
      utils.LockFile(self.lock_fd)
    except:
      self.lock_fd.close()
      raise

    # Read version
    try:
      version_fd = open(constants.JOB_QUEUE_VERSION_FILE, "r")
    except IOError, err:
      if err.errno not in (errno.ENOENT, ):
        raise

      # Setup a new queue
      self._InitQueueUnlocked()

      # Try to open again
      version_fd = open(constants.JOB_QUEUE_VERSION_FILE, "r")

    try:
      # Try to read version
      version = int(version_fd.read(128))

      # Verify version
      if version != constants.JOB_QUEUE_VERSION:
        raise errors.JobQueueError("Found version %s, expected %s",
                                   version, constants.JOB_QUEUE_VERSION)
    finally:
      version_fd.close()

    self._last_serial = self._ReadSerial()
    if self._last_serial is None:
      raise errors.ConfigurationError("Can't read/parse the job queue serial"
                                      " file")

  @staticmethod
  def _ReadSerial():
    """Try to read the job serial file.

    @rtype: None or int
    @return: If the serial can be read, then it is returned. Otherwise None
             is returned.

    """
    try:
      serial_fd = open(constants.JOB_QUEUE_SERIAL_FILE, "r")
      try:
        # Read last serial
        serial = int(serial_fd.read(1024).strip())
      finally:
        serial_fd.close()
    except (ValueError, EnvironmentError):
      serial = None

    return serial

  def Close(self):
    assert self.lock_fd, "Queue should be open"

    self.lock_fd.close()
    self.lock_fd = None

  def _InitQueueUnlocked(self):
    assert self.lock_fd, "Queue should be open"

    utils.WriteFile(constants.JOB_QUEUE_VERSION_FILE,
                    data="%s\n" % constants.JOB_QUEUE_VERSION)
    if self._ReadSerial() is None:
      utils.WriteFile(constants.JOB_QUEUE_SERIAL_FILE,
                      data="%s\n" % 0)

  def _NewSerialUnlocked(self, nodes):
    """Generates a new job identifier.

    Job identifiers are unique during the lifetime of a cluster.

    Returns: A string representing the job identifier.

    """
    assert self.lock_fd, "Queue should be open"

    # New number
    serial = self._last_serial + 1

    # Write to file
    utils.WriteFile(constants.JOB_QUEUE_SERIAL_FILE,
                    data="%s\n" % serial)

    # Keep it only if we were able to write the file
    self._last_serial = serial

    # Distribute the serial to the other nodes
    try:
      nodes.remove(self._my_hostname)
    except ValueError:
      pass

    result = rpc.call_upload_file(nodes, constants.JOB_QUEUE_SERIAL_FILE)
    for node in nodes:
      if not result[node]:
        logging.error("copy of job queue file to node %s failed", node)

    return self.FormatJobID(serial)

  def _GetJobPath(self, job_id):
    return os.path.join(constants.QUEUE_DIR, "job-%s" % job_id)

  def _GetArchivedJobPath(self, job_id):
    return os.path.join(constants.JOB_QUEUE_ARCHIVE_DIR, "job-%s" % job_id)

  def _ExtractJobID(self, name):
    m = self._RE_JOB_FILE.match(name)
    if m:
      return m.group(1)
    else:
      return None

  def _GetJobIDsUnlocked(self, archived=False):
    """Return all known job IDs.

    If the parameter archived is True, archived jobs IDs will be
    included. Currently this argument is unused.

    The method only looks at disk because it's a requirement that all
    jobs are present on disk (so in the _memcache we don't have any
    extra IDs).

    """
    jlist = [self._ExtractJobID(name) for name in self._ListJobFiles()]
    jlist.sort()
    return jlist

  def _ListJobFiles(self):
    assert self.lock_fd, "Queue should be open"

    return [name for name in utils.ListVisibleFiles(constants.QUEUE_DIR)
            if self._RE_JOB_FILE.match(name)]

  def _LoadJobUnlocked(self, job_id):
    assert self.lock_fd, "Queue should be open"

    if job_id in self._memcache:
      logging.debug("Found job %s in memcache", job_id)
      return self._memcache[job_id]

    filepath = self._GetJobPath(job_id)
    logging.debug("Loading job from %s", filepath)
    try:
      fd = open(filepath, "r")
    except IOError, err:
      if err.errno in (errno.ENOENT, ):
        return None
      raise
    try:
      data = serializer.LoadJson(fd.read())
    finally:
      fd.close()

    job = _QueuedJob.Restore(self, data)
    self._memcache[job_id] = job
    logging.debug("Added job %s to the cache", job_id)
    return job

  def _GetJobsUnlocked(self, job_ids):
    if not job_ids:
      job_ids = self._GetJobIDsUnlocked()

    return [self._LoadJobUnlocked(job_id) for job_id in job_ids]

  @utils.LockedMethod
  def GetJobs(self, job_ids):
    return self._GetJobsUnlocked(job_ids)

  @utils.LockedMethod
  def AddJob(self, ops, nodes):
    """Create and store on disk a new job.

    @type ops: list
    @param ops: The list of OpCodes that will become the new job.
    @type nodes: list
    @param nodes: The list of nodes to which the new job serial will be
                  distributed.

    """
    assert self.lock_fd, "Queue should be open"

    # Get job identifier
    job_id = self._NewSerialUnlocked(nodes)
    job = _QueuedJob(self, job_id, ops)

    # Write to disk
    self._UpdateJobUnlocked(job)

    logging.debug("Added new job %s to the cache", job_id)
    self._memcache[job_id] = job

    return job

  def _UpdateJobUnlocked(self, job):
    assert self.lock_fd, "Queue should be open"

    filename = self._GetJobPath(job.id)
    logging.debug("Writing job %s to %s", job.id, filename)
    utils.WriteFile(filename,
                    data=serializer.DumpJson(job.Serialize(), indent=False))
    self._CleanCacheUnlocked([job.id])

  def _CleanCacheUnlocked(self, exclude):
    """Clean the memory cache.

    The exceptions argument contains job IDs that should not be
    cleaned.

    """
    assert isinstance(exclude, list)
    for job in self._memcache.values():
      if job.id in exclude:
        continue
      if job.GetStatus() not in (constants.JOB_STATUS_QUEUED,
                                 constants.JOB_STATUS_RUNNING):
        logging.debug("Cleaning job %s from the cache", job.id)
        try:
          del self._memcache[job.id]
        except KeyError:
          pass

  @utils.LockedMethod
  def UpdateJob(self, job):
    return self._UpdateJobUnlocked(job)

  @utils.LockedMethod
  def ArchiveJob(self, job_id):
    """Archives a job.

    @type job_id: string
    @param job_id: Job ID of job to be archived.

    """
    logging.debug("Archiving job %s", job_id)

    job = self._LoadJobUnlocked(job_id)
    if not job:
      logging.debug("Job %s not found", job_id)
      return

    if not self._ShouldJobBeArchivedUnlocked(job):
      return

    try:
      old = self._GetJobPath(job.id)
      new = self._GetArchivedJobPath(job.id)

      os.rename(old, new)

      logging.debug("Successfully archived job %s", job.id)
    finally:
      # Cleaning the cache because we don't know what os.rename actually did
      # and to be on the safe side.
      self._CleanCacheUnlocked([])


class JobQueue:
  """The job queue.

  """
  def __init__(self, context):
    self._lock = threading.Lock()
    self._jobs = DiskJobStorage("")
    self._wpool = _JobQueueWorkerPool(context)

    for job in self._jobs.GetJobs(None):
      status = job.GetStatus()
      if status in (constants.JOB_STATUS_QUEUED, ):
        self._wpool.AddTask(job)

      elif status in (constants.JOB_STATUS_RUNNING, ):
        logging.warning("Unfinished job %s found: %s", job.id, job)
        job.SetUnclean("Unclean master daemon shutdown")

  @utils.LockedMethod
  def SubmitJob(self, ops, nodes):
    """Add a new job to the queue.

    This enters the job into our job queue and also puts it on the new
    queue, in order for it to be picked up by the queue processors.

    @type ops: list
    @param ops: the sequence of opcodes that will become the new job
    @type nodes: list
    @param nodes: the list of nodes to which the queue should be
                  distributed

    """
    job = self._jobs.AddJob(ops, nodes)

    # Add to worker pool
    self._wpool.AddTask(job)

    return job.id

  def ArchiveJob(self, job_id):
    self._jobs.ArchiveJob(job_id)

  def CancelJob(self, job_id):
    raise NotImplementedError()

  def _GetJobInfo(self, job, fields):
    row = []
    for fname in fields:
      if fname == "id":
        row.append(job.id)
      elif fname == "status":
        row.append(job.GetStatus())
      elif fname == "ops":
        row.append([op.GetInput().__getstate__() for op in job._ops])
      elif fname == "opresult":
        row.append([op.GetResult() for op in job._ops])
      elif fname == "opstatus":
        row.append([op.GetStatus() for op in job._ops])
      elif fname == "ticker":
        ji = job.GetRunOpIndex()
        if ji < 0:
          lmsg = None
        else:
          lmsg = job._ops[ji].RetrieveLog(-1)
          # message might be empty here
          if lmsg:
            lmsg = lmsg[0]
          else:
            lmsg = None
        row.append(lmsg)
      else:
        raise errors.OpExecError("Invalid job query field '%s'" % fname)
    return row

  def QueryJobs(self, job_ids, fields):
    """Returns a list of jobs in queue.

    Args:
    - job_ids: Sequence of job identifiers or None for all
    - fields: Names of fields to return

    """
    self._lock.acquire()
    try:
      jobs = []

      for job in self._jobs.GetJobs(job_ids):
        if job is None:
          jobs.append(None)
        else:
          jobs.append(self._GetJobInfo(job, fields))

      return jobs
    finally:
      self._lock.release()

  @utils.LockedMethod
  def Shutdown(self):
    """Stops the job queue.

    """
    self._wpool.TerminateWorkers()
    self._jobs.Close()
