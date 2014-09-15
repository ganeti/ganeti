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


"""Support for mocking the RPC runner"""


import mock

from ganeti import objects
from ganeti.rpc import node as rpc

from cmdlib.testsupport.util import patchModule


def CreateRpcRunnerMock():
  """Creates a new L{mock.MagicMock} tailored for L{rpc.RpcRunner}

  """
  ret = mock.MagicMock(spec=rpc.RpcRunner)
  return ret


class RpcResultsBuilder(object):
  """Helper class which assists in constructing L{rpc.RpcResult} objects.

  This class provides some convenience methods for constructing L{rpc.RpcResult}
  objects. It is possible to create single results with the C{Create*} methods
  or to create multi-node results by repeatedly calling the C{Add*} methods and
  then obtaining the final result with C{Build}.

  The C{node} parameter of all the methods can either be a L{objects.Node}
  object, a node UUID or a node name. You have to provide the cluster config
  in the constructor if you want to use node UUID's/names.

  A typical usage of this class is as follows::

    self.rpc.call_some_rpc.return_value = \
      RpcResultsBuilder(cfg=self.cfg) \
        .AddSuccessfulNode(node1,
                           {
                             "result_key": "result_data",
                             "another_key": "other_data",
                           }) \
        .AddErrorNode(node2) \
        .Build()

  """

  def __init__(self, cfg=None, use_node_names=False):
    """Constructor.

    @type cfg: L{ganeti.config.ConfigWriter}
    @param cfg: used to resolve nodes if not C{None}
    @type use_node_names: bool
    @param use_node_names: if set to C{True}, the node field in the RPC results
          will contain the node name instead of the node UUID.
    """
    self._cfg = cfg
    self._use_node_names = use_node_names
    self._results = []

  def _GetNode(self, node_id):
    if isinstance(node_id, objects.Node):
      return node_id

    node = None
    if self._cfg is not None:
      node = self._cfg.GetNodeInfo(node_id)
      if node is None:
        node = self._cfg.GetNodeInfoByName(node_id)

    assert node is not None, "Failed to find '%s' in configuration" % node_id
    return node

  def _GetNodeId(self, node_id):
    node = self._GetNode(node_id)
    if self._use_node_names:
      return node.name
    else:
      return node.uuid

  def CreateSuccessfulNodeResult(self, node, data=None):
    """@see L{RpcResultsBuilder}

    @param node: @see L{RpcResultsBuilder}.
    @type data: dict
    @param data: the data as returned by the RPC
    @rtype: L{rpc.RpcResult}
    """
    if data is None:
      data = {}
    return rpc.RpcResult(data=(True, data), node=self._GetNodeId(node))

  def CreateFailedNodeResult(self, node):
    """@see L{RpcResultsBuilder}

    @param node: @see L{RpcResultsBuilder}.
    @rtype: L{rpc.RpcResult}
    """
    return rpc.RpcResult(failed=True, node=self._GetNodeId(node))

  def CreateOfflineNodeResult(self, node):
    """@see L{RpcResultsBuilder}

    @param node: @see L{RpcResultsBuilder}.
    @rtype: L{rpc.RpcResult}
    """
    return rpc.RpcResult(failed=True, offline=True, node=self._GetNodeId(node))

  def CreateErrorNodeResult(self, node, error_msg=None):
    """@see L{RpcResultsBuilder}

    @param node: @see L{RpcResultsBuilder}.
    @type error_msg: string
    @param error_msg: the error message as returned by the RPC
    @rtype: L{rpc.RpcResult}
    """
    return rpc.RpcResult(data=(False, error_msg), node=self._GetNodeId(node))

  def AddSuccessfulNode(self, node, data=None):
    """@see L{CreateSuccessfulNode}

    @rtype: L{RpcResultsBuilder}
    @return: self for chaining

    """
    self._results.append(self.CreateSuccessfulNodeResult(node, data))
    return self

  def AddFailedNode(self, node):
    """@see L{CreateFailedNode}

    @rtype: L{RpcResultsBuilder}
    @return: self for chaining

    """
    self._results.append(self.CreateFailedNodeResult(node))
    return self

  def AddOfflineNode(self, node):
    """@see L{CreateOfflineNode}

    @rtype: L{RpcResultsBuilder}
    @return: self for chaining

    """
    self._results.append(self.CreateOfflineNodeResult(node))
    return self

  def AddErrorNode(self, node, error_msg=None):
    """@see L{CreateErrorNode}

    @rtype: L{RpcResultsBuilder}
    @return: self for chaining

    """
    self._results.append(self.CreateErrorNodeResult(node, error_msg=error_msg))
    return self

  def Build(self):
    """Creates a dictionary holding multi-node results

    @rtype: dict
    """
    return dict((result.node, result) for result in self._results)


# pylint: disable=C0103
def patchRpc(module_under_test):
  """Patches the L{ganeti.rpc} module for tests.

  This function is meant to be used as a decorator for test methods.

  @type module_under_test: string
  @param module_under_test: the module within cmdlib which is tested. The
        "ganeti.cmdlib" prefix is optional.

  """
  return patchModule(module_under_test, "rpc", wraps=rpc)


def SetupDefaultRpcModuleMock(rpc_mod):
  """Configures the given rpc_mod.

  All relevant functions in rpc_mod are stubbed in a sensible way.

  @param rpc_mod: the mock module to configure

  """
  rpc_mod.DnsOnlyRunner.return_value = CreateRpcRunnerMock()
