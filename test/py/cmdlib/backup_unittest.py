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


"""Tests for LUBackup*"""

import mock

from ganeti import constants
from ganeti import opcodes
from ganeti import query

from testsupport import *

import testutils


class TestLUBackupQuery(CmdlibTestCase):
  def setUp(self):
    super(TestLUBackupQuery, self).setUp()

    self.fields = query._BuildExportFields().keys()

  def testFailingExportList(self):
    self.rpc.call_export_list.return_value = \
      self.RpcResultsBuilder() \
        .AddFailedNode(self.master) \
        .Build()
    op = opcodes.OpBackupQuery(nodes=[self.master.name])
    ret = self.ExecOpCode(op)
    self.assertEqual({self.master.name: False}, ret)

  def testQueryOneNode(self):
    self.rpc.call_export_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master,
                           ["mock_export1", "mock_export2"]) \
        .Build()
    op = opcodes.OpBackupQuery(nodes=[self.master.name])
    ret = self.ExecOpCode(op)
    self.assertEqual({self.master.name: ["mock_export1", "mock_export2"]}, ret)

  def testQueryAllNodes(self):
    node = self.cfg.AddNewNode()
    self.rpc.call_export_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, ["mock_export1"]) \
        .AddSuccessfulNode(node, ["mock_export2"]) \
        .Build()
    op = opcodes.OpBackupQuery()
    ret = self.ExecOpCode(op)
    self.assertEqual({
                       self.master.name: ["mock_export1"],
                       node.name: ["mock_export2"]
                     }, ret)


class TestLUBackupPrepare(CmdlibTestCase):
  @patchUtils("instance_utils")
  def testPrepareLocalExport(self, utils):
    utils.ReadOneLineFile.return_value = "cluster_secret"
    inst = self.cfg.AddNewInstance()
    op = opcodes.OpBackupPrepare(instance_name=inst.name,
                                 mode=constants.EXPORT_MODE_LOCAL)
    self.ExecOpCode(op)

  @patchUtils("instance_utils")
  def testPrepareRemoteExport(self, utils):
    utils.ReadOneLineFile.return_value = "cluster_secret"
    inst = self.cfg.AddNewInstance()
    self.rpc.call_x509_cert_create.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(inst.primary_node,
                                    ("key_name",
                                     testutils.ReadTestData("cert1.pem")))
    op = opcodes.OpBackupPrepare(instance_name=inst.name,
                                 mode=constants.EXPORT_MODE_REMOTE)
    self.ExecOpCode(op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
