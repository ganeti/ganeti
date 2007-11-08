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


# List of all hooks
_hooks = []


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
  return subprocess.Popen(GetSSHCommand(node, cmd, strict=strict),
                          shell=False)


def GetCommandOutput(node, cmd):
  """Returns the output of a command executed on the given node.

  """
  p = subprocess.Popen(GetSSHCommand(node, cmd),
                       shell=False, stdout=subprocess.PIPE)
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

  """
  return _ResolveName(['gnt-instance', 'info', instance['name']],
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


def LoadHooks():
  """Load all QA hooks.

  """
  hooks_dir = qa_config.get('options', {}).get('hooks-dir', None)
  if not hooks_dir:
    return
  if hooks_dir not in sys.path:
    sys.path.insert(0, hooks_dir)
  for name in utils.ListVisibleFiles(hooks_dir):
    if name.endswith('.py'):
      # Load and instanciate hook
      _hooks.append(__import__(name[:-3], None, None, ['']).hook())


class QaHookContext:
  name = None
  phase = None
  success = None
  args = None
  kwargs = None


def _CallHooks(ctx):
  """Calls all hooks with the given context.

  """
  if not _hooks:
    return

  name = "%s-%s" % (ctx.phase, ctx.name)
  if ctx.success is not None:
    msg = "%s (success=%s)" % (name, ctx.success)
  else:
    msg = name
  print FormatInfo("Begin %s" % msg)
  for hook in _hooks:
    hook.run(ctx)
  print FormatInfo("End %s" % name)


def DefineHook(name):
  """Wraps a function with calls to hooks.

  Usage: prefix function with @qa_utils.DefineHook(...)

  """
  def wrapper(fn):
    def new_f(*args, **kwargs):
      # Create context
      ctx = QaHookContext()
      ctx.name = name
      ctx.phase = 'pre'
      ctx.args = args
      ctx.kwargs = kwargs

      _CallHooks(ctx)
      try:
        ctx.phase = 'post'
        ctx.success = True
        try:
          # Call real function
          return fn(*args, **kwargs)
        except:
          ctx.success = False
          raise
      finally:
        _CallHooks(ctx)

    # Override function metadata
    new_f.func_name = fn.func_name
    new_f.func_doc = fn.func_doc

    return new_f

  return wrapper
