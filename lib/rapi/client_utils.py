#
#

# Copyright (C) 2010 Google Inc.
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


"""RAPI client utilities.

"""

from ganeti import constants
from ganeti import cli

from ganeti.rapi import client

# Local constant to avoid importing ganeti.http
HTTP_NOT_FOUND = 404


class RapiJobPollCb(cli.JobPollCbBase):
  def __init__(self, cl):
    """Initializes this class.

    @param cl: RAPI client instance

    """
    cli.JobPollCbBase.__init__(self)

    self.cl = cl

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial):
    """Waits for changes on a job.

    """
    try:
      result = self.cl.WaitForJobChange(job_id, fields,
                                        prev_job_info, prev_log_serial)
    except client.GanetiApiError, err:
      if err.code == HTTP_NOT_FOUND:
        return None

      raise

    if result is None:
      return constants.JOB_NOTCHANGED

    return (result["job_info"], result["log_entries"])

  def QueryJobs(self, job_ids, fields):
    """Returns the given fields for the selected job IDs.

    @type job_ids: list of numbers
    @param job_ids: Job IDs
    @type fields: list of strings
    @param fields: Fields

    """
    if len(job_ids) != 1:
      raise NotImplementedError("Only one job supported at this time")

    try:
      result = self.cl.GetJobStatus(job_ids[0])
    except client.GanetiApiError, err:
      if err.code == HTTP_NOT_FOUND:
        return [None]

      raise

    return [[result[name] for name in fields], ]


def PollJob(rapi_client, job_id, reporter):
  """Function to poll for the result of a job.

  @param rapi_client: RAPI client instance
  @type job_id: number
  @param job_id: Job ID
  @type reporter: L{cli.JobPollReportCbBase}
  @param reporter: PollJob reporter instance

  """
  return cli.GenericPollJob(job_id, RapiJobPollCb(rapi_client), reporter)
