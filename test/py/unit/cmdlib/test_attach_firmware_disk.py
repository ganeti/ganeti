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


"""Attaching a second firmware-role disk to an instance must be rejected
(M4): two NVRAM stores would silently fork, and the hypervisor only ever
reads the first (see L{ganeti.hypervisor.hv_kvm}._FindFirmwareDisk).
"""

import os
import sys
import unittest

from ganeti import constants
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


class TestAttachFirmwareDisk(CmdlibTestCase):
  """DDM_ATTACH of firmware-role disks and the one-per-instance invariant."""

  def _GetTestModule(self):
    return "instance_set_params"

  def setUp(self):
    super().setUp()
    self.cfg.GetClusterInfo().default_iallocator = None
    self.MockOutDiskRpcs()

    self.fw_disk = self.cfg.CreateDisk(
        size=constants.OVMF_FIRMWARE_DISK_SIZE,
        params={constants.LDP_ACCESS: constants.DISK_KERNELSPACE})
    self.fw_disk.role = constants.DR_ROLE_FIRMWARE
    self.inst = self.cfg.AddNewInstance(disks=[self.fw_disk])


  def MockOutDiskRpcs(self):
    """Make disk assemble/mirror RPCs succeed everywhere."""
    self.rpc.call_blockdev_assemble.side_effect = \
        lambda node, disk, *a, **kw: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, ("/dev/mocked_path",
                                                "mocked_link", None))
    self.rpc.call_blockdev_getmirrorstatus.side_effect = \
        lambda node, disks: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, [])
    self.rpc.call_blockdev_shutdown.side_effect = \
        lambda node, disk, *a: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)

  def _DetachOrphan(self, disk):
    """Create a now-orphan disk: attach to a throwaway instance (which
    registers it in the config), then detach it again."""
    throwaway = self.cfg.AddNewInstance()
    self.cfg.AddInstanceDisk(throwaway.uuid, disk)
    self.cfg.DetachInstanceDisk(throwaway.uuid, disk.uuid)
    self.cfg.RemoveInstance(throwaway.uuid)

  def _AttachOp(self, disk):
    return opcodes.OpInstanceSetParams(
        instance_name=self.inst.name,
        disks=[[constants.DDM_ATTACH, -1,
                {
                  "uuid": disk.uuid,
                }]])

  def testAttachSecondFirmwareDiskIsRejected(self):
    """The instance already owns a firmware disk; attaching a second one
    (e.g. a stale NVRAM disk left over after a detach) must fail prereq."""
    orphan_fw = self.cfg.CreateDisk(
        size=constants.OVMF_FIRMWARE_DISK_SIZE,
        params={constants.LDP_ACCESS: constants.DISK_KERNELSPACE})
    orphan_fw.role = constants.DR_ROLE_FIRMWARE
    self._DetachOrphan(orphan_fw)

    self.ExecOpCodeExpectOpPrereqError(
        self._AttachOp(orphan_fw), "already has a firmware disk")

  def testAttachFirmwareDiskToInstanceWithNoneSucceeds(self):
    """Attaching a firmware disk to an instance that has none (e.g.
    re-attaching the NVRAM disk after a prior detach) must succeed."""
    self.cfg.DetachInstanceDisk(self.inst.uuid, self.fw_disk.uuid)

    self.ExecOpCode(self._AttachOp(self.fw_disk))

    roles = [d.role for d in self.cfg.GetInstanceDisks(self.inst.uuid)]
    self.assertEqual(roles.count(constants.DR_ROLE_FIRMWARE), 1)

  def testAttachPlainDiskIsUnaffected(self):
    """A plain data disk attaches normally next to the firmware disk."""
    data_disk = self.cfg.CreateDisk(size=1024)
    self._DetachOrphan(data_disk)

    self.ExecOpCode(self._AttachOp(data_disk))

    roles = [d.role for d in self.cfg.GetInstanceDisks(self.inst.uuid)]
    self.assertEqual(roles.count(constants.DR_ROLE_FIRMWARE), 1)
    self.assertEqual(2, len(roles))


if __name__ == "__main__":
  unittest.main()
