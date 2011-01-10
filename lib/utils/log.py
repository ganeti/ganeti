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

import logging
import logging.handlers

from ganeti import constants


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
