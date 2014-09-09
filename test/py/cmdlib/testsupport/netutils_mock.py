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


"""Support for mocking the netutils module"""

import mock

from ganeti import compat
from ganeti import netutils
from cmdlib.testsupport.util import patchModule


# pylint: disable=C0103
def patchNetutils(module_under_test):
  """Patches the L{ganeti.netutils} module for tests.

  This function is meant to be used as a decorator for test methods.

  @type module_under_test: string
  @param module_under_test: the module within cmdlib which is tested. The
        "ganeti.cmdlib" prefix is optional.

  """
  return patchModule(module_under_test, "netutils")


class HostnameMock(object):
  """Simple mocked version of L{netutils.Hostname}.

  """
  def __init__(self, name, ip):
    self.name = name
    self.ip = ip


def _IsOverwrittenReturnValue(value):
  return value is not None and value != mock.DEFAULT and \
      not isinstance(value, mock.Mock)


# pylint: disable=W0613
def _GetHostnameMock(cfg, mock_fct, name=None, family=None):
  if _IsOverwrittenReturnValue(mock_fct.return_value):
    return mock.DEFAULT

  if name is None:
    name = cfg.GetMasterNodeName()

  if name == cfg.GetClusterName():
    cluster = cfg.GetClusterInfo()
    return HostnameMock(cluster.cluster_name, cluster.master_ip)

  node = cfg.GetNodeInfoByName(name)
  if node is not None:
    return HostnameMock(node.name, node.primary_ip)

  return HostnameMock(name, "203.0.113.253")


# pylint: disable=W0613
def _TcpPingMock(cfg, mock_fct, target, port, timeout=None,
                 live_port_needed=None, source=None):
  if _IsOverwrittenReturnValue(mock_fct.return_value):
    return mock.DEFAULT

  if target == cfg.GetClusterName():
    return True
  if cfg.GetNodeInfoByName(target) is not None:
    return True
  if target in [node.primary_ip for node in cfg.GetAllNodesInfo().values()]:
    return True
  if target in [node.secondary_ip for node in cfg.GetAllNodesInfo().values()]:
    return True
  return False


def SetupDefaultNetutilsMock(netutils_mod, cfg):
  """Configures the given netutils_mod mock to work with the given config.

  All relevant functions in netutils_mod are stubbed in such a way that they
  are consistent with the configuration.

  @param netutils_mod: the mock module to configure
  @type cfg: cmdlib.testsupport.ConfigMock
  @param cfg: the configuration to query for netutils request

  """
  netutils_mod.GetHostname.side_effect = \
    compat.partial(_GetHostnameMock, cfg, netutils_mod.GetHostname)
  netutils_mod.TcpPing.side_effect = \
    compat.partial(_TcpPingMock, cfg, netutils_mod.TcpPing)
  netutils_mod.GetDaemonPort.side_effect = netutils.GetDaemonPort
  netutils_mod.FormatAddress.side_effect = netutils.FormatAddress
  netutils_mod.Hostname.GetNormalizedName.side_effect = \
    netutils.Hostname.GetNormalizedName
  netutils_mod.IPAddress = netutils.IPAddress
  netutils_mod.IP4Address = netutils.IP4Address
  netutils_mod.IP6Address = netutils.IP6Address
