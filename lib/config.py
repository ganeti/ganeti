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


"""Configuration management for Ganeti

This module provides the interface to the Ganeti cluster configuration.

The configuration data is stored on every node but is updated on the master
only. After each update, the master distributes the data to the other nodes.

Currently, the data storage format is JSON. YAML was slow and consuming too
much memory.

"""

# pylint: disable=R0904
# R0904: Too many public methods

import copy
import os
import random
import logging
import time
import itertools

from ganeti import errors
from ganeti import locking
from ganeti import utils
from ganeti import constants
import ganeti.rpc.node as rpc
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

  def GetECReserved(self, ec_id):
    """ Used when you want to retrieve all reservations for a specific
        execution context. E.g when commiting reserved IPs for a specific
        network.

    """
    ec_reserved = set()
    if ec_id in self._ec_reserved:
      ec_reserved.update(self._ec_reserved[ec_id])
    return ec_reserved

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


class ConfigWriter(object):
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
    self._temporary_ips = TemporaryReservationManager()
    self._all_rms = [self._temporary_ids, self._temporary_macs,
                     self._temporary_secrets, self._temporary_lvs,
                     self._temporary_ips]
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
  def GetNdGroupParams(self, nodegroup):
    """Get the node groups params populated with cluster defaults.

    @type nodegroup: L{objects.NodeGroup}
    @param nodegroup: The node group we want to know the params for
    @return: A dict with the filled in node group params

    """
    return self._config_data.cluster.FillNDGroup(nodegroup)

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

  def _UnlockedGetNetworkMACPrefix(self, net_uuid):
    """Return the network mac prefix if it exists or the cluster level default.

    """
    prefix = None
    if net_uuid:
      nobj = self._UnlockedGetNetwork(net_uuid)
      if nobj.mac_prefix:
        prefix = nobj.mac_prefix

    return prefix

  def _GenerateOneMAC(self, prefix=None):
    """Return a function that randomly generates a MAC suffic
       and appends it to the given prefix. If prefix is not given get
       the cluster level default.

    """
    if not prefix:
      prefix = self._config_data.cluster.mac_prefix

    def GenMac():
      byte1 = random.randrange(0, 256)
      byte2 = random.randrange(0, 256)
      byte3 = random.randrange(0, 256)
      mac = "%s:%02x:%02x:%02x" % (prefix, byte1, byte2, byte3)
      return mac

    return GenMac

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateMAC(self, net_uuid, ec_id):
    """Generate a MAC for an instance.

    This should check the current instances for duplicates.

    """
    existing = self._AllMACs()
    prefix = self._UnlockedGetNetworkMACPrefix(net_uuid)
    gen_mac = self._GenerateOneMAC(prefix)
    return self._temporary_ids.Generate(existing, gen_mac, ec_id)

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

  def _UnlockedCommitTemporaryIps(self, ec_id):
    """Commit all reserved IP address to their respective pools

    """
    for action, address, net_uuid in self._temporary_ips.GetECReserved(ec_id):
      self._UnlockedCommitIp(action, net_uuid, address)

  def _UnlockedCommitIp(self, action, net_uuid, address):
    """Commit a reserved IP address to an IP pool.

    The IP address is taken from the network's IP pool and marked as reserved.

    """
    nobj = self._UnlockedGetNetwork(net_uuid)
    pool = network.AddressPool(nobj)
    if action == constants.RESERVE_ACTION:
      pool.Reserve(address)
    elif action == constants.RELEASE_ACTION:
      pool.Release(address)

  def _UnlockedReleaseIp(self, net_uuid, address, ec_id):
    """Give a specific IP address back to an IP pool.

    The IP address is returned to the IP pool designated by pool_id and marked
    as reserved.

    """
    self._temporary_ips.Reserve(ec_id,
                                (constants.RELEASE_ACTION, address, net_uuid))

  @locking.ssynchronized(_config_lock, shared=1)
  def ReleaseIp(self, net_uuid, address, ec_id):
    """Give a specified IP address back to an IP pool.

    This is just a wrapper around _UnlockedReleaseIp.

    """
    if net_uuid:
      self._UnlockedReleaseIp(net_uuid, address, ec_id)

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateIp(self, net_uuid, ec_id):
    """Find a free IPv4 address for an instance.

    """
    nobj = self._UnlockedGetNetwork(net_uuid)
    pool = network.AddressPool(nobj)

    def gen_one():
      try:
        ip = pool.GenerateFree()
      except errors.AddressPoolError:
        raise errors.ReservationError("Cannot generate IP. Network is full")
      return (constants.RESERVE_ACTION, ip, net_uuid)

    _, address, _ = self._temporary_ips.Generate([], gen_one, ec_id)
    return address

  def _UnlockedReserveIp(self, net_uuid, address, ec_id, check=True):
    """Reserve a given IPv4 address for use by an instance.

    """
    nobj = self._UnlockedGetNetwork(net_uuid)
    pool = network.AddressPool(nobj)
    try:
      isreserved = pool.IsReserved(address)
      isextreserved = pool.IsReserved(address, external=True)
    except errors.AddressPoolError:
      raise errors.ReservationError("IP address not in network")
    if isreserved:
      raise errors.ReservationError("IP address already in use")
    if check and isextreserved:
      raise errors.ReservationError("IP is externally reserved")

    return self._temporary_ips.Reserve(ec_id,
                                       (constants.RESERVE_ACTION,
                                        address, net_uuid))

  @locking.ssynchronized(_config_lock, shared=1)
  def ReserveIp(self, net_uuid, address, ec_id, check=True):
    """Reserve a given IPv4 address for use by an instance.

    """
    if net_uuid:
      return self._UnlockedReserveIp(net_uuid, address, ec_id, check)

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

  def _AllDisks(self):
    """Compute the list of all Disks (recursively, including children).

    """
    def DiskAndAllChildren(disk):
      """Returns a list containing the given disk and all of his children.

      """
      disks = [disk]
      if disk.children:
        for child_disk in disk.children:
          disks.extend(DiskAndAllChildren(child_disk))
      return disks

    disks = []
    for instance in self._config_data.instances.values():
      for disk in instance.disks:
        disks.extend(DiskAndAllChildren(disk))
    return disks

  def _AllNICs(self):
    """Compute the list of all NICs.

    """
    nics = []
    for instance in self._config_data.instances.values():
      nics.extend(instance.nics)
    return nics

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

  def _CheckDiskIDs(self, disk, l_ids):
    """Compute duplicate disk IDs

    @type disk: L{objects.Disk}
    @param disk: the disk at which to start searching
    @type l_ids: list
    @param l_ids: list of current logical ids
    @rtype: list
    @return: a list of error messages

    """
    result = []
    if disk.logical_id is not None:
      if disk.logical_id in l_ids:
        result.append("duplicate logical id %s" % str(disk.logical_id))
      else:
        l_ids.append(disk.logical_id)

    if disk.children:
      for child in disk.children:
        result.extend(self._CheckDiskIDs(child, l_ids))
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

    # global cluster checks
    if not cluster.enabled_hypervisors:
      result.append("enabled hypervisors list doesn't have any entries")
    invalid_hvs = set(cluster.enabled_hypervisors) - constants.HYPER_TYPES
    if invalid_hvs:
      result.append("enabled hypervisors contains invalid entries: %s" %
                    utils.CommaJoin(invalid_hvs))
    missing_hvp = (set(cluster.enabled_hypervisors) -
                   set(cluster.hvparams.keys()))
    if missing_hvp:
      result.append("hypervisor parameters missing for the enabled"
                    " hypervisor(s) %s" % utils.CommaJoin(missing_hvp))

    if not cluster.enabled_disk_templates:
      result.append("enabled disk templates list doesn't have any entries")
    invalid_disk_templates = set(cluster.enabled_disk_templates) \
                               - constants.DISK_TEMPLATES
    if invalid_disk_templates:
      result.append("enabled disk templates list contains invalid entries:"
                    " %s" % utils.CommaJoin(invalid_disk_templates))

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

    def _helper_ipolicy(owner, ipolicy, iscluster):
      try:
        objects.InstancePolicy.CheckParameterSyntax(ipolicy, iscluster)
      except errors.ConfigurationError, err:
        result.append("%s has invalid instance policy: %s" % (owner, err))
      for key, value in ipolicy.items():
        if key == constants.ISPECS_MINMAX:
          for k in range(len(value)):
            _helper_ispecs(owner, "ipolicy/%s[%s]" % (key, k), value[k])
        elif key == constants.ISPECS_STD:
          _helper(owner, "ipolicy/" + key, value,
                  constants.ISPECS_PARAMETER_TYPES)
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

    def _helper_ispecs(owner, parentkey, params):
      for (key, value) in params.items():
        fullkey = "/".join([parentkey, key])
        _helper(owner, fullkey, value, constants.ISPECS_PARAMETER_TYPES)

    # check cluster parameters
    _helper("cluster", "beparams", cluster.SimpleFillBE({}),
            constants.BES_PARAMETER_TYPES)
    _helper("cluster", "nicparams", cluster.SimpleFillNIC({}),
            constants.NICS_PARAMETER_TYPES)
    _helper_nic("cluster", cluster.SimpleFillNIC({}))
    _helper("cluster", "ndparams", cluster.SimpleFillND({}),
            constants.NDS_PARAMETER_TYPES)
    _helper_ipolicy("cluster", cluster.ipolicy, True)

    for disk_template in cluster.diskparams:
      if disk_template not in constants.DTS_HAVE_ACCESS:
        continue

      access = cluster.diskparams[disk_template].get(constants.LDP_ACCESS,
                                                     constants.DISK_KERNELSPACE)
      if access not in constants.DISK_VALID_ACCESS_MODES:
        result.append(
          "Invalid value of '%s:%s': '%s' (expected one of %s)" % (
            disk_template, constants.LDP_ACCESS, access,
            utils.CommaJoin(constants.DISK_VALID_ACCESS_MODES)
          )
        )

    # per-instance checks
    for instance_uuid in data.instances:
      instance = data.instances[instance_uuid]
      if instance.uuid != instance_uuid:
        result.append("instance '%s' is indexed by wrong UUID '%s'" %
                      (instance.name, instance_uuid))
      if instance.primary_node not in data.nodes:
        result.append("instance '%s' has invalid primary node '%s'" %
                      (instance.name, instance.primary_node))
      for snode in instance.secondary_nodes:
        if snode not in data.nodes:
          result.append("instance '%s' has invalid secondary node '%s'" %
                        (instance.name, snode))
      for idx, nic in enumerate(instance.nics):
        if nic.mac in seen_macs:
          result.append("instance '%s' has NIC %d mac %s duplicate" %
                        (instance.name, idx, nic.mac))
        else:
          seen_macs.append(nic.mac)
        if nic.nicparams:
          filled = cluster.SimpleFillNIC(nic.nicparams)
          owner = "instance %s nic %d" % (instance.name, idx)
          _helper(owner, "nicparams",
                  filled, constants.NICS_PARAMETER_TYPES)
          _helper_nic(owner, filled)

      # disk template checks
      if not instance.disk_template in data.cluster.enabled_disk_templates:
        result.append("instance '%s' uses the disabled disk template '%s'." %
                      (instance.name, instance.disk_template))

      # parameter checks
      if instance.beparams:
        _helper("instance %s" % instance.name, "beparams",
                cluster.FillBE(instance), constants.BES_PARAMETER_TYPES)

      # gather the drbd ports for duplicate checks
      for (idx, dsk) in enumerate(instance.disks):
        if dsk.dev_type in constants.DTS_DRBD:
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
        result.extend(self._CheckDiskIDs(disk, seen_lids))

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
    for node_uuid, node in data.nodes.items():
      if node.uuid != node_uuid:
        result.append("Node '%s' is indexed by wrong UUID '%s'" %
                      (node.name, node_uuid))
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
      used_globals = constants.NDC_GLOBALS.intersection(node.ndparams)
      if used_globals:
        result.append("Node '%s' has some global parameters set: %s" %
                      (node.name, utils.CommaJoin(used_globals)))

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

        _AddIpAddress("%s/%s/%s" % (link, nic.ip, nic.network),
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
    @return: dictionary of node_uuid: dict of minor: instance_uuid;
        the returned dict will have all the nodes in it (even if with
        an empty list), and a list of duplicates; if the duplicates
        list is not empty, the configuration is corrupted and its caller
        should raise an exception

    """
    def _AppendUsedMinors(get_node_name_fn, instance, disk, used):
      duplicates = []
      if disk.dev_type == constants.DT_DRBD8 and len(disk.logical_id) >= 5:
        node_a, node_b, _, minor_a, minor_b = disk.logical_id[:5]
        for node_uuid, minor in ((node_a, minor_a), (node_b, minor_b)):
          assert node_uuid in used, \
            ("Node '%s' of instance '%s' not found in node list" %
             (get_node_name_fn(node_uuid), instance.name))
          if minor in used[node_uuid]:
            duplicates.append((node_uuid, minor, instance.uuid,
                               used[node_uuid][minor]))
          else:
            used[node_uuid][minor] = instance.uuid
      if disk.children:
        for child in disk.children:
          duplicates.extend(_AppendUsedMinors(get_node_name_fn, instance, child,
                                              used))
      return duplicates

    duplicates = []
    my_dict = dict((node_uuid, {}) for node_uuid in self._config_data.nodes)
    for instance in self._config_data.instances.itervalues():
      for disk in instance.disks:
        duplicates.extend(_AppendUsedMinors(self._UnlockedGetNodeName,
                                            instance, disk, my_dict))
    for (node_uuid, minor), inst_uuid in self._temporary_drbds.iteritems():
      if minor in my_dict[node_uuid] and my_dict[node_uuid][minor] != inst_uuid:
        duplicates.append((node_uuid, minor, inst_uuid,
                           my_dict[node_uuid][minor]))
      else:
        my_dict[node_uuid][minor] = inst_uuid
    return my_dict, duplicates

  @locking.ssynchronized(_config_lock)
  def ComputeDRBDMap(self):
    """Compute the used DRBD minor/nodes.

    This is just a wrapper over L{_UnlockedComputeDRBDMap}.

    @return: dictionary of node_uuid: dict of minor: instance_uuid;
        the returned dict will have all the nodes in it (even if with
        an empty list).

    """
    d_map, duplicates = self._UnlockedComputeDRBDMap()
    if duplicates:
      raise errors.ConfigurationError("Duplicate DRBD ports detected: %s" %
                                      str(duplicates))
    return d_map

  @locking.ssynchronized(_config_lock)
  def AllocateDRBDMinor(self, node_uuids, inst_uuid):
    """Allocate a drbd minor.

    The free minor will be automatically computed from the existing
    devices. A node can be given multiple times in order to allocate
    multiple minors. The result is the list of minors, in the same
    order as the passed nodes.

    @type inst_uuid: string
    @param inst_uuid: the instance for which we allocate minors

    """
    assert isinstance(inst_uuid, basestring), \
           "Invalid argument '%s' passed to AllocateDRBDMinor" % inst_uuid

    d_map, duplicates = self._UnlockedComputeDRBDMap()
    if duplicates:
      raise errors.ConfigurationError("Duplicate DRBD ports detected: %s" %
                                      str(duplicates))
    result = []
    for nuuid in node_uuids:
      ndata = d_map[nuuid]
      if not ndata:
        # no minors used, we can start at 0
        result.append(0)
        ndata[0] = inst_uuid
        self._temporary_drbds[(nuuid, 0)] = inst_uuid
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
      assert minor not in d_map[nuuid], \
             ("Attempt to reuse allocated DRBD minor %d on node %s,"
              " already allocated to instance %s" %
              (minor, nuuid, d_map[nuuid][minor]))
      ndata[minor] = inst_uuid
      # double-check minor against reservation
      r_key = (nuuid, minor)
      assert r_key not in self._temporary_drbds, \
             ("Attempt to reuse reserved DRBD minor %d on node %s,"
              " reserved for instance %s" %
              (minor, nuuid, self._temporary_drbds[r_key]))
      self._temporary_drbds[r_key] = inst_uuid
      result.append(minor)
    logging.debug("Request to allocate drbd minors, input: %s, returning %s",
                  node_uuids, result)
    return result

  def _UnlockedReleaseDRBDMinors(self, inst_uuid):
    """Release temporary drbd minors allocated for a given instance.

    @type inst_uuid: string
    @param inst_uuid: the instance for which temporary minors should be
                      released

    """
    assert isinstance(inst_uuid, basestring), \
           "Invalid argument passed to ReleaseDRBDMinors"
    for key, uuid in self._temporary_drbds.items():
      if uuid == inst_uuid:
        del self._temporary_drbds[key]

  @locking.ssynchronized(_config_lock)
  def ReleaseDRBDMinors(self, inst_uuid):
    """Release temporary drbd minors allocated for a given instance.

    This should be called on the error paths, on the success paths
    it's automatically called by the ConfigWriter add and update
    functions.

    This function is just a wrapper over L{_UnlockedReleaseDRBDMinors}.

    @type inst_uuid: string
    @param inst_uuid: the instance for which temporary minors should be
                      released

    """
    self._UnlockedReleaseDRBDMinors(inst_uuid)

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
    """Get the UUID of the master node for this cluster.

    @return: Master node UUID

    """
    return self._config_data.cluster.master_node

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterNodeName(self):
    """Get the hostname of the master node for this cluster.

    @return: Master node hostname

    """
    return self._UnlockedGetNodeName(self._config_data.cluster.master_node)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMasterNodeInfo(self):
    """Get the master node information for this cluster.

    @rtype: objects.Node
    @return: Master node L{objects.Node} object

    """
    return self._UnlockedGetNodeInfo(self._config_data.cluster.master_node)

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
  def GetGlusterStorageDir(self):
    """Get the Gluster storage dir for this cluster.

    """
    return self._config_data.cluster.gluster_storage_dir

  @locking.ssynchronized(_config_lock, shared=1)
  def GetHypervisorType(self):
    """Get the hypervisor type for this cluster.

    """
    return self._config_data.cluster.enabled_hypervisors[0]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetRsaHostKey(self):
    """Return the rsa hostkey from the config.

    @rtype: string
    @return: the rsa hostkey

    """
    return self._config_data.cluster.rsahostkeypub

  @locking.ssynchronized(_config_lock, shared=1)
  def GetDsaHostKey(self):
    """Return the dsa hostkey from the config.

    @rtype: string
    @return: the dsa hostkey

    """
    return self._config_data.cluster.dsahostkeypub

  @locking.ssynchronized(_config_lock, shared=1)
  def GetDefaultIAllocator(self):
    """Get the default instance allocator for this cluster.

    """
    return self._config_data.cluster.default_iallocator

  @locking.ssynchronized(_config_lock, shared=1)
  def GetDefaultIAllocatorParameters(self):
    """Get the default instance allocator parameters for this cluster.

    @rtype: dict
    @return: dict of iallocator parameters

    """
    return self._config_data.cluster.default_iallocator_params

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
      uuid=cluster.master_node, ip=cluster.master_ip,
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

  def _UnlockedGetAllNodeGroupsInfo(self):
    """Get the configuration of all node groups.

    """
    return dict(self._config_data.nodegroups)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNodeGroupsInfo(self):
    """Get the configuration of all node groups.

    """
    return self._UnlockedGetAllNodeGroupsInfo()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNodeGroupsInfoDict(self):
    """Get the configuration of all node groups expressed as a dictionary of
    dictionaries.

    """
    return dict(map(lambda (uuid, ng): (uuid, ng.ToDict()),
                    self._UnlockedGetAllNodeGroupsInfo().items()))

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupList(self):
    """Get a list of node groups.

    """
    return self._config_data.nodegroups.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupMembersByNodes(self, nodes):
    """Get nodes which are member in the same nodegroups as the given nodes.

    """
    ngfn = lambda node_uuid: self._UnlockedGetNodeInfo(node_uuid).group
    return frozenset(member_uuid
                     for node_uuid in nodes
                     for member_uuid in
                       self._UnlockedGetNodeGroup(ngfn(node_uuid)).members)

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

    self._CheckUniqueUUID(instance, include_temporary=False)

    instance.serial_no = 1
    instance.ctime = instance.mtime = time.time()
    self._config_data.instances[instance.uuid] = instance
    self._config_data.cluster.serial_no += 1
    self._UnlockedReleaseDRBDMinors(instance.uuid)
    self._UnlockedCommitTemporaryIps(ec_id)
    self._WriteConfig()

  def _EnsureUUID(self, item, ec_id):
    """Ensures a given object has a valid UUID.

    @param item: the instance or node to be checked
    @param ec_id: the execution context id for the uuid reservation

    """
    if not item.uuid:
      item.uuid = self._GenerateUniqueID(ec_id)
    else:
      self._CheckUniqueUUID(item, include_temporary=True)

  def _CheckUniqueUUID(self, item, include_temporary):
    """Checks that the UUID of the given object is unique.

    @param item: the instance or node to be checked
    @param include_temporary: whether temporarily generated UUID's should be
              included in the check. If the UUID of the item to be checked is
              a temporarily generated one, this has to be C{False}.

    """
    if not item.uuid:
      raise errors.ConfigurationError("'%s' must have an UUID" % (item.name,))
    if item.uuid in self._AllIDs(include_temporary=include_temporary):
      raise errors.ConfigurationError("Cannot add '%s': UUID %s already"
                                      " in use" % (item.name, item.uuid))

  def _SetInstanceStatus(self, inst_uuid, status, disks_active):
    """Set the instance's status to a given value.

    """
    if inst_uuid not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" %
                                      inst_uuid)
    instance = self._config_data.instances[inst_uuid]

    if status is None:
      status = instance.admin_state
    if disks_active is None:
      disks_active = instance.disks_active

    assert status in constants.ADMINST_ALL, \
           "Invalid status '%s' passed to SetInstanceStatus" % (status,)

    if instance.admin_state != status or \
       instance.disks_active != disks_active:
      instance.admin_state = status
      instance.disks_active = disks_active
      instance.serial_no += 1
      instance.mtime = time.time()
      self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def MarkInstanceUp(self, inst_uuid):
    """Mark the instance status to up in the config.

    This also sets the instance disks active flag.

    """
    self._SetInstanceStatus(inst_uuid, constants.ADMINST_UP, True)

  @locking.ssynchronized(_config_lock)
  def MarkInstanceOffline(self, inst_uuid):
    """Mark the instance status to down in the config.

    This also clears the instance disks active flag.

    """
    self._SetInstanceStatus(inst_uuid, constants.ADMINST_OFFLINE, False)

  @locking.ssynchronized(_config_lock)
  def RemoveInstance(self, inst_uuid):
    """Remove the instance from the configuration.

    """
    if inst_uuid not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" % inst_uuid)

    # If a network port has been allocated to the instance,
    # return it to the pool of free ports.
    inst = self._config_data.instances[inst_uuid]
    network_port = getattr(inst, "network_port", None)
    if network_port is not None:
      self._config_data.cluster.tcpudp_port_pool.add(network_port)

    instance = self._UnlockedGetInstanceInfo(inst_uuid)

    for nic in instance.nics:
      if nic.network and nic.ip:
        # Return all IP addresses to the respective address pools
        self._UnlockedCommitIp(constants.RELEASE_ACTION, nic.network, nic.ip)

    del self._config_data.instances[inst_uuid]
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def RenameInstance(self, inst_uuid, new_name):
    """Rename an instance.

    This needs to be done in ConfigWriter and not by RemoveInstance
    combined with AddInstance as only we can guarantee an atomic
    rename.

    """
    if inst_uuid not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" % inst_uuid)

    inst = self._config_data.instances[inst_uuid]
    inst.name = new_name

    for (idx, disk) in enumerate(inst.disks):
      if disk.dev_type in [constants.DT_FILE, constants.DT_SHARED_FILE]:
        # rename the file paths in logical and physical id
        file_storage_dir = os.path.dirname(os.path.dirname(disk.logical_id[1]))
        disk.logical_id = (disk.logical_id[0],
                           utils.PathJoin(file_storage_dir, inst.name,
                                          "disk%s" % idx))

    # Force update of ssconf files
    self._config_data.cluster.serial_no += 1

    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def MarkInstanceDown(self, inst_uuid):
    """Mark the status of an instance to down in the configuration.

    This does not touch the instance disks active flag, as shut down instances
    can still have active disks.

    """
    self._SetInstanceStatus(inst_uuid, constants.ADMINST_DOWN, None)

  @locking.ssynchronized(_config_lock)
  def MarkInstanceDisksActive(self, inst_uuid):
    """Mark the status of instance disks active.

    """
    self._SetInstanceStatus(inst_uuid, None, True)

  @locking.ssynchronized(_config_lock)
  def MarkInstanceDisksInactive(self, inst_uuid):
    """Mark the status of instance disks inactive.

    """
    self._SetInstanceStatus(inst_uuid, None, False)

  def _UnlockedGetInstanceList(self):
    """Get the list of instances.

    This function is for internal use, when the config lock is already held.

    """
    return self._config_data.instances.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceList(self):
    """Get the list of instances.

    @return: array of instances, ex. ['instance2-uuid', 'instance1-uuid']

    """
    return self._UnlockedGetInstanceList()

  def ExpandInstanceName(self, short_name):
    """Attempt to expand an incomplete instance name.

    """
    # Locking is done in L{ConfigWriter.GetAllInstancesInfo}
    all_insts = self.GetAllInstancesInfo().values()
    expanded_name = _MatchNameComponentIgnoreCase(
                      short_name, [inst.name for inst in all_insts])

    if expanded_name is not None:
      # there has to be exactly one instance with that name
      inst = (filter(lambda n: n.name == expanded_name, all_insts)[0])
      return (inst.uuid, inst.name)
    else:
      return (None, None)

  def _UnlockedGetInstanceInfo(self, inst_uuid):
    """Returns information about an instance.

    This function is for internal use, when the config lock is already held.

    """
    if inst_uuid not in self._config_data.instances:
      return None

    return self._config_data.instances[inst_uuid]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceInfo(self, inst_uuid):
    """Returns information about an instance.

    It takes the information from the configuration file. Other information of
    an instance are taken from the live systems.

    @param inst_uuid: UUID of the instance

    @rtype: L{objects.Instance}
    @return: the instance object

    """
    return self._UnlockedGetInstanceInfo(inst_uuid)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceNodeGroups(self, inst_uuid, primary_only=False):
    """Returns set of node group UUIDs for instance's nodes.

    @rtype: frozenset

    """
    instance = self._UnlockedGetInstanceInfo(inst_uuid)
    if not instance:
      raise errors.ConfigurationError("Unknown instance '%s'" % inst_uuid)

    if primary_only:
      nodes = [instance.primary_node]
    else:
      nodes = instance.all_nodes

    return frozenset(self._UnlockedGetNodeInfo(node_uuid).group
                     for node_uuid in nodes)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceNetworks(self, inst_uuid):
    """Returns set of network UUIDs for instance's nics.

    @rtype: frozenset

    """
    instance = self._UnlockedGetInstanceInfo(inst_uuid)
    if not instance:
      raise errors.ConfigurationError("Unknown instance '%s'" % inst_uuid)

    networks = set()
    for nic in instance.nics:
      if nic.network:
        networks.add(nic.network)

    return frozenset(networks)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMultiInstanceInfo(self, inst_uuids):
    """Get the configuration of multiple instances.

    @param inst_uuids: list of instance UUIDs
    @rtype: list
    @return: list of tuples (instance UUID, instance_info), where
        instance_info is what would GetInstanceInfo return for the
        node, while keeping the original order

    """
    return [(uuid, self._UnlockedGetInstanceInfo(uuid)) for uuid in inst_uuids]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMultiInstanceInfoByName(self, inst_names):
    """Get the configuration of multiple instances.

    @param inst_names: list of instance names
    @rtype: list
    @return: list of tuples (instance, instance_info), where
        instance_info is what would GetInstanceInfo return for the
        node, while keeping the original order

    """
    result = []
    for name in inst_names:
      instance = self._UnlockedGetInstanceInfoByName(name)
      result.append((instance.uuid, instance))
    return result

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllInstancesInfo(self):
    """Get the configuration of all instances.

    @rtype: dict
    @return: dict of (instance, instance_info), where instance_info is what
              would GetInstanceInfo return for the node

    """
    return self._UnlockedGetAllInstancesInfo()

  def _UnlockedGetAllInstancesInfo(self):
    my_dict = dict([(inst_uuid, self._UnlockedGetInstanceInfo(inst_uuid))
                    for inst_uuid in self._UnlockedGetInstanceList()])
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
    return dict((uuid, inst)
                for (uuid, inst) in self._config_data.instances.items()
                if filter_fn(inst))

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceInfoByName(self, inst_name):
    """Get the L{objects.Instance} object for a named instance.

    @param inst_name: name of the instance to get information for
    @type inst_name: string
    @return: the corresponding L{objects.Instance} instance or None if no
          information is available

    """
    return self._UnlockedGetInstanceInfoByName(inst_name)

  def _UnlockedGetInstanceInfoByName(self, inst_name):
    for inst in self._UnlockedGetAllInstancesInfo().values():
      if inst.name == inst_name:
        return inst
    return None

  def _UnlockedGetInstanceName(self, inst_uuid):
    inst_info = self._UnlockedGetInstanceInfo(inst_uuid)
    if inst_info is None:
      raise errors.OpExecError("Unknown instance: %s" % inst_uuid)
    return inst_info.name

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceName(self, inst_uuid):
    """Gets the instance name for the passed instance.

    @param inst_uuid: instance UUID to get name for
    @type inst_uuid: string
    @rtype: string
    @return: instance name

    """
    return self._UnlockedGetInstanceName(inst_uuid)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceNames(self, inst_uuids):
    """Gets the instance names for the passed list of nodes.

    @param inst_uuids: list of instance UUIDs to get names for
    @type inst_uuids: list of strings
    @rtype: list of strings
    @return: list of instance names

    """
    return self._UnlockedGetInstanceNames(inst_uuids)

  def _UnlockedGetInstanceNames(self, inst_uuids):
    return [self._UnlockedGetInstanceName(uuid) for uuid in inst_uuids]

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
    self._UnlockedAddNodeToGroup(node.uuid, node.group)
    self._config_data.nodes[node.uuid] = node
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def RemoveNode(self, node_uuid):
    """Remove a node from the configuration.

    """
    logging.info("Removing node %s from configuration", node_uuid)

    if node_uuid not in self._config_data.nodes:
      raise errors.ConfigurationError("Unknown node '%s'" % node_uuid)

    self._UnlockedRemoveNodeFromGroup(self._config_data.nodes[node_uuid])
    del self._config_data.nodes[node_uuid]
    self._config_data.cluster.serial_no += 1
    self._WriteConfig()

  def ExpandNodeName(self, short_name):
    """Attempt to expand an incomplete node name into a node UUID.

    """
    # Locking is done in L{ConfigWriter.GetAllNodesInfo}
    all_nodes = self.GetAllNodesInfo().values()
    expanded_name = _MatchNameComponentIgnoreCase(
                      short_name, [node.name for node in all_nodes])

    if expanded_name is not None:
      # there has to be exactly one node with that name
      node = (filter(lambda n: n.name == expanded_name, all_nodes)[0])
      return (node.uuid, node.name)
    else:
      return (None, None)

  def _UnlockedGetNodeInfo(self, node_uuid):
    """Get the configuration of a node, as stored in the config.

    This function is for internal use, when the config lock is already
    held.

    @param node_uuid: the node UUID

    @rtype: L{objects.Node}
    @return: the node object

    """
    if node_uuid not in self._config_data.nodes:
      return None

    return self._config_data.nodes[node_uuid]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeInfo(self, node_uuid):
    """Get the configuration of a node, as stored in the config.

    This is just a locked wrapper over L{_UnlockedGetNodeInfo}.

    @param node_uuid: the node UUID

    @rtype: L{objects.Node}
    @return: the node object

    """
    return self._UnlockedGetNodeInfo(node_uuid)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeInstances(self, node_uuid):
    """Get the instances of a node, as stored in the config.

    @param node_uuid: the node UUID

    @rtype: (list, list)
    @return: a tuple with two lists: the primary and the secondary instances

    """
    pri = []
    sec = []
    for inst in self._config_data.instances.values():
      if inst.primary_node == node_uuid:
        pri.append(inst.uuid)
      if node_uuid in inst.secondary_nodes:
        sec.append(inst.uuid)
    return (pri, sec)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupInstances(self, uuid, primary_only=False):
    """Get the instances of a node group.

    @param uuid: Node group UUID
    @param primary_only: Whether to only consider primary nodes
    @rtype: frozenset
    @return: List of instance UUIDs in node group

    """
    if primary_only:
      nodes_fn = lambda inst: [inst.primary_node]
    else:
      nodes_fn = lambda inst: inst.all_nodes

    return frozenset(inst.uuid
                     for inst in self._config_data.instances.values()
                     for node_uuid in nodes_fn(inst)
                     if self._UnlockedGetNodeInfo(node_uuid).group == uuid)

  def _UnlockedGetHvparamsString(self, hvname):
    """Return the string representation of the list of hyervisor parameters of
    the given hypervisor.

    @see: C{GetHvparams}

    """
    result = ""
    hvparams = self._config_data.cluster.hvparams[hvname]
    for key in hvparams:
      result += "%s=%s\n" % (key, hvparams[key])
    return result

  @locking.ssynchronized(_config_lock, shared=1)
  def GetHvparamsString(self, hvname):
    """Return the hypervisor parameters of the given hypervisor.

    @type hvname: string
    @param hvname: name of a hypervisor
    @rtype: string
    @return: string containing key-value-pairs, one pair on each line;
      format: KEY=VALUE

    """
    return self._UnlockedGetHvparamsString(hvname)

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
    return [node.uuid for node in all_nodes if not node.offline]

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
    return [node.uuid for node in all_nodes if node.vm_capable]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNonVmCapableNodeList(self):
    """Return the list of nodes which are not vm capable.

    """
    all_nodes = [self._UnlockedGetNodeInfo(node)
                 for node in self._UnlockedGetNodeList()]
    return [node.uuid for node in all_nodes if not node.vm_capable]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMultiNodeInfo(self, node_uuids):
    """Get the configuration of multiple nodes.

    @param node_uuids: list of node UUIDs
    @rtype: list
    @return: list of tuples of (node, node_info), where node_info is
        what would GetNodeInfo return for the node, in the original
        order

    """
    return [(uuid, self._UnlockedGetNodeInfo(uuid)) for uuid in node_uuids]

  def _UnlockedGetAllNodesInfo(self):
    """Gets configuration of all nodes.

    @note: See L{GetAllNodesInfo}

    """
    return dict([(node_uuid, self._UnlockedGetNodeInfo(node_uuid))
                 for node_uuid in self._UnlockedGetNodeList()])

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNodesInfo(self):
    """Get the configuration of all nodes.

    @rtype: dict
    @return: dict of (node, node_info), where node_info is what
              would GetNodeInfo return for the node

    """
    return self._UnlockedGetAllNodesInfo()

  def _UnlockedGetNodeInfoByName(self, node_name):
    for node in self._UnlockedGetAllNodesInfo().values():
      if node.name == node_name:
        return node
    return None

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeInfoByName(self, node_name):
    """Get the L{objects.Node} object for a named node.

    @param node_name: name of the node to get information for
    @type node_name: string
    @return: the corresponding L{objects.Node} instance or None if no
          information is available

    """
    return self._UnlockedGetNodeInfoByName(node_name)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupInfoByName(self, nodegroup_name):
    """Get the L{objects.NodeGroup} object for a named node group.

    @param nodegroup_name: name of the node group to get information for
    @type nodegroup_name: string
    @return: the corresponding L{objects.NodeGroup} instance or None if no
          information is available

    """
    for nodegroup in self._UnlockedGetAllNodeGroupsInfo().values():
      if nodegroup.name == nodegroup_name:
        return nodegroup
    return None

  def _UnlockedGetNodeName(self, node_spec):
    if isinstance(node_spec, objects.Node):
      return node_spec.name
    elif isinstance(node_spec, basestring):
      node_info = self._UnlockedGetNodeInfo(node_spec)
      if node_info is None:
        raise errors.OpExecError("Unknown node: %s" % node_spec)
      return node_info.name
    else:
      raise errors.ProgrammerError("Can't handle node spec '%s'" % node_spec)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeName(self, node_spec):
    """Gets the node name for the passed node.

    @param node_spec: node to get names for
    @type node_spec: either node UUID or a L{objects.Node} object
    @rtype: string
    @return: node name

    """
    return self._UnlockedGetNodeName(node_spec)

  def _UnlockedGetNodeNames(self, node_specs):
    return [self._UnlockedGetNodeName(node_spec) for node_spec in node_specs]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeNames(self, node_specs):
    """Gets the node names for the passed list of nodes.

    @param node_specs: list of nodes to get names for
    @type node_specs: list of either node UUIDs or L{objects.Node} objects
    @rtype: list of strings
    @return: list of node names

    """
    return self._UnlockedGetNodeNames(node_specs)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeGroupsFromNodes(self, node_uuids):
    """Returns groups for a list of nodes.

    @type node_uuids: list of string
    @param node_uuids: List of node UUIDs
    @rtype: frozenset

    """
    return frozenset(self._UnlockedGetNodeInfo(uuid).group
                     for uuid in node_uuids)

  def _UnlockedGetMasterCandidateStats(self, exceptions=None):
    """Get the number of current and maximum desired and possible candidates.

    @type exceptions: list
    @param exceptions: if passed, list of nodes that should be ignored
    @rtype: tuple
    @return: tuple of (current, desired and possible, possible)

    """
    mc_now = mc_should = mc_max = 0
    for node in self._config_data.nodes.values():
      if exceptions and node.uuid in exceptions:
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
  def MaintainCandidatePool(self, exception_node_uuids):
    """Try to grow the candidate pool to the desired size.

    @type exception_node_uuids: list
    @param exception_node_uuids: if passed, list of nodes that should be ignored
    @rtype: list
    @return: list with the adjusted nodes (L{objects.Node} instances)

    """
    mc_now, mc_max, _ = self._UnlockedGetMasterCandidateStats(
                          exception_node_uuids)
    mod_list = []
    if mc_now < mc_max:
      node_list = self._config_data.nodes.keys()
      random.shuffle(node_list)
      for uuid in node_list:
        if mc_now >= mc_max:
          break
        node = self._config_data.nodes[uuid]
        if (node.master_candidate or node.offline or node.drained or
            node.uuid in exception_node_uuids or not node.master_capable):
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

  def _UnlockedAddNodeToGroup(self, node_uuid, nodegroup_uuid):
    """Add a given node to the specified group.

    """
    if nodegroup_uuid not in self._config_data.nodegroups:
      # This can happen if a node group gets deleted between its lookup and
      # when we're adding the first node to it, since we don't keep a lock in
      # the meantime. It's ok though, as we'll fail cleanly if the node group
      # is not found anymore.
      raise errors.OpExecError("Unknown node group: %s" % nodegroup_uuid)
    if node_uuid not in self._config_data.nodegroups[nodegroup_uuid].members:
      self._config_data.nodegroups[nodegroup_uuid].members.append(node_uuid)

  def _UnlockedRemoveNodeFromGroup(self, node):
    """Remove a given node from its group.

    """
    nodegroup = node.group
    if nodegroup not in self._config_data.nodegroups:
      logging.warning("Warning: node '%s' has unknown node group '%s'"
                      " (while being removed from it)", node.uuid, nodegroup)
    nodegroup_obj = self._config_data.nodegroups[nodegroup]
    if node.uuid not in nodegroup_obj.members:
      logging.warning("Warning: node '%s' not a member of its node group '%s'"
                      " (while being removed from it)", node.uuid, nodegroup)
    else:
      nodegroup_obj.members.remove(node.uuid)

  @locking.ssynchronized(_config_lock)
  def AssignGroupNodes(self, mods):
    """Changes the group of a number of nodes.

    @type mods: list of tuples; (node name, new group UUID)
    @param mods: Node membership modifications

    """
    groups = self._config_data.nodegroups
    nodes = self._config_data.nodes

    resmod = []

    # Try to resolve UUIDs first
    for (node_uuid, new_group_uuid) in mods:
      try:
        node = nodes[node_uuid]
      except KeyError:
        raise errors.ConfigurationError("Unable to find node '%s'" % node_uuid)

      if node.group == new_group_uuid:
        # Node is being assigned to its current group
        logging.debug("Node '%s' was assigned to its current group (%s)",
                      node_uuid, node.group)
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

      assert node.uuid in old_group.members, \
        ("Inconsistent configuration: node '%s' not listed in members for its"
         " old group '%s'" % (node.uuid, old_group.uuid))
      assert node.uuid not in new_group.members, \
        ("Inconsistent configuration: node '%s' already listed in members for"
         " its new group '%s'" % (node.uuid, new_group.uuid))

      resmod.append((node, old_group, new_group))

    # Apply changes
    for (node, old_group, new_group) in resmod:
      assert node.uuid != new_group.uuid and old_group.uuid != new_group.uuid, \
        "Assigning to current group is not possible"

      node.group = new_group.uuid

      # Update members of involved groups
      if node.uuid in old_group.members:
        old_group.members.remove(node.uuid)
      if node.uuid not in new_group.members:
        new_group.members.append(node.uuid)

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
            self._config_data.networks.values() +
            self._AllDisks() +
            self._AllNICs() +
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

    if not data.cluster.master_node in data.nodes:
      msg = ("The configuration denotes node %s as master, but does not"
             " contain information about this node" %
             data.cluster.master_node)
      raise errors.ConfigurationError(msg)

    master_info = data.nodes[data.cluster.master_node]
    if master_info.name != self._my_hostname and not accept_foreign:
      msg = ("The configuration denotes node %s as master, while my"
             " hostname is %s; opening a foreign configuration is only"
             " possible in accept_foreign mode" %
             (master_info.name, self._my_hostname))
      raise errors.ConfigurationError(msg)

    self._config_data = data
    # reset the last serial as -1 so that the next write will cause
    # ssconf update
    self._last_cluster_serial = -1

    # Upgrade configuration if needed
    self._UpgradeConfig()

    self._cfg_id = utils.GetFileID(path=self._cfg_file)

  def _UpgradeConfig(self):
    """Run any upgrade steps.

    This method performs both in-object upgrades and also update some data
    elements that need uniqueness across the whole configuration or interact
    with other objects.

    @warning: this function will call L{_WriteConfig()}, but also
        L{DropECReservations} so it needs to be called only from a
        "safe" place (the constructor). If one wanted to call it with
        the lock held, a DropECReservationUnlocked would need to be
        created first, to avoid causing deadlock.

    """
    # Keep a copy of the persistent part of _config_data to check for changes
    # Serialization doesn't guarantee order in dictionaries
    oldconf = copy.deepcopy(self._config_data.ToDict())

    # In-object upgrades
    self._config_data.UpgradeConfig()

    for item in self._AllUUIDObjects():
      if item.uuid is None:
        item.uuid = self._GenerateUniqueID(_UPGRADE_CONFIG_JID)
    if not self._config_data.nodegroups:
      default_nodegroup_name = constants.INITIAL_NODE_GROUP_NAME
      default_nodegroup = objects.NodeGroup(name=default_nodegroup_name,
                                            members=[])
      self._UnlockedAddNodeGroup(default_nodegroup, _UPGRADE_CONFIG_JID, True)
    for node in self._config_data.nodes.values():
      if not node.group:
        node.group = self.LookupNodeGroup(None)
      # This is technically *not* an upgrade, but needs to be done both when
      # nodegroups are being added, and upon normally loading the config,
      # because the members list of a node group is discarded upon
      # serializing/deserializing the object.
      self._UnlockedAddNodeToGroup(node.uuid, node.group)

    modified = (oldconf != self._config_data.ToDict())
    if modified:
      self._WriteConfig()
      # This is ok even if it acquires the internal lock, as _UpgradeConfig is
      # only called at config init time, without the lock held
      self.DropECReservations(_UPGRADE_CONFIG_JID)
    else:
      config_errors = self._UnlockedVerifyConfig()
      if config_errors:
        errmsg = ("Loaded configuration data is not consistent: %s" %
                  (utils.CommaJoin(config_errors)))
        logging.critical(errmsg)

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
    for node_uuid in self._UnlockedGetNodeList():
      node_info = self._UnlockedGetNodeInfo(node_uuid)
      if node_info.name == myhostname or not node_info.master_candidate:
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
    txt = serializer.DumpJson(
      self._config_data.ToDict(_with_private=True),
      private_encoder=serializer.EncodeWithPrivateFields
    )

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
          self._UnlockedGetNodeNames(self._UnlockedGetOnlineNodeList()),
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

  def _GetAllHvparamsStrings(self, hypervisors):
    """Get the hvparams of all given hypervisors from the config.

    @type hypervisors: list of string
    @param hypervisors: list of hypervisor names
    @rtype: dict of strings
    @returns: dictionary mapping the hypervisor name to a string representation
      of the hypervisor's hvparams

    """
    hvparams = {}
    for hv in hypervisors:
      hvparams[hv] = self._UnlockedGetHvparamsString(hv)
    return hvparams

  @staticmethod
  def _ExtendByAllHvparamsStrings(ssconf_values, all_hvparams):
    """Extends the ssconf_values dictionary by hvparams.

    @type ssconf_values: dict of strings
    @param ssconf_values: dictionary mapping ssconf_keys to strings
      representing the content of ssconf files
    @type all_hvparams: dict of strings
    @param all_hvparams: dictionary mapping hypervisor names to a string
      representation of their hvparams
    @rtype: same as ssconf_values
    @returns: the ssconf_values dictionary extended by hvparams

    """
    for hv in all_hvparams:
      ssconf_key = constants.SS_HVPARAMS_PREF + hv
      ssconf_values[ssconf_key] = all_hvparams[hv]
    return ssconf_values

  def _UnlockedGetSsconfValues(self):
    """Return the values needed by ssconf.

    @rtype: dict
    @return: a dictionary with keys the ssconf names and values their
        associated value

    """
    fn = "\n".join
    instance_names = utils.NiceSort(
                       [inst.name for inst in
                        self._UnlockedGetAllInstancesInfo().values()])
    node_infos = self._UnlockedGetAllNodesInfo().values()
    node_names = [node.name for node in node_infos]
    node_pri_ips = ["%s %s" % (ninfo.name, ninfo.primary_ip)
                    for ninfo in node_infos]
    node_snd_ips = ["%s %s" % (ninfo.name, ninfo.secondary_ip)
                    for ninfo in node_infos]

    instance_data = fn(instance_names)
    off_data = fn(node.name for node in node_infos if node.offline)
    on_data = fn(node.name for node in node_infos if not node.offline)
    mc_data = fn(node.name for node in node_infos if node.master_candidate)
    mc_ips_data = fn(node.primary_ip for node in node_infos
                     if node.master_candidate)
    node_data = fn(node_names)
    node_pri_ips_data = fn(node_pri_ips)
    node_snd_ips_data = fn(node_snd_ips)

    cluster = self._config_data.cluster
    cluster_tags = fn(cluster.GetTags())

    master_candidates_certs = fn("%s=%s" % (mc_uuid, mc_cert)
                                 for mc_uuid, mc_cert
                                 in cluster.candidate_certs.items())

    hypervisor_list = fn(cluster.enabled_hypervisors)
    all_hvparams = self._GetAllHvparamsStrings(constants.HYPER_TYPES)

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
      constants.SS_GLUSTER_STORAGE_DIR: cluster.gluster_storage_dir,
      constants.SS_MASTER_CANDIDATES: mc_data,
      constants.SS_MASTER_CANDIDATES_IPS: mc_ips_data,
      constants.SS_MASTER_CANDIDATES_CERTS: master_candidates_certs,
      constants.SS_MASTER_IP: cluster.master_ip,
      constants.SS_MASTER_NETDEV: cluster.master_netdev,
      constants.SS_MASTER_NETMASK: str(cluster.master_netmask),
      constants.SS_MASTER_NODE: self._UnlockedGetNodeName(cluster.master_node),
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
    ssconf_values = self._ExtendByAllHvparamsStrings(ssconf_values,
                                                     all_hvparams)
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
  def Update(self, target, feedback_fn, ec_id=None):
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
      self._UnlockedReleaseDRBDMinors(target.uuid)

    if ec_id is not None:
      # Commit all ips reserved by OpInstanceSetParams and OpGroupSetParams
      self._UnlockedCommitTemporaryIps(ec_id)

    self._WriteConfig(feedback_fn=feedback_fn)

  @locking.ssynchronized(_config_lock)
  def DropECReservations(self, ec_id):
    """Drop per-execution-context reservations

    """
    for rm in self._all_rms:
      rm.DropECReservations(ec_id)

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNetworksInfo(self):
    """Get configuration info of all the networks.

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
    names = [net.name
             for net in self._config_data.networks.values()]
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

    net.serial_no = 1
    net.ctime = net.mtime = time.time()
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
    if target is None:
      return None
    if target in self._config_data.networks:
      return target
    for net in self._config_data.networks.values():
      if net.name == target:
        return net.uuid
    raise errors.OpPrereqError("Network '%s' not found" % target,
                               errors.ECODE_NOENT)

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

  def _UnlockedGetGroupNetParams(self, net_uuid, node_uuid):
    """Get the netparams (mode, link) of a network.

    Get a network's netparams for a given node.

    @type net_uuid: string
    @param net_uuid: network uuid
    @type node_uuid: string
    @param node_uuid: node UUID
    @rtype: dict or None
    @return: netparams

    """
    node_info = self._UnlockedGetNodeInfo(node_uuid)
    nodegroup_info = self._UnlockedGetNodeGroup(node_info.group)
    netparams = nodegroup_info.networks.get(net_uuid, None)

    return netparams

  @locking.ssynchronized(_config_lock, shared=1)
  def GetGroupNetParams(self, net_uuid, node_uuid):
    """Locking wrapper of _UnlockedGetGroupNetParams()

    """
    return self._UnlockedGetGroupNetParams(net_uuid, node_uuid)

  @locking.ssynchronized(_config_lock, shared=1)
  def CheckIPInNodeGroup(self, ip, node_uuid):
    """Check IP uniqueness in nodegroup.

    Check networks that are connected in the node's node group
    if ip is contained in any of them. Used when creating/adding
    a NIC to ensure uniqueness among nodegroups.

    @type ip: string
    @param ip: ip address
    @type node_uuid: string
    @param node_uuid: node UUID
    @rtype: (string, dict) or (None, None)
    @return: (network name, netparams)

    """
    if ip is None:
      return (None, None)
    node_info = self._UnlockedGetNodeInfo(node_uuid)
    nodegroup_info = self._UnlockedGetNodeGroup(node_info.group)
    for net_uuid in nodegroup_info.networks.keys():
      net_info = self._UnlockedGetNetwork(net_uuid)
      pool = network.AddressPool(net_info)
      if pool.Contains(ip):
        return (net_info.name, nodegroup_info.networks[net_uuid])

    return (None, None)
