#
#

# Copyright (C) 2011 Google Inc.
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

"""IP pool related commands"""

# pylint: disable-msg=W0401,W0614
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)

from ganeti.cli import *
from ganeti import constants
from ganeti import opcodes
from ganeti import utils
from textwrap import wrap


#: default list of fields for L{ListNetworks}
_LIST_DEF_FIELDS = ["name", "network", "gateway",
                    "network_type", "mac_prefix", "group_list"]


def _HandleReservedIPs(ips):
  if ips is not None:
    if ips == "":
      return []
    else:
      return utils.UnescapeAndSplit(ips, sep=",")
  return None

def AddNetwork(opts, args):
  """Add a network to the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 1 with the network name to create
  @rtype: int
  @return: the desired exit code

  """
  (network_name, ) = args

  op = opcodes.OpNetworkAdd(network_name=network_name,
                            gateway=opts.gateway,
                            network=opts.network,
                            gateway6=opts.gateway6,
                            network6=opts.network6,
                            mac_prefix=opts.mac_prefix,
                            network_type=opts.network_type,
                            add_reserved_ips=_HandleReservedIPs(opts.add_reserved_ips))
  SubmitOpCode(op, opts=opts)


def MapNetwork(opts, args):
  """Map a network to a node group.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 3 with network, nodegroup, mode, physlink
  @rtype: int
  @return: the desired exit code

  """
  network = args[0]
  groups = args[1]
  mode = args[2]
  link = args[3]

  #TODO: allow comma separated group names
  if groups == 'all':
    cl = GetClient()
    (groups, ) = cl.QueryGroups([], ['name'], False)
  else:
    groups = [groups]

  for group in groups:
    op = opcodes.OpNetworkConnect(group_name=group,
                                  network_name=network,
                                  network_mode=mode,
                                  network_link=link,
                                  conflicts_check=opts.conflicts_check)
    SubmitOpCode(op, opts=opts)


def UnmapNetwork(opts, args):
  """Unmap a network from a node group.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 3 with network, nodegorup
  @rtype: int
  @return: the desired exit code

  """
  network = args[0]
  groups = args[1]

  #TODO: allow comma separated group names
  if groups == 'all':
    cl = GetClient()
    (groups, ) = cl.QueryGroups([], ['name'], False)
  else:
    groups = [groups]

  for group in groups:
    op = opcodes.OpNetworkDisconnect(group_name=group,
                                     network_name=network,
                                     conflicts_check=opts.conflicts_check)
    SubmitOpCode(op, opts=opts)


def ListNetworks(opts, args):
  """List Ip pools and their properties.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: networks to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  desired_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)
  fmtoverride = {
    "group_list": (",".join, False),
    "inst_list": (",".join, False),
  }

  return GenericList(constants.QR_NETWORK, desired_fields, args, None,
                     opts.separator, not opts.no_headers,
                     verbose=opts.verbose, format_override=fmtoverride)


def ListNetworkFields(opts, args):
  """List network fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  return GenericListFields(constants.QR_NETWORK, args, opts.separator,
                           not opts.no_headers)


def ShowNetworkConfig(opts, args):
  """Show network information.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should either be an empty list, in which case
      we show information about all nodes, or should contain
      a list of networks (names or UUIDs) to be queried for information
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()
  result = cl.QueryNetworks(fields=["name", "network", "gateway",
                                    "network6", "gateway6",
                                    "mac_prefix", "network_type",
                                    "free_count", "reserved_count",
                                    "map", "group_list", "inst_list",
                                    "external_reservations"],
                            names=args, use_locking=False)

  for (name, network, gateway, network6, gateway6,
       mac_prefix, network_type, free_count, reserved_count,
       map, group_list, instances, ext_res) in result:
    size = free_count + reserved_count
    ToStdout("Network name: %s", name)
    ToStdout("  subnet: %s", network)
    ToStdout("  gateway: %s", gateway)
    ToStdout("  subnet6: %s", network6)
    ToStdout("  gateway6: %s", gateway6)
    ToStdout("  mac prefix: %s", mac_prefix)
    ToStdout("  type: %s", network_type)
    ToStdout("  size: %d", size)
    ToStdout("  free: %d (%.2f%%)", free_count,
             100 * float(free_count)/float(size))
    ToStdout("  usage map:")
    idx = 0
    for line in wrap(map, width=64):
      ToStdout("     %s %s %d", str(idx).rjust(3), line.ljust(64), idx + 63)
      idx += 64
    ToStdout("         (X) used    (.) free")

    if ext_res:
      ToStdout("  externally reserved IPs:")
      for line in wrap(ext_res, width=64):
        ToStdout("    %s" % line)

    if group_list:
      ToStdout("  connected to node groups:")
      for group in group_list:
        ToStdout("    %s", group)
    else:
      ToStdout("  not connected to any node group")

    if instances:
      ToStdout("  used by %d instances:", len(instances))
      for inst in instances:
        ((ips, networks), ) = cl.QueryInstances([inst],
                                                ["nic.ips", "nic.networks"],
                                                use_locking=False)

        l = lambda value: ", ".join(`idx`+":"+str(ip)
                                    for idx, (ip, net) in enumerate(value)
                                      if net == name)

        ToStdout("    %s : %s", inst, l(zip(ips,networks)))
    else:
      ToStdout("  not used by any instances")


def SetNetworkParams(opts, args):
  """Modifies an IP address pool's parameters.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the node group name

  @rtype: int
  @return: the desired exit code

  """

  # TODO: add "network": opts.network,
  all_changes = {
    "gateway": opts.gateway,
    "add_reserved_ips": _HandleReservedIPs(opts.add_reserved_ips),
    "remove_reserved_ips": _HandleReservedIPs(opts.remove_reserved_ips),
    "mac_prefix": opts.mac_prefix,
    "network_type": opts.network_type,
    "gateway6": opts.gateway6,
    "network6": opts.network6,
  }

  if all_changes.values().count(None) == len(all_changes):
    ToStderr("Please give at least one of the parameters.")
    return 1

  op = opcodes.OpNetworkSetParams(network_name=args[0],
                                  # pylint: disable-msg=W0142
                                  **all_changes)

  # TODO: add feedback to user, e.g. list the modifications
  SubmitOrSend(op, opts)


def RemoveNetwork(opts, args):
  """Remove an IP address pool from the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 1 with the id of the IP address pool to remove
  @rtype: int
  @return: the desired exit code

  """
  (network_name,) = args
  op = opcodes.OpNetworkRemove(network_name=network_name, force=opts.force)
  SubmitOpCode(op, opts=opts)


commands = {
  "add": (
    AddNetwork, ARGS_ONE_NETWORK,
    [DRY_RUN_OPT, NETWORK_OPT, GATEWAY_OPT, ADD_RESERVED_IPS_OPT,
     MAC_PREFIX_OPT, NETWORK_TYPE_OPT, NETWORK6_OPT, GATEWAY6_OPT],
    "<network_name>", "Add a new IP network to the cluster"),
  "list": (
    ListNetworks, ARGS_MANY_NETWORKS,
    [NOHDR_OPT, SEP_OPT, FIELDS_OPT, VERBOSE_OPT],
    "[<network_id>...]",
    "Lists the IP networks in the cluster. The available fields can be shown"
    " using the \"list-fields\" command (see the man page for details)."
    " The default list is (in order): %s." % utils.CommaJoin(_LIST_DEF_FIELDS)),
  "list-fields": (
    ListNetworkFields, [ArgUnknown()], [NOHDR_OPT, SEP_OPT], "[fields...]",
    "Lists all available fields for networks"),
  "info": (
    ShowNetworkConfig, ARGS_MANY_NETWORKS, [],
    "[<network_name>...]", "Show information about the network(s)"),
  "modify": (
    SetNetworkParams, ARGS_ONE_NETWORK,
    [DRY_RUN_OPT, SUBMIT_OPT, ADD_RESERVED_IPS_OPT, REMOVE_RESERVED_IPS_OPT,
     GATEWAY_OPT, MAC_PREFIX_OPT, NETWORK_TYPE_OPT, NETWORK6_OPT, GATEWAY6_OPT],
    "<network_name>", "Alters the parameters of a network"),
  "connect": (
    MapNetwork,
    [ArgNetwork(min=1, max=1), ArgGroup(min=1, max=1),
     ArgUnknown(min=1, max=1), ArgUnknown(min=1, max=1)],
    [NOCONFLICTSCHECK_OPT],
    "<network_name> <node_group> <mode> <link>",
    "Map a given network to the specified node group"
    " with given mode and link (netparams)"),
  "disconnect": (
    UnmapNetwork,
    [ArgNetwork(min=1, max=1), ArgGroup(min=1, max=1)],
    [NOCONFLICTSCHECK_OPT],
    "<network_name> <node_group>",
    "Unmap a given network from a specified node group"),
  "remove": (
    RemoveNetwork, ARGS_ONE_NETWORK, [FORCE_OPT, DRY_RUN_OPT],
    "[--dry-run] <network_id>",
    "Remove an (empty) network from the cluster"),
}


def Main():
  return GenericMain(commands)
