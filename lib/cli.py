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


"""Module dealing with command line parsing"""


import sys
import textwrap
import os.path
import copy
from cStringIO import StringIO

from ganeti import utils
from ganeti import logger
from ganeti import errors
from ganeti import mcpu
from ganeti import constants
from ganeti import opcodes

from optparse import (OptionParser, make_option, TitledHelpFormatter,
                      Option, OptionValueError, SUPPRESS_HELP)

__all__ = ["DEBUG_OPT", "NOHDR_OPT", "SEP_OPT", "GenericMain", "SubmitOpCode",
           "cli_option", "GenerateTable", "AskUser",
           "ARGS_NONE", "ARGS_FIXED", "ARGS_ATLEAST", "ARGS_ANY", "ARGS_ONE",
           "USEUNITS_OPT", "FIELDS_OPT", "FORCE_OPT",
           "ListTags", "AddTags", "RemoveTags", "TAG_SRC_OPT",
           "FormatError",
           ]


def _ExtractTagsObject(opts, args):
  """Extract the tag type object.

  Note that this function will modify its args parameter.

  """
  if not hasattr(opts, "tag_type"):
    raise errors.ProgrammerError("tag_type not passed to _ExtractTagsObject")
  kind = opts.tag_type
  if kind == constants.TAG_CLUSTER:
    retval = kind, kind
  elif kind == constants.TAG_NODE or kind == constants.TAG_INSTANCE:
    if not args:
      raise errors.OpPrereqError("no arguments passed to the command")
    name = args.pop(0)
    retval = kind, name
  else:
    raise errors.ProgrammerError("Unhandled tag type '%s'" % kind)
  return retval


def _ExtendTags(opts, args):
  """Extend the args if a source file has been given.

  This function will extend the tags with the contents of the file
  passed in the 'tags_source' attribute of the opts parameter. A file
  named '-' will be replaced by stdin.

  """
  fname = opts.tags_source
  if fname is None:
    return
  if fname == "-":
    new_fh = sys.stdin
  else:
    new_fh = open(fname, "r")
  new_data = []
  try:
    # we don't use the nice 'new_data = [line.strip() for line in fh]'
    # because of python bug 1633941
    while True:
      line = new_fh.readline()
      if not line:
        break
      new_data.append(line.strip())
  finally:
    new_fh.close()
  args.extend(new_data)


def ListTags(opts, args):
  """List the tags on a given object.

  This is a generic implementation that knows how to deal with all
  three cases of tag objects (cluster, node, instance). The opts
  argument is expected to contain a tag_type field denoting what
  object type we work on.

  """
  kind, name = _ExtractTagsObject(opts, args)
  op = opcodes.OpGetTags(kind=kind, name=name)
  result = SubmitOpCode(op)
  result = list(result)
  result.sort()
  for tag in result:
    print tag


def AddTags(opts, args):
  """Add tags on a given object.

  This is a generic implementation that knows how to deal with all
  three cases of tag objects (cluster, node, instance). The opts
  argument is expected to contain a tag_type field denoting what
  object type we work on.

  """
  kind, name = _ExtractTagsObject(opts, args)
  _ExtendTags(opts, args)
  if not args:
    raise errors.OpPrereqError("No tags to be added")
  op = opcodes.OpAddTags(kind=kind, name=name, tags=args)
  SubmitOpCode(op)


def RemoveTags(opts, args):
  """Remove tags from a given object.

  This is a generic implementation that knows how to deal with all
  three cases of tag objects (cluster, node, instance). The opts
  argument is expected to contain a tag_type field denoting what
  object type we work on.

  """
  kind, name = _ExtractTagsObject(opts, args)
  _ExtendTags(opts, args)
  if not args:
    raise errors.OpPrereqError("No tags to be removed")
  op = opcodes.OpDelTags(kind=kind, name=name, tags=args)
  SubmitOpCode(op)


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

TAG_SRC_OPT = make_option("--from", dest="tags_source",
                          default=None, help="File with tag names")

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


def AskUser(text, choices=None):
  """Ask the user a question.

  Args:
    text - the question to ask.

    choices - list with elements tuples (input_char, return_value,
    description); if not given, it will default to: [('y', True,
    'Perform the operation'), ('n', False, 'Do no do the operation')];
    note that the '?' char is reserved for help

  Returns: one of the return values from the choices list; if input is
  not possible (i.e. not running with a tty, we return the last entry
  from the list

  """
  if choices is None:
    choices = [('y', True, 'Perform the operation'),
               ('n', False, 'Do not perform the operation')]
  if not choices or not isinstance(choices, list):
    raise errors.ProgrammerError("Invalid choiches argument to AskUser")
  for entry in choices:
    if not isinstance(entry, tuple) or len(entry) < 3 or entry[0] == '?':
      raise errors.ProgrammerError("Invalid choiches element to AskUser")

  answer = choices[-1][1]
  new_text = []
  for line in text.splitlines():
    new_text.append(textwrap.fill(line, 70, replace_whitespace=False))
  text = "\n".join(new_text)
  try:
    f = file("/dev/tty", "r+")
  except IOError:
    return answer
  try:
    chars = [entry[0] for entry in choices]
    chars[-1] = "[%s]" % chars[-1]
    chars.append('?')
    maps = dict([(entry[0], entry[1]) for entry in choices])
    while True:
      f.write(text)
      f.write('\n')
      f.write("/".join(chars))
      f.write(": ")
      line = f.readline(2).strip().lower()
      if line in maps:
        answer = maps[line]
        break
      elif line == '?':
        for entry in choices:
          f.write(" %s - %s\n" % (entry[0], entry[2]))
        f.write("\n")
        continue
  finally:
    f.close()
  return answer


def SubmitOpCode(op, proc=None, feedback_fn=None):
  """Function to submit an opcode.

  This is just a simple wrapper over the construction of the processor
  instance. It should be extended to better handle feedback and
  interaction functions.

  """
  if proc is None:
    proc = mcpu.Processor()
  if feedback_fn is None:
    feedback_fn = logger.ToStdout
  return proc.ExecOpCode(op, feedback_fn)


def FormatError(err):
  """Return a formatted error message for a given error.

  This function takes an exception instance and returns a tuple
  consisting of two values: first, the recommended exit code, and
  second, a string describing the error message (not
  newline-terminated).

  """
  retcode = 1
  obuf = StringIO()
  if isinstance(err, errors.ConfigurationError):
    msg = "Corrupt configuration file: %s" % err
    logger.Error(msg)
    obuf.write(msg + "\n")
    obuf.write("Aborting.")
    retcode = 2
  elif isinstance(err, errors.HooksAbort):
    obuf.write("Failure: hooks execution failed:\n")
    for node, script, out in err.args[0]:
      if out:
        obuf.write("  node: %s, script: %s, output: %s\n" %
                   (node, script, out))
      else:
        obuf.write("  node: %s, script: %s (no output)\n" %
                   (node, script))
  elif isinstance(err, errors.HooksFailure):
    obuf.write("Failure: hooks general failure: %s" % str(err))
  elif isinstance(err, errors.ResolverError):
    this_host = utils.HostInfo.SysName()
    if err.args[0] == this_host:
      msg = "Failure: can't resolve my own hostname ('%s')"
    else:
      msg = "Failure: can't resolve hostname '%s'"
    obuf.write(msg % err.args[0])
  elif isinstance(err, errors.OpPrereqError):
    obuf.write("Failure: prerequisites not met for this"
               " operation:\n%s" % str(err))
  elif isinstance(err, errors.OpExecError):
    obuf.write("Failure: command execution error:\n%s" % str(err))
  elif isinstance(err, errors.TagError):
    obuf.write("Failure: invalid tag(s) given:\n%s" % str(err))
  elif isinstance(err, errors.GenericError):
    obuf.write("Unhandled Ganeti error: %s" % str(err))
  else:
    obuf.write("Unhandled exception: %s" % str(err))
  return retcode, obuf.getvalue().rstrip('\n')


def GenericMain(commands, override=None):
  """Generic main function for all the gnt-* commands.

  Arguments:
    - commands: a dictionary with a special structure, see the design doc
                for command line handling.
    - override: if not None, we expect a dictionary with keys that will
                override command line options; this can be used to pass
                options from the scripts to generic functions

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

  if override is not None:
    for key, val in override.iteritems():
      setattr(options, key, val)

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
    except errors.GenericError, err:
      result, err_msg = FormatError(err)
      logger.ToStderr(err_msg)
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
