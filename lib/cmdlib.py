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


"""Module implementing the master-side code."""

# pylint: disable-msg=W0201,C0302

# W0201 since most LU attributes are defined in CheckPrereq or similar
# functions

# C0302: since we have waaaay to many lines in this module

import os
import os.path
import time
import re
import platform
import logging
import copy
import OpenSSL
import socket
import tempfile
import shutil
import itertools

from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti import constants
from ganeti import objects
from ganeti import serializer
from ganeti import ssconf
from ganeti import uidpool
from ganeti import compat
from ganeti import masterd
from ganeti import netutils
from ganeti import query
from ganeti import qlang
from ganeti import opcodes

import ganeti.masterd.instance # pylint: disable-msg=W0611


def _SupportsOob(cfg, node):
  """Tells if node supports OOB.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type node: L{objects.Node}
  @param node: The node
  @return: The OOB script if supported or an empty string otherwise

  """
  return cfg.GetNdParams(node)[constants.ND_OOB_PROGRAM]


# End types
class LogicalUnit(object):
  """Logical Unit base class.

  Subclasses must follow these rules:
    - implement ExpandNames
    - implement CheckPrereq (except when tasklets are used)
    - implement Exec (except when tasklets are used)
    - implement BuildHooksEnv
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

  def __init__(self, processor, op, context, rpc):
    """Constructor for LogicalUnit.

    This needs to be overridden in derived classes in order to check op
    validity.

    """
    self.proc = processor
    self.op = op
    self.cfg = context.cfg
    self.context = context
    self.rpc = rpc
    # Dicts used to declare locking needs to mcpu
    self.needed_locks = None
    self.acquired_locks = {}
    self.share_locks = dict.fromkeys(locking.LEVELS, 0)
    self.add_locks = {}
    self.remove_locks = {}
    # Used to force good behavior when calling helper functions
    self.recalculate_locks = {}
    self.__ssh = None
    # logging
    self.Log = processor.Log # pylint: disable-msg=C0103
    self.LogWarning = processor.LogWarning # pylint: disable-msg=C0103
    self.LogInfo = processor.LogInfo # pylint: disable-msg=C0103
    self.LogStep = processor.LogStep # pylint: disable-msg=C0103
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

  def __GetSSH(self):
    """Returns the SshRunner object

    """
    if not self.__ssh:
      self.__ssh = ssh.SshRunner(self.cfg.GetClusterName())
    return self.__ssh

  ssh = property(fget=__GetSSH)

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
      - if you don't need any lock at a particular level omit that level
      - don't put anything for the BGL level
      - if you want all locks at a level use locking.ALL_SET as a value

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
    @type level: member of ganeti.locking.LEVELS

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

    This method should return a three-node tuple consisting of: a dict
    containing the environment that will be used for running the
    specific hook for this LU, a list of node names on which the hook
    should run before the execution, and a list of node names on which
    the hook should run after the execution.

    The keys of the dict must not have 'GANETI_' prefixed as this will
    be handled in the hooks runner. Also note additional keys will be
    added by the hooks runner. If the LU doesn't define any
    environment, an empty dict (and not None) should be returned.

    No nodes should be returned as an empty list (and not None).

    Note that if the HPATH for a LU class is None, this function will
    not be called.

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
    # pylint: disable-msg=W0613,R0201
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

  def _LockInstancesNodes(self, primary_only=False):
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

    """
    assert locking.LEVEL_NODE in self.recalculate_locks, \
      "_LockInstancesNodes helper function called with no nodes to recalculate"

    # TODO: check if we're really been called with the instance locks held

    # For now we'll replace self.needed_locks[locking.LEVEL_NODE], but in the
    # future we might want to have different behaviors depending on the value
    # of self.recalculate_locks[locking.LEVEL_NODE]
    wanted_nodes = []
    for instance_name in self.acquired_locks[locking.LEVEL_INSTANCE]:
      instance = self.context.cfg.GetInstanceInfo(instance_name)
      wanted_nodes.append(instance.primary_node)
      if not primary_only:
        wanted_nodes.extend(instance.secondary_nodes)

    if self.recalculate_locks[locking.LEVEL_NODE] == constants.LOCKS_REPLACE:
      self.needed_locks[locking.LEVEL_NODE] = wanted_nodes
    elif self.recalculate_locks[locking.LEVEL_NODE] == constants.LOCKS_APPEND:
      self.needed_locks[locking.LEVEL_NODE].extend(wanted_nodes)

    del self.recalculate_locks[locking.LEVEL_NODE]


class NoHooksLU(LogicalUnit): # pylint: disable-msg=W0223
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
    assert False, "BuildHooksEnv called for NoHooksLUs"


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

  def __init__(self, names, fields, use_locking):
    """Initializes this class.

    """
    self.names = names
    self.use_locking = use_locking

    self.query = query.Query(self.FIELDS, fields)
    self.requested_data = self.query.RequestedData()

    self.do_locking = None
    self.wanted = None

  def _GetNames(self, lu, all_names, lock_level):
    """Helper function to determine names asked for in the query.

    """
    if self.do_locking:
      names = lu.acquired_locks[lock_level]
    else:
      names = all_names

    if self.wanted == locking.ALL_SET:
      assert not self.names
      # caller didn't specify names, so ordering is not important
      return utils.NiceSort(names)

    # caller specified names and we must keep the same order
    assert self.names
    assert not self.do_locking or lu.acquired_locks[lock_level]

    missing = set(self.wanted).difference(names)
    if missing:
      raise errors.OpExecError("Some items were removed before retrieving"
                               " their data: %s" % missing)

    # Return expanded names
    return self.wanted

  @classmethod
  def FieldsQuery(cls, fields):
    """Returns list of available fields.

    @return: List of L{objects.QueryFieldDefinition}

    """
    return query.QueryFields(cls.FIELDS, fields)

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
    return query.GetQueryResponse(self.query, self._GetQueryData(lu))

  def OldStyleQuery(self, lu):
    """Collect data and execute query.

    """
    return self.query.OldStyleQuery(self._GetQueryData(lu))


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


def _CheckGlobalHvParams(params):
  """Validates that given hypervisor params are not global ones.

  This will ensure that instances don't get customised versions of
  global params.

  """
  used_globals = constants.HVC_GLOBALS.intersection(params)
  if used_globals:
    msg = ("The following hypervisor parameters are global and cannot"
           " be customized at instance level, please modify them at"
           " cluster level: %s" % utils.CommaJoin(used_globals))
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


def _GetClusterDomainSecret():
  """Reads the cluster domain secret.

  """
  return utils.ReadOneLineFile(constants.CLUSTER_DOMAIN_SECRET_FILE,
                               strict=True)


def _CheckInstanceDown(lu, instance, reason):
  """Ensure that an instance is not running."""
  if instance.admin_up:
    raise errors.OpPrereqError("Instance %s is marked to be up, %s" %
                               (instance.name, reason), errors.ECODE_STATE)

  pnode = instance.primary_node
  ins_l = lu.rpc.call_instance_list([pnode], [instance.hypervisor])[pnode]
  ins_l.Raise("Can't contact node %s for instance information" % pnode,
              prereq=True, ecode=errors.ECODE_ENVIRON)

  if instance.name in ins_l.payload:
    raise errors.OpPrereqError("Instance %s is running, %s" %
                               (instance.name, reason), errors.ECODE_STATE)


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


def _BuildInstanceHookEnv(name, primary_node, secondary_nodes, os_type, status,
                          memory, vcpus, nics, disk_template, disks,
                          bep, hvp, hypervisor_name):
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
  @type status: boolean
  @param status: the should_run status of the instance
  @type memory: string
  @param memory: the memory size of the instance
  @type vcpus: string
  @param vcpus: the count of VCPUs the instance has
  @type nics: list
  @param nics: list of tuples (ip, mac, mode, link) representing
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
  @rtype: dict
  @return: the hook environment for this instance

  """
  if status:
    str_status = "up"
  else:
    str_status = "down"
  env = {
    "OP_TARGET": name,
    "INSTANCE_NAME": name,
    "INSTANCE_PRIMARY": primary_node,
    "INSTANCE_SECONDARIES": " ".join(secondary_nodes),
    "INSTANCE_OS_TYPE": os_type,
    "INSTANCE_STATUS": str_status,
    "INSTANCE_MEMORY": memory,
    "INSTANCE_VCPUS": vcpus,
    "INSTANCE_DISK_TEMPLATE": disk_template,
    "INSTANCE_HYPERVISOR": hypervisor_name,
  }

  if nics:
    nic_count = len(nics)
    for idx, (ip, mac, mode, link) in enumerate(nics):
      if ip is None:
        ip = ""
      env["INSTANCE_NIC%d_IP" % idx] = ip
      env["INSTANCE_NIC%d_MAC" % idx] = mac
      env["INSTANCE_NIC%d_MODE" % idx] = mode
      env["INSTANCE_NIC%d_LINK" % idx] = link
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

  for source, kind in [(bep, "BE"), (hvp, "HV")]:
    for key, value in source.items():
      env["INSTANCE_%s_%s" % (kind, key)] = value

  return env


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
  cluster = lu.cfg.GetClusterInfo()
  for nic in nics:
    ip = nic.ip
    mac = nic.mac
    filled_params = cluster.SimpleFillNIC(nic.nicparams)
    mode = filled_params[constants.NIC_MODE]
    link = filled_params[constants.NIC_LINK]
    hooks_nics.append((ip, mac, mode, link))
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
    'name': instance.name,
    'primary_node': instance.primary_node,
    'secondary_nodes': instance.secondary_nodes,
    'os_type': instance.os,
    'status': instance.admin_up,
    'memory': bep[constants.BE_MEMORY],
    'vcpus': bep[constants.BE_VCPUS],
    'nics': _NICListToTuple(lu, instance.nics),
    'disk_template': instance.disk_template,
    'disks': [(disk.size, disk.mode) for disk in instance.disks],
    'bep': bep,
    'hvp': hvp,
    'hypervisor_name': instance.hypervisor,
  }
  if override:
    args.update(override)
  return _BuildInstanceHookEnv(**args) # pylint: disable-msg=W0142


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
  if not os_obj.supported_variants:
    return
  variant = objects.OS.GetVariant(name)
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
    return [[cfg.GetFileStorageDir()]]

  return []


def _FindFaultyInstanceDisks(cfg, rpc, instance, node_name, prereq):
  faulty = []

  for dev in instance.disks:
    cfg.SetDiskID(dev, node_name)

  result = rpc.call_blockdev_getmirrorstatus(node_name, instance.disks)
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
  specified, then the LU's opcode's iallocator slot is filled with the
  cluster-wide default iallocator.

  @type iallocator_slot: string
  @param iallocator_slot: the name of the opcode iallocator slot
  @type node_slot: string
  @param node_slot: the name of the opcode target node slot

  """
  node = getattr(lu.op, node_slot, None)
  iallocator = getattr(lu.op, iallocator_slot, None)

  if node is not None and iallocator is not None:
    raise errors.OpPrereqError("Do not specify both, iallocator and node.",
                               errors.ECODE_INVAL)
  elif node is None and iallocator is None:
    default_iallocator = lu.cfg.GetDefaultIAllocator()
    if default_iallocator:
      setattr(lu.op, iallocator_slot, default_iallocator)
    else:
      raise errors.OpPrereqError("No iallocator or node given and no"
                                 " cluster-wide default iallocator found."
                                 " Please specify either an iallocator or a"
                                 " node, or set a cluster-wide default"
                                 " iallocator.")


class LUClusterPostInit(LogicalUnit):
  """Logical unit for running hooks after cluster initialization.

  """
  HPATH = "cluster-init"
  HTYPE = constants.HTYPE_CLUSTER

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    env = {"OP_TARGET": self.cfg.GetClusterName()}
    mn = self.cfg.GetMasterNode()
    return env, [], [mn]

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
    env = {"OP_TARGET": self.cfg.GetClusterName()}
    return env, [], []

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
    master = self.cfg.GetMasterNode()

    # Run post hooks on master node before it's removed
    hm = self.proc.hmclass(self.rpc.call_hooks_runner, self)
    try:
      hm.RunPhase(constants.HOOKS_PHASE_POST, [master])
    except:
      # pylint: disable-msg=W0702
      self.LogWarning("Errors occurred running hooks on %s" % master)

    result = self.rpc.call_node_stop_master(master, False)
    result.Raise("Could not disable the master role")

    return master


def _VerifyCertificate(filename):
  """Verifies a certificate for LUClusterVerify.

  @type filename: string
  @param filename: Path to PEM file

  """
  try:
    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           utils.ReadFile(filename))
  except Exception, err: # pylint: disable-msg=W0703
    return (LUClusterVerify.ETYPE_ERROR,
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
    return (LUClusterVerify.ETYPE_WARNING, fnamemsg)
  elif errcode == utils.CERT_ERROR:
    return (LUClusterVerify.ETYPE_ERROR, fnamemsg)

  raise errors.ProgrammerError("Unhandled certificate error code %r" % errcode)


class LUClusterVerify(LogicalUnit):
  """Verifies the cluster status.

  """
  HPATH = "cluster-verify"
  HTYPE = constants.HTYPE_CLUSTER
  REQ_BGL = False

  TCLUSTER = "cluster"
  TNODE = "node"
  TINSTANCE = "instance"

  ECLUSTERCFG = (TCLUSTER, "ECLUSTERCFG")
  ECLUSTERCERT = (TCLUSTER, "ECLUSTERCERT")
  EINSTANCEBADNODE = (TINSTANCE, "EINSTANCEBADNODE")
  EINSTANCEDOWN = (TINSTANCE, "EINSTANCEDOWN")
  EINSTANCELAYOUT = (TINSTANCE, "EINSTANCELAYOUT")
  EINSTANCEMISSINGDISK = (TINSTANCE, "EINSTANCEMISSINGDISK")
  EINSTANCEFAULTYDISK = (TINSTANCE, "EINSTANCEFAULTYDISK")
  EINSTANCEWRONGNODE = (TINSTANCE, "EINSTANCEWRONGNODE")
  EINSTANCESPLITGROUPS = (TINSTANCE, "EINSTANCESPLITGROUPS")
  ENODEDRBD = (TNODE, "ENODEDRBD")
  ENODEDRBDHELPER = (TNODE, "ENODEDRBDHELPER")
  ENODEFILECHECK = (TNODE, "ENODEFILECHECK")
  ENODEHOOKS = (TNODE, "ENODEHOOKS")
  ENODEHV = (TNODE, "ENODEHV")
  ENODELVM = (TNODE, "ENODELVM")
  ENODEN1 = (TNODE, "ENODEN1")
  ENODENET = (TNODE, "ENODENET")
  ENODEOS = (TNODE, "ENODEOS")
  ENODEORPHANINSTANCE = (TNODE, "ENODEORPHANINSTANCE")
  ENODEORPHANLV = (TNODE, "ENODEORPHANLV")
  ENODERPC = (TNODE, "ENODERPC")
  ENODESSH = (TNODE, "ENODESSH")
  ENODEVERSION = (TNODE, "ENODEVERSION")
  ENODESETUP = (TNODE, "ENODESETUP")
  ENODETIME = (TNODE, "ENODETIME")
  ENODEOOBPATH = (TNODE, "ENODEOOBPATH")

  ETYPE_FIELD = "code"
  ETYPE_ERROR = "ERROR"
  ETYPE_WARNING = "WARNING"

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
    @ivar sbp: diction of {secondary-node: list of instances} of all peers
        of this node (config)
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

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
    }
    self.share_locks = dict.fromkeys(locking.LEVELS, 1)

  def _Error(self, ecode, item, msg, *args, **kwargs):
    """Format an error message.

    Based on the opcode's error_codes parameter, either format a
    parseable error code, or a simpler error string.

    This must be called only from Exec and functions called from Exec.

    """
    ltype = kwargs.get(self.ETYPE_FIELD, self.ETYPE_ERROR)
    itype, etxt = ecode
    # first complete the msg
    if args:
      msg = msg % args
    # then format the whole message
    if self.op.error_codes:
      msg = "%s:%s:%s:%s:%s" % (ltype, etxt, itype, item, msg)
    else:
      if item:
        item = " " + item
      else:
        item = ""
      msg = "%s: %s%s: %s" % (ltype, itype, item, msg)
    # and finally report it via the feedback_fn
    self._feedback_fn("  - %s" % msg)

  def _ErrorIf(self, cond, *args, **kwargs):
    """Log an error message if the passed condition is True.

    """
    cond = bool(cond) or self.op.debug_simulate_errors
    if cond:
      self._Error(*args, **kwargs)
    # do not mark the operation as failed for WARN cases only
    if kwargs.get(self.ETYPE_FIELD, self.ETYPE_ERROR) == self.ETYPE_ERROR:
      self.bad = self.bad or cond

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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    # main result, nresult should be a non-empty dict
    test = not nresult or not isinstance(nresult, dict)
    _ErrorIf(test, self.ENODERPC, node,
                  "unable to verify node: no data returned")
    if test:
      return False

    # compares ganeti version
    local_version = constants.PROTOCOL_VERSION
    remote_version = nresult.get("version", None)
    test = not (remote_version and
                isinstance(remote_version, (list, tuple)) and
                len(remote_version) == 2)
    _ErrorIf(test, self.ENODERPC, node,
             "connection to node returned invalid data")
    if test:
      return False

    test = local_version != remote_version[0]
    _ErrorIf(test, self.ENODEVERSION, node,
             "incompatible protocol versions: master %s,"
             " node %s", local_version, remote_version[0])
    if test:
      return False

    # node seems compatible, we can actually try to look into its results

    # full package version
    self._ErrorIf(constants.RELEASE_VERSION != remote_version[1],
                  self.ENODEVERSION, node,
                  "software version mismatch: master %s, node %s",
                  constants.RELEASE_VERSION, remote_version[1],
                  code=self.ETYPE_WARNING)

    hyp_result = nresult.get(constants.NV_HYPERVISOR, None)
    if ninfo.vm_capable and isinstance(hyp_result, dict):
      for hv_name, hv_result in hyp_result.iteritems():
        test = hv_result is not None
        _ErrorIf(test, self.ENODEHV, node,
                 "hypervisor %s verify failure: '%s'", hv_name, hv_result)

    hvp_result = nresult.get(constants.NV_HVPARAMS, None)
    if ninfo.vm_capable and isinstance(hvp_result, list):
      for item, hv_name, hv_result in hvp_result:
        _ErrorIf(True, self.ENODEHV, node,
                 "hypervisor %s parameter verify failure (source %s): %s",
                 hv_name, item, hv_result)

    test = nresult.get(constants.NV_NODESETUP,
                           ["Missing NODESETUP results"])
    _ErrorIf(test, self.ENODESETUP, node, "node setup error: %s",
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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    ntime = nresult.get(constants.NV_TIME, None)
    try:
      ntime_merged = utils.MergeTime(ntime)
    except (ValueError, TypeError):
      _ErrorIf(True, self.ENODETIME, node, "Node returned invalid time")
      return

    if ntime_merged < (nvinfo_starttime - constants.NODE_MAX_CLOCK_SKEW):
      ntime_diff = "%.01fs" % abs(nvinfo_starttime - ntime_merged)
    elif ntime_merged > (nvinfo_endtime + constants.NODE_MAX_CLOCK_SKEW):
      ntime_diff = "%.01fs" % abs(ntime_merged - nvinfo_endtime)
    else:
      ntime_diff = None

    _ErrorIf(ntime_diff is not None, self.ENODETIME, node,
             "Node time diverges by at least %s from master node time",
             ntime_diff)

  def _VerifyNodeLVM(self, ninfo, nresult, vg_name):
    """Check the node time.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param vg_name: the configured VG name

    """
    if vg_name is None:
      return

    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    # checks vg existence and size > 20G
    vglist = nresult.get(constants.NV_VGLIST, None)
    test = not vglist
    _ErrorIf(test, self.ENODELVM, node, "unable to check volume groups")
    if not test:
      vgstatus = utils.CheckVolumeGroupSize(vglist, vg_name,
                                            constants.MIN_VG_SIZE)
      _ErrorIf(vgstatus, self.ENODELVM, node, vgstatus)

    # check pv names
    pvlist = nresult.get(constants.NV_PVLIST, None)
    test = pvlist is None
    _ErrorIf(test, self.ENODELVM, node, "Can't get PV list from node")
    if not test:
      # check that ':' is not present in PV names, since it's a
      # special character for lvcreate (denotes the range of PEs to
      # use on the PV)
      for _, pvname, owner_vg in pvlist:
        test = ":" in pvname
        _ErrorIf(test, self.ENODELVM, node, "Invalid character ':' in PV"
                 " '%s' of VG '%s'", pvname, owner_vg)

  def _VerifyNodeNetwork(self, ninfo, nresult):
    """Check the node time.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    test = constants.NV_NODELIST not in nresult
    _ErrorIf(test, self.ENODESSH, node,
             "node hasn't returned node ssh connectivity data")
    if not test:
      if nresult[constants.NV_NODELIST]:
        for a_node, a_msg in nresult[constants.NV_NODELIST].items():
          _ErrorIf(True, self.ENODESSH, node,
                   "ssh communication with node '%s': %s", a_node, a_msg)

    test = constants.NV_NODENETTEST not in nresult
    _ErrorIf(test, self.ENODENET, node,
             "node hasn't returned node tcp connectivity data")
    if not test:
      if nresult[constants.NV_NODENETTEST]:
        nlist = utils.NiceSort(nresult[constants.NV_NODENETTEST].keys())
        for anode in nlist:
          _ErrorIf(True, self.ENODENET, node,
                   "tcp communication with node '%s': %s",
                   anode, nresult[constants.NV_NODENETTEST][anode])

    test = constants.NV_MASTERIP not in nresult
    _ErrorIf(test, self.ENODENET, node,
             "node hasn't returned node master IP reachability data")
    if not test:
      if not nresult[constants.NV_MASTERIP]:
        if node == self.master_node:
          msg = "the master node cannot reach the master IP (not configured?)"
        else:
          msg = "cannot reach the master IP"
        _ErrorIf(True, self.ENODENET, node, msg)

  def _VerifyInstance(self, instance, instanceconfig, node_image,
                      diskstatus):
    """Verify an instance.

    This function checks to see if the required block devices are
    available on the instance's node.

    """
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103
    node_current = instanceconfig.primary_node

    node_vol_should = {}
    instanceconfig.MapLVsByNode(node_vol_should)

    for node in node_vol_should:
      n_img = node_image[node]
      if n_img.offline or n_img.rpc_fail or n_img.lvm_fail:
        # ignore missing volumes on offline or broken nodes
        continue
      for volume in node_vol_should[node]:
        test = volume not in n_img.volumes
        _ErrorIf(test, self.EINSTANCEMISSINGDISK, instance,
                 "volume %s missing on node %s", volume, node)

    if instanceconfig.admin_up:
      pri_img = node_image[node_current]
      test = instance not in pri_img.instances and not pri_img.offline
      _ErrorIf(test, self.EINSTANCEDOWN, instance,
               "instance not running on its primary node %s",
               node_current)

    for node, n_img in node_image.items():
      if (not node == node_current):
        test = instance in n_img.instances
        _ErrorIf(test, self.EINSTANCEWRONGNODE, instance,
                 "instance should not run on node %s", node)

    diskdata = [(nname, success, status, idx)
                for (nname, disks) in diskstatus.items()
                for idx, (success, status) in enumerate(disks)]

    for nname, success, bdev_status, idx in diskdata:
      _ErrorIf(instanceconfig.admin_up and not success,
               self.EINSTANCEFAULTYDISK, instance,
               "couldn't retrieve status for disk/%s on %s: %s",
               idx, nname, bdev_status)
      _ErrorIf((instanceconfig.admin_up and success and
                bdev_status.ldisk_status == constants.LDS_FAULTY),
               self.EINSTANCEFAULTYDISK, instance,
               "disk/%s on %s is faulty", idx, nname)

  def _VerifyOrphanVolumes(self, node_vol_should, node_image, reserved):
    """Verify if there are any unknown volumes in the cluster.

    The .os, .swap and backup volumes are ignored. All other volumes are
    reported as unknown.

    @type reserved: L{ganeti.utils.FieldSet}
    @param reserved: a FieldSet of reserved volume names

    """
    for node, n_img in node_image.items():
      if n_img.offline or n_img.rpc_fail or n_img.lvm_fail:
        # skip non-healthy nodes
        continue
      for volume in n_img.volumes:
        test = ((node not in node_vol_should or
                volume not in node_vol_should[node]) and
                not reserved.Matches(volume))
        self._ErrorIf(test, self.ENODEORPHANLV, node,
                      "volume %s is unknown", volume)

  def _VerifyOrphanInstances(self, instancelist, node_image):
    """Verify the list of running instances.

    This checks what instances are running but unknown to the cluster.

    """
    for node, n_img in node_image.items():
      for o_inst in n_img.instances:
        test = o_inst not in instancelist
        self._ErrorIf(test, self.ENODEORPHANINSTANCE, node,
                      "instance %s on node %s should not exist", o_inst, node)

  def _VerifyNPlusOneMemory(self, node_image, instance_cfg):
    """Verify N+1 Memory Resilience.

    Check that if one single node dies we can still start all the
    instances it was primary for.

    """
    for node, n_img in node_image.items():
      # This code checks that every node which is now listed as
      # secondary has enough memory to host all instances it is
      # supposed to should a single other node in the cluster fail.
      # FIXME: not ready for failover to an arbitrary node
      # FIXME: does not support file-backed instances
      # WARNING: we currently take into account down instances as well
      # as up ones, considering that even if they're down someone
      # might want to start them even in the event of a node failure.
      for prinode, instances in n_img.sbp.items():
        needed_mem = 0
        for instance in instances:
          bep = self.cfg.GetClusterInfo().FillBE(instance_cfg[instance])
          if bep[constants.BE_AUTO_BALANCE]:
            needed_mem += bep[constants.BE_MEMORY]
        test = n_img.mfree < needed_mem
        self._ErrorIf(test, self.ENODEN1, node,
                      "not enough memory to accomodate instance failovers"
                      " should node %s fail", prinode)

  def _VerifyNodeFiles(self, ninfo, nresult, file_list, local_cksum,
                       master_files):
    """Verifies and computes the node required file checksums.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param file_list: required list of files
    @param local_cksum: dictionary of local files and their checksums
    @param master_files: list of files that only masters should have

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    remote_cksum = nresult.get(constants.NV_FILELIST, None)
    test = not isinstance(remote_cksum, dict)
    _ErrorIf(test, self.ENODEFILECHECK, node,
             "node hasn't returned file checksum data")
    if test:
      return

    for file_name in file_list:
      node_is_mc = ninfo.master_candidate
      must_have = (file_name not in master_files) or node_is_mc
      # missing
      test1 = file_name not in remote_cksum
      # invalid checksum
      test2 = not test1 and remote_cksum[file_name] != local_cksum[file_name]
      # existing and good
      test3 = not test1 and remote_cksum[file_name] == local_cksum[file_name]
      _ErrorIf(test1 and must_have, self.ENODEFILECHECK, node,
               "file '%s' missing", file_name)
      _ErrorIf(test2 and must_have, self.ENODEFILECHECK, node,
               "file '%s' has wrong checksum", file_name)
      # not candidate and this is not a must-have file
      _ErrorIf(test2 and not must_have, self.ENODEFILECHECK, node,
               "file '%s' should not exist on non master"
               " candidates (and the file is outdated)", file_name)
      # all good, except non-master/non-must have combination
      _ErrorIf(test3 and not must_have, self.ENODEFILECHECK, node,
               "file '%s' should not exist"
               " on non master candidates", file_name)

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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    if drbd_helper:
      helper_result = nresult.get(constants.NV_DRBDHELPER, None)
      test = (helper_result == None)
      _ErrorIf(test, self.ENODEDRBDHELPER, node,
               "no drbd usermode helper returned")
      if helper_result:
        status, payload = helper_result
        test = not status
        _ErrorIf(test, self.ENODEDRBDHELPER, node,
                 "drbd usermode helper check unsuccessful: %s", payload)
        test = status and (payload != drbd_helper)
        _ErrorIf(test, self.ENODEDRBDHELPER, node,
                 "wrong drbd usermode helper: %s", payload)

    # compute the DRBD minors
    node_drbd = {}
    for minor, instance in drbd_map[node].items():
      test = instance not in instanceinfo
      _ErrorIf(test, self.ECLUSTERCFG, None,
               "ghost instance '%s' in temporary DRBD map", instance)
        # ghost instance should not be running, but otherwise we
        # don't give double warnings (both ghost instance and
        # unallocated minor in use)
      if test:
        node_drbd[minor] = (instance, False)
      else:
        instance = instanceinfo[instance]
        node_drbd[minor] = (instance.name, instance.admin_up)

    # and now check them
    used_minors = nresult.get(constants.NV_DRBDLIST, [])
    test = not isinstance(used_minors, (tuple, list))
    _ErrorIf(test, self.ENODEDRBD, node,
             "cannot parse drbd status file: %s", str(used_minors))
    if test:
      # we cannot check drbd status
      return

    for minor, (iname, must_exist) in node_drbd.items():
      test = minor not in used_minors and must_exist
      _ErrorIf(test, self.ENODEDRBD, node,
               "drbd minor %d of instance %s is not active", minor, iname)
    for minor in used_minors:
      test = minor not in node_drbd
      _ErrorIf(test, self.ENODEDRBD, node,
               "unallocated drbd minor %d is in use", minor)

  def _UpdateNodeOS(self, ninfo, nresult, nimg):
    """Builds the node OS structures.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object

    """
    node = ninfo.name
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    remote_os = nresult.get(constants.NV_OSLIST, None)
    test = (not isinstance(remote_os, list) or
            not compat.all(isinstance(v, list) and len(v) == 7
                           for v in remote_os))

    _ErrorIf(test, self.ENODEOS, node,
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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    assert not nimg.os_fail, "Entered _VerifyNodeOS with failed OS rpc?"

    for os_name, os_data in nimg.oslist.items():
      assert os_data, "Empty OS status for OS %s?!" % os_name
      f_path, f_status, f_diag, f_var, f_param, f_api = os_data[0]
      _ErrorIf(not f_status, self.ENODEOS, node,
               "Invalid OS %s (located at %s): %s", os_name, f_path, f_diag)
      _ErrorIf(len(os_data) > 1, self.ENODEOS, node,
               "OS '%s' has multiple entries (first one shadows the rest): %s",
               os_name, utils.CommaJoin([v[0] for v in os_data]))
      # this will catched in backend too
      _ErrorIf(compat.any(v >= constants.OS_API_V15 for v in f_api)
               and not f_var, self.ENODEOS, node,
               "OS %s with API at least %d does not declare any variant",
               os_name, constants.OS_API_V15)
      # comparisons with the 'base' image
      test = os_name not in base.oslist
      _ErrorIf(test, self.ENODEOS, node,
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
                         ("parameters", f_param, b_param)]:
        _ErrorIf(a != b, self.ENODEOS, node,
                 "OS %s %s differs from reference node %s: %s vs. %s",
                 kind, os_name, base.name,
                 utils.CommaJoin(a), utils.CommaJoin(b))

    # check any missing OSes
    missing = set(base.oslist.keys()).difference(nimg.oslist.keys())
    _ErrorIf(missing, self.ENODEOS, node,
             "OSes present on reference node %s but missing on this node: %s",
             base.name, utils.CommaJoin(missing))

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
        self._ErrorIf(path_result, self.ENODEOOBPATH, node, path_result)

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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    nimg.lvm_fail = True
    lvdata = nresult.get(constants.NV_LVLIST, "Missing LV data")
    if vg_name is None:
      pass
    elif isinstance(lvdata, basestring):
      _ErrorIf(True, self.ENODELVM, node, "LVM problem on node: %s",
               utils.SafeEncode(lvdata))
    elif not isinstance(lvdata, dict):
      _ErrorIf(True, self.ENODELVM, node, "rpc call to node failed (lvlist)")
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
    self._ErrorIf(test, self.ENODEHV, ninfo.name, "rpc call to node failed"
                  " (instancelist): %s", utils.SafeEncode(str(idata)))
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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

    # try to read free memory (from the hypervisor)
    hv_info = nresult.get(constants.NV_HVINFO, None)
    test = not isinstance(hv_info, dict) or "memory_free" not in hv_info
    _ErrorIf(test, self.ENODEHV, node, "rpc call to node failed (hvinfo)")
    if not test:
      try:
        nimg.mfree = int(hv_info["memory_free"])
      except (ValueError, TypeError):
        _ErrorIf(True, self.ENODERPC, node,
                 "node returned invalid nodeinfo, check hypervisor")

    # FIXME: devise a free space model for file based instances as well
    if vg_name is not None:
      test = (constants.NV_VGLIST not in nresult or
              vg_name not in nresult[constants.NV_VGLIST])
      _ErrorIf(test, self.ENODELVM, node,
               "node didn't return data for the volume group '%s'"
               " - it is either missing or broken", vg_name)
      if not test:
        try:
          nimg.dfree = int(nresult[constants.NV_VGLIST][vg_name])
        except (ValueError, TypeError):
          _ErrorIf(True, self.ENODERPC, node,
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
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103

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

      # Creating copies as SetDiskID below will modify the objects and that can
      # lead to incorrect data returned from nodes
      devonly = [dev.Copy() for (_, dev) in disks]

      for dev in devonly:
        self.cfg.SetDiskID(dev, nname)

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
        _ErrorIf(msg, self.ENODERPC, nname,
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
    assert set(instdisk) == set(instanceinfo), "instdisk consistency failure"

    return instdisk

  def _VerifyHVP(self, hvp_data):
    """Verifies locally the syntax of the hypervisor parameters.

    """
    for item, hv_name, hv_params in hvp_data:
      msg = ("hypervisor %s parameters syntax check (source %s): %%s" %
             (item, hv_name))
      try:
        hv_class = hypervisor.GetHypervisor(hv_name)
        utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
        hv_class.CheckParameterSyntax(hv_params)
      except errors.GenericError, err:
        self._ErrorIf(True, self.ECLUSTERCFG, None, msg % str(err))


  def BuildHooksEnv(self):
    """Build hooks env.

    Cluster-Verify hooks just ran in the post phase and their failure makes
    the output be logged in the verify output and the verification to fail.

    """
    all_nodes = self.cfg.GetNodeList()
    env = {
      "CLUSTER_TAGS": " ".join(self.cfg.GetClusterInfo().GetTags())
      }
    for node in self.cfg.GetAllNodesInfo().values():
      env["NODE_TAGS_%s" % node.name] = " ".join(node.GetTags())

    return env, [], all_nodes

  def Exec(self, feedback_fn):
    """Verify integrity of cluster, performing various test on nodes.

    """
    # This method has too many local variables. pylint: disable-msg=R0914
    self.bad = False
    _ErrorIf = self._ErrorIf # pylint: disable-msg=C0103
    verbose = self.op.verbose
    self._feedback_fn = feedback_fn
    feedback_fn("* Verifying global settings")
    for msg in self.cfg.VerifyConfig():
      _ErrorIf(True, self.ECLUSTERCFG, None, msg)

    # Check the cluster certificates
    for cert_filename in constants.ALL_CERT_FILES:
      (errcode, msg) = _VerifyCertificate(cert_filename)
      _ErrorIf(errcode, self.ECLUSTERCERT, None, msg, code=errcode)

    vg_name = self.cfg.GetVGName()
    drbd_helper = self.cfg.GetDRBDHelper()
    hypervisors = self.cfg.GetClusterInfo().enabled_hypervisors
    cluster = self.cfg.GetClusterInfo()
    nodelist = utils.NiceSort(self.cfg.GetNodeList())
    nodeinfo = [self.cfg.GetNodeInfo(nname) for nname in nodelist]
    nodeinfo_byname = dict(zip(nodelist, nodeinfo))
    instancelist = utils.NiceSort(self.cfg.GetInstanceList())
    instanceinfo = dict((iname, self.cfg.GetInstanceInfo(iname))
                        for iname in instancelist)
    groupinfo = self.cfg.GetAllNodeGroupsInfo()
    i_non_redundant = [] # Non redundant instances
    i_non_a_balanced = [] # Non auto-balanced instances
    n_offline = 0 # Count of offline nodes
    n_drained = 0 # Count of nodes being drained
    node_vol_should = {}

    # FIXME: verify OS list
    # do local checksums
    master_files = [constants.CLUSTER_CONF_FILE]
    master_node = self.master_node = self.cfg.GetMasterNode()
    master_ip = self.cfg.GetMasterIP()

    file_names = ssconf.SimpleStore().GetFileList()
    file_names.extend(constants.ALL_CERT_FILES)
    file_names.extend(master_files)
    if cluster.modify_etc_hosts:
      file_names.append(constants.ETC_HOSTS)

    local_checksums = utils.FingerprintFiles(file_names)

    # Compute the set of hypervisor parameters
    hvp_data = []
    for hv_name in hypervisors:
      hvp_data.append(("cluster", hv_name, cluster.GetHVDefaults(hv_name)))
    for os_name, os_hvp in cluster.os_hvp.items():
      for hv_name, hv_params in os_hvp.items():
        if not hv_params:
          continue
        full_params = cluster.GetHVDefaults(hv_name, os_name=os_name)
        hvp_data.append(("os %s" % os_name, hv_name, full_params))
    # TODO: collapse identical parameter values in a single one
    for instance in instanceinfo.values():
      if not instance.hvparams:
        continue
      hvp_data.append(("instance %s" % instance.name, instance.hypervisor,
                       cluster.FillHV(instance)))
    # and verify them locally
    self._VerifyHVP(hvp_data)

    feedback_fn("* Gathering data (%d nodes)" % len(nodelist))
    node_verify_param = {
      constants.NV_FILELIST: file_names,
      constants.NV_NODELIST: [node.name for node in nodeinfo
                              if not node.offline],
      constants.NV_HYPERVISOR: hypervisors,
      constants.NV_HVPARAMS: hvp_data,
      constants.NV_NODENETTEST: [(node.name, node.primary_ip,
                                  node.secondary_ip) for node in nodeinfo
                                 if not node.offline],
      constants.NV_INSTANCELIST: hypervisors,
      constants.NV_VERSION: None,
      constants.NV_HVINFO: self.cfg.GetHypervisorType(),
      constants.NV_NODESETUP: None,
      constants.NV_TIME: None,
      constants.NV_MASTERIP: (master_node, master_ip),
      constants.NV_OSLIST: None,
      constants.NV_VMNODES: self.cfg.GetNonVmCapableNodeList(),
      }

    if vg_name is not None:
      node_verify_param[constants.NV_VGLIST] = None
      node_verify_param[constants.NV_LVLIST] = vg_name
      node_verify_param[constants.NV_PVLIST] = [vg_name]
      node_verify_param[constants.NV_DRBDLIST] = None

    if drbd_helper:
      node_verify_param[constants.NV_DRBDHELPER] = drbd_helper

    # Build our expected cluster state
    node_image = dict((node.name, self.NodeImage(offline=node.offline,
                                                 name=node.name,
                                                 vm_capable=node.vm_capable))
                      for node in nodeinfo)

    # Gather OOB paths
    oob_paths = []
    for node in nodeinfo:
      path = _SupportsOob(self.cfg, node)
      if path and path not in oob_paths:
        oob_paths.append(path)

    if oob_paths:
      node_verify_param[constants.NV_OOB_PATHS] = oob_paths

    for instance in instancelist:
      inst_config = instanceinfo[instance]

      for nname in inst_config.all_nodes:
        if nname not in node_image:
          # ghost node
          gnode = self.NodeImage(name=nname)
          gnode.ghost = True
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

    # At this point, we have the in-memory data structures complete,
    # except for the runtime information, which we'll gather next

    # Due to the way our RPC system works, exact response times cannot be
    # guaranteed (e.g. a broken node could run into a timeout). By keeping the
    # time before and after executing the request, we can at least have a time
    # window.
    nvinfo_starttime = time.time()
    all_nvinfo = self.rpc.call_node_verify(nodelist, node_verify_param,
                                           self.cfg.GetClusterName())
    nvinfo_endtime = time.time()

    all_drbd_map = self.cfg.ComputeDRBDMap()

    feedback_fn("* Gathering disk information (%s nodes)" % len(nodelist))
    instdisk = self._CollectDiskInfo(nodelist, node_image, instanceinfo)

    feedback_fn("* Verifying node status")

    refos_img = None

    for node_i in nodeinfo:
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
      _ErrorIf(msg, self.ENODERPC, node, "while contacting node: %s", msg)
      if msg:
        nimg.rpc_fail = True
        continue

      nresult = all_nvinfo[node].payload

      nimg.call_ok = self._VerifyNode(node_i, nresult)
      self._VerifyNodeTime(node_i, nresult, nvinfo_starttime, nvinfo_endtime)
      self._VerifyNodeNetwork(node_i, nresult)
      self._VerifyNodeFiles(node_i, nresult, file_names, local_checksums,
                            master_files)

      self._VerifyOob(node_i, nresult)

      if nimg.vm_capable:
        self._VerifyNodeLVM(node_i, nresult, vg_name)
        self._VerifyNodeDrbd(node_i, nresult, instanceinfo, drbd_helper,
                             all_drbd_map)

        self._UpdateNodeVolumes(node_i, nresult, nimg, vg_name)
        self._UpdateNodeInstances(node_i, nresult, nimg)
        self._UpdateNodeInfo(node_i, nresult, nimg, vg_name)
        self._UpdateNodeOS(node_i, nresult, nimg)
        if not nimg.os_fail:
          if refos_img is None:
            refos_img = nimg
          self._VerifyNodeOS(node_i, nimg, refos_img)

    feedback_fn("* Verifying instance status")
    for instance in instancelist:
      if verbose:
        feedback_fn("* Verifying instance %s" % instance)
      inst_config = instanceinfo[instance]
      self._VerifyInstance(instance, inst_config, node_image,
                           instdisk[instance])
      inst_nodes_offline = []

      pnode = inst_config.primary_node
      pnode_img = node_image[pnode]
      _ErrorIf(pnode_img.rpc_fail and not pnode_img.offline,
               self.ENODERPC, pnode, "instance %s, connection to"
               " primary node failed", instance)

      if pnode_img.offline:
        inst_nodes_offline.append(pnode)

      # If the instance is non-redundant we cannot survive losing its primary
      # node, so we are not N+1 compliant. On the other hand we have no disk
      # templates with more than one secondary so that situation is not well
      # supported either.
      # FIXME: does not support file-backed instances
      if not inst_config.secondary_nodes:
        i_non_redundant.append(instance)

      _ErrorIf(len(inst_config.secondary_nodes) > 1, self.EINSTANCELAYOUT,
               instance, "instance has multiple secondary nodes: %s",
               utils.CommaJoin(inst_config.secondary_nodes),
               code=self.ETYPE_WARNING)

      if inst_config.disk_template in constants.DTS_NET_MIRROR:
        pnode = inst_config.primary_node
        instance_nodes = utils.NiceSort(inst_config.all_nodes)
        instance_groups = {}

        for node in instance_nodes:
          instance_groups.setdefault(nodeinfo_byname[node].group,
                                     []).append(node)

        pretty_list = [
          "%s (group %s)" % (utils.CommaJoin(nodes), groupinfo[group].name)
          # Sort so that we always list the primary node first.
          for group, nodes in sorted(instance_groups.items(),
                                     key=lambda (_, nodes): pnode in nodes,
                                     reverse=True)]

        self._ErrorIf(len(instance_groups) > 1, self.EINSTANCESPLITGROUPS,
                      instance, "instance has primary and secondary nodes in"
                      " different groups: %s", utils.CommaJoin(pretty_list),
                      code=self.ETYPE_WARNING)

      if not cluster.FillBE(inst_config)[constants.BE_AUTO_BALANCE]:
        i_non_a_balanced.append(instance)

      for snode in inst_config.secondary_nodes:
        s_img = node_image[snode]
        _ErrorIf(s_img.rpc_fail and not s_img.offline, self.ENODERPC, snode,
                 "instance %s, connection to secondary node failed", instance)

        if s_img.offline:
          inst_nodes_offline.append(snode)

      # warn that the instance lives on offline nodes
      _ErrorIf(inst_nodes_offline, self.EINSTANCEBADNODE, instance,
               "instance lives on offline node(s) %s",
               utils.CommaJoin(inst_nodes_offline))
      # ... or ghost/non-vm_capable nodes
      for node in inst_config.all_nodes:
        _ErrorIf(node_image[node].ghost, self.EINSTANCEBADNODE, instance,
                 "instance lives on ghost node %s", node)
        _ErrorIf(not node_image[node].vm_capable, self.EINSTANCEBADNODE,
                 instance, "instance lives on non-vm_capable node %s", node)

    feedback_fn("* Verifying orphan volumes")
    reserved = utils.FieldSet(*cluster.reserved_lvs)
    self._VerifyOrphanVolumes(node_vol_should, node_image, reserved)

    feedback_fn("* Verifying orphan instances")
    self._VerifyOrphanInstances(instancelist, node_image)

    if constants.VERIFY_NPLUSONE_MEM not in self.op.skip_checks:
      feedback_fn("* Verifying N+1 Memory redundancy")
      self._VerifyNPlusOneMemory(node_image, instanceinfo)

    feedback_fn("* Other Notes")
    if i_non_redundant:
      feedback_fn("  - NOTICE: %d non-redundant instance(s) found."
                  % len(i_non_redundant))

    if i_non_a_balanced:
      feedback_fn("  - NOTICE: %d non-auto-balanced instance(s) found."
                  % len(i_non_a_balanced))

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
    # We only really run POST phase hooks, and are only interested in
    # their results
    if phase == constants.HOOKS_PHASE_POST:
      # Used to change hooks' output to proper indentation
      feedback_fn("* Hooks Results")
      assert hooks_results, "invalid result from hooks"

      for node_name in hooks_results:
        res = hooks_results[node_name]
        msg = res.fail_msg
        test = msg and not res.offline
        self._ErrorIf(test, self.ENODEHOOKS, node_name,
                      "Communication failure in hooks execution: %s", msg)
        if res.offline or msg:
          # No need to investigate payload if node is offline or gave an error.
          # override manually lu_result here as _ErrorIf only
          # overrides self.bad
          lu_result = 1
          continue
        for script, hkr, output in res.payload:
          test = hkr == constants.HKR_FAIL
          self._ErrorIf(test, self.ENODEHOOKS, node_name,
                        "Script %s failed, output:", script)
          if test:
            output = self._HOOKS_INDENT_RE.sub('      ', output)
            feedback_fn("%s" % output)
            lu_result = 0

      return lu_result


class LUClusterVerifyDisks(NoHooksLU):
  """Verifies the cluster disks status.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
    }
    self.share_locks = dict.fromkeys(locking.LEVELS, 1)

  def Exec(self, feedback_fn):
    """Verify integrity of cluster disks.

    @rtype: tuple of three items
    @return: a tuple of (dict of node-to-node_error, list of instances
        which need activate-disks, dict of instance: (node, volume) for
        missing volumes

    """
    result = res_nodes, res_instances, res_missing = {}, [], {}

    nodes = utils.NiceSort(self.cfg.GetVmCapableNodeList())
    instances = self.cfg.GetAllInstancesInfo().values()

    nv_dict = {}
    for inst in instances:
      inst_lvs = {}
      if not inst.admin_up:
        continue
      inst.MapLVsByNode(inst_lvs)
      # transform { iname: {node: [vol,],},} to {(node, vol): iname}
      for node, vol_list in inst_lvs.iteritems():
        for vol in vol_list:
          nv_dict[(node, vol)] = inst

    if not nv_dict:
      return result

    node_lvs = self.rpc.call_lv_list(nodes, [])
    for node, node_res in node_lvs.items():
      if node_res.offline:
        continue
      msg = node_res.fail_msg
      if msg:
        logging.warning("Error enumerating LVs on node %s: %s", node, msg)
        res_nodes[node] = msg
        continue

      lvs = node_res.payload
      for lv_name, (_, _, lv_online) in lvs.items():
        inst = nv_dict.pop((node, lv_name), None)
        if (not lv_online and inst is not None
            and inst.name not in res_instances):
          res_instances.append(inst.name)

    # any leftover items in nv_dict are missing LVs, let's arrange the
    # data better
    for key, inst in nv_dict.iteritems():
      if inst.name not in res_missing:
        res_missing[inst.name] = []
      res_missing[inst.name].append(key)

    return result


class LUClusterRepairDiskSizes(NoHooksLU):
  """Verifies the cluster disks sizes.

  """
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.instances:
      self.wanted_names = []
      for name in self.op.instances:
        full_name = _ExpandInstanceName(self.cfg, name)
        self.wanted_names.append(full_name)
      self.needed_locks = {
        locking.LEVEL_NODE: [],
        locking.LEVEL_INSTANCE: self.wanted_names,
        }
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE
    else:
      self.wanted_names = None
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_INSTANCE: locking.ALL_SET,
        }
    self.share_locks = dict(((i, 1) for i in locking.LEVELS))

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE and self.wanted_names is not None:
      self._LockInstancesNodes(primary_only=True)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    if self.wanted_names is None:
      self.wanted_names = self.acquired_locks[locking.LEVEL_INSTANCE]

    self.wanted_instances = [self.cfg.GetInstanceInfo(name) for name
                             in self.wanted_names]

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
    env = {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_NAME": self.op.name,
      }
    mn = self.cfg.GetMasterNode()
    all_nodes = self.cfg.GetNodeList()
    return env, [mn], all_nodes

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
    ip = self.ip

    # shutdown the master IP
    master = self.cfg.GetMasterNode()
    result = self.rpc.call_node_stop_master(master, False)
    result.Raise("Could not disable the master role")

    try:
      cluster = self.cfg.GetClusterInfo()
      cluster.cluster_name = clustername
      cluster.master_ip = ip
      self.cfg.Update(cluster, feedback_fn)

      # update the known hosts file
      ssh.WriteKnownHostsFile(self.cfg, constants.SSH_KNOWN_HOSTS_FILE)
      node_list = self.cfg.GetOnlineNodeList()
      try:
        node_list.remove(master)
      except ValueError:
        pass
      _UploadHelper(self, node_list, constants.SSH_KNOWN_HOSTS_FILE)
    finally:
      result = self.rpc.call_node_start_master(master, False, False)
      msg = result.fail_msg
      if msg:
        self.LogWarning("Could not re-enable the master role on"
                        " the master, please restart manually: %s", msg)

    return clustername


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

  def ExpandNames(self):
    # FIXME: in the future maybe other cluster params won't require checking on
    # all nodes to be modified.
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
    }
    self.share_locks[locking.LEVEL_NODE] = 1

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    env = {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_VG_NAME": self.op.vg_name,
      }
    mn = self.cfg.GetMasterNode()
    return env, [mn], [mn]

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

    node_list = self.acquired_locks[locking.LEVEL_NODE]

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
      for node in node_list:
        ninfo = self.cfg.GetNodeInfo(node)
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
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)
      self.new_beparams = cluster.SimpleFillBE(self.op.beparams)

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)
      self.new_ndparams = cluster.SimpleFillND(self.op.ndparams)

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
            nic_errors.append("Instance %s, nic/%d: routed nick with no ip" %
                              (instance.name, nic_idx))
      if nic_errors:
        raise errors.OpPrereqError("Cannot apply the change, errors:\n%s" %
                                   "\n".join(nic_errors))

    # hypervisor list/parameters
    self.new_hvparams = new_hvp = objects.FillDict(cluster.hvparams, {})
    if self.op.hvparams:
      for hv_name, hv_dict in self.op.hvparams.items():
        if hv_name not in self.new_hvparams:
          self.new_hvparams[hv_name] = hv_dict
        else:
          self.new_hvparams[hv_name].update(hv_dict)

    # os hypervisor parameters
    self.new_os_hvp = objects.FillDict(cluster.os_hvp, {})
    if self.op.os_hvp:
      for os_name, hvs in self.op.os_hvp.items():
        if os_name not in self.new_os_hvp:
          self.new_os_hvp[os_name] = hvs
        else:
          for hv_name, hv_dict in hvs.items():
            if hv_name not in self.new_os_hvp[os_name]:
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
          hv_class = hypervisor.GetHypervisor(hv_name)
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
          hv_class = hypervisor.GetHypervisor(hv_name)
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
    if self.op.osparams:
      self.cluster.osparams = self.new_osp
    if self.op.ndparams:
      self.cluster.ndparams = self.new_ndparams

    if self.op.candidate_pool_size is not None:
      self.cluster.candidate_pool_size = self.op.candidate_pool_size
      # we need to update the pool size here, otherwise the save will fail
      _AdjustCandidatePool(self, [])

    if self.op.maintain_node_health is not None:
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
      master = self.cfg.GetMasterNode()
      feedback_fn("Shutting down master ip on the current netdev (%s)" %
                  self.cluster.master_netdev)
      result = self.rpc.call_node_stop_master(master, False)
      result.Raise("Could not disable the master ip")
      feedback_fn("Changing master_netdev from %s to %s" %
                  (self.cluster.master_netdev, self.op.master_netdev))
      self.cluster.master_netdev = self.op.master_netdev

    self.cfg.Update(self.cluster, feedback_fn)

    if self.op.master_netdev:
      feedback_fn("Starting the master ip on the new master netdev (%s)" %
                  self.op.master_netdev)
      result = self.rpc.call_node_start_master(master, False, False)
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
        lu.proc.LogWarning(msg)


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
  # 1. Gather target nodes
  myself = lu.cfg.GetNodeInfo(lu.cfg.GetMasterNode())
  dist_nodes = lu.cfg.GetOnlineNodeList()
  nvm_nodes = lu.cfg.GetNonVmCapableNodeList()
  vm_nodes = [name for name in dist_nodes if name not in nvm_nodes]
  if additional_nodes is not None:
    dist_nodes.extend(additional_nodes)
    if additional_vm:
      vm_nodes.extend(additional_nodes)
  if myself.name in dist_nodes:
    dist_nodes.remove(myself.name)
  if myself.name in vm_nodes:
    vm_nodes.remove(myself.name)

  # 2. Gather files to distribute
  dist_files = set([constants.ETC_HOSTS,
                    constants.SSH_KNOWN_HOSTS_FILE,
                    constants.RAPI_CERT_FILE,
                    constants.RAPI_USERS_FILE,
                    constants.CONFD_HMAC_KEY,
                    constants.CLUSTER_DOMAIN_SECRET_FILE,
                   ])

  vm_files = set()
  enabled_hypervisors = lu.cfg.GetClusterInfo().enabled_hypervisors
  for hv_name in enabled_hypervisors:
    hv_class = hypervisor.GetHypervisor(hv_name)
    vm_files.update(hv_class.GetAncillaryFiles())

  # 3. Perform the files upload
  for fname in dist_files:
    _UploadHelper(lu, dist_nodes, fname)
  for fname in vm_files:
    _UploadHelper(lu, vm_nodes, fname)


class LUClusterRedistConf(NoHooksLU):
  """Force the redistribution of cluster configuration.

  This is a very simple LU.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
    }
    self.share_locks[locking.LEVEL_NODE] = 1

  def Exec(self, feedback_fn):
    """Redistribute the configuration.

    """
    self.cfg.Update(self.cfg.GetClusterInfo(), feedback_fn)
    _RedistributeAncillaryFiles(self)


def _WaitForSync(lu, instance, disks=None, oneshot=False):
  """Sleep and poll for an instance's disk to sync.

  """
  if not instance.disks or disks is not None and not disks:
    return True

  disks = _ExpandCheckDisks(instance, disks)

  if not oneshot:
    lu.proc.LogInfo("Waiting for instance %s to sync disks." % instance.name)

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
    rstats = lu.rpc.call_blockdev_getmirrorstatus(node, disks)
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
        lu.proc.LogInfo("- device %s: %5.2f%% done, %s" %
                        (disks[i].iv_name, mstat.sync_percent, rem_time))

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
    lu.proc.LogInfo("Instance %s's disks are in sync." % instance.name)
  return not cumul_degraded


def _CheckDiskConsistency(lu, dev, node, on_primary, ldisk=False):
  """Check that mirrors are not degraded.

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
      result = result and _CheckDiskConsistency(lu, child, node, on_primary)

  return result


class LUOobCommand(NoHooksLU):
  """Logical unit for OOB handling.

  """
  REG_BGL = False

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the node exists in the configuration
     - OOB is supported

    Any errors are signaled by raising errors.OpPrereqError.

    """
    self.nodes = []
    for node_name in self.op.node_names:
      node = self.cfg.GetNodeInfo(node_name)

      if node is None:
        raise errors.OpPrereqError("Node %s not found" % node_name,
                                   errors.ECODE_NOENT)
      else:
        self.nodes.append(node)

      if (self.op.command == constants.OOB_POWER_OFF and not node.offline):
        raise errors.OpPrereqError(("Cannot power off node %s because it is"
                                    " not marked offline") % node_name,
                                   errors.ECODE_STATE)

  def ExpandNames(self):
    """Gather locks we need.

    """
    if self.op.node_names:
      self.op.node_names = [_ExpandNodeName(self.cfg, name)
                            for name in self.op.node_names]
    else:
      self.op.node_names = self.cfg.GetNodeList()

    self.needed_locks = {
      locking.LEVEL_NODE: self.op.node_names,
      }

  def Exec(self, feedback_fn):
    """Execute OOB and return result if we expect any.

    """
    master_node = self.cfg.GetMasterNode()
    ret = []

    for node in self.nodes:
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
        self.LogWarning("On node '%s' out-of-band RPC failed with: %s",
                        node.name, result.fail_msg)
        node_entry.append((constants.RS_NODATA, None))
      else:
        try:
          self._CheckPayload(result)
        except errors.OpExecError, err:
          self.LogWarning("The payload returned by '%s' is not valid: %s",
                          node.name, err)
          node_entry.append((constants.RS_NODATA, None))
        else:
          if self.op.command == constants.OOB_HEALTH:
            # For health we should log important events
            for item, status in result.payload:
              if status in [constants.OOB_STATUS_WARNING,
                            constants.OOB_STATUS_CRITICAL]:
                self.LogWarning("On node '%s' item '%s' has status '%s'",
                                node.name, item, status)

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



class LUOsDiagnose(NoHooksLU):
  """Logical unit for OS diagnose/query.

  """
  REQ_BGL = False
  _HID = "hidden"
  _BLK = "blacklisted"
  _VLD = "valid"
  _FIELDS_STATIC = utils.FieldSet()
  _FIELDS_DYNAMIC = utils.FieldSet("name", _VLD, "node_status", "variants",
                                   "parameters", "api_versions", _HID, _BLK)

  def CheckArguments(self):
    if self.op.names:
      raise errors.OpPrereqError("Selective OS query not supported",
                                 errors.ECODE_INVAL)

    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

  def ExpandNames(self):
    # Lock all nodes, in shared mode
    # Temporary removal of locks, should be reverted later
    # TODO: reintroduce locks when they are lighter-weight
    self.needed_locks = {}
    #self.share_locks[locking.LEVEL_NODE] = 1
    #self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

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

  def Exec(self, feedback_fn):
    """Compute the list of OSes.

    """
    valid_nodes = [node.name
                   for node in self.cfg.GetAllNodesInfo().values()
                   if not node.offline and node.vm_capable]
    node_data = self.rpc.call_os_diagnose(valid_nodes)
    pol = self._DiagnoseByOS(node_data)
    output = []
    cluster = self.cfg.GetClusterInfo()

    for os_name in utils.NiceSort(pol.keys()):
      os_data = pol[os_name]
      row = []
      valid = True
      (variants, params, api_versions) = null_state = (set(), set(), set())
      for idx, osl in enumerate(os_data.values()):
        valid = bool(valid and osl and osl[0][1])
        if not valid:
          (variants, params, api_versions) = null_state
          break
        node_variants, node_params, node_api = osl[0][3:6]
        if idx == 0: # first entry
          variants = set(node_variants)
          params = set(node_params)
          api_versions = set(node_api)
        else: # keep consistency
          variants.intersection_update(node_variants)
          params.intersection_update(node_params)
          api_versions.intersection_update(node_api)

      is_hid = os_name in cluster.hidden_os
      is_blk = os_name in cluster.blacklisted_os
      if ((self._HID not in self.op.output_fields and is_hid) or
          (self._BLK not in self.op.output_fields and is_blk) or
          (self._VLD not in self.op.output_fields and not valid)):
        continue

      for field in self.op.output_fields:
        if field == "name":
          val = os_name
        elif field == self._VLD:
          val = valid
        elif field == "node_status":
          # this is just a copy of the dict
          val = {}
          for node_name, nos_list in os_data.items():
            val[node_name] = nos_list
        elif field == "variants":
          val = utils.NiceSort(list(variants))
        elif field == "parameters":
          val = list(params)
        elif field == "api_versions":
          val = list(api_versions)
        elif field == self._HID:
          val = is_hid
        elif field == self._BLK:
          val = is_blk
        else:
          raise errors.ParameterError(field)
        row.append(val)
      output.append(row)

    return output


class LUNodeRemove(LogicalUnit):
  """Logical unit for removing a node.

  """
  HPATH = "node-remove"
  HTYPE = constants.HTYPE_NODE

  def BuildHooksEnv(self):
    """Build hooks env.

    This doesn't run on the target node in the pre phase as a failed
    node would then be impossible to remove.

    """
    env = {
      "OP_TARGET": self.op.node_name,
      "NODE_NAME": self.op.node_name,
      }
    all_nodes = self.cfg.GetNodeList()
    try:
      all_nodes.remove(self.op.node_name)
    except ValueError:
      logging.warning("Node %s which is about to be removed not found"
                      " in the all nodes list", self.op.node_name)
    return env, all_nodes, all_nodes

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

    instance_list = self.cfg.GetInstanceList()

    masternode = self.cfg.GetMasterNode()
    if node.name == masternode:
      raise errors.OpPrereqError("Node is the master node,"
                                 " you need to failover first.",
                                 errors.ECODE_INVAL)

    for instance_name in instance_list:
      instance = self.cfg.GetInstanceInfo(instance_name)
      if node.name in instance.all_nodes:
        raise errors.OpPrereqError("Instance %s is still running on the node,"
                                   " please remove first." % instance_name,
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

    # Promote nodes to master candidate as needed
    _AdjustCandidatePool(self, exceptions=[node.name])
    self.context.RemoveNode(node.name)

    # Run post hooks on the node before it's removed
    hm = self.proc.hmclass(self.rpc.call_hooks_runner, self)
    try:
      hm.RunPhase(constants.HOOKS_PHASE_POST, [node.name])
    except:
      # pylint: disable-msg=W0702
      self.LogWarning("Errors occurred running hooks on %s" % node.name)

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
    lu.share_locks[locking.LEVEL_NODE] = 1

    if self.names:
      self.wanted = _GetWantedNodes(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = (self.use_locking and
                       query.NQ_LIVE in self.requested_data)

    if self.do_locking:
      # if we don't request only static fields, we need to lock the nodes
      lu.needed_locks[locking.LEVEL_NODE] = self.wanted

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    all_info = lu.cfg.GetAllNodesInfo()

    nodenames = self._GetNames(lu, all_info.keys(), locking.LEVEL_NODE)

    # Gather data as requested
    if query.NQ_LIVE in self.requested_data:
      node_data = lu.rpc.call_node_info(nodenames, lu.cfg.GetVGName(),
                                        lu.cfg.GetHypervisorType())
      live_data = dict((name, nresult.payload)
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
  # pylint: disable-msg=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.nq = _NodeQuery(self.op.names, self.op.output_fields,
                         self.op.use_locking)

  def ExpandNames(self):
    self.nq.ExpandNames(self)

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
    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1
    if not self.op.nodes:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
    else:
      self.needed_locks[locking.LEVEL_NODE] = \
        _GetWantedNodes(self, self.op.nodes)

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    nodenames = self.acquired_locks[locking.LEVEL_NODE]
    volumes = self.rpc.call_node_volumes(nodenames)

    ilist = [self.cfg.GetInstanceInfo(iname) for iname
             in self.cfg.GetInstanceList()]

    lv_by_node = dict([(inst, inst.MapLVsByNode()) for inst in ilist])

    output = []
    for node in nodenames:
      nresult = volumes[node]
      if nresult.offline:
        continue
      msg = nresult.fail_msg
      if msg:
        self.LogWarning("Can't compute volume data on node %s: %s", node, msg)
        continue

      node_vols = nresult.payload[:]
      node_vols.sort(key=lambda vol: vol['dev'])

      for vol in node_vols:
        node_output = []
        for field in self.op.output_fields:
          if field == "node":
            val = node
          elif field == "phys":
            val = vol['dev']
          elif field == "vg":
            val = vol['vg']
          elif field == "name":
            val = vol['name']
          elif field == "size":
            val = int(float(vol['size']))
          elif field == "instance":
            for inst in ilist:
              if node not in lv_by_node[inst]:
                continue
              if vol['name'] in lv_by_node[inst][node]:
                val = inst.name
                break
            else:
              val = '-'
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
    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1

    if self.op.nodes:
      self.needed_locks[locking.LEVEL_NODE] = \
        _GetWantedNodes(self, self.op.nodes)
    else:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    self.nodes = self.acquired_locks[locking.LEVEL_NODE]

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
    lu.share_locks[locking.LEVEL_INSTANCE] = 1
    lu.share_locks[locking.LEVEL_NODE] = 1

    if self.names:
      self.wanted = _GetWantedInstances(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = (self.use_locking and
                       query.IQ_LIVE in self.requested_data)
    if self.do_locking:
      lu.needed_locks[locking.LEVEL_INSTANCE] = self.wanted
      lu.needed_locks[locking.LEVEL_NODE] = []
      lu.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, lu, level):
    if level == locking.LEVEL_NODE and self.do_locking:
      lu._LockInstancesNodes() # pylint: disable-msg=W0212

  def _GetQueryData(self, lu):
    """Computes the list of instances and their attributes.

    """
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
            if all_info[inst].primary_node == name:
              live_data.update(result.payload)
            else:
              wrongnode_inst.add(inst)
        # else no instance is alive
    else:
      live_data = {}

    if query.IQ_DISKUSAGE in self.requested_data:
      disk_usage = dict((inst.name,
                         _ComputeDiskSize(inst.disk_template,
                                          [{"size": disk.size}
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

    return query.InstanceQueryData(instance_list, lu.cfg.GetClusterInfo(),
                                   disk_usage, offline_nodes, bad_nodes,
                                   live_data, wrongnode_inst, consinfo)


class LUQuery(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable-msg=W0142
  REQ_BGL = False

  def CheckArguments(self):
    qcls = _GetQueryImplementation(self.op.what)
    names = qlang.ReadSimpleFilter("name", self.op.filter)

    self.impl = qcls(names, self.op.fields, False)

  def ExpandNames(self):
    self.impl.ExpandNames(self)

  def DeclareLocks(self, level):
    self.impl.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.impl.NewStyleQuery(self)


class LUQueryFields(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable-msg=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.qcls = _GetQueryImplementation(self.op.what)

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    return self.qcls.FieldsQuery(self.op.fields)


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
    if self.op.readd and self.op.group:
      raise errors.OpPrereqError("Cannot pass a node group when a node is"
                                 " being readded", errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on all nodes before, and on all nodes + the new node after.

    """
    env = {
      "OP_TARGET": self.op.node_name,
      "NODE_NAME": self.op.node_name,
      "NODE_PIP": self.op.primary_ip,
      "NODE_SIP": self.op.secondary_ip,
      "MASTER_CAPABLE": str(self.op.master_capable),
      "VM_CAPABLE": str(self.op.vm_capable),
      }
    nodes_0 = self.cfg.GetNodeList()
    nodes_1 = nodes_0 + [self.op.node_name, ]
    return env, nodes_0, nodes_1

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

    for existing_node_name in node_list:
      existing_node = cfg.GetNodeInfo(existing_node_name)

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
                                   group=node_group)

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)

  def Exec(self, feedback_fn):
    """Adds the new node to the cluster.

    """
    new_node = self.new_node
    node = new_node.name

    # We adding a new node so we assume it's powered
    new_node.powered = True

    # for re-adds, reset the offline/drained/master-candidate flags;
    # we need to reset here, otherwise offline would prevent RPC calls
    # later in the procedure; this also means that if the re-add
    # fails, we are left with a non-offlined, broken node
    if self.op.readd:
      new_node.drained = new_node.offline = False # pylint: disable-msg=W0201
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

    # check connectivity
    result = self.rpc.call_version([node])[node]
    result.Raise("Can't get version information from node %s" % node)
    if constants.PROTOCOL_VERSION == result.payload:
      logging.info("Communication to node %s fine, sw version %s match",
                   node, result.payload)
    else:
      raise errors.OpExecError("Version mismatch master version %s,"
                               " node version %s" %
                               (constants.PROTOCOL_VERSION, result.payload))

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
      constants.NV_NODELIST: [node],
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
        raise errors.OpExecError("ssh/hostname verification failed.")

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
                self.op.secondary_ip, self.op.ndparams]
    if all_mods.count(None) == len(all_mods):
      raise errors.OpPrereqError("Please pass at least one modification",
                                 errors.ECODE_INVAL)
    if all_mods.count(True) > 1:
      raise errors.OpPrereqError("Can't set the node into more than one"
                                 " state at the same time",
                                 errors.ECODE_INVAL)

    # Boolean value that tells us whether we might be demoting from MC
    self.might_demote = (self.op.master_candidate == False or
                         self.op.offline == True or
                         self.op.drained == True or
                         self.op.master_capable == False)

    if self.op.secondary_ip:
      if not netutils.IP4Address.IsValid(self.op.secondary_ip):
        raise errors.OpPrereqError("Secondary IP (%s) needs to be a valid IPv4"
                                   " address" % self.op.secondary_ip,
                                   errors.ECODE_INVAL)

    self.lock_all = self.op.auto_promote and self.might_demote
    self.lock_instances = self.op.secondary_ip is not None

  def ExpandNames(self):
    if self.lock_all:
      self.needed_locks = {locking.LEVEL_NODE: locking.ALL_SET}
    else:
      self.needed_locks = {locking.LEVEL_NODE: self.op.node_name}

    if self.lock_instances:
      self.needed_locks[locking.LEVEL_INSTANCE] = locking.ALL_SET

  def DeclareLocks(self, level):
    # If we have locked all instances, before waiting to lock nodes, release
    # all the ones living on nodes unrelated to the current operation.
    if level == locking.LEVEL_NODE and self.lock_instances:
      instances_release = []
      instances_keep = []
      self.affected_instances = []
      if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
        for instance_name in self.acquired_locks[locking.LEVEL_INSTANCE]:
          instance = self.context.cfg.GetInstanceInfo(instance_name)
          i_mirrored = instance.disk_template in constants.DTS_NET_MIRROR
          if i_mirrored and self.op.node_name in instance.all_nodes:
            instances_keep.append(instance_name)
            self.affected_instances.append(instance)
          else:
            instances_release.append(instance_name)
        if instances_release:
          self.context.glm.release(locking.LEVEL_INSTANCE, instances_release)
          self.acquired_locks[locking.LEVEL_INSTANCE] = instances_keep

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master node.

    """
    env = {
      "OP_TARGET": self.op.node_name,
      "MASTER_CANDIDATE": str(self.op.master_candidate),
      "OFFLINE": str(self.op.offline),
      "DRAINED": str(self.op.drained),
      "MASTER_CAPABLE": str(self.op.master_capable),
      "VM_CAPABLE": str(self.op.vm_capable),
      }
    nl = [self.cfg.GetMasterNode(),
          self.op.node_name]
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    node = self.node = self.cfg.GetNodeInfo(self.op.node_name)

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

    if self.op.vm_capable == False:
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
                                   " promotion", errors.ECODE_STATE)

    self.old_flags = old_flags = (node.master_candidate,
                                  node.drained, node.offline)
    assert old_flags in self._F2R, "Un-handled old flags  %s" % str(old_flags)
    self.old_role = old_role = self._F2R[old_flags]

    # Check for ineffective changes
    for attr in self._FLAGS:
      if (getattr(self.op, attr) == False and getattr(node, attr) == False):
        self.LogInfo("Ignoring request to unset flag %s, already unset", attr)
        setattr(self.op, attr, None)

    # Past this point, any flag change to False means a transition
    # away from the respective state, as only real changes are kept

    # TODO: We might query the real power state if it supports OOB
    if _SupportsOob(self.cfg, node):
      if self.op.offline is False and not (node.powered or
                                           self.op.powered == True):
        raise errors.OpPrereqError(("Please power on node %s first before you"
                                    " can reset offline state") %
                                   self.op.node_name)
    elif self.op.powered is not None:
      raise errors.OpPrereqError(("Unable to change powered state for node %s"
                                  " which does not support out-of-band"
                                  " handling") % self.op.node_name)

    # If we're being deofflined/drained, we'll MC ourself if needed
    if (self.op.drained == False or self.op.offline == False or
        (self.op.master_capable and not node.master_capable)):
      if _DecideSelfPromotion(self):
        self.op.master_candidate = True
        self.LogInfo("Auto-promoting node to master candidate")

    # If we're no longer master capable, we'll demote ourselves from MC
    if self.op.master_capable == False and node.master_candidate:
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

    if self.op.secondary_ip:
      # Ok even without locking, because this can't be changed by any LU
      master = self.cfg.GetNodeInfo(self.cfg.GetMasterNode())
      master_singlehomed = master.secondary_ip == master.primary_ip
      if master_singlehomed and self.op.secondary_ip:
        raise errors.OpPrereqError("Cannot change the secondary ip on a single"
                                   " homed cluster", errors.ECODE_INVAL)

      if node.offline:
        if self.affected_instances:
          raise errors.OpPrereqError("Cannot change secondary ip: offline"
                                     " node has instances (%s) configured"
                                     " to use it" % self.affected_instances)
      else:
        # On online nodes, check that no instances are running, and that
        # the node has the new ip and we can reach it.
        for instance in self.affected_instances:
          _CheckInstanceDown(self, instance, "cannot change secondary ip")

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
      self.new_ndparams = new_ndparams

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
      "architecture": (platform.architecture()[0], platform.machine()),
      "name": cluster.cluster_name,
      "master": cluster.master_node,
      "default_hypervisor": cluster.enabled_hypervisors[0],
      "enabled_hypervisors": cluster.enabled_hypervisors,
      "hvparams": dict([(hypervisor_name, cluster.hvparams[hypervisor_name])
                        for hypervisor_name in cluster.enabled_hypervisors]),
      "os_hvp": os_hvp,
      "beparams": cluster.beparams,
      "osparams": cluster.osparams,
      "nicparams": cluster.nicparams,
      "ndparams": cluster.ndparams,
      "candidate_pool_size": cluster.candidate_pool_size,
      "master_netdev": cluster.master_netdev,
      "volume_group_name": cluster.volume_group_name,
      "drbd_usermode_helper": cluster.drbd_usermode_helper,
      "file_storage_dir": cluster.file_storage_dir,
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
  _FIELDS_DYNAMIC = utils.FieldSet()
  _FIELDS_STATIC = utils.FieldSet("cluster_name", "master_node", "drain_flag",
                                  "watcher_pause", "volume_group_name")

  def CheckArguments(self):
    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    """Dump a representation of the cluster config to the standard output.

    """
    values = []
    for field in self.op.output_fields:
      if field == "cluster_name":
        entry = self.cfg.GetClusterName()
      elif field == "master_node":
        entry = self.cfg.GetMasterNode()
      elif field == "drain_flag":
        entry = os.path.exists(constants.JOB_QUEUE_DRAIN_FILE)
      elif field == "watcher_pause":
        entry = utils.ReadWatcherPauseFile(constants.WATCHER_PAUSEFILE)
      elif field == "volume_group_name":
        entry = self.cfg.GetVGName()
      else:
        raise errors.ParameterError(field)
      values.append(entry)
    return values


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
      result = lu.rpc.call_blockdev_assemble(node, node_disk, iname, False, idx)
      msg = result.fail_msg
      if msg:
        lu.proc.LogWarning("Could not prepare block device %s on node %s"
                           " (is_primary=False, pass=1): %s",
                           inst_disk.iv_name, node, msg)
        if not ignore_secondaries:
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
      result = lu.rpc.call_blockdev_assemble(node, node_disk, iname, True, idx)
      msg = result.fail_msg
      if msg:
        lu.proc.LogWarning("Could not prepare block device %s on node %s"
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
      lu.proc.LogWarning("", hint="If the message above refers to a"
                         " secondary node,"
                         " you can retry the operation using '--force'.")
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
  _CheckInstanceDown(lu, instance, "cannot shutdown disks")
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
      result = lu.rpc.call_blockdev_shutdown(node, top_disk)
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

  This function check if a given node has the needed amount of free
  memory. In case the node has less memory or we cannot get the
  information from the node, this function raise an OpPrereqError
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
  @raise errors.OpPrereqError: if the node doesn't have enough memory, or
      we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info([node], None, hypervisor_name)
  nodeinfo[node].Raise("Can't get data from node %s" % node,
                       prereq=True, ecode=errors.ECODE_ENVIRON)
  free_mem = nodeinfo[node].payload.get('memory_free', None)
  if not isinstance(free_mem, int):
    raise errors.OpPrereqError("Can't compute free memory on node %s, result"
                               " was '%s'" % (node, free_mem),
                               errors.ECODE_ENVIRON)
  if requested > free_mem:
    raise errors.OpPrereqError("Not enough memory on node %s for %s:"
                               " needed %s MiB, available %s MiB" %
                               (node, reason, requested, free_mem),
                               errors.ECODE_NORES)


def _CheckNodesFreeDiskPerVG(lu, nodenames, req_sizes):
  """Checks if nodes have enough free disk space in the all VGs.

  This function check if all given nodes have the needed amount of
  free disk. In case any node has less disk or we cannot get the
  information from the node, this function raise an OpPrereqError
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

  This function check if all given nodes have the needed amount of
  free disk. In case any node has less disk or we cannot get the
  information from the node, this function raise an OpPrereqError
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
  nodeinfo = lu.rpc.call_node_info(nodenames, vg, None)
  for node in nodenames:
    info = nodeinfo[node]
    info.Raise("Cannot get current information from node %s" % node,
               prereq=True, ecode=errors.ECODE_ENVIRON)
    vg_free = info.payload.get("vg_free", None)
    if not isinstance(vg_free, int):
      raise errors.OpPrereqError("Can't compute free disk space on node"
                                 " %s for vg %s, result was '%s'" %
                                 (node, vg, vg_free), errors.ECODE_ENVIRON)
    if requested > vg_free:
      raise errors.OpPrereqError("Not enough disk space on target node %s"
                                 " vg %s: required %d MiB, available %d MiB" %
                                 (node, vg, requested, vg_free),
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
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "FORCE": self.op.force,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

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
      hv_type = hypervisor.GetHypervisor(instance.hypervisor)
      hv_type.CheckParameterSyntax(filled_hvp)
      _CheckHVParams(self, instance.all_nodes, instance.hypervisor, filled_hvp)

    self.primary_offline = self.cfg.GetNodeInfo(instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.proc.LogWarning("Ignoring offline primary node")

      if self.op.hvparams or self.op.beparams:
        self.proc.LogWarning("Overridden parameters are ignored")
    else:
      _CheckNodeOnline(self, instance.primary_node)

      bep = self.cfg.GetClusterInfo().FillBE(instance)

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
                             bep[constants.BE_MEMORY], instance.hypervisor)

  def Exec(self, feedback_fn):
    """Start the instance.

    """
    instance = self.instance
    force = self.op.force

    self.cfg.MarkInstanceUp(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.proc.LogInfo("Primary node offline, marked instance as started")
    else:
      node_current = instance.primary_node

      _StartInstanceDisks(self, instance, force)

      result = self.rpc.call_instance_start(node_current, instance,
                                            self.op.hvparams, self.op.beparams)
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
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    _CheckNodeOnline(self, instance.primary_node)

    # check bridges existence
    _CheckInstanceBridgesExist(self, instance)

  def Exec(self, feedback_fn):
    """Reboot the instance.

    """
    instance = self.instance
    ignore_secondaries = self.op.ignore_secondaries
    reboot_type = self.op.reboot_type

    node_current = instance.primary_node

    if reboot_type in [constants.INSTANCE_REBOOT_SOFT,
                       constants.INSTANCE_REBOOT_HARD]:
      for disk in instance.disks:
        self.cfg.SetDiskID(disk, node_current)
      result = self.rpc.call_instance_reboot(node_current, instance,
                                             reboot_type,
                                             self.op.shutdown_timeout)
      result.Raise("Could not reboot instance")
    else:
      result = self.rpc.call_instance_shutdown(node_current, instance,
                                               self.op.shutdown_timeout)
      result.Raise("Could not shutdown instance for full reboot")
      _ShutdownInstanceDisks(self, instance)
      _StartInstanceDisks(self, instance, ignore_secondaries)
      result = self.rpc.call_instance_start(node_current, instance, None, None)
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
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    self.primary_offline = \
      self.cfg.GetNodeInfo(self.instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.proc.LogWarning("Ignoring offline primary node")
    else:
      _CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Shutdown the instance.

    """
    instance = self.instance
    node_current = instance.primary_node
    timeout = self.op.timeout

    self.cfg.MarkInstanceDown(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.proc.LogInfo("Primary node offline, marked instance as stopped")
    else:
      result = self.rpc.call_instance_shutdown(node_current, instance, timeout)
      msg = result.fail_msg
      if msg:
        self.proc.LogWarning("Could not shutdown instance: %s" % msg)

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
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node, "Instance primary node"
                     " offline, cannot reinstall")
    for node in instance.secondary_nodes:
      _CheckNodeOnline(self, node, "Instance secondary node offline,"
                       " cannot reinstall")

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name,
                                 errors.ECODE_INVAL)
    _CheckInstanceDown(self, instance, "cannot reinstall")

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
      result = self.rpc.call_instance_os_add(inst.primary_node, inst, True,
                                             self.op.debug_level,
                                             osparams=self.os_inst)
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

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node)

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name, errors.ECODE_INVAL)
    _CheckInstanceDown(self, instance, "cannot recreate disks")

    if not self.op.disks:
      self.op.disks = range(len(instance.disks))
    else:
      for idx in self.op.disks:
        if idx >= len(instance.disks):
          raise errors.OpPrereqError("Invalid disk index passed '%s'" % idx,
                                     errors.ECODE_INVAL)

    self.instance = instance

  def Exec(self, feedback_fn):
    """Recreate the disks.

    """
    to_skip = []
    for idx, _ in enumerate(self.instance.disks):
      if idx not in self.op.disks: # disk idx has not been passed in
        to_skip.append(idx)
        continue

    _CreateDisks(self, self.instance, to_skip=to_skip)


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
      raise errors.OpPrereqError("Cannot do ip check without a name check",
                                 errors.ECODE_INVAL)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["INSTANCE_NEW_NAME"] = self.op.new_name
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    self.op.instance_name = _ExpandInstanceName(self.cfg,
                                                self.op.instance_name)
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None
    _CheckNodeOnline(self, instance.primary_node)
    _CheckInstanceDown(self, instance, "cannot rename")
    self.instance = instance

    new_name = self.op.new_name
    if self.op.name_check:
      hostname = netutils.GetHostname(name=new_name)
      self.LogInfo("Resolved given name '%s' to '%s'", new_name,
                   hostname.name)
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
    if (inst.disk_template == constants.DT_FILE and
        self.op.new_name != inst.name):
      old_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])
      rename_file_storage = True

    self.cfg.RenameInstance(inst.name, self.op.new_name)
    # Change the instance lock. This is definitely safe while we hold the BGL
    self.context.glm.remove(locking.LEVEL_INSTANCE, old_name)
    self.context.glm.add(locking.LEVEL_INSTANCE, self.op.new_name)

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
    try:
      result = self.rpc.call_instance_run_rename(inst.primary_node, inst,
                                                 old_name, self.op.debug_level)
      msg = result.fail_msg
      if msg:
        msg = ("Could not run OS rename script for instance %s on node %s"
               " (but the instance has been renamed in Ganeti): %s" %
               (inst.name, inst.primary_node, msg))
        self.proc.LogWarning(msg)
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
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["SHUTDOWN_TIMEOUT"] = self.op.shutdown_timeout
    nl = [self.cfg.GetMasterNode()]
    nl_post = list(self.instance.all_nodes) + nl
    return env, nl, nl_post

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

    _RemoveInstance(self, feedback_fn, instance, self.op.ignore_failures)


def _RemoveInstance(lu, feedback_fn, instance, ignore_failures):
  """Utility function to remove an instance.

  """
  logging.info("Removing block devices for instance %s", instance.name)

  if not _RemoveDisks(lu, instance):
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
  # pylint: disable-msg=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.iq = _InstanceQuery(self.op.names, self.op.output_fields,
                             self.op.use_locking)

  def ExpandNames(self):
    self.iq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.iq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.iq.OldStyleQuery(self)


class LUInstanceFailover(LogicalUnit):
  """Failover an instance.

  """
  HPATH = "instance-failover"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    instance = self.instance
    source_node = instance.primary_node
    target_node = instance.secondary_nodes[0]
    env = {
      "IGNORE_CONSISTENCY": self.op.ignore_consistency,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      "OLD_PRIMARY": source_node,
      "OLD_SECONDARY": target_node,
      "NEW_PRIMARY": target_node,
      "NEW_SECONDARY": source_node,
      }
    env.update(_BuildInstanceHookEnvByObject(self, instance))
    nl = [self.cfg.GetMasterNode()] + list(instance.secondary_nodes)
    nl_post = list(nl)
    nl_post.append(source_node)
    return env, nl, nl_post

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    bep = self.cfg.GetClusterInfo().FillBE(instance)
    if instance.disk_template not in constants.DTS_NET_MIRROR:
      raise errors.OpPrereqError("Instance's disk layout is not"
                                 " network mirrored, cannot failover.",
                                 errors.ECODE_STATE)

    secondary_nodes = instance.secondary_nodes
    if not secondary_nodes:
      raise errors.ProgrammerError("no secondary node but using "
                                   "a mirrored disk template")

    target_node = secondary_nodes[0]
    _CheckNodeOnline(self, target_node)
    _CheckNodeNotDrained(self, target_node)
    if instance.admin_up:
      # check memory requirements on the secondary node
      _CheckNodeFreeMemory(self, target_node, "failing over instance %s" %
                           instance.name, bep[constants.BE_MEMORY],
                           instance.hypervisor)
    else:
      self.LogInfo("Not checking memory on the secondary node as"
                   " instance will not be started")

    # check bridge existance
    _CheckInstanceBridgesExist(self, instance, node=target_node)

  def Exec(self, feedback_fn):
    """Failover an instance.

    The failover is done by shutting it down on its present node and
    starting it on the secondary.

    """
    instance = self.instance
    primary_node = self.cfg.GetNodeInfo(instance.primary_node)

    source_node = instance.primary_node
    target_node = instance.secondary_nodes[0]

    if instance.admin_up:
      feedback_fn("* checking disk consistency between source and target")
      for dev in instance.disks:
        # for drbd, these are drbd over lvm
        if not _CheckDiskConsistency(self, dev, target_node, False):
          if not self.op.ignore_consistency:
            raise errors.OpExecError("Disk %s is degraded on target node,"
                                     " aborting failover." % dev.iv_name)
    else:
      feedback_fn("* not checking disk consistency as instance is not running")

    feedback_fn("* shutting down instance on source node")
    logging.info("Shutting down instance %s on node %s",
                 instance.name, source_node)

    result = self.rpc.call_instance_shutdown(source_node, instance,
                                             self.op.shutdown_timeout)
    msg = result.fail_msg
    if msg:
      if self.op.ignore_consistency or primary_node.offline:
        self.proc.LogWarning("Could not shutdown instance %s on node %s."
                             " Proceeding anyway. Please make sure node"
                             " %s is down. Error details: %s",
                             instance.name, source_node, source_node, msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (instance.name, source_node, msg))

    feedback_fn("* deactivating the instance's disks on source node")
    if not _ShutdownInstanceDisks(self, instance, ignore_primary=True):
      raise errors.OpExecError("Can't shut down the instance's disks.")

    instance.primary_node = target_node
    # distribute new instance config to the other nodes
    self.cfg.Update(instance, feedback_fn)

    # Only start the instance if it's marked as up
    if instance.admin_up:
      feedback_fn("* activating the instance's disks on target node")
      logging.info("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, _ = _AssembleInstanceDisks(self, instance,
                                           ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      feedback_fn("* starting the instance on the target node")
      result = self.rpc.call_instance_start(target_node, instance, None, None)
      msg = result.fail_msg
      if msg:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (instance.name, target_node, msg))


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

    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

    self._migrater = TLMigrateInstance(self, self.op.instance_name,
                                       self.op.cleanup)
    self.tasklets = [self._migrater]

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    instance = self._migrater.instance
    source_node = instance.primary_node
    target_node = instance.secondary_nodes[0]
    env = _BuildInstanceHookEnvByObject(self, instance)
    env["MIGRATE_LIVE"] = self._migrater.live
    env["MIGRATE_CLEANUP"] = self.op.cleanup
    env.update({
        "OLD_PRIMARY": source_node,
        "OLD_SECONDARY": target_node,
        "NEW_PRIMARY": target_node,
        "NEW_SECONDARY": source_node,
        })
    nl = [self.cfg.GetMasterNode()] + list(instance.secondary_nodes)
    nl_post = list(nl)
    nl_post.append(source_node)
    return env, nl, nl_post


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
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes(primary_only=True)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "TARGET_NODE": self.op.target_node,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = [self.cfg.GetMasterNode()] + [self.instance.primary_node,
                                       self.op.target_node]
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

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

    if instance.admin_up:
      # check memory requirements on the secondary node
      _CheckNodeFreeMemory(self, target_node, "failing over instance %s" %
                           instance.name, bep[constants.BE_MEMORY],
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

    result = self.rpc.call_instance_shutdown(source_node, instance,
                                             self.op.shutdown_timeout)
    msg = result.fail_msg
    if msg:
      if self.op.ignore_consistency:
        self.proc.LogWarning("Could not shutdown instance %s on node %s."
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
      self.LogWarning("Device creation failed, reverting...")
      try:
        _RemoveDisks(self, instance, target_node=target_node)
      finally:
        self.cfg.ReleaseDRBDMinors(instance.name)
        raise

    cluster_name = self.cfg.GetClusterInfo().cluster_name

    errs = []
    # activate, get path, copy the data over
    for idx, disk in enumerate(instance.disks):
      self.LogInfo("Copying data for disk %d", idx)
      result = self.rpc.call_blockdev_assemble(target_node, disk,
                                               instance.name, True, idx)
      if result.fail_msg:
        self.LogWarning("Can't assemble newly created disk %d: %s",
                        idx, result.fail_msg)
        errs.append(result.fail_msg)
        break
      dev_path = result.payload
      result = self.rpc.call_blockdev_export(source_node, disk,
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
    if instance.admin_up:
      self.LogInfo("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, _ = _AssembleInstanceDisks(self, instance,
                                           ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      result = self.rpc.call_instance_start(target_node, instance, None, None)
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

  def ExpandNames(self):
    self.op.node_name = _ExpandNodeName(self.cfg, self.op.node_name)

    self.needed_locks = {
      locking.LEVEL_NODE: [self.op.node_name],
      }

    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

    # Create tasklets for migrating instances for all instances on this node
    names = []
    tasklets = []

    for inst in _GetNodePrimaryInstances(self.cfg, self.op.node_name):
      logging.debug("Migrating instance %s", inst.name)
      names.append(inst.name)

      tasklets.append(TLMigrateInstance(self, inst.name, False))

    self.tasklets = tasklets

    # Declare instance locks
    self.needed_locks[locking.LEVEL_INSTANCE] = names

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    env = {
      "NODE_NAME": self.op.node_name,
      }

    nl = [self.cfg.GetMasterNode()]

    return (env, nl, nl)


class TLMigrateInstance(Tasklet):
  """Tasklet class for instance migration.

  @type live: boolean
  @ivar live: whether the migration will be done live or non-live;
      this variable is initalized only after CheckPrereq has run

  """
  def __init__(self, lu, instance_name, cleanup):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_name = instance_name
    self.cleanup = cleanup
    self.live = False # will be overridden later

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    instance_name = _ExpandInstanceName(self.lu.cfg, self.instance_name)
    instance = self.cfg.GetInstanceInfo(instance_name)
    assert instance is not None

    if instance.disk_template != constants.DT_DRBD8:
      raise errors.OpPrereqError("Instance's disk layout is not"
                                 " drbd8, cannot migrate.", errors.ECODE_STATE)

    secondary_nodes = instance.secondary_nodes
    if not secondary_nodes:
      raise errors.ConfigurationError("No secondary node but using"
                                      " drbd8 disk template")

    i_be = self.cfg.GetClusterInfo().FillBE(instance)

    target_node = secondary_nodes[0]
    # check memory requirements on the secondary node
    _CheckNodeFreeMemory(self.lu, target_node, "migrating instance %s" %
                         instance.name, i_be[constants.BE_MEMORY],
                         instance.hypervisor)

    # check bridge existance
    _CheckInstanceBridgesExist(self.lu, instance, node=target_node)

    if not self.cleanup:
      _CheckNodeNotDrained(self.lu, target_node)
      result = self.rpc.call_instance_migratable(instance.primary_node,
                                                 instance)
      result.Raise("Can't migrate, please use failover",
                   prereq=True, ecode=errors.ECODE_STATE)

    self.instance = instance

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
      i_hv = self.cfg.GetClusterInfo().FillHV(instance, skip_globals=False)
      self.lu.op.mode = i_hv[constants.HV_MIGRATION_MODE]

    self.live = self.lu.op.mode == constants.HT_MIGRATION_LIVE

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
                                            self.instance.disks)
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
                                           self.instance.disks,
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
                               " or the hypervisor is confused. You will have"
                               " to ensure manually that it runs only on one"
                               " and restart this operation.")

    if not (runningon_source or runningon_target):
      raise errors.OpExecError("Instance does not seem to be running at all."
                               " In this case, it's safer to repair by"
                               " running 'gnt-instance stop' to ensure disk"
                               " shutdown, and then restarting it.")

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
    try:
      self._EnsureSecondary(target_node)
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()
    except errors.OpExecError, err:
      self.lu.LogWarning("Migration failed and I can't reconnect the"
                         " drives: error '%s'\n"
                         "Please look and recover the instance status" %
                         str(err))

  def _AbortMigration(self):
    """Call the hypervisor code to abort a started migration.

    """
    instance = self.instance
    target_node = self.target_node
    migration_info = self.migration_info

    abort_result = self.rpc.call_finalize_migration(target_node,
                                                    instance,
                                                    migration_info,
                                                    False)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on target node %s: %s",
                    target_node, abort_msg)
      # Don't raise an exception here, as we stil have to try to revert the
      # disk status, even if this step failed.

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

    self.feedback_fn("* checking disk consistency between source and target")
    for dev in instance.disks:
      if not _CheckDiskConsistency(self.lu, dev, target_node, False):
        raise errors.OpExecError("Disk %s is degraded or not fully"
                                 " synchronized on target node,"
                                 " aborting migrate." % dev.iv_name)

    # First get the migration information from the remote node
    result = self.rpc.call_migration_info(source_node, instance)
    msg = result.fail_msg
    if msg:
      log_err = ("Failed fetching source migration information from %s: %s" %
                 (source_node, msg))
      logging.error(log_err)
      raise errors.OpExecError(log_err)

    self.migration_info = migration_info = result.payload

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
    time.sleep(10)
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
    time.sleep(10)

    instance.primary_node = target_node
    # distribute new instance config to the other nodes
    self.cfg.Update(instance, self.feedback_fn)

    result = self.rpc.call_finalize_migration(target_node,
                                              instance,
                                              migration_info,
                                              True)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed:"
                    " %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    self._EnsureSecondary(source_node)
    self._WaitUntilSync()
    self._GoStandalone()
    self._GoReconnect(False)
    self._WaitUntilSync()

    self.feedback_fn("* done")

  def Exec(self, feedback_fn):
    """Perform the migration.

    """
    feedback_fn("Migrating instance %s" % self.instance.name)

    self.feedback_fn = feedback_fn

    self.source_node = self.instance.primary_node
    self.target_node = self.instance.secondary_nodes[0]
    self.all_nodes = [self.source_node, self.target_node]
    self.nodes_ip = {
      self.source_node: self.cfg.GetNodeInfo(self.source_node).secondary_ip,
      self.target_node: self.cfg.GetNodeInfo(self.target_node).secondary_ip,
      }

    if self.cleanup:
      return self._ExecCleanup()
    else:
      return self._ExecMigration()


def _CreateBlockDev(lu, node, instance, device, force_create,
                    info, force_open):
  """Create a tree of block devices on a given node.

  If this device type has to be created on secondaries, create it and
  all its children.

  If not, just recurse to children keeping the same 'force' value.

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

  """
  if device.CreateOnSecondary():
    force_create = True

  if device.children:
    for child in device.children:
      _CreateBlockDev(lu, node, instance, child, force_create,
                      info, force_open)

  if not force_create:
    return

  _CreateSingleBlockDev(lu, node, instance, device, info, force_open)


def _CreateSingleBlockDev(lu, node, instance, device, info, force_open):
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

  """
  lu.cfg.SetDiskID(device, node)
  result = lu.rpc.call_blockdev_create(node, device, device.size,
                                       instance.name, force_open, info)
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


def _GenerateDRBD8Branch(lu, primary, secondary, size, vgname, names, iv_name,
                         p_minor, s_minor):
  """Generate a drbd8 device complete with its children.

  """
  port = lu.cfg.AllocatePort()
  shared_secret = lu.cfg.GenerateDRBDSecret(lu.proc.GetECId())
  dev_data = objects.Disk(dev_type=constants.LD_LV, size=size,
                          logical_id=(vgname, names[0]))
  dev_meta = objects.Disk(dev_type=constants.LD_LV, size=128,
                          logical_id=(vgname, names[1]))
  drbd_dev = objects.Disk(dev_type=constants.LD_DRBD8, size=size,
                          logical_id=(primary, secondary, port,
                                      p_minor, s_minor,
                                      shared_secret),
                          children=[dev_data, dev_meta],
                          iv_name=iv_name)
  return drbd_dev


def _GenerateDiskTemplate(lu, template_name,
                          instance_name, primary_node,
                          secondary_nodes, disk_info,
                          file_storage_dir, file_driver,
                          base_index, feedback_fn):
  """Generate the entire disk layout for a given template type.

  """
  #TODO: compute space requirements

  vgname = lu.cfg.GetVGName()
  disk_count = len(disk_info)
  disks = []
  if template_name == constants.DT_DISKLESS:
    pass
  elif template_name == constants.DT_PLAIN:
    if len(secondary_nodes) != 0:
      raise errors.ProgrammerError("Wrong template configuration")

    names = _GenerateUniqueNames(lu, [".disk%d" % (base_index + i)
                                      for i in range(disk_count)])
    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      vg = disk.get("vg", vgname)
      feedback_fn("* disk %i, vg %s, name %s" % (idx, vg, names[idx]))
      disk_dev = objects.Disk(dev_type=constants.LD_LV, size=disk["size"],
                              logical_id=(vg, names[idx]),
                              iv_name="disk/%d" % disk_index,
                              mode=disk["mode"])
      disks.append(disk_dev)
  elif template_name == constants.DT_DRBD8:
    if len(secondary_nodes) != 1:
      raise errors.ProgrammerError("Wrong template configuration")
    remote_node = secondary_nodes[0]
    minors = lu.cfg.AllocateDRBDMinor(
      [primary_node, remote_node] * len(disk_info), instance_name)

    names = []
    for lv_prefix in _GenerateUniqueNames(lu, [".disk%d" % (base_index + i)
                                               for i in range(disk_count)]):
      names.append(lv_prefix + "_data")
      names.append(lv_prefix + "_meta")
    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      vg = disk.get("vg", vgname)
      disk_dev = _GenerateDRBD8Branch(lu, primary_node, remote_node,
                                      disk["size"], vg, names[idx*2:idx*2+2],
                                      "disk/%d" % disk_index,
                                      minors[idx*2], minors[idx*2+1])
      disk_dev.mode = disk["mode"]
      disks.append(disk_dev)
  elif template_name == constants.DT_FILE:
    if len(secondary_nodes) != 0:
      raise errors.ProgrammerError("Wrong template configuration")

    opcodes.RequireFileStorage()

    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      disk_dev = objects.Disk(dev_type=constants.LD_FILE, size=disk["size"],
                              iv_name="disk/%d" % disk_index,
                              logical_id=(file_driver,
                                          "%s/disk%d" % (file_storage_dir,
                                                         disk_index)),
                              mode=disk["mode"])
      disks.append(disk_dev)
  else:
    raise errors.ProgrammerError("Invalid disk template '%s'" % template_name)
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


def _WipeDisks(lu, instance):
  """Wipes instance disks.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should create
  @return: the success of the wipe

  """
  node = instance.primary_node
  logging.info("Pause sync of instance %s disks", instance.name)
  result = lu.rpc.call_blockdev_pause_resume_sync(node, instance.disks, True)

  for idx, success in enumerate(result.payload):
    if not success:
      logging.warn("pause-sync of instance %s for disks %d failed",
                   instance.name, idx)

  try:
    for idx, device in enumerate(instance.disks):
      lu.LogInfo("* Wiping disk %d", idx)
      logging.info("Wiping disk %d for instance %s", idx, instance.name)

      # The wipe size is MIN_WIPE_CHUNK_PERCENT % of the instance disk but
      # MAX_WIPE_CHUNK at max
      wipe_chunk_size = min(constants.MAX_WIPE_CHUNK, device.size / 100.0 *
                            constants.MIN_WIPE_CHUNK_PERCENT)

      offset = 0
      size = device.size
      last_output = 0
      start_time = time.time()

      while offset < size:
        wipe_size = min(wipe_chunk_size, size - offset)
        result = lu.rpc.call_blockdev_wipe(node, device, offset, wipe_size)
        result.Raise("Could not wipe disk %d at offset %d for size %d" %
                     (idx, offset, wipe_size))
        now = time.time()
        offset += wipe_size
        if now - last_output >= 60:
          eta = _CalcEta(now - start_time, offset, size)
          lu.LogInfo(" - done: %.1f%% ETA: %s" %
                     (offset / float(size) * 100, utils.FormatSeconds(eta)))
          last_output = now
  finally:
    logging.info("Resume sync of instance %s disks", instance.name)

    result = lu.rpc.call_blockdev_pause_resume_sync(node, instance.disks, False)

    for idx, success in enumerate(result.payload):
      if not success:
        lu.LogWarning("Warning: Resume sync of disk %d failed. Please have a"
                      " look at the status and troubleshoot the issue.", idx)
        logging.warn("resume-sync of instance %s for disks %d failed",
                     instance.name, idx)


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

  if instance.disk_template == constants.DT_FILE:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    result = lu.rpc.call_file_storage_dir_create(pnode, file_storage_dir)

    result.Raise("Failed to create directory '%s' on"
                 " node %s" % (file_storage_dir, pnode))

  # Note: this needs to be kept in sync with adding of disks in
  # LUInstanceSetParams
  for idx, device in enumerate(instance.disks):
    if to_skip and idx in to_skip:
      continue
    logging.info("Creating volume %s for instance %s",
                 device.iv_name, instance.name)
    #HARDCODE
    for node in all_nodes:
      f_create = node == pnode
      _CreateBlockDev(lu, node, instance, device, f_create, info, f_create)


def _RemoveDisks(lu, instance, target_node=None):
  """Remove all disks for an instance.

  This abstracts away some work from `AddInstance()` and
  `RemoveInstance()`. Note that in case some of the devices couldn't
  be removed, the removal will continue with the other ones (compare
  with `_CreateDisks()`).

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
  for device in instance.disks:
    if target_node:
      edata = [(target_node, device)]
    else:
      edata = device.ComputeNodeTree(instance.primary_node)
    for node, disk in edata:
      lu.cfg.SetDiskID(disk, node)
      msg = lu.rpc.call_blockdev_remove(node, disk).fail_msg
      if msg:
        lu.LogWarning("Could not remove block device %s on node %s,"
                      " continuing anyway: %s", device.iv_name, node, msg)
        all_result = False

  if instance.disk_template == constants.DT_FILE:
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
    """Universal algorithm

    """
    vgs = {}
    for disk in disks:
      vgs[disk["vg"]] = vgs.get("vg", 0) + disk["size"] + payload

    return vgs

  # Required free disk space as a function of disk and swap space
  req_size_dict = {
    constants.DT_DISKLESS: {},
    constants.DT_PLAIN: _compute(disks, 0),
    # 128 MB are added for drbd metadata for each disk
    constants.DT_DRBD8: _compute(disks, 128),
    constants.DT_FILE: {},
  }

  if disk_template not in req_size_dict:
    raise errors.ProgrammerError("Disk template '%s' size requirement"
                                 " is unknown" %  disk_template)

  return req_size_dict[disk_template]


def _ComputeDiskSize(disk_template, disks):
  """Compute disk size requirements in the volume group

  """
  # Required free disk space as a function of disk and swap space
  req_size_dict = {
    constants.DT_DISKLESS: None,
    constants.DT_PLAIN: sum(d["size"] for d in disks),
    # 128 MB are added for drbd metadata for each disk
    constants.DT_DRBD8: sum(d["size"] + 128 for d in disks),
    constants.DT_FILE: None,
  }

  if disk_template not in req_size_dict:
    raise errors.ProgrammerError("Disk template '%s' size requirement"
                                 " is unknown" %  disk_template)

  return req_size_dict[disk_template]


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
  hvinfo = lu.rpc.call_hypervisor_validate_params(nodenames,
                                                  hvname,
                                                  hvparams)
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
  result = lu.rpc.call_os_validate(required, nodenames, osname,
                                   [constants.OS_VALIDATE_PARAMETERS],
                                   osparams)
  for node, nres in result.items():
    # we don't check for offline cases since this should be run only
    # against the master node and/or an instance's nodes
    nres.Raise("OS Parameters validation failed on node %s" % node)
    if not nres.payload:
      lu.LogInfo("OS %s not found on node %s, validation skipped",
                 osname, node)


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
      raise errors.OpPrereqError("Cannot do ip check without a name check",
                                 errors.ECODE_INVAL)

    # check nics' parameter names
    for nic in self.op.nics:
      utils.ForceDictType(nic, constants.INIC_PARAMS_TYPES)

    # check disks. parameter names and consistent adopt/no-adopt strategy
    has_adopt = has_no_adopt = False
    for disk in self.op.disks:
      utils.ForceDictType(disk, constants.IDISK_PARAMS_TYPES)
      if "adopt" in disk:
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

    self.adopt_disks = has_adopt

    # instance name verification
    if self.op.name_check:
      self.hostname1 = netutils.GetHostname(name=self.op.instance_name)
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

    if self.op.file_storage_dir and os.path.isabs(self.op.file_storage_dir):
      raise errors.OpPrereqError("File storage directory path not absolute",
                                 errors.ECODE_INVAL)

    ### Node/iallocator related checks
    _CheckIAllocatorOrNode(self, "iallocator", "pnode")

    if self.op.pnode is not None:
      if self.op.disk_template in constants.DTS_NET_MIRROR:
        if self.op.snode is None:
          raise errors.OpPrereqError("The networked disk templates need"
                                     " a mirror node", errors.ECODE_INVAL)
      elif self.op.snode:
        self.LogWarning("Secondary node will be ignored on non-mirrored disk"
                        " template")
        self.op.snode = None

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
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
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
        self.op.src_node = None
        if os.path.isabs(src_path):
          raise errors.OpPrereqError("Importing an instance from an absolute"
                                     " path requires a source node option.",
                                     errors.ECODE_INVAL)
      else:
        self.op.src_node = src_node = _ExpandNodeName(self.cfg, src_node)
        if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
          self.needed_locks[locking.LEVEL_NODE].append(src_node)
        if not os.path.isabs(src_path):
          self.op.src_path = src_path = \
            utils.PathJoin(constants.EXPORT_DIR, src_path)

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    nics = [n.ToDict() for n in self.nics]
    ial = IAllocator(self.cfg, self.rpc,
                     mode=constants.IALLOCATOR_MODE_ALLOC,
                     name=self.op.instance_name,
                     disk_template=self.op.disk_template,
                     tags=[],
                     os=self.op.os_type,
                     vcpus=self.be_full[constants.BE_VCPUS],
                     mem_size=self.be_full[constants.BE_MEMORY],
                     disks=self.disks,
                     nics=nics,
                     hypervisor=self.op.hypervisor,
                     )

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)
    if len(ial.result) != ial.required_nodes:
      raise errors.OpPrereqError("iallocator '%s' returned invalid number"
                                 " of nodes (%s), required %s" %
                                 (self.op.iallocator, len(ial.result),
                                  ial.required_nodes), errors.ECODE_FAULT)
    self.op.pnode = ial.result[0]
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 utils.CommaJoin(ial.result))
    if ial.required_nodes == 2:
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
      memory=self.be_full[constants.BE_MEMORY],
      vcpus=self.be_full[constants.BE_VCPUS],
      nics=_NICListToTuple(self, self.nics),
      disk_template=self.op.disk_template,
      disks=[(d["size"], d["mode"]) for d in self.disks],
      bep=self.be_full,
      hvp=self.hv_full,
      hypervisor_name=self.op.hypervisor,
    ))

    nl = ([self.cfg.GetMasterNode(), self.op.pnode] +
          self.secondaries)
    return env, nl, nl

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
      locked_nodes = self.acquired_locks[locking.LEVEL_NODE]
      exp_list = self.rpc.call_export_list(locked_nodes)
      found = False
      for node in exp_list:
        if exp_list[node].fail_msg:
          continue
        if src_path in exp_list[node].payload:
          found = True
          self.op.src_node = src_node = node
          self.op.src_path = src_path = utils.PathJoin(constants.EXPORT_DIR,
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
      else:
        raise errors.OpPrereqError("No disk template specified and the export"
                                   " is missing the disk_template information",
                                   errors.ECODE_INVAL)

    if not self.op.disks:
      if einfo.has_option(constants.INISECT_INS, "disk_count"):
        disks = []
        # TODO: import the disk iv_name too
        for idx in range(einfo.getint(constants.INISECT_INS, "disk_count")):
          disk_sz = einfo.getint(constants.INISECT_INS, "disk%d_size" % idx)
          disks.append({"size": disk_sz})
        self.op.disks = disks
      else:
        raise errors.OpPrereqError("No disk info specified and the export"
                                   " is missing the disk information",
                                   errors.ECODE_INVAL)

    if (not self.op.nics and
        einfo.has_option(constants.INISECT_INS, "nic_count")):
      nics = []
      for idx in range(einfo.getint(constants.INISECT_INS, "nic_count")):
        ndict = {}
        for name in list(constants.NICS_PARAMETERS) + ["ip", "mac"]:
          v = einfo.get(constants.INISECT_INS, "nic%d_%s" % (idx, name))
          ndict[name] = v
        nics.append(ndict)
      self.op.nics = nics

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

  def CheckPrereq(self):
    """Check prerequisites.

    """
    if self.op.mode == constants.INSTANCE_IMPORT:
      export_info = self._ReadExportInfo()
      self._ReadExportParams(export_info)

    if (not self.cfg.GetVGName() and
        self.op.disk_template not in constants.DTS_NOT_LVM):
      raise errors.OpPrereqError("Cluster does not support lvm-based"
                                 " instances", errors.ECODE_STATE)

    if self.op.hypervisor is None:
      self.op.hypervisor = self.cfg.GetHypervisorType()

    cluster = self.cfg.GetClusterInfo()
    enabled_hvs = cluster.enabled_hypervisors
    if self.op.hypervisor not in enabled_hvs:
      raise errors.OpPrereqError("Selected hypervisor (%s) not enabled in the"
                                 " cluster (%s)" % (self.op.hypervisor,
                                  ",".join(enabled_hvs)),
                                 errors.ECODE_STATE)

    # check hypervisor parameter syntax (locally)
    utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
    filled_hvp = cluster.SimpleFillHV(self.op.hypervisor, self.op.os_type,
                                      self.op.hvparams)
    hv_type = hypervisor.GetHypervisor(self.op.hypervisor)
    hv_type.CheckParameterSyntax(filled_hvp)
    self.hv_full = filled_hvp
    # check that we don't specify global parameters on an instance
    _CheckGlobalHvParams(self.op.hvparams)

    # fill and remember the beparams dict
    utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)
    self.be_full = cluster.SimpleFillBE(self.op.beparams)

    # build os parameters
    self.os_full = cluster.SimpleFillOS(self.op.os_type, self.op.osparams)

    # now that hvp/bep are in final format, let's reset to defaults,
    # if told to do so
    if self.op.identify_defaults:
      self._RevertToDefaults(cluster)

    # NIC buildup
    self.nics = []
    for idx, nic in enumerate(self.op.nics):
      nic_mode_req = nic.get("mode", None)
      nic_mode = nic_mode_req
      if nic_mode is None:
        nic_mode = cluster.nicparams[constants.PP_DEFAULT][constants.NIC_MODE]

      # in routed mode, for the first nic, the default ip is 'auto'
      if nic_mode == constants.NIC_MODE_ROUTED and idx == 0:
        default_ip_mode = constants.VALUE_AUTO
      else:
        default_ip_mode = constants.VALUE_NONE

      # ip validity checks
      ip = nic.get("ip", default_ip_mode)
      if ip is None or ip.lower() == constants.VALUE_NONE:
        nic_ip = None
      elif ip.lower() == constants.VALUE_AUTO:
        if not self.op.name_check:
          raise errors.OpPrereqError("IP address set to auto but name checks"
                                     " have been skipped",
                                     errors.ECODE_INVAL)
        nic_ip = self.hostname1.ip
      else:
        if not netutils.IPAddress.IsValid(ip):
          raise errors.OpPrereqError("Invalid IP address '%s'" % ip,
                                     errors.ECODE_INVAL)
        nic_ip = ip

      # TODO: check the ip address for uniqueness
      if nic_mode == constants.NIC_MODE_ROUTED and not nic_ip:
        raise errors.OpPrereqError("Routed nic mode requires an ip address",
                                   errors.ECODE_INVAL)

      # MAC address verification
      mac = nic.get("mac", constants.VALUE_AUTO)
      if mac not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        mac = utils.NormalizeAndValidateMac(mac)

        try:
          self.cfg.ReserveMAC(mac, self.proc.GetECId())
        except errors.ReservationError:
          raise errors.OpPrereqError("MAC address %s already in use"
                                     " in cluster" % mac,
                                     errors.ECODE_NOTUNIQUE)

      # bridge verification
      bridge = nic.get("bridge", None)
      link = nic.get("link", None)
      if bridge and link:
        raise errors.OpPrereqError("Cannot pass 'bridge' and 'link'"
                                   " at the same time", errors.ECODE_INVAL)
      elif bridge and nic_mode == constants.NIC_MODE_ROUTED:
        raise errors.OpPrereqError("Cannot pass 'bridge' on a routed nic",
                                   errors.ECODE_INVAL)
      elif bridge:
        link = bridge

      nicparams = {}
      if nic_mode_req:
        nicparams[constants.NIC_MODE] = nic_mode_req
      if link:
        nicparams[constants.NIC_LINK] = link

      check_params = cluster.SimpleFillNIC(nicparams)
      objects.NIC.CheckParameterSyntax(check_params)
      self.nics.append(objects.NIC(mac=mac, ip=nic_ip, nicparams=nicparams))

    # disk checks/pre-build
    self.disks = []
    for disk in self.op.disks:
      mode = disk.get("mode", constants.DISK_RDWR)
      if mode not in constants.DISK_ACCESS_SET:
        raise errors.OpPrereqError("Invalid disk access mode '%s'" %
                                   mode, errors.ECODE_INVAL)
      size = disk.get("size", None)
      if size is None:
        raise errors.OpPrereqError("Missing disk size", errors.ECODE_INVAL)
      try:
        size = int(size)
      except (TypeError, ValueError):
        raise errors.OpPrereqError("Invalid disk size '%s'" % size,
                                   errors.ECODE_INVAL)
      vg = disk.get("vg", self.cfg.GetVGName())
      new_disk = {"size": size, "mode": mode, "vg": vg}
      if "adopt" in disk:
        new_disk["adopt"] = disk["adopt"]
      self.disks.append(new_disk)

    if self.op.mode == constants.INSTANCE_IMPORT:

      # Check that the new instance doesn't have less disks than the export
      instance_disks = len(self.disks)
      export_disks = export_info.getint(constants.INISECT_INS, 'disk_count')
      if instance_disks < export_disks:
        raise errors.OpPrereqError("Not enough disks to import."
                                   " (instance: %d, export: %d)" %
                                   (instance_disks, export_disks),
                                   errors.ECODE_INVAL)

      disk_images = []
      for idx in range(export_disks):
        option = 'disk%d_dump' % idx
        if export_info.has_option(constants.INISECT_INS, option):
          # FIXME: are the old os-es, disk sizes, etc. useful?
          export_name = export_info.get(constants.INISECT_INS, option)
          image = utils.PathJoin(self.op.src_path, export_name)
          disk_images.append(image)
        else:
          disk_images.append(False)

      self.src_images = disk_images

      old_name = export_info.get(constants.INISECT_INS, 'name')
      try:
        exp_nic_count = export_info.getint(constants.INISECT_INS, 'nic_count')
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid export file, nic_count is not"
                                   " an integer: %s" % str(err),
                                   errors.ECODE_STATE)
      if self.op.instance_name == old_name:
        for idx, nic in enumerate(self.nics):
          if nic.mac == constants.VALUE_AUTO and exp_nic_count >= idx:
            nic_mac_ini = 'nic%d_mac' % idx
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
        nic.mac = self.cfg.GenerateMAC(self.proc.GetECId())

    #### allocator run

    if self.op.iallocator is not None:
      self._RunAllocator()

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

    # mirror node verification
    if self.op.disk_template in constants.DTS_NET_MIRROR:
      if self.op.snode == pnode.name:
        raise errors.OpPrereqError("The secondary node cannot be the"
                                   " primary node.", errors.ECODE_INVAL)
      _CheckNodeOnline(self, self.op.snode)
      _CheckNodeNotDrained(self, self.op.snode)
      _CheckNodeVmCapable(self, self.op.snode)
      self.secondaries.append(self.op.snode)

    nodenames = [pnode.name] + self.secondaries

    if not self.adopt_disks:
      # Check lv size requirements, if not adopting
      req_sizes = _ComputeDiskSizePerVG(self.op.disk_template, self.disks)
      _CheckNodesFreeDiskPerVG(self, nodenames, req_sizes)

    else: # instead, we must check the adoption data
      all_lvs = set([i["vg"] + "/" + i["adopt"] for i in self.disks])
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
        dsk["size"] = int(float(node_lvs[dsk["vg"] + "/" + dsk["adopt"]][0]))

    _CheckHVParams(self, nodenames, self.op.hypervisor, self.op.hvparams)

    _CheckNodeHasOS(self, pnode.name, self.op.os_type, self.op.force_variant)
    # check OS parameters (remotely)
    _CheckOSParams(self, True, nodenames, self.op.os_type, self.os_full)

    _CheckNicsBridgesExist(self, self.nics, self.pnode.name)

    # memory check on primary node
    if self.op.start:
      _CheckNodeFreeMemory(self, self.pnode.name,
                           "creating instance %s" % self.op.instance_name,
                           self.be_full[constants.BE_MEMORY],
                           self.op.hypervisor)

    self.dry_run_result = list(nodenames)

  def Exec(self, feedback_fn):
    """Create and add the instance to the cluster.

    """
    instance = self.op.instance_name
    pnode_name = self.pnode.name

    ht_kind = self.op.hypervisor
    if ht_kind in constants.HTS_REQ_PORT:
      network_port = self.cfg.AllocatePort()
    else:
      network_port = None

    if constants.ENABLE_FILE_STORAGE:
      # this is needed because os.path.join does not accept None arguments
      if self.op.file_storage_dir is None:
        string_file_storage_dir = ""
      else:
        string_file_storage_dir = self.op.file_storage_dir

      # build the full file storage dir path
      file_storage_dir = utils.PathJoin(self.cfg.GetFileStorageDir(),
                                        string_file_storage_dir, instance)
    else:
      file_storage_dir = ""

    disks = _GenerateDiskTemplate(self,
                                  self.op.disk_template,
                                  instance, pnode_name,
                                  self.secondaries,
                                  self.disks,
                                  file_storage_dir,
                                  self.op.file_driver,
                                  0,
                                  feedback_fn)

    iobj = objects.Instance(name=instance, os=self.op.os_type,
                            primary_node=pnode_name,
                            nics=self.nics, disks=disks,
                            disk_template=self.op.disk_template,
                            admin_up=False,
                            network_port=network_port,
                            beparams=self.op.beparams,
                            hvparams=self.op.hvparams,
                            hypervisor=self.op.hypervisor,
                            osparams=self.op.osparams,
                            )

    if self.adopt_disks:
      # rename LVs to the newly-generated names; we need to construct
      # 'fake' LV disks with the old data, plus the new unique_id
      tmp_disks = [objects.Disk.FromDict(v.ToDict()) for v in disks]
      rename_to = []
      for t_dsk, a_dsk in zip (tmp_disks, self.disks):
        rename_to.append(t_dsk.logical_id)
        t_dsk.logical_id = (t_dsk.logical_id[0], a_dsk["adopt"])
        self.cfg.SetDiskID(t_dsk, pnode_name)
      result = self.rpc.call_blockdev_rename(pnode_name,
                                             zip(tmp_disks, rename_to))
      result.Raise("Failed to rename adoped LVs")
    else:
      feedback_fn("* creating instance disks...")
      try:
        _CreateDisks(self, iobj)
      except errors.OpExecError:
        self.LogWarning("Device creation failed, reverting...")
        try:
          _RemoveDisks(self, iobj)
        finally:
          self.cfg.ReleaseDRBDMinors(instance)
          raise

      if self.cfg.GetClusterInfo().prealloc_wipe_disks:
        feedback_fn("* wiping instance disks...")
        try:
          _WipeDisks(self, iobj)
        except errors.OpExecError:
          self.LogWarning("Device wiping failed, reverting...")
          try:
            _RemoveDisks(self, iobj)
          finally:
            self.cfg.ReleaseDRBDMinors(instance)
            raise

    feedback_fn("adding instance %s to cluster config" % instance)

    self.cfg.AddInstance(iobj, self.proc.GetECId())

    # Declare that we don't want to remove the instance lock anymore, as we've
    # added the instance to the config
    del self.remove_locks[locking.LEVEL_INSTANCE]
    # Unlock all the nodes
    if self.op.mode == constants.INSTANCE_IMPORT:
      nodes_keep = [self.op.src_node]
      nodes_release = [node for node in self.acquired_locks[locking.LEVEL_NODE]
                       if node != self.op.src_node]
      self.context.glm.release(locking.LEVEL_NODE, nodes_release)
      self.acquired_locks[locking.LEVEL_NODE] = nodes_keep
    else:
      self.context.glm.release(locking.LEVEL_NODE)
      del self.acquired_locks[locking.LEVEL_NODE]

    if self.op.wait_for_sync:
      disk_abort = not _WaitForSync(self, iobj)
    elif iobj.disk_template in constants.DTS_NET_MIRROR:
      # make sure the disks are not degraded (still sync-ing is ok)
      time.sleep(15)
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

    if iobj.disk_template != constants.DT_DISKLESS and not self.adopt_disks:
      if self.op.mode == constants.INSTANCE_CREATE:
        if not self.op.no_install:
          feedback_fn("* running the instance OS create scripts...")
          # FIXME: pass debug option from opcode to backend
          result = self.rpc.call_instance_os_add(pnode_name, iobj, False,
                                                 self.op.debug_level)
          result.Raise("Could not add os for instance %s"
                       " on node %s" % (instance, pnode_name))

      elif self.op.mode == constants.INSTANCE_IMPORT:
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

      elif self.op.mode == constants.INSTANCE_REMOTE_IMPORT:
        feedback_fn("* preparing remote import...")
        # The source cluster will stop the instance before attempting to make a
        # connection. In some cases stopping an instance can take a long time,
        # hence the shutdown timeout is added to the connection timeout.
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

        # Run rename script on newly imported instance
        assert iobj.name == instance
        feedback_fn("Running rename script for %s" % instance)
        result = self.rpc.call_instance_run_rename(pnode_name, iobj,
                                                   self.source_instance_name,
                                                   self.op.debug_level)
        if result.fail_msg:
          self.LogWarning("Failed to run rename script for %s on node"
                          " %s: %s" % (instance, pnode_name, result.fail_msg))

      else:
        # also checked in the prereq part
        raise errors.ProgrammerError("Unknown OS initialization mode '%s'"
                                     % self.op.mode)

    if self.op.start:
      iobj.admin_up = True
      self.cfg.Update(iobj, feedback_fn)
      logging.info("Starting instance %s on node %s", instance, pnode_name)
      feedback_fn("* starting instance...")
      result = self.rpc.call_instance_start(pnode_name, iobj, None, None)
      result.Raise("Could not start instance")

    return list(iobj.all_nodes)


class LUInstanceConsole(NoHooksLU):
  """Connect to an instance's console.

  This is somewhat special in that it returns the command line that
  you need to run on the master node in order to connect to the
  console.

  """
  REQ_BGL = False

  def ExpandNames(self):
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
      if instance.admin_up:
        state = "ERROR_down"
      else:
        state = "ADMIN_down"
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
  hyper = hypervisor.GetHypervisor(instance.hypervisor)
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
    TLReplaceDisks.CheckArguments(self.op.mode, self.op.remote_node,
                                  self.op.iallocator)

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    if self.op.iallocator is not None:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

    elif self.op.remote_node is not None:
      remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)
      self.op.remote_node = remote_node

      # Warning: do not remove the locking of the new secondary here
      # unless DRBD8.AddChildren is changed to work in parallel;
      # currently it doesn't since parallel invocations of
      # FindUnusedMinor will conflict
      self.needed_locks[locking.LEVEL_NODE] = [remote_node]
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

    else:
      self.needed_locks[locking.LEVEL_NODE] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

    self.replacer = TLReplaceDisks(self, self.op.instance_name, self.op.mode,
                                   self.op.iallocator, self.op.remote_node,
                                   self.op.disks, False, self.op.early_release)

    self.tasklets = [self.replacer]

  def DeclareLocks(self, level):
    # If we're not already locking all nodes in the set we have to declare the
    # instance's primary/secondary nodes.
    if (level == locking.LEVEL_NODE and
        self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET):
      self._LockInstancesNodes()

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
    nl = [
      self.cfg.GetMasterNode(),
      instance.primary_node,
      ]
    if self.op.remote_node is not None:
      nl.append(self.op.remote_node)
    return env, nl, nl


class TLReplaceDisks(Tasklet):
  """Replaces disks for an instance.

  Note: Locking is not within the scope of this class.

  """
  def __init__(self, lu, instance_name, mode, iallocator_name, remote_node,
               disks, delay_iallocator, early_release):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_name = instance_name
    self.mode = mode
    self.iallocator_name = iallocator_name
    self.remote_node = remote_node
    self.disks = disks
    self.delay_iallocator = delay_iallocator
    self.early_release = early_release

    # Runtime data
    self.instance = None
    self.new_node = None
    self.target_node = None
    self.other_node = None
    self.remote_node_info = None
    self.node_secondary_ip = None

  @staticmethod
  def CheckArguments(mode, remote_node, iallocator):
    """Helper function for users of this class.

    """
    # check for valid parameter combination
    if mode == constants.REPLACE_DISK_CHG:
      if remote_node is None and iallocator is None:
        raise errors.OpPrereqError("When changing the secondary either an"
                                   " iallocator script must be used or the"
                                   " new node given", errors.ECODE_INVAL)

      if remote_node is not None and iallocator is not None:
        raise errors.OpPrereqError("Give either the iallocator or the new"
                                   " secondary, not both", errors.ECODE_INVAL)

    elif remote_node is not None or iallocator is not None:
      # Not replacing the secondary
      raise errors.OpPrereqError("The iallocator and new node options can"
                                 " only be used when changing the"
                                 " secondary node", errors.ECODE_INVAL)

  @staticmethod
  def _RunAllocator(lu, iallocator_name, instance_name, relocate_from):
    """Compute a new secondary node using an IAllocator.

    """
    ial = IAllocator(lu.cfg, lu.rpc,
                     mode=constants.IALLOCATOR_MODE_RELOC,
                     name=instance_name,
                     relocate_from=relocate_from)

    ial.Run(iallocator_name)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using iallocator '%s':"
                                 " %s" % (iallocator_name, ial.info),
                                 errors.ECODE_NORES)

    if len(ial.result) != ial.required_nodes:
      raise errors.OpPrereqError("iallocator '%s' returned invalid number"
                                 " of nodes (%s), required %s" %
                                 (iallocator_name,
                                  len(ial.result), ial.required_nodes),
                                 errors.ECODE_FAULT)

    remote_node_name = ial.result[0]

    lu.LogInfo("Selected new secondary for instance '%s': %s",
               instance_name, remote_node_name)

    return remote_node_name

  def _FindFaultyDisks(self, node_name):
    return _FindFaultyInstanceDisks(self.cfg, self.rpc, self.instance,
                                    node_name, True)

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

    if not self.delay_iallocator:
      self._CheckPrereq2()

  def _CheckPrereq2(self):
    """Check prerequisites, second part.

    This function should always be part of CheckPrereq. It was separated and is
    now called from Exec because during node evacuation iallocator was only
    called with an unmodified cluster model, not taking planned changes into
    account.

    """
    instance = self.instance
    secondary_node = instance.secondary_nodes[0]

    if self.iallocator_name is None:
      remote_node = self.remote_node
    else:
      remote_node = self._RunAllocator(self.lu, self.iallocator_name,
                                       instance.name, instance.secondary_nodes)

    if remote_node is not None:
      self.remote_node_info = self.cfg.GetNodeInfo(remote_node)
      assert self.remote_node_info is not None, \
        "Cannot retrieve locked node %s" % remote_node
    else:
      self.remote_node_info = None

    if remote_node == self.instance.primary_node:
      raise errors.OpPrereqError("The specified node is the primary node of"
                                 " the instance.", errors.ECODE_INVAL)

    if remote_node == secondary_node:
      raise errors.OpPrereqError("The specified node is already the"
                                 " secondary node of the instance.",
                                 errors.ECODE_INVAL)

    if self.disks and self.mode in (constants.REPLACE_DISK_AUTO,
                                    constants.REPLACE_DISK_CHG):
      raise errors.OpPrereqError("Cannot specify disks to be replaced",
                                 errors.ECODE_INVAL)

    if self.mode == constants.REPLACE_DISK_AUTO:
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

    for node in check_nodes:
      _CheckNodeOnline(self.lu, node)

    # Check whether disks are valid
    for disk_idx in self.disks:
      instance.FindDisk(disk_idx)

    # Get secondary node IP addresses
    node_2nd_ip = {}

    for node_name in [self.target_node, self.other_node, self.new_node]:
      if node_name is not None:
        node_2nd_ip[node_name] = self.cfg.GetNodeInfo(node_name).secondary_ip

    self.node_secondary_ip = node_2nd_ip

  def Exec(self, feedback_fn):
    """Execute disk replacement.

    This dispatches the disk replacement to the appropriate handler.

    """
    if self.delay_iallocator:
      self._CheckPrereq2()

    if not self.disks:
      feedback_fn("No disks need replacement")
      return

    feedback_fn("Replacing disk(s) %s for %s" %
                (utils.CommaJoin(self.disks), self.instance.name))

    activate_disks = (not self.instance.admin_up)

    # Activate the instance disks if we're replacing them on a down instance
    if activate_disks:
      _StartInstanceDisks(self.lu, self.instance, True)

    try:
      # Should we replace the secondary node?
      if self.new_node is not None:
        fn = self._ExecDrbd8Secondary
      else:
        fn = self._ExecDrbd8DiskOnly

      return fn(feedback_fn)

    finally:
      # Deactivate the instance disks if we're replacing them on a
      # down instance
      if activate_disks:
        _SafeShutdownInstanceDisks(self.lu, self.instance)

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
        self.lu.LogInfo("Checking disk/%d on %s" % (idx, node))
        self.cfg.SetDiskID(dev, node)

        result = self.rpc.call_blockdev_find(node, dev)

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

      if not _CheckDiskConsistency(self.lu, dev, node_name, on_primary,
                                   ldisk=ldisk):
        raise errors.OpExecError("Node %s has degraded storage, unsafe to"
                                 " replace disks for instance %s" %
                                 (node_name, self.instance.name))

  def _CreateNewStorage(self, node_name):
    vgname = self.cfg.GetVGName()
    iv_names = {}

    for idx, dev in enumerate(self.instance.disks):
      if idx not in self.disks:
        continue

      self.lu.LogInfo("Adding storage on %s for disk/%d" % (node_name, idx))

      self.cfg.SetDiskID(dev, node_name)

      lv_names = [".disk%d_%s" % (idx, suffix) for suffix in ["data", "meta"]]
      names = _GenerateUniqueNames(self.lu, lv_names)

      lv_data = objects.Disk(dev_type=constants.LD_LV, size=dev.size,
                             logical_id=(vgname, names[0]))
      lv_meta = objects.Disk(dev_type=constants.LD_LV, size=128,
                             logical_id=(vgname, names[1]))

      new_lvs = [lv_data, lv_meta]
      old_lvs = dev.children
      iv_names[dev.iv_name] = (dev, old_lvs, new_lvs)

      # we pass force_create=True to force the LVM creation
      for new_lv in new_lvs:
        _CreateBlockDev(self.lu, node_name, self.instance, new_lv, True,
                        _GetInstanceInfoText(self.instance), False)

    return iv_names

  def _CheckDevices(self, node_name, iv_names):
    for name, (dev, _, _) in iv_names.iteritems():
      self.cfg.SetDiskID(dev, node_name)

      result = self.rpc.call_blockdev_find(node_name, dev)

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
      self.lu.LogInfo("Remove logical volumes for %s" % name)

      for lv in old_lvs:
        self.cfg.SetDiskID(lv, node_name)

        msg = self.rpc.call_blockdev_remove(node_name, lv).fail_msg
        if msg:
          self.lu.LogWarning("Can't remove old LV: %s" % msg,
                             hint="remove unused LVs manually")

  def _ReleaseNodeLock(self, node_name):
    """Releases the lock for a given node."""
    self.lu.context.glm.release(locking.LEVEL_NODE, node_name)

  def _ExecDrbd8DiskOnly(self, feedback_fn):
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
      self.lu.LogInfo("Detaching %s drbd from local storage" % dev.iv_name)

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

      for old, new in zip(old_lvs, new_lvs):
        new.logical_id = old.logical_id
        self.cfg.SetDiskID(new, self.target_node)

      for disk in old_lvs:
        disk.logical_id = ren_fn(disk, temp_suffix)
        self.cfg.SetDiskID(disk, self.target_node)

      # Now that the new lvs have the old name, we can add them to the device
      self.lu.LogInfo("Adding new mirror component on %s" % self.target_node)
      result = self.rpc.call_blockdev_addchildren(self.target_node, dev,
                                                  new_lvs)
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

      dev.children = new_lvs

      self.cfg.Update(self.instance, feedback_fn)

    cstep = 5
    if self.early_release:
      self.lu.LogStep(cstep, steps_total, "Removing old storage")
      cstep += 1
      self._RemoveOldStorage(self.target_node, iv_names)
      # WARNING: we release both node locks here, do not do other RPCs
      # than WaitForSync to the primary node
      self._ReleaseNodeLock([self.target_node, self.other_node])

    # Wait for sync
    # This can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its return value
    self.lu.LogStep(cstep, steps_total, "Sync devices")
    cstep += 1
    _WaitForSync(self.lu, self.instance)

    # Check all devices manually
    self._CheckDevices(self.instance.primary_node, iv_names)

    # Step: remove old storage
    if not self.early_release:
      self.lu.LogStep(cstep, steps_total, "Removing old storage")
      cstep += 1
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

    # Step: check device activation
    self.lu.LogStep(1, steps_total, "Check device existence")
    self._CheckDisksExistence([self.instance.primary_node])
    self._CheckVolumeGroup([self.instance.primary_node])

    # Step: check other node consistency
    self.lu.LogStep(2, steps_total, "Check peer consistency")
    self._CheckDisksConsistency(self.instance.primary_node, True, True)

    # Step: create new storage
    self.lu.LogStep(3, steps_total, "Allocate new storage")
    for idx, dev in enumerate(self.instance.disks):
      self.lu.LogInfo("Adding new local storage on %s for disk/%d" %
                      (self.new_node, idx))
      # we pass force_create=True to force LVM creation
      for new_lv in dev.children:
        _CreateBlockDev(self.lu, self.new_node, self.instance, new_lv, True,
                        _GetInstanceInfoText(self.instance), False)

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
                              size=dev.size)
      try:
        _CreateSingleBlockDev(self.lu, self.new_node, self.instance, new_drbd,
                              _GetInstanceInfoText(self.instance), False)
      except errors.GenericError:
        self.cfg.ReleaseDRBDMinors(self.instance.name)
        raise

    # We have new devices, shutdown the drbd on the old secondary
    for idx, dev in enumerate(self.instance.disks):
      self.lu.LogInfo("Shutting down drbd for disk/%d on old node" % idx)
      self.cfg.SetDiskID(dev, self.target_node)
      msg = self.rpc.call_blockdev_shutdown(self.target_node, dev).fail_msg
      if msg:
        self.lu.LogWarning("Failed to shutdown drbd for disk/%d on old"
                           "node: %s" % (idx, msg),
                           hint=("Please cleanup this device manually as"
                                 " soon as possible"))

    self.lu.LogInfo("Detaching primary drbds from the network (=> standalone)")
    result = self.rpc.call_drbd_disconnect_net([self.instance.primary_node],
                                               self.node_secondary_ip,
                                               self.instance.disks)\
                                              [self.instance.primary_node]

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

    # and now perform the drbd attach
    self.lu.LogInfo("Attaching primary drbds to new secondary"
                    " (standalone => connected)")
    result = self.rpc.call_drbd_attach_net([self.instance.primary_node,
                                            self.new_node],
                                           self.node_secondary_ip,
                                           self.instance.disks,
                                           self.instance.name,
                                           False)
    for to_node, to_result in result.items():
      msg = to_result.fail_msg
      if msg:
        self.lu.LogWarning("Can't attach drbd disks on node %s: %s",
                           to_node, msg,
                           hint=("please do a gnt-instance info to see the"
                                 " status of disks"))
    cstep = 5
    if self.early_release:
      self.lu.LogStep(cstep, steps_total, "Removing old storage")
      cstep += 1
      self._RemoveOldStorage(self.target_node, iv_names)
      # WARNING: we release all node locks here, do not do other RPCs
      # than WaitForSync to the primary node
      self._ReleaseNodeLock([self.instance.primary_node,
                             self.target_node,
                             self.new_node])

    # Wait for sync
    # This can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its return value
    self.lu.LogStep(cstep, steps_total, "Sync devices")
    cstep += 1
    _WaitForSync(self.lu, self.instance)

    # Check all devices manually
    self._CheckDevices(self.instance.primary_node, iv_names)

    # Step: remove old storage
    if not self.early_release:
      self.lu.LogStep(cstep, steps_total, "Removing old storage")
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
        self.proc.LogWarning(str(err.args[0]))
      else:
        raise

  def CheckPrereq(self):
    """Check prerequisites.

    """
    # Check whether any instance on this node has faulty disks
    for inst in _GetNodeInstances(self.cfg, self.op.node_name):
      if not inst.admin_up:
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


class LUNodeEvacStrategy(NoHooksLU):
  """Computes the node evacuation strategy.

  """
  REQ_BGL = False

  def CheckArguments(self):
    _CheckIAllocatorOrNode(self, "iallocator", "remote_node")

  def ExpandNames(self):
    self.op.nodes = _GetWantedNodes(self, self.op.nodes)
    self.needed_locks = locks = {}
    if self.op.remote_node is None:
      locks[locking.LEVEL_NODE] = locking.ALL_SET
    else:
      self.op.remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)
      locks[locking.LEVEL_NODE] = self.op.nodes + [self.op.remote_node]

  def Exec(self, feedback_fn):
    if self.op.remote_node is not None:
      instances = []
      for node in self.op.nodes:
        instances.extend(_GetNodeSecondaryInstances(self.cfg, node))
      result = []
      for i in instances:
        if i.primary_node == self.op.remote_node:
          raise errors.OpPrereqError("Node %s is the primary node of"
                                     " instance %s, cannot use it as"
                                     " secondary" %
                                     (self.op.remote_node, i.name),
                                     errors.ECODE_INVAL)
        result.append([i.name, self.op.remote_node])
    else:
      ial = IAllocator(self.cfg, self.rpc,
                       mode=constants.IALLOCATOR_MODE_MEVAC,
                       evac_nodes=self.op.nodes)
      ial.Run(self.op.iallocator, validate=True)
      if not ial.success:
        raise errors.OpExecError("No valid evacuation solution: %s" % ial.info,
                                 errors.ECODE_NORES)
      result = ial.result
    return result


class LUInstanceGrowDisk(LogicalUnit):
  """Grow a disk of an instance.

  """
  HPATH = "disk-grow"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    env = {
      "DISK": self.op.disk,
      "AMOUNT": self.op.amount,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

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
                                 " growing.", errors.ECODE_INVAL)

    self.disk = instance.FindDisk(self.op.disk)

    if instance.disk_template != constants.DT_FILE:
      # TODO: check the free disk space for file, when that feature
      # will be supported
      _CheckNodesFreeDiskPerVG(self, nodenames,
                               self.disk.ComputeGrowth(self.op.amount))

  def Exec(self, feedback_fn):
    """Execute disk grow.

    """
    instance = self.instance
    disk = self.disk

    disks_ok, _ = _AssembleInstanceDisks(self, self.instance, disks=[disk])
    if not disks_ok:
      raise errors.OpExecError("Cannot activate block device to grow")

    for node in instance.all_nodes:
      self.cfg.SetDiskID(disk, node)
      result = self.rpc.call_blockdev_grow(node, disk, self.op.amount)
      result.Raise("Grow request failed to node %s" % node)

      # TODO: Rewrite code to work properly
      # DRBD goes into sync mode for a short amount of time after executing the
      # "resize" command. DRBD 8.x below version 8.0.13 contains a bug whereby
      # calling "resize" in sync mode fails. Sleeping for a short amount of
      # time is a work-around.
      time.sleep(5)

    disk.RecordGrow(self.op.amount)
    self.cfg.Update(instance, feedback_fn)
    if self.op.wait_for_sync:
      disk_abort = not _WaitForSync(self, instance, disks=[disk])
      if disk_abort:
        self.proc.LogWarning("Warning: disk sync-ing has not returned a good"
                             " status.\nPlease check the instance.")
      if not instance.admin_up:
        _SafeShutdownInstanceDisks(self, instance, disks=[disk])
    elif not instance.admin_up:
      self.proc.LogWarning("Not shutting down the disk even if the instance is"
                           " not supposed to be running because no wait for"
                           " sync mode was requested.")


class LUInstanceQueryData(NoHooksLU):
  """Query runtime instance data.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}
    self.share_locks = dict.fromkeys(locking.LEVELS, 1)

    if self.op.instances:
      self.wanted_names = []
      for name in self.op.instances:
        full_name = _ExpandInstanceName(self.cfg, name)
        self.wanted_names.append(full_name)
      self.needed_locks[locking.LEVEL_INSTANCE] = self.wanted_names
    else:
      self.wanted_names = None
      self.needed_locks[locking.LEVEL_INSTANCE] = locking.ALL_SET

    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    if self.wanted_names is None:
      self.wanted_names = self.acquired_locks[locking.LEVEL_INSTANCE]

    self.wanted_instances = [self.cfg.GetInstanceInfo(name) for name
                             in self.wanted_names]

  def _ComputeBlockdevStatus(self, node, instance_name, dev):
    """Returns the status of a block device

    """
    if self.op.static or not node:
      return None

    self.cfg.SetDiskID(dev, node)

    result = self.rpc.call_blockdev_find(node, dev)
    if result.offline:
      return None

    result.Raise("Can't compute disk status for %s" % instance_name)

    status = result.payload
    if status is None:
      return None

    return (status.dev_path, status.major, status.minor,
            status.sync_percent, status.estimated_time,
            status.is_degraded, status.ldisk_status)

  def _ComputeDiskStatus(self, instance, snode, dev):
    """Compute block device status.

    """
    if dev.dev_type in constants.LDS_DRBD:
      # we change the snode then (otherwise we use the one passed in)
      if dev.logical_id[0] == instance.primary_node:
        snode = dev.logical_id[1]
      else:
        snode = dev.logical_id[0]

    dev_pstatus = self._ComputeBlockdevStatus(instance.primary_node,
                                              instance.name, dev)
    dev_sstatus = self._ComputeBlockdevStatus(snode, instance.name, dev)

    if dev.children:
      dev_children = [self._ComputeDiskStatus(instance, snode, child)
                      for child in dev.children]
    else:
      dev_children = []

    data = {
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

    return data

  def Exec(self, feedback_fn):
    """Gather and return data"""
    result = {}

    cluster = self.cfg.GetClusterInfo()

    for instance in self.wanted_instances:
      if not self.op.static:
        remote_info = self.rpc.call_instance_info(instance.primary_node,
                                                  instance.name,
                                                  instance.hypervisor)
        remote_info.Raise("Error checking node %s" % instance.primary_node)
        remote_info = remote_info.payload
        if remote_info and "state" in remote_info:
          remote_state = "up"
        else:
          remote_state = "down"
      else:
        remote_state = None
      if instance.admin_up:
        config_state = "up"
      else:
        config_state = "down"

      disks = [self._ComputeDiskStatus(instance, None, device)
               for device in instance.disks]

      idict = {
        "name": instance.name,
        "config_state": config_state,
        "run_state": remote_state,
        "pnode": instance.primary_node,
        "snodes": instance.secondary_nodes,
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

      result[instance.name] = idict

    return result


class LUInstanceSetParams(LogicalUnit):
  """Modifies an instances's parameters.

  """
  HPATH = "instance-modify"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    if not (self.op.nics or self.op.disks or self.op.disk_template or
            self.op.hvparams or self.op.beparams or self.op.os_name):
      raise errors.OpPrereqError("No changes submitted", errors.ECODE_INVAL)

    if self.op.hvparams:
      _CheckGlobalHvParams(self.op.hvparams)

    # Disk validation
    disk_addremove = 0
    for disk_op, disk_dict in self.op.disks:
      utils.ForceDictType(disk_dict, constants.IDISK_PARAMS_TYPES)
      if disk_op == constants.DDM_REMOVE:
        disk_addremove += 1
        continue
      elif disk_op == constants.DDM_ADD:
        disk_addremove += 1
      else:
        if not isinstance(disk_op, int):
          raise errors.OpPrereqError("Invalid disk index", errors.ECODE_INVAL)
        if not isinstance(disk_dict, dict):
          msg = "Invalid disk value: expected dict, got '%s'" % disk_dict
          raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

      if disk_op == constants.DDM_ADD:
        mode = disk_dict.setdefault('mode', constants.DISK_RDWR)
        if mode not in constants.DISK_ACCESS_SET:
          raise errors.OpPrereqError("Invalid disk access mode '%s'" % mode,
                                     errors.ECODE_INVAL)
        size = disk_dict.get('size', None)
        if size is None:
          raise errors.OpPrereqError("Required disk parameter size missing",
                                     errors.ECODE_INVAL)
        try:
          size = int(size)
        except (TypeError, ValueError), err:
          raise errors.OpPrereqError("Invalid disk size parameter: %s" %
                                     str(err), errors.ECODE_INVAL)
        disk_dict['size'] = size
      else:
        # modification of disk
        if 'size' in disk_dict:
          raise errors.OpPrereqError("Disk size change not possible, use"
                                     " grow-disk", errors.ECODE_INVAL)

    if disk_addremove > 1:
      raise errors.OpPrereqError("Only one disk add or remove operation"
                                 " supported at a time", errors.ECODE_INVAL)

    if self.op.disks and self.op.disk_template is not None:
      raise errors.OpPrereqError("Disk template conversion and other disk"
                                 " changes not supported at the same time",
                                 errors.ECODE_INVAL)

    if (self.op.disk_template and
        self.op.disk_template in constants.DTS_NET_MIRROR and
        self.op.remote_node is None):
      raise errors.OpPrereqError("Changing the disk template to a mirrored"
                                 " one requires specifying a secondary node",
                                 errors.ECODE_INVAL)

    # NIC validation
    nic_addremove = 0
    for nic_op, nic_dict in self.op.nics:
      utils.ForceDictType(nic_dict, constants.INIC_PARAMS_TYPES)
      if nic_op == constants.DDM_REMOVE:
        nic_addremove += 1
        continue
      elif nic_op == constants.DDM_ADD:
        nic_addremove += 1
      else:
        if not isinstance(nic_op, int):
          raise errors.OpPrereqError("Invalid nic index", errors.ECODE_INVAL)
        if not isinstance(nic_dict, dict):
          msg = "Invalid nic value: expected dict, got '%s'" % nic_dict
          raise errors.OpPrereqError(msg, errors.ECODE_INVAL)

      # nic_dict should be a dict
      nic_ip = nic_dict.get('ip', None)
      if nic_ip is not None:
        if nic_ip.lower() == constants.VALUE_NONE:
          nic_dict['ip'] = None
        else:
          if not netutils.IPAddress.IsValid(nic_ip):
            raise errors.OpPrereqError("Invalid IP address '%s'" % nic_ip,
                                       errors.ECODE_INVAL)

      nic_bridge = nic_dict.get('bridge', None)
      nic_link = nic_dict.get('link', None)
      if nic_bridge and nic_link:
        raise errors.OpPrereqError("Cannot pass 'bridge' and 'link'"
                                   " at the same time", errors.ECODE_INVAL)
      elif nic_bridge and nic_bridge.lower() == constants.VALUE_NONE:
        nic_dict['bridge'] = None
      elif nic_link and nic_link.lower() == constants.VALUE_NONE:
        nic_dict['link'] = None

      if nic_op == constants.DDM_ADD:
        nic_mac = nic_dict.get('mac', None)
        if nic_mac is None:
          nic_dict['mac'] = constants.VALUE_AUTO

      if 'mac' in nic_dict:
        nic_mac = nic_dict['mac']
        if nic_mac not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
          nic_mac = utils.NormalizeAndValidateMac(nic_mac)

        if nic_op != constants.DDM_ADD and nic_mac == constants.VALUE_AUTO:
          raise errors.OpPrereqError("'auto' is not a valid MAC address when"
                                     " modifying an existing nic",
                                     errors.ECODE_INVAL)

    if nic_addremove > 1:
      raise errors.OpPrereqError("Only one NIC add or remove operation"
                                 " supported at a time", errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
      if self.op.disk_template and self.op.remote_node:
        self.op.remote_node = _ExpandNodeName(self.cfg, self.op.remote_node)
        self.needed_locks[locking.LEVEL_NODE].append(self.op.remote_node)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, primary and secondaries.

    """
    args = dict()
    if constants.BE_MEMORY in self.be_new:
      args['memory'] = self.be_new[constants.BE_MEMORY]
    if constants.BE_VCPUS in self.be_new:
      args['vcpus'] = self.be_new[constants.BE_VCPUS]
    # TODO: export disk changes. Note: _BuildInstanceHookEnv* don't export disk
    # information at all.
    if self.op.nics:
      args['nics'] = []
      nic_override = dict(self.op.nics)
      for idx, nic in enumerate(self.instance.nics):
        if idx in nic_override:
          this_nic_override = nic_override[idx]
        else:
          this_nic_override = {}
        if 'ip' in this_nic_override:
          ip = this_nic_override['ip']
        else:
          ip = nic.ip
        if 'mac' in this_nic_override:
          mac = this_nic_override['mac']
        else:
          mac = nic.mac
        if idx in self.nic_pnew:
          nicparams = self.nic_pnew[idx]
        else:
          nicparams = self.cluster.SimpleFillNIC(nic.nicparams)
        mode = nicparams[constants.NIC_MODE]
        link = nicparams[constants.NIC_LINK]
        args['nics'].append((ip, mac, mode, link))
      if constants.DDM_ADD in nic_override:
        ip = nic_override[constants.DDM_ADD].get('ip', None)
        mac = nic_override[constants.DDM_ADD]['mac']
        nicparams = self.nic_pnew[constants.DDM_ADD]
        mode = nicparams[constants.NIC_MODE]
        link = nicparams[constants.NIC_LINK]
        args['nics'].append((ip, mac, mode, link))
      elif constants.DDM_REMOVE in nic_override:
        del args['nics'][-1]

    env = _BuildInstanceHookEnvByObject(self, self.instance, override=args)
    if self.op.disk_template:
      env["NEW_DISK_TEMPLATE"] = self.op.disk_template
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    # checking the new params on the primary/secondary nodes

    instance = self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    cluster = self.cluster = self.cfg.GetClusterInfo()
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    pnode = instance.primary_node
    nodelist = list(instance.all_nodes)

    # OS change
    if self.op.os_name and not self.op.force:
      _CheckNodeHasOS(self, instance.primary_node, self.op.os_name,
                      self.op.force_variant)
      instance_os = self.op.os_name
    else:
      instance_os = instance.os

    if self.op.disk_template:
      if instance.disk_template == self.op.disk_template:
        raise errors.OpPrereqError("Instance already has disk template %s" %
                                   instance.disk_template, errors.ECODE_INVAL)

      if (instance.disk_template,
          self.op.disk_template) not in self._DISK_CONVERSIONS:
        raise errors.OpPrereqError("Unsupported disk template conversion from"
                                   " %s to %s" % (instance.disk_template,
                                                  self.op.disk_template),
                                   errors.ECODE_INVAL)
      _CheckInstanceDown(self, instance, "cannot change disk template")
      if self.op.disk_template in constants.DTS_NET_MIRROR:
        if self.op.remote_node == pnode:
          raise errors.OpPrereqError("Given new secondary node %s is the same"
                                     " as the primary node of the instance" %
                                     self.op.remote_node, errors.ECODE_STATE)
        _CheckNodeOnline(self, self.op.remote_node)
        _CheckNodeNotDrained(self, self.op.remote_node)
        # FIXME: here we assume that the old instance type is DT_PLAIN
        assert instance.disk_template == constants.DT_PLAIN
        disks = [{"size": d.size, "vg": d.logical_id[0]}
                 for d in instance.disks]
        required = _ComputeDiskSizePerVG(self.op.disk_template, disks)
        _CheckNodesFreeDiskPerVG(self, [self.op.remote_node], required)

    # hvparams processing
    if self.op.hvparams:
      hv_type = instance.hypervisor
      i_hvdict = _GetUpdatedParams(instance.hvparams, self.op.hvparams)
      utils.ForceDictType(i_hvdict, constants.HVS_PARAMETER_TYPES)
      hv_new = cluster.SimpleFillHV(hv_type, instance.os, i_hvdict)

      # local check
      hypervisor.GetHypervisor(hv_type).CheckParameterSyntax(hv_new)
      _CheckHVParams(self, nodelist, instance.hypervisor, hv_new)
      self.hv_new = hv_new # the new actual values
      self.hv_inst = i_hvdict # the new dict (without defaults)
    else:
      self.hv_new = self.hv_inst = {}

    # beparams processing
    if self.op.beparams:
      i_bedict = _GetUpdatedParams(instance.beparams, self.op.beparams,
                                   use_none=True)
      utils.ForceDictType(i_bedict, constants.BES_PARAMETER_TYPES)
      be_new = cluster.SimpleFillBE(i_bedict)
      self.be_new = be_new # the new actual values
      self.be_inst = i_bedict # the new dict (without defaults)
    else:
      self.be_new = self.be_inst = {}

    # osparams processing
    if self.op.osparams:
      i_osdict = _GetUpdatedParams(instance.osparams, self.op.osparams)
      _CheckOSParams(self, True, nodelist, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = {}

    self.warn = []

    if constants.BE_MEMORY in self.op.beparams and not self.op.force:
      mem_check_list = [pnode]
      if be_new[constants.BE_AUTO_BALANCE]:
        # either we changed auto_balance to yes or it was from before
        mem_check_list.extend(instance.secondary_nodes)
      instance_info = self.rpc.call_instance_info(pnode, instance.name,
                                                  instance.hypervisor)
      nodeinfo = self.rpc.call_node_info(mem_check_list, None,
                                         instance.hypervisor)
      pninfo = nodeinfo[pnode]
      msg = pninfo.fail_msg
      if msg:
        # Assume the primary node is unreachable and go ahead
        self.warn.append("Can't get info from primary node %s: %s" %
                         (pnode,  msg))
      elif not isinstance(pninfo.payload.get('memory_free', None), int):
        self.warn.append("Node data from primary node %s doesn't contain"
                         " free memory information" % pnode)
      elif instance_info.fail_msg:
        self.warn.append("Can't get instance runtime information: %s" %
                        instance_info.fail_msg)
      else:
        if instance_info.payload:
          current_mem = int(instance_info.payload['memory'])
        else:
          # Assume instance not running
          # (there is a slight race condition here, but it's not very probable,
          # and we have no other way to check)
          current_mem = 0
        miss_mem = (be_new[constants.BE_MEMORY] - current_mem -
                    pninfo.payload['memory_free'])
        if miss_mem > 0:
          raise errors.OpPrereqError("This change will prevent the instance"
                                     " from starting, due to %d MB of memory"
                                     " missing on its primary node" % miss_mem,
                                     errors.ECODE_NORES)

      if be_new[constants.BE_AUTO_BALANCE]:
        for node, nres in nodeinfo.items():
          if node not in instance.secondary_nodes:
            continue
          msg = nres.fail_msg
          if msg:
            self.warn.append("Can't get info from secondary node %s: %s" %
                             (node, msg))
          elif not isinstance(nres.payload.get('memory_free', None), int):
            self.warn.append("Secondary node %s didn't return free"
                             " memory information" % node)
          elif be_new[constants.BE_MEMORY] > nres.payload['memory_free']:
            self.warn.append("Not enough memory to failover instance to"
                             " secondary node %s" % node)

    # NIC processing
    self.nic_pnew = {}
    self.nic_pinst = {}
    for nic_op, nic_dict in self.op.nics:
      if nic_op == constants.DDM_REMOVE:
        if not instance.nics:
          raise errors.OpPrereqError("Instance has no NICs, cannot remove",
                                     errors.ECODE_INVAL)
        continue
      if nic_op != constants.DDM_ADD:
        # an existing nic
        if not instance.nics:
          raise errors.OpPrereqError("Invalid NIC index %s, instance has"
                                     " no NICs" % nic_op,
                                     errors.ECODE_INVAL)
        if nic_op < 0 or nic_op >= len(instance.nics):
          raise errors.OpPrereqError("Invalid NIC index %s, valid values"
                                     " are 0 to %d" %
                                     (nic_op, len(instance.nics) - 1),
                                     errors.ECODE_INVAL)
        old_nic_params = instance.nics[nic_op].nicparams
        old_nic_ip = instance.nics[nic_op].ip
      else:
        old_nic_params = {}
        old_nic_ip = None

      update_params_dict = dict([(key, nic_dict[key])
                                 for key in constants.NICS_PARAMETERS
                                 if key in nic_dict])

      if 'bridge' in nic_dict:
        update_params_dict[constants.NIC_LINK] = nic_dict['bridge']

      new_nic_params = _GetUpdatedParams(old_nic_params,
                                         update_params_dict)
      utils.ForceDictType(new_nic_params, constants.NICS_PARAMETER_TYPES)
      new_filled_nic_params = cluster.SimpleFillNIC(new_nic_params)
      objects.NIC.CheckParameterSyntax(new_filled_nic_params)
      self.nic_pinst[nic_op] = new_nic_params
      self.nic_pnew[nic_op] = new_filled_nic_params
      new_nic_mode = new_filled_nic_params[constants.NIC_MODE]

      if new_nic_mode == constants.NIC_MODE_BRIDGED:
        nic_bridge = new_filled_nic_params[constants.NIC_LINK]
        msg = self.rpc.call_bridges_exist(pnode, [nic_bridge]).fail_msg
        if msg:
          msg = "Error checking bridges on node %s: %s" % (pnode, msg)
          if self.op.force:
            self.warn.append(msg)
          else:
            raise errors.OpPrereqError(msg, errors.ECODE_ENVIRON)
      if new_nic_mode == constants.NIC_MODE_ROUTED:
        if 'ip' in nic_dict:
          nic_ip = nic_dict['ip']
        else:
          nic_ip = old_nic_ip
        if nic_ip is None:
          raise errors.OpPrereqError('Cannot set the nic ip to None'
                                     ' on a routed nic', errors.ECODE_INVAL)
      if 'mac' in nic_dict:
        nic_mac = nic_dict['mac']
        if nic_mac is None:
          raise errors.OpPrereqError('Cannot set the nic mac to None',
                                     errors.ECODE_INVAL)
        elif nic_mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
          # otherwise generate the mac
          nic_dict['mac'] = self.cfg.GenerateMAC(self.proc.GetECId())
        else:
          # or validate/reserve the current one
          try:
            self.cfg.ReserveMAC(nic_mac, self.proc.GetECId())
          except errors.ReservationError:
            raise errors.OpPrereqError("MAC address %s already in use"
                                       " in cluster" % nic_mac,
                                       errors.ECODE_NOTUNIQUE)

    # DISK processing
    if self.op.disks and instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Disk operations not supported for"
                                 " diskless instances",
                                 errors.ECODE_INVAL)
    for disk_op, _ in self.op.disks:
      if disk_op == constants.DDM_REMOVE:
        if len(instance.disks) == 1:
          raise errors.OpPrereqError("Cannot remove the last disk of"
                                     " an instance", errors.ECODE_INVAL)
        _CheckInstanceDown(self, instance, "cannot remove disks")

      if (disk_op == constants.DDM_ADD and
          len(instance.disks) >= constants.MAX_DISKS):
        raise errors.OpPrereqError("Instance has too many disks (%d), cannot"
                                   " add more" % constants.MAX_DISKS,
                                   errors.ECODE_STATE)
      if disk_op not in (constants.DDM_ADD, constants.DDM_REMOVE):
        # an existing disk
        if disk_op < 0 or disk_op >= len(instance.disks):
          raise errors.OpPrereqError("Invalid disk index %s, valid values"
                                     " are 0 to %d" %
                                     (disk_op, len(instance.disks)),
                                     errors.ECODE_INVAL)

    return

  def _ConvertPlainToDrbd(self, feedback_fn):
    """Converts an instance from plain to drbd.

    """
    feedback_fn("Converting template to drbd")
    instance = self.instance
    pnode = instance.primary_node
    snode = self.op.remote_node

    # create a fake disk info for _GenerateDiskTemplate
    disk_info = [{"size": d.size, "mode": d.mode} for d in instance.disks]
    new_disks = _GenerateDiskTemplate(self, self.op.disk_template,
                                      instance.name, pnode, [snode],
                                      disk_info, None, None, 0, feedback_fn)
    info = _GetInstanceInfoText(instance)
    feedback_fn("Creating aditional volumes...")
    # first, create the missing data and meta devices
    for disk in new_disks:
      # unfortunately this is... not too nice
      _CreateSingleBlockDev(self, pnode, instance, disk.children[1],
                            info, True)
      for child in disk.children:
        _CreateSingleBlockDev(self, snode, instance, child, info, True)
    # at this stage, all new LVs have been created, we can rename the
    # old ones
    feedback_fn("Renaming original volumes...")
    rename_list = [(o, n.children[0].logical_id)
                   for (o, n) in zip(instance.disks, new_disks)]
    result = self.rpc.call_blockdev_rename(pnode, rename_list)
    result.Raise("Failed to rename original LVs")

    feedback_fn("Initializing DRBD devices...")
    # all child devices are in place, we can now create the DRBD devices
    for disk in new_disks:
      for node in [pnode, snode]:
        f_create = node == pnode
        _CreateSingleBlockDev(self, node, instance, disk, info, f_create)

    # at this point, the instance has been modified
    instance.disk_template = constants.DT_DRBD8
    instance.disks = new_disks
    self.cfg.Update(instance, feedback_fn)

    # disks are created, waiting for sync
    disk_abort = not _WaitForSync(self, instance)
    if disk_abort:
      raise errors.OpExecError("There are some degraded disks for"
                               " this instance, please cleanup manually")

  def _ConvertDrbdToPlain(self, feedback_fn):
    """Converts an instance from drbd to plain.

    """
    instance = self.instance
    assert len(instance.secondary_nodes) == 1
    pnode = instance.primary_node
    snode = instance.secondary_nodes[0]
    feedback_fn("Converting template to plain")

    old_disks = instance.disks
    new_disks = [d.children[0] for d in old_disks]

    # copy over size and mode
    for parent, child in zip(old_disks, new_disks):
      child.size = parent.size
      child.mode = parent.mode

    # update instance structure
    instance.disks = new_disks
    instance.disk_template = constants.DT_PLAIN
    self.cfg.Update(instance, feedback_fn)

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

  def Exec(self, feedback_fn):
    """Modifies an instance.

    All parameters take effect only at the next restart of the instance.

    """
    # Process here the warnings from CheckPrereq, as we don't have a
    # feedback_fn there.
    for warn in self.warn:
      feedback_fn("WARNING: %s" % warn)

    result = []
    instance = self.instance
    # disk changes
    for disk_op, disk_dict in self.op.disks:
      if disk_op == constants.DDM_REMOVE:
        # remove the last disk
        device = instance.disks.pop()
        device_idx = len(instance.disks)
        for node, disk in device.ComputeNodeTree(instance.primary_node):
          self.cfg.SetDiskID(disk, node)
          msg = self.rpc.call_blockdev_remove(node, disk).fail_msg
          if msg:
            self.LogWarning("Could not remove disk/%d on node %s: %s,"
                            " continuing anyway", device_idx, node, msg)
        result.append(("disk/%d" % device_idx, "remove"))
      elif disk_op == constants.DDM_ADD:
        # add a new disk
        if instance.disk_template == constants.DT_FILE:
          file_driver, file_path = instance.disks[0].logical_id
          file_path = os.path.dirname(file_path)
        else:
          file_driver = file_path = None
        disk_idx_base = len(instance.disks)
        new_disk = _GenerateDiskTemplate(self,
                                         instance.disk_template,
                                         instance.name, instance.primary_node,
                                         instance.secondary_nodes,
                                         [disk_dict],
                                         file_path,
                                         file_driver,
                                         disk_idx_base, feedback_fn)[0]
        instance.disks.append(new_disk)
        info = _GetInstanceInfoText(instance)

        logging.info("Creating volume %s for instance %s",
                     new_disk.iv_name, instance.name)
        # Note: this needs to be kept in sync with _CreateDisks
        #HARDCODE
        for node in instance.all_nodes:
          f_create = node == instance.primary_node
          try:
            _CreateBlockDev(self, node, instance, new_disk,
                            f_create, info, f_create)
          except errors.OpExecError, err:
            self.LogWarning("Failed to create volume %s (%s) on"
                            " node %s: %s",
                            new_disk.iv_name, new_disk, node, err)
        result.append(("disk/%d" % disk_idx_base, "add:size=%s,mode=%s" %
                       (new_disk.size, new_disk.mode)))
      else:
        # change a given disk
        instance.disks[disk_op].mode = disk_dict['mode']
        result.append(("disk.mode/%d" % disk_op, disk_dict['mode']))

    if self.op.disk_template:
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

    # NIC changes
    for nic_op, nic_dict in self.op.nics:
      if nic_op == constants.DDM_REMOVE:
        # remove the last nic
        del instance.nics[-1]
        result.append(("nic.%d" % len(instance.nics), "remove"))
      elif nic_op == constants.DDM_ADD:
        # mac and bridge should be set, by now
        mac = nic_dict['mac']
        ip = nic_dict.get('ip', None)
        nicparams = self.nic_pinst[constants.DDM_ADD]
        new_nic = objects.NIC(mac=mac, ip=ip, nicparams=nicparams)
        instance.nics.append(new_nic)
        result.append(("nic.%d" % (len(instance.nics) - 1),
                       "add:mac=%s,ip=%s,mode=%s,link=%s" %
                       (new_nic.mac, new_nic.ip,
                        self.nic_pnew[constants.DDM_ADD][constants.NIC_MODE],
                        self.nic_pnew[constants.DDM_ADD][constants.NIC_LINK]
                       )))
      else:
        for key in 'mac', 'ip':
          if key in nic_dict:
            setattr(instance.nics[nic_op], key, nic_dict[key])
        if nic_op in self.nic_pinst:
          instance.nics[nic_op].nicparams = self.nic_pinst[nic_op]
        for key, val in nic_dict.iteritems():
          result.append(("nic.%s/%d" % (key, nic_op), val))

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

    self.cfg.Update(instance, feedback_fn)

    return result

  _DISK_CONVERSIONS = {
    (constants.DT_PLAIN, constants.DT_DRBD8): _ConvertPlainToDrbd,
    (constants.DT_DRBD8, constants.DT_PLAIN): _ConvertDrbdToPlain,
    }


class LUBackupQuery(NoHooksLU):
  """Query the exports list

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1
    if not self.op.nodes:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
    else:
      self.needed_locks[locking.LEVEL_NODE] = \
        _GetWantedNodes(self, self.op.nodes)

  def Exec(self, feedback_fn):
    """Compute the list of all the exported system images.

    @rtype: dict
    @return: a dictionary with the structure node->(export-list)
        where export-list is a list of the instances exported on
        that node.

    """
    self.nodes = self.acquired_locks[locking.LEVEL_NODE]
    rpcresult = self.rpc.call_export_list(self.nodes)
    result = {}
    for node in rpcresult:
      if rpcresult[node].fail_msg:
        result[node] = False
      else:
        result[node] = rpcresult[node].payload

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

    nl = [self.cfg.GetMasterNode(), self.instance.primary_node]

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      nl.append(self.op.target_node)

    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance and node names are valid.

    """
    instance_name = self.op.instance_name

    self.instance = self.cfg.GetInstanceInfo(instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

    if (self.op.remove_instance and self.instance.admin_up and
        not self.op.shutdown):
      raise errors.OpPrereqError("Can not remove instance without shutting it"
                                 " down before")

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
        raise errors.OpPrereqError("Invalid data for X509 key name: %s" % err)

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

    activate_disks = (not instance.admin_up)

    if activate_disks:
      # Activate the instance disks if we'exporting a stopped instance
      feedback_fn("Activating disks for %s" % instance.name)
      _StartInstanceDisks(self, instance, None)

    try:
      helper = masterd.instance.ExportInstanceHelper(self, feedback_fn,
                                                     instance)

      helper.CreateSnapshots()
      try:
        if (self.op.shutdown and instance.admin_up and
            not self.op.remove_instance):
          assert not activate_disks
          feedback_fn("Starting instance %s" % instance.name)
          result = self.rpc.call_instance_start(src_node, instance, None, None)
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
    self.needed_locks = {}
    # We need all nodes to be locked in order for RemoveExport to work, but we
    # don't need to lock the instance itself, as nothing will happen to it (and
    # we can remove exports also for a removed instance)
    self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

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

    locked_nodes = self.acquired_locks[locking.LEVEL_NODE]
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

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    env = {
      "GROUP_NAME": self.op.group_name,
      }
    mn = self.cfg.GetMasterNode()
    return env, [mn], [mn]

  def Exec(self, feedback_fn):
    """Add the node group to the cluster.

    """
    group_obj = objects.NodeGroup(name=self.op.group_name, members=[],
                                  uuid=self.group_uuid,
                                  alloc_policy=self.op.alloc_policy,
                                  ndparams=self.op.ndparams)

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
    # list of "source" groups, we need to fetch node information.
    self.node_data = self.cfg.GetAllNodesInfo()
    affected_groups = set(self.node_data[node].group for node in self.op.nodes)
    affected_groups.add(self.group_uuid)

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: list(affected_groups),
      locking.LEVEL_NODE: self.op.nodes,
      }

  def CheckPrereq(self):
    """Check prerequisites.

    """
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
                          " to be spit across groups: %s",
                          utils.CommaJoin(utils.NiceSort(previous_splits)))

  def Exec(self, feedback_fn):
    """Assign nodes to a new group.

    """
    for node in self.op.nodes:
      self.node_data[node].group = self.group_uuid

    self.cfg.Update(self.group, feedback_fn) # Saves all modified nodes.

  @staticmethod
  def CheckAssignmentForSplitInstances(changes, node_data, instance_data):
    """Check for split instances after a node assignment.

    This method considers a series of node assignments as an atomic operation,
    and returns information about split instances after applying the set of
    changes.

    In particular, it returns information about newly split instances, and
    instances that were already split, and remain so after the change.

    Only instances whose disk template is listed in constants.DTS_NET_MIRROR are
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
      if inst.disk_template not in constants.DTS_NET_MIRROR:
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
        raise errors.OpPrereqError("Some groups do not exist: %s" % missing,
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

    return query.GroupQueryData([self._all_groups[uuid]
                                 for uuid in self.wanted],
                                group_to_nodes, group_to_instances)


class LUGroupQuery(NoHooksLU):
  """Logical unit for querying node groups.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.gq = _GroupQuery(self.op.names, self.op.output_fields, False)

  def ExpandNames(self):
    self.gq.ExpandNames(self)

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
      self.op.alloc_policy,
      ]

    if all_changes.count(None) == len(all_changes):
      raise errors.OpPrereqError("Please pass at least one modification",
                                 errors.ECODE_INVAL)

  def ExpandNames(self):
    # This raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }

  def CheckPrereq(self):
    """Check prerequisites.

    """
    self.group = self.cfg.GetNodeGroup(self.group_uuid)

    if self.group is None:
      raise errors.OpExecError("Could not retrieve group '%s' (UUID: %s)" %
                               (self.op.group_name, self.group_uuid))

    if self.op.ndparams:
      new_ndparams = _GetUpdatedParams(self.group.ndparams, self.op.ndparams)
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)
      self.new_ndparams = new_ndparams

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    env = {
      "GROUP_NAME": self.op.group_name,
      "NEW_ALLOC_POLICY": self.op.alloc_policy,
      }
    mn = self.cfg.GetMasterNode()
    return env, [mn], [mn]

  def Exec(self, feedback_fn):
    """Modifies the node group.

    """
    result = []

    if self.op.ndparams:
      self.group.ndparams = self.new_ndparams
      result.append(("ndparams", str(self.group.ndparams)))

    if self.op.alloc_policy:
      self.group.alloc_policy = self.op.alloc_policy

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
      raise errors.OpPrereqError("Group '%s' is the only group,"
                                 " cannot be removed" %
                                 self.op.group_name,
                                 errors.ECODE_STATE)

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    env = {
      "GROUP_NAME": self.op.group_name,
      }
    mn = self.cfg.GetMasterNode()
    return env, [mn], [mn]

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
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.old_name)

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      }

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the given old_name exists as a node group, and that
    new_name doesn't.

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
    env = {
      "OLD_NAME": self.op.old_name,
      "NEW_NAME": self.op.new_name,
      }

    mn = self.cfg.GetMasterNode()
    all_nodes = self.cfg.GetAllNodesInfo()
    run_nodes = [mn]
    all_nodes.pop(mn, None)

    for node in all_nodes.values():
      if node.group == self.group_uuid:
        run_nodes.append(node.name)

    return env, run_nodes, run_nodes

  def Exec(self, feedback_fn):
    """Rename the node group.

    """
    group = self.cfg.GetNodeGroup(self.group_uuid)

    if group is None:
      raise errors.OpExecError("Could not retrieve group '%s' (UUID: %s)" %
                               (self.op.old_name, self.group_uuid))

    group.name = self.op.new_name
    self.cfg.Update(group, feedback_fn)

    return self.op.new_name


class TagsLU(NoHooksLU): # pylint: disable-msg=W0223
  """Generic tags LU.

  This is an abstract class which is the parent of all the other tags LUs.

  """

  def ExpandNames(self):
    self.needed_locks = {}
    if self.op.kind == constants.TAG_NODE:
      self.op.name = _ExpandNodeName(self.cfg, self.op.name)
      self.needed_locks[locking.LEVEL_NODE] = self.op.name
    elif self.op.kind == constants.TAG_INSTANCE:
      self.op.name = _ExpandInstanceName(self.cfg, self.op.name)
      self.needed_locks[locking.LEVEL_INSTANCE] = self.op.name

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
    self.share_locks = dict.fromkeys(locking.LEVELS, 1)

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
        self.LogInfo("Test delay iteration %d/%d" % (i, top_value))
        self._TestDelay()


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
        # pylint: disable-msg=E1101
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


class IAllocator(object):
  """IAllocator framework.

  An IAllocator instance has three sets of attributes:
    - cfg that is needed to query the cluster
    - input data (all members of the _KEYS class attribute are required)
    - four buffer attributes (in|out_data|text), that represent the
      input (to the external script) in text and data structure format,
      and the output from it, again in two formats
    - the result variables from the script (success, info, nodes) for
      easy usage

  """
  # pylint: disable-msg=R0902
  # lots of instance attributes
  _ALLO_KEYS = [
    "name", "mem_size", "disks", "disk_template",
    "os", "tags", "nics", "vcpus", "hypervisor",
    ]
  _RELO_KEYS = [
    "name", "relocate_from",
    ]
  _EVAC_KEYS = [
    "evac_nodes",
    ]

  def __init__(self, cfg, rpc, mode, **kwargs):
    self.cfg = cfg
    self.rpc = rpc
    # init buffer variables
    self.in_text = self.out_text = self.in_data = self.out_data = None
    # init all input fields so that pylint is happy
    self.mode = mode
    self.mem_size = self.disks = self.disk_template = None
    self.os = self.tags = self.nics = self.vcpus = None
    self.hypervisor = None
    self.relocate_from = None
    self.name = None
    self.evac_nodes = None
    # computed fields
    self.required_nodes = None
    # init result fields
    self.success = self.info = self.result = None
    if self.mode == constants.IALLOCATOR_MODE_ALLOC:
      keyset = self._ALLO_KEYS
      fn = self._AddNewInstance
    elif self.mode == constants.IALLOCATOR_MODE_RELOC:
      keyset = self._RELO_KEYS
      fn = self._AddRelocateInstance
    elif self.mode == constants.IALLOCATOR_MODE_MEVAC:
      keyset = self._EVAC_KEYS
      fn = self._AddEvacuateNodes
    else:
      raise errors.ProgrammerError("Unknown mode '%s' passed to the"
                                   " IAllocator" % self.mode)
    for key in kwargs:
      if key not in keyset:
        raise errors.ProgrammerError("Invalid input parameter '%s' to"
                                     " IAllocator" % key)
      setattr(self, key, kwargs[key])

    for key in keyset:
      if key not in kwargs:
        raise errors.ProgrammerError("Missing input parameter '%s' to"
                                     " IAllocator" % key)
    self._BuildInputData(fn)

  def _ComputeClusterData(self):
    """Compute the generic allocator input data.

    This is the data that is independent of the actual operation.

    """
    cfg = self.cfg
    cluster_info = cfg.GetClusterInfo()
    # cluster data
    data = {
      "version": constants.IALLOCATOR_VERSION,
      "cluster_name": cfg.GetClusterName(),
      "cluster_tags": list(cluster_info.GetTags()),
      "enabled_hypervisors": list(cluster_info.enabled_hypervisors),
      # we don't have job IDs
      }
    ninfo = cfg.GetAllNodesInfo()
    iinfo = cfg.GetAllInstancesInfo().values()
    i_list = [(inst, cluster_info.FillBE(inst)) for inst in iinfo]

    # node data
    node_list = [n.name for n in ninfo.values() if n.vm_capable]

    if self.mode == constants.IALLOCATOR_MODE_ALLOC:
      hypervisor_name = self.hypervisor
    elif self.mode == constants.IALLOCATOR_MODE_RELOC:
      hypervisor_name = cfg.GetInstanceInfo(self.name).hypervisor
    elif self.mode == constants.IALLOCATOR_MODE_MEVAC:
      hypervisor_name = cluster_info.enabled_hypervisors[0]

    node_data = self.rpc.call_node_info(node_list, cfg.GetVGName(),
                                        hypervisor_name)
    node_iinfo = \
      self.rpc.call_all_instances_info(node_list,
                                       cluster_info.enabled_hypervisors)

    data["nodegroups"] = self._ComputeNodeGroupData(cfg)

    config_ndata = self._ComputeBasicNodeData(ninfo)
    data["nodes"] = self._ComputeDynamicNodeData(ninfo, node_data, node_iinfo,
                                                 i_list, config_ndata)
    assert len(data["nodes"]) == len(ninfo), \
        "Incomplete node data computed"

    data["instances"] = self._ComputeInstanceData(cluster_info, i_list)

    self.in_data = data

  @staticmethod
  def _ComputeNodeGroupData(cfg):
    """Compute node groups data.

    """
    ng = {}
    for guuid, gdata in cfg.GetAllNodeGroupsInfo().items():
      ng[guuid] = {
        "name": gdata.name,
        "alloc_policy": gdata.alloc_policy,
        }
    return ng

  @staticmethod
  def _ComputeBasicNodeData(node_cfg):
    """Compute global node data.

    @rtype: dict
    @returns: a dict of name: (node dict, node config)

    """
    node_results = {}
    for ninfo in node_cfg.values():
      # fill in static (config-based) values
      pnr = {
        "tags": list(ninfo.GetTags()),
        "primary_ip": ninfo.primary_ip,
        "secondary_ip": ninfo.secondary_ip,
        "offline": ninfo.offline,
        "drained": ninfo.drained,
        "master_candidate": ninfo.master_candidate,
        "group": ninfo.group,
        "master_capable": ninfo.master_capable,
        "vm_capable": ninfo.vm_capable,
        }

      node_results[ninfo.name] = pnr

    return node_results

  @staticmethod
  def _ComputeDynamicNodeData(node_cfg, node_data, node_iinfo, i_list,
                              node_results):
    """Compute global node data.

    @param node_results: the basic node structures as filled from the config

    """
    # make a copy of the current dict
    node_results = dict(node_results)
    for nname, nresult in node_data.items():
      assert nname in node_results, "Missing basic data for node %s" % nname
      ninfo = node_cfg[nname]

      if not (ninfo.offline or ninfo.drained):
        nresult.Raise("Can't get data for node %s" % nname)
        node_iinfo[nname].Raise("Can't get node instance info from node %s" %
                                nname)
        remote_info = nresult.payload

        for attr in ['memory_total', 'memory_free', 'memory_dom0',
                     'vg_size', 'vg_free', 'cpu_total']:
          if attr not in remote_info:
            raise errors.OpExecError("Node '%s' didn't return attribute"
                                     " '%s'" % (nname, attr))
          if not isinstance(remote_info[attr], int):
            raise errors.OpExecError("Node '%s' returned invalid value"
                                     " for '%s': %s" %
                                     (nname, attr, remote_info[attr]))
        # compute memory used by primary instances
        i_p_mem = i_p_up_mem = 0
        for iinfo, beinfo in i_list:
          if iinfo.primary_node == nname:
            i_p_mem += beinfo[constants.BE_MEMORY]
            if iinfo.name not in node_iinfo[nname].payload:
              i_used_mem = 0
            else:
              i_used_mem = int(node_iinfo[nname].payload[iinfo.name]['memory'])
            i_mem_diff = beinfo[constants.BE_MEMORY] - i_used_mem
            remote_info['memory_free'] -= max(0, i_mem_diff)

            if iinfo.admin_up:
              i_p_up_mem += beinfo[constants.BE_MEMORY]

        # compute memory used by instances
        pnr_dyn = {
          "total_memory": remote_info['memory_total'],
          "reserved_memory": remote_info['memory_dom0'],
          "free_memory": remote_info['memory_free'],
          "total_disk": remote_info['vg_size'],
          "free_disk": remote_info['vg_free'],
          "total_cpus": remote_info['cpu_total'],
          "i_pri_memory": i_p_mem,
          "i_pri_up_memory": i_p_up_mem,
          }
        pnr_dyn.update(node_results[nname])
        node_results[nname] = pnr_dyn

    return node_results

  @staticmethod
  def _ComputeInstanceData(cluster_info, i_list):
    """Compute global instance data.

    """
    instance_data = {}
    for iinfo, beinfo in i_list:
      nic_data = []
      for nic in iinfo.nics:
        filled_params = cluster_info.SimpleFillNIC(nic.nicparams)
        nic_dict = {"mac": nic.mac,
                    "ip": nic.ip,
                    "mode": filled_params[constants.NIC_MODE],
                    "link": filled_params[constants.NIC_LINK],
                   }
        if filled_params[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
          nic_dict["bridge"] = filled_params[constants.NIC_LINK]
        nic_data.append(nic_dict)
      pir = {
        "tags": list(iinfo.GetTags()),
        "admin_up": iinfo.admin_up,
        "vcpus": beinfo[constants.BE_VCPUS],
        "memory": beinfo[constants.BE_MEMORY],
        "os": iinfo.os,
        "nodes": [iinfo.primary_node] + list(iinfo.secondary_nodes),
        "nics": nic_data,
        "disks": [{"size": dsk.size, "mode": dsk.mode} for dsk in iinfo.disks],
        "disk_template": iinfo.disk_template,
        "hypervisor": iinfo.hypervisor,
        }
      pir["disk_space_total"] = _ComputeDiskSize(iinfo.disk_template,
                                                 pir["disks"])
      instance_data[iinfo.name] = pir

    return instance_data

  def _AddNewInstance(self):
    """Add new instance data to allocator structure.

    This in combination with _AllocatorGetClusterData will create the
    correct structure needed as input for the allocator.

    The checks for the completeness of the opcode must have already been
    done.

    """
    disk_space = _ComputeDiskSize(self.disk_template, self.disks)

    if self.disk_template in constants.DTS_NET_MIRROR:
      self.required_nodes = 2
    else:
      self.required_nodes = 1
    request = {
      "name": self.name,
      "disk_template": self.disk_template,
      "tags": self.tags,
      "os": self.os,
      "vcpus": self.vcpus,
      "memory": self.mem_size,
      "disks": self.disks,
      "disk_space_total": disk_space,
      "nics": self.nics,
      "required_nodes": self.required_nodes,
      }
    return request

  def _AddRelocateInstance(self):
    """Add relocate instance data to allocator structure.

    This in combination with _IAllocatorGetClusterData will create the
    correct structure needed as input for the allocator.

    The checks for the completeness of the opcode must have already been
    done.

    """
    instance = self.cfg.GetInstanceInfo(self.name)
    if instance is None:
      raise errors.ProgrammerError("Unknown instance '%s' passed to"
                                   " IAllocator" % self.name)

    if instance.disk_template not in constants.DTS_NET_MIRROR:
      raise errors.OpPrereqError("Can't relocate non-mirrored instances",
                                 errors.ECODE_INVAL)

    if len(instance.secondary_nodes) != 1:
      raise errors.OpPrereqError("Instance has not exactly one secondary node",
                                 errors.ECODE_STATE)

    self.required_nodes = 1
    disk_sizes = [{'size': disk.size} for disk in instance.disks]
    disk_space = _ComputeDiskSize(instance.disk_template, disk_sizes)

    request = {
      "name": self.name,
      "disk_space_total": disk_space,
      "required_nodes": self.required_nodes,
      "relocate_from": self.relocate_from,
      }
    return request

  def _AddEvacuateNodes(self):
    """Add evacuate nodes data to allocator structure.

    """
    request = {
      "evac_nodes": self.evac_nodes
      }
    return request

  def _BuildInputData(self, fn):
    """Build input data structures.

    """
    self._ComputeClusterData()

    request = fn()
    request["type"] = self.mode
    self.in_data["request"] = request

    self.in_text = serializer.Dump(self.in_data)

  def Run(self, name, validate=True, call_fn=None):
    """Run an instance allocator and return the results.

    """
    if call_fn is None:
      call_fn = self.rpc.call_iallocator_runner

    result = call_fn(self.cfg.GetMasterNode(), name, self.in_text)
    result.Raise("Failure while running the iallocator script")

    self.out_text = result.payload
    if validate:
      self._ValidateResult()

  def _ValidateResult(self):
    """Process the allocator results.

    This will process and if successful save the result in
    self.out_data and the other parameters.

    """
    try:
      rdict = serializer.Load(self.out_text)
    except Exception, err:
      raise errors.OpExecError("Can't parse iallocator results: %s" % str(err))

    if not isinstance(rdict, dict):
      raise errors.OpExecError("Can't parse iallocator results: not a dict")

    # TODO: remove backwards compatiblity in later versions
    if "nodes" in rdict and "result" not in rdict:
      rdict["result"] = rdict["nodes"]
      del rdict["nodes"]

    for key in "success", "info", "result":
      if key not in rdict:
        raise errors.OpExecError("Can't parse iallocator results:"
                                 " missing key '%s'" % key)
      setattr(self, key, rdict[key])

    if not isinstance(rdict["result"], list):
      raise errors.OpExecError("Can't parse iallocator results: 'result' key"
                               " is not a list")
    self.out_data = rdict


class LUTestAllocator(NoHooksLU):
  """Run allocator tests.

  This LU runs the allocator tests

  """
  def CheckPrereq(self):
    """Check prerequisites.

    This checks the opcode parameters depending on the director and mode test.

    """
    if self.op.mode == constants.IALLOCATOR_MODE_ALLOC:
      for attr in ["mem_size", "disks", "disk_template",
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
            "size" not in row or
            not isinstance(row["size"], int) or
            "mode" not in row or
            row["mode"] not in ['r', 'w']):
          raise errors.OpPrereqError("Invalid contents of the 'disks'"
                                     " parameter", errors.ECODE_INVAL)
      if self.op.hypervisor is None:
        self.op.hypervisor = self.cfg.GetHypervisorType()
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      fname = _ExpandInstanceName(self.cfg, self.op.name)
      self.op.name = fname
      self.relocate_from = self.cfg.GetInstanceInfo(fname).secondary_nodes
    elif self.op.mode == constants.IALLOCATOR_MODE_MEVAC:
      if not hasattr(self.op, "evac_nodes"):
        raise errors.OpPrereqError("Missing attribute 'evac_nodes' on"
                                   " opcode input", errors.ECODE_INVAL)
    else:
      raise errors.OpPrereqError("Invalid test allocator mode '%s'" %
                                 self.op.mode, errors.ECODE_INVAL)

    if self.op.direction == constants.IALLOCATOR_DIR_OUT:
      if self.op.allocator is None:
        raise errors.OpPrereqError("Missing allocator name",
                                   errors.ECODE_INVAL)
    elif self.op.direction != constants.IALLOCATOR_DIR_IN:
      raise errors.OpPrereqError("Wrong allocator test '%s'" %
                                 self.op.direction, errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Run the allocator test.

    """
    if self.op.mode == constants.IALLOCATOR_MODE_ALLOC:
      ial = IAllocator(self.cfg, self.rpc,
                       mode=self.op.mode,
                       name=self.op.name,
                       mem_size=self.op.mem_size,
                       disks=self.op.disks,
                       disk_template=self.op.disk_template,
                       os=self.op.os,
                       tags=self.op.tags,
                       nics=self.op.nics,
                       vcpus=self.op.vcpus,
                       hypervisor=self.op.hypervisor,
                       )
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      ial = IAllocator(self.cfg, self.rpc,
                       mode=self.op.mode,
                       name=self.op.name,
                       relocate_from=list(self.relocate_from),
                       )
    elif self.op.mode == constants.IALLOCATOR_MODE_MEVAC:
      ial = IAllocator(self.cfg, self.rpc,
                       mode=self.op.mode,
                       evac_nodes=self.op.evac_nodes)
    else:
      raise errors.ProgrammerError("Uncatched mode %s in"
                                   " LUTestAllocator.Exec", self.op.mode)

    if self.op.direction == constants.IALLOCATOR_DIR_IN:
      result = ial.in_text
    else:
      ial.Run(self.op.allocator, validate=False)
      result = ial.out_text
    return result


#: Query type implementations
_QUERY_IMPL = {
  constants.QR_INSTANCE: _InstanceQuery,
  constants.QR_NODE: _NodeQuery,
  constants.QR_GROUP: _GroupQuery,
  }


def _GetQueryImplementation(name):
  """Returns the implemtnation for a query type.

  @param name: Query type, must be one of L{constants.QR_OP_QUERY}

  """
  try:
    return _QUERY_IMPL[name]
  except KeyError:
    raise errors.OpPrereqError("Unknown query resource '%s'" % name,
                               errors.ECODE_INVAL)
