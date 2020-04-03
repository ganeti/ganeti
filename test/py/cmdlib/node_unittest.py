#!/usr/bin/python3
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


"""Tests for LUNode*

"""

from collections import defaultdict
import mock

from ganeti import compat
from ganeti import constants
from ganeti import objects
from ganeti import opcodes
from ganeti.cmdlib import node

from testsupport import *

import testutils


# pylint: disable=W0613
def _TcpPingFailSecondary(cfg, mock_fct, target, port, timeout=None,
                          live_port_needed=None, source=None):
  # This will return True if target is in 192.0.2.0/24 (primary range)
  # and False if not.
  return "192.0.2." in target


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
    self.rpc.call_node_crypto_tokens.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.node_add,
            [(constants.CRYPTO_TYPE_SSL_DIGEST, "IA:MA:FA:KE:DI:GE:ST")])

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

  def testAddCandidateCert(self):
    self.ExecOpCode(self.op_add)

    created_node = self.cfg.GetNodeInfoByName(self.op_add.node_name)
    cluster = self.cfg.GetClusterInfo()
    self.assertTrue(created_node.uuid in cluster.candidate_certs)

  def testReAddCandidateCert(self):
    cluster = self.cfg.GetClusterInfo()
    self.ExecOpCode(self.op_readd)
    created_node = self.cfg.GetNodeInfoByName(self.op_readd.node_name)
    self.assertTrue(created_node.uuid in cluster.candidate_certs)

  def testAddNoCandidateCert(self):
    op = self.CopyOpCode(self.op_add,
                         master_capable=False)
    self.ExecOpCode(op)

    created_node = self.cfg.GetNodeInfoByName(self.op_add.node_name)
    cluster = self.cfg.GetClusterInfo()
    self.assertFalse(created_node.uuid in cluster.candidate_certs)

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

  def testReaddingMaster(self):
    op = opcodes.OpNodeAdd(node_name=self.cfg.GetMasterNodeName(),
                           readd=True)

    self.ExecOpCodeExpectOpPrereqError(op, "Cannot readd the master node")

  def testReaddNotVmCapableNode(self):
    self.cfg.AddNewInstance(primary_node=self.node_readd)
    self.netutils_mod.GetHostname.return_value = \
      HostnameMock(self.node_readd.name, self.node_readd.primary_ip)

    op = self.CopyOpCode(self.op_readd, vm_capable=False)

    self.ExecOpCodeExpectOpPrereqError(op, "Node .* being re-added with"
                                       " vm_capable flag set to false, but it"
                                       " already holds instances")

  def testReaddAndPassNodeGroup(self):
    op = self.CopyOpCode(self.op_readd,group="groupname")

    self.ExecOpCodeExpectOpPrereqError(op, "Cannot pass a node group when a"
                                       " node is being readded")

  def testPrimaryIPv6(self):
    self.master.secondary_ip = self.master.primary_ip

    op = self.CopyOpCode(self.op_add, primary_ip="2001:DB8::1",
                         secondary_ip=self.REMOVE)

    self.ExecOpCode(op)

  def testInvalidSecondaryIP(self):
    op = self.CopyOpCode(self.op_add, secondary_ip="333.444.555.777")

    self.ExecOpCodeExpectOpPrereqError(op, "Secondary IP .* needs to be a valid"
                                       " IPv4 address")

  def testNodeAlreadyInCluster(self):
    op = self.CopyOpCode(self.op_readd, readd=False)

    self.ExecOpCodeExpectOpPrereqError(op, "Node %s is already in the"
                                       " configuration" % self.node_readd.name)

  def testReaddNodeNotInConfiguration(self):
    op = self.CopyOpCode(self.op_add, readd=True)

    self.ExecOpCodeExpectOpPrereqError(op, "Node %s is not in the"
                                       " configuration" % self.node_add.name)

  def testPrimaryIpConflict(self):
    # In LUNodeAdd, DNS will resolve the node name to an IP address, that is
    # used to overwrite any given primary_ip value!
    # Thus we need to mock this DNS resolver here!
    self.netutils_mod.GetHostname.return_value = \
      HostnameMock(self.node_add.name, self.node_readd.primary_ip)

    op = self.CopyOpCode(self.op_add)

    self.ExecOpCodeExpectOpPrereqError(op, "New node ip address.* conflict with"
                                       " existing node")

  def testSecondaryIpConflict(self):
    op = self.CopyOpCode(self.op_add, secondary_ip=self.node_readd.secondary_ip)

    self.ExecOpCodeExpectOpPrereqError(op, "New node ip address.* conflict with"
                                       " existing node")

  def testReaddWithDifferentIP(self):
    op = self.CopyOpCode(self.op_readd, primary_ip="192.0.2.100",
                         secondary_ip="230.0.113.100")

    self.ExecOpCodeExpectOpPrereqError(op, "Readded node doesn't have the same"
                                       " IP address configuration as before")

  def testNodeHasSecondaryIpButNotMaster(self):
    self.master.secondary_ip = self.master.primary_ip

    self.ExecOpCodeExpectOpPrereqError(self.op_add, "The master has no"
                                       " secondary ip but the new node has one")

  def testMasterHasSecondaryIpButNotNode(self):
    op = self.CopyOpCode(self.op_add, secondary_ip=None)

    self.ExecOpCodeExpectOpPrereqError(op, "The master has a secondary ip but"
                                       " the new node doesn't have one")

  def testNodeNotReachableByPing(self):
    self.netutils_mod.TcpPing.return_value = False

    op = self.CopyOpCode(self.op_add)

    self.ExecOpCodeExpectOpPrereqError(op, "Node not reachable by ping")

  def testNodeNotReachableByPingOnSecondary(self):
    self.netutils_mod.GetHostname.return_value = \
      HostnameMock(self.node_add.name, self.node_add.primary_ip)
    self.netutils_mod.TcpPing.side_effect = \
      compat.partial(_TcpPingFailSecondary, self.cfg, self.netutils_mod.TcpPing)

    op = self.CopyOpCode(self.op_add)

    self.ExecOpCodeExpectOpPrereqError(op, "Node secondary ip not reachable by"
                                       " TCP based ping to node daemon port")

  def testCantGetVersion(self):
    self.mocked_dns_rpc.call_version.return_value = \
      self.RpcResultsBuilder(use_node_names=True) \
        .AddErrorNode(self.node_add) \
        .Build()

    op = self.CopyOpCode(self.op_add)
    self.ExecOpCodeExpectOpPrereqError(op, "Can't get version information from"
                                       " node %s" % self.node_add.name)


class TestLUNodeSetParams(CmdlibTestCase):
  def setUp(self):
    super(TestLUNodeSetParams, self).setUp()

    self.MockOut(node, 'netutils', self.netutils_mod)
    node.netutils.TcpPing.return_value = True

    self.node = self.cfg.AddNewNode(
        primary_ip='192.168.168.191',
        secondary_ip='192.168.168.192',
        master_candidate=True, uuid='blue_bunny')

    self.snode = self.cfg.AddNewNode(
        primary_ip='192.168.168.193',
        secondary_ip='192.168.168.194',
        master_candidate=True, uuid='pink_bunny')

  def testSetSecondaryIp(self):
    self.instance = self.cfg.AddNewInstance(primary_node=self.node,
                                            secondary_node=self.snode,
                                            disk_template='drbd')
    op = opcodes.OpNodeSetParams(node_name=self.node.name,
                                 secondary_ip='254.254.254.254')
    self.ExecOpCode(op)

    self.assertEqual('254.254.254.254', self.node.secondary_ip)
    self.assertEqual(sorted(self.wconfd.all_locks.items()), [
        ('cluster/BGL', 'shared'),
        ('instance/mock_inst_1.example.com', 'shared'),
        ('node-res/blue_bunny', 'exclusive'),
        ('node/blue_bunny', 'exclusive')])

  def testSetSecondaryIpNoLock(self):
    self.instance = self.cfg.AddNewInstance(primary_node=self.node,
                                            secondary_node=self.snode,
                                            disk_template='file')
    op = opcodes.OpNodeSetParams(node_name=self.node.name,
                                 secondary_ip='254.254.254.254')
    self.ExecOpCode(op)

    self.assertEqual('254.254.254.254', self.node.secondary_ip)
    self.assertEqual(sorted(self.wconfd.all_locks.items()), [
        ('cluster/BGL', 'shared'),
        ('node-res/blue_bunny', 'exclusive'),
        ('node/blue_bunny', 'exclusive')])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
