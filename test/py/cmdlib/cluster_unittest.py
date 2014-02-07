#!/usr/bin/python
#

# Copyright (C) 2008, 2011, 2012, 2013 Google Inc.
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


"""Tests for LUCluster*

"""

import OpenSSL

import copy
import unittest
import operator

from ganeti.cmdlib import cluster
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import objects
from ganeti import opcodes
from ganeti import utils
from ganeti import pathutils
from ganeti import query
from ganeti.hypervisor import hv_xen

from testsupport import *

import testutils


class TestClusterVerifySsh(unittest.TestCase):
  def testMultipleGroups(self):
    fn = cluster.LUClusterVerifyGroup._SelectSshCheckNodes
    mygroupnodes = [
      objects.Node(name="node20", group="my", offline=False),
      objects.Node(name="node21", group="my", offline=False),
      objects.Node(name="node22", group="my", offline=False),
      objects.Node(name="node23", group="my", offline=False),
      objects.Node(name="node24", group="my", offline=False),
      objects.Node(name="node25", group="my", offline=False),
      objects.Node(name="node26", group="my", offline=True),
      ]
    nodes = [
      objects.Node(name="node1", group="g1", offline=True),
      objects.Node(name="node2", group="g1", offline=False),
      objects.Node(name="node3", group="g1", offline=False),
      objects.Node(name="node4", group="g1", offline=True),
      objects.Node(name="node5", group="g1", offline=False),
      objects.Node(name="node10", group="xyz", offline=False),
      objects.Node(name="node11", group="xyz", offline=False),
      objects.Node(name="node40", group="alloff", offline=True),
      objects.Node(name="node41", group="alloff", offline=True),
      objects.Node(name="node50", group="aaa", offline=False),
      ] + mygroupnodes
    assert not utils.FindDuplicates(map(operator.attrgetter("name"), nodes))

    (online, perhost) = fn(mygroupnodes, "my", nodes)
    self.assertEqual(online, ["node%s" % i for i in range(20, 26)])
    self.assertEqual(set(perhost.keys()), set(online))

    self.assertEqual(perhost, {
      "node20": ["node10", "node2", "node50"],
      "node21": ["node11", "node3", "node50"],
      "node22": ["node10", "node5", "node50"],
      "node23": ["node11", "node2", "node50"],
      "node24": ["node10", "node3", "node50"],
      "node25": ["node11", "node5", "node50"],
      })

  def testSingleGroup(self):
    fn = cluster.LUClusterVerifyGroup._SelectSshCheckNodes
    nodes = [
      objects.Node(name="node1", group="default", offline=True),
      objects.Node(name="node2", group="default", offline=False),
      objects.Node(name="node3", group="default", offline=False),
      objects.Node(name="node4", group="default", offline=True),
      ]
    assert not utils.FindDuplicates(map(operator.attrgetter("name"), nodes))

    (online, perhost) = fn(nodes, "default", nodes)
    self.assertEqual(online, ["node2", "node3"])
    self.assertEqual(set(perhost.keys()), set(online))

    self.assertEqual(perhost, {
      "node2": [],
      "node3": [],
      })


class TestLUClusterActivateMasterIp(CmdlibTestCase):
  def testSuccess(self):
    op = opcodes.OpClusterActivateMasterIp()

    self.rpc.call_node_activate_master_ip.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)

    self.ExecOpCode(op)

    self.rpc.call_node_activate_master_ip.assert_called_once_with(
      self.master_uuid, self.cfg.GetMasterNetworkParameters(), False)

  def testFailure(self):
    op = opcodes.OpClusterActivateMasterIp()

    self.rpc.call_node_activate_master_ip.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master) \

    self.ExecOpCodeExpectOpExecError(op)


class TestLUClusterDeactivateMasterIp(CmdlibTestCase):
  def testSuccess(self):
    op = opcodes.OpClusterDeactivateMasterIp()

    self.rpc.call_node_deactivate_master_ip.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)

    self.ExecOpCode(op)

    self.rpc.call_node_deactivate_master_ip.assert_called_once_with(
      self.master_uuid, self.cfg.GetMasterNetworkParameters(), False)

  def testFailure(self):
    op = opcodes.OpClusterDeactivateMasterIp()

    self.rpc.call_node_deactivate_master_ip.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master) \

    self.ExecOpCodeExpectOpExecError(op)


class TestLUClusterConfigQuery(CmdlibTestCase):
  def testInvalidField(self):
    op = opcodes.OpClusterConfigQuery(output_fields=["pinky_bunny"])

    self.ExecOpCodeExpectOpPrereqError(op, "pinky_bunny")

  def testAllFields(self):
    op = opcodes.OpClusterConfigQuery(output_fields=query.CLUSTER_FIELDS.keys())

    self.rpc.call_get_watcher_pause.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, -1)

    ret = self.ExecOpCode(op)

    self.assertEqual(1, self.rpc.call_get_watcher_pause.call_count)
    self.assertEqual(len(ret), len(query.CLUSTER_FIELDS))

  def testEmpytFields(self):
    op = opcodes.OpClusterConfigQuery(output_fields=[])

    self.ExecOpCode(op)

    self.assertFalse(self.rpc.call_get_watcher_pause.called)


class TestLUClusterDestroy(CmdlibTestCase):
  def testExistingNodes(self):
    op = opcodes.OpClusterDestroy()

    self.cfg.AddNewNode()
    self.cfg.AddNewNode()

    self.ExecOpCodeExpectOpPrereqError(op, "still 2 node\(s\)")

  def testExistingInstances(self):
    op = opcodes.OpClusterDestroy()

    self.cfg.AddNewInstance()
    self.cfg.AddNewInstance()

    self.ExecOpCodeExpectOpPrereqError(op, "still 2 instance\(s\)")

  def testEmptyCluster(self):
    op = opcodes.OpClusterDestroy()

    self.ExecOpCode(op)

    self.assertSingleHooksCall([self.master.name],
                               "cluster-destroy",
                               constants.HOOKS_PHASE_POST)


class TestLUClusterPostInit(CmdlibTestCase):

  @testutils.patch_object(cluster, "_UpdateMasterClientCert")
  def testExecution(self, update_client_cert_mock):
    # mock the client certificate creation as it is tested separately
    update_client_cert_mock.return_value = None
    # For the purpose of this test, return the same certificate digest for all
    # nodes
    self.rpc.call_node_crypto_tokens = \
      lambda node_uuid, _: self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(node_uuid,
          [(constants.CRYPTO_TYPE_SSL_DIGEST, "IA:MA:FA:KE:DI:GE:ST")])
    op = opcodes.OpClusterPostInit()

    self.ExecOpCode(op)

    self.assertSingleHooksCall([self.master.name],
                               "cluster-init",
                               constants.HOOKS_PHASE_POST)


class TestLUClusterQuery(CmdlibTestCase):
  def testSimpleInvocation(self):
    op = opcodes.OpClusterQuery()

    self.ExecOpCode(op)

  def testIPv6Cluster(self):
    op = opcodes.OpClusterQuery()

    self.cluster.primary_ip_family = netutils.IP6Address.family

    self.ExecOpCode(op)


class TestLUClusterRedistConf(CmdlibTestCase):
  def testSimpleInvocation(self):
    op = opcodes.OpClusterRedistConf()

    self.ExecOpCode(op)


class TestLUClusterRename(CmdlibTestCase):
  NEW_NAME = "new-name.example.com"
  NEW_IP = "203.0.113.100"

  def testNoChanges(self):
    op = opcodes.OpClusterRename(name=self.cfg.GetClusterName())

    self.ExecOpCodeExpectOpPrereqError(op, "name nor the IP address")

  def testReachableIp(self):
    op = opcodes.OpClusterRename(name=self.NEW_NAME)

    self.netutils_mod.GetHostname.return_value = \
      HostnameMock(self.NEW_NAME, self.NEW_IP)
    self.netutils_mod.TcpPing.return_value = True

    self.ExecOpCodeExpectOpPrereqError(op, "is reachable on the network")

  def testValidRename(self):
    op = opcodes.OpClusterRename(name=self.NEW_NAME)

    self.netutils_mod.GetHostname.return_value = \
      HostnameMock(self.NEW_NAME, self.NEW_IP)

    self.ExecOpCode(op)

    self.assertEqual(1, self.ssh_mod.WriteKnownHostsFile.call_count)
    self.rpc.call_node_deactivate_master_ip.assert_called_once_with(
      self.master_uuid, self.cfg.GetMasterNetworkParameters(), False)
    self.rpc.call_node_activate_master_ip.assert_called_once_with(
      self.master_uuid, self.cfg.GetMasterNetworkParameters(), False)

  def testRenameOfflineMaster(self):
    op = opcodes.OpClusterRename(name=self.NEW_NAME)

    self.master.offline = True
    self.netutils_mod.GetHostname.return_value = \
      HostnameMock(self.NEW_NAME, self.NEW_IP)

    self.ExecOpCode(op)


class TestLUClusterRepairDiskSizes(CmdlibTestCase):
  def testNoInstances(self):
    op = opcodes.OpClusterRepairDiskSizes()

    self.ExecOpCode(op)

  def _SetUpInstanceSingleDisk(self, dev_type=constants.DT_PLAIN):
    pnode = self.master
    snode = self.cfg.AddNewNode()

    disk = self.cfg.CreateDisk(dev_type=dev_type,
                               primary_node=pnode,
                               secondary_node=snode)
    inst = self.cfg.AddNewInstance(disks=[disk])

    return (inst, disk)

  def testSingleInstanceOnFailingNode(self):
    (inst, _) = self._SetUpInstanceSingleDisk()
    op = opcodes.OpClusterRepairDiskSizes(instances=[inst.name])

    self.rpc.call_blockdev_getdimensions.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master)

    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("Failure in blockdev_getdimensions")

  def _ExecOpClusterRepairDiskSizes(self, node_data):
    # not specifying instances repairs all
    op = opcodes.OpClusterRepairDiskSizes()

    self.rpc.call_blockdev_getdimensions.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, node_data)

    return self.ExecOpCode(op)

  def testInvalidResultData(self):
    for data in [[], [None], ["invalid"], [("still", "invalid")]]:
      self.ResetMocks()

      self._SetUpInstanceSingleDisk()
      self._ExecOpClusterRepairDiskSizes(data)

      self.mcpu.assertLogContainsRegex("ignoring")

  def testCorrectSize(self):
    self._SetUpInstanceSingleDisk()
    changed = self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, None)])
    self.mcpu.assertLogIsEmpty()
    self.assertEqual(0, len(changed))

  def testWrongSize(self):
    self._SetUpInstanceSingleDisk()
    changed = self._ExecOpClusterRepairDiskSizes([(512 * 1024 * 1024, None)])
    self.assertEqual(1, len(changed))

  def testCorrectDRBD(self):
    self._SetUpInstanceSingleDisk(dev_type=constants.DT_DRBD8)
    changed = self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, None)])
    self.mcpu.assertLogIsEmpty()
    self.assertEqual(0, len(changed))

  def testWrongDRBDChild(self):
    (_, disk) = self._SetUpInstanceSingleDisk(dev_type=constants.DT_DRBD8)
    disk.children[0].size = 512
    changed = self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, None)])
    self.assertEqual(1, len(changed))

  def testExclusiveStorageInvalidResultData(self):
    self._SetUpInstanceSingleDisk()
    self.master.ndparams[constants.ND_EXCLUSIVE_STORAGE] = True
    self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, None)])

    self.mcpu.assertLogContainsRegex(
      "did not return valid spindles information")

  def testExclusiveStorageCorrectSpindles(self):
    (_, disk) = self._SetUpInstanceSingleDisk()
    disk.spindles = 1
    self.master.ndparams[constants.ND_EXCLUSIVE_STORAGE] = True
    changed = self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, 1)])
    self.assertEqual(0, len(changed))

  def testExclusiveStorageWrongSpindles(self):
    self._SetUpInstanceSingleDisk()
    self.master.ndparams[constants.ND_EXCLUSIVE_STORAGE] = True
    changed = self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, 1)])
    self.assertEqual(1, len(changed))


class TestLUClusterSetParams(CmdlibTestCase):
  UID_POOL = [(10, 1000)]

  def testUidPool(self):
    op = opcodes.OpClusterSetParams(uid_pool=self.UID_POOL)
    self.ExecOpCode(op)
    self.assertEqual(self.UID_POOL, self.cluster.uid_pool)

  def testAddUids(self):
    old_pool = [(1, 9)]
    self.cluster.uid_pool = list(old_pool)
    op = opcodes.OpClusterSetParams(add_uids=self.UID_POOL)
    self.ExecOpCode(op)
    self.assertEqual(set(self.UID_POOL + old_pool),
                     set(self.cluster.uid_pool))

  def testRemoveUids(self):
    additional_pool = [(1, 9)]
    self.cluster.uid_pool = self.UID_POOL + additional_pool
    op = opcodes.OpClusterSetParams(remove_uids=self.UID_POOL)
    self.ExecOpCode(op)
    self.assertEqual(additional_pool, self.cluster.uid_pool)

  def testMasterNetmask(self):
    op = opcodes.OpClusterSetParams(master_netmask=26)
    self.ExecOpCode(op)
    self.assertEqual(26, self.cluster.master_netmask)

  def testInvalidDiskparams(self):
    for diskparams in [{constants.DT_DISKLESS: {constants.LV_STRIPES: 0}},
                       {constants.DT_DRBD8: {constants.RBD_POOL: "pool"}},
                       {constants.DT_DRBD8: {constants.RBD_ACCESS: "bunny"}}]:
      self.ResetMocks()
      op = opcodes.OpClusterSetParams(diskparams=diskparams)
      self.ExecOpCodeExpectOpPrereqError(op, "verify diskparams")

  def testValidDiskparams(self):
    diskparams = {constants.DT_RBD: {constants.RBD_POOL: "mock_pool",
                                     constants.RBD_ACCESS: "kernelspace"}}
    op = opcodes.OpClusterSetParams(diskparams=diskparams)
    self.ExecOpCode(op)
    self.assertEqual(diskparams[constants.DT_RBD],
                     self.cluster.diskparams[constants.DT_RBD])

  def testMinimalDiskparams(self):
    diskparams = {constants.DT_RBD: {constants.RBD_POOL: "mock_pool"}}
    self.cluster.diskparams = {}
    op = opcodes.OpClusterSetParams(diskparams=diskparams)
    self.ExecOpCode(op)
    self.assertEqual(diskparams, self.cluster.diskparams)

  def testValidDiskparamsAccess(self):
    for value in constants.DISK_VALID_ACCESS_MODES:
      self.ResetMocks()
      op = opcodes.OpClusterSetParams(diskparams={
        constants.DT_RBD: {constants.RBD_ACCESS: value}
      })
      self.ExecOpCode(op)
      got = self.cluster.diskparams[constants.DT_RBD][constants.RBD_ACCESS]
      self.assertEqual(value, got)

  def testInvalidDiskparamsAccess(self):
    for value in ["default", "pinky_bunny"]:
      self.ResetMocks()
      op = opcodes.OpClusterSetParams(diskparams={
        constants.DT_RBD: {constants.RBD_ACCESS: value}
      })
      self.ExecOpCodeExpectOpPrereqError(op, "Invalid value of 'rbd:access'")

  def testUnsetDrbdHelperWithDrbdDisks(self):
    self.cfg.AddNewInstance(disks=[
      self.cfg.CreateDisk(dev_type=constants.DT_DRBD8, create_nodes=True)])
    op = opcodes.OpClusterSetParams(drbd_helper="")
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot disable drbd helper")

  def testFileStorageDir(self):
    op = opcodes.OpClusterSetParams(file_storage_dir="/random/path")
    self.ExecOpCode(op)

  def testSetFileStorageDirToCurrentValue(self):
    op = opcodes.OpClusterSetParams(
           file_storage_dir=self.cluster.file_storage_dir)
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("file storage dir already set to value")

  def testUnsetFileStorageDirFileStorageEnabled(self):
    self.cfg.SetEnabledDiskTemplates([constants.DT_FILE])
    op = opcodes.OpClusterSetParams(file_storage_dir='')
    self.ExecOpCodeExpectOpPrereqError(op, "Unsetting the 'file' storage")

  def testUnsetFileStorageDirFileStorageDisabled(self):
    self.cfg.SetEnabledDiskTemplates([constants.DT_PLAIN])
    op = opcodes.OpClusterSetParams(file_storage_dir='')
    self.ExecOpCode(op)

  def testSetFileStorageDirFileStorageDisabled(self):
    self.cfg.SetEnabledDiskTemplates([constants.DT_PLAIN])
    op = opcodes.OpClusterSetParams(file_storage_dir='/some/path/')
    self.ExecOpCode(op)
    self.mcpu.assertLogContainsRegex("although file storage is not enabled")

  def testValidDrbdHelper(self):
    node1 = self.cfg.AddNewNode()
    node1.offline = True
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, "/bin/true") \
        .AddOfflineNode(node1) \
        .Build()
    op = opcodes.OpClusterSetParams(drbd_helper="/bin/true")
    self.ExecOpCode(op)
    self.mcpu.assertLogContainsRegex("Not checking drbd helper on offline node")

  def testDrbdHelperFailingNode(self):
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddFailedNode(self.master) \
        .Build()
    op = opcodes.OpClusterSetParams(drbd_helper="/bin/true")
    self.ExecOpCodeExpectOpPrereqError(op, "Error checking drbd helper")

  def testInvalidDrbdHelper(self):
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, "/bin/false") \
        .Build()
    op = opcodes.OpClusterSetParams(drbd_helper="/bin/true")
    self.ExecOpCodeExpectOpPrereqError(op, "drbd helper is /bin/false")

  def testDrbdHelperWithoutDrbdDiskTemplate(self):
    drbd_helper = "/bin/random_helper"
    self.cfg.SetEnabledDiskTemplates([constants.DT_DISKLESS])
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, drbd_helper) \
        .Build()
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("but did not enable")

  def testResetDrbdHelperDrbdDisabled(self):
    drbd_helper = ""
    self.cfg.SetEnabledDiskTemplates([constants.DT_DISKLESS])
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCode(op)

    self.assertEqual(None, self.cluster.drbd_usermode_helper)

  def testResetDrbdHelperDrbdEnabled(self):
    drbd_helper = ""
    self.cluster.enabled_disk_templates = [constants.DT_DRBD8]
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCodeExpectOpPrereqError(
        op, "Cannot disable drbd helper while DRBD is enabled.")

  def testEnableDrbdNoHelper(self):
    self.cluster.enabled_disk_templates = [constants.DT_DISKLESS]
    self.cluster.drbd_usermode_helper = None
    enabled_disk_templates = [constants.DT_DRBD8]
    op = opcodes.OpClusterSetParams(
        enabled_disk_templates=enabled_disk_templates)
    self.ExecOpCodeExpectOpPrereqError(
        op, "Cannot enable DRBD without a DRBD usermode helper set")

  def testEnableDrbdHelperSet(self):
    drbd_helper = "/bin/random_helper"
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, drbd_helper) \
        .Build()
    self.cfg.SetEnabledDiskTemplates([constants.DT_DISKLESS])
    self.cluster.drbd_usermode_helper = drbd_helper
    enabled_disk_templates = [constants.DT_DRBD8]
    op = opcodes.OpClusterSetParams(
        enabled_disk_templates=enabled_disk_templates,
        ipolicy={constants.IPOLICY_DTS: enabled_disk_templates})
    self.ExecOpCode(op)

    self.assertEqual(drbd_helper, self.cluster.drbd_usermode_helper)

  def testDrbdHelperAlreadySet(self):
    drbd_helper = "/bin/true"
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, "/bin/true") \
        .Build()
    self.cfg.SetEnabledDiskTemplates([constants.DT_DISKLESS])
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCode(op)

    self.assertEqual(drbd_helper, self.cluster.drbd_usermode_helper)
    self.mcpu.assertLogContainsRegex("DRBD helper already in desired state")

  def testSetDrbdHelper(self):
    drbd_helper = "/bin/true"
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, "/bin/true") \
        .Build()
    self.cluster.drbd_usermode_helper = "/bin/false"
    self.cfg.SetEnabledDiskTemplates([constants.DT_DRBD8])
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCode(op)

    self.assertEqual(drbd_helper, self.cluster.drbd_usermode_helper)

  def testBeparams(self):
    beparams = {constants.BE_VCPUS: 32}
    op = opcodes.OpClusterSetParams(beparams=beparams)
    self.ExecOpCode(op)
    self.assertEqual(32, self.cluster
                           .beparams[constants.PP_DEFAULT][constants.BE_VCPUS])

  def testNdparams(self):
    ndparams = {constants.ND_EXCLUSIVE_STORAGE: True}
    op = opcodes.OpClusterSetParams(ndparams=ndparams)
    self.ExecOpCode(op)
    self.assertEqual(True, self.cluster
                             .ndparams[constants.ND_EXCLUSIVE_STORAGE])

  def testNdparamsResetOobProgram(self):
    ndparams = {constants.ND_OOB_PROGRAM: ""}
    op = opcodes.OpClusterSetParams(ndparams=ndparams)
    self.ExecOpCode(op)
    self.assertEqual(constants.NDC_DEFAULTS[constants.ND_OOB_PROGRAM],
                     self.cluster.ndparams[constants.ND_OOB_PROGRAM])

  def testHvState(self):
    hv_state = {constants.HT_FAKE: {constants.HVST_CPU_TOTAL: 8}}
    op = opcodes.OpClusterSetParams(hv_state=hv_state)
    self.ExecOpCode(op)
    self.assertEqual(8, self.cluster.hv_state_static
                          [constants.HT_FAKE][constants.HVST_CPU_TOTAL])

  def testDiskState(self):
    disk_state = {
      constants.DT_PLAIN: {
        "mock_vg": {constants.DS_DISK_TOTAL: 10}
      }
    }
    op = opcodes.OpClusterSetParams(disk_state=disk_state)
    self.ExecOpCode(op)
    self.assertEqual(10, self.cluster
                           .disk_state_static[constants.DT_PLAIN]["mock_vg"]
                             [constants.DS_DISK_TOTAL])

  def testDefaultIPolicy(self):
    ipolicy = constants.IPOLICY_DEFAULTS
    op = opcodes.OpClusterSetParams(ipolicy=ipolicy)
    self.ExecOpCode(op)

  def testIPolicyNewViolation(self):
    import ganeti.constants as C
    ipolicy = C.IPOLICY_DEFAULTS
    ipolicy[C.ISPECS_MINMAX][0][C.ISPECS_MIN][C.ISPEC_MEM_SIZE] = 128
    ipolicy[C.ISPECS_MINMAX][0][C.ISPECS_MAX][C.ISPEC_MEM_SIZE] = 128

    self.cfg.AddNewInstance(beparams={C.BE_MINMEM: 512, C.BE_MAXMEM: 512})
    op = opcodes.OpClusterSetParams(ipolicy=ipolicy)
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("instances violate them")

  def testNicparamsNoInstance(self):
    nicparams = {
      constants.NIC_LINK: "mock_bridge"
    }
    op = opcodes.OpClusterSetParams(nicparams=nicparams)
    self.ExecOpCode(op)

    self.assertEqual("mock_bridge",
                     self.cluster.nicparams
                       [constants.PP_DEFAULT][constants.NIC_LINK])

  def testNicparamsInvalidConf(self):
    nicparams = {
      constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
      constants.NIC_LINK: ""
    }
    op = opcodes.OpClusterSetParams(nicparams=nicparams)
    self.ExecOpCodeExpectException(op, errors.ConfigurationError, "NIC link")

  def testNicparamsInvalidInstanceConf(self):
    nicparams = {
      constants.NIC_MODE: constants.NIC_MODE_BRIDGED,
      constants.NIC_LINK: "mock_bridge"
    }
    self.cfg.AddNewInstance(nics=[
      self.cfg.CreateNic(nicparams={constants.NIC_LINK: None})])
    op = opcodes.OpClusterSetParams(nicparams=nicparams)
    self.ExecOpCodeExpectOpPrereqError(op, "Missing bridged NIC link")

  def testNicparamsMissingIp(self):
    nicparams = {
      constants.NIC_MODE: constants.NIC_MODE_ROUTED
    }
    self.cfg.AddNewInstance()
    op = opcodes.OpClusterSetParams(nicparams=nicparams)
    self.ExecOpCodeExpectOpPrereqError(op, "routed NIC with no ip address")

  def testNicparamsWithInstance(self):
    nicparams = {
      constants.NIC_LINK: "mock_bridge"
    }
    self.cfg.AddNewInstance()
    op = opcodes.OpClusterSetParams(nicparams=nicparams)
    self.ExecOpCode(op)

  def testDefaultHvparams(self):
    hvparams = constants.HVC_DEFAULTS
    op = opcodes.OpClusterSetParams(hvparams=hvparams)
    self.ExecOpCode(op)

    self.assertEqual(hvparams, self.cluster.hvparams)

  def testMinimalHvparams(self):
    hvparams = {
      constants.HT_FAKE: {
        constants.HV_MIGRATION_MODE: constants.HT_MIGRATION_NONLIVE
      }
    }
    self.cluster.hvparams = {}
    op = opcodes.OpClusterSetParams(hvparams=hvparams)
    self.ExecOpCode(op)

    self.assertEqual(hvparams, self.cluster.hvparams)

  def testOsHvp(self):
    os_hvp = {
      "mocked_os": {
        constants.HT_FAKE: {
          constants.HV_MIGRATION_MODE: constants.HT_MIGRATION_NONLIVE
        }
      },
      "other_os": constants.HVC_DEFAULTS
    }
    op = opcodes.OpClusterSetParams(os_hvp=os_hvp)
    self.ExecOpCode(op)

    self.assertEqual(constants.HT_MIGRATION_NONLIVE,
                     self.cluster.os_hvp["mocked_os"][constants.HT_FAKE]
                       [constants.HV_MIGRATION_MODE])
    self.assertEqual(constants.HVC_DEFAULTS, self.cluster.os_hvp["other_os"])

  def testRemoveOsHvp(self):
    os_hvp = {"mocked_os": {constants.HT_FAKE: None}}
    op = opcodes.OpClusterSetParams(os_hvp=os_hvp)
    self.ExecOpCode(op)

    assert constants.HT_FAKE not in self.cluster.os_hvp["mocked_os"]

  def testDefaultOsHvp(self):
    os_hvp = {"mocked_os": constants.HVC_DEFAULTS.copy()}
    self.cluster.os_hvp = {"mocked_os": {}}
    op = opcodes.OpClusterSetParams(os_hvp=os_hvp)
    self.ExecOpCode(op)

    self.assertEqual(os_hvp, self.cluster.os_hvp)

  def testOsparams(self):
    osparams = {
      "mocked_os": {
        "param1": "value1",
        "param2": None
      },
      "other_os": {
        "param1": None
      }
    }
    self.cluster.osparams = {"other_os": {"param1": "value1"}}
    self.cluster.osparams_private_cluster = {}
    op = opcodes.OpClusterSetParams(osparams=osparams)
    self.ExecOpCode(op)

    self.assertEqual({"mocked_os": {"param1": "value1"}}, self.cluster.osparams)

  def testEnabledHypervisors(self):
    enabled_hypervisors = [constants.HT_XEN_HVM, constants.HT_XEN_PVM]
    op = opcodes.OpClusterSetParams(enabled_hypervisors=enabled_hypervisors)
    self.ExecOpCode(op)

    self.assertEqual(enabled_hypervisors, self.cluster.enabled_hypervisors)

  def testEnabledHypervisorsWithoutHypervisorParams(self):
    enabled_hypervisors = [constants.HT_FAKE]
    self.cluster.hvparams = {}
    op = opcodes.OpClusterSetParams(enabled_hypervisors=enabled_hypervisors)
    self.ExecOpCode(op)

    self.assertEqual(enabled_hypervisors, self.cluster.enabled_hypervisors)
    self.assertEqual(constants.HVC_DEFAULTS[constants.HT_FAKE],
                     self.cluster.hvparams[constants.HT_FAKE])

  @testutils.patch_object(utils, "FindFile")
  def testValidDefaultIallocator(self, find_file_mock):
    find_file_mock.return_value = "/random/path"
    default_iallocator = "/random/path"
    op = opcodes.OpClusterSetParams(default_iallocator=default_iallocator)
    self.ExecOpCode(op)

    self.assertEqual(default_iallocator, self.cluster.default_iallocator)

  @testutils.patch_object(utils, "FindFile")
  def testInvalidDefaultIallocator(self, find_file_mock):
    find_file_mock.return_value = None
    default_iallocator = "/random/path"
    op = opcodes.OpClusterSetParams(default_iallocator=default_iallocator)
    self.ExecOpCodeExpectOpPrereqError(op, "Invalid default iallocator script")

  def testEnabledDiskTemplates(self):
    enabled_disk_templates = [constants.DT_DISKLESS, constants.DT_PLAIN]
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=enabled_disk_templates,
           ipolicy={constants.IPOLICY_DTS: enabled_disk_templates})
    self.ExecOpCode(op)

    self.assertEqual(enabled_disk_templates,
                     self.cluster.enabled_disk_templates)

  def testEnabledDiskTemplatesVsIpolicy(self):
    enabled_disk_templates = [constants.DT_DISKLESS, constants.DT_PLAIN]
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=enabled_disk_templates,
           ipolicy={constants.IPOLICY_DTS: [constants.DT_FILE]})
    self.ExecOpCodeExpectOpPrereqError(op, "but not enabled on the cluster")

  def testDisablingDiskTemplatesOfInstances(self):
    old_disk_templates = [constants.DT_DISKLESS, constants.DT_PLAIN]
    self.cfg.SetEnabledDiskTemplates(old_disk_templates)
    self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.DT_PLAIN)])
    new_disk_templates = [constants.DT_DISKLESS, constants.DT_DRBD8]
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=new_disk_templates,
           ipolicy={constants.IPOLICY_DTS: new_disk_templates})
    self.ExecOpCodeExpectOpPrereqError(op, "least one instance using it")

  def testEnabledDiskTemplatesWithoutVgName(self):
    enabled_disk_templates = [constants.DT_PLAIN]
    self.cluster.volume_group_name = None
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=enabled_disk_templates)
    self.ExecOpCodeExpectOpPrereqError(op, "specify a volume group")

  def testDisableDiskTemplateWithExistingInstance(self):
    enabled_disk_templates = [constants.DT_DISKLESS]
    self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.DT_PLAIN)])
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=enabled_disk_templates,
           ipolicy={constants.IPOLICY_DTS: enabled_disk_templates})
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot disable disk template")

  def testVgNameNoLvmDiskTemplateEnabled(self):
    vg_name = "test_vg"
    self.cfg.SetEnabledDiskTemplates([constants.DT_DISKLESS])
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCode(op)

    self.assertEqual(vg_name, self.cluster.volume_group_name)
    self.mcpu.assertLogIsEmpty()

  def testUnsetVgNameWithLvmDiskTemplateEnabled(self):
    vg_name = ""
    self.cluster.enabled_disk_templates = [constants.DT_PLAIN]
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot unset volume group")

  def testUnsetVgNameWithLvmInstance(self):
    vg_name = ""
    self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.DT_PLAIN)])
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot unset volume group")

  def testUnsetVgNameWithNoLvmDiskTemplateEnabled(self):
    vg_name = ""
    self.cfg.SetEnabledDiskTemplates([constants.DT_DISKLESS])
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCode(op)

    self.assertEqual(None, self.cluster.volume_group_name)

  def testVgNameToOldName(self):
    vg_name = self.cluster.volume_group_name
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("already in desired state")

  def testVgNameWithFailingNode(self):
    vg_name = "test_vg"
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.rpc.call_vg_list.return_value = \
      self.RpcResultsBuilder() \
        .AddFailedNode(self.master) \
        .Build()
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("Error while gathering data on node")

  def testVgNameWithValidNode(self):
    vg_name = "test_vg"
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.rpc.call_vg_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {vg_name: 1024 * 1024}) \
        .Build()
    self.ExecOpCode(op)

  def testVgNameWithTooSmallNode(self):
    vg_name = "test_vg"
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.rpc.call_vg_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {vg_name: 1}) \
        .Build()
    self.ExecOpCodeExpectOpPrereqError(op, "too small")

  def testMiscParameters(self):
    op = opcodes.OpClusterSetParams(candidate_pool_size=123,
                                    maintain_node_health=True,
                                    modify_etc_hosts=True,
                                    prealloc_wipe_disks=True,
                                    reserved_lvs=["/dev/mock_lv"],
                                    use_external_mip_script=True)
    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()
    self.assertEqual(123, self.cluster.candidate_pool_size)
    self.assertEqual(True, self.cluster.maintain_node_health)
    self.assertEqual(True, self.cluster.modify_etc_hosts)
    self.assertEqual(True, self.cluster.prealloc_wipe_disks)
    self.assertEqual(["/dev/mock_lv"], self.cluster.reserved_lvs)
    self.assertEqual(True, self.cluster.use_external_mip_script)

  def testAddHiddenOs(self):
    self.cluster.hidden_os = ["hidden1", "hidden2"]
    op = opcodes.OpClusterSetParams(hidden_os=[(constants.DDM_ADD, "hidden2"),
                                               (constants.DDM_ADD, "hidden3")])
    self.ExecOpCode(op)

    self.assertEqual(["hidden1", "hidden2", "hidden3"], self.cluster.hidden_os)
    self.mcpu.assertLogContainsRegex("OS hidden2 already")

  def testRemoveBlacklistedOs(self):
    self.cluster.blacklisted_os = ["blisted1", "blisted2"]
    op = opcodes.OpClusterSetParams(blacklisted_os=[
                                      (constants.DDM_REMOVE, "blisted2"),
                                      (constants.DDM_REMOVE, "blisted3")])
    self.ExecOpCode(op)

    self.assertEqual(["blisted1"], self.cluster.blacklisted_os)
    self.mcpu.assertLogContainsRegex("OS blisted3 not found")

  def testMasterNetdev(self):
    master_netdev = "test_dev"
    op = opcodes.OpClusterSetParams(master_netdev=master_netdev)
    self.ExecOpCode(op)

    self.assertEqual(master_netdev, self.cluster.master_netdev)

  def testMasterNetdevFailNoForce(self):
    master_netdev = "test_dev"
    op = opcodes.OpClusterSetParams(master_netdev=master_netdev)
    self.rpc.call_node_deactivate_master_ip.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master)
    self.ExecOpCodeExpectOpExecError(op, "Could not disable the master ip")

  def testMasterNetdevFailForce(self):
    master_netdev = "test_dev"
    op = opcodes.OpClusterSetParams(master_netdev=master_netdev,
                                    force=True)
    self.rpc.call_node_deactivate_master_ip.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master)
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("Could not disable the master ip")


class TestLUClusterVerify(CmdlibTestCase):
  def testVerifyAllGroups(self):
    op = opcodes.OpClusterVerify()
    result = self.ExecOpCode(op)

    self.assertEqual(2, len(result["jobs"]))

  def testVerifyDefaultGroups(self):
    op = opcodes.OpClusterVerify(group_name="default")
    result = self.ExecOpCode(op)

    self.assertEqual(1, len(result["jobs"]))


class TestLUClusterVerifyConfig(CmdlibTestCase):

  def setUp(self):
    super(TestLUClusterVerifyConfig, self).setUp()

    self._load_cert_patcher = testutils \
      .patch_object(OpenSSL.crypto, "load_certificate")
    self._load_cert_mock = self._load_cert_patcher.start()
    self._verify_cert_patcher = testutils \
      .patch_object(utils, "VerifyCertificate")
    self._verify_cert_mock = self._verify_cert_patcher.start()
    self._read_file_patcher = testutils.patch_object(utils, "ReadFile")
    self._read_file_mock = self._read_file_patcher.start()
    self._can_read_patcher = testutils.patch_object(utils, "CanRead")
    self._can_read_mock = self._can_read_patcher.start()

    self._can_read_mock.return_value = True
    self._read_file_mock.return_value = True
    self._verify_cert_mock.return_value = (None, "")
    self._load_cert_mock.return_value = True

  def tearDown(self):
    super(TestLUClusterVerifyConfig, self).tearDown()

    self._can_read_patcher.stop()
    self._read_file_patcher.stop()
    self._verify_cert_patcher.stop()
    self._load_cert_patcher.stop()

  def testSuccessfulRun(self):
    self.cfg.AddNewInstance()
    op = opcodes.OpClusterVerifyConfig()
    result = self.ExecOpCode(op)
    self.assertTrue(result)

  def testDanglingNode(self):
    node = self.cfg.AddNewNode()
    self.cfg.AddNewInstance(primary_node=node)
    node.group = "invalid"
    op = opcodes.OpClusterVerifyConfig()
    result = self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex(
      "following nodes \(and their instances\) belong to a non existing group")
    self.assertFalse(result)

  def testDanglingInstance(self):
    inst = self.cfg.AddNewInstance()
    inst.primary_node = "invalid"
    op = opcodes.OpClusterVerifyConfig()
    result = self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex(
      "following instances have a non-existing primary-node")
    self.assertFalse(result)


class TestLUClusterVerifyGroup(CmdlibTestCase):
  def testEmptyNodeGroup(self):
    group = self.cfg.AddNewNodeGroup()
    op = opcodes.OpClusterVerifyGroup(group_name=group.name, verbose=True)

    result = self.ExecOpCode(op)

    self.assertTrue(result)
    self.mcpu.assertLogContainsRegex("Empty node group, skipping verification")

  def testSimpleInvocation(self):
    op = opcodes.OpClusterVerifyGroup(group_name="default", verbose=True)

    self.ExecOpCode(op)

  def testSimpleInvocationWithInstance(self):
    self.cfg.AddNewInstance(disks=[])
    op = opcodes.OpClusterVerifyGroup(group_name="default", verbose=True)

    self.ExecOpCode(op)

  def testGhostNode(self):
    group = self.cfg.AddNewNodeGroup()
    node = self.cfg.AddNewNode(group=group.uuid, offline=True)
    self.master.offline = True
    self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                            primary_node=self.master,
                            secondary_node=node)

    self.rpc.call_blockdev_getmirrorstatus_multi.return_value = \
      RpcResultsBuilder() \
        .AddOfflineNode(self.master) \
        .Build()

    op = opcodes.OpClusterVerifyGroup(group_name="default", verbose=True)

    self.ExecOpCode(op)

  def testValidRpcResult(self):
    self.cfg.AddNewInstance(disks=[])

    self.rpc.call_node_verify.return_value = \
      RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {}) \
        .Build()

    op = opcodes.OpClusterVerifyGroup(group_name="default", verbose=True)

    self.ExecOpCode(op)


class TestLUClusterVerifyGroupMethods(CmdlibTestCase):
  """Base class for testing individual methods in LUClusterVerifyGroup.

  """
  def setUp(self):
    super(TestLUClusterVerifyGroupMethods, self).setUp()
    self.op = opcodes.OpClusterVerifyGroup(group_name="default")

  def PrepareLU(self, lu):
    lu._exclusive_storage = False
    lu.master_node = self.master_uuid
    lu.group_info = self.group
    cluster.LUClusterVerifyGroup.all_node_info = \
      property(fget=lambda _: self.cfg.GetAllNodesInfo())


class TestLUClusterVerifyGroupVerifyNode(TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testInvalidNodeResult(self, lu):
    self.assertFalse(lu._VerifyNode(self.master, None))
    self.assertFalse(lu._VerifyNode(self.master, ""))

  @withLockedLU
  def testInvalidVersion(self, lu):
    self.assertFalse(lu._VerifyNode(self.master, {"version": None}))
    self.assertFalse(lu._VerifyNode(self.master, {"version": ""}))
    self.assertFalse(lu._VerifyNode(self.master, {
      "version": (constants.PROTOCOL_VERSION - 1, constants.RELEASE_VERSION)
    }))

    self.mcpu.ClearLogMessages()
    self.assertTrue(lu._VerifyNode(self.master, {
      "version": (constants.PROTOCOL_VERSION, constants.RELEASE_VERSION + "x")
    }))
    self.mcpu.assertLogContainsRegex("software version mismatch")

  def _GetValidNodeResult(self, additional_fields):
    ret = {
      "version": (constants.PROTOCOL_VERSION, constants.RELEASE_VERSION),
      constants.NV_NODESETUP: []
    }
    ret.update(additional_fields)
    return ret

  @withLockedLU
  def testHypervisor(self, lu):
    lu._VerifyNode(self.master, self._GetValidNodeResult({
      constants.NV_HYPERVISOR: {
        constants.HT_XEN_PVM: None,
        constants.HT_XEN_HVM: "mock error"
      }
    }))
    self.mcpu.assertLogContainsRegex(constants.HT_XEN_HVM)
    self.mcpu.assertLogContainsRegex("mock error")

  @withLockedLU
  def testHvParams(self, lu):
    lu._VerifyNode(self.master, self._GetValidNodeResult({
      constants.NV_HVPARAMS: [("mock item", constants.HT_XEN_HVM, "mock error")]
    }))
    self.mcpu.assertLogContainsRegex(constants.HT_XEN_HVM)
    self.mcpu.assertLogContainsRegex("mock item")
    self.mcpu.assertLogContainsRegex("mock error")

  @withLockedLU
  def testSuccessfulResult(self, lu):
    self.assertTrue(lu._VerifyNode(self.master, self._GetValidNodeResult({})))
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupVerifyNodeTime(TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testInvalidNodeResult(self, lu):
    for ndata in [{}, {constants.NV_TIME: "invalid"}]:
      self.mcpu.ClearLogMessages()
      lu._VerifyNodeTime(self.master, ndata, None, None)

      self.mcpu.assertLogContainsRegex("Node returned invalid time")

  @withLockedLU
  def testNodeDiverges(self, lu):
    for ntime in [(0, 0), (2000, 0)]:
      self.mcpu.ClearLogMessages()
      lu._VerifyNodeTime(self.master, {constants.NV_TIME: ntime}, 1000, 1005)

      self.mcpu.assertLogContainsRegex("Node time diverges")

  @withLockedLU
  def testSuccessfulResult(self, lu):
    lu._VerifyNodeTime(self.master, {constants.NV_TIME: (0, 0)}, 0, 5)
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupUpdateVerifyNodeLVM(
        TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupUpdateVerifyNodeLVM, self).setUp()
    self.VALID_NRESULT = {
      constants.NV_VGLIST: {"mock_vg": 30000},
      constants.NV_PVLIST: [
        {
          "name": "mock_pv",
          "vg_name": "mock_vg",
          "size": 5000,
          "free": 2500,
          "attributes": [],
          "lv_list": []
        }
      ]
    }

  @withLockedLU
  def testNoVgName(self, lu):
    lu._UpdateVerifyNodeLVM(self.master, {}, None, None)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testEmptyNodeResult(self, lu):
    lu._UpdateVerifyNodeLVM(self.master, {}, "mock_vg", None)
    self.mcpu.assertLogContainsRegex("unable to check volume groups")
    self.mcpu.assertLogContainsRegex("Can't get PV list from node")

  @withLockedLU
  def testValidNodeResult(self, lu):
    lu._UpdateVerifyNodeLVM(self.master, self.VALID_NRESULT, "mock_vg", None)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testValidNodeResultExclusiveStorage(self, lu):
    lu._exclusive_storage = True
    lu._UpdateVerifyNodeLVM(self.master, self.VALID_NRESULT, "mock_vg",
                            cluster.LUClusterVerifyGroup.NodeImage())
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupVerifyGroupDRBDVersion(
        TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testEmptyNodeResult(self, lu):
    lu._VerifyGroupDRBDVersion({})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testValidNodeResult(self, lu):
    lu._VerifyGroupDRBDVersion(
      RpcResultsBuilder()
        .AddSuccessfulNode(self.master, {
          constants.NV_DRBDVERSION: "8.3.0"
        })
        .Build())
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testDifferentVersions(self, lu):
    node1 = self.cfg.AddNewNode()
    lu._VerifyGroupDRBDVersion(
      RpcResultsBuilder()
        .AddSuccessfulNode(self.master, {
          constants.NV_DRBDVERSION: "8.3.0"
        })
        .AddSuccessfulNode(node1, {
          constants.NV_DRBDVERSION: "8.4.0"
        })
        .Build())
    self.mcpu.assertLogContainsRegex("DRBD version mismatch: 8.3.0")
    self.mcpu.assertLogContainsRegex("DRBD version mismatch: 8.4.0")


class TestLUClusterVerifyGroupVerifyGroupLVM(TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testNoVgName(self, lu):
    lu._VerifyGroupLVM(None, None)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testNoExclusiveStorage(self, lu):
    lu._VerifyGroupLVM(None, "mock_vg")
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testNoPvInfo(self, lu):
    lu._exclusive_storage = True
    nimg = cluster.LUClusterVerifyGroup.NodeImage()
    lu._VerifyGroupLVM({self.master.uuid: nimg}, "mock_vg")
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testValidPvInfos(self, lu):
    lu._exclusive_storage = True
    node2 = self.cfg.AddNewNode()
    nimg1 = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master.uuid)
    nimg1.pv_min = 10000
    nimg1.pv_max = 10010
    nimg2 = cluster.LUClusterVerifyGroup.NodeImage(uuid=node2.uuid)
    nimg2.pv_min = 9998
    nimg2.pv_max = 10005
    lu._VerifyGroupLVM({self.master.uuid: nimg1, node2.uuid: nimg2}, "mock_vg")
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupVerifyNodeBridges(
        TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testNoBridges(self, lu):
    lu._VerifyNodeBridges(None, None, None)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testInvalidBridges(self, lu):
    for ndata in [{}, {constants.NV_BRIDGES: ""}]:
      self.mcpu.ClearLogMessages()
      lu._VerifyNodeBridges(self.master, ndata, ["mock_bridge"])
      self.mcpu.assertLogContainsRegex("not return valid bridge information")

    self.mcpu.ClearLogMessages()
    lu._VerifyNodeBridges(self.master, {constants.NV_BRIDGES: ["mock_bridge"]},
                          ["mock_bridge"])
    self.mcpu.assertLogContainsRegex("missing bridge")


class TestLUClusterVerifyGroupVerifyNodeUserScripts(
        TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testNoUserScripts(self, lu):
    lu._VerifyNodeUserScripts(self.master, {})
    self.mcpu.assertLogContainsRegex("did not return user scripts information")

  @withLockedLU
  def testBrokenUserScripts(self, lu):
    lu._VerifyNodeUserScripts(self.master,
                              {constants.NV_USERSCRIPTS: ["script"]})
    self.mcpu.assertLogContainsRegex("scripts not present or not executable")


class TestLUClusterVerifyGroupVerifyNodeNetwork(
        TestLUClusterVerifyGroupMethods):

  def setUp(self):
    super(TestLUClusterVerifyGroupVerifyNodeNetwork, self).setUp()
    self.VALID_NRESULT = {
      constants.NV_NODELIST: {},
      constants.NV_NODENETTEST: {},
      constants.NV_MASTERIP: True
    }

  @withLockedLU
  def testEmptyNodeResult(self, lu):
    lu._VerifyNodeNetwork(self.master, {})
    self.mcpu.assertLogContainsRegex(
      "node hasn't returned node ssh connectivity data")
    self.mcpu.assertLogContainsRegex(
      "node hasn't returned node tcp connectivity data")
    self.mcpu.assertLogContainsRegex(
      "node hasn't returned node master IP reachability data")

  @withLockedLU
  def testValidResult(self, lu):
    lu._VerifyNodeNetwork(self.master, self.VALID_NRESULT)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testSshProblem(self, lu):
    self.VALID_NRESULT.update({
      constants.NV_NODELIST: {
        "mock_node": "mock_error"
      }
    })
    lu._VerifyNodeNetwork(self.master, self.VALID_NRESULT)
    self.mcpu.assertLogContainsRegex("ssh communication with node 'mock_node'")

  @withLockedLU
  def testTcpProblem(self, lu):
    self.VALID_NRESULT.update({
      constants.NV_NODENETTEST: {
        "mock_node": "mock_error"
      }
    })
    lu._VerifyNodeNetwork(self.master, self.VALID_NRESULT)
    self.mcpu.assertLogContainsRegex("tcp communication with node 'mock_node'")

  @withLockedLU
  def testMasterIpNotReachable(self, lu):
    self.VALID_NRESULT.update({
      constants.NV_MASTERIP: False
    })
    node1 = self.cfg.AddNewNode()
    lu._VerifyNodeNetwork(self.master, self.VALID_NRESULT)
    self.mcpu.assertLogContainsRegex(
      "the master node cannot reach the master IP")

    self.mcpu.ClearLogMessages()
    lu._VerifyNodeNetwork(node1, self.VALID_NRESULT)
    self.mcpu.assertLogContainsRegex("cannot reach the master IP")


class TestLUClusterVerifyGroupVerifyInstance(TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupVerifyInstance, self).setUp()

    self.node1 = self.cfg.AddNewNode()
    self.drbd_inst = self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                                 primary_node=self.master,
                                 secondary_node=self.node1)])
    self.running_inst = self.cfg.AddNewInstance(
      admin_state=constants.ADMINST_UP, disks_active=True)
    self.diskless_inst = self.cfg.AddNewInstance(disks=[])

    self.master_img = \
      cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)
    self.master_img.volumes = ["/".join(disk.logical_id)
                               for inst in [self.running_inst,
                                            self.diskless_inst]
                               for disk in inst.disks]
    self.master_img.volumes.extend(
      ["/".join(disk.logical_id) for disk in self.drbd_inst.disks[0].children])
    self.master_img.instances = [self.running_inst.uuid]
    self.node1_img = \
      cluster.LUClusterVerifyGroup.NodeImage(uuid=self.node1.uuid)
    self.node1_img.volumes = \
      ["/".join(disk.logical_id) for disk in self.drbd_inst.disks[0].children]
    self.node_imgs = {
      self.master_uuid: self.master_img,
      self.node1.uuid: self.node1_img
    }
    self.diskstatus = {
      self.master_uuid: [
        (True, objects.BlockDevStatus(ldisk_status=constants.LDS_OKAY))
        for _ in self.running_inst.disks
      ]
    }

  @withLockedLU
  def testDisklessInst(self, lu):
    lu._VerifyInstance(self.diskless_inst, self.node_imgs, {})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testOfflineNode(self, lu):
    self.master_img.offline = True
    lu._VerifyInstance(self.drbd_inst, self.node_imgs, {})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testRunningOnOfflineNode(self, lu):
    self.master_img.offline = True
    lu._VerifyInstance(self.running_inst, self.node_imgs, {})
    self.mcpu.assertLogContainsRegex(
      "instance is marked as running and lives on offline node")

  @withLockedLU
  def testMissingVolume(self, lu):
    self.master_img.volumes = []
    lu._VerifyInstance(self.running_inst, self.node_imgs, {})
    self.mcpu.assertLogContainsRegex("volume .* missing")

  @withLockedLU
  def testRunningInstanceOnWrongNode(self, lu):
    self.master_img.instances = []
    self.diskless_inst.admin_state = constants.ADMINST_UP
    lu._VerifyInstance(self.running_inst, self.node_imgs, {})
    self.mcpu.assertLogContainsRegex("instance not running on its primary node")

  @withLockedLU
  def testRunningInstanceOnRightNode(self, lu):
    self.master_img.instances = [self.running_inst.uuid]
    lu._VerifyInstance(self.running_inst, self.node_imgs, {})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testValidDiskStatus(self, lu):
    lu._VerifyInstance(self.running_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testDegradedDiskStatus(self, lu):
    self.diskstatus[self.master_uuid][0][1].is_degraded = True
    lu._VerifyInstance(self.running_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogContainsRegex("instance .* is degraded")

  @withLockedLU
  def testNotOkayDiskStatus(self, lu):
    self.diskstatus[self.master_uuid][0][1].ldisk_status = constants.LDS_FAULTY
    lu._VerifyInstance(self.running_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogContainsRegex("instance .* state is 'faulty'")

  @withLockedLU
  def testExclusiveStorageWithInvalidInstance(self, lu):
    self.master.ndparams[constants.ND_EXCLUSIVE_STORAGE] = True
    lu._VerifyInstance(self.drbd_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogContainsRegex(
      "instance has template drbd, which is not supported")

  @withLockedLU
  def testExclusiveStorageWithValidInstance(self, lu):
    self.master.ndparams[constants.ND_EXCLUSIVE_STORAGE] = True
    self.running_inst.disks[0].spindles = 1
    lu._VerifyInstance(self.running_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testDrbdInTwoGroups(self, lu):
    group = self.cfg.AddNewNodeGroup()
    self.node1.group = group.uuid
    lu._VerifyInstance(self.drbd_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogContainsRegex(
      "instance has primary and secondary nodes in different groups")

  @withLockedLU
  def testOfflineSecondary(self, lu):
    self.node1_img.offline = True
    lu._VerifyInstance(self.drbd_inst, self.node_imgs, self.diskstatus)
    self.mcpu.assertLogContainsRegex("instance has offline secondary node\(s\)")


class TestLUClusterVerifyGroupVerifyOrphanVolumes(
        TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testOrphanedVolume(self, lu):
    master_img = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)
    master_img.volumes = ["mock_vg/disk_0", "mock_vg/disk_1", "mock_vg/disk_2"]
    node_imgs = {
      self.master_uuid: master_img
    }
    node_vol_should = {
      self.master_uuid: ["mock_vg/disk_0"]
    }

    lu._VerifyOrphanVolumes(node_vol_should, node_imgs,
                            utils.FieldSet("mock_vg/disk_2"))
    self.mcpu.assertLogContainsRegex("volume mock_vg/disk_1 is unknown")
    self.mcpu.assertLogDoesNotContainRegex("volume mock_vg/disk_0 is unknown")
    self.mcpu.assertLogDoesNotContainRegex("volume mock_vg/disk_2 is unknown")


class TestLUClusterVerifyGroupVerifyNPlusOneMemory(
        TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testN1Failure(self, lu):
    group1 = self.cfg.AddNewNodeGroup()

    node1 = self.cfg.AddNewNode()
    node2 = self.cfg.AddNewNode(group=group1)
    node3 = self.cfg.AddNewNode()

    inst1 = self.cfg.AddNewInstance()
    inst2 = self.cfg.AddNewInstance()
    inst3 = self.cfg.AddNewInstance()

    node1_img = cluster.LUClusterVerifyGroup.NodeImage(uuid=node1.uuid)
    node1_img.sbp = {
      self.master_uuid: [inst1.uuid, inst2.uuid, inst3.uuid]
    }

    node2_img = cluster.LUClusterVerifyGroup.NodeImage(uuid=node2.uuid)

    node3_img = cluster.LUClusterVerifyGroup.NodeImage(uuid=node3.uuid)
    node3_img.offline = True

    node_imgs = {
      node1.uuid: node1_img,
      node2.uuid: node2_img,
      node3.uuid: node3_img
    }

    lu._VerifyNPlusOneMemory(node_imgs, self.cfg.GetAllInstancesInfo())
    self.mcpu.assertLogContainsRegex(
      "not enough memory to accomodate instance failovers")

    self.mcpu.ClearLogMessages()
    node1_img.mfree = 1000
    lu._VerifyNPlusOneMemory(node_imgs, self.cfg.GetAllInstancesInfo())
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupVerifyFiles(TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def test(self, lu):
    node1 = self.cfg.AddNewNode(master_candidate=False, offline=False,
                                vm_capable=True)
    node2 = self.cfg.AddNewNode(master_candidate=True, vm_capable=False)
    node3 = self.cfg.AddNewNode(master_candidate=False, offline=False,
                                vm_capable=True)
    node4 = self.cfg.AddNewNode(master_candidate=False, offline=False,
                                vm_capable=True)
    node5 = self.cfg.AddNewNode(master_candidate=False, offline=True)

    nodeinfo = [self.master, node1, node2, node3, node4, node5]
    files_all = set([
      pathutils.CLUSTER_DOMAIN_SECRET_FILE,
      pathutils.RAPI_CERT_FILE,
      pathutils.RAPI_USERS_FILE,
      ])
    files_opt = set([
      pathutils.RAPI_USERS_FILE,
      hv_xen.XL_CONFIG_FILE,
      pathutils.VNC_PASSWORD_FILE,
      ])
    files_mc = set([
      pathutils.CLUSTER_CONF_FILE,
      ])
    files_vm = set([
      hv_xen.XEND_CONFIG_FILE,
      hv_xen.XL_CONFIG_FILE,
      pathutils.VNC_PASSWORD_FILE,
      ])
    nvinfo = RpcResultsBuilder() \
      .AddSuccessfulNode(self.master, {
        constants.NV_FILELIST: {
          pathutils.CLUSTER_CONF_FILE: "82314f897f38b35f9dab2f7c6b1593e0",
          pathutils.RAPI_CERT_FILE: "babbce8f387bc082228e544a2146fee4",
          pathutils.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          hv_xen.XEND_CONFIG_FILE: "b4a8a824ab3cac3d88839a9adeadf310",
          hv_xen.XL_CONFIG_FILE: "77935cee92afd26d162f9e525e3d49b9"
        }}) \
      .AddSuccessfulNode(node1, {
        constants.NV_FILELIST: {
          pathutils.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          hv_xen.XEND_CONFIG_FILE: "b4a8a824ab3cac3d88839a9adeadf310",
          }
        }) \
      .AddSuccessfulNode(node2, {
        constants.NV_FILELIST: {
          pathutils.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          pathutils.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          }
        }) \
      .AddSuccessfulNode(node3, {
        constants.NV_FILELIST: {
          pathutils.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          pathutils.CLUSTER_CONF_FILE: "conf-a6d4b13e407867f7a7b4f0f232a8f527",
          pathutils.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          pathutils.RAPI_USERS_FILE: "rapiusers-ea3271e8d810ef3",
          hv_xen.XL_CONFIG_FILE: "77935cee92afd26d162f9e525e3d49b9"
          }
        }) \
      .AddSuccessfulNode(node4, {}) \
      .AddOfflineNode(node5) \
      .Build()
    assert set(nvinfo.keys()) == set(map(operator.attrgetter("uuid"), nodeinfo))

    lu._VerifyFiles(nodeinfo, self.master_uuid, nvinfo,
                    (files_all, files_opt, files_mc, files_vm))

    expected_msgs = [
      "File %s found with 2 different checksums (variant 1 on"
        " %s, %s, %s; variant 2 on %s)" %
        (pathutils.RAPI_CERT_FILE, node1.name, node2.name, node3.name,
         self.master.name),
      "File %s is missing from node(s) %s" %
        (pathutils.CLUSTER_DOMAIN_SECRET_FILE, node1.name),
      "File %s should not exist on node(s) %s" %
        (pathutils.CLUSTER_CONF_FILE, node3.name),
      "File %s is missing from node(s) %s" %
        (hv_xen.XEND_CONFIG_FILE, node3.name),
      "File %s is missing from node(s) %s" %
        (pathutils.CLUSTER_CONF_FILE, node2.name),
      "File %s found with 2 different checksums (variant 1 on"
        " %s; variant 2 on %s)" %
        (pathutils.CLUSTER_CONF_FILE, self.master.name, node3.name),
      "File %s is optional, but it must exist on all or no nodes (not"
        " found on %s, %s, %s)" %
        (pathutils.RAPI_USERS_FILE, self.master.name, node1.name, node2.name),
      "File %s is optional, but it must exist on all or no nodes (not"
        " found on %s)" % (hv_xen.XL_CONFIG_FILE, node1.name),
      "Node did not return file checksum data",
      ]

    self.assertEqual(len(self.mcpu.GetLogMessages()), len(expected_msgs))
    for expected_msg in expected_msgs:
      self.mcpu.assertLogContainsInLine(expected_msg)


class TestLUClusterVerifyGroupVerifyNodeDrbd(TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupVerifyNodeDrbd, self).setUp()

    self.node1 = self.cfg.AddNewNode()
    self.node2 = self.cfg.AddNewNode()
    self.inst = self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                                 primary_node=self.node1,
                                 secondary_node=self.node2)],
      admin_state=constants.ADMINST_UP)

  @withLockedLU
  def testNoDrbdHelper(self, lu):
    lu._VerifyNodeDrbd(self.master, {}, self.cfg.GetAllInstancesInfo(), None,
                       self.cfg.ComputeDRBDMap())
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testDrbdHelperInvalidNodeResult(self, lu):
    for ndata, expected in [({}, "no drbd usermode helper returned"),
                            ({constants.NV_DRBDHELPER: (False, "")},
                             "drbd usermode helper check unsuccessful"),
                            ({constants.NV_DRBDHELPER: (True, "/bin/false")},
                             "wrong drbd usermode helper")]:
      self.mcpu.ClearLogMessages()
      lu._VerifyNodeDrbd(self.master, ndata, self.cfg.GetAllInstancesInfo(),
                         "/bin/true", self.cfg.ComputeDRBDMap())
      self.mcpu.assertLogContainsRegex(expected)

  @withLockedLU
  def testNoNodeResult(self, lu):
    lu._VerifyNodeDrbd(self.node1, {}, self.cfg.GetAllInstancesInfo(),
                         None, self.cfg.ComputeDRBDMap())
    self.mcpu.assertLogContainsRegex("drbd minor 1 of .* is not active")

  @withLockedLU
  def testInvalidNodeResult(self, lu):
    lu._VerifyNodeDrbd(self.node1, {constants.NV_DRBDLIST: ""},
                       self.cfg.GetAllInstancesInfo(), None,
                       self.cfg.ComputeDRBDMap())
    self.mcpu.assertLogContainsRegex("cannot parse drbd status file")

  @withLockedLU
  def testWrongMinorInUse(self, lu):
    lu._VerifyNodeDrbd(self.node1, {constants.NV_DRBDLIST: [2]},
                       self.cfg.GetAllInstancesInfo(), None,
                       self.cfg.ComputeDRBDMap())
    self.mcpu.assertLogContainsRegex("drbd minor 1 of .* is not active")
    self.mcpu.assertLogContainsRegex("unallocated drbd minor 2 is in use")

  @withLockedLU
  def testValidResult(self, lu):
    lu._VerifyNodeDrbd(self.node1, {constants.NV_DRBDLIST: [1]},
                       self.cfg.GetAllInstancesInfo(), None,
                       self.cfg.ComputeDRBDMap())
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupVerifyNodeOs(TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testUpdateNodeOsInvalidNodeResult(self, lu):
    for ndata in [{}, {constants.NV_OSLIST: ""}, {constants.NV_OSLIST: [""]},
                  {constants.NV_OSLIST: [["1", "2"]]}]:
      self.mcpu.ClearLogMessages()
      nimage = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)
      lu._UpdateNodeOS(self.master, ndata, nimage)
      self.mcpu.assertLogContainsRegex("node hasn't returned valid OS data")

  @withLockedLU
  def testUpdateNodeOsValidNodeResult(self, lu):
    ndata = {
      constants.NV_OSLIST: [
        ["mock_OS", "/mocked/path", True, "", ["default"], [],
         [constants.OS_API_V20]],
        ["Another_Mock", "/random", True, "", ["var1", "var2"],
         [{"param1": "val1"}, {"param2": "val2"}], constants.OS_API_VERSIONS]
      ]
    }
    nimage = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)
    lu._UpdateNodeOS(self.master, ndata, nimage)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testVerifyNodeOs(self, lu):
    node = self.cfg.AddNewNode()
    nimg_root = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)
    nimg = cluster.LUClusterVerifyGroup.NodeImage(uuid=node.uuid)

    nimg_root.os_fail = False
    nimg_root.oslist = {
      "mock_os": [("/mocked/path", True, "", set(["default"]), set(),
                   set([constants.OS_API_V20]))],
      "broken_base_os": [("/broken", False, "", set(), set(),
                         set([constants.OS_API_V20]))],
      "only_on_root": [("/random", True, "", set(), set(), set())],
      "diffing_os": [("/pinky", True, "", set(["var1", "var2"]),
                      set([("param1", "val1"), ("param2", "val2")]),
                      set([constants.OS_API_V20]))]
    }
    nimg.os_fail = False
    nimg.oslist = {
      "mock_os": [("/mocked/path", True, "", set(["default"]), set(),
                   set([constants.OS_API_V20]))],
      "only_on_test": [("/random", True, "", set(), set(), set())],
      "diffing_os": [("/bunny", True, "", set(["var1", "var3"]),
                      set([("param1", "val1"), ("param3", "val3")]),
                      set([constants.OS_API_V15]))],
      "broken_os": [("/broken", False, "", set(), set(),
                     set([constants.OS_API_V20]))],
      "multi_entries": [
        ("/multi1", True, "", set(), set(), set([constants.OS_API_V20])),
        ("/multi2", True, "", set(), set(), set([constants.OS_API_V20]))]
    }

    lu._VerifyNodeOS(node, nimg, nimg_root)

    expected_msgs = [
      "Extra OS only_on_test not present on reference node",
      "OSes present on reference node .* but missing on this node:" +
        " only_on_root",
      "OS API version for diffing_os differs",
      "OS variants list for diffing_os differs",
      "OS parameters for diffing_os differs",
      "Invalid OS broken_os",
      "Extra OS broken_os not present on reference node",
      "OS 'multi_entries' has multiple entries",
      "Extra OS multi_entries not present on reference node"
    ]

    self.assertEqual(len(expected_msgs), len(self.mcpu.GetLogMessages()))
    for expected_msg in expected_msgs:
      self.mcpu.assertLogContainsRegex(expected_msg)


class TestLUClusterVerifyGroupVerifyAcceptedFileStoragePaths(
  TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testNotMaster(self, lu):
    lu._VerifyAcceptedFileStoragePaths(self.master, {}, False)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testNotMasterButRetunedValue(self, lu):
    lu._VerifyAcceptedFileStoragePaths(
      self.master, {constants.NV_ACCEPTED_STORAGE_PATHS: []}, False)
    self.mcpu.assertLogContainsRegex(
      "Node should not have returned forbidden file storage paths")

  @withLockedLU
  def testMasterInvalidNodeResult(self, lu):
    lu._VerifyAcceptedFileStoragePaths(self.master, {}, True)
    self.mcpu.assertLogContainsRegex(
      "Node did not return forbidden file storage paths")

  @withLockedLU
  def testMasterForbiddenPaths(self, lu):
    lu._VerifyAcceptedFileStoragePaths(
      self.master, {constants.NV_ACCEPTED_STORAGE_PATHS: ["/forbidden"]}, True)
    self.mcpu.assertLogContainsRegex("Found forbidden file storage paths")

  @withLockedLU
  def testMasterSuccess(self, lu):
    lu._VerifyAcceptedFileStoragePaths(
      self.master, {constants.NV_ACCEPTED_STORAGE_PATHS: []}, True)
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupVerifyStoragePaths(
  TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testVerifyFileStoragePathsSuccess(self, lu):
    lu._VerifyFileStoragePaths(self.master, {})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testVerifyFileStoragePathsFailure(self, lu):
    lu._VerifyFileStoragePaths(self.master,
                               {constants.NV_FILE_STORAGE_PATH: "/fail/path"})
    self.mcpu.assertLogContainsRegex(
      "The configured file storage path is unusable")

  @withLockedLU
  def testVerifySharedFileStoragePathsSuccess(self, lu):
    lu._VerifySharedFileStoragePaths(self.master, {})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testVerifySharedFileStoragePathsFailure(self, lu):
    lu._VerifySharedFileStoragePaths(
      self.master, {constants.NV_SHARED_FILE_STORAGE_PATH: "/fail/path"})
    self.mcpu.assertLogContainsRegex(
      "The configured sharedfile storage path is unusable")


class TestLUClusterVerifyGroupVerifyOob(TestLUClusterVerifyGroupMethods):
  @withLockedLU
  def testEmptyResult(self, lu):
    lu._VerifyOob(self.master, {})
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testErrorResults(self, lu):
    lu._VerifyOob(self.master, {constants.NV_OOB_PATHS: ["path1", "path2"]})
    self.mcpu.assertLogContainsRegex("path1")
    self.mcpu.assertLogContainsRegex("path2")


class TestLUClusterVerifyGroupUpdateNodeVolumes(
  TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupUpdateNodeVolumes, self).setUp()
    self.nimg = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)

  @withLockedLU
  def testNoVgName(self, lu):
    lu._UpdateNodeVolumes(self.master, {}, self.nimg, None)
    self.mcpu.assertLogIsEmpty()
    self.assertTrue(self.nimg.lvm_fail)

  @withLockedLU
  def testErrorMessage(self, lu):
    lu._UpdateNodeVolumes(self.master, {constants.NV_LVLIST: "mock error"},
                          self.nimg, "mock_vg")
    self.mcpu.assertLogContainsRegex("LVM problem on node: mock error")
    self.assertTrue(self.nimg.lvm_fail)

  @withLockedLU
  def testInvalidNodeResult(self, lu):
    lu._UpdateNodeVolumes(self.master, {constants.NV_LVLIST: [1, 2, 3]},
                          self.nimg, "mock_vg")
    self.mcpu.assertLogContainsRegex("rpc call to node failed")
    self.assertTrue(self.nimg.lvm_fail)

  @withLockedLU
  def testValidNodeResult(self, lu):
    lu._UpdateNodeVolumes(self.master, {constants.NV_LVLIST: {}},
                          self.nimg, "mock_vg")
    self.mcpu.assertLogIsEmpty()
    self.assertFalse(self.nimg.lvm_fail)


class TestLUClusterVerifyGroupUpdateNodeInstances(
  TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupUpdateNodeInstances, self).setUp()
    self.nimg = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)

  @withLockedLU
  def testInvalidNodeResult(self, lu):
    lu._UpdateNodeInstances(self.master, {}, self.nimg)
    self.mcpu.assertLogContainsRegex("rpc call to node failed")

  @withLockedLU
  def testValidNodeResult(self, lu):
    inst = self.cfg.AddNewInstance()
    lu._UpdateNodeInstances(self.master,
                            {constants.NV_INSTANCELIST: [inst.name]},
                            self.nimg)
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupUpdateNodeInfo(TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupUpdateNodeInfo, self).setUp()
    self.nimg = cluster.LUClusterVerifyGroup.NodeImage(uuid=self.master_uuid)
    self.valid_hvresult = {constants.NV_HVINFO: {"memory_free": 1024}}

  @withLockedLU
  def testInvalidHvNodeResult(self, lu):
    for ndata in [{}, {constants.NV_HVINFO: ""}]:
      self.mcpu.ClearLogMessages()
      lu._UpdateNodeInfo(self.master, ndata, self.nimg, None)
      self.mcpu.assertLogContainsRegex("rpc call to node failed")

  @withLockedLU
  def testInvalidMemoryFreeHvNodeResult(self, lu):
    lu._UpdateNodeInfo(self.master,
                       {constants.NV_HVINFO: {"memory_free": "abc"}},
                       self.nimg, None)
    self.mcpu.assertLogContainsRegex(
      "node returned invalid nodeinfo, check hypervisor")

  @withLockedLU
  def testValidHvNodeResult(self, lu):
    lu._UpdateNodeInfo(self.master, self.valid_hvresult, self.nimg, None)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testInvalidVgNodeResult(self, lu):
    for vgdata in [[], ""]:
      self.mcpu.ClearLogMessages()
      ndata = {constants.NV_VGLIST: vgdata}
      ndata.update(self.valid_hvresult)
      lu._UpdateNodeInfo(self.master, ndata, self.nimg, "mock_vg")
      self.mcpu.assertLogContainsRegex(
        "node didn't return data for the volume group 'mock_vg'")

  @withLockedLU
  def testInvalidDiskFreeVgNodeResult(self, lu):
    self.valid_hvresult.update({
      constants.NV_VGLIST: {"mock_vg": "abc"}
    })
    lu._UpdateNodeInfo(self.master, self.valid_hvresult, self.nimg, "mock_vg")
    self.mcpu.assertLogContainsRegex(
      "node returned invalid LVM info, check LVM status")

  @withLockedLU
  def testValidVgNodeResult(self, lu):
    self.valid_hvresult.update({
      constants.NV_VGLIST: {"mock_vg": 10000}
    })
    lu._UpdateNodeInfo(self.master, self.valid_hvresult, self.nimg, "mock_vg")
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupCollectDiskInfo(TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupCollectDiskInfo, self).setUp()

    self.node1 = self.cfg.AddNewNode()
    self.node2 = self.cfg.AddNewNode()
    self.node3 = self.cfg.AddNewNode()

    self.diskless_inst = \
      self.cfg.AddNewInstance(primary_node=self.node1,
                              disk_template=constants.DT_DISKLESS)
    self.plain_inst = \
      self.cfg.AddNewInstance(primary_node=self.node2,
                              disk_template=constants.DT_PLAIN)
    self.drbd_inst = \
      self.cfg.AddNewInstance(primary_node=self.node3,
                              secondary_node=self.node2,
                              disk_template=constants.DT_DRBD8)

    self.node1_img = cluster.LUClusterVerifyGroup.NodeImage(
                       uuid=self.node1.uuid)
    self.node1_img.pinst = [self.diskless_inst.uuid]
    self.node1_img.sinst = []
    self.node2_img = cluster.LUClusterVerifyGroup.NodeImage(
                       uuid=self.node2.uuid)
    self.node2_img.pinst = [self.plain_inst.uuid]
    self.node2_img.sinst = [self.drbd_inst.uuid]
    self.node3_img = cluster.LUClusterVerifyGroup.NodeImage(
                       uuid=self.node3.uuid)
    self.node3_img.pinst = [self.drbd_inst.uuid]
    self.node3_img.sinst = []

    self.node_images = {
      self.node1.uuid: self.node1_img,
      self.node2.uuid: self.node2_img,
      self.node3.uuid: self.node3_img
    }

    self.node_uuids = [self.node1.uuid, self.node2.uuid, self.node3.uuid]

  @withLockedLU
  def testSuccessfulRun(self, lu):
    self.rpc.call_blockdev_getmirrorstatus_multi.return_value = \
      RpcResultsBuilder() \
        .AddSuccessfulNode(self.node2, [(True, ""), (True, "")]) \
        .AddSuccessfulNode(self.node3, [(True, "")]) \
        .Build()

    lu._CollectDiskInfo(self.node_uuids, self.node_images,
                        self.cfg.GetAllInstancesInfo())

    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testOfflineAndFailingNodes(self, lu):
    self.rpc.call_blockdev_getmirrorstatus_multi.return_value = \
      RpcResultsBuilder() \
        .AddOfflineNode(self.node2) \
        .AddFailedNode(self.node3) \
        .Build()

    lu._CollectDiskInfo(self.node_uuids, self.node_images,
                        self.cfg.GetAllInstancesInfo())

    self.mcpu.assertLogContainsRegex("while getting disk information")

  @withLockedLU
  def testInvalidNodeResult(self, lu):
    self.rpc.call_blockdev_getmirrorstatus_multi.return_value = \
      RpcResultsBuilder() \
        .AddSuccessfulNode(self.node2, [(True,), (False,)]) \
        .AddSuccessfulNode(self.node3, [""]) \
        .Build()

    lu._CollectDiskInfo(self.node_uuids, self.node_images,
                        self.cfg.GetAllInstancesInfo())
    # logging is not performed through mcpu
    self.mcpu.assertLogIsEmpty()


class TestLUClusterVerifyGroupHooksCallBack(TestLUClusterVerifyGroupMethods):
  def setUp(self):
    super(TestLUClusterVerifyGroupHooksCallBack, self).setUp()

    self.feedback_fn = lambda _: None

  def PrepareLU(self, lu):
    super(TestLUClusterVerifyGroupHooksCallBack, self).PrepareLU(lu)

    lu.my_node_uuids = list(self.cfg.GetAllNodesInfo().keys())

  @withLockedLU
  def testEmptyGroup(self, lu):
    lu.my_node_uuids = []
    lu.HooksCallBack(constants.HOOKS_PHASE_POST, None, self.feedback_fn, None)

  @withLockedLU
  def testFailedResult(self, lu):
    lu.HooksCallBack(constants.HOOKS_PHASE_POST,
                     RpcResultsBuilder(use_node_names=True)
                       .AddFailedNode(self.master).Build(),
                     self.feedback_fn,
                     None)
    self.mcpu.assertLogContainsRegex("Communication failure in hooks execution")

  @withLockedLU
  def testOfflineNode(self, lu):
    lu.HooksCallBack(constants.HOOKS_PHASE_POST,
                     RpcResultsBuilder(use_node_names=True)
                       .AddOfflineNode(self.master).Build(),
                     self.feedback_fn,
                     None)

  @withLockedLU
  def testValidResult(self, lu):
    lu.HooksCallBack(constants.HOOKS_PHASE_POST,
                     RpcResultsBuilder(use_node_names=True)
                       .AddSuccessfulNode(self.master,
                                          [("mock_script",
                                            constants.HKR_SUCCESS,
                                            "mock output")])
                       .Build(),
                     self.feedback_fn,
                     None)

  @withLockedLU
  def testFailedScriptResult(self, lu):
    lu.HooksCallBack(constants.HOOKS_PHASE_POST,
                     RpcResultsBuilder(use_node_names=True)
                       .AddSuccessfulNode(self.master,
                                          [("mock_script",
                                            constants.HKR_FAIL,
                                            "mock output")])
                       .Build(),
                     self.feedback_fn,
                     None)
    self.mcpu.assertLogContainsRegex("Script mock_script failed")


class TestLUClusterVerifyDisks(CmdlibTestCase):
  def testVerifyDisks(self):
    op = opcodes.OpClusterVerifyDisks()
    result = self.ExecOpCode(op)

    self.assertEqual(1, len(result["jobs"]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
