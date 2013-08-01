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
    self._cur_nic_id = 1

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
      primary_ip = "192.168.0.%d" % node_id
    if secondary_ip is None:
      secondary_ip = "192.168.1.%d" % node_id
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
                     os="mocked_os",
                     hypervisor=constants.HT_FAKE,
                     hvparams=None,
                     beparams=None,
                     osparams=None,
                     admin_state=constants.ADMINST_DOWN,
                     nics=None,
                     disks=None,
                     disk_template=None,
                     disks_active=False,
                     network_port=None):
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
    if hvparams is None:
      hvparams = {}
    if beparams is None:
      beparams = {}
    if osparams is None:
      osparams = {}
    if nics is None:
      nics = [self.CreateNic()]
    if disks is None:
      disks = [self.CreateDisk()]
    if disk_template is None:
      if len(disks) == 0:
        disk_template = constants.DT_DISKLESS
      else:
        dt_guess_dict = {
          constants.LD_LV: constants.DT_PLAIN,
          constants.LD_FILE: constants.DT_FILE,
          constants.LD_DRBD8: constants.DT_DRBD8,
          constants.LD_RBD: constants.DT_RBD,
          constants.LD_BLOCKDEV: constants.DT_BLOCK,
          constants.LD_EXT: constants.DT_EXT
        }
        assert constants.LOGICAL_DISK_TYPES == set(dt_guess_dict.keys())
        disk_template = dt_guess_dict[disks[0].dev_type]

    inst = objects.Instance(uuid=uuid,
                            name=name,
                            primary_node=primary_node,
                            os=os,
                            hypervisor=hypervisor,
                            hvparams=hvparams,
                            beparams=beparams,
                            osparams=osparams,
                            admin_state=admin_state,
                            nics=nics,
                            disks=disks,
                            disk_template=disk_template,
                            disks_active=disks_active,
                            network_port=network_port)
    self.AddInstance(inst, None)
    return inst

  def CreateDisk(self,
                 uuid=None,
                 name=None,
                 dev_type=constants.LD_LV,
                 logical_id=None,
                 physical_id=None,
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

    if dev_type == constants.LD_DRBD8:
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
        data_child = self.CreateDisk(dev_type=constants.LD_LV,
                                     size=size)
        meta_child = self.CreateDisk(dev_type=constants.LD_LV,
                                     size=constants.DRBD_META_SIZE)
        children = [data_child, meta_child]
    elif dev_type == constants.LD_LV:
      if logical_id is None:
        logical_id = ("mockvg", "mock_disk_%d" % disk_id)
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
                        physical_id=physical_id,
                        children=children,
                        iv_name=iv_name,
                        size=size,
                        mode=mode,
                        params=params,
                        spindles=spindles)

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
    if nicparams is None:
      nicparams = {}

    return objects.NIC(uuid=uuid,
                       name=name,
                       mac=mac,
                       ip=ip,
                       network=network,
                       nicparams=nicparams,
                       netinfo=netinfo)

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
      master_ip="192.168.0.254",
      master_netdev=constants.DEFAULT_BRIDGE,
      master_netmask=None,
      use_external_mip_script=None,
      cluster_name="cluster.example.com",
      file_storage_dir="/tmp",
      shared_file_storage_dir=None,
      enabled_hypervisors=list(constants.HYPER_TYPES),
      hvparams=constants.HVC_DEFAULTS.copy(),
      ipolicy=None,
      os_hvp={"mocked_os": constants.HVC_DEFAULTS.copy()},
      beparams=None,
      osparams=None,
      nicparams={constants.PP_DEFAULT: constants.NICC_DEFAULTS},
      ndparams=None,
      diskparams=None,
      candidate_pool_size=3,
      modify_etc_hosts=False,
      modify_ssh_setup=False,
      maintain_node_health=False,
      uid_pool=None,
      default_iallocator=None,
      hidden_os=None,
      blacklisted_os=None,
      primary_ip_family=None,
      prealloc_wipe_disks=None,
      enabled_disk_templates=constants.DISK_TEMPLATES.copy(),
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
