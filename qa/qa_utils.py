# Copyright (C) 2007 Google Inc.
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


"""Utilities for QA tests.

"""

import os
import sys
import subprocess

from ganeti import utils

import qa_config
import qa_error


_INFO_SEQ = None
_WARNING_SEQ = None
_ERROR_SEQ = None
_RESET_SEQ = None


def _SetupColours():
  """Initializes the colour constants.

  """
  global _INFO_SEQ, _WARNING_SEQ, _ERROR_SEQ, _RESET_SEQ

  try:
    import curses
  except ImportError:
    # Don't use colours if curses module can't be imported
    return

  curses.setupterm()

  _RESET_SEQ = curses.tigetstr("op")

  setaf = curses.tigetstr("setaf")
  _INFO_SEQ = curses.tparm(setaf, curses.COLOR_GREEN)
  _WARNING_SEQ = curses.tparm(setaf, curses.COLOR_YELLOW)
  _ERROR_SEQ = curses.tparm(setaf, curses.COLOR_RED)


_SetupColours()


def AssertEqual(first, second, msg=None):
  """Raises an error when values aren't equal.

  """
  if not first == second:
    raise qa_error.Error(msg or '%r == %r' % (first, second))


def GetSSHCommand(node, cmd, strict=True):
  """Builds SSH command to be executed.

  """
  args = [ 'ssh', '-oEscapeChar=none', '-oBatchMode=yes', '-l', 'root' ]

  if strict:
    tmp = 'yes'
  else:
    tmp = 'no'
  args.append('-oStrictHostKeyChecking=%s' % tmp)
  args.append('-oClearAllForwardings=yes')
  args.append('-oForwardAgent=yes')
  args.append(node)

  if qa_config.options.dry_run:
    prefix = 'exit 0; '
  else:
    prefix = ''

  args.append(prefix + cmd)

  print 'SSH:', utils.ShellQuoteArgs(args)

  return args


def StartSSH(node, cmd, strict=True):
  """Starts SSH.

  """
  args = GetSSHCommand(node, cmd, strict=strict)
  return subprocess.Popen(args, shell=False)


def UploadFile(node, src):
  """Uploads a file to a node and returns the filename.

  Caller needs to remove the returned file on the node when it's not needed
  anymore.
  """
  # Make sure nobody else has access to it while preserving local permissions
  mode = os.stat(src).st_mode & 0700

  cmd = ('tmp=$(tempfile --mode %o --prefix gnt) && '
         '[[ -f "${tmp}" ]] && '
         'cat > "${tmp}" && '
         'echo "${tmp}"') % mode

  f = open(src, 'r')
  try:
    p = subprocess.Popen(GetSSHCommand(node, cmd), shell=False, stdin=f,
                         stdout=subprocess.PIPE)
    AssertEqual(p.wait(), 0)

    # Return temporary filename
    return p.stdout.read().strip()
  finally:
    f.close()


def ResolveInstanceName(instance):
  """Gets the full name of an instance.

  """
  master = qa_config.GetMasterNode()

  info_cmd = utils.ShellQuoteArgs(['gnt-instance', 'info', instance['name']])
  sed_cmd = utils.ShellQuoteArgs(['sed', '-n', '-e', 's/^Instance name: *//p'])

  cmd = '%s | %s' % (info_cmd, sed_cmd)
  ssh_cmd = GetSSHCommand(master['primary'], cmd)
  p = subprocess.Popen(ssh_cmd, shell=False, stdout=subprocess.PIPE)
  AssertEqual(p.wait(), 0)

  return p.stdout.read().strip()


def _PrintWithColor(text, seq):
  f = sys.stdout

  if not f.isatty():
    seq = None

  if seq:
    f.write(seq)

  f.write(text)
  f.write("\n")

  if seq:
    f.write(_RESET_SEQ)


def PrintWarning(text):
  return _PrintWithColor(text, _WARNING_SEQ)


def PrintError(f, text):
  return _PrintWithColor(text, _ERROR_SEQ)


def PrintInfo(f, text):
  return _PrintWithColor(text, _INFO_SEQ)
