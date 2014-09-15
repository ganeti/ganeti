#!/usr/bin/python
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

import testutils
import mock


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
    disks = [{constants.IDISK_SIZE: d.size,
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
