#
#

# Copyright (C) 2013 Google Inc.
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


"""Support for mocking the cluster configuration"""


import time
import uuid as uuid_module

from ganeti import config
from ganeti import constants
from ganeti import objects
from ganeti.network import AddressPool

import mocks


def _StubGetEntResolver():
  return mocks.FakeGetentResolver()


# pylint: disable=R0904
class ConfigMock(config.ConfigWriter):
  """A mocked cluster configuration with added methods for easy customization.

  """

  def __init__(self):
    self._cur_group_id = 1
    self._cur_node_id = 1
    self._cur_inst_id = 1
    self._cur_disk_id = 1
    self._cur_os_id = 1
    self._cur_nic_id = 1
    self._cur_net_id = 1
    self._default_os = None

    super(ConfigMock, self).__init__(cfg_file="/dev/null",
                                     _getents=_StubGetEntResolver())

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

    self.AddNodeGroup(group, None)
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

    self.AddNode(node, None)
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
                            nics=nics,
                            disks=disks,
                            disk_template=disk_template,
                            disks_active=disks_active,
                            network_port=network_port)
    self.AddInstance(inst, None)
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
    elif dev_type == constants.DT_PLAIN:
      if logical_id is None:
        logical_id = ("mockvg", "mock_disk_%d" % disk_id)
    elif dev_type in constants.DTS_FILEBASED:
      if logical_id is None:
        logical_id = (constants.FD_LOOP, "/file/storage/disk%d" % disk_id)
    elif dev_type == constants.DT_BLOCK:
      if logical_id is None:
        logical_id = (constants.BLOCKDEV_DRIVER_MANUAL,
                      "/dev/disk/disk%d" % disk_id)
    elif logical_id is None:
      raise NotImplementedError
    if children is None:
      children = []
    if iv_name is None:
      iv_name = "disk/%d" % instance_disk_index
    if params is None:
      params = {}

    return objects.Disk(uuid=uuid,
                        name=name,
                        dev_type=dev_type,
                        logical_id=logical_id,
                        children=children,
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

  def _OpenConfig(self, accept_foreign):
    self._config_data = objects.ConfigData(
      version=constants.CONFIG_VERSION,
      cluster=None,
      nodegroups={},
      nodes={},
      instances={},
      networks={})

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
    self._config_data.cluster = self._cluster

    self._default_group = self.AddNewNodeGroup(name="default")
    self._master_node = self.AddNewNode(uuid=master_node_uuid)

  def _WriteConfig(self, destination=None, feedback_fn=None):
    pass

  def _DistributeConfig(self, feedback_fn):
    pass

  def _GetRpc(self, address_list):
    raise AssertionError("This should not be used during tests!")
