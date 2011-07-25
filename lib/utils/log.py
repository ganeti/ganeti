#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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

"""Utility functions for logging.

"""

import os.path
import logging
import logging.handlers

from ganeti import constants
from ganeti import compat


class _ReopenableLogHandler(logging.handlers.BaseRotatingHandler):
  """Log handler with ability to reopen log file on request.

  In combination with a SIGHUP handler this class can reopen the log file on
  user request.

  """
  def __init__(self, filename):
    """Initializes this class.

    @type filename: string
    @param filename: Path to logfile

    """
    logging.handlers.BaseRotatingHandler.__init__(self, filename, "a")

    assert self.encoding is None, "Encoding not supported for logging"
    assert not hasattr(self, "_reopen"), "Base class has '_reopen' attribute"

    self._reopen = False

  def shouldRollover(self, _): # pylint: disable-msg=C0103
    """Determine whether log file should be reopened.

    """
    return self._reopen or not self.stream

  def doRollover(self): # pylint: disable-msg=C0103
    """Reopens the log file.

    """
    if self.stream:
      self.stream.flush()
      self.stream.close()
      self.stream = None

    # Reopen file
    # TODO: Handle errors?
    self.stream = open(self.baseFilename, "a")

    # Don't reopen on the next message
    self._reopen = False

  def RequestReopen(self):
    """Register a request to reopen the file.

    The file will be reopened before writing the next log record.

    """
    self._reopen = True


def _LogErrorsToConsole(base):
  """Create wrapper class writing errors to console.

  This needs to be in a function for unittesting.

  """
  class wrapped(base): # pylint: disable-msg=C0103
    """Log handler that doesn't fallback to stderr.

    When an error occurs while writing on the logfile, logging.FileHandler
    tries to log on stderr. This doesn't work in Ganeti since stderr is
    redirected to a logfile. This class avoids failures by reporting errors to
    /dev/console.

    """
    def __init__(self, console, *args, **kwargs):
      """Initializes this class.

      @type console: file-like object or None
      @param console: Open file-like object for console

      """
      base.__init__(self, *args, **kwargs)
      assert not hasattr(self, "_console")
      self._console = console

    def handleError(self, record): # pylint: disable-msg=C0103
      """Handle errors which occur during an emit() call.

      Try to handle errors with FileHandler method, if it fails write to
      /dev/console.

      """
      try:
        base.handleError(record)
      except Exception: # pylint: disable-msg=W0703
        if self._console:
          try:
            # Ignore warning about "self.format", pylint: disable-msg=E1101
            self._console.write("Cannot log message:\n%s\n" %
                                self.format(record))
          except Exception: # pylint: disable-msg=W0703
            # Log handler tried everything it could, now just give up
            pass

  return wrapped


#: Custom log handler for writing to console with a reopenable handler
_LogHandler = _LogErrorsToConsole(_ReopenableLogHandler)


def _GetLogFormatter(program, multithreaded, debug, syslog):
  """Build log formatter.

  @param program: Program name
  @param multithreaded: Whether to add thread name to log messages
  @param debug: Whether to enable debug messages
  @param syslog: Whether the formatter will be used for syslog

  """
  parts = []

  if syslog:
    parts.append(program + "[%(process)d]:")
  else:
    parts.append("%(asctime)s: " + program + " pid=%(process)d")

  if multithreaded:
    if syslog:
      parts.append(" (%(threadName)s)")
    else:
      parts.append("/%(threadName)s")

  # Add debug info for non-syslog loggers
  if debug and not syslog:
    parts.append(" %(module)s:%(lineno)s")

  # Ses, we do want the textual level, as remote syslog will probably lose the
  # error level, and it's easier to grep for it.
  parts.append(" %(levelname)s %(message)s")

  return logging.Formatter("".join(parts))


def _ReopenLogFiles(handlers):
  """Wrapper for reopening all log handler's files in a sequence.

  """
  for handler in handlers:
    handler.RequestReopen()
  logging.info("Received request to reopen log files")


def SetupLogging(logfile, program, debug=0, stderr_logging=False,
                 multithreaded=False, syslog=constants.SYSLOG_USAGE,
                 console_logging=False, root_logger=None):
  """Configures the logging module.

  @type logfile: str
  @param logfile: the filename to which we should log
  @type program: str
  @param program: the name under which we should log messages
  @type debug: integer
  @param debug: if greater than zero, enable debug messages, otherwise
      only those at C{INFO} and above level
  @type stderr_logging: boolean
  @param stderr_logging: whether we should also log to the standard error
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
  @type root_logger: logging.Logger
  @param root_logger: Root logger to use (for unittests)
  @raise EnvironmentError: if we can't open the log file and
      syslog/stderr logging is disabled
  @rtype: callable
  @return: Function reopening all open log files when called

  """
  progname = os.path.basename(program)

  formatter = _GetLogFormatter(progname, multithreaded, debug, False)
  syslog_fmt = _GetLogFormatter(progname, multithreaded, debug, True)

  reopen_handlers = []

  if root_logger is None:
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
    syslog_handler.setFormatter(syslog_fmt)
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
        logfile_handler = _LogHandler(open(constants.DEV_CONSOLE, "a"),
                                      logfile)
      else:
        logfile_handler = _ReopenableLogHandler(logfile)

      logfile_handler.setFormatter(formatter)
      if debug:
        logfile_handler.setLevel(logging.DEBUG)
      else:
        logfile_handler.setLevel(logging.INFO)
      root_logger.addHandler(logfile_handler)
      reopen_handlers.append(logfile_handler)
    except EnvironmentError:
      if stderr_logging or syslog == constants.SYSLOG_YES:
        logging.exception("Failed to enable logging to file '%s'", logfile)
      else:
        # we need to re-raise the exception
        raise

  return compat.partial(_ReopenLogFiles, reopen_handlers)
