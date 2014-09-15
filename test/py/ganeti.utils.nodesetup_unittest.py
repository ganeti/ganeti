#!/usr/bin/python
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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
    os.chmod(self.tmpname, 0644)

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

  def testSettingOrdering(self):
    utils.SetEtcHostsEntry(self.tmpname, "127.0.0.1", "localhost.localdomain",
                           ["localhost"])

    self.assertFileContent(self.tmpname,
      "# This is a test file for /etc/hosts\n"
      "127.0.0.1\tlocalhost.localdomain localhost\n"
      "192.0.2.1 router gw\n")
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
