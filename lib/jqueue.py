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

Locking: there's a single, large lock in the L{JobQueue} class. It's
used by all other classes in this module.

@var JOBQUEUE_THREADS: the number of worker threads we start for
    processing jobs

"""

import os
import logging
import threading
import errno
import re
import time
import weakref

try:
  # pylint: disable-msg=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
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
JOBS_PER_ARCHIVE_DIRECTORY = 10000


class CancelJob(Exception):
  """Special exception to cancel a job.

  """


def TimeStampNow():
  """Returns the current timestamp.

  @rtype: tuple
  @return: the current time in the (seconds, microseconds) format

  """
  return utils.SplitTime(time.time())


class _QueuedOpCode(object):
  """Encapsulates an opcode object.

  @ivar log: holds the execution log and consists of tuples
  of the form C{(log_serial, timestamp, level, message)}
  @ivar input: the OpCode we encapsulate
  @ivar status: the current status
  @ivar result: the result of the LU execution
  @ivar start_timestamp: timestamp for the start of the execution
  @ivar exec_timestamp: timestamp for the actual LU Exec() function invocation
  @ivar stop_timestamp: timestamp for the end of the execution

  """
  __slots__ = ["input", "status", "result", "log",
               "start_timestamp", "exec_timestamp", "end_timestamp",
               "__weakref__"]

  def __init__(self, op):
    """Constructor for the _QuededOpCode.

    @type op: L{opcodes.OpCode}
    @param op: the opcode we encapsulate

    """
    self.input = op
    self.status = constants.OP_STATUS_QUEUED
    self.result = None
    self.log = []
    self.start_timestamp = None
    self.exec_timestamp = None
    self.end_timestamp = None

  @classmethod
  def Restore(cls, state):
    """Restore the _QueuedOpCode from the serialized form.

    @type state: dict
    @param state: the serialized state
    @rtype: _QueuedOpCode
    @return: a new _QueuedOpCode instance

    """
    obj = _QueuedOpCode.__new__(cls)
    obj.input = opcodes.OpCode.LoadOpCode(state["input"])
    obj.status = state["status"]
    obj.result = state["result"]
    obj.log = state["log"]
    obj.start_timestamp = state.get("start_timestamp", None)
    obj.exec_timestamp = state.get("exec_timestamp", None)
    obj.end_timestamp = state.get("end_timestamp", None)
    return obj

  def Serialize(self):
    """Serializes this _QueuedOpCode.

    @rtype: dict
    @return: the dictionary holding the serialized state

    """
    return {
      "input": self.input.__getstate__(),
      "status": self.status,
      "result": self.result,
      "log": self.log,
      "start_timestamp": self.start_timestamp,
      "exec_timestamp": self.exec_timestamp,
      "end_timestamp": self.end_timestamp,
      }


class _QueuedJob(object):
  """In-memory job representation.

  This is what we use to track the user-submitted jobs. Locking must
  be taken care of by users of this class.

  @type queue: L{JobQueue}
  @ivar queue: the parent queue
  @ivar id: the job ID
  @type ops: list
  @ivar ops: the list of _QueuedOpCode that constitute the job
  @type log_serial: int
  @ivar log_serial: holds the index for the next log entry
  @ivar received_timestamp: the timestamp for when the job was received
  @ivar start_timestmap: the timestamp for start of execution
  @ivar end_timestamp: the timestamp for end of execution
  @ivar lock_status: In-memory locking information for debugging
  @ivar change: a Condition variable we use for waiting for job changes

  """
  # pylint: disable-msg=W0212
  __slots__ = ["queue", "id", "ops", "log_serial",
               "received_timestamp", "start_timestamp", "end_timestamp",
               "lock_status", "change",
               "__weakref__"]

  def __init__(self, queue, job_id, ops):
    """Constructor for the _QueuedJob.

    @type queue: L{JobQueue}
    @param queue: our parent queue
    @type job_id: job_id
    @param job_id: our job id
    @type ops: list
    @param ops: the list of opcodes we hold, which will be encapsulated
        in _QueuedOpCodes

    """
    if not ops:
      raise errors.GenericError("A job needs at least one opcode")

    self.queue = queue
    self.id = job_id
    self.ops = [_QueuedOpCode(op) for op in ops]
    self.log_serial = 0
    self.received_timestamp = TimeStampNow()
    self.start_timestamp = None
    self.end_timestamp = None

    # In-memory attributes
    self.lock_status = None

    # Condition to wait for changes
    self.change = threading.Condition(self.queue._lock)

  def __repr__(self):
    status = ["%s.%s" % (self.__class__.__module__, self.__class__.__name__),
              "id=%s" % self.id,
              "ops=%s" % ",".join([op.input.Summary() for op in self.ops])]

    return "<%s at %#x>" % (" ".join(status), id(self))

  @classmethod
  def Restore(cls, queue, state):
    """Restore a _QueuedJob from serialized state:

    @type queue: L{JobQueue}
    @param queue: to which queue the restored job belongs
    @type state: dict
    @param state: the serialized state
    @rtype: _JobQueue
    @return: the restored _JobQueue instance

    """
    obj = _QueuedJob.__new__(cls)
    obj.queue = queue
    obj.id = state["id"]
    obj.received_timestamp = state.get("received_timestamp", None)
    obj.start_timestamp = state.get("start_timestamp", None)
    obj.end_timestamp = state.get("end_timestamp", None)

    # In-memory attributes
    obj.lock_status = None

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
    """Serialize the _JobQueue instance.

    @rtype: dict
    @return: the serialized state

    """
    return {
      "id": self.id,
      "ops": [op.Serialize() for op in self.ops],
      "start_timestamp": self.start_timestamp,
      "end_timestamp": self.end_timestamp,
      "received_timestamp": self.received_timestamp,
      }

  def CalcStatus(self):
    """Compute the status of this job.

    This function iterates over all the _QueuedOpCodes in the job and
    based on their status, computes the job status.

    The algorithm is:
      - if we find a cancelled, or finished with error, the job
        status will be the same
      - otherwise, the last opcode with the status one of:
          - waitlock
          - canceling
          - running

        will determine the job status

      - otherwise, it means either all opcodes are queued, or success,
        and the job status will be the same

    @return: the job status

    """
    status = constants.JOB_STATUS_QUEUED

    all_success = True
    for op in self.ops:
      if op.status == constants.OP_STATUS_SUCCESS:
        continue

      all_success = False

      if op.status == constants.OP_STATUS_QUEUED:
        pass
      elif op.status == constants.OP_STATUS_WAITLOCK:
        status = constants.JOB_STATUS_WAITLOCK
      elif op.status == constants.OP_STATUS_RUNNING:
        status = constants.JOB_STATUS_RUNNING
      elif op.status == constants.OP_STATUS_CANCELING:
        status = constants.JOB_STATUS_CANCELING
        break
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
    """Selectively returns the log entries.

    @type newer_than: None or int
    @param newer_than: if this is None, return all log entries,
        otherwise return only the log entries with serial higher
        than this value
    @rtype: list
    @return: the list of the log entries selected

    """
    if newer_than is None:
      serial = -1
    else:
      serial = newer_than

    entries = []
    for op in self.ops:
      entries.extend(filter(lambda entry: entry[0] > serial, op.log))

    return entries

  def GetInfo(self, fields):
    """Returns information about a job.

    @type fields: list
    @param fields: names of fields to return
    @rtype: list
    @return: list with one element for each field
    @raise errors.OpExecError: when an invalid field
        has been passed

    """
    row = []
    for fname in fields:
      if fname == "id":
        row.append(self.id)
      elif fname == "status":
        row.append(self.CalcStatus())
      elif fname == "ops":
        row.append([op.input.__getstate__() for op in self.ops])
      elif fname == "opresult":
        row.append([op.result for op in self.ops])
      elif fname == "opstatus":
        row.append([op.status for op in self.ops])
      elif fname == "oplog":
        row.append([op.log for op in self.ops])
      elif fname == "opstart":
        row.append([op.start_timestamp for op in self.ops])
      elif fname == "opexec":
        row.append([op.exec_timestamp for op in self.ops])
      elif fname == "opend":
        row.append([op.end_timestamp for op in self.ops])
      elif fname == "received_ts":
        row.append(self.received_timestamp)
      elif fname == "start_ts":
        row.append(self.start_timestamp)
      elif fname == "end_ts":
        row.append(self.end_timestamp)
      elif fname == "lock_status":
        row.append(self.lock_status)
      elif fname == "summary":
        row.append([op.input.Summary() for op in self.ops])
      else:
        raise errors.OpExecError("Invalid self query field '%s'" % fname)
    return row

  def MarkUnfinishedOps(self, status, result):
    """Mark unfinished opcodes with a given status and result.

    This is an utility function for marking all running or waiting to
    be run opcodes with a given status. Opcodes which are already
    finalised are not changed.

    @param status: a given opcode status
    @param result: the opcode result

    """
    not_marked = True
    for op in self.ops:
      if op.status in constants.OPS_FINALIZED:
        assert not_marked, "Finalized opcodes found after non-finalized ones"
        continue
      op.status = status
      op.result = result
      not_marked = False


class _OpExecCallbacks(mcpu.OpExecCbBase):
  def __init__(self, queue, job, op):
    """Initializes this class.

    @type queue: L{JobQueue}
    @param queue: Job queue
    @type job: L{_QueuedJob}
    @param job: Job object
    @type op: L{_QueuedOpCode}
    @param op: OpCode

    """
    assert queue, "Queue is missing"
    assert job, "Job is missing"
    assert op, "Opcode is missing"

    self._queue = queue
    self._job = job
    self._op = op

  def NotifyStart(self):
    """Mark the opcode as running, not lock-waiting.

    This is called from the mcpu code as a notifier function, when the LU is
    finally about to start the Exec() method. Of course, to have end-user
    visible results, the opcode must be initially (before calling into
    Processor.ExecOpCode) set to OP_STATUS_WAITLOCK.

    """
    self._queue.acquire()
    try:
      assert self._op.status in (constants.OP_STATUS_WAITLOCK,
                                 constants.OP_STATUS_CANCELING)

      # All locks are acquired by now
      self._job.lock_status = None

      # Cancel here if we were asked to
      if self._op.status == constants.OP_STATUS_CANCELING:
        raise CancelJob()

      self._op.status = constants.OP_STATUS_RUNNING
      self._op.exec_timestamp = TimeStampNow()
    finally:
      self._queue.release()

  def Feedback(self, *args):
    """Append a log entry.

    """
    assert len(args) < 3

    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      (log_type, log_msg) = args

    # The time is split to make serialization easier and not lose
    # precision.
    timestamp = utils.SplitTime(time.time())

    self._queue.acquire()
    try:
      self._job.log_serial += 1
      self._op.log.append((self._job.log_serial, timestamp, log_type, log_msg))
      self._queue.UpdateJobUnlocked(self._job, replicate=False)

      self._job.change.notifyAll()
    finally:
      self._queue.release()

  def ReportLocks(self, msg):
    """Write locking information to the job.

    Called whenever the LU processor is waiting for a lock or has acquired one.

    """
    # Not getting the queue lock because this is a single assignment
    self._job.lock_status = msg


class _WaitForJobChangesHelper(object):
  """Helper class using initofy to wait for changes in a job file.

  This class takes a previous job status and serial, and alerts the client when
  the current job status has changed.

  @type job_id: string
  @ivar job_id: id of the job we're watching
  @type prev_job_info: string
  @ivar prev_job_info: previous job info, as passed by the luxi client
  @type prev_log_serial: string
  @ivar prev_log_serial: previous job serial, as passed by the luxi client
  @type queue: L{JobQueue}
  @ivar queue: job queue (used for a few utility functions)
  @type job_path: string
  @ivar job_path: absolute path of the job file
  @type wm: pyinotify.WatchManager (or None)
  @ivar wm: inotify watch manager to watch for changes
  @type inotify_handler: L{asyncnotifier.SingleFileEventHandler}
  @ivar inotify_handler: single file event handler, used for watching
  @type notifier: pyinotify.Notifier
  @ivar notifier: inotify single-threaded notifier, used for watching

  """

  def __init__(self, job_id, fields, prev_job_info, prev_log_serial, queue):
    self.job_id = job_id
    self.fields = fields
    self.prev_job_info = prev_job_info
    self.prev_log_serial = prev_log_serial
    self.queue = queue
    # pylint: disable-msg=W0212
    self.job_path = self.queue._GetJobPath(self.job_id)
    self.wm = None
    self.inotify_handler = None
    self.notifier = None

  def _SetupInotify(self):
    """Create the inotify

    @raises errors.InotifyError: if the notifier cannot be setup

    """
    if self.wm:
      return
    self.wm = pyinotify.WatchManager()
    self.inotify_handler = asyncnotifier.SingleFileEventHandler(self.wm,
                                                                self.OnInotify,
                                                                self.job_path)
    self.notifier = pyinotify.Notifier(self.wm, self.inotify_handler)
    self.inotify_handler.enable()

  def _LoadDiskStatus(self):
    job = self.queue.SafeLoadJobFromDisk(self.job_id)
    if not job:
      raise errors.JobLost()
    self.job_status = job.CalcStatus()

    job_info = job.GetInfo(self.fields)
    log_entries = job.GetLogEntries(self.prev_log_serial)
    # Serializing and deserializing data can cause type changes (e.g. from
    # tuple to list) or precision loss. We're doing it here so that we get
    # the same modifications as the data received from the client. Without
    # this, the comparison afterwards might fail without the data being
    # significantly different.
    # TODO: we just deserialized from disk, investigate how to make sure that
    # the job info and log entries are compatible to avoid this further step.
    self.job_info = serializer.LoadJson(serializer.DumpJson(job_info))
    self.log_entries = serializer.LoadJson(serializer.DumpJson(log_entries))

  def _CheckForChanges(self):
    self._LoadDiskStatus()
    # Don't even try to wait if the job is no longer running, there will be
    # no changes.
    if (self.job_status not in (constants.JOB_STATUS_QUEUED,
                                constants.JOB_STATUS_RUNNING,
                                constants.JOB_STATUS_WAITLOCK) or
        self.prev_job_info != self.job_info or
        (self.log_entries and self.prev_log_serial != self.log_entries[0][0])):
      logging.debug("Job %s changed", self.job_id)
      return (self.job_info, self.log_entries)

    raise utils.RetryAgain()

  def OnInotify(self, notifier_enabled):
    if not notifier_enabled:
      self.inotify_handler.enable()

  def WaitFn(self, timeout):
    self._SetupInotify()
    if self.notifier.check_events(timeout*1000):
      self.notifier.read_events()
    self.notifier.process_events()

  def WaitForChanges(self, timeout):
    try:
      return utils.Retry(self._CheckForChanges,
                         utils.RETRY_REMAINING_TIME,
                         timeout,
                         wait_fn=self.WaitFn)
    except (errors.InotifyError, errors.JobLost):
      return None
    except utils.RetryTimeout:
      return constants.JOB_NOTCHANGED

  def Close(self):
    if self.wm:
      self.notifier.stop()


class _JobQueueWorker(workerpool.BaseWorker):
  """The actual job workers.

  """
  def RunTask(self, job): # pylint: disable-msg=W0221
    """Job executor.

    This functions processes a job. It is closely tied to the _QueuedJob and
    _QueuedOpCode classes.

    @type job: L{_QueuedJob}
    @param job: the job to be processed

    """
    logging.info("Processing job %s", job.id)
    proc = mcpu.Processor(self.pool.queue.context, job.id)
    queue = job.queue
    try:
      try:
        count = len(job.ops)
        for idx, op in enumerate(job.ops):
          op_summary = op.input.Summary()
          if op.status == constants.OP_STATUS_SUCCESS:
            # this is a job that was partially completed before master
            # daemon shutdown, so it can be expected that some opcodes
            # are already completed successfully (if any did error
            # out, then the whole job should have been aborted and not
            # resubmitted for processing)
            logging.info("Op %s/%s: opcode %s already processed, skipping",
                         idx + 1, count, op_summary)
            continue
          try:
            logging.info("Op %s/%s: Starting opcode %s", idx + 1, count,
                         op_summary)

            queue.acquire()
            try:
              if op.status == constants.OP_STATUS_CANCELED:
                raise CancelJob()
              assert op.status == constants.OP_STATUS_QUEUED
              op.status = constants.OP_STATUS_WAITLOCK
              op.result = None
              op.start_timestamp = TimeStampNow()
              if idx == 0: # first opcode
                job.start_timestamp = op.start_timestamp
              queue.UpdateJobUnlocked(job)

              input_opcode = op.input
            finally:
              queue.release()

            # Make sure not to hold queue lock while calling ExecOpCode
            result = proc.ExecOpCode(input_opcode,
                                     _OpExecCallbacks(queue, job, op))

            queue.acquire()
            try:
              op.status = constants.OP_STATUS_SUCCESS
              op.result = result
              op.end_timestamp = TimeStampNow()
              queue.UpdateJobUnlocked(job)
            finally:
              queue.release()

            logging.info("Op %s/%s: Successfully finished opcode %s",
                         idx + 1, count, op_summary)
          except CancelJob:
            # Will be handled further up
            raise
          except Exception, err:
            queue.acquire()
            try:
              try:
                op.status = constants.OP_STATUS_ERROR
                if isinstance(err, errors.GenericError):
                  op.result = errors.EncodeException(err)
                else:
                  op.result = str(err)
                op.end_timestamp = TimeStampNow()
                logging.info("Op %s/%s: Error in opcode %s: %s",
                             idx + 1, count, op_summary, err)
              finally:
                queue.UpdateJobUnlocked(job)
            finally:
              queue.release()
            raise

      except CancelJob:
        queue.acquire()
        try:
          queue.CancelJobUnlocked(job)
        finally:
          queue.release()
      except errors.GenericError, err:
        logging.exception("Ganeti exception")
      except:
        logging.exception("Unhandled exception")
    finally:
      queue.acquire()
      try:
        try:
          job.lock_status = None
          job.end_timestamp = TimeStampNow()
          queue.UpdateJobUnlocked(job)
        finally:
          job_id = job.id
          status = job.CalcStatus()
      finally:
        queue.release()

      logging.info("Finished job %s, status = %s", job_id, status)


class _JobQueueWorkerPool(workerpool.WorkerPool):
  """Simple class implementing a job-processing workerpool.

  """
  def __init__(self, queue):
    super(_JobQueueWorkerPool, self).__init__("JobQueue",
                                              JOBQUEUE_THREADS,
                                              _JobQueueWorker)
    self.queue = queue


def _RequireOpenQueue(fn):
  """Decorator for "public" functions.

  This function should be used for all 'public' functions. That is,
  functions usually called from other classes. Note that this should
  be applied only to methods (not plain functions), since it expects
  that the decorated function is called with a first argument that has
  a '_queue_filelock' argument.

  @warning: Use this decorator only after utils.LockedMethod!

  Example::
    @utils.LockedMethod
    @_RequireOpenQueue
    def Example(self):
      pass

  """
  def wrapper(self, *args, **kwargs):
    # pylint: disable-msg=W0212
    assert self._queue_filelock is not None, "Queue should be open"
    return fn(self, *args, **kwargs)
  return wrapper


class JobQueue(object):
  """Queue used to manage the jobs.

  @cvar _RE_JOB_FILE: regex matching the valid job file names

  """
  _RE_JOB_FILE = re.compile(r"^job-(%s)$" % constants.JOB_ID_TEMPLATE)

  def __init__(self, context):
    """Constructor for JobQueue.

    The constructor will initialize the job queue object and then
    start loading the current jobs from disk, either for starting them
    (if they were queue) or for aborting them (if they were already
    running).

    @type context: GanetiContext
    @param context: the context object for access to the configuration
        data and other ganeti objects

    """
    self.context = context
    self._memcache = weakref.WeakValueDictionary()
    self._my_hostname = utils.HostInfo().name

    # Locking
    self._lock = threading.Lock()
    self.acquire = self._lock.acquire
    self.release = self._lock.release

    # Initialize the queue, and acquire the filelock.
    # This ensures no other process is working on the job queue.
    self._queue_filelock = jstore.InitAndVerifyQueue(must_lock=True)

    # Read serial file
    self._last_serial = jstore.ReadSerial()
    assert self._last_serial is not None, ("Serial file was modified between"
                                           " check in jstore and here")

    # Get initial list of nodes
    self._nodes = dict((n.name, n.primary_ip)
                       for n in self.context.cfg.GetAllNodesInfo().values()
                       if n.master_candidate)

    # Remove master node
    self._nodes.pop(self._my_hostname, None)

    # TODO: Check consistency across nodes

    self._queue_size = 0
    self._UpdateQueueSizeUnlocked()
    self._drained = self._IsQueueMarkedDrain()

    # Setup worker pool
    self._wpool = _JobQueueWorkerPool(self)
    try:
      # We need to lock here because WorkerPool.AddTask() may start a job while
      # we're still doing our work.
      self.acquire()
      try:
        logging.info("Inspecting job queue")

        all_job_ids = self._GetJobIDsUnlocked()
        jobs_count = len(all_job_ids)
        lastinfo = time.time()
        for idx, job_id in enumerate(all_job_ids):
          # Give an update every 1000 jobs or 10 seconds
          if (idx % 1000 == 0 or time.time() >= (lastinfo + 10.0) or
              idx == (jobs_count - 1)):
            logging.info("Job queue inspection: %d/%d (%0.1f %%)",
                         idx, jobs_count - 1, 100.0 * (idx + 1) / jobs_count)
            lastinfo = time.time()

          job = self._LoadJobUnlocked(job_id)

          # a failure in loading the job can cause 'None' to be returned
          if job is None:
            continue

          status = job.CalcStatus()

          if status in (constants.JOB_STATUS_QUEUED, ):
            self._wpool.AddTask(job)

          elif status in (constants.JOB_STATUS_RUNNING,
                          constants.JOB_STATUS_WAITLOCK,
                          constants.JOB_STATUS_CANCELING):
            logging.warning("Unfinished job %s found: %s", job.id, job)
            try:
              job.MarkUnfinishedOps(constants.OP_STATUS_ERROR,
                                    "Unclean master daemon shutdown")
            finally:
              self.UpdateJobUnlocked(job)

        logging.info("Job queue inspection finished")
      finally:
        self.release()
    except:
      self._wpool.TerminateWorkers()
      raise

  @utils.LockedMethod
  @_RequireOpenQueue
  def AddNode(self, node):
    """Register a new node with the queue.

    @type node: L{objects.Node}
    @param node: the node object to be added

    """
    node_name = node.name
    assert node_name != self._my_hostname

    # Clean queue directory on added node
    result = rpc.RpcRunner.call_jobqueue_purge(node_name)
    msg = result.fail_msg
    if msg:
      logging.warning("Cannot cleanup queue directory on node %s: %s",
                      node_name, msg)

    if not node.master_candidate:
      # remove if existing, ignoring errors
      self._nodes.pop(node_name, None)
      # and skip the replication of the job ids
      return

    # Upload the whole queue excluding archived jobs
    files = [self._GetJobPath(job_id) for job_id in self._GetJobIDsUnlocked()]

    # Upload current serial file
    files.append(constants.JOB_QUEUE_SERIAL_FILE)

    for file_name in files:
      # Read file content
      content = utils.ReadFile(file_name)

      result = rpc.RpcRunner.call_jobqueue_update([node_name],
                                                  [node.primary_ip],
                                                  file_name, content)
      msg = result[node_name].fail_msg
      if msg:
        logging.error("Failed to upload file %s to node %s: %s",
                      file_name, node_name, msg)

    self._nodes[node_name] = node.primary_ip

  @utils.LockedMethod
  @_RequireOpenQueue
  def RemoveNode(self, node_name):
    """Callback called when removing nodes from the cluster.

    @type node_name: str
    @param node_name: the name of the node to remove

    """
    self._nodes.pop(node_name, None)

  @staticmethod
  def _CheckRpcResult(result, nodes, failmsg):
    """Verifies the status of an RPC call.

    Since we aim to keep consistency should this node (the current
    master) fail, we will log errors if our rpc fail, and especially
    log the case when more than half of the nodes fails.

    @param result: the data as returned from the rpc call
    @type nodes: list
    @param nodes: the list of nodes we made the call to
    @type failmsg: str
    @param failmsg: the identifier to be used for logging

    """
    failed = []
    success = []

    for node in nodes:
      msg = result[node].fail_msg
      if msg:
        failed.append(node)
        logging.error("RPC call %s (%s) failed on node %s: %s",
                      result[node].call, failmsg, node, msg)
      else:
        success.append(node)

    # +1 for the master node
    if (len(success) + 1) < len(failed):
      # TODO: Handle failing nodes
      logging.error("More than half of the nodes failed")

  def _GetNodeIp(self):
    """Helper for returning the node name/ip list.

    @rtype: (list, list)
    @return: a tuple of two lists, the first one with the node
        names and the second one with the node addresses

    """
    name_list = self._nodes.keys()
    addr_list = [self._nodes[name] for name in name_list]
    return name_list, addr_list

  def _UpdateJobQueueFile(self, file_name, data, replicate):
    """Writes a file locally and then replicates it to all nodes.

    This function will replace the contents of a file on the local
    node and then replicate it to all the other nodes we have.

    @type file_name: str
    @param file_name: the path of the file to be replicated
    @type data: str
    @param data: the new contents of the file
    @type replicate: boolean
    @param replicate: whether to spread the changes to the remote nodes

    """
    utils.WriteFile(file_name, data=data)

    if replicate:
      names, addrs = self._GetNodeIp()
      result = rpc.RpcRunner.call_jobqueue_update(names, addrs, file_name, data)
      self._CheckRpcResult(result, self._nodes, "Updating %s" % file_name)

  def _RenameFilesUnlocked(self, rename):
    """Renames a file locally and then replicate the change.

    This function will rename a file in the local queue directory
    and then replicate this rename to all the other nodes we have.

    @type rename: list of (old, new)
    @param rename: List containing tuples mapping old to new names

    """
    # Rename them locally
    for old, new in rename:
      utils.RenameFile(old, new, mkdir=True)

    # ... and on all nodes
    names, addrs = self._GetNodeIp()
    result = rpc.RpcRunner.call_jobqueue_rename(names, addrs, rename)
    self._CheckRpcResult(result, self._nodes, "Renaming files (%r)" % rename)

  @staticmethod
  def _FormatJobID(job_id):
    """Convert a job ID to string format.

    Currently this just does C{str(job_id)} after performing some
    checks, but if we want to change the job id format this will
    abstract this change.

    @type job_id: int or long
    @param job_id: the numeric job id
    @rtype: str
    @return: the formatted job id

    """
    if not isinstance(job_id, (int, long)):
      raise errors.ProgrammerError("Job ID '%s' not numeric" % job_id)
    if job_id < 0:
      raise errors.ProgrammerError("Job ID %s is negative" % job_id)

    return str(job_id)

  @classmethod
  def _GetArchiveDirectory(cls, job_id):
    """Returns the archive directory for a job.

    @type job_id: str
    @param job_id: Job identifier
    @rtype: str
    @return: Directory name

    """
    return str(int(job_id) / JOBS_PER_ARCHIVE_DIRECTORY)

  def _NewSerialsUnlocked(self, count):
    """Generates a new job identifier.

    Job identifiers are unique during the lifetime of a cluster.

    @type count: integer
    @param count: how many serials to return
    @rtype: str
    @return: a string representing the job identifier.

    """
    assert count > 0
    # New number
    serial = self._last_serial + count

    # Write to file
    self._UpdateJobQueueFile(constants.JOB_QUEUE_SERIAL_FILE,
                             "%s\n" % serial, True)

    result = [self._FormatJobID(v)
              for v in range(self._last_serial, serial + 1)]
    # Keep it only if we were able to write the file
    self._last_serial = serial

    return result

  @staticmethod
  def _GetJobPath(job_id):
    """Returns the job file for a given job id.

    @type job_id: str
    @param job_id: the job identifier
    @rtype: str
    @return: the path to the job file

    """
    return utils.PathJoin(constants.QUEUE_DIR, "job-%s" % job_id)

  @classmethod
  def _GetArchivedJobPath(cls, job_id):
    """Returns the archived job file for a give job id.

    @type job_id: str
    @param job_id: the job identifier
    @rtype: str
    @return: the path to the archived job file

    """
    return utils.PathJoin(constants.JOB_QUEUE_ARCHIVE_DIR,
                          cls._GetArchiveDirectory(job_id), "job-%s" % job_id)

  def _GetJobIDsUnlocked(self, sort=True):
    """Return all known job IDs.

    The method only looks at disk because it's a requirement that all
    jobs are present on disk (so in the _memcache we don't have any
    extra IDs).

    @type sort: boolean
    @param sort: perform sorting on the returned job ids
    @rtype: list
    @return: the list of job IDs

    """
    jlist = []
    for filename in utils.ListVisibleFiles(constants.QUEUE_DIR):
      m = self._RE_JOB_FILE.match(filename)
      if m:
        jlist.append(m.group(1))
    if sort:
      jlist = utils.NiceSort(jlist)
    return jlist

  def _LoadJobUnlocked(self, job_id):
    """Loads a job from the disk or memory.

    Given a job id, this will return the cached job object if
    existing, or try to load the job from the disk. If loading from
    disk, it will also add the job to the cache.

    @param job_id: the job id
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    job = self._memcache.get(job_id, None)
    if job:
      logging.debug("Found job %s in memcache", job_id)
      return job

    try:
      job = self._LoadJobFromDisk(job_id)
    except errors.JobFileCorrupted:
      old_path = self._GetJobPath(job_id)
      new_path = self._GetArchivedJobPath(job_id)
      if old_path == new_path:
        # job already archived (future case)
        logging.exception("Can't parse job %s", job_id)
      else:
        # non-archived case
        logging.exception("Can't parse job %s, will archive.", job_id)
        self._RenameFilesUnlocked([(old_path, new_path)])
      return None

    self._memcache[job_id] = job
    logging.debug("Added job %s to the cache", job_id)
    return job

  def _LoadJobFromDisk(self, job_id):
    """Load the given job file from disk.

    Given a job file, read, load and restore it in a _QueuedJob format.

    @type job_id: string
    @param job_id: job identifier
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    filepath = self._GetJobPath(job_id)
    logging.debug("Loading job from %s", filepath)
    try:
      raw_data = utils.ReadFile(filepath)
    except EnvironmentError, err:
      if err.errno in (errno.ENOENT, ):
        return None
      raise

    try:
      data = serializer.LoadJson(raw_data)
      job = _QueuedJob.Restore(self, data)
    except Exception, err: # pylint: disable-msg=W0703
      raise errors.JobFileCorrupted(err)

    return job

  def SafeLoadJobFromDisk(self, job_id):
    """Load the given job file from disk.

    Given a job file, read, load and restore it in a _QueuedJob format.
    In case of error reading the job, it gets returned as None, and the
    exception is logged.

    @type job_id: string
    @param job_id: job identifier
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    try:
      return self._LoadJobFromDisk(job_id)
    except (errors.JobFileCorrupted, EnvironmentError):
      logging.exception("Can't load/parse job %s", job_id)
      return None

  @staticmethod
  def _IsQueueMarkedDrain():
    """Check if the queue is marked from drain.

    This currently uses the queue drain file, which makes it a
    per-node flag. In the future this can be moved to the config file.

    @rtype: boolean
    @return: True of the job queue is marked for draining

    """
    return os.path.exists(constants.JOB_QUEUE_DRAIN_FILE)

  def _UpdateQueueSizeUnlocked(self):
    """Update the queue size.

    """
    self._queue_size = len(self._GetJobIDsUnlocked(sort=False))

  @utils.LockedMethod
  @_RequireOpenQueue
  def SetDrainFlag(self, drain_flag):
    """Sets the drain flag for the queue.

    @type drain_flag: boolean
    @param drain_flag: Whether to set or unset the drain flag

    """
    if drain_flag:
      utils.WriteFile(constants.JOB_QUEUE_DRAIN_FILE, data="", close=True)
    else:
      utils.RemoveFile(constants.JOB_QUEUE_DRAIN_FILE)

    self._drained = drain_flag

    return True

  @_RequireOpenQueue
  def _SubmitJobUnlocked(self, job_id, ops):
    """Create and store a new job.

    This enters the job into our job queue and also puts it on the new
    queue, in order for it to be picked up by the queue processors.

    @type job_id: job ID
    @param job_id: the job ID for the new job
    @type ops: list
    @param ops: The list of OpCodes that will become the new job.
    @rtype: L{_QueuedJob}
    @return: the job object to be queued
    @raise errors.JobQueueDrainError: if the job queue is marked for draining
    @raise errors.JobQueueFull: if the job queue has too many jobs in it

    """
    # Ok when sharing the big job queue lock, as the drain file is created when
    # the lock is exclusive.
    if self._drained:
      raise errors.JobQueueDrainError("Job queue is drained, refusing job")

    if self._queue_size >= constants.JOB_QUEUE_SIZE_HARD_LIMIT:
      raise errors.JobQueueFull()

    job = _QueuedJob(self, job_id, ops)

    # Write to disk
    self.UpdateJobUnlocked(job)

    self._queue_size += 1

    logging.debug("Adding new job %s to the cache", job_id)
    self._memcache[job_id] = job

    return job

  @utils.LockedMethod
  @_RequireOpenQueue
  def SubmitJob(self, ops):
    """Create and store a new job.

    @see: L{_SubmitJobUnlocked}

    """
    job_id = self._NewSerialsUnlocked(1)[0]
    self._wpool.AddTask(self._SubmitJobUnlocked(job_id, ops))
    return job_id

  @utils.LockedMethod
  @_RequireOpenQueue
  def SubmitManyJobs(self, jobs):
    """Create and store multiple jobs.

    @see: L{_SubmitJobUnlocked}

    """
    results = []
    tasks = []
    all_job_ids = self._NewSerialsUnlocked(len(jobs))
    for job_id, ops in zip(all_job_ids, jobs):
      try:
        tasks.append((self._SubmitJobUnlocked(job_id, ops), ))
        status = True
        data = job_id
      except errors.GenericError, err:
        data = str(err)
        status = False
      results.append((status, data))
    self._wpool.AddManyTasks(tasks)

    return results

  @_RequireOpenQueue
  def UpdateJobUnlocked(self, job, replicate=True):
    """Update a job's on disk storage.

    After a job has been modified, this function needs to be called in
    order to write the changes to disk and replicate them to the other
    nodes.

    @type job: L{_QueuedJob}
    @param job: the changed job
    @type replicate: boolean
    @param replicate: whether to replicate the change to remote nodes

    """
    filename = self._GetJobPath(job.id)
    data = serializer.DumpJson(job.Serialize(), indent=False)
    logging.debug("Writing job %s to %s", job.id, filename)
    self._UpdateJobQueueFile(filename, data, replicate)

    # Notify waiters about potential changes
    job.change.notifyAll()

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
    @rtype: tuple (job info, log entries)
    @return: a tuple of the job information as required via
        the fields parameter, and the log entries as a list

        if the job has not changed and the timeout has expired,
        we instead return a special value,
        L{constants.JOB_NOTCHANGED}, which should be interpreted
        as such by the clients

    """
    helper = _WaitForJobChangesHelper(job_id, fields, prev_job_info,
                                      prev_log_serial, self)
    try:
      return helper.WaitForChanges(timeout)
    finally:
      helper.Close()

  @utils.LockedMethod
  @_RequireOpenQueue
  def CancelJob(self, job_id):
    """Cancels a job.

    This will only succeed if the job has not started yet.

    @type job_id: string
    @param job_id: job ID of job to be cancelled.

    """
    logging.info("Cancelling job %s", job_id)

    job = self._LoadJobUnlocked(job_id)
    if not job:
      logging.debug("Job %s not found", job_id)
      return (False, "Job %s not found" % job_id)

    job_status = job.CalcStatus()

    if job_status not in (constants.JOB_STATUS_QUEUED,
                          constants.JOB_STATUS_WAITLOCK):
      logging.debug("Job %s is no longer waiting in the queue", job.id)
      return (False, "Job %s is no longer waiting in the queue" % job.id)

    if job_status == constants.JOB_STATUS_QUEUED:
      self.CancelJobUnlocked(job)
      return (True, "Job %s canceled" % job.id)

    elif job_status == constants.JOB_STATUS_WAITLOCK:
      # The worker will notice the new status and cancel the job
      try:
        job.MarkUnfinishedOps(constants.OP_STATUS_CANCELING, None)
      finally:
        self.UpdateJobUnlocked(job)
      return (True, "Job %s will be canceled" % job.id)

  @_RequireOpenQueue
  def CancelJobUnlocked(self, job):
    """Marks a job as canceled.

    """
    try:
      job.MarkUnfinishedOps(constants.OP_STATUS_CANCELED,
                            "Job canceled by request")
    finally:
      self.UpdateJobUnlocked(job)

  @_RequireOpenQueue
  def _ArchiveJobsUnlocked(self, jobs):
    """Archives jobs.

    @type jobs: list of L{_QueuedJob}
    @param jobs: Job objects
    @rtype: int
    @return: Number of archived jobs

    """
    archive_jobs = []
    rename_files = []
    for job in jobs:
      if job.CalcStatus() not in (constants.JOB_STATUS_CANCELED,
                                  constants.JOB_STATUS_SUCCESS,
                                  constants.JOB_STATUS_ERROR):
        logging.debug("Job %s is not yet done", job.id)
        continue

      archive_jobs.append(job)

      old = self._GetJobPath(job.id)
      new = self._GetArchivedJobPath(job.id)
      rename_files.append((old, new))

    # TODO: What if 1..n files fail to rename?
    self._RenameFilesUnlocked(rename_files)

    logging.debug("Successfully archived job(s) %s",
                  utils.CommaJoin(job.id for job in archive_jobs))

    # Since we haven't quite checked, above, if we succeeded or failed renaming
    # the files, we update the cached queue size from the filesystem. When we
    # get around to fix the TODO: above, we can use the number of actually
    # archived jobs to fix this.
    self._UpdateQueueSizeUnlocked()
    return len(archive_jobs)

  @utils.LockedMethod
  @_RequireOpenQueue
  def ArchiveJob(self, job_id):
    """Archives a job.

    This is just a wrapper over L{_ArchiveJobsUnlocked}.

    @type job_id: string
    @param job_id: Job ID of job to be archived.
    @rtype: bool
    @return: Whether job was archived

    """
    logging.info("Archiving job %s", job_id)

    job = self._LoadJobUnlocked(job_id)
    if not job:
      logging.debug("Job %s not found", job_id)
      return False

    return self._ArchiveJobsUnlocked([job]) == 1

  @utils.LockedMethod
  @_RequireOpenQueue
  def AutoArchiveJobs(self, age, timeout):
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
    end_time = now + timeout
    archived_count = 0
    last_touched = 0

    all_job_ids = self._GetJobIDsUnlocked()
    pending = []
    for idx, job_id in enumerate(all_job_ids):
      last_touched = idx + 1

      # Not optimal because jobs could be pending
      # TODO: Measure average duration for job archival and take number of
      # pending jobs into account.
      if time.time() > end_time:
        break

      # Returns None if the job failed to load
      job = self._LoadJobUnlocked(job_id)
      if job:
        if job.end_timestamp is None:
          if job.start_timestamp is None:
            job_age = job.received_timestamp
          else:
            job_age = job.start_timestamp
        else:
          job_age = job.end_timestamp

        if age == -1 or now - job_age[0] > age:
          pending.append(job)

          # Archive 10 jobs at a time
          if len(pending) >= 10:
            archived_count += self._ArchiveJobsUnlocked(pending)
            pending = []

    if pending:
      archived_count += self._ArchiveJobsUnlocked(pending)

    return (archived_count, len(all_job_ids) - last_touched)

  def QueryJobs(self, job_ids, fields):
    """Returns a list of jobs in queue.

    @type job_ids: list
    @param job_ids: sequence of job identifiers or None for all
    @type fields: list
    @param fields: names of fields to return
    @rtype: list
    @return: list one element per job, each element being list with
        the requested fields

    """
    jobs = []
    list_all = False
    if not job_ids:
      # Since files are added to/removed from the queue atomically, there's no
      # risk of getting the job ids in an inconsistent state.
      job_ids = self._GetJobIDsUnlocked()
      list_all = True

    for job_id in job_ids:
      job = self.SafeLoadJobFromDisk(job_id)
      if job is not None:
        jobs.append(job.GetInfo(fields))
      elif not list_all:
        jobs.append(None)

    return jobs

  @utils.LockedMethod
  @_RequireOpenQueue
  def Shutdown(self):
    """Stops the job queue.

    This shutdowns all the worker threads an closes the queue.

    """
    self._wpool.TerminateWorkers()

    self._queue_filelock.Close()
    self._queue_filelock = None
