#
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

"""Utility functions for X509.

"""

import calendar
import datetime
import errno
import logging
import re
import time

from cryptography import x509 as cryptography_x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ganeti import errors
from ganeti import constants
from ganeti import pathutils

from ganeti.utils import text as utils_text
from ganeti.utils import io as utils_io
from ganeti.utils import hash as utils_hash


HEX_CHAR_RE = r"[a-zA-Z0-9]"
VALID_X509_SIGNATURE_SALT = re.compile("^%s+$" % HEX_CHAR_RE, re.S)
X509_SIGNATURE = re.compile(r"^%s:\s*(?P<salt>%s+)/(?P<sign>%s+)$" %
                            (re.escape(constants.X509_CERT_SIGNATURE_HEADER),
                             HEX_CHAR_RE, HEX_CHAR_RE),
                            re.S | re.I)

# Certificate verification results
(CERT_WARNING,
 CERT_ERROR) = range(1, 3)

# Map constants to actual hash digests
_SIGN_DIGESTS = {"SHA256": hashes.SHA256}
def _GenerateRsaKey():
  return rsa.generate_private_key(public_exponent=65537,
                                  key_size=constants.RSA_KEY_BITS)


def _BuildCertificate(common_name, validity, serial_no,
                      issuer_name, public_key, is_ca=False,
                      issuer_public_key=None):
  """Builds an X509 certificate template.

  @type common_name: string
  @param common_name: commonName of the certificate's subject
  @type validity: int, seconds from now
  @param validity: Validity of the certificate in seconds
  @type serial_no: int
  @param serial_no: Serial number of the certificate
  @type issuer_name: cryptography.x509.Name
  @param issuer_name: Name of the issuing certificate
  @type public_key: cryptography public key
  @param public_key: Public key of the certificate's subject
  @type is_ca: bool
  @param is_ca: Whether the certificate may act as a CA, i.e. sign other
                certificates; Ganeti's cluster certificate is used both
                as a server certificate and as the CA signing the node
                client certificates
  @type issuer_public_key: cryptography public key or None
  @param issuer_public_key: Public key of the issuer, used to build the
                            authority key identifier extension
  @rtype: cryptography.x509.CertificateBuilder
  @return: The unsigned certificate template

  """
  subject_attrs = []
  if common_name:
    subject_attrs.append(
      cryptography_x509.NameAttribute(NameOID.COMMON_NAME, common_name))

  now = datetime.datetime.now(datetime.timezone.utc)
  builder = (
    cryptography_x509.CertificateBuilder()
      .subject_name(cryptography_x509.Name(subject_attrs))
      .issuer_name(issuer_name)
      .public_key(public_key)
      .serial_number(serial_no)
      .not_valid_before(now)
      .not_valid_after(now + datetime.timedelta(seconds=validity)))

  # A CA cert needs an explicit basicConstraints CA flag; pyOpenSSL's
  # bare v1 certs were accepted implicitly, v3 certs are not.
  builder = builder.add_extension(
    cryptography_x509.BasicConstraints(ca=is_ca, path_length=None),
    critical=True)

  builder = builder.add_extension(
    cryptography_x509.KeyUsage(
      digital_signature=True,
      content_commitment=False,
      key_encipherment=True,
      data_encipherment=False,
      key_agreement=False,
      key_cert_sign=is_ca,
      crl_sign=is_ca,
      encipher_only=False,
      decipher_only=False),
    critical=True)

  builder = builder.add_extension(
    cryptography_x509.SubjectKeyIdentifier.from_public_key(public_key),
    critical=False)

  if issuer_public_key is not None:
    builder = builder.add_extension(
      cryptography_x509.AuthorityKeyIdentifier.from_issuer_public_key(
        issuer_public_key),
      critical=False)

  return builder


def _CertValidityTime(cert, attr):
  # cryptography >= 42 deprecates the naive not_valid_* properties in
  # favor of aware not_valid_*_utc; older releases (Debian Bookworm
  # ships 38.x, Trixie < 42) only have the former.
  dt = getattr(cert, attr + "_utc", None) or getattr(cert, attr)
  if dt is None:
    return None

  return dt.replace(tzinfo=None)


def _DatetimeToUnix(dt):
  """Converts a naive-UTC datetime to a Unix timestamp.

  @type dt: datetime.datetime or None
  @param dt: Naive datetime interpreted as UTC
  @return: Seconds since the Epoch, or None

  """
  if dt is None:
    return None

  return calendar.timegm(dt.utctimetuple())


def GetX509CertValidity(cert):
  """Returns the validity period of the certificate.

  @type cert: cryptography.x509.Certificate
  @param cert: X509 certificate object

  """
  return (_DatetimeToUnix(_CertValidityTime(cert, "not_valid_before")),
          _DatetimeToUnix(_CertValidityTime(cert, "not_valid_after")))

def _VerifyCertificateInner(expired, not_before, not_after, now,
                            warn_days, error_days):
  """Verifies certificate validity.

  @type expired: bool
  @param expired: Whether the certificate is expired as of now
  @type not_before: number or None
  @param not_before: Unix timestamp before which certificate is not valid
  @type not_after: number or None
  @param not_after: Unix timestamp after which certificate is invalid
  @type now: number
  @param now: Current time as Unix timestamp
  @type warn_days: number or None
  @param warn_days: How many days before expiration a warning should be reported
  @type error_days: number or None
  @param error_days: How many days before expiration an error should be reported

  """
  if expired:
    msg = "Certificate is expired"
    if not_before is not None and not_after is not None:
      msg += (" (valid from %s to %s)" %
              (utils_text.FormatTime(not_before),
               utils_text.FormatTime(not_after)))
    elif not_before is not None:
      msg += " (valid from %s)" % utils_text.FormatTime(not_before)
    elif not_after is not None:
      msg += " (valid until %s)" % utils_text.FormatTime(not_after)

    return (CERT_ERROR, msg)

  elif not_before is not None and not_before > now:
    return (CERT_WARNING,
            "Certificate not yet valid (valid from %s)" %
            utils_text.FormatTime(not_before))

  elif not_after is not None:
    remaining_days = int((not_after - now) / (24 * 3600))

    msg = "Certificate expires in about %d days" % remaining_days

    if error_days is not None and remaining_days <= error_days:
      return (CERT_ERROR, msg)

    if warn_days is not None and remaining_days <= warn_days:
      return (CERT_WARNING, msg)

  return (None, None)


def VerifyX509Certificate(cert, warn_days, error_days):
  """Verifies a certificate for LUClusterVerify.

  @type cert: cryptography.x509.Certificate
  @param cert: X509 certificate object
  @type warn_days: number or None
  @param warn_days: How many days before expiration a warning should be reported
  @type error_days: number or None
  @param error_days: How many days before expiration an error should be reported

  """
  (not_before, not_after) = GetX509CertValidity(cert)

  now = time.time() + constants.NODE_MAX_CLOCK_SKEW

  # The clock skew allowance above is deliberately included here: a
  # certificate that expired within the last NODE_MAX_CLOCK_SKEW seconds
  # is still accepted, mirroring the behaviour of the previous
  # pyOpenSSL-based implementation.
  expired = not_after is None or not_after < now

  return _VerifyCertificateInner(expired, not_before, not_after,
                                 now, warn_days, error_days)


def SignX509Certificate(cert, key, salt):
  """Sign a X509 certificate.

  An RFC822-like signature header is added in front of the certificate.

  @type cert: cryptography.x509.Certificate
  @param cert: X509 certificate object
  @type key: string
  @param key: Key for HMAC
  @type salt: string
  @param salt: Salt for HMAC
  @rtype: string
  @return: Serialized and signed certificate in PEM format

  """
  if not VALID_X509_SIGNATURE_SALT.match(salt):
    raise errors.GenericError("Invalid salt: %r" % salt)

  # Dumping as PEM here ensures the certificate is in a sane format
  cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")

  return ("%s: %s/%s\n\n%s" %
          (constants.X509_CERT_SIGNATURE_HEADER, salt,
           utils_hash.Sha1Hmac(key, cert_pem, salt=salt),
           cert_pem))


def _ExtractX509CertificateSignature(cert_pem):
  """Helper function to extract signature from X509 certificate.

  """
  if isinstance(cert_pem, bytes):
    cert_pem = cert_pem.decode("ascii")

  # Extract signature from original PEM data
  for line in cert_pem.splitlines():
    if line.startswith("---"):
      break

    m = X509_SIGNATURE.match(line.strip())
    if m:
      return (m.group("salt"), m.group("sign"))

  raise errors.GenericError("X509 certificate signature is missing")


def LoadSignedX509Certificate(cert_pem, key):
  """Verifies a signed X509 certificate.

  @type cert_pem: string
  @param cert_pem: Certificate in PEM format and with signature header
  @type key: string
  @param key: Key for HMAC
  @rtype: tuple; (cryptography.x509.Certificate, string)
  @return: X509 certificate object and salt

  """
  (salt, signature) = _ExtractX509CertificateSignature(cert_pem)

  # Load and dump certificate to ensure it's in a sane format
  (cert, sane_pem) = ExtractX509Certificate(cert_pem)

  if not utils_hash.VerifySha1Hmac(key, sane_pem, signature, salt=salt):
    raise errors.GenericError("X509 certificate signature is invalid")

  return (cert, salt)


def GenerateSelfSignedX509Cert(common_name, validity, serial_no):
  """Generates a self-signed X509 certificate.

  @type common_name: string
  @param common_name: commonName value
  @type validity: int
  @param validity: Validity for certificate in seconds
  @return: a tuple of strings containing the PEM-encoded private key and
           certificate

  """
  key = _GenerateRsaKey()
  subject = cryptography_x509.Name(
    [cryptography_x509.NameAttribute(NameOID.COMMON_NAME, common_name)]
    if common_name else [])

  cert = (_BuildCertificate(common_name, validity, serial_no,
                            subject, key.public_key(), is_ca=True)
          .sign(key, _SIGN_DIGESTS[constants.X509_CERT_SIGN_DIGEST]()))

  key_pem = key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption())
  cert_pem = cert.public_bytes(serialization.Encoding.PEM)

  return (key_pem, cert_pem)


def GenerateSelfSignedSslCert(filename, serial_no,
                              common_name=constants.X509_CERT_CN,
                              validity=constants.X509_CERT_DEFAULT_VALIDITY,
                              uid=-1, gid=-1):
  """Legacy function to generate self-signed X509 certificate.

  @type filename: str
  @param filename: path to write certificate to
  @type common_name: string
  @param common_name: commonName value
  @type validity: int
  @param validity: validity of certificate in number of days
  @type uid: int
  @param uid: the user ID of the user who will be owner of the certificate file
  @type gid: int
  @param gid: the group ID of the group who will own the certificate file
  @return: a tuple of strings containing the PEM-encoded private key and
           certificate

  """
  # TODO: Investigate using the cluster name instead of X505_CERT_CN for
  # common_name, as cluster-renames are very seldom, and it'd be nice if RAPI
  # and node daemon certificates have the proper Subject/Issuer.
  (key_pem, cert_pem) = GenerateSelfSignedX509Cert(
      common_name, validity * 24 * 60 * 60, serial_no)

  utils_io.WriteFile(filename, mode=0o440, data=key_pem + cert_pem,
                     uid=uid, gid=gid)
  return (key_pem, cert_pem)


def GenerateSignedX509Cert(common_name, validity, serial_no,
                           signing_cert_pem):
  """Generates a signed (but not self-signed) X509 certificate.

  @type common_name: string
  @param common_name: commonName value, should be hostname of the machine
  @type validity: int
  @param validity: Validity for certificate in seconds
  @type signing_cert_pem: X509 key
  @param signing_cert_pem: PEM-encoded private key of the signing certificate
  @return: a tuple of strings containing the PEM-encoded private key and
           certificate
  """

  # Create private RSA key
  key = _GenerateRsaKey()


  # Ganeti reads PEM files as text; the loaders require bytes.
  if not isinstance(signing_cert_pem, bytes):
    signing_cert_pem = signing_cert_pem.encode("ascii")

  # Load the certificates used for signing.
  signing_key = serialization.load_pem_private_key(signing_cert_pem,
                                                   password=None)
  signing_cert = cryptography_x509.load_pem_x509_certificate(
    signing_cert_pem)

  # Create a certificate and sign it.
  cert = (_BuildCertificate(common_name, validity, serial_no,
                            signing_cert.subject, key.public_key(),
                            is_ca=False,
                            issuer_public_key=signing_key.public_key())
          .sign(signing_key, _SIGN_DIGESTS[constants.X509_CERT_SIGN_DIGEST]()))

  # Encode the key and certificate in PEM format.
  key_pem = key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption())
  cert_pem = cert.public_bytes(serialization.Encoding.PEM)

  return (key_pem, cert_pem)


def GenerateSignedSslCert(filename_cert, serial_no,
                          filename_signing_cert,
                          common_name=constants.X509_CERT_CN,
                          validity=constants.X509_CERT_DEFAULT_VALIDITY,
                          uid=-1, gid=-1):
  signing_cert_pem = utils_io.ReadFile(filename_signing_cert)
  (key_pem, cert_pem) = GenerateSignedX509Cert(
      common_name, validity * 24 * 60 * 60, serial_no, signing_cert_pem)

  utils_io.WriteFile(filename_cert, mode=0o440, data=key_pem + cert_pem,
                     uid=uid, gid=gid, backup=True)
  return (key_pem, cert_pem)


def ExtractX509Certificate(pem):
  """Extracts the certificate from a PEM-formatted string.

  @type pem: string
  @rtype: tuple; (cryptography.x509.Certificate, string)
  @return: Certificate object and PEM-formatted certificate

  """
  if not isinstance(pem, bytes):
    pem = pem.encode("ascii")

  cert = cryptography_x509.load_pem_x509_certificate(pem)

  return (cert,
          cert.public_bytes(serialization.Encoding.PEM).decode("ascii"))


def X509CertKeyCheck(cert, key):
  """Function for verifying certificate with a certain private key.

  @type key: cryptography private key object
  @param key: Private key object
  @type cert: cryptography.x509.Certificate
  @param cert: X509 certificate object
  @rtype: bool
  @return: Whether the certificate's public key matches the private key

  """
  cert_pub = cert.public_key().public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo)
  key_pub = key.public_key().public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo)

  return cert_pub == key_pub


def FormatCertificateDigest(der_cert):
  """Compute SHA1 digest of a DER-encoded certificate.

  Returns the digest in the same colon-separated hex format as
  pyOpenSSL's C{X509.digest()}, for compatibility with existing
  certificate digest storage (ssconf, etc.).

  @type der_cert: bytes
  @param der_cert: DER-encoded certificate
  @rtype: string
  @return: SHA1 digest in "XX:XX:XX:..." format

  """
  raw = hashes.Hash(hashes.SHA1())
  raw.update(der_cert)
  return ":".join(f"{b:02X}" for b in raw.finalize())


def CheckNodeCertificate(cert, _noded_cert_file=pathutils.NODED_CERT_FILE):
  """Checks the local node daemon certificate against given certificate.

  Both certificates must be signed with the same key (as stored in the local
  L{pathutils.NODED_CERT_FILE} file). No error is raised if no local
  certificate can be found.

  @type cert: cryptography.x509.Certificate
  @param cert: X509 certificate object
  @raise errors.X509CertError: When an error related to X509 occurred
  @raise errors.GenericError: When the verification failed

  """
  try:
    noded_pem = utils_io.ReadFile(_noded_cert_file)
  except EnvironmentError as err:
    if err.errno != errno.ENOENT:
      raise

    logging.debug("Node certificate file '%s' was not found", _noded_cert_file)
    return

  if not isinstance(noded_pem, bytes):
    noded_pem = noded_pem.encode("ascii")

  try:
    noded_cert = cryptography_x509.load_pem_x509_certificate(noded_pem)
  except Exception as err:
    raise errors.X509CertError(_noded_cert_file,
                               "Unable to load certificate: %s" % err)

  try:
    noded_key = serialization.load_pem_private_key(noded_pem, password=None)
  except Exception as err:
    raise errors.X509CertError(_noded_cert_file,
                               "Unable to load private key: %s" % err)

  # Check consistency of server.pem file
  if not X509CertKeyCheck(noded_cert, noded_key):
    # This should never happen as it would mean the certificate in server.pem
    # is out of sync with the private key stored in the same file
    raise errors.X509CertError(_noded_cert_file,
                               "Certificate does not match with private key")

  # Check with supplied certificate with local key
  if not X509CertKeyCheck(cert, noded_key):
    raise errors.GenericError("Given cluster certificate does not match"
                              " local key")
