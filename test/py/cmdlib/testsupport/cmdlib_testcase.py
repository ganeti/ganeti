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
import mock
import re
import traceback

from cmdlib.testsupport.config_mock import ConfigMock
from cmdlib.testsupport.iallocator_mock import patchIAllocator
from cmdlib.testsupport.lock_manager_mock import LockManagerMock
from cmdlib.testsupport.netutils_mock import patchNetutils, \
  SetupDefaultNetutilsMock
from cmdlib.testsupport.processor_mock import ProcessorMock
from cmdlib.testsupport.rpc_runner_mock import CreateRpcRunnerMock, \
  RpcResultsBuilder, patchRpc, SetupDefaultRpcModuleMock
from cmdlib.testsupport.ssh_mock import patchSsh

from ganeti.cmdlib.base import LogicalUnit
from ganeti import errors
from ganeti import locking
from ganeti import objects
from ganeti import opcodes
from ganeti import runtime

import testutils


class GanetiContextMock(object):
  # pylint: disable=W0212
  cfg = property(fget=lambda self: self._test_case.cfg)
  # pylint: disable=W0212
  glm = property(fget=lambda self: self._test_case.glm)
  # pylint: disable=W0212
  rpc = property(fget=lambda self: self._test_case.rpc)

  def __init__(self, test_case):
    self._test_case = test_case

  def AddNode(self, node, ec_id):
    self._test_case.cfg.AddNode(node, ec_id)
    self._test_case.glm.add(locking.LEVEL_NODE, node.uuid)
    self._test_case.glm.add(locking.LEVEL_NODE_RES, node.uuid)

  def ReaddNode(self, node):
    pass

  def RemoveNode(self, node):
    self._test_case.cfg.RemoveNode(node.uuid)
    self._test_case.glm.remove(locking.LEVEL_NODE, node.uuid)
    self._test_case.glm.remove(locking.LEVEL_NODE_RES, node.uuid)


class MockLU(LogicalUnit):
  def BuildHooksNodes(self):
    pass

  def BuildHooksEnv(self):
    pass


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

  cluster = property(fget=lambda self: self.cfg.GetClusterInfo(),
                     doc="Cluster configuration object")
  master = property(fget=lambda self: self.cfg.GetMasterNodeInfo(),
                    doc="Master node")
  master_uuid = property(fget=lambda self: self.cfg.GetMasterNode(),
                         doc="Master node UUID")
  # pylint: disable=W0212
  group = property(fget=lambda self: self._GetDefaultGroup(),
                   doc="Default node group")

  os = property(fget=lambda self: self.cfg.GetDefaultOs(),
                doc="Default OS")
  os_name_variant = property(
    fget=lambda self: self.os.name + objects.OS.VARIANT_DELIM +
      self.os.supported_variants[0],
    doc="OS name and variant string")

  def setUp(self):
    super(CmdlibTestCase, self).setUp()
    self._iallocator_patcher = None
    self._netutils_patcher = None
    self._ssh_patcher = None
    self._rpc_patcher = None

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
    if self._rpc_patcher is not None:
      self._rpc_patcher.stop()
      self._rpc_patcher = None

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
    self.ctx = GanetiContextMock(self)
    self.mcpu = ProcessorMock(self.ctx)

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

    try:
      self._rpc_patcher = patchRpc(self._GetTestModule())
      self.rpc_mod = self._rpc_patcher.start()
      SetupDefaultRpcModuleMock(self.rpc_mod)
    except (ImportError, AttributeError):
      # this test module does not use rpc, no patching performed
      self._rpc_patcher = None

  def GetMockLU(self):
    """Creates a mock L{LogialUnit} with access to the mocked config etc.

    @rtype: L{LogialUnit}
    @return: A mock LU

    """
    return MockLU(self.mcpu, mock.MagicMock(), self.ctx, self.rpc)

  def RpcResultsBuilder(self, use_node_names=False):
    """Creates a pre-configured L{RpcResultBuilder}

    @type use_node_names: bool
    @param use_node_names: @see L{RpcResultBuilder}
    @rtype: L{RpcResultBuilder}
    @return: a pre-configured builder for RPC results

    """
    return RpcResultsBuilder(cfg=self.cfg, use_node_names=use_node_names)

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

  def RunWithLockedLU(self, opcode, test_func):
    """Takes the given opcode, creates a LU and runs func on it.

    The passed LU did already perform locking, but no methods which actually
    require locking are executed on the LU.

    @param opcode: the opcode to get the LU for.
    @param test_func: the function to execute with the LU as parameter.
    @return: the result of test_func

    """
    self.glm.AddLocksFromConfig(self.cfg)

    return self.mcpu.RunWithLockedLU(opcode, test_func)

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
      if value == self.REMOVE and key in state:
        del state[key]
      else:
        state[key] = value

    return opcodes.OpCode.LoadOpCode(state)

  def _GetDefaultGroup(self):
    for group in self.cfg.GetAllNodeGroupsInfo().values():
      if group.name == "default":
        return group
    assert False


# pylint: disable=C0103
def withLockedLU(func):
  """Convenience decorator which runs the decorated method with the LU.

  This uses L{CmdlibTestCase.RunWithLockedLU} to run the decorated method.
  For this to work, the opcode to run has to be an instance field named "op",
  "_op", "opcode" or "_opcode".

  If the instance has a method called "PrepareLU", this method is invoked with
  the LU right before the test method is called.

  """
  def wrapper(*args, **kwargs):
    test = args[0]
    assert isinstance(test, CmdlibTestCase)

    op = None
    for attr_name in ["op", "_op", "opcode", "_opcode"]:
      if hasattr(test, attr_name):
        op = getattr(test, attr_name)
        break
    assert op is not None

    prepare_fn = None
    if hasattr(test, "PrepareLU"):
      prepare_fn = getattr(test, "PrepareLU")
      assert callable(prepare_fn)

    # pylint: disable=W0142
    def callWithLU(lu):
      if prepare_fn:
        prepare_fn(lu)

      new_args = list(args)
      new_args.append(lu)
      func(*new_args, **kwargs)

    return test.RunWithLockedLU(op, callWithLU)
  return wrapper
