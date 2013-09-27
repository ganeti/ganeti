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
