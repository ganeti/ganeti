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


"""Logical units dealing with node groups."""

import itertools
import logging

from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import objects
from ganeti import opcodes
from ganeti import qlang
from ganeti import query
from ganeti import utils
from ganeti.masterd import iallocator
from ganeti.cmdlib.base import LogicalUnit, NoHooksLU, QueryBase, \
  ResultWithJobs
from ganeti.cmdlib.common import MergeAndVerifyHvState, \
  MergeAndVerifyDiskState, GetWantedNodes, GetUpdatedParams, \
  CheckNodeGroupInstances, GetUpdatedIPolicy, \
  ComputeNewInstanceViolations, GetDefaultIAllocator, ShareAll, \
  CheckInstancesNodeGroups, LoadNodeEvacResult, MapInstanceLvsToNodes, \
  CheckIpolicyVsDiskTemplates, CheckDiskAccessModeValidity, \
  CheckDiskAccessModeConsistency

import ganeti.masterd.instance


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

  def _CheckIpolicy(self):
    """Checks the group's ipolicy for consistency and validity.

    """
    if self.op.ipolicy:
      cluster = self.cfg.GetClusterInfo()
      full_ipolicy = cluster.SimpleFillIPolicy(self.op.ipolicy)
      try:
        objects.InstancePolicy.CheckParameterSyntax(full_ipolicy, False)
      except errors.ConfigurationError, err:
        raise errors.OpPrereqError("Invalid instance policy: %s" % err,
                                   errors.ECODE_INVAL)
      CheckIpolicyVsDiskTemplates(full_ipolicy,
                                  cluster.enabled_disk_templates)

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
      self.new_hv_state = MergeAndVerifyHvState(self.op.hv_state, None)
    else:
      self.new_hv_state = None

    if self.op.disk_state:
      self.new_disk_state = MergeAndVerifyDiskState(self.op.disk_state, None)
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

    self._CheckIpolicy()

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
    (self.op.node_uuids, self.op.nodes) = GetWantedNodes(self, self.op.nodes)

    # We want to lock all the affected nodes and groups. We have readily
    # available the list of nodes, and the *destination* group. To gather the
    # list of "source" groups, we need to fetch node information later on.
    self.needed_locks = {
      locking.LEVEL_NODEGROUP: set([self.group_uuid]),
      locking.LEVEL_NODE: self.op.node_uuids,
      }

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert len(self.needed_locks[locking.LEVEL_NODEGROUP]) == 1

      # Try to get all affected nodes' groups without having the group or node
      # lock yet. Needs verification later in the code flow.
      groups = self.cfg.GetNodeGroupsFromNodes(self.op.node_uuids)

      self.needed_locks[locking.LEVEL_NODEGROUP].update(groups)

  def CheckPrereq(self):
    """Check prerequisites.

    """
    assert self.needed_locks[locking.LEVEL_NODEGROUP]
    assert (frozenset(self.owned_locks(locking.LEVEL_NODE)) ==
            frozenset(self.op.node_uuids))

    expected_locks = (set([self.group_uuid]) |
                      self.cfg.GetNodeGroupsFromNodes(self.op.node_uuids))
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
      self.CheckAssignmentForSplitInstances([(uuid, self.group_uuid)
                                             for uuid in self.op.node_uuids],
                                            self.node_data, instance_data)

    if new_splits:
      fmt_new_splits = utils.CommaJoin(utils.NiceSort(
                         self.cfg.GetInstanceNames(new_splits)))

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
                          utils.CommaJoin(utils.NiceSort(
                            self.cfg.GetInstanceNames(previous_splits))))

  def Exec(self, feedback_fn):
    """Assign nodes to a new group.

    """
    mods = [(node_uuid, self.group_uuid) for node_uuid in self.op.node_uuids]

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

    @type changes: list of (node_uuid, new_group_uuid) pairs.
    @param changes: list of node assignments to consider.
    @param node_data: a dict with data for all nodes
    @param instance_data: a dict with all instances to consider
    @rtype: a two-tuple
    @return: a list of instances that were previously okay and result split as a
      consequence of this change, and a list of instances that were previously
      split and this change does not fix.

    """
    changed_nodes = dict((uuid, group) for uuid, group in changes
                         if node_data[uuid].group != group)

    all_split_instances = set()
    previously_split_instances = set()

    for inst in instance_data.values():
      if inst.disk_template not in constants.DTS_INT_MIRROR:
        continue

      if len(set(node_data[node_uuid].group
                 for node_uuid in inst.all_nodes)) > 1:
        previously_split_instances.add(inst.uuid)

      if len(set(changed_nodes.get(node_uuid, node_data[node_uuid].group)
                 for node_uuid in inst.all_nodes)) > 1:
        all_split_instances.add(inst.uuid)

    return (list(all_split_instances - previously_split_instances),
            list(previously_split_instances & all_split_instances))


class GroupQuery(QueryBase):
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
          group_to_nodes[node.group].append(node.uuid)
          node_to_group[node.uuid] = node.group

      if do_instances:
        all_instances = lu.cfg.GetAllInstancesInfo()
        group_to_instances = dict((uuid, []) for uuid in self.wanted)

        for instance in all_instances.values():
          node = instance.primary_node
          if node in node_to_group:
            group_to_instances[node_to_group[node]].append(instance.uuid)

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
    self.gq = GroupQuery(qlang.MakeSimpleFilter("name", self.op.names),
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

    if self.op.diskparams:
      CheckDiskAccessModeValidity(self.op.diskparams)

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
        self.cfg.GetInstanceNames(
          self.cfg.GetNodeGroupInstances(self.group_uuid))

  @staticmethod
  def _UpdateAndVerifyDiskParams(old, new):
    """Updates and verifies disk parameters.

    """
    new_params = GetUpdatedParams(old, new)
    utils.ForceDictType(new_params, constants.DISK_DT_TYPES)
    return new_params

  def _CheckIpolicy(self, cluster, owned_instance_names):
    """Sanity checks for the ipolicy.

    @type cluster: C{objects.Cluster}
    @param cluster: the cluster's configuration
    @type owned_instance_names: list of string
    @param owned_instance_names: list of instances

    """
    if self.op.ipolicy:
      self.new_ipolicy = GetUpdatedIPolicy(self.group.ipolicy,
                                           self.op.ipolicy,
                                           group_policy=True)

      new_ipolicy = cluster.SimpleFillIPolicy(self.new_ipolicy)
      CheckIpolicyVsDiskTemplates(new_ipolicy,
                                  cluster.enabled_disk_templates)
      instances = \
        dict(self.cfg.GetMultiInstanceInfoByName(owned_instance_names))
      gmi = ganeti.masterd.instance
      violations = \
          ComputeNewInstanceViolations(gmi.CalculateGroupIPolicy(cluster,
                                                                 self.group),
                                       new_ipolicy, instances.values(),
                                       self.cfg)

      if violations:
        self.LogWarning("After the ipolicy change the following instances"
                        " violate them: %s",
                        utils.CommaJoin(violations))

  def CheckPrereq(self):
    """Check prerequisites.

    """
    owned_instance_names = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))

    # Check if locked instances are still correct
    CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instance_names)

    self.group = self.cfg.GetNodeGroup(self.group_uuid)
    cluster = self.cfg.GetClusterInfo()

    if self.group is None:
      raise errors.OpExecError("Could not retrieve group '%s' (UUID: %s)" %
                               (self.op.group_name, self.group_uuid))

    if self.op.ndparams:
      new_ndparams = GetUpdatedParams(self.group.ndparams, self.op.ndparams)
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
        CheckDiskAccessModeConsistency(self.new_diskparams, self.cfg,
                                       group=self.group)
      except errors.OpPrereqError, err:
        raise errors.OpPrereqError("While verify diskparams options: %s" % err,
                                   errors.ECODE_INVAL)

    if self.op.hv_state:
      self.new_hv_state = MergeAndVerifyHvState(self.op.hv_state,
                                                self.group.hv_state_static)

    if self.op.disk_state:
      self.new_disk_state = \
        MergeAndVerifyDiskState(self.op.disk_state,
                                self.group.disk_state_static)

    self._CheckIpolicy(cluster, owned_instance_names)

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
    group_nodes = [node.uuid
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
    run_nodes.extend(node.uuid for node in all_nodes.values()
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

    self.op.iallocator = GetDefaultIAllocator(self.cfg, self.op.iallocator)

    self.share_locks = ShareAll()
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
        self.cfg.GetInstanceNames(
          self.cfg.GetNodeGroupInstances(self.group_uuid))

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
                             self.cfg.GetInstanceNodeGroups(
                               self.cfg.GetInstanceInfoByName(instance_name)
                                 .uuid))
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
      member_node_uuids = [node_uuid
                           for group in owned_groups
                           for node_uuid in
                             self.cfg.GetNodeGroup(group).members]
      self.needed_locks[locking.LEVEL_NODE].extend(member_node_uuids)

  def CheckPrereq(self):
    owned_instance_names = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_node_uuids = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert owned_groups.issuperset(self.req_target_uuids)
    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instance_names)

    # Get instance information
    self.instances = \
      dict(self.cfg.GetMultiInstanceInfoByName(owned_instance_names))

    # Check if node groups for locked instances are still correct
    CheckInstancesNodeGroups(self.cfg, self.instances,
                             owned_groups, owned_node_uuids, self.group_uuid)

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

  @staticmethod
  def _MigrateToFailover(op):
    """Return an equivalent failover opcode for a migrate one.

    If the argument is not a failover opcode, return it unchanged.

    """
    if not isinstance(op, opcodes.OpInstanceMigrate):
      return op
    else:
      return opcodes.OpInstanceFailover(
        instance_name=op.instance_name,
        instance_uuid=getattr(op, "instance_uuid", None),
        target_node=getattr(op, "target_node", None),
        target_node_uuid=getattr(op, "target_node_uuid", None),
        ignore_ipolicy=op.ignore_ipolicy,
        cleanup=op.cleanup)

  def Exec(self, feedback_fn):
    inst_names = list(self.owned_locks(locking.LEVEL_INSTANCE))

    assert self.group_uuid not in self.target_uuids

    req = iallocator.IAReqGroupChange(instances=inst_names,
                                      target_groups=self.target_uuids)
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute group evacuation using"
                                 " iallocator '%s': %s" %
                                 (self.op.iallocator, ial.info),
                                 errors.ECODE_NORES)

    jobs = LoadNodeEvacResult(self, ial.result, self.op.early_release, False)

    self.LogInfo("Iallocator returned %s job(s) for evacuating node group %s",
                 len(jobs), self.op.group_name)

    if self.op.force_failover:
      self.LogInfo("Will insist on failovers")
      jobs = [[self._MigrateToFailover(op) for op in job] for job in jobs]

    if self.op.sequential:
      self.LogInfo("Jobs will be submitted to run sequentially")
      for job in jobs[1:]:
        for op in job:
          op.depends = [(-1, ["error", "success"])]

    return ResultWithJobs(jobs)


class LUGroupVerifyDisks(NoHooksLU):
  """Verifies the status of all disks in a node group.

  """
  REQ_BGL = False

  def ExpandNames(self):
    # Raises errors.OpPrereqError on its own if group can't be found
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    self.share_locks = ShareAll()
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
        self.cfg.GetInstanceNames(
          self.cfg.GetNodeGroupInstances(self.group_uuid))

    elif level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      self.needed_locks[locking.LEVEL_NODEGROUP] = \
        set([self.group_uuid] +
            # Lock all groups used by instances optimistically; this requires
            # going via the node before it's locked, requiring verification
            # later on
            [group_uuid
             for instance_name in self.owned_locks(locking.LEVEL_INSTANCE)
             for group_uuid in
               self.cfg.GetInstanceNodeGroups(
                 self.cfg.GetInstanceInfoByName(instance_name).uuid)])

    elif level == locking.LEVEL_NODE:
      # This will only lock the nodes in the group to be verified which contain
      # actual instances
      self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND
      self._LockInstancesNodes()

      # Lock all nodes in group to be verified
      assert self.group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)
      member_node_uuids = self.cfg.GetNodeGroup(self.group_uuid).members
      self.needed_locks[locking.LEVEL_NODE].extend(member_node_uuids)

  def CheckPrereq(self):
    owned_inst_names = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_node_uuids = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_inst_names)

    # Get instance information
    self.instances = dict(self.cfg.GetMultiInstanceInfoByName(owned_inst_names))

    # Check if node groups for locked instances are still correct
    CheckInstancesNodeGroups(self.cfg, self.instances,
                             owned_groups, owned_node_uuids, self.group_uuid)

  def _VerifyInstanceLvs(self, node_errors, offline_disk_instance_names,
                         missing_disks):
    node_lv_to_inst = MapInstanceLvsToNodes(
      [inst for inst in self.instances.values() if inst.disks_active])
    if node_lv_to_inst:
      node_uuids = utils.NiceSort(set(self.owned_locks(locking.LEVEL_NODE)) &
                                  set(self.cfg.GetVmCapableNodeList()))

      node_lvs = self.rpc.call_lv_list(node_uuids, [])

      for (node_uuid, node_res) in node_lvs.items():
        if node_res.offline:
          continue

        msg = node_res.fail_msg
        if msg:
          logging.warning("Error enumerating LVs on node %s: %s",
                          self.cfg.GetNodeName(node_uuid), msg)
          node_errors[node_uuid] = msg
          continue

        for lv_name, (_, _, lv_online) in node_res.payload.items():
          inst = node_lv_to_inst.pop((node_uuid, lv_name), None)
          if not lv_online and inst is not None:
            offline_disk_instance_names.add(inst.name)

      # any leftover items in nv_dict are missing LVs, let's arrange the data
      # better
      for key, inst in node_lv_to_inst.iteritems():
        missing_disks.setdefault(inst.name, []).append(list(key))

  def _VerifyDrbdStates(self, node_errors, offline_disk_instance_names):
    node_to_inst = {}
    for inst in self.instances.values():
      if not inst.disks_active or inst.disk_template != constants.DT_DRBD8:
        continue

      for node_uuid in itertools.chain([inst.primary_node],
                                       inst.secondary_nodes):
        node_to_inst.setdefault(node_uuid, []).append(inst)

    for (node_uuid, insts) in node_to_inst.items():
      node_disks = [(inst.disks, inst) for inst in insts]
      node_res = self.rpc.call_drbd_needs_activation(node_uuid, node_disks)
      msg = node_res.fail_msg
      if msg:
        logging.warning("Error getting DRBD status on node %s: %s",
                        self.cfg.GetNodeName(node_uuid), msg)
        node_errors[node_uuid] = msg
        continue

      faulty_disk_uuids = set(node_res.payload)
      for inst in self.instances.values():
        inst_disk_uuids = set([disk.uuid for disk in inst.disks])
        if inst_disk_uuids.intersection(faulty_disk_uuids):
          offline_disk_instance_names.add(inst.name)

  def Exec(self, feedback_fn):
    """Verify integrity of cluster disks.

    @rtype: tuple of three items
    @return: a tuple of (dict of node-to-node_error, list of instances
        which need activate-disks, dict of instance: (node, volume) for
        missing volumes

    """
    node_errors = {}
    offline_disk_instance_names = set()
    missing_disks = {}

    self._VerifyInstanceLvs(node_errors, offline_disk_instance_names,
                            missing_disks)
    self._VerifyDrbdStates(node_errors, offline_disk_instance_names)

    return (node_errors, list(offline_disk_instance_names), missing_disks)
