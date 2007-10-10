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

_program = '(unknown)'
_errlog = None
_inflog = None
_dbglog = None
_stdout = None
_stderr = None
_debug = False


def _SetDestination(name, filename, stream=None):
  """Configure the destination for a given logger

  This function configures the logging destination for a given loger.
  Parameters:
    - name: the logger name
    - filename: if not empty, log messages will be written (also) to this file
    - stream: if not none, log messages will be output (also) to this stream

  Returns:
    - the logger identified by the `name` argument
  """
  ret = logging.getLogger(name)

  if filename:
    fmtr = logging.Formatter('%(asctime)s %(message)s')

    hdlr = logging.FileHandler(filename)
    hdlr.setFormatter(fmtr)
    ret.addHandler(hdlr)

  if stream:
    if name in ('error', 'info', 'debug'):
      fmtr = logging.Formatter('%(asctime)s %(message)s')
    else:
      fmtr = logging.Formatter('%(message)s')
    hdlr = logging.StreamHandler(stream)
    hdlr.setFormatter(fmtr)
    ret.addHandler(hdlr)

  ret.setLevel(logging.INFO)

  return ret


def _GenericSetup(program, errfile, inffile, dbgfile,
                  twisted_workaround=False):
  """Configure logging based on arguments

  Arguments:
    - name of program
    - error log filename
    - info log filename
    - debug log filename
    - twisted_workaround: if true, emit all messages to stderr
  """
  global _program
  global _errlog
  global _inflog
  global _dbglog
  global _stdout
  global _stderr

  _program = program
  if twisted_workaround:
    _errlog = _SetDestination('error', None, sys.stderr)
    _inflog = _SetDestination('info', None, sys.stderr)
    _dbglog = _SetDestination('debug', None, sys.stderr)
  else:
    _errlog = _SetDestination('error', errfile)
    _inflog = _SetDestination('info', inffile)
    _dbglog = _SetDestination('debug', dbgfile)

  _stdout = _SetDestination('user', None, sys.stdout)
  _stderr = _SetDestination('stderr', None, sys.stderr)


def SetupLogging(twisted_workaround=False, debug=False, program='ganeti'):
  """Setup logging for ganeti

  On failure, a check is made whether process is run by root or not,
  and an appropriate error message is printed on stderr, then process
  exits.

  This function is just a wraper over `_GenericSetup()` using specific
  arguments.

  Parameter:
    twisted_workaround: passed to `_GenericSetup()`

  """
  try:
    _GenericSetup(program,
                  os.path.join(constants.LOG_DIR, "errors"),
                  os.path.join(constants.LOG_DIR, "info"),
                  os.path.join(constants.LOG_DIR, "debug"),
                  twisted_workaround)
  except IOError:
    # The major reason to end up here is that we're being run as a
    # non-root user.  We might also get here if xen has not been
    # installed properly.  This is not the correct place to enforce
    # being run by root; nevertheless, here makes sense because here
    # is where we first notice it.
    if os.getuid() != 0:
      sys.stderr.write('This program must be run by the superuser.\n')
    else:
      sys.stderr.write('Unable to open log files.  Incomplete system?\n')

    sys.exit(2)

  global _debug
  _debug = debug


def _WriteEntry(log, txt):
  """
  Write a message to a given log.
  Splits multi-line messages up into a series of log writes, to
  keep consistent format on lines in file.

  Parameters:
    - log: the destination log
    - txt: the message

  """
  if log is None:
    sys.stderr.write("Logging system not initialized while processing"
                     " message:\n")
    sys.stderr.write("%s\n" % txt)
    return

  lines = txt.split('\n')

  spaces = ' ' * len(_program) + '| '

  lines = ([ _program + ': ' + lines[0] ] +
           map(lambda a: spaces + a, lines[1:]))

  for line in lines:
    log.log(logging.INFO, line)


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


def Error(txt):
  """Write a message to our error log

  Parameters:
    - dbg: if true, the message will also be output to stderr
    - txt: the log message

  """
  _WriteEntry(_errlog, txt)
  sys.stderr.write(txt + '\n')


def Info(txt):
  """Write a message to our general messages log

  If the global debug flag is true, the log message will also be
  output to stderr.

  Parameters:
    - txt: the log message

  """
  _WriteEntry(_inflog, txt)
  if _debug:
    _WriteEntry(_stderr, txt)


def Debug(txt):
  """Write a message to the debug log

  If the global debug flag is true, the log message will also be
  output to stderr.

  Parameters:
    - txt: the log message

  """
  _WriteEntry(_dbglog, txt)
  if _debug:
    _WriteEntry(_stderr, txt)
