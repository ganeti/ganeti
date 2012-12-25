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


"""Script for unittesting the luxi module"""


import unittest

from ganeti import constants
from ganeti import errors
from ganeti import luxi
from ganeti import serializer

import testutils


class TestLuxiParsing(testutils.GanetiTestCase):
  def testParseRequest(self):
    msg = serializer.DumpJson({
      luxi.KEY_METHOD: "foo",
      luxi.KEY_ARGS: ("bar", "baz", 123),
      })

    self.assertEqualValues(luxi.ParseRequest(msg),
                           ("foo", ["bar", "baz", 123], None))

    self.assertRaises(luxi.ProtocolError, luxi.ParseRequest,
                      "this\"is {invalid, ]json data")

    # No dict
    self.assertRaises(luxi.ProtocolError, luxi.ParseRequest,
                      serializer.DumpJson(123))

    # Empty dict
    self.assertRaises(luxi.ProtocolError, luxi.ParseRequest,
                      serializer.DumpJson({ }))

    # No arguments
    self.assertRaises(luxi.ProtocolError, luxi.ParseRequest,
                      serializer.DumpJson({ luxi.KEY_METHOD: "foo", }))

    # No method
    self.assertRaises(luxi.ProtocolError, luxi.ParseRequest,
                      serializer.DumpJson({ luxi.KEY_ARGS: [], }))

    # No method or arguments
    self.assertRaises(luxi.ProtocolError, luxi.ParseRequest,
                      serializer.DumpJson({ luxi.KEY_VERSION: 1, }))

  def testParseRequestWithVersion(self):
    msg = serializer.DumpJson({
      luxi.KEY_METHOD: "version",
      luxi.KEY_ARGS: (["some"], "args", 0, "here"),
      luxi.KEY_VERSION: 20100101,
      })

    self.assertEqualValues(luxi.ParseRequest(msg),
                           ("version", [["some"], "args", 0, "here"], 20100101))

  def testParseResponse(self):
    msg = serializer.DumpJson({
      luxi.KEY_SUCCESS: True,
      luxi.KEY_RESULT: None,
      })

    self.assertEqual(luxi.ParseResponse(msg), (True, None, None))

    self.assertRaises(luxi.ProtocolError, luxi.ParseResponse,
                      "this\"is {invalid, ]json data")

    # No dict
    self.assertRaises(luxi.ProtocolError, luxi.ParseResponse,
                      serializer.DumpJson(123))

    # Empty dict
    self.assertRaises(luxi.ProtocolError, luxi.ParseResponse,
                      serializer.DumpJson({ }))

    # No success
    self.assertRaises(luxi.ProtocolError, luxi.ParseResponse,
                      serializer.DumpJson({ luxi.KEY_RESULT: True, }))

    # No result
    self.assertRaises(luxi.ProtocolError, luxi.ParseResponse,
                      serializer.DumpJson({ luxi.KEY_SUCCESS: True, }))

    # No result or success
    self.assertRaises(luxi.ProtocolError, luxi.ParseResponse,
                      serializer.DumpJson({ luxi.KEY_VERSION: 123, }))

  def testParseResponseWithVersion(self):
    msg = serializer.DumpJson({
      luxi.KEY_SUCCESS: True,
      luxi.KEY_RESULT: "Hello World",
      luxi.KEY_VERSION: 19991234,
      })

    self.assertEqual(luxi.ParseResponse(msg), (True, "Hello World", 19991234))

  def testFormatResponse(self):
    for success, result in [(False, "error"), (True, "abc"),
                            (True, { "a": 123, "b": None, })]:
      msg = luxi.FormatResponse(success, result)
      msgdata = serializer.LoadJson(msg)
      self.assert_(luxi.KEY_SUCCESS in msgdata)
      self.assert_(luxi.KEY_RESULT in msgdata)
      self.assert_(luxi.KEY_VERSION not in msgdata)
      self.assertEqualValues(msgdata,
                             { luxi.KEY_SUCCESS: success,
                               luxi.KEY_RESULT: result,
                             })

  def testFormatResponseWithVersion(self):
    for success, result, version in [(False, "error", 123), (True, "abc", 999),
                                     (True, { "a": 123, "b": None, }, 2010)]:
      msg = luxi.FormatResponse(success, result, version=version)
      msgdata = serializer.LoadJson(msg)
      self.assert_(luxi.KEY_SUCCESS in msgdata)
      self.assert_(luxi.KEY_RESULT in msgdata)
      self.assert_(luxi.KEY_VERSION in msgdata)
      self.assertEqualValues(msgdata,
                             { luxi.KEY_SUCCESS: success,
                               luxi.KEY_RESULT: result,
                               luxi.KEY_VERSION: version,
                             })

  def testFormatRequest(self):
    for method, args in [("a", []), ("b", [1, 2, 3])]:
      msg = luxi.FormatRequest(method, args)
      msgdata = serializer.LoadJson(msg)
      self.assert_(luxi.KEY_METHOD in msgdata)
      self.assert_(luxi.KEY_ARGS in msgdata)
      self.assert_(luxi.KEY_VERSION not in msgdata)
      self.assertEqualValues(msgdata,
                             { luxi.KEY_METHOD: method,
                               luxi.KEY_ARGS: args,
                             })

  def testFormatRequestWithVersion(self):
    for method, args, version in [("fn1", [], 123), ("fn2", [1, 2, 3], 999)]:
      msg = luxi.FormatRequest(method, args, version=version)
      msgdata = serializer.LoadJson(msg)
      self.assert_(luxi.KEY_METHOD in msgdata)
      self.assert_(luxi.KEY_ARGS in msgdata)
      self.assert_(luxi.KEY_VERSION in msgdata)
      self.assertEqualValues(msgdata,
                             { luxi.KEY_METHOD: method,
                               luxi.KEY_ARGS: args,
                               luxi.KEY_VERSION: version,
                             })


class TestCallLuxiMethod(unittest.TestCase):
  MY_LUXI_VERSION = 1234
  assert constants.LUXI_VERSION != MY_LUXI_VERSION

  def testSuccessNoVersion(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fn1")
      self.assertEqual(args, "Hello World")
      return luxi.FormatResponse(True, "x")

    result = luxi.CallLuxiMethod(_Cb, "fn1", "Hello World")

  def testServerVersionOnly(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fn1")
      self.assertEqual(args, "Hello World")
      return luxi.FormatResponse(True, "x", version=self.MY_LUXI_VERSION)

    self.assertRaises(errors.LuxiError, luxi.CallLuxiMethod,
                      _Cb, "fn1", "Hello World")

  def testWithVersion(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fn99")
      self.assertEqual(args, "xyz")
      return luxi.FormatResponse(True, "y", version=self.MY_LUXI_VERSION)

    self.assertEqual("y", luxi.CallLuxiMethod(_Cb, "fn99", "xyz",
                                              version=self.MY_LUXI_VERSION))

  def testVersionMismatch(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fn5")
      self.assertEqual(args, "xyz")
      return luxi.FormatResponse(True, "F", version=self.MY_LUXI_VERSION * 2)

    self.assertRaises(errors.LuxiError, luxi.CallLuxiMethod,
                      _Cb, "fn5", "xyz", version=self.MY_LUXI_VERSION)

  def testError(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fnErr")
      self.assertEqual(args, [])
      err = errors.OpPrereqError("Test")
      return luxi.FormatResponse(False, errors.EncodeException(err))

    self.assertRaises(errors.OpPrereqError, luxi.CallLuxiMethod,
                      _Cb, "fnErr", [])

  def testErrorWithVersionMismatch(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fnErr")
      self.assertEqual(args, [])
      err = errors.OpPrereqError("TestVer")
      return luxi.FormatResponse(False, errors.EncodeException(err),
                                 version=self.MY_LUXI_VERSION * 2)

    self.assertRaises(errors.LuxiError, luxi.CallLuxiMethod,
                      _Cb, "fnErr", [],
                      version=self.MY_LUXI_VERSION)

  def testErrorWithVersion(self):
    def _Cb(msg):
      (method, args, version) = luxi.ParseRequest(msg)
      self.assertEqual(method, "fn9")
      self.assertEqual(args, [])
      err = errors.OpPrereqError("TestVer")
      return luxi.FormatResponse(False, errors.EncodeException(err),
                                 version=self.MY_LUXI_VERSION)

    self.assertRaises(errors.OpPrereqError, luxi.CallLuxiMethod,
                      _Cb, "fn9", [],
                      version=self.MY_LUXI_VERSION)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
