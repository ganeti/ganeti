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


"""UEFI firmware disk creation on clusters whose template default access
is userspace (M1): the firmware disk must reach the node with
access=kernelspace so the volume is mapped (rbd map) and can be seeded.
"""

import os
import sys
import unittest

from ganeti import constants
from ganeti import objects
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


class TestUefiCreateOnUserspaceRbd(CmdlibTestCase):
  """Create a UEFI instance on an RBD cluster with access=userspace.

  The firmware disk must be created (and seeded) with kernelspace
  access even though the template default is userspace, so that the
  node maps the volume and the dm/loop pflash mechanism finds a local
  block device.
  """

  def _GetTestModule(self):
    return "instance_create"

  def setUp(self):
    super().setUp()
    # RBD template default: userspace access. Fill via FillDict so the
    # other RBD params (pool, namespace, user-id) keep their defaults.
    rbd_params = objects.FillDict(constants.DISK_DT_DEFAULTS[constants.DT_RBD],
                                  {constants.LDP_ACCESS:
                                   constants.DISK_USERSPACE})
    self.cfg.GetClusterInfo().diskparams[constants.DT_RBD] = rbd_params

    # Capture the disk objects shipped to the nodes at the bdev.Create
    self.MockOutOsDiagnoseRpc()
    self.MockOutNodeInfoRpc()
    self.create_calls = []
    self.rpc.call_blockdev_create.side_effect = \
        self._CaptureBlockdevCreate
    self.seed_calls = []
    self.rpc.call_blockdev_seed_firmware.side_effect = \
        self._CaptureSeedFirmware

  def _SuccessfulResult(self, node):
    return self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(node, None)


  def MockOutNodeInfoRpc(self):
    """Make node-info RPCs succeed with plenty of free resources."""
    bootid = "mock_bootid"
    storage_info = [{
      "type": constants.ST_LVM_VG,
      "storage_free": 10000,
    }]
    hv_info = {
      "cpu_total": 16,
      "memory_free": 2048,
    }
    node_info_result = (bootid, storage_info, (hv_info,))

    def _NodeInfoResult(node, *_):
      if isinstance(node, (list, tuple)):
        builder = self.RpcResultsBuilder()
        for single_node in node:
          builder.AddSuccessfulNode(single_node, node_info_result)
        return builder.Build()
      return self.RpcResultsBuilder() \
          .CreateSuccessfulNodeResult(node, node_info_result)

    self.rpc.call_node_info.side_effect = _NodeInfoResult
    self.rpc.call_instance_info.side_effect = \
        lambda node, inst, hv, hvp: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_bridges_exist.side_effect = \
        lambda node, bridges: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, True)
    self.rpc.call_blockdev_getmirrorstatus.side_effect = \
        lambda node, disks: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, [])
    self.rpc.call_blockdev_wipe.side_effect = \
        lambda node, disk, *a: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_blockdev_shutdown.side_effect = \
        lambda node, disk, *a: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_blockdev_remove.side_effect = \
        lambda node, disk, *a: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_blockdev_assemble.side_effect = \
        lambda node, disk, *a, **kw: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, (None, None, None))
    self.rpc.call_instance_start.side_effect = \
        lambda node, inst, hv, sa: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)

  def MockOutOsDiagnoseRpc(self):
    """Make OS diagnose succeed with the mocked default OS."""
    os_obj = self.cfg.GetDefaultOs()
    os_result = [(os_obj.name,
                  os_obj.path,
                  True,
                  "",
                  os_obj.supported_variants,
                  os_obj.supported_parameters,
                  os_obj.api_versions,
                  True)]
    self.rpc.call_os_diagnose.side_effect = \
        lambda nodes, *_: self.RpcResultsBuilder() \
            .AddSuccessfulNode(self.cfg.GetMasterNodeInfo(), os_result) \
            .Build()

  def _CaptureBlockdevCreate(self, node, disk, *_args, **_kwargs):
    self.create_calls.append((node, disk[0]))
    return self._SuccessfulResult(node)

  def _CaptureSeedFirmware(self, node, disk, code_path, vars_path):
    self.seed_calls.append((node, disk[0], code_path, vars_path))
    return self._SuccessfulResult(node)

  def _UefiCreateOp(self):
    return opcodes.OpInstanceCreate(
        instance_name="uefi-rbd.example.com",
        pnode=self.cfg.GetMasterNodeInfo().name,
        disk_template=constants.DT_RBD,
        hypervisor=constants.HT_KVM,
        mode=constants.INSTANCE_CREATE,
        nics=[{}],
        disks=[{constants.IDISK_SIZE: 1024}],
        os_type=self.cfg.GetDefaultOs().name,
        hvparams={constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})

  def testFirmwareDiskCreatedKernelspaceOnUserspaceRbd(self):
    self.ExecOpCode(self._UefiCreateOp())

    fw_disks = [disk for (_, disk) in self.create_calls
                if disk.role == constants.DR_ROLE_FIRMWARE]
    self.assertEqual(1, len(fw_disks))

    fw_disk = fw_disks[0]
    # The disk must be shipped with kernelspace access: this is what the
    # node-side bdev.Create/Attach sees and decides rbd map on.
    self.assertEqual(constants.DISK_KERNELSPACE,
                     fw_disk.params[constants.LDP_ACCESS])

    # Data disks keep the template default (userspace).
    data_disks = [disk for (_, disk) in self.create_calls
                  if disk.role != constants.DR_ROLE_FIRMWARE]
    self.assertEqual(1, len(data_disks))
    self.assertEqual(constants.DISK_USERSPACE,
                     data_disks[0].params[constants.LDP_ACCESS])

  def testFirmwareDiskSeededKernelspaceOnUserspaceRbd(self):
    self.ExecOpCode(self._UefiCreateOp())

    self.assertEqual(1, len(self.seed_calls))
    (_, seeded_disk, _, _) = self.seed_calls[0]
    self.assertEqual(constants.DR_ROLE_FIRMWARE, seeded_disk.role)
    self.assertEqual(constants.DISK_KERNELSPACE,
                     seeded_disk.params[constants.LDP_ACCESS])


  def testFirmwareDiskParamsPersistedInConfig(self):
    self.ExecOpCode(self._UefiCreateOp())

    inst = self.cfg.GetInstanceInfoByName("uefi-rbd.example.com")
    fw = [d for d in self.cfg.GetInstanceDisks(inst.uuid)
          if d.role == constants.DR_ROLE_FIRMWARE]
    self.assertEqual(1, len(fw))
    self.assertEqual(constants.DISK_KERNELSPACE,
                     fw[0].params[constants.LDP_ACCESS])


if __name__ == "__main__":
  unittest.main()
