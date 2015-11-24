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


"""Module implementing the logic for running hooks.

"""

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import compat
from ganeti import pathutils


def RpcResultsToHooksResults(rpc_results):
  """Function to convert RPC results to the format expected by HooksMaster.

  @type rpc_results: dict(node: L{rpc.RpcResult})
  @param rpc_results: RPC results
  @rtype: dict(node: (fail_msg, offline, hooks_results))
  @return: RPC results unpacked according to the format expected by
    L({hooksmaster.HooksMaster}

  """
  return dict((node, (rpc_res.fail_msg, rpc_res.offline, rpc_res.payload))
              for (node, rpc_res) in rpc_results.items())


class HooksMaster(object):
  def __init__(self, opcode, hooks_path, nodes, hooks_execution_fn,
               hooks_results_adapt_fn, build_env_fn, prepare_post_nodes_fn,
               log_fn, htype=None, cluster_name=None, master_name=None,
               master_uuid=None, job_id=None):
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
    @type prepare_post_nodes_fn: function that take a list of node UUIDs and
      returns a list of node UUIDs
    @param prepare_post_nodes_fn: function that is invoked right before
      executing post hooks and can change the list of node UUIDs to run the post
      hooks on
    @type log_fn: function that accepts a string
    @param log_fn: logging function
    @type htype: string or None
    @param htype: None or one of L{constants.HTYPE_CLUSTER},
     L{constants.HTYPE_NODE}, L{constants.HTYPE_INSTANCE}
    @type cluster_name: string
    @param cluster_name: name of the cluster
    @type master_name: string
    @param master_name: name of the master
    @type master_uuid: string
    @param master_uuid: uuid of the master
    @type job_id: int
    @param job_id: the id of the job process (used in global post hooks)

    """
    self.opcode = opcode
    self.hooks_path = hooks_path
    self.hooks_execution_fn = hooks_execution_fn
    self.hooks_results_adapt_fn = hooks_results_adapt_fn
    self.build_env_fn = build_env_fn
    self.prepare_post_nodes_fn = prepare_post_nodes_fn
    self.log_fn = log_fn
    self.htype = htype
    self.cluster_name = cluster_name
    self.master_name = master_name
    self.master_uuid = master_uuid
    self.job_id = job_id

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

  def _CheckParamsAndExecHooks(self, node_list, hpath, phase, env):
    """Check rpc parameters and call hooks_execution_fn (rpc).

    """
    if node_list is None or not node_list:
      return {}

    # Convert everything to strings
    env = dict([(str(key), str(val)) for key, val in env.iteritems()])
    assert compat.all(key == "PATH" or key.startswith("GANETI_")
                      for key in env)
    for node in node_list:
      assert utils.UUID_RE.match(node), "Invalid node uuid %s" % node

    return self.hooks_execution_fn(node_list, hpath, phase, env)

  def _RunWrapper(self, node_list, hpath, phase, phase_env, is_global=False,
                  post_status=None):
    """Simple wrapper over self.callfn.

    This method fixes the environment before executing the hooks.

    """
    env = {
      "PATH": constants.HOOKS_PATH,
      "GANETI_HOOKS_VERSION": constants.HOOKS_VERSION,
      "GANETI_OP_CODE": self.opcode,
      "GANETI_DATA_DIR": pathutils.DATA_DIR,
      "GANETI_HOOKS_PHASE": phase,
      "GANETI_HOOKS_PATH": hpath,
      }

    if self.htype:
      env["GANETI_OBJECT_TYPE"] = self.htype

    if self.cluster_name is not None:
      env["GANETI_CLUSTER"] = self.cluster_name

    if self.master_name is not None:
      env["GANETI_MASTER"] = self.master_name

    if self.job_id and is_global:
      env["GANETI_JOB_ID"] = self.job_id
    if phase == constants.HOOKS_PHASE_POST and is_global:
      assert post_status is not None
      env["GANETI_POST_STATUS"] = post_status

    if phase_env:
      env = utils.algo.JoinDisjointDicts(env, phase_env)

    if not is_global:
      return self._CheckParamsAndExecHooks(node_list, hpath, phase, env)

    # For global hooks, we need to send different env values to master and
    # to the others
    ret = dict()
    env["GANETI_IS_MASTER"] = constants.GLOBAL_HOOKS_MASTER
    master_set = frozenset([self.master_uuid])
    ret.update(self._CheckParamsAndExecHooks(master_set, hpath, phase, env))

    if node_list:
      node_list = frozenset(set(node_list) - master_set)
    env["GANETI_IS_MASTER"] = constants.GLOBAL_HOOKS_NOT_MASTER
    ret.update(self._CheckParamsAndExecHooks(node_list, hpath, phase, env))

    return ret

  def RunPhase(self, phase, node_uuids=None, is_global=False,
               post_status=None):
    """Run all the scripts for a phase.

    This is the main function of the HookMaster.
    It executes self.hooks_execution_fn, and after running
    self.hooks_results_adapt_fn on its results it expects them to be in the
    form {node_name: (fail_msg, [(script, result, output), ...]}).

    @param phase: one of L{constants.HOOKS_PHASE_POST} or
        L{constants.HOOKS_PHASE_PRE}; it denotes the hooks phase
    @param node_uuids: overrides the predefined list of nodes for the given
        phase
    @param is_global: whether global or per-opcode hooks should be executed
    @param post_status: the job execution status for the global post hooks
    @return: the processed results of the hooks multi-node rpc call
    @raise errors.HooksFailure: on communication failure to the nodes
    @raise errors.HooksAbort: on failure of one of the hooks

    """
    if phase == constants.HOOKS_PHASE_PRE:
      if node_uuids is None:
        node_uuids = self.pre_nodes
      env = self.pre_env
    elif phase == constants.HOOKS_PHASE_POST:
      if node_uuids is None:
        node_uuids = self.post_nodes
        if node_uuids is not None and self.prepare_post_nodes_fn is not None:
          node_uuids = frozenset(self.prepare_post_nodes_fn(list(node_uuids)))
      env = self._BuildEnv(phase)
    else:
      raise AssertionError("Unknown phase '%s'" % phase)

    if not node_uuids and not is_global:
      # empty node list, we should not attempt to run this as either
      # we're in the cluster init phase and the rpc client part can't
      # even attempt to run, or this LU doesn't do hooks at all
      return

    hooks_path = constants.GLOBAL_HOOKS_DIR if is_global else self.hooks_path
    results = self._RunWrapper(node_uuids, hooks_path, phase, env, is_global,
                               post_status)
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
    nodes = [self.master_uuid]
    self._RunWrapper(nodes, hpath, phase, self.pre_env)

  @staticmethod
  def BuildFromLu(hooks_execution_fn, lu, job_id=None):
    if lu.HPATH is None:
      nodes = (None, None)
    else:
      hooks_nodes = lu.BuildHooksNodes()
      if len(hooks_nodes) != 2:
        raise errors.ProgrammerError(
          "LogicalUnit.BuildHooksNodes must return a 2-tuple")
      nodes = (frozenset(hooks_nodes[0]), frozenset(hooks_nodes[1]))

    master_name = cluster_name = None
    if lu.cfg:
      master_name = lu.cfg.GetMasterNodeName()
      master_uuid = lu.cfg.GetMasterNode()
      cluster_name = lu.cfg.GetClusterName()

    return HooksMaster(lu.op.OP_ID, lu.HPATH, nodes, hooks_execution_fn,
                       RpcResultsToHooksResults, lu.BuildHooksEnv,
                       lu.PreparePostHookNodes, lu.LogWarning, lu.HTYPE,
                       cluster_name, master_name, master_uuid, job_id)


def ExecGlobalPostHooks(opcode, master_name, rpc_runner, log_fn,
                        cluster_name, master_uuid, job_id, status):
  """ Build hooks manager and execute global post hooks just on the master

  """
  hm = HooksMaster(opcode, hooks_path=None, nodes=([], [master_uuid]),
                   hooks_execution_fn=rpc_runner,
                   hooks_results_adapt_fn=RpcResultsToHooksResults,
                   build_env_fn=None, prepare_post_nodes_fn=None,
                   log_fn=log_fn, htype=None, cluster_name=cluster_name,
                   master_name=master_name, master_uuid=master_uuid,
                   job_id=job_id)
  hm.RunPhase(constants.HOOKS_PHASE_POST, is_global=True, post_status=status)
