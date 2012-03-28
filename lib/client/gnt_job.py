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


def ListJobs(opts, args):
  """List the jobs

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_DEF_FIELDS)

  fmtoverride = {
    "status": (_FormatStatus, False),
    "summary": (lambda value: ",".join(str(item) for item in value), False),
    }
  fmtoverride.update(dict.fromkeys(["opstart", "opexec", "opend"],
    (lambda value: map(FormatTimestamp, value), None)))

  return GenericList(constants.QR_JOB, selected_fields, args, None,
                     opts.separator, not opts.no_headers,
                     format_override=fmtoverride, verbose=opts.verbose,
                     force_filter=opts.force_filter, namefield="id")


def ListJobFields(opts, args):
  """List job fields.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: fields to list, or empty for all
  @rtype: int
  @return: the desired exit code

  """
  return GenericListFields(constants.QR_JOB, args, opts.separator,
                           not opts.no_headers)


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


def CancelJobs(opts, args):
  """Cancel not-yet-started jobs.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain the job IDs to be cancelled
  @rtype: int
  @return: the desired exit code

  """
  client = GetClient()
  result = constants.EXIT_SUCCESS

  for job_id in args:
    (success, msg) = client.CancelJob(job_id)

    if not success:
      result = constants.EXIT_FAILURE

    ToStdout(msg)

  return result


def ShowJobs(opts, args):
  """Show detailed information about jobs.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain the job IDs to be queried
  @rtype: int
  @return: the desired exit code

  """
  def format_msg(level, text):
    """Display the text indented."""
    ToStdout("%s%s", "  " * level, text)

  def result_helper(value):
    """Format a result field in a nice way."""
    if isinstance(value, (tuple, list)):
      return "[%s]" % utils.CommaJoin(value)
    else:
      return str(value)

  selected_fields = [
    "id", "status", "ops", "opresult", "opstatus", "oplog",
    "opstart", "opexec", "opend", "received_ts", "start_ts", "end_ts",
    ]

  result = GetClient().Query(constants.QR_JOB, selected_fields,
                             qlang.MakeSimpleFilter("id", args)).data

  first = True

  for entry in result:
    if not first:
      format_msg(0, "")
    else:
      first = False

    ((_, job_id), (rs_status, status), (_, ops), (_, opresult), (_, opstatus),
     (_, oplog), (_, opstart), (_, opexec), (_, opend), (_, recv_ts),
     (_, start_ts), (_, end_ts)) = entry

    # Detect non-normal results
    if rs_status != constants.RS_NORMAL:
      format_msg(0, "Job ID %s not found" % job_id)
      continue

    format_msg(0, "Job ID: %s" % job_id)
    if status in _USER_JOB_STATUS:
      status = _USER_JOB_STATUS[status]
    else:
      raise errors.ProgrammerError("Unknown job status code '%s'" % status)

    format_msg(1, "Status: %s" % status)

    if recv_ts is not None:
      format_msg(1, "Received:         %s" % FormatTimestamp(recv_ts))
    else:
      format_msg(1, "Missing received timestamp (%s)" % str(recv_ts))

    if start_ts is not None:
      if recv_ts is not None:
        d1 = start_ts[0] - recv_ts[0] + (start_ts[1] - recv_ts[1]) / 1000000.0
        delta = " (delta %.6fs)" % d1
      else:
        delta = ""
      format_msg(1, "Processing start: %s%s" %
                 (FormatTimestamp(start_ts), delta))
    else:
      format_msg(1, "Processing start: unknown (%s)" % str(start_ts))

    if end_ts is not None:
      if start_ts is not None:
        d2 = end_ts[0] - start_ts[0] + (end_ts[1] - start_ts[1]) / 1000000.0
        delta = " (delta %.6fs)" % d2
      else:
        delta = ""
      format_msg(1, "Processing end:   %s%s" %
                 (FormatTimestamp(end_ts), delta))
    else:
      format_msg(1, "Processing end:   unknown (%s)" % str(end_ts))

    if end_ts is not None and recv_ts is not None:
      d3 = end_ts[0] - recv_ts[0] + (end_ts[1] - recv_ts[1]) / 1000000.0
      format_msg(1, "Total processing time: %.6f seconds" % d3)
    else:
      format_msg(1, "Total processing time: N/A")
    format_msg(1, "Opcodes:")
    for (opcode, result, status, log, s_ts, x_ts, e_ts) in \
            zip(ops, opresult, opstatus, oplog, opstart, opexec, opend):
      format_msg(2, "%s" % opcode["OP_ID"])
      format_msg(3, "Status: %s" % status)
      if isinstance(s_ts, (tuple, list)):
        format_msg(3, "Processing start: %s" % FormatTimestamp(s_ts))
      else:
        format_msg(3, "No processing start time")
      if isinstance(x_ts, (tuple, list)):
        format_msg(3, "Execution start:  %s" % FormatTimestamp(x_ts))
      else:
        format_msg(3, "No execution start time")
      if isinstance(e_ts, (tuple, list)):
        format_msg(3, "Processing end:   %s" % FormatTimestamp(e_ts))
      else:
        format_msg(3, "No processing end time")
      format_msg(3, "Input fields:")
      for key in utils.NiceSort(opcode.keys()):
        if key == "OP_ID":
          continue
        val = opcode[key]
        if isinstance(val, (tuple, list)):
          val = ",".join([str(item) for item in val])
        format_msg(4, "%s: %s" % (key, val))
      if result is None:
        format_msg(3, "No output data")
      elif isinstance(result, (tuple, list)):
        if not result:
          format_msg(3, "Result: empty sequence")
        else:
          format_msg(3, "Result:")
          for elem in result:
            format_msg(4, result_helper(elem))
      elif isinstance(result, dict):
        if not result:
          format_msg(3, "Result: empty dictionary")
        else:
          format_msg(3, "Result:")
          for key, val in result.iteritems():
            format_msg(4, "%s: %s" % (key, result_helper(val)))
      else:
        format_msg(3, "Result: %s" % result)
      format_msg(3, "Execution log:")
      for serial, log_ts, log_type, log_msg in log:
        time_txt = FormatTimestamp(log_ts)
        encoded = FormatLogMessage(log_type, log_msg)
        format_msg(4, "%s:%s:%s %s" % (serial, time_txt, log_type, encoded))
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


commands = {
  "list": (
    ListJobs, [ArgJobId()],
    [NOHDR_OPT, SEP_OPT, FIELDS_OPT, VERBOSE_OPT, FORCE_FILTER_OPT],
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
    CancelJobs, [ArgJobId(min=1)], [],
    "<job-id> [<job-id> ...]", "Cancel specified jobs"),
  "info": (
    ShowJobs, [ArgJobId(min=1)], [],
    "<job-id> [<job-id> ...]",
    "Show detailed information about the specified jobs"),
  "watch": (
    WatchJob, [ArgJobId(min=1, max=1)], [],
    "<job-id>", "Follows a job and prints its output as it arrives"),
  }


#: dictionary with aliases for commands
aliases = {
  "show": "info",
  }


def Main():
  return GenericMain(commands, aliases=aliases)
