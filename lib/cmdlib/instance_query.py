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


"""Logical units for querying instances."""

import itertools
import logging
import operator

from ganeti import compat
from ganeti import constants
from ganeti import locking
from ganeti import qlang
from ganeti import query
from ganeti.cmdlib.base import QueryBase, NoHooksLU
from ganeti.cmdlib.common import ShareAll, GetWantedInstances, \
  CheckInstanceNodeGroups, CheckInstancesNodeGroups, AnnotateDiskParams
from ganeti.cmdlib.instance_operation import GetInstanceConsole
from ganeti.cmdlib.instance_utils import NICListToTuple

import ganeti.masterd.instance


class InstanceQuery(QueryBase):
  FIELDS = query.INSTANCE_FIELDS

  def ExpandNames(self, lu):
    lu.needed_locks = {}
    lu.share_locks = ShareAll()

    if self.names:
      self.wanted = GetWantedInstances(lu, self.names)
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
      CheckInstanceNodeGroups(lu.cfg, instance_name, owned_groups)

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
          consinfo[inst.name] = GetInstanceConsole(cluster, inst)
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


class LUInstanceQuery(NoHooksLU):
  """Logical unit for querying instances.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.iq = InstanceQuery(qlang.MakeSimpleFilter("name", self.op.names),
                             self.op.output_fields, self.op.use_locking)

  def ExpandNames(self):
    self.iq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.iq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.iq.OldStyleQuery(self)


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
      self.wanted_names = GetWantedInstances(self, self.op.instances)
    else:
      # Will use acquired locks
      self.wanted_names = None

    if self.op.use_locking:
      self.share_locks = ShareAll()

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
      CheckInstancesNodeGroups(self.cfg, instances, owned_groups, owned_nodes,
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
    (anno_dev,) = AnnotateDiskParams(instance, [dev], self.cfg)

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
      "name": dev.name,
      "uuid": dev.uuid,
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
        "nics": NICListToTuple(self, instance.nics),
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
