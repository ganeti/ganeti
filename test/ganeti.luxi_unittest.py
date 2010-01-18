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
                           ("foo", ["bar", "baz", 123]))

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

  def testParseResponse(self):
    msg = serializer.DumpJson({
      luxi.KEY_SUCCESS: True,
      luxi.KEY_RESULT: None,
      })

    self.assertEqual(luxi.ParseResponse(msg), (True, None))

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

  def testFormatResponse(self):
    for success, result in [(False, "error"), (True, "abc"),
                            (True, { "a": 123, "b": None, })]:
      msg = luxi.FormatResponse(success, result)
      msgdata = serializer.LoadJson(msg)
      self.assert_(luxi.KEY_SUCCESS in msgdata)
      self.assert_(luxi.KEY_RESULT in msgdata)
      self.assertEqualValues(msgdata,
                             { luxi.KEY_SUCCESS: success,
                               luxi.KEY_RESULT: result,
                             })

  def testFormatRequest(self):
    for method, args in [("a", []), ("b", [1, 2, 3])]:
      msg = luxi.FormatRequest(method, args)
      msgdata = serializer.LoadJson(msg)
      self.assert_(luxi.KEY_METHOD in msgdata)
      self.assert_(luxi.KEY_ARGS in msgdata)
      self.assertEqualValues(msgdata,
                             { luxi.KEY_METHOD: method,
                               luxi.KEY_ARGS: args,
                             })


if __name__ == "__main__":
  testutils.GanetiTestProgram()
