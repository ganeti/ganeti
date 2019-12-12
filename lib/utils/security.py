#
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

"""Utility functions for security features of Ganeti.

"""

import logging
import os
import time
import uuid as uuid_module

import OpenSSL

from ganeti.utils import io
from ganeti.utils import x509
from ganeti import constants
from ganeti import errors
from ganeti import pathutils


def UuidToInt(uuid):
  uuid_obj = uuid_module.UUID(uuid)
  return uuid_obj.int # pylint: disable=E1101


def GetCertificateDigest(cert_filename=pathutils.NODED_CLIENT_CERT_FILE):
  """Reads the SSL certificate and returns the sha1 digest.

  """
  cert_plain = io.ReadFile(cert_filename)
  cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                         cert_plain)
  return cert.digest("sha1").decode("ascii")


def GenerateNewSslCert(new_cert, cert_filename, serial_no, log_msg,
                       uid=-1, gid=-1):
  """Creates a new server SSL certificate and backups the old one.

  @type new_cert: boolean
  @param new_cert: whether a new certificate should be created
  @type cert_filename: string
  @param cert_filename: filename of the certificate file
  @type serial_no: int
  @param serial_no: serial number of the certificate
  @type log_msg: string
  @param log_msg: log message to be written on certificate creation
  @type uid: int
  @param uid: the user ID of the user who will be owner of the certificate file
  @type gid: int
  @param gid: the group ID of the group who will own the certificate file

  """
  cert_exists = os.path.exists(cert_filename)
  if new_cert or not cert_exists:
    if cert_exists:
      io.CreateBackup(cert_filename)

    logging.debug(log_msg)
    x509.GenerateSelfSignedSslCert(cert_filename, serial_no, uid=uid, gid=gid)


def GenerateNewClientSslCert(cert_filename, signing_cert_filename,
                             hostname):
  """Creates a new server SSL certificate and backups the old one.

  @type cert_filename: string
  @param cert_filename: filename of the certificate file
  @type signing_cert_filename: string
  @param signing_cert_filename: name of the certificate to be used for signing
  @type hostname: string
  @param hostname: name of the machine whose cert is created

  """
  serial_no = int(time.time())
  x509.GenerateSignedSslCert(cert_filename, serial_no, signing_cert_filename,
                             common_name=hostname)


def VerifyCertificate(filename):
  """Verifies a SSL certificate.

  @type filename: string
  @param filename: Path to PEM file

  """
  try:
    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           io.ReadFile(filename))
  except Exception as err: # pylint: disable=W0703
    return (constants.CV_ERROR,
            "Failed to load X509 certificate %s: %s" % (filename, err))

  (errcode, msg) = \
    x509.VerifyX509Certificate(cert, constants.SSL_CERT_EXPIRATION_WARN,
                               constants.SSL_CERT_EXPIRATION_ERROR)

  if msg:
    fnamemsg = "While verifying %s: %s" % (filename, msg)
  else:
    fnamemsg = None

  if errcode is None:
    return (None, fnamemsg)
  elif errcode == x509.CERT_WARNING:
    return (constants.CV_WARNING, fnamemsg)
  elif errcode == x509.CERT_ERROR:
    return (constants.CV_ERROR, fnamemsg)

  raise errors.ProgrammerError("Unhandled certificate error code %r" % errcode)


def IsCertificateSelfSigned(cert_filename):
  """Checks whether the certificate issuer is the same as the owner.

  Note that this does not actually verify the signature, it simply
  compares the certificates common name and the issuer's common
  name. This is sufficient, because now that Ganeti started creating
  non-self-signed client-certificates, it uses their hostnames
  as common names and thus they are distinguishable by common name
  from the server certificates.

  @type cert_filename: string
  @param cert_filename: filename of the certificate to examine

  """
  try:
    cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                           io.ReadFile(cert_filename))
  except Exception as err: # pylint: disable=W0703
    return (constants.CV_ERROR,
            "Failed to load X509 certificate %s: %s" % (cert_filename, err))

  if cert.get_subject().CN == cert.get_issuer().CN:
    msg = "The certificate '%s' is self-signed. Please run 'gnt-cluster" \
          " renew-crypto --new-node-certificates' to get a properly signed" \
          " certificate." % cert_filename
    return (constants.CV_WARNING, msg)

  return (None, None)
