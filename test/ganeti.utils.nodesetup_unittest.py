#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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


"""Script for testing ganeti.utils.nodesetup"""

import os
import tempfile
import unittest

from ganeti import constants
from ganeti import utils

import testutils


class TestEtcHosts(testutils.GanetiTestCase):
  """Test functions modifying /etc/hosts"""

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpname = self._CreateTempFile()
    handle = open(self.tmpname, "w")
    try:
      handle.write("# This is a test file for /etc/hosts\n")
      handle.write("127.0.0.1\tlocalhost\n")
      handle.write("192.0.2.1 router gw\n")
    finally:
      handle.close()

  def testSettingNewIp(self):
    utils.SetEtcHostsEntry(self.tmpname, "198.51.100.4", "myhost.example.com",
                           ["myhost"])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router gw\n"
      "198.51.100.4\tmyhost.example.com myhost\n")
    self.assertFileMode(self.tmpname, 0644)

  def testSettingExistingIp(self):
    utils.SetEtcHostsEntry(self.tmpname, "192.0.2.1", "myhost.example.com",
                           ["myhost"])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1\tmyhost.example.com myhost\n")
    self.assertFileMode(self.tmpname, 0644)

  def testSettingDuplicateName(self):
    utils.SetEtcHostsEntry(self.tmpname, "198.51.100.4", "myhost", ["myhost"])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router gw\n"
      "198.51.100.4\tmyhost\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingExistingHost(self):
    utils.RemoveEtcHostsEntry(self.tmpname, "router")

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 gw\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingSingleExistingHost(self):
    utils.RemoveEtcHostsEntry(self.tmpname, "localhost")

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "192.0.2.1 router gw\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingNonExistingHost(self):
    utils.RemoveEtcHostsEntry(self.tmpname, "myhost")

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router gw\n")
    self.assertFileMode(self.tmpname, 0644)

  def testRemovingAlias(self):
    utils.RemoveEtcHostsEntry(self.tmpname, "gw")

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost\n"
      "192.0.2.1 router\n")
    self.assertFileMode(self.tmpname, 0644)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
