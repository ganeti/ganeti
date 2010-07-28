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
import shutil
import tempfile
import unittest

from ganeti import utils
from ganeti import constants
from ganeti import backend
from ganeti import netutils

import testutils


class TestX509Certificates(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def test(self):
    (name, cert_pem) = backend.CreateX509Certificate(300, cryptodir=self.tmpdir)

    self.assertEqual(utils.ReadFile(os.path.join(self.tmpdir, name,
                                                 backend._X509_CERT_FILE)),
                     cert_pem)
    self.assert_(0 < os.path.getsize(os.path.join(self.tmpdir, name,
                                                  backend._X509_KEY_FILE)))

    (name2, cert_pem2) = \
      backend.CreateX509Certificate(300, cryptodir=self.tmpdir)

    backend.RemoveX509Certificate(name, cryptodir=self.tmpdir)
    backend.RemoveX509Certificate(name2, cryptodir=self.tmpdir)

    self.assertEqual(utils.ListVisibleFiles(self.tmpdir), [])

  def testNonEmpty(self):
    (name, _) = backend.CreateX509Certificate(300, cryptodir=self.tmpdir)

    utils.WriteFile(utils.PathJoin(self.tmpdir, name, "hello-world"),
                    data="Hello World")

    self.assertRaises(backend.RPCFail, backend.RemoveX509Certificate,
                      name, cryptodir=self.tmpdir)

    self.assertEqual(utils.ListVisibleFiles(self.tmpdir), [name])


class TestNodeVerify(testutils.GanetiTestCase):
  def testMasterIPLocalhost(self):
    # this a real functional test, but requires localhost to be reachable
    local_data = (netutils.Hostname.GetSysName(),
                  constants.IP4_ADDRESS_LOCALHOST)
    result = backend.VerifyNode({constants.NV_MASTERIP: local_data}, None)
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failUnless(result[constants.NV_MASTERIP], "Cannot reach localhost")

  def testMasterIPUnreachable(self):
    # Network 192.0.2.0/24 is reserved for test/documentation as per
    # RFC 5737
    bad_data =  ("master.example.com", "192.0.2.1")
    # we just test that whatever TcpPing returns, VerifyNode returns too
    netutils.TcpPing = lambda a, b, source=None: False
    result = backend.VerifyNode({constants.NV_MASTERIP: bad_data}, None)
    self.failUnless(constants.NV_MASTERIP in result,
                    "Master IP data not returned")
    self.failIf(result[constants.NV_MASTERIP],
                "Result from netutils.TcpPing corrupted")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
