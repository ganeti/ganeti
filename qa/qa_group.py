#
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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


"""QA tests for node groups.

"""

from ganeti import constants
from ganeti import query
from ganeti import utils

import qa_config
import qa_utils

from qa_utils import AssertCommand, AssertEqual, GetCommandOutput


def GetDefaultGroup():
  """Returns the default node group.

  """
  groups = qa_config.get("groups", {})
  return groups.get("group-with-nodes", constants.INITIAL_NODE_GROUP_NAME)


def TestGroupAddRemoveRename():
  """gnt-group add/remove/rename"""
  groups = qa_config.get("groups", {})

  existing_group_with_nodes = GetDefaultGroup()

  group1, group2, group3 = groups.get("inexistent-groups",
                                      ["group1", "group2", "group3"])[:3]

  AssertCommand(["gnt-group", "add", group1])
  AssertCommand(["gnt-group", "add", group2])
  AssertCommand(["gnt-group", "add", group2], fail=True)
  AssertCommand(["gnt-group", "add", existing_group_with_nodes], fail=True)

  AssertCommand(["gnt-group", "rename", group1, group2], fail=True)
  AssertCommand(["gnt-group", "rename", group1, group3])

  try:
    AssertCommand(["gnt-group", "rename", existing_group_with_nodes, group1])

    AssertCommand(["gnt-group", "remove", group2])
    AssertCommand(["gnt-group", "remove", group3])
    AssertCommand(["gnt-group", "remove", group1], fail=True)
  finally:
    # Try to ensure idempotency re groups that already existed.
    AssertCommand(["gnt-group", "rename", group1, existing_group_with_nodes])


def TestGroupAddWithOptions():
  """gnt-group add with options"""
  groups = qa_config.get("groups", {})
  group1 = groups.get("inexistent-groups", ["group1"])[0]

  AssertCommand(["gnt-group", "add", "--alloc-policy", "notvalid", group1],
                fail=True)

  AssertCommand(["gnt-group", "add", "--alloc-policy", "last_resort",
                 "--node-parameters", "oob_program=/bin/true", group1])

  AssertCommand(["gnt-group", "remove", group1])


def TestGroupModify():
  """gnt-group modify"""
  groups = qa_config.get("groups", {})
  group1 = groups.get("inexistent-groups", ["group1"])[0]

  AssertCommand(["gnt-group", "add", group1])

  std_defaults = constants.IPOLICY_DEFAULTS[constants.ISPECS_STD]
  min_v = std_defaults[constants.ISPEC_MEM_SIZE] * 10
  max_v = min_v * 10

  try:
    AssertCommand(["gnt-group", "modify", "--alloc-policy", "unallocable",
                   "--node-parameters", "oob_program=/bin/false", group1])
    AssertCommand(["gnt-group", "modify",
                   "--alloc-policy", "notvalid", group1], fail=True)
    AssertCommand(["gnt-group", "modify", "--specs-mem-size",
                   "min=%s,max=%s,std=0" % (min_v, max_v), group1], fail=True)
    AssertCommand(["gnt-group", "modify", "--specs-mem-size",
                   "min=%s,max=%s" % (min_v, max_v), group1])
    AssertCommand(["gnt-group", "modify",
                   "--node-parameters", "spindle_count=10", group1])
    if qa_config.TestEnabled("htools"):
      AssertCommand(["hbal", "-L", "-G", group1])
    AssertCommand(["gnt-group", "modify",
                   "--node-parameters", "spindle_count=default", group1])
  finally:
    AssertCommand(["gnt-group", "remove", group1])


def TestGroupList():
  """gnt-group list"""
  qa_utils.GenericQueryTest("gnt-group", query.GROUP_FIELDS.keys())


def TestGroupListFields():
  """gnt-group list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-group", query.GROUP_FIELDS.keys())


def TestAssignNodesIncludingSplit(orig_group, node1, node2):
  """gnt-group assign-nodes --force

  Expects node1 and node2 to be primary and secondary for a common instance.

  """
  assert node1 != node2
  groups = qa_config.get("groups", {})
  other_group = groups.get("inexistent-groups", ["group1"])[0]

  master_node = qa_config.GetMasterNode()["primary"]

  def AssertInGroup(group, nodes):
    real_output = GetCommandOutput(master_node,
                                   "gnt-node list --no-headers -o group " +
                                   utils.ShellQuoteArgs(nodes))
    AssertEqual(real_output.splitlines(), [group] * len(nodes))

  AssertInGroup(orig_group, [node1, node2])
  AssertCommand(["gnt-group", "add", other_group])

  try:
    AssertCommand(["gnt-group", "assign-nodes", other_group, node1, node2])
    AssertInGroup(other_group, [node1, node2])

    # This should fail because moving node1 to orig_group would leave their
    # common instance split between orig_group and other_group.
    AssertCommand(["gnt-group", "assign-nodes", orig_group, node1], fail=True)
    AssertInGroup(other_group, [node1, node2])

    AssertCommand(["gnt-group", "assign-nodes", "--force", orig_group, node1])
    AssertInGroup(orig_group, [node1])
    AssertInGroup(other_group, [node2])

    AssertCommand(["gnt-group", "assign-nodes", orig_group, node2])
    AssertInGroup(orig_group, [node1, node2])
  finally:
    AssertCommand(["gnt-group", "remove", other_group])
