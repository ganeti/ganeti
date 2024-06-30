#!/usr/bin/python3
#

# Copyright (C) 2008, 2011, 2012, 2013 Google Inc.
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


"""Tests for LUInstance*

"""

import copy
import itertools
import re
import unittest
import os
from unittest import mock

from ganeti import backend
from ganeti import compat
from ganeti import config
from ganeti import constants
from ganeti import errors
from ganeti import ht
from ganeti import opcodes
from ganeti import objects
from ganeti.rpc import node as rpc
from ganeti import utils
from ganeti.cmdlib import instance
from ganeti.cmdlib import instance_storage
from ganeti.cmdlib import instance_create
from ganeti.cmdlib import instance_set_params
from ganeti.cmdlib import instance_utils

from cmdlib.cmdlib_unittest import _FakeLU

from testsupport import *

import testutils
from testutils.config_mock import _UpdateIvNames


class TestComputeIPolicyInstanceSpecViolation(unittest.TestCase):
  def setUp(self):
    self.ispec = {
      constants.ISPEC_MEM_SIZE: 2048,
      constants.ISPEC_CPU_COUNT: 2,
      constants.ISPEC_DISK_COUNT: 1,
      constants.ISPEC_DISK_SIZE: [512],
      constants.ISPEC_NIC_COUNT: 0,
      constants.ISPEC_SPINDLE_USE: 1,
      }
    self.stub = mock.MagicMock()
    self.stub.return_value = []

  def testPassThrough(self):
    ret = instance_utils.ComputeIPolicyInstanceSpecViolation(
        NotImplemented, self.ispec, [constants.DT_PLAIN], _compute_fn=self.stub)
    self.assertEqual(ret, [])
    self.stub.assert_called_with(NotImplemented, 2048, 2, 1, 0, [512],
                                 1, [constants.DT_PLAIN])


class TestLUInstanceCreate(CmdlibTestCase):
  def _setupOSDiagnose(self):
    os_result = [(self.os.name,
                  self.os.path,
                  True,
                  "",
                  self.os.supported_variants,
                  self.os.supported_parameters,
                  self.os.api_versions,
                  True)]
    self.rpc.call_os_diagnose.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, os_result) \
        .AddSuccessfulNode(self.node1, os_result) \
        .AddSuccessfulNode(self.node2, os_result) \
        .Build()

  def setUp(self):
    super(TestLUInstanceCreate, self).setUp()
    self.ResetMocks()

    self.MockOut(instance_create, 'netutils', self.netutils_mod)
    self.MockOut(instance_utils, 'netutils', self.netutils_mod)

    self.net = self.cfg.AddNewNetwork()
    self.cfg.ConnectNetworkToGroup(self.net, self.group)

    self.node1 = self.cfg.AddNewNode()
    self.node2 = self.cfg.AddNewNode()

    hv_info = ("bootid",
               [{
                 "type": constants.ST_LVM_VG,
                 "storage_free": 10000
               }],
               ({"memory_free": 10000}, ))
    self.rpc.call_node_info.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, hv_info) \
        .AddSuccessfulNode(self.node1, hv_info) \
        .AddSuccessfulNode(self.node2, hv_info) \
        .Build()

    self._setupOSDiagnose()

    self.rpc.call_blockdev_getmirrorstatus.side_effect = \
      lambda node, _: self.RpcResultsBuilder() \
                        .CreateSuccessfulNodeResult(node, [])

    self.iallocator_cls.return_value.result = [self.node1.name, self.node2.name]

    self.diskless_op = opcodes.OpInstanceCreate(
      instance_name="diskless.example.com",
      pnode=self.master.name,
      disk_template=constants.DT_DISKLESS,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[],
      os_type=self.os_name_variant,
      name_check=True,
      ip_check=True)

    self.plain_op = opcodes.OpInstanceCreate(
      instance_name="plain.example.com",
      pnode=self.master.name,
      disk_template=constants.DT_PLAIN,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      os_type=self.os_name_variant)

    self.block_op = opcodes.OpInstanceCreate(
      instance_name="block.example.com",
      pnode=self.master.name,
      disk_template=constants.DT_BLOCK,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024,
        constants.IDISK_ADOPT: "/dev/disk/block0"
      }],
      os_type=self.os_name_variant)

    self.drbd_op = opcodes.OpInstanceCreate(
      instance_name="drbd.example.com",
      pnode=self.node1.name,
      snode=self.node2.name,
      disk_template=constants.DT_DRBD8,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      os_type=self.os_name_variant)

    self.file_op = opcodes.OpInstanceCreate(
      instance_name="file.example.com",
      pnode=self.node1.name,
      disk_template=constants.DT_FILE,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      os_type=self.os_name_variant)

    self.shared_file_op = opcodes.OpInstanceCreate(
      instance_name="shared-file.example.com",
      pnode=self.node1.name,
      disk_template=constants.DT_SHARED_FILE,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      os_type=self.os_name_variant)

    self.gluster_op = opcodes.OpInstanceCreate(
      instance_name="gluster.example.com",
      pnode=self.node1.name,
      disk_template=constants.DT_GLUSTER,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      os_type=self.os_name_variant)

    self.rbd_op = opcodes.OpInstanceCreate(
      instance_name="gluster.example.com",
      pnode=self.node1.name,
      disk_template=constants.DT_RBD,
      mode=constants.INSTANCE_CREATE,
      nics=[{}],
      disks=[{
        constants.IDISK_SIZE: 1024
      }],
      os_type=self.os_name_variant)

  def testSimpleCreate(self):
    op = self.CopyOpCode(self.diskless_op)
    self.ExecOpCode(op)

  def testStrangeHostnameResolve(self):
    op = self.CopyOpCode(self.diskless_op)
    self.netutils_mod.GetHostname.return_value = \
      HostnameMock("random.host.example.com", "203.0.113.1")
    self.ExecOpCodeExpectOpPrereqError(
      op, "Resolved hostname .* does not look the same as given hostname")

  def testOpportunisticLockingNoIAllocator(self):
    op = self.CopyOpCode(self.diskless_op,
                         opportunistic_locking=True,
                         iallocator=None)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Opportunistic locking is only available in combination with an"
          " instance allocator")

  def testNicWithNetAndMode(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_NETWORK: self.net.name,
                           constants.INIC_MODE: constants.NIC_MODE_BRIDGED
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "If network is given, no mode or link is allowed to be passed")

  def testAutoIpNoNameCheck(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: constants.VALUE_AUTO
                         }],
                         ip_check=False,
                         name_check=False)
    self.ExecOpCodeExpectOpPrereqError(
      op, "IP address set to auto but the name checks are not enabled")

  def testAutoIp(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: constants.VALUE_AUTO
                         }])
    self.ExecOpCode(op)

  def testPoolIpNoNetwork(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: constants.NIC_IP_POOL
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "if ip=pool, parameter network must be passed too")

  def testValidIp(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: "203.0.113.1"
                         }])
    self.ExecOpCode(op)

  def testRoutedNoIp(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_NETWORK: constants.VALUE_NONE,
                           constants.INIC_MODE: constants.NIC_MODE_ROUTED
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Routed nic mode requires an ip address"
      " if not attached to a network")

  def testValicMac(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_MAC: "f0:df:f4:a3:d1:cf"
                         }])
    self.ExecOpCode(op)

  def testValidNicParams(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_MODE: constants.NIC_MODE_BRIDGED,
                           constants.INIC_LINK: "br_mock"
                         }])
    self.ExecOpCode(op)

  def testValidNicParamsOpenVSwitch(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_MODE: constants.NIC_MODE_OVS,
                           constants.INIC_VLAN: "1"
                         }])
    self.ExecOpCode(op)

  def testNicNoneName(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_NAME: constants.VALUE_NONE
                         }])
    self.ExecOpCode(op)

  def testConflictingIP(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: self.net.gateway[:-1] + "2"
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "The requested IP address .* belongs to network .*, but the target"
          " NIC does not.")

  def testVLanFormat(self):
    for vlan in [".pinky", ":bunny", ":1:pinky", "bunny"]:
      self.ResetMocks()
      op = self.CopyOpCode(self.diskless_op,
                           nics=[{
                             constants.INIC_VLAN: vlan
                           }])
      self.ExecOpCodeExpectOpPrereqError(
        op, "Specified VLAN parameter is invalid")

  def testPoolIp(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: constants.NIC_IP_POOL,
                           constants.INIC_NETWORK: self.net.name
                         }])
    self.ExecOpCode(op)

  def testPoolIpUnconnectedNetwork(self):
    net = self.cfg.AddNewNetwork()
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: constants.NIC_IP_POOL,
                           constants.INIC_NETWORK: net.name
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "No netparams found for network .*.")

  def testIpNotInNetwork(self):
    op = self.CopyOpCode(self.diskless_op,
                         nics=[{
                           constants.INIC_IP: "203.0.113.1",
                           constants.INIC_NETWORK: self.net.name
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "IP address .* already in use or does not belong to network .*")

  def testMixAdoptAndNotAdopt(self):
    op = self.CopyOpCode(self.diskless_op,
                         disk_template=constants.DT_PLAIN,
                         disks=[{
                           constants.IDISK_ADOPT: "lv1"
                         }, {}])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Either all disks are adopted or none is")

  def testMustAdoptWithoutAdopt(self):
    op = self.CopyOpCode(self.diskless_op,
                         disk_template=constants.DT_BLOCK,
                         disks=[{}])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk template blockdev requires disk adoption, but no 'adopt'"
          " parameter given")

  def testDontAdoptWithAdopt(self):
    op = self.CopyOpCode(self.diskless_op,
                         disk_template=constants.DT_DRBD8,
                         disks=[{
                           constants.IDISK_ADOPT: "lv1"
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk adoption is not supported for the 'drbd' disk template")

  def testAdoptWithIAllocator(self):
    op = self.CopyOpCode(self.diskless_op,
                         disk_template=constants.DT_PLAIN,
                         disks=[{
                           constants.IDISK_ADOPT: "lv1"
                         }],
                         iallocator="mock")
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk adoption not allowed with an iallocator script")

  def testAdoptWithImport(self):
    op = self.CopyOpCode(self.diskless_op,
                         disk_template=constants.DT_PLAIN,
                         disks=[{
                           constants.IDISK_ADOPT: "lv1"
                         }],
                         mode=constants.INSTANCE_IMPORT)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk adoption not allowed for instance import")

  def testArgumentCombinations(self):
    op = self.CopyOpCode(self.diskless_op,
                         # start flag will be flipped
                         no_install=True,
                         start=True,
                         # no allowed combination
                         ip_check=True,
                         name_check=False)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Cannot do IP address check without a name check")

  def testInvalidFileDriver(self):
    op = self.CopyOpCode(self.diskless_op,
                         file_driver="invalid_file_driver")
    self.ExecOpCodeExpectOpPrereqError(
      op, "Parameter 'OP_INSTANCE_CREATE.file_driver' fails validation")

  def testMissingSecondaryNode(self):
    op = self.CopyOpCode(self.diskless_op,
                         pnode=self.master.name,
                         disk_template=constants.DT_DRBD8)
    self.ExecOpCodeExpectOpPrereqError(
      op, "The networked disk templates need a mirror node")

  def testIgnoredSecondaryNode(self):
    op = self.CopyOpCode(self.diskless_op,
                         pnode=self.master.name,
                         snode=self.node1.name,
                         disk_template=constants.DT_PLAIN)
    try:
      self.ExecOpCode(op)
    except Exception:
      pass
    self.mcpu.assertLogContainsRegex(
      "Secondary node will be ignored on non-mirrored disk template")

  def testMissingOsType(self):
    op = self.CopyOpCode(self.diskless_op,
                         os_type=self.REMOVE)
    self.ExecOpCodeExpectOpPrereqError(op, "No guest OS or OS image specified")

  def testBlacklistedOs(self):
    self.cluster.blacklisted_os = [self.os_name_variant]
    op = self.CopyOpCode(self.diskless_op)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Guest OS .* is not allowed for installation")

  def testMissingDiskTemplate(self):
    self.cluster.enabled_disk_templates = [constants.DT_DISKLESS]
    op = self.CopyOpCode(self.diskless_op,
                         disk_template=self.REMOVE)
    self.ExecOpCode(op)

  def testExistingInstance(self):
    inst = self.cfg.AddNewInstance()
    op = self.CopyOpCode(self.diskless_op,
                         instance_name=inst.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance .* is already in the cluster")

  def testPlainInstance(self):
    op = self.CopyOpCode(self.plain_op)
    self.ExecOpCode(op)

  def testPlainIAllocator(self):
    op = self.CopyOpCode(self.plain_op,
                         pnode=self.REMOVE,
                         iallocator="mock")
    self.ExecOpCode(op)

  def testIAllocatorOpportunisticLocking(self):
    op = self.CopyOpCode(self.plain_op,
                         pnode=self.REMOVE,
                         iallocator="mock",
                         opportunistic_locking=True)
    self.ExecOpCode(op)

  def testFailingIAllocator(self):
    self.iallocator_cls.return_value.success = False
    op = self.CopyOpCode(self.plain_op,
                         pnode=self.REMOVE,
                         iallocator="mock")
    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't compute nodes using iallocator")

  def testDrbdInstance(self):
    op = self.CopyOpCode(self.drbd_op)
    self.ExecOpCode(op)

  def testDrbdIAllocator(self):
    op = self.CopyOpCode(self.drbd_op,
                         pnode=self.REMOVE,
                         snode=self.REMOVE,
                         iallocator="mock")
    self.ExecOpCode(op)

  def testFileInstance(self):
    op = self.CopyOpCode(self.file_op)
    self.ExecOpCode(op)

  def testFileInstanceNoClusterStorage(self):
    self.cluster.file_storage_dir = None
    op = self.CopyOpCode(self.file_op)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Cluster file storage dir for 'file' storage type not defined")

  def testFileInstanceAdditionalPath(self):
    op = self.CopyOpCode(self.file_op,
                         file_storage_dir="mock_dir")
    self.ExecOpCode(op)

  def testIdentifyDefaults(self):
    op = self.CopyOpCode(self.plain_op,
                         hvparams={
                           constants.HV_BOOT_ORDER: "cd"
                         },
                         beparams=constants.BEC_DEFAULTS.copy(),
                         nics=[{
                           constants.NIC_MODE: constants.NIC_MODE_BRIDGED
                         }],
                         osparams={
                           self.os_name_variant: {}
                         },
                         osparams_private={},
                         identify_defaults=True)
    self.ExecOpCode(op)

    inst = list(self.cfg.GetAllInstancesInfo().values())[0]
    self.assertEqual(0, len(inst.hvparams))
    self.assertEqual(0, len(inst.beparams))
    assert self.os_name_variant not in inst.osparams or \
            len(inst.osparams[self.os_name_variant]) == 0

  def testOfflineNode(self):
    self.node1.offline = True
    op = self.CopyOpCode(self.diskless_op,
                         pnode=self.node1.name)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot use offline primary node")

  def testDrainedNode(self):
    self.node1.drained = True
    op = self.CopyOpCode(self.diskless_op,
                         pnode=self.node1.name)
    self.ExecOpCodeExpectOpPrereqError(op, "Cannot use drained primary node")

  def testNonVmCapableNode(self):
    self.node1.vm_capable = False
    op = self.CopyOpCode(self.diskless_op,
                         pnode=self.node1.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Cannot use non-vm_capable primary node")

  def testNonEnabledHypervisor(self):
    self.cluster.enabled_hypervisors = [constants.HT_XEN_HVM]
    op = self.CopyOpCode(self.diskless_op,
                         hypervisor=constants.HT_FAKE)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Selected hypervisor .* not enabled in the cluster")

  def testAddTag(self):
    op = self.CopyOpCode(self.diskless_op,
                         tags=["tag"])
    self.ExecOpCode(op)

  def testInvalidTag(self):
    op = self.CopyOpCode(self.diskless_op,
                         tags=["too_long" * 20])
    self.ExecOpCodeExpectException(op, errors.TagError, "Tag too long")

  def testPingableInstanceName(self):
    self.netutils_mod.TcpPing.return_value = True
    op = self.CopyOpCode(self.diskless_op)
    self.ExecOpCodeExpectOpPrereqError(
      op, "IP .* of instance diskless.example.com already in use")

  def testPrimaryIsSecondaryNode(self):
    op = self.CopyOpCode(self.drbd_op,
                         snode=self.drbd_op.pnode)
    self.ExecOpCodeExpectOpPrereqError(
      op, "The secondary node cannot be the primary node")

  def testPrimarySecondaryDifferentNodeGroups(self):
    group = self.cfg.AddNewNodeGroup()
    self.node2.group = group.uuid
    op = self.CopyOpCode(self.drbd_op)
    self.ExecOpCode(op)
    self.mcpu.assertLogContainsRegex(
      "The primary and secondary nodes are in two different node groups")

  def testExclusiveStorageUnsupportedDiskTemplate(self):
    self.node1.ndparams[constants.ND_EXCLUSIVE_STORAGE] = True
    op = self.CopyOpCode(self.drbd_op)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk template drbd not supported with exclusive storage")

  def testAdoptPlain(self):
    self.rpc.call_lv_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {
          "xenvg/mock_disk_1": (10000, None, False)
        }) \
        .Build()
    op = self.CopyOpCode(self.plain_op)
    op.disks[0].update({constants.IDISK_ADOPT: "mock_disk_1"})
    self.ExecOpCode(op)

  def testAdoptPlainMissingLv(self):
    self.rpc.call_lv_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {}) \
        .Build()
    op = self.CopyOpCode(self.plain_op)
    op.disks[0].update({constants.IDISK_ADOPT: "mock_disk_1"})
    self.ExecOpCodeExpectOpPrereqError(op, "Missing logical volume")

  def testAdoptPlainOnlineLv(self):
    self.rpc.call_lv_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {
          "xenvg/mock_disk_1": (10000, None, True)
        }) \
        .Build()
    op = self.CopyOpCode(self.plain_op)
    op.disks[0].update({constants.IDISK_ADOPT: "mock_disk_1"})
    self.ExecOpCodeExpectOpPrereqError(
      op, "Online logical volumes found, cannot adopt")

  def testAdoptBlock(self):
    self.rpc.call_bdev_sizes.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {
          "/dev/disk/block0": 10000
        }) \
        .Build()
    op = self.CopyOpCode(self.block_op)
    self.ExecOpCode(op)

  def testAdoptBlockDuplicateNames(self):
    op = self.CopyOpCode(self.block_op,
                         disks=[{
                           constants.IDISK_SIZE: 0,
                           constants.IDISK_ADOPT: "/dev/disk/block0"
                         }, {
                           constants.IDISK_SIZE: 0,
                           constants.IDISK_ADOPT: "/dev/disk/block0"
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Duplicate disk names given for adoption")

  def testAdoptBlockInvalidNames(self):
    op = self.CopyOpCode(self.block_op,
                         disks=[{
                           constants.IDISK_SIZE: 0,
                           constants.IDISK_ADOPT: "/invalid/block0"
                         }])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Device node.* lie outside .* and cannot be adopted")

  def testAdoptBlockMissingDisk(self):
    self.rpc.call_bdev_sizes.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {}) \
        .Build()
    op = self.CopyOpCode(self.block_op)
    self.ExecOpCodeExpectOpPrereqError(op, "Missing block device")

  def testNoWaitForSyncDrbd(self):
    op = self.CopyOpCode(self.drbd_op,
                         wait_for_sync=False)
    self.ExecOpCode(op)

  def testNoWaitForSyncPlain(self):
    op = self.CopyOpCode(self.plain_op,
                         wait_for_sync=False)
    self.ExecOpCode(op)

  def testImportPlainFromGivenSrcNode(self):
    exp_info = """
[export]
version=0
os=%s
[instance]
name=old_name.example.com
""" % self.os.name

    self.rpc.call_export_info.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, exp_info)
    op = self.CopyOpCode(self.plain_op,
                         mode=constants.INSTANCE_IMPORT,
                         src_node=self.master.name)
    self.ExecOpCode(op)

  def testImportPlainWithoutSrcNodeNotFound(self):
    op = self.CopyOpCode(self.plain_op,
                         mode=constants.INSTANCE_IMPORT)
    self.ExecOpCodeExpectOpPrereqError(
      op, "No export found for relative path")

  def testImportPlainWithoutSrcNode(self):
    exp_info = """
[export]
version=0
os=%s
[instance]
name=old_name.example.com
""" % self.os.name

    self.rpc.call_export_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {"mock_path": {}}) \
        .Build()
    self.rpc.call_export_info.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, exp_info)

    op = self.CopyOpCode(self.plain_op,
                         mode=constants.INSTANCE_IMPORT,
                         src_path="mock_path")
    self.ExecOpCode(op)

  def testImportPlainCorruptExportInfo(self):
    exp_info = ""
    self.rpc.call_export_info.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, exp_info)
    op = self.CopyOpCode(self.plain_op,
                         mode=constants.INSTANCE_IMPORT,
                         src_node=self.master.name)
    self.ExecOpCodeExpectException(op, errors.ProgrammerError,
                                   "Corrupted export config")

  def testImportPlainWrongExportInfoVersion(self):
    exp_info = """
[export]
version=1
"""
    self.rpc.call_export_info.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, exp_info)
    op = self.CopyOpCode(self.plain_op,
                         mode=constants.INSTANCE_IMPORT,
                         src_node=self.master.name)
    self.ExecOpCodeExpectOpPrereqError(op, "Wrong export version")

  def testImportPlainWithParametersAndImport(self):
    exp_info = """
[export]
version=0
os=%s
[instance]
name=old_name.example.com
disk0_size=1024
disk1_size=1500
disk1_dump=mock_path
nic0_mode=bridged
nic0_link=br_mock
nic0_mac=f6:ab:f4:45:d1:af
nic0_ip=192.0.2.1
tags=tag1 tag2
hypervisor=xen-hvm
[hypervisor]
boot_order=cd
[backend]
memory=1024
vcpus=8
[os]
param1=val1
""" % self.os.name

    self.rpc.call_export_info.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, exp_info)
    self.rpc.call_import_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, "daemon_name")
    self.rpc.call_impexp_status.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master,
                                    [
                                      objects.ImportExportStatus(exit_status=0)
                                    ])
    self.rpc.call_impexp_cleanup.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)

    op = self.CopyOpCode(self.plain_op,
                         disks=[],
                         nics=[],
                         tags=[],
                         hypervisor=None,
                         hvparams={},
                         mode=constants.INSTANCE_IMPORT,
                         src_node=self.master.name)
    self.ExecOpCode(op)


class TestDiskTemplateDiskTypeBijection(TestLUInstanceCreate):
  """Tests that one disk template corresponds to exactly one disk type."""

  def GetSingleInstance(self):
    instances = self.cfg.GetInstancesInfoByFilter(lambda _: True)
    self.assertEqual(len(instances), 1,
      "Expected 1 instance, got\n%s" % instances)
    return list(instances.values())[0]

  def testDiskTemplateLogicalIdBijectionDiskless(self):
    op = self.CopyOpCode(self.diskless_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_DISKLESS)
    self.assertEqual(instance.disks, [])

  def testDiskTemplateLogicalIdBijectionPlain(self):
    op = self.CopyOpCode(self.plain_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_PLAIN)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_PLAIN)

  def testDiskTemplateLogicalIdBijectionBlock(self):
    self.rpc.call_bdev_sizes.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {
          "/dev/disk/block0": 10000
        }) \
        .Build()
    op = self.CopyOpCode(self.block_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_BLOCK)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_BLOCK)

  def testDiskTemplateLogicalIdBijectionDrbd(self):
    op = self.CopyOpCode(self.drbd_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_DRBD8)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_DRBD8)

  def testDiskTemplateLogicalIdBijectionFile(self):
    op = self.CopyOpCode(self.file_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_FILE)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_FILE)

  def testDiskTemplateLogicalIdBijectionSharedFile(self):
    self.cluster.shared_file_storage_dir = '/tmp'
    op = self.CopyOpCode(self.shared_file_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_SHARED_FILE)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_SHARED_FILE)

  def testDiskTemplateLogicalIdBijectionGluster(self):
    self.cluster.gluster_storage_dir = '/tmp'
    op = self.CopyOpCode(self.gluster_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_GLUSTER)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_GLUSTER)

  def testDiskTemplateLogicalIdBijectionRbd(self):
    op = self.CopyOpCode(self.rbd_op)
    self.ExecOpCode(op)
    instance = self.GetSingleInstance()
    self.assertEqual(instance.disk_template, constants.DT_RBD)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    self.assertEqual(disks[0].dev_type, constants.DT_RBD)


class TestCheckOSVariant(CmdlibTestCase):
  def testNoVariantsSupported(self):
    os = self.cfg.CreateOs(supported_variants=[])
    self.assertRaises(backend.RPCFail, backend._CheckOSVariant,
                      os, "os+variant")

  def testNoVariantGiven(self):
    os = self.cfg.CreateOs(supported_variants=["default"])
    self.assertRaises(backend.RPCFail, backend._CheckOSVariant,
                      os, "os")

  def testWrongVariantGiven(self):
    os = self.cfg.CreateOs(supported_variants=["default"])
    self.assertRaises(backend.RPCFail, backend._CheckOSVariant,
                      os, "os+wrong_variant")

  def testOkWithVariant(self):
    os = self.cfg.CreateOs(supported_variants=["default"])
    backend._CheckOSVariant(os, "os+default")

  def testOkWithoutVariant(self):
    os = self.cfg.CreateOs(supported_variants=[])
    backend._CheckOSVariant(os, "os")


class TestCheckTargetNodeIPolicy(TestLUInstanceCreate):
  def setUp(self):
    super(TestCheckTargetNodeIPolicy, self).setUp()

    self.op = self.diskless_op

    self.instance = self.cfg.AddNewInstance()
    self.target_group = self.cfg.AddNewNodeGroup()
    self.target_node = self.cfg.AddNewNode(group=self.target_group)

  @withLockedLU
  def testNoViolation(self, lu):
    compute_recoder = mock.Mock(return_value=[])
    instance.CheckTargetNodeIPolicy(lu, NotImplemented, self.instance,
                                    self.target_node, NotImplemented,
                                    _compute_fn=compute_recoder)
    self.assertTrue(compute_recoder.called)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testNoIgnore(self, lu):
    compute_recoder = mock.Mock(return_value=["mem_size not in range"])
    self.assertRaises(errors.OpPrereqError, instance.CheckTargetNodeIPolicy,
                      lu, NotImplemented, self.instance,
                      self.target_node, NotImplemented,
                      _compute_fn=compute_recoder)
    self.assertTrue(compute_recoder.called)
    self.mcpu.assertLogIsEmpty()

  @withLockedLU
  def testIgnoreViolation(self, lu):
    compute_recoder = mock.Mock(return_value=["mem_size not in range"])
    instance.CheckTargetNodeIPolicy(lu, NotImplemented, self.instance,
                                    self.target_node, NotImplemented,
                                    ignore=True, _compute_fn=compute_recoder)
    self.assertTrue(compute_recoder.called)
    msg = ("Instance does not meet target node group's .* instance policy:"
           " mem_size not in range")
    self.mcpu.assertLogContainsRegex(msg)


class TestIndexOperations(unittest.TestCase):

  """Test if index operations on containers work as expected."""

  def testGetIndexFromIdentifierTail(self):
    """Check if -1 is translated to tail index."""
    container = ['item1134']

    idx = instance_utils.GetIndexFromIdentifier("-1", "test", container)
    self.assertEqual(1, idx)

  def testGetIndexFromIdentifierEmpty(self):
    """Check if empty containers return 0 as index."""
    container = []

    idx = instance_utils.GetIndexFromIdentifier("0", "test", container)
    self.assertEqual(0, idx)
    idx = instance_utils.GetIndexFromIdentifier("-1", "test", container)
    self.assertEqual(0, idx)

  def testGetIndexFromIdentifierError(self):
    """Check if wrong input raises an exception."""
    container = []

    self.assertRaises(errors.OpPrereqError,
                      instance_utils.GetIndexFromIdentifier,
                      "lala", "test", container)

  def testGetIndexFromIdentifierOffByOne(self):
    """Check for off-by-one errors."""
    container = []

    self.assertRaises(IndexError, instance_utils.GetIndexFromIdentifier,
                      "1", "test", container)

  def testGetIndexFromIdentifierOutOfRange(self):
    """Check for identifiers out of the container range."""
    container = []

    self.assertRaises(IndexError, instance_utils.GetIndexFromIdentifier,
                      "-1134", "test", container)
    self.assertRaises(IndexError, instance_utils.GetIndexFromIdentifier,
                      "1134", "test", container)

  def testInsertItemtoIndex(self):
    """Test if we can insert an item to a container at a specified index."""
    container = []

    instance_utils.InsertItemToIndex(0, 2, container)
    self.assertEqual([2], container)

    instance_utils.InsertItemToIndex(0, 1, container)
    self.assertEqual([1, 2], container)

    instance_utils.InsertItemToIndex(-1, 3, container)
    self.assertEqual([1, 2, 3], container)

    self.assertRaises(AssertionError, instance_utils.InsertItemToIndex, -2,
                      1134, container)

    self.assertRaises(AssertionError, instance_utils.InsertItemToIndex, 4, 1134,
                      container)


class TestApplyContainerMods(unittest.TestCase):

  def applyAndAssert(self, container, inp, expected_container,
                     expected_chgdesc=[]):
    """Apply a list of changes to a container and check the container state

    Parameters:
    @type container: List
    @param container: The container on which we will apply the changes
    @type inp: List<(action, index, object)>
    @param inp: The list of changes, a tupple with three elements:
                i. action, e.g. constants.DDM_ADD
                ii. index, e.g. -1, 0, 10
                iii. object (any type)
    @type expected: List
    @param expected: The expected state of the container
    @type chgdesc: List
    @param chgdesc: List of applied changes


    """
    chgdesc = []
    mods = instance_utils.PrepareContainerMods(inp, None)
    instance_utils.ApplyContainerMods("test", container, chgdesc, mods,
                                      None, None, None, None, None)
    self.assertEqual(container, expected_container)
    self.assertEqual(chgdesc, expected_chgdesc)

  def _insertContainerSuccessFn(self, op):
    container = []
    inp = [(op, -1, "Hello"),
           (op, -1, "World"),
           (op, 0, "Start"),
           (op, -1, "End"),
           ]
    expected = ["Start", "Hello", "World", "End"]
    self.applyAndAssert(container, inp, expected)

    inp = [(op, 0, "zero"),
           (op, 3, "Added"),
           (op, 5, "four"),
           (op, 7, "xyz"),
           ]
    expected = ["zero", "Start", "Hello", "Added", "World", "four", "End",
                "xyz"]
    self.applyAndAssert(container, inp, expected)

  def _insertContainerErrorFn(self, op):
    container = []
    expected = None

    inp = [(op, 1, "error"), ]
    self.assertRaises(IndexError, self.applyAndAssert, container, inp,
                      expected)

    inp = [(op, -2, "error"), ]
    self.assertRaises(IndexError, self.applyAndAssert, container, inp,
                      expected)

  def _extractContainerSuccessFn(self, op):
    container = ["item1", "item2", "item3", "item4", "item5"]
    inp = [(op, -1, None),
           (op, -0, None),
           (op, 1, None),
           ]
    expected = ["item2", "item4"]
    chgdesc = [('test/4', op),
               ('test/0', op),
               ('test/1', op)
               ]
    self.applyAndAssert(container, inp, expected, chgdesc)

  def _extractContainerErrorFn(self, op):
    container = []
    expected = None

    inp = [(op, 0, None), ]
    self.assertRaises(IndexError, self.applyAndAssert, container, inp,
                      expected)

    inp = [(op, -1, None), ]
    self.assertRaises(IndexError, self.applyAndAssert, container, inp,
                      expected)

    inp = [(op, 2, None), ]
    self.assertRaises(IndexError, self.applyAndAssert, container, inp,
                      expected)
    container = [""]
    inp = [(op, 0, None), ]
    expected = None
    self.assertRaises(AssertionError, self.applyAndAssert, container, inp,
                      expected)

  def testEmptyContainer(self):
    container = []
    chgdesc = []
    instance_utils.ApplyContainerMods("test", container, chgdesc, [], None,
                                      None, None, None, None)
    self.assertEqual(container, [])
    self.assertEqual(chgdesc, [])

  def testAddSuccess(self):
    self._insertContainerSuccessFn(constants.DDM_ADD)

  def testAddError(self):
    self._insertContainerErrorFn(constants.DDM_ADD)

  def testAttachSuccess(self):
    self._insertContainerSuccessFn(constants.DDM_ATTACH)

  def testAttachError(self):
    self._insertContainerErrorFn(constants.DDM_ATTACH)

  def testRemoveSuccess(self):
    self._extractContainerSuccessFn(constants.DDM_REMOVE)

  def testRemoveError(self):
    self._extractContainerErrorFn(constants.DDM_REMOVE)

  def testDetachSuccess(self):
    self._extractContainerSuccessFn(constants.DDM_DETACH)

  def testDetachError(self):
    self._extractContainerErrorFn(constants.DDM_DETACH)

  def testModify(self):
    container = ["item 1", "item 2"]
    mods = instance_utils.PrepareContainerMods([
      (constants.DDM_MODIFY, -1, "a"),
      (constants.DDM_MODIFY, 0, "b"),
      (constants.DDM_MODIFY, 1, "c"),
      ], None)
    chgdesc = []
    instance_utils.ApplyContainerMods("test", container, chgdesc, mods,
                                      None, None, None, None, None)
    self.assertEqual(container, ["item 1", "item 2"])
    self.assertEqual(chgdesc, [])

    for idx in [-2, len(container) + 1]:
      mods = instance_utils.PrepareContainerMods([
        (constants.DDM_MODIFY, idx, "error"),
        ], None)
      self.assertRaises(IndexError, instance_utils.ApplyContainerMods,
                        "test", container, None, mods, None, None, None, None,
                        None)

  @staticmethod
  def _CreateTestFn(idx, params, private):
    private.data = ("add", idx, params)
    return ((100 * idx, params), [
      ("test/%s" % idx, hex(idx)),
      ])

  @staticmethod
  def _AttachTestFn(idx, params, private):
    private.data = ("attach", idx, params)
    return ((100 * idx, params), [
      ("test/%s" % idx, hex(idx)),
      ])

  @staticmethod
  def _ModifyTestFn(idx, item, params, private):
    private.data = ("modify", idx, params)
    return [
      ("test/%s" % idx, "modify %s" % params),
      ]

  @staticmethod
  def _RemoveTestFn(idx, item, private):
    private.data = ("remove", idx, item)

  @staticmethod
  def _DetachTestFn(idx, item, private):
    private.data = ("detach", idx, item)

  def testAddWithCreateFunction(self):
    container = []
    chgdesc = []
    mods = instance_utils.PrepareContainerMods([
      (constants.DDM_ADD, -1, "Hello"),
      (constants.DDM_ADD, -1, "World"),
      (constants.DDM_ADD, 0, "Start"),
      (constants.DDM_ADD, -1, "End"),
      (constants.DDM_REMOVE, 2, None),
      (constants.DDM_MODIFY, -1, "foobar"),
      (constants.DDM_REMOVE, 2, None),
      (constants.DDM_ADD, 1, "More"),
      (constants.DDM_DETACH, -1, None),
      (constants.DDM_ATTACH, 0, "Hello"),
      ], mock.Mock)
    instance_utils.ApplyContainerMods("test", container, chgdesc, mods,
                                      self._CreateTestFn, self._AttachTestFn,
                                      self._ModifyTestFn, self._RemoveTestFn,
                                      self._DetachTestFn)
    self.assertEqual(container, [
      (000, "Hello"),
      (000, "Start"),
      (100, "More"),
      ])
    self.assertEqual(chgdesc, [
      ("test/0", "0x0"),
      ("test/1", "0x1"),
      ("test/0", "0x0"),
      ("test/3", "0x3"),
      ("test/2", "remove"),
      ("test/2", "modify foobar"),
      ("test/2", "remove"),
      ("test/1", "0x1"),
      ("test/2", "detach"),
      ("test/0", "0x0"),
      ])
    self.assertTrue(compat.all(op == private.data[0]
                               for (op, _, _, private) in mods))
    self.assertEqual([private.data for (op, _, _, private) in mods], [
      ("add", 0, "Hello"),
      ("add", 1, "World"),
      ("add", 0, "Start"),
      ("add", 3, "End"),
      ("remove", 2, (100, "World")),
      ("modify", 2, "foobar"),
      ("remove", 2, (300, "End")),
      ("add", 1, "More"),
      ("detach", 2, (000, "Hello")),
      ("attach", 0, "Hello"),
      ])


class _FakeConfigForGenDiskTemplate(ConfigMock):
  def __init__(self):
    super(_FakeConfigForGenDiskTemplate, self).__init__()

    self._unique_id = itertools.count()
    self._drbd_minor = itertools.count(20)
    self._port = itertools.count(constants.FIRST_DRBD_PORT)
    self._secret = itertools.count()

  def GenerateUniqueID(self, ec_id):
    return "ec%s-uq%s" % (ec_id, next(self._unique_id))

  def AllocateDRBDMinor(self, nodes, disk):
    return [next(self._drbd_minor)
            for _ in nodes]

  def AllocatePort(self):
    return next(self._port)

  def GenerateDRBDSecret(self, ec_id):
    return "ec%s-secret%s" % (ec_id, next(self._secret))


class TestGenerateDiskTemplate(CmdlibTestCase):
  def setUp(self):
    super(TestGenerateDiskTemplate, self).setUp()

    self.cfg = _FakeConfigForGenDiskTemplate()
    self.cluster.enabled_disk_templates = list(constants.DISK_TEMPLATES)

    self.nodegroup = self.cfg.AddNewNodeGroup(name="ng")

    self.lu = self.GetMockLU()

  @staticmethod
  def GetDiskParams():
    return copy.deepcopy(constants.DISK_DT_DEFAULTS)

  def testWrongDiskTemplate(self):
    gdt = instance_storage.GenerateDiskTemplate
    disk_template = "##unknown##"

    assert disk_template not in constants.DISK_TEMPLATES

    self.assertRaises(errors.OpPrereqError, gdt, self.lu, disk_template,
                      "inst26831.example.com", "node30113.example.com", [], [],
                      NotImplemented, NotImplemented, 0, self.lu.LogInfo,
                      self.GetDiskParams())

  def testDiskless(self):
    gdt = instance_storage.GenerateDiskTemplate

    result = gdt(self.lu, constants.DT_DISKLESS, "inst27734.example.com",
                 "node30113.example.com", [], [],
                 NotImplemented, NotImplemented, 0, self.lu.LogInfo,
                 self.GetDiskParams())
    self.assertEqual(result, [])

  def _TestTrivialDisk(self, template, disk_info, base_index, exp_dev_type,
                       file_storage_dir=NotImplemented,
                       file_driver=NotImplemented):
    gdt = instance_storage.GenerateDiskTemplate

    for params in disk_info:
      utils.ForceDictType(params, constants.IDISK_PARAMS_TYPES)

    # Check if non-empty list of secondaries is rejected
    self.assertRaises(errors.ProgrammerError, gdt, self.lu,
                      template, "inst25088.example.com",
                      "node185.example.com", ["node323.example.com"], [],
                      NotImplemented, NotImplemented, base_index,
                      self.lu.LogInfo, self.GetDiskParams())

    result = gdt(self.lu, template, "inst21662.example.com",
                 "node21741.example.com", [],
                 disk_info, file_storage_dir, file_driver, base_index,
                 self.lu.LogInfo, self.GetDiskParams())

    for (idx, disk) in enumerate(result):
      self.assertTrue(isinstance(disk, objects.Disk))
      self.assertEqual(disk.dev_type, exp_dev_type)
      self.assertEqual(disk.size, disk_info[idx][constants.IDISK_SIZE])
      self.assertEqual(disk.mode, disk_info[idx][constants.IDISK_MODE])
      self.assertTrue(disk.children is None)

    self._CheckIvNames(result, base_index, base_index + len(disk_info))
    _UpdateIvNames(base_index, result)
    self._CheckIvNames(result, base_index, base_index + len(disk_info))

    return result

  def _CheckIvNames(self, disks, base_index, end_index):
    self.assertEqual([d.iv_name for d in disks],
                     ["disk/%s" % i for i in range(base_index, end_index)])

  def testPlain(self):
    disk_info = [{
      constants.IDISK_SIZE: 1024,
      constants.IDISK_MODE: constants.DISK_RDWR,
      }, {
      constants.IDISK_SIZE: 4096,
      constants.IDISK_VG: "othervg",
      constants.IDISK_MODE: constants.DISK_RDWR,
      }]

    result = self._TestTrivialDisk(constants.DT_PLAIN, disk_info, 3,
                                   constants.DT_PLAIN)

    self.assertEqual([d.logical_id for d in result], [
      ("xenvg", "ec1-uq0.disk3"),
      ("othervg", "ec1-uq1.disk4"),
      ])
    self.assertEqual([d.nodes for d in result], [
                     ["node21741.example.com"], ["node21741.example.com"]])


  def testFile(self):
    # anything != DT_FILE would do here
    self.cluster.enabled_disk_templates = [constants.DT_PLAIN]
    self.assertRaises(errors.OpPrereqError, self._TestTrivialDisk,
                      constants.DT_FILE, [], 0, NotImplemented)
    self.assertRaises(errors.OpPrereqError, self._TestTrivialDisk,
                      constants.DT_SHARED_FILE, [], 0, NotImplemented)

    for disk_template in constants.DTS_FILEBASED:
      disk_info = [{
        constants.IDISK_SIZE: 80 * 1024,
        constants.IDISK_MODE: constants.DISK_RDONLY,
        }, {
        constants.IDISK_SIZE: 4096,
        constants.IDISK_MODE: constants.DISK_RDWR,
        }, {
        constants.IDISK_SIZE: 6 * 1024,
        constants.IDISK_MODE: constants.DISK_RDWR,
        }]

      self.cluster.enabled_disk_templates = [disk_template]
      result = self._TestTrivialDisk(
        disk_template, disk_info, 2, disk_template,
        file_storage_dir="/tmp", file_driver=constants.FD_BLKTAP)

      if disk_template == constants.DT_GLUSTER:
        # Here "inst21662.example.com" is actually the instance UUID, not its
        # name, so while this result looks wrong, it is actually correct.
        expected = [(constants.FD_BLKTAP,
                     'ganeti/inst21662.example.com.%d' % x)
                    for x in (2,3,4)]
        self.assertEqual([d.logical_id for d in result],
                         expected)
        self.assertEqual([d.nodes for d in result], [
          [], [], []])
      else:
        if disk_template == constants.DT_FILE:
          self.assertEqual([d.nodes for d in result], [
            ["node21741.example.com"], ["node21741.example.com"],
            ["node21741.example.com"]])
        else:
          self.assertEqual([d.nodes for d in result], [
            [], [], []])

        for (idx, disk) in enumerate(result):
          (file_driver, file_storage_dir) = disk.logical_id
          dir_fmt = r"^/tmp/.*\.%s\.disk%d$" % (disk_template, idx + 2)
          self.assertEqual(file_driver, constants.FD_BLKTAP)
          # FIXME: use assertIsNotNone when py 2.7 is minimum supported version
          self.assertNotEqual(re.match(dir_fmt, file_storage_dir), None)

  def testBlock(self):
    disk_info = [{
      constants.IDISK_SIZE: 8 * 1024,
      constants.IDISK_MODE: constants.DISK_RDWR,
      constants.IDISK_ADOPT: "/tmp/some/block/dev",
      }]

    result = self._TestTrivialDisk(constants.DT_BLOCK, disk_info, 10,
                                   constants.DT_BLOCK)

    self.assertEqual([d.logical_id for d in result], [
      (constants.BLOCKDEV_DRIVER_MANUAL, "/tmp/some/block/dev"),
      ])
    self.assertEqual([d.nodes for d in result], [[]])

  def testRbd(self):
    disk_info = [{
      constants.IDISK_SIZE: 8 * 1024,
      constants.IDISK_MODE: constants.DISK_RDONLY,
      }, {
      constants.IDISK_SIZE: 100 * 1024,
      constants.IDISK_MODE: constants.DISK_RDWR,
      }]

    result = self._TestTrivialDisk(constants.DT_RBD, disk_info, 0,
                                   constants.DT_RBD)

    self.assertEqual([d.logical_id for d in result], [
      ("rbd", "ec1-uq0.rbd.disk0"),
      ("rbd", "ec1-uq1.rbd.disk1"),
      ])
    self.assertEqual([d.nodes for d in result], [[], []])

  def testDrbd8(self):
    gdt = instance_storage.GenerateDiskTemplate
    drbd8_defaults = constants.DISK_LD_DEFAULTS[constants.DT_DRBD8]
    drbd8_default_metavg = drbd8_defaults[constants.LDP_DEFAULT_METAVG]

    disk_info = [{
      constants.IDISK_SIZE: 1024,
      constants.IDISK_MODE: constants.DISK_RDWR,
      }, {
      constants.IDISK_SIZE: 100 * 1024,
      constants.IDISK_MODE: constants.DISK_RDONLY,
      constants.IDISK_METAVG: "metavg",
      }, {
      constants.IDISK_SIZE: 4096,
      constants.IDISK_MODE: constants.DISK_RDWR,
      constants.IDISK_VG: "vgxyz",
      },
      ]

    exp_logical_ids = [
      [
        (self.lu.cfg.GetVGName(), "ec1-uq0.disk0_data"),
        (drbd8_default_metavg, "ec1-uq0.disk0_meta"),
      ], [
        (self.lu.cfg.GetVGName(), "ec1-uq1.disk1_data"),
        ("metavg", "ec1-uq1.disk1_meta"),
      ], [
        ("vgxyz", "ec1-uq2.disk2_data"),
        (drbd8_default_metavg, "ec1-uq2.disk2_meta"),
      ]]

    exp_nodes = ["node1334.example.com", "node12272.example.com"]

    assert len(exp_logical_ids) == len(disk_info)

    for params in disk_info:
      utils.ForceDictType(params, constants.IDISK_PARAMS_TYPES)

    # Check if empty list of secondaries is rejected
    self.assertRaises(errors.ProgrammerError, gdt, self.lu, constants.DT_DRBD8,
                      "inst827.example.com", "node1334.example.com", [],
                      disk_info, NotImplemented, NotImplemented, 0,
                      self.lu.LogInfo, self.GetDiskParams())

    result = gdt(self.lu, constants.DT_DRBD8, "inst827.example.com",
                 "node1334.example.com", ["node12272.example.com"],
                 disk_info, NotImplemented, NotImplemented, 0, self.lu.LogInfo,
                 self.GetDiskParams())

    for (idx, disk) in enumerate(result):
      self.assertTrue(isinstance(disk, objects.Disk))
      self.assertEqual(disk.dev_type, constants.DT_DRBD8)
      self.assertEqual(disk.size, disk_info[idx][constants.IDISK_SIZE])
      self.assertEqual(disk.mode, disk_info[idx][constants.IDISK_MODE])

      for child in disk.children:
        self.assertTrue(isinstance(disk, objects.Disk))
        self.assertEqual(child.dev_type, constants.DT_PLAIN)
        self.assertTrue(child.children is None)
        self.assertEqual(child.nodes, exp_nodes)

      self.assertEqual([d.logical_id for d in disk.children],
                       exp_logical_ids[idx])
      self.assertEqual(disk.nodes, exp_nodes)

      self.assertEqual(len(disk.children), 2)
      self.assertEqual(disk.children[0].size, disk.size)
      self.assertEqual(disk.children[1].size, constants.DRBD_META_SIZE)

    self._CheckIvNames(result, 0, len(disk_info))
    _UpdateIvNames(0, result)
    self._CheckIvNames(result, 0, len(disk_info))

    self.assertEqual([d.logical_id for d in result], [
      ("node1334.example.com", "node12272.example.com",
       constants.FIRST_DRBD_PORT, 20, 21, "ec1-secret0"),
      ("node1334.example.com", "node12272.example.com",
       constants.FIRST_DRBD_PORT + 1, 22, 23, "ec1-secret1"),
      ("node1334.example.com", "node12272.example.com",
       constants.FIRST_DRBD_PORT + 2, 24, 25, "ec1-secret2"),
      ])


class _DiskPauseTracker:
  def __init__(self):
    self.history = []

  def __call__(self, instance_disks, pause):
    (disks, instance) = instance_disks
    disk_uuids = [d.uuid for d in disks]
    assert not (set(disk_uuids) - set(instance.disks))

    self.history.extend((i.logical_id, i.size, pause)
                        for i in disks)

    return (True, [True] * len(disks))


class _ConfigForDiskWipe:
  def __init__(self, exp_node_uuid, disks):
    self._exp_node_uuid = exp_node_uuid
    self._disks = disks

  def GetNodeName(self, node_uuid):
    assert node_uuid == self._exp_node_uuid
    return "name.of.expected.node"

  def GetInstanceDisks(self, _):
    return self._disks


class _RpcForDiskWipe:
  def __init__(self, exp_node, pause_cb, wipe_cb):
    self._exp_node = exp_node
    self._pause_cb = pause_cb
    self._wipe_cb = wipe_cb

  def call_blockdev_pause_resume_sync(self, node, disks, pause):
    assert node == self._exp_node
    return rpc.RpcResult(data=self._pause_cb(disks, pause))

  def call_blockdev_wipe(self, node, bdev, offset, size):
    assert node == self._exp_node
    return rpc.RpcResult(data=self._wipe_cb(bdev, offset, size))


class _DiskWipeProgressTracker:
  def __init__(self, start_offset):
    self._start_offset = start_offset
    self.progress = {}

  def __call__(self, disk_info, offset, size):
    (disk, _) = disk_info
    assert isinstance(offset, int)
    assert isinstance(size, int)

    max_chunk_size = (disk.size / 100.0 * constants.MIN_WIPE_CHUNK_PERCENT)

    assert offset >= self._start_offset
    assert (offset + size) <= disk.size

    assert size > 0
    assert size <= constants.MAX_WIPE_CHUNK
    assert size <= max_chunk_size

    assert offset == self._start_offset or disk.logical_id in self.progress

    # Keep track of progress
    cur_progress = self.progress.setdefault(disk.logical_id, self._start_offset)

    assert cur_progress == offset

    # Record progress
    self.progress[disk.logical_id] += size

    return (True, None)


class TestWipeDisks(unittest.TestCase):
  def _FailingPauseCb(self, disks_info, pause):
    (disks, _) = disks_info
    self.assertEqual(len(disks), 3)
    self.assertTrue(pause)
    # Simulate an RPC error
    return (False, "error")

  def testPauseFailure(self):
    node_name = "node1372.example.com"

    disks = [
      objects.Disk(dev_type=constants.DT_PLAIN, uuid="disk0"),
      objects.Disk(dev_type=constants.DT_PLAIN, uuid="disk1"),
      objects.Disk(dev_type=constants.DT_PLAIN, uuid="disk2"),
      ]

    lu = _FakeLU(rpc=_RpcForDiskWipe(node_name, self._FailingPauseCb,
                                     NotImplemented),
                 cfg=_ConfigForDiskWipe(node_name, disks))

    inst = objects.Instance(name="inst21201",
                            primary_node=node_name,
                            disk_template=constants.DT_PLAIN,
                            disks=[d.uuid for d in disks])

    self.assertRaises(errors.OpExecError, instance_create.WipeDisks, lu, inst)

  def _FailingWipeCb(self, disk_info, offset, size):
    # This should only ever be called for the first disk
    (disk, _) = disk_info
    self.assertEqual(disk.logical_id, "disk0")
    return (False, None)

  def testFailingWipe(self):
    node_uuid = "node13445-uuid"
    pt = _DiskPauseTracker()

    disks = [
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk0",
                   size=100 * 1024, uuid="disk0"),
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk1",
                   size=500 * 1024, uuid="disk1"),
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk2",
                   size=256, uuid="disk2"),
      ]

    lu = _FakeLU(rpc=_RpcForDiskWipe(node_uuid, pt, self._FailingWipeCb),
                 cfg=_ConfigForDiskWipe(node_uuid, disks))

    inst = objects.Instance(name="inst562",
                            primary_node=node_uuid,
                            disk_template=constants.DT_PLAIN,
                            disks=[d.uuid for d in disks])

    try:
      instance_create.WipeDisks(lu, inst)
    except errors.OpExecError as err:
      self.assertTrue(str(err), "Could not wipe disk 0 at offset 0 ")
    else:
      self.fail("Did not raise exception")

    # Check if all disks were paused and resumed
    self.assertEqual(pt.history, [
      ("disk0", 100 * 1024, True),
      ("disk1", 500 * 1024, True),
      ("disk2", 256, True),
      ("disk0", 100 * 1024, False),
      ("disk1", 500 * 1024, False),
      ("disk2", 256, False),
      ])

  def _PrepareWipeTest(self, start_offset, disks):
    node_name = "node-with-offset%s.example.com" % start_offset
    pauset = _DiskPauseTracker()
    progresst = _DiskWipeProgressTracker(start_offset)

    lu = _FakeLU(rpc=_RpcForDiskWipe(node_name, pauset, progresst),
                 cfg=_ConfigForDiskWipe(node_name, disks))

    instance = objects.Instance(name="inst3560",
                                primary_node=node_name,
                                disk_template=constants.DT_PLAIN,
                                disks=[d.uuid for d in disks])

    return (lu, instance, pauset, progresst)

  def testNormalWipe(self):
    disks = [
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk0",
                   size=1024, uuid="disk0"),
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk1",
                   size=500 * 1024, uuid="disk1"),
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk2",
                   size=128, uuid="disk2"),
      objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk3",
                   size=constants.MAX_WIPE_CHUNK, uuid="disk3"),
      ]

    (lu, inst, pauset, progresst) = self._PrepareWipeTest(0, disks)

    instance_create.WipeDisks(lu, inst)

    self.assertEqual(pauset.history, [
      ("disk0", 1024, True),
      ("disk1", 500 * 1024, True),
      ("disk2", 128, True),
      ("disk3", constants.MAX_WIPE_CHUNK, True),
      ("disk0", 1024, False),
      ("disk1", 500 * 1024, False),
      ("disk2", 128, False),
      ("disk3", constants.MAX_WIPE_CHUNK, False),
      ])

    # Ensure the complete disk has been wiped
    self.assertEqual(progresst.progress,
                     dict((i.logical_id, i.size) for i in disks))

  def testWipeWithStartOffset(self):
    for start_offset in [0, 280, 8895, 1563204]:
      disks = [
        objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk0",
                     size=128, uuid="disk0"),
        objects.Disk(dev_type=constants.DT_PLAIN, logical_id="disk1",
                     size=start_offset + (100 * 1024), uuid="disk1"),
        ]

      (lu, inst, pauset, progresst) = \
        self._PrepareWipeTest(start_offset, disks)

      # Test start offset with only one disk
      instance_create.WipeDisks(lu, inst,
                                disks=[(1, disks[1], start_offset)])

      # Only the second disk may have been paused and wiped
      self.assertEqual(pauset.history, [
        ("disk1", start_offset + (100 * 1024), True),
        ("disk1", start_offset + (100 * 1024), False),
        ])
      self.assertEqual(progresst.progress, {
        "disk1": disks[1].size,
        })


class TestCheckOpportunisticLocking(unittest.TestCase):
  class OpTest(opcodes.OpCode):
    OP_PARAMS = [
      ("opportunistic_locking", False, ht.TBool, None),
      ("iallocator", None, ht.TMaybe(ht.TNonEmptyString), "")
      ]

  @classmethod
  def _MakeOp(cls, **kwargs):
    op = cls.OpTest(**kwargs)
    op.Validate(True)
    return op

  def testMissingAttributes(self):
    self.assertRaises(AttributeError, instance.CheckOpportunisticLocking,
                      object())

  def testDefaults(self):
    op = self._MakeOp()
    instance.CheckOpportunisticLocking(op)

  def test(self):
    for iallocator in [None, "something", "other"]:
      for opplock in [False, True]:
        op = self._MakeOp(iallocator=iallocator,
                          opportunistic_locking=opplock)
        if opplock and not iallocator:
          self.assertRaises(errors.OpPrereqError,
                            instance.CheckOpportunisticLocking, op)
        else:
          instance.CheckOpportunisticLocking(op)


class TestLUInstanceMove(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceMove, self).setUp()

    self.node = self.cfg.AddNewNode()

    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.node, ("/dev/mocked_path",
                                    "/var/run/ganeti/instance-disks/mocked_d",
                                    None))
    self.rpc.call_blockdev_remove.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, "")

    def ImportStart(node_uuid, opt, inst, component, args):
      return self.RpcResultsBuilder() \
               .CreateSuccessfulNodeResult(node_uuid,
                                           "deamon_on_%s" % node_uuid)
    self.rpc.call_import_start.side_effect = ImportStart

    def ImpExpStatus(node_uuid, name):
      return self.RpcResultsBuilder() \
               .CreateSuccessfulNodeResult(node_uuid,
                                           [objects.ImportExportStatus(
                                             exit_status=0
                                           )])
    self.rpc.call_impexp_status.side_effect = ImpExpStatus

    def ImpExpCleanup(node_uuid, name):
      return self.RpcResultsBuilder() \
               .CreateSuccessfulNodeResult(node_uuid)
    self.rpc.call_impexp_cleanup.side_effect = ImpExpCleanup

  def testMissingInstance(self):
    op = opcodes.OpInstanceMove(instance_name="missing.inst",
                                target_node=self.node.name)
    self.ExecOpCodeExpectOpPrereqError(op, "Instance 'missing.inst' not known")

  def testUncopyableDiskTemplate(self):
    inst = self.cfg.AddNewInstance(disk_template=constants.DT_SHARED_FILE)
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.node.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance disk 0 has disk type sharedfile and is not suitable"
      " for copying")

  def testAlreadyOnTargetNode(self):
    inst = self.cfg.AddNewInstance()
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.master.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance .* is already on the node .*")

  def testMoveStoppedInstance(self):
    inst = self.cfg.AddNewInstance()
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.node.name)
    self.ExecOpCode(op)

  def testMoveRunningInstance(self):
    self.rpc.call_node_info.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.node,
                           (NotImplemented, NotImplemented,
                            ({"memory_free": 10000}, ))) \
        .Build()
    self.rpc.call_instance_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.node, "")

    inst = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP)
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.node.name)
    self.ExecOpCode(op)

  def testMoveFailingStartInstance(self):
    self.rpc.call_node_info.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.node,
                           (NotImplemented, NotImplemented,
                            ({"memory_free": 10000}, ))) \
        .Build()
    self.rpc.call_instance_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.node)

    inst = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP)
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.node.name)
    self.ExecOpCodeExpectOpExecError(
      op, "Could not start instance .* on node .*")

  def testMoveFailingImpExpDaemonExitCode(self):
    inst = self.cfg.AddNewInstance()
    self.rpc.call_impexp_status.side_effect = None
    self.rpc.call_impexp_status.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.node,
                                    [objects.ImportExportStatus(
                                      exit_status=1,
                                      recent_output=["mock output"]
                                    )])
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.node.name)
    self.ExecOpCodeExpectOpExecError(op, "Errors during disk copy")

  def testMoveFailingStartImpExpDaemon(self):
    inst = self.cfg.AddNewInstance()
    self.rpc.call_import_start.side_effect = None
    self.rpc.call_import_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.node)
    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.node.name)
    self.ExecOpCodeExpectOpExecError(op, "Errors during disk copy")


class TestLUInstanceRename(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceRename, self).setUp()

    self.MockOut(instance_utils, 'netutils', self.netutils_mod)

    self.inst = self.cfg.AddNewInstance()

    self.op = opcodes.OpInstanceRename(instance_name=self.inst.name,
                                       new_name="new_name.example.com")

  def testIpCheckWithoutNameCheck(self):
    op = self.CopyOpCode(self.op,
                         ip_check=True,
                         name_check=False)
    self.ExecOpCodeExpectOpPrereqError(
      op, "IP address check requires a name check")

  def testIpAlreadyInUse(self):
    self.netutils_mod.TcpPing.return_value = True
    op = self.CopyOpCode(self.op,
                         name_check=True,
                         ip_check=True)
    self.ExecOpCodeExpectOpPrereqError(
      op, "IP .* of instance .* already in use")

  def testExistingInstanceName(self):
    self.cfg.AddNewInstance(name="new_name.example.com")
    op = self.CopyOpCode(self.op)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance .* is already in the cluster")

  def testFileInstance(self):
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, (None, None, None))
    self.rpc.call_blockdev_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, (None, None))

    inst = self.cfg.AddNewInstance(disk_template=constants.DT_FILE)
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name)
    self.ExecOpCode(op)


class TestLUInstanceMultiAlloc(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceMultiAlloc, self).setUp()

    self.inst_op = opcodes.OpInstanceCreate(instance_name="inst.example.com",
                                            disk_template=constants.DT_DRBD8,
                                            disks=[],
                                            nics=[],
                                            os_type="mock_os",
                                            hypervisor=constants.HT_XEN_HVM,
                                            mode=constants.INSTANCE_CREATE)

  def testInstanceWithIAllocator(self):
    inst = self.CopyOpCode(self.inst_op,
                           iallocator="mock")
    op = opcodes.OpInstanceMultiAlloc(instances=[inst])
    self.ExecOpCodeExpectOpPrereqError(
      op, "iallocator are not allowed to be set on instance objects")

  def testOnlySomeNodesGiven(self):
    inst1 = self.CopyOpCode(self.inst_op,
                            pnode=self.master.name)
    inst2 = self.CopyOpCode(self.inst_op)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst1, inst2])
    self.ExecOpCodeExpectOpPrereqError(
      op, "There are instance objects providing pnode/snode while others"
          " do not")

  def testMissingIAllocator(self):
    self.cluster.default_iallocator = None
    inst = self.CopyOpCode(self.inst_op)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst])
    self.ExecOpCodeExpectOpPrereqError(
      op, "No iallocator or nodes on the instances given and no cluster-wide"
          " default iallocator found")

  def testDuplicateInstanceNames(self):
    inst1 = self.CopyOpCode(self.inst_op)
    inst2 = self.CopyOpCode(self.inst_op)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst1, inst2])
    self.ExecOpCodeExpectOpPrereqError(
      op, "There are duplicate instance names")

  def testWithGivenNodes(self):
    snode = self.cfg.AddNewNode()
    inst = self.CopyOpCode(self.inst_op,
                           pnode=self.master.name,
                           snode=snode.name)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst])
    self.ExecOpCode(op)

  def testDryRun(self):
    snode = self.cfg.AddNewNode()
    inst = self.CopyOpCode(self.inst_op,
                           pnode=self.master.name,
                           snode=snode.name)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst],
                                      dry_run=True)
    self.ExecOpCode(op)

  def testWithIAllocator(self):
    snode = self.cfg.AddNewNode()
    self.iallocator_cls.return_value.result = \
      ([("inst.example.com", [self.master.name, snode.name])], [])

    inst = self.CopyOpCode(self.inst_op)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst],
                                      iallocator="mock_ialloc")
    self.ExecOpCode(op)

  def testManyInstancesWithIAllocator(self):
    snode = self.cfg.AddNewNode()

    inst1 = self.CopyOpCode(self.inst_op)
    inst2 = self.CopyOpCode(self.inst_op, instance_name="inst2.example.com")

    self.iallocator_cls.return_value.result = \
      ([("inst.example.com",  [self.master.name, snode.name]),
        ("inst2.example.com", [self.master.name, snode.name])],
       [])

    op = opcodes.OpInstanceMultiAlloc(instances=[inst1, inst2],
                                      iallocator="mock_ialloc")
    self.ExecOpCode(op)

  def testWithIAllocatorOpportunisticLocking(self):
    snode = self.cfg.AddNewNode()
    self.iallocator_cls.return_value.result = \
      ([("inst.example.com", [self.master.name, snode.name])], [])

    inst = self.CopyOpCode(self.inst_op)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst],
                                      iallocator="mock_ialloc",
                                      opportunistic_locking=True)
    self.ExecOpCode(op)

  def testFailingIAllocator(self):
    self.iallocator_cls.return_value.success = False

    inst = self.CopyOpCode(self.inst_op)
    op = opcodes.OpInstanceMultiAlloc(instances=[inst],
                                      iallocator="mock_ialloc")
    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't compute nodes using iallocator")


class TestLUInstanceSetParams(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceSetParams, self).setUp()

    self.MockOut(instance_set_params, 'netutils', self.netutils_mod)
    self.MockOut(instance_utils, 'netutils', self.netutils_mod)

    self.dev_type = constants.DT_PLAIN
    self.inst = self.cfg.AddNewInstance(disk_template=self.dev_type)
    self.op = opcodes.OpInstanceSetParams(instance_name=self.inst.name)

    self.cfg._cluster.default_iallocator=None

    self.running_inst = \
      self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP)
    self.running_op = \
      opcodes.OpInstanceSetParams(instance_name=self.running_inst.name)

    ext_disks = [self.cfg.CreateDisk(dev_type=constants.DT_EXT,
                                     params={
                                       constants.IDISK_PROVIDER: "pvdr"
                                     })]
    self.ext_storage_inst = \
      self.cfg.AddNewInstance(disk_template=constants.DT_EXT,
                              disks=ext_disks)
    self.ext_storage_op = \
      opcodes.OpInstanceSetParams(instance_name=self.ext_storage_inst.name)

    self.snode = self.cfg.AddNewNode()

    self.mocked_storage_type = constants.ST_LVM_VG
    self.mocked_storage_free = 10000
    self.mocked_master_cpu_total = 16
    self.mocked_master_memory_free = 2048
    self.mocked_snode_cpu_total = 16
    self.mocked_snode_memory_free = 512

    self.mocked_running_inst_memory = 1024
    self.mocked_running_inst_vcpus = 8
    self.mocked_running_inst_state = "running"
    self.mocked_running_inst_time = 10938474

    self.mocked_disk_uuid = "mock_uuid_1134"
    self.mocked_disk_name = "mock_disk_1134"

    bootid = "mock_bootid"
    storage_info = [
      {
        "type": self.mocked_storage_type,
        "storage_free": self.mocked_storage_free
      }
    ]
    hv_info_master = {
      "cpu_total": self.mocked_master_cpu_total,
      "memory_free": self.mocked_master_memory_free
    }
    hv_info_snode = {
      "cpu_total": self.mocked_snode_cpu_total,
      "memory_free": self.mocked_snode_memory_free
    }

    self.rpc.call_node_info.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master,
                           (bootid, storage_info, (hv_info_master, ))) \
        .AddSuccessfulNode(self.snode,
                           (bootid, storage_info, (hv_info_snode, ))) \
        .Build()

    def _InstanceInfo(_, instance, __, ___):
      if instance in [self.inst.name, self.ext_storage_inst.name]:
        return self.RpcResultsBuilder() \
          .CreateSuccessfulNodeResult(self.master, None)
      elif instance == self.running_inst.name:
        return self.RpcResultsBuilder() \
          .CreateSuccessfulNodeResult(
            self.master, {
              "memory": self.mocked_running_inst_memory,
              "vcpus": self.mocked_running_inst_vcpus,
              "state": self.mocked_running_inst_state,
              "time": self.mocked_running_inst_time
            })
      else:
        raise AssertionError()
    self.rpc.call_instance_info.side_effect = _InstanceInfo

    self.rpc.call_bridges_exist.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)

    self.rpc.call_blockdev_getmirrorstatus.side_effect = \
      lambda node, _: self.RpcResultsBuilder() \
                        .CreateSuccessfulNodeResult(node, [])

    self.rpc.call_blockdev_shutdown.side_effect = \
      lambda node, _: self.RpcResultsBuilder() \
                        .CreateSuccessfulNodeResult(node, [])

  def testNoChanges(self):
    op = self.CopyOpCode(self.op)
    self.ExecOpCodeExpectOpPrereqError(op, "No changes submitted")

  def testGlobalHvparams(self):
    op = self.CopyOpCode(self.op,
                         hvparams={constants.HV_MIGRATION_PORT: 1234})
    self.ExecOpCodeExpectOpPrereqError(
      op, "hypervisor parameters are global and cannot be customized")

  def testHvparams(self):
    op = self.CopyOpCode(self.op,
                         hvparams={constants.HV_BOOT_ORDER: "cd"})
    self.ExecOpCode(op)

  def testDisksAndDiskTemplate(self):
    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_PLAIN,
                         disks=[[constants.DDM_ADD, -1, {}]])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk template conversion and other disk changes not supported at"
          " the same time")

  def testDiskTemplateToMirroredNoRemoteNode(self):
    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_DRBD8)
    self.ExecOpCodeExpectOpPrereqError(
      op, "No iallocator or node given and no cluster-wide default iallocator"
          " found; please specify either an iallocator or a node, or set a"
          " cluster-wide default iallocator")

  def testPrimaryNodeToOldPrimaryNode(self):
    op = self.CopyOpCode(self.op,
                         pnode=self.master.name)
    self.ExecOpCode(op)

  def testPrimaryNodeChange(self):
    node = self.cfg.AddNewNode()
    op = self.CopyOpCode(self.op,
                         pnode=node.name)
    self.ExecOpCode(op)

  def testPrimaryNodeChangeRunningInstance(self):
    node = self.cfg.AddNewNode()
    op = self.CopyOpCode(self.running_op,
                         pnode=node.name)
    self.ExecOpCodeExpectOpPrereqError(op, "Instance is still running")

  def testOsChange(self):
    os = self.cfg.CreateOs(supported_variants=[])
    self.rpc.call_os_validate.return_value = True
    op = self.CopyOpCode(self.op,
                         os_name=os.name)
    self.ExecOpCode(op)

  def testVCpuChange(self):
    op = self.CopyOpCode(self.op,
                         beparams={
                           constants.BE_VCPUS: 4
                         })
    self.ExecOpCode(op)

  def testWrongCpuMask(self):
    op = self.CopyOpCode(self.op,
                         beparams={
                           constants.BE_VCPUS: 4
                         },
                         hvparams={
                           constants.HV_CPU_MASK: "1,2:3,4"
                         })
    self.ExecOpCodeExpectOpPrereqError(
      op, "Number of vCPUs .* does not match the CPU mask .*")

  def testCorrectCpuMask(self):
    op = self.CopyOpCode(self.op,
                         beparams={
                           constants.BE_VCPUS: 4
                         },
                         hvparams={
                           constants.HV_CPU_MASK: "1,2:3,4:all:1,4"
                         })
    self.ExecOpCode(op)

  def testOsParams(self):
    op = self.CopyOpCode(self.op,
                         osparams={
                           self.os.supported_parameters[0]: "test_param_val"
                         })
    self.ExecOpCode(op)

  def testIncreaseMemoryTooMuch(self):
    op = self.CopyOpCode(self.running_op,
                         beparams={
                           constants.BE_MAXMEM:
                             self.mocked_master_memory_free * 2
                         })
    self.ExecOpCodeExpectOpPrereqError(
      op, "This change will prevent the instance from starting")

  def testIncreaseMemory(self):
    op = self.CopyOpCode(self.running_op,
                         beparams={
                           constants.BE_MAXMEM: self.mocked_master_memory_free
                         })
    self.ExecOpCode(op)

  def testIncreaseMemoryTooMuchForSecondary(self):
    inst = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP,
                                   disk_template=constants.DT_DRBD8,
                                   secondary_node=self.snode)
    self.rpc.call_instance_info.side_effect = [
      self.RpcResultsBuilder()
        .CreateSuccessfulNodeResult(self.master,
                                    {
                                      "memory":
                                        self.mocked_snode_memory_free * 2,
                                      "vcpus": self.mocked_running_inst_vcpus,
                                      "state": self.mocked_running_inst_state,
                                      "time": self.mocked_running_inst_time
                                    })]

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         beparams={
                           constants.BE_MAXMEM:
                             self.mocked_snode_memory_free * 2,
                           constants.BE_AUTO_BALANCE: True
                         })
    self.ExecOpCodeExpectOpPrereqError(
      op, "This change will prevent the instance from failover to its"
          " secondary node")

  def testInvalidRuntimeMemory(self):
    op = self.CopyOpCode(self.running_op,
                         runtime_mem=self.mocked_master_memory_free * 2)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance .* must have memory between .* and .* of memory")

  def testIncreaseRuntimeMemory(self):
    op = self.CopyOpCode(self.running_op,
                         runtime_mem=self.mocked_master_memory_free,
                         beparams={
                           constants.BE_MAXMEM: self.mocked_master_memory_free
                         })
    self.ExecOpCode(op)

  def testAddNicWithPoolIpNoNetwork(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1,
                                {
                                  constants.INIC_IP: constants.NIC_IP_POOL
                                })])
    self.ExecOpCodeExpectOpPrereqError(
      op, "If ip=pool, parameter network cannot be none")

  def testAddNicWithPoolIp(self):
    net = self.cfg.AddNewNetwork()
    self.cfg.ConnectNetworkToGroup(net, self.group)
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1,
                                {
                                  constants.INIC_IP: constants.NIC_IP_POOL,
                                  constants.INIC_NETWORK: net.name
                                })])
    self.ExecOpCode(op)

  def testAddNicWithInvalidIp(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1,
                                {
                                  constants.INIC_IP: "invalid"
                                })])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Invalid IP address")

  def testAddNic(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1, {})])
    self.ExecOpCode(op)

  def testAttachNICs(self):
    msg = "Attach operation is not supported for NICs"
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ATTACH, -1, {})])
    self.ExecOpCodeExpectOpPrereqError(op, msg)

  def testNoHotplugSupport(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1, {})],
                         )
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master)
    self.assertFalse(self.rpc.call_hotplug_supported.called)

  def testHotplugIfPossible(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1, {})]
                         )
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateFailedNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertFalse(self.rpc.call_hotplug_device.called)

  def testHotAddNic(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1, {})],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)

  def testAddNicWithIp(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_ADD, -1,
                                {
                                  constants.INIC_IP: "2.3.1.4"
                                })])
    self.ExecOpCode(op)

  def testModifyNicRoutedWithoutIp(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_MODIFY, 0,
                                {
                                  constants.INIC_NETWORK: constants.VALUE_NONE,
                                  constants.INIC_MODE: constants.NIC_MODE_ROUTED
                                })])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Cannot set the NIC IP address to None on a routed NIC"
      " if not attached to a network")

  def testModifyNicSetMac(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_MODIFY, 0,
                                {
                                  constants.INIC_MAC: "0a:12:95:15:bf:75"
                                })])
    self.ExecOpCode(op)

  def testModifyNicWithPoolIpNoNetwork(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_MODIFY, -1,
                                {
                                  constants.INIC_IP: constants.NIC_IP_POOL
                                })])
    self.ExecOpCodeExpectOpPrereqError(
      op, "ip=pool, but no network found")

  def testModifyNicSetNet(self):
    old_net = self.cfg.AddNewNetwork()
    self.cfg.ConnectNetworkToGroup(old_net, self.group)
    inst = self.cfg.AddNewInstance(nics=[
      self.cfg.CreateNic(network=old_net,
                         ip="198.51.100.2")])

    new_net = self.cfg.AddNewNetwork(mac_prefix="be")
    self.cfg.ConnectNetworkToGroup(new_net, self.group)
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         nics=[(constants.DDM_MODIFY, 0,
                                {
                                  constants.INIC_NETWORK: new_net.name
                                })])
    self.ExecOpCode(op)

  def testModifyNicSetLinkWhileConnected(self):
    old_net = self.cfg.AddNewNetwork()
    self.cfg.ConnectNetworkToGroup(old_net, self.group)
    inst = self.cfg.AddNewInstance(nics=[
      self.cfg.CreateNic(network=old_net)])

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         nics=[(constants.DDM_MODIFY, 0,
                                {
                                  constants.INIC_LINK: "mock_link"
                                })])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Not allowed to change link or mode of a NIC that is connected"
          " to a network")

  def testModifyNicSetNetAndIp(self):
    net = self.cfg.AddNewNetwork(mac_prefix="be", network="123.123.123.0/24")
    self.cfg.ConnectNetworkToGroup(net, self.group)
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_MODIFY, 0,
                                {
                                  constants.INIC_NETWORK: net.name,
                                  constants.INIC_IP: "123.123.123.1"
                                })])
    self.ExecOpCode(op)

  def testModifyNic(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_MODIFY, 0, {})])
    self.ExecOpCode(op)

  def testHotModifyNic(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_MODIFY, 0, {})],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)

  def testRemoveLastNic(self):
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_REMOVE, 0, {})])
    self.ExecOpCodeExpectOpPrereqError(
      op, "violates policy")

  def testRemoveNic(self):
    inst = self.cfg.AddNewInstance(nics=[self.cfg.CreateNic(),
                                         self.cfg.CreateNic()])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         nics=[(constants.DDM_REMOVE, 0, {})])
    self.ExecOpCode(op)

  def testDetachNICs(self):
    msg = "Detach operation is not supported for NICs"
    op = self.CopyOpCode(self.op,
                         nics=[(constants.DDM_DETACH, -1, {})])
    self.ExecOpCodeExpectOpPrereqError(op, msg)

  def testHotRemoveNic(self):
    inst = self.cfg.AddNewInstance(nics=[self.cfg.CreateNic(),
                                         self.cfg.CreateNic()])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         nics=[(constants.DDM_REMOVE, 0, {})],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)

  def testSetOffline(self):
    op = self.CopyOpCode(self.op,
                         offline=True)
    self.ExecOpCode(op)

  def testUnsetOffline(self):
    op = self.CopyOpCode(self.op,
                         offline=False)
    self.ExecOpCode(op)

  def testAddDiskInvalidMode(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_MODE: "invalid"
                                 }]])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Invalid disk access mode 'invalid'")

  def testAddDiskMissingSize(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1, {}]])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Required disk parameter 'size' missing")

  def testAddDiskInvalidSize(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: "invalid"
                                 }]])
    self.ExecOpCodeExpectException(
      op, errors.TypeEnforcementError, "is not a valid size")

  def testAddDiskUnknownParam(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   "uuid": self.mocked_disk_uuid
                                 }]])
    self.ExecOpCodeExpectException(
      op, errors.TypeEnforcementError, "Unknown parameter 'uuid'")

  def testAddDiskRunningInstanceNoWaitForSync(self):
    op = self.CopyOpCode(self.running_op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]],
                         wait_for_sync=False)
    self.ExecOpCode(op)
    self.assertFalse(self.rpc.call_blockdev_shutdown.called)

  def testAddDiskDownInstance(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]])
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_blockdev_shutdown.called)

  def testAddDiskIndexBased(self):
    SPECIFIC_SIZE = 435 * 4
    insertion_index = len(self.inst.disks)
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, insertion_index,
                                 {
                                   constants.IDISK_SIZE: SPECIFIC_SIZE
                                 }]])
    self.ExecOpCode(op)
    self.assertEqual(len(self.inst.disks), insertion_index + 1)
    new_disk = self.cfg.GetDisk(self.inst.disks[insertion_index])
    self.assertEqual(new_disk.size, SPECIFIC_SIZE)

  def testAddDiskHugeIndex(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, 5,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]])
    self.ExecOpCodeExpectException(
      op, IndexError, "Got disk index.*but there are only.*"
    )

  def testAddExtDisk(self):
    op = self.CopyOpCode(self.ext_storage_op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]])
    self.ExecOpCodeExpectOpPrereqError(op,
                                       "Missing provider for template 'ext'")

    op = self.CopyOpCode(self.ext_storage_op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024,
                                   constants.IDISK_PROVIDER: "bla"
                                 }]])
    self.ExecOpCode(op)

  def testAddDiskDownInstanceNoWaitForSync(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]],
                         wait_for_sync=False)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't add a disk to an instance with deactivated disks"
          " and --no-wait-for-sync given")

  def testAddDiskRunningInstance(self):
    op = self.CopyOpCode(self.running_op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]])
    self.ExecOpCode(op)

    self.assertFalse(self.rpc.call_blockdev_shutdown.called)

  def testAddDiskNoneName(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024,
                                   constants.IDISK_NAME: constants.VALUE_NONE
                                 }]])
    self.ExecOpCode(op)

  def testHotAddDisk(self):
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, ("/dev/mocked_path",
                                    "/var/run/ganeti/instance-disks/mocked_d",
                                    None))
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ADD, -1,
                                 {
                                   constants.IDISK_SIZE: 1024,
                                 }]],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_blockdev_create.called)
    self.assertTrue(self.rpc.call_blockdev_assemble.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)

  def testAttachDiskWrongParams(self):
    msg = "Only one argument is permitted in attach op, either name or uuid"
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_SIZE: 1134
                                 }]],
                         )
    self.ExecOpCodeExpectOpPrereqError(op, msg)
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   'uuid': "1134",
                                   constants.IDISK_NAME: "1134",
                                 }]],
                         )
    self.ExecOpCodeExpectOpPrereqError(op, msg)
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   'uuid': "1134",
                                   constants.IDISK_SIZE: 1134,
                                 }]],
                         )
    self.ExecOpCodeExpectOpPrereqError(op, msg)

  def testAttachDiskWrongTemplate(self):
    msg = "Instance has '%s' template while disk has '%s' template" % \
      (constants.DT_PLAIN, constants.DT_BLOCK)
    self.cfg.AddOrphanDisk(name=self.mocked_disk_name,
                           dev_type=constants.DT_BLOCK)
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         )
    self.ExecOpCodeExpectOpPrereqError(op, msg)

  def testAttachDiskWrongNodes(self):
    msg = "Disk nodes are \['mock_node_1134'\]"

    self.cfg.AddOrphanDisk(name=self.mocked_disk_name,
                           primary_node="mock_node_1134")
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         )
    self.ExecOpCodeExpectOpPrereqError(op, msg)

  def testAttachDiskRunningInstance(self):
    self.cfg.AddOrphanDisk(name=self.mocked_disk_name,
                           primary_node=self.master.uuid)
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master,
                                    ("/dev/mocked_path",
                                     "/var/run/ganeti/instance-disks/mocked_d",
                                     None))
    op = self.CopyOpCode(self.running_op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         )
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_blockdev_assemble.called)
    self.assertFalse(self.rpc.call_blockdev_shutdown.called)

  def testAttachDiskRunningInstanceNoWaitForSync(self):
    self.cfg.AddOrphanDisk(name=self.mocked_disk_name,
                           primary_node=self.master.uuid)
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master,
                                    ("/dev/mocked_path",
                                     "/var/run/ganeti/instance-disks/mocked_d",
                                     None))
    op = self.CopyOpCode(self.running_op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         wait_for_sync=False)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_blockdev_assemble.called)
    self.assertFalse(self.rpc.call_blockdev_shutdown.called)

  def testAttachDiskDownInstance(self):
    self.cfg.AddOrphanDisk(name=self.mocked_disk_name,
                           primary_node=self.master.uuid)
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]])
    self.ExecOpCode(op)

    self.assertTrue(self.rpc.call_blockdev_assemble.called)
    self.assertTrue(self.rpc.call_blockdev_shutdown.called)

  def testAttachDiskDownInstanceNoWaitForSync(self):
    self.cfg.AddOrphanDisk(name=self.mocked_disk_name)
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         wait_for_sync=False)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't attach a disk to an instance with deactivated disks"
          " and --no-wait-for-sync given.")

  def testHotAttachDisk(self):
    self.cfg.AddOrphanDisk(name=self.mocked_disk_name,
                           primary_node=self.master.uuid)
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master,
                                    ("/dev/mocked_path",
                                     "/var/run/ganeti/instance-disks/mocked_d",
                                     None))
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_blockdev_assemble.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)

  def testHotRemoveDisk(self):
    inst = self.cfg.AddNewInstance(disks=[self.cfg.CreateDisk(),
                                          self.cfg.CreateDisk()])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_REMOVE, -1,
                                 {}]],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)
    self.assertTrue(self.rpc.call_blockdev_shutdown.called)
    self.assertTrue(self.rpc.call_blockdev_remove.called)

  def testHotDetachDisk(self):
    inst = self.cfg.AddNewInstance(disks=[self.cfg.CreateDisk(),
                                          self.cfg.CreateDisk()])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH, -1,
                                 {}]],
                         hotplug=True)
    self.rpc.call_hotplug_supported.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertTrue(self.rpc.call_hotplug_supported.called)
    self.assertTrue(self.rpc.call_hotplug_device.called)
    self.assertTrue(self.rpc.call_blockdev_shutdown.called)

  def testDetachAttachFileBasedDisk(self):
    """Detach and re-attach a disk from a file-based instance."""
    # Create our disk and calculate the path where it is stored, its name, as
    # well as the expected path where it will be moved.
    mock_disk = self.cfg.CreateDisk(
      name='mock_disk_1134', dev_type=constants.DT_FILE,
      logical_id=('loop', '/tmp/instance/disk'), primary_node=self.master.uuid)

    # Create a file-based instance
    file_disk = self.cfg.CreateDisk(
      dev_type=constants.DT_FILE,
      logical_id=('loop', '/tmp/instance/disk2'))
    inst = self.cfg.AddNewInstance(name='instance',
                                   disk_template=constants.DT_FILE,
                                   disks=[file_disk, mock_disk],
                                  )

    # Detach the disk and assert that it has been moved to the upper directory
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH, -1,
                                 {}]],
                         )
    self.ExecOpCode(op)
    mock_disk = self.cfg.GetDiskInfo(mock_disk.uuid)
    self.assertEqual('/tmp/disk', mock_disk.logical_id[1])

    # Re-attach the disk and assert that it has been moved to the original
    # directory
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_ATTACH, -1,
                                 {
                                   constants.IDISK_NAME: self.mocked_disk_name
                                 }]],
                         )
    self.ExecOpCode(op)
    mock_disk = self.cfg.GetDiskInfo(mock_disk.uuid)
    self.assertIn('/tmp/instance', mock_disk.logical_id[1])

  def testAttachDetachDisk(self):
    """Check if the disks can be attached and detached in sequence.

    Also, check if the operations succeed both with name and uuid.
    """
    disk1 = self.cfg.CreateDisk(uuid=self.mocked_disk_uuid,
                                primary_node=self.master.uuid)
    disk2 = self.cfg.CreateDisk(name="mock_name_1134",
                                primary_node=self.master.uuid)

    inst = self.cfg.AddNewInstance(disks=[disk1, disk2])

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH, self.mocked_disk_uuid,
                                 {}]])
    self.ExecOpCode(op)
    self.assertEqual([disk2], self.cfg.GetInstanceDisks(inst.uuid))

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_ATTACH, 0,
                                 {
                                   'uuid': self.mocked_disk_uuid
                                 }]])
    self.ExecOpCode(op)
    self.assertEqual([disk1, disk2], self.cfg.GetInstanceDisks(inst.uuid))

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH, 1,
                                 {}]])
    self.ExecOpCode(op)
    self.assertEqual([disk1], self.cfg.GetInstanceDisks(inst.uuid))

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_ATTACH, 0,
                                 {
                                   constants.IDISK_NAME: "mock_name_1134"
                                 }]])
    self.ExecOpCode(op)
    self.assertEqual([disk2, disk1], self.cfg.GetInstanceDisks(inst.uuid))

  def testDetachAndAttachToDisklessInstance(self):
    """Check if a disk can be detached and then re-attached if the instance is
    diskless inbetween.

    """
    disk = self.cfg.CreateDisk(uuid=self.mocked_disk_uuid,
                               primary_node=self.master.uuid)

    inst = self.cfg.AddNewInstance(disks=[disk], primary_node=self.master)

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH,
                         self.mocked_disk_uuid, {}]])

    self.ExecOpCode(op)
    self.assertEqual([], self.cfg.GetInstanceDisks(inst.uuid))

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_ATTACH, 0,
                                 {
                                   'uuid': self.mocked_disk_uuid
                                 }]])
    self.ExecOpCode(op)
    self.assertEqual([disk], self.cfg.GetInstanceDisks(inst.uuid))

  def testDetachAttachDrbdDisk(self):
    """Check if a DRBD disk can be detached and then re-attached.

    """
    disk = self.cfg.CreateDisk(uuid=self.mocked_disk_uuid,
                               primary_node=self.master.uuid,
                               secondary_node=self.snode.uuid,
                               dev_type=constants.DT_DRBD8)

    inst = self.cfg.AddNewInstance(disks=[disk], primary_node=self.master)

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH,
                         self.mocked_disk_uuid, {}]])

    self.ExecOpCode(op)
    self.assertEqual([], self.cfg.GetInstanceDisks(inst.uuid))

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_ATTACH, 0,
                                 {
                                   'uuid': self.mocked_disk_uuid
                                 }]])
    self.ExecOpCode(op)
    self.assertEqual([disk], self.cfg.GetInstanceDisks(inst.uuid))

  def testDetachAttachDrbdDiskWithWrongPrimaryNode(self):
    """Check if disk attachment with a wrong primary node fails.

    """
    disk1 = self.cfg.CreateDisk(uuid=self.mocked_disk_uuid,
                               primary_node=self.master.uuid,
                               secondary_node=self.snode.uuid,
                               dev_type=constants.DT_DRBD8)

    inst1 = self.cfg.AddNewInstance(disks=[disk1], primary_node=self.master,
                                    secondary_node=self.snode)

    op = self.CopyOpCode(self.op,
                         instance_name=inst1.name,
                         disks=[[constants.DDM_DETACH,
                         self.mocked_disk_uuid, {}]])

    self.ExecOpCode(op)
    self.assertEqual([], self.cfg.GetInstanceDisks(inst1.uuid))

    disk2 = self.cfg.CreateDisk(uuid="mock_uuid_1135",
                               primary_node=self.snode.uuid,
                               secondary_node=self.master.uuid,
                               dev_type=constants.DT_DRBD8)

    inst2 = self.cfg.AddNewInstance(disks=[disk2], primary_node=self.snode,
                                    secondary_node=self.master)

    op = self.CopyOpCode(self.op,
                         instance_name=inst2.name,
                         disks=[[constants.DDM_ATTACH, 0,
                                 {
                                   'uuid': self.mocked_disk_uuid
                                 }]])

    self.assertRaises(errors.OpExecError, self.ExecOpCode, op)


  def testDetachAttachExtDisk(self):
    """Check attach/detach functionality of ExtStorage disks.

    """
    disk = self.cfg.CreateDisk(uuid=self.mocked_disk_uuid,
                               dev_type=constants.DT_EXT,
                               params={
                                 constants.IDISK_PROVIDER: "pvdr"
                               })

    inst = self.cfg.AddNewInstance(disks=[disk], primary_node=self.master)

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_DETACH,
                         self.mocked_disk_uuid, {}]])

    self.ExecOpCode(op)
    self.assertEqual([], self.cfg.GetInstanceDisks(inst.uuid))

    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_ATTACH, 0,
                                 {
                                   'uuid': self.mocked_disk_uuid
                                 }]])
    self.ExecOpCode(op)
    self.assertEqual([disk], self.cfg.GetInstanceDisks(inst.uuid))

  def testRemoveDiskRemovesStorageDir(self):
    inst = self.cfg.AddNewInstance(disks=[self.cfg.CreateDisk(dev_type='file')])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_REMOVE, -1,
                                 {}]])
    self.rpc.call_instance_info.side_effect = [
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    ]
    self.rpc.call_file_storage_dir_remove.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.rpc.call_file_storage_dir_remove.assert_called_with(
        self.master.uuid, '/file/storage')

  def testRemoveDiskKeepsStorageForRemaining(self):
    inst = self.cfg.AddNewInstance(disks=[self.cfg.CreateDisk(dev_type='file'),
                                          self.cfg.CreateDisk(dev_type='file')])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_REMOVE, -1,
                                 {}]])
    self.rpc.call_instance_info.side_effect = [
      self.RpcResultsBuilder()
        .CreateSuccessfulNodeResult(self.master)
    ]
    self.rpc.call_file_storage_dir_remove.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.ExecOpCode(op)
    self.assertFalse(self.rpc.call_file_storage_dir_remove.called)

  def testRemoveUsedDiskWithoutHotplug(self):
    inst = self.cfg.AddNewInstance(disks=[self.cfg.CreateDisk(),
                                          self.cfg.CreateDisk()])
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name,
                         disks=[[constants.DDM_REMOVE, -1, {}]],
                         hotplug=False) # without hotplug
    self.rpc.call_instance_info.side_effect = [
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master,
                                {
                                  "memory": self.mocked_snode_memory_free,
                                  "vcpus": self.mocked_running_inst_vcpus,
                                  "state": self.mocked_running_inst_state,
                                  "time": self.mocked_running_inst_time
                                })]
    self.ExecOpCodeExpectOpPrereqError(
      op, "can't remove volume from a running instance without using hotplug")
    self.assertFalse(self.rpc.call_blockdev_shutdown.called)
    self.assertFalse(self.rpc.call_blockdev_remove.called)

  def testModifyDiskWithSize(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_MODIFY, 0,
                                 {
                                   constants.IDISK_SIZE: 1024
                                 }]])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk size change not possible, use grow-disk")

  def testModifyDiskWithRandomParams(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_MODIFY, 0,
                                 {
                                   constants.IDISK_METAVG: "new_meta_vg",
                                   constants.IDISK_MODE: "invalid",
                                   constants.IDISK_NAME: "new_name"
                                 }]])
    self.ExecOpCodeExpectException(op, errors.TypeEnforcementError,
                                   "Unknown parameter 'metavg'")

  def testModifyDiskUnsetName(self):
    op = self.CopyOpCode(self.op,
                         disks=[[constants.DDM_MODIFY, 0,
                                  {
                                    constants.IDISK_NAME: constants.VALUE_NONE
                                  }]])
    self.ExecOpCode(op)

  def testModifyExtDiskProvider(self):
    mod = [[constants.DDM_MODIFY, 0,
             {
               constants.IDISK_PROVIDER: "anything"
             }]]
    op = self.CopyOpCode(self.op, disks=mod)
    self.ExecOpCodeExpectException(op, errors.TypeEnforcementError,
                                   "Unknown parameter 'provider'")

    op = self.CopyOpCode(self.ext_storage_op, disks=mod)
    self.ExecOpCodeExpectOpPrereqError(op, "Disk 'provider' parameter change"
                                           " is not possible")

  def testSetOldDiskTemplate(self):
    op = self.CopyOpCode(self.op,
                         disk_template=self.dev_type)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance already has disk template")

  def testSetDisabledDiskTemplate(self):
    self.cfg.SetEnabledDiskTemplates([self.inst.disk_template])
    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_EXT)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Disk template .* is not enabled for this cluster")

  def testConvertToExtWithMissingProvider(self):
    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_EXT)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Missing provider for template .*")

  def testConvertToNotExtWithProvider(self):
    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_FILE,
                         ext_params={constants.IDISK_PROVIDER: "pvdr"})
    self.ExecOpCodeExpectOpPrereqError(
      op, "The 'provider' option is only valid for the ext disk"
          " template, not .*")

  def testConvertToExtWithSameProvider(self):
    op = self.CopyOpCode(self.ext_storage_op,
                         disk_template=constants.DT_EXT,
                         ext_params={constants.IDISK_PROVIDER: "pvdr"})
    self.ExecOpCodeExpectOpPrereqError(
      op, "Not converting, 'disk/0' of type ExtStorage already using"
          " provider 'pvdr'")

  def testConvertToInvalidDiskTemplate(self):
    for disk_template in constants.DTS_NOT_CONVERTIBLE_TO:
      op = self.CopyOpCode(self.op,
                           disk_template=disk_template)
      self.ExecOpCodeExpectOpPrereqError(
        op, "Conversion to the .* disk template is not supported")

  def testConvertFromInvalidDiskTemplate(self):
    for disk_template in constants.DTS_NOT_CONVERTIBLE_FROM:
      inst = self.cfg.AddNewInstance(disk_template=disk_template)
      op = self.CopyOpCode(self.op,
                           instance_name=inst.name,
                           disk_template=constants.DT_PLAIN)
      self.ExecOpCodeExpectOpPrereqError(
        op, "Conversion from the .* disk template is not supported")

  def testConvertToDRBDWithSecondarySameAsPrimary(self):
    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_DRBD8,
                         remote_node=self.master.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Given new secondary node .* is the same as the primary node"
          " of the instance")

  def testConvertPlainToDRBD(self):
    self.rpc.call_blockdev_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_blockdev_getmirrorstatus.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, [objects.BlockDevStatus()])

    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_DRBD8,
                         remote_node=self.snode.name)
    self.ExecOpCode(op)

  def testConvertDRBDToPlain(self):
    for disk_uuid in self.inst.disks:
      self.cfg.RemoveInstanceDisk(self.inst.uuid, disk_uuid)
    disk = self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                               primary_node=self.master,
                               secondary_node=self.snode)
    self.cfg.AddInstanceDisk(self.inst.uuid, disk)
    self.inst.disk_template = constants.DT_DRBD8
    self.rpc.call_blockdev_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_blockdev_remove.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master)
    self.rpc.call_blockdev_getmirrorstatus.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, [objects.BlockDevStatus()])

    op = self.CopyOpCode(self.op,
                         disk_template=constants.DT_PLAIN)
    self.ExecOpCode(op)


class TestLUInstanceChangeGroup(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceChangeGroup, self).setUp()

    self.group2 = self.cfg.AddNewNodeGroup()
    self.node2 = self.cfg.AddNewNode(group=self.group2)
    self.inst = self.cfg.AddNewInstance()
    self.op = opcodes.OpInstanceChangeGroup(instance_name=self.inst.name)

  def testTargetGroupIsInstanceGroup(self):
    op = self.CopyOpCode(self.op,
                         target_groups=[self.group.name])
    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't use group\(s\) .* as targets, they are used by the"
          " instance .*")

  def testNoTargetGroups(self):
    inst = self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                                   primary_node=self.master,
                                   secondary_node=self.node2)
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "There are no possible target groups")

  def testFailingIAllocator(self):
    self.iallocator_cls.return_value.success = False
    op = self.CopyOpCode(self.op)

    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't compute solution for changing group of instance .*"
          " using iallocator .*")

  def testChangeGroup(self):
    self.iallocator_cls.return_value.success = True
    self.iallocator_cls.return_value.result = ([], [], [])
    op = self.CopyOpCode(self.op)

    self.ExecOpCode(op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
