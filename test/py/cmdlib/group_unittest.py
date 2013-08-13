#!/usr/bin/python
#

# Copyright (C) 2008, 2011, 2012, 2013 Google Inc.
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


"""Tests for LUGroup*

"""

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
      constants.LD_LV: {
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


class TestLUGroupQuery(CmdlibTestCase):
  def setUp(self):
    super(TestLUGroupQuery, self).setUp()
    self.fields = query._BuildGroupFields().keys()

  def testInvalidGroupName(self):
    op = opcodes.OpGroupQuery(names=["does_not_exist"],
                              output_fields=self.fields)

    self.ExecOpCodeExpectOpPrereqError(op, "Some groups do not exist")

  def testQueryAllGroups(self):
    op = opcodes.OpGroupQuery(output_fields=self.fields)

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()

  def testQueryGroupsByNameAndUuid(self):
    group1 = self.cfg.AddNewNodeGroup()
    group2 = self.cfg.AddNewNodeGroup()

    node1 = self.cfg.AddNewNode(group=group1)
    node2 = self.cfg.AddNewNode(group=group1)
    self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                            primary_node=node1,
                            secondary_node=node2)
    self.cfg.AddNewInstance(primary_node=node2)

    op = opcodes.OpGroupQuery(names=[group1.name, group2.uuid],
                              output_fields=self.fields)

    self.ExecOpCode(op)

    self.mcpu.assertLogIsEmpty()


if __name__ == "__main__":
  testutils.GanetiTestProgram()
