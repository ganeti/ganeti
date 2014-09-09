#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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
