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

"""boot_type corner cases: hvparam inheritance must not touch the disk
lifecycle, and boot paths must detect uefi-without-firmware-disk early.
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


class BootTypeTestBase(CmdlibTestCase):
  """Common fixtures: a KVM instance and helpers to inspect its disks.

  _GetTestModule must return a real cmdlib module name (CmdlibTestCase
  derives it from the legacy <module>_unittest.py file-name convention,
  which this pytest file does not follow).
  """

  def _GetTestModule(self):
    return "instance_set_params"

  def setUp(self):
    super().setUp()
    self.MockOutNodeInfoRpc()
    self.MockOutDiskCreationRpcs()

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

  def MockOutDiskCreationRpcs(self):
    """Make blockdev create/seed/wipe RPCs succeed everywhere."""
    self.rpc.call_blockdev_create.side_effect = \
        lambda node, disk, *_: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    seed_calls = []
    self.rpc.call_blockdev_seed_firmware.side_effect = \
        lambda node, disk, code_path, vars_path: (seed_calls.append(
            (code_path, vars_path)) or
            self.RpcResultsBuilder()
            .CreateSuccessfulNodeResult(node, None))
    self.seed_calls = seed_calls
    self.rpc.call_blockdev_wipe.side_effect = \
        lambda node, disk, *_: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_blockdev_shutdown.side_effect = \
        lambda node, disk, *_: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_blockdev_remove.side_effect = \
        lambda node, disk, *_: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, None)
    self.rpc.call_blockdev_assemble.side_effect = \
        lambda node, disk, *a, **kw: self.RpcResultsBuilder() \
            .CreateSuccessfulNodeResult(node, (None, None, None))

  def AddKvmInstance(self, admin_state=constants.ADMINST_DOWN,
                     hvparams=None, disks=None):
    """Add a KVM instance; defaults to a stopped plain-template one."""
    return self.cfg.AddNewInstance(hypervisor=constants.HT_KVM,
                                   hvparams=hvparams,
                                   admin_state=admin_state,
                                   disks=disks)

  def GetFirmwareDisks(self, inst):
    return [d for d in self.cfg.GetInstanceDisks(inst.uuid)
            if d.role == constants.DR_ROLE_FIRMWARE]

  def SetClusterKvmBootType(self, boot_type):
    """Set the cluster-wide KVM default for boot_type."""
    hvparams = self.cluster.hvparams[constants.HT_KVM]
    hvparams[constants.HV_BOOT_TYPE] = boot_type


class TestSetParamsBootTypeTransition(BootTypeTestBase):
  """_CheckBootTypeTransition: explicit vs inherited uefi (tests T1-T8)."""

  def _ModifyOp(self, inst, **kwargs):
    return opcodes.OpInstanceSetParams(instance_name=inst.name, **kwargs)

  def testUnrelatedModifyOnRunningUefiInheritedInstance(self):
    """T1: cluster default uefi, running instance, unrelated modify."""
    inst = self.AddKvmInstance(admin_state=constants.ADMINST_UP)
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    op = self._ModifyOp(inst, beparams={constants.BE_MINMEM: 128})

    self.ExecOpCode(op)
    self.assertEqual(0, len(self.GetFirmwareDisks(inst)))

  def testDiskTemplateModifyOnStoppedUefiInheritedInstance(self):
    """T2: cluster default uefi, stopped instance, node-res-lock-holding
    modify must not create a firmware disk."""
    inst = self.AddKvmInstance()
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    # a template change holds node-res locks - the scenario that used to
    # silently flip _add_firmware_disk
    op = self._ModifyOp(inst,
                        disk_template=constants.DT_DRBD8,
                        remote_node=self.cfg.AddNewNode().name)

    self.ExecOpCode(op)
    self.assertEqual(0, len(self.GetFirmwareDisks(inst)))

  def testExplicitUefiOnStoppedUefiInheritedInstance(self):
    """T3: cluster default uefi, stopped instance, explicit boot_type
    creates the firmware disk (missing-disk recovery path)."""
    inst = self.AddKvmInstance()
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    op = self._ModifyOp(inst,
                        hvparams={constants.HV_BOOT_TYPE:
                                  constants.HT_BOOT_UEFI})

    result = self.ExecOpCode(op)
    self.assertEqual(1, len(self.GetFirmwareDisks(inst)))
    self.assertIn(("firmware_disk", "add:role=%s" %
                   constants.DR_ROLE_FIRMWARE), result)

  def testExplicitUefiOnRunningInstance(self):
    """T4: running instance, explicit uefi must fail (state check)."""
    inst = self.AddKvmInstance(admin_state=constants.ADMINST_UP)

    op = self._ModifyOp(inst,
                        hvparams={constants.HV_BOOT_TYPE:
                                  constants.HT_BOOT_UEFI})

    self.ExecOpCodeExpectOpPrereqError(
        op, "cannot add the UEFI firmware disk")
    self.assertEqual(0, len(self.GetFirmwareDisks(inst)))

  def testExplicitUefiOnBiosCluster(self):
    """T5: baseline - bios default, stopped instance, explicit uefi
    creates the disk."""
    inst = self.AddKvmInstance()
    self.SetClusterKvmBootType(constants.HT_BOOT_BIOS)

    op = self._ModifyOp(inst,
                        hvparams={constants.HV_BOOT_TYPE:
                                  constants.HT_BOOT_UEFI})

    result = self.ExecOpCode(op)
    self.assertEqual(1, len(self.GetFirmwareDisks(inst)))
    self.assertIn(("firmware_disk", "add:role=%s" %
                   constants.DR_ROLE_FIRMWARE), result)

  def testExplicitUefiWithExistingFirmwareDisk(self):
    """T6: idempotent re-set; no error, no duplicate disk."""
    fw_disk = self.cfg.CreateDisk(
        size=constants.OVMF_FIRMWARE_DISK_SIZE,
        params={constants.LDP_ACCESS: constants.DISK_KERNELSPACE})
    fw_disk.role = constants.DR_ROLE_FIRMWARE
    inst = self.AddKvmInstance(disks=[fw_disk])

    op = self._ModifyOp(inst,
                        hvparams={constants.HV_BOOT_TYPE:
                                  constants.HT_BOOT_UEFI})

    self.ExecOpCode(op)
    self.assertEqual(1, len(self.GetFirmwareDisks(inst)))

  def testNonKvmInstanceWithUefiClusterDefault(self):
    """T7: non-KVM hypervisor, cluster default uefi: no error, no disk."""
    inst = self.cfg.AddNewInstance(hypervisor=constants.HT_XEN_PVM)
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    op = self._ModifyOp(inst, beparams={constants.BE_VCPUS: 2})

    self.ExecOpCode(op)
    self.assertEqual(0, len(self.GetFirmwareDisks(inst)))

  def testExplicitBiosOnUefiInheritedInstance(self):
    """T8: switching explicitly away keeps the disk inert but in place."""
    fw_disk = self.cfg.CreateDisk(
        size=constants.OVMF_FIRMWARE_DISK_SIZE,
        params={constants.LDP_ACCESS: constants.DISK_KERNELSPACE})
    fw_disk.role = constants.DR_ROLE_FIRMWARE
    inst = self.AddKvmInstance(disks=[fw_disk])
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    op = self._ModifyOp(inst,
                        hvparams={constants.HV_BOOT_TYPE:
                                  constants.HT_BOOT_BIOS})

    self.ExecOpCode(op)
    self.assertEqual(1, len(self.GetFirmwareDisks(inst)))


class TestOvmfTemplateResolution(BootTypeTestBase):
  """Seed RPC must receive the resolved ovmf_code/ovmf_vars paths."""

  def _ModifyToUefi(self, inst, extra_hvparams=None):
    hvparams = {constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI}
    hvparams.update(extra_hvparams or {})
    return opcodes.OpInstanceSetParams(instance_name=inst.name,
                                       hvparams=hvparams)

  def _CreateUefiOp(self, instance_name, hvparams):
    self._setupOSDiagnose()
    return opcodes.OpInstanceCreate(
        instance_name=instance_name,
        pnode=self.master.name,
        disk_template=constants.DT_PLAIN,
        mode=constants.INSTANCE_CREATE,
        nics=[{}],
        disks=[{constants.IDISK_SIZE: 1024}],
        hypervisor=constants.HT_KVM,
        hvparams=hvparams,
        os_type=self.os_name_variant)

  def _setupOSDiagnose(self):
    os_result = [(self.os.name,
                  self.os.path,
                  True,
                  "",
                  self.os.supported_variants,
                  self.os.supported_parameters,
                  self.os.api_versions,
                  True)]
    self.rpc.call_os_diagnose.return_value = \
        self.RpcResultsBuilder() \
            .AddSuccessfulNode(self.master, os_result) \
            .Build()

  def testModifySeedsWithExplicitOverrides(self):
    inst = self.AddKvmInstance()
    op = self._ModifyToUefi(inst, {
        constants.HV_OVMF_CODE: "/custom/OVMF_CODE.fd",
        constants.HV_OVMF_VARS: "/custom/OVMF_VARS.fd"})

    self.ExecOpCode(op)

    self.assertEqual(1, len(self.GetFirmwareDisks(inst)))
    self.assertEqual([("/custom/OVMF_CODE.fd", "/custom/OVMF_VARS.fd")],
                     self.seed_calls)

  def testModifySeedsWithTemplateDefaults(self):
    inst = self.AddKvmInstance()
    op = self._ModifyToUefi(inst)

    self.ExecOpCode(op)

    self.assertEqual([(constants.OVMF_CODE_TEMPLATE,
                       constants.OVMF_VARS_TEMPLATE)],
                     self.seed_calls)

  def testModifyEmptyOverrideFallsBackToTemplates(self):
    inst = self.AddKvmInstance()
    op = self._ModifyToUefi(inst, {
        constants.HV_OVMF_CODE: "",
        constants.HV_OVMF_VARS: ""})

    self.ExecOpCode(op)

    self.assertEqual([(constants.OVMF_CODE_TEMPLATE,
                       constants.OVMF_VARS_TEMPLATE)],
                     self.seed_calls)

  def testCreateSeedsWithExplicitOverrides(self):
    op = self._CreateUefiOp("uefi-create.example.com", {
        constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI,
        constants.HV_OVMF_CODE: "/custom/OVMF_CODE.fd",
        constants.HV_OVMF_VARS: "/custom/OVMF_VARS.fd"})

    self.ExecOpCode(op)

    self.assertEqual([("/custom/OVMF_CODE.fd", "/custom/OVMF_VARS.fd")],
                     self.seed_calls)

  def testCreateSeedsWithTemplateDefaults(self):
    op = self._CreateUefiOp("uefi-default.example.com", {
        constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})

    self.ExecOpCode(op)

    self.assertEqual([(constants.OVMF_CODE_TEMPLATE,
                       constants.OVMF_VARS_TEMPLATE)],
                     self.seed_calls)


class TestBootPathGuards(BootTypeTestBase):
  """Startup/failover/move must detect uefi-without-firmware (U1-U6)."""

  def _AddUefiResolvingInstance(self, disks=None):
    inst = self.AddKvmInstance(disks=disks)
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)
    return inst

  def _FirmwareDisk(self):
    disk = self.cfg.CreateDisk(
        size=constants.OVMF_FIRMWARE_DISK_SIZE,
        params={constants.LDP_ACCESS: constants.DISK_KERNELSPACE})
    disk.role = constants.DR_ROLE_FIRMWARE
    return disk

  def testStartupRefusedWithoutFirmwareDisk(self):
    """U1: resolves uefi, no firmware disk -> actionable prereq error."""
    inst = self._AddUefiResolvingInstance()

    op = opcodes.OpInstanceStartup(instance_name=inst.name, force=False)

    self.ExecOpCodeExpectOpPrereqError(
        op, "no UEFI firmware disk.*gnt-instance modify")

  def testStartupProceedsWithFirmwareDisk(self):
    """U2: disk present -> prereq passes."""
    inst = self._AddUefiResolvingInstance(disks=[self._FirmwareDisk()])

    op = opcodes.OpInstanceStartup(instance_name=inst.name, force=False)

    self.ExecOpCode(op)

  def testStartupEphemeralUefiOverrideRefused(self):
    """U3: start-time -H boot_type=uefi without a disk is refused in
    prereq, not by the node's hypervisor."""
    inst = self.AddKvmInstance()  # cluster default stays direct_kernel

    op = opcodes.OpInstanceStartup(
        instance_name=inst.name, force=False,
        hvparams={constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI})

    self.ExecOpCodeExpectOpPrereqError(
        op, "no UEFI firmware disk.*gnt-instance modify")

  def testFailoverRefusedWithoutFirmwareDisk(self):
    """U4: failover of a uefi-resolving instance without a disk."""
    inst = self.cfg.AddNewInstance(
        hypervisor=constants.HT_KVM,
        disk_template=constants.DT_DRBD8,
        secondary_node=self.cfg.AddNewNode())
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    op = opcodes.OpInstanceFailover(instance_name=inst.name)

    self.ExecOpCodeExpectOpPrereqError(
        op, "no UEFI firmware disk.*gnt-instance modify")

  def testMoveRefusedWithoutFirmwareDisk(self):
    """U5: move of a uefi-resolving instance without a disk."""
    inst = self.cfg.AddNewInstance(hypervisor=constants.HT_KVM)
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    op = opcodes.OpInstanceMove(instance_name=inst.name,
                                target_node=self.cfg.AddNewNode().name)

    self.ExecOpCodeExpectOpPrereqError(
        op, "no UEFI firmware disk.*gnt-instance modify")

  def testStartupAllowedForBiosInstance(self):
    """U6: resolves bios, no firmware disk -> no error."""
    inst = self.AddKvmInstance()
    self.SetClusterKvmBootType(constants.HT_BOOT_BIOS)

    op = opcodes.OpInstanceStartup(instance_name=inst.name, force=False)

    self.ExecOpCode(op)


class TestClusterBootTypeDefaultFlip(BootTypeTestBase):
  """ClusterSetParams: flipping the KVM boot_type default to uefi (C1-C7)."""

  def _FlipOp(self, force=False):
    return opcodes.OpClusterSetParams(
        hvparams={constants.HT_KVM: {
          constants.HV_BOOT_TYPE: constants.HT_BOOT_UEFI}},
        force=force)

  def testFlipRefusedWithAffectedInstances(self):
    """C1: affected instances, no --force -> prereq error naming them."""
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM)
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM)

    self.ExecOpCodeExpectOpPrereqError(
        self._FlipOp(), "leave 2 instance.*--force")

  def testFlipForcedSubmitsMigrationJob(self):
    """C2: --force with a stopped affected instance submits a follow-up
    job switching it explicitly (creating its firmware disk)."""
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM)

    result = self.ExecOpCode(self._FlipOp(force=True)) or {}

    self.assertEqual(constants.HT_BOOT_UEFI,
                     self.cluster.hvparams[constants.HT_KVM]
                     [constants.HV_BOOT_TYPE])
    self.assertLogContainsRegex(
        "Submitting follow-up jobs to switch 1 stopped")
    self.assertEqual(1, len(result.get(constants.JOB_IDS_KEY, ())))

  def testFlipForcedRunningInstanceOnlyWarned(self):
    """C6: --force cannot grow a disk under a running instance; it is
    warned about and no follow-up job is submitted for it."""
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM,
                            admin_state=constants.ADMINST_UP)

    result = self.ExecOpCode(self._FlipOp(force=True)) or {}

    self.assertEqual(0, len(result.get(constants.JOB_IDS_KEY, ())))
    self.assertLogContainsRegex(
        "1 affected instance.*running or offline.*refuse to start")

  def testFlipForcedMixedInstances(self):
    """C7: --force submits jobs for stopped instances only."""
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM)
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM,
                            admin_state=constants.ADMINST_UP)

    result = self.ExecOpCode(self._FlipOp(force=True)) or {}

    self.assertEqual(1, len(result.get(constants.JOB_IDS_KEY, ())))

  def testFlipAllowedWhenAllInstancesHaveFirmwareDisks(self):
    """C3: affected set empty because disks exist -> silent success."""
    fw_disk = self.cfg.CreateDisk(
        size=constants.OVMF_FIRMWARE_DISK_SIZE,
        params={constants.LDP_ACCESS: constants.DISK_KERNELSPACE})
    fw_disk.role = constants.DR_ROLE_FIRMWARE
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM, disks=[fw_disk])

    self.ExecOpCode(self._FlipOp())

    self.assertEqual(constants.HT_BOOT_UEFI,
                     self.cluster.hvparams[constants.HT_KVM]
                     [constants.HV_BOOT_TYPE])

  def testFlipIgnoresInstancesWithExplicitOverride(self):
    """C4: an instance-level boot_type override removes it from the
    affected set."""
    self.cfg.AddNewInstance(
        hypervisor=constants.HT_KVM,
        hvparams={constants.HV_BOOT_TYPE: constants.HT_BOOT_BIOS})

    result = self.ExecOpCode(self._FlipOp()) or {}

    self.assertEqual(0, len(result.get(constants.JOB_IDS_KEY, ())))

  def testFlipToUefiWhenAlreadyUefi(self):
    """C5: no transition (old default already uefi) -> silent success."""
    self.cfg.AddNewInstance(hypervisor=constants.HT_KVM)
    self.SetClusterKvmBootType(constants.HT_BOOT_UEFI)

    result = self.ExecOpCode(self._FlipOp()) or {}

    self.assertEqual(0, len(result.get(constants.JOB_IDS_KEY, ())))


if __name__ == "__main__":
  unittest.main()
