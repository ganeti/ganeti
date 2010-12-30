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

import testutils


class TestOpcodes(unittest.TestCase):
  def test(self):
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, None)
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, "")
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, {})
    self.assertRaises(ValueError, opcodes.OpCode.LoadOpCode, {"OP_ID": ""})

    for cls in opcodes.OP_MAPPING.values():
      self.assert_(cls.OP_ID.startswith("OP_"))
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
