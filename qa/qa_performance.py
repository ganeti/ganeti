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


"""Performance testing QA tests.

"""

import time
import functools

from ganeti import constants

import qa_config
import qa_error
from qa_instance_utils import GetGenericAddParameters
import qa_job_utils


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
    self._jobs[job_id] = _JobQueueDriver._JobEntry(job_id,
                                                   running_fn,
                                                   success_fn)
    # the status will be updated on the next call to _FetchJobStatuses
    self._jobs_per_status.setdefault(self._UNKNOWN_STATUS, []).append(job_id)

  def _FetchJobStatuses(self):
    """Retrieves status information of the given jobs.

    @rtype: dict of string to list of L{_JobEntry)

    """
    cmd = (["gnt-job", "list", "--no-headers", "-o", "id,status"])
    cmd.extend(map(str, self._GetJobIds()))
    job_statuses = [line.split() for line in
                    qa_job_utils.GetOutputFromMaster(cmd).splitlines()]
    new_statuses = {}
    for job_id, status in job_statuses:
      new_statuses.setdefault(status, []).append(self._jobs[int(job_id)])
    self._jobs_per_status = new_statuses

  def _GetJobIds(self):
    return list(self._jobs.keys())

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
        "Jobs %s are in error state!" % error_jobs)

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


def _SubmitInstanceCreationJob(instance):
  """Submit an instance creation job.

  @type instance: L{qa_config._QaInstance}
  @param instance: instance to submit a create command for
  @rtype: int
  @return: job id of the submitted creation job

  """
  disk_template = qa_config.GetDefaultDiskTemplate()
  try:
    cmd = (["gnt-instance", "add", "--submit",
            "--os-type=%s" % qa_config.get("os"),
            "--disk-template=%s" % disk_template] +
           GetGenericAddParameters(instance, disk_template))
    cmd.append(instance.name)

    return qa_job_utils.ExecuteJobProducingCommand(cmd)
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

    return qa_job_utils.ExecuteJobProducingCommand(cmd)
  finally:
    instance.Release()


def TestParallelInstanceCreationPerformance():
  """PERFORMANCE: Parallel instance creation.

  """
  job_driver = _JobQueueDriver()

  def _CreateSuccessFn(instance, job_driver, _):
    job_id = _SubmitInstanceRemoveJob(instance)
    job_driver.AddJob(job_id)

  for instance in _AcquireAllInstances():
    job_id = _SubmitInstanceCreationJob(instance)
    job_driver.AddJob(job_id,
                      success_fn=functools.partial(_CreateSuccessFn, instance))

  job_driver.WaitForCompletion()
