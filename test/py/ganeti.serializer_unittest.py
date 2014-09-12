#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Script for unittesting the serializer module"""


import unittest

from ganeti import serializer
from ganeti import errors
from ganeti import ht

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
                             (data, ""))
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


if __name__ == "__main__":
  testutils.GanetiTestProgram()
