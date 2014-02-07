#
#

# Copyright (C) 2006, 2007, 2011, 2012, 2013, 2014 Google Inc.
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


"""Module for the LUXI protocol

This module implements the local unix socket protocol. You only need
this module and the opcodes module in the client program in order to
communicate with the master.

The module is also used by the master daemon.

"""

from ganeti import constants
from ganeti import objects
import ganeti.rpc.client as cl
from ganeti.rpc.errors import RequestError
from ganeti.rpc.transport import Transport

__all__ = [
  # classes:
  "Client"
  ]

REQ_SUBMIT_JOB = constants.LUXI_REQ_SUBMIT_JOB
REQ_SUBMIT_JOB_TO_DRAINED_QUEUE = constants.LUXI_REQ_SUBMIT_JOB_TO_DRAINED_QUEUE
REQ_SUBMIT_MANY_JOBS = constants.LUXI_REQ_SUBMIT_MANY_JOBS
REQ_PICKUP_JOB = constants.LUXI_REQ_PICKUP_JOB
REQ_WAIT_FOR_JOB_CHANGE = constants.LUXI_REQ_WAIT_FOR_JOB_CHANGE
REQ_CANCEL_JOB = constants.LUXI_REQ_CANCEL_JOB
REQ_ARCHIVE_JOB = constants.LUXI_REQ_ARCHIVE_JOB
REQ_CHANGE_JOB_PRIORITY = constants.LUXI_REQ_CHANGE_JOB_PRIORITY
REQ_AUTO_ARCHIVE_JOBS = constants.LUXI_REQ_AUTO_ARCHIVE_JOBS
REQ_QUERY = constants.LUXI_REQ_QUERY
REQ_QUERY_FIELDS = constants.LUXI_REQ_QUERY_FIELDS
REQ_QUERY_JOBS = constants.LUXI_REQ_QUERY_JOBS
REQ_QUERY_INSTANCES = constants.LUXI_REQ_QUERY_INSTANCES
REQ_QUERY_NODES = constants.LUXI_REQ_QUERY_NODES
REQ_QUERY_GROUPS = constants.LUXI_REQ_QUERY_GROUPS
REQ_QUERY_NETWORKS = constants.LUXI_REQ_QUERY_NETWORKS
REQ_QUERY_EXPORTS = constants.LUXI_REQ_QUERY_EXPORTS
REQ_QUERY_CONFIG_VALUES = constants.LUXI_REQ_QUERY_CONFIG_VALUES
REQ_QUERY_CLUSTER_INFO = constants.LUXI_REQ_QUERY_CLUSTER_INFO
REQ_QUERY_TAGS = constants.LUXI_REQ_QUERY_TAGS
REQ_SET_DRAIN_FLAG = constants.LUXI_REQ_SET_DRAIN_FLAG
REQ_SET_WATCHER_PAUSE = constants.LUXI_REQ_SET_WATCHER_PAUSE
REQ_ALL = constants.LUXI_REQ_ALL

DEF_RWTO = constants.LUXI_DEF_RWTO
WFJC_TIMEOUT = constants.LUXI_WFJC_TIMEOUT


class Client(cl.AbstractClient):
  """High-level client implementation.

  This uses a backing Transport-like class on top of which it
  implements data serialization/deserialization.

  """
  def __init__(self, address=None, timeouts=None, transport=Transport):
    """Constructor for the Client class.

    Arguments are the same as for L{AbstractClient}.

    """
    super(Client, self).__init__(address, timeouts, transport)
    # Override the version of the protocol:
    self.version = constants.LUXI_VERSION

  def SetQueueDrainFlag(self, drain_flag):
    return self.CallMethod(REQ_SET_DRAIN_FLAG, (drain_flag, ))

  def SetWatcherPause(self, until):
    return self.CallMethod(REQ_SET_WATCHER_PAUSE, (until, ))

  def PickupJob(self, job):
    return self.CallMethod(REQ_PICKUP_JOB, (job,))

  def SubmitJob(self, ops):
    ops_state = map(lambda op: op.__getstate__()
                               if not isinstance(op, objects.ConfigObject)
                               else op.ToDict(_with_private=True), ops)
    return self.CallMethod(REQ_SUBMIT_JOB, (ops_state, ))

  def SubmitJobToDrainedQueue(self, ops):
    ops_state = map(lambda op: op.__getstate__(), ops)
    return self.CallMethod(REQ_SUBMIT_JOB_TO_DRAINED_QUEUE, (ops_state, ))

  def SubmitManyJobs(self, jobs):
    jobs_state = []
    for ops in jobs:
      jobs_state.append([op.__getstate__() for op in ops])
    return self.CallMethod(REQ_SUBMIT_MANY_JOBS, (jobs_state, ))

  @staticmethod
  def _PrepareJobId(request_name, job_id):
    try:
      return int(job_id)
    except ValueError:
      raise RequestError("Invalid parameter passed to %s as job id: "
                         " expected integer, got value %s" %
                         (request_name, job_id))

  def CancelJob(self, job_id):
    job_id = Client._PrepareJobId(REQ_CANCEL_JOB, job_id)
    return self.CallMethod(REQ_CANCEL_JOB, (job_id, ))

  def ArchiveJob(self, job_id):
    job_id = Client._PrepareJobId(REQ_ARCHIVE_JOB, job_id)
    return self.CallMethod(REQ_ARCHIVE_JOB, (job_id, ))

  def ChangeJobPriority(self, job_id, priority):
    job_id = Client._PrepareJobId(REQ_CHANGE_JOB_PRIORITY, job_id)
    return self.CallMethod(REQ_CHANGE_JOB_PRIORITY, (job_id, priority))

  def AutoArchiveJobs(self, age):
    timeout = (DEF_RWTO - 1) / 2
    return self.CallMethod(REQ_AUTO_ARCHIVE_JOBS, (age, timeout))

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial,
                           timeout=WFJC_TIMEOUT):
    """Waits for changes on a job.

    @param job_id: Job ID
    @type fields: list
    @param fields: List of field names to be observed
    @type prev_job_info: None or list
    @param prev_job_info: Previously received job information
    @type prev_log_serial: None or int/long
    @param prev_log_serial: Highest log serial number previously received
    @type timeout: int/float
    @param timeout: Timeout in seconds (values larger than L{WFJC_TIMEOUT} will
                    be capped to that value)

    """
    assert timeout >= 0, "Timeout can not be negative"
    return self.CallMethod(REQ_WAIT_FOR_JOB_CHANGE,
                           (job_id, fields, prev_job_info,
                            prev_log_serial,
                            min(WFJC_TIMEOUT, timeout)))

  def WaitForJobChange(self, job_id, fields, prev_job_info, prev_log_serial):
    job_id = Client._PrepareJobId(REQ_WAIT_FOR_JOB_CHANGE, job_id)
    while True:
      result = self.WaitForJobChangeOnce(job_id, fields,
                                         prev_job_info, prev_log_serial)
      if result != constants.JOB_NOTCHANGED:
        break
    return result

  def Query(self, what, fields, qfilter):
    """Query for resources/items.

    @param what: One of L{constants.QR_VIA_LUXI}
    @type fields: List of strings
    @param fields: List of requested fields
    @type qfilter: None or list
    @param qfilter: Query filter
    @rtype: L{objects.QueryResponse}

    """
    result = self.CallMethod(REQ_QUERY, (what, fields, qfilter))
    return objects.QueryResponse.FromDict(result)

  def QueryFields(self, what, fields):
    """Query for available fields.

    @param what: One of L{constants.QR_VIA_LUXI}
    @type fields: None or list of strings
    @param fields: List of requested fields
    @rtype: L{objects.QueryFieldsResponse}

    """
    result = self.CallMethod(REQ_QUERY_FIELDS, (what, fields))
    return objects.QueryFieldsResponse.FromDict(result)

  def QueryJobs(self, job_ids, fields):
    return self.CallMethod(REQ_QUERY_JOBS, (job_ids, fields))

  def QueryInstances(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_INSTANCES, (names, fields, use_locking))

  def QueryNodes(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_NODES, (names, fields, use_locking))

  def QueryGroups(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_GROUPS, (names, fields, use_locking))

  def QueryNetworks(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_NETWORKS, (names, fields, use_locking))

  def QueryExports(self, nodes, use_locking):
    return self.CallMethod(REQ_QUERY_EXPORTS, (nodes, use_locking))

  def QueryClusterInfo(self):
    return self.CallMethod(REQ_QUERY_CLUSTER_INFO, ())

  def QueryConfigValues(self, fields):
    return self.CallMethod(REQ_QUERY_CONFIG_VALUES, (fields, ))

  def QueryTags(self, kind, name):
    return self.CallMethod(REQ_QUERY_TAGS, (kind, name))
