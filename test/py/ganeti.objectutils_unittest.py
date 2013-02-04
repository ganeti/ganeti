#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for unittesting the objectutils module"""


import unittest

from ganeti import objectutils

import testutils


class SlotsAutoSlot(objectutils.AutoSlots):
  @classmethod
  def _GetSlots(mcs, attr):
    return attr["SLOTS"]


class AutoSlotted(object):
  __metaclass__ = SlotsAutoSlot

  SLOTS = ["foo", "bar", "baz"]


class TestAutoSlot(unittest.TestCase):
  def test(self):
    slotted = AutoSlotted()
    self.assertEqual(slotted.__slots__, AutoSlotted.SLOTS)


class TestContainerToDicts(unittest.TestCase):
  def testUnknownType(self):
    for value in [None, 19410, "xyz"]:
      try:
        objectutils.ContainerToDicts(value)
      except TypeError, err:
        self.assertTrue(str(err).startswith("Unknown container type"))
      else:
        self.fail("Exception was not raised")

  def testEmptyDict(self):
    value = {}
    self.assertFalse(type(value) in objectutils._SEQUENCE_TYPES)
    self.assertEqual(objectutils.ContainerToDicts(value), {})

  def testEmptySequences(self):
    for cls in [list, tuple, set, frozenset]:
      self.assertEqual(objectutils.ContainerToDicts(cls()), [])


class _FakeWithFromDict:
  def FromDict(self, _):
    raise NotImplemented


class TestContainerFromDicts(unittest.TestCase):
  def testUnknownType(self):
    for cls in [str, int, bool]:
      try:
        objectutils.ContainerFromDicts(None, cls, NotImplemented)
      except TypeError, err:
        self.assertTrue(str(err).startswith("Unknown container type"))
      else:
        self.fail("Exception was not raised")

      try:
        objectutils.ContainerFromDicts(None, cls(), NotImplemented)
      except TypeError, err:
        self.assertTrue(str(err).endswith("is not a type"))
      else:
        self.fail("Exception was not raised")

  def testEmptyDict(self):
    value = {}
    self.assertFalse(type(value) in objectutils._SEQUENCE_TYPES)
    self.assertEqual(objectutils.ContainerFromDicts(value, dict,
                                                    NotImplemented),
                     {})

  def testEmptySequences(self):
    for cls in [list, tuple, set, frozenset]:
      self.assertEqual(objectutils.ContainerFromDicts([], cls,
                                                      _FakeWithFromDict),
                       cls())


if __name__ == "__main__":
  testutils.GanetiTestProgram()
