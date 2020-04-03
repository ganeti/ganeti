#
#

# Copyright (C) 2010 Google Inc.
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


"""Classes and functions for import/export daemon.

"""

import os
import re
import socket
import logging
import signal
import errno
import time
from io import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import netutils
from ganeti import compat


#: Used to recognize point at which socat(1) starts to listen on its socket.
#: The local address is required for the remote peer to connect (in particular
#: the port number).
LISTENING_RE = re.compile(r"^listening on\s+"
                          r"AF=(?P<family>\d+)\s+"
                          r"(?P<address>.+):(?P<port>\d+)$", re.I)

#: Used to recognize point at which socat(1) is sending data over the wire
TRANSFER_LOOP_RE = re.compile(r"^starting data transfer loop with FDs\s+.*$",
                              re.I)

SOCAT_LOG_DEBUG = "D"
SOCAT_LOG_INFO = "I"
SOCAT_LOG_NOTICE = "N"
SOCAT_LOG_WARNING = "W"
SOCAT_LOG_ERROR = "E"
SOCAT_LOG_FATAL = "F"

SOCAT_LOG_IGNORE = compat.UniqueFrozenset([
  SOCAT_LOG_DEBUG,
  SOCAT_LOG_INFO,
  SOCAT_LOG_NOTICE,
  ])

#: Used to parse GNU dd(1) statistics
DD_INFO_RE = re.compile(r"^(?P<bytes>\d+)\s*byte(?:|s)\s.*\scopied,\s*"
                        r"(?P<seconds>[\d.]+)\s*s(?:|econds),.*$", re.I)

#: Used to ignore "N+N records in/out" on dd(1)'s stderr
DD_STDERR_IGNORE = re.compile(r"^\d+\+\d+\s*records\s+(?:in|out)$", re.I)

#: Signal upon which dd(1) will print statistics (on some platforms, SIGINFO is
#: unavailable and SIGUSR1 is used instead)
DD_INFO_SIGNAL = getattr(signal, "SIGINFO", signal.SIGUSR1)

#: Buffer size: at most this many bytes are transferred at once
BUFSIZE = 1024 * 1024

# Common options for socat
SOCAT_TCP_OPTS = ["keepalive", "keepidle=60", "keepintvl=10", "keepcnt=5"]
SOCAT_OPENSSL_OPTS = ["verify=1", "cipher=%s" % constants.OPENSSL_CIPHERS]

if constants.SOCAT_USE_COMPRESS:
  # Disables all compression in by OpenSSL. Only supported in patched versions
  # of socat (as of November 2010). See INSTALL for more information.
  SOCAT_OPENSSL_OPTS.append("compress=none")

SOCAT_OPTION_MAXLEN = 400

(PROG_OTHER,
 PROG_SOCAT,
 PROG_DD,
 PROG_DD_PID,
 PROG_EXP_SIZE) = range(1, 6)

PROG_ALL = compat.UniqueFrozenset([
  PROG_OTHER,
  PROG_SOCAT,
  PROG_DD,
  PROG_DD_PID,
  PROG_EXP_SIZE,
  ])


class CommandBuilder(object):
  _SOCAT_VERSION = (0,)

  def __init__(self, mode, opts, socat_stderr_fd, dd_stderr_fd, dd_pid_fd):
    """Initializes this class.

    @param mode: Daemon mode (import or export)
    @param opts: Options object
    @type socat_stderr_fd: int
    @param socat_stderr_fd: File descriptor socat should write its stderr to
    @type dd_stderr_fd: int
    @param dd_stderr_fd: File descriptor dd should write its stderr to
    @type dd_pid_fd: int
    @param dd_pid_fd: File descriptor the child should write dd's PID to

    """
    self._opts = opts
    self._mode = mode
    self._socat_stderr_fd = socat_stderr_fd
    self._dd_stderr_fd = dd_stderr_fd
    self._dd_pid_fd = dd_pid_fd

    assert (self._opts.magic is None or
            constants.IE_MAGIC_RE.match(self._opts.magic))

  @staticmethod
  def GetBashCommand(cmd):
    """Prepares a command to be run in Bash.

    """
    return ["bash", "-o", "errexit", "-o", "pipefail", "-c", cmd]

  @classmethod
  def _GetSocatVersion(cls):
    """Returns the socat version, as a tuple of ints.

    The version is memoized in a class variable for future use.
    """
    if cls._SOCAT_VERSION > (0,):
      return cls._SOCAT_VERSION

    socat = utils.RunCmd([constants.SOCAT_PATH, "-V"])
    # No need to check for errors here. If -V is not there, socat is really
    # old. Any other failure will be handled when running the actual socat
    # command.
    for line in socat.output.splitlines():
      match = re.match(r"socat version ((\d+\.)*(\d+))", line)
      if match:
        try:
          cls._SOCAT_VERSION = tuple(int(x) for x in match.group(1).split('.'))
        except TypeError:
          pass
        break
    return cls._SOCAT_VERSION

  def _GetSocatCommand(self):
    """Returns the socat command.

    """
    common_addr_opts = SOCAT_TCP_OPTS + SOCAT_OPENSSL_OPTS + [
      "key=%s" % self._opts.key,
      "cert=%s" % self._opts.cert,
      "cafile=%s" % self._opts.ca,
      ]

    if self._opts.bind is not None:
      common_addr_opts.append("bind=%s" % self._opts.bind)

    assert not (self._opts.ipv4 and self._opts.ipv6)

    if self._opts.ipv4:
      common_addr_opts.append("pf=ipv4")
    elif self._opts.ipv6:
      common_addr_opts.append("pf=ipv6")

    if self._mode == constants.IEM_IMPORT:
      if self._opts.port is None:
        port = 0
      else:
        port = self._opts.port

      addr1 = [
        "OPENSSL-LISTEN:%s" % port,
        "reuseaddr",

        # Retry to listen if connection wasn't established successfully, up to
        # 100 times a second. Note that this still leaves room for DoS attacks.
        "forever",
        "intervall=0.01",
        ] + common_addr_opts
      addr2 = ["stdout"]

    elif self._mode == constants.IEM_EXPORT:
      if self._opts.host and netutils.IP6Address.IsValid(self._opts.host):
        host = "[%s]" % self._opts.host
      else:
        host = self._opts.host

      addr1 = ["stdin"]
      addr2 = [
        "OPENSSL:%s:%s" % (host, self._opts.port),

        # How long to wait per connection attempt
        "connect-timeout=%s" % self._opts.connect_timeout,

        # Retry a few times before giving up to connect (once per second)
        "retry=%s" % self._opts.connect_retries,
        "intervall=1",
        ] + common_addr_opts

      # For socat versions >= 1.7.3, we need to also specify
      # openssl-commonname, otherwise server certificate verification will
      # fail.
      if self._GetSocatVersion() >= (1, 7, 3):
        addr2 += ["openssl-commonname=%s" % constants.X509_CERT_CN]

    else:
      raise errors.GenericError("Invalid mode '%s'" % self._mode)

    for i in [addr1, addr2]:
      for value in i:
        if len(value) > SOCAT_OPTION_MAXLEN:
          raise errors.GenericError("Socat option longer than %s"
                                    " characters: %r" %
                                    (SOCAT_OPTION_MAXLEN, value))
        if "," in value:
          raise errors.GenericError("Comma not allowed in socat option"
                                    " value: %r" % value)

    return [
      constants.SOCAT_PATH,

      # Log to stderr
      "-ls",

      # Log level
      "-d", "-d",

      # Buffer size
      "-b%s" % BUFSIZE,

      # Unidirectional mode, the first address is only used for reading, and the
      # second address is only used for writing
      "-u",

      ",".join(addr1), ",".join(addr2),
      ]

  def _GetMagicCommand(self):
    """Returns the command to read/write the magic value.

    """
    if not self._opts.magic:
      return None

    # Prefix to ensure magic isn't interpreted as option to "echo"
    magic = "M=%s" % self._opts.magic

    cmd = StringIO()

    if self._mode == constants.IEM_IMPORT:
      cmd.write("{ ")
      cmd.write(utils.ShellQuoteArgs(["read", "-n", str(len(magic)), "magic"]))
      cmd.write(" && ")
      cmd.write("if test \"$magic\" != %s; then" % utils.ShellQuote(magic))
      cmd.write(" echo %s >&2;" % utils.ShellQuote("Magic value mismatch"))
      cmd.write(" exit 1;")
      cmd.write("fi;")
      cmd.write(" }")

    elif self._mode == constants.IEM_EXPORT:
      cmd.write(utils.ShellQuoteArgs(["echo", "-E", "-n", magic]))

    else:
      raise errors.GenericError("Invalid mode '%s'" % self._mode)

    return cmd.getvalue()

  def _GetDdCommand(self):
    """Returns the command for measuring throughput.

    """
    dd_cmd = StringIO()

    magic_cmd = self._GetMagicCommand()
    if magic_cmd:
      dd_cmd.write("{ ")
      dd_cmd.write(magic_cmd)
      dd_cmd.write(" && ")

    dd_cmd.write("{ ")
    # Setting LC_ALL since we want to parse the output and explicitly
    # redirecting stdin, as the background process (dd) would have
    # /dev/null as stdin otherwise
    dd_cmd.write("LC_ALL=C dd bs=%s <&0 2>&%d & pid=${!};" %
                 (BUFSIZE, self._dd_stderr_fd))
    # Send PID to daemon
    dd_cmd.write(" echo $pid >&%d;" % self._dd_pid_fd)
    # And wait for dd
    dd_cmd.write(" wait $pid;")
    dd_cmd.write(" }")

    if magic_cmd:
      dd_cmd.write(" }")

    return dd_cmd.getvalue()

  def _GetTransportCommand(self):
    """Returns the command for the transport part of the daemon.

    """
    socat_cmd = ("%s 2>&%d" %
                 (utils.ShellQuoteArgs(self._GetSocatCommand()),
                  self._socat_stderr_fd))
    dd_cmd = self._GetDdCommand()

    compr = self._opts.compress

    parts = []

    if self._mode == constants.IEM_IMPORT:
      parts.append(socat_cmd)

      if compr in [constants.IEC_GZIP, constants.IEC_GZIP_FAST,
                   constants.IEC_GZIP_SLOW, constants.IEC_LZOP]:
        utility_name = constants.IEC_COMPRESSION_UTILITIES.get(compr, compr)
        parts.append("%s -d -c" % utility_name)
      elif compr != constants.IEC_NONE:
        parts.append("%s -d" % compr)
      else:
        # No compression
        pass

      parts.append(dd_cmd)

    elif self._mode == constants.IEM_EXPORT:
      parts.append(dd_cmd)

      if compr in [constants.IEC_GZIP_SLOW, constants.IEC_LZOP]:
        utility_name = constants.IEC_COMPRESSION_UTILITIES.get(compr, compr)
        parts.append("%s -c" % utility_name)
      elif compr in [constants.IEC_GZIP_FAST, constants.IEC_GZIP]:
        parts.append("gzip -1 -c")
      elif compr != constants.IEC_NONE:
        parts.append(compr)
      else:
        # No compression
        pass

      parts.append(socat_cmd)

    else:
      raise errors.GenericError("Invalid mode '%s'" % self._mode)

    # TODO: Run transport as separate user
    # The transport uses its own shell to simplify running it as a separate user
    # in the future.
    return self.GetBashCommand(" | ".join(parts))

  def GetCommand(self):
    """Returns the complete child process command.

    """
    transport_cmd = self._GetTransportCommand()

    buf = StringIO()

    if self._opts.cmd_prefix:
      buf.write(self._opts.cmd_prefix)
      buf.write(" ")

    buf.write(utils.ShellQuoteArgs(transport_cmd))

    if self._opts.cmd_suffix:
      buf.write(" ")
      buf.write(self._opts.cmd_suffix)

    return self.GetBashCommand(buf.getvalue())


def _VerifyListening(family, address, port):
  """Verify address given as listening address by socat.

  """
  if family not in (socket.AF_INET, socket.AF_INET6):
    raise errors.GenericError("Address family %r not supported" % family)

  if (family == socket.AF_INET6 and address.startswith("[") and
      address.endswith("]")):
    address = address.lstrip("[").rstrip("]")

  try:
    packed_address = socket.inet_pton(family, address)
  except socket.error:
    raise errors.GenericError("Invalid address %r for family %s" %
                              (address, family))

  return (socket.inet_ntop(family, packed_address), port)


class ChildIOProcessor(object):
  def __init__(self, debug, status_file, logger, throughput_samples, exp_size):
    """Initializes this class.

    """
    self._debug = debug
    self._status_file = status_file
    self._logger = logger

    self._splitter = dict([(prog, utils.LineSplitter(self._ProcessOutput, prog))
                           for prog in PROG_ALL])

    self._dd_pid = None
    self._dd_ready = False
    self._dd_tp_samples = throughput_samples
    self._dd_progress = []

    # Expected size of transferred data
    self._exp_size = exp_size

  def GetLineSplitter(self, prog):
    """Returns the line splitter for a program.

    """
    return self._splitter[prog]

  def FlushAll(self):
    """Flushes all line splitters.

    """
    for ls in self._splitter.values():
      ls.flush()

  def CloseAll(self):
    """Closes all line splitters.

    """
    for ls in self._splitter.values():
      ls.close()
    self._splitter.clear()

  def NotifyDd(self):
    """Tells dd(1) to write statistics.

    """
    if self._dd_pid is None:
      # Can't notify
      return False

    if not self._dd_ready:
      # There's a race condition between starting the program and sending
      # signals.  The signal handler is only registered after some time, so we
      # have to check whether the program is ready. If it isn't, sending a
      # signal will invoke the default handler (and usually abort the program).
      if not utils.IsProcessHandlingSignal(self._dd_pid, DD_INFO_SIGNAL):
        logging.debug("dd is not yet ready for signal %s", DD_INFO_SIGNAL)
        return False

      logging.debug("dd is now handling signal %s", DD_INFO_SIGNAL)
      self._dd_ready = True

    logging.debug("Sending signal %s to PID %s", DD_INFO_SIGNAL, self._dd_pid)
    try:
      os.kill(self._dd_pid, DD_INFO_SIGNAL)
    except EnvironmentError as err:
      if err.errno != errno.ESRCH:
        raise

      # Process no longer exists
      logging.debug("dd exited")
      self._dd_pid = None

    return True

  def _ProcessOutput(self, line, prog):
    """Takes care of child process output.

    @type line: string
    @param line: Child output line
    @type prog: number
    @param prog: Program from which the line originates

    """
    force_update = False
    forward_line = line

    if prog == PROG_SOCAT:
      level = None
      parts = line.split(None, 4)

      if len(parts) == 5:
        (_, _, _, level, msg) = parts

        force_update = self._ProcessSocatOutput(self._status_file, level, msg)

        if self._debug or (level and level not in SOCAT_LOG_IGNORE):
          forward_line = "socat: %s %s" % (level, msg)
        else:
          forward_line = None
      else:
        forward_line = "socat: %s" % line

    elif prog == PROG_DD:
      (should_forward, force_update) = self._ProcessDdOutput(line)

      if should_forward or self._debug:
        forward_line = "dd: %s" % line
      else:
        forward_line = None

    elif prog == PROG_DD_PID:
      if self._dd_pid:
        raise RuntimeError("dd PID reported more than once")
      logging.debug("Received dd PID %r", line)
      self._dd_pid = int(line)
      forward_line = None

    elif prog == PROG_EXP_SIZE:
      logging.debug("Received predicted size %r", line)
      forward_line = None

      if line:
        try:
          exp_size = utils.BytesToMebibyte(int(line))
        except (ValueError, TypeError) as err:
          logging.error("Failed to convert predicted size %r to number: %s",
                        line, err)
          exp_size = None
      else:
        exp_size = None

      self._exp_size = exp_size

    if forward_line:
      self._logger.info(forward_line)
      self._status_file.AddRecentOutput(forward_line)

    self._status_file.Update(force_update)

  @staticmethod
  def _ProcessSocatOutput(status_file, level, msg):
    """Interprets socat log output.

    """
    if level == SOCAT_LOG_NOTICE:
      if status_file.GetListenPort() is None:
        # TODO: Maybe implement timeout to not listen forever
        m = LISTENING_RE.match(msg)
        if m:
          (_, port) = _VerifyListening(int(m.group("family")),
                                       m.group("address"),
                                       int(m.group("port")))

          status_file.SetListenPort(port)
          return True

      if not status_file.GetConnected():
        m = TRANSFER_LOOP_RE.match(msg)
        if m:
          logging.debug("Connection established")
          status_file.SetConnected()
          return True

    return False

  def _ProcessDdOutput(self, line):
    """Interprets a line of dd(1)'s output.

    """
    m = DD_INFO_RE.match(line)
    if m:
      seconds = float(m.group("seconds"))
      mbytes = utils.BytesToMebibyte(int(m.group("bytes")))
      self._UpdateDdProgress(seconds, mbytes)
      return (False, True)

    m = DD_STDERR_IGNORE.match(line)
    if m:
      # Ignore
      return (False, False)

    # Forward line
    return (True, False)

  def _UpdateDdProgress(self, seconds, mbytes):
    """Updates the internal status variables for dd(1) progress.

    @type seconds: float
    @param seconds: Timestamp of this update
    @type mbytes: float
    @param mbytes: Total number of MiB transferred so far

    """
    # Add latest sample
    self._dd_progress.append((seconds, mbytes))

    # Remove old samples
    del self._dd_progress[:-self._dd_tp_samples]

    # Calculate throughput
    throughput = _CalcThroughput(self._dd_progress)

    # Calculate percent and ETA
    percent = None
    eta = None

    if self._exp_size is not None:
      if self._exp_size != 0:
        percent = max(0, min(100, (100.0 * mbytes) / self._exp_size))

      if throughput:
        eta = max(0, float(self._exp_size - mbytes) / throughput)

    self._status_file.SetProgress(mbytes, throughput, percent, eta)


def _CalcThroughput(samples):
  """Calculates the throughput in MiB/second.

  @type samples: sequence
  @param samples: List of samples, each consisting of a (timestamp, mbytes)
                  tuple
  @rtype: float or None
  @return: Throughput in MiB/second

  """
  if len(samples) < 2:
    # Can't calculate throughput
    return None

  (start_time, start_mbytes) = samples[0]
  (end_time, end_mbytes) = samples[-1]

  return (float(end_mbytes) - start_mbytes) / (float(end_time) - start_time)
