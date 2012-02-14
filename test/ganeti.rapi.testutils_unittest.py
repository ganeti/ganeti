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


"""Script for testing ganeti.rapi.testutils"""

import unittest

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import opcodes
from ganeti import rapi

import ganeti.rapi.testutils

import testutils


class TestHideInternalErrors(unittest.TestCase):
  def test(self):
    def inner():
      raise errors.GenericError("error")

    fn = rapi.testutils._HideInternalErrors(inner)

    self.assertRaises(rapi.testutils.VerificationError, fn)


class TestVerifyOpInput(unittest.TestCase):
  def testUnknownOpId(self):
    voi = rapi.testutils.VerifyOpInput

    self.assertRaises(rapi.testutils.VerificationError, voi, "UNK_OP_ID", None)

  def testUnknownParameter(self):
    voi = rapi.testutils.VerifyOpInput

    self.assertRaises(rapi.testutils.VerificationError, voi,
      opcodes.OpClusterRename.OP_ID, {
      "unk": "unk",
      })

  def testWrongParameterValue(self):
    voi = rapi.testutils.VerifyOpInput
    self.assertRaises(rapi.testutils.VerificationError, voi,
      opcodes.OpClusterRename.OP_ID, {
      "name": object(),
      })

  def testSuccess(self):
    voi = rapi.testutils.VerifyOpInput
    voi(opcodes.OpClusterRename.OP_ID, {
      "name": "new-name.example.com",
      })


class TestVerifyOpResult(unittest.TestCase):
  def testSuccess(self):
    vor = rapi.testutils.VerifyOpResult

    vor(opcodes.OpClusterVerify.OP_ID, {
      constants.JOB_IDS_KEY: [
        (False, "error message"),
        ],
      })

  def testWrongResult(self):
    vor = rapi.testutils.VerifyOpResult

    self.assertRaises(rapi.testutils.VerificationError, vor,
      opcodes.OpClusterVerify.OP_ID, [])

  def testNoResultCheck(self):
    vor = rapi.testutils.VerifyOpResult

    assert opcodes.OpTestDummy.OP_RESULT is None

    vor(opcodes.OpTestDummy.OP_ID, None)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
