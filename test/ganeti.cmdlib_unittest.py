#!/usr/bin/python
#

# Copyright (C) 2008 Google Inc.
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

from ganeti import constants
from ganeti import mcpu
from ganeti import cmdlib
from ganeti import opcodes
from ganeti import errors
from ganeti import utils
from ganeti import luxi
from ganeti import ht
from ganeti import objects

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
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    # Try to load non-certificate file
    invalid_cert = self._TestDataFilename("bdev-net.txt")
    (errcode, msg) = cmdlib._VerifyCertificate(invalid_cert)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)


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

    class TestOpcode(opcodes.OpCode):
      OP_ID = "OP_TEST"
      OP_PARAMS = [
        ("iallocator", None, ht.NoType),
        ("node", None, ht.NoType),
        ]

    default_iallocator = mocks.FakeConfig().GetDefaultIAllocator()
    other_iallocator = default_iallocator + "_not"

    op = TestOpcode()
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


class TestLUTestJobqueue(unittest.TestCase):
  def test(self):
    self.assert_(cmdlib.LUTestJobqueue._CLIENT_CONNECT_TIMEOUT <
                 (luxi.WFJC_TIMEOUT * 0.75),
                 msg=("Client timeout too high, might not notice bugs"
                      " in WaitForJobChange"))


class TestLUQuery(unittest.TestCase):
  def test(self):
    self.assertEqual(sorted(cmdlib._QUERY_IMPL.keys()),
                     sorted(constants.QR_OP_QUERY))

    assert constants.QR_NODE in constants.QR_OP_QUERY
    assert constants.QR_INSTANCE in constants.QR_OP_QUERY

    for i in constants.QR_OP_QUERY:
      self.assert_(cmdlib._GetQueryImplementation(i))

    self.assertRaises(errors.OpPrereqError, cmdlib._GetQueryImplementation, "")
    self.assertRaises(errors.OpPrereqError, cmdlib._GetQueryImplementation,
                      "xyz")


class TestLUAssignGroupNodes(unittest.TestCase):

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
      cmdlib.LUAssignGroupNodes.CheckAssignmentForSplitInstances([],
                                                                 node_data,
                                                                 instance_data)

    self.assertEqual([], new)
    self.assertEqual(set(["inst3b", "inst3c"]), set(prev))

    # And now some changes.
    (new, prev) = \
      cmdlib.LUAssignGroupNodes.CheckAssignmentForSplitInstances([("n1b",
                                                                   "g3")],
                                                                 node_data,
                                                                 instance_data)

    self.assertEqual(set(["inst1a", "inst1b"]), set(new))
    self.assertEqual(set(["inst3c"]), set(prev))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
