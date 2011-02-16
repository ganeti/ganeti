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

from ganeti.client import gnt_cluster
from ganeti import utils
from ganeti import compat

import testutils


class TestEpo(unittest.TestCase):
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

  def testPingFnRemoveHostsUp(self):
    seen = set()
    def _FakeSeenPing(ip, *args, **kwargs):
      node = self.ips2node[ip]
      self.assertFalse(node in seen)
      seen.add(node)
      return True

    helper = gnt_cluster._RunWhenNodesReachableHelper(self.nodes,
                                                      self._FakeAction,
                                                      self.nodes2ip, port=0,
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
                                                      self.nodes2ip, port=0,
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
