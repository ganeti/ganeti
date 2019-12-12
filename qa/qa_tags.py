#
#

# Copyright (C) 2007 Google Inc.
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


"""Tags related QA tests.

"""

from ganeti import constants

from qa import qa_rapi

from qa_utils import AssertCommand


_TEMP_TAG_NAMES = ["TEMP-Ganeti-QA-Tag%d" % i for i in range(3)]
_TEMP_TAG_RE = r'^TEMP-Ganeti-QA-Tag\d+$'

_KIND_TO_COMMAND = {
  constants.TAG_CLUSTER: "gnt-cluster",
  constants.TAG_NODE: "gnt-node",
  constants.TAG_INSTANCE: "gnt-instance",
  constants.TAG_NODEGROUP: "gnt-group",
  constants.TAG_NETWORK: "gnt-network",
  }


def _TestTags(kind, name):
  """Generic function for add-tags.

  """
  def cmdfn(subcmd):
    cmd = [_KIND_TO_COMMAND[kind], subcmd]

    if kind != constants.TAG_CLUSTER:
      cmd.append(name)

    return cmd

  for cmd in [
    cmdfn("add-tags") + _TEMP_TAG_NAMES,
    cmdfn("list-tags"),
    ["gnt-cluster", "search-tags", _TEMP_TAG_RE],
    cmdfn("remove-tags") + _TEMP_TAG_NAMES,
    ]:
    AssertCommand(cmd)

  if qa_rapi.Enabled():
    qa_rapi.TestTags(kind, name, _TEMP_TAG_NAMES)


def TestClusterTags():
  """gnt-cluster tags"""
  _TestTags(constants.TAG_CLUSTER, "")


def TestNodeTags(node):
  """gnt-node tags"""
  _TestTags(constants.TAG_NODE, node.primary)


def TestGroupTags(group):
  """gnt-group tags"""
  _TestTags(constants.TAG_NODEGROUP, group)


def TestInstanceTags(instance):
  """gnt-instance tags"""
  _TestTags(constants.TAG_INSTANCE, instance.name)


def TestNetworkTags(network):
  """gnt-network tags"""
  _TestTags(constants.TAG_NETWORK, network)
