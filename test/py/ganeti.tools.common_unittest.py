#!/usr/bin/python
#

# Copyright (C) 2015 Google Inc.
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


"""Script for testing ganeti.tools.ssl_update"""

import unittest
import shutil
import tempfile
import os.path
import OpenSSL
import time

from ganeti import constants
from ganeti import errors
from ganeti import serializer
from ganeti import utils
from ganeti.tools import common

import testutils


class TestGenerateClientCert(unittest.TestCase):

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

    self.client_cert = os.path.join(self.tmpdir, "client.pem")

    self.server_cert = os.path.join(self.tmpdir, "server.pem")
    some_serial_no = int(time.time())
    utils.GenerateSelfSignedSslCert(self.server_cert, some_serial_no)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testRegnerateClientCertificate(self):
    my_node_name = "mynode.example.com"
    data = {constants.NDS_CLUSTER_NAME: "winnie_poohs_cluster",
            constants.NDS_NODE_DAEMON_CERTIFICATE: "some_cert",
            constants.NDS_NODE_NAME: my_node_name}

    common.GenerateClientCertificate(data, Exception,
                                     client_cert=self.client_cert,
                                     signing_cert=self.server_cert)

    client_cert_pem = utils.ReadFile(self.client_cert)
    server_cert_pem = utils.ReadFile(self.server_cert)
    client_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                  client_cert_pem)
    signing_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                   server_cert_pem)
    self.assertEqual(client_cert.get_issuer().CN, signing_cert.get_subject().CN)
    self.assertEqual(client_cert.get_subject().CN, my_node_name)


class TestLoadData(unittest.TestCase):

  def testNoJson(self):
    self.assertRaises(errors.ParseError, common.LoadData, Exception, "")
    self.assertRaises(errors.ParseError, common.LoadData, Exception, "}")

  def testInvalidDataStructure(self):
    raw = serializer.DumpJson({
      "some other thing": False,
      })
    self.assertRaises(errors.ParseError, common.LoadData, Exception, raw)

    raw = serializer.DumpJson([])
    self.assertRaises(errors.ParseError, common.LoadData, Exception, raw)

  def testValidData(self):
    raw = serializer.DumpJson({})
    self.assertEqual(common.LoadData(raw, Exception), {})


class TestVerifyClusterName(unittest.TestCase):

  class MyException(Exception):
    pass

  def setUp(self):
    unittest.TestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    unittest.TestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoName(self):
    self.assertRaises(self.MyException, common.VerifyClusterName,
                      {}, self.MyException, "cluster_name",
                      _verify_fn=NotImplemented)

  @staticmethod
  def _FailingVerify(name):
    assert name == "cluster.example.com"
    raise errors.GenericError()

  def testFailingVerification(self):
    data = {
      constants.SSHS_CLUSTER_NAME: "cluster.example.com",
      }

    self.assertRaises(errors.GenericError, common.VerifyClusterName,
                      data, self.MyException, "cluster_name",
                      _verify_fn=self._FailingVerify)


class TestVerifyCertificateStrong(testutils.GanetiTestCase):

  class MyException(Exception):
    pass

  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testNoCert(self):
    self.assertRaises(self.MyException, common.VerifyCertificateStrong,
                      {}, self.MyException, _verify_fn=NotImplemented)

  def testVerificationSuccessWithCert(self):
    common.VerifyCertificateStrong({
      constants.NDS_NODE_DAEMON_CERTIFICATE: "something",
      }, self.MyException, _verify_fn=lambda x,y: None)

  def testNoPrivateKey(self):
    cert_filename = testutils.TestDataFilename("cert1.pem")
    cert_pem = utils.ReadFile(cert_filename)

    self.assertRaises(self.MyException,
                      common._VerifyCertificateStrong,
                      cert_pem, self.MyException, _check_fn=NotImplemented)

  def testInvalidCertificate(self):
    self.assertRaises(self.MyException,
                      common._VerifyCertificateStrong,
                      "Something that's not a certificate",
                      self.MyException,
                      _check_fn=NotImplemented)

  @staticmethod
  def _Check(cert):
    assert cert.get_subject()

  def testSuccessfulCheck(self):
    cert_filename = testutils.TestDataFilename("cert2.pem")
    cert_pem = utils.ReadFile(cert_filename)
    result = \
      common._VerifyCertificateStrong(cert_pem, self.MyException,
                                      _check_fn=self._Check)

    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, result)
    self.assertTrue(cert)

    key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, result)
    self.assertTrue(key)

  def testMismatchingKey(self):
    cert1_path = testutils.TestDataFilename("cert1.pem")
    cert2_path = testutils.TestDataFilename("cert2.pem")

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
      common._VerifyCertificateStrong(cert1_pem + key2_pem, self.MyException,
                                      _check_fn=NotImplemented)
    except self.MyException, err:
      self.assertTrue("not signed with given key" in str(err))
    else:
      self.fail("Exception was not raised")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
