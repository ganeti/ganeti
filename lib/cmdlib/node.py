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


"""Logical units dealing with nodes."""

import logging
import operator

from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import netutils
from ganeti import objects
from ganeti import opcodes
from ganeti import rpc
from ganeti import utils
from ganeti.masterd import iallocator

from ganeti.cmdlib.base import LogicalUnit, NoHooksLU, ResultWithJobs
from ganeti.cmdlib.common import CheckParamsNotGlobal, \
  MergeAndVerifyHvState, MergeAndVerifyDiskState, \
  IsExclusiveStorageEnabledNode, CheckNodePVs, \
  RedistributeAncillaryFiles, ExpandNodeUuidAndName, ShareAll, SupportsOob, \
  CheckInstanceState, INSTANCE_DOWN, GetUpdatedParams, \
  AdjustCandidatePool, CheckIAllocatorOrNode, LoadNodeEvacResult, \
  GetWantedNodes, MapInstanceLvsToNodes, RunPostHook, \
  FindFaultyInstanceDisks, CheckStorageTypeEnabled


def _DecideSelfPromotion(lu, exceptions=None):
  """Decide whether I should promote myself as a master candidate.

  """
  cp_size = lu.cfg.GetClusterInfo().candidate_pool_size
  mc_now, mc_should, _ = lu.cfg.GetMasterCandidateStats(exceptions)
  # the new node will increase mc_max with one, so:
  mc_should = min(mc_should + 1, cp_size)
  return mc_now < mc_should


def _CheckNodeHasSecondaryIP(lu, node, secondary_ip, prereq):
  """Ensure that a node has the given secondary ip.

  @type lu: L{LogicalUnit}
  @param lu: the LU on behalf of which we make the check
  @type node: L{objects.Node}
  @param node: the node to check
  @type secondary_ip: string
  @param secondary_ip: the ip to check
  @type prereq: boolean
  @param prereq: whether to throw a prerequisite or an execute error
  @raise errors.OpPrereqError: if the node doesn't have the ip,
  and prereq=True
  @raise errors.OpExecError: if the node doesn't have the ip, and prereq=False

  """
  # this can be called with a new node, which has no UUID yet, so perform the
  # RPC call using its name
  result = lu.rpc.call_node_has_ip_address(node.name, secondary_ip)
  result.Raise("Failure checking secondary ip on node %s" % node.name,
               prereq=prereq, ecode=errors.ECODE_ENVIRON)
  if not result.payload:
    msg = ("Node claims it doesn't have the secondary ip you gave (%s),"
           " please fix and re-run this command" % secondary_ip)
    if prereq:
      raise errors.OpPrereqError(msg, errors.ECODE_ENVIRON)
    else:
      raise errors.OpExecError(msg)


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

    if self.op.readd and self.op.node_name == self.cfg.GetMasterNodeName():
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
    hook_nodes = self.cfg.GetNodeList()
    new_node_info = self.cfg.GetNodeInfoByName(self.op.node_name)
    if new_node_info is not None:
      # Exclude added node
      hook_nodes = list(set(hook_nodes) - set([new_node_info.uuid]))

    # add the new node as post hook node by name; it does not have an UUID yet
    return (hook_nodes, hook_nodes, [self.op.node_name, ])

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the new node is not already in the config
     - it is resolvable
     - its parameters (single/dual homed) matches the cluster

    Any errors are signaled by raising errors.OpPrereqError.

    """
    node_name = self.hostname.name
    self.op.primary_ip = self.hostname.ip
    if self.op.secondary_ip is None:
      if self.primary_ip_family == netutils.IP6Address.family:
        raise errors.OpPrereqError("When using a IPv6 primary address, a valid"
                                   " IPv4 address must be given as secondary",
                                   errors.ECODE_INVAL)
      self.op.secondary_ip = self.op.primary_ip

    secondary_ip = self.op.secondary_ip
    if not netutils.IP4Address.IsValid(secondary_ip):
      raise errors.OpPrereqError("Secondary IP (%s) needs to be a valid IPv4"
                                 " address" % secondary_ip, errors.ECODE_INVAL)

    existing_node_info = self.cfg.GetNodeInfoByName(node_name)
    if not self.op.readd and existing_node_info is not None:
      raise errors.OpPrereqError("Node %s is already in the configuration" %
                                 node_name, errors.ECODE_EXISTS)
    elif self.op.readd and existing_node_info is None:
      raise errors.OpPrereqError("Node %s is not in the configuration" %
                                 node_name, errors.ECODE_NOENT)

    self.changed_primary_ip = False

    for existing_node in self.cfg.GetAllNodesInfo().values():
      if self.op.readd and node_name == existing_node.name:
        if existing_node.secondary_ip != secondary_ip:
          raise errors.OpPrereqError("Readded node doesn't have the same IP"
                                     " address configuration as before",
                                     errors.ECODE_INVAL)
        if existing_node.primary_ip != self.op.primary_ip:
          self.changed_primary_ip = True

        continue

      if (existing_node.primary_ip == self.op.primary_ip or
          existing_node.secondary_ip == self.op.primary_ip or
          existing_node.primary_ip == secondary_ip or
          existing_node.secondary_ip == secondary_ip):
        raise errors.OpPrereqError("New node ip address(es) conflict with"
                                   " existing node %s" % existing_node.name,
                                   errors.ECODE_NOTUNIQUE)

    # After this 'if' block, None is no longer a valid value for the
    # _capable op attributes
    if self.op.readd:
      assert existing_node_info is not None, \
        "Can't retrieve locked node %s" % node_name
      for attr in self._NFLAGS:
        if getattr(self.op, attr) is None:
          setattr(self.op, attr, getattr(existing_node_info, attr))
    else:
      for attr in self._NFLAGS:
        if getattr(self.op, attr) is None:
          setattr(self.op, attr, True)

    if self.op.readd and not self.op.vm_capable:
      pri, sec = self.cfg.GetNodeInstances(existing_node_info.uuid)
      if pri or sec:
        raise errors.OpPrereqError("Node %s being re-added with vm_capable"
                                   " flag set to false, but it already holds"
                                   " instances" % node_name,
                                   errors.ECODE_STATE)

    # check that the type of the node (single versus dual homed) is the
    # same as for the master
    myself = self.cfg.GetMasterNodeInfo()
    master_singlehomed = myself.secondary_ip == myself.primary_ip
    newbie_singlehomed = secondary_ip == self.op.primary_ip
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
    if not netutils.TcpPing(self.op.primary_ip, constants.DEFAULT_NODED_PORT):
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
      exceptions = [existing_node_info.uuid]
    else:
      exceptions = []

    if self.op.master_capable:
      self.master_candidate = _DecideSelfPromotion(self, exceptions=exceptions)
    else:
      self.master_candidate = False

    node_group = self.cfg.LookupNodeGroup(self.op.group)

    if self.op.readd:
      self.new_node = existing_node_info
    else:
      self.new_node = objects.Node(name=node_name,
                                   primary_ip=self.op.primary_ip,
                                   secondary_ip=secondary_ip,
                                   master_candidate=self.master_candidate,
                                   offline=False, drained=False,
                                   group=node_group, ndparams={})

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)
      CheckParamsNotGlobal(self.op.ndparams, constants.NDC_GLOBALS, "node",
                           "node", "cluster or group")

    if self.op.hv_state:
      self.new_hv_state = MergeAndVerifyHvState(self.op.hv_state, None)

    if self.op.disk_state:
      self.new_disk_state = MergeAndVerifyDiskState(self.op.disk_state, None)

    # TODO: If we need to have multiple DnsOnlyRunner we probably should make
    #       it a property on the base class.
    rpcrunner = rpc.DnsOnlyRunner()
    result = rpcrunner.call_version([node_name])[node_name]
    result.Raise("Can't get version information from node %s" % node_name)
    if constants.PROTOCOL_VERSION == result.payload:
      logging.info("Communication to node %s fine, sw version %s match",
                   node_name, result.payload)
    else:
      raise errors.OpPrereqError("Version mismatch master version %s,"
                                 " node version %s" %
                                 (constants.PROTOCOL_VERSION, result.payload),
                                 errors.ECODE_ENVIRON)

    vg_name = self.cfg.GetVGName()
    if vg_name is not None:
      vparams = {constants.NV_PVLIST: [vg_name]}
      excl_stor = IsExclusiveStorageEnabledNode(self.cfg, self.new_node)
      cname = self.cfg.GetClusterName()
      result = rpcrunner.call_node_verify_light(
          [node_name], vparams, cname,
          self.cfg.GetClusterInfo().hvparams,
          {node_name: node_group},
          self.cfg.GetAllNodeGroupsInfoDict()
        )[node_name]
      (errmsgs, _) = CheckNodePVs(result.payload, excl_stor)
      if errmsgs:
        raise errors.OpPrereqError("Checks on node PVs failed: %s" %
                                   "; ".join(errmsgs), errors.ECODE_ENVIRON)

  def _InitOpenVSwitch(self):
    filled_ndparams = self.cfg.GetClusterInfo().FillND(
      self.new_node, self.cfg.GetNodeGroup(self.new_node.group))

    ovs = filled_ndparams.get(constants.ND_OVS, None)
    ovs_name = filled_ndparams.get(constants.ND_OVS_NAME, None)
    ovs_link = filled_ndparams.get(constants.ND_OVS_LINK, None)

    if ovs:
      if not ovs_link:
        self.LogInfo("No physical interface for OpenvSwitch was given."
                     " OpenvSwitch will not have an outside connection. This"
                     " might not be what you want.")

      result = self.rpc.call_node_configure_ovs(
                 self.new_node.name, ovs_name, ovs_link)
      result.Raise("Failed to initialize OpenVSwitch on new node")

  def Exec(self, feedback_fn):
    """Adds the new node to the cluster.

    """
    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER), \
      "Not owning BGL"

    # We adding a new node so we assume it's powered
    self.new_node.powered = True

    # for re-adds, reset the offline/drained/master-candidate flags;
    # we need to reset here, otherwise offline would prevent RPC calls
    # later in the procedure; this also means that if the re-add
    # fails, we are left with a non-offlined, broken node
    if self.op.readd:
      self.new_node.offline = False
      self.new_node.drained = False
      self.LogInfo("Readding a node, the offline/drained flags were reset")
      # if we demote the node, we do cleanup later in the procedure
      self.new_node.master_candidate = self.master_candidate
      if self.changed_primary_ip:
        self.new_node.primary_ip = self.op.primary_ip

    # copy the master/vm_capable flags
    for attr in self._NFLAGS:
      setattr(self.new_node, attr, getattr(self.op, attr))

    # notify the user about any possible mc promotion
    if self.new_node.master_candidate:
      self.LogInfo("Node will be a master candidate")

    if self.op.ndparams:
      self.new_node.ndparams = self.op.ndparams
    else:
      self.new_node.ndparams = {}

    if self.op.hv_state:
      self.new_node.hv_state_static = self.new_hv_state

    if self.op.disk_state:
      self.new_node.disk_state_static = self.new_disk_state

    # Add node to our /etc/hosts, and add key to known_hosts
    if self.cfg.GetClusterInfo().modify_etc_hosts:
      master_node = self.cfg.GetMasterNode()
      result = self.rpc.call_etc_hosts_modify(
                 master_node, constants.ETC_HOSTS_ADD, self.hostname.name,
                 self.hostname.ip)
      result.Raise("Can't update hosts file with new host data")

    if self.new_node.secondary_ip != self.new_node.primary_ip:
      _CheckNodeHasSecondaryIP(self, self.new_node, self.new_node.secondary_ip,
                               False)

    node_verifier_uuids = [self.cfg.GetMasterNode()]
    node_verify_param = {
      constants.NV_NODELIST: ([self.new_node.name], {}),
      # TODO: do a node-net-test as well?
    }

    result = self.rpc.call_node_verify(
               node_verifier_uuids, node_verify_param,
               self.cfg.GetClusterName(),
               self.cfg.GetClusterInfo().hvparams,
               {self.new_node.name: self.cfg.LookupNodeGroup(self.op.group)},
               self.cfg.GetAllNodeGroupsInfoDict()
               )
    for verifier in node_verifier_uuids:
      result[verifier].Raise("Cannot communicate with node %s" % verifier)
      nl_payload = result[verifier].payload[constants.NV_NODELIST]
      if nl_payload:
        for failed in nl_payload:
          feedback_fn("ssh/hostname verification failed"
                      " (checking from %s): %s" %
                      (verifier, nl_payload[failed]))
        raise errors.OpExecError("ssh/hostname verification failed")

    self._InitOpenVSwitch()

    if self.op.readd:
      self.context.ReaddNode(self.new_node)
      RedistributeAncillaryFiles(self)
      # make sure we redistribute the config
      self.cfg.Update(self.new_node, feedback_fn)
      # and make sure the new node will not have old files around
      if not self.new_node.master_candidate:
        result = self.rpc.call_node_demote_from_mc(self.new_node.uuid)
        result.Warn("Node failed to demote itself from master candidate status",
                    self.LogWarning)
    else:
      self.context.AddNode(self.new_node, self.proc.GetECId())
      RedistributeAncillaryFiles(self)


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
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)
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
            self.op.node_uuid in instance.all_nodes)

  def ExpandNames(self):
    if self.lock_all:
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,

        # Block allocations when all nodes are locked
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODE: self.op.node_uuid,
        }

    # Since modifying a node can have severe effects on currently running
    # operations the resource lock is at least acquired in shared mode
    self.needed_locks[locking.LEVEL_NODE_RES] = \
      self.needed_locks[locking.LEVEL_NODE]

    # Get all locks except nodes in shared mode; they are not used for anything
    # but read-only access
    self.share_locks = ShareAll()
    self.share_locks[locking.LEVEL_NODE] = 0
    self.share_locks[locking.LEVEL_NODE_RES] = 0
    self.share_locks[locking.LEVEL_NODE_ALLOC] = 0

    if self.lock_instances:
      self.needed_locks[locking.LEVEL_INSTANCE] = \
        self.cfg.GetInstanceNames(
          self.cfg.GetInstancesInfoByFilter(self._InstanceFilter).keys())

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
    nl = [self.cfg.GetMasterNode(), self.op.node_uuid]
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the instance list against the existing names.

    """
    node = self.cfg.GetNodeInfo(self.op.node_uuid)
    if self.lock_instances:
      affected_instances = \
        self.cfg.GetInstancesInfoByFilter(self._InstanceFilter)

      # Verify instance locks
      owned_instance_names = self.owned_locks(locking.LEVEL_INSTANCE)
      wanted_instance_names = frozenset([inst.name for inst in
                                         affected_instances.values()])
      if wanted_instance_names - owned_instance_names:
        raise errors.OpPrereqError("Instances affected by changing node %s's"
                                   " secondary IP address have changed since"
                                   " locks were acquired, wanted '%s', have"
                                   " '%s'; retry the operation" %
                                   (node.name,
                                    utils.CommaJoin(wanted_instance_names),
                                    utils.CommaJoin(owned_instance_names)),
                                   errors.ECODE_STATE)
    else:
      affected_instances = None

    if (self.op.master_candidate is not None or
        self.op.drained is not None or
        self.op.offline is not None):
      # we can't change the master's node flags
      if node.uuid == self.cfg.GetMasterNode():
        raise errors.OpPrereqError("The master role can be changed"
                                   " only via master-failover",
                                   errors.ECODE_INVAL)

    if self.op.master_candidate and not node.master_capable:
      raise errors.OpPrereqError("Node %s is not master capable, cannot make"
                                 " it a master candidate" % node.name,
                                 errors.ECODE_STATE)

    if self.op.vm_capable is False:
      (ipri, isec) = self.cfg.GetNodeInstances(node.uuid)
      if ipri or isec:
        raise errors.OpPrereqError("Node %s hosts instances, cannot unset"
                                   " the vm_capable flag" % node.name,
                                   errors.ECODE_STATE)

    if node.master_candidate and self.might_demote and not self.lock_all:
      assert not self.op.auto_promote, "auto_promote set but lock_all not"
      # check if after removing the current node, we're missing master
      # candidates
      (mc_remaining, mc_should, _) = \
          self.cfg.GetMasterCandidateStats(exceptions=[node.uuid])
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
      if getattr(self.op, attr) is False and getattr(node, attr) is False:
        self.LogInfo("Ignoring request to unset flag %s, already unset", attr)
        setattr(self.op, attr, None)

    # Past this point, any flag change to False means a transition
    # away from the respective state, as only real changes are kept

    # TODO: We might query the real power state if it supports OOB
    if SupportsOob(self.cfg, node):
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
      result = self.rpc.call_version([node.uuid])[node.uuid]
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
      master = self.cfg.GetMasterNodeInfo()
      master_singlehomed = master.secondary_ip == master.primary_ip
      if master_singlehomed and self.op.secondary_ip != node.primary_ip:
        if self.op.force and node.uuid == master.uuid:
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
        if self.op.force and node.uuid == master.uuid:
          self.LogWarning("Transitioning from multi-homed to single-homed"
                          " cluster; secondary IP addresses will have to be"
                          " removed")
        else:
          raise errors.OpPrereqError("Cannot set the secondary IP to be the"
                                     " same as the primary IP on a multi-homed"
                                     " cluster, unless the --force option is"
                                     " passed, and the target node is the"
                                     " master", errors.ECODE_INVAL)

      assert not (set([inst.name for inst in affected_instances.values()]) -
                  self.owned_locks(locking.LEVEL_INSTANCE))

      if node.offline:
        if affected_instances:
          msg = ("Cannot change secondary IP address: offline node has"
                 " instances (%s) configured to use it" %
                 utils.CommaJoin(
                   [inst.name for inst in affected_instances.values()]))
          raise errors.OpPrereqError(msg, errors.ECODE_STATE)
      else:
        # On online nodes, check that no instances are running, and that
        # the node has the new ip and we can reach it.
        for instance in affected_instances.values():
          CheckInstanceState(self, instance, INSTANCE_DOWN,
                             msg="cannot change secondary ip")

        _CheckNodeHasSecondaryIP(self, node, self.op.secondary_ip, True)
        if master.uuid != node.uuid:
          # check reachability from master secondary ip to new secondary ip
          if not netutils.TcpPing(self.op.secondary_ip,
                                  constants.DEFAULT_NODED_PORT,
                                  source=master.secondary_ip):
            raise errors.OpPrereqError("Node secondary ip not reachable by TCP"
                                       " based ping to node daemon port",
                                       errors.ECODE_ENVIRON)

    if self.op.ndparams:
      new_ndparams = GetUpdatedParams(node.ndparams, self.op.ndparams)
      utils.ForceDictType(new_ndparams, constants.NDS_PARAMETER_TYPES)
      CheckParamsNotGlobal(self.op.ndparams, constants.NDC_GLOBALS, "node",
                           "node", "cluster or group")
      self.new_ndparams = new_ndparams

    if self.op.hv_state:
      self.new_hv_state = MergeAndVerifyHvState(self.op.hv_state,
                                                node.hv_state_static)

    if self.op.disk_state:
      self.new_disk_state = \
        MergeAndVerifyDiskState(self.op.disk_state, node.disk_state_static)

  def Exec(self, feedback_fn):
    """Modifies a node.

    """
    node = self.cfg.GetNodeInfo(self.op.node_uuid)
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

    if self.new_role != self.old_role:
      # Tell the node to demote itself, if no longer MC and not offline
      if self.old_role == self._ROLE_CANDIDATE and \
          self.new_role != self._ROLE_OFFLINE:
        msg = self.rpc.call_node_demote_from_mc(node.name).fail_msg
        if msg:
          self.LogWarning("Node failed to demote itself: %s", msg)

      new_flags = self._R2F[self.new_role]
      for of, nf, desc in zip(self.old_flags, new_flags, self._FLAGS):
        if of != nf:
          result.append((desc, str(nf)))
      (node.master_candidate, node.drained, node.offline) = new_flags

      # we locked all nodes, we adjust the CP before updating this node
      if self.lock_all:
        AdjustCandidatePool(self, [node.uuid])

    if self.op.secondary_ip:
      node.secondary_ip = self.op.secondary_ip
      result.append(("secondary_ip", self.op.secondary_ip))

    # this will trigger configuration file update, if needed
    self.cfg.Update(node, feedback_fn)

    # this will trigger job queue propagation or cleanup if the mc
    # flag changed
    if [self.old_role, self.new_role].count(self._ROLE_CANDIDATE) == 1:
      self.context.ReaddNode(node)

    return result


class LUNodePowercycle(NoHooksLU):
  """Powercycles a node.

  """
  REQ_BGL = False

  def CheckArguments(self):
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)

    if self.op.node_uuid == self.cfg.GetMasterNode() and not self.op.force:
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
    default_hypervisor = self.cfg.GetHypervisorType()
    hvparams = self.cfg.GetClusterInfo().hvparams[default_hypervisor]
    result = self.rpc.call_node_powercycle(self.op.node_uuid,
                                           default_hypervisor,
                                           hvparams)
    result.Raise("Failed to schedule the reboot")
    return result.payload


def _GetNodeInstancesInner(cfg, fn):
  return [i for i in cfg.GetAllInstancesInfo().values() if fn(i)]


def _GetNodePrimaryInstances(cfg, node_uuid):
  """Returns primary instances on a node.

  """
  return _GetNodeInstancesInner(cfg,
                                lambda inst: node_uuid == inst.primary_node)


def _GetNodeSecondaryInstances(cfg, node_uuid):
  """Returns secondary instances on a node.

  """
  return _GetNodeInstancesInner(cfg,
                                lambda inst: node_uuid in inst.secondary_nodes)


def _GetNodeInstances(cfg, node_uuid):
  """Returns a list of all primary and secondary instances on a node.

  """

  return _GetNodeInstancesInner(cfg, lambda inst: node_uuid in inst.all_nodes)


class LUNodeEvacuate(NoHooksLU):
  """Evacuates instances off a list of nodes.

  """
  REQ_BGL = False

  def CheckArguments(self):
    CheckIAllocatorOrNode(self, "iallocator", "remote_node")

  def ExpandNames(self):
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)

    if self.op.remote_node is not None:
      (self.op.remote_node_uuid, self.op.remote_node) = \
        ExpandNodeUuidAndName(self.cfg, self.op.remote_node_uuid,
                              self.op.remote_node)
      assert self.op.remote_node

      if self.op.node_uuid == self.op.remote_node_uuid:
        raise errors.OpPrereqError("Can not use evacuated node as a new"
                                   " secondary node", errors.ECODE_INVAL)

      if self.op.mode != constants.NODE_EVAC_SEC:
        raise errors.OpPrereqError("Without the use of an iallocator only"
                                   " secondary instances can be evacuated",
                                   errors.ECODE_INVAL)

    # Declare locks
    self.share_locks = ShareAll()
    self.needed_locks = {
      locking.LEVEL_INSTANCE: [],
      locking.LEVEL_NODEGROUP: [],
      locking.LEVEL_NODE: [],
      }

    # Determine nodes (via group) optimistically, needs verification once locks
    # have been acquired
    self.lock_nodes = self._DetermineNodes()

  def _DetermineNodes(self):
    """Gets the list of node UUIDs to operate on.

    """
    if self.op.remote_node is None:
      # Iallocator will choose any node(s) in the same group
      group_nodes = self.cfg.GetNodeGroupMembersByNodes([self.op.node_uuid])
    else:
      group_nodes = frozenset([self.op.remote_node_uuid])

    # Determine nodes to be locked
    return set([self.op.node_uuid]) | group_nodes

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

    return inst_fn(self.cfg, self.op.node_uuid)

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
    owned_instance_names = self.owned_locks(locking.LEVEL_INSTANCE)
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

    if set(self.instance_names) != owned_instance_names:
      raise errors.OpExecError("Instances on node '%s' changed since locks"
                               " were acquired, current instances are '%s',"
                               " used to be '%s'; retry the operation" %
                               (self.op.node_name,
                                utils.CommaJoin(self.instance_names),
                                utils.CommaJoin(owned_instance_names)))

    if self.instance_names:
      self.LogInfo("Evacuating instances from node '%s': %s",
                   self.op.node_name,
                   utils.CommaJoin(utils.NiceSort(self.instance_names)))
    else:
      self.LogInfo("No instances to evacuate from node '%s'",
                   self.op.node_name)

    if self.op.remote_node is not None:
      for i in self.instances:
        if i.primary_node == self.op.remote_node_uuid:
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
      req = iallocator.IAReqNodeEvac(evac_mode=self.op.mode,
                                     instances=list(self.instance_names))
      ial = iallocator.IAllocator(self.cfg, self.rpc, req)

      ial.Run(self.op.iallocator)

      if not ial.success:
        raise errors.OpPrereqError("Can't compute node evacuation using"
                                   " iallocator '%s': %s" %
                                   (self.op.iallocator, ial.info),
                                   errors.ECODE_NORES)

      jobs = LoadNodeEvacResult(self, ial.result, self.op.early_release, True)

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


class LUNodeMigrate(LogicalUnit):
  """Migrate all instances from a node.

  """
  HPATH = "node-migrate"
  HTYPE = constants.HTYPE_NODE
  REQ_BGL = False

  def CheckArguments(self):
    pass

  def ExpandNames(self):
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)

    self.share_locks = ShareAll()
    self.needed_locks = {
      locking.LEVEL_NODE: [self.op.node_uuid],
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
    jobs = [
      [opcodes.OpInstanceMigrate(
        instance_name=inst.name,
        mode=self.op.mode,
        live=self.op.live,
        iallocator=self.op.iallocator,
        target_node=self.op.target_node,
        allow_runtime_changes=self.op.allow_runtime_changes,
        ignore_ipolicy=self.op.ignore_ipolicy)]
      for inst in _GetNodePrimaryInstances(self.cfg, self.op.node_uuid)]

    # TODO: Run iallocator in this opcode and pass correct placement options to
    # OpInstanceMigrate. Since other jobs can modify the cluster between
    # running the iallocator and the actual migration, a good consistency model
    # will have to be found.

    assert (frozenset(self.owned_locks(locking.LEVEL_NODE)) ==
            frozenset([self.op.node_uuid]))

    return ResultWithJobs(jobs)


def _GetStorageTypeArgs(cfg, storage_type):
  """Returns the arguments for a storage type.

  """
  # Special case for file storage

  if storage_type == constants.ST_FILE:
    return [[cfg.GetFileStorageDir()]]
  elif storage_type == constants.ST_SHARED_FILE:
    dts = cfg.GetClusterInfo().enabled_disk_templates
    paths = []
    if constants.DT_SHARED_FILE in dts:
      paths.append(cfg.GetSharedFileStorageDir())
    if constants.DT_GLUSTER in dts:
      paths.append(cfg.GetGlusterStorageDir())
    return [paths]
  else:
    return []


class LUNodeModifyStorage(NoHooksLU):
  """Logical unit for modifying a storage volume on a node.

  """
  REQ_BGL = False

  def CheckArguments(self):
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)

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

  def CheckPrereq(self):
    """Check prerequisites.

    """
    CheckStorageTypeEnabled(self.cfg.GetClusterInfo(), self.op.storage_type)

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: self.op.node_uuid,
      }

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    st_args = _GetStorageTypeArgs(self.cfg, self.op.storage_type)
    result = self.rpc.call_storage_modify(self.op.node_uuid,
                                          self.op.storage_type, st_args,
                                          self.op.name, self.op.changes)
    result.Raise("Failed to modify storage unit '%s' on %s" %
                 (self.op.name, self.op.node_name))


def _CheckOutputFields(fields, selected):
  """Checks whether all selected fields are valid according to fields.

  @type fields: L{utils.FieldSet}
  @param fields: fields set
  @type selected: L{utils.FieldSet}
  @param selected: fields set

  """
  delta = fields.NonMatching(selected)
  if delta:
    raise errors.OpPrereqError("Unknown output fields selected: %s"
                               % ",".join(delta), errors.ECODE_INVAL)


class LUNodeQueryvols(NoHooksLU):
  """Logical unit for getting volumes on node(s).

  """
  REQ_BGL = False

  def CheckArguments(self):
    _CheckOutputFields(utils.FieldSet(constants.VF_NODE, constants.VF_PHYS,
                                      constants.VF_VG, constants.VF_NAME,
                                      constants.VF_SIZE, constants.VF_INSTANCE),
                       self.op.output_fields)

  def ExpandNames(self):
    self.share_locks = ShareAll()

    if self.op.nodes:
      self.needed_locks = {
        locking.LEVEL_NODE: GetWantedNodes(self, self.op.nodes)[0],
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    node_uuids = self.owned_locks(locking.LEVEL_NODE)
    volumes = self.rpc.call_node_volumes(node_uuids)

    ilist = self.cfg.GetAllInstancesInfo()
    vol2inst = MapInstanceLvsToNodes(ilist.values())

    output = []
    for node_uuid in node_uuids:
      nresult = volumes[node_uuid]
      if nresult.offline:
        continue
      msg = nresult.fail_msg
      if msg:
        self.LogWarning("Can't compute volume data on node %s: %s",
                        self.cfg.GetNodeName(node_uuid), msg)
        continue

      node_vols = sorted(nresult.payload,
                         key=operator.itemgetter(constants.VF_DEV))

      for vol in node_vols:
        node_output = []
        for field in self.op.output_fields:
          if field == constants.VF_NODE:
            val = self.cfg.GetNodeName(node_uuid)
          elif field == constants.VF_PHYS:
            val = vol[constants.VF_DEV]
          elif field == constants.VF_VG:
            val = vol[constants.VF_VG]
          elif field == constants.VF_NAME:
            val = vol[constants.VF_NAME]
          elif field == constants.VF_SIZE:
            val = int(float(vol[constants.VF_SIZE]))
          elif field == constants.VF_INSTANCE:
            inst = vol2inst.get((node_uuid, vol[constants.VF_VG] + "/" +
                                 vol[constants.VF_NAME]), None)
            if inst is not None:
              val = inst.name
            else:
              val = "-"
          else:
            raise errors.ParameterError(field)
          node_output.append(str(val))

        output.append(node_output)

    return output


class LUNodeQueryStorage(NoHooksLU):
  """Logical unit for getting information on storage units on node(s).

  """
  REQ_BGL = False

  def CheckArguments(self):
    _CheckOutputFields(utils.FieldSet(*constants.VALID_STORAGE_FIELDS),
                       self.op.output_fields)

  def ExpandNames(self):
    self.share_locks = ShareAll()

    if self.op.nodes:
      self.needed_locks = {
        locking.LEVEL_NODE: GetWantedNodes(self, self.op.nodes)[0],
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }

  def _DetermineStorageType(self):
    """Determines the default storage type of the cluster.

    """
    enabled_disk_templates = self.cfg.GetClusterInfo().enabled_disk_templates
    default_storage_type = \
        constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[enabled_disk_templates[0]]
    return default_storage_type

  def CheckPrereq(self):
    """Check prerequisites.

    """
    if self.op.storage_type:
      CheckStorageTypeEnabled(self.cfg.GetClusterInfo(), self.op.storage_type)
      self.storage_type = self.op.storage_type
    else:
      self.storage_type = self._DetermineStorageType()
      supported_storage_types = constants.STS_REPORT_NODE_STORAGE
      if self.storage_type not in supported_storage_types:
        raise errors.OpPrereqError(
            "Storage reporting for storage type '%s' is not supported. Please"
            " use the --storage-type option to specify one of the supported"
            " storage types (%s) or set the default disk template to one that"
            " supports storage reporting." %
            (self.storage_type, utils.CommaJoin(supported_storage_types)))

  def Exec(self, feedback_fn):
    """Computes the list of nodes and their attributes.

    """
    if self.op.storage_type:
      self.storage_type = self.op.storage_type
    else:
      self.storage_type = self._DetermineStorageType()

    self.node_uuids = self.owned_locks(locking.LEVEL_NODE)

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

    st_args = _GetStorageTypeArgs(self.cfg, self.storage_type)
    data = self.rpc.call_storage_list(self.node_uuids,
                                      self.storage_type, st_args,
                                      self.op.name, fields)

    result = []

    for node_uuid in utils.NiceSort(self.node_uuids):
      node_name = self.cfg.GetNodeName(node_uuid)
      nresult = data[node_uuid]
      if nresult.offline:
        continue

      msg = nresult.fail_msg
      if msg:
        self.LogWarning("Can't get storage data from node %s: %s",
                        node_name, msg)
        continue

      rows = dict([(row[name_idx], row) for row in nresult.payload])

      for name in utils.NiceSort(rows.keys()):
        row = rows[name]

        out = []

        for field in self.op.output_fields:
          if field == constants.SF_NODE:
            val = node_name
          elif field == constants.SF_TYPE:
            val = self.storage_type
          elif field in field_idx:
            val = row[field_idx[field]]
          else:
            raise errors.ParameterError(field)

          out.append(val)

        result.append(out)

    return result


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
      all_nodes.remove(self.op.node_uuid)
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
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)
    node = self.cfg.GetNodeInfo(self.op.node_uuid)
    assert node is not None

    masternode = self.cfg.GetMasterNode()
    if node.uuid == masternode:
      raise errors.OpPrereqError("Node is the master node, failover to another"
                                 " node is required", errors.ECODE_INVAL)

    for _, instance in self.cfg.GetAllInstancesInfo().items():
      if node.uuid in instance.all_nodes:
        raise errors.OpPrereqError("Instance %s is still running on the node,"
                                   " please remove first" % instance.name,
                                   errors.ECODE_INVAL)
    self.op.node_name = node.name
    self.node = node

  def Exec(self, feedback_fn):
    """Removes the node from the cluster.

    """
    logging.info("Stopping the node daemon and removing configs from node %s",
                 self.node.name)

    modify_ssh_setup = self.cfg.GetClusterInfo().modify_ssh_setup

    assert locking.BGL in self.owned_locks(locking.LEVEL_CLUSTER), \
      "Not owning BGL"

    # Promote nodes to master candidate as needed
    AdjustCandidatePool(self, exceptions=[self.node.uuid])
    self.context.RemoveNode(self.node)

    # Run post hooks on the node before it's removed
    RunPostHook(self, self.node.name)

    # we have to call this by name rather than by UUID, as the node is no longer
    # in the config
    result = self.rpc.call_node_leave_cluster(self.node.name, modify_ssh_setup)
    msg = result.fail_msg
    if msg:
      self.LogWarning("Errors encountered on the remote node while leaving"
                      " the cluster: %s", msg)

    # Remove node from our /etc/hosts
    if self.cfg.GetClusterInfo().modify_etc_hosts:
      master_node_uuid = self.cfg.GetMasterNode()
      result = self.rpc.call_etc_hosts_modify(master_node_uuid,
                                              constants.ETC_HOSTS_REMOVE,
                                              self.node.name, None)
      result.Raise("Can't update hosts file with new host data")
      RedistributeAncillaryFiles(self)


class LURepairNodeStorage(NoHooksLU):
  """Repairs the volume group on a node.

  """
  REQ_BGL = False

  def CheckArguments(self):
    (self.op.node_uuid, self.op.node_name) = \
      ExpandNodeUuidAndName(self.cfg, self.op.node_uuid, self.op.node_name)

    storage_type = self.op.storage_type

    if (constants.SO_FIX_CONSISTENCY not in
        constants.VALID_STORAGE_OPERATIONS.get(storage_type, [])):
      raise errors.OpPrereqError("Storage units of type '%s' can not be"
                                 " repaired" % storage_type,
                                 errors.ECODE_INVAL)

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: [self.op.node_uuid],
      }

  def _CheckFaultyDisks(self, instance, node_uuid):
    """Ensure faulty disks abort the opcode or at least warn."""
    try:
      if FindFaultyInstanceDisks(self.cfg, self.rpc, instance,
                                 node_uuid, True):
        raise errors.OpPrereqError("Instance '%s' has faulty disks on"
                                   " node '%s'" %
                                   (instance.name,
                                    self.cfg.GetNodeName(node_uuid)),
                                   errors.ECODE_STATE)
    except errors.OpPrereqError, err:
      if self.op.ignore_consistency:
        self.LogWarning(str(err.args[0]))
      else:
        raise

  def CheckPrereq(self):
    """Check prerequisites.

    """
    CheckStorageTypeEnabled(self.cfg.GetClusterInfo(), self.op.storage_type)

    # Check whether any instance on this node has faulty disks
    for inst in _GetNodeInstances(self.cfg, self.op.node_uuid):
      if not inst.disks_active:
        continue
      check_nodes = set(inst.all_nodes)
      check_nodes.discard(self.op.node_uuid)
      for inst_node_uuid in check_nodes:
        self._CheckFaultyDisks(inst, inst_node_uuid)

  def Exec(self, feedback_fn):
    feedback_fn("Repairing storage unit '%s' on %s ..." %
                (self.op.name, self.op.node_name))

    st_args = _GetStorageTypeArgs(self.cfg, self.op.storage_type)
    result = self.rpc.call_storage_execute(self.op.node_uuid,
                                           self.op.storage_type, st_args,
                                           self.op.name,
                                           constants.SO_FIX_CONSISTENCY)
    result.Raise("Failed to repair storage unit '%s' on %s" %
                 (self.op.name, self.op.node_name))
