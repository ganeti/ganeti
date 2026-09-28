#
#

# Copyright (C) 2026 the Ganeti project
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

"""Zeroing backup boot_type checks.

The zeroing image boots from disk via firmware, so any direct-kernel
boot type (with or without UEFI) is rejected up front.

"""
import os
import sys
import unittest
from unittest import mock

from ganeti import constants
from ganeti import errors
from ganeti import opcodes

# The CmdlibTestCase support lives in the legacy test tree; make it
# importable regardless of how pytest was invoked (the make target runs
# from a temp dir without the legacy tree on sys.path).
LEGACY_PATH = os.path.realpath(os.path.join(os.path.dirname(__file__),
                                            "..", "..", "legacy"))
if LEGACY_PATH not in sys.path:
  sys.path.insert(0, LEGACY_PATH)

# pylint: disable=C0411,C0413,E0401
from cmdlib.testsupport.cmdlib_testcase import CmdlibTestCase


class TestBackupExportZeroingBootType(CmdlibTestCase):
  """LUBackupExport zero_free_space rejects direct-kernel boot types."""

  def _GetTestModule(self):
    return "backup"

  def setUp(self):
    super().setUp()
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, ("/dev/mock_path",
                                                  "/dev/mock_link_name",
                                                  None))
    self.rpc.call_blockdev_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, None)

  def _ZeroingOp(self, inst):
    return opcodes.OpBackupExport(instance_name=inst.name,
                                  target_node=self.master.name,
                                  mode=constants.EXPORT_MODE_LOCAL,
                                  zero_free_space=True)

  def _AddKvmInstance(self, boot_type):
    return self.cfg.AddNewInstance(
        hypervisor=constants.HT_KVM,
        hvparams={constants.HV_BOOT_TYPE: boot_type,
                  constants.HV_KVM_USER_SHUTDOWN: True})

  def testDirectKernelRejected(self):
    inst = self._AddKvmInstance(constants.HT_BOOT_DIRECT_KERNEL)
    op = self._ZeroingOp(inst)
    self.ExecOpCodeExpectOpPrereqError(op, "not direct kernel boot")

  def testDirectKernelEfiRejected(self):
    # direct_kernel_efi is a direct-kernel mode, so the zeroing guard must
    # reject it like direct_kernel (the zeroing image boots from disk via
    # firmware and any -kernel boot bypasses the disk). It is also an OVMF
    # mode, so in the full LU the export block fires first; drive the
    # zeroing check in isolation with the export block stubbed out.
    import ganeti.cmdlib.backup as backup_mod

    self.assertTrue(
        backup_mod.uses_direct_kernel(constants.HT_BOOT_DIRECT_KERNEL_EFI))
    inst = self._AddKvmInstance(constants.HT_BOOT_DIRECT_KERNEL_EFI)
    lu = backup_mod.LUBackupExport.__new__(backup_mod.LUBackupExport)
    lu.cfg = self.cfg
    lu.instance = inst
    lu.op = self._ZeroingOp(inst)
    lu.op.target_node_uuid = self.master.uuid
    lu._process = None
    with mock.patch.object(backup_mod, "uses_ovmf", return_value=False):
      with self.assertRaises(errors.OpPrereqError) as ctx:
        lu.CheckPrereq()
    self.assertIn("not direct kernel boot", str(ctx.exception))

  def testUefiRejectedByExportBlock(self):
    # uefi passes the zeroing boot_type check but is still rejected by
    # the earlier OVMF export block.
    inst = self._AddKvmInstance(constants.HT_BOOT_UEFI)
    op = self._ZeroingOp(inst)
    self.ExecOpCodeExpectOpPrereqError(op, "Exporting UEFI instances")

  def testBiosBootOrderCdromRejected(self):
    inst = self._AddKvmInstance(constants.HT_BOOT_BIOS)
    inst.hvparams[constants.HV_BOOT_ORDER] = constants.HT_BO_CDROM
    op = self._ZeroingOp(inst)
    self.ExecOpCodeExpectOpPrereqError(op, "Booting from disk")


if __name__ == "__main__":
  unittest.main()
