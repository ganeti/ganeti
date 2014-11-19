#
#

# Copyright (C) 2006, 2007, 2012 Google Inc.
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

"""Job related commands"""

# pylint: disable=W0401,W0613,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0613: Unused argument, since all functions follow the same API
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-job

from ganeti.cli import *
from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import cli
from ganeti import qlang


#: default list of fields for L{ListJobs}
_LIST_DEF_FIELDS = ["id", "status", "summary"]

#: map converting the job status contants to user-visible
#: names
_USER_JOB_STATUS = {
  constants.JOB_STATUS_QUEUED: "queued",
  constants.JOB_STATUS_WAITING: "waiting",
  constants.JOB_STATUS_CANCELING: "canceling",
  constants.JOB_STATUS_RUNNING: "running",
  constants.JOB_STATUS_CANCELED: "canceled",
  constants.JOB_STATUS_SUCCESS: "success",
  constants.JOB_STATUS_ERROR: "error",
  }


def _FormatStatus(value):
  """Formats a job status.

  """
  try:
    return _USER_JOB_STATUS[value]
  except KeyError:
    raise errors.ProgrammerError("Unknown job status code '%s'" % value)


def _FormatSummary(value):
  """Formats a job's summary. Takes possible non-ascii encoding into account.

  """
  return ','.encode('utf-8').join(item.encode('utf-8') for item in value)


_JOB_LIST_FORMAT = {
  "status": (_FormatStatus, False),
  "summary": (_FormatSummary, False),
  }
_JOB_LIST_FORMAT.update(dict.fromkeys(["opstart", "opexec", "opend"],
                                      (lambda value: map(FormatTimestamp,
                                                         value),
                                       None)))


def _ParseJobIds(args):
  """Parses a list of string job IDs into integers.

  @param args: list of strings
  @return: list of integers
  @raise OpPrereqError: in case of invalid values

  """
  try:
    return [int(a) for a in args]
  except (ValueError, TypeError), err:
    raise errors.OpPrereqError("Invalid job ID passed: %s" % err,
                               errors.ECODE_INVAL)


def ListJobs(opts, args):
  """List the jobs

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)

  if opts.archived and "archived" not in selected_fields:
    selected_fields.append("archived")

  qfilter = qlang.MakeSimpleFilter("status", opts.status_filter)

  cl = GetClient()

  return GenericList(constants.QR_JOB, selected_fields, args, None,
                     opts.separator, not opts.no_headers,
                     format_override=_JOB_LIST_FORMAT, verbose=opts.verbose,
                     force_filter=opts.force_filter, namefield="id",
                     qfilter=qfilter, isnumeric=True, cl=cl)


def ListJobFields(opts, args):
  """List job fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  cl = GetClient()

  return GenericListFields(constants.QR_JOB, args, opts.separator,
                           not opts.no_headers, cl=cl)


def ArchiveJobs(opts, args):
  """Archive jobs.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain the job IDs to be archived
  @rtype: int
  @return: the desired exit code

  """
  client = GetClient()

  rcode = 0
  for job_id in args:
    if not client.ArchiveJob(job_id):
      ToStderr("Failed to archive job with ID '%s'", job_id)
      rcode = 1

  return rcode


def AutoArchiveJobs(opts, args):
  """Archive jobs based on age.

  This will archive jobs based on their age, or all jobs if a 'all' is
  passed.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the age as a time spec
      that can be parsed by L{ganeti.cli.ParseTimespec} or the
      keyword I{all}, which will cause all jobs to be archived
  @rtype: int
  @return: the desired exit code

  """
  client = GetClient()

  age = args[0]

  if age == "all":
    age = -1
  else:
    age = ParseTimespec(age)

  (archived_count, jobs_left) = client.AutoArchiveJobs(age)
  ToStdout("Archived %s jobs, %s unchecked left", archived_count, jobs_left)

  return 0


def _MultiJobAction(opts, args, cl, stdout_fn, ask_fn, question, action_fn):
  """Applies a function to multipe jobs.

  @param opts: Command line options
  @type args: list
  @param args: Job IDs
  @rtype: int
  @return: Exit code

  """
  if cl is None:
    cl = GetClient()

  if stdout_fn is None:
    stdout_fn = ToStdout

  if ask_fn is None:
    ask_fn = AskUser

  result = constants.EXIT_SUCCESS

  if bool(args) ^ (opts.status_filter is None):
    raise errors.OpPrereqError("Either a status filter or job ID(s) must be"
                               " specified and never both", errors.ECODE_INVAL)

  if opts.status_filter is not None:
    response = cl.Query(constants.QR_JOB, ["id", "status", "summary"],
                        qlang.MakeSimpleFilter("status", opts.status_filter))

    jobs = [i for ((_, i), _, _) in response.data]
    if not jobs:
      raise errors.OpPrereqError("No jobs with the requested status have been"
                                 " found", errors.ECODE_STATE)

    if not opts.force:
      (_, table) = FormatQueryResult(response, header=True,
                                     format_override=_JOB_LIST_FORMAT)
      for line in table:
        stdout_fn(line)

      if not ask_fn(question):
        return constants.EXIT_CONFIRMATION
  else:
    jobs = args

  for job_id in jobs:
    (success, msg) = action_fn(cl, job_id)

    if not success:
      result = constants.EXIT_FAILURE

    stdout_fn(msg)

  return result


def CancelJobs(opts, args, cl=None, _stdout_fn=ToStdout, _ask_fn=AskUser):
  """Cancel not-yet-started jobs.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain the job IDs to be cancelled
  @rtype: int
  @return: the desired exit code

  """
  if opts.kill:
    action_name = "KILL"
    if not opts.yes_do_it:
      raise errors.OpPrereqError("The --kill option must be confirmed"
                                 " with --yes-do-it", errors.ECODE_INVAL)
  else:
    action_name = "Cancel"
  return _MultiJobAction(opts, args, cl, _stdout_fn, _ask_fn,
                         "%s job(s) listed above?" % action_name,
                         lambda cl, job_id: cl.CancelJob(job_id,
                                                         kill=opts.kill))


def ChangePriority(opts, args):
  """Change priority of jobs.

  @param opts: Command line options
  @type args: list
  @param args: Job IDs
  @rtype: int
  @return: Exit code

  """
  if opts.priority is None:
    ToStderr("--priority option must be given.")
    return constants.EXIT_FAILURE

  return _MultiJobAction(opts, args, None, None, None,
                         "Change priority of job(s) listed above?",
                         lambda cl, job_id:
                           cl.ChangeJobPriority(job_id, opts.priority))


def _ListOpcodeTimestamp(name, ts, container):
  """ Adds the opcode timestamp to the given container.

  """
  if isinstance(ts, (tuple, list)):
    container.append((name, FormatTimestamp(ts), "opcode_timestamp"))
  else:
    container.append((name, "N/A", "opcode_timestamp"))


def _CalcDelta(from_ts, to_ts):
  """ Calculates the delta between two timestamps.

  """
  return to_ts[0] - from_ts[0] + (to_ts[1] - from_ts[1]) / 1000000.0


def _ListJobTimestamp(name, ts, container, prior_ts=None):
  """ Adds the job timestamp to the given container.

  @param prior_ts: The timestamp used to calculate the amount of time that
                   passed since the given timestamp.

  """
  if ts is not None:
    delta = ""
    if prior_ts is not None:
      delta = " (delta %.6fs)" % _CalcDelta(prior_ts, ts)
    output = "%s%s" % (FormatTimestamp(ts), delta)
    container.append((name, output, "job_timestamp"))
  else:
    container.append((name, "unknown (%s)" % str(ts), "job_timestamp"))


def ShowJobs(opts, args):
  """Show detailed information about jobs.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain the job IDs to be queried
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = [
    "id", "status", "ops", "opresult", "opstatus", "oplog",
    "opstart", "opexec", "opend", "received_ts", "start_ts", "end_ts",
    ]

  qfilter = qlang.MakeSimpleFilter("id", _ParseJobIds(args))
  cl = GetClient()
  result = cl.Query(constants.QR_JOB, selected_fields, qfilter).data

  job_info_container = []

  for entry in result:
    ((_, job_id), (rs_status, status), (_, ops), (_, opresult), (_, opstatus),
     (_, oplog), (_, opstart), (_, opexec), (_, opend), (_, recv_ts),
     (_, start_ts), (_, end_ts)) = entry

    # Detect non-normal results
    if rs_status != constants.RS_NORMAL:
      job_info_container.append("Job ID %s not found" % job_id)
      continue

    # Container for produced data
    job_info = [("Job ID", job_id)]

    if status in _USER_JOB_STATUS:
      status = _USER_JOB_STATUS[status]
    else:
      raise errors.ProgrammerError("Unknown job status code '%s'" % status)

    job_info.append(("Status", status))

    _ListJobTimestamp("Received", recv_ts, job_info)
    _ListJobTimestamp("Processing start", start_ts, job_info, prior_ts=recv_ts)
    _ListJobTimestamp("Processing end", end_ts, job_info, prior_ts=start_ts)

    if end_ts is not None and recv_ts is not None:
      job_info.append(("Total processing time", "%.6f seconds" %
                       _CalcDelta(recv_ts, end_ts)))
    else:
      job_info.append(("Total processing time", "N/A"))

    opcode_container = []
    for (opcode, result, status, log, s_ts, x_ts, e_ts) in \
            zip(ops, opresult, opstatus, oplog, opstart, opexec, opend):
      opcode_info = []
      opcode_info.append(("Opcode", opcode["OP_ID"]))
      opcode_info.append(("Status", status))

      _ListOpcodeTimestamp("Processing start", s_ts, opcode_info)
      _ListOpcodeTimestamp("Execution start", x_ts, opcode_info)
      _ListOpcodeTimestamp("Processing end", e_ts, opcode_info)

      opcode_info.append(("Input fields", opcode))
      opcode_info.append(("Result", result))

      exec_log_container = []
      for serial, log_ts, log_type, log_msg in log:
        time_txt = FormatTimestamp(log_ts)
        encoded = FormatLogMessage(log_type, log_msg)

        # Arranged in this curious way to preserve the brevity for multiple
        # logs. This content cannot be exposed as a 4-tuple, as time contains
        # the colon, causing some YAML parsers to fail.
        exec_log_info = [
          ("Time", time_txt),
          ("Content", (serial, log_type, encoded,)),
          ]
        exec_log_container.append(exec_log_info)
      opcode_info.append(("Execution log", exec_log_container))

      opcode_container.append(opcode_info)

    job_info.append(("Opcodes", opcode_container))
    job_info_container.append(job_info)

  PrintGenericInfo(job_info_container)

  return 0


def WatchJob(opts, args):
  """Follow a job and print its output as it arrives.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: Contains the job ID
  @rtype: int
  @return: the desired exit code

  """
  job_id = args[0]

  msg = ("Output from job %s follows" % job_id)
  ToStdout(msg)
  ToStdout("-" * len(msg))

  retcode = 0
  try:
    cli.PollJob(job_id)
  except errors.GenericError, err:
    (retcode, job_result) = cli.FormatError(err)
    ToStderr("Job %s failed: %s", job_id, job_result)

  return retcode


def WaitJob(opts, args):
  """Wait for a job to finish, not producing any output.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: Contains the job ID
  @rtype: int
  @return: the desired exit code

  """
  job_id = args[0]

  retcode = 0
  try:
    cli.PollJob(job_id, feedback_fn=lambda _: None)
  except errors.GenericError, err:
    (retcode, job_result) = cli.FormatError(err)
    ToStderr("Job %s failed: %s", job_id, job_result)

  return retcode

_KILL_OPT = \
  cli_option("--kill", default=False,
             action="store_true", dest="kill",
             help="Kill running jobs with SIGKILL")

_YES_DOIT_OPT = cli_option("--yes-do-it", "--ya-rly", dest="yes_do_it",
                           help="Really use --kill", action="store_true")

_PENDING_OPT = \
  cli_option("--pending", default=None,
             action="store_const", dest="status_filter",
             const=constants.JOBS_PENDING,
             help="Select jobs pending execution or being cancelled")

_RUNNING_OPT = \
  cli_option("--running", default=None,
             action="store_const", dest="status_filter",
             const=frozenset([
               constants.JOB_STATUS_RUNNING,
               ]),
             help="Show jobs currently running only")

_ERROR_OPT = \
  cli_option("--error", default=None,
             action="store_const", dest="status_filter",
             const=frozenset([
               constants.JOB_STATUS_ERROR,
               ]),
             help="Show failed jobs only")

_FINISHED_OPT = \
  cli_option("--finished", default=None,
             action="store_const", dest="status_filter",
             const=constants.JOBS_FINALIZED,
             help="Show finished jobs only")

_ARCHIVED_OPT = \
  cli_option("--archived", default=False,
             action="store_true", dest="archived",
             help="Include archived jobs in list (slow and expensive)")

_QUEUED_OPT = \
  cli_option("--queued", default=None,
             action="store_const", dest="status_filter",
             const=frozenset([
               constants.JOB_STATUS_QUEUED,
               ]),
             help="Select queued jobs only")

_WAITING_OPT = \
  cli_option("--waiting", default=None,
             action="store_const", dest="status_filter",
             const=frozenset([
               constants.JOB_STATUS_WAITING,
               ]),
             help="Select waiting jobs only")


commands = {
  "list": (
    ListJobs, [ArgJobId()],
    [NOHDR_OPT, SEP_OPT, FIELDS_OPT, VERBOSE_OPT, FORCE_FILTER_OPT,
     _PENDING_OPT, _RUNNING_OPT, _ERROR_OPT, _FINISHED_OPT, _ARCHIVED_OPT],
    "[job_id ...]",
    "Lists the jobs and their status. The available fields can be shown"
    " using the \"list-fields\" command (see the man page for details)."
    " The default field list is (in order): %s." %
    utils.CommaJoin(_LIST_DEF_FIELDS)),
  "list-fields": (
    ListJobFields, [ArgUnknown()],
    [NOHDR_OPT, SEP_OPT],
    "[fields...]",
    "Lists all available fields for jobs"),
  "archive": (
    ArchiveJobs, [ArgJobId(min=1)], [],
    "<job-id> [<job-id> ...]", "Archive specified jobs"),
  "autoarchive": (
    AutoArchiveJobs,
    [ArgSuggest(min=1, max=1, choices=["1d", "1w", "4w", "all"])],
    [],
    "<age>", "Auto archive jobs older than the given age"),
  "cancel": (
    CancelJobs, [ArgJobId()],
    [FORCE_OPT, _KILL_OPT, _PENDING_OPT, _QUEUED_OPT, _WAITING_OPT,
     _YES_DOIT_OPT],
    "{[--force] [--kill --yes-do-it] {--pending | --queued | --waiting} |"
    " <job-id> [<job-id> ...]}",
    "Cancel jobs"),
  "info": (
    ShowJobs, [ArgJobId(min=1)], [],
    "<job-id> [<job-id> ...]",
    "Show detailed information about the specified jobs"),
  "wait": (
    WaitJob, [ArgJobId(min=1, max=1)], [],
    "<job-id>", "Wait for a job to finish"),
  "watch": (
    WatchJob, [ArgJobId(min=1, max=1)], [],
    "<job-id>", "Follows a job and prints its output as it arrives"),
  "change-priority": (
    ChangePriority, [ArgJobId()],
    [PRIORITY_OPT, FORCE_OPT, _PENDING_OPT, _QUEUED_OPT, _WAITING_OPT],
    "--priority <priority> {[--force] {--pending | --queued | --waiting} |"
    " <job-id> [<job-id> ...]}",
    "Change the priority of jobs"),
  }


#: dictionary with aliases for commands
aliases = {
  "show": "info",
  }


def Main():
  return GenericMain(commands, aliases=aliases)
