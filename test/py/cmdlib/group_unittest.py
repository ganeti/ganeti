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

from testsupport import *

import testutils


class TestLUGroupAssignNodes(CmdlibTestCase):
  def __init__(self, methodName='runTest'):
    super(TestLUGroupAssignNodes, self).__init__(methodName)

    self.op = opcodes.OpGroupAssignNodes(group_name="default",
                                         nodes=[])

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
      [("n1b", g3.uuid)], self.cfg.GetAllNodesInfo(), self.cfg.GetAllInstancesInfo())

    self.assertEqual(set(["inst1a", "inst1b"]), set(new))
    self.assertEqual(set(["inst3c"]), set(prev))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
