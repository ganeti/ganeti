#
#

# Copyright (C) 2006, 2007, 2010, 2013 Google Inc.
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
  op = opcodes.OpOsDiagnose(output_fields=["name", "variants"],
                            names=[])
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
                                           "blacklisted", "hidden", "os_hvp",
                                           "osparams", "trusted"],
                            names=[])
  result = SubmitOpCode(op, opts=opts)

  if result is None:
    ToStderr("Can't get the OS list")
    return 1

  do_filter = bool(args)

  total_os_hvp = {}
  total_osparams = {}

  for (name, valid, variants, parameters, api_versions, blk, hid, os_hvp,
       osparams, trusted) in result:
    total_os_hvp.update(os_hvp)
    total_osparams.update(osparams)
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
    ToStdout("  - trusted: %s", trusted)
    ToStdout("")

  if args:
    all_names = set(total_os_hvp) | set(total_osparams)
    for name in args:
      if not name in all_names:
        ToStdout("%s: ", name)
      else:
        info = [
          (name, [
            ("OS-specific hypervisor parameters", total_os_hvp.get(name, {})),
            ("OS parameters", total_osparams.get(name, {})),
            ]),
          ]
        PrintGenericInfo(info)
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

  if result is None:
    ToStderr("Can't get the OS list")
    return 1

  has_bad = False

  for os_name, _, os_variants, node_data, hid, blk in result:
    nodes_valid = {}
    nodes_bad = {}
    nodes_hidden = {}
    for node_name, node_info in node_data.items():
      nodes_hidden[node_name] = []
      if node_info: # at least one entry in the per-node list
        (fo_path, fo_status, fo_msg, fo_variants,
         fo_params, fo_api, fo_trusted) = node_info.pop(0)
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
        if fo_trusted:
          fo_msg += " [trusted]"
        else:
          fo_msg += " [untrusted]"
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

    st_msg = "OS: %s [global status: %s]" % (os_name, status)
    if hid:
      st_msg += " [hidden]"
    if blk:
      st_msg += " [blacklisted]"
    ToStdout(st_msg)
    if os_variants:
      ToStdout("  Variants: [%s]" % utils.CommaJoin(os_variants))

    for msg_map in (nodes_valid, nodes_bad):
      map_k = utils.NiceSort(msg_map)
      for node_name in map_k:
        ToStdout("  Node: %s, status: %s", node_name, msg_map[node_name])
        for msg in nodes_hidden[node_name]:
          ToStdout(msg)
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
  # We have to disable pylint for this assignment because of a Pylint bug:
  # Even though there is no `os` in scope, it claims
  #   Redefining name 'os' from outer scope
  # It is supposed to come from `from ganeti.cli import *`, but that doesn't
  # export `os` since it has `__all__` set.
  os = args[0]  # pylint: disable=W0621

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
