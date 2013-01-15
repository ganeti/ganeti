#
#

# Copyright (C) 2013 Google Inc.
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


"""QA tests for networks.

"""

import qa_config
import qa_utils

from qa_utils import AssertCommand


def GetNonexistentNetworks(count):
  """Gets network names which shouldn't exist on the cluster.

  @param count: Number of networks to get
  @rtype: integer

  """
  return qa_utils.GetNonexistentEntityNames(count, "networks", "network")


def TestNetworkAddRemove():
  """gnt-network add/remove"""
  (network1, network2) = GetNonexistentNetworks(2)

  # Add some networks of different sizes.
  # Note: Using RFC5737 addresses.
  AssertCommand(["gnt-network", "add", "--network", "192.0.2.0/30", network1])
  AssertCommand(["gnt-network", "add", "--network", "198.51.100.0/24",
                 network2])
  # Try to add a network with an existing name.
  AssertCommand(["gnt-network", "add", "--network", "203.0.133.0/24", network2],
                fail=True)

  AssertCommand(["gnt-network", "remove", network1])
  AssertCommand(["gnt-network", "remove", network2])


def TestNetworkConnect():
  """gnt-network connect/disconnect"""
  (group1, ) = qa_utils.GetNonexistentGroups(1)
  (network1, ) = GetNonexistentNetworks(1)

  default_mode = "bridged"
  default_link = "xen-br0"
  nicparams = qa_config.get("default-nicparams")
  if nicparams:
    mode = nicparams.get("mode", default_mode)
    link = nicparams.get("link", default_link)
  else:
    mode = default_mode
    link = default_link

  AssertCommand(["gnt-group", "add", group1])
  AssertCommand(["gnt-network", "add", "--network", "192.0.2.0/24", network1])

  AssertCommand(["gnt-network", "connect", network1, mode, link, group1])
  AssertCommand(["gnt-network", "disconnect", network1, group1])

  AssertCommand(["gnt-group", "remove", group1])
  AssertCommand(["gnt-network", "remove", network1])
