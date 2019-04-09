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


"""Logical units for querying instances."""

import itertools

from ganeti import constants
from ganeti import locking
from ganeti import utils
from ganeti.cmdlib.base import NoHooksLU
from ganeti.cmdlib.common import ShareAll, GetWantedInstances, \
  CheckInstancesNodeGroups, AnnotateDiskParams
from ganeti.cmdlib.instance_utils import NICListToTuple
from ganeti.hypervisor import hv_base


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
      (_, self.wanted_names) = GetWantedInstances(self, self.op.instances)
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
      self.dont_collate_locks[locking.LEVEL_NODEGROUP] = True
      self.dont_collate_locks[locking.LEVEL_NODE] = True
      self.dont_collate_locks[locking.LEVEL_NETWORK] = True

  def DeclareLocks(self, level):
    if self.op.use_locking:
      owned_instances = dict(self.cfg.GetMultiInstanceInfoByName(
                               self.owned_locks(locking.LEVEL_INSTANCE)))
      if level == locking.LEVEL_NODEGROUP:

        # Lock all groups used by instances optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        self.needed_locks[locking.LEVEL_NODEGROUP] = \
          frozenset(group_uuid
                    for instance_uuid in owned_instances
                    for group_uuid in
                    self.cfg.GetInstanceNodeGroups(instance_uuid))

      elif level == locking.LEVEL_NODE:
        self._LockInstancesNodes()

      elif level == locking.LEVEL_NETWORK:
        self.needed_locks[locking.LEVEL_NETWORK] = \
          frozenset(net_uuid
                    for instance_uuid in owned_instances.keys()
                    for net_uuid in
                    self.cfg.GetInstanceNetworks(instance_uuid))

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_node_uuids = frozenset(self.owned_locks(locking.LEVEL_NODE))
    owned_networks = frozenset(self.owned_locks(locking.LEVEL_NETWORK))

    if self.wanted_names is None:
      assert self.op.use_locking, "Locking was not used"
      self.wanted_names = owned_instances

    instances = dict(self.cfg.GetMultiInstanceInfoByName(self.wanted_names))

    if self.op.use_locking:
      CheckInstancesNodeGroups(self.cfg, instances, owned_groups,
                               owned_node_uuids, None)
    else:
      assert not (owned_instances or owned_groups or
                  owned_node_uuids or owned_networks)

    self.wanted_instances = list(instances.values())

  def _ComputeBlockdevStatus(self, node_uuid, instance, dev):
    """Returns the status of a block device

    """
    if self.op.static or not node_uuid:
      return None

    result = self.rpc.call_blockdev_find(node_uuid, (dev, instance))
    if result.offline:
      return None

    result.Raise("Can't compute disk status for %s" % instance.name)

    status = result.payload
    if status is None:
      return None

    return (status.dev_path, status.major, status.minor,
            status.sync_percent, status.estimated_time,
            status.is_degraded, status.ldisk_status)

  def _ComputeDiskStatus(self, instance, node_uuid2name_fn, dev):
    """Compute block device status.

    """
    (anno_dev,) = AnnotateDiskParams(instance, [dev], self.cfg)

    return self._ComputeDiskStatusInner(instance, None, node_uuid2name_fn,
                                        anno_dev)

  def _ComputeDiskStatusInner(self, instance, snode_uuid, node_uuid2name_fn,
                              dev):
    """Compute block device status.

    @attention: The device has to be annotated already.

    """
    drbd_info = None
    output_logical_id = dev.logical_id
    if dev.dev_type in constants.DTS_DRBD:
      # we change the snode then (otherwise we use the one passed in)
      if dev.logical_id[0] == instance.primary_node:
        snode_uuid = dev.logical_id[1]
        snode_minor = dev.logical_id[4]
        pnode_minor = dev.logical_id[3]
      else:
        snode_uuid = dev.logical_id[0]
        snode_minor = dev.logical_id[3]
        pnode_minor = dev.logical_id[4]
      drbd_info = {
        "primary_node": node_uuid2name_fn(instance.primary_node),
        "primary_minor": pnode_minor,
        "secondary_node": node_uuid2name_fn(snode_uuid),
        "secondary_minor": snode_minor,
        "port": dev.logical_id[2],
      }
      # replace the secret present at the end of the ids with None
      output_logical_id = dev.logical_id[:-1] + (None,)

    dev_pstatus = self._ComputeBlockdevStatus(instance.primary_node,
                                              instance, dev)
    dev_sstatus = self._ComputeBlockdevStatus(snode_uuid, instance, dev)

    if dev.children:
      dev_children = [
        self._ComputeDiskStatusInner(instance, snode_uuid, node_uuid2name_fn, d)
        for d in dev.children
      ]
    else:
      dev_children = []

    return {
      "iv_name": dev.iv_name,
      "dev_type": dev.dev_type,
      "logical_id": output_logical_id,
      "drbd_info": drbd_info,
      "pstatus": dev_pstatus,
      "sstatus": dev_sstatus,
      "children": dev_children,
      "mode": dev.mode,
      "size": dev.size,
      "spindles": dev.spindles,
      "name": dev.name,
      "uuid": dev.uuid,
      }

  def Exec(self, feedback_fn):
    """Gather and return data"""
    result = {}

    cluster = self.cfg.GetClusterInfo()

    node_uuids = itertools.chain(*(self.cfg.GetInstanceNodes(i.uuid)
                                   for i in self.wanted_instances))
    nodes = dict(self.cfg.GetMultiNodeInfo(node_uuids))

    groups = dict(self.cfg.GetMultiNodeGroupInfo(node.group
                                                 for node in nodes.values()))

    for instance in self.wanted_instances:
      pnode = nodes[instance.primary_node]
      hvparams = cluster.FillHV(instance, skip_globals=True)

      if self.op.static or pnode.offline:
        remote_state = None
        if pnode.offline:
          self.LogWarning("Primary node %s is marked offline, returning static"
                          " information only for instance %s" %
                          (pnode.name, instance.name))
      else:
        remote_info = self.rpc.call_instance_info(
            instance.primary_node, instance.name, instance.hypervisor,
            cluster.hvparams[instance.hypervisor])
        remote_info.Raise("Error checking node %s" % pnode.name)
        remote_info = remote_info.payload

        allow_userdown = \
            cluster.enabled_user_shutdown and \
            (instance.hypervisor != constants.HT_KVM or
             hvparams[constants.HV_KVM_USER_SHUTDOWN])

        if remote_info and "state" in remote_info:
          if hv_base.HvInstanceState.IsShutdown(remote_info["state"]):
            if allow_userdown:
              remote_state = "user down"
            else:
              remote_state = "down"
          else:
            remote_state = "up"
        else:
          if instance.admin_state == constants.ADMINST_UP:
            remote_state = "down"
          elif instance.admin_state == constants.ADMINST_DOWN:
            if instance.admin_state_source == constants.USER_SOURCE:
              remote_state = "user down"
            else:
              remote_state = "down"
          else:
            remote_state = "offline"

      group2name_fn = lambda uuid: groups[uuid].name
      node_uuid2name_fn = lambda uuid: nodes[uuid].name

      disk_objects = self.cfg.GetInstanceDisks(instance.uuid)
      output_disks = [self._ComputeDiskStatus(instance, node_uuid2name_fn, d)
                      for d in disk_objects]

      secondary_nodes = self.cfg.GetInstanceSecondaryNodes(instance.uuid)
      snodes_group_uuids = [nodes[snode_uuid].group
                            for snode_uuid in secondary_nodes]

      result[instance.name] = {
        "name": instance.name,
        "config_state": instance.admin_state,
        "run_state": remote_state,
        "pnode": pnode.name,
        "pnode_group_uuid": pnode.group,
        "pnode_group_name": group2name_fn(pnode.group),
        "snodes": [node_uuid2name_fn(n) for n in secondary_nodes],
        "snodes_group_uuids": snodes_group_uuids,
        "snodes_group_names": [group2name_fn(u) for u in snodes_group_uuids],
        "os": instance.os,
        # this happens to be the same format used for hooks
        "nics": NICListToTuple(self, instance.nics),
        "disk_template": utils.GetDiskTemplate(disk_objects),
        "disks": output_disks,
        "hypervisor": instance.hypervisor,
        "network_port": instance.network_port,
        "hv_instance": instance.hvparams,
        "hv_actual": hvparams,
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
