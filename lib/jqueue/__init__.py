#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2014 Google Inc.
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


"""Module implementing the job queue handling.

"""

import logging
import errno
import time
import weakref
import threading
import itertools
import operator
import os

try:
  # pylint: disable=E0611
  from pyinotify import pyinotify
except ImportError:
  import pyinotify

from ganeti import asyncnotifier
from ganeti import constants
from ganeti import serializer
from ganeti import locking
from ganeti import luxi
from ganeti import opcodes
from ganeti import opcodes_base
from ganeti import errors
from ganeti import mcpu
from ganeti import utils
from ganeti import jstore
import ganeti.rpc.node as rpc
from ganeti import runtime
from ganeti import netutils
from ganeti import compat
from ganeti import ht
from ganeti import query
from ganeti import qlang
from ganeti import pathutils
from ganeti import vcluster
from ganeti.cmdlib import cluster


#: Retrieves "id" attribute
_GetIdAttr = operator.attrgetter("id")


class CancelJob(Exception):
  """Special exception to cancel a job.

  """


def TimeStampNow():
  """Returns the current timestamp.

  @rtype: tuple
  @return: the current time in the (seconds, microseconds) format

  """
  return utils.SplitTime(time.time())


def _CallJqUpdate(runner, names, file_name, content):
  """Updates job queue file after virtualizing filename.

  """
  virt_file_name = vcluster.MakeVirtualPath(file_name)
  return runner.call_jobqueue_update(names, virt_file_name, content)


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
    """Initializes instances of this class.

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
               "writable", "archived",
               "livelock", "process_id",
               "__weakref__"]

  def AddReasons(self, pickup=False):
    """Extend the reason trail

    Add the reason for all the opcodes of this job to be executed.

    """
    count = 0
    for queued_op in self.ops:
      op = queued_op.input
      if pickup:
        reason_src_prefix = constants.OPCODE_REASON_SRC_PICKUP
      else:
        reason_src_prefix = constants.OPCODE_REASON_SRC_OPCODE
      reason_src = opcodes_base.NameToReasonSrc(op.__class__.__name__,
                                                reason_src_prefix)
      reason_text = "job=%d;index=%d" % (self.id, count)
      reason = getattr(op, "reason", [])
      reason.append((reason_src, reason_text, utils.EpochNano()))
      op.reason = reason
      count = count + 1

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
    self.id = int(job_id)
    self.ops = [_QueuedOpCode(op) for op in ops]
    self.AddReasons()
    self.log_serial = 0
    self.received_timestamp = TimeStampNow()
    self.start_timestamp = None
    self.end_timestamp = None
    self.archived = False
    self.livelock = None
    self.process_id = None

    self._InitInMemory(self, writable)

    assert not self.archived, "New jobs can not be marked as archived"

  @staticmethod
  def _InitInMemory(obj, writable):
    """Initializes in-memory variables.

    """
    obj.writable = writable
    obj.ops_iter = None
    obj.cur_opctx = None

  def __repr__(self):
    status = ["%s.%s" % (self.__class__.__module__, self.__class__.__name__),
              "id=%s" % self.id,
              "ops=%s" % ",".join([op.input.Summary() for op in self.ops])]

    return "<%s at %#x>" % (" ".join(status), id(self))

  @classmethod
  def Restore(cls, queue, state, writable, archived):
    """Restore a _QueuedJob from serialized state:

    @type queue: L{JobQueue}
    @param queue: to which queue the restored job belongs
    @type state: dict
    @param state: the serialized state
    @type writable: bool
    @param writable: Whether job can be modified
    @type archived: bool
    @param archived: Whether job was already archived
    @rtype: _JobQueue
    @return: the restored _JobQueue instance

    """
    obj = _QueuedJob.__new__(cls)
    obj.queue = queue
    obj.id = int(state["id"])
    obj.received_timestamp = state.get("received_timestamp", None)
    obj.start_timestamp = state.get("start_timestamp", None)
    obj.end_timestamp = state.get("end_timestamp", None)
    obj.archived = archived
    obj.livelock = state.get("livelock", None)
    obj.process_id = state.get("process_id", None)
    if obj.process_id is not None:
      obj.process_id = int(obj.process_id)

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
      "livelock": self.livelock,
      "process_id": self.process_id,
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
      entries.extend([entry for entry in op.log if entry[0] > serial])

    return entries

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

  def ChangePriority(self, priority):
    """Changes the job priority.

    @type priority: int
    @param priority: New priority
    @rtype: tuple; (bool, string)
    @return: Boolean describing whether job's priority was successfully changed
      and a text message

    """
    status = self.CalcStatus()

    if status in constants.JOBS_FINALIZED:
      return (False, "Job %s is finished" % self.id)
    elif status == constants.JOB_STATUS_CANCELING:
      return (False, "Job %s is cancelling" % self.id)
    else:
      assert status in (constants.JOB_STATUS_QUEUED,
                        constants.JOB_STATUS_WAITING,
                        constants.JOB_STATUS_RUNNING)

      changed = False
      for op in self.ops:
        if (op.status == constants.OP_STATUS_RUNNING or
            op.status in constants.OPS_FINALIZED):
          assert not changed, \
            ("Found opcode for which priority should not be changed after"
             " priority has been changed for previous opcodes")
          continue

        assert op.status in (constants.OP_STATUS_QUEUED,
                             constants.OP_STATUS_WAITING)

        changed = True

        # Set new priority (doesn't modify opcode input)
        op.priority = priority

      if changed:
        return (True, ("Priorities of pending opcodes for job %s have been"
                       " changed to %s" % (self.id, priority)))
      else:
        return (False, "Job %s had no pending opcodes" % self.id)

  def SetPid(self, pid):
    """Sets the job's process ID

    @type pid: int
    @param pid: the process ID

    """
    status = self.CalcStatus()

    if status in (constants.JOB_STATUS_QUEUED,
                  constants.JOB_STATUS_WAITING):
      if self.process_id is not None:
        logging.warning("Replacing the process id %s of job %s with %s",
                        self.process_id, self.id, pid)
      self.process_id = pid
    else:
      logging.warning("Can set pid only for queued/waiting jobs")


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
    super(_OpExecCallbacks, self).__init__()

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

  def NotifyRetry(self):
    """Mark opcode again as lock-waiting.

    This is called from the mcpu code just after calling PrepareRetry.
    The opcode will now again acquire locks (more, hopefully).

    """
    self._op.status = constants.OP_STATUS_WAITING
    logging.debug("Opcode will be retried. Back to waiting.")

  def _AppendFeedback(self, timestamp, log_type, log_msgs):
    """Internal feedback append function, with locks

    @type timestamp: tuple (int, int)
    @param timestamp: timestamp of the log message

    @type log_type: string
    @param log_type: log type (one of Types.ELogType)

    @type log_msgs: any
    @param log_msgs: log data to append
     """

    # This should be removed once Feedback() has a clean interface.
    # Feedback can be called with anything, we interpret ELogMessageList as
    # messages that have to be individually added to the log list, but pushed
    # in a single update. Other msgtypes are only transparently passed forward.
    if log_type == constants.ELOG_MESSAGE_LIST:
      log_type = constants.ELOG_MESSAGE
    else:
      log_msgs = [log_msgs]

    for msg in log_msgs:
      self._job.log_serial += 1
      self._op.log.append((self._job.log_serial, timestamp, log_type, msg))
    self._queue.UpdateJobUnlocked(self._job, replicate=False)

  # TODO: Cleanup calling conventions, make them explicit
  def Feedback(self, *args):
    """Append a log entry.

    Calling conventions:
    arg[0]: (optional) string, message type (Types.ELogType)
    arg[1]: data to be interpreted as a message
    """
    assert len(args) < 3

    # TODO: Use separate keyword arguments for a single string vs. a list.
    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      (log_type, log_msg) = args

    # The time is split to make serialization easier and not lose
    # precision.
    timestamp = utils.SplitTime(time.time())
    self._AppendFeedback(timestamp, log_type, log_msg)

  def CurrentPriority(self):
    """Returns current priority for opcode.

    """
    assert self._op.status in (constants.OP_STATUS_WAITING,
                               constants.OP_STATUS_CANCELING)

    # Cancel here if we were asked to
    self._CheckCancel()

    return self._op.priority

  def SubmitManyJobs(self, jobs):
    """Submits jobs for processing.

    See L{JobQueue.SubmitManyJobs}.

    """
    # Locking is done in job queue
    return self._queue.SubmitManyJobs(jobs)


def _EncodeOpError(err):
  """Encodes an error which occurred while processing an opcode.

  """
  if isinstance(err, errors.GenericError):
    to_encode = err
  else:
    to_encode = errors.OpExecError(str(err))

  return errors.EncodeException(to_encode)


class _TimeoutStrategyWrapper(object):
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


class _OpExecContext(object):
  def __init__(self, op, index, log_prefix, timeout_strategy_factory):
    """Initializes this class.

    """
    self.op = op
    self.index = index
    self.log_prefix = log_prefix
    self.summary = op.input.Summary()

    # Create local copy to modify
    if getattr(op.input, opcodes_base.DEPEND_ATTR, None):
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

    assert op.status in (constants.OP_STATUS_WAITING,
                         constants.OP_STATUS_CANCELING)

    # The very last check if the job was cancelled before trying to execute
    if op.status == constants.OP_STATUS_CANCELING:
      return (constants.OP_STATUS_CANCELING, None)

    timeout = opctx.GetNextLockTimeout()

    try:
      # Make sure not to hold queue lock while calling ExecOpCode
      result = self.opexec_fn(op.input,
                              _OpExecCallbacks(self.queue, self.job, op),
                              timeout=timeout)
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

          (op_status, op_result) = self._ExecOpCodeUnlocked(opctx)

          op.status = op_status
          op.result = op_result

          assert not waitjob

        if op.status in (constants.OP_STATUS_WAITING,
                         constants.OP_STATUS_QUEUED):
          # waiting: Couldn't get locks in time
          # queued: Queue is shutting down
          assert not op.end_timestamp
        else:
          # Finalize opcode
          op.end_timestamp = TimeStampNow()

          if op.status == constants.OP_STATUS_CANCELING:
            assert not compat.any(i.status != constants.OP_STATUS_CANCELING
                                  for i in job.ops[opctx.index:])
          else:
            assert op.status in constants.OPS_FINALIZED

      if op.status == constants.OP_STATUS_QUEUED:
        # Queue is shutting down
        assert not waitjob

        finalize = False

        # Reset context
        job.cur_opctx = None

        # In no case must the status be finalized here
        assert job.CalcStatus() == constants.JOB_STATUS_QUEUED

      elif op.status == constants.OP_STATUS_WAITING or waitjob:
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
          # If we get here, we cannot afford to check for any consistency
          # any more, we just want to clean up.
          # TODO: Actually, it wouldn't be a bad idea to start a timer
          # here to kill the whole process.
          to_encode = errors.OpExecError("Preceding opcode failed")
          job.MarkUnfinishedOps(constants.OP_STATUS_ERROR,
                                _EncodeOpError(to_encode))
          finalize = True
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


class _JobDependencyManager(object):
  """Keeps track of job dependencies.

  """
  (WAIT,
   ERROR,
   CANCEL,
   CONTINUE,
   WRONGSTATUS) = range(1, 6)

  def __init__(self, getstatus_fn):
    """Initializes this class.

    """
    self._getstatus_fn = getstatus_fn

    self._waiters = {}

  def JobWaiting(self, job):
    """Checks if a job is waiting.

    """
    return compat.any(job in jobs
                      for jobs in self._waiters.values())

  def CheckAndRegister(self, job, dep_job_id, dep_status):
    """Checks if a dependency job has the requested status.

    If the other job is not yet in a finalized status, the calling job will be
    notified (re-added to the workerpool) at a later point.

    @type job: L{_QueuedJob}
    @param job: Job object
    @type dep_job_id: int
    @param dep_job_id: ID of dependency job
    @type dep_status: list
    @param dep_status: Required status

    """
    assert ht.TJobId(job.id)
    assert ht.TJobId(dep_job_id)
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

  def _RemoveEmptyWaitersUnlocked(self):
    """Remove all jobs without actual waiters.

    """
    for job_id in [job_id for (job_id, waiters) in self._waiters.items()
                   if not waiters]:
      del self._waiters[job_id]


class JobQueue(object):
  """Queue used to manage the jobs.

  """
  def __init__(self, context, cfg):
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

    # Get initial list of nodes
    self._nodes = dict((n.name, n.primary_ip)
                       for n in cfg.GetAllNodesInfo().values()
                       if n.master_candidate)

    # Remove master node
    self._nodes.pop(self._my_hostname, None)

    # Job dependencies
    self.depmgr = _JobDependencyManager(self._GetJobStatusForDependencies)

  def _GetRpc(self, address_list):
    """Gets RPC runner with context.

    """
    return rpc.JobQueueRunner(self.context, address_list)

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
                    gid=getents.daemons_gid,
                    mode=constants.JOB_QUEUE_FILES_PERMS)

    if replicate:
      names, addrs = self._GetNodeIp()
      result = _CallJqUpdate(self._GetRpc(addrs), names, file_name, data)
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
    result = self._GetRpc(addrs).call_jobqueue_rename(names, rename)
    self._CheckRpcResult(result, self._nodes, "Renaming files (%r)" % rename)

  @staticmethod
  def _GetJobPath(job_id):
    """Returns the job file for a given job id.

    @type job_id: str
    @param job_id: the job identifier
    @rtype: str
    @return: the path to the job file

    """
    return utils.PathJoin(pathutils.QUEUE_DIR, "job-%s" % job_id)

  @staticmethod
  def _GetArchivedJobPath(job_id):
    """Returns the archived job file for a give job id.

    @type job_id: str
    @param job_id: the job identifier
    @rtype: str
    @return: the path to the archived job file

    """
    return utils.PathJoin(pathutils.JOB_QUEUE_ARCHIVE_DIR,
                          jstore.GetArchiveDirectory(job_id),
                          "job-%s" % job_id)

  @staticmethod
  def _DetermineJobDirectories(archived):
    """Build list of directories containing job files.

    @type archived: bool
    @param archived: Whether to include directories for archived jobs
    @rtype: list

    """
    result = [pathutils.QUEUE_DIR]

    if archived:
      archive_path = pathutils.JOB_QUEUE_ARCHIVE_DIR
      result.extend(utils.PathJoin(archive_path, job_file) for job_file in
                        utils.ListVisibleFiles(archive_path))

    return result

  @classmethod
  def _GetJobIDsUnlocked(cls, sort=True, archived=False):
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

    for path in cls._DetermineJobDirectories(archived):
      for filename in utils.ListVisibleFiles(path):
        m = constants.JOB_FILE_RE.match(filename)
        if m:
          jlist.append(int(m.group(1)))

    if sort:
      jlist.sort()
    return jlist

  def _LoadJobUnlocked(self, job_id):
    """Loads a job from the disk or memory.

    Given a job id, this will return the cached job object if
    existing, or try to load the job from the disk. If loading from
    disk, it will also add the job to the cache.

    @type job_id: int
    @param job_id: the job id
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    assert isinstance(job_id, int), "Job queue: Supplied job id is not an int!"

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

    @type job_id: int
    @param job_id: job identifier
    @type try_archived: bool
    @param try_archived: Whether to try loading an archived job
    @rtype: L{_QueuedJob} or None
    @return: either None or the job object

    """
    path_functions = [(self._GetJobPath, False)]

    if try_archived:
      path_functions.append((self._GetArchivedJobPath, True))

    raw_data = None
    archived = None

    for (fn, archived) in path_functions:
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
      logging.debug("No data available for job %s", job_id)
      return None

    if writable is None:
      writable = not archived

    try:
      data = serializer.LoadJson(raw_data)
      job = _QueuedJob.Restore(self, data, writable, archived)
    except Exception, err: # pylint: disable=W0703
      raise errors.JobFileCorrupted(err)

    return job

  def SafeLoadJobFromDisk(self, job_id, try_archived, writable=None):
    """Load the given job file from disk.

    Given a job file, read, load and restore it in a _QueuedJob format.
    In case of error reading the job, it gets returned as None, and the
    exception is logged.

    @type job_id: int
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

  @classmethod
  def SubmitManyJobs(cls, jobs):
    """Create and store multiple jobs.

    """
    return luxi.Client(address=pathutils.QUERY_SOCKET).SubmitManyJobs(jobs)

  @staticmethod
  def _ResolveJobDependencies(resolve_fn, deps):
    """Resolves relative job IDs in dependencies.

    @type resolve_fn: callable
    @param resolve_fn: Function to resolve a relative job ID
    @type deps: list
    @param deps: Dependencies
    @rtype: tuple; (boolean, string or list)
    @return: If successful (first tuple item), the returned list contains
      resolved job IDs along with the requested status; if not successful,
      the second element is an error message

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

  def _GetJobStatusForDependencies(self, job_id):
    """Gets the status of a job for dependencies.

    @type job_id: int
    @param job_id: Job ID
    @raise errors.JobLost: If job can't be found

    """
    # Not using in-memory cache as doing so would require an exclusive lock

    # Try to load from disk
    job = self.SafeLoadJobFromDisk(job_id, True, writable=False)

    if job:
      assert not job.writable, "Got writable job" # pylint: disable=E1101

    if job:
      return job.CalcStatus()

    raise errors.JobLost("Job %s not found" % job_id)

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
      assert not job.archived, "Can't update archived job"

    filename = self._GetJobPath(job.id)
    data = serializer.DumpJson(job.Serialize())
    logging.debug("Writing job %s to %s", job.id, filename)
    self._UpdateJobQueueFile(filename, data, replicate)

  def HasJobBeenFinalized(self, job_id):
    """Checks if a job has been finalized.

    @type job_id: int
    @param job_id: Job identifier
    @rtype: boolean
    @return: True if the job has been finalized,
        False if the timeout has been reached,
        None if the job doesn't exist

    """
    job = self.SafeLoadJobFromDisk(job_id, True, writable=False)
    if job is not None:
      return job.CalcStatus() in constants.JOBS_FINALIZED
    elif cluster.LUClusterDestroy.clusterHasBeenDestroyed:
      # FIXME: The above variable is a temporary workaround until the Python job
      # queue is completely removed. When removing the job queue, also remove
      # the variable from LUClusterDestroy.
      return True
    else:
      return None

  def CancelJob(self, job_id):
    """Cancels a job.

    This will only succeed if the job has not started yet.

    @type job_id: int
    @param job_id: job ID of job to be cancelled.

    """
    logging.info("Cancelling job %s", job_id)

    return self._ModifyJobUnlocked(job_id, lambda job: job.Cancel())

  def ChangeJobPriority(self, job_id, priority):
    """Changes a job's priority.

    @type job_id: int
    @param job_id: ID of the job whose priority should be changed
    @type priority: int
    @param priority: New priority

    """
    logging.info("Changing priority of job %s to %s", job_id, priority)

    if priority not in constants.OP_PRIO_SUBMIT_VALID:
      allowed = utils.CommaJoin(constants.OP_PRIO_SUBMIT_VALID)
      raise errors.GenericError("Invalid priority %s, allowed are %s" %
                                (priority, allowed))

    def fn(job):
      (success, msg) = job.ChangePriority(priority)
      return (success, msg)

    return self._ModifyJobUnlocked(job_id, fn)

  def _ModifyJobUnlocked(self, job_id, mod_fn):
    """Modifies a job.

    @type job_id: int
    @param job_id: Job ID
    @type mod_fn: callable
    @param mod_fn: Modifying function, receiving job object as parameter,
      returning tuple of (status boolean, message string)

    """
    job = self._LoadJobUnlocked(job_id)
    if not job:
      logging.debug("Job %s not found", job_id)
      return (False, "Job %s not found" % job_id)

    assert job.writable, "Can't modify read-only job"
    assert not job.archived, "Can't modify archived job"

    (success, msg) = mod_fn(job)

    if success:
      # If the job was finalized (e.g. cancelled), this is the final write
      # allowed. The job can be archived anytime.
      self.UpdateJobUnlocked(job)

    return (success, msg)
