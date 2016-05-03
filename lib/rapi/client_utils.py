#
#

# Copyright (C) 2010 Google Inc.
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
                           prev_job_info, prev_log_serial,
                           timeout=constants.DEFAULT_WFJC_TIMEOUT):
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

  def CancelJob(self, job_id):
    """Cancels a currently running job.

    """
    return self.cl.CancelJob(job_id)


def PollJob(rapi_client, job_id, reporter):
  """Function to poll for the result of a job.

  @param rapi_client: RAPI client instance
  @type job_id: number
  @param job_id: Job ID
  @type reporter: L{cli.JobPollReportCbBase}
  @param reporter: PollJob reporter instance

  @return: The opresult of the job
  @raise errors.JobLost: If job can't be found
  @raise errors.OpExecError: if job didn't succeed

  @see: L{ganeti.cli.GenericPollJob}

  """
  return cli.GenericPollJob(job_id, RapiJobPollCb(rapi_client), reporter)
