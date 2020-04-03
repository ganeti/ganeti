#!/usr/bin/python3
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


"""Script for unittesting the cmdlib module 'instance_storage'"""


import unittest

from ganeti import constants
from ganeti.cmdlib import instance_storage
from ganeti import errors
from ganeti import objects
from ganeti import opcodes

import testutils
import mock
import time

from testsupport import CmdlibTestCase


class TestCheckNodesFreeDiskOnVG(unittest.TestCase):

  def setUp(self):
    self.node_uuid = "12345"
    self.node_uuids = [self.node_uuid]

    self.node_info = mock.Mock()

    self.es = True
    self.ndparams = {constants.ND_EXCLUSIVE_STORAGE: self.es}

    mock_rpc = mock.Mock()
    mock_rpc.call_node_info = mock.Mock()

    mock_cfg = mock.Mock()
    mock_cfg.GetNodeInfo = mock.Mock(return_value=self.node_info)
    mock_cfg.GetNdParams = mock.Mock(return_value=self.ndparams)

    self.hvname = "myhv"
    self.hvparams = mock.Mock()
    self.clusterinfo = mock.Mock()
    self.clusterinfo.hvparams = {self.hvname: self.hvparams}

    mock_cfg.GetHypervisorType = mock.Mock(return_value=self.hvname)
    mock_cfg.GetClusterInfo = mock.Mock(return_value=self.clusterinfo)

    self.lu = mock.Mock()
    self.lu.rpc = mock_rpc
    self.lu.cfg = mock_cfg

    self.vg = "myvg"

    self.node_name = "mynode"
    self.space_info = [{"type": constants.ST_LVM_VG,
                        "name": self.vg,
                        "storage_free": 125,
                        "storage_size": 666}]

  def testPerformNodeInfoCall(self):
    expected_hv_arg = [(self.hvname, self.hvparams)]
    expected_storage_arg = {self.node_uuid:
        [(constants.ST_LVM_VG, self.vg, [self.es]),
         (constants.ST_LVM_PV, self.vg, [self.es])]}
    instance_storage._PerformNodeInfoCall(self.lu, self.node_uuids, self.vg)
    self.lu.rpc.call_node_info.assert_called_with(
        self.node_uuids, expected_storage_arg, expected_hv_arg)

  def testCheckVgCapacityForNode(self):
    requested = 123
    node_info = (None, self.space_info, None)
    instance_storage._CheckVgCapacityForNode(self.node_name, node_info,
                                             self.vg, requested)

  def testCheckVgCapacityForNodeNotEnough(self):
    requested = 250
    node_info = (None, self.space_info, None)
    self.assertRaises(
        errors.OpPrereqError,
        instance_storage._CheckVgCapacityForNode,
        self.node_name, node_info, self.vg, requested)

  def testCheckVgCapacityForNodeNoStorageData(self):
    node_info = (None, [], None)
    self.assertRaises(
        errors.OpPrereqError,
        instance_storage._CheckVgCapacityForNode,
        self.node_name, node_info, self.vg, NotImplemented)

  def testCheckVgCapacityForNodeBogusSize(self):
    broken_space_info = [{"type": constants.ST_LVM_VG,
                        "name": self.vg,
                        "storage_free": "greenbunny",
                        "storage_size": "redbunny"}]
    node_info = (None, broken_space_info, None)
    self.assertRaises(
        errors.OpPrereqError,
        instance_storage._CheckVgCapacityForNode,
        self.node_name, node_info, self.vg, NotImplemented)


class TestCheckComputeDisksInfo(unittest.TestCase):
  """Tests for instance_storage.ComputeDisksInfo()

  """
  def setUp(self):
    """Set up input data"""
    self.disks = [
      objects.Disk(dev_type=constants.DT_PLAIN, size=1024,
                   logical_id=("ganeti", "disk01234"),
                   name="disk-0", mode="rw", params={},
                   children=[], uuid="disk0"),
      objects.Disk(dev_type=constants.DT_PLAIN, size=2048,
                   logical_id=("ganeti", "disk56789"),
                   name="disk-1", mode="ro", params={},
                   children=[], uuid="disk1")
      ]

    self.ext_params = {
      "provider": "pvdr",
      "param1"  : "value1",
      "param2"  : "value2"
      }

    self.default_vg = "ganeti-vg"

  def testComputeDisksInfo(self):
    """Test instance_storage.ComputeDisksInfo() method"""
    disks_info = instance_storage.ComputeDisksInfo(self.disks,
                                                   constants.DT_EXT,
                                                   self.default_vg,
                                                   self.ext_params)

    for disk, d in zip(disks_info, self.disks):
      self.assertEqual(disk.get("size"), d.size)
      self.assertEqual(disk.get("mode"), d.mode)
      self.assertEqual(disk.get("name"), d.name)
      self.assertEqual(disk.get("param1"), self.ext_params.get("param1"))
      self.assertEqual(disk.get("param2"), self.ext_params.get("param2"))
      self.assertEqual(disk.get("provider"), self.ext_params.get("provider"))

  def testComputeDisksInfoPlainToDrbd(self):
    disks = [{constants.IDISK_TYPE: constants.DT_DRBD8,
              constants.IDISK_SIZE: d.size,
              constants.IDISK_MODE: d.mode,
              constants.IDISK_VG: d.logical_id[0],
              constants.IDISK_NAME: d.name}
             for d in self.disks]

    disks_info = instance_storage.ComputeDisksInfo(self.disks,
                                                   constants.DT_DRBD8,
                                                   self.default_vg, {})
    self.assertEqual(disks, disks_info)

  def testComputeDisksInfoFails(self):
    """Test instance_storage.ComputeDisksInfo() method fails"""
    self.assertRaises(
      errors.OpPrereqError, instance_storage.ComputeDisksInfo,
      self.disks, constants.DT_EXT, self.default_vg, {})
    self.assertRaises(
      errors.OpPrereqError, instance_storage.ComputeDisksInfo,
      self.disks, constants.DT_DRBD8, self.default_vg, self.ext_params)

    self.ext_params.update({"size": 128})
    self.assertRaises(
      AssertionError, instance_storage.ComputeDisksInfo,
      self.disks, constants.DT_EXT, self.default_vg, self.ext_params)


class TestLUInstanceReplaceDisks(CmdlibTestCase):
  """Tests for LUInstanceReplaceDisks."""

  def setUp(self):
    super(TestLUInstanceReplaceDisks, self).setUp()

    self.MockOut(time, 'sleep')

    self.node1 = self.cfg.AddNewNode()
    self.node2 = self.cfg.AddNewNode()

  def MakeOpCode(self, disks, early_release=False, ignore_ipolicy=False,
                 remote_node=False, mode='replace_auto', iallocator=None):
    return opcodes.OpInstanceReplaceDisks(
        instance_name=self.instance.name,
        instance_uuid=self.instance.uuid,
        early_release=early_release,
        ignore_ipolicy=ignore_ipolicy,
        mode=mode,
        disks=disks,
        remote_node=self.node2.name if remote_node else None,
        remote_node_uuid=self.node2.uuid if remote_node else None,
        iallocator=iallocator)

  def testInvalidTemplate(self):
    self.instance = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP,
                                            disk_template='diskless',
                                            primary_node=self.node1)

    opcode = self.MakeOpCode([])
    self.ExecOpCodeExpectOpPrereqError(
        opcode, 'strange layout')

  def SimulateDiskFailure(self, node, disk):
    def Faulty(node_uuid):
      disks = self.cfg.GetInstanceDisks(node_uuid)
      return [i for i,d in enumerate(disks)
              if i == disk and node.uuid == node_uuid]
    self.MockOut(instance_storage.TLReplaceDisks, '_FindFaultyDisks',
                 side_effect=Faulty)
    self.MockOut(instance_storage.TLReplaceDisks, '_CheckDevices')
    self.MockOut(instance_storage.TLReplaceDisks, '_CheckVolumeGroup')
    self.MockOut(instance_storage.TLReplaceDisks, '_CheckDisksExistence')
    self.MockOut(instance_storage.TLReplaceDisks, '_CheckDisksConsistency')
    self.MockOut(instance_storage.LUInstanceReplaceDisks, 'AssertReleasedLocks')
    self.MockOut(instance_storage, 'WaitForSync')
    self.rpc.call_blockdev_addchildren().fail_msg = None

  def testReplacePrimary(self):
    self.instance = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP,
                                            disk_template='drbd',
                                            primary_node=self.node1,
                                            secondary_node=self.node2)

    self.SimulateDiskFailure(self.node1, 0)

    opcode = self.MakeOpCode([0], mode='replace_on_primary')
    self.ExecOpCode(opcode)
    self.rpc.call_blockdev_rename.assert_any_call(self.node1.uuid, [])

  def testReplaceSecondary(self):
    self.instance = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP,
                                            disk_template='drbd',
                                            primary_node=self.node1,
                                            secondary_node=self.node2)

    self.SimulateDiskFailure(self.node2, 0)

    opcode = self.MakeOpCode([0], mode='replace_on_secondary')
    self.ExecOpCode(opcode)
    self.rpc.call_blockdev_rename.assert_any_call(self.node2.uuid, [])

  def testReplaceSecondaryNew(self):
    disk = self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                               primary_node=self.node1,
                               secondary_node=self.node2)
    self.instance = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP,
                                            disk_template='drbd',
                                            disks=[disk],
                                            primary_node=self.node1,
                                            secondary_node=self.node2)

    self.SimulateDiskFailure(self.node2, 0)
    node3 = self.cfg.AddNewNode()
    self.MockOut(instance_storage.TLReplaceDisks, '_RunAllocator',
                 return_value=node3.uuid)
    self.rpc.call_drbd_disconnect_net().__getitem__().fail_msg = None
    self.rpc.call_blockdev_shutdown().fail_msg = None
    self.rpc.call_drbd_attach_net().fail_msg = None

    opcode = self.MakeOpCode([], mode='replace_new_secondary',
                             iallocator='hail')
    self.ExecOpCode(opcode)
    self.rpc.call_blockdev_shutdown.assert_any_call(
        self.node2.uuid, (disk, self.instance))
    self.rpc.call_drbd_attach_net.assert_any_call(
        [self.node1.uuid, node3.uuid], ([disk], self.instance),
        False)

if __name__ == "__main__":
  testutils.GanetiTestProgram()
