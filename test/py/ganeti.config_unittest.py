#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""Script for unittesting the config module"""


import unittest
import os
import tempfile
import operator

from ganeti import bootstrap
from ganeti import config
from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import utils
from ganeti import netutils
from ganeti import compat
from ganeti import serializer

from ganeti.config import TemporaryReservationManager

import testutils
import mocks
import mock
from testutils.config_mock import ConfigMock, _UpdateIvNames


def _StubGetEntResolver():
  return mocks.FakeGetentResolver()


class TestConfigRunner(unittest.TestCase):
  """Testing case for HooksRunner"""
  def setUp(self):
    fd, self.cfg_file = tempfile.mkstemp()
    os.close(fd)
    self._init_cluster(self.cfg_file)

  def tearDown(self):
    try:
      os.unlink(self.cfg_file)
    except OSError:
      pass

  def _get_object(self):
    """Returns an instance of ConfigWriter"""
    cfg = config.ConfigWriter(cfg_file=self.cfg_file, offline=True,
                              _getents=_StubGetEntResolver)
    return cfg

  def _get_object_mock(self):
    """Returns a mocked instance of ConfigWriter"""
    cfg = ConfigMock(cfg_file=self.cfg_file)
    return cfg

  def _init_cluster(self, cfg):
    """Initializes the cfg object"""
    me = netutils.Hostname()
    ip = constants.IP4_ADDRESS_LOCALHOST
    # master_ip must not conflict with the node ip address
    master_ip = "127.0.0.2"

    cluster_config = objects.Cluster(
      serial_no=1,
      rsahostkeypub="",
      dsahostkeypub="",
      highest_used_port=(constants.FIRST_DRBD_PORT - 1),
      mac_prefix="aa:00:00",
      volume_group_name="xenvg",
      drbd_usermode_helper="/bin/true",
      nicparams={constants.PP_DEFAULT: constants.NICC_DEFAULTS},
      ndparams=constants.NDC_DEFAULTS,
      tcpudp_port_pool=set(),
      enabled_hypervisors=[constants.HT_FAKE],
      master_node=me.name,
      master_ip=master_ip,
      master_netdev=constants.DEFAULT_BRIDGE,
      cluster_name="cluster.local",
      file_storage_dir="/tmp",
      uid_pool=[],
      )

    master_node_config = objects.Node(name=me.name,
                                      primary_ip=me.ip,
                                      secondary_ip=ip,
                                      serial_no=1,
                                      master_candidate=True)

    bootstrap.InitConfig(constants.CONFIG_VERSION,
                         cluster_config, master_node_config, self.cfg_file)

  def _create_instance(self, cfg):
    """Create and return an instance object"""
    inst = objects.Instance(name="test.example.com",
                            uuid="test-uuid",
                            disks=[], nics=[],
                            disk_template=constants.DT_DISKLESS,
                            primary_node=cfg.GetMasterNode(),
                            osparams_private=serializer.PrivateDict(),
                            beparams={})
    return inst

  def testEmpty(self):
    """Test instantiate config object"""
    self._get_object()

  def testInit(self):
    """Test initialize the config file"""
    cfg = self._get_object()
    self.failUnlessEqual(1, len(cfg.GetNodeList()))
    self.failUnlessEqual(0, len(cfg.GetInstanceList()))

  def _GenericNodesCheck(self, iobj, all_nodes, secondary_nodes):
    for i in [all_nodes, secondary_nodes]:
      self.assertTrue(isinstance(i, (list, tuple)),
                      msg="Data type doesn't guarantee order")

    self.assertTrue(iobj.primary_node not in secondary_nodes)
    self.assertEqual(all_nodes[0], iobj.primary_node,
                     msg="Primary node not first node in list")

  def _CreateInstanceDisk(self, cfg):
    # Construct instance and add a plain disk
    inst = self._create_instance(cfg)
    cfg.AddInstance(inst, "my-job")
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=128,
                        logical_id=("myxenvg", "disk25494"), uuid="disk0",
                        name="name0")
    cfg.AddInstanceDisk(inst.uuid, disk)

    return inst, disk

  def testDiskInfoByUUID(self):
    """Check if the GetDiskInfo works with UUIDs."""
    # Create mock config writer
    cfg = self._get_object_mock()

    # Create an instance and attach a disk to it
    inst, disk = self._CreateInstanceDisk(cfg)

    result = cfg.GetDiskInfo("disk0")
    self.assertEqual(disk, result)

  def testDiskInfoByName(self):
    """Check if the GetDiskInfo works with names."""
    # Create mock config writer
    cfg = self._get_object_mock()

    # Create an instance and attach a disk to it
    inst, disk = self._CreateInstanceDisk(cfg)

    result = cfg.GetDiskInfoByName("name0")
    self.assertEqual(disk, result)

  def testDiskInfoByWrongUUID(self):
    """Assert that GetDiskInfo raises an exception when given a wrong UUID."""
    # Create mock config writer
    cfg = self._get_object_mock()

    # Create an instance and attach a disk to it
    inst, disk = self._CreateInstanceDisk(cfg)

    result = cfg.GetDiskInfo("disk1134")
    self.assertEqual(None, result)

  def testDiskInfoByWrongName(self):
    """Assert that GetDiskInfo returns None when given a wrong name."""
    # Create mock config writer
    cfg = self._get_object_mock()

    # Create an instance and attach a disk to it
    inst, disk = self._CreateInstanceDisk(cfg)

    result = cfg.GetDiskInfoByName("name1134")
    self.assertEqual(None, result)

  def testDiskInfoDuplicateName(self):
    """Assert that GetDiskInfo raises exception on duplicate names."""
    # Create mock config writer
    cfg = self._get_object_mock()

    # Create an instance and attach a disk to it
    inst, disk = self._CreateInstanceDisk(cfg)

    # Create a disk with the same name and attach it to the instance.
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=128,
                        logical_id=("myxenvg", "disk25494"), uuid="disk1",
                        name="name0")
    cfg.AddInstanceDisk(inst.uuid, disk)

    self.assertRaises(errors.ConfigurationError, cfg.GetDiskInfoByName, "name0")

  def testInstNodesNoDisks(self):
    """Test all_nodes/secondary_nodes when there are no disks"""
    # construct instance
    cfg = self._get_object_mock()
    inst = self._create_instance(cfg)
    cfg.AddInstance(inst, "my-job")

    # No disks
    all_nodes = cfg.GetInstanceNodes(inst.uuid)
    secondary_nodes = cfg.GetInstanceSecondaryNodes(inst.uuid)
    self._GenericNodesCheck(inst, all_nodes, secondary_nodes)
    self.assertEqual(len(secondary_nodes), 0)
    self.assertEqual(set(all_nodes), set([inst.primary_node]))
    self.assertEqual(cfg.GetInstanceLVsByNode(inst.uuid), {
      inst.primary_node: [],
      })

  def testInstNodesPlainDisks(self):
    # construct instance
    cfg = self._get_object_mock()
    inst = self._create_instance(cfg)
    disks = [
      objects.Disk(dev_type=constants.DT_PLAIN, size=128,
                   logical_id=("myxenvg", "disk25494"),
                   uuid="disk0"),
      objects.Disk(dev_type=constants.DT_PLAIN, size=512,
                   logical_id=("myxenvg", "disk29071"),
                   uuid="disk1"),
      ]
    cfg.AddInstance(inst, "my-job")
    for disk in disks:
      cfg.AddInstanceDisk(inst.uuid, disk)

    # Plain disks
    all_nodes = cfg.GetInstanceNodes(inst.uuid)
    secondary_nodes = cfg.GetInstanceSecondaryNodes(inst.uuid)
    self._GenericNodesCheck(inst, all_nodes, secondary_nodes)
    self.assertEqual(len(secondary_nodes), 0)
    self.assertEqual(set(all_nodes), set([inst.primary_node]))
    self.assertEqual(cfg.GetInstanceLVsByNode(inst.uuid), {
      inst.primary_node: ["myxenvg/disk25494", "myxenvg/disk29071"],
      })

  def testInstNodesDrbdDisks(self):
    # construct a second node
    cfg = self._get_object_mock()
    node_group = cfg.LookupNodeGroup(None)
    master_uuid = cfg.GetMasterNode()
    node2 = objects.Node(name="node2.example.com", group=node_group,
                         ndparams={}, uuid="node2-uuid")
    cfg.AddNode(node2, "my-job")

    # construct instance
    inst = self._create_instance(cfg)
    disks = [
      objects.Disk(dev_type=constants.DT_DRBD8, size=786432,
                   logical_id=(master_uuid, node2.uuid,
                               12300, 0, 0, "secret"),
                   children=[
                     objects.Disk(dev_type=constants.DT_PLAIN, size=786432,
                                  logical_id=("myxenvg", "disk0"),
                                  uuid="data0"),
                     objects.Disk(dev_type=constants.DT_PLAIN, size=128,
                                  logical_id=("myxenvg", "meta0"),
                                  uuid="meta0")
                   ],
                   iv_name="disk/0", uuid="disk0")
      ]
    cfg.AddInstance(inst, "my-job")
    for disk in disks:
      cfg.AddInstanceDisk(inst.uuid, disk)

    # Drbd Disks
    all_nodes = cfg.GetInstanceNodes(inst.uuid)
    secondary_nodes = cfg.GetInstanceSecondaryNodes(inst.uuid)
    self._GenericNodesCheck(inst, all_nodes, secondary_nodes)
    self.assertEqual(set(secondary_nodes), set([node2.uuid]))
    self.assertEqual(set(all_nodes),
                     set([inst.primary_node, node2.uuid]))
    self.assertEqual(cfg.GetInstanceLVsByNode(inst.uuid), {
      master_uuid: ["myxenvg/disk0", "myxenvg/meta0"],
      node2.uuid: ["myxenvg/disk0", "myxenvg/meta0"],
      })

  def testUpgradeSave(self):
    """Test that any modification done during upgrading is saved back"""
    cfg = self._get_object()

    # Remove an element, run upgrade, and check if the element is
    # back and the file upgraded
    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    # For a ConfigObject, None is the same as a missing field
    node.ndparams = None
    oldsaved = utils.ReadFile(self.cfg_file)
    cfg._UpgradeConfig(saveafter=True)
    self.assertTrue(node.ndparams is not None)
    newsaved = utils.ReadFile(self.cfg_file)
    # We rely on the fact that at least the serial number changes
    self.assertNotEqual(oldsaved, newsaved)

    # Add something that should not be there this time
    key = list(constants.NDC_GLOBALS)[0]
    node.ndparams[key] = constants.NDC_DEFAULTS[key]
    cfg._WriteConfig(None)
    oldsaved = utils.ReadFile(self.cfg_file)
    cfg._UpgradeConfig(saveafter=True)
    self.assertTrue(node.ndparams.get(key) is None)
    newsaved = utils.ReadFile(self.cfg_file)
    self.assertNotEqual(oldsaved, newsaved)

    # Do the upgrade again, this time there should be no update
    oldsaved = newsaved
    cfg._UpgradeConfig(saveafter=True)
    newsaved = utils.ReadFile(self.cfg_file)
    self.assertEqual(oldsaved, newsaved)

    # Reload the configuration again: it shouldn't change the file
    oldsaved = newsaved
    self._get_object()
    newsaved = utils.ReadFile(self.cfg_file)
    self.assertEqual(oldsaved, newsaved)

  def testNICParameterSyntaxCheck(self):
    """Test the NIC's CheckParameterSyntax function"""
    mode = constants.NIC_MODE
    link = constants.NIC_LINK
    m_bridged = constants.NIC_MODE_BRIDGED
    m_routed = constants.NIC_MODE_ROUTED
    CheckSyntax = objects.NIC.CheckParameterSyntax

    CheckSyntax(constants.NICC_DEFAULTS)
    CheckSyntax({mode: m_bridged, link: "br1"})
    CheckSyntax({mode: m_routed, link: "default"})
    self.assertRaises(errors.ConfigurationError,
                      CheckSyntax, {mode: "000invalid", link: "any"})
    self.assertRaises(errors.ConfigurationError,
                      CheckSyntax, {mode: m_bridged, link: None})
    self.assertRaises(errors.ConfigurationError,
                      CheckSyntax, {mode: m_bridged, link: ""})

  def testGetNdParamsDefault(self):
    cfg = self._get_object()
    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    self.assertEqual(cfg.GetNdParams(node), constants.NDC_DEFAULTS)

  def testGetNdParamsModifiedNode(self):
    my_ndparams = {
        constants.ND_OOB_PROGRAM: "/bin/node-oob",
        constants.ND_SPINDLE_COUNT: 1,
        constants.ND_EXCLUSIVE_STORAGE: False,
        constants.ND_OVS: True,
        constants.ND_OVS_NAME: "openvswitch",
        constants.ND_OVS_LINK: "eth1",
        constants.ND_SSH_PORT: 22,
        constants.ND_CPU_SPEED: 1.0,
        }

    cfg = self._get_object_mock()
    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    node.ndparams = my_ndparams
    cfg.Update(node, None)
    self.assertEqual(cfg.GetNdParams(node), my_ndparams)

  def testGetNdParamsInheritance(self):
    node_ndparams = {
      constants.ND_OOB_PROGRAM: "/bin/node-oob",
      constants.ND_OVS_LINK: "eth3"
      }
    group_ndparams = {
      constants.ND_SPINDLE_COUNT: 10,
      constants.ND_OVS: True,
      constants.ND_OVS_NAME: "openvswitch",
      constants.ND_SSH_PORT: 222,
      }
    expected_ndparams = {
      constants.ND_OOB_PROGRAM: "/bin/node-oob",
      constants.ND_SPINDLE_COUNT: 10,
      constants.ND_EXCLUSIVE_STORAGE:
        constants.NDC_DEFAULTS[constants.ND_EXCLUSIVE_STORAGE],
      constants.ND_OVS: True,
      constants.ND_OVS_NAME: "openvswitch",
      constants.ND_OVS_LINK: "eth3",
      constants.ND_SSH_PORT: 222,
      constants.ND_CPU_SPEED: 1.0,
      }
    cfg = self._get_object_mock()
    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    node.ndparams = node_ndparams
    cfg.Update(node, None)
    group = cfg.GetNodeGroup(node.group)
    group.ndparams = group_ndparams
    cfg.Update(group, None)
    self.assertEqual(cfg.GetNdParams(node), expected_ndparams)

  def testAddGroupFillsFieldsIfMissing(self):
    cfg = self._get_object()
    group = objects.NodeGroup(name="test", members=[])
    cfg.AddNodeGroup(group, "my-job")
    self.assert_(utils.UUID_RE.match(group.uuid))
    self.assertEqual(constants.ALLOC_POLICY_PREFERRED, group.alloc_policy)

  def testAddGroupPreservesFields(self):
    cfg = self._get_object()
    group = objects.NodeGroup(name="test", members=[],
                              alloc_policy=constants.ALLOC_POLICY_LAST_RESORT)
    cfg.AddNodeGroup(group, "my-job")
    self.assertEqual(constants.ALLOC_POLICY_LAST_RESORT, group.alloc_policy)

  def testAddGroupDoesNotPreserveFields(self):
    cfg = self._get_object()
    group = objects.NodeGroup(name="test", members=[],
                              serial_no=17, ctime=123, mtime=456)
    cfg.AddNodeGroup(group, "my-job")
    self.assertEqual(1, group.serial_no)
    self.assert_(group.ctime > 1200000000)
    self.assert_(group.mtime > 1200000000)

  def testAddGroupCanSkipUUIDCheck(self):
    cfg = self._get_object()
    uuid = cfg.GenerateUniqueID("my-job")
    group = objects.NodeGroup(name="test", members=[], uuid=uuid,
                              serial_no=17, ctime=123, mtime=456)

    self.assertRaises(errors.ConfigurationError,
                      cfg.AddNodeGroup, group, "my-job")

    cfg.AddNodeGroup(group, "my-job", check_uuid=False) # Does not raise.
    self.assertEqual(uuid, group.uuid)

  def testAssignGroupNodes(self):
    me = netutils.Hostname()
    cfg = self._get_object()

    # Create two groups
    grp1 = objects.NodeGroup(name="grp1", members=[],
                             uuid="2f2fadf7-2a70-4a23-9ab5-2568c252032c")
    grp1_serial = 1
    cfg.AddNodeGroup(grp1, "job")

    grp2 = objects.NodeGroup(name="grp2", members=[],
                             uuid="798d0de3-680f-4a0e-b29a-0f54f693b3f1")
    grp2_serial = 1
    cfg.AddNodeGroup(grp2, "job")
    self.assertEqual(set(ng.name for ng in cfg.GetAllNodeGroupsInfo().values()),
                     set(["grp1", "grp2", constants.INITIAL_NODE_GROUP_NAME]))

    # No-op
    cluster_serial = cfg.GetClusterInfo().serial_no
    cfg.AssignGroupNodes([])
    cluster_serial += 1

    # Create two nodes
    node1 = objects.Node(name="node1", group=grp1.uuid, ndparams={},
                         uuid="node1-uuid")
    node1_serial = 1
    node2 = objects.Node(name="node2", group=grp2.uuid, ndparams={},
                         uuid="node2-uuid")
    node2_serial = 1
    cfg.AddNode(node1, "job")
    cfg.AddNode(node2, "job")
    cluster_serial += 2
    self.assertEqual(set(cfg.GetNodeList()),
                     set(["node1-uuid", "node2-uuid",
                          cfg.GetNodeInfoByName(me.name).uuid]))

    (grp1, grp2) = [cfg.GetNodeGroup(grp.uuid) for grp in (grp1, grp2)]

    def _VerifySerials():
      self.assertEqual(cfg.GetClusterInfo().serial_no, cluster_serial)
      self.assertEqual(node1.serial_no, node1_serial)
      self.assertEqual(node2.serial_no, node2_serial)
      self.assertEqual(grp1.serial_no, grp1_serial)
      self.assertEqual(grp2.serial_no, grp2_serial)

    _VerifySerials()

    self.assertEqual(set(grp1.members), set(["node1-uuid"]))
    self.assertEqual(set(grp2.members), set(["node2-uuid"]))

    # Check invalid nodes and groups
    self.assertRaises(errors.ConfigurationError, cfg.AssignGroupNodes, [
      ("unknown.node.example.com", grp2.uuid),
      ])
    self.assertRaises(errors.ConfigurationError, cfg.AssignGroupNodes, [
      (node1.name, "unknown-uuid"),
      ])

    self.assertEqual(node1.group, grp1.uuid)
    self.assertEqual(node2.group, grp2.uuid)
    self.assertEqual(set(grp1.members), set(["node1-uuid"]))
    self.assertEqual(set(grp2.members), set(["node2-uuid"]))

    # Another no-op
    cfg.AssignGroupNodes([])
    cluster_serial += 1
    _VerifySerials()

    # Assign to the same group (should be a no-op)
    self.assertEqual(node2.group, grp2.uuid)
    cfg.AssignGroupNodes([
      (node2.uuid, grp2.uuid),
      ])
    cluster_serial += 1
    self.assertEqual(node2.group, grp2.uuid)
    _VerifySerials()
    self.assertEqual(set(grp1.members), set(["node1-uuid"]))
    self.assertEqual(set(grp2.members), set(["node2-uuid"]))

    # Assign node 2 to group 1
    self.assertEqual(node2.group, grp2.uuid)
    cfg.AssignGroupNodes([
      (node2.uuid, grp1.uuid),
      ])
    (grp1, grp2) = [cfg.GetNodeGroup(grp.uuid) for grp in (grp1, grp2)]
    (node1, node2) =  [cfg.GetNodeInfo(node.uuid) for node in (node1, node2)]
    cluster_serial += 1
    node2_serial += 1
    grp1_serial += 1
    grp2_serial += 1
    self.assertEqual(node2.group, grp1.uuid)
    _VerifySerials()
    self.assertEqual(set(grp1.members), set(["node1-uuid", "node2-uuid"]))
    self.assertFalse(grp2.members)

    # And assign both nodes to group 2
    self.assertEqual(node1.group, grp1.uuid)
    self.assertEqual(node2.group, grp1.uuid)
    self.assertNotEqual(grp1.uuid, grp2.uuid)
    cfg.AssignGroupNodes([
      (node1.uuid, grp2.uuid),
      (node2.uuid, grp2.uuid),
      ])
    (grp1, grp2) = [cfg.GetNodeGroup(grp.uuid) for grp in (grp1, grp2)]
    (node1, node2) =  [cfg.GetNodeInfo(node.uuid) for node in (node1, node2)]
    cluster_serial += 1
    node1_serial += 1
    node2_serial += 1
    grp1_serial += 1
    grp2_serial += 1
    self.assertEqual(node1.group, grp2.uuid)
    self.assertEqual(node2.group, grp2.uuid)
    _VerifySerials()
    self.assertFalse(grp1.members)
    self.assertEqual(set(grp2.members), set(["node1-uuid", "node2-uuid"]))

  # Tests for Ssconf helper functions
  def testUnlockedGetHvparamsString(self):
    hvparams = {"a": "A", "b": "B", "c": "C"}
    hvname = "myhv"
    cfg_writer = self._get_object()
    cfg_writer._SetConfigData(mock.Mock())
    cfg_writer._ConfigData().cluster = mock.Mock()
    cfg_writer._ConfigData().cluster.hvparams = {hvname: hvparams}

    result = cfg_writer._UnlockedGetHvparamsString(hvname)

    self.assertTrue("a=A" in result)
    lines = [line for line in result.split('\n') if line != '']
    self.assertEqual(len(hvparams.keys()), len(lines))

  def testExtendByAllHvparamsStrings(self):
    all_hvparams = {constants.HT_XEN_PVM: "foo"}
    ssconf_values = {}
    cfg_writer = self._get_object()

    cfg_writer._ExtendByAllHvparamsStrings(ssconf_values, all_hvparams)

    expected_key = constants.SS_HVPARAMS_PREF + constants.HT_XEN_PVM
    self.assertTrue(expected_key in ssconf_values)

  def testAddAndRemoveCerts(self):
    cfg = self._get_object()
    self.assertEqual(0, len(cfg.GetCandidateCerts()))

    node_uuid = "1234"
    cert_digest = "foobar"
    cfg.AddNodeToCandidateCerts(node_uuid, cert_digest,
                                warn_fn=None, info_fn=None)
    self.assertEqual(1, len(cfg.GetCandidateCerts()))

    # Try adding the same cert again
    cfg.AddNodeToCandidateCerts(node_uuid, cert_digest,
                                warn_fn=None, info_fn=None)
    self.assertEqual(1, len(cfg.GetCandidateCerts()))
    self.assertTrue(cfg.GetCandidateCerts()[node_uuid] == cert_digest)

    # Overriding cert
    other_digest = "barfoo"
    cfg.AddNodeToCandidateCerts(node_uuid, other_digest,
                                warn_fn=None, info_fn=None)
    self.assertEqual(1, len(cfg.GetCandidateCerts()))
    self.assertTrue(cfg.GetCandidateCerts()[node_uuid] == other_digest)

    # Try removing a certificate from a node that is not in the list
    other_node_uuid = "5678"
    cfg.RemoveNodeFromCandidateCerts(other_node_uuid, warn_fn=None)
    self.assertEqual(1, len(cfg.GetCandidateCerts()))

    # Remove a certificate from a node that is in the list
    cfg.RemoveNodeFromCandidateCerts(node_uuid, warn_fn=None)
    self.assertEqual(0, len(cfg.GetCandidateCerts()))

  def testAttachDetachDisks(self):
    """Test if the attach/detach wrappers work properly.

    This test checks if the configuration remains in a consistent state after a
    series of detach/attach ops
    """
    # construct instance
    cfg = self._get_object_mock()
    inst = self._create_instance(cfg)
    disk = objects.Disk(dev_type=constants.DT_PLAIN, size=128,
                        logical_id=("myxenvg", "disk25494"), uuid="disk0")
    cfg.AddInstance(inst, "my-job")
    cfg.AddInstanceDisk(inst.uuid, disk)

    # Detach disk from non-existent instance
    self.assertRaises(errors.ConfigurationError, cfg.DetachInstanceDisk,
                      "1134", "disk0")

    # Detach non-existent disk
    self.assertRaises(errors.ConfigurationError, cfg.DetachInstanceDisk,
                      "test-uuid", "disk1")

    # Detach disk
    cfg.DetachInstanceDisk("test-uuid", "disk0")
    instance_disks = cfg.GetInstanceDisks("test-uuid")
    self.assertEqual(instance_disks, [])

    # Detach disk again
    self.assertRaises(errors.ProgrammerError, cfg.DetachInstanceDisk,
                      "test-uuid", "disk0")

    # Attach disk
    cfg.AttachInstanceDisk("test-uuid", "disk0")
    instance_disks = cfg.GetInstanceDisks("test-uuid")
    self.assertEqual(instance_disks, [disk])

def _IsErrorInList(err_str, err_list):
  return any((err_str in e) for e in err_list)


class TestTRM(unittest.TestCase):
  EC_ID = 1

  def testEmpty(self):
    t = TemporaryReservationManager()
    t.Reserve(self.EC_ID, "a")
    self.assertFalse(t.Reserved(self.EC_ID))
    self.assertTrue(t.Reserved("a"))
    self.assertEqual(len(t.GetReserved()), 1)

  def testDuplicate(self):
    t = TemporaryReservationManager()
    t.Reserve(self.EC_ID, "a")
    self.assertRaises(errors.ReservationError, t.Reserve, 2, "a")
    t.DropECReservations(self.EC_ID)
    self.assertFalse(t.Reserved("a"))


class TestCheckInstanceDiskIvNames(unittest.TestCase):
  @staticmethod
  def _MakeDisks(names):
    return [objects.Disk(iv_name=name) for name in names]

  def testNoError(self):
    disks = self._MakeDisks(["disk/0", "disk/1"])
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [])
    _UpdateIvNames(0, disks)
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [])

  def testWrongNames(self):
    disks = self._MakeDisks(["disk/1", "disk/3", "disk/2"])
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [
      (0, "disk/0", "disk/1"),
      (1, "disk/1", "disk/3"),
      ])

    # Fix names
    _UpdateIvNames(0, disks)
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
