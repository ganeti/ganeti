#!/usr/bin/python3
#

# Copyright (C) 2008, 2011, 2012, 2013 Google Inc.
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


"""Script for unittesting the cmdlib module"""


import mock
import unittest
import itertools
import copy

from ganeti import constants
from ganeti import mcpu
from ganeti import cmdlib
from ganeti.cmdlib import cluster
from ganeti.cmdlib.cluster import verify
from ganeti.cmdlib import instance_storage
from ganeti.cmdlib import instance_utils
from ganeti.cmdlib import common
from ganeti.cmdlib import query
from ganeti import opcodes
from ganeti import errors
from ganeti import luxi
from ganeti import ht
from ganeti import objects
from ganeti import locking
from ganeti.masterd import iallocator

import testutils
import mocks


class TestOpcodeParams(testutils.GanetiTestCase):
  def testParamsStructures(self):
    for op in mcpu.Processor.DISPATCH_TABLE:
      lu = mcpu.Processor.DISPATCH_TABLE[op]
      lu_name = lu.__name__
      self.assertFalse(hasattr(lu, "_OP_REQP"),
                  msg=("LU '%s' has old-style _OP_REQP" % lu_name))
      self.assertFalse(hasattr(lu, "_OP_DEFS"),
                  msg=("LU '%s' has old-style _OP_DEFS" % lu_name))
      self.assertFalse(hasattr(lu, "_OP_PARAMS"),
                  msg=("LU '%s' has old-style _OP_PARAMS" % lu_name))


class TestIAllocatorChecks(testutils.GanetiTestCase):
  def testFunction(self):
    class TestLU(object):
      def __init__(self, opcode):
        self.cfg = mocks.FakeConfig()
        self.op = opcode

    class OpTest(opcodes.OpCode):
       OP_PARAMS = [
        ("iallocator", None, ht.TAny, None),
        ("node", None, ht.TAny, None),
        ]

    default_iallocator = mocks.FakeConfig().GetDefaultIAllocator()
    other_iallocator = default_iallocator + "_not"

    op = OpTest()
    lu = TestLU(op)

    c_i = lambda: common.CheckIAllocatorOrNode(lu, "iallocator", "node")

    # Neither node nor iallocator given
    for n in (None, []):
      op.iallocator = None
      op.node = n
      c_i()
      self.assertEqual(lu.op.iallocator, default_iallocator)
      self.assertEqual(lu.op.node, n)

    # Both, iallocator and node given
    for a in ("test", constants.DEFAULT_IALLOCATOR_SHORTCUT):
      op.iallocator = a
      op.node = "test"
      self.assertRaises(errors.OpPrereqError, c_i)

    # Only iallocator given
    for n in (None, []):
      op.iallocator = other_iallocator
      op.node = n
      c_i()
      self.assertEqual(lu.op.iallocator, other_iallocator)
      self.assertEqual(lu.op.node, n)

    # Only node given
    op.iallocator = None
    op.node = "node"
    c_i()
    self.assertEqual(lu.op.iallocator, None)
    self.assertEqual(lu.op.node, "node")

    # Asked for default iallocator, no node given
    op.iallocator = constants.DEFAULT_IALLOCATOR_SHORTCUT
    op.node = None
    c_i()
    self.assertEqual(lu.op.iallocator, default_iallocator)
    self.assertEqual(lu.op.node, None)

    # No node, iallocator or default iallocator
    op.iallocator = None
    op.node = None
    lu.cfg.GetDefaultIAllocator = lambda: None
    self.assertRaises(errors.OpPrereqError, c_i)


class TestLUTestJqueue(unittest.TestCase):
  def test(self):
    self.assertTrue(cmdlib.LUTestJqueue._CLIENT_CONNECT_TIMEOUT <
                 (luxi.WFJC_TIMEOUT * 0.75),
                 msg=("Client timeout too high, might not notice bugs"
                      " in WaitForJobChange"))


class TestLUQuery(unittest.TestCase):
  def test(self):
    self.assertEqual(sorted(query._QUERY_IMPL.keys()),
                     sorted(constants.QR_VIA_OP))

    assert constants.QR_NODE in constants.QR_VIA_LUXI
    assert constants.QR_INSTANCE in constants.QR_VIA_LUXI

    for i in constants.QR_VIA_OP:
      self.assertTrue(query._GetQueryImplementation(i))

    self.assertRaises(errors.OpPrereqError, query._GetQueryImplementation,
                      "")
    self.assertRaises(errors.OpPrereqError, query._GetQueryImplementation,
                      "xyz")


class _FakeLU:
  def __init__(self, cfg=NotImplemented, proc=NotImplemented,
               rpc=NotImplemented):
    self.warning_log = []
    self.info_log = []
    self.cfg = cfg
    self.proc = proc
    self.rpc = rpc

  def LogWarning(self, text, *args):
    self.warning_log.append((text, args))

  def LogInfo(self, text, *args):
    self.info_log.append((text, args))


class TestLoadNodeEvacResult(unittest.TestCase):
  def testSuccess(self):
    for moved in [[], [
      ("inst20153.example.com", "grp2", ["nodeA4509", "nodeB2912"]),
      ]]:
      for early_release in [False, True]:
        for use_nodes in [False, True]:
          jobs = [
            [opcodes.OpInstanceReplaceDisks().__getstate__()],
            [opcodes.OpInstanceMigrate().__getstate__()],
            ]

          alloc_result = (moved, [], jobs)
          assert iallocator._NEVAC_RESULT(alloc_result)

          lu = _FakeLU()
          result = common.LoadNodeEvacResult(lu, alloc_result,
                                             early_release, use_nodes)

          if moved:
            (_, (info_args, )) = lu.info_log.pop(0)
            for (instname, instgroup, instnodes) in moved:
              self.assertTrue(instname in info_args)
              if use_nodes:
                for i in instnodes:
                  self.assertTrue(i in info_args)
              else:
                self.assertTrue(instgroup in info_args)

          self.assertFalse(lu.info_log)
          self.assertFalse(lu.warning_log)

          for op in itertools.chain(*result):
            if hasattr(op.__class__, "early_release"):
              self.assertEqual(op.early_release, early_release)
            else:
              self.assertFalse(hasattr(op, "early_release"))

  def testFailed(self):
    alloc_result = ([], [
      ("inst5191.example.com", "errormsg21178"),
      ], [])
    assert iallocator._NEVAC_RESULT(alloc_result)

    lu = _FakeLU()
    self.assertRaises(errors.OpExecError, common.LoadNodeEvacResult,
                      lu, alloc_result, False, False)
    self.assertFalse(lu.info_log)
    (_, (args, )) = lu.warning_log.pop(0)
    self.assertTrue("inst5191.example.com" in args)
    self.assertTrue("errormsg21178" in args)
    self.assertFalse(lu.warning_log)


class TestUpdateAndVerifySubDict(unittest.TestCase):
  def setUp(self):
    self.type_check = {
        "a": constants.VTYPE_INT,
        "b": constants.VTYPE_STRING,
        "c": constants.VTYPE_BOOL,
        "d": constants.VTYPE_STRING,
        }

  def test(self):
    old_test = {
      "foo": {
        "d": "blubb",
        "a": 321,
        },
      "baz": {
        "a": 678,
        "b": "678",
        "c": True,
        },
      }
    test = {
      "foo": {
        "a": 123,
        "b": "123",
        "c": True,
        },
      "bar": {
        "a": 321,
        "b": "321",
        "c": False,
        },
      }

    mv = {
      "foo": {
        "a": 123,
        "b": "123",
        "c": True,
        "d": "blubb"
        },
      "bar": {
        "a": 321,
        "b": "321",
        "c": False,
        },
      "baz": {
        "a": 678,
        "b": "678",
        "c": True,
        },
      }

    verified = common._UpdateAndVerifySubDict(old_test, test, self.type_check)
    self.assertEqual(verified, mv)

  def testWrong(self):
    test = {
      "foo": {
        "a": "blubb",
        "b": "123",
        "c": True,
        },
      "bar": {
        "a": 321,
        "b": "321",
        "c": False,
        },
      }

    self.assertRaises(errors.TypeEnforcementError,
                      common._UpdateAndVerifySubDict, {}, test,
                      self.type_check)


class TestHvStateHelper(unittest.TestCase):
  def testWithoutOpData(self):
    self.assertEqual(common.MergeAndVerifyHvState(None, NotImplemented),
                     None)

  def testWithoutOldData(self):
    new = {
      constants.HT_XEN_PVM: {
        constants.HVST_MEMORY_TOTAL: 4096,
        },
      }
    self.assertEqual(common.MergeAndVerifyHvState(new, None), new)

  def testWithWrongHv(self):
    new = {
      "i-dont-exist": {
        constants.HVST_MEMORY_TOTAL: 4096,
        },
      }
    self.assertRaises(errors.OpPrereqError, common.MergeAndVerifyHvState,
                      new, None)

class TestDiskStateHelper(unittest.TestCase):
  def testWithoutOpData(self):
    self.assertEqual(common.MergeAndVerifyDiskState(None, NotImplemented),
                     None)

  def testWithoutOldData(self):
    new = {
      constants.DT_PLAIN: {
        "xenvg": {
          constants.DS_DISK_RESERVED: 1024,
          },
        },
      }
    self.assertEqual(common.MergeAndVerifyDiskState(new, None), new)

  def testWithWrongStorageType(self):
    new = {
      "i-dont-exist": {
        "xenvg": {
          constants.DS_DISK_RESERVED: 1024,
          },
        },
      }
    self.assertRaises(errors.OpPrereqError, common.MergeAndVerifyDiskState,
                      new, None)


class TestComputeMinMaxSpec(unittest.TestCase):
  def setUp(self):
    self.ispecs = {
      constants.ISPECS_MAX: {
        constants.ISPEC_MEM_SIZE: 512,
        constants.ISPEC_DISK_SIZE: 1024,
        },
      constants.ISPECS_MIN: {
        constants.ISPEC_MEM_SIZE: 128,
        constants.ISPEC_DISK_COUNT: 1,
        },
      }

  def testNoneValue(self):
    self.assertTrue(common._ComputeMinMaxSpec(constants.ISPEC_MEM_SIZE, None,
                                              self.ispecs, None) is None)

  def testAutoValue(self):
    self.assertTrue(common._ComputeMinMaxSpec(constants.ISPEC_MEM_SIZE, None,
                                              self.ispecs,
                                              constants.VALUE_AUTO) is None)

  def testNotDefined(self):
    self.assertTrue(common._ComputeMinMaxSpec(constants.ISPEC_NIC_COUNT, None,
                                              self.ispecs, 3) is None)

  def testNoMinDefined(self):
    self.assertTrue(common._ComputeMinMaxSpec(constants.ISPEC_DISK_SIZE, None,
                                              self.ispecs, 128) is None)

  def testNoMaxDefined(self):
    self.assertTrue(common._ComputeMinMaxSpec(constants.ISPEC_DISK_COUNT,
                                              None, self.ispecs, 16) is None)

  def testOutOfRange(self):
    for (name, val) in ((constants.ISPEC_MEM_SIZE, 64),
                        (constants.ISPEC_MEM_SIZE, 768),
                        (constants.ISPEC_DISK_SIZE, 4096),
                        (constants.ISPEC_DISK_COUNT, 0)):
      min_v = self.ispecs[constants.ISPECS_MIN].get(name, val)
      max_v = self.ispecs[constants.ISPECS_MAX].get(name, val)
      self.assertEqual(common._ComputeMinMaxSpec(name, None,
                                                 self.ispecs, val),
                       "%s value %s is not in range [%s, %s]" %
                       (name, val,min_v, max_v))
      self.assertEqual(common._ComputeMinMaxSpec(name, "1",
                                                 self.ispecs, val),
                       "%s/1 value %s is not in range [%s, %s]" %
                       (name, val,min_v, max_v))

  def test(self):
    for (name, val) in ((constants.ISPEC_MEM_SIZE, 256),
                        (constants.ISPEC_MEM_SIZE, 128),
                        (constants.ISPEC_MEM_SIZE, 512),
                        (constants.ISPEC_DISK_SIZE, 1024),
                        (constants.ISPEC_DISK_SIZE, 0),
                        (constants.ISPEC_DISK_COUNT, 1),
                        (constants.ISPEC_DISK_COUNT, 5)):
      self.assertTrue(common._ComputeMinMaxSpec(name, None, self.ispecs, val)
                      is None)


def _ValidateComputeMinMaxSpec(name, *_):
  assert name in constants.ISPECS_PARAMETERS
  return None


def _NoDiskComputeMinMaxSpec(name, *_):
  if name == constants.ISPEC_DISK_COUNT:
    return name
  else:
    return None


class _SpecWrapper:
  def __init__(self, spec):
    self.spec = spec

  def ComputeMinMaxSpec(self, *args):
    return self.spec.pop(0)


class TestComputeIPolicySpecViolation(unittest.TestCase):
  # Minimal policy accepted by _ComputeIPolicySpecViolation()
  _MICRO_IPOL = {
    constants.IPOLICY_DTS: [constants.DT_PLAIN, constants.DT_DISKLESS],
    constants.ISPECS_MINMAX: [NotImplemented],
    }

  def test(self):
    compute_fn = _ValidateComputeMinMaxSpec
    ret = common.ComputeIPolicySpecViolation(self._MICRO_IPOL, 1024, 1, 1, 1,
                                             [1024], 1, [constants.DT_PLAIN],
                                             _compute_fn=compute_fn)
    self.assertEqual(ret, [])

  def testDiskFull(self):
    compute_fn = _NoDiskComputeMinMaxSpec
    ret = common.ComputeIPolicySpecViolation(self._MICRO_IPOL, 1024, 1, 1, 1,
                                             [1024], 1, [constants.DT_PLAIN],
                                             _compute_fn=compute_fn)
    self.assertEqual(ret, [constants.ISPEC_DISK_COUNT])

  def testDiskLess(self):
    compute_fn = _NoDiskComputeMinMaxSpec
    ret = common.ComputeIPolicySpecViolation(self._MICRO_IPOL, 1024, 1, 0, 1,
                                             [], 1, [],
                                             _compute_fn=compute_fn)
    self.assertEqual(ret, [])

  def testWrongTemplates(self):
    compute_fn = _ValidateComputeMinMaxSpec
    ret = common.ComputeIPolicySpecViolation(self._MICRO_IPOL, 1024, 1, 1, 1,
                                             [1024], 1, [constants.DT_DRBD8],
                                             _compute_fn=compute_fn)
    self.assertEqual(len(ret), 1)
    self.assertTrue("Disk template" in ret[0])

  def testInvalidArguments(self):
    self.assertRaises(AssertionError, common.ComputeIPolicySpecViolation,
                      self._MICRO_IPOL, 1024, 1, 1, 1, constants.DT_DISKLESS, 1,
                      constants.DT_PLAIN,)

  def testInvalidSpec(self):
    spec = _SpecWrapper([None, False, "foo", None, "bar", None])
    compute_fn = spec.ComputeMinMaxSpec
    ret = common.ComputeIPolicySpecViolation(self._MICRO_IPOL, 1024, 1, 1, 1,
                                             [1024], 1, [constants.DT_PLAIN],
                                             _compute_fn=compute_fn)
    self.assertEqual(ret, ["foo", "bar"])
    self.assertFalse(spec.spec)

  def testWithIPolicy(self):
    mem_size = 2048
    cpu_count = 2
    disk_count = 1
    disk_sizes = [512]
    nic_count = 1
    spindle_use = 4
    disk_template = "mytemplate"
    ispec = {
      constants.ISPEC_MEM_SIZE: mem_size,
      constants.ISPEC_CPU_COUNT: cpu_count,
      constants.ISPEC_DISK_COUNT: disk_count,
      constants.ISPEC_DISK_SIZE: disk_sizes[0],
      constants.ISPEC_NIC_COUNT: nic_count,
      constants.ISPEC_SPINDLE_USE: spindle_use,
      }
    ipolicy1 = {
      constants.ISPECS_MINMAX: [{
        constants.ISPECS_MIN: ispec,
        constants.ISPECS_MAX: ispec,
        }],
      constants.IPOLICY_DTS: [disk_template],
      }
    ispec_copy = copy.deepcopy(ispec)
    ipolicy2 = {
      constants.ISPECS_MINMAX: [
        {
          constants.ISPECS_MIN: ispec_copy,
          constants.ISPECS_MAX: ispec_copy,
          },
        {
          constants.ISPECS_MIN: ispec,
          constants.ISPECS_MAX: ispec,
          },
        ],
      constants.IPOLICY_DTS: [disk_template],
      }
    ipolicy3 = {
      constants.ISPECS_MINMAX: [
        {
          constants.ISPECS_MIN: ispec,
          constants.ISPECS_MAX: ispec,
          },
        {
          constants.ISPECS_MIN: ispec_copy,
          constants.ISPECS_MAX: ispec_copy,
          },
        ],
      constants.IPOLICY_DTS: [disk_template],
      }
    def AssertComputeViolation(ipolicy, violations):
      ret = common.ComputeIPolicySpecViolation(ipolicy, mem_size, cpu_count,
                                               disk_count, nic_count,
                                               disk_sizes, spindle_use,
                                               [disk_template]*disk_count)
      self.assertEqual(len(ret), violations)

    AssertComputeViolation(ipolicy1, 0)
    AssertComputeViolation(ipolicy2, 0)
    AssertComputeViolation(ipolicy3, 0)
    for par in constants.ISPECS_PARAMETERS:
      ispec[par] += 1
      AssertComputeViolation(ipolicy1, 1)
      AssertComputeViolation(ipolicy2, 0)
      AssertComputeViolation(ipolicy3, 0)
      ispec[par] -= 2
      AssertComputeViolation(ipolicy1, 1)
      AssertComputeViolation(ipolicy2, 0)
      AssertComputeViolation(ipolicy3, 0)
      ispec[par] += 1 # Restore
    ipolicy1[constants.IPOLICY_DTS] = ["another_template"]
    AssertComputeViolation(ipolicy1, 1)


class TestComputeIPolicyDiskSizesViolation(unittest.TestCase):
  # Minimal policy accepted by _ComputeIPolicyDiskSizesViolation()
  _MICRO_IPOL = {
    constants.IPOLICY_DTS: [constants.DT_PLAIN, constants.DT_DISKLESS],
    constants.ISPECS_MINMAX: [None],
    }

  def MakeDisks(self, *dev_types):
    return [mock.Mock(dev_type=d) for d in dev_types]

  def test(self):
    compute_fn = _ValidateComputeMinMaxSpec
    ret = common.ComputeIPolicyDiskSizesViolation(
      self._MICRO_IPOL, [1024], self.MakeDisks(constants.DT_PLAIN),
      _compute_fn=compute_fn)
    self.assertEqual(ret, [])

  def testDiskFull(self):
    compute_fn = _NoDiskComputeMinMaxSpec
    ret = common.ComputeIPolicyDiskSizesViolation(
      self._MICRO_IPOL, [1024], self.MakeDisks(constants.DT_PLAIN),
      _compute_fn=compute_fn)
    self.assertEqual(ret, [constants.ISPEC_DISK_COUNT])

  def testDisksMixed(self):
    compute_fn = _ValidateComputeMinMaxSpec
    ipol = copy.deepcopy(self._MICRO_IPOL)
    ipol[constants.IPOLICY_DTS].append(constants.DT_DRBD8)
    ret = common.ComputeIPolicyDiskSizesViolation(
      ipol, [1024, 1024],
      self.MakeDisks(constants.DT_DRBD8, constants.DT_PLAIN),
      _compute_fn=compute_fn)
    self.assertEqual(ret, [])


  def testDiskLess(self):
    compute_fn = _NoDiskComputeMinMaxSpec
    ret = common.ComputeIPolicyDiskSizesViolation(self._MICRO_IPOL, [],
                                                  [],
                                                  _compute_fn=compute_fn)
    self.assertEqual(ret, [])

  def testWrongTemplates(self):
    compute_fn = _ValidateComputeMinMaxSpec

    ret = common.ComputeIPolicyDiskSizesViolation(
      self._MICRO_IPOL, [1024], self.MakeDisks(constants.DT_DRBD8),
      _compute_fn=compute_fn)
    self.assertEqual(len(ret), 1)
    self.assertTrue("Disk template" in ret[0])

  def _AssertComputeViolation(self, ipolicy, disk_sizes, dev_types,
                              violations):
    ret = common.ComputeIPolicyDiskSizesViolation(
      ipolicy, disk_sizes, self.MakeDisks(*dev_types))
    self.assertEqual(len(ret), violations)

  def testWithIPolicy(self):
    mem_size = 2048
    cpu_count = 2
    disk_count = 1
    disk_sizes = [512]
    nic_count = 1
    spindle_use = 4
    disk_template = "mytemplate"
    ispec = {
      constants.ISPEC_MEM_SIZE: mem_size,
      constants.ISPEC_CPU_COUNT: cpu_count,
      constants.ISPEC_DISK_COUNT: disk_count,
      constants.ISPEC_DISK_SIZE: disk_sizes[0],
      constants.ISPEC_NIC_COUNT: nic_count,
      constants.ISPEC_SPINDLE_USE: spindle_use,
      }

    ipolicy = {
      constants.ISPECS_MINMAX: [{
        constants.ISPECS_MIN: ispec,
        constants.ISPECS_MAX: ispec,
        }],
      constants.IPOLICY_DTS: [disk_template],
      }

    self._AssertComputeViolation(ipolicy, [512], [disk_template], 0)
    self._AssertComputeViolation(ipolicy, [], [disk_template], 1)
    self._AssertComputeViolation(ipolicy, [], [], 1)
    self._AssertComputeViolation(ipolicy, [512, 512],
                                 [disk_template, disk_template], 1)
    self._AssertComputeViolation(ipolicy, [511], [disk_template], 1)
    self._AssertComputeViolation(ipolicy, [513], [disk_template], 1)


class _StubComputeIPolicySpecViolation:
  def __init__(self, mem_size, cpu_count, disk_count, nic_count, disk_sizes,
               spindle_use, disk_template):
    self.mem_size = mem_size
    self.cpu_count = cpu_count
    self.disk_count = disk_count
    self.nic_count = nic_count
    self.disk_sizes = disk_sizes
    self.spindle_use = spindle_use
    self.disk_template = disk_template

  def __call__(self, _, mem_size, cpu_count, disk_count, nic_count, disk_sizes,
               spindle_use, disk_template):
    assert self.mem_size == mem_size
    assert self.cpu_count == cpu_count
    assert self.disk_count == disk_count
    assert self.nic_count == nic_count
    assert self.disk_sizes == disk_sizes
    assert self.spindle_use == spindle_use
    assert self.disk_template == disk_template

    return []


class _FakeConfigForComputeIPolicyInstanceViolation:
  def __init__(self, be, excl_stor):
    self.cluster = objects.Cluster(beparams={"default": be})
    self.excl_stor = excl_stor

  def GetClusterInfo(self):
    return self.cluster

  def GetNodeInfo(self, _):
    return {}

  def GetNdParams(self, _):
    return {
      constants.ND_EXCLUSIVE_STORAGE: self.excl_stor,
      }

  def GetInstanceNodes(self, instance_uuid):
    return ("pnode_uuid", )

  def GetInstanceDisks(self, _):
    return [objects.Disk(size=512, spindles=13, uuid="disk_uuid",
                         dev_type=constants.DT_PLAIN)]


class TestComputeIPolicyInstanceViolation(unittest.TestCase):
  def setUp(self):
    self.beparams = {
      constants.BE_MAXMEM: 2048,
      constants.BE_VCPUS: 2,
      constants.BE_SPINDLE_USE: 4,
      }
    self.cfg = _FakeConfigForComputeIPolicyInstanceViolation(
        self.beparams, False)
    self.cfg_exclusive = _FakeConfigForComputeIPolicyInstanceViolation(
        self.beparams, True)
    self.stub = mock.MagicMock()
    self.stub.return_value = []

  def testPlain(self):
    instance = objects.Instance(beparams=self.beparams, disks=["disk_uuid"],
                                nics=[], primary_node="pnode_uuid",
                                disk_template=constants.DT_PLAIN)
    ret = common.ComputeIPolicyInstanceViolation(
        NotImplemented, instance, self.cfg, _compute_fn=self.stub)
    self.assertEqual(ret, [])
    self.stub.assert_called_with(NotImplemented, 2048, 2, 1, 0, [512], 4,
                                 [constants.DT_PLAIN])

  def testNoBeparams(self):
    instance = objects.Instance(beparams={}, disks=["disk_uuid"],
                                 nics=[], primary_node="pnode_uuid",
                                 disk_template=constants.DT_PLAIN)
    ret = common.ComputeIPolicyInstanceViolation(
        NotImplemented, instance, self.cfg, _compute_fn=self.stub)
    self.assertEqual(ret, [])
    self.stub.assert_called_with(NotImplemented, 2048, 2, 1, 0, [512], 4,
                                 [constants.DT_PLAIN])

  def testExclusiveStorage(self):
    instance = objects.Instance(beparams=self.beparams, disks=["disk_uuid"],
                                nics=[], primary_node="pnode_uuid",
                                disk_template=constants.DT_PLAIN)
    ret = common.ComputeIPolicyInstanceViolation(
        NotImplemented, instance, self.cfg_exclusive, _compute_fn=self.stub)
    self.assertEqual(ret, [])
    self.stub.assert_called_with(NotImplemented, 2048, 2, 1, 0, [512], 13,
                                 [constants.DT_PLAIN])

  def testExclusiveStorageNoBeparams(self):
    instance = objects.Instance(beparams={}, disks=["disk_uuid"],
                                 nics=[], primary_node="pnode_uuid",
                                 disk_template=constants.DT_PLAIN)
    ret = common.ComputeIPolicyInstanceViolation(
        NotImplemented, instance, self.cfg_exclusive, _compute_fn=self.stub)
    self.assertEqual(ret, [])
    self.stub.assert_called_with(NotImplemented, 2048, 2, 1, 0, [512], 13,
                                 [constants.DT_PLAIN])


class _CallRecorder:
  def __init__(self, return_value=None):
    self.called = False
    self.return_value = return_value

  def __call__(self, *args):
    self.called = True
    return self.return_value


class TestComputeIPolicyNodeViolation(unittest.TestCase):
  def setUp(self):
    self.recorder = _CallRecorder(return_value=[])

  def testSameGroup(self):
    ret = instance_utils._ComputeIPolicyNodeViolation(
      NotImplemented,
      NotImplemented,
      "foo", "foo", NotImplemented,
      _compute_fn=self.recorder)
    self.assertFalse(self.recorder.called)
    self.assertEqual(ret, [])

  def testDifferentGroup(self):
    ret = instance_utils._ComputeIPolicyNodeViolation(
      NotImplemented,
      NotImplemented,
      "foo", "bar", NotImplemented,
      _compute_fn=self.recorder)
    self.assertTrue(self.recorder.called)
    self.assertEqual(ret, [])


class TestDiskSizeInBytesToMebibytes(unittest.TestCase):
  def testLessThanOneMebibyte(self):
    for i in [1, 2, 7, 512, 1000, 1023]:
      lu = _FakeLU()
      result = instance_storage._DiskSizeInBytesToMebibytes(lu, i)
      self.assertEqual(result, 1)
      self.assertEqual(len(lu.warning_log), 1)
      self.assertEqual(len(lu.warning_log[0]), 2)
      (_, (warnsize, )) = lu.warning_log[0]
      self.assertEqual(warnsize, (1024 * 1024) - i)

  def testEven(self):
    for i in [1, 2, 7, 512, 1000, 1023]:
      lu = _FakeLU()
      result = instance_storage._DiskSizeInBytesToMebibytes(lu,
                                                            i * 1024 * 1024)
      self.assertEqual(result, i)
      self.assertFalse(lu.warning_log)

  def testLargeNumber(self):
    for i in [1, 2, 7, 512, 1000, 1023, 2724, 12420]:
      for j in [1, 2, 486, 326, 986, 1023]:
        lu = _FakeLU()
        size = (1024 * 1024 * i) + j
        result = instance_storage._DiskSizeInBytesToMebibytes(lu, size)
        self.assertEqual(result, i + 1, msg="Amount was not rounded up")
        self.assertEqual(len(lu.warning_log), 1)
        self.assertEqual(len(lu.warning_log[0]), 2)
        (_, (warnsize, )) = lu.warning_log[0]
        self.assertEqual(warnsize, (1024 * 1024) - j)


class _OpTestVerifyErrors(opcodes.OpCode):
  OP_PARAMS = [
    ("debug_simulate_errors", False, ht.TBool, ""),
    ("error_codes", False, ht.TBool, ""),
    ("ignore_errors",
     [],
     ht.TListOf(ht.TElemOf(constants.CV_ALL_ECODES_STRINGS)),
     "")
    ]


class _LuTestVerifyErrors(verify._VerifyErrors):
  def __init__(self, **kwargs):
    super(_LuTestVerifyErrors, self).__init__()
    self.op = _OpTestVerifyErrors(**kwargs)
    self.op.Validate(True)
    self.msglist = []
    self._feedback_fn = self.Feedback
    self.bad = False

  # TODO: Cleanup calling conventions, make them explicit
  def Feedback(self, *args):

    # TODO: Remove this once calling conventions are explicit.
    # Feedback can be called with anything, we interpret ELogMessageList as
    # messages that have to be individually added to the log list, but pushed
    # in a single update. Other types are only transparently passed forward.
    if len(args) == 1:
      log_type = constants.ELOG_MESSAGE
      log_msg = args[0]
    else:
      log_type, log_msg = args

    if log_type != constants.ELOG_MESSAGE_LIST:
      log_msg = [log_msg]

    self.msglist.extend(log_msg)

  def DispatchCallError(self, which, *args, **kwargs):
    if which:
      self._Error(*args, **kwargs)
    else:
      self._ErrorIf(True, *args, **kwargs)

  def CallErrorIf(self, c, *args, **kwargs):
    self._ErrorIf(c, *args, **kwargs)


class TestVerifyErrors(unittest.TestCase):
  # Fake cluster-verify error code structures; we use two arbitary real error
  # codes to pass validation of ignore_errors
  (_, _ERR1ID, _) = constants.CV_ECLUSTERCFG
  _NODESTR = "node"
  _NODENAME = "mynode"
  _ERR1CODE = (_NODESTR, _ERR1ID, "Error one")
  (_, _ERR2ID, _) = constants.CV_ECLUSTERCERT
  _INSTSTR = "instance"
  _INSTNAME = "myinstance"
  _ERR2CODE = (_INSTSTR, _ERR2ID, "Error two")
  # Arguments used to call _Error() or _ErrorIf()
  _ERR1ARGS = (_ERR1CODE, _NODENAME, "Error1 is %s", "an error")
  _ERR2ARGS = (_ERR2CODE, _INSTNAME, "Error2 has no argument")
  # Expected error messages
  _ERR1MSG = _ERR1ARGS[2] % _ERR1ARGS[3]
  _ERR2MSG = _ERR2ARGS[2]

  def testNoError(self):
    lu = _LuTestVerifyErrors()
    lu.CallErrorIf(False, self._ERR1CODE, *self._ERR1ARGS)
    self.assertFalse(lu.bad)
    self.assertFalse(lu.msglist)

  def _InitTest(self, **kwargs):
    self.lu1 = _LuTestVerifyErrors(**kwargs)
    self.lu2 = _LuTestVerifyErrors(**kwargs)

  def _CallError(self, *args, **kwargs):
    # Check that _Error() and _ErrorIf() produce the same results
    self.lu1.DispatchCallError(True, *args, **kwargs)
    self.lu2.DispatchCallError(False, *args, **kwargs)
    self.assertEqual(self.lu1.bad, self.lu2.bad)
    self.assertEqual(self.lu1.msglist, self.lu2.msglist)
    # Test-specific checks are made on one LU
    return self.lu1

  def _checkMsgCommon(self, logstr, errmsg, itype, item, warning):
    self.assertTrue(errmsg in logstr)
    if warning:
      self.assertTrue("WARNING" in logstr)
    else:
      self.assertTrue("ERROR" in logstr)
    self.assertTrue(itype in logstr)
    self.assertTrue(item in logstr)

  def _checkMsg1(self, logstr, warning=False):
    self._checkMsgCommon(logstr, self._ERR1MSG, self._NODESTR,
                         self._NODENAME, warning)

  def _checkMsg2(self, logstr, warning=False):
    self._checkMsgCommon(logstr, self._ERR2MSG, self._INSTSTR,
                         self._INSTNAME, warning)

  def testPlain(self):
    self._InitTest()
    lu = self._CallError(*self._ERR1ARGS)
    self.assertTrue(lu.bad)
    self.assertEqual(len(lu.msglist), 1)
    self._checkMsg1(lu.msglist[0])

  def testMultiple(self):
    self._InitTest()
    self._CallError(*self._ERR1ARGS)
    lu = self._CallError(*self._ERR2ARGS)
    self.assertTrue(lu.bad)
    self.assertEqual(len(lu.msglist), 2)
    self._checkMsg1(lu.msglist[0])
    self._checkMsg2(lu.msglist[1])

  def testIgnore(self):
    self._InitTest(ignore_errors=[self._ERR1ID])
    lu = self._CallError(*self._ERR1ARGS)
    self.assertFalse(lu.bad)
    self.assertEqual(len(lu.msglist), 1)
    self._checkMsg1(lu.msglist[0], warning=True)

  def testWarning(self):
    self._InitTest()
    lu = self._CallError(*self._ERR1ARGS,
                         code=_LuTestVerifyErrors.ETYPE_WARNING)
    self.assertFalse(lu.bad)
    self.assertEqual(len(lu.msglist), 1)
    self._checkMsg1(lu.msglist[0], warning=True)

  def testWarning2(self):
    self._InitTest()
    self._CallError(*self._ERR1ARGS)
    lu = self._CallError(*self._ERR2ARGS,
                         code=_LuTestVerifyErrors.ETYPE_WARNING)
    self.assertTrue(lu.bad)
    self.assertEqual(len(lu.msglist), 2)
    self._checkMsg1(lu.msglist[0])
    self._checkMsg2(lu.msglist[1], warning=True)

  def testDebugSimulate(self):
    lu = _LuTestVerifyErrors(debug_simulate_errors=True)
    lu.CallErrorIf(False, *self._ERR1ARGS)
    self.assertTrue(lu.bad)
    self.assertEqual(len(lu.msglist), 1)
    self._checkMsg1(lu.msglist[0])

  def testErrCodes(self):
    self._InitTest(error_codes=True)
    lu = self._CallError(*self._ERR1ARGS)
    self.assertTrue(lu.bad)
    self.assertEqual(len(lu.msglist), 1)
    self._checkMsg1(lu.msglist[0])
    self.assertTrue(self._ERR1ID in lu.msglist[0])


class TestGetUpdatedIPolicy(unittest.TestCase):
  """Tests for cmdlib._GetUpdatedIPolicy()"""
  _OLD_CLUSTER_POLICY = {
    constants.IPOLICY_VCPU_RATIO: 1.5,
    constants.ISPECS_MINMAX: [
      {
        constants.ISPECS_MIN: {
          constants.ISPEC_MEM_SIZE: 32768,
          constants.ISPEC_CPU_COUNT: 8,
          constants.ISPEC_DISK_COUNT: 1,
          constants.ISPEC_DISK_SIZE: 1024,
          constants.ISPEC_NIC_COUNT: 1,
          constants.ISPEC_SPINDLE_USE: 1,
          },
        constants.ISPECS_MAX: {
          constants.ISPEC_MEM_SIZE: 65536,
          constants.ISPEC_CPU_COUNT: 10,
          constants.ISPEC_DISK_COUNT: 5,
          constants.ISPEC_DISK_SIZE: 1024 * 1024,
          constants.ISPEC_NIC_COUNT: 3,
          constants.ISPEC_SPINDLE_USE: 12,
          },
        },
      constants.ISPECS_MINMAX_DEFAULTS,
      ],
    constants.ISPECS_STD: constants.IPOLICY_DEFAULTS[constants.ISPECS_STD],
    }
  _OLD_GROUP_POLICY = {
    constants.IPOLICY_SPINDLE_RATIO: 2.5,
    constants.ISPECS_MINMAX: [{
      constants.ISPECS_MIN: {
        constants.ISPEC_MEM_SIZE: 128,
        constants.ISPEC_CPU_COUNT: 1,
        constants.ISPEC_DISK_COUNT: 1,
        constants.ISPEC_DISK_SIZE: 1024,
        constants.ISPEC_NIC_COUNT: 1,
        constants.ISPEC_SPINDLE_USE: 1,
        },
      constants.ISPECS_MAX: {
        constants.ISPEC_MEM_SIZE: 32768,
        constants.ISPEC_CPU_COUNT: 8,
        constants.ISPEC_DISK_COUNT: 5,
        constants.ISPEC_DISK_SIZE: 1024 * 1024,
        constants.ISPEC_NIC_COUNT: 3,
        constants.ISPEC_SPINDLE_USE: 12,
        },
      }],
    }

  def _TestSetSpecs(self, old_policy, isgroup):
    diff_minmax = [{
      constants.ISPECS_MIN: {
        constants.ISPEC_MEM_SIZE: 64,
        constants.ISPEC_CPU_COUNT: 1,
        constants.ISPEC_DISK_COUNT: 2,
        constants.ISPEC_DISK_SIZE: 64,
        constants.ISPEC_NIC_COUNT: 1,
        constants.ISPEC_SPINDLE_USE: 1,
        },
      constants.ISPECS_MAX: {
        constants.ISPEC_MEM_SIZE: 16384,
        constants.ISPEC_CPU_COUNT: 10,
        constants.ISPEC_DISK_COUNT: 12,
        constants.ISPEC_DISK_SIZE: 1024,
        constants.ISPEC_NIC_COUNT: 9,
        constants.ISPEC_SPINDLE_USE: 18,
        },
      }]
    diff_std = {
        constants.ISPEC_DISK_COUNT: 10,
        constants.ISPEC_DISK_SIZE: 512,
        }
    diff_policy = {
      constants.ISPECS_MINMAX: diff_minmax
      }
    if not isgroup:
      diff_policy[constants.ISPECS_STD] = diff_std
    new_policy = common.GetUpdatedIPolicy(old_policy, diff_policy,
                                          group_policy=isgroup)

    self.assertTrue(constants.ISPECS_MINMAX in new_policy)
    self.assertEqual(new_policy[constants.ISPECS_MINMAX], diff_minmax)
    for key in old_policy:
      if not key in diff_policy:
        self.assertTrue(key in new_policy)
        self.assertEqual(new_policy[key], old_policy[key])

    if not isgroup:
      new_std = new_policy[constants.ISPECS_STD]
      for key in diff_std:
        self.assertTrue(key in new_std)
        self.assertEqual(new_std[key], diff_std[key])
      old_std = old_policy.get(constants.ISPECS_STD, {})
      for key in old_std:
        self.assertTrue(key in new_std)
        if key not in diff_std:
          self.assertEqual(new_std[key], old_std[key])

  def _TestSet(self, old_policy, diff_policy, isgroup):
    new_policy = common.GetUpdatedIPolicy(old_policy, diff_policy,
                                           group_policy=isgroup)
    for key in diff_policy:
      self.assertTrue(key in new_policy)
      self.assertEqual(new_policy[key], diff_policy[key])
    for key in old_policy:
      if not key in diff_policy:
        self.assertTrue(key in new_policy)
        self.assertEqual(new_policy[key], old_policy[key])

  def testSet(self):
    diff_policy = {
      constants.IPOLICY_VCPU_RATIO: 3,
      constants.IPOLICY_DTS: [constants.DT_FILE],
      }
    self._TestSet(self._OLD_GROUP_POLICY, diff_policy, True)
    self._TestSetSpecs(self._OLD_GROUP_POLICY, True)
    self._TestSet({}, diff_policy, True)
    self._TestSetSpecs({}, True)
    self._TestSet(self._OLD_CLUSTER_POLICY, diff_policy, False)
    self._TestSetSpecs(self._OLD_CLUSTER_POLICY, False)

  def testUnset(self):
    old_policy = self._OLD_GROUP_POLICY
    diff_policy = {
      constants.IPOLICY_SPINDLE_RATIO: constants.VALUE_DEFAULT,
      }
    new_policy = common.GetUpdatedIPolicy(old_policy, diff_policy,
                                          group_policy=True)
    for key in diff_policy:
      self.assertFalse(key in new_policy)
    for key in old_policy:
      if not key in diff_policy:
        self.assertTrue(key in new_policy)
        self.assertEqual(new_policy[key], old_policy[key])

    self.assertRaises(errors.OpPrereqError, common.GetUpdatedIPolicy,
                      old_policy, diff_policy, group_policy=False)

  def testUnsetEmpty(self):
    old_policy = {}
    for key in constants.IPOLICY_ALL_KEYS:
      diff_policy = {
        key: constants.VALUE_DEFAULT,
        }
    new_policy = common.GetUpdatedIPolicy(old_policy, diff_policy,
                                          group_policy=True)
    self.assertEqual(new_policy, old_policy)

  def _TestInvalidKeys(self, old_policy, isgroup):
    INVALID_KEY = "this_key_shouldnt_be_allowed"
    INVALID_DICT = {
      INVALID_KEY: 3,
      }
    invalid_policy = INVALID_DICT
    self.assertRaises(errors.OpPrereqError, common.GetUpdatedIPolicy,
                      old_policy, invalid_policy, group_policy=isgroup)
    invalid_ispecs = {
      constants.ISPECS_MINMAX: [INVALID_DICT],
      }
    self.assertRaises(errors.TypeEnforcementError, common.GetUpdatedIPolicy,
                      old_policy, invalid_ispecs, group_policy=isgroup)
    if isgroup:
      invalid_for_group = {
        constants.ISPECS_STD: constants.IPOLICY_DEFAULTS[constants.ISPECS_STD],
        }
      self.assertRaises(errors.OpPrereqError, common.GetUpdatedIPolicy,
                        old_policy, invalid_for_group, group_policy=isgroup)
    good_ispecs = self._OLD_CLUSTER_POLICY[constants.ISPECS_MINMAX]
    invalid_ispecs = copy.deepcopy(good_ispecs)
    invalid_policy = {
      constants.ISPECS_MINMAX: invalid_ispecs,
      }
    for minmax in invalid_ispecs:
      for key in constants.ISPECS_MINMAX_KEYS:
        ispec = minmax[key]
        ispec[INVALID_KEY] = None
        self.assertRaises(errors.TypeEnforcementError,
                          common.GetUpdatedIPolicy, old_policy,
                          invalid_policy, group_policy=isgroup)
        del ispec[INVALID_KEY]
        for par in constants.ISPECS_PARAMETERS:
          oldv = ispec[par]
          ispec[par] = "this_is_not_good"
          self.assertRaises(errors.TypeEnforcementError,
                            common.GetUpdatedIPolicy,
                            old_policy, invalid_policy, group_policy=isgroup)
          ispec[par] = oldv
    # This is to make sure that no two errors were present during the tests
    common.GetUpdatedIPolicy(old_policy, invalid_policy,
                             group_policy=isgroup)

  def testInvalidKeys(self):
    self._TestInvalidKeys(self._OLD_GROUP_POLICY, True)
    self._TestInvalidKeys(self._OLD_CLUSTER_POLICY, False)

  def testInvalidValues(self):
    for par in (constants.IPOLICY_PARAMETERS |
                frozenset([constants.IPOLICY_DTS])):
      bad_policy = {
        par: "invalid_value",
        }
      self.assertRaises(errors.OpPrereqError, common.GetUpdatedIPolicy, {},
                        bad_policy, group_policy=True)


class TestCopyLockList(unittest.TestCase):
  def test(self):
    self.assertEqual(instance_utils.CopyLockList([]), [])
    self.assertEqual(instance_utils.CopyLockList(None), None)
    self.assertEqual(instance_utils.CopyLockList(locking.ALL_SET),
                     locking.ALL_SET)

    names = ["foo", "bar"]
    output = instance_utils.CopyLockList(names)
    self.assertEqual(names, output)
    self.assertNotEqual(id(names), id(output), msg="List was not copied")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
