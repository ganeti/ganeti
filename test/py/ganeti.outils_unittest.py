#!/usr/bin/python
#

# Copyright (C) 2012, 2013 Google Inc.
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


"""Script for unittesting the outils module"""


import unittest

from ganeti import outils

import testutils


class SlotsAutoSlot(outils.AutoSlots):
  @classmethod
  def _GetSlots(mcs, attr):
    return attr["SLOTS"]


class AutoSlotted(object, metaclass=SlotsAutoSlot):
  SLOTS = ["foo", "bar", "baz"]


class TestAutoSlot(unittest.TestCase):
  def test(self):
    slotted = AutoSlotted()
    self.assertEqual(slotted.__slots__, AutoSlotted.SLOTS)


class TestContainerToDicts(unittest.TestCase):
  def testUnknownType(self):
    for value in [None, 19410, "xyz"]:
      try:
        outils.ContainerToDicts(value)
      except TypeError as err:
        self.assertTrue(str(err).startswith("Unknown container type"))
      else:
        self.fail("Exception was not raised")

  def testEmptyDict(self):
    value = {}
    self.assertFalse(type(value) in outils._SEQUENCE_TYPES)
    self.assertEqual(outils.ContainerToDicts(value), {})

  def testEmptySequences(self):
    for cls in [list, tuple, set, frozenset]:
      self.assertEqual(outils.ContainerToDicts(cls()), [])


class _FakeWithFromDict:
  def FromDict(self, _):
    raise NotImplemented


class TestContainerFromDicts(unittest.TestCase):
  def testUnknownType(self):
    for cls in [str, int, bool]:
      try:
        outils.ContainerFromDicts(None, cls, NotImplemented)
      except TypeError as err:
        self.assertTrue(str(err).startswith("Unknown container type"))
      else:
        self.fail("Exception was not raised")

      try:
        outils.ContainerFromDicts(None, cls(), NotImplemented)
      except TypeError as err:
        self.assertTrue(str(err).endswith("is not a type"))
      else:
        self.fail("Exception was not raised")

  def testEmptyDict(self):
    value = {}
    self.assertFalse(type(value) in outils._SEQUENCE_TYPES)
    self.assertEqual(outils.ContainerFromDicts(value, dict,
                                                    NotImplemented),
                     {})

  def testEmptySequences(self):
    for cls in [list, tuple, set, frozenset]:
      self.assertEqual(outils.ContainerFromDicts([], cls,
                                                      _FakeWithFromDict),
                       cls())


if __name__ == "__main__":
  testutils.GanetiTestProgram()
