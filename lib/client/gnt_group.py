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


#: default list of fields for L{ListGroups}
_LIST_DEF_FIELDS = ["name", "node_cnt", "pinst_cnt"]


#: headers (and full field list) for L{ListGroups}
_LIST_HEADERS = {
  "name": "Group", "uuid": "UUID",
  "node_cnt": "Nodes", "node_list": "NodeList",
  "pinst_cnt": "Instances", "pinst_list": "InstanceList",
}


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

  int_type_fields = frozenset(["node_cnt", "pinst_cnt"])
  list_type_fields = frozenset(["node_list", "pinst_list"])

  for row in output:
    for idx, field in enumerate(desired_fields):
      val = row[idx]

      if field in list_type_fields:
        val = ",".join(val)
      elif opts.roman_integers and field in int_type_fields:
        val = compat.TryToRoman(val)
      elif val is None:
        val = "?"

      row[idx] = str(val)

  data = GenerateTable(separator=opts.separator, headers=headers,
                       fields=desired_fields, data=output)

  for line in data:
    ToStdout(line)

  return 0


commands = {
  "list": (
    ListGroups, ARGS_MANY_GROUPS,
    [NOHDR_OPT, SEP_OPT, FIELDS_OPT, SYNC_OPT, ROMAN_OPT],
    "[<group_name>...]", "Lists the node groups in the cluster."),
}


def Main():
  return GenericMain(commands)
