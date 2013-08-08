#
#

# Copyright (C) 2006, 2007, 2011, 2012 Google Inc.
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
from ganeti import compat


_OP_PREFIX = "Op"
_LU_PREFIX = "LU"

#: LU classes which don't need to acquire the node allocation lock
#: (L{locking.NAL}) when they acquire all node or node resource locks
_NODE_ALLOC_WHITELIST = frozenset([])

#: LU classes which don't need to acquire the node allocation lock
#: (L{locking.NAL}) in the same mode (shared/exclusive) as the node
#: or node resource locks
_NODE_ALLOC_MODE_WHITELIST = compat.UniqueFrozenset([
  cmdlib.LUBackupExport,
  cmdlib.LUBackupRemove,
  cmdlib.LUOobCommand,
  ])


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


class OpExecCbBase: # pylint: disable=W0232
  """Base class for OpCode execution callbacks.

  """
  def NotifyStart(self):
    """Called when we are about to execute the LU.

    This function is called when we're about to start the lu's Exec() method,
    that is, after we have acquired all locks.

    """

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


def _ProcessResult(submit_fn, op, result):
  """Examines opcode result.

  If necessary, additional processing on the result is done.

  """
  if isinstance(result, cmdlib.ResultWithJobs):
    # Copy basic parameters (e.g. priority)
    map(compat.partial(_SetBaseOpParams, op,
                       "Submitted by %s" % op.OP_ID),
        itertools.chain(*result.jobs))

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


def _VerifyLocks(lu, glm, _mode_whitelist=_NODE_ALLOC_MODE_WHITELIST,
                 _nal_whitelist=_NODE_ALLOC_WHITELIST):
  """Performs consistency checks on locks acquired by a logical unit.

  @type lu: L{cmdlib.LogicalUnit}
  @param lu: Logical unit instance
  @type glm: L{locking.GanetiLockManager}
  @param glm: Lock manager

  """
  if not __debug__:
    return

  have_nal = glm.check_owned(locking.LEVEL_NODE_ALLOC, locking.NAL)

  for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
    # TODO: Verify using actual lock mode, not using LU variables
    if level in lu.needed_locks:
      share_node_alloc = lu.share_locks[locking.LEVEL_NODE_ALLOC]
      share_level = lu.share_locks[level]

      if lu.__class__ in _mode_whitelist:
        assert share_node_alloc != share_level, \
          "LU is whitelisted to use different modes for node allocation lock"
      else:
        assert bool(share_node_alloc) == bool(share_level), \
          ("Node allocation lock must be acquired using the same mode as nodes"
           " and node resources")

      if lu.__class__ in _nal_whitelist:
        assert not have_nal, \
          "LU is whitelisted for not acquiring the node allocation lock"
      elif lu.needed_locks[level] == locking.ALL_SET or glm.owning_all(level):
        assert have_nal, \
          ("Node allocation lock must be used if an LU acquires all nodes"
           " or node resources")


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
    self.context = context
    self._ec_id = ec_id
    self._cbs = None
    self.rpc = context.rpc
    self.hmclass = hooksmaster.HooksMaster
    self._enable_locks = enable_locks

  def _CheckLocksEnabled(self):
    """Checks if locking is enabled.

    @raise errors.ProgrammerError: In case locking is not enabled

    """
    if not self._enable_locks:
      raise errors.ProgrammerError("Attempted to use disabled locks")

  def _AcquireLocks(self, level, names, shared, opportunistic, timeout):
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
    @raise LockAcquireTimeout: In case locks couldn't be acquired in specified
        amount of time

    """
    self._CheckLocksEnabled()

    if self._cbs:
      priority = self._cbs.CurrentPriority()
    else:
      priority = None

    acquired = self.context.glm.acquire(level, names, shared=shared,
                                        timeout=timeout, priority=priority,
                                        opportunistic=opportunistic)

    if acquired is None:
      raise LockAcquireTimeout()

    return acquired

  def _ExecLU(self, lu):
    """Logical Unit execution sequence.

    """
    write_count = self.context.cfg.write_count
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

    try:
      result = _ProcessResult(submit_mj_fn, lu.op, lu.Exec(self.Log))
      h_results = hm.RunPhase(constants.HOOKS_PHASE_POST)
      result = lu.HooksCallBack(constants.HOOKS_PHASE_POST, h_results,
                                self.Log, result)
    finally:
      # FIXME: This needs locks if not lu_class.REQ_BGL
      if write_count != self.context.cfg.write_count:
        hm.RunConfigUpdate()

    return result

  def BuildHooksManager(self, lu):
    return self.hmclass.BuildFromLu(lu.rpc.call_hooks_runner, lu)

  def _LockAndExecLU(self, lu, level, calc_timeout):
    """Execute a Logical Unit, with the needed locks.

    This is a recursive function that starts locking the given level, and
    proceeds up, till there are no more locks to acquire. Then it executes the
    given LU and its opcodes.

    """
    glm = self.context.glm
    adding_locks = level in lu.add_locks
    acquiring_locks = level in lu.needed_locks

    if level not in locking.LEVELS:
      _VerifyLocks(lu, glm)

      if self._cbs:
        self._cbs.NotifyStart()

      try:
        result = self._ExecLU(lu)
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

    elif adding_locks and acquiring_locks:
      # We could both acquire and add locks at the same level, but for now we
      # don't need this, so we'll avoid the complicated code needed.
      raise NotImplementedError("Can't declare locks to acquire when adding"
                                " others")

    elif adding_locks or acquiring_locks:
      self._CheckLocksEnabled()

      lu.DeclareLocks(level)
      share = lu.share_locks[level]
      opportunistic = lu.opportunistic_locks[level]

      try:
        assert adding_locks ^ acquiring_locks, \
          "Locks must be either added or acquired"

        if acquiring_locks:
          # Acquiring locks
          needed_locks = lu.needed_locks[level]

          self._AcquireLocks(level, needed_locks, share, opportunistic,
                             calc_timeout())
        else:
          # Adding locks
          add_locks = lu.add_locks[level]
          lu.remove_locks[level] = add_locks

          try:
            glm.add(level, add_locks, acquired=1, shared=share)
          except errors.LockError:
            logging.exception("Detected lock error in level %s for locks"
                              " %s, shared=%s", level, add_locks, share)
            raise errors.OpPrereqError(
              "Couldn't add locks (%s), most likely because of another"
              " job who added them first" % add_locks,
              errors.ECODE_NOTUNIQUE)

        try:
          result = self._LockAndExecLU(lu, level + 1, calc_timeout)
        finally:
          if level in lu.remove_locks:
            glm.remove(level, lu.remove_locks[level])
      finally:
        if glm.is_owned(level):
          glm.release(level)

    else:
      result = self._LockAndExecLU(lu, level + 1, calc_timeout)

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

      try:
        lu = lu_class(self, op, self.context, self.rpc)
        lu.ExpandNames()
        assert lu.needed_locks is not None, "needed_locks not set by LU"

        try:
          result = self._LockAndExecLU(lu, locking.LEVEL_CLUSTER + 1,
                                       calc_timeout)
        finally:
          if self._ec_id:
            self.context.cfg.DropECReservations(self._ec_id)
      finally:
        # Release BGL if owned
        if self.context.glm.is_owned(locking.LEVEL_CLUSTER):
          assert self._enable_locks
          self.context.glm.release(locking.LEVEL_CLUSTER)
    finally:
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
