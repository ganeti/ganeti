#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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

import logging
import errno
import time
import weakref
import threading
import itertools

try:
  # pylint: disable=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import constants
from ganeti import serializer
from ganeti import workerpool
from ganeti import locking
from ganeti import opcodes
from ganeti import errors
from ganeti import mcpu
from ganeti import utils
from ganeti import jstore
from ganeti import rpc
from ganeti import runtime
from ganeti import netutils
from ganeti import compat
from ganeti import ht


JOBQUEUE_THREADS = 25
JOBS_PER_ARCHIVE_DIRECTORY = 10000

# member lock names to be passed to @ssynchronized decorator
_LOCK = "_lock"
_QUEUE = "_queue"


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
  __slots__ = ["input", "status", "result", "log", "priority",
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

    # Get initial priority (it might change during the lifetime of this opcode)
    self.priority = getattr(op, "priority", constants.OP_PRIO_DEFAULT)

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
    obj.priority = state.get("priority", constants.OP_PRIO_DEFAULT)
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
      "priority": self.priority,
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
  @ivar writable: Whether the job is allowed to be modified

  """
  # pylint: disable=W0212
  __slots__ = ["queue", "id", "ops", "log_serial", "ops_iter", "cur_opctx",
               "received_timestamp", "start_timestamp", "end_timestamp",
               "__weakref__", "processor_lock", "writable"]

  def __init__(self, queue, job_id, ops, writable):
    """Constructor for the _QueuedJob.

    @type queue: L{JobQueue}
    @param queue: our parent queue
    @type job_id: job_id
    @param job_id: our job id
    @type ops: list
    @param ops: the list of opcodes we hold, which will be encapsulated
        in _QueuedOpCodes
    @type writable: bool
    @param writable: Whether job can be modified

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

    self._InitInMemory(self, writable)

  @staticmethod
  def _InitInMemory(obj, writable):
    """Initializes in-memory variables.

    """
    obj.writable = writable
    obj.ops_iter = None
    obj.cur_opctx = None

    # Read-only jobs are not processed and therefore don't need a lock
    if writable:
      obj.processor_lock = threading.Lock()
    else:
      obj.processor_lock = None

  def __repr__(self):
    status = ["%s.%s" % (self.__class__.__module__, self.__class__.__name__),
              "id=%s" % self.id,
              "ops=%s" % ",".join([op.input.Summary() for op in self.ops])]

    return "<%s at %#x>" % (" ".join(status), id(self))

  @classmethod
  def Restore(cls, queue, state, writable):
    """Restore a _QueuedJob from serialized state:

    @type queue: L{JobQueue}
    @param queue: to which queue the restored job belongs
    @type state: dict
    @param state: the serialized state
    @type writable: bool
    @param writable: Whether job can be modified
    @rtype: _JobQueue
    @return: the restored _JobQueue instance

    """
    obj = _QueuedJob.__new__(cls)
    obj.queue = queue
    obj.id = state["id"]
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

    cls._InitInMemory(obj, writable)

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
      elif op.status == constants.OP_STATUS_WAITING:
        status = constants.JOB_STATUS_WAITING
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

  def CalcPriority(self):
    """Gets the current priority for this job.

    Only unfinished opcodes are considered. When all are done, the default
    priority is used.

    @rtype: int

    """
    priorities = [op.priority for op in self.ops
                  if op.status not in constants.OPS_FINALIZED]

    if not priorities:
      # All opcodes are done, assume default priority
      return constants.OP_PRIO_DEFAULT

    return min(priorities)

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
      elif fname == "priority":
        row.append(self.CalcPriority())
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
      elif fname == "oppriority":
        row.append([op.priority for op in self.ops])
      elif fname == "received_ts":
        row.append(self.received_timestamp)
      elif fname == "start_ts":
        row.append(self.start_timestamp)
      elif fname == "end_ts":
        row.append(self.end_timestamp)
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

  def Finalize(self):
    """Marks the job as finalized.

    """
    self.end_timestamp = TimeStampNow()

  def Cancel(self):
    """Marks job as canceled/-ing if possible.

    @rtype: tuple; (bool, string)
    @return: Boolean describing whether job was successfully canceled or marked
      as canceling and a text message

    """
    status = self.CalcStatus()

    if status == constants.JOB_STATUS_QUEUED:
      self.MarkUnfinishedOps(constants.OP_STATUS_CANCELED,
                             "Job canceled by request")
      self.Finalize()
      return (True, "Job %s canceled" % self.id)

    elif status == constants.JOB_STATUS_WAITING:
      # The worker will notice the new status and cancel the job
      self.MarkUnfinishedOps(constants.OP_STATUS_CANCELING, None)
      return (True, "Job %s will be canceled" % self.id)

    else:
      logging.debug("Job %s is no longer waiting in the queue", self.id)
      return (False, "Job %s is no longer waiting in the queue" % self.id)


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

  def _CheckCancel(self):
    """Raises an exception to cancel the job if asked to.

    """
    # Cancel here if we were asked to
    if self._op.status == constants.OP_STATUS_CANCELING:
      logging.debug("Canceling opcode")
      raise CancelJob()

  @locking.ssynchronized(_QUEUE, shared=1)
  def NotifyStart(self):
    """Mark the opcode as running, not lock-waiting.

    This is called from the mcpu code as a notifier function, when the LU is
    finally about to start the Exec() method. Of course, to have end-user
    visible results, the opcode must be initially (before calling into
    Processor.ExecOpCode) set to OP_STATUS_WAITING.

    """
    assert self._op in self._job.ops
    assert self._op.status in (constants.OP_STATUS_WAITING,
                               constants.OP_STATUS_CANCELING)

    # Cancel here if we were asked to
    self._CheckCancel()

    logging.debug("Opcode is now running")

    self._op.status = constants.OP_STATUS_RUNNING
    self._op.exec_timestamp = TimeStampNow()

    # And finally replicate the job status
    self._queue.UpdateJobUnlocked(self._job)

  @locking.ssynchronized(_QUEUE, shared=1)
  def _AppendFeedback(self, timestamp, log_type, log_msg):
    """Internal feedback append function, with locks

    """
    self._job.log_serial += 1
    self._op.log.append((self._job.log_serial, timestamp, log_type, log_msg))
    self._queue.UpdateJobUnlocked(self._job, replicate=False)

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
    self._AppendFeedback(timestamp, log_type, log_msg)

  def CheckCancel(self):
    """Check whether job has been cancelled.

    """
    assert self._op.status in (constants.OP_STATUS_WAITING,
                               constants.OP_STATUS_CANCELING)

    # Cancel here if we were asked to
    self._CheckCancel()

  def SubmitManyJobs(self, jobs):
    """Submits jobs for processing.

    See L{JobQueue.SubmitManyJobs}.

    """
    # Locking is done in job queue
    return self._queue.SubmitManyJobs(jobs)


class _JobChangesChecker(object):
  def __init__(self, fields, prev_job_info, prev_log_serial):
    """Initializes this class.

    @type fields: list of strings
    @param fields: Fields requested by LUXI client
    @type prev_job_info: string
    @param prev_job_info: previous job info, as passed by the LUXI client
    @type prev_log_serial: string
    @param prev_log_serial: previous job serial, as passed by the LUXI client

    """
    self._fields = fields
    self._prev_job_info = prev_job_info
    self._prev_log_serial = prev_log_serial

  def __call__(self, job):
    """Checks whether job has changed.

    @type job: L{_QueuedJob}
    @param job: Job object

    """
    assert not job.writable, "Expected read-only job"

    status = job.CalcStatus()
    job_info = job.GetInfo(self._fields)
    log_entries = job.GetLogEntries(self._prev_log_serial)

    # Serializing and deserializing data can cause type changes (e.g. from
    # tuple to list) or precision loss. We're doing it here so that we get
    # the same modifications as the data received from the client. Without
    # this, the comparison afterwards might fail without the data being
    # significantly different.
    # TODO: we just deserialized from disk, investigate how to make sure that
    # the job info and log entries are compatible to avoid this further step.
    # TODO: Doing something like in testutils.py:UnifyValueType might be more
    # efficient, though floats will be tricky
    job_info = serializer.LoadJson(serializer.DumpJson(job_info))
    log_entries = serializer.LoadJson(serializer.DumpJson(log_entries))

    # Don't even try to wait if the job is no longer running, there will be
    # no changes.
    if (status not in (constants.JOB_STATUS_QUEUED,
                       constants.JOB_STATUS_RUNNING,
                       constants.JOB_STATUS_WAITING) or
        job_info != self._prev_job_info or
        (log_entries and self._prev_log_serial != log_entries[0][0])):
      logging.debug("Job %s changed", job.id)
      return (job_info, log_entries)

    return None


class _JobFileChangesWaiter(object):
  def __init__(self, filename):
    """Initializes this class.

    @type filename: string
    @param filename: Path to job file
    @raises errors.InotifyError: if the notifier cannot be setup

    """
    self._wm = pyinotify.WatchManager()
    self._inotify_handler = \
      asyncnotifier.SingleFileEventHandler(self._wm, self._OnInotify, filename)
    self._notifier = \
      pyinotify.Notifier(self._wm, default_proc_fun=self._inotify_handler)
    try:
      self._inotify_handler.enable()
    except Exception:
      # pyinotify doesn't close file descriptors automatically
      self._notifier.stop()
      raise

  def _OnInotify(self, notifier_enabled):
    """Callback for inotify.

    """
    if not notifier_enabled:
      self._inotify_handler.enable()

  def Wait(self, timeout):
    """Waits for the job file to change.

    @type timeout: float
    @param timeout: Timeout in seconds
    @return: Whether there have been events

    """
    assert timeout >= 0
    have_events = self._notifier.check_events(timeout * 1000)
    if have_events:
      self._notifier.read_events()
    self._notifier.process_events()
    return have_events

  def Close(self):
    """Closes underlying notifier and its file descriptor.

    """
    self._notifier.stop()


class _JobChangesWaiter(object):
  def __init__(self, filename):
    """Initializes this class.

    @type filename: string
    @param filename: Path to job file

    """
    self._filewaiter = None
    self._filename = filename

  def Wait(self, timeout):
    """Waits for a job to change.

    @type timeout: float
    @param timeout: Timeout in seconds
    @return: Whether there have been events

    """
    if self._filewaiter:
      return self._filewaiter.Wait(timeout)

    # Lazy setup: Avoid inotify setup cost when job file has already changed.
    # If this point is reached, return immediately and let caller check the job
    # file again in case there were changes since the last check. This avoids a
    # race condition.
    self._filewaiter = _JobFileChangesWaiter(self._filename)

    return True

  def Close(self):
    """Closes underlying waiter.

    """
    if self._filewaiter:
      self._filewaiter.Close()


class _WaitForJobChangesHelper(object):
  """Helper class using inotify to wait for changes in a job file.

  This class takes a previous job status and serial, and alerts the client when
  the current job status has changed.

  """
  @staticmethod
  def _CheckForChanges(counter, job_load_fn, check_fn):
    if counter.next() > 0:
      # If this isn't the first check the job is given some more time to change
      # again. This gives better performance for jobs generating many
      # changes/messages.
      time.sleep(0.1)

    job = job_load_fn()
    if not job:
      raise errors.JobLost()

    result = check_fn(job)
    if result is None:
      raise utils.RetryAgain()

    return result

  def __call__(self, filename, job_load_fn,
               fields, prev_job_info, prev_log_serial, timeout):
    """Waits for changes on a job.

    @type filename: string
    @param filename: File on which to wait for changes
    @type job_load_fn: callable
    @param job_load_fn: Function to load job
    @type fields: list of strings
    @param fields: Which fields to check for changes
    @type prev_job_info: list or None
    @param prev_job_info: Last job information returned
    @type prev_log_serial: int
    @param prev_log_serial: Last job message serial number
    @type timeout: float
    @param timeout: maximum time to wait in seconds

    """
    counter = itertools.count()
    try:
      check_fn = _JobChangesChecker(fields, prev_job_info, prev_log_serial)
      waiter = _JobChangesWaiter(filename)
      try:
        return utils.Retry(compat.partial(self._CheckForChanges,
                                          counter, job_load_fn, check_fn),
                           utils.RETRY_REMAINING_TIME, timeout,
                           wait_fn=waiter.Wait)
      finally:
        waiter.Close()
    except (errors.InotifyError, errors.JobLost):
      return None
    except utils.RetryTimeout:
      return constants.JOB_NOTCHANGED


def _EncodeOpError(err):
  """Encodes an error which occurred while processing an opcode.

  """
  if isinstance(err, errors.GenericError):
    to_encode = err
  else:
    to_encode = errors.OpExecError(str(err))

  return errors.EncodeException(to_encode)


class _TimeoutStrategyWrapper:
  def __init__(self, fn):
    """Initializes this class.

    """
    self._fn = fn
    self._next = None

  def _Advance(self):
    """Gets the next timeout if necessary.

    """
    if self._next is None:
      self._next = self._fn()

  def Peek(self):
    """Returns the next timeout.

    """
    self._Advance()
    return self._next

  def Next(self):
    """Returns the current timeout and advances the internal state.

    """
    self._Advance()
    result = self._next
    self._next = None
    return result


class _OpExecContext:
  def __init__(self, op, index, log_prefix, timeout_strategy_factory):
    """Initializes this class.

    """
    self.op = op
    self.index = index
    self.log_prefix = log_prefix
    self.summary = op.input.Summary()

    # Create local copy to modify
    if getattr(op.input, opcodes.DEPEND_ATTR, None):
      self.jobdeps = op.input.depends[:]
    else:
      self.jobdeps = None

    self._timeout_strategy_factory = timeout_strategy_factory
    self._ResetTimeoutStrategy()

  def _ResetTimeoutStrategy(self):
    """Creates a new timeout strategy.

    """
    self._timeout_strategy = \
      _TimeoutStrategyWrapper(self._timeout_strategy_factory().NextAttempt)

  def CheckPriorityIncrease(self):
    """Checks whether priority can and should be increased.

    Called when locks couldn't be acquired.

    """
    op = self.op

    # Exhausted all retries and next round should not use blocking acquire
    # for locks?
    if (self._timeout_strategy.Peek() is None and
        op.priority > constants.OP_PRIO_HIGHEST):
      logging.debug("Increasing priority")
      op.priority -= 1
      self._ResetTimeoutStrategy()
      return True

    return False

  def GetNextLockTimeout(self):
    """Returns the next lock acquire timeout.

    """
    return self._timeout_strategy.Next()


class _JobProcessor(object):
  (DEFER,
   WAITDEP,
   FINISHED) = range(1, 4)

  def __init__(self, queue, opexec_fn, job,
               _timeout_strategy_factory=mcpu.LockAttemptTimeoutStrategy):
    """Initializes this class.

    """
    self.queue = queue
    self.opexec_fn = opexec_fn
    self.job = job
    self._timeout_strategy_factory = _timeout_strategy_factory

  @staticmethod
  def _FindNextOpcode(job, timeout_strategy_factory):
    """Locates the next opcode to run.

    @type job: L{_QueuedJob}
    @param job: Job object
    @param timeout_strategy_factory: Callable to create new timeout strategy

    """
    # Create some sort of a cache to speed up locating next opcode for future
    # lookups
    # TODO: Consider splitting _QueuedJob.ops into two separate lists, one for
    # pending and one for processed ops.
    if job.ops_iter is None:
      job.ops_iter = enumerate(job.ops)

    # Find next opcode to run
    while True:
      try:
        (idx, op) = job.ops_iter.next()
      except StopIteration:
        raise errors.ProgrammerError("Called for a finished job")

      if op.status == constants.OP_STATUS_RUNNING:
        # Found an opcode already marked as running
        raise errors.ProgrammerError("Called for job marked as running")

      opctx = _OpExecContext(op, idx, "Op %s/%s" % (idx + 1, len(job.ops)),
                             timeout_strategy_factory)

      if op.status not in constants.OPS_FINALIZED:
        return opctx

      # This is a job that was partially completed before master daemon
      # shutdown, so it can be expected that some opcodes are already
      # completed successfully (if any did error out, then the whole job
      # should have been aborted and not resubmitted for processing).
      logging.info("%s: opcode %s already processed, skipping",
                   opctx.log_prefix, opctx.summary)

  @staticmethod
  def _MarkWaitlock(job, op):
    """Marks an opcode as waiting for locks.

    The job's start timestamp is also set if necessary.

    @type job: L{_QueuedJob}
    @param job: Job object
    @type op: L{_QueuedOpCode}
    @param op: Opcode object

    """
    assert op in job.ops
    assert op.status in (constants.OP_STATUS_QUEUED,
                         constants.OP_STATUS_WAITING)

    update = False

    op.result = None

    if op.status == constants.OP_STATUS_QUEUED:
      op.status = constants.OP_STATUS_WAITING
      update = True

    if op.start_timestamp is None:
      op.start_timestamp = TimeStampNow()
      update = True

    if job.start_timestamp is None:
      job.start_timestamp = op.start_timestamp
      update = True

    assert op.status == constants.OP_STATUS_WAITING

    return update

  @staticmethod
  def _CheckDependencies(queue, job, opctx):
    """Checks if an opcode has dependencies and if so, processes them.

    @type queue: L{JobQueue}
    @param queue: Queue object
    @type job: L{_QueuedJob}
    @param job: Job object
    @type opctx: L{_OpExecContext}
    @param opctx: Opcode execution context
    @rtype: bool
    @return: Whether opcode will be re-scheduled by dependency tracker

    """
    op = opctx.op

    result = False

    while opctx.jobdeps:
      (dep_job_id, dep_status) = opctx.jobdeps[0]

      (depresult, depmsg) = queue.depmgr.CheckAndRegister(job, dep_job_id,
                                                          dep_status)
      assert ht.TNonEmptyString(depmsg), "No dependency message"

      logging.info("%s: %s", opctx.log_prefix, depmsg)

      if depresult == _JobDependencyManager.CONTINUE:
        # Remove dependency and continue
        opctx.jobdeps.pop(0)

      elif depresult == _JobDependencyManager.WAIT:
        # Need to wait for notification, dependency tracker will re-add job
        # to workerpool
        result = True
        break

      elif depresult == _JobDependencyManager.CANCEL:
        # Job was cancelled, cancel this job as well
        job.Cancel()
        assert op.status == constants.OP_STATUS_CANCELING
        break

      elif depresult in (_JobDependencyManager.WRONGSTATUS,
                         _JobDependencyManager.ERROR):
        # Job failed or there was an error, this job must fail
        op.status = constants.OP_STATUS_ERROR
        op.result = _EncodeOpError(errors.OpExecError(depmsg))
        break

      else:
        raise errors.ProgrammerError("Unknown dependency result '%s'" %
                                     depresult)

    return result

  def _ExecOpCodeUnlocked(self, opctx):
    """Processes one opcode and returns the result.

    """
    op = opctx.op

    assert op.status == constants.OP_STATUS_WAITING

    timeout = opctx.GetNextLockTimeout()

    try:
      # Make sure not to hold queue lock while calling ExecOpCode
      result = self.opexec_fn(op.input,
                              _OpExecCallbacks(self.queue, self.job, op),
                              timeout=timeout, priority=op.priority)
    except mcpu.LockAcquireTimeout:
      assert timeout is not None, "Received timeout for blocking acquire"
      logging.debug("Couldn't acquire locks in %0.6fs", timeout)

      assert op.status in (constants.OP_STATUS_WAITING,
                           constants.OP_STATUS_CANCELING)

      # Was job cancelled while we were waiting for the lock?
      if op.status == constants.OP_STATUS_CANCELING:
        return (constants.OP_STATUS_CANCELING, None)

      # Stay in waitlock while trying to re-acquire lock
      return (constants.OP_STATUS_WAITING, None)
    except CancelJob:
      logging.exception("%s: Canceling job", opctx.log_prefix)
      assert op.status == constants.OP_STATUS_CANCELING
      return (constants.OP_STATUS_CANCELING, None)
    except Exception, err: # pylint: disable=W0703
      logging.exception("%s: Caught exception in %s",
                        opctx.log_prefix, opctx.summary)
      return (constants.OP_STATUS_ERROR, _EncodeOpError(err))
    else:
      logging.debug("%s: %s successful",
                    opctx.log_prefix, opctx.summary)
      return (constants.OP_STATUS_SUCCESS, result)

  def __call__(self, _nextop_fn=None):
    """Continues execution of a job.

    @param _nextop_fn: Callback function for tests
    @return: C{FINISHED} if job is fully processed, C{DEFER} if the job should
      be deferred and C{WAITDEP} if the dependency manager
      (L{_JobDependencyManager}) will re-schedule the job when appropriate

    """
    queue = self.queue
    job = self.job

    logging.debug("Processing job %s", job.id)

    queue.acquire(shared=1)
    try:
      opcount = len(job.ops)

      assert job.writable, "Expected writable job"

      # Don't do anything for finalized jobs
      if job.CalcStatus() in constants.JOBS_FINALIZED:
        return self.FINISHED

      # Is a previous opcode still pending?
      if job.cur_opctx:
        opctx = job.cur_opctx
        job.cur_opctx = None
      else:
        if __debug__ and _nextop_fn:
          _nextop_fn()
        opctx = self._FindNextOpcode(job, self._timeout_strategy_factory)

      op = opctx.op

      # Consistency check
      assert compat.all(i.status in (constants.OP_STATUS_QUEUED,
                                     constants.OP_STATUS_CANCELING)
                        for i in job.ops[opctx.index + 1:])

      assert op.status in (constants.OP_STATUS_QUEUED,
                           constants.OP_STATUS_WAITING,
                           constants.OP_STATUS_CANCELING)

      assert (op.priority <= constants.OP_PRIO_LOWEST and
              op.priority >= constants.OP_PRIO_HIGHEST)

      waitjob = None

      if op.status != constants.OP_STATUS_CANCELING:
        assert op.status in (constants.OP_STATUS_QUEUED,
                             constants.OP_STATUS_WAITING)

        # Prepare to start opcode
        if self._MarkWaitlock(job, op):
          # Write to disk
          queue.UpdateJobUnlocked(job)

        assert op.status == constants.OP_STATUS_WAITING
        assert job.CalcStatus() == constants.JOB_STATUS_WAITING
        assert job.start_timestamp and op.start_timestamp
        assert waitjob is None

        # Check if waiting for a job is necessary
        waitjob = self._CheckDependencies(queue, job, opctx)

        assert op.status in (constants.OP_STATUS_WAITING,
                             constants.OP_STATUS_CANCELING,
                             constants.OP_STATUS_ERROR)

        if not (waitjob or op.status in (constants.OP_STATUS_CANCELING,
                                         constants.OP_STATUS_ERROR)):
          logging.info("%s: opcode %s waiting for locks",
                       opctx.log_prefix, opctx.summary)

          assert not opctx.jobdeps, "Not all dependencies were removed"

          queue.release()
          try:
            (op_status, op_result) = self._ExecOpCodeUnlocked(opctx)
          finally:
            queue.acquire(shared=1)

          op.status = op_status
          op.result = op_result

          assert not waitjob

        if op.status == constants.OP_STATUS_WAITING:
          # Couldn't get locks in time
          assert not op.end_timestamp
        else:
          # Finalize opcode
          op.end_timestamp = TimeStampNow()

          if op.status == constants.OP_STATUS_CANCELING:
            assert not compat.any(i.status != constants.OP_STATUS_CANCELING
                                  for i in job.ops[opctx.index:])
          else:
            assert op.status in constants.OPS_FINALIZED

      if op.status == constants.OP_STATUS_WAITING or waitjob:
        finalize = False

        if not waitjob and opctx.CheckPriorityIncrease():
          # Priority was changed, need to update on-disk file
          queue.UpdateJobUnlocked(job)

        # Keep around for another round
        job.cur_opctx = opctx

        assert (op.priority <= constants.OP_PRIO_LOWEST and
                op.priority >= constants.OP_PRIO_HIGHEST)

        # In no case must the status be finalized here
        assert job.CalcStatus() == constants.JOB_STATUS_WAITING

      else:
        # Ensure all opcodes so far have been successful
        assert (opctx.index == 0 or
                compat.all(i.status == constants.OP_STATUS_SUCCESS
                           for i in job.ops[:opctx.index]))

        # Reset context
        job.cur_opctx = None

        if op.status == constants.OP_STATUS_SUCCESS:
          finalize = False

        elif op.status == constants.OP_STATUS_ERROR:
          # Ensure failed opcode has an exception as its result
          assert errors.GetEncodedError(job.ops[opctx.index].result)

          to_encode = errors.OpExecError("Preceding opcode failed")
          job.MarkUnfinishedOps(constants.OP_STATUS_ERROR,
                                _EncodeOpError(to_encode))
          finalize = True

          # Consistency check
          assert compat.all(i.status == constants.OP_STATUS_ERROR and
                            errors.GetEncodedError(i.result)
                            for i in job.ops[opctx.index:])

        elif op.status == constants.OP_STATUS_CANCELING:
          job.MarkUnfinishedOps(constants.OP_STATUS_CANCELED,
                                "Job canceled by request")
          finalize = True

        else:
          raise errors.ProgrammerError("Unknown status '%s'" % op.status)

        if opctx.index == (opcount - 1):
          # Finalize on last opcode
          finalize = True

        if finalize:
          # All opcodes have been run, finalize job
          job.Finalize()

        # Write to disk. If the job status is final, this is the final write
        # allowed. Once the file has been written, it can be archived anytime.
        queue.UpdateJobUnlocked(job)

        assert not waitjob

        if finalize:
          logging.info("Finished job %s, status = %s", job.id, job.CalcStatus())
          return self.FINISHED

      assert not waitjob or queue.depmgr.JobWaiting(job)

      if waitjob:
        return self.WAITDEP
      else:
        return self.DEFER
    finally:
      assert job.writable, "Job became read-only while being processed"
      queue.release()


class _JobQueueWorker(workerpool.BaseWorker):
  """The actual job workers.

  """
  def RunTask(self, job): # pylint: disable=W0221
    """Job executor.

    @type job: L{_QueuedJob}
    @param job: the job to be processed

    """
    assert job.writable, "Expected writable job"

    # Ensure only one worker is active on a single job. If a job registers for
    # a dependency job, and the other job notifies before the first worker is
    # done, the job can end up in the tasklist more than once.
    job.processor_lock.acquire()
    try:
      return self._RunTaskInner(job)
    finally:
      job.processor_lock.release()

  def _RunTaskInner(self, job):
    """Executes a job.

    Must be called with per-job lock acquired.

    """
    queue = job.queue
    assert queue == self.pool.queue

    setname_fn = lambda op: self.SetTaskName(self._GetWorkerName(job, op))
    setname_fn(None)

    proc = mcpu.Processor(queue.context, job.id)

    # Create wrapper for setting thread name
    wrap_execop_fn = compat.partial(self._WrapExecOpCode, setname_fn,
                                    proc.ExecOpCode)

    result = _JobProcessor(queue, wrap_execop_fn, job)()

    if result == _JobProcessor.FINISHED:
      # Notify waiting jobs
      queue.depmgr.NotifyWaiters(job.id)

    elif result == _JobProcessor.DEFER:
      # Schedule again
      raise workerpool.DeferTask(priority=job.CalcPriority())

    elif result == _JobProcessor.WAITDEP:
      # No-op, dependency manager will re-schedule
      pass

    else:
      raise errors.ProgrammerError("Job processor returned unknown status %s" %
                                   (result, ))

  @staticmethod
  def _WrapExecOpCode(setname_fn, execop_fn, op, *args, **kwargs):
    """Updates the worker thread name to include a short summary of the opcode.

    @param setname_fn: Callable setting worker thread name
    @param execop_fn: Callable for executing opcode (usually
                      L{mcpu.Processor.ExecOpCode})

    """
    setname_fn(op)
    try:
      return execop_fn(op, *args, **kwargs)
    finally:
      setname_fn(None)

  @staticmethod
  def _GetWorkerName(job, op):
    """Sets the worker thread name.

    @type job: L{_QueuedJob}
    @type op: L{opcodes.OpCode}

    """
    parts = ["Job%s" % job.id]

    if op:
      parts.append(op.TinySummary())

    return "/".join(parts)


class _JobQueueWorkerPool(workerpool.WorkerPool):
  """Simple class implementing a job-processing workerpool.

  """
  def __init__(self, queue):
    super(_JobQueueWorkerPool, self).__init__("Jq",
                                              JOBQUEUE_THREADS,
                                              _JobQueueWorker)
    self.queue = queue


class _JobDependencyManager:
  """Keeps track of job dependencies.

  """
  (WAIT,
   ERROR,
   CANCEL,
   CONTINUE,
   WRONGSTATUS) = range(1, 6)

  def __init__(self, getstatus_fn, enqueue_fn):
    """Initializes this class.

    """
    self._getstatus_fn = getstatus_fn
    self._enqueue_fn = enqueue_fn

    self._waiters = {}
    self._lock = locking.SharedLock("JobDepMgr")

  @locking.ssynchronized(_LOCK, shared=1)
  def GetLockInfo(self, requested): # pylint: disable=W0613
    """Retrieves information about waiting jobs.

    @type requested: set
    @param requested: Requested information, see C{query.LQ_*}

    """
    # No need to sort here, that's being done by the lock manager and query
    # library. There are no priorities for notifying jobs, hence all show up as
    # one item under "pending".
    return [("job/%s" % job_id, None, None,
             [("job", [job.id for job in waiters])])
            for job_id, waiters in self._waiters.items()
            if waiters]

  @locking.ssynchronized(_LOCK, shared=1)
  def JobWaiting(self, job):
    """Checks if a job is waiting.

    """
    return compat.any(job in jobs
                      for jobs in self._waiters.values())

  @locking.ssynchronized(_LOCK)
  def CheckAndRegister(self, job, dep_job_id, dep_status):
    """Checks if a dependency job has the requested status.

    If the other job is not yet in a finalized status, the calling job will be
    notified (re-added to the workerpool) at a later point.

    @type job: L{_QueuedJob}
    @param job: Job object
    @type dep_job_id: string
    @param dep_job_id: ID of dependency job
    @type dep_status: list
    @param dep_status: Required status

    """
    assert ht.TString(job.id)
    assert ht.TString(dep_job_id)
    assert ht.TListOf(ht.TElemOf(constants.JOBS_FINALIZED))(dep_status)

    if job.id == dep_job_id:
      return (self.ERROR, "Job can't depend on itself")

    # Get status of dependency job
    try:
      status = self._getstatus_fn(dep_job_id)
    except errors.JobLost, err:
      return (self.ERROR, "Dependency error: %s" % err)

    assert status in constants.JOB_STATUS_ALL

    job_id_waiters = self._waiters.setdefault(dep_job_id, set())

    if status not in constants.JOBS_FINALIZED:
      # Register for notification and wait for job to finish
      job_id_waiters.add(job)
      return (self.WAIT,
              "Need to wait for job %s, wanted status '%s'" %
              (dep_job_id, dep_status))

    # Remove from waiters list
    if job in job_id_waiters:
      job_id_waiters.remove(job)

    if (status == constants.JOB_STATUS_CANCELED and
        constants.JOB_STATUS_CANCELED not in dep_status):
      return (self.CANCEL, "Dependency job %s was cancelled" % dep_job_id)

    elif not dep_status or status in dep_status:
      return (self.CONTINUE,
              "Dependency job %s finished with status '%s'" %
              (dep_job_id, status))

    else:
      return (self.WRONGSTATUS,
              "Dependency job %s finished with status '%s',"
              " not one of '%s' as required" %
              (dep_job_id, status, utils.CommaJoin(dep_status)))

  @locking.ssynchronized(_LOCK)
  def NotifyWaiters(self, job_id):
    """Notifies all jobs waiting for a certain job ID.

    @type job_id: string
    @param job_id: Job ID

    """
    assert ht.TString(job_id)

    jobs = self._waiters.pop(job_id, None)
    if jobs:
      # Re-add jobs to workerpool
      logging.debug("Re-adding %s jobs which were waiting for job %s",
                    len(jobs), job_id)
      self._enqueue_fn(jobs)

    # Remove all jobs without actual waiters
    for job_id in [job_id for (job_id, waiters) in self._waiters.items()
                   if not waiters]:
      del self._waiters[job_id]


def _RequireOpenQueue(fn):
  """Decorator for "public" functions.

  This function should be used for all 'public' functions. That is,
  functions usually called from other classes. Note that this should
  be applied only to methods (not plain functions), since it expects
  that the decorated function is called with a first argument that has
  a '_queue_filelock' argument.

  @warning: Use this decorator only after locking.ssynchronized

  Example::
    @locking.ssynchronized(_LOCK)
    @_RequireOpenQueue
    def Example(self):
      pass

  """
  def wrapper(self, *args, **kwargs):
    # pylint: disable=W0212
    assert self._queue_filelock is not None, "Queue should be open"
    return fn(self, *args, **kwargs)
  return wrapper


class JobQueue(object):
  """Queue used to manage the jobs.

  """
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
    self._my_hostname = netutils.Hostname.GetSysName()

    # The Big JobQueue lock. If a code block or method acquires it in shared
    # mode safe it must guarantee concurrency with all the code acquiring it in
    # shared mode, including itself. In order not to acquire it at all
    # concurrency must be guaranteed with all code acquiring it in shared mode
    # and all code acquiring it exclusively.
    self._lock = locking.SharedLock("JobQueue")

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
    self._drained = jstore.CheckDrainFlag()

    # Job dependencies
    self.depmgr = _JobDependencyManager(self._GetJobStatusForDependencies,
                                        self._EnqueueJobs)
    self.context.glm.AddToLockMonitor(self.depmgr)

    # Setup worker pool
    self._wpool = _JobQueueWorkerPool(self)
    try:
      self._InspectQueue()
    except:
      self._wpool.TerminateWorkers()
      raise

  @locking.ssynchronized(_LOCK)
  @_RequireOpenQueue
  def _InspectQueue(self):
    """Loads the whole job queue and resumes unfinished jobs.

    This function needs the lock here because WorkerPool.AddTask() may start a
    job while we're still doing our work.

    """
    logging.info("Inspecting job queue")

    restartjobs = []

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

      if status == constants.JOB_STATUS_QUEUED:
        restartjobs.append(job)

      elif status in (constants.JOB_STATUS_RUNNING,
                      constants.JOB_STATUS_WAITING,
                      constants.JOB_STATUS_CANCELING):
        logging.warning("Unfinished job %s found: %s", job.id, job)

        if status == constants.JOB_STATUS_WAITING:
          # Restart job
          job.MarkUnfinishedOps(constants.OP_STATUS_QUEUED, None)
          restartjobs.append(job)
        else:
          job.MarkUnfinishedOps(constants.OP_STATUS_ERROR,
                                "Unclean master daemon shutdown")
          job.Finalize()

        self.UpdateJobUnlocked(job)

    if restartjobs:
      logging.info("Restarting %s jobs", len(restartjobs))
      self._EnqueueJobsUnlocked(restartjobs)

    logging.info("Job queue inspection finished")

  @locking.ssynchronized(_LOCK)
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

  @locking.ssynchronized(_LOCK)
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
    # TODO: Change to "tuple(map(list, zip(*self._nodes.items())))"?
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
    getents = runtime.GetEnts()
    utils.WriteFile(file_name, data=data, uid=getents.masterd_uid,
                    gid=getents.masterd_gid)

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
              for v in range(self._last_serial + 1, serial + 1)]

    # Keep it only if we were able to write the file
    self._last_serial = serial

    assert len(result) == count

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

  @staticmethod
  def _GetJobIDsUnlocked(sort=True):
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
      m = constants.JOB_FILE_RE.match(filename)
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
      assert job.writable, "Found read-only job in memcache"
      return job

    try:
      job = self._LoadJobFromDisk(job_id, False)
      if job is None:
        return job
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

    assert job.writable, "Job just loaded is not writable"

    self._memcache[job_id] = job
    logging.debug("Added job %s to the cache", job_id)
    return job

  def _LoadJobFromDisk(self, job_id, try_archived, writable=None):
    """Load the given job file from disk.

    Given a job file, read, load and restore it in a _QueuedJob format.

    @type job_id: string
    @param job_id: job identifier
    @type try_archived: bool
    @param try_archived: Whether to try loading an archived job
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    path_functions = [(self._GetJobPath, True)]

    if try_archived:
      path_functions.append((self._GetArchivedJobPath, False))

    raw_data = None
    writable_default = None

    for (fn, writable_default) in path_functions:
      filepath = fn(job_id)
      logging.debug("Loading job from %s", filepath)
      try:
        raw_data = utils.ReadFile(filepath)
      except EnvironmentError, err:
        if err.errno != errno.ENOENT:
          raise
      else:
        break

    if not raw_data:
      return None

    if writable is None:
      writable = writable_default

    try:
      data = serializer.LoadJson(raw_data)
      job = _QueuedJob.Restore(self, data, writable)
    except Exception, err: # pylint: disable=W0703
      raise errors.JobFileCorrupted(err)

    return job

  def SafeLoadJobFromDisk(self, job_id, try_archived, writable=None):
    """Load the given job file from disk.

    Given a job file, read, load and restore it in a _QueuedJob format.
    In case of error reading the job, it gets returned as None, and the
    exception is logged.

    @type job_id: string
    @param job_id: job identifier
    @type try_archived: bool
    @param try_archived: Whether to try loading an archived job
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    try:
      return self._LoadJobFromDisk(job_id, try_archived, writable=writable)
    except (errors.JobFileCorrupted, EnvironmentError):
      logging.exception("Can't load/parse job %s", job_id)
      return None

  def _UpdateQueueSizeUnlocked(self):
    """Update the queue size.

    """
    self._queue_size = len(self._GetJobIDsUnlocked(sort=False))

  @locking.ssynchronized(_LOCK)
  @_RequireOpenQueue
  def SetDrainFlag(self, drain_flag):
    """Sets the drain flag for the queue.

    @type drain_flag: boolean
    @param drain_flag: Whether to set or unset the drain flag

    """
    jstore.SetDrainFlag(drain_flag)

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
    @raise errors.GenericError: If an opcode is not valid

    """
    # Ok when sharing the big job queue lock, as the drain file is created when
    # the lock is exclusive.
    if self._drained:
      raise errors.JobQueueDrainError("Job queue is drained, refusing job")

    if self._queue_size >= constants.JOB_QUEUE_SIZE_HARD_LIMIT:
      raise errors.JobQueueFull()

    job = _QueuedJob(self, job_id, ops, True)

    # Check priority
    for idx, op in enumerate(job.ops):
      if op.priority not in constants.OP_PRIO_SUBMIT_VALID:
        allowed = utils.CommaJoin(constants.OP_PRIO_SUBMIT_VALID)
        raise errors.GenericError("Opcode %s has invalid priority %s, allowed"
                                  " are %s" % (idx, op.priority, allowed))

      dependencies = getattr(op.input, opcodes.DEPEND_ATTR, None)
      if not opcodes.TNoRelativeJobDependencies(dependencies):
        raise errors.GenericError("Opcode %s has invalid dependencies, must"
                                  " match %s: %s" %
                                  (idx, opcodes.TNoRelativeJobDependencies,
                                   dependencies))

    # Write to disk
    self.UpdateJobUnlocked(job)

    self._queue_size += 1

    logging.debug("Adding new job %s to the cache", job_id)
    self._memcache[job_id] = job

    return job

  @locking.ssynchronized(_LOCK)
  @_RequireOpenQueue
  def SubmitJob(self, ops):
    """Create and store a new job.

    @see: L{_SubmitJobUnlocked}

    """
    (job_id, ) = self._NewSerialsUnlocked(1)
    self._EnqueueJobsUnlocked([self._SubmitJobUnlocked(job_id, ops)])
    return job_id

  @locking.ssynchronized(_LOCK)
  @_RequireOpenQueue
  def SubmitManyJobs(self, jobs):
    """Create and store multiple jobs.

    @see: L{_SubmitJobUnlocked}

    """
    all_job_ids = self._NewSerialsUnlocked(len(jobs))

    (results, added_jobs) = \
      self._SubmitManyJobsUnlocked(jobs, all_job_ids, [])

    self._EnqueueJobsUnlocked(added_jobs)

    return results

  @staticmethod
  def _FormatSubmitError(msg, ops):
    """Formats errors which occurred while submitting a job.

    """
    return ("%s; opcodes %s" %
            (msg, utils.CommaJoin(op.Summary() for op in ops)))

  @staticmethod
  def _ResolveJobDependencies(resolve_fn, deps):
    """Resolves relative job IDs in dependencies.

    @type resolve_fn: callable
    @param resolve_fn: Function to resolve a relative job ID
    @type deps: list
    @param deps: Dependencies
    @rtype: list
    @return: Resolved dependencies

    """
    result = []

    for (dep_job_id, dep_status) in deps:
      if ht.TRelativeJobId(dep_job_id):
        assert ht.TInt(dep_job_id) and dep_job_id < 0
        try:
          job_id = resolve_fn(dep_job_id)
        except IndexError:
          # Abort
          return (False, "Unable to resolve relative job ID %s" % dep_job_id)
      else:
        job_id = dep_job_id

      result.append((job_id, dep_status))

    return (True, result)

  def _SubmitManyJobsUnlocked(self, jobs, job_ids, previous_job_ids):
    """Create and store multiple jobs.

    @see: L{_SubmitJobUnlocked}

    """
    results = []
    added_jobs = []

    def resolve_fn(job_idx, reljobid):
      assert reljobid < 0
      return (previous_job_ids + job_ids[:job_idx])[reljobid]

    for (idx, (job_id, ops)) in enumerate(zip(job_ids, jobs)):
      for op in ops:
        if getattr(op, opcodes.DEPEND_ATTR, None):
          (status, data) = \
            self._ResolveJobDependencies(compat.partial(resolve_fn, idx),
                                         op.depends)
          if not status:
            # Abort resolving dependencies
            assert ht.TNonEmptyString(data), "No error message"
            break
          # Use resolved dependencies
          op.depends = data
      else:
        try:
          job = self._SubmitJobUnlocked(job_id, ops)
        except errors.GenericError, err:
          status = False
          data = self._FormatSubmitError(str(err), ops)
        else:
          status = True
          data = job_id
          added_jobs.append(job)

      results.append((status, data))

    return (results, added_jobs)

  @locking.ssynchronized(_LOCK)
  def _EnqueueJobs(self, jobs):
    """Helper function to add jobs to worker pool's queue.

    @type jobs: list
    @param jobs: List of all jobs

    """
    return self._EnqueueJobsUnlocked(jobs)

  def _EnqueueJobsUnlocked(self, jobs):
    """Helper function to add jobs to worker pool's queue.

    @type jobs: list
    @param jobs: List of all jobs

    """
    assert self._lock.is_owned(shared=0), "Must own lock in exclusive mode"
    self._wpool.AddManyTasks([(job, ) for job in jobs],
                             priority=[job.CalcPriority() for job in jobs])

  def _GetJobStatusForDependencies(self, job_id):
    """Gets the status of a job for dependencies.

    @type job_id: string
    @param job_id: Job ID
    @raise errors.JobLost: If job can't be found

    """
    if not isinstance(job_id, basestring):
      job_id = self._FormatJobID(job_id)

    # Not using in-memory cache as doing so would require an exclusive lock

    # Try to load from disk
    job = self.SafeLoadJobFromDisk(job_id, True, writable=False)

    assert not job.writable, "Got writable job" # pylint: disable=E1101

    if job:
      return job.CalcStatus()

    raise errors.JobLost("Job %s not found" % job_id)

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
    if __debug__:
      finalized = job.CalcStatus() in constants.JOBS_FINALIZED
      assert (finalized ^ (job.end_timestamp is None))
      assert job.writable, "Can't update read-only job"

    filename = self._GetJobPath(job.id)
    data = serializer.DumpJson(job.Serialize(), indent=False)
    logging.debug("Writing job %s to %s", job.id, filename)
    self._UpdateJobQueueFile(filename, data, replicate)

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
    @param timeout: maximum time to wait in seconds
    @rtype: tuple (job info, log entries)
    @return: a tuple of the job information as required via
        the fields parameter, and the log entries as a list

        if the job has not changed and the timeout has expired,
        we instead return a special value,
        L{constants.JOB_NOTCHANGED}, which should be interpreted
        as such by the clients

    """
    load_fn = compat.partial(self.SafeLoadJobFromDisk, job_id, False,
                             writable=False)

    helper = _WaitForJobChangesHelper()

    return helper(self._GetJobPath(job_id), load_fn,
                  fields, prev_job_info, prev_log_serial, timeout)

  @locking.ssynchronized(_LOCK)
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

    assert job.writable, "Can't cancel read-only job"

    (success, msg) = job.Cancel()

    if success:
      # If the job was finalized (e.g. cancelled), this is the final write
      # allowed. The job can be archived anytime.
      self.UpdateJobUnlocked(job)

    return (success, msg)

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
      assert job.writable, "Can't archive read-only job"

      if job.CalcStatus() not in constants.JOBS_FINALIZED:
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

  @locking.ssynchronized(_LOCK)
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

  @locking.ssynchronized(_LOCK)
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
      job = self.SafeLoadJobFromDisk(job_id, True)
      if job is not None:
        jobs.append(job.GetInfo(fields))
      elif not list_all:
        jobs.append(None)

    return jobs

  @locking.ssynchronized(_LOCK)
  @_RequireOpenQueue
  def Shutdown(self):
    """Stops the job queue.

    This shutdowns all the worker threads an closes the queue.

    """
    self._wpool.TerminateWorkers()

    self._queue_filelock.Close()
    self._queue_filelock = None
