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

"""Script to configure the node daemon.

"""

import os
import os.path
import optparse
import sys
import logging

from ganeti import cli
from ganeti import constants
from ganeti import pathutils
from ganeti import ssconf
from ganeti import utils


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  parser = optparse.OptionParser(usage="%prog [--no-backup]",
                                 prog=os.path.basename(sys.argv[0]))
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option(cli.YES_DOIT_OPT)
  parser.add_option("--no-backup", dest="backup", default=True,
                    action="store_false",
                    help="Whether to create backup copies of deleted files")

  (opts, args) = parser.parse_args()

  return VerifyOptions(parser, opts, args)


def VerifyOptions(parser, opts, args):
  """Verifies options and arguments for correctness.

  """
  if args:
    parser.error("No arguments are expected")

  return opts


def Main():
  """Main routine.

  """
  opts = ParseOptions()

  utils.SetupToolLogging(opts.debug, opts.verbose)

  try:
    # List of files to delete. Contains tuples consisting of the absolute path
    # and a boolean denoting whether a backup copy should be created before
    # deleting.
    clean_files = [
      (pathutils.CONFD_HMAC_KEY, True),
      (pathutils.CLUSTER_CONF_FILE, True),
      (pathutils.CLUSTER_DOMAIN_SECRET_FILE, True),
      ]
    clean_files.extend((f, True) for f in pathutils.ALL_CERT_FILES)
    clean_files.extend((f, False) for f in ssconf.SimpleStore().GetFileList())

    if not opts.yes_do_it:
      cli.ToStderr("Cleaning a node is irreversible. If you really want to"
                   " clean this node, supply the --yes-do-it option.")
      return constants.EXIT_FAILURE

    logging.info("Stopping daemons")
    result = utils.RunCmd([pathutils.DAEMON_UTIL, "stop-all"],
                          interactive=True)
    if result.failed:
      raise Exception("Could not stop daemons, command '%s' failed: %s" %
                      (result.cmd, result.fail_reason))

    for (filename, backup) in clean_files:
      if os.path.exists(filename):
        if opts.backup and backup:
          logging.info("Backing up %s", filename)
          utils.CreateBackup(filename)

        logging.info("Removing %s", filename)
        utils.RemoveFile(filename)

    logging.info("Node successfully cleaned")
  except Exception, err: # pylint: disable=W0703
    logging.debug("Caught unhandled exception", exc_info=True)

    (retcode, message) = cli.FormatError(err)
    logging.error(message)

    return retcode
  else:
    return constants.EXIT_SUCCESS
