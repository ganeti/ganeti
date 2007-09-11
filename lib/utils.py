#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Ganeti small utilities
"""


import sys
import os
import sha
import time
import subprocess
import re
import socket
import tempfile
import shutil
from errno import ENOENT, ENOTDIR, EISDIR, EEXIST

from ganeti import logger
from ganeti import errors

_locksheld = []
_re_shell_unquoted = re.compile('^[-.,=:/_+@A-Za-z0-9]+$')

class RunResult(object):
  """Simple class for holding the result of running external programs.

  Instance variables:
    exit_code: the exit code of the program, or None (if the program
               didn't exit())
    signal: numeric signal that caused the program to finish, or None
            (if the program wasn't terminated by a signal)
    stdout: the standard output of the program
    stderr: the standard error of the program
    failed: a Boolean value which is True in case the program was
            terminated by a signal or exited with a non-zero exit code
    fail_reason: a string detailing the termination reason

  """
  __slots__ = ["exit_code", "signal", "stdout", "stderr",
               "failed", "fail_reason", "cmd"]


  def __init__(self, exit_code, signal, stdout, stderr, cmd):
    self.cmd = cmd
    self.exit_code = exit_code
    self.signal = signal
    self.stdout = stdout
    self.stderr = stderr
    self.failed = (signal is not None or exit_code != 0)

    if self.signal is not None:
      self.fail_reason = "terminated by signal %s" % self.signal
    elif self.exit_code is not None:
      self.fail_reason = "exited with exit code %s" % self.exit_code
    else:
      self.fail_reason = "unable to determine termination reason"

  def _GetOutput(self):
    """Returns the combined stdout and stderr for easier usage.

    """
    return self.stdout + self.stderr

  output = property(_GetOutput, None, None, "Return full output")


def _GetLockFile(subsystem):
  """Compute the file name for a given lock name."""
  return "/var/lock/ganeti_lock_%s" % subsystem


def Lock(name, max_retries=None, debug=False):
  """Lock a given subsystem.

  In case the lock is already held by an alive process, the function
  will sleep indefintely and poll with a one second interval.

  When the optional integer argument 'max_retries' is passed with a
  non-zero value, the function will sleep only for this number of
  times, and then it will will raise a LockError if the lock can't be
  acquired. Passing in a negative number will cause only one try to
  get the lock. Passing a positive number will make the function retry
  for approximately that number of seconds.

  """
  lockfile = _GetLockFile(name)

  if name in _locksheld:
    raise errors.LockError('Lock "%s" already held!' % (name,))

  errcount = 0

  retries = 0
  while True:
    try:
      fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_SYNC)
      break
    except OSError, creat_err:
      if creat_err.errno != EEXIST:
        raise errors.LockError("Can't create the lock file. Error '%s'." %
                               str(creat_err))

      try:
        pf = open(lockfile, 'r')
      except IOError, open_err:
        errcount += 1
        if errcount >= 5:
          raise errors.LockError("Lock file exists but cannot be opened."
                                 " Error: '%s'." % str(open_err))
        time.sleep(1)
        continue

      try:
        pid = int(pf.read())
      except ValueError:
        raise errors.LockError("Invalid pid string in %s" %
                               (lockfile,))

      if not IsProcessAlive(pid):
        raise errors.LockError("Stale lockfile %s for pid %d?" %
                               (lockfile, pid))

      if max_retries and max_retries <= retries:
        raise errors.LockError("Can't acquire lock during the specified"
                               " time, aborting.")
      if retries == 5 and (debug or sys.stdin.isatty()):
        logger.ToStderr("Waiting for '%s' lock from pid %d..." % (name, pid))

      time.sleep(1)
      retries += 1
      continue

  os.write(fd, '%d\n' % (os.getpid(),))
  os.close(fd)

  _locksheld.append(name)


def Unlock(name):
  """Unlock a given subsystem.

  """
  lockfile = _GetLockFile(name)

  try:
    fd = os.open(lockfile, os.O_RDONLY)
  except OSError:
    raise errors.LockError('Lock "%s" not held.' % (name,))

  f = os.fdopen(fd, 'r')
  pid_str = f.read()

  try:
    pid = int(pid_str)
  except ValueError:
    raise errors.LockError('Unable to determine PID of locking process.')

  if pid != os.getpid():
    raise errors.LockError('Lock not held by me (%d != %d)' %
                           (os.getpid(), pid,))

  os.unlink(lockfile)
  _locksheld.remove(name)


def LockCleanup():
  """Remove all locks.

  """
  for lock in _locksheld:
    Unlock(lock)


def RunCmd(cmd):
  """Execute a (shell) command.

  The command should not read from its standard input, as it will be
  closed.

  Args:
    cmd: command to run. (str)

  Returns: `RunResult` instance

  """
  if isinstance(cmd, list):
    cmd = [str(val) for val in cmd]
    strcmd = " ".join(cmd)
    shell = False
  else:
    strcmd = cmd
    shell = True
  new_env = dict([(key, val) for (key, val) in os.environ.items()
                  if not (key == "LANG" or key.startswith("LC_"))])
  child = subprocess.Popen(cmd, shell=shell,
                           stderr=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           stdin=subprocess.PIPE,
                           close_fds=True, env=new_env)

  child.stdin.close()
  out = child.stdout.read()
  err = child.stderr.read()

  status = child.wait()
  if status >= 0:
    exitcode = status
    signal = None
  else:
    exitcode = None
    signal = -status

  return RunResult(exitcode, signal, out, err, strcmd)


def RunCmdUnlocked(cmd):
  """Execute a shell command without the 'cmd' lock.

  This variant of `RunCmd()` drops the 'cmd' lock before running the
  command and re-aquires it afterwards, thus it can be used to call
  other ganeti commands.

  The argument and return values are the same as for the `RunCmd()`
  function.

  Args:
    cmd - command to run. (str)

  Returns:
    `RunResult`

  """
  Unlock('cmd')
  ret = RunCmd(cmd)
  Lock('cmd')

  return ret


def RemoveFile(filename):
  """Remove a file ignoring some errors.

  Remove a file, ignoring non-existing ones or directories. Other
  errors are passed.

  """
  try:
    os.unlink(filename)
  except OSError, err:
    if err.errno not in (ENOENT, EISDIR):
      raise


def _FingerprintFile(filename):
  """Compute the fingerprint of a file.

  If the file does not exist, a None will be returned
  instead.

  Args:
    filename - Filename (str)

  """
  if not (os.path.exists(filename) and os.path.isfile(filename)):
    return None

  f = open(filename)

  fp = sha.sha()
  while True:
    data = f.read(4096)
    if not data:
      break

    fp.update(data)

  return fp.hexdigest()


def FingerprintFiles(files):
  """Compute fingerprints for a list of files.

  Args:
    files - array of filenames.  ( [str, ...] )

  Return value:
    dictionary of filename: fingerprint for the files that exist

  """
  ret = {}

  for filename in files:
    cksum = _FingerprintFile(filename)
    if cksum:
      ret[filename] = cksum

  return ret


def CheckDict(target, template, logname=None):
  """Ensure a dictionary has a required set of keys.

  For the given dictionaries `target` and `template`, ensure target
  has all the keys from template. Missing keys are added with values
  from template.

  Args:
    target   - the dictionary to check
    template - template dictionary
    logname  - a caller-chosen string to identify the debug log
               entry; if None, no logging will be done

  Returns value:
    None

  """
  missing = []
  for k in template:
    if k not in target:
      missing.append(k)
      target[k] = template[k]

  if missing and logname:
    logger.Debug('%s missing keys %s' %
                 (logname, ', '.join(missing)))


def IsProcessAlive(pid):
  """Check if a given pid exists on the system.

  Returns: true or false, depending on if the pid exists or not

  Remarks: zombie processes treated as not alive

  """
  try:
    f = open("/proc/%d/status" % pid)
  except IOError, err:
    if err.errno in (ENOENT, ENOTDIR):
      return False

  alive = True
  try:
    data = f.readlines()
    if len(data) > 1:
      state = data[1].split()
      if len(state) > 1 and state[1] == "Z":
        alive = False
  finally:
    f.close()

  return alive


def MatchNameComponent(key, name_list):
  """Try to match a name against a list.

  This function will try to match a name like test1 against a list
  like ['test1.example.com', 'test2.example.com', ...]. Against this
  list, 'test1' as well as 'test1.example' will match, but not
  'test1.ex'. A multiple match will be considered as no match at all
  (e.g. 'test1' against ['test1.example.com', 'test1.example.org']).

  Args:
    key: the name to be searched
    name_list: the list of strings against which to search the key

  Returns:
    None if there is no match *or* if there are multiple matches
    otherwise the element from the list which matches

  """
  mo = re.compile("^%s(\..*)?$" % re.escape(key))
  names_filtered = [name for name in name_list if mo.match(name) is not None]
  if len(names_filtered) != 1:
    return None
  return names_filtered[0]


def LookupHostname(hostname):
  """Look up hostname

  Args:
    hostname: hostname to look up, can be also be a non FQDN

  Returns:
    Dictionary with keys:
    - ip: IP addr
    - hostname_full: hostname fully qualified
    - hostname: hostname fully qualified (historic artifact)

  """
  try:
    (fqdn, dummy, ipaddrs) = socket.gethostbyname_ex(hostname)
    ipaddr = ipaddrs[0]
  except socket.gaierror:
    # hostname not found in DNS
    return None

  returnhostname = {
    "ip": ipaddr,
    "hostname_full": fqdn,
    "hostname": fqdn,
    }

  return returnhostname


def ListVolumeGroups():
  """List volume groups and their size

  Returns:
     Dictionary with keys volume name and values the size of the volume

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
      logger.Error("Invalid output from vgs (%s): %s" % (err, line))
      continue

    retval[name] = size

  return retval


def BridgeExists(bridge):
  """Check whether the given bridge exists in the system

  Returns:
     True if it does, false otherwise.

  """
  return os.path.isdir("/sys/class/net/%s/bridge" % bridge)


def NiceSort(name_list):
  """Sort a list of strings based on digit and non-digit groupings.

  Given a list of names ['a1', 'a10', 'a11', 'a2'] this function will
  sort the list in the logical order ['a1', 'a2', 'a10', 'a11'].

  The sort algorithm breaks each name in groups of either only-digits
  or no-digits. Only the first eight such groups are considered, and
  after that we just use what's left of the string.

  Return value
    - a copy of the list sorted according to our algorithm

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


def CheckDaemonAlive(pid_file, process_string):
  """Check wether the specified daemon is alive.

  Args:
   - pid_file: file to read the daemon pid from, the file is
               expected to contain only a single line containing
               only the PID
   - process_string: a substring that we expect to find in
                     the command line of the daemon process

  Returns:
   - True if the daemon is judged to be alive (that is:
      - the PID file exists, is readable and contains a number
      - a process of the specified PID is running
      - that process contains the specified string in its
        command line
      - the process is not in state Z (zombie))
   - False otherwise

  """
  try:
    pid_file = file(pid_file, 'r')
    try:
      pid = int(pid_file.readline())
    finally:
      pid_file.close()

    cmdline_file_path = "/proc/%s/cmdline" % (pid)
    cmdline_file = open(cmdline_file_path, 'r')
    try:
      cmdline = cmdline_file.readline()
    finally:
      cmdline_file.close()

    if not process_string in cmdline:
      return False

    stat_file_path =  "/proc/%s/stat" % (pid)
    stat_file = open(stat_file_path, 'r')
    try:
      process_state = stat_file.readline().split()[2]
    finally:
      stat_file.close()

    if process_state == 'Z':
      return False

  except (IndexError, IOError, ValueError):
    return False

  return True


def TryConvert(fn, val):
  """Try to convert a value ignoring errors.

  This function tries to apply function `fn` to `val`. If no
  ValueError or TypeError exceptions are raised, it will return the
  result, else it will return the original value. Any other exceptions
  are propagated to the caller.

  """
  try:
    nv = fn(val)
  except (ValueError, TypeError), err:
    nv = val
  return nv


def IsValidIP(ip):
  """Verifies the syntax of an IP address.

  This function checks if the ip address passes is valid or not based
  on syntax (not ip range, class calculations or anything).

  """
  unit = "(0|[1-9]\d{0,2})"
  return re.match("^%s\.%s\.%s\.%s$" % (unit, unit, unit, unit), ip)


def IsValidShellParam(word):
  """Verifies is the given word is safe from the shell's p.o.v.

  This means that we can pass this to a command via the shell and be
  sure that it doesn't alter the command line and is passed as such to
  the actual command.

  Note that we are overly restrictive here, in order to be on the safe
  side.

  """
  return bool(re.match("^[-a-zA-Z0-9._+/:%@]+$", word))


def BuildShellCmd(template, *args):
  """Build a safe shell command line from the given arguments.

  This function will check all arguments in the args list so that they
  are valid shell parameters (i.e. they don't contain shell
  metacharaters). If everything is ok, it will return the result of
  template % args.

  """
  for word in args:
    if not IsValidShellParam(word):
      raise errors.ProgrammerError("Shell argument '%s' contains"
                                   " invalid characters" % word)
  return template % args


def FormatUnit(value):
  """Formats an incoming number of MiB with the appropriate unit.

  Value needs to be passed as a numeric type. Return value is always a string.

  """
  if value < 1024:
    return "%dM" % round(value, 0)

  elif value < (1024 * 1024):
    return "%0.1fG" % round(float(value) / 1024, 1)

  else:
    return "%0.1fT" % round(float(value) / 1024 / 1024, 1)


def ParseUnit(input_string):
  """Tries to extract number and scale from the given string.

  Input must be in the format NUMBER+ [DOT NUMBER+] SPACE* [UNIT]. If no unit
  is specified, it defaults to MiB. Return value is always an int in MiB.

  """
  m = re.match('^([.\d]+)\s*([a-zA-Z]+)?$', input_string)
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


def AddAuthorizedKey(file_name, key):
  """Adds an SSH public key to an authorized_keys file.

  Args:
    file_name: Path to authorized_keys file
    key: String containing key
  """
  key_fields = key.split()

  f = open(file_name, 'a+')
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

  Args:
    file_name: Path to authorized_keys file
    key: String containing key
  """
  key_fields = key.split()

  fd, tmpname = tempfile.mkstemp(dir=os.path.dirname(file_name))
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


def CreateBackup(file_name):
  """Creates a backup of a file.

  Returns: the path to the newly created backup file.

  """
  if not os.path.isfile(file_name):
    raise errors.ProgrammerError("Can't make a backup of a non-file '%s'" %
                                file_name)

  # Warning: the following code contains a race condition when we create more
  # than one backup of the same file in a second.
  backup_name = file_name + '.backup-%d' % int(time.time())
  shutil.copyfile(file_name, backup_name)
  return backup_name


def ShellQuote(value):
  """Quotes shell argument according to POSIX.

  """
  if _re_shell_unquoted.match(value):
    return value
  else:
    return "'%s'" % value.replace("'", "'\\''")


def ShellQuoteArgs(args):
  """Quotes all given shell arguments and concatenates using spaces.

  """
  return ' '.join([ShellQuote(i) for i in args])


def _ParseIpOutput(output):
  """Parsing code for GetLocalIPAddresses().

  This function is split out, so we can unit test it.

  """
  re_ip = re.compile('^(\d+\.\d+\.\d+\.\d+)(?:/\d+)$')

  ips = []
  for line in output.splitlines(False):
    fields = line.split()
    if len(line) < 4:
      continue
    m = re_ip.match(fields[3])
    if m:
      ips.append(m.group(1))

  return ips


def GetLocalIPAddresses():
  """Gets a list of all local IP addresses.

  Should this break one day, a small Python module written in C could
  use the API call getifaddrs().

  """
  result = RunCmd(["ip", "-family", "inet", "-oneline", "addr", "show"])
  if result.failed:
    raise errors.OpExecError("Command '%s' failed, error: %s,"
      " output: %s" % (result.cmd, result.fail_reason, result.output))

  return _ParseIpOutput(result.output)
