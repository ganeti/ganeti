#
#

# Copyright (C) 2013 Google Inc.
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


"""File storage functions.

"""

import logging
import os

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import pathutils
from ganeti import utils


def GetFileStorageSpaceInfo(path):
  """Retrieves the free and total space of the device where the file is
     located.

     @type path: string
     @param path: Path of the file whose embracing device's capacity is
       reported.
     @return: a dictionary containing 'vg_size' and 'vg_free' given in MebiBytes

  """
  try:
    result = os.statvfs(path)
    free = (result.f_frsize * result.f_bavail) / (1024 * 1024)
    size = (result.f_frsize * result.f_blocks) / (1024 * 1024)
    return {"type": constants.ST_FILE,
            "name": path,
            "storage_size": size,
            "storage_free": free}
  except OSError, e:
    raise errors.CommandError("Failed to retrieve file system information about"
                              " path: %s - %s" % (path, e.strerror))


def _GetForbiddenFileStoragePaths():
  """Builds a list of path prefixes which shouldn't be used for file storage.

  @rtype: frozenset

  """
  paths = set([
    "/boot",
    "/dev",
    "/etc",
    "/home",
    "/proc",
    "/root",
    "/sys",
    ])

  for prefix in ["", "/usr", "/usr/local"]:
    paths.update(map(lambda s: "%s/%s" % (prefix, s),
                     ["bin", "lib", "lib32", "lib64", "sbin"]))

  return compat.UniqueFrozenset(map(os.path.normpath, paths))


def _ComputeWrongFileStoragePaths(paths,
                                  _forbidden=_GetForbiddenFileStoragePaths()):
  """Cross-checks a list of paths for prefixes considered bad.

  Some paths, e.g. "/bin", should not be used for file storage.

  @type paths: list
  @param paths: List of paths to be checked
  @rtype: list
  @return: Sorted list of paths for which the user should be warned

  """
  def _Check(path):
    return (not os.path.isabs(path) or
            path in _forbidden or
            filter(lambda p: utils.IsBelowDir(p, path), _forbidden))

  return utils.NiceSort(filter(_Check, map(os.path.normpath, paths)))


def ComputeWrongFileStoragePaths(_filename=pathutils.FILE_STORAGE_PATHS_FILE):
  """Returns a list of file storage paths whose prefix is considered bad.

  See L{_ComputeWrongFileStoragePaths}.

  """
  return _ComputeWrongFileStoragePaths(_LoadAllowedFileStoragePaths(_filename))


def _CheckFileStoragePath(path, allowed, exact_match_ok=False):
  """Checks if a path is in a list of allowed paths for file storage.

  @type path: string
  @param path: Path to check
  @type allowed: list
  @param allowed: List of allowed paths
  @type exact_match_ok: bool
  @param exact_match_ok: whether or not it is okay when the path is exactly
      equal to an allowed path and not a subdir of it
  @raise errors.FileStoragePathError: If the path is not allowed

  """
  if not os.path.isabs(path):
    raise errors.FileStoragePathError("File storage path must be absolute,"
                                      " got '%s'" % path)

  for i in allowed:
    if not os.path.isabs(i):
      logging.info("Ignoring relative path '%s' for file storage", i)
      continue

    if exact_match_ok:
      if os.path.normpath(i) == os.path.normpath(path):
        break

    if utils.IsBelowDir(i, path):
      break
  else:
    raise errors.FileStoragePathError("Path '%s' is not acceptable for file"
                                      " storage" % path)


def _LoadAllowedFileStoragePaths(filename):
  """Loads file containing allowed file storage paths.

  @rtype: list
  @return: List of allowed paths (can be an empty list)

  """
  try:
    contents = utils.ReadFile(filename)
  except EnvironmentError:
    return []
  else:
    return utils.FilterEmptyLinesAndComments(contents)


def CheckFileStoragePathAcceptance(
    path, _filename=pathutils.FILE_STORAGE_PATHS_FILE,
    exact_match_ok=False):
  """Checks if a path is allowed for file storage.

  @type path: string
  @param path: Path to check
  @raise errors.FileStoragePathError: If the path is not allowed

  """
  allowed = _LoadAllowedFileStoragePaths(_filename)
  if not allowed:
    raise errors.FileStoragePathError("No paths are valid or path file '%s'"
                                      " was not accessible." % _filename)

  if _ComputeWrongFileStoragePaths([path]):
    raise errors.FileStoragePathError("Path '%s' uses a forbidden prefix" %
                                      path)

  _CheckFileStoragePath(path, allowed, exact_match_ok=exact_match_ok)


def _CheckFileStoragePathExistance(path):
  """Checks whether the given path is usable on the file system.

  This checks wether the path is existing, a directory and writable.

  @type path: string
  @param path: path to check

  """
  if not os.path.isdir(path):
    raise errors.FileStoragePathError("Path '%s' does not exist or is not a"
                                      " directory." % path)
  if not os.access(path, os.W_OK):
    raise errors.FileStoragePathError("Path '%s' is not writable" % path)


def CheckFileStoragePath(
    path, _allowed_paths_file=pathutils.FILE_STORAGE_PATHS_FILE):
  """Checks whether the path exists and is acceptable to use.

  Can be used for any file-based storage, for example shared-file storage.

  @type path: string
  @param path: path to check
  @rtype: string
  @returns: error message if the path is not ready to use

  """
  try:
    CheckFileStoragePathAcceptance(path, _filename=_allowed_paths_file,
                                   exact_match_ok=True)
  except errors.FileStoragePathError as e:
    return str(e)
  if not os.path.isdir(path):
    return "Path '%s' is not existing or not a directory." % path
  if not os.access(path, os.W_OK):
    return "Path '%s' is not writable" % path
