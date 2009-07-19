#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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
# 0.0510-1301, USA.


"""Script for unittesting the serializer module"""


import unittest

from ganeti import serializer
from ganeti import errors


class SimplejsonMock(object):
  def dumps(self, data, indent=None):
    return repr(data)

  def loads(self, data):
    return eval(data)


class TestSerializer(unittest.TestCase):
  """Serializer tests"""

  _TESTDATA = [
    "test",
    255,
    [1, 2, 3],
    (1, 2, 3),
    { 1: 2, "foo": "bar", },
    ]

  def setUp(self):
    self._orig_simplejson = serializer.simplejson
    serializer.simplejson = SimplejsonMock()

  def tearDown(self):
    serializer.simplejson = self._orig_simplejson

  def testGeneric(self):
    return self._TestSerializer(serializer.Dump, serializer.Load)

  def testJson(self):
    return self._TestSerializer(serializer.DumpJson, serializer.LoadJson)

  def testSignedMessage(self):
    LoadSigned = serializer.LoadSigned
    DumpSigned = serializer.DumpSigned
    SaltEqualTo = serializer.SaltEqualTo
    SaltIn = serializer.SaltIn
    SaltInRange = serializer.SaltInRange

    for data in self._TESTDATA:
      self.assertEqual(LoadSigned(DumpSigned(data, "mykey"), "mykey"), data)
      self.assertEqual(LoadSigned(
                         DumpSigned(data, "myprivatekey", "mysalt"),
                         "myprivatekey", SaltEqualTo("mysalt")), data)
      self.assertEqual(LoadSigned(
                         DumpSigned(data, "myprivatekey", "mysalt"),
                         "myprivatekey", SaltIn(["notmysalt", "mysalt"])), data)
      self.assertEqual(LoadSigned(
                         DumpSigned(data, "myprivatekey", "12345"),
                         "myprivatekey", SaltInRange(12340, 12346)), data)
    self.assertRaises(errors.SignatureError, serializer.LoadSigned,
                      serializer.DumpSigned("test", "myprivatekey"),
                      "myotherkey")
    self.assertRaises(errors.SignatureError, serializer.LoadSigned,
                      serializer.DumpSigned("test", "myprivatekey", "salt"),
                      "myprivatekey")
    self.assertRaises(errors.SignatureError, serializer.LoadSigned,
                      serializer.DumpSigned("test", "myprivatekey", "salt"),
                      "myprivatekey", SaltIn(["notmysalt", "morenotmysalt"]))
    self.assertRaises(errors.SignatureError, serializer.LoadSigned,
                      serializer.DumpSigned("test", "myprivatekey", "salt"),
                      "myprivatekey", SaltInRange(1, 2))
    self.assertRaises(errors.SignatureError, serializer.LoadSigned,
                      serializer.DumpSigned("test", "myprivatekey", "12345"),
                      "myprivatekey", SaltInRange(1, 2))

  def _TestSerializer(self, dump_fn, load_fn):
    for data in self._TESTDATA:
      self.failUnless(dump_fn(data).endswith("\n"))
      self.failUnlessEqual(load_fn(dump_fn(data)), data)


if __name__ == '__main__':
  unittest.main()
