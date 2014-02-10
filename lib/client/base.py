#
#

# Copyright (C) 2014 Google Inc.
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


"""Utils for CLI commands"""

from ganeti import cli
from ganeti import constants
from ganeti import ht


def GetResult(cl, opts, result):
  """Waits for jobs and returns whether they have succeeded

  Some OpCodes return of list of jobs.  This function can be used
  after issueing a given OpCode to look at the OpCode's result and, if
  it is of type L{ht.TJobIdListOnly}, then it will wait for the jobs
  to complete, otherwise just return L{constants.EXIT_SUCCESS}.

  @type cl: L{ganeti.luxi.Client}
  @param cl: client that was used to submit the OpCode, which will
             also be used to poll the jobs

  @param opts: CLI options

  @param result: result of the opcode which might contain job
         information, in which case the jobs will be polled, or simply
         the result of the opcode

  @rtype: int
  @return: L{constants.EXIT_SUCCESS} if all jobs completed
           successfully, L{constants.EXIT_FAILURE} otherwise

  """
  if not ht.TJobIdListOnly(result):
    return constants.EXIT_SUCCESS

  jex = cli.JobExecutor(cl=cl, opts=opts)

  for (status, job_id) in result[constants.JOB_IDS_KEY]:
    jex.AddJobId(None, status, job_id)

  bad_jobs = [job_result
              for success, job_result in jex.GetResults()
              if not success]

  if len(bad_jobs) > 0:
    for job in bad_jobs:
      cli.ToStdout("Job failed, result is '%s'.", job)
    cli.ToStdout("%s job(s) failed.", bad_jobs)
    return constants.EXIT_FAILURE
  else:
    return constants.EXIT_SUCCESS
