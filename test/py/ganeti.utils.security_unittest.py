#!/usr/bin/python3
#

# Copyright (C) 2013 Google Inc.
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


"""Script for unittesting the ganeti.utils.storage module"""

import mock
import os
import shutil
import tempfile
import unittest

from ganeti import constants
from ganeti.utils import security

import testutils


class TestUuidConversion(unittest.TestCase):

  def testUuidConversion(self):
    uuid_as_int = security.UuidToInt("5cd037f4-9587-49c4-a23e-142f8b7e909d")
    self.assertEqual(uuid_as_int, int(uuid_as_int))


class TestGetCertificateDigest(testutils.GanetiTestCase):

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    # certificate file that contains the certificate only
    self._certfilename1 = testutils.TestDataFilename("cert1.pem")
    # (different) certificate file that contains both, certificate
    # and private key
    self._certfilename2 = testutils.TestDataFilename("cert2.pem")

  def testGetCertificateDigest(self):
    digest1 = security.GetCertificateDigest(
      cert_filename=self._certfilename1)
    digest2 = security.GetCertificateDigest(
      cert_filename=self._certfilename2)
    self.assertFalse(digest1 == digest2)


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    security.VerifyCertificate(testutils.TestDataFilename("cert1.pem"))

    nonexist_filename = os.path.join(self.tmpdir, "does-not-exist")

    (errcode, msg) = security.VerifyCertificate(nonexist_filename)
    self.assertEqual(errcode, constants.CV_ERROR)

    # Try to load non-certificate file
    invalid_cert = testutils.TestDataFilename("bdev-net.txt")
    (errcode, msg) = security.VerifyCertificate(invalid_cert)
    self.assertEqual(errcode, constants.CV_ERROR)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
