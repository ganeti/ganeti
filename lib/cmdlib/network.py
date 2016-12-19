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


"""Logical units dealing with networks."""

from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import network
from ganeti import objects
from ganeti import utils
from ganeti.cmdlib.base import LogicalUnit
from ganeti.cmdlib.common import CheckNodeGroupInstances


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
      self.needed_locks = {
        locking.LEVEL_NODE: locking.ALL_SET,
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
    return _BuildNetworkHookEnv(**args)

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
              pool.Reserve(ip, external=True)
              self.LogInfo("Reserved IP address of node '%s' (%s)",
                           node.name, ip)
          except errors.AddressPoolError, err:
            self.LogWarning("Cannot reserve IP address '%s' of node '%s': %s",
                            ip, node.name, err)

      master_ip = self.cfg.GetClusterInfo().master_ip
      try:
        if pool.Contains(master_ip):
          pool.Reserve(master_ip, external=True)
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
    return _BuildNetworkHookEnv(**args)

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
          self.pool.Reserve(ip, external=True)
        except errors.AddressPoolError, err:
          self.LogWarning("Cannot reserve IP address %s: %s", ip, err)

    if self.op.remove_reserved_ips:
      for ip in self.op.remove_reserved_ips:
        if ip == self.network.gateway:
          self.LogWarning("Cannot unreserve Gateway's IP")
          continue
        try:
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


def _FmtNetworkConflict(details):
  """Utility for L{_NetworkConflictCheck}.

  """
  return utils.CommaJoin("nic%s/%s" % (idx, ipaddr)
                         for (idx, ipaddr) in details)


def _NetworkConflictCheck(lu, check_fn, action, instances):
  """Checks for network interface conflicts with a network.

  @type lu: L{LogicalUnit}
  @type check_fn: callable receiving one parameter (L{objects.NIC}) and
    returning boolean
  @param check_fn: Function checking for conflict
  @type action: string
  @param action: Part of error message (see code)
  @param instances: the instances to check
  @type instances: list of instance objects
  @raise errors.OpPrereqError: If conflicting IP addresses are found.

  """
  conflicts = []

  for instance in instances:
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
    self.network_vlan = self.op.network_vlan

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
          self.cfg.GetInstanceNames(
            self.cfg.GetNodeGroupInstances(self.group_uuid))

  def BuildHooksEnv(self):
    ret = {
      "GROUP_NAME": self.group_name,
      "GROUP_NETWORK_MODE": self.network_mode,
      "GROUP_NETWORK_LINK": self.network_link,
      "GROUP_NETWORK_VLAN": self.network_vlan,
      }
    return ret

  def BuildHooksNodes(self):
    node_uuids = self.cfg.GetNodeGroup(self.group_uuid).members
    return (node_uuids, node_uuids)

  def CheckPrereq(self):
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))

    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    owned_instance_names = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    if self.op.conflicts_check:
      CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instance_names)

    self.netparams = {
      constants.NIC_MODE: self.network_mode,
      constants.NIC_LINK: self.network_link,
      constants.NIC_VLAN: self.network_vlan,
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

      _NetworkConflictCheck(
        self, lambda nic: pool.Contains(nic.ip), "connect to",
        [instance_info for (_, instance_info) in
         self.cfg.GetMultiInstanceInfoByName(owned_instance_names)])

  def Exec(self, feedback_fn):
    # Connect the network and update the group only if not already connected
    if not self.connected:
      self.group.networks[self.network_uuid] = self.netparams
      self.cfg.Update(self.group, feedback_fn)


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
        self.cfg.GetInstanceNames(
          self.cfg.GetNodeGroupInstances(self.group_uuid))

  def BuildHooksEnv(self):
    ret = {
      "GROUP_NAME": self.group_name,
      }

    if self.connected:
      ret.update({
        "GROUP_NETWORK_MODE": self.netparams[constants.NIC_MODE],
        "GROUP_NETWORK_LINK": self.netparams[constants.NIC_LINK],
        "GROUP_NETWORK_VLAN": self.netparams[constants.NIC_VLAN],
        })
    return ret

  def BuildHooksNodes(self):
    nodes = self.cfg.GetNodeGroup(self.group_uuid).members
    return (nodes, nodes)

  def CheckPrereq(self):
    owned_groups = frozenset(self.owned_locks(locking.LEVEL_NODEGROUP))

    assert self.group_uuid in owned_groups

    # Check if locked instances are still correct
    owned_instances = frozenset(self.owned_locks(locking.LEVEL_INSTANCE))
    CheckNodeGroupInstances(self.cfg, self.group_uuid, owned_instances)

    self.group = self.cfg.GetNodeGroup(self.group_uuid)
    self.connected = True
    if self.network_uuid not in self.group.networks:
      self.LogWarning("Network '%s' is not mapped to group '%s'",
                      self.network_name, self.group.name)
      self.connected = False

    # We need this check only if network is not already connected
    else:
      _NetworkConflictCheck(
        self, lambda nic: nic.network == self.network_uuid, "disconnect from",
        [instance_info for (_, instance_info) in
         self.cfg.GetMultiInstanceInfoByName(owned_instances)])
      self.netparams = self.group.networks.get(self.network_uuid)

  def Exec(self, feedback_fn):
    # Disconnect the network and update the group only if network is connected
    if self.connected:
      del self.group.networks[self.network_uuid]
      self.cfg.Update(self.group, feedback_fn)
