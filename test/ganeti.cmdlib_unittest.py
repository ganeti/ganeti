#!/usr/bin/python
#

# Copyright (C) 2008, 2011 Google Inc.
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
# 0.0510-1301, USA.


"""Script for unittesting the cmdlib module"""


import os
import unittest
import time
import tempfile
import shutil
import operator

from ganeti import constants
from ganeti import mcpu
from ganeti import cmdlib
from ganeti import opcodes
from ganeti import errors
from ganeti import utils
from ganeti import luxi
from ganeti import ht
from ganeti import objects
from ganeti import compat
from ganeti import rpc

import testutils
import mocks


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    cmdlib._VerifyCertificate(self._TestDataFilename("cert1.pem"))

    nonexist_filename = os.path.join(self.tmpdir, "does-not-exist")

    (errcode, msg) = cmdlib._VerifyCertificate(nonexist_filename)
    self.assertEqual(errcode, cmdlib.LUClusterVerifyConfig.ETYPE_ERROR)

    # Try to load non-certificate file
    invalid_cert = self._TestDataFilename("bdev-net.txt")
    (errcode, msg) = cmdlib._VerifyCertificate(invalid_cert)
    self.assertEqual(errcode, cmdlib.LUClusterVerifyConfig.ETYPE_ERROR)


class TestOpcodeParams(testutils.GanetiTestCase):
  def testParamsStructures(self):
    for op in sorted(mcpu.Processor.DISPATCH_TABLE):
      lu = mcpu.Processor.DISPATCH_TABLE[op]
      lu_name = lu.__name__
      self.failIf(hasattr(lu, "_OP_REQP"),
                  msg=("LU '%s' has old-style _OP_REQP" % lu_name))
      self.failIf(hasattr(lu, "_OP_DEFS"),
                  msg=("LU '%s' has old-style _OP_DEFS" % lu_name))
      self.failIf(hasattr(lu, "_OP_PARAMS"),
                  msg=("LU '%s' has old-style _OP_PARAMS" % lu_name))


class TestIAllocatorChecks(testutils.GanetiTestCase):
  def testFunction(self):
    class TestLU(object):
      def __init__(self, opcode):
        self.cfg = mocks.FakeConfig()
        self.op = opcode

    class OpTest(opcodes.OpCode):
       OP_PARAMS = [
        ("iallocator", None, ht.NoType, None),
        ("node", None, ht.NoType, None),
        ]

    default_iallocator = mocks.FakeConfig().GetDefaultIAllocator()
    other_iallocator = default_iallocator + "_not"

    op = OpTest()
    lu = TestLU(op)

    c_i = lambda: cmdlib._CheckIAllocatorOrNode(lu, "iallocator", "node")

    # Neither node nor iallocator given
    op.iallocator = None
    op.node = None
    c_i()
    self.assertEqual(lu.op.iallocator, default_iallocator)
    self.assertEqual(lu.op.node, None)

    # Both, iallocator and node given
    op.iallocator = "test"
    op.node = "test"
    self.assertRaises(errors.OpPrereqError, c_i)

    # Only iallocator given
    op.iallocator = other_iallocator
    op.node = None
    c_i()
    self.assertEqual(lu.op.iallocator, other_iallocator)
    self.assertEqual(lu.op.node, None)

    # Only node given
    op.iallocator = None
    op.node = "node"
    c_i()
    self.assertEqual(lu.op.iallocator, None)
    self.assertEqual(lu.op.node, "node")

    # No node, iallocator or default iallocator
    op.iallocator = None
    op.node = None
    lu.cfg.GetDefaultIAllocator = lambda: None
    self.assertRaises(errors.OpPrereqError, c_i)


class TestLUTestJqueue(unittest.TestCase):
  def test(self):
    self.assert_(cmdlib.LUTestJqueue._CLIENT_CONNECT_TIMEOUT <
                 (luxi.WFJC_TIMEOUT * 0.75),
                 msg=("Client timeout too high, might not notice bugs"
                      " in WaitForJobChange"))


class TestLUQuery(unittest.TestCase):
  def test(self):
    self.assertEqual(sorted(cmdlib._QUERY_IMPL.keys()),
                     sorted(constants.QR_VIA_OP))

    assert constants.QR_NODE in constants.QR_VIA_OP
    assert constants.QR_INSTANCE in constants.QR_VIA_OP

    for i in constants.QR_VIA_OP:
      self.assert_(cmdlib._GetQueryImplementation(i))

    self.assertRaises(errors.OpPrereqError, cmdlib._GetQueryImplementation, "")
    self.assertRaises(errors.OpPrereqError, cmdlib._GetQueryImplementation,
                      "xyz")


class TestLUGroupAssignNodes(unittest.TestCase):

  def testCheckAssignmentForSplitInstances(self):
    node_data = dict((name, objects.Node(name=name, group=group))
                     for (name, group) in [("n1a", "g1"), ("n1b", "g1"),
                                           ("n2a", "g2"), ("n2b", "g2"),
                                           ("n3a", "g3"), ("n3b", "g3"),
                                           ("n3c", "g3"),
                                           ])

    def Instance(name, pnode, snode):
      if snode is None:
        disks = []
        disk_template = constants.DT_DISKLESS
      else:
        disks = [objects.Disk(dev_type=constants.LD_DRBD8,
                              logical_id=[pnode, snode, 1, 17, 17])]
        disk_template = constants.DT_DRBD8

      return objects.Instance(name=name, primary_node=pnode, disks=disks,
                              disk_template=disk_template)

    instance_data = dict((name, Instance(name, pnode, snode))
                         for name, pnode, snode in [("inst1a", "n1a", "n1b"),
                                                    ("inst1b", "n1b", "n1a"),
                                                    ("inst2a", "n2a", "n2b"),
                                                    ("inst3a", "n3a", None),
                                                    ("inst3b", "n3b", "n1b"),
                                                    ("inst3c", "n3b", "n2b"),
                                                    ])

    # Test first with the existing state.
    (new, prev) = \
      cmdlib.LUGroupAssignNodes.CheckAssignmentForSplitInstances([],
                                                                 node_data,
                                                                 instance_data)

    self.assertEqual([], new)
    self.assertEqual(set(["inst3b", "inst3c"]), set(prev))

    # And now some changes.
    (new, prev) = \
      cmdlib.LUGroupAssignNodes.CheckAssignmentForSplitInstances([("n1b",
                                                                   "g3")],
                                                                 node_data,
                                                                 instance_data)

    self.assertEqual(set(["inst1a", "inst1b"]), set(new))
    self.assertEqual(set(["inst3c"]), set(prev))


class TestClusterVerifySsh(unittest.TestCase):
  def testMultipleGroups(self):
    fn = cmdlib.LUClusterVerifyGroup._SelectSshCheckNodes
    mygroupnodes = [
      objects.Node(name="node20", group="my", offline=False),
      objects.Node(name="node21", group="my", offline=False),
      objects.Node(name="node22", group="my", offline=False),
      objects.Node(name="node23", group="my", offline=False),
      objects.Node(name="node24", group="my", offline=False),
      objects.Node(name="node25", group="my", offline=False),
      objects.Node(name="node26", group="my", offline=True),
      ]
    nodes = [
      objects.Node(name="node1", group="g1", offline=True),
      objects.Node(name="node2", group="g1", offline=False),
      objects.Node(name="node3", group="g1", offline=False),
      objects.Node(name="node4", group="g1", offline=True),
      objects.Node(name="node5", group="g1", offline=False),
      objects.Node(name="node10", group="xyz", offline=False),
      objects.Node(name="node11", group="xyz", offline=False),
      objects.Node(name="node40", group="alloff", offline=True),
      objects.Node(name="node41", group="alloff", offline=True),
      objects.Node(name="node50", group="aaa", offline=False),
      ] + mygroupnodes
    assert not utils.FindDuplicates(map(operator.attrgetter("name"), nodes))

    (online, perhost) = fn(mygroupnodes, "my", nodes)
    self.assertEqual(online, ["node%s" % i for i in range(20, 26)])
    self.assertEqual(set(perhost.keys()), set(online))

    self.assertEqual(perhost, {
      "node20": ["node10", "node2", "node50"],
      "node21": ["node11", "node3", "node50"],
      "node22": ["node10", "node5", "node50"],
      "node23": ["node11", "node2", "node50"],
      "node24": ["node10", "node3", "node50"],
      "node25": ["node11", "node5", "node50"],
      })

  def testSingleGroup(self):
    fn = cmdlib.LUClusterVerifyGroup._SelectSshCheckNodes
    nodes = [
      objects.Node(name="node1", group="default", offline=True),
      objects.Node(name="node2", group="default", offline=False),
      objects.Node(name="node3", group="default", offline=False),
      objects.Node(name="node4", group="default", offline=True),
      ]
    assert not utils.FindDuplicates(map(operator.attrgetter("name"), nodes))

    (online, perhost) = fn(nodes, "default", nodes)
    self.assertEqual(online, ["node2", "node3"])
    self.assertEqual(set(perhost.keys()), set(online))

    self.assertEqual(perhost, {
      "node2": [],
      "node3": [],
      })


class TestClusterVerifyFiles(unittest.TestCase):
  @staticmethod
  def _FakeErrorIf(errors, cond, ecode, item, msg, *args, **kwargs):
    assert ((ecode == cmdlib.LUClusterVerifyGroup.ENODEFILECHECK and
             ht.TNonEmptyString(item)) or
            (ecode == cmdlib.LUClusterVerifyGroup.ECLUSTERFILECHECK and
             item is None))

    if args:
      msg = msg % args

    if cond:
      errors.append((item, msg))

  _VerifyFiles = cmdlib.LUClusterVerifyGroup._VerifyFiles

  def test(self):
    errors = []
    master_name = "master.example.com"
    nodeinfo = [
      objects.Node(name=master_name, offline=False),
      objects.Node(name="node2.example.com", offline=False),
      objects.Node(name="node3.example.com", master_candidate=True),
      objects.Node(name="node4.example.com", offline=False),
      objects.Node(name="nodata.example.com"),
      objects.Node(name="offline.example.com", offline=True),
      ]
    cluster = objects.Cluster(modify_etc_hosts=True,
                              enabled_hypervisors=[constants.HT_XEN_HVM])
    files_all = set([
      constants.CLUSTER_DOMAIN_SECRET_FILE,
      constants.RAPI_CERT_FILE,
      ])
    files_all_opt = set([
      constants.RAPI_USERS_FILE,
      ])
    files_mc = set([
      constants.CLUSTER_CONF_FILE,
      ])
    files_vm = set()
    nvinfo = {
      master_name: rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          constants.CLUSTER_CONF_FILE: "82314f897f38b35f9dab2f7c6b1593e0",
          constants.RAPI_CERT_FILE: "babbce8f387bc082228e544a2146fee4",
          constants.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
        }})),
      "node2.example.com": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          constants.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          }
        })),
      "node3.example.com": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          constants.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          constants.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          }
        })),
      "node4.example.com": rpc.RpcResult(data=(True, {
        constants.NV_FILELIST: {
          constants.RAPI_CERT_FILE: "97f0356500e866387f4b84233848cc4a",
          constants.CLUSTER_CONF_FILE: "conf-a6d4b13e407867f7a7b4f0f232a8f527",
          constants.CLUSTER_DOMAIN_SECRET_FILE: "cds-47b5b3f19202936bb4",
          constants.RAPI_USERS_FILE: "rapiusers-ea3271e8d810ef3",
          }
        })),
      "nodata.example.com": rpc.RpcResult(data=(True, {})),
      "offline.example.com": rpc.RpcResult(offline=True),
      }
    assert set(nvinfo.keys()) == set(map(operator.attrgetter("name"), nodeinfo))

    self._VerifyFiles(compat.partial(self._FakeErrorIf, errors), nodeinfo,
                      master_name, nvinfo,
                      (files_all, files_all_opt, files_mc, files_vm))
    self.assertEqual(sorted(errors), sorted([
      (None, ("File %s found with 2 different checksums (variant 1 on"
              " node2.example.com, node3.example.com, node4.example.com;"
              " variant 2 on master.example.com)" % constants.RAPI_CERT_FILE)),
      (None, ("File %s is missing from node(s) node2.example.com" %
              constants.CLUSTER_DOMAIN_SECRET_FILE)),
      (None, ("File %s should not exist on node(s) node4.example.com" %
              constants.CLUSTER_CONF_FILE)),
      (None, ("File %s is missing from node(s) node3.example.com" %
              constants.CLUSTER_CONF_FILE)),
      (None, ("File %s found with 2 different checksums (variant 1 on"
              " master.example.com; variant 2 on node4.example.com)" %
              constants.CLUSTER_CONF_FILE)),
      (None, ("File %s is optional, but it must exist on all or no nodes (not"
              " found on master.example.com, node2.example.com,"
              " node3.example.com)" % constants.RAPI_USERS_FILE)),
      ("nodata.example.com", "Node did not return file checksum data"),
      ]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
