#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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


"""Configuration management for Ganeti

This module provides the interface to the Ganeti cluster configuration.

The configuration data is stored on every node but is updated on the master
only. After each update, the master distributes the data to the other nodes.

Currently, the data storage format is JSON. YAML was slow and consuming too
much memory.

"""

# pylint: disable=R0904
# R0904: Too many public methods

import os
import random
import logging
import time
import itertools

from ganeti import errors
from ganeti import locking
from ganeti import utils
from ganeti import constants
from ganeti import rpc
from ganeti import objects
from ganeti import serializer
from ganeti import uidpool
from ganeti import netutils
from ganeti import runtime
from ganeti import pathutils
from ganeti import network


_config_lock = locking.SharedLock("ConfigWriter")

# job id used for resource management at config upgrade time
_UPGRADE_CONFIG_JID = "jid-cfg-upgrade"


def _ValidateConfig(data):
  """Verifies that a configuration objects looks valid.

  This only verifies the version of the configuration.

  @raise errors.ConfigurationError: if the version differs from what
      we expect

  """
  if data.version != constants.CONFIG_VERSION:
    raise errors.ConfigVersionMismatch(constants.CONFIG_VERSION, data.version)


class TemporaryReservationManager:
  """A temporary resource reservation manager.

  This is used to reserve resources in a job, before using them, making sure
  other jobs cannot get them in the meantime.

  """
  def __init__(self):
    self._ec_reserved = {}

  def Reserved(self, resource):
    for holder_reserved in self._ec_reserved.values():
      if resource in holder_reserved:
        return True
    return False

  def Reserve(self, ec_id, resource):
    if self.Reserved(resource):
      raise errors.ReservationError("Duplicate reservation for resource '%s'"
                                    % str(resource))
    if ec_id not in self._ec_reserved:
      self._ec_reserved[ec_id] = set([resource])
    else:
      self._ec_reserved[ec_id].add(resource)

  def DropECReservations(self, ec_id):
    if ec_id in self._ec_reserved:
      del self._ec_reserved[ec_id]

  def GetReserved(self):
    all_reserved = set()
    for holder_reserved in self._ec_reserved.values():
      all_reserved.update(holder_reserved)
    return all_reserved

  def Generate(self, existing, generate_one_fn, ec_id):
    """Generate a new resource of this type

    """
    assert callable(generate_one_fn)

    all_elems = self.GetReserved()
    all_elems.update(existing)
    retries = 64
    while retries > 0:
      new_resource = generate_one_fn()
      if new_resource is not None and new_resource not in all_elems:
        break
    else:
      raise errors.ConfigurationError("Not able generate new resource"
                                      " (last tried: %s)" % new_resource)
    self.Reserve(ec_id, new_resource)
    return new_resource


def _MatchNameComponentIgnoreCase(short_name, names):
  """Wrapper around L{utils.text.MatchNameComponent}.

  """
  return utils.MatchNameComponent(short_name, names, case_sensitive=False)


def _CheckInstanceDiskIvNames(disks):
  """Checks if instance's disks' C{iv_name} attributes are in order.

  @type disks: list of L{objects.Disk}
  @param disks: List of disks
  @rtype: list of tuples; (int, string, string)
  @return: List of wrongly named disks, each tuple contains disk index,
    expected and actual name

  """
  result = []

  for (idx, disk) in enumerate(disks):
    exp_iv_name = "disk/%s" % idx
    if disk.iv_name != exp_iv_name:
      result.append((idx, exp_iv_name, disk.iv_name))

  return result


class ConfigWriter:
  """The interface to the cluster configuration.

  @ivar _temporary_lvs: reservation manager for temporary LVs
  @ivar _all_rms: a list of all temporary reservation managers

  """
  def __init__(self, cfg_file=None, offline=False, _getents=runtime.GetEnts,
               accept_foreign=False):
    self.write_count = 0
    self._lock = _config_lock
    self._config_data = None
    self._offline = offline
    if cfg_file is None:
      self._cfg_file = pathutils.CLUSTER_CONF_FILE
    else:
      self._cfg_file = cfg_file
    self._getents = _getents
    self._temporary_ids = TemporaryReservationManager()
    self._temporary_drbds = {}
    self._temporary_macs = TemporaryReservationManager()
    self._temporary_secrets = TemporaryReservationManager()
    self._temporary_lvs = TemporaryReservationManager()
    self._all_rms = [self._temporary_ids, self._temporary_macs,
                     self._temporary_secrets, self._temporary_lvs]
    # Note: in order to prevent errors when resolving our name in
    # _DistributeConfig, we compute it here once and reuse it; it's
    # better to raise an error before starting to modify the config
    # file than after it was modified
    self._my_hostname = netutils.Hostname.GetSysName()
    self._last_cluster_serial = -1
    self._cfg_id = None
    self._context = None
    self._OpenConfig(accept_foreign)

  def _GetRpc(self, address_list):
    """Returns RPC runner for configuration.

    """
    return rpc.ConfigRunner(self._context, address_list)

  def SetContext(self, context):
    """Sets Ganeti context.

    """
    self._context = context

  # this method needs to be static, so that we can call it on the class
  @staticmethod
  def IsCluster():
    """Check if the cluster is configured.

    """
    return os.path.exists(pathutils.CLUSTER_CONF_FILE)

  def _GenerateOneMAC(self):
    """Generate one mac address

    """
    prefix = self._config_data.cluster.mac_prefix
    byte1 = random.randrange(0, 256)
    byte2 = random.randrange(0, 256)
    byte3 = random.randrange(0, 256)
    mac = "%s:%02x:%02x:%02x" % (prefix, byte1, byte2, byte3)
    return mac

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNdParams(self, node):
    """Get the node params populated with cluster defaults.

    @type node: L{objects.Node}
    @param node: The node we want to know the params for
    @return: A dict with the filled in node params

    """
    nodegroup = self._UnlockedGetNodeGroup(node.group)
    return self._config_data.cluster.FillND(node, nodegroup)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceDiskParams(self, instance):
    """Get the disk params populated with inherit chain.

    @type instance: L{objects.Instance}
    @param instance: The instance we want to know the params for
    @return: A dict with the filled in disk params

    """
    node = self._UnlockedGetNodeInfo(instance.primary_node)
    nodegroup = self._UnlockedGetNodeGroup(node.group)
    return self._UnlockedGetGroupDiskParams(nodegroup)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetGroupDiskParams(self, group):
    """Get the disk params populated with inherit chain.

    @type group: L{objects.NodeGroup}
    @param group: The group we want to know the params for
    @return: A dict with the filled in disk params

    """
    return self._UnlockedGetGroupDiskParams(group)

  def _UnlockedGetGroupDiskParams(self, group):
    """Get the disk params populated with inherit chain down to node-group.

    @type group: L{objects.NodeGroup}
    @param group: The group we want to know the params for
    @return: A dict with the filled in disk params

    """
    return self._config_data.cluster.SimpleFillDP(group.diskparams)

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateMAC(self, ec_id):
    """Generate a MAC for an instance.

    This should check the current instances for duplicates.

    """
    existing = self._AllMACs()
    return self._temporary_ids.Generate(existing, self._GenerateOneMAC, ec_id)

  @locking.ssynchronized(_config_lock, shared=1)
  def ReserveMAC(self, mac, ec_id):
    """Reserve a MAC for an instance.

    This only checks instances managed by this cluster, it does not
    check for potential collisions elsewhere.

    """
    all_macs = self._AllMACs()
    if mac in all_macs:
      raise errors.ReservationError("mac already in use")
    else:
      self._temporary_macs.Reserve(ec_id, mac)

  @locking.ssynchronized(_config_lock, shared=1)
  def ReserveLV(self, lv_name, ec_id):
    """Reserve an VG/LV pair for an instance.

    @type lv_name: string
    @param lv_name: the logical volume name to reserve

    """
    all_lvs = self._AllLVs()
    if lv_name in all_lvs:
      raise errors.ReservationError("LV already in use")
    else:
      self._temporary_lvs.Reserve(ec_id, lv_name)

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateDRBDSecret(self, ec_id):
    """Generate a DRBD secret.

    This checks the current disks for duplicates.

    """
    return self._temporary_secrets.Generate(self._AllDRBDSecrets(),
                                            utils.GenerateSecret,
                                            ec_id)

  def _AllLVs(self):
    """Compute the list of all LVs.

    """
    lvnames = set()
    for instance in self._config_data.instances.values():
      node_data = instance.MapLVsByNode()
      for lv_list in node_data.values():
        lvnames.update(lv_list)
    return lvnames

  def _AllIDs(self, include_temporary):
    """Compute the list of all UUIDs and names we have.

    @type include_temporary: boolean
    @param include_temporary: whether to include the _temporary_ids set
    @rtype: set
    @return: a set of IDs

    """
    existing = set()
    if include_temporary:
      existing.update(self._temporary_ids.GetReserved())
    existing.update(self._AllLVs())
    existing.update(self._config_data.instances.keys())
    existing.update(self._config_data.nodes.keys())
    existing.update([i.uuid for i in self._AllUUIDObjects() if i.uuid])
    return existing

  def _GenerateUniqueID(self, ec_id):
    """Generate an unique UUID.

    This checks the current node, instances and disk names for
    duplicates.

    @rtype: string
    @return: the unique id

    """
    existing = self._AllIDs(include_temporary=False)
    return self._temporary_ids.Generate(existing, utils.NewUUID, ec_id)

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateUniqueID(self, ec_id):
    """Generate an unique ID.

    This is just a wrapper over the unlocked version.

    @type ec_id: string
    @param ec_id: unique id for the job to reserve the id to

    """
    return self._GenerateUniqueID(ec_id)

  def _AllMACs(self):
    """Return all MACs present in the config.

    @rtype: list
    @return: the list of all MACs

    """
    result = []
    for instance in self._config_data.instances.values():
      for nic in instance.nics:
        result.append(nic.mac)

    return result

  def _AllDRBDSecrets(self):
    """Return all DRBD secrets present in the config.

    @rtype: list
    @return: the list of all DRBD secrets

    """
    def helper(disk, result):
      """Recursively gather secrets from this disk."""
      if disk.dev_type == constants.DT_DRBD8:
        result.append(disk.logical_id[5])
      if disk.children:
        for child in disk.children:
          helper(child, result)

    result = []
    for instance in self._config_data.instances.values():
      for disk in instance.disks:
        helper(disk, result)

    return result

  def _CheckDiskIDs(self, disk, l_ids, p_ids):
    """Compute duplicate disk IDs

    @type disk: L{objects.Disk}
    @param disk: the disk at which to start searching
    @type l_ids: list
    @param l_ids: list of current logical ids
    @type p_ids: list
    @param p_ids: list of current physical ids
    @rtype: list
    @return: a list of error messages

    """
    result = []
    if disk.logical_id is not None:
      if disk.logical_id in l_ids:
        result.append("duplicate logical id %s" % str(disk.logical_id))
      else:
        l_ids.append(disk.logical_id)
    if disk.physical_id is not None:
      if disk.physical_id in p_ids:
        result.append("duplicate physical id %s" % str(disk.physical_id))
      else:
        p_ids.append(disk.physical_id)

    if disk.children:
      for child in disk.children:
        result.extend(self._CheckDiskIDs(child, l_ids, p_ids))
    return result

  def _UnlockedVerifyConfig(self):
    """Verify function.

    @rtype: list
    @return: a list of error messages; a non-empty list signifies
        configuration errors

    """
    # pylint: disable=R0914
    result = []
    seen_macs = []
    ports = {}
    data = self._config_data
    cluster = data.cluster
    seen_lids = []
    seen_pids = []

    # global cluster checks
    if not cluster.enabled_hypervisors:
      result.append("enabled hypervisors list doesn't have any entries")
    invalid_hvs = set(cluster.enabled_hypervisors) - constants.HYPER_TYPES
    if invalid_hvs:
      result.append("enabled hypervisors contains invalid entries: %s" %
                    invalid_hvs)
    missing_hvp = (set(cluster.enabled_hypervisors) -
                   set(cluster.hvparams.keys()))
    if missing_hvp:
      result.append("hypervisor parameters missing for the enabled"
                    " hypervisor(s) %s" % utils.CommaJoin(missing_hvp))

    if cluster.master_node not in data.nodes:
      result.append("cluster has invalid primary node '%s'" %
                    cluster.master_node)

    def _helper(owner, attr, value, template):
      try:
        utils.ForceDictType(value, template)
      except errors.GenericError, err:
        result.append("%s has invalid %s: %s" % (owner, attr, err))

    def _helper_nic(owner, params):
      try:
        objects.NIC.CheckParameterSyntax(params)
      except errors.ConfigurationError, err:
        result.append("%s has invalid nicparams: %s" % (owner, err))

    def _helper_ipolicy(owner, params, check_std):
      try:
        objects.InstancePolicy.CheckParameterSyntax(params, check_std)
      except errors.ConfigurationError, err:
        result.append("%s has invalid instance policy: %s" % (owner, err))

    def _helper_ispecs(owner, params):
      for key, value in params.items():
        if key in constants.IPOLICY_ISPECS:
          fullkey = "ipolicy/" + key
          _helper(owner, fullkey, value, constants.ISPECS_PARAMETER_TYPES)
        else:
          # FIXME: assuming list type
          if key in constants.IPOLICY_PARAMETERS:
            exp_type = float
          else:
            exp_type = list
          if not isinstance(value, exp_type):
            result.append("%s has invalid instance policy: for %s,"
                          " expecting %s, got %s" %
                          (owner, key, exp_type.__name__, type(value)))

    # check cluster parameters
    _helper("cluster", "beparams", cluster.SimpleFillBE({}),
            constants.BES_PARAMETER_TYPES)
    _helper("cluster", "nicparams", cluster.SimpleFillNIC({}),
            constants.NICS_PARAMETER_TYPES)
    _helper_nic("cluster", cluster.SimpleFillNIC({}))
    _helper("cluster", "ndparams", cluster.SimpleFillND({}),
            constants.NDS_PARAMETER_TYPES)
    _helper_ipolicy("cluster", cluster.SimpleFillIPolicy({}), True)
    _helper_ispecs("cluster", cluster.SimpleFillIPolicy({}))

    # per-instance checks
    for instance_name in data.instances:
      instance = data.instances[instance_name]
      if instance.name != instance_name:
        result.append("instance '%s' is indexed by wrong name '%s'" %
                      (instance.name, instance_name))
      if instance.primary_node not in data.nodes:
        result.append("instance '%s' has invalid primary node '%s'" %
                      (instance_name, instance.primary_node))
      for snode in instance.secondary_nodes:
        if snode not in data.nodes:
          result.append("instance '%s' has invalid secondary node '%s'" %
                        (instance_name, snode))
      for idx, nic in enumerate(instance.nics):
        if nic.mac in seen_macs:
          result.append("instance '%s' has NIC %d mac %s duplicate" %
                        (instance_name, idx, nic.mac))
        else:
          seen_macs.append(nic.mac)
        if nic.nicparams:
          filled = cluster.SimpleFillNIC(nic.nicparams)
          owner = "instance %s nic %d" % (instance.name, idx)
          _helper(owner, "nicparams",
                  filled, constants.NICS_PARAMETER_TYPES)
          _helper_nic(owner, filled)

      # parameter checks
      if instance.beparams:
        _helper("instance %s" % instance.name, "beparams",
                cluster.FillBE(instance), constants.BES_PARAMETER_TYPES)

      # gather the drbd ports for duplicate checks
      for (idx, dsk) in enumerate(instance.disks):
        if dsk.dev_type in constants.LDS_DRBD:
          tcp_port = dsk.logical_id[2]
          if tcp_port not in ports:
            ports[tcp_port] = []
          ports[tcp_port].append((instance.name, "drbd disk %s" % idx))
      # gather network port reservation
      net_port = getattr(instance, "network_port", None)
      if net_port is not None:
        if net_port not in ports:
          ports[net_port] = []
        ports[net_port].append((instance.name, "network port"))

      # instance disk verify
      for idx, disk in enumerate(instance.disks):
        result.extend(["instance '%s' disk %d error: %s" %
                       (instance.name, idx, msg) for msg in disk.Verify()])
        result.extend(self._CheckDiskIDs(disk, seen_lids, seen_pids))

      wrong_names = _CheckInstanceDiskIvNames(instance.disks)
      if wrong_names:
        tmp = "; ".join(("name of disk %s should be '%s', but is '%s'" %
                         (idx, exp_name, actual_name))
                        for (idx, exp_name, actual_name) in wrong_names)

        result.append("Instance '%s' has wrongly named disks: %s" %
                      (instance.name, tmp))

    # cluster-wide pool of free ports
    for free_port in cluster.tcpudp_port_pool:
      if free_port not in ports:
        ports[free_port] = []
      ports[free_port].append(("cluster", "port marked as free"))

    # compute tcp/udp duplicate ports
    keys = ports.keys()
    keys.sort()
    for pnum in keys:
      pdata = ports[pnum]
      if len(pdata) > 1:
        txt = utils.CommaJoin(["%s/%s" % val for val in pdata])
        result.append("tcp/udp port %s has duplicates: %s" % (pnum, txt))

    # highest used tcp port check
    if keys:
      if keys[-1] > cluster.highest_used_port:
        result.append("Highest used port mismatch, saved %s, computed %s" %
                      (cluster.highest_used_port, keys[-1]))

    if not data.nodes[cluster.master_node].master_candidate:
      result.append("Master node is not a master candidate")

    # master candidate checks
    mc_now, mc_max, _ = self._UnlockedGetMasterCandidateStats()
    if mc_now < mc_max:
      result.append("Not enough master candidates: actual %d, target %d" %
                    (mc_now, mc_max))

    # node checks
    for node_name, node in data.nodes.items():
      if node.name != node_name:
        result.append("Node '%s' is indexed by wrong name '%s'" %
                      (node.name, node_name))
      if [node.master_candidate, node.drained, node.offline].count(True) > 1:
        result.append("Node %s state is invalid: master_candidate=%s,"
                      " drain=%s, offline=%s" %
                      (node.name, node.master_candidate, node.drained,
                       node.offline))
      if node.group not in data.nodegroups:
        result.append("Node '%s' has invalid group '%s'" %
                      (node.name, node.group))
      else:
        _helper("node %s" % node.name, "ndparams",
                cluster.FillND(node, data.nodegroups[node.group]),
                constants.NDS_PARAMETER_TYPES)

    # nodegroups checks
    nodegroups_names = set()
    for nodegroup_uuid in data.nodegroups:
      nodegroup = data.nodegroups[nodegroup_uuid]
      if nodegroup.uuid != nodegroup_uuid:
        result.append("node group '%s' (uuid: '%s') indexed by wrong uuid '%s'"
                      % (nodegroup.name, nodegroup.uuid, nodegroup_uuid))
      if utils.UUID_RE.match(nodegroup.name.lower()):
        result.append("node group '%s' (uuid: '%s') has uuid-like name" %
                      (nodegroup.name, nodegroup.uuid))
      if nodegroup.name in nodegroups_names:
        result.append("duplicate node group name '%s'" % nodegroup.name)
      else:
        nodegroups_names.add(nodegroup.name)
      group_name = "group %s" % nodegroup.name
      _helper_ipolicy(group_name, cluster.SimpleFillIPolicy(nodegroup.ipolicy),
                      False)
      _helper_ispecs(group_name, cluster.SimpleFillIPolicy(nodegroup.ipolicy))
      if nodegroup.ndparams:
        _helper(group_name, "ndparams",
                cluster.SimpleFillND(nodegroup.ndparams),
                constants.NDS_PARAMETER_TYPES)

    # drbd minors check
    _, duplicates = self._UnlockedComputeDRBDMap()
    for node, minor, instance_a, instance_b in duplicates:
      result.append("DRBD minor %d on node %s is assigned twice to instances"
                    " %s and %s" % (minor, node, instance_a, instance_b))

    # IP checks
    default_nicparams = cluster.nicparams[constants.PP_DEFAULT]
    ips = {}

    def _AddIpAddress(ip, name):
      ips.setdefault(ip, []).append(name)

    _AddIpAddress(cluster.master_ip, "cluster_ip")

    for node in data.nodes.values():
      _AddIpAddress(node.primary_ip, "node:%s/primary" % node.name)
      if node.secondary_ip != node.primary_ip:
        _AddIpAddress(node.secondary_ip, "node:%s/secondary" % node.name)

    for instance in data.instances.values():
      for idx, nic in enumerate(instance.nics):
        if nic.ip is None:
          continue

        nicparams = objects.FillDict(default_nicparams, nic.nicparams)
        nic_mode = nicparams[constants.NIC_MODE]
        nic_link = nicparams[constants.NIC_LINK]

        if nic_mode == constants.NIC_MODE_BRIDGED:
          link = "bridge:%s" % nic_link
        elif nic_mode == constants.NIC_MODE_ROUTED:
          link = "route:%s" % nic_link
        else:
          raise errors.ProgrammerError("NIC mode '%s' not handled" % nic_mode)

        _AddIpAddress("%s/%s" % (link, nic.ip),
                      "instance:%s/nic:%d" % (instance.name, idx))

    for ip, owners in ips.items():
      if len(owners) > 1:
        result.append("IP address %s is used by multiple owners: %s" %
                      (ip, utils.CommaJoin(owners)))

    return result

  @locking.ssynchronized(_config_lock, shared=1)
  def VerifyConfig(self):
    """Verify function.

    This is just a wrapper over L{_UnlockedVerifyConfig}.

    @rtype: list
    @return: a list of error messages; a non-empty list signifies
        configuration errors

    """
    return self._UnlockedVerifyConfig()

  def _UnlockedSetDiskID(self, disk, node_name):
    """Convert the unique ID to the ID needed on the target nodes.

    This is used only for drbd, which needs ip/port configuration.

    The routine descends down and updates its children also, because
    this helps when the only the top device is passed to the remote
    node.

    This function is for internal use, when the config lock is already held.

    """
    if disk.children:
      for child in disk.children:
        self._UnlockedSetDiskID(child, node_name)

    if disk.logical_id is None and disk.physical_id is not None:
      return
    if disk.dev_type == constants.LD_DRBD8:
      pnode, snode, port, pminor, sminor, secret = disk.logical_id
      if node_name not in (pnode, snode):
        raise errors.ConfigurationError("DRBD device not knowing node %s" %
                                        node_name)
      pnode_info = self._UnlockedGetNodeInfo(pnode)
      snode_info = self._UnlockedGetNodeInfo(snode)
      if pnode_info is None or snode_info is None:
        raise errors.ConfigurationError("Can't find primary or secondary node"
                                        " for %s" % str(disk))
      p_data = (pnode_info.secondary_ip, port)
      s_data = (snode_info.secondary_ip, port)
      if pnode == node_name:
        disk.physical_id = p_data + s_data + (pminor, secret)
      else: # it must be secondary, we tested above
        disk.physical_id = s_data + p_data + (sminor, secret)
    else:
      disk.physical_id = disk.logical_id
    return

  @locking.ssynchronized(_config_lock)
  def SetDiskID(self, disk, node_name):
    """Convert the unique ID to the ID needed on the target nodes.

    This is used only for drbd, which needs ip/port configuration.

    The routine descends down and updates its children also, because
    this helps when the only the top device is passed to the remote
    node.

    """
    return self._UnlockedSetDiskID(disk, node_name)

  @locking.ssynchronized(_config_lock)
  def AddTcpUdpPort(self, port):
    """Adds a new port to the available port pool.

    @warning: this method does not "flush" the configuration (via
        L{_WriteConfig}); callers should do that themselves once the
        configuration is stable

    """
    if not isinstance(port, int):
      raise errors.ProgrammerError("Invalid type passed for port")

    self._config_data.cluster.tcpudp_port_pool.add(port)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetPortList(self):
    """Returns a copy of the current port list.

    """
    return self._config_data.cluster.tcpudp_port_pool.copy()

  @locking.ssynchronized(_config_lock)
  def AllocatePort(self):
    """Allocate a port.

    The port will be taken from the available port pool or from the
    default port range (and in this case we increase
    highest_used_port).

    """
    # If there are TCP/IP ports configured, we use them first.
    if self._config_data.cluster.tcpudp_port_pool:
      port = self._config_data.cluster.tcpudp_port_pool.pop()
    else:
      port = self._config_data.cluster.highest_used_port + 1
      if port >= constants.LAST_DRBD_PORT:
        raise errors.ConfigurationError("The highest used port is greater"
                                        " than %s. Aborting." %
                                        constants.LAST_DRBD_PORT)
      self._config_data.cluster.highest_used_port = port

    self._WriteConfig()
    return port

  def _UnlockedComputeDRBDMap(self):
    """Compute the used DRBD minor/nodes.

    @rtype: (dict, list)
    @return: dictionary of node_name: dict of minor: instance_name;
        the returned dict will have all the nodes in it (even if with
        an empty list), and a list of duplicates; if the duplicates
        list is not empty, the configuration is corrupted and its caller
        should raise an exception

    """
    def _AppendUsedPorts(instance_name, disk, used):
      duplicates = []
      if disk.dev_type == constants.LD_DRBD8 and len(disk.logical_id) >= 5:
        node_a, node_b, _, minor_a, minor_b = disk.logical_id[:5]
        for node, port in ((node_a, minor_a), (node_b, minor_b)):
          assert node in used, ("Node '%s' of instance '%s' not found"
                                " in node list" % (node, instance_name))
          if port in used[node]:
            duplicates.append((node, port, instance_name, used[node][port]))
          else:
            used[node][port] = instance_name
      if disk.children:
        for child in disk.children:
          duplicates.extend(_AppendUsedPorts(instance_name, child, used))
      return duplicates

    duplicates = []
    my_dict = dict((node, {}) for node in self._config_data.nodes)
    for instance in self._config_data.instances.itervalues():
      for disk in instance.disks:
        duplicates.extend(_AppendUsedPorts(instance.name, disk, my_dict))
    for (node, minor), instance in self._temporary_drbds.iteritems():
      if minor in my_dict[node] and my_dict[node][minor] != instance:
        duplicates.append((node, minor, instance, my_dict[node][minor]))
      else:
        my_dict[node][minor] = instance
    return my_dict, duplicates

  @locking.ssynchronized(_config_lock)
  def ComputeDRBDMap(self):
    """Compute the used DRBD minor/nodes.

    This is just a wrapper over L{_UnlockedComputeDRBDMap}.

    @return: dictionary of node_name: dict of minor: instance_name;
        the returned dict will have all the nodes in it (even if with
        an empty list).

    """
    d_map, duplicates = self._UnlockedComputeDRBDMap()
    if duplicates:
      raise errors.ConfigurationError("Duplicate DRBD ports detected: %s" %
                                      str(duplicates))
    return d_map

  @locking.ssynchronized(_config_lock)
  def AllocateDRBDMinor(self, nodes, instance):
    """Allocate a drbd minor.

    The free minor will be automatically computed from the existing
    devices. A node can be given multiple times in order to allocate
    multiple minors. The result is the list of minors, in the same
    order as the passed nodes.

    @type instance: string
    @param instance: the instance for which we allocate minors

    """
    assert isinstance(instance, basestring), \
           "Invalid argument '%s' passed to AllocateDRBDMinor" % instance

    d_map, duplicates = self._UnlockedComputeDRBDMap()
    if duplicates:
      raise errors.ConfigurationError("Duplicate DRBD ports detected: %s" %
                                      str(duplicates))
    result = []
    for nname in nodes:
      ndata = d_map[nname]
      if not ndata:
        # no minors used, we can start at 0
        result.append(0)
        ndata[0] = instance
        self._temporary_drbds[(nname, 0)] = instance
        continue
      keys = ndata.keys()
      keys.sort()
      ffree = utils.FirstFree(keys)
      if ffree is None:
        # return the next minor
        # TODO: implement high-limit check
        minor = keys[-1] + 1
      else:
        minor = ffree
      # double-check minor against current instances
      assert minor not in d_map[nname], \
             ("Attempt to reuse allocated DRBD minor %d on node %s,"
              " already allocated to instance %s" %
              (minor, nname, d_map[nname][minor]))
      ndata[minor] = instance
      # double-check minor against reservation
      r_key = (nname, minor)
      assert r_key not in self._temporary_drbds, \
             ("Attempt to reuse reserved DRBD minor %d on node %s,"
              " reserved for instance %s" %
              (minor, nname, self._temporary_drbds[r_key]))
      self._temporary_drbds[r_key] = instance
      result.append(minor)
    logging.debug("Request to allocate drbd minors, input: %s, returning %s",
                  nodes, result)
    return result

  def _UnlockedReleaseDRBDMinors(self, instance):
    """Release temporary drbd minors allocated for a given instance.

    @type instance: string
    @param instance: the instance for which temporary minors should be
                     released

    """
    assert isinstance(instance, basestring), \
           "Invalid argument passed to ReleaseDRBDMinors"
    for key, name in self._temporary_drbds.items():
      if name == instance:
        del self._temporary_drbds[key]

  @locking.ssynchronized(_config_lock)
  def ReleaseDRBDMinors(self, instance):
    """Release temporary drbd minors allocated for a given instance.

    This should be called on the error paths, on the success paths
    it's automatically called by the ConfigWriter add and update
    functions.

    This function is just a wrapper over L{_UnlockedReleaseDRBDMinors}.

    @type instance: string
    @param instance: the instance for which temporary minors should be
                     released

    """
    self._UnlockedReleaseDRBDMinors(instance)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetConfigVersion(self):
    """Get the configuration version.

    @return: Config version

    """
    return self._config_data.version

  @locking.ssynchronized(_config_lock, shared=1)
  def GetClusterName(self):
    """Get cluster name.

    @return: Cluster name

    """
    return self._config_data.cluster.cluster_name

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterNode(self):
    """Get the hostname of the master node for this cluster.

    @return: Master hostname

    """
    return self._config_data.cluster.master_node

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterIP(self):
    """Get the IP of the master node for this cluster.

    @return: Master IP

    """
    return self._config_data.cluster.master_ip

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterNetdev(self):
    """Get the master network device for this cluster.

    """
    return self._config_data.cluster.master_netdev

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterNetmask(self):
    """Get the netmask of the master node for this cluster.

    """
    return self._config_data.cluster.master_netmask

  @locking.ssynchronized(_config_lock, shared=1)
  def GetUseExternalMipScript(self):
    """Get flag representing whether to use the external master IP setup script.

    """
    return self._config_data.cluster.use_external_mip_script

  @locking.ssynchronized(_config_lock, shared=1)
  def GetFileStorageDir(self):
    """Get the file storage dir for this cluster.

    """
    return self._config_data.cluster.file_storage_dir

  @locking.ssynchronized(_config_lock, shared=1)
  def GetSharedFileStorageDir(self):
    """Get the shared file storage dir for this cluster.

    """
    return self._config_data.cluster.shared_file_storage_dir

  @locking.ssynchronized(_config_lock, shared=1)
  def GetHypervisorType(self):
    """Get the hypervisor type for this cluster.

    """
    return self._config_data.cluster.enabled_hypervisors[0]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetHostKey(self):
    """Return the rsa hostkey from the config.

    @rtype: string
    @return: the rsa hostkey

    """
    return self._config_data.cluster.rsahostkeypub

  @locking.ssynchronized(_config_lock, shared=1)
  def GetDefaultIAllocator(self):
    """Get the default instance allocator for this cluster.

    """
    return self._config_data.cluster.default_iallocator

  @locking.ssynchronized(_config_lock, shared=1)
  def GetPrimaryIPFamily(self):
    """Get cluster primary ip family.

    @return: primary ip family

    """
    return self._config_data.cluster.primary_ip_family

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterNetworkParameters(self):
    """Get network parameters of the master node.

    @rtype: L{object.MasterNetworkParameters}
    @return: network parameters of the master node

    """
    cluster = self._config_data.cluster
    result = objects.MasterNetworkParameters(
      name=cluster.master_node, ip=cluster.master_ip,
      netmask=cluster.master_netmask, netdev=cluster.master_netdev,
      ip_family=cluster.primary_ip_family)

    return result

  @locking.ssynchronized(_config_lock)
  def AddNodeGroup(self, group, ec_id, check_uuid=True):
    """Add a node group to the configuration.

    This method calls group.UpgradeConfig() to fill any missing attributes
    according to their default values.

    @type group: L{objects.NodeGroup}
    @param group: the NodeGroup object to add
    @type ec_id: string
    @param ec_id: unique id for the job to use when creating a missing UUID
    @type check_uuid: bool
    @param check_uuid: add an UUID to the group if it doesn't have one or, if
                       it does, ensure that it does not exist in the
                       configuration already

    """
    self._UnlockedAddNodeGroup(group, ec_id, check_uuid)
    self._WriteConfig()

  def _UnlockedAddNodeGroup(self, group, ec_id, check_uuid):
    """Add a node group to the configuration.

    """
    logging.info("Adding node group %s to configuration", group.name)

    # Some code might need to add a node group with a pre-populated UUID
    # generated with ConfigWriter.GenerateUniqueID(). We allow them to bypass
    # the "does this UUID" exist already check.
    if check_uuid:
      self._EnsureUUID(group, ec_id)

    try:
      existing_uuid = self._UnlockedLookupNodeGroup(group.name)
    except errors.OpPrereqError:
      pass
    else:
      raise errors.OpPrereqError("Desired group name '%s' already exists as a"
                                 " node group (UUID: %s)" %
                                 (group.name, existing_uuid),
                                 errors.ECODE_EXISTS)

    group.serial_no = 1
    group.ctime = group.mtime = time.time()
    group.UpgradeConfig()

    self._config_data.nodegroups[group.uuid] = group
    self._config_data.cluster.serial_no += 1

  @locking.ssynchronized(_config_lock)
  def RemoveNodeGroup(self, group_uuid):
    """Remove a node group from the configuration.

    @type group_uuid: string
    @param group_uuid: the UUID of the node group to remove

    """
    logging.info("Removing node group %s from configuration", group_uuid)

    if group_uuid not in self._config_data.nodegroups:
      raise errors.ConfigurationError("Unknown node group '%s'" % group_uuid)

    assert len(self._config_data.nodegroups) != 1, \
            "Group '%s' is the only group, cannot be removed" % group_uuid

    del self._config_data.nodegroups[group_uuid]
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  def _UnlockedLookupNodeGroup(self, target):
    """Lookup a node group's UUID.

    @type target: string or None
    @param target: group name or UUID or None to look for the default
    @rtype: string
    @return: nodegroup UUID
    @raises errors.OpPrereqError: when the target group cannot be found

    """
    if target is None:
      if len(self._config_data.nodegroups) != 1:
        raise errors.OpPrereqError("More than one node group exists. Target"
                                   " group must be specified explicitly.")
      else:
        return self._config_data.nodegroups.keys()[0]
    if target in self._config_data.nodegroups:
      return target
    for nodegroup in self._config_data.nodegroups.values():
      if nodegroup.name == target:
        return nodegroup.uuid
    raise errors.OpPrereqError("Node group '%s' not found" % target,
                               errors.ECODE_NOENT)

  @locking.ssynchronized(_config_lock, shared=1)
  def LookupNodeGroup(self, target):
    """Lookup a node group's UUID.

    This function is just a wrapper over L{_UnlockedLookupNodeGroup}.

    @type target: string or None
    @param target: group name or UUID or None to look for the default
    @rtype: string
    @return: nodegroup UUID

    """
    return self._UnlockedLookupNodeGroup(target)

  def _UnlockedGetNodeGroup(self, uuid):
    """Lookup a node group.

    @type uuid: string
    @param uuid: group UUID
    @rtype: L{objects.NodeGroup} or None
    @return: nodegroup object, or None if not found

    """
    if uuid not in self._config_data.nodegroups:
      return None

    return self._config_data.nodegroups[uuid]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroup(self, uuid):
    """Lookup a node group.

    @type uuid: string
    @param uuid: group UUID
    @rtype: L{objects.NodeGroup} or None
    @return: nodegroup object, or None if not found

    """
    return self._UnlockedGetNodeGroup(uuid)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNodeGroupsInfo(self):
    """Get the configuration of all node groups.

    """
    return dict(self._config_data.nodegroups)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupList(self):
    """Get a list of node groups.

    """
    return self._config_data.nodegroups.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupMembersByNodes(self, nodes):
    """Get nodes which are member in the same nodegroups as the given nodes.

    """
    ngfn = lambda node_name: self._UnlockedGetNodeInfo(node_name).group
    return frozenset(member_name
                     for node_name in nodes
                     for member_name in
                       self._UnlockedGetNodeGroup(ngfn(node_name)).members)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMultiNodeGroupInfo(self, group_uuids):
    """Get the configuration of multiple node groups.

    @param group_uuids: List of node group UUIDs
    @rtype: list
    @return: List of tuples of (group_uuid, group_info)

    """
    return [(uuid, self._UnlockedGetNodeGroup(uuid)) for uuid in group_uuids]

  @locking.ssynchronized(_config_lock)
  def AddInstance(self, instance, ec_id):
    """Add an instance to the config.

    This should be used after creating a new instance.

    @type instance: L{objects.Instance}
    @param instance: the instance object

    """
    if not isinstance(instance, objects.Instance):
      raise errors.ProgrammerError("Invalid type passed to AddInstance")

    if instance.disk_template != constants.DT_DISKLESS:
      all_lvs = instance.MapLVsByNode()
      logging.info("Instance '%s' DISK_LAYOUT: %s", instance.name, all_lvs)

    all_macs = self._AllMACs()
    for nic in instance.nics:
      if nic.mac in all_macs:
        raise errors.ConfigurationError("Cannot add instance %s:"
                                        " MAC address '%s' already in use." %
                                        (instance.name, nic.mac))

    self._EnsureUUID(instance, ec_id)

    instance.serial_no = 1
    instance.ctime = instance.mtime = time.time()
    self._config_data.instances[instance.name] = instance
    self._config_data.cluster.serial_no += 1
    self._UnlockedReleaseDRBDMinors(instance.name)
    self._WriteConfig()

  def _EnsureUUID(self, item, ec_id):
    """Ensures a given object has a valid UUID.

    @param item: the instance or node to be checked
    @param ec_id: the execution context id for the uuid reservation

    """
    if not item.uuid:
      item.uuid = self._GenerateUniqueID(ec_id)
    elif item.uuid in self._AllIDs(include_temporary=True):
      raise errors.ConfigurationError("Cannot add '%s': UUID %s already"
                                      " in use" % (item.name, item.uuid))

  def _SetInstanceStatus(self, instance_name, status):
    """Set the instance's status to a given value.

    """
    assert status in constants.ADMINST_ALL, \
           "Invalid status '%s' passed to SetInstanceStatus" % (status,)

    if instance_name not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" %
                                      instance_name)
    instance = self._config_data.instances[instance_name]
    if instance.admin_state != status:
      instance.admin_state = status
      instance.serial_no += 1
      instance.mtime = time.time()
      self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def MarkInstanceUp(self, instance_name):
    """Mark the instance status to up in the config.

    """
    self._SetInstanceStatus(instance_name, constants.ADMINST_UP)

  @locking.ssynchronized(_config_lock)
  def MarkInstanceOffline(self, instance_name):
    """Mark the instance status to down in the config.

    """
    self._SetInstanceStatus(instance_name, constants.ADMINST_OFFLINE)

  @locking.ssynchronized(_config_lock)
  def RemoveInstance(self, instance_name):
    """Remove the instance from the configuration.

    """
    if instance_name not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" % instance_name)

    # If a network port has been allocated to the instance,
    # return it to the pool of free ports.
    inst = self._config_data.instances[instance_name]
    network_port = getattr(inst, "network_port", None)
    if network_port is not None:
      self._config_data.cluster.tcpudp_port_pool.add(network_port)

    del self._config_data.instances[instance_name]
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def RenameInstance(self, old_name, new_name):
    """Rename an instance.

    This needs to be done in ConfigWriter and not by RemoveInstance
    combined with AddInstance as only we can guarantee an atomic
    rename.

    """
    if old_name not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" % old_name)

    # Operate on a copy to not loose instance object in case of a failure
    inst = self._config_data.instances[old_name].Copy()
    inst.name = new_name

    for (idx, disk) in enumerate(inst.disks):
      if disk.dev_type == constants.LD_FILE:
        # rename the file paths in logical and physical id
        file_storage_dir = os.path.dirname(os.path.dirname(disk.logical_id[1]))
        disk.logical_id = (disk.logical_id[0],
                           utils.PathJoin(file_storage_dir, inst.name,
                                          "disk%s" % idx))
        disk.physical_id = disk.logical_id

    # Actually replace instance object
    del self._config_data.instances[old_name]
    self._config_data.instances[inst.name] = inst

    # Force update of ssconf files
    self._config_data.cluster.serial_no += 1

    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def MarkInstanceDown(self, instance_name):
    """Mark the status of an instance to down in the configuration.

    """
    self._SetInstanceStatus(instance_name, constants.ADMINST_DOWN)

  def _UnlockedGetInstanceList(self):
    """Get the list of instances.

    This function is for internal use, when the config lock is already held.

    """
    return self._config_data.instances.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceList(self):
    """Get the list of instances.

    @return: array of instances, ex. ['instance2.example.com',
        'instance1.example.com']

    """
    return self._UnlockedGetInstanceList()

  def ExpandInstanceName(self, short_name):
    """Attempt to expand an incomplete instance name.

    """
    # Locking is done in L{ConfigWriter.GetInstanceList}
    return _MatchNameComponentIgnoreCase(short_name, self.GetInstanceList())

  def _UnlockedGetInstanceInfo(self, instance_name):
    """Returns information about an instance.

    This function is for internal use, when the config lock is already held.

    """
    if instance_name not in self._config_data.instances:
      return None

    return self._config_data.instances[instance_name]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceInfo(self, instance_name):
    """Returns information about an instance.

    It takes the information from the configuration file. Other information of
    an instance are taken from the live systems.

    @param instance_name: name of the instance, e.g.
        I{instance1.example.com}

    @rtype: L{objects.Instance}
    @return: the instance object

    """
    return self._UnlockedGetInstanceInfo(instance_name)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceNodeGroups(self, instance_name, primary_only=False):
    """Returns set of node group UUIDs for instance's nodes.

    @rtype: frozenset

    """
    instance = self._UnlockedGetInstanceInfo(instance_name)
    if not instance:
      raise errors.ConfigurationError("Unknown instance '%s'" % instance_name)

    if primary_only:
      nodes = [instance.primary_node]
    else:
      nodes = instance.all_nodes

    return frozenset(self._UnlockedGetNodeInfo(node_name).group
                     for node_name in nodes)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMultiInstanceInfo(self, instances):
    """Get the configuration of multiple instances.

    @param instances: list of instance names
    @rtype: list
    @return: list of tuples (instance, instance_info), where
        instance_info is what would GetInstanceInfo return for the
        node, while keeping the original order

    """
    return [(name, self._UnlockedGetInstanceInfo(name)) for name in instances]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllInstancesInfo(self):
    """Get the configuration of all instances.

    @rtype: dict
    @return: dict of (instance, instance_info), where instance_info is what
              would GetInstanceInfo return for the node

    """
    my_dict = dict([(instance, self._UnlockedGetInstanceInfo(instance))
                    for instance in self._UnlockedGetInstanceList()])
    return my_dict

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstancesInfoByFilter(self, filter_fn):
    """Get instance configuration with a filter.

    @type filter_fn: callable
    @param filter_fn: Filter function receiving instance object as parameter,
      returning boolean. Important: this function is called while the
      configuration locks is held. It must not do any complex work or call
      functions potentially leading to a deadlock. Ideally it doesn't call any
      other functions and just compares instance attributes.

    """
    return dict((name, inst)
                for (name, inst) in self._config_data.instances.items()
                if filter_fn(inst))

  @locking.ssynchronized(_config_lock)
  def AddNode(self, node, ec_id):
    """Add a node to the configuration.

    @type node: L{objects.Node}
    @param node: a Node instance

    """
    logging.info("Adding node %s to configuration", node.name)

    self._EnsureUUID(node, ec_id)

    node.serial_no = 1
    node.ctime = node.mtime = time.time()
    self._UnlockedAddNodeToGroup(node.name, node.group)
    self._config_data.nodes[node.name] = node
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def RemoveNode(self, node_name):
    """Remove a node from the configuration.

    """
    logging.info("Removing node %s from configuration", node_name)

    if node_name not in self._config_data.nodes:
      raise errors.ConfigurationError("Unknown node '%s'" % node_name)

    self._UnlockedRemoveNodeFromGroup(self._config_data.nodes[node_name])
    del self._config_data.nodes[node_name]
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  def ExpandNodeName(self, short_name):
    """Attempt to expand an incomplete node name.

    """
    # Locking is done in L{ConfigWriter.GetNodeList}
    return _MatchNameComponentIgnoreCase(short_name, self.GetNodeList())

  def _UnlockedGetNodeInfo(self, node_name):
    """Get the configuration of a node, as stored in the config.

    This function is for internal use, when the config lock is already
    held.

    @param node_name: the node name, e.g. I{node1.example.com}

    @rtype: L{objects.Node}
    @return: the node object

    """
    if node_name not in self._config_data.nodes:
      return None

    return self._config_data.nodes[node_name]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeInfo(self, node_name):
    """Get the configuration of a node, as stored in the config.

    This is just a locked wrapper over L{_UnlockedGetNodeInfo}.

    @param node_name: the node name, e.g. I{node1.example.com}

    @rtype: L{objects.Node}
    @return: the node object

    """
    return self._UnlockedGetNodeInfo(node_name)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeInstances(self, node_name):
    """Get the instances of a node, as stored in the config.

    @param node_name: the node name, e.g. I{node1.example.com}

    @rtype: (list, list)
    @return: a tuple with two lists: the primary and the secondary instances

    """
    pri = []
    sec = []
    for inst in self._config_data.instances.values():
      if inst.primary_node == node_name:
        pri.append(inst.name)
      if node_name in inst.secondary_nodes:
        sec.append(inst.name)
    return (pri, sec)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupInstances(self, uuid, primary_only=False):
    """Get the instances of a node group.

    @param uuid: Node group UUID
    @param primary_only: Whether to only consider primary nodes
    @rtype: frozenset
    @return: List of instance names in node group

    """
    if primary_only:
      nodes_fn = lambda inst: [inst.primary_node]
    else:
      nodes_fn = lambda inst: inst.all_nodes

    return frozenset(inst.name
                     for inst in self._config_data.instances.values()
                     for node_name in nodes_fn(inst)
                     if self._UnlockedGetNodeInfo(node_name).group == uuid)

  def _UnlockedGetNodeList(self):
    """Return the list of nodes which are in the configuration.

    This function is for internal use, when the config lock is already
    held.

    @rtype: list

    """
    return self._config_data.nodes.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeList(self):
    """Return the list of nodes which are in the configuration.

    """
    return self._UnlockedGetNodeList()

  def _UnlockedGetOnlineNodeList(self):
    """Return the list of nodes which are online.

    """
    all_nodes = [self._UnlockedGetNodeInfo(node)
                 for node in self._UnlockedGetNodeList()]
    return [node.name for node in all_nodes if not node.offline]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetOnlineNodeList(self):
    """Return the list of nodes which are online.

    """
    return self._UnlockedGetOnlineNodeList()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetVmCapableNodeList(self):
    """Return the list of nodes which are not vm capable.

    """
    all_nodes = [self._UnlockedGetNodeInfo(node)
                 for node in self._UnlockedGetNodeList()]
    return [node.name for node in all_nodes if node.vm_capable]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNonVmCapableNodeList(self):
    """Return the list of nodes which are not vm capable.

    """
    all_nodes = [self._UnlockedGetNodeInfo(node)
                 for node in self._UnlockedGetNodeList()]
    return [node.name for node in all_nodes if not node.vm_capable]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMultiNodeInfo(self, nodes):
    """Get the configuration of multiple nodes.

    @param nodes: list of node names
    @rtype: list
    @return: list of tuples of (node, node_info), where node_info is
        what would GetNodeInfo return for the node, in the original
        order

    """
    return [(name, self._UnlockedGetNodeInfo(name)) for name in nodes]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNodesInfo(self):
    """Get the configuration of all nodes.

    @rtype: dict
    @return: dict of (node, node_info), where node_info is what
              would GetNodeInfo return for the node

    """
    return self._UnlockedGetAllNodesInfo()

  def _UnlockedGetAllNodesInfo(self):
    """Gets configuration of all nodes.

    @note: See L{GetAllNodesInfo}

    """
    return dict([(node, self._UnlockedGetNodeInfo(node))
                 for node in self._UnlockedGetNodeList()])

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupsFromNodes(self, nodes):
    """Returns groups for a list of nodes.

    @type nodes: list of string
    @param nodes: List of node names
    @rtype: frozenset

    """
    return frozenset(self._UnlockedGetNodeInfo(name).group for name in nodes)

  def _UnlockedGetMasterCandidateStats(self, exceptions=None):
    """Get the number of current and maximum desired and possible candidates.

    @type exceptions: list
    @param exceptions: if passed, list of nodes that should be ignored
    @rtype: tuple
    @return: tuple of (current, desired and possible, possible)

    """
    mc_now = mc_should = mc_max = 0
    for node in self._config_data.nodes.values():
      if exceptions and node.name in exceptions:
        continue
      if not (node.offline or node.drained) and node.master_capable:
        mc_max += 1
      if node.master_candidate:
        mc_now += 1
    mc_should = min(mc_max, self._config_data.cluster.candidate_pool_size)
    return (mc_now, mc_should, mc_max)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterCandidateStats(self, exceptions=None):
    """Get the number of current and maximum possible candidates.

    This is just a wrapper over L{_UnlockedGetMasterCandidateStats}.

    @type exceptions: list
    @param exceptions: if passed, list of nodes that should be ignored
    @rtype: tuple
    @return: tuple of (current, max)

    """
    return self._UnlockedGetMasterCandidateStats(exceptions)

  @locking.ssynchronized(_config_lock)
  def MaintainCandidatePool(self, exceptions):
    """Try to grow the candidate pool to the desired size.

    @type exceptions: list
    @param exceptions: if passed, list of nodes that should be ignored
    @rtype: list
    @return: list with the adjusted nodes (L{objects.Node} instances)

    """
    mc_now, mc_max, _ = self._UnlockedGetMasterCandidateStats(exceptions)
    mod_list = []
    if mc_now < mc_max:
      node_list = self._config_data.nodes.keys()
      random.shuffle(node_list)
      for name in node_list:
        if mc_now >= mc_max:
          break
        node = self._config_data.nodes[name]
        if (node.master_candidate or node.offline or node.drained or
            node.name in exceptions or not node.master_capable):
          continue
        mod_list.append(node)
        node.master_candidate = True
        node.serial_no += 1
        mc_now += 1
      if mc_now != mc_max:
        # this should not happen
        logging.warning("Warning: MaintainCandidatePool didn't manage to"
                        " fill the candidate pool (%d/%d)", mc_now, mc_max)
      if mod_list:
        self._config_data.cluster.serial_no += 1
        self._WriteConfig()

    return mod_list

  def _UnlockedAddNodeToGroup(self, node_name, nodegroup_uuid):
    """Add a given node to the specified group.

    """
    if nodegroup_uuid not in self._config_data.nodegroups:
      # This can happen if a node group gets deleted between its lookup and
      # when we're adding the first node to it, since we don't keep a lock in
      # the meantime. It's ok though, as we'll fail cleanly if the node group
      # is not found anymore.
      raise errors.OpExecError("Unknown node group: %s" % nodegroup_uuid)
    if node_name not in self._config_data.nodegroups[nodegroup_uuid].members:
      self._config_data.nodegroups[nodegroup_uuid].members.append(node_name)

  def _UnlockedRemoveNodeFromGroup(self, node):
    """Remove a given node from its group.

    """
    nodegroup = node.group
    if nodegroup not in self._config_data.nodegroups:
      logging.warning("Warning: node '%s' has unknown node group '%s'"
                      " (while being removed from it)", node.name, nodegroup)
    nodegroup_obj = self._config_data.nodegroups[nodegroup]
    if node.name not in nodegroup_obj.members:
      logging.warning("Warning: node '%s' not a member of its node group '%s'"
                      " (while being removed from it)", node.name, nodegroup)
    else:
      nodegroup_obj.members.remove(node.name)

  @locking.ssynchronized(_config_lock)
  def AssignGroupNodes(self, mods):
    """Changes the group of a number of nodes.

    @type mods: list of tuples; (node name, new group UUID)
    @param mods: Node membership modifications

    """
    groups = self._config_data.nodegroups
    nodes = self._config_data.nodes

    resmod = []

    # Try to resolve names/UUIDs first
    for (node_name, new_group_uuid) in mods:
      try:
        node = nodes[node_name]
      except KeyError:
        raise errors.ConfigurationError("Unable to find node '%s'" % node_name)

      if node.group == new_group_uuid:
        # Node is being assigned to its current group
        logging.debug("Node '%s' was assigned to its current group (%s)",
                      node_name, node.group)
        continue

      # Try to find current group of node
      try:
        old_group = groups[node.group]
      except KeyError:
        raise errors.ConfigurationError("Unable to find old group '%s'" %
                                        node.group)

      # Try to find new group for node
      try:
        new_group = groups[new_group_uuid]
      except KeyError:
        raise errors.ConfigurationError("Unable to find new group '%s'" %
                                        new_group_uuid)

      assert node.name in old_group.members, \
        ("Inconsistent configuration: node '%s' not listed in members for its"
         " old group '%s'" % (node.name, old_group.uuid))
      assert node.name not in new_group.members, \
        ("Inconsistent configuration: node '%s' already listed in members for"
         " its new group '%s'" % (node.name, new_group.uuid))

      resmod.append((node, old_group, new_group))

    # Apply changes
    for (node, old_group, new_group) in resmod:
      assert node.uuid != new_group.uuid and old_group.uuid != new_group.uuid, \
        "Assigning to current group is not possible"

      node.group = new_group.uuid

      # Update members of involved groups
      if node.name in old_group.members:
        old_group.members.remove(node.name)
      if node.name not in new_group.members:
        new_group.members.append(node.name)

    # Update timestamps and serials (only once per node/group object)
    now = time.time()
    for obj in frozenset(itertools.chain(*resmod)): # pylint: disable=W0142
      obj.serial_no += 1
      obj.mtime = now

    # Force ssconf update
    self._config_data.cluster.serial_no += 1

    self._WriteConfig()

  def _BumpSerialNo(self):
    """Bump up the serial number of the config.

    """
    self._config_data.serial_no += 1
    self._config_data.mtime = time.time()

  def _AllUUIDObjects(self):
    """Returns all objects with uuid attributes.

    """
    return (self._config_data.instances.values() +
            self._config_data.nodes.values() +
            self._config_data.nodegroups.values() +
            [self._config_data.cluster])

  def _OpenConfig(self, accept_foreign):
    """Read the config data from disk.

    """
    raw_data = utils.ReadFile(self._cfg_file)

    try:
      data = objects.ConfigData.FromDict(serializer.Load(raw_data))
    except Exception, err:
      raise errors.ConfigurationError(err)

    # Make sure the configuration has the right version
    _ValidateConfig(data)

    if (not hasattr(data, "cluster") or
        not hasattr(data.cluster, "rsahostkeypub")):
      raise errors.ConfigurationError("Incomplete configuration"
                                      " (missing cluster.rsahostkeypub)")

    if data.cluster.master_node != self._my_hostname and not accept_foreign:
      msg = ("The configuration denotes node %s as master, while my"
             " hostname is %s; opening a foreign configuration is only"
             " possible in accept_foreign mode" %
             (data.cluster.master_node, self._my_hostname))
      raise errors.ConfigurationError(msg)

    # Upgrade configuration if needed
    data.UpgradeConfig()

    self._config_data = data
    # reset the last serial as -1 so that the next write will cause
    # ssconf update
    self._last_cluster_serial = -1

    # And finally run our (custom) config upgrade sequence
    self._UpgradeConfig()

    self._cfg_id = utils.GetFileID(path=self._cfg_file)

  def _UpgradeConfig(self):
    """Run upgrade steps that cannot be done purely in the objects.

    This is because some data elements need uniqueness across the
    whole configuration, etc.

    @warning: this function will call L{_WriteConfig()}, but also
        L{DropECReservations} so it needs to be called only from a
        "safe" place (the constructor). If one wanted to call it with
        the lock held, a DropECReservationUnlocked would need to be
        created first, to avoid causing deadlock.

    """
    modified = False
    for item in self._AllUUIDObjects():
      if item.uuid is None:
        item.uuid = self._GenerateUniqueID(_UPGRADE_CONFIG_JID)
        modified = True
    if not self._config_data.nodegroups:
      default_nodegroup_name = constants.INITIAL_NODE_GROUP_NAME
      default_nodegroup = objects.NodeGroup(name=default_nodegroup_name,
                                            members=[])
      self._UnlockedAddNodeGroup(default_nodegroup, _UPGRADE_CONFIG_JID, True)
      modified = True
    for node in self._config_data.nodes.values():
      if not node.group:
        node.group = self.LookupNodeGroup(None)
        modified = True
      # This is technically *not* an upgrade, but needs to be done both when
      # nodegroups are being added, and upon normally loading the config,
      # because the members list of a node group is discarded upon
      # serializing/deserializing the object.
      self._UnlockedAddNodeToGroup(node.name, node.group)
    if modified:
      self._WriteConfig()
      # This is ok even if it acquires the internal lock, as _UpgradeConfig is
      # only called at config init time, without the lock held
      self.DropECReservations(_UPGRADE_CONFIG_JID)

  def _DistributeConfig(self, feedback_fn):
    """Distribute the configuration to the other nodes.

    Currently, this only copies the configuration file. In the future,
    it could be used to encapsulate the 2/3-phase update mechanism.

    """
    if self._offline:
      return True

    bad = False

    node_list = []
    addr_list = []
    myhostname = self._my_hostname
    # we can skip checking whether _UnlockedGetNodeInfo returns None
    # since the node list comes from _UnlocketGetNodeList, and we are
    # called with the lock held, so no modifications should take place
    # in between
    for node_name in self._UnlockedGetNodeList():
      if node_name == myhostname:
        continue
      node_info = self._UnlockedGetNodeInfo(node_name)
      if not node_info.master_candidate:
        continue
      node_list.append(node_info.name)
      addr_list.append(node_info.primary_ip)

    # TODO: Use dedicated resolver talking to config writer for name resolution
    result = \
      self._GetRpc(addr_list).call_upload_file(node_list, self._cfg_file)
    for to_node, to_result in result.items():
      msg = to_result.fail_msg
      if msg:
        msg = ("Copy of file %s to node %s failed: %s" %
               (self._cfg_file, to_node, msg))
        logging.error(msg)

        if feedback_fn:
          feedback_fn(msg)

        bad = True

    return not bad

  def _WriteConfig(self, destination=None, feedback_fn=None):
    """Write the configuration data to persistent storage.

    """
    assert feedback_fn is None or callable(feedback_fn)

    # Warn on config errors, but don't abort the save - the
    # configuration has already been modified, and we can't revert;
    # the best we can do is to warn the user and save as is, leaving
    # recovery to the user
    config_errors = self._UnlockedVerifyConfig()
    if config_errors:
      errmsg = ("Configuration data is not consistent: %s" %
                (utils.CommaJoin(config_errors)))
      logging.critical(errmsg)
      if feedback_fn:
        feedback_fn(errmsg)

    if destination is None:
      destination = self._cfg_file
    self._BumpSerialNo()
    txt = serializer.Dump(self._config_data.ToDict())

    getents = self._getents()
    try:
      fd = utils.SafeWriteFile(destination, self._cfg_id, data=txt,
                               close=False, gid=getents.confd_gid, mode=0640)
    except errors.LockError:
      raise errors.ConfigurationError("The configuration file has been"
                                      " modified since the last write, cannot"
                                      " update")
    try:
      self._cfg_id = utils.GetFileID(fd=fd)
    finally:
      os.close(fd)

    self.write_count += 1

    # and redistribute the config file to master candidates
    self._DistributeConfig(feedback_fn)

    # Write ssconf files on all nodes (including locally)
    if self._last_cluster_serial < self._config_data.cluster.serial_no:
      if not self._offline:
        result = self._GetRpc(None).call_write_ssconf_files(
          self._UnlockedGetOnlineNodeList(),
          self._UnlockedGetSsconfValues())

        for nname, nresu in result.items():
          msg = nresu.fail_msg
          if msg:
            errmsg = ("Error while uploading ssconf files to"
                      " node %s: %s" % (nname, msg))
            logging.warning(errmsg)

            if feedback_fn:
              feedback_fn(errmsg)

      self._last_cluster_serial = self._config_data.cluster.serial_no

  def _UnlockedGetSsconfValues(self):
    """Return the values needed by ssconf.

    @rtype: dict
    @return: a dictionary with keys the ssconf names and values their
        associated value

    """
    fn = "\n".join
    instance_names = utils.NiceSort(self._UnlockedGetInstanceList())
    node_names = utils.NiceSort(self._UnlockedGetNodeList())
    node_info = [self._UnlockedGetNodeInfo(name) for name in node_names]
    node_pri_ips = ["%s %s" % (ninfo.name, ninfo.primary_ip)
                    for ninfo in node_info]
    node_snd_ips = ["%s %s" % (ninfo.name, ninfo.secondary_ip)
                    for ninfo in node_info]

    instance_data = fn(instance_names)
    off_data = fn(node.name for node in node_info if node.offline)
    on_data = fn(node.name for node in node_info if not node.offline)
    mc_data = fn(node.name for node in node_info if node.master_candidate)
    mc_ips_data = fn(node.primary_ip for node in node_info
                     if node.master_candidate)
    node_data = fn(node_names)
    node_pri_ips_data = fn(node_pri_ips)
    node_snd_ips_data = fn(node_snd_ips)

    cluster = self._config_data.cluster
    cluster_tags = fn(cluster.GetTags())

    hypervisor_list = fn(cluster.enabled_hypervisors)

    uid_pool = uidpool.FormatUidPool(cluster.uid_pool, separator="\n")

    nodegroups = ["%s %s" % (nodegroup.uuid, nodegroup.name) for nodegroup in
                  self._config_data.nodegroups.values()]
    nodegroups_data = fn(utils.NiceSort(nodegroups))
    networks = ["%s %s" % (net.uuid, net.name) for net in
                self._config_data.networks.values()]
    networks_data = fn(utils.NiceSort(networks))

    ssconf_values = {
      constants.SS_CLUSTER_NAME: cluster.cluster_name,
      constants.SS_CLUSTER_TAGS: cluster_tags,
      constants.SS_FILE_STORAGE_DIR: cluster.file_storage_dir,
      constants.SS_SHARED_FILE_STORAGE_DIR: cluster.shared_file_storage_dir,
      constants.SS_MASTER_CANDIDATES: mc_data,
      constants.SS_MASTER_CANDIDATES_IPS: mc_ips_data,
      constants.SS_MASTER_IP: cluster.master_ip,
      constants.SS_MASTER_NETDEV: cluster.master_netdev,
      constants.SS_MASTER_NETMASK: str(cluster.master_netmask),
      constants.SS_MASTER_NODE: cluster.master_node,
      constants.SS_NODE_LIST: node_data,
      constants.SS_NODE_PRIMARY_IPS: node_pri_ips_data,
      constants.SS_NODE_SECONDARY_IPS: node_snd_ips_data,
      constants.SS_OFFLINE_NODES: off_data,
      constants.SS_ONLINE_NODES: on_data,
      constants.SS_PRIMARY_IP_FAMILY: str(cluster.primary_ip_family),
      constants.SS_INSTANCE_LIST: instance_data,
      constants.SS_RELEASE_VERSION: constants.RELEASE_VERSION,
      constants.SS_HYPERVISOR_LIST: hypervisor_list,
      constants.SS_MAINTAIN_NODE_HEALTH: str(cluster.maintain_node_health),
      constants.SS_UID_POOL: uid_pool,
      constants.SS_NODEGROUPS: nodegroups_data,
      constants.SS_NETWORKS: networks_data,
      }
    bad_values = [(k, v) for k, v in ssconf_values.items()
                  if not isinstance(v, (str, basestring))]
    if bad_values:
      err = utils.CommaJoin("%s=%s" % (k, v) for k, v in bad_values)
      raise errors.ConfigurationError("Some ssconf key(s) have non-string"
                                      " values: %s" % err)
    return ssconf_values

  @locking.ssynchronized(_config_lock, shared=1)
  def GetSsconfValues(self):
    """Wrapper using lock around _UnlockedGetSsconf().

    """
    return self._UnlockedGetSsconfValues()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetVGName(self):
    """Return the volume group name.

    """
    return self._config_data.cluster.volume_group_name

  @locking.ssynchronized(_config_lock)
  def SetVGName(self, vg_name):
    """Set the volume group name.

    """
    self._config_data.cluster.volume_group_name = vg_name
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetDRBDHelper(self):
    """Return DRBD usermode helper.

    """
    return self._config_data.cluster.drbd_usermode_helper

  @locking.ssynchronized(_config_lock)
  def SetDRBDHelper(self, drbd_helper):
    """Set DRBD usermode helper.

    """
    self._config_data.cluster.drbd_usermode_helper = drbd_helper
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMACPrefix(self):
    """Return the mac prefix.

    """
    return self._config_data.cluster.mac_prefix

  @locking.ssynchronized(_config_lock, shared=1)
  def GetClusterInfo(self):
    """Returns information about the cluster

    @rtype: L{objects.Cluster}
    @return: the cluster object

    """
    return self._config_data.cluster

  @locking.ssynchronized(_config_lock, shared=1)
  def HasAnyDiskOfType(self, dev_type):
    """Check if in there is at disk of the given type in the configuration.

    """
    return self._config_data.HasAnyDiskOfType(dev_type)

  @locking.ssynchronized(_config_lock)
  def Update(self, target, feedback_fn):
    """Notify function to be called after updates.

    This function must be called when an object (as returned by
    GetInstanceInfo, GetNodeInfo, GetCluster) has been updated and the
    caller wants the modifications saved to the backing store. Note
    that all modified objects will be saved, but the target argument
    is the one the caller wants to ensure that it's saved.

    @param target: an instance of either L{objects.Cluster},
        L{objects.Node} or L{objects.Instance} which is existing in
        the cluster
    @param feedback_fn: Callable feedback function

    """
    if self._config_data is None:
      raise errors.ProgrammerError("Configuration file not read,"
                                   " cannot save.")
    update_serial = False
    if isinstance(target, objects.Cluster):
      test = target == self._config_data.cluster
    elif isinstance(target, objects.Node):
      test = target in self._config_data.nodes.values()
      update_serial = True
    elif isinstance(target, objects.Instance):
      test = target in self._config_data.instances.values()
    elif isinstance(target, objects.NodeGroup):
      test = target in self._config_data.nodegroups.values()
    elif isinstance(target, objects.Network):
      test = target in self._config_data.networks.values()
    else:
      raise errors.ProgrammerError("Invalid object type (%s) passed to"
                                   " ConfigWriter.Update" % type(target))
    if not test:
      raise errors.ConfigurationError("Configuration updated since object"
                                      " has been read or unknown object")
    target.serial_no += 1
    target.mtime = now = time.time()

    if update_serial:
      # for node updates, we need to increase the cluster serial too
      self._config_data.cluster.serial_no += 1
      self._config_data.cluster.mtime = now

    if isinstance(target, objects.Instance):
      self._UnlockedReleaseDRBDMinors(target.name)

    self._WriteConfig(feedback_fn=feedback_fn)

  @locking.ssynchronized(_config_lock)
  def DropECReservations(self, ec_id):
    """Drop per-execution-context reservations

    """
    for rm in self._all_rms:
      rm.DropECReservations(ec_id)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNetworksInfo(self):
    """Get the configuration of all networks

    """
    return dict(self._config_data.networks)

  def _UnlockedGetNetworkList(self):
    """Get the list of networks.

    This function is for internal use, when the config lock is already held.

    """
    return self._config_data.networks.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNetworkList(self):
    """Get the list of networks.

    @return: array of networks, ex. ["main", "vlan100", "200]

    """
    return self._UnlockedGetNetworkList()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNetworkNames(self):
    """Get a list of network names

    """
    names = [network.name
             for network in self._config_data.networks.values()]
    return names

  def _UnlockedGetNetwork(self, uuid):
    """Returns information about a network.

    This function is for internal use, when the config lock is already held.

    """
    if uuid not in self._config_data.networks:
      return None

    return self._config_data.networks[uuid]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNetwork(self, uuid):
    """Returns information about a network.

    It takes the information from the configuration file.

    @param uuid: UUID of the network

    @rtype: L{objects.Network}
    @return: the network object

    """
    return self._UnlockedGetNetwork(uuid)

  @locking.ssynchronized(_config_lock)
  def AddNetwork(self, net, ec_id, check_uuid=True):
    """Add a network to the configuration.

    @type net: L{objects.Network}
    @param net: the Network object to add
    @type ec_id: string
    @param ec_id: unique id for the job to use when creating a missing UUID

    """
    self._UnlockedAddNetwork(net, ec_id, check_uuid)
    self._WriteConfig()

  def _UnlockedAddNetwork(self, net, ec_id, check_uuid):
    """Add a network to the configuration.

    """
    logging.info("Adding network %s to configuration", net.name)

    if check_uuid:
      self._EnsureUUID(net, ec_id)

    existing_uuid = self._UnlockedLookupNetwork(net.name)
    if existing_uuid:
      raise errors.OpPrereqError("Desired network name '%s' already"
                                 " exists as a network (UUID: %s)" %
                                 (net.name, existing_uuid),
                                 errors.ECODE_EXISTS)
    net.serial_no = 1
    self._config_data.networks[net.uuid] = net
    self._config_data.cluster.serial_no += 1

  def _UnlockedLookupNetwork(self, target):
    """Lookup a network's UUID.

    @type target: string
    @param target: network name or UUID
    @rtype: string
    @return: network UUID
    @raises errors.OpPrereqError: when the target network cannot be found

    """
    if target in self._config_data.networks:
      return target
    for net in self._config_data.networks.values():
      if net.name == target:
        return net.uuid
    return None

  @locking.ssynchronized(_config_lock, shared=1)
  def LookupNetwork(self, target):
    """Lookup a network's UUID.

    This function is just a wrapper over L{_UnlockedLookupNetwork}.

    @type target: string
    @param target: network name or UUID
    @rtype: string
    @return: network UUID

    """
    return self._UnlockedLookupNetwork(target)

  @locking.ssynchronized(_config_lock)
  def RemoveNetwork(self, network_uuid):
    """Remove a network from the configuration.

    @type network_uuid: string
    @param network_uuid: the UUID of the network to remove

    """
    logging.info("Removing network %s from configuration", network_uuid)

    if network_uuid not in self._config_data.networks:
      raise errors.ConfigurationError("Unknown network '%s'" % network_uuid)

    del self._config_data.networks[network_uuid]
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()
