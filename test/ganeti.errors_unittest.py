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
      self.assert_(errors.GetErrorClass(name) is cls)

  def testEncodeException(self):
    self.assertEqualValues(errors.EncodeException(Exception("Foobar")),
                           ("Exception", ("Foobar", )))
    err = errors.GenericError(True, 100, "foo", ["x", "y"])
    self.assertEqualValues(errors.EncodeException(err),
                           ("GenericError", (True, 100, "foo", ["x", "y"])))

  def testMaybeRaise(self):
    # These shouldn't raise
    for i in [None, 1, 2, 3, "Hello World", (1, ), (1, 2, 3),
              ("NoErrorClassName", []), ("NoErrorClassName", None),
              ("GenericError", [1, 2, 3], None), ("GenericError", 1)]:
      errors.MaybeRaise(i)

    self.assertRaises(errors.GenericError, errors.MaybeRaise,
                      ("GenericError", ["Hello"]))

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
