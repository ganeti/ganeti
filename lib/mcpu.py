#
#

# Copyright (C) 2006, 2007, 2011, 2012 Google Inc.
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


"""Module implementing the logic behind the cluster operations

This module implements the logic for doing operations in the cluster. There
are two kinds of classes defined:
  - logical units, which know how to deal with their specific opcode only
  - the processor, which dispatches the opcodes to their logical units

"""

import sys
import logging
import random
import time
import itertools
import traceback

from ganeti import opcodes
from ganeti import opcodes_base
from ganeti import constants
from ganeti import errors
from ganeti import hooksmaster
from ganeti import cmdlib
from ganeti import locking
from ganeti import utils
from ganeti import wconfd


sighupReceived = [False]
lusExecuting = [0]

_OP_PREFIX = "Op"
_LU_PREFIX = "LU"


class LockAcquireTimeout(Exception):
  """Exception to report timeouts on acquiring locks.

  """


def _CalculateLockAttemptTimeouts():
  """Calculate timeouts for lock attempts.

  """
  result = [constants.LOCK_ATTEMPTS_MINWAIT]
  running_sum = result[0]

  # Wait for a total of at least LOCK_ATTEMPTS_TIMEOUT before doing a
  # blocking acquire
  while running_sum < constants.LOCK_ATTEMPTS_TIMEOUT:
    timeout = (result[-1] * 1.05) ** 1.25

    # Cap max timeout. This gives other jobs a chance to run even if
    # we're still trying to get our locks, before finally moving to a
    # blocking acquire.
    timeout = min(timeout, constants.LOCK_ATTEMPTS_MAXWAIT)
    # And also cap the lower boundary for safety
    timeout = max(timeout, constants.LOCK_ATTEMPTS_MINWAIT)

    result.append(timeout)
    running_sum += timeout

  return result


class LockAttemptTimeoutStrategy(object):
  """Class with lock acquire timeout strategy.

  """
  __slots__ = [
    "_timeouts",
    "_random_fn",
    "_time_fn",
    ]

  _TIMEOUT_PER_ATTEMPT = _CalculateLockAttemptTimeouts()

  def __init__(self, _time_fn=time.time, _random_fn=random.random):
    """Initializes this class.

    @param _time_fn: Time function for unittests
    @param _random_fn: Random number generator for unittests

    """
    object.__init__(self)

    self._timeouts = iter(self._TIMEOUT_PER_ATTEMPT)
    self._time_fn = _time_fn
    self._random_fn = _random_fn

  def NextAttempt(self):
    """Returns the timeout for the next attempt.

    """
    try:
      timeout = self._timeouts.next()
    except StopIteration:
      # No more timeouts, do blocking acquire
      timeout = None

    if timeout is not None:
      # Add a small variation (-/+ 5%) to timeout. This helps in situations
      # where two or more jobs are fighting for the same lock(s).
      variation_range = timeout * 0.1
      timeout += ((self._random_fn() * variation_range) -
                  (variation_range * 0.5))

    return timeout


class OpExecCbBase(object): # pylint: disable=W0232
  """Base class for OpCode execution callbacks.

  """
  def NotifyStart(self):
    """Called when we are about to execute the LU.

    This function is called when we're about to start the lu's Exec() method,
    that is, after we have acquired all locks.

    """

  def NotifyRetry(self):
    """Called when we are about to reset an LU to retry again.

    This function is called after PrepareRetry successfully completed.

    """

  # TODO: Cleanup calling conventions, make them explicit.
  def Feedback(self, *args):
    """Sends feedback from the LU code to the end-user.

    """

  def CurrentPriority(self): # pylint: disable=R0201
    """Returns current priority or C{None}.

    """
    return None

  def SubmitManyJobs(self, jobs):
    """Submits jobs for processing.

    See L{jqueue.JobQueue.SubmitManyJobs}.

    """
    raise NotImplementedError


def _LUNameForOpName(opname):
  """Computes the LU name for a given OpCode name.

  """
  assert opname.startswith(_OP_PREFIX), \
      "Invalid OpCode name, doesn't start with %s: %s" % (_OP_PREFIX, opname)

  return _LU_PREFIX + opname[len(_OP_PREFIX):]


def _ComputeDispatchTable():
  """Computes the opcode-to-lu dispatch table.

  """
  return dict((op, getattr(cmdlib, _LUNameForOpName(op.__name__)))
              for op in opcodes.OP_MAPPING.values()
              if op.WITH_LU)


def _SetBaseOpParams(src, defcomment, dst):
  """Copies basic opcode parameters.

  @type src: L{opcodes.OpCode}
  @param src: Source opcode
  @type defcomment: string
  @param defcomment: Comment to specify if not already given
  @type dst: L{opcodes.OpCode}
  @param dst: Destination opcode

  """
  if hasattr(src, "debug_level"):
    dst.debug_level = src.debug_level

  if (getattr(dst, "priority", None) is None and
      hasattr(src, "priority")):
    dst.priority = src.priority

  if not getattr(dst, opcodes_base.COMMENT_ATTR, None):
    dst.comment = defcomment

  if hasattr(src, constants.OPCODE_REASON):
    dst.reason = list(getattr(dst, constants.OPCODE_REASON, []))
    dst.reason.extend(getattr(src, constants.OPCODE_REASON, []))


def _ProcessResult(submit_fn, op, result):
  """Examines opcode result.

  If necessary, additional processing on the result is done.

  """
  if isinstance(result, cmdlib.ResultWithJobs):
    # Copy basic parameters (e.g. priority)
    for op2 in itertools.chain(*result.jobs):
      _SetBaseOpParams(op, "Submitted by %s" % op.OP_ID, op2)

    # Submit jobs
    job_submission = submit_fn(result.jobs)

    # Build dictionary
    result = result.other

    assert constants.JOB_IDS_KEY not in result, \
      "Key '%s' found in additional return values" % constants.JOB_IDS_KEY

    result[constants.JOB_IDS_KEY] = job_submission

  return result


def _FailingSubmitManyJobs(_):
  """Implementation of L{OpExecCbBase.SubmitManyJobs} to raise an exception.

  """
  raise errors.ProgrammerError("Opcodes processed without callbacks (e.g."
                               " queries) can not submit jobs")


def _LockList(names):
  """If 'names' is a string, make it a single-element list.

  @type names: list or string or NoneType
  @param names: Lock names
  @rtype: a list of strings
  @return: if 'names' argument is an iterable, a list of it;
      if it's a string, make it a one-element list;
      if L{locking.ALL_SET}, L{locking.ALL_SET}

  """
  if names == locking.ALL_SET:
    return names
  elif isinstance(names, basestring):
    return [names]
  else:
    return list(names)


def _CheckSecretParameters(op):
  """Check if secret parameters are expected, but missing.

  """
  if hasattr(op, "osparams_secret") and op.osparams_secret:
    for secret_param in op.osparams_secret:
      if op.osparams_secret[secret_param].Get() == constants.REDACTED:
        raise errors.OpPrereqError("Please re-submit secret parameters to job.",
                                   errors.ECODE_INVAL)


class Processor(object):
  """Object which runs OpCodes"""
  DISPATCH_TABLE = _ComputeDispatchTable()

  def __init__(self, context, ec_id, enable_locks=True):
    """Constructor for Processor

    @type context: GanetiContext
    @param context: global Ganeti context
    @type ec_id: string
    @param ec_id: execution context identifier

    """
    self._ec_id = ec_id
    self._cbs = None
    self.cfg = context.GetConfig(ec_id)
    self.rpc = context.GetRpc(self.cfg)
    self.hmclass = hooksmaster.HooksMaster
    self._enable_locks = enable_locks
    self.wconfd = wconfd # Indirection to allow testing
    self._wconfdcontext = context.GetWConfdContext(ec_id)

  def _CheckLocksEnabled(self):
    """Checks if locking is enabled.

    @raise errors.ProgrammerError: In case locking is not enabled

    """
    if not self._enable_locks:
      raise errors.ProgrammerError("Attempted to use disabled locks")

  def _RequestAndWait(self, request, timeout):
    """Request locks from WConfD and wait for them to be granted.

    @type request: list
    @param request: the lock request to be sent to WConfD
    @type timeout: float
    @param timeout: the time to wait for the request to be granted
    @raise LockAcquireTimeout: In case locks couldn't be acquired in specified
        amount of time; in this case, locks still might be acquired or a request
        pending.

    """
    logging.debug("Trying %ss to request %s for %s",
                  timeout, request, self._wconfdcontext)
    if self._cbs:
      priority = self._cbs.CurrentPriority() # pylint: disable=W0612
    else:
      priority = None

    if priority is None:
      priority = constants.OP_PRIO_DEFAULT

    ## Expect a signal
    if sighupReceived[0]:
      logging.warning("Ignoring unexpected SIGHUP")
    sighupReceived[0] = False

    # Request locks
    self.wconfd.Client().UpdateLocksWaiting(self._wconfdcontext, priority,
                                            request)
    pending = self.wconfd.Client().HasPendingRequest(self._wconfdcontext)

    if pending:
      def _HasPending():
        if sighupReceived[0]:
          return self.wconfd.Client().HasPendingRequest(self._wconfdcontext)
        else:
          return True

      pending = utils.SimpleRetry(False, _HasPending, 0.05, timeout)

      signal = sighupReceived[0]

      if pending:
        pending = self.wconfd.Client().HasPendingRequest(self._wconfdcontext)

      if pending and signal:
        logging.warning("Ignoring unexpected SIGHUP")
      sighupReceived[0] = False

    logging.debug("Finished trying. Pending: %s", pending)
    if pending:
      raise LockAcquireTimeout()

  def _AcquireLocks(self, level, names, shared, opportunistic, timeout,
                    opportunistic_count=1, request_only=False):
    """Acquires locks via the Ganeti lock manager.

    @type level: int
    @param level: Lock level
    @type names: list or string
    @param names: Lock names
    @type shared: bool
    @param shared: Whether the locks should be acquired in shared mode
    @type opportunistic: bool
    @param opportunistic: Whether to acquire opportunistically
    @type timeout: None or float
    @param timeout: Timeout for acquiring the locks
    @type request_only: bool
    @param request_only: do not acquire the locks, just return the request
    @raise LockAcquireTimeout: In case locks couldn't be acquired in specified
        amount of time; in this case, locks still might be acquired or a request
        pending.

    """
    self._CheckLocksEnabled()

    if self._cbs:
      priority = self._cbs.CurrentPriority() # pylint: disable=W0612
    else:
      priority = None

    if priority is None:
      priority = constants.OP_PRIO_DEFAULT

    if names == locking.ALL_SET:
      if opportunistic:
        expand_fns = {
          locking.LEVEL_CLUSTER: (lambda: [locking.BGL]),
          locking.LEVEL_INSTANCE: self.cfg.GetInstanceList,
          locking.LEVEL_NODEGROUP: self.cfg.GetNodeGroupList,
          locking.LEVEL_NODE: self.cfg.GetNodeList,
          locking.LEVEL_NODE_RES: self.cfg.GetNodeList,
          locking.LEVEL_NETWORK: self.cfg.GetNetworkList,
          }
        names = expand_fns[level]()
      else:
        names = locking.LOCKSET_NAME

    names = _LockList(names)

    # For locks of the same level, the lock order is lexicographic
    names.sort()

    levelname = locking.LEVEL_NAMES[level]

    locks = ["%s/%s" % (levelname, lock) for lock in list(names)]

    if not names:
      logging.debug("Acquiring no locks for (%s) at level %s",
                    self._wconfdcontext, levelname)
      return []

    if shared:
      request = [[lock, "shared"] for lock in locks]
    else:
      request = [[lock, "exclusive"] for lock in locks]

    if request_only:
      logging.debug("Lock request for level %s is %s", level, request)
      return request

    self.cfg.OutDate()

    if timeout is None:
      ## Note: once we are so desperate for locks to request them
      ## unconditionally, we no longer care about an original plan
      ## to acquire locks opportunistically.
      logging.info("Definitely requesting %s for %s",
                   request, self._wconfdcontext)
      ## The only way to be sure of not getting starved is to sequentially
      ## acquire the locks one by one (in lock order).
      for r in request:
        logging.debug("Definite request %s for %s", r, self._wconfdcontext)
        self.wconfd.Client().UpdateLocksWaiting(self._wconfdcontext, priority,
                                                [r])
        while True:
          pending = self.wconfd.Client().HasPendingRequest(self._wconfdcontext)
          if not pending:
            break
          time.sleep(10.0 * random.random())

    elif opportunistic:
      logging.debug("For %ss trying to opportunistically acquire"
                    "  at least %d of %s for %s.",
                    timeout, opportunistic_count, locks, self._wconfdcontext)
      locks = utils.SimpleRetry(
        lambda l: l != [], self.wconfd.Client().GuardedOpportunisticLockUnion,
        2.0, timeout, args=[opportunistic_count, self._wconfdcontext, request])
      logging.debug("Managed to get the following locks: %s", locks)
      if locks == []:
        raise LockAcquireTimeout()
    else:
      self._RequestAndWait(request, timeout)

    return locks

  def _ExecLU(self, lu):
    """Logical Unit execution sequence.

    """
    write_count = self.cfg.write_count
    lu.cfg.OutDate()
    lu.CheckPrereq()

    hm = self.BuildHooksManager(lu)
    h_results = hm.RunPhase(constants.HOOKS_PHASE_PRE)
    lu.HooksCallBack(constants.HOOKS_PHASE_PRE, h_results,
                     self.Log, None)

    if getattr(lu.op, "dry_run", False):
      # in this mode, no post-hooks are run, and the config is not
      # written (as it might have been modified by another LU, and we
      # shouldn't do writeout on behalf of other threads
      self.LogInfo("dry-run mode requested, not actually executing"
                   " the operation")
      return lu.dry_run_result

    if self._cbs:
      submit_mj_fn = self._cbs.SubmitManyJobs
    else:
      submit_mj_fn = _FailingSubmitManyJobs

    lusExecuting[0] += 1
    try:
      result = _ProcessResult(submit_mj_fn, lu.op, lu.Exec(self.Log))
      h_results = hm.RunPhase(constants.HOOKS_PHASE_POST)
      result = lu.HooksCallBack(constants.HOOKS_PHASE_POST, h_results,
                                self.Log, result)
    finally:
      # FIXME: This needs locks if not lu_class.REQ_BGL
      lusExecuting[0] -= 1
      if write_count != self.cfg.write_count:
        hm.RunConfigUpdate()

    return result

  def BuildHooksManager(self, lu):
    return self.hmclass.BuildFromLu(lu.rpc.call_hooks_runner, lu)

  def _LockAndExecLU(self, lu, level, calc_timeout, pending=None):
    """Execute a Logical Unit, with the needed locks.

    This is a recursive function that starts locking the given level, and
    proceeds up, till there are no more locks to acquire. Then it executes the
    given LU and its opcodes.

    """
    pending = pending or []
    logging.debug("Looking at locks of level %s, still need to obtain %s",
                  level, pending)
    adding_locks = level in lu.add_locks
    acquiring_locks = level in lu.needed_locks

    if level not in locking.LEVELS:
      if pending:
        self._RequestAndWait(pending, calc_timeout())
        lu.cfg.OutDate()
        lu.wconfdlocks = self.wconfd.Client().ListLocks(self._wconfdcontext)
        pending = []

      logging.debug("Finished acquiring locks")

      if self._cbs:
        self._cbs.NotifyStart()

      try:
        result = self._ExecLU(lu)
      except errors.OpPrereqError, err:
        if len(err.args) < 2 or err.args[1] != errors.ECODE_TEMP_NORES:
          raise

        logging.debug("Temporarily out of resources; will retry internally")
        try:
          lu.PrepareRetry(self.Log)
          if self._cbs:
            self._cbs.NotifyRetry()
        except errors.OpRetryNotSupportedError:
          logging.debug("LU does not know how to retry.")
          raise err
        raise LockAcquireTimeout()
      except AssertionError, err:
        # this is a bit ugly, as we don't know from which phase
        # (prereq, exec) this comes; but it's better than an exception
        # with no information
        (_, _, tb) = sys.exc_info()
        err_info = traceback.format_tb(tb)
        del tb
        logging.exception("Detected AssertionError")
        raise errors.OpExecError("Internal assertion error: please report"
                                 " this as a bug.\nError message: '%s';"
                                 " location:\n%s" % (str(err), err_info[-1]))
      return result

    # Determine if the acquiring is opportunistic up front
    opportunistic = lu.opportunistic_locks[level]

    dont_collate = lu.dont_collate_locks[level]

    if dont_collate and pending:
      self._RequestAndWait(pending, calc_timeout())
      lu.cfg.OutDate()
      lu.wconfdlocks = self.wconfd.Client().ListLocks(self._wconfdcontext)
      pending = []

    if adding_locks and opportunistic:
      # We could simultaneously acquire locks opportunistically and add new
      # ones, but that would require altering the API, and no use cases are
      # present in the system at the moment.
      raise NotImplementedError("Can't opportunistically acquire locks when"
                                " adding new ones")

    if adding_locks and acquiring_locks and \
       lu.needed_locks[level] == locking.ALL_SET:
      # It would also probably be possible to acquire all locks of a certain
      # type while adding new locks, but there is no use case at the moment.
      raise NotImplementedError("Can't request all locks of a certain level"
                                " and add new locks")

    if adding_locks or acquiring_locks:
      self._CheckLocksEnabled()

      lu.DeclareLocks(level)
      share = lu.share_locks[level]
      opportunistic_count = lu.opportunistic_locks_count[level]

      try:
        if acquiring_locks:
          needed_locks = _LockList(lu.needed_locks[level])
        else:
          needed_locks = []

        if adding_locks:
          needed_locks.extend(_LockList(lu.add_locks[level]))

        timeout = calc_timeout()
        if timeout is not None and not opportunistic:
          pending = pending + self._AcquireLocks(level, needed_locks, share,
                                                 opportunistic, timeout,
                                                 request_only=True)
        else:
          if pending:
            self._RequestAndWait(pending, calc_timeout())
            lu.cfg.OutDate()
            lu.wconfdlocks = self.wconfd.Client().ListLocks(self._wconfdcontext)
            pending = []
          self._AcquireLocks(level, needed_locks, share, opportunistic,
                             timeout,
                             opportunistic_count=opportunistic_count)
          lu.wconfdlocks = self.wconfd.Client().ListLocks(self._wconfdcontext)

        result = self._LockAndExecLU(lu, level + 1, calc_timeout,
                                     pending=pending)
      finally:
        levelname = locking.LEVEL_NAMES[level]
        logging.debug("Freeing locks at level %s for %s",
                      levelname, self._wconfdcontext)
        self.wconfd.Client().FreeLocksLevel(self._wconfdcontext, levelname)
    else:
      result = self._LockAndExecLU(lu, level + 1, calc_timeout, pending=pending)

    return result

  # pylint: disable=R0201
  def _CheckLUResult(self, op, result):
    """Check the LU result against the contract in the opcode.

    """
    resultcheck_fn = op.OP_RESULT
    if not (resultcheck_fn is None or resultcheck_fn(result)):
      logging.error("Expected opcode result matching %s, got %s",
                    resultcheck_fn, result)
      if not getattr(op, "dry_run", False):
        # FIXME: LUs should still behave in dry_run mode, or
        # alternately we should have OP_DRYRUN_RESULT; in the
        # meantime, we simply skip the OP_RESULT check in dry-run mode
        raise errors.OpResultError("Opcode result does not match %s: %s" %
                                   (resultcheck_fn, utils.Truncate(result, 80)))

  def ExecOpCode(self, op, cbs, timeout=None):
    """Execute an opcode.

    @type op: an OpCode instance
    @param op: the opcode to be executed
    @type cbs: L{OpExecCbBase}
    @param cbs: Runtime callbacks
    @type timeout: float or None
    @param timeout: Maximum time to acquire all locks, None for no timeout
    @raise LockAcquireTimeout: In case locks couldn't be acquired in specified
        amount of time

    """
    if not isinstance(op, opcodes.OpCode):
      raise errors.ProgrammerError("Non-opcode instance passed"
                                   " to ExecOpcode (%s)" % type(op))

    lu_class = self.DISPATCH_TABLE.get(op.__class__, None)
    if lu_class is None:
      raise errors.OpCodeUnknown("Unknown opcode")

    if timeout is None:
      calc_timeout = lambda: None
    else:
      calc_timeout = utils.RunningTimeout(timeout, False).Remaining

    self._cbs = cbs
    try:
      if self._enable_locks:
        # Acquire the Big Ganeti Lock exclusively if this LU requires it,
        # and in a shared fashion otherwise (to prevent concurrent run with
        # an exclusive LU.
        self._AcquireLocks(locking.LEVEL_CLUSTER, locking.BGL,
                            not lu_class.REQ_BGL, False, calc_timeout())
      elif lu_class.REQ_BGL:
        raise errors.ProgrammerError("Opcode '%s' requires BGL, but locks are"
                                     " disabled" % op.OP_ID)

      lu = lu_class(self, op, self.cfg, self.rpc,
                    self._wconfdcontext, self.wconfd)
      lu.wconfdlocks = self.wconfd.Client().ListLocks(self._wconfdcontext)
      _CheckSecretParameters(op)
      lu.ExpandNames()
      assert lu.needed_locks is not None, "needed_locks not set by LU"

      try:
        result = self._LockAndExecLU(lu, locking.LEVEL_CLUSTER + 1,
                                     calc_timeout)
      finally:
        if self._ec_id:
          self.cfg.DropECReservations(self._ec_id)
    finally:
      self.wconfd.Client().FreeLocksLevel(
        self._wconfdcontext, locking.LEVEL_NAMES[locking.LEVEL_CLUSTER])
      self._cbs = None

    self._CheckLUResult(op, result)

    return result

  def Log(self, *args):
    """Forward call to feedback callback function.

    """
    if self._cbs:
      self._cbs.Feedback(*args)

  def LogStep(self, current, total, message):
    """Log a change in LU execution progress.

    """
    logging.debug("Step %d/%d %s", current, total, message)
    self.Log("STEP %d/%d %s" % (current, total, message))

  def LogWarning(self, message, *args, **kwargs):
    """Log a warning to the logs and the user.

    The optional keyword argument is 'hint' and can be used to show a
    hint to the user (presumably related to the warning). If the
    message is empty, it will not be printed at all, allowing one to
    show only a hint.

    """
    assert not kwargs or (len(kwargs) == 1 and "hint" in kwargs), \
           "Invalid keyword arguments for LogWarning (%s)" % str(kwargs)
    if args:
      message = message % tuple(args)
    if message:
      logging.warning(message)
      self.Log(" - WARNING: %s" % message)
    if "hint" in kwargs:
      self.Log("      Hint: %s" % kwargs["hint"])

  def LogInfo(self, message, *args):
    """Log an informational message to the logs and the user.

    """
    if args:
      message = message % tuple(args)
    logging.info(message)
    self.Log(" - INFO: %s" % message)

  def GetECId(self):
    """Returns the current execution context ID.

    """
    if not self._ec_id:
      raise errors.ProgrammerError("Tried to use execution context id when"
                                   " not set")
    return self._ec_id
