#
#

# Copyright (C) 2014 Google Inc.
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

"""Common functions for tool scripts.

"""

import logging
import OpenSSL
from cStringIO import StringIO

from ganeti import constants
from ganeti import utils
from ganeti import serializer
from ganeti import ssconf


def VerifyOptions(parser, opts, args):
  """Verifies options and arguments for correctness.

  """
  if args:
    parser.error("No arguments are expected")

  return opts


def _VerifyCertificate(cert_pem, error_fn,
                       _check_fn=utils.CheckNodeCertificate):
  """Verifies a certificate against the local node daemon certificate.

  @type cert_pem: string
  @param cert_pem: Certificate and key in PEM format
  @type error_fn: callable
  @param error_fn: function to call in case of an error
  @rtype: string
  @return: Formatted key and certificate

  """
  try:
    cert = \
      OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
  except Exception, err:
    raise error_fn("(stdin) Unable to load certificate: %s" % err)

  try:
    key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
  except OpenSSL.crypto.Error, err:
    raise error_fn("(stdin) Unable to load private key: %s" % err)

  # Check certificate with given key; this detects cases where the key given on
  # stdin doesn't match the certificate also given on stdin
  try:
    utils.X509CertKeyCheck(cert, key)
  except OpenSSL.SSL.Error:
    raise error_fn("(stdin) Certificate is not signed with given key")

  # Standard checks, including check against an existing local certificate
  # (no-op if that doesn't exist)
  _check_fn(cert)

  key_encoded = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)
  cert_encoded = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                                 cert)
  complete_cert_encoded = key_encoded + cert_encoded
  if not cert_pem == complete_cert_encoded:
    logging.error("The certificate differs after being reencoded. Please"
                  " renew the certificates cluster-wide to prevent future"
                  " inconsistencies.")

  # Format for storing on disk
  buf = StringIO()
  buf.write(cert_pem)
  return buf.getvalue()


def VerifyCertificate(data, error_fn, _verify_fn=_VerifyCertificate):
  """Verifies cluster certificate.

  @type data: dict
  @type error_fn: callable
  @param error_fn: function to call in case of an error
  @rtype: string
  @return: Formatted key and certificate

  """
  cert = data.get(constants.NDS_NODE_DAEMON_CERTIFICATE)
  if not cert:
    raise error_fn("Node daemon certificate must be specified")

  return _verify_fn(cert, error_fn)


def VerifyClusterName(data, error_fn,
                      _verify_fn=ssconf.VerifyClusterName):
  """Verifies cluster name.

  @type data: dict

  """
  name = data.get(constants.SSHS_CLUSTER_NAME)
  if name:
    _verify_fn(name)
  else:
    raise error_fn("Cluster name must be specified")


def LoadData(raw, data_check):
  """Parses and verifies input data.

  @rtype: dict

  """
  return serializer.LoadAndVerifyJson(raw, data_check)
