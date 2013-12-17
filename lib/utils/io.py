#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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

"""Utility functions for I/O.

"""

import os
import logging
import shutil
import tempfile
import errno
import time
import stat
import grp
import pwd

from ganeti import errors
from ganeti import constants
from ganeti import pathutils
from ganeti.utils import filelock

#: Directory used by fsck(8) to store recovered data, usually at a file
#: system's root directory
_LOST_AND_FOUND = "lost+found"

# Possible values for keep_perms in WriteFile()
KP_NEVER = 0
KP_ALWAYS = 1
KP_IF_EXISTS = 2

KEEP_PERMS_VALUES = [
  KP_NEVER,
  KP_ALWAYS,
  KP_IF_EXISTS,
  ]


def ErrnoOrStr(err):
  """Format an EnvironmentError exception.

  If the L{err} argument has an errno attribute, it will be looked up
  and converted into a textual C{E...} description. Otherwise the
  string representation of the error will be returned.

  @type err: L{EnvironmentError}
  @param err: the exception to format

  """
  if hasattr(err, "errno"):
    detail = errno.errorcode[err.errno]
  else:
    detail = str(err)
  return detail


class FileStatHelper:
  """Helper to store file handle's C{fstat}.

  Useful in combination with L{ReadFile}'s C{preread} parameter.

  """
  def __init__(self):
    """Initializes this class.

    """
    self.st = None

  def __call__(self, fh):
    """Calls C{fstat} on file handle.

    """
    self.st = os.fstat(fh.fileno())


def ReadFile(file_name, size=-1, preread=None):
  """Reads a file.

  @type size: int
  @param size: Read at most size bytes (if negative, entire file)
  @type preread: callable receiving file handle as single parameter
  @param preread: Function called before file is read
  @rtype: str
  @return: the (possibly partial) content of the file

  """
  f = open(file_name, "r")
  try:
    if preread:
      preread(f)

    return f.read(size)
  finally:
    f.close()


def WriteFile(file_name, fn=None, data=None,
              mode=None, uid=-1, gid=-1,
              atime=None, mtime=None, close=True,
              dry_run=False, backup=False,
              prewrite=None, postwrite=None, keep_perms=KP_NEVER):
  """(Over)write a file atomically.

  The file_name and either fn (a function taking one argument, the
  file descriptor, and which should write the data to it) or data (the
  contents of the file) must be passed. The other arguments are
  optional and allow setting the file mode, owner and group, and the
  mtime/atime of the file.

  If the function doesn't raise an exception, it has succeeded and the
  target file has the new contents. If the function has raised an
  exception, an existing target file should be unmodified and the
  temporary file should be removed.

  @type file_name: str
  @param file_name: the target filename
  @type fn: callable
  @param fn: content writing function, called with
      file descriptor as parameter
  @type data: str
  @param data: contents of the file
  @type mode: int
  @param mode: file mode
  @type uid: int
  @param uid: the owner of the file
  @type gid: int
  @param gid: the group of the file
  @type atime: int
  @param atime: a custom access time to be set on the file
  @type mtime: int
  @param mtime: a custom modification time to be set on the file
  @type close: boolean
  @param close: whether to close file after writing it
  @type prewrite: callable
  @param prewrite: function to be called before writing content
  @type postwrite: callable
  @param postwrite: function to be called after writing content
  @type keep_perms: members of L{KEEP_PERMS_VALUES}
  @param keep_perms: if L{KP_NEVER} (default), owner, group, and mode are
      taken from the other parameters; if L{KP_ALWAYS}, owner, group, and
      mode are copied from the existing file; if L{KP_IF_EXISTS}, owner,
      group, and mode are taken from the file, and if the file doesn't
      exist, they are taken from the other parameters. It is an error to
      pass L{KP_ALWAYS} when the file doesn't exist or when C{uid}, C{gid},
      or C{mode} are set to non-default values.

  @rtype: None or int
  @return: None if the 'close' parameter evaluates to True,
      otherwise the file descriptor

  @raise errors.ProgrammerError: if any of the arguments are not valid

  """
  if not os.path.isabs(file_name):
    raise errors.ProgrammerError("Path passed to WriteFile is not"
                                 " absolute: '%s'" % file_name)

  if [fn, data].count(None) != 1:
    raise errors.ProgrammerError("fn or data required")

  if [atime, mtime].count(None) == 1:
    raise errors.ProgrammerError("Both atime and mtime must be either"
                                 " set or None")

  if not keep_perms in KEEP_PERMS_VALUES:
    raise errors.ProgrammerError("Invalid value for keep_perms: %s" %
                                 keep_perms)
  if keep_perms == KP_ALWAYS and (uid != -1 or gid != -1 or mode is not None):
    raise errors.ProgrammerError("When keep_perms==KP_ALWAYS, 'uid', 'gid',"
                                 " and 'mode' cannot be set")

  if backup and not dry_run and os.path.isfile(file_name):
    CreateBackup(file_name)

  if keep_perms == KP_ALWAYS or keep_perms == KP_IF_EXISTS:
    # os.stat() raises an exception if the file doesn't exist
    try:
      file_stat = os.stat(file_name)
      mode = stat.S_IMODE(file_stat.st_mode)
      uid = file_stat.st_uid
      gid = file_stat.st_gid
    except OSError:
      if keep_perms == KP_ALWAYS:
        raise
      # else: if keeep_perms == KP_IF_EXISTS it's ok if the file doesn't exist

  # Whether temporary file needs to be removed (e.g. if any error occurs)
  do_remove = True

  # Function result
  result = None

  (dir_name, base_name) = os.path.split(file_name)
  (fd, new_name) = tempfile.mkstemp(suffix=".new", prefix=base_name,
                                    dir=dir_name)
  try:
    try:
      if uid != -1 or gid != -1:
        os.chown(new_name, uid, gid)
      if mode:
        os.chmod(new_name, mode)
      if callable(prewrite):
        prewrite(fd)
      if data is not None:
        if isinstance(data, unicode):
          data = data.encode()
        assert isinstance(data, str)
        to_write = len(data)
        offset = 0
        while offset < to_write:
          written = os.write(fd, buffer(data, offset))
          assert written >= 0
          assert written <= to_write - offset
          offset += written
        assert offset == to_write
      else:
        fn(fd)
      if callable(postwrite):
        postwrite(fd)
      os.fsync(fd)
      if atime is not None and mtime is not None:
        os.utime(new_name, (atime, mtime))
    finally:
      # Close file unless the file descriptor should be returned
      if close:
        os.close(fd)
      else:
        result = fd

    # Rename file to destination name
    if not dry_run:
      os.rename(new_name, file_name)
      # Successful, no need to remove anymore
      do_remove = False
  finally:
    if do_remove:
      RemoveFile(new_name)

  return result


def GetFileID(path=None, fd=None):
  """Returns the file 'id', i.e. the dev/inode and mtime information.

  Either the path to the file or the fd must be given.

  @param path: the file path
  @param fd: a file descriptor
  @return: a tuple of (device number, inode number, mtime)

  """
  if [path, fd].count(None) != 1:
    raise errors.ProgrammerError("One and only one of fd/path must be given")

  if fd is None:
    st = os.stat(path)
  else:
    st = os.fstat(fd)

  return (st.st_dev, st.st_ino, st.st_mtime)


def VerifyFileID(fi_disk, fi_ours):
  """Verifies that two file IDs are matching.

  Differences in the inode/device are not accepted, but and older
  timestamp for fi_disk is accepted.

  @param fi_disk: tuple (dev, inode, mtime) representing the actual
      file data
  @param fi_ours: tuple (dev, inode, mtime) representing the last
      written file data
  @rtype: boolean

  """
  (d1, i1, m1) = fi_disk
  (d2, i2, m2) = fi_ours

  return (d1, i1) == (d2, i2) and m1 <= m2


def SafeWriteFile(file_name, file_id, **kwargs):
  """Wraper over L{WriteFile} that locks the target file.

  By keeping the target file locked during WriteFile, we ensure that
  cooperating writers will safely serialise access to the file.

  @type file_name: str
  @param file_name: the target filename
  @type file_id: tuple
  @param file_id: a result from L{GetFileID}

  """
  fd = os.open(file_name, os.O_RDONLY | os.O_CREAT)
  try:
    filelock.LockFile(fd)
    if file_id is not None:
      disk_id = GetFileID(fd=fd)
      if not VerifyFileID(disk_id, file_id):
        raise errors.LockError("Cannot overwrite file %s, it has been modified"
                               " since last written" % file_name)
    return WriteFile(file_name, **kwargs)
  finally:
    os.close(fd)


def ReadOneLineFile(file_name, strict=False):
  """Return the first non-empty line from a file.

  @type strict: boolean
  @param strict: if True, abort if the file has more than one
      non-empty line

  """
  file_lines = ReadFile(file_name).splitlines()
  full_lines = filter(bool, file_lines)
  if not file_lines or not full_lines:
    raise errors.GenericError("No data in one-liner file %s" % file_name)
  elif strict and len(full_lines) > 1:
    raise errors.GenericError("Too many lines in one-liner file %s" %
                              file_name)
  return full_lines[0]


def RemoveFile(filename):
  """Remove a file ignoring some errors.

  Remove a file, ignoring non-existing ones or directories. Other
  errors are passed.

  @type filename: str
  @param filename: the file to be removed

  """
  try:
    os.unlink(filename)
  except OSError, err:
    if err.errno not in (errno.ENOENT, errno.EISDIR):
      raise


def RemoveDir(dirname):
  """Remove an empty directory.

  Remove a directory, ignoring non-existing ones.
  Other errors are passed. This includes the case,
  where the directory is not empty, so it can't be removed.

  @type dirname: str
  @param dirname: the empty directory to be removed

  """
  try:
    os.rmdir(dirname)
  except OSError, err:
    if err.errno != errno.ENOENT:
      raise


def RenameFile(old, new, mkdir=False, mkdir_mode=0750, dir_uid=None,
               dir_gid=None):
  """Renames a file.

  This just creates the very least directory if it does not exist and C{mkdir}
  is set to true.

  @type old: string
  @param old: Original path
  @type new: string
  @param new: New path
  @type mkdir: bool
  @param mkdir: Whether to create target directory if it doesn't exist
  @type mkdir_mode: int
  @param mkdir_mode: Mode for newly created directories
  @type dir_uid: int
  @param dir_uid: The uid for the (if fresh created) dir
  @type dir_gid: int
  @param dir_gid: The gid for the (if fresh created) dir

  """
  try:
    return os.rename(old, new)
  except OSError, err:
    # In at least one use case of this function, the job queue, directory
    # creation is very rare. Checking for the directory before renaming is not
    # as efficient.
    if mkdir and err.errno == errno.ENOENT:
      # Create directory and try again
      dir_path = os.path.dirname(new)
      MakeDirWithPerm(dir_path, mkdir_mode, dir_uid, dir_gid)

      return os.rename(old, new)

    raise


def EnforcePermission(path, mode, uid=None, gid=None, must_exist=True,
                      _chmod_fn=os.chmod, _chown_fn=os.chown, _stat_fn=os.stat):
  """Enforces that given path has given permissions.

  @param path: The path to the file
  @param mode: The mode of the file
  @param uid: The uid of the owner of this file
  @param gid: The gid of the owner of this file
  @param must_exist: Specifies if non-existance of path will be an error
  @param _chmod_fn: chmod function to use (unittest only)
  @param _chown_fn: chown function to use (unittest only)

  """
  logging.debug("Checking %s", path)

  # chown takes -1 if you want to keep one part of the ownership, however
  # None is Python standard for that. So we remap them here.
  if uid is None:
    uid = -1
  if gid is None:
    gid = -1

  try:
    st = _stat_fn(path)

    fmode = stat.S_IMODE(st[stat.ST_MODE])
    if fmode != mode:
      logging.debug("Changing mode of %s from %#o to %#o", path, fmode, mode)
      _chmod_fn(path, mode)

    if max(uid, gid) > -1:
      fuid = st[stat.ST_UID]
      fgid = st[stat.ST_GID]
      if fuid != uid or fgid != gid:
        logging.debug("Changing owner of %s from UID %s/GID %s to"
                      " UID %s/GID %s", path, fuid, fgid, uid, gid)
        _chown_fn(path, uid, gid)
  except EnvironmentError, err:
    if err.errno == errno.ENOENT:
      if must_exist:
        raise errors.GenericError("Path %s should exist, but does not" % path)
    else:
      raise errors.GenericError("Error while changing permissions on %s: %s" %
                                (path, err))


def MakeDirWithPerm(path, mode, uid, gid, _lstat_fn=os.lstat,
                    _mkdir_fn=os.mkdir, _perm_fn=EnforcePermission):
  """Enforces that given path is a dir and has given mode, uid and gid set.

  @param path: The path to the file
  @param mode: The mode of the file
  @param uid: The uid of the owner of this file
  @param gid: The gid of the owner of this file
  @param _lstat_fn: Stat function to use (unittest only)
  @param _mkdir_fn: mkdir function to use (unittest only)
  @param _perm_fn: permission setter function to use (unittest only)

  """
  logging.debug("Checking directory %s", path)
  try:
    # We don't want to follow symlinks
    st = _lstat_fn(path)
  except EnvironmentError, err:
    if err.errno != errno.ENOENT:
      raise errors.GenericError("stat(2) on %s failed: %s" % (path, err))
    _mkdir_fn(path)
  else:
    if not stat.S_ISDIR(st[stat.ST_MODE]):
      raise errors.GenericError(("Path %s is expected to be a directory, but "
                                 "isn't") % path)

  _perm_fn(path, mode, uid=uid, gid=gid)


def Makedirs(path, mode=0750):
  """Super-mkdir; create a leaf directory and all intermediate ones.

  This is a wrapper around C{os.makedirs} adding error handling not implemented
  before Python 2.5.

  """
  try:
    os.makedirs(path, mode)
  except OSError, err:
    # Ignore EEXIST. This is only handled in os.makedirs as included in
    # Python 2.5 and above.
    if err.errno != errno.EEXIST or not os.path.exists(path):
      raise


def TimestampForFilename():
  """Returns the current time formatted for filenames.

  The format doesn't contain colons as some shells and applications treat them
  as separators. Uses the local timezone.

  """
  return time.strftime("%Y-%m-%d_%H_%M_%S")


def CreateBackup(file_name):
  """Creates a backup of a file.

  @type file_name: str
  @param file_name: file to be backed up
  @rtype: str
  @return: the path to the newly created backup
  @raise errors.ProgrammerError: for invalid file names

  """
  if not os.path.isfile(file_name):
    raise errors.ProgrammerError("Can't make a backup of a non-file '%s'" %
                                 file_name)

  prefix = ("%s.backup-%s." %
            (os.path.basename(file_name), TimestampForFilename()))
  dir_name = os.path.dirname(file_name)

  fsrc = open(file_name, "rb")
  try:
    (fd, backup_name) = tempfile.mkstemp(prefix=prefix, dir=dir_name)
    fdst = os.fdopen(fd, "wb")
    try:
      logging.debug("Backing up %s at %s", file_name, backup_name)
      shutil.copyfileobj(fsrc, fdst)
    finally:
      fdst.close()
  finally:
    fsrc.close()

  return backup_name


def ListVisibleFiles(path, _is_mountpoint=os.path.ismount):
  """Returns a list of visible files in a directory.

  @type path: str
  @param path: the directory to enumerate
  @rtype: list
  @return: the list of all files not starting with a dot
  @raise ProgrammerError: if L{path} is not an absolue and normalized path

  """
  if not IsNormAbsPath(path):
    raise errors.ProgrammerError("Path passed to ListVisibleFiles is not"
                                 " absolute/normalized: '%s'" % path)

  mountpoint = _is_mountpoint(path)

  def fn(name):
    """File name filter.

    Ignores files starting with a dot (".") as by Unix convention they're
    considered hidden. The "lost+found" directory found at the root of some
    filesystems is also hidden.

    """
    return not (name.startswith(".") or
                (mountpoint and name == _LOST_AND_FOUND and
                 os.path.isdir(os.path.join(path, name))))

  return filter(fn, os.listdir(path))


def EnsureDirs(dirs):
  """Make required directories, if they don't exist.

  @param dirs: list of tuples (dir_name, dir_mode)
  @type dirs: list of (string, integer)

  """
  for dir_name, dir_mode in dirs:
    try:
      os.mkdir(dir_name, dir_mode)
    except EnvironmentError, err:
      if err.errno != errno.EEXIST:
        raise errors.GenericError("Cannot create needed directory"
                                  " '%s': %s" % (dir_name, err))
    try:
      os.chmod(dir_name, dir_mode)
    except EnvironmentError, err:
      raise errors.GenericError("Cannot change directory permissions on"
                                " '%s': %s" % (dir_name, err))
    if not os.path.isdir(dir_name):
      raise errors.GenericError("%s is not a directory" % dir_name)


def FindFile(name, search_path, test=os.path.exists):
  """Look for a filesystem object in a given path.

  This is an abstract method to search for filesystem object (files,
  dirs) under a given search path.

  @type name: str
  @param name: the name to look for
  @type search_path: str
  @param search_path: location to start at
  @type test: callable
  @param test: a function taking one argument that should return True
      if the a given object is valid; the default value is
      os.path.exists, causing only existing files to be returned
  @rtype: str or None
  @return: full path to the object if found, None otherwise

  """
  # validate the filename mask
  if constants.EXT_PLUGIN_MASK.match(name) is None:
    logging.critical("Invalid value passed for external script name: '%s'",
                     name)
    return None

  for dir_name in search_path:
    # FIXME: investigate switch to PathJoin
    item_name = os.path.sep.join([dir_name, name])
    # check the user test and that we're indeed resolving to the given
    # basename
    if test(item_name) and os.path.basename(item_name) == name:
      return item_name
  return None


def IsNormAbsPath(path):
  """Check whether a path is absolute and also normalized

  This avoids things like /dir/../../other/path to be valid.

  """
  return os.path.normpath(path) == path and os.path.isabs(path)


def IsBelowDir(root, other_path):
  """Check whether a path is below a root dir.

  This works around the nasty byte-byte comparison of commonprefix.

  """
  if not (os.path.isabs(root) and os.path.isabs(other_path)):
    raise ValueError("Provided paths '%s' and '%s' are not absolute" %
                     (root, other_path))

  norm_other = os.path.normpath(other_path)

  if norm_other == os.sep:
    # The root directory can never be below another path
    return False

  norm_root = os.path.normpath(root)

  if norm_root == os.sep:
    # This is the root directory, no need to add another slash
    prepared_root = norm_root
  else:
    prepared_root = "%s%s" % (norm_root, os.sep)

  return os.path.commonprefix([prepared_root, norm_other]) == prepared_root


def PathJoin(*args):
  """Safe-join a list of path components.

  Requirements:
      - the first argument must be an absolute path
      - no component in the path must have backtracking (e.g. /../),
        since we check for normalization at the end

  @param args: the path components to be joined
  @raise ValueError: for invalid paths

  """
  # ensure we're having at least two paths passed in
  if len(args) <= 1:
    raise errors.ProgrammerError("PathJoin requires two arguments")
  # ensure the first component is an absolute and normalized path name
  root = args[0]
  if not IsNormAbsPath(root):
    raise ValueError("Invalid parameter to PathJoin: '%s'" % str(args[0]))
  result = os.path.join(*args)
  # ensure that the whole path is normalized
  if not IsNormAbsPath(result):
    raise ValueError("Invalid parameters to PathJoin: '%s'" % str(args))
  # check that we're still under the original prefix
  if not IsBelowDir(root, result):
    raise ValueError("Error: path joining resulted in different prefix"
                     " (%s != %s)" % (result, root))
  return result


def TailFile(fname, lines=20):
  """Return the last lines from a file.

  @note: this function will only read and parse the last 4KB of
      the file; if the lines are very long, it could be that less
      than the requested number of lines are returned

  @param fname: the file name
  @type lines: int
  @param lines: the (maximum) number of lines to return

  """
  fd = open(fname, "r")
  try:
    fd.seek(0, 2)
    pos = fd.tell()
    pos = max(0, pos - 4096)
    fd.seek(pos, 0)
    raw_data = fd.read()
  finally:
    fd.close()

  rows = raw_data.splitlines()
  return rows[-lines:]


def BytesToMebibyte(value):
  """Converts bytes to mebibytes.

  @type value: int
  @param value: Value in bytes
  @rtype: int
  @return: Value in mebibytes

  """
  return int(round(value / (1024.0 * 1024.0), 0))


def CalculateDirectorySize(path):
  """Calculates the size of a directory recursively.

  @type path: string
  @param path: Path to directory
  @rtype: int
  @return: Size in mebibytes

  """
  size = 0

  for (curpath, _, files) in os.walk(path):
    for filename in files:
      st = os.lstat(PathJoin(curpath, filename))
      size += st.st_size

  return BytesToMebibyte(size)


def GetFilesystemStats(path):
  """Returns the total and free space on a filesystem.

  @type path: string
  @param path: Path on filesystem to be examined
  @rtype: int
  @return: tuple of (Total space, Free space) in mebibytes

  """
  st = os.statvfs(path)

  fsize = BytesToMebibyte(st.f_bavail * st.f_frsize)
  tsize = BytesToMebibyte(st.f_blocks * st.f_frsize)
  return (tsize, fsize)


def ReadPidFile(pidfile):
  """Read a pid from a file.

  @type  pidfile: string
  @param pidfile: path to the file containing the pid
  @rtype: int
  @return: The process id, if the file exists and contains a valid PID,
           otherwise 0

  """
  try:
    raw_data = ReadOneLineFile(pidfile)
  except EnvironmentError, err:
    if err.errno != errno.ENOENT:
      logging.exception("Can't read pid file")
    return 0

  return _ParsePidFileContents(raw_data)


def _ParsePidFileContents(data):
  """Tries to extract a process ID from a PID file's content.

  @type data: string
  @rtype: int
  @return: Zero if nothing could be read, PID otherwise

  """
  try:
    pid = int(data)
  except (TypeError, ValueError):
    logging.info("Can't parse pid file contents", exc_info=True)
    return 0
  else:
    return pid


def ReadLockedPidFile(path):
  """Reads a locked PID file.

  This can be used together with L{utils.process.StartDaemon}.

  @type path: string
  @param path: Path to PID file
  @return: PID as integer or, if file was unlocked or couldn't be opened, None

  """
  try:
    fd = os.open(path, os.O_RDONLY)
  except EnvironmentError, err:
    if err.errno == errno.ENOENT:
      # PID file doesn't exist
      return None
    raise

  try:
    try:
      # Try to acquire lock
      filelock.LockFile(fd)
    except errors.LockError:
      # Couldn't lock, daemon is running
      return int(os.read(fd, 100))
  finally:
    os.close(fd)

  return None


def _SplitSshKey(key):
  """Splits a line for SSH's C{authorized_keys} file.

  If the line has no options (e.g. no C{command="..."}), only the significant
  parts, the key type and its hash, are used. Otherwise the whole line is used
  (split at whitespace).

  @type key: string
  @param key: Key line
  @rtype: tuple

  """
  parts = key.split()

  if parts and parts[0] in constants.SSHAK_ALL:
    # If the key has no options in front of it, we only want the significant
    # fields
    return (False, parts[:2])
  else:
    # Can't properly split the line, so use everything
    return (True, parts)


def AddAuthorizedKey(file_obj, key):
  """Adds an SSH public key to an authorized_keys file.

  @type file_obj: str or file handle
  @param file_obj: path to authorized_keys file
  @type key: str
  @param key: string containing key

  """
  key_fields = _SplitSshKey(key)

  if isinstance(file_obj, basestring):
    f = open(file_obj, "a+")
  else:
    f = file_obj

  try:
    nl = True
    for line in f:
      # Ignore whitespace changes
      if _SplitSshKey(line) == key_fields:
        break
      nl = line.endswith("\n")
    else:
      if not nl:
        f.write("\n")
      f.write(key.rstrip("\r\n"))
      f.write("\n")
      f.flush()
  finally:
    f.close()


def RemoveAuthorizedKey(file_name, key):
  """Removes an SSH public key from an authorized_keys file.

  @type file_name: str
  @param file_name: path to authorized_keys file
  @type key: str
  @param key: string containing key

  """
  key_fields = _SplitSshKey(key)

  fd, tmpname = tempfile.mkstemp(dir=os.path.dirname(file_name))
  try:
    out = os.fdopen(fd, "w")
    try:
      f = open(file_name, "r")
      try:
        for line in f:
          # Ignore whitespace changes while comparing lines
          if _SplitSshKey(line) != key_fields:
            out.write(line)

        out.flush()
        os.rename(tmpname, file_name)
      finally:
        f.close()
    finally:
      out.close()
  except:
    RemoveFile(tmpname)
    raise


def DaemonPidFileName(name):
  """Compute a ganeti pid file absolute path

  @type name: str
  @param name: the daemon name
  @rtype: str
  @return: the full path to the pidfile corresponding to the given
      daemon name

  """
  return PathJoin(pathutils.RUN_DIR, "%s.pid" % name)


def WritePidFile(pidfile):
  """Write the current process pidfile.

  @type pidfile: string
  @param pidfile: the path to the file to be written
  @raise errors.LockError: if the pid file already exists and
      points to a live process
  @rtype: int
  @return: the file descriptor of the lock file; do not close this unless
      you want to unlock the pid file

  """
  # We don't rename nor truncate the file to not drop locks under
  # existing processes
  fd_pidfile = os.open(pidfile, os.O_RDWR | os.O_CREAT, 0600)

  # Lock the PID file (and fail if not possible to do so). Any code
  # wanting to send a signal to the daemon should try to lock the PID
  # file before reading it. If acquiring the lock succeeds, the daemon is
  # no longer running and the signal should not be sent.
  try:
    filelock.LockFile(fd_pidfile)
  except errors.LockError:
    msg = ["PID file '%s' is already locked by another process" % pidfile]
    # Try to read PID file
    pid = _ParsePidFileContents(os.read(fd_pidfile, 100))
    if pid > 0:
      msg.append(", PID read from file is %s" % pid)
    raise errors.PidFileLockError("".join(msg))

  os.write(fd_pidfile, "%d\n" % os.getpid())

  return fd_pidfile


def ReadWatcherPauseFile(filename, now=None, remove_after=3600):
  """Reads the watcher pause file.

  @type filename: string
  @param filename: Path to watcher pause file
  @type now: None, float or int
  @param now: Current time as Unix timestamp
  @type remove_after: int
  @param remove_after: Remove watcher pause file after specified amount of
    seconds past the pause end time

  """
  if now is None:
    now = time.time()

  try:
    value = ReadFile(filename)
  except IOError, err:
    if err.errno != errno.ENOENT:
      raise
    value = None

  if value is not None:
    try:
      value = int(value)
    except ValueError:
      logging.warning(("Watcher pause file (%s) contains invalid value,"
                       " removing it"), filename)
      RemoveFile(filename)
      value = None

    if value is not None:
      # Remove file if it's outdated
      if now > (value + remove_after):
        RemoveFile(filename)
        value = None

      elif now > value:
        value = None

  return value


def NewUUID():
  """Returns a random UUID.

  @note: This is a Linux-specific method as it uses the /proc
      filesystem.
  @rtype: str

  """
  return ReadFile(constants.RANDOM_UUID_FILE, size=128).rstrip("\n")


class TemporaryFileManager(object):
  """Stores the list of files to be deleted and removes them on demand.

  """

  def __init__(self):
    self._files = []

  def __del__(self):
    self.Cleanup()

  def Add(self, filename):
    """Add file to list of files to be deleted.

    @type filename: string
    @param filename: path to filename to be added

    """
    self._files.append(filename)

  def Remove(self, filename):
    """Remove file from list of files to be deleted.

    @type filename: string
    @param filename: path to filename to be deleted

    """
    self._files.remove(filename)

  def Cleanup(self):
    """Delete all files marked for deletion

    """
    while self._files:
      RemoveFile(self._files.pop())


def IsUserInGroup(uid, gid):
  """Returns True if the user belongs to the group.

  @type uid: int
  @param uid: the user id
  @type gid: int
  @param gid: the group id
  @rtype: bool

  """
  user = pwd.getpwuid(uid)
  group = grp.getgrgid(gid)
  return user.pw_gid == gid or user.pw_name in group.gr_mem


def CanRead(username, filename):
  """Returns True if the user can access (read) the file.

  @type username: string
  @param username: the name of the user
  @type filename: string
  @param filename: the name of the file
  @rtype: bool

  """
  filestats = os.stat(filename)
  user = pwd.getpwnam(username)
  uid = user.pw_uid
  user_readable = filestats.st_mode & stat.S_IRUSR != 0
  group_readable = filestats.st_mode & stat.S_IRGRP != 0
  return ((filestats.st_uid == uid and user_readable)
          or (filestats.st_uid != uid and
              IsUserInGroup(uid, filestats.st_gid) and group_readable))
