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
  existing_group_with_nodes = GetDefaultGroup()

  (group1, group2, group3) = qa_utils.GetNonexistentGroups(3)

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
  (group1, ) = qa_utils.GetNonexistentGroups(1)

  AssertCommand(["gnt-group", "add", "--alloc-policy", "notvalid", group1],
                fail=True)

  AssertCommand(["gnt-group", "add", "--alloc-policy", "last_resort",
                 "--node-parameters", "oob_program=/bin/true", group1])

  AssertCommand(["gnt-group", "remove", group1])


def _GetGroupIPolicy(groupname):
  """Return the run-time values of the cluster-level instance policy.

  @type groupname: string
  @param groupname: node group name
  @rtype: tuple
  @return: (policy, specs), where:
      - policy is a dictionary of the policy values, instance specs excluded
      - specs is a dictionary containing only the specs, using the internal
        format (see L{constants.IPOLICY_DEFAULTS} for an example), but without
        the standard values

  """
  info = qa_utils.GetObjectInfo(["gnt-group", "info", groupname])
  assert len(info) == 1
  policy = info[0]["Instance policy"]

  (ret_policy, ret_specs) = qa_utils.ParseIPolicy(policy)

  # Sanity checks
  assert "minmax" in ret_specs
  assert len(ret_specs["minmax"]) > 0
  assert len(ret_policy) > 0
  return (ret_policy, ret_specs)


def _TestGroupSetISpecs(groupname, new_specs=None, diff_specs=None,
                        fail=False, old_values=None):
  """Change instance specs on a group.

  At most one of new_specs or diff_specs can be specified.

  @type groupname: string
  @param groupname: group name
  @type new_specs: dict
  @param new_specs: new complete specs, in the same format returned by
      L{_GetGroupIPolicy}
  @type diff_specs: dict
  @param diff_specs: partial specs, it can be an incomplete specifications, but
      if min/max specs are specified, their number must match the number of the
      existing specs
  @type fail: bool
  @param fail: if the change is expected to fail
  @type old_values: tuple
  @param old_values: (old_policy, old_specs), as returned by
      L{_GetGroupIPolicy}
  @return: same as L{_GetGroupIPolicy}

  """
  build_cmd = lambda opts: ["gnt-group", "modify"] + opts + [groupname]
  get_policy = lambda: _GetGroupIPolicy(groupname)
  return qa_utils.TestSetISpecs(
    new_specs=new_specs, diff_specs=diff_specs,
    get_policy_fn=get_policy, build_cmd_fn=build_cmd,
    fail=fail, old_values=old_values)


def _TestGroupModifyISpecs(groupname):
  # This test is built on the assumption that the default ipolicy holds for
  # the node group under test
  old_values = _GetGroupIPolicy(groupname)
  samevals = dict((p, 4) for p in constants.ISPECS_PARAMETERS)
  base_specs = {
    constants.ISPECS_MINMAX: [{
      constants.ISPECS_MIN: samevals,
      constants.ISPECS_MAX: samevals,
      }],
    }
  mod_values = _TestGroupSetISpecs(groupname, new_specs=base_specs,
                                   old_values=old_values)
  for par in constants.ISPECS_PARAMETERS:
    # First make sure that the test works with good values
    good_specs = {
      constants.ISPECS_MINMAX: [{
        constants.ISPECS_MIN: {par: 8},
        constants.ISPECS_MAX: {par: 8},
        }],
      }
    mod_values = _TestGroupSetISpecs(groupname, diff_specs=good_specs,
                                     old_values=mod_values)
    bad_specs = {
      constants.ISPECS_MINMAX: [{
        constants.ISPECS_MIN: {par: 8},
        constants.ISPECS_MAX: {par: 4},
        }],
      }
    _TestGroupSetISpecs(groupname, diff_specs=bad_specs, fail=True,
                        old_values=mod_values)
  AssertCommand(["gnt-group", "modify", "--ipolicy-bounds-specs", "default",
                 groupname])
  AssertEqual(_GetGroupIPolicy(groupname), old_values)

  # Get the ipolicy command (from the cluster config)
  mnode = qa_config.GetMasterNode()
  addcmd = GetCommandOutput(mnode.primary, utils.ShellQuoteArgs([
    "gnt-group", "show-ispecs-cmd", "--include-defaults", groupname,
    ]))
  modcmd = ["gnt-group", "modify"]
  opts = addcmd.split()
  assert opts[0:2] == ["gnt-group", "add"]
  for k in range(2, len(opts) - 1):
    if opts[k].startswith("--ipolicy-"):
      assert k + 2 <= len(opts)
      modcmd.extend(opts[k:k + 2])
  modcmd.append(groupname)
  # Apply the ipolicy to the group and verify the result
  AssertCommand(modcmd)
  new_addcmd = GetCommandOutput(mnode.primary, utils.ShellQuoteArgs([
    "gnt-group", "show-ispecs-cmd", groupname,
    ]))
  AssertEqual(addcmd, new_addcmd)


def _TestGroupModifyIPolicy(groupname):
  _TestGroupModifyISpecs(groupname)

  # We assume that the default ipolicy holds
  (old_policy, old_specs) = _GetGroupIPolicy(groupname)
  for (par, setval, iname, expval) in [
    ("vcpu-ratio", 1.5, None, 1.5),
    ("spindle-ratio", 1.5, None, 1.5),
    ("disk-templates", constants.DT_PLAIN,
     "allowed disk templates", constants.DT_PLAIN)
    ]:
    if not iname:
      iname = par
    build_cmdline = lambda val: ["gnt-group", "modify", "--ipolicy-" + par,
                                 str(val), groupname]

    AssertCommand(build_cmdline(setval))
    (new_policy, new_specs) = _GetGroupIPolicy(groupname)
    AssertEqual(new_specs, old_specs)
    for (p, val) in new_policy.items():
      if p == iname:
        AssertEqual(val, expval)
      else:
        AssertEqual(val, old_policy[p])

    AssertCommand(build_cmdline("default"))
    (new_policy, new_specs) = _GetGroupIPolicy(groupname)
    AssertEqual(new_specs, old_specs)
    AssertEqual(new_policy, old_policy)


def TestGroupModify():
  """gnt-group modify"""
  # This tests assumes LVM to be enabled, thus it should skip if
  # this is not the case
  if not qa_config.IsStorageTypeSupported(constants.ST_LVM_VG):
    return
  (group1, ) = qa_utils.GetNonexistentGroups(1)

  AssertCommand(["gnt-group", "add", group1])

  try:
    _TestGroupModifyIPolicy(group1)
    AssertCommand(["gnt-group", "modify", "--alloc-policy", "unallocable",
                   "--node-parameters", "oob_program=/bin/false", group1])
    AssertCommand(["gnt-group", "modify",
                   "--alloc-policy", "notvalid", group1], fail=True)
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

  (other_group, ) = qa_utils.GetNonexistentGroups(1)

  master_node = qa_config.GetMasterNode().primary

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
