#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Module implementing the job queue handling.

Locking:
There's a single, large lock in the JobQueue class. It's used by all other
classes in this module.

"""

import os
import logging
import threading
import errno
import re
import time
import weakref

from ganeti import constants
from ganeti import serializer
from ganeti import workerpool
from ganeti import opcodes
from ganeti import errors
from ganeti import mcpu
from ganeti import utils
from ganeti import jstore
from ganeti import rpc


JOBQUEUE_THREADS = 25


def TimeStampNow():
  return utils.SplitTime(time.time())


class _QueuedOpCode(object):
  """Encasulates an opcode object.

  The 'log' attribute holds the execution log and consists of tuples
  of the form (log_serial, timestamp, level, message).

  """
  def __init__(self, op):
    self.input = op
    self.status = constants.OP_STATUS_QUEUED
    self.result = None
    self.log = []
    self.start_timestamp = None
    self.end_timestamp = None

  @classmethod
  def Restore(cls, state):
    obj = _QueuedOpCode.__new__(cls)
    obj.input = opcodes.OpCode.LoadOpCode(state["input"])
    obj.status = state["status"]
    obj.result = state["result"]
    obj.log = state["log"]
    obj.start_timestamp = state.get("start_timestamp", None)
    obj.end_timestamp = state.get("end_timestamp", None)
    return obj

  def Serialize(self):
    return {
      "input": self.input.__getstate__(),
      "status": self.status,
      "result": self.result,
      "log": self.log,
      "start_timestamp": self.start_timestamp,
      "end_timestamp": self.end_timestamp,
      }


class _QueuedJob(object):
  """In-memory job representation.

  This is what we use to track the user-submitted jobs. Locking must be taken
  care of by users of this class.

  """
  def __init__(self, queue, job_id, ops):
    if not ops:
      # TODO
      raise Exception("No opcodes")

    self.queue = queue
    self.id = job_id
    self.ops = [_QueuedOpCode(op) for op in ops]
    self.run_op_index = -1
    self.log_serial = 0
    self.received_timestamp = TimeStampNow()
    self.start_timestamp = None
    self.end_timestamp = None

    # Condition to wait for changes
    self.change = threading.Condition(self.queue._lock)

  @classmethod
  def Restore(cls, queue, state):
    obj = _QueuedJob.__new__(cls)
    obj.queue = queue
    obj.id = state["id"]
    obj.run_op_index = state["run_op_index"]
    obj.received_timestamp = state.get("received_timestamp", None)
    obj.start_timestamp = state.get("start_timestamp", None)
    obj.end_timestamp = state.get("end_timestamp", None)

    obj.ops = []
    obj.log_serial = 0
    for op_state in state["ops"]:
      op = _QueuedOpCode.Restore(op_state)
      for log_entry in op.log:
        obj.log_serial = max(obj.log_serial, log_entry[0])
      obj.ops.append(op)

    # Condition to wait for changes
    obj.change = threading.Condition(obj.queue._lock)

    return obj

  def Serialize(self):
    return {
      "id": self.id,
      "ops": [op.Serialize() for op in self.ops],
      "run_op_index": self.run_op_index,
      "start_timestamp": self.start_timestamp,
      "end_timestamp": self.end_timestamp,
      "received_timestamp": self.received_timestamp,
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

  def GetLogEntries(self, newer_than):
    if newer_than is None:
      serial = -1
    else:
      serial = newer_than

    entries = []
    for op in self.ops:
      entries.extend(filter(lambda entry: entry[0] > newer_than, op.log))

    return entries


class _JobQueueWorker(workerpool.BaseWorker):
  def RunTask(self, job):
    """Job executor.

    This functions processes a job. It is closely tied to the _QueuedJob and
    _QueuedOpCode classes.

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
              op.start_timestamp = TimeStampNow()
              if idx == 0: # first opcode
                job.start_timestamp = op.start_timestamp
              queue.UpdateJobUnlocked(job)

              input_opcode = op.input
            finally:
              queue.release()

            def _Log(*args):
              """Append a log entry.

              """
              assert len(args) < 3

              if len(args) == 1:
                log_type = constants.ELOG_MESSAGE
                log_msg = args[0]
              else:
                log_type, log_msg = args

              # The time is split to make serialization easier and not lose
              # precision.
              timestamp = utils.SplitTime(time.time())

              queue.acquire()
              try:
                job.log_serial += 1
                op.log.append((job.log_serial, timestamp, log_type, log_msg))

                job.change.notifyAll()
              finally:
                queue.release()

            # Make sure not to hold lock while _Log is called
            result = proc.ExecOpCode(input_opcode, _Log)

            queue.acquire()
            try:
              op.status = constants.OP_STATUS_SUCCESS
              op.result = result
              op.end_timestamp = TimeStampNow()
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
                op.end_timestamp = TimeStampNow()
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
        try:
          job.run_op_idx = -1
          job.end_timestamp = TimeStampNow()
          queue.UpdateJobUnlocked(job)
        finally:
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
    self._memcache = weakref.WeakValueDictionary()
    self._my_hostname = utils.HostInfo().name

    # Locking
    self._lock = threading.Lock()
    self.acquire = self._lock.acquire
    self.release = self._lock.release

    # Initialize
    self._queue_lock = jstore.InitAndVerifyQueue(must_lock=True)

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

  @utils.LockedMethod
  @_RequireOpenQueue
  def AddNode(self, node_name):
    assert node_name != self._my_hostname

    # Clean queue directory on added node
    rpc.call_jobqueue_purge(node_name)

    # Upload the whole queue excluding archived jobs
    files = [self._GetJobPath(job_id) for job_id in self._GetJobIDsUnlocked()]

    # Upload current serial file
    files.append(constants.JOB_QUEUE_SERIAL_FILE)

    for file_name in files:
      # Read file content
      fd = open(file_name, "r")
      try:
        content = fd.read()
      finally:
        fd.close()

      result = rpc.call_jobqueue_update([node_name], file_name, content)
      if not result[node_name]:
        logging.error("Failed to upload %s to %s", file_name, node_name)

    self._nodes.add(node_name)

  @utils.LockedMethod
  @_RequireOpenQueue
  def RemoveNode(self, node_name):
    try:
      # The queue is removed by the "leave node" RPC call.
      self._nodes.remove(node_name)
    except KeyError:
      pass

  def _CheckRpcResult(self, result, nodes, failmsg):
    failed = []
    success = []

    for node in nodes:
      if result[node]:
        success.append(node)
      else:
        failed.append(node)

    if failed:
      logging.error("%s failed on %s", failmsg, ", ".join(failed))

    # +1 for the master node
    if (len(success) + 1) < len(failed):
      # TODO: Handle failing nodes
      logging.error("More than half of the nodes failed")

  def _WriteAndReplicateFileUnlocked(self, file_name, data):
    """Writes a file locally and then replicates it to all nodes.

    """
    utils.WriteFile(file_name, data=data)

    result = rpc.call_jobqueue_update(self._nodes, file_name, data)
    self._CheckRpcResult(result, self._nodes,
                         "Updating %s" % file_name)

  def _RenameFileUnlocked(self, old, new):
    os.rename(old, new)

    result = rpc.call_jobqueue_rename(self._nodes, old, new)
    self._CheckRpcResult(result, self._nodes,
                         "Moving %s to %s" % (old, new))

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
    jlist = utils.NiceSort(jlist)
    return jlist

  def _ListJobFiles(self):
    return [name for name in utils.ListVisibleFiles(constants.QUEUE_DIR)
            if self._RE_JOB_FILE.match(name)]

  def _LoadJobUnlocked(self, job_id):
    job = self._memcache.get(job_id, None)
    if job:
      logging.debug("Found job %s in memcache", job_id)
      return job

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

    logging.debug("Adding new job %s to the cache", job_id)
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

    # Notify waiters about potential changes
    job.change.notifyAll()

  @utils.LockedMethod
  @_RequireOpenQueue
  def WaitForJobChanges(self, job_id, fields, prev_job_info, prev_log_serial,
                        timeout):
    """Waits for changes in a job.

    @type job_id: string
    @param job_id: Job identifier
    @type fields: list of strings
    @param fields: Which fields to check for changes
    @type prev_job_info: list or None
    @param prev_job_info: Last job information returned
    @type prev_log_serial: int
    @param prev_log_serial: Last job message serial number
    @type timeout: float
    @param timeout: maximum time to wait

    """
    logging.debug("Waiting for changes in job %s", job_id)
    end_time = time.time() + timeout
    while True:
      delta_time = end_time - time.time()
      if delta_time < 0:
        return constants.JOB_NOTCHANGED

      job = self._LoadJobUnlocked(job_id)
      if not job:
        logging.debug("Job %s not found", job_id)
        break

      status = job.CalcStatus()
      job_info = self._GetJobInfoUnlocked(job, fields)
      log_entries = job.GetLogEntries(prev_log_serial)

      # Serializing and deserializing data can cause type changes (e.g. from
      # tuple to list) or precision loss. We're doing it here so that we get
      # the same modifications as the data received from the client. Without
      # this, the comparison afterwards might fail without the data being
      # significantly different.
      job_info = serializer.LoadJson(serializer.DumpJson(job_info))
      log_entries = serializer.LoadJson(serializer.DumpJson(log_entries))

      if status not in (constants.JOB_STATUS_QUEUED,
                        constants.JOB_STATUS_RUNNING):
        # Don't even try to wait if the job is no longer running, there will be
        # no changes.
        break

      if (prev_job_info != job_info or
          (log_entries and prev_log_serial != log_entries[0][0])):
        break

      logging.debug("Waiting again")

      # Release the queue lock while waiting
      job.change.wait(delta_time)

    logging.debug("Job %s changed", job_id)

    return (job_info, log_entries)

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

  @_RequireOpenQueue
  def _ArchiveJobUnlocked(self, job_id):
    """Archives a job.

    @type job_id: string
    @param job_id: Job ID of job to be archived.

    """
    logging.info("Archiving job %s", job_id)

    job = self._LoadJobUnlocked(job_id)
    if not job:
      logging.debug("Job %s not found", job_id)
      return

    if job.CalcStatus() not in (constants.JOB_STATUS_CANCELED,
                                constants.JOB_STATUS_SUCCESS,
                                constants.JOB_STATUS_ERROR):
      logging.debug("Job %s is not yet done", job.id)
      return

    old = self._GetJobPath(job.id)
    new = self._GetArchivedJobPath(job.id)

    self._RenameFileUnlocked(old, new)

    logging.debug("Successfully archived job %s", job.id)

  @utils.LockedMethod
  @_RequireOpenQueue
  def ArchiveJob(self, job_id):
    """Archives a job.

    @type job_id: string
    @param job_id: Job ID of job to be archived.

    """
    return self._ArchiveJobUnlocked(job_id)

  @utils.LockedMethod
  @_RequireOpenQueue
  def AutoArchiveJobs(self, age):
    """Archives all jobs based on age.

    The method will archive all jobs which are older than the age
    parameter. For jobs that don't have an end timestamp, the start
    timestamp will be considered. The special '-1' age will cause
    archival of all jobs (that are not running or queued).

    @type age: int
    @param age: the minimum age in seconds

    """
    logging.info("Archiving jobs with age more than %s seconds", age)

    now = time.time()
    for jid in self._GetJobIDsUnlocked(archived=False):
      job = self._LoadJobUnlocked(jid)
      if job.CalcStatus() not in (constants.OP_STATUS_SUCCESS,
                                  constants.OP_STATUS_ERROR,
                                  constants.OP_STATUS_CANCELED):
        continue
      if job.end_timestamp is None:
        if job.start_timestamp is None:
          job_age = job.received_timestamp
        else:
          job_age = job.start_timestamp
      else:
        job_age = job.end_timestamp

      if age == -1 or now - job_age[0] > age:
        self._ArchiveJobUnlocked(jid)

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
      elif fname == "oplog":
        row.append([op.log for op in job.ops])
      elif fname == "opstart":
        row.append([op.start_timestamp for op in job.ops])
      elif fname == "opend":
        row.append([op.end_timestamp for op in job.ops])
      elif fname == "received_ts":
        row.append(job.received_timestamp)
      elif fname == "start_ts":
        row.append(job.start_timestamp)
      elif fname == "end_ts":
        row.append(job.end_timestamp)
      elif fname == "summary":
        row.append([op.input.Summary() for op in job.ops])
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
