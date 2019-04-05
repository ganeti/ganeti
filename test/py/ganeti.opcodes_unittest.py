#!/usr/bin/python
#

# Copyright (C) 2010, 2011, 2012 Google Inc.
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


"""Script for testing ganeti.backend"""

import os
import sys
import unittest

from ganeti import utils
from ganeti import opcodes
from ganeti import opcodes_base
from ganeti import ht
from ganeti import constants
from ganeti import errors
from ganeti import compat

import testutils


class TestOpcodes(unittest.TestCase):
  def test(self):
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, None)
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, "")
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, {})
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, {"OP_ID": ""})

    for cls in opcodes.OP_MAPPING.values():
      self.assert_(cls.OP_ID.startswith("OP_"))
      self.assert_(len(cls.OP_ID) > 3)
      self.assertEqual(cls.OP_ID, cls.OP_ID.upper())
      self.assertEqual(cls.OP_ID, opcodes_base._NameToId(cls.__name__))
      self.assertFalse(
        compat.any(cls.OP_ID.startswith(prefix)
                   for prefix in opcodes_base.SUMMARY_PREFIX.keys()))
      self.assertTrue(callable(cls.OP_RESULT),
                      msg=("%s should have a result check" % cls.OP_ID))

      self.assertRaises(TypeError, cls, unsupported_parameter="some value")

      args = [
        # No variables
        {},

        # Variables supported by all opcodes
        {"dry_run": False, "debug_level": 0, },

        # All variables
        dict([(name, []) for name in cls.GetAllSlots()])
        ]

      for i in args:
        op = cls(**i)

        self.assertEqual(op.OP_ID, cls.OP_ID)
        self._checkSummary(op)

        # Try a restore
        state = op.__getstate__()
        self.assert_(isinstance(state, dict))

        restored = opcodes.OpCode.LoadOpCode(state)
        self.assert_(isinstance(restored, cls))
        self._checkSummary(restored)

        for name in ["x_y_z", "hello_world"]:
          assert name not in cls.GetAllSlots()
          for value in [None, True, False, [], "Hello World"]:
            self.assertRaises(AttributeError, setattr, op, name, value)

  def _checkSummary(self, op):
    summary = op.Summary()

    if hasattr(op, "OP_DSC_FIELD"):
      self.assert_(("OP_%s" % summary).startswith("%s(" % op.OP_ID))
      self.assert_(summary.endswith(")"))
    else:
      self.assertEqual("OP_%s" % summary, op.OP_ID)

  def testSummary(self):
    class OpTest(opcodes.OpCode):
      OP_DSC_FIELD = "data"
      OP_PARAMS = [
        ("data", ht.NoDefault, ht.TString, None),
        ]

    self.assertEqual(OpTest(data="").Summary(), "TEST()")
    self.assertEqual(OpTest(data="Hello World").Summary(),
                     "TEST(Hello World)")
    self.assertEqual(OpTest(data="node1.example.com").Summary(),
                     "TEST(node1.example.com)")

  def testSummaryFormatter(self):
    class OpTest(opcodes.OpCode):
      OP_DSC_FIELD = "data"
      OP_DSC_FORMATTER = lambda _, v: "a"
      OP_PARAMS = [
        ("data", ht.NoDefault, ht.TString, None),
        ]
    self.assertEqual(OpTest(data="").Summary(), "TEST(a)")
    self.assertEqual(OpTest(data="b").Summary(), "TEST(a)")

  def testTinySummary(self):
    self.assertFalse(
      utils.FindDuplicates(opcodes_base.SUMMARY_PREFIX.values()))
    self.assertTrue(compat.all(prefix.endswith("_") and supplement.endswith("_")
                               for (prefix, supplement) in
                                 opcodes_base.SUMMARY_PREFIX.items()))

    self.assertEqual(opcodes.OpClusterPostInit().TinySummary(), "C_POST_INIT")
    self.assertEqual(opcodes.OpNodeRemove().TinySummary(), "N_REMOVE")
    self.assertEqual(opcodes.OpInstanceMigrate().TinySummary(), "I_MIGRATE")
    self.assertEqual(opcodes.OpTestJqueue().TinySummary(), "TEST_JQUEUE")

  def testListSummary(self):
    class OpTest(opcodes.OpCode):
      OP_DSC_FIELD = "data"
      OP_PARAMS = [
        ("data", ht.NoDefault, ht.TList, None),
        ]

    self.assertEqual(OpTest(data=["a", "b", "c"]).Summary(),
                     "TEST(a,b,c)")
    self.assertEqual(OpTest(data=["a", None, "c"]).Summary(),
                     "TEST(a,None,c)")
    self.assertEqual(OpTest(data=[1, 2, 3, 4]).Summary(), "TEST(1,2,3,4)")

  def testOpId(self):
    self.assertFalse(utils.FindDuplicates(cls.OP_ID
                                          for cls in opcodes._GetOpList()))
    self.assertEqual(len(opcodes._GetOpList()), len(opcodes.OP_MAPPING))

  def testParams(self):
    supported_by_all = set(["debug_level", "dry_run", "priority"])

    self.assertTrue(opcodes_base.BaseOpCode not in opcodes.OP_MAPPING.values())
    self.assertTrue(opcodes.OpCode not in opcodes.OP_MAPPING.values())

    for cls in opcodes.OP_MAPPING.values() + [opcodes.OpCode]:
      all_slots = cls.GetAllSlots()

      self.assertEqual(len(set(all_slots) & supported_by_all), 3,
                       msg=("Opcode %s doesn't support all base"
                            " parameters (%r)" % (cls.OP_ID, supported_by_all)))

      # All opcodes must have OP_PARAMS
      self.assert_(hasattr(cls, "OP_PARAMS"),
                   msg="%s doesn't have OP_PARAMS" % cls.OP_ID)

      param_names = [name for (name, _, _, _) in cls.GetAllParams()]

      self.assertEqual(all_slots, param_names)

      # Without inheritance
      self.assertEqual(cls.__slots__,
                       [name for (name, _, _, _) in cls.OP_PARAMS])

      # This won't work if parameters are converted to a dictionary
      duplicates = utils.FindDuplicates(param_names)
      self.assertFalse(duplicates,
                       msg=("Found duplicate parameters %r in %s" %
                            (duplicates, cls.OP_ID)))

      # Check parameter definitions
      for attr_name, aval, test, doc in cls.GetAllParams():
        self.assert_(attr_name)
        self.assertTrue(callable(test),
                     msg=("Invalid type check for %s.%s" %
                          (cls.OP_ID, attr_name)))
        self.assertTrue(doc is None or isinstance(doc, str))

        if callable(aval):
          default_value = aval()
          self.assertFalse(callable(default_value),
                           msg=("Default value of %s.%s returned by function"
                                " is callable" % (cls.OP_ID, attr_name)))
        else:
          default_value = aval

        if aval is not ht.NoDefault and aval is not None:
          self.assertTrue(test(default_value),
                          msg=("Default value of %s.%s does not verify" %
                               (cls.OP_ID, attr_name)))

      # If any parameter has documentation, all others need to have it as well
      has_doc = [doc is not None for (_, _, _, doc) in cls.OP_PARAMS]
      self.assertTrue(not compat.any(has_doc) or compat.all(has_doc),
                      msg="%s does not document all parameters" % cls)

  def testValidateNoModification(self):
    class OpTest(opcodes.OpCode):
      OP_PARAMS = [
        ("nodef", None, ht.TString, None),
        ("wdef", "default", ht.TMaybeString, None),
        ("number", 0, ht.TInt, None),
        ("notype", None, ht.TAny, None),
        ]

    # Missing required parameter "nodef"
    op = OpTest()
    before = op.__getstate__()
    self.assertRaises(errors.OpPrereqError, op.Validate, False)
    self.assertTrue(op.nodef is None)
    self.assertEqual(op.wdef, "default")
    self.assertEqual(op.number, 0)
    self.assertTrue(op.notype is None)
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    # Required parameter "nodef" is provided
    op = OpTest(nodef="foo")
    before = op.__getstate__()
    op.Validate(False)
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")
    self.assertEqual(op.nodef, "foo")
    self.assertEqual(op.wdef, "default")
    self.assertEqual(op.number, 0)
    self.assertTrue(op.notype is None)

    # Missing required parameter "nodef"
    op = OpTest(wdef="hello", number=999)
    before = op.__getstate__()
    self.assertRaises(errors.OpPrereqError, op.Validate, False)
    self.assertTrue(op.nodef is None)
    self.assertTrue(op.notype is None)
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    # Wrong type for "nodef"
    op = OpTest(nodef=987)
    before = op.__getstate__()
    self.assertRaises(errors.OpPrereqError, op.Validate, False)
    self.assertEqual(op.nodef, 987)
    self.assertTrue(op.notype is None)
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    # Testing different types for "notype"
    op = OpTest(nodef="foo", notype=[1, 2, 3])
    before = op.__getstate__()
    op.Validate(False)
    self.assertEqual(op.nodef, "foo")
    self.assertEqual(op.notype, [1, 2, 3])
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    op = OpTest(nodef="foo", notype="Hello World")
    before = op.__getstate__()
    op.Validate(False)
    self.assertEqual(op.nodef, "foo")
    self.assertEqual(op.notype, "Hello World")
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

  def testValidateSetDefaults(self):
    class OpTest(opcodes.OpCode):
      OP_PARAMS = [
        ("value1", "default", ht.TMaybeString, None),
        ("value2", "result", ht.TMaybeString, None),
        ]

    op = OpTest()
    op.Validate(True)
    self.assertEqual(op.value1, "default")
    self.assertEqual(op.value2, "result")
    self.assert_(op.dry_run is None)
    self.assert_(op.debug_level is None)
    self.assertEqual(op.priority, constants.OP_PRIO_DEFAULT)

    op = OpTest(value1="hello", value2="world", debug_level=123)
    op.Validate(True)
    self.assertEqual(op.value1, "hello")
    self.assertEqual(op.value2, "world")
    self.assertEqual(op.debug_level, 123)

  def testOpInstanceMultiAlloc(self):
    inst = dict([(name, []) for name in opcodes.OpInstanceCreate.GetAllSlots()])
    inst_op = opcodes.OpInstanceCreate(**inst)
    inst_state = inst_op.__getstate__()

    multialloc = opcodes.OpInstanceMultiAlloc(instances=[inst_op])
    state = multialloc.__getstate__()
    self.assertEquals(state["instances"], [inst_state])
    loaded_multialloc = opcodes.OpCode.LoadOpCode(state)
    (loaded_inst,) = loaded_multialloc.instances
    self.assertNotEquals(loaded_inst, inst_op)
    self.assertEquals(loaded_inst.__getstate__(), inst_state)


class TestOpcodeDepends(unittest.TestCase):
  def test(self):
    check_relative = opcodes_base.BuildJobDepCheck(True)
    check_norelative = opcodes_base.TNoRelativeJobDependencies

    for fn in [check_relative, check_norelative]:
      self.assertTrue(fn(None))
      self.assertTrue(fn([]))
      self.assertTrue(fn([(1, [])]))
      self.assertTrue(fn([(719833, [])]))
      self.assertTrue(fn([("24879", [])]))
      self.assertTrue(fn([(2028, [constants.JOB_STATUS_ERROR])]))
      self.assertTrue(fn([
        (2028, [constants.JOB_STATUS_ERROR]),
        (18750, []),
        (5063, [constants.JOB_STATUS_SUCCESS, constants.JOB_STATUS_ERROR]),
        ]))

      self.assertFalse(fn(1))
      self.assertFalse(fn([(9, )]))
      self.assertFalse(fn([(15194, constants.JOB_STATUS_ERROR)]))

    for i in [
      [(-1, [])],
      [(-27740, [constants.JOB_STATUS_CANCELED, constants.JOB_STATUS_ERROR]),
       (-1, [constants.JOB_STATUS_ERROR]),
       (9921, [])],
      ]:
      self.assertTrue(check_relative(i))
      self.assertFalse(check_norelative(i))


class TestResultChecks(unittest.TestCase):
  def testJobIdList(self):
    for i in [[], [(False, "error")], [(False, "")],
              [(True, 123), (True, "999")]]:
      self.assertTrue(ht.TJobIdList(i))

    for i in ["", [("x", 1)], [[], []], [[False, "", None], [True, 123]]]:
      self.assertFalse(ht.TJobIdList(i))

  def testJobIdListOnly(self):
    self.assertTrue(ht.TJobIdListOnly({
      constants.JOB_IDS_KEY: [],
      }))
    self.assertTrue(ht.TJobIdListOnly({
      constants.JOB_IDS_KEY: [(True, "9282")],
      }))

    self.assertFalse(ht.TJobIdListOnly({
      "x": None,
      }))
    self.assertFalse(ht.TJobIdListOnly({
      constants.JOB_IDS_KEY: [],
      "x": None,
      }))
    self.assertFalse(ht.TJobIdListOnly({
      constants.JOB_IDS_KEY: [("foo", "bar")],
      }))
    self.assertFalse(ht.TJobIdListOnly({
      constants.JOB_IDS_KEY: [("one", "two", "three")],
      }))


class TestOpInstanceSetParams(unittest.TestCase):
  def _GenericTests(self, fn):
    self.assertTrue(fn([]))
    self.assertTrue(fn([(constants.DDM_ADD, {})]))
    self.assertTrue(fn([(constants.DDM_ATTACH, {})]))
    self.assertTrue(fn([(constants.DDM_REMOVE, {})]))
    self.assertTrue(fn([(constants.DDM_DETACH, {})]))
    for i in [0, 1, 2, 3, 9, 10, 1024]:
      self.assertTrue(fn([(i, {})]))

    self.assertFalse(fn(None))
    self.assertFalse(fn({}))
    self.assertFalse(fn(""))
    self.assertFalse(fn(0))
    self.assertFalse(fn([(-100, {})]))
    self.assertFalse(fn([(constants.DDM_ADD, 2, 3)]))
    self.assertFalse(fn([[constants.DDM_ADD]]))

  def testNicModifications(self):
    fn = ht.TSetParamsMods(ht.TINicParams)
    self._GenericTests(fn)

    for param in constants.INIC_PARAMS:
      self.assertTrue(fn([[constants.DDM_ADD, {param: None}]]))
      self.assertTrue(fn([[constants.DDM_ADD, {param: param}]]))

  def testDiskModifications(self):
    fn = ht.TSetParamsMods(ht.TIDiskParams)
    self._GenericTests(fn)

    for param in constants.IDISK_PARAMS:
      self.assertTrue(fn([[constants.DDM_ADD, {param: 0}]]))
      self.assertTrue(fn([[constants.DDM_ADD, {param: param}]]))
      self.assertTrue(fn([[constants.DDM_ATTACH, {param: param}]]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
