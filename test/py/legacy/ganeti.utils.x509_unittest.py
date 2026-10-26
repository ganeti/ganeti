#!/usr/bin/python3
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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


"""Script for testing ganeti.utils.x509"""

import datetime
import os
import tempfile
import unittest
import shutil
import string

from cryptography import x509 as cryptography_x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ganeti import constants
from ganeti import utils
from ganeti import errors

import testutils


class TestGetX509CertValidity(testutils.GanetiTestCase):
  def _LoadCert(self, name):
    return cryptography_x509.load_pem_x509_certificate(
      testutils.ReadTestData(name).encode("ascii"))

  def test(self):
    validity = utils.GetX509CertValidity(self._LoadCert("cert1.pem"))
    self.assertEqual(validity, (1519816700, 1519903100))



class TestSignX509Certificate(unittest.TestCase):
  KEY = "My private key!"
  KEY_OTHER = "Another key"

  def test(self):
    # Generate certificate valid for 5 minutes
    (_, cert_pem) = utils.GenerateSelfSignedX509Cert(None, 300, 1)

    cert = cryptography_x509.load_pem_x509_certificate(cert_pem)


    # No signature at all
    self.assertRaises(errors.GenericError,
                      utils.LoadSignedX509Certificate, cert_pem, self.KEY)

    # Invalid input
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Signature: \n", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Sign: $1234$abcdef\n", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      "X-Ganeti-Signature: $1234567890$abcdef\n", self.KEY)
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      b"X-Ganeti-Signature: $1234$abc\n\n" + cert_pem, self.KEY)

    # Invalid salt
    for salt in list("-_@$,:;/\\ \t\n"):
      self.assertRaises(errors.GenericError, utils.SignX509Certificate,
                        cert_pem, self.KEY, "foo%sbar" % salt)

    for salt in ["HelloWorld", "salt", string.ascii_letters, string.digits,
                 utils.GenerateSecret(numbytes=4),
                 utils.GenerateSecret(numbytes=16),
                 "{123:456}".encode("ascii").hex()]:
      signed_pem = utils.SignX509Certificate(cert, self.KEY, salt)

      self._Check(cert, salt, signed_pem)

      self._Check(cert, salt, "X-Another-Header: with a value\n" + signed_pem)
      self._Check(cert, salt, (10 * "Hello World!\n") + signed_pem)
      self._Check(cert, salt, (signed_pem + "\n\na few more\n"
                               "lines----\n------ at\nthe end!"))

  def _Check(self, cert, salt, pem):
    (cert2, salt2) = utils.LoadSignedX509Certificate(pem, self.KEY)
    self.assertEqual(salt, salt2)
    self.assertEqual(cert.fingerprint(hashes.SHA1()),
                     cert2.fingerprint(hashes.SHA1()))

    # Other key
    self.assertRaises(errors.GenericError, utils.LoadSignedX509Certificate,
                      pem, self.KEY_OTHER)


class TestCertVerification(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def testVerifyCertificate(self):
    cert_pem = testutils.ReadTestData("cert1.pem")
    cert = cryptography_x509.load_pem_x509_certificate(
      cert_pem.encode("ascii"))

    # Not checking return value as this certificate is expired
    utils.VerifyX509Certificate(cert, 30, 7)

  @staticmethod
  def _GenCert(key, before, validity):
    # Builds a self-signed certificate with a not_valid_before in the
    # past ("before" < 0) or future ("before" > 0), mirroring the old
    # pyOpenSSL gmtime_adj_notBefore behaviour.
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    not_before = now + datetime.timedelta(seconds=int(before))
    not_after = now + datetime.timedelta(seconds=validity)

    return (
      cryptography_x509.CertificateBuilder()
        .subject_name(cryptography_x509.Name([]))
        .issuer_name(cryptography_x509.Name([]))
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256()))

  def testClockSkew(self):
    SKEW = constants.NODE_MAX_CLOCK_SKEW
    # Create private and public key
    key = rsa.generate_private_key(public_exponent=65537,
                                   key_size=constants.RSA_KEY_BITS)

    validity = 7 * 86400
    # skew small enough, accepting cert; note that this is a timed
    # test, and could fail if the machine is so loaded that the next
    # few lines take more than NODE_MAX_CLOCK_SKEW / 2
    for before in [-1, 0, SKEW // 4, SKEW // 2]:
      cert = self._GenCert(key, before, validity)
      result = utils.VerifyX509Certificate(cert, 1, 2)
      self.assertEqual(result, (None, None))

    # skew too great, not accepting certs
    for before in [SKEW * 2, SKEW * 10]:
      cert = self._GenCert(key, before, validity)
      (status, msg) = utils.VerifyX509Certificate(cert, 1, 2)
      self.assertEqual(status, utils.CERT_WARNING)
      self.assertTrue(msg.startswith("Certificate not yet valid"))


class TestVerifyCertificateInner(unittest.TestCase):
  def test(self):
    vci = utils.x509._VerifyCertificateInner

    # Valid
    self.assertEqual(vci(False, 1263916313, 1298476313, 1266940313, 30, 7),
                     (None, None))

    # Not yet valid
    (errcode, msg) = vci(False, 1266507600, 1267544400, 1266075600, 30, 7)
    self.assertEqual(errcode, utils.CERT_WARNING)

    # Expiring soon
    (errcode, msg) = vci(False, 1266507600, 1267544400, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(False, 1266507600, 1267544400, 1266939600, 30, 1)
    self.assertEqual(errcode, utils.CERT_WARNING)

    (errcode, msg) = vci(False, 1266507600, None, 1266939600, 30, 7)
    self.assertEqual(errcode, None)

    # Expired
    (errcode, msg) = vci(True, 1266507600, 1267544400, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(True, None, 1267544400, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(True, 1266507600, None, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)

    (errcode, msg) = vci(True, None, None, 1266939600, 30, 7)
    self.assertEqual(errcode, utils.CERT_ERROR)


class TestGenerateX509Certs(unittest.TestCase):
  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmpdir)

  def _checkRsaPrivateKey(self, key):
    lines = key.splitlines()
    return (("-----BEGIN RSA PRIVATE KEY-----" in lines and
             "-----END RSA PRIVATE KEY-----" in lines) or
            ("-----BEGIN PRIVATE KEY-----" in lines and
             "-----END PRIVATE KEY-----" in lines))

  def _checkCertificate(self, cert):
    lines = cert.splitlines()
    return ("-----BEGIN CERTIFICATE-----" in lines and
            "-----END CERTIFICATE-----" in lines)

  def test(self):
    for common_name in [None, ".", "Ganeti", "node1.example.com"]:
      (key_pem, cert_pem) = utils.GenerateSelfSignedX509Cert(common_name, 300,
                                                             1)
      self._checkRsaPrivateKey(key_pem)
      self._checkCertificate(cert_pem)

      key = serialization.load_pem_private_key(key_pem, password=None)
      self.assertTrue(key.key_size >= 1024)
      self.assertEqual(key.key_size, constants.RSA_KEY_BITS)
      self.assertTrue(isinstance(key, rsa.RSAPrivateKey))

      x509 = cryptography_x509.load_pem_x509_certificate(cert_pem)
      self.assertEqual(_NameCn(x509.issuer), common_name)
      self.assertEqual(_NameCn(x509.subject), common_name)
      self.assertEqual(x509.public_key().key_size, constants.RSA_KEY_BITS)

  def testLegacy(self):
    cert1_filename = os.path.join(self.tmpdir, "cert1.pem")

    utils.GenerateSelfSignedSslCert(cert1_filename, 1, validity=1)

    cert1 = utils.ReadFile(cert1_filename)

    self.assertTrue(self._checkRsaPrivateKey(cert1))
    self.assertTrue(self._checkCertificate(cert1))

  def _checkKeyMatchesCert(self, key, cert):
    return utils.X509CertKeyCheck(cert, key)

  def testSignedSslCertificate(self):
    server_cert_filename = os.path.join(self.tmpdir, "server.pem")
    utils.GenerateSelfSignedSslCert(server_cert_filename, 123456)

    client_hostname = "myhost.example.com"
    client_cert_filename = os.path.join(self.tmpdir, "client.pem")
    utils.GenerateSignedSslCert(client_cert_filename, 666,
        server_cert_filename, common_name=client_hostname)

    client_cert_pem = utils.ReadFile(client_cert_filename)

    self._checkRsaPrivateKey(client_cert_pem)
    self._checkCertificate(client_cert_pem)

    priv_key = serialization.load_pem_private_key(
      client_cert_pem.encode("ascii"), password=None)
    client_cert = cryptography_x509.load_pem_x509_certificate(
      client_cert_pem.encode("ascii"))

    self.assertTrue(self._checkKeyMatchesCert(priv_key, client_cert))
    self.assertEqual(_NameCn(client_cert.issuer), "ganeti.example.com")
    self.assertEqual(_NameCn(client_cert.subject), client_hostname)




def _NameCn(name):
  """Returns the commonName attribute of a cryptography X509 name."""
  attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
  if not attrs:
    return None

  return attrs[0].value


class TestCheckNodeCertificate(testutils.GanetiTestCase):
  def setUp(self):
    testutils.GanetiTestCase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  def tearDown(self):
    testutils.GanetiTestCase.tearDown(self)
    shutil.rmtree(self.tmpdir)

  def testMismatchingKey(self):
    other_cert = testutils.TestDataFilename("cert1.pem")
    node_cert = testutils.TestDataFilename("cert2.pem")

    cert = cryptography_x509.load_pem_x509_certificate(
      utils.ReadFile(other_cert).encode("ascii"))

    try:
      utils.CheckNodeCertificate(cert, _noded_cert_file=node_cert)
    except errors.GenericError as err:
      self.assertEqual(str(err),
                       "Given cluster certificate does not match local key")
    else:
      self.fail("Exception was not raised")

  def testMatchingKey(self):
    cert_filename = testutils.TestDataFilename("cert2.pem")

    # Extract certificate
    cert = cryptography_x509.load_pem_x509_certificate(
      utils.ReadFile(cert_filename).encode("ascii"))

    utils.CheckNodeCertificate(cert, _noded_cert_file=cert_filename)

  def testMissingFile(self):
    cert_path = testutils.TestDataFilename("cert1.pem")
    nodecert = utils.PathJoin(self.tmpdir, "does-not-exist")

    utils.CheckNodeCertificate(NotImplemented, _noded_cert_file=nodecert)

    self.assertFalse(os.path.exists(nodecert))

  def testInvalidCertificate(self):
    tmpfile = utils.PathJoin(self.tmpdir, "cert")
    utils.WriteFile(tmpfile, data="not a certificate")

    self.assertRaises(errors.X509CertError, utils.CheckNodeCertificate,
                      NotImplemented, _noded_cert_file=tmpfile)

  def testNoPrivateKey(self):
    cert = testutils.TestDataFilename("cert1.pem")
    self.assertRaises(errors.X509CertError, utils.CheckNodeCertificate,
                      NotImplemented, _noded_cert_file=cert)

  def testMismatchInNodeCert(self):
    cert1_path = testutils.TestDataFilename("cert1.pem")
    cert2_path = testutils.TestDataFilename("cert2.pem")
    tmpfile = utils.PathJoin(self.tmpdir, "cert")

    # Extract certificate
    cert1 = cryptography_x509.load_pem_x509_certificate(
      utils.ReadFile(cert1_path).encode("ascii"))
    cert1_pem = cert1.public_bytes(serialization.Encoding.PEM)

    # Extract mismatching key
    key2 = serialization.load_pem_private_key(
      utils.ReadFile(cert2_path).encode("ascii"), password=None)
    key2_pem = key2.private_bytes(
      serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
      serialization.NoEncryption())

    # Write to file
    utils.WriteFile(tmpfile, data=cert1_pem + key2_pem)

    try:
      utils.CheckNodeCertificate(cert1, _noded_cert_file=tmpfile)
    except errors.X509CertError as err:
      self.assertEqual(err.args,
                       (tmpfile, "Certificate does not match with private key"))
    else:
      self.fail("Exception was not raised")


if __name__ == "__main__":
  testutils.GanetiTestProgram()
