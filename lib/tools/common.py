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

import OpenSSL

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import serializer
from ganeti import ssconf
from ganeti import ssh


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
  @param cert_pem: Certificate in PEM format (no key)

  """
  try:
    OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
  except OpenSSL.crypto.Error, err:
    pass
  else:
    raise error_fn("No private key may be given")

  try:
    cert = \
      OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert_pem)
  except Exception, err:
    raise errors.X509CertError("(stdin)",
                               "Unable to load certificate: %s" % err)

  _check_fn(cert)


def VerifyCertificate(data, error_fn, _verify_fn=_VerifyCertificate):
  """Verifies cluster certificate.

  @type data: dict

  """
  cert = data.get(constants.SSHS_NODE_DAEMON_CERTIFICATE)
  if cert:
    _verify_fn(cert, error_fn)


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


def GenerateRootSshKeys(error_fn, _homedir_fn=None):
  """Generates root's SSH keys for this node.

  """
  ssh.InitSSHSetup(error_fn=error_fn, _homedir_fn=_homedir_fn)
