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

from ganeti import constants
from ganeti import objects
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


class TestLUBackupExportBase(CmdlibTestCase):
  def setUp(self):
    super(TestLUBackupExportBase, self).setUp()

    self.rpc.call_instance_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)

    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, ("/dev/mock_path",
                                                  "/dev/mock_link_name"))

    self.rpc.call_blockdev_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, None)

    self.rpc.call_blockdev_snapshot.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, ("mock_vg", "mock_id"))

    self.rpc.call_blockdev_remove.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, None)

    self.rpc.call_export_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, "export_daemon")

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

    self.rpc.call_finalize_export.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, None)

  def testRemoveRunningInstanceWithoutShutdown(self):
    inst = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP)
    op = opcodes.OpBackupExport(instance_name=inst.name,
                                target_node=self.master.name,
                                shutdown=False,
                                remove_instance=True)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Can not remove instance without shutting it down before")

  def testUnsupportedDiskTemplate(self):
    inst = self.cfg.AddNewInstance(disk_template=constants.DT_FILE)
    op = opcodes.OpBackupExport(instance_name=inst.name,
                                target_node=self.master.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Export not supported for instances with file-based disks")


class TestLUBackupExportLocalExport(TestLUBackupExportBase):
  def setUp(self):
    super(TestLUBackupExportLocalExport, self).setUp()

    self.inst = self.cfg.AddNewInstance()
    self.target_node = self.cfg.AddNewNode()
    self.op = opcodes.OpBackupExport(mode=constants.EXPORT_MODE_LOCAL,
                                     instance_name=self.inst.name,
                                     target_node=self.target_node.name)

    self.rpc.call_import_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.target_node, "import_daemon")

  def testExportWithShutdown(self):
    inst = self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP)
    op = self.CopyOpCode(self.op, instance_name=inst.name, shutdown=True)
    self.ExecOpCode(op)

  def testExportDeactivatedDisks(self):
    self.ExecOpCode(self.op)

  def testExportRemoveInstance(self):
    op = self.CopyOpCode(self.op, remove_instance=True)
    self.ExecOpCode(op)


class TestLUBackupExportRemoteExport(TestLUBackupExportBase):
  def setUp(self):
    super(TestLUBackupExportRemoteExport, self).setUp()

    self.inst = self.cfg.AddNewInstance()
    self.op = opcodes.OpBackupExport(mode=constants.EXPORT_MODE_REMOTE,
                                     instance_name=self.inst.name,
                                     target_node=[],
                                     x509_key_name=["mock_key_name"],
                                     destination_x509_ca="mock_dest_ca")

  def testRemoteExportWithoutX509KeyName(self):
    op = self.CopyOpCode(self.op, x509_key_name=self.REMOVE)
    self.ExecOpCodeExpectOpPrereqError(op,
                                       "Missing X509 key name for encryption")

  def testRemoteExportWithoutX509DestCa(self):
    op = self.CopyOpCode(self.op, destination_x509_ca=self.REMOVE)
    self.ExecOpCodeExpectOpPrereqError(op,
                                       "Missing destination X509 CA")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
