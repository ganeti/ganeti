#!/usr/bin/python
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


"""Script for unittesting the cmdlib module 'instance_storage'"""


import unittest

from ganeti import constants
from ganeti.cmdlib import instance_storage
from ganeti import errors

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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
