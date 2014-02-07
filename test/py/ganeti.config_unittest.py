#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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
from ganeti.cmdlib import instance

from ganeti.config import TemporaryReservationManager

import testutils
import mocks
import mock


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

  def _create_instance(self):
    """Create and return an instance object"""
    inst = objects.Instance(name="test.example.com",
                            uuid="test-uuid",
                            disks=[], nics=[],
                            disk_template=constants.DT_DISKLESS,
                            primary_node=self._get_object().GetMasterNode(),
                            osparams_private=serializer.PrivateDict())
    return inst

  def testEmpty(self):
    """Test instantiate config object"""
    self._get_object()

  def testInit(self):
    """Test initialize the config file"""
    cfg = self._get_object()
    self.failUnlessEqual(1, len(cfg.GetNodeList()))
    self.failUnlessEqual(0, len(cfg.GetInstanceList()))

  def testUpdateCluster(self):
    """Test updates on the cluster object"""
    cfg = self._get_object()
    # construct a fake cluster object
    fake_cl = objects.Cluster()
    # fail if we didn't read the config
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_cl, None)

    cl = cfg.GetClusterInfo()
    # first pass, must not fail
    cfg.Update(cl, None)
    # second pass, also must not fail (after the config has been written)
    cfg.Update(cl, None)
    # but the fake_cl update should still fail
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_cl, None)

  def testUpdateNode(self):
    """Test updates on one node object"""
    cfg = self._get_object()
    # construct a fake node
    fake_node = objects.Node()
    # fail if we didn't read the config
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_node,
                          None)

    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    # first pass, must not fail
    cfg.Update(node, None)
    # second pass, also must not fail (after the config has been written)
    cfg.Update(node, None)
    # but the fake_node update should still fail
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_node,
                          None)

  def testUpdateInstance(self):
    """Test updates on one instance object"""
    cfg = self._get_object()
    # construct a fake instance
    inst = self._create_instance()
    fake_instance = objects.Instance()
    # fail if we didn't read the config
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_instance,
                          None)

    cfg.AddInstance(inst, "my-job")
    instance = cfg.GetInstanceInfo(cfg.GetInstanceList()[0])
    # first pass, must not fail
    cfg.Update(instance, None)
    # second pass, also must not fail (after the config has been written)
    cfg.Update(instance, None)
    # but the fake_instance update should still fail
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_instance,
                          None)

  def testUpgradeSave(self):
    """Test that any modification done during upgrading is saved back"""
    cfg = self._get_object()

    # Remove an element, run upgrade, and check if the element is
    # back and the file upgraded
    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    # For a ConfigObject, None is the same as a missing field
    node.ndparams = None
    oldsaved = utils.ReadFile(self.cfg_file)
    cfg._UpgradeConfig()
    self.assertTrue(node.ndparams is not None)
    newsaved = utils.ReadFile(self.cfg_file)
    # We rely on the fact that at least the serial number changes
    self.assertNotEqual(oldsaved, newsaved)

    # Add something that should not be there this time
    key = list(constants.NDC_GLOBALS)[0]
    node.ndparams[key] = constants.NDC_DEFAULTS[key]
    cfg._WriteConfig(None)
    oldsaved = utils.ReadFile(self.cfg_file)
    cfg._UpgradeConfig()
    self.assertTrue(node.ndparams.get(key) is None)
    newsaved = utils.ReadFile(self.cfg_file)
    self.assertNotEqual(oldsaved, newsaved)

    # Do the upgrade again, this time there should be no update
    oldsaved = newsaved
    cfg._UpgradeConfig()
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
        }

    cfg = self._get_object()
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
      }
    cfg = self._get_object()
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
    self.assertEqual(set(map(operator.attrgetter("name"),
                             cfg.GetAllNodeGroupsInfo().values())),
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

    # Destructive tests
    orig_group = node2.group
    try:
      other_uuid = "68b3d087-6ea5-491c-b81f-0a47d90228c5"
      assert compat.all(node.group != other_uuid
                        for node in cfg.GetAllNodesInfo().values())
      node2.group = "68b3d087-6ea5-491c-b81f-0a47d90228c5"
      self.assertRaises(errors.ConfigurationError, cfg.AssignGroupNodes, [
        (node2.uuid, grp2.uuid),
        ])
      _VerifySerials()
    finally:
      node2.group = orig_group

  def _TestVerifyConfigIPolicy(self, ipolicy, ipowner, cfg, isgroup):
    INVALID_KEY = "this_key_cannot_exist"

    ipolicy[INVALID_KEY] = None
    # A call to cluster.SimpleFillIPolicy causes different kinds of error
    # depending on the owner (cluster or group)
    if isgroup:
      errs = cfg.VerifyConfig()
      self.assertTrue(len(errs) >= 1)
      errstr = "%s has invalid instance policy" % ipowner
      self.assertTrue(_IsErrorInList(errstr, errs))
    else:
      self.assertRaises(AssertionError, cfg.VerifyConfig)
    del ipolicy[INVALID_KEY]
    errs = cfg.VerifyConfig()
    self.assertFalse(errs)

    key = list(constants.IPOLICY_PARAMETERS)[0]
    hasoldv = (key in ipolicy)
    if hasoldv:
      oldv = ipolicy[key]
    ipolicy[key] = "blah"
    errs = cfg.VerifyConfig()
    self.assertTrue(len(errs) >= 1)
    self.assertTrue(_IsErrorInList("%s has invalid instance policy" % ipowner,
                                   errs))
    if hasoldv:
      ipolicy[key] = oldv
    else:
      del ipolicy[key]

    ispeclist = []
    if constants.ISPECS_MINMAX in ipolicy:
      for k in range(len(ipolicy[constants.ISPECS_MINMAX])):
        ispeclist.extend([
            (ipolicy[constants.ISPECS_MINMAX][k][constants.ISPECS_MIN],
             "%s[%s]/%s" % (constants.ISPECS_MINMAX, k, constants.ISPECS_MIN)),
            (ipolicy[constants.ISPECS_MINMAX][k][constants.ISPECS_MAX],
             "%s[%s]/%s" % (constants.ISPECS_MINMAX, k, constants.ISPECS_MAX)),
            ])
    if constants.ISPECS_STD in ipolicy:
      ispeclist.append((ipolicy[constants.ISPECS_STD], constants.ISPECS_STD))

    for (ispec, ispecpath) in ispeclist:
      ispec[INVALID_KEY] = None
      errs = cfg.VerifyConfig()
      self.assertTrue(len(errs) >= 1)
      self.assertTrue(_IsErrorInList(("%s has invalid ipolicy/%s" %
                                      (ipowner, ispecpath)), errs))
      del ispec[INVALID_KEY]
      errs = cfg.VerifyConfig()
      self.assertFalse(errs)

      for par in constants.ISPECS_PARAMETERS:
        hasoldv = par in ispec
        if hasoldv:
          oldv = ispec[par]
        ispec[par] = "blah"
        errs = cfg.VerifyConfig()
        self.assertTrue(len(errs) >= 1)
        self.assertTrue(_IsErrorInList(("%s has invalid ipolicy/%s" %
                                        (ipowner, ispecpath)), errs))
        if hasoldv:
          ispec[par] = oldv
        else:
          del ispec[par]
        errs = cfg.VerifyConfig()
        self.assertFalse(errs)

    if constants.ISPECS_MINMAX in ipolicy:
      # Test partial minmax specs
      for minmax in ipolicy[constants.ISPECS_MINMAX]:
        for key in constants.ISPECS_MINMAX_KEYS:
          self.assertTrue(key in minmax)
          ispec = minmax[key]
          del minmax[key]
          errs = cfg.VerifyConfig()
          self.assertTrue(len(errs) >= 1)
          self.assertTrue(_IsErrorInList("Missing instance specification",
                                         errs))
          minmax[key] = ispec
          for par in constants.ISPECS_PARAMETERS:
            oldv = ispec[par]
            del ispec[par]
            errs = cfg.VerifyConfig()
            self.assertTrue(len(errs) >= 1)
            self.assertTrue(_IsErrorInList("Missing instance specs parameters",
                                           errs))
            ispec[par] = oldv
      errs = cfg.VerifyConfig()
      self.assertFalse(errs)

  def _TestVerifyConfigGroupIPolicy(self, groupinfo, cfg):
    old_ipolicy = groupinfo.ipolicy
    ipolicy = cfg.GetClusterInfo().SimpleFillIPolicy({})
    groupinfo.ipolicy = ipolicy
    # Test partial policies
    for key in constants.IPOLICY_ALL_KEYS:
      self.assertTrue(key in ipolicy)
      oldv = ipolicy[key]
      del ipolicy[key]
      errs = cfg.VerifyConfig()
      self.assertFalse(errs)
      ipolicy[key] = oldv
    groupinfo.ipolicy = old_ipolicy

  def _TestVerifyConfigClusterIPolicy(self, ipolicy, cfg):
    # Test partial policies
    for key in constants.IPOLICY_ALL_KEYS:
      self.assertTrue(key in ipolicy)
      oldv = ipolicy[key]
      del ipolicy[key]
      self.assertRaises(AssertionError, cfg.VerifyConfig)
      ipolicy[key] = oldv
    errs = cfg.VerifyConfig()
    self.assertFalse(errs)
    # Partial standard specs
    ispec = ipolicy[constants.ISPECS_STD]
    for par in constants.ISPECS_PARAMETERS:
      oldv = ispec[par]
      del ispec[par]
      errs = cfg.VerifyConfig()
      self.assertTrue(len(errs) >= 1)
      self.assertTrue(_IsErrorInList("Missing instance specs parameters",
                                     errs))
      ispec[par] = oldv
    errs = cfg.VerifyConfig()
    self.assertFalse(errs)

  def testVerifyConfig(self):
    cfg = self._get_object()

    errs = cfg.VerifyConfig()
    self.assertFalse(errs)

    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    key = list(constants.NDC_GLOBALS)[0]
    node.ndparams[key] = constants.NDC_DEFAULTS[key]
    errs = cfg.VerifyConfig()
    self.assertTrue(len(errs) >= 1)
    self.assertTrue(_IsErrorInList("has some global parameters set", errs))

    del node.ndparams[key]
    errs = cfg.VerifyConfig()
    self.assertFalse(errs)

    cluster = cfg.GetClusterInfo()
    nodegroup = cfg.GetNodeGroup(cfg.GetNodeGroupList()[0])
    self._TestVerifyConfigIPolicy(cluster.ipolicy, "cluster", cfg, False)
    self._TestVerifyConfigClusterIPolicy(cluster.ipolicy, cfg)
    self._TestVerifyConfigIPolicy(nodegroup.ipolicy, nodegroup.name, cfg, True)
    self._TestVerifyConfigGroupIPolicy(nodegroup, cfg)
    nodegroup.ipolicy = cluster.SimpleFillIPolicy(nodegroup.ipolicy)
    self._TestVerifyConfigIPolicy(nodegroup.ipolicy, nodegroup.name, cfg, True)

  # Tests for Ssconf helper functions
  def testUnlockedGetHvparamsString(self):
    hvparams = {"a": "A", "b": "B", "c": "C"}
    hvname = "myhv"
    cfg_writer = self._get_object()
    cfg_writer._config_data = mock.Mock()
    cfg_writer._config_data.cluster = mock.Mock()
    cfg_writer._config_data.cluster.hvparams = {hvname: hvparams}

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


def _IsErrorInList(err_str, err_list):
  return any(map(lambda e: err_str in e, err_list))


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
    instance._UpdateIvNames(0, disks)
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [])

  def testWrongNames(self):
    disks = self._MakeDisks(["disk/1", "disk/3", "disk/2"])
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [
      (0, "disk/0", "disk/1"),
      (1, "disk/1", "disk/3"),
      ])

    # Fix names
    instance._UpdateIvNames(0, disks)
    self.assertEqual(config._CheckInstanceDiskIvNames(disks), [])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
