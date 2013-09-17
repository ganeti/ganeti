#!/usr/bin/python
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


"""Tests for LUNode*

"""

from collections import defaultdict

from ganeti import constants
from ganeti import objects
from ganeti import opcodes

from testsupport import *

import testutils


class TestLUNodeAdd(CmdlibTestCase):
  def setUp(self):
    super(TestLUNodeAdd, self).setUp()

    # One node for testing readding:
    self.node_readd = self.cfg.AddNewNode()
    self.op_readd = opcodes.OpNodeAdd(node_name=self.node_readd.name,
                                      readd=True,
                                      primary_ip=self.node_readd.primary_ip,
                                      secondary_ip=self.node_readd.secondary_ip)

    # One node for testing adding:
    # don't add to configuration now!
    self.node_add = objects.Node(name="node_add",
                                 primary_ip="192.0.2.200",
                                 secondary_ip="203.0.113.200")

    self.op_add = opcodes.OpNodeAdd(node_name=self.node_add.name,
                                    primary_ip=self.node_add.primary_ip,
                                    secondary_ip=self.node_add.secondary_ip)

    self.netutils_mod.TcpPing.return_value = True

    self.mocked_dns_rpc = self.rpc_mod.DnsOnlyRunner.return_value

    self.mocked_dns_rpc.call_version.return_value = \
      self.RpcResultsBuilder(use_node_names=True) \
        .AddSuccessfulNode(self.node_add, constants.CONFIG_VERSION) \
        .AddSuccessfulNode(self.node_readd, constants.CONFIG_VERSION) \
        .Build()

    node_verify_result = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.node_add, {constants.NV_NODELIST: []})
    # we can't know the node's UUID in advance, so use defaultdict here
    self.rpc.call_node_verify.return_value = \
      defaultdict(lambda: node_verify_result, {})

  def testOvsParamsButNotEnabled(self):
    ndparams = {
      constants.ND_OVS: False,
      constants.ND_OVS_NAME: "testswitch",
    }

    op = self.CopyOpCode(self.op_add,
                         ndparams=ndparams)

    self.ExecOpCodeExpectOpPrereqError(op, "OpenvSwitch is not enabled")

  def testOvsNoLink(self):
    ndparams = {
      constants.ND_OVS: True,
      constants.ND_OVS_NAME: "testswitch",
      constants.ND_OVS_LINK: None,
    }

    op = self.CopyOpCode(self.op_add,
                         ndparams=ndparams)

    self.ExecOpCode(op)
    self.assertLogContainsRegex(
      "No physical interface for OpenvSwitch was given."
      " OpenvSwitch will not have an outside connection."
      " This might not be what you want")

    created_node = self.cfg.GetNodeInfoByName(op.node_name)
    self.assertEqual(ndparams[constants.ND_OVS],
                     created_node.ndparams.get(constants.ND_OVS, None))
    self.assertEqual(ndparams[constants.ND_OVS_NAME],
                     created_node.ndparams.get(constants.ND_OVS_NAME, None))
    self.assertEqual(ndparams[constants.ND_OVS_LINK],
                     created_node.ndparams.get(constants.ND_OVS_LINK, None))

  def testWithoutOVS(self):
    self.ExecOpCode(self.op_add)

    created_node = self.cfg.GetNodeInfoByName(self.op_add.node_name)
    self.assertEqual(None,
                     created_node.ndparams.get(constants.ND_OVS, None))

  def testWithOVS(self):
    ndparams = {
      constants.ND_OVS: True,
      constants.ND_OVS_LINK: "eth2",
    }

    op = self.CopyOpCode(self.op_add,
                         ndparams=ndparams)

    self.ExecOpCode(op)

    created_node = self.cfg.GetNodeInfoByName(op.node_name)
    self.assertEqual(ndparams[constants.ND_OVS],
                     created_node.ndparams.get(constants.ND_OVS, None))
    self.assertEqual(ndparams[constants.ND_OVS_LINK],
                     created_node.ndparams.get(constants.ND_OVS_LINK, None))

if __name__ == "__main__":
  testutils.GanetiTestProgram()
