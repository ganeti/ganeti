#
#

# Copyright (C) 2015 Google Inc.
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


"""Module implementing the execution of opcode post hooks in a separate process

This process receives the job_id from the master process and runs global post
hooks for the last opcode whose execution started before the job process
disappeared.

"""

import contextlib
import logging
import os
import sys

from ganeti import constants
from ganeti import hooksmaster
from ganeti import pathutils
from ganeti import utils
from ganeti.jqueue import JobQueue
from ganeti.rpc import transport
from ganeti.server import masterd
from ganeti.utils import livelock


def _GetMasterInfo():
  """Retrieve the job id from the master process

  This also closes standard input/output

  @rtype: int

  """
  logging.debug("Reading job id from the master process")
  logging.debug("Opening transport over stdin/out")
  with contextlib.closing(transport.FdTransport((0, 1))) as trans:
    job_id = int(trans.Call(""))
    logging.debug("Got job id %d", job_id)
  return job_id


def main():

  debug = int(os.environ["GNT_DEBUG"])

  logname = pathutils.GetLogFilename("jobs")
  utils.SetupLogging(logname, "job-post-hooks-startup", debug=debug)
  job_id = _GetMasterInfo()
  utils.SetupLogging(logname, "job-%s-post-hooks" % (job_id,), debug=debug)

  try:
    job = JobQueue.SafeLoadJobFromDisk(None, job_id, try_archived=False,
                                       writable=False)
    assert job.id == job_id, "The job id received %d differs " % job_id + \
      "from the serialized one %d" % job.id

    target_op = None
    for op in job.ops:
      if op.start_timestamp is None:
        break
      target_op = op

    # We should run post hooks only if opcode execution has been started.
    # Note that currently the opcodes inside a job execute sequentially.
    if target_op is None:
      sys.exit(0)

    livelock_name = livelock.LiveLockName("post-hooks-executor-%d" % job_id)
    context = masterd.GanetiContext(livelock_name)
    cfg_tmp = context.GetConfig(job_id)
    # Get static snapshot of the config and release it in order to prevent
    # further synchronizations.
    cfg = cfg_tmp.GetDetachedConfig()
    cfg_tmp.OutDate()

    hooksmaster.ExecGlobalPostHooks(target_op.input.OP_ID,
                                    cfg.GetMasterNodeName(),
                                    context.GetRpc(cfg).call_hooks_runner,
                                    logging.warning, cfg.GetClusterName(),
                                    cfg.GetMasterNode(), job_id,
                                    constants.POST_HOOKS_STATUS_DISAPPEARED)
  except Exception: # pylint: disable=W0703
    logging.exception("Exception when trying to run post hooks of job %d",
                      job_id)
  finally:
    logging.debug("Post hooks exec for disappeared job %d finalized", job_id)
    logging.debug("Removing livelock file %s", livelock_name.GetPath())
    os.remove(livelock_name.GetPath())

  sys.exit(0)

if __name__ == '__main__':
  main()
