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


"""Logical units dealing with instance migration an failover."""

import logging
import time

from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti.masterd import iallocator
from ganeti import utils
from ganeti.cmdlib.base import LogicalUnit, Tasklet
from ganeti.cmdlib.common import ExpandInstanceUuidAndName, \
  CheckIAllocatorOrNode, ExpandNodeUuidAndName
from ganeti.cmdlib.instance_storage import CheckDiskConsistency, \
  ExpandCheckDisks, ShutdownInstanceDisks, AssembleInstanceDisks
from ganeti.cmdlib.instance_utils import BuildInstanceHookEnvByObject, \
  CheckTargetNodeIPolicy, ReleaseLocks, CheckNodeNotDrained, \
  CopyLockList, CheckNodeFreeMemory, CheckInstanceBridgesExist

import ganeti.masterd.instance


def _ExpandNamesForMigration(lu):
  """Expands names for use with L{TLMigrateInstance}.

  @type lu: L{LogicalUnit}

  """
  if lu.op.target_node is not None:
    (lu.op.target_node_uuid, lu.op.target_node) = \
      ExpandNodeUuidAndName(lu.cfg, lu.op.target_node_uuid, lu.op.target_node)

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

    instance = lu.cfg.GetInstanceInfo(lu.op.instance_uuid)

    # Node locks are already declared here rather than at LEVEL_NODE as we need
    # the instance object anyway to declare the node allocation lock.
    if instance.disk_template in constants.DTS_EXT_MIRROR:
      if lu.op.target_node is None:
        lu.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
        lu.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET
      else:
        lu.needed_locks[locking.LEVEL_NODE] = [instance.primary_node,
                                               lu.op.target_node_uuid]
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
      CopyLockList(lu.needed_locks[locking.LEVEL_NODE])


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
      TLMigrateInstance(self, self.op.instance_uuid, self.op.instance_name,
                        self.op.cleanup, True, False,
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
    source_node_uuid = instance.primary_node
    target_node_uuid = self._migrater.target_node_uuid
    env = {
      "IGNORE_CONSISTENCY": self.op.ignore_consistency,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      "OLD_PRIMARY": self.cfg.GetNodeName(source_node_uuid),
      "NEW_PRIMARY": self.cfg.GetNodeName(target_node_uuid),
      "FAILOVER_CLEANUP": self.op.cleanup,
      }

    if instance.disk_template in constants.DTS_INT_MIRROR:
      env["OLD_SECONDARY"] = self.cfg.GetNodeName(instance.secondary_nodes[0])
      env["NEW_SECONDARY"] = self.cfg.GetNodeName(source_node_uuid)
    else:
      env["OLD_SECONDARY"] = env["NEW_SECONDARY"] = ""

    env.update(BuildInstanceHookEnvByObject(self, instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self._migrater.instance
    nl = [self.cfg.GetMasterNode()] + list(instance.secondary_nodes)
    nl.append(self._migrater.target_node_uuid)
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
      TLMigrateInstance(self, self.op.instance_uuid, self.op.instance_name,
                        self.op.cleanup, False, self.op.allow_failover, False,
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
    source_node_uuid = instance.primary_node
    target_node_uuid = self._migrater.target_node_uuid
    env = BuildInstanceHookEnvByObject(self, instance)
    env.update({
      "MIGRATE_LIVE": self._migrater.live,
      "MIGRATE_CLEANUP": self.op.cleanup,
      "OLD_PRIMARY": self.cfg.GetNodeName(source_node_uuid),
      "NEW_PRIMARY": self.cfg.GetNodeName(target_node_uuid),
      "ALLOW_RUNTIME_CHANGES": self.op.allow_runtime_changes,
      })

    if instance.disk_template in constants.DTS_INT_MIRROR:
      env["OLD_SECONDARY"] = self.cfg.GetNodeName(instance.secondary_nodes[0])
      env["NEW_SECONDARY"] = self.cfg.GetNodeName(source_node_uuid)
    else:
      env["OLD_SECONDARY"] = env["NEW_SECONDARY"] = ""

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    instance = self._migrater.instance
    snode_uuids = list(instance.secondary_nodes)
    nl = [self.cfg.GetMasterNode(), instance.primary_node] + snode_uuids
    nl.append(self._migrater.target_node_uuid)
    return (nl, nl)


class TLMigrateInstance(Tasklet):
  """Tasklet class for instance migration.

  @type live: boolean
  @ivar live: whether the migration will be done live or non-live;
      this variable is initalized only after CheckPrereq has run
  @type cleanup: boolean
  @ivar cleanup: Wheater we cleanup from a failed migration
  @type iallocator: string
  @ivar iallocator: The iallocator used to determine target_node
  @type target_node_uuid: string
  @ivar target_node_uuid: If given, the target node UUID to reallocate the
      instance to
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

  def __init__(self, lu, instance_uuid, instance_name, cleanup, failover,
               fallback, ignore_consistency, allow_runtime_changes,
               shutdown_timeout, ignore_ipolicy):
    """Initializes this class.

    """
    Tasklet.__init__(self, lu)

    # Parameters
    self.instance_uuid = instance_uuid
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
    (self.instance_uuid, self.instance_name) = \
      ExpandInstanceUuidAndName(self.lu.cfg, self.instance_uuid,
                                self.instance_name)
    self.instance = self.cfg.GetInstanceInfo(self.instance_uuid)
    assert self.instance is not None
    cluster = self.cfg.GetClusterInfo()

    if (not self.cleanup and
        not self.instance.admin_state == constants.ADMINST_UP and
        not self.failover and self.fallback):
      self.lu.LogInfo("Instance is marked down or offline, fallback allowed,"
                      " switching to failover")
      self.failover = True

    if self.instance.disk_template not in constants.DTS_MIRRORED:
      if self.failover:
        text = "failovers"
      else:
        text = "migrations"
      raise errors.OpPrereqError("Instance's disk layout '%s' does not allow"
                                 " %s" % (self.instance.disk_template, text),
                                 errors.ECODE_STATE)

    if self.instance.disk_template in constants.DTS_EXT_MIRROR:
      CheckIAllocatorOrNode(self.lu, "iallocator", "target_node")

      if self.lu.op.iallocator:
        assert locking.NAL in self.lu.owned_locks(locking.LEVEL_NODE_ALLOC)
        self._RunAllocator()
      else:
        # We set set self.target_node_uuid as it is required by
        # BuildHooksEnv
        self.target_node_uuid = self.lu.op.target_node_uuid

      # Check that the target node is correct in terms of instance policy
      nodeinfo = self.cfg.GetNodeInfo(self.target_node_uuid)
      group_info = self.cfg.GetNodeGroup(nodeinfo.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)
      CheckTargetNodeIPolicy(self.lu, ipolicy, self.instance, nodeinfo,
                             self.cfg, ignore=self.ignore_ipolicy)

      # self.target_node is already populated, either directly or by the
      # iallocator run
      target_node_uuid = self.target_node_uuid
      if self.target_node_uuid == self.instance.primary_node:
        raise errors.OpPrereqError(
          "Cannot migrate instance %s to its primary (%s)" %
          (self.instance.name,
           self.cfg.GetNodeName(self.instance.primary_node)),
          errors.ECODE_STATE)

      if len(self.lu.tasklets) == 1:
        # It is safe to release locks only when we're the only tasklet
        # in the LU
        ReleaseLocks(self.lu, locking.LEVEL_NODE,
                     keep=[self.instance.primary_node, self.target_node_uuid])
        ReleaseLocks(self.lu, locking.LEVEL_NODE_ALLOC)

    else:
      assert not self.lu.glm.is_owned(locking.LEVEL_NODE_ALLOC)

      secondary_node_uuids = self.instance.secondary_nodes
      if not secondary_node_uuids:
        raise errors.ConfigurationError("No secondary node but using"
                                        " %s disk template" %
                                        self.instance.disk_template)
      self.target_node_uuid = target_node_uuid = secondary_node_uuids[0]
      if self.lu.op.iallocator or \
        (self.lu.op.target_node_uuid and
         self.lu.op.target_node_uuid != target_node_uuid):
        if self.failover:
          text = "failed over"
        else:
          text = "migrated"
        raise errors.OpPrereqError("Instances with disk template %s cannot"
                                   " be %s to arbitrary nodes"
                                   " (neither an iallocator nor a target"
                                   " node can be passed)" %
                                   (self.instance.disk_template, text),
                                   errors.ECODE_INVAL)
      nodeinfo = self.cfg.GetNodeInfo(target_node_uuid)
      group_info = self.cfg.GetNodeGroup(nodeinfo.group)
      ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                              group_info)
      CheckTargetNodeIPolicy(self.lu, ipolicy, self.instance, nodeinfo,
                             self.cfg, ignore=self.ignore_ipolicy)

    i_be = cluster.FillBE(self.instance)

    # check memory requirements on the secondary node
    if (not self.cleanup and
         (not self.failover or
           self.instance.admin_state == constants.ADMINST_UP)):
      self.tgt_free_mem = CheckNodeFreeMemory(
          self.lu, target_node_uuid,
          "migrating instance %s" % self.instance.name,
          i_be[constants.BE_MINMEM], self.instance.hypervisor,
          self.cfg.GetClusterInfo().hvparams[self.instance.hypervisor])
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
    CheckInstanceBridgesExist(self.lu, self.instance,
                              node_uuid=target_node_uuid)

    if not self.cleanup:
      CheckNodeNotDrained(self.lu, target_node_uuid)
      if not self.failover:
        result = self.rpc.call_instance_migratable(self.instance.primary_node,
                                                   self.instance)
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
      remote_info = self.rpc.call_instance_info(
          self.instance.primary_node, self.instance.name,
          self.instance.hypervisor, cluster.hvparams[self.instance.hypervisor])
      remote_info.Raise("Error checking instance on node %s" %
                        self.cfg.GetNodeName(self.instance.primary_node))
      instance_running = bool(remote_info.payload)
      if instance_running:
        self.current_mem = int(remote_info.payload["memory"])

  def _RunAllocator(self):
    """Run the allocator based on input opcode.

    """
    assert locking.NAL in self.lu.owned_locks(locking.LEVEL_NODE_ALLOC)

    # FIXME: add a self.ignore_ipolicy option
    req = iallocator.IAReqRelocate(
          inst_uuid=self.instance_uuid,
          relocate_from_node_uuids=[self.instance.primary_node])
    ial = iallocator.IAllocator(self.cfg, self.rpc, req)

    ial.Run(self.lu.op.iallocator)

    if not ial.success:
      raise errors.OpPrereqError("Can't compute nodes using"
                                 " iallocator '%s': %s" %
                                 (self.lu.op.iallocator, ial.info),
                                 errors.ECODE_NORES)
    self.target_node_uuid = self.cfg.GetNodeInfoByName(ial.result[0]).uuid
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
      result = self.rpc.call_drbd_wait_sync(self.all_node_uuids,
                                            (self.instance.disks,
                                             self.instance))
      min_percent = 100
      for node_uuid, nres in result.items():
        nres.Raise("Cannot resync disks on node %s" %
                   self.cfg.GetNodeName(node_uuid))
        node_done, node_percent = nres.payload
        all_done = all_done and node_done
        if node_percent is not None:
          min_percent = min(min_percent, node_percent)
      if not all_done:
        if min_percent < 100:
          self.feedback_fn("   - progress: %.1f%%" % min_percent)
        time.sleep(2)

  def _EnsureSecondary(self, node_uuid):
    """Demote a node to secondary.

    """
    self.feedback_fn("* switching node %s to secondary mode" %
                     self.cfg.GetNodeName(node_uuid))

    result = self.rpc.call_blockdev_close(node_uuid, self.instance.name,
                                          (self.instance.disks, self.instance))
    result.Raise("Cannot change disk to secondary on node %s" %
                 self.cfg.GetNodeName(node_uuid))

  def _GoStandalone(self):
    """Disconnect from the network.

    """
    self.feedback_fn("* changing into standalone mode")
    result = self.rpc.call_drbd_disconnect_net(
               self.all_node_uuids, (self.instance.disks, self.instance))
    for node_uuid, nres in result.items():
      nres.Raise("Cannot disconnect disks node %s" %
                 self.cfg.GetNodeName(node_uuid))

  def _GoReconnect(self, multimaster):
    """Reconnect to the network.

    """
    if multimaster:
      msg = "dual-master"
    else:
      msg = "single-master"
    self.feedback_fn("* changing disks into %s mode" % msg)
    result = self.rpc.call_drbd_attach_net(self.all_node_uuids,
                                           (self.instance.disks, self.instance),
                                           self.instance.name, multimaster)
    for node_uuid, nres in result.items():
      nres.Raise("Cannot change disks config on node %s" %
                 self.cfg.GetNodeName(node_uuid))

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
    # check running on only one node
    self.feedback_fn("* checking where the instance actually runs"
                     " (if this hangs, the hypervisor might be in"
                     " a bad state)")
    cluster_hvparams = self.cfg.GetClusterInfo().hvparams
    ins_l = self.rpc.call_instance_list(self.all_node_uuids,
                                        [self.instance.hypervisor],
                                        cluster_hvparams)
    for node_uuid, result in ins_l.items():
      result.Raise("Can't contact node %s" % node_uuid)

    runningon_source = self.instance.name in \
                         ins_l[self.source_node_uuid].payload
    runningon_target = self.instance.name in \
                         ins_l[self.target_node_uuid].payload

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
                       " updating config" %
                       self.cfg.GetNodeName(self.target_node_uuid))
      self.instance.primary_node = self.target_node_uuid
      self.cfg.Update(self.instance, self.feedback_fn)
      demoted_node_uuid = self.source_node_uuid
    else:
      self.feedback_fn("* instance confirmed to be running on its"
                       " primary node (%s)" %
                       self.cfg.GetNodeName(self.source_node_uuid))
      demoted_node_uuid = self.target_node_uuid

    if self.instance.disk_template in constants.DTS_INT_MIRROR:
      self._EnsureSecondary(demoted_node_uuid)
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
    if self.instance.disk_template in constants.DTS_EXT_MIRROR:
      return

    try:
      self._EnsureSecondary(self.target_node_uuid)
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
    abort_result = self.rpc.call_instance_finalize_migration_dst(
                     self.target_node_uuid, self.instance, self.migration_info,
                     False)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on target node %s: %s",
                    self.cfg.GetNodeName(self.target_node_uuid), abort_msg)
      # Don't raise an exception here, as we stil have to try to revert the
      # disk status, even if this step failed.

    abort_result = self.rpc.call_instance_finalize_migration_src(
      self.source_node_uuid, self.instance, False, self.live)
    abort_msg = abort_result.fail_msg
    if abort_msg:
      logging.error("Aborting migration failed on source node %s: %s",
                    self.cfg.GetNodeName(self.source_node_uuid), abort_msg)

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
    # Check for hypervisor version mismatch and warn the user.
    hvspecs = [(self.instance.hypervisor,
                self.cfg.GetClusterInfo().hvparams[self.instance.hypervisor])]
    nodeinfo = self.rpc.call_node_info(
                 [self.source_node_uuid, self.target_node_uuid], None, hvspecs)
    for ninfo in nodeinfo.values():
      ninfo.Raise("Unable to retrieve node information from node '%s'" %
                  ninfo.node)
    (_, _, (src_info, )) = nodeinfo[self.source_node_uuid].payload
    (_, _, (dst_info, )) = nodeinfo[self.target_node_uuid].payload

    if ((constants.HV_NODEINFO_KEY_VERSION in src_info) and
        (constants.HV_NODEINFO_KEY_VERSION in dst_info)):
      src_version = src_info[constants.HV_NODEINFO_KEY_VERSION]
      dst_version = dst_info[constants.HV_NODEINFO_KEY_VERSION]
      if src_version != dst_version:
        self.feedback_fn("* warning: hypervisor version mismatch between"
                         " source (%s) and target (%s) node" %
                         (src_version, dst_version))

    self.feedback_fn("* checking disk consistency between source and target")
    for (idx, dev) in enumerate(self.instance.disks):
      if not CheckDiskConsistency(self.lu, self.instance, dev,
                                  self.target_node_uuid,
                                  False):
        raise errors.OpExecError("Disk %s is degraded or not fully"
                                 " synchronized on target node,"
                                 " aborting migration" % idx)

    if self.current_mem > self.tgt_free_mem:
      if not self.allow_runtime_changes:
        raise errors.OpExecError("Memory ballooning not allowed and not enough"
                                 " free memory to fit instance %s on target"
                                 " node %s (have %dMB, need %dMB)" %
                                 (self.instance.name,
                                  self.cfg.GetNodeName(self.target_node_uuid),
                                  self.tgt_free_mem, self.current_mem))
      self.feedback_fn("* setting instance memory to %s" % self.tgt_free_mem)
      rpcres = self.rpc.call_instance_balloon_memory(self.instance.primary_node,
                                                     self.instance,
                                                     self.tgt_free_mem)
      rpcres.Raise("Cannot modify instance runtime memory")

    # First get the migration information from the remote node
    result = self.rpc.call_migration_info(self.source_node_uuid, self.instance)
    msg = result.fail_msg
    if msg:
      log_err = ("Failed fetching source migration information from %s: %s" %
                 (self.cfg.GetNodeName(self.source_node_uuid), msg))
      logging.error(log_err)
      raise errors.OpExecError(log_err)

    self.migration_info = migration_info = result.payload

    if self.instance.disk_template not in constants.DTS_EXT_MIRROR:
      # Then switch the disks to master/master mode
      self._EnsureSecondary(self.target_node_uuid)
      self._GoStandalone()
      self._GoReconnect(True)
      self._WaitUntilSync()

    self.feedback_fn("* preparing %s to accept the instance" %
                     self.cfg.GetNodeName(self.target_node_uuid))
    result = self.rpc.call_accept_instance(self.target_node_uuid,
                                           self.instance,
                                           migration_info,
                                           self.nodes_ip[self.target_node_uuid])

    msg = result.fail_msg
    if msg:
      logging.error("Instance pre-migration failed, trying to revert"
                    " disk status: %s", msg)
      self.feedback_fn("Pre-migration failed, aborting")
      self._AbortMigration()
      self._RevertDiskStatus()
      raise errors.OpExecError("Could not pre-migrate instance %s: %s" %
                               (self.instance.name, msg))

    self.feedback_fn("* migrating instance to %s" %
                     self.cfg.GetNodeName(self.target_node_uuid))
    cluster = self.cfg.GetClusterInfo()
    result = self.rpc.call_instance_migrate(
        self.source_node_uuid, cluster.cluster_name, self.instance,
        self.nodes_ip[self.target_node_uuid], self.live)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration failed, trying to revert"
                    " disk status: %s", msg)
      self.feedback_fn("Migration failed, aborting")
      self._AbortMigration()
      self._RevertDiskStatus()
      raise errors.OpExecError("Could not migrate instance %s: %s" %
                               (self.instance.name, msg))

    self.feedback_fn("* starting memory transfer")
    last_feedback = time.time()
    while True:
      result = self.rpc.call_instance_get_migration_status(
                 self.source_node_uuid, self.instance)
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
                                 (self.instance.name, msg))

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

    result = self.rpc.call_instance_finalize_migration_src(
               self.source_node_uuid, self.instance, True, self.live)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed"
                    " on the source node: %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    self.instance.primary_node = self.target_node_uuid

    # distribute new instance config to the other nodes
    self.cfg.Update(self.instance, self.feedback_fn)

    result = self.rpc.call_instance_finalize_migration_dst(
               self.target_node_uuid, self.instance, migration_info, True)
    msg = result.fail_msg
    if msg:
      logging.error("Instance migration succeeded, but finalization failed"
                    " on the target node: %s", msg)
      raise errors.OpExecError("Could not finalize instance migration: %s" %
                               msg)

    if self.instance.disk_template not in constants.DTS_EXT_MIRROR:
      self._EnsureSecondary(self.source_node_uuid)
      self._WaitUntilSync()
      self._GoStandalone()
      self._GoReconnect(False)
      self._WaitUntilSync()

    # If the instance's disk template is `rbd' or `ext' and there was a
    # successful migration, unmap the device from the source node.
    if self.instance.disk_template in (constants.DT_RBD, constants.DT_EXT):
      disks = ExpandCheckDisks(self.instance, self.instance.disks)
      self.feedback_fn("* unmapping instance's disks from %s" %
                       self.cfg.GetNodeName(self.source_node_uuid))
      for disk in disks:
        result = self.rpc.call_blockdev_shutdown(self.source_node_uuid,
                                                 (disk, self.instance))
        msg = result.fail_msg
        if msg:
          logging.error("Migration was successful, but couldn't unmap the"
                        " block device %s on source node %s: %s",
                        disk.iv_name,
                        self.cfg.GetNodeName(self.source_node_uuid), msg)
          logging.error("You need to unmap the device %s manually on %s",
                        disk.iv_name,
                        self.cfg.GetNodeName(self.source_node_uuid))

    self.feedback_fn("* done")

  def _ExecFailover(self):
    """Failover an instance.

    The failover is done by shutting it down on its present node and
    starting it on the secondary.

    """
    primary_node = self.cfg.GetNodeInfo(self.instance.primary_node)

    source_node_uuid = self.instance.primary_node

    if self.instance.disks_active:
      self.feedback_fn("* checking disk consistency between source and target")
      for (idx, dev) in enumerate(self.instance.disks):
        # for drbd, these are drbd over lvm
        if not CheckDiskConsistency(self.lu, self.instance, dev,
                                    self.target_node_uuid, False):
          if primary_node.offline:
            self.feedback_fn("Node %s is offline, ignoring degraded disk %s on"
                             " target node %s" %
                             (primary_node.name, idx,
                              self.cfg.GetNodeName(self.target_node_uuid)))
          elif not self.ignore_consistency:
            raise errors.OpExecError("Disk %s is degraded on target node,"
                                     " aborting failover" % idx)
    else:
      self.feedback_fn("* not checking disk consistency as instance is not"
                       " running")

    self.feedback_fn("* shutting down instance on source node")
    logging.info("Shutting down instance %s on node %s",
                 self.instance.name, self.cfg.GetNodeName(source_node_uuid))

    result = self.rpc.call_instance_shutdown(source_node_uuid, self.instance,
                                             self.shutdown_timeout,
                                             self.lu.op.reason)
    msg = result.fail_msg
    if msg:
      if self.ignore_consistency or primary_node.offline:
        self.lu.LogWarning("Could not shutdown instance %s on node %s,"
                           " proceeding anyway; please make sure node"
                           " %s is down; error details: %s",
                           self.instance.name,
                           self.cfg.GetNodeName(source_node_uuid),
                           self.cfg.GetNodeName(source_node_uuid), msg)
      else:
        raise errors.OpExecError("Could not shutdown instance %s on"
                                 " node %s: %s" %
                                 (self.instance.name,
                                  self.cfg.GetNodeName(source_node_uuid), msg))

    self.feedback_fn("* deactivating the instance's disks on source node")
    if not ShutdownInstanceDisks(self.lu, self.instance, ignore_primary=True):
      raise errors.OpExecError("Can't shut down the instance's disks")

    self.instance.primary_node = self.target_node_uuid
    # distribute new instance config to the other nodes
    self.cfg.Update(self.instance, self.feedback_fn)

    # Only start the instance if it's marked as up
    if self.instance.admin_state == constants.ADMINST_UP:
      self.feedback_fn("* activating the instance's disks on target node %s" %
                       self.cfg.GetNodeName(self.target_node_uuid))
      logging.info("Starting instance %s on node %s", self.instance.name,
                   self.cfg.GetNodeName(self.target_node_uuid))

      disks_ok, _ = AssembleInstanceDisks(self.lu, self.instance,
                                          ignore_secondaries=True)
      if not disks_ok:
        ShutdownInstanceDisks(self.lu, self.instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      self.feedback_fn("* starting the instance on the target node %s" %
                       self.cfg.GetNodeName(self.target_node_uuid))
      result = self.rpc.call_instance_start(self.target_node_uuid,
                                            (self.instance, None, None), False,
                                            self.lu.op.reason)
      msg = result.fail_msg
      if msg:
        ShutdownInstanceDisks(self.lu, self.instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (self.instance.name,
                                  self.cfg.GetNodeName(self.target_node_uuid),
                                  msg))

  def Exec(self, feedback_fn):
    """Perform the migration.

    """
    self.feedback_fn = feedback_fn
    self.source_node_uuid = self.instance.primary_node

    # FIXME: if we implement migrate-to-any in DRBD, this needs fixing
    if self.instance.disk_template in constants.DTS_INT_MIRROR:
      self.target_node_uuid = self.instance.secondary_nodes[0]
      # Otherwise self.target_node has been populated either
      # directly, or through an iallocator.

    self.all_node_uuids = [self.source_node_uuid, self.target_node_uuid]
    self.nodes_ip = dict((uuid, node.secondary_ip) for (uuid, node)
                         in self.cfg.GetMultiNodeInfo(self.all_node_uuids))

    if self.failover:
      feedback_fn("Failover instance %s" % self.instance.name)
      self._ExecFailover()
    else:
      feedback_fn("Migrating instance %s" % self.instance.name)

      if self.cleanup:
        return self._ExecCleanup()
      else:
        return self._ExecMigration()
