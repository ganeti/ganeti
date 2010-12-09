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

"""Node group related commands"""

# pylint: disable-msg=W0401,W0614
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)

from ganeti.cli import *
from ganeti import compat
from ganeti import opcodes
from ganeti import utils


#: default list of fields for L{ListGroups}
_LIST_DEF_FIELDS = ["name", "node_cnt", "pinst_cnt"]


#: headers (and full field list) for L{ListGroups}
_LIST_HEADERS = {
  "name": "Group", "uuid": "UUID",
  "node_cnt": "Nodes", "node_list": "NodeList",
  "pinst_cnt": "Instances", "pinst_list": "InstanceList",
  "ctime": "CTime", "mtime": "MTime", "serial_no": "SerialNo",
}


def AddGroup(opts, args):
  """Add a node group to the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 1 with the name of the group to create
  @rtype: int
  @return: the desired exit code

  """
  (group_name,) = args
  op = opcodes.OpAddGroup(group_name=group_name, ndparams=opts.ndparams)
  SubmitOpCode(op, opts=opts)


def ListGroups(opts, args):
  """List node groups and their properties.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: groups to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  desired_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)

  output = GetClient().QueryGroups(args, desired_fields, opts.do_locking)

  if opts.no_headers:
    headers = None
  else:
    headers = _LIST_HEADERS

  int_type_fields = frozenset(["node_cnt", "pinst_cnt", "serial_no"])
  list_type_fields = frozenset(["node_list", "pinst_list"])
  date_type_fields = frozenset(["mtime", "ctime"])

  for row in output:
    for idx, field in enumerate(desired_fields):
      val = row[idx]

      if field in list_type_fields:
        val = ",".join(val)
      elif opts.roman_integers and field in int_type_fields:
        val = compat.TryToRoman(val)
      elif field in date_type_fields:
        val = utils.FormatTime(val)
      elif val is None:
        val = "?"

      row[idx] = str(val)

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=desired_fields, data=output)

  for line in data:
    ToStdout(line)

  return 0


def SetGroupParams(opts, args):
  """Modifies a node group's parameters.

  @param opts: the command line options seletect by the user
  @type args: list
  @param args: should contain only one element, the node group name

  @rtype: int
  @return: the desired exit code

  """
  all_changes = {
    "ndparams": opts.ndparams,
  }

  if all_changes.values().count(None) == len(all_changes):
    ToStderr("Please give at least one of the parameters.")
    return 1

  op = opcodes.OpSetGroupParams(group_name=args[0], **all_changes)
  result = SubmitOrSend(op, opts)

  if result:
    ToStdout("Modified node group %s", args[0])
    for param, data in result:
      ToStdout(" - %-5s -> %s", param, data)

  return 0


def RemoveGroup(opts, args):
  """Remove a node group from the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 1 with the name of the group to remove
  @rtype: int
  @return: the desired exit code

  """
  (group_name,) = args
  op = opcodes.OpRemoveGroup(group_name=group_name)
  SubmitOpCode(op, opts=opts)


def RenameGroup(opts, args):
  """Rename a node group.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 2, [old_name, new_name]
  @rtype: int
  @return: the desired exit code

  """
  old_name, new_name = args
  op = opcodes.OpRenameGroup(old_name=old_name, new_name=new_name)
  SubmitOpCode(op, opts=opts)


commands = {
  "add": (
    AddGroup, ARGS_ONE_GROUP, [DRY_RUN_OPT, NODE_PARAMS_OPT],
    "<group_name>", "Add a new node group to the cluster"),
  "list": (
    ListGroups, ARGS_MANY_GROUPS,
    [NOHDR_OPT, SEP_OPT, FIELDS_OPT, SYNC_OPT, ROMAN_OPT],
    "[<group_name>...]",
    "Lists the node groups in the cluster. The available fields are (see"
    " the man page for details): %s. The default list is (in order): %s." %
    (utils.CommaJoin(_LIST_HEADERS), utils.CommaJoin(_LIST_DEF_FIELDS))),
  "modify": (
    SetGroupParams, ARGS_ONE_GROUP,
    [DRY_RUN_OPT, SUBMIT_OPT, NODE_PARAMS_OPT],
    "<group_name>", "Alters the parameters of a node group"),
  "remove": (
    RemoveGroup, ARGS_ONE_GROUP, [DRY_RUN_OPT],
    "[--dry-run] <group_name>",
    "Remove an (empty) node group from the cluster"),
  "rename": (
    RenameGroup, [ArgGroup(min=2, max=2)], [DRY_RUN_OPT],
    "[--dry-run] <old_name> <new_name>", "Rename a node group"),
}


def Main():
  return GenericMain(commands)
