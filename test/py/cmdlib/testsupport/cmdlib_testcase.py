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


import inspect
import re
import traceback

from cmdlib.testsupport.config_mock import ConfigMock
from cmdlib.testsupport.iallocator_mock import patchIAllocator
from cmdlib.testsupport.lock_manager_mock import LockManagerMock
from cmdlib.testsupport.netutils_mock import patchNetutils, \
  SetupDefaultNetutilsMock
from cmdlib.testsupport.processor_mock import ProcessorMock
from cmdlib.testsupport.rpc_runner_mock import CreateRpcRunnerMock
from cmdlib.testsupport.ssh_mock import patchSsh

from ganeti import errors
from ganeti import opcodes
from ganeti import runtime

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
    * C{iallocator_cls}: @see L{patchIAllocator}
    * C{mcpu}: @see L{ProcessorMock}
    * C{netutils_mod}: @see L{patchNetutils}
    * C{ssh_mod}: @see L{patchSsh}

  """

  REMOVE = object()

  def setUp(self):
    super(CmdlibTestCase, self).setUp()
    self._iallocator_patcher = None
    self._netutils_patcher = None
    self._ssh_patcher = None

    try:
      runtime.InitArchInfo()
    except errors.ProgrammerError:
      # during tests, the arch info can be initialized multiple times
      pass

    self.ResetMocks()

  def _StopPatchers(self):
    if self._iallocator_patcher is not None:
      self._iallocator_patcher.stop()
      self._iallocator_patcher = None
    if self._netutils_patcher is not None:
      self._netutils_patcher.stop()
      self._netutils_patcher = None
    if self._ssh_patcher is not None:
      self._ssh_patcher.stop()
      self._ssh_patcher = None

  def tearDown(self):
    super(CmdlibTestCase, self).tearDown()

    self._StopPatchers()

  def _GetTestModule(self):
    module = inspect.getsourcefile(self.__class__).split("/")[-1]
    suffix = "_unittest.py"
    assert module.endswith(suffix), "Naming convention for cmdlib test" \
                                    " modules is: <module>%s (found '%s')"\
                                    % (suffix, module)
    return module[:-len(suffix)]

  def ResetMocks(self):
    """Resets all mocks back to their initial state.

    This is useful if you want to execute more than one opcode in a single
    test.

    """
    self.cfg = ConfigMock()
    self.glm = LockManagerMock()
    self.rpc = CreateRpcRunnerMock()
    ctx = GanetiContextMock(self.cfg, self.glm, self.rpc)
    self.mcpu = ProcessorMock(ctx)

    self._StopPatchers()
    try:
      self._iallocator_patcher = patchIAllocator(self._GetTestModule())
      self.iallocator_cls = self._iallocator_patcher.start()
    except (ImportError, AttributeError):
      # this test module does not use iallocator, no patching performed
      self._iallocator_patcher = None

    try:
      self._netutils_patcher = patchNetutils(self._GetTestModule())
      self.netutils_mod = self._netutils_patcher.start()
      SetupDefaultNetutilsMock(self.netutils_mod, self.cfg)
    except (ImportError, AttributeError):
      # this test module does not use netutils, no patching performed
      self._netutils_patcher = None

    try:
      self._ssh_patcher = patchSsh(self._GetTestModule())
      self.ssh_mod = self._ssh_patcher.start()
    except (ImportError, AttributeError):
      # this test module does not use ssh, no patching performed
      self._ssh_patcher = None

  def ExecOpCode(self, opcode):
    """Executes the given opcode.

    @param opcode: the opcode to execute
    @return: the result of the LU's C{Exec} method

    """
    self.glm.AddLocksFromConfig(self.cfg)

    return self.mcpu.ExecOpCodeAndRecordOutput(opcode)

  def ExecOpCodeExpectException(self, opcode,
                                expected_exception,
                                expected_regex=None):
    """Executes the given opcode and expects an exception.

    @param opcode: @see L{ExecOpCode}
    @type expected_exception: class
    @param expected_exception: the exception which must be raised
    @type expected_regex: string
    @param expected_regex: if not C{None}, a regular expression which must be
          present in the string representation of the exception

    """
    try:
      self.ExecOpCode(opcode)
    except expected_exception, e:
      if expected_regex is not None:
        assert re.search(expected_regex, str(e)) is not None, \
                "Caught exception '%s' did not match '%s'" % \
                  (str(e), expected_regex)
    except Exception, e:
      tb = traceback.format_exc()
      raise AssertionError("%s\n(See original exception above)\n"
                           "Expected exception '%s' was not raised,"
                           " got '%s' of class '%s' instead." %
                           (tb, expected_exception, e, e.__class__))
    else:
      raise AssertionError("Expected exception '%s' was not raised" %
                           expected_exception)

  def ExecOpCodeExpectOpPrereqError(self, opcode, expected_regex=None):
    """Executes the given opcode and expects a L{errors.OpPrereqError}

    @see L{ExecOpCodeExpectException}

    """
    self.ExecOpCodeExpectException(opcode, errors.OpPrereqError, expected_regex)

  def ExecOpCodeExpectOpExecError(self, opcode, expected_regex=None):
    """Executes the given opcode and expects a L{errors.OpExecError}

    @see L{ExecOpCodeExpectException}

    """
    self.ExecOpCodeExpectException(opcode, errors.OpExecError, expected_regex)

  def assertLogContainsMessage(self, expected_msg):
    """Shortcut for L{ProcessorMock.assertLogContainsMessage}

    """
    self.mcpu.assertLogContainsMessage(expected_msg)

  def assertLogContainsRegex(self, expected_regex):
    """Shortcut for L{ProcessorMock.assertLogContainsRegex}

    """
    self.mcpu.assertLogContainsRegex(expected_regex)

  def assertHooksCall(self, nodes, hook_path, phase,
                      environment=None, count=None, index=0):
    """Asserts a call to C{rpc.call_hooks_runner}

    @type nodes: list of string
    @param nodes: node UUID's or names hooks run on
    @type hook_path: string
    @param hook_path: path (or name) of the hook run
    @type phase: string
    @param phase: phase in which the hook runs in
    @type environment: dict
    @param environment: the environment passed to the hooks. C{None} to skip
            asserting it
    @type count: int
    @param count: the number of hook invocations. C{None} to skip asserting it
    @type index: int
    @param index: the index of the hook invocation to assert

    """
    if count is not None:
      self.assertEqual(count, self.rpc.call_hooks_runner.call_count)

    args = self.rpc.call_hooks_runner.call_args[index]

    self.assertEqual(set(nodes), set(args[0]))
    self.assertEqual(hook_path, args[1])
    self.assertEqual(phase, args[2])
    if environment is not None:
      self.assertEqual(environment, args[3])

  def assertSingleHooksCall(self, nodes, hook_path, phase,
                            environment=None):
    """Asserts a single call to C{rpc.call_hooks_runner}

    @see L{assertHooksCall} for parameter description.

    """
    self.assertHooksCall(nodes, hook_path, phase,
                         environment=environment, count=1)

  def CopyOpCode(self, opcode, **kwargs):
    """Creates a copy of the given opcode and applies modifications to it

    @type opcode: opcode.OpCode
    @param opcode: the opcode to copy
    @type kwargs: dict
    @param kwargs: dictionary of fields to overwrite in the copy. The special
          value L{REMOVE} can be used to remove fields from the copy.
    @return: a copy of the given opcode

    """
    state = opcode.__getstate__()

    for key, value in kwargs.items():
      if value == self.REMOVE:
        del state[key]
      else:
        state[key] = value

    return opcodes.OpCode.LoadOpCode(state)
