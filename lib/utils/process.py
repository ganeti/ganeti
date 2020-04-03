#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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

"""Utility functions for processes.

"""


import os
import sys
import subprocess
import errno
import select
import logging
import signal
import resource

from io import StringIO

from ganeti import errors
from ganeti import constants
from ganeti import compat

from ganeti.utils import retry as utils_retry
from ganeti.utils import wrapper as utils_wrapper
from ganeti.utils import text as utils_text
from ganeti.utils import io as utils_io
from ganeti.utils import algo as utils_algo


#: when set to True, L{RunCmd} is disabled
_no_fork = False

(_TIMEOUT_NONE,
 _TIMEOUT_TERM,
 _TIMEOUT_KILL) = range(3)


def DisableFork():
  """Disables the use of fork(2).

  """
  global _no_fork # pylint: disable=W0603

  _no_fork = True


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
  @type failed_by_timeout: boolean
  @ivar failed_by_timeout: True in case the program was
      terminated by timeout
  @ivar fail_reason: a string detailing the termination reason

  """
  __slots__ = ["exit_code", "signal", "stdout", "stderr",
               "failed", "failed_by_timeout", "fail_reason", "cmd"]

  def __init__(self, exit_code, signal_, stdout, stderr, cmd, timeout_action,
               timeout):
    self.cmd = cmd
    self.exit_code = exit_code
    self.signal = signal_
    self.stdout = stdout
    self.stderr = stderr
    self.failed = (signal_ is not None or exit_code != 0)
    self.failed_by_timeout = timeout_action != _TIMEOUT_NONE

    fail_msgs = []
    if self.signal is not None:
      fail_msgs.append("terminated by signal %s" % self.signal)
    elif self.exit_code is not None:
      fail_msgs.append("exited with exit code %s" % self.exit_code)
    else:
      fail_msgs.append("unable to determine termination reason")

    if timeout_action == _TIMEOUT_TERM:
      fail_msgs.append("terminated after timeout of %.2f seconds" % timeout)
    elif timeout_action == _TIMEOUT_KILL:
      fail_msgs.append(("force termination after timeout of %.2f seconds"
                        " and linger for another %.2f seconds") %
                       (timeout, constants.CHILD_LINGER_TIMEOUT))

    if fail_msgs and self.failed:
      self.fail_reason = utils_text.CommaJoin(fail_msgs)
    else:
      self.fail_reason = None

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
           interactive=False, timeout=None, noclose_fds=None,
           input_fd=None, postfork_fn=None):
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
  @param interactive: whether we pipe stdin, stdout and stderr
                      (default behaviour) or run the command interactive
  @type timeout: int
  @param timeout: If not None, timeout in seconds until child process gets
                  killed
  @type noclose_fds: list
  @param noclose_fds: list of additional (fd >=3) file descriptors to leave
                      open for the child process
  @type input_fd: C{file}-like object or numeric file descriptor
  @param input_fd: File descriptor for process' standard input
  @type postfork_fn: Callable receiving PID as parameter
  @param postfork_fn: Callback run after fork but before timeout
  @rtype: L{RunResult}
  @return: RunResult instance
  @raise errors.ProgrammerError: if we call this when forks are disabled

  """
  if _no_fork:
    raise errors.ProgrammerError("utils.RunCmd() called with fork() disabled")

  if output and interactive:
    raise errors.ProgrammerError("Parameters 'output' and 'interactive' can"
                                 " not be provided at the same time")

  if not (output is None or input_fd is None):
    # The current logic in "_RunCmdFile", which is used when output is defined,
    # does not support input files (not hard to implement, though)
    raise errors.ProgrammerError("Parameters 'output' and 'input_fd' can"
                                 " not be used at the same time")

  if isinstance(cmd, str):
    strcmd = cmd
    shell = True
  else:
    cmd = [str(val) for val in cmd]
    strcmd = utils_text.ShellQuoteArgs(cmd)
    shell = False

  if output:
    logging.info("RunCmd %s, output file '%s'", strcmd, output)
  else:
    logging.info("RunCmd %s", strcmd)

  cmd_env = _BuildCmdEnvironment(env, reset_env)

  try:
    if output is None:
      out, err, status, timeout_action = _RunCmdPipe(cmd, cmd_env, shell, cwd,
                                                     interactive, timeout,
                                                     noclose_fds, input_fd,
                                                     postfork_fn=postfork_fn)
    else:
      if postfork_fn:
        raise errors.ProgrammerError("postfork_fn is not supported if output"
                                     " should be captured")
      assert input_fd is None
      timeout_action = _TIMEOUT_NONE
      status = _RunCmdFile(cmd, cmd_env, shell, output, cwd, noclose_fds)
      out = err = ""
  except OSError as err:
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

  return RunResult(exitcode, signal_, out, err, strcmd, timeout_action, timeout)


def SetupDaemonEnv(cwd="/", umask=0o77):
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

  output_close = True

  if output_fd is not None:
    output_close = False
  elif output_file is not None:
    # Open output file
    try:
      output_fd = os.open(output_file,
                          os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    except EnvironmentError as err:
      raise Exception("Opening output file failed: %s" % err)
  else:
    output_fd = os.open(os.devnull, os.O_WRONLY)

  # Redirect standard I/O
  os.dup2(devnull_fd, 0)
  os.dup2(output_fd, 1)
  os.dup2(output_fd, 2)

  if devnull_fd > 2:
    utils_wrapper.CloseFdNoError(devnull_fd)

  if output_close and output_fd > 2:
    utils_wrapper.CloseFdNoError(output_fd)


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
  if _no_fork:
    raise errors.ProgrammerError("utils.StartDaemon() called with fork()"
                                 " disabled")

  if output and not (bool(output) ^ (output_fd is not None)):
    raise errors.ProgrammerError("Only one of 'output' and 'output_fd' can be"
                                 " specified")

  if isinstance(cmd, str):
    cmd = ["/bin/sh", "-c", cmd]

  strcmd = utils_text.ShellQuoteArgs(cmd)

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
            # Try to start child process, will either execve or exit on failure.
            _StartDaemonChild(errpipe_read, errpipe_write,
                              pidpipe_read, pidpipe_write,
                              cmd, cmd_env, cwd,
                              output, output_fd, pidfile)
        finally:
          utils_wrapper.CloseFdNoError(errpipe_write)

        # Wait for daemon to be started (or an error message to
        # arrive) and read up to 100 KB as an error message
        errormsg = utils_wrapper.RetryOnSignal(os.read, errpipe_read,
                                               100 * 1024).decode("utf-8")
      finally:
        utils_wrapper.CloseFdNoError(errpipe_read)
    finally:
      utils_wrapper.CloseFdNoError(pidpipe_write)

    # Read up to 128 bytes for PID
    pidtext = utils_wrapper.RetryOnSignal(os.read, pidpipe_read, 128)
  finally:
    utils_wrapper.CloseFdNoError(pidpipe_read)

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
  except (ValueError, TypeError) as err:
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
    utils_wrapper.CloseFdNoError(errpipe_read)
    utils_wrapper.CloseFdNoError(pidpipe_read)

    # First child process
    SetupDaemonEnv()

    # And fork for the second time
    pid = os.fork()
    if pid != 0:
      # Exit first child process
      os._exit(0) # pylint: disable=W0212

    # Make sure pipe is closed on execv* (and thereby notifies
    # original process)
    utils_wrapper.SetCloseOnExecFlag(errpipe_write, True)

    # List of file descriptors to be left open
    noclose_fds = [errpipe_write]

    # Open PID file
    if pidfile:
      fd_pidfile = utils_io.WritePidFile(pidfile)

      # Keeping the file open to hold the lock
      noclose_fds.append(fd_pidfile)

      utils_wrapper.SetCloseOnExecFlag(fd_pidfile, False)
    else:
      fd_pidfile = None

    SetupDaemonFDs(output, fd_output)

    # Send daemon PID to parent
    utils_wrapper.RetryOnSignal(os.write, pidpipe_write,
                                b"%d" % os.getpid())

    # Close all file descriptors except stdio and error message pipe
    CloseFDs(noclose_fds=noclose_fds)

    # Change working directory
    os.chdir(cwd)

    if env is None:
      os.execvp(args[0], args)
    else:
      os.execvpe(args[0], args, env)
  except: # pylint: disable=W0702
    try:
      # Report errors to original process
      WriteErrorToFD(errpipe_write, str(sys.exc_info()[1]))
    except: # pylint: disable=W0702
      # Ignore errors in error handling
      pass

  os._exit(1) # pylint: disable=W0212


def WriteErrorToFD(fd, err):
  """Possibly write an error message to a fd.

  @type fd: None or int (file descriptor)
  @param fd: if not None, the error will be written to this fd
  @param err: string, the error message

  """
  if fd is None:
    return

  if not err:
    err = "<unknown error>"

  utils_wrapper.RetryOnSignal(os.write, fd, err.encode("utf-8"))


def _CheckIfAlive(child):
  """Raises L{utils_retry.RetryAgain} if child is still alive.

  @raises utils_retry.RetryAgain: If child is still alive

  """
  if child.poll() is None:
    raise utils_retry.RetryAgain()


def _WaitForProcess(child, timeout):
  """Waits for the child to terminate or until we reach timeout.

  """
  try:
    utils_retry.Retry(_CheckIfAlive, (1.0, 1.2, 5.0), max(0, timeout),
                      args=[child])
  except utils_retry.RetryTimeout:
    pass


def _RunCmdPipe(cmd, env, via_shell, cwd, interactive, timeout, noclose_fds,
                input_fd, postfork_fn=None,
                _linger_timeout=constants.CHILD_LINGER_TIMEOUT):
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
  @type timeout: int
  @param timeout: Timeout after the programm gets terminated
  @type noclose_fds: list
  @param noclose_fds: list of additional (fd >=3) file descriptors to leave
                      open for the child process
  @type input_fd: C{file}-like object or numeric file descriptor
  @param input_fd: File descriptor for process' standard input
  @type postfork_fn: Callable receiving PID as parameter
  @param postfork_fn: Function run after fork but before timeout
  @rtype: tuple
  @return: (out, err, status)

  """
  # pylint: disable=R0101
  poller = select.poll()

  if interactive:
    stderr = None
    stdout = None
  else:
    stderr = subprocess.PIPE
    stdout = subprocess.PIPE

  if input_fd:
    stdin = input_fd
  elif interactive:
    stdin = None
  else:
    stdin = subprocess.PIPE

  if noclose_fds:
    pass_fds = noclose_fds
  else:
    pass_fds = []

  child = subprocess.Popen(cmd, shell=via_shell,
                           stderr=stderr,
                           stdout=stdout,
                           stdin=stdin,
                           pass_fds=pass_fds,
                           env=env,
                           cwd=cwd,
                           encoding="utf-8")

  if postfork_fn:
    postfork_fn(child.pid)

  out = StringIO()
  err = StringIO()

  linger_timeout = None

  if timeout is None:
    poll_timeout = None
  else:
    poll_timeout = utils_algo.RunningTimeout(timeout, True).Remaining

  msg_timeout = ("Command %s (%d) run into execution timeout, terminating" %
                 (cmd, child.pid))
  msg_linger = ("Command %s (%d) run into linger timeout, killing" %
                (cmd, child.pid))

  timeout_action = _TIMEOUT_NONE

  # subprocess: "If the stdin argument is PIPE, this attribute is a file object
  # that provides input to the child process. Otherwise, it is None."
  assert (stdin == subprocess.PIPE) ^ (child.stdin is None), \
    "subprocess' stdin did not behave as documented"

  if not interactive:
    if child.stdin is not None:
      child.stdin.close()
    poller.register(child.stdout, select.POLLIN)
    poller.register(child.stderr, select.POLLIN)
    fdmap = {
      child.stdout.fileno(): (out, child.stdout),
      child.stderr.fileno(): (err, child.stderr),
      }
    for fd in fdmap:
      utils_wrapper.SetNonblockFlag(fd, True)

    while fdmap:
      if poll_timeout:
        pt = poll_timeout() * 1000
        if pt < 0:
          if linger_timeout is None:
            logging.warning(msg_timeout)
            if child.poll() is None:
              timeout_action = _TIMEOUT_TERM
              utils_wrapper.IgnoreProcessNotFound(os.kill, child.pid,
                                                  signal.SIGTERM)
            linger_timeout = \
              utils_algo.RunningTimeout(_linger_timeout, True).Remaining
          pt = linger_timeout() * 1000
          if pt < 0:
            break
      else:
        pt = None

      pollresult = utils_wrapper.RetryOnSignal(poller.poll, pt)

      for fd, event in pollresult:
        if event & select.POLLIN or event & select.POLLPRI:
          data = fdmap[fd][1].read()
          # no data from read signifies EOF (the same as POLLHUP)
          if not data:
            poller.unregister(fd)
            fdmap[fd][1].close()
            del fdmap[fd]
            continue
          fdmap[fd][0].write(data)
        if (event & select.POLLNVAL or event & select.POLLHUP or
            event & select.POLLERR):
          poller.unregister(fd)
          fdmap[fd][1].close()
          del fdmap[fd]

    if fdmap:
      for (_, handle) in fdmap.values():
        handle.close()

  if timeout is not None:
    assert callable(poll_timeout)

    # We have no I/O left but it might still run
    if child.poll() is None:
      _WaitForProcess(child, poll_timeout())

    # Terminate if still alive after timeout
    if child.poll() is None:
      if linger_timeout is None:
        logging.warning(msg_timeout)
        timeout_action = _TIMEOUT_TERM
        utils_wrapper.IgnoreProcessNotFound(os.kill, child.pid, signal.SIGTERM)
        lt = _linger_timeout
      else:
        lt = linger_timeout()
      _WaitForProcess(child, lt)

    # Okay, still alive after timeout and linger timeout? Kill it!
    if child.poll() is None:
      timeout_action = _TIMEOUT_KILL
      logging.warning(msg_linger)
      utils_wrapper.IgnoreProcessNotFound(os.kill, child.pid, signal.SIGKILL)

  out = out.getvalue()
  err = err.getvalue()

  status = child.wait()
  return out, err, status, timeout_action


def _RunCmdFile(cmd, env, via_shell, output, cwd, noclose_fds):
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
  @type noclose_fds: list
  @param noclose_fds: list of additional (fd >=3) file descriptors to leave
                      open for the child process
  @rtype: int
  @return: the exit status

  """
  fh = open(output, "a")

  if noclose_fds:
    pass_fds = noclose_fds
  else:
    pass_fds = []

  try:
    child = subprocess.Popen(cmd, shell=via_shell,
                             stderr=subprocess.STDOUT,
                             stdout=fh,
                             stdin=subprocess.PIPE,
                             pass_fds=pass_fds,
                             env=env,
                             cwd=cwd,
                             encoding="utf-8")

    child.stdin.close()
    status = child.wait()
  finally:
    fh.close()
  return status


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
    dir_contents = utils_io.ListVisibleFiles(dir_name)
  except OSError as err:
    logging.warning("RunParts: skipping %s (cannot list: %s)", dir_name, err)
    return rr

  for relname in sorted(dir_contents):
    fname = utils_io.PathJoin(dir_name, relname)
    if not (constants.EXT_PLUGIN_MASK.match(relname) is not None and
            utils_wrapper.IsExecutable(fname)):
      rr.append((relname, constants.RUNPARTS_SKIP, None))
    else:
      try:
        result = RunCmd([fname], env=env, reset_env=reset_env)
      except Exception as err: # pylint: disable=W0703
        rr.append((relname, constants.RUNPARTS_ERR, str(err)))
      else:
        rr.append((relname, constants.RUNPARTS_RUN, result))

  return rr


def _GetProcStatusPath(pid):
  """Returns the path for a PID's proc status file.

  @type pid: int
  @param pid: Process ID
  @rtype: string

  """
  return "/proc/%d/status" % pid


def GetProcCmdline(pid):
  """Returns the command line of a pid as a list of arguments.

  @type pid: int
  @param pid: Process ID
  @rtype: list of string

  @raise EnvironmentError: If the process does not exist

  """
  proc_path = "/proc/%d/cmdline" % pid
  with open(proc_path, 'r') as f:
    nulled_cmdline = f.read()
  # Individual arguments are separated by nul chars in the contents of the proc
  # file
  return nulled_cmdline.split('\x00')


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
    except EnvironmentError as err:
      if err.errno in (errno.ENOENT, errno.ENOTDIR):
        return False
      elif err.errno == errno.EINVAL:
        raise utils_retry.RetryAgain(err)
      raise

  assert isinstance(pid, int), "pid must be an integer"
  if pid <= 0:
    return False

  # /proc in a multiprocessor environment can have strange behaviors.
  # Retry the os.stat a few times until we get a good result.
  try:
    return utils_retry.Retry(_TryStat, (0.01, 1.5, 0.1), 0.5,
                             args=[_GetProcStatusPath(pid)])
  except utils_retry.RetryTimeout as err:
    err.RaiseInner()


def IsDaemonAlive(name):
  """Determines whether a daemon is alive

  @type name: string
  @param name: daemon name

  @rtype: boolean
  @return: True if daemon is running, False otherwise

  """
  return IsProcessAlive(utils_io.ReadPidFile(utils_io.DaemonPidFileName(name)))


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
    proc_status = utils_io.ReadFile(status_path)
  except EnvironmentError as err:
    # In at least one case, reading /proc/$pid/status failed with ESRCH.
    if err.errno in (errno.ENOENT, errno.ENOTDIR, errno.EINVAL, errno.ESRCH):
      return False
    raise

  sigcgt = _GetProcStatusField(proc_status, "SigCgt")
  if sigcgt is None:
    raise RuntimeError("%s is missing 'SigCgt' field" % status_path)

  # Now check whether signal is handled
  return signum in _ParseSigsetT(sigcgt)


def Daemonize(logfile):
  """Daemonize the current process.

  This detaches the current process from the controlling terminal and
  runs it in the background as a daemon.

  @type logfile: str
  @param logfile: the logfile to which we should redirect stdout/stderr
  @rtype: tuple; (int, callable)
  @return: File descriptor of pipe(2) which must be closed to notify parent
    process and a callable to reopen log files

  """
  # pylint: disable=W0212
  # yes, we really want os._exit

  # TODO: do another attempt to merge Daemonize and StartDaemon, or at
  # least abstract the pipe functionality between them

  # Create pipe for sending error messages
  (rpipe, wpipe) = os.pipe()

  # this might fail
  pid = os.fork()
  if pid == 0:  # The first child.
    SetupDaemonEnv()

    # this might fail
    pid = os.fork() # Fork a second child.
    if pid == 0:  # The second child.
      utils_wrapper.CloseFdNoError(rpipe)
    else:
      # exit() or _exit()?  See below.
      os._exit(0) # Exit parent (the first child) of the second child.
  else:
    utils_wrapper.CloseFdNoError(wpipe)
    # Wait for daemon to be started (or an error message to
    # arrive) and read up to 100 KB as an error message
    errormsg = utils_wrapper.RetryOnSignal(os.read, rpipe, 100 * 1024)
    if errormsg:
      sys.stderr.write("Error when starting daemon process: %r\n" % errormsg)
      rcode = 1
    else:
      rcode = 0
    os._exit(rcode) # Exit parent of the first child.

  reopen_fn = compat.partial(SetupDaemonFDs, logfile, None)

  # Open logs for the first time
  reopen_fn()

  return (wpipe, reopen_fn)


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
    if utils_wrapper.IgnoreProcessNotFound(os.kill, pid, signal_) and wait:
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
      raise utils_retry.RetryAgain()

    if result_pid > 0:
      return

    raise utils_retry.RetryAgain()

  try:
    # Wait up to $timeout seconds
    utils_retry.Retry(_CheckProcess, (0.01, 1.5, 0.1), timeout)
  except utils_retry.RetryTimeout:
    pass

  if IsProcessAlive(pid):
    # Kill process if it's still alive
    _helper(pid, signal.SIGKILL, waitpid)


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
      utils_wrapper.ResetTempfileModule()

      # Call function
      result = int(bool(fn(*args)))
      assert result in (0, 1)
    except: # pylint: disable=W0702
      logging.exception("Error while calling function in separate process")
      # 0 and 1 are reserved for the return value
      result = 33

    os._exit(result) # pylint: disable=W0212

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

  # Iterate through and close all file descriptors (except the standard ones)
  for fd in range(3, MAXFD):
    if noclose_fds and fd in noclose_fds:
      continue
    utils_wrapper.CloseFdNoError(fd)
