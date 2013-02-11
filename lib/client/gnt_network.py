#
#

# Copyright (C) 2011, 2012 Google Inc.
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

# pylint: disable=W0401,W0614
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)

import textwrap
import itertools

from ganeti.cli import *
from ganeti import constants
from ganeti import opcodes
from ganeti import utils
from ganeti import errors


#: default list of fields for L{ListNetworks}
_LIST_DEF_FIELDS = ["name", "network", "gateway",
                    "mac_prefix", "group_list", "tags"]


def _HandleReservedIPs(ips):
  if ips is None:
    return None
  elif not ips:
    return []
  else:
    return utils.UnescapeAndSplit(ips, sep=",")


def AddNetwork(opts, args):
  """Add a network to the cluster.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: a list of length 1 with the network name to create
  @rtype: int
  @return: the desired exit code

  """
  (network_name, ) = args

  if opts.network is None:
    raise errors.OpPrereqError("The --network option must be given",
                               errors.ECODE_INVAL)

  if opts.tags is not None:
    tags = opts.tags.split(",")
  else:
    tags = []

  reserved_ips = _HandleReservedIPs(opts.add_reserved_ips)

  op = opcodes.OpNetworkAdd(network_name=network_name,
                            gateway=opts.gateway,
                            network=opts.network,
                            gateway6=opts.gateway6,
                            network6=opts.network6,
                            mac_prefix=opts.mac_prefix,
                            add_reserved_ips=reserved_ips,
                            conflicts_check=opts.conflicts_check,
                            tags=tags)
  SubmitOrSend(op, opts)


def _GetDefaultGroups(cl, groups):
  """Gets list of groups to operate on.

  If C{groups} doesn't contain groups, a list of all groups in the cluster is
  returned.

  @type cl: L{luxi.Client}
  @type groups: list
  @rtype: list

  """
  if groups:
    return groups

  return list(itertools.chain(*cl.QueryGroups([], ["uuid"], False)))


def ConnectNetwork(opts, args):
  """Map a network to a node group.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: Network, mode, physlink and node groups
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  (network, mode, link) = args[:3]
  groups = _GetDefaultGroups(cl, args[3:])

  # TODO: Change logic to support "--submit"
  for group in groups:
    op = opcodes.OpNetworkConnect(group_name=group,
                                  network_name=network,
                                  network_mode=mode,
                                  network_link=link,
                                  conflicts_check=opts.conflicts_check)
    SubmitOpCode(op, opts=opts, cl=cl)


def DisconnectNetwork(opts, args):
  """Unmap a network from a node group.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: Network and node groups
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  (network, ) = args[:1]
  groups = _GetDefaultGroups(cl, args[1:])

  # TODO: Change logic to support "--submit"
  for group in groups:
    op = opcodes.OpNetworkDisconnect(group_name=group,
                                     network_name=network,
                                     conflicts_check=opts.conflicts_check)
    SubmitOpCode(op, opts=opts, cl=cl)


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
    "group_list":
      (lambda data: utils.CommaJoin("%s (%s, %s)" % (name, mode, link)
                                    for (name, mode, link) in data),
       False),
    "inst_list": (",".join, False),
    "tags": (",".join, False),
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


def ShowNetworkConfig(_, args):
  """Show network information.

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
                                    "mac_prefix",
                                    "free_count", "reserved_count",
                                    "map", "group_list", "inst_list",
                                    "external_reservations",
                                    "serial_no", "uuid"],
                            names=args, use_locking=False)

  for (name, network, gateway, network6, gateway6,
       mac_prefix, free_count, reserved_count,
       mapping, group_list, instances, ext_res, serial, uuid) in result:
    size = free_count + reserved_count
    ToStdout("Network name: %s", name)
    ToStdout("UUID: %s", uuid)
    ToStdout("Serial number: %d", serial)
    ToStdout("  Subnet: %s", network)
    ToStdout("  Gateway: %s", gateway)
    ToStdout("  IPv6 Subnet: %s", network6)
    ToStdout("  IPv6 Gateway: %s", gateway6)
    ToStdout("  Mac Prefix: %s", mac_prefix)
    ToStdout("  Size: %d", size)
    ToStdout("  Free: %d (%.2f%%)", free_count,
             100 * float(free_count) / float(size))
    ToStdout("  Usage map:")
    idx = 0
    for line in textwrap.wrap(mapping, width=64):
      ToStdout("     %s %s %d", str(idx).rjust(3), line.ljust(64), idx + 63)
      idx += 64
    ToStdout("         (X) used    (.) free")

    if ext_res:
      ToStdout("  externally reserved IPs:")
      for line in textwrap.wrap(ext_res, width=64):
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

        l = lambda value: ", ".join(str(idx) + ":" + str(ip)
                                    for idx, (ip, net) in enumerate(value)
                                      if net == name)

        ToStdout("    %s : %s", inst, l(zip(ips, networks)))
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
    "gateway6": opts.gateway6,
    "network6": opts.network6,
  }

  if all_changes.values().count(None) == len(all_changes):
    ToStderr("Please give at least one of the parameters.")
    return 1

  # pylint: disable=W0142
  op = opcodes.OpNetworkSetParams(network_name=args[0], **all_changes)

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
  SubmitOrSend(op, opts)


commands = {
  "add": (
    AddNetwork, ARGS_ONE_NETWORK,
    [DRY_RUN_OPT, NETWORK_OPT, GATEWAY_OPT, ADD_RESERVED_IPS_OPT,
     MAC_PREFIX_OPT, NETWORK6_OPT, GATEWAY6_OPT,
     NOCONFLICTSCHECK_OPT, TAG_ADD_OPT, PRIORITY_OPT, SUBMIT_OPT],
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
     GATEWAY_OPT, MAC_PREFIX_OPT, NETWORK6_OPT, GATEWAY6_OPT,
     PRIORITY_OPT],
    "<network_name>", "Alters the parameters of a network"),
  "connect": (
    ConnectNetwork,
    [ArgNetwork(min=1, max=1),
     ArgChoice(min=1, max=1, choices=constants.NIC_VALID_MODES),
     ArgUnknown(min=1, max=1),
     ArgGroup()],
    [NOCONFLICTSCHECK_OPT, PRIORITY_OPT],
    "<network_name> <mode> <link> [<node_group>...]",
    "Map a given network to the specified node group"
    " with given mode and link (netparams)"),
  "disconnect": (
    DisconnectNetwork,
    [ArgNetwork(min=1, max=1), ArgGroup()],
    [NOCONFLICTSCHECK_OPT, PRIORITY_OPT],
    "<network_name> [<node_group>...]",
    "Unmap a given network from a specified node group"),
  "remove": (
    RemoveNetwork, ARGS_ONE_NETWORK,
    [FORCE_OPT, DRY_RUN_OPT, SUBMIT_OPT, PRIORITY_OPT],
    "[--dry-run] <network_id>",
    "Remove an (empty) network from the cluster"),
  "list-tags": (
    ListTags, ARGS_ONE_NETWORK, [],
    "<network_name>", "List the tags of the given network"),
  "add-tags": (
    AddTags, [ArgNetwork(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT, SUBMIT_OPT],
    "<network_name> tag...", "Add tags to the given network"),
  "remove-tags": (
    RemoveTags, [ArgNetwork(min=1, max=1), ArgUnknown()],
    [TAG_SRC_OPT, PRIORITY_OPT, SUBMIT_OPT],
    "<network_name> tag...", "Remove tags from given network"),
}


def Main():
  return GenericMain(commands, override={"tag_type": constants.TAG_NETWORK})
