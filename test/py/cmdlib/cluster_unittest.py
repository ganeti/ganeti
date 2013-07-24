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


"""Tests for LUCluster*

"""

from ganeti import opcodes

from testsupport import *

import testutils


class TestLUClusterActivateMasterIp(CmdlibTestCase):
  def testSuccess(self):
    op = opcodes.OpClusterActivateMasterIp()

    self.rpc.call_node_activate_master_ip.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateSuccessfulNodeResult(self.cfg.GetMasterNode())

    self.ExecOpCode(op)

    self.rpc.call_node_activate_master_ip.assert_called_once_with(
      self.cfg.GetMasterNode(),
      self.cfg.GetMasterNetworkParameters(),
      False)

  def testFailure(self):
    op = opcodes.OpClusterActivateMasterIp()

    self.rpc.call_node_activate_master_ip.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .CreateFailedNodeResult(self.cfg.GetMasterNode()) \

    self.ExecOpCodeExpectOpExecError(op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
