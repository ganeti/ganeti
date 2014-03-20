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

"""Script to update a node's SSH key files.

This script is used to update the node's 'authorized_keys' and
'ganeti_pub_key' files. It will be called via SSH from the master
node.

"""

import os
import os.path
import optparse
import sys
import logging

from ganeti import cli
from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import ht
from ganeti import ssh
from ganeti import pathutils
from ganeti.tools import common


_DATA_CHECK = ht.TStrictDict(False, True, {
  constants.SSHS_CLUSTER_NAME: ht.TNonEmptyString,
  constants.SSHS_NODE_DAEMON_CERTIFICATE: ht.TNonEmptyString,
  constants.SSHS_SSH_PUBLIC_KEYS:
    ht.TDictOf(ht.TNonEmptyString, ht.TListOf(ht.TNonEmptyString)),
  constants.SSHS_SSH_AUTHORIZED_KEYS:
    ht.TDictOf(ht.TNonEmptyString, ht.TListOf(ht.TNonEmptyString)),
  })


class SshUpdateError(errors.GenericError):
  """Local class for reporting errors.

  """


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  program = os.path.basename(sys.argv[0])

  parser = optparse.OptionParser(
    usage="%prog [--dry-run] [--verbose] [--debug]", prog=program)
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option(cli.DRY_RUN_OPT)

  (opts, args) = parser.parse_args()

  return common.VerifyOptions(parser, opts, args)


def UpdateAuthorizedKeys(data, dry_run, _homedir_fn=None):
  """Updates root's C{authorized_keys} file.

  @type data: dict
  @param data: Input data
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run

  """
  authorized_keys = data.get(constants.SSHS_SSH_AUTHORIZED_KEYS)

  if authorized_keys:
    (auth_keys_file, _) = \
      ssh.GetAllUserFiles(constants.SSH_LOGIN_USER, mkdir=True,
                          _homedir_fn=_homedir_fn)

    if dry_run:
      logging.info("This is a dry run, not modifying %s", auth_keys_file)
    else:
      all_authorized_keys = []
      for keys in authorized_keys.values():
        all_authorized_keys += keys
      if not os.path.exists(auth_keys_file):
        utils.WriteFile(auth_keys_file, mode=0600, data="")
      ssh.AddAuthorizedKeys(auth_keys_file, all_authorized_keys)


def UpdatePubKeyFile(data, dry_run, key_file=pathutils.SSH_PUB_KEYS):
  """Updates the file of public SSH keys.

  @type data: dict
  @param data: Input data
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run

  """
  public_keys = data.get(constants.SSHS_SSH_PUBLIC_KEYS)
  if not public_keys:
    logging.info("No public keys received. Not modifying"
                 " the public key file at all.")
    return
  if dry_run:
    logging.info("This is a dry run, not modifying %s", key_file)
  ssh.OverridePubKeyFile(public_keys, key_file=key_file)


def Main():
  """Main routine.

  """
  opts = ParseOptions()

  utils.SetupToolLogging(opts.debug, opts.verbose)

  try:
    data = common.LoadData(sys.stdin.read(), _DATA_CHECK)

    # Check if input data is correct
    common.VerifyClusterName(data, SshUpdateError)
    common.VerifyCertificate(data, SshUpdateError)

    # Update SSH files
    UpdateAuthorizedKeys(data, opts.dry_run)
    UpdatePubKeyFile(data, opts.dry_run)

    logging.info("Setup finished successfully")
  except Exception, err: # pylint: disable=W0703
    logging.debug("Caught unhandled exception", exc_info=True)

    (retcode, message) = cli.FormatError(err)
    logging.error(message)

    return retcode
  else:
    return constants.EXIT_SUCCESS
