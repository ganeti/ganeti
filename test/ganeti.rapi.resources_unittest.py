#!/usr/bin/python
#

# Copyright (C) 2007, 2008 Google Inc.
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
