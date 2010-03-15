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

  def _checkSummary(self, op):
    summary = op.Summary()

    if hasattr(op, "OP_DSC_FIELD"):
      self.assert_(("OP_%s" % summary).startswith("%s(" % op.OP_ID))
      self.assert_(summary.endswith(")"))
    else:
      self.assertEqual("OP_%s" % summary, op.OP_ID)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
