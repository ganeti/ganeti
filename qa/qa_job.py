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

from ganeti import constants
from ganeti import query

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
  status_dict = _GetJobStatuses()
  if status_dict.get(job_id, None) != constants.JOB_STATUS_CANCELED:
    raise qa_error.Error("Job was not successfully cancelled!")
