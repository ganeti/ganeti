#
#

# Copyright (C) 2013 Google Inc.
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


"""QA tests for networks.

"""

import qa_config
import qa_tags
import qa_utils

from ganeti import query

from qa_utils import AssertCommand


def TestNetworkList():
  """gnt-network list"""
  qa_utils.GenericQueryTest("gnt-network", list(query.NETWORK_FIELDS))


def TestNetworkListFields():
  """gnt-network list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-network", list(query.NETWORK_FIELDS))


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

  TestNetworkList()
  TestNetworkListFields()

  AssertCommand(["gnt-network", "remove", network1])
  AssertCommand(["gnt-network", "remove", network2])

  TestNetworkList()


def TestNetworkTags():
  """gnt-network tags"""
  (network, ) = GetNonexistentNetworks(1)
  AssertCommand(["gnt-network", "add", "--network", "192.0.2.0/30", network])
  qa_tags.TestNetworkTags(network)
  AssertCommand(["gnt-network", "remove", network])


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

  nicparams = "mode=%s,link=%s" % (mode, link)

  AssertCommand(["gnt-group", "add", group1])
  AssertCommand(["gnt-network", "add", "--network", "192.0.2.0/24", network1])

  AssertCommand(["gnt-network", "connect", "--nic-parameters", nicparams,
                network1, group1])

  TestNetworkList()

  AssertCommand(["gnt-network", "disconnect", network1, group1])

  AssertCommand(["gnt-group", "remove", group1])
  AssertCommand(["gnt-network", "remove", network1])
