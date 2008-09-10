#
#

# Copyright (C) 2006, 2007 Google Inc.
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

import os
import tempfile
import random
import logging

from ganeti import errors
from ganeti import locking
from ganeti import logger
from ganeti import utils
from ganeti import constants
from ganeti import rpc
from ganeti import objects
from ganeti import serializer
from ganeti import ssconf


_config_lock = locking.SharedLock()


def ValidateConfig():
  sstore = ssconf.SimpleStore()

  if sstore.GetConfigVersion() != constants.CONFIG_VERSION:
    raise errors.ConfigurationError("Cluster configuration version"
                                    " mismatch, got %s instead of %s" %
                                    (sstore.GetConfigVersion(),
                                     constants.CONFIG_VERSION))


class ConfigWriter:
  """The interface to the cluster configuration.

  """
  def __init__(self, cfg_file=None, offline=False):
    self.write_count = 0
    self._lock = _config_lock
    self._config_data = None
    self._config_time = None
    self._config_size = None
    self._config_inode = None
    self._offline = offline
    if cfg_file is None:
      self._cfg_file = constants.CLUSTER_CONF_FILE
    else:
      self._cfg_file = cfg_file
    self._temporary_ids = set()
    # Note: in order to prevent errors when resolving our name in
    # _DistributeConfig, we compute it here once and reuse it; it's
    # better to raise an error before starting to modify the config
    # file than after it was modified
    self._my_hostname = utils.HostInfo().name

  # this method needs to be static, so that we can call it on the class
  @staticmethod
  def IsCluster():
    """Check if the cluster is configured.

    """
    return os.path.exists(constants.CLUSTER_CONF_FILE)

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateMAC(self):
    """Generate a MAC for an instance.

    This should check the current instances for duplicates.

    """
    self._OpenConfig()
    prefix = self._config_data.cluster.mac_prefix
    all_macs = self._AllMACs()
    retries = 64
    while retries > 0:
      byte1 = random.randrange(0, 256)
      byte2 = random.randrange(0, 256)
      byte3 = random.randrange(0, 256)
      mac = "%s:%02x:%02x:%02x" % (prefix, byte1, byte2, byte3)
      if mac not in all_macs:
        break
      retries -= 1
    else:
      raise errors.ConfigurationError("Can't generate unique MAC")
    return mac

  @locking.ssynchronized(_config_lock, shared=1)
  def IsMacInUse(self, mac):
    """Predicate: check if the specified MAC is in use in the Ganeti cluster.

    This only checks instances managed by this cluster, it does not
    check for potential collisions elsewhere.

    """
    self._OpenConfig()
    all_macs = self._AllMACs()
    return mac in all_macs

  def _ComputeAllLVs(self):
    """Compute the list of all LVs.

    """
    self._OpenConfig()
    lvnames = set()
    for instance in self._config_data.instances.values():
      node_data = instance.MapLVsByNode()
      for lv_list in node_data.values():
        lvnames.update(lv_list)
    return lvnames

  @locking.ssynchronized(_config_lock, shared=1)
  def GenerateUniqueID(self, exceptions=None):
    """Generate an unique disk name.

    This checks the current node, instances and disk names for
    duplicates.

    Args:
      - exceptions: a list with some other names which should be checked
                    for uniqueness (used for example when you want to get
                    more than one id at one time without adding each one in
                    turn to the config file

    Returns: the unique id as a string

    """
    existing = set()
    existing.update(self._temporary_ids)
    existing.update(self._ComputeAllLVs())
    existing.update(self._config_data.instances.keys())
    existing.update(self._config_data.nodes.keys())
    if exceptions is not None:
      existing.update(exceptions)
    retries = 64
    while retries > 0:
      unique_id = utils.NewUUID()
      if unique_id not in existing and unique_id is not None:
        break
    else:
      raise errors.ConfigurationError("Not able generate an unique ID"
                                      " (last tried ID: %s" % unique_id)
    self._temporary_ids.add(unique_id)
    return unique_id

  def _AllMACs(self):
    """Return all MACs present in the config.

    """
    self._OpenConfig()

    result = []
    for instance in self._config_data.instances.values():
      for nic in instance.nics:
        result.append(nic.mac)

    return result

  @locking.ssynchronized(_config_lock, shared=1)
  def VerifyConfig(self):
    """Stub verify function.
    """
    self._OpenConfig()

    result = []
    seen_macs = []
    data = self._config_data
    for instance_name in data.instances:
      instance = data.instances[instance_name]
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
    return result

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
    if disk.dev_type in constants.LDS_DRBD:
      pnode, snode, port = disk.logical_id
      if node_name not in (pnode, snode):
        raise errors.ConfigurationError("DRBD device not knowing node %s" %
                                        node_name)
      pnode_info = self._UnlockedGetNodeInfo(pnode)
      snode_info = self._UnlockedGetNodeInfo(snode)
      if pnode_info is None or snode_info is None:
        raise errors.ConfigurationError("Can't find primary or secondary node"
                                        " for %s" % str(disk))
      if pnode == node_name:
        disk.physical_id = (pnode_info.secondary_ip, port,
                            snode_info.secondary_ip, port)
      else: # it must be secondary, we tested above
        disk.physical_id = (snode_info.secondary_ip, port,
                            pnode_info.secondary_ip, port)
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

    """
    if not isinstance(port, int):
      raise errors.ProgrammerError("Invalid type passed for port")

    self._OpenConfig()
    self._config_data.cluster.tcpudp_port_pool.add(port)
    self._WriteConfig()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetPortList(self):
    """Returns a copy of the current port list.

    """
    self._OpenConfig()
    return self._config_data.cluster.tcpudp_port_pool.copy()

  @locking.ssynchronized(_config_lock)
  def AllocatePort(self):
    """Allocate a port.

    The port will be taken from the available port pool or from the
    default port range (and in this case we increase
    highest_used_port).

    """
    self._OpenConfig()

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

  @locking.ssynchronized(_config_lock, shared=1)
  def GetHostKey(self):
    """Return the rsa hostkey from the config.

    Args: None

    Returns: rsa hostkey
    """
    self._OpenConfig()
    return self._config_data.cluster.rsahostkeypub

  @locking.ssynchronized(_config_lock)
  def AddInstance(self, instance):
    """Add an instance to the config.

    This should be used after creating a new instance.

    Args:
      instance: the instance object
    """
    if not isinstance(instance, objects.Instance):
      raise errors.ProgrammerError("Invalid type passed to AddInstance")

    if instance.disk_template != constants.DT_DISKLESS:
      all_lvs = instance.MapLVsByNode()
      logger.Info("Instance '%s' DISK_LAYOUT: %s" % (instance.name, all_lvs))

    self._OpenConfig()
    self._config_data.instances[instance.name] = instance
    self._WriteConfig()

  def _SetInstanceStatus(self, instance_name, status):
    """Set the instance's status to a given value.

    """
    if status not in ("up", "down"):
      raise errors.ProgrammerError("Invalid status '%s' passed to"
                                   " ConfigWriter._SetInstanceStatus()" %
                                   status)
    self._OpenConfig()

    if instance_name not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" %
                                      instance_name)
    instance = self._config_data.instances[instance_name]
    if instance.status != status:
      instance.status = status
      self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def MarkInstanceUp(self, instance_name):
    """Mark the instance status to up in the config.

    """
    self._SetInstanceStatus(instance_name, "up")

  @locking.ssynchronized(_config_lock)
  def RemoveInstance(self, instance_name):
    """Remove the instance from the configuration.

    """
    self._OpenConfig()

    if instance_name not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" % instance_name)
    del self._config_data.instances[instance_name]
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def RenameInstance(self, old_name, new_name):
    """Rename an instance.

    This needs to be done in ConfigWriter and not by RemoveInstance
    combined with AddInstance as only we can guarantee an atomic
    rename.

    """
    self._OpenConfig()
    if old_name not in self._config_data.instances:
      raise errors.ConfigurationError("Unknown instance '%s'" % old_name)
    inst = self._config_data.instances[old_name]
    del self._config_data.instances[old_name]
    inst.name = new_name

    for disk in inst.disks:
      if disk.dev_type == constants.LD_FILE:
        # rename the file paths in logical and physical id
        file_storage_dir = os.path.dirname(os.path.dirname(disk.logical_id[1]))
        disk.physical_id = disk.logical_id = (disk.logical_id[0],
                                              os.path.join(file_storage_dir,
                                                           inst.name,
                                                           disk.iv_name))

    self._config_data.instances[inst.name] = inst
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def MarkInstanceDown(self, instance_name):
    """Mark the status of an instance to down in the configuration.

    """
    self._SetInstanceStatus(instance_name, "down")

  def _UnlockedGetInstanceList(self):
    """Get the list of instances.

    This function is for internal use, when the config lock is already held.

    """
    self._OpenConfig()
    return self._config_data.instances.keys()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceList(self):
    """Get the list of instances.

    Returns:
      array of instances, ex. ['instance2.example.com','instance1.example.com']
      these contains all the instances, also the ones in Admin_down state

    """
    return self._UnlockedGetInstanceList()

  @locking.ssynchronized(_config_lock, shared=1)
  def ExpandInstanceName(self, short_name):
    """Attempt to expand an incomplete instance name.

    """
    self._OpenConfig()

    return utils.MatchNameComponent(short_name,
                                    self._config_data.instances.keys())

  def _UnlockedGetInstanceInfo(self, instance_name):
    """Returns informations about an instance.

    This function is for internal use, when the config lock is already held.

    """
    self._OpenConfig()

    if instance_name not in self._config_data.instances:
      return None

    return self._config_data.instances[instance_name]

  @locking.ssynchronized(_config_lock, shared=1)
  def GetInstanceInfo(self, instance_name):
    """Returns informations about an instance.

    It takes the information from the configuration file. Other informations of
    an instance are taken from the live systems.

    Args:
      instance: name of the instance, ex instance1.example.com

    Returns:
      the instance object

    """
    return self._UnlockedGetInstanceInfo(instance_name)

  @locking.ssynchronized(_config_lock)
  def AddNode(self, node):
    """Add a node to the configuration.

    Args:
      node: an object.Node instance

    """
    logging.info("Adding node %s to configuration" % node.name)

    self._OpenConfig()
    self._config_data.nodes[node.name] = node
    self._WriteConfig()

  @locking.ssynchronized(_config_lock)
  def RemoveNode(self, node_name):
    """Remove a node from the configuration.

    """
    logging.info("Removing node %s from configuration" % node_name)

    self._OpenConfig()
    if node_name not in self._config_data.nodes:
      raise errors.ConfigurationError("Unknown node '%s'" % node_name)

    del self._config_data.nodes[node_name]
    self._WriteConfig()

  @locking.ssynchronized(_config_lock, shared=1)
  def ExpandNodeName(self, short_name):
    """Attempt to expand an incomplete instance name.

    """
    self._OpenConfig()

    return utils.MatchNameComponent(short_name,
                                    self._config_data.nodes.keys())

  def _UnlockedGetNodeInfo(self, node_name):
    """Get the configuration of a node, as stored in the config.

    This function is for internal use, when the config lock is already held.

    Args: node: nodename (tuple) of the node

    Returns: the node object

    """
    self._OpenConfig()

    if node_name not in self._config_data.nodes:
      return None

    return self._config_data.nodes[node_name]


  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeInfo(self, node_name):
    """Get the configuration of a node, as stored in the config.

    Args: node: nodename (tuple) of the node

    Returns: the node object

    """
    return self._UnlockedGetNodeInfo(node_name)

  def _UnlockedGetNodeList(self):
    """Return the list of nodes which are in the configuration.

    This function is for internal use, when the config lock is already held.

    """
    self._OpenConfig()
    return self._config_data.nodes.keys()


  @locking.ssynchronized(_config_lock, shared=1)
  def GetNodeList(self):
    """Return the list of nodes which are in the configuration.

    """
    return self._UnlockedGetNodeList()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetAllNodesInfo(self):
    """Get the configuration of all nodes.

    @rtype: dict
    @returns: dict of (node, node_info), where node_info is what
              would GetNodeInfo return for the node

    """
    my_dict = dict([(node, self._UnlockedGetNodeInfo(node))
                    for node in self._UnlockedGetNodeList()])
    return my_dict

  @locking.ssynchronized(_config_lock, shared=1)
  def DumpConfig(self):
    """Return the entire configuration of the cluster.
    """
    self._OpenConfig()
    return self._config_data

  def _BumpSerialNo(self):
    """Bump up the serial number of the config.

    """
    self._config_data.cluster.serial_no += 1

  def _OpenConfig(self):
    """Read the config data from disk.

    In case we already have configuration data and the config file has
    the same mtime as when we read it, we skip the parsing of the
    file, since de-serialisation could be slow.

    """
    try:
      st = os.stat(self._cfg_file)
    except OSError, err:
      raise errors.ConfigurationError("Can't stat config file: %s" % err)
    if (self._config_data is not None and
        self._config_time is not None and
        self._config_time == st.st_mtime and
        self._config_size == st.st_size and
        self._config_inode == st.st_ino):
      # data is current, so skip loading of config file
      return

    # Make sure the configuration has the right version
    ValidateConfig()

    f = open(self._cfg_file, 'r')
    try:
      try:
        data = objects.ConfigData.FromDict(serializer.Load(f.read()))
      except Exception, err:
        raise errors.ConfigurationError(err)
    finally:
      f.close()
    if (not hasattr(data, 'cluster') or
        not hasattr(data.cluster, 'rsahostkeypub')):
      raise errors.ConfigurationError("Incomplete configuration"
                                      " (missing cluster.rsahostkeypub)")
    self._config_data = data
    self._config_time = st.st_mtime
    self._config_size = st.st_size
    self._config_inode = st.st_ino

  def _DistributeConfig(self):
    """Distribute the configuration to the other nodes.

    Currently, this only copies the configuration file. In the future,
    it could be used to encapsulate the 2/3-phase update mechanism.

    """
    if self._offline:
      return True
    bad = False
    nodelist = self._UnlockedGetNodeList()
    myhostname = self._my_hostname

    try:
      nodelist.remove(myhostname)
    except ValueError:
      pass

    result = rpc.call_upload_file(nodelist, self._cfg_file)
    for node in nodelist:
      if not result[node]:
        logger.Error("copy of file %s to node %s failed" %
                     (self._cfg_file, node))
        bad = True
    return not bad

  def _WriteConfig(self, destination=None):
    """Write the configuration data to persistent storage.

    """
    if destination is None:
      destination = self._cfg_file
    self._BumpSerialNo()
    txt = serializer.Dump(self._config_data.ToDict())
    dir_name, file_name = os.path.split(destination)
    fd, name = tempfile.mkstemp('.newconfig', file_name, dir_name)
    f = os.fdopen(fd, 'w')
    try:
      f.write(txt)
      os.fsync(f.fileno())
    finally:
      f.close()
    # we don't need to do os.close(fd) as f.close() did it
    os.rename(name, destination)
    self.write_count += 1
    # re-set our cache as not to re-read the config file
    try:
      st = os.stat(destination)
    except OSError, err:
      raise errors.ConfigurationError("Can't stat config file: %s" % err)
    self._config_time = st.st_mtime
    self._config_size = st.st_size
    self._config_inode = st.st_ino
    # and redistribute the config file
    self._DistributeConfig()

  @locking.ssynchronized(_config_lock)
  def InitConfig(self, node, primary_ip, secondary_ip,
                 hostkeypub, mac_prefix, vg_name, def_bridge):
    """Create the initial cluster configuration.

    It will contain the current node, which will also be the master
    node, and no instances or operating systmes.

    Args:
      node: the nodename of the initial node
      primary_ip: the IP address of the current host
      secondary_ip: the secondary IP of the current host or None
      hostkeypub: the public hostkey of this host

    """
    hu_port = constants.FIRST_DRBD_PORT - 1
    globalconfig = objects.Cluster(serial_no=1,
                                   rsahostkeypub=hostkeypub,
                                   highest_used_port=hu_port,
                                   mac_prefix=mac_prefix,
                                   volume_group_name=vg_name,
                                   default_bridge=def_bridge,
                                   tcpudp_port_pool=set())
    if secondary_ip is None:
      secondary_ip = primary_ip
    nodeconfig = objects.Node(name=node, primary_ip=primary_ip,
                              secondary_ip=secondary_ip)

    self._config_data = objects.ConfigData(nodes={node: nodeconfig},
                                           instances={},
                                           cluster=globalconfig)
    self._WriteConfig()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetVGName(self):
    """Return the volume group name.

    """
    self._OpenConfig()
    return self._config_data.cluster.volume_group_name

  @locking.ssynchronized(_config_lock)
  def SetVGName(self, vg_name):
    """Set the volume group name.

    """
    self._OpenConfig()
    self._config_data.cluster.volume_group_name = vg_name
    self._WriteConfig()

  @locking.ssynchronized(_config_lock, shared=1)
  def GetDefBridge(self):
    """Return the default bridge.

    """
    self._OpenConfig()
    return self._config_data.cluster.default_bridge

  @locking.ssynchronized(_config_lock, shared=1)
  def GetMACPrefix(self):
    """Return the mac prefix.

    """
    self._OpenConfig()
    return self._config_data.cluster.mac_prefix

  @locking.ssynchronized(_config_lock, shared=1)
  def GetClusterInfo(self):
    """Returns informations about the cluster

    Returns:
      the cluster object

    """
    self._OpenConfig()

    return self._config_data.cluster

  @locking.ssynchronized(_config_lock)
  def Update(self, target):
    """Notify function to be called after updates.

    This function must be called when an object (as returned by
    GetInstanceInfo, GetNodeInfo, GetCluster) has been updated and the
    caller wants the modifications saved to the backing store. Note
    that all modified objects will be saved, but the target argument
    is the one the caller wants to ensure that it's saved.

    """
    if self._config_data is None:
      raise errors.ProgrammerError("Configuration file not read,"
                                   " cannot save.")
    if isinstance(target, objects.Cluster):
      test = target == self._config_data.cluster
    elif isinstance(target, objects.Node):
      test = target in self._config_data.nodes.values()
    elif isinstance(target, objects.Instance):
      test = target in self._config_data.instances.values()
    else:
      raise errors.ProgrammerError("Invalid object type (%s) passed to"
                                   " ConfigWriter.Update" % type(target))
    if not test:
      raise errors.ConfigurationError("Configuration updated since object"
                                      " has been read or unknown object")
    self._WriteConfig()
