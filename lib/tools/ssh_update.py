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
    ht.TItems(
      [ht.TElemOf(constants.SSHS_ACTIONS),
       ht.TDictOf(ht.TNonEmptyString, ht.TListOf(ht.TNonEmptyString))]),
  constants.SSHS_SSH_AUTHORIZED_KEYS:
    ht.TItems(
      [ht.TElemOf(constants.SSHS_ACTIONS),
       ht.TDictOf(ht.TNonEmptyString, ht.TListOf(ht.TNonEmptyString))]),
  constants.SSHS_GENERATE:
    ht.TItems(
      [ht.TSshKeyType, # The type of key to generate
       ht.TPositive, # The number of bits in the key
       ht.TString]), # The suffix
  constants.SSHS_SSH_KEY_TYPE: ht.TSshKeyType,
  constants.SSHS_SSH_KEY_BITS: ht.TPositive,
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
  instructions = data.get(constants.SSHS_SSH_AUTHORIZED_KEYS)
  if not instructions:
    logging.info("No change to the authorized_keys file requested.")
    return
  (action, authorized_keys) = instructions

  (auth_keys_file, _) = \
    ssh.GetAllUserFiles(constants.SSH_LOGIN_USER, mkdir=True,
                        _homedir_fn=_homedir_fn)

  key_values = []
  for key_value in authorized_keys.values():
    key_values += key_value
  if action == constants.SSHS_ADD:
    if dry_run:
      logging.info("This is a dry run, not adding keys to %s",
                   auth_keys_file)
    else:
      if not os.path.exists(auth_keys_file):
        utils.WriteFile(auth_keys_file, mode=0600, data="")
      ssh.AddAuthorizedKeys(auth_keys_file, key_values)
  elif action == constants.SSHS_REMOVE:
    if dry_run:
      logging.info("This is a dry run, not removing keys from %s",
                   auth_keys_file)
    else:
      ssh.RemoveAuthorizedKeys(auth_keys_file, key_values)
  else:
    raise SshUpdateError("Action '%s' not implemented for authorized keys."
                         % action)


def UpdatePubKeyFile(data, dry_run, key_file=pathutils.SSH_PUB_KEYS):
  """Updates the file of public SSH keys.

  @type data: dict
  @param data: Input data
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run

  """
  instructions = data.get(constants.SSHS_SSH_PUBLIC_KEYS)
  if not instructions:
    logging.info("No instructions to modify public keys received."
                 " Not modifying the public key file at all.")
    return
  (action, public_keys) = instructions

  if action == constants.SSHS_OVERRIDE:
    if dry_run:
      logging.info("This is a dry run, not overriding %s", key_file)
    else:
      ssh.OverridePubKeyFile(public_keys, key_file=key_file)
  elif action in [constants.SSHS_ADD, constants.SSHS_REPLACE_OR_ADD]:
    if dry_run:
      logging.info("This is a dry run, not adding or replacing a key to %s",
                   key_file)
    else:
      for uuid, keys in public_keys.items():
        if action == constants.SSHS_REPLACE_OR_ADD:
          ssh.RemovePublicKey(uuid, key_file=key_file)
        for key in keys:
          ssh.AddPublicKey(uuid, key, key_file=key_file)
  elif action == constants.SSHS_REMOVE:
    if dry_run:
      logging.info("This is a dry run, not removing keys from %s", key_file)
    else:
      for uuid in public_keys.keys():
        ssh.RemovePublicKey(uuid, key_file=key_file)
  elif action == constants.SSHS_CLEAR:
    if dry_run:
      logging.info("This is a dry run, not clearing file %s", key_file)
    else:
      ssh.ClearPubKeyFile(key_file=key_file)
  else:
    raise SshUpdateError("Action '%s' not implemented for public keys."
                         % action)


def GenerateRootSshKeys(data, dry_run):
  """(Re-)generates the root SSH keys.

  @type data: dict
  @param data: Input data
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run

  """
  generate_info = data.get(constants.SSHS_GENERATE)
  if generate_info:
    key_type, key_bits, suffix = generate_info
    if dry_run:
      logging.info("This is a dry run, not generating any files.")
    else:
      common.GenerateRootSshKeys(key_type, key_bits, SshUpdateError,
                                 _suffix=suffix)


def Main():
  """Main routine.

  """
  opts = ParseOptions()

  utils.SetupToolLogging(opts.debug, opts.verbose)

  try:
    data = common.LoadData(sys.stdin.read(), _DATA_CHECK)

    # Check if input data is correct
    common.VerifyClusterName(data, SshUpdateError, constants.SSHS_CLUSTER_NAME)
    common.VerifyCertificateSoft(data, SshUpdateError)

    # Update / Generate SSH files
    UpdateAuthorizedKeys(data, opts.dry_run)
    UpdatePubKeyFile(data, opts.dry_run)
    GenerateRootSshKeys(data, opts.dry_run)

    logging.info("Setup finished successfully")
  except Exception, err: # pylint: disable=W0703
    logging.debug("Caught unhandled exception", exc_info=True)

    (retcode, message) = cli.FormatError(err)
    logging.error(message)

    return retcode
  else:
    return constants.EXIT_SUCCESS
