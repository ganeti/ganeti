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


"""Tests for LUTest*

"""


from ganeti import constants
from ganeti import errors
from ganeti import opcodes

from testsupport import *

import testutils

DELAY_DURATION = 0.01


class TestLUTestDelay(CmdlibTestCase):
  def testRepeatedInvocation(self):
    op = opcodes.OpTestDelay(duration=DELAY_DURATION,
                             repeat=3)
    self.ExecOpCode(op)

    self.assertLogContainsMessage(" - INFO: Test delay iteration 0/2")
    self.mcpu.assertLogContainsEntry(constants.ELOG_MESSAGE,
                                     " - INFO: Test delay iteration 1/2")
    self.assertLogContainsRegex("2/2$")

  def testInvalidDuration(self):
    op = opcodes.OpTestDelay(duration=-1)

    self.assertRaises(errors.OpExecError, self.ExecOpCode, op)

  def testOnNodeUuid(self):
    node_uuids = [self.cfg.GetMasterNode()]
    op = opcodes.OpTestDelay(duration=DELAY_DURATION,
                             on_node_uuids=node_uuids)
    self.ExecOpCode(op)

    self.rpc.call_test_delay.assert_called_once_with(node_uuids, DELAY_DURATION)

  def testOnNodeName(self):
    op = opcodes.OpTestDelay(duration=DELAY_DURATION,
                             on_nodes=[self.cfg.GetMasterNodeName()])
    self.ExecOpCode(op)

    self.rpc.call_test_delay.assert_called_once_with([self.cfg.GetMasterNode()],
                                                     DELAY_DURATION)

  def testSuccessfulRpc(self):
    op = opcodes.OpTestDelay(duration=DELAY_DURATION,
                             on_nodes=[self.cfg.GetMasterNodeName()])

    self.rpc.call_test_delay.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .AddSuccessfulNode(self.cfg.GetMasterNode()) \
        .Build()

    self.ExecOpCode(op)

    self.rpc.call_test_delay.assert_called_once()

  def testFailingRpc(self):
    op = opcodes.OpTestDelay(duration=DELAY_DURATION,
                             on_nodes=[self.cfg.GetMasterNodeName()])

    self.rpc.call_test_delay.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .AddFailedNode(self.cfg.GetMasterNode()) \
        .Build()

    self.assertRaises(errors.OpExecError, self.ExecOpCode, op)

  def testMultipleNodes(self):
    node1 = self.cfg.AddNewNode()
    node2 = self.cfg.AddNewNode()
    op = opcodes.OpTestDelay(duration=DELAY_DURATION,
                             on_nodes=[node1.name, node2.name])

    self.rpc.call_test_delay.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .AddSuccessfulNode(node1) \
        .AddSuccessfulNode(node2) \
        .Build()

    self.ExecOpCode(op)

    self.rpc.call_test_delay.assert_called_once_with([node1.uuid, node2.uuid],
                                                     DELAY_DURATION)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
