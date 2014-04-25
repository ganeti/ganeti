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
  logname = pathutils.GetLogFilename("jobs")
  utils.SetupLogging(logname, "job-startup", debug=True) # TODO

  (job_id, livelock_name) = _GetMasterInfo()

  utils.SetupLogging(logname, "job-%s" % (job_id,), debug=True) # TODO

  exit_code = 1
  try:
    logging.debug("Preparing the context and the configuration")
    context = masterd.GanetiContext(livelock_name)

    logging.debug("Registering a SIGTERM handler")

    cancel = [False]

    def _TermHandler(signum, _frame):
      logging.info("Killed by signal %d", signum)
      cancel[0] = True
    signal.signal(signal.SIGTERM, _TermHandler)

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
