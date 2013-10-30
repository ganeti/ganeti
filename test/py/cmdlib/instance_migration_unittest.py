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


"""Tests for LUInstanceFailover and LUInstanceMigrate

"""

from ganeti import constants
from ganeti import objects
from ganeti import opcodes

from testsupport import *

import testutils


class TestLUInstanceMigrate(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceMigrate, self).setUp()

    self.snode = self.cfg.AddNewNode()

    hv_info = ("bootid",
               [{
                 "type": constants.ST_LVM_VG,
                 "storage_free": 10000
               }],
               ({"memory_free": 10000}, ))
    self.rpc.call_node_info.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, hv_info) \
        .AddSuccessfulNode(self.snode, hv_info) \
        .Build()

    self.rpc.call_blockdev_find.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, objects.BlockDevStatus())

    self.rpc.call_migration_info.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_accept_instance.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.snode, True)
    self.rpc.call_instance_migrate.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_instance_get_migration_status.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, objects.MigrationStatus())
    self.rpc.call_instance_finalize_migration_dst.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.snode, True)
    self.rpc.call_instance_finalize_migration_src.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)

    self.inst = self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                                        admin_state=constants.ADMINST_UP,
                                        secondary_node=self.snode)
    self.op = opcodes.OpInstanceMigrate(instance_name=self.inst.name)

  def testPlainDisk(self):
    inst = self.cfg.AddNewInstance(disk_template=constants.DT_PLAIN)
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance's disk layout 'plain' does not allow migrations")

  def testMigrationToWrongNode(self):
    node = self.cfg.AddNewNode()
    op = self.CopyOpCode(self.op,
                         target_node=node.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instances with disk template drbd cannot be migrated to"
          " arbitrary nodes")

  def testMigration(self):
    op = self.CopyOpCode(self.op)
    self.ExecOpCode(op)


class TestLUInstanceFailover(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceFailover, self).setUp()

    self.snode = self.cfg.AddNewNode()

    hv_info = ("bootid",
               [{
                 "type": constants.ST_LVM_VG,
                 "storage_free": 10000
               }],
               ({"memory_free": 10000}, ))
    self.rpc.call_node_info.return_value = \
      self.RpcResultsBuilder() \
        .AddSuccessfulNode(self.master, hv_info) \
        .AddSuccessfulNode(self.snode, hv_info) \
        .Build()

    self.rpc.call_blockdev_find.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, objects.BlockDevStatus())

    self.rpc.call_instance_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_blockdev_shutdown.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_blockdev_assemble.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.snode, ("/dev/mock", "/var/mock"))
    self.rpc.call_instance_start.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.snode, True)

    self.inst = self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                                        admin_state=constants.ADMINST_UP,
                                        secondary_node=self.snode)
    self.op = opcodes.OpInstanceFailover(instance_name=self.inst.name)

  def testPlainDisk(self):
    inst = self.cfg.AddNewInstance(disk_template=constants.DT_PLAIN)
    op = self.CopyOpCode(self.op,
                         instance_name=inst.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance's disk layout 'plain' does not allow failovers")

  def testMigrationToWrongNode(self):
    node = self.cfg.AddNewNode()
    op = self.CopyOpCode(self.op,
                         target_node=node.name)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instances with disk template drbd cannot be failed over to"
          " arbitrary nodes")

  def testMigration(self):
    op = self.CopyOpCode(self.op)
    self.ExecOpCode(op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
