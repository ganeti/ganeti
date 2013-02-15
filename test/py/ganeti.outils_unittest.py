#!/usr/bin/python
#

# Copyright (C) 2012, 2013 Google Inc.
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


"""Script for unittesting the outils module"""


import unittest

from ganeti import outils

import testutils


class SlotsAutoSlot(outils.AutoSlots):
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
        outils.ContainerToDicts(value)
      except TypeError, err:
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
      except TypeError, err:
        self.assertTrue(str(err).startswith("Unknown container type"))
      else:
        self.fail("Exception was not raised")

      try:
        outils.ContainerFromDicts(None, cls(), NotImplemented)
      except TypeError, err:
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
