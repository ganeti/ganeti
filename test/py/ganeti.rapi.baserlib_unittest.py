#!/usr/bin/python
#

# Copyright (C) 2011 Google Inc.
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


"""Script for testing ganeti.rapi.baserlib"""

import unittest
import itertools

from ganeti import errors
from ganeti import opcodes
from ganeti import ht
from ganeti import http
from ganeti import compat
from ganeti.rapi import baserlib

import testutils


class TestFillOpcode(unittest.TestCase):
  class OpTest(opcodes.OpCode):
    OP_PARAMS = [
      ("test", None, ht.TMaybeString, None),
      ]

  def test(self):
    for static in [None, {}]:
      op = baserlib.FillOpcode(self.OpTest, {}, static)
      self.assertTrue(isinstance(op, self.OpTest))
      self.assertTrue(op.test is None)

  def testStatic(self):
    op = baserlib.FillOpcode(self.OpTest, {}, {"test": "abc"})
    self.assertTrue(isinstance(op, self.OpTest))
    self.assertEqual(op.test, "abc")

    # Overwrite static parameter
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, {"test": 123}, {"test": "abc"})

  def testType(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, {"test": [1, 2, 3]}, {})

  def testStaticType(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, {}, {"test": [1, 2, 3]})

  def testUnicode(self):
    op = baserlib.FillOpcode(self.OpTest, {u"test": "abc"}, {})
    self.assertTrue(isinstance(op, self.OpTest))
    self.assertEqual(op.test, "abc")

    op = baserlib.FillOpcode(self.OpTest, {}, {u"test": "abc"})
    self.assertTrue(isinstance(op, self.OpTest))
    self.assertEqual(op.test, "abc")

  def testUnknownParameter(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, {"othervalue": 123}, None)

  def testInvalidBody(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, "", None)
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, range(10), None)

  def testRenameBothSpecified(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, { "old": 123, "new": 999, }, None,
                      rename={ "old": "new", })

  def testRename(self):
    value = "Hello World"
    op = baserlib.FillOpcode(self.OpTest, { "data": value, }, None,
                             rename={ "data": "test", })
    self.assertEqual(op.test, value)

  def testRenameStatic(self):
    self.assertRaises(http.HttpBadRequest, baserlib.FillOpcode,
                      self.OpTest, { "data": 0, }, { "test": None, },
                      rename={ "data": "test", })


class TestOpcodeResource(unittest.TestCase):
  @staticmethod
  def _MakeClass(method, attrs):
    return type("Test%s" % method, (baserlib.OpcodeResource, ), attrs)

  @staticmethod
  def _GetMethodAttributes(method):
    attrs = ["%s_OPCODE" % method, "%s_RENAME" % method,
             "%s_ALIASES" % method, "%s_FORBIDDEN" % method,
             "Get%sOpInput" % method.capitalize()]
    assert attrs == dict((opattrs.method, opattrs.GetModifiers())
                         for opattrs in baserlib.OPCODE_ATTRS)[method]
    return attrs

  def test(self):
    for method in baserlib._SUPPORTED_METHODS:
      # Empty handler
      obj = self._MakeClass(method, {})(None, {}, None)
      for m_attr in baserlib.OPCODE_ATTRS:
        for attr in m_attr.GetAll():
          self.assertFalse(hasattr(obj, attr))

      # Direct handler function
      obj = self._MakeClass(method, {
        method: lambda _: None,
        })(None, {}, None)
      self.assertFalse(compat.all(hasattr(obj, attr)
                                  for i in baserlib._SUPPORTED_METHODS
                                  for attr in self._GetMethodAttributes(i)))

      # Let metaclass define handler function
      for opcls in [None, object()]:
        obj = self._MakeClass(method, {
          "%s_OPCODE" % method: opcls,
          })(None, {}, None)
        self.assertTrue(callable(getattr(obj, method)))
        self.assertEqual(getattr(obj, "%s_OPCODE" % method), opcls)
        self.assertFalse(hasattr(obj, "%s_RENAME" % method))
        self.assertFalse(compat.any(hasattr(obj, attr)
                                    for i in baserlib._SUPPORTED_METHODS
                                      if i != method
                                    for attr in self._GetMethodAttributes(i)))

  def testIllegalRename(self):
    class _TClass(baserlib.OpcodeResource):
      PUT_RENAME = None
      def PUT(self): pass

    self.assertRaises(AssertionError, _TClass, None, None, None)

  def testEmpty(self):
    class _Empty(baserlib.OpcodeResource):
      pass

    obj = _Empty(None, {}, None)

    for m_attr in baserlib.OPCODE_ATTRS:
        for attr in m_attr.GetAll():
          self.assertFalse(hasattr(obj, attr))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
