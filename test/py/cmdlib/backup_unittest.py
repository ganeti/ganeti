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


"""Tests for LUBackup*"""

from ganeti import constants
from ganeti import objects
from ganeti import opcodes
from ganeti import query

from testsupport import *

import testutils


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
                                                  "/dev/mock_link_name",
                                                  None))

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

  def testValidCompressionTool(self):
    op = self.CopyOpCode(self.op, compress="lzop")
    self.cfg.SetCompressionTools(["gzip", "lzop"])
    self.ExecOpCode(op)

  def testInvalidCompressionTool(self):
    op = self.CopyOpCode(self.op, compress="invalid")
    self.cfg.SetCompressionTools(["gzip", "lzop"])
    self.ExecOpCodeExpectOpPrereqError(op, "Compression tool not allowed")


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
