#
#

# Copyright (C) 2013 Google Inc.
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


"""Support for mocking the cluster configuration"""


import random
import time
import uuid as uuid_module

from ganeti import config
from ganeti import constants
from ganeti import errors
from ganeti.network import AddressPool
from ganeti import objects
from ganeti import utils

import mocks


RESERVE_ACTION = "reserve"
RELEASE_ACTION = "release"


def _StubGetEntResolver():
  return mocks.FakeGetentResolver()


def _UpdateIvNames(base_idx, disks):
  """Update the C{iv_name} attribute of disks.

  @type disks: list of L{objects.Disk}

  """
  for (idx, disk) in enumerate(disks):
    disk.iv_name = "disk/%s" % (base_idx + idx)


# pylint: disable=R0904
class ConfigMock(config.ConfigWriter):
  """A mocked cluster configuration with added methods for easy customization.

  """

  def __init__(self, cfg_file="/dev/null"):
    self._cur_group_id = 1
    self._cur_node_id = 1
    self._cur_inst_id = 1
    self._cur_disk_id = 1
    self._cur_os_id = 1
    self._cur_nic_id = 1
    self._cur_net_id = 1
    self._default_os = None
    self._mocked_config_store = None

    self._temporary_macs = config.TemporaryReservationManager()
    self._temporary_secrets = config.TemporaryReservationManager()
    self._temporary_lvs = config.TemporaryReservationManager()
    self._temporary_ips = config.TemporaryReservationManager()

    super(ConfigMock, self).__init__(cfg_file=cfg_file,
                                     _getents=_StubGetEntResolver(),
                                     offline=True)

    with self.GetConfigManager():
      self._CreateConfig()

  def _GetUuid(self):
    return str(uuid_module.uuid4())

  def _GetObjUuid(self, obj):
    if obj is None:
      return None
    elif isinstance(obj, objects.ConfigObject):
      return obj.uuid
    else:
      return obj

  def AddNewNodeGroup(self,
                      uuid=None,
                      name=None,
                      ndparams=None,
                      diskparams=None,
                      ipolicy=None,
                      hv_state_static=None,
                      disk_state_static=None,
                      alloc_policy=None,
                      networks=None):
    """Add a new L{objects.NodeGroup} to the cluster configuration

    See L{objects.NodeGroup} for parameter documentation.

    @rtype: L{objects.NodeGroup}
    @return: the newly added node group

    """
    group_id = self._cur_group_id
    self._cur_group_id += 1

    if uuid is None:
      uuid = self._GetUuid()
    if name is None:
      name = "mock_group_%d" % group_id
    if networks is None:
      networks = {}

    group = objects.NodeGroup(uuid=uuid,
                              name=name,
                              ndparams=ndparams,
                              diskparams=diskparams,
                              ipolicy=ipolicy,
                              hv_state_static=hv_state_static,
                              disk_state_static=disk_state_static,
                              alloc_policy=alloc_policy,
                              networks=networks,
                              members=[])

    self._UnlockedAddNodeGroup(group, None, True)
    return group

  # pylint: disable=R0913
  def AddNewNode(self,
                 uuid=None,
                 name=None,
                 primary_ip=None,
                 secondary_ip=None,
                 master_candidate=True,
                 offline=False,
                 drained=False,
                 group=None,
                 master_capable=True,
                 vm_capable=True,
                 ndparams=None,
                 powered=True,
                 hv_state=None,
                 hv_state_static=None,
                 disk_state=None,
                 disk_state_static=None):
    """Add a new L{objects.Node} to the cluster configuration

    See L{objects.Node} for parameter documentation.

    @rtype: L{objects.Node}
    @return: the newly added node

    """
    node_id = self._cur_node_id
    self._cur_node_id += 1

    if uuid is None:
      uuid = self._GetUuid()
    if name is None:
      name = "mock_node_%d.example.com" % node_id
    if primary_ip is None:
      primary_ip = "192.0.2.%d" % node_id
    if secondary_ip is None:
      secondary_ip = "203.0.113.%d" % node_id
    if group is None:
      group = self._default_group.uuid
    group = self._GetObjUuid(group)
    if ndparams is None:
      ndparams = {}

    node = objects.Node(uuid=uuid,
                        name=name,
                        primary_ip=primary_ip,
                        secondary_ip=secondary_ip,
                        master_candidate=master_candidate,
                        offline=offline,
                        drained=drained,
                        group=group,
                        master_capable=master_capable,
                        vm_capable=vm_capable,
                        ndparams=ndparams,
                        powered=powered,
                        hv_state=hv_state,
                        hv_state_static=hv_state_static,
                        disk_state=disk_state,
                        disk_state_static=disk_state_static)

    self._UnlockedAddNode(node, None)
    return node

  def AddNewInstance(self,
                     uuid=None,
                     name=None,
                     primary_node=None,
                     os=None,
                     hypervisor=None,
                     hvparams=None,
                     beparams=None,
                     osparams=None,
                     osparams_private=None,
                     admin_state=None,
                     admin_state_source=None,
                     nics=None,
                     disks=None,
                     disk_template=None,
                     disks_active=None,
                     network_port=None,
                     secondary_node=None):
    """Add a new L{objects.Instance} to the cluster configuration

    See L{objects.Instance} for parameter documentation.

    @rtype: L{objects.Instance}
    @return: the newly added instance

    """
    inst_id = self._cur_inst_id
    self._cur_inst_id += 1

    if uuid is None:
      uuid = self._GetUuid()
    if name is None:
      name = "mock_inst_%d.example.com" % inst_id
    if primary_node is None:
      primary_node = self._master_node.uuid
    primary_node = self._GetObjUuid(primary_node)
    if os is None:
      os = self.GetDefaultOs().name + objects.OS.VARIANT_DELIM +\
           self.GetDefaultOs().supported_variants[0]
    if hypervisor is None:
      hypervisor = self.GetClusterInfo().enabled_hypervisors[0]
    if hvparams is None:
      hvparams = {}
    if beparams is None:
      beparams = {}
    if osparams is None:
      osparams = {}
    if osparams_private is None:
      osparams_private = {}
    if admin_state is None:
      admin_state = constants.ADMINST_DOWN
    if admin_state_source is None:
      admin_state_source = constants.ADMIN_SOURCE
    if nics is None:
      nics = [self.CreateNic()]
    if disk_template is None:
      if disks is None:
        # user chose nothing, so create a plain disk for him
        disk_template = constants.DT_PLAIN
      elif len(disks) == 0:
        disk_template = constants.DT_DISKLESS
      else:
        disk_template = disks[0].dev_type
    if disks is None:
      if disk_template == constants.DT_DISKLESS:
        disks = []
      elif disk_template == constants.DT_EXT:
        provider = "mock_provider"
        disks = [self.CreateDisk(dev_type=disk_template,
                                 primary_node=primary_node,
                                 secondary_node=secondary_node,
                                 params={constants.IDISK_PROVIDER: provider})]
      else:
        disks = [self.CreateDisk(dev_type=disk_template,
                                 primary_node=primary_node,
                                 secondary_node=secondary_node)]
    if disks_active is None:
      disks_active = admin_state == constants.ADMINST_UP

    inst = objects.Instance(uuid=uuid,
                            name=name,
                            primary_node=primary_node,
                            os=os,
                            hypervisor=hypervisor,
                            hvparams=hvparams,
                            beparams=beparams,
                            osparams=osparams,
                            osparams_private=osparams_private,
                            admin_state=admin_state,
                            admin_state_source=admin_state_source,
                            nics=nics,
                            disks=[],
                            disks_active=disks_active,
                            network_port=network_port)
    self.AddInstance(inst, None)
    for disk in disks:
      self.AddInstanceDisk(inst.uuid, disk)
    return inst

  def AddNewNetwork(self,
                    uuid=None,
                    name=None,
                    mac_prefix=None,
                    network=None,
                    network6=None,
                    gateway=None,
                    gateway6=None,
                    reservations=None,
                    ext_reservations=None):
    """Add a new L{objects.Network} to the cluster configuration

    See L{objects.Network} for parameter documentation.

    @rtype: L{objects.Network}
    @return: the newly added network

    """
    net_id = self._cur_net_id
    self._cur_net_id += 1

    if uuid is None:
      uuid = self._GetUuid()
    if name is None:
      name = "mock_net_%d" % net_id
    if network is None:
      network = "198.51.100.0/24"
    if gateway is None:
      if network[-3:] == "/24":
        gateway = network[:-4] + "1"
      else:
        gateway = "198.51.100.1"
    if network[-3:] == "/24" and gateway == network[:-4] + "1":
      if reservations is None:
        reservations = "0" * 256
      if ext_reservations:
        ext_reservations = "11" + ("0" * 253) + "1"
    elif reservations is None or ext_reservations is None:
      raise AssertionError("You have to specify 'reservations' and"
                           " 'ext_reservations'!")

    net = objects.Network(uuid=uuid,
                          name=name,
                          mac_prefix=mac_prefix,
                          network=network,
                          network6=network6,
                          gateway=gateway,
                          gateway6=gateway6,
                          reservations=reservations,
                          ext_reservations=ext_reservations)
    self.AddNetwork(net, None)
    return net

  def AddOrphanDisk(self, **params):
    disk = self.CreateDisk(**params)
    self._UnlockedAddDisk(disk)

  def ConnectNetworkToGroup(self, net, group, netparams=None):
    """Connect the given network to the group.

    @type net: string or L{objects.Network}
    @param net: network object or UUID
    @type group: string of L{objects.NodeGroup}
    @param group: node group object of UUID
    @type netparams: dict
    @param netparams: network parameters for this connection

    """
    net_obj = None
    if isinstance(net, objects.Network):
      net_obj = net
    else:
      net_obj = self.GetNetwork(net)

    group_obj = None
    if isinstance(group, objects.NodeGroup):
      group_obj = group
    else:
      group_obj = self.GetNodeGroup(group)

    if net_obj is None or group_obj is None:
      raise AssertionError("Failed to get network or node group")

    if netparams is None:
      netparams = {
        constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
        constants.NIC_LINK: "br_mock"
      }

    group_obj.networks[net_obj.uuid] = netparams

  def CreateDisk(self,
                 uuid=None,
                 name=None,
                 dev_type=constants.DT_PLAIN,
                 logical_id=None,
                 children=None,
                 nodes=None,
                 iv_name=None,
                 size=1024,
                 mode=constants.DISK_RDWR,
                 params=None,
                 spindles=None,
                 primary_node=None,
                 secondary_node=None,
                 create_nodes=False,
                 instance_disk_index=0):
    """Create a new L{objecs.Disk} object

    @rtype: L{objects.Disk}
    @return: the newly create disk object

    """
    disk_id = self._cur_disk_id
    self._cur_disk_id += 1

    if uuid is None:
      uuid = self._GetUuid()
    if name is None:
      name = "mock_disk_%d" % disk_id
    if params is None:
      params = {}

    if dev_type == constants.DT_DRBD8:
      pnode_uuid = self._GetObjUuid(primary_node)
      snode_uuid = self._GetObjUuid(secondary_node)
      if logical_id is not None:
        pnode_uuid = logical_id[0]
        snode_uuid = logical_id[1]

      if pnode_uuid is None and create_nodes:
        pnode_uuid = self.AddNewNode().uuid
      if snode_uuid is None and create_nodes:
        snode_uuid = self.AddNewNode().uuid

      if pnode_uuid is None or snode_uuid is None:
        raise AssertionError("Trying to create DRBD disk without nodes!")

      if logical_id is None:
        logical_id = (pnode_uuid, snode_uuid,
                      constants.FIRST_DRBD_PORT + disk_id,
                      disk_id, disk_id, "mock_secret")
      if children is None:
        data_child = self.CreateDisk(dev_type=constants.DT_PLAIN,
                                     size=size)
        meta_child = self.CreateDisk(dev_type=constants.DT_PLAIN,
                                     size=constants.DRBD_META_SIZE)
        children = [data_child, meta_child]

      if nodes is None:
        nodes = [pnode_uuid, snode_uuid]
    elif dev_type == constants.DT_PLAIN:
      if logical_id is None:
        logical_id = ("mockvg", "mock_disk_%d" % disk_id)
      if nodes is None and primary_node is not None:
        nodes = [primary_node]
    elif dev_type in constants.DTS_FILEBASED:
      if logical_id is None:
        logical_id = (constants.FD_LOOP, "/file/storage/disk%d" % disk_id)
      if (nodes is None and primary_node is not None and
          dev_type == constants.DT_FILE):
        nodes = [primary_node]
    elif dev_type == constants.DT_BLOCK:
      if logical_id is None:
        logical_id = (constants.BLOCKDEV_DRIVER_MANUAL,
                      "/dev/disk/disk%d" % disk_id)
    elif dev_type == constants.DT_EXT:
      if logical_id is None:
        provider = params.get(constants.IDISK_PROVIDER, None)
        if provider is None:
          raise AssertionError("You must specify a 'provider' for 'ext' disks")
        logical_id = (provider, "mock_disk_%d" % disk_id)
    elif logical_id is None:
      raise NotImplementedError
    if children is None:
      children = []
    if nodes is None:
      nodes = []
    if iv_name is None:
      iv_name = "disk/%d" % instance_disk_index

    return objects.Disk(uuid=uuid,
                        name=name,
                        dev_type=dev_type,
                        logical_id=logical_id,
                        children=children,
                        nodes=nodes,
                        iv_name=iv_name,
                        size=size,
                        mode=mode,
                        params=params,
                        spindles=spindles)

  def GetDefaultOs(self):
    if self._default_os is None:
      self._default_os = self.CreateOs(name="mocked_os")
    return self._default_os

  def CreateOs(self,
               name=None,
               path=None,
               api_versions=None,
               create_script=None,
               export_script=None,
               import_script=None,
               rename_script=None,
               verify_script=None,
               supported_variants=None,
               supported_parameters=None):
    """Create a new L{objects.OS} object

    @rtype: L{object.OS}
    @return: the newly create OS objects

    """
    os_id = self._cur_os_id
    self._cur_os_id += 1

    if name is None:
      name = "mock_os_%d" % os_id
    if path is None:
      path = "/mocked/path/%d" % os_id
    if api_versions is None:
      api_versions = [constants.OS_API_V20]
    if create_script is None:
      create_script = "mock_create.sh"
    if export_script is None:
      export_script = "mock_export.sh"
    if import_script is None:
      import_script = "mock_import.sh"
    if rename_script is None:
      rename_script = "mock_rename.sh"
    if verify_script is None:
      verify_script = "mock_verify.sh"
    if supported_variants is None:
      supported_variants = ["default"]
    if supported_parameters is None:
      supported_parameters = ["mock_param"]

    return objects.OS(name=name,
                      path=path,
                      api_versions=api_versions,
                      create_script=create_script,
                      export_script=export_script,
                      import_script=import_script,
                      rename_script=rename_script,
                      verify_script=verify_script,
                      supported_variants=supported_variants,
                      supported_parameters=supported_parameters)

  def CreateNic(self,
                uuid=None,
                name=None,
                mac=None,
                ip=None,
                network=None,
                nicparams=None,
                netinfo=None):
    """Create a new L{objecs.NIC} object

    @rtype: L{objects.NIC}
    @return: the newly create NIC object

    """
    nic_id = self._cur_nic_id
    self._cur_nic_id += 1

    if uuid is None:
      uuid = self._GetUuid()
    if name is None:
      name = "mock_nic_%d" % nic_id
    if mac is None:
      mac = "aa:00:00:aa:%02x:%02x" % (nic_id / 0xff, nic_id % 0xff)
    if isinstance(network, objects.Network):
      if ip:
        pool = AddressPool(network)
        pool.Reserve(ip)
      network = network.uuid
    if nicparams is None:
      nicparams = {}

    return objects.NIC(uuid=uuid,
                       name=name,
                       mac=mac,
                       ip=ip,
                       network=network,
                       nicparams=nicparams,
                       netinfo=netinfo)

  def SetEnabledDiskTemplates(self, enabled_disk_templates):
    """Set the enabled disk templates in the cluster.

    This also takes care of required IPolicy updates.

    @type enabled_disk_templates: list of string
    @param enabled_disk_templates: list of disk templates to enable

    """
    cluster = self.GetClusterInfo()
    cluster.enabled_disk_templates = list(enabled_disk_templates)
    cluster.ipolicy[constants.IPOLICY_DTS] = list(enabled_disk_templates)

  def ComputeDRBDMap(self):
    return dict((node_uuid, {}) for node_uuid in self._ConfigData().nodes)

  def AllocateDRBDMinor(self, node_uuids, disk_uuid):
    return [0] * len(node_uuids)

  def ReleaseDRBDMinors(self, disk_uuid):
    pass

  def SetIPolicyField(self, category, field, value):
    """Set a value of a desired ipolicy field.

    @type category: one of L{constants.ISPECS_MAX}, L{constants.ISPECS_MIN},
      L{constants.ISPECS_STD}
    @param category: Whether to change the default value, or the upper or lower
      bound.
    @type field: string
    @param field: The field to change.
    @type value: any
    @param value: The value to assign.

    """
    if category not in [constants.ISPECS_MAX, constants.ISPECS_MIN,
                        constants.ISPECS_STD]:
      raise ValueError("Invalid ipolicy category %s" % category)

    ipolicy_dict = self.GetClusterInfo().ipolicy[constants.ISPECS_MINMAX][0]
    ipolicy_dict[category][field] = value

  def _CreateConfig(self):
    self._config_data = objects.ConfigData(
      version=constants.CONFIG_VERSION,
      cluster=None,
      nodegroups={},
      nodes={},
      instances={},
      networks={},
      disks={})

    master_node_uuid = self._GetUuid()

    self._cluster = objects.Cluster(
      serial_no=1,
      rsahostkeypub="",
      highest_used_port=(constants.FIRST_DRBD_PORT - 1),
      tcpudp_port_pool=set(),
      mac_prefix="aa:00:00",
      volume_group_name="xenvg",
      reserved_lvs=None,
      drbd_usermode_helper="/bin/true",
      master_node=master_node_uuid,
      master_ip="192.0.2.254",
      master_netdev=constants.DEFAULT_BRIDGE,
      master_netmask=None,
      use_external_mip_script=None,
      cluster_name="cluster.example.com",
      file_storage_dir="/tmp",
      shared_file_storage_dir=None,
      enabled_hypervisors=[constants.HT_XEN_HVM, constants.HT_XEN_PVM,
                           constants.HT_KVM],
      hvparams=constants.HVC_DEFAULTS.copy(),
      ipolicy=None,
      os_hvp={self.GetDefaultOs().name: constants.HVC_DEFAULTS.copy()},
      beparams=None,
      osparams=None,
      osparams_private_cluster=None,
      nicparams={constants.PP_DEFAULT: constants.NICC_DEFAULTS},
      ndparams=None,
      diskparams=None,
      candidate_pool_size=3,
      modify_etc_hosts=False,
      modify_ssh_setup=False,
      maintain_node_health=False,
      uid_pool=None,
      default_iallocator="mock_iallocator",
      hidden_os=None,
      blacklisted_os=None,
      primary_ip_family=None,
      prealloc_wipe_disks=None,
      enabled_disk_templates=list(constants.DISK_TEMPLATE_PREFERENCE),
      )
    self._cluster.ctime = self._cluster.mtime = time.time()
    self._cluster.UpgradeConfig()
    self._ConfigData().cluster = self._cluster

    self._default_group = self.AddNewNodeGroup(name="default")
    self._master_node = self.AddNewNode(uuid=master_node_uuid)

  def _OpenConfig(self, _accept_foreign, force=False):
    self._config_data = self._mocked_config_store

  def _WriteConfig(self, destination=None, releaselock=False):
    self._mocked_config_store = self._ConfigData()

  def _GetRpc(self, _address_list):
    raise AssertionError("This should not be used during tests!")

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
      prefix = self._ConfigData().cluster.mac_prefix

    def GenMac():
      byte1 = random.randrange(0, 256)
      byte2 = random.randrange(0, 256)
      byte3 = random.randrange(0, 256)
      mac = "%s:%02x:%02x:%02x" % (prefix, byte1, byte2, byte3)
      return mac

    return GenMac

  def GenerateMAC(self, net_uuid, ec_id):
    """Generate a MAC for an instance.

    This should check the current instances for duplicates.

    """
    existing = self._AllMACs()
    prefix = self._UnlockedGetNetworkMACPrefix(net_uuid)
    gen_mac = self._GenerateOneMAC(prefix)
    return self._temporary_macs.Generate(existing, gen_mac, ec_id)

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

  def GenerateDRBDSecret(self, ec_id):
    """Generate a DRBD secret.

    This checks the current disks for duplicates.

    """
    return self._temporary_secrets.Generate(self._AllDRBDSecrets(),
                                            utils.GenerateSecret,
                                            ec_id)

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
    pool = AddressPool(nobj)
    if action == RESERVE_ACTION:
      pool.Reserve(address)
    elif action == RELEASE_ACTION:
      pool.Release(address)

  def _UnlockedReleaseIp(self, net_uuid, address, ec_id):
    """Give a specific IP address back to an IP pool.

    The IP address is returned to the IP pool designated by pool_id and marked
    as reserved.

    """
    self._temporary_ips.Reserve(ec_id,
                                (RELEASE_ACTION, address, net_uuid))

  def ReleaseIp(self, net_uuid, address, ec_id):
    """Give a specified IP address back to an IP pool.

    This is just a wrapper around _UnlockedReleaseIp.

    """
    if net_uuid:
      self._UnlockedReleaseIp(net_uuid, address, ec_id)

  def GenerateIp(self, net_uuid, ec_id):
    """Find a free IPv4 address for an instance.

    """
    nobj = self._UnlockedGetNetwork(net_uuid)
    pool = AddressPool(nobj)

    def gen_one():
      try:
        ip = pool.GenerateFree()
      except errors.AddressPoolError:
        raise errors.ReservationError("Cannot generate IP. Network is full")
      return (RESERVE_ACTION, ip, net_uuid)

    _, address, _ = self._temporary_ips.Generate([], gen_one, ec_id)
    return address

  def _UnlockedReserveIp(self, net_uuid, address, ec_id, check=True):
    """Reserve a given IPv4 address for use by an instance.

    """
    nobj = self._UnlockedGetNetwork(net_uuid)
    pool = AddressPool(nobj)
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
                                       (RESERVE_ACTION,
                                        address, net_uuid))

  def ReserveIp(self, net_uuid, address, ec_id, check=True):
    """Reserve a given IPv4 address for use by an instance.

    """
    if net_uuid:
      return self._UnlockedReserveIp(net_uuid, address, ec_id, check)

  def AddInstance(self, instance, ec_id, replace=False):
    """Add an instance to the config.

    """
    instance.serial_no = 1
    instance.ctime = instance.mtime = time.time()
    self._ConfigData().instances[instance.uuid] = instance
    self._ConfigData().cluster.serial_no += 1 # pylint: disable=E1103
    self.ReleaseDRBDMinors(instance.uuid)
    self._UnlockedCommitTemporaryIps(ec_id)

  def _UnlockedAddDisk(self, disk):
    disk.UpgradeConfig()
    self._ConfigData().disks[disk.uuid] = disk
    self._ConfigData().cluster.serial_no += 1 # pylint: disable=E1103
    self.ReleaseDRBDMinors(disk.uuid)

  def _UnlockedAttachInstanceDisk(self, inst_uuid, disk_uuid, idx=None):
    instance = self._UnlockedGetInstanceInfo(inst_uuid)
    if idx is None:
      idx = len(instance.disks)
    instance.disks.insert(idx, disk_uuid)
    instance_disks = self._UnlockedGetInstanceDisks(inst_uuid)
    for (disk_idx, disk) in enumerate(instance_disks[idx:]):
      disk.iv_name = "disk/%s" % (idx + disk_idx)
    instance.serial_no += 1
    instance.mtime = time.time()

  def AddInstanceDisk(self, inst_uuid, disk, idx=None, replace=False):
    self._UnlockedAddDisk(disk)
    self._UnlockedAttachInstanceDisk(inst_uuid, disk.uuid, idx)

  def AttachInstanceDisk(self, inst_uuid, disk_uuid, idx=None):
    self._UnlockedAttachInstanceDisk(inst_uuid, disk_uuid, idx)

  def GetDisk(self, disk_uuid):
    """Retrieves a disk object if present.

    """
    return self._ConfigData().disks[disk_uuid]

  def AllocatePort(self):
    return 1

  def Update(self, target, feedback_fn, ec_id=None):
    def replace_in(target, tdict):
      tdict[target.uuid] = target

    update_serial = False
    if isinstance(target, objects.Cluster):
      self._ConfigData().cluster = target
    elif isinstance(target, objects.Node):
      replace_in(target, self._ConfigData().nodes)
      update_serial = True
    elif isinstance(target, objects.Instance):
      replace_in(target, self._ConfigData().instances)
    elif isinstance(target, objects.NodeGroup):
      replace_in(target, self._ConfigData().nodegroups)
    elif isinstance(target, objects.Network):
      replace_in(target, self._ConfigData().networks)
    elif isinstance(target, objects.Disk):
      replace_in(target, self._ConfigData().disks)

    target.serial_no += 1
    target.mtime = now = time.time()

    if update_serial:
      self._ConfigData().cluster.serial_no += 1 # pylint: disable=E1103
      self._ConfigData().cluster.mtime = now

  def SetInstancePrimaryNode(self, inst_uuid, target_node_uuid):
    self._UnlockedGetInstanceInfo(inst_uuid).primary_node = target_node_uuid

  def _SetInstanceStatus(self, inst_uuid, status,
                         disks_active, admin_state_source):
    if inst_uuid not in self._ConfigData().instances:
      raise errors.ConfigurationError("Unknown instance '%s'" %
                                      inst_uuid)
    instance = self._ConfigData().instances[inst_uuid]

    if status is None:
      status = instance.admin_state
    if disks_active is None:
      disks_active = instance.disks_active
    if admin_state_source is None:
      admin_state_source = instance.admin_state_source

    assert status in constants.ADMINST_ALL, \
           "Invalid status '%s' passed to SetInstanceStatus" % (status,)

    if instance.admin_state != status or \
       instance.disks_active != disks_active or \
       instance.admin_state_source != admin_state_source:
      instance.admin_state = status
      instance.disks_active = disks_active
      instance.admin_state_source = admin_state_source
      instance.serial_no += 1
      instance.mtime = time.time()
    return instance

  def _UnlockedDetachInstanceDisk(self, inst_uuid, disk_uuid):
    """Detach a disk from an instance.

    @type inst_uuid: string
    @param inst_uuid: The UUID of the instance object
    @type disk_uuid: string
    @param disk_uuid: The UUID of the disk object

    """
    instance = self._UnlockedGetInstanceInfo(inst_uuid)
    if instance is None:
      raise errors.ConfigurationError("Instance %s doesn't exist"
                                      % inst_uuid)
    if disk_uuid not in self._ConfigData().disks:
      raise errors.ConfigurationError("Disk %s doesn't exist" % disk_uuid)

    # Check if disk is attached to the instance
    if disk_uuid not in instance.disks:
      raise errors.ProgrammerError("Disk %s is not attached to an instance"
                                   % disk_uuid)

    idx = instance.disks.index(disk_uuid)
    instance.disks.remove(disk_uuid)
    instance_disks = self._UnlockedGetInstanceDisks(inst_uuid)
    _UpdateIvNames(idx, instance_disks[idx:])
    instance.serial_no += 1
    instance.mtime = time.time()

  def DetachInstanceDisk(self, inst_uuid, disk_uuid):
    self._UnlockedDetachInstanceDisk(inst_uuid, disk_uuid)

  def RemoveInstanceDisk(self, inst_uuid, disk_uuid):
    self._UnlockedDetachInstanceDisk(inst_uuid, disk_uuid)
    self._UnlockedRemoveDisk(disk_uuid)

  def RemoveInstance(self, inst_uuid):
    del self._ConfigData().instances[inst_uuid]

  def AddTcpUdpPort(self, port):
    self._ConfigData().cluster.tcpudp_port_pool.add(port)
