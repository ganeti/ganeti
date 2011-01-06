#
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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

"""Debugging commands"""

# pylint: disable-msg=W0401,W0614,C0103
# W0401: Wildcard import ganeti.cli
# W0614: Unused import %s from wildcard import (since we need cli)
# C0103: Invalid name gnt-backup

import simplejson
import time
import socket
import logging

from ganeti.cli import *
from ganeti import cli
from ganeti import constants
from ganeti import opcodes
from ganeti import utils
from ganeti import errors
from ganeti import compat


#: Default fields for L{ListLocks}
_LIST_LOCKS_DEF_FIELDS = [
  "name",
  "mode",
  "owner",
  "pending",
  ]


def Delay(opts, args):
  """Sleeps for a while

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the duration
      the sleep
  @rtype: int
  @return: the desired exit code

  """
  delay = float(args[0])
  op = opcodes.OpTestDelay(duration=delay,
                           on_master=opts.on_master,
                           on_nodes=opts.on_nodes,
                           repeat=opts.repeat)
  SubmitOpCode(op, opts=opts)

  return 0


def GenericOpCodes(opts, args):
  """Send any opcode to the master.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the path of
      the file with the opcode definition
  @rtype: int
  @return: the desired exit code

  """
  cl = cli.GetClient()
  jex = cli.JobExecutor(cl=cl, verbose=opts.verbose, opts=opts)

  job_cnt = 0
  op_cnt = 0
  if opts.timing_stats:
    ToStdout("Loading...")
  for job_idx in range(opts.rep_job):
    for fname in args:
      # pylint: disable-msg=W0142
      op_data = simplejson.loads(utils.ReadFile(fname))
      op_list = [opcodes.OpCode.LoadOpCode(val) for val in op_data]
      op_list = op_list * opts.rep_op
      jex.QueueJob("file %s/%d" % (fname, job_idx), *op_list)
      op_cnt += len(op_list)
      job_cnt += 1

  if opts.timing_stats:
    t1 = time.time()
    ToStdout("Submitting...")

  jex.SubmitPending(each=opts.each)

  if opts.timing_stats:
    t2 = time.time()
    ToStdout("Executing...")

  jex.GetResults()
  if opts.timing_stats:
    t3 = time.time()
    ToStdout("C:op     %4d" % op_cnt)
    ToStdout("C:job    %4d" % job_cnt)
    ToStdout("T:submit %4.4f" % (t2-t1))
    ToStdout("T:exec   %4.4f" % (t3-t2))
    ToStdout("T:total  %4.4f" % (t3-t1))
  return 0


def TestAllocator(opts, args):
  """Runs the test allocator opcode.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should contain only one element, the iallocator name
  @rtype: int
  @return: the desired exit code

  """
  try:
    disks = [{"size": utils.ParseUnit(val), "mode": 'w'}
             for val in opts.disks.split(",")]
  except errors.UnitParseError, err:
    ToStderr("Invalid disks parameter '%s': %s", opts.disks, err)
    return 1

  nics = [val.split("/") for val in opts.nics.split(",")]
  for row in nics:
    while len(row) < 3:
      row.append(None)
    for i in range(3):
      if row[i] == '':
        row[i] = None
  nic_dict = [{"mac": v[0], "ip": v[1], "bridge": v[2]} for v in nics]

  if opts.tags is None:
    opts.tags = []
  else:
    opts.tags = opts.tags.split(",")

  op = opcodes.OpTestAllocator(mode=opts.mode,
                               name=args[0],
                               evac_nodes=args,
                               mem_size=opts.mem,
                               disks=disks,
                               disk_template=opts.disk_template,
                               nics=nic_dict,
                               os=opts.os,
                               vcpus=opts.vcpus,
                               tags=opts.tags,
                               direction=opts.direction,
                               allocator=opts.iallocator,
                               )
  result = SubmitOpCode(op, opts=opts)
  ToStdout("%s" % result)
  return 0


def _TestJobSubmission(opts):
  """Tests submitting jobs.

  """
  ToStdout("Testing job submission")

  testdata = [
    (0, 0, constants.OP_PRIO_LOWEST),
    (0, 0, constants.OP_PRIO_HIGHEST),
    ]

  for priority in (constants.OP_PRIO_SUBMIT_VALID |
                   frozenset([constants.OP_PRIO_LOWEST,
                              constants.OP_PRIO_HIGHEST])):
    for offset in [-1, +1]:
      testdata.extend([
        (0, 0, priority + offset),
        (3, 0, priority + offset),
        (0, 3, priority + offset),
        (4, 2, priority + offset),
        ])

  cl = cli.GetClient()

  for before, after, failpriority in testdata:
    ops = []
    ops.extend([opcodes.OpTestDelay(duration=0) for _ in range(before)])
    ops.append(opcodes.OpTestDelay(duration=0, priority=failpriority))
    ops.extend([opcodes.OpTestDelay(duration=0) for _ in range(after)])

    try:
      cl.SubmitJob(ops)
    except errors.GenericError, err:
      if opts.debug:
        ToStdout("Ignoring error: %s", err)
    else:
      raise errors.OpExecError("Submitting opcode with priority %s did not"
                               " fail when it should (allowed are %s)" %
                               (failpriority, constants.OP_PRIO_SUBMIT_VALID))

    jobs = [
      [opcodes.OpTestDelay(duration=0),
       opcodes.OpTestDelay(duration=0, dry_run=False),
       opcodes.OpTestDelay(duration=0, dry_run=True)],
      ops,
      ]
    result = cl.SubmitManyJobs(jobs)
    if not (len(result) == 2 and
            compat.all(len(i) == 2 for i in result) and
            compat.all(isinstance(i[1], basestring) for i in result) and
            result[0][0] and not result[1][0]):
      raise errors.OpExecError("Submitting multiple jobs did not work as"
                               " expected, result %s" % result)
    assert len(result) == 2

  ToStdout("Job submission tests were successful")


class _JobQueueTestReporter(cli.StdioJobPollReportCb):
  def __init__(self):
    """Initializes this class.

    """
    cli.StdioJobPollReportCb.__init__(self)
    self._expected_msgcount = 0
    self._all_testmsgs = []
    self._testmsgs = None
    self._job_id = None

  def GetTestMessages(self):
    """Returns all test log messages received so far.

    """
    return self._all_testmsgs

  def GetJobId(self):
    """Returns the job ID.

    """
    return self._job_id

  def ReportLogMessage(self, job_id, serial, timestamp, log_type, log_msg):
    """Handles a log message.

    """
    if self._job_id is None:
      self._job_id = job_id
    elif self._job_id != job_id:
      raise errors.ProgrammerError("The same reporter instance was used for"
                                   " more than one job")

    if log_type == constants.ELOG_JQUEUE_TEST:
      (sockname, test, arg) = log_msg
      return self._ProcessTestMessage(job_id, sockname, test, arg)

    elif (log_type == constants.ELOG_MESSAGE and
          log_msg.startswith(constants.JQT_MSGPREFIX)):
      if self._testmsgs is None:
        raise errors.OpExecError("Received test message without a preceding"
                                 " start message")
      testmsg = log_msg[len(constants.JQT_MSGPREFIX):]
      self._testmsgs.append(testmsg)
      self._all_testmsgs.append(testmsg)
      return

    return cli.StdioJobPollReportCb.ReportLogMessage(self, job_id, serial,
                                                     timestamp, log_type,
                                                     log_msg)

  def _ProcessTestMessage(self, job_id, sockname, test, arg):
    """Handles a job queue test message.

    """
    if test not in constants.JQT_ALL:
      raise errors.OpExecError("Received invalid test message %s" % test)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
      sock.settimeout(30.0)

      logging.debug("Connecting to %s", sockname)
      sock.connect(sockname)

      logging.debug("Checking status")
      jobdetails = cli.GetClient().QueryJobs([job_id], ["status"])[0]
      if not jobdetails:
        raise errors.OpExecError("Can't find job %s" % job_id)

      status = jobdetails[0]

      logging.debug("Status of job %s is %s", job_id, status)

      if test == constants.JQT_EXPANDNAMES:
        if status != constants.JOB_STATUS_WAITLOCK:
          raise errors.OpExecError("Job status while expanding names is '%s',"
                                   " not '%s' as expected" %
                                   (status, constants.JOB_STATUS_WAITLOCK))
      elif test in (constants.JQT_EXEC, constants.JQT_LOGMSG):
        if status != constants.JOB_STATUS_RUNNING:
          raise errors.OpExecError("Job status while executing opcode is '%s',"
                                   " not '%s' as expected" %
                                   (status, constants.JOB_STATUS_RUNNING))

      if test == constants.JQT_STARTMSG:
        logging.debug("Expecting %s test messages", arg)
        self._testmsgs = []
      elif test == constants.JQT_LOGMSG:
        if len(self._testmsgs) != arg:
          raise errors.OpExecError("Received %s test messages when %s are"
                                   " expected" % (len(self._testmsgs), arg))
    finally:
      logging.debug("Closing socket")
      sock.close()


def TestJobqueue(opts, _):
  """Runs a few tests on the job queue.

  """
  _TestJobSubmission(opts)

  (TM_SUCCESS,
   TM_MULTISUCCESS,
   TM_FAIL,
   TM_PARTFAIL) = range(4)
  TM_ALL = frozenset([TM_SUCCESS, TM_MULTISUCCESS, TM_FAIL, TM_PARTFAIL])

  for mode in TM_ALL:
    test_messages = [
      "Testing mode %s" % mode,
      "Hello World",
      "A",
      "",
      "B"
      "Foo|bar|baz",
      utils.TimestampForFilename(),
      ]

    fail = mode in (TM_FAIL, TM_PARTFAIL)

    if mode == TM_PARTFAIL:
      ToStdout("Testing partial job failure")
      ops = [
        opcodes.OpTestJobqueue(notify_waitlock=True, notify_exec=True,
                               log_messages=test_messages, fail=False),
        opcodes.OpTestJobqueue(notify_waitlock=True, notify_exec=True,
                               log_messages=test_messages, fail=False),
        opcodes.OpTestJobqueue(notify_waitlock=True, notify_exec=True,
                               log_messages=test_messages, fail=True),
        opcodes.OpTestJobqueue(notify_waitlock=True, notify_exec=True,
                               log_messages=test_messages, fail=False),
        ]
      expect_messages = 3 * [test_messages]
      expect_opstatus = [
        constants.OP_STATUS_SUCCESS,
        constants.OP_STATUS_SUCCESS,
        constants.OP_STATUS_ERROR,
        constants.OP_STATUS_ERROR,
        ]
      expect_resultlen = 2
    elif mode == TM_MULTISUCCESS:
      ToStdout("Testing multiple successful opcodes")
      ops = [
        opcodes.OpTestJobqueue(notify_waitlock=True, notify_exec=True,
                               log_messages=test_messages, fail=False),
        opcodes.OpTestJobqueue(notify_waitlock=True, notify_exec=True,
                               log_messages=test_messages, fail=False),
        ]
      expect_messages = 2 * [test_messages]
      expect_opstatus = [
        constants.OP_STATUS_SUCCESS,
        constants.OP_STATUS_SUCCESS,
        ]
      expect_resultlen = 2
    else:
      if mode == TM_SUCCESS:
        ToStdout("Testing job success")
        expect_opstatus = [constants.OP_STATUS_SUCCESS]
      elif mode == TM_FAIL:
        ToStdout("Testing job failure")
        expect_opstatus = [constants.OP_STATUS_ERROR]
      else:
        raise errors.ProgrammerError("Unknown test mode %s" % mode)

      ops = [
        opcodes.OpTestJobqueue(notify_waitlock=True,
                               notify_exec=True,
                               log_messages=test_messages,
                               fail=fail)
        ]
      expect_messages = [test_messages]
      expect_resultlen = 1

    cl = cli.GetClient()
    cli.SetGenericOpcodeOpts(ops, opts)

    # Send job to master daemon
    job_id = cli.SendJob(ops, cl=cl)

    reporter = _JobQueueTestReporter()
    results = None

    try:
      results = cli.PollJob(job_id, cl=cl, reporter=reporter)
    except errors.OpExecError, err:
      if not fail:
        raise
      ToStdout("Ignoring error: %s", err)
    else:
      if fail:
        raise errors.OpExecError("Job didn't fail when it should")

    # Check length of result
    if fail:
      if results is not None:
        raise errors.OpExecError("Received result from failed job")
    elif len(results) != expect_resultlen:
      raise errors.OpExecError("Received %s results (%s), expected %s" %
                               (len(results), results, expect_resultlen))

    # Check received log messages
    all_messages = [i for j in expect_messages for i in j]
    if reporter.GetTestMessages() != all_messages:
      raise errors.OpExecError("Received test messages don't match input"
                               " (input %r, received %r)" %
                               (all_messages, reporter.GetTestMessages()))

    # Check final status
    reported_job_id = reporter.GetJobId()
    if reported_job_id != job_id:
      raise errors.OpExecError("Reported job ID %s doesn't match"
                               "submission job ID %s" %
                               (reported_job_id, job_id))

    jobdetails = cli.GetClient().QueryJobs([job_id], ["status", "opstatus"])[0]
    if not jobdetails:
      raise errors.OpExecError("Can't find job %s" % job_id)

    if fail:
      exp_status = constants.JOB_STATUS_ERROR
    else:
      exp_status = constants.JOB_STATUS_SUCCESS

    (final_status, final_opstatus) = jobdetails
    if final_status != exp_status:
      raise errors.OpExecError("Final job status is %s, not %s as expected" %
                               (final_status, exp_status))
    if len(final_opstatus) != len(ops):
      raise errors.OpExecError("Did not receive status for all opcodes (got %s,"
                               " expected %s)" %
                               (len(final_opstatus), len(ops)))
    if final_opstatus != expect_opstatus:
      raise errors.OpExecError("Opcode status is %s, expected %s" %
                               (final_opstatus, expect_opstatus))

  ToStdout("Job queue test successful")

  return 0


def ListLocks(opts, args): # pylint: disable-msg=W0613
  """List all locks.

  @param opts: the command line options selected by the user
  @type args: list
  @param args: should be an empty list
  @rtype: int
  @return: the desired exit code

  """
  selected_fields = ParseFields(opts.output, _LIST_LOCKS_DEF_FIELDS)

  def _DashIfNone(fn):
    def wrapper(value):
      if not value:
        return "-"
      return fn(value)
    return wrapper

  def _FormatPending(value):
    """Format pending acquires.

    """
    return utils.CommaJoin("%s:%s" % (mode, ",".join(threads))
                           for mode, threads in value)

  # Format raw values
  fmtoverride = {
    "mode": (_DashIfNone(str), False),
    "owner": (_DashIfNone(",".join), False),
    "pending": (_DashIfNone(_FormatPending), False),
    }

  while True:
    ret = GenericList(constants.QR_LOCK, selected_fields, None, None,
                      opts.separator, not opts.no_headers,
                      format_override=fmtoverride)

    if ret != constants.EXIT_SUCCESS:
      return ret

    if not opts.interval:
      break

    ToStdout("")
    time.sleep(opts.interval)

  return 0


commands = {
  'delay': (
    Delay, [ArgUnknown(min=1, max=1)],
    [cli_option("--no-master", dest="on_master", default=True,
                action="store_false", help="Do not sleep in the master code"),
     cli_option("-n", dest="on_nodes", default=[],
                action="append", help="Select nodes to sleep on"),
     cli_option("-r", "--repeat", type="int", default="0", dest="repeat",
                help="Number of times to repeat the sleep"),
     DRY_RUN_OPT, PRIORITY_OPT,
     ],
    "[opts...] <duration>", "Executes a TestDelay OpCode"),
  'submit-job': (
    GenericOpCodes, [ArgFile(min=1)],
    [VERBOSE_OPT,
     cli_option("--op-repeat", type="int", default="1", dest="rep_op",
                help="Repeat the opcode sequence this number of times"),
     cli_option("--job-repeat", type="int", default="1", dest="rep_job",
                help="Repeat the job this number of times"),
     cli_option("--timing-stats", default=False,
                action="store_true", help="Show timing stats"),
     cli_option("--each", default=False, action="store_true",
                help="Submit each job separately"),
     DRY_RUN_OPT, PRIORITY_OPT,
     ],
    "<op_list_file...>", "Submits jobs built from json files"
    " containing a list of serialized opcodes"),
  'allocator': (
    TestAllocator, [ArgUnknown(min=1)],
    [cli_option("--dir", dest="direction",
                default="in", choices=["in", "out"],
                help="Show allocator input (in) or allocator"
                " results (out)"),
     IALLOCATOR_OPT,
     cli_option("-m", "--mode", default="relocate",
                choices=["relocate", "allocate", "multi-evacuate"],
                help="Request mode, either allocate or relocate"),
     cli_option("--mem", default=128, type="unit",
                help="Memory size for the instance (MiB)"),
     cli_option("--disks", default="4096,4096",
                help="Comma separated list of disk sizes (MiB)"),
     DISK_TEMPLATE_OPT,
     cli_option("--nics", default="00:11:22:33:44:55",
                help="Comma separated list of nics, each nic"
                " definition is of form mac/ip/bridge, if"
                " missing values are replace by None"),
     OS_OPT,
     cli_option("-p", "--vcpus", default=1, type="int",
                help="Select number of VCPUs for the instance"),
     cli_option("--tags", default=None,
                help="Comma separated list of tags"),
     DRY_RUN_OPT, PRIORITY_OPT,
     ],
    "{opts...} <instance>", "Executes a TestAllocator OpCode"),
  "test-jobqueue": (
    TestJobqueue, ARGS_NONE, [PRIORITY_OPT],
    "", "Test a few aspects of the job queue"),
  "locks": (
    ListLocks, ARGS_NONE, [NOHDR_OPT, SEP_OPT, FIELDS_OPT, INTERVAL_OPT],
    "[--interval N]", "Show a list of locks in the master daemon"),
  }


def Main():
  return GenericMain(commands)
