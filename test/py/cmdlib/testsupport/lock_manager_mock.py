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


"""Support for mocking the lock manager"""


from ganeti import locking


class LockManagerMock(locking.GanetiLockManager):
  """Mocked lock manager for tests.

  """
  def __init__(self):
    # reset singleton instance, there is a separate lock manager for every test
    # pylint: disable=W0212
    self.__class__._instance = None

    super(LockManagerMock, self).__init__([], [], [], [])

  def AddLocksFromConfig(self, cfg):
    """Create locks for all entities in the given configuration.

    @type cfg: ganeti.config.ConfigWriter
    """
    try:
      self.acquire(locking.LEVEL_CLUSTER, locking.BGL)

      for node_uuid in cfg.GetNodeList():
        self.add(locking.LEVEL_NODE, node_uuid)
        self.add(locking.LEVEL_NODE_RES, node_uuid)
      for group_uuid in cfg.GetNodeGroupList():
        self.add(locking.LEVEL_NODEGROUP, group_uuid)
      for inst in cfg.GetAllInstancesInfo().values():
        self.add(locking.LEVEL_INSTANCE, inst.name)
      for net_uuid in cfg.GetNetworkList():
        self.add(locking.LEVEL_NETWORK, net_uuid)
    finally:
      self.release(locking.LEVEL_CLUSTER, locking.BGL)
