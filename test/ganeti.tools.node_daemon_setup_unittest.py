#!/usr/bin/python
#

# Copyright (C) 2012 Google Inc.
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


"""Script for testing ganeti.tools.node_daemon_setup"""

import unittest
import shutil
import tempfile
import os.path
import OpenSSL

from ganeti import errors
from ganeti import constants
from ganeti import serializer
from ganeti import pathutils
from ganeti import compat
from ganeti import utils
from ganeti.tools import node_daemon_setup

import testutils


_SetupError = node_daemon_setup.SetupError


class TestLoadData(unittest.TestCase):
  def testNoJson(self):
    for data in ["", "{", "}"]:
      self.assertRaises(errors.ParseError, node_daemon_setup.LoadData, data)

  def testInvalidDataStructure(self):
    raw = serializer.DumpJson({
      "some other thing": False,
      })
    self.assertRaises(errors.ParseError, node_daemon_setup.LoadData, raw)

    raw = serializer.DumpJson([])
    self.assertRaises(errors.ParseError, node_daemon_setup.LoadData, raw)

  def testValidData(self):
    raw = serializer.DumpJson({})
    self.assertEqual(node_daemon_setup.LoadData(raw), {})


class TestVerifyCertificate(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoCert(self):
    self.assertRaises(_SetupError, node_daemon_setup.VerifyCertificate,
                      {}, _verify_fn=NotImplemented)

  def testVerificationSuccessWithCert(self):
    node_daemon_setup.VerifyCertificate({
      constants.NDS_NODE_DAEMON_CERTIFICATE: "something",
      }, _verify_fn=lambda _: None)

  def testNoPrivateKey(self):
    cert_filename = self._TestDataFilename("cert1.pem")
    cert_pem = utils.ReadFile(cert_filename)

    self.assertRaises(errors.X509CertError,
                      node_daemon_setup._VerifyCertificate,
                      cert_pem, _check_fn=NotImplemented)

  def testInvalidCertificate(self):
    self.assertRaises(errors.X509CertError,
                      node_daemon_setup._VerifyCertificate,
                      "Something that's not a certificate",
                      _check_fn=NotImplemented)

  @staticmethod
  def _Check(cert):
    assert cert.get_subject()

  def testSuccessfulCheck(self):
    cert_filename = self._TestDataFilename("cert2.pem")
    cert_pem = utils.ReadFile(cert_filename)
    result = \
      node_daemon_setup._VerifyCertificate(cert_pem, _check_fn=self._Check)
    self.assertTrue("-----BEGIN PRIVATE KEY-----" in result)
    self.assertTrue("-----BEGIN CERTIFICATE-----" in result)

  def testMismatchingKey(self):
    cert1_path = self._TestDataFilename("cert1.pem")
    cert2_path = self._TestDataFilename("cert2.pem")

    # Extract certificate
    cert1 = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                            utils.ReadFile(cert1_path))
    cert1_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                cert1)

    # Extract mismatching key
    key2 = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                          utils.ReadFile(cert2_path))
    key2_pem = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM,
                                              key2)

    try:
      node_daemon_setup._VerifyCertificate(cert1_pem + key2_pem,
                                           _check_fn=NotImplemented)
    except errors.X509CertError, err:
      self.assertEqual(err.args,
                       ("(stdin)", "Certificate is not signed with given key"))
    else:
      self.fail("Exception was not raised")


class TestVerifyClusterName(unittest.TestCase):
  def setUp(self):
    unittest.TestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoName(self):
    self.assertRaises(_SetupError, node_daemon_setup.VerifyClusterName,
                      {}, _verify_fn=NotImplemented)

  @staticmethod
  def _FailingVerify(name):
    assert name == "somecluster.example.com"
    raise errors.GenericError()

  def testFailingVerification(self):
    data = {
      constants.NDS_CLUSTER_NAME: "somecluster.example.com",
      }

    self.assertRaises(errors.GenericError, node_daemon_setup.VerifyClusterName,
                      data, _verify_fn=self._FailingVerify)

  def testSuccess(self):
    data = {
      constants.NDS_CLUSTER_NAME: "cluster.example.com",
      }

    result = \
      node_daemon_setup.VerifyClusterName(data, _verify_fn=lambda _: None)

    self.assertEqual(result, "cluster.example.com")


class TestVerifySsconf(unittest.TestCase):
  def testNoSsconf(self):
    self.assertRaises(_SetupError, node_daemon_setup.VerifySsconf,
                      {}, NotImplemented, _verify_fn=NotImplemented)

    for items in [None, {}]:
      self.assertRaises(_SetupError, node_daemon_setup.VerifySsconf, {
        constants.NDS_SSCONF: items,
        }, NotImplemented, _verify_fn=NotImplemented)

  def _Check(self, names):
    self.assertEqual(frozenset(names), frozenset([
      constants.SS_CLUSTER_NAME,
      constants.SS_INSTANCE_LIST,
      ]))

  def testSuccess(self):
    ssdata = {
      constants.SS_CLUSTER_NAME: "cluster.example.com",
      constants.SS_INSTANCE_LIST: [],
      }

    result = node_daemon_setup.VerifySsconf({
      constants.NDS_SSCONF: ssdata,
      }, "cluster.example.com", _verify_fn=self._Check)

    self.assertEqual(result, ssdata)

    self.assertRaises(_SetupError, node_daemon_setup.VerifySsconf, {
      constants.NDS_SSCONF: ssdata,
      }, "wrong.example.com", _verify_fn=self._Check)

  def testInvalidKey(self):
    self.assertRaises(errors.GenericError, node_daemon_setup.VerifySsconf, {
      constants.NDS_SSCONF: {
        "no-valid-ssconf-key": "value",
        },
      }, NotImplemented)


if __name__ == "__main__":
  testutils.GanetiTestProgram()
