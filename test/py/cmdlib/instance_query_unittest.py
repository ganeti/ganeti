#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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


"""Tests for LUInstanceFailover and LUInstanceMigrate

"""

from ganeti import opcodes
from ganeti import query

from testsupport import *

import testutils


class TestLUInstanceQuery(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceQuery, self).setUp()

    self.inst = self.cfg.AddNewInstance()
    self.fields = query._BuildInstanceFields().keys()

  def testInvalidInstance(self):
    op = opcodes.OpInstanceQuery(names=["does_not_exist"],
                                 output_fields=self.fields)
    self.ExecOpCodeExpectOpPrereqError(
      op, "Instance 'does_not_exist' not known")

  def testQueryInstance(self):
    op = opcodes.OpInstanceQuery(output_fields=self.fields)
    self.ExecOpCode(op)


class TestLUInstanceQueryData(CmdlibTestCase):
  def setUp(self):
    super(TestLUInstanceQueryData, self).setUp()

    self.inst = self.cfg.AddNewInstance()

  def testQueryInstanceData(self):
    op = opcodes.OpInstanceQueryData()
    self.ExecOpCode(op)

  def testQueryStaticInstanceData(self):
    op = opcodes.OpInstanceQueryData(static=True)
    self.ExecOpCode(op)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
