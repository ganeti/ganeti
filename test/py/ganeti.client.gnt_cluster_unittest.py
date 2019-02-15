#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.client.gnt_cluster"""

import unittest
import optparse
import os
import shutil
import tempfile

from ganeti import errors
from ganeti.client import gnt_cluster
from ganeti import utils
from ganeti import compat
from ganeti import constants
from ganeti import ssh
from ganeti import cli

import mock
import testutils


class TestEpoUtilities(unittest.TestCase):
  def setUp(self):
    self.nodes2ip = dict(("node%s" % i, "192.0.2.%s" % i) for i in range(1, 10))
    self.nodes = set(self.nodes2ip.keys())
    self.ips2node = dict((v, k) for (k, v) in self.nodes2ip.items())

  def _FakeAction(*args):
    return True

  def _FakePing(ip, port, live_port_needed=False):
    self.assert_(live_port_needed)
    self.assertEqual(port, 0)
    return True

  def _FakeSleep(secs):
    self.assert_(secs >= 0 and secs <= 5)
    return

  def _NoopFeedback(self, text):
    return

  def testPingFnRemoveHostsUp(self):
    seen = set()
    def _FakeSeenPing(ip, *args, **kwargs):
      node = self.ips2node[ip]
      self.assertFalse(node in seen)
      seen.add(node)
      return True

    helper = gnt_cluster._RunWhenNodesReachableHelper(self.nodes,
                                                      self._FakeAction,
                                                      self.nodes2ip, 0,
                                                      self._NoopFeedback,
                                                      _ping_fn=_FakeSeenPing,
                                                      _sleep_fn=self._FakeSleep)

    nodes_len = len(self.nodes)
    for (num, _) in enumerate(self.nodes):
      helper.Wait(5)
      if num < nodes_len - 1:
        self.assertRaises(utils.RetryAgain, helper)
      else:
        helper()

    self.assertEqual(seen, self.nodes)
    self.assertFalse(helper.down)
    self.assertEqual(helper.up, self.nodes)

  def testActionReturnFalseSetsHelperFalse(self):
    called = False
    def _FalseAction(*args):
      return called

    helper = gnt_cluster._RunWhenNodesReachableHelper(self.nodes, _FalseAction,
                                                      self.nodes2ip, 0,
                                                      self._NoopFeedback,
                                                      _ping_fn=self._FakePing,
                                                      _sleep_fn=self._FakeSleep)
    for _ in self.nodes:
      try:
        helper()
      except utils.RetryAgain:
        called = True

    self.assertFalse(helper.success)

  def testMaybeInstanceStartup(self):
    instances_arg = []
    def _FakeInstanceStart(opts, instances, start):
      instances_arg.append(set(instances))
      return None

    inst_map = {
      "inst1": set(["node1", "node2"]),
      "inst2": set(["node1", "node3"]),
      "inst3": set(["node2", "node1"]),
      "inst4": set(["node2", "node1", "node3"]),
      "inst5": set(["node4"]),
      }

    fn = _FakeInstanceStart
    self.assert_(gnt_cluster._MaybeInstanceStartup(None, inst_map, set(),
                                                   _instance_start_fn=fn))
    self.assertFalse(instances_arg)
    result = gnt_cluster._MaybeInstanceStartup(None, inst_map, set(["node1"]),
                                               _instance_start_fn=fn)
    self.assert_(result)
    self.assertFalse(instances_arg)
    result = gnt_cluster._MaybeInstanceStartup(None, inst_map,
                                               set(["node1", "node3"]),
                                               _instance_start_fn=fn)
    self.assert_(result is None)
    self.assertEqual(instances_arg.pop(0), set(["inst2"]))
    self.assertFalse("inst2" in inst_map)
    result = gnt_cluster._MaybeInstanceStartup(None, inst_map,
                                               set(["node1", "node3"]),
                                               _instance_start_fn=fn)
    self.assert_(result)
    self.assertFalse(instances_arg)
    result = gnt_cluster._MaybeInstanceStartup(None, inst_map,
                                               set(["node1", "node3", "node2"]),
                                               _instance_start_fn=fn)
    self.assertEqual(instances_arg.pop(0), set(["inst1", "inst3", "inst4"]))
    self.assert_(result is None)
    result = gnt_cluster._MaybeInstanceStartup(None, inst_map,
                                               set(["node1", "node3", "node2",
                                                    "node4"]),
                                               _instance_start_fn=fn)
    self.assert_(result is None)
    self.assertEqual(instances_arg.pop(0), set(["inst5"]))
    self.assertFalse(inst_map)


class _ClientForEpo:
  def __init__(self, groups, nodes):
    self._groups = groups
    self._nodes = nodes

  def QueryGroups(self, names, fields, use_locking):
    assert not use_locking
    assert fields == ["node_list"]
    return self._groups

  def QueryNodes(self, names, fields, use_locking):
    assert not use_locking
    assert fields == ["name", "master", "pinst_list", "sinst_list", "powered",
                      "offline"]
    return self._nodes


class TestEpo(unittest.TestCase):
  _ON_EXITCODE = 253
  _OFF_EXITCODE = 254

  def _ConfirmForce(self, *args):
    self.fail("Shouldn't need confirmation")

  def _Confirm(self, exp_names, result, names, ltype, text):
    self.assertEqual(names, exp_names)
    self.assertFalse(result is NotImplemented)
    return result

  def _Off(self, exp_node_list, opts, node_list, inst_map):
    self.assertEqual(node_list, exp_node_list)
    self.assertFalse(inst_map)
    return self._OFF_EXITCODE

  def _Test(self, *args, **kwargs):
    defaults = dict(qcl=NotImplemented, _on_fn=NotImplemented,
                    _off_fn=NotImplemented,
                    _stdout_fn=lambda *args: None,
                    _stderr_fn=lambda *args: None)
    defaults.update(kwargs)
    return gnt_cluster.Epo(*args, **defaults)

  def testShowAllWithGroups(self):
    opts = optparse.Values(dict(groups=True, show_all=True))
    result = self._Test(opts, NotImplemented)
    self.assertEqual(result, constants.EXIT_FAILURE)

  def testShowAllWithArgs(self):
    opts = optparse.Values(dict(groups=False, show_all=True))
    result = self._Test(opts, ["a", "b", "c"])
    self.assertEqual(result, constants.EXIT_FAILURE)

  def testNoArgumentsNoParameters(self):
    for (force, confirm_result) in [(True, NotImplemented), (False, False),
                                    (False, True)]:
      opts = optparse.Values(dict(groups=False, show_all=False, force=force,
                                  on=False))
      client = _ClientForEpo(NotImplemented, [
        ("node1.example.com", False, [], [], True, False),
        ])

      if force:
        confirm_fn = self._ConfirmForce
      else:
        confirm_fn = compat.partial(self._Confirm, ["node1.example.com"],
                                    confirm_result)

      off_fn = compat.partial(self._Off, ["node1.example.com"])

      result = self._Test(opts, [], qcl=client, _off_fn=off_fn,
                          _confirm_fn=confirm_fn)
      if force or confirm_result:
        self.assertEqual(result, self._OFF_EXITCODE)
      else:
        self.assertEqual(result, constants.EXIT_FAILURE)

  def testPowerOn(self):
    for master in [False, True]:
      opts = optparse.Values(dict(groups=False, show_all=True,
                                  force=True, on=True))
      client = _ClientForEpo(NotImplemented, [
        ("node1.example.com", False, [], [], True, False),
        ("node2.example.com", False, [], [], False, False),
        ("node3.example.com", False, [], [], True, True),
        ("node4.example.com", False, [], [], None, True),
        ("node5.example.com", master, [], [], False, False),
        ])

      def _On(_, all_nodes, node_list, inst_map):
        self.assertEqual(all_nodes,
                         ["node%s.example.com" % i for i in range(1, 6)])
        if master:
          self.assertEqual(node_list, ["node2.example.com"])
        else:
          self.assertEqual(node_list, ["node2.example.com",
                                       "node5.example.com"])
        self.assertFalse(inst_map)
        return self._ON_EXITCODE

      result = self._Test(opts, [], qcl=client, _on_fn=_On,
                          _confirm_fn=self._ConfirmForce)
      self.assertEqual(result, self._ON_EXITCODE)

  def testMasterWithoutShowAll(self):
    opts = optparse.Values(dict(groups=False, show_all=False,
                                force=True, on=False))
    client = _ClientForEpo(NotImplemented, [
      ("node1.example.com", True, [], [], True, False),
      ])
    result = self._Test(opts, [], qcl=client, _confirm_fn=self._ConfirmForce)
    self.assertEqual(result, constants.EXIT_FAILURE)


class DrbdHelperTestCase(unittest.TestCase):

  def setUp(self):
    unittest.TestCase.setUp(self)
    self.enabled_disk_templates = []

  def enableDrbd(self):
    self.enabled_disk_templates = [constants.DT_DRBD8]

  def disableDrbd(self):
    self.enabled_disk_templates = [constants.DT_DISKLESS]


class InitDrbdHelper(DrbdHelperTestCase):

  def testNoDrbdNoHelper(self):
    opts = mock.Mock()
    opts.drbd_helper = None
    self.disableDrbd()
    helper = gnt_cluster._InitDrbdHelper(opts, self.enabled_disk_templates,
                                         feedback_fn=mock.Mock())
    self.assertEquals(None, helper)

  def testNoDrbdHelper(self):
    opts = mock.Mock()
    self.disableDrbd()
    opts.drbd_helper = "/bin/true"
    helper = gnt_cluster._InitDrbdHelper(opts, self.enabled_disk_templates,
                                         feedback_fn=mock.Mock())
    self.assertEquals(opts.drbd_helper, helper)

  def testDrbdHelperNone(self):
    opts = mock.Mock()
    self.enableDrbd()
    opts.drbd_helper = None
    helper = gnt_cluster._InitDrbdHelper(opts, self.enabled_disk_templates,
                                         feedback_fn=mock.Mock())
    self.assertEquals(constants.DEFAULT_DRBD_HELPER, helper)

  def testDrbdHelperEmpty(self):
    opts = mock.Mock()
    self.enableDrbd()
    opts.drbd_helper = ''
    self.assertRaises(errors.OpPrereqError, gnt_cluster._InitDrbdHelper, opts,
        self.enabled_disk_templates, feedback_fn=mock.Mock())

  def testDrbdHelper(self):
    opts = mock.Mock()
    self.enableDrbd()
    opts.drbd_helper = "/bin/true"
    helper = gnt_cluster._InitDrbdHelper(opts, self.enabled_disk_templates,
                                         feedback_fn=mock.Mock())
    self.assertEquals(opts.drbd_helper, helper)


class GetDrbdHelper(DrbdHelperTestCase):

  def testNoDrbdNoHelper(self):
    opts = mock.Mock()
    self.disableDrbd()
    opts.drbd_helper = None
    helper = gnt_cluster._GetDrbdHelper(opts, self.enabled_disk_templates)
    self.assertEquals(None, helper)

  def testNoTemplateInfoNoHelper(self):
    opts = mock.Mock()
    opts.drbd_helper = None
    helper = gnt_cluster._GetDrbdHelper(opts, None)
    self.assertEquals(None, helper)

  def testNoTemplateInfoHelper(self):
    opts = mock.Mock()
    opts.drbd_helper = "/bin/true"
    helper = gnt_cluster._GetDrbdHelper(opts, None)
    self.assertEquals(opts.drbd_helper, helper)

  def testNoDrbdHelper(self):
    opts = mock.Mock()
    self.disableDrbd()
    opts.drbd_helper = "/bin/true"
    helper = gnt_cluster._GetDrbdHelper(opts, None)
    self.assertEquals(opts.drbd_helper, helper)

  def testDrbdNoHelper(self):
    opts = mock.Mock()
    self.enableDrbd()
    opts.drbd_helper = None
    helper = gnt_cluster._GetDrbdHelper(opts, self.enabled_disk_templates)
    self.assertEquals(None, helper)

  def testDrbdHelper(self):
    opts = mock.Mock()
    self.enableDrbd()
    opts.drbd_helper = "/bin/true"
    helper = gnt_cluster._GetDrbdHelper(opts, self.enabled_disk_templates)
    self.assertEquals(opts.drbd_helper, helper)


class TestBuildGanetiPubKeys(testutils.GanetiTestCase):

  _SOME_KEY_DICT = {"rsa": "key_rsa",
                    "dsa": "key_dsa"}
  _MASTER_NODE_NAME = "master_node"
  _MASTER_NODE_UUID = "master_uuid"
  _NUM_NODES = 2 # excluding master node
  _ONLINE_NODE_NAMES = ["node%s_name" % i for i in range(_NUM_NODES)]
  _ONLINE_NODE_UUIDS = ["node%s_uuid" % i for i in range(_NUM_NODES)]
  _CLUSTER_NAME = "cluster_name"
  _PRIV_KEY = "master_private_key"
  _PUB_KEY = "master_public_key"
  _MODIFY_SSH_SETUP = True
  _AUTH_KEYS = "a\nb\nc"
  _SSH_KEY_TYPE = "dsa"

  def _setUpFakeKeys(self):
    os.makedirs(os.path.join(self.tmpdir, ".ssh"))

    for key_type in ["rsa", "dsa"]:
      self.priv_filename = os.path.join(self.tmpdir, ".ssh", "id_%s" % key_type)
      utils.WriteFile(self.priv_filename, data=self._PRIV_KEY)

      self.pub_filename = os.path.join(
        self.tmpdir, ".ssh", "id_%s.pub" % key_type)
      utils.WriteFile(self.pub_filename, data=self._PUB_KEY)

    self.auth_filename = os.path.join(self.tmpdir, ".ssh", "authorized_keys")
    utils.WriteFile(self.auth_filename, data=self._AUTH_KEYS)

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()
    self.pub_key_filename = os.path.join(self.tmpdir, "ganeti_test_pub_keys")
    self._setUpFakeKeys()

    self._ssh_read_remote_ssh_pub_keys_patcher = testutils \
      .patch_object(ssh, "ReadRemoteSshPubKeys")
    self._ssh_read_remote_ssh_pub_keys_mock = \
      self._ssh_read_remote_ssh_pub_keys_patcher.start()
    self._ssh_read_remote_ssh_pub_keys_mock.return_value = self._SOME_KEY_DICT

    self.mock_cl = mock.Mock()
    self.mock_cl.QueryConfigValues = mock.Mock()
    self.mock_cl.QueryConfigValues.return_value = \
      (self._CLUSTER_NAME, self._MASTER_NODE_NAME, self._MODIFY_SSH_SETUP,
       self._SSH_KEY_TYPE)

    self._get_online_nodes_mock = mock.Mock()
    self._get_online_nodes_mock.return_value = \
      self._ONLINE_NODE_NAMES

    self._get_nodes_ssh_ports_mock = mock.Mock()
    self._get_nodes_ssh_ports_mock.return_value = \
      [22 for i in range(self._NUM_NODES + 1)]

    self._get_node_uuids_mock = mock.Mock()
    self._get_node_uuids_mock.return_value = \
      self._ONLINE_NODE_UUIDS + [self._MASTER_NODE_UUID]

    self._options = mock.Mock()
    self._options.ssh_key_check = False

  def _GetTempHomedir(self, _):
    return self.tmpdir

  def tearDown(self):
    super(testutils.GanetiTestCase, self).tearDown()
    shutil.rmtree(self.tmpdir)
    self._ssh_read_remote_ssh_pub_keys_patcher.stop()

  def testNewPubKeyFile(self):
    gnt_cluster._BuildGanetiPubKeys(
      self._options,
      pub_key_file=self.pub_key_filename,
      cl=self.mock_cl,
      get_online_nodes_fn=self._get_online_nodes_mock,
      get_nodes_ssh_ports_fn=self._get_nodes_ssh_ports_mock,
      get_node_uuids_fn=self._get_node_uuids_mock,
      homedir_fn=self._GetTempHomedir)
    key_file_result = utils.ReadFile(self.pub_key_filename)
    for node_uuid in self._ONLINE_NODE_UUIDS + [self._MASTER_NODE_UUID]:
      self.assertTrue(node_uuid in key_file_result)
    self.assertTrue(self._PUB_KEY in key_file_result)

  def testOverridePubKeyFile(self):
    fd = open(self.pub_key_filename, "w")
    fd.write("Pink Bunny")
    fd.close()
    gnt_cluster._BuildGanetiPubKeys(
      self._options,
      pub_key_file=self.pub_key_filename,
      cl=self.mock_cl,
      get_online_nodes_fn=self._get_online_nodes_mock,
      get_nodes_ssh_ports_fn=self._get_nodes_ssh_ports_mock,
      get_node_uuids_fn=self._get_node_uuids_mock,
      homedir_fn=self._GetTempHomedir)
    self.assertFalse("Pink Bunny" in self.pub_key_filename)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
