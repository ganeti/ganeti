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

import errno
import os
import os.path
import optparse
import sys
import stat

from ganeti import constants
from ganeti import errors
from ganeti import runtime
from ganeti import ssconf
from ganeti import utils


(DIR,
 FILE,
 QUEUE_DIR) = range(1, 4)

ALL_TYPES = frozenset([
  DIR,
  FILE,
  QUEUE_DIR,
  ])


class EnsureError(errors.GenericError):
  """Top-level error class related to this script.

  """


def EnsurePermission(path, mode, uid=-1, gid=-1, must_exist=True,
                     _chmod_fn=os.chmod, _chown_fn=os.chown):
  """Ensures that given path has given mode.

  @param path: The path to the file
  @param mode: The mode of the file
  @param uid: The uid of the owner of this file
  @param gid: The gid of the owner of this file
  @param must_exist: Specifies if non-existance of path will be an error
  @param _chmod_fn: chmod function to use (unittest only)
  @param _chown_fn: chown function to use (unittest only)

  """
  try:
    _chmod_fn(path, mode)

    if max(uid, gid) > -1:
      _chown_fn(path, uid, gid)
  except EnvironmentError, err:
    if err.errno == errno.ENOENT:
      if must_exist:
        raise EnsureError("Path %s does not exists, but should" % path)
    else:
      raise EnsureError("Error while changing permission on %s: %s" %
                        (path, err))


def EnsureDir(path, mode, uid, gid, _stat_fn=os.lstat, _mkdir_fn=os.mkdir,
              _ensure_fn=EnsurePermission):
  """Ensures that given path is a dir and has given mode, uid and gid set.

  @param path: The path to the file
  @param mode: The mode of the file
  @param uid: The uid of the owner of this file
  @param gid: The gid of the owner of this file
  @param _stat_fn: Stat function to use (unittest only)
  @param _mkdir_fn: mkdir function to use (unittest only)
  @param _ensure_fn: ensure function to use (unittest only)

  """
  try:
    # We don't want to follow symlinks
    st_mode = _stat_fn(path)[stat.ST_MODE]

    if not stat.S_ISDIR(st_mode):
      raise EnsureError("Path %s is expected to be a directory, but it's not" %
                        path)
  except EnvironmentError, err:
    if err.errno == errno.ENOENT:
      _mkdir_fn(path)
    else:
      raise EnsureError("Error while do a stat() on %s: %s" % (path, err))

  _ensure_fn(path, mode, uid=uid, gid=gid)


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

  for root, dirs, files in os.walk(path):
    for subdir in dirs:
      EnsurePermission(os.path.join(root, subdir), dir_perm, uid=uid, gid=gid)

    for filename in files:
      EnsurePermission(os.path.join(root, filename), file_perm, uid=uid,
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
      EnsurePermission(utils.PathJoin(path, filename), mode, uid=uid, gid=gid)


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
      EnsureDir(pathname, mode, uid, gid)
    elif pathtype == QUEUE_DIR:
      EnsureQueueDir(pathname, mode, uid, gid)
  elif pathtype == FILE:
    (must_exist, ) = path[5:]
    EnsurePermission(pathname, mode, uid=uid, gid=gid, must_exist=must_exist)


def GetPaths():
  """Returns a tuple of path objects to process.

  """
  getent = runtime.GetEnts()
  masterd_log = constants.DAEMONS_LOGFILES[constants.MASTERD]
  noded_log = constants.DAEMONS_LOGFILES[constants.NODED]
  confd_log = constants.DAEMONS_LOGFILES[constants.CONFD]
  rapi_log = constants.DAEMONS_LOGFILES[constants.RAPI]

  rapi_dir = os.path.join(constants.DATA_DIR, "rapi")

  paths = [
    (constants.DATA_DIR, DIR, 0755, getent.masterd_uid,
     getent.masterd_gid),
    (constants.CLUSTER_DOMAIN_SECRET_FILE, FILE, 0640,
     getent.masterd_uid, getent.masterd_gid, False),
    (constants.CLUSTER_CONF_FILE, FILE, 0640, getent.masterd_uid,
     getent.confd_gid, False),
    (constants.CONFD_HMAC_KEY, FILE, 0440, getent.confd_uid,
     getent.masterd_gid, False),
    (constants.SSH_KNOWN_HOSTS_FILE, FILE, 0644, getent.masterd_uid,
     getent.masterd_gid, False),
    (constants.RAPI_CERT_FILE, FILE, 0440, getent.rapi_uid,
     getent.masterd_gid, False),
    (constants.NODED_CERT_FILE, FILE, 0440, getent.masterd_uid,
     getent.masterd_gid, False),
    ]

  ss = ssconf.SimpleStore()
  for ss_path in ss.GetFileList():
    paths.append((ss_path, FILE, constants.SS_FILE_PERMS,
                  getent.noded_uid, 0, False))

  paths.extend([
    (constants.QUEUE_DIR, DIR, 0700, getent.masterd_uid,
     getent.masterd_gid),
    (constants.QUEUE_DIR, QUEUE_DIR, 0600, getent.masterd_uid,
     getent.masterd_gid),
    (constants.JOB_QUEUE_LOCK_FILE, FILE, 0600,
     getent.masterd_uid, getent.masterd_gid, False),
    (constants.JOB_QUEUE_SERIAL_FILE, FILE, 0600,
     getent.masterd_uid, getent.masterd_gid, False),
    (constants.JOB_QUEUE_ARCHIVE_DIR, DIR, 0700,
     getent.masterd_uid, getent.masterd_gid),
    (rapi_dir, DIR, 0750, getent.rapi_uid, getent.masterd_gid),
    (constants.RAPI_USERS_FILE, FILE, 0640, getent.rapi_uid,
     getent.masterd_gid, False),
    (constants.RUN_GANETI_DIR, DIR, 0775, getent.masterd_uid,
     getent.daemons_gid),
    (constants.SOCKET_DIR, DIR, 0750, getent.masterd_uid,
     getent.daemons_gid),
    (constants.MASTER_SOCKET, FILE, 0770, getent.masterd_uid,
     getent.daemons_gid, False),
    (constants.BDEV_CACHE_DIR, DIR, 0755, getent.noded_uid,
     getent.masterd_gid),
    (constants.UIDPOOL_LOCKDIR, DIR, 0750, getent.noded_uid,
     getent.masterd_gid),
    (constants.DISK_LINKS_DIR, DIR, 0755, getent.noded_uid,
     getent.masterd_gid),
    (constants.CRYPTO_KEYS_DIR, DIR, 0700, getent.noded_uid,
     getent.masterd_gid),
    (constants.IMPORT_EXPORT_DIR, DIR, 0755, getent.noded_uid,
     getent.masterd_gid),
    (constants.LOG_DIR, DIR, 0770, getent.masterd_uid,
     getent.daemons_gid),
    (masterd_log, FILE, 0600, getent.masterd_uid, getent.masterd_gid,
     False),
    (confd_log, FILE, 0600, getent.confd_uid, getent.masterd_gid, False),
    (noded_log, FILE, 0600, getent.noded_uid, getent.masterd_gid, False),
    (rapi_log, FILE, 0600, getent.rapi_uid, getent.masterd_gid, False),
    (constants.LOG_OS_DIR, DIR, 0750, getent.masterd_uid,
     getent.daemons_gid),
    ])

  return tuple(paths)


def ParseOptions():
  """Parses the options passed to the program.

  @return: Options and arguments

  """
  program = os.path.basename(sys.argv[0])

  parser = optparse.OptionParser(usage="%%prog [--full-run]",
                                 prog=program)
  parser.add_option("--full-run", "-f", dest="full_run", action="store_true",
                    default=False, help=("Make a full run and collect"
                                         " additional files (time consuming)"))

  return parser.parse_args()


def Main():
  """Main routine.

  """
  getent = runtime.GetEnts()
  (opts, _) = ParseOptions()

  try:
    for path in GetPaths():
      ProcessPath(path)

    if opts.full_run:
      RecursiveEnsure(constants.JOB_QUEUE_ARCHIVE_DIR, getent.masterd_uid,
                      getent.masterd_gid, 0700, 0600)
  except EnsureError, err:
    print >> sys.stderr, "An error occurred while ensure permissions:", err
    return constants.EXIT_FAILURE

  return constants.EXIT_SUCCESS
