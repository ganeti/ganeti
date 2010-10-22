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


"""Script for testing ganeti.query"""

import re
import unittest

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti import query
from ganeti import objects

import testutils


class TestConstants(unittest.TestCase):
  def test(self):
    self.assertEqual(set(query._VERIFY_FN.keys()),
                     constants.QFT_ALL)


class _QueryData:
  def __init__(self, data, **kwargs):
    self.data = data

    for name, value in kwargs.items():
      setattr(self, name, value)

  def __iter__(self):
    return iter(self.data)


def _GetDiskSize(nr, ctx, item):
  disks = item["disks"]
  try:
    return (constants.QRFS_NORMAL, disks[nr])
  except IndexError:
    return (constants.QRFS_UNAVAIL, None)


class TestQuery(unittest.TestCase):
  def test(self):
    (STATIC, DISK) = range(10, 12)

    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT),
       STATIC, lambda ctx, item: (constants.QRFS_NORMAL, item["name"])),
      (query._MakeField("master", "Master", constants.QFT_BOOL),
       STATIC, lambda ctx, item: (constants.QRFS_NORMAL,
                                  ctx.mastername == item["name"])),
      ] +
      [(query._MakeField("disk%s.size" % i, "DiskSize%s" % i,
                         constants.QFT_UNIT),
        DISK, compat.partial(_GetDiskSize, i))
       for i in range(4)])

    q = query.Query(fielddef, ["name"])
    self.assertEqual(q.RequestedData(), set([STATIC]))
    self.assertEqual(len(q._fields), 1)
    self.assertEqual(len(q.GetFields()), 1)
    self.assertEqual(q.GetFields()[0].ToDict(),
      objects.QueryFieldDefinition(name="name",
                                   title="Name",
                                   kind=constants.QFT_TEXT).ToDict())

    # Create data only once query has been prepared
    data = [
      { "name": "node1", "disks": [0, 1, 2], },
      { "name": "node2", "disks": [3, 4], },
      { "name": "node3", "disks": [5, 6, 7], },
      ]

    self.assertEqual(q.Query(_QueryData(data, mastername="node3")),
                     [[(constants.QRFS_NORMAL, "node1")],
                      [(constants.QRFS_NORMAL, "node2")],
                      [(constants.QRFS_NORMAL, "node3")]])
    self.assertEqual(q.OldStyleQuery(_QueryData(data, mastername="node3")),
                     [["node1"], ["node2"], ["node3"]])

    q = query.Query(fielddef, ["name", "master"])
    self.assertEqual(q.RequestedData(), set([STATIC]))
    self.assertEqual(len(q._fields), 2)
    self.assertEqual(q.Query(_QueryData(data, mastername="node3")),
                     [[(constants.QRFS_NORMAL, "node1"),
                       (constants.QRFS_NORMAL, False)],
                      [(constants.QRFS_NORMAL, "node2"),
                       (constants.QRFS_NORMAL, False)],
                      [(constants.QRFS_NORMAL, "node3"),
                       (constants.QRFS_NORMAL, True)],
                     ])

    q = query.Query(fielddef, ["name", "master", "disk0.size"])
    self.assertEqual(q.RequestedData(), set([STATIC, DISK]))
    self.assertEqual(len(q._fields), 3)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[(constants.QRFS_NORMAL, "node1"),
                       (constants.QRFS_NORMAL, False),
                       (constants.QRFS_NORMAL, 0)],
                      [(constants.QRFS_NORMAL, "node2"),
                       (constants.QRFS_NORMAL, True),
                       (constants.QRFS_NORMAL, 3)],
                      [(constants.QRFS_NORMAL, "node3"),
                       (constants.QRFS_NORMAL, False),
                       (constants.QRFS_NORMAL, 5)],
                     ])

    # With unknown column
    q = query.Query(fielddef, ["disk2.size", "disk1.size", "disk99.size",
                               "disk0.size"])
    self.assertEqual(q.RequestedData(), set([DISK]))
    self.assertEqual(len(q._fields), 4)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[(constants.QRFS_NORMAL, 2),
                       (constants.QRFS_NORMAL, 1),
                       (constants.QRFS_UNKNOWN, None),
                       (constants.QRFS_NORMAL, 0)],
                      [(constants.QRFS_UNAVAIL, None),
                       (constants.QRFS_NORMAL, 4),
                       (constants.QRFS_UNKNOWN, None),
                       (constants.QRFS_NORMAL, 3)],
                      [(constants.QRFS_NORMAL, 7),
                       (constants.QRFS_NORMAL, 6),
                       (constants.QRFS_UNKNOWN, None),
                       (constants.QRFS_NORMAL, 5)],
                     ])
    self.assertRaises(errors.OpPrereqError, q.OldStyleQuery,
                      _QueryData(data, mastername="node2"))
    self.assertEqual([fdef.ToDict() for fdef in q.GetFields()], [
                     { "name": "disk2.size", "title": "DiskSize2",
                       "kind": constants.QFT_UNIT, },
                     { "name": "disk1.size", "title": "DiskSize1",
                       "kind": constants.QFT_UNIT, },
                     { "name": "disk99.size", "title": "disk99.size",
                       "kind": constants.QFT_UNKNOWN, },
                     { "name": "disk0.size", "title": "DiskSize0",
                       "kind": constants.QFT_UNIT, },
                     ])

    # Empty query
    q = query.Query(fielddef, [])
    self.assertEqual(q.RequestedData(), set([]))
    self.assertEqual(len(q._fields), 0)
    self.assertEqual(q.Query(_QueryData(data, mastername="node2")),
                     [[], [], []])
    self.assertEqual(q.OldStyleQuery(_QueryData(data, mastername="node2")),
                     [[], [], []])
    self.assertEqual(q.GetFields(), [])

  def testPrepareFieldList(self):
    # Duplicate titles
    for (a, b) in [("name", "name"), ("NAME", "name")]:
      self.assertRaises(AssertionError, query._PrepareFieldList, [
        (query._MakeField("name", b, constants.QFT_TEXT), None,
         lambda *args: None),
        (query._MakeField("other", a, constants.QFT_TEXT), None,
         lambda *args: None),
        ])

    # Non-lowercase names
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("NAME", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ])
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("Name", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # Empty name
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("", "Name", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # Empty title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # Whitespace in title
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Co lu mn", constants.QFT_TEXT), None,
       lambda *args: None),
      ])

    # No callable function
    self.assertRaises(AssertionError, query._PrepareFieldList, [
      (query._MakeField("name", "Name", constants.QFT_TEXT), None, None),
      ])

  def testUnknown(self):
    fielddef = query._PrepareFieldList([
      (query._MakeField("name", "Name", constants.QFT_TEXT),
       None, lambda _, item: (constants.QRFS_NORMAL, "name%s" % item)),
      (query._MakeField("other0", "Other0", constants.QFT_TIMESTAMP),
       None, lambda *args: (constants.QRFS_NORMAL, 1234)),
      (query._MakeField("nodata", "NoData", constants.QFT_NUMBER),
       None, lambda *args: (constants.QRFS_NODATA, None)),
      (query._MakeField("unavail", "Unavail", constants.QFT_BOOL),
       None, lambda *args: (constants.QRFS_UNAVAIL, None)),
      ])

    for selected in [["foo"], ["Hello", "World"],
                     ["name1", "other", "foo"]]:
      q = query.Query(fielddef, selected)
      self.assertEqual(len(q._fields), len(selected))
      self.assert_(compat.all(len(row) == len(selected)
                              for row in q.Query(_QueryData(range(1, 10)))))
      self.assertEqual(q.Query(_QueryData(range(1, 10))),
                       [[(constants.QRFS_UNKNOWN, None)] * len(selected)
                        for i in range(1, 10)])
      self.assertEqual([fdef.ToDict() for fdef in q.GetFields()],
                       [{ "name": name, "title": name,
                          "kind": constants.QFT_UNKNOWN, }
                        for name in selected])

    q = query.Query(fielddef, ["name", "other0", "nodata", "unavail"])
    self.assertEqual(len(q._fields), 4)
    self.assertEqual(q.OldStyleQuery(_QueryData(range(1, 10))), [
                     ["name%s" % i, 1234, None, None]
                     for i in range(1, 10)
                     ])

    q = query.Query(fielddef, ["name", "other0", "nodata", "unavail", "unk"])
    self.assertEqual(len(q._fields), 5)
    self.assertEqual(q.Query(_QueryData(range(1, 10))),
                     [[(constants.QRFS_NORMAL, "name%s" % i),
                       (constants.QRFS_NORMAL, 1234),
                       (constants.QRFS_NODATA, None),
                       (constants.QRFS_UNAVAIL, None),
                       (constants.QRFS_UNKNOWN, None)]
                      for i in range(1, 10)])


if __name__ == "__main__":
  testutils.GanetiTestProgram()
