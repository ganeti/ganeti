#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.masterd.iallocator"""

import unittest

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import ht
from ganeti.masterd import iallocator

import testutils


class _StubIAllocator(object):
  def __init__(self, success):
    self.success = success


class TestIAReqMultiInstanceAlloc(unittest.TestCase):
  def testResult(self):
    good_results = [
      # First result (all instances "allocate")
      [
        [["foo", ["a", "b"]],
         ["bar", ["c"]],
         ["baz", []]],
        []
      ],
      # Second result (partial "allocate", partial "fail")
      [
        [["bar", ["c", "b"]],
         ["baz", ["a"]]],
        ["foo"]
      ],
      # Third result (all instances "fail")
      [
        [],
        ["foo", "bar", "baz"]
      ],
      ]
    bad_results = [
      "foobar",
      1234,
      [],
      [[]],
      [[], [], []],
      ]

    result_fn = iallocator.IAReqMultiInstanceAlloc.REQ_RESULT

    self.assertTrue(compat.all(map(result_fn, good_results)))
    self.assertFalse(compat.any(map(result_fn, bad_results)))


class TestIARequestBase(unittest.TestCase):
  def testValidateResult(self):
    class _StubReqBase(iallocator.IARequestBase):
      MODE = constants.IALLOCATOR_MODE_ALLOC
      REQ_RESULT = ht.TBool

    stub = _StubReqBase()
    stub.ValidateResult(_StubIAllocator(True), True)
    self.assertRaises(errors.ResultValidationError, stub.ValidateResult,
                      _StubIAllocator(True), "foo")
    stub.ValidateResult(_StubIAllocator(False), True)
    # We don't validate the result if the iallocation request was not successful
    stub.ValidateResult(_StubIAllocator(False), "foo")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
