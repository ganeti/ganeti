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

import OpenSSL

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
X509_CERT_SIGN_DIGEST = "SHA1"

# Certificate verification results
(CERT_WARNING,
 CERT_ERROR) = range(1, 3)

#: ASN1 time regexp
_ASN1_TIME_REGEX = re.compile(r"^(\d+)([-+]\d\d)(\d\d)$")


def _ParseAsn1Generalizedtime(value):
  """Parses an ASN1 GENERALIZEDTIME timestamp as used by pyOpenSSL.

  @type value: string
  @param value: ASN1 GENERALIZEDTIME timestamp
  @return: Seconds since the Epoch (1970-01-01 00:00:00 UTC)

  """
  m = _ASN1_TIME_REGEX.match(value)
  if m:
    # We have an offset
    asn1time = m.group(1)
    hours = int(m.group(2))
    minutes = int(m.group(3))
    utcoffset = (60 * hours) + minutes
  else:
    if not value.endswith("Z"):
      raise ValueError("Missing timezone")
    asn1time = value[:-1]
    utcoffset = 0

  parsed = time.strptime(asn1time, "%Y%m%d%H%M%S")

  tt = datetime.datetime(*(parsed[:7])) - datetime.timedelta(minutes=utcoffset)

  return calendar.timegm(tt.utctimetuple())


def GetX509CertValidity(cert):
  """Returns the validity period of the certificate.

  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object

  """
  # The get_notBefore and get_notAfter functions are only supported in
  # pyOpenSSL 0.7 and above.
  try:
    get_notbefore_fn = cert.get_notBefore
  except AttributeError:
    not_before = None
  else:
    not_before_asn1 = get_notbefore_fn()

    if not_before_asn1 is None:
      not_before = None
    else:
      not_before = _ParseAsn1Generalizedtime(not_before_asn1)

  try:
    get_notafter_fn = cert.get_notAfter
  except AttributeError:
    not_after = None
  else:
    not_after_asn1 = get_notafter_fn()

    if not_after_asn1 is None:
      not_after = None
    else:
      not_after = _ParseAsn1Generalizedtime(not_after_asn1)

  return (not_before, not_after)


def _VerifyCertificateInner(expired, not_before, not_after, now,
                            warn_days, error_days):
  """Verifies certificate validity.

  @type expired: bool
  @param expired: Whether pyOpenSSL considers the certificate as expired
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

  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object
  @type warn_days: number or None
  @param warn_days: How many days before expiration a warning should be reported
  @type error_days: number or None
  @param error_days: How many days before expiration an error should be reported

  """
  # Depending on the pyOpenSSL version, this can just return (None, None)
  (not_before, not_after) = GetX509CertValidity(cert)

  now = time.time() + constants.NODE_MAX_CLOCK_SKEW

  return _VerifyCertificateInner(cert.has_expired(), not_before, not_after,
                                 now, warn_days, error_days)


def SignX509Certificate(cert, key, salt):
  """Sign a X509 certificate.

  An RFC822-like signature header is added in front of the certificate.

  @type cert: OpenSSL.crypto.X509
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
  cert_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)

  return ("%s: %s/%s\n\n%s" %
          (constants.X509_CERT_SIGNATURE_HEADER, salt,
           utils_hash.Sha1Hmac(key, cert_pem, salt=salt),
           cert_pem))


def _ExtractX509CertificateSignature(cert_pem):
  """Helper function to extract signature from X509 certificate.

  """
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
  @rtype: tuple; (OpenSSL.crypto.X509, string)
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
  # Create private and public key
  key = OpenSSL.crypto.PKey()
  key.generate_key(OpenSSL.crypto.TYPE_RSA, constants.RSA_KEY_BITS)

  # Create self-signed certificate
  cert = OpenSSL.crypto.X509()
  if common_name:
    cert.get_subject().CN = common_name
  cert.set_serial_number(serial_no)
  cert.gmtime_adj_notBefore(0)
  cert.gmtime_adj_notAfter(validity)
  cert.set_issuer(cert.get_subject())
  cert.set_pubkey(key)
  cert.sign(key, constants.X509_CERT_SIGN_DIGEST)

  key_pem = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)
  cert_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)

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

  utils_io.WriteFile(filename, mode=0440, data=key_pem + cert_pem,
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
  # Create key pair with private and public key.
  key_pair = OpenSSL.crypto.PKey()
  key_pair.generate_key(OpenSSL.crypto.TYPE_RSA, constants.RSA_KEY_BITS)

  # Create certificate sigining request.
  req = OpenSSL.crypto.X509Req()
  req.get_subject().CN = common_name
  req.set_pubkey(key_pair)
  req.sign(key_pair, X509_CERT_SIGN_DIGEST)

  # Load the certificates used for signing.
  signing_key = OpenSSL.crypto.load_privatekey(
      OpenSSL.crypto.FILETYPE_PEM, signing_cert_pem)
  signing_cert = OpenSSL.crypto.load_certificate(
      OpenSSL.crypto.FILETYPE_PEM, signing_cert_pem)

  # Create a certificate and sign it.
  cert = OpenSSL.crypto.X509()
  cert.set_subject(req.get_subject())
  cert.set_serial_number(serial_no)
  cert.gmtime_adj_notBefore(0)
  cert.gmtime_adj_notAfter(validity)
  cert.set_issuer(signing_cert.get_subject())
  cert.set_pubkey(req.get_pubkey())
  cert.sign(signing_key, X509_CERT_SIGN_DIGEST)

  # Encode the key and certificate in PEM format.
  key_pem = OpenSSL.crypto.dump_privatekey(
      OpenSSL.crypto.FILETYPE_PEM, key_pair)
  cert_pem = OpenSSL.crypto.dump_certificate(
      OpenSSL.crypto.FILETYPE_PEM, cert)

  return (key_pem, cert_pem)


def GenerateSignedSslCert(filename_cert, serial_no,
                          filename_signing_cert,
                          common_name=constants.X509_CERT_CN,
                          validity=constants.X509_CERT_DEFAULT_VALIDITY,
                          uid=-1, gid=-1):
  signing_cert_pem = utils_io.ReadFile(filename_signing_cert)
  (key_pem, cert_pem) = GenerateSignedX509Cert(
      common_name, validity * 24 * 60 * 60, serial_no, signing_cert_pem)

  utils_io.WriteFile(filename_cert, mode=0440, data=key_pem + cert_pem,
                     uid=uid, gid=gid, backup=True)
  return (key_pem, cert_pem)


def ExtractX509Certificate(pem):
  """Extracts the certificate from a PEM-formatted string.

  @type pem: string
  @rtype: tuple; (OpenSSL.X509 object, string)
  @return: Certificate object and PEM-formatted certificate

  """
  cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, pem)

  return (cert,
          OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert))


def X509CertKeyCheck(cert, key):
  """Function for verifying certificate with a certain private key.

  @type key: OpenSSL.crypto.PKey
  @param key: Private key object
  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object
  @rtype: callable
  @return: Callable doing the actual check; will raise C{OpenSSL.SSL.Error} if
    certificate is not signed by given private key

  """
  ctx = OpenSSL.SSL.Context(OpenSSL.SSL.TLSv1_METHOD)
  ctx.use_certificate(cert)
  ctx.use_privatekey(key)
  ctx.check_privatekey()


def CheckNodeCertificate(cert, _noded_cert_file=pathutils.NODED_CERT_FILE):
  """Checks the local node daemon certificate against given certificate.

  Both certificates must be signed with the same key (as stored in the local
  L{pathutils.NODED_CERT_FILE} file). No error is raised if no local
  certificate can be found.

  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object
  @raise errors.X509CertError: When an error related to X509 occurred
  @raise errors.GenericError: When the verification failed

  """
  try:
    noded_pem = utils_io.ReadFile(_noded_cert_file)
  except EnvironmentError, err:
    if err.errno != errno.ENOENT:
      raise

    logging.debug("Node certificate file '%s' was not found", _noded_cert_file)
    return

  try:
    noded_cert = \
      OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, noded_pem)
  except Exception, err:
    raise errors.X509CertError(_noded_cert_file,
                               "Unable to load certificate: %s" % err)

  try:
    noded_key = \
      OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, noded_pem)
  except Exception, err:
    raise errors.X509CertError(_noded_cert_file,
                               "Unable to load private key: %s" % err)

  # Check consistency of server.pem file
  try:
    X509CertKeyCheck(noded_cert, noded_key)
  except OpenSSL.SSL.Error:
    # This should never happen as it would mean the certificate in server.pem
    # is out of sync with the private key stored in the same file
    raise errors.X509CertError(_noded_cert_file,
                               "Certificate does not match with private key")

  # Check with supplied certificate with local key
  try:
    X509CertKeyCheck(cert, noded_key)
  except OpenSSL.SSL.Error:
    raise errors.GenericError("Given cluster certificate does not match"
                              " local key")
