#
#

# Copyright (C) 2012 Google Inc.
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

"""Script to prepare a node for joining a cluster.

"""

import os
import os.path
import optparse
import sys
import logging

from ganeti import cli
from ganeti import constants
from ganeti import errors
from ganeti import pathutils
from ganeti import utils
from ganeti import ht
from ganeti import ssh
from ganeti.tools import common


_SSH_KEY_LIST_ITEM = \
  ht.TAnd(ht.TIsLength(3),
          ht.TItems([
            ht.TSshKeyType,
            ht.Comment("public")(ht.TNonEmptyString),
            ht.Comment("private")(ht.TNonEmptyString),
          ]))

_SSH_KEY_LIST = ht.TListOf(_SSH_KEY_LIST_ITEM)

_DATA_CHECK = ht.TStrictDict(False, True, {
  constants.SSHS_CLUSTER_NAME: ht.TNonEmptyString,
  constants.SSHS_NODE_DAEMON_CERTIFICATE: ht.TNonEmptyString,
  constants.SSHS_SSH_HOST_KEY: _SSH_KEY_LIST,
  constants.SSHS_SSH_ROOT_KEY: _SSH_KEY_LIST,
  constants.SSHS_SSH_AUTHORIZED_KEYS:
    ht.TDictOf(ht.TNonEmptyString, ht.TListOf(ht.TNonEmptyString)),
  constants.SSHS_SSH_KEY_TYPE: ht.TSshKeyType,
  constants.SSHS_SSH_KEY_BITS: ht.TPositive,
  })


class JoinError(errors.GenericError):
  """Local class for reporting errors.

  """


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  program = os.path.basename(sys.argv[0])

  parser = optparse.OptionParser(usage="%prog [--dry-run]",
                                 prog=program)
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option(cli.DRY_RUN_OPT)

  (opts, args) = parser.parse_args()

  return common.VerifyOptions(parser, opts, args)


def _UpdateKeyFiles(keys, dry_run, keyfiles):
  """Updates SSH key files.

  @type keys: sequence of tuple; (string, string, string)
  @param keys: Keys to write, tuples consist of key type
    (L{constants.SSHK_ALL}), public and private key
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run
  @type keyfiles: dict; (string as key, tuple with (string, string) as values)
  @param keyfiles: Mapping from key types (L{constants.SSHK_ALL}) to file
    names; value tuples consist of public key filename and private key filename

  """
  assert set(keyfiles) == constants.SSHK_ALL

  for (kind, private_key, public_key) in keys:
    (private_file, public_file) = keyfiles[kind]

    logging.debug("Writing %s ...", private_file)
    utils.WriteFile(private_file, data=private_key, mode=0600,
                    backup=True, dry_run=dry_run)

    logging.debug("Writing %s ...", public_file)
    utils.WriteFile(public_file, data=public_key, mode=0644,
                    backup=True, dry_run=dry_run)


def UpdateSshDaemon(data, dry_run, _runcmd_fn=utils.RunCmd,
                    _keyfiles=None):
  """Updates SSH daemon's keys.

  Unless C{dry_run} is set, the daemon is restarted at the end.

  @type data: dict
  @param data: Input data
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run

  """
  keys = data.get(constants.SSHS_SSH_HOST_KEY)
  if not keys:
    return

  if _keyfiles is None:
    _keyfiles = constants.SSH_DAEMON_KEYFILES

  logging.info("Updating SSH daemon key files")
  _UpdateKeyFiles(keys, dry_run, _keyfiles)

  if dry_run:
    logging.info("This is a dry run, not restarting SSH daemon")
  else:
    result = _runcmd_fn([pathutils.DAEMON_UTIL, "reload-ssh-keys"],
                        interactive=True)
    if result.failed:
      raise JoinError("Could not reload SSH keys, command '%s'"
                      " had exitcode %s and error %s" %
                       (result.cmd, result.exit_code, result.output))


def UpdateSshRoot(data, dry_run, _homedir_fn=None):
  """Updates root's SSH keys.

  Root's C{authorized_keys} file is also updated with new public keys.

  @type data: dict
  @param data: Input data
  @type dry_run: boolean
  @param dry_run: Whether to perform a dry run

  """
  authorized_keys = data.get(constants.SSHS_SSH_AUTHORIZED_KEYS)

  (auth_keys_file, _) = \
    ssh.GetAllUserFiles(constants.SSH_LOGIN_USER, mkdir=True,
                        _homedir_fn=_homedir_fn)

  if dry_run:
    logging.info("This is a dry run, not replacing the SSH keys.")
  else:
    ssh_key_type = data.get(constants.SSHS_SSH_KEY_TYPE)
    ssh_key_bits = data.get(constants.SSHS_SSH_KEY_BITS)
    common.GenerateRootSshKeys(ssh_key_type, ssh_key_bits, error_fn=JoinError,
                               _homedir_fn=_homedir_fn)

  if authorized_keys:
    if dry_run:
      logging.info("This is a dry run, not modifying %s", auth_keys_file)
    else:
      all_authorized_keys = []
      for keys in authorized_keys.values():
        all_authorized_keys += keys
      ssh.AddAuthorizedKeys(auth_keys_file, all_authorized_keys)


def Main():
  """Main routine.

  """
  opts = ParseOptions()

  utils.SetupToolLogging(opts.debug, opts.verbose)

  try:
    data = common.LoadData(sys.stdin.read(), _DATA_CHECK)

    # Check if input data is correct
    common.VerifyClusterName(data, JoinError, constants.SSHS_CLUSTER_NAME)
    common.VerifyCertificateSoft(data, JoinError)

    # Update SSH files
    UpdateSshDaemon(data, opts.dry_run)
    UpdateSshRoot(data, opts.dry_run)

    logging.info("Setup finished successfully")
  except Exception, err: # pylint: disable=W0703
    logging.debug("Caught unhandled exception", exc_info=True)

    (retcode, message) = cli.FormatError(err)
    logging.error(message)

    return retcode
  else:
    return constants.EXIT_SUCCESS
