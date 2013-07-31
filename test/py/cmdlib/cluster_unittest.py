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

import unittest
import operator
import os
import tempfile
import shutil

from ganeti import constants
from ganeti import compat
from ganeti import errors
from ganeti import ht
from ganeti import netutils
from ganeti import objects
from ganeti import opcodes
from ganeti import utils
from ganeti import pathutils
from ganeti import rpc
from ganeti import query
from ganeti.cmdlib import cluster
from ganeti.hypervisor import hv_xen

from testsupport import *

import testutils
import mocks


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    cluster._VerifyCertificate(testutils.TestDataFilename("cert1.pem"))

    nonexist_filename = os.path.join(self.tmpdir, "does-not-exist")

    (errcode, msg) = cluster._VerifyCertificate(nonexist_filename)
    self.assertEqual(errcode, cluster.LUClusterVerifyConfig.ETYPE_ERROR)

    # Try to load non-certificate file
    invalid_cert = testutils.TestDataFilename("bdev-net.txt")
    (errcode, msg) = cluster._VerifyCertificate(invalid_cert)
    self.assertEqual(errcode, cluster.LUClusterVerifyConfig.ETYPE_ERROR)


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


class TestClusterVerifyFiles(unittest.TestCase):
  @staticmethod
  def _FakeErrorIf(errors, cond, ecode, item, msg, *args, **kwargs):
    assert ((ecode == constants.CV_ENODEFILECHECK and
             ht.TNonEmptyString(item)) or
            (ecode == constants.CV_ECLUSTERFILECHECK and
             item is None))

    if args:
      msg = msg % args

    if cond:
      errors.append((item, msg))

  def test(self):
    errors = []
    nodeinfo = [
      objects.Node(name="master.example.com",
                   uuid="master-uuid",
                   offline=False,
                   vm_capable=True),
      objects.Node(name="node2.example.com",
                   uuid="node2-uuid",
                   offline=False,
                   vm_capable=True),
      objects.Node(name="node3.example.com",
                   uuid="node3-uuid",
                   master_candidate=True,
                   vm_capable=False),
      objects.Node(name="node4.example.com",
                   uuid="node4-uuid",
                   offline=False,
                   vm_capable=True),
      objects.Node(name="nodata.example.com",
                   uuid="nodata-uuid",
                   offline=False,
                   vm_capable=True),
      objects.Node(name="offline.example.com",
                   uuid="offline-uuid",
                   offline=True),
      ]
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
    nvinfo = {
      "master-uuid": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          pathutils.CLUSTER_CONF_FILE: "82314f897f38b35f9dab2f7c6b1593e0",
          pathutils.RAPI_CERT_FILE: "babbce8f387bc082228e544a2146fee4",
          pathutils.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          hv_xen.XEND_CONFIG_FILE: "b4a8a824ab3cac3d88839a9adeadf310",
          hv_xen.XL_CONFIG_FILE: "77935cee92afd26d162f9e525e3d49b9"
        }})),
      "node2-uuid": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          pathutils.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          hv_xen.XEND_CONFIG_FILE: "b4a8a824ab3cac3d88839a9adeadf310",
          }
        })),
      "node3-uuid": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          pathutils.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          pathutils.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          }
        })),
      "node4-uuid": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          pathutils.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          pathutils.CLUSTER_CONF_FILE: "conf-a6d4b13e407867f7a7b4f0f232a8f527",
          pathutils.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          pathutils.RAPI_USERS_FILE: "rapiusers-ea3271e8d810ef3",
          hv_xen.XL_CONFIG_FILE: "77935cee92afd26d162f9e525e3d49b9"
          }
        })),
      "nodata-uuid": rpc.RpcResult(data=(True, {})),
      "offline-uuid": rpc.RpcResult(offline=True),
      }
    assert set(nvinfo.keys()) == set(map(operator.attrgetter("uuid"), nodeinfo))

    verify_lu = cluster.LUClusterVerifyGroup(mocks.FakeProc(),
                                             opcodes.OpClusterVerify(),
                                             mocks.FakeContext(),
                                             None)

    verify_lu._ErrorIf = compat.partial(self._FakeErrorIf, errors)

    # TODO: That's a bit hackish to mock only this single method. We should
    # build a better FakeConfig which provides such a feature already.
    def GetNodeName(node_uuid):
      for node in nodeinfo:
        if node.uuid == node_uuid:
          return node.name
      return None

    verify_lu.cfg.GetNodeName = GetNodeName

    verify_lu._VerifyFiles(nodeinfo, "master-uuid", nvinfo,
                           (files_all, files_opt, files_mc, files_vm))
    self.assertEqual(sorted(errors), sorted([
      (None, ("File %s found with 2 different checksums (variant 1 on"
              " node2.example.com, node3.example.com, node4.example.com;"
              " variant 2 on master.example.com)" % pathutils.RAPI_CERT_FILE)),
      (None, ("File %s is missing from node(s) node2.example.com" %
              pathutils.CLUSTER_DOMAIN_SECRET_FILE)),
      (None, ("File %s should not exist on node(s) node4.example.com" %
              pathutils.CLUSTER_CONF_FILE)),
      (None, ("File %s is missing from node(s) node4.example.com" %
              hv_xen.XEND_CONFIG_FILE)),
      (None, ("File %s is missing from node(s) node3.example.com" %
              pathutils.CLUSTER_CONF_FILE)),
      (None, ("File %s found with 2 different checksums (variant 1 on"
              " master.example.com; variant 2 on node4.example.com)" %
              pathutils.CLUSTER_CONF_FILE)),
      (None, ("File %s is optional, but it must exist on all or no nodes (not"
              " found on master.example.com, node2.example.com,"
              " node3.example.com)" % pathutils.RAPI_USERS_FILE)),
      (None, ("File %s is optional, but it must exist on all or no nodes (not"
              " found on node2.example.com)" % hv_xen.XL_CONFIG_FILE)),
      ("nodata.example.com", "Node did not return file checksum data"),
      ]))


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
  def testExecuion(self):
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
  NEW_IP = "1.2.3.4"

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

  def _SetUpInstanceSingleDisk(self, dev_type=constants.LD_LV):
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
    self._SetUpInstanceSingleDisk(dev_type=constants.LD_DRBD8)
    changed = self._ExecOpClusterRepairDiskSizes([(1024 * 1024 * 1024, None)])
    self.mcpu.assertLogIsEmpty()
    self.assertEqual(0, len(changed))

  def testWrongDRBDChild(self):
    (_, disk) = self._SetUpInstanceSingleDisk(dev_type=constants.LD_DRBD8)
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
    op = opcodes.OpClusterSetParams(master_netmask=0xFFFF0000)
    self.ExecOpCode(op)
    self.assertEqual(0xFFFF0000, self.cluster.master_netmask)

  def testInvalidDiskparams(self):
    for diskparams in [{constants.DT_DISKLESS: {constants.LV_STRIPES: 0}},
                       {constants.DT_DRBD8: {constants.RBD_POOL: "pool"}}]:
      self.ResetMocks()
      op = opcodes.OpClusterSetParams(diskparams=diskparams)
      self.ExecOpCodeExpectOpPrereqError(op, "verify diskparams")

  def testValidDiskparams(self):
    diskparams = {constants.DT_RBD: {constants.RBD_POOL: "mock_pool"}}
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

  def testUnsetDrbdHelperWithDrbdDisks(self):
    self.cfg.AddNewInstance(disks=[
      self.cfg.CreateDisk(dev_type=constants.LD_DRBD8, create_nodes=True)])
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
    self.cluster.enabled_disk_templates = [constants.DT_DISKLESS]
    self.rpc.call_drbd_helper.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, drbd_helper) \
        .Build()
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("but did not enable")

  def testResetDrbdHelper(self):
    drbd_helper = ""
    self.cluster.enabled_disk_templates = [constants.DT_DISKLESS]
    op = opcodes.OpClusterSetParams(drbd_helper=drbd_helper)
    self.ExecOpCode(op)

    self.assertEqual(None, self.cluster.drbd_usermode_helper)

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
      constants.LD_LV: {
        "mock_vg": {constants.DS_DISK_TOTAL: 10}
      }
    }
    op = opcodes.OpClusterSetParams(disk_state=disk_state)
    self.ExecOpCode(op)
    self.assertEqual(10, self.cluster
                           .disk_state_static[constants.LD_LV]["mock_vg"]
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
      constants.NIC_MODE: constants.NIC_MODE_BRIDGED
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
           enabled_disk_templates=enabled_disk_templates)
    self.ExecOpCode(op)

    self.assertEqual(enabled_disk_templates,
                     self.cluster.enabled_disk_templates)

  def testEnabledDiskTemplatesWithoutVgName(self):
    enabled_disk_templates = [constants.DT_PLAIN]
    self.cluster.volume_group_name = None
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=enabled_disk_templates)
    self.ExecOpCodeExpectOpPrereqError(op, "specify a volume group")

  def testDisableDiskTemplateWithExistingInstance(self):
    enabled_disk_templates = [constants.DT_DISKLESS]
    self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.LD_LV)])
    op = opcodes.OpClusterSetParams(
           enabled_disk_templates=enabled_disk_templates)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot disable disk template")

  def testVgNameNoLvmDiskTemplateEnabled(self):
    vg_name = "test_vg"
    self.cluster.enabled_disk_templates = [constants.DT_DISKLESS]
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCode(op)

    self.assertEqual(vg_name, self.cluster.volume_group_name)
    self.mcpu.assertLogContainsRegex("enable any lvm disk template")

  def testUnsetVgNameWithLvmDiskTemplateEnabled(self):
    vg_name = ""
    self.cluster.enabled_disk_templates = [constants.DT_PLAIN]
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot unset volume group")

  def testUnsetVgNameWithLvmInstance(self):
    vg_name = ""
    self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.LD_LV)])
    op = opcodes.OpClusterSetParams(vg_name=vg_name)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot disable lvm storage")

  def testUnsetVgNameWithNoLvmDiskTemplateEnabled(self):
    vg_name = ""
    self.cluster.enabled_disk_templates = [constants.DT_DISKLESS]
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
