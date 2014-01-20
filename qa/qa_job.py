#
#

# Copyright (C) 2012, 2014 Google Inc.
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


"""Job-related QA tests.

"""

from ganeti.utils import retry
from ganeti import constants
from ganeti import query

import functools
import re

import qa_config
import qa_error
import qa_utils

from qa_utils import AssertCommand, GetCommandOutput


def TestJobList():
  """gnt-job list"""
  qa_utils.GenericQueryTest("gnt-job", query.JOB_FIELDS.keys(),
                            namefield="id", test_unknown=False)


def TestJobListFields():
  """gnt-node list-fields"""
  qa_utils.GenericQueryFieldsTest("gnt-job", query.JOB_FIELDS.keys())


def _GetJobStatuses():
  """ Invokes gnt-job list and extracts an id to status dictionary.

  @rtype: dict of string to string
  @return: A dictionary mapping job ids to matching statuses

  """
  master = qa_config.GetMasterNode()
  list_output = GetCommandOutput(
    master.primary, "gnt-job list --no-headers --output=id,status"
  )
  return dict(map(lambda s: s.split(), list_output.splitlines()))


def _GetJobStatus(job_id):
  """ Retrieves the status of a job.

  @type job_id: string
  @param job_id: The job id, represented as a string.
  @rtype: string or None

  @return: The job status, or None if not present.

  """
  return _GetJobStatuses().get(job_id, None)


def _RetryingFetchJobStatus(retry_status, job_id):
  """ Used with C{retry.Retry}, waits for a status other than the one given.

  @type retry_status: string
  @param retry_status: The old job status, expected to change.
  @type job_id: string
  @param job_id: The job id, represented as a string.

  @rtype: string or None
  @return: The new job status, or None if none could be retrieved.

  """
  status = _GetJobStatus(job_id)
  if status == retry_status:
    raise retry.RetryAgain()
  return status


def TestJobCancellation():
  """gnt-job cancel"""
  # The delay used for the first command should be large enough for the next
  # command and the cancellation command to complete before the first job is
  # done. The second delay should be small enough that not too much time is
  # spend waiting in the case of a failed cancel and a running command.
  FIRST_COMMAND_DELAY = 10.0
  AssertCommand(["gnt-debug", "delay", "--submit", str(FIRST_COMMAND_DELAY)])

  SECOND_COMMAND_DELAY = 1.0
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
  job_status = _GetJobStatus(job_id)
  if job_status != constants.JOB_STATUS_CANCELED:
    # Try and see if the job is being cancelled, and wait until the status
    # changes or we hit a timeout
    if job_status == constants.JOB_STATUS_CANCELING:
      retry_fn = functools.partial(_RetryingFetchJobStatus,
                                   constants.JOB_STATUS_CANCELING, job_id)
      try:
        job_status = retry.Retry(retry_fn, 2.0, 2 * FIRST_COMMAND_DELAY)
      except retry.RetryTimeout:
        # The job status remains the same
        pass

    if job_status != constants.JOB_STATUS_CANCELED:
      raise qa_error.Error("Job was not successfully cancelled, status "
                           "found: %s" % job_status)
