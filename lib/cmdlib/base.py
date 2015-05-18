#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Base classes and functions for cmdlib."""

import logging

from ganeti import errors
from ganeti import constants
from ganeti import locking
from ganeti import query
from ganeti import utils
from ganeti.cmdlib.common import ExpandInstanceUuidAndName


class ResultWithJobs(object):
  """Data container for LU results with jobs.

  Instances of this class returned from L{LogicalUnit.Exec} will be recognized
  by L{mcpu._ProcessResult}. The latter will then submit the jobs
  contained in the C{jobs} attribute and include the job IDs in the opcode
  result.

  """
  def __init__(self, jobs, **kwargs):
    """Initializes this class.

    Additional return values can be specified as keyword arguments.

    @type jobs: list of lists of L{opcode.OpCode}
    @param jobs: A list of lists of opcode objects

    """
    self.jobs = jobs
    self.other = kwargs


class LUWConfdClient(object):
  """Wrapper class for wconfd client calls from LUs.

  Correctly updates the cache of the LU's owned locks
  when leaving. Also transparently adds the context
  for resource requests.

  """
  def __init__(self, lu):
    self.lu = lu

  def TryUpdateLocks(self, req):
    self.lu.wconfd.Client().TryUpdateLocks(self.lu.wconfdcontext, req)
    self.lu.wconfdlocks = \
      self.lu.wconfd.Client().ListLocks(self.lu.wconfdcontext)

  def DownGradeLocksLevel(self, level):
    self.lu.wconfd.Client().DownGradeLocksLevel(self.lu.wconfdcontext, level)
    self.lu.wconfdlocks = \
      self.lu.wconfd.Client().ListLocks(self.lu.wconfdcontext)

  def FreeLocksLevel(self, level):
    self.lu.wconfd.Client().FreeLocksLevel(self.lu.wconfdcontext, level)
    self.lu.wconfdlocks = \
      self.lu.wconfd.Client().ListLocks(self.lu.wconfdcontext)


class LogicalUnit(object): # pylint: disable=R0902
  """Logical Unit base class.

  Subclasses must follow these rules:
    - implement ExpandNames
    - implement CheckPrereq (except when tasklets are used)
    - implement Exec (except when tasklets are used)
    - implement BuildHooksEnv
    - implement BuildHooksNodes
    - redefine HPATH and HTYPE
    - optionally redefine their run requirements:
        REQ_BGL: the LU needs to hold the Big Ganeti Lock exclusively

  Note that all commands require root permissions.

  @ivar dry_run_result: the value (if any) that will be returned to the caller
      in dry-run mode (signalled by opcode dry_run parameter)

  """
  # This class has more than 20 instance variables, but at most have sensible
  # defaults and are used in a declartive way, this is not a problem.

  HPATH = None
  HTYPE = None
  REQ_BGL = True

  def __init__(self, processor, op, cfg,
               rpc_runner, wconfdcontext, wconfd):
    """Constructor for LogicalUnit.

    This needs to be overridden in derived classes in order to check op
    validity.

    @type wconfdcontext: (int, string)
    @param wconfdcontext: the identity of the logical unit to represent itself
        to wconfd when asking for resources; it is given as job id and livelock
        file.
    @param wconfd: the wconfd class to use; dependency injection to allow
        testability.

    """
    self.proc = processor
    self.op = op
    self.cfg = cfg
    self.wconfdlocks = []
    self.wconfdcontext = wconfdcontext
    self.rpc = rpc_runner
    self.wconfd = wconfd # wconfd module to use, for testing

    # Dictionaries used to declare locking needs to mcpu
    self.needed_locks = None
    self.share_locks = dict.fromkeys(locking.LEVELS, 0)
    self.opportunistic_locks = dict.fromkeys(locking.LEVELS, False)
    self.opportunistic_locks_count = dict.fromkeys(locking.LEVELS, 1)
    self.dont_collate_locks = dict.fromkeys(locking.LEVELS, False)

    self.add_locks = {}

    # Used to force good behavior when calling helper functions
    self.recalculate_locks = {}

    # logging
    self.Log = processor.Log # pylint: disable=C0103
    self.LogWarning = processor.LogWarning # pylint: disable=C0103
    self.LogInfo = processor.LogInfo # pylint: disable=C0103
    self.LogStep = processor.LogStep # pylint: disable=C0103
    # support for dry-run
    self.dry_run_result = None
    # support for generic debug attribute
    if (not hasattr(self.op, "debug_level") or
        not isinstance(self.op.debug_level, int)):
      self.op.debug_level = 0

    # Tasklets
    self.tasklets = None

    # Validate opcode parameters and set defaults
    self.op.Validate(True)

    self.CheckArguments()

  def WConfdClient(self):
    return LUWConfdClient(self)

  def owned_locks(self, level):
    """Return the list of locks owned by the LU at a given level.

    This method assumes that is field wconfdlocks is set correctly
    by mcpu.

    """
    levelprefix = "%s/" % (locking.LEVEL_NAMES[level],)
    locks = set([lock[0][len(levelprefix):]
                for lock in self.wconfdlocks
                if lock[0].startswith(levelprefix)])
    expand_fns = {
      locking.LEVEL_CLUSTER: (lambda: [locking.BGL]),
      locking.LEVEL_INSTANCE:
        lambda: self.cfg.GetInstanceNames(self.cfg.GetInstanceList()),
      locking.LEVEL_NODEGROUP: self.cfg.GetNodeGroupList,
      locking.LEVEL_NODE: self.cfg.GetNodeList,
      locking.LEVEL_NODE_RES: self.cfg.GetNodeList,
      locking.LEVEL_NETWORK: self.cfg.GetNetworkList,
      }
    if locking.LOCKSET_NAME in locks:
      return expand_fns[level]()
    else:
      return locks

  def release_request(self, level, names):
    """Return a request to release the specified locks of the given level.

    Correctly break up the group lock to do so.

    """
    levelprefix = "%s/" % (locking.LEVEL_NAMES[level],)
    release = [[levelprefix + lock, "release"] for lock in names]

    # if we break up the set-lock, make sure we ask for the rest of it.
    setlock = levelprefix + locking.LOCKSET_NAME
    if [setlock, "exclusive"] in self.wconfdlocks:
      owned = self.owned_locks(level)
      request = [[levelprefix + lock, "exclusive"]
                 for lock in owned
                 if lock not in names]
    elif [setlock, "shared"] in self.wconfdlocks:
      owned = self.owned_locks(level)
      request = [[levelprefix + lock, "shared"]
                 for lock in owned
                 if lock not in names]
    else:
      request = []

    return release + [[setlock, "release"]] + request

  def CheckArguments(self):
    """Check syntactic validity for the opcode arguments.

    This method is for doing a simple syntactic check and ensure
    validity of opcode parameters, without any cluster-related
    checks. While the same can be accomplished in ExpandNames and/or
    CheckPrereq, doing these separate is better because:

      - ExpandNames is left as as purely a lock-related function
      - CheckPrereq is run after we have acquired locks (and possible
        waited for them)

    The function is allowed to change the self.op attribute so that
    later methods can no longer worry about missing parameters.

    """
    pass

  def ExpandNames(self):
    """Expand names for this LU.

    This method is called before starting to execute the opcode, and it should
    update all the parameters of the opcode to their canonical form (e.g. a
    short node name must be fully expanded after this method has successfully
    completed). This way locking, hooks, logging, etc. can work correctly.

    LUs which implement this method must also populate the self.needed_locks
    member, as a dict with lock levels as keys, and a list of needed lock names
    as values. Rules:

      - use an empty dict if you don't need any lock
      - if you don't need any lock at a particular level omit that
        level (note that in this case C{DeclareLocks} won't be called
        at all for that level)
      - if you need locks at a level, but you can't calculate it in
        this function, initialise that level with an empty list and do
        further processing in L{LogicalUnit.DeclareLocks} (see that
        function's docstring)
      - don't put anything for the BGL level
      - if you want all locks at a level use L{locking.ALL_SET} as a value

    If you need to share locks (rather than acquire them exclusively) at one
    level you can modify self.share_locks, setting a true value (usually 1) for
    that level. By default locks are not shared.

    This function can also define a list of tasklets, which then will be
    executed in order instead of the usual LU-level CheckPrereq and Exec
    functions, if those are not defined by the LU.

    Examples::

      # Acquire all nodes and one instance
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_INSTANCE: ['instance1.example.com'],
      }
      # Acquire just two nodes
      self.needed_locks = {
        locking.LEVEL_NODE: ['node1-uuid', 'node2-uuid'],
      }
      # Acquire no locks
      self.needed_locks = {} # No, you can't leave it to the default value None

    """
    # The implementation of this method is mandatory only if the new LU is
    # concurrent, so that old LUs don't need to be changed all at the same
    # time.
    if self.REQ_BGL:
      self.needed_locks = {} # Exclusive LUs don't need locks.
    else:
      raise NotImplementedError

  def DeclareLocks(self, level):
    """Declare LU locking needs for a level

    While most LUs can just declare their locking needs at ExpandNames time,
    sometimes there's the need to calculate some locks after having acquired
    the ones before. This function is called just before acquiring locks at a
    particular level, but after acquiring the ones at lower levels, and permits
    such calculations. It can be used to modify self.needed_locks, and by
    default it does nothing.

    This function is only called if you have something already set in
    self.needed_locks for the level.

    @param level: Locking level which is going to be locked
    @type level: member of L{ganeti.locking.LEVELS}

    """

  def CheckPrereq(self):
    """Check prerequisites for this LU.

    This method should check that the prerequisites for the execution
    of this LU are fulfilled. It can do internode communication, but
    it should be idempotent - no cluster or system changes are
    allowed.

    The method should raise errors.OpPrereqError in case something is
    not fulfilled. Its return value is ignored.

    This method should also update all the parameters of the opcode to
    their canonical form if it hasn't been done by ExpandNames before.

    """
    if self.tasklets is not None:
      for (idx, tl) in enumerate(self.tasklets):
        logging.debug("Checking prerequisites for tasklet %s/%s",
                      idx + 1, len(self.tasklets))
        tl.CheckPrereq()
    else:
      pass

  def Exec(self, feedback_fn):
    """Execute the LU.

    This method should implement the actual work. It should raise
    errors.OpExecError for failures that are somewhat dealt with in
    code, or expected.

    """
    if self.tasklets is not None:
      for (idx, tl) in enumerate(self.tasklets):
        logging.debug("Executing tasklet %s/%s", idx + 1, len(self.tasklets))
        tl.Exec(feedback_fn)
    else:
      raise NotImplementedError

  def PrepareRetry(self, _feedback_fn):
    """Prepare the LU to run again.

    This method is called if the Exec failed for temporarily lacking resources.
    It is expected to change the state of the LU so that it can be tried again,
    and also change its locking policy to acquire more resources to have a
    better chance of suceeding in the retry.

    """
    # pylint: disable=R0201
    raise errors.OpRetryNotSupportedError()

  def BuildHooksEnv(self):
    """Build hooks environment for this LU.

    @rtype: dict
    @return: Dictionary containing the environment that will be used for
      running the hooks for this LU. The keys of the dict must not be prefixed
      with "GANETI_"--that'll be added by the hooks runner. The hooks runner
      will extend the environment with additional variables. If no environment
      should be defined, an empty dictionary should be returned (not C{None}).
    @note: If the C{HPATH} attribute of the LU class is C{None}, this function
      will not be called.

    """
    raise NotImplementedError

  def BuildHooksNodes(self):
    """Build list of nodes to run LU's hooks.

    @rtype: tuple; (list, list)
    @return: Tuple containing a list of node UUIDs on which the hook
      should run before the execution and a list of node UUIDs on which the
      hook should run after the execution.
      No nodes should be returned as an empty list (and not None).
    @note: If the C{HPATH} attribute of the LU class is C{None}, this function
      will not be called.

    """
    raise NotImplementedError

  def PreparePostHookNodes(self, post_hook_node_uuids):
    """Extend list of nodes to run the post LU hook.

    This method allows LUs to change the list of node UUIDs on which the
    post hook should run after the LU has been executed but before the post
    hook is run.

    @type post_hook_node_uuids: list
    @param post_hook_node_uuids: The initial list of node UUIDs to run the
      post hook on, as returned by L{BuildHooksNodes}.
    @rtype: list
    @return: list of node UUIDs on which the post hook should run. The default
      implementation returns the passed in C{post_hook_node_uuids}, but
      custom implementations can choose to alter the list.

    """
    # For consistency with HooksCallBack we ignore the "could be a function"
    # warning
    # pylint: disable=R0201
    return post_hook_node_uuids

  def HooksCallBack(self, phase, hook_results, feedback_fn, lu_result):
    """Notify the LU about the results of its hooks.

    This method is called every time a hooks phase is executed, and notifies
    the Logical Unit about the hooks' result. The LU can then use it to alter
    its result based on the hooks.  By default the method does nothing and the
    previous result is passed back unchanged but any LU can define it if it
    wants to use the local cluster hook-scripts somehow.

    @param phase: one of L{constants.HOOKS_PHASE_POST} or
        L{constants.HOOKS_PHASE_PRE}; it denotes the hooks phase
    @param hook_results: the results of the multi-node hooks rpc call
    @param feedback_fn: function used send feedback back to the caller
    @param lu_result: the previous Exec result this LU had, or None
        in the PRE phase
    @return: the new Exec result, based on the previous result
        and hook results

    """
    # API must be kept, thus we ignore the unused argument and could
    # be a function warnings
    # pylint: disable=W0613,R0201
    return lu_result

  def _ExpandAndLockInstance(self, allow_forthcoming=False):
    """Helper function to expand and lock an instance.

    Many LUs that work on an instance take its name in self.op.instance_name
    and need to expand it and then declare the expanded name for locking. This
    function does it, and then updates self.op.instance_name to the expanded
    name. It also initializes needed_locks as a dict, if this hasn't been done
    before.

    @param allow_forthcoming: if True, do not insist that the intsance be real;
        the default behaviour is to raise a prerequisite error if the specified
        instance is forthcoming.

    """
    if self.needed_locks is None:
      self.needed_locks = {}
    else:
      assert locking.LEVEL_INSTANCE not in self.needed_locks, \
        "_ExpandAndLockInstance called with instance-level locks set"
    (self.op.instance_uuid, self.op.instance_name) = \
      ExpandInstanceUuidAndName(self.cfg, self.op.instance_uuid,
                                self.op.instance_name)
    self.needed_locks[locking.LEVEL_INSTANCE] = self.op.instance_name
    if not allow_forthcoming:
      if self.cfg.GetInstanceInfo(self.op.instance_uuid).forthcoming:
        raise errors.OpPrereqError(
          "forthcoming instances not supported for this operation")

  def _LockInstancesNodes(self, primary_only=False,
                          level=locking.LEVEL_NODE):
    """Helper function to declare instances' nodes for locking.

    This function should be called after locking one or more instances to lock
    their nodes. Its effect is populating self.needed_locks[locking.LEVEL_NODE]
    with all primary or secondary nodes for instances already locked and
    present in self.needed_locks[locking.LEVEL_INSTANCE].

    It should be called from DeclareLocks, and for safety only works if
    self.recalculate_locks[locking.LEVEL_NODE] is set.

    In the future it may grow parameters to just lock some instance's nodes, or
    to just lock primaries or secondary nodes, if needed.

    If should be called in DeclareLocks in a way similar to::

      if level == locking.LEVEL_NODE:
        self._LockInstancesNodes()

    @type primary_only: boolean
    @param primary_only: only lock primary nodes of locked instances
    @param level: Which lock level to use for locking nodes

    """
    assert level in self.recalculate_locks, \
      "_LockInstancesNodes helper function called with no nodes to recalculate"

    # TODO: check if we're really been called with the instance locks held

    # For now we'll replace self.needed_locks[locking.LEVEL_NODE], but in the
    # future we might want to have different behaviors depending on the value
    # of self.recalculate_locks[locking.LEVEL_NODE]
    wanted_node_uuids = []
    locked_i = self.owned_locks(locking.LEVEL_INSTANCE)
    for _, instance in self.cfg.GetMultiInstanceInfoByName(locked_i):
      wanted_node_uuids.append(instance.primary_node)
      if not primary_only:
        wanted_node_uuids.extend(
          self.cfg.GetInstanceSecondaryNodes(instance.uuid))

    if self.recalculate_locks[level] == constants.LOCKS_REPLACE:
      self.needed_locks[level] = wanted_node_uuids
    elif self.recalculate_locks[level] == constants.LOCKS_APPEND:
      self.needed_locks[level].extend(wanted_node_uuids)
    else:
      raise errors.ProgrammerError("Unknown recalculation mode")

    del self.recalculate_locks[level]

  def AssertReleasedLocks(self, level):
    """Raise AssertionError if the LU holds some locks of the given level.

    """
    assert not self.owned_locks(level)


class NoHooksLU(LogicalUnit): # pylint: disable=W0223
  """Simple LU which runs no hooks.

  This LU is intended as a parent for other LogicalUnits which will
  run no hooks, in order to reduce duplicate code.

  """
  HPATH = None
  HTYPE = None

  def BuildHooksEnv(self):
    """Empty BuildHooksEnv for NoHooksLu.

    This just raises an error.

    """
    raise AssertionError("BuildHooksEnv called for NoHooksLUs")

  def BuildHooksNodes(self):
    """Empty BuildHooksNodes for NoHooksLU.

    """
    raise AssertionError("BuildHooksNodes called for NoHooksLU")

  def PreparePostHookNodes(self, post_hook_node_uuids):
    """Empty PreparePostHookNodes for NoHooksLU.

    """
    raise AssertionError("PreparePostHookNodes called for NoHooksLU")


class Tasklet(object):
  """Tasklet base class.

  Tasklets are subcomponents for LUs. LUs can consist entirely of tasklets or
  they can mix legacy code with tasklets. Locking needs to be done in the LU,
  tasklets know nothing about locks.

  Subclasses must follow these rules:
    - Implement CheckPrereq
    - Implement Exec

  """
  def __init__(self, lu):
    self.lu = lu

    # Shortcuts
    self.cfg = lu.cfg
    self.rpc = lu.rpc

  def CheckPrereq(self):
    """Check prerequisites for this tasklets.

    This method should check whether the prerequisites for the execution of
    this tasklet are fulfilled. It can do internode communication, but it
    should be idempotent - no cluster or system changes are allowed.

    The method should raise errors.OpPrereqError in case something is not
    fulfilled. Its return value is ignored.

    This method should also update all parameters to their canonical form if it
    hasn't been done before.

    """
    pass

  def Exec(self, feedback_fn):
    """Execute the tasklet.

    This method should implement the actual work. It should raise
    errors.OpExecError for failures that are somewhat dealt with in code, or
    expected.

    """
    raise NotImplementedError


class QueryBase(object):
  """Base for query utility classes.

  """
  #: Attribute holding field definitions
  FIELDS = None

  #: Field to sort by
  SORT_FIELD = "name"

  def __init__(self, qfilter, fields, use_locking):
    """Initializes this class.

    """
    self.use_locking = use_locking

    self.query = query.Query(self.FIELDS, fields, qfilter=qfilter,
                             namefield=self.SORT_FIELD)
    self.requested_data = self.query.RequestedData()
    self.names = self.query.RequestedNames()

    # Sort only if no names were requested
    self.sort_by_name = not self.names

    self.do_locking = None
    self.wanted = None

  def _GetNames(self, lu, all_names, lock_level):
    """Helper function to determine names asked for in the query.

    """
    if self.do_locking:
      names = lu.owned_locks(lock_level)
    else:
      names = all_names

    if self.wanted == locking.ALL_SET:
      assert not self.names
      # caller didn't specify names, so ordering is not important
      return utils.NiceSort(names)

    # caller specified names and we must keep the same order
    assert self.names

    missing = set(self.wanted).difference(names)
    if missing:
      raise errors.OpExecError("Some items were removed before retrieving"
                               " their data: %s" % missing)

    # Return expanded names
    return self.wanted

  def ExpandNames(self, lu):
    """Expand names for this query.

    See L{LogicalUnit.ExpandNames}.

    """
    raise NotImplementedError()

  def DeclareLocks(self, lu, level):
    """Declare locks for this query.

    See L{LogicalUnit.DeclareLocks}.

    """
    raise NotImplementedError()

  def _GetQueryData(self, lu):
    """Collects all data for this query.

    @return: Query data object

    """
    raise NotImplementedError()

  def NewStyleQuery(self, lu):
    """Collect data and execute query.

    """
    return query.GetQueryResponse(self.query, self._GetQueryData(lu),
                                  sort_by_name=self.sort_by_name)

  def OldStyleQuery(self, lu):
    """Collect data and execute query.

    """
    return self.query.OldStyleQuery(self._GetQueryData(lu),
                                    sort_by_name=self.sort_by_name)
