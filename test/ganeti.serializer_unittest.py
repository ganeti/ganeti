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
# 02110-1301, USA.


"""Script for unittesting the serializer module"""


import unittest

from ganeti import serializer
from ganeti import errors

import testutils


class TestSerializer(testutils.GanetiTestCase):
  """Serializer tests"""

  _TESTDATA = [
    "test",
    255,
    [1, 2, 3],
    (1, 2, 3),
    { "1": 2, "foo": "bar", },
    ["abc", 1, 2, 3, 999,
      {
        "a1": ("Hello", "World"),
        "a2": "This is only a test",
        "a3": None,
        },
      {
        "foo": "bar",
        },
      ]
    ]

  def _TestSerializer(self, dump_fn, load_fn):
    for data in self._TESTDATA:
      self.failUnless(dump_fn(data).endswith("\n"))
      self.assertEqualValues(load_fn(dump_fn(data)), data)

  def testGeneric(self):
    self._TestSerializer(serializer.Dump, serializer.Load)

  def testSignedGeneric(self):
    self._TestSigned(serializer.DumpSigned, serializer.LoadSigned)

  def testJson(self):
    self._TestSerializer(serializer.DumpJson, serializer.LoadJson)

  def testSignedJson(self):
    self._TestSigned(serializer.DumpSignedJson, serializer.LoadSignedJson)

  def _TestSigned(self, dump_fn, load_fn):
    for data in self._TESTDATA:
      self.assertEqualValues(load_fn(dump_fn(data, "mykey"), "mykey"),
                             (data, ''))
      self.assertEqualValues(load_fn(dump_fn(data, "myprivatekey",
                                             salt="mysalt"),
                                     "myprivatekey"),
                             (data, "mysalt"))

      keydict = {
        "mykey_id": "myprivatekey",
        }
      self.assertEqualValues(load_fn(dump_fn(data, "myprivatekey",
                                             salt="mysalt",
                                             key_selector="mykey_id"),
                                     keydict.get),
                             (data, "mysalt"))
      self.assertRaises(errors.SignatureError, load_fn,
                        dump_fn(data, "myprivatekey",
                                salt="mysalt",
                                key_selector="mykey_id"),
                        {}.get)

    self.assertRaises(errors.SignatureError, load_fn,
                      dump_fn("test", "myprivatekey"),
                      "myotherkey")

    self.assertRaises(errors.SignatureError, load_fn,
                      serializer.DumpJson("This is a test"), "mykey")
    self.assertRaises(errors.SignatureError, load_fn,
                      serializer.DumpJson({}), "mykey")

    # Message missing salt and HMAC
    tdata = { "msg": "Foo", }
    self.assertRaises(errors.SignatureError, load_fn,
                      serializer.DumpJson(tdata), "mykey")


if __name__ == '__main__':
  testutils.GanetiTestProgram()
