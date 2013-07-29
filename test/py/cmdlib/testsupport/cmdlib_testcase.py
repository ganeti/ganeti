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


"""Main module of the cmdlib test framework"""


from cmdlib.testsupport.config_mock import ConfigMock
from cmdlib.testsupport.iallocator_mock import CreateIAllocatorMock
from cmdlib.testsupport.lock_manager_mock import LockManagerMock
from cmdlib.testsupport.processor_mock import ProcessorMock
from cmdlib.testsupport.rpc_runner_mock import CreateRpcRunnerMock

import testutils


class GanetiContextMock(object):
  def __init__(self, cfg, glm, rpc):
    self.cfg = cfg
    self.glm = glm
    self.rpc = rpc


# pylint: disable=R0904
class CmdlibTestCase(testutils.GanetiTestCase):
  """Base class for cmdlib tests.

  This class sets up a mocked environment for the execution of
  L{ganeti.cmdlib.base.LogicalUnit} subclasses.

  The environment can be customized via the following fields:

    * C{cfg}: @see L{ConfigMock}
    * C{glm}: @see L{LockManagerMock}
    * C{rpc}: @see L{CreateRpcRunnerMock}
    * C{iallocator}: @see L{CreateIAllocatorMock}
    * C{mcpu}: @see L{ProcessorMock}

  """
  def setUp(self):
    super(CmdlibTestCase, self).setUp()

    self.cfg = ConfigMock()
    self.glm = LockManagerMock()
    self.rpc = CreateRpcRunnerMock()
    self.iallocator = CreateIAllocatorMock()
    ctx = GanetiContextMock(self.cfg, self.glm, self.rpc)
    self.mcpu = ProcessorMock(ctx)

  def tearDown(self):
    super(CmdlibTestCase, self).tearDown()

  def ExecOpCode(self, opcode):
    """Executes the given opcode.

    @param opcode: the opcode to execute
    @return: the result of the LU's C{Exec} method
    """
    self.glm.AddLocksFromConfig(self.cfg)

    return self.mcpu.ExecOpCodeAndRecordOutput(opcode)

  def assertLogContainsMessage(self, expected_msg):
    """Shortcut for L{ProcessorMock.assertLogContainsMessage}

    """
    self.mcpu.assertLogContainsMessage(expected_msg)

  def assertLogContainsRegex(self, expected_regex):
    """Shortcut for L{ProcessorMock.assertLogContainsRegex}

    """
    self.mcpu.assertLogContainsRegex(expected_regex)

