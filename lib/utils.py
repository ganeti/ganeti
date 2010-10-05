#
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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


"""Ganeti utility module.

This module holds functions that can be used in both daemons (all) and
the command line scripts.

"""


import os
import sys
import time
import subprocess
import re
import socket
import tempfile
import shutil
import errno
import pwd
import itertools
import select
import fcntl
import resource
import logging
import logging.handlers
import signal
import OpenSSL
import datetime
import calendar
import hmac
import collections

from cStringIO import StringIO

try:
  # pylint: disable-msg=F0401
  import ctypes
except ImportError:
  ctypes = None

from ganeti import errors
from ganeti import constants
from ganeti import compat


_locksheld = []
_re_shell_unquoted = re.compile('^[-.,=:/_+@A-Za-z0-9]+$')

debug_locks = False

#: when set to True, L{RunCmd} is disabled
no_fork = False

_RANDOM_UUID_FILE = "/proc/sys/kernel/random/uuid"

HEX_CHAR_RE = r"[a-zA-Z0-9]"
VALID_X509_SIGNATURE_SALT = re.compile("^%s+$" % HEX_CHAR_RE, re.S)
X509_SIGNATURE = re.compile(r"^%s:\s*(?P<salt>%s+)/(?P<sign>%s+)$" %
                            (re.escape(constants.X509_CERT_SIGNATURE_HEADER),
                             HEX_CHAR_RE, HEX_CHAR_RE),
                            re.S | re.I)

_VALID_SERVICE_NAME_RE = re.compile("^[-_.a-zA-Z0-9]{1,128}$")

UUID_RE = re.compile('^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-'
                     '[a-f0-9]{4}-[a-f0-9]{12}$')

# Certificate verification results
(CERT_WARNING,
 CERT_ERROR) = range(1, 3)

# Flags for mlockall() (from bits/mman.h)
_MCL_CURRENT = 1
_MCL_FUTURE = 2

#: MAC checker regexp
_MAC_CHECK = re.compile("^([0-9a-f]{2}:){5}[0-9a-f]{2}$", re.I)


class RunResult(object):
  """Holds the result of running external programs.

  @type exit_code: int
  @ivar exit_code: the exit code of the program, or None (if the program
      didn't exit())
  @type signal: int or None
  @ivar signal: the signal that caused the program to finish, or None
      (if the program wasn't terminated by a signal)
  @type stdout: str
  @ivar stdout: the standard output of the program
  @type stderr: str
  @ivar stderr: the standard error of the program
  @type failed: boolean
  @ivar failed: True in case the program was
      terminated by a signal or exited with a non-zero exit code
  @ivar fail_reason: a string detailing the termination reason

  """
  __slots__ = ["exit_code", "signal", "stdout", "stderr",
               "failed", "fail_reason", "cmd"]


  def __init__(self, exit_code, signal_, stdout, stderr, cmd):
    self.cmd = cmd
    self.exit_code = exit_code
    self.signal = signal_
    self.stdout = stdout
    self.stderr = stderr
    self.failed = (signal_ is not None or exit_code != 0)

    if self.signal is not None:
      self.fail_reason = "terminated by signal %s" % self.signal
    elif self.exit_code is not None:
      self.fail_reason = "exited with exit code %s" % self.exit_code
    else:
      self.fail_reason = "unable to determine termination reason"

    if self.failed:
      logging.debug("Command '%s' failed (%s); output: %s",
                    self.cmd, self.fail_reason, self.output)

  def _GetOutput(self):
    """Returns the combined stdout and stderr for easier usage.

    """
    return self.stdout + self.stderr

  output = property(_GetOutput, None, None, "Return full output")


def _BuildCmdEnvironment(env, reset):
  """Builds the environment for an external program.

  """
  if reset:
    cmd_env = {}
  else:
    cmd_env = os.environ.copy()
    cmd_env["LC_ALL"] = "C"

  if env is not None:
    cmd_env.update(env)

  return cmd_env


def RunCmd(cmd, env=None, output=None, cwd="/", reset_env=False,
           interactive=False):
  """Execute a (shell) command.

  The command should not read from its standard input, as it will be
  closed.

  @type cmd: string or list
  @param cmd: Command to run
  @type env: dict
  @param env: Additional environment variables
  @type output: str
  @param output: if desired, the output of the command can be
      saved in a file instead of the RunResult instance; this
      parameter denotes the file name (if not None)
  @type cwd: string
  @param cwd: if specified, will be used as the working
      directory for the command; the default will be /
  @type reset_env: boolean
  @param reset_env: whether to reset or keep the default os environment
  @type interactive: boolean
  @param interactive: weather we pipe stdin, stdout and stderr
                      (default behaviour) or run the command interactive
  @rtype: L{RunResult}
  @return: RunResult instance
  @raise errors.ProgrammerError: if we call this when forks are disabled

  """
  if no_fork:
    raise errors.ProgrammerError("utils.RunCmd() called with fork() disabled")

  if output and interactive:
    raise errors.ProgrammerError("Parameters 'output' and 'interactive' can"
                                 " not be provided at the same time")

  if isinstance(cmd, basestring):
    strcmd = cmd
    shell = True
  else:
    cmd = [str(val) for val in cmd]
    strcmd = ShellQuoteArgs(cmd)
    shell = False

  if output:
    logging.debug("RunCmd %s, output file '%s'", strcmd, output)
  else:
    logging.debug("RunCmd %s", strcmd)

  cmd_env = _BuildCmdEnvironment(env, reset_env)

  try:
    if output is None:
      out, err, status = _RunCmdPipe(cmd, cmd_env, shell, cwd, interactive)
    else:
      status = _RunCmdFile(cmd, cmd_env, shell, output, cwd)
      out = err = ""
  except OSError, err:
    if err.errno == errno.ENOENT:
      raise errors.OpExecError("Can't execute '%s': not found (%s)" %
                               (strcmd, err))
    else:
      raise

  if status >= 0:
    exitcode = status
    signal_ = None
  else:
    exitcode = None
    signal_ = -status

  return RunResult(exitcode, signal_, out, err, strcmd)


def SetupDaemonEnv(cwd="/", umask=077):
  """Setup a daemon's environment.

  This should be called between the first and second fork, due to
  setsid usage.

  @param cwd: the directory to which to chdir
  @param umask: the umask to setup

  """
  os.chdir(cwd)
  os.umask(umask)
  os.setsid()


def SetupDaemonFDs(output_file, output_fd):
  """Setups up a daemon's file descriptors.

  @param output_file: if not None, the file to which to redirect
      stdout/stderr
  @param output_fd: if not None, the file descriptor for stdout/stderr

  """
  # check that at most one is defined
  assert [output_file, output_fd].count(None) >= 1

  # Open /dev/null (read-only, only for stdin)
  devnull_fd = os.open(os.devnull, os.O_RDONLY)

  if output_fd is not None:
    pass
  elif output_file is not None:
    # Open output file
    try:
      output_fd = os.open(output_file,
                          os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0600)
    except EnvironmentError, err:
      raise Exception("Opening output file failed: %s" % err)
  else:
    output_fd = os.open(os.devnull, os.O_WRONLY)

  # Redirect standard I/O
  os.dup2(devnull_fd, 0)
  os.dup2(output_fd, 1)
  os.dup2(output_fd, 2)


def StartDaemon(cmd, env=None, cwd="/", output=None, output_fd=None,
                pidfile=None):
  """Start a daemon process after forking twice.

  @type cmd: string or list
  @param cmd: Command to run
  @type env: dict
  @param env: Additional environment variables
  @type cwd: string
  @param cwd: Working directory for the program
  @type output: string
  @param output: Path to file in which to save the output
  @type output_fd: int
  @param output_fd: File descriptor for output
  @type pidfile: string
  @param pidfile: Process ID file
  @rtype: int
  @return: Daemon process ID
  @raise errors.ProgrammerError: if we call this when forks are disabled

  """
  if no_fork:
    raise errors.ProgrammerError("utils.StartDaemon() called with fork()"
                                 " disabled")

  if output and not (bool(output) ^ (output_fd is not None)):
    raise errors.ProgrammerError("Only one of 'output' and 'output_fd' can be"
                                 " specified")

  if isinstance(cmd, basestring):
    cmd = ["/bin/sh", "-c", cmd]

  strcmd = ShellQuoteArgs(cmd)

  if output:
    logging.debug("StartDaemon %s, output file '%s'", strcmd, output)
  else:
    logging.debug("StartDaemon %s", strcmd)

  cmd_env = _BuildCmdEnvironment(env, False)

  # Create pipe for sending PID back
  (pidpipe_read, pidpipe_write) = os.pipe()
  try:
    try:
      # Create pipe for sending error messages
      (errpipe_read, errpipe_write) = os.pipe()
      try:
        try:
          # First fork
          pid = os.fork()
          if pid == 0:
            try:
              # Child process, won't return
              _StartDaemonChild(errpipe_read, errpipe_write,
                                pidpipe_read, pidpipe_write,
                                cmd, cmd_env, cwd,
                                output, output_fd, pidfile)
            finally:
              # Well, maybe child process failed
              os._exit(1) # pylint: disable-msg=W0212
        finally:
          _CloseFDNoErr(errpipe_write)

        # Wait for daemon to be started (or an error message to arrive) and read
        # up to 100 KB as an error message
        errormsg = RetryOnSignal(os.read, errpipe_read, 100 * 1024)
      finally:
        _CloseFDNoErr(errpipe_read)
    finally:
      _CloseFDNoErr(pidpipe_write)

    # Read up to 128 bytes for PID
    pidtext = RetryOnSignal(os.read, pidpipe_read, 128)
  finally:
    _CloseFDNoErr(pidpipe_read)

  # Try to avoid zombies by waiting for child process
  try:
    os.waitpid(pid, 0)
  except OSError:
    pass

  if errormsg:
    raise errors.OpExecError("Error when starting daemon process: %r" %
                             errormsg)

  try:
    return int(pidtext)
  except (ValueError, TypeError), err:
    raise errors.OpExecError("Error while trying to parse PID %r: %s" %
                             (pidtext, err))


def _StartDaemonChild(errpipe_read, errpipe_write,
                      pidpipe_read, pidpipe_write,
                      args, env, cwd,
                      output, fd_output, pidfile):
  """Child process for starting daemon.

  """
  try:
    # Close parent's side
    _CloseFDNoErr(errpipe_read)
    _CloseFDNoErr(pidpipe_read)

    # First child process
    SetupDaemonEnv()

    # And fork for the second time
    pid = os.fork()
    if pid != 0:
      # Exit first child process
      os._exit(0) # pylint: disable-msg=W0212

    # Make sure pipe is closed on execv* (and thereby notifies
    # original process)
    SetCloseOnExecFlag(errpipe_write, True)

    # List of file descriptors to be left open
    noclose_fds = [errpipe_write]

    # Open PID file
    if pidfile:
      fd_pidfile = WritePidFile(pidfile)

      # Keeping the file open to hold the lock
      noclose_fds.append(fd_pidfile)

      SetCloseOnExecFlag(fd_pidfile, False)
    else:
      fd_pidfile = None

    SetupDaemonFDs(output, fd_output)

    # Send daemon PID to parent
    RetryOnSignal(os.write, pidpipe_write, str(os.getpid()))

    # Close all file descriptors except stdio and error message pipe
    CloseFDs(noclose_fds=noclose_fds)

    # Change working directory
    os.chdir(cwd)

    if env is None:
      os.execvp(args[0], args)
    else:
      os.execvpe(args[0], args, env)
  except: # pylint: disable-msg=W0702
    try:
      # Report errors to original process
      buf = str(sys.exc_info()[1])

      RetryOnSignal(os.write, errpipe_write, buf)
    except: # pylint: disable-msg=W0702
      # Ignore errors in error handling
      pass

  os._exit(1) # pylint: disable-msg=W0212


def _RunCmdPipe(cmd, env, via_shell, cwd, interactive):
  """Run a command and return its output.

  @type  cmd: string or list
  @param cmd: Command to run
  @type env: dict
  @param env: The environment to use
  @type via_shell: bool
  @param via_shell: if we should run via the shell
  @type cwd: string
  @param cwd: the working directory for the program
  @type interactive: boolean
  @param interactive: Run command interactive (without piping)
  @rtype: tuple
  @return: (out, err, status)

  """
  poller = select.poll()

  stderr = subprocess.PIPE
  stdout = subprocess.PIPE
  stdin = subprocess.PIPE

  if interactive:
    stderr = stdout = stdin = None

  child = subprocess.Popen(cmd, shell=via_shell,
                           stderr=stderr,
                           stdout=stdout,
                           stdin=stdin,
                           close_fds=True, env=env,
                           cwd=cwd)

  out = StringIO()
  err = StringIO()
  if not interactive:
    child.stdin.close()
    poller.register(child.stdout, select.POLLIN)
    poller.register(child.stderr, select.POLLIN)
    fdmap = {
      child.stdout.fileno(): (out, child.stdout),
      child.stderr.fileno(): (err, child.stderr),
      }
    for fd in fdmap:
      SetNonblockFlag(fd, True)

    while fdmap:
      pollresult = RetryOnSignal(poller.poll)

      for fd, event in pollresult:
        if event & select.POLLIN or event & select.POLLPRI:
          data = fdmap[fd][1].read()
          # no data from read signifies EOF (the same as POLLHUP)
          if not data:
            poller.unregister(fd)
            del fdmap[fd]
            continue
          fdmap[fd][0].write(data)
        if (event & select.POLLNVAL or event & select.POLLHUP or
            event & select.POLLERR):
          poller.unregister(fd)
          del fdmap[fd]

  out = out.getvalue()
  err = err.getvalue()

  status = child.wait()
  return out, err, status


def _RunCmdFile(cmd, env, via_shell, output, cwd):
  """Run a command and save its output to a file.

  @type  cmd: string or list
  @param cmd: Command to run
  @type env: dict
  @param env: The environment to use
  @type via_shell: bool
  @param via_shell: if we should run via the shell
  @type output: str
  @param output: the filename in which to save the output
  @type cwd: string
  @param cwd: the working directory for the program
  @rtype: int
  @return: the exit status

  """
  fh = open(output, "a")
  try:
    child = subprocess.Popen(cmd, shell=via_shell,
                             stderr=subprocess.STDOUT,
                             stdout=fh,
                             stdin=subprocess.PIPE,
                             close_fds=True, env=env,
                             cwd=cwd)

    child.stdin.close()
    status = child.wait()
  finally:
    fh.close()
  return status


def SetCloseOnExecFlag(fd, enable):
  """Sets or unsets the close-on-exec flag on a file descriptor.

  @type fd: int
  @param fd: File descriptor
  @type enable: bool
  @param enable: Whether to set or unset it.

  """
  flags = fcntl.fcntl(fd, fcntl.F_GETFD)

  if enable:
    flags |= fcntl.FD_CLOEXEC
  else:
    flags &= ~fcntl.FD_CLOEXEC

  fcntl.fcntl(fd, fcntl.F_SETFD, flags)


def SetNonblockFlag(fd, enable):
  """Sets or unsets the O_NONBLOCK flag on on a file descriptor.

  @type fd: int
  @param fd: File descriptor
  @type enable: bool
  @param enable: Whether to set or unset it

  """
  flags = fcntl.fcntl(fd, fcntl.F_GETFL)

  if enable:
    flags |= os.O_NONBLOCK
  else:
    flags &= ~os.O_NONBLOCK

  fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def RetryOnSignal(fn, *args, **kwargs):
  """Calls a function again if it failed due to EINTR.

  """
  while True:
    try:
      return fn(*args, **kwargs)
    except EnvironmentError, err:
      if err.errno != errno.EINTR:
        raise
    except (socket.error, select.error), err:
      # In python 2.6 and above select.error is an IOError, so it's handled
      # above, in 2.5 and below it's not, and it's handled here.
      if not (err.args and err.args[0] == errno.EINTR):
        raise


def RunParts(dir_name, env=None, reset_env=False):
  """Run Scripts or programs in a directory

  @type dir_name: string
  @param dir_name: absolute path to a directory
  @type env: dict
  @param env: The environment to use
  @type reset_env: boolean
  @param reset_env: whether to reset or keep the default os environment
  @rtype: list of tuples
  @return: list of (name, (one of RUNDIR_STATUS), RunResult)

  """
  rr = []

  try:
    dir_contents = ListVisibleFiles(dir_name)
  except OSError, err:
    logging.warning("RunParts: skipping %s (cannot list: %s)", dir_name, err)
    return rr

  for relname in sorted(dir_contents):
    fname = PathJoin(dir_name, relname)
    if not (os.path.isfile(fname) and os.access(fname, os.X_OK) and
            constants.EXT_PLUGIN_MASK.match(relname) is not None):
      rr.append((relname, constants.RUNPARTS_SKIP, None))
    else:
      try:
        result = RunCmd([fname], env=env, reset_env=reset_env)
      except Exception, err: # pylint: disable-msg=W0703
        rr.append((relname, constants.RUNPARTS_ERR, str(err)))
      else:
        rr.append((relname, constants.RUNPARTS_RUN, result))

  return rr


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


def RenameFile(old, new, mkdir=False, mkdir_mode=0750):
  """Renames a file.

  @type old: string
  @param old: Original path
  @type new: string
  @param new: New path
  @type mkdir: bool
  @param mkdir: Whether to create target directory if it doesn't exist
  @type mkdir_mode: int
  @param mkdir_mode: Mode for newly created directories

  """
  try:
    return os.rename(old, new)
  except OSError, err:
    # In at least one use case of this function, the job queue, directory
    # creation is very rare. Checking for the directory before renaming is not
    # as efficient.
    if mkdir and err.errno == errno.ENOENT:
      # Create directory and try again
      Makedirs(os.path.dirname(new), mode=mkdir_mode)

      return os.rename(old, new)

    raise


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


def ResetTempfileModule():
  """Resets the random name generator of the tempfile module.

  This function should be called after C{os.fork} in the child process to
  ensure it creates a newly seeded random generator. Otherwise it would
  generate the same random parts as the parent process. If several processes
  race for the creation of a temporary file, this could lead to one not getting
  a temporary name.

  """
  # pylint: disable-msg=W0212
  if hasattr(tempfile, "_once_lock") and hasattr(tempfile, "_name_sequence"):
    tempfile._once_lock.acquire()
    try:
      # Reset random name generator
      tempfile._name_sequence = None
    finally:
      tempfile._once_lock.release()
  else:
    logging.critical("The tempfile module misses at least one of the"
                     " '_once_lock' and '_name_sequence' attributes")


def _FingerprintFile(filename):
  """Compute the fingerprint of a file.

  If the file does not exist, a None will be returned
  instead.

  @type filename: str
  @param filename: the filename to checksum
  @rtype: str
  @return: the hex digest of the sha checksum of the contents
      of the file

  """
  if not (os.path.exists(filename) and os.path.isfile(filename)):
    return None

  f = open(filename)

  fp = compat.sha1_hash()
  while True:
    data = f.read(4096)
    if not data:
      break

    fp.update(data)

  return fp.hexdigest()


def FingerprintFiles(files):
  """Compute fingerprints for a list of files.

  @type files: list
  @param files: the list of filename to fingerprint
  @rtype: dict
  @return: a dictionary filename: fingerprint, holding only
      existing files

  """
  ret = {}

  for filename in files:
    cksum = _FingerprintFile(filename)
    if cksum:
      ret[filename] = cksum

  return ret


def ForceDictType(target, key_types, allowed_values=None):
  """Force the values of a dict to have certain types.

  @type target: dict
  @param target: the dict to update
  @type key_types: dict
  @param key_types: dict mapping target dict keys to types
                    in constants.ENFORCEABLE_TYPES
  @type allowed_values: list
  @keyword allowed_values: list of specially allowed values

  """
  if allowed_values is None:
    allowed_values = []

  if not isinstance(target, dict):
    msg = "Expected dictionary, got '%s'" % target
    raise errors.TypeEnforcementError(msg)

  for key in target:
    if key not in key_types:
      msg = "Unknown key '%s'" % key
      raise errors.TypeEnforcementError(msg)

    if target[key] in allowed_values:
      continue

    ktype = key_types[key]
    if ktype not in constants.ENFORCEABLE_TYPES:
      msg = "'%s' has non-enforceable type %s" % (key, ktype)
      raise errors.ProgrammerError(msg)

    if ktype in (constants.VTYPE_STRING, constants.VTYPE_MAYBE_STRING):
      if target[key] is None and ktype == constants.VTYPE_MAYBE_STRING:
        pass
      elif not isinstance(target[key], basestring):
        if isinstance(target[key], bool) and not target[key]:
          target[key] = ''
        else:
          msg = "'%s' (value %s) is not a valid string" % (key, target[key])
          raise errors.TypeEnforcementError(msg)
    elif ktype == constants.VTYPE_BOOL:
      if isinstance(target[key], basestring) and target[key]:
        if target[key].lower() == constants.VALUE_FALSE:
          target[key] = False
        elif target[key].lower() == constants.VALUE_TRUE:
          target[key] = True
        else:
          msg = "'%s' (value %s) is not a valid boolean" % (key, target[key])
          raise errors.TypeEnforcementError(msg)
      elif target[key]:
        target[key] = True
      else:
        target[key] = False
    elif ktype == constants.VTYPE_SIZE:
      try:
        target[key] = ParseUnit(target[key])
      except errors.UnitParseError, err:
        msg = "'%s' (value %s) is not a valid size. error: %s" % \
              (key, target[key], err)
        raise errors.TypeEnforcementError(msg)
    elif ktype == constants.VTYPE_INT:
      try:
        target[key] = int(target[key])
      except (ValueError, TypeError):
        msg = "'%s' (value %s) is not a valid integer" % (key, target[key])
        raise errors.TypeEnforcementError(msg)


def _GetProcStatusPath(pid):
  """Returns the path for a PID's proc status file.

  @type pid: int
  @param pid: Process ID
  @rtype: string

  """
  return "/proc/%d/status" % pid


def IsProcessAlive(pid):
  """Check if a given pid exists on the system.

  @note: zombie status is not handled, so zombie processes
      will be returned as alive
  @type pid: int
  @param pid: the process ID to check
  @rtype: boolean
  @return: True if the process exists

  """
  def _TryStat(name):
    try:
      os.stat(name)
      return True
    except EnvironmentError, err:
      if err.errno in (errno.ENOENT, errno.ENOTDIR):
        return False
      elif err.errno == errno.EINVAL:
        raise RetryAgain(err)
      raise

  assert isinstance(pid, int), "pid must be an integer"
  if pid <= 0:
    return False

  # /proc in a multiprocessor environment can have strange behaviors.
  # Retry the os.stat a few times until we get a good result.
  try:
    return Retry(_TryStat, (0.01, 1.5, 0.1), 0.5,
                 args=[_GetProcStatusPath(pid)])
  except RetryTimeout, err:
    err.RaiseInner()


def _ParseSigsetT(sigset):
  """Parse a rendered sigset_t value.

  This is the opposite of the Linux kernel's fs/proc/array.c:render_sigset_t
  function.

  @type sigset: string
  @param sigset: Rendered signal set from /proc/$pid/status
  @rtype: set
  @return: Set of all enabled signal numbers

  """
  result = set()

  signum = 0
  for ch in reversed(sigset):
    chv = int(ch, 16)

    # The following could be done in a loop, but it's easier to read and
    # understand in the unrolled form
    if chv & 1:
      result.add(signum + 1)
    if chv & 2:
      result.add(signum + 2)
    if chv & 4:
      result.add(signum + 3)
    if chv & 8:
      result.add(signum + 4)

    signum += 4

  return result


def _GetProcStatusField(pstatus, field):
  """Retrieves a field from the contents of a proc status file.

  @type pstatus: string
  @param pstatus: Contents of /proc/$pid/status
  @type field: string
  @param field: Name of field whose value should be returned
  @rtype: string

  """
  for line in pstatus.splitlines():
    parts = line.split(":", 1)

    if len(parts) < 2 or parts[0] != field:
      continue

    return parts[1].strip()

  return None


def IsProcessHandlingSignal(pid, signum, status_path=None):
  """Checks whether a process is handling a signal.

  @type pid: int
  @param pid: Process ID
  @type signum: int
  @param signum: Signal number
  @rtype: bool

  """
  if status_path is None:
    status_path = _GetProcStatusPath(pid)

  try:
    proc_status = ReadFile(status_path)
  except EnvironmentError, err:
    # In at least one case, reading /proc/$pid/status failed with ESRCH.
    if err.errno in (errno.ENOENT, errno.ENOTDIR, errno.EINVAL, errno.ESRCH):
      return False
    raise

  sigcgt = _GetProcStatusField(proc_status, "SigCgt")
  if sigcgt is None:
    raise RuntimeError("%s is missing 'SigCgt' field" % status_path)

  # Now check whether signal is handled
  return signum in _ParseSigsetT(sigcgt)


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

  try:
    pid = int(raw_data)
  except (TypeError, ValueError), err:
    logging.info("Can't parse pid file contents", exc_info=True)
    return 0

  return pid


def ReadLockedPidFile(path):
  """Reads a locked PID file.

  This can be used together with L{StartDaemon}.

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
      LockFile(fd)
    except errors.LockError:
      # Couldn't lock, daemon is running
      return int(os.read(fd, 100))
  finally:
    os.close(fd)

  return None


def MatchNameComponent(key, name_list, case_sensitive=True):
  """Try to match a name against a list.

  This function will try to match a name like test1 against a list
  like C{['test1.example.com', 'test2.example.com', ...]}. Against
  this list, I{'test1'} as well as I{'test1.example'} will match, but
  not I{'test1.ex'}. A multiple match will be considered as no match
  at all (e.g. I{'test1'} against C{['test1.example.com',
  'test1.example.org']}), except when the key fully matches an entry
  (e.g. I{'test1'} against C{['test1', 'test1.example.com']}).

  @type key: str
  @param key: the name to be searched
  @type name_list: list
  @param name_list: the list of strings against which to search the key
  @type case_sensitive: boolean
  @param case_sensitive: whether to provide a case-sensitive match

  @rtype: None or str
  @return: None if there is no match I{or} if there are multiple matches,
      otherwise the element from the list which matches

  """
  if key in name_list:
    return key

  re_flags = 0
  if not case_sensitive:
    re_flags |= re.IGNORECASE
    key = key.upper()
  mo = re.compile("^%s(\..*)?$" % re.escape(key), re_flags)
  names_filtered = []
  string_matches = []
  for name in name_list:
    if mo.match(name) is not None:
      names_filtered.append(name)
      if not case_sensitive and key == name.upper():
        string_matches.append(name)

  if len(string_matches) == 1:
    return string_matches[0]
  if len(names_filtered) == 1:
    return names_filtered[0]
  return None


def ValidateServiceName(name):
  """Validate the given service name.

  @type name: number or string
  @param name: Service name or port specification

  """
  try:
    numport = int(name)
  except (ValueError, TypeError):
    # Non-numeric service name
    valid = _VALID_SERVICE_NAME_RE.match(name)
  else:
    # Numeric port (protocols other than TCP or UDP might need adjustments
    # here)
    valid = (numport >= 0 and numport < (1 << 16))

  if not valid:
    raise errors.OpPrereqError("Invalid service name '%s'" % name,
                               errors.ECODE_INVAL)

  return name


def ListVolumeGroups():
  """List volume groups and their size

  @rtype: dict
  @return:
       Dictionary with keys volume name and values
       the size of the volume

  """
  command = "vgs --noheadings --units m --nosuffix -o name,size"
  result = RunCmd(command)
  retval = {}
  if result.failed:
    return retval

  for line in result.stdout.splitlines():
    try:
      name, size = line.split()
      size = int(float(size))
    except (IndexError, ValueError), err:
      logging.error("Invalid output from vgs (%s): %s", err, line)
      continue

    retval[name] = size

  return retval


def BridgeExists(bridge):
  """Check whether the given bridge exists in the system

  @type bridge: str
  @param bridge: the bridge name to check
  @rtype: boolean
  @return: True if it does

  """
  return os.path.isdir("/sys/class/net/%s/bridge" % bridge)


def NiceSort(name_list):
  """Sort a list of strings based on digit and non-digit groupings.

  Given a list of names C{['a1', 'a10', 'a11', 'a2']} this function
  will sort the list in the logical order C{['a1', 'a2', 'a10',
  'a11']}.

  The sort algorithm breaks each name in groups of either only-digits
  or no-digits. Only the first eight such groups are considered, and
  after that we just use what's left of the string.

  @type name_list: list
  @param name_list: the names to be sorted
  @rtype: list
  @return: a copy of the name list sorted with our algorithm

  """
  _SORTER_BASE = "(\D+|\d+)"
  _SORTER_FULL = "^%s%s?%s?%s?%s?%s?%s?%s?.*$" % (_SORTER_BASE, _SORTER_BASE,
                                                  _SORTER_BASE, _SORTER_BASE,
                                                  _SORTER_BASE, _SORTER_BASE,
                                                  _SORTER_BASE, _SORTER_BASE)
  _SORTER_RE = re.compile(_SORTER_FULL)
  _SORTER_NODIGIT = re.compile("^\D*$")
  def _TryInt(val):
    """Attempts to convert a variable to integer."""
    if val is None or _SORTER_NODIGIT.match(val):
      return val
    rval = int(val)
    return rval

  to_sort = [([_TryInt(grp) for grp in _SORTER_RE.match(name).groups()], name)
             for name in name_list]
  to_sort.sort()
  return [tup[1] for tup in to_sort]


def TryConvert(fn, val):
  """Try to convert a value ignoring errors.

  This function tries to apply function I{fn} to I{val}. If no
  C{ValueError} or C{TypeError} exceptions are raised, it will return
  the result, else it will return the original value. Any other
  exceptions are propagated to the caller.

  @type fn: callable
  @param fn: function to apply to the value
  @param val: the value to be converted
  @return: The converted value if the conversion was successful,
      otherwise the original value.

  """
  try:
    nv = fn(val)
  except (ValueError, TypeError):
    nv = val
  return nv


def IsValidShellParam(word):
  """Verifies is the given word is safe from the shell's p.o.v.

  This means that we can pass this to a command via the shell and be
  sure that it doesn't alter the command line and is passed as such to
  the actual command.

  Note that we are overly restrictive here, in order to be on the safe
  side.

  @type word: str
  @param word: the word to check
  @rtype: boolean
  @return: True if the word is 'safe'

  """
  return bool(re.match("^[-a-zA-Z0-9._+/:%@]+$", word))


def BuildShellCmd(template, *args):
  """Build a safe shell command line from the given arguments.

  This function will check all arguments in the args list so that they
  are valid shell parameters (i.e. they don't contain shell
  metacharacters). If everything is ok, it will return the result of
  template % args.

  @type template: str
  @param template: the string holding the template for the
      string formatting
  @rtype: str
  @return: the expanded command line

  """
  for word in args:
    if not IsValidShellParam(word):
      raise errors.ProgrammerError("Shell argument '%s' contains"
                                   " invalid characters" % word)
  return template % args


def FormatUnit(value, units):
  """Formats an incoming number of MiB with the appropriate unit.

  @type value: int
  @param value: integer representing the value in MiB (1048576)
  @type units: char
  @param units: the type of formatting we should do:
      - 'h' for automatic scaling
      - 'm' for MiBs
      - 'g' for GiBs
      - 't' for TiBs
  @rtype: str
  @return: the formatted value (with suffix)

  """
  if units not in ('m', 'g', 't', 'h'):
    raise errors.ProgrammerError("Invalid unit specified '%s'" % str(units))

  suffix = ''

  if units == 'm' or (units == 'h' and value < 1024):
    if units == 'h':
      suffix = 'M'
    return "%d%s" % (round(value, 0), suffix)

  elif units == 'g' or (units == 'h' and value < (1024 * 1024)):
    if units == 'h':
      suffix = 'G'
    return "%0.1f%s" % (round(float(value) / 1024, 1), suffix)

  else:
    if units == 'h':
      suffix = 'T'
    return "%0.1f%s" % (round(float(value) / 1024 / 1024, 1), suffix)


def ParseUnit(input_string):
  """Tries to extract number and scale from the given string.

  Input must be in the format C{NUMBER+ [DOT NUMBER+] SPACE*
  [UNIT]}. If no unit is specified, it defaults to MiB. Return value
  is always an int in MiB.

  """
  m = re.match('^([.\d]+)\s*([a-zA-Z]+)?$', str(input_string))
  if not m:
    raise errors.UnitParseError("Invalid format")

  value = float(m.groups()[0])

  unit = m.groups()[1]
  if unit:
    lcunit = unit.lower()
  else:
    lcunit = 'm'

  if lcunit in ('m', 'mb', 'mib'):
    # Value already in MiB
    pass

  elif lcunit in ('g', 'gb', 'gib'):
    value *= 1024

  elif lcunit in ('t', 'tb', 'tib'):
    value *= 1024 * 1024

  else:
    raise errors.UnitParseError("Unknown unit: %s" % unit)

  # Make sure we round up
  if int(value) < value:
    value += 1

  # Round up to the next multiple of 4
  value = int(value)
  if value % 4:
    value += 4 - value % 4

  return value


def ParseCpuMask(cpu_mask):
  """Parse a CPU mask definition and return the list of CPU IDs.

  CPU mask format: comma-separated list of CPU IDs
  or dash-separated ID ranges
  Example: "0-2,5" -> "0,1,2,5"

  @type cpu_mask: str
  @param cpu_mask: CPU mask definition
  @rtype: list of int
  @return: list of CPU IDs

  """
  if not cpu_mask:
    return []
  cpu_list = []
  for range_def in cpu_mask.split(","):
    boundaries = range_def.split("-")
    n_elements = len(boundaries)
    if n_elements > 2:
      raise errors.ParseError("Invalid CPU ID range definition"
                              " (only one hyphen allowed): %s" % range_def)
    try:
      lower = int(boundaries[0])
    except (ValueError, TypeError), err:
      raise errors.ParseError("Invalid CPU ID value for lower boundary of"
                              " CPU ID range: %s" % str(err))
    try:
      higher = int(boundaries[-1])
    except (ValueError, TypeError), err:
      raise errors.ParseError("Invalid CPU ID value for higher boundary of"
                              " CPU ID range: %s" % str(err))
    if lower > higher:
      raise errors.ParseError("Invalid CPU ID range definition"
                              " (%d > %d): %s" % (lower, higher, range_def))
    cpu_list.extend(range(lower, higher + 1))
  return cpu_list


def AddAuthorizedKey(file_obj, key):
  """Adds an SSH public key to an authorized_keys file.

  @type file_obj: str or file handle
  @param file_obj: path to authorized_keys file
  @type key: str
  @param key: string containing key

  """
  key_fields = key.split()

  if isinstance(file_obj, basestring):
    f = open(file_obj, 'a+')
  else:
    f = file_obj

  try:
    nl = True
    for line in f:
      # Ignore whitespace changes
      if line.split() == key_fields:
        break
      nl = line.endswith('\n')
    else:
      if not nl:
        f.write("\n")
      f.write(key.rstrip('\r\n'))
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
  key_fields = key.split()

  fd, tmpname = tempfile.mkstemp(dir=os.path.dirname(file_name))
  try:
    out = os.fdopen(fd, 'w')
    try:
      f = open(file_name, 'r')
      try:
        for line in f:
          # Ignore whitespace changes while comparing lines
          if line.split() != key_fields:
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


def SetEtcHostsEntry(file_name, ip, hostname, aliases):
  """Sets the name of an IP address and hostname in /etc/hosts.

  @type file_name: str
  @param file_name: path to the file to modify (usually C{/etc/hosts})
  @type ip: str
  @param ip: the IP address
  @type hostname: str
  @param hostname: the hostname to be added
  @type aliases: list
  @param aliases: the list of aliases to add for the hostname

  """
  # Ensure aliases are unique
  aliases = UniqueSequence([hostname] + aliases)[1:]

  def _WriteEtcHosts(fd):
    # Duplicating file descriptor because os.fdopen's result will automatically
    # close the descriptor, but we would still like to have its functionality.
    out = os.fdopen(os.dup(fd), "w")
    try:
      for line in ReadFile(file_name).splitlines(True):
        fields = line.split()
        if fields and not fields[0].startswith("#") and ip == fields[0]:
          continue
        out.write(line)

      out.write("%s\t%s" % (ip, hostname))
      if aliases:
        out.write(" %s" % " ".join(aliases))
      out.write("\n")
      out.flush()
    finally:
      out.close()

  WriteFile(file_name, fn=_WriteEtcHosts, mode=0644)


def AddHostToEtcHosts(hostname, ip):
  """Wrapper around SetEtcHostsEntry.

  @type hostname: str
  @param hostname: a hostname that will be resolved and added to
      L{constants.ETC_HOSTS}
  @type ip: str
  @param ip: The ip address of the host

  """
  SetEtcHostsEntry(constants.ETC_HOSTS, ip, hostname, [hostname.split(".")[0]])


def RemoveEtcHostsEntry(file_name, hostname):
  """Removes a hostname from /etc/hosts.

  IP addresses without names are removed from the file.

  @type file_name: str
  @param file_name: path to the file to modify (usually C{/etc/hosts})
  @type hostname: str
  @param hostname: the hostname to be removed

  """
  def _WriteEtcHosts(fd):
    # Duplicating file descriptor because os.fdopen's result will automatically
    # close the descriptor, but we would still like to have its functionality.
    out = os.fdopen(os.dup(fd), "w")
    try:
      for line in ReadFile(file_name).splitlines(True):
        fields = line.split()
        if len(fields) > 1 and not fields[0].startswith("#"):
          names = fields[1:]
          if hostname in names:
            while hostname in names:
              names.remove(hostname)
            if names:
              out.write("%s %s\n" % (fields[0], " ".join(names)))
            continue

        out.write(line)

      out.flush()
    finally:
      out.close()

  WriteFile(file_name, fn=_WriteEtcHosts, mode=0644)


def RemoveHostFromEtcHosts(hostname):
  """Wrapper around RemoveEtcHostsEntry.

  @type hostname: str
  @param hostname: hostname that will be resolved and its
      full and shot name will be removed from
      L{constants.ETC_HOSTS}

  """
  RemoveEtcHostsEntry(constants.ETC_HOSTS, hostname)
  RemoveEtcHostsEntry(constants.ETC_HOSTS, hostname.split(".")[0])


def TimestampForFilename():
  """Returns the current time formatted for filenames.

  The format doesn't contain colons as some shells and applications them as
  separators.

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

  fsrc = open(file_name, 'rb')
  try:
    (fd, backup_name) = tempfile.mkstemp(prefix=prefix, dir=dir_name)
    fdst = os.fdopen(fd, 'wb')
    try:
      logging.debug("Backing up %s at %s", file_name, backup_name)
      shutil.copyfileobj(fsrc, fdst)
    finally:
      fdst.close()
  finally:
    fsrc.close()

  return backup_name


def ShellQuote(value):
  """Quotes shell argument according to POSIX.

  @type value: str
  @param value: the argument to be quoted
  @rtype: str
  @return: the quoted value

  """
  if _re_shell_unquoted.match(value):
    return value
  else:
    return "'%s'" % value.replace("'", "'\\''")


def ShellQuoteArgs(args):
  """Quotes a list of shell arguments.

  @type args: list
  @param args: list of arguments to be quoted
  @rtype: str
  @return: the quoted arguments concatenated with spaces

  """
  return ' '.join([ShellQuote(i) for i in args])


class ShellWriter:
  """Helper class to write scripts with indentation.

  """
  INDENT_STR = "  "

  def __init__(self, fh):
    """Initializes this class.

    """
    self._fh = fh
    self._indent = 0

  def IncIndent(self):
    """Increase indentation level by 1.

    """
    self._indent += 1

  def DecIndent(self):
    """Decrease indentation level by 1.

    """
    assert self._indent > 0
    self._indent -= 1

  def Write(self, txt, *args):
    """Write line to output file.

    """
    assert self._indent >= 0

    self._fh.write(self._indent * self.INDENT_STR)

    if args:
      self._fh.write(txt % args)
    else:
      self._fh.write(txt)

    self._fh.write("\n")


def ListVisibleFiles(path):
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
  files = [i for i in os.listdir(path) if not i.startswith(".")]
  return files


def GetHomeDir(user, default=None):
  """Try to get the homedir of the given user.

  The user can be passed either as a string (denoting the name) or as
  an integer (denoting the user id). If the user is not found, the
  'default' argument is returned, which defaults to None.

  """
  try:
    if isinstance(user, basestring):
      result = pwd.getpwnam(user)
    elif isinstance(user, (int, long)):
      result = pwd.getpwuid(user)
    else:
      raise errors.ProgrammerError("Invalid type passed to GetHomeDir (%s)" %
                                   type(user))
  except KeyError:
    return default
  return result.pw_dir


def NewUUID():
  """Returns a random UUID.

  @note: This is a Linux-specific method as it uses the /proc
      filesystem.
  @rtype: str

  """
  return ReadFile(_RANDOM_UUID_FILE, size=128).rstrip("\n")


def GenerateSecret(numbytes=20):
  """Generates a random secret.

  This will generate a pseudo-random secret returning an hex string
  (so that it can be used where an ASCII string is needed).

  @param numbytes: the number of bytes which will be represented by the returned
      string (defaulting to 20, the length of a SHA1 hash)
  @rtype: str
  @return: an hex representation of the pseudo-random sequence

  """
  return os.urandom(numbytes).encode('hex')


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


def ReadFile(file_name, size=-1):
  """Reads a file.

  @type size: int
  @param size: Read at most size bytes (if negative, entire file)
  @rtype: str
  @return: the (possibly partial) content of the file

  """
  f = open(file_name, "r")
  try:
    return f.read(size)
  finally:
    f.close()


def WriteFile(file_name, fn=None, data=None,
              mode=None, uid=-1, gid=-1,
              atime=None, mtime=None, close=True,
              dry_run=False, backup=False,
              prewrite=None, postwrite=None):
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

  if backup and not dry_run and os.path.isfile(file_name):
    CreateBackup(file_name)

  dir_name, base_name = os.path.split(file_name)
  fd, new_name = tempfile.mkstemp('.new', base_name, dir_name)
  do_remove = True
  # here we need to make sure we remove the temp file, if any error
  # leaves it in place
  try:
    if uid != -1 or gid != -1:
      os.chown(new_name, uid, gid)
    if mode:
      os.chmod(new_name, mode)
    if callable(prewrite):
      prewrite(fd)
    if data is not None:
      os.write(fd, data)
    else:
      fn(fd)
    if callable(postwrite):
      postwrite(fd)
    os.fsync(fd)
    if atime is not None and mtime is not None:
      os.utime(new_name, (atime, mtime))
    if not dry_run:
      os.rename(new_name, file_name)
      do_remove = False
  finally:
    if close:
      os.close(fd)
      result = None
    else:
      result = fd
    if do_remove:
      RemoveFile(new_name)

  return result


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


def FirstFree(seq, base=0):
  """Returns the first non-existing integer from seq.

  The seq argument should be a sorted list of positive integers. The
  first time the index of an element is smaller than the element
  value, the index will be returned.

  The base argument is used to start at a different offset,
  i.e. C{[3, 4, 6]} with I{offset=3} will return 5.

  Example: C{[0, 1, 3]} will return I{2}.

  @type seq: sequence
  @param seq: the sequence to be analyzed.
  @type base: int
  @param base: use this value as the base index of the sequence
  @rtype: int
  @return: the first non-used index in the sequence

  """
  for idx, elem in enumerate(seq):
    assert elem >= base, "Passed element is higher than base offset"
    if elem > idx + base:
      # idx is not used
      return idx + base
  return None


def SingleWaitForFdCondition(fdobj, event, timeout):
  """Waits for a condition to occur on the socket.

  Immediately returns at the first interruption.

  @type fdobj: integer or object supporting a fileno() method
  @param fdobj: entity to wait for events on
  @type event: integer
  @param event: ORed condition (see select module)
  @type timeout: float or None
  @param timeout: Timeout in seconds
  @rtype: int or None
  @return: None for timeout, otherwise occured conditions

  """
  check = (event | select.POLLPRI |
           select.POLLNVAL | select.POLLHUP | select.POLLERR)

  if timeout is not None:
    # Poller object expects milliseconds
    timeout *= 1000

  poller = select.poll()
  poller.register(fdobj, event)
  try:
    # TODO: If the main thread receives a signal and we have no timeout, we
    # could wait forever. This should check a global "quit" flag or something
    # every so often.
    io_events = poller.poll(timeout)
  except select.error, err:
    if err[0] != errno.EINTR:
      raise
    io_events = []
  if io_events and io_events[0][1] & check:
    return io_events[0][1]
  else:
    return None


class FdConditionWaiterHelper(object):
  """Retry helper for WaitForFdCondition.

  This class contains the retried and wait functions that make sure
  WaitForFdCondition can continue waiting until the timeout is actually
  expired.

  """

  def __init__(self, timeout):
    self.timeout = timeout

  def Poll(self, fdobj, event):
    result = SingleWaitForFdCondition(fdobj, event, self.timeout)
    if result is None:
      raise RetryAgain()
    else:
      return result

  def UpdateTimeout(self, timeout):
    self.timeout = timeout


def WaitForFdCondition(fdobj, event, timeout):
  """Waits for a condition to occur on the socket.

  Retries until the timeout is expired, even if interrupted.

  @type fdobj: integer or object supporting a fileno() method
  @param fdobj: entity to wait for events on
  @type event: integer
  @param event: ORed condition (see select module)
  @type timeout: float or None
  @param timeout: Timeout in seconds
  @rtype: int or None
  @return: None for timeout, otherwise occured conditions

  """
  if timeout is not None:
    retrywaiter = FdConditionWaiterHelper(timeout)
    try:
      result = Retry(retrywaiter.Poll, RETRY_REMAINING_TIME, timeout,
                     args=(fdobj, event), wait_fn=retrywaiter.UpdateTimeout)
    except RetryTimeout:
      result = None
  else:
    result = None
    while result is None:
      result = SingleWaitForFdCondition(fdobj, event, timeout)
  return result


def UniqueSequence(seq):
  """Returns a list with unique elements.

  Element order is preserved.

  @type seq: sequence
  @param seq: the sequence with the source elements
  @rtype: list
  @return: list of unique elements from seq

  """
  seen = set()
  return [i for i in seq if i not in seen and not seen.add(i)]


def NormalizeAndValidateMac(mac):
  """Normalizes and check if a MAC address is valid.

  Checks whether the supplied MAC address is formally correct, only
  accepts colon separated format. Normalize it to all lower.

  @type mac: str
  @param mac: the MAC to be validated
  @rtype: str
  @return: returns the normalized and validated MAC.

  @raise errors.OpPrereqError: If the MAC isn't valid

  """
  if not _MAC_CHECK.match(mac):
    raise errors.OpPrereqError("Invalid MAC address specified: %s" %
                               mac, errors.ECODE_INVAL)

  return mac.lower()


def TestDelay(duration):
  """Sleep for a fixed amount of time.

  @type duration: float
  @param duration: the sleep duration
  @rtype: boolean
  @return: False for negative value, True otherwise

  """
  if duration < 0:
    return False, "Invalid sleep duration"
  time.sleep(duration)
  return True, None


def _CloseFDNoErr(fd, retries=5):
  """Close a file descriptor ignoring errors.

  @type fd: int
  @param fd: the file descriptor
  @type retries: int
  @param retries: how many retries to make, in case we get any
      other error than EBADF

  """
  try:
    os.close(fd)
  except OSError, err:
    if err.errno != errno.EBADF:
      if retries > 0:
        _CloseFDNoErr(fd, retries - 1)
    # else either it's closed already or we're out of retries, so we
    # ignore this and go on


def CloseFDs(noclose_fds=None):
  """Close file descriptors.

  This closes all file descriptors above 2 (i.e. except
  stdin/out/err).

  @type noclose_fds: list or None
  @param noclose_fds: if given, it denotes a list of file descriptor
      that should not be closed

  """
  # Default maximum for the number of available file descriptors.
  if 'SC_OPEN_MAX' in os.sysconf_names:
    try:
      MAXFD = os.sysconf('SC_OPEN_MAX')
      if MAXFD < 0:
        MAXFD = 1024
    except OSError:
      MAXFD = 1024
  else:
    MAXFD = 1024
  maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
  if (maxfd == resource.RLIM_INFINITY):
    maxfd = MAXFD

  # Iterate through and close all file descriptors (except the standard ones)
  for fd in range(3, maxfd):
    if noclose_fds and fd in noclose_fds:
      continue
    _CloseFDNoErr(fd)


def Mlockall(_ctypes=ctypes):
  """Lock current process' virtual address space into RAM.

  This is equivalent to the C call mlockall(MCL_CURRENT|MCL_FUTURE),
  see mlock(2) for more details. This function requires ctypes module.

  @raises errors.NoCtypesError: if ctypes module is not found

  """
  if _ctypes is None:
    raise errors.NoCtypesError()

  libc = _ctypes.cdll.LoadLibrary("libc.so.6")
  if libc is None:
    logging.error("Cannot set memory lock, ctypes cannot load libc")
    return

  # Some older version of the ctypes module don't have built-in functionality
  # to access the errno global variable, where function error codes are stored.
  # By declaring this variable as a pointer to an integer we can then access
  # its value correctly, should the mlockall call fail, in order to see what
  # the actual error code was.
  # pylint: disable-msg=W0212
  libc.__errno_location.restype = _ctypes.POINTER(_ctypes.c_int)

  if libc.mlockall(_MCL_CURRENT | _MCL_FUTURE):
    # pylint: disable-msg=W0212
    logging.error("Cannot set memory lock: %s",
                  os.strerror(libc.__errno_location().contents.value))
    return

  logging.debug("Memory lock set")


def Daemonize(logfile):
  """Daemonize the current process.

  This detaches the current process from the controlling terminal and
  runs it in the background as a daemon.

  @type logfile: str
  @param logfile: the logfile to which we should redirect stdout/stderr
  @rtype: int
  @return: the value zero

  """
  # pylint: disable-msg=W0212
  # yes, we really want os._exit

  # this might fail
  pid = os.fork()
  if (pid == 0):  # The first child.
    SetupDaemonEnv()

    # this might fail
    pid = os.fork() # Fork a second child.
    if (pid == 0):  # The second child.
      pass # nothing special to do in the child
    else:
      # exit() or _exit()?  See below.
      os._exit(0) # Exit parent (the first child) of the second child.
  else:
    os._exit(0) # Exit parent of the first child.

  SetupDaemonFDs(logfile, None)
  return 0


def DaemonPidFileName(name):
  """Compute a ganeti pid file absolute path

  @type name: str
  @param name: the daemon name
  @rtype: str
  @return: the full path to the pidfile corresponding to the given
      daemon name

  """
  return PathJoin(constants.RUN_GANETI_DIR, "%s.pid" % name)


def EnsureDaemon(name):
  """Check for and start daemon if not alive.

  """
  result = RunCmd([constants.DAEMON_UTIL, "check-and-start", name])
  if result.failed:
    logging.error("Can't start daemon '%s', failure %s, output: %s",
                  name, result.fail_reason, result.output)
    return False

  return True


def StopDaemon(name):
  """Stop daemon

  """
  result = RunCmd([constants.DAEMON_UTIL, "stop", name])
  if result.failed:
    logging.error("Can't stop daemon '%s', failure %s, output: %s",
                  name, result.fail_reason, result.output)
    return False

  return True


def WritePidFile(pidfile):
  """Write the current process pidfile.

  The file will be written to L{constants.RUN_GANETI_DIR}I{/name.pid}

  @type name: str
  @param name: the daemon name to use
  @param pid: if passed, will be used instead of getpid()
  @raise errors.GenericError: if the pid file already exists and
      points to a live process

  """
  # We don't rename nor truncate the file to not drop locks under
  # existing processes
  fd_pidfile = os.open(pidfile, os.O_WRONLY | os.O_CREAT, 0600)

  # Lock the PID file (and fail if not possible to do so). Any code
  # wanting to send a signal to the daemon should try to lock the PID
  # file before reading it. If acquiring the lock succeeds, the daemon is
  # no longer running and the signal should not be sent.
  LockFile(fd_pidfile)

  os.write(fd_pidfile, "%d\n" % os.getpid())

  return fd_pidfile


def RemovePidFile(name):
  """Remove the current process pidfile.

  Any errors are ignored.

  @type name: str
  @param name: the daemon name used to derive the pidfile name

  """
  pidfilename = DaemonPidFileName(name)
  # TODO: we could check here that the file contains our pid
  try:
    RemoveFile(pidfilename)
  except: # pylint: disable-msg=W0702
    pass


def KillProcess(pid, signal_=signal.SIGTERM, timeout=30,
                waitpid=False):
  """Kill a process given by its pid.

  @type pid: int
  @param pid: The PID to terminate.
  @type signal_: int
  @param signal_: The signal to send, by default SIGTERM
  @type timeout: int
  @param timeout: The timeout after which, if the process is still alive,
                  a SIGKILL will be sent. If not positive, no such checking
                  will be done
  @type waitpid: boolean
  @param waitpid: If true, we should waitpid on this process after
      sending signals, since it's our own child and otherwise it
      would remain as zombie

  """
  def _helper(pid, signal_, wait):
    """Simple helper to encapsulate the kill/waitpid sequence"""
    if IgnoreProcessNotFound(os.kill, pid, signal_) and wait:
      try:
        os.waitpid(pid, os.WNOHANG)
      except OSError:
        pass

  if pid <= 0:
    # kill with pid=0 == suicide
    raise errors.ProgrammerError("Invalid pid given '%s'" % pid)

  if not IsProcessAlive(pid):
    return

  _helper(pid, signal_, waitpid)

  if timeout <= 0:
    return

  def _CheckProcess():
    if not IsProcessAlive(pid):
      return

    try:
      (result_pid, _) = os.waitpid(pid, os.WNOHANG)
    except OSError:
      raise RetryAgain()

    if result_pid > 0:
      return

    raise RetryAgain()

  try:
    # Wait up to $timeout seconds
    Retry(_CheckProcess, (0.01, 1.5, 0.1), timeout)
  except RetryTimeout:
    pass

  if IsProcessAlive(pid):
    # Kill process if it's still alive
    _helper(pid, signal.SIGKILL, waitpid)


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


def CheckVolumeGroupSize(vglist, vgname, minsize):
  """Checks if the volume group list is valid.

  The function will check if a given volume group is in the list of
  volume groups and has a minimum size.

  @type vglist: dict
  @param vglist: dictionary of volume group names and their size
  @type vgname: str
  @param vgname: the volume group we should check
  @type minsize: int
  @param minsize: the minimum size we accept
  @rtype: None or str
  @return: None for success, otherwise the error message

  """
  vgsize = vglist.get(vgname, None)
  if vgsize is None:
    return "volume group '%s' missing" % vgname
  elif vgsize < minsize:
    return ("volume group '%s' too small (%s MiB required, %d MiB found)" %
            (vgname, minsize, vgsize))
  return None


def SplitTime(value):
  """Splits time as floating point number into a tuple.

  @param value: Time in seconds
  @type value: int or float
  @return: Tuple containing (seconds, microseconds)

  """
  (seconds, microseconds) = divmod(int(value * 1000000), 1000000)

  assert 0 <= seconds, \
    "Seconds must be larger than or equal to 0, but are %s" % seconds
  assert 0 <= microseconds <= 999999, \
    "Microseconds must be 0-999999, but are %s" % microseconds

  return (int(seconds), int(microseconds))


def MergeTime(timetuple):
  """Merges a tuple into time as a floating point number.

  @param timetuple: Time as tuple, (seconds, microseconds)
  @type timetuple: tuple
  @return: Time as a floating point number expressed in seconds

  """
  (seconds, microseconds) = timetuple

  assert 0 <= seconds, \
    "Seconds must be larger than or equal to 0, but are %s" % seconds
  assert 0 <= microseconds <= 999999, \
    "Microseconds must be 0-999999, but are %s" % microseconds

  return float(seconds) + (float(microseconds) * 0.000001)


class LogFileHandler(logging.FileHandler):
  """Log handler that doesn't fallback to stderr.

  When an error occurs while writing on the logfile, logging.FileHandler tries
  to log on stderr. This doesn't work in ganeti since stderr is redirected to
  the logfile. This class avoids failures reporting errors to /dev/console.

  """
  def __init__(self, filename, mode="a", encoding=None):
    """Open the specified file and use it as the stream for logging.

    Also open /dev/console to report errors while logging.

    """
    logging.FileHandler.__init__(self, filename, mode, encoding)
    self.console = open(constants.DEV_CONSOLE, "a")

  def handleError(self, record): # pylint: disable-msg=C0103
    """Handle errors which occur during an emit() call.

    Try to handle errors with FileHandler method, if it fails write to
    /dev/console.

    """
    try:
      logging.FileHandler.handleError(self, record)
    except Exception: # pylint: disable-msg=W0703
      try:
        self.console.write("Cannot log message:\n%s\n" % self.format(record))
      except Exception: # pylint: disable-msg=W0703
        # Log handler tried everything it could, now just give up
        pass


def SetupLogging(logfile, debug=0, stderr_logging=False, program="",
                 multithreaded=False, syslog=constants.SYSLOG_USAGE,
                 console_logging=False):
  """Configures the logging module.

  @type logfile: str
  @param logfile: the filename to which we should log
  @type debug: integer
  @param debug: if greater than zero, enable debug messages, otherwise
      only those at C{INFO} and above level
  @type stderr_logging: boolean
  @param stderr_logging: whether we should also log to the standard error
  @type program: str
  @param program: the name under which we should log messages
  @type multithreaded: boolean
  @param multithreaded: if True, will add the thread name to the log file
  @type syslog: string
  @param syslog: one of 'no', 'yes', 'only':
      - if no, syslog is not used
      - if yes, syslog is used (in addition to file-logging)
      - if only, only syslog is used
  @type console_logging: boolean
  @param console_logging: if True, will use a FileHandler which falls back to
      the system console if logging fails
  @raise EnvironmentError: if we can't open the log file and
      syslog/stderr logging is disabled

  """
  fmt = "%(asctime)s: " + program + " pid=%(process)d"
  sft = program + "[%(process)d]:"
  if multithreaded:
    fmt += "/%(threadName)s"
    sft += " (%(threadName)s)"
  if debug:
    fmt += " %(module)s:%(lineno)s"
    # no debug info for syslog loggers
  fmt += " %(levelname)s %(message)s"
  # yes, we do want the textual level, as remote syslog will probably
  # lose the error level, and it's easier to grep for it
  sft += " %(levelname)s %(message)s"
  formatter = logging.Formatter(fmt)
  sys_fmt = logging.Formatter(sft)

  root_logger = logging.getLogger("")
  root_logger.setLevel(logging.NOTSET)

  # Remove all previously setup handlers
  for handler in root_logger.handlers:
    handler.close()
    root_logger.removeHandler(handler)

  if stderr_logging:
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    if debug:
      stderr_handler.setLevel(logging.NOTSET)
    else:
      stderr_handler.setLevel(logging.CRITICAL)
    root_logger.addHandler(stderr_handler)

  if syslog in (constants.SYSLOG_YES, constants.SYSLOG_ONLY):
    facility = logging.handlers.SysLogHandler.LOG_DAEMON
    syslog_handler = logging.handlers.SysLogHandler(constants.SYSLOG_SOCKET,
                                                    facility)
    syslog_handler.setFormatter(sys_fmt)
    # Never enable debug over syslog
    syslog_handler.setLevel(logging.INFO)
    root_logger.addHandler(syslog_handler)

  if syslog != constants.SYSLOG_ONLY:
    # this can fail, if the logging directories are not setup or we have
    # a permisssion problem; in this case, it's best to log but ignore
    # the error if stderr_logging is True, and if false we re-raise the
    # exception since otherwise we could run but without any logs at all
    try:
      if console_logging:
        logfile_handler = LogFileHandler(logfile)
      else:
        logfile_handler = logging.FileHandler(logfile)
      logfile_handler.setFormatter(formatter)
      if debug:
        logfile_handler.setLevel(logging.DEBUG)
      else:
        logfile_handler.setLevel(logging.INFO)
      root_logger.addHandler(logfile_handler)
    except EnvironmentError:
      if stderr_logging or syslog == constants.SYSLOG_YES:
        logging.exception("Failed to enable logging to file '%s'", logfile)
      else:
        # we need to re-raise the exception
        raise


def IsNormAbsPath(path):
  """Check whether a path is absolute and also normalized

  This avoids things like /dir/../../other/path to be valid.

  """
  return os.path.normpath(path) == path and os.path.isabs(path)


def PathJoin(*args):
  """Safe-join a list of path components.

  Requirements:
      - the first argument must be an absolute path
      - no component in the path must have backtracking (e.g. /../),
        since we check for normalization at the end

  @param args: the path components to be joined
  @raise ValueError: for invalid paths

  """
  # ensure we're having at least one path passed in
  assert args
  # ensure the first component is an absolute and normalized path name
  root = args[0]
  if not IsNormAbsPath(root):
    raise ValueError("Invalid parameter to PathJoin: '%s'" % str(args[0]))
  result = os.path.join(*args)
  # ensure that the whole path is normalized
  if not IsNormAbsPath(result):
    raise ValueError("Invalid parameters to PathJoin: '%s'" % str(args))
  # check that we're still under the original prefix
  prefix = os.path.commonprefix([root, result])
  if prefix != root:
    raise ValueError("Error: path joining resulted in different prefix"
                     " (%s != %s)" % (prefix, root))
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
    pos = max(0, pos-4096)
    fd.seek(pos, 0)
    raw_data = fd.read()
  finally:
    fd.close()

  rows = raw_data.splitlines()
  return rows[-lines:]


def FormatTimestampWithTZ(secs):
  """Formats a Unix timestamp with the local timezone.

  """
  return time.strftime("%F %T %Z", time.gmtime(secs))


def _ParseAsn1Generalizedtime(value):
  """Parses an ASN1 GENERALIZEDTIME timestamp as used by pyOpenSSL.

  @type value: string
  @param value: ASN1 GENERALIZEDTIME timestamp

  """
  m = re.match(r"^(\d+)([-+]\d\d)(\d\d)$", value)
  if m:
    # We have an offset
    asn1time = m.group(1)
    hours = int(m.group(2))
    minutes = int(m.group(3))
    utcoffset = (60 * hours) + minutes
  else:
    if not value.endswith("Z"):
      raise ValueError("Missing timezone")
    asn1time = value[:-1]
    utcoffset = 0

  parsed = time.strptime(asn1time, "%Y%m%d%H%M%S")

  tt = datetime.datetime(*(parsed[:7])) - datetime.timedelta(minutes=utcoffset)

  return calendar.timegm(tt.utctimetuple())


def GetX509CertValidity(cert):
  """Returns the validity period of the certificate.

  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object

  """
  # The get_notBefore and get_notAfter functions are only supported in
  # pyOpenSSL 0.7 and above.
  try:
    get_notbefore_fn = cert.get_notBefore
  except AttributeError:
    not_before = None
  else:
    not_before_asn1 = get_notbefore_fn()

    if not_before_asn1 is None:
      not_before = None
    else:
      not_before = _ParseAsn1Generalizedtime(not_before_asn1)

  try:
    get_notafter_fn = cert.get_notAfter
  except AttributeError:
    not_after = None
  else:
    not_after_asn1 = get_notafter_fn()

    if not_after_asn1 is None:
      not_after = None
    else:
      not_after = _ParseAsn1Generalizedtime(not_after_asn1)

  return (not_before, not_after)


def _VerifyCertificateInner(expired, not_before, not_after, now,
                            warn_days, error_days):
  """Verifies certificate validity.

  @type expired: bool
  @param expired: Whether pyOpenSSL considers the certificate as expired
  @type not_before: number or None
  @param not_before: Unix timestamp before which certificate is not valid
  @type not_after: number or None
  @param not_after: Unix timestamp after which certificate is invalid
  @type now: number
  @param now: Current time as Unix timestamp
  @type warn_days: number or None
  @param warn_days: How many days before expiration a warning should be reported
  @type error_days: number or None
  @param error_days: How many days before expiration an error should be reported

  """
  if expired:
    msg = "Certificate is expired"

    if not_before is not None and not_after is not None:
      msg += (" (valid from %s to %s)" %
              (FormatTimestampWithTZ(not_before),
               FormatTimestampWithTZ(not_after)))
    elif not_before is not None:
      msg += " (valid from %s)" % FormatTimestampWithTZ(not_before)
    elif not_after is not None:
      msg += " (valid until %s)" % FormatTimestampWithTZ(not_after)

    return (CERT_ERROR, msg)

  elif not_before is not None and not_before > now:
    return (CERT_WARNING,
            "Certificate not yet valid (valid from %s)" %
            FormatTimestampWithTZ(not_before))

  elif not_after is not None:
    remaining_days = int((not_after - now) / (24 * 3600))

    msg = "Certificate expires in about %d days" % remaining_days

    if error_days is not None and remaining_days <= error_days:
      return (CERT_ERROR, msg)

    if warn_days is not None and remaining_days <= warn_days:
      return (CERT_WARNING, msg)

  return (None, None)


def VerifyX509Certificate(cert, warn_days, error_days):
  """Verifies a certificate for LUVerifyCluster.

  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object
  @type warn_days: number or None
  @param warn_days: How many days before expiration a warning should be reported
  @type error_days: number or None
  @param error_days: How many days before expiration an error should be reported

  """
  # Depending on the pyOpenSSL version, this can just return (None, None)
  (not_before, not_after) = GetX509CertValidity(cert)

  return _VerifyCertificateInner(cert.has_expired(), not_before, not_after,
                                 time.time(), warn_days, error_days)


def SignX509Certificate(cert, key, salt):
  """Sign a X509 certificate.

  An RFC822-like signature header is added in front of the certificate.

  @type cert: OpenSSL.crypto.X509
  @param cert: X509 certificate object
  @type key: string
  @param key: Key for HMAC
  @type salt: string
  @param salt: Salt for HMAC
  @rtype: string
  @return: Serialized and signed certificate in PEM format

  """
  if not VALID_X509_SIGNATURE_SALT.match(salt):
    raise errors.GenericError("Invalid salt: %r" % salt)

  # Dumping as PEM here ensures the certificate is in a sane format
  cert_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)

  return ("%s: %s/%s\n\n%s" %
          (constants.X509_CERT_SIGNATURE_HEADER, salt,
           Sha1Hmac(key, cert_pem, salt=salt),
           cert_pem))


def _ExtractX509CertificateSignature(cert_pem):
  """Helper function to extract signature from X509 certificate.

  """
  # Extract signature from original PEM data
  for line in cert_pem.splitlines():
    if line.startswith("---"):
      break

    m = X509_SIGNATURE.match(line.strip())
    if m:
      return (m.group("salt"), m.group("sign"))

  raise errors.GenericError("X509 certificate signature is missing")


def LoadSignedX509Certificate(cert_pem, key):
  """Verifies a signed X509 certificate.

  @type cert_pem: string
  @param cert_pem: Certificate in PEM format and with signature header
  @type key: string
  @param key: Key for HMAC
  @rtype: tuple; (OpenSSL.crypto.X509, string)
  @return: X509 certificate object and salt

  """
  (salt, signature) = _ExtractX509CertificateSignature(cert_pem)

  # Load certificate
  cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert_pem)

  # Dump again to ensure it's in a sane format
  sane_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)

  if not VerifySha1Hmac(key, sane_pem, signature, salt=salt):
    raise errors.GenericError("X509 certificate signature is invalid")

  return (cert, salt)


def Sha1Hmac(key, text, salt=None):
  """Calculates the HMAC-SHA1 digest of a text.

  HMAC is defined in RFC2104.

  @type key: string
  @param key: Secret key
  @type text: string

  """
  if salt:
    salted_text = salt + text
  else:
    salted_text = text

  return hmac.new(key, salted_text, compat.sha1).hexdigest()


def VerifySha1Hmac(key, text, digest, salt=None):
  """Verifies the HMAC-SHA1 digest of a text.

  HMAC is defined in RFC2104.

  @type key: string
  @param key: Secret key
  @type text: string
  @type digest: string
  @param digest: Expected digest
  @rtype: bool
  @return: Whether HMAC-SHA1 digest matches

  """
  return digest.lower() == Sha1Hmac(key, text, salt=salt).lower()


def SafeEncode(text):
  """Return a 'safe' version of a source string.

  This function mangles the input string and returns a version that
  should be safe to display/encode as ASCII. To this end, we first
  convert it to ASCII using the 'backslashreplace' encoding which
  should get rid of any non-ASCII chars, and then we process it
  through a loop copied from the string repr sources in the python; we
  don't use string_escape anymore since that escape single quotes and
  backslashes too, and that is too much; and that escaping is not
  stable, i.e. string_escape(string_escape(x)) != string_escape(x).

  @type text: str or unicode
  @param text: input data
  @rtype: str
  @return: a safe version of text

  """
  if isinstance(text, unicode):
    # only if unicode; if str already, we handle it below
    text = text.encode('ascii', 'backslashreplace')
  resu = ""
  for char in text:
    c = ord(char)
    if char  == '\t':
      resu += r'\t'
    elif char == '\n':
      resu += r'\n'
    elif char == '\r':
      resu += r'\'r'
    elif c < 32 or c >= 127: # non-printable
      resu += "\\x%02x" % (c & 0xff)
    else:
      resu += char
  return resu


def UnescapeAndSplit(text, sep=","):
  """Split and unescape a string based on a given separator.

  This function splits a string based on a separator where the
  separator itself can be escape in order to be an element of the
  elements. The escaping rules are (assuming coma being the
  separator):
    - a plain , separates the elements
    - a sequence \\\\, (double backslash plus comma) is handled as a
      backslash plus a separator comma
    - a sequence \, (backslash plus comma) is handled as a
      non-separator comma

  @type text: string
  @param text: the string to split
  @type sep: string
  @param text: the separator
  @rtype: string
  @return: a list of strings

  """
  # we split the list by sep (with no escaping at this stage)
  slist = text.split(sep)
  # next, we revisit the elements and if any of them ended with an odd
  # number of backslashes, then we join it with the next
  rlist = []
  while slist:
    e1 = slist.pop(0)
    if e1.endswith("\\"):
      num_b = len(e1) - len(e1.rstrip("\\"))
      if num_b % 2 == 1:
        e2 = slist.pop(0)
        # here the backslashes remain (all), and will be reduced in
        # the next step
        rlist.append(e1 + sep + e2)
        continue
    rlist.append(e1)
  # finally, replace backslash-something with something
  rlist = [re.sub(r"\\(.)", r"\1", v) for v in rlist]
  return rlist


def CommaJoin(names):
  """Nicely join a set of identifiers.

  @param names: set, list or tuple
  @return: a string with the formatted results

  """
  return ", ".join([str(val) for val in names])


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


def GetMounts(filename=constants.PROC_MOUNTS):
  """Returns the list of mounted filesystems.

  This function is Linux-specific.

  @param filename: path of mounts file (/proc/mounts by default)
  @rtype: list of tuples
  @return: list of mount entries (device, mountpoint, fstype, options)

  """
  # TODO(iustin): investigate non-Linux options (e.g. via mount output)
  data = []
  mountlines = ReadFile(filename).splitlines()
  for line in mountlines:
    device, mountpoint, fstype, options, _ = line.split(None, 4)
    data.append((device, mountpoint, fstype, options))

  return data


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


def RunInSeparateProcess(fn, *args):
  """Runs a function in a separate process.

  Note: Only boolean return values are supported.

  @type fn: callable
  @param fn: Function to be called
  @rtype: bool
  @return: Function's result

  """
  pid = os.fork()
  if pid == 0:
    # Child process
    try:
      # In case the function uses temporary files
      ResetTempfileModule()

      # Call function
      result = int(bool(fn(*args)))
      assert result in (0, 1)
    except: # pylint: disable-msg=W0702
      logging.exception("Error while calling function in separate process")
      # 0 and 1 are reserved for the return value
      result = 33

    os._exit(result) # pylint: disable-msg=W0212

  # Parent process

  # Avoid zombies and check exit code
  (_, status) = os.waitpid(pid, 0)

  if os.WIFSIGNALED(status):
    exitcode = None
    signum = os.WTERMSIG(status)
  else:
    exitcode = os.WEXITSTATUS(status)
    signum = None

  if not (exitcode in (0, 1) and signum is None):
    raise errors.GenericError("Child program failed (code=%s, signal=%s)" %
                              (exitcode, signum))

  return bool(exitcode)


def IgnoreProcessNotFound(fn, *args, **kwargs):
  """Ignores ESRCH when calling a process-related function.

  ESRCH is raised when a process is not found.

  @rtype: bool
  @return: Whether process was found

  """
  try:
    fn(*args, **kwargs)
  except EnvironmentError, err:
    # Ignore ESRCH
    if err.errno == errno.ESRCH:
      return False
    raise

  return True


def IgnoreSignals(fn, *args, **kwargs):
  """Tries to call a function ignoring failures due to EINTR.

  """
  try:
    return fn(*args, **kwargs)
  except EnvironmentError, err:
    if err.errno == errno.EINTR:
      return None
    else:
      raise
  except (select.error, socket.error), err:
    # In python 2.6 and above select.error is an IOError, so it's handled
    # above, in 2.5 and below it's not, and it's handled here.
    if err.args and err.args[0] == errno.EINTR:
      return None
    else:
      raise


def LockFile(fd):
  """Locks a file using POSIX locks.

  @type fd: int
  @param fd: the file descriptor we need to lock

  """
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except IOError, err:
    if err.errno == errno.EAGAIN:
      raise errors.LockError("File already locked")
    raise


def FormatTime(val):
  """Formats a time value.

  @type val: float or None
  @param val: the timestamp as returned by time.time()
  @return: a string value or N/A if we don't have a valid timestamp

  """
  if val is None or not isinstance(val, (int, float)):
    return "N/A"
  # these two codes works on Linux, but they are not guaranteed on all
  # platforms
  return time.strftime("%F %T", time.localtime(val))


def FormatSeconds(secs):
  """Formats seconds for easier reading.

  @type secs: number
  @param secs: Number of seconds
  @rtype: string
  @return: Formatted seconds (e.g. "2d 9h 19m 49s")

  """
  parts = []

  secs = round(secs, 0)

  if secs > 0:
    # Negative values would be a bit tricky
    for unit, one in [("d", 24 * 60 * 60), ("h", 60 * 60), ("m", 60)]:
      (complete, secs) = divmod(secs, one)
      if complete or parts:
        parts.append("%d%s" % (complete, unit))

  parts.append("%ds" % secs)

  return " ".join(parts)


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


class RetryTimeout(Exception):
  """Retry loop timed out.

  Any arguments which was passed by the retried function to RetryAgain will be
  preserved in RetryTimeout, if it is raised. If such argument was an exception
  the RaiseInner helper method will reraise it.

  """
  def RaiseInner(self):
    if self.args and isinstance(self.args[0], Exception):
      raise self.args[0]
    else:
      raise RetryTimeout(*self.args)


class RetryAgain(Exception):
  """Retry again.

  Any arguments passed to RetryAgain will be preserved, if a timeout occurs, as
  arguments to RetryTimeout. If an exception is passed, the RaiseInner() method
  of the RetryTimeout() method can be used to reraise it.

  """


class _RetryDelayCalculator(object):
  """Calculator for increasing delays.

  """
  __slots__ = [
    "_factor",
    "_limit",
    "_next",
    "_start",
    ]

  def __init__(self, start, factor, limit):
    """Initializes this class.

    @type start: float
    @param start: Initial delay
    @type factor: float
    @param factor: Factor for delay increase
    @type limit: float or None
    @param limit: Upper limit for delay or None for no limit

    """
    assert start > 0.0
    assert factor >= 1.0
    assert limit is None or limit >= 0.0

    self._start = start
    self._factor = factor
    self._limit = limit

    self._next = start

  def __call__(self):
    """Returns current delay and calculates the next one.

    """
    current = self._next

    # Update for next run
    if self._limit is None or self._next < self._limit:
      self._next = min(self._limit, self._next * self._factor)

    return current


#: Special delay to specify whole remaining timeout
RETRY_REMAINING_TIME = object()


def Retry(fn, delay, timeout, args=None, wait_fn=time.sleep,
          _time_fn=time.time):
  """Call a function repeatedly until it succeeds.

  The function C{fn} is called repeatedly until it doesn't throw L{RetryAgain}
  anymore. Between calls a delay, specified by C{delay}, is inserted. After a
  total of C{timeout} seconds, this function throws L{RetryTimeout}.

  C{delay} can be one of the following:
    - callable returning the delay length as a float
    - Tuple of (start, factor, limit)
    - L{RETRY_REMAINING_TIME} to sleep until the timeout expires (this is
      useful when overriding L{wait_fn} to wait for an external event)
    - A static delay as a number (int or float)

  @type fn: callable
  @param fn: Function to be called
  @param delay: Either a callable (returning the delay), a tuple of (start,
                factor, limit) (see L{_RetryDelayCalculator}),
                L{RETRY_REMAINING_TIME} or a number (int or float)
  @type timeout: float
  @param timeout: Total timeout
  @type wait_fn: callable
  @param wait_fn: Waiting function
  @return: Return value of function

  """
  assert callable(fn)
  assert callable(wait_fn)
  assert callable(_time_fn)

  if args is None:
    args = []

  end_time = _time_fn() + timeout

  if callable(delay):
    # External function to calculate delay
    calc_delay = delay

  elif isinstance(delay, (tuple, list)):
    # Increasing delay with optional upper boundary
    (start, factor, limit) = delay
    calc_delay = _RetryDelayCalculator(start, factor, limit)

  elif delay is RETRY_REMAINING_TIME:
    # Always use the remaining time
    calc_delay = None

  else:
    # Static delay
    calc_delay = lambda: delay

  assert calc_delay is None or callable(calc_delay)

  while True:
    retry_args = []
    try:
      # pylint: disable-msg=W0142
      return fn(*args)
    except RetryAgain, err:
      retry_args = err.args
    except RetryTimeout:
      raise errors.ProgrammerError("Nested retry loop detected that didn't"
                                   " handle RetryTimeout")

    remaining_time = end_time - _time_fn()

    if remaining_time < 0.0:
      # pylint: disable-msg=W0142
      raise RetryTimeout(*retry_args)

    assert remaining_time >= 0.0

    if calc_delay is None:
      wait_fn(remaining_time)
    else:
      current_delay = calc_delay()
      if current_delay > 0.0:
        wait_fn(current_delay)


def GetClosedTempfile(*args, **kwargs):
  """Creates a temporary file and returns its path.

  """
  (fd, path) = tempfile.mkstemp(*args, **kwargs)
  _CloseFDNoErr(fd)
  return path


def GenerateSelfSignedX509Cert(common_name, validity):
  """Generates a self-signed X509 certificate.

  @type common_name: string
  @param common_name: commonName value
  @type validity: int
  @param validity: Validity for certificate in seconds

  """
  # Create private and public key
  key = OpenSSL.crypto.PKey()
  key.generate_key(OpenSSL.crypto.TYPE_RSA, constants.RSA_KEY_BITS)

  # Create self-signed certificate
  cert = OpenSSL.crypto.X509()
  if common_name:
    cert.get_subject().CN = common_name
  cert.set_serial_number(1)
  cert.gmtime_adj_notBefore(0)
  cert.gmtime_adj_notAfter(validity)
  cert.set_issuer(cert.get_subject())
  cert.set_pubkey(key)
  cert.sign(key, constants.X509_CERT_SIGN_DIGEST)

  key_pem = OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)
  cert_pem = OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)

  return (key_pem, cert_pem)


def GenerateSelfSignedSslCert(filename, common_name=constants.X509_CERT_CN,
                              validity=constants.X509_CERT_DEFAULT_VALIDITY):
  """Legacy function to generate self-signed X509 certificate.

  @type filename: str
  @param filename: path to write certificate to
  @type common_name: string
  @param common_name: commonName value
  @type validity: int
  @param validity: validity of certificate in number of days

  """
  # TODO: Investigate using the cluster name instead of X505_CERT_CN for
  # common_name, as cluster-renames are very seldom, and it'd be nice if RAPI
  # and node daemon certificates have the proper Subject/Issuer.
  (key_pem, cert_pem) = GenerateSelfSignedX509Cert(common_name,
                                                   validity * 24 * 60 * 60)

  WriteFile(filename, mode=0400, data=key_pem + cert_pem)


class FileLock(object):
  """Utility class for file locks.

  """
  def __init__(self, fd, filename):
    """Constructor for FileLock.

    @type fd: file
    @param fd: File object
    @type filename: str
    @param filename: Path of the file opened at I{fd}

    """
    self.fd = fd
    self.filename = filename

  @classmethod
  def Open(cls, filename):
    """Creates and opens a file to be used as a file-based lock.

    @type filename: string
    @param filename: path to the file to be locked

    """
    # Using "os.open" is necessary to allow both opening existing file
    # read/write and creating if not existing. Vanilla "open" will truncate an
    # existing file -or- allow creating if not existing.
    return cls(os.fdopen(os.open(filename, os.O_RDWR | os.O_CREAT), "w+"),
               filename)

  def __del__(self):
    self.Close()

  def Close(self):
    """Close the file and release the lock.

    """
    if hasattr(self, "fd") and self.fd:
      self.fd.close()
      self.fd = None

  def _flock(self, flag, blocking, timeout, errmsg):
    """Wrapper for fcntl.flock.

    @type flag: int
    @param flag: operation flag
    @type blocking: bool
    @param blocking: whether the operation should be done in blocking mode.
    @type timeout: None or float
    @param timeout: for how long the operation should be retried (implies
                    non-blocking mode).
    @type errmsg: string
    @param errmsg: error message in case operation fails.

    """
    assert self.fd, "Lock was closed"
    assert timeout is None or timeout >= 0, \
      "If specified, timeout must be positive"
    assert not (flag & fcntl.LOCK_NB), "LOCK_NB must not be set"

    # When a timeout is used, LOCK_NB must always be set
    if not (timeout is None and blocking):
      flag |= fcntl.LOCK_NB

    if timeout is None:
      self._Lock(self.fd, flag, timeout)
    else:
      try:
        Retry(self._Lock, (0.1, 1.2, 1.0), timeout,
              args=(self.fd, flag, timeout))
      except RetryTimeout:
        raise errors.LockError(errmsg)

  @staticmethod
  def _Lock(fd, flag, timeout):
    try:
      fcntl.flock(fd, flag)
    except IOError, err:
      if timeout is not None and err.errno == errno.EAGAIN:
        raise RetryAgain()

      logging.exception("fcntl.flock failed")
      raise

  def Exclusive(self, blocking=False, timeout=None):
    """Locks the file in exclusive mode.

    @type blocking: boolean
    @param blocking: whether to block and wait until we
        can lock the file or return immediately
    @type timeout: int or None
    @param timeout: if not None, the duration to wait for the lock
        (in blocking mode)

    """
    self._flock(fcntl.LOCK_EX, blocking, timeout,
                "Failed to lock %s in exclusive mode" % self.filename)

  def Shared(self, blocking=False, timeout=None):
    """Locks the file in shared mode.

    @type blocking: boolean
    @param blocking: whether to block and wait until we
        can lock the file or return immediately
    @type timeout: int or None
    @param timeout: if not None, the duration to wait for the lock
        (in blocking mode)

    """
    self._flock(fcntl.LOCK_SH, blocking, timeout,
                "Failed to lock %s in shared mode" % self.filename)

  def Unlock(self, blocking=True, timeout=None):
    """Unlocks the file.

    According to C{flock(2)}, unlocking can also be a nonblocking
    operation::

      To make a non-blocking request, include LOCK_NB with any of the above
      operations.

    @type blocking: boolean
    @param blocking: whether to block and wait until we
        can lock the file or return immediately
    @type timeout: int or None
    @param timeout: if not None, the duration to wait for the lock
        (in blocking mode)

    """
    self._flock(fcntl.LOCK_UN, blocking, timeout,
                "Failed to unlock %s" % self.filename)


class LineSplitter:
  """Splits data chunks into lines separated by newline.

  Instances provide a file-like interface.

  """
  def __init__(self, line_fn, *args):
    """Initializes this class.

    @type line_fn: callable
    @param line_fn: Function called for each line, first parameter is line
    @param args: Extra arguments for L{line_fn}

    """
    assert callable(line_fn)

    if args:
      # Python 2.4 doesn't have functools.partial yet
      self._line_fn = \
        lambda line: line_fn(line, *args) # pylint: disable-msg=W0142
    else:
      self._line_fn = line_fn

    self._lines = collections.deque()
    self._buffer = ""

  def write(self, data):
    parts = (self._buffer + data).split("\n")
    self._buffer = parts.pop()
    self._lines.extend(parts)

  def flush(self):
    while self._lines:
      self._line_fn(self._lines.popleft().rstrip("\r\n"))

  def close(self):
    self.flush()
    if self._buffer:
      self._line_fn(self._buffer)


def SignalHandled(signums):
  """Signal Handled decoration.

  This special decorator installs a signal handler and then calls the target
  function. The function must accept a 'signal_handlers' keyword argument,
  which will contain a dict indexed by signal number, with SignalHandler
  objects as values.

  The decorator can be safely stacked with iself, to handle multiple signals
  with different handlers.

  @type signums: list
  @param signums: signals to intercept

  """
  def wrap(fn):
    def sig_function(*args, **kwargs):
      assert 'signal_handlers' not in kwargs or \
             kwargs['signal_handlers'] is None or \
             isinstance(kwargs['signal_handlers'], dict), \
             "Wrong signal_handlers parameter in original function call"
      if 'signal_handlers' in kwargs and kwargs['signal_handlers'] is not None:
        signal_handlers = kwargs['signal_handlers']
      else:
        signal_handlers = {}
        kwargs['signal_handlers'] = signal_handlers
      sighandler = SignalHandler(signums)
      try:
        for sig in signums:
          signal_handlers[sig] = sighandler
        return fn(*args, **kwargs)
      finally:
        sighandler.Reset()
    return sig_function
  return wrap


class SignalWakeupFd(object):
  try:
    # This is only supported in Python 2.5 and above (some distributions
    # backported it to Python 2.4)
    _set_wakeup_fd_fn = signal.set_wakeup_fd
  except AttributeError:
    # Not supported
    def _SetWakeupFd(self, _): # pylint: disable-msg=R0201
      return -1
  else:
    def _SetWakeupFd(self, fd):
      return self._set_wakeup_fd_fn(fd)

  def __init__(self):
    """Initializes this class.

    """
    (read_fd, write_fd) = os.pipe()

    # Once these succeeded, the file descriptors will be closed automatically.
    # Buffer size 0 is important, otherwise .read() with a specified length
    # might buffer data and the file descriptors won't be marked readable.
    self._read_fh = os.fdopen(read_fd, "r", 0)
    self._write_fh = os.fdopen(write_fd, "w", 0)

    self._previous = self._SetWakeupFd(self._write_fh.fileno())

    # Utility functions
    self.fileno = self._read_fh.fileno
    self.read = self._read_fh.read

  def Reset(self):
    """Restores the previous wakeup file descriptor.

    """
    if hasattr(self, "_previous") and self._previous is not None:
      self._SetWakeupFd(self._previous)
      self._previous = None

  def Notify(self):
    """Notifies the wakeup file descriptor.

    """
    self._write_fh.write("\0")

  def __del__(self):
    """Called before object deletion.

    """
    self.Reset()


class SignalHandler(object):
  """Generic signal handler class.

  It automatically restores the original handler when deconstructed or
  when L{Reset} is called. You can either pass your own handler
  function in or query the L{called} attribute to detect whether the
  signal was sent.

  @type signum: list
  @ivar signum: the signals we handle
  @type called: boolean
  @ivar called: tracks whether any of the signals have been raised

  """
  def __init__(self, signum, handler_fn=None, wakeup=None):
    """Constructs a new SignalHandler instance.

    @type signum: int or list of ints
    @param signum: Single signal number or set of signal numbers
    @type handler_fn: callable
    @param handler_fn: Signal handling function

    """
    assert handler_fn is None or callable(handler_fn)

    self.signum = set(signum)
    self.called = False

    self._handler_fn = handler_fn
    self._wakeup = wakeup

    self._previous = {}
    try:
      for signum in self.signum:
        # Setup handler
        prev_handler = signal.signal(signum, self._HandleSignal)
        try:
          self._previous[signum] = prev_handler
        except:
          # Restore previous handler
          signal.signal(signum, prev_handler)
          raise
    except:
      # Reset all handlers
      self.Reset()
      # Here we have a race condition: a handler may have already been called,
      # but there's not much we can do about it at this point.
      raise

  def __del__(self):
    self.Reset()

  def Reset(self):
    """Restore previous handler.

    This will reset all the signals to their previous handlers.

    """
    for signum, prev_handler in self._previous.items():
      signal.signal(signum, prev_handler)
      # If successful, remove from dict
      del self._previous[signum]

  def Clear(self):
    """Unsets the L{called} flag.

    This function can be used in case a signal may arrive several times.

    """
    self.called = False

  def _HandleSignal(self, signum, frame):
    """Actual signal handling function.

    """
    # This is not nice and not absolutely atomic, but it appears to be the only
    # solution in Python -- there are no atomic types.
    self.called = True

    if self._wakeup:
      # Notify whoever is interested in signals
      self._wakeup.Notify()

    if self._handler_fn:
      self._handler_fn(signum, frame)


class FieldSet(object):
  """A simple field set.

  Among the features are:
    - checking if a string is among a list of static string or regex objects
    - checking if a whole list of string matches
    - returning the matching groups from a regex match

  Internally, all fields are held as regular expression objects.

  """
  def __init__(self, *items):
    self.items = [re.compile("^%s$" % value) for value in items]

  def Extend(self, other_set):
    """Extend the field set with the items from another one"""
    self.items.extend(other_set.items)

  def Matches(self, field):
    """Checks if a field matches the current set

    @type field: str
    @param field: the string to match
    @return: either None or a regular expression match object

    """
    for m in itertools.ifilter(None, (val.match(field) for val in self.items)):
      return m
    return None

  def NonMatching(self, items):
    """Returns the list of fields not matching the current set

    @type items: list
    @param items: the list of fields to check
    @rtype: list
    @return: list of non-matching fields

    """
    return [val for val in items if not self.Matches(val)]
