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
# 0.0510-1301, USA.


"""Script for unittesting the backend module"""


import os
import unittest
import time
import tempfile
import shutil

from ganeti import backend
from ganeti import constants
from ganeti import utils

import testutils


class TestNodeVerify(testutils.GanetiTestCase):
  def testMasterIPLocalhost(self):
    # this a real functional test, but requires localhost to be reachable
    local_data = (utils.HostInfo().name, constants.LOCALHOST_IP_ADDRESS)
    result = backend.VerifyNode({constants.NV_MASTERIP: local_data}, None)
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failUnless(result[constants.NV_MASTERIP], "Cannot reach localhost")

  def testMasterIPUnreachable(self):
    # Network 192.0.2.0/24 is reserved for test/documentation as per
    # RFC 5735
    bad_data =  ("master.example.com", "192.0.2.1")
    # we just test that whatever TcpPing returns, VerifyNode returns too
    utils.TcpPing = lambda a, b, source=None: False
    result = backend.VerifyNode({constants.NV_MASTERIP: bad_data}, None)
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failIf(result[constants.NV_MASTERIP],
                "Result from utils.TcpPing corrupted")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
