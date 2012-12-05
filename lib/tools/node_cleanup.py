#
#

# Copyright (C) 2012 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

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
    clean_files.extend(map(lambda s: (s, True), pathutils.ALL_CERT_FILES))
    clean_files.extend(map(lambda s: (s, False),
                           ssconf.SimpleStore().GetFileList()))

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
