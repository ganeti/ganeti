#!/usr/bin/python
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


"""Tests for LUInstanceFailover and LUInstanceMigrate

"""

from ganeti import constants
from ganeti import objects
from ganeti import opcodes

from testsupport import *

from functools import partial
import testutils
import mock


class TestLUInstanceMigrate(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceMigrate, self).setUp()

    self.snode = self.cfg.AddNewNode()

    self._ResetRPC()

    self.inst = self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                                        admin_state=constants.ADMINST_UP,
                                        secondary_node=self.snode)
    self.op = opcodes.OpInstanceMigrate(instance_name=self.inst.name)

  def _ResetRPC(self):
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
    self.rpc.call_instance_start_postcopy.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)
    self.rpc.call_instance_finalize_migration_dst.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.snode, True)
    self.rpc.call_instance_finalize_migration_src.return_value = \
      self.RpcResultsBuilder() \
        .CreateSuccessfulNodeResult(self.master, True)

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
      op, "Instances with disk types drbd cannot be migrated to"
          " arbitrary nodes")

  def testMigration(self):
    op = self.CopyOpCode(self.op)
    self.ExecOpCode(op)

  def _buildMigrationStatusResponse(self, **kwargs):
      return self.RpcResultsBuilder().CreateSuccessfulNodeResult(
          self.master,
          objects.MigrationStatus(**kwargs)
      )

  def _execPostcopyMigration(self):
    self.__status = 'active'

    def change_status(*args, **kwargs):
      self.__status = 'postcopy-active'
      return mock.DEFAULT

    def migration_statuses(*args, **kwargs):
      yield self._buildMigrationStatusResponse(status=self.__status,
                                               dirty_sync_count='1')
      for i in range(3):
        yield self._buildMigrationStatusResponse(status=self.__status,
                                                 dirty_sync_count='2')

      yield self._buildMigrationStatusResponse(status='completed',
                                               dirty_sync_count='2')

    self.rpc.call_instance_get_migration_status.side_effect = \
        migration_statuses()
    self.rpc.call_instance_start_postcopy.side_effect = change_status

    op = self.CopyOpCode(self.op)
    self.ExecOpCode(op)

    self._ResetRPC()

  def testPostcopyMigration(self):
    self.inst.hypervisor = 'kvm'
    self.inst.hvparams['migration_caps'] = 'postcopy-ram'

    self._execPostcopyMigration()

    self.assertTrue(self.__status == 'postcopy-active',
                    'Not in postcopy mode after op executed')

    self.inst = self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                                        admin_state=constants.ADMINST_UP,
                                        secondary_node=self.snode)


  def testPostcopyMigrationWithDefaultHVParams(self):
    self.inst.hypervisor = 'kvm'
    self.cluster.hvparams['kvm']['migration_caps'] = 'postcopy-ram'

    self._execPostcopyMigration()

    self.assertTrue(self.__status == 'postcopy-active',
                    'Not in postcopy mode after op executed')

    self.inst = self.cfg.AddNewInstance(disk_template=constants.DT_DRBD8,
                                        admin_state=constants.ADMINST_UP,
                                        secondary_node=self.snode)

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
        .CreateSuccessfulNodeResult(self.snode,
                                    ("/dev/mock", "/var/mock", None))
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
      op, "Instances with disk types drbd cannot be failed over to"
          " arbitrary nodes")

  def testMigration(self):
    op = self.CopyOpCode(self.op)
    self.ExecOpCode(op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
