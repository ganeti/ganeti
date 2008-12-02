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


"""Module implementing the logic behind the cluster operations

This module implements the logic for doing operations in the cluster. There
are two kinds of classes defined:
  - logical units, which know how to deal with their specific opcode only
  - the processor, which dispatches the opcodes to their logical units

"""

import logging

from ganeti import opcodes
from ganeti import constants
from ganeti import errors
from ganeti import rpc
from ganeti import cmdlib
from ganeti import locking


class Processor(object):
  """Object which runs OpCodes"""
  DISPATCH_TABLE = {
    # Cluster
    opcodes.OpDestroyCluster: cmdlib.LUDestroyCluster,
    opcodes.OpQueryClusterInfo: cmdlib.LUQueryClusterInfo,
    opcodes.OpVerifyCluster: cmdlib.LUVerifyCluster,
    opcodes.OpQueryConfigValues: cmdlib.LUQueryConfigValues,
    opcodes.OpRenameCluster: cmdlib.LURenameCluster,
    opcodes.OpVerifyDisks: cmdlib.LUVerifyDisks,
    opcodes.OpSetClusterParams: cmdlib.LUSetClusterParams,
    # node lu
    opcodes.OpAddNode: cmdlib.LUAddNode,
    opcodes.OpQueryNodes: cmdlib.LUQueryNodes,
    opcodes.OpQueryNodeVolumes: cmdlib.LUQueryNodeVolumes,
    opcodes.OpRemoveNode: cmdlib.LURemoveNode,
    opcodes.OpSetNodeParams: cmdlib.LUSetNodeParams,
    # instance lu
    opcodes.OpCreateInstance: cmdlib.LUCreateInstance,
    opcodes.OpReinstallInstance: cmdlib.LUReinstallInstance,
    opcodes.OpRemoveInstance: cmdlib.LURemoveInstance,
    opcodes.OpRenameInstance: cmdlib.LURenameInstance,
    opcodes.OpActivateInstanceDisks: cmdlib.LUActivateInstanceDisks,
    opcodes.OpShutdownInstance: cmdlib.LUShutdownInstance,
    opcodes.OpStartupInstance: cmdlib.LUStartupInstance,
    opcodes.OpRebootInstance: cmdlib.LURebootInstance,
    opcodes.OpDeactivateInstanceDisks: cmdlib.LUDeactivateInstanceDisks,
    opcodes.OpReplaceDisks: cmdlib.LUReplaceDisks,
    opcodes.OpFailoverInstance: cmdlib.LUFailoverInstance,
    opcodes.OpConnectConsole: cmdlib.LUConnectConsole,
    opcodes.OpQueryInstances: cmdlib.LUQueryInstances,
    opcodes.OpQueryInstanceData: cmdlib.LUQueryInstanceData,
    opcodes.OpSetInstanceParams: cmdlib.LUSetInstanceParams,
    opcodes.OpGrowDisk: cmdlib.LUGrowDisk,
    # os lu
    opcodes.OpDiagnoseOS: cmdlib.LUDiagnoseOS,
    # exports lu
    opcodes.OpQueryExports: cmdlib.LUQueryExports,
    opcodes.OpExportInstance: cmdlib.LUExportInstance,
    opcodes.OpRemoveExport: cmdlib.LURemoveExport,
    # tags lu
    opcodes.OpGetTags: cmdlib.LUGetTags,
    opcodes.OpSearchTags: cmdlib.LUSearchTags,
    opcodes.OpAddTags: cmdlib.LUAddTags,
    opcodes.OpDelTags: cmdlib.LUDelTags,
    # test lu
    opcodes.OpTestDelay: cmdlib.LUTestDelay,
    opcodes.OpTestAllocator: cmdlib.LUTestAllocator,
    }

  def __init__(self, context):
    """Constructor for Processor

    Args:
     - feedback_fn: the feedback function (taking one string) to be run when
                    interesting events are happening
    """
    self.context = context
    self._feedback_fn = None
    self.exclusive_BGL = False
    self.rpc = rpc.RpcRunner(context.cfg)

  def _ExecLU(self, lu):
    """Logical Unit execution sequence.

    """
    write_count = self.context.cfg.write_count
    lu.CheckPrereq()
    hm = HooksMaster(self.rpc.call_hooks_runner, self, lu)
    h_results = hm.RunPhase(constants.HOOKS_PHASE_PRE)
    lu.HooksCallBack(constants.HOOKS_PHASE_PRE, h_results,
                     self._feedback_fn, None)
    try:
      result = lu.Exec(self._feedback_fn)
      h_results = hm.RunPhase(constants.HOOKS_PHASE_POST)
      result = lu.HooksCallBack(constants.HOOKS_PHASE_POST, h_results,
                                self._feedback_fn, result)
    finally:
      # FIXME: This needs locks if not lu_class.REQ_BGL
      if write_count != self.context.cfg.write_count:
        hm.RunConfigUpdate()

    return result

  def _LockAndExecLU(self, lu, level):
    """Execute a Logical Unit, with the needed locks.

    This is a recursive function that starts locking the given level, and
    proceeds up, till there are no more locks to acquire. Then it executes the
    given LU and its opcodes.

    """
    adding_locks = level in lu.add_locks
    acquiring_locks = level in lu.needed_locks
    if level not in locking.LEVELS:
      if callable(self._run_notifier):
        self._run_notifier()
      result = self._ExecLU(lu)
    elif adding_locks and acquiring_locks:
      # We could both acquire and add locks at the same level, but for now we
      # don't need this, so we'll avoid the complicated code needed.
      raise NotImplementedError(
        "Can't declare locks to acquire when adding others")
    elif adding_locks or acquiring_locks:
      lu.DeclareLocks(level)
      share = lu.share_locks[level]
      if acquiring_locks:
        needed_locks = lu.needed_locks[level]
        lu.acquired_locks[level] = self.context.glm.acquire(level,
                                                            needed_locks,
                                                            shared=share)
      else: # adding_locks
        add_locks = lu.add_locks[level]
        lu.remove_locks[level] = add_locks
        try:
          self.context.glm.add(level, add_locks, acquired=1, shared=share)
        except errors.LockError:
          raise errors.OpPrereqError(
            "Coudn't add locks (%s), probably because of a race condition"
            " with another job, who added them first" % add_locks)
      try:
        try:
          if adding_locks:
            lu.acquired_locks[level] = add_locks
          result = self._LockAndExecLU(lu, level + 1)
        finally:
          if level in lu.remove_locks:
            self.context.glm.remove(level, lu.remove_locks[level])
      finally:
        if self.context.glm.is_owned(level):
          self.context.glm.release(level)
    else:
      result = self._LockAndExecLU(lu, level + 1)

    return result

  def ExecOpCode(self, op, feedback_fn, run_notifier):
    """Execute an opcode.

    @type op: an OpCode instance
    @param op: the opcode to be executed
    @type feedback_fn: a function that takes a single argument
    @param feedback_fn: this function will be used as feedback from the LU
                        code to the end-user
    @type run_notifier: callable (no arguments) or None
    @param run_notifier:  this function (if callable) will be called when
                          we are about to call the lu's Exec() method, that
                          is, after we have aquired all locks

    """
    if not isinstance(op, opcodes.OpCode):
      raise errors.ProgrammerError("Non-opcode instance passed"
                                   " to ExecOpcode")

    self._feedback_fn = feedback_fn
    self._run_notifier = run_notifier
    lu_class = self.DISPATCH_TABLE.get(op.__class__, None)
    if lu_class is None:
      raise errors.OpCodeUnknown("Unknown opcode")

    # Acquire the Big Ganeti Lock exclusively if this LU requires it, and in a
    # shared fashion otherwise (to prevent concurrent run with an exclusive LU.
    self.context.glm.acquire(locking.LEVEL_CLUSTER, [locking.BGL],
                             shared=not lu_class.REQ_BGL)
    try:
      self.exclusive_BGL = lu_class.REQ_BGL
      lu = lu_class(self, op, self.context, self.rpc)
      lu.ExpandNames()
      assert lu.needed_locks is not None, "needed_locks not set by LU"
      result = self._LockAndExecLU(lu, locking.LEVEL_INSTANCE)
    finally:
      self.context.glm.release(locking.LEVEL_CLUSTER)
      self.exclusive_BGL = False

    return result

  def LogStep(self, current, total, message):
    """Log a change in LU execution progress.

    """
    logging.debug("Step %d/%d %s", current, total, message)
    self._feedback_fn("STEP %d/%d %s" % (current, total, message))

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
      self._feedback_fn(" - WARNING: %s" % message)
    if "hint" in kwargs:
      self._feedback_fn("      Hint: %s" % kwargs["hint"])

  def LogInfo(self, message, *args):
    """Log an informational message to the logs and the user.

    """
    if args:
      message = message % tuple(args)
    logging.info(message)
    self._feedback_fn(" - INFO: %s" % message)


class HooksMaster(object):
  """Hooks master.

  This class distributes the run commands to the nodes based on the
  specific LU class.

  In order to remove the direct dependency on the rpc module, the
  constructor needs a function which actually does the remote
  call. This will usually be rpc.call_hooks_runner, but any function
  which behaves the same works.

  """
  def __init__(self, callfn, proc, lu):
    self.callfn = callfn
    self.proc = proc
    self.lu = lu
    self.op = lu.op
    self.env, node_list_pre, node_list_post = self._BuildEnv()
    self.node_list = {constants.HOOKS_PHASE_PRE: node_list_pre,
                      constants.HOOKS_PHASE_POST: node_list_post}

  def _BuildEnv(self):
    """Compute the environment and the target nodes.

    Based on the opcode and the current node list, this builds the
    environment for the hooks and the target node list for the run.

    """
    env = {
      "PATH": "/sbin:/bin:/usr/sbin:/usr/bin",
      "GANETI_HOOKS_VERSION": constants.HOOKS_VERSION,
      "GANETI_OP_CODE": self.op.OP_ID,
      "GANETI_OBJECT_TYPE": self.lu.HTYPE,
      "GANETI_DATA_DIR": constants.DATA_DIR,
      }

    if self.lu.HPATH is not None:
      lu_env, lu_nodes_pre, lu_nodes_post = self.lu.BuildHooksEnv()
      if lu_env:
        for key in lu_env:
          env["GANETI_" + key] = lu_env[key]
    else:
      lu_nodes_pre = lu_nodes_post = []

    return env, frozenset(lu_nodes_pre), frozenset(lu_nodes_post)

  def _RunWrapper(self, node_list, hpath, phase):
    """Simple wrapper over self.callfn.

    This method fixes the environment before doing the rpc call.

    """
    env = self.env.copy()
    env["GANETI_HOOKS_PHASE"] = phase
    env["GANETI_HOOKS_PATH"] = hpath
    if self.lu.cfg is not None:
      env["GANETI_CLUSTER"] = self.lu.cfg.GetClusterName()
      env["GANETI_MASTER"] = self.lu.cfg.GetMasterNode()

    env = dict([(str(key), str(val)) for key, val in env.iteritems()])

    return self.callfn(node_list, hpath, phase, env)

  def RunPhase(self, phase):
    """Run all the scripts for a phase.

    This is the main function of the HookMaster.

    @param phase: one of L{constants.HOOKS_PHASE_POST} or
        L{constants.HOOKS_PHASE_PRE}; it denotes the hooks phase
    @return: the processed results of the hooks multi-node rpc call
    @raise errors.HooksFailure: on communication failure to the nodes

    """
    if not self.node_list[phase]:
      # empty node list, we should not attempt to run this as either
      # we're in the cluster init phase and the rpc client part can't
      # even attempt to run, or this LU doesn't do hooks at all
      return
    hpath = self.lu.HPATH
    results = self._RunWrapper(self.node_list[phase], hpath, phase)
    if phase == constants.HOOKS_PHASE_PRE:
      errs = []
      if not results:
        raise errors.HooksFailure("Communication failure")
      for node_name in results:
        res = results[node_name]
        if res is False or not isinstance(res, list):
          self.proc.LogWarning("Communication failure to node %s" % node_name)
          continue
        for script, hkr, output in res:
          if hkr == constants.HKR_FAIL:
            output = output.strip().encode("string_escape")
            errs.append((node_name, script, output))
      if errs:
        raise errors.HooksAbort(errs)
    return results

  def RunConfigUpdate(self):
    """Run the special configuration update hook

    This is a special hook that runs only on the master after each
    top-level LI if the configuration has been updated.

    """
    phase = constants.HOOKS_PHASE_POST
    hpath = constants.HOOKS_NAME_CFGUPDATE
    nodes = [self.lu.cfg.GetMasterNode()]
    results = self._RunWrapper(nodes, hpath, phase)
