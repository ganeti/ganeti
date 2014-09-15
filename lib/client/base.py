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
