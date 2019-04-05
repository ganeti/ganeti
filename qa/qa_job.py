#
#

# Copyright (C) 2012, 2014 Google Inc.
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


"""Job-related QA tests.

"""

import functools
import re

from ganeti.utils import retry
from ganeti import constants
from ganeti import query
import qa_config
import qa_error
import qa_job_utils
import qa_utils
from qa_utils import AssertCommand, GetCommandOutput


def TestJobList():
  """gnt-job list"""
  qa_utils.GenericQueryTest("gnt-job", list(query.JOB_FIELDS),
                            namefield="id", test_unknown=False)


def TestJobListFields():
  """gnt-node list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-job", list(query.JOB_FIELDS))


def TestJobCancellation():
  """gnt-job cancel"""
  # The delay used for the first command should be large enough for the next
  # command and the cancellation command to complete before the first job is
  # done. The second delay should be small enough that not too much time is
  # spend waiting in the case of a failed cancel and a running command.
  FIRST_COMMAND_DELAY = 10.0
  AssertCommand(["gnt-debug", "delay", "--submit", str(FIRST_COMMAND_DELAY)])

  SECOND_COMMAND_DELAY = 3.0
  master = qa_config.GetMasterNode()

  # Forcing tty usage does not work on buildbot, so force all output of this
  # command to be redirected to stdout
  job_id_output = GetCommandOutput(
    master.primary, "gnt-debug delay --submit %s 2>&1" % SECOND_COMMAND_DELAY
  )

  possible_job_ids = re.findall("JobID: ([0-9]+)", job_id_output)
  if len(possible_job_ids) != 1:
    raise qa_error.Error("Cannot parse gnt-debug delay output to find job id")

  job_id = possible_job_ids[0]
  AssertCommand(["gnt-job", "cancel", job_id])

  # Now wait until the second job finishes, and expect the watch to fail due to
  # job cancellation
  AssertCommand(["gnt-job", "watch", job_id], fail=True)

  # Then check for job cancellation
  job_status = qa_job_utils.GetJobStatus(job_id)
  if job_status != constants.JOB_STATUS_CANCELED:
    # Try and see if the job is being cancelled, and wait until the status
    # changes or we hit a timeout
    if job_status == constants.JOB_STATUS_CANCELING:
      retry_fn = functools.partial(qa_job_utils.RetryingWhileJobStatus,
                                   constants.JOB_STATUS_CANCELING, job_id)
      try:
        # The multiplier to use is arbitrary, setting it higher could prevent
        # flakiness
        WAIT_MULTIPLIER = 4.0
        job_status = retry.Retry(retry_fn, 2.0,
                                 WAIT_MULTIPLIER * FIRST_COMMAND_DELAY)
      except retry.RetryTimeout:
        # The job status remains the same
        pass

    if job_status != constants.JOB_STATUS_CANCELED:
      raise qa_error.Error("Job was not successfully cancelled, status "
                           "found: %s" % job_status)
