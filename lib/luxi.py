#
#

# Copyright (C) 2006, 2007, 2011, 2012, 2013, 2014 Google Inc.
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


"""Module for the LUXI protocol

This module implements the local unix socket protocol. You only need
this module and the opcodes module in the client program in order to
communicate with the master.

The module is also used by the master daemon.

"""

from ganeti import constants
from ganeti import pathutils
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
REQ_QUERY_FILTERS = constants.LUXI_REQ_QUERY_FILTERS
REQ_REPLACE_FILTER = constants.LUXI_REQ_REPLACE_FILTER
REQ_DELETE_FILTER = constants.LUXI_REQ_DELETE_FILTER
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
    super(Client, self).__init__(timeouts, transport)
    # Override the version of the protocol:
    self.version = constants.LUXI_VERSION
    # Store the socket address
    if address is None:
      address = pathutils.QUERY_SOCKET
    self.address = address
    self._InitTransport()

  def _GetAddress(self):
    return self.address

  def SetQueueDrainFlag(self, drain_flag):
    return self.CallMethod(REQ_SET_DRAIN_FLAG, (drain_flag, ))

  def SetWatcherPause(self, until):
    return self.CallMethod(REQ_SET_WATCHER_PAUSE, (until, ))

  def PickupJob(self, job):
    return self.CallMethod(REQ_PICKUP_JOB, (job,))

  def SubmitJob(self, ops):
    ops_state = [op.__getstate__()
                 if not isinstance(op, objects.ConfigObject)
                 else op.ToDict(_with_private=True)
                 for op in ops]
    return self.CallMethod(REQ_SUBMIT_JOB, (ops_state, ))

  def SubmitJobToDrainedQueue(self, ops):
    ops_state = [op.__getstate__() for op in ops]
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

  def CancelJob(self, job_id, kill=False):
    job_id = Client._PrepareJobId(REQ_CANCEL_JOB, job_id)
    return self.CallMethod(REQ_CANCEL_JOB, (job_id, kill))

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

  def QueryFilters(self, uuids, fields):
    return self.CallMethod(REQ_QUERY_FILTERS, (uuids, fields))

  def ReplaceFilter(self, uuid, priority, predicates, action, reason):
    return self.CallMethod(REQ_REPLACE_FILTER,
                           (uuid, priority, predicates, action, reason))

  def DeleteFilter(self, uuid):
    return self.CallMethod(REQ_DELETE_FILTER, (uuid, ))

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
