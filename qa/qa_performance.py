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


"""Performance testing QA tests.

"""

import datetime
import functools
import itertools
import threading
import time

from ganeti import constants

from qa import qa_config
from qa import qa_error
from qa_instance_utils import GetGenericAddParameters
from qa import qa_job_utils
from qa import qa_logging
from qa import qa_utils


MAX_JOB_SUBMISSION_DURATION = 15.0


class _JobQueueDriver(object):
  """This class handles polling of jobs and reacting on status changes.

  Jobs are added via the L{AddJob} method, and can have callback functions
  assigned to them. Those are called as soon as the job enters the appropriate
  state. Callback functions can add new jobs to the driver as needed.

  A call to L{WaitForCompletion} finally polls Ganeti until all jobs have
  succeeded.

  """

  _UNKNOWN_STATUS = "unknown"

  class _JobEntry(object):
    """Internal class representing a job entry.

    """
    def __init__(self, job_id, running_fn, success_fn):
      self.job_id = job_id
      self.running_fn = running_fn
      self.success_fn = success_fn

    def __str__(self):
      return str(self.job_id)

  def __init__(self):
    self._jobs = {}
    self._running_notified = set()
    self._jobs_per_status = {}
    self._lock = threading.RLock()

  def AddJob(self, job_id, running_fn=None, success_fn=None):
    """Add a job to the driver.

    @type job_id: of ints
    @param job_id: job id to add to the driver
    @type running_fn: function taking a L{_JobQueueDriver} and an int
    @param running_fn: function called once when a job changes to running state
                       (or success state, if the running state was too short)
    @type success_fn: function taking a L{_JobQueueDriver} and an int
    @param success_fn: function called for each successful job id

    """
    with self._lock:
      self._jobs[job_id] = _JobQueueDriver._JobEntry(job_id,
                                                     running_fn,
                                                     success_fn)
      # the status will be updated on the next call to _FetchJobStatuses
      self._jobs_per_status.setdefault(self._UNKNOWN_STATUS, []).append(job_id)

  def _FetchJobStatuses(self):
    """Retrieves status information of the given jobs.

    """
    job_statuses = qa_job_utils.GetJobStatuses(self._GetJobIds())

    new_statuses = {}
    for job_id, status in job_statuses.items():
      new_statuses.setdefault(status, []).append(self._jobs[int(job_id)])
    self._jobs_per_status = new_statuses

  def _GetJobIds(self):
    return list(self._jobs)

  def _GetJobsInStatuses(self, statuses):
    """Returns a list of L{_JobEntry} of all jobs in the given statuses.

    @type statuses: iterable of strings
    @param statuses: jobs in those statuses are returned
    @rtype: list of L{_JobEntry}
    @return: list of job entries in the requested statuses

    """
    ret = []
    for state in statuses:
      ret.extend(self._jobs_per_status.get(state, []))
    return ret

  def _UpdateJobStatuses(self):
    """Retrieves job statuses from the cluster and updates internal state.

    """
    self._FetchJobStatuses()
    error_jobs = self._GetJobsInStatuses([constants.JOB_STATUS_ERROR])
    if error_jobs:
      raise qa_error.Error(
        "Jobs %s are in error state!" % [job.job_id for job in error_jobs])

    for job in self._GetJobsInStatuses([constants.JOB_STATUS_RUNNING,
                                        constants.JOB_STATUS_SUCCESS]):
      if job.job_id not in self._running_notified:
        if job.running_fn is not None:
          job.running_fn(self, job.job_id)
        self._running_notified.add(job.job_id)

    for job in self._GetJobsInStatuses([constants.JOB_STATUS_SUCCESS]):
      if job.success_fn is not None:
        job.success_fn(self, job.job_id)

      # we're done with this job
      del self._jobs[job.job_id]

  def _HasPendingJobs(self):
    """Checks if there are still jobs pending.

    @rtype: bool
    @return: C{True} if there are still jobs which have not succeeded

    """
    with self._lock:
      self._UpdateJobStatuses()
      uncompleted_jobs = self._GetJobsInStatuses(
        constants.JOB_STATUS_ALL - constants.JOBS_FINALIZED)
      unknown_jobs = self._GetJobsInStatuses([self._UNKNOWN_STATUS])
      return len(uncompleted_jobs) > 0 or len(unknown_jobs) > 0

  def WaitForCompletion(self):
    """Wait for the completion of all registered jobs.

    """
    while self._HasPendingJobs():
      time.sleep(2)

    with self._lock:
      if self._jobs:
        raise qa_error.Error(
          "Jobs %s didn't finish in success state!" % self._GetJobIds())


def _AcquireAllInstances():
  """Generator for acquiring all instances in the QA config.

  """
  try:
    while True:
      instance = qa_config.AcquireInstance()
      yield instance
  except qa_error.OutOfInstancesError:
    pass


def _AcquireAllNodes():
  """Generator for acquiring all nodes in the QA config.

  """
  exclude = []
  try:
    while True:
      node = qa_config.AcquireNode(exclude=exclude)
      exclude.append(node)
      yield node
  except qa_error.OutOfNodesError:
    pass


def _ExecuteJobSubmittingCmd(cmd):
  """Executes a job submitting command and returns the resulting job ID.

  This will fail if submitting the job takes longer than
  L{MAX_JOB_SUBMISSION_DURATION}.

  @type cmd: list of string or string
  @param cmd: the job producing command to execute on the cluster
  @rtype: int
  @return: job-id

  """
  start = datetime.datetime.now()
  result = qa_job_utils.ExecuteJobProducingCommand(cmd)
  duration = qa_utils.TimedeltaToTotalSeconds(datetime.datetime.now() - start)
  if duration > MAX_JOB_SUBMISSION_DURATION:
    print(qa_logging.FormatWarning(
      "Executing '%s' took %f seconds, a maximum of %f was expected" %
      (cmd, duration, MAX_JOB_SUBMISSION_DURATION)))
  return result


def _SubmitInstanceCreationJob(instance, disk_template=None):
  """Submit an instance creation job.

  @type instance: L{qa_config._QaInstance}
  @param instance: instance to submit a create command for
  @type disk_template: string
  @param disk_template: disk template for the new instance or C{None} which
                        causes the default disk template to be used
  @rtype: int
  @return: job id of the submitted creation job

  """
  if disk_template is None:
    disk_template = qa_config.GetDefaultDiskTemplate()
  try:
    cmd = (["gnt-instance", "add", "--submit", "--opportunistic-locking",
            "--os-type=%s" % qa_config.get("os"),
            "--disk-template=%s" % disk_template] +
           GetGenericAddParameters(instance, disk_template))
    cmd.append(instance.name)

    instance.SetDiskTemplate(disk_template)

    return _ExecuteJobSubmittingCmd(cmd)
  except:
    instance.Release()
    raise


def _SubmitInstanceRemoveJob(instance):
  """Submit an instance remove job.

  @type instance: L{qa_config._QaInstance}
  @param instance: the instance to remove
  @rtype: int
  @return: job id of the submitted remove job

  """
  try:
    cmd = (["gnt-instance", "remove", "--submit", "-f"])
    cmd.append(instance.name)

    return _ExecuteJobSubmittingCmd(cmd)
  finally:
    instance.Release()


def _TestParallelInstanceCreationAndRemoval(max_instances=None,
                                            disk_template=None,
                                            custom_job_driver=None):
  """Tests parallel creation and immediate removal of instances.

  @type max_instances: int
  @param max_instances: maximum number of instances to create
  @type disk_template: string
  @param disk_template: disk template for the new instances or C{None} which
                        causes the default disk template to be used
  @type custom_job_driver: _JobQueueDriver
  @param custom_job_driver: a custom L{_JobQueueDriver} to use if not L{None}.
                            If one is specified, C{WaitForCompletion} is _not_
                            called on it.

  """
  job_driver = custom_job_driver or _JobQueueDriver()

  def _CreateSuccessFn(instance, job_driver, _):
    job_id = _SubmitInstanceRemoveJob(instance)
    job_driver.AddJob(job_id)

  instance_generator = _AcquireAllInstances()
  if max_instances is not None:
    instance_generator = itertools.islice(instance_generator, max_instances)

  for instance in instance_generator:
    job_id = _SubmitInstanceCreationJob(instance, disk_template=disk_template)
    job_driver.AddJob(
      job_id, success_fn=functools.partial(_CreateSuccessFn, instance))

  if custom_job_driver is None:
    job_driver.WaitForCompletion()


def TestParallelMaxInstanceCreationPerformance():
  """PERFORMANCE: Parallel instance creation (instance count = max).

  """
  _TestParallelInstanceCreationAndRemoval()


def TestParallelNodeCountInstanceCreationPerformance():
  """PERFORMANCE: Parallel instance creation (instance count = node count).

  """
  nodes = list(_AcquireAllNodes())
  _TestParallelInstanceCreationAndRemoval(max_instances=len(nodes))
  qa_config.ReleaseManyNodes(nodes)


def CreateAllInstances():
  """Create all instances configured in QA config in the cluster.

  @rtype: list of L{qa_config._QaInstance}
  @return: list of instances created in the cluster

  """
  job_driver = _JobQueueDriver()
  instances = list(_AcquireAllInstances())
  for instance in instances:
    job_id = _SubmitInstanceCreationJob(instance)
    job_driver.AddJob(job_id)

  job_driver.WaitForCompletion()
  return instances


def RemoveAllInstances(instances):
  """Removes all given instances from the cluster.

  @type instances: list of L{qa_config._QaInstance}
  @param instances:

  """
  job_driver = _JobQueueDriver()
  for instance in instances:
    job_id = _SubmitInstanceRemoveJob(instance)
    job_driver.AddJob(job_id)

  job_driver.WaitForCompletion()


def TestParallelModify(instances):
  """PERFORMANCE: Parallel instance modify.

  @type instances: list of L{qa_config._QaInstance}
  @param instances: list of instances to issue modify commands against

  """
  job_driver = _JobQueueDriver()
  # set min mem to same value as max mem
  new_min_mem = qa_config.get(constants.BE_MAXMEM)
  for instance in instances:
    cmd = (["gnt-instance", "modify", "--submit",
            "-B", "%s=%s" % (constants.BE_MINMEM, new_min_mem)])
    cmd.append(instance.name)
    job_driver.AddJob(_ExecuteJobSubmittingCmd(cmd))

    cmd = (["gnt-instance", "modify", "--submit",
            "-O", "fake_os_param=fake_value"])
    cmd.append(instance.name)
    job_driver.AddJob(_ExecuteJobSubmittingCmd(cmd))

    cmd = (["gnt-instance", "modify", "--submit",
            "-O", "fake_os_param=fake_value",
            "-B", "%s=%s" % (constants.BE_MINMEM, new_min_mem)])
    cmd.append(instance.name)
    job_driver.AddJob(_ExecuteJobSubmittingCmd(cmd))

  job_driver.WaitForCompletion()


def TestParallelInstanceOSOperations(instances):
  """PERFORMANCE: Parallel instance OS operations.

  Note: This test leaves the instances either running or stopped, there's no
  guarantee on the actual status.

  @type instances: list of L{qa_config._QaInstance}
  @param instances: list of instances to issue lifecycle commands against

  """
  OPS = ["start", "shutdown", "reboot", "reinstall"]
  job_driver = _JobQueueDriver()

  def _SubmitNextOperation(instance, start, idx, job_driver, _):
    if idx == len(OPS):
      return
    op_idx = (start + idx) % len(OPS)

    next_fn = functools.partial(_SubmitNextOperation, instance, start, idx + 1)

    if OPS[op_idx] == "reinstall" and \
        instance.disk_template == constants.DT_DISKLESS:
      # no reinstall possible with diskless instances
      next_fn(job_driver, None)
      return
    elif OPS[op_idx] == "reinstall":
      # the instance has to be shut down for reinstall to work
      shutdown_cmd = ["gnt-instance", "shutdown", "--submit", instance.name]
      cmd = ["gnt-instance", "reinstall", "--submit", "-f", instance.name]

      job_driver.AddJob(_ExecuteJobSubmittingCmd(shutdown_cmd),
                        running_fn=lambda _, __: job_driver.AddJob(
                          _ExecuteJobSubmittingCmd(cmd),
                          running_fn=next_fn))
    else:
      cmd = ["gnt-instance", OPS[op_idx], "--submit"]
      if OPS[op_idx] == "reinstall":
        cmd.append("-f")
      cmd.append(instance.name)

      job_id = _ExecuteJobSubmittingCmd(cmd)
      job_driver.AddJob(job_id, running_fn=next_fn)

  for start, instance in enumerate(instances):
    _SubmitNextOperation(instance, start % len(OPS), 0, job_driver, None)

  job_driver.WaitForCompletion()


def TestParallelInstanceQueries(instances):
  """PERFORMANCE: Parallel instance queries.

  @type instances: list of L{qa_config._QaInstance}
  @param instances: list of instances to issue queries against

  """
  threads = qa_job_utils.QAThreadGroup()
  for instance in instances:
    cmd = ["gnt-instance", "info", instance.name]
    info_thread = qa_job_utils.QAThread(qa_utils.AssertCommand, [cmd], {})
    threads.Start(info_thread)

    cmd = ["gnt-instance", "list"]
    list_thread = qa_job_utils.QAThread(qa_utils.AssertCommand, [cmd], {})
    threads.Start(list_thread)

  threads.JoinAndReraise()


def TestJobQueueSubmissionPerformance():
  """PERFORMANCE: Job queue submission performance.

  This test exercises the job queue and verifies that the job submission time
  does not increase as more jobs are added.

  """
  MAX_CLUSTER_INFO_SECONDS = 15.0
  job_driver = _JobQueueDriver()
  submission_durations = []

  def _VerifySubmissionDuration(duration_seconds):
    # only start to verify the submission duration once we got data from the
    # first 10 job submissions
    if len(submission_durations) >= 10:
      avg_duration = sum(submission_durations) / len(submission_durations)
      max_duration = avg_duration * 1.5
      if duration_seconds > max_duration:
        print(qa_logging.FormatWarning(
          "Submitting a delay job took %f seconds, max %f expected" %
          (duration_seconds, max_duration)))
    else:
      submission_durations.append(duration_seconds)

  def _SubmitDelayJob(count):
    for _ in range(count):
      cmd = ["gnt-debug", "delay", "--submit", "0.1"]

      start = datetime.datetime.now()
      job_id = _ExecuteJobSubmittingCmd(cmd)
      duration_seconds = \
        qa_utils.TimedeltaToTotalSeconds(datetime.datetime.now() - start)
      _VerifySubmissionDuration(duration_seconds)

      job_driver.AddJob(job_id)

  threads = qa_job_utils.QAThreadGroup()
  for _ in range(10):
    thread = qa_job_utils.QAThread(_SubmitDelayJob, [20], {})
    threads.Start(thread)

  threads.JoinAndReraise()

  qa_utils.AssertCommand(["gnt-cluster", "info"],
                         max_seconds=MAX_CLUSTER_INFO_SECONDS)

  job_driver.WaitForCompletion()


def TestParallelDRBDInstanceCreationPerformance():
  """PERFORMANCE: Parallel DRBD backed instance creation.

  """
  assert qa_config.IsTemplateSupported(constants.DT_DRBD8)

  nodes = list(_AcquireAllNodes())
  _TestParallelInstanceCreationAndRemoval(max_instances=len(nodes) * 2,
                                          disk_template=constants.DT_DRBD8)
  qa_config.ReleaseManyNodes(nodes)


def TestParallelPlainInstanceCreationPerformance():
  """PERFORMANCE: Parallel plain backed instance creation.

  """
  assert qa_config.IsTemplateSupported(constants.DT_PLAIN)

  nodes = list(_AcquireAllNodes())
  _TestParallelInstanceCreationAndRemoval(max_instances=len(nodes) * 2,
                                          disk_template=constants.DT_PLAIN)
  qa_config.ReleaseManyNodes(nodes)


def _TestInstanceOperationInParallelToInstanceCreation(*cmds):
  """Run the given test command in parallel to an instance creation.

  @type cmds: list of list of strings
  @param cmds: commands to execute in parallel to an instance creation. Each
               command in the list is executed once the previous job starts
               to run.

  """
  def _SubmitNextCommand(cmd_idx, job_driver, _):
    if cmd_idx >= len(cmds):
      return
    job_id = _ExecuteJobSubmittingCmd(cmds[cmd_idx])
    job_driver.AddJob(
      job_id, success_fn=functools.partial(_SubmitNextCommand, cmd_idx + 1))

  assert qa_config.IsTemplateSupported(constants.DT_DRBD8)
  assert len(cmds) > 0

  job_driver = _JobQueueDriver()
  _SubmitNextCommand(0, job_driver, None)

  _TestParallelInstanceCreationAndRemoval(max_instances=1,
                                          disk_template=constants.DT_DRBD8,
                                          custom_job_driver=job_driver)

  job_driver.WaitForCompletion()


def TestParallelInstanceFailover(instance):
  """PERFORMANCE: Instance failover with parallel instance creation.

  """
  _TestInstanceOperationInParallelToInstanceCreation(
    ["gnt-instance", "failover", "--submit", "-f", "--shutdown-timeout=0",
     instance.name])


def TestParallelInstanceMigration(instance):
  """PERFORMANCE: Instance migration with parallel instance creation.

  """
  _TestInstanceOperationInParallelToInstanceCreation(
    ["gnt-instance", "migrate", "--submit", "-f", instance.name])


def TestParallelInstanceReplaceDisks(instance):
  """PERFORMANCE: Instance replace-disks with parallel instance creation.

  """
  _TestInstanceOperationInParallelToInstanceCreation(
    ["gnt-instance", "replace-disks", "--submit", "--early-release", "-p",
     instance.name])


def TestParallelInstanceReboot(instance):
  """PERFORMANCE: Instance reboot with parallel instance creation.

  """
  _TestInstanceOperationInParallelToInstanceCreation(
    ["gnt-instance", "reboot", "--submit", instance.name])


def TestParallelInstanceReinstall(instance):
  """PERFORMANCE: Instance reinstall with parallel instance creation.

  """
  # instance reinstall requires the instance to be down
  qa_utils.AssertCommand(["gnt-instance", "stop", instance.name])

  _TestInstanceOperationInParallelToInstanceCreation(
    ["gnt-instance", "reinstall", "--submit", "-f", instance.name])

  qa_utils.AssertCommand(["gnt-instance", "start", instance.name])


def TestParallelInstanceRename(instance):
  """PERFORMANCE: Instance rename with parallel instance creation.

  """
  # instance rename requires the instance to be down
  qa_utils.AssertCommand(["gnt-instance", "stop", instance.name])

  new_instance = qa_config.AcquireInstance()
  try:
    _TestInstanceOperationInParallelToInstanceCreation(
      ["gnt-instance", "rename", "--submit", instance.name, new_instance.name],
      ["gnt-instance", "rename", "--submit", new_instance.name, instance.name])
  finally:
    new_instance.Release()

  qa_utils.AssertCommand(["gnt-instance", "start", instance.name])
