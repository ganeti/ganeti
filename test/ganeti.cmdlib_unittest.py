#!/usr/bin/python
#

# Copyright (C) 2008 Google Inc.
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


"""Script for unittesting the cmdlib module"""


import os
import unittest
import time
import tempfile
import shutil

from ganeti import cmdlib
from ganeti import errors

import testutils


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    cmdlib._VerifyCertificate(self._TestDataFilename("cert1.pem"))

    nonexist_filename = os.path.join(self.tmpdir, "does-not-exist")

    (errcode, msg) = cmdlib._VerifyCertificate(nonexist_filename)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    # Try to load non-certificate file
    invalid_cert = self._TestDataFilename("bdev-net1.txt")
    (errcode, msg) = cmdlib._VerifyCertificate(invalid_cert)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)


class TestVerifyCertificateInner(unittest.TestCase):
  FAKEFILE = "/tmp/fake/cert/file.pem"

  def test(self):
    vci = cmdlib._VerifyCertificateInner

    # Valid
    self.assertEqual(vci(self.FAKEFILE, False, 1263916313, 1298476313,
                         1266940313, warn_days=30, error_days=7),
                     (None, None))

    # Not yet valid
    (errcode, msg) = vci(self.FAKEFILE, False, 1266507600, 1267544400,
                         1266075600, warn_days=30, error_days=7)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_WARNING)

    # Expiring soon
    (errcode, msg) = vci(self.FAKEFILE, False, 1266507600, 1267544400,
                         1266939600, warn_days=30, error_days=7)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    (errcode, msg) = vci(self.FAKEFILE, False, 1266507600, 1267544400,
                         1266939600, warn_days=30, error_days=1)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_WARNING)

    (errcode, msg) = vci(self.FAKEFILE, False, 1266507600, None,
                         1266939600, warn_days=30, error_days=7)
    self.assertEqual(errcode, None)

    # Expired
    (errcode, msg) = vci(self.FAKEFILE, True, 1266507600, 1267544400,
                         1266939600, warn_days=30, error_days=7)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    (errcode, msg) = vci(self.FAKEFILE, True, None, 1267544400,
                         1266939600, warn_days=30, error_days=7)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    (errcode, msg) = vci(self.FAKEFILE, True, 1266507600, None,
                         1266939600, warn_days=30, error_days=7)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)

    (errcode, msg) = vci(self.FAKEFILE, True, None, None,
                         1266939600, warn_days=30, error_days=7)
    self.assertEqual(errcode, cmdlib.LUVerifyCluster.ETYPE_ERROR)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
