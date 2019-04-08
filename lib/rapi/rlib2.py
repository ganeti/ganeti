#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Remote API resource implementations.

PUT or POST?
============

According to RFC2616 the main difference between PUT and POST is that
POST can create new resources but PUT can only create the resource the
URI was pointing to on the PUT request.

In the context of this module POST on ``/2/instances`` to change an existing
entity is legitimate, while PUT would not be. PUT creates a new entity (e.g. a
new instance) with a name specified in the request.

Quoting from RFC2616, section 9.6::

  The fundamental difference between the POST and PUT requests is reflected in
  the different meaning of the Request-URI. The URI in a POST request
  identifies the resource that will handle the enclosed entity. That resource
  might be a data-accepting process, a gateway to some other protocol, or a
  separate entity that accepts annotations. In contrast, the URI in a PUT
  request identifies the entity enclosed with the request -- the user agent
  knows what URI is intended and the server MUST NOT attempt to apply the
  request to some other resource. If the server desires that the request be
  applied to a different URI, it MUST send a 301 (Moved Permanently) response;
  the user agent MAY then make its own decision regarding whether or not to
  redirect the request.

So when adding new methods, if they are operating on the URI entity itself,
PUT should be prefered over POST.

"""

# pylint: disable=C0103

# C0103: Invalid name, since the R_* names are not conforming

import errno
import OpenSSL
import socket

from ganeti import opcodes
from ganeti import objects
from ganeti import http
from ganeti import constants
from ganeti import cli
from ganeti import rapi
from ganeti import ht
from ganeti import compat
from ganeti.rapi import baserlib


_COMMON_FIELDS = ["ctime", "mtime", "uuid", "serial_no", "tags"]
I_FIELDS = ["name", "admin_state", "os",
            "pnode", "snodes",
            "disk_template",
            "nic.ips", "nic.macs", "nic.modes", "nic.uuids", "nic.names",
            "nic.links", "nic.networks", "nic.networks.names", "nic.bridges",
            "network_port",
            "disk.sizes", "disk.spindles", "disk_usage", "disk.uuids",
            "disk.names",
            "beparams", "hvparams",
            "oper_state", "oper_ram", "oper_vcpus", "status",
            "custom_hvparams", "custom_beparams", "custom_nicparams",
            ] + _COMMON_FIELDS

N_FIELDS = ["name", "offline", "master_candidate", "drained",
            "dtotal", "dfree", "sptotal", "spfree",
            "mtotal", "mnode", "mfree",
            "pinst_cnt", "sinst_cnt",
            "ctotal", "cnos", "cnodes", "csockets",
            "pip", "sip", "role",
            "pinst_list", "sinst_list",
            "master_capable", "vm_capable",
            "ndparams",
            "group.uuid",
            ] + _COMMON_FIELDS

NET_FIELDS = ["name", "network", "gateway",
              "network6", "gateway6",
              "mac_prefix",
              "free_count", "reserved_count",
              "map", "group_list", "inst_list",
              "external_reservations",
              ] + _COMMON_FIELDS

G_FIELDS = [
  "alloc_policy",
  "name",
  "node_cnt",
  "node_list",
  "ipolicy",
  "custom_ipolicy",
  "diskparams",
  "custom_diskparams",
  "ndparams",
  "custom_ndparams",
  ] + _COMMON_FIELDS

FILTER_RULE_FIELDS = [
  "watermark",
  "priority",
  "predicates",
  "action",
  "reason_trail",
  "uuid",
  ]

J_FIELDS_BULK = [
  "id", "ops", "status", "summary",
  "opstatus",
  "received_ts", "start_ts", "end_ts",
  ]

J_FIELDS = J_FIELDS_BULK + [
  "oplog",
  "opresult",
  ]

_NR_DRAINED = "drained"
_NR_MASTER_CANDIDATE = "master-candidate"
_NR_MASTER = "master"
_NR_OFFLINE = "offline"
_NR_REGULAR = "regular"

_NR_MAP = {
  constants.NR_MASTER: _NR_MASTER,
  constants.NR_MCANDIDATE: _NR_MASTER_CANDIDATE,
  constants.NR_DRAINED: _NR_DRAINED,
  constants.NR_OFFLINE: _NR_OFFLINE,
  constants.NR_REGULAR: _NR_REGULAR,
  }

assert frozenset(_NR_MAP) == constants.NR_ALL

# Request data version field
_REQ_DATA_VERSION = "__version__"

# Feature string for instance creation request data version 1
_INST_CREATE_REQV1 = "instance-create-reqv1"

# Feature string for instance reinstall request version 1
_INST_REINSTALL_REQV1 = "instance-reinstall-reqv1"

# Feature string for node migration version 1
_NODE_MIGRATE_REQV1 = "node-migrate-reqv1"

# Feature string for node evacuation with LU-generated jobs
_NODE_EVAC_RES1 = "node-evac-res1"

ALL_FEATURES = compat.UniqueFrozenset([
  _INST_CREATE_REQV1,
  _INST_REINSTALL_REQV1,
  _NODE_MIGRATE_REQV1,
  _NODE_EVAC_RES1,
  ])

# Timeout for /2/jobs/[job_id]/wait. Gives job up to 10 seconds to change.
_WFJC_TIMEOUT = 10


# FIXME: For compatibility we update the beparams/memory field. Needs to be
#        removed in Ganeti 2.8
def _UpdateBeparams(inst):
  """Updates the beparams dict of inst to support the memory field.

  @param inst: Inst dict
  @return: Updated inst dict

  """
  beparams = inst["beparams"]
  beparams[constants.BE_MEMORY] = beparams[constants.BE_MAXMEM]

  return inst


def _CheckIfConnectionDropped(sock):
  """Utility function to monitor the state of an open connection.

  @param sock: Connection's open socket
  @return: True if the connection was remotely closed, otherwise False

  """
  try:
    result = sock.recv(0)
    if result == "":
      return True
  # The connection is still open
  except OpenSSL.SSL.WantReadError:
    return False
  # The connection has been terminated gracefully
  except OpenSSL.SSL.ZeroReturnError:
    return True
  # The connection was terminated
  except OpenSSL.SSL.SysCallError:
    return True
  # The usual EAGAIN is raised when the read would block, but only if SSL is
  # disabled (The SSL case is covered by WantReadError above).
  except socket.error as err:
    if getattr(err, 'errno') == errno.EAGAIN:
      return False
    else:
      raise
  return False


class R_root(baserlib.ResourceBase):
  """/ resource.

  """
  @staticmethod
  def GET():
    """Supported for legacy reasons.

    """
    return None


class R_2(R_root):
  """/2 resource.

  """


class R_version(baserlib.ResourceBase):
  """/version resource.

  This resource should be used to determine the remote API version and
  to adapt clients accordingly.

  """
  @staticmethod
  def GET():
    """Returns the remote API version.

    """
    return constants.RAPI_VERSION


class R_2_info(baserlib.OpcodeResource):
  """/2/info resource.

  """
  GET_OPCODE = opcodes.OpClusterQuery
  GET_ALIASES = {
    "volume_group_name": "vg_name",
    "drbd_usermode_helper": "drbd_helper",
    }

  def GET(self):
    """Returns cluster information.

    """
    client = self.GetClient()
    return client.QueryClusterInfo()


class R_2_features(baserlib.ResourceBase):
  """/2/features resource.

  """
  @staticmethod
  def GET():
    """Returns list of optional RAPI features implemented.

    """
    return list(ALL_FEATURES)


class R_2_os(baserlib.OpcodeResource):
  """/2/os resource.

  """
  GET_OPCODE = opcodes.OpOsDiagnose

  def GET(self):
    """Return a list of all OSes.

    Can return error 500 in case of a problem.

    Example: ["debian-etch"]

    """
    cl = self.GetClient()
    op = opcodes.OpOsDiagnose(output_fields=["name", "variants"], names=[])
    cancel_fn = (lambda: _CheckIfConnectionDropped(self._req.request_sock))
    job_id = self.SubmitJob([op], cl=cl)
    # we use custom feedback function, instead of print we log the status
    result = cli.PollJob(job_id, cl, feedback_fn=baserlib.FeedbackFn,
                         cancel_fn=cancel_fn)
    diagnose_data = result[0]

    if not isinstance(diagnose_data, list):
      raise http.HttpBadGateway(message="Can't get OS list")

    os_names = []
    for (name, variants) in diagnose_data:
      os_names.extend(cli.CalculateOSNames(name, variants))

    return os_names


class R_2_redist_config(baserlib.OpcodeResource):
  """/2/redistribute-config resource.

  """
  PUT_OPCODE = opcodes.OpClusterRedistConf


class R_2_cluster_modify(baserlib.OpcodeResource):
  """/2/modify resource.

  """
  PUT_OPCODE = opcodes.OpClusterSetParams
  PUT_FORBIDDEN = [
    "compression_tools",
    ]


def checkFilterParameters(data):
  """Checks and extracts filter rule parameters from a request body.

  @return: the checked parameters: (priority, predicates, action).

  """

  if not isinstance(data, dict):
    raise http.HttpBadRequest("Invalid body contents, not a dictionary")

  # Forbid unknown parameters
  allowed_params = set(["priority", "predicates", "action", "reason"])
  for param in data:
    if param not in allowed_params:
      raise http.HttpBadRequest("Invalid body parameters: filter rule doesn't"
                                " support the parameter '%s'" % param)

  priority = baserlib.CheckParameter(
    data, "priority", exptype=int, default=0)

  # We leave the deeper check into the predicates list to the server.
  predicates = baserlib.CheckParameter(
    data, "predicates", exptype=list, default=[])

  # The action can be a string or a list; we leave the check to the server.
  action = baserlib.CheckParameter(data, "action", default="CONTINUE")

  reason = baserlib.CheckParameter(data, "reason", exptype=list, default=[])

  return (priority, predicates, action, reason)


class R_2_filters(baserlib.ResourceBase):
  """/2/filters resource.

  """

  def GET(self):
    """Returns a list of all filter rules.

    @return: a dictionary with filter rule UUID and uri.

    """
    client = self.GetClient()

    if self.useBulk():
      bulkdata = client.QueryFilters(None, FILTER_RULE_FIELDS)
      return baserlib.MapBulkFields(bulkdata, FILTER_RULE_FIELDS)
    else:
      jobdata = map(compat.fst, client.QueryFilters(None, ["uuid"]))
      return baserlib.BuildUriList(jobdata, "/2/filters/%s",
                                   uri_fields=("uuid", "uri"))

  def POST(self):
    """Adds a filter rule.

    @return: the UUID of the newly created filter rule.

    """
    priority, predicates, action, reason = \
      checkFilterParameters(self.request_body)

    # ReplaceFilter(None, ...) inserts a new filter.
    return self.GetClient().ReplaceFilter(None, priority, predicates, action,
                                          reason)


class R_2_filters_uuid(baserlib.ResourceBase):
  """/2/filters/[filter_uuid] resource.

  """
  def GET(self):
    """Returns a filter rule.

    @return: a dictionary with job parameters.
        The result includes:
            - uuid: unique filter ID string
            - watermark: highest job ID ever used as a number
            - priority: filter priority as a non-negative number
            - predicates: filter predicates, each one being a list
              with the first element being the name of the predicate
              and the rest being parameters suitable for that predicate
            - action: effect of the filter as a string
            - reason_trail: reasons for the addition of this filter as a
              list of lists

    """
    uuid = self.items[0]

    result = baserlib.HandleItemQueryErrors(self.GetClient().QueryFilters,
                                            uuids=[uuid],
                                            fields=FILTER_RULE_FIELDS)

    return baserlib.MapFields(FILTER_RULE_FIELDS, result[0])

  def PUT(self):
    """Replaces an existing filter rule, or creates one if it doesn't
    exist already.

    @return: the UUID of the changed or created filter rule.

    """
    uuid = self.items[0]

    priority, predicates, action, reason = \
      checkFilterParameters(self.request_body)

    return self.GetClient().ReplaceFilter(uuid, priority, predicates, action,
                                          reason)

  def DELETE(self):
    """Deletes a filter rule.

    """
    uuid = self.items[0]
    return self.GetClient().DeleteFilter(uuid)


class R_2_jobs(baserlib.ResourceBase):
  """/2/jobs resource.

  """
  def GET(self):
    """Returns a dictionary of jobs.

    @return: a dictionary with jobs id and uri.

    """
    client = self.GetClient()

    if self.useBulk():
      bulkdata = client.QueryJobs(None, J_FIELDS_BULK)
      return baserlib.MapBulkFields(bulkdata, J_FIELDS_BULK)
    else:
      jobdata = map(compat.fst, client.QueryJobs(None, ["id"]))
      return baserlib.BuildUriList(jobdata, "/2/jobs/%s",
                                   uri_fields=("id", "uri"))


class R_2_jobs_id(baserlib.ResourceBase):
  """/2/jobs/[job_id] resource.

  """
  def GET(self):
    """Returns a job status.

    @return: a dictionary with job parameters.
        The result includes:
            - id: job ID as a number
            - status: current job status as a string
            - ops: involved OpCodes as a list of dictionaries for each
              opcodes in the job
            - opstatus: OpCodes status as a list
            - opresult: OpCodes results as a list of lists

    """
    job_id = self.items[0]
    result = self.GetClient().QueryJobs([job_id, ], J_FIELDS)[0]
    if result is None:
      raise http.HttpNotFound()
    return baserlib.MapFields(J_FIELDS, result)

  def DELETE(self):
    """Cancel not-yet-started job.

    """
    job_id = self.items[0]
    result = self.GetClient().CancelJob(job_id)
    return result


class R_2_jobs_id_wait(baserlib.ResourceBase):
  """/2/jobs/[job_id]/wait resource.

  """
  # WaitForJobChange provides access to sensitive information and blocks
  # machine resources (it's a blocking RAPI call), hence restricting access.
  GET_ACCESS = [rapi.RAPI_ACCESS_WRITE]

  def GET(self):
    """Waits for job changes.

    """
    job_id = self.items[0]

    fields = self.getBodyParameter("fields")
    prev_job_info = self.getBodyParameter("previous_job_info", None)
    prev_log_serial = self.getBodyParameter("previous_log_serial", None)

    if not isinstance(fields, list):
      raise http.HttpBadRequest("The 'fields' parameter should be a list")

    if not (prev_job_info is None or isinstance(prev_job_info, list)):
      raise http.HttpBadRequest("The 'previous_job_info' parameter should"
                                " be a list")

    if not (prev_log_serial is None or
            isinstance(prev_log_serial, int)):
      raise http.HttpBadRequest("The 'previous_log_serial' parameter should"
                                " be a number")

    client = self.GetClient()
    result = client.WaitForJobChangeOnce(job_id, fields,
                                         prev_job_info, prev_log_serial,
                                         timeout=_WFJC_TIMEOUT)
    if not result:
      raise http.HttpNotFound()

    if result == constants.JOB_NOTCHANGED:
      # No changes
      return None

    (job_info, log_entries) = result

    return {
      "job_info": job_info,
      "log_entries": log_entries,
      }


class R_2_nodes(baserlib.OpcodeResource):
  """/2/nodes resource.

  """

  def GET(self):
    """Returns a list of all nodes.

    """
    client = self.GetClient()

    if self.useBulk():
      bulkdata = client.QueryNodes([], N_FIELDS, False)
      return baserlib.MapBulkFields(bulkdata, N_FIELDS)
    else:
      nodesdata = client.QueryNodes([], ["name"], False)
      nodeslist = [row[0] for row in nodesdata]
      return baserlib.BuildUriList(nodeslist, "/2/nodes/%s",
                                   uri_fields=("id", "uri"))


class R_2_nodes_name(baserlib.OpcodeResource):
  """/2/nodes/[node_name] resource.

  """
  GET_ALIASES = {
    "sip": "secondary_ip",
    }

  def GET(self):
    """Send information about a node.

    """
    node_name = self.items[0]
    client = self.GetClient()

    result = baserlib.HandleItemQueryErrors(client.QueryNodes,
                                            names=[node_name], fields=N_FIELDS,
                                            use_locking=self.useLocking())

    return baserlib.MapFields(N_FIELDS, result[0])


class R_2_nodes_name_powercycle(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/powercycle resource.

  """
  POST_OPCODE = opcodes.OpNodePowercycle

  def GetPostOpInput(self):
    """Tries to powercycle a node.

    """
    return (self.request_body, {
      "node_name": self.items[0],
      "force": self.useForce(),
      })


class R_2_nodes_name_role(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/role resource.

  """
  PUT_OPCODE = opcodes.OpNodeSetParams

  def GET(self):
    """Returns the current node role.

    @return: Node role

    """
    node_name = self.items[0]
    client = self.GetClient()
    result = client.QueryNodes(names=[node_name], fields=["role"],
                               use_locking=self.useLocking())

    return _NR_MAP[result[0][0]]

  def GetPutOpInput(self):
    """Sets the node role.

    """
    baserlib.CheckType(self.request_body, str, "Body contents")

    role = self.request_body

    if role == _NR_REGULAR:
      candidate = False
      offline = False
      drained = False

    elif role == _NR_MASTER_CANDIDATE:
      candidate = True
      offline = drained = None

    elif role == _NR_DRAINED:
      drained = True
      candidate = offline = None

    elif role == _NR_OFFLINE:
      offline = True
      candidate = drained = None

    else:
      raise http.HttpBadRequest("Can't set '%s' role" % role)

    assert len(self.items) == 1

    return ({}, {
      "node_name": self.items[0],
      "master_candidate": candidate,
      "offline": offline,
      "drained": drained,
      "force": self.useForce(),
      "auto_promote": bool(self._checkIntVariable("auto-promote", default=0)),
      })


class R_2_nodes_name_evacuate(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/evacuate resource.

  """
  POST_OPCODE = opcodes.OpNodeEvacuate

  def GetPostOpInput(self):
    """Evacuate all instances off a node.

    """
    return (self.request_body, {
      "node_name": self.items[0],
      "dry_run": self.dryRun(),
      })


class R_2_nodes_name_migrate(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/migrate resource.

  """
  POST_OPCODE = opcodes.OpNodeMigrate

  def GetPostOpInput(self):
    """Migrate all primary instances from a node.

    """
    if self.queryargs:
      # Support old-style requests
      if "live" in self.queryargs and "mode" in self.queryargs:
        raise http.HttpBadRequest("Only one of 'live' and 'mode' should"
                                  " be passed")

      if "live" in self.queryargs:
        if self._checkIntVariable("live", default=1):
          mode = constants.HT_MIGRATION_LIVE
        else:
          mode = constants.HT_MIGRATION_NONLIVE
      else:
        mode = self._checkStringVariable("mode", default=None)

      data = {
        "mode": mode,
        }
    else:
      data = self.request_body

    return (data, {
      "node_name": self.items[0],
      })


class R_2_nodes_name_modify(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/modify resource.

  """
  POST_OPCODE = opcodes.OpNodeSetParams

  def GetPostOpInput(self):
    """Changes parameters of a node.

    """
    assert len(self.items) == 1

    return (self.request_body, {
      "node_name": self.items[0],
      })


class R_2_nodes_name_storage(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/storage resource.

  """
  # LUNodeQueryStorage acquires locks, hence restricting access to GET
  GET_ACCESS = [rapi.RAPI_ACCESS_WRITE]
  GET_OPCODE = opcodes.OpNodeQueryStorage

  def GetGetOpInput(self):
    """List storage available on a node.

    """
    storage_type = self._checkStringVariable("storage_type", None)
    output_fields = self._checkStringVariable("output_fields", None)

    if not output_fields:
      raise http.HttpBadRequest("Missing the required 'output_fields'"
                                " parameter")

    return ({}, {
      "nodes": [self.items[0]],
      "storage_type": storage_type,
      "output_fields": output_fields.split(","),
      })


class R_2_nodes_name_storage_modify(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/storage/modify resource.

  """
  PUT_OPCODE = opcodes.OpNodeModifyStorage

  def GetPutOpInput(self):
    """Modifies a storage volume on a node.

    """
    storage_type = self._checkStringVariable("storage_type", None)
    name = self._checkStringVariable("name", None)

    if not name:
      raise http.HttpBadRequest("Missing the required 'name'"
                                " parameter")

    changes = {}

    if "allocatable" in self.queryargs:
      changes[constants.SF_ALLOCATABLE] = \
        bool(self._checkIntVariable("allocatable", default=1))

    return ({}, {
      "node_name": self.items[0],
      "storage_type": storage_type,
      "name": name,
      "changes": changes,
      })


class R_2_nodes_name_storage_repair(baserlib.OpcodeResource):
  """/2/nodes/[node_name]/storage/repair resource.

  """
  PUT_OPCODE = opcodes.OpRepairNodeStorage

  def GetPutOpInput(self):
    """Repairs a storage volume on a node.

    """
    storage_type = self._checkStringVariable("storage_type", None)
    name = self._checkStringVariable("name", None)
    if not name:
      raise http.HttpBadRequest("Missing the required 'name'"
                                " parameter")

    return ({}, {
      "node_name": self.items[0],
      "storage_type": storage_type,
      "name": name,
      })


class R_2_networks(baserlib.OpcodeResource):
  """/2/networks resource.

  """
  POST_OPCODE = opcodes.OpNetworkAdd
  POST_RENAME = {
    "name": "network_name",
    }

  def GetPostOpInput(self):
    """Create a network.

    """
    assert not self.items
    return (self.request_body, {
      "dry_run": self.dryRun(),
      })

  def GET(self):
    """Returns a list of all networks.

    """
    client = self.GetClient()

    if self.useBulk():
      bulkdata = client.QueryNetworks([], NET_FIELDS, False)
      return baserlib.MapBulkFields(bulkdata, NET_FIELDS)
    else:
      data = client.QueryNetworks([], ["name"], False)
      networknames = [row[0] for row in data]
      return baserlib.BuildUriList(networknames, "/2/networks/%s",
                                   uri_fields=("name", "uri"))


class R_2_networks_name(baserlib.OpcodeResource):
  """/2/networks/[network_name] resource.

  """
  DELETE_OPCODE = opcodes.OpNetworkRemove

  def GET(self):
    """Send information about a network.

    """
    network_name = self.items[0]
    client = self.GetClient()

    result = baserlib.HandleItemQueryErrors(client.QueryNetworks,
                                            names=[network_name],
                                            fields=NET_FIELDS,
                                            use_locking=self.useLocking())

    return baserlib.MapFields(NET_FIELDS, result[0])

  def GetDeleteOpInput(self):
    """Delete a network.

    """
    assert len(self.items) == 1
    return (self.request_body, {
      "network_name": self.items[0],
      "dry_run": self.dryRun(),
      })


class R_2_networks_name_connect(baserlib.OpcodeResource):
  """/2/networks/[network_name]/connect resource.

  """
  PUT_OPCODE = opcodes.OpNetworkConnect

  def GetPutOpInput(self):
    """Changes some parameters of node group.

    """
    assert self.items
    return (self.request_body, {
      "network_name": self.items[0],
      "dry_run": self.dryRun(),
      })


class R_2_networks_name_disconnect(baserlib.OpcodeResource):
  """/2/networks/[network_name]/disconnect resource.

  """
  PUT_OPCODE = opcodes.OpNetworkDisconnect

  def GetPutOpInput(self):
    """Changes some parameters of node group.

    """
    assert self.items
    return (self.request_body, {
      "network_name": self.items[0],
      "dry_run": self.dryRun(),
      })


class R_2_networks_name_modify(baserlib.OpcodeResource):
  """/2/networks/[network_name]/modify resource.

  """
  PUT_OPCODE = opcodes.OpNetworkSetParams

  def GetPutOpInput(self):
    """Changes some parameters of network.

    """
    assert self.items
    return (self.request_body, {
      "network_name": self.items[0],
      })


class R_2_groups(baserlib.OpcodeResource):
  """/2/groups resource.

  """
  POST_OPCODE = opcodes.OpGroupAdd
  POST_RENAME = {
    "name": "group_name",
    }

  def GetPostOpInput(self):
    """Create a node group.


    """
    assert not self.items
    return (self.request_body, {
      "dry_run": self.dryRun(),
      })

  def GET(self):
    """Returns a list of all node groups.

    """
    client = self.GetClient()

    if self.useBulk():
      bulkdata = client.QueryGroups([], G_FIELDS, False)
      return baserlib.MapBulkFields(bulkdata, G_FIELDS)
    else:
      data = client.QueryGroups([], ["name"], False)
      groupnames = [row[0] for row in data]
      return baserlib.BuildUriList(groupnames, "/2/groups/%s",
                                   uri_fields=("name", "uri"))


class R_2_groups_name(baserlib.OpcodeResource):
  """/2/groups/[group_name] resource.

  """
  DELETE_OPCODE = opcodes.OpGroupRemove

  def GET(self):
    """Send information about a node group.

    """
    group_name = self.items[0]
    client = self.GetClient()

    result = baserlib.HandleItemQueryErrors(client.QueryGroups,
                                            names=[group_name], fields=G_FIELDS,
                                            use_locking=self.useLocking())

    return baserlib.MapFields(G_FIELDS, result[0])

  def GetDeleteOpInput(self):
    """Delete a node group.

    """
    assert len(self.items) == 1
    return ({}, {
      "group_name": self.items[0],
      "dry_run": self.dryRun(),
      })


class R_2_groups_name_modify(baserlib.OpcodeResource):
  """/2/groups/[group_name]/modify resource.

  """
  PUT_OPCODE = opcodes.OpGroupSetParams
  PUT_RENAME = {
    "custom_ndparams": "ndparams",
    "custom_ipolicy": "ipolicy",
    "custom_diskparams": "diskparams",
    }

  def GetPutOpInput(self):
    """Changes some parameters of node group.

    """
    assert self.items
    return (self.request_body, {
      "group_name": self.items[0],
      })


class R_2_groups_name_rename(baserlib.OpcodeResource):
  """/2/groups/[group_name]/rename resource.

  """
  PUT_OPCODE = opcodes.OpGroupRename

  def GetPutOpInput(self):
    """Changes the name of a node group.

    """
    assert len(self.items) == 1
    return (self.request_body, {
      "group_name": self.items[0],
      "dry_run": self.dryRun(),
      })


class R_2_groups_name_assign_nodes(baserlib.OpcodeResource):
  """/2/groups/[group_name]/assign-nodes resource.

  """
  PUT_OPCODE = opcodes.OpGroupAssignNodes

  def GetPutOpInput(self):
    """Assigns nodes to a group.

    """
    assert len(self.items) == 1
    return (self.request_body, {
      "group_name": self.items[0],
      "dry_run": self.dryRun(),
      "force": self.useForce(),
      })


def _ConvertUsbDevices(data):
  """Convert in place the usb_devices string to the proper format.

  In Ganeti 2.8.4 the separator for the usb_devices hvparam was changed from
  comma to space because commas cannot be accepted on the command line
  (they already act as the separator between different hvparams). RAPI
  should be able to accept commas for backwards compatibility, but we want
  it to also accept the new space separator. Therefore, we convert
  spaces into commas here and keep the old parsing logic elsewhere.

  """
  try:
    hvparams = data["hvparams"]
    usb_devices = hvparams[constants.HV_USB_DEVICES]
    hvparams[constants.HV_USB_DEVICES] = usb_devices.replace(" ", ",")
    data["hvparams"] = hvparams
  except KeyError:
    #No usb_devices, no modification required
    pass


class R_2_instances(baserlib.OpcodeResource):
  """/2/instances resource.

  """
  POST_OPCODE = opcodes.OpInstanceCreate
  POST_RENAME = {
    "os": "os_type",
    "name": "instance_name",
    }

  def GET(self):
    """Returns a list of all available instances.

    """
    client = self.GetClient()

    use_locking = self.useLocking()
    if self.useBulk():
      bulkdata = client.QueryInstances([], I_FIELDS, use_locking)
      return map(_UpdateBeparams, baserlib.MapBulkFields(bulkdata, I_FIELDS))
    else:
      instancesdata = client.QueryInstances([], ["name"], use_locking)
      instanceslist = [row[0] for row in instancesdata]
      return baserlib.BuildUriList(instanceslist, "/2/instances/%s",
                                   uri_fields=("id", "uri"))

  def GetPostOpInput(self):
    """Create an instance.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")

    # Default to request data version 0
    data_version = self.getBodyParameter(_REQ_DATA_VERSION, 0)

    if data_version == 0:
      raise http.HttpBadRequest("Instance creation request version 0 is no"
                                " longer supported")
    elif data_version != 1:
      raise http.HttpBadRequest("Unsupported request data version %s" %
                                data_version)

    data = self.request_body.copy()
    # Remove "__version__"
    data.pop(_REQ_DATA_VERSION, None)

    _ConvertUsbDevices(data)

    return (data, {
      "dry_run": self.dryRun(),
      })


class R_2_instances_multi_alloc(baserlib.OpcodeResource):
  """/2/instances-multi-alloc resource.

  """
  POST_OPCODE = opcodes.OpInstanceMultiAlloc

  def GetPostOpInput(self):
    """Try to allocate multiple instances.

    @return: A dict with submitted jobs, allocatable instances and failed
             allocations

    """
    if "instances" not in self.request_body:
      raise http.HttpBadRequest("Request is missing required 'instances' field"
                                " in body")

    # Unlike most other RAPI calls, this one is composed of individual opcodes,
    # and we have to do the filling ourselves
    OPCODE_RENAME = {
      "os": "os_type",
      "name": "instance_name",
    }

    body = objects.FillDict(self.request_body, {
      "instances": [
        baserlib.FillOpcode(opcodes.OpInstanceCreate, inst, {},
                            rename=OPCODE_RENAME)
        for inst in self.request_body["instances"]
        ],
      })

    return (body, {
      "dry_run": self.dryRun(),
      })


class R_2_instances_name(baserlib.OpcodeResource):
  """/2/instances/[instance_name] resource.

  """
  DELETE_OPCODE = opcodes.OpInstanceRemove

  def GET(self):
    """Send information about an instance.

    """
    client = self.GetClient()
    instance_name = self.items[0]

    result = baserlib.HandleItemQueryErrors(client.QueryInstances,
                                            names=[instance_name],
                                            fields=I_FIELDS,
                                            use_locking=self.useLocking())

    return _UpdateBeparams(baserlib.MapFields(I_FIELDS, result[0]))

  def GetDeleteOpInput(self):
    """Delete an instance.

    """
    assert len(self.items) == 1
    return (self.request_body, {
      "instance_name": self.items[0],
      "ignore_failures": False,
      "dry_run": self.dryRun(),
      })


class R_2_instances_name_info(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/info resource.

  """
  GET_OPCODE = opcodes.OpInstanceQueryData

  def GetGetOpInput(self):
    """Request detailed instance information.

    """
    assert len(self.items) == 1
    return ({}, {
      "instances": [self.items[0]],
      "static": bool(self._checkIntVariable("static", default=0)),
      })


class R_2_instances_name_reboot(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/reboot resource.

  Implements an instance reboot.

  """
  POST_OPCODE = opcodes.OpInstanceReboot

  def GetPostOpInput(self):
    """Reboot an instance.

    The URI takes type=[hard|soft|full] and
    ignore_secondaries=[False|True] parameters.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      "reboot_type":
        self.queryargs.get("type", [constants.INSTANCE_REBOOT_HARD])[0],
      "ignore_secondaries": bool(self._checkIntVariable("ignore_secondaries")),
      "dry_run": self.dryRun(),
      })


class R_2_instances_name_startup(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/startup resource.

  Implements an instance startup.

  """
  PUT_OPCODE = opcodes.OpInstanceStartup

  def GetPutOpInput(self):
    """Startup an instance.

    The URI takes force=[False|True] parameter to start the instance
    if even if secondary disks are failing.

    """
    return ({}, {
      "instance_name": self.items[0],
      "force": self.useForce(),
      "dry_run": self.dryRun(),
      "no_remember": bool(self._checkIntVariable("no_remember")),
      })


class R_2_instances_name_shutdown(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/shutdown resource.

  Implements an instance shutdown.

  """
  PUT_OPCODE = opcodes.OpInstanceShutdown

  def GetPutOpInput(self):
    """Shutdown an instance.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      "no_remember": bool(self._checkIntVariable("no_remember")),
      "dry_run": self.dryRun(),
      })


def _ParseInstanceReinstallRequest(name, data):
  """Parses a request for reinstalling an instance.

  """
  if not isinstance(data, dict):
    raise http.HttpBadRequest("Invalid body contents, not a dictionary")

  ostype = baserlib.CheckParameter(data, "os", default=None)
  start = baserlib.CheckParameter(data, "start", exptype=bool,
                                  default=True)
  osparams = baserlib.CheckParameter(data, "osparams", default=None)

  ops = [
    opcodes.OpInstanceShutdown(instance_name=name),
    opcodes.OpInstanceReinstall(instance_name=name, os_type=ostype,
                                osparams=osparams),
    ]

  if start:
    ops.append(opcodes.OpInstanceStartup(instance_name=name, force=False))

  return ops


class R_2_instances_name_reinstall(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/reinstall resource.

  Implements an instance reinstall.

  """
  POST_OPCODE = opcodes.OpInstanceReinstall

  def POST(self):
    """Reinstall an instance.

    The URI takes os=name and nostartup=[0|1] optional
    parameters. By default, the instance will be started
    automatically.

    """
    if self.request_body:
      if self.queryargs:
        raise http.HttpBadRequest("Can't combine query and body parameters")

      body = self.request_body
    elif self.queryargs:
      # Legacy interface, do not modify/extend
      body = {
        "os": self._checkStringVariable("os"),
        "start": not self._checkIntVariable("nostartup"),
        }
    else:
      body = {}

    ops = _ParseInstanceReinstallRequest(self.items[0], body)

    return self.SubmitJob(ops)


class R_2_instances_name_replace_disks(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/replace-disks resource.

  """
  POST_OPCODE = opcodes.OpInstanceReplaceDisks

  def GetPostOpInput(self):
    """Replaces disks on an instance.

    """
    static = {
      "instance_name": self.items[0],
      }

    if self.request_body:
      data = self.request_body
    elif self.queryargs:
      # Legacy interface, do not modify/extend
      data = {
        "remote_node": self._checkStringVariable("remote_node", default=None),
        "mode": self._checkStringVariable("mode", default=None),
        "disks": self._checkStringVariable("disks", default=None),
        "iallocator": self._checkStringVariable("iallocator", default=None),
        }
    else:
      data = {}

    # Parse disks
    try:
      raw_disks = data.pop("disks")
    except KeyError:
      pass
    else:
      if raw_disks:
        if ht.TListOf(ht.TInt)(raw_disks): # pylint: disable=E1102
          data["disks"] = raw_disks
        else:
          # Backwards compatibility for strings of the format "1, 2, 3"
          try:
            data["disks"] = [int(part) for part in raw_disks.split(",")]
          except (TypeError, ValueError) as err:
            raise http.HttpBadRequest("Invalid disk index passed: %s" % err)

    return (data, static)


class R_2_instances_name_activate_disks(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/activate-disks resource.

  """
  PUT_OPCODE = opcodes.OpInstanceActivateDisks

  def GetPutOpInput(self):
    """Activate disks for an instance.

    The URI might contain ignore_size to ignore current recorded size.

    """
    return ({}, {
      "instance_name": self.items[0],
      "ignore_size": bool(self._checkIntVariable("ignore_size")),
      })


class R_2_instances_name_deactivate_disks(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/deactivate-disks resource.

  """
  PUT_OPCODE = opcodes.OpInstanceDeactivateDisks

  def GetPutOpInput(self):
    """Deactivate disks for an instance.

    """
    return ({}, {
      "instance_name": self.items[0],
      "force": self.useForce(),
      })


class R_2_instances_name_recreate_disks(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/recreate-disks resource.

  """
  POST_OPCODE = opcodes.OpInstanceRecreateDisks

  def GetPostOpInput(self):
    """Recreate disks for an instance.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      })


class R_2_instances_name_prepare_export(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/prepare-export resource.

  """
  PUT_OPCODE = opcodes.OpBackupPrepare

  def GetPutOpInput(self):
    """Prepares an export for an instance.

    """
    return ({}, {
      "instance_name": self.items[0],
      "mode": self._checkStringVariable("mode"),
      })


class R_2_instances_name_export(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/export resource.

  """
  PUT_OPCODE = opcodes.OpBackupExport
  PUT_RENAME = {
    "destination": "target_node",
    }

  def GetPutOpInput(self):
    """Exports an instance.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      })


class R_2_instances_name_migrate(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/migrate resource.

  """
  PUT_OPCODE = opcodes.OpInstanceMigrate

  def GetPutOpInput(self):
    """Migrates an instance.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      })


class R_2_instances_name_failover(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/failover resource.

  """
  PUT_OPCODE = opcodes.OpInstanceFailover

  def GetPutOpInput(self):
    """Does a failover of an instance.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      })


class R_2_instances_name_rename(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/rename resource.

  """
  PUT_OPCODE = opcodes.OpInstanceRename

  def GetPutOpInput(self):
    """Changes the name of an instance.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      })


class R_2_instances_name_modify(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/modify resource.

  """
  PUT_OPCODE = opcodes.OpInstanceSetParams
  PUT_RENAME = {
    "custom_beparams": "beparams",
    "custom_hvparams": "hvparams",
    }

  def GetPutOpInput(self):
    """Changes parameters of an instance.

    """
    data = self.request_body.copy()
    _ConvertUsbDevices(data)

    return (data, {
      "instance_name": self.items[0],
      })


class R_2_instances_name_disk_grow(baserlib.OpcodeResource):
  """/2/instances/[instance_name]/disk/[disk_index]/grow resource.

  """
  POST_OPCODE = opcodes.OpInstanceGrowDisk

  def GetPostOpInput(self):
    """Increases the size of an instance disk.

    """
    return (self.request_body, {
      "instance_name": self.items[0],
      "disk": int(self.items[1]),
      })


class R_2_instances_name_console(baserlib.ResourceBase):
  """/2/instances/[instance_name]/console resource.

  """
  GET_ACCESS = [rapi.RAPI_ACCESS_WRITE, rapi.RAPI_ACCESS_READ]
  GET_OPCODE = opcodes.OpInstanceConsole

  def GET(self):
    """Request information for connecting to instance's console.

    @return: Serialized instance console description, see
             L{objects.InstanceConsole}

    """
    instance_name = self.items[0]
    client = self.GetClient()

    (console, oper_state) = \
      client.QueryInstances([instance_name], ["console", "oper_state"],
                            False)[0]

    if not oper_state:
      raise http.HttpServiceUnavailable("Instance console unavailable")

    assert isinstance(console, dict)
    return console


def _GetQueryFields(args):
  """Tries to extract C{fields} query parameter.

  @type args: dictionary
  @rtype: list of string
  @raise http.HttpBadRequest: When parameter can't be found

  """
  try:
    fields = args["fields"]
  except KeyError:
    raise http.HttpBadRequest("Missing 'fields' query argument")

  return _SplitQueryFields(fields[0])


def _SplitQueryFields(fields):
  """Splits fields as given for a query request.

  @type fields: string
  @rtype: list of string

  """
  return [i.strip() for i in fields.split(",")]


class R_2_query(baserlib.ResourceBase):
  """/2/query/[resource] resource.

  """
  # Results might contain sensitive information
  GET_ACCESS = [rapi.RAPI_ACCESS_WRITE, rapi.RAPI_ACCESS_READ]
  PUT_ACCESS = GET_ACCESS
  GET_OPCODE = opcodes.OpQuery
  PUT_OPCODE = opcodes.OpQuery

  def _Query(self, fields, qfilter):
    client = self.GetClient()
    return client.Query(self.items[0], fields, qfilter).ToDict()

  def GET(self):
    """Returns resource information.

    @return: Query result, see L{objects.QueryResponse}

    """
    return self._Query(_GetQueryFields(self.queryargs), None)

  def PUT(self):
    """Submits job querying for resources.

    @return: Query result, see L{objects.QueryResponse}

    """
    body = self.request_body

    baserlib.CheckType(body, dict, "Body contents")

    try:
      fields = body["fields"]
    except KeyError:
      fields = _GetQueryFields(self.queryargs)

    qfilter = body.get("qfilter", None)
    # TODO: remove this after 2.7
    if qfilter is None:
      qfilter = body.get("filter", None)

    return self._Query(fields, qfilter)


class R_2_query_fields(baserlib.ResourceBase):
  """/2/query/[resource]/fields resource.

  """
  GET_OPCODE = opcodes.OpQueryFields

  def GET(self):
    """Retrieves list of available fields for a resource.

    @return: List of serialized L{objects.QueryFieldDefinition}

    """
    try:
      raw_fields = self.queryargs["fields"]
    except KeyError:
      fields = None
    else:
      fields = _SplitQueryFields(raw_fields[0])

    return self.GetClient().QueryFields(self.items[0], fields).ToDict()


class _R_Tags(baserlib.OpcodeResource):
  """Quasiclass for tagging resources.

  Manages tags. When inheriting this class you must define the
  TAG_LEVEL for it.

  """
  TAG_LEVEL = None
  GET_OPCODE = opcodes.OpTagsGet
  PUT_OPCODE = opcodes.OpTagsSet
  DELETE_OPCODE = opcodes.OpTagsDel

  def __init__(self, items, queryargs, req, **kwargs):
    """A tag resource constructor.

    We have to override the default to sort out cluster naming case.

    """
    baserlib.OpcodeResource.__init__(self, items, queryargs, req, **kwargs)

    if self.TAG_LEVEL == constants.TAG_CLUSTER:
      self.name = None
    else:
      self.name = items[0]

  def GET(self):
    """Returns a list of tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    kind = self.TAG_LEVEL

    if kind in constants.VALID_TAG_TYPES:
      cl = self.GetClient()
      if kind == constants.TAG_CLUSTER:
        if self.name:
          raise http.HttpBadRequest("Can't specify a name"
                                    " for cluster tag request")
        tags = list(cl.QueryTags(kind, ""))
      else:
        if not self.name:
          raise http.HttpBadRequest("Missing name on tag request")
        tags = list(cl.QueryTags(kind, self.name))

    else:
      raise http.HttpBadRequest("Unhandled tag type!")

    return list(tags)

  def GetPutOpInput(self):
    """Add a set of tags.

    The request as a list of strings should be PUT to this URI. And
    you'll have back a job id.

    """
    return ({}, {
      "kind": self.TAG_LEVEL,
      "name": self.name,
      "tags": self.queryargs.get("tag", []),
      "dry_run": self.dryRun(),
      })

  def GetDeleteOpInput(self):
    """Delete a tag.

    In order to delete a set of tags, the DELETE
    request should be addressed to URI like:
    /tags?tag=[tag]&tag=[tag]

    """
    # Re-use code
    return self.GetPutOpInput()


class R_2_instances_name_tags(_R_Tags):
  """ /2/instances/[instance_name]/tags resource.

  Manages per-instance tags.

  """
  TAG_LEVEL = constants.TAG_INSTANCE


class R_2_nodes_name_tags(_R_Tags):
  """ /2/nodes/[node_name]/tags resource.

  Manages per-node tags.

  """
  TAG_LEVEL = constants.TAG_NODE


class R_2_groups_name_tags(_R_Tags):
  """ /2/groups/[group_name]/tags resource.

  Manages per-nodegroup tags.

  """
  TAG_LEVEL = constants.TAG_NODEGROUP


class R_2_networks_name_tags(_R_Tags):
  """ /2/networks/[network_name]/tags resource.

  Manages per-network tags.

  """
  TAG_LEVEL = constants.TAG_NETWORK


class R_2_tags(_R_Tags):
  """ /2/tags resource.

  Manages cluster tags.

  """
  TAG_LEVEL = constants.TAG_CLUSTER
