#
#

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
import re
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

  # Don't use colours if stdout isn't a terminal
  if not sys.stdout.isatty():
    return

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


def AssertIn(item, sequence):
  """Raises an error when item is not in sequence.

  """
  if item not in sequence:
    raise qa_error.Error('%r not in %r' % (item, sequence))


def AssertEqual(first, second):
  """Raises an error when values aren't equal.

  """
  if not first == second:
    raise qa_error.Error('%r == %r' % (first, second))


def AssertNotEqual(first, second):
  """Raises an error when values are equal.

  """
  if not first != second:
    raise qa_error.Error('%r != %r' % (first, second))


def AssertMatch(string, pattern):
  """Raises an error when string doesn't match regexp pattern.

  """
  if not re.match(pattern, string):
    raise qa_error.Error("%r doesn't match /%r/" % (string, pattern))


def GetSSHCommand(node, cmd, strict=True):
  """Builds SSH command to be executed.

  Args:
  - node: Node the command should run on
  - cmd: Command to be executed as a list with all parameters
  - strict: Whether to enable strict host key checking

  """
  args = [ 'ssh', '-oEscapeChar=none', '-oBatchMode=yes', '-l', 'root', '-t' ]

  if strict:
    tmp = 'yes'
  else:
    tmp = 'no'
  args.append('-oStrictHostKeyChecking=%s' % tmp)
  args.append('-oClearAllForwardings=yes')
  args.append('-oForwardAgent=yes')
  args.append(node)
  args.append(cmd)

  return args


def StartLocalCommand(cmd, **kwargs):
  """Starts a local command.

  """
  print "Command: %s" % utils.ShellQuoteArgs(cmd)
  return subprocess.Popen(cmd, shell=False, **kwargs)


def StartSSH(node, cmd, strict=True):
  """Starts SSH.

  """
  return StartLocalCommand(GetSSHCommand(node, cmd, strict=strict))


def GetCommandOutput(node, cmd):
  """Returns the output of a command executed on the given node.

  """
  p = StartLocalCommand(GetSSHCommand(node, cmd), stdout=subprocess.PIPE)
  AssertEqual(p.wait(), 0)
  return p.stdout.read()


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


def BackupFile(node, path):
  """Creates a backup of a file on the node and returns the filename.

  Caller needs to remove the returned file on the node when it's not needed
  anymore.

  """
  cmd = ("tmp=$(tempfile --prefix .gnt --directory=$(dirname %s)) && "
         "[[ -f \"$tmp\" ]] && "
         "cp %s $tmp && "
         "echo $tmp") % (utils.ShellQuote(path), utils.ShellQuote(path))

  # Return temporary filename
  return GetCommandOutput(node, cmd).strip()


def _ResolveName(cmd, key):
  """Helper function.

  """
  master = qa_config.GetMasterNode()

  output = GetCommandOutput(master['primary'], utils.ShellQuoteArgs(cmd))
  for line in output.splitlines():
    (lkey, lvalue) = line.split(':', 1)
    if lkey == key:
      return lvalue.lstrip()
  raise KeyError("Key not found")


def ResolveInstanceName(instance):
  """Gets the full name of an instance.

  @type instance: string
  @param instance: Instance name

  """
  return _ResolveName(['gnt-instance', 'info', instance],
                      'Instance name')


def ResolveNodeName(node):
  """Gets the full name of a node.

  """
  return _ResolveName(['gnt-node', 'info', node['primary']],
                      'Node name')


def GetNodeInstances(node, secondaries=False):
  """Gets a list of instances on a node.

  """
  master = qa_config.GetMasterNode()
  node_name = ResolveNodeName(node)

  # Get list of all instances
  cmd = ['gnt-instance', 'list', '--separator=:', '--no-headers',
         '--output=name,pnode,snodes']
  output = GetCommandOutput(master['primary'], utils.ShellQuoteArgs(cmd))

  instances = []
  for line in output.splitlines():
    (name, pnode, snodes) = line.split(':', 2)
    if ((not secondaries and pnode == node_name) or
        (secondaries and node_name in snodes.split(','))):
      instances.append(name)

  return instances


def _FormatWithColor(text, seq):
  if not seq:
    return text
  return "%s%s%s" % (seq, text, _RESET_SEQ)


FormatWarning = lambda text: _FormatWithColor(text, _WARNING_SEQ)
FormatError = lambda text: _FormatWithColor(text, _ERROR_SEQ)
FormatInfo = lambda text: _FormatWithColor(text, _INFO_SEQ)
