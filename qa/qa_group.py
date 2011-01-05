#
#

# Copyright (C) 2010 Google Inc.
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


from ganeti import constants
from ganeti import query

import qa_config
import qa_utils

from qa_utils import AssertCommand


def TestGroupAddRemoveRename():
  """gnt-group add/remove/rename"""
  groups = qa_config.get("groups", {})

  existing_group_with_nodes = groups.get("group-with-nodes",
                                         constants.INITIAL_NODE_GROUP_NAME)
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

  try:
    AssertCommand(["gnt-group", "modify", "--alloc-policy", "unallocable",
                   "--node-parameters", "oob_program=/bin/false", group1])
    AssertCommand(["gnt-group", "modify",
                   "--alloc-policy", "notvalid", group1], fail=True)
  finally:
    AssertCommand(["gnt-group", "remove", group1])


def TestGroupList():
  """gnt-group list"""
  qa_utils.GenericQueryTest("gnt-group", query.GROUP_FIELDS.keys())


def TestGroupListFields():
  """gnt-group list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-group", query.GROUP_FIELDS.keys())
