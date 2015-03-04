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


def InstanceRemoved(remove_instance):
  """Checks whether the instance was removed during a test of opcode execution.

  """
  def WrappingFunction(fn):
    def CheckingFunction(self, *args, **kwargs):
      fn(self, *args, **kwargs)
      instance_removed = (self.rpc.call_blockdev_remove.called -
                          self.rpc.call_blockdev_snapshot.called) > 0
      if remove_instance and not instance_removed:
        raise self.fail(msg="Instance not removed when it should have been")
      if not remove_instance and instance_removed:
        raise self.fail(msg="Instance removed when it should not have been")
    return CheckingFunction
  return WrappingFunction


def TrySnapshots(try_snapshot):
  """Checks whether an attempt to snapshot disks should have been attempted.

  """
  def WrappingFunction(fn):
    def CheckingFunction(self, *args, **kwargs):
      fn(self, *args, **kwargs)
      snapshots_tried = self.rpc.call_blockdev_snapshot.called > 0
      if try_snapshot and not snapshots_tried:
        raise self.fail(msg="Disks should have been snapshotted but weren't")
      if not try_snapshot and snapshots_tried:
        raise self.fail(msg="Disks snapshotted without a need to do so")
    return CheckingFunction
  return WrappingFunction


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


class TestLUBackupExportLocalExport(TestLUBackupExportBase):
  def setUp(self):
    # The initial instance prep
    super(TestLUBackupExportLocalExport, self).setUp()

    self.target_node = self.cfg.AddNewNode()
    self.op = opcodes.OpBackupExport(mode=constants.EXPORT_MODE_LOCAL,
                                     target_node=self.target_node.name)
    self._PrepareInstance()

    self.rpc.call_import_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.target_node, "import_daemon")

  def _PrepareInstance(self, online=False, snapshottable=True):
    """Produces an instance for export tests, and updates the opcode.

    """
    if online:
      admin_state = constants.ADMINST_UP
    else:
      admin_state = constants.ADMINST_DOWN

    if snapshottable:
      disk_template = constants.DT_PLAIN
    else:
      disk_template = constants.DT_FILE

    inst = self.cfg.AddNewInstance(admin_state=admin_state,
                                   disk_template=disk_template)
    self.op = self.CopyOpCode(self.op, instance_name=inst.name)

  @TrySnapshots(True)
  @InstanceRemoved(False)
  def testPlainExportWithShutdown(self):
    self._PrepareInstance(online=True)
    self.ExecOpCode(self.op)

  @TrySnapshots(False)
  @InstanceRemoved(False)
  def testFileExportWithShutdown(self):
    self._PrepareInstance(online=True, snapshottable=False)
    self.ExecOpCodeExpectOpExecError(self.op, ".*--long-sleep option.*")

  @TrySnapshots(False)
  @InstanceRemoved(False)
  def testFileLongSleepExport(self):
    self._PrepareInstance(online=True, snapshottable=False)
    op = self.CopyOpCode(self.op, long_sleep=True)
    self.ExecOpCode(op)

  @TrySnapshots(True)
  @InstanceRemoved(False)
  def testPlainLiveExport(self):
    self._PrepareInstance(online=True)
    op = self.CopyOpCode(self.op, shutdown=False)
    self.ExecOpCode(op)

  @TrySnapshots(False)
  @InstanceRemoved(False)
  def testFileLiveExport(self):
    self._PrepareInstance(online=True, snapshottable=False)
    op = self.CopyOpCode(self.op, shutdown=False)
    self.ExecOpCodeExpectOpExecError(op, ".*live export.*")

  @TrySnapshots(False)
  @InstanceRemoved(False)
  def testPlainOfflineExport(self):
    self._PrepareInstance(online=False)
    self.ExecOpCode(self.op)

  @TrySnapshots(False)
  @InstanceRemoved(False)
  def testFileOfflineExport(self):
    self._PrepareInstance(online=False, snapshottable=False)
    self.ExecOpCode(self.op)

  @TrySnapshots(False)
  @InstanceRemoved(True)
  def testExportRemoveOfflineInstance(self):
    self._PrepareInstance(online=False)
    op = self.CopyOpCode(self.op, remove_instance=True)
    self.ExecOpCode(op)

  @TrySnapshots(False)
  @InstanceRemoved(True)
  def testExportRemoveOnlineInstance(self):
    self._PrepareInstance(online=True)
    op = self.CopyOpCode(self.op, remove_instance=True)
    self.ExecOpCode(op)

  @TrySnapshots(False)
  @InstanceRemoved(False)
  def testValidCompressionTool(self):
    op = self.CopyOpCode(self.op, compress="lzop")
    self.cfg.SetCompressionTools(["gzip", "lzop"])
    self.ExecOpCode(op)

  @InstanceRemoved(False)
  def testInvalidCompressionTool(self):
    op = self.CopyOpCode(self.op, compress="invalid")
    self.cfg.SetCompressionTools(["gzip", "lzop"])
    self.ExecOpCodeExpectOpPrereqError(op, "Compression tool not allowed")

  def testLiveLongSleep(self):
    op = self.CopyOpCode(self.op, shutdown=False, long_sleep=True)
    self.ExecOpCodeExpectOpPrereqError(op, ".*long sleep.*")


class TestLUBackupExportRemoteExport(TestLUBackupExportBase):
  def setUp(self):
    super(TestLUBackupExportRemoteExport, self).setUp()

    self.inst = self.cfg.AddNewInstance()
    self.op = opcodes.OpBackupExport(mode=constants.EXPORT_MODE_REMOTE,
                                     instance_name=self.inst.name,
                                     target_node=[],
                                     x509_key_name=["mock_key_name"],
                                     destination_x509_ca="mock_dest_ca")

  @InstanceRemoved(False)
  def testRemoteExportWithoutX509KeyName(self):
    op = self.CopyOpCode(self.op, x509_key_name=self.REMOVE)
    self.ExecOpCodeExpectOpPrereqError(op,
                                       "Missing X509 key name for encryption")

  @InstanceRemoved(False)
  def testRemoteExportWithoutX509DestCa(self):
    op = self.CopyOpCode(self.op, destination_x509_ca=self.REMOVE)
    self.ExecOpCodeExpectOpPrereqError(op,
                                       "Missing destination X509 CA")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
