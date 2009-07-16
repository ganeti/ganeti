#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Script for unittesting the config module"""


import unittest
import os
import time
import tempfile
import os.path
import socket

from ganeti import bootstrap
from ganeti import config
from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import utils


class TestConfigRunner(unittest.TestCase):
  """Testing case for HooksRunner"""
  def setUp(self):
    fd, self.cfg_file = tempfile.mkstemp()
    os.close(fd)
    self._init_cluster(self.cfg_file)

  def tearDown(self):
    try:
      os.unlink(self.cfg_file)
    except OSError:
      pass

  def _get_object(self):
    """Returns a instance of ConfigWriter"""
    cfg = config.ConfigWriter(cfg_file=self.cfg_file, offline=True)
    return cfg

  def _init_cluster(self, cfg):
    """Initializes the cfg object"""
    me = utils.HostInfo()
    ip = constants.LOCALHOST_IP_ADDRESS

    cluster_config = objects.Cluster(
      serial_no=1,
      rsahostkeypub="",
      highest_used_port=(constants.FIRST_DRBD_PORT - 1),
      mac_prefix="aa:00:00",
      volume_group_name="xenvg",
      default_bridge=constants.DEFAULT_BRIDGE,
      tcpudp_port_pool=set(),
      default_hypervisor=constants.HT_FAKE,
      enabled_hypervisors=[constants.HT_FAKE],
      master_node=me.name,
      master_ip="127.0.0.1",
      master_netdev=constants.DEFAULT_BRIDGE,
      cluster_name="cluster.local",
      file_storage_dir="/tmp",
      )

    master_node_config = objects.Node(name=me.name,
                                      primary_ip=me.ip,
                                      secondary_ip=ip,
                                      serial_no=1,
                                      master_candidate=True)

    bootstrap.InitConfig(constants.CONFIG_VERSION,
                         cluster_config, master_node_config, self.cfg_file)

  def _create_instance(self):
    """Create and return an instance object"""
    inst = objects.Instance(name="test.example.com", disks=[], nics=[],
                            disk_template=constants.DT_DISKLESS,
                            primary_node=self._get_object().GetMasterNode())
    return inst

  def testEmpty(self):
    """Test instantiate config object"""
    self._get_object()

  def testInit(self):
    """Test initialize the config file"""
    cfg = self._get_object()
    self.failUnlessEqual(1, len(cfg.GetNodeList()))
    self.failUnlessEqual(0, len(cfg.GetInstanceList()))

  def testUpdateCluster(self):
    """Test updates on the cluster object"""
    cfg = self._get_object()
    # construct a fake cluster object
    fake_cl = objects.Cluster()
    # fail if we didn't read the config
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_cl)

    cl = cfg.GetClusterInfo()
    # first pass, must not fail
    cfg.Update(cl)
    # second pass, also must not fail (after the config has been written)
    cfg.Update(cl)
    # but the fake_cl update should still fail
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_cl)

  def testUpdateNode(self):
    """Test updates on one node object"""
    cfg = self._get_object()
    # construct a fake node
    fake_node = objects.Node()
    # fail if we didn't read the config
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_node)

    node = cfg.GetNodeInfo(cfg.GetNodeList()[0])
    # first pass, must not fail
    cfg.Update(node)
    # second pass, also must not fail (after the config has been written)
    cfg.Update(node)
    # but the fake_node update should still fail
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_node)

  def testUpdateInstance(self):
    """Test updates on one instance object"""
    cfg = self._get_object()
    # construct a fake instance
    inst = self._create_instance()
    fake_instance = objects.Instance()
    # fail if we didn't read the config
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_instance)

    cfg.AddInstance(inst)
    instance = cfg.GetInstanceInfo(cfg.GetInstanceList()[0])
    # first pass, must not fail
    cfg.Update(instance)
    # second pass, also must not fail (after the config has been written)
    cfg.Update(instance)
    # but the fake_instance update should still fail
    self.failUnlessRaises(errors.ConfigurationError, cfg.Update, fake_instance)


if __name__ == '__main__':
  unittest.main()
