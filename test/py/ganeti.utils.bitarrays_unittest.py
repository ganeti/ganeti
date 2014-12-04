#!/usr/bin/python
#

# Copyright (C) 2014 Google Inc.
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


"""Script for unittesting the bitarray utility functions"""

import unittest
import testutils
from bitarray import bitarray

from ganeti import errors
from ganeti.utils import bitarrays


_FREE = bitarray("11100010")
_FULL = bitarray("11111111")


class GetFreeSlotTest(unittest.TestCase):
  """Test function that finds a free slot in a bitarray"""

  def testFreeSlot(self):
    self.assertEquals(bitarrays.GetFreeSlot(_FREE), 3)

  def testReservedSlot(self):
    self.assertRaises(errors.GenericError,
                      bitarrays.GetFreeSlot,
                      _FREE, slot=1)

  def testNoFreeSlot(self):
    self.assertRaises(errors.GenericError,
                      bitarrays.GetFreeSlot,
                      _FULL)

  def testGetAndReserveSlot(self):
    self.assertEquals(bitarrays.GetFreeSlot(_FREE, slot=5, reserve=True), 5)
    self.assertEquals(_FREE, bitarray("11100110"))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
