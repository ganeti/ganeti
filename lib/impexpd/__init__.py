#
#

# Copyright (C) 2010 Google Inc.
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


"""Classes and functions for import/export daemon.

"""

import re
import socket
from cStringIO import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import utils


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

SOCAT_LOG_IGNORE = frozenset([
  SOCAT_LOG_DEBUG,
  SOCAT_LOG_INFO,
  SOCAT_LOG_NOTICE,
  ])

#: Buffer size: at most this many bytes are transferred at once
BUFSIZE = 1024 * 1024

# Common options for socat
SOCAT_TCP_OPTS = ["keepalive", "keepidle=60", "keepintvl=10", "keepcnt=5"]
SOCAT_OPENSSL_OPTS = ["verify=1", "cipher=HIGH", "method=TLSv1"]

(PROG_OTHER,
 PROG_SOCAT) = range(1, 3)
PROG_ALL = frozenset([
  PROG_OTHER,
  PROG_SOCAT,
  ])


class CommandBuilder(object):
  def __init__(self, mode, opts, socat_stderr_fd):
    """Initializes this class.

    @param mode: Daemon mode (import or export)
    @param opts: Options object
    @type socat_stderr_fd: int
    @param socat_stderr_fd: File descriptor socat should write its stderr to

    """
    self._opts = opts
    self._mode = mode
    self._socat_stderr_fd = socat_stderr_fd

  @staticmethod
  def GetBashCommand(cmd):
    """Prepares a command to be run in Bash.

    """
    return ["bash", "-o", "errexit", "-o", "pipefail", "-c", cmd]

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
      addr1 = ["stdin"]
      addr2 = [
        "OPENSSL:%s:%s" % (self._opts.host, self._opts.port),

        # How long to wait per connection attempt
        "connect-timeout=%s" % self._opts.connect_timeout,

        # Retry a few times before giving up to connect (once per second)
        "retry=%s" % self._opts.connect_retries,
        "intervall=1",
        ] + common_addr_opts

    else:
      raise errors.GenericError("Invalid mode '%s'" % self._mode)

    for i in [addr1, addr2]:
      for value in i:
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

      ",".join(addr1), ",".join(addr2)
      ]

  def _GetTransportCommand(self):
    """Returns the command for the transport part of the daemon.

    """
    socat_cmd = ("%s 2>&%d" %
                 (utils.ShellQuoteArgs(self._GetSocatCommand()),
                  self._socat_stderr_fd))

    compr = self._opts.compress

    assert compr in constants.IEC_ALL

    if self._mode == constants.IEM_IMPORT:
      if compr == constants.IEC_GZIP:
        transport_cmd = "%s | gunzip -c" % socat_cmd
      else:
        transport_cmd = socat_cmd
    elif self._mode == constants.IEM_EXPORT:
      if compr == constants.IEC_GZIP:
        transport_cmd = "gzip -c | %s" % socat_cmd
      else:
        transport_cmd = socat_cmd
    else:
      raise errors.GenericError("Invalid mode '%s'" % self._mode)

    # TODO: Use "dd" to measure processed data (allows to give an ETA)

    # TODO: Run transport as separate user
    # The transport uses its own shell to simplify running it as a separate user
    # in the future.
    return self.GetBashCommand(transport_cmd)

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
  # TODO: Implement IPv6 support
  if family != socket.AF_INET:
    raise errors.GenericError("Address family %r not supported" % family)

  try:
    packed_address = socket.inet_pton(family, address)
  except socket.error:
    raise errors.GenericError("Invalid address %r for family %s" %
                              (address, family))

  return (socket.inet_ntop(family, packed_address), port)


class ChildIOProcessor(object):
  def __init__(self, debug, status_file, logger):
    """Initializes this class.

    """
    self._debug = debug
    self._status_file = status_file
    self._logger = logger

    self._splitter = dict([(prog, utils.LineSplitter(self._ProcessOutput, prog))
                           for prog in PROG_ALL])

  def GetLineSplitter(self, prog):
    """Returns the line splitter for a program.

    """
    return self._splitter[prog]

  def FlushAll(self):
    """Flushes all line splitters.

    """
    for ls in self._splitter.itervalues():
      ls.flush()

  def CloseAll(self):
    """Closes all line splitters.

    """
    for ls in self._splitter.itervalues():
      ls.close()
    self._splitter.clear()

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
          status_file.SetConnected()
          return True

    return False
