#!/usr/bin/python
#

# Copyright (C) 2013 Google Inc.
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


"""Script for unittesting the ganeti.utils.storage module"""

import mock
import os
import shutil
import tempfile
import unittest

from ganeti import constants
from ganeti.utils import security

import testutils


class TestCandidateCerts(unittest.TestCase):

  def setUp(self):
    self._warn_fn = mock.Mock()
    self._info_fn = mock.Mock()
    self._candidate_certs = {}

  def testAddAndRemoveCerts(self):
    self.assertEqual(0, len(self._candidate_certs))

    node_uuid = "1234"
    cert_digest = "foobar"
    security.AddNodeToCandidateCerts(node_uuid, cert_digest,
      self._candidate_certs, warn_fn=self._warn_fn, info_fn=self._info_fn)
    self.assertEqual(1, len(self._candidate_certs))

    # Try adding the same cert again
    security.AddNodeToCandidateCerts(node_uuid, cert_digest,
      self._candidate_certs, warn_fn=self._warn_fn, info_fn=self._info_fn)
    self.assertEqual(1, len(self._candidate_certs))
    self.assertTrue(self._candidate_certs[node_uuid] == cert_digest)

    # Overriding cert
    other_digest = "barfoo"
    security.AddNodeToCandidateCerts(node_uuid, other_digest,
      self._candidate_certs, warn_fn=self._warn_fn, info_fn=self._info_fn)
    self.assertEqual(1, len(self._candidate_certs))
    self.assertTrue(self._candidate_certs[node_uuid] == other_digest)

    # Try removing a certificate from a node that is not in the list
    other_node_uuid = "5678"
    security.RemoveNodeFromCandidateCerts(
      other_node_uuid, self._candidate_certs, warn_fn=self._warn_fn)
    self.assertEqual(1, len(self._candidate_certs))

    # Remove a certificate from a node that is in the list
    security.RemoveNodeFromCandidateCerts(
      node_uuid, self._candidate_certs, warn_fn=self._warn_fn)
    self.assertEqual(0, len(self._candidate_certs))


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
