#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Module dealing with command line parsing"""


import sys
import textwrap
import os.path
import time
import logging
import errno
import itertools
import shlex

from io import StringIO
from optparse import (OptionParser, TitledHelpFormatter)

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import opcodes
import ganeti.rpc.errors as rpcerr
from ganeti import ssh
from ganeti import compat
from ganeti import netutils
from ganeti import qlang
from ganeti import objects
from ganeti import pathutils
from ganeti import serializer
import ganeti.cli_opts
# Import constants
from ganeti.cli_opts import *  # pylint: disable=W0401,W0614

from ganeti.runtime import (GetClient)


__all__ = [
  # Generic functions for CLI programs
  "ConfirmOperation",
  "CreateIPolicyFromOpts",
  "GenericMain",
  "GenericInstanceCreate",
  "GenericList",
  "GenericListFields",
  "GetClient",
  "GetOnlineNodes",
  "GetNodesSshPorts",
  "GetNodeUUIDs",
  "JobExecutor",
  "ParseTimespec",
  "RunWhileClusterStopped",
  "RunWhileDaemonsStopped",
  "SubmitOpCode",
  "SubmitOpCodeToDrainedQueue",
  "SubmitOrSend",
  # Formatting functions
  "ToStderr", "ToStdout",
  "ToStdoutAndLoginfo",
  "FormatError",
  "FormatQueryResult",
  "FormatParamsDictInfo",
  "FormatPolicyInfo",
  "PrintIPolicyCommand",
  "PrintGenericInfo",
  "GenerateTable",
  "AskUser",
  "FormatTimestamp",
  "FormatLogMessage",
  # Tags functions
  "ListTags",
  "AddTags",
  "RemoveTags",
  # command line options support infrastructure
  "ARGS_MANY_INSTANCES",
  "ARGS_MANY_NODES",
  "ARGS_MANY_GROUPS",
  "ARGS_MANY_NETWORKS",
  "ARGS_MANY_FILTERS",
  "ARGS_NONE",
  "ARGS_ONE_INSTANCE",
  "ARGS_ONE_NODE",
  "ARGS_ONE_GROUP",
  "ARGS_ONE_OS",
  "ARGS_ONE_NETWORK",
  "ARGS_ONE_FILTER",
  "ArgChoice",
  "ArgCommand",
  "ArgFile",
  "ArgGroup",
  "ArgHost",
  "ArgInstance",
  "ArgJobId",
  "ArgNetwork",
  "ArgNode",
  "ArgOs",
  "ArgExtStorage",
  "ArgFilter",
  "ArgSuggest",
  "ArgUnknown",
  "FixHvParams",
  "SplitNodeOption",
  "CalculateOSNames",
  "ParseFields",
  ] + ganeti.cli_opts.__all__ # Command line options

# Query result status for clients
(QR_NORMAL,
 QR_UNKNOWN,
 QR_INCOMPLETE) = range(3)

#: Maximum batch size for ChooseJob
_CHOOSE_BATCH = 25


# constants used to create InstancePolicy dictionary
TISPECS_GROUP_TYPES = {
  constants.ISPECS_MIN: constants.VTYPE_INT,
  constants.ISPECS_MAX: constants.VTYPE_INT,
  }

TISPECS_CLUSTER_TYPES = {
  constants.ISPECS_MIN: constants.VTYPE_INT,
  constants.ISPECS_MAX: constants.VTYPE_INT,
  constants.ISPECS_STD: constants.VTYPE_INT,
  }

#: User-friendly names for query2 field types
_QFT_NAMES = {
  constants.QFT_UNKNOWN: "Unknown",
  constants.QFT_TEXT: "Text",
  constants.QFT_BOOL: "Boolean",
  constants.QFT_NUMBER: "Number",
  constants.QFT_NUMBER_FLOAT: "Floating-point number",
  constants.QFT_UNIT: "Storage size",
  constants.QFT_TIMESTAMP: "Timestamp",
  constants.QFT_OTHER: "Custom",
  }


class _Argument(object):
  def __init__(self, min=0, max=None): # pylint: disable=W0622
    self.min = min
    self.max = max

  def __repr__(self):
    return ("<%s min=%s max=%s>" %
            (self.__class__.__name__, self.min, self.max))


class ArgSuggest(_Argument):
  """Suggesting argument.

  Value can be any of the ones passed to the constructor.

  """
  # pylint: disable=W0622
  def __init__(self, min=0, max=None, choices=None):
    _Argument.__init__(self, min=min, max=max)
    self.choices = choices

  def __repr__(self):
    return ("<%s min=%s max=%s choices=%r>" %
            (self.__class__.__name__, self.min, self.max, self.choices))


class ArgChoice(ArgSuggest):
  """Choice argument.

  Value can be any of the ones passed to the constructor. Like L{ArgSuggest},
  but value must be one of the choices.

  """


class ArgUnknown(_Argument):
  """Unknown argument to program (e.g. determined at runtime).

  """


class ArgInstance(_Argument):
  """Instances argument.

  """


class ArgNode(_Argument):
  """Node argument.

  """


class ArgNetwork(_Argument):
  """Network argument.

  """


class ArgGroup(_Argument):
  """Node group argument.

  """


class ArgJobId(_Argument):
  """Job ID argument.

  """


class ArgFile(_Argument):
  """File path argument.

  """


class ArgCommand(_Argument):
  """Command argument.

  """


class ArgHost(_Argument):
  """Host argument.

  """


class ArgOs(_Argument):
  """OS argument.

  """


class ArgExtStorage(_Argument):
  """ExtStorage argument.

  """


class ArgFilter(_Argument):
  """Filter UUID argument.

  """


ARGS_NONE = []
ARGS_MANY_INSTANCES = [ArgInstance()]
ARGS_MANY_NETWORKS = [ArgNetwork()]
ARGS_MANY_NODES = [ArgNode()]
ARGS_MANY_GROUPS = [ArgGroup()]
ARGS_MANY_FILTERS = [ArgFilter()]
ARGS_ONE_INSTANCE = [ArgInstance(min=1, max=1)]
ARGS_ONE_NETWORK = [ArgNetwork(min=1, max=1)]
ARGS_ONE_NODE = [ArgNode(min=1, max=1)]
ARGS_ONE_GROUP = [ArgGroup(min=1, max=1)]
ARGS_ONE_OS = [ArgOs(min=1, max=1)]
ARGS_ONE_FILTER = [ArgFilter(min=1, max=1)]


def _ExtractTagsObject(opts, args):
  """Extract the tag type object.

  Note that this function will modify its args parameter.

  """
  if not hasattr(opts, "tag_type"):
    raise errors.ProgrammerError("tag_type not passed to _ExtractTagsObject")
  kind = opts.tag_type
  if kind == constants.TAG_CLUSTER:
    retval = kind, ""
  elif kind in (constants.TAG_NODEGROUP,
                constants.TAG_NODE,
                constants.TAG_NETWORK,
                constants.TAG_INSTANCE):
    if not args:
      raise errors.OpPrereqError("no arguments passed to the command",
                                 errors.ECODE_INVAL)
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
  cl = GetClient()
  result = cl.QueryTags(kind, name)
  result = list(result)
  result.sort()
  for tag in result:
    ToStdout(tag)


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
    raise errors.OpPrereqError("No tags to be added", errors.ECODE_INVAL)
  op = opcodes.OpTagsSet(kind=kind, name=name, tags=args)
  SubmitOrSend(op, opts)


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
    raise errors.OpPrereqError("No tags to be removed", errors.ECODE_INVAL)
  op = opcodes.OpTagsDel(kind=kind, name=name, tags=args)
  SubmitOrSend(op, opts)


class _ShowUsage(Exception):
  """Exception class for L{_ParseArgs}.

  """
  def __init__(self, exit_error):
    """Initializes instances of this class.

    @type exit_error: bool
    @param exit_error: Whether to report failure on exit

    """
    Exception.__init__(self)
    self.exit_error = exit_error


class _ShowVersion(Exception):
  """Exception class for L{_ParseArgs}.

  """


def _ParseArgs(binary, argv, commands, aliases, env_override):
  """Parser for the command line arguments.

  This function parses the arguments and returns the function which
  must be executed together with its (modified) arguments.

  @param binary: Script name
  @param argv: Command line arguments
  @param commands: Dictionary containing command definitions
  @param aliases: dictionary with command aliases {"alias": "target", ...}
  @param env_override: list of env variables allowed for default args
  @raise _ShowUsage: If usage description should be shown
  @raise _ShowVersion: If version should be shown

  """
  assert not (env_override - set(commands))
  assert not (set(aliases.keys()) & set(commands.keys()))

  if len(argv) > 1:
    cmd = argv[1]
  else:
    # No option or command given
    raise _ShowUsage(exit_error=True)

  if cmd == "--version":
    raise _ShowVersion()
  elif cmd == "--help":
    raise _ShowUsage(exit_error=False)
  elif not (cmd in commands or cmd in aliases):
    raise _ShowUsage(exit_error=True)

  # get command, unalias it, and look it up in commands
  if cmd in aliases:
    if aliases[cmd] not in commands:
      raise errors.ProgrammerError("Alias '%s' maps to non-existing"
                                   " command '%s'" % (cmd, aliases[cmd]))

    cmd = aliases[cmd]

  if cmd in env_override:
    args_env_name = ("%s_%s" % (binary.replace("-", "_"), cmd)).upper()
    env_args = os.environ.get(args_env_name)
    if env_args:
      argv = utils.InsertAtPos(argv, 2, shlex.split(env_args))

  func, args_def, parser_opts, usage, description = commands[cmd]
  parser = OptionParser(option_list=parser_opts + COMMON_OPTS,
                        description=description,
                        formatter=TitledHelpFormatter(),
                        usage="%%prog %s %s" % (cmd, usage))
  parser.disable_interspersed_args()
  options, args = parser.parse_args(args=argv[2:])

  if not _CheckArguments(cmd, args_def, args):
    return None, None, None

  return func, options, args


def _FormatUsage(binary, commands):
  """Generates a nice description of all commands.

  @param binary: Script name
  @param commands: Dictionary containing command definitions

  """
  # compute the max line length for cmd + usage
  mlen = min(60, max(map(len, commands)))

  yield "Usage: %s {command} [options...] [argument...]" % binary
  yield "%s <command> --help to see details, or man %s" % (binary, binary)
  yield ""
  yield "Commands:"

  # and format a nice command list
  for (cmd, (_, _, _, _, help_text)) in sorted(commands.items()):
    help_lines = textwrap.wrap(help_text, 79 - 3 - mlen)
    yield " %-*s - %s" % (mlen, cmd, help_lines.pop(0))
    for line in help_lines:
      yield " %-*s   %s" % (mlen, "", line)

  yield ""


def _CheckArguments(cmd, args_def, args):
  """Verifies the arguments using the argument definition.

  Algorithm:

    1. Abort with error if values specified by user but none expected.

    1. For each argument in definition

      1. Keep running count of minimum number of values (min_count)
      1. Keep running count of maximum number of values (max_count)
      1. If it has an unlimited number of values

        1. Abort with error if it's not the last argument in the definition

    1. If last argument has limited number of values

      1. Abort with error if number of values doesn't match or is too large

    1. Abort with error if user didn't pass enough values (min_count)

  """
  if args and not args_def:
    ToStderr("Error: Command %s expects no arguments", cmd)
    return False

  min_count = None
  max_count = None
  check_max = None

  last_idx = len(args_def) - 1

  for idx, arg in enumerate(args_def):
    if min_count is None:
      min_count = arg.min
    elif arg.min is not None:
      min_count += arg.min

    if max_count is None:
      max_count = arg.max
    elif arg.max is not None:
      max_count += arg.max

    if idx == last_idx:
      check_max = (arg.max is not None)

    elif arg.max is None:
      raise errors.ProgrammerError("Only the last argument can have max=None")

  if check_max:
    # Command with exact number of arguments
    if (min_count is not None and max_count is not None and
        min_count == max_count and len(args) != min_count):
      ToStderr("Error: Command %s expects %d argument(s)", cmd, min_count)
      return False

    # Command with limited number of arguments
    if max_count is not None and len(args) > max_count:
      ToStderr("Error: Command %s expects only %d argument(s)",
               cmd, max_count)
      return False

  # Command with some required arguments
  if min_count is not None and len(args) < min_count:
    ToStderr("Error: Command %s expects at least %d argument(s)",
             cmd, min_count)
    return False

  return True


def SplitNodeOption(value):
  """Splits the value of a --node option.

  """
  if value and ":" in value:
    return value.split(":", 1)
  else:
    return (value, None)


def CalculateOSNames(os_name, os_variants):
  """Calculates all the names an OS can be called, according to its variants.

  @type os_name: string
  @param os_name: base name of the os
  @type os_variants: list or None
  @param os_variants: list of supported variants
  @rtype: list
  @return: list of valid names

  """
  if os_variants:
    return ["%s+%s" % (os_name, v) for v in os_variants]
  else:
    return [os_name]


def ParseFields(selected, default):
  """Parses the values of "--field"-like options.

  @type selected: string or None
  @param selected: User-selected options
  @type default: list
  @param default: Default fields

  """
  if selected is None:
    return default

  if selected.startswith("+"):
    return default + selected[1:].split(",")

  return selected.split(",")


def AskUser(text, choices=None):
  """Ask the user a question.

  @param text: the question to ask

  @param choices: list with elements tuples (input_char, return_value,
      description); if not given, it will default to: [('y', True,
      'Perform the operation'), ('n', False, 'Do no do the operation')];
      note that the '?' char is reserved for help

  @return: one of the return values from the choices list; if input is
      not possible (i.e. not running with a tty, we return the last
      entry from the list

  """
  if choices is None:
    choices = [("y", True, "Perform the operation"),
               ("n", False, "Do not perform the operation")]
  if not choices or not isinstance(choices, list):
    raise errors.ProgrammerError("Invalid choices argument to AskUser")
  for entry in choices:
    if not isinstance(entry, tuple) or len(entry) < 3 or entry[0] == "?":
      raise errors.ProgrammerError("Invalid choices element to AskUser")

  answer = choices[-1][1]
  new_text = []
  for line in text.splitlines():
    new_text.append(textwrap.fill(line, 70, replace_whitespace=False))
  text = "\n".join(new_text)
  try:
    f = file("/dev/tty", "a+")
  except IOError:
    return answer
  try:
    chars = [entry[0] for entry in choices]
    chars[-1] = "[%s]" % chars[-1]
    chars.append("?")
    maps = dict([(entry[0], entry[1]) for entry in choices])
    while True:
      f.write(text)
      f.write("\n")
      f.write("/".join(chars))
      f.write(": ")
      line = f.readline(2).strip().lower()
      if line in maps:
        answer = maps[line]
        break
      elif line == "?":
        for entry in choices:
          f.write(" %s - %s\n" % (entry[0], entry[2]))
        f.write("\n")
        continue
  finally:
    f.close()
  return answer


def SendJob(ops, cl=None):
  """Function to submit an opcode without waiting for the results.

  @type ops: list
  @param ops: list of opcodes
  @type cl: luxi.Client
  @param cl: the luxi client to use for communicating with the master;
             if None, a new client will be created

  """
  if cl is None:
    cl = GetClient()

  job_id = cl.SubmitJob(ops)

  return job_id


def GenericPollJob(job_id, cbs, report_cbs, cancel_fn=None,
                   update_freq=constants.DEFAULT_WFJC_TIMEOUT):
  """Generic job-polling function.

  @type job_id: number
  @param job_id: Job ID
  @type cbs: Instance of L{JobPollCbBase}
  @param cbs: Data callbacks
  @type report_cbs: Instance of L{JobPollReportCbBase}
  @param report_cbs: Reporting callbacks
  @type cancel_fn: Function returning a boolean
  @param cancel_fn: Function to check if we should cancel the running job
  @type update_freq: int/long
  @param update_freq: number of seconds between each WFJC reports
  @return: the opresult of the job
  @raise errors.JobLost: If job can't be found
  @raise errors.JobCanceled: If job is canceled
  @raise errors.OpExecError: If job didn't succeed

  """
  prev_job_info = None
  prev_logmsg_serial = None

  status = None
  should_cancel = False

  if update_freq <= 0:
    raise errors.ParameterError("Update frequency must be a positive number")

  while True:
    if cancel_fn:
      timer = 0
      while timer < update_freq:
        result = cbs.WaitForJobChangeOnce(job_id, ["status"], prev_job_info,
                                          prev_logmsg_serial,
                                          timeout=constants.CLI_WFJC_FREQUENCY)
        should_cancel = cancel_fn()
        if should_cancel or not result or result != constants.JOB_NOTCHANGED:
          break
        timer += constants.CLI_WFJC_FREQUENCY
    else:
      result = cbs.WaitForJobChangeOnce(job_id, ["status"], prev_job_info,
                                        prev_logmsg_serial, timeout=update_freq)
    if not result:
      # job not found, go away!
      raise errors.JobLost("Job with id %s lost" % job_id)

    if should_cancel:
      logging.info("Job %s canceled because the client timed out.", job_id)
      cbs.CancelJob(job_id)
      raise errors.JobCanceled("Job was canceled")

    if result == constants.JOB_NOTCHANGED:
      report_cbs.ReportNotChanged(job_id, status)
      # Wait again
      continue

    # Split result, a tuple of (field values, log entries)
    (job_info, log_entries) = result
    (status, ) = job_info

    if log_entries:
      for log_entry in log_entries:
        (serial, timestamp, log_type, message) = log_entry
        report_cbs.ReportLogMessage(job_id, serial, timestamp,
                                    log_type, message)
        prev_logmsg_serial = max(prev_logmsg_serial, serial)

    # TODO: Handle canceled and archived jobs
    elif status in (constants.JOB_STATUS_SUCCESS,
                    constants.JOB_STATUS_ERROR,
                    constants.JOB_STATUS_CANCELING,
                    constants.JOB_STATUS_CANCELED):
      break

    prev_job_info = job_info

  jobs = cbs.QueryJobs([job_id], ["status", "opstatus", "opresult"])
  if not jobs:
    raise errors.JobLost("Job with id %s lost" % job_id)

  status, opstatus, result = jobs[0]

  if status == constants.JOB_STATUS_SUCCESS:
    return result

  if status in (constants.JOB_STATUS_CANCELING, constants.JOB_STATUS_CANCELED):
    raise errors.JobCanceled("Job was canceled")

  has_ok = False
  for idx, (status, msg) in enumerate(zip(opstatus, result)):
    if status == constants.OP_STATUS_SUCCESS:
      has_ok = True
    elif status == constants.OP_STATUS_ERROR:
      errors.MaybeRaise(msg)

      if has_ok:
        raise errors.OpExecError("partial failure (opcode %d): %s" %
                                 (idx, msg))

      raise errors.OpExecError(str(msg))

  # default failure mode
  raise errors.OpExecError(result)


class JobPollCbBase(object):
  """Base class for L{GenericPollJob} callbacks.

  """
  def __init__(self):
    """Initializes this class.

    """

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial,
                           timeout=constants.DEFAULT_WFJC_TIMEOUT):
    """Waits for changes on a job.

    """
    raise NotImplementedError()

  def QueryJobs(self, job_ids, fields):
    """Returns the selected fields for the selected job IDs.

    @type job_ids: list of numbers
    @param job_ids: Job IDs
    @type fields: list of strings
    @param fields: Fields

    """
    raise NotImplementedError()

  def CancelJob(self, job_id):
    """Cancels a currently running job.

    @type job_id: number
    @param job_id: The ID of the Job we want to cancel

    """
    raise NotImplementedError()


class JobPollReportCbBase(object):
  """Base class for L{GenericPollJob} reporting callbacks.

  """
  def __init__(self):
    """Initializes this class.

    """

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    raise NotImplementedError()

  def ReportNotChanged(self, job_id, status):
    """Called for if a job hasn't changed in a while.

    @type job_id: number
    @param job_id: Job ID
    @type status: string or None
    @param status: Job status if available

    """
    raise NotImplementedError()


class _LuxiJobPollCb(JobPollCbBase):
  def __init__(self, cl):
    """Initializes this class.

    """
    JobPollCbBase.__init__(self)
    self.cl = cl

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial,
                           timeout=constants.DEFAULT_WFJC_TIMEOUT):
    """Waits for changes on a job.

    """
    return self.cl.WaitForJobChangeOnce(job_id, fields,
                                        prev_job_info, prev_log_serial,
                                        timeout=timeout)

  def QueryJobs(self, job_ids, fields):
    """Returns the selected fields for the selected job IDs.

    """
    return self.cl.QueryJobs(job_ids, fields)

  def CancelJob(self, job_id):
    """Cancels a currently running job.

    """
    return self.cl.CancelJob(job_id)


class FeedbackFnJobPollReportCb(JobPollReportCbBase):
  def __init__(self, feedback_fn):
    """Initializes this class.

    """
    JobPollReportCbBase.__init__(self)

    self.feedback_fn = feedback_fn

    assert callable(feedback_fn)

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    self.feedback_fn((timestamp, log_type, log_msg))

  def ReportNotChanged(self, job_id, status):
    """Called if a job hasn't changed in a while.

    """
    # Ignore


class StdioJobPollReportCb(JobPollReportCbBase):
  def __init__(self):
    """Initializes this class.

    """
    JobPollReportCbBase.__init__(self)

    self.notified_queued = False
    self.notified_waitlock = False

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    ToStdout("%s %s", time.ctime(utils.MergeTime(timestamp)),
             FormatLogMessage(log_type, log_msg))

  def ReportNotChanged(self, job_id, status):
    """Called if a job hasn't changed in a while.

    """
    if status is None:
      return

    if status == constants.JOB_STATUS_QUEUED and not self.notified_queued:
      ToStderr("Job %s is waiting in queue", job_id)
      self.notified_queued = True

    elif status == constants.JOB_STATUS_WAITING and not self.notified_waitlock:
      ToStderr("Job %s is trying to acquire all necessary locks", job_id)
      self.notified_waitlock = True


def FormatLogMessage(log_type, log_msg):
  """Formats a job message according to its type.

  """
  if log_type != constants.ELOG_MESSAGE:
    log_msg = str(log_msg)

  return utils.SafeEncode(log_msg)


def PollJob(job_id, cl=None, feedback_fn=None, reporter=None, cancel_fn=None,
            update_freq=constants.DEFAULT_WFJC_TIMEOUT):
  """Function to poll for the result of a job.

  @type job_id: job identified
  @param job_id: the job to poll for results
  @type cl: luxi.Client
  @param cl: the luxi client to use for communicating with the master;
             if None, a new client will be created
  @type cancel_fn: Function returning a boolean
  @param cancel_fn: Function to check if we should cancel the running job
  @type update_freq: int/long
  @param update_freq: number of seconds between each WFJC report

  """
  if cl is None:
    cl = GetClient()

  if reporter is None:
    if feedback_fn:
      reporter = FeedbackFnJobPollReportCb(feedback_fn)
    else:
      reporter = StdioJobPollReportCb()
  elif feedback_fn:
    raise errors.ProgrammerError("Can't specify reporter and feedback function")

  return GenericPollJob(job_id, _LuxiJobPollCb(cl), reporter,
                        cancel_fn=cancel_fn, update_freq=update_freq)


def SubmitOpCode(op, cl=None, feedback_fn=None, opts=None, reporter=None):
  """Legacy function to submit an opcode.

  This is just a simple wrapper over the construction of the processor
  instance. It should be extended to better handle feedback and
  interaction functions.

  """
  if cl is None:
    cl = GetClient()

  SetGenericOpcodeOpts([op], opts)

  job_id = SendJob([op], cl=cl)
  if hasattr(opts, "print_jobid") and opts.print_jobid:
    ToStdout("%d" % job_id)

  op_results = PollJob(job_id, cl=cl, feedback_fn=feedback_fn,
                       reporter=reporter)

  return op_results[0]


def SubmitOpCodeToDrainedQueue(op):
  """Forcefully insert a job in the queue, even if it is drained.

  """
  cl = GetClient()
  job_id = cl.SubmitJobToDrainedQueue([op])
  op_results = PollJob(job_id, cl=cl)
  return op_results[0]


def SubmitOrSend(op, opts, cl=None, feedback_fn=None):
  """Wrapper around SubmitOpCode or SendJob.

  This function will decide, based on the 'opts' parameter, whether to
  submit and wait for the result of the opcode (and return it), or
  whether to just send the job and print its identifier. It is used in
  order to simplify the implementation of the '--submit' option.

  It will also process the opcodes if we're sending the via SendJob
  (otherwise SubmitOpCode does it).

  """
  if opts and opts.submit_only:
    job = [op]
    SetGenericOpcodeOpts(job, opts)
    job_id = SendJob(job, cl=cl)
    if opts.print_jobid:
      ToStdout("%d" % job_id)
    raise errors.JobSubmittedException(job_id)
  else:
    return SubmitOpCode(op, cl=cl, feedback_fn=feedback_fn, opts=opts)


def _InitReasonTrail(op, opts):
  """Builds the first part of the reason trail

  Builds the initial part of the reason trail, adding the user provided reason
  (if it exists) and the name of the command starting the operation.

  @param op: the opcode the reason trail will be added to
  @param opts: the command line options selected by the user

  """
  assert len(sys.argv) >= 2
  trail = []

  if opts.reason:
    trail.append((constants.OPCODE_REASON_SRC_USER,
                  opts.reason,
                  utils.EpochNano()))

  binary = os.path.basename(sys.argv[0])
  source = "%s:%s" % (constants.OPCODE_REASON_SRC_CLIENT, binary)
  command = sys.argv[1]
  trail.append((source, command, utils.EpochNano()))
  op.reason = trail


def SetGenericOpcodeOpts(opcode_list, options):
  """Processor for generic options.

  This function updates the given opcodes based on generic command
  line options (like debug, dry-run, etc.).

  @param opcode_list: list of opcodes
  @param options: command line options or None
  @return: None (in-place modification)

  """
  if not options:
    return
  for op in opcode_list:
    op.debug_level = options.debug
    if hasattr(options, "dry_run"):
      op.dry_run = options.dry_run
    if getattr(options, "priority", None) is not None:
      op.priority = options.priority
    _InitReasonTrail(op, options)


def FormatError(err):
  """Return a formatted error message for a given error.

  This function takes an exception instance and returns a tuple
  consisting of two values: first, the recommended exit code, and
  second, a string describing the error message (not
  newline-terminated).

  """
  retcode = 1
  obuf = StringIO()
  msg = str(err)
  if isinstance(err, errors.ConfigurationError):
    txt = "Corrupt configuration file: %s" % msg
    logging.error(txt)
    obuf.write(txt + "\n")
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
    obuf.write("Failure: hooks general failure: %s" % msg)
  elif isinstance(err, errors.ResolverError):
    this_host = netutils.Hostname.GetSysName()
    if err.args[0] == this_host:
      msg = "Failure: can't resolve my own hostname ('%s')"
    else:
      msg = "Failure: can't resolve hostname '%s'"
    obuf.write(msg % err.args[0])
  elif isinstance(err, errors.OpPrereqError):
    if len(err.args) == 2:
      obuf.write("Failure: prerequisites not met for this"
                 " operation:\nerror type: %s, error details:\n%s" %
                 (err.args[1], err.args[0]))
    else:
      obuf.write("Failure: prerequisites not met for this"
                 " operation:\n%s" % msg)
  elif isinstance(err, errors.OpExecError):
    obuf.write("Failure: command execution error:\n%s" % msg)
  elif isinstance(err, errors.TagError):
    obuf.write("Failure: invalid tag(s) given:\n%s" % msg)
  elif isinstance(err, errors.JobQueueDrainError):
    obuf.write("Failure: the job queue is marked for drain and doesn't"
               " accept new requests\n")
  elif isinstance(err, errors.JobQueueFull):
    obuf.write("Failure: the job queue is full and doesn't accept new"
               " job submissions until old jobs are archived\n")
  elif isinstance(err, errors.TypeEnforcementError):
    obuf.write("Parameter Error: %s" % msg)
  elif isinstance(err, errors.ParameterError):
    obuf.write("Failure: unknown/wrong parameter name '%s'" % msg)
  elif isinstance(err, rpcerr.NoMasterError):
    if err.args[0] == pathutils.MASTER_SOCKET:
      daemon = "the master daemon"
    elif err.args[0] == pathutils.QUERY_SOCKET:
      daemon = "the config daemon"
    else:
      daemon = "socket '%s'" % str(err.args[0])
    obuf.write("Cannot communicate with %s.\nIs the process running"
               " and listening for connections?" % daemon)
  elif isinstance(err, rpcerr.TimeoutError):
    obuf.write("Timeout while talking to the master daemon. Jobs might have"
               " been submitted and will continue to run even if the call"
               " timed out. Useful commands in this situation are \"gnt-job"
               " list\", \"gnt-job cancel\" and \"gnt-job watch\". Error:\n")
    obuf.write(msg)
  elif isinstance(err, rpcerr.PermissionError):
    obuf.write("It seems you don't have permissions to connect to the"
               " master daemon.\nPlease retry as a different user.")
  elif isinstance(err, rpcerr.ProtocolError):
    obuf.write("Unhandled protocol error while talking to the master daemon:\n"
               "%s" % msg)
  elif isinstance(err, errors.JobLost):
    obuf.write("Error checking job status: %s" % msg)
  elif isinstance(err, errors.QueryFilterParseError):
    obuf.write("Error while parsing query filter: %s\n" % err.args[0])
    obuf.write("\n".join(err.GetDetails()))
  elif isinstance(err, errors.GenericError):
    obuf.write("Unhandled Ganeti error: %s" % msg)
  elif isinstance(err, errors.JobSubmittedException):
    obuf.write("JobID: %s\n" % err.args[0])
    retcode = 0
  else:
    obuf.write("Unhandled exception: %s" % msg)
  return retcode, obuf.getvalue().rstrip("\n")


def GenericMain(commands, override=None, aliases=None,
                env_override=frozenset()):
  """Generic main function for all the gnt-* commands.

  @param commands: a dictionary with a special structure, see the design doc
                   for command line handling.
  @param override: if not None, we expect a dictionary with keys that will
                   override command line options; this can be used to pass
                   options from the scripts to generic functions
  @param aliases: dictionary with command aliases {'alias': 'target, ...}
  @param env_override: list of environment names which are allowed to submit
                       default args for commands

  """
  # save the program name and the entire command line for later logging
  if sys.argv:
    binary = os.path.basename(sys.argv[0])
    if not binary:
      binary = sys.argv[0]

    if len(sys.argv) >= 2:
      logname = utils.ShellQuoteArgs([binary, sys.argv[1]])
    else:
      logname = binary

    cmdline = utils.ShellQuoteArgs([binary] + sys.argv[1:])
  else:
    binary = "<unknown program>"
    cmdline = "<unknown>"

  if aliases is None:
    aliases = {}

  try:
    (func, options, args) = _ParseArgs(binary, sys.argv, commands, aliases,
                                       env_override)
  except _ShowVersion:
    ToStdout("%s (ganeti %s) %s", binary, constants.VCS_VERSION,
             constants.RELEASE_VERSION)
    return constants.EXIT_SUCCESS
  except _ShowUsage as err:
    for line in _FormatUsage(binary, commands):
      ToStdout(line)

    if err.exit_error:
      return constants.EXIT_FAILURE
    else:
      return constants.EXIT_SUCCESS
  except errors.ParameterError as err:
    result, err_msg = FormatError(err)
    ToStderr(err_msg)
    return 1

  if func is None: # parse error
    return 1

  if override is not None:
    for key, val in override.items():
      setattr(options, key, val)

  utils.SetupLogging(pathutils.LOG_COMMANDS, logname, debug=options.debug,
                     stderr_logging=True)

  logging.debug("Command line: %s", cmdline)

  try:
    result = func(options, args)
  except (errors.GenericError, rpcerr.ProtocolError,
          errors.JobSubmittedException) as err:
    result, err_msg = FormatError(err)
    logging.exception("Error during command processing")
    ToStderr(err_msg)
  except KeyboardInterrupt:
    result = constants.EXIT_FAILURE
    ToStderr("Aborted. Note that if the operation created any jobs, they"
             " might have been submitted and"
             " will continue to run in the background.")
  except IOError as err:
    if err.errno == errno.EPIPE:
      # our terminal went away, we'll exit
      sys.exit(constants.EXIT_FAILURE)
    else:
      raise

  return result


def ParseNicOption(optvalue):
  """Parses the value of the --net option(s).

  """
  try:
    nic_max = max(int(nidx[0]) + 1 for nidx in optvalue)
  except (TypeError, ValueError) as err:
    raise errors.OpPrereqError("Invalid NIC index passed: %s" % str(err),
                               errors.ECODE_INVAL)

  nics = [{}] * nic_max
  for nidx, ndict in optvalue:
    nidx = int(nidx)

    if not isinstance(ndict, dict):
      raise errors.OpPrereqError("Invalid nic/%d value: expected dict,"
                                 " got %s" % (nidx, ndict), errors.ECODE_INVAL)

    utils.ForceDictType(ndict, constants.INIC_PARAMS_TYPES)

    nics[nidx] = ndict

  return nics


def FixHvParams(hvparams):
  # In Ganeti 2.8.4 the separator for the usb_devices hvparam was changed from
  # comma to space because commas cannot be accepted on the command line
  # (they already act as the separator between different hvparams). Still,
  # RAPI should be able to accept commas for backwards compatibility.
  # Therefore, we convert spaces into commas here, and we keep the old
  # parsing logic everywhere else.
  try:
    new_usb_devices = hvparams[constants.HV_USB_DEVICES].replace(" ", ",")
    hvparams[constants.HV_USB_DEVICES] = new_usb_devices
  except KeyError:
    #No usb_devices, no modification required
    pass


def GenericInstanceCreate(mode, opts, args):
  """Add an instance to the cluster via either creation or import.

  @param mode: constants.INSTANCE_CREATE or constants.INSTANCE_IMPORT
  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the new instance name
  @rtype: int
  @return: the desired exit code

  """
  instance = args[0]
  forthcoming = opts.ensure_value("forthcoming", False)
  commit = opts.ensure_value("commit", False)

  if forthcoming and commit:
    raise errors.OpPrereqError("Creating an instance only forthcoming and"
                               " commiting it are mutally exclusive",
                               errors.ECODE_INVAL)

  (pnode, snode) = SplitNodeOption(opts.node)

  hypervisor = None
  hvparams = {}
  if opts.hypervisor:
    hypervisor, hvparams = opts.hypervisor

  if opts.nics:
    nics = ParseNicOption(opts.nics)
  elif opts.no_nics:
    # no nics
    nics = []
  elif mode == constants.INSTANCE_CREATE:
    # default of one nic, all auto
    nics = [{}]
  else:
    # mode == import
    nics = []

  if opts.disk_template == constants.DT_DISKLESS:
    if opts.disks or opts.sd_size is not None:
      raise errors.OpPrereqError("Diskless instance but disk"
                                 " information passed", errors.ECODE_INVAL)
    disks = []
  else:
    if (not opts.disks and not opts.sd_size
        and mode == constants.INSTANCE_CREATE):
      raise errors.OpPrereqError("No disk information specified",
                                 errors.ECODE_INVAL)
    if opts.disks and opts.sd_size is not None:
      raise errors.OpPrereqError("Please use either the '--disk' or"
                                 " '-s' option", errors.ECODE_INVAL)
    if opts.sd_size is not None:
      opts.disks = [(0, {constants.IDISK_SIZE: opts.sd_size})]

    if opts.disks:
      try:
        disk_max = max(int(didx[0]) + 1 for didx in opts.disks)
      except ValueError as err:
        raise errors.OpPrereqError("Invalid disk index passed: %s" % str(err),
                                   errors.ECODE_INVAL)
      disks = [{}] * disk_max
    else:
      disks = []
    for didx, ddict in opts.disks:
      didx = int(didx)
      if not isinstance(ddict, dict):
        msg = "Invalid disk/%d value: expected dict, got %s" % (didx, ddict)
        raise errors.OpPrereqError(msg, errors.ECODE_INVAL)
      elif constants.IDISK_SIZE in ddict:
        if constants.IDISK_ADOPT in ddict:
          raise errors.OpPrereqError("Only one of 'size' and 'adopt' allowed"
                                     " (disk %d)" % didx, errors.ECODE_INVAL)
        try:
          ddict[constants.IDISK_SIZE] = \
            utils.ParseUnit(ddict[constants.IDISK_SIZE])
        except ValueError as err:
          raise errors.OpPrereqError("Invalid disk size for disk %d: %s" %
                                     (didx, err), errors.ECODE_INVAL)
      elif constants.IDISK_ADOPT in ddict:
        if constants.IDISK_SPINDLES in ddict:
          raise errors.OpPrereqError("spindles is not a valid option when"
                                     " adopting a disk", errors.ECODE_INVAL)
        if mode == constants.INSTANCE_IMPORT:
          raise errors.OpPrereqError("Disk adoption not allowed for instance"
                                     " import", errors.ECODE_INVAL)
        ddict[constants.IDISK_SIZE] = 0
      else:
        raise errors.OpPrereqError("Missing size or adoption source for"
                                   " disk %d" % didx, errors.ECODE_INVAL)
      if constants.IDISK_SPINDLES in ddict:
        ddict[constants.IDISK_SPINDLES] = int(ddict[constants.IDISK_SPINDLES])

      disks[didx] = ddict

  if opts.tags is not None:
    tags = opts.tags.split(",")
  else:
    tags = []

  utils.ForceDictType(opts.beparams, constants.BES_PARAMETER_COMPAT)
  utils.ForceDictType(hvparams, constants.HVS_PARAMETER_TYPES)
  FixHvParams(hvparams)

  osparams_private = opts.osparams_private or serializer.PrivateDict()
  osparams_secret = opts.osparams_secret or serializer.PrivateDict()

  helper_startup_timeout = opts.helper_startup_timeout
  helper_shutdown_timeout = opts.helper_shutdown_timeout

  if mode == constants.INSTANCE_CREATE:
    start = opts.start
    os_type = opts.os
    force_variant = opts.force_variant
    src_node = None
    src_path = None
    no_install = opts.no_install
    identify_defaults = False
    compress = constants.IEC_NONE
    if opts.instance_communication is None:
      instance_communication = False
    else:
      instance_communication = opts.instance_communication
  elif mode == constants.INSTANCE_IMPORT:
    if forthcoming:
      raise errors.OpPrereqError("forthcoming instances can only be created,"
                                 " not imported")
    start = False
    os_type = None
    force_variant = False
    src_node = opts.src_node
    src_path = opts.src_dir
    no_install = None
    identify_defaults = opts.identify_defaults
    compress = opts.compress
    instance_communication = False
  else:
    raise errors.ProgrammerError("Invalid creation mode %s" % mode)

  op = opcodes.OpInstanceCreate(
    forthcoming=forthcoming,
    commit=commit,
    instance_name=instance,
    disks=disks,
    disk_template=opts.disk_template,
    group_name=opts.nodegroup,
    nics=nics,
    conflicts_check=opts.conflicts_check,
    pnode=pnode, snode=snode,
    ip_check=opts.ip_check,
    name_check=opts.name_check,
    wait_for_sync=opts.wait_for_sync,
    file_storage_dir=opts.file_storage_dir,
    file_driver=opts.file_driver,
    iallocator=opts.iallocator,
    hypervisor=hypervisor,
    hvparams=hvparams,
    beparams=opts.beparams,
    osparams=opts.osparams,
    osparams_private=osparams_private,
    osparams_secret=osparams_secret,
    mode=mode,
    opportunistic_locking=opts.opportunistic_locking,
    start=start,
    os_type=os_type,
    force_variant=force_variant,
    src_node=src_node,
    src_path=src_path,
    compress=compress,
    tags=tags,
    no_install=no_install,
    identify_defaults=identify_defaults,
    ignore_ipolicy=opts.ignore_ipolicy,
    instance_communication=instance_communication,
    helper_startup_timeout=helper_startup_timeout,
    helper_shutdown_timeout=helper_shutdown_timeout)

  SubmitOrSend(op, opts)
  return 0


class _RunWhileDaemonsStoppedHelper(object):
  """Helper class for L{RunWhileDaemonsStopped} to simplify state management

  """
  def __init__(self, feedback_fn, cluster_name, master_node,
               online_nodes, ssh_ports, exclude_daemons, debug,
               verbose):
    """Initializes this class.

    @type feedback_fn: callable
    @param feedback_fn: Feedback function
    @type cluster_name: string
    @param cluster_name: Cluster name
    @type master_node: string
    @param master_node Master node name
    @type online_nodes: list
    @param online_nodes: List of names of online nodes
    @type ssh_ports: list
    @param ssh_ports: List of SSH ports of online nodes
    @type exclude_daemons: list of string
    @param exclude_daemons: list of daemons that will be restarted on master
                            after all others are shutdown
    @type debug: boolean
    @param debug: show debug output
    @type verbose: boolesn
    @param verbose: show verbose output

    """
    self.feedback_fn = feedback_fn
    self.cluster_name = cluster_name
    self.master_node = master_node
    self.online_nodes = online_nodes
    self.ssh_ports = dict(zip(online_nodes, ssh_ports))

    self.ssh = ssh.SshRunner(self.cluster_name)

    self.nonmaster_nodes = [name for name in online_nodes
                            if name != master_node]

    self.exclude_daemons = exclude_daemons
    self.debug = debug
    self.verbose = verbose

    assert self.master_node not in self.nonmaster_nodes

  def _RunCmd(self, node_name, cmd):
    """Runs a command on the local or a remote machine.

    @type node_name: string
    @param node_name: Machine name
    @type cmd: list
    @param cmd: Command

    """
    if node_name is None or node_name == self.master_node:
      # No need to use SSH
      result = utils.RunCmd(cmd)
    else:
      result = self.ssh.Run(node_name, constants.SSH_LOGIN_USER,
                            utils.ShellQuoteArgs(cmd),
                            port=self.ssh_ports[node_name])

    if result.failed:
      errmsg = ["Failed to run command %s" % result.cmd]
      if node_name:
        errmsg.append("on node %s" % node_name)
      errmsg.append(": exitcode %s and error %s" %
                    (result.exit_code, result.output))
      raise errors.OpExecError(" ".join(errmsg))

  def Call(self, fn, *args):
    """Call function while all daemons are stopped.

    @type fn: callable
    @param fn: Function to be called

    """
    # Pause watcher by acquiring an exclusive lock on watcher state file
    self.feedback_fn("Blocking watcher")
    watcher_block = utils.FileLock.Open(pathutils.WATCHER_LOCK_FILE)
    try:
      # TODO: Currently, this just blocks. There's no timeout.
      # TODO: Should it be a shared lock?
      watcher_block.Exclusive(blocking=True)

      # Stop master daemons, so that no new jobs can come in and all running
      # ones are finished
      self.feedback_fn("Stopping master daemons")
      self._RunCmd(None, [pathutils.DAEMON_UTIL, "stop-master"])
      try:
        # Stop daemons on all nodes
        online_nodes = [self.master_node] + [n for n in self.online_nodes
                                             if n != self.master_node]
        for node_name in online_nodes:
          self.feedback_fn("Stopping daemons on %s" % node_name)
          self._RunCmd(node_name, [pathutils.DAEMON_UTIL, "stop-all"])
          # Starting any daemons listed as exception
          if node_name == self.master_node:
            for daemon in self.exclude_daemons:
              self.feedback_fn("Starting daemon '%s' on %s" % (daemon,
                                                               node_name))
              self._RunCmd(node_name, [pathutils.DAEMON_UTIL, "start", daemon])

        # All daemons are shut down now
        try:
          return fn(self, *args)
        except Exception as err:
          _, errmsg = FormatError(err)
          logging.exception("Caught exception")
          self.feedback_fn(errmsg)
          raise
      finally:
        # Start cluster again, master node last
        for node_name in self.nonmaster_nodes + [self.master_node]:
          # Stopping any daemons listed as exception.
          # This might look unnecessary, but it makes sure that daemon-util
          # starts all daemons in the right order.
          if node_name == self.master_node:
            self.exclude_daemons.reverse()
            for daemon in self.exclude_daemons:
              self.feedback_fn("Stopping daemon '%s' on %s" % (daemon,
                                                               node_name))
              self._RunCmd(node_name, [pathutils.DAEMON_UTIL, "stop", daemon])
          self.feedback_fn("Starting daemons on %s" % node_name)
          self._RunCmd(node_name, [pathutils.DAEMON_UTIL, "start-all"])

    finally:
      # Resume watcher
      watcher_block.Close()


def RunWhileDaemonsStopped(feedback_fn, exclude_daemons, fn, *args, **kwargs):
  """Calls a function while all cluster daemons are stopped.

  @type feedback_fn: callable
  @param feedback_fn: Feedback function
  @type exclude_daemons: list of string
  @param exclude_daemons: list of daemons that stopped, but immediately
                          restarted on the master to be available when calling
                          'fn'. If None, all daemons will be stopped and none
                          will be started before calling 'fn'.
  @type fn: callable
  @param fn: Function to be called when daemons are stopped

  """
  feedback_fn("Gathering cluster information")

  # This ensures we're running on the master daemon
  cl = GetClient()

  (cluster_name, master_node) = \
    cl.QueryConfigValues(["cluster_name", "master_node"])

  online_nodes = GetOnlineNodes([], cl=cl)
  ssh_ports = GetNodesSshPorts(online_nodes, cl)

  # Don't keep a reference to the client. The master daemon will go away.
  del cl

  assert master_node in online_nodes
  if exclude_daemons is None:
    exclude_daemons = []

  debug = kwargs.get("debug", False)
  verbose = kwargs.get("verbose", False)

  return _RunWhileDaemonsStoppedHelper(
      feedback_fn, cluster_name, master_node, online_nodes, ssh_ports,
      exclude_daemons, debug, verbose).Call(fn, *args)


def RunWhileClusterStopped(feedback_fn, fn, *args):
  """Calls a function while all cluster daemons are stopped.

  @type feedback_fn: callable
  @param feedback_fn: Feedback function
  @type fn: callable
  @param fn: Function to be called when daemons are stopped

  """
  RunWhileDaemonsStopped(feedback_fn, None, fn, *args)


def GenerateTable(headers, fields, separator, data,
                  numfields=None, unitfields=None,
                  units=None):
  """Prints a table with headers and different fields.

  @type headers: dict
  @param headers: dictionary mapping field names to headers for
      the table
  @type fields: list
  @param fields: the field names corresponding to each row in
      the data field
  @param separator: the separator to be used; if this is None,
      the default 'smart' algorithm is used which computes optimal
      field width, otherwise just the separator is used between
      each field
  @type data: list
  @param data: a list of lists, each sublist being one row to be output
  @type numfields: list
  @param numfields: a list with the fields that hold numeric
      values and thus should be right-aligned
  @type unitfields: list
  @param unitfields: a list with the fields that hold numeric
      values that should be formatted with the units field
  @type units: string or None
  @param units: the units we should use for formatting, or None for
      automatic choice (human-readable for non-separator usage, otherwise
      megabytes); this is a one-letter string

  """
  if units is None:
    if separator:
      units = "m"
    else:
      units = "h"

  if numfields is None:
    numfields = []
  if unitfields is None:
    unitfields = []

  numfields = utils.FieldSet(*numfields)
  unitfields = utils.FieldSet(*unitfields)

  format_fields = []
  for field in fields:
    if headers and field not in headers:
      # TODO: handle better unknown fields (either revert to old
      # style of raising exception, or deal more intelligently with
      # variable fields)
      headers[field] = field
    if separator is not None:
      format_fields.append("%s")
    elif numfields.Matches(field):
      format_fields.append("%*s")
    else:
      format_fields.append("%-*s")

  if separator is None:
    mlens = [0 for name in fields]
    format_str = " ".join(format_fields)
  else:
    format_str = separator.replace("%", "%%").join(format_fields)

  for row in data:
    if row is None:
      continue
    for idx, val in enumerate(row):
      if unitfields.Matches(fields[idx]):
        try:
          val = int(val)
        except (TypeError, ValueError):
          pass
        else:
          val = row[idx] = utils.FormatUnit(val, units)
      val = row[idx] = str(val)
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
    result.append(format_str % tuple(args))

  if separator is None:
    assert len(mlens) == len(fields)

    if fields and not numfields.Matches(fields[-1]):
      mlens[-1] = 0

  for line in data:
    args = []
    if line is None:
      line = ["-" for _ in fields]
    for idx in range(len(fields)):
      if separator is None:
        args.append(mlens[idx])
      args.append(line[idx])
    result.append(format_str % tuple(args))

  return result


def _FormatBool(value):
  """Formats a boolean value as a string.

  """
  if value:
    return "Y"
  return "N"


#: Default formatting for query results; (callback, align right)
_DEFAULT_FORMAT_QUERY = {
  constants.QFT_TEXT: (str, False),
  constants.QFT_BOOL: (_FormatBool, False),
  constants.QFT_NUMBER: (str, True),
  constants.QFT_NUMBER_FLOAT: (str, True),
  constants.QFT_TIMESTAMP: (utils.FormatTime, False),
  constants.QFT_OTHER: (str, False),
  constants.QFT_UNKNOWN: (str, False),
  }


def _GetColumnFormatter(fdef, override, unit):
  """Returns formatting function for a field.

  @type fdef: L{objects.QueryFieldDefinition}
  @type override: dict
  @param override: Dictionary for overriding field formatting functions,
    indexed by field name, contents like L{_DEFAULT_FORMAT_QUERY}
  @type unit: string
  @param unit: Unit used for formatting fields of type L{constants.QFT_UNIT}
  @rtype: tuple; (callable, bool)
  @return: Returns the function to format a value (takes one parameter) and a
    boolean for aligning the value on the right-hand side

  """
  fmt = override.get(fdef.name, None)
  if fmt is not None:
    return fmt

  assert constants.QFT_UNIT not in _DEFAULT_FORMAT_QUERY

  if fdef.kind == constants.QFT_UNIT:
    # Can't keep this information in the static dictionary
    return (lambda value: utils.FormatUnit(value, unit), True)

  fmt = _DEFAULT_FORMAT_QUERY.get(fdef.kind, None)
  if fmt is not None:
    return fmt

  raise NotImplementedError("Can't format column type '%s'" % fdef.kind)


class _QueryColumnFormatter(object):
  """Callable class for formatting fields of a query.

  """
  def __init__(self, fn, status_fn, verbose):
    """Initializes this class.

    @type fn: callable
    @param fn: Formatting function
    @type status_fn: callable
    @param status_fn: Function to report fields' status
    @type verbose: boolean
    @param verbose: whether to use verbose field descriptions or not

    """
    self._fn = fn
    self._status_fn = status_fn
    self._verbose = verbose

  def __call__(self, data):
    """Returns a field's string representation.

    """
    (status, value) = data

    # Report status
    self._status_fn(status)

    if status == constants.RS_NORMAL:
      return self._fn(value)

    assert value is None, \
           "Found value %r for abnormal status %s" % (value, status)

    return FormatResultError(status, self._verbose)


def FormatResultError(status, verbose):
  """Formats result status other than L{constants.RS_NORMAL}.

  @param status: The result status
  @type verbose: boolean
  @param verbose: Whether to return the verbose text
  @return: Text of result status

  """
  assert status != constants.RS_NORMAL, \
         "FormatResultError called with status equal to constants.RS_NORMAL"
  try:
    (verbose_text, normal_text) = constants.RSS_DESCRIPTION[status]
  except KeyError:
    raise NotImplementedError("Unknown status %s" % status)
  else:
    if verbose:
      return verbose_text
    return normal_text


def FormatQueryResult(result, unit=None, format_override=None, separator=None,
                      header=False, verbose=False):
  """Formats data in L{objects.QueryResponse}.

  @type result: L{objects.QueryResponse}
  @param result: result of query operation
  @type unit: string
  @param unit: Unit used for formatting fields of type L{constants.QFT_UNIT},
    see L{utils.text.FormatUnit}
  @type format_override: dict
  @param format_override: Dictionary for overriding field formatting functions,
    indexed by field name, contents like L{_DEFAULT_FORMAT_QUERY}
  @type separator: string or None
  @param separator: String used to separate fields
  @type header: bool
  @param header: Whether to output header row
  @type verbose: boolean
  @param verbose: whether to use verbose field descriptions or not

  """
  if unit is None:
    if separator:
      unit = "m"
    else:
      unit = "h"

  if format_override is None:
    format_override = {}

  stats = dict.fromkeys(constants.RS_ALL, 0)

  def _RecordStatus(status):
    if status in stats:
      stats[status] += 1

  columns = []
  for fdef in result.fields:
    assert fdef.title and fdef.name
    (fn, align_right) = _GetColumnFormatter(fdef, format_override, unit)
    columns.append(TableColumn(fdef.title,
                               _QueryColumnFormatter(fn, _RecordStatus,
                                                     verbose),
                               align_right))

  table = FormatTable(result.data, columns, header, separator)

  # Collect statistics
  assert len(stats) == len(constants.RS_ALL)
  assert compat.all(count >= 0 for count in stats.values())

  # Determine overall status. If there was no data, unknown fields must be
  # detected via the field definitions.
  if (stats[constants.RS_UNKNOWN] or
      (not result.data and _GetUnknownFields(result.fields))):
    status = QR_UNKNOWN
  elif compat.any(count > 0 for key, count in stats.items()
                  if key != constants.RS_NORMAL):
    status = QR_INCOMPLETE
  else:
    status = QR_NORMAL

  return (status, table)


def _GetUnknownFields(fdefs):
  """Returns list of unknown fields included in C{fdefs}.

  @type fdefs: list of L{objects.QueryFieldDefinition}

  """
  return [fdef for fdef in fdefs
          if fdef.kind == constants.QFT_UNKNOWN]


def _WarnUnknownFields(fdefs):
  """Prints a warning to stderr if a query included unknown fields.

  @type fdefs: list of L{objects.QueryFieldDefinition}

  """
  unknown = _GetUnknownFields(fdefs)
  if unknown:
    ToStderr("Warning: Queried for unknown fields %s",
             utils.CommaJoin(fdef.name for fdef in unknown))
    return True

  return False


def GenericList(resource, fields, names, unit, separator, header, cl=None,
                format_override=None, verbose=False, force_filter=False,
                namefield=None, qfilter=None, isnumeric=False):
  """Generic implementation for listing all items of a resource.

  @param resource: One of L{constants.QR_VIA_LUXI}
  @type fields: list of strings
  @param fields: List of fields to query for
  @type names: list of strings
  @param names: Names of items to query for
  @type unit: string or None
  @param unit: Unit used for formatting fields of type L{constants.QFT_UNIT} or
    None for automatic choice (human-readable for non-separator usage,
    otherwise megabytes); this is a one-letter string
  @type separator: string or None
  @param separator: String used to separate fields
  @type header: bool
  @param header: Whether to show header row
  @type force_filter: bool
  @param force_filter: Whether to always treat names as filter
  @type format_override: dict
  @param format_override: Dictionary for overriding field formatting functions,
    indexed by field name, contents like L{_DEFAULT_FORMAT_QUERY}
  @type verbose: boolean
  @param verbose: whether to use verbose field descriptions or not
  @type namefield: string
  @param namefield: Name of field to use for simple filters (see
    L{qlang.MakeFilter} for details)
  @type qfilter: list or None
  @param qfilter: Query filter (in addition to names)
  @param isnumeric: bool
  @param isnumeric: Whether the namefield's type is numeric, and therefore
    any simple filters built by namefield should use integer values to
    reflect that

  """
  if not names:
    names = None

  namefilter = qlang.MakeFilter(names, force_filter, namefield=namefield,
                                isnumeric=isnumeric)

  if qfilter is None:
    qfilter = namefilter
  elif namefilter is not None:
    qfilter = [qlang.OP_AND, namefilter, qfilter]

  if cl is None:
    cl = GetClient()

  response = cl.Query(resource, fields, qfilter)

  found_unknown = _WarnUnknownFields(response.fields)

  (status, data) = FormatQueryResult(response, unit=unit, separator=separator,
                                     header=header,
                                     format_override=format_override,
                                     verbose=verbose)

  for line in data:
    ToStdout(line)

  assert ((found_unknown and status == QR_UNKNOWN) or
          (not found_unknown and status != QR_UNKNOWN))

  if status == QR_UNKNOWN:
    return constants.EXIT_UNKNOWN_FIELD

  # TODO: Should the list command fail if not all data could be collected?
  return constants.EXIT_SUCCESS


def _FieldDescValues(fdef):
  """Helper function for L{GenericListFields} to get query field description.

  @type fdef: L{objects.QueryFieldDefinition}
  @rtype: list

  """
  return [
    fdef.name,
    _QFT_NAMES.get(fdef.kind, fdef.kind),
    fdef.title,
    fdef.doc,
    ]


def GenericListFields(resource, fields, separator, header, cl=None):
  """Generic implementation for listing fields for a resource.

  @param resource: One of L{constants.QR_VIA_LUXI}
  @type fields: list of strings
  @param fields: List of fields to query for
  @type separator: string or None
  @param separator: String used to separate fields
  @type header: bool
  @param header: Whether to show header row

  """
  if cl is None:
    cl = GetClient()

  if not fields:
    fields = None

  response = cl.QueryFields(resource, fields)

  found_unknown = _WarnUnknownFields(response.fields)

  columns = [
    TableColumn("Name", str, False),
    TableColumn("Type", str, False),
    TableColumn("Title", str, False),
    TableColumn("Description", str, False),
    ]

  rows = map(_FieldDescValues, response.fields)

  for line in FormatTable(rows, columns, header, separator):
    ToStdout(line)

  if found_unknown:
    return constants.EXIT_UNKNOWN_FIELD

  return constants.EXIT_SUCCESS


class TableColumn(object):
  """Describes a column for L{FormatTable}.

  """
  def __init__(self, title, fn, align_right):
    """Initializes this class.

    @type title: string
    @param title: Column title
    @type fn: callable
    @param fn: Formatting function
    @type align_right: bool
    @param align_right: Whether to align values on the right-hand side

    """
    self.title = title
    self.format = fn
    self.align_right = align_right


def _GetColFormatString(width, align_right):
  """Returns the format string for a field.

  """
  if align_right:
    sign = ""
  else:
    sign = "-"

  return "%%%s%ss" % (sign, width)


def FormatTable(rows, columns, header, separator):
  """Formats data as a table.

  @type rows: list of lists
  @param rows: Row data, one list per row
  @type columns: list of L{TableColumn}
  @param columns: Column descriptions
  @type header: bool
  @param header: Whether to show header row
  @type separator: string or None
  @param separator: String used to separate columns

  """
  if header:
    data = [[col.title for col in columns]]
    colwidth = [len(col.title) for col in columns]
  else:
    data = []
    colwidth = [0 for _ in columns]

  # Format row data
  for row in rows:
    assert len(row) == len(columns)

    formatted = [col.format(value) for value, col in zip(row, columns)]

    if separator is None:
      # Update column widths
      for idx, (oldwidth, value) in enumerate(zip(colwidth, formatted)):
        # Modifying a list's items while iterating is fine
        colwidth[idx] = max(oldwidth, len(value))

    data.append(formatted)

  if separator is not None:
    # Return early if a separator is used
    return [separator.join(row) for row in data]

  if columns and not columns[-1].align_right:
    # Avoid unnecessary spaces at end of line
    colwidth[-1] = 0

  # Build format string
  fmt = " ".join([_GetColFormatString(width, col.align_right)
                  for col, width in zip(columns, colwidth)])

  return [fmt % tuple(row) for row in data]


def FormatTimestamp(ts):
  """Formats a given timestamp.

  @type ts: timestamp
  @param ts: a timeval-type timestamp, a tuple of seconds and microseconds

  @rtype: string
  @return: a string with the formatted timestamp

  """
  if not isinstance(ts, (tuple, list)) or len(ts) != 2:
    return "?"

  (sec, usecs) = ts
  return utils.FormatTime(sec, usecs=usecs)


def ParseTimespec(value):
  """Parse a time specification.

  The following suffixed will be recognized:

    - s: seconds
    - m: minutes
    - h: hours
    - d: day
    - w: weeks

  Without any suffix, the value will be taken to be in seconds.

  """
  value = str(value)
  if not value:
    raise errors.OpPrereqError("Empty time specification passed",
                               errors.ECODE_INVAL)
  suffix_map = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    }
  if value[-1] not in suffix_map:
    try:
      value = int(value)
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid time specification '%s'" % value,
                                 errors.ECODE_INVAL)
  else:
    multiplier = suffix_map[value[-1]]
    value = value[:-1]
    if not value: # no data left after stripping the suffix
      raise errors.OpPrereqError("Invalid time specification (only"
                                 " suffix passed)", errors.ECODE_INVAL)
    try:
      value = int(value) * multiplier
    except (TypeError, ValueError):
      raise errors.OpPrereqError("Invalid time specification '%s'" % value,
                                 errors.ECODE_INVAL)
  return value


def GetOnlineNodes(nodes, cl=None, nowarn=False, secondary_ips=False,
                   filter_master=False, nodegroup=None):
  """Returns the names of online nodes.

  This function will also log a warning on stderr with the names of
  the online nodes.

  @param nodes: if not empty, use only this subset of nodes (minus the
      offline ones)
  @param cl: if not None, luxi client to use
  @type nowarn: boolean
  @param nowarn: by default, this function will output a note with the
      offline nodes that are skipped; if this parameter is True the
      note is not displayed
  @type secondary_ips: boolean
  @param secondary_ips: if True, return the secondary IPs instead of the
      names, useful for doing network traffic over the replication interface
      (if any)
  @type filter_master: boolean
  @param filter_master: if True, do not return the master node in the list
      (useful in coordination with secondary_ips where we cannot check our
      node name against the list)
  @type nodegroup: string
  @param nodegroup: If set, only return nodes in this node group

  """
  if cl is None:
    cl = GetClient()

  qfilter = []

  if nodes:
    qfilter.append(qlang.MakeSimpleFilter("name", nodes))

  if nodegroup is not None:
    qfilter.append([qlang.OP_OR, [qlang.OP_EQUAL, "group", nodegroup],
                                 [qlang.OP_EQUAL, "group.uuid", nodegroup]])

  if filter_master:
    qfilter.append([qlang.OP_NOT, [qlang.OP_TRUE, "master"]])

  if qfilter:
    if len(qfilter) > 1:
      final_filter = [qlang.OP_AND] + qfilter
    else:
      assert len(qfilter) == 1
      final_filter = qfilter[0]
  else:
    final_filter = None

  result = cl.Query(constants.QR_NODE, ["name", "offline", "sip"], final_filter)

  def _IsOffline(row):
    (_, (_, offline), _) = row
    return offline

  def _GetName(row):
    ((_, name), _, _) = row
    return name

  def _GetSip(row):
    (_, _, (_, sip)) = row
    return sip

  (offline, online) = compat.partition(result.data, _IsOffline)

  if offline and not nowarn:
    ToStderr("Note: skipping offline node(s): %s" %
             utils.CommaJoin(map(_GetName, offline)))

  if secondary_ips:
    fn = _GetSip
  else:
    fn = _GetName

  return map(fn, online)


def GetNodesSshPorts(nodes, cl):
  """Retrieves SSH ports of given nodes.

  @param nodes: the names of nodes
  @type nodes: a list of strings
  @param cl: a client to use for the query
  @type cl: L{ganeti.luxi.Client}
  @return: the list of SSH ports corresponding to the nodes
  @rtype: a list of tuples

  """
  return [t[0] for t in cl.QueryNodes(names=nodes,
                                      fields=["ndp/ssh_port"],
                                      use_locking=False)]


def GetNodeUUIDs(nodes, cl):
  """Retrieves the UUIDs of given nodes.

  @param nodes: the names of nodes
  @type nodes: a list of string
  @param cl: a client to use for the query
  @type cl: L{ganeti.luxi.Client}
  @return: the list of UUIDs corresponding to the nodes
  @rtype: a list of tuples

  """
  return [t[0] for t in cl.QueryNodes(names=nodes,
                                      fields=["uuid"],
                                      use_locking=False)]


def _ToStream(stream, txt, *args):
  """Write a message to a stream, bypassing the logging system

  @type stream: file object
  @param stream: the file to which we should write
  @type txt: str
  @param txt: the message

  """
  try:
    if args:
      args = tuple(args)
      stream.write(txt % args)
    else:
      stream.write(txt)
    stream.write("\n")
    stream.flush()
  except IOError as err:
    if err.errno == errno.EPIPE:
      # our terminal went away, we'll exit
      sys.exit(constants.EXIT_FAILURE)
    else:
      raise


def ToStdout(txt, *args):
  """Write a message to stdout only, bypassing the logging system

  This is just a wrapper over _ToStream.

  @type txt: str
  @param txt: the message

  """
  _ToStream(sys.stdout, txt, *args)


def ToStdoutAndLoginfo(txt, *args):
  """Write a message to stdout and additionally log it at INFO level"""
  ToStdout(txt, *args)
  logging.info(txt, *args)


def ToStderr(txt, *args):
  """Write a message to stderr only, bypassing the logging system

  This is just a wrapper over _ToStream.

  @type txt: str
  @param txt: the message

  """
  _ToStream(sys.stderr, txt, *args)


class JobExecutor(object):
  """Class which manages the submission and execution of multiple jobs.

  Note that instances of this class should not be reused between
  GetResults() calls.

  """
  def __init__(self, cl=None, verbose=True, opts=None, feedback_fn=None):
    self.queue = []
    if cl is None:
      cl = GetClient()
    self.cl = cl
    self.verbose = verbose
    self.jobs = []
    self.opts = opts
    self.feedback_fn = feedback_fn
    self._counter = itertools.count()

  @staticmethod
  def _IfName(name, fmt):
    """Helper function for formatting name.

    """
    if name:
      return fmt % name

    return ""

  def QueueJob(self, name, *ops):
    """Record a job for later submit.

    @type name: string
    @param name: a description of the job, will be used in WaitJobSet

    """
    SetGenericOpcodeOpts(ops, self.opts)
    self.queue.append((next(self._counter), name, ops))

  def AddJobId(self, name, status, job_id):
    """Adds a job ID to the internal queue.

    """
    self.jobs.append((next(self._counter), status, job_id, name))

  def SubmitPending(self, each=False):
    """Submit all pending jobs.

    """
    if each:
      results = []
      for (_, _, ops) in self.queue:
        # SubmitJob will remove the success status, but raise an exception if
        # the submission fails, so we'll notice that anyway.
        results.append([True, self.cl.SubmitJob(ops)[0]])
    else:
      results = self.cl.SubmitManyJobs([ops for (_, _, ops) in self.queue])
    for ((status, data), (idx, name, _)) in zip(results, self.queue):
      self.jobs.append((idx, status, data, name))

  def _ChooseJob(self):
    """Choose a non-waiting/queued job to poll next.

    """
    assert self.jobs, "_ChooseJob called with empty job list"

    result = self.cl.QueryJobs([i[2] for i in self.jobs[:_CHOOSE_BATCH]],
                               ["status"])
    assert result

    for job_data, status in zip(self.jobs, result):
      if (isinstance(status, list) and status and
          status[0] in (constants.JOB_STATUS_QUEUED,
                        constants.JOB_STATUS_WAITING,
                        constants.JOB_STATUS_CANCELING)):
        # job is still present and waiting
        continue
      # good candidate found (either running job or lost job)
      self.jobs.remove(job_data)
      return job_data

    # no job found
    return self.jobs.pop(0)

  def GetResults(self):
    """Wait for and return the results of all jobs.

    @rtype: list
    @return: list of tuples (success, job results), in the same order
        as the submitted jobs; if a job has failed, instead of the result
        there will be the error message

    """
    if not self.jobs:
      self.SubmitPending()
    results = []
    if self.verbose:
      ok_jobs = [row[2] for row in self.jobs if row[1]]
      if ok_jobs:
        ToStdout("Submitted jobs %s", utils.CommaJoin(ok_jobs))

    # first, remove any non-submitted jobs
    self.jobs, failures = compat.partition(self.jobs, lambda x: x[1])
    for idx, _, jid, name in failures:
      ToStderr("Failed to submit job%s: %s", self._IfName(name, " for %s"), jid)
      results.append((idx, False, jid))

    while self.jobs:
      (idx, _, jid, name) = self._ChooseJob()
      ToStdout("Waiting for job %s%s ...", jid, self._IfName(name, " for %s"))
      try:
        job_result = PollJob(jid, cl=self.cl, feedback_fn=self.feedback_fn)
        success = True
      except errors.JobLost as err:
        _, job_result = FormatError(err)
        ToStderr("Job %s%s has been archived, cannot check its result",
                 jid, self._IfName(name, " for %s"))
        success = False
      except (errors.GenericError, rpcerr.ProtocolError) as err:
        _, job_result = FormatError(err)
        success = False
        # the error message will always be shown, verbose or not
        ToStderr("Job %s%s has failed: %s",
                 jid, self._IfName(name, " for %s"), job_result)

      results.append((idx, success, job_result))

    # sort based on the index, then drop it
    results.sort()
    results = [i[1:] for i in results]

    return results

  def WaitOrShow(self, wait):
    """Wait for job results or only print the job IDs.

    @type wait: boolean
    @param wait: whether to wait or not

    """
    if wait:
      return self.GetResults()
    else:
      if not self.jobs:
        self.SubmitPending()
      for _, status, result, name in self.jobs:
        if status:
          ToStdout("%s: %s", result, name)
        else:
          ToStderr("Failure for %s: %s", name, result)
      return [row[1:3] for row in self.jobs]


def FormatParamsDictInfo(param_dict, actual, roman=False):
  """Formats a parameter dictionary.

  @type param_dict: dict
  @param param_dict: the own parameters
  @type actual: dict
  @param actual: the current parameter set (including defaults)
  @rtype: dict
  @return: dictionary where the value of each parameter is either a fully
      formatted string or a dictionary containing formatted strings

  """
  ret = {}
  for (key, data) in actual.items():
    if isinstance(data, dict) and data:
      ret[key] = FormatParamsDictInfo(param_dict.get(key, {}), data, roman)
    else:
      default_str = "default (%s)" % compat.TryToRoman(data, roman)
      ret[key] = str(compat.TryToRoman(param_dict.get(key, default_str), roman))
  return ret


def _FormatListInfoDefault(data, def_data):
  if data is not None:
    ret = utils.CommaJoin(data)
  else:
    ret = "default (%s)" % utils.CommaJoin(def_data)
  return ret


def FormatPolicyInfo(custom_ipolicy, eff_ipolicy, iscluster, roman=False):
  """Formats an instance policy.

  @type custom_ipolicy: dict
  @param custom_ipolicy: own policy
  @type eff_ipolicy: dict
  @param eff_ipolicy: effective policy (including defaults); ignored for
      cluster
  @type iscluster: bool
  @param iscluster: the policy is at cluster level
  @type roman: bool
  @param roman: whether to print the values in roman numerals
  @rtype: list of pairs
  @return: formatted data, suitable for L{PrintGenericInfo}

  """
  if iscluster:
    eff_ipolicy = custom_ipolicy

  minmax_out = []
  custom_minmax = custom_ipolicy.get(constants.ISPECS_MINMAX)
  if custom_minmax:
    for (k, minmax) in enumerate(custom_minmax):
      minmax_out.append([
        ("%s/%s" % (key, k),
         FormatParamsDictInfo(minmax[key], minmax[key], roman))
        for key in constants.ISPECS_MINMAX_KEYS
        ])
  else:
    for (k, minmax) in enumerate(eff_ipolicy[constants.ISPECS_MINMAX]):
      minmax_out.append([
        ("%s/%s" % (key, k),
         FormatParamsDictInfo({}, minmax[key], roman))
        for key in constants.ISPECS_MINMAX_KEYS
        ])
  ret = [("bounds specs", minmax_out)]

  if iscluster:
    stdspecs = custom_ipolicy[constants.ISPECS_STD]
    ret.append(
      (constants.ISPECS_STD,
       FormatParamsDictInfo(stdspecs, stdspecs, roman))
      )

  ret.append(
    ("allowed disk templates",
     _FormatListInfoDefault(custom_ipolicy.get(constants.IPOLICY_DTS),
                            eff_ipolicy[constants.IPOLICY_DTS]))
    )
  to_roman = compat.TryToRoman
  ret.extend([
    (key, str(to_roman(custom_ipolicy.get(key,
                                          "default (%s)" % eff_ipolicy[key]),
                       roman)))
    for key in constants.IPOLICY_PARAMETERS
    ])
  return ret


def _PrintSpecsParameters(buf, specs):
  values = ("%s=%s" % (par, val) for (par, val) in sorted(specs.items()))
  buf.write(",".join(values))


def PrintIPolicyCommand(buf, ipolicy, isgroup):
  """Print the command option used to generate the given instance policy.

  Currently only the parts dealing with specs are supported.

  @type buf: StringIO
  @param buf: stream to write into
  @type ipolicy: dict
  @param ipolicy: instance policy
  @type isgroup: bool
  @param isgroup: whether the policy is at group level

  """
  if not isgroup:
    stdspecs = ipolicy.get("std")
    if stdspecs:
      buf.write(" %s " % IPOLICY_STD_SPECS_STR)
      _PrintSpecsParameters(buf, stdspecs)
  minmaxes = ipolicy.get("minmax", [])
  first = True
  for minmax in minmaxes:
    minspecs = minmax.get("min")
    maxspecs = minmax.get("max")
    if minspecs and maxspecs:
      if first:
        buf.write(" %s " % IPOLICY_BOUNDS_SPECS_STR)
        first = False
      else:
        buf.write("//")
      buf.write("min:")
      _PrintSpecsParameters(buf, minspecs)
      buf.write("/max:")
      _PrintSpecsParameters(buf, maxspecs)


def ConfirmOperation(names, list_type, text, extra=""):
  """Ask the user to confirm an operation on a list of list_type.

  This function is used to request confirmation for doing an operation
  on a given list of list_type.

  @type names: list
  @param names: the list of names that we display when
      we ask for confirmation
  @type list_type: str
  @param list_type: Human readable name for elements in the list (e.g. nodes)
  @type text: str
  @param text: the operation that the user should confirm
  @rtype: boolean
  @return: True or False depending on user's confirmation.

  """
  count = len(names)
  msg = ("The %s will operate on %d %s.\n%s"
         "Do you want to continue?" % (text, count, list_type, extra))
  affected = (("\nAffected %s:\n" % list_type) +
              "\n".join(["  %s" % name for name in names]))

  choices = [("y", True, "Yes, execute the %s" % text),
             ("n", False, "No, abort the %s" % text)]

  if count > 20:
    choices.insert(1, ("v", "v", "View the list of affected %s" % list_type))
    question = msg
  else:
    question = msg + affected

  choice = AskUser(question, choices)
  if choice == "v":
    choices.pop(1)
    choice = AskUser(msg + affected, choices)
  return choice


def _MaybeParseUnit(elements):
  """Parses and returns an array of potential values with units.

  """
  parsed = {}
  for k, v in elements.items():
    if v == constants.VALUE_DEFAULT:
      parsed[k] = v
    else:
      parsed[k] = utils.ParseUnit(v)
  return parsed


def _InitISpecsFromSplitOpts(ipolicy, ispecs_mem_size, ispecs_cpu_count,
                             ispecs_disk_count, ispecs_disk_size,
                             ispecs_nic_count, group_ipolicy, fill_all):
  try:
    if ispecs_mem_size:
      ispecs_mem_size = _MaybeParseUnit(ispecs_mem_size)
    if ispecs_disk_size:
      ispecs_disk_size = _MaybeParseUnit(ispecs_disk_size)
  except (TypeError, ValueError, errors.UnitParseError) as err:
    raise errors.OpPrereqError("Invalid disk (%s) or memory (%s) size"
                               " in policy: %s" %
                               (ispecs_disk_size, ispecs_mem_size, err),
                               errors.ECODE_INVAL)

  # prepare ipolicy dict
  ispecs_transposed = {
    constants.ISPEC_MEM_SIZE: ispecs_mem_size,
    constants.ISPEC_CPU_COUNT: ispecs_cpu_count,
    constants.ISPEC_DISK_COUNT: ispecs_disk_count,
    constants.ISPEC_DISK_SIZE: ispecs_disk_size,
    constants.ISPEC_NIC_COUNT: ispecs_nic_count,
    }

  # first, check that the values given are correct
  if group_ipolicy:
    forced_type = TISPECS_GROUP_TYPES
  else:
    forced_type = TISPECS_CLUSTER_TYPES
  for specs in ispecs_transposed.values():
    assert isinstance(specs, dict)
    utils.ForceDictType(specs, forced_type)

  # then transpose
  ispecs = {
    constants.ISPECS_MIN: {},
    constants.ISPECS_MAX: {},
    constants.ISPECS_STD: {},
    }
  for (name, specs) in ispecs_transposed.items():
    assert name in constants.ISPECS_PARAMETERS
    for key, val in specs.items(): # {min: .. ,max: .., std: ..}
      assert key in ispecs
      ispecs[key][name] = val
  minmax_out = {}
  for key in constants.ISPECS_MINMAX_KEYS:
    if fill_all:
      minmax_out[key] = \
        objects.FillDict(constants.ISPECS_MINMAX_DEFAULTS[key], ispecs[key])
    else:
      minmax_out[key] = ispecs[key]
  ipolicy[constants.ISPECS_MINMAX] = [minmax_out]
  if fill_all:
    ipolicy[constants.ISPECS_STD] = \
        objects.FillDict(constants.IPOLICY_DEFAULTS[constants.ISPECS_STD],
                         ispecs[constants.ISPECS_STD])
  else:
    ipolicy[constants.ISPECS_STD] = ispecs[constants.ISPECS_STD]


def _ParseSpecUnit(spec, keyname):
  ret = spec.copy()
  for k in [constants.ISPEC_DISK_SIZE, constants.ISPEC_MEM_SIZE]:
    if k in ret:
      try:
        ret[k] = utils.ParseUnit(ret[k])
      except (TypeError, ValueError, errors.UnitParseError) as err:
        raise errors.OpPrereqError(("Invalid parameter %s (%s) in %s instance"
                                    " specs: %s" % (k, ret[k], keyname, err)),
                                   errors.ECODE_INVAL)
  return ret


def _ParseISpec(spec, keyname, required):
  ret = _ParseSpecUnit(spec, keyname)
  utils.ForceDictType(ret, constants.ISPECS_PARAMETER_TYPES)
  missing = constants.ISPECS_PARAMETERS - frozenset(ret)
  if required and missing:
    raise errors.OpPrereqError("Missing parameters in ipolicy spec %s: %s" %
                               (keyname, utils.CommaJoin(missing)),
                               errors.ECODE_INVAL)
  return ret


def _GetISpecsInAllowedValues(minmax_ispecs, allowed_values):
  ret = None
  if (minmax_ispecs and allowed_values and len(minmax_ispecs) == 1 and
      len(minmax_ispecs[0]) == 1):
    for (key, spec) in minmax_ispecs[0].items():
      # This loop is executed exactly once
      if key in allowed_values and not spec:
        ret = key
  return ret


def _InitISpecsFromFullOpts(ipolicy_out, minmax_ispecs, std_ispecs,
                            group_ipolicy, allowed_values):
  found_allowed = _GetISpecsInAllowedValues(minmax_ispecs, allowed_values)
  if found_allowed is not None:
    ipolicy_out[constants.ISPECS_MINMAX] = found_allowed
  elif minmax_ispecs is not None:
    minmax_out = []
    for mmpair in minmax_ispecs:
      mmpair_out = {}
      for (key, spec) in mmpair.items():
        if key not in constants.ISPECS_MINMAX_KEYS:
          msg = "Invalid key in bounds instance specifications: %s" % key
          raise errors.OpPrereqError(msg, errors.ECODE_INVAL)
        mmpair_out[key] = _ParseISpec(spec, key, True)
      minmax_out.append(mmpair_out)
    ipolicy_out[constants.ISPECS_MINMAX] = minmax_out
  if std_ispecs is not None:
    assert not group_ipolicy # This is not an option for gnt-group
    ipolicy_out[constants.ISPECS_STD] = _ParseISpec(std_ispecs, "std", False)


def CreateIPolicyFromOpts(ispecs_mem_size=None,
                          ispecs_cpu_count=None,
                          ispecs_disk_count=None,
                          ispecs_disk_size=None,
                          ispecs_nic_count=None,
                          minmax_ispecs=None,
                          std_ispecs=None,
                          ipolicy_disk_templates=None,
                          ipolicy_vcpu_ratio=None,
                          ipolicy_spindle_ratio=None,
                          group_ipolicy=False,
                          allowed_values=None,
                          fill_all=False):
  """Creation of instance policy based on command line options.

  @param fill_all: whether for cluster policies we should ensure that
    all values are filled

  """
  assert not (fill_all and allowed_values)

  split_specs = (ispecs_mem_size or ispecs_cpu_count or ispecs_disk_count or
                 ispecs_disk_size or ispecs_nic_count)
  if split_specs and (minmax_ispecs is not None or std_ispecs is not None):
    raise errors.OpPrereqError("A --specs-xxx option cannot be specified"
                               " together with any --ipolicy-xxx-specs option",
                               errors.ECODE_INVAL)

  ipolicy_out = objects.MakeEmptyIPolicy()
  if split_specs:
    assert fill_all
    _InitISpecsFromSplitOpts(ipolicy_out, ispecs_mem_size, ispecs_cpu_count,
                             ispecs_disk_count, ispecs_disk_size,
                             ispecs_nic_count, group_ipolicy, fill_all)
  elif minmax_ispecs is not None or std_ispecs is not None:
    _InitISpecsFromFullOpts(ipolicy_out, minmax_ispecs, std_ispecs,
                            group_ipolicy, allowed_values)

  if ipolicy_disk_templates is not None:
    if allowed_values and ipolicy_disk_templates in allowed_values:
      ipolicy_out[constants.IPOLICY_DTS] = ipolicy_disk_templates
    else:
      ipolicy_out[constants.IPOLICY_DTS] = list(ipolicy_disk_templates)
  if ipolicy_vcpu_ratio is not None:
    ipolicy_out[constants.IPOLICY_VCPU_RATIO] = ipolicy_vcpu_ratio
  if ipolicy_spindle_ratio is not None:
    ipolicy_out[constants.IPOLICY_SPINDLE_RATIO] = ipolicy_spindle_ratio

  assert not (frozenset(ipolicy_out) - constants.IPOLICY_ALL_KEYS)

  if not group_ipolicy and fill_all:
    ipolicy_out = objects.FillIPolicy(constants.IPOLICY_DEFAULTS, ipolicy_out)

  return ipolicy_out


def _NotAContainer(data):
  """ Checks whether the input is not a container data type.

  @rtype: bool

  """
  return not isinstance(data, (list, dict, tuple))


def _GetAlignmentMapping(data):
  """ Returns info about alignment if present in an encoded ordered dictionary.

  @type data: list of tuple
  @param data: The encoded ordered dictionary, as defined in
               L{_SerializeGenericInfo}.
  @rtype: dict of any to int
  @return: The dictionary mapping alignment groups to the maximum length of the
           dictionary key found in the group.

  """
  alignment_map = {}
  for entry in data:
    if len(entry) > 2:
      group_key = entry[2]
      key_length = len(entry[0])
      if group_key in alignment_map:
        alignment_map[group_key] = max(alignment_map[group_key], key_length)
      else:
        alignment_map[group_key] = key_length

  return alignment_map


def _SerializeGenericInfo(buf, data, level, afterkey=False):
  """Formatting core of L{PrintGenericInfo}.

  @param buf: (string) stream to accumulate the result into
  @param data: data to format
  @type level: int
  @param level: depth in the data hierarchy, used for indenting
  @type afterkey: bool
  @param afterkey: True when we are in the middle of a line after a key (used
      to properly add newlines or indentation)

  """
  baseind = "  "
  if isinstance(data, dict):
    if not data:
      buf.write("\n")
    else:
      if afterkey:
        buf.write("\n")
        doindent = True
      else:
        doindent = False
      for key in sorted(data):
        if doindent:
          buf.write(baseind * level)
        else:
          doindent = True
        buf.write(key)
        buf.write(": ")
        _SerializeGenericInfo(buf, data[key], level + 1, afterkey=True)
  elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], tuple):
    # list of tuples (an ordered dictionary)
    # the tuples may have two or three members - key, value, and alignment group
    # if the alignment group is present, align all values sharing the same group
    if afterkey:
      buf.write("\n")
      doindent = True
    else:
      doindent = False

    alignment_mapping = _GetAlignmentMapping(data)
    for entry in data:
      key, val = entry[0:2]
      if doindent:
        buf.write(baseind * level)
      else:
        doindent = True
      buf.write(key)
      buf.write(": ")
      if len(entry) > 2:
        max_key_length = alignment_mapping[entry[2]]
        buf.write(" " * (max_key_length - len(key)))
      _SerializeGenericInfo(buf, val, level + 1, afterkey=True)
  elif isinstance(data, tuple) and all(map(_NotAContainer, data)):
    # tuples with simple content are serialized as inline lists
    buf.write("[%s]\n" % utils.CommaJoin(data))
  elif isinstance(data, list) or isinstance(data, tuple):
    # lists and tuples
    if not data:
      buf.write("\n")
    else:
      if afterkey:
        buf.write("\n")
        doindent = True
      else:
        doindent = False
      for item in data:
        if doindent:
          buf.write(baseind * level)
        else:
          doindent = True
        buf.write("-")
        buf.write(baseind[1:])
        _SerializeGenericInfo(buf, item, level + 1)
  else:
    # This branch should be only taken for strings, but it's practically
    # impossible to guarantee that no other types are produced somewhere
    buf.write(str(data))
    buf.write("\n")


def PrintGenericInfo(data):
  """Print information formatted according to the hierarchy.

  The output is a valid YAML string.

  @param data: the data to print. It's a hierarchical structure whose elements
      can be:
        - dictionaries, where keys are strings and values are of any of the
          types listed here
        - lists of tuples (key, value) or (key, value, alignment_group), where
          key is a string, value is of any of the types listed here, and
          alignment_group can be any hashable value; it's a way to encode
          ordered dictionaries; any entries sharing the same alignment group are
          aligned by appending whitespace before the value as needed
        - lists of any of the types listed here
        - strings

  """
  buf = StringIO()
  _SerializeGenericInfo(buf, data, 0)
  ToStdout(buf.getvalue().rstrip("\n"))
