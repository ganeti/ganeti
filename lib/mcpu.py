#
#

# Copyright (C) 2006, 2007, 2011 Google Inc.
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

import logging
import random
import time

from ganeti import opcodes
from ganeti import constants
from ganeti import errors
from ganeti import rpc
from ganeti import cmdlib
from ganeti import locking
from ganeti import utils
from ganeti import compat


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

  def CheckCancel(self):
    """Check whether job has been cancelled.

    """

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


def _RpcResultsToHooksResults(rpc_results):
  """Function to convert RPC results to the format expected by HooksMaster.

  @type rpc_results: dict(node: L{rpc.RpcResult})
  @param rpc_results: RPC results
  @rtype: dict(node: (fail_msg, offline, hooks_results))
  @return: RPC results unpacked according to the format expected by
    L({mcpu.HooksMaster}

  """
  return dict((node, (rpc_res.fail_msg, rpc_res.offline, rpc_res.payload))
              for (node, rpc_res) in rpc_results.items())


class Processor(object):
  """Object which runs OpCodes"""
  DISPATCH_TABLE = _ComputeDispatchTable()

  def __init__(self, context, ec_id):
    """Constructor for Processor

    @type context: GanetiContext
    @param context: global Ganeti context
    @type ec_id: string
    @param ec_id: execution context identifier

    """
    self.context = context
    self._ec_id = ec_id
    self._cbs = None
    self.rpc = rpc.RpcRunner(context.cfg)
    self.hmclass = HooksMaster

  def _AcquireLocks(self, level, names, shared, timeout, priority):
    """Acquires locks via the Ganeti lock manager.

    @type level: int
    @param level: Lock level
    @type names: list or string
    @param names: Lock names
    @type shared: bool
    @param shared: Whether the locks should be acquired in shared mode
    @type timeout: None or float
    @param timeout: Timeout for acquiring the locks
    @raise LockAcquireTimeout: In case locks couldn't be acquired in specified
        amount of time

    """
    if self._cbs:
      self._cbs.CheckCancel()

    acquired = self.context.glm.acquire(level, names, shared=shared,
                                        timeout=timeout, priority=priority)

    if acquired is None:
      raise LockAcquireTimeout()

    return acquired

  def _ProcessResult(self, result):
    """Examines opcode result.

    If necessary, additional processing on the result is done.

    """
    if isinstance(result, cmdlib.ResultWithJobs):
      # Submit jobs
      job_submission = self._cbs.SubmitManyJobs(result.jobs)

      # Build dictionary
      result = result.other

      assert constants.JOB_IDS_KEY not in result, \
        "Key '%s' found in additional return values" % constants.JOB_IDS_KEY

      result[constants.JOB_IDS_KEY] = job_submission

    return result

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

    try:
      result = self._ProcessResult(lu.Exec(self.Log))
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

  def _LockAndExecLU(self, lu, level, calc_timeout, priority):
    """Execute a Logical Unit, with the needed locks.

    This is a recursive function that starts locking the given level, and
    proceeds up, till there are no more locks to acquire. Then it executes the
    given LU and its opcodes.

    """
    adding_locks = level in lu.add_locks
    acquiring_locks = level in lu.needed_locks
    if level not in locking.LEVELS:
      if self._cbs:
        self._cbs.NotifyStart()

      result = self._ExecLU(lu)

    elif adding_locks and acquiring_locks:
      # We could both acquire and add locks at the same level, but for now we
      # don't need this, so we'll avoid the complicated code needed.
      raise NotImplementedError("Can't declare locks to acquire when adding"
                                " others")

    elif adding_locks or acquiring_locks:
      lu.DeclareLocks(level)
      share = lu.share_locks[level]

      try:
        assert adding_locks ^ acquiring_locks, \
          "Locks must be either added or acquired"

        if acquiring_locks:
          # Acquiring locks
          needed_locks = lu.needed_locks[level]

          self._AcquireLocks(level, needed_locks, share,
                             calc_timeout(), priority)
        else:
          # Adding locks
          add_locks = lu.add_locks[level]
          lu.remove_locks[level] = add_locks

          try:
            self.context.glm.add(level, add_locks, acquired=1, shared=share)
          except errors.LockError:
            raise errors.OpPrereqError(
              "Couldn't add locks (%s), probably because of a race condition"
              " with another job, who added them first" % add_locks,
              errors.ECODE_FAULT)

        try:
          result = self._LockAndExecLU(lu, level + 1, calc_timeout, priority)
        finally:
          if level in lu.remove_locks:
            self.context.glm.remove(level, lu.remove_locks[level])
      finally:
        if self.context.glm.is_owned(level):
          self.context.glm.release(level)

    else:
      result = self._LockAndExecLU(lu, level + 1, calc_timeout, priority)

    return result

  def ExecOpCode(self, op, cbs, timeout=None, priority=None):
    """Execute an opcode.

    @type op: an OpCode instance
    @param op: the opcode to be executed
    @type cbs: L{OpExecCbBase}
    @param cbs: Runtime callbacks
    @type timeout: float or None
    @param timeout: Maximum time to acquire all locks, None for no timeout
    @type priority: number or None
    @param priority: Priority for acquiring lock(s)
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
      # Acquire the Big Ganeti Lock exclusively if this LU requires it,
      # and in a shared fashion otherwise (to prevent concurrent run with
      # an exclusive LU.
      self._AcquireLocks(locking.LEVEL_CLUSTER, locking.BGL,
                          not lu_class.REQ_BGL, calc_timeout(),
                          priority)
      try:
        lu = lu_class(self, op, self.context, self.rpc)
        lu.ExpandNames()
        assert lu.needed_locks is not None, "needed_locks not set by LU"

        try:
          result = self._LockAndExecLU(lu, locking.LEVEL_INSTANCE, calc_timeout,
                                       priority)
        finally:
          if self._ec_id:
            self.context.cfg.DropECReservations(self._ec_id)
      finally:
        self.context.glm.release(locking.LEVEL_CLUSTER)
    finally:
      self._cbs = None

    resultcheck_fn = op.OP_RESULT
    if not (resultcheck_fn is None or resultcheck_fn(result)):
      logging.error("Expected opcode result matching %s, got %s",
                    resultcheck_fn, result)
      raise errors.OpResultError("Opcode result does not match %s" %
                                 resultcheck_fn)

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


class HooksMaster(object):
  def __init__(self, opcode, hooks_path, nodes, hooks_execution_fn,
    hooks_results_adapt_fn, build_env_fn, log_fn, htype=None, cluster_name=None,
    master_name=None):
    """Base class for hooks masters.

    This class invokes the execution of hooks according to the behaviour
    specified by its parameters.

    @type opcode: string
    @param opcode: opcode of the operation to which the hooks are tied
    @type hooks_path: string
    @param hooks_path: prefix of the hooks directories
    @type nodes: 2-tuple of lists
    @param nodes: 2-tuple of lists containing nodes on which pre-hooks must be
      run and nodes on which post-hooks must be run
    @type hooks_execution_fn: function that accepts the following parameters:
      (node_list, hooks_path, phase, environment)
    @param hooks_execution_fn: function that will execute the hooks; can be
      None, indicating that no conversion is necessary.
    @type hooks_results_adapt_fn: function
    @param hooks_results_adapt_fn: function that will adapt the return value of
      hooks_execution_fn to the format expected by RunPhase
    @type build_env_fn: function that returns a dictionary having strings as
      keys
    @param build_env_fn: function that builds the environment for the hooks
    @type log_fn: function that accepts a string
    @param log_fn: logging function
    @type htype: string or None
    @param htype: None or one of L{constants.HTYPE_CLUSTER},
     L{constants.HTYPE_NODE}, L{constants.HTYPE_INSTANCE}
    @type cluster_name: string
    @param cluster_name: name of the cluster
    @type master_name: string
    @param master_name: name of the master

    """
    self.opcode = opcode
    self.hooks_path = hooks_path
    self.hooks_execution_fn = hooks_execution_fn
    self.hooks_results_adapt_fn = hooks_results_adapt_fn
    self.build_env_fn = build_env_fn
    self.log_fn = log_fn
    self.htype = htype
    self.cluster_name = cluster_name
    self.master_name = master_name

    self.pre_env = self._BuildEnv(constants.HOOKS_PHASE_PRE)
    (self.pre_nodes, self.post_nodes) = nodes

  def _BuildEnv(self, phase):
    """Compute the environment and the target nodes.

    Based on the opcode and the current node list, this builds the
    environment for the hooks and the target node list for the run.

    """
    if phase == constants.HOOKS_PHASE_PRE:
      prefix = "GANETI_"
    elif phase == constants.HOOKS_PHASE_POST:
      prefix = "GANETI_POST_"
    else:
      raise AssertionError("Unknown phase '%s'" % phase)

    env = {}

    if self.hooks_path is not None:
      phase_env = self.build_env_fn()
      if phase_env:
        assert not compat.any(key.upper().startswith(prefix)
                              for key in phase_env)
        env.update(("%s%s" % (prefix, key), value)
                   for (key, value) in phase_env.items())

    if phase == constants.HOOKS_PHASE_PRE:
      assert compat.all((key.startswith("GANETI_") and
                         not key.startswith("GANETI_POST_"))
                        for key in env)

    elif phase == constants.HOOKS_PHASE_POST:
      assert compat.all(key.startswith("GANETI_POST_") for key in env)
      assert isinstance(self.pre_env, dict)

      # Merge with pre-phase environment
      assert not compat.any(key.startswith("GANETI_POST_")
                            for key in self.pre_env)
      env.update(self.pre_env)
    else:
      raise AssertionError("Unknown phase '%s'" % phase)

    return env

  def _RunWrapper(self, node_list, hpath, phase, phase_env):
    """Simple wrapper over self.callfn.

    This method fixes the environment before executing the hooks.

    """
    env = {
      "PATH": "/sbin:/bin:/usr/sbin:/usr/bin",
      "GANETI_HOOKS_VERSION": constants.HOOKS_VERSION,
      "GANETI_OP_CODE": self.opcode,
      "GANETI_DATA_DIR": constants.DATA_DIR,
      "GANETI_HOOKS_PHASE": phase,
      "GANETI_HOOKS_PATH": hpath,
      }

    if self.htype:
      env["GANETI_OBJECT_TYPE"] = self.htype

    if self.cluster_name is not None:
      env["GANETI_CLUSTER"] = self.cluster_name

    if self.master_name is not None:
      env["GANETI_MASTER"] = self.master_name

    if phase_env:
      env = utils.algo.JoinDisjointDicts(env, phase_env)

    # Convert everything to strings
    env = dict([(str(key), str(val)) for key, val in env.iteritems()])

    assert compat.all(key == "PATH" or key.startswith("GANETI_")
                      for key in env)

    return self.hooks_execution_fn(node_list, hpath, phase, env)

  def RunPhase(self, phase, nodes=None):
    """Run all the scripts for a phase.

    This is the main function of the HookMaster.
    It executes self.hooks_execution_fn, and after running
    self.hooks_results_adapt_fn on its results it expects them to be in the form
    {node_name: (fail_msg, [(script, result, output), ...]}).

    @param phase: one of L{constants.HOOKS_PHASE_POST} or
        L{constants.HOOKS_PHASE_PRE}; it denotes the hooks phase
    @param nodes: overrides the predefined list of nodes for the given phase
    @return: the processed results of the hooks multi-node rpc call
    @raise errors.HooksFailure: on communication failure to the nodes
    @raise errors.HooksAbort: on failure of one of the hooks

    """
    if phase == constants.HOOKS_PHASE_PRE:
      if nodes is None:
        nodes = self.pre_nodes
      env = self.pre_env
    elif phase == constants.HOOKS_PHASE_POST:
      if nodes is None:
        nodes = self.post_nodes
      env = self._BuildEnv(phase)
    else:
      raise AssertionError("Unknown phase '%s'" % phase)

    if not nodes:
      # empty node list, we should not attempt to run this as either
      # we're in the cluster init phase and the rpc client part can't
      # even attempt to run, or this LU doesn't do hooks at all
      return

    results = self._RunWrapper(nodes, self.hooks_path, phase, env)
    if not results:
      msg = "Communication Failure"
      if phase == constants.HOOKS_PHASE_PRE:
        raise errors.HooksFailure(msg)
      else:
        self.log_fn(msg)
        return results

    converted_res = results
    if self.hooks_results_adapt_fn:
      converted_res = self.hooks_results_adapt_fn(results)

    errs = []
    for node_name, (fail_msg, offline, hooks_results) in converted_res.items():
      if offline:
        continue

      if fail_msg:
        self.log_fn("Communication failure to node %s: %s", node_name, fail_msg)
        continue

      for script, hkr, output in hooks_results:
        if hkr == constants.HKR_FAIL:
          if phase == constants.HOOKS_PHASE_PRE:
            errs.append((node_name, script, output))
          else:
            if not output:
              output = "(no output)"
            self.log_fn("On %s script %s failed, output: %s" %
                        (node_name, script, output))

    if errs and phase == constants.HOOKS_PHASE_PRE:
      raise errors.HooksAbort(errs)

    return results

  def RunConfigUpdate(self):
    """Run the special configuration update hook

    This is a special hook that runs only on the master after each
    top-level LI if the configuration has been updated.

    """
    phase = constants.HOOKS_PHASE_POST
    hpath = constants.HOOKS_NAME_CFGUPDATE
    nodes = [self.master_name]
    self._RunWrapper(nodes, hpath, phase, self.pre_env)

  @staticmethod
  def BuildFromLu(hooks_execution_fn, lu):
    if lu.HPATH is None:
      nodes = (None, None)
    else:
      nodes = map(frozenset, lu.BuildHooksNodes())

    master_name = cluster_name = None
    if lu.cfg:
      master_name = lu.cfg.GetMasterNode()
      cluster_name = lu.cfg.GetClusterName()

    return HooksMaster(lu.op.OP_ID, lu.HPATH, nodes, hooks_execution_fn,
                       _RpcResultsToHooksResults, lu.BuildHooksEnv,
                       lu.LogWarning, lu.HTYPE, cluster_name, master_name)
