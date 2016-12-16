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


"""Module implementing executing of a job as a separate process

The complete protocol of initializing a job is described in the haskell
module Ganeti.Query.Exec
"""

import contextlib
import logging
import os
import signal
import sys
import time

from ganeti import mcpu
from ganeti.server import masterd
from ganeti.rpc import transport
from ganeti import utils
from ganeti import pathutils
from ganeti.utils import livelock


def _GetMasterInfo():
  """Retrieves the job id and lock file name from the master process

  This also closes standard input/output

  """
  logging.debug("Opening transport over stdin/out")
  with contextlib.closing(transport.FdTransport((0, 1))) as trans:
    logging.debug("Reading job id from the master process")
    job_id = int(trans.Call(""))
    logging.debug("Got job id %d", job_id)
    logging.debug("Reading the livelock name from the master process")
    livelock_name = livelock.LiveLockName(trans.Call(""))
    logging.debug("Got livelock %s", livelock_name)
  return (job_id, livelock_name)


def main():

  debug = int(os.environ["GNT_DEBUG"])

  logname = pathutils.GetLogFilename("jobs")
  utils.SetupLogging(logname, "job-startup", debug=debug)

  (job_id, livelock_name) = _GetMasterInfo()

  utils.SetupLogging(logname, "job-%s" % (job_id,), debug=debug)

  exit_code = 1
  try:
    logging.debug("Preparing the context and the configuration")
    context = masterd.GanetiContext(livelock_name)

    logging.debug("Registering signal handlers")

    cancel = [False]
    prio_change = [False]

    def _TermHandler(signum, _frame):
      logging.info("Killed by signal %d", signum)
      cancel[0] = True
    signal.signal(signal.SIGTERM, _TermHandler)

    def _HupHandler(signum, _frame):
      logging.debug("Received signal %d, old flag was %s, will set to True",
                    signum, mcpu.sighupReceived)
      mcpu.sighupReceived[0] = True
    signal.signal(signal.SIGHUP, _HupHandler)

    def _User1Handler(signum, _frame):
      logging.info("Received signal %d, indicating priority change", signum)
      prio_change[0] = True
    signal.signal(signal.SIGUSR1, _User1Handler)

    logging.debug("Picking up job %d", job_id)
    context.jobqueue.PickupJob(job_id)

    # waiting for the job to finish
    time.sleep(1)
    while not context.jobqueue.HasJobBeenFinalized(job_id):
      if cancel[0]:
        logging.debug("Got cancel request, cancelling job %d", job_id)
        r = context.jobqueue.CancelJob(job_id)
        logging.debug("CancelJob result for job %d: %s", job_id, r)
        cancel[0] = False
      if prio_change[0]:
        logging.debug("Received priority-change request")
        try:
          fname = os.path.join(pathutils.LUXID_MESSAGE_DIR, "%d.prio" % job_id)
          new_prio = int(utils.ReadFile(fname))
          utils.RemoveFile(fname)
          logging.debug("Changing priority of job %d to %d", job_id, new_prio)
          r = context.jobqueue.ChangeJobPriority(job_id, new_prio)
          logging.debug("Result of changing priority of %d to %d: %s", job_id,
                        new_prio, r)
        except Exception: # pylint: disable=W0703
          logging.warning("Informed of priority change, but could not"
                          " read new priority")
        prio_change[0] = False
      time.sleep(1)

    # wait until the queue finishes
    logging.debug("Waiting for the queue to finish")
    while context.jobqueue.PrepareShutdown():
      time.sleep(1)
    logging.debug("Shutting the queue down")
    context.jobqueue.Shutdown()
    exit_code = 0
  except Exception: # pylint: disable=W0703
    logging.exception("Exception when trying to run job %d", job_id)
  finally:
    logging.debug("Job %d finalized", job_id)
    logging.debug("Removing livelock file %s", livelock_name.GetPath())
    os.remove(livelock_name.GetPath())

  sys.exit(exit_code)

if __name__ == '__main__':
  main()
