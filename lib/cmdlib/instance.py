#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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


"""Logical units dealing with instances."""

import logging
import os

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti.masterd import iallocator
from ganeti import masterd
from ganeti import netutils
from ganeti import objects
from ganeti import utils

from ganeti.cmdlib.base import NoHooksLU, LogicalUnit, ResultWithJobs

from ganeti.cmdlib.common import \
  INSTANCE_NOT_RUNNING, CheckNodeOnline, \
  ShareAll, GetDefaultIAllocator, CheckInstanceNodeGroups, \
  LoadNodeEvacResult, \
  ExpandInstanceUuidAndName, \
  CheckInstanceState, ExpandNodeUuidAndName, \
  CheckDiskTemplateEnabled
from ganeti.cmdlib.instance_storage import CreateDisks, \
  ComputeDisks, \
  StartInstanceDisks, ShutdownInstanceDisks, \
  AssembleInstanceDisks
from ganeti.cmdlib.instance_utils import \
  BuildInstanceHookEnvByObject,\
  CheckNodeNotDrained, RemoveInstance, CopyLockList, \
  CheckNodeVmCapable, CheckTargetNodeIPolicy, \
  GetInstanceInfoText, RemoveDisks, CheckNodeFreeMemory, \
  CheckInstanceBridgesExist, \
  CheckInstanceExistence, \
  CheckHostnameSane, CheckOpportunisticLocking, ComputeFullBeParams, \
  ComputeNics, CreateInstanceAllocRequest
import ganeti.masterd.instance


class LUInstanceRename(LogicalUnit):
  """Rename an instance.

  """
  HPATH = "instance-rename"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check arguments.

    """
    if self.op.ip_check and not self.op.name_check:
      # TODO: make the ip check more flexible and not depend on the name check
      raise errors.OpPrereqError("IP address check requires a name check",
                                 errors.ECODE_INVAL)

    self._new_name_resolved = False

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = BuildInstanceHookEnvByObject(self, self.instance)
    env["INSTANCE_NEW_NAME"] = self.op.new_name
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + \
      list(self.cfg.GetInstanceNodes(self.instance.uuid))
    return (nl, nl)

  def _PerformChecksAndResolveNewName(self):
    """Checks and resolves the new name, storing the FQDN, if permitted.

    """
    if self._new_name_resolved or not self.op.name_check:
      return

    hostname = CheckHostnameSane(self, self.op.new_name)
    self.op.new_name = hostname.name
    if (self.op.ip_check and
        netutils.TcpPing(hostname.ip, constants.DEFAULT_NODED_PORT)):
      raise errors.OpPrereqError("IP %s of instance %s already in use" %
                                 (hostname.ip, self.op.new_name),
                                 errors.ECODE_NOTUNIQUE)
    self._new_name_resolved = True

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    (self.op.instance_uuid, self.op.instance_name) = \
      ExpandInstanceUuidAndName(self.cfg, self.op.instance_uuid,
                                self.op.instance_name)
    instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert instance is not None

    # It should actually not happen that an instance is running with a disabled
    # disk template, but in case it does, the renaming of file-based instances
    # will fail horribly. Thus, we test it before.
    for disk in self.cfg.GetInstanceDisks(instance.uuid):
      if (disk.dev_type in constants.DTS_FILEBASED and
          self.op.new_name != instance.name):
        # TODO: when disks are separate objects, this should check for disk
        # types, not disk templates.
        CheckDiskTemplateEnabled(self.cfg.GetClusterInfo(), disk.dev_type)

    CheckNodeOnline(self, instance.primary_node)
    CheckInstanceState(self, instance, INSTANCE_NOT_RUNNING,
                       msg="cannot rename")
    self.instance = instance

    self._PerformChecksAndResolveNewName()

    if self.op.new_name != instance.name:
      CheckInstanceExistence(self, self.op.new_name)

  def ExpandNames(self):
    self._ExpandAndLockInstance(allow_forthcoming=True)

    # Note that this call might not resolve anything if name checks have been
    # disabled in the opcode. In this case, we might have a renaming collision
    # if a shortened name and a full name are used simultaneously, as we will
    # have two different locks. However, at that point the user has taken away
    # the tools necessary to detect this issue.
    self._PerformChecksAndResolveNewName()

    # Used to prevent instance namespace collisions.
    if self.op.new_name != self.op.instance_name:
      CheckInstanceExistence(self, self.op.new_name)
      self.add_locks[locking.LEVEL_INSTANCE] = self.op.new_name

  def Exec(self, feedback_fn):
    """Rename the instance.

    """
    old_name = self.instance.name

    rename_file_storage = False
    disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    renamed_storage = [d for d in disks
                       if (d.dev_type in constants.DTS_FILEBASED and
                           d.dev_type != constants.DT_GLUSTER)]
    if renamed_storage and self.op.new_name != self.instance.name:
      disks = self.cfg.GetInstanceDisks(self.instance.uuid)
      old_file_storage_dir = os.path.dirname(disks[0].logical_id[1])
      rename_file_storage = True

    self.cfg.RenameInstance(self.instance.uuid, self.op.new_name)

    # Assert that we have both the locks needed
    assert old_name in self.owned_locks(locking.LEVEL_INSTANCE)
    assert self.op.new_name in self.owned_locks(locking.LEVEL_INSTANCE)

    # re-read the instance from the configuration after rename
    renamed_inst = self.cfg.GetInstanceInfo(self.instance.uuid)
    disks = self.cfg.GetInstanceDisks(renamed_inst.uuid)

    if self.instance.forthcoming:
      return renamed_inst.name

    if rename_file_storage:
      new_file_storage_dir = os.path.dirname(disks[0].logical_id[1])
      result = self.rpc.call_file_storage_dir_rename(renamed_inst.primary_node,
                                                     old_file_storage_dir,
                                                     new_file_storage_dir)
      result.Raise("Could not rename on node %s directory '%s' to '%s'"
                   " (but the instance has been renamed in Ganeti)" %
                   (self.cfg.GetNodeName(renamed_inst.primary_node),
                    old_file_storage_dir, new_file_storage_dir))

    StartInstanceDisks(self, renamed_inst, None)
    renamed_inst = self.cfg.GetInstanceInfo(renamed_inst.uuid)

    # update info on disks
    info = GetInstanceInfoText(renamed_inst)
    for (idx, disk) in enumerate(disks):
      for node_uuid in self.cfg.GetInstanceNodes(renamed_inst.uuid):
        result = self.rpc.call_blockdev_setinfo(node_uuid,
                                                (disk, renamed_inst), info)
        result.Warn("Error setting info on node %s for disk %s" %
                    (self.cfg.GetNodeName(node_uuid), idx), self.LogWarning)
    try:
      result = self.rpc.call_instance_run_rename(renamed_inst.primary_node,
                                                 renamed_inst, old_name,
                                                 self.op.debug_level)
      result.Warn("Could not run OS rename script for instance %s on node %s"
                  " (but the instance has been renamed in Ganeti)" %
                  (renamed_inst.name,
                   self.cfg.GetNodeName(renamed_inst.primary_node)),
                  self.LogWarning)
    finally:
      ShutdownInstanceDisks(self, renamed_inst)

    return renamed_inst.name


class LUInstanceRemove(LogicalUnit):
  """Remove an instance.

  """
  HPATH = "instance-remove"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance(allow_forthcoming=True)
    self.needed_locks[locking.LEVEL_NODE] = []
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_REPLACE
    self.dont_collate_locks[locking.LEVEL_NODE] = True
    self.dont_collate_locks[locking.LEVEL_NODE_RES] = True

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes()
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = BuildInstanceHookEnvByObject(self, self.instance,
                                       secondary_nodes=self.secondary_nodes,
                                       disks=self.inst_disks)
    env["SHUTDOWN_TIMEOUT"] = self.op.shutdown_timeout
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()]
    nl_post = list(self.cfg.GetInstanceNodes(self.instance.uuid)) + nl
    return (nl, nl_post)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    self.secondary_nodes = \
      self.cfg.GetInstanceSecondaryNodes(self.instance.uuid)
    self.inst_disks = self.cfg.GetInstanceDisks(self.instance.uuid)

  def Exec(self, feedback_fn):
    """Remove the instance.

    """
    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))
    assert not (set(self.cfg.GetInstanceNodes(self.instance.uuid)) -
                self.owned_locks(locking.LEVEL_NODE)), \
      "Not owning correct locks"

    if not self.instance.forthcoming:
      logging.info("Shutting down instance %s on node %s", self.instance.name,
                   self.cfg.GetNodeName(self.instance.primary_node))

      result = self.rpc.call_instance_shutdown(self.instance.primary_node,
                                               self.instance,
                                               self.op.shutdown_timeout,
                                               self.op.reason)
      if self.op.ignore_failures:
        result.Warn("Warning: can't shutdown instance", feedback_fn)
      else:
        result.Raise("Could not shutdown instance %s on node %s" %
                     (self.instance.name,
                      self.cfg.GetNodeName(self.instance.primary_node)))
    else:
      logging.info("Instance %s on node %s is forthcoming; not shutting down",
                   self.instance.name,
                   self.cfg.GetNodeName(self.instance.primary_node))

    RemoveInstance(self, feedback_fn, self.instance, self.op.ignore_failures)


class LUInstanceMove(LogicalUnit):
  """Move an instance by data-copying.

  This LU is only used if the instance needs to be moved by copying the data
  from one node in the cluster to another. The instance is shut down and
  the data is copied to the new node and the configuration change is propagated,
  then the instance is started again.

  See also:
  L{LUInstanceFailover} for moving an instance on shared storage (no copying
  required).

  L{LUInstanceMigrate} for the live migration of an instance (no shutdown
  required).
  """
  HPATH = "instance-move"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    (self.op.target_node_uuid, self.op.target_node) = \
      ExpandNodeUuidAndName(self.cfg, self.op.target_node_uuid,
                            self.op.target_node)
    self.needed_locks[locking.LEVEL_NODE] = [self.op.target_node_uuid]
    self.needed_locks[locking.LEVEL_NODE_RES] = []
    self.recalculate_locks[locking.LEVEL_NODE] = constants.LOCKS_APPEND

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      self._LockInstancesNodes(primary_only=True)
    elif level == locking.LEVEL_NODE_RES:
      # Copy node locks
      self.needed_locks[locking.LEVEL_NODE_RES] = \
        CopyLockList(self.needed_locks[locking.LEVEL_NODE])

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and target nodes of the instance.

    """
    env = {
      "TARGET_NODE": self.op.target_node,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }
    env.update(BuildInstanceHookEnvByObject(self, self.instance))
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [
      self.cfg.GetMasterNode(),
      self.instance.primary_node,
      self.op.target_node_uuid,
      ]
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    for idx, dsk in enumerate(disks):
      if dsk.dev_type not in constants.DTS_COPYABLE:
        raise errors.OpPrereqError("Instance disk %d has disk type %s and is"
                                   " not suitable for copying"
                                   % (idx, dsk.dev_type), errors.ECODE_STATE)

    target_node = self.cfg.GetNodeInfo(self.op.target_node_uuid)
    assert target_node is not None, \
      "Cannot retrieve locked node %s" % self.op.target_node

    self.target_node_uuid = target_node.uuid
    if target_node.uuid == self.instance.primary_node:
      raise errors.OpPrereqError("Instance %s is already on the node %s" %
                                 (self.instance.name, target_node.name),
                                 errors.ECODE_STATE)

    cluster = self.cfg.GetClusterInfo()
    bep = cluster.FillBE(self.instance)

    CheckNodeOnline(self, target_node.uuid)
    CheckNodeNotDrained(self, target_node.uuid)
    CheckNodeVmCapable(self, target_node.uuid)
    group_info = self.cfg.GetNodeGroup(target_node.group)
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster, group_info)
    CheckTargetNodeIPolicy(self, ipolicy, self.instance, target_node, self.cfg,
                           ignore=self.op.ignore_ipolicy)

    if self.instance.admin_state == constants.ADMINST_UP:
      # check memory requirements on the target node
      CheckNodeFreeMemory(
          self, target_node.uuid, "failing over instance %s" %
          self.instance.name, bep[constants.BE_MAXMEM],
          self.instance.hypervisor,
          cluster.hvparams[self.instance.hypervisor])
    else:
      self.LogInfo("Not checking memory on the secondary node as"
                   " instance will not be started")

    # check bridge existance
    CheckInstanceBridgesExist(self, self.instance, node_uuid=target_node.uuid)

  def Exec(self, feedback_fn):
    """Move an instance.

    The move is done by shutting it down on its present node, copying
    the data over (slow) and starting it on the new node.

    """
    source_node = self.cfg.GetNodeInfo(self.instance.primary_node)
    target_node = self.cfg.GetNodeInfo(self.target_node_uuid)

    self.LogInfo("Shutting down instance %s on source node %s",
                 self.instance.name, source_node.name)

    assert (self.owned_locks(locking.LEVEL_NODE) ==
            self.owned_locks(locking.LEVEL_NODE_RES))

    result = self.rpc.call_instance_shutdown(source_node.uuid, self.instance,
                                             self.op.shutdown_timeout,
                                             self.op.reason)
    if self.op.ignore_consistency:
      result.Warn("Could not shutdown instance %s on node %s. Proceeding"
                  " anyway. Please make sure node %s is down. Error details" %
                  (self.instance.name, source_node.name, source_node.name),
                  self.LogWarning)
    else:
      result.Raise("Could not shutdown instance %s on node %s" %
                   (self.instance.name, source_node.name))

    # create the target disks
    try:
      CreateDisks(self, self.instance, target_node_uuid=target_node.uuid)
    except errors.OpExecError:
      self.LogWarning("Device creation failed")
      for disk_uuid in self.instance.disks:
        self.cfg.ReleaseDRBDMinors(disk_uuid)
      raise

    errs = []
    transfers = []
    # activate, get path, create transfer jobs
    disks = self.cfg.GetInstanceDisks(self.instance.uuid)
    for idx, disk in enumerate(disks):
      # FIXME: pass debug option from opcode to backend
      dt = masterd.instance.DiskTransfer("disk/%s" % idx,
                                         constants.IEIO_RAW_DISK,
                                         (disk, self.instance),
                                         constants.IEIO_RAW_DISK,
                                         (disk, self.instance),
                                         None)
      transfers.append(dt)
      self.cfg.Update(disk, feedback_fn)

    import_result = \
      masterd.instance.TransferInstanceData(self, feedback_fn,
                                            source_node.uuid,
                                            target_node.uuid,
                                            target_node.secondary_ip,
                                            self.op.compress,
                                            self.instance, transfers)
    if not compat.all(import_result):
      errs.append("Failed to transfer instance data")

    if errs:
      self.LogWarning("Some disks failed to copy, aborting")
      try:
        RemoveDisks(self, self.instance, target_node_uuid=target_node.uuid)
      finally:
        for disk_uuid in self.instance.disks:
          self.cfg.ReleaseDRBDMinors(disk_uuid)
        raise errors.OpExecError("Errors during disk copy: %s" %
                                 (",".join(errs),))

    self.instance.primary_node = target_node.uuid
    self.cfg.Update(self.instance, feedback_fn)
    for disk in disks:
      self.cfg.SetDiskNodes(disk.uuid, [target_node.uuid])

    self.LogInfo("Removing the disks on the original node")
    RemoveDisks(self, self.instance, target_node_uuid=source_node.uuid)

    # Only start the instance if it's marked as up
    if self.instance.admin_state == constants.ADMINST_UP:
      self.LogInfo("Starting instance %s on node %s",
                   self.instance.name, target_node.name)

      disks_ok, _, _ = AssembleInstanceDisks(self, self.instance,
                                             ignore_secondaries=True)
      if not disks_ok:
        ShutdownInstanceDisks(self, self.instance)
        raise errors.OpExecError("Can't activate the instance's disks")

      result = self.rpc.call_instance_start(target_node.uuid,
                                            (self.instance, None, None), False,
                                            self.op.reason)
      msg = result.fail_msg
      if msg:
        ShutdownInstanceDisks(self, self.instance)
        raise errors.OpExecError("Could not start instance %s on node %s: %s" %
                                 (self.instance.name, target_node.name, msg))


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

    if not has_nodes and self.op.iallocator is None:
      default_iallocator = self.cfg.GetDefaultIAllocator()
      if default_iallocator:
        self.op.iallocator = default_iallocator
      else:
        raise errors.OpPrereqError("No iallocator or nodes on the instances"
                                   " given and no cluster-wide default"
                                   " iallocator found; please specify either"
                                   " an iallocator or nodes on the instances"
                                   " or set a cluster-wide default iallocator",
                                   errors.ECODE_INVAL)

    CheckOpportunisticLocking(self.op)

    dups = utils.FindDuplicates([op.instance_name for op in self.op.instances])
    if dups:
      raise errors.OpPrereqError("There are duplicate instance names: %s" %
                                 utils.CommaJoin(dups), errors.ECODE_INVAL)

  def ExpandNames(self):
    """Calculate the locks.

    """
    self.share_locks = ShareAll()
    self.needed_locks = {}

    if self.op.iallocator:
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET
      self.needed_locks[locking.LEVEL_NODE_RES] = locking.ALL_SET

      if self.op.opportunistic_locking:
        self.opportunistic_locks[locking.LEVEL_NODE] = True
        self.opportunistic_locks[locking.LEVEL_NODE_RES] = True
    else:
      nodeslist = []
      for inst in self.op.instances:
        (inst.pnode_uuid, inst.pnode) = \
          ExpandNodeUuidAndName(self.cfg, inst.pnode_uuid, inst.pnode)
        nodeslist.append(inst.pnode_uuid)
        if inst.snode is not None:
          (inst.snode_uuid, inst.snode) = \
            ExpandNodeUuidAndName(self.cfg, inst.snode_uuid, inst.snode)
          nodeslist.append(inst.snode_uuid)

      self.needed_locks[locking.LEVEL_NODE] = nodeslist
      # Lock resources of instance's primary and secondary nodes (copy to
      # prevent accidential modification)
      self.needed_locks[locking.LEVEL_NODE_RES] = list(nodeslist)

  def CheckPrereq(self):
    """Check prerequisite.

    """
    if self.op.iallocator:
      cluster = self.cfg.GetClusterInfo()
      default_vg = self.cfg.GetVGName()
      ec_id = self.proc.GetECId()

      if self.op.opportunistic_locking:
        # Only consider nodes for which a lock is held
        node_whitelist = self.cfg.GetNodeNames(
          set(self.owned_locks(locking.LEVEL_NODE)) &
          set(self.owned_locks(locking.LEVEL_NODE_RES)))
      else:
        node_whitelist = None

      insts = [CreateInstanceAllocRequest(op, ComputeDisks(op.disks,
                                                           op.disk_template,
                                                           default_vg),
                                          ComputeNics(op, cluster, None,
                                                      self.cfg, ec_id),
                                          ComputeFullBeParams(op, cluster),
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
    if self.op.iallocator:
      (allocatable, failed_insts) = self.ia_result # pylint: disable=W0633
      allocatable_insts = map(compat.fst, allocatable)
    else:
      allocatable_insts = [op.instance_name for op in self.op.instances]
      failed_insts = []

    return {
      constants.ALLOCATABLE_KEY: allocatable_insts,
      constants.FAILED_KEY: failed_insts,
      }

  def Exec(self, feedback_fn):
    """Executes the opcode.

    """
    jobs = []
    if self.op.iallocator:
      op2inst = dict((op.instance_name, op) for op in self.op.instances)
      (allocatable, failed) = self.ia_result # pylint: disable=W0633

      for (name, node_names) in allocatable:
        op = op2inst.pop(name)

        (op.pnode_uuid, op.pnode) = \
          ExpandNodeUuidAndName(self.cfg, None, node_names[0])
        if len(node_names) > 1:
          (op.snode_uuid, op.snode) = \
            ExpandNodeUuidAndName(self.cfg, None, node_names[1])

        jobs.append([op])

      missing = set(op2inst.keys()) - set(failed)
      assert not missing, \
        "Iallocator did return incomplete result: %s" % \
        utils.CommaJoin(missing)
    else:
      jobs.extend([op] for op in self.op.instances)

    return ResultWithJobs(jobs, **self._ConstructPartialResult())


class LUInstanceChangeGroup(LogicalUnit):
  HPATH = "instance-change-group"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = ShareAll()

    self.needed_locks = {
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],
      }

    self._ExpandAndLockInstance()

    if self.op.target_groups:
      self.req_target_uuids = map(self.cfg.LookupNodeGroup,
                                  self.op.target_groups)
    else:
      self.req_target_uuids = None

    self.op.iallocator = GetDefaultIAllocator(self.cfg, self.op.iallocator)

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODEGROUP:
      assert not self.needed_locks[locking.LEVEL_NODEGROUP]

      if self.req_target_uuids:
        lock_groups = set(self.req_target_uuids)

        # Lock all groups used by instance optimistically; this requires going
        # via the node before it's locked, requiring verification later on
        instance_groups = self.cfg.GetInstanceNodeGroups(self.op.instance_uuid)
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
        lock_groups = (frozenset(self.owned_locks(locking.LEVEL_NODEGROUP)) |
                       self.cfg.GetInstanceNodeGroups(self.op.instance_uuid))
        member_nodes = [node_uuid
                        for group in lock_groups
                        for node_uuid in self.cfg.GetNodeGroup(group).members]
        self.needed_locks[locking.LEVEL_NODE].extend(member_nodes)
      else:
        # Lock all nodes as all groups are potential targets
        self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

  def CheckPrereq(self):
    owned_instance_names = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    assert (self.req_target_uuids is None or
            owned_groups.issuperset(self.req_target_uuids))
    assert owned_instance_names == set([self.op.instance_name])

    # Get instance information
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)

    # Check if node groups for locked instance are still correct
    instance_all_nodes = self.cfg.GetInstanceNodes(self.instance.uuid)
    assert owned_nodes.issuperset(instance_all_nodes), \
      ("Instance %s's nodes changed while we kept the lock" %
       self.op.instance_name)

    inst_groups = CheckInstanceNodeGroups(self.cfg, self.op.instance_uuid,
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

    env.update(BuildInstanceHookEnvByObject(self, self.instance))

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

    jobs = LoadNodeEvacResult(self, ial.result, self.op.early_release, False)

    self.LogInfo("Iallocator returned %s job(s) for changing group of"
                 " instance '%s'", len(jobs), self.op.instance_name)

    return ResultWithJobs(jobs)
