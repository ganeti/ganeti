#
#

# Copyright (C) 2006, 2007, 2010, 2013 Google Inc.
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

"""OS scripts related commands"""

# pylint: disable=W0401,W0613,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0613: Unused argument, since all functions follow the same API
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-os

from ganeti.cli import *
from ganeti import constants
from ganeti import opcodes
from ganeti import utils


def ListOS(opts, args):
  """List the valid OSes in the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpOsDiagnose(output_fields=["name", "variants"], names=[])
  result = SubmitOpCode(op, opts=opts)

  if not opts.no_headers:
    headers = {"name": "Name"}
  else:
    headers = None

  os_names = []
  for (name, variants) in result:
    os_names.extend([[n] for n in CalculateOSNames(name, variants)])

  data = GenerateTable(separator=None, headers=headers, fields=["name"],
                       data=os_names, units=None)

  for line in data:
    ToStdout(line)

  return 0


def ShowOSInfo(opts, args):
  """List detailed information about OSes in the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpOsDiagnose(output_fields=["name", "valid", "variants",
                                           "parameters", "api_versions",
                                           "blacklisted", "hidden"],
                            names=[])
  result = SubmitOpCode(op, opts=opts)

  if not result:
    ToStderr("Can't get the OS list")
    return 1

  do_filter = bool(args)

  for (name, valid, variants, parameters, api_versions, blk, hid) in result:
    if do_filter:
      if name not in args:
        continue
      else:
        args.remove(name)
    ToStdout("%s:", name)
    ToStdout("  - valid: %s", valid)
    ToStdout("  - hidden: %s", hid)
    ToStdout("  - blacklisted: %s", blk)
    if valid:
      ToStdout("  - API versions:")
      for version in sorted(api_versions):
        ToStdout("    - %s", version)
      ToStdout("  - variants:")
      for vname in variants:
        ToStdout("    - %s", vname)
      ToStdout("  - parameters:")
      for pname, pdesc in parameters:
        ToStdout("    - %s: %s", pname, pdesc)
    ToStdout("")

  if args:
    for name in args:
      ToStdout("%s: ", name)
      ToStdout("")

  return 0


def _OsStatus(status, diagnose):
  """Beautifier function for OS status.

  @type status: boolean
  @param status: is the OS valid
  @type diagnose: string
  @param diagnose: the error message for invalid OSes
  @rtype: string
  @return: a formatted status

  """
  if status:
    return "valid"
  else:
    return "invalid - %s" % diagnose


def DiagnoseOS(opts, args):
  """Analyse all OSes on this cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  op = opcodes.OpOsDiagnose(output_fields=["name", "valid", "variants",
                                           "node_status", "hidden",
                                           "blacklisted"], names=[])
  result = SubmitOpCode(op, opts=opts)

  if not result:
    ToStderr("Can't get the OS list")
    return 1

  has_bad = False

  for os_name, _, os_variants, node_data, hid, blk in result:
    nodes_valid = {}
    nodes_bad = {}
    nodes_hidden = {}
    for node_name, node_info in node_data.iteritems():
      nodes_hidden[node_name] = []
      if node_info: # at least one entry in the per-node list
        (fo_path, fo_status, fo_msg, fo_variants,
         fo_params, fo_api) = node_info.pop(0)
        fo_msg = "%s (path: %s)" % (_OsStatus(fo_status, fo_msg), fo_path)
        if fo_api:
          max_os_api = max(fo_api)
          fo_msg += " [API versions: %s]" % utils.CommaJoin(fo_api)
        else:
          max_os_api = 0
          fo_msg += " [no API versions declared]"

        if max_os_api >= constants.OS_API_V15:
          if fo_variants:
            fo_msg += " [variants: %s]" % utils.CommaJoin(fo_variants)
          else:
            fo_msg += " [no variants]"
        if max_os_api >= constants.OS_API_V20:
          if fo_params:
            fo_msg += (" [parameters: %s]" %
                       utils.CommaJoin([v[0] for v in fo_params]))
          else:
            fo_msg += " [no parameters]"
        if fo_status:
          nodes_valid[node_name] = fo_msg
        else:
          nodes_bad[node_name] = fo_msg
        for hpath, hstatus, hmsg, _, _, _ in node_info:
          nodes_hidden[node_name].append("    [hidden] path: %s, status: %s" %
                                         (hpath, _OsStatus(hstatus, hmsg)))
      else:
        nodes_bad[node_name] = "OS not found"

    # TODO: Shouldn't the global status be calculated by the LU?
    if nodes_valid and not nodes_bad:
      status = "valid"
    elif not nodes_valid and nodes_bad:
      status = "invalid"
      has_bad = True
    else:
      status = "partial valid"
      has_bad = True

    def _OutputPerNodeOSStatus(msg_map):
      map_k = utils.NiceSort(msg_map.keys())
      for node_name in map_k:
        ToStdout("  Node: %s, status: %s", node_name, msg_map[node_name])
        for msg in nodes_hidden[node_name]:
          ToStdout(msg)

    st_msg = "OS: %s [global status: %s]" % (os_name, status)
    if hid:
      st_msg += " [hidden]"
    if blk:
      st_msg += " [blacklisted]"
    ToStdout(st_msg)
    if os_variants:
      ToStdout("  Variants: [%s]" % utils.CommaJoin(os_variants))
    _OutputPerNodeOSStatus(nodes_valid)
    _OutputPerNodeOSStatus(nodes_bad)
    ToStdout("")

  return int(has_bad)


def ModifyOS(opts, args):
  """Modify OS parameters for one OS.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be a list with one entry
  @rtype: int
  @return: the desired exit code

  """
  os = args[0]

  if opts.hvparams:
    os_hvp = {os: dict(opts.hvparams)}
  else:
    os_hvp = None

  if opts.osparams:
    osp = {os: opts.osparams}
  else:
    osp = None

  if opts.osparams_private:
    osp_private = {os: opts.osparams_private}
  else:
    osp_private = None

  if opts.hidden is not None:
    if opts.hidden:
      ohid = [(constants.DDM_ADD, os)]
    else:
      ohid = [(constants.DDM_REMOVE, os)]
  else:
    ohid = None

  if opts.blacklisted is not None:
    if opts.blacklisted:
      oblk = [(constants.DDM_ADD, os)]
    else:
      oblk = [(constants.DDM_REMOVE, os)]
  else:
    oblk = None

  if not (os_hvp or osp or osp_private or ohid or oblk):
    ToStderr("At least one of OS parameters or hypervisor parameters"
             " must be passed")
    return 1

  op = opcodes.OpClusterSetParams(os_hvp=os_hvp,
                                  osparams=osp,
                                  osparams_private_cluster=osp_private,
                                  hidden_os=ohid,
                                  blacklisted_os=oblk)
  SubmitOrSend(op, opts)

  return 0


commands = {
  "list": (
    ListOS, ARGS_NONE, [NOHDR_OPT, PRIORITY_OPT],
    "", "Lists all valid operating systems on the cluster"),
  "diagnose": (
    DiagnoseOS, ARGS_NONE, [PRIORITY_OPT],
    "", "Diagnose all operating systems"),
  "info": (
    ShowOSInfo, [ArgOs()], [PRIORITY_OPT],
    "", "Show detailed information about "
    "operating systems"),
  "modify": (
    ModifyOS, ARGS_ONE_OS,
    [HVLIST_OPT, OSPARAMS_OPT, OSPARAMS_PRIVATE_OPT,
     DRY_RUN_OPT, PRIORITY_OPT, HID_OS_OPT, BLK_OS_OPT] + SUBMIT_OPTS,
    "", "Modify the OS parameters"),
  }

#: dictionary with aliases for commands
aliases = {
  "show": "info",
  }


def Main():
  return GenericMain(commands, aliases=aliases)
