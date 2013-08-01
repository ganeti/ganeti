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
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateSuccessfulNodeResult(self.master)

    self.ExecOpCode(op)

    self.rpc.call_node_activate_master_ip.assert_called_once_with(
      self.master_uuid, self.cfg.GetMasterNetworkParameters(), False)

  def testFailure(self):
    op = opcodes.OpClusterActivateMasterIp()

    self.rpc.call_node_activate_master_ip.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateFailedNodeResult(self.master) \

    self.ExecOpCodeExpectOpExecError(op)


class TestLUClusterDeactivateMasterIp(CmdlibTestCase):
  def testSuccess(self):
    op = opcodes.OpClusterDeactivateMasterIp()

    self.rpc.call_node_deactivate_master_ip.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateSuccessfulNodeResult(self.master)

    self.ExecOpCode(op)

    self.rpc.call_node_deactivate_master_ip.assert_called_once_with(
      self.master_uuid, self.cfg.GetMasterNetworkParameters(), False)

  def testFailure(self):
    op = opcodes.OpClusterDeactivateMasterIp()

    self.rpc.call_node_deactivate_master_ip.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateFailedNodeResult(self.master) \

    self.ExecOpCodeExpectOpExecError(op)


class TestLUClusterConfigQuery(CmdlibTestCase):
  def testInvalidField(self):
    op = opcodes.OpClusterConfigQuery(output_fields=["pinky_bunny"])

    self.ExecOpCodeExpectOpPrereqError(op, "pinky_bunny")

  def testAllFields(self):
    op = opcodes.OpClusterConfigQuery(output_fields=query.CLUSTER_FIELDS.keys())

    self.rpc.call_get_watcher_pause.return_value = \
      RpcResultsBuilder(self.cfg) \
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

    inst = self.cfg.AddNewInstance()
    disk = self.cfg.CreateDisk(dev_type=dev_type,
                               primary_node=pnode,
                               secondary_node=snode)
    inst.disks.append(disk)

    return (inst, disk)

  def testSingleInstanceOnFailingNode(self):
    (inst, _) = self._SetUpInstanceSingleDisk()
    op = opcodes.OpClusterRepairDiskSizes(instances=[inst.name])

    self.rpc.call_blockdev_getdimensions.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateFailedNodeResult(self.master)

    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("Failure in blockdev_getdimensions")

  def _ExecOpClusterRepairDiskSizes(self, node_data):
    # not specifying instances repairs all
    op = opcodes.OpClusterRepairDiskSizes()

    self.rpc.call_blockdev_getdimensions.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
