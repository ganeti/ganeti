#!/usr/bin/python
#

# Copyright (C) 2010, 2012 Google Inc.
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


"""Script for testing ganeti.backend"""

import os
import sys
import unittest

from ganeti import errors

import testutils


class TestErrors(testutils.GanetiTestCase):
  def testGetErrorClass(self):
    tdata = {
      "": None,
      ".": None,
      "-": None,
      "ECODE_INVAL": None,
      "NoErrorClassName": None,
      "GenericError": errors.GenericError,
      "ProgrammerError": errors.ProgrammerError,
      }

    for name, cls in tdata.items():
      self.assertTrue(errors.GetErrorClass(name) is cls)

  def testEncodeException(self):
    self.assertEqualValues(errors.EncodeException(Exception("Foobar")),
                           ("Exception", ("Foobar", )))
    err = errors.GenericError(True, 100, "foo", ["x", "y"])
    self.assertEqualValues(errors.EncodeException(err),
                           ("GenericError", (True, 100, "foo", ["x", "y"])))

  def testMaybeRaise(self):
    testvals = [None, 1, 2, 3, "Hello World", (1, ), (1, 2, 3),
                ("NoErrorClassName", []), ("NoErrorClassName", None),
                ("GenericError", [1, 2, 3], None), ("GenericError", 1)]
    # These shouldn't raise
    for i in testvals:
      errors.MaybeRaise(i)

    self.assertRaises(errors.GenericError, errors.MaybeRaise,
                      ("GenericError", ["Hello"]))
    # Check error encoding
    for i in testvals:
      src = errors.GenericError(i)
      try:
        errors.MaybeRaise(errors.EncodeException(src))
      except errors.GenericError as dst:
        self.assertEqual(src.args, dst.args)
        self.assertEqual(src.__class__, dst.__class__)
      else:
        self.fail("Exception %s not raised" % repr(src))

  def testGetEncodedError(self):
    self.assertEqualValues(errors.GetEncodedError(["GenericError",
                                                   ("Hello", 123, "World")]),
                           (errors.GenericError, ("Hello", 123, "World")))
    self.assertEqualValues(errors.GetEncodedError(["GenericError", []]),
                           (errors.GenericError, ()))
    self.assertFalse(errors.GetEncodedError(["NoErrorClass",
                                             ("Hello", 123, "World")]))


if __name__ == "__main__":
  testutils.GanetiTestProgram()
