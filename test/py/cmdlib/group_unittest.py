#!/usr/bin/python3
#

# Copyright (C) 2008, 2011, 2012, 2013 Google Inc.
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


"""Tests for LUGroup*

"""

import itertools

from ganeti import constants
from ganeti import opcodes
from ganeti import query

from testsupport import *

import testutils


class TestLUGroupAdd(CmdlibTestCase):
  def testAddExistingGroup(self):
    self.cfg.AddNewNodeGroup(name="existing_group")

    op = opcodes.OpGroupAdd(group_name="existing_group")
    self.ExecOpCodeExpectOpPrereqError(
      op, "Desired group name 'existing_group' already exists")

  def testAddNewGroup(self):
    op = opcodes.OpGroupAdd(group_name="new_group")

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()

  def testAddNewGroupParams(self):
    ndparams = {constants.ND_EXCLUSIVE_STORAGE: True}
    hv_state = {constants.HT_FAKE: {constants.HVST_CPU_TOTAL: 8}}
    disk_state = {
      constants.DT_PLAIN: {
        "mock_vg": {constants.DS_DISK_TOTAL: 10}
      }
    }
    diskparams = {constants.DT_RBD: {constants.RBD_POOL: "mock_pool"}}
    ipolicy = constants.IPOLICY_DEFAULTS
    op = opcodes.OpGroupAdd(group_name="new_group",
                            ndparams=ndparams,
                            hv_state=hv_state,
                            disk_state=disk_state,
                            diskparams=diskparams,
                            ipolicy=ipolicy)

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()

  def testAddNewGroupInvalidDiskparams(self):
    diskparams = {constants.DT_RBD: {constants.LV_STRIPES: 1}}
    op = opcodes.OpGroupAdd(group_name="new_group",
                            diskparams=diskparams)

    self.ExecOpCodeExpectOpPrereqError(
      op, "Provided option keys not supported")

  def testAddNewGroupInvalidIPolic(self):
    ipolicy = {"invalid_key": "value"}
    op = opcodes.OpGroupAdd(group_name="new_group",
                            ipolicy=ipolicy)

    self.ExecOpCodeExpectOpPrereqError(op, "Invalid keys in ipolicy")


class TestLUGroupAssignNodes(CmdlibTestCase):
  def __init__(self, methodName='runTest'):
    super(TestLUGroupAssignNodes, self).__init__(methodName)

    self.op = opcodes.OpGroupAssignNodes(group_name="default",
                                         nodes=[])

  def testAssignSingleNode(self):
    node = self.cfg.AddNewNode()
    op = self.CopyOpCode(self.op, nodes=[node.name])

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()

  def _BuildSplitInstanceSituation(self):
    node = self.cfg.AddNewNode()
    self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                            primary_node=self.master,
                            secondary_node=node)
    group = self.cfg.AddNewNodeGroup()

    return (node, group)

  def testSplitInstanceNoForce(self):
    (node, group) = self._BuildSplitInstanceSituation()
    op = opcodes.OpGroupAssignNodes(group_name=group.name,
                                    nodes=[node.name])

    self.ExecOpCodeExpectOpExecError(
      op, "instances get split by this change and --force was not given")

  def testSplitInstanceForce(self):
    (node, group) = self._BuildSplitInstanceSituation()

    node2 = self.cfg.AddNewNode(group=group)
    self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                            primary_node=self.master,
                            secondary_node=node2)

    op = opcodes.OpGroupAssignNodes(group_name=group.name,
                                    nodes=[node.name],
                                    force=True)

    self.ExecOpCode(op)

    self.mcpu.assertLogContainsRegex("will split the following instances")
    self.mcpu.assertLogContainsRegex(
      "instances continue to be split across groups")


  @withLockedLU
  def testCheckAssignmentForSplitInstances(self, lu):
    self.cfg._OpenConfig(True)
    g1 = self.cfg.AddNewNodeGroup()
    g2 = self.cfg.AddNewNodeGroup()
    g3 = self.cfg.AddNewNodeGroup()

    for (n, g) in [("n1a", g1), ("n1b", g1), ("n2a", g2), ("n2b", g2),
                   ("n3a", g3), ("n3b", g3), ("n3c", g3)]:
      self.cfg.AddNewNode(uuid=n, group=g.uuid)

    for uuid, pnode, snode in [("inst1a", "n1a", "n1b"),
                               ("inst1b", "n1b", "n1a"),
                               ("inst2a", "n2a", "n2b"),
                               ("inst3a", "n3a", None),
                               ("inst3b", "n3b", "n1b"),
                               ("inst3c", "n3b", "n2b")]:
      dt = constants.DT_DISKLESS if snode is None else constants.DT_DRBD8
      self.cfg.AddNewInstance(uuid=uuid,
                              disk_template=dt,
                              primary_node=pnode,
                              secondary_node=snode)

    # Test first with the existing state.
    (new, prev) = lu.CheckAssignmentForSplitInstances(
      [], self.cfg.GetAllNodesInfo(), self.cfg.GetAllInstancesInfo())

    self.assertEqual([], new)
    self.assertEqual(set(["inst3b", "inst3c"]), set(prev))

    # And now some changes.
    (new, prev) = lu.CheckAssignmentForSplitInstances(
      [("n1b", g3.uuid)],
      self.cfg.GetAllNodesInfo(),
      self.cfg.GetAllInstancesInfo())

    self.assertEqual(set(["inst1a", "inst1b"]), set(new))
    self.assertEqual(set(["inst3c"]), set(prev))


class TestLUGroupSetParams(CmdlibTestCase):
  def testNoModifications(self):
    op = opcodes.OpGroupSetParams(group_name=self.group.name)

    self.ExecOpCodeExpectOpPrereqError(op,
                                       "Please pass at least one modification")

  def testModifyingAll(self):
    ndparams = {constants.ND_EXCLUSIVE_STORAGE: True}
    hv_state = {constants.HT_FAKE: {constants.HVST_CPU_TOTAL: 8}}
    disk_state = {
      constants.DT_PLAIN: {
        "mock_vg": {constants.DS_DISK_TOTAL: 10}
      }
    }
    diskparams = {constants.DT_RBD: {constants.RBD_POOL: "mock_pool"}}
    ipolicy = {constants.IPOLICY_DTS: [constants.DT_DRBD8]}
    op = opcodes.OpGroupSetParams(group_name=self.group.name,
                                  ndparams=ndparams,
                                  hv_state=hv_state,
                                  disk_state=disk_state,
                                  diskparams=diskparams,
                                  ipolicy=ipolicy)

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()

  def testInvalidDiskparams(self):
    diskparams = {constants.DT_RBD: {constants.LV_STRIPES: 1}}
    op = opcodes.OpGroupSetParams(group_name=self.group.name,
                                  diskparams=diskparams)

    self.ExecOpCodeExpectOpPrereqError(
      op, "Provided option keys not supported")

  def testIPolicyNewViolations(self):
    self.cfg.AddNewInstance(beparams={constants.BE_VCPUS: 8})

    min_max = dict(constants.ISPECS_MINMAX_DEFAULTS)
    min_max[constants.ISPECS_MAX].update({constants.ISPEC_CPU_COUNT: 2})
    ipolicy = {constants.ISPECS_MINMAX: [min_max]}
    op = opcodes.OpGroupSetParams(group_name=self.group.name,
                                  ipolicy=ipolicy)

    self.ExecOpCode(op)

    self.assertLogContainsRegex(
      "After the ipolicy change the following instances violate them")


class TestLUGroupRemove(CmdlibTestCase):
  def testNonEmptyGroup(self):
    group = self.cfg.AddNewNodeGroup()
    self.cfg.AddNewNode(group=group)
    op = opcodes.OpGroupRemove(group_name=group.name)

    self.ExecOpCodeExpectOpPrereqError(op, "Group .* not empty")

  def testRemoveLastGroup(self):
    self.master.group = "invalid_group"
    op = opcodes.OpGroupRemove(group_name=self.group.name)

    self.ExecOpCodeExpectOpPrereqError(
      op, "Group .* is the only group, cannot be removed")

  def testRemoveGroup(self):
    group = self.cfg.AddNewNodeGroup()
    op = opcodes.OpGroupRemove(group_name=group.name)

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()


class TestLUGroupRename(CmdlibTestCase):
  def testRenameToExistingName(self):
    group = self.cfg.AddNewNodeGroup()
    op = opcodes.OpGroupRename(group_name=group.name,
                               new_name=self.group.name)

    self.ExecOpCodeExpectOpPrereqError(
      op, "Desired new name .* clashes with existing node group")

  def testRename(self):
    group = self.cfg.AddNewNodeGroup()
    op = opcodes.OpGroupRename(group_name=group.name,
                               new_name="new_group_name")

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()


class TestLUGroupEvacuate(CmdlibTestCase):
  def testEvacuateEmptyGroup(self):
    group = self.cfg.AddNewNodeGroup()
    op = opcodes.OpGroupEvacuate(group_name=group.name)

    self.iallocator_cls.return_value.result = ([], [], [])

    self.ExecOpCode(op)

  def testEvacuateOnlyGroup(self):
    op = opcodes.OpGroupEvacuate(group_name=self.group.name)

    self.ExecOpCodeExpectOpPrereqError(
      op, "There are no possible target groups")

  def testEvacuateWithTargetGroups(self):
    group = self.cfg.AddNewNodeGroup()
    self.cfg.AddNewNode(group=group)
    self.cfg.AddNewNode(group=group)

    target_group1 = self.cfg.AddNewNodeGroup()
    target_group2 = self.cfg.AddNewNodeGroup()
    op = opcodes.OpGroupEvacuate(group_name=group.name,
                                 target_groups=[target_group1.name,
                                                target_group2.name])

    self.iallocator_cls.return_value.result = ([], [], [])

    self.ExecOpCode(op)

  def testFailingIAllocator(self):
    group = self.cfg.AddNewNodeGroup()
    op = opcodes.OpGroupEvacuate(group_name=group.name)

    self.iallocator_cls.return_value.success = False

    self.ExecOpCodeExpectOpPrereqError(
      op, "Can't compute group evacuation using iallocator")


class TestLUGroupVerifyDisks(CmdlibTestCase):
  def testNoInstances(self):
    op = opcodes.OpGroupVerifyDisks(group_name=self.group.name)

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()

  def testOfflineAndFailingNode(self):
    node = self.cfg.AddNewNode(offline=True)
    self.cfg.AddNewInstance(primary_node=node,
                            admin_state=constants.ADMINST_UP)
    self.cfg.AddNewInstance(admin_state=constants.ADMINST_UP)
    self.rpc.call_lv_list.return_value = \
      self.RpcResultsBuilder() \
        .AddFailedNode(self.master) \
        .AddOfflineNode(node) \
        .Build()

    op = opcodes.OpGroupVerifyDisks(group_name=self.group.name)

    (nerrors, offline, missing) = self.ExecOpCode(op)

    self.assertEqual(1, len(nerrors))
    self.assertEqual(0, len(offline))
    self.assertEqual(2, len(missing))

  def testValidNodeResult(self):
    self.cfg.AddNewInstance(
      disks=[self.cfg.CreateDisk(dev_type=constants.DT_PLAIN),
             self.cfg.CreateDisk(dev_type=constants.DT_PLAIN)
             ],
      admin_state=constants.ADMINST_UP)
    self.rpc.call_lv_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, {
          "mockvg/mock_disk_1": (None, None, True),
          "mockvg/mock_disk_2": (None, None, False)
        }) \
        .Build()

    op = opcodes.OpGroupVerifyDisks(group_name=self.group.name)

    (nerrors, offline, missing) = self.ExecOpCode(op)

    self.assertEqual(0, len(nerrors))
    self.assertEqual(1, len(offline))
    self.assertEqual(0, len(missing))

  def testDrbdDisk(self):
    node1 = self.cfg.AddNewNode()
    node2 = self.cfg.AddNewNode()
    node3 = self.cfg.AddNewNode()
    node4 = self.cfg.AddNewNode()

    valid_disk = self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                                     primary_node=node1,
                                     secondary_node=node2)
    broken_disk = self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                                      primary_node=node1,
                                      secondary_node=node2)
    failing_node_disk = self.cfg.CreateDisk(dev_type=constants.DT_DRBD8,
                                            primary_node=node3,
                                            secondary_node=node4)

    self.cfg.AddNewInstance(disks=[valid_disk, broken_disk],
                            primary_node=node1,
                            admin_state=constants.ADMINST_UP)
    self.cfg.AddNewInstance(disks=[failing_node_disk],
                            primary_node=node3,
                            admin_state=constants.ADMINST_UP)

    lv_list_result = dict(("/".join(disk.logical_id), (None, None, True))
                          for disk in itertools.chain(valid_disk.children,
                                                      broken_disk.children))
    self.rpc.call_lv_list.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(node1, lv_list_result) \
        .AddSuccessfulNode(node2, lv_list_result) \
        .AddFailedNode(node3) \
        .AddFailedNode(node4) \
        .Build()

    def GetDrbdNeedsActivationResult(node_uuid, *_):
      if node_uuid == node1.uuid:
        return self.RpcResultsBuilder() \
                 .CreateSuccessfulNodeResult(node1, [])
      elif node_uuid == node2.uuid:
        return self.RpcResultsBuilder() \
                 .CreateSuccessfulNodeResult(node2, [broken_disk.uuid])
      elif node_uuid == node3.uuid or node_uuid == node4.uuid:
        return self.RpcResultsBuilder() \
                 .CreateFailedNodeResult(node_uuid)

    self.rpc.call_drbd_needs_activation.side_effect = \
      GetDrbdNeedsActivationResult

    op = opcodes.OpGroupVerifyDisks(group_name=self.group.name)

    (nerrors, offline, missing) = self.ExecOpCode(op)

    self.assertEqual(2, len(nerrors))
    self.assertEqual(1, len(offline))
    self.assertEqual(1, len(missing))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
