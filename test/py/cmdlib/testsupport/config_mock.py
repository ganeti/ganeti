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

import uuid

from ganeti import config
from ganeti import constants
from ganeti import objects

import mocks


def _StubGetEntResolver():
  return mocks.FakeGetentResolver()


class ConfigMock(config.ConfigWriter):
  """A mocked cluster configuration with added methods for easy customization.

  """

  def __init__(self):
    self._cur_group_id = 1
    self._cur_node_id = 1
    self._cur_inst_id = 1

    super(ConfigMock, self).__init__(cfg_file="/dev/null",
                                     _getents=_StubGetEntResolver())

  def _GetUuid(self):
    return str(uuid.uuid4())

  def AddNewNodeGroup(self,
                      uuid=None,
                      name=None,
                      ndparams=None,
                      diskparams=None,
                      ipolicy=None,
                      hv_state_static=None,
                      disk_state_static=None,
                      alloc_policy=None,
                      networks=[]):
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
    if isinstance(group, objects.NodeGroup):
      group = group.uuid

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
                     hvparams={},
                     beparams={},
                     osparams={},
                     admin_state=constants.ADMINST_DOWN,
                     nics=[],
                     disks=[],
                     disk_template=constants.DT_DISKLESS,
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
    if isinstance(primary_node, objects.Node):
      primary_node = self._master_node.uuid

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
      mac_prefix="aa:00:00",
      volume_group_name="xenvg",
      drbd_usermode_helper="/bin/true",
      nicparams={constants.PP_DEFAULT: constants.NICC_DEFAULTS},
      ndparams=constants.NDC_DEFAULTS,
      tcpudp_port_pool=set(),
      enabled_hypervisors=[constants.HT_FAKE],
      master_node=master_node_uuid,
      master_ip="192.168.0.254",
      master_netdev=constants.DEFAULT_BRIDGE,
      cluster_name="cluster.example.com",
      file_storage_dir="/tmp",
      uid_pool=[],
      )
    self._config_data.cluster = self._cluster

    self._default_group = self.AddNewNodeGroup(name="default")
    self._master_node = self.AddNewNode(uuid=master_node_uuid)

  def _WriteConfig(self, destination=None, feedback_fn=None):
    pass

  def _DistributeConfig(self, feedback_fn):
    pass

  def _GetRpc(self, address_list):
    raise NotImplementedError
