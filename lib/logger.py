#
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


"""Logging for Ganeti

This module abstracts the logging handling away from the rest of the
Ganeti code. It offers some utility functions for easy logging.

"""

# pylint: disable-msg=W0603,C0103

import sys
import logging


def SetupLogging(logfile, debug=False, stderr_logging=False, program=""):
  """Configures the logging module.

  """
  fmt = "%(asctime)s: " + program + " "
  if debug:
    fmt += ("pid=%(process)d/%(threadName)s %(levelname)s"
           " %(module)s:%(lineno)s %(message)s")
  else:
    fmt += "pid=%(process)d %(levelname)s %(message)s"
  formatter = logging.Formatter(fmt)

  root_logger = logging.getLogger("")
  root_logger.setLevel(logging.NOTSET)

  if stderr_logging:
    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    if debug:
      stderr_handler.setLevel(logging.NOTSET)
    else:
      stderr_handler.setLevel(logging.CRITICAL)
    root_logger.addHandler(stderr_handler)

  # this can fail, if the logging directories are not setup or we have
  # a permisssion problem; in this case, it's best to log but ignore
  # the error if stderr_logging is True, and if false we re-raise the
  # exception since otherwise we could run but without any logs at all
  try:
    logfile_handler = logging.FileHandler(logfile)
    logfile_handler.setFormatter(formatter)
    if debug:
      logfile_handler.setLevel(logging.DEBUG)
    else:
      logfile_handler.setLevel(logging.INFO)
    root_logger.addHandler(logfile_handler)
  except EnvironmentError, err:
    if stderr_logging:
      logging.exception("Failed to enable logging to file '%s'", logfile)
    else:
      # we need to re-raise the exception
      raise


# Backwards compatibility
Error = logging.error
Info = logging.info
Debug = logging.debug


def ToStdout(txt):
  """Write a message to stdout only, bypassing the logging system

  Parameters:
    - txt: the message

  """
  sys.stdout.write(txt + '\n')
  sys.stdout.flush()


def ToStderr(txt):
  """Write a message to stderr only, bypassing the logging system

  Parameters:
    - txt: the message

  """
  sys.stderr.write(txt + '\n')
  sys.stderr.flush()
