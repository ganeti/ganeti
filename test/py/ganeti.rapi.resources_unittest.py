#!/usr/bin/python
#

# Copyright (C) 2007, 2008 Google Inc.
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


"""Script for unittesting the RAPI resources module"""


import unittest
import tempfile

from ganeti import errors
from ganeti import http

from ganeti.rapi import connector
from ganeti.rapi import rlib2

import testutils


class MapperTests(unittest.TestCase):
  """Tests for remote API URI mapper."""

  def setUp(self):
    self.map = connector.Mapper()

  def _TestUri(self, uri, result):
    self.assertEquals(self.map.getController(uri), result)

  def _TestFailingUri(self, uri):
    self.failUnlessRaises(http.HttpNotFound, self.map.getController, uri)

  def testMapper(self):
    """Testing Mapper"""

    self._TestFailingUri("/tags")
    self._TestFailingUri("/instances")
    self._TestUri("/version", (rlib2.R_version, [], {}))

    self._TestUri("/2/instances/www.test.com",
                  (rlib2.R_2_instances_name,
                   ["www.test.com"],
                   {}))

    self._TestUri("/2/instances/www.test.com/tags?f=5&f=6&alt=html",
                  (rlib2.R_2_instances_name_tags,
                   ["www.test.com"],
                   {"alt": ["html"],
                    "f": ["5", "6"],
                   }))

    self._TestFailingUri("/tag")
    self._TestFailingUri("/instances/does/not/exist")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
