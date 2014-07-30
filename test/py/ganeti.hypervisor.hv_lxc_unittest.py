#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.hypervisor.hv_lxc"""

import unittest

from ganeti import constants
from ganeti import objects
from ganeti import hypervisor
from ganeti import utils

from ganeti.hypervisor import hv_base
from ganeti.hypervisor import hv_lxc
from ganeti.hypervisor.hv_lxc import LXCHypervisor

import mock
import shutil
import tempfile
import testutils
from testutils import patch_object


def setUpModule():
  # Creating instance of LXCHypervisor will fail by permission issue of
  # instance directories
  global temp_dir
  temp_dir = tempfile.mkdtemp()
  LXCHypervisor._ROOT_DIR = utils.PathJoin(temp_dir, "root")
  LXCHypervisor._LOG_DIR = utils.PathJoin(temp_dir, "log")


def tearDownModule():
  shutil.rmtree(temp_dir)


def RunResultOk(stdout):
  return utils.RunResult(0, None, stdout, "", [], None, None)


class TestConsole(unittest.TestCase):
  def test(self):
    instance = objects.Instance(name="lxc.example.com",
                                primary_node="node199-uuid")
    node = objects.Node(name="node199", uuid="node199-uuid",
                        ndparams={})
    group = objects.NodeGroup(name="group991", ndparams={})
    cons = hv_lxc.LXCHypervisor.GetInstanceConsole(instance, node, group,
                                                   {}, {})
    self.assertEqual(cons.Validate(), None)
    self.assertEqual(cons.kind, constants.CONS_SSH)
    self.assertEqual(cons.host, node.name)
    self.assertEqual(cons.command[-1], instance.name)


class TestLXCIsInstanceAlive(unittest.TestCase):
  @patch_object(utils, "RunCmd")
  def testActive(self, runcmd_mock):
    runcmd_mock.return_value = RunResultOk("inst1 inst2 inst3\ninst4 inst5")
    self.assertTrue(LXCHypervisor._IsInstanceAlive("inst4"))

  @patch_object(utils, "RunCmd")
  def testInactive(self, runcmd_mock):
    runcmd_mock.return_value = RunResultOk("inst1 inst2foo")
    self.assertFalse(LXCHypervisor._IsInstanceAlive("inst2"))


class TestLXCHypervisorGetInstanceInfo(unittest.TestCase):
  def setUp(self):
    self.hv = LXCHypervisor()
    self.hv._GetCgroupCpuList = mock.Mock(return_value=[1, 3])
    self.hv._GetCgroupMemoryLimit = mock.Mock(return_value=128*(1024**2))

  @patch_object(LXCHypervisor, "_IsInstanceAlive")
  def testRunningInstance(self, isalive_mock):
    isalive_mock.return_value = True
    self.assertEqual(self.hv.GetInstanceInfo("inst1"),
                     ("inst1", 0, 128, 2, hv_base.HvInstanceState.RUNNING, 0))

  @patch_object(LXCHypervisor, "_IsInstanceAlive")
  def testInactiveOrNonexistentInstance(self, isalive_mock):
    isalive_mock.return_value = False
    self.assertIsNone(self.hv.GetInstanceInfo("inst1"))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
