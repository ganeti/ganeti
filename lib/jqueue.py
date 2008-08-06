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
from ganeti import jstore
from ganeti import rpc


JOBQUEUE_THREADS = 5


class _QueuedOpCode(object):
  """Encasulates an opcode object.

  Access is synchronized by the '_lock' attribute.

  The 'log' attribute holds the execution log and consists of tuples
  of the form (timestamp, level, message).

  """
  def __new__(cls, *args, **kwargs):
    obj = object.__new__(cls, *args, **kwargs)
    # Create a special lock for logging
    obj._log_lock = threading.Lock()
    return obj

  def __init__(self, op):
    self.input = op
    self.status = constants.OP_STATUS_QUEUED
    self.result = None
    self.log = []

  @classmethod
  def Restore(cls, state):
    obj = _QueuedOpCode.__new__(cls)
    obj.input = opcodes.OpCode.LoadOpCode(state["input"])
    obj.status = state["status"]
    obj.result = state["result"]
    obj.log = state["log"]
    return obj

  def Serialize(self):
    self._log_lock.acquire()
    try:
      return {
        "input": self.input.__getstate__(),
        "status": self.status,
        "result": self.result,
        "log": self.log,
        }
    finally:
      self._log_lock.release()

  def Log(self, *args):
    """Append a log entry.

    """
    assert len(args) < 3

    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      log_type, log_msg = args

    self._log_lock.acquire()
    try:
      self.log.append((time.time(), log_type, log_msg))
    finally:
      self._log_lock.release()

  def RetrieveLog(self, start_at=0):
    """Retrieve (a part of) the execution log.

    """
    self._log_lock.acquire()
    try:
      return self.log[start_at:]
    finally:
      self._log_lock.release()


class _QueuedJob(object):
  """In-memory job representation.

  This is what we use to track the user-submitted jobs.

  """
  def __init__(self, queue, job_id, ops):
    if not ops:
      # TODO
      raise Exception("No opcodes")

    self.queue = queue
    self.id = job_id
    self.ops = [_QueuedOpCode(op) for op in ops]
    self.run_op_index = -1

  @classmethod
  def Restore(cls, queue, state):
    obj = _QueuedJob.__new__(cls)
    obj.queue = queue
    obj.id = state["id"]
    obj.ops = [_QueuedOpCode.Restore(op_state) for op_state in state["ops"]]
    obj.run_op_index = state["run_op_index"]
    return obj

  def Serialize(self):
    return {
      "id": self.id,
      "ops": [op.Serialize() for op in self.ops],
      "run_op_index": self.run_op_index,
      }

  def CalcStatus(self):
    status = constants.JOB_STATUS_QUEUED

    all_success = True
    for op in self.ops:
      if op.status == constants.OP_STATUS_SUCCESS:
        continue

      all_success = False

      if op.status == constants.OP_STATUS_QUEUED:
        pass
      elif op.status == constants.OP_STATUS_RUNNING:
        status = constants.JOB_STATUS_RUNNING
      elif op.status == constants.OP_STATUS_ERROR:
        status = constants.JOB_STATUS_ERROR
        # The whole job fails if one opcode failed
        break
      elif op.status == constants.OP_STATUS_CANCELED:
        status = constants.OP_STATUS_CANCELED
        break

    if all_success:
      status = constants.JOB_STATUS_SUCCESS

    return status


class _JobQueueWorker(workerpool.BaseWorker):
  def RunTask(self, job):
    """Job executor.

    This functions processes a job.

    """
    logging.debug("Worker %s processing job %s",
                  self.worker_id, job.id)
    proc = mcpu.Processor(self.pool.queue.context)
    queue = job.queue
    try:
      try:
        count = len(job.ops)
        for idx, op in enumerate(job.ops):
          try:
            logging.debug("Op %s/%s: Starting %s", idx + 1, count, op)

            queue.acquire()
            try:
              job.run_op_index = idx
              op.status = constants.OP_STATUS_RUNNING
              op.result = None
              queue.UpdateJobUnlocked(job)

              input_opcode = op.input
            finally:
              queue.release()

            result = proc.ExecOpCode(input_opcode, op.Log)

            queue.acquire()
            try:
              op.status = constants.OP_STATUS_SUCCESS
              op.result = result
              queue.UpdateJobUnlocked(job)
            finally:
              queue.release()

            logging.debug("Op %s/%s: Successfully finished %s",
                          idx + 1, count, op)
          except Exception, err:
            queue.acquire()
            try:
              try:
                op.status = constants.OP_STATUS_ERROR
                op.result = str(err)
                logging.debug("Op %s/%s: Error in %s", idx + 1, count, op)
              finally:
                queue.UpdateJobUnlocked(job)
            finally:
              queue.release()
            raise

      except errors.GenericError, err:
        logging.exception("Ganeti exception")
      except:
        logging.exception("Unhandled exception")
    finally:
      queue.acquire()
      try:
        job_id = job.id
        status = job.CalcStatus()
      finally:
        queue.release()
      logging.debug("Worker %s finished job %s, status = %s",
                    self.worker_id, job_id, status)


class _JobQueueWorkerPool(workerpool.WorkerPool):
  def __init__(self, queue):
    super(_JobQueueWorkerPool, self).__init__(JOBQUEUE_THREADS,
                                              _JobQueueWorker)
    self.queue = queue


class JobQueue(object):
  _RE_JOB_FILE = re.compile(r"^job-(%s)$" % constants.JOB_ID_TEMPLATE)

  def _RequireOpenQueue(fn):
    """Decorator for "public" functions.

    This function should be used for all "public" functions. That is, functions
    usually called from other classes.

    Important: Use this decorator only after utils.LockedMethod!

    Example:
      @utils.LockedMethod
      @_RequireOpenQueue
      def Example(self):
        pass

    """
    def wrapper(self, *args, **kwargs):
      assert self._queue_lock is not None, "Queue should be open"
      return fn(self, *args, **kwargs)
    return wrapper

  def __init__(self, context):
    self.context = context
    self._memcache = {}
    self._my_hostname = utils.HostInfo().name

    # Locking
    self._lock = threading.Lock()
    self.acquire = self._lock.acquire
    self.release = self._lock.release

    # Initialize
    self._queue_lock = jstore.InitAndVerifyQueue(exclusive=True)

    # Read serial file
    self._last_serial = jstore.ReadSerial()
    assert self._last_serial is not None, ("Serial file was modified between"
                                           " check in jstore and here")

    # Get initial list of nodes
    self._nodes = set(self.context.cfg.GetNodeList())

    # Remove master node
    try:
      self._nodes.remove(self._my_hostname)
    except ValueError:
      pass

    # TODO: Check consistency across nodes

    # Setup worker pool
    self._wpool = _JobQueueWorkerPool(self)

    # We need to lock here because WorkerPool.AddTask() may start a job while
    # we're still doing our work.
    self.acquire()
    try:
      for job in self._GetJobsUnlocked(None):
        status = job.CalcStatus()

        if status in (constants.JOB_STATUS_QUEUED, ):
          self._wpool.AddTask(job)

        elif status in (constants.JOB_STATUS_RUNNING, ):
          logging.warning("Unfinished job %s found: %s", job.id, job)
          try:
            for op in job.ops:
              op.status = constants.OP_STATUS_ERROR
              op.result = "Unclean master daemon shutdown"
          finally:
            self.UpdateJobUnlocked(job)
    finally:
      self.release()

  def _WriteAndReplicateFileUnlocked(self, file_name, data):
    """Writes a file locally and then replicates it to all nodes.

    """
    utils.WriteFile(file_name, data=data)

    nodes = self._nodes[:]

    # Remove master node
    try:
      nodes.remove(self._my_hostname)
    except ValueError:
      pass

  def _WriteAndReplicateFileUnlocked(self, file_name, data):
    """Writes a file locally and then replicates it to all nodes.

    """
    utils.WriteFile(file_name, data=data)

    failed_nodes = 0
    result = rpc.call_upload_file(self._nodes, file_name)
    for node in self._nodes:
      if not result[node]:
        failed_nodes += 1
        logging.error("Copy of job queue file to node %s failed", node)

    # TODO: check failed_nodes

  def _FormatJobID(self, job_id):
    if not isinstance(job_id, (int, long)):
      raise errors.ProgrammerError("Job ID '%s' not numeric" % job_id)
    if job_id < 0:
      raise errors.ProgrammerError("Job ID %s is negative" % job_id)

    return str(job_id)

  def _NewSerialUnlocked(self):
    """Generates a new job identifier.

    Job identifiers are unique during the lifetime of a cluster.

    Returns: A string representing the job identifier.

    """
    # New number
    serial = self._last_serial + 1

    # Write to file
    self._WriteAndReplicateFileUnlocked(constants.JOB_QUEUE_SERIAL_FILE,
                                        "%s\n" % serial)

    # Keep it only if we were able to write the file
    self._last_serial = serial

    return self._FormatJobID(serial)

  @staticmethod
  def _GetJobPath(job_id):
    return os.path.join(constants.QUEUE_DIR, "job-%s" % job_id)

  @staticmethod
  def _GetArchivedJobPath(job_id):
    return os.path.join(constants.JOB_QUEUE_ARCHIVE_DIR, "job-%s" % job_id)

  @classmethod
  def _ExtractJobID(cls, name):
    m = cls._RE_JOB_FILE.match(name)
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
    return [name for name in utils.ListVisibleFiles(constants.QUEUE_DIR)
            if self._RE_JOB_FILE.match(name)]

  def _LoadJobUnlocked(self, job_id):
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
  @_RequireOpenQueue
  def SubmitJob(self, ops):
    """Create and store a new job.

    This enters the job into our job queue and also puts it on the new
    queue, in order for it to be picked up by the queue processors.

    @type ops: list
    @param ops: The list of OpCodes that will become the new job.

    """
    # Get job identifier
    job_id = self._NewSerialUnlocked()
    job = _QueuedJob(self, job_id, ops)

    # Write to disk
    self.UpdateJobUnlocked(job)

    logging.debug("Added new job %s to the cache", job_id)
    self._memcache[job_id] = job

    # Add to worker pool
    self._wpool.AddTask(job)

    return job.id

  @_RequireOpenQueue
  def UpdateJobUnlocked(self, job):
    filename = self._GetJobPath(job.id)
    data = serializer.DumpJson(job.Serialize(), indent=False)
    logging.debug("Writing job %s to %s", job.id, filename)
    self._WriteAndReplicateFileUnlocked(filename, data)
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
      if job.CalcStatus() not in (constants.JOB_STATUS_QUEUED,
                                  constants.JOB_STATUS_RUNNING):
        logging.debug("Cleaning job %s from the cache", job.id)
        try:
          del self._memcache[job.id]
        except KeyError:
          pass

  @utils.LockedMethod
  @_RequireOpenQueue
  def CancelJob(self, job_id):
    """Cancels a job.

    @type job_id: string
    @param job_id: Job ID of job to be cancelled.

    """
    logging.debug("Cancelling job %s", job_id)

    job = self._LoadJobUnlocked(job_id)
    if not job:
      logging.debug("Job %s not found", job_id)
      return

    if job.CalcStatus() not in (constants.JOB_STATUS_QUEUED,):
      logging.debug("Job %s is no longer in the queue", job.id)
      return

    try:
      for op in job.ops:
        op.status = constants.OP_STATUS_ERROR
        op.result = "Job cancelled by request"
    finally:
      self.UpdateJobUnlocked(job)

  @utils.LockedMethod
  @_RequireOpenQueue
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

    if job.CalcStatus() not in (constants.JOB_STATUS_CANCELED,
                                constants.JOB_STATUS_SUCCESS,
                                constants.JOB_STATUS_ERROR):
      logging.debug("Job %s is not yet done", job.id)
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

  def _GetJobInfoUnlocked(self, job, fields):
    row = []
    for fname in fields:
      if fname == "id":
        row.append(job.id)
      elif fname == "status":
        row.append(job.CalcStatus())
      elif fname == "ops":
        row.append([op.input.__getstate__() for op in job.ops])
      elif fname == "opresult":
        row.append([op.result for op in job.ops])
      elif fname == "opstatus":
        row.append([op.status for op in job.ops])
      elif fname == "ticker":
        ji = job.run_op_index
        if ji < 0:
          lmsg = None
        else:
          lmsg = job.ops[ji].RetrieveLog(-1)
          # message might be empty here
          if lmsg:
            lmsg = lmsg[0]
          else:
            lmsg = None
        row.append(lmsg)
      else:
        raise errors.OpExecError("Invalid job query field '%s'" % fname)
    return row

  @utils.LockedMethod
  @_RequireOpenQueue
  def QueryJobs(self, job_ids, fields):
    """Returns a list of jobs in queue.

    Args:
    - job_ids: Sequence of job identifiers or None for all
    - fields: Names of fields to return

    """
    jobs = []

    for job in self._GetJobsUnlocked(job_ids):
      if job is None:
        jobs.append(None)
      else:
        jobs.append(self._GetJobInfoUnlocked(job, fields))

    return jobs

  @utils.LockedMethod
  @_RequireOpenQueue
  def Shutdown(self):
    """Stops the job queue.

    """
    self._wpool.TerminateWorkers()

    self._queue_lock.Close()
    self._queue_lock = None
