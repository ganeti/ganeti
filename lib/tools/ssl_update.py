#
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

"""Script to recreate and sign the client SSL certificates.

"""

import os
import os.path
import optparse
import sys
import logging
import time

from ganeti import cli
from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import ht
from ganeti import pathutils
from ganeti.tools import common


_DATA_CHECK = ht.TStrictDict(False, True, {
  constants.NDS_CLUSTER_NAME: ht.TNonEmptyString,
  constants.NDS_NODE_DAEMON_CERTIFICATE: ht.TNonEmptyString,
  constants.NDS_NODE_NAME: ht.TNonEmptyString,
  })


class SslSetupError(errors.GenericError):
  """Local class for reporting errors.

  """


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  parser = optparse.OptionParser(usage="%prog [--dry-run]",
                                 prog=os.path.basename(sys.argv[0]))
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option(cli.DRY_RUN_OPT)

  (opts, args) = parser.parse_args()

  return common.VerifyOptions(parser, opts, args)


def RegenerateClientCertificate(
    data, client_cert=pathutils.NODED_CLIENT_CERT_FILE,
    signing_cert=pathutils.NODED_CERT_FILE):
  """Regenerates the client certificate of the node.

  @type data: string
  @param data: the JSON-formated input data

  """
  if not os.path.exists(signing_cert):
    raise SslSetupError("The signing certificate '%s' cannot be found."
                        % signing_cert)

  # TODO: This sets the serial number to the number of seconds
  # since epoch. This is technically not a correct serial number
  # (in the way SSL is supposed to be used), but it serves us well
  # enough for now, as we don't have any infrastructure for keeping
  # track of the number of signed certificates yet.
  serial_no = int(time.time())

  # The hostname of the node is provided with the input data.
  hostname = data.get(constants.NDS_NODE_NAME)

  # TODO: make backup of the file before regenerating.
  utils.GenerateSignedSslCert(client_cert, serial_no, signing_cert,
                              common_name=hostname)


def Main():
  """Main routine.

  """
  opts = ParseOptions()

  utils.SetupToolLogging(opts.debug, opts.verbose)

  try:
    data = common.LoadData(sys.stdin.read(), _DATA_CHECK)

    common.VerifyClusterName(data, SslSetupError)

    # Verifies whether the server certificate of the caller
    # is the same as on this node.
    common.VerifyCertificate(data, SslSetupError)

    RegenerateClientCertificate(data)

  except Exception, err: # pylint: disable=W0703
    logging.debug("Caught unhandled exception", exc_info=True)

    (retcode, message) = cli.FormatError(err)
    logging.error(message)

    return retcode
  else:
    return constants.EXIT_SUCCESS
