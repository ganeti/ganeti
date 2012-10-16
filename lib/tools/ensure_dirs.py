#
#

# Copyright (C) 2011 Google Inc.
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

"""Script to ensure permissions on files/dirs are accurate.

"""

import os
import os.path
import optparse
import sys
import logging

from ganeti import constants
from ganeti import errors
from ganeti import runtime
from ganeti import ssconf
from ganeti import utils
from ganeti import cli
from ganeti import pathutils


(DIR,
 FILE,
 QUEUE_DIR) = range(1, 4)

ALL_TYPES = frozenset([
  DIR,
  FILE,
  QUEUE_DIR,
  ])


def RecursiveEnsure(path, uid, gid, dir_perm, file_perm):
  """Ensures permissions recursively down a directory.

  This functions walks the path and sets permissions accordingly.

  @param path: The absolute path to walk
  @param uid: The uid used as owner
  @param gid: The gid used as group
  @param dir_perm: The permission bits set for directories
  @param file_perm: The permission bits set for files

  """
  assert os.path.isabs(path), "Path %s is not absolute" % path
  assert os.path.isdir(path), "Path %s is not a dir" % path

  logging.debug("Recursively processing %s", path)

  for root, dirs, files in os.walk(path):
    for subdir in dirs:
      utils.EnforcePermission(os.path.join(root, subdir), dir_perm, uid=uid,
                              gid=gid)

    for filename in files:
      utils.EnforcePermission(os.path.join(root, filename), file_perm, uid=uid,
                              gid=gid)


def EnsureQueueDir(path, mode, uid, gid):
  """Sets the correct permissions on all job files in the queue.

  @param path: Directory path
  @param mode: Wanted file mode
  @param uid: Wanted user ID
  @param gid: Wanted group ID

  """
  for filename in utils.ListVisibleFiles(path):
    if constants.JOB_FILE_RE.match(filename):
      utils.EnforcePermission(utils.PathJoin(path, filename), mode, uid=uid,
                              gid=gid)


def ProcessPath(path):
  """Processes a path component.

  @param path: A tuple of the path component to process

  """
  (pathname, pathtype, mode, uid, gid) = path[0:5]

  assert pathtype in ALL_TYPES

  if pathtype in (DIR, QUEUE_DIR):
    # No additional parameters
    assert len(path[5:]) == 0
    if pathtype == DIR:
      utils.MakeDirWithPerm(pathname, mode, uid, gid)
    elif pathtype == QUEUE_DIR:
      EnsureQueueDir(pathname, mode, uid, gid)
  elif pathtype == FILE:
    (must_exist, ) = path[5:]
    utils.EnforcePermission(pathname, mode, uid=uid, gid=gid,
                            must_exist=must_exist)


def GetPaths():
  """Returns a tuple of path objects to process.

  """
  getent = runtime.GetEnts()
  masterd_log = constants.DAEMONS_LOGFILES[constants.MASTERD]
  noded_log = constants.DAEMONS_LOGFILES[constants.NODED]
  confd_log = constants.DAEMONS_LOGFILES[constants.CONFD]
  rapi_log = constants.DAEMONS_LOGFILES[constants.RAPI]

  rapi_dir = os.path.join(pathutils.DATA_DIR, "rapi")
  cleaner_log_dir = os.path.join(pathutils.LOG_DIR, "cleaner")
  master_cleaner_log_dir = os.path.join(pathutils.LOG_DIR, "master-cleaner")

  paths = [
    (pathutils.DATA_DIR, DIR, 0755, getent.masterd_uid,
     getent.masterd_gid),
    (pathutils.CLUSTER_DOMAIN_SECRET_FILE, FILE, 0640,
     getent.masterd_uid, getent.masterd_gid, False),
    (pathutils.CLUSTER_CONF_FILE, FILE, 0640, getent.masterd_uid,
     getent.confd_gid, False),
    (pathutils.CONFD_HMAC_KEY, FILE, 0440, getent.confd_uid,
     getent.masterd_gid, False),
    (pathutils.SSH_KNOWN_HOSTS_FILE, FILE, 0644, getent.masterd_uid,
     getent.masterd_gid, False),
    (pathutils.RAPI_CERT_FILE, FILE, 0440, getent.rapi_uid,
     getent.masterd_gid, False),
    (pathutils.SPICE_CERT_FILE, FILE, 0440, getent.noded_uid,
     getent.masterd_gid, False),
    (pathutils.SPICE_CACERT_FILE, FILE, 0440, getent.noded_uid,
     getent.masterd_gid, False),
    (pathutils.NODED_CERT_FILE, FILE, 0440, getent.masterd_uid,
     getent.masterd_gid, False),
    ]

  ss = ssconf.SimpleStore()
  for ss_path in ss.GetFileList():
    paths.append((ss_path, FILE, constants.SS_FILE_PERMS,
                  getent.noded_uid, getent.noded_gid, False))

  paths.extend([
    (pathutils.QUEUE_DIR, DIR, 0700, getent.masterd_uid,
     getent.masterd_gid),
    (pathutils.QUEUE_DIR, QUEUE_DIR, 0600, getent.masterd_uid,
     getent.masterd_gid),
    (pathutils.JOB_QUEUE_LOCK_FILE, FILE, 0600,
     getent.masterd_uid, getent.masterd_gid, False),
    (pathutils.JOB_QUEUE_SERIAL_FILE, FILE, 0600,
     getent.masterd_uid, getent.masterd_gid, False),
    (pathutils.JOB_QUEUE_VERSION_FILE, FILE, 0600,
     getent.masterd_uid, getent.masterd_gid, False),
    (pathutils.JOB_QUEUE_ARCHIVE_DIR, DIR, 0700,
     getent.masterd_uid, getent.masterd_gid),
    (rapi_dir, DIR, 0750, getent.rapi_uid, getent.masterd_gid),
    (pathutils.RAPI_USERS_FILE, FILE, 0640, getent.rapi_uid,
     getent.masterd_gid, False),
    (pathutils.RUN_DIR, DIR, 0775, getent.masterd_uid,
     getent.daemons_gid),
    (pathutils.SOCKET_DIR, DIR, 0750, getent.masterd_uid,
     getent.daemons_gid),
    (pathutils.MASTER_SOCKET, FILE, 0660, getent.masterd_uid,
     getent.daemons_gid, False),
    (pathutils.BDEV_CACHE_DIR, DIR, 0755, getent.noded_uid,
     getent.masterd_gid),
    (pathutils.UIDPOOL_LOCKDIR, DIR, 0750, getent.noded_uid,
     getent.masterd_gid),
    (pathutils.DISK_LINKS_DIR, DIR, 0755, getent.noded_uid,
     getent.masterd_gid),
    (pathutils.CRYPTO_KEYS_DIR, DIR, 0700, getent.noded_uid,
     getent.masterd_gid),
    (pathutils.IMPORT_EXPORT_DIR, DIR, 0755, getent.noded_uid,
     getent.masterd_gid),
    (pathutils.LOG_DIR, DIR, 0770, getent.masterd_uid,
     getent.daemons_gid),
    (masterd_log, FILE, 0600, getent.masterd_uid, getent.masterd_gid,
     False),
    (confd_log, FILE, 0600, getent.confd_uid, getent.masterd_gid, False),
    (noded_log, FILE, 0600, getent.noded_uid, getent.masterd_gid, False),
    (rapi_log, FILE, 0600, getent.rapi_uid, getent.masterd_gid, False),
    (pathutils.LOG_OS_DIR, DIR, 0750, getent.masterd_uid,
     getent.daemons_gid),
    (cleaner_log_dir, DIR, 0750, getent.noded_uid, getent.noded_gid),
    (master_cleaner_log_dir, DIR, 0750, getent.masterd_uid, getent.masterd_gid),
    ])

  return paths


def SetupLogging(opts):
  """Configures the logging module.

  """
  formatter = logging.Formatter("%(asctime)s: %(message)s")

  stderr_handler = logging.StreamHandler()
  stderr_handler.setFormatter(formatter)
  if opts.debug:
    stderr_handler.setLevel(logging.NOTSET)
  elif opts.verbose:
    stderr_handler.setLevel(logging.INFO)
  else:
    stderr_handler.setLevel(logging.WARNING)

  root_logger = logging.getLogger("")
  root_logger.setLevel(logging.NOTSET)
  root_logger.addHandler(stderr_handler)


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  program = os.path.basename(sys.argv[0])

  parser = optparse.OptionParser(usage="%%prog [--full-run]",
                                 prog=program)
  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.VERBOSE_OPT)
  parser.add_option("--full-run", "-f", dest="full_run", action="store_true",
                    default=False, help=("Make a full run and set permissions"
                                         " on archived jobs (time consuming)"))

  return parser.parse_args()


def Main():
  """Main routine.

  """
  (opts, _) = ParseOptions()

  SetupLogging(opts)

  if opts.full_run:
    logging.info("Running in full mode")

  getent = runtime.GetEnts()

  try:
    for path in GetPaths():
      ProcessPath(path)

    if opts.full_run:
      RecursiveEnsure(pathutils.JOB_QUEUE_ARCHIVE_DIR, getent.masterd_uid,
                      getent.masterd_gid, 0700, 0600)
  except errors.GenericError, err:
    logging.error("An error occurred while setting permissions: %s", err)
    return constants.EXIT_FAILURE

  return constants.EXIT_SUCCESS
