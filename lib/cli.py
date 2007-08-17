#!/usr/bin/python
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


"""Module dealing with command line parsing"""


import sys
import textwrap
import os.path
import copy

from ganeti import utils
from ganeti import logger
from ganeti import errors
from ganeti import mcpu
from ganeti import constants

from optparse import (OptionParser, make_option, TitledHelpFormatter,
                      Option, OptionValueError, SUPPRESS_HELP)

__all__ = ["DEBUG_OPT", "NOHDR_OPT", "SEP_OPT", "GenericMain", "SubmitOpCode",
           "cli_option", "GenerateTable",
           "ARGS_NONE", "ARGS_FIXED", "ARGS_ATLEAST", "ARGS_ANY", "ARGS_ONE",
           "USEUNITS_OPT", "FIELDS_OPT", "FORCE_OPT"]

DEBUG_OPT = make_option("-d", "--debug", default=False,
                        action="store_true",
                        help="Turn debugging on")

NOHDR_OPT = make_option("--no-headers", default=False,
                        action="store_true", dest="no_headers",
                        help="Don't display column headers")

SEP_OPT = make_option("--separator", default=None,
                      action="store", dest="separator",
                      help="Separator between output fields"
                      " (defaults to one space)")

USEUNITS_OPT = make_option("--human-readable", default=False,
                           action="store_true", dest="human_readable",
                           help="Print sizes in human readable format")

FIELDS_OPT = make_option("-o", "--output", dest="output", action="store",
                         type="string", help="Select output fields",
                         metavar="FIELDS")

FORCE_OPT = make_option("-f", "--force", dest="force", action="store_true",
                        default=False, help="Force the operation")

_LOCK_OPT = make_option("--lock-retries", default=None,
                        type="int", help=SUPPRESS_HELP)


def ARGS_FIXED(val):
  """Macro-like function denoting a fixed number of arguments"""
  return -val


def ARGS_ATLEAST(val):
  """Macro-like function denoting a minimum number of arguments"""
  return val


ARGS_NONE = None
ARGS_ONE = ARGS_FIXED(1)
ARGS_ANY = ARGS_ATLEAST(0)


def check_unit(option, opt, value):
  try:
    return utils.ParseUnit(value)
  except errors.UnitParseError, err:
    raise OptionValueError("option %s: %s" % (opt, err))


class CliOption(Option):
  TYPES = Option.TYPES + ("unit",)
  TYPE_CHECKER = copy.copy(Option.TYPE_CHECKER)
  TYPE_CHECKER["unit"] = check_unit


# optparse.py sets make_option, so we do it for our own option class, too
cli_option = CliOption


def _ParseArgs(argv, commands):
  """Parses the command line and return the function which must be
  executed together with its arguments

  Arguments:
    argv: the command line

    commands: dictionary with special contents, see the design doc for
    cmdline handling

  """
  if len(argv) == 0:
    binary = "<command>"
  else:
    binary = argv[0].split("/")[-1]

  if len(argv) > 1 and argv[1] == "--version":
    print "%s (ganeti) %s" % (binary, constants.RELEASE_VERSION)
    # Quit right away. That way we don't have to care about this special
    # argument. optparse.py does it the same.
    sys.exit(0)

  if len(argv) < 2 or argv[1] not in commands.keys():
    # let's do a nice thing
    sortedcmds = commands.keys()
    sortedcmds.sort()
    print ("Usage: %(bin)s {command} [options...] [argument...]"
           "\n%(bin)s <command> --help to see details, or"
           " man %(bin)s\n" % {"bin": binary})
    # compute the max line length for cmd + usage
    mlen = max([len(" %s %s" % (cmd, commands[cmd][3])) for cmd in commands])
    mlen = min(60, mlen) # should not get here...
    # and format a nice command list
    print "Commands:"
    for cmd in sortedcmds:
      cmdstr = " %s %s" % (cmd, commands[cmd][3])
      help_text = commands[cmd][4]
      help_lines = textwrap.wrap(help_text, 79-3-mlen)
      print "%-*s - %s" % (mlen, cmdstr,
                                          help_lines.pop(0))
      for line in help_lines:
        print "%-*s   %s" % (mlen, "", line)
    print
    return None, None, None
  cmd = argv.pop(1)
  func, nargs, parser_opts, usage, description = commands[cmd]
  parser_opts.append(_LOCK_OPT)
  parser = OptionParser(option_list=parser_opts,
                        description=description,
                        formatter=TitledHelpFormatter(),
                        usage="%%prog %s %s" % (cmd, usage))
  parser.disable_interspersed_args()
  options, args = parser.parse_args()
  if nargs is None:
    if len(args) != 0:
      print >> sys.stderr, ("Error: Command %s expects no arguments" % cmd)
      return None, None, None
  elif nargs < 0 and len(args) != -nargs:
    print >> sys.stderr, ("Error: Command %s expects %d argument(s)" %
                         (cmd, -nargs))
    return None, None, None
  elif nargs >= 0 and len(args) < nargs:
    print >> sys.stderr, ("Error: Command %s expects at least %d argument(s)" %
                         (cmd, nargs))
    return None, None, None

  return func, options, args


def _AskUser(text):
  """Ask the user a yes/no question.

  Args:
    questionstring - the question to ask.

  Returns:
    True or False depending on answer (No for False is default).

  """
  try:
    f = file("/dev/tty", "r+")
  except IOError:
    return False
  answer = False
  try:
    f.write(textwrap.fill(text))
    f.write('\n')
    f.write("y/[n]: ")
    line = f.readline(16).strip().lower()
    answer = line in ('y', 'yes')
  finally:
    f.close()
  return answer


def SubmitOpCode(op):
  """Function to submit an opcode.

  This is just a simple wrapper over the construction of the processor
  instance. It should be extended to better handle feedback and
  interaction functions.

  """
  proc = mcpu.Processor()
  return proc.ExecOpCode(op, logger.ToStdout)


def GenericMain(commands):
  """Generic main function for all the gnt-* commands.

  Argument: a dictionary with a special structure, see the design doc
  for command line handling.

  """
  # save the program name and the entire command line for later logging
  if sys.argv:
    binary = os.path.basename(sys.argv[0]) or sys.argv[0]
    if len(sys.argv) >= 2:
      binary += " " + sys.argv[1]
      old_cmdline = " ".join(sys.argv[2:])
    else:
      old_cmdline = ""
  else:
    binary = "<unknown program>"
    old_cmdline = ""

  func, options, args = _ParseArgs(sys.argv, commands)
  if func is None: # parse error
    return 1

  options._ask_user = _AskUser

  logger.SetupLogging(debug=options.debug, program=binary)

  try:
    utils.Lock('cmd', max_retries=options.lock_retries, debug=options.debug)
  except errors.LockError, err:
    logger.ToStderr(str(err))
    return 1

  if old_cmdline:
    logger.Info("run with arguments '%s'" % old_cmdline)
  else:
    logger.Info("run with no arguments")

  try:
    try:
      result = func(options, args)
    except errors.ConfigurationError, err:
      logger.Error("Corrupt configuration file: %s" % err)
      logger.ToStderr("Aborting.")
      result = 2
    except errors.HooksAbort, err:
      logger.ToStderr("Failure: hooks execution failed:")
      for node, script, out in err.args[0]:
        if out:
          logger.ToStderr("  node: %s, script: %s, output: %s" %
                          (node, script, out))
        else:
          logger.ToStderr("  node: %s, script: %s (no output)" %
                          (node, script))
      result = 1
    except errors.HooksFailure, err:
      logger.ToStderr("Failure: hooks general failure: %s" % str(err))
      result = 1
    except errors.OpPrereqError, err:
      logger.ToStderr("Failure: prerequisites not met for this"
                      " operation:\n%s" % str(err))
      result = 1
    except errors.OpExecError, err:
      logger.ToStderr("Failure: command execution error:\n%s" % str(err))
      result = 1
  finally:
    utils.Unlock('cmd')
    utils.LockCleanup()

  return result


def GenerateTable(headers, fields, separator, data,
                  numfields=None, unitfields=None):
  """Prints a table with headers and different fields.

  Args:
    headers: Dict of header titles or None if no headers should be shown
    fields: List of fields to show
    separator: String used to separate fields or None for spaces
    data: Data to be printed
    numfields: List of fields to be aligned to right
    unitfields: List of fields to be formatted as units

  """
  if numfields is None:
    numfields = []
  if unitfields is None:
    unitfields = []

  format_fields = []
  for field in fields:
    if separator is not None:
      format_fields.append("%s")
    elif field in numfields:
      format_fields.append("%*s")
    else:
      format_fields.append("%-*s")

  if separator is None:
    mlens = [0 for name in fields]
    format = ' '.join(format_fields)
  else:
    format = separator.replace("%", "%%").join(format_fields)

  for row in data:
    for idx, val in enumerate(row):
      if fields[idx] in unitfields:
        try:
          val = int(val)
        except ValueError:
          pass
        else:
          val = row[idx] = utils.FormatUnit(val)
      if separator is None:
        mlens[idx] = max(mlens[idx], len(val))

  result = []
  if headers:
    args = []
    for idx, name in enumerate(fields):
      hdr = headers[name]
      if separator is None:
        mlens[idx] = max(mlens[idx], len(hdr))
        args.append(mlens[idx])
      args.append(hdr)
    result.append(format % tuple(args))

  for line in data:
    args = []
    for idx in xrange(len(fields)):
      if separator is None:
        args.append(mlens[idx])
      args.append(line[idx])
    result.append(format % tuple(args))

  return result
