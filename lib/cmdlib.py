#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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

# pylint: disable-msg=W0613,W0201

import os
import os.path
import sha
import time
import tempfile
import re
import platform
import logging
import copy
import random

from ganeti import ssh
from ganeti import utils
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti import constants
from ganeti import objects
from ganeti import opcodes
from ganeti import serializer
from ganeti import ssconf


class LogicalUnit(object):
  """Logical Unit base class.

  Subclasses must follow these rules:
    - implement ExpandNames
    - implement CheckPrereq
    - implement Exec
    - implement BuildHooksEnv
    - redefine HPATH and HTYPE
    - optionally redefine their run requirements:
        REQ_BGL: the LU needs to hold the Big Ganeti Lock exclusively

  Note that all commands require root permissions.

  """
  HPATH = None
  HTYPE = None
  _OP_REQP = []
  REQ_BGL = True

  def __init__(self, processor, op, context, rpc):
    """Constructor for LogicalUnit.

    This needs to be overriden in derived classes in order to check op
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
    self.share_locks = dict(((i, 0) for i in locking.LEVELS))
    self.add_locks = {}
    self.remove_locks = {}
    # Used to force good behavior when calling helper functions
    self.recalculate_locks = {}
    self.__ssh = None
    # logging
    self.LogWarning = processor.LogWarning
    self.LogInfo = processor.LogInfo

    for attr_name in self._OP_REQP:
      attr_val = getattr(op, attr_name, None)
      if attr_val is None:
        raise errors.OpPrereqError("Required parameter '%s' missing" %
                                   attr_name)
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
      - CheckPrereq is run after we have aquired locks (and possible
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
    completed). This way locking, hooks, logging, ecc. can work correctly.

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

    Examples::

      # Acquire all nodes and one instance
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_INSTANCE: ['instance1.example.tld'],
      }
      # Acquire just two nodes
      self.needed_locks = {
        locking.LEVEL_NODE: ['node1.example.tld', 'node2.example.tld'],
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
    raise NotImplementedError

  def Exec(self, feedback_fn):
    """Execute the LU.

    This method should implement the actual work. It should raise
    errors.OpExecError for failures that are somewhat dealt with in
    code, or expected.

    """
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
    expanded_name = self.cfg.ExpandInstanceName(self.op.instance_name)
    if expanded_name is None:
      raise errors.OpPrereqError("Instance '%s' not known" %
                                  self.op.instance_name)
    self.needed_locks[locking.LEVEL_INSTANCE] = expanded_name
    self.op.instance_name = expanded_name

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


class NoHooksLU(LogicalUnit):
  """Simple LU which runs no hooks.

  This LU is intended as a parent for other LogicalUnits which will
  run no hooks, in order to reduce duplicate code.

  """
  HPATH = None
  HTYPE = None


def _GetWantedNodes(lu, nodes):
  """Returns list of checked and expanded node names.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type nodes: list
  @param nodes: list of node names or None for all nodes
  @rtype: list
  @return: the list of nodes, sorted
  @raise errors.OpProgrammerError: if the nodes parameter is wrong type

  """
  if not isinstance(nodes, list):
    raise errors.OpPrereqError("Invalid argument type 'nodes'")

  if not nodes:
    raise errors.ProgrammerError("_GetWantedNodes should only be called with a"
      " non-empty list of nodes whose name is to be expanded.")

  wanted = []
  for name in nodes:
    node = lu.cfg.ExpandNodeName(name)
    if node is None:
      raise errors.OpPrereqError("No such node name '%s'" % name)
    wanted.append(node)

  return utils.NiceSort(wanted)


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
  if not isinstance(instances, list):
    raise errors.OpPrereqError("Invalid argument type 'instances'")

  if instances:
    wanted = []

    for name in instances:
      instance = lu.cfg.ExpandInstanceName(name)
      if instance is None:
        raise errors.OpPrereqError("No such instance name '%s'" % name)
      wanted.append(instance)

  else:
    wanted = lu.cfg.GetInstanceList()
  return utils.NiceSort(wanted)


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
                               % ",".join(delta))


def _CheckBooleanOpField(op, name):
  """Validates boolean opcode parameters.

  This will ensure that an opcode parameter is either a boolean value,
  or None (but that it always exists).

  """
  val = getattr(op, name, None)
  if not (val is None or isinstance(val, bool)):
    raise errors.OpPrereqError("Invalid boolean parameter '%s' (%s)" %
                               (name, str(val)))
  setattr(op, name, val)


def _CheckNodeOnline(lu, node):
  """Ensure that a given node is online.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @raise errors.OpPrereqError: if the nodes is offline

  """
  if lu.cfg.GetNodeInfo(node).offline:
    raise errors.OpPrereqError("Can't use offline node %s" % node)


def _BuildInstanceHookEnv(name, primary_node, secondary_nodes, os_type, status,
                          memory, vcpus, nics):
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
  @param status: the desired status of the instances
  @type memory: string
  @param memory: the memory size of the instance
  @type vcpus: string
  @param vcpus: the count of VCPUs the instance has
  @type nics: list
  @param nics: list of tuples (ip, bridge, mac) representing
      the NICs the instance  has
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
    "INSTANCE_MEMORY": memory,
    "INSTANCE_VCPUS": vcpus,
  }

  if nics:
    nic_count = len(nics)
    for idx, (ip, bridge, mac) in enumerate(nics):
      if ip is None:
        ip = ""
      env["INSTANCE_NIC%d_IP" % idx] = ip
      env["INSTANCE_NIC%d_BRIDGE" % idx] = bridge
      env["INSTANCE_NIC%d_HWADDR" % idx] = mac
  else:
    nic_count = 0

  env["INSTANCE_NIC_COUNT"] = nic_count

  return env


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
  bep = lu.cfg.GetClusterInfo().FillBE(instance)
  args = {
    'name': instance.name,
    'primary_node': instance.primary_node,
    'secondary_nodes': instance.secondary_nodes,
    'os_type': instance.os,
    'status': instance.os,
    'memory': bep[constants.BE_MEMORY],
    'vcpus': bep[constants.BE_VCPUS],
    'nics': [(nic.ip, nic.bridge, nic.mac) for nic in instance.nics],
  }
  if override:
    args.update(override)
  return _BuildInstanceHookEnv(**args)


def _AdjustCandidatePool(lu):
  """Adjust the candidate pool after node operations.

  """
  mod_list = lu.cfg.MaintainCandidatePool()
  if mod_list:
    lu.LogInfo("Promoted nodes to master candidate role: %s",
               ", ".join(mod_list))
    for name in mod_list:
      lu.context.ReaddNode(name)
  mc_now, mc_max = lu.cfg.GetMasterCandidateStats()
  if mc_now > mc_max:
    lu.LogInfo("Note: more nodes are candidates (%d) than desired (%d)" %
               (mc_now, mc_max))


def _CheckInstanceBridgesExist(lu, instance):
  """Check that the brigdes needed by an instance exist.

  """
  # check bridges existance
  brlist = [nic.bridge for nic in instance.nics]
  result = lu.rpc.call_bridges_exist(instance.primary_node, brlist)
  result.Raise()
  if not result.data:
    raise errors.OpPrereqError("One or more target bridges %s does not"
                               " exist on destination node '%s'" %
                               (brlist, instance.primary_node))


class LUDestroyCluster(NoHooksLU):
  """Logical unit for destroying the cluster.

  """
  _OP_REQP = []

  def CheckPrereq(self):
    """Check prerequisites.

    This checks whether the cluster is empty.

    Any errors are signalled by raising errors.OpPrereqError.

    """
    master = self.cfg.GetMasterNode()

    nodelist = self.cfg.GetNodeList()
    if len(nodelist) != 1 or nodelist[0] != master:
      raise errors.OpPrereqError("There are still %d node(s) in"
                                 " this cluster." % (len(nodelist) - 1))
    instancelist = self.cfg.GetInstanceList()
    if instancelist:
      raise errors.OpPrereqError("There are still %d instance(s) in"
                                 " this cluster." % len(instancelist))

  def Exec(self, feedback_fn):
    """Destroys the cluster.

    """
    master = self.cfg.GetMasterNode()
    result = self.rpc.call_node_stop_master(master, False)
    result.Raise()
    if not result.data:
      raise errors.OpExecError("Could not disable the master role")
    priv_key, pub_key, _ = ssh.GetUserFiles(constants.GANETI_RUNAS)
    utils.CreateBackup(priv_key)
    utils.CreateBackup(pub_key)
    return master


class LUVerifyCluster(LogicalUnit):
  """Verifies the cluster status.

  """
  HPATH = "cluster-verify"
  HTYPE = constants.HTYPE_CLUSTER
  _OP_REQP = ["skip_checks"]
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
    }
    self.share_locks = dict(((i, 1) for i in locking.LEVELS))

  def _VerifyNode(self, nodeinfo, file_list, local_cksum,
                  node_result, feedback_fn, master_files):
    """Run multiple tests against a node.

    Test list:

      - compares ganeti version
      - checks vg existance and size > 20G
      - checks config file checksum
      - checks ssh to other nodes

    @type nodeinfo: L{objects.Node}
    @param nodeinfo: the node to check
    @param file_list: required list of files
    @param local_cksum: dictionary of local files and their checksums
    @param node_result: the results from the node
    @param feedback_fn: function used to accumulate results
    @param master_files: list of files that only masters should have

    """
    node = nodeinfo.name

    # main result, node_result should be a non-empty dict
    if not node_result or not isinstance(node_result, dict):
      feedback_fn("  - ERROR: unable to verify node %s." % (node,))
      return True

    # compares ganeti version
    local_version = constants.PROTOCOL_VERSION
    remote_version = node_result.get('version', None)
    if not remote_version:
      feedback_fn("  - ERROR: connection to %s failed" % (node))
      return True

    if local_version != remote_version:
      feedback_fn("  - ERROR: sw version mismatch: master %s, node(%s) %s" %
                      (local_version, node, remote_version))
      return True

    # checks vg existance and size > 20G

    bad = False
    vglist = node_result.get(constants.NV_VGLIST, None)
    if not vglist:
      feedback_fn("  - ERROR: unable to check volume groups on node %s." %
                      (node,))
      bad = True
    else:
      vgstatus = utils.CheckVolumeGroupSize(vglist, self.cfg.GetVGName(),
                                            constants.MIN_VG_SIZE)
      if vgstatus:
        feedback_fn("  - ERROR: %s on node %s" % (vgstatus, node))
        bad = True

    # checks config file checksum

    remote_cksum = node_result.get(constants.NV_FILELIST, None)
    if not isinstance(remote_cksum, dict):
      bad = True
      feedback_fn("  - ERROR: node hasn't returned file checksum data")
    else:
      for file_name in file_list:
        node_is_mc = nodeinfo.master_candidate
        must_have_file = file_name not in master_files
        if file_name not in remote_cksum:
          if node_is_mc or must_have_file:
            bad = True
            feedback_fn("  - ERROR: file '%s' missing" % file_name)
        elif remote_cksum[file_name] != local_cksum[file_name]:
          if node_is_mc or must_have_file:
            bad = True
            feedback_fn("  - ERROR: file '%s' has wrong checksum" % file_name)
          else:
            # not candidate and this is not a must-have file
            bad = True
            feedback_fn("  - ERROR: non master-candidate has old/wrong file"
                        " '%s'" % file_name)
        else:
          # all good, except non-master/non-must have combination
          if not node_is_mc and not must_have_file:
            feedback_fn("  - ERROR: file '%s' should not exist on non master"
                        " candidates" % file_name)

    # checks ssh to any

    if constants.NV_NODELIST not in node_result:
      bad = True
      feedback_fn("  - ERROR: node hasn't returned node ssh connectivity data")
    else:
      if node_result[constants.NV_NODELIST]:
        bad = True
        for node in node_result[constants.NV_NODELIST]:
          feedback_fn("  - ERROR: ssh communication with node '%s': %s" %
                          (node, node_result[constants.NV_NODELIST][node]))

    if constants.NV_NODENETTEST not in node_result:
      bad = True
      feedback_fn("  - ERROR: node hasn't returned node tcp connectivity data")
    else:
      if node_result[constants.NV_NODENETTEST]:
        bad = True
        nlist = utils.NiceSort(node_result[constants.NV_NODENETTEST].keys())
        for node in nlist:
          feedback_fn("  - ERROR: tcp communication with node '%s': %s" %
                          (node, node_result[constants.NV_NODENETTEST][node]))

    hyp_result = node_result.get(constants.NV_HYPERVISOR, None)
    if isinstance(hyp_result, dict):
      for hv_name, hv_result in hyp_result.iteritems():
        if hv_result is not None:
          feedback_fn("  - ERROR: hypervisor %s verify failure: '%s'" %
                      (hv_name, hv_result))
    return bad

  def _VerifyInstance(self, instance, instanceconfig, node_vol_is,
                      node_instance, feedback_fn, n_offline):
    """Verify an instance.

    This function checks to see if the required block devices are
    available on the instance's node.

    """
    bad = False

    node_current = instanceconfig.primary_node

    node_vol_should = {}
    instanceconfig.MapLVsByNode(node_vol_should)

    for node in node_vol_should:
      if node in n_offline:
        # ignore missing volumes on offline nodes
        continue
      for volume in node_vol_should[node]:
        if node not in node_vol_is or volume not in node_vol_is[node]:
          feedback_fn("  - ERROR: volume %s missing on node %s" %
                          (volume, node))
          bad = True

    if not instanceconfig.status == 'down':
      if ((node_current not in node_instance or
          not instance in node_instance[node_current]) and
          node_current not in n_offline):
        feedback_fn("  - ERROR: instance %s not running on node %s" %
                        (instance, node_current))
        bad = True

    for node in node_instance:
      if (not node == node_current):
        if instance in node_instance[node]:
          feedback_fn("  - ERROR: instance %s should not run on node %s" %
                          (instance, node))
          bad = True

    return bad

  def _VerifyOrphanVolumes(self, node_vol_should, node_vol_is, feedback_fn):
    """Verify if there are any unknown volumes in the cluster.

    The .os, .swap and backup volumes are ignored. All other volumes are
    reported as unknown.

    """
    bad = False

    for node in node_vol_is:
      for volume in node_vol_is[node]:
        if node not in node_vol_should or volume not in node_vol_should[node]:
          feedback_fn("  - ERROR: volume %s on node %s should not exist" %
                      (volume, node))
          bad = True
    return bad

  def _VerifyOrphanInstances(self, instancelist, node_instance, feedback_fn):
    """Verify the list of running instances.

    This checks what instances are running but unknown to the cluster.

    """
    bad = False
    for node in node_instance:
      for runninginstance in node_instance[node]:
        if runninginstance not in instancelist:
          feedback_fn("  - ERROR: instance %s on node %s should not exist" %
                          (runninginstance, node))
          bad = True
    return bad

  def _VerifyNPlusOneMemory(self, node_info, instance_cfg, feedback_fn):
    """Verify N+1 Memory Resilience.

    Check that if one single node dies we can still start all the instances it
    was primary for.

    """
    bad = False

    for node, nodeinfo in node_info.iteritems():
      # This code checks that every node which is now listed as secondary has
      # enough memory to host all instances it is supposed to should a single
      # other node in the cluster fail.
      # FIXME: not ready for failover to an arbitrary node
      # FIXME: does not support file-backed instances
      # WARNING: we currently take into account down instances as well as up
      # ones, considering that even if they're down someone might want to start
      # them even in the event of a node failure.
      for prinode, instances in nodeinfo['sinst-by-pnode'].iteritems():
        needed_mem = 0
        for instance in instances:
          bep = self.cfg.GetClusterInfo().FillBE(instance_cfg[instance])
          if bep[constants.BE_AUTO_BALANCE]:
            needed_mem += bep[constants.BE_MEMORY]
        if nodeinfo['mfree'] < needed_mem:
          feedback_fn("  - ERROR: not enough memory on node %s to accomodate"
                      " failovers should node %s fail" % (node, prinode))
          bad = True
    return bad

  def CheckPrereq(self):
    """Check prerequisites.

    Transform the list of checks we're going to skip into a set and check that
    all its members are valid.

    """
    self.skip_set = frozenset(self.op.skip_checks)
    if not constants.VERIFY_OPTIONAL_CHECKS.issuperset(self.skip_set):
      raise errors.OpPrereqError("Invalid checks to be skipped specified")

  def BuildHooksEnv(self):
    """Build hooks env.

    Cluster-Verify hooks just rone in the post phase and their failure makes
    the output be logged in the verify output and the verification to fail.

    """
    all_nodes = self.cfg.GetNodeList()
    # TODO: populate the environment with useful information for verify hooks
    env = {}
    return env, [], all_nodes

  def Exec(self, feedback_fn):
    """Verify integrity of cluster, performing various test on nodes.

    """
    bad = False
    feedback_fn("* Verifying global settings")
    for msg in self.cfg.VerifyConfig():
      feedback_fn("  - ERROR: %s" % msg)

    vg_name = self.cfg.GetVGName()
    hypervisors = self.cfg.GetClusterInfo().enabled_hypervisors
    nodelist = utils.NiceSort(self.cfg.GetNodeList())
    nodeinfo = [self.cfg.GetNodeInfo(nname) for nname in nodelist]
    instancelist = utils.NiceSort(self.cfg.GetInstanceList())
    i_non_redundant = [] # Non redundant instances
    i_non_a_balanced = [] # Non auto-balanced instances
    n_offline = [] # List of offline nodes
    node_volume = {}
    node_instance = {}
    node_info = {}
    instance_cfg = {}

    # FIXME: verify OS list
    # do local checksums
    master_files = [constants.CLUSTER_CONF_FILE]

    file_names = ssconf.SimpleStore().GetFileList()
    file_names.append(constants.SSL_CERT_FILE)
    file_names.extend(master_files)

    local_checksums = utils.FingerprintFiles(file_names)

    feedback_fn("* Gathering data (%d nodes)" % len(nodelist))
    node_verify_param = {
      constants.NV_FILELIST: file_names,
      constants.NV_NODELIST: nodelist,
      constants.NV_HYPERVISOR: hypervisors,
      constants.NV_NODENETTEST: [(node.name, node.primary_ip,
                                  node.secondary_ip) for node in nodeinfo],
      constants.NV_LVLIST: vg_name,
      constants.NV_INSTANCELIST: hypervisors,
      constants.NV_VGLIST: None,
      constants.NV_VERSION: None,
      constants.NV_HVINFO: self.cfg.GetHypervisorType(),
      }
    all_nvinfo = self.rpc.call_node_verify(nodelist, node_verify_param,
                                           self.cfg.GetClusterName())

    cluster = self.cfg.GetClusterInfo()
    master_node = self.cfg.GetMasterNode()
    for node_i in nodeinfo:
      node = node_i.name
      nresult = all_nvinfo[node].data

      if node_i.offline:
        feedback_fn("* Skipping offline node %s" % (node,))
        n_offline.append(node)
        continue

      if node == master_node:
        ntype = "master"
      elif node_i.master_candidate:
        ntype = "master candidate"
      else:
        ntype = "regular"
      feedback_fn("* Verifying node %s (%s)" % (node, ntype))

      if all_nvinfo[node].failed or not isinstance(nresult, dict):
        feedback_fn("  - ERROR: connection to %s failed" % (node,))
        bad = True
        continue

      result = self._VerifyNode(node_i, file_names, local_checksums,
                                nresult, feedback_fn, master_files)
      bad = bad or result

      lvdata = nresult.get(constants.NV_LVLIST, "Missing LV data")
      if isinstance(lvdata, basestring):
        feedback_fn("  - ERROR: LVM problem on node %s: %s" %
                    (node, lvdata.encode('string_escape')))
        bad = True
        node_volume[node] = {}
      elif not isinstance(lvdata, dict):
        feedback_fn("  - ERROR: connection to %s failed (lvlist)" % (node,))
        bad = True
        continue
      else:
        node_volume[node] = lvdata

      # node_instance
      idata = nresult.get(constants.NV_INSTANCELIST, None)
      if not isinstance(idata, list):
        feedback_fn("  - ERROR: connection to %s failed (instancelist)" %
                    (node,))
        bad = True
        continue

      node_instance[node] = idata

      # node_info
      nodeinfo = nresult.get(constants.NV_HVINFO, None)
      if not isinstance(nodeinfo, dict):
        feedback_fn("  - ERROR: connection to %s failed (hvinfo)" % (node,))
        bad = True
        continue

      try:
        node_info[node] = {
          "mfree": int(nodeinfo['memory_free']),
          "dfree": int(nresult[constants.NV_VGLIST][vg_name]),
          "pinst": [],
          "sinst": [],
          # dictionary holding all instances this node is secondary for,
          # grouped by their primary node. Each key is a cluster node, and each
          # value is a list of instances which have the key as primary and the
          # current node as secondary.  this is handy to calculate N+1 memory
          # availability if you can only failover from a primary to its
          # secondary.
          "sinst-by-pnode": {},
        }
      except ValueError:
        feedback_fn("  - ERROR: invalid value returned from node %s" % (node,))
        bad = True
        continue

    node_vol_should = {}

    for instance in instancelist:
      feedback_fn("* Verifying instance %s" % instance)
      inst_config = self.cfg.GetInstanceInfo(instance)
      result =  self._VerifyInstance(instance, inst_config, node_volume,
                                     node_instance, feedback_fn, n_offline)
      bad = bad or result

      inst_config.MapLVsByNode(node_vol_should)

      instance_cfg[instance] = inst_config

      pnode = inst_config.primary_node
      if pnode in node_info:
        node_info[pnode]['pinst'].append(instance)
      elif pnode not in n_offline:
        feedback_fn("  - ERROR: instance %s, connection to primary node"
                    " %s failed" % (instance, pnode))
        bad = True

      # If the instance is non-redundant we cannot survive losing its primary
      # node, so we are not N+1 compliant. On the other hand we have no disk
      # templates with more than one secondary so that situation is not well
      # supported either.
      # FIXME: does not support file-backed instances
      if len(inst_config.secondary_nodes) == 0:
        i_non_redundant.append(instance)
      elif len(inst_config.secondary_nodes) > 1:
        feedback_fn("  - WARNING: multiple secondaries for instance %s"
                    % instance)

      if not cluster.FillBE(inst_config)[constants.BE_AUTO_BALANCE]:
        i_non_a_balanced.append(instance)

      for snode in inst_config.secondary_nodes:
        if snode in node_info:
          node_info[snode]['sinst'].append(instance)
          if pnode not in node_info[snode]['sinst-by-pnode']:
            node_info[snode]['sinst-by-pnode'][pnode] = []
          node_info[snode]['sinst-by-pnode'][pnode].append(instance)
        elif snode not in n_offline:
          feedback_fn("  - ERROR: instance %s, connection to secondary node"
                      " %s failed" % (instance, snode))

    feedback_fn("* Verifying orphan volumes")
    result = self._VerifyOrphanVolumes(node_vol_should, node_volume,
                                       feedback_fn)
    bad = bad or result

    feedback_fn("* Verifying remaining instances")
    result = self._VerifyOrphanInstances(instancelist, node_instance,
                                         feedback_fn)
    bad = bad or result

    if constants.VERIFY_NPLUSONE_MEM not in self.skip_set:
      feedback_fn("* Verifying N+1 Memory redundancy")
      result = self._VerifyNPlusOneMemory(node_info, instance_cfg, feedback_fn)
      bad = bad or result

    feedback_fn("* Other Notes")
    if i_non_redundant:
      feedback_fn("  - NOTICE: %d non-redundant instance(s) found."
                  % len(i_non_redundant))

    if i_non_a_balanced:
      feedback_fn("  - NOTICE: %d non-auto-balanced instance(s) found."
                  % len(i_non_a_balanced))

    if n_offline:
      feedback_fn("  - NOTICE: %d offline node(s) found." % len(n_offline))

    return not bad

  def HooksCallBack(self, phase, hooks_results, feedback_fn, lu_result):
    """Analize the post-hooks' result

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
      indent_re = re.compile('^', re.M)
      feedback_fn("* Hooks Results")
      if not hooks_results:
        feedback_fn("  - ERROR: general communication failure")
        lu_result = 1
      else:
        for node_name in hooks_results:
          show_node_header = True
          res = hooks_results[node_name]
          if res.failed or res.data is False or not isinstance(res.data, list):
            if res.offline:
              # no need to warn or set fail return value
              continue
            feedback_fn("    Communication failure in hooks execution")
            lu_result = 1
            continue
          for script, hkr, output in res.data:
            if hkr == constants.HKR_FAIL:
              # The node header is only shown once, if there are
              # failing hooks on that node
              if show_node_header:
                feedback_fn("  Node %s:" % node_name)
                show_node_header = False
              feedback_fn("    ERROR: Script %s failed, output:" % script)
              output = indent_re.sub('      ', output)
              feedback_fn("%s" % output)
              lu_result = 1

      return lu_result


class LUVerifyDisks(NoHooksLU):
  """Verifies the cluster disks status.

  """
  _OP_REQP = []
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
    }
    self.share_locks = dict(((i, 1) for i in locking.LEVELS))

  def CheckPrereq(self):
    """Check prerequisites.

    This has no prerequisites.

    """
    pass

  def Exec(self, feedback_fn):
    """Verify integrity of cluster disks.

    """
    result = res_nodes, res_nlvm, res_instances, res_missing = [], {}, [], {}

    vg_name = self.cfg.GetVGName()
    nodes = utils.NiceSort(self.cfg.GetNodeList())
    instances = [self.cfg.GetInstanceInfo(name)
                 for name in self.cfg.GetInstanceList()]

    nv_dict = {}
    for inst in instances:
      inst_lvs = {}
      if (inst.status != "up" or
          inst.disk_template not in constants.DTS_NET_MIRROR):
        continue
      inst.MapLVsByNode(inst_lvs)
      # transform { iname: {node: [vol,],},} to {(node, vol): iname}
      for node, vol_list in inst_lvs.iteritems():
        for vol in vol_list:
          nv_dict[(node, vol)] = inst

    if not nv_dict:
      return result

    node_lvs = self.rpc.call_volume_list(nodes, vg_name)

    to_act = set()
    for node in nodes:
      # node_volume
      lvs = node_lvs[node]
      if lvs.failed:
        if not lvs.offline:
          self.LogWarning("Connection to node %s failed: %s" %
                          (node, lvs.data))
        continue
      lvs = lvs.data
      if isinstance(lvs, basestring):
        logging.warning("Error enumerating LVs on node %s: %s", node, lvs)
        res_nlvm[node] = lvs
      elif not isinstance(lvs, dict):
        logging.warning("Connection to node %s failed or invalid data"
                        " returned", node)
        res_nodes.append(node)
        continue

      for lv_name, (_, lv_inactive, lv_online) in lvs.iteritems():
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


class LURenameCluster(LogicalUnit):
  """Rename the cluster.

  """
  HPATH = "cluster-rename"
  HTYPE = constants.HTYPE_CLUSTER
  _OP_REQP = ["name"]

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    env = {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_NAME": self.op.name,
      }
    mn = self.cfg.GetMasterNode()
    return env, [mn], [mn]

  def CheckPrereq(self):
    """Verify that the passed name is a valid one.

    """
    hostname = utils.HostInfo(self.op.name)

    new_name = hostname.name
    self.ip = new_ip = hostname.ip
    old_name = self.cfg.GetClusterName()
    old_ip = self.cfg.GetMasterIP()
    if new_name == old_name and new_ip == old_ip:
      raise errors.OpPrereqError("Neither the name nor the IP address of the"
                                 " cluster has changed")
    if new_ip != old_ip:
      if utils.TcpPing(new_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("The given cluster IP address (%s) is"
                                   " reachable on the network. Aborting." %
                                   new_ip)

    self.op.name = new_name

  def Exec(self, feedback_fn):
    """Rename the cluster.

    """
    clustername = self.op.name
    ip = self.ip

    # shutdown the master IP
    master = self.cfg.GetMasterNode()
    result = self.rpc.call_node_stop_master(master, False)
    if result.failed or not result.data:
      raise errors.OpExecError("Could not disable the master role")

    try:
      cluster = self.cfg.GetClusterInfo()
      cluster.cluster_name = clustername
      cluster.master_ip = ip
      self.cfg.Update(cluster)

      # update the known hosts file
      ssh.WriteKnownHostsFile(self.cfg, constants.SSH_KNOWN_HOSTS_FILE)
      node_list = self.cfg.GetNodeList()
      try:
        node_list.remove(master)
      except ValueError:
        pass
      result = self.rpc.call_upload_file(node_list,
                                         constants.SSH_KNOWN_HOSTS_FILE)
      for to_node, to_result in result.iteritems():
        if to_result.failed or not to_result.data:
          logging.error("Copy of file %s to node %s failed", fname, to_node)

    finally:
      result = self.rpc.call_node_start_master(master, False)
      if result.failed or not result.data:
        self.LogWarning("Could not re-enable the master role on"
                        " the master, please restart manually.")


def _RecursiveCheckIfLVMBased(disk):
  """Check if the given disk or its children are lvm-based.

  @type disk: L{objects.Disk}
  @param disk: the disk to check
  @rtype: booleean
  @return: boolean indicating whether a LD_LV dev_type was found or not

  """
  if disk.children:
    for chdisk in disk.children:
      if _RecursiveCheckIfLVMBased(chdisk):
        return True
  return disk.dev_type == constants.LD_LV


class LUSetClusterParams(LogicalUnit):
  """Change the parameters of the cluster.

  """
  HPATH = "cluster-modify"
  HTYPE = constants.HTYPE_CLUSTER
  _OP_REQP = []
  REQ_BGL = False

  def CheckParameters(self):
    """Check parameters

    """
    if not hasattr(self.op, "candidate_pool_size"):
      self.op.candidate_pool_size = None
    if self.op.candidate_pool_size is not None:
      try:
        self.op.candidate_pool_size = int(self.op.candidate_pool_size)
      except ValueError, err:
        raise errors.OpPrereqError("Invalid candidate_pool_size value: %s" %
                                   str(err))
      if self.op.candidate_pool_size < 1:
        raise errors.OpPrereqError("At least one master candidate needed")

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
    # FIXME: This only works because there is only one parameter that can be
    # changed or removed.
    if self.op.vg_name is not None and not self.op.vg_name:
      instances = self.cfg.GetAllInstancesInfo().values()
      for inst in instances:
        for disk in inst.disks:
          if _RecursiveCheckIfLVMBased(disk):
            raise errors.OpPrereqError("Cannot disable lvm storage while"
                                       " lvm-based instances exist")

    node_list = self.acquired_locks[locking.LEVEL_NODE]

    # if vg_name not None, checks given volume group on all nodes
    if self.op.vg_name:
      vglist = self.rpc.call_vg_list(node_list)
      for node in node_list:
        if vglist[node].failed:
          # ignoring down node
          self.LogWarning("Node %s unreachable/error, ignoring" % node)
          continue
        vgstatus = utils.CheckVolumeGroupSize(vglist[node].data,
                                              self.op.vg_name,
                                              constants.MIN_VG_SIZE)
        if vgstatus:
          raise errors.OpPrereqError("Error on node '%s': %s" %
                                     (node, vgstatus))

    self.cluster = cluster = self.cfg.GetClusterInfo()
    # validate beparams changes
    if self.op.beparams:
      utils.CheckBEParams(self.op.beparams)
      self.new_beparams = cluster.FillDict(
        cluster.beparams[constants.BEGR_DEFAULT], self.op.beparams)

    # hypervisor list/parameters
    self.new_hvparams = cluster.FillDict(cluster.hvparams, {})
    if self.op.hvparams:
      if not isinstance(self.op.hvparams, dict):
        raise errors.OpPrereqError("Invalid 'hvparams' parameter on input")
      for hv_name, hv_dict in self.op.hvparams.items():
        if hv_name not in self.new_hvparams:
          self.new_hvparams[hv_name] = hv_dict
        else:
          self.new_hvparams[hv_name].update(hv_dict)

    if self.op.enabled_hypervisors is not None:
      self.hv_list = self.op.enabled_hypervisors
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
          hv_class.CheckParameterSyntax(hv_params)
          _CheckHVParams(self, node_list, hv_name, hv_params)

  def Exec(self, feedback_fn):
    """Change the parameters of the cluster.

    """
    if self.op.vg_name is not None:
      if self.op.vg_name != self.cfg.GetVGName():
        self.cfg.SetVGName(self.op.vg_name)
      else:
        feedback_fn("Cluster LVM configuration already in desired"
                    " state, not changing")
    if self.op.hvparams:
      self.cluster.hvparams = self.new_hvparams
    if self.op.enabled_hypervisors is not None:
      self.cluster.enabled_hypervisors = self.op.enabled_hypervisors
    if self.op.beparams:
      self.cluster.beparams[constants.BEGR_DEFAULT] = self.new_beparams
    if self.op.candidate_pool_size is not None:
      self.cluster.candidate_pool_size = self.op.candidate_pool_size

    self.cfg.Update(self.cluster)

    # we want to update nodes after the cluster so that if any errors
    # happen, we have recorded and saved the cluster info
    if self.op.candidate_pool_size is not None:
      _AdjustCandidatePool(self)


def _WaitForSync(lu, instance, oneshot=False, unlock=False):
  """Sleep and poll for an instance's disk to sync.

  """
  if not instance.disks:
    return True

  if not oneshot:
    lu.proc.LogInfo("Waiting for instance %s to sync disks." % instance.name)

  node = instance.primary_node

  for dev in instance.disks:
    lu.cfg.SetDiskID(dev, node)

  retries = 0
  while True:
    max_time = 0
    done = True
    cumul_degraded = False
    rstats = lu.rpc.call_blockdev_getmirrorstatus(node, instance.disks)
    if rstats.failed or not rstats.data:
      lu.LogWarning("Can't get any data from node %s", node)
      retries += 1
      if retries >= 10:
        raise errors.RemoteError("Can't contact node %s for mirror data,"
                                 " aborting." % node)
      time.sleep(6)
      continue
    rstats = rstats.data
    retries = 0
    for i in range(len(rstats)):
      mstat = rstats[i]
      if mstat is None:
        lu.LogWarning("Can't compute data for node %s/%s",
                           node, instance.disks[i].iv_name)
        continue
      # we ignore the ldisk parameter
      perc_done, est_time, is_degraded, _ = mstat
      cumul_degraded = cumul_degraded or (is_degraded and perc_done is None)
      if perc_done is not None:
        done = False
        if est_time is not None:
          rem_time = "%d estimated seconds remaining" % est_time
          max_time = est_time
        else:
          rem_time = "no time estimate"
        lu.proc.LogInfo("- device %s: %5.2f%% done, %s" %
                        (instance.disks[i].iv_name, perc_done, rem_time))
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
  if ldisk:
    idx = 6
  else:
    idx = 5

  result = True
  if on_primary or dev.AssembleOnSecondary():
    rstats = lu.rpc.call_blockdev_find(node, dev)
    if rstats.failed or not rstats.data:
      logging.warning("Node %s: disk degraded, not found or node down", node)
      result = False
    else:
      result = result and (not rstats.data[idx])
  if dev.children:
    for child in dev.children:
      result = result and _CheckDiskConsistency(lu, child, node, on_primary)

  return result


class LUDiagnoseOS(NoHooksLU):
  """Logical unit for OS diagnose/query.

  """
  _OP_REQP = ["output_fields", "names"]
  REQ_BGL = False
  _FIELDS_STATIC = utils.FieldSet()
  _FIELDS_DYNAMIC = utils.FieldSet("name", "valid", "node_status")

  def ExpandNames(self):
    if self.op.names:
      raise errors.OpPrereqError("Selective OS query not supported")

    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

    # Lock all nodes, in shared mode
    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1
    self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def CheckPrereq(self):
    """Check prerequisites.

    """

  @staticmethod
  def _DiagnoseByOS(node_list, rlist):
    """Remaps a per-node return list into an a per-os per-node dictionary

    @param node_list: a list with the names of all nodes
    @param rlist: a map with node names as keys and OS objects as values

    @rtype: dict
    @returns: a dictionary with osnames as keys and as value another map, with
        nodes as keys and list of OS objects as values, eg::

          {"debian-etch": {"node1": [<object>,...],
                           "node2": [<object>,]}
          }

    """
    all_os = {}
    for node_name, nr in rlist.iteritems():
      if nr.failed or not nr.data:
        continue
      for os_obj in nr.data:
        if os_obj.name not in all_os:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_os[os_obj.name] = {}
          for nname in node_list:
            all_os[os_obj.name][nname] = []
        all_os[os_obj.name][node_name].append(os_obj)
    return all_os

  def Exec(self, feedback_fn):
    """Compute the list of OSes.

    """
    node_list = self.acquired_locks[locking.LEVEL_NODE]
    node_data = self.rpc.call_os_diagnose(node_list)
    if node_data == False:
      raise errors.OpExecError("Can't gather the list of OSes")
    pol = self._DiagnoseByOS(node_list, node_data)
    output = []
    for os_name, os_data in pol.iteritems():
      row = []
      for field in self.op.output_fields:
        if field == "name":
          val = os_name
        elif field == "valid":
          val = utils.all([osl and osl[0] for osl in os_data.values()])
        elif field == "node_status":
          val = {}
          for node_name, nos_list in os_data.iteritems():
            val[node_name] = [(v.status, v.path) for v in nos_list]
        else:
          raise errors.ParameterError(field)
        row.append(val)
      output.append(row)

    return output


class LURemoveNode(LogicalUnit):
  """Logical unit for removing a node.

  """
  HPATH = "node-remove"
  HTYPE = constants.HTYPE_NODE
  _OP_REQP = ["node_name"]

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
    all_nodes.remove(self.op.node_name)
    return env, all_nodes, all_nodes

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the node exists in the configuration
     - it does not have primary or secondary instances
     - it's not the master

    Any errors are signalled by raising errors.OpPrereqError.

    """
    node = self.cfg.GetNodeInfo(self.cfg.ExpandNodeName(self.op.node_name))
    if node is None:
      raise errors.OpPrereqError, ("Node '%s' is unknown." % self.op.node_name)

    instance_list = self.cfg.GetInstanceList()

    masternode = self.cfg.GetMasterNode()
    if node.name == masternode:
      raise errors.OpPrereqError("Node is the master node,"
                                 " you need to failover first.")

    for instance_name in instance_list:
      instance = self.cfg.GetInstanceInfo(instance_name)
      if node.name == instance.primary_node:
        raise errors.OpPrereqError("Instance %s still running on the node,"
                                   " please remove first." % instance_name)
      if node.name in instance.secondary_nodes:
        raise errors.OpPrereqError("Instance %s has node as a secondary,"
                                   " please remove first." % instance_name)
    self.op.node_name = node.name
    self.node = node

  def Exec(self, feedback_fn):
    """Removes the node from the cluster.

    """
    node = self.node
    logging.info("Stopping the node daemon and removing configs from node %s",
                 node.name)

    self.context.RemoveNode(node.name)

    self.rpc.call_node_leave_cluster(node.name)

    # Promote nodes to master candidate as needed
    _AdjustCandidatePool(self)


class LUQueryNodes(NoHooksLU):
  """Logical unit for querying nodes.

  """
  _OP_REQP = ["output_fields", "names"]
  REQ_BGL = False
  _FIELDS_DYNAMIC = utils.FieldSet(
    "dtotal", "dfree",
    "mtotal", "mnode", "mfree",
    "bootid",
    "ctotal",
    )

  _FIELDS_STATIC = utils.FieldSet(
    "name", "pinst_cnt", "sinst_cnt",
    "pinst_list", "sinst_list",
    "pip", "sip", "tags",
    "serial_no",
    "master_candidate",
    "master",
    "offline",
    )

  def ExpandNames(self):
    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1

    if self.op.names:
      self.wanted = _GetWantedNodes(self, self.op.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self._FIELDS_STATIC.NonMatching(self.op.output_fields)
    if self.do_locking:
      # if we don't request only static fields, we need to lock the nodes
      self.needed_locks[locking.LEVEL_NODE] = self.wanted


  def CheckPrereq(self):
    """Check prerequisites.

    """
    # The validation of the node list is done in the _GetWantedNodes,
    # if non empty, and if empty, there's no validation to do
    pass

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    all_info = self.cfg.GetAllNodesInfo()
    if self.do_locking:
      nodenames = self.acquired_locks[locking.LEVEL_NODE]
    elif self.wanted != locking.ALL_SET:
      nodenames = self.wanted
      missing = set(nodenames).difference(all_info.keys())
      if missing:
        raise errors.OpExecError(
          "Some nodes were removed before retrieving their data: %s" % missing)
    else:
      nodenames = all_info.keys()

    nodenames = utils.NiceSort(nodenames)
    nodelist = [all_info[name] for name in nodenames]

    # begin data gathering

    if self.do_locking:
      live_data = {}
      node_data = self.rpc.call_node_info(nodenames, self.cfg.GetVGName(),
                                          self.cfg.GetHypervisorType())
      for name in nodenames:
        nodeinfo = node_data[name]
        if not nodeinfo.failed and nodeinfo.data:
          nodeinfo = nodeinfo.data
          fn = utils.TryConvert
          live_data[name] = {
            "mtotal": fn(int, nodeinfo.get('memory_total', None)),
            "mnode": fn(int, nodeinfo.get('memory_dom0', None)),
            "mfree": fn(int, nodeinfo.get('memory_free', None)),
            "dtotal": fn(int, nodeinfo.get('vg_size', None)),
            "dfree": fn(int, nodeinfo.get('vg_free', None)),
            "ctotal": fn(int, nodeinfo.get('cpu_total', None)),
            "bootid": nodeinfo.get('bootid', None),
            }
        else:
          live_data[name] = {}
    else:
      live_data = dict.fromkeys(nodenames, {})

    node_to_primary = dict([(name, set()) for name in nodenames])
    node_to_secondary = dict([(name, set()) for name in nodenames])

    inst_fields = frozenset(("pinst_cnt", "pinst_list",
                             "sinst_cnt", "sinst_list"))
    if inst_fields & frozenset(self.op.output_fields):
      instancelist = self.cfg.GetInstanceList()

      for instance_name in instancelist:
        inst = self.cfg.GetInstanceInfo(instance_name)
        if inst.primary_node in node_to_primary:
          node_to_primary[inst.primary_node].add(inst.name)
        for secnode in inst.secondary_nodes:
          if secnode in node_to_secondary:
            node_to_secondary[secnode].add(inst.name)

    master_node = self.cfg.GetMasterNode()

    # end data gathering

    output = []
    for node in nodelist:
      node_output = []
      for field in self.op.output_fields:
        if field == "name":
          val = node.name
        elif field == "pinst_list":
          val = list(node_to_primary[node.name])
        elif field == "sinst_list":
          val = list(node_to_secondary[node.name])
        elif field == "pinst_cnt":
          val = len(node_to_primary[node.name])
        elif field == "sinst_cnt":
          val = len(node_to_secondary[node.name])
        elif field == "pip":
          val = node.primary_ip
        elif field == "sip":
          val = node.secondary_ip
        elif field == "tags":
          val = list(node.GetTags())
        elif field == "serial_no":
          val = node.serial_no
        elif field == "master_candidate":
          val = node.master_candidate
        elif field == "master":
          val = node.name == master_node
        elif field == "offline":
          val = node.offline
        elif self._FIELDS_DYNAMIC.Matches(field):
          val = live_data[node.name].get(field, None)
        else:
          raise errors.ParameterError(field)
        node_output.append(val)
      output.append(node_output)

    return output


class LUQueryNodeVolumes(NoHooksLU):
  """Logical unit for getting volumes on node(s).

  """
  _OP_REQP = ["nodes", "output_fields"]
  REQ_BGL = False
  _FIELDS_DYNAMIC = utils.FieldSet("phys", "vg", "name", "size", "instance")
  _FIELDS_STATIC = utils.FieldSet("node")

  def ExpandNames(self):
    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1
    if not self.op.nodes:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
    else:
      self.needed_locks[locking.LEVEL_NODE] = \
        _GetWantedNodes(self, self.op.nodes)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the fields required are valid output fields.

    """
    self.nodes = self.acquired_locks[locking.LEVEL_NODE]

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    nodenames = self.nodes
    volumes = self.rpc.call_node_volumes(nodenames)

    ilist = [self.cfg.GetInstanceInfo(iname) for iname
             in self.cfg.GetInstanceList()]

    lv_by_node = dict([(inst, inst.MapLVsByNode()) for inst in ilist])

    output = []
    for node in nodenames:
      if node not in volumes or volumes[node].failed or not volumes[node].data:
        continue

      node_vols = volumes[node].data[:]
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


class LUAddNode(LogicalUnit):
  """Logical unit for adding node to the cluster.

  """
  HPATH = "node-add"
  HTYPE = constants.HTYPE_NODE
  _OP_REQP = ["node_name"]

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on all nodes before, and on all nodes + the new node after.

    """
    env = {
      "OP_TARGET": self.op.node_name,
      "NODE_NAME": self.op.node_name,
      "NODE_PIP": self.op.primary_ip,
      "NODE_SIP": self.op.secondary_ip,
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

    Any errors are signalled by raising errors.OpPrereqError.

    """
    node_name = self.op.node_name
    cfg = self.cfg

    dns_data = utils.HostInfo(node_name)

    node = dns_data.name
    primary_ip = self.op.primary_ip = dns_data.ip
    secondary_ip = getattr(self.op, "secondary_ip", None)
    if secondary_ip is None:
      secondary_ip = primary_ip
    if not utils.IsValidIP(secondary_ip):
      raise errors.OpPrereqError("Invalid secondary IP given")
    self.op.secondary_ip = secondary_ip

    node_list = cfg.GetNodeList()
    if not self.op.readd and node in node_list:
      raise errors.OpPrereqError("Node %s is already in the configuration" %
                                 node)
    elif self.op.readd and node not in node_list:
      raise errors.OpPrereqError("Node %s is not in the configuration" % node)

    for existing_node_name in node_list:
      existing_node = cfg.GetNodeInfo(existing_node_name)

      if self.op.readd and node == existing_node_name:
        if (existing_node.primary_ip != primary_ip or
            existing_node.secondary_ip != secondary_ip):
          raise errors.OpPrereqError("Readded node doesn't have the same IP"
                                     " address configuration as before")
        continue

      if (existing_node.primary_ip == primary_ip or
          existing_node.secondary_ip == primary_ip or
          existing_node.primary_ip == secondary_ip or
          existing_node.secondary_ip == secondary_ip):
        raise errors.OpPrereqError("New node ip address(es) conflict with"
                                   " existing node %s" % existing_node.name)

    # check that the type of the node (single versus dual homed) is the
    # same as for the master
    myself = cfg.GetNodeInfo(self.cfg.GetMasterNode())
    master_singlehomed = myself.secondary_ip == myself.primary_ip
    newbie_singlehomed = secondary_ip == primary_ip
    if master_singlehomed != newbie_singlehomed:
      if master_singlehomed:
        raise errors.OpPrereqError("The master has no private ip but the"
                                   " new node has one")
      else:
        raise errors.OpPrereqError("The master has a private ip but the"
                                   " new node doesn't have one")

    # checks reachablity
    if not utils.TcpPing(primary_ip, constants.DEFAULT_NODED_PORT):
      raise errors.OpPrereqError("Node not reachable by ping")

    if not newbie_singlehomed:
      # check reachability from my secondary ip to newbie's secondary ip
      if not utils.TcpPing(secondary_ip, constants.DEFAULT_NODED_PORT,
                           source=myself.secondary_ip):
        raise errors.OpPrereqError("Node secondary ip not reachable by TCP"
                                   " based ping to noded port")

    cp_size = self.cfg.GetClusterInfo().candidate_pool_size
    node_info = self.cfg.GetAllNodesInfo().values()
    mc_now, _ = self.cfg.GetMasterCandidateStats()
    master_candidate = mc_now < cp_size

    self.new_node = objects.Node(name=node,
                                 primary_ip=primary_ip,
                                 secondary_ip=secondary_ip,
                                 master_candidate=master_candidate,
                                 offline=False)

  def Exec(self, feedback_fn):
    """Adds the new node to the cluster.

    """
    new_node = self.new_node
    node = new_node.name

    # check connectivity
    result = self.rpc.call_version([node])[node]
    result.Raise()
    if result.data:
      if constants.PROTOCOL_VERSION == result.data:
        logging.info("Communication to node %s fine, sw version %s match",
                     node, result.data)
      else:
        raise errors.OpExecError("Version mismatch master version %s,"
                                 " node version %s" %
                                 (constants.PROTOCOL_VERSION, result.data))
    else:
      raise errors.OpExecError("Cannot get version from the new node")

    # setup ssh on node
    logging.info("Copy ssh key to node %s", node)
    priv_key, pub_key, _ = ssh.GetUserFiles(constants.GANETI_RUNAS)
    keyarray = []
    keyfiles = [constants.SSH_HOST_DSA_PRIV, constants.SSH_HOST_DSA_PUB,
                constants.SSH_HOST_RSA_PRIV, constants.SSH_HOST_RSA_PUB,
                priv_key, pub_key]

    for i in keyfiles:
      f = open(i, 'r')
      try:
        keyarray.append(f.read())
      finally:
        f.close()

    result = self.rpc.call_node_add(node, keyarray[0], keyarray[1],
                                    keyarray[2],
                                    keyarray[3], keyarray[4], keyarray[5])

    if result.failed or not result.data:
      raise errors.OpExecError("Cannot transfer ssh keys to the new node")

    # Add node to our /etc/hosts, and add key to known_hosts
    utils.AddHostToEtcHosts(new_node.name)

    if new_node.secondary_ip != new_node.primary_ip:
      result = self.rpc.call_node_has_ip_address(new_node.name,
                                                 new_node.secondary_ip)
      if result.failed or not result.data:
        raise errors.OpExecError("Node claims it doesn't have the secondary ip"
                                 " you gave (%s). Please fix and re-run this"
                                 " command." % new_node.secondary_ip)

    node_verify_list = [self.cfg.GetMasterNode()]
    node_verify_param = {
      'nodelist': [node],
      # TODO: do a node-net-test as well?
    }

    result = self.rpc.call_node_verify(node_verify_list, node_verify_param,
                                       self.cfg.GetClusterName())
    for verifier in node_verify_list:
      if result[verifier].failed or not result[verifier].data:
        raise errors.OpExecError("Cannot communicate with %s's node daemon"
                                 " for remote verification" % verifier)
      if result[verifier].data['nodelist']:
        for failed in result[verifier].data['nodelist']:
          feedback_fn("ssh/hostname verification failed %s -> %s" %
                      (verifier, result[verifier]['nodelist'][failed]))
        raise errors.OpExecError("ssh/hostname verification failed.")

    # Distribute updated /etc/hosts and known_hosts to all nodes,
    # including the node just added
    myself = self.cfg.GetNodeInfo(self.cfg.GetMasterNode())
    dist_nodes = self.cfg.GetNodeList()
    if not self.op.readd:
      dist_nodes.append(node)
    if myself.name in dist_nodes:
      dist_nodes.remove(myself.name)

    logging.debug("Copying hosts and known_hosts to all nodes")
    for fname in (constants.ETC_HOSTS, constants.SSH_KNOWN_HOSTS_FILE):
      result = self.rpc.call_upload_file(dist_nodes, fname)
      for to_node, to_result in result.iteritems():
        if to_result.failed or not to_result.data:
          logging.error("Copy of file %s to node %s failed", fname, to_node)

    to_copy = []
    if constants.HT_XEN_HVM in self.cfg.GetClusterInfo().enabled_hypervisors:
      to_copy.append(constants.VNC_PASSWORD_FILE)
    for fname in to_copy:
      result = self.rpc.call_upload_file([node], fname)
      if result[node].failed or not result[node]:
        logging.error("Could not copy file %s to node %s", fname, node)

    if self.op.readd:
      self.context.ReaddNode(new_node)
    else:
      self.context.AddNode(new_node)


class LUSetNodeParams(LogicalUnit):
  """Modifies the parameters of a node.

  """
  HPATH = "node-modify"
  HTYPE = constants.HTYPE_NODE
  _OP_REQP = ["node_name"]
  REQ_BGL = False

  def CheckArguments(self):
    node_name = self.cfg.ExpandNodeName(self.op.node_name)
    if node_name is None:
      raise errors.OpPrereqError("Invalid node name '%s'" % self.op.node_name)
    self.op.node_name = node_name
    if not hasattr(self.op, 'master_candidate'):
      raise errors.OpPrereqError("Please pass at least one modification")
    self.op.master_candidate = bool(self.op.master_candidate)

  def ExpandNames(self):
    self.needed_locks = {locking.LEVEL_NODE: self.op.node_name}

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master node.

    """
    env = {
      "OP_TARGET": self.op.node_name,
      "MASTER_CANDIDATE": str(self.op.master_candidate),
      }
    nl = [self.cfg.GetMasterNode(),
          self.op.node_name]
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    force = self.force = self.op.force

    if self.op.master_candidate == False:
      if self.op.node_name == self.cfg.GetMasterNode():
        raise errors.OpPrereqError("The master node has to be a"
                                   " master candidate")
      cp_size = self.cfg.GetClusterInfo().candidate_pool_size
      node_info = self.cfg.GetAllNodesInfo().values()
      num_candidates = len([node for node in node_info
                            if node.master_candidate])
      if num_candidates <= cp_size:
        msg = ("Not enough master candidates (desired"
               " %d, new value will be %d)" % (cp_size, num_candidates-1))
        if force:
          self.LogWarning(msg)
        else:
          raise errors.OpPrereqError(msg)

    return

  def Exec(self, feedback_fn):
    """Modifies a node.

    """
    node = self.cfg.GetNodeInfo(self.op.node_name)

    result = []

    if self.op.master_candidate is not None:
      node.master_candidate = self.op.master_candidate
      result.append(("master_candidate", str(self.op.master_candidate)))
      if self.op.master_candidate == False:
        rrc = self.rpc.call_node_demote_from_mc(node.name)
        if (rrc.failed or not isinstance(rrc.data, (tuple, list))
            or len(rrc.data) != 2):
          self.LogWarning("Node rpc error: %s" % rrc.error)
        elif not rrc.data[0]:
          self.LogWarning("Node failed to demote itself: %s" % rrc.data[1])

    # this will trigger configuration file update, if needed
    self.cfg.Update(node)
    # this will trigger job queue propagation or cleanup
    if self.op.node_name != self.cfg.GetMasterNode():
      self.context.ReaddNode(node)

    return result


class LUQueryClusterInfo(NoHooksLU):
  """Query cluster configuration.

  """
  _OP_REQP = []
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def CheckPrereq(self):
    """No prerequsites needed for this LU.

    """
    pass

  def Exec(self, feedback_fn):
    """Return cluster config.

    """
    cluster = self.cfg.GetClusterInfo()
    result = {
      "software_version": constants.RELEASE_VERSION,
      "protocol_version": constants.PROTOCOL_VERSION,
      "config_version": constants.CONFIG_VERSION,
      "os_api_version": constants.OS_API_VERSION,
      "export_version": constants.EXPORT_VERSION,
      "architecture": (platform.architecture()[0], platform.machine()),
      "name": cluster.cluster_name,
      "master": cluster.master_node,
      "default_hypervisor": cluster.default_hypervisor,
      "enabled_hypervisors": cluster.enabled_hypervisors,
      "hvparams": cluster.hvparams,
      "beparams": cluster.beparams,
      "candidate_pool_size": cluster.candidate_pool_size,
      }

    return result


class LUQueryConfigValues(NoHooksLU):
  """Return configuration values.

  """
  _OP_REQP = []
  REQ_BGL = False
  _FIELDS_DYNAMIC = utils.FieldSet()
  _FIELDS_STATIC = utils.FieldSet("cluster_name", "master_node", "drain_flag")

  def ExpandNames(self):
    self.needed_locks = {}

    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

  def CheckPrereq(self):
    """No prerequisites.

    """
    pass

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
      else:
        raise errors.ParameterError(field)
      values.append(entry)
    return values


class LUActivateInstanceDisks(NoHooksLU):
  """Bring up an instance's disks.

  """
  _OP_REQP = ["instance_name"]
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
    _CheckNodeOnline(self, instance.primary_node)

  def Exec(self, feedback_fn):
    """Activate the disks.

    """
    disks_ok, disks_info = _AssembleInstanceDisks(self, self.instance)
    if not disks_ok:
      raise errors.OpExecError("Cannot activate block devices")

    return disks_info


def _AssembleInstanceDisks(lu, instance, ignore_secondaries=False):
  """Prepare the block devices for an instance.

  This sets up the block devices on all nodes.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance for whose disks we assemble
  @type ignore_secondaries: boolean
  @param ignore_secondaries: if true, errors on secondary nodes
      won't result in an error return from the function
  @return: False if the operation failed, otherwise a list of
      (host, instance_visible_name, node_visible_name)
      with the mapping from node devices to instance devices

  """
  device_info = []
  disks_ok = True
  iname = instance.name
  # With the two passes mechanism we try to reduce the window of
  # opportunity for the race condition of switching DRBD to primary
  # before handshaking occured, but we do not eliminate it

  # The proper fix would be to wait (with some limits) until the
  # connection has been made and drbd transitions from WFConnection
  # into any other network-connected state (Connected, SyncTarget,
  # SyncSource, etc.)

  # 1st pass, assemble on all nodes in secondary mode
  for inst_disk in instance.disks:
    for node, node_disk in inst_disk.ComputeNodeTree(instance.primary_node):
      lu.cfg.SetDiskID(node_disk, node)
      result = lu.rpc.call_blockdev_assemble(node, node_disk, iname, False)
      if result.failed or not result:
        lu.proc.LogWarning("Could not prepare block device %s on node %s"
                           " (is_primary=False, pass=1)",
                           inst_disk.iv_name, node)
        if not ignore_secondaries:
          disks_ok = False

  # FIXME: race condition on drbd migration to primary

  # 2nd pass, do only the primary node
  for inst_disk in instance.disks:
    for node, node_disk in inst_disk.ComputeNodeTree(instance.primary_node):
      if node != instance.primary_node:
        continue
      lu.cfg.SetDiskID(node_disk, node)
      result = lu.rpc.call_blockdev_assemble(node, node_disk, iname, True)
      if result.failed or not result:
        lu.proc.LogWarning("Could not prepare block device %s on node %s"
                           " (is_primary=True, pass=2)",
                           inst_disk.iv_name, node)
        disks_ok = False
    device_info.append((instance.primary_node, inst_disk.iv_name, result))

  # leave the disks configured for the primary node
  # this is a workaround that would be fixed better by
  # improving the logical/physical id handling
  for disk in instance.disks:
    lu.cfg.SetDiskID(disk, instance.primary_node)

  return disks_ok, device_info


def _StartInstanceDisks(lu, instance, force):
  """Start the disks of an instance.

  """
  disks_ok, dummy = _AssembleInstanceDisks(lu, instance,
                                           ignore_secondaries=force)
  if not disks_ok:
    _ShutdownInstanceDisks(lu, instance)
    if force is not None and not force:
      lu.proc.LogWarning("", hint="If the message above refers to a"
                         " secondary node,"
                         " you can retry the operation using '--force'.")
    raise errors.OpExecError("Disk consistency error")


class LUDeactivateInstanceDisks(NoHooksLU):
  """Shutdown an instance's disks.

  """
  _OP_REQP = ["instance_name"]
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
    _SafeShutdownInstanceDisks(self, instance)


def _SafeShutdownInstanceDisks(lu, instance):
  """Shutdown block devices of an instance.

  This function checks if an instance is running, before calling
  _ShutdownInstanceDisks.

  """
  ins_l = lu.rpc.call_instance_list([instance.primary_node],
                                      [instance.hypervisor])
  ins_l = ins_l[instance.primary_node]
  if ins_l.failed or not isinstance(ins_l.data, list):
    raise errors.OpExecError("Can't contact node '%s'" %
                             instance.primary_node)

  if instance.name in ins_l.data:
    raise errors.OpExecError("Instance is running, can't shutdown"
                             " block devices.")

  _ShutdownInstanceDisks(lu, instance)


def _ShutdownInstanceDisks(lu, instance, ignore_primary=False):
  """Shutdown block devices of an instance.

  This does the shutdown on all nodes of the instance.

  If the ignore_primary is false, errors on the primary node are
  ignored.

  """
  result = True
  for disk in instance.disks:
    for node, top_disk in disk.ComputeNodeTree(instance.primary_node):
      lu.cfg.SetDiskID(top_disk, node)
      result = lu.rpc.call_blockdev_shutdown(node, top_disk)
      if result.failed or not result.data:
        logging.error("Could not shutdown block device %s on node %s",
                      disk.iv_name, node)
        if not ignore_primary or node != instance.primary_node:
          result = False
  return result


def _CheckNodeFreeMemory(lu, node, reason, requested, hypervisor):
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
  @type hypervisor: C{str}
  @param hypervisor: the hypervisor to ask for memory stats
  @raise errors.OpPrereqError: if the node doesn't have enough memory, or
      we cannot check the node

  """
  nodeinfo = lu.rpc.call_node_info([node], lu.cfg.GetVGName(), hypervisor)
  nodeinfo[node].Raise()
  free_mem = nodeinfo[node].data.get('memory_free')
  if not isinstance(free_mem, int):
    raise errors.OpPrereqError("Can't compute free memory on node %s, result"
                             " was '%s'" % (node, free_mem))
  if requested > free_mem:
    raise errors.OpPrereqError("Not enough memory on node %s for %s:"
                             " needed %s MiB, available %s MiB" %
                             (node, reason, requested, free_mem))


class LUStartupInstance(LogicalUnit):
  """Starts an instance.

  """
  HPATH = "instance-start"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "force"]
  REQ_BGL = False

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
    nl = ([self.cfg.GetMasterNode(), self.instance.primary_node] +
          list(self.instance.secondary_nodes))
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    _CheckNodeOnline(self, instance.primary_node)

    bep = self.cfg.GetClusterInfo().FillBE(instance)
    # check bridges existance
    _CheckInstanceBridgesExist(self, instance)

    _CheckNodeFreeMemory(self, instance.primary_node,
                         "starting instance %s" % instance.name,
                         bep[constants.BE_MEMORY], instance.hypervisor)

  def Exec(self, feedback_fn):
    """Start the instance.

    """
    instance = self.instance
    force = self.op.force
    extra_args = getattr(self.op, "extra_args", "")

    self.cfg.MarkInstanceUp(instance.name)

    node_current = instance.primary_node

    _StartInstanceDisks(self, instance, force)

    result = self.rpc.call_instance_start(node_current, instance, extra_args)
    if result.failed or not result.data:
      _ShutdownInstanceDisks(self, instance)
      raise errors.OpExecError("Could not start instance")


class LURebootInstance(LogicalUnit):
  """Reboot an instance.

  """
  HPATH = "instance-reboot"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "ignore_secondaries", "reboot_type"]
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.reboot_type not in [constants.INSTANCE_REBOOT_SOFT,
                                   constants.INSTANCE_REBOOT_HARD,
                                   constants.INSTANCE_REBOOT_FULL]:
      raise errors.ParameterError("reboot type not in [%s, %s, %s]" %
                                  (constants.INSTANCE_REBOOT_SOFT,
                                   constants.INSTANCE_REBOOT_HARD,
                                   constants.INSTANCE_REBOOT_FULL))
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "IGNORE_SECONDARIES": self.op.ignore_secondaries,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = ([self.cfg.GetMasterNode(), self.instance.primary_node] +
          list(self.instance.secondary_nodes))
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    _CheckNodeOnline(self, instance.primary_node)

    # check bridges existance
    _CheckInstanceBridgesExist(self, instance)

  def Exec(self, feedback_fn):
    """Reboot the instance.

    """
    instance = self.instance
    ignore_secondaries = self.op.ignore_secondaries
    reboot_type = self.op.reboot_type
    extra_args = getattr(self.op, "extra_args", "")

    node_current = instance.primary_node

    if reboot_type in [constants.INSTANCE_REBOOT_SOFT,
                       constants.INSTANCE_REBOOT_HARD]:
      result = self.rpc.call_instance_reboot(node_current, instance,
                                             reboot_type, extra_args)
      if result.failed or not result.data:
        raise errors.OpExecError("Could not reboot instance")
    else:
      if not self.rpc.call_instance_shutdown(node_current, instance):
        raise errors.OpExecError("could not shutdown instance for full reboot")
      _ShutdownInstanceDisks(self, instance)
      _StartInstanceDisks(self, instance, ignore_secondaries)
      result = self.rpc.call_instance_start(node_current, instance, extra_args)
      if result.failed or not result.data:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance for full reboot")

    self.cfg.MarkInstanceUp(instance.name)


class LUShutdownInstance(LogicalUnit):
  """Shutdown an instance.

  """
  HPATH = "instance-stop"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name"]
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    nl = ([self.cfg.GetMasterNode(), self.instance.primary_node] +
          list(self.instance.secondary_nodes))
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node)

  def Exec(self, feedback_fn):
    """Shutdown the instance.

    """
    instance = self.instance
    node_current = instance.primary_node
    self.cfg.MarkInstanceDown(instance.name)
    result = self.rpc.call_instance_shutdown(node_current, instance)
    if result.failed or not result.data:
      self.proc.LogWarning("Could not shutdown instance")

    _ShutdownInstanceDisks(self, instance)


class LUReinstallInstance(LogicalUnit):
  """Reinstall an instance.

  """
  HPATH = "instance-reinstall"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name"]
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    nl = ([self.cfg.GetMasterNode(), self.instance.primary_node] +
          list(self.instance.secondary_nodes))
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
                                 self.op.instance_name)
    if instance.status != "down":
      raise errors.OpPrereqError("Instance '%s' is marked to be up" %
                                 self.op.instance_name)
    remote_info = self.rpc.call_instance_info(instance.primary_node,
                                              instance.name,
                                              instance.hypervisor)
    if remote_info.failed or remote_info.data:
      raise errors.OpPrereqError("Instance '%s' is running on the node %s" %
                                 (self.op.instance_name,
                                  instance.primary_node))

    self.op.os_type = getattr(self.op, "os_type", None)
    if self.op.os_type is not None:
      # OS verification
      pnode = self.cfg.GetNodeInfo(
        self.cfg.ExpandNodeName(instance.primary_node))
      if pnode is None:
        raise errors.OpPrereqError("Primary node '%s' is unknown" %
                                   self.op.pnode)
      result = self.rpc.call_os_get(pnode.name, self.op.os_type)
      result.Raise()
      if not isinstance(result.data, objects.OS):
        raise errors.OpPrereqError("OS '%s' not in supported OS list for"
                                   " primary node"  % self.op.os_type)

    self.instance = instance

  def Exec(self, feedback_fn):
    """Reinstall the instance.

    """
    inst = self.instance

    if self.op.os_type is not None:
      feedback_fn("Changing OS to '%s'..." % self.op.os_type)
      inst.os = self.op.os_type
      self.cfg.Update(inst)

    _StartInstanceDisks(self, inst, None)
    try:
      feedback_fn("Running the instance OS create scripts...")
      result = self.rpc.call_instance_os_add(inst.primary_node, inst)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Could not install OS for instance %s"
                                 " on node %s" %
                                 (inst.name, inst.primary_node))
    finally:
      _ShutdownInstanceDisks(self, inst)


class LURenameInstance(LogicalUnit):
  """Rename an instance.

  """
  HPATH = "instance-rename"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "new_name"]

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = _BuildInstanceHookEnvByObject(self, self.instance)
    env["INSTANCE_NEW_NAME"] = self.op.new_name
    nl = ([self.cfg.GetMasterNode(), self.instance.primary_node] +
          list(self.instance.secondary_nodes))
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(
      self.cfg.ExpandInstanceName(self.op.instance_name))
    if instance is None:
      raise errors.OpPrereqError("Instance '%s' not known" %
                                 self.op.instance_name)
    _CheckNodeOnline(self, instance.primary_node)

    if instance.status != "down":
      raise errors.OpPrereqError("Instance '%s' is marked to be up" %
                                 self.op.instance_name)
    remote_info = self.rpc.call_instance_info(instance.primary_node,
                                              instance.name,
                                              instance.hypervisor)
    remote_info.Raise()
    if remote_info.data:
      raise errors.OpPrereqError("Instance '%s' is running on the node %s" %
                                 (self.op.instance_name,
                                  instance.primary_node))
    self.instance = instance

    # new name verification
    name_info = utils.HostInfo(self.op.new_name)

    self.op.new_name = new_name = name_info.name
    instance_list = self.cfg.GetInstanceList()
    if new_name in instance_list:
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 new_name)

    if not getattr(self.op, "ignore_ip", False):
      if utils.TcpPing(name_info.ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (name_info.ip, new_name))


  def Exec(self, feedback_fn):
    """Reinstall the instance.

    """
    inst = self.instance
    old_name = inst.name

    if inst.disk_template == constants.DT_FILE:
      old_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])

    self.cfg.RenameInstance(inst.name, self.op.new_name)
    # Change the instance lock. This is definitely safe while we hold the BGL
    self.context.glm.remove(locking.LEVEL_INSTANCE, old_name)
    self.context.glm.add(locking.LEVEL_INSTANCE, self.op.new_name)

    # re-read the instance from the configuration after rename
    inst = self.cfg.GetInstanceInfo(self.op.new_name)

    if inst.disk_template == constants.DT_FILE:
      new_file_storage_dir = os.path.dirname(inst.disks[0].logical_id[1])
      result = self.rpc.call_file_storage_dir_rename(inst.primary_node,
                                                     old_file_storage_dir,
                                                     new_file_storage_dir)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Could not connect to node '%s' to rename"
                                 " directory '%s' to '%s' (but the instance"
                                 " has been renamed in Ganeti)" % (
                                 inst.primary_node, old_file_storage_dir,
                                 new_file_storage_dir))

      if not result.data[0]:
        raise errors.OpExecError("Could not rename directory '%s' to '%s'"
                                 " (but the instance has been renamed in"
                                 " Ganeti)" % (old_file_storage_dir,
                                               new_file_storage_dir))

    _StartInstanceDisks(self, inst, None)
    try:
      result = self.rpc.call_instance_run_rename(inst.primary_node, inst,
                                                 old_name)
      if result.failed or not result.data:
        msg = ("Could not run OS rename script for instance %s on node %s"
               " (but the instance has been renamed in Ganeti)" %
               (inst.name, inst.primary_node))
        self.proc.LogWarning(msg)
    finally:
      _ShutdownInstanceDisks(self, inst)


class LURemoveInstance(LogicalUnit):
  """Remove an instance.

  """
  HPATH = "instance-remove"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "ignore_failures"]
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
    nl = [self.cfg.GetMasterNode()]
    return env, nl, nl

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

    result = self.rpc.call_instance_shutdown(instance.primary_node, instance)
    if result.failed or not result.data:
      if self.op.ignore_failures:
        feedback_fn("Warning: can't shutdown instance")
      else:
        raise errors.OpExecError("Could not shutdown instance %s on node %s" %
                                 (instance.name, instance.primary_node))

    logging.info("Removing block devices for instance %s", instance.name)

    if not _RemoveDisks(self, instance):
      if self.op.ignore_failures:
        feedback_fn("Warning: can't remove instance's disks")
      else:
        raise errors.OpExecError("Can't remove instance's disks")

    logging.info("Removing instance %s out of cluster config", instance.name)

    self.cfg.RemoveInstance(instance.name)
    self.remove_locks[locking.LEVEL_INSTANCE] = instance.name


class LUQueryInstances(NoHooksLU):
  """Logical unit for querying instances.

  """
  _OP_REQP = ["output_fields", "names"]
  REQ_BGL = False
  _FIELDS_STATIC = utils.FieldSet(*["name", "os", "pnode", "snodes",
                                    "admin_state", "admin_ram",
                                    "disk_template", "ip", "mac", "bridge",
                                    "sda_size", "sdb_size", "vcpus", "tags",
                                    "network_port", "beparams",
                                    "(disk).(size)/([0-9]+)",
                                    "(disk).(sizes)",
                                    "(nic).(mac|ip|bridge)/([0-9]+)",
                                    "(nic).(macs|ips|bridges)",
                                    "(disk|nic).(count)",
                                    "serial_no", "hypervisor", "hvparams",] +
                                  ["hv/%s" % name
                                   for name in constants.HVS_PARAMETERS] +
                                  ["be/%s" % name
                                   for name in constants.BES_PARAMETERS])
  _FIELDS_DYNAMIC = utils.FieldSet("oper_state", "oper_ram", "status")


  def ExpandNames(self):
    _CheckOutputFields(static=self._FIELDS_STATIC,
                       dynamic=self._FIELDS_DYNAMIC,
                       selected=self.op.output_fields)

    self.needed_locks = {}
    self.share_locks[locking.LEVEL_INSTANCE] = 1
    self.share_locks[locking.LEVEL_NODE] = 1

    if self.op.names:
      self.wanted = _GetWantedInstances(self, self.op.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self._FIELDS_STATIC.NonMatching(self.op.output_fields)
    if self.do_locking:
      self.needed_locks[locking.LEVEL_INSTANCE] = self.wanted
      self.needed_locks[locking.LEVEL_NODE] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE and self.do_locking:
      self._LockInstancesNodes()

  def CheckPrereq(self):
    """Check prerequisites.

    """
    pass

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    all_info = self.cfg.GetAllInstancesInfo()
    if self.do_locking:
      instance_names = self.acquired_locks[locking.LEVEL_INSTANCE]
    elif self.wanted != locking.ALL_SET:
      instance_names = self.wanted
      missing = set(instance_names).difference(all_info.keys())
      if missing:
        raise errors.OpExecError(
          "Some instances were removed before retrieving their data: %s"
          % missing)
    else:
      instance_names = all_info.keys()

    instance_names = utils.NiceSort(instance_names)
    instance_list = [all_info[iname] for iname in instance_names]

    # begin data gathering

    nodes = frozenset([inst.primary_node for inst in instance_list])
    hv_list = list(set([inst.hypervisor for inst in instance_list]))

    bad_nodes = []
    off_nodes = []
    if self.do_locking:
      live_data = {}
      node_data = self.rpc.call_all_instances_info(nodes, hv_list)
      for name in nodes:
        result = node_data[name]
        if result.offline:
          # offline nodes will be in both lists
          off_nodes.append(name)
        if result.failed:
          bad_nodes.append(name)
        else:
          if result.data:
            live_data.update(result.data)
            # else no instance is alive
    else:
      live_data = dict([(name, {}) for name in instance_names])

    # end data gathering

    HVPREFIX = "hv/"
    BEPREFIX = "be/"
    output = []
    for instance in instance_list:
      iout = []
      i_hv = self.cfg.GetClusterInfo().FillHV(instance)
      i_be = self.cfg.GetClusterInfo().FillBE(instance)
      for field in self.op.output_fields:
        st_match = self._FIELDS_STATIC.Matches(field)
        if field == "name":
          val = instance.name
        elif field == "os":
          val = instance.os
        elif field == "pnode":
          val = instance.primary_node
        elif field == "snodes":
          val = list(instance.secondary_nodes)
        elif field == "admin_state":
          val = (instance.status != "down")
        elif field == "oper_state":
          if instance.primary_node in bad_nodes:
            val = None
          else:
            val = bool(live_data.get(instance.name))
        elif field == "status":
          if instance.primary_node in off_nodes:
            val = "ERROR_nodeoffline"
          elif instance.primary_node in bad_nodes:
            val = "ERROR_nodedown"
          else:
            running = bool(live_data.get(instance.name))
            if running:
              if instance.status != "down":
                val = "running"
              else:
                val = "ERROR_up"
            else:
              if instance.status != "down":
                val = "ERROR_down"
              else:
                val = "ADMIN_down"
        elif field == "oper_ram":
          if instance.primary_node in bad_nodes:
            val = None
          elif instance.name in live_data:
            val = live_data[instance.name].get("memory", "?")
          else:
            val = "-"
        elif field == "disk_template":
          val = instance.disk_template
        elif field == "ip":
          val = instance.nics[0].ip
        elif field == "bridge":
          val = instance.nics[0].bridge
        elif field == "mac":
          val = instance.nics[0].mac
        elif field == "sda_size" or field == "sdb_size":
          idx = ord(field[2]) - ord('a')
          try:
            val = instance.FindDisk(idx).size
          except errors.OpPrereqError:
            val = None
        elif field == "tags":
          val = list(instance.GetTags())
        elif field == "serial_no":
          val = instance.serial_no
        elif field == "network_port":
          val = instance.network_port
        elif field == "hypervisor":
          val = instance.hypervisor
        elif field == "hvparams":
          val = i_hv
        elif (field.startswith(HVPREFIX) and
              field[len(HVPREFIX):] in constants.HVS_PARAMETERS):
          val = i_hv.get(field[len(HVPREFIX):], None)
        elif field == "beparams":
          val = i_be
        elif (field.startswith(BEPREFIX) and
              field[len(BEPREFIX):] in constants.BES_PARAMETERS):
          val = i_be.get(field[len(BEPREFIX):], None)
        elif st_match and st_match.groups():
          # matches a variable list
          st_groups = st_match.groups()
          if st_groups and st_groups[0] == "disk":
            if st_groups[1] == "count":
              val = len(instance.disks)
            elif st_groups[1] == "sizes":
              val = [disk.size for disk in instance.disks]
            elif st_groups[1] == "size":
              try:
                val = instance.FindDisk(st_groups[2]).size
              except errors.OpPrereqError:
                val = None
            else:
              assert False, "Unhandled disk parameter"
          elif st_groups[0] == "nic":
            if st_groups[1] == "count":
              val = len(instance.nics)
            elif st_groups[1] == "macs":
              val = [nic.mac for nic in instance.nics]
            elif st_groups[1] == "ips":
              val = [nic.ip for nic in instance.nics]
            elif st_groups[1] == "bridges":
              val = [nic.bridge for nic in instance.nics]
            else:
              # index-based item
              nic_idx = int(st_groups[2])
              if nic_idx >= len(instance.nics):
                val = None
              else:
                if st_groups[1] == "mac":
                  val = instance.nics[nic_idx].mac
                elif st_groups[1] == "ip":
                  val = instance.nics[nic_idx].ip
                elif st_groups[1] == "bridge":
                  val = instance.nics[nic_idx].bridge
                else:
                  assert False, "Unhandled NIC parameter"
          else:
            assert False, "Unhandled variable parameter"
        else:
          raise errors.ParameterError(field)
        iout.append(val)
      output.append(iout)

    return output


class LUFailoverInstance(LogicalUnit):
  """Failover an instance.

  """
  HPATH = "instance-failover"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "ignore_consistency"]
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
    env = {
      "IGNORE_CONSISTENCY": self.op.ignore_consistency,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = [self.cfg.GetMasterNode()] + list(self.instance.secondary_nodes)
    return env, nl, nl

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
                                 " network mirrored, cannot failover.")

    secondary_nodes = instance.secondary_nodes
    if not secondary_nodes:
      raise errors.ProgrammerError("no secondary node but using "
                                   "a mirrored disk template")

    target_node = secondary_nodes[0]
    _CheckNodeOnline(self, target_node)
    # check memory requirements on the secondary node
    _CheckNodeFreeMemory(self, target_node, "failing over instance %s" %
                         instance.name, bep[constants.BE_MEMORY],
                         instance.hypervisor)

    # check bridge existance
    brlist = [nic.bridge for nic in instance.nics]
    result = self.rpc.call_bridges_exist(target_node, brlist)
    result.Raise()
    if not result.data:
      raise errors.OpPrereqError("One or more target bridges %s does not"
                                 " exist on destination node '%s'" %
                                 (brlist, target_node))

  def Exec(self, feedback_fn):
    """Failover an instance.

    The failover is done by shutting it down on its present node and
    starting it on the secondary.

    """
    instance = self.instance

    source_node = instance.primary_node
    target_node = instance.secondary_nodes[0]

    feedback_fn("* checking disk consistency between source and target")
    for dev in instance.disks:
      # for drbd, these are drbd over lvm
      if not _CheckDiskConsistency(self, dev, target_node, False):
        if instance.status == "up" and not self.op.ignore_consistency:
          raise errors.OpExecError("Disk %s is degraded on target node,"
                                   " aborting failover." % dev.iv_name)

    feedback_fn("* shutting down instance on source node")
    logging.info("Shutting down instance %s on node %s",
                 instance.name, source_node)

    result = self.rpc.call_instance_shutdown(source_node, instance)
    if result.failed or not result.data:
      if self.op.ignore_consistency:
        self.proc.LogWarning("Could not shutdown instance %s on node %s."
                             " Proceeding"
                             " anyway. Please make sure node %s is down",
                             instance.name, source_node, source_node)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on node %s" %
                                 (instance.name, source_node))

    feedback_fn("* deactivating the instance's disks on source node")
    if not _ShutdownInstanceDisks(self, instance, ignore_primary=True):
      raise errors.OpExecError("Can't shut down the instance's disks.")

    instance.primary_node = target_node
    # distribute new instance config to the other nodes
    self.cfg.Update(instance)

    # Only start the instance if it's marked as up
    if instance.status == "up":
      feedback_fn("* activating the instance's disks on target node")
      logging.info("Starting instance %s on node %s",
                   instance.name, target_node)

      disks_ok, dummy = _AssembleInstanceDisks(self, instance,
                                               ignore_secondaries=True)
      if not disks_ok:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      feedback_fn("* starting the instance on the target node")
      result = self.rpc.call_instance_start(target_node, instance, None)
      if result.failed or not result.data:
        _ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance %s on node %s." %
                                 (instance.name, target_node))


def _CreateBlockDevOnPrimary(lu, node, instance, device, info):
  """Create a tree of block devices on the primary node.

  This always creates all devices.

  """
  if device.children:
    for child in device.children:
      if not _CreateBlockDevOnPrimary(lu, node, instance, child, info):
        return False

  lu.cfg.SetDiskID(device, node)
  new_id = lu.rpc.call_blockdev_create(node, device, device.size,
                                       instance.name, True, info)
  if new_id.failed or not new_id.data:
    return False
  if device.physical_id is None:
    device.physical_id = new_id
  return True


def _CreateBlockDevOnSecondary(lu, node, instance, device, force, info):
  """Create a tree of block devices on a secondary node.

  If this device type has to be created on secondaries, create it and
  all its children.

  If not, just recurse to children keeping the same 'force' value.

  """
  if device.CreateOnSecondary():
    force = True
  if device.children:
    for child in device.children:
      if not _CreateBlockDevOnSecondary(lu, node, instance,
                                        child, force, info):
        return False

  if not force:
    return True
  lu.cfg.SetDiskID(device, node)
  new_id = lu.rpc.call_blockdev_create(node, device, device.size,
                                       instance.name, False, info)
  if new_id.failed or not new_id.data:
    return False
  if device.physical_id is None:
    device.physical_id = new_id
  return True


def _GenerateUniqueNames(lu, exts):
  """Generate a suitable LV name.

  This will generate a logical volume name for the given instance.

  """
  results = []
  for val in exts:
    new_id = lu.cfg.GenerateUniqueID()
    results.append("%s%s" % (new_id, val))
  return results


def _GenerateDRBD8Branch(lu, primary, secondary, size, names, iv_name,
                         p_minor, s_minor):
  """Generate a drbd8 device complete with its children.

  """
  port = lu.cfg.AllocatePort()
  vgname = lu.cfg.GetVGName()
  shared_secret = lu.cfg.GenerateDRBDSecret()
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
                          base_index):
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

    names = _GenerateUniqueNames(lu, [".disk%d" % i
                                      for i in range(disk_count)])
    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      disk_dev = objects.Disk(dev_type=constants.LD_LV, size=disk["size"],
                              logical_id=(vgname, names[idx]),
                              iv_name="disk/%d" % disk_index)
      disks.append(disk_dev)
  elif template_name == constants.DT_DRBD8:
    if len(secondary_nodes) != 1:
      raise errors.ProgrammerError("Wrong template configuration")
    remote_node = secondary_nodes[0]
    minors = lu.cfg.AllocateDRBDMinor(
      [primary_node, remote_node] * len(disk_info), instance_name)

    names = _GenerateUniqueNames(lu,
                                 [".disk%d_%s" % (i, s)
                                  for i in range(disk_count)
                                  for s in ("data", "meta")
                                  ])
    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      disk_dev = _GenerateDRBD8Branch(lu, primary_node, remote_node,
                                      disk["size"], names[idx*2:idx*2+2],
                                      "disk/%d" % disk_index,
                                      minors[idx*2], minors[idx*2+1])
      disks.append(disk_dev)
  elif template_name == constants.DT_FILE:
    if len(secondary_nodes) != 0:
      raise errors.ProgrammerError("Wrong template configuration")

    for idx, disk in enumerate(disk_info):
      disk_index = idx + base_index
      disk_dev = objects.Disk(dev_type=constants.LD_FILE, size=disk["size"],
                              iv_name="disk/%d" % disk_index,
                              logical_id=(file_driver,
                                          "%s/disk%d" % (file_storage_dir,
                                                         idx)))
      disks.append(disk_dev)
  else:
    raise errors.ProgrammerError("Invalid disk template '%s'" % template_name)
  return disks


def _GetInstanceInfoText(instance):
  """Compute that text that should be added to the disk's metadata.

  """
  return "originstname+%s" % instance.name


def _CreateDisks(lu, instance):
  """Create all disks for an instance.

  This abstracts away some work from AddInstance.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should create
  @rtype: boolean
  @return: the success of the creation

  """
  info = _GetInstanceInfoText(instance)

  if instance.disk_template == constants.DT_FILE:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    result = lu.rpc.call_file_storage_dir_create(instance.primary_node,
                                                 file_storage_dir)

    if result.failed or not result.data:
      logging.error("Could not connect to node '%s'", instance.primary_node)
      return False

    if not result.data[0]:
      logging.error("Failed to create directory '%s'", file_storage_dir)
      return False

  # Note: this needs to be kept in sync with adding of disks in
  # LUSetInstanceParams
  for device in instance.disks:
    logging.info("Creating volume %s for instance %s",
                 device.iv_name, instance.name)
    #HARDCODE
    for secondary_node in instance.secondary_nodes:
      if not _CreateBlockDevOnSecondary(lu, secondary_node, instance,
                                        device, False, info):
        logging.error("Failed to create volume %s (%s) on secondary node %s!",
                      device.iv_name, device, secondary_node)
        return False
    #HARDCODE
    if not _CreateBlockDevOnPrimary(lu, instance.primary_node,
                                    instance, device, info):
      logging.error("Failed to create volume %s on primary!", device.iv_name)
      return False

  return True


def _RemoveDisks(lu, instance):
  """Remove all disks for an instance.

  This abstracts away some work from `AddInstance()` and
  `RemoveInstance()`. Note that in case some of the devices couldn't
  be removed, the removal will continue with the other ones (compare
  with `_CreateDisks()`).

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should remove
  @rtype: boolean
  @return: the success of the removal

  """
  logging.info("Removing block devices for instance %s", instance.name)

  result = True
  for device in instance.disks:
    for node, disk in device.ComputeNodeTree(instance.primary_node):
      lu.cfg.SetDiskID(disk, node)
      result = lu.rpc.call_blockdev_remove(node, disk)
      if result.failed or not result.data:
        lu.proc.LogWarning("Could not remove block device %s on node %s,"
                           " continuing anyway", device.iv_name, node)
        result = False

  if instance.disk_template == constants.DT_FILE:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    result = lu.rpc.call_file_storage_dir_remove(instance.primary_node,
                                                 file_storage_dir)
    if result.failed or not result.data:
      logging.error("Could not remove directory '%s'", file_storage_dir)
      result = False

  return result


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
    info.Raise()
    if not info.data or not isinstance(info.data, (tuple, list)):
      raise errors.OpPrereqError("Cannot get current information"
                                 " from node '%s' (%s)" % (node, info.data))
    if not info.data[0]:
      raise errors.OpPrereqError("Hypervisor parameter validation failed:"
                                 " %s" % info.data[1])


class LUCreateInstance(LogicalUnit):
  """Create an instance.

  """
  HPATH = "instance-add"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "disks", "disk_template",
              "mode", "start",
              "wait_for_sync", "ip_check", "nics",
              "hvparams", "beparams"]
  REQ_BGL = False

  def _ExpandNode(self, node):
    """Expands and checks one node name.

    """
    node_full = self.cfg.ExpandNodeName(node)
    if node_full is None:
      raise errors.OpPrereqError("Unknown node %s" % node)
    return node_full

  def ExpandNames(self):
    """ExpandNames for CreateInstance.

    Figure out the right locks for instance creation.

    """
    self.needed_locks = {}

    # set optional parameters to none if they don't exist
    for attr in ["pnode", "snode", "iallocator", "hypervisor"]:
      if not hasattr(self.op, attr):
        setattr(self.op, attr, None)

    # cheap checks, mostly valid constants given

    # verify creation mode
    if self.op.mode not in (constants.INSTANCE_CREATE,
                            constants.INSTANCE_IMPORT):
      raise errors.OpPrereqError("Invalid instance creation mode '%s'" %
                                 self.op.mode)

    # disk template and mirror node verification
    if self.op.disk_template not in constants.DISK_TEMPLATES:
      raise errors.OpPrereqError("Invalid disk template name")

    if self.op.hypervisor is None:
      self.op.hypervisor = self.cfg.GetHypervisorType()

    cluster = self.cfg.GetClusterInfo()
    enabled_hvs = cluster.enabled_hypervisors
    if self.op.hypervisor not in enabled_hvs:
      raise errors.OpPrereqError("Selected hypervisor (%s) not enabled in the"
                                 " cluster (%s)" % (self.op.hypervisor,
                                  ",".join(enabled_hvs)))

    # check hypervisor parameter syntax (locally)

    filled_hvp = cluster.FillDict(cluster.hvparams[self.op.hypervisor],
                                  self.op.hvparams)
    hv_type = hypervisor.GetHypervisor(self.op.hypervisor)
    hv_type.CheckParameterSyntax(filled_hvp)

    # fill and remember the beparams dict
    utils.CheckBEParams(self.op.beparams)
    self.be_full = cluster.FillDict(cluster.beparams[constants.BEGR_DEFAULT],
                                    self.op.beparams)

    #### instance parameters check

    # instance name verification
    hostname1 = utils.HostInfo(self.op.instance_name)
    self.op.instance_name = instance_name = hostname1.name

    # this is just a preventive check, but someone might still add this
    # instance in the meantime, and creation will fail at lock-add time
    if instance_name in self.cfg.GetInstanceList():
      raise errors.OpPrereqError("Instance '%s' is already in the cluster" %
                                 instance_name)

    self.add_locks[locking.LEVEL_INSTANCE] = instance_name

    # NIC buildup
    self.nics = []
    for nic in self.op.nics:
      # ip validity checks
      ip = nic.get("ip", None)
      if ip is None or ip.lower() == "none":
        nic_ip = None
      elif ip.lower() == constants.VALUE_AUTO:
        nic_ip = hostname1.ip
      else:
        if not utils.IsValidIP(ip):
          raise errors.OpPrereqError("Given IP address '%s' doesn't look"
                                     " like a valid IP" % ip)
        nic_ip = ip

      # MAC address verification
      mac = nic.get("mac", constants.VALUE_AUTO)
      if mac not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        if not utils.IsValidMac(mac.lower()):
          raise errors.OpPrereqError("Invalid MAC address specified: %s" %
                                     mac)
      # bridge verification
      bridge = nic.get("bridge", self.cfg.GetDefBridge())
      self.nics.append(objects.NIC(mac=mac, ip=nic_ip, bridge=bridge))

    # disk checks/pre-build
    self.disks = []
    for disk in self.op.disks:
      mode = disk.get("mode", constants.DISK_RDWR)
      if mode not in constants.DISK_ACCESS_SET:
        raise errors.OpPrereqError("Invalid disk access mode '%s'" %
                                   mode)
      size = disk.get("size", None)
      if size is None:
        raise errors.OpPrereqError("Missing disk size")
      try:
        size = int(size)
      except ValueError:
        raise errors.OpPrereqError("Invalid disk size '%s'" % size)
      self.disks.append({"size": size, "mode": mode})

    # used in CheckPrereq for ip ping check
    self.check_ip = hostname1.ip

    # file storage checks
    if (self.op.file_driver and
        not self.op.file_driver in constants.FILE_DRIVER):
      raise errors.OpPrereqError("Invalid file driver name '%s'" %
                                 self.op.file_driver)

    if self.op.file_storage_dir and os.path.isabs(self.op.file_storage_dir):
      raise errors.OpPrereqError("File storage directory path not absolute")

    ### Node/iallocator related checks
    if [self.op.iallocator, self.op.pnode].count(None) != 1:
      raise errors.OpPrereqError("One and only one of iallocator and primary"
                                 " node must be given")

    if self.op.iallocator:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
    else:
      self.op.pnode = self._ExpandNode(self.op.pnode)
      nodelist = [self.op.pnode]
      if self.op.snode is not None:
        self.op.snode = self._ExpandNode(self.op.snode)
        nodelist.append(self.op.snode)
      self.needed_locks[locking.LEVEL_NODE] = nodelist

    # in case of import lock the source node too
    if self.op.mode == constants.INSTANCE_IMPORT:
      src_node = getattr(self.op, "src_node", None)
      src_path = getattr(self.op, "src_path", None)

      if src_path is None:
        self.op.src_path = src_path = self.op.instance_name

      if src_node is None:
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        self.op.src_node = None
        if os.path.isabs(src_path):
          raise errors.OpPrereqError("Importing an instance from an absolute"
                                     " path requires a source node option.")
      else:
        self.op.src_node = src_node = self._ExpandNode(src_node)
        if self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET:
          self.needed_locks[locking.LEVEL_NODE].append(src_node)
        if not os.path.isabs(src_path):
          self.op.src_path = src_path = \
            os.path.join(constants.EXPORT_DIR, src_path)

    else: # INSTANCE_CREATE
      if getattr(self.op, "os_type", None) is None:
        raise errors.OpPrereqError("No guest OS specified")

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    nics = [n.ToDict() for n in self.nics]
    ial = IAllocator(self,
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
                                 " iallocator '%s': %s" % (self.op.iallocator,
                                                           ial.info))
    if len(ial.nodes) != ial.required_nodes:
      raise errors.OpPrereqError("iallocator '%s' returned invalid number"
                                 " of nodes (%s), required %s" %
                                 (self.op.iallocator, len(ial.nodes),
                                  ial.required_nodes))
    self.op.pnode = ial.nodes[0]
    self.LogInfo("Selected nodes for instance %s via iallocator %s: %s",
                 self.op.instance_name, self.op.iallocator,
                 ", ".join(ial.nodes))
    if ial.required_nodes == 2:
      self.op.snode = ial.nodes[1]

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "INSTANCE_DISK_TEMPLATE": self.op.disk_template,
      "INSTANCE_DISK_SIZE": ",".join(str(d["size"]) for d in self.disks),
      "INSTANCE_ADD_MODE": self.op.mode,
      }
    if self.op.mode == constants.INSTANCE_IMPORT:
      env["INSTANCE_SRC_NODE"] = self.op.src_node
      env["INSTANCE_SRC_PATH"] = self.op.src_path
      env["INSTANCE_SRC_IMAGES"] = self.src_images

    env.update(_BuildInstanceHookEnv(name=self.op.instance_name,
      primary_node=self.op.pnode,
      secondary_nodes=self.secondaries,
      status=self.instance_status,
      os_type=self.op.os_type,
      memory=self.be_full[constants.BE_MEMORY],
      vcpus=self.be_full[constants.BE_VCPUS],
      nics=[(n.ip, n.bridge, n.mac) for n in self.nics],
    ))

    nl = ([self.cfg.GetMasterNode(), self.op.pnode] +
          self.secondaries)
    return env, nl, nl


  def CheckPrereq(self):
    """Check prerequisites.

    """
    if (not self.cfg.GetVGName() and
        self.op.disk_template not in constants.DTS_NOT_LVM):
      raise errors.OpPrereqError("Cluster does not support lvm-based"
                                 " instances")


    if self.op.mode == constants.INSTANCE_IMPORT:
      src_node = self.op.src_node
      src_path = self.op.src_path

      if src_node is None:
        exp_list = self.rpc.call_export_list(
          self.acquired_locks[locking.LEVEL_NODE])
        found = False
        for node in exp_list:
          if not exp_list[node].failed and src_path in exp_list[node].data:
            found = True
            self.op.src_node = src_node = node
            self.op.src_path = src_path = os.path.join(constants.EXPORT_DIR,
                                                       src_path)
            break
        if not found:
          raise errors.OpPrereqError("No export found for relative path %s" %
                                      src_path)

      _CheckNodeOnline(self, src_node)
      result = self.rpc.call_export_info(src_node, src_path)
      result.Raise()
      if not result.data:
        raise errors.OpPrereqError("No export found in dir %s" % src_path)

      export_info = result.data
      if not export_info.has_section(constants.INISECT_EXP):
        raise errors.ProgrammerError("Corrupted export config")

      ei_version = export_info.get(constants.INISECT_EXP, 'version')
      if (int(ei_version) != constants.EXPORT_VERSION):
        raise errors.OpPrereqError("Wrong export version %s (wanted %d)" %
                                   (ei_version, constants.EXPORT_VERSION))

      # Check that the new instance doesn't have less disks than the export
      instance_disks = len(self.disks)
      export_disks = export_info.getint(constants.INISECT_INS, 'disk_count')
      if instance_disks < export_disks:
        raise errors.OpPrereqError("Not enough disks to import."
                                   " (instance: %d, export: %d)" %
                                   (instance_disks, export_disks))

      self.op.os_type = export_info.get(constants.INISECT_EXP, 'os')
      disk_images = []
      for idx in range(export_disks):
        option = 'disk%d_dump' % idx
        if export_info.has_option(constants.INISECT_INS, option):
          # FIXME: are the old os-es, disk sizes, etc. useful?
          export_name = export_info.get(constants.INISECT_INS, option)
          image = os.path.join(src_path, export_name)
          disk_images.append(image)
        else:
          disk_images.append(False)

      self.src_images = disk_images

      old_name = export_info.get(constants.INISECT_INS, 'name')
      # FIXME: int() here could throw a ValueError on broken exports
      exp_nic_count = int(export_info.get(constants.INISECT_INS, 'nic_count'))
      if self.op.instance_name == old_name:
        for idx, nic in enumerate(self.nics):
          if nic.mac == constants.VALUE_AUTO and exp_nic_count >= idx:
            nic_mac_ini = 'nic%d_mac' % idx
            nic.mac = export_info.get(constants.INISECT_INS, nic_mac_ini)

    # ip ping checks (we use the same ip that was resolved in ExpandNames)
    if self.op.start and not self.op.ip_check:
      raise errors.OpPrereqError("Cannot ignore IP address conflicts when"
                                 " adding an instance in start mode")

    if self.op.ip_check:
      if utils.TcpPing(self.check_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                   (self.check_ip, self.op.instance_name))

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
                                 pnode.name)

    self.secondaries = []

    # mirror node verification
    if self.op.disk_template in constants.DTS_NET_MIRROR:
      if self.op.snode is None:
        raise errors.OpPrereqError("The networked disk templates need"
                                   " a mirror node")
      if self.op.snode == pnode.name:
        raise errors.OpPrereqError("The secondary node cannot be"
                                   " the primary node.")
      self.secondaries.append(self.op.snode)
      _CheckNodeOnline(self, self.op.snode)

    nodenames = [pnode.name] + self.secondaries

    req_size = _ComputeDiskSize(self.op.disk_template,
                                self.disks)

    # Check lv size requirements
    if req_size is not None:
      nodeinfo = self.rpc.call_node_info(nodenames, self.cfg.GetVGName(),
                                         self.op.hypervisor)
      for node in nodenames:
        info = nodeinfo[node]
        info.Raise()
        info = info.data
        if not info:
          raise errors.OpPrereqError("Cannot get current information"
                                     " from node '%s'" % node)
        vg_free = info.get('vg_free', None)
        if not isinstance(vg_free, int):
          raise errors.OpPrereqError("Can't compute free disk space on"
                                     " node %s" % node)
        if req_size > info['vg_free']:
          raise errors.OpPrereqError("Not enough disk space on target node %s."
                                     " %d MB available, %d MB required" %
                                     (node, info['vg_free'], req_size))

    _CheckHVParams(self, nodenames, self.op.hypervisor, self.op.hvparams)

    # os verification
    result = self.rpc.call_os_get(pnode.name, self.op.os_type)
    result.Raise()
    if not isinstance(result.data, objects.OS):
      raise errors.OpPrereqError("OS '%s' not in supported os list for"
                                 " primary node"  % self.op.os_type)

    # bridge check on primary node
    bridges = [n.bridge for n in self.nics]
    result = self.rpc.call_bridges_exist(self.pnode.name, bridges)
    result.Raise()
    if not result.data:
      raise errors.OpPrereqError("One of the target bridges '%s' does not"
                                 " exist on destination node '%s'" %
                                 (",".join(bridges), pnode.name))

    # memory check on primary node
    if self.op.start:
      _CheckNodeFreeMemory(self, self.pnode.name,
                           "creating instance %s" % self.op.instance_name,
                           self.be_full[constants.BE_MEMORY],
                           self.op.hypervisor)

    if self.op.start:
      self.instance_status = 'up'
    else:
      self.instance_status = 'down'

  def Exec(self, feedback_fn):
    """Create and add the instance to the cluster.

    """
    instance = self.op.instance_name
    pnode_name = self.pnode.name

    for nic in self.nics:
      if nic.mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
        nic.mac = self.cfg.GenerateMAC()

    ht_kind = self.op.hypervisor
    if ht_kind in constants.HTS_REQ_PORT:
      network_port = self.cfg.AllocatePort()
    else:
      network_port = None

    ##if self.op.vnc_bind_address is None:
    ##  self.op.vnc_bind_address = constants.VNC_DEFAULT_BIND_ADDRESS

    # this is needed because os.path.join does not accept None arguments
    if self.op.file_storage_dir is None:
      string_file_storage_dir = ""
    else:
      string_file_storage_dir = self.op.file_storage_dir

    # build the full file storage dir path
    file_storage_dir = os.path.normpath(os.path.join(
                                        self.cfg.GetFileStorageDir(),
                                        string_file_storage_dir, instance))


    disks = _GenerateDiskTemplate(self,
                                  self.op.disk_template,
                                  instance, pnode_name,
                                  self.secondaries,
                                  self.disks,
                                  file_storage_dir,
                                  self.op.file_driver,
                                  0)

    iobj = objects.Instance(name=instance, os=self.op.os_type,
                            primary_node=pnode_name,
                            nics=self.nics, disks=disks,
                            disk_template=self.op.disk_template,
                            status=self.instance_status,
                            network_port=network_port,
                            beparams=self.op.beparams,
                            hvparams=self.op.hvparams,
                            hypervisor=self.op.hypervisor,
                            )

    feedback_fn("* creating instance disks...")
    if not _CreateDisks(self, iobj):
      _RemoveDisks(self, iobj)
      self.cfg.ReleaseDRBDMinors(instance)
      raise errors.OpExecError("Device creation failed, reverting...")

    feedback_fn("adding instance %s to cluster config" % instance)

    self.cfg.AddInstance(iobj)
    # Declare that we don't want to remove the instance lock anymore, as we've
    # added the instance to the config
    del self.remove_locks[locking.LEVEL_INSTANCE]
    # Remove the temp. assignements for the instance's drbds
    self.cfg.ReleaseDRBDMinors(instance)
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

    feedback_fn("creating os for instance %s on node %s" %
                (instance, pnode_name))

    if iobj.disk_template != constants.DT_DISKLESS:
      if self.op.mode == constants.INSTANCE_CREATE:
        feedback_fn("* running the instance OS create scripts...")
        result = self.rpc.call_instance_os_add(pnode_name, iobj)
        result.Raise()
        if not result.data:
          raise errors.OpExecError("Could not add os for instance %s"
                                   " on node %s" %
                                   (instance, pnode_name))

      elif self.op.mode == constants.INSTANCE_IMPORT:
        feedback_fn("* running the instance OS import scripts...")
        src_node = self.op.src_node
        src_images = self.src_images
        cluster_name = self.cfg.GetClusterName()
        import_result = self.rpc.call_instance_os_import(pnode_name, iobj,
                                                         src_node, src_images,
                                                         cluster_name)
        import_result.Raise()
        for idx, result in enumerate(import_result.data):
          if not result:
            self.LogWarning("Could not import the image %s for instance"
                            " %s, disk %d, on node %s" %
                            (src_images[idx], instance, idx, pnode_name))
      else:
        # also checked in the prereq part
        raise errors.ProgrammerError("Unknown OS initialization mode '%s'"
                                     % self.op.mode)

    if self.op.start:
      logging.info("Starting instance %s on node %s", instance, pnode_name)
      feedback_fn("* starting instance...")
      result = self.rpc.call_instance_start(pnode_name, iobj, None)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Could not start instance")


class LUConnectConsole(NoHooksLU):
  """Connect to an instance's console.

  This is somewhat special in that it returns the command line that
  you need to run on the master node in order to connect to the
  console.

  """
  _OP_REQP = ["instance_name"]
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
    _CheckNodeOnline(self, self.op.primary_node)

  def Exec(self, feedback_fn):
    """Connect to the console of an instance

    """
    instance = self.instance
    node = instance.primary_node

    node_insts = self.rpc.call_instance_list([node],
                                             [instance.hypervisor])[node]
    node_insts.Raise()

    if instance.name not in node_insts.data:
      raise errors.OpExecError("Instance %s is not running." % instance.name)

    logging.debug("Connecting to console of %s on %s", instance.name, node)

    hyper = hypervisor.GetHypervisor(instance.hypervisor)
    console_cmd = hyper.GetShellCommandForConsole(instance)

    # build ssh cmdline
    return self.ssh.BuildCmd(node, "root", console_cmd, batch=True, tty=True)


class LUReplaceDisks(LogicalUnit):
  """Replace the disks of an instance.

  """
  HPATH = "mirrors-replace"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "mode", "disks"]
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    if not hasattr(self.op, "remote_node"):
      self.op.remote_node = None

    ia_name = getattr(self.op, "iallocator", None)
    if ia_name is not None:
      if self.op.remote_node is not None:
        raise errors.OpPrereqError("Give either the iallocator or the new"
                                   " secondary, not both")
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
    elif self.op.remote_node is not None:
      remote_node = self.cfg.ExpandNodeName(self.op.remote_node)
      if remote_node is None:
        raise errors.OpPrereqError("Node '%s' not known" %
                                   self.op.remote_node)
      self.op.remote_node = remote_node
      self.needed_locks[locking.LEVEL_NODE] = [remote_node]
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
    else:
      self.needed_locks[locking.LEVEL_NODE] = []
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    # If we're not already locking all nodes in the set we have to declare the
    # instance's primary/secondary nodes.
    if (level == locking.LEVEL_NODE and
        self.needed_locks[locking.LEVEL_NODE] is not locking.ALL_SET):
      self._LockInstancesNodes()

  def _RunAllocator(self):
    """Compute a new secondary node using an IAllocator.

    """
    ial = IAllocator(self,
                     mode=constants.IALLOCATOR_MODE_RELOC,
                     name=self.op.instance_name,
                     relocate_from=[self.sec_node])

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" % (self.op.iallocator,
                                                           ial.info))
    if len(ial.nodes) != ial.required_nodes:
      raise errors.OpPrereqError("iallocator '%s' returned invalid number"
                                 " of nodes (%s), required %s" %
                                 (len(ial.nodes), ial.required_nodes))
    self.op.remote_node = ial.nodes[0]
    self.LogInfo("Selected new secondary for the instance: %s",
                 self.op.remote_node)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, the primary and all the secondaries.

    """
    env = {
      "MODE": self.op.mode,
      "NEW_SECONDARY": self.op.remote_node,
      "OLD_SECONDARY": self.instance.secondary_nodes[0],
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = [
      self.cfg.GetMasterNode(),
      self.instance.primary_node,
      ]
    if self.op.remote_node is not None:
      nl.append(self.op.remote_node)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    self.instance = instance

    if instance.disk_template not in constants.DTS_NET_MIRROR:
      raise errors.OpPrereqError("Instance's disk layout is not"
                                 " network mirrored.")

    if len(instance.secondary_nodes) != 1:
      raise errors.OpPrereqError("The instance has a strange layout,"
                                 " expected one secondary but found %d" %
                                 len(instance.secondary_nodes))

    self.sec_node = instance.secondary_nodes[0]

    ia_name = getattr(self.op, "iallocator", None)
    if ia_name is not None:
      self._RunAllocator()

    remote_node = self.op.remote_node
    if remote_node is not None:
      self.remote_node_info = self.cfg.GetNodeInfo(remote_node)
      assert self.remote_node_info is not None, \
        "Cannot retrieve locked node %s" % remote_node
    else:
      self.remote_node_info = None
    if remote_node == instance.primary_node:
      raise errors.OpPrereqError("The specified node is the primary node of"
                                 " the instance.")
    elif remote_node == self.sec_node:
      if self.op.mode == constants.REPLACE_DISK_SEC:
        # this is for DRBD8, where we can't execute the same mode of
        # replacement as for drbd7 (no different port allocated)
        raise errors.OpPrereqError("Same secondary given, cannot execute"
                                   " replacement")
    if instance.disk_template == constants.DT_DRBD8:
      if (self.op.mode == constants.REPLACE_DISK_ALL and
          remote_node is not None):
        # switch to replace secondary mode
        self.op.mode = constants.REPLACE_DISK_SEC

      if self.op.mode == constants.REPLACE_DISK_ALL:
        raise errors.OpPrereqError("Template 'drbd' only allows primary or"
                                   " secondary disk replacement, not"
                                   " both at once")
      elif self.op.mode == constants.REPLACE_DISK_PRI:
        if remote_node is not None:
          raise errors.OpPrereqError("Template 'drbd' does not allow changing"
                                     " the secondary while doing a primary"
                                     " node disk replacement")
        self.tgt_node = instance.primary_node
        self.oth_node = instance.secondary_nodes[0]
        _CheckNodeOnline(self, self.tgt_node)
        _CheckNodeOnline(self, self.oth_node)
      elif self.op.mode == constants.REPLACE_DISK_SEC:
        self.new_node = remote_node # this can be None, in which case
                                    # we don't change the secondary
        self.tgt_node = instance.secondary_nodes[0]
        self.oth_node = instance.primary_node
        _CheckNodeOnline(self, self.oth_node)
        if self.new_node is not None:
          _CheckNodeOnline(self, self.new_node)
        else:
          _CheckNodeOnline(self, self.tgt_node)
      else:
        raise errors.ProgrammerError("Unhandled disk replace mode")

    if not self.op.disks:
      self.op.disks = range(len(instance.disks))

    for disk_idx in self.op.disks:
      instance.FindDisk(disk_idx)

  def _ExecD8DiskOnly(self, feedback_fn):
    """Replace a disk on the primary or secondary for dbrd8.

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
    warning, info = (self.proc.LogWarning, self.proc.LogInfo)
    instance = self.instance
    iv_names = {}
    vgname = self.cfg.GetVGName()
    # start of work
    cfg = self.cfg
    tgt_node = self.tgt_node
    oth_node = self.oth_node

    # Step: check device activation
    self.proc.LogStep(1, steps_total, "check device existence")
    info("checking volume groups")
    my_vg = cfg.GetVGName()
    results = self.rpc.call_vg_list([oth_node, tgt_node])
    if not results:
      raise errors.OpExecError("Can't list volume groups on the nodes")
    for node in oth_node, tgt_node:
      res = results[node]
      if res.failed or not res.data or my_vg not in res.data:
        raise errors.OpExecError("Volume group '%s' not found on %s" %
                                 (my_vg, node))
    for idx, dev in enumerate(instance.disks):
      if idx not in self.op.disks:
        continue
      for node in tgt_node, oth_node:
        info("checking disk/%d on %s" % (idx, node))
        cfg.SetDiskID(dev, node)
        if not self.rpc.call_blockdev_find(node, dev):
          raise errors.OpExecError("Can't find disk/%d on node %s" %
                                   (idx, node))

    # Step: check other node consistency
    self.proc.LogStep(2, steps_total, "check peer consistency")
    for idx, dev in enumerate(instance.disks):
      if idx not in self.op.disks:
        continue
      info("checking disk/%d consistency on %s" % (idx, oth_node))
      if not _CheckDiskConsistency(self, dev, oth_node,
                                   oth_node==instance.primary_node):
        raise errors.OpExecError("Peer node (%s) has degraded storage, unsafe"
                                 " to replace disks on this node (%s)" %
                                 (oth_node, tgt_node))

    # Step: create new storage
    self.proc.LogStep(3, steps_total, "allocate new storage")
    for idx, dev in enumerate(instance.disks):
      if idx not in self.op.disks:
        continue
      size = dev.size
      cfg.SetDiskID(dev, tgt_node)
      lv_names = [".disk%d_%s" % (idx, suf)
                  for suf in ["data", "meta"]]
      names = _GenerateUniqueNames(self, lv_names)
      lv_data = objects.Disk(dev_type=constants.LD_LV, size=size,
                             logical_id=(vgname, names[0]))
      lv_meta = objects.Disk(dev_type=constants.LD_LV, size=128,
                             logical_id=(vgname, names[1]))
      new_lvs = [lv_data, lv_meta]
      old_lvs = dev.children
      iv_names[dev.iv_name] = (dev, old_lvs, new_lvs)
      info("creating new local storage on %s for %s" %
           (tgt_node, dev.iv_name))
      # since we *always* want to create this LV, we use the
      # _Create...OnPrimary (which forces the creation), even if we
      # are talking about the secondary node
      for new_lv in new_lvs:
        if not _CreateBlockDevOnPrimary(self, tgt_node, instance, new_lv,
                                        _GetInstanceInfoText(instance)):
          raise errors.OpExecError("Failed to create new LV named '%s' on"
                                   " node '%s'" %
                                   (new_lv.logical_id[1], tgt_node))

    # Step: for each lv, detach+rename*2+attach
    self.proc.LogStep(4, steps_total, "change drbd configuration")
    for dev, old_lvs, new_lvs in iv_names.itervalues():
      info("detaching %s drbd from local storage" % dev.iv_name)
      result = self.rpc.call_blockdev_removechildren(tgt_node, dev, old_lvs)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Can't detach drbd from local storage on node"
                                 " %s for device %s" % (tgt_node, dev.iv_name))
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
      # build the rename list based on what LVs exist on the node
      rlist = []
      for to_ren in old_lvs:
        find_res = self.rpc.call_blockdev_find(tgt_node, to_ren)
        if not find_res.failed and find_res.data is not None: # device exists
          rlist.append((to_ren, ren_fn(to_ren, temp_suffix)))

      info("renaming the old LVs on the target node")
      result = self.rpc.call_blockdev_rename(tgt_node, rlist)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Can't rename old LVs on node %s" % tgt_node)
      # now we rename the new LVs to the old LVs
      info("renaming the new LVs on the target node")
      rlist = [(new, old.physical_id) for old, new in zip(old_lvs, new_lvs)]
      result = self.rpc.call_blockdev_rename(tgt_node, rlist)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Can't rename new LVs on node %s" % tgt_node)

      for old, new in zip(old_lvs, new_lvs):
        new.logical_id = old.logical_id
        cfg.SetDiskID(new, tgt_node)

      for disk in old_lvs:
        disk.logical_id = ren_fn(disk, temp_suffix)
        cfg.SetDiskID(disk, tgt_node)

      # now that the new lvs have the old name, we can add them to the device
      info("adding new mirror component on %s" % tgt_node)
      result =self.rpc.call_blockdev_addchildren(tgt_node, dev, new_lvs)
      if result.failed or not result.data:
        for new_lv in new_lvs:
          result = self.rpc.call_blockdev_remove(tgt_node, new_lv)
          if result.failed or not result.data:
            warning("Can't rollback device %s", hint="manually cleanup unused"
                    " logical volumes")
        raise errors.OpExecError("Can't add local storage to drbd")

      dev.children = new_lvs
      cfg.Update(instance)

    # Step: wait for sync

    # this can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its
    # return value
    self.proc.LogStep(5, steps_total, "sync devices")
    _WaitForSync(self, instance, unlock=True)

    # so check manually all the devices
    for name, (dev, old_lvs, new_lvs) in iv_names.iteritems():
      cfg.SetDiskID(dev, instance.primary_node)
      result = self.rpc.call_blockdev_find(instance.primary_node, dev)
      if result.failed or result.data[5]:
        raise errors.OpExecError("DRBD device %s is degraded!" % name)

    # Step: remove old storage
    self.proc.LogStep(6, steps_total, "removing old storage")
    for name, (dev, old_lvs, new_lvs) in iv_names.iteritems():
      info("remove logical volumes for %s" % name)
      for lv in old_lvs:
        cfg.SetDiskID(lv, tgt_node)
        result = self.rpc.call_blockdev_remove(tgt_node, lv)
        if result.failed or not result.data:
          warning("Can't remove old LV", hint="manually remove unused LVs")
          continue

  def _ExecD8Secondary(self, feedback_fn):
    """Replace the secondary node for drbd8.

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
    warning, info = (self.proc.LogWarning, self.proc.LogInfo)
    instance = self.instance
    iv_names = {}
    vgname = self.cfg.GetVGName()
    # start of work
    cfg = self.cfg
    old_node = self.tgt_node
    new_node = self.new_node
    pri_node = instance.primary_node

    # Step: check device activation
    self.proc.LogStep(1, steps_total, "check device existence")
    info("checking volume groups")
    my_vg = cfg.GetVGName()
    results = self.rpc.call_vg_list([pri_node, new_node])
    for node in pri_node, new_node:
      res = results[node]
      if res.failed or not res.data or my_vg not in res.data:
        raise errors.OpExecError("Volume group '%s' not found on %s" %
                                 (my_vg, node))
    for idx, dev in enumerate(instance.disks):
      if idx not in self.op.disks:
        continue
      info("checking disk/%d on %s" % (idx, pri_node))
      cfg.SetDiskID(dev, pri_node)
      result = self.rpc.call_blockdev_find(pri_node, dev)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Can't find disk/%d on node %s" %
                                 (idx, pri_node))

    # Step: check other node consistency
    self.proc.LogStep(2, steps_total, "check peer consistency")
    for idx, dev in enumerate(instance.disks):
      if idx not in self.op.disks:
        continue
      info("checking disk/%d consistency on %s" % (idx, pri_node))
      if not _CheckDiskConsistency(self, dev, pri_node, True, ldisk=True):
        raise errors.OpExecError("Primary node (%s) has degraded storage,"
                                 " unsafe to replace the secondary" %
                                 pri_node)

    # Step: create new storage
    self.proc.LogStep(3, steps_total, "allocate new storage")
    for idx, dev in enumerate(instance.disks):
      size = dev.size
      info("adding new local storage on %s for disk/%d" %
           (new_node, idx))
      # since we *always* want to create this LV, we use the
      # _Create...OnPrimary (which forces the creation), even if we
      # are talking about the secondary node
      for new_lv in dev.children:
        if not _CreateBlockDevOnPrimary(self, new_node, instance, new_lv,
                                        _GetInstanceInfoText(instance)):
          raise errors.OpExecError("Failed to create new LV named '%s' on"
                                   " node '%s'" %
                                   (new_lv.logical_id[1], new_node))

    # Step 4: dbrd minors and drbd setups changes
    # after this, we must manually remove the drbd minors on both the
    # error and the success paths
    minors = cfg.AllocateDRBDMinor([new_node for dev in instance.disks],
                                   instance.name)
    logging.debug("Allocated minors %s" % (minors,))
    self.proc.LogStep(4, steps_total, "changing drbd configuration")
    for idx, (dev, new_minor) in enumerate(zip(instance.disks, minors)):
      size = dev.size
      info("activating a new drbd on %s for disk/%d" % (new_node, idx))
      # create new devices on new_node
      if pri_node == dev.logical_id[0]:
        new_logical_id = (pri_node, new_node,
                          dev.logical_id[2], dev.logical_id[3], new_minor,
                          dev.logical_id[5])
      else:
        new_logical_id = (new_node, pri_node,
                          dev.logical_id[2], new_minor, dev.logical_id[4],
                          dev.logical_id[5])
      iv_names[idx] = (dev, dev.children, new_logical_id)
      logging.debug("Allocated new_minor: %s, new_logical_id: %s", new_minor,
                    new_logical_id)
      new_drbd = objects.Disk(dev_type=constants.LD_DRBD8,
                              logical_id=new_logical_id,
                              children=dev.children)
      if not _CreateBlockDevOnSecondary(self, new_node, instance,
                                        new_drbd, False,
                                        _GetInstanceInfoText(instance)):
        self.cfg.ReleaseDRBDMinors(instance.name)
        raise errors.OpExecError("Failed to create new DRBD on"
                                 " node '%s'" % new_node)

    for idx, dev in enumerate(instance.disks):
      # we have new devices, shutdown the drbd on the old secondary
      info("shutting down drbd for disk/%d on old node" % idx)
      cfg.SetDiskID(dev, old_node)
      result = self.rpc.call_blockdev_shutdown(old_node, dev)
      if result.failed or not result.data:
        warning("Failed to shutdown drbd for disk/%d on old node" % idx,
                hint="Please cleanup this device manually as soon as possible")

    info("detaching primary drbds from the network (=> standalone)")
    done = 0
    for idx, dev in enumerate(instance.disks):
      cfg.SetDiskID(dev, pri_node)
      # set the network part of the physical (unique in bdev terms) id
      # to None, meaning detach from network
      dev.physical_id = (None, None, None, None) + dev.physical_id[4:]
      # and 'find' the device, which will 'fix' it to match the
      # standalone state
      result = self.rpc.call_blockdev_find(pri_node, dev)
      if not result.failed and result.data:
        done += 1
      else:
        warning("Failed to detach drbd disk/%d from network, unusual case" %
                idx)

    if not done:
      # no detaches succeeded (very unlikely)
      self.cfg.ReleaseDRBDMinors(instance.name)
      raise errors.OpExecError("Can't detach at least one DRBD from old node")

    # if we managed to detach at least one, we update all the disks of
    # the instance to point to the new secondary
    info("updating instance configuration")
    for dev, _, new_logical_id in iv_names.itervalues():
      dev.logical_id = new_logical_id
      cfg.SetDiskID(dev, pri_node)
    cfg.Update(instance)
    # we can remove now the temp minors as now the new values are
    # written to the config file (and therefore stable)
    self.cfg.ReleaseDRBDMinors(instance.name)

    # and now perform the drbd attach
    info("attaching primary drbds to new secondary (standalone => connected)")
    failures = []
    for idx, dev in enumerate(instance.disks):
      info("attaching primary drbd for disk/%d to new secondary node" % idx)
      # since the attach is smart, it's enough to 'find' the device,
      # it will automatically activate the network, if the physical_id
      # is correct
      cfg.SetDiskID(dev, pri_node)
      logging.debug("Disk to attach: %s", dev)
      result = self.rpc.call_blockdev_find(pri_node, dev)
      if result.failed or not result.data:
        warning("can't attach drbd disk/%d to new secondary!" % idx,
                "please do a gnt-instance info to see the status of disks")

    # this can fail as the old devices are degraded and _WaitForSync
    # does a combined result over all disks, so we don't check its
    # return value
    self.proc.LogStep(5, steps_total, "sync devices")
    _WaitForSync(self, instance, unlock=True)

    # so check manually all the devices
    for idx, (dev, old_lvs, _) in iv_names.iteritems():
      cfg.SetDiskID(dev, pri_node)
      result = self.rpc.call_blockdev_find(pri_node, dev)
      result.Raise()
      if result.data[5]:
        raise errors.OpExecError("DRBD device disk/%d is degraded!" % idx)

    self.proc.LogStep(6, steps_total, "removing old storage")
    for idx, (dev, old_lvs, _) in iv_names.iteritems():
      info("remove logical volumes for disk/%d" % idx)
      for lv in old_lvs:
        cfg.SetDiskID(lv, old_node)
        result = self.rpc.call_blockdev_remove(old_node, lv)
        if result.failed or not result.data:
          warning("Can't remove LV on old secondary",
                  hint="Cleanup stale volumes by hand")

  def Exec(self, feedback_fn):
    """Execute disk replacement.

    This dispatches the disk replacement to the appropriate handler.

    """
    instance = self.instance

    # Activate the instance disks if we're replacing them on a down instance
    if instance.status == "down":
      _StartInstanceDisks(self, instance, True)

    if instance.disk_template == constants.DT_DRBD8:
      if self.op.remote_node is None:
        fn = self._ExecD8DiskOnly
      else:
        fn = self._ExecD8Secondary
    else:
      raise errors.ProgrammerError("Unhandled disk replacement case")

    ret = fn(feedback_fn)

    # Deactivate the instance disks if we're replacing them on a down instance
    if instance.status == "down":
      _SafeShutdownInstanceDisks(self, instance)

    return ret


class LUGrowDisk(LogicalUnit):
  """Grow a disk of an instance.

  """
  HPATH = "disk-grow"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "disk", "amount", "wait_for_sync"]
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
    nl = [
      self.cfg.GetMasterNode(),
      self.instance.primary_node,
      ]
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node)
    for node in instance.secondary_nodes:
      _CheckNodeOnline(self, node)


    self.instance = instance

    if instance.disk_template not in (constants.DT_PLAIN, constants.DT_DRBD8):
      raise errors.OpPrereqError("Instance's disk layout does not support"
                                 " growing.")

    self.disk = instance.FindDisk(self.op.disk)

    nodenames = [instance.primary_node] + list(instance.secondary_nodes)
    nodeinfo = self.rpc.call_node_info(nodenames, self.cfg.GetVGName(),
                                       instance.hypervisor)
    for node in nodenames:
      info = nodeinfo[node]
      if info.failed or not info.data:
        raise errors.OpPrereqError("Cannot get current information"
                                   " from node '%s'" % node)
      vg_free = info.data.get('vg_free', None)
      if not isinstance(vg_free, int):
        raise errors.OpPrereqError("Can't compute free disk space on"
                                   " node %s" % node)
      if self.op.amount > vg_free:
        raise errors.OpPrereqError("Not enough disk space on target node %s:"
                                   " %d MiB available, %d MiB required" %
                                   (node, vg_free, self.op.amount))

  def Exec(self, feedback_fn):
    """Execute disk grow.

    """
    instance = self.instance
    disk = self.disk
    for node in (instance.secondary_nodes + (instance.primary_node,)):
      self.cfg.SetDiskID(disk, node)
      result = self.rpc.call_blockdev_grow(node, disk, self.op.amount)
      result.Raise()
      if (not result.data or not isinstance(result.data, (list, tuple)) or
          len(result.data) != 2):
        raise errors.OpExecError("Grow request failed to node %s" % node)
      elif not result.data[0]:
        raise errors.OpExecError("Grow request failed to node %s: %s" %
                                 (node, result.data[1]))
    disk.RecordGrow(self.op.amount)
    self.cfg.Update(instance)
    if self.op.wait_for_sync:
      disk_abort = not _WaitForSync(self, instance)
      if disk_abort:
        self.proc.LogWarning("Warning: disk sync-ing has not returned a good"
                             " status.\nPlease check the instance.")


class LUQueryInstanceData(NoHooksLU):
  """Query runtime instance data.

  """
  _OP_REQP = ["instances", "static"]
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}
    self.share_locks = dict(((i, 1) for i in locking.LEVELS))

    if not isinstance(self.op.instances, list):
      raise errors.OpPrereqError("Invalid argument type 'instances'")

    if self.op.instances:
      self.wanted_names = []
      for name in self.op.instances:
        full_name = self.cfg.ExpandInstanceName(name)
        if full_name is None:
          raise errors.OpPrereqError("Instance '%s' not known" %
                                     self.op.instance_name)
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
    return

  def _ComputeDiskStatus(self, instance, snode, dev):
    """Compute block device status.

    """
    static = self.op.static
    if not static:
      self.cfg.SetDiskID(dev, instance.primary_node)
      dev_pstatus = self.rpc.call_blockdev_find(instance.primary_node, dev)
      dev_pstatus.Raise()
      dev_pstatus = dev_pstatus.data
    else:
      dev_pstatus = None

    if dev.dev_type in constants.LDS_DRBD:
      # we change the snode then (otherwise we use the one passed in)
      if dev.logical_id[0] == instance.primary_node:
        snode = dev.logical_id[1]
      else:
        snode = dev.logical_id[0]

    if snode and not static:
      self.cfg.SetDiskID(dev, snode)
      dev_sstatus = self.rpc.call_blockdev_find(snode, dev)
      dev_sstatus.Raise()
      dev_sstatus = dev_sstatus.data
    else:
      dev_sstatus = None

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
        remote_info.Raise()
        remote_info = remote_info.data
        if remote_info and "state" in remote_info:
          remote_state = "up"
        else:
          remote_state = "down"
      else:
        remote_state = None
      if instance.status == "down":
        config_state = "down"
      else:
        config_state = "up"

      disks = [self._ComputeDiskStatus(instance, None, device)
               for device in instance.disks]

      idict = {
        "name": instance.name,
        "config_state": config_state,
        "run_state": remote_state,
        "pnode": instance.primary_node,
        "snodes": instance.secondary_nodes,
        "os": instance.os,
        "nics": [(nic.mac, nic.ip, nic.bridge) for nic in instance.nics],
        "disks": disks,
        "hypervisor": instance.hypervisor,
        "network_port": instance.network_port,
        "hv_instance": instance.hvparams,
        "hv_actual": cluster.FillHV(instance),
        "be_instance": instance.beparams,
        "be_actual": cluster.FillBE(instance),
        }

      result[instance.name] = idict

    return result


class LUSetInstanceParams(LogicalUnit):
  """Modifies an instances's parameters.

  """
  HPATH = "instance-modify"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name"]
  REQ_BGL = False

  def CheckArguments(self):
    if not hasattr(self.op, 'nics'):
      self.op.nics = []
    if not hasattr(self.op, 'disks'):
      self.op.disks = []
    if not hasattr(self.op, 'beparams'):
      self.op.beparams = {}
    if not hasattr(self.op, 'hvparams'):
      self.op.hvparams = {}
    self.op.force = getattr(self.op, "force", False)
    if not (self.op.nics or self.op.disks or
            self.op.hvparams or self.op.beparams):
      raise errors.OpPrereqError("No changes submitted")

    utils.CheckBEParams(self.op.beparams)

    # Disk validation
    disk_addremove = 0
    for disk_op, disk_dict in self.op.disks:
      if disk_op == constants.DDM_REMOVE:
        disk_addremove += 1
        continue
      elif disk_op == constants.DDM_ADD:
        disk_addremove += 1
      else:
        if not isinstance(disk_op, int):
          raise errors.OpPrereqError("Invalid disk index")
      if disk_op == constants.DDM_ADD:
        mode = disk_dict.setdefault('mode', constants.DISK_RDWR)
        if mode not in (constants.DISK_RDONLY, constants.DISK_RDWR):
          raise errors.OpPrereqError("Invalid disk access mode '%s'" % mode)
        size = disk_dict.get('size', None)
        if size is None:
          raise errors.OpPrereqError("Required disk parameter size missing")
        try:
          size = int(size)
        except ValueError, err:
          raise errors.OpPrereqError("Invalid disk size parameter: %s" %
                                     str(err))
        disk_dict['size'] = size
      else:
        # modification of disk
        if 'size' in disk_dict:
          raise errors.OpPrereqError("Disk size change not possible, use"
                                     " grow-disk")

    if disk_addremove > 1:
      raise errors.OpPrereqError("Only one disk add or remove operation"
                                 " supported at a time")

    # NIC validation
    nic_addremove = 0
    for nic_op, nic_dict in self.op.nics:
      if nic_op == constants.DDM_REMOVE:
        nic_addremove += 1
        continue
      elif nic_op == constants.DDM_ADD:
        nic_addremove += 1
      else:
        if not isinstance(nic_op, int):
          raise errors.OpPrereqError("Invalid nic index")

      # nic_dict should be a dict
      nic_ip = nic_dict.get('ip', None)
      if nic_ip is not None:
        if nic_ip.lower() == "none":
          nic_dict['ip'] = None
        else:
          if not utils.IsValidIP(nic_ip):
            raise errors.OpPrereqError("Invalid IP address '%s'" % nic_ip)
      # we can only check None bridges and assign the default one
      nic_bridge = nic_dict.get('bridge', None)
      if nic_bridge is None:
        nic_dict['bridge'] = self.cfg.GetDefBridge()
      # but we can validate MACs
      nic_mac = nic_dict.get('mac', None)
      if nic_mac is not None:
        if self.cfg.IsMacInUse(nic_mac):
          raise errors.OpPrereqError("MAC address %s already in use"
                                     " in cluster" % nic_mac)
        if nic_mac not in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
          if not utils.IsValidMac(nic_mac):
            raise errors.OpPrereqError("Invalid MAC address %s" % nic_mac)
    if nic_addremove > 1:
      raise errors.OpPrereqError("Only one NIC add or remove operation"
                                 " supported at a time")

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.needed_locks[locking.LEVEL_NODE] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on the master, primary and secondaries.

    """
    args = dict()
    if constants.BE_MEMORY in self.be_new:
      args['memory'] = self.be_new[constants.BE_MEMORY]
    if constants.BE_VCPUS in self.be_new:
      args['vcpus'] = self.be_new[constants.BE_VCPUS]
    # FIXME: readd disk/nic changes
    env = _BuildInstanceHookEnvByObject(self, self.instance, override=args)
    nl = [self.cfg.GetMasterNode(),
          self.instance.primary_node] + list(self.instance.secondary_nodes)
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    force = self.force = self.op.force

    # checking the new params on the primary/secondary nodes

    instance = self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    pnode = self.instance.primary_node
    nodelist = [pnode]
    nodelist.extend(instance.secondary_nodes)

    # hvparams processing
    if self.op.hvparams:
      i_hvdict = copy.deepcopy(instance.hvparams)
      for key, val in self.op.hvparams.iteritems():
        if val == constants.VALUE_DEFAULT:
          try:
            del i_hvdict[key]
          except KeyError:
            pass
        elif val == constants.VALUE_NONE:
          i_hvdict[key] = None
        else:
          i_hvdict[key] = val
      cluster = self.cfg.GetClusterInfo()
      hv_new = cluster.FillDict(cluster.hvparams[instance.hypervisor],
                                i_hvdict)
      # local check
      hypervisor.GetHypervisor(
        instance.hypervisor).CheckParameterSyntax(hv_new)
      _CheckHVParams(self, nodelist, instance.hypervisor, hv_new)
      self.hv_new = hv_new # the new actual values
      self.hv_inst = i_hvdict # the new dict (without defaults)
    else:
      self.hv_new = self.hv_inst = {}

    # beparams processing
    if self.op.beparams:
      i_bedict = copy.deepcopy(instance.beparams)
      for key, val in self.op.beparams.iteritems():
        if val == constants.VALUE_DEFAULT:
          try:
            del i_bedict[key]
          except KeyError:
            pass
        else:
          i_bedict[key] = val
      cluster = self.cfg.GetClusterInfo()
      be_new = cluster.FillDict(cluster.beparams[constants.BEGR_DEFAULT],
                                i_bedict)
      self.be_new = be_new # the new actual values
      self.be_inst = i_bedict # the new dict (without defaults)
    else:
      self.be_new = self.be_inst = {}

    self.warn = []

    if constants.BE_MEMORY in self.op.beparams and not self.force:
      mem_check_list = [pnode]
      if be_new[constants.BE_AUTO_BALANCE]:
        # either we changed auto_balance to yes or it was from before
        mem_check_list.extend(instance.secondary_nodes)
      instance_info = self.rpc.call_instance_info(pnode, instance.name,
                                                  instance.hypervisor)
      nodeinfo = self.rpc.call_node_info(mem_check_list, self.cfg.GetVGName(),
                                         instance.hypervisor)
      if nodeinfo[pnode].failed or not isinstance(nodeinfo[pnode].data, dict):
        # Assume the primary node is unreachable and go ahead
        self.warn.append("Can't get info from primary node %s" % pnode)
      else:
        if not instance_info.failed and instance_info.data:
          current_mem = instance_info.data['memory']
        else:
          # Assume instance not running
          # (there is a slight race condition here, but it's not very probable,
          # and we have no other way to check)
          current_mem = 0
        miss_mem = (be_new[constants.BE_MEMORY] - current_mem -
                    nodeinfo[pnode].data['memory_free'])
        if miss_mem > 0:
          raise errors.OpPrereqError("This change will prevent the instance"
                                     " from starting, due to %d MB of memory"
                                     " missing on its primary node" % miss_mem)

      if be_new[constants.BE_AUTO_BALANCE]:
        for node, nres in instance.secondary_nodes.iteritems():
          if nres.failed or not isinstance(nres.data, dict):
            self.warn.append("Can't get info from secondary node %s" % node)
          elif be_new[constants.BE_MEMORY] > nres.data['memory_free']:
            self.warn.append("Not enough memory to failover instance to"
                             " secondary node %s" % node)

    # NIC processing
    for nic_op, nic_dict in self.op.nics:
      if nic_op == constants.DDM_REMOVE:
        if not instance.nics:
          raise errors.OpPrereqError("Instance has no NICs, cannot remove")
        continue
      if nic_op != constants.DDM_ADD:
        # an existing nic
        if nic_op < 0 or nic_op >= len(instance.nics):
          raise errors.OpPrereqError("Invalid NIC index %s, valid values"
                                     " are 0 to %d" %
                                     (nic_op, len(instance.nics)))
      nic_bridge = nic_dict.get('bridge', None)
      if nic_bridge is not None:
        if not self.rpc.call_bridges_exist(pnode, [nic_bridge]):
          msg = ("Bridge '%s' doesn't exist on one of"
                 " the instance nodes" % nic_bridge)
          if self.force:
            self.warn.append(msg)
          else:
            raise errors.OpPrereqError(msg)

    # DISK processing
    if self.op.disks and instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Disk operations not supported for"
                                 " diskless instances")
    for disk_op, disk_dict in self.op.disks:
      if disk_op == constants.DDM_REMOVE:
        if len(instance.disks) == 1:
          raise errors.OpPrereqError("Cannot remove the last disk of"
                                     " an instance")
        ins_l = self.rpc.call_instance_list([pnode], [instance.hypervisor])
        ins_l = ins_l[pnode]
        if not type(ins_l) is list:
          raise errors.OpPrereqError("Can't contact node '%s'" % pnode)
        if instance.name in ins_l:
          raise errors.OpPrereqError("Instance is running, can't remove"
                                     " disks.")

      if (disk_op == constants.DDM_ADD and
          len(instance.nics) >= constants.MAX_DISKS):
        raise errors.OpPrereqError("Instance has too many disks (%d), cannot"
                                   " add more" % constants.MAX_DISKS)
      if disk_op not in (constants.DDM_ADD, constants.DDM_REMOVE):
        # an existing disk
        if disk_op < 0 or disk_op >= len(instance.disks):
          raise errors.OpPrereqError("Invalid disk index %s, valid values"
                                     " are 0 to %d" %
                                     (disk_op, len(instance.disks)))

    return

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
          result = self.rpc.call_blockdev_remove(node, disk)
          if result.failed or not result.data:
            self.proc.LogWarning("Could not remove disk/%d on node %s,"
                                 " continuing anyway", device_idx, node)
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
                                         instance, instance.primary_node,
                                         instance.secondary_nodes,
                                         [disk_dict],
                                         file_path,
                                         file_driver,
                                         disk_idx_base)[0]
        new_disk.mode = disk_dict['mode']
        instance.disks.append(new_disk)
        info = _GetInstanceInfoText(instance)

        logging.info("Creating volume %s for instance %s",
                     new_disk.iv_name, instance.name)
        # Note: this needs to be kept in sync with _CreateDisks
        #HARDCODE
        for secondary_node in instance.secondary_nodes:
          if not _CreateBlockDevOnSecondary(self, secondary_node, instance,
                                            new_disk, False, info):
            self.LogWarning("Failed to create volume %s (%s) on"
                            " secondary node %s!",
                            new_disk.iv_name, new_disk, secondary_node)
        #HARDCODE
        if not _CreateBlockDevOnPrimary(self, instance.primary_node,
                                        instance, new_disk, info):
          self.LogWarning("Failed to create volume %s on primary!",
                          new_disk.iv_name)
        result.append(("disk/%d" % disk_idx_base, "add:size=%s,mode=%s" %
                       (new_disk.size, new_disk.mode)))
      else:
        # change a given disk
        instance.disks[disk_op].mode = disk_dict['mode']
        result.append(("disk.mode/%d" % disk_op, disk_dict['mode']))
    # NIC changes
    for nic_op, nic_dict in self.op.nics:
      if nic_op == constants.DDM_REMOVE:
        # remove the last nic
        del instance.nics[-1]
        result.append(("nic.%d" % len(instance.nics), "remove"))
      elif nic_op == constants.DDM_ADD:
        # add a new nic
        if 'mac' not in nic_dict:
          mac = constants.VALUE_GENERATE
        else:
          mac = nic_dict['mac']
        if mac in (constants.VALUE_AUTO, constants.VALUE_GENERATE):
          mac = self.cfg.GenerateMAC()
        new_nic = objects.NIC(mac=mac, ip=nic_dict.get('ip', None),
                              bridge=nic_dict.get('bridge', None))
        instance.nics.append(new_nic)
        result.append(("nic.%d" % (len(instance.nics) - 1),
                       "add:mac=%s,ip=%s,bridge=%s" %
                       (new_nic.mac, new_nic.ip, new_nic.bridge)))
      else:
        # change a given nic
        for key in 'mac', 'ip', 'bridge':
          if key in nic_dict:
            setattr(instance.nics[nic_op], key, nic_dict[key])
            result.append(("nic.%s/%d" % (key, nic_op), nic_dict[key]))

    # hvparams changes
    if self.op.hvparams:
      instance.hvparams = self.hv_new
      for key, val in self.op.hvparams.iteritems():
        result.append(("hv/%s" % key, val))

    # beparams changes
    if self.op.beparams:
      instance.beparams = self.be_inst
      for key, val in self.op.beparams.iteritems():
        result.append(("be/%s" % key, val))

    self.cfg.Update(instance)

    return result


class LUQueryExports(NoHooksLU):
  """Query the exports list

  """
  _OP_REQP = ['nodes']
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}
    self.share_locks[locking.LEVEL_NODE] = 1
    if not self.op.nodes:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
    else:
      self.needed_locks[locking.LEVEL_NODE] = \
        _GetWantedNodes(self, self.op.nodes)

  def CheckPrereq(self):
    """Check prerequisites.

    """
    self.nodes = self.acquired_locks[locking.LEVEL_NODE]

  def Exec(self, feedback_fn):
    """Compute the list of all the exported system images.

    @rtype: dict
    @return: a dictionary with the structure node->(export-list)
        where export-list is a list of the instances exported on
        that node.

    """
    rpcresult = self.rpc.call_export_list(self.nodes)
    result = {}
    for node in rpcresult:
      if rpcresult[node].failed:
        result[node] = False
      else:
        result[node] = rpcresult[node].data

    return result


class LUExportInstance(LogicalUnit):
  """Export an instance to an image in the cluster.

  """
  HPATH = "instance-export"
  HTYPE = constants.HTYPE_INSTANCE
  _OP_REQP = ["instance_name", "target_node", "shutdown"]
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    # FIXME: lock only instance primary and destination node
    #
    # Sad but true, for now we have do lock all nodes, as we don't know where
    # the previous export might be, and and in this LU we search for it and
    # remove it from its current node. In the future we could fix this by:
    #  - making a tasklet to search (share-lock all), then create the new one,
    #    then one to remove, after
    #  - removing the removal operation altoghether
    self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def DeclareLocks(self, level):
    """Last minute lock declaration."""
    # All nodes are locked anyway, so nothing to do here.

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on the master, primary node and target node.

    """
    env = {
      "EXPORT_NODE": self.op.target_node,
      "EXPORT_DO_SHUTDOWN": self.op.shutdown,
      }
    env.update(_BuildInstanceHookEnvByObject(self, self.instance))
    nl = [self.cfg.GetMasterNode(), self.instance.primary_node,
          self.op.target_node]
    return env, nl, nl

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance and node names are valid.

    """
    instance_name = self.op.instance_name
    self.instance = self.cfg.GetInstanceInfo(instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, instance.primary_node)

    self.dst_node = self.cfg.GetNodeInfo(
      self.cfg.ExpandNodeName(self.op.target_node))

    if self.dst_node is None:
      # This is wrong node name, not a non-locked node
      raise errors.OpPrereqError("Wrong node name %s" % self.op.target_node)
    _CheckNodeOnline(self, self.op.target_node)

    # instance disk type verification
    for disk in self.instance.disks:
      if disk.dev_type == constants.LD_FILE:
        raise errors.OpPrereqError("Export not supported for instances with"
                                   " file-based disks")

  def Exec(self, feedback_fn):
    """Export an instance to an image in the cluster.

    """
    instance = self.instance
    dst_node = self.dst_node
    src_node = instance.primary_node
    if self.op.shutdown:
      # shutdown the instance, but not the disks
      result = self.rpc.call_instance_shutdown(src_node, instance)
      result.Raise()
      if not result.data:
        raise errors.OpExecError("Could not shutdown instance %s on node %s" %
                                 (instance.name, src_node))

    vgname = self.cfg.GetVGName()

    snap_disks = []

    try:
      for disk in instance.disks:
        # new_dev_name will be a snapshot of an lvm leaf of the one we passed
        new_dev_name = self.rpc.call_blockdev_snapshot(src_node, disk)
        if new_dev_name.failed or not new_dev_name.data:
          self.LogWarning("Could not snapshot block device %s on node %s",
                          disk.logical_id[1], src_node)
          snap_disks.append(False)
        else:
          new_dev = objects.Disk(dev_type=constants.LD_LV, size=disk.size,
                                 logical_id=(vgname, new_dev_name.data),
                                 physical_id=(vgname, new_dev_name.data),
                                 iv_name=disk.iv_name)
          snap_disks.append(new_dev)

    finally:
      if self.op.shutdown and instance.status == "up":
        result = self.rpc.call_instance_start(src_node, instance, None)
        if result.failed or not result.data:
          _ShutdownInstanceDisks(self, instance)
          raise errors.OpExecError("Could not start instance")

    # TODO: check for size

    cluster_name = self.cfg.GetClusterName()
    for idx, dev in enumerate(snap_disks):
      if dev:
        result = self.rpc.call_snapshot_export(src_node, dev, dst_node.name,
                                               instance, cluster_name, idx)
        if result.failed or not result.data:
          self.LogWarning("Could not export block device %s from node %s to"
                          " node %s", dev.logical_id[1], src_node,
                          dst_node.name)
        result = self.rpc.call_blockdev_remove(src_node, dev)
        if result.failed or not result.data:
          self.LogWarning("Could not remove snapshot block device %s from node"
                          " %s", dev.logical_id[1], src_node)

    result = self.rpc.call_finalize_export(dst_node.name, instance, snap_disks)
    if result.failed or not result.data:
      self.LogWarning("Could not finalize export for instance %s on node %s",
                      instance.name, dst_node.name)

    nodelist = self.cfg.GetNodeList()
    nodelist.remove(dst_node.name)

    # on one-node clusters nodelist will be empty after the removal
    # if we proceed the backup would be removed because OpQueryExports
    # substitutes an empty list with the full cluster node list.
    if nodelist:
      exportlist = self.rpc.call_export_list(nodelist)
      for node in exportlist:
        if exportlist[node].failed:
          continue
        if instance.name in exportlist[node].data:
          if not self.rpc.call_export_remove(node, instance.name):
            self.LogWarning("Could not remove older export for instance %s"
                            " on node %s", instance.name, node)


class LURemoveExport(NoHooksLU):
  """Remove exports related to the named instance.

  """
  _OP_REQP = ["instance_name"]
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}
    # We need all nodes to be locked in order for RemoveExport to work, but we
    # don't need to lock the instance itself, as nothing will happen to it (and
    # we can remove exports also for a removed instance)
    self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def CheckPrereq(self):
    """Check prerequisites.
    """
    pass

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

    exportlist = self.rpc.call_export_list(self.acquired_locks[
      locking.LEVEL_NODE])
    found = False
    for node in exportlist:
      if exportlist[node].failed:
        self.LogWarning("Failed to query node %s, continuing" % node)
        continue
      if instance_name in exportlist[node].data:
        found = True
        result = self.rpc.call_export_remove(node, instance_name)
        if result.failed or not result.data:
          logging.error("Could not remove export for instance %s"
                        " on node %s", instance_name, node)

    if fqdn_warn and not found:
      feedback_fn("Export not found. If trying to remove an export belonging"
                  " to a deleted instance please use its Fully Qualified"
                  " Domain Name.")


class TagsLU(NoHooksLU):
  """Generic tags LU.

  This is an abstract class which is the parent of all the other tags LUs.

  """

  def ExpandNames(self):
    self.needed_locks = {}
    if self.op.kind == constants.TAG_NODE:
      name = self.cfg.ExpandNodeName(self.op.name)
      if name is None:
        raise errors.OpPrereqError("Invalid node name (%s)" %
                                   (self.op.name,))
      self.op.name = name
      self.needed_locks[locking.LEVEL_NODE] = name
    elif self.op.kind == constants.TAG_INSTANCE:
      name = self.cfg.ExpandInstanceName(self.op.name)
      if name is None:
        raise errors.OpPrereqError("Invalid instance name (%s)" %
                                   (self.op.name,))
      self.op.name = name
      self.needed_locks[locking.LEVEL_INSTANCE] = name

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
                                 str(self.op.kind))


class LUGetTags(TagsLU):
  """Returns the tags of a given object.

  """
  _OP_REQP = ["kind", "name"]
  REQ_BGL = False

  def Exec(self, feedback_fn):
    """Returns the tag list.

    """
    return list(self.target.GetTags())


class LUSearchTags(NoHooksLU):
  """Searches the tags for a given pattern.

  """
  _OP_REQP = ["pattern"]
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
                                 (self.op.pattern, err))

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


class LUAddTags(TagsLU):
  """Sets a tag on a given object.

  """
  _OP_REQP = ["kind", "name", "tags"]
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
    try:
      self.cfg.Update(self.target)
    except errors.ConfigurationError:
      raise errors.OpRetryError("There has been a modification to the"
                                " config file and the operation has been"
                                " aborted. Please retry.")


class LUDelTags(TagsLU):
  """Delete a list of tags from a given object.

  """
  _OP_REQP = ["kind", "name", "tags"]
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
    if not del_tags <= cur_tags:
      diff_tags = del_tags - cur_tags
      diff_names = ["'%s'" % tag for tag in diff_tags]
      diff_names.sort()
      raise errors.OpPrereqError("Tag(s) %s not found" %
                                 (",".join(diff_names)))

  def Exec(self, feedback_fn):
    """Remove the tag from the object.

    """
    for tag in self.op.tags:
      self.target.RemoveTag(tag)
    try:
      self.cfg.Update(self.target)
    except errors.ConfigurationError:
      raise errors.OpRetryError("There has been a modification to the"
                                " config file and the operation has been"
                                " aborted. Please retry.")


class LUTestDelay(NoHooksLU):
  """Sleep for a specified amount of time.

  This LU sleeps on the master and/or nodes for a specified amount of
  time.

  """
  _OP_REQP = ["duration", "on_master", "on_nodes"]
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

  def CheckPrereq(self):
    """Check prerequisites.

    """

  def Exec(self, feedback_fn):
    """Do the actual sleep.

    """
    if self.op.on_master:
      if not utils.TestDelay(self.op.duration):
        raise errors.OpExecError("Error during master delay test")
    if self.op.on_nodes:
      result = self.rpc.call_test_delay(self.op.on_nodes, self.op.duration)
      if not result:
        raise errors.OpExecError("Complete failure from rpc call")
      for node, node_result in result.items():
        node_result.Raise()
        if not node_result.data:
          raise errors.OpExecError("Failure during rpc call to node %s,"
                                   " result: %s" % (node, node_result.data))


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
  _ALLO_KEYS = [
    "mem_size", "disks", "disk_template",
    "os", "tags", "nics", "vcpus", "hypervisor",
    ]
  _RELO_KEYS = [
    "relocate_from",
    ]

  def __init__(self, lu, mode, name, **kwargs):
    self.lu = lu
    # init buffer variables
    self.in_text = self.out_text = self.in_data = self.out_data = None
    # init all input fields so that pylint is happy
    self.mode = mode
    self.name = name
    self.mem_size = self.disks = self.disk_template = None
    self.os = self.tags = self.nics = self.vcpus = None
    self.relocate_from = None
    # computed fields
    self.required_nodes = None
    # init result fields
    self.success = self.info = self.nodes = None
    if self.mode == constants.IALLOCATOR_MODE_ALLOC:
      keyset = self._ALLO_KEYS
    elif self.mode == constants.IALLOCATOR_MODE_RELOC:
      keyset = self._RELO_KEYS
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
    self._BuildInputData()

  def _ComputeClusterData(self):
    """Compute the generic allocator input data.

    This is the data that is independent of the actual operation.

    """
    cfg = self.lu.cfg
    cluster_info = cfg.GetClusterInfo()
    # cluster data
    data = {
      "version": 1,
      "cluster_name": cfg.GetClusterName(),
      "cluster_tags": list(cluster_info.GetTags()),
      "enable_hypervisors": list(cluster_info.enabled_hypervisors),
      # we don't have job IDs
      }
    iinfo = cfg.GetAllInstancesInfo().values()
    i_list = [(inst, cluster_info.FillBE(inst)) for inst in iinfo]

    # node data
    node_results = {}
    node_list = cfg.GetNodeList()

    if self.mode == constants.IALLOCATOR_MODE_ALLOC:
      hypervisor = self.hypervisor
    elif self.mode == constants.IALLOCATOR_MODE_RELOC:
      hypervisor = cfg.GetInstanceInfo(self.name).hypervisor

    node_data = self.lu.rpc.call_node_info(node_list, cfg.GetVGName(),
                                           hypervisor)
    node_iinfo = self.lu.rpc.call_all_instances_info(node_list,
                       cluster_info.enabled_hypervisors)
    for nname in node_list:
      ninfo = cfg.GetNodeInfo(nname)
      node_data[nname].Raise()
      if not isinstance(node_data[nname].data, dict):
        raise errors.OpExecError("Can't get data for node %s" % nname)
      remote_info = node_data[nname].data
      for attr in ['memory_total', 'memory_free', 'memory_dom0',
                   'vg_size', 'vg_free', 'cpu_total']:
        if attr not in remote_info:
          raise errors.OpExecError("Node '%s' didn't return attribute '%s'" %
                                   (nname, attr))
        try:
          remote_info[attr] = int(remote_info[attr])
        except ValueError, err:
          raise errors.OpExecError("Node '%s' returned invalid value for '%s':"
                                   " %s" % (nname, attr, str(err)))
      # compute memory used by primary instances
      i_p_mem = i_p_up_mem = 0
      for iinfo, beinfo in i_list:
        if iinfo.primary_node == nname:
          i_p_mem += beinfo[constants.BE_MEMORY]
          if iinfo.name not in node_iinfo[nname]:
            i_used_mem = 0
          else:
            i_used_mem = int(node_iinfo[nname][iinfo.name]['memory'])
          i_mem_diff = beinfo[constants.BE_MEMORY] - i_used_mem
          remote_info['memory_free'] -= max(0, i_mem_diff)

          if iinfo.status == "up":
            i_p_up_mem += beinfo[constants.BE_MEMORY]

      # compute memory used by instances
      pnr = {
        "tags": list(ninfo.GetTags()),
        "total_memory": remote_info['memory_total'],
        "reserved_memory": remote_info['memory_dom0'],
        "free_memory": remote_info['memory_free'],
        "i_pri_memory": i_p_mem,
        "i_pri_up_memory": i_p_up_mem,
        "total_disk": remote_info['vg_size'],
        "free_disk": remote_info['vg_free'],
        "primary_ip": ninfo.primary_ip,
        "secondary_ip": ninfo.secondary_ip,
        "total_cpus": remote_info['cpu_total'],
        "offline": ninfo.offline,
        }
      node_results[nname] = pnr
    data["nodes"] = node_results

    # instance data
    instance_data = {}
    for iinfo, beinfo in i_list:
      nic_data = [{"mac": n.mac, "ip": n.ip, "bridge": n.bridge}
                  for n in iinfo.nics]
      pir = {
        "tags": list(iinfo.GetTags()),
        "should_run": iinfo.status == "up",
        "vcpus": beinfo[constants.BE_VCPUS],
        "memory": beinfo[constants.BE_MEMORY],
        "os": iinfo.os,
        "nodes": [iinfo.primary_node] + list(iinfo.secondary_nodes),
        "nics": nic_data,
        "disks": [{"size": dsk.size, "mode": "w"} for dsk in iinfo.disks],
        "disk_template": iinfo.disk_template,
        "hypervisor": iinfo.hypervisor,
        }
      instance_data[iinfo.name] = pir

    data["instances"] = instance_data

    self.in_data = data

  def _AddNewInstance(self):
    """Add new instance data to allocator structure.

    This in combination with _AllocatorGetClusterData will create the
    correct structure needed as input for the allocator.

    The checks for the completeness of the opcode must have already been
    done.

    """
    data = self.in_data
    if len(self.disks) != 2:
      raise errors.OpExecError("Only two-disk configurations supported")

    disk_space = _ComputeDiskSize(self.disk_template, self.disks)

    if self.disk_template in constants.DTS_NET_MIRROR:
      self.required_nodes = 2
    else:
      self.required_nodes = 1
    request = {
      "type": "allocate",
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
    data["request"] = request

  def _AddRelocateInstance(self):
    """Add relocate instance data to allocator structure.

    This in combination with _IAllocatorGetClusterData will create the
    correct structure needed as input for the allocator.

    The checks for the completeness of the opcode must have already been
    done.

    """
    instance = self.lu.cfg.GetInstanceInfo(self.name)
    if instance is None:
      raise errors.ProgrammerError("Unknown instance '%s' passed to"
                                   " IAllocator" % self.name)

    if instance.disk_template not in constants.DTS_NET_MIRROR:
      raise errors.OpPrereqError("Can't relocate non-mirrored instances")

    if len(instance.secondary_nodes) != 1:
      raise errors.OpPrereqError("Instance has not exactly one secondary node")

    self.required_nodes = 1
    disk_sizes = [{'size': disk.size} for disk in instance.disks]
    disk_space = _ComputeDiskSize(instance.disk_template, disk_sizes)

    request = {
      "type": "relocate",
      "name": self.name,
      "disk_space_total": disk_space,
      "required_nodes": self.required_nodes,
      "relocate_from": self.relocate_from,
      }
    self.in_data["request"] = request

  def _BuildInputData(self):
    """Build input data structures.

    """
    self._ComputeClusterData()

    if self.mode == constants.IALLOCATOR_MODE_ALLOC:
      self._AddNewInstance()
    else:
      self._AddRelocateInstance()

    self.in_text = serializer.Dump(self.in_data)

  def Run(self, name, validate=True, call_fn=None):
    """Run an instance allocator and return the results.

    """
    if call_fn is None:
      call_fn = self.lu.rpc.call_iallocator_runner
    data = self.in_text

    result = call_fn(self.lu.cfg.GetMasterNode(), name, self.in_text)
    result.Raise()

    if not isinstance(result.data, (list, tuple)) or len(result.data) != 4:
      raise errors.OpExecError("Invalid result from master iallocator runner")

    rcode, stdout, stderr, fail = result.data

    if rcode == constants.IARUN_NOTFOUND:
      raise errors.OpExecError("Can't find allocator '%s'" % name)
    elif rcode == constants.IARUN_FAILURE:
      raise errors.OpExecError("Instance allocator call failed: %s,"
                               " output: %s" % (fail, stdout+stderr))
    self.out_text = stdout
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

    for key in "success", "info", "nodes":
      if key not in rdict:
        raise errors.OpExecError("Can't parse iallocator results:"
                                 " missing key '%s'" % key)
      setattr(self, key, rdict[key])

    if not isinstance(rdict["nodes"], list):
      raise errors.OpExecError("Can't parse iallocator results: 'nodes' key"
                               " is not a list")
    self.out_data = rdict


class LUTestAllocator(NoHooksLU):
  """Run allocator tests.

  This LU runs the allocator tests

  """
  _OP_REQP = ["direction", "mode", "name"]

  def CheckPrereq(self):
    """Check prerequisites.

    This checks the opcode parameters depending on the director and mode test.

    """
    if self.op.mode == constants.IALLOCATOR_MODE_ALLOC:
      for attr in ["name", "mem_size", "disks", "disk_template",
                   "os", "tags", "nics", "vcpus"]:
        if not hasattr(self.op, attr):
          raise errors.OpPrereqError("Missing attribute '%s' on opcode input" %
                                     attr)
      iname = self.cfg.ExpandInstanceName(self.op.name)
      if iname is not None:
        raise errors.OpPrereqError("Instance '%s' already in the cluster" %
                                   iname)
      if not isinstance(self.op.nics, list):
        raise errors.OpPrereqError("Invalid parameter 'nics'")
      for row in self.op.nics:
        if (not isinstance(row, dict) or
            "mac" not in row or
            "ip" not in row or
            "bridge" not in row):
          raise errors.OpPrereqError("Invalid contents of the"
                                     " 'nics' parameter")
      if not isinstance(self.op.disks, list):
        raise errors.OpPrereqError("Invalid parameter 'disks'")
      if len(self.op.disks) != 2:
        raise errors.OpPrereqError("Only two-disk configurations supported")
      for row in self.op.disks:
        if (not isinstance(row, dict) or
            "size" not in row or
            not isinstance(row["size"], int) or
            "mode" not in row or
            row["mode"] not in ['r', 'w']):
          raise errors.OpPrereqError("Invalid contents of the"
                                     " 'disks' parameter")
      if self.op.hypervisor is None:
        self.op.hypervisor = self.cfg.GetHypervisorType()
    elif self.op.mode == constants.IALLOCATOR_MODE_RELOC:
      if not hasattr(self.op, "name"):
        raise errors.OpPrereqError("Missing attribute 'name' on opcode input")
      fname = self.cfg.ExpandInstanceName(self.op.name)
      if fname is None:
        raise errors.OpPrereqError("Instance '%s' not found for relocation" %
                                   self.op.name)
      self.op.name = fname
      self.relocate_from = self.cfg.GetInstanceInfo(fname).secondary_nodes
    else:
      raise errors.OpPrereqError("Invalid test allocator mode '%s'" %
                                 self.op.mode)

    if self.op.direction == constants.IALLOCATOR_DIR_OUT:
      if not hasattr(self.op, "allocator") or self.op.allocator is None:
        raise errors.OpPrereqError("Missing allocator name")
    elif self.op.direction != constants.IALLOCATOR_DIR_IN:
      raise errors.OpPrereqError("Wrong allocator test '%s'" %
                                 self.op.direction)

  def Exec(self, feedback_fn):
    """Run the allocator test.

    """
    if self.op.mode == constants.IALLOCATOR_MODE_ALLOC:
      ial = IAllocator(self,
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
    else:
      ial = IAllocator(self,
                       mode=self.op.mode,
                       name=self.op.name,
                       relocate_from=list(self.relocate_from),
                       )

    if self.op.direction == constants.IALLOCATOR_DIR_IN:
      result = ial.in_text
    else:
      ial.Run(self.op.allocator, validate=False)
      result = ial.out_text
    return result
