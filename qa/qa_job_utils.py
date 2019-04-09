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


"""QA utility functions for testing jobs

"""

import re
import sys
import threading
import time

from ganeti import constants
from ganeti import locking
from ganeti import utils
from ganeti.utils import retry

import qa_config
import qa_logging
import qa_error

from qa_utils import AssertCommand, GetCommandOutput, GetObjectInfo, stdout_of


AVAILABLE_LOCKS = [locking.LEVEL_NODE, ]


def GetOutputFromMaster(cmd, use_multiplexer=True, log_cmd=True):
  """ Gets the output of a command executed on master.

  """
  if isinstance(cmd, str):
    cmdstr = cmd
  else:
    cmdstr = utils.ShellQuoteArgs(cmd)

  # Necessary due to the stderr stream not being captured properly on the
  # buildbot
  cmdstr += " 2>&1"

  return GetCommandOutput(qa_config.GetMasterNode().primary, cmdstr,
                          use_multiplexer=use_multiplexer, log_cmd=log_cmd)


def ExecuteJobProducingCommand(cmd):
  """ Executes a command that contains the --submit flag, and returns a job id.

  @type cmd: list of string
  @param cmd: The command to execute, broken into constituent components.

  """
  job_id_output = GetOutputFromMaster(cmd)

  # Usually, the output contains "JobID: <job_id>", but for instance related
  # commands, the output is of the form "<job_id>: <instance_name>"
  possible_job_ids = re.findall("JobID: ([0-9]+)", job_id_output) or \
                     re.findall("([0-9]+): .+", job_id_output)
  if len(possible_job_ids) != 1:
    raise qa_error.Error("Cannot parse command output to find job id: output "
                         "is %s" % job_id_output)

  return int(possible_job_ids[0])


def GetJobStatuses(job_ids=None):
  """ Invokes gnt-job list and extracts an id to status dictionary.

  @type job_ids: list
  @param job_ids: list of job ids to query the status for; if C{None}, the
                  status of all current jobs is returned
  @rtype: dict of string to string
  @return: A dictionary mapping job ids to matching statuses

  """
  cmd = ["gnt-job", "list", "--no-headers", "--output=id,status"]
  if job_ids is not None:
    cmd.extend([str(id) for id in job_ids])

  list_output = GetOutputFromMaster(cmd)
  return dict([s.split() for s in list_output.splitlines()])


def _RetrieveTerminationInfo(job_id):
  """ Retrieves the termination info from a job caused by gnt-debug delay.

  @rtype: dict or None
  @return: The termination log entry, or None if no entry was found

  """
  job_info = GetObjectInfo(["gnt-job", "info", str(job_id)])

  opcodes = job_info[0]["Opcodes"]
  if not opcodes:
    raise qa_error.Error("Cannot retrieve a list of opcodes")

  execution_logs = opcodes[0]["Execution log"]
  if not execution_logs:
    return None

  is_termination_info_fn = \
    lambda e: e["Content"][1] == constants.ELOG_DELAY_TEST

  filtered_logs = [l for l in execution_logs if is_termination_info(l)]

  no_logs = len(filtered_logs)
  if no_logs > 1:
    raise qa_error.Error("Too many interruption information entries found!")
  elif no_logs == 1:
    return filtered_logs[0]
  else:
    return None


def _StartDelayFunction(locks, timeout):
  """ Starts the gnt-debug delay option with the given locks and timeout.

  """
  # The interruptible switch must be used
  cmd = ["gnt-debug", "delay", "-i", "--submit", "--no-master"]

  for node in locks.get(locking.LEVEL_NODE, []):
    cmd.append("-n%s" % node)
  cmd.append(str(timeout))

  job_id = ExecuteJobProducingCommand(cmd)

  # Waits until a non-empty result is returned from the function
  log_entry = retry.SimpleRetry(lambda x: x, _RetrieveTerminationInfo, 2.0,
                                10.0, args=[job_id])

  if not log_entry:
    raise qa_error.Error("Failure when trying to retrieve delay termination "
                         "information")

  _, _, (socket_path, ) = log_entry["Content"]

  return socket_path


def _TerminateDelayFunction(termination_socket):
  """ Terminates the delay function by communicating with the domain socket.

  """
  AssertCommand("echo a | socat -u stdin UNIX-CLIENT:%s" % termination_socket)


def _GetNodeUUIDMap(nodes):
  """ Given a list of nodes, retrieves a mapping of their names to UUIDs.

  @type nodes: list of string
  @param nodes: The nodes to retrieve a map for. If empty, returns information
                for all the nodes.

  """
  cmd = ["gnt-node", "list", "--no-header", "-o", "name,uuid"]
  cmd.extend(nodes)
  output = GetOutputFromMaster(cmd)
  return dict([x.split() for x in output.splitlines()])


def _FindLockNames(locks):
  """ Finds the ids and descriptions of locks that given locks can block.

  @type locks: dict of locking level to list
  @param locks: The locks that gnt-debug delay is holding.

  @rtype: dict of string to string
  @return: The lock name to entity name map.

  For a given set of locks, some internal locks (e.g. ALL_SET locks) can be
  blocked even though they were not listed explicitly. This function has to take
  care and list all locks that can be blocked by the locks given as parameters.

  """
  lock_map = {}

  if locking.LEVEL_NODE in locks:
    node_locks = locks[locking.LEVEL_NODE]
    if node_locks == locking.ALL_SET:
      # Empty list retrieves all info
      name_uuid_map = _GetNodeUUIDMap([])
    else:
      name_uuid_map = _GetNodeUUIDMap(node_locks)

    for name in name_uuid_map:
      lock_map["node/%s" % name_uuid_map[name]] = name

    # If ALL_SET was requested explicitly, or there is at least one lock
    # Note that locking.ALL_SET is None and hence the strange form of the if
    if node_locks == locking.ALL_SET or node_locks:
      lock_map["node/[lockset]"] = "joint node lock"

  #TODO add other lock types here when support for these is added
  return lock_map


def _GetBlockingLocks():
  """ Finds out which locks are blocking jobs by invoking "gnt-debug locks".

  @rtype: list of string
  @return: The names of the locks currently blocking any job.

  """
  # Due to mysterious issues when a SSH multiplexer is being used by two
  # threads, we turn it off, and block most of the logging to improve the
  # visibility of the other thread's output
  locks_output = GetOutputFromMaster("gnt-debug locks", use_multiplexer=False,
                                     log_cmd=False)

  # The first non-empty line is the header, which we do not need
  lock_lines = locks_output.splitlines()[1:]

  blocking_locks = []
  for lock_line in lock_lines:
    components = lock_line.split()
    if len(components) != 4:
      raise qa_error.Error("Error while parsing gnt-debug locks output, "
                           "line at fault is: %s" % lock_line)

    lock_name, _, _, pending_jobs = components

    if pending_jobs != '-':
      blocking_locks.append(lock_name)

  return blocking_locks


class QAThread(threading.Thread):
  """ An exception-preserving thread that executes a given function.

  """
  def __init__(self, fn, args, kwargs):
    """ Constructor accepting the function to be invoked later.

    """
    threading.Thread.__init__(self)
    self._fn = fn
    self._args = args
    self._kwargs = kwargs
    self._exc_info = None

  def run(self):
    """ Executes the function, preserving exception info if necessary.

    """
    # pylint: disable=W0702
    # We explicitly want to catch absolutely anything
    try:
      self._fn(*self._args, **self._kwargs)
    except:
      self._exc_info = sys.exc_info()
    # pylint: enable=W0702

  def reraise(self):
    """ Reraises any exceptions that might have occured during thread execution.

    """
    if self._exc_info is not None:
      raise self._exc_info[0](self._exc_info[1]).with_traceback(self._exc_info[2])


class QAThreadGroup(object):
  """This class manages a list of QAThreads.

  """
  def __init__(self):
    self._threads = []

  def Start(self, thread):
    """Starts the given thread and adds it to this group.

    @type thread: qa_job_utils.QAThread
    @param thread: the thread to start and to add to this group.

    """
    thread.start()
    self._threads.append(thread)

  def JoinAndReraise(self):
    """Joins all threads in this group and calls their C{reraise} method.

    """
    for thread in self._threads:
      thread.join()
      thread.reraise()


class PausedWatcher(object):
  """Pauses the watcher for the duration of the inner code

  """
  def __enter__(self):
    AssertCommand(["gnt-cluster", "watcher", "pause", "12h"])

  def __exit__(self, _ex_type, ex_value, _ex_traceback):
    try:
      AssertCommand(["gnt-cluster", "watcher", "continue"])
    except qa_error.Error as err:
      # If an exception happens during 'continue', re-raise it only if there
      # is no exception from the inner block:
      if ex_value is None:
        raise
      else:
        print(qa_logging.FormatError('Re-enabling watcher failed: %s' %
                                     (err, )))


# TODO: Can this be done as a decorator? Implement as needed.
def RunWithLocks(fn, locks, timeout, block, *args, **kwargs):
  """ Runs the given function, acquiring a set of locks beforehand.

  @type fn: function
  @param fn: The function to invoke.
  @type locks: dict of string to list of string
  @param locks: The locks to acquire, per lock category.
  @type timeout: number
  @param timeout: The number of seconds the locks should be held before
                  expiring.
  @type block: bool
  @param block: Whether the test should block when locks are used or not.

  This function allows a set of locks to be acquired in preparation for a QA
  test, to try and see if the function can run in parallel with other
  operations.

  Locks are acquired by invoking a gnt-debug delay operation which can be
  interrupted as needed. The QA test is then run in a separate thread, with the
  current thread observing jobs waiting for locks. When a job is spotted waiting
  for a lock held by the started delay operation, this is noted, and the delay
  is interrupted, allowing the QA test to continue.

  A default timeout is not provided by design - the test creator must make a
  good conservative estimate.

  """
  if [l_type for l_type in locks if l_type not in AVAILABLE_LOCKS]:
    raise qa_error.Error("Attempted to acquire locks that cannot yet be "
                         "acquired in the course of a QA test.")

  # The watcher may interfere by issuing its own jobs - therefore pause it
  # also reject all its jobs and wait for any running jobs to finish.
  AssertCommand(["gnt-cluster", "watcher", "pause", "12h"])
  filter_uuid = stdout_of([
    "gnt-filter", "add",
    '--predicates=[["reason", ["=", "source", "gnt:watcher"]]]',
    "--action=REJECT"
  ])
  while stdout_of(["gnt-job", "list", "--no-header", "--running"]) != "":
    time.sleep(1)

  # Find out the lock names prior to starting the delay function
  lock_name_map = _FindLockNames(locks)

  blocking_owned_locks = []
  test_blocked = False

  termination_socket = _StartDelayFunction(locks, timeout)
  delay_fn_terminated = False

  try:
    qa_thread = QAThread(fn, args, kwargs)
    qa_thread.start()

    while qa_thread.isAlive():
      blocking_locks = _GetBlockingLocks()
      blocking_owned_locks = \
        set(blocking_locks).intersection(set(lock_name_map))

      if blocking_owned_locks:
        # Set the flag first - if the termination attempt fails, we do not want
        # to redo it in the finally block
        delay_fn_terminated = True
        _TerminateDelayFunction(termination_socket)
        test_blocked = True
        break

      time.sleep(5) # Set arbitrarily

    # The thread should be either finished or unblocked at this point
    qa_thread.join()

    # Raise any errors that might have occured in the thread
    qa_thread.reraise()

  finally:
    if not delay_fn_terminated:
      _TerminateDelayFunction(termination_socket)

  blocking_lock_names = ", ".join(map(lock_name_map.get, blocking_owned_locks))
  if not block and test_blocked:
    raise qa_error.Error("QA test succeded, but was blocked by locks: %s" %
                         blocking_lock_names)
  elif block and not test_blocked:
    raise qa_error.Error("QA test succeded, but was not blocked as it was "
                         "expected to by locks: %s" % blocking_lock_names)
  else:
    pass

  # Revive the watcher
  AssertCommand(["gnt-filter", "delete", filter_uuid])
  AssertCommand(["gnt-cluster", "watcher", "continue"])


def GetJobStatus(job_id):
  """ Retrieves the status of a job.

  @type job_id: string
  @param job_id: The job id, represented as a string.
  @rtype: string or None

  @return: The job status, or None if not present.

  """
  return GetJobStatuses([job_id]).get(job_id, None)


def RetryingUntilJobStatus(retry_status, job_id):
  """ Used with C{retry.Retry}, waits for a given status.

  @type retry_status: string
  @param retry_status: The job status to wait for.
  @type job_id: string
  @param job_id: The job id, represented as a string.

  """
  status = GetJobStatus(job_id)
  if status != retry_status:
    raise retry.RetryAgain()


def RetryingWhileJobStatus(retry_status, job_id):
  """ Used with C{retry.Retry}, waits for a status other than the one given.

  @type retry_status: string
  @param retry_status: The old job status, expected to change.
  @type job_id: string
  @param job_id: The job id, represented as a string.

  @rtype: string or None
  @return: The new job status, or None if none could be retrieved.

  """
  status = GetJobStatus(job_id)
  if status == retry_status:
    raise retry.RetryAgain()
  return status
