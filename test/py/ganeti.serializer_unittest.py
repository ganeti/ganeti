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


import doctest
import unittest

from ganeti import errors
from ganeti import ht
from ganeti import objects
from ganeti import serializer

import testutils


class TestSerializer(testutils.GanetiTestCase):
  """Serializer tests"""

  _TESTDATA = [
    "test",
    255,
    [1, 2, 3],
    (1, 2, 3),
    {"1": 2,
     "foo": "bar"},
    ["abc", 1, 2, 3, 999,
      {
        "a1": ("Hello", "World"),
        "a2": "This is only a test",
        "a3": None,
        "osparams:": serializer.PrivateDict({
                      "foo": 5,
                     })
      }
    ]
  ]

  def _TestSerializer(self, dump_fn, load_fn):
    _dump_fn = lambda data: dump_fn(
      data,
      private_encoder=serializer.EncodeWithPrivateFields
    )
    for data in self._TESTDATA:
      self.failUnless(_dump_fn(data).endswith("\n"))
      self.assertEqualValues(load_fn(_dump_fn(data)), data)

  def testGeneric(self):
    self._TestSerializer(serializer.Dump, serializer.Load)

  def testSignedGeneric(self):
    self._TestSigned(serializer.DumpSigned, serializer.LoadSigned)

  def testJson(self):
    self._TestSerializer(serializer.DumpJson, serializer.LoadJson)

  def testSignedJson(self):
    self._TestSigned(serializer.DumpSignedJson, serializer.LoadSignedJson)

  def _TestSigned(self, dump_fn, load_fn):
    _dump_fn = lambda *args, **kwargs: dump_fn(
      *args,
      private_encoder=serializer.EncodeWithPrivateFields,
      **kwargs
    )
    for data in self._TESTDATA:
      self.assertEqualValues(load_fn(_dump_fn(data, "mykey"), "mykey"),
                             (data, ""))
      self.assertEqualValues(load_fn(_dump_fn(data, "myprivatekey",
                                              salt="mysalt"),
                                     "myprivatekey"),
                             (data, "mysalt"))

      keydict = {
        "mykey_id": "myprivatekey",
        }
      self.assertEqualValues(load_fn(_dump_fn(data, "myprivatekey",
                                              salt="mysalt",
                                              key_selector="mykey_id"),
                                     keydict.get),
                             (data, "mysalt"))
      self.assertRaises(errors.SignatureError, load_fn,
                        _dump_fn(data, "myprivatekey",
                                 salt="mysalt",
                                 key_selector="mykey_id"),
                        {}.get)

    self.assertRaises(errors.SignatureError, load_fn,
                      _dump_fn("test", "myprivatekey"),
                      "myotherkey")

    self.assertRaises(errors.SignatureError, load_fn,
                      serializer.DumpJson("This is a test"), "mykey")
    self.assertRaises(errors.SignatureError, load_fn,
                      serializer.DumpJson({}), "mykey")

    # Message missing salt and HMAC
    tdata = { "msg": "Foo", }
    self.assertRaises(errors.SignatureError, load_fn,
                      serializer.DumpJson(tdata), "mykey")


class TestLoadAndVerifyJson(unittest.TestCase):
  def testNoJson(self):
    self.assertRaises(errors.ParseError, serializer.LoadAndVerifyJson,
                      "", NotImplemented)
    self.assertRaises(errors.ParseError, serializer.LoadAndVerifyJson,
                      "}", NotImplemented)

  def testVerificationFails(self):
    self.assertRaises(errors.ParseError, serializer.LoadAndVerifyJson,
                      "{}", lambda _: False)

    verify_fn = ht.TListOf(ht.TNonEmptyString)
    try:
      serializer.LoadAndVerifyJson("{}", verify_fn)
    except errors.ParseError, err:
      self.assertTrue(str(err).endswith(str(verify_fn)))
    else:
      self.fail("Exception not raised")

  def testSuccess(self):
    self.assertEqual(serializer.LoadAndVerifyJson("{}", ht.TAny), {})
    self.assertEqual(serializer.LoadAndVerifyJson("\"Foo\"", ht.TAny), "Foo")


class TestPrivate(unittest.TestCase):

  def testEquality(self):
    pDict = serializer.PrivateDict()
    pDict["bar"] = "egg"
    nDict = {"bar": "egg"}
    self.assertEqual(pDict, nDict, "PrivateDict-dict equality failure")

  def testPrivateDictUnprivate(self):
    pDict = serializer.PrivateDict()
    pDict["bar"] = "egg"
    uDict = pDict.Unprivate()
    nDict = {"bar": "egg"}
    self.assertEquals(type(uDict), dict,
                      "PrivateDict.Unprivate() did not return a dict")
    self.assertEqual(pDict, uDict, "PrivateDict.Unprivate() equality failure")
    self.assertEqual(nDict, uDict, "PrivateDict.Unprivate() failed to return")

  def testAttributeTransparency(self):
    class Dummy(object):
      pass

    dummy = Dummy()
    dummy.bar = "egg"
    pDummy = serializer.Private(dummy)
    self.assertEqual(pDummy.bar, "egg", "Failed to access attribute of Private")

  def testCallTransparency(self):
    foo = serializer.Private("egg")
    self.assertEqual(foo.upper(), "EGG", "Failed to call Private instance")

  def testFillDict(self):
    pDict = serializer.PrivateDict()
    pDict["bar"] = "egg"
    self.assertEqual(pDict, objects.FillDict({}, pDict))

  def testLeak(self):
    pDict = serializer.PrivateDict()
    pDict["bar"] = "egg"
    self.assertNotIn("egg", str(pDict), "Value leaked in str(PrivateDict)")
    self.assertNotIn("egg", repr(pDict), "Value leaked in repr(PrivateDict)")
    self.assertNotIn("egg", "{0}".format(pDict),
                     "Value leaked in PrivateDict.__format__")
    self.assertNotIn("egg", serializer.Dump(pDict),
                     "Value leaked in serializer.Dump(PrivateDict)")

  def testProperAccess(self):
    pDict = serializer.PrivateDict()
    pDict["bar"] = "egg"

    self.assertIs("egg", pDict["bar"].Get(),
                  "Value not returned by Private.Get()")
    self.assertIs("egg", pDict.GetPrivate("bar"),
                  "Value not returned by Private.GetPrivate()")
    self.assertIs("egg", pDict.Unprivate()["bar"],
                  "Value not returned by PrivateDict.Unprivate()")
    self.assertIn(
      "egg",
      serializer.Dump(pDict,
                      private_encoder=serializer.EncodeWithPrivateFields)
    )

  def testDictGet(self):
    self.assertIs("tar", serializer.PrivateDict().GetPrivate("bar", "tar"),
                  "Private.GetPrivate() did not handle the default case")

  def testZeronessPrivate(self):
    self.assertTrue(serializer.Private("foo"),
                    "Private of non-empty string is false")
    self.assertFalse(serializer.Private(""), "Private empty string is true")


class TestCheckDoctests(unittest.TestCase):

  def testCheckSerializer(self):
    results = doctest.testmod(serializer)
    self.assertEquals(results.failed, 0, "Doctest failures detected")

if __name__ == "__main__":
  testutils.GanetiTestProgram()
