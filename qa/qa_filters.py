#
#

# Copyright (C) 2014 Google Inc.
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


"""QA tests for job filters.

"""

import time

from ganeti import query
from ganeti.utils import retry

from qa import qa_job_utils
from qa import qa_utils
from qa_utils import AssertCommand, AssertEqual, AssertIn, stdout_of


def GetJobStatus(job_id):
  """Queries the status of the job by parsing output of gnt-job info.

  @type job_id: int
  @param job_id: ID of the job to query
  @return: status of the job as lower-case string

  """
  out = stdout_of(["gnt-job", "info", str(job_id)])
  # The second line of gnt-job info shows the status.
  return out.split('\n')[1].strip().lower().split("status: ")[1]


def KillWaitJobs(job_ids):
  """Kills the lists of jobs, then watches them so that when this function
  returns we can be sure the jobs are all done.

  This should be called at the end of tests that started jobs with --submit
  so that following tests have an empty job queue.

  @type job_ids: list of int
  @param job_ids: the lists of job IDs to kill and wait for
  """
  # We use fail=None to ignore the exit code, since it can be non-zero
  # if the job is already terminated.
  for jid in job_ids:
    AssertCommand(["gnt-job", "cancel", "--kill", "--yes-do-it", str(jid)],
                  fail=None)
  for jid in job_ids:
    AssertCommand(["gnt-job", "watch", str(jid)], fail=None)


def AssertStatusRetry(jid, status, interval=1.0, timeout=20.0):
  """Keeps polling the given job until a given status is reached.

  @type jid: int
  @param jid: job ID of the job to poll
  @type status: string
  @param status: status to wait for
  @type interval: float
  @param interval: polling interval in seconds
  @type timeout: float
  @param timeout: polling timeout in seconds

  @raise retry:RetryTimeout: If the status was not reached within the timeout
  """
  retry_fn = lambda: qa_job_utils.RetryingUntilJobStatus(status, str(jid))
  retry.Retry(retry_fn, interval, timeout)


def TestFilterList():
  """gnt-filter list"""
  qa_utils.GenericQueryTest("gnt-filter", list(query.FILTER_FIELDS),
                            namefield="uuid", test_unknown=False)


def TestFilterListFields():
  """gnt-filter list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-filter", list(query.FILTER_FIELDS))


def TestFilterAddRemove():
  """gnt-filter add/delete"""

  uuid1 = stdout_of(["gnt-filter", "add", "--reason", "reason1"])

  TestFilterList()
  TestFilterListFields()

  uuid2 = stdout_of(["gnt-filter", "list", "--no-headers", "--output=uuid"])

  AssertEqual(uuid1, uuid2)

  AssertCommand(["gnt-filter", "delete", uuid1])

  TestFilterList()


def TestFilterWatermark():
  """Tests that the filter watermark is set correctly"""

  # Check what the current highest job ID is
  highest_jid1 = int(stdout_of(
    ["gnt-debug", "delay", "--print-jobid", "0.01"]
  ))

  # Add the filter; this sets the watermark
  uuid = stdout_of(["gnt-filter", "add"])

  # Check what the current highest job ID is
  highest_jid2 = int(stdout_of(
    ["gnt-debug", "delay", "--print-jobid", "0.01"]
  ))

  info_out = stdout_of(["gnt-filter", "info", uuid])
  # The second line of gnt-filter info shows the watermark.
  watermark = int(
    info_out.split('\n')[1].strip().lower().split("watermark: ")[1]
  )

  # The atermark must be at least as high as the JID of the job we started
  # just before the creation, and must be lower than the JID of any job
  # created afterwards.
  assert highest_jid1 <= watermark < highest_jid2, \
    "Watermark not in range: %d <= %d < %d" % (highest_jid1, watermark,
                                               highest_jid2)

  # Clean up.
  AssertCommand(["gnt-filter", "delete", uuid])


def TestFilterReject():
  """Tests that the REJECT filter does reject new jobs and that the
  "jobid" predicate works.
  """

  # Add a filter that rejects all new jobs.
  uuid = stdout_of([
    "gnt-filter", "add",
    '--predicates=[["jobid", [">", "id", "watermark"]]]',
    "--action=REJECT",
  ])

  # Newly queued jobs must now fail.
  AssertCommand(["gnt-debug", "delay", "0.01"], fail=True)

  # Clean up.
  AssertCommand(["gnt-filter", "delete", uuid])


def TestFilterOpCode():
  """Tests that filtering with the "opcode" predicate works"""

  # Check that delay jobs work fine.
  AssertCommand(["gnt-debug", "delay", "0.01"])

  # Add a filter that rejects all new delay jobs.
  uuid = stdout_of([
    "gnt-filter", "add",
    '--predicates=[["opcode", ["=", "OP_ID", "OP_TEST_DELAY"]]]',
    "--action=REJECT",
  ])

  # Newly queued delay jobs must now fail.
  AssertCommand(["gnt-debug", "delay", "0.01"], fail=True)

  # Clean up.
  AssertCommand(["gnt-filter", "delete", uuid])


def TestFilterContinue():
  """Tests that the CONTINUE filter has no effect"""

  # Add a filter that just passes to the next filter.
  uuid_cont = stdout_of([
    "gnt-filter", "add",
    '--predicates=[["jobid", [">", "id", "watermark"]]]',
    "--action=CONTINUE",
    "--priority=0",
  ])

  # Add a filter that rejects all new jobs.
  uuid_reject = stdout_of([
    "gnt-filter", "add",
    '--predicates=[["jobid", [">", "id", "watermark"]]]',
    "--action=REJECT",
    "--priority=1",
  ])

  # Newly queued jobs must now fail.
  AssertCommand(["gnt-debug", "delay", "0.01"], fail=True)

  # Delete the rejecting filter.
  AssertCommand(["gnt-filter", "delete", uuid_reject])

  # Newly queued jobs must now succeed.
  AssertCommand(["gnt-debug", "delay", "0.01"])

  # Clean up.
  AssertCommand(["gnt-filter", "delete", uuid_cont])


def TestFilterReasonChain():
  """Tests that filters are processed in the right order and that the
  "reason" predicate works.
  """

  # Add a filter chain that pauses all new jobs apart from those with a
  # specific reason.

  # Accept all jobs that have the "allow this" reason.
  uuid1 = stdout_of([
    "gnt-filter",
    "add",
    '--predicates=[["reason", ["=", "reason", "allow this"]]]',
    "--action=ACCEPT",
    # Default priority 0
  ])

  # Reject those that haven't (but make the one above run first).
  uuid2 = stdout_of([
    "gnt-filter",
    "add",
    '--predicates=[["jobid", [">", "id", "watermark"]]]',
    "--action=REJECT",
    "--priority=1",
  ])

  # This job must now go into queued status.
  AssertCommand(["gnt-debug", "delay", "0.01"], fail=True)
  AssertCommand(["gnt-debug", "delay", "--reason=allow this", "0.01"])

  # Clean up.
  AssertCommand(["gnt-filter", "delete", uuid1])
  AssertCommand(["gnt-filter", "delete", uuid2])


def TestFilterAcceptPause():
  """Tests that the PAUSE filter allows scheduling, but prevents starting,
  and that the ACCEPT filter immediately allows starting.
  """

  AssertCommand(["gnt-cluster", "watcher", "pause", "600"])

  # Add a filter chain that pauses all new jobs apart from those with a
  # specific reason.
  # When the pausing filter is deleted, paused jobs must be continued.

  # Accept all jobs that have the "allow this" reason.
  uuid1 = stdout_of([
    "gnt-filter",
    "add",
    '--predicates=[["reason", ["=", "reason", "allow this"]]]',
    "--action=ACCEPT",
    # Default priority 0
  ])

  # Pause those that haven't (but make the one above run first).
  uuid2 = stdout_of([
    "gnt-filter",
    "add",
    '--predicates=[["jobid", [">", "id", "watermark"]]]',
    "--action=PAUSE",
    "--priority=1",
  ])

  # This job must now go into queued status.
  jid1 = int(stdout_of([
    "gnt-debug", "delay", "--submit", "--print-jobid", "0.01",
  ]))

  # This job should run and finish.
  jid2 = int(stdout_of([
    "gnt-debug", "delay", "--submit", "--print-jobid", "--reason=allow this",
    "0.01",
  ]))

  time.sleep(5)  # give some time to get queued

  AssertStatusRetry(jid1, "queued")  # job should be paused
  AssertStatusRetry(jid2, "success")  # job should not be paused

  # Delete the filters.
  AssertCommand(["gnt-filter", "delete", uuid1])
  AssertCommand(["gnt-filter", "delete", uuid2])

  # Now the paused job should run through.
  time.sleep(5)
  AssertStatusRetry(jid1, "success")

  AssertCommand(["gnt-cluster", "watcher", "continue"])


def TestFilterRateLimit():
  """Tests that the RATE_LIMIT filter does reject new jobs when all
  rate-limiting buckets are taken.
  """

  # Make sure our test is not constrained by "max-running-jobs"
  # (simply set it to the default).
  AssertCommand(["gnt-cluster", "modify", "--max-running-jobs=20"])
  AssertCommand(["gnt-cluster", "modify", "--max-tracked-jobs=25"])
  AssertCommand(["gnt-cluster", "watcher", "pause", "600"])

  # Add a filter that rejects all new jobs.
  uuid = stdout_of([
    "gnt-filter", "add",
    '--predicates=[["jobid", [">", "id", "watermark"]]]',
    "--action=RATE_LIMIT 2",
  ])

  # Now only the first 2 jobs must be scheduled.
  jid1 = int(stdout_of([
    "gnt-debug", "delay", "--print-jobid", "--submit", "200"
  ]))
  jid2 = int(stdout_of([
    "gnt-debug", "delay", "--print-jobid", "--submit", "200"
  ]))
  jid3 = int(stdout_of([
    "gnt-debug", "delay", "--print-jobid", "--submit", "200"
  ]))

  time.sleep(5)  # give the scheduler some time to notice

  AssertIn(GetJobStatus(jid1), ["running", "waiting"],
           msg="Job should not be rate-limited")
  AssertIn(GetJobStatus(jid2), ["running", "waiting"],
           msg="Job should not be rate-limited")
  AssertEqual(GetJobStatus(jid3), "queued", msg="Job should be rate-limited")

  # Clean up.
  AssertCommand(["gnt-filter", "delete", uuid])
  KillWaitJobs([jid1, jid2, jid3])
  AssertCommand(["gnt-cluster", "watcher", "continue"])


def TestAdHocReasonRateLimit():
  """Tests that ad-hoc rate limiting using --reason="rate-limit:n:..." works.
  """

  # Make sure our test is not constrained by "max-running-jobs"
  # (simply set it to the default).
  AssertCommand(["gnt-cluster", "modify", "--max-running-jobs=20"])
  AssertCommand(["gnt-cluster", "modify", "--max-tracked-jobs=25"])

  # Only the first 2 jobs must be scheduled.
  jid1 = int(stdout_of([
    "gnt-debug", "delay", "--print-jobid", "--submit",
    "--reason=rate-limit:2:hello", "200",
  ]))
  jid2 = int(stdout_of([
    "gnt-debug", "delay", "--print-jobid", "--submit",
    "--reason=rate-limit:2:hello", "200",
  ]))
  jid3 = int(stdout_of([
    "gnt-debug", "delay", "--print-jobid", "--submit",
    "--reason=rate-limit:2:hello", "200",
  ]))

  time.sleep(5)  # give the scheduler some time to notice

  AssertIn(GetJobStatus(jid1), ["running", "waiting"],
           msg="Job should not be rate-limited")
  AssertIn(GetJobStatus(jid2), ["running", "waiting"],
           msg="Job should not be rate-limited")
  AssertEqual(GetJobStatus(jid3), "queued", msg="Job should be rate-limited")

  # Clean up.
  KillWaitJobs([jid1, jid2, jid3])
