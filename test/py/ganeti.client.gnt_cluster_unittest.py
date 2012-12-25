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


"""Script for testing ganeti.client.gnt_cluster"""

import unittest
import optparse

from ganeti.client import gnt_cluster
from ganeti import utils
from ganeti import compat
from ganeti import constants

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
    defaults = dict(cl=NotImplemented, _on_fn=NotImplemented,
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

      result = self._Test(opts, [], cl=client, _off_fn=off_fn,
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

      result = self._Test(opts, [], cl=client, _on_fn=_On,
                          _confirm_fn=self._ConfirmForce)
      self.assertEqual(result, self._ON_EXITCODE)

  def testMasterWithoutShowAll(self):
    opts = optparse.Values(dict(groups=False, show_all=False,
                                force=True, on=False))
    client = _ClientForEpo(NotImplemented, [
      ("node1.example.com", True, [], [], True, False),
      ])
    result = self._Test(opts, [], cl=client, _confirm_fn=self._ConfirmForce)
    self.assertEqual(result, constants.EXIT_FAILURE)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
