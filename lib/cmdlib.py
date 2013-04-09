#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Module implementing the master-side code."""

# pylint: disable=W0201,C0302

# W0201 since most LU attributes are defined in CheckPrereq or similar
# functions

# C0302: since we have waaaay too many lines in this module

import os
import os.path
import time
import re
import logging
import copy
import OpenSSL
import socket
import tempfile
import shutil
import itertools
import operator

from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti import constants
from ganeti import objects
from ganeti import ssconf
from ganeti import uidpool
from ganeti import compat
from ganeti import masterd
from ganeti import netutils
from ganeti import query
from ganeti import qlang
from ganeti import opcodes
from ganeti import ht
from ganeti import rpc
from ganeti import runtime
from ganeti import pathutils
from ganeti import vcluster
from ganeti import network
from ganeti.masterd import iallocator

import ganeti.masterd.instance # pylint: disable=W0611


# States of instance
INSTANCE_DOWN = [constants.ADMINST_DOWN]
INSTANCE_ONLINE = [constants.ADMINST_DOWN, constants.ADMINST_UP]
INSTANCE_NOT_RUNNING = [constants.ADMINST_DOWN, constants.ADMINST_OFFLINE]

#: Instance status in which an instance can be marked as offline/online
CAN_CHANGE_INSTANCE_OFFLINE = (frozenset(INSTANCE_DOWN) | frozenset([
  constants.ADMINST_OFFLINE,
  ]))


class ResultWithJobs:
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


class LogicalUnit(object):
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
  HPATH = None
  HTYPE = None
  REQ_BGL = True

  def __init__(self, processor, op, context, rpc_runner):
    """Constructor for LogicalUnit.

    This needs to be overridden in derived classes in order to check op
    validity.

    """
    self.proc = processor
    self.op = op
    self.cfg = context.cfg
    self.glm = context.glm
    # readability alias
    self.owned_locks = context.glm.list_owned
    self.context = context
    self.rpc = rpc_runner

    # Dictionaries used to declare locking needs to mcpu
    self.needed_locks = None
    self.share_locks = dict.fromkeys(locking.LEVELS, 0)
    self.opportunistic_locks = dict.fromkeys(locking.LEVELS, False)

    self.add_locks = {}
    self.remove_locks = {}

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
        locking.LEVEL_NODE: ['node1.example.com', 'node2.example.com'],
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
    @return: Tuple containing a list of node names on which the hook
      should run before the execution and a list of node names on which the
      hook should run after the execution. No nodes should be returned as an
      empty list (and not None).
    @note: If the C{HPATH} attribute of the LU class is C{None}, this function
      will not be called.

    """
    raise NotImplementedError

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

  def _ExpandAndLockInstance(self):
    """Helper function to expand and lock an instance.

    Many LUs that work on an instance take its name in self.op.instance_name
    and need to expand it and then declare the expanded name for locking. This
    function does it, and then updates self.op.instance_name to the expanded
    name. It also initializes needed_locks as a dict, if this hasn't been done
    before.

    """
    if self.needed_locks is None:
      self.needed_locks = {}
    else:
      assert locking.LEVEL_INSTANCE not in self.needed_locks, \
        "_ExpandAndLockInstance called with instance-level locks set"
    self.op.instance_name = _ExpandInstanceName(self.cfg,
                                                self.op.instance_name)
    self.needed_locks[locking.LEVEL_INSTANCE] = self.op.instance_name

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
    wanted_nodes = []
    locked_i = self.owned_locks(locking.LEVEL_INSTANCE)
    for _, instance in self.cfg.GetMultiInstanceInfo(locked_i):
      wanted_nodes.append(instance.primary_node)
      if not primary_only:
        wanted_nodes.extend(instance.secondary_nodes)

    if self.recalculate_locks[level] == constants.LOCKS_REPLACE:
      self.needed_locks[level] = wanted_nodes
    elif self.recalculate_locks[level] == constants.LOCKS_APPEND:
      self.needed_locks[level].extend(wanted_nodes)
    else:
      raise errors.ProgrammerError("Unknown recalculation mode")

    del self.recalculate_locks[level]


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


class Tasklet:
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


class _QueryBase:
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
    assert not self.do_locking or lu.glm.is_owned(lock_level)

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


def _ShareAll():
  """Returns a dict declaring all lock levels shared.

  """
  return dict.fromkeys(locking.LEVELS, 1)


def _AnnotateDiskParams(instance, devs, cfg):
  """Little helper wrapper to the rpc annotation method.

  @param instance: The instance object
  @type devs: List of L{objects.Disk}
  @param devs: The root devices (not any of its children!)
  @param cfg: The config object
  @returns The annotated disk copies
  @see L{rpc.AnnotateDiskParams}

  """
  return rpc.AnnotateDiskParams(instance.disk_template, devs,
                                cfg.GetInstanceDiskParams(instance))


def _CheckInstancesNodeGroups(cfg, instances, owned_groups, owned_nodes,
                              cur_group_uuid):
  """Checks if node groups for locked instances are still correct.

  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @type instances: dict; string as key, L{objects.Instance} as value
  @param instances: Dictionary, instance name as key, instance object as value
  @type owned_groups: iterable of string
  @param owned_groups: List of owned groups
  @type owned_nodes: iterable of string
  @param owned_nodes: List of owned nodes
  @type cur_group_uuid: string or None
  @param cur_group_uuid: Optional group UUID to check against instance's groups

  """
  for (name, inst) in instances.items():
    assert owned_nodes.issuperset(inst.all_nodes), \
      "Instance %s's nodes changed while we kept the lock" % name

    inst_groups = _CheckInstanceNodeGroups(cfg, name, owned_groups)

    assert cur_group_uuid is None or cur_group_uuid in inst_groups, \
      "Instance %s has no node in group %s" % (name, cur_group_uuid)


def _CheckInstanceNodeGroups(cfg, instance_name, owned_groups,
                             primary_only=False):
  """Checks if the owned node groups are still correct for an instance.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type instance_name: string
  @param instance_name: Instance name
  @type owned_groups: set or frozenset
  @param owned_groups: List of currently owned node groups
  @type primary_only: boolean
  @param primary_only: Whether to check node groups for only the primary node

  """
  inst_groups = cfg.GetInstanceNodeGroups(instance_name, primary_only)

  if not owned_groups.issuperset(inst_groups):
    raise errors.OpPrereqError("Instance %s's node groups changed since"
                               " locks were acquired, current groups are"
                               " are '%s', owning groups '%s'; retry the"
                               " operation" %
                               (instance_name,
                                utils.CommaJoin(inst_groups),
                                utils.CommaJoin(owned_groups)),
                               errors.ECODE_STATE)

  return inst_groups


def _CheckNodeGroupInstances(cfg, group_uuid, owned_instances):
  """Checks if the instances in a node group are still correct.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type group_uuid: string
  @param group_uuid: Node group UUID
  @type owned_instances: set or frozenset
  @param owned_instances: List of currently owned instances

  """
  wanted_instances = cfg.GetNodeGroupInstances(group_uuid)
  if owned_instances != wanted_instances:
    raise errors.OpPrereqError("Instances in node group '%s' changed since"
                               " locks were acquired, wanted '%s', have '%s';"
                               " retry the operation" %
                               (group_uuid,
                                utils.CommaJoin(wanted_instances),
                                utils.CommaJoin(owned_instances)),
                               errors.ECODE_STATE)

  return wanted_instances


def _SupportsOob(cfg, node):
  """Tells if node supports OOB.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type node: L{objects.Node}
  @param node: The node
  @return: The OOB script if supported or an empty string otherwise

  """
  return cfg.GetNdParams(node)[constants.ND_OOB_PROGRAM]


def _IsExclusiveStorageEnabledNode(cfg, node):
  """Whether exclusive_storage is in effect for the given node.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type node: L{objects.Node}
  @param node: The node
  @rtype: bool
  @return: The effective value of exclusive_storage

  """
  return cfg.GetNdParams(node)[constants.ND_EXCLUSIVE_STORAGE]


def _IsExclusiveStorageEnabledNodeName(cfg, nodename):
  """Whether exclusive_storage is in effect for the given node.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type nodename: string
  @param nodename: The node
  @rtype: bool
  @return: The effective value of exclusive_storage
  @raise errors.OpPrereqError: if no node exists with the given name

  """
  ni = cfg.GetNodeInfo(nodename)
  if ni is None:
    raise errors.OpPrereqError("Invalid node name %s" % nodename,
                               errors.ECODE_NOENT)
  return _IsExclusiveStorageEnabledNode(cfg, ni)


def _CopyLockList(names):
  """Makes a copy of a list of lock names.

  Handles L{locking.ALL_SET} correctly.

  """
  if names == locking.ALL_SET:
    return locking.ALL_SET
  else:
    return names[:]


def _GetWantedNodes(lu, nodes):
  """Returns list of checked and expanded node names.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type nodes: list
  @param nodes: list of node names or None for all nodes
  @rtype: list
  @return: the list of nodes, sorted
  @raise errors.ProgrammerError: if the nodes parameter is wrong type

  """
  if nodes:
    return [_ExpandNodeName(lu.cfg, name) for name in nodes]

  return utils.NiceSort(lu.cfg.GetNodeList())


def _GetWantedInstances(lu, instances):
  """Returns list of checked and expanded instance names.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instances: list
  @param instances: list of instance names or None for all instances
  @rtype: list
  @return: the list of instances, sorted
  @raise errors.OpPrereqError: if the instances parameter is wrong type
  @raise errors.OpPrereqError: if any of the passed instances is not found

  """
  if instances:
    wanted = [_ExpandInstanceName(lu.cfg, name) for name in instances]
  else:
    wanted = utils.NiceSort(lu.cfg.GetInstanceList())
  return wanted


def _GetUpdatedParams(old_params, update_dict,
                      use_default=True, use_none=False):
  """Return the new version of a parameter dictionary.

  @type old_params: dict
  @param old_params: old parameters
  @type update_dict: dict
  @param update_dict: dict containing new parameter values, or
      constants.VALUE_DEFAULT to reset the parameter to its default
      value
  @param use_default: boolean
  @type use_default: whether to recognise L{constants.VALUE_DEFAULT}
      values as 'to be deleted' values
  @param use_none: boolean
  @type use_none: whether to recognise C{None} values as 'to be
      deleted' values
  @rtype: dict
  @return: the new parameter dictionary

  """
  params_copy = copy.deepcopy(old_params)
  for key, val in update_dict.iteritems():
    if ((use_default and val == constants.VALUE_DEFAULT) or
        (use_none and val is None)):
      try:
        del params_copy[key]
      except KeyError:
        pass
    else:
      params_copy[key] = val
  return params_copy


def _GetUpdatedIPolicy(old_ipolicy, new_ipolicy, group_policy=False):
  """Return the new version of a instance policy.

  @param group_policy: whether this policy applies to a group and thus
    we should support removal of policy entries

  """
  use_none = use_default = group_policy
  ipolicy = copy.deepcopy(old_ipolicy)
  for key, value in new_ipolicy.items():
    if key not in constants.IPOLICY_ALL_KEYS:
      raise errors.OpPrereqError("Invalid key in new ipolicy: %s" % key,
                                 errors.ECODE_INVAL)
    if key in constants.IPOLICY_ISPECS:
      ipolicy[key] = _GetUpdatedParams(old_ipolicy.get(key, {}), value,
                                       use_none=use_none,
                                       use_default=use_default)
      utils.ForceDictType(ipolicy[key], constants.ISPECS_PARAMETER_TYPES)
    else:
      if (not value or value == [constants.VALUE_DEFAULT] or
          value == constants.VALUE_DEFAULT):
        if group_policy:
          del ipolicy[key]
        else:
          raise errors.OpPrereqError("Can't unset ipolicy attribute '%s'"
                                     " on the cluster'" % key,
                                     errors.ECODE_INVAL)
      else:
        if key in constants.IPOLICY_PARAMETERS:
          # FIXME: we assume all such values are float
          try:
            ipolicy[key] = float(value)
          except (TypeError, ValueError), err:
            raise errors.OpPrereqError("Invalid value for attribute"
                                       " '%s': '%s', error: %s" %
                                       (key, value, err), errors.ECODE_INVAL)
        else:
          # FIXME: we assume all others are lists; this should be redone
          # in a nicer way
          ipolicy[key] = list(value)
  try:
    objects.InstancePolicy.CheckParameterSyntax(ipolicy, not group_policy)
  except errors.ConfigurationError, err:
    raise errors.OpPrereqError("Invalid instance policy: %s" % err,
                               errors.ECODE_INVAL)
  return ipolicy


def _UpdateAndVerifySubDict(base, updates, type_check):
  """Updates and verifies a dict with sub dicts of the same type.

  @param base: The dict with the old data
  @param updates: The dict with the new data
  @param type_check: Dict suitable to ForceDictType to verify correct types
  @returns: A new dict with updated and verified values

  """
  def fn(old, value):
    new = _GetUpdatedParams(old, value)
    utils.ForceDictType(new, type_check)
    return new

  ret = copy.deepcopy(base)
  ret.update(dict((key, fn(base.get(key, {}), value))
                  for key, value in updates.items()))
  return ret


def _MergeAndVerifyHvState(op_input, obj_input):
  """Combines the hv state from an opcode with the one of the object

  @param op_input: The input dict from the opcode
  @param obj_input: The input dict from the objects
  @return: The verified and updated dict

  """
  if op_input:
    invalid_hvs = set(op_input) - constants.HYPER_TYPES
    if invalid_hvs:
      raise errors.OpPrereqError("Invalid hypervisor(s) in hypervisor state:"
                                 " %s" % utils.CommaJoin(invalid_hvs),
                                 errors.ECODE_INVAL)
    if obj_input is None:
      obj_input = {}
    type_check = constants.HVSTS_PARAMETER_TYPES
    return _UpdateAndVerifySubDict(obj_input, op_input, type_check)

  return None


def _MergeAndVerifyDiskState(op_input, obj_input):
  """Combines the disk state from an opcode with the one of the object

  @param op_input: The input dict from the opcode
  @param obj_input: The input dict from the objects
  @return: The verified and updated dict
  """
  if op_input:
    invalid_dst = set(op_input) - constants.DS_VALID_TYPES
    if invalid_dst:
      raise errors.OpPrereqError("Invalid storage type(s) in disk state: %s" %
                                 utils.CommaJoin(invalid_dst),
                                 errors.ECODE_INVAL)
    type_check = constants.DSS_PARAMETER_TYPES
    if obj_input is None:
      obj_input = {}
    return dict((key, _UpdateAndVerifySubDict(obj_input.get(key, {}), value,
                                              type_check))
                for key, value in op_input.items())

  return None


def _ReleaseLocks(lu, level, names=None, keep=None):
  """Releases locks owned by an LU.

  @type lu: L{LogicalUnit}
  @param level: Lock level
  @type names: list or None
  @param names: Names of locks to release
  @type keep: list or None
  @param keep: Names of locks to retain

  """
  assert not (keep is not None and names is not None), \
         "Only one of the 'names' and the 'keep' parameters can be given"

  if names is not None:
    should_release = names.__contains__
  elif keep:
    should_release = lambda name: name not in keep
  else:
    should_release = None

  owned = lu.owned_locks(level)
  if not owned:
    # Not owning any lock at this level, do nothing
    pass

  elif should_release:
    retain = []
    release = []

    # Determine which locks to release
    for name in owned:
      if should_release(name):
        release.append(name)
      else:
        retain.append(name)

    assert len(lu.owned_locks(level)) == (len(retain) + len(release))

    # Release just some locks
    lu.glm.release(level, names=release)

    assert frozenset(lu.owned_locks(level)) == frozenset(retain)
  else:
    # Release everything
    lu.glm.release(level)

    assert not lu.glm.is_owned(level), "No locks should be owned"


def _MapInstanceDisksToNodes(instances):
  """Creates a map from (node, volume) to instance name.

  @type instances: list of L{objects.Instance}
  @rtype: dict; tuple of (node name, volume name) as key, instance name as value

  """
  return dict(((node, vol), inst.name)
              for inst in instances
              for (node, vols) in inst.MapLVsByNode().items()
              for vol in vols)


def _RunPostHook(lu, node_name):
  """Runs the post-hook for an opcode on a single node.

  """
  hm = lu.proc.BuildHooksManager(lu)
  try:
    hm.RunPhase(constants.HOOKS_PHASE_POST, nodes=[node_name])
  except Exception, err: # pylint: disable=W0703
    lu.LogWarning("Errors occurred running hooks on %s: %s",
                  node_name, err)


def _CheckOutputFields(static, dynamic, selected):
  """Checks whether all selected fields are valid.

  @type static: L{utils.FieldSet}
  @param static: static fields set
  @type dynamic: L{utils.FieldSet}
  @param dynamic: dynamic fields set

  """
  f = utils.FieldSet()
  f.Extend(static)
  f.Extend(dynamic)

  delta = f.NonMatching(selected)
  if delta:
    raise errors.OpPrereqError("Unknown output fields selected: %s"
                               % ",".join(delta), errors.ECODE_INVAL)


def _CheckParamsNotGlobal(params, glob_pars, kind, bad_levels, good_levels):
  """Make sure that none of the given paramters is global.

  If a global parameter is found, an L{errors.OpPrereqError} exception is
  raised. This is used to avoid setting global parameters for individual nodes.

  @type params: dictionary
  @param params: Parameters to check
  @type glob_pars: dictionary
  @param glob_pars: Forbidden parameters
  @type kind: string
  @param kind: Kind of parameters (e.g. "node")
  @type bad_levels: string
  @param bad_levels: Level(s) at which the parameters are forbidden (e.g.
      "instance")
  @type good_levels: strings
  @param good_levels: Level(s) at which the parameters are allowed (e.g.
      "cluster or group")

  """
  used_globals = glob_pars.intersection(params)
  if used_globals:
    msg = ("The following %s parameters are global and cannot"
           " be customized at %s level, please modify them at"
           " %s level: %s" %
           (kind, bad_levels, good_levels, utils.CommaJoin(used_globals)))
    raise errors.OpPrereqError(msg, errors.ECODE_INVAL)


def _CheckNodeOnline(lu, node, msg=None):
  """Ensure that a given node is online.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @param msg: if passed, should be a message to replace the default one
  @raise errors.OpPrereqError: if the node is offline

  """
  if msg is None:
    msg = "Can't use offline node"
  if lu.cfg.GetNodeInfo(node).offline:
    raise errors.OpPrereqError("%s: %s" % (msg, node), errors.ECODE_STATE)


def _CheckNodeNotDrained(lu, node):
  """Ensure that a given node is not drained.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @raise errors.OpPrereqError: if the node is drained

  """
  if lu.cfg.GetNodeInfo(node).drained:
    raise errors.OpPrereqError("Can't use drained node %s" % node,
                               errors.ECODE_STATE)


def _CheckNodeVmCapable(lu, node):
  """Ensure that a given node is vm capable.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @raise errors.OpPrereqError: if the node is not vm capable

  """
  if not lu.cfg.GetNodeInfo(node).vm_capable:
    raise errors.OpPrereqError("Can't use non-vm_capable node %s" % node,
                               errors.ECODE_STATE)


def _CheckNodeHasOS(lu, node, os_name, force_variant):
  """Ensure that a node supports a given OS.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @param os_name: the OS to query about
  @param force_variant: whether to ignore variant errors
  @raise errors.OpPrereqError: if the node is not supporting the OS

  """
  result = lu.rpc.call_os_get(node, os_name)
  result.Raise("OS '%s' not in supported OS list for node %s" %
               (os_name, node),
               prereq=True, ecode=errors.ECODE_INVAL)
  if not force_variant:
    _CheckOSVariant(result.payload, os_name)


def _CheckNodeHasSecondaryIP(lu, node, secondary_ip, prereq):
  """Ensure that a node has the given secondary ip.

  @type lu: L{LogicalUnit}
  @param lu: the LU on behalf of which we make the check
  @type node: string
  @param node: the node to check
  @type secondary_ip: string
  @param secondary_ip: the ip to check
  @type prereq: boolean
  @param prereq: whether to throw a prerequisite or an execute error
  @raise errors.OpPrereqError: if the node doesn't have the ip, and prereq=True
  @raise errors.OpExecError: if the node doesn't have the ip, and prereq=False

  """
  result = lu.rpc.call_node_has_ip_address(node, secondary_ip)
  result.Raise("Failure checking secondary ip on node %s" % node,
               prereq=prereq, ecode=errors.ECODE_ENVIRON)
  if not result.payload:
    msg = ("Node claims it doesn't have the secondary ip you gave (%s),"
           " please fix and re-run this command" % secondary_ip)
    if prereq:
      raise errors.OpPrereqError(msg, errors.ECODE_ENVIRON)
    else:
      raise errors.OpExecError(msg)


def _CheckNodePVs(nresult, exclusive_storage):
  """Check node PVs.

  """
  pvlist_dict = nresult.get(constants.NV_PVLIST, None)
  if pvlist_dict is None:
    return (["Can't get PV list from node"], None)
  pvlist = map(objects.LvmPvInfo.FromDict, pvlist_dict)
  errlist = []
  # check that ':' is not present in PV names, since it's a
  # special character for lvcreate (denotes the range of PEs to
  # use on the PV)
  for pv in pvlist:
    if ":" in pv.name:
      errlist.append("Invalid character ':' in PV '%s' of VG '%s'" %
                     (pv.name, pv.vg_name))
  es_pvinfo = None
  if exclusive_storage:
    (errmsgs, es_pvinfo) = utils.LvmExclusiveCheckNodePvs(pvlist)
    errlist.extend(errmsgs)
    shared_pvs = nresult.get(constants.NV_EXCLUSIVEPVS, None)
    if shared_pvs:
      for (pvname, lvlist) in shared_pvs:
        # TODO: Check that LVs are really unrelated (snapshots, DRBD meta...)
        errlist.append("PV %s is shared among unrelated LVs (%s)" %
                       (pvname, utils.CommaJoin(lvlist)))
  return (errlist, es_pvinfo)


def _GetClusterDomainSecret():
  """Reads the cluster domain secret.

  """
  return utils.ReadOneLineFile(pathutils.CLUSTER_DOMAIN_SECRET_FILE,
                               strict=True)


def _CheckInstanceState(lu, instance, req_states, msg=None):
  """Ensure that an instance is in one of the required states.

  @param lu: the LU on behalf of which we make the check
  @param instance: the instance to check
  @param msg: if passed, should be a message to replace the default one
  @raise errors.OpPrereqError: if the instance is not in the required state

  """
  if msg is None:
    msg = ("can't use instance from outside %s states" %
           utils.CommaJoin(req_states))
  if instance.admin_state not in req_states:
    raise errors.OpPrereqError("Instance '%s' is marked to be %s, %s" %
                               (instance.name, instance.admin_state, msg),
                               errors.ECODE_STATE)

  if constants.ADMINST_UP not in req_states:
    pnode = instance.primary_node
    if not lu.cfg.GetNodeInfo(pnode).offline:
      ins_l = lu.rpc.call_instance_list([pnode], [instance.hypervisor])[pnode]
      ins_l.Raise("Can't contact node %s for instance information" % pnode,
                  prereq=True, ecode=errors.ECODE_ENVIRON)
      if instance.name in ins_l.payload:
        raise errors.OpPrereqError("Instance %s is running, %s" %
                                   (instance.name, msg), errors.ECODE_STATE)
    else:
      lu.LogWarning("Primary node offline, ignoring check that instance"
                     " is down")


def _ComputeMinMaxSpec(name, qualifier, ipolicy, value):
  """Computes if value is in the desired range.

  @param name: name of the parameter for which we perform the check
  @param qualifier: a qualifier used in the error message (e.g. 'disk/1',
      not just 'disk')
  @param ipolicy: dictionary containing min, max and std values
  @param value: actual value that we want to use
  @return: None or element not meeting the criteria


  """
  if value in [None, constants.VALUE_AUTO]:
    return None
  max_v = ipolicy[constants.ISPECS_MAX].get(name, value)
  min_v = ipolicy[constants.ISPECS_MIN].get(name, value)
  if value > max_v or min_v > value:
    if qualifier:
      fqn = "%s/%s" % (name, qualifier)
    else:
      fqn = name
    return ("%s value %s is not in range [%s, %s]" %
            (fqn, value, min_v, max_v))
  return None


def _ComputeIPolicySpecViolation(ipolicy, mem_size, cpu_count, disk_count,
                                 nic_count, disk_sizes, spindle_use,
                                 disk_template,
                                 _compute_fn=_ComputeMinMaxSpec):
  """Verifies ipolicy against provided specs.

  @type ipolicy: dict
  @param ipolicy: The ipolicy
  @type mem_size: int
  @param mem_size: The memory size
  @type cpu_count: int
  @param cpu_count: Used cpu cores
  @type disk_count: int
  @param disk_count: Number of disks used
  @type nic_count: int
  @param nic_count: Number of nics used
  @type disk_sizes: list of ints
  @param disk_sizes: Disk sizes of used disk (len must match C{disk_count})
  @type spindle_use: int
  @param spindle_use: The number of spindles this instance uses
  @type disk_template: string
  @param disk_template: The disk template of the instance
  @param _compute_fn: The compute function (unittest only)
  @return: A list of violations, or an empty list of no violations are found

  """
  assert disk_count == len(disk_sizes)

  test_settings = [
    (constants.ISPEC_MEM_SIZE, "", mem_size),
    (constants.ISPEC_CPU_COUNT, "", cpu_count),
    (constants.ISPEC_NIC_COUNT, "", nic_count),
    (constants.ISPEC_SPINDLE_USE, "", spindle_use),
    ] + [(constants.ISPEC_DISK_SIZE, str(idx), d)
         for idx, d in enumerate(disk_sizes)]
  if disk_template != constants.DT_DISKLESS:
    # This check doesn't make sense for diskless instances
    test_settings.append((constants.ISPEC_DISK_COUNT, "", disk_count))
  ret = []
  allowed_dts = ipolicy[constants.IPOLICY_DTS]
  if disk_template not in allowed_dts:
    ret.append("Disk template %s is not allowed (allowed templates: %s)" %
               (disk_template, utils.CommaJoin(allowed_dts)))

  return ret + filter(None,
                      (_compute_fn(name, qualifier, ipolicy, value)
                       for (name, qualifier, value) in test_settings))


def _ComputeIPolicyInstanceViolation(ipolicy, instance, cfg,
                                     _compute_fn=_ComputeIPolicySpecViolation):
  """Compute if instance meets the specs of ipolicy.

  @type ipolicy: dict
  @param ipolicy: The ipolicy to verify against
  @type instance: L{objects.Instance}
  @param instance: The instance to verify
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{_ComputeIPolicySpecViolation}

  """
  be_full = cfg.GetClusterInfo().FillBE(instance)
  mem_size = be_full[constants.BE_MAXMEM]
  cpu_count = be_full[constants.BE_VCPUS]
  spindle_use = be_full[constants.BE_SPINDLE_USE]
  disk_count = len(instance.disks)
  disk_sizes = [disk.size for disk in instance.disks]
  nic_count = len(instance.nics)
  disk_template = instance.disk_template

  return _compute_fn(ipolicy, mem_size, cpu_count, disk_count, nic_count,
                     disk_sizes, spindle_use, disk_template)


def _ComputeIPolicyInstanceSpecViolation(
  ipolicy, instance_spec, disk_template,
  _compute_fn=_ComputeIPolicySpecViolation):
  """Compute if instance specs meets the specs of ipolicy.

  @type ipolicy: dict
  @param ipolicy: The ipolicy to verify against
  @param instance_spec: dict
  @param instance_spec: The instance spec to verify
  @type disk_template: string
  @param disk_template: the disk template of the instance
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{_ComputeIPolicySpecViolation}

  """
  mem_size = instance_spec.get(constants.ISPEC_MEM_SIZE, None)
  cpu_count = instance_spec.get(constants.ISPEC_CPU_COUNT, None)
  disk_count = instance_spec.get(constants.ISPEC_DISK_COUNT, 0)
  disk_sizes = instance_spec.get(constants.ISPEC_DISK_SIZE, [])
  nic_count = instance_spec.get(constants.ISPEC_NIC_COUNT, 0)
  spindle_use = instance_spec.get(constants.ISPEC_SPINDLE_USE, None)

  return _compute_fn(ipolicy, mem_size, cpu_count, disk_count, nic_count,
                     disk_sizes, spindle_use, disk_template)


def _ComputeIPolicyNodeViolation(ipolicy, instance, current_group,
                                 target_group, cfg,
                                 _compute_fn=_ComputeIPolicyInstanceViolation):
  """Compute if instance meets the specs of the new target group.

  @param ipolicy: The ipolicy to verify
  @param instance: The instance object to verify
  @param current_group: The current group of the instance
  @param target_group: The new group of the instance
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{_ComputeIPolicySpecViolation}

  """
  if current_group == target_group:
    return []
  else:
    return _compute_fn(ipolicy, instance, cfg)


def _CheckTargetNodeIPolicy(lu, ipolicy, instance, node, cfg, ignore=False,
                            _compute_fn=_ComputeIPolicyNodeViolation):
  """Checks that the target node is correct in terms of instance policy.

  @param ipolicy: The ipolicy to verify
  @param instance: The instance object to verify
  @param node: The new node to relocate
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @param ignore: Ignore violations of the ipolicy
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{_ComputeIPolicySpecViolation}

  """
  primary_node = lu.cfg.GetNodeInfo(instance.primary_node)
  res = _compute_fn(ipolicy, instance, primary_node.group, node.group, cfg)

  if res:
    msg = ("Instance does not meet target node group's (%s) instance"
           " policy: %s") % (node.group, utils.CommaJoin(res))
    if ignore:
      lu.LogWarning(msg)
    else:
      raise errors.OpPrereqError(msg, errors.ECODE_INVAL)


def _ComputeNewInstanceViolations(old_ipolicy, new_ipolicy, instances, cfg):
  """Computes a set of any instances that would violate the new ipolicy.

  @param old_ipolicy: The current (still in-place) ipolicy
  @param new_ipolicy: The new (to become) ipolicy
  @param instances: List of instances to verify
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @return: A list of instances which violates the new ipolicy but
      did not before

  """
  return (_ComputeViolatingInstances(new_ipolicy, instances, cfg) -
          _ComputeViolatingInstances(old_ipolicy, instances, cfg))


def _ExpandItemName(fn, name, kind):
  """Expand an item name.

  @param fn: the function to use for expansion
  @param name: requested item name
  @param kind: text description ('Node' or 'Instance')
  @return: the resolved (full) name
  @raise errors.OpPrereqError: if the item is not found

  """
  full_name = fn(name)
  if full_name is None:
    raise errors.OpPrereqError("%s '%s' not known" % (kind, name),
                               errors.ECODE_NOENT)
  return full_name


def _ExpandNodeName(cfg, name):
  """Wrapper over L{_ExpandItemName} for nodes."""
  return _ExpandItemName(cfg.ExpandNodeName, name, "Node")


def _ExpandInstanceName(cfg, name):
  """Wrapper over L{_ExpandItemName} for instance."""
  return _ExpandItemName(cfg.ExpandInstanceName, name, "Instance")


def _BuildNetworkHookEnv(name, subnet, gateway, network6, gateway6,
                         mac_prefix, tags):
  """Builds network related env variables for hooks

  This builds the hook environment from individual variables.

  @type name: string
  @param name: the name of the network
  @type subnet: string
  @param subnet: the ipv4 subnet
  @type gateway: string
  @param gateway: the ipv4 gateway
  @type network6: string
  @param network6: the ipv6 subnet
  @type gateway6: string
  @param gateway6: the ipv6 gateway
  @type mac_prefix: string
  @param mac_prefix: the mac_prefix
  @type tags: list
  @param tags: the tags of the network

  """
  env = {}
  if name:
    env["NETWORK_NAME"] = name
  if subnet:
    env["NETWORK_SUBNET"] = subnet
  if gateway:
    env["NETWORK_GATEWAY"] = gateway
  if network6:
    env["NETWORK_SUBNET6"] = network6
  if gateway6:
    env["NETWORK_GATEWAY6"] = gateway6
  if mac_prefix:
    env["NETWORK_MAC_PREFIX"] = mac_prefix
  if tags:
    env["NETWORK_TAGS"] = " ".join(tags)

  return env


def _BuildInstanceHookEnv(name, primary_node, secondary_nodes, os_type, status,
                          minmem, maxmem, vcpus, nics, disk_template, disks,
                          bep, hvp, hypervisor_name, tags):
  """Builds instance related env variables for hooks

  This builds the hook environment from individual variables.

  @type name: string
  @param name: the name of the instance
  @type primary_node: string
  @param primary_node: the name of the instance's primary node
  @type secondary_nodes: list
  @param secondary_nodes: list of secondary nodes as strings
  @type os_type: string
  @param os_type: the name of the instance's OS
  @type status: string
  @param status: the desired status of the instance
  @type minmem: string
  @param minmem: the minimum memory size of the instance
  @type maxmem: string
  @param maxmem: the maximum memory size of the instance
  @type vcpus: string
  @param vcpus: the count of VCPUs the instance has
  @type nics: list
  @param nics: list of tuples (ip, mac, mode, link, net, netinfo) representing
      the NICs the instance has
  @type disk_template: string
  @param disk_template: the disk template of the instance
  @type disks: list
  @param disks: the list of (size, mode) pairs
  @type bep: dict
  @param bep: the backend parameters for the instance
  @type hvp: dict
  @param hvp: the hypervisor parameters for the instance
  @type hypervisor_name: string
  @param hypervisor_name: the hypervisor for the instance
  @type tags: list
  @param tags: list of instance tags as strings
  @rtype: dict
  @return: the hook environment for this instance

  """
  env = {
    "OP_TARGET": name,
    "INSTANCE_NAME": name,
    "INSTANCE_PRIMARY": primary_node,
    "INSTANCE_SECONDARIES": " ".join(secondary_nodes),
    "INSTANCE_OS_TYPE": os_type,
    "INSTANCE_STATUS": status,
    "INSTANCE_MINMEM": minmem,
    "INSTANCE_MAXMEM": maxmem,
    # TODO(2.9) remove deprecated "memory" value
    "INSTANCE_MEMORY": maxmem,
    "INSTANCE_VCPUS": vcpus,
    "INSTANCE_DISK_TEMPLATE": disk_template,
    "INSTANCE_HYPERVISOR": hypervisor_name,
  }
  if nics:
    nic_count = len(nics)
    for idx, (ip, mac, mode, link, net, netinfo) in enumerate(nics):
      if ip is None:
        ip = ""
      env["INSTANCE_NIC%d_IP" % idx] = ip
      env["INSTANCE_NIC%d_MAC" % idx] = mac
      env["INSTANCE_NIC%d_MODE" % idx] = mode
      env["INSTANCE_NIC%d_LINK" % idx] = link
      if netinfo:
        nobj = objects.Network.FromDict(netinfo)
        env.update(nobj.HooksDict("INSTANCE_NIC%d_" % idx))
      elif network:
        # FIXME: broken network reference: the instance NIC specifies a
        # network, but the relevant network entry was not in the config. This
        # should be made impossible.
        env["INSTANCE_NIC%d_NETWORK_NAME" % idx] = net
      if mode == constants.NIC_MODE_BRIDGED:
        env["INSTANCE_NIC%d_BRIDGE" % idx] = link
  else:
    nic_count = 0

  env["INSTANCE_NIC_COUNT"] = nic_count

  if disks:
    disk_count = len(disks)
    for idx, (size, mode) in enumerate(disks):
      env["INSTANCE_DISK%d_SIZE" % idx] = size
      env["INSTANCE_DISK%d_MODE" % idx] = mode
  else:
    disk_count = 0

  env["INSTANCE_DISK_COUNT"] = disk_count

  if not tags:
    tags = []

  env["INSTANCE_TAGS"] = " ".join(tags)

  for source, kind in [(bep, "BE"), (hvp, "HV")]:
    for key, value in source.items():
      env["INSTANCE_%s_%s" % (kind, key)] = value

  return env


def _NICToTuple(lu, nic):
  """Build a tupple of nic information.

  @type lu:  L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type nic: L{objects.NIC}
  @param nic: nic to convert to hooks tuple

  """
  cluster = lu.cfg.GetClusterInfo()
  filled_params = cluster.SimpleFillNIC(nic.nicparams)
  mode = filled_params[constants.NIC_MODE]
  link = filled_params[constants.NIC_LINK]
  netinfo = None
  if nic.network:
    nobj = lu.cfg.GetNetwork(nic.network)
    netinfo = objects.Network.ToDict(nobj)
  return (nic.ip, nic.mac, mode, link, nic.network, netinfo)


def _NICListToTuple(lu, nics):
  """Build a list of nic information tuples.

  This list is suitable to be passed to _BuildInstanceHookEnv or as a return
  value in LUInstanceQueryData.

  @type lu:  L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type nics: list of L{objects.NIC}
  @param nics: list of nics to convert to hooks tuples

  """
  hooks_nics = []
  for nic in nics:
    hooks_nics.append(_NICToTuple(lu, nic))
  return hooks_nics


def _BuildInstanceHookEnvByObject(lu, instance, override=None):
  """Builds instance related env variables for hooks from an object.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance for which we should build the
      environment
  @type override: dict
  @param override: dictionary with key/values that will override
      our values
  @rtype: dict
  @return: the hook environment dictionary

  """
  cluster = lu.cfg.GetClusterInfo()
  bep = cluster.FillBE(instance)
  hvp = cluster.FillHV(instance)
  args = {
    "name": instance.name,
    "primary_node": instance.primary_node,
    "secondary_nodes": instance.secondary_nodes,
    "os_type": instance.os,
    "status": instance.admin_state,
    "maxmem": bep[constants.BE_MAXMEM],
    "minmem": bep[constants.BE_MINMEM],
    "vcpus": bep[constants.BE_VCPUS],
    "nics": _NICListToTuple(lu, instance.nics),
    "disk_template": instance.disk_template,
    "disks": [(disk.size, disk.mode) for disk in instance.disks],
    "bep": bep,
    "hvp": hvp,
    "hypervisor_name": instance.hypervisor,
    "tags": instance.tags,
  }
  if override:
    args.update(override)
  return _BuildInstanceHookEnv(**args) # pylint: disable=W0142


def _AdjustCandidatePool(lu, exceptions):
  """Adjust the candidate pool after node operations.

  """
  mod_list = lu.cfg.MaintainCandidatePool(exceptions)
  if mod_list:
    lu.LogInfo("Promoted nodes to master candidate role: %s",
               utils.CommaJoin(node.name for node in mod_list))
    for name in mod_list:
      lu.context.ReaddNode(name)
  mc_now, mc_max, _ = lu.cfg.GetMasterCandidateStats(exceptions)
  if mc_now > mc_max:
    lu.LogInfo("Note: more nodes are candidates (%d) than desired (%d)" %
               (mc_now, mc_max))


def _DecideSelfPromotion(lu, exceptions=None):
  """Decide whether I should promote myself as a master candidate.

  """
  cp_size = lu.cfg.GetClusterInfo().candidate_pool_size
  mc_now, mc_should, _ = lu.cfg.GetMasterCandidateStats(exceptions)
  # the new node will increase mc_max with one, so:
  mc_should = min(mc_should + 1, cp_size)
  return mc_now < mc_should


def _ComputeViolatingInstances(ipolicy, instances, cfg):
  """Computes a set of instances who violates given ipolicy.

  @param ipolicy: The ipolicy to verify
  @type instances: L{objects.Instance}
  @param instances: List of instances to verify
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @return: A frozenset of instance names violating the ipolicy

  """
  return frozenset([inst.name for inst in instances
                    if _ComputeIPolicyInstanceViolation(ipolicy, inst, cfg)])


def _CheckNicsBridgesExist(lu, target_nics, target_node):
  """Check that the brigdes needed by a list of nics exist.

  """
  cluster = lu.cfg.GetClusterInfo()
  paramslist = [cluster.SimpleFillNIC(nic.nicparams) for nic in target_nics]
  brlist = [params[constants.NIC_LINK] for params in paramslist
            if params[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED]
  if brlist:
    result = lu.rpc.call_bridges_exist(target_node, brlist)
    result.Raise("Error checking bridges on destination node '%s'" %
                 target_node, prereq=True, ecode=errors.ECODE_ENVIRON)


def _CheckInstanceBridgesExist(lu, instance, node=None):
  """Check that the brigdes needed by an instance exist.

  """
  if node is None:
    node = instance.primary_node
  _CheckNicsBridgesExist(lu, instance.nics, node)


def _CheckOSVariant(os_obj, name):
  """Check whether an OS name conforms to the os variants specification.

  @type os_obj: L{objects.OS}
  @param os_obj: OS object to check
  @type name: string
  @param name: OS name passed by the user, to check for validity

  """
  variant = objects.OS.GetVariant(name)
  if not os_obj.supported_variants:
    if variant:
      raise errors.OpPrereqError("OS '%s' doesn't support variants ('%s'"
                                 " passed)" % (os_obj.name, variant),
                                 errors.ECODE_INVAL)
    return
  if not variant:
    raise errors.OpPrereqError("OS name must include a variant",
                               errors.ECODE_INVAL)

  if variant not in os_obj.supported_variants:
    raise errors.OpPrereqError("Unsupported OS variant", errors.ECODE_INVAL)


def _GetNodeInstancesInner(cfg, fn):
  return [i for i in cfg.GetAllInstancesInfo().values() if fn(i)]


def _GetNodeInstances(cfg, node_name):
  """Returns a list of all primary and secondary instances on a node.

  """

  return _GetNodeInstancesInner(cfg, lambda inst: node_name in inst.all_nodes)


def _GetNodePrimaryInstances(cfg, node_name):
  """Returns primary instances on a node.

  """
  return _GetNodeInstancesInner(cfg,
                                lambda inst: node_name == inst.primary_node)


def _GetNodeSecondaryInstances(cfg, node_name):
  """Returns secondary instances on a node.

  """
  return _GetNodeInstancesInner(cfg,
                                lambda inst: node_name in inst.secondary_nodes)


def _GetStorageTypeArgs(cfg, storage_type):
  """Returns the arguments for a storage type.

  """
  # Special case for file storage
  if storage_type == constants.ST_FILE:
    # storage.FileStorage wants a list of storage directories
    return [[cfg.GetFileStorageDir(), cfg.GetSharedFileStorageDir()]]

  return []


def _FindFaultyInstanceDisks(cfg, rpc_runner, instance, node_name, prereq):
  faulty = []

  for dev in instance.disks:
    cfg.SetDiskID(dev, node_name)

  result = rpc_runner.call_blockdev_getmirrorstatus(node_name, (instance.disks,
                                                                instance))
  result.Raise("Failed to get disk status from node %s" % node_name,
               prereq=prereq, ecode=errors.ECODE_ENVIRON)

  for idx, bdev_status in enumerate(result.payload):
    if bdev_status and bdev_status.ldisk_status == constants.LDS_FAULTY:
      faulty.append(idx)

  return faulty


def _CheckIAllocatorOrNode(lu, iallocator_slot, node_slot):
  """Check the sanity of iallocator and node arguments and use the
  cluster-wide iallocator if appropriate.

  Check that at most one of (iallocator, node) is specified. If none is
  specified, or the iallocator is L{constants.DEFAULT_IALLOCATOR_SHORTCUT},
  then the LU's opcode's iallocator slot is filled with the cluster-wide
  default iallocator.

  @type iallocator_slot: string
  @param iallocator_slot: the name of the opcode iallocator slot
  @type node_slot: string
  @param node_slot: the name of the opcode target node slot

  """
  node = getattr(lu.op, node_slot, None)
  ialloc = getattr(lu.op, iallocator_slot, None)
  if node == []:
    node = None

  if node is not None and ialloc is not None:
    raise errors.OpPrereqError("Do not specify both, iallocator and node",
                               errors.ECODE_INVAL)
  elif ((node is None and ialloc is None) or
        ialloc == constants.DEFAULT_IALLOCATOR_SHORTCUT):
    default_iallocator = lu.cfg.GetDefaultIAllocator()
    if default_iallocator:
      setattr(lu.op, iallocator_slot, default_iallocator)
    else:
      raise errors.OpPrereqError("No iallocator or node given and no"
                                 " cluster-wide default iallocator found;"
                                 " please specify either an iallocator or a"
                                 " node, or set a cluster-wide default"
                                 " iallocator", errors.ECODE_INVAL)


def _GetDefaultIAllocator(cfg, ialloc):
  """Decides on which iallocator to use.

  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration object
  @type ialloc: string or None
  @param ialloc: Iallocator specified in opcode
  @rtype: string
  @return: Iallocator name

  """
  if not ialloc:
    # Use default iallocator
    ialloc = cfg.GetDefaultIAllocator()

  if not ialloc:
    raise errors.OpPrereqError("No iallocator was specified, neither in the"
                               " opcode nor as a cluster-wide default",
                               errors.ECODE_INVAL)

  return ialloc


def _CheckHostnameSane(lu, name):
  """Ensures that a given hostname resolves to a 'sane' name.

  The given name is required to be a prefix of the resolved hostname,
  to prevent accidental mismatches.

  @param lu: the logical unit on behalf of which we're checking
  @param name: the name we should resolve and check
  @return: the resolved hostname object

  """
  hostname = netutils.GetHostname(name=name)
  if hostname.name != name:
    lu.LogInfo("Resolved given name '%s' to '%s'", name, hostname.name)
  if not utils.MatchNameComponent(name, [hostname.name]):
    raise errors.OpPrereqError(("Resolved hostname '%s' does not look the"
                                " same as given hostname '%s'") %
                                (hostname.name, name), errors.ECODE_INVAL)
  return hostname


class LUClusterPostInit(LogicalUnit):
  """Logical unit for running hooks after cluster initialization.

  """
  HPATH = "cluster-init"
  HTYPE = constants.HTYPE_CLUSTER

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([], [self.cfg.GetMasterNode()])

  def Exec(self, feedback_fn):
    """Nothing to do.

    """
    return True


class LUClusterDestroy(LogicalUnit):
  """Logical unit for destroying the cluster.

  """
  HPATH = "cluster-destroy"
  HTYPE = constants.HTYPE_CLUSTER

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([], [])

  def CheckPrereq(self):
    """Check prerequisites.

    This checks whether the cluster is empty.

    Any errors are signaled by raising errors.OpPrereqError.

    """
    master = self.cfg.GetMasterNode()

    nodelist = self.cfg.GetNodeList()
    if len(nodelist) != 1 or nodelist[0] != master:
      raise errors.OpPrereqError("There are still %d node(s) in"
                                 " this cluster." % (len(nodelist) - 1),
                                 errors.ECODE_INVAL)
    instancelist = self.cfg.GetInstanceList()
    if instancelist:
      raise errors.OpPrereqError("There are still %d instance(s) in"
                                 " this cluster." % len(instancelist),
                                 errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Destroys the cluster.

    """
    master_params = self.cfg.GetMasterNetworkParameters()

    # Run post hooks on master node before it's removed
    _RunPostHook(self, master_params.name)

    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_deactivate_master_ip(master_params.name,
                                                     master_params, ems)
    if result.fail_msg:
      self.LogWarning("Error disabling the master IP address: %s",
                      result.fail_msg)

    return master_params.name


def _VerifyCertificate(filename):
  """Verifies a certificate for L{LUClusterVerifyConfig}.

  @type filename: string
  @param filename: Path to PEM file

  """
  try:
    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           utils.ReadFile(filename))
  except Exception, err: # pylint: disable=W0703
    return (LUClusterVerifyConfig.ETYPE_ERROR,
            "Failed to load X509 certificate %s: %s" % (filename, err))

  (errcode, msg) = \
    utils.VerifyX509Certificate(cert, constants.SSL_CERT_EXPIRATION_WARN,
                                constants.SSL_CERT_EXPIRATION_ERROR)

  if msg:
    fnamemsg = "While verifying %s: %s" % (filename, msg)
  else:
    fnamemsg = None

  if errcode is None:
    return (None, fnamemsg)
  elif errcode == utils.CERT_WARNING:
    return (LUClusterVerifyConfig.ETYPE_WARNING, fnamemsg)
  elif errcode == utils.CERT_ERROR:
    return (LUClusterVerifyConfig.ETYPE_ERROR, fnamemsg)

  raise errors.ProgrammerError("Unhandled certificate error code %r" % errcode)


def _GetAllHypervisorParameters(cluster, instances):
  """Compute the set of all hypervisor parameters.

  @type cluster: L{objects.Cluster}
  @param cluster: the cluster object
  @param instances: list of L{objects.Instance}
  @param instances: additional instances from which to obtain parameters
  @rtype: list of (origin, hypervisor, parameters)
  @return: a list with all parameters found, indicating the hypervisor they
       apply to, and the origin (can be "cluster", "os X", or "instance Y")

  """
  hvp_data = []

  for hv_name in cluster.enabled_hypervisors:
    hvp_data.append(("cluster", hv_name, cluster.GetHVDefaults(hv_name)))

  for os_name, os_hvp in cluster.os_hvp.items():
    for hv_name, hv_params in os_hvp.items():
      if hv_params:
        full_params = cluster.GetHVDefaults(hv_name, os_name=os_name)
        hvp_data.append(("os %s" % os_name, hv_name, full_params))

  # TODO: collapse identical parameter values in a single one
  for instance in instances:
    if instance.hvparams:
      hvp_data.append(("instance %s" % instance.name, instance.hypervisor,
                       cluster.FillHV(instance)))

  return hvp_data


class _VerifyErrors(object):
  """Mix-in for cluster/group verify LUs.

  It provides _Error and _ErrorIf, and updates the self.bad boolean. (Expects
  self.op and self._feedback_fn to be available.)

  """

  ETYPE_FIELD = "code"
  ETYPE_ERROR = "ERROR"
  ETYPE_WARNING = "WARNING"

  def _Error(self, ecode, item, msg, *args, **kwargs):
    """Format an error message.

    Based on the opcode's error_codes parameter, either format a
    parseable error code, or a simpler error string.

    This must be called only from Exec and functions called from Exec.

    """
    ltype = kwargs.get(self.ETYPE_FIELD, self.ETYPE_ERROR)
    itype, etxt, _ = ecode
    # If the error code is in the list of ignored errors, demote the error to a
    # warning
    if etxt in self.op.ignore_errors:     # pylint: disable=E1101
      ltype = self.ETYPE_WARNING
    # first complete the msg
    if args:
      msg = msg % args
    # then format the whole message
    if self.op.error_codes: # This is a mix-in. pylint: disable=E1101
      msg = "%s:%s:%s:%s:%s" % (ltype, etxt, itype, item, msg)
    else:
      if item:
        item = " " + item
      else:
        item = ""
      msg = "%s: %s%s: %s" % (ltype, itype, item, msg)
    # and finally report it via the feedback_fn
    self._feedback_fn("  - %s" % msg) # Mix-in. pylint: disable=E1101
    # do not mark the operation as failed for WARN cases only
    if ltype == self.ETYPE_ERROR:
      self.bad = True

  def _ErrorIf(self, cond, *args, **kwargs):
    """Log an error message if the passed condition is True.

    """
    if (bool(cond)
        or self.op.debug_simulate_errors): # pylint: disable=E1101
      self._Error(*args, **kwargs)


class LUClusterVerify(NoHooksLU):
  """Submits all jobs necessary to verify the cluster.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    jobs = []

    if self.op.group_name:
      groups = [self.op.group_name]
      depends_fn = lambda: None
    else:
      groups = self.cfg.GetNodeGroupList()

      # Verify global configuration
      jobs.append([
        opcodes.OpClusterVerifyConfig(ignore_errors=self.op.ignore_errors),
        ])

      # Always depend on global verification
      depends_fn = lambda: [(-len(jobs), [])]

    jobs.extend(
      [opcodes.OpClusterVerifyGroup(group_name=group,
                                    ignore_errors=self.op.ignore_errors,
                                    depends=depends_fn())]
      for group in groups)

    # Fix up all parameters
    for op in itertools.chain(*jobs): # pylint: disable=W0142
      op.debug_simulate_errors = self.op.debug_simulate_errors
      op.verbose = self.op.verbose
      op.error_codes = self.op.error_codes
      try:
        op.skip_checks = self.op.skip_checks
      except AttributeError:
        assert not isinstance(op, opcodes.OpClusterVerifyGroup)

    return ResultWithJobs(jobs)


class LUClusterVerifyConfig(NoHooksLU, _VerifyErrors):
  """Verifies the cluster config.

  """
  REQ_BGL = False

  def _VerifyHVP(self, hvp_data):
    """Verifies locally the syntax of the hypervisor parameters.

    """
    for item, hv_name, hv_params in hvp_data:
      msg = ("hypervisor %s parameters syntax check (source %s): %%s" %
             (item, hv_name))
      try:
        hv_class = hypervisor.GetHypervisorClass(hv_name)
        utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
        hv_class.CheckParameterSyntax(hv_params)
      except errors.GenericError, err:
        self._ErrorIf(True, constants.CV_ECLUSTERCFG, None, msg % str(err))

  def ExpandNames(self):
    self.needed_locks = dict.fromkeys(locking.LEVELS, locking.ALL_SET)
    self.share_locks = _ShareAll()

  def CheckPrereq(self):
    """Check prerequisites.

    """
    # Retrieve all information
    self.all_group_info = self.cfg.GetAllNodeGroupsInfo()
    self.all_node_info = self.cfg.GetAllNodesInfo()
    self.all_inst_info = self.cfg.GetAllInstancesInfo()

  def Exec(self, feedback_fn):
    """Verify integrity of cluster, performing various test on nodes.

    """
    self.bad = False
    self._feedback_fn = feedback_fn

    feedback_fn("* Verifying cluster config")

    for msg in self.cfg.VerifyConfig():
      self._ErrorIf(True, constants.CV_ECLUSTERCFG, None, msg)

    feedback_fn("* Verifying cluster certificate files")

    for cert_filename in pathutils.ALL_CERT_FILES:
      (errcode, msg) = _VerifyCertificate(cert_filename)
      self._ErrorIf(errcode, constants.CV_ECLUSTERCERT, None, msg, code=errcode)

    feedback_fn("* Verifying hypervisor parameters")

    self._VerifyHVP(_GetAllHypervisorParameters(self.cfg.GetClusterInfo(),
                                                self.all_inst_info.values()))

    feedback_fn("* Verifying all nodes belong to an existing group")

    # We do this verification here because, should this bogus circumstance
    # occur, it would never be caught by VerifyGroup, which only acts on
    # nodes/instances reachable from existing node groups.

    dangling_nodes = set(node.name for node in self.all_node_info.values()
                         if node.group not in self.all_group_info)

    dangling_instances = {}
    no_node_instances = []

    for inst in self.all_inst_info.values():
      if inst.primary_node in dangling_nodes:
        dangling_instances.setdefault(inst.primary_node, []).append(inst.name)
      elif inst.primary_node not in self.all_node_info:
        no_node_instances.append(inst.name)

    pretty_dangling = [
        "%s (%s)" %
        (node.name,
         utils.CommaJoin(dangling_instances.get(node.name,
                                                ["no instances"])))
        for node in dangling_nodes]

    self._ErrorIf(bool(dangling_nodes), constants.CV_ECLUSTERDANGLINGNODES,
                  None,
                  "the following nodes (and their instances) belong to a non"
                  " existing group: %s", utils.CommaJoin(pretty_dangling))

    self._ErrorIf(bool(no_node_instances), constants.CV_ECLUSTERDANGLINGINST,
                  None,
                  "the following instances have a non-existing primary-node:"
                  " %s", utils.CommaJoin(no_node_instances))

    return not self.bad


class LUClusterVerifyGroup(LogicalUnit, _VerifyErrors):
  """Verifies the status of a node group.

  """
  HPATH = "cluster-verify"
  HTYPE = constants.HTYPE_CLUSTER
  REQ_BGL = False

  _HOOKS_INDENT_RE = re.compile("^", re.M)

  class NodeImage(object):
    """A class representing the logical and physical status of a node.

    @type name: string
    @ivar name: the node name to which this object refers
    @ivar volumes: a structure as returned from
        L{ganeti.backend.GetVolumeList} (runtime)
    @ivar instances: a list of running instances (runtime)
    @ivar pinst: list of configured primary instances (config)
    @ivar sinst: list of configured secondary instances (config)
    @ivar sbp: dictionary of {primary-node: list of instances} for all
        instances for which this node is secondary (config)
    @ivar mfree: free memory, as reported by hypervisor (runtime)
    @ivar dfree: free disk, as reported by the node (runtime)
    @ivar offline: the offline status (config)
    @type rpc_fail: boolean
    @ivar rpc_fail: whether the RPC verify call was successfull (overall,
        not whether the individual keys were correct) (runtime)
    @type lvm_fail: boolean
    @ivar lvm_fail: whether the RPC call didn't return valid LVM data
    @type hyp_fail: boolean
    @ivar hyp_fail: whether the RPC call didn't return the instance list
    @type ghost: boolean
    @ivar ghost: whether this is a known node or not (config)
    @type os_fail: boolean
    @ivar os_fail: whether the RPC call didn't return valid OS data
    @type oslist: list
    @ivar oslist: list of OSes as diagnosed by DiagnoseOS
    @type vm_capable: boolean
    @ivar vm_capable: whether the node can host instances
    @type pv_min: float
    @ivar pv_min: size in MiB of the smallest PVs
    @type pv_max: float
    @ivar pv_max: size in MiB of the biggest PVs

    """
    def __init__(self, offline=False, name=None, vm_capable=True):
      self.name = name
      self.volumes = {}
      self.instances = []
      self.pinst = []
      self.sinst = []
      self.sbp = {}
      self.mfree = 0
      self.dfree = 0
      self.offline = offline
      self.vm_capable = vm_capable
      self.rpc_fail = False
      self.lvm_fail = False
      self.hyp_fail = False
      self.ghost = False
      self.os_fail = False
      self.oslist = {}
      self.pv_min = None
      self.pv_max = None

  def ExpandNames(self):
    # This raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    # Get instances in node group; this is unsafe and needs verification later
    inst_names = \
      self.cfg.GetNodeGroupInstances(self.group_uuid, primary_only=True)

    self.needed_locks = {
      locking.LEVEL_INSTANCE: inst_names,
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      locking.LEVEL_NODE: [],

      # This opcode is run by watcher every five minutes and acquires all nodes
      # for a group. It doesn't run for a long time, so it's better to acquire
      # the node allocation lock as well.
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    self.share_locks = _ShareAll()

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      # Get members of node group; this is unsafe and needs verification later
      nodes = set(self.cfg.GetNodeGroup(self.group_uuid).members)

      all_inst_info = self.cfg.GetAllInstancesInfo()

      # In Exec(), we warn about mirrored instances that have primary and
      # secondary living in separate node groups. To fully verify that
      # volumes for these instances are healthy, we will need to do an
      # extra call to their secondaries. We ensure here those nodes will
      # be locked.
      for inst in self.owned_locks(locking.LEVEL_INSTANCE):
        # Important: access only the instances whose lock is owned
        if all_inst_info[inst].disk_template in constants.DTS_INT_MIRROR:
          nodes.update(all_inst_info[inst].secondary_nodes)

      self.needed_locks[locking.LEVEL_NODE] = nodes

  def CheckPrereq(self):
    assert self.group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)
    self.group_info = self.cfg.GetNodeGroup(self.group_uuid)

    group_nodes = set(self.group_info.members)
    group_instances = \
      self.cfg.GetNodeGroupInstances(self.group_uuid, primary_only=True)

    unlocked_nodes = \
        group_nodes.difference(self.owned_locks(locking.LEVEL_NODE))

    unlocked_instances = \
        group_instances.difference(self.owned_locks(locking.LEVEL_INSTANCE))

    if unlocked_nodes:
      raise errors.OpPrereqError("Missing lock for nodes: %s" %
                                 utils.CommaJoin(unlocked_nodes),
                                 errors.ECODE_STATE)

    if unlocked_instances:
      raise errors.OpPrereqError("Missing lock for instances: %s" %
                                 utils.CommaJoin(unlocked_instances),
                                 errors.ECODE_STATE)

    self.all_node_info = self.cfg.GetAllNodesInfo()
    self.all_inst_info = self.cfg.GetAllInstancesInfo()

    self.my_node_names = utils.NiceSort(group_nodes)
    self.my_inst_names = utils.NiceSort(group_instances)

    self.my_node_info = dict((name, self.all_node_info[name])
                             for name in self.my_node_names)

    self.my_inst_info = dict((name, self.all_inst_info[name])
                             for name in self.my_inst_names)

    # We detect here the nodes that will need the extra RPC calls for verifying
    # split LV volumes; they should be locked.
    extra_lv_nodes = set()

    for inst in self.my_inst_info.values():
      if inst.disk_template in constants.DTS_INT_MIRROR:
        for nname in inst.all_nodes:
          if self.all_node_info[nname].group != self.group_uuid:
            extra_lv_nodes.add(nname)

    unlocked_lv_nodes = \
        extra_lv_nodes.difference(self.owned_locks(locking.LEVEL_NODE))

    if unlocked_lv_nodes:
      raise errors.OpPrereqError("Missing node locks for LV check: %s" %
                                 utils.CommaJoin(unlocked_lv_nodes),
                                 errors.ECODE_STATE)
    self.extra_lv_nodes = list(extra_lv_nodes)

  def _VerifyNode(self, ninfo, nresult):
    """Perform some basic validation on data returned from a node.

      - check the result data structure is well formed and has all the
        mandatory fields
      - check ganeti version

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the results from the node
    @rtype: boolean
    @return: whether overall this call was successful (and we can expect
         reasonable values in the respose)

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    # main result, nresult should be a non-empty dict
    test = not nresult or not isinstance(nresult, dict)
    _ErrorIf(test, constants.CV_ENODERPC, node,
                  "unable to verify node: no data returned")
    if test:
      return False

    # compares ganeti version
    local_version = constants.PROTOCOL_VERSION
    remote_version = nresult.get("version", None)
    test = not (remote_version and
                isinstance(remote_version, (list, tuple)) and
                len(remote_version) == 2)
    _ErrorIf(test, constants.CV_ENODERPC, node,
             "connection to node returned invalid data")
    if test:
      return False

    test = local_version != remote_version[0]
    _ErrorIf(test, constants.CV_ENODEVERSION, node,
             "incompatible protocol versions: master %s,"
             " node %s", local_version, remote_version[0])
    if test:
      return False

    # node seems compatible, we can actually try to look into its results

    # full package version
    self._ErrorIf(constants.RELEASE_VERSION != remote_version[1],
                  constants.CV_ENODEVERSION, node,
                  "software version mismatch: master %s, node %s",
                  constants.RELEASE_VERSION, remote_version[1],
                  code=self.ETYPE_WARNING)

    hyp_result = nresult.get(constants.NV_HYPERVISOR, None)
    if ninfo.vm_capable and isinstance(hyp_result, dict):
      for hv_name, hv_result in hyp_result.iteritems():
        test = hv_result is not None
        _ErrorIf(test, constants.CV_ENODEHV, node,
                 "hypervisor %s verify failure: '%s'", hv_name, hv_result)

    hvp_result = nresult.get(constants.NV_HVPARAMS, None)
    if ninfo.vm_capable and isinstance(hvp_result, list):
      for item, hv_name, hv_result in hvp_result:
        _ErrorIf(True, constants.CV_ENODEHV, node,
                 "hypervisor %s parameter verify failure (source %s): %s",
                 hv_name, item, hv_result)

    test = nresult.get(constants.NV_NODESETUP,
                       ["Missing NODESETUP results"])
    _ErrorIf(test, constants.CV_ENODESETUP, node, "node setup error: %s",
             "; ".join(test))

    return True

  def _VerifyNodeTime(self, ninfo, nresult,
                      nvinfo_starttime, nvinfo_endtime):
    """Check the node time.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nvinfo_starttime: the start time of the RPC call
    @param nvinfo_endtime: the end time of the RPC call

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    ntime = nresult.get(constants.NV_TIME, None)
    try:
      ntime_merged = utils.MergeTime(ntime)
    except (ValueError, TypeError):
      _ErrorIf(True, constants.CV_ENODETIME, node, "Node returned invalid time")
      return

    if ntime_merged < (nvinfo_starttime - constants.NODE_MAX_CLOCK_SKEW):
      ntime_diff = "%.01fs" % abs(nvinfo_starttime - ntime_merged)
    elif ntime_merged > (nvinfo_endtime + constants.NODE_MAX_CLOCK_SKEW):
      ntime_diff = "%.01fs" % abs(ntime_merged - nvinfo_endtime)
    else:
      ntime_diff = None

    _ErrorIf(ntime_diff is not None, constants.CV_ENODETIME, node,
             "Node time diverges by at least %s from master node time",
             ntime_diff)

  def _UpdateVerifyNodeLVM(self, ninfo, nresult, vg_name, nimg):
    """Check the node LVM results and update info for cross-node checks.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param vg_name: the configured VG name
    @type nimg: L{NodeImage}
    @param nimg: node image

    """
    if vg_name is None:
      return

    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    # checks vg existence and size > 20G
    vglist = nresult.get(constants.NV_VGLIST, None)
    test = not vglist
    _ErrorIf(test, constants.CV_ENODELVM, node, "unable to check volume groups")
    if not test:
      vgstatus = utils.CheckVolumeGroupSize(vglist, vg_name,
                                            constants.MIN_VG_SIZE)
      _ErrorIf(vgstatus, constants.CV_ENODELVM, node, vgstatus)

    # Check PVs
    (errmsgs, pvminmax) = _CheckNodePVs(nresult, self._exclusive_storage)
    for em in errmsgs:
      self._Error(constants.CV_ENODELVM, node, em)
    if pvminmax is not None:
      (nimg.pv_min, nimg.pv_max) = pvminmax

  def _VerifyGroupLVM(self, node_image, vg_name):
    """Check cross-node consistency in LVM.

    @type node_image: dict
    @param node_image: info about nodes, mapping from node to names to
      L{NodeImage} objects
    @param vg_name: the configured VG name

    """
    if vg_name is None:
      return

    # Only exlcusive storage needs this kind of checks
    if not self._exclusive_storage:
      return

    # exclusive_storage wants all PVs to have the same size (approximately),
    # if the smallest and the biggest ones are okay, everything is fine.
    # pv_min is None iff pv_max is None
    vals = filter((lambda ni: ni.pv_min is not None), node_image.values())
    if not vals:
      return
    (pvmin, minnode) = min((ni.pv_min, ni.name) for ni in vals)
    (pvmax, maxnode) = max((ni.pv_max, ni.name) for ni in vals)
    bad = utils.LvmExclusiveTestBadPvSizes(pvmin, pvmax)
    self._ErrorIf(bad, constants.CV_EGROUPDIFFERENTPVSIZE, self.group_info.name,
                  "PV sizes differ too much in the group; smallest (%s MB) is"
                  " on %s, biggest (%s MB) is on %s",
                  pvmin, minnode, pvmax, maxnode)

  def _VerifyNodeBridges(self, ninfo, nresult, bridges):
    """Check the node bridges.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param bridges: the expected list of bridges

    """
    if not bridges:
      return

    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    missing = nresult.get(constants.NV_BRIDGES, None)
    test = not isinstance(missing, list)
    _ErrorIf(test, constants.CV_ENODENET, node,
             "did not return valid bridge information")
    if not test:
      _ErrorIf(bool(missing), constants.CV_ENODENET, node,
               "missing bridges: %s" % utils.CommaJoin(sorted(missing)))

  def _VerifyNodeUserScripts(self, ninfo, nresult):
    """Check the results of user scripts presence and executability on the node

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    node = ninfo.name

    test = not constants.NV_USERSCRIPTS in nresult
    self._ErrorIf(test, constants.CV_ENODEUSERSCRIPTS, node,
                  "did not return user scripts information")

    broken_scripts = nresult.get(constants.NV_USERSCRIPTS, None)
    if not test:
      self._ErrorIf(broken_scripts, constants.CV_ENODEUSERSCRIPTS, node,
                    "user scripts not present or not executable: %s" %
                    utils.CommaJoin(sorted(broken_scripts)))

  def _VerifyNodeNetwork(self, ninfo, nresult):
    """Check the node network connectivity results.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    test = constants.NV_NODELIST not in nresult
    _ErrorIf(test, constants.CV_ENODESSH, node,
             "node hasn't returned node ssh connectivity data")
    if not test:
      if nresult[constants.NV_NODELIST]:
        for a_node, a_msg in nresult[constants.NV_NODELIST].items():
          _ErrorIf(True, constants.CV_ENODESSH, node,
                   "ssh communication with node '%s': %s", a_node, a_msg)

    test = constants.NV_NODENETTEST not in nresult
    _ErrorIf(test, constants.CV_ENODENET, node,
             "node hasn't returned node tcp connectivity data")
    if not test:
      if nresult[constants.NV_NODENETTEST]:
        nlist = utils.NiceSort(nresult[constants.NV_NODENETTEST].keys())
        for anode in nlist:
          _ErrorIf(True, constants.CV_ENODENET, node,
                   "tcp communication with node '%s': %s",
                   anode, nresult[constants.NV_NODENETTEST][anode])

    test = constants.NV_MASTERIP not in nresult
    _ErrorIf(test, constants.CV_ENODENET, node,
             "node hasn't returned node master IP reachability data")
    if not test:
      if not nresult[constants.NV_MASTERIP]:
        if node == self.master_node:
          msg = "the master node cannot reach the master IP (not configured?)"
        else:
          msg = "cannot reach the master IP"
        _ErrorIf(True, constants.CV_ENODENET, node, msg)

  def _VerifyInstance(self, instance, inst_config, node_image,
                      diskstatus):
    """Verify an instance.

    This function checks to see if the required block devices are
    available on the instance's node, and that the nodes are in the correct
    state.

    """
    _ErrorIf = self._ErrorIf # pylint: disable=C0103
    pnode = inst_config.primary_node
    pnode_img = node_image[pnode]
    groupinfo = self.cfg.GetAllNodeGroupsInfo()

    node_vol_should = {}
    inst_config.MapLVsByNode(node_vol_should)

    cluster = self.cfg.GetClusterInfo()
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                            self.group_info)
    err = _ComputeIPolicyInstanceViolation(ipolicy, inst_config, self.cfg)
    _ErrorIf(err, constants.CV_EINSTANCEPOLICY, instance, utils.CommaJoin(err),
             code=self.ETYPE_WARNING)

    for node in node_vol_should:
      n_img = node_image[node]
      if n_img.offline or n_img.rpc_fail or n_img.lvm_fail:
        # ignore missing volumes on offline or broken nodes
        continue
      for volume in node_vol_should[node]:
        test = volume not in n_img.volumes
        _ErrorIf(test, constants.CV_EINSTANCEMISSINGDISK, instance,
                 "volume %s missing on node %s", volume, node)

    if inst_config.admin_state == constants.ADMINST_UP:
      test = instance not in pnode_img.instances and not pnode_img.offline
      _ErrorIf(test, constants.CV_EINSTANCEDOWN, instance,
               "instance not running on its primary node %s",
               pnode)
      _ErrorIf(pnode_img.offline, constants.CV_EINSTANCEBADNODE, instance,
               "instance is marked as running and lives on offline node %s",
               pnode)

    diskdata = [(nname, success, status, idx)
                for (nname, disks) in diskstatus.items()
                for idx, (success, status) in enumerate(disks)]

    for nname, success, bdev_status, idx in diskdata:
      # the 'ghost node' construction in Exec() ensures that we have a
      # node here
      snode = node_image[nname]
      bad_snode = snode.ghost or snode.offline
      _ErrorIf(inst_config.admin_state == constants.ADMINST_UP and
               not success and not bad_snode,
               constants.CV_EINSTANCEFAULTYDISK, instance,
               "couldn't retrieve status for disk/%s on %s: %s",
               idx, nname, bdev_status)
      _ErrorIf((inst_config.admin_state == constants.ADMINST_UP and
                success and bdev_status.ldisk_status == constants.LDS_FAULTY),
               constants.CV_EINSTANCEFAULTYDISK, instance,
               "disk/%s on %s is faulty", idx, nname)

    _ErrorIf(pnode_img.rpc_fail and not pnode_img.offline,
             constants.CV_ENODERPC, pnode, "instance %s, connection to"
             " primary node failed", instance)

    _ErrorIf(len(inst_config.secondary_nodes) > 1,
             constants.CV_EINSTANCELAYOUT,
             instance, "instance has multiple secondary nodes: %s",
             utils.CommaJoin(inst_config.secondary_nodes),
             code=self.ETYPE_WARNING)

    if inst_config.disk_template not in constants.DTS_EXCL_STORAGE:
      # Disk template not compatible with exclusive_storage: no instance
      # node should have the flag set
      es_flags = rpc.GetExclusiveStorageForNodeNames(self.cfg,
                                                     inst_config.all_nodes)
      es_nodes = [n for (n, es) in es_flags.items()
                  if es]
      _ErrorIf(es_nodes, constants.CV_EINSTANCEUNSUITABLENODE, instance,
               "instance has template %s, which is not supported on nodes"
               " that have exclusive storage set: %s",
               inst_config.disk_template, utils.CommaJoin(es_nodes))

    if inst_config.disk_template in constants.DTS_INT_MIRROR:
      instance_nodes = utils.NiceSort(inst_config.all_nodes)
      instance_groups = {}

      for node in instance_nodes:
        instance_groups.setdefault(self.all_node_info[node].group,
                                   []).append(node)

      pretty_list = [
        "%s (group %s)" % (utils.CommaJoin(nodes), groupinfo[group].name)
        # Sort so that we always list the primary node first.
        for group, nodes in sorted(instance_groups.items(),
                                   key=lambda (_, nodes): pnode in nodes,
                                   reverse=True)]

      self._ErrorIf(len(instance_groups) > 1,
                    constants.CV_EINSTANCESPLITGROUPS,
                    instance, "instance has primary and secondary nodes in"
                    " different groups: %s", utils.CommaJoin(pretty_list),
                    code=self.ETYPE_WARNING)

    inst_nodes_offline = []
    for snode in inst_config.secondary_nodes:
      s_img = node_image[snode]
      _ErrorIf(s_img.rpc_fail and not s_img.offline, constants.CV_ENODERPC,
               snode, "instance %s, connection to secondary node failed",
               instance)

      if s_img.offline:
        inst_nodes_offline.append(snode)

    # warn that the instance lives on offline nodes
    _ErrorIf(inst_nodes_offline, constants.CV_EINSTANCEBADNODE, instance,
             "instance has offline secondary node(s) %s",
             utils.CommaJoin(inst_nodes_offline))
    # ... or ghost/non-vm_capable nodes
    for node in inst_config.all_nodes:
      _ErrorIf(node_image[node].ghost, constants.CV_EINSTANCEBADNODE,
               instance, "instance lives on ghost node %s", node)
      _ErrorIf(not node_image[node].vm_capable, constants.CV_EINSTANCEBADNODE,
               instance, "instance lives on non-vm_capable node %s", node)

  def _VerifyOrphanVolumes(self, node_vol_should, node_image, reserved):
    """Verify if there are any unknown volumes in the cluster.

    The .os, .swap and backup volumes are ignored. All other volumes are
    reported as unknown.

    @type reserved: L{ganeti.utils.FieldSet}
    @param reserved: a FieldSet of reserved volume names

    """
    for node, n_img in node_image.items():
      if (n_img.offline or n_img.rpc_fail or n_img.lvm_fail or
          self.all_node_info[node].group != self.group_uuid):
        # skip non-healthy nodes
        continue
      for volume in n_img.volumes:
        test = ((node not in node_vol_should or
                volume not in node_vol_should[node]) and
                not reserved.Matches(volume))
        self._ErrorIf(test, constants.CV_ENODEORPHANLV, node,
                      "volume %s is unknown", volume)

  def _VerifyNPlusOneMemory(self, node_image, instance_cfg):
    """Verify N+1 Memory Resilience.

    Check that if one single node dies we can still start all the
    instances it was primary for.

    """
    cluster_info = self.cfg.GetClusterInfo()
    for node, n_img in node_image.items():
      # This code checks that every node which is now listed as
      # secondary has enough memory to host all instances it is
      # supposed to should a single other node in the cluster fail.
      # FIXME: not ready for failover to an arbitrary node
      # FIXME: does not support file-backed instances
      # WARNING: we currently take into account down instances as well
      # as up ones, considering that even if they're down someone
      # might want to start them even in the event of a node failure.
      if n_img.offline or self.all_node_info[node].group != self.group_uuid:
        # we're skipping nodes marked offline and nodes in other groups from
        # the N+1 warning, since most likely we don't have good memory
        # infromation from them; we already list instances living on such
        # nodes, and that's enough warning
        continue
      #TODO(dynmem): also consider ballooning out other instances
      for prinode, instances in n_img.sbp.items():
        needed_mem = 0
        for instance in instances:
          bep = cluster_info.FillBE(instance_cfg[instance])
          if bep[constants.BE_AUTO_BALANCE]:
            needed_mem += bep[constants.BE_MINMEM]
        test = n_img.mfree < needed_mem
        self._ErrorIf(test, constants.CV_ENODEN1, node,
                      "not enough memory to accomodate instance failovers"
                      " should node %s fail (%dMiB needed, %dMiB available)",
                      prinode, needed_mem, n_img.mfree)

  @classmethod
  def _VerifyFiles(cls, errorif, nodeinfo, master_node, all_nvinfo,
                   (files_all, files_opt, files_mc, files_vm)):
    """Verifies file checksums collected from all nodes.

    @param errorif: Callback for reporting errors
    @param nodeinfo: List of L{objects.Node} objects
    @param master_node: Name of master node
    @param all_nvinfo: RPC results

    """
    # Define functions determining which nodes to consider for a file
    files2nodefn = [
      (files_all, None),
      (files_mc, lambda node: (node.master_candidate or
                               node.name == master_node)),
      (files_vm, lambda node: node.vm_capable),
      ]

    # Build mapping from filename to list of nodes which should have the file
    nodefiles = {}
    for (files, fn) in files2nodefn:
      if fn is None:
        filenodes = nodeinfo
      else:
        filenodes = filter(fn, nodeinfo)
      nodefiles.update((filename,
                        frozenset(map(operator.attrgetter("name"), filenodes)))
                       for filename in files)

    assert set(nodefiles) == (files_all | files_mc | files_vm)

    fileinfo = dict((filename, {}) for filename in nodefiles)
    ignore_nodes = set()

    for node in nodeinfo:
      if node.offline:
        ignore_nodes.add(node.name)
        continue

      nresult = all_nvinfo[node.name]

      if nresult.fail_msg or not nresult.payload:
        node_files = None
      else:
        fingerprints = nresult.payload.get(constants.NV_FILELIST, None)
        node_files = dict((vcluster.LocalizeVirtualPath(key), value)
                          for (key, value) in fingerprints.items())
        del fingerprints

      test = not (node_files and isinstance(node_files, dict))
      errorif(test, constants.CV_ENODEFILECHECK, node.name,
              "Node did not return file checksum data")
      if test:
        ignore_nodes.add(node.name)
        continue

      # Build per-checksum mapping from filename to nodes having it
      for (filename, checksum) in node_files.items():
        assert filename in nodefiles
        fileinfo[filename].setdefault(checksum, set()).add(node.name)

    for (filename, checksums) in fileinfo.items():
      assert compat.all(len(i) > 10 for i in checksums), "Invalid checksum"

      # Nodes having the file
      with_file = frozenset(node_name
                            for nodes in fileinfo[filename].values()
                            for node_name in nodes) - ignore_nodes

      expected_nodes = nodefiles[filename] - ignore_nodes

      # Nodes missing file
      missing_file = expected_nodes - with_file

      if filename in files_opt:
        # All or no nodes
        errorif(missing_file and missing_file != expected_nodes,
                constants.CV_ECLUSTERFILECHECK, None,
                "File %s is optional, but it must exist on all or no"
                " nodes (not found on %s)",
                filename, utils.CommaJoin(utils.NiceSort(missing_file)))
      else:
        errorif(missing_file, constants.CV_ECLUSTERFILECHECK, None,
                "File %s is missing from node(s) %s", filename,
                utils.CommaJoin(utils.NiceSort(missing_file)))

        # Warn if a node has a file it shouldn't
        unexpected = with_file - expected_nodes
        errorif(unexpected,
                constants.CV_ECLUSTERFILECHECK, None,
                "File %s should not exist on node(s) %s",
                filename, utils.CommaJoin(utils.NiceSort(unexpected)))

      # See if there are multiple versions of the file
      test = len(checksums) > 1
      if test:
        variants = ["variant %s on %s" %
                    (idx + 1, utils.CommaJoin(utils.NiceSort(nodes)))
                    for (idx, (checksum, nodes)) in
                      enumerate(sorted(checksums.items()))]
      else:
        variants = []

      errorif(test, constants.CV_ECLUSTERFILECHECK, None,
              "File %s found with %s different checksums (%s)",
              filename, len(checksums), "; ".join(variants))

  def _VerifyNodeDrbd(self, ninfo, nresult, instanceinfo, drbd_helper,
                      drbd_map):
    """Verifies and the node DRBD status.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param instanceinfo: the dict of instances
    @param drbd_helper: the configured DRBD usermode helper
    @param drbd_map: the DRBD map as returned by
        L{ganeti.config.ConfigWriter.ComputeDRBDMap}

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    if drbd_helper:
      helper_result = nresult.get(constants.NV_DRBDHELPER, None)
      test = (helper_result is None)
      _ErrorIf(test, constants.CV_ENODEDRBDHELPER, node,
               "no drbd usermode helper returned")
      if helper_result:
        status, payload = helper_result
        test = not status
        _ErrorIf(test, constants.CV_ENODEDRBDHELPER, node,
                 "drbd usermode helper check unsuccessful: %s", payload)
        test = status and (payload != drbd_helper)
        _ErrorIf(test, constants.CV_ENODEDRBDHELPER, node,
                 "wrong drbd usermode helper: %s", payload)

    # compute the DRBD minors
    node_drbd = {}
    for minor, instance in drbd_map[node].items():
      test = instance not in instanceinfo
      _ErrorIf(test, constants.CV_ECLUSTERCFG, None,
               "ghost instance '%s' in temporary DRBD map", instance)
        # ghost instance should not be running, but otherwise we
        # don't give double warnings (both ghost instance and
        # unallocated minor in use)
      if test:
        node_drbd[minor] = (instance, False)
      else:
        instance = instanceinfo[instance]
        node_drbd[minor] = (instance.name,
                            instance.admin_state == constants.ADMINST_UP)

    # and now check them
    used_minors = nresult.get(constants.NV_DRBDLIST, [])
    test = not isinstance(used_minors, (tuple, list))
    _ErrorIf(test, constants.CV_ENODEDRBD, node,
             "cannot parse drbd status file: %s", str(used_minors))
    if test:
      # we cannot check drbd status
      return

    for minor, (iname, must_exist) in node_drbd.items():
      test = minor not in used_minors and must_exist
      _ErrorIf(test, constants.CV_ENODEDRBD, node,
               "drbd minor %d of instance %s is not active", minor, iname)
    for minor in used_minors:
      test = minor not in node_drbd
      _ErrorIf(test, constants.CV_ENODEDRBD, node,
               "unallocated drbd minor %d is in use", minor)

  def _UpdateNodeOS(self, ninfo, nresult, nimg):
    """Builds the node OS structures.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    remote_os = nresult.get(constants.NV_OSLIST, None)
    test = (not isinstance(remote_os, list) or
            not compat.all(isinstance(v, list) and len(v) == 7
                           for v in remote_os))

    _ErrorIf(test, constants.CV_ENODEOS, node,
             "node hasn't returned valid OS data")

    nimg.os_fail = test

    if test:
      return

    os_dict = {}

    for (name, os_path, status, diagnose,
         variants, parameters, api_ver) in nresult[constants.NV_OSLIST]:

      if name not in os_dict:
        os_dict[name] = []

      # parameters is a list of lists instead of list of tuples due to
      # JSON lacking a real tuple type, fix it:
      parameters = [tuple(v) for v in parameters]
      os_dict[name].append((os_path, status, diagnose,
                            set(variants), set(parameters), set(api_ver)))

    nimg.oslist = os_dict

  def _VerifyNodeOS(self, ninfo, nimg, base):
    """Verifies the node OS list.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nimg: the node image object
    @param base: the 'template' node we match against (e.g. from the master)

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    assert not nimg.os_fail, "Entered _VerifyNodeOS with failed OS rpc?"

    beautify_params = lambda l: ["%s: %s" % (k, v) for (k, v) in l]
    for os_name, os_data in nimg.oslist.items():
      assert os_data, "Empty OS status for OS %s?!" % os_name
      f_path, f_status, f_diag, f_var, f_param, f_api = os_data[0]
      _ErrorIf(not f_status, constants.CV_ENODEOS, node,
               "Invalid OS %s (located at %s): %s", os_name, f_path, f_diag)
      _ErrorIf(len(os_data) > 1, constants.CV_ENODEOS, node,
               "OS '%s' has multiple entries (first one shadows the rest): %s",
               os_name, utils.CommaJoin([v[0] for v in os_data]))
      # comparisons with the 'base' image
      test = os_name not in base.oslist
      _ErrorIf(test, constants.CV_ENODEOS, node,
               "Extra OS %s not present on reference node (%s)",
               os_name, base.name)
      if test:
        continue
      assert base.oslist[os_name], "Base node has empty OS status?"
      _, b_status, _, b_var, b_param, b_api = base.oslist[os_name][0]
      if not b_status:
        # base OS is invalid, skipping
        continue
      for kind, a, b in [("API version", f_api, b_api),
                         ("variants list", f_var, b_var),
                         ("parameters", beautify_params(f_param),
                          beautify_params(b_param))]:
        _ErrorIf(a != b, constants.CV_ENODEOS, node,
                 "OS %s for %s differs from reference node %s: [%s] vs. [%s]",
                 kind, os_name, base.name,
                 utils.CommaJoin(sorted(a)), utils.CommaJoin(sorted(b)))

    # check any missing OSes
    missing = set(base.oslist.keys()).difference(nimg.oslist.keys())
    _ErrorIf(missing, constants.CV_ENODEOS, node,
             "OSes present on reference node %s but missing on this node: %s",
             base.name, utils.CommaJoin(missing))

  def _VerifyFileStoragePaths(self, ninfo, nresult, is_master):
    """Verifies paths in L{pathutils.FILE_STORAGE_PATHS_FILE}.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @type is_master: bool
    @param is_master: Whether node is the master node

    """
    node = ninfo.name

    if (is_master and
        (constants.ENABLE_FILE_STORAGE or
         constants.ENABLE_SHARED_FILE_STORAGE)):
      try:
        fspaths = nresult[constants.NV_FILE_STORAGE_PATHS]
      except KeyError:
        # This should never happen
        self._ErrorIf(True, constants.CV_ENODEFILESTORAGEPATHS, node,
                      "Node did not return forbidden file storage paths")
      else:
        self._ErrorIf(fspaths, constants.CV_ENODEFILESTORAGEPATHS, node,
                      "Found forbidden file storage paths: %s",
                      utils.CommaJoin(fspaths))
    else:
      self._ErrorIf(constants.NV_FILE_STORAGE_PATHS in nresult,
                    constants.CV_ENODEFILESTORAGEPATHS, node,
                    "Node should not have returned forbidden file storage"
                    " paths")

  def _VerifyOob(self, ninfo, nresult):
    """Verifies out of band functionality of a node.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    node = ninfo.name
    # We just have to verify the paths on master and/or master candidates
    # as the oob helper is invoked on the master
    if ((ninfo.master_candidate or ninfo.master_capable) and
        constants.NV_OOB_PATHS in nresult):
      for path_result in nresult[constants.NV_OOB_PATHS]:
        self._ErrorIf(path_result, constants.CV_ENODEOOBPATH, node, path_result)

  def _UpdateNodeVolumes(self, ninfo, nresult, nimg, vg_name):
    """Verifies and updates the node volume data.

    This function will update a L{NodeImage}'s internal structures
    with data from the remote call.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object
    @param vg_name: the configured VG name

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    nimg.lvm_fail = True
    lvdata = nresult.get(constants.NV_LVLIST, "Missing LV data")
    if vg_name is None:
      pass
    elif isinstance(lvdata, basestring):
      _ErrorIf(True, constants.CV_ENODELVM, node, "LVM problem on node: %s",
               utils.SafeEncode(lvdata))
    elif not isinstance(lvdata, dict):
      _ErrorIf(True, constants.CV_ENODELVM, node,
               "rpc call to node failed (lvlist)")
    else:
      nimg.volumes = lvdata
      nimg.lvm_fail = False

  def _UpdateNodeInstances(self, ninfo, nresult, nimg):
    """Verifies and updates the node instance list.

    If the listing was successful, then updates this node's instance
    list. Otherwise, it marks the RPC call as failed for the instance
    list key.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object

    """
    idata = nresult.get(constants.NV_INSTANCELIST, None)
    test = not isinstance(idata, list)
    self._ErrorIf(test, constants.CV_ENODEHV, ninfo.name,
                  "rpc call to node failed (instancelist): %s",
                  utils.SafeEncode(str(idata)))
    if test:
      nimg.hyp_fail = True
    else:
      nimg.instances = idata

  def _UpdateNodeInfo(self, ninfo, nresult, nimg, vg_name):
    """Verifies and computes a node information map

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object
    @param vg_name: the configured VG name

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    # try to read free memory (from the hypervisor)
    hv_info = nresult.get(constants.NV_HVINFO, None)
    test = not isinstance(hv_info, dict) or "memory_free" not in hv_info
    _ErrorIf(test, constants.CV_ENODEHV, node,
             "rpc call to node failed (hvinfo)")
    if not test:
      try:
        nimg.mfree = int(hv_info["memory_free"])
      except (ValueError, TypeError):
        _ErrorIf(True, constants.CV_ENODERPC, node,
                 "node returned invalid nodeinfo, check hypervisor")

    # FIXME: devise a free space model for file based instances as well
    if vg_name is not None:
      test = (constants.NV_VGLIST not in nresult or
              vg_name not in nresult[constants.NV_VGLIST])
      _ErrorIf(test, constants.CV_ENODELVM, node,
               "node didn't return data for the volume group '%s'"
               " - it is either missing or broken", vg_name)
      if not test:
        try:
          nimg.dfree = int(nresult[constants.NV_VGLIST][vg_name])
        except (ValueError, TypeError):
          _ErrorIf(True, constants.CV_ENODERPC, node,
                   "node returned invalid LVM info, check LVM status")

  def _CollectDiskInfo(self, nodelist, node_image, instanceinfo):
    """Gets per-disk status information for all instances.

    @type nodelist: list of strings
    @param nodelist: Node names
    @type node_image: dict of (name, L{objects.Node})
    @param node_image: Node objects
    @type instanceinfo: dict of (name, L{objects.Instance})
    @param instanceinfo: Instance objects
    @rtype: {instance: {node: [(succes, payload)]}}
    @return: a dictionary of per-instance dictionaries with nodes as
        keys and disk information as values; the disk information is a
        list of tuples (success, payload)

    """
    _ErrorIf = self._ErrorIf # pylint: disable=C0103

    node_disks = {}
    node_disks_devonly = {}
    diskless_instances = set()
    diskless = constants.DT_DISKLESS

    for nname in nodelist:
      node_instances = list(itertools.chain(node_image[nname].pinst,
                                            node_image[nname].sinst))
      diskless_instances.update(inst for inst in node_instances
                                if instanceinfo[inst].disk_template == diskless)
      disks = [(inst, disk)
               for inst in node_instances
               for disk in instanceinfo[inst].disks]

      if not disks:
        # No need to collect data
        continue

      node_disks[nname] = disks

      # _AnnotateDiskParams makes already copies of the disks
      devonly = []
      for (inst, dev) in disks:
        (anno_disk,) = _AnnotateDiskParams(instanceinfo[inst], [dev], self.cfg)
        self.cfg.SetDiskID(anno_disk, nname)
        devonly.append(anno_disk)

      node_disks_devonly[nname] = devonly

    assert len(node_disks) == len(node_disks_devonly)

    # Collect data from all nodes with disks
    result = self.rpc.call_blockdev_getmirrorstatus_multi(node_disks.keys(),
                                                          node_disks_devonly)

    assert len(result) == len(node_disks)

    instdisk = {}

    for (nname, nres) in result.items():
      disks = node_disks[nname]

      if nres.offline:
        # No data from this node
        data = len(disks) * [(False, "node offline")]
      else:
        msg = nres.fail_msg
        _ErrorIf(msg, constants.CV_ENODERPC, nname,
                 "while getting disk information: %s", msg)
        if msg:
          # No data from this node
          data = len(disks) * [(False, msg)]
        else:
          data = []
          for idx, i in enumerate(nres.payload):
            if isinstance(i, (tuple, list)) and len(i) == 2:
              data.append(i)
            else:
              logging.warning("Invalid result from node %s, entry %d: %s",
                              nname, idx, i)
              data.append((False, "Invalid result from the remote node"))

      for ((inst, _), status) in zip(disks, data):
        instdisk.setdefault(inst, {}).setdefault(nname, []).append(status)

    # Add empty entries for diskless instances.
    for inst in diskless_instances:
      assert inst not in instdisk
      instdisk[inst] = {}

    assert compat.all(len(statuses) == len(instanceinfo[inst].disks) and
                      len(nnames) <= len(instanceinfo[inst].all_nodes) and
                      compat.all(isinstance(s, (tuple, list)) and
                                 len(s) == 2 for s in statuses)
                      for inst, nnames in instdisk.items()
                      for nname, statuses in nnames.items())
    if __debug__:
      instdisk_keys = set(instdisk)
      instanceinfo_keys = set(instanceinfo)
      assert instdisk_keys == instanceinfo_keys, \
        ("instdisk keys (%s) do not match instanceinfo keys (%s)" %
         (instdisk_keys, instanceinfo_keys))

    return instdisk

  @staticmethod
  def _SshNodeSelector(group_uuid, all_nodes):
    """Create endless iterators for all potential SSH check hosts.

    """
    nodes = [node for node in all_nodes
             if (node.group != group_uuid and
                 not node.offline)]
    keyfunc = operator.attrgetter("group")

    return map(itertools.cycle,
               [sorted(map(operator.attrgetter("name"), names))
                for _, names in itertools.groupby(sorted(nodes, key=keyfunc),
                                                  keyfunc)])

  @classmethod
  def _SelectSshCheckNodes(cls, group_nodes, group_uuid, all_nodes):
    """Choose which nodes should talk to which other nodes.

    We will make nodes contact all nodes in their group, and one node from
    every other group.

    @warning: This algorithm has a known issue if one node group is much
      smaller than others (e.g. just one node). In such a case all other
      nodes will talk to the single node.

    """
    online_nodes = sorted(node.name for node in group_nodes if not node.offline)
    sel = cls._SshNodeSelector(group_uuid, all_nodes)

    return (online_nodes,
            dict((name, sorted([i.next() for i in sel]))
                 for name in online_nodes))

  def BuildHooksEnv(self):
    """Build hooks env.

    Cluster-Verify hooks just ran in the post phase and their failure makes
    the output be logged in the verify output and the verification to fail.

    """
    env = {
      "CLUSTER_TAGS": " ".join(self.cfg.GetClusterInfo().GetTags()),
      }

    env.update(("NODE_TAGS_%s" % node.name, " ".join(node.GetTags()))
               for node in self.my_node_info.values())

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([], self.my_node_names)

  def Exec(self, feedback_fn):
    """Verify integrity of the node group, performing various test on nodes.

    """
    # This method has too many local variables. pylint: disable=R0914
    feedback_fn("* Verifying group '%s'" % self.group_info.name)

    if not self.my_node_names:
      # empty node group
      feedback_fn("* Empty node group, skipping verification")
      return True

    self.bad = False
    _ErrorIf = self._ErrorIf # pylint: disable=C0103
    verbose = self.op.verbose
    self._feedback_fn = feedback_fn

    vg_name = self.cfg.GetVGName()
    drbd_helper = self.cfg.GetDRBDHelper()
    cluster = self.cfg.GetClusterInfo()
    hypervisors = cluster.enabled_hypervisors
    node_data_list = [self.my_node_info[name] for name in self.my_node_names]

    i_non_redundant = [] # Non redundant instances
    i_non_a_balanced = [] # Non auto-balanced instances
    i_offline = 0 # Count of offline instances
    n_offline = 0 # Count of offline nodes
    n_drained = 0 # Count of nodes being drained
    node_vol_should = {}

    # FIXME: verify OS list

    # File verification
    filemap = _ComputeAncillaryFiles(cluster, False)

    # do local checksums
    master_node = self.master_node = self.cfg.GetMasterNode()
    master_ip = self.cfg.GetMasterIP()

    feedback_fn("* Gathering data (%d nodes)" % len(self.my_node_names))

    user_scripts = []
    if self.cfg.GetUseExternalMipScript():
      user_scripts.append(pathutils.EXTERNAL_MASTER_SETUP_SCRIPT)

    node_verify_param = {
      constants.NV_FILELIST:
        map(vcluster.MakeVirtualPath,
            utils.UniqueSequence(filename
                                 for files in filemap
                                 for filename in files)),
      constants.NV_NODELIST:
        self._SelectSshCheckNodes(node_data_list, self.group_uuid,
                                  self.all_node_info.values()),
      constants.NV_HYPERVISOR: hypervisors,
      constants.NV_HVPARAMS:
        _GetAllHypervisorParameters(cluster, self.all_inst_info.values()),
      constants.NV_NODENETTEST: [(node.name, node.primary_ip, node.secondary_ip)
                                 for node in node_data_list
                                 if not node.offline],
      constants.NV_INSTANCELIST: hypervisors,
      constants.NV_VERSION: None,
      constants.NV_HVINFO: self.cfg.GetHypervisorType(),
      constants.NV_NODESETUP: None,
      constants.NV_TIME: None,
      constants.NV_MASTERIP: (master_node, master_ip),
      constants.NV_OSLIST: None,
      constants.NV_VMNODES: self.cfg.GetNonVmCapableNodeList(),
      constants.NV_USERSCRIPTS: user_scripts,
      }

    if vg_name is not None:
      node_verify_param[constants.NV_VGLIST] = None
      node_verify_param[constants.NV_LVLIST] = vg_name
      node_verify_param[constants.NV_PVLIST] = [vg_name]

    if drbd_helper:
      node_verify_param[constants.NV_DRBDLIST] = None
      node_verify_param[constants.NV_DRBDHELPER] = drbd_helper

    if constants.ENABLE_FILE_STORAGE or constants.ENABLE_SHARED_FILE_STORAGE:
      # Load file storage paths only from master node
      node_verify_param[constants.NV_FILE_STORAGE_PATHS] = master_node

    # bridge checks
    # FIXME: this needs to be changed per node-group, not cluster-wide
    bridges = set()
    default_nicpp = cluster.nicparams[constants.PP_DEFAULT]
    if default_nicpp[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
      bridges.add(default_nicpp[constants.NIC_LINK])
    for instance in self.my_inst_info.values():
      for nic in instance.nics:
        full_nic = cluster.SimpleFillNIC(nic.nicparams)
        if full_nic[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
          bridges.add(full_nic[constants.NIC_LINK])

    if bridges:
      node_verify_param[constants.NV_BRIDGES] = list(bridges)

    # Build our expected cluster state
    node_image = dict((node.name, self.NodeImage(offline=node.offline,
                                                 name=node.name,
                                                 vm_capable=node.vm_capable))
                      for node in node_data_list)

    # Gather OOB paths
    oob_paths = []
    for node in self.all_node_info.values():
      path = _SupportsOob(self.cfg, node)
      if path and path not in oob_paths:
        oob_paths.append(path)

    if oob_paths:
      node_verify_param[constants.NV_OOB_PATHS] = oob_paths

    for instance in self.my_inst_names:
      inst_config = self.my_inst_info[instance]
      if inst_config.admin_state == constants.ADMINST_OFFLINE:
        i_offline += 1

      for nname in inst_config.all_nodes:
        if nname not in node_image:
          gnode = self.NodeImage(name=nname)
          gnode.ghost = (nname not in self.all_node_info)
          node_image[nname] = gnode

      inst_config.MapLVsByNode(node_vol_should)

      pnode = inst_config.primary_node
      node_image[pnode].pinst.append(instance)

      for snode in inst_config.secondary_nodes:
        nimg = node_image[snode]
        nimg.sinst.append(instance)
        if pnode not in nimg.sbp:
          nimg.sbp[pnode] = []
        nimg.sbp[pnode].append(instance)

    es_flags = rpc.GetExclusiveStorageForNodeNames(self.cfg, self.my_node_names)
    # The value of exclusive_storage should be the same across the group, so if
    # it's True for at least a node, we act as if it were set for all the nodes
    self._exclusive_storage = compat.any(es_flags.values())
    if self._exclusive_storage:
      node_verify_param[constants.NV_EXCLUSIVEPVS] = True

    # At this point, we have the in-memory data structures complete,
    # except for the runtime information, which we'll gather next

    # Due to the way our RPC system works, exact response times cannot be
    # guaranteed (e.g. a broken node could run into a timeout). By keeping the
    # time before and after executing the request, we can at least have a time
    # window.
    nvinfo_starttime = time.time()
    all_nvinfo = self.rpc.call_node_verify(self.my_node_names,
                                           node_verify_param,
                                           self.cfg.GetClusterName())
    nvinfo_endtime = time.time()

    if self.extra_lv_nodes and vg_name is not None:
      extra_lv_nvinfo = \
          self.rpc.call_node_verify(self.extra_lv_nodes,
                                    {constants.NV_LVLIST: vg_name},
                                    self.cfg.GetClusterName())
    else:
      extra_lv_nvinfo = {}

    all_drbd_map = self.cfg.ComputeDRBDMap()

    feedback_fn("* Gathering disk information (%s nodes)" %
                len(self.my_node_names))
    instdisk = self._CollectDiskInfo(self.my_node_names, node_image,
                                     self.my_inst_info)

    feedback_fn("* Verifying configuration file consistency")

    # If not all nodes are being checked, we need to make sure the master node
    # and a non-checked vm_capable node are in the list.
    absent_nodes = set(self.all_node_info).difference(self.my_node_info)
    if absent_nodes:
      vf_nvinfo = all_nvinfo.copy()
      vf_node_info = list(self.my_node_info.values())
      additional_nodes = []
      if master_node not in self.my_node_info:
        additional_nodes.append(master_node)
        vf_node_info.append(self.all_node_info[master_node])
      # Add the first vm_capable node we find which is not included,
      # excluding the master node (which we already have)
      for node in absent_nodes:
        nodeinfo = self.all_node_info[node]
        if (nodeinfo.vm_capable and not nodeinfo.offline and
            node != master_node):
          additional_nodes.append(node)
          vf_node_info.append(self.all_node_info[node])
          break
      key = constants.NV_FILELIST
      vf_nvinfo.update(self.rpc.call_node_verify(additional_nodes,
                                                 {key: node_verify_param[key]},
                                                 self.cfg.GetClusterName()))
    else:
      vf_nvinfo = all_nvinfo
      vf_node_info = self.my_node_info.values()

    self._VerifyFiles(_ErrorIf, vf_node_info, master_node, vf_nvinfo, filemap)

    feedback_fn("* Verifying node status")

    refos_img = None

    for node_i in node_data_list:
      node = node_i.name
      nimg = node_image[node]

      if node_i.offline:
        if verbose:
          feedback_fn("* Skipping offline node %s" % (node,))
        n_offline += 1
        continue

      if node == master_node:
        ntype = "master"
      elif node_i.master_candidate:
        ntype = "master candidate"
      elif node_i.drained:
        ntype = "drained"
        n_drained += 1
      else:
        ntype = "regular"
      if verbose:
        feedback_fn("* Verifying node %s (%s)" % (node, ntype))

      msg = all_nvinfo[node].fail_msg
      _ErrorIf(msg, constants.CV_ENODERPC, node, "while contacting node: %s",
               msg)
      if msg:
        nimg.rpc_fail = True
        continue

      nresult = all_nvinfo[node].payload

      nimg.call_ok = self._VerifyNode(node_i, nresult)
      self._VerifyNodeTime(node_i, nresult, nvinfo_starttime, nvinfo_endtime)
      self._VerifyNodeNetwork(node_i, nresult)
      self._VerifyNodeUserScripts(node_i, nresult)
      self._VerifyOob(node_i, nresult)
      self._VerifyFileStoragePaths(node_i, nresult,
                                   node == master_node)

      if nimg.vm_capable:
        self._UpdateVerifyNodeLVM(node_i, nresult, vg_name, nimg)
        self._VerifyNodeDrbd(node_i, nresult, self.all_inst_info, drbd_helper,
                             all_drbd_map)

        self._UpdateNodeVolumes(node_i, nresult, nimg, vg_name)
        self._UpdateNodeInstances(node_i, nresult, nimg)
        self._UpdateNodeInfo(node_i, nresult, nimg, vg_name)
        self._UpdateNodeOS(node_i, nresult, nimg)

        if not nimg.os_fail:
          if refos_img is None:
            refos_img = nimg
          self._VerifyNodeOS(node_i, nimg, refos_img)
        self._VerifyNodeBridges(node_i, nresult, bridges)

        # Check whether all running instancies are primary for the node. (This
        # can no longer be done from _VerifyInstance below, since some of the
        # wrong instances could be from other node groups.)
        non_primary_inst = set(nimg.instances).difference(nimg.pinst)

        for inst in non_primary_inst:
          test = inst in self.all_inst_info
          _ErrorIf(test, constants.CV_EINSTANCEWRONGNODE, inst,
                   "instance should not run on node %s", node_i.name)
          _ErrorIf(not test, constants.CV_ENODEORPHANINSTANCE, node_i.name,
                   "node is running unknown instance %s", inst)

    self._VerifyGroupLVM(node_image, vg_name)

    for node, result in extra_lv_nvinfo.items():
      self._UpdateNodeVolumes(self.all_node_info[node], result.payload,
                              node_image[node], vg_name)

    feedback_fn("* Verifying instance status")
    for instance in self.my_inst_names:
      if verbose:
        feedback_fn("* Verifying instance %s" % instance)
      inst_config = self.my_inst_info[instance]
      self._VerifyInstance(instance, inst_config, node_image,
                           instdisk[instance])

      # If the instance is non-redundant we cannot survive losing its primary
      # node, so we are not N+1 compliant.
      if inst_config.disk_template not in constants.DTS_MIRRORED:
        i_non_redundant.append(instance)

      if not cluster.FillBE(inst_config)[constants.BE_AUTO_BALANCE]:
        i_non_a_balanced.append(instance)

    feedback_fn("* Verifying orphan volumes")
    reserved = utils.FieldSet(*cluster.reserved_lvs)

    # We will get spurious "unknown volume" warnings if any node of this group
    # is secondary for an instance whose primary is in another group. To avoid
    # them, we find these instances and add their volumes to node_vol_should.
    for inst in self.all_inst_info.values():
      for secondary in inst.secondary_nodes:
        if (secondary in self.my_node_info
            and inst.name not in self.my_inst_info):
          inst.MapLVsByNode(node_vol_should)
          break

    self._VerifyOrphanVolumes(node_vol_should, node_image, reserved)

    if constants.VERIFY_NPLUSONE_MEM not in self.op.skip_checks:
      feedback_fn("* Verifying N+1 Memory redundancy")
      self._VerifyNPlusOneMemory(node_image, self.my_inst_info)

    feedback_fn("* Other Notes")
    if i_non_redundant:
      feedback_fn("  - NOTICE: %d non-redundant instance(s) found."
                  % len(i_non_redundant))

    if i_non_a_balanced:
      feedback_fn("  - NOTICE: %d non-auto-balanced instance(s) found."
                  % len(i_non_a_balanced))

    if i_offline:
      feedback_fn("  - NOTICE: %d offline instance(s) found." % i_offline)

    if n_offline:
      feedback_fn("  - NOTICE: %d offline node(s) found." % n_offline)

    if n_drained:
      feedback_fn("  - NOTICE: %d drained node(s) found." % n_drained)

    return not self.bad

  def HooksCallBack(self, phase, hooks_results, feedback_fn, lu_result):
    """Analyze the post-hooks' result

    This method analyses the hook result, handles it, and sends some
    nicely-formatted feedback back to the user.

    @param phase: one of L{constants.HOOKS_PHASE_POST} or
        L{constants.HOOKS_PHASE_PRE}; it denotes the hooks phase
    @param hooks_results: the results of the multi-node hooks rpc call
    @param feedback_fn: function used send feedback back to the caller
    @param lu_result: previous Exec result
    @return: the new Exec result, based on the previous result
        and hook results

    """
    # We only really run POST phase hooks, only for non-empty groups,
    # and are only interested in their results
    if not self.my_node_names:
      # empty node group
      pass
    elif phase == constants.HOOKS_PHASE_POST:
      # Used to change hooks' output to proper indentation
      feedback_fn("* Hooks Results")
      assert hooks_results, "invalid result from hooks"

      for node_name in hooks_results:
        res = hooks_results[node_name]
        msg = res.fail_msg
        test = msg and not res.offline
        self._ErrorIf(test, constants.CV_ENODEHOOKS, node_name,
                      "Communication failure in hooks execution: %s", msg)
        if res.offline or msg:
          # No need to investigate payload if node is offline or gave
          # an error.
          continue
        for script, hkr, output in res.payload:
          test = hkr == constants.HKR_FAIL
          self._ErrorIf(test, constants.CV_ENODEHOOKS, node_name,
                        "Script %s failed, output:", script)
          if test:
            output = self._HOOKS_INDENT_RE.sub("      ", output)
            feedback_fn("%s" % output)
            lu_result = False

    return lu_result


class LUClusterVerifyDisks(NoHooksLU):
  """Verifies the cluster disks status.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = _ShareAll()
    self.needed_locks = {
      locking.LEVEL_NODEGROUP: locking.ALL_SET,
      }

  def Exec(self, feedback_fn):
    group_names = self.owned_locks(locking.LEVEL_NODEGROUP)

    # Submit one instance of L{opcodes.OpGroupVerifyDisks} per node group
    return ResultWithJobs([[opcodes.OpGroupVerifyDisks(group_name=group)]
                           for group in group_names])


class LUGroupVerifyDisks(NoHooksLU):
  """Verifies the status of all disks in a node group.

  """
  REQ_BGL = False

  def ExpandNames(self):
    # Raises errors.OpPrereqError on its own if group can't be found
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    self.share_locks = _ShareAll()
    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],

      # This opcode is acquires all node locks in a group. LUClusterVerifyDisks
      # starts one instance of this opcode for every group, which means all
      # nodes will be locked for a short amount of time, so it's better to
      # acquire the node allocation lock as well.
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

  def DeclareLocks(self, level):
    if level == locking.LEVEL_INSTANCE:
      assert not self.needed_locks[locking.LEVEL_INSTANCE]

      # Lock instances optimistically, needs verification once node and group
      # locks have been acquired
      self.needed_locks[locking.LEVEL_INSTANCE] = \
        self.cfg.GetNodeGroupInstances(self.group_uuid)

    elif level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        set([self.group_uuid] +
            # Lock all groups used by instances optimistically; this requires
            # going via the node before it's locked, requiring verification
            # later on
            [group_uuid
             for instance_name in self.owned_locks(locking.LEVEL_INSTANCE)
             for group_uuid in self.cfg.GetInstanceNodeGroups(instance_name)])

    elif level == locking.LEVEL_NODE:
      # This will only lock the nodes in the group to be verified which contain
      # actual instances
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
      self._LockInstancesNodes()

      # Lock all nodes in group to be verified
      assert self.group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)
      member_nodes = self.cfg.GetNodeGroup(self.group_uuid).members
      self.needed_locks[locking.LEVEL_NODE].extend(member_nodes)

  def CheckPrereq(self):
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    _CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instances)

    # Get instance information
    self.instances = dict(self.cfg.GetMultiInstanceInfo(owned_instances))

    # Check if node groups for locked instances are still correct
    _CheckInstancesNodeGroups(self.cfg, self.instances,
                              owned_groups, owned_nodes, self.group_uuid)

  def Exec(self, feedback_fn):
    """Verify integrity of cluster disks.

    @rtype: tuple of three items
    @return: a tuple of (dict of node-to-node_error, list of instances
        which need activate-disks, dict of instance: (node, volume) for
        missing volumes

    """
    res_nodes = {}
    res_instances = set()
    res_missing = {}

    nv_dict = _MapInstanceDisksToNodes(
      [inst for inst in self.instances.values()
       if inst.admin_state == constants.ADMINST_UP])

    if nv_dict:
      nodes = utils.NiceSort(set(self.owned_locks(locking.LEVEL_NODE)) &
                             set(self.cfg.GetVmCapableNodeList()))

      node_lvs = self.rpc.call_lv_list(nodes, [])

      for (node, node_res) in node_lvs.items():
        if node_res.offline:
          continue

        msg = node_res.fail_msg
        if msg:
          logging.warning("Error enumerating LVs on node %s: %s", node, msg)
          res_nodes[node] = msg
          continue

        for lv_name, (_, _, lv_online) in node_res.payload.items():
          inst = nv_dict.pop((node, lv_name), None)
          if not (lv_online or inst is None):
            res_instances.add(inst)

      # any leftover items in nv_dict are missing LVs, let's arrange the data
      # better
      for key, inst in nv_dict.iteritems():
        res_missing.setdefault(inst, []).append(list(key))

    return (res_nodes, list(res_instances), res_missing)


class LUClusterRepairDiskSizes(NoHooksLU):
  """Verifies the cluster disks sizes.

  """
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.instances:
      self.wanted_names = _GetWantedInstances(self, self.op.instances)
      # Not getting the node allocation lock as only a specific set of
      # instances (and their nodes) is going to be acquired
      self.needed_locks = {
        locking.LEVEL_NODE_RES: [],
        locking.LEVEL_INSTANCE: self.wanted_names,
        }
      self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE
    else:
      self.wanted_names = None
      self.needed_locks = {
        locking.LEVEL_NODE_RES: locking.ALL_SET,
        locking.LEVEL_INSTANCE: locking.ALL_SET,

        # This opcode is acquires the node locks for all instances
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }

    self.share_locks = {
      locking.LEVEL_NODE_RES: 1,
      locking.LEVEL_INSTANCE: 0,
      locking.LEVEL_NODE_ALLOC: 1,
      }

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE_RES and self.wanted_names is not None:
      self._LockInstancesNodes(primary_only=True, level=level)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    if self.wanted_names is None:
      self.wanted_names = self.owned_locks(locking.LEVEL_INSTANCE)

    self.wanted_instances = \
        map(compat.snd, self.cfg.GetMultiInstanceInfo(self.wanted_names))

  def _EnsureChildSizes(self, disk):
    """Ensure children of the disk have the needed disk size.

    This is valid mainly for DRBD8 and fixes an issue where the
    children have smaller disk size.

    @param disk: an L{ganeti.objects.Disk} object

    """
    if disk.dev_type == constants.LD_DRBD8:
      assert disk.children, "Empty children for DRBD8?"
      fchild = disk.children[0]
      mismatch = fchild.size < disk.size
      if mismatch:
        self.LogInfo("Child disk has size %d, parent %d, fixing",
                     fchild.size, disk.size)
        fchild.size = disk.size

      # and we recurse on this child only, not on the metadev
      return self._EnsureChildSizes(fchild) or mismatch
    else:
      return False

  def Exec(self, feedback_fn):
    """Verify the size of cluster disks.

    """
    # TODO: check child disks too
    # TODO: check differences in size between primary/secondary nodes
    per_node_disks = {}
    for instance in self.wanted_instances:
      pnode = instance.primary_node
      if pnode not in per_node_disks:
        per_node_disks[pnode] = []
      for idx, disk in enumerate(instance.disks):
        per_node_disks[pnode].append((instance, idx, disk))

    assert not (frozenset(per_node_disks.keys()) -
                self.owned_locks(locking.LEVEL_NODE_RES)), \
      "Not owning correct locks"
    assert not self.owned_locks(locking.LEVEL_NODE)

    changed = []
    for node, dskl in per_node_disks.items():
      newl = [v[2].Copy() for v in dskl]
      for dsk in newl:
        self.cfg.SetDiskID(dsk, node)
      result = self.rpc.call_blockdev_getsize(node, newl)
      if result.fail_msg:
        self.LogWarning("Failure in blockdev_getsize call to node"
                        " %s, ignoring", node)
        continue
      if len(result.payload) != len(dskl):
        logging.warning("Invalid result from node %s: len(dksl)=%d,"
                        " result.payload=%s", node, len(dskl), result.payload)
        self.LogWarning("Invalid result from node %s, ignoring node results",
                        node)
        continue
      for ((instance, idx, disk), size) in zip(dskl, result.payload):
        if size is None:
          self.LogWarning("Disk %d of instance %s did not return size"
                          " information, ignoring", idx, instance.name)
          continue
        if not isinstance(size, (int, long)):
          self.LogWarning("Disk %d of instance %s did not return valid"
                          " size information, ignoring", idx, instance.name)
          continue
        size = size >> 20
        if size != disk.size:
          self.LogInfo("Disk %d of instance %s has mismatched size,"
                       " correcting: recorded %d, actual %d", idx,
                       instance.name, disk.size, size)
          disk.size = size
          self.cfg.Update(instance, feedback_fn)
          changed.append((instance.name, idx, size))
        if self._EnsureChildSizes(disk):
          self.cfg.Update(instance, feedback_fn)
          changed.append((instance.name, idx, disk.size))
    return changed


class LUClusterRename(LogicalUnit):
  """Rename the cluster.

  """
  HPATH = "cluster-rename"
  HTYPE = constants.HTYPE_CLUSTER

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_NAME": self.op.name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([self.cfg.GetMasterNode()], self.cfg.GetNodeList())

  def CheckPrereq(self):
    """Verify that the passed name is a valid one.

    """
    hostname = netutils.GetHostname(name=self.op.name,
                                    family=self.cfg.GetPrimaryIPFamily())

    new_name = hostname.name
    self.ip = new_ip = hostname.ip
    old_name = self.cfg.GetClusterName()
    old_ip = self.cfg.GetMasterIP()
    if new_name == old_name and new_ip == old_ip:
      raise errors.OpPrereqError("Neither the name nor the IP address of the"
                                 " cluster has changed",
                                 errors.ECODE_INVAL)
    if new_ip != old_ip:
      if netutils.TcpPing(new_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("The given cluster IP address (%s) is"
                                   " reachable on the network" %
                                   new_ip, errors.ECODE_NOTUNIQUE)

    self.op.name = new_name

  def Exec(self, feedback_fn):
    """Rename the cluster.

    """
    clustername = self.op.name
    new_ip = self.ip

    # shutdown the master IP
    master_params = self.cfg.GetMasterNetworkParameters()
    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_deactivate_master_ip(master_params.name,
                                                     master_params, ems)
    result.Raise("Could not disable the master role")

    try:
      cluster = self.cfg.GetClusterInfo()
      cluster.cluster_name = clustername
      cluster.master_ip = new_ip
      self.cfg.Update(cluster, feedback_fn)

      # update the known hosts file
      ssh.WriteKnownHostsFile(self.cfg, pathutils.SSH_KNOWN_HOSTS_FILE)
      node_list = self.cfg.GetOnlineNodeList()
      try:
        node_list.remove(master_params.name)
      except ValueError:
        pass
      _UploadHelper(self, node_list, pathutils.SSH_KNOWN_HOSTS_FILE)
    finally:
      master_params.ip = new_ip
      result = self.rpc.call_node_activate_master_ip(master_params.name,
                                                     master_params, ems)
      msg = result.fail_msg
      if msg:
        self.LogWarning("Could not re-enable the master role on"
                        " the master, please restart manually: %s", msg)

    return clustername


def _ValidateNetmask(cfg, netmask):
  """Checks if a netmask is valid.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type netmask: int
  @param netmask: the netmask to be verified
  @raise errors.OpPrereqError: if the validation fails

  """
  ip_family = cfg.GetPrimaryIPFamily()
  try:
    ipcls = netutils.IPAddress.GetClassFromIpFamily(ip_family)
  except errors.ProgrammerError:
    raise errors.OpPrereqError("Invalid primary ip family: %s." %
                               ip_family, errors.ECODE_INVAL)
  if not ipcls.ValidateNetmask(netmask):
    raise errors.OpPrereqError("CIDR netmask (%s) not valid" %
                                (netmask), errors.ECODE_INVAL)


class LUClusterSetParams(LogicalUnit):
  """Change the parameters of the cluster.

  """
  HPATH = "cluster-modify"
  HTYPE = constants.HTYPE_CLUSTER
  REQ_BGL = False

  def CheckArguments(self):
    """Check parameters

    """
    if self.op.uid_pool:
      uidpool.CheckUidPool(self.op.uid_pool)

    if self.op.add_uids:
      uidpool.CheckUidPool(self.op.add_uids)

    if self.op.remove_uids:
      uidpool.CheckUidPool(self.op.remove_uids)

    if self.op.master_netmask is not None:
      _ValidateNetmask(self.cfg, self.op.master_netmask)

    if self.op.diskparams:
      for dt_params in self.op.diskparams.values():
        utils.ForceDictType(dt_params, constants.DISK_DT_TYPES)
      try:
        utils.VerifyDictOptions(self.op.diskparams, constants.DISK_DT_DEFAULTS)
      except errors.OpPrereqError, err:
        raise errors.OpPrereqError("While verify diskparams options: %s" % err,
                                   errors.ECODE_INVAL)

  def ExpandNames(self):
    # FIXME: in the future maybe other cluster params won't require checking on
    # all nodes to be modified.
    # FIXME: This opcode changes cluster-wide settings. Is acquiring all
    # resource locks the right thing, shouldn't it be the BGL instead?
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
      locking.LEVEL_NODEGROUP: locking.ALL_SET,
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
    }
    self.share_locks = _ShareAll()

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_VG_NAME": self.op.vg_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def CheckPrereq(self):
    """Check prerequisites.

    This checks whether the given params don't conflict and
    if the given volume group is valid.

    """
    if self.op.vg_name is not None and not self.op.vg_name:
      if self.cfg.HasAnyDiskOfType(constants.LD_LV):
        raise errors.OpPrereqError("Cannot disable lvm storage while lvm-based"
                                   " instances exist", errors.ECODE_INVAL)

    if self.op.drbd_helper is not None and not self.op.drbd_helper:
      if self.cfg.HasAnyDiskOfType(constants.LD_DRBD8):
        raise errors.OpPrereqError("Cannot disable drbd helper while"
                                   " drbd-based instances exist",
                                   errors.ECODE_INVAL)

    node_list = self.owned_locks(locking.LEVEL_NODE)

    # if vg_name not None, checks given volume group on all nodes
    if self.op.vg_name:
      vglist = self.rpc.call_vg_list(node_list)
      for node in node_list:
        msg = vglist[node].fail_msg
        if msg:
          # ignoring down node
          self.LogWarning("Error while gathering data on node %s"
                          " (ignoring node): %s", node, msg)
          continue
        vgstatus = utils.CheckVolumeGroupSize(vglist[node].payload,
                                              self.op.vg_name,
                                              constants.MIN_VG_SIZE)
        if vgstatus:
          raise errors.OpPrereqError("Error on node '%s': %s" %
                                     (node, vgstatus), errors.ECODE_ENVIRON)

    if self.op.drbd_helper:
      # checks given drbd helper on all nodes
      helpers = self.rpc.call_drbd_helper(node_list)
      for (node, ninfo) in self.cfg.GetMultiNodeInfo(node_list):
        if ninfo.offline:
          self.LogInfo("Not checking drbd helper on offline node %s", node)
          continue
        msg = helpers[node].fail_msg
        if msg:
          raise errors.OpPrereqError("Error checking drbd helper on node"
                                     " '%s': %s" % (node, msg),
                                     errors.ECODE_ENVIRON)
        node_helper = helpers[node].payload
        if node_helper != self.op.drbd_helper:
          raise errors.OpPrereqError("Error on node '%s': drbd helper is %s" %
                                     (node, node_helper), errors.ECODE_ENVIRON)

    self.cluster = cluster = self.cfg.GetClusterInfo()
    # validate params changes
    if self.op.beparams:
      objects.UpgradeBeParams(self.op.beparams)
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)
      self.new_beparams = cluster.SimpleFillBE(self.op.beparams)

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)
      self.new_ndparams = cluster.SimpleFillND(self.op.ndparams)

      # TODO: we need a more general way to handle resetting
      # cluster-level parameters to default values
      if self.new_ndparams["oob_program"] == "":
        self.new_ndparams["oob_program"] = \
            constants.NDC_DEFAULTS[constants.ND_OOB_PROGRAM]

    if self.op.hv_state:
      new_hv_state = _MergeAndVerifyHvState(self.op.hv_state,
                                            self.cluster.hv_state_static)
      self.new_hv_state = dict((hv, cluster.SimpleFillHvState(values))
                               for hv, values in new_hv_state.items())

    if self.op.disk_state:
      new_disk_state = _MergeAndVerifyDiskState(self.op.disk_state,
                                                self.cluster.disk_state_static)
      self.new_disk_state = \
        dict((storage, dict((name, cluster.SimpleFillDiskState(values))
                            for name, values in svalues.items()))
             for storage, svalues in new_disk_state.items())

    if self.op.ipolicy:
      self.new_ipolicy = _GetUpdatedIPolicy(cluster.ipolicy, self.op.ipolicy,
                                            group_policy=False)

      all_instances = self.cfg.GetAllInstancesInfo().values()
      violations = set()
      for group in self.cfg.GetAllNodeGroupsInfo().values():
        instances = frozenset([inst for inst in all_instances
                               if compat.any(node in group.members
                                             for node in inst.all_nodes)])
        new_ipolicy = objects.FillIPolicy(self.new_ipolicy, group.ipolicy)
        ipol = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group)
        new = _ComputeNewInstanceViolations(ipol,
                                            new_ipolicy, instances, self.cfg)
        if new:
          violations.update(new)

      if violations:
        self.LogWarning("After the ipolicy change the following instances"
                        " violate them: %s",
                        utils.CommaJoin(utils.NiceSort(violations)))

    if self.op.nicparams:
      utils.ForceDictType(self.op.nicparams, constants.NICS_PARAMETER_TYPES)
      self.new_nicparams = cluster.SimpleFillNIC(self.op.nicparams)
      objects.NIC.CheckParameterSyntax(self.new_nicparams)
      nic_errors = []

      # check all instances for consistency
      for instance in self.cfg.GetAllInstancesInfo().values():
        for nic_idx, nic in enumerate(instance.nics):
          params_copy = copy.deepcopy(nic.nicparams)
          params_filled = objects.FillDict(self.new_nicparams, params_copy)

          # check parameter syntax
          try:
            objects.NIC.CheckParameterSyntax(params_filled)
          except errors.ConfigurationError, err:
            nic_errors.append("Instance %s, nic/%d: %s" %
                              (instance.name, nic_idx, err))

          # if we're moving instances to routed, check that they have an ip
          target_mode = params_filled[constants.NIC_MODE]
          if target_mode == constants.NIC_MODE_ROUTED and not nic.ip:
            nic_errors.append("Instance %s, nic/%d: routed NIC with no ip"
                              " address" % (instance.name, nic_idx))
      if nic_errors:
        raise errors.OpPrereqError("Cannot apply the change, errors:\n%s" %
                                   "\n".join(nic_errors), errors.ECODE_INVAL)

    # hypervisor list/parameters
    self.new_hvparams = new_hvp = objects.FillDict(cluster.hvparams, {})
    if self.op.hvparams:
      for hv_name, hv_dict in self.op.hvparams.items():
        if hv_name not in self.new_hvparams:
          self.new_hvparams[hv_name] = hv_dict
        else:
          self.new_hvparams[hv_name].update(hv_dict)

    # disk template parameters
    self.new_diskparams = objects.FillDict(cluster.diskparams, {})
    if self.op.diskparams:
      for dt_name, dt_params in self.op.diskparams.items():
        if dt_name not in self.op.diskparams:
          self.new_diskparams[dt_name] = dt_params
        else:
          self.new_diskparams[dt_name].update(dt_params)

    # os hypervisor parameters
    self.new_os_hvp = objects.FillDict(cluster.os_hvp, {})
    if self.op.os_hvp:
      for os_name, hvs in self.op.os_hvp.items():
        if os_name not in self.new_os_hvp:
          self.new_os_hvp[os_name] = hvs
        else:
          for hv_name, hv_dict in hvs.items():
            if hv_dict is None:
              # Delete if it exists
              self.new_os_hvp[os_name].pop(hv_name, None)
            elif hv_name not in self.new_os_hvp[os_name]:
              self.new_os_hvp[os_name][hv_name] = hv_dict
            else:
              self.new_os_hvp[os_name][hv_name].update(hv_dict)

    # os parameters
    self.new_osp = objects.FillDict(cluster.osparams, {})
    if self.op.osparams:
      for os_name, osp in self.op.osparams.items():
        if os_name not in self.new_osp:
          self.new_osp[os_name] = {}

        self.new_osp[os_name] = _GetUpdatedParams(self.new_osp[os_name], osp,
                                                  use_none=True)

        if not self.new_osp[os_name]:
          # we removed all parameters
          del self.new_osp[os_name]
        else:
          # check the parameter validity (remote check)
          _CheckOSParams(self, False, [self.cfg.GetMasterNode()],
                         os_name, self.new_osp[os_name])

    # changes to the hypervisor list
    if self.op.enabled_hypervisors is not None:
      self.hv_list = self.op.enabled_hypervisors
      for hv in self.hv_list:
        # if the hypervisor doesn't already exist in the cluster
        # hvparams, we initialize it to empty, and then (in both
        # cases) we make sure to fill the defaults, as we might not
        # have a complete defaults list if the hypervisor wasn't
        # enabled before
        if hv not in new_hvp:
          new_hvp[hv] = {}
        new_hvp[hv] = objects.FillDict(constants.HVC_DEFAULTS[hv], new_hvp[hv])
        utils.ForceDictType(new_hvp[hv], constants.HVS_PARAMETER_TYPES)
    else:
      self.hv_list = cluster.enabled_hypervisors

    if self.op.hvparams or self.op.enabled_hypervisors is not None:
      # either the enabled list has changed, or the parameters have, validate
      for hv_name, hv_params in self.new_hvparams.items():
        if ((self.op.hvparams and hv_name in self.op.hvparams) or
            (self.op.enabled_hypervisors and
             hv_name in self.op.enabled_hypervisors)):
          # either this is a new hypervisor, or its parameters have changed
          hv_class = hypervisor.GetHypervisorClass(hv_name)
          utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
          hv_class.CheckParameterSyntax(hv_params)
          _CheckHVParams(self, node_list, hv_name, hv_params)

    if self.op.os_hvp:
      # no need to check any newly-enabled hypervisors, since the
      # defaults have already been checked in the above code-block
      for os_name, os_hvp in self.new_os_hvp.items():
        for hv_name, hv_params in os_hvp.items():
          utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
          # we need to fill in the new os_hvp on top of the actual hv_p
          cluster_defaults = self.new_hvparams.get(hv_name, {})
          new_osp = objects.FillDict(cluster_defaults, hv_params)
          hv_class = hypervisor.GetHypervisorClass(hv_name)
          hv_class.CheckParameterSyntax(new_osp)
          _CheckHVParams(self, node_list, hv_name, new_osp)

    if self.op.default_iallocator:
      alloc_script = utils.FindFile(self.op.default_iallocator,
                                    constants.IALLOCATOR_SEARCH_PATH,
                                    os.path.isfile)
      if alloc_script is None:
        raise errors.OpPrereqError("Invalid default iallocator script '%s'"
                                   " specified" % self.op.default_iallocator,
                                   errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Change the parameters of the cluster.

    """
    if self.op.vg_name is not None:
      new_volume = self.op.vg_name
      if not new_volume:
        new_volume = None
      if new_volume != self.cfg.GetVGName():
        self.cfg.SetVGName(new_volume)
      else:
        feedback_fn("Cluster LVM configuration already in desired"
                    " state, not changing")
    if self.op.drbd_helper is not None:
      new_helper = self.op.drbd_helper
      if not new_helper:
        new_helper = None
      if new_helper != self.cfg.GetDRBDHelper():
        self.cfg.SetDRBDHelper(new_helper)
      else:
        feedback_fn("Cluster DRBD helper already in desired state,"
                    " not changing")
    if self.op.hvparams:
      self.cluster.hvparams = self.new_hvparams
    if self.op.os_hvp:
      self.cluster.os_hvp = self.new_os_hvp
    if self.op.enabled_hypervisors is not None:
      self.cluster.hvparams = self.new_hvparams
      self.cluster.enabled_hypervisors = self.op.enabled_hypervisors
    if self.op.beparams:
      self.cluster.beparams[constants.PP_DEFAULT] = self.new_beparams
    if self.op.nicparams:
      self.cluster.nicparams[constants.PP_DEFAULT] = self.new_nicparams
    if self.op.ipolicy:
      self.cluster.ipolicy = self.new_ipolicy
    if self.op.osparams:
      self.cluster.osparams = self.new_osp
    if self.op.ndparams:
      self.cluster.ndparams = self.new_ndparams
    if self.op.diskparams:
      self.cluster.diskparams = self.new_diskparams
    if self.op.hv_state:
      self.cluster.hv_state_static = self.new_hv_state
    if self.op.disk_state:
      self.cluster.disk_state_static = self.new_disk_state

    if self.op.candidate_pool_size is not None:
      self.cluster.candidate_pool_size = self.op.candidate_pool_size
      # we need to update the pool size here, otherwise the save will fail
      _AdjustCandidatePool(self, [])

    if self.op.maintain_node_health is not None:
      if self.op.maintain_node_health and not constants.ENABLE_CONFD:
        feedback_fn("Note: CONFD was disabled at build time, node health"
                    " maintenance is not useful (still enabling it)")
      self.cluster.maintain_node_health = self.op.maintain_node_health

    if self.op.prealloc_wipe_disks is not None:
      self.cluster.prealloc_wipe_disks = self.op.prealloc_wipe_disks

    if self.op.add_uids is not None:
      uidpool.AddToUidPool(self.cluster.uid_pool, self.op.add_uids)

    if self.op.remove_uids is not None:
      uidpool.RemoveFromUidPool(self.cluster.uid_pool, self.op.remove_uids)

    if self.op.uid_pool is not None:
      self.cluster.uid_pool = self.op.uid_pool

    if self.op.default_iallocator is not None:
      self.cluster.default_iallocator = self.op.default_iallocator

    if self.op.reserved_lvs is not None:
      self.cluster.reserved_lvs = self.op.reserved_lvs

    if self.op.use_external_mip_script is not None:
      self.cluster.use_external_mip_script = self.op.use_external_mip_script

    def helper_os(aname, mods, desc):
      desc += " OS list"
      lst = getattr(self.cluster, aname)
      for key, val in mods:
        if key == constants.DDM_ADD:
          if val in lst:
            feedback_fn("OS %s already in %s, ignoring" % (val, desc))
          else:
            lst.append(val)
        elif key == constants.DDM_REMOVE:
          if val in lst:
            lst.remove(val)
          else:
            feedback_fn("OS %s not found in %s, ignoring" % (val, desc))
        else:
          raise errors.ProgrammerError("Invalid modification '%s'" % key)

    if self.op.hidden_os:
      helper_os("hidden_os", self.op.hidden_os, "hidden")

    if self.op.blacklisted_os:
      helper_os("blacklisted_os", self.op.blacklisted_os, "blacklisted")

    if self.op.master_netdev:
      master_params = self.cfg.GetMasterNetworkParameters()
      ems = self.cfg.GetUseExternalMipScript()
      feedback_fn("Shutting down master ip on the current netdev (%s)" %
                  self.cluster.master_netdev)
      result = self.rpc.call_node_deactivate_master_ip(master_params.name,
                                                       master_params, ems)
      result.Raise("Could not disable the master ip")
      feedback_fn("Changing master_netdev from %s to %s" %
                  (master_params.netdev, self.op.master_netdev))
      self.cluster.master_netdev = self.op.master_netdev

    if self.op.master_netmask:
      master_params = self.cfg.GetMasterNetworkParameters()
      feedback_fn("Changing master IP netmask to %s" % self.op.master_netmask)
      result = self.rpc.call_node_change_master_netmask(master_params.name,
                                                        master_params.netmask,
                                                        self.op.master_netmask,
                                                        master_params.ip,
                                                        master_params.netdev)
      if result.fail_msg:
        msg = "Could not change the master IP netmask: %s" % result.fail_msg
        feedback_fn(msg)

      self.cluster.master_netmask = self.op.master_netmask

    self.cfg.Update(self.cluster, feedback_fn)

    if self.op.master_netdev:
      master_params = self.cfg.GetMasterNetworkParameters()
      feedback_fn("Starting the master ip on the new master netdev (%s)" %
                  self.op.master_netdev)
      ems = self.cfg.GetUseExternalMipScript()
      result = self.rpc.call_node_activate_master_ip(master_params.name,
                                                     master_params, ems)
      if result.fail_msg:
        self.LogWarning("Could not re-enable the master ip on"
                        " the master, please restart manually: %s",
                        result.fail_msg)


def _UploadHelper(lu, nodes, fname):
  """Helper for uploading a file and showing warnings.

  """
  if os.path.exists(fname):
    result = lu.rpc.call_upload_file(nodes, fname)
    for to_node, to_result in result.items():
      msg = to_result.fail_msg
      if msg:
        msg = ("Copy of file %s to node %s failed: %s" %
               (fname, to_node, msg))
        lu.LogWarning(msg)


def _ComputeAncillaryFiles(cluster, redist):
  """Compute files external to Ganeti which need to be consistent.

  @type redist: boolean
  @param redist: Whether to include files which need to be redistributed

  """
  # Compute files for all nodes
  files_all = set([
    pathutils.SSH_KNOWN_HOSTS_FILE,
    pathutils.CONFD_HMAC_KEY,
    pathutils.CLUSTER_DOMAIN_SECRET_FILE,
    pathutils.SPICE_CERT_FILE,
    pathutils.SPICE_CACERT_FILE,
    pathutils.RAPI_USERS_FILE,
    ])

  if redist:
    # we need to ship at least the RAPI certificate
    files_all.add(pathutils.RAPI_CERT_FILE)
  else:
    files_all.update(pathutils.ALL_CERT_FILES)
    files_all.update(ssconf.SimpleStore().GetFileList())

  if cluster.modify_etc_hosts:
    files_all.add(pathutils.ETC_HOSTS)

  if cluster.use_external_mip_script:
    files_all.add(pathutils.EXTERNAL_MASTER_SETUP_SCRIPT)

  # Files which are optional, these must:
  # - be present in one other category as well
  # - either exist or not exist on all nodes of that category (mc, vm all)
  files_opt = set([
    pathutils.RAPI_USERS_FILE,
    ])

  # Files which should only be on master candidates
  files_mc = set()

  if not redist:
    files_mc.add(pathutils.CLUSTER_CONF_FILE)

  # File storage
  if (not redist and
      (constants.ENABLE_FILE_STORAGE or constants.ENABLE_SHARED_FILE_STORAGE)):
    files_all.add(pathutils.FILE_STORAGE_PATHS_FILE)
    files_opt.add(pathutils.FILE_STORAGE_PATHS_FILE)

  # Files which should only be on VM-capable nodes
  files_vm = set(
    filename
    for hv_name in cluster.enabled_hypervisors
    for filename in
      hypervisor.GetHypervisorClass(hv_name).GetAncillaryFiles()[0])

  files_opt |= set(
    filename
    for hv_name in cluster.enabled_hypervisors
    for filename in
      hypervisor.GetHypervisorClass(hv_name).GetAncillaryFiles()[1])

  # Filenames in each category must be unique
  all_files_set = files_all | files_mc | files_vm
  assert (len(all_files_set) ==
          sum(map(len, [files_all, files_mc, files_vm]))), \
         "Found file listed in more than one file list"

  # Optional files must be present in one other category
  assert all_files_set.issuperset(files_opt), \
         "Optional file not in a different required list"

  # This one file should never ever be re-distributed via RPC
  assert not (redist and
              pathutils.FILE_STORAGE_PATHS_FILE in all_files_set)

  return (files_all, files_opt, files_mc, files_vm)


def _RedistributeAncillaryFiles(lu, additional_nodes=None, additional_vm=True):
  """Distribute additional files which are part of the cluster configuration.

  ConfigWriter takes care of distributing the config and ssconf files, but
  there are more files which should be distributed to all nodes. This function
  makes sure those are copied.

  @param lu: calling logical unit
  @param additional_nodes: list of nodes not in the config to distribute to
  @type additional_vm: boolean
  @param additional_vm: whether the additional nodes are vm-capable or not

  """
  # Gather target nodes
  cluster = lu.cfg.GetClusterInfo()
  master_info = lu.cfg.GetNodeInfo(lu.cfg.GetMasterNode())

  online_nodes = lu.cfg.GetOnlineNodeList()
  online_set = frozenset(online_nodes)
  vm_nodes = list(online_set.intersection(lu.cfg.GetVmCapableNodeList()))

  if additional_nodes is not None:
    online_nodes.extend(additional_nodes)
    if additional_vm:
      vm_nodes.extend(additional_nodes)

  # Never distribute to master node
  for nodelist in [online_nodes, vm_nodes]:
    if master_info.name in nodelist:
      nodelist.remove(master_info.name)

  # Gather file lists
  (files_all, _, files_mc, files_vm) = \
    _ComputeAncillaryFiles(cluster, True)

  # Never re-distribute configuration file from here
  assert not (pathutils.CLUSTER_CONF_FILE in files_all or
              pathutils.CLUSTER_CONF_FILE in files_vm)
  assert not files_mc, "Master candidates not handled in this function"

  filemap = [
    (online_nodes, files_all),
    (vm_nodes, files_vm),
    ]

  # Upload the files
  for (node_list, files) in filemap:
    for fname in files:
      _UploadHelper(lu, node_list, fname)


class LUClusterRedistConf(NoHooksLU):
  """Force the redistribution of cluster configuration.

  This is a very simple LU.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
    }
    self.share_locks = _ShareAll()

  def Exec(self, feedback_fn):
    """Redistribute the configuration.

    """
    self.cfg.Update(self.cfg.GetClusterInfo(), feedback_fn)
    _RedistributeAncillaryFiles(self)


class LUClusterActivateMasterIp(NoHooksLU):
  """Activate the master IP on the master node.

  """
  def Exec(self, feedback_fn):
    """Activate the master IP.

    """
    master_params = self.cfg.GetMasterNetworkParameters()
    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_activate_master_ip(master_params.name,
                                                   master_params, ems)
    result.Raise("Could not activate the master IP")


class LUClusterDeactivateMasterIp(NoHooksLU):
  """Deactivate the master IP on the master node.

  """
  def Exec(self, feedback_fn):
    """Deactivate the master IP.

    """
    master_params = self.cfg.GetMasterNetworkParameters()
    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_deactivate_master_ip(master_params.name,
                                                     master_params, ems)
    result.Raise("Could not deactivate the master IP")


def _WaitForSync(lu, instance, disks=None, oneshot=False):
  """Sleep and poll for an instance's disk to sync.

  """
  if not instance.disks or disks is not None and not disks:
    return True

  disks = _ExpandCheckDisks(instance, disks)

  if not oneshot:
    lu.LogInfo("Waiting for instance %s to sync disks", instance.name)

  node = instance.primary_node

  for dev in disks:
    lu.cfg.SetDiskID(dev, node)

  # TODO: Convert to utils.Retry

  retries = 0
  degr_retries = 10 # in seconds, as we sleep 1 second each time
  while True:
    max_time = 0
    done = True
    cumul_degraded = False
    rstats = lu.rpc.call_blockdev_getmirrorstatus(node, (disks, instance))
    msg = rstats.fail_msg
    if msg:
      lu.LogWarning("Can't get any data from node %s: %s", node, msg)
      retries += 1
      if retries >= 10:
        raise errors.RemoteError("Can't contact node %s for mirror data,"
                                 " aborting." % node)
      time.sleep(6)
      continue
    rstats = rstats.payload
    retries = 0
    for i, mstat in enumerate(rstats):
      if mstat is None:
        lu.LogWarning("Can't compute data for node %s/%s",
                           node, disks[i].iv_name)
        continue

      cumul_degraded = (cumul_degraded or
                        (mstat.is_degraded and mstat.sync_percent is None))
      if mstat.sync_percent is not None:
        done = False
        if mstat.estimated_time is not None:
          rem_time = ("%s remaining (estimated)" %
                      utils.FormatSeconds(mstat.estimated_time))
          max_time = mstat.estimated_time
        else:
          rem_time = "no time estimate"
        lu.LogInfo("- device %s: %5.2f%% done, %s",
                   disks[i].iv_name, mstat.sync_percent, rem_time)

    # if we're done but degraded, let's do a few small retries, to
    # make sure we see a stable and not transient situation; therefore
    # we force restart of the loop
    if (done or oneshot) and cumul_degraded and degr_retries > 0:
      logging.info("Degraded disks found, %d retries left", degr_retries)
      degr_retries -= 1
      time.sleep(1)
      continue

    if done or oneshot:
      break

    time.sleep(min(60, max_time))

  if done:
    lu.LogInfo("Instance %s's disks are in sync", instance.name)

  return not cumul_degraded


def _BlockdevFind(lu, node, dev, instance):
  """Wrapper around call_blockdev_find to annotate diskparams.

  @param lu: A reference to the lu object
  @param node: The node to call out
  @param dev: The device to find
  @param instance: The instance object the device belongs to
  @returns The result of the rpc call

  """
  (disk,) = _AnnotateDiskParams(instance, [dev], lu.cfg)
  return lu.rpc.call_blockdev_find(node, disk)


def _CheckDiskConsistency(lu, instance, dev, node, on_primary, ldisk=False):
  """Wrapper around L{_CheckDiskConsistencyInner}.

  """
  (disk,) = _AnnotateDiskParams(instance, [dev], lu.cfg)
  return _CheckDiskConsistencyInner(lu, instance, disk, node, on_primary,
                                    ldisk=ldisk)


def _CheckDiskConsistencyInner(lu, instance, dev, node, on_primary,
                               ldisk=False):
  """Check that mirrors are not degraded.

  @attention: The device has to be annotated already.

  The ldisk parameter, if True, will change the test from the
  is_degraded attribute (which represents overall non-ok status for
  the device(s)) to the ldisk (representing the local storage status).

  """
  lu.cfg.SetDiskID(dev, node)

  result = True

  if on_primary or dev.AssembleOnSecondary():
    rstats = lu.rpc.call_blockdev_find(node, dev)
    msg = rstats.fail_msg
    if msg:
      lu.LogWarning("Can't find disk on node %s: %s", node, msg)
      result = False
    elif not rstats.payload:
      lu.LogWarning("Can't find disk on node %s", node)
      result = False
    else:
      if ldisk:
        result = result and rstats.payload.ldisk_status == constants.LDS_OKAY
      else:
        result = result and not rstats.payload.is_degraded

  if dev.children:
    for child in dev.children:
      result = result and _CheckDiskConsistencyInner(lu, instance, child, node,
                                                     on_primary)

  return result


class LUOobCommand(NoHooksLU):
  """Logical unit for OOB handling.

  """
  REQ_BGL = False
  _SKIP_MASTER = (constants.OOB_POWER_OFF, constants.OOB_POWER_CYCLE)

  def ExpandNames(self):
    """Gather locks we need.

    """
    if self.op.node_names:
      self.op.node_names = _GetWantedNodes(self, self.op.node_names)
      lock_names = self.op.node_names
    else:
      lock_names = locking.ALL_SET

    self.needed_locks = {
      locking.LEVEL_NODE: lock_names,
      }

    self.share_locks[locking.LEVEL_NODE_ALLOC] = 1

    if not self.op.node_names:
      # Acquire node allocation lock only if all nodes are affected
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the node exists in the configuration
     - OOB is supported

    Any errors are signaled by raising errors.OpPrereqError.

    """
    self.nodes = []
    self.master_node = self.cfg.GetMasterNode()

    assert self.op.power_delay >= 0.0

    if self.op.node_names:
      if (self.op.command in self._SKIP_MASTER and
          self.master_node in self.op.node_names):
        master_node_obj = self.cfg.GetNodeInfo(self.master_node)
        master_oob_handler = _SupportsOob(self.cfg, master_node_obj)

        if master_oob_handler:
          additional_text = ("run '%s %s %s' if you want to operate on the"
                             " master regardless") % (master_oob_handler,
                                                      self.op.command,
                                                      self.master_node)
        else:
          additional_text = "it does not support out-of-band operations"

        raise errors.OpPrereqError(("Operating on the master node %s is not"
                                    " allowed for %s; %s") %
                                   (self.master_node, self.op.command,
                                    additional_text), errors.ECODE_INVAL)
    else:
      self.op.node_names = self.cfg.GetNodeList()
      if self.op.command in self._SKIP_MASTER:
        self.op.node_names.remove(self.master_node)

    if self.op.command in self._SKIP_MASTER:
      assert self.master_node not in self.op.node_names

    for (node_name, node) in self.cfg.GetMultiNodeInfo(self.op.node_names):
      if node is None:
        raise errors.OpPrereqError("Node %s not found" % node_name,
                                   errors.ECODE_NOENT)
      else:
        self.nodes.append(node)

      if (not self.op.ignore_status and
          (self.op.command == constants.OOB_POWER_OFF and not node.offline)):
        raise errors.OpPrereqError(("Cannot power off node %s because it is"
                                    " not marked offline") % node_name,
                                   errors.ECODE_STATE)

  def Exec(self, feedback_fn):
    """Execute OOB and return result if we expect any.

    """
    master_node = self.master_node
    ret = []

    for idx, node in enumerate(utils.NiceSort(self.nodes,
                                              key=lambda node: node.name)):
      node_entry = [(constants.RS_NORMAL, node.name)]
      ret.append(node_entry)

      oob_program = _SupportsOob(self.cfg, node)

      if not oob_program:
        node_entry.append((constants.RS_UNAVAIL, None))
        continue

      logging.info("Executing out-of-band command '%s' using '%s' on %s",
                   self.op.command, oob_program, node.name)
      result = self.rpc.call_run_oob(master_node, oob_program,
                                     self.op.command, node.name,
                                     self.op.timeout)

      if result.fail_msg:
        self.LogWarning("Out-of-band RPC failed on node '%s': %s",
                        node.name, result.fail_msg)
        node_entry.append((constants.RS_NODATA, None))
      else:
        try:
          self._CheckPayload(result)
        except errors.OpExecError, err:
          self.LogWarning("Payload returned by node '%s' is not valid: %s",
                          node.name, err)
          node_entry.append((constants.RS_NODATA, None))
        else:
          if self.op.command == constants.OOB_HEALTH:
            # For health we should log important events
            for item, status in result.payload:
              if status in [constants.OOB_STATUS_WARNING,
                            constants.OOB_STATUS_CRITICAL]:
                self.LogWarning("Item '%s' on node '%s' has status '%s'",
                                item, node.name, status)

          if self.op.command == constants.OOB_POWER_ON:
            node.powered = True
          elif self.op.command == constants.OOB_POWER_OFF:
            node.powered = False
          elif self.op.command == constants.OOB_POWER_STATUS:
            powered = result.payload[constants.OOB_POWER_STATUS_POWERED]
            if powered != node.powered:
              logging.warning(("Recorded power state (%s) of node '%s' does not"
                               " match actual power state (%s)"), node.powered,
                              node.name, powered)

          # For configuration changing commands we should update the node
          if self.op.command in (constants.OOB_POWER_ON,
                                 constants.OOB_POWER_OFF):
            self.cfg.Update(node, feedback_fn)

          node_entry.append((constants.RS_NORMAL, result.payload))

          if (self.op.command == constants.OOB_POWER_ON and
              idx < len(self.nodes) - 1):
            time.sleep(self.op.power_delay)

    return ret

  def _CheckPayload(self, result):
    """Checks if the payload is valid.

    @param result: RPC result
    @raises errors.OpExecError: If payload is not valid

    """
    errs = []
    if self.op.command == constants.OOB_HEALTH:
      if not isinstance(result.payload, list):
        errs.append("command 'health' is expected to return a list but got %s" %
                    type(result.payload))
      else:
        for item, status in result.payload:
          if status not in constants.OOB_STATUSES:
            errs.append("health item '%s' has invalid status '%s'" %
                        (item, status))

    if self.op.command == constants.OOB_POWER_STATUS:
      if not isinstance(result.payload, dict):
        errs.append("power-status is expected to return a dict but got %s" %
                    type(result.payload))

    if self.op.command in [
      constants.OOB_POWER_ON,
      constants.OOB_POWER_OFF,
      constants.OOB_POWER_CYCLE,
      ]:
      if result.payload is not None:
        errs.append("%s is expected to not return payload but got '%s'" %
                    (self.op.command, result.payload))

    if errs:
      raise errors.OpExecError("Check of out-of-band payload failed due to %s" %
                               utils.CommaJoin(errs))


class _OsQuery(_QueryBase):
  FIELDS = query.OS_FIELDS

  def ExpandNames(self, lu):
    # Lock all nodes in shared mode
    # Temporary removal of locks, should be reverted later
    # TODO: reintroduce locks when they are lighter-weight
    lu.needed_locks = {}
    #self.share_locks[locking.LEVEL_NODE] = 1
    #self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

    # The following variables interact with _QueryBase._GetNames
    if self.names:
      self.wanted = self.names
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

  def DeclareLocks(self, lu, level):
    pass

  @staticmethod
  def _DiagnoseByOS(rlist):
    """Remaps a per-node return list into an a per-os per-node dictionary

    @param rlist: a map with node names as keys and OS objects as values

    @rtype: dict
    @return: a dictionary with osnames as keys and as value another
        map, with nodes as keys and tuples of (path, status, diagnose,
        variants, parameters, api_versions) as values, eg::

          {"debian-etch": {"node1": [(/usr/lib/..., True, "", [], []),
                                     (/srv/..., False, "invalid api")],
                           "node2": [(/srv/..., True, "", [], [])]}
          }

    """
    all_os = {}
    # we build here the list of nodes that didn't fail the RPC (at RPC
    # level), so that nodes with a non-responding node daemon don't
    # make all OSes invalid
    good_nodes = [node_name for node_name in rlist
                  if not rlist[node_name].fail_msg]
    for node_name, nr in rlist.items():
      if nr.fail_msg or not nr.payload:
        continue
      for (name, path, status, diagnose, variants,
           params, api_versions) in nr.payload:
        if name not in all_os:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_os[name] = {}
          for nname in good_nodes:
            all_os[name][nname] = []
        # convert params from [name, help] to (name, help)
        params = [tuple(v) for v in params]
        all_os[name][node_name].append((path, status, diagnose,
                                        variants, params, api_versions))
    return all_os

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    valid_nodes = [node.name
                   for node in lu.cfg.GetAllNodesInfo().values()
                   if not node.offline and node.vm_capable]
    pol = self._DiagnoseByOS(lu.rpc.call_os_diagnose(valid_nodes))
    cluster = lu.cfg.GetClusterInfo()

    data = {}

    for (os_name, os_data) in pol.items():
      info = query.OsInfo(name=os_name, valid=True, node_status=os_data,
                          hidden=(os_name in cluster.hidden_os),
                          blacklisted=(os_name in cluster.blacklisted_os))

      variants = set()
      parameters = set()
      api_versions = set()

      for idx, osl in enumerate(os_data.values()):
        info.valid = bool(info.valid and osl and osl[0][1])
        if not info.valid:
          break

        (node_variants, node_params, node_api) = osl[0][3:6]
        if idx == 0:
          # First entry
          variants.update(node_variants)
          parameters.update(node_params)
          api_versions.update(node_api)
        else:
          # Filter out inconsistent values
          variants.intersection_update(node_variants)
          parameters.intersection_update(node_params)
          api_versions.intersection_update(node_api)

      info.variants = list(variants)
      info.parameters = list(parameters)
      info.api_versions = list(api_versions)

      data[os_name] = info

    # Prepare data in requested order
    return [data[name] for name in self._GetNames(lu, pol.keys(), None)
            if name in data]


class LUOsDiagnose(NoHooksLU):
  """Logical unit for OS diagnose/query.

  """
  REQ_BGL = False

  @staticmethod
  def _BuildFilter(fields, names):
    """Builds a filter for querying OSes.

    """
    name_filter = qlang.MakeSimpleFilter("name", names)

    # Legacy behaviour: Hide hidden, blacklisted or invalid OSes if the
    # respective field is not requested
    status_filter = [[qlang.OP_NOT, [qlang.OP_TRUE, fname]]
                     for fname in ["hidden", "blacklisted"]
                     if fname not in fields]
    if "valid" not in fields:
      status_filter.append([qlang.OP_TRUE, "valid"])

    if status_filter:
      status_filter.insert(0, qlang.OP_AND)
    else:
      status_filter = None

    if name_filter and status_filter:
      return [qlang.OP_AND, name_filter, status_filter]
    elif name_filter:
      return name_filter
    else:
      return status_filter

  def CheckArguments(self):
    self.oq = _OsQuery(self._BuildFilter(self.op.output_fields, self.op.names),
                       self.op.output_fields, False)

  def ExpandNames(self):
    self.oq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.oq.OldStyleQuery(self)


class _ExtStorageQuery(_QueryBase):
  FIELDS = query.EXTSTORAGE_FIELDS

  def ExpandNames(self, lu):
    # Lock all nodes in shared mode
    # Temporary removal of locks, should be reverted later
    # TODO: reintroduce locks when they are lighter-weight
    lu.needed_locks = {}
    #self.share_locks[locking.LEVEL_NODE] = 1
    #self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

    # The following variables interact with _QueryBase._GetNames
    if self.names:
      self.wanted = self.names
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

  def DeclareLocks(self, lu, level):
    pass

  @staticmethod
  def _DiagnoseByProvider(rlist):
    """Remaps a per-node return list into an a per-provider per-node dictionary

    @param rlist: a map with node names as keys and ExtStorage objects as values

    @rtype: dict
    @return: a dictionary with extstorage providers as keys and as
        value another map, with nodes as keys and tuples of
        (path, status, diagnose, parameters) as values, eg::

          {"provider1": {"node1": [(/usr/lib/..., True, "", [])]
                         "node2": [(/srv/..., False, "missing file")]
                         "node3": [(/srv/..., True, "", [])]
          }

    """
    all_es = {}
    # we build here the list of nodes that didn't fail the RPC (at RPC
    # level), so that nodes with a non-responding node daemon don't
    # make all OSes invalid
    good_nodes = [node_name for node_name in rlist
                  if not rlist[node_name].fail_msg]
    for node_name, nr in rlist.items():
      if nr.fail_msg or not nr.payload:
        continue
      for (name, path, status, diagnose, params) in nr.payload:
        if name not in all_es:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_es[name] = {}
          for nname in good_nodes:
            all_es[name][nname] = []
        # convert params from [name, help] to (name, help)
        params = [tuple(v) for v in params]
        all_es[name][node_name].append((path, status, diagnose, params))
    return all_es

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    valid_nodes = [node.name
                   for node in lu.cfg.GetAllNodesInfo().values()
                   if not node.offline and node.vm_capable]
    pol = self._DiagnoseByProvider(lu.rpc.call_extstorage_diagnose(valid_nodes))

    data = {}

    nodegroup_list = lu.cfg.GetNodeGroupList()

    for (es_name, es_data) in pol.items():
      # For every provider compute the nodegroup validity.
      # To do this we need to check the validity of each node in es_data
      # and then construct the corresponding nodegroup dict:
      #      { nodegroup1: status
      #        nodegroup2: status
      #      }
      ndgrp_data = {}
      for nodegroup in nodegroup_list:
        ndgrp = lu.cfg.GetNodeGroup(nodegroup)

        nodegroup_nodes = ndgrp.members
        nodegroup_name = ndgrp.name
        node_statuses = []

        for node in nodegroup_nodes:
          if node in valid_nodes:
            if es_data[node] != []:
              node_status = es_data[node][0][1]
              node_statuses.append(node_status)
            else:
              node_statuses.append(False)

        if False in node_statuses:
          ndgrp_data[nodegroup_name] = False
        else:
          ndgrp_data[nodegroup_name] = True

      # Compute the provider's parameters
      parameters = set()
      for idx, esl in enumerate(es_data.values()):
        valid = bool(esl and esl[0][1])
        if not valid:
          break

        node_params = esl[0][3]
        if idx == 0:
          # First entry
          parameters.update(node_params)
        else:
          # Filter out inconsistent values
          parameters.intersection_update(node_params)

      params = list(parameters)

      # Now fill all the info for this provider
      info = query.ExtStorageInfo(name=es_name, node_status=es_data,
                                  nodegroup_status=ndgrp_data,
                                  parameters=params)

      data[es_name] = info

    # Prepare data in requested order
    return [data[name] for name in self._GetNames(lu, pol.keys(), None)
            if name in data]


class LUExtStorageDiagnose(NoHooksLU):
  """Logical unit for ExtStorage diagnose/query.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.eq = _ExtStorageQuery(qlang.MakeSimpleFilter("name", self.op.names),
                               self.op.output_fields, False)

  def ExpandNames(self):
    self.eq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.eq.OldStyleQuery(self)


class LUNodeRemove(LogicalUnit):
  """Logical unit for removing a node.

  """
  HPATH = "node-remove"
  HTYPE = constants.HTYPE_NODE

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.op.node_name,
      "NODE_NAME": self.op.node_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    This doesn't run on the target node in the pre phase as a failed
    node would then be impossible to remove.

    """
    all_nodes = self.cfg.GetNodeList()
    try:
      all_nodes.remove(self.op.node_name)
    except ValueError:
      pass
    return (all_nodes, all_nodes)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the node exists in the configuration
     - it does not have primary or secondary instances
     - it's not the master

    Any errors are signaled by raising errors.OpPrereqError.

    """
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)
    node = self.cfg.GetNodeInfo(self.op.node_name)
    assert node is not None

    masternode = self.cfg.GetMasterNode()
    if node.name == masternode:
      raise errors.OpPrereqError("Node is the master node, failover to another"
                                 " node is required", errors.ECODE_INVAL)

    for instance_name, instance in self.cfg.GetAllInstancesInfo().items():
      if node.name in instance.all_nodes:
        raise errors.OpPrereqError("Instance %s is still running on the node,"
                                   " please remove first" % instance_name,
                                   errors.ECODE_INVAL)
    self.op.node_name = node.name
    self.node = node

  def Exec(self, feedback_fn):
    """Removes the node from the cluster.

    """
    node = self.node
    logging.info("Stopping the node daemon and removing configs from node %s",
                 node.name)

    modify_ssh_setup = self.cfg.GetClusterInfo().modify_ssh_setup

    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER), \
      "Not owning BGL"

    # Promote nodes to master candidate as needed
    _AdjustCandidatePool(self, exceptions=[node.name])
    self.context.RemoveNode(node.name)

    # Run post hooks on the node before it's removed
    _RunPostHook(self, node.name)

    result = self.rpc.call_node_leave_cluster(node.name, modify_ssh_setup)
    msg = result.fail_msg
    if msg:
      self.LogWarning("Errors encountered on the remote node while leaving"
                      " the cluster: %s", msg)

    # Remove node from our /etc/hosts
    if self.cfg.GetClusterInfo().modify_etc_hosts:
      master_node = self.cfg.GetMasterNode()
      result = self.rpc.call_etc_hosts_modify(master_node,
                                              constants.ETC_HOSTS_REMOVE,
                                              node.name, None)
      result.Raise("Can't update hosts file with new host data")
      _RedistributeAncillaryFiles(self)


class _NodeQuery(_QueryBase):
  FIELDS = query.NODE_FIELDS

  def ExpandNames(self, lu):
    lu.needed_locks = {}
    lu.share_locks = _ShareAll()

    if self.names:
      self.wanted = _GetWantedNodes(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = (self.use_locking and
                       query.NQ_LIVE in self.requested_data)

    if self.do_locking:
      # If any non-static field is requested we need to lock the nodes
      lu.needed_locks[locking.LEVEL_NODE] = self.wanted
      lu.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    all_info = lu.cfg.GetAllNodesInfo()

    nodenames = self._GetNames(lu, all_info.keys(), locking.LEVEL_NODE)

    # Gather data as requested
    if query.NQ_LIVE in self.requested_data:
      # filter out non-vm_capable nodes
      toquery_nodes = [name for name in nodenames if all_info[name].vm_capable]

      es_flags = rpc.GetExclusiveStorageForNodeNames(lu.cfg, toquery_nodes)
      node_data = lu.rpc.call_node_info(toquery_nodes, [lu.cfg.GetVGName()],
                                        [lu.cfg.GetHypervisorType()], es_flags)
      live_data = dict((name, rpc.MakeLegacyNodeInfo(nresult.payload))
                       for (name, nresult) in node_data.items()
                       if not nresult.fail_msg and nresult.payload)
    else:
      live_data = None

    if query.NQ_INST in self.requested_data:
      node_to_primary = dict([(name, set()) for name in nodenames])
      node_to_secondary = dict([(name, set()) for name in nodenames])

      inst_data = lu.cfg.GetAllInstancesInfo()

      for inst in inst_data.values():
        if inst.primary_node in node_to_primary:
          node_to_primary[inst.primary_node].add(inst.name)
        for secnode in inst.secondary_nodes:
          if secnode in node_to_secondary:
            node_to_secondary[secnode].add(inst.name)
    else:
      node_to_primary = None
      node_to_secondary = None

    if query.NQ_OOB in self.requested_data:
      oob_support = dict((name, bool(_SupportsOob(lu.cfg, node)))
                         for name, node in all_info.iteritems())
    else:
      oob_support = None

    if query.NQ_GROUP in self.requested_data:
      groups = lu.cfg.GetAllNodeGroupsInfo()
    else:
      groups = {}

    return query.NodeQueryData([all_info[name] for name in nodenames],
                               live_data, lu.cfg.GetMasterNode(),
                               node_to_primary, node_to_secondary, groups,
                               oob_support, lu.cfg.GetClusterInfo())


class LUNodeQuery(NoHooksLU):
  """Logical unit for querying nodes.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.nq = _NodeQuery(qlang.MakeSimpleFilter("name", self.op.names),
                         self.op.output_fields, self.op.use_locking)

  def ExpandNames(self):
    self.nq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.nq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.nq.OldStyleQuery(self)


class LUNodeQueryvols(NoHooksLU):
  """Logical unit for getting volumes on node(s).

  """
  REQ_BGL = False
  _FIELDS_DYNAMIC = utils.FieldSet("phys", "vg", "name", "size", "instance")
  _FIELDS_STATIC = utils.FieldSet("node")

  def CheckArguments(self):
    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

  def ExpandNames(self):
    self.share_locks = _ShareAll()

    if self.op.nodes:
      self.needed_locks = {
        locking.LEVEL_NODE: _GetWantedNodes(self, self.op.nodes),
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    nodenames = self.owned_locks(locking.LEVEL_NODE)
    volumes = self.rpc.call_node_volumes(nodenames)

    ilist = self.cfg.GetAllInstancesInfo()
    vol2inst = _MapInstanceDisksToNodes(ilist.values())

    output = []
    for node in nodenames:
      nresult = volumes[node]
      if nresult.offline:
        continue
      msg = nresult.fail_msg
      if msg:
        self.LogWarning("Can't compute volume data on node %s: %s", node, msg)
        continue

      node_vols = sorted(nresult.payload,
                         key=operator.itemgetter("dev"))

      for vol in node_vols:
        node_output = []
        for field in self.op.output_fields:
          if field == "node":
            val = node
          elif field == "phys":
            val = vol["dev"]
          elif field == "vg":
            val = vol["vg"]
          elif field == "name":
            val = vol["name"]
          elif field == "size":
            val = int(float(vol["size"]))
          elif field == "instance":
            val = vol2inst.get((node, vol["vg"] + "/" + vol["name"]), "-")
          else:
            raise errors.ParameterError(field)
          node_output.append(str(val))

        output.append(node_output)

    return output


class LUNodeQueryStorage(NoHooksLU):
  """Logical unit for getting information on storage units on node(s).

  """
  _FIELDS_STATIC = utils.FieldSet(constants.SF_NODE)
  REQ_BGL = False

  def CheckArguments(self):
    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=utils.FieldSet(*constants.VALID_STORAGE_FIELDS),
                       selected=self.op.output_fields)

  def ExpandNames(self):
    self.share_locks = _ShareAll()

    if self.op.nodes:
      self.needed_locks = {
        locking.LEVEL_NODE: _GetWantedNodes(self, self.op.nodes),
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    self.nodes = self.owned_locks(locking.LEVEL_NODE)

    # Always get name to sort by
    if constants.SF_NAME in self.op.output_fields:
      fields = self.op.output_fields[:]
    else:
      fields = [constants.SF_NAME] + self.op.output_fields

    # Never ask for node or type as it's only known to the LU
    for extra in [constants.SF_NODE, constants.SF_TYPE]:
      while extra in fields:
        fields.remove(extra)

    field_idx = dict([(name, idx) for (idx, name) in enumerate(fields)])
    name_idx = field_idx[constants.SF_NAME]

    st_args = _GetStorageTypeArgs(self.cfg, self.op.storage_type)
    data = self.rpc.call_storage_list(self.nodes,
                                      self.op.storage_type, st_args,
                                      self.op.name, fields)

    result = []

    for node in utils.NiceSort(self.nodes):
      nresult = data[node]
      if nresult.offline:
        continue

      msg = nresult.fail_msg
      if msg:
        self.LogWarning("Can't get storage data from node %s: %s", node, msg)
        continue

      rows = dict([(row[name_idx], row) for row in nresult.payload])

      for name in utils.NiceSort(rows.keys()):
        row = rows[name]

        out = []

        for field in self.op.output_fields:
          if field == constants.SF_NODE:
            val = node
          elif field == constants.SF_TYPE:
            val = self.op.storage_type
          elif field in field_idx:
            val = row[field_idx[field]]
          else:
            raise errors.ParameterError(field)

          out.append(val)

        result.append(out)

    return result


class _InstanceQuery(_QueryBase):
  FIELDS = query.INSTANCE_FIELDS

  def ExpandNames(self, lu):
    lu.needed_locks = {}
    lu.share_locks = _ShareAll()

    if self.names:
      self.wanted = _GetWantedInstances(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = (self.use_locking and
                       query.IQ_LIVE in self.requested_data)
    if self.do_locking:
      lu.needed_locks[locking.LEVEL_INSTANCE] = self.wanted
      lu.needed_locks[locking.LEVEL_NODEGROUP] = []
      lu.needed_locks[locking.LEVEL_NODE] = []
      lu.needed_locks[locking.LEVEL_NETWORK] = []
      lu.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

    self.do_grouplocks = (self.do_locking and
                          query.IQ_NODES in self.requested_data)

  def DeclareLocks(self, lu, level):
    if self.do_locking:
      if level == locking.LEVEL_NODEGROUP and self.do_grouplocks:
        assert not lu.needed_locks[locking.LEVEL_NODEGROUP]

        # Lock all groups used by instances optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        lu.needed_locks[locking.LEVEL_NODEGROUP] = \
          set(group_uuid
              for instance_name in lu.owned_locks(locking.LEVEL_INSTANCE)
              for group_uuid in lu.cfg.GetInstanceNodeGroups(instance_name))
      elif level == locking.LEVEL_NODE:
        lu._LockInstancesNodes() # pylint: disable=W0212

      elif level == locking.LEVEL_NETWORK:
        lu.needed_locks[locking.LEVEL_NETWORK] = \
          frozenset(net_uuid
                    for instance_name in lu.owned_locks(locking.LEVEL_INSTANCE)
                    for net_uuid in lu.cfg.GetInstanceNetworks(instance_name))

  @staticmethod
  def _CheckGroupLocks(lu):
    owned_instances = frozenset(lu.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(lu.owned_locks(locking.LEVEL_NODEGROUP))

    # Check if node groups for locked instances are still correct
    for instance_name in owned_instances:
      _CheckInstanceNodeGroups(lu.cfg, instance_name, owned_groups)

  def _GetQueryData(self, lu):
    """Computes the list of instances and their attributes.

    """
    if self.do_grouplocks:
      self._CheckGroupLocks(lu)

    cluster = lu.cfg.GetClusterInfo()
    all_info = lu.cfg.GetAllInstancesInfo()

    instance_names = self._GetNames(lu, all_info.keys(), locking.LEVEL_INSTANCE)

    instance_list = [all_info[name] for name in instance_names]
    nodes = frozenset(itertools.chain(*(inst.all_nodes
                                        for inst in instance_list)))
    hv_list = list(set([inst.hypervisor for inst in instance_list]))
    bad_nodes = []
    offline_nodes = []
    wrongnode_inst = set()

    # Gather data as requested
    if self.requested_data & set([query.IQ_LIVE, query.IQ_CONSOLE]):
      live_data = {}
      node_data = lu.rpc.call_all_instances_info(nodes, hv_list)
      for name in nodes:
        result = node_data[name]
        if result.offline:
          # offline nodes will be in both lists
          assert result.fail_msg
          offline_nodes.append(name)
        if result.fail_msg:
          bad_nodes.append(name)
        elif result.payload:
          for inst in result.payload:
            if inst in all_info:
              if all_info[inst].primary_node == name:
                live_data.update(result.payload)
              else:
                wrongnode_inst.add(inst)
            else:
              # orphan instance; we don't list it here as we don't
              # handle this case yet in the output of instance listing
              logging.warning("Orphan instance '%s' found on node %s",
                              inst, name)
        # else no instance is alive
    else:
      live_data = {}

    if query.IQ_DISKUSAGE in self.requested_data:
      gmi = ganeti.masterd.instance
      disk_usage = dict((inst.name,
                         gmi.ComputeDiskSize(inst.disk_template,
                                             [{constants.IDISK_SIZE: disk.size}
                                              for disk in inst.disks]))
                        for inst in instance_list)
    else:
      disk_usage = None

    if query.IQ_CONSOLE in self.requested_data:
      consinfo = {}
      for inst in instance_list:
        if inst.name in live_data:
          # Instance is running
          consinfo[inst.name] = _GetInstanceConsole(cluster, inst)
        else:
          consinfo[inst.name] = None
      assert set(consinfo.keys()) == set(instance_names)
    else:
      consinfo = None

    if query.IQ_NODES in self.requested_data:
      node_names = set(itertools.chain(*map(operator.attrgetter("all_nodes"),
                                            instance_list)))
      nodes = dict(lu.cfg.GetMultiNodeInfo(node_names))
      groups = dict((uuid, lu.cfg.GetNodeGroup(uuid))
                    for uuid in set(map(operator.attrgetter("group"),
                                        nodes.values())))
    else:
      nodes = None
      groups = None

    if query.IQ_NETWORKS in self.requested_data:
      net_uuids = itertools.chain(*(lu.cfg.GetInstanceNetworks(i.name)
                                    for i in instance_list))
      networks = dict((uuid, lu.cfg.GetNetwork(uuid)) for uuid in net_uuids)
    else:
      networks = None

    return query.InstanceQueryData(instance_list, lu.cfg.GetClusterInfo(),
                                   disk_usage, offline_nodes, bad_nodes,
                                   live_data, wrongnode_inst, consinfo,
                                   nodes, groups, networks)


class LUQuery(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    qcls = _GetQueryImplementation(self.op.what)

    self.impl = qcls(self.op.qfilter, self.op.fields, self.op.use_locking)

  def ExpandNames(self):
    self.impl.ExpandNames(self)

  def DeclareLocks(self, level):
    self.impl.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.impl.NewStyleQuery(self)


class LUQueryFields(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.qcls = _GetQueryImplementation(self.op.what)

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    return query.QueryFields(self.qcls.FIELDS, self.op.fields)


class LUNodeModifyStorage(NoHooksLU):
  """Logical unit for modifying a storage volume on a node.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)

    storage_type = self.op.storage_type

    try:
      modifiable = constants.MODIFIABLE_STORAGE_FIELDS[storage_type]
    except KeyError:
      raise errors.OpPrereqError("Storage units of type '%s' can not be"
                                 " modified" % storage_type,
                                 errors.ECODE_INVAL)

    diff = set(self.op.changes.keys()) - modifiable
    if diff:
      raise errors.OpPrereqError("The following fields can not be modified for"
                                 " storage units of type '%s': %r" %
                                 (storage_type, list(diff)),
                                 errors.ECODE_INVAL)

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: self.op.node_name,
      }

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    st_args = _GetStorageTypeArgs(self.cfg, self.op.storage_type)
    result = self.rpc.call_storage_modify(self.op.node_name,
                                          self.op.storage_type, st_args,
                                          self.op.name, self.op.changes)
    result.Raise("Failed to modify storage unit '%s' on %s" %
                 (self.op.name, self.op.node_name))


class LUNodeAdd(LogicalUnit):
  """Logical unit for adding node to the cluster.

  """
  HPATH = "node-add"
  HTYPE = constants.HTYPE_NODE
  _NFLAGS = ["master_capable", "vm_capable"]

  def CheckArguments(self):
    self.primary_ip_family = self.cfg.GetPrimaryIPFamily()
    # validate/normalize the node name
    self.hostname = netutils.GetHostname(name=self.op.node_name,
                                         family=self.primary_ip_family)
    self.op.node_name = self.hostname.name

    if self.op.readd and self.op.node_name == self.cfg.GetMasterNode():
      raise errors.OpPrereqError("Cannot readd the master node",
                                 errors.ECODE_STATE)

    if self.op.readd and self.op.group:
      raise errors.OpPrereqError("Cannot pass a node group when a node is"
                                 " being readded", errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on all nodes before, and on all nodes + the new node after.

    """
    return {
      "OP_TARGET": self.op.node_name,
      "NODE_NAME": self.op.node_name,
      "NODE_PIP": self.op.primary_ip,
      "NODE_SIP": self.op.secondary_ip,
      "MASTER_CAPABLE": str(self.op.master_capable),
      "VM_CAPABLE": str(self.op.vm_capable),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    # Exclude added node
    pre_nodes = list(set(self.cfg.GetNodeList()) - set([self.op.node_name]))
    post_nodes = pre_nodes + [self.op.node_name, ]

    return (pre_nodes, post_nodes)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the new node is not already in the config
     - it is resolvable
     - its parameters (single/dual homed) matches the cluster

    Any errors are signaled by raising errors.OpPrereqError.

    """
    cfg = self.cfg
    hostname = self.hostname
    node = hostname.name
    primary_ip = self.op.primary_ip = hostname.ip
    if self.op.secondary_ip is None:
      if self.primary_ip_family == netutils.IP6Address.family:
        raise errors.OpPrereqError("When using a IPv6 primary address, a valid"
                                   " IPv4 address must be given as secondary",
                                   errors.ECODE_INVAL)
      self.op.secondary_ip = primary_ip

    secondary_ip = self.op.secondary_ip
    if not netutils.IP4Address.IsValid(secondary_ip):
      raise errors.OpPrereqError("Secondary IP (%s) needs to be a valid IPv4"
                                 " address" % secondary_ip, errors.ECODE_INVAL)

    node_list = cfg.GetNodeList()
    if not self.op.readd and node in node_list:
      raise errors.OpPrereqError("Node %s is already in the configuration" %
                                 node, errors.ECODE_EXISTS)
    elif self.op.readd and node not in node_list:
      raise errors.OpPrereqError("Node %s is not in the configuration" % node,
                                 errors.ECODE_NOENT)

    self.changed_primary_ip = False

    for existing_node_name, existing_node in cfg.GetMultiNodeInfo(node_list):
      if self.op.readd and node == existing_node_name:
        if existing_node.secondary_ip != secondary_ip:
          raise errors.OpPrereqError("Readded node doesn't have the same IP"
                                     " address configuration as before",
                                     errors.ECODE_INVAL)
        if existing_node.primary_ip != primary_ip:
          self.changed_primary_ip = True

        continue

      if (existing_node.primary_ip == primary_ip or
          existing_node.secondary_ip == primary_ip or
          existing_node.primary_ip == secondary_ip or
          existing_node.secondary_ip == secondary_ip):
        raise errors.OpPrereqError("New node ip address(es) conflict with"
                                   " existing node %s" % existing_node.name,
                                   errors.ECODE_NOTUNIQUE)

    # After this 'if' block, None is no longer a valid value for the
    # _capable op attributes
    if self.op.readd:
      old_node = self.cfg.GetNodeInfo(node)
      assert old_node is not None, "Can't retrieve locked node %s" % node
      for attr in self._NFLAGS:
        if getattr(self.op, attr) is None:
          setattr(self.op, attr, getattr(old_node, attr))
    else:
      for attr in self._NFLAGS:
        if getattr(self.op, attr) is None:
          setattr(self.op, attr, True)

    if self.op.readd and not self.op.vm_capable:
      pri, sec = cfg.GetNodeInstances(node)
      if pri or sec:
        raise errors.OpPrereqError("Node %s being re-added with vm_capable"
                                   " flag set to false, but it already holds"
                                   " instances" % node,
                                   errors.ECODE_STATE)

    # check that the type of the node (single versus dual homed) is the
    # same as for the master
    myself = cfg.GetNodeInfo(self.cfg.GetMasterNode())
    master_singlehomed = myself.secondary_ip == myself.primary_ip
    newbie_singlehomed = secondary_ip == primary_ip
    if master_singlehomed != newbie_singlehomed:
      if master_singlehomed:
        raise errors.OpPrereqError("The master has no secondary ip but the"
                                   " new node has one",
                                   errors.ECODE_INVAL)
      else:
        raise errors.OpPrereqError("The master has a secondary ip but the"
                                   " new node doesn't have one",
                                   errors.ECODE_INVAL)

    # checks reachability
    if not netutils.TcpPing(primary_ip, constants.DEFAULT_NODED_PORT):
      raise errors.OpPrereqError("Node not reachable by ping",
                                 errors.ECODE_ENVIRON)

    if not newbie_singlehomed:
      # check reachability from my secondary ip to newbie's secondary ip
      if not netutils.TcpPing(secondary_ip, constants.DEFAULT_NODED_PORT,
                              source=myself.secondary_ip):
        raise errors.OpPrereqError("Node secondary ip not reachable by TCP"
                                   " based ping to node daemon port",
                                   errors.ECODE_ENVIRON)

    if self.op.readd:
      exceptions = [node]
    else:
      exceptions = []

    if self.op.master_capable:
      self.master_candidate = _DecideSelfPromotion(self, exceptions=exceptions)
    else:
      self.master_candidate = False

    if self.op.readd:
      self.new_node = old_node
    else:
      node_group = cfg.LookupNodeGroup(self.op.group)
      self.new_node = objects.Node(name=node,
                                   primary_ip=primary_ip,
                                   secondary_ip=secondary_ip,
                                   master_candidate=self.master_candidate,
                                   offline=False, drained=False,
                                   group=node_group, ndparams={})

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)
      _CheckParamsNotGlobal(self.op.ndparams, constants.NDC_GLOBALS, "node",
                            "node", "cluster or group")

    if self.op.hv_state:
      self.new_hv_state = _MergeAndVerifyHvState(self.op.hv_state, None)

    if self.op.disk_state:
      self.new_disk_state = _MergeAndVerifyDiskState(self.op.disk_state, None)

    # TODO: If we need to have multiple DnsOnlyRunner we probably should make
    #       it a property on the base class.
    rpcrunner = rpc.DnsOnlyRunner()
    result = rpcrunner.call_version([node])[node]
    result.Raise("Can't get version information from node %s" % node)
    if constants.PROTOCOL_VERSION == result.payload:
      logging.info("Communication to node %s fine, sw version %s match",
                   node, result.payload)
    else:
      raise errors.OpPrereqError("Version mismatch master version %s,"
                                 " node version %s" %
                                 (constants.PROTOCOL_VERSION, result.payload),
                                 errors.ECODE_ENVIRON)

    vg_name = cfg.GetVGName()
    if vg_name is not None:
      vparams = {constants.NV_PVLIST: [vg_name]}
      excl_stor = _IsExclusiveStorageEnabledNode(cfg, self.new_node)
      cname = self.cfg.GetClusterName()
      result = rpcrunner.call_node_verify_light([node], vparams, cname)[node]
      (errmsgs, _) = _CheckNodePVs(result.payload, excl_stor)
      if errmsgs:
        raise errors.OpPrereqError("Checks on node PVs failed: %s" %
                                   "; ".join(errmsgs), errors.ECODE_ENVIRON)

  def Exec(self, feedback_fn):
    """Adds the new node to the cluster.

    """
    new_node = self.new_node
    node = new_node.name

    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER), \
      "Not owning BGL"

    # We adding a new node so we assume it's powered
    new_node.powered = True

    # for re-adds, reset the offline/drained/master-candidate flags;
    # we need to reset here, otherwise offline would prevent RPC calls
    # later in the procedure; this also means that if the re-add
    # fails, we are left with a non-offlined, broken node
    if self.op.readd:
      new_node.drained = new_node.offline = False # pylint: disable=W0201
      self.LogInfo("Readding a node, the offline/drained flags were reset")
      # if we demote the node, we do cleanup later in the procedure
      new_node.master_candidate = self.master_candidate
      if self.changed_primary_ip:
        new_node.primary_ip = self.op.primary_ip

    # copy the master/vm_capable flags
    for attr in self._NFLAGS:
      setattr(new_node, attr, getattr(self.op, attr))

    # notify the user about any possible mc promotion
    if new_node.master_candidate:
      self.LogInfo("Node will be a master candidate")

    if self.op.ndparams:
      new_node.ndparams = self.op.ndparams
    else:
      new_node.ndparams = {}

    if self.op.hv_state:
      new_node.hv_state_static = self.new_hv_state

    if self.op.disk_state:
      new_node.disk_state_static = self.new_disk_state

    # Add node to our /etc/hosts, and add key to known_hosts
    if self.cfg.GetClusterInfo().modify_etc_hosts:
      master_node = self.cfg.GetMasterNode()
      result = self.rpc.call_etc_hosts_modify(master_node,
                                              constants.ETC_HOSTS_ADD,
                                              self.hostname.name,
                                              self.hostname.ip)
      result.Raise("Can't update hosts file with new host data")

    if new_node.secondary_ip != new_node.primary_ip:
      _CheckNodeHasSecondaryIP(self, new_node.name, new_node.secondary_ip,
                               False)

    node_verify_list = [self.cfg.GetMasterNode()]
    node_verify_param = {
      constants.NV_NODELIST: ([node], {}),
      # TODO: do a node-net-test as well?
    }

    result = self.rpc.call_node_verify(node_verify_list, node_verify_param,
                                       self.cfg.GetClusterName())
    for verifier in node_verify_list:
      result[verifier].Raise("Cannot communicate with node %s" % verifier)
      nl_payload = result[verifier].payload[constants.NV_NODELIST]
      if nl_payload:
        for failed in nl_payload:
          feedback_fn("ssh/hostname verification failed"
                      " (checking from %s): %s" %
                      (verifier, nl_payload[failed]))
        raise errors.OpExecError("ssh/hostname verification failed")

    if self.op.readd:
      _RedistributeAncillaryFiles(self)
      self.context.ReaddNode(new_node)
      # make sure we redistribute the config
      self.cfg.Update(new_node, feedback_fn)
      # and make sure the new node will not have old files around
      if not new_node.master_candidate:
        result = self.rpc.call_node_demote_from_mc(new_node.name)
        msg = result.fail_msg
        if msg:
          self.LogWarning("Node failed to demote itself from master"
                          " candidate status: %s" % msg)
    else:
      _RedistributeAncillaryFiles(self, additional_nodes=[node],
                                  additional_vm=self.op.vm_capable)
      self.context.AddNode(new_node, self.proc.GetECId())


class LUNodeSetParams(LogicalUnit):
  """Modifies the parameters of a node.

  @cvar _F2R: a dictionary from tuples of flags (mc, drained, offline)
      to the node role (as _ROLE_*)
  @cvar _R2F: a dictionary from node role to tuples of flags
  @cvar _FLAGS: a list of attribute names corresponding to the flags

  """
  HPATH = "node-modify"
  HTYPE = constants.HTYPE_NODE
  REQ_BGL = False
  (_ROLE_CANDIDATE, _ROLE_DRAINED, _ROLE_OFFLINE, _ROLE_REGULAR) = range(4)
  _F2R = {
    (True, False, False): _ROLE_CANDIDATE,
    (False, True, False): _ROLE_DRAINED,
    (False, False, True): _ROLE_OFFLINE,
    (False, False, False): _ROLE_REGULAR,
    }
  _R2F = dict((v, k) for k, v in _F2R.items())
  _FLAGS = ["master_candidate", "drained", "offline"]

  def CheckArguments(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)
    all_mods = [self.op.offline, self.op.master_candidate, self.op.drained,
                self.op.master_capable, self.op.vm_capable,
                self.op.secondary_ip, self.op.ndparams, self.op.hv_state,
                self.op.disk_state]
    if all_mods.count(None) == len(all_mods):
      raise errors.OpPrereqError("Please pass at least one modification",
                                 errors.ECODE_INVAL)
    if all_mods.count(True) > 1:
      raise errors.OpPrereqError("Can't set the node into more than one"
                                 " state at the same time",
                                 errors.ECODE_INVAL)

    # Boolean value that tells us whether we might be demoting from MC
    self.might_demote = (self.op.master_candidate is False or
                         self.op.offline is True or
                         self.op.drained is True or
                         self.op.master_capable is False)

    if self.op.secondary_ip:
      if not netutils.IP4Address.IsValid(self.op.secondary_ip):
        raise errors.OpPrereqError("Secondary IP (%s) needs to be a valid IPv4"
                                   " address" % self.op.secondary_ip,
                                   errors.ECODE_INVAL)

    self.lock_all = self.op.auto_promote and self.might_demote
    self.lock_instances = self.op.secondary_ip is not None

  def _InstanceFilter(self, instance):
    """Filter for getting affected instances.

    """
    return (instance.disk_template in constants.DTS_INT_MIRROR and
            self.op.node_name in instance.all_nodes)

  def ExpandNames(self):
    if self.lock_all:
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,

        # Block allocations when all nodes are locked
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODE: self.op.node_name,
        }

    # Since modifying a node can have severe effects on currently running
    # operations the resource lock is at least acquired in shared mode
    self.needed_locks[locking.LEVEL_NODE_RES] = \
      self.needed_locks[locking.LEVEL_NODE]

    # Get all locks except nodes in shared mode; they are not used for anything
    # but read-only access
    self.share_locks = _ShareAll()
    self.share_locks[locking.LEVEL_NODE] = 0
    self.share_locks[locking.LEVEL_NODE_RES] = 0
    self.share_locks[locking.LEVEL_NODE_ALLOC] = 0

    if self.lock_instances:
      self.needed_locks[locking.LEVEL_INSTANCE] = \
        frozenset(self.cfg.GetInstancesInfoByFilter(self._InstanceFilter))

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master node.

    """
    return {
      "OP_TARGET": self.op.node_name,
      "MASTER_CANDIDATE": str(self.op.master_candidate),
      "OFFLINE": str(self.op.offline),
      "DRAINED": str(self.op.drained),
      "MASTER_CAPABLE": str(self.op.master_capable),
      "VM_CAPABLE": str(self.op.vm_capable),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.op.node_name]
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    node = self.node = self.cfg.GetNodeInfo(self.op.node_name)

    if self.lock_instances:
      affected_instances = \
        self.cfg.GetInstancesInfoByFilter(self._InstanceFilter)

      # Verify instance locks
      owned_instances = self.owned_locks(locking.LEVEL_INSTANCE)
      wanted_instances = frozenset(affected_instances.keys())
      if wanted_instances - owned_instances:
        raise errors.OpPrereqError("Instances affected by changing node %s's"
                                   " secondary IP address have changed since"
                                   " locks were acquired, wanted '%s', have"
                                   " '%s'; retry the operation" %
                                   (self.op.node_name,
                                    utils.CommaJoin(wanted_instances),
                                    utils.CommaJoin(owned_instances)),
                                   errors.ECODE_STATE)
    else:
      affected_instances = None

    if (self.op.master_candidate is not None or
        self.op.drained is not None or
        self.op.offline is not None):
      # we can't change the master's node flags
      if self.op.node_name == self.cfg.GetMasterNode():
        raise errors.OpPrereqError("The master role can be changed"
                                   " only via master-failover",
                                   errors.ECODE_INVAL)

    if self.op.master_candidate and not node.master_capable:
      raise errors.OpPrereqError("Node %s is not master capable, cannot make"
                                 " it a master candidate" % node.name,
                                 errors.ECODE_STATE)

    if self.op.vm_capable is False:
      (ipri, isec) = self.cfg.GetNodeInstances(self.op.node_name)
      if ipri or isec:
        raise errors.OpPrereqError("Node %s hosts instances, cannot unset"
                                   " the vm_capable flag" % node.name,
                                   errors.ECODE_STATE)

    if node.master_candidate and self.might_demote and not self.lock_all:
      assert not self.op.auto_promote, "auto_promote set but lock_all not"
      # check if after removing the current node, we're missing master
      # candidates
      (mc_remaining, mc_should, _) = \
          self.cfg.GetMasterCandidateStats(exceptions=[node.name])
      if mc_remaining < mc_should:
        raise errors.OpPrereqError("Not enough master candidates, please"
                                   " pass auto promote option to allow"
                                   " promotion (--auto-promote or RAPI"
                                   " auto_promote=True)", errors.ECODE_STATE)

    self.old_flags = old_flags = (node.master_candidate,
                                  node.drained, node.offline)
    assert old_flags in self._F2R, "Un-handled old flags %s" % str(old_flags)
    self.old_role = old_role = self._F2R[old_flags]

    # Check for ineffective changes
    for attr in self._FLAGS:
      if (getattr(self.op, attr) is False and getattr(node, attr) is False):
        self.LogInfo("Ignoring request to unset flag %s, already unset", attr)
        setattr(self.op, attr, None)

    # Past this point, any flag change to False means a transition
    # away from the respective state, as only real changes are kept

    # TODO: We might query the real power state if it supports OOB
    if _SupportsOob(self.cfg, node):
      if self.op.offline is False and not (node.powered or
                                           self.op.powered is True):
        raise errors.OpPrereqError(("Node %s needs to be turned on before its"
                                    " offline status can be reset") %
                                   self.op.node_name, errors.ECODE_STATE)
    elif self.op.powered is not None:
      raise errors.OpPrereqError(("Unable to change powered state for node %s"
                                  " as it does not support out-of-band"
                                  " handling") % self.op.node_name,
                                 errors.ECODE_STATE)

    # If we're being deofflined/drained, we'll MC ourself if needed
    if (self.op.drained is False or self.op.offline is False or
        (self.op.master_capable and not node.master_capable)):
      if _DecideSelfPromotion(self):
        self.op.master_candidate = True
        self.LogInfo("Auto-promoting node to master candidate")

    # If we're no longer master capable, we'll demote ourselves from MC
    if self.op.master_capable is False and node.master_candidate:
      self.LogInfo("Demoting from master candidate")
      self.op.master_candidate = False

    # Compute new role
    assert [getattr(self.op, attr) for attr in self._FLAGS].count(True) <= 1
    if self.op.master_candidate:
      new_role = self._ROLE_CANDIDATE
    elif self.op.drained:
      new_role = self._ROLE_DRAINED
    elif self.op.offline:
      new_role = self._ROLE_OFFLINE
    elif False in [self.op.master_candidate, self.op.drained, self.op.offline]:
      # False is still in new flags, which means we're un-setting (the
      # only) True flag
      new_role = self._ROLE_REGULAR
    else: # no new flags, nothing, keep old role
      new_role = old_role

    self.new_role = new_role

    if old_role == self._ROLE_OFFLINE and new_role != old_role:
      # Trying to transition out of offline status
      result = self.rpc.call_version([node.name])[node.name]
      if result.fail_msg:
        raise errors.OpPrereqError("Node %s is being de-offlined but fails"
                                   " to report its version: %s" %
                                   (node.name, result.fail_msg),
                                   errors.ECODE_STATE)
      else:
        self.LogWarning("Transitioning node from offline to online state"
                        " without using re-add. Please make sure the node"
                        " is healthy!")

    # When changing the secondary ip, verify if this is a single-homed to
    # multi-homed transition or vice versa, and apply the relevant
    # restrictions.
    if self.op.secondary_ip:
      # Ok even without locking, because this can't be changed by any LU
      master = self.cfg.GetNodeInfo(self.cfg.GetMasterNode())
      master_singlehomed = master.secondary_ip == master.primary_ip
      if master_singlehomed and self.op.secondary_ip != node.primary_ip:
        if self.op.force and node.name == master.name:
          self.LogWarning("Transitioning from single-homed to multi-homed"
                          " cluster; all nodes will require a secondary IP"
                          " address")
        else:
          raise errors.OpPrereqError("Changing the secondary ip on a"
                                     " single-homed cluster requires the"
                                     " --force option to be passed, and the"
                                     " target node to be the master",
                                     errors.ECODE_INVAL)
      elif not master_singlehomed and self.op.secondary_ip == node.primary_ip:
        if self.op.force and node.name == master.name:
          self.LogWarning("Transitioning from multi-homed to single-homed"
                          " cluster; secondary IP addresses will have to be"
                          " removed")
        else:
          raise errors.OpPrereqError("Cannot set the secondary IP to be the"
                                     " same as the primary IP on a multi-homed"
                                     " cluster, unless the --force option is"
                                     " passed, and the target node is the"
                                     " master", errors.ECODE_INVAL)

      assert not (frozenset(affected_instances) -
                  self.owned_locks(locking.LEVEL_INSTANCE))

      if node.offline:
        if affected_instances:
          msg = ("Cannot change secondary IP address: offline node has"
                 " instances (%s) configured to use it" %
                 utils.CommaJoin(affected_instances.keys()))
          raise errors.OpPrereqError(msg, errors.ECODE_STATE)
      else:
        # On online nodes, check that no instances are running, and that
        # the node has the new ip and we can reach it.
        for instance in affected_instances.values():
          _CheckInstanceState(self, instance, INSTANCE_DOWN,
                              msg="cannot change secondary ip")

        _CheckNodeHasSecondaryIP(self, node.name, self.op.secondary_ip, True)
        if master.name != node.name:
          # check reachability from master secondary ip to new secondary ip
          if not netutils.TcpPing(self.op.secondary_ip,
                                  constants.DEFAULT_NODED_PORT,
                                  source=master.secondary_ip):
            raise errors.OpPrereqError("Node secondary ip not reachable by TCP"
                                       " based ping to node daemon port",
                                       errors.ECODE_ENVIRON)

    if self.op.ndparams:
      new_ndparams = _GetUpdatedParams(self.node.ndparams, self.op.ndparams)
      utils.ForceDictType(new_ndparams, constants.NDS_PARAMETER_TYPES)
      _CheckParamsNotGlobal(self.op.ndparams, constants.NDC_GLOBALS, "node",
                            "node", "cluster or group")
      self.new_ndparams = new_ndparams

    if self.op.hv_state:
      self.new_hv_state = _MergeAndVerifyHvState(self.op.hv_state,
                                                 self.node.hv_state_static)

    if self.op.disk_state:
      self.new_disk_state = \
        _MergeAndVerifyDiskState(self.op.disk_state,
                                 self.node.disk_state_static)

  def Exec(self, feedback_fn):
    """Modifies a node.

    """
    node = self.node
    old_role = self.old_role
    new_role = self.new_role

    result = []

    if self.op.ndparams:
      node.ndparams = self.new_ndparams

    if self.op.powered is not None:
      node.powered = self.op.powered

    if self.op.hv_state:
      node.hv_state_static = self.new_hv_state

    if self.op.disk_state:
      node.disk_state_static = self.new_disk_state

    for attr in ["master_capable", "vm_capable"]:
      val = getattr(self.op, attr)
      if val is not None:
        setattr(node, attr, val)
        result.append((attr, str(val)))

    if new_role != old_role:
      # Tell the node to demote itself, if no longer MC and not offline
      if old_role == self._ROLE_CANDIDATE and new_role != self._ROLE_OFFLINE:
        msg = self.rpc.call_node_demote_from_mc(node.name).fail_msg
        if msg:
          self.LogWarning("Node failed to demote itself: %s", msg)

      new_flags = self._R2F[new_role]
      for of, nf, desc in zip(self.old_flags, new_flags, self._FLAGS):
        if of != nf:
          result.append((desc, str(nf)))
      (node.master_candidate, node.drained, node.offline) = new_flags

      # we locked all nodes, we adjust the CP before updating this node
      if self.lock_all:
        _AdjustCandidatePool(self, [node.name])

    if self.op.secondary_ip:
      node.secondary_ip = self.op.secondary_ip
      result.append(("secondary_ip", self.op.secondary_ip))

    # this will trigger configuration file update, if needed
    self.cfg.Update(node, feedback_fn)

    # this will trigger job queue propagation or cleanup if the mc
    # flag changed
    if [old_role, new_role].count(self._ROLE_CANDIDATE) == 1:
      self.context.ReaddNode(node)

    return result


class LUNodePowercycle(NoHooksLU):
  """Powercycles a node.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)
    if self.op.node_name == self.cfg.GetMasterNode() and not self.op.force:
      raise errors.OpPrereqError("The node is the master and the force"
                                 " parameter was not set",
                                 errors.ECODE_INVAL)

  def ExpandNames(self):
    """Locking for PowercycleNode.

    This is a last-resort option and shouldn't block on other
    jobs. Therefore, we grab no locks.

    """
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    """Reboots a node.

    """
    result = self.rpc.call_node_powercycle(self.op.node_name,
                                           self.cfg.GetHypervisorType())
    result.Raise("Failed to schedule the reboot")
    return result.payload


class LUClusterQuery(NoHooksLU):
  """Query cluster configuration.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    """Return cluster config.

    """
    cluster = self.cfg.GetClusterInfo()
    os_hvp = {}

    # Filter just for enabled hypervisors
    for os_name, hv_dict in cluster.os_hvp.items():
      os_hvp[os_name] = {}
      for hv_name, hv_params in hv_dict.items():
        if hv_name in cluster.enabled_hypervisors:
          os_hvp[os_name][hv_name] = hv_params

    # Convert ip_family to ip_version
    primary_ip_version = constants.IP4_VERSION
    if cluster.primary_ip_family == netutils.IP6Address.family:
      primary_ip_version = constants.IP6_VERSION

    result = {
      "software_version": constants.RELEASE_VERSION,
      "protocol_version": constants.PROTOCOL_VERSION,
      "config_version": constants.CONFIG_VERSION,
      "os_api_version": max(constants.OS_API_VERSIONS),
      "export_version": constants.EXPORT_VERSION,
      "architecture": runtime.GetArchInfo(),
      "name": cluster.cluster_name,
      "master": cluster.master_node,
      "default_hypervisor": cluster.primary_hypervisor,
      "enabled_hypervisors": cluster.enabled_hypervisors,
      "hvparams": dict([(hypervisor_name, cluster.hvparams[hypervisor_name])
                        for hypervisor_name in cluster.enabled_hypervisors]),
      "os_hvp": os_hvp,
      "beparams": cluster.beparams,
      "osparams": cluster.osparams,
      "ipolicy": cluster.ipolicy,
      "nicparams": cluster.nicparams,
      "ndparams": cluster.ndparams,
      "diskparams": cluster.diskparams,
      "candidate_pool_size": cluster.candidate_pool_size,
      "master_netdev": cluster.master_netdev,
      "master_netmask": cluster.master_netmask,
      "use_external_mip_script": cluster.use_external_mip_script,
      "volume_group_name": cluster.volume_group_name,
      "drbd_usermode_helper": cluster.drbd_usermode_helper,
      "file_storage_dir": cluster.file_storage_dir,
      "shared_file_storage_dir": cluster.shared_file_storage_dir,
      "maintain_node_health": cluster.maintain_node_health,
      "ctime": cluster.ctime,
      "mtime": cluster.mtime,
      "uuid": cluster.uuid,
      "tags": list(cluster.GetTags()),
      "uid_pool": cluster.uid_pool,
      "default_iallocator": cluster.default_iallocator,
      "reserved_lvs": cluster.reserved_lvs,
      "primary_ip_version": primary_ip_version,
      "prealloc_wipe_disks": cluster.prealloc_wipe_disks,
      "hidden_os": cluster.hidden_os,
      "blacklisted_os": cluster.blacklisted_os,
      }

    return result


class LUClusterConfigQuery(NoHooksLU):
  """Return configuration values.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.cq = _ClusterQuery(None, self.op.output_fields, False)

  def ExpandNames(self):
    self.cq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.cq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    result = self.cq.OldStyleQuery(self)

    assert len(result) == 1

    return result[0]


class _ClusterQuery(_QueryBase):
  FIELDS = query.CLUSTER_FIELDS

  #: Do not sort (there is only one item)
  SORT_FIELD = None

  def ExpandNames(self, lu):
    lu.needed_locks = {}

    # The following variables interact with _QueryBase._GetNames
    self.wanted = locking.ALL_SET
    self.do_locking = self.use_locking

    if self.do_locking:
      raise errors.OpPrereqError("Can not use locking for cluster queries",
                                 errors.ECODE_INVAL)

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    if query.CQ_CONFIG in self.requested_data:
      cluster = lu.cfg.GetClusterInfo()
    else:
      cluster = NotImplemented

    if query.CQ_QUEUE_DRAINED in self.requested_data:
      drain_flag = os.path.exists(pathutils.JOB_QUEUE_DRAIN_FILE)
    else:
      drain_flag = NotImplemented

    if query.CQ_WATCHER_PAUSE in self.requested_data:
      master_name = lu.cfg.GetMasterNode()

      result = lu.rpc.call_get_watcher_pause(master_name)
      result.Raise("Can't retrieve watcher pause from master node '%s'" %
                   master_name)

      watcher_pause = result.payload
    else:
      watcher_pause = NotImplemented

    return query.ClusterQueryData(cluster, drain_flag, watcher_pause)


class LUInstanceActivateDisks(NoHooksLU):
  """Bring up an instance's disks.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Activate the disks.

    """
    disks_ok, disks_info = \
              _AssembleInstanceDisks(self, self.instance,
                                     ignore_size=self.op.ignore_size)
    if not disks_ok:
      raise errors.OpExecError("Cannot activate block devices")

    if self.op.wait_for_sync:
      if not _WaitForSync(self, self.instance):
        raise errors.OpExecError("Some disks of the instance are degraded!")

    return disks_info


def _AssembleInstanceDisks(lu, instance, disks=None, ignore_secondaries=False,
                           ignore_size=False):
  """Prepare the block devices for an instance.

  This sets up the block devices on all nodes.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance for whose disks we assemble
  @type disks: list of L{objects.Disk} or None
  @param disks: which disks to assemble (or all, if None)
  @type ignore_secondaries: boolean
  @param ignore_secondaries: if true, errors on secondary nodes
      won't result in an error return from the function
  @type ignore_size: boolean
  @param ignore_size: if true, the current known size of the disk
      will not be used during the disk activation, useful for cases
      when the size is wrong
  @return: False if the operation failed, otherwise a list of
      (host, instance_visible_name, node_visible_name)
      with the mapping from node devices to instance devices

  """
  device_info = []
  disks_ok = True
  iname = instance.name
  disks = _ExpandCheckDisks(instance, disks)

  # With the two passes mechanism we try to reduce the window of
  # opportunity for the race condition of switching DRBD to primary
  # before handshaking occured, but we do not eliminate it

  # The proper fix would be to wait (with some limits) until the
  # connection has been made and drbd transitions from WFConnection
  # into any other network-connected state (Connected, SyncTarget,
  # SyncSource, etc.)

  # 1st pass, assemble on all nodes in secondary mode
  for idx, inst_disk in enumerate(disks):
    for node, node_disk in inst_disk.ComputeNodeTree(instance.primary_node):
      if ignore_size:
        node_disk = node_disk.Copy()
        node_disk.UnsetSize()
      lu.cfg.SetDiskID(node_disk, node)
      result = lu.rpc.call_blockdev_assemble(node, (node_disk, instance), iname,
                                             False, idx)
      msg = result.fail_msg
      if msg:
        is_offline_secondary = (node in instance.secondary_nodes and
                                result.offline)
        lu.LogWarning("Could not prepare block device %s on node %s"
                      " (is_primary=False, pass=1): %s",
                      inst_disk.iv_name, node, msg)
        if not (ignore_secondaries or is_offline_secondary):
          disks_ok = False

  # FIXME: race condition on drbd migration to primary

  # 2nd pass, do only the primary node
  for idx, inst_disk in enumerate(disks):
    dev_path = None

    for node, node_disk in inst_disk.ComputeNodeTree(instance.primary_node):
      if node != instance.primary_node:
        continue
      if ignore_size:
        node_disk = node_disk.Copy()
        node_disk.UnsetSize()
      lu.cfg.SetDiskID(node_disk, node)
      result = lu.rpc.call_blockdev_assemble(node, (node_disk, instance), iname,
                                             True, idx)
      msg = result.fail_msg
      if msg:
        lu.LogWarning("Could not prepare block device %s on node %s"
                      " (is_primary=True, pass=2): %s",
                      inst_disk.iv_name, node, msg)
        disks_ok = False
      else:
        dev_path = result.payload

    device_info.append((instance.primary_node, inst_disk.iv_name, dev_path))

  # leave the disks configured for the primary node
  # this is a workaround that would be fixed better by
  # improving the logical/physical id handling
  for disk in disks:
    lu.cfg.SetDiskID(disk, instance.primary_node)

  return disks_ok, device_info


def _StartInstanceDisks(lu, instance, force):
  """Start the disks of an instance.

  """
  disks_ok, _ = _AssembleInstanceDisks(lu, instance,
                                           ignore_secondaries=force)
  if not disks_ok:
    _ShutdownInstanceDisks(lu, instance)
    if force is not None and not force:
      lu.LogWarning("",
                    hint=("If the message above refers to a secondary node,"
                          " you can retry the operation using '--force'"))
    raise errors.OpExecError("Disk consistency error")


class LUInstanceDeactivateDisks(NoHooksLU):
  """Shutdown an instance's disks.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

  def Exec(self, feedback_fn):
    """Deactivate the disks

    """
    instance = self.instance
    if self.op.force:
      _ShutdownInstanceDisks(self, instance)
    else:
      _SafeShutdownInstanceDisks(self, instance)


def _SafeShutdownInstanceDisks(lu, instance, disks=None):
  """Shutdown block devices of an instance.

  This function checks if an instance is running, before calling
  _ShutdownInstanceDisks.

  """
  _CheckInstanceState(lu, instance, INSTANCE_DOWN, msg="cannot shutdown disks")
  _ShutdownInstanceDisks(lu, instance, disks=disks)


def _ExpandCheckDisks(instance, disks):
  """Return the instance disks selected by the disks list

  @type disks: list of L{objects.Disk} or None
  @param disks: selected disks
  @rtype: list of L{objects.Disk}
  @return: selected instance disks to act on

  """
  if disks is None:
    return instance.disks
  else:
    if not set(disks).issubset(instance.disks):
      raise errors.ProgrammerError("Can only act on disks belonging to the"
                                   " target instance")
    return disks


def _ShutdownInstanceDisks(lu, instance, disks=None, ignore_primary=False):
  """Shutdown block devices of an instance.

  This does the shutdown on all nodes of the instance.

  If the ignore_primary is false, errors on the primary node are
  ignored.

  """
  all_result = True
  disks = _ExpandCheckDisks(instance, disks)

  for disk in disks:
    for node, top_disk in disk.ComputeNodeTree(instance.primary_node):
      lu.cfg.SetDiskID(top_disk, node)
      result = lu.rpc.call_blockdev_shutdown(node, (top_disk, instance))
      msg = result.fail_msg
      if msg:
        lu.LogWarning("Could not shutdown block device %s on node %s: %s",
                      disk.iv_name, node, msg)
        if ((node == instance.primary_node and not ignore_primary) or
            (node != instance.primary_node and not result.offline)):
          all_result = False
  return all_result


def _CheckNodeFreeMemory(lu, node, reason, requested, hypervisor_name):
  """Checks if a node has enough free memory.

  This function checks if a given node has the needed amount of free
  memory. In case the node has less memory or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type node: C{str}
  @param node: the node to check
  @type reason: C{str}
  @param reason: string to use in the error message
  @type requested: C{int}
  @param requested: the amount of memory in MiB to check for
  @type hypervisor_name: C{str}
  @param hypervisor_name: the hypervisor to ask for memory stats
  @rtype: integer
  @return: node current free memory
  @raise errors.OpPrereqError: if the node doesn't have enough memory, or
      we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info([node], None, [hypervisor_name], False)
  nodeinfo[node].Raise("Can't get data from node %s" % node,
                       prereq=True, ecode=errors.ECODE_ENVIRON)
  (_, _, (hv_info, )) = nodeinfo[node].payload

  free_mem = hv_info.get("memory_free", None)
  if not isinstance(free_mem, int):
    raise errors.OpPrereqError("Can't compute free memory on node %s, result"
                               " was '%s'" % (node, free_mem),
                               errors.ECODE_ENVIRON)
  if requested > free_mem:
    raise errors.OpPrereqError("Not enough memory on node %s for %s:"
                               " needed %s MiB, available %s MiB" %
                               (node, reason, requested, free_mem),
                               errors.ECODE_NORES)
  return free_mem


def _CheckNodesFreeDiskPerVG(lu, nodenames, req_sizes):
  """Checks if nodes have enough free disk space in all the VGs.

  This function checks if all given nodes have the needed amount of
  free disk. In case any node has less disk or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type nodenames: C{list}
  @param nodenames: the list of node names to check
  @type req_sizes: C{dict}
  @param req_sizes: the hash of vg and corresponding amount of disk in
      MiB to check for
  @raise errors.OpPrereqError: if the node doesn't have enough disk,
      or we cannot check the node

  """
  for vg, req_size in req_sizes.items():
    _CheckNodesFreeDiskOnVG(lu, nodenames, vg, req_size)


def _CheckNodesFreeDiskOnVG(lu, nodenames, vg, requested):
  """Checks if nodes have enough free disk space in the specified VG.

  This function checks if all given nodes have the needed amount of
  free disk. In case any node has less disk or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type nodenames: C{list}
  @param nodenames: the list of node names to check
  @type vg: C{str}
  @param vg: the volume group to check
  @type requested: C{int}
  @param requested: the amount of disk in MiB to check for
  @raise errors.OpPrereqError: if the node doesn't have enough disk,
      or we cannot check the node

  """
  es_flags = rpc.GetExclusiveStorageForNodeNames(lu.cfg, nodenames)
  nodeinfo = lu.rpc.call_node_info(nodenames, [vg], None, es_flags)
  for node in nodenames:
    info = nodeinfo[node]
    info.Raise("Cannot get current information from node %s" % node,
               prereq=True, ecode=errors.ECODE_ENVIRON)
    (_, (vg_info, ), _) = info.payload
    vg_free = vg_info.get("vg_free", None)
    if not isinstance(vg_free, int):
      raise errors.OpPrereqError("Can't compute free disk space on node"
                                 " %s for vg %s, result was '%s'" %
                                 (node, vg, vg_free), errors.ECODE_ENVIRON)
    if requested > vg_free:
      raise errors.OpPrereqError("Not enough disk space on target node %s"
                                 " vg %s: required %d MiB, available %d MiB" %
                                 (node, vg, requested, vg_free),
                                 errors.ECODE_NORES)


def _CheckNodesPhysicalCPUs(lu, nodenames, requested, hypervisor_name):
  """Checks if nodes have enough physical CPUs

  This function checks if all given nodes have the needed number of
  physical CPUs. In case any node has less CPUs or we cannot get the
  information from the node, this function raises an OpPrereqError
  exception.

  @type lu: C{LogicalUnit}
  @param lu: a logical unit from which we get configuration data
  @type nodenames: C{list}
  @param nodenames: the list of node names to check
  @type requested: C{int}
  @param requested: the minimum acceptable number of physical CPUs
  @raise errors.OpPrereqError: if the node doesn't have enough CPUs,
      or we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info(nodenames, None, [hypervisor_name], None)
  for node in nodenames:
    info = nodeinfo[node]
    info.Raise("Cannot get current information from node %s" % node,
               prereq=True, ecode=errors.ECODE_ENVIRON)
    (_, _, (hv_info, )) = info.payload
    num_cpus = hv_info.get("cpu_total", None)
    if not isinstance(num_cpus, int):
      raise errors.OpPrereqError("Can't compute the number of physical CPUs"
                                 " on node %s, result was '%s'" %
                                 (node, num_cpus), errors.ECODE_ENVIRON)
    if requested > num_cpus:
      raise errors.OpPrereqError("Node %s has %s physical CPUs, but %s are "
                                 "required" % (node, num_cpus, requested),
                                 errors.ECODE_NORES)


class LUInstanceStartup(LogicalUnit):
  """Starts an instance.

  """
  HPATH = "instance-start"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    # extra beparams
    if self.op.beparams:
      # fill the beparams dict
      objects.UpgradeBeParams(self.op.beparams)
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE_RES:
      self._LockInstancesNodes(primary_only=True, level=locking.LEVEL_NODE_RES)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "FORCE": self.op.force,
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    # extra hvparams
    if self.op.hvparams:
      # check hypervisor parameter syntax (locally)
      cluster = self.cfg.GetClusterInfo()
      utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
      filled_hvp = cluster.FillHV(instance)
      filled_hvp.update(self.op.hvparams)
      hv_type = hypervisor.GetHypervisorClass(instance.hypervisor)
      hv_type.CheckParameterSyntax(filled_hvp)
      _CheckHVParams(self, instance.all_nodes, instance.hypervisor, filled_hvp)

    _CheckInstanceState(self, instance, INSTANCE_ONLINE)

    self.primary_offline = self.cfg.GetNodeInfo(instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")

      if self.op.hvparams or self.op.beparams:
        self.LogWarning("Overridden parameters are ignored")
    else:
      _CheckNodeOnline(self, instance.primary_node)

      bep = self.cfg.GetClusterInfo().FillBE(instance)
      bep.update(self.op.beparams)

      # check bridges existence
      _CheckInstanceBridgesExist(self, instance)

      remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                instance.name,
                                                instance.hypervisor)
      remote_info.Raise("Error checking node %s" % instance.primary_node,
                        prereq=True, ecode=errors.ECODE_ENVIRON)
      if not remote_info.payload: # not running already
        _CheckNodeFreeMemory(self, instance.primary_node,
                             "starting instance %s" % instance.name,
                             bep[constants.BE_MINMEM], instance.hypervisor)

  def Exec(self, feedback_fn):
    """Start the instance.

    """
    instance = self.instance
    force = self.op.force

    if not self.op.no_remember:
      self.cfg.MarkInstanceUp(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as started")
    else:
      node_current = instance.primary_node

      _StartInstanceDisks(self, instance, force)

      result = \
        self.rpc.call_instance_start(node_current,
                                     (instance, self.op.hvparams,
                                      self.op.beparams),
                                     self.op.startup_paused)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance: %s" % msg)


class LUInstanceReboot(LogicalUnit):
  """Reboot an instance.

  """
  HPATH = "instance-reboot"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "IGNORE_SECONDARIES": self.op.ignore_secondaries,
      "REBOOT_TYPE": self.op.reboot_type,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckInstanceState(self, instance, INSTANCE_ONLINE)
    _CheckNodeOnline(self, instance.primary_node)

    # check bridges existence
    _CheckInstanceBridgesExist(self, instance)

  def Exec(self, feedback_fn):
    """Reboot the instance.

    """
    instance = self.instance
    ignore_secondaries = self.op.ignore_secondaries
    reboot_type = self.op.reboot_type

    remote_info = self.rpc.call_instance_info(instance.primary_node,
                                              instance.name,
                                              instance.hypervisor)
    remote_info.Raise("Error checking node %s" % instance.primary_node)
    instance_running = bool(remote_info.payload)

    node_current = instance.primary_node

    if instance_running and reboot_type in [constants.INSTANCE_REBOOT_SOFT,
                                            constants.INSTANCE_REBOOT_HARD]:
      for disk in instance.disks:
        self.cfg.SetDiskID(disk, node_current)
      result = self.rpc.call_instance_reboot(node_current, instance,
                                             reboot_type,
                                             self.op.shutdown_timeout)
      result.Raise("Could not reboot instance")
    else:
      if instance_running:
        result = self.rpc.call_instance_shutdown(node_current, instance,
                                                 self.op.shutdown_timeout)
        result.Raise("Could not shutdown instance for full reboot")
        _ShutdownInstanceDisks(self, instance)
      else:
        self.LogInfo("Instance %s was already stopped, starting now",
                     instance.name)
      _StartInstanceDisks(self, instance, ignore_secondaries)
      result = self.rpc.call_instance_start(node_current,
                                            (instance, None, None), False)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance for"
                                 " full reboot: %s" % msg)

    self.cfg.MarkInstanceUp(instance.name)


class LUInstanceShutdown(LogicalUnit):
  """Shutdown an instance.

  """
  HPATH = "instance-stop"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["TIMEOUT"] = self.op.timeout
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if not self.op.force:
      _CheckInstanceState(self, self.instance, INSTANCE_ONLINE)
    else:
      self.LogWarning("Ignoring offline instance check")

    self.primary_offline = \
      self.cfg.GetNodeInfo(self.instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")
    else:
      _CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Shutdown the instance.

    """
    instance = self.instance
    node_current = instance.primary_node
    timeout = self.op.timeout

    # If the instance is offline we shouldn't mark it as down, as that
    # resets the offline flag.
    if not self.op.no_remember and instance.admin_state in INSTANCE_ONLINE:
      self.cfg.MarkInstanceDown(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as stopped")
    else:
      result = self.rpc.call_instance_shutdown(node_current, instance, timeout)
      msg = result.fail_msg
      if msg:
        self.LogWarning("Could not shutdown instance: %s", msg)

      _ShutdownInstanceDisks(self, instance)


class LUInstanceReinstall(LogicalUnit):
  """Reinstall an instance.

  """
  HPATH = "instance-reinstall"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    return _BuildInstanceHookEnvByObject(self, self.instance)

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node, "Instance primary node"
                     " offline, cannot reinstall")

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name,
                                 errors.ECODE_INVAL)
    _CheckInstanceState(self, instance, INSTANCE_DOWN, msg="cannot reinstall")

    if self.op.os_type is not None:
      # OS verification
      pnode = _ExpandNodeName(self.cfg, instance.primary_node)
      _CheckNodeHasOS(self, pnode, self.op.os_type, self.op.force_variant)
      instance_os = self.op.os_type
    else:
      instance_os = instance.os

    nodelist = list(instance.all_nodes)

    if self.op.osparams:
      i_osdict = _GetUpdatedParams(instance.osparams, self.op.osparams)
      _CheckOSParams(self, True, nodelist, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = None

    self.instance = instance

  def Exec(self, feedback_fn):
    """Reinstall the instance.

    """
    inst = self.instance

    if self.op.os_type is not None:
      feedback_fn("Changing OS to '%s'..." % self.op.os_type)
      inst.os = self.op.os_type
      # Write to configuration
      self.cfg.Update(inst, feedback_fn)

    _StartInstanceDisks(self, inst, None)
    try:
      feedback_fn("Running the instance OS create scripts...")
      # FIXME: pass debug option from opcode to backend
      result = self.rpc.call_instance_os_add(inst.primary_node,
                                             (inst, self.os_inst), True,
                                             self.op.debug_level)
      result.Raise("Could not install OS for instance %s on node %s" %
                   (inst.name, inst.primary_node))
    finally:
      _ShutdownInstanceDisks(self, inst)


class LUInstanceRecreateDisks(LogicalUnit):
  """Recreate an instance's missing disks.

  """
  HPATH = "instance-recreate-disks"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  _MODIFYABLE = compat.UniqueFrozenset([
    constants.IDISK_SIZE,
    constants.IDISK_MODE,
    ])

  # New or changed disk parameters may have different semantics
  assert constants.IDISK_PARAMS == (_MODIFYABLE | frozenset([
    constants.IDISK_ADOPT,

    # TODO: Implement support changing VG while recreating
    constants.IDISK_VG,
    constants.IDISK_METAVG,
    constants.IDISK_PROVIDER,
    ]))

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    be_full = self.cfg.GetClusterInfo().FillBE(self.instance)

    # FIXME
    # The allocator should actually run in "relocate" mode, but current
    # allocators don't support relocating all the nodes of an instance at
    # the same time. As a workaround we use "allocate" mode, but this is
    # suboptimal for two reasons:
    # - The instance name passed to the allocator is present in the list of
    #   existing instances, so there could be a conflict within the
    #   internal structures of the allocator. This doesn't happen with the
    #   current allocators, but it's a liability.
    # - The allocator counts the resources used by the instance twice: once
    #   because the instance exists already, and once because it tries to
    #   allocate a new instance.
    # The allocator could choose some of the nodes on which the instance is
    # running, but that's not a problem. If the instance nodes are broken,
    # they should be already be marked as drained or offline, and hence
    # skipped by the allocator. If instance disks have been lost for other
    # reasons, then recreating the disks on the same nodes should be fine.
    disk_template = self.instance.disk_template
    spindle_use = be_full[constants.BE_SPINDLE_USE]
    req = iallocator.IAReqInstanceAlloc(name=self.op.instance_name,
                                        disk_template=disk_template,
                                        tags=list(self.instance.GetTags()),
                                        os=self.instance.os,
                                        nics=[{}],
                                        vcpus=be_full[constants.BE_VCPUS],
                                        memory=be_full[constants.BE_MAXMEM],
                                        spindle_use=spindle_use,
                                        disks=[{constants.IDISK_SIZE: d.size,
                                                constants.IDISK_MODE: d.mode}
                                                for d in self.instance.disks],
                                        hypervisor=self.instance.hypervisor,
                                        node_whitelist=None)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    assert req.RequiredNodes() == len(self.instance.all_nodes)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using iallocator '%s':"
                                 " %s" % (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)

    self.op.nodes = ial.result
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(ial.result))

  def CheckArguments(self):
    if self.op.disks and ht.TNonNegativeInt(self.op.disks[0]):
      # Normalize and convert deprecated list of disk indices
      self.op.disks = [(idx, {}) for idx in sorted(frozenset(self.op.disks))]

    duplicates = utils.FindDuplicates(map(compat.fst, self.op.disks))
    if duplicates:
      raise errors.OpPrereqError("Some disks have been specified more than"
                                 " once: %s" % utils.CommaJoin(duplicates),
                                 errors.ECODE_INVAL)

    # We don't want _CheckIAllocatorOrNode selecting the default iallocator
    # when neither iallocator nor nodes are specified
    if self.op.iallocator or self.op.nodes:
      _CheckIAllocatorOrNode(self, "iallocator", "nodes")

    for (idx, params) in self.op.disks:
      utils.ForceDictType(params, constants.IDISK_PARAMS_TYPES)
      unsupported = frozenset(params.keys()) - self._MODIFYABLE
      if unsupported:
        raise errors.OpPrereqError("Parameters for disk %s try to change"
                                   " unmodifyable parameter(s): %s" %
                                   (idx, utils.CommaJoin(unsupported)),
                                   errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

    if self.op.nodes:
      self.op.nodes = [_ExpandNodeName(self.cfg, n) for n in self.op.nodes]
      self.needed_locks[locking.LEVEL_NODE] = list(self.op.nodes)
    else:
      self.needed_locks[locking.LEVEL_NODE] = []
      if self.op.iallocator:
        # iallocator will select a new node in the same group
        self.needed_locks[locking.LEVEL_NODEGROUP] = []
        self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

    self.needed_locks[locking.LEVEL_NODE_RES] = []

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert self.op.iallocator is not None
      assert not self.op.nodes
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]
      self.share_locks[locking.LEVEL_NODEGROUP] = 1
      # Lock the primary group used by the instance optimistically; this
      # requires going via the node before it's locked, requiring
      # verification later on
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetInstanceNodeGroups(self.op.instance_name, primary_only=True)

    elif level == locking.LEVEL_NODE:
      # If an allocator is used, then we lock all the nodes in the current
      # instance group, as we don't know yet which ones will be selected;
      # if we replace the nodes without using an allocator, locks are
      # already declared in ExpandNames; otherwise, we need to lock all the
      # instance nodes for disk re-creation
      if self.op.iallocator:
        assert not self.op.nodes
        assert not self.needed_locks[locking.LEVEL_NODE]
        assert len(self.owned_locks(locking.LEVEL_NODEGROUP)) == 1

        # Lock member nodes of the group of the primary node
        for group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP):
          self.needed_locks[locking.LEVEL_NODE].extend(
            self.cfg.GetNodeGroup(group_uuid).members)

        assert locking.NAL in self.owned_locks(locking.LEVEL_NODE_ALLOC)
      elif not self.op.nodes:
        self._LockInstancesNodes(primary_only=False)
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    return _BuildInstanceHookEnvByObject(self, self.instance)

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    if self.op.nodes:
      if len(self.op.nodes) != len(instance.all_nodes):
        raise errors.OpPrereqError("Instance %s currently has %d nodes, but"
                                   " %d replacement nodes were specified" %
                                   (instance.name, len(instance.all_nodes),
                                    len(self.op.nodes)),
                                   errors.ECODE_INVAL)
      assert instance.disk_template != constants.DT_DRBD8 or \
          len(self.op.nodes) == 2
      assert instance.disk_template != constants.DT_PLAIN or \
          len(self.op.nodes) == 1
      primary_node = self.op.nodes[0]
    else:
      primary_node = instance.primary_node
    if not self.op.iallocator:
      _CheckNodeOnline(self, primary_node)

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name, errors.ECODE_INVAL)

    # Verify if node group locks are still correct
    owned_groups = self.owned_locks(locking.LEVEL_NODEGROUP)
    if owned_groups:
      # Node group locks are acquired only for the primary node (and only
      # when the allocator is used)
      _CheckInstanceNodeGroups(self.cfg, self.op.instance_name, owned_groups,
                               primary_only=True)

    # if we replace nodes *and* the old primary is offline, we don't
    # check the instance state
    old_pnode = self.cfg.GetNodeInfo(instance.primary_node)
    if not ((self.op.iallocator or self.op.nodes) and old_pnode.offline):
      _CheckInstanceState(self, instance, INSTANCE_NOT_RUNNING,
                          msg="cannot recreate disks")

    if self.op.disks:
      self.disks = dict(self.op.disks)
    else:
      self.disks = dict((idx, {}) for idx in range(len(instance.disks)))

    maxidx = max(self.disks.keys())
    if maxidx >= len(instance.disks):
      raise errors.OpPrereqError("Invalid disk index '%s'" % maxidx,
                                 errors.ECODE_INVAL)

    if ((self.op.nodes or self.op.iallocator) and
        sorted(self.disks.keys()) != range(len(instance.disks))):
      raise errors.OpPrereqError("Can't recreate disks partially and"
                                 " change the nodes at the same time",
                                 errors.ECODE_INVAL)

    self.instance = instance

    if self.op.iallocator:
      self._RunAllocator()
      # Release unneeded node and node resource locks
      _ReleaseLocks(self, locking.LEVEL_NODE, keep=self.op.nodes)
      _ReleaseLocks(self, locking.LEVEL_NODE_RES, keep=self.op.nodes)
      _ReleaseLocks(self, locking.LEVEL_NODE_ALLOC)

    assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

  def Exec(self, feedback_fn):
    """Recreate the disks.

    """
    instance = self.instance

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    to_skip = []
    mods = [] # keeps track of needed changes

    for idx, disk in enumerate(instance.disks):
      try:
        changes = self.disks[idx]
      except KeyError:
        # Disk should not be recreated
        to_skip.append(idx)
        continue

      # update secondaries for disks, if needed
      if self.op.nodes and disk.dev_type == constants.LD_DRBD8:
        # need to update the nodes and minors
        assert len(self.op.nodes) == 2
        assert len(disk.logical_id) == 6 # otherwise disk internals
                                         # have changed
        (_, _, old_port, _, _, old_secret) = disk.logical_id
        new_minors = self.cfg.AllocateDRBDMinor(self.op.nodes, instance.name)
        new_id = (self.op.nodes[0], self.op.nodes[1], old_port,
                  new_minors[0], new_minors[1], old_secret)
        assert len(disk.logical_id) == len(new_id)
      else:
        new_id = None

      mods.append((idx, new_id, changes))

    # now that we have passed all asserts above, we can apply the mods
    # in a single run (to avoid partial changes)
    for idx, new_id, changes in mods:
      disk = instance.disks[idx]
      if new_id is not None:
        assert disk.dev_type == constants.LD_DRBD8
        disk.logical_id = new_id
      if changes:
        disk.Update(size=changes.get(constants.IDISK_SIZE, None),
                    mode=changes.get(constants.IDISK_MODE, None))

    # change primary node, if needed
    if self.op.nodes:
      instance.primary_node = self.op.nodes[0]
      self.LogWarning("Changing the instance's nodes, you will have to"
                      " remove any disks left on the older nodes manually")

    if self.op.nodes:
      self.cfg.Update(instance, feedback_fn)

    # All touched nodes must be locked
    mylocks = self.owned_locks(locking.LEVEL_NODE)
    assert mylocks.issuperset(frozenset(instance.all_nodes))
    _CreateDisks(self, instance, to_skip=to_skip)


class LUInstanceRename(LogicalUnit):
  """Rename an instance.

  """
  HPATH = "instance-rename"
  HTYPE = constants.HTYPE_INSTANCE

  def CheckArguments(self):
    """Check arguments.

    """
    if self.op.ip_check and not self.op.name_check:
      # TODO: make the ip check more flexible and not depend on the name check
      raise errors.OpPrereqError("IP address check requires a name check",
                                 errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["INSTANCE_NEW_NAME"] = self.op.new_name
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    self.op.instance_name = _ExpandInstanceName(self.cfg,
                                                self.op.instance_name)
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None
    _CheckNodeOnline(self, instance.primary_node)
    _CheckInstanceState(self, instance, INSTANCE_NOT_RUNNING,
                        msg="cannot rename")
    self.instance = instance

    new_name = self.op.new_name
    if self.op.name_check:
      hostname = _CheckHostnameSane(self, new_name)
      new_name = self.op.new_name = hostname.name
      if (self.op.ip_check and
          netutils.TcpPing(hostname.ip, constants.DEFAULT_NODED_PORT)):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (hostname.ip, new_name),
                                   errors.ECODE_NOTUNIQUE)

    instance_list = self.cfg.GetInstanceList()
    if new_name in instance_list and new_name != instance.name:
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 new_name, errors.ECODE_EXISTS)

  def Exec(self, feedback_fn):
    """Rename the instance.

    """
    inst = self.instance
    old_name = inst.name

    rename_file_storage = False
    if (inst.disk_template in constants.DTS_FILEBASED and
        self.op.new_name != inst.name):
      old_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])
      rename_file_storage = True

    self.cfg.RenameInstance(inst.name, self.op.new_name)
    # Change the instance lock. This is definitely safe while we hold the BGL.
    # Otherwise the new lock would have to be added in acquired mode.
    assert self.REQ_BGL
    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER)
    self.glm.remove(locking.LEVEL_INSTANCE, old_name)
    self.glm.add(locking.LEVEL_INSTANCE, self.op.new_name)

    # re-read the instance from the configuration after rename
    inst = self.cfg.GetInstanceInfo(self.op.new_name)

    if rename_file_storage:
      new_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])
      result = self.rpc.call_file_storage_dir_rename(inst.primary_node,
                                                     old_file_storage_dir,
                                                     new_file_storage_dir)
      result.Raise("Could not rename on node %s directory '%s' to '%s'"
                   " (but the instance has been renamed in Ganeti)" %
                   (inst.primary_node, old_file_storage_dir,
                    new_file_storage_dir))

    _StartInstanceDisks(self, inst, None)
    # update info on disks
    info = _GetInstanceInfoText(inst)
    for (idx, disk) in enumerate(inst.disks):
      for node in inst.all_nodes:
        self.cfg.SetDiskID(disk, node)
        result = self.rpc.call_blockdev_setinfo(node, disk, info)
        if result.fail_msg:
          self.LogWarning("Error setting info on node %s for disk %s: %s",
                          node, idx, result.fail_msg)
    try:
      result = self.rpc.call_instance_run_rename(inst.primary_node, inst,
                                                 old_name, self.op.debug_level)
      msg = result.fail_msg
      if msg:
        msg = ("Could not run OS rename script for instance %s on node %s"
               " (but the instance has been renamed in Ganeti): %s" %
               (inst.name, inst.primary_node, msg))
        self.LogWarning(msg)
    finally:
      _ShutdownInstanceDisks(self, inst)

    return inst.name


class LUInstanceRemove(LogicalUnit):
  """Remove an instance.

  """
  HPATH = "instance-remove"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["SHUTDOWN_TIMEOUT"] = self.op.shutdown_timeout
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()]
    nl_post = list(self.instance.all_nodes) + nl
    return (nl, nl_post)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

  def Exec(self, feedback_fn):
    """Remove the instance.

    """
    instance = self.instance
    logging.info("Shutting down instance %s on node %s",
                 instance.name, instance.primary_node)

    result = self.rpc.call_instance_shutdown(instance.primary_node, instance,
                                             self.op.shutdown_timeout)
    msg = result.fail_msg
    if msg:
      if self.op.ignore_failures:
        feedback_fn("Warning: can't shutdown instance: %s" % msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, instance.primary_node, msg))

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))
    assert not (set(instance.all_nodes) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Not owning correct locks"

    _RemoveInstance(self, feedback_fn, instance, self.op.ignore_failures)


def _RemoveInstance(lu, feedback_fn, instance, ignore_failures):
  """Utility function to remove an instance.

  """
  logging.info("Removing block devices for instance %s", instance.name)

  if not _RemoveDisks(lu, instance, ignore_failures=ignore_failures):
    if not ignore_failures:
      raise errors.OpExecError("Can't remove instance's disks")
    feedback_fn("Warning: can't remove instance's disks")

  logging.info("Removing instance %s out of cluster config", instance.name)

  lu.cfg.RemoveInstance(instance.name)

  assert not lu.remove_locks.get(locking.LEVEL_INSTANCE), \
    "Instance lock removal conflict"

  # Remove lock for the instance
  lu.remove_locks[locking.LEVEL_INSTANCE] = instance.name


class LUInstanceQuery(NoHooksLU):
  """Logical unit for querying instances.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.iq = _InstanceQuery(qlang.MakeSimpleFilter("name", self.op.names),
                             self.op.output_fields, self.op.use_locking)

  def ExpandNames(self):
    self.iq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.iq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.iq.OldStyleQuery(self)


def _ExpandNamesForMigration(lu):
  """Expands names for use with L{TLMigrateInstance}.

  @type lu: L{LogicalUnit}

  """
  if lu.op.target_node is not None:
    lu.op.target_node = _ExpandNodeName(lu.cfg, lu.op.target_node)

  lu.needed_locks[locking.LEVEL_NODE] = []
  lu.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  lu.needed_locks[locking.LEVEL_NODE_RES] = []
  lu.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  # The node allocation lock is actually only needed for externally replicated
  # instances (e.g. sharedfile or RBD) and if an iallocator is used.
  lu.needed_locks[locking.LEVEL_NODE_ALLOC] = []


def _DeclareLocksForMigration(lu, level):
  """Declares locks for L{TLMigrateInstance}.

  @type lu: L{LogicalUnit}
  @param level: Lock level

  """
  if level == locking.LEVEL_NODE_ALLOC:
    assert lu.op.instance_name in lu.owned_locks(locking.LEVEL_INSTANCE)

    instance = lu.cfg.GetInstanceInfo(lu.op.instance_name)

    # Node locks are already declared here rather than at LEVEL_NODE as we need
    # the instance object anyway to declare the node allocation lock.
    if instance.disk_template in constants.DTS_EXT_MIRROR:
      if lu.op.target_node is None:
        lu.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        lu.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET
      else:
        lu.needed_locks[locking.LEVEL_NODE] = [instance.primary_node,
                                               lu.op.target_node]
      del lu.recalculate_locks[locking.LEVEL_NODE]
    else:
      lu._LockInstancesNodes() # pylint: disable=W0212

  elif level == locking.LEVEL_NODE:
    # Node locks are declared together with the node allocation lock
    assert (lu.needed_locks[locking.LEVEL_NODE] or
            lu.needed_locks[locking.LEVEL_NODE] is locking.ALL_SET)

  elif level == locking.LEVEL_NODE_RES:
    # Copy node locks
    lu.needed_locks[locking.LEVEL_NODE_RES] = \
      _CopyLockList(lu.needed_locks[locking.LEVEL_NODE])


class LUInstanceFailover(LogicalUnit):
  """Failover an instance.

  """
  HPATH = "instance-failover"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check the arguments.

    """
    self.iallocator = getattr(self.op, "iallocator", None)
    self.target_node = getattr(self.op, "target_node", None)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    _ExpandNamesForMigration(self)

    self._migrater = \
      TLMigrateInstance(self, self.op.instance_name, False, True, False,
                        self.op.ignore_consistency, True,
                        self.op.shutdown_timeout, self.op.ignore_ipolicy)

    self.tasklets = [self._migrater]

  def DeclareLocks(self, level):
    _DeclareLocksForMigration(self, level)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    instance = self._migrater.instance
    source_node = instance.primary_node
    target_node = self.op.target_node
    env = {
      "IGNORE_CONSISTENCY": self.op.ignore_consistency,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      "OLD_PRIMARY": source_node,
      "NEW_PRIMARY": target_node,
      }

    if instance.disk_template in constants.DTS_INT_MIRROR:
      env["OLD_SECONDARY"] = instance.secondary_nodes[0]
      env["NEW_SECONDARY"] = source_node
    else:
      env["OLD_SECONDARY"] = env["NEW_SECONDARY"] = ""

    env.update(_BuildInstanceHookEnvByObject(self, instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self._migrater.instance
    nl = [self.cfg.GetMasterNode()] + list(instance.secondary_nodes)
    return (nl, nl + [instance.primary_node])


class LUInstanceMigrate(LogicalUnit):
  """Migrate an instance.

  This is migration without shutting down, compared to the failover,
  which is done with shutdown.

  """
  HPATH = "instance-migrate"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    _ExpandNamesForMigration(self)

    self._migrater = \
      TLMigrateInstance(self, self.op.instance_name, self.op.cleanup,
                        False, self.op.allow_failover, False,
                        self.op.allow_runtime_changes,
                        constants.DEFAULT_SHUTDOWN_TIMEOUT,
                        self.op.ignore_ipolicy)

    self.tasklets = [self._migrater]

  def DeclareLocks(self, level):
    _DeclareLocksForMigration(self, level)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    instance = self._migrater.instance
    source_node = instance.primary_node
    target_node = self.op.target_node
    env = _BuildInstanceHookEnvByObject(self, instance)
    env.update({
      "MIGRATE_LIVE": self._migrater.live,
      "MIGRATE_CLEANUP": self.op.cleanup,
      "OLD_PRIMARY": source_node,
      "NEW_PRIMARY": target_node,
      "ALLOW_RUNTIME_CHANGES": self.op.allow_runtime_changes,
      })

    if instance.disk_template in constants.DTS_INT_MIRROR:
      env["OLD_SECONDARY"] = target_node
      env["NEW_SECONDARY"] = source_node
    else:
      env["OLD_SECONDARY"] = env["NEW_SECONDARY"] = None

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self._migrater.instance
    snodes = list(instance.secondary_nodes)
    nl = [self.cfg.GetMasterNode(), instance.primary_node] + snodes
    return (nl, nl)


class LUInstanceMove(LogicalUnit):
  """Move an instance by data-copying.

  """
  HPATH = "instance-move"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    target_node = _ExpandNodeName(self.cfg, self.op.target_node)
    self.op.target_node = target_node
    self.needed_locks[locking.LEVEL_NODE] = [target_node]
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes(primary_only=True)
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "TARGET_NODE": self.op.target_node,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [
      self.cfg.GetMasterNode(),
      self.instance.primary_node,
      self.op.target_node,
      ]
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if instance.disk_template not in constants.DTS_COPYABLE:
      raise errors.OpPrereqError("Disk template %s not suitable for copying" %
                                 instance.disk_template, errors.ECODE_STATE)

    node = self.cfg.GetNodeInfo(self.op.target_node)
    assert node is not None, \
      "Cannot retrieve locked node %s" % self.op.target_node

    self.target_node = target_node = node.name

    if target_node == instance.primary_node:
      raise errors.OpPrereqError("Instance %s is already on the node %s" %
                                 (instance.name, target_node),
                                 errors.ECODE_STATE)

    bep = self.cfg.GetClusterInfo().FillBE(instance)

    for idx, dsk in enumerate(instance.disks):
      if dsk.dev_type not in (constants.LD_LV, constants.LD_FILE):
        raise errors.OpPrereqError("Instance disk %d has a complex layout,"
                                   " cannot copy" % idx, errors.ECODE_STATE)

    _CheckNodeOnline(self, target_node)
    _CheckNodeNotDrained(self, target_node)
    _CheckNodeVmCapable(self, target_node)
    cluster = self.cfg.GetClusterInfo()
    group_info = self.cfg.GetNodeGroup(node.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    _CheckTargetNodeIPolicy(self, ipolicy, instance, node, self.cfg,
                            ignore=self.op.ignore_ipolicy)

    if instance.admin_state == constants.ADMINST_UP:
      # check memory requirements on the secondary node
      _CheckNodeFreeMemory(self, target_node, "failing over instance %s" %
                           instance.name, bep[constants.BE_MAXMEM],
                           instance.hypervisor)
    else:
      self.LogInfo("Not checking memory on the secondary node as"
                   " instance will not be started")

    # check bridge existance
    _CheckInstanceBridgesExist(self, instance, node=target_node)

  def Exec(self, feedback_fn):
    """Move an instance.

    The move is done by shutting it down on its present node, copying
    the data over (slow) and starting it on the new node.

    """
    instance = self.instance

    source_node = instance.primary_node
    target_node = self.target_node

    self.LogInfo("Shutting down instance %s on source node %s",
                 instance.name, source_node)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    result = self.rpc.call_instance_shutdown(source_node, instance,
                                             self.op.shutdown_timeout)
    msg = result.fail_msg
    if msg:
      if self.op.ignore_consistency:
        self.LogWarning("Could not shutdown instance %s on node %s."
                        " Proceeding anyway. Please make sure node"
                        " %s is down. Error details: %s",
                        instance.name, source_node, source_node, msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, source_node, msg))

    # create the target disks
    try:
      _CreateDisks(self, instance, target_node=target_node)
    except errors.OpExecError:
      self.LogWarning("Device creation failed")
      self.cfg.ReleaseDRBDMinors(instance.name)
      raise

    cluster_name = self.cfg.GetClusterInfo().cluster_name

    errs = []
    # activate, get path, copy the data over
    for idx, disk in enumerate(instance.disks):
      self.LogInfo("Copying data for disk %d", idx)
      result = self.rpc.call_blockdev_assemble(target_node, (disk, instance),
                                               instance.name, True, idx)
      if result.fail_msg:
        self.LogWarning("Can't assemble newly created disk %d: %s",
                        idx, result.fail_msg)
        errs.append(result.fail_msg)
        break
      dev_path = result.payload
      result = self.rpc.call_blockdev_export(source_node, (disk, instance),
                                             target_node, dev_path,
                                             cluster_name)
      if result.fail_msg:
        self.LogWarning("Can't copy data over for disk %d: %s",
                        idx, result.fail_msg)
        errs.append(result.fail_msg)
        break

    if errs:
      self.LogWarning("Some disks failed to copy, aborting")
      try:
        _RemoveDisks(self, instance, target_node=target_node)
      finally:
        self.cfg.ReleaseDRBDMinors(instance.name)
        raise errors.OpExecError("Errors during disk copy: %s" %
                                 (",".join(errs),))

    instance.primary_node = target_node
    self.cfg.Update(instance, feedback_fn)

    self.LogInfo("Removing the disks on the original node")
    _RemoveDisks(self, instance, target_node=source_node)

    # Only start the instance if it's marked as up
    if instance.admin_state == constants.ADMINST_UP:
      self.LogInfo("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, _ = _AssembleInstanceDisks(self, instance,
                                           ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      result = self.rpc.call_instance_start(target_node,
                                            (instance, None, None), False)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (instance.name, target_node, msg))


class LUNodeMigrate(LogicalUnit):
  """Migrate all instances from a node.

  """
  HPATH = "node-migrate"
  HTYPE = constants.HTYPE_NODE
  REQ_BGL = False

  def CheckArguments(self):
    pass

  def ExpandNames(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)

    self.share_locks = _ShareAll()
    self.needed_locks = {
      locking.LEVEL_NODE: [self.op.node_name],
      }

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    return {
      "NODE_NAME": self.op.node_name,
      "ALLOW_RUNTIME_CHANGES": self.op.allow_runtime_changes,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()]
    return (nl, nl)

  def CheckPrereq(self):
    pass

  def Exec(self, feedback_fn):
    # Prepare jobs for migration instances
    allow_runtime_changes = self.op.allow_runtime_changes
    jobs = [
      [opcodes.OpInstanceMigrate(instance_name=inst.name,
                                 mode=self.op.mode,
                                 live=self.op.live,
                                 iallocator=self.op.iallocator,
                                 target_node=self.op.target_node,
                                 allow_runtime_changes=allow_runtime_changes,
                                 ignore_ipolicy=self.op.ignore_ipolicy)]
      for inst in _GetNodePrimaryInstances(self.cfg, self.op.node_name)]

    # TODO: Run iallocator in this opcode and pass correct placement options to
    # OpInstanceMigrate. Since other jobs can modify the cluster between
    # running the iallocator and the actual migration, a good consistency model
    # will have to be found.

    assert (frozenset(self.owned_locks(locking.LEVEL_NODE)) ==
            frozenset([self.op.node_name]))

    return ResultWithJobs(jobs)


class TLMigrateInstance(Tasklet):
  """Tasklet class for instance migration.

  @type live: boolean
  @ivar live: whether the migration will be done live or non-live;
      this variable is initalized only after CheckPrereq has run
  @type cleanup: boolean
  @ivar cleanup: Wheater we cleanup from a failed migration
  @type iallocator: string
  @ivar iallocator: The iallocator used to determine target_node
  @type target_node: string
  @ivar target_node: If given, the target_node to reallocate the instance to
  @type failover: boolean
  @ivar failover: Whether operation results in failover or migration
  @type fallback: boolean
  @ivar fallback: Whether fallback to failover is allowed if migration not
                  possible
  @type ignore_consistency: boolean
  @ivar ignore_consistency: Wheter we should ignore consistency between source
                            and target node
  @type shutdown_timeout: int
  @ivar shutdown_timeout: In case of failover timeout of the shutdown
  @type ignore_ipolicy: bool
  @ivar ignore_ipolicy: If true, we can ignore instance policy when migrating

  """

  # Constants
  _MIGRATION_POLL_INTERVAL = 1      # seconds
  _MIGRATION_FEEDBACK_INTERVAL = 10 # seconds

  def __init__(self, lu, instance_name, cleanup, failover, fallback,
               ignore_consistency, allow_runtime_changes, shutdown_timeout,
               ignore_ipolicy):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_name = instance_name
    self.cleanup = cleanup
    self.live = False # will be overridden later
    self.failover = failover
    self.fallback = fallback
    self.ignore_consistency = ignore_consistency
    self.shutdown_timeout = shutdown_timeout
    self.ignore_ipolicy = ignore_ipolicy
    self.allow_runtime_changes = allow_runtime_changes

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    instance_name = _ExpandInstanceName(self.lu.cfg, self.instance_name)
    instance = self.cfg.GetInstanceInfo(instance_name)
    assert instance is not None
    self.instance = instance
    cluster = self.cfg.GetClusterInfo()

    if (not self.cleanup and
        not instance.admin_state == constants.ADMINST_UP and
        not self.failover and self.fallback):
      self.lu.LogInfo("Instance is marked down or offline, fallback allowed,"
                      " switching to failover")
      self.failover = True

    if instance.disk_template not in constants.DTS_MIRRORED:
      if self.failover:
        text = "failovers"
      else:
        text = "migrations"
      raise errors.OpPrereqError("Instance's disk layout '%s' does not allow"
                                 " %s" % (instance.disk_template, text),
                                 errors.ECODE_STATE)

    if instance.disk_template in constants.DTS_EXT_MIRROR:
      _CheckIAllocatorOrNode(self.lu, "iallocator", "target_node")

      if self.lu.op.iallocator:
        assert locking.NAL in self.lu.owned_locks(locking.LEVEL_NODE_ALLOC)
        self._RunAllocator()
      else:
        # We set set self.target_node as it is required by
        # BuildHooksEnv
        self.target_node = self.lu.op.target_node

      # Check that the target node is correct in terms of instance policy
      nodeinfo = self.cfg.GetNodeInfo(self.target_node)
      group_info = self.cfg.GetNodeGroup(nodeinfo.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)
      _CheckTargetNodeIPolicy(self.lu, ipolicy, instance, nodeinfo, self.cfg,
                              ignore=self.ignore_ipolicy)

      # self.target_node is already populated, either directly or by the
      # iallocator run
      target_node = self.target_node
      if self.target_node == instance.primary_node:
        raise errors.OpPrereqError("Cannot migrate instance %s"
                                   " to its primary (%s)" %
                                   (instance.name, instance.primary_node),
                                   errors.ECODE_STATE)

      if len(self.lu.tasklets) == 1:
        # It is safe to release locks only when we're the only tasklet
        # in the LU
        _ReleaseLocks(self.lu, locking.LEVEL_NODE,
                      keep=[instance.primary_node, self.target_node])
        _ReleaseLocks(self.lu, locking.LEVEL_NODE_ALLOC)

    else:
      assert not self.lu.glm.is_owned(locking.LEVEL_NODE_ALLOC)

      secondary_nodes = instance.secondary_nodes
      if not secondary_nodes:
        raise errors.ConfigurationError("No secondary node but using"
                                        " %s disk template" %
                                        instance.disk_template)
      target_node = secondary_nodes[0]
      if self.lu.op.iallocator or (self.lu.op.target_node and
                                   self.lu.op.target_node != target_node):
        if self.failover:
          text = "failed over"
        else:
          text = "migrated"
        raise errors.OpPrereqError("Instances with disk template %s cannot"
                                   " be %s to arbitrary nodes"
                                   " (neither an iallocator nor a target"
                                   " node can be passed)" %
                                   (instance.disk_template, text),
                                   errors.ECODE_INVAL)
      nodeinfo = self.cfg.GetNodeInfo(target_node)
      group_info = self.cfg.GetNodeGroup(nodeinfo.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)
      _CheckTargetNodeIPolicy(self.lu, ipolicy, instance, nodeinfo, self.cfg,
                              ignore=self.ignore_ipolicy)

    i_be = cluster.FillBE(instance)

    # check memory requirements on the secondary node
    if (not self.cleanup and
         (not self.failover or instance.admin_state == constants.ADMINST_UP)):
      self.tgt_free_mem = _CheckNodeFreeMemory(self.lu, target_node,
                                               "migrating instance %s" %
                                               instance.name,
                                               i_be[constants.BE_MINMEM],
                                               instance.hypervisor)
    else:
      self.lu.LogInfo("Not checking memory on the secondary node as"
                      " instance will not be started")

    # check if failover must be forced instead of migration
    if (not self.cleanup and not self.failover and
        i_be[constants.BE_ALWAYS_FAILOVER]):
      self.lu.LogInfo("Instance configured to always failover; fallback"
                      " to failover")
      self.failover = True

    # check bridge existance
    _CheckInstanceBridgesExist(self.lu, instance, node=target_node)

    if not self.cleanup:
      _CheckNodeNotDrained(self.lu, target_node)
      if not self.failover:
        result = self.rpc.call_instance_migratable(instance.primary_node,
                                                   instance)
        if result.fail_msg and self.fallback:
          self.lu.LogInfo("Can't migrate, instance offline, fallback to"
                          " failover")
          self.failover = True
        else:
          result.Raise("Can't migrate, please use failover",
                       prereq=True, ecode=errors.ECODE_STATE)

    assert not (self.failover and self.cleanup)

    if not self.failover:
      if self.lu.op.live is not None and self.lu.op.mode is not None:
        raise errors.OpPrereqError("Only one of the 'live' and 'mode'"
                                   " parameters are accepted",
                                   errors.ECODE_INVAL)
      if self.lu.op.live is not None:
        if self.lu.op.live:
          self.lu.op.mode = constants.HT_MIGRATION_LIVE
        else:
          self.lu.op.mode = constants.HT_MIGRATION_NONLIVE
        # reset the 'live' parameter to None so that repeated
        # invocations of CheckPrereq do not raise an exception
        self.lu.op.live = None
      elif self.lu.op.mode is None:
        # read the default value from the hypervisor
        i_hv = cluster.FillHV(self.instance, skip_globals=False)
        self.lu.op.mode = i_hv[constants.HV_MIGRATION_MODE]

      self.live = self.lu.op.mode == constants.HT_MIGRATION_LIVE
    else:
      # Failover is never live
      self.live = False

    if not (self.failover or self.cleanup):
      remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                instance.name,
                                                instance.hypervisor)
      remote_info.Raise("Error checking instance on node %s" %
                        instance.primary_node)
      instance_running = bool(remote_info.payload)
      if instance_running:
        self.current_mem = int(remote_info.payload["memory"])

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    assert locking.NAL in self.lu.owned_locks(locking.LEVEL_NODE_ALLOC)

    # FIXME: add a self.ignore_ipolicy option
    req = iallocator.IAReqRelocate(name=self.instance_name,
                                   relocate_from=[self.instance.primary_node])
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.lu.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.lu.op.iallocator, ial.info),
                                 errors.ECODE_NORES)
    self.target_node = ial.result[0]
    self.lu.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                    self.instance_name, self.lu.op.iallocator,
                    utils.CommaJoin(ial.result))

  def _WaitUntilSync(self):
    """Poll with custom rpc for disk sync.

    This uses our own step-based rpc call.

    """
    self.feedback_fn("* wait until resync is done")
    all_done = False
    while not all_done:
      all_done = True
      result = self.rpc.call_drbd_wait_sync(self.all_nodes,
                                            self.nodes_ip,
                                            (self.instance.disks,
                                             self.instance))
      min_percent = 100
      for node, nres in result.items():
        nres.Raise("Cannot resync disks on node %s" % node)
        node_done, node_percent = nres.payload
        all_done = all_done and node_done
        if node_percent is not None:
          min_percent = min(min_percent, node_percent)
      if not all_done:
        if min_percent < 100:
          self.feedback_fn("   - progress: %.1f%%" % min_percent)
        time.sleep(2)

  def _EnsureSecondary(self, node):
    """Demote a node to secondary.

    """
    self.feedback_fn("* switching node %s to secondary mode" % node)

    for dev in self.instance.disks:
      self.cfg.SetDiskID(dev, node)

    result = self.rpc.call_blockdev_close(node, self.instance.name,
                                          self.instance.disks)
    result.Raise("Cannot change disk to secondary on node %s" % node)

  def _GoStandalone(self):
    """Disconnect from the network.

    """
    self.feedback_fn("* changing into standalone mode")
    result = self.rpc.call_drbd_disconnect_net(self.all_nodes, self.nodes_ip,
                                               self.instance.disks)
    for node, nres in result.items():
      nres.Raise("Cannot disconnect disks node %s" % node)

  def _GoReconnect(self, multimaster):
    """Reconnect to the network.

    """
    if multimaster:
      msg = "dual-master"
    else:
      msg = "single-master"
    self.feedback_fn("* changing disks into %s mode" % msg)
    result = self.rpc.call_drbd_attach_net(self.all_nodes, self.nodes_ip,
                                           (self.instance.disks, self.instance),
                                           self.instance.name, multimaster)
    for node, nres in result.items():
      nres.Raise("Cannot change disks config on node %s" % node)

  def _ExecCleanup(self):
    """Try to cleanup after a failed migration.

    The cleanup is done by:
      - check that the instance is running only on one node
        (and update the config if needed)
      - change disks on its secondary node to secondary
      - wait until disks are fully synchronized
      - disconnect from the network
      - change disks into single-master mode
      - wait again until disks are fully synchronized

    """
    instance = self.instance
    target_node = self.target_node
    source_node = self.source_node

    # check running on only one node
    self.feedback_fn("* checking where the instance actually runs"
                     " (if this hangs, the hypervisor might be in"
                     " a bad state)")
    ins_l = self.rpc.call_instance_list(self.all_nodes, [instance.hypervisor])
    for node, result in ins_l.items():
      result.Raise("Can't contact node %s" % node)

    runningon_source = instance.name in ins_l[source_node].payload
    runningon_target = instance.name in ins_l[target_node].payload

    if runningon_source and runningon_target:
      raise errors.OpExecError("Instance seems to be running on two nodes,"
                               " or the hypervisor is confused; you will have"
                               " to ensure manually that it runs only on one"
                               " and restart this operation")

    if not (runningon_source or runningon_target):
      raise errors.OpExecError("Instance does not seem to be running at all;"
                               " in this case it's safer to repair by"
                               " running 'gnt-instance stop' to ensure disk"
                               " shutdown, and then restarting it")

    if runningon_target:
      # the migration has actually succeeded, we need to update the config
      self.feedback_fn("* instance running on secondary node (%s),"
                       " updating config" % target_node)
      instance.primary_node = target_node
      self.cfg.Update(instance, self.feedback_fn)
      demoted_node = source_node
    else:
      self.feedback_fn("* instance confirmed to be running on its"
                       " primary node (%s)" % source_node)
      demoted_node = target_node

    if instance.disk_template in constants.DTS_INT_MIRROR:
      self._EnsureSecondary(demoted_node)
      try:
        self._WaitUntilSync()
      except errors.OpExecError:
        # we ignore here errors, since if the device is standalone, it
        # won't be able to sync
        pass
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()

    self.feedback_fn("* done")

  def _RevertDiskStatus(self):
    """Try to revert the disk status after a failed migration.

    """
    target_node = self.target_node
    if self.instance.disk_template in constants.DTS_EXT_MIRROR:
      return

    try:
      self._EnsureSecondary(target_node)
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()
    except errors.OpExecError, err:
      self.lu.LogWarning("Migration failed and I can't reconnect the drives,"
                         " please try to recover the instance manually;"
                         " error '%s'" % str(err))

  def _AbortMigration(self):
    """Call the hypervisor code to abort a started migration.

    """
    instance = self.instance
    target_node = self.target_node
    source_node = self.source_node
    migration_info = self.migration_info

    abort_result = self.rpc.call_instance_finalize_migration_dst(target_node,
                                                                 instance,
                                                                 migration_info,
                                                                 False)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on target node %s: %s",
                    target_node, abort_msg)
      # Don't raise an exception here, as we stil have to try to revert the
      # disk status, even if this step failed.

    abort_result = self.rpc.call_instance_finalize_migration_src(
      source_node, instance, False, self.live)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on source node %s: %s",
                    source_node, abort_msg)

  def _ExecMigration(self):
    """Migrate an instance.

    The migrate is done by:
      - change the disks into dual-master mode
      - wait until disks are fully synchronized again
      - migrate the instance
      - change disks on the new secondary node (the old primary) to secondary
      - wait until disks are fully synchronized
      - change disks into single-master mode

    """
    instance = self.instance
    target_node = self.target_node
    source_node = self.source_node

    # Check for hypervisor version mismatch and warn the user.
    nodeinfo = self.rpc.call_node_info([source_node, target_node],
                                       None, [self.instance.hypervisor], False)
    for ninfo in nodeinfo.values():
      ninfo.Raise("Unable to retrieve node information from node '%s'" %
                  ninfo.node)
    (_, _, (src_info, )) = nodeinfo[source_node].payload
    (_, _, (dst_info, )) = nodeinfo[target_node].payload

    if ((constants.HV_NODEINFO_KEY_VERSION in src_info) and
        (constants.HV_NODEINFO_KEY_VERSION in dst_info)):
      src_version = src_info[constants.HV_NODEINFO_KEY_VERSION]
      dst_version = dst_info[constants.HV_NODEINFO_KEY_VERSION]
      if src_version != dst_version:
        self.feedback_fn("* warning: hypervisor version mismatch between"
                         " source (%s) and target (%s) node" %
                         (src_version, dst_version))

    self.feedback_fn("* checking disk consistency between source and target")
    for (idx, dev) in enumerate(instance.disks):
      if not _CheckDiskConsistency(self.lu, instance, dev, target_node, False):
        raise errors.OpExecError("Disk %s is degraded or not fully"
                                 " synchronized on target node,"
                                 " aborting migration" % idx)

    if self.current_mem > self.tgt_free_mem:
      if not self.allow_runtime_changes:
        raise errors.OpExecError("Memory ballooning not allowed and not enough"
                                 " free memory to fit instance %s on target"
                                 " node %s (have %dMB, need %dMB)" %
                                 (instance.name, target_node,
                                  self.tgt_free_mem, self.current_mem))
      self.feedback_fn("* setting instance memory to %s" % self.tgt_free_mem)
      rpcres = self.rpc.call_instance_balloon_memory(instance.primary_node,
                                                     instance,
                                                     self.tgt_free_mem)
      rpcres.Raise("Cannot modify instance runtime memory")

    # First get the migration information from the remote node
    result = self.rpc.call_migration_info(source_node, instance)
    msg = result.fail_msg
    if msg:
      log_err = ("Failed fetching source migration information from %s: %s" %
                 (source_node, msg))
      logging.error(log_err)
      raise errors.OpExecError(log_err)

    self.migration_info = migration_info = result.payload

    if self.instance.disk_template not in constants.DTS_EXT_MIRROR:
      # Then switch the disks to master/master mode
      self._EnsureSecondary(target_node)
      self._GoStandalone()
      self._GoReconnect(True)
      self._WaitUntilSync()

    self.feedback_fn("* preparing %s to accept the instance" % target_node)
    result = self.rpc.call_accept_instance(target_node,
                                           instance,
                                           migration_info,
                                           self.nodes_ip[target_node])

    msg = result.fail_msg
    if msg:
      logging.error("Instance pre-migration failed, trying to revert"
                    " disk status: %s", msg)
      self.feedback_fn("Pre-migration failed, aborting")
      self._AbortMigration()
      self._RevertDiskStatus()
      raise errors.OpExecError("Could not pre-migrate instance %s: %s" %
                               (instance.name, msg))

    self.feedback_fn("* migrating instance to %s" % target_node)
    result = self.rpc.call_instance_migrate(source_node, instance,
                                            self.nodes_ip[target_node],
                                            self.live)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration failed, trying to revert"
                    " disk status: %s", msg)
      self.feedback_fn("Migration failed, aborting")
      self._AbortMigration()
      self._RevertDiskStatus()
      raise errors.OpExecError("Could not migrate instance %s: %s" %
                               (instance.name, msg))

    self.feedback_fn("* starting memory transfer")
    last_feedback = time.time()
    while True:
      result = self.rpc.call_instance_get_migration_status(source_node,
                                                           instance)
      msg = result.fail_msg
      ms = result.payload   # MigrationStatus instance
      if msg or (ms.status in constants.HV_MIGRATION_FAILED_STATUSES):
        logging.error("Instance migration failed, trying to revert"
                      " disk status: %s", msg)
        self.feedback_fn("Migration failed, aborting")
        self._AbortMigration()
        self._RevertDiskStatus()
        if not msg:
          msg = "hypervisor returned failure"
        raise errors.OpExecError("Could not migrate instance %s: %s" %
                                 (instance.name, msg))

      if result.payload.status != constants.HV_MIGRATION_ACTIVE:
        self.feedback_fn("* memory transfer complete")
        break

      if (utils.TimeoutExpired(last_feedback,
                               self._MIGRATION_FEEDBACK_INTERVAL) and
          ms.transferred_ram is not None):
        mem_progress = 100 * float(ms.transferred_ram) / float(ms.total_ram)
        self.feedback_fn("* memory transfer progress: %.2f %%" % mem_progress)
        last_feedback = time.time()

      time.sleep(self._MIGRATION_POLL_INTERVAL)

    result = self.rpc.call_instance_finalize_migration_src(source_node,
                                                           instance,
                                                           True,
                                                           self.live)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed"
                    " on the source node: %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    instance.primary_node = target_node

    # distribute new instance config to the other nodes
    self.cfg.Update(instance, self.feedback_fn)

    result = self.rpc.call_instance_finalize_migration_dst(target_node,
                                                           instance,
                                                           migration_info,
                                                           True)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed"
                    " on the target node: %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    if self.instance.disk_template not in constants.DTS_EXT_MIRROR:
      self._EnsureSecondary(source_node)
      self._WaitUntilSync()
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()

    # If the instance's disk template is `rbd' or `ext' and there was a
    # successful migration, unmap the device from the source node.
    if self.instance.disk_template in (constants.DT_RBD, constants.DT_EXT):
      disks = _ExpandCheckDisks(instance, instance.disks)
      self.feedback_fn("* unmapping instance's disks from %s" % source_node)
      for disk in disks:
        result = self.rpc.call_blockdev_shutdown(source_node, (disk, instance))
        msg = result.fail_msg
        if msg:
          logging.error("Migration was successful, but couldn't unmap the"
                        " block device %s on source node %s: %s",
                        disk.iv_name, source_node, msg)
          logging.error("You need to unmap the device %s manually on %s",
                        disk.iv_name, source_node)

    self.feedback_fn("* done")

  def _ExecFailover(self):
    """Failover an instance.

    The failover is done by shutting it down on its present node and
    starting it on the secondary.

    """
    instance = self.instance
    primary_node = self.cfg.GetNodeInfo(instance.primary_node)

    source_node = instance.primary_node
    target_node = self.target_node

    if instance.admin_state == constants.ADMINST_UP:
      self.feedback_fn("* checking disk consistency between source and target")
      for (idx, dev) in enumerate(instance.disks):
        # for drbd, these are drbd over lvm
        if not _CheckDiskConsistency(self.lu, instance, dev, target_node,
                                     False):
          if primary_node.offline:
            self.feedback_fn("Node %s is offline, ignoring degraded disk %s on"
                             " target node %s" %
                             (primary_node.name, idx, target_node))
          elif not self.ignore_consistency:
            raise errors.OpExecError("Disk %s is degraded on target node,"
                                     " aborting failover" % idx)
    else:
      self.feedback_fn("* not checking disk consistency as instance is not"
                       " running")

    self.feedback_fn("* shutting down instance on source node")
    logging.info("Shutting down instance %s on node %s",
                 instance.name, source_node)

    result = self.rpc.call_instance_shutdown(source_node, instance,
                                             self.shutdown_timeout)
    msg = result.fail_msg
    if msg:
      if self.ignore_consistency or primary_node.offline:
        self.lu.LogWarning("Could not shutdown instance %s on node %s,"
                           " proceeding anyway; please make sure node"
                           " %s is down; error details: %s",
                           instance.name, source_node, source_node, msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, source_node, msg))

    self.feedback_fn("* deactivating the instance's disks on source node")
    if not _ShutdownInstanceDisks(self.lu, instance, ignore_primary=True):
      raise errors.OpExecError("Can't shut down the instance's disks")

    instance.primary_node = target_node
    # distribute new instance config to the other nodes
    self.cfg.Update(instance, self.feedback_fn)

    # Only start the instance if it's marked as up
    if instance.admin_state == constants.ADMINST_UP:
      self.feedback_fn("* activating the instance's disks on target node %s" %
                       target_node)
      logging.info("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, _ = _AssembleInstanceDisks(self.lu, instance,
                                           ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self.lu, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      self.feedback_fn("* starting the instance on the target node %s" %
                       target_node)
      result = self.rpc.call_instance_start(target_node, (instance, None, None),
                                            False)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self.lu, instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (instance.name, target_node, msg))

  def Exec(self, feedback_fn):
    """Perform the migration.

    """
    self.feedback_fn = feedback_fn
    self.source_node = self.instance.primary_node

    # FIXME: if we implement migrate-to-any in DRBD, this needs fixing
    if self.instance.disk_template in constants.DTS_INT_MIRROR:
      self.target_node = self.instance.secondary_nodes[0]
      # Otherwise self.target_node has been populated either
      # directly, or through an iallocator.

    self.all_nodes = [self.source_node, self.target_node]
    self.nodes_ip = dict((name, node.secondary_ip) for (name, node)
                         in self.cfg.GetMultiNodeInfo(self.all_nodes))

    if self.failover:
      feedback_fn("Failover instance %s" % self.instance.name)
      self._ExecFailover()
    else:
      feedback_fn("Migrating instance %s" % self.instance.name)

      if self.cleanup:
        return self._ExecCleanup()
      else:
        return self._ExecMigration()


def _CreateBlockDev(lu, node, instance, device, force_create, info,
                    force_open):
  """Wrapper around L{_CreateBlockDevInner}.

  This method annotates the root device first.

  """
  (disk,) = _AnnotateDiskParams(instance, [device], lu.cfg)
  excl_stor = _IsExclusiveStorageEnabledNodeName(lu.cfg, node)
  return _CreateBlockDevInner(lu, node, instance, disk, force_create, info,
                              force_open, excl_stor)


def _CreateBlockDevInner(lu, node, instance, device, force_create,
                         info, force_open, excl_stor):
  """Create a tree of block devices on a given node.

  If this device type has to be created on secondaries, create it and
  all its children.

  If not, just recurse to children keeping the same 'force' value.

  @attention: The device has to be annotated already.

  @param lu: the lu on whose behalf we execute
  @param node: the node on which to create the device
  @type instance: L{objects.Instance}
  @param instance: the instance which owns the device
  @type device: L{objects.Disk}
  @param device: the device to create
  @type force_create: boolean
  @param force_create: whether to force creation of this device; this
      will be change to True whenever we find a device which has
      CreateOnSecondary() attribute
  @param info: the extra 'metadata' we should attach to the device
      (this will be represented as a LVM tag)
  @type force_open: boolean
  @param force_open: this parameter will be passes to the
      L{backend.BlockdevCreate} function where it specifies
      whether we run on primary or not, and it affects both
      the child assembly and the device own Open() execution
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active for the node

  """
  if device.CreateOnSecondary():
    force_create = True

  if device.children:
    for child in device.children:
      _CreateBlockDevInner(lu, node, instance, child, force_create,
                           info, force_open, excl_stor)

  if not force_create:
    return

  _CreateSingleBlockDev(lu, node, instance, device, info, force_open,
                        excl_stor)


def _CreateSingleBlockDev(lu, node, instance, device, info, force_open,
                          excl_stor):
  """Create a single block device on a given node.

  This will not recurse over children of the device, so they must be
  created in advance.

  @param lu: the lu on whose behalf we execute
  @param node: the node on which to create the device
  @type instance: L{objects.Instance}
  @param instance: the instance which owns the device
  @type device: L{objects.Disk}
  @param device: the device to create
  @param info: the extra 'metadata' we should attach to the device
      (this will be represented as a LVM tag)
  @type force_open: boolean
  @param force_open: this parameter will be passes to the
      L{backend.BlockdevCreate} function where it specifies
      whether we run on primary or not, and it affects both
      the child assembly and the device own Open() execution
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active for the node

  """
  lu.cfg.SetDiskID(device, node)
  result = lu.rpc.call_blockdev_create(node, device, device.size,
                                       instance.name, force_open, info,
                                       excl_stor)
  result.Raise("Can't create block device %s on"
               " node %s for instance %s" % (device, node, instance.name))
  if device.physical_id is None:
    device.physical_id = result.payload


def _GenerateUniqueNames(lu, exts):
  """Generate a suitable LV name.

  This will generate a logical volume name for the given instance.

  """
  results = []
  for val in exts:
    new_id = lu.cfg.GenerateUniqueID(lu.proc.GetECId())
    results.append("%s%s" % (new_id, val))
  return results


def _GenerateDRBD8Branch(lu, primary, secondary, size, vgnames, names,
                         iv_name, p_minor, s_minor):
  """Generate a drbd8 device complete with its children.

  """
  assert len(vgnames) == len(names) == 2
  port = lu.cfg.AllocatePort()
  shared_secret = lu.cfg.GenerateDRBDSecret(lu.proc.GetECId())

  dev_data = objects.Disk(dev_type=constants.LD_LV, size=size,
                          logical_id=(vgnames[0], names[0]),
                          params={})
  dev_meta = objects.Disk(dev_type=constants.LD_LV,
                          size=constants.DRBD_META_SIZE,
                          logical_id=(vgnames[1], names[1]),
                          params={})
  drbd_dev = objects.Disk(dev_type=constants.LD_DRBD8, size=size,
                          logical_id=(primary, secondary, port,
                                      p_minor, s_minor,
                                      shared_secret),
                          children=[dev_data, dev_meta],
                          iv_name=iv_name, params={})
  return drbd_dev


_DISK_TEMPLATE_NAME_PREFIX = {
  constants.DT_PLAIN: "",
  constants.DT_RBD: ".rbd",
  constants.DT_EXT: ".ext",
  }


_DISK_TEMPLATE_DEVICE_TYPE = {
  constants.DT_PLAIN: constants.LD_LV,
  constants.DT_FILE: constants.LD_FILE,
  constants.DT_SHARED_FILE: constants.LD_FILE,
  constants.DT_BLOCK: constants.LD_BLOCKDEV,
  constants.DT_RBD: constants.LD_RBD,
  constants.DT_EXT: constants.LD_EXT,
  }


def _GenerateDiskTemplate(
  lu, template_name, instance_name, primary_node, secondary_nodes,
  disk_info, file_storage_dir, file_driver, base_index,
  feedback_fn, full_disk_params, _req_file_storage=opcodes.RequireFileStorage,
  _req_shr_file_storage=opcodes.RequireSharedFileStorage):
  """Generate the entire disk layout for a given template type.

  """
  vgname = lu.cfg.GetVGName()
  disk_count = len(disk_info)
  disks = []

  if template_name == constants.DT_DISKLESS:
    pass
  elif template_name == constants.DT_DRBD8:
    if len(secondary_nodes) != 1:
      raise errors.ProgrammerError("Wrong template configuration")
    remote_node = secondary_nodes[0]
    minors = lu.cfg.AllocateDRBDMinor(
      [primary_node, remote_node] * len(disk_info), instance_name)

    (drbd_params, _, _) = objects.Disk.ComputeLDParams(template_name,
                                                       full_disk_params)
    drbd_default_metavg = drbd_params[constants.LDP_DEFAULT_METAVG]

    names = []
    for lv_prefix in _GenerateUniqueNames(lu, [".disk%d" % (base_index + i)
                                               for i in range(disk_count)]):
      names.append(lv_prefix + "_data")
      names.append(lv_prefix + "_meta")
    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      data_vg = disk.get(constants.IDISK_VG, vgname)
      meta_vg = disk.get(constants.IDISK_METAVG, drbd_default_metavg)
      disk_dev = _GenerateDRBD8Branch(lu, primary_node, remote_node,
                                      disk[constants.IDISK_SIZE],
                                      [data_vg, meta_vg],
                                      names[idx * 2:idx * 2 + 2],
                                      "disk/%d" % disk_index,
                                      minors[idx * 2], minors[idx * 2 + 1])
      disk_dev.mode = disk[constants.IDISK_MODE]
      disks.append(disk_dev)
  else:
    if secondary_nodes:
      raise errors.ProgrammerError("Wrong template configuration")

    if template_name == constants.DT_FILE:
      _req_file_storage()
    elif template_name == constants.DT_SHARED_FILE:
      _req_shr_file_storage()

    name_prefix = _DISK_TEMPLATE_NAME_PREFIX.get(template_name, None)
    if name_prefix is None:
      names = None
    else:
      names = _GenerateUniqueNames(lu, ["%s.disk%s" %
                                        (name_prefix, base_index + i)
                                        for i in range(disk_count)])

    if template_name == constants.DT_PLAIN:

      def logical_id_fn(idx, _, disk):
        vg = disk.get(constants.IDISK_VG, vgname)
        return (vg, names[idx])

    elif template_name in (constants.DT_FILE, constants.DT_SHARED_FILE):
      logical_id_fn = \
        lambda _, disk_index, disk: (file_driver,
                                     "%s/disk%d" % (file_storage_dir,
                                                    disk_index))
    elif template_name == constants.DT_BLOCK:
      logical_id_fn = \
        lambda idx, disk_index, disk: (constants.BLOCKDEV_DRIVER_MANUAL,
                                       disk[constants.IDISK_ADOPT])
    elif template_name == constants.DT_RBD:
      logical_id_fn = lambda idx, _, disk: ("rbd", names[idx])
    elif template_name == constants.DT_EXT:
      def logical_id_fn(idx, _, disk):
        provider = disk.get(constants.IDISK_PROVIDER, None)
        if provider is None:
          raise errors.ProgrammerError("Disk template is %s, but '%s' is"
                                       " not found", constants.DT_EXT,
                                       constants.IDISK_PROVIDER)
        return (provider, names[idx])
    else:
      raise errors.ProgrammerError("Unknown disk template '%s'" % template_name)

    dev_type = _DISK_TEMPLATE_DEVICE_TYPE[template_name]

    for idx, disk in enumerate(disk_info):
      params = {}
      # Only for the Ext template add disk_info to params
      if template_name == constants.DT_EXT:
        params[constants.IDISK_PROVIDER] = disk[constants.IDISK_PROVIDER]
        for key in disk:
          if key not in constants.IDISK_PARAMS:
            params[key] = disk[key]
      disk_index = idx + base_index
      size = disk[constants.IDISK_SIZE]
      feedback_fn("* disk %s, size %s" %
                  (disk_index, utils.FormatUnit(size, "h")))
      disks.append(objects.Disk(dev_type=dev_type, size=size,
                                logical_id=logical_id_fn(idx, disk_index, disk),
                                iv_name="disk/%d" % disk_index,
                                mode=disk[constants.IDISK_MODE],
                                params=params))

  return disks


def _GetInstanceInfoText(instance):
  """Compute that text that should be added to the disk's metadata.

  """
  return "originstname+%s" % instance.name


def _CalcEta(time_taken, written, total_size):
  """Calculates the ETA based on size written and total size.

  @param time_taken: The time taken so far
  @param written: amount written so far
  @param total_size: The total size of data to be written
  @return: The remaining time in seconds

  """
  avg_time = time_taken / float(written)
  return (total_size - written) * avg_time


def _WipeDisks(lu, instance, disks=None):
  """Wipes instance disks.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should create
  @return: the success of the wipe

  """
  node = instance.primary_node

  if disks is None:
    disks = [(idx, disk, 0)
             for (idx, disk) in enumerate(instance.disks)]

  for (_, device, _) in disks:
    lu.cfg.SetDiskID(device, node)

  logging.info("Pausing synchronization of disks of instance '%s'",
               instance.name)
  result = lu.rpc.call_blockdev_pause_resume_sync(node,
                                                  (map(compat.snd, disks),
                                                   instance),
                                                  True)
  result.Raise("Failed to pause disk synchronization on node '%s'" % node)

  for idx, success in enumerate(result.payload):
    if not success:
      logging.warn("Pausing synchronization of disk %s of instance '%s'"
                   " failed", idx, instance.name)

  try:
    for (idx, device, offset) in disks:
      # The wipe size is MIN_WIPE_CHUNK_PERCENT % of the instance disk but
      # MAX_WIPE_CHUNK at max. Truncating to integer to avoid rounding errors.
      wipe_chunk_size = \
        int(min(constants.MAX_WIPE_CHUNK,
                device.size / 100.0 * constants.MIN_WIPE_CHUNK_PERCENT))

      size = device.size
      last_output = 0
      start_time = time.time()

      if offset == 0:
        info_text = ""
      else:
        info_text = (" (from %s to %s)" %
                     (utils.FormatUnit(offset, "h"),
                      utils.FormatUnit(size, "h")))

      lu.LogInfo("* Wiping disk %s%s", idx, info_text)

      logging.info("Wiping disk %d for instance %s on node %s using"
                   " chunk size %s", idx, instance.name, node, wipe_chunk_size)

      while offset < size:
        wipe_size = min(wipe_chunk_size, size - offset)

        logging.debug("Wiping disk %d, offset %s, chunk %s",
                      idx, offset, wipe_size)

        result = lu.rpc.call_blockdev_wipe(node, (device, instance), offset,
                                           wipe_size)
        result.Raise("Could not wipe disk %d at offset %d for size %d" %
                     (idx, offset, wipe_size))

        now = time.time()
        offset += wipe_size
        if now - last_output >= 60:
          eta = _CalcEta(now - start_time, offset, size)
          lu.LogInfo(" - done: %.1f%% ETA: %s",
                     offset / float(size) * 100, utils.FormatSeconds(eta))
          last_output = now
  finally:
    logging.info("Resuming synchronization of disks for instance '%s'",
                 instance.name)

    result = lu.rpc.call_blockdev_pause_resume_sync(node,
                                                    (map(compat.snd, disks),
                                                     instance),
                                                    False)

    if result.fail_msg:
      lu.LogWarning("Failed to resume disk synchronization on node '%s': %s",
                    node, result.fail_msg)
    else:
      for idx, success in enumerate(result.payload):
        if not success:
          lu.LogWarning("Resuming synchronization of disk %s of instance '%s'"
                        " failed", idx, instance.name)


def _CreateDisks(lu, instance, to_skip=None, target_node=None):
  """Create all disks for an instance.

  This abstracts away some work from AddInstance.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should create
  @type to_skip: list
  @param to_skip: list of indices to skip
  @type target_node: string
  @param target_node: if passed, overrides the target node for creation
  @rtype: boolean
  @return: the success of the creation

  """
  info = _GetInstanceInfoText(instance)
  if target_node is None:
    pnode = instance.primary_node
    all_nodes = instance.all_nodes
  else:
    pnode = target_node
    all_nodes = [pnode]

  if instance.disk_template in constants.DTS_FILEBASED:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    result = lu.rpc.call_file_storage_dir_create(pnode, file_storage_dir)

    result.Raise("Failed to create directory '%s' on"
                 " node %s" % (file_storage_dir, pnode))

  disks_created = []
  # Note: this needs to be kept in sync with adding of disks in
  # LUInstanceSetParams
  for idx, device in enumerate(instance.disks):
    if to_skip and idx in to_skip:
      continue
    logging.info("Creating disk %s for instance '%s'", idx, instance.name)
    #HARDCODE
    for node in all_nodes:
      f_create = node == pnode
      try:
        _CreateBlockDev(lu, node, instance, device, f_create, info, f_create)
        disks_created.append((node, device))
      except errors.OpExecError:
        logging.warning("Creating disk %s for instance '%s' failed",
                        idx, instance.name)
        for (node, disk) in disks_created:
          lu.cfg.SetDiskID(disk, node)
          result = lu.rpc.call_blockdev_remove(node, disk)
          if result.fail_msg:
            logging.warning("Failed to remove newly-created disk %s on node %s:"
                            " %s", device, node, result.fail_msg)
        raise


def _RemoveDisks(lu, instance, target_node=None, ignore_failures=False):
  """Remove all disks for an instance.

  This abstracts away some work from `AddInstance()` and
  `RemoveInstance()`. Note that in case some of the devices couldn't
  be removed, the removal will continue with the other ones.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should remove
  @type target_node: string
  @param target_node: used to override the node on which to remove the disks
  @rtype: boolean
  @return: the success of the removal

  """
  logging.info("Removing block devices for instance %s", instance.name)

  all_result = True
  ports_to_release = set()
  anno_disks = _AnnotateDiskParams(instance, instance.disks, lu.cfg)
  for (idx, device) in enumerate(anno_disks):
    if target_node:
      edata = [(target_node, device)]
    else:
      edata = device.ComputeNodeTree(instance.primary_node)
    for node, disk in edata:
      lu.cfg.SetDiskID(disk, node)
      result = lu.rpc.call_blockdev_remove(node, disk)
      if result.fail_msg:
        lu.LogWarning("Could not remove disk %s on node %s,"
                      " continuing anyway: %s", idx, node, result.fail_msg)
        if not (result.offline and node != instance.primary_node):
          all_result = False

    # if this is a DRBD disk, return its port to the pool
    if device.dev_type in constants.LDS_DRBD:
      ports_to_release.add(device.logical_id[2])

  if all_result or ignore_failures:
    for port in ports_to_release:
      lu.cfg.AddTcpUdpPort(port)

  if instance.disk_template in constants.DTS_FILEBASED:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    if target_node:
      tgt = target_node
    else:
      tgt = instance.primary_node
    result = lu.rpc.call_file_storage_dir_remove(tgt, file_storage_dir)
    if result.fail_msg:
      lu.LogWarning("Could not remove directory '%s' on node %s: %s",
                    file_storage_dir, instance.primary_node, result.fail_msg)
      all_result = False

  return all_result


def _ComputeDiskSizePerVG(disk_template, disks):
  """Compute disk size requirements in the volume group

  """
  def _compute(disks, payload):
    """Universal algorithm.

    """
    vgs = {}
    for disk in disks:
      vgs[disk[constants.IDISK_VG]] = \
        vgs.get(constants.IDISK_VG, 0) + disk[constants.IDISK_SIZE] + payload

    return vgs

  # Required free disk space as a function of disk and swap space
  req_size_dict = {
    constants.DT_DISKLESS: {},
    constants.DT_PLAIN: _compute(disks, 0),
    # 128 MB are added for drbd metadata for each disk
    constants.DT_DRBD8: _compute(disks, constants.DRBD_META_SIZE),
    constants.DT_FILE: {},
    constants.DT_SHARED_FILE: {},
  }

  if disk_template not in req_size_dict:
    raise errors.ProgrammerError("Disk template '%s' size requirement"
                                 " is unknown" % disk_template)

  return req_size_dict[disk_template]


def _FilterVmNodes(lu, nodenames):
  """Filters out non-vm_capable nodes from a list.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit for which we check
  @type nodenames: list
  @param nodenames: the list of nodes on which we should check
  @rtype: list
  @return: the list of vm-capable nodes

  """
  vm_nodes = frozenset(lu.cfg.GetNonVmCapableNodeList())
  return [name for name in nodenames if name not in vm_nodes]


def _CheckHVParams(lu, nodenames, hvname, hvparams):
  """Hypervisor parameter validation.

  This function abstract the hypervisor parameter validation to be
  used in both instance create and instance modify.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit for which we check
  @type nodenames: list
  @param nodenames: the list of nodes on which we should check
  @type hvname: string
  @param hvname: the name of the hypervisor we should use
  @type hvparams: dict
  @param hvparams: the parameters which we need to check
  @raise errors.OpPrereqError: if the parameters are not valid

  """
  nodenames = _FilterVmNodes(lu, nodenames)

  cluster = lu.cfg.GetClusterInfo()
  hvfull = objects.FillDict(cluster.hvparams.get(hvname, {}), hvparams)

  hvinfo = lu.rpc.call_hypervisor_validate_params(nodenames, hvname, hvfull)
  for node in nodenames:
    info = hvinfo[node]
    if info.offline:
      continue
    info.Raise("Hypervisor parameter validation failed on node %s" % node)


def _CheckOSParams(lu, required, nodenames, osname, osparams):
  """OS parameters validation.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit for which we check
  @type required: boolean
  @param required: whether the validation should fail if the OS is not
      found
  @type nodenames: list
  @param nodenames: the list of nodes on which we should check
  @type osname: string
  @param osname: the name of the hypervisor we should use
  @type osparams: dict
  @param osparams: the parameters which we need to check
  @raise errors.OpPrereqError: if the parameters are not valid

  """
  nodenames = _FilterVmNodes(lu, nodenames)
  result = lu.rpc.call_os_validate(nodenames, required, osname,
                                   [constants.OS_VALIDATE_PARAMETERS],
                                   osparams)
  for node, nres in result.items():
    # we don't check for offline cases since this should be run only
    # against the master node and/or an instance's nodes
    nres.Raise("OS Parameters validation failed on node %s" % node)
    if not nres.payload:
      lu.LogInfo("OS %s not found on node %s, validation skipped",
                 osname, node)


def _CreateInstanceAllocRequest(op, disks, nics, beparams, node_whitelist):
  """Wrapper around IAReqInstanceAlloc.

  @param op: The instance opcode
  @param disks: The computed disks
  @param nics: The computed nics
  @param beparams: The full filled beparams
  @param node_whitelist: List of nodes which should appear as online to the
    allocator (unless the node is already marked offline)

  @returns: A filled L{iallocator.IAReqInstanceAlloc}

  """
  spindle_use = beparams[constants.BE_SPINDLE_USE]
  return iallocator.IAReqInstanceAlloc(name=op.instance_name,
                                       disk_template=op.disk_template,
                                       tags=op.tags,
                                       os=op.os_type,
                                       vcpus=beparams[constants.BE_VCPUS],
                                       memory=beparams[constants.BE_MAXMEM],
                                       spindle_use=spindle_use,
                                       disks=disks,
                                       nics=[n.ToDict() for n in nics],
                                       hypervisor=op.hypervisor,
                                       node_whitelist=node_whitelist)


def _ComputeNics(op, cluster, default_ip, cfg, ec_id):
  """Computes the nics.

  @param op: The instance opcode
  @param cluster: Cluster configuration object
  @param default_ip: The default ip to assign
  @param cfg: An instance of the configuration object
  @param ec_id: Execution context ID

  @returns: The build up nics

  """
  nics = []
  for nic in op.nics:
    nic_mode_req = nic.get(constants.INIC_MODE, None)
    nic_mode = nic_mode_req
    if nic_mode is None or nic_mode == constants.VALUE_AUTO:
      nic_mode = cluster.nicparams[constants.PP_DEFAULT][constants.NIC_MODE]

    net = nic.get(constants.INIC_NETWORK, None)
    link = nic.get(constants.NIC_LINK, None)
    ip = nic.get(constants.INIC_IP, None)

    if net is None or net.lower() == constants.VALUE_NONE:
      net = None
    else:
      if nic_mode_req is not None or link is not None:
        raise errors.OpPrereqError("If network is given, no mode or link"
                                   " is allowed to be passed",
                                   errors.ECODE_INVAL)

    # ip validity checks
    if ip is None or ip.lower() == constants.VALUE_NONE:
      nic_ip = None
    elif ip.lower() == constants.VALUE_AUTO:
      if not op.name_check:
        raise errors.OpPrereqError("IP address set to auto but name checks"
                                   " have been skipped",
                                   errors.ECODE_INVAL)
      nic_ip = default_ip
    else:
      # We defer pool operations until later, so that the iallocator has
      # filled in the instance's node(s) dimara
      if ip.lower() == constants.NIC_IP_POOL:
        if net is None:
          raise errors.OpPrereqError("if ip=pool, parameter network"
                                     " must be passed too",
                                     errors.ECODE_INVAL)

      elif not netutils.IPAddress.IsValid(ip):
        raise errors.OpPrereqError("Invalid IP address '%s'" % ip,
                                   errors.ECODE_INVAL)

      nic_ip = ip

    # TODO: check the ip address for uniqueness
    if nic_mode == constants.NIC_MODE_ROUTED and not nic_ip:
      raise errors.OpPrereqError("Routed nic mode requires an ip address",
                                 errors.ECODE_INVAL)

    # MAC address verification
    mac = nic.get(constants.INIC_MAC, constants.VALUE_AUTO)
    if mac not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
      mac = utils.NormalizeAndValidateMac(mac)

      try:
        # TODO: We need to factor this out
        cfg.ReserveMAC(mac, ec_id)
      except errors.ReservationError:
        raise errors.OpPrereqError("MAC address %s already in use"
                                   " in cluster" % mac,
                                   errors.ECODE_NOTUNIQUE)

    #  Build nic parameters
    nicparams = {}
    if nic_mode_req:
      nicparams[constants.NIC_MODE] = nic_mode
    if link:
      nicparams[constants.NIC_LINK] = link

    check_params = cluster.SimpleFillNIC(nicparams)
    objects.NIC.CheckParameterSyntax(check_params)
    net_uuid = cfg.LookupNetwork(net)
    nics.append(objects.NIC(mac=mac, ip=nic_ip,
                            network=net_uuid, nicparams=nicparams))

  return nics


def _ComputeDisks(op, default_vg):
  """Computes the instance disks.

  @param op: The instance opcode
  @param default_vg: The default_vg to assume

  @return: The computed disks

  """
  disks = []
  for disk in op.disks:
    mode = disk.get(constants.IDISK_MODE, constants.DISK_RDWR)
    if mode not in constants.DISK_ACCESS_SET:
      raise errors.OpPrereqError("Invalid disk access mode '%s'" %
                                 mode, errors.ECODE_INVAL)
    size = disk.get(constants.IDISK_SIZE, None)
    if size is None:
      raise errors.OpPrereqError("Missing disk size", errors.ECODE_INVAL)
    try:
      size = int(size)
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid disk size '%s'" % size,
                                 errors.ECODE_INVAL)

    ext_provider = disk.get(constants.IDISK_PROVIDER, None)
    if ext_provider and op.disk_template != constants.DT_EXT:
      raise errors.OpPrereqError("The '%s' option is only valid for the %s"
                                 " disk template, not %s" %
                                 (constants.IDISK_PROVIDER, constants.DT_EXT,
                                 op.disk_template), errors.ECODE_INVAL)

    data_vg = disk.get(constants.IDISK_VG, default_vg)
    new_disk = {
      constants.IDISK_SIZE: size,
      constants.IDISK_MODE: mode,
      constants.IDISK_VG: data_vg,
      }

    if constants.IDISK_METAVG in disk:
      new_disk[constants.IDISK_METAVG] = disk[constants.IDISK_METAVG]
    if constants.IDISK_ADOPT in disk:
      new_disk[constants.IDISK_ADOPT] = disk[constants.IDISK_ADOPT]

    # For extstorage, demand the `provider' option and add any
    # additional parameters (ext-params) to the dict
    if op.disk_template == constants.DT_EXT:
      if ext_provider:
        new_disk[constants.IDISK_PROVIDER] = ext_provider
        for key in disk:
          if key not in constants.IDISK_PARAMS:
            new_disk[key] = disk[key]
      else:
        raise errors.OpPrereqError("Missing provider for template '%s'" %
                                   constants.DT_EXT, errors.ECODE_INVAL)

    disks.append(new_disk)

  return disks


def _ComputeFullBeParams(op, cluster):
  """Computes the full beparams.

  @param op: The instance opcode
  @param cluster: The cluster config object

  @return: The fully filled beparams

  """
  default_beparams = cluster.beparams[constants.PP_DEFAULT]
  for param, value in op.beparams.iteritems():
    if value == constants.VALUE_AUTO:
      op.beparams[param] = default_beparams[param]
  objects.UpgradeBeParams(op.beparams)
  utils.ForceDictType(op.beparams, constants.BES_PARAMETER_TYPES)
  return cluster.SimpleFillBE(op.beparams)


def _CheckOpportunisticLocking(op):
  """Generate error if opportunistic locking is not possible.

  """
  if op.opportunistic_locking and not op.iallocator:
    raise errors.OpPrereqError("Opportunistic locking is only available in"
                               " combination with an instance allocator",
                               errors.ECODE_INVAL)


class LUInstanceCreate(LogicalUnit):
  """Create an instance.

  """
  HPATH = "instance-add"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    # do not require name_check to ease forward/backward compatibility
    # for tools
    if self.op.no_install and self.op.start:
      self.LogInfo("No-installation mode selected, disabling startup")
      self.op.start = False
    # validate/normalize the instance name
    self.op.instance_name = \
      netutils.Hostname.GetNormalizedName(self.op.instance_name)

    if self.op.ip_check and not self.op.name_check:
      # TODO: make the ip check more flexible and not depend on the name check
      raise errors.OpPrereqError("Cannot do IP address check without a name"
                                 " check", errors.ECODE_INVAL)

    # check nics' parameter names
    for nic in self.op.nics:
      utils.ForceDictType(nic, constants.INIC_PARAMS_TYPES)

    # check disks. parameter names and consistent adopt/no-adopt strategy
    has_adopt = has_no_adopt = False
    for disk in self.op.disks:
      if self.op.disk_template != constants.DT_EXT:
        utils.ForceDictType(disk, constants.IDISK_PARAMS_TYPES)
      if constants.IDISK_ADOPT in disk:
        has_adopt = True
      else:
        has_no_adopt = True
    if has_adopt and has_no_adopt:
      raise errors.OpPrereqError("Either all disks are adopted or none is",
                                 errors.ECODE_INVAL)
    if has_adopt:
      if self.op.disk_template not in constants.DTS_MAY_ADOPT:
        raise errors.OpPrereqError("Disk adoption is not supported for the"
                                   " '%s' disk template" %
                                   self.op.disk_template,
                                   errors.ECODE_INVAL)
      if self.op.iallocator is not None:
        raise errors.OpPrereqError("Disk adoption not allowed with an"
                                   " iallocator script", errors.ECODE_INVAL)
      if self.op.mode == constants.INSTANCE_IMPORT:
        raise errors.OpPrereqError("Disk adoption not allowed for"
                                   " instance import", errors.ECODE_INVAL)
    else:
      if self.op.disk_template in constants.DTS_MUST_ADOPT:
        raise errors.OpPrereqError("Disk template %s requires disk adoption,"
                                   " but no 'adopt' parameter given" %
                                   self.op.disk_template,
                                   errors.ECODE_INVAL)

    self.adopt_disks = has_adopt

    # instance name verification
    if self.op.name_check:
      self.hostname1 = _CheckHostnameSane(self, self.op.instance_name)
      self.op.instance_name = self.hostname1.name
      # used in CheckPrereq for ip ping check
      self.check_ip = self.hostname1.ip
    else:
      self.check_ip = None

    # file storage checks
    if (self.op.file_driver and
        not self.op.file_driver in constants.FILE_DRIVER):
      raise errors.OpPrereqError("Invalid file driver name '%s'" %
                                 self.op.file_driver, errors.ECODE_INVAL)

    if self.op.disk_template == constants.DT_FILE:
      opcodes.RequireFileStorage()
    elif self.op.disk_template == constants.DT_SHARED_FILE:
      opcodes.RequireSharedFileStorage()

    ### Node/iallocator related checks
    _CheckIAllocatorOrNode(self, "iallocator", "pnode")

    if self.op.pnode is not None:
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        if self.op.snode is None:
          raise errors.OpPrereqError("The networked disk templates need"
                                     " a mirror node", errors.ECODE_INVAL)
      elif self.op.snode:
        self.LogWarning("Secondary node will be ignored on non-mirrored disk"
                        " template")
        self.op.snode = None

    _CheckOpportunisticLocking(self.op)

    self._cds = _GetClusterDomainSecret()

    if self.op.mode == constants.INSTANCE_IMPORT:
      # On import force_variant must be True, because if we forced it at
      # initial install, our only chance when importing it back is that it
      # works again!
      self.op.force_variant = True

      if self.op.no_install:
        self.LogInfo("No-installation mode has no effect during import")

    elif self.op.mode == constants.INSTANCE_CREATE:
      if self.op.os_type is None:
        raise errors.OpPrereqError("No guest OS specified",
                                   errors.ECODE_INVAL)
      if self.op.os_type in self.cfg.GetClusterInfo().blacklisted_os:
        raise errors.OpPrereqError("Guest OS '%s' is not allowed for"
                                   " installation" % self.op.os_type,
                                   errors.ECODE_STATE)
      if self.op.disk_template is None:
        raise errors.OpPrereqError("No disk template specified",
                                   errors.ECODE_INVAL)

    elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
      # Check handshake to ensure both clusters have the same domain secret
      src_handshake = self.op.source_handshake
      if not src_handshake:
        raise errors.OpPrereqError("Missing source handshake",
                                   errors.ECODE_INVAL)

      errmsg = masterd.instance.CheckRemoteExportHandshake(self._cds,
                                                           src_handshake)
      if errmsg:
        raise errors.OpPrereqError("Invalid handshake: %s" % errmsg,
                                   errors.ECODE_INVAL)

      # Load and check source CA
      self.source_x509_ca_pem = self.op.source_x509_ca
      if not self.source_x509_ca_pem:
        raise errors.OpPrereqError("Missing source X509 CA",
                                   errors.ECODE_INVAL)

      try:
        (cert, _) = utils.LoadSignedX509Certificate(self.source_x509_ca_pem,
                                                    self._cds)
      except OpenSSL.crypto.Error, err:
        raise errors.OpPrereqError("Unable to load source X509 CA (%s)" %
                                   (err, ), errors.ECODE_INVAL)

      (errcode, msg) = utils.VerifyX509Certificate(cert, None, None)
      if errcode is not None:
        raise errors.OpPrereqError("Invalid source X509 CA (%s)" % (msg, ),
                                   errors.ECODE_INVAL)

      self.source_x509_ca = cert

      src_instance_name = self.op.source_instance_name
      if not src_instance_name:
        raise errors.OpPrereqError("Missing source instance name",
                                   errors.ECODE_INVAL)

      self.source_instance_name = \
          netutils.GetHostname(name=src_instance_name).name

    else:
      raise errors.OpPrereqError("Invalid instance creation mode %r" %
                                 self.op.mode, errors.ECODE_INVAL)

  def ExpandNames(self):
    """ExpandNames for CreateInstance.

    Figure out the right locks for instance creation.

    """
    self.needed_locks = {}

    instance_name = self.op.instance_name
    # this is just a preventive check, but someone might still add this
    # instance in the meantime, and creation will fail at lock-add time
    if instance_name in self.cfg.GetInstanceList():
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 instance_name, errors.ECODE_EXISTS)

    self.add_locks[locking.LEVEL_INSTANCE] = instance_name

    if self.op.iallocator:
      # TODO: Find a solution to not lock all nodes in the cluster, e.g. by
      # specifying a group on instance creation and then selecting nodes from
      # that group
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

      if self.op.opportunistic_locking:
        self.opportunistic_locks[locking.LEVEL_NODE] = True
        self.opportunistic_locks[locking.LEVEL_NODE_RES] = True
    else:
      self.op.pnode = _ExpandNodeName(self.cfg, self.op.pnode)
      nodelist = [self.op.pnode]
      if self.op.snode is not None:
        self.op.snode = _ExpandNodeName(self.cfg, self.op.snode)
        nodelist.append(self.op.snode)
      self.needed_locks[locking.LEVEL_NODE] = nodelist

    # in case of import lock the source node too
    if self.op.mode == constants.INSTANCE_IMPORT:
      src_node = self.op.src_node
      src_path = self.op.src_path

      if src_path is None:
        self.op.src_path = src_path = self.op.instance_name

      if src_node is None:
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET
        self.op.src_node = None
        if os.path.isabs(src_path):
          raise errors.OpPrereqError("Importing an instance from a path"
                                     " requires a source node option",
                                     errors.ECODE_INVAL)
      else:
        self.op.src_node = src_node = _ExpandNodeName(self.cfg, src_node)
        if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
          self.needed_locks[locking.LEVEL_NODE].append(src_node)
        if not os.path.isabs(src_path):
          self.op.src_path = src_path = \
            utils.PathJoin(pathutils.EXPORT_DIR, src_path)

    self.needed_locks[locking.LEVEL_NODE_RES] = \
      _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    if self.op.opportunistic_locking:
      # Only consider nodes for which a lock is held
      node_whitelist = list(self.owned_locks(locking.LEVEL_NODE))
    else:
      node_whitelist = None

    #TODO Export network to iallocator so that it chooses a pnode
    #     in a nodegroup that has the desired network connected to
    req = _CreateInstanceAllocRequest(self.op, self.disks,
                                      self.nics, self.be_full,
                                      node_whitelist)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      # When opportunistic locks are used only a temporary failure is generated
      if self.op.opportunistic_locking:
        ecode = errors.ECODE_TEMP_NORES
      else:
        ecode = errors.ECODE_NORES

      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 ecode)

    self.op.pnode = ial.result[0]
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(ial.result))

    assert req.RequiredNodes() in (1, 2), "Wrong node count from iallocator"

    if req.RequiredNodes() == 2:
      self.op.snode = ial.result[1]

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "ADD_MODE": self.op.mode,
      }
    if self.op.mode == constants.INSTANCE_IMPORT:
      env["SRC_NODE"] = self.op.src_node
      env["SRC_PATH"] = self.op.src_path
      env["SRC_IMAGES"] = self.src_images

    env.update(_BuildInstanceHookEnv(
      name=self.op.instance_name,
      primary_node=self.op.pnode,
      secondary_nodes=self.secondaries,
      status=self.op.start,
      os_type=self.op.os_type,
      minmem=self.be_full[constants.BE_MINMEM],
      maxmem=self.be_full[constants.BE_MAXMEM],
      vcpus=self.be_full[constants.BE_VCPUS],
      nics=_NICListToTuple(self, self.nics),
      disk_template=self.op.disk_template,
      disks=[(d[constants.IDISK_SIZE], d[constants.IDISK_MODE])
             for d in self.disks],
      bep=self.be_full,
      hvp=self.hv_full,
      hypervisor_name=self.op.hypervisor,
      tags=self.op.tags,
    ))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.op.pnode] + self.secondaries
    return nl, nl

  def _ReadExportInfo(self):
    """Reads the export information from disk.

    It will override the opcode source node and path with the actual
    information, if these two were not specified before.

    @return: the export information

    """
    assert self.op.mode == constants.INSTANCE_IMPORT

    src_node = self.op.src_node
    src_path = self.op.src_path

    if src_node is None:
      locked_nodes = self.owned_locks(locking.LEVEL_NODE)
      exp_list = self.rpc.call_export_list(locked_nodes)
      found = False
      for node in exp_list:
        if exp_list[node].fail_msg:
          continue
        if src_path in exp_list[node].payload:
          found = True
          self.op.src_node = src_node = node
          self.op.src_path = src_path = utils.PathJoin(pathutils.EXPORT_DIR,
                                                       src_path)
          break
      if not found:
        raise errors.OpPrereqError("No export found for relative path %s" %
                                    src_path, errors.ECODE_INVAL)

    _CheckNodeOnline(self, src_node)
    result = self.rpc.call_export_info(src_node, src_path)
    result.Raise("No export or invalid export found in dir %s" % src_path)

    export_info = objects.SerializableConfigParser.Loads(str(result.payload))
    if not export_info.has_section(constants.INISECT_EXP):
      raise errors.ProgrammerError("Corrupted export config",
                                   errors.ECODE_ENVIRON)

    ei_version = export_info.get(constants.INISECT_EXP, "version")
    if (int(ei_version) != constants.EXPORT_VERSION):
      raise errors.OpPrereqError("Wrong export version %s (wanted %d)" %
                                 (ei_version, constants.EXPORT_VERSION),
                                 errors.ECODE_ENVIRON)
    return export_info

  def _ReadExportParams(self, einfo):
    """Use export parameters as defaults.

    In case the opcode doesn't specify (as in override) some instance
    parameters, then try to use them from the export information, if
    that declares them.

    """
    self.op.os_type = einfo.get(constants.INISECT_EXP, "os")

    if self.op.disk_template is None:
      if einfo.has_option(constants.INISECT_INS, "disk_template"):
        self.op.disk_template = einfo.get(constants.INISECT_INS,
                                          "disk_template")
        if self.op.disk_template not in constants.DISK_TEMPLATES:
          raise errors.OpPrereqError("Disk template specified in configuration"
                                     " file is not one of the allowed values:"
                                     " %s" %
                                     " ".join(constants.DISK_TEMPLATES),
                                     errors.ECODE_INVAL)
      else:
        raise errors.OpPrereqError("No disk template specified and the export"
                                   " is missing the disk_template information",
                                   errors.ECODE_INVAL)

    if not self.op.disks:
      disks = []
      # TODO: import the disk iv_name too
      for idx in range(constants.MAX_DISKS):
        if einfo.has_option(constants.INISECT_INS, "disk%d_size" % idx):
          disk_sz = einfo.getint(constants.INISECT_INS, "disk%d_size" % idx)
          disks.append({constants.IDISK_SIZE: disk_sz})
      self.op.disks = disks
      if not disks and self.op.disk_template != constants.DT_DISKLESS:
        raise errors.OpPrereqError("No disk info specified and the export"
                                   " is missing the disk information",
                                   errors.ECODE_INVAL)

    if not self.op.nics:
      nics = []
      for idx in range(constants.MAX_NICS):
        if einfo.has_option(constants.INISECT_INS, "nic%d_mac" % idx):
          ndict = {}
          for name in list(constants.NICS_PARAMETERS) + ["ip", "mac"]:
            v = einfo.get(constants.INISECT_INS, "nic%d_%s" % (idx, name))
            ndict[name] = v
          nics.append(ndict)
        else:
          break
      self.op.nics = nics

    if not self.op.tags and einfo.has_option(constants.INISECT_INS, "tags"):
      self.op.tags = einfo.get(constants.INISECT_INS, "tags").split()

    if (self.op.hypervisor is None and
        einfo.has_option(constants.INISECT_INS, "hypervisor")):
      self.op.hypervisor = einfo.get(constants.INISECT_INS, "hypervisor")

    if einfo.has_section(constants.INISECT_HYP):
      # use the export parameters but do not override the ones
      # specified by the user
      for name, value in einfo.items(constants.INISECT_HYP):
        if name not in self.op.hvparams:
          self.op.hvparams[name] = value

    if einfo.has_section(constants.INISECT_BEP):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_BEP):
        if name not in self.op.beparams:
          self.op.beparams[name] = value
        # Compatibility for the old "memory" be param
        if name == constants.BE_MEMORY:
          if constants.BE_MAXMEM not in self.op.beparams:
            self.op.beparams[constants.BE_MAXMEM] = value
          if constants.BE_MINMEM not in self.op.beparams:
            self.op.beparams[constants.BE_MINMEM] = value
    else:
      # try to read the parameters old style, from the main section
      for name in constants.BES_PARAMETERS:
        if (name not in self.op.beparams and
            einfo.has_option(constants.INISECT_INS, name)):
          self.op.beparams[name] = einfo.get(constants.INISECT_INS, name)

    if einfo.has_section(constants.INISECT_OSP):
      # use the parameters, without overriding
      for name, value in einfo.items(constants.INISECT_OSP):
        if name not in self.op.osparams:
          self.op.osparams[name] = value

  def _RevertToDefaults(self, cluster):
    """Revert the instance parameters to the default values.

    """
    # hvparams
    hv_defs = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type, {})
    for name in self.op.hvparams.keys():
      if name in hv_defs and hv_defs[name] == self.op.hvparams[name]:
        del self.op.hvparams[name]
    # beparams
    be_defs = cluster.SimpleFillBE({})
    for name in self.op.beparams.keys():
      if name in be_defs and be_defs[name] == self.op.beparams[name]:
        del self.op.beparams[name]
    # nic params
    nic_defs = cluster.SimpleFillNIC({})
    for nic in self.op.nics:
      for name in constants.NICS_PARAMETERS:
        if name in nic and name in nic_defs and nic[name] == nic_defs[name]:
          del nic[name]
    # osparams
    os_defs = cluster.SimpleFillOS(self.op.os_type, {})
    for name in self.op.osparams.keys():
      if name in os_defs and os_defs[name] == self.op.osparams[name]:
        del self.op.osparams[name]

  def _CalculateFileStorageDir(self):
    """Calculate final instance file storage dir.

    """
    # file storage dir calculation/check
    self.instance_file_storage_dir = None
    if self.op.disk_template in constants.DTS_FILEBASED:
      # build the full file storage dir path
      joinargs = []

      if self.op.disk_template == constants.DT_SHARED_FILE:
        get_fsd_fn = self.cfg.GetSharedFileStorageDir
      else:
        get_fsd_fn = self.cfg.GetFileStorageDir

      cfg_storagedir = get_fsd_fn()
      if not cfg_storagedir:
        raise errors.OpPrereqError("Cluster file storage dir not defined",
                                   errors.ECODE_STATE)
      joinargs.append(cfg_storagedir)

      if self.op.file_storage_dir is not None:
        joinargs.append(self.op.file_storage_dir)

      joinargs.append(self.op.instance_name)

      # pylint: disable=W0142
      self.instance_file_storage_dir = utils.PathJoin(*joinargs)

  def CheckPrereq(self): # pylint: disable=R0914
    """Check prerequisites.

    """
    self._CalculateFileStorageDir()

    if self.op.mode == constants.INSTANCE_IMPORT:
      export_info = self._ReadExportInfo()
      self._ReadExportParams(export_info)
      self._old_instance_name = export_info.get(constants.INISECT_INS, "name")
    else:
      self._old_instance_name = None

    if (not self.cfg.GetVGName() and
        self.op.disk_template not in constants.DTS_NOT_LVM):
      raise errors.OpPrereqError("Cluster does not support lvm-based"
                                 " instances", errors.ECODE_STATE)

    if (self.op.hypervisor is None or
        self.op.hypervisor == constants.VALUE_AUTO):
      self.op.hypervisor = self.cfg.GetHypervisorType()

    cluster = self.cfg.GetClusterInfo()
    enabled_hvs = cluster.enabled_hypervisors
    if self.op.hypervisor not in enabled_hvs:
      raise errors.OpPrereqError("Selected hypervisor (%s) not enabled in the"
                                 " cluster (%s)" %
                                 (self.op.hypervisor, ",".join(enabled_hvs)),
                                 errors.ECODE_STATE)

    # Check tag validity
    for tag in self.op.tags:
      objects.TaggableObject.ValidateTag(tag)

    # check hypervisor parameter syntax (locally)
    utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
    filled_hvp = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type,
                                      self.op.hvparams)
    hv_type = hypervisor.GetHypervisorClass(self.op.hypervisor)
    hv_type.CheckParameterSyntax(filled_hvp)
    self.hv_full = filled_hvp
    # check that we don't specify global parameters on an instance
    _CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS, "hypervisor",
                          "instance", "cluster")

    # fill and remember the beparams dict
    self.be_full = _ComputeFullBeParams(self.op, cluster)

    # build os parameters
    self.os_full = cluster.SimpleFillOS(self.op.os_type, self.op.osparams)

    # now that hvp/bep are in final format, let's reset to defaults,
    # if told to do so
    if self.op.identify_defaults:
      self._RevertToDefaults(cluster)

    # NIC buildup
    self.nics = _ComputeNics(self.op, cluster, self.check_ip, self.cfg,
                             self.proc.GetECId())

    # disk checks/pre-build
    default_vg = self.cfg.GetVGName()
    self.disks = _ComputeDisks(self.op, default_vg)

    if self.op.mode == constants.INSTANCE_IMPORT:
      disk_images = []
      for idx in range(len(self.disks)):
        option = "disk%d_dump" % idx
        if export_info.has_option(constants.INISECT_INS, option):
          # FIXME: are the old os-es, disk sizes, etc. useful?
          export_name = export_info.get(constants.INISECT_INS, option)
          image = utils.PathJoin(self.op.src_path, export_name)
          disk_images.append(image)
        else:
          disk_images.append(False)

      self.src_images = disk_images

      if self.op.instance_name == self._old_instance_name:
        for idx, nic in enumerate(self.nics):
          if nic.mac == constants.VALUE_AUTO:
            nic_mac_ini = "nic%d_mac" % idx
            nic.mac = export_info.get(constants.INISECT_INS, nic_mac_ini)

    # ENDIF: self.op.mode == constants.INSTANCE_IMPORT

    # ip ping checks (we use the same ip that was resolved in ExpandNames)
    if self.op.ip_check:
      if netutils.TcpPing(self.check_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (self.check_ip, self.op.instance_name),
                                   errors.ECODE_NOTUNIQUE)

    #### mac address generation
    # By generating here the mac address both the allocator and the hooks get
    # the real final mac address rather than the 'auto' or 'generate' value.
    # There is a race condition between the generation and the instance object
    # creation, which means that we know the mac is valid now, but we're not
    # sure it will be when we actually add the instance. If things go bad
    # adding the instance will abort because of a duplicate mac, and the
    # creation job will fail.
    for nic in self.nics:
      if nic.mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        nic.mac = self.cfg.GenerateMAC(nic.network, self.proc.GetECId())

    #### allocator run

    if self.op.iallocator is not None:
      self._RunAllocator()

    # Release all unneeded node locks
    keep_locks = filter(None, [self.op.pnode, self.op.snode, self.op.src_node])
    _ReleaseLocks(self, locking.LEVEL_NODE, keep=keep_locks)
    _ReleaseLocks(self, locking.LEVEL_NODE_RES, keep=keep_locks)
    _ReleaseLocks(self, locking.LEVEL_NODE_ALLOC)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES)), \
      "Node locks differ from node resource locks"

    #### node related checks

    # check primary node
    self.pnode = pnode = self.cfg.GetNodeInfo(self.op.pnode)
    assert self.pnode is not None, \
      "Cannot retrieve locked node %s" % self.op.pnode
    if pnode.offline:
      raise errors.OpPrereqError("Cannot use offline primary node '%s'" %
                                 pnode.name, errors.ECODE_STATE)
    if pnode.drained:
      raise errors.OpPrereqError("Cannot use drained primary node '%s'" %
                                 pnode.name, errors.ECODE_STATE)
    if not pnode.vm_capable:
      raise errors.OpPrereqError("Cannot use non-vm_capable primary node"
                                 " '%s'" % pnode.name, errors.ECODE_STATE)

    self.secondaries = []

    # Fill in any IPs from IP pools. This must happen here, because we need to
    # know the nic's primary node, as specified by the iallocator
    for idx, nic in enumerate(self.nics):
      net_uuid = nic.network
      if net_uuid is not None:
        nobj = self.cfg.GetNetwork(net_uuid)
        netparams = self.cfg.GetGroupNetParams(net_uuid, self.pnode.name)
        if netparams is None:
          raise errors.OpPrereqError("No netparams found for network"
                                     " %s. Propably not connected to"
                                     " node's %s nodegroup" %
                                     (nobj.name, self.pnode.name),
                                     errors.ECODE_INVAL)
        self.LogInfo("NIC/%d inherits netparams %s" %
                     (idx, netparams.values()))
        nic.nicparams = dict(netparams)
        if nic.ip is not None:
          if nic.ip.lower() == constants.NIC_IP_POOL:
            try:
              nic.ip = self.cfg.GenerateIp(net_uuid, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("Unable to get a free IP for NIC %d"
                                         " from the address pool" % idx,
                                         errors.ECODE_STATE)
            self.LogInfo("Chose IP %s from network %s", nic.ip, nobj.name)
          else:
            try:
              self.cfg.ReserveIp(net_uuid, nic.ip, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("IP address %s already in use"
                                         " or does not belong to network %s" %
                                         (nic.ip, nobj.name),
                                         errors.ECODE_NOTUNIQUE)

      # net is None, ip None or given
      elif self.op.conflicts_check:
        _CheckForConflictingIp(self, nic.ip, self.pnode.name)

    # mirror node verification
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.snode == pnode.name:
        raise errors.OpPrereqError("The secondary node cannot be the"
                                   " primary node", errors.ECODE_INVAL)
      _CheckNodeOnline(self, self.op.snode)
      _CheckNodeNotDrained(self, self.op.snode)
      _CheckNodeVmCapable(self, self.op.snode)
      self.secondaries.append(self.op.snode)

      snode = self.cfg.GetNodeInfo(self.op.snode)
      if pnode.group != snode.group:
        self.LogWarning("The primary and secondary nodes are in two"
                        " different node groups; the disk parameters"
                        " from the first disk's node group will be"
                        " used")

    if not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      nodes = [pnode]
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        nodes.append(snode)
      has_es = lambda n: _IsExclusiveStorageEnabledNode(self.cfg, n)
      if compat.any(map(has_es, nodes)):
        raise errors.OpPrereqError("Disk template %s not supported with"
                                   " exclusive storage" % self.op.disk_template,
                                   errors.ECODE_STATE)

    nodenames = [pnode.name] + self.secondaries

    if not self.adopt_disks:
      if self.op.disk_template == constants.DT_RBD:
        # _CheckRADOSFreeSpace() is just a placeholder.
        # Any function that checks prerequisites can be placed here.
        # Check if there is enough space on the RADOS cluster.
        _CheckRADOSFreeSpace()
      elif self.op.disk_template == constants.DT_EXT:
        # FIXME: Function that checks prereqs if needed
        pass
      else:
        # Check lv size requirements, if not adopting
        req_sizes = _ComputeDiskSizePerVG(self.op.disk_template, self.disks)
        _CheckNodesFreeDiskPerVG(self, nodenames, req_sizes)

    elif self.op.disk_template == constants.DT_PLAIN: # Check the adoption data
      all_lvs = set(["%s/%s" % (disk[constants.IDISK_VG],
                                disk[constants.IDISK_ADOPT])
                     for disk in self.disks])
      if len(all_lvs) != len(self.disks):
        raise errors.OpPrereqError("Duplicate volume names given for adoption",
                                   errors.ECODE_INVAL)
      for lv_name in all_lvs:
        try:
          # FIXME: lv_name here is "vg/lv" need to ensure that other calls
          # to ReserveLV uses the same syntax
          self.cfg.ReserveLV(lv_name, self.proc.GetECId())
        except errors.ReservationError:
          raise errors.OpPrereqError("LV named %s used by another instance" %
                                     lv_name, errors.ECODE_NOTUNIQUE)

      vg_names = self.rpc.call_vg_list([pnode.name])[pnode.name]
      vg_names.Raise("Cannot get VG information from node %s" % pnode.name)

      node_lvs = self.rpc.call_lv_list([pnode.name],
                                       vg_names.payload.keys())[pnode.name]
      node_lvs.Raise("Cannot get LV information from node %s" % pnode.name)
      node_lvs = node_lvs.payload

      delta = all_lvs.difference(node_lvs.keys())
      if delta:
        raise errors.OpPrereqError("Missing logical volume(s): %s" %
                                   utils.CommaJoin(delta),
                                   errors.ECODE_INVAL)
      online_lvs = [lv for lv in all_lvs if node_lvs[lv][2]]
      if online_lvs:
        raise errors.OpPrereqError("Online logical volumes found, cannot"
                                   " adopt: %s" % utils.CommaJoin(online_lvs),
                                   errors.ECODE_STATE)
      # update the size of disk based on what is found
      for dsk in self.disks:
        dsk[constants.IDISK_SIZE] = \
          int(float(node_lvs["%s/%s" % (dsk[constants.IDISK_VG],
                                        dsk[constants.IDISK_ADOPT])][0]))

    elif self.op.disk_template == constants.DT_BLOCK:
      # Normalize and de-duplicate device paths
      all_disks = set([os.path.abspath(disk[constants.IDISK_ADOPT])
                       for disk in self.disks])
      if len(all_disks) != len(self.disks):
        raise errors.OpPrereqError("Duplicate disk names given for adoption",
                                   errors.ECODE_INVAL)
      baddisks = [d for d in all_disks
                  if not d.startswith(constants.ADOPTABLE_BLOCKDEV_ROOT)]
      if baddisks:
        raise errors.OpPrereqError("Device node(s) %s lie outside %s and"
                                   " cannot be adopted" %
                                   (utils.CommaJoin(baddisks),
                                    constants.ADOPTABLE_BLOCKDEV_ROOT),
                                   errors.ECODE_INVAL)

      node_disks = self.rpc.call_bdev_sizes([pnode.name],
                                            list(all_disks))[pnode.name]
      node_disks.Raise("Cannot get block device information from node %s" %
                       pnode.name)
      node_disks = node_disks.payload
      delta = all_disks.difference(node_disks.keys())
      if delta:
        raise errors.OpPrereqError("Missing block device(s): %s" %
                                   utils.CommaJoin(delta),
                                   errors.ECODE_INVAL)
      for dsk in self.disks:
        dsk[constants.IDISK_SIZE] = \
          int(float(node_disks[dsk[constants.IDISK_ADOPT]]))

    # Verify instance specs
    spindle_use = self.be_full.get(constants.BE_SPINDLE_USE, None)
    ispec = {
      constants.ISPEC_MEM_SIZE: self.be_full.get(constants.BE_MAXMEM, None),
      constants.ISPEC_CPU_COUNT: self.be_full.get(constants.BE_VCPUS, None),
      constants.ISPEC_DISK_COUNT: len(self.disks),
      constants.ISPEC_DISK_SIZE: [disk[constants.IDISK_SIZE]
                                  for disk in self.disks],
      constants.ISPEC_NIC_COUNT: len(self.nics),
      constants.ISPEC_SPINDLE_USE: spindle_use,
      }

    group_info = self.cfg.GetNodeGroup(pnode.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    res = _ComputeIPolicyInstanceSpecViolation(ipolicy, ispec,
                                               self.op.disk_template)
    if not self.op.ignore_ipolicy and res:
      msg = ("Instance allocation to group %s (%s) violates policy: %s" %
             (pnode.group, group_info.name, utils.CommaJoin(res)))
      raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

    _CheckHVParams(self, nodenames, self.op.hypervisor, self.op.hvparams)

    _CheckNodeHasOS(self, pnode.name, self.op.os_type, self.op.force_variant)
    # check OS parameters (remotely)
    _CheckOSParams(self, True, nodenames, self.op.os_type, self.os_full)

    _CheckNicsBridgesExist(self, self.nics, self.pnode.name)

    #TODO: _CheckExtParams (remotely)
    # Check parameters for extstorage

    # memory check on primary node
    #TODO(dynmem): use MINMEM for checking
    if self.op.start:
      _CheckNodeFreeMemory(self, self.pnode.name,
                           "creating instance %s" % self.op.instance_name,
                           self.be_full[constants.BE_MAXMEM],
                           self.op.hypervisor)

    self.dry_run_result = list(nodenames)

  def Exec(self, feedback_fn):
    """Create and add the instance to the cluster.

    """
    instance = self.op.instance_name
    pnode_name = self.pnode.name

    assert not (self.owned_locks(locking.LEVEL_NODE_RES) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Node locks differ from node resource locks"
    assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

    ht_kind = self.op.hypervisor
    if ht_kind in constants.HTS_REQ_PORT:
      network_port = self.cfg.AllocatePort()
    else:
      network_port = None

    # This is ugly but we got a chicken-egg problem here
    # We can only take the group disk parameters, as the instance
    # has no disks yet (we are generating them right here).
    node = self.cfg.GetNodeInfo(pnode_name)
    nodegroup = self.cfg.GetNodeGroup(node.group)
    disks = _GenerateDiskTemplate(self,
                                  self.op.disk_template,
                                  instance, pnode_name,
                                  self.secondaries,
                                  self.disks,
                                  self.instance_file_storage_dir,
                                  self.op.file_driver,
                                  0,
                                  feedback_fn,
                                  self.cfg.GetGroupDiskParams(nodegroup))

    iobj = objects.Instance(name=instance, os=self.op.os_type,
                            primary_node=pnode_name,
                            nics=self.nics, disks=disks,
                            disk_template=self.op.disk_template,
                            admin_state=constants.ADMINST_DOWN,
                            network_port=network_port,
                            beparams=self.op.beparams,
                            hvparams=self.op.hvparams,
                            hypervisor=self.op.hypervisor,
                            osparams=self.op.osparams,
                            )

    if self.op.tags:
      for tag in self.op.tags:
        iobj.AddTag(tag)

    if self.adopt_disks:
      if self.op.disk_template == constants.DT_PLAIN:
        # rename LVs to the newly-generated names; we need to construct
        # 'fake' LV disks with the old data, plus the new unique_id
        tmp_disks = [objects.Disk.FromDict(v.ToDict()) for v in disks]
        rename_to = []
        for t_dsk, a_dsk in zip(tmp_disks, self.disks):
          rename_to.append(t_dsk.logical_id)
          t_dsk.logical_id = (t_dsk.logical_id[0], a_dsk[constants.IDISK_ADOPT])
          self.cfg.SetDiskID(t_dsk, pnode_name)
        result = self.rpc.call_blockdev_rename(pnode_name,
                                               zip(tmp_disks, rename_to))
        result.Raise("Failed to rename adoped LVs")
    else:
      feedback_fn("* creating instance disks...")
      try:
        _CreateDisks(self, iobj)
      except errors.OpExecError:
        self.LogWarning("Device creation failed")
        self.cfg.ReleaseDRBDMinors(instance)
        raise

    feedback_fn("adding instance %s to cluster config" % instance)

    self.cfg.AddInstance(iobj, self.proc.GetECId())

    # Declare that we don't want to remove the instance lock anymore, as we've
    # added the instance to the config
    del self.remove_locks[locking.LEVEL_INSTANCE]

    if self.op.mode == constants.INSTANCE_IMPORT:
      # Release unused nodes
      _ReleaseLocks(self, locking.LEVEL_NODE, keep=[self.op.src_node])
    else:
      # Release all nodes
      _ReleaseLocks(self, locking.LEVEL_NODE)

    disk_abort = False
    if not self.adopt_disks and self.cfg.GetClusterInfo().prealloc_wipe_disks:
      feedback_fn("* wiping instance disks...")
      try:
        _WipeDisks(self, iobj)
      except errors.OpExecError, err:
        logging.exception("Wiping disks failed")
        self.LogWarning("Wiping instance disks failed (%s)", err)
        disk_abort = True

    if disk_abort:
      # Something is already wrong with the disks, don't do anything else
      pass
    elif self.op.wait_for_sync:
      disk_abort = not _WaitForSync(self, iobj)
    elif iobj.disk_template in constants.DTS_INT_MIRROR:
      # make sure the disks are not degraded (still sync-ing is ok)
      feedback_fn("* checking mirrors status")
      disk_abort = not _WaitForSync(self, iobj, oneshot=True)
    else:
      disk_abort = False

    if disk_abort:
      _RemoveDisks(self, iobj)
      self.cfg.RemoveInstance(iobj.name)
      # Make sure the instance lock gets removed
      self.remove_locks[locking.LEVEL_INSTANCE] = iobj.name
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance")

    # Release all node resource locks
    _ReleaseLocks(self, locking.LEVEL_NODE_RES)

    if iobj.disk_template != constants.DT_DISKLESS and not self.adopt_disks:
      # we need to set the disks ID to the primary node, since the
      # preceding code might or might have not done it, depending on
      # disk template and other options
      for disk in iobj.disks:
        self.cfg.SetDiskID(disk, pnode_name)
      if self.op.mode == constants.INSTANCE_CREATE:
        if not self.op.no_install:
          pause_sync = (iobj.disk_template in constants.DTS_INT_MIRROR and
                        not self.op.wait_for_sync)
          if pause_sync:
            feedback_fn("* pausing disk sync to install instance OS")
            result = self.rpc.call_blockdev_pause_resume_sync(pnode_name,
                                                              (iobj.disks,
                                                               iobj), True)
            for idx, success in enumerate(result.payload):
              if not success:
                logging.warn("pause-sync of instance %s for disk %d failed",
                             instance, idx)

          feedback_fn("* running the instance OS create scripts...")
          # FIXME: pass debug option from opcode to backend
          os_add_result = \
            self.rpc.call_instance_os_add(pnode_name, (iobj, None), False,
                                          self.op.debug_level)
          if pause_sync:
            feedback_fn("* resuming disk sync")
            result = self.rpc.call_blockdev_pause_resume_sync(pnode_name,
                                                              (iobj.disks,
                                                               iobj), False)
            for idx, success in enumerate(result.payload):
              if not success:
                logging.warn("resume-sync of instance %s for disk %d failed",
                             instance, idx)

          os_add_result.Raise("Could not add os for instance %s"
                              " on node %s" % (instance, pnode_name))

      else:
        if self.op.mode == constants.INSTANCE_IMPORT:
          feedback_fn("* running the instance OS import scripts...")

          transfers = []

          for idx, image in enumerate(self.src_images):
            if not image:
              continue

            # FIXME: pass debug option from opcode to backend
            dt = masterd.instance.DiskTransfer("disk/%s" % idx,
                                               constants.IEIO_FILE, (image, ),
                                               constants.IEIO_SCRIPT,
                                               (iobj.disks[idx], idx),
                                               None)
            transfers.append(dt)

          import_result = \
            masterd.instance.TransferInstanceData(self, feedback_fn,
                                                  self.op.src_node, pnode_name,
                                                  self.pnode.secondary_ip,
                                                  iobj, transfers)
          if not compat.all(import_result):
            self.LogWarning("Some disks for instance %s on node %s were not"
                            " imported successfully" % (instance, pnode_name))

          rename_from = self._old_instance_name

        elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
          feedback_fn("* preparing remote import...")
          # The source cluster will stop the instance before attempting to make
          # a connection. In some cases stopping an instance can take a long
          # time, hence the shutdown timeout is added to the connection
          # timeout.
          connect_timeout = (constants.RIE_CONNECT_TIMEOUT +
                             self.op.source_shutdown_timeout)
          timeouts = masterd.instance.ImportExportTimeouts(connect_timeout)

          assert iobj.primary_node == self.pnode.name
          disk_results = \
            masterd.instance.RemoteImport(self, feedback_fn, iobj, self.pnode,
                                          self.source_x509_ca,
                                          self._cds, timeouts)
          if not compat.all(disk_results):
            # TODO: Should the instance still be started, even if some disks
            # failed to import (valid for local imports, too)?
            self.LogWarning("Some disks for instance %s on node %s were not"
                            " imported successfully" % (instance, pnode_name))

          rename_from = self.source_instance_name

        else:
          # also checked in the prereq part
          raise errors.ProgrammerError("Unknown OS initialization mode '%s'"
                                       % self.op.mode)

        # Run rename script on newly imported instance
        assert iobj.name == instance
        feedback_fn("Running rename script for %s" % instance)
        result = self.rpc.call_instance_run_rename(pnode_name, iobj,
                                                   rename_from,
                                                   self.op.debug_level)
        if result.fail_msg:
          self.LogWarning("Failed to run rename script for %s on node"
                          " %s: %s" % (instance, pnode_name, result.fail_msg))

    assert not self.owned_locks(locking.LEVEL_NODE_RES)

    if self.op.start:
      iobj.admin_state = constants.ADMINST_UP
      self.cfg.Update(iobj, feedback_fn)
      logging.info("Starting instance %s on node %s", instance, pnode_name)
      feedback_fn("* starting instance...")
      result = self.rpc.call_instance_start(pnode_name, (iobj, None, None),
                                            False)
      result.Raise("Could not start instance")

    return list(iobj.all_nodes)


class LUInstanceMultiAlloc(NoHooksLU):
  """Allocates multiple instances at the same time.

  """
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    nodes = []
    for inst in self.op.instances:
      if inst.iallocator is not None:
        raise errors.OpPrereqError("iallocator are not allowed to be set on"
                                   " instance objects", errors.ECODE_INVAL)
      nodes.append(bool(inst.pnode))
      if inst.disk_template in constants.DTS_INT_MIRROR:
        nodes.append(bool(inst.snode))

    has_nodes = compat.any(nodes)
    if compat.all(nodes) ^ has_nodes:
      raise errors.OpPrereqError("There are instance objects providing"
                                 " pnode/snode while others do not",
                                 errors.ECODE_INVAL)

    if self.op.iallocator is None:
      default_iallocator = self.cfg.GetDefaultIAllocator()
      if default_iallocator and has_nodes:
        self.op.iallocator = default_iallocator
      else:
        raise errors.OpPrereqError("No iallocator or nodes on the instances"
                                   " given and no cluster-wide default"
                                   " iallocator found; please specify either"
                                   " an iallocator or nodes on the instances"
                                   " or set a cluster-wide default iallocator",
                                   errors.ECODE_INVAL)

    _CheckOpportunisticLocking(self.op)

    dups = utils.FindDuplicates([op.instance_name for op in self.op.instances])
    if dups:
      raise errors.OpPrereqError("There are duplicate instance names: %s" %
                                 utils.CommaJoin(dups), errors.ECODE_INVAL)

  def ExpandNames(self):
    """Calculate the locks.

    """
    self.share_locks = _ShareAll()
    self.needed_locks = {
      # iallocator will select nodes and even if no iallocator is used,
      # collisions with LUInstanceCreate should be avoided
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    if self.op.iallocator:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
      self.needed_locks[locking.LEVEL_NODE_RES] = locking.ALL_SET

      if self.op.opportunistic_locking:
        self.opportunistic_locks[locking.LEVEL_NODE] = True
        self.opportunistic_locks[locking.LEVEL_NODE_RES] = True
    else:
      nodeslist = []
      for inst in self.op.instances:
        inst.pnode = _ExpandNodeName(self.cfg, inst.pnode)
        nodeslist.append(inst.pnode)
        if inst.snode is not None:
          inst.snode = _ExpandNodeName(self.cfg, inst.snode)
          nodeslist.append(inst.snode)

      self.needed_locks[locking.LEVEL_NODE] = nodeslist
      # Lock resources of instance's primary and secondary nodes (copy to
      # prevent accidential modification)
      self.needed_locks[locking.LEVEL_NODE_RES] = list(nodeslist)

  def CheckPrereq(self):
    """Check prerequisite.

    """
    cluster = self.cfg.GetClusterInfo()
    default_vg = self.cfg.GetVGName()
    ec_id = self.proc.GetECId()

    if self.op.opportunistic_locking:
      # Only consider nodes for which a lock is held
      node_whitelist = list(self.owned_locks(locking.LEVEL_NODE))
    else:
      node_whitelist = None

    insts = [_CreateInstanceAllocRequest(op, _ComputeDisks(op, default_vg),
                                         _ComputeNics(op, cluster, None,
                                                      self.cfg, ec_id),
                                         _ComputeFullBeParams(op, cluster),
                                         node_whitelist)
             for op in self.op.instances]

    req = iallocator.IAReqMultiInstanceAlloc(instances=insts)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)

    self.ia_result = ial.result

    if self.op.dry_run:
      self.dry_run_result = objects.FillDict(self._ConstructPartialResult(), {
        constants.JOB_IDS_KEY: [],
        })

  def _ConstructPartialResult(self):
    """Contructs the partial result.

    """
    (allocatable, failed) = self.ia_result
    return {
      opcodes.OpInstanceMultiAlloc.ALLOCATABLE_KEY:
        map(compat.fst, allocatable),
      opcodes.OpInstanceMultiAlloc.FAILED_KEY: failed,
      }

  def Exec(self, feedback_fn):
    """Executes the opcode.

    """
    op2inst = dict((op.instance_name, op) for op in self.op.instances)
    (allocatable, failed) = self.ia_result

    jobs = []
    for (name, nodes) in allocatable:
      op = op2inst.pop(name)

      if len(nodes) > 1:
        (op.pnode, op.snode) = nodes
      else:
        (op.pnode,) = nodes

      jobs.append([op])

    missing = set(op2inst.keys()) - set(failed)
    assert not missing, \
      "Iallocator did return incomplete result: %s" % utils.CommaJoin(missing)

    return ResultWithJobs(jobs, **self._ConstructPartialResult())


def _CheckRADOSFreeSpace():
  """Compute disk size requirements inside the RADOS cluster.

  """
  # For the RADOS cluster we assume there is always enough space.
  pass


class LUInstanceConsole(NoHooksLU):
  """Connect to an instance's console.

  This is somewhat special in that it returns the command line that
  you need to run on the master node in order to connect to the
  console.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = _ShareAll()
    self._ExpandAndLockInstance()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Connect to the console of an instance

    """
    instance = self.instance
    node = instance.primary_node

    node_insts = self.rpc.call_instance_list([node],
                                             [instance.hypervisor])[node]
    node_insts.Raise("Can't get node information from %s" % node)

    if instance.name not in node_insts.payload:
      if instance.admin_state == constants.ADMINST_UP:
        state = constants.INSTST_ERRORDOWN
      elif instance.admin_state == constants.ADMINST_DOWN:
        state = constants.INSTST_ADMINDOWN
      else:
        state = constants.INSTST_ADMINOFFLINE
      raise errors.OpExecError("Instance %s is not running (state %s)" %
                               (instance.name, state))

    logging.debug("Connecting to console of %s on %s", instance.name, node)

    return _GetInstanceConsole(self.cfg.GetClusterInfo(), instance)


def _GetInstanceConsole(cluster, instance):
  """Returns console information for an instance.

  @type cluster: L{objects.Cluster}
  @type instance: L{objects.Instance}
  @rtype: dict

  """
  hyper = hypervisor.GetHypervisorClass(instance.hypervisor)
  # beparams and hvparams are passed separately, to avoid editing the
  # instance and then saving the defaults in the instance itself.
  hvparams = cluster.FillHV(instance)
  beparams = cluster.FillBE(instance)
  console = hyper.GetInstanceConsole(instance, hvparams, beparams)

  assert console.instance == instance.name
  assert console.Validate()

  return console.ToDict()


class LUInstanceReplaceDisks(LogicalUnit):
  """Replace the disks of an instance.

  """
  HPATH = "mirrors-replace"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    remote_node = self.op.remote_node
    ialloc = self.op.iallocator
    if self.op.mode == constants.REPLACE_DISK_CHG:
      if remote_node is None and ialloc is None:
        raise errors.OpPrereqError("When changing the secondary either an"
                                   " iallocator script must be used or the"
                                   " new node given", errors.ECODE_INVAL)
      else:
        _CheckIAllocatorOrNode(self, "iallocator", "remote_node")

    elif remote_node is not None or ialloc is not None:
      # Not replacing the secondary
      raise errors.OpPrereqError("The iallocator and new node options can"
                                 " only be used when changing the"
                                 " secondary node", errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    assert locking.LEVEL_NODE not in self.needed_locks
    assert locking.LEVEL_NODE_RES not in self.needed_locks
    assert locking.LEVEL_NODEGROUP not in self.needed_locks

    assert self.op.iallocator is None or self.op.remote_node is None, \
      "Conflicting options"

    if self.op.remote_node is not None:
      self.op.remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)

      # Warning: do not remove the locking of the new secondary here
      # unless DRBD8.AddChildren is changed to work in parallel;
      # currently it doesn't since parallel invocations of
      # FindUnusedMinor will conflict
      self.needed_locks[locking.LEVEL_NODE] = [self.op.remote_node]
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
    else:
      self.needed_locks[locking.LEVEL_NODE] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

      if self.op.iallocator is not None:
        # iallocator will select a new node in the same group
        self.needed_locks[locking.LEVEL_NODEGROUP] = []
        self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

    self.needed_locks[locking.LEVEL_NODE_RES] = []

    self.replacer = TLReplaceDisks(self, self.op.instance_name, self.op.mode,
                                   self.op.iallocator, self.op.remote_node,
                                   self.op.disks, self.op.early_release,
                                   self.op.ignore_ipolicy)

    self.tasklets = [self.replacer]

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert self.op.remote_node is None
      assert self.op.iallocator is not None
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      self.share_locks[locking.LEVEL_NODEGROUP] = 1
      # Lock all groups used by instance optimistically; this requires going
      # via the node before it's locked, requiring verification later on
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetInstanceNodeGroups(self.op.instance_name)

    elif level == locking.LEVEL_NODE:
      if self.op.iallocator is not None:
        assert self.op.remote_node is None
        assert not self.needed_locks[locking.LEVEL_NODE]
        assert locking.NAL in self.owned_locks(locking.LEVEL_NODE_ALLOC)

        # Lock member nodes of all locked groups
        self.needed_locks[locking.LEVEL_NODE] = \
            [node_name
             for group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)
             for node_name in self.cfg.GetNodeGroup(group_uuid).members]
      else:
        assert not self.glm.is_owned(locking.LEVEL_NODE_ALLOC)

        self._LockInstancesNodes()

    elif level == locking.LEVEL_NODE_RES:
      # Reuse node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        self.needed_locks[locking.LEVEL_NODE]

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    instance = self.replacer.instance
    env = {
      "MODE": self.op.mode,
      "NEW_SECONDARY": self.op.remote_node,
      "OLD_SECONDARY": instance.secondary_nodes[0],
      }
    env.update(_BuildInstanceHookEnvByObject(self, instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self.replacer.instance
    nl = [
      self.cfg.GetMasterNode(),
      instance.primary_node,
      ]
    if self.op.remote_node is not None:
      nl.append(self.op.remote_node)
    return nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    """
    assert (self.glm.is_owned(locking.LEVEL_NODEGROUP) or
            self.op.iallocator is None)

    # Verify if node group locks are still correct
    owned_groups = self.owned_locks(locking.LEVEL_NODEGROUP)
    if owned_groups:
      _CheckInstanceNodeGroups(self.cfg, self.op.instance_name, owned_groups)

    return LogicalUnit.CheckPrereq(self)


class TLReplaceDisks(Tasklet):
  """Replaces disks for an instance.

  Note: Locking is not within the scope of this class.

  """
  def __init__(self, lu, instance_name, mode, iallocator_name, remote_node,
               disks, early_release, ignore_ipolicy):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_name = instance_name
    self.mode = mode
    self.iallocator_name = iallocator_name
    self.remote_node = remote_node
    self.disks = disks
    self.early_release = early_release
    self.ignore_ipolicy = ignore_ipolicy

    # Runtime data
    self.instance = None
    self.new_node = None
    self.target_node = None
    self.other_node = None
    self.remote_node_info = None
    self.node_secondary_ip = None

  @staticmethod
  def _RunAllocator(lu, iallocator_name, instance_name, relocate_from):
    """Compute a new secondary node using an IAllocator.

    """
    req = iallocator.IAReqRelocate(name=instance_name,
                                   relocate_from=list(relocate_from))
    ial = iallocator.IAllocator(lu.cfg, lu.rpc, req)

    ial.Run(iallocator_name)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using iallocator '%s':"
                                 " %s" % (iallocator_name, ial.info),
                                 errors.ECODE_NORES)

    remote_node_name = ial.result[0]

    lu.LogInfo("Selected new secondary for instance '%s': %s",
               instance_name, remote_node_name)

    return remote_node_name

  def _FindFaultyDisks(self, node_name):
    """Wrapper for L{_FindFaultyInstanceDisks}.

    """
    return _FindFaultyInstanceDisks(self.cfg, self.rpc, self.instance,
                                    node_name, True)

  def _CheckDisksActivated(self, instance):
    """Checks if the instance disks are activated.

    @param instance: The instance to check disks
    @return: True if they are activated, False otherwise

    """
    nodes = instance.all_nodes

    for idx, dev in enumerate(instance.disks):
      for node in nodes:
        self.lu.LogInfo("Checking disk/%d on %s", idx, node)
        self.cfg.SetDiskID(dev, node)

        result = _BlockdevFind(self, node, dev, instance)

        if result.offline:
          continue
        elif result.fail_msg or not result.payload:
          return False

    return True

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.instance_name

    if instance.disk_template != constants.DT_DRBD8:
      raise errors.OpPrereqError("Can only run replace disks for DRBD8-based"
                                 " instances", errors.ECODE_INVAL)

    if len(instance.secondary_nodes) != 1:
      raise errors.OpPrereqError("The instance has a strange layout,"
                                 " expected one secondary but found %d" %
                                 len(instance.secondary_nodes),
                                 errors.ECODE_FAULT)

    instance = self.instance
    secondary_node = instance.secondary_nodes[0]

    if self.iallocator_name is None:
      remote_node = self.remote_node
    else:
      remote_node = self._RunAllocator(self.lu, self.iallocator_name,
                                       instance.name, instance.secondary_nodes)

    if remote_node is None:
      self.remote_node_info = None
    else:
      assert remote_node in self.lu.owned_locks(locking.LEVEL_NODE), \
             "Remote node '%s' is not locked" % remote_node

      self.remote_node_info = self.cfg.GetNodeInfo(remote_node)
      assert self.remote_node_info is not None, \
        "Cannot retrieve locked node %s" % remote_node

    if remote_node == self.instance.primary_node:
      raise errors.OpPrereqError("The specified node is the primary node of"
                                 " the instance", errors.ECODE_INVAL)

    if remote_node == secondary_node:
      raise errors.OpPrereqError("The specified node is already the"
                                 " secondary node of the instance",
                                 errors.ECODE_INVAL)

    if self.disks and self.mode in (constants.REPLACE_DISK_AUTO,
                                    constants.REPLACE_DISK_CHG):
      raise errors.OpPrereqError("Cannot specify disks to be replaced",
                                 errors.ECODE_INVAL)

    if self.mode == constants.REPLACE_DISK_AUTO:
      if not self._CheckDisksActivated(instance):
        raise errors.OpPrereqError("Please run activate-disks on instance %s"
                                   " first" % self.instance_name,
                                   errors.ECODE_STATE)
      faulty_primary = self._FindFaultyDisks(instance.primary_node)
      faulty_secondary = self._FindFaultyDisks(secondary_node)

      if faulty_primary and faulty_secondary:
        raise errors.OpPrereqError("Instance %s has faulty disks on more than"
                                   " one node and can not be repaired"
                                   " automatically" % self.instance_name,
                                   errors.ECODE_STATE)

      if faulty_primary:
        self.disks = faulty_primary
        self.target_node = instance.primary_node
        self.other_node = secondary_node
        check_nodes = [self.target_node, self.other_node]
      elif faulty_secondary:
        self.disks = faulty_secondary
        self.target_node = secondary_node
        self.other_node = instance.primary_node
        check_nodes = [self.target_node, self.other_node]
      else:
        self.disks = []
        check_nodes = []

    else:
      # Non-automatic modes
      if self.mode == constants.REPLACE_DISK_PRI:
        self.target_node = instance.primary_node
        self.other_node = secondary_node
        check_nodes = [self.target_node, self.other_node]

      elif self.mode == constants.REPLACE_DISK_SEC:
        self.target_node = secondary_node
        self.other_node = instance.primary_node
        check_nodes = [self.target_node, self.other_node]

      elif self.mode == constants.REPLACE_DISK_CHG:
        self.new_node = remote_node
        self.other_node = instance.primary_node
        self.target_node = secondary_node
        check_nodes = [self.new_node, self.other_node]

        _CheckNodeNotDrained(self.lu, remote_node)
        _CheckNodeVmCapable(self.lu, remote_node)

        old_node_info = self.cfg.GetNodeInfo(secondary_node)
        assert old_node_info is not None
        if old_node_info.offline and not self.early_release:
          # doesn't make sense to delay the release
          self.early_release = True
          self.lu.LogInfo("Old secondary %s is offline, automatically enabling"
                          " early-release mode", secondary_node)

      else:
        raise errors.ProgrammerError("Unhandled disk replace mode (%s)" %
                                     self.mode)

      # If not specified all disks should be replaced
      if not self.disks:
        self.disks = range(len(self.instance.disks))

    # TODO: This is ugly, but right now we can't distinguish between internal
    # submitted opcode and external one. We should fix that.
    if self.remote_node_info:
      # We change the node, lets verify it still meets instance policy
      new_group_info = self.cfg.GetNodeGroup(self.remote_node_info.group)
      cluster = self.cfg.GetClusterInfo()
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              new_group_info)
      _CheckTargetNodeIPolicy(self, ipolicy, instance, self.remote_node_info,
                              self.cfg, ignore=self.ignore_ipolicy)

    for node in check_nodes:
      _CheckNodeOnline(self.lu, node)

    touched_nodes = frozenset(node_name for node_name in [self.new_node,
                                                          self.other_node,
                                                          self.target_node]
                              if node_name is not None)

    # Release unneeded node and node resource locks
    _ReleaseLocks(self.lu, locking.LEVEL_NODE, keep=touched_nodes)
    _ReleaseLocks(self.lu, locking.LEVEL_NODE_RES, keep=touched_nodes)
    _ReleaseLocks(self.lu, locking.LEVEL_NODE_ALLOC)

    # Release any owned node group
    _ReleaseLocks(self.lu, locking.LEVEL_NODEGROUP)

    # Check whether disks are valid
    for disk_idx in self.disks:
      instance.FindDisk(disk_idx)

    # Get secondary node IP addresses
    self.node_secondary_ip = dict((name, node.secondary_ip) for (name, node)
                                  in self.cfg.GetMultiNodeInfo(touched_nodes))

  def Exec(self, feedback_fn):
    """Execute disk replacement.

    This dispatches the disk replacement to the appropriate handler.

    """
    if __debug__:
      # Verify owned locks before starting operation
      owned_nodes = self.lu.owned_locks(locking.LEVEL_NODE)
      assert set(owned_nodes) == set(self.node_secondary_ip), \
          ("Incorrect node locks, owning %s, expected %s" %
           (owned_nodes, self.node_secondary_ip.keys()))
      assert (self.lu.owned_locks(locking.LEVEL_NODE) ==
              self.lu.owned_locks(locking.LEVEL_NODE_RES))
      assert not self.lu.glm.is_owned(locking.LEVEL_NODE_ALLOC)

      owned_instances = self.lu.owned_locks(locking.LEVEL_INSTANCE)
      assert list(owned_instances) == [self.instance_name], \
          "Instance '%s' not locked" % self.instance_name

      assert not self.lu.glm.is_owned(locking.LEVEL_NODEGROUP), \
          "Should not own any node group lock at this point"

    if not self.disks:
      feedback_fn("No disks need replacement for instance '%s'" %
                  self.instance.name)
      return

    feedback_fn("Replacing disk(s) %s for instance '%s'" %
                (utils.CommaJoin(self.disks), self.instance.name))
    feedback_fn("Current primary node: %s" % self.instance.primary_node)
    feedback_fn("Current seconary node: %s" %
                utils.CommaJoin(self.instance.secondary_nodes))

    activate_disks = (self.instance.admin_state != constants.ADMINST_UP)

    # Activate the instance disks if we're replacing them on a down instance
    if activate_disks:
      _StartInstanceDisks(self.lu, self.instance, True)

    try:
      # Should we replace the secondary node?
      if self.new_node is not None:
        fn = self._ExecDrbd8Secondary
      else:
        fn = self._ExecDrbd8DiskOnly

      result = fn(feedback_fn)
    finally:
      # Deactivate the instance disks if we're replacing them on a
      # down instance
      if activate_disks:
        _SafeShutdownInstanceDisks(self.lu, self.instance)

    assert not self.lu.owned_locks(locking.LEVEL_NODE)

    if __debug__:
      # Verify owned locks
      owned_nodes = self.lu.owned_locks(locking.LEVEL_NODE_RES)
      nodes = frozenset(self.node_secondary_ip)
      assert ((self.early_release and not owned_nodes) or
              (not self.early_release and not (set(owned_nodes) - nodes))), \
        ("Not owning the correct locks, early_release=%s, owned=%r,"
         " nodes=%r" % (self.early_release, owned_nodes, nodes))

    return result

  def _CheckVolumeGroup(self, nodes):
    self.lu.LogInfo("Checking volume groups")

    vgname = self.cfg.GetVGName()

    # Make sure volume group exists on all involved nodes
    results = self.rpc.call_vg_list(nodes)
    if not results:
      raise errors.OpExecError("Can't list volume groups on the nodes")

    for node in nodes:
      res = results[node]
      res.Raise("Error checking node %s" % node)
      if vgname not in res.payload:
        raise errors.OpExecError("Volume group '%s' not found on node %s" %
                                 (vgname, node))

  def _CheckDisksExistence(self, nodes):
    # Check disk existence
    for idx, dev in enumerate(self.instance.disks):
      if idx not in self.disks:
        continue

      for node in nodes:
        self.lu.LogInfo("Checking disk/%d on %s", idx, node)
        self.cfg.SetDiskID(dev, node)

        result = _BlockdevFind(self, node, dev, self.instance)

        msg = result.fail_msg
        if msg or not result.payload:
          if not msg:
            msg = "disk not found"
          raise errors.OpExecError("Can't find disk/%d on node %s: %s" %
                                   (idx, node, msg))

  def _CheckDisksConsistency(self, node_name, on_primary, ldisk):
    for idx, dev in enumerate(self.instance.disks):
      if idx not in self.disks:
        continue

      self.lu.LogInfo("Checking disk/%d consistency on node %s" %
                      (idx, node_name))

      if not _CheckDiskConsistency(self.lu, self.instance, dev, node_name,
                                   on_primary, ldisk=ldisk):
        raise errors.OpExecError("Node %s has degraded storage, unsafe to"
                                 " replace disks for instance %s" %
                                 (node_name, self.instance.name))

  def _CreateNewStorage(self, node_name):
    """Create new storage on the primary or secondary node.

    This is only used for same-node replaces, not for changing the
    secondary node, hence we don't want to modify the existing disk.

    """
    iv_names = {}

    disks = _AnnotateDiskParams(self.instance, self.instance.disks, self.cfg)
    for idx, dev in enumerate(disks):
      if idx not in self.disks:
        continue

      self.lu.LogInfo("Adding storage on %s for disk/%d", node_name, idx)

      self.cfg.SetDiskID(dev, node_name)

      lv_names = [".disk%d_%s" % (idx, suffix) for suffix in ["data", "meta"]]
      names = _GenerateUniqueNames(self.lu, lv_names)

      (data_disk, meta_disk) = dev.children
      vg_data = data_disk.logical_id[0]
      lv_data = objects.Disk(dev_type=constants.LD_LV, size=dev.size,
                             logical_id=(vg_data, names[0]),
                             params=data_disk.params)
      vg_meta = meta_disk.logical_id[0]
      lv_meta = objects.Disk(dev_type=constants.LD_LV,
                             size=constants.DRBD_META_SIZE,
                             logical_id=(vg_meta, names[1]),
                             params=meta_disk.params)

      new_lvs = [lv_data, lv_meta]
      old_lvs = [child.Copy() for child in dev.children]
      iv_names[dev.iv_name] = (dev, old_lvs, new_lvs)
      excl_stor = _IsExclusiveStorageEnabledNodeName(self.lu.cfg, node_name)

      # we pass force_create=True to force the LVM creation
      for new_lv in new_lvs:
        _CreateBlockDevInner(self.lu, node_name, self.instance, new_lv, True,
                             _GetInstanceInfoText(self.instance), False,
                             excl_stor)

    return iv_names

  def _CheckDevices(self, node_name, iv_names):
    for name, (dev, _, _) in iv_names.iteritems():
      self.cfg.SetDiskID(dev, node_name)

      result = _BlockdevFind(self, node_name, dev, self.instance)

      msg = result.fail_msg
      if msg or not result.payload:
        if not msg:
          msg = "disk not found"
        raise errors.OpExecError("Can't find DRBD device %s: %s" %
                                 (name, msg))

      if result.payload.is_degraded:
        raise errors.OpExecError("DRBD device %s is degraded!" % name)

  def _RemoveOldStorage(self, node_name, iv_names):
    for name, (_, old_lvs, _) in iv_names.iteritems():
      self.lu.LogInfo("Remove logical volumes for %s", name)

      for lv in old_lvs:
        self.cfg.SetDiskID(lv, node_name)

        msg = self.rpc.call_blockdev_remove(node_name, lv).fail_msg
        if msg:
          self.lu.LogWarning("Can't remove old LV: %s", msg,
                             hint="remove unused LVs manually")

  def _ExecDrbd8DiskOnly(self, feedback_fn): # pylint: disable=W0613
    """Replace a disk on the primary or secondary for DRBD 8.

    The algorithm for replace is quite complicated:

      1. for each disk to be replaced:

        1. create new LVs on the target node with unique names
        1. detach old LVs from the drbd device
        1. rename old LVs to name_replaced.<time_t>
        1. rename new LVs to old LVs
        1. attach the new LVs (with the old names now) to the drbd device

      1. wait for sync across all devices

      1. for each modified disk:

        1. remove old LVs (which have the name name_replaces.<time_t>)

    Failures are not very well handled.

    """
    steps_total = 6

    # Step: check device activation
    self.lu.LogStep(1, steps_total, "Check device existence")
    self._CheckDisksExistence([self.other_node, self.target_node])
    self._CheckVolumeGroup([self.target_node, self.other_node])

    # Step: check other node consistency
    self.lu.LogStep(2, steps_total, "Check peer consistency")
    self._CheckDisksConsistency(self.other_node,
                                self.other_node == self.instance.primary_node,
                                False)

    # Step: create new storage
    self.lu.LogStep(3, steps_total, "Allocate new storage")
    iv_names = self._CreateNewStorage(self.target_node)

    # Step: for each lv, detach+rename*2+attach
    self.lu.LogStep(4, steps_total, "Changing drbd configuration")
    for dev, old_lvs, new_lvs in iv_names.itervalues():
      self.lu.LogInfo("Detaching %s drbd from local storage", dev.iv_name)

      result = self.rpc.call_blockdev_removechildren(self.target_node, dev,
                                                     old_lvs)
      result.Raise("Can't detach drbd from local storage on node"
                   " %s for device %s" % (self.target_node, dev.iv_name))
      #dev.children = []
      #cfg.Update(instance)

      # ok, we created the new LVs, so now we know we have the needed
      # storage; as such, we proceed on the target node to rename
      # old_lv to _old, and new_lv to old_lv; note that we rename LVs
      # using the assumption that logical_id == physical_id (which in
      # turn is the unique_id on that node)

      # FIXME(iustin): use a better name for the replaced LVs
      temp_suffix = int(time.time())
      ren_fn = lambda d, suff: (d.physical_id[0],
                                d.physical_id[1] + "_replaced-%s" % suff)

      # Build the rename list based on what LVs exist on the node
      rename_old_to_new = []
      for to_ren in old_lvs:
        result = self.rpc.call_blockdev_find(self.target_node, to_ren)
        if not result.fail_msg and result.payload:
          # device exists
          rename_old_to_new.append((to_ren, ren_fn(to_ren, temp_suffix)))

      self.lu.LogInfo("Renaming the old LVs on the target node")
      result = self.rpc.call_blockdev_rename(self.target_node,
                                             rename_old_to_new)
      result.Raise("Can't rename old LVs on node %s" % self.target_node)

      # Now we rename the new LVs to the old LVs
      self.lu.LogInfo("Renaming the new LVs on the target node")
      rename_new_to_old = [(new, old.physical_id)
                           for old, new in zip(old_lvs, new_lvs)]
      result = self.rpc.call_blockdev_rename(self.target_node,
                                             rename_new_to_old)
      result.Raise("Can't rename new LVs on node %s" % self.target_node)

      # Intermediate steps of in memory modifications
      for old, new in zip(old_lvs, new_lvs):
        new.logical_id = old.logical_id
        self.cfg.SetDiskID(new, self.target_node)

      # We need to modify old_lvs so that removal later removes the
      # right LVs, not the newly added ones; note that old_lvs is a
      # copy here
      for disk in old_lvs:
        disk.logical_id = ren_fn(disk, temp_suffix)
        self.cfg.SetDiskID(disk, self.target_node)

      # Now that the new lvs have the old name, we can add them to the device
      self.lu.LogInfo("Adding new mirror component on %s", self.target_node)
      result = self.rpc.call_blockdev_addchildren(self.target_node,
                                                  (dev, self.instance), new_lvs)
      msg = result.fail_msg
      if msg:
        for new_lv in new_lvs:
          msg2 = self.rpc.call_blockdev_remove(self.target_node,
                                               new_lv).fail_msg
          if msg2:
            self.lu.LogWarning("Can't rollback device %s: %s", dev, msg2,
                               hint=("cleanup manually the unused logical"
                                     "volumes"))
        raise errors.OpExecError("Can't add local storage to drbd: %s" % msg)

    cstep = itertools.count(5)

    if self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node, iv_names)
      # TODO: Check if releasing locks early still makes sense
      _ReleaseLocks(self.lu, locking.LEVEL_NODE_RES)
    else:
      # Release all resource locks except those used by the instance
      _ReleaseLocks(self.lu, locking.LEVEL_NODE_RES,
                    keep=self.node_secondary_ip.keys())

    # Release all node locks while waiting for sync
    _ReleaseLocks(self.lu, locking.LEVEL_NODE)

    # TODO: Can the instance lock be downgraded here? Take the optional disk
    # shutdown in the caller into consideration.

    # Wait for sync
    # This can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its return value
    self.lu.LogStep(cstep.next(), steps_total, "Sync devices")
    _WaitForSync(self.lu, self.instance)

    # Check all devices manually
    self._CheckDevices(self.instance.primary_node, iv_names)

    # Step: remove old storage
    if not self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node, iv_names)

  def _ExecDrbd8Secondary(self, feedback_fn):
    """Replace the secondary node for DRBD 8.

    The algorithm for replace is quite complicated:
      - for all disks of the instance:
        - create new LVs on the new node with same names
        - shutdown the drbd device on the old secondary
        - disconnect the drbd network on the primary
        - create the drbd device on the new secondary
        - network attach the drbd on the primary, using an artifice:
          the drbd code for Attach() will connect to the network if it
          finds a device which is connected to the good local disks but
          not network enabled
      - wait for sync across all devices
      - remove all disks from the old secondary

    Failures are not very well handled.

    """
    steps_total = 6

    pnode = self.instance.primary_node

    # Step: check device activation
    self.lu.LogStep(1, steps_total, "Check device existence")
    self._CheckDisksExistence([self.instance.primary_node])
    self._CheckVolumeGroup([self.instance.primary_node])

    # Step: check other node consistency
    self.lu.LogStep(2, steps_total, "Check peer consistency")
    self._CheckDisksConsistency(self.instance.primary_node, True, True)

    # Step: create new storage
    self.lu.LogStep(3, steps_total, "Allocate new storage")
    disks = _AnnotateDiskParams(self.instance, self.instance.disks, self.cfg)
    excl_stor = _IsExclusiveStorageEnabledNodeName(self.lu.cfg, self.new_node)
    for idx, dev in enumerate(disks):
      self.lu.LogInfo("Adding new local storage on %s for disk/%d" %
                      (self.new_node, idx))
      # we pass force_create=True to force LVM creation
      for new_lv in dev.children:
        _CreateBlockDevInner(self.lu, self.new_node, self.instance, new_lv,
                             True, _GetInstanceInfoText(self.instance), False,
                             excl_stor)

    # Step 4: dbrd minors and drbd setups changes
    # after this, we must manually remove the drbd minors on both the
    # error and the success paths
    self.lu.LogStep(4, steps_total, "Changing drbd configuration")
    minors = self.cfg.AllocateDRBDMinor([self.new_node
                                         for dev in self.instance.disks],
                                        self.instance.name)
    logging.debug("Allocated minors %r", minors)

    iv_names = {}
    for idx, (dev, new_minor) in enumerate(zip(self.instance.disks, minors)):
      self.lu.LogInfo("activating a new drbd on %s for disk/%d" %
                      (self.new_node, idx))
      # create new devices on new_node; note that we create two IDs:
      # one without port, so the drbd will be activated without
      # networking information on the new node at this stage, and one
      # with network, for the latter activation in step 4
      (o_node1, o_node2, o_port, o_minor1, o_minor2, o_secret) = dev.logical_id
      if self.instance.primary_node == o_node1:
        p_minor = o_minor1
      else:
        assert self.instance.primary_node == o_node2, "Three-node instance?"
        p_minor = o_minor2

      new_alone_id = (self.instance.primary_node, self.new_node, None,
                      p_minor, new_minor, o_secret)
      new_net_id = (self.instance.primary_node, self.new_node, o_port,
                    p_minor, new_minor, o_secret)

      iv_names[idx] = (dev, dev.children, new_net_id)
      logging.debug("Allocated new_minor: %s, new_logical_id: %s", new_minor,
                    new_net_id)
      new_drbd = objects.Disk(dev_type=constants.LD_DRBD8,
                              logical_id=new_alone_id,
                              children=dev.children,
                              size=dev.size,
                              params={})
      (anno_new_drbd,) = _AnnotateDiskParams(self.instance, [new_drbd],
                                             self.cfg)
      try:
        _CreateSingleBlockDev(self.lu, self.new_node, self.instance,
                              anno_new_drbd,
                              _GetInstanceInfoText(self.instance), False,
                              excl_stor)
      except errors.GenericError:
        self.cfg.ReleaseDRBDMinors(self.instance.name)
        raise

    # We have new devices, shutdown the drbd on the old secondary
    for idx, dev in enumerate(self.instance.disks):
      self.lu.LogInfo("Shutting down drbd for disk/%d on old node", idx)
      self.cfg.SetDiskID(dev, self.target_node)
      msg = self.rpc.call_blockdev_shutdown(self.target_node,
                                            (dev, self.instance)).fail_msg
      if msg:
        self.lu.LogWarning("Failed to shutdown drbd for disk/%d on old"
                           "node: %s" % (idx, msg),
                           hint=("Please cleanup this device manually as"
                                 " soon as possible"))

    self.lu.LogInfo("Detaching primary drbds from the network (=> standalone)")
    result = self.rpc.call_drbd_disconnect_net([pnode], self.node_secondary_ip,
                                               self.instance.disks)[pnode]

    msg = result.fail_msg
    if msg:
      # detaches didn't succeed (unlikely)
      self.cfg.ReleaseDRBDMinors(self.instance.name)
      raise errors.OpExecError("Can't detach the disks from the network on"
                               " old node: %s" % (msg,))

    # if we managed to detach at least one, we update all the disks of
    # the instance to point to the new secondary
    self.lu.LogInfo("Updating instance configuration")
    for dev, _, new_logical_id in iv_names.itervalues():
      dev.logical_id = new_logical_id
      self.cfg.SetDiskID(dev, self.instance.primary_node)

    self.cfg.Update(self.instance, feedback_fn)

    # Release all node locks (the configuration has been updated)
    _ReleaseLocks(self.lu, locking.LEVEL_NODE)

    # and now perform the drbd attach
    self.lu.LogInfo("Attaching primary drbds to new secondary"
                    " (standalone => connected)")
    result = self.rpc.call_drbd_attach_net([self.instance.primary_node,
                                            self.new_node],
                                           self.node_secondary_ip,
                                           (self.instance.disks, self.instance),
                                           self.instance.name,
                                           False)
    for to_node, to_result in result.items():
      msg = to_result.fail_msg
      if msg:
        self.lu.LogWarning("Can't attach drbd disks on node %s: %s",
                           to_node, msg,
                           hint=("please do a gnt-instance info to see the"
                                 " status of disks"))

    cstep = itertools.count(5)

    if self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node, iv_names)
      # TODO: Check if releasing locks early still makes sense
      _ReleaseLocks(self.lu, locking.LEVEL_NODE_RES)
    else:
      # Release all resource locks except those used by the instance
      _ReleaseLocks(self.lu, locking.LEVEL_NODE_RES,
                    keep=self.node_secondary_ip.keys())

    # TODO: Can the instance lock be downgraded here? Take the optional disk
    # shutdown in the caller into consideration.

    # Wait for sync
    # This can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its return value
    self.lu.LogStep(cstep.next(), steps_total, "Sync devices")
    _WaitForSync(self.lu, self.instance)

    # Check all devices manually
    self._CheckDevices(self.instance.primary_node, iv_names)

    # Step: remove old storage
    if not self.early_release:
      self.lu.LogStep(cstep.next(), steps_total, "Removing old storage")
      self._RemoveOldStorage(self.target_node, iv_names)


class LURepairNodeStorage(NoHooksLU):
  """Repairs the volume group on a node.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)

    storage_type = self.op.storage_type

    if (constants.SO_FIX_CONSISTENCY not in
        constants.VALID_STORAGE_OPERATIONS.get(storage_type, [])):
      raise errors.OpPrereqError("Storage units of type '%s' can not be"
                                 " repaired" % storage_type,
                                 errors.ECODE_INVAL)

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: [self.op.node_name],
      }

  def _CheckFaultyDisks(self, instance, node_name):
    """Ensure faulty disks abort the opcode or at least warn."""
    try:
      if _FindFaultyInstanceDisks(self.cfg, self.rpc, instance,
                                  node_name, True):
        raise errors.OpPrereqError("Instance '%s' has faulty disks on"
                                   " node '%s'" % (instance.name, node_name),
                                   errors.ECODE_STATE)
    except errors.OpPrereqError, err:
      if self.op.ignore_consistency:
        self.LogWarning(str(err.args[0]))
      else:
        raise

  def CheckPrereq(self):
    """Check prerequisites.

    """
    # Check whether any instance on this node has faulty disks
    for inst in _GetNodeInstances(self.cfg, self.op.node_name):
      if inst.admin_state != constants.ADMINST_UP:
        continue
      check_nodes = set(inst.all_nodes)
      check_nodes.discard(self.op.node_name)
      for inst_node_name in check_nodes:
        self._CheckFaultyDisks(inst, inst_node_name)

  def Exec(self, feedback_fn):
    feedback_fn("Repairing storage unit '%s' on %s ..." %
                (self.op.name, self.op.node_name))

    st_args = _GetStorageTypeArgs(self.cfg, self.op.storage_type)
    result = self.rpc.call_storage_execute(self.op.node_name,
                                           self.op.storage_type, st_args,
                                           self.op.name,
                                           constants.SO_FIX_CONSISTENCY)
    result.Raise("Failed to repair storage unit '%s' on %s" %
                 (self.op.name, self.op.node_name))


class LUNodeEvacuate(NoHooksLU):
  """Evacuates instances off a list of nodes.

  """
  REQ_BGL = False

  _MODE2IALLOCATOR = {
    constants.NODE_EVAC_PRI: constants.IALLOCATOR_NEVAC_PRI,
    constants.NODE_EVAC_SEC: constants.IALLOCATOR_NEVAC_SEC,
    constants.NODE_EVAC_ALL: constants.IALLOCATOR_NEVAC_ALL,
    }
  assert frozenset(_MODE2IALLOCATOR.keys()) == constants.NODE_EVAC_MODES
  assert (frozenset(_MODE2IALLOCATOR.values()) ==
          constants.IALLOCATOR_NEVAC_MODES)

  def CheckArguments(self):
    _CheckIAllocatorOrNode(self, "iallocator", "remote_node")

  def ExpandNames(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)

    if self.op.remote_node is not None:
      self.op.remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)
      assert self.op.remote_node

      if self.op.remote_node == self.op.node_name:
        raise errors.OpPrereqError("Can not use evacuated node as a new"
                                   " secondary node", errors.ECODE_INVAL)

      if self.op.mode != constants.NODE_EVAC_SEC:
        raise errors.OpPrereqError("Without the use of an iallocator only"
                                   " secondary instances can be evacuated",
                                   errors.ECODE_INVAL)

    # Declare locks
    self.share_locks = _ShareAll()
    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],
      }

    # Determine nodes (via group) optimistically, needs verification once locks
    # have been acquired
    self.lock_nodes = self._DetermineNodes()

  def _DetermineNodes(self):
    """Gets the list of nodes to operate on.

    """
    if self.op.remote_node is None:
      # Iallocator will choose any node(s) in the same group
      group_nodes = self.cfg.GetNodeGroupMembersByNodes([self.op.node_name])
    else:
      group_nodes = frozenset([self.op.remote_node])

    # Determine nodes to be locked
    return set([self.op.node_name]) | group_nodes

  def _DetermineInstances(self):
    """Builds list of instances to operate on.

    """
    assert self.op.mode in constants.NODE_EVAC_MODES

    if self.op.mode == constants.NODE_EVAC_PRI:
      # Primary instances only
      inst_fn = _GetNodePrimaryInstances
      assert self.op.remote_node is None, \
        "Evacuating primary instances requires iallocator"
    elif self.op.mode == constants.NODE_EVAC_SEC:
      # Secondary instances only
      inst_fn = _GetNodeSecondaryInstances
    else:
      # All instances
      assert self.op.mode == constants.NODE_EVAC_ALL
      inst_fn = _GetNodeInstances
      # TODO: In 2.6, change the iallocator interface to take an evacuation mode
      # per instance
      raise errors.OpPrereqError("Due to an issue with the iallocator"
                                 " interface it is not possible to evacuate"
                                 " all instances at once; specify explicitly"
                                 " whether to evacuate primary or secondary"
                                 " instances",
                                 errors.ECODE_INVAL)

    return inst_fn(self.cfg, self.op.node_name)

  def DeclareLocks(self, level):
    if level == locking.LEVEL_INSTANCE:
      # Lock instances optimistically, needs verification once node and group
      # locks have been acquired
      self.needed_locks[locking.LEVEL_INSTANCE] = \
        set(i.name for i in self._DetermineInstances())

    elif level == locking.LEVEL_NODEGROUP:
      # Lock node groups for all potential target nodes optimistically, needs
      # verification once nodes have been acquired
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetNodeGroupsFromNodes(self.lock_nodes)

    elif level == locking.LEVEL_NODE:
      self.needed_locks[locking.LEVEL_NODE] = self.lock_nodes

  def CheckPrereq(self):
    # Verify locks
    owned_instances = self.owned_locks(locking.LEVEL_INSTANCE)
    owned_nodes = self.owned_locks(locking.LEVEL_NODE)
    owned_groups = self.owned_locks(locking.LEVEL_NODEGROUP)

    need_nodes = self._DetermineNodes()

    if not owned_nodes.issuperset(need_nodes):
      raise errors.OpPrereqError("Nodes in same group as '%s' changed since"
                                 " locks were acquired, current nodes are"
                                 " are '%s', used to be '%s'; retry the"
                                 " operation" %
                                 (self.op.node_name,
                                  utils.CommaJoin(need_nodes),
                                  utils.CommaJoin(owned_nodes)),
                                 errors.ECODE_STATE)

    wanted_groups = self.cfg.GetNodeGroupsFromNodes(owned_nodes)
    if owned_groups != wanted_groups:
      raise errors.OpExecError("Node groups changed since locks were acquired,"
                               " current groups are '%s', used to be '%s';"
                               " retry the operation" %
                               (utils.CommaJoin(wanted_groups),
                                utils.CommaJoin(owned_groups)))

    # Determine affected instances
    self.instances = self._DetermineInstances()
    self.instance_names = [i.name for i in self.instances]

    if set(self.instance_names) != owned_instances:
      raise errors.OpExecError("Instances on node '%s' changed since locks"
                               " were acquired, current instances are '%s',"
                               " used to be '%s'; retry the operation" %
                               (self.op.node_name,
                                utils.CommaJoin(self.instance_names),
                                utils.CommaJoin(owned_instances)))

    if self.instance_names:
      self.LogInfo("Evacuating instances from node '%s': %s",
                   self.op.node_name,
                   utils.CommaJoin(utils.NiceSort(self.instance_names)))
    else:
      self.LogInfo("No instances to evacuate from node '%s'",
                   self.op.node_name)

    if self.op.remote_node is not None:
      for i in self.instances:
        if i.primary_node == self.op.remote_node:
          raise errors.OpPrereqError("Node %s is the primary node of"
                                     " instance %s, cannot use it as"
                                     " secondary" %
                                     (self.op.remote_node, i.name),
                                     errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    assert (self.op.iallocator is not None) ^ (self.op.remote_node is not None)

    if not self.instance_names:
      # No instances to evacuate
      jobs = []

    elif self.op.iallocator is not None:
      # TODO: Implement relocation to other group
      evac_mode = self._MODE2IALLOCATOR[self.op.mode]
      req = iallocator.IAReqNodeEvac(evac_mode=evac_mode,
                                     instances=list(self.instance_names))
      ial = iallocator.IAllocator(self.cfg, self.rpc, req)

      ial.Run(self.op.iallocator)

      if not ial.success:
        raise errors.OpPrereqError("Can't compute node evacuation using"
                                   " iallocator '%s': %s" %
                                   (self.op.iallocator, ial.info),
                                   errors.ECODE_NORES)

      jobs = _LoadNodeEvacResult(self, ial.result, self.op.early_release, True)

    elif self.op.remote_node is not None:
      assert self.op.mode == constants.NODE_EVAC_SEC
      jobs = [
        [opcodes.OpInstanceReplaceDisks(instance_name=instance_name,
                                        remote_node=self.op.remote_node,
                                        disks=[],
                                        mode=constants.REPLACE_DISK_CHG,
                                        early_release=self.op.early_release)]
        for instance_name in self.instance_names]

    else:
      raise errors.ProgrammerError("No iallocator or remote node")

    return ResultWithJobs(jobs)


def _SetOpEarlyRelease(early_release, op):
  """Sets C{early_release} flag on opcodes if available.

  """
  try:
    op.early_release = early_release
  except AttributeError:
    assert not isinstance(op, opcodes.OpInstanceReplaceDisks)

  return op


def _NodeEvacDest(use_nodes, group, nodes):
  """Returns group or nodes depending on caller's choice.

  """
  if use_nodes:
    return utils.CommaJoin(nodes)
  else:
    return group


def _LoadNodeEvacResult(lu, alloc_result, early_release, use_nodes):
  """Unpacks the result of change-group and node-evacuate iallocator requests.

  Iallocator modes L{constants.IALLOCATOR_MODE_NODE_EVAC} and
  L{constants.IALLOCATOR_MODE_CHG_GROUP}.

  @type lu: L{LogicalUnit}
  @param lu: Logical unit instance
  @type alloc_result: tuple/list
  @param alloc_result: Result from iallocator
  @type early_release: bool
  @param early_release: Whether to release locks early if possible
  @type use_nodes: bool
  @param use_nodes: Whether to display node names instead of groups

  """
  (moved, failed, jobs) = alloc_result

  if failed:
    failreason = utils.CommaJoin("%s (%s)" % (name, reason)
                                 for (name, reason) in failed)
    lu.LogWarning("Unable to evacuate instances %s", failreason)
    raise errors.OpExecError("Unable to evacuate instances %s" % failreason)

  if moved:
    lu.LogInfo("Instances to be moved: %s",
               utils.CommaJoin("%s (to %s)" %
                               (name, _NodeEvacDest(use_nodes, group, nodes))
                               for (name, group, nodes) in moved))

  return [map(compat.partial(_SetOpEarlyRelease, early_release),
              map(opcodes.OpCode.LoadOpCode, ops))
          for ops in jobs]


def _DiskSizeInBytesToMebibytes(lu, size):
  """Converts a disk size in bytes to mebibytes.

  Warns and rounds up if the size isn't an even multiple of 1 MiB.

  """
  (mib, remainder) = divmod(size, 1024 * 1024)

  if remainder != 0:
    lu.LogWarning("Disk size is not an even multiple of 1 MiB; rounding up"
                  " to not overwrite existing data (%s bytes will not be"
                  " wiped)", (1024 * 1024) - remainder)
    mib += 1

  return mib


class LUInstanceGrowDisk(LogicalUnit):
  """Grow a disk of an instance.

  """
  HPATH = "disk-grow"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE
    self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    env = {
      "DISK": self.op.disk,
      "AMOUNT": self.op.amount,
      "ABSOLUTE": self.op.absolute,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    nodenames = list(instance.all_nodes)
    for node in nodenames:
      _CheckNodeOnline(self, node)

    self.instance = instance

    if instance.disk_template not in constants.DTS_GROWABLE:
      raise errors.OpPrereqError("Instance's disk layout does not support"
                                 " growing", errors.ECODE_INVAL)

    self.disk = instance.FindDisk(self.op.disk)

    if self.op.absolute:
      self.target = self.op.amount
      self.delta = self.target - self.disk.size
      if self.delta < 0:
        raise errors.OpPrereqError("Requested size (%s) is smaller than "
                                   "current disk size (%s)" %
                                   (utils.FormatUnit(self.target, "h"),
                                    utils.FormatUnit(self.disk.size, "h")),
                                   errors.ECODE_STATE)
    else:
      self.delta = self.op.amount
      self.target = self.disk.size + self.delta
      if self.delta < 0:
        raise errors.OpPrereqError("Requested increment (%s) is negative" %
                                   utils.FormatUnit(self.delta, "h"),
                                   errors.ECODE_INVAL)

    self._CheckDiskSpace(nodenames, self.disk.ComputeGrowth(self.delta))

  def _CheckDiskSpace(self, nodenames, req_vgspace):
    template = self.instance.disk_template
    if template not in (constants.DTS_NO_FREE_SPACE_CHECK):
      # TODO: check the free disk space for file, when that feature will be
      # supported
      nodes = map(self.cfg.GetNodeInfo, nodenames)
      es_nodes = filter(lambda n: _IsExclusiveStorageEnabledNode(self.cfg, n),
                        nodes)
      if es_nodes:
        # With exclusive storage we need to something smarter than just looking
        # at free space; for now, let's simply abort the operation.
        raise errors.OpPrereqError("Cannot grow disks when exclusive_storage"
                                   " is enabled", errors.ECODE_STATE)
      _CheckNodesFreeDiskPerVG(self, nodenames, req_vgspace)

  def Exec(self, feedback_fn):
    """Execute disk grow.

    """
    instance = self.instance
    disk = self.disk

    assert set([instance.name]) == self.owned_locks(locking.LEVEL_INSTANCE)
    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    wipe_disks = self.cfg.GetClusterInfo().prealloc_wipe_disks

    disks_ok, _ = _AssembleInstanceDisks(self, self.instance, disks=[disk])
    if not disks_ok:
      raise errors.OpExecError("Cannot activate block device to grow")

    feedback_fn("Growing disk %s of instance '%s' by %s to %s" %
                (self.op.disk, instance.name,
                 utils.FormatUnit(self.delta, "h"),
                 utils.FormatUnit(self.target, "h")))

    # First run all grow ops in dry-run mode
    for node in instance.all_nodes:
      self.cfg.SetDiskID(disk, node)
      result = self.rpc.call_blockdev_grow(node, (disk, instance), self.delta,
                                           True, True)
      result.Raise("Dry-run grow request failed to node %s" % node)

    if wipe_disks:
      # Get disk size from primary node for wiping
      result = self.rpc.call_blockdev_getsize(instance.primary_node, [disk])
      result.Raise("Failed to retrieve disk size from node '%s'" %
                   instance.primary_node)

      (disk_size_in_bytes, ) = result.payload

      if disk_size_in_bytes is None:
        raise errors.OpExecError("Failed to retrieve disk size from primary"
                                 " node '%s'" % instance.primary_node)

      old_disk_size = _DiskSizeInBytesToMebibytes(self, disk_size_in_bytes)

      assert old_disk_size >= disk.size, \
        ("Retrieved disk size too small (got %s, should be at least %s)" %
         (old_disk_size, disk.size))
    else:
      old_disk_size = None

    # We know that (as far as we can test) operations across different
    # nodes will succeed, time to run it for real on the backing storage
    for node in instance.all_nodes:
      self.cfg.SetDiskID(disk, node)
      result = self.rpc.call_blockdev_grow(node, (disk, instance), self.delta,
                                           False, True)
      result.Raise("Grow request failed to node %s" % node)

    # And now execute it for logical storage, on the primary node
    node = instance.primary_node
    self.cfg.SetDiskID(disk, node)
    result = self.rpc.call_blockdev_grow(node, (disk, instance), self.delta,
                                         False, False)
    result.Raise("Grow request failed to node %s" % node)

    disk.RecordGrow(self.delta)
    self.cfg.Update(instance, feedback_fn)

    # Changes have been recorded, release node lock
    _ReleaseLocks(self, locking.LEVEL_NODE)

    # Downgrade lock while waiting for sync
    self.glm.downgrade(locking.LEVEL_INSTANCE)

    assert wipe_disks ^ (old_disk_size is None)

    if wipe_disks:
      assert instance.disks[self.op.disk] == disk

      # Wipe newly added disk space
      _WipeDisks(self, instance,
                 disks=[(self.op.disk, disk, old_disk_size)])

    if self.op.wait_for_sync:
      disk_abort = not _WaitForSync(self, instance, disks=[disk])
      if disk_abort:
        self.LogWarning("Disk syncing has not returned a good status; check"
                        " the instance")
      if instance.admin_state != constants.ADMINST_UP:
        _SafeShutdownInstanceDisks(self, instance, disks=[disk])
    elif instance.admin_state != constants.ADMINST_UP:
      self.LogWarning("Not shutting down the disk even if the instance is"
                      " not supposed to be running because no wait for"
                      " sync mode was requested")

    assert self.owned_locks(locking.LEVEL_NODE_RES)
    assert set([instance.name]) == self.owned_locks(locking.LEVEL_INSTANCE)


class LUInstanceQueryData(NoHooksLU):
  """Query runtime instance data.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

    # Use locking if requested or when non-static information is wanted
    if not (self.op.static or self.op.use_locking):
      self.LogWarning("Non-static data requested, locks need to be acquired")
      self.op.use_locking = True

    if self.op.instances or not self.op.use_locking:
      # Expand instance names right here
      self.wanted_names = _GetWantedInstances(self, self.op.instances)
    else:
      # Will use acquired locks
      self.wanted_names = None

    if self.op.use_locking:
      self.share_locks = _ShareAll()

      if self.wanted_names is None:
        self.needed_locks[locking.LEVEL_INSTANCE] = locking.ALL_SET
      else:
        self.needed_locks[locking.LEVEL_INSTANCE] = self.wanted_names

      self.needed_locks[locking.LEVEL_NODEGROUP] = []
      self.needed_locks[locking.LEVEL_NODE] = []
      self.needed_locks[locking.LEVEL_NETWORK] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if self.op.use_locking:
      owned_instances = self.owned_locks(locking.LEVEL_INSTANCE)
      if level == locking.LEVEL_NODEGROUP:

        # Lock all groups used by instances optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        self.needed_locks[locking.LEVEL_NODEGROUP] = \
          frozenset(group_uuid
                    for instance_name in owned_instances
                    for group_uuid in
                      self.cfg.GetInstanceNodeGroups(instance_name))

      elif level == locking.LEVEL_NODE:
        self._LockInstancesNodes()

      elif level == locking.LEVEL_NETWORK:
        self.needed_locks[locking.LEVEL_NETWORK] = \
          frozenset(net_uuid
                    for instance_name in owned_instances
                    for net_uuid in
                       self.cfg.GetInstanceNetworks(instance_name))

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))
    owned_networks = frozenset(self.owned_locks(locking.LEVEL_NETWORK))

    if self.wanted_names is None:
      assert self.op.use_locking, "Locking was not used"
      self.wanted_names = owned_instances

    instances = dict(self.cfg.GetMultiInstanceInfo(self.wanted_names))

    if self.op.use_locking:
      _CheckInstancesNodeGroups(self.cfg, instances, owned_groups, owned_nodes,
                                None)
    else:
      assert not (owned_instances or owned_groups or
                  owned_nodes or owned_networks)

    self.wanted_instances = instances.values()

  def _ComputeBlockdevStatus(self, node, instance, dev):
    """Returns the status of a block device

    """
    if self.op.static or not node:
      return None

    self.cfg.SetDiskID(dev, node)

    result = self.rpc.call_blockdev_find(node, dev)
    if result.offline:
      return None

    result.Raise("Can't compute disk status for %s" % instance.name)

    status = result.payload
    if status is None:
      return None

    return (status.dev_path, status.major, status.minor,
            status.sync_percent, status.estimated_time,
            status.is_degraded, status.ldisk_status)

  def _ComputeDiskStatus(self, instance, snode, dev):
    """Compute block device status.

    """
    (anno_dev,) = _AnnotateDiskParams(instance, [dev], self.cfg)

    return self._ComputeDiskStatusInner(instance, snode, anno_dev)

  def _ComputeDiskStatusInner(self, instance, snode, dev):
    """Compute block device status.

    @attention: The device has to be annotated already.

    """
    if dev.dev_type in constants.LDS_DRBD:
      # we change the snode then (otherwise we use the one passed in)
      if dev.logical_id[0] == instance.primary_node:
        snode = dev.logical_id[1]
      else:
        snode = dev.logical_id[0]

    dev_pstatus = self._ComputeBlockdevStatus(instance.primary_node,
                                              instance, dev)
    dev_sstatus = self._ComputeBlockdevStatus(snode, instance, dev)

    if dev.children:
      dev_children = map(compat.partial(self._ComputeDiskStatusInner,
                                        instance, snode),
                         dev.children)
    else:
      dev_children = []

    return {
      "iv_name": dev.iv_name,
      "dev_type": dev.dev_type,
      "logical_id": dev.logical_id,
      "physical_id": dev.physical_id,
      "pstatus": dev_pstatus,
      "sstatus": dev_sstatus,
      "children": dev_children,
      "mode": dev.mode,
      "size": dev.size,
      }

  def Exec(self, feedback_fn):
    """Gather and return data"""
    result = {}

    cluster = self.cfg.GetClusterInfo()

    node_names = itertools.chain(*(i.all_nodes for i in self.wanted_instances))
    nodes = dict(self.cfg.GetMultiNodeInfo(node_names))

    groups = dict(self.cfg.GetMultiNodeGroupInfo(node.group
                                                 for node in nodes.values()))

    group2name_fn = lambda uuid: groups[uuid].name
    for instance in self.wanted_instances:
      pnode = nodes[instance.primary_node]

      if self.op.static or pnode.offline:
        remote_state = None
        if pnode.offline:
          self.LogWarning("Primary node %s is marked offline, returning static"
                          " information only for instance %s" %
                          (pnode.name, instance.name))
      else:
        remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                  instance.name,
                                                  instance.hypervisor)
        remote_info.Raise("Error checking node %s" % instance.primary_node)
        remote_info = remote_info.payload
        if remote_info and "state" in remote_info:
          remote_state = "up"
        else:
          if instance.admin_state == constants.ADMINST_UP:
            remote_state = "down"
          else:
            remote_state = instance.admin_state

      disks = map(compat.partial(self._ComputeDiskStatus, instance, None),
                  instance.disks)

      snodes_group_uuids = [nodes[snode_name].group
                            for snode_name in instance.secondary_nodes]

      result[instance.name] = {
        "name": instance.name,
        "config_state": instance.admin_state,
        "run_state": remote_state,
        "pnode": instance.primary_node,
        "pnode_group_uuid": pnode.group,
        "pnode_group_name": group2name_fn(pnode.group),
        "snodes": instance.secondary_nodes,
        "snodes_group_uuids": snodes_group_uuids,
        "snodes_group_names": map(group2name_fn, snodes_group_uuids),
        "os": instance.os,
        # this happens to be the same format used for hooks
        "nics": _NICListToTuple(self, instance.nics),
        "disk_template": instance.disk_template,
        "disks": disks,
        "hypervisor": instance.hypervisor,
        "network_port": instance.network_port,
        "hv_instance": instance.hvparams,
        "hv_actual": cluster.FillHV(instance, skip_globals=True),
        "be_instance": instance.beparams,
        "be_actual": cluster.FillBE(instance),
        "os_instance": instance.osparams,
        "os_actual": cluster.SimpleFillOS(instance.os, instance.osparams),
        "serial_no": instance.serial_no,
        "mtime": instance.mtime,
        "ctime": instance.ctime,
        "uuid": instance.uuid,
        }

    return result


def PrepareContainerMods(mods, private_fn):
  """Prepares a list of container modifications by adding a private data field.

  @type mods: list of tuples; (operation, index, parameters)
  @param mods: List of modifications
  @type private_fn: callable or None
  @param private_fn: Callable for constructing a private data field for a
    modification
  @rtype: list

  """
  if private_fn is None:
    fn = lambda: None
  else:
    fn = private_fn

  return [(op, idx, params, fn()) for (op, idx, params) in mods]


#: Type description for changes as returned by L{ApplyContainerMods}'s
#: callbacks
_TApplyContModsCbChanges = \
  ht.TMaybeListOf(ht.TAnd(ht.TIsLength(2), ht.TItems([
    ht.TNonEmptyString,
    ht.TAny,
    ])))


def ApplyContainerMods(kind, container, chgdesc, mods,
                       create_fn, modify_fn, remove_fn):
  """Applies descriptions in C{mods} to C{container}.

  @type kind: string
  @param kind: One-word item description
  @type container: list
  @param container: Container to modify
  @type chgdesc: None or list
  @param chgdesc: List of applied changes
  @type mods: list
  @param mods: Modifications as returned by L{PrepareContainerMods}
  @type create_fn: callable
  @param create_fn: Callback for creating a new item (L{constants.DDM_ADD});
    receives absolute item index, parameters and private data object as added
    by L{PrepareContainerMods}, returns tuple containing new item and changes
    as list
  @type modify_fn: callable
  @param modify_fn: Callback for modifying an existing item
    (L{constants.DDM_MODIFY}); receives absolute item index, item, parameters
    and private data object as added by L{PrepareContainerMods}, returns
    changes as list
  @type remove_fn: callable
  @param remove_fn: Callback on removing item; receives absolute item index,
    item and private data object as added by L{PrepareContainerMods}

  """
  for (op, idx, params, private) in mods:
    if idx == -1:
      # Append
      absidx = len(container) - 1
    elif idx < 0:
      raise IndexError("Not accepting negative indices other than -1")
    elif idx > len(container):
      raise IndexError("Got %s index %s, but there are only %s" %
                       (kind, idx, len(container)))
    else:
      absidx = idx

    changes = None

    if op == constants.DDM_ADD:
      # Calculate where item will be added
      if idx == -1:
        addidx = len(container)
      else:
        addidx = idx

      if create_fn is None:
        item = params
      else:
        (item, changes) = create_fn(addidx, params, private)

      if idx == -1:
        container.append(item)
      else:
        assert idx >= 0
        assert idx <= len(container)
        # list.insert does so before the specified index
        container.insert(idx, item)
    else:
      # Retrieve existing item
      try:
        item = container[absidx]
      except IndexError:
        raise IndexError("Invalid %s index %s" % (kind, idx))

      if op == constants.DDM_REMOVE:
        assert not params

        if remove_fn is not None:
          remove_fn(absidx, item, private)

        changes = [("%s/%s" % (kind, absidx), "remove")]

        assert container[absidx] == item
        del container[absidx]
      elif op == constants.DDM_MODIFY:
        if modify_fn is not None:
          changes = modify_fn(absidx, item, params, private)
      else:
        raise errors.ProgrammerError("Unhandled operation '%s'" % op)

    assert _TApplyContModsCbChanges(changes)

    if not (chgdesc is None or changes is None):
      chgdesc.extend(changes)


def _UpdateIvNames(base_index, disks):
  """Updates the C{iv_name} attribute of disks.

  @type disks: list of L{objects.Disk}

  """
  for (idx, disk) in enumerate(disks):
    disk.iv_name = "disk/%s" % (base_index + idx, )


class _InstNicModPrivate:
  """Data structure for network interface modifications.

  Used by L{LUInstanceSetParams}.

  """
  def __init__(self):
    self.params = None
    self.filled = None


class LUInstanceSetParams(LogicalUnit):
  """Modifies an instances's parameters.

  """
  HPATH = "instance-modify"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  @staticmethod
  def _UpgradeDiskNicMods(kind, mods, verify_fn):
    assert ht.TList(mods)
    assert not mods or len(mods[0]) in (2, 3)

    if mods and len(mods[0]) == 2:
      result = []

      addremove = 0
      for op, params in mods:
        if op in (constants.DDM_ADD, constants.DDM_REMOVE):
          result.append((op, -1, params))
          addremove += 1

          if addremove > 1:
            raise errors.OpPrereqError("Only one %s add or remove operation is"
                                       " supported at a time" % kind,
                                       errors.ECODE_INVAL)
        else:
          result.append((constants.DDM_MODIFY, op, params))

      assert verify_fn(result)
    else:
      result = mods

    return result

  @staticmethod
  def _CheckMods(kind, mods, key_types, item_fn):
    """Ensures requested disk/NIC modifications are valid.

    """
    for (op, _, params) in mods:
      assert ht.TDict(params)

      # If 'key_types' is an empty dict, we assume we have an
      # 'ext' template and thus do not ForceDictType
      if key_types:
        utils.ForceDictType(params, key_types)

      if op == constants.DDM_REMOVE:
        if params:
          raise errors.OpPrereqError("No settings should be passed when"
                                     " removing a %s" % kind,
                                     errors.ECODE_INVAL)
      elif op in (constants.DDM_ADD, constants.DDM_MODIFY):
        item_fn(op, params)
      else:
        raise errors.ProgrammerError("Unhandled operation '%s'" % op)

  @staticmethod
  def _VerifyDiskModification(op, params):
    """Verifies a disk modification.

    """
    if op == constants.DDM_ADD:
      mode = params.setdefault(constants.IDISK_MODE, constants.DISK_RDWR)
      if mode not in constants.DISK_ACCESS_SET:
        raise errors.OpPrereqError("Invalid disk access mode '%s'" % mode,
                                   errors.ECODE_INVAL)

      size = params.get(constants.IDISK_SIZE, None)
      if size is None:
        raise errors.OpPrereqError("Required disk parameter '%s' missing" %
                                   constants.IDISK_SIZE, errors.ECODE_INVAL)

      try:
        size = int(size)
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid disk size parameter: %s" % err,
                                   errors.ECODE_INVAL)

      params[constants.IDISK_SIZE] = size

    elif op == constants.DDM_MODIFY:
      if constants.IDISK_SIZE in params:
        raise errors.OpPrereqError("Disk size change not possible, use"
                                   " grow-disk", errors.ECODE_INVAL)
      if constants.IDISK_MODE not in params:
        raise errors.OpPrereqError("Disk 'mode' is the only kind of"
                                   " modification supported, but missing",
                                   errors.ECODE_NOENT)
      if len(params) > 1:
        raise errors.OpPrereqError("Disk modification doesn't support"
                                   " additional arbitrary parameters",
                                   errors.ECODE_INVAL)

  @staticmethod
  def _VerifyNicModification(op, params):
    """Verifies a network interface modification.

    """
    if op in (constants.DDM_ADD, constants.DDM_MODIFY):
      ip = params.get(constants.INIC_IP, None)
      req_net = params.get(constants.INIC_NETWORK, None)
      link = params.get(constants.NIC_LINK, None)
      mode = params.get(constants.NIC_MODE, None)
      if req_net is not None:
        if req_net.lower() == constants.VALUE_NONE:
          params[constants.INIC_NETWORK] = None
          req_net = None
        elif link is not None or mode is not None:
          raise errors.OpPrereqError("If network is given"
                                     " mode or link should not",
                                     errors.ECODE_INVAL)

      if op == constants.DDM_ADD:
        macaddr = params.get(constants.INIC_MAC, None)
        if macaddr is None:
          params[constants.INIC_MAC] = constants.VALUE_AUTO

      if ip is not None:
        if ip.lower() == constants.VALUE_NONE:
          params[constants.INIC_IP] = None
        else:
          if ip.lower() == constants.NIC_IP_POOL:
            if op == constants.DDM_ADD and req_net is None:
              raise errors.OpPrereqError("If ip=pool, parameter network"
                                         " cannot be none",
                                         errors.ECODE_INVAL)
          else:
            if not netutils.IPAddress.IsValid(ip):
              raise errors.OpPrereqError("Invalid IP address '%s'" % ip,
                                         errors.ECODE_INVAL)

      if constants.INIC_MAC in params:
        macaddr = params[constants.INIC_MAC]
        if macaddr not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
          macaddr = utils.NormalizeAndValidateMac(macaddr)

        if op == constants.DDM_MODIFY and macaddr == constants.VALUE_AUTO:
          raise errors.OpPrereqError("'auto' is not a valid MAC address when"
                                     " modifying an existing NIC",
                                     errors.ECODE_INVAL)

  def CheckArguments(self):
    if not (self.op.nics or self.op.disks or self.op.disk_template or
            self.op.hvparams or self.op.beparams or self.op.os_name or
            self.op.offline is not None or self.op.runtime_mem):
      raise errors.OpPrereqError("No changes submitted", errors.ECODE_INVAL)

    if self.op.hvparams:
      _CheckParamsNotGlobal(self.op.hvparams, constants.HVC_GLOBALS,
                            "hypervisor", "instance", "cluster")

    self.op.disks = self._UpgradeDiskNicMods(
      "disk", self.op.disks, opcodes.OpInstanceSetParams.TestDiskModifications)
    self.op.nics = self._UpgradeDiskNicMods(
      "NIC", self.op.nics, opcodes.OpInstanceSetParams.TestNicModifications)

    if self.op.disks and self.op.disk_template is not None:
      raise errors.OpPrereqError("Disk template conversion and other disk"
                                 " changes not supported at the same time",
                                 errors.ECODE_INVAL)

    if (self.op.disk_template and
        self.op.disk_template in constants.DTS_INT_MIRROR and
        self.op.remote_node is None):
      raise errors.OpPrereqError("Changing the disk template to a mirrored"
                                 " one requires specifying a secondary node",
                                 errors.ECODE_INVAL)

    # Check NIC modifications
    self._CheckMods("NIC", self.op.nics, constants.INIC_PARAMS_TYPES,
                    self._VerifyNicModification)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODEGROUP] = []
    # Can't even acquire node locks in shared mode as upcoming changes in
    # Ganeti 2.6 will start to modify the node object on disk conversion
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE
    # Look node group to look up the ipolicy
    self.share_locks[locking.LEVEL_NODEGROUP] = 1

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]
      # Acquire locks for the instance's nodegroups optimistically. Needs
      # to be verified in CheckPrereq
      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        self.cfg.GetInstanceNodeGroups(self.op.instance_name)
    elif level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
      if self.op.disk_template and self.op.remote_node:
        self.op.remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)
        self.needed_locks[locking.LEVEL_NODE].append(self.op.remote_node)
    elif level == locking.LEVEL_NODE_RES and self.op.disk_template:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        _CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, primary and secondaries.

    """
    args = {}
    if constants.BE_MINMEM in self.be_new:
      args["minmem"] = self.be_new[constants.BE_MINMEM]
    if constants.BE_MAXMEM in self.be_new:
      args["maxmem"] = self.be_new[constants.BE_MAXMEM]
    if constants.BE_VCPUS in self.be_new:
      args["vcpus"] = self.be_new[constants.BE_VCPUS]
    # TODO: export disk changes. Note: _BuildInstanceHookEnv* don't export disk
    # information at all.

    if self._new_nics is not None:
      nics = []

      for nic in self._new_nics:
        n = copy.deepcopy(nic)
        nicparams = self.cluster.SimpleFillNIC(n.nicparams)
        n.nicparams = nicparams
        nics.append(_NICToTuple(self, n))

      args["nics"] = nics

    env = _BuildInstanceHookEnvByObject(self, self.instance, override=args)
    if self.op.disk_template:
      env["NEW_DISK_TEMPLATE"] = self.op.disk_template
    if self.op.runtime_mem:
      env["RUNTIME_MEMORY"] = self.op.runtime_mem

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def _PrepareNicModification(self, params, private, old_ip, old_net_uuid,
                              old_params, cluster, pnode):

    update_params_dict = dict([(key, params[key])
                               for key in constants.NICS_PARAMETERS
                               if key in params])

    req_link = update_params_dict.get(constants.NIC_LINK, None)
    req_mode = update_params_dict.get(constants.NIC_MODE, None)

    new_net_uuid = None
    new_net_uuid_or_name = params.get(constants.INIC_NETWORK, old_net_uuid)
    if new_net_uuid_or_name:
      new_net_uuid = self.cfg.LookupNetwork(new_net_uuid_or_name)
      new_net_obj = self.cfg.GetNetwork(new_net_uuid)

    if old_net_uuid:
      old_net_obj = self.cfg.GetNetwork(old_net_uuid)

    if new_net_uuid:
      netparams = self.cfg.GetGroupNetParams(new_net_uuid, pnode)
      if not netparams:
        raise errors.OpPrereqError("No netparams found for the network"
                                   " %s, probably not connected" %
                                   new_net_obj.name, errors.ECODE_INVAL)
      new_params = dict(netparams)
    else:
      new_params = _GetUpdatedParams(old_params, update_params_dict)

    utils.ForceDictType(new_params, constants.NICS_PARAMETER_TYPES)

    new_filled_params = cluster.SimpleFillNIC(new_params)
    objects.NIC.CheckParameterSyntax(new_filled_params)

    new_mode = new_filled_params[constants.NIC_MODE]
    if new_mode == constants.NIC_MODE_BRIDGED:
      bridge = new_filled_params[constants.NIC_LINK]
      msg = self.rpc.call_bridges_exist(pnode, [bridge]).fail_msg
      if msg:
        msg = "Error checking bridges on node '%s': %s" % (pnode, msg)
        if self.op.force:
          self.warn.append(msg)
        else:
          raise errors.OpPrereqError(msg, errors.ECODE_ENVIRON)

    elif new_mode == constants.NIC_MODE_ROUTED:
      ip = params.get(constants.INIC_IP, old_ip)
      if ip is None:
        raise errors.OpPrereqError("Cannot set the NIC IP address to None"
                                   " on a routed NIC", errors.ECODE_INVAL)

    elif new_mode == constants.NIC_MODE_OVS:
      # TODO: check OVS link
      self.LogInfo("OVS links are currently not checked for correctness")

    if constants.INIC_MAC in params:
      mac = params[constants.INIC_MAC]
      if mac is None:
        raise errors.OpPrereqError("Cannot unset the NIC MAC address",
                                   errors.ECODE_INVAL)
      elif mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        # otherwise generate the MAC address
        params[constants.INIC_MAC] = \
          self.cfg.GenerateMAC(new_net_uuid, self.proc.GetECId())
      else:
        # or validate/reserve the current one
        try:
          self.cfg.ReserveMAC(mac, self.proc.GetECId())
        except errors.ReservationError:
          raise errors.OpPrereqError("MAC address '%s' already in use"
                                     " in cluster" % mac,
                                     errors.ECODE_NOTUNIQUE)
    elif new_net_uuid != old_net_uuid:

      def get_net_prefix(net_uuid):
        mac_prefix = None
        if net_uuid:
          nobj = self.cfg.GetNetwork(net_uuid)
          mac_prefix = nobj.mac_prefix

        return mac_prefix

      new_prefix = get_net_prefix(new_net_uuid)
      old_prefix = get_net_prefix(old_net_uuid)
      if old_prefix != new_prefix:
        params[constants.INIC_MAC] = \
          self.cfg.GenerateMAC(new_net_uuid, self.proc.GetECId())

    # if there is a change in (ip, network) tuple
    new_ip = params.get(constants.INIC_IP, old_ip)
    if (new_ip, new_net_uuid) != (old_ip, old_net_uuid):
      if new_ip:
        # if IP is pool then require a network and generate one IP
        if new_ip.lower() == constants.NIC_IP_POOL:
          if new_net_uuid:
            try:
              new_ip = self.cfg.GenerateIp(new_net_uuid, self.proc.GetECId())
            except errors.ReservationError:
              raise errors.OpPrereqError("Unable to get a free IP"
                                         " from the address pool",
                                         errors.ECODE_STATE)
            self.LogInfo("Chose IP %s from network %s",
                         new_ip,
                         new_net_obj.name)
            params[constants.INIC_IP] = new_ip
          else:
            raise errors.OpPrereqError("ip=pool, but no network found",
                                       errors.ECODE_INVAL)
        # Reserve new IP if in the new network if any
        elif new_net_uuid:
          try:
            self.cfg.ReserveIp(new_net_uuid, new_ip, self.proc.GetECId())
            self.LogInfo("Reserving IP %s in network %s",
                         new_ip, new_net_obj.name)
          except errors.ReservationError:
            raise errors.OpPrereqError("IP %s not available in network %s" %
                                       (new_ip, new_net_obj.name),
                                       errors.ECODE_NOTUNIQUE)
        # new network is None so check if new IP is a conflicting IP
        elif self.op.conflicts_check:
          _CheckForConflictingIp(self, new_ip, pnode)

      # release old IP if old network is not None
      if old_ip and old_net_uuid:
        try:
          self.cfg.ReleaseIp(old_net_uuid, old_ip, self.proc.GetECId())
        except errors.AddressPoolError:
          logging.warning("Release IP %s not contained in network %s",
                          old_ip, old_net_obj.name)

    # there are no changes in (ip, network) tuple and old network is not None
    elif (old_net_uuid is not None and
          (req_link is not None or req_mode is not None)):
      raise errors.OpPrereqError("Not allowed to change link or mode of"
                                 " a NIC that is connected to a network",
                                 errors.ECODE_INVAL)

    private.params = new_params
    private.filled = new_filled_params

  def _PreCheckDiskTemplate(self, pnode_info):
    """CheckPrereq checks related to a new disk template."""
    # Arguments are passed to avoid configuration lookups
    instance = self.instance
    pnode = instance.primary_node
    cluster = self.cluster
    if instance.disk_template == self.op.disk_template:
      raise errors.OpPrereqError("Instance already has disk template %s" %
                                 instance.disk_template, errors.ECODE_INVAL)

    if (instance.disk_template,
        self.op.disk_template) not in self._DISK_CONVERSIONS:
      raise errors.OpPrereqError("Unsupported disk template conversion from"
                                 " %s to %s" % (instance.disk_template,
                                                self.op.disk_template),
                                 errors.ECODE_INVAL)
    _CheckInstanceState(self, instance, INSTANCE_DOWN,
                        msg="cannot change disk template")
    if self.op.disk_template in constants.DTS_INT_MIRROR:
      if self.op.remote_node == pnode:
        raise errors.OpPrereqError("Given new secondary node %s is the same"
                                   " as the primary node of the instance" %
                                   self.op.remote_node, errors.ECODE_STATE)
      _CheckNodeOnline(self, self.op.remote_node)
      _CheckNodeNotDrained(self, self.op.remote_node)
      # FIXME: here we assume that the old instance type is DT_PLAIN
      assert instance.disk_template == constants.DT_PLAIN
      disks = [{constants.IDISK_SIZE: d.size,
                constants.IDISK_VG: d.logical_id[0]}
               for d in instance.disks]
      required = _ComputeDiskSizePerVG(self.op.disk_template, disks)
      _CheckNodesFreeDiskPerVG(self, [self.op.remote_node], required)

      snode_info = self.cfg.GetNodeInfo(self.op.remote_node)
      snode_group = self.cfg.GetNodeGroup(snode_info.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              snode_group)
      _CheckTargetNodeIPolicy(self, ipolicy, instance, snode_info, self.cfg,
                              ignore=self.op.ignore_ipolicy)
      if pnode_info.group != snode_info.group:
        self.LogWarning("The primary and secondary nodes are in two"
                        " different node groups; the disk parameters"
                        " from the first disk's node group will be"
                        " used")

    if not self.op.disk_template in constants.DTS_EXCL_STORAGE:
      # Make sure none of the nodes require exclusive storage
      nodes = [pnode_info]
      if self.op.disk_template in constants.DTS_INT_MIRROR:
        assert snode_info
        nodes.append(snode_info)
      has_es = lambda n: _IsExclusiveStorageEnabledNode(self.cfg, n)
      if compat.any(map(has_es, nodes)):
        errmsg = ("Cannot convert disk template from %s to %s when exclusive"
                  " storage is enabled" % (instance.disk_template,
                                           self.op.disk_template))
        raise errors.OpPrereqError(errmsg, errors.ECODE_STATE)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    assert self.op.instance_name in self.owned_locks(locking.LEVEL_INSTANCE)
    instance = self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)

    cluster = self.cluster = self.cfg.GetClusterInfo()
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    pnode = instance.primary_node
    assert pnode in self.owned_locks(locking.LEVEL_NODE)
    nodelist = list(instance.all_nodes)
    pnode_info = self.cfg.GetNodeInfo(pnode)
    self.diskparams = self.cfg.GetInstanceDiskParams(instance)

    #_CheckInstanceNodeGroups(self.cfg, self.op.instance_name, owned_groups)
    assert pnode_info.group in self.owned_locks(locking.LEVEL_NODEGROUP)
    group_info = self.cfg.GetNodeGroup(pnode_info.group)

    # dictionary with instance information after the modification
    ispec = {}

    # Check disk modifications. This is done here and not in CheckArguments
    # (as with NICs), because we need to know the instance's disk template
    if instance.disk_template == constants.DT_EXT:
      self._CheckMods("disk", self.op.disks, {},
                      self._VerifyDiskModification)
    else:
      self._CheckMods("disk", self.op.disks, constants.IDISK_PARAMS_TYPES,
                      self._VerifyDiskModification)

    # Prepare disk/NIC modifications
    self.diskmod = PrepareContainerMods(self.op.disks, None)
    self.nicmod = PrepareContainerMods(self.op.nics, _InstNicModPrivate)

    # Check the validity of the `provider' parameter
    if instance.disk_template in constants.DT_EXT:
      for mod in self.diskmod:
        ext_provider = mod[2].get(constants.IDISK_PROVIDER, None)
        if mod[0] == constants.DDM_ADD:
          if ext_provider is None:
            raise errors.OpPrereqError("Instance template is '%s' and parameter"
                                       " '%s' missing, during disk add" %
                                       (constants.DT_EXT,
                                        constants.IDISK_PROVIDER),
                                       errors.ECODE_NOENT)
        elif mod[0] == constants.DDM_MODIFY:
          if ext_provider:
            raise errors.OpPrereqError("Parameter '%s' is invalid during disk"
                                       " modification" %
                                       constants.IDISK_PROVIDER,
                                       errors.ECODE_INVAL)
    else:
      for mod in self.diskmod:
        ext_provider = mod[2].get(constants.IDISK_PROVIDER, None)
        if ext_provider is not None:
          raise errors.OpPrereqError("Parameter '%s' is only valid for"
                                     " instances of type '%s'" %
                                     (constants.IDISK_PROVIDER,
                                      constants.DT_EXT),
                                     errors.ECODE_INVAL)

    # OS change
    if self.op.os_name and not self.op.force:
      _CheckNodeHasOS(self, instance.primary_node, self.op.os_name,
                      self.op.force_variant)
      instance_os = self.op.os_name
    else:
      instance_os = instance.os

    assert not (self.op.disk_template and self.op.disks), \
      "Can't modify disk template and apply disk changes at the same time"

    if self.op.disk_template:
      self._PreCheckDiskTemplate(pnode_info)

    # hvparams processing
    if self.op.hvparams:
      hv_type = instance.hypervisor
      i_hvdict = _GetUpdatedParams(instance.hvparams, self.op.hvparams)
      utils.ForceDictType(i_hvdict, constants.HVS_PARAMETER_TYPES)
      hv_new = cluster.SimpleFillHV(hv_type, instance.os, i_hvdict)

      # local check
      hypervisor.GetHypervisorClass(hv_type).CheckParameterSyntax(hv_new)
      _CheckHVParams(self, nodelist, instance.hypervisor, hv_new)
      self.hv_proposed = self.hv_new = hv_new # the new actual values
      self.hv_inst = i_hvdict # the new dict (without defaults)
    else:
      self.hv_proposed = cluster.SimpleFillHV(instance.hypervisor, instance.os,
                                              instance.hvparams)
      self.hv_new = self.hv_inst = {}

    # beparams processing
    if self.op.beparams:
      i_bedict = _GetUpdatedParams(instance.beparams, self.op.beparams,
                                   use_none=True)
      objects.UpgradeBeParams(i_bedict)
      utils.ForceDictType(i_bedict, constants.BES_PARAMETER_TYPES)
      be_new = cluster.SimpleFillBE(i_bedict)
      self.be_proposed = self.be_new = be_new # the new actual values
      self.be_inst = i_bedict # the new dict (without defaults)
    else:
      self.be_new = self.be_inst = {}
      self.be_proposed = cluster.SimpleFillBE(instance.beparams)
    be_old = cluster.FillBE(instance)

    # CPU param validation -- checking every time a parameter is
    # changed to cover all cases where either CPU mask or vcpus have
    # changed
    if (constants.BE_VCPUS in self.be_proposed and
        constants.HV_CPU_MASK in self.hv_proposed):
      cpu_list = \
        utils.ParseMultiCpuMask(self.hv_proposed[constants.HV_CPU_MASK])
      # Verify mask is consistent with number of vCPUs. Can skip this
      # test if only 1 entry in the CPU mask, which means same mask
      # is applied to all vCPUs.
      if (len(cpu_list) > 1 and
          len(cpu_list) != self.be_proposed[constants.BE_VCPUS]):
        raise errors.OpPrereqError("Number of vCPUs [%d] does not match the"
                                   " CPU mask [%s]" %
                                   (self.be_proposed[constants.BE_VCPUS],
                                    self.hv_proposed[constants.HV_CPU_MASK]),
                                   errors.ECODE_INVAL)

      # Only perform this test if a new CPU mask is given
      if constants.HV_CPU_MASK in self.hv_new:
        # Calculate the largest CPU number requested
        max_requested_cpu = max(map(max, cpu_list))
        # Check that all of the instance's nodes have enough physical CPUs to
        # satisfy the requested CPU mask
        _CheckNodesPhysicalCPUs(self, instance.all_nodes,
                                max_requested_cpu + 1, instance.hypervisor)

    # osparams processing
    if self.op.osparams:
      i_osdict = _GetUpdatedParams(instance.osparams, self.op.osparams)
      _CheckOSParams(self, True, nodelist, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = {}

    self.warn = []

    #TODO(dynmem): do the appropriate check involving MINMEM
    if (constants.BE_MAXMEM in self.op.beparams and not self.op.force and
        be_new[constants.BE_MAXMEM] > be_old[constants.BE_MAXMEM]):
      mem_check_list = [pnode]
      if be_new[constants.BE_AUTO_BALANCE]:
        # either we changed auto_balance to yes or it was from before
        mem_check_list.extend(instance.secondary_nodes)
      instance_info = self.rpc.call_instance_info(pnode, instance.name,
                                                  instance.hypervisor)
      nodeinfo = self.rpc.call_node_info(mem_check_list, None,
                                         [instance.hypervisor], False)
      pninfo = nodeinfo[pnode]
      msg = pninfo.fail_msg
      if msg:
        # Assume the primary node is unreachable and go ahead
        self.warn.append("Can't get info from primary node %s: %s" %
                         (pnode, msg))
      else:
        (_, _, (pnhvinfo, )) = pninfo.payload
        if not isinstance(pnhvinfo.get("memory_free", None), int):
          self.warn.append("Node data from primary node %s doesn't contain"
                           " free memory information" % pnode)
        elif instance_info.fail_msg:
          self.warn.append("Can't get instance runtime information: %s" %
                           instance_info.fail_msg)
        else:
          if instance_info.payload:
            current_mem = int(instance_info.payload["memory"])
          else:
            # Assume instance not running
            # (there is a slight race condition here, but it's not very
            # probable, and we have no other way to check)
            # TODO: Describe race condition
            current_mem = 0
          #TODO(dynmem): do the appropriate check involving MINMEM
          miss_mem = (be_new[constants.BE_MAXMEM] - current_mem -
                      pnhvinfo["memory_free"])
          if miss_mem > 0:
            raise errors.OpPrereqError("This change will prevent the instance"
                                       " from starting, due to %d MB of memory"
                                       " missing on its primary node" %
                                       miss_mem, errors.ECODE_NORES)

      if be_new[constants.BE_AUTO_BALANCE]:
        for node, nres in nodeinfo.items():
          if node not in instance.secondary_nodes:
            continue
          nres.Raise("Can't get info from secondary node %s" % node,
                     prereq=True, ecode=errors.ECODE_STATE)
          (_, _, (nhvinfo, )) = nres.payload
          if not isinstance(nhvinfo.get("memory_free", None), int):
            raise errors.OpPrereqError("Secondary node %s didn't return free"
                                       " memory information" % node,
                                       errors.ECODE_STATE)
          #TODO(dynmem): do the appropriate check involving MINMEM
          elif be_new[constants.BE_MAXMEM] > nhvinfo["memory_free"]:
            raise errors.OpPrereqError("This change will prevent the instance"
                                       " from failover to its secondary node"
                                       " %s, due to not enough memory" % node,
                                       errors.ECODE_STATE)

    if self.op.runtime_mem:
      remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                instance.name,
                                                instance.hypervisor)
      remote_info.Raise("Error checking node %s" % instance.primary_node)
      if not remote_info.payload: # not running already
        raise errors.OpPrereqError("Instance %s is not running" %
                                   instance.name, errors.ECODE_STATE)

      current_memory = remote_info.payload["memory"]
      if (not self.op.force and
           (self.op.runtime_mem > self.be_proposed[constants.BE_MAXMEM] or
            self.op.runtime_mem < self.be_proposed[constants.BE_MINMEM])):
        raise errors.OpPrereqError("Instance %s must have memory between %d"
                                   " and %d MB of memory unless --force is"
                                   " given" %
                                   (instance.name,
                                    self.be_proposed[constants.BE_MINMEM],
                                    self.be_proposed[constants.BE_MAXMEM]),
                                   errors.ECODE_INVAL)

      delta = self.op.runtime_mem - current_memory
      if delta > 0:
        _CheckNodeFreeMemory(self, instance.primary_node,
                             "ballooning memory for instance %s" %
                             instance.name, delta, instance.hypervisor)

    if self.op.disks and instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Disk operations not supported for"
                                 " diskless instances", errors.ECODE_INVAL)

    def _PrepareNicCreate(_, params, private):
      self._PrepareNicModification(params, private, None, None,
                                   {}, cluster, pnode)
      return (None, None)

    def _PrepareNicMod(_, nic, params, private):
      self._PrepareNicModification(params, private, nic.ip, nic.network,
                                   nic.nicparams, cluster, pnode)
      return None

    def _PrepareNicRemove(_, params, __):
      ip = params.ip
      net = params.network
      if net is not None and ip is not None:
        self.cfg.ReleaseIp(net, ip, self.proc.GetECId())

    # Verify NIC changes (operating on copy)
    nics = instance.nics[:]
    ApplyContainerMods("NIC", nics, None, self.nicmod,
                       _PrepareNicCreate, _PrepareNicMod, _PrepareNicRemove)
    if len(nics) > constants.MAX_NICS:
      raise errors.OpPrereqError("Instance has too many network interfaces"
                                 " (%d), cannot add more" % constants.MAX_NICS,
                                 errors.ECODE_STATE)

    # Verify disk changes (operating on a copy)
    disks = instance.disks[:]
    ApplyContainerMods("disk", disks, None, self.diskmod, None, None, None)
    if len(disks) > constants.MAX_DISKS:
      raise errors.OpPrereqError("Instance has too many disks (%d), cannot add"
                                 " more" % constants.MAX_DISKS,
                                 errors.ECODE_STATE)
    disk_sizes = [disk.size for disk in instance.disks]
    disk_sizes.extend(params["size"] for (op, idx, params, private) in
                      self.diskmod if op == constants.DDM_ADD)
    ispec[constants.ISPEC_DISK_COUNT] = len(disk_sizes)
    ispec[constants.ISPEC_DISK_SIZE] = disk_sizes

    if self.op.offline is not None and self.op.offline:
      _CheckInstanceState(self, instance, CAN_CHANGE_INSTANCE_OFFLINE,
                          msg="can't change to offline")

    # Pre-compute NIC changes (necessary to use result in hooks)
    self._nic_chgdesc = []
    if self.nicmod:
      # Operate on copies as this is still in prereq
      nics = [nic.Copy() for nic in instance.nics]
      ApplyContainerMods("NIC", nics, self._nic_chgdesc, self.nicmod,
                         self._CreateNewNic, self._ApplyNicMods, None)
      self._new_nics = nics
      ispec[constants.ISPEC_NIC_COUNT] = len(self._new_nics)
    else:
      self._new_nics = None
      ispec[constants.ISPEC_NIC_COUNT] = len(instance.nics)

    if not self.op.ignore_ipolicy:
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)

      # Fill ispec with backend parameters
      ispec[constants.ISPEC_SPINDLE_USE] = \
        self.be_new.get(constants.BE_SPINDLE_USE, None)
      ispec[constants.ISPEC_CPU_COUNT] = self.be_new.get(constants.BE_VCPUS,
                                                         None)

      # Copy ispec to verify parameters with min/max values separately
      if self.op.disk_template:
        new_disk_template = self.op.disk_template
      else:
        new_disk_template = instance.disk_template
      ispec_max = ispec.copy()
      ispec_max[constants.ISPEC_MEM_SIZE] = \
        self.be_new.get(constants.BE_MAXMEM, None)
      res_max = _ComputeIPolicyInstanceSpecViolation(ipolicy, ispec_max,
                                                     new_disk_template)
      ispec_min = ispec.copy()
      ispec_min[constants.ISPEC_MEM_SIZE] = \
        self.be_new.get(constants.BE_MINMEM, None)
      res_min = _ComputeIPolicyInstanceSpecViolation(ipolicy, ispec_min,
                                                     new_disk_template)

      if (res_max or res_min):
        # FIXME: Improve error message by including information about whether
        # the upper or lower limit of the parameter fails the ipolicy.
        msg = ("Instance allocation to group %s (%s) violates policy: %s" %
               (group_info, group_info.name,
                utils.CommaJoin(set(res_max + res_min))))
        raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

  def _ConvertPlainToDrbd(self, feedback_fn):
    """Converts an instance from plain to drbd.

    """
    feedback_fn("Converting template to drbd")
    instance = self.instance
    pnode = instance.primary_node
    snode = self.op.remote_node

    assert instance.disk_template == constants.DT_PLAIN

    # create a fake disk info for _GenerateDiskTemplate
    disk_info = [{constants.IDISK_SIZE: d.size, constants.IDISK_MODE: d.mode,
                  constants.IDISK_VG: d.logical_id[0]}
                 for d in instance.disks]
    new_disks = _GenerateDiskTemplate(self, self.op.disk_template,
                                      instance.name, pnode, [snode],
                                      disk_info, None, None, 0, feedback_fn,
                                      self.diskparams)
    anno_disks = rpc.AnnotateDiskParams(constants.DT_DRBD8, new_disks,
                                        self.diskparams)
    p_excl_stor = _IsExclusiveStorageEnabledNodeName(self.cfg, pnode)
    s_excl_stor = _IsExclusiveStorageEnabledNodeName(self.cfg, snode)
    info = _GetInstanceInfoText(instance)
    feedback_fn("Creating additional volumes...")
    # first, create the missing data and meta devices
    for disk in anno_disks:
      # unfortunately this is... not too nice
      _CreateSingleBlockDev(self, pnode, instance, disk.children[1],
                            info, True, p_excl_stor)
      for child in disk.children:
        _CreateSingleBlockDev(self, snode, instance, child, info, True,
                              s_excl_stor)
    # at this stage, all new LVs have been created, we can rename the
    # old ones
    feedback_fn("Renaming original volumes...")
    rename_list = [(o, n.children[0].logical_id)
                   for (o, n) in zip(instance.disks, new_disks)]
    result = self.rpc.call_blockdev_rename(pnode, rename_list)
    result.Raise("Failed to rename original LVs")

    feedback_fn("Initializing DRBD devices...")
    # all child devices are in place, we can now create the DRBD devices
    for disk in anno_disks:
      for (node, excl_stor) in [(pnode, p_excl_stor), (snode, s_excl_stor)]:
        f_create = node == pnode
        _CreateSingleBlockDev(self, node, instance, disk, info, f_create,
                              excl_stor)

    # at this point, the instance has been modified
    instance.disk_template = constants.DT_DRBD8
    instance.disks = new_disks
    self.cfg.Update(instance, feedback_fn)

    # Release node locks while waiting for sync
    _ReleaseLocks(self, locking.LEVEL_NODE)

    # disks are created, waiting for sync
    disk_abort = not _WaitForSync(self, instance,
                                  oneshot=not self.op.wait_for_sync)
    if disk_abort:
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance, please cleanup manually")

    # Node resource locks will be released by caller

  def _ConvertDrbdToPlain(self, feedback_fn):
    """Converts an instance from drbd to plain.

    """
    instance = self.instance

    assert len(instance.secondary_nodes) == 1
    assert instance.disk_template == constants.DT_DRBD8

    pnode = instance.primary_node
    snode = instance.secondary_nodes[0]
    feedback_fn("Converting template to plain")

    old_disks = _AnnotateDiskParams(instance, instance.disks, self.cfg)
    new_disks = [d.children[0] for d in instance.disks]

    # copy over size and mode
    for parent, child in zip(old_disks, new_disks):
      child.size = parent.size
      child.mode = parent.mode

    # this is a DRBD disk, return its port to the pool
    # NOTE: this must be done right before the call to cfg.Update!
    for disk in old_disks:
      tcp_port = disk.logical_id[2]
      self.cfg.AddTcpUdpPort(tcp_port)

    # update instance structure
    instance.disks = new_disks
    instance.disk_template = constants.DT_PLAIN
    self.cfg.Update(instance, feedback_fn)

    # Release locks in case removing disks takes a while
    _ReleaseLocks(self, locking.LEVEL_NODE)

    feedback_fn("Removing volumes on the secondary node...")
    for disk in old_disks:
      self.cfg.SetDiskID(disk, snode)
      msg = self.rpc.call_blockdev_remove(snode, disk).fail_msg
      if msg:
        self.LogWarning("Could not remove block device %s on node %s,"
                        " continuing anyway: %s", disk.iv_name, snode, msg)

    feedback_fn("Removing unneeded volumes on the primary node...")
    for idx, disk in enumerate(old_disks):
      meta = disk.children[1]
      self.cfg.SetDiskID(meta, pnode)
      msg = self.rpc.call_blockdev_remove(pnode, meta).fail_msg
      if msg:
        self.LogWarning("Could not remove metadata for disk %d on node %s,"
                        " continuing anyway: %s", idx, pnode, msg)

  def _CreateNewDisk(self, idx, params, _):
    """Creates a new disk.

    """
    instance = self.instance

    # add a new disk
    if instance.disk_template in constants.DTS_FILEBASED:
      (file_driver, file_path) = instance.disks[0].logical_id
      file_path = os.path.dirname(file_path)
    else:
      file_driver = file_path = None

    disk = \
      _GenerateDiskTemplate(self, instance.disk_template, instance.name,
                            instance.primary_node, instance.secondary_nodes,
                            [params], file_path, file_driver, idx,
                            self.Log, self.diskparams)[0]

    info = _GetInstanceInfoText(instance)

    logging.info("Creating volume %s for instance %s",
                 disk.iv_name, instance.name)
    # Note: this needs to be kept in sync with _CreateDisks
    #HARDCODE
    for node in instance.all_nodes:
      f_create = (node == instance.primary_node)
      try:
        _CreateBlockDev(self, node, instance, disk, f_create, info, f_create)
      except errors.OpExecError, err:
        self.LogWarning("Failed to create volume %s (%s) on node '%s': %s",
                        disk.iv_name, disk, node, err)

    return (disk, [
      ("disk/%d" % idx, "add:size=%s,mode=%s" % (disk.size, disk.mode)),
      ])

  @staticmethod
  def _ModifyDisk(idx, disk, params, _):
    """Modifies a disk.

    """
    disk.mode = params[constants.IDISK_MODE]

    return [
      ("disk.mode/%d" % idx, disk.mode),
      ]

  def _RemoveDisk(self, idx, root, _):
    """Removes a disk.

    """
    (anno_disk,) = _AnnotateDiskParams(self.instance, [root], self.cfg)
    for node, disk in anno_disk.ComputeNodeTree(self.instance.primary_node):
      self.cfg.SetDiskID(disk, node)
      msg = self.rpc.call_blockdev_remove(node, disk).fail_msg
      if msg:
        self.LogWarning("Could not remove disk/%d on node '%s': %s,"
                        " continuing anyway", idx, node, msg)

    # if this is a DRBD disk, return its port to the pool
    if root.dev_type in constants.LDS_DRBD:
      self.cfg.AddTcpUdpPort(root.logical_id[2])

  def _CreateNewNic(self, idx, params, private):
    """Creates data structure for a new network interface.

    """
    mac = params[constants.INIC_MAC]
    ip = params.get(constants.INIC_IP, None)
    net = params.get(constants.INIC_NETWORK, None)
    net_uuid = self.cfg.LookupNetwork(net)
    #TODO: not private.filled?? can a nic have no nicparams??
    nicparams = private.filled
    nobj = objects.NIC(mac=mac, ip=ip, network=net_uuid, nicparams=nicparams)

    return (nobj, [
      ("nic.%d" % idx,
       "add:mac=%s,ip=%s,mode=%s,link=%s,network=%s" %
       (mac, ip, private.filled[constants.NIC_MODE],
       private.filled[constants.NIC_LINK],
       net)),
      ])

  def _ApplyNicMods(self, idx, nic, params, private):
    """Modifies a network interface.

    """
    changes = []

    for key in [constants.INIC_MAC, constants.INIC_IP]:
      if key in params:
        changes.append(("nic.%s/%d" % (key, idx), params[key]))
        setattr(nic, key, params[key])

    new_net = params.get(constants.INIC_NETWORK, nic.network)
    new_net_uuid = self.cfg.LookupNetwork(new_net)
    if new_net_uuid != nic.network:
      changes.append(("nic.network/%d" % idx, new_net))
      nic.network = new_net_uuid

    if private.filled:
      nic.nicparams = private.filled

      for (key, val) in nic.nicparams.items():
        changes.append(("nic.%s/%d" % (key, idx), val))

    return changes

  def Exec(self, feedback_fn):
    """Modifies an instance.

    All parameters take effect only at the next restart of the instance.

    """
    # Process here the warnings from CheckPrereq, as we don't have a
    # feedback_fn there.
    # TODO: Replace with self.LogWarning
    for warn in self.warn:
      feedback_fn("WARNING: %s" % warn)

    assert ((self.op.disk_template is None) ^
            bool(self.owned_locks(locking.LEVEL_NODE_RES))), \
      "Not owning any node resource locks"

    result = []
    instance = self.instance

    # runtime memory
    if self.op.runtime_mem:
      rpcres = self.rpc.call_instance_balloon_memory(instance.primary_node,
                                                     instance,
                                                     self.op.runtime_mem)
      rpcres.Raise("Cannot modify instance runtime memory")
      result.append(("runtime_memory", self.op.runtime_mem))

    # Apply disk changes
    ApplyContainerMods("disk", instance.disks, result, self.diskmod,
                       self._CreateNewDisk, self._ModifyDisk, self._RemoveDisk)
    _UpdateIvNames(0, instance.disks)

    if self.op.disk_template:
      if __debug__:
        check_nodes = set(instance.all_nodes)
        if self.op.remote_node:
          check_nodes.add(self.op.remote_node)
        for level in [locking.LEVEL_NODE, locking.LEVEL_NODE_RES]:
          owned = self.owned_locks(level)
          assert not (check_nodes - owned), \
            ("Not owning the correct locks, owning %r, expected at least %r" %
             (owned, check_nodes))

      r_shut = _ShutdownInstanceDisks(self, instance)
      if not r_shut:
        raise errors.OpExecError("Cannot shutdown instance disks, unable to"
                                 " proceed with disk template conversion")
      mode = (instance.disk_template, self.op.disk_template)
      try:
        self._DISK_CONVERSIONS[mode](self, feedback_fn)
      except:
        self.cfg.ReleaseDRBDMinors(instance.name)
        raise
      result.append(("disk_template", self.op.disk_template))

      assert instance.disk_template == self.op.disk_template, \
        ("Expected disk template '%s', found '%s'" %
         (self.op.disk_template, instance.disk_template))

    # Release node and resource locks if there are any (they might already have
    # been released during disk conversion)
    _ReleaseLocks(self, locking.LEVEL_NODE)
    _ReleaseLocks(self, locking.LEVEL_NODE_RES)

    # Apply NIC changes
    if self._new_nics is not None:
      instance.nics = self._new_nics
      result.extend(self._nic_chgdesc)

    # hvparams changes
    if self.op.hvparams:
      instance.hvparams = self.hv_inst
      for key, val in self.op.hvparams.iteritems():
        result.append(("hv/%s" % key, val))

    # beparams changes
    if self.op.beparams:
      instance.beparams = self.be_inst
      for key, val in self.op.beparams.iteritems():
        result.append(("be/%s" % key, val))

    # OS change
    if self.op.os_name:
      instance.os = self.op.os_name

    # osparams changes
    if self.op.osparams:
      instance.osparams = self.os_inst
      for key, val in self.op.osparams.iteritems():
        result.append(("os/%s" % key, val))

    if self.op.offline is None:
      # Ignore
      pass
    elif self.op.offline:
      # Mark instance as offline
      self.cfg.MarkInstanceOffline(instance.name)
      result.append(("admin_state", constants.ADMINST_OFFLINE))
    else:
      # Mark instance as online, but stopped
      self.cfg.MarkInstanceDown(instance.name)
      result.append(("admin_state", constants.ADMINST_DOWN))

    self.cfg.Update(instance, feedback_fn, self.proc.GetECId())

    assert not (self.owned_locks(locking.LEVEL_NODE_RES) or
                self.owned_locks(locking.LEVEL_NODE)), \
      "All node locks should have been released by now"

    return result

  _DISK_CONVERSIONS = {
    (constants.DT_PLAIN, constants.DT_DRBD8): _ConvertPlainToDrbd,
    (constants.DT_DRBD8, constants.DT_PLAIN): _ConvertDrbdToPlain,
    }


class LUInstanceChangeGroup(LogicalUnit):
  HPATH = "instance-change-group"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = _ShareAll()

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    self._ExpandAndLockInstance()

    if self.op.target_groups:
      self.req_target_uuids = map(self.cfg.LookupNodeGroup,
                                  self.op.target_groups)
    else:
      self.req_target_uuids = None

    self.op.iallocator = _GetDefaultIAllocator(self.cfg, self.op.iallocator)

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      if self.req_target_uuids:
        lock_groups = set(self.req_target_uuids)

        # Lock all groups used by instance optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        instance_groups = self.cfg.GetInstanceNodeGroups(self.op.instance_name)
        lock_groups.update(instance_groups)
      else:
        # No target groups, need to lock all of them
        lock_groups = locking.ALL_SET

      self.needed_locks[locking.LEVEL_NODEGROUP] = lock_groups

    elif level == locking.LEVEL_NODE:
      if self.req_target_uuids:
        # Lock all nodes used by instances
        self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
        self._LockInstancesNodes()

        # Lock all nodes in all potential target groups
        lock_groups = (frozenset(self.owned_locks(locking.LEVEL_NODEGROUP)) -
                       self.cfg.GetInstanceNodeGroups(self.op.instance_name))
        member_nodes = [node_name
                        for group in lock_groups
                        for node_name in self.cfg.GetNodeGroup(group).members]
        self.needed_locks[locking.LEVEL_NODE].extend(member_nodes)
      else:
        # Lock all nodes as all groups are potential targets
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def CheckPrereq(self):
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert (self.req_target_uuids is None or
            owned_groups.issuperset(self.req_target_uuids))
    assert owned_instances == set([self.op.instance_name])

    # Get instance information
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)

    # Check if node groups for locked instance are still correct
    assert owned_nodes.issuperset(self.instance.all_nodes), \
      ("Instance %s's nodes changed while we kept the lock" %
       self.op.instance_name)

    inst_groups = _CheckInstanceNodeGroups(self.cfg, self.op.instance_name,
                                           owned_groups)

    if self.req_target_uuids:
      # User requested specific target groups
      self.target_uuids = frozenset(self.req_target_uuids)
    else:
      # All groups except those used by the instance are potential targets
      self.target_uuids = owned_groups - inst_groups

    conflicting_groups = self.target_uuids & inst_groups
    if conflicting_groups:
      raise errors.OpPrereqError("Can't use group(s) '%s' as targets, they are"
                                 " used by the instance '%s'" %
                                 (utils.CommaJoin(conflicting_groups),
                                  self.op.instance_name),
                                 errors.ECODE_INVAL)

    if not self.target_uuids:
      raise errors.OpPrereqError("There are no possible target groups",
                                 errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    assert self.target_uuids

    env = {
      "TARGET_GROUPS": " ".join(self.target_uuids),
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    instances = list(self.owned_locks(locking.LEVEL_INSTANCE))

    assert instances == [self.op.instance_name], "Instance not locked"

    req = iallocator.IAReqGroupChange(instances=instances,
                                      target_groups=list(self.target_uuids))
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute solution for changing group of"
                                 " instance '%s' using iallocator '%s': %s" %
                                 (self.op.instance_name, self.op.iallocator,
                                  ial.info), errors.ECODE_NORES)

    jobs = _LoadNodeEvacResult(self, ial.result, self.op.early_release, False)

    self.LogInfo("Iallocator returned %s job(s) for changing group of"
                 " instance '%s'", len(jobs), self.op.instance_name)

    return ResultWithJobs(jobs)


class LUBackupQuery(NoHooksLU):
  """Query the exports list

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.expq = _ExportQuery(qlang.MakeSimpleFilter("node", self.op.nodes),
                             ["node", "export"], self.op.use_locking)

  def ExpandNames(self):
    self.expq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.expq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    result = {}

    for (node, expname) in self.expq.OldStyleQuery(self):
      if expname is None:
        result[node] = False
      else:
        result.setdefault(node, []).append(expname)

    return result


class _ExportQuery(_QueryBase):
  FIELDS = query.EXPORT_FIELDS

  #: The node name is not a unique key for this query
  SORT_FIELD = "node"

  def ExpandNames(self, lu):
    lu.needed_locks = {}

    # The following variables interact with _QueryBase._GetNames
    if self.names:
      self.wanted = _GetWantedNodes(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

    if self.do_locking:
      lu.share_locks = _ShareAll()
      lu.needed_locks = {
        locking.LEVEL_NODE: self.wanted,
        }

      if not self.names:
        lu.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    # TODO
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    nodes = self._GetNames(lu, lu.cfg.GetNodeList(), locking.LEVEL_NODE)

    result = []

    for (node, nres) in lu.rpc.call_export_list(nodes).items():
      if nres.fail_msg:
        result.append((node, None))
      else:
        result.extend((node, expname) for expname in nres.payload)

    return result


class LUBackupPrepare(NoHooksLU):
  """Prepares an instance for an export and returns useful information.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def CheckPrereq(self):
    """Check prerequisites.

    """
    instance_name = self.op.instance_name

    self.instance = self.cfg.GetInstanceInfo(instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

    self._cds = _GetClusterDomainSecret()

  def Exec(self, feedback_fn):
    """Prepares an instance for an export.

    """
    instance = self.instance

    if self.op.mode == constants.EXPORT_MODE_REMOTE:
      salt = utils.GenerateSecret(8)

      feedback_fn("Generating X509 certificate on %s" % instance.primary_node)
      result = self.rpc.call_x509_cert_create(instance.primary_node,
                                              constants.RIE_CERT_VALIDITY)
      result.Raise("Can't create X509 key and certificate on %s" % result.node)

      (name, cert_pem) = result.payload

      cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                             cert_pem)

      return {
        "handshake": masterd.instance.ComputeRemoteExportHandshake(self._cds),
        "x509_key_name": (name, utils.Sha1Hmac(self._cds, name, salt=salt),
                          salt),
        "x509_ca": utils.SignX509Certificate(cert, self._cds, salt),
        }

    return None


class LUBackupExport(LogicalUnit):
  """Export an instance to an image in the cluster.

  """
  HPATH = "instance-export"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check the arguments.

    """
    self.x509_key_name = self.op.x509_key_name
    self.dest_x509_ca_pem = self.op.destination_x509_ca

    if self.op.mode == constants.EXPORT_MODE_REMOTE:
      if not self.x509_key_name:
        raise errors.OpPrereqError("Missing X509 key name for encryption",
                                   errors.ECODE_INVAL)

      if not self.dest_x509_ca_pem:
        raise errors.OpPrereqError("Missing destination X509 CA",
                                   errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    # Lock all nodes for local exports
    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      # FIXME: lock only instance primary and destination node
      #
      # Sad but true, for now we have do lock all nodes, as we don't know where
      # the previous export might be, and in this LU we search for it and
      # remove it from its current node. In the future we could fix this by:
      #  - making a tasklet to search (share-lock all), then create the
      #    new one, then one to remove, after
      #  - removing the removal operation altogether
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

      # Allocations should be stopped while this LU runs with node locks, but
      # it doesn't have to be exclusive
      self.share_locks[locking.LEVEL_NODE_ALLOC] = 1
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def DeclareLocks(self, level):
    """Last minute lock declaration."""
    # All nodes are locked anyway, so nothing to do here.

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on the master, primary node and target node.

    """
    env = {
      "EXPORT_MODE": self.op.mode,
      "EXPORT_NODE": self.op.target_node,
      "EXPORT_DO_SHUTDOWN": self.op.shutdown,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      # TODO: Generic function for boolean env variables
      "REMOVE_INSTANCE": str(bool(self.op.remove_instance)),
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.instance.primary_node]

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      nl.append(self.op.target_node)

    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance and node names are valid.

    """
    instance_name = self.op.instance_name

    self.instance = self.cfg.GetInstanceInfo(instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

    if (self.op.remove_instance and
        self.instance.admin_state == constants.ADMINST_UP and
        not self.op.shutdown):
      raise errors.OpPrereqError("Can not remove instance without shutting it"
                                 " down before", errors.ECODE_STATE)

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      self.op.target_node = _ExpandNodeName(self.cfg, self.op.target_node)
      self.dst_node = self.cfg.GetNodeInfo(self.op.target_node)
      assert self.dst_node is not None

      _CheckNodeOnline(self, self.dst_node.name)
      _CheckNodeNotDrained(self, self.dst_node.name)

      self._cds = None
      self.dest_disk_info = None
      self.dest_x509_ca = None

    elif self.op.mode == constants.EXPORT_MODE_REMOTE:
      self.dst_node = None

      if len(self.op.target_node) != len(self.instance.disks):
        raise errors.OpPrereqError(("Received destination information for %s"
                                    " disks, but instance %s has %s disks") %
                                   (len(self.op.target_node), instance_name,
                                    len(self.instance.disks)),
                                   errors.ECODE_INVAL)

      cds = _GetClusterDomainSecret()

      # Check X509 key name
      try:
        (key_name, hmac_digest, hmac_salt) = self.x509_key_name
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid data for X509 key name: %s" % err,
                                   errors.ECODE_INVAL)

      if not utils.VerifySha1Hmac(cds, key_name, hmac_digest, salt=hmac_salt):
        raise errors.OpPrereqError("HMAC for X509 key name is wrong",
                                   errors.ECODE_INVAL)

      # Load and verify CA
      try:
        (cert, _) = utils.LoadSignedX509Certificate(self.dest_x509_ca_pem, cds)
      except OpenSSL.crypto.Error, err:
        raise errors.OpPrereqError("Unable to load destination X509 CA (%s)" %
                                   (err, ), errors.ECODE_INVAL)

      (errcode, msg) = utils.VerifyX509Certificate(cert, None, None)
      if errcode is not None:
        raise errors.OpPrereqError("Invalid destination X509 CA (%s)" %
                                   (msg, ), errors.ECODE_INVAL)

      self.dest_x509_ca = cert

      # Verify target information
      disk_info = []
      for idx, disk_data in enumerate(self.op.target_node):
        try:
          (host, port, magic) = \
            masterd.instance.CheckRemoteExportDiskInfo(cds, idx, disk_data)
        except errors.GenericError, err:
          raise errors.OpPrereqError("Target info for disk %s: %s" %
                                     (idx, err), errors.ECODE_INVAL)

        disk_info.append((host, port, magic))

      assert len(disk_info) == len(self.op.target_node)
      self.dest_disk_info = disk_info

    else:
      raise errors.ProgrammerError("Unhandled export mode %r" %
                                   self.op.mode)

    # instance disk type verification
    # TODO: Implement export support for file-based disks
    for disk in self.instance.disks:
      if disk.dev_type == constants.LD_FILE:
        raise errors.OpPrereqError("Export not supported for instances with"
                                   " file-based disks", errors.ECODE_INVAL)

  def _CleanupExports(self, feedback_fn):
    """Removes exports of current instance from all other nodes.

    If an instance in a cluster with nodes A..D was exported to node C, its
    exports will be removed from the nodes A, B and D.

    """
    assert self.op.mode != constants.EXPORT_MODE_REMOTE

    nodelist = self.cfg.GetNodeList()
    nodelist.remove(self.dst_node.name)

    # on one-node clusters nodelist will be empty after the removal
    # if we proceed the backup would be removed because OpBackupQuery
    # substitutes an empty list with the full cluster node list.
    iname = self.instance.name
    if nodelist:
      feedback_fn("Removing old exports for instance %s" % iname)
      exportlist = self.rpc.call_export_list(nodelist)
      for node in exportlist:
        if exportlist[node].fail_msg:
          continue
        if iname in exportlist[node].payload:
          msg = self.rpc.call_export_remove(node, iname).fail_msg
          if msg:
            self.LogWarning("Could not remove older export for instance %s"
                            " on node %s: %s", iname, node, msg)

  def Exec(self, feedback_fn):
    """Export an instance to an image in the cluster.

    """
    assert self.op.mode in constants.EXPORT_MODES

    instance = self.instance
    src_node = instance.primary_node

    if self.op.shutdown:
      # shutdown the instance, but not the disks
      feedback_fn("Shutting down instance %s" % instance.name)
      result = self.rpc.call_instance_shutdown(src_node, instance,
                                               self.op.shutdown_timeout)
      # TODO: Maybe ignore failures if ignore_remove_failures is set
      result.Raise("Could not shutdown instance %s on"
                   " node %s" % (instance.name, src_node))

    # set the disks ID correctly since call_instance_start needs the
    # correct drbd minor to create the symlinks
    for disk in instance.disks:
      self.cfg.SetDiskID(disk, src_node)

    activate_disks = (instance.admin_state != constants.ADMINST_UP)

    if activate_disks:
      # Activate the instance disks if we'exporting a stopped instance
      feedback_fn("Activating disks for %s" % instance.name)
      _StartInstanceDisks(self, instance, None)

    try:
      helper = masterd.instance.ExportInstanceHelper(self, feedback_fn,
                                                     instance)

      helper.CreateSnapshots()
      try:
        if (self.op.shutdown and
            instance.admin_state == constants.ADMINST_UP and
            not self.op.remove_instance):
          assert not activate_disks
          feedback_fn("Starting instance %s" % instance.name)
          result = self.rpc.call_instance_start(src_node,
                                                (instance, None, None), False)
          msg = result.fail_msg
          if msg:
            feedback_fn("Failed to start instance: %s" % msg)
            _ShutdownInstanceDisks(self, instance)
            raise errors.OpExecError("Could not start instance: %s" % msg)

        if self.op.mode == constants.EXPORT_MODE_LOCAL:
          (fin_resu, dresults) = helper.LocalExport(self.dst_node)
        elif self.op.mode == constants.EXPORT_MODE_REMOTE:
          connect_timeout = constants.RIE_CONNECT_TIMEOUT
          timeouts = masterd.instance.ImportExportTimeouts(connect_timeout)

          (key_name, _, _) = self.x509_key_name

          dest_ca_pem = \
            OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                            self.dest_x509_ca)

          (fin_resu, dresults) = helper.RemoteExport(self.dest_disk_info,
                                                     key_name, dest_ca_pem,
                                                     timeouts)
      finally:
        helper.Cleanup()

      # Check for backwards compatibility
      assert len(dresults) == len(instance.disks)
      assert compat.all(isinstance(i, bool) for i in dresults), \
             "Not all results are boolean: %r" % dresults

    finally:
      if activate_disks:
        feedback_fn("Deactivating disks for %s" % instance.name)
        _ShutdownInstanceDisks(self, instance)

    if not (compat.all(dresults) and fin_resu):
      failures = []
      if not fin_resu:
        failures.append("export finalization")
      if not compat.all(dresults):
        fdsk = utils.CommaJoin(idx for (idx, dsk) in enumerate(dresults)
                               if not dsk)
        failures.append("disk export: disk(s) %s" % fdsk)

      raise errors.OpExecError("Export failed, errors in %s" %
                               utils.CommaJoin(failures))

    # At this point, the export was successful, we can cleanup/finish

    # Remove instance if requested
    if self.op.remove_instance:
      feedback_fn("Removing instance %s" % instance.name)
      _RemoveInstance(self, feedback_fn, instance,
                      self.op.ignore_remove_failures)

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      self._CleanupExports(feedback_fn)

    return fin_resu, dresults


class LUBackupRemove(NoHooksLU):
  """Remove exports related to the named instance.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      # We need all nodes to be locked in order for RemoveExport to work, but
      # we don't need to lock the instance itself, as nothing will happen to it
      # (and we can remove exports also for a removed instance)
      locking.LEVEL_NODE: locking.ALL_SET,

      # Removing backups is quick, so blocking allocations is justified
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    # Allocations should be stopped while this LU runs with node locks, but it
    # doesn't have to be exclusive
    self.share_locks[locking.LEVEL_NODE_ALLOC] = 1

  def Exec(self, feedback_fn):
    """Remove any export.

    """
    instance_name = self.cfg.ExpandInstanceName(self.op.instance_name)
    # If the instance was not found we'll try with the name that was passed in.
    # This will only work if it was an FQDN, though.
    fqdn_warn = False
    if not instance_name:
      fqdn_warn = True
      instance_name = self.op.instance_name

    locked_nodes = self.owned_locks(locking.LEVEL_NODE)
    exportlist = self.rpc.call_export_list(locked_nodes)
    found = False
    for node in exportlist:
      msg = exportlist[node].fail_msg
      if msg:
        self.LogWarning("Failed to query node %s (continuing): %s", node, msg)
        continue
      if instance_name in exportlist[node].payload:
        found = True
        result = self.rpc.call_export_remove(node, instance_name)
        msg = result.fail_msg
        if msg:
          logging.error("Could not remove export for instance %s"
                        " on node %s: %s", instance_name, node, msg)

    if fqdn_warn and not found:
      feedback_fn("Export not found. If trying to remove an export belonging"
                  " to a deleted instance please use its Fully Qualified"
                  " Domain Name.")


class LUGroupAdd(LogicalUnit):
  """Logical unit for creating node groups.

  """
  HPATH = "group-add"
  HTYPE = constants.HTYPE_GROUP
  REQ_BGL = False

  def ExpandNames(self):
    # We need the new group's UUID here so that we can create and acquire the
    # corresponding lock. Later, in Exec(), we'll indicate to cfg.AddNodeGroup
    # that it should not check whether the UUID exists in the configuration.
    self.group_uuid = self.cfg.GenerateUniqueID(self.proc.GetECId())
    self.needed_locks = {}
    self.add_locks[locking.LEVEL_NODEGROUP] = self.group_uuid

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the given group name is not an existing node group
    already.

    """
    try:
      existing_uuid = self.cfg.LookupNodeGroup(self.op.group_name)
    except errors.OpPrereqError:
      pass
    else:
      raise errors.OpPrereqError("Desired group name '%s' already exists as a"
                                 " node group (UUID: %s)" %
                                 (self.op.group_name, existing_uuid),
                                 errors.ECODE_EXISTS)

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)

    if self.op.hv_state:
      self.new_hv_state = _MergeAndVerifyHvState(self.op.hv_state, None)
    else:
      self.new_hv_state = None

    if self.op.disk_state:
      self.new_disk_state = _MergeAndVerifyDiskState(self.op.disk_state, None)
    else:
      self.new_disk_state = None

    if self.op.diskparams:
      for templ in constants.DISK_TEMPLATES:
        if templ in self.op.diskparams:
          utils.ForceDictType(self.op.diskparams[templ],
                              constants.DISK_DT_TYPES)
      self.new_diskparams = self.op.diskparams
      try:
        utils.VerifyDictOptions(self.new_diskparams, constants.DISK_DT_DEFAULTS)
      except errors.OpPrereqError, err:
        raise errors.OpPrereqError("While verify diskparams options: %s" % err,
                                   errors.ECODE_INVAL)
    else:
      self.new_diskparams = {}

    if self.op.ipolicy:
      cluster = self.cfg.GetClusterInfo()
      full_ipolicy = cluster.SimpleFillIPolicy(self.op.ipolicy)
      try:
        objects.InstancePolicy.CheckParameterSyntax(full_ipolicy, False)
      except errors.ConfigurationError, err:
        raise errors.OpPrereqError("Invalid instance policy: %s" % err,
                                   errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "GROUP_NAME": self.op.group_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    """Add the node group to the cluster.

    """
    group_obj = objects.NodeGroup(name=self.op.group_name, members=[],
                                  uuid=self.group_uuid,
                                  alloc_policy=self.op.alloc_policy,
                                  ndparams=self.op.ndparams,
                                  diskparams=self.new_diskparams,
                                  ipolicy=self.op.ipolicy,
                                  hv_state_static=self.new_hv_state,
                                  disk_state_static=self.new_disk_state)

    self.cfg.AddNodeGroup(group_obj, self.proc.GetECId(), check_uuid=False)
    del self.remove_locks[locking.LEVEL_NODEGROUP]


class LUGroupAssignNodes(NoHooksLU):
  """Logical unit for assigning nodes to groups.

  """
  REQ_BGL = False

  def ExpandNames(self):
    # These raise errors.OpPrereqError on their own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)
    self.op.nodes = _GetWantedNodes(self, self.op.nodes)

    # We want to lock all the affected nodes and groups. We have readily
    # available the list of nodes, and the *destination* group. To gather the
    # list of "source" groups, we need to fetch node information later on.
    self.needed_locks = {
      locking.LEVEL_NODEGROUP: set([self.group_uuid]),
      locking.LEVEL_NODE: self.op.nodes,
      }

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert len(self.needed_locks[locking.LEVEL_NODEGROUP]) == 1

      # Try to get all affected nodes' groups without having the group or node
      # lock yet. Needs verification later in the code flow.
      groups = self.cfg.GetNodeGroupsFromNodes(self.op.nodes)

      self.needed_locks[locking.LEVEL_NODEGROUP].update(groups)

  def CheckPrereq(self):
    """Check prerequisites.

    """
    assert self.needed_locks[locking.LEVEL_NODEGROUP]
    assert (frozenset(self.owned_locks(locking.LEVEL_NODE)) ==
            frozenset(self.op.nodes))

    expected_locks = (set([self.group_uuid]) |
                      self.cfg.GetNodeGroupsFromNodes(self.op.nodes))
    actual_locks = self.owned_locks(locking.LEVEL_NODEGROUP)
    if actual_locks != expected_locks:
      raise errors.OpExecError("Nodes changed groups since locks were acquired,"
                               " current groups are '%s', used to be '%s'" %
                               (utils.CommaJoin(expected_locks),
                                utils.CommaJoin(actual_locks)))

    self.node_data = self.cfg.GetAllNodesInfo()
    self.group = self.cfg.GetNodeGroup(self.group_uuid)
    instance_data = self.cfg.GetAllInstancesInfo()

    if self.group is None:
      raise errors.OpExecError("Could not retrieve group '%s' (UUID: %s)" %
                               (self.op.group_name, self.group_uuid))

    (new_splits, previous_splits) = \
      self.CheckAssignmentForSplitInstances([(node, self.group_uuid)
                                             for node in self.op.nodes],
                                            self.node_data, instance_data)

    if new_splits:
      fmt_new_splits = utils.CommaJoin(utils.NiceSort(new_splits))

      if not self.op.force:
        raise errors.OpExecError("The following instances get split by this"
                                 " change and --force was not given: %s" %
                                 fmt_new_splits)
      else:
        self.LogWarning("This operation will split the following instances: %s",
                        fmt_new_splits)

        if previous_splits:
          self.LogWarning("In addition, these already-split instances continue"
                          " to be split across groups: %s",
                          utils.CommaJoin(utils.NiceSort(previous_splits)))

  def Exec(self, feedback_fn):
    """Assign nodes to a new group.

    """
    mods = [(node_name, self.group_uuid) for node_name in self.op.nodes]

    self.cfg.AssignGroupNodes(mods)

  @staticmethod
  def CheckAssignmentForSplitInstances(changes, node_data, instance_data):
    """Check for split instances after a node assignment.

    This method considers a series of node assignments as an atomic operation,
    and returns information about split instances after applying the set of
    changes.

    In particular, it returns information about newly split instances, and
    instances that were already split, and remain so after the change.

    Only instances whose disk template is listed in constants.DTS_INT_MIRROR are
    considered.

    @type changes: list of (node_name, new_group_uuid) pairs.
    @param changes: list of node assignments to consider.
    @param node_data: a dict with data for all nodes
    @param instance_data: a dict with all instances to consider
    @rtype: a two-tuple
    @return: a list of instances that were previously okay and result split as a
      consequence of this change, and a list of instances that were previously
      split and this change does not fix.

    """
    changed_nodes = dict((node, group) for node, group in changes
                         if node_data[node].group != group)

    all_split_instances = set()
    previously_split_instances = set()

    def InstanceNodes(instance):
      return [instance.primary_node] + list(instance.secondary_nodes)

    for inst in instance_data.values():
      if inst.disk_template not in constants.DTS_INT_MIRROR:
        continue

      instance_nodes = InstanceNodes(inst)

      if len(set(node_data[node].group for node in instance_nodes)) > 1:
        previously_split_instances.add(inst.name)

      if len(set(changed_nodes.get(node, node_data[node].group)
                 for node in instance_nodes)) > 1:
        all_split_instances.add(inst.name)

    return (list(all_split_instances - previously_split_instances),
            list(previously_split_instances & all_split_instances))


class _GroupQuery(_QueryBase):
  FIELDS = query.GROUP_FIELDS

  def ExpandNames(self, lu):
    lu.needed_locks = {}

    self._all_groups = lu.cfg.GetAllNodeGroupsInfo()
    self._cluster = lu.cfg.GetClusterInfo()
    name_to_uuid = dict((g.name, g.uuid) for g in self._all_groups.values())

    if not self.names:
      self.wanted = [name_to_uuid[name]
                     for name in utils.NiceSort(name_to_uuid.keys())]
    else:
      # Accept names to be either names or UUIDs.
      missing = []
      self.wanted = []
      all_uuid = frozenset(self._all_groups.keys())

      for name in self.names:
        if name in all_uuid:
          self.wanted.append(name)
        elif name in name_to_uuid:
          self.wanted.append(name_to_uuid[name])
        else:
          missing.append(name)

      if missing:
        raise errors.OpPrereqError("Some groups do not exist: %s" %
                                   utils.CommaJoin(missing),
                                   errors.ECODE_NOENT)

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of node groups and their attributes.

    """
    do_nodes = query.GQ_NODE in self.requested_data
    do_instances = query.GQ_INST in self.requested_data

    group_to_nodes = None
    group_to_instances = None

    # For GQ_NODE, we need to map group->[nodes], and group->[instances] for
    # GQ_INST. The former is attainable with just GetAllNodesInfo(), but for the
    # latter GetAllInstancesInfo() is not enough, for we have to go through
    # instance->node. Hence, we will need to process nodes even if we only need
    # instance information.
    if do_nodes or do_instances:
      all_nodes = lu.cfg.GetAllNodesInfo()
      group_to_nodes = dict((uuid, []) for uuid in self.wanted)
      node_to_group = {}

      for node in all_nodes.values():
        if node.group in group_to_nodes:
          group_to_nodes[node.group].append(node.name)
          node_to_group[node.name] = node.group

      if do_instances:
        all_instances = lu.cfg.GetAllInstancesInfo()
        group_to_instances = dict((uuid, []) for uuid in self.wanted)

        for instance in all_instances.values():
          node = instance.primary_node
          if node in node_to_group:
            group_to_instances[node_to_group[node]].append(instance.name)

        if not do_nodes:
          # Do not pass on node information if it was not requested.
          group_to_nodes = None

    return query.GroupQueryData(self._cluster,
                                [self._all_groups[uuid]
                                 for uuid in self.wanted],
                                group_to_nodes, group_to_instances,
                                query.GQ_DISKPARAMS in self.requested_data)


class LUGroupQuery(NoHooksLU):
  """Logical unit for querying node groups.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.gq = _GroupQuery(qlang.MakeSimpleFilter("name", self.op.names),
                          self.op.output_fields, False)

  def ExpandNames(self):
    self.gq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.gq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.gq.OldStyleQuery(self)


class LUGroupSetParams(LogicalUnit):
  """Modifies the parameters of a node group.

  """
  HPATH = "group-modify"
  HTYPE = constants.HTYPE_GROUP
  REQ_BGL = False

  def CheckArguments(self):
    all_changes = [
      self.op.ndparams,
      self.op.diskparams,
      self.op.alloc_policy,
      self.op.hv_state,
      self.op.disk_state,
      self.op.ipolicy,
      ]

    if all_changes.count(None) == len(all_changes):
      raise errors.OpPrereqError("Please pass at least one modification",
                                 errors.ECODE_INVAL)

  def ExpandNames(self):
    # This raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }

    self.share_locks[locking.LEVEL_INSTANCE] = 1

  def DeclareLocks(self, level):
    if level == locking.LEVEL_INSTANCE:
      assert not self.needed_locks[locking.LEVEL_INSTANCE]

      # Lock instances optimistically, needs verification once group lock has
      # been acquired
      self.needed_locks[locking.LEVEL_INSTANCE] = \
          self.cfg.GetNodeGroupInstances(self.group_uuid)

  @staticmethod
  def _UpdateAndVerifyDiskParams(old, new):
    """Updates and verifies disk parameters.

    """
    new_params = _GetUpdatedParams(old, new)
    utils.ForceDictType(new_params, constants.DISK_DT_TYPES)
    return new_params

  def CheckPrereq(self):
    """Check prerequisites.

    """
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))

    # Check if locked instances are still correct
    _CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instances)

    self.group = self.cfg.GetNodeGroup(self.group_uuid)
    cluster = self.cfg.GetClusterInfo()

    if self.group is None:
      raise errors.OpExecError("Could not retrieve group '%s' (UUID: %s)" %
                               (self.op.group_name, self.group_uuid))

    if self.op.ndparams:
      new_ndparams = _GetUpdatedParams(self.group.ndparams, self.op.ndparams)
      utils.ForceDictType(new_ndparams, constants.NDS_PARAMETER_TYPES)
      self.new_ndparams = new_ndparams

    if self.op.diskparams:
      diskparams = self.group.diskparams
      uavdp = self._UpdateAndVerifyDiskParams
      # For each disktemplate subdict update and verify the values
      new_diskparams = dict((dt,
                             uavdp(diskparams.get(dt, {}),
                                   self.op.diskparams[dt]))
                            for dt in constants.DISK_TEMPLATES
                            if dt in self.op.diskparams)
      # As we've all subdicts of diskparams ready, lets merge the actual
      # dict with all updated subdicts
      self.new_diskparams = objects.FillDict(diskparams, new_diskparams)
      try:
        utils.VerifyDictOptions(self.new_diskparams, constants.DISK_DT_DEFAULTS)
      except errors.OpPrereqError, err:
        raise errors.OpPrereqError("While verify diskparams options: %s" % err,
                                   errors.ECODE_INVAL)

    if self.op.hv_state:
      self.new_hv_state = _MergeAndVerifyHvState(self.op.hv_state,
                                                 self.group.hv_state_static)

    if self.op.disk_state:
      self.new_disk_state = \
        _MergeAndVerifyDiskState(self.op.disk_state,
                                 self.group.disk_state_static)

    if self.op.ipolicy:
      self.new_ipolicy = _GetUpdatedIPolicy(self.group.ipolicy,
                                            self.op.ipolicy,
                                            group_policy=True)

      new_ipolicy = cluster.SimpleFillIPolicy(self.new_ipolicy)
      inst_filter = lambda inst: inst.name in owned_instances
      instances = self.cfg.GetInstancesInfoByFilter(inst_filter).values()
      gmi = ganeti.masterd.instance
      violations = \
          _ComputeNewInstanceViolations(gmi.CalculateGroupIPolicy(cluster,
                                                                  self.group),
                                        new_ipolicy, instances, self.cfg)

      if violations:
        self.LogWarning("After the ipolicy change the following instances"
                        " violate them: %s",
                        utils.CommaJoin(violations))

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "GROUP_NAME": self.op.group_name,
      "NEW_ALLOC_POLICY": self.op.alloc_policy,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    """Modifies the node group.

    """
    result = []

    if self.op.ndparams:
      self.group.ndparams = self.new_ndparams
      result.append(("ndparams", str(self.group.ndparams)))

    if self.op.diskparams:
      self.group.diskparams = self.new_diskparams
      result.append(("diskparams", str(self.group.diskparams)))

    if self.op.alloc_policy:
      self.group.alloc_policy = self.op.alloc_policy

    if self.op.hv_state:
      self.group.hv_state_static = self.new_hv_state

    if self.op.disk_state:
      self.group.disk_state_static = self.new_disk_state

    if self.op.ipolicy:
      self.group.ipolicy = self.new_ipolicy

    self.cfg.Update(self.group, feedback_fn)
    return result


class LUGroupRemove(LogicalUnit):
  HPATH = "group-remove"
  HTYPE = constants.HTYPE_GROUP
  REQ_BGL = False

  def ExpandNames(self):
    # This will raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)
    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the given group name exists as a node group, that is
    empty (i.e., contains no nodes), and that is not the last group of the
    cluster.

    """
    # Verify that the group is empty.
    group_nodes = [node.name
                   for node in self.cfg.GetAllNodesInfo().values()
                   if node.group == self.group_uuid]

    if group_nodes:
      raise errors.OpPrereqError("Group '%s' not empty, has the following"
                                 " nodes: %s" %
                                 (self.op.group_name,
                                  utils.CommaJoin(utils.NiceSort(group_nodes))),
                                 errors.ECODE_STATE)

    # Verify the cluster would not be left group-less.
    if len(self.cfg.GetNodeGroupList()) == 1:
      raise errors.OpPrereqError("Group '%s' is the only group, cannot be"
                                 " removed" % self.op.group_name,
                                 errors.ECODE_STATE)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "GROUP_NAME": self.op.group_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    """Remove the node group.

    """
    try:
      self.cfg.RemoveNodeGroup(self.group_uuid)
    except errors.ConfigurationError:
      raise errors.OpExecError("Group '%s' with UUID %s disappeared" %
                               (self.op.group_name, self.group_uuid))

    self.remove_locks[locking.LEVEL_NODEGROUP] = self.group_uuid


class LUGroupRename(LogicalUnit):
  HPATH = "group-rename"
  HTYPE = constants.HTYPE_GROUP
  REQ_BGL = False

  def ExpandNames(self):
    # This raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }

  def CheckPrereq(self):
    """Check prerequisites.

    Ensures requested new name is not yet used.

    """
    try:
      new_name_uuid = self.cfg.LookupNodeGroup(self.op.new_name)
    except errors.OpPrereqError:
      pass
    else:
      raise errors.OpPrereqError("Desired new name '%s' clashes with existing"
                                 " node group (UUID: %s)" %
                                 (self.op.new_name, new_name_uuid),
                                 errors.ECODE_EXISTS)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OLD_NAME": self.op.group_name,
      "NEW_NAME": self.op.new_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()

    all_nodes = self.cfg.GetAllNodesInfo()
    all_nodes.pop(mn, None)

    run_nodes = [mn]
    run_nodes.extend(node.name for node in all_nodes.values()
                     if node.group == self.group_uuid)

    return (run_nodes, run_nodes)

  def Exec(self, feedback_fn):
    """Rename the node group.

    """
    group = self.cfg.GetNodeGroup(self.group_uuid)

    if group is None:
      raise errors.OpExecError("Could not retrieve group '%s' (UUID: %s)" %
                               (self.op.group_name, self.group_uuid))

    group.name = self.op.new_name
    self.cfg.Update(group, feedback_fn)

    return self.op.new_name


class LUGroupEvacuate(LogicalUnit):
  HPATH = "group-evacuate"
  HTYPE = constants.HTYPE_GROUP
  REQ_BGL = False

  def ExpandNames(self):
    # This raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    if self.op.target_groups:
      self.req_target_uuids = map(self.cfg.LookupNodeGroup,
                                  self.op.target_groups)
    else:
      self.req_target_uuids = []

    if self.group_uuid in self.req_target_uuids:
      raise errors.OpPrereqError("Group to be evacuated (%s) can not be used"
                                 " as a target group (targets are %s)" %
                                 (self.group_uuid,
                                  utils.CommaJoin(self.req_target_uuids)),
                                 errors.ECODE_INVAL)

    self.op.iallocator = _GetDefaultIAllocator(self.cfg, self.op.iallocator)

    self.share_locks = _ShareAll()
    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],
      }

  def DeclareLocks(self, level):
    if level == locking.LEVEL_INSTANCE:
      assert not self.needed_locks[locking.LEVEL_INSTANCE]

      # Lock instances optimistically, needs verification once node and group
      # locks have been acquired
      self.needed_locks[locking.LEVEL_INSTANCE] = \
        self.cfg.GetNodeGroupInstances(self.group_uuid)

    elif level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      if self.req_target_uuids:
        lock_groups = set([self.group_uuid] + self.req_target_uuids)

        # Lock all groups used by instances optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        lock_groups.update(group_uuid
                           for instance_name in
                             self.owned_locks(locking.LEVEL_INSTANCE)
                           for group_uuid in
                             self.cfg.GetInstanceNodeGroups(instance_name))
      else:
        # No target groups, need to lock all of them
        lock_groups = locking.ALL_SET

      self.needed_locks[locking.LEVEL_NODEGROUP] = lock_groups

    elif level == locking.LEVEL_NODE:
      # This will only lock the nodes in the group to be evacuated which
      # contain actual instances
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
      self._LockInstancesNodes()

      # Lock all nodes in group to be evacuated and target groups
      owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
      assert self.group_uuid in owned_groups
      member_nodes = [node_name
                      for group in owned_groups
                      for node_name in self.cfg.GetNodeGroup(group).members]
      self.needed_locks[locking.LEVEL_NODE].extend(member_nodes)

  def CheckPrereq(self):
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert owned_groups.issuperset(self.req_target_uuids)
    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    _CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instances)

    # Get instance information
    self.instances = dict(self.cfg.GetMultiInstanceInfo(owned_instances))

    # Check if node groups for locked instances are still correct
    _CheckInstancesNodeGroups(self.cfg, self.instances,
                              owned_groups, owned_nodes, self.group_uuid)

    if self.req_target_uuids:
      # User requested specific target groups
      self.target_uuids = self.req_target_uuids
    else:
      # All groups except the one to be evacuated are potential targets
      self.target_uuids = [group_uuid for group_uuid in owned_groups
                           if group_uuid != self.group_uuid]

      if not self.target_uuids:
        raise errors.OpPrereqError("There are no possible target groups",
                                   errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "GROUP_NAME": self.op.group_name,
      "TARGET_GROUPS": " ".join(self.target_uuids),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()

    assert self.group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)

    run_nodes = [mn] + self.cfg.GetNodeGroup(self.group_uuid).members

    return (run_nodes, run_nodes)

  def Exec(self, feedback_fn):
    instances = list(self.owned_locks(locking.LEVEL_INSTANCE))

    assert self.group_uuid not in self.target_uuids

    req = iallocator.IAReqGroupChange(instances=instances,
                                      target_groups=self.target_uuids)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute group evacuation using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)

    jobs = _LoadNodeEvacResult(self, ial.result, self.op.early_release, False)

    self.LogInfo("Iallocator returned %s job(s) for evacuating node group %s",
                 len(jobs), self.op.group_name)

    return ResultWithJobs(jobs)


class TagsLU(NoHooksLU): # pylint: disable=W0223
  """Generic tags LU.

  This is an abstract class which is the parent of all the other tags LUs.

  """
  def ExpandNames(self):
    self.group_uuid = None
    self.needed_locks = {}

    if self.op.kind == constants.TAG_NODE:
      self.op.name = _ExpandNodeName(self.cfg, self.op.name)
      lock_level = locking.LEVEL_NODE
      lock_name = self.op.name
    elif self.op.kind == constants.TAG_INSTANCE:
      self.op.name = _ExpandInstanceName(self.cfg, self.op.name)
      lock_level = locking.LEVEL_INSTANCE
      lock_name = self.op.name
    elif self.op.kind == constants.TAG_NODEGROUP:
      self.group_uuid = self.cfg.LookupNodeGroup(self.op.name)
      lock_level = locking.LEVEL_NODEGROUP
      lock_name = self.group_uuid
    elif self.op.kind == constants.TAG_NETWORK:
      self.network_uuid = self.cfg.LookupNetwork(self.op.name)
      lock_level = locking.LEVEL_NETWORK
      lock_name = self.network_uuid
    else:
      lock_level = None
      lock_name = None

    if lock_level and getattr(self.op, "use_locking", True):
      self.needed_locks[lock_level] = lock_name

    # FIXME: Acquire BGL for cluster tag operations (as of this writing it's
    # not possible to acquire the BGL based on opcode parameters)

  def CheckPrereq(self):
    """Check prerequisites.

    """
    if self.op.kind == constants.TAG_CLUSTER:
      self.target = self.cfg.GetClusterInfo()
    elif self.op.kind == constants.TAG_NODE:
      self.target = self.cfg.GetNodeInfo(self.op.name)
    elif self.op.kind == constants.TAG_INSTANCE:
      self.target = self.cfg.GetInstanceInfo(self.op.name)
    elif self.op.kind == constants.TAG_NODEGROUP:
      self.target = self.cfg.GetNodeGroup(self.group_uuid)
    elif self.op.kind == constants.TAG_NETWORK:
      self.target = self.cfg.GetNetwork(self.network_uuid)
    else:
      raise errors.OpPrereqError("Wrong tag type requested (%s)" %
                                 str(self.op.kind), errors.ECODE_INVAL)


class LUTagsGet(TagsLU):
  """Returns the tags of a given object.

  """
  REQ_BGL = False

  def ExpandNames(self):
    TagsLU.ExpandNames(self)

    # Share locks as this is only a read operation
    self.share_locks = _ShareAll()

  def Exec(self, feedback_fn):
    """Returns the tag list.

    """
    return list(self.target.GetTags())


class LUTagsSearch(NoHooksLU):
  """Searches the tags for a given pattern.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def CheckPrereq(self):
    """Check prerequisites.

    This checks the pattern passed for validity by compiling it.

    """
    try:
      self.re = re.compile(self.op.pattern)
    except re.error, err:
      raise errors.OpPrereqError("Invalid search pattern '%s': %s" %
                                 (self.op.pattern, err), errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Returns the tag list.

    """
    cfg = self.cfg
    tgts = [("/cluster", cfg.GetClusterInfo())]
    ilist = cfg.GetAllInstancesInfo().values()
    tgts.extend([("/instances/%s" % i.name, i) for i in ilist])
    nlist = cfg.GetAllNodesInfo().values()
    tgts.extend([("/nodes/%s" % n.name, n) for n in nlist])
    tgts.extend(("/nodegroup/%s" % n.name, n)
                for n in cfg.GetAllNodeGroupsInfo().values())
    results = []
    for path, target in tgts:
      for tag in target.GetTags():
        if self.re.search(tag):
          results.append((path, tag))
    return results


class LUTagsSet(TagsLU):
  """Sets a tag on a given object.

  """
  REQ_BGL = False

  def CheckPrereq(self):
    """Check prerequisites.

    This checks the type and length of the tag name and value.

    """
    TagsLU.CheckPrereq(self)
    for tag in self.op.tags:
      objects.TaggableObject.ValidateTag(tag)

  def Exec(self, feedback_fn):
    """Sets the tag.

    """
    try:
      for tag in self.op.tags:
        self.target.AddTag(tag)
    except errors.TagError, err:
      raise errors.OpExecError("Error while setting tag: %s" % str(err))
    self.cfg.Update(self.target, feedback_fn)


class LUTagsDel(TagsLU):
  """Delete a list of tags from a given object.

  """
  REQ_BGL = False

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that we have the given tag.

    """
    TagsLU.CheckPrereq(self)
    for tag in self.op.tags:
      objects.TaggableObject.ValidateTag(tag)
    del_tags = frozenset(self.op.tags)
    cur_tags = self.target.GetTags()

    diff_tags = del_tags - cur_tags
    if diff_tags:
      diff_names = ("'%s'" % i for i in sorted(diff_tags))
      raise errors.OpPrereqError("Tag(s) %s not found" %
                                 (utils.CommaJoin(diff_names), ),
                                 errors.ECODE_NOENT)

  def Exec(self, feedback_fn):
    """Remove the tag from the object.

    """
    for tag in self.op.tags:
      self.target.RemoveTag(tag)
    self.cfg.Update(self.target, feedback_fn)


class LUTestDelay(NoHooksLU):
  """Sleep for a specified amount of time.

  This LU sleeps on the master and/or nodes for a specified amount of
  time.

  """
  REQ_BGL = False

  def ExpandNames(self):
    """Expand names and set required locks.

    This expands the node list, if any.

    """
    self.needed_locks = {}
    if self.op.on_nodes:
      # _GetWantedNodes can be used here, but is not always appropriate to use
      # this way in ExpandNames. Check LogicalUnit.ExpandNames docstring for
      # more information.
      self.op.on_nodes = _GetWantedNodes(self, self.op.on_nodes)
      self.needed_locks[locking.LEVEL_NODE] = self.op.on_nodes

  def _TestDelay(self):
    """Do the actual sleep.

    """
    if self.op.on_master:
      if not utils.TestDelay(self.op.duration):
        raise errors.OpExecError("Error during master delay test")
    if self.op.on_nodes:
      result = self.rpc.call_test_delay(self.op.on_nodes, self.op.duration)
      for node, node_result in result.items():
        node_result.Raise("Failure during rpc call to node %s" % node)

  def Exec(self, feedback_fn):
    """Execute the test delay opcode, with the wanted repetitions.

    """
    if self.op.repeat == 0:
      self._TestDelay()
    else:
      top_value = self.op.repeat - 1
      for i in range(self.op.repeat):
        self.LogInfo("Test delay iteration %d/%d", i, top_value)
        self._TestDelay()


class LURestrictedCommand(NoHooksLU):
  """Logical unit for executing restricted commands.

  """
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.nodes:
      self.op.nodes = _GetWantedNodes(self, self.op.nodes)

    self.needed_locks = {
      locking.LEVEL_NODE: self.op.nodes,
      }
    self.share_locks = {
      locking.LEVEL_NODE: not self.op.use_locking,
      }

  def CheckPrereq(self):
    """Check prerequisites.

    """

  def Exec(self, feedback_fn):
    """Execute restricted command and return output.

    """
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    # Check if correct locks are held
    assert set(self.op.nodes).issubset(owned_nodes)

    rpcres = self.rpc.call_restricted_command(self.op.nodes, self.op.command)

    result = []

    for node_name in self.op.nodes:
      nres = rpcres[node_name]
      if nres.fail_msg:
        msg = ("Command '%s' on node '%s' failed: %s" %
               (self.op.command, node_name, nres.fail_msg))
        result.append((False, msg))
      else:
        result.append((True, nres.payload))

    return result


class LUTestJqueue(NoHooksLU):
  """Utility LU to test some aspects of the job queue.

  """
  REQ_BGL = False

  # Must be lower than default timeout for WaitForJobChange to see whether it
  # notices changed jobs
  _CLIENT_CONNECT_TIMEOUT = 20.0
  _CLIENT_CONFIRM_TIMEOUT = 60.0

  @classmethod
  def _NotifyUsingSocket(cls, cb, errcls):
    """Opens a Unix socket and waits for another program to connect.

    @type cb: callable
    @param cb: Callback to send socket name to client
    @type errcls: class
    @param errcls: Exception class to use for errors

    """
    # Using a temporary directory as there's no easy way to create temporary
    # sockets without writing a custom loop around tempfile.mktemp and
    # socket.bind
    tmpdir = tempfile.mkdtemp()
    try:
      tmpsock = utils.PathJoin(tmpdir, "sock")

      logging.debug("Creating temporary socket at %s", tmpsock)
      sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      try:
        sock.bind(tmpsock)
        sock.listen(1)

        # Send details to client
        cb(tmpsock)

        # Wait for client to connect before continuing
        sock.settimeout(cls._CLIENT_CONNECT_TIMEOUT)
        try:
          (conn, _) = sock.accept()
        except socket.error, err:
          raise errcls("Client didn't connect in time (%s)" % err)
      finally:
        sock.close()
    finally:
      # Remove as soon as client is connected
      shutil.rmtree(tmpdir)

    # Wait for client to close
    try:
      try:
        # pylint: disable=E1101
        # Instance of '_socketobject' has no ... member
        conn.settimeout(cls._CLIENT_CONFIRM_TIMEOUT)
        conn.recv(1)
      except socket.error, err:
        raise errcls("Client failed to confirm notification (%s)" % err)
    finally:
      conn.close()

  def _SendNotification(self, test, arg, sockname):
    """Sends a notification to the client.

    @type test: string
    @param test: Test name
    @param arg: Test argument (depends on test)
    @type sockname: string
    @param sockname: Socket path

    """
    self.Log(constants.ELOG_JQUEUE_TEST, (sockname, test, arg))

  def _Notify(self, prereq, test, arg):
    """Notifies the client of a test.

    @type prereq: bool
    @param prereq: Whether this is a prereq-phase test
    @type test: string
    @param test: Test name
    @param arg: Test argument (depends on test)

    """
    if prereq:
      errcls = errors.OpPrereqError
    else:
      errcls = errors.OpExecError

    return self._NotifyUsingSocket(compat.partial(self._SendNotification,
                                                  test, arg),
                                   errcls)

  def CheckArguments(self):
    self.checkargs_calls = getattr(self, "checkargs_calls", 0) + 1
    self.expandnames_calls = 0

  def ExpandNames(self):
    checkargs_calls = getattr(self, "checkargs_calls", 0)
    if checkargs_calls < 1:
      raise errors.ProgrammerError("CheckArguments was not called")

    self.expandnames_calls += 1

    if self.op.notify_waitlock:
      self._Notify(True, constants.JQT_EXPANDNAMES, None)

    self.LogInfo("Expanding names")

    # Get lock on master node (just to get a lock, not for a particular reason)
    self.needed_locks = {
      locking.LEVEL_NODE: self.cfg.GetMasterNode(),
      }

  def Exec(self, feedback_fn):
    if self.expandnames_calls < 1:
      raise errors.ProgrammerError("ExpandNames was not called")

    if self.op.notify_exec:
      self._Notify(False, constants.JQT_EXEC, None)

    self.LogInfo("Executing")

    if self.op.log_messages:
      self._Notify(False, constants.JQT_STARTMSG, len(self.op.log_messages))
      for idx, msg in enumerate(self.op.log_messages):
        self.LogInfo("Sending log message %s", idx + 1)
        feedback_fn(constants.JQT_MSGPREFIX + msg)
        # Report how many test messages have been sent
        self._Notify(False, constants.JQT_LOGMSG, idx + 1)

    if self.op.fail:
      raise errors.OpExecError("Opcode failure was requested")

    return True


class LUTestAllocator(NoHooksLU):
  """Run allocator tests.

  This LU runs the allocator tests

  """
  def CheckPrereq(self):
    """Check prerequisites.

    This checks the opcode parameters depending on the director and mode test.

    """
    if self.op.mode in (constants.IALLOCATOR_MODE_ALLOC,
                        constants.IALLOCATOR_MODE_MULTI_ALLOC):
      for attr in ["memory", "disks", "disk_template",
                   "os", "tags", "nics", "vcpus"]:
        if not hasattr(self.op, attr):
          raise errors.OpPrereqError("Missing attribute '%s' on opcode input" %
                                     attr, errors.ECODE_INVAL)
      iname = self.cfg.ExpandInstanceName(self.op.name)
      if iname is not None:
        raise errors.OpPrereqError("Instance '%s' already in the cluster" %
                                   iname, errors.ECODE_EXISTS)
      if not isinstance(self.op.nics, list):
        raise errors.OpPrereqError("Invalid parameter 'nics'",
                                   errors.ECODE_INVAL)
      if not isinstance(self.op.disks, list):
        raise errors.OpPrereqError("Invalid parameter 'disks'",
                                   errors.ECODE_INVAL)
      for row in self.op.disks:
        if (not isinstance(row, dict) or
            constants.IDISK_SIZE not in row or
            not isinstance(row[constants.IDISK_SIZE], int) or
            constants.IDISK_MODE not in row or
            row[constants.IDISK_MODE] not in constants.DISK_ACCESS_SET):
          raise errors.OpPrereqError("Invalid contents of the 'disks'"
                                     " parameter", errors.ECODE_INVAL)
      if self.op.hypervisor is None:
        self.op.hypervisor = self.cfg.GetHypervisorType()
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      fname = _ExpandInstanceName(self.cfg, self.op.name)
      self.op.name = fname
      self.relocate_from = \
          list(self.cfg.GetInstanceInfo(fname).secondary_nodes)
    elif self.op.mode in (constants.IALLOCATOR_MODE_CHG_GROUP,
                          constants.IALLOCATOR_MODE_NODE_EVAC):
      if not self.op.instances:
        raise errors.OpPrereqError("Missing instances", errors.ECODE_INVAL)
      self.op.instances = _GetWantedInstances(self, self.op.instances)
    else:
      raise errors.OpPrereqError("Invalid test allocator mode '%s'" %
                                 self.op.mode, errors.ECODE_INVAL)

    if self.op.direction == constants.IALLOCATOR_DIR_OUT:
      if self.op.iallocator is None:
        raise errors.OpPrereqError("Missing allocator name",
                                   errors.ECODE_INVAL)
    elif self.op.direction != constants.IALLOCATOR_DIR_IN:
      raise errors.OpPrereqError("Wrong allocator test '%s'" %
                                 self.op.direction, errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Run the allocator test.

    """
    if self.op.mode == constants.IALLOCATOR_MODE_ALLOC:
      req = iallocator.IAReqInstanceAlloc(name=self.op.name,
                                          memory=self.op.memory,
                                          disks=self.op.disks,
                                          disk_template=self.op.disk_template,
                                          os=self.op.os,
                                          tags=self.op.tags,
                                          nics=self.op.nics,
                                          vcpus=self.op.vcpus,
                                          spindle_use=self.op.spindle_use,
                                          hypervisor=self.op.hypervisor,
                                          node_whitelist=None)
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      req = iallocator.IAReqRelocate(name=self.op.name,
                                     relocate_from=list(self.relocate_from))
    elif self.op.mode == constants.IALLOCATOR_MODE_CHG_GROUP:
      req = iallocator.IAReqGroupChange(instances=self.op.instances,
                                        target_groups=self.op.target_groups)
    elif self.op.mode == constants.IALLOCATOR_MODE_NODE_EVAC:
      req = iallocator.IAReqNodeEvac(instances=self.op.instances,
                                     evac_mode=self.op.evac_mode)
    elif self.op.mode == constants.IALLOCATOR_MODE_MULTI_ALLOC:
      disk_template = self.op.disk_template
      insts = [iallocator.IAReqInstanceAlloc(name="%s%s" % (self.op.name, idx),
                                             memory=self.op.memory,
                                             disks=self.op.disks,
                                             disk_template=disk_template,
                                             os=self.op.os,
                                             tags=self.op.tags,
                                             nics=self.op.nics,
                                             vcpus=self.op.vcpus,
                                             spindle_use=self.op.spindle_use,
                                             hypervisor=self.op.hypervisor)
               for idx in range(self.op.count)]
      req = iallocator.IAReqMultiInstanceAlloc(instances=insts)
    else:
      raise errors.ProgrammerError("Uncatched mode %s in"
                                   " LUTestAllocator.Exec", self.op.mode)

    ial = iallocator.IAllocator(self.cfg, self.rpc, req)
    if self.op.direction == constants.IALLOCATOR_DIR_IN:
      result = ial.in_text
    else:
      ial.Run(self.op.iallocator, validate=False)
      result = ial.out_text
    return result


class LUNetworkAdd(LogicalUnit):
  """Logical unit for creating networks.

  """
  HPATH = "network-add"
  HTYPE = constants.HTYPE_NETWORK
  REQ_BGL = False

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def CheckArguments(self):
    if self.op.mac_prefix:
      self.op.mac_prefix = \
        utils.NormalizeAndValidateThreeOctetMacPrefix(self.op.mac_prefix)

  def ExpandNames(self):
    self.network_uuid = self.cfg.GenerateUniqueID(self.proc.GetECId())

    if self.op.conflicts_check:
      self.share_locks[locking.LEVEL_NODE] = 1
      self.share_locks[locking.LEVEL_NODE_ALLOC] = 1
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }
    else:
      self.needed_locks = {}

    self.add_locks[locking.LEVEL_NETWORK] = self.network_uuid

  def CheckPrereq(self):
    if self.op.network is None:
      raise errors.OpPrereqError("Network must be given",
                                 errors.ECODE_INVAL)

    try:
      existing_uuid = self.cfg.LookupNetwork(self.op.network_name)
    except errors.OpPrereqError:
      pass
    else:
      raise errors.OpPrereqError("Desired network name '%s' already exists as a"
                                 " network (UUID: %s)" %
                                 (self.op.network_name, existing_uuid),
                                 errors.ECODE_EXISTS)

    # Check tag validity
    for tag in self.op.tags:
      objects.TaggableObject.ValidateTag(tag)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    args = {
      "name": self.op.network_name,
      "subnet": self.op.network,
      "gateway": self.op.gateway,
      "network6": self.op.network6,
      "gateway6": self.op.gateway6,
      "mac_prefix": self.op.mac_prefix,
      "tags": self.op.tags,
      }
    return _BuildNetworkHookEnv(**args) # pylint: disable=W0142

  def Exec(self, feedback_fn):
    """Add the ip pool to the cluster.

    """
    nobj = objects.Network(name=self.op.network_name,
                           network=self.op.network,
                           gateway=self.op.gateway,
                           network6=self.op.network6,
                           gateway6=self.op.gateway6,
                           mac_prefix=self.op.mac_prefix,
                           uuid=self.network_uuid)
    # Initialize the associated address pool
    try:
      pool = network.AddressPool.InitializeNetwork(nobj)
    except errors.AddressPoolError, err:
      raise errors.OpExecError("Cannot create IP address pool for network"
                               " '%s': %s" % (self.op.network_name, err))

    # Check if we need to reserve the nodes and the cluster master IP
    # These may not be allocated to any instances in routed mode, as
    # they wouldn't function anyway.
    if self.op.conflicts_check:
      for node in self.cfg.GetAllNodesInfo().values():
        for ip in [node.primary_ip, node.secondary_ip]:
          try:
            if pool.Contains(ip):
              pool.Reserve(ip)
              self.LogInfo("Reserved IP address of node '%s' (%s)",
                           node.name, ip)
          except errors.AddressPoolError, err:
            self.LogWarning("Cannot reserve IP address '%s' of node '%s': %s",
                            ip, node.name, err)

      master_ip = self.cfg.GetClusterInfo().master_ip
      try:
        if pool.Contains(master_ip):
          pool.Reserve(master_ip)
          self.LogInfo("Reserved cluster master IP address (%s)", master_ip)
      except errors.AddressPoolError, err:
        self.LogWarning("Cannot reserve cluster master IP address (%s): %s",
                        master_ip, err)

    if self.op.add_reserved_ips:
      for ip in self.op.add_reserved_ips:
        try:
          pool.Reserve(ip, external=True)
        except errors.AddressPoolError, err:
          raise errors.OpExecError("Cannot reserve IP address '%s': %s" %
                                   (ip, err))

    if self.op.tags:
      for tag in self.op.tags:
        nobj.AddTag(tag)

    self.cfg.AddNetwork(nobj, self.proc.GetECId(), check_uuid=False)
    del self.remove_locks[locking.LEVEL_NETWORK]


class LUNetworkRemove(LogicalUnit):
  HPATH = "network-remove"
  HTYPE = constants.HTYPE_NETWORK
  REQ_BGL = False

  def ExpandNames(self):
    self.network_uuid = self.cfg.LookupNetwork(self.op.network_name)

    self.share_locks[locking.LEVEL_NODEGROUP] = 1
    self.needed_locks = {
      locking.LEVEL_NETWORK: [self.network_uuid],
      locking.LEVEL_NODEGROUP: locking.ALL_SET,
      }

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the given network name exists as a network, that is
    empty (i.e., contains no nodes), and that is not the last group of the
    cluster.

    """
    # Verify that the network is not conncted.
    node_groups = [group.name
                   for group in self.cfg.GetAllNodeGroupsInfo().values()
                   if self.network_uuid in group.networks]

    if node_groups:
      self.LogWarning("Network '%s' is connected to the following"
                      " node groups: %s" %
                      (self.op.network_name,
                       utils.CommaJoin(utils.NiceSort(node_groups))))
      raise errors.OpPrereqError("Network still connected", errors.ECODE_STATE)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "NETWORK_NAME": self.op.network_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    """Remove the network.

    """
    try:
      self.cfg.RemoveNetwork(self.network_uuid)
    except errors.ConfigurationError:
      raise errors.OpExecError("Network '%s' with UUID %s disappeared" %
                               (self.op.network_name, self.network_uuid))


class LUNetworkSetParams(LogicalUnit):
  """Modifies the parameters of a network.

  """
  HPATH = "network-modify"
  HTYPE = constants.HTYPE_NETWORK
  REQ_BGL = False

  def CheckArguments(self):
    if (self.op.gateway and
        (self.op.add_reserved_ips or self.op.remove_reserved_ips)):
      raise errors.OpPrereqError("Cannot modify gateway and reserved ips"
                                 " at once", errors.ECODE_INVAL)

  def ExpandNames(self):
    self.network_uuid = self.cfg.LookupNetwork(self.op.network_name)

    self.needed_locks = {
      locking.LEVEL_NETWORK: [self.network_uuid],
      }

  def CheckPrereq(self):
    """Check prerequisites.

    """
    self.network = self.cfg.GetNetwork(self.network_uuid)
    self.gateway = self.network.gateway
    self.mac_prefix = self.network.mac_prefix
    self.network6 = self.network.network6
    self.gateway6 = self.network.gateway6
    self.tags = self.network.tags

    self.pool = network.AddressPool(self.network)

    if self.op.gateway:
      if self.op.gateway == constants.VALUE_NONE:
        self.gateway = None
      else:
        self.gateway = self.op.gateway
        if self.pool.IsReserved(self.gateway):
          raise errors.OpPrereqError("Gateway IP address '%s' is already"
                                     " reserved" % self.gateway,
                                     errors.ECODE_STATE)

    if self.op.mac_prefix:
      if self.op.mac_prefix == constants.VALUE_NONE:
        self.mac_prefix = None
      else:
        self.mac_prefix = \
          utils.NormalizeAndValidateThreeOctetMacPrefix(self.op.mac_prefix)

    if self.op.gateway6:
      if self.op.gateway6 == constants.VALUE_NONE:
        self.gateway6 = None
      else:
        self.gateway6 = self.op.gateway6

    if self.op.network6:
      if self.op.network6 == constants.VALUE_NONE:
        self.network6 = None
      else:
        self.network6 = self.op.network6

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    args = {
      "name": self.op.network_name,
      "subnet": self.network.network,
      "gateway": self.gateway,
      "network6": self.network6,
      "gateway6": self.gateway6,
      "mac_prefix": self.mac_prefix,
      "tags": self.tags,
      }
    return _BuildNetworkHookEnv(**args) # pylint: disable=W0142

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def Exec(self, feedback_fn):
    """Modifies the network.

    """
    #TODO: reserve/release via temporary reservation manager
    #      extend cfg.ReserveIp/ReleaseIp with the external flag
    if self.op.gateway:
      if self.gateway == self.network.gateway:
        self.LogWarning("Gateway is already %s", self.gateway)
      else:
        if self.gateway:
          self.pool.Reserve(self.gateway, external=True)
        if self.network.gateway:
          self.pool.Release(self.network.gateway, external=True)
        self.network.gateway = self.gateway

    if self.op.add_reserved_ips:
      for ip in self.op.add_reserved_ips:
        try:
          if self.pool.IsReserved(ip):
            self.LogWarning("IP address %s is already reserved", ip)
          else:
            self.pool.Reserve(ip, external=True)
        except errors.AddressPoolError, err:
          self.LogWarning("Cannot reserve IP address %s: %s", ip, err)

    if self.op.remove_reserved_ips:
      for ip in self.op.remove_reserved_ips:
        if ip == self.network.gateway:
          self.LogWarning("Cannot unreserve Gateway's IP")
          continue
        try:
          if not self.pool.IsReserved(ip):
            self.LogWarning("IP address %s is already unreserved", ip)
          else:
            self.pool.Release(ip, external=True)
        except errors.AddressPoolError, err:
          self.LogWarning("Cannot release IP address %s: %s", ip, err)

    if self.op.mac_prefix:
      self.network.mac_prefix = self.mac_prefix

    if self.op.network6:
      self.network.network6 = self.network6

    if self.op.gateway6:
      self.network.gateway6 = self.gateway6

    self.pool.Validate()

    self.cfg.Update(self.network, feedback_fn)


class _NetworkQuery(_QueryBase):
  FIELDS = query.NETWORK_FIELDS

  def ExpandNames(self, lu):
    lu.needed_locks = {}
    lu.share_locks = _ShareAll()

    self.do_locking = self.use_locking

    all_networks = lu.cfg.GetAllNetworksInfo()
    name_to_uuid = dict((n.name, n.uuid) for n in all_networks.values())

    if self.names:
      missing = []
      self.wanted = []

      for name in self.names:
        if name in name_to_uuid:
          self.wanted.append(name_to_uuid[name])
        else:
          missing.append(name)

      if missing:
        raise errors.OpPrereqError("Some networks do not exist: %s" % missing,
                                   errors.ECODE_NOENT)
    else:
      self.wanted = locking.ALL_SET

    if self.do_locking:
      lu.needed_locks[locking.LEVEL_NETWORK] = self.wanted
      if query.NETQ_INST in self.requested_data:
        lu.needed_locks[locking.LEVEL_INSTANCE] = locking.ALL_SET
      if query.NETQ_GROUP in self.requested_data:
        lu.needed_locks[locking.LEVEL_NODEGROUP] = locking.ALL_SET

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of networks and their attributes.

    """
    all_networks = lu.cfg.GetAllNetworksInfo()

    network_uuids = self._GetNames(lu, all_networks.keys(),
                                   locking.LEVEL_NETWORK)

    do_instances = query.NETQ_INST in self.requested_data
    do_groups = query.NETQ_GROUP in self.requested_data

    network_to_instances = None
    network_to_groups = None

    # For NETQ_GROUP, we need to map network->[groups]
    if do_groups:
      all_groups = lu.cfg.GetAllNodeGroupsInfo()
      network_to_groups = dict((uuid, []) for uuid in network_uuids)
      for _, group in all_groups.iteritems():
        for net_uuid in network_uuids:
          netparams = group.networks.get(net_uuid, None)
          if netparams:
            info = (group.name, netparams[constants.NIC_MODE],
                    netparams[constants.NIC_LINK])

            network_to_groups[net_uuid].append(info)

    if do_instances:
      all_instances = lu.cfg.GetAllInstancesInfo()
      network_to_instances = dict((uuid, []) for uuid in network_uuids)
      for instance in all_instances.values():
        for nic in instance.nics:
          if nic.network in network_uuids:
            network_to_instances[nic.network].append(instance.name)
            break

    if query.NETQ_STATS in self.requested_data:
      stats = \
        dict((uuid,
              self._GetStats(network.AddressPool(all_networks[uuid])))
             for uuid in network_uuids)
    else:
      stats = None

    return query.NetworkQueryData([all_networks[uuid]
                                   for uuid in network_uuids],
                                   network_to_groups,
                                   network_to_instances,
                                   stats)

  @staticmethod
  def _GetStats(pool):
    """Returns statistics for a network address pool.

    """
    return {
      "free_count": pool.GetFreeCount(),
      "reserved_count": pool.GetReservedCount(),
      "map": pool.GetMap(),
      "external_reservations":
        utils.CommaJoin(pool.GetExternalReservations()),
      }


class LUNetworkQuery(NoHooksLU):
  """Logical unit for querying networks.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.nq = _NetworkQuery(qlang.MakeSimpleFilter("name", self.op.names),
                            self.op.output_fields, self.op.use_locking)

  def ExpandNames(self):
    self.nq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.nq.OldStyleQuery(self)


class LUNetworkConnect(LogicalUnit):
  """Connect a network to a nodegroup

  """
  HPATH = "network-connect"
  HTYPE = constants.HTYPE_NETWORK
  REQ_BGL = False

  def ExpandNames(self):
    self.network_name = self.op.network_name
    self.group_name = self.op.group_name
    self.network_mode = self.op.network_mode
    self.network_link = self.op.network_link

    self.network_uuid = self.cfg.LookupNetwork(self.network_name)
    self.group_uuid = self.cfg.LookupNodeGroup(self.group_name)

    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }
    self.share_locks[locking.LEVEL_INSTANCE] = 1

    if self.op.conflicts_check:
      self.needed_locks[locking.LEVEL_NETWORK] = [self.network_uuid]
      self.share_locks[locking.LEVEL_NETWORK] = 1

  def DeclareLocks(self, level):
    if level == locking.LEVEL_INSTANCE:
      assert not self.needed_locks[locking.LEVEL_INSTANCE]

      # Lock instances optimistically, needs verification once group lock has
      # been acquired
      if self.op.conflicts_check:
        self.needed_locks[locking.LEVEL_INSTANCE] = \
            self.cfg.GetNodeGroupInstances(self.group_uuid)

  def BuildHooksEnv(self):
    ret = {
      "GROUP_NAME": self.group_name,
      "GROUP_NETWORK_MODE": self.network_mode,
      "GROUP_NETWORK_LINK": self.network_link,
      }
    return ret

  def BuildHooksNodes(self):
    nodes = self.cfg.GetNodeGroup(self.group_uuid).members
    return (nodes, nodes)

  def CheckPrereq(self):
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))

    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    if self.op.conflicts_check:
      _CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instances)

    self.netparams = {
      constants.NIC_MODE: self.network_mode,
      constants.NIC_LINK: self.network_link,
      }
    objects.NIC.CheckParameterSyntax(self.netparams)

    self.group = self.cfg.GetNodeGroup(self.group_uuid)
    #if self.network_mode == constants.NIC_MODE_BRIDGED:
    #  _CheckNodeGroupBridgesExist(self, self.network_link, self.group_uuid)
    self.connected = False
    if self.network_uuid in self.group.networks:
      self.LogWarning("Network '%s' is already mapped to group '%s'" %
                      (self.network_name, self.group.name))
      self.connected = True

    # check only if not already connected
    elif self.op.conflicts_check:
      pool = network.AddressPool(self.cfg.GetNetwork(self.network_uuid))

      _NetworkConflictCheck(self, lambda nic: pool.Contains(nic.ip),
                            "connect to", owned_instances)

  def Exec(self, feedback_fn):
    # Connect the network and update the group only if not already connected
    if not self.connected:
      self.group.networks[self.network_uuid] = self.netparams
      self.cfg.Update(self.group, feedback_fn)


def _NetworkConflictCheck(lu, check_fn, action, instances):
  """Checks for network interface conflicts with a network.

  @type lu: L{LogicalUnit}
  @type check_fn: callable receiving one parameter (L{objects.NIC}) and
    returning boolean
  @param check_fn: Function checking for conflict
  @type action: string
  @param action: Part of error message (see code)
  @raise errors.OpPrereqError: If conflicting IP addresses are found.

  """
  conflicts = []

  for (_, instance) in lu.cfg.GetMultiInstanceInfo(instances):
    instconflicts = [(idx, nic.ip)
                     for (idx, nic) in enumerate(instance.nics)
                     if check_fn(nic)]

    if instconflicts:
      conflicts.append((instance.name, instconflicts))

  if conflicts:
    lu.LogWarning("IP addresses from network '%s', which is about to %s"
                  " node group '%s', are in use: %s" %
                  (lu.network_name, action, lu.group.name,
                   utils.CommaJoin(("%s: %s" %
                                    (name, _FmtNetworkConflict(details)))
                                   for (name, details) in conflicts)))

    raise errors.OpPrereqError("Conflicting IP addresses found; "
                               " remove/modify the corresponding network"
                               " interfaces", errors.ECODE_STATE)


def _FmtNetworkConflict(details):
  """Utility for L{_NetworkConflictCheck}.

  """
  return utils.CommaJoin("nic%s/%s" % (idx, ipaddr)
                         for (idx, ipaddr) in details)


class LUNetworkDisconnect(LogicalUnit):
  """Disconnect a network to a nodegroup

  """
  HPATH = "network-disconnect"
  HTYPE = constants.HTYPE_NETWORK
  REQ_BGL = False

  def ExpandNames(self):
    self.network_name = self.op.network_name
    self.group_name = self.op.group_name

    self.network_uuid = self.cfg.LookupNetwork(self.network_name)
    self.group_uuid = self.cfg.LookupNodeGroup(self.group_name)

    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }
    self.share_locks[locking.LEVEL_INSTANCE] = 1

  def DeclareLocks(self, level):
    if level == locking.LEVEL_INSTANCE:
      assert not self.needed_locks[locking.LEVEL_INSTANCE]

      # Lock instances optimistically, needs verification once group lock has
      # been acquired
      self.needed_locks[locking.LEVEL_INSTANCE] = \
        self.cfg.GetNodeGroupInstances(self.group_uuid)

  def BuildHooksEnv(self):
    ret = {
      "GROUP_NAME": self.group_name,
      }
    return ret

  def BuildHooksNodes(self):
    nodes = self.cfg.GetNodeGroup(self.group_uuid).members
    return (nodes, nodes)

  def CheckPrereq(self):
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))

    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    _CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instances)

    self.group = self.cfg.GetNodeGroup(self.group_uuid)
    self.connected = True
    if self.network_uuid not in self.group.networks:
      self.LogWarning("Network '%s' is not mapped to group '%s'",
                      self.network_name, self.group.name)
      self.connected = False

    # We need this check only if network is not already connected
    else:
      _NetworkConflictCheck(self, lambda nic: nic.network == self.network_uuid,
                            "disconnect from", owned_instances)

  def Exec(self, feedback_fn):
    # Disconnect the network and update the group only if network is connected
    if self.connected:
      del self.group.networks[self.network_uuid]
      self.cfg.Update(self.group, feedback_fn)


#: Query type implementations
_QUERY_IMPL = {
  constants.QR_CLUSTER: _ClusterQuery,
  constants.QR_INSTANCE: _InstanceQuery,
  constants.QR_NODE: _NodeQuery,
  constants.QR_GROUP: _GroupQuery,
  constants.QR_NETWORK: _NetworkQuery,
  constants.QR_OS: _OsQuery,
  constants.QR_EXTSTORAGE: _ExtStorageQuery,
  constants.QR_EXPORT: _ExportQuery,
  }

assert set(_QUERY_IMPL.keys()) == constants.QR_VIA_OP


def _GetQueryImplementation(name):
  """Returns the implemtnation for a query type.

  @param name: Query type, must be one of L{constants.QR_VIA_OP}

  """
  try:
    return _QUERY_IMPL[name]
  except KeyError:
    raise errors.OpPrereqError("Unknown query resource '%s'" % name,
                               errors.ECODE_INVAL)


def _CheckForConflictingIp(lu, ip, node):
  """In case of conflicting IP address raise error.

  @type ip: string
  @param ip: IP address
  @type node: string
  @param node: node name

  """
  (conf_net, _) = lu.cfg.CheckIPInNodeGroup(ip, node)
  if conf_net is not None:
    raise errors.OpPrereqError(("Conflicting IP address found: '%s' != '%s'" %
                                (ip, conf_net)),
                               errors.ECODE_STATE)

  return (None, None)
