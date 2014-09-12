#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.jstore"""

import re
import unittest
import random

from ganeti import constants
from ganeti import utils
from ganeti import compat
from ganeti import errors
from ganeti import jstore

import testutils


class TestFormatJobID(testutils.GanetiTestCase):
  def test(self):
    self.assertEqual(jstore.FormatJobID(0), 0)
    self.assertEqual(jstore.FormatJobID(30498), 30498)
    self.assertEqual(jstore.FormatJobID(319472592764518609),
                     319472592764518609)

  def testErrors(self):
    for i in [-1, -2288, -9667, -0.205641, 0.0, 0.1, 13041.4472, "", "Hello",
              [], [1], {}]:
      self.assertRaises(errors.ProgrammerError, jstore.FormatJobID, i)


class TestGetArchiveDirectory(testutils.GanetiTestCase):
  def test(self):
    tests = [
      ("0", [0, 1, 3343, 9712, 9999]),
      ("1", [10000, 13188, 19999]),
      ("29", [290000, 296041, 298796, 299999]),
      ("30", [300000, 309384]),
      ]

    for (exp, job_ids) in tests:
      for job_id in job_ids:
        fmt_id = jstore.FormatJobID(job_id)
        self.assertEqual(jstore.GetArchiveDirectory(fmt_id), exp)
        self.assertEqual(jstore.ParseJobId(fmt_id), job_id)

  def testErrors(self):
    self.assertRaises(errors.ParameterError, jstore.GetArchiveDirectory, None)
    self.assertRaises(errors.ParameterError, jstore.GetArchiveDirectory, "foo")


class TestParseJobId(testutils.GanetiTestCase):
  def test(self):
    self.assertEqual(jstore.ParseJobId(29981), 29981)
    self.assertEqual(jstore.ParseJobId("12918"), 12918)

  def testErrors(self):
    self.assertRaises(errors.ParameterError, jstore.ParseJobId, "")
    self.assertRaises(errors.ParameterError, jstore.ParseJobId, "MXXI")
    self.assertRaises(errors.ParameterError, jstore.ParseJobId, [])


class TestReadNumericFile(testutils.GanetiTestCase):
  def testNonExistingFile(self):
    result = jstore._ReadNumericFile("/tmp/this/file/does/not/exist")
    self.assertTrue(result is None)

  def testValidFile(self):
    tmpfile = self._CreateTempFile()

    for (data, exp) in [("123", 123), ("0\n", 0)]:
      utils.WriteFile(tmpfile, data=data)
      result = jstore._ReadNumericFile(tmpfile)
      self.assertEqual(result, exp)

  def testInvalidContent(self):
    tmpfile = self._CreateTempFile()
    utils.WriteFile(tmpfile, data="{wrong content")
    self.assertRaises(errors.JobQueueError, jstore._ReadNumericFile, tmpfile)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
