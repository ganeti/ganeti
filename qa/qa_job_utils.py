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


"""QA utility functions for testing jobs

"""

import re

from ganeti import constants
from ganeti import locking
from ganeti import utils

import qa_config
import qa_error

from qa_utils import AssertCommand, GetCommandOutput, GetObjectInfo


AVAILABLE_LOCKS = [locking.LEVEL_NODE, ]


def _GetOutputFromMaster(cmd):
  """ Gets the output of a command executed on master.

  """
  if isinstance(cmd, basestring):
    cmdstr = cmd
  else:
    cmdstr = utils.ShellQuoteArgs(cmd)

  # Necessary due to the stderr stream not being captured properly on the
  # buildbot
  cmdstr += " 2>&1"

  return GetCommandOutput(qa_config.GetMasterNode().primary, cmdstr)


def ExecuteJobProducingCommand(cmd):
  """ Executes a command that contains the --submit flag, and returns a job id.

  @type cmd: list of string
  @param cmd: The command to execute, broken into constituent components.

  """
  job_id_output = _GetOutputFromMaster(cmd)

  possible_job_ids = re.findall("JobID: ([0-9]+)", job_id_output)
  if len(possible_job_ids) != 1:
    raise qa_error.Error("Cannot parse command output to find job id: output "
                         "is %s" % job_id_output)

  return int(possible_job_ids[0])


def _StartDelayFunction(locks, timeout):
  """ Starts the gnt-debug delay option with the given locks and timeout.

  """
  # The interruptible switch must be used
  cmd = ["gnt-debug", "delay", "-i", "--submit", "--no-master"]

  for node in locks.get(locking.LEVEL_NODE, []):
    cmd.append("-n%s" % node)

  cmd.append(str(timeout))

  job_id = ExecuteJobProducingCommand(cmd)
  job_info = GetObjectInfo(["gnt-job", "info", str(job_id)])
  execution_logs = job_info[0]["Opcodes"][0]["Execution log"]

  is_termination_info_fn = \
    lambda e: e["Content"][1] == constants.ELOG_DELAY_TEST
  filtered_logs = filter(is_termination_info_fn, execution_logs)

  if len(filtered_logs) != 1:
    raise qa_error.Error("Failure when trying to retrieve delay termination "
                         "information")

  _, _, (socket_path, ) = filtered_logs[0]["Content"]

  return socket_path


def _TerminateDelayFunction(termination_socket):
  """ Terminates the delay function by communicating with the domain socket.

  """
  AssertCommand("echo a | socat -u stdin UNIX-CLIENT:%s" % termination_socket)


# TODO: Can this be done as a decorator? Implement as needed.
def RunWithLocks(fn, locks, timeout, *args, **kwargs):
  """ Runs the given function, acquiring a set of locks beforehand.

  @type fn: function
  @param fn: The function to invoke.
  @type locks: dict of string to list of string
  @param locks: The locks to acquire, per lock category.
  @type timeout: number
  @param timeout: The number of seconds the locks should be held before
                  expiring.

  This function allows a set of locks to be acquired in preparation for a QA
  test, to try and see if the function can run in parallel with other
  operations.

  The current version simply creates the locks, which expire after a given
  timeout, and attempts to invoke the provided function.

  This will probably block the QA, and future versions will address this.

  A default timeout is not provided by design - the test creator must make a
  good conservative estimate.

  """
  if filter(lambda l_type: l_type not in AVAILABLE_LOCKS, locks):
    raise qa_error.Error("Attempted to acquire locks that cannot yet be "
                         "acquired in the course of a QA test.")

  # The watcher may interfere by issuing its own jobs - therefore pause it
  AssertCommand(["gnt-cluster", "watcher", "pause", "12h"])

  termination_socket = _StartDelayFunction(locks, timeout)

  fn(*args, **kwargs)

  _TerminateDelayFunction(termination_socket)

  # Revive the watcher
  AssertCommand(["gnt-cluster", "watcher", "continue"])
