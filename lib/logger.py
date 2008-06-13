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
import os, os.path

from ganeti import constants


def _CreateFileHandler(name):
  return logging.FileHandler(os.path.join(constants.LOG_DIR, name))


def SetupLogging(program='ganeti', debug=False):
  """Setup logging for ganeti

  On failure, a check is made whether process is run by root or not,
  and an appropriate error message is printed on stderr, then process
  exits.

  Args:
    debug: Whether to enable verbose logging
    program: Program name

  """
  fmt = "%(asctime)s " + program + ": %(message)s"
  formatter = logging.Formatter(fmt)

  info_file = _CreateFileHandler("info")
  info_file.setLevel(logging.INFO)
  info_file.setFormatter(formatter)

  errors_file = _CreateFileHandler("errors")
  errors_file.setLevel(logging.ERROR)
  errors_file.setFormatter(formatter)

  debug_file = _CreateFileHandler("debug")
  debug_file.setLevel(logging.DEBUG)
  debug_file.setFormatter(formatter)

  stderr_file = logging.StreamHandler()
  if debug:
    stderr_file.setLevel(logging.NOTSET)
  else:
    stderr_file.setLevel(logging.ERROR)

  root_logger = logging.getLogger("")
  root_logger.setLevel(logging.NOTSET)
  root_logger.addHandler(info_file)
  root_logger.addHandler(errors_file)
  root_logger.addHandler(debug_file)
  root_logger.addHandler(stderr_file)


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
