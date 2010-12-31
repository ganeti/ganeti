#!/usr/bin/python
#

# Copyright (C) 2010 Google Inc.
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


"""Script for testing ganeti.backend"""

import os
import sys
import unittest

from ganeti import utils
from ganeti import opcodes
from ganeti import ht
from ganeti import constants
from ganeti import errors

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

      self.assertRaises(TypeError, cls, unsupported_parameter="some value")

      args = [
        # No variables
        {},

        # Variables supported by all opcodes
        {"dry_run": False, "debug_level": 0, },

        # All variables
        dict([(name, False) for name in cls._all_slots()])
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
          assert name not in cls._all_slots()
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
    class _TestOp(opcodes.OpCode):
      OP_ID = "OP_TEST"
      OP_DSC_FIELD = "data"
      OP_PARAMS = [
        ("data", ht.NoDefault, ht.TString),
        ]

    self.assertEqual(_TestOp(data="").Summary(), "TEST()")
    self.assertEqual(_TestOp(data="Hello World").Summary(),
                     "TEST(Hello World)")
    self.assertEqual(_TestOp(data="node1.example.com").Summary(),
                     "TEST(node1.example.com)")

  def testListSummary(self):
    class _TestOp(opcodes.OpCode):
      OP_ID = "OP_TEST"
      OP_DSC_FIELD = "data"
      OP_PARAMS = [
        ("data", ht.NoDefault, ht.TList),
        ]

    self.assertEqual(_TestOp(data=["a", "b", "c"]).Summary(),
                     "TEST(a,b,c)")
    self.assertEqual(_TestOp(data=["a", None, "c"]).Summary(),
                     "TEST(a,None,c)")
    self.assertEqual(_TestOp(data=[1, 2, 3, 4]).Summary(), "TEST(1,2,3,4)")

  def testOpId(self):
    self.assertFalse(utils.FindDuplicates(cls.OP_ID
                                          for cls in opcodes._GetOpList()))
    self.assertEqual(len(opcodes._GetOpList()), len(opcodes.OP_MAPPING))

  def testParams(self):
    supported_by_all = set(["debug_level", "dry_run", "priority"])

    self.assert_(opcodes.BaseOpCode not in opcodes.OP_MAPPING.values())
    self.assert_(opcodes.OpCode in opcodes.OP_MAPPING.values())

    for cls in opcodes.OP_MAPPING.values():
      all_slots = cls._all_slots()

      self.assertEqual(len(set(all_slots) & supported_by_all), 3,
                       msg=("Opcode %s doesn't support all base"
                            " parameters (%r)" % (cls.OP_ID, supported_by_all)))

      # All opcodes must have OP_PARAMS
      self.assert_(hasattr(cls, "OP_PARAMS"),
                   msg="%s doesn't have OP_PARAMS" % cls.OP_ID)

      param_names = [name for (name, _, _) in cls.GetAllParams()]

      self.assertEqual(all_slots, param_names)

      # Without inheritance
      self.assertEqual(cls.__slots__, [name for (name, _, _) in cls.OP_PARAMS])

      # This won't work if parameters are converted to a dictionary
      duplicates = utils.FindDuplicates(param_names)
      self.assertFalse(duplicates,
                       msg=("Found duplicate parameters %r in %s" %
                            (duplicates, cls.OP_ID)))

      # Check parameter definitions
      for attr_name, aval, test in cls.GetAllParams():
        self.assert_(attr_name)
        self.assert_(test is None or test is ht.NoType or callable(test),
                     msg=("Invalid type check for %s.%s" %
                          (cls.OP_ID, attr_name)))

        if callable(aval):
          self.assertFalse(callable(aval()),
                           msg="Default value returned by function is callable")

  def testValidateNoModification(self):
    class _TestOp(opcodes.OpCode):
      OP_ID = "OP_TEST"
      OP_PARAMS = [
        ("nodef", ht.NoDefault, ht.TMaybeString),
        ("wdef", "default", ht.TMaybeString),
        ("number", 0, ht.TInt),
        ("notype", None, ht.NoType),
        ]

    # Missing required parameter "nodef"
    op = _TestOp()
    before = op.__getstate__()
    self.assertRaises(errors.OpPrereqError, op.Validate, False)
    self.assertFalse(hasattr(op, "nodef"))
    self.assertFalse(hasattr(op, "wdef"))
    self.assertFalse(hasattr(op, "number"))
    self.assertFalse(hasattr(op, "notype"))
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    # Required parameter "nodef" is provided
    op = _TestOp(nodef="foo")
    before = op.__getstate__()
    op.Validate(False)
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")
    self.assertEqual(op.nodef, "foo")
    self.assertFalse(hasattr(op, "wdef"))
    self.assertFalse(hasattr(op, "number"))
    self.assertFalse(hasattr(op, "notype"))

    # Missing required parameter "nodef"
    op = _TestOp(wdef="hello", number=999)
    before = op.__getstate__()
    self.assertRaises(errors.OpPrereqError, op.Validate, False)
    self.assertFalse(hasattr(op, "nodef"))
    self.assertFalse(hasattr(op, "notype"))
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    # Wrong type for "nodef"
    op = _TestOp(nodef=987)
    before = op.__getstate__()
    self.assertRaises(errors.OpPrereqError, op.Validate, False)
    self.assertEqual(op.nodef, 987)
    self.assertFalse(hasattr(op, "notype"))
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    # Testing different types for "notype"
    op = _TestOp(nodef="foo", notype=[1, 2, 3])
    before = op.__getstate__()
    op.Validate(False)
    self.assertEqual(op.nodef, "foo")
    self.assertEqual(op.notype, [1, 2, 3])
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

    op = _TestOp(nodef="foo", notype="Hello World")
    before = op.__getstate__()
    op.Validate(False)
    self.assertEqual(op.nodef, "foo")
    self.assertEqual(op.notype, "Hello World")
    self.assertEqual(op.__getstate__(), before, msg="Opcode was modified")

  def testValidateSetDefaults(self):
    class _TestOp(opcodes.OpCode):
      OP_ID = "OP_TEST"
      OP_PARAMS = [
        # Static default value
        ("value1", "default", ht.TMaybeString),

        # Default value callback
        ("value2", lambda: "result", ht.TMaybeString),
        ]

    op = _TestOp()
    before = op.__getstate__()
    op.Validate(True)
    self.assertNotEqual(op.__getstate__(), before,
                        msg="Opcode was not modified")
    self.assertEqual(op.value1, "default")
    self.assertEqual(op.value2, "result")
    self.assert_(op.dry_run is None)
    self.assert_(op.debug_level is None)
    self.assertEqual(op.priority, constants.OP_PRIO_DEFAULT)

    op = _TestOp(value1="hello", value2="world", debug_level=123)
    before = op.__getstate__()
    op.Validate(True)
    self.assertNotEqual(op.__getstate__(), before,
                        msg="Opcode was not modified")
    self.assertEqual(op.value1, "hello")
    self.assertEqual(op.value2, "world")
    self.assertEqual(op.debug_level, 123)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
