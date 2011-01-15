#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""Remote API version 2 baserlib.library.

  PUT or POST?
  ============

  According to RFC2616 the main difference between PUT and POST is that
  POST can create new resources but PUT can only create the resource the
  URI was pointing to on the PUT request.

  To be in context of this module for instance creation POST on
  /2/instances is legitim while PUT would be not, due to it does create a
  new entity and not just replace /2/instances with it.

  So when adding new methods, if they are operating on the URI entity itself,
  PUT should be prefered over POST.

"""

# pylint: disable-msg=C0103

# C0103: Invalid name, since the R_* names are not conforming

from ganeti import opcodes
from ganeti import http
from ganeti import constants
from ganeti import cli
from ganeti import utils
from ganeti import rapi
from ganeti.rapi import baserlib


_COMMON_FIELDS = ["ctime", "mtime", "uuid", "serial_no", "tags"]
I_FIELDS = ["name", "admin_state", "os",
            "pnode", "snodes",
            "disk_template",
            "nic.ips", "nic.macs", "nic.modes", "nic.links", "nic.bridges",
            "network_port",
            "disk.sizes", "disk_usage",
            "beparams", "hvparams",
            "oper_state", "oper_ram", "oper_vcpus", "status",
            "custom_hvparams", "custom_beparams", "custom_nicparams",
            ] + _COMMON_FIELDS

N_FIELDS = ["name", "offline", "master_candidate", "drained",
            "dtotal", "dfree",
            "mtotal", "mnode", "mfree",
            "pinst_cnt", "sinst_cnt",
            "ctotal", "cnodes", "csockets",
            "pip", "sip", "role",
            "pinst_list", "sinst_list",
            "master_capable", "vm_capable",
            "group.uuid",
            ] + _COMMON_FIELDS

G_FIELDS = ["name", "uuid",
            "alloc_policy",
            "node_cnt", "node_list",
            "ctime", "mtime", "serial_no",
            ]  # "tags" is missing to be able to use _COMMON_FIELDS here.

_NR_DRAINED = "drained"
_NR_MASTER_CANDIATE = "master-candidate"
_NR_MASTER = "master"
_NR_OFFLINE = "offline"
_NR_REGULAR = "regular"

_NR_MAP = {
  "M": _NR_MASTER,
  "C": _NR_MASTER_CANDIATE,
  "D": _NR_DRAINED,
  "O": _NR_OFFLINE,
  "R": _NR_REGULAR,
  }

# Request data version field
_REQ_DATA_VERSION = "__version__"

# Feature string for instance creation request data version 1
_INST_CREATE_REQV1 = "instance-create-reqv1"

# Feature string for instance reinstall request version 1
_INST_REINSTALL_REQV1 = "instance-reinstall-reqv1"

# Timeout for /2/jobs/[job_id]/wait. Gives job up to 10 seconds to change.
_WFJC_TIMEOUT = 10


class R_version(baserlib.R_Generic):
  """/version resource.

  This resource should be used to determine the remote API version and
  to adapt clients accordingly.

  """
  @staticmethod
  def GET():
    """Returns the remote API version.

    """
    return constants.RAPI_VERSION


class R_2_info(baserlib.R_Generic):
  """/2/info resource.

  """
  @staticmethod
  def GET():
    """Returns cluster information.

    """
    client = baserlib.GetClient()
    return client.QueryClusterInfo()


class R_2_features(baserlib.R_Generic):
  """/2/features resource.

  """
  @staticmethod
  def GET():
    """Returns list of optional RAPI features implemented.

    """
    return [_INST_CREATE_REQV1, _INST_REINSTALL_REQV1]


class R_2_os(baserlib.R_Generic):
  """/2/os resource.

  """
  @staticmethod
  def GET():
    """Return a list of all OSes.

    Can return error 500 in case of a problem.

    Example: ["debian-etch"]

    """
    cl = baserlib.GetClient()
    op = opcodes.OpDiagnoseOS(output_fields=["name", "variants"], names=[])
    job_id = baserlib.SubmitJob([op], cl)
    # we use custom feedback function, instead of print we log the status
    result = cli.PollJob(job_id, cl, feedback_fn=baserlib.FeedbackFn)
    diagnose_data = result[0]

    if not isinstance(diagnose_data, list):
      raise http.HttpBadGateway(message="Can't get OS list")

    os_names = []
    for (name, variants) in diagnose_data:
      os_names.extend(cli.CalculateOSNames(name, variants))

    return os_names


class R_2_redist_config(baserlib.R_Generic):
  """/2/redistribute-config resource.

  """
  @staticmethod
  def PUT():
    """Redistribute configuration to all nodes.

    """
    return baserlib.SubmitJob([opcodes.OpClusterRedistConf()])


class R_2_cluster_modify(baserlib.R_Generic):
  """/2/modify resource.

  """
  def PUT(self):
    """Modifies cluster parameters.

    @return: a job id

    """
    op = baserlib.FillOpcode(opcodes.OpClusterSetParams, self.request_body,
                             None)

    return baserlib.SubmitJob([op])


class R_2_jobs(baserlib.R_Generic):
  """/2/jobs resource.

  """
  @staticmethod
  def GET():
    """Returns a dictionary of jobs.

    @return: a dictionary with jobs id and uri.

    """
    fields = ["id"]
    cl = baserlib.GetClient()
    # Convert the list of lists to the list of ids
    result = [job_id for [job_id] in cl.QueryJobs(None, fields)]
    return baserlib.BuildUriList(result, "/2/jobs/%s",
                                 uri_fields=("id", "uri"))


class R_2_jobs_id(baserlib.R_Generic):
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
    fields = ["id", "ops", "status", "summary",
              "opstatus", "opresult", "oplog",
              "received_ts", "start_ts", "end_ts",
              ]
    job_id = self.items[0]
    result = baserlib.GetClient().QueryJobs([job_id, ], fields)[0]
    if result is None:
      raise http.HttpNotFound()
    return baserlib.MapFields(fields, result)

  def DELETE(self):
    """Cancel not-yet-started job.

    """
    job_id = self.items[0]
    result = baserlib.GetClient().CancelJob(job_id)
    return result


class R_2_jobs_id_wait(baserlib.R_Generic):
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
            isinstance(prev_log_serial, (int, long))):
      raise http.HttpBadRequest("The 'previous_log_serial' parameter should"
                                " be a number")

    client = baserlib.GetClient()
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


class R_2_nodes(baserlib.R_Generic):
  """/2/nodes resource.

  """
  def GET(self):
    """Returns a list of all nodes.

    """
    client = baserlib.GetClient()

    if self.useBulk():
      bulkdata = client.QueryNodes([], N_FIELDS, False)
      return baserlib.MapBulkFields(bulkdata, N_FIELDS)
    else:
      nodesdata = client.QueryNodes([], ["name"], False)
      nodeslist = [row[0] for row in nodesdata]
      return baserlib.BuildUriList(nodeslist, "/2/nodes/%s",
                                   uri_fields=("id", "uri"))


class R_2_nodes_name(baserlib.R_Generic):
  """/2/nodes/[node_name] resource.

  """
  def GET(self):
    """Send information about a node.

    """
    node_name = self.items[0]
    client = baserlib.GetClient()

    result = baserlib.HandleItemQueryErrors(client.QueryNodes,
                                            names=[node_name], fields=N_FIELDS,
                                            use_locking=self.useLocking())

    return baserlib.MapFields(N_FIELDS, result[0])


class R_2_nodes_name_role(baserlib.R_Generic):
  """ /2/nodes/[node_name]/role resource.

  """
  def GET(self):
    """Returns the current node role.

    @return: Node role

    """
    node_name = self.items[0]
    client = baserlib.GetClient()
    result = client.QueryNodes(names=[node_name], fields=["role"],
                               use_locking=self.useLocking())

    return _NR_MAP[result[0][0]]

  def PUT(self):
    """Sets the node role.

    @return: a job id

    """
    if not isinstance(self.request_body, basestring):
      raise http.HttpBadRequest("Invalid body contents, not a string")

    node_name = self.items[0]
    role = self.request_body

    if role == _NR_REGULAR:
      candidate = False
      offline = False
      drained = False

    elif role == _NR_MASTER_CANDIATE:
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

    op = opcodes.OpSetNodeParams(node_name=node_name,
                                 master_candidate=candidate,
                                 offline=offline,
                                 drained=drained,
                                 force=bool(self.useForce()))

    return baserlib.SubmitJob([op])


class R_2_nodes_name_evacuate(baserlib.R_Generic):
  """/2/nodes/[node_name]/evacuate resource.

  """
  def POST(self):
    """Evacuate all secondary instances off a node.

    """
    node_name = self.items[0]
    remote_node = self._checkStringVariable("remote_node", default=None)
    iallocator = self._checkStringVariable("iallocator", default=None)
    early_r = bool(self._checkIntVariable("early_release", default=0))
    dry_run = bool(self.dryRun())

    cl = baserlib.GetClient()

    op = opcodes.OpNodeEvacuationStrategy(nodes=[node_name],
                                          iallocator=iallocator,
                                          remote_node=remote_node)

    job_id = baserlib.SubmitJob([op], cl)
    # we use custom feedback function, instead of print we log the status
    result = cli.PollJob(job_id, cl, feedback_fn=baserlib.FeedbackFn)

    jobs = []
    for iname, node in result:
      if dry_run:
        jid = None
      else:
        op = opcodes.OpReplaceDisks(instance_name=iname,
                                    remote_node=node, disks=[],
                                    mode=constants.REPLACE_DISK_CHG,
                                    early_release=early_r)
        jid = baserlib.SubmitJob([op])
      jobs.append((jid, iname, node))

    return jobs


class R_2_nodes_name_migrate(baserlib.R_Generic):
  """/2/nodes/[node_name]/migrate resource.

  """
  def POST(self):
    """Migrate all primary instances from a node.

    """
    node_name = self.items[0]

    if "live" in self.queryargs and "mode" in self.queryargs:
      raise http.HttpBadRequest("Only one of 'live' and 'mode' should"
                                " be passed")
    elif "live" in self.queryargs:
      if self._checkIntVariable("live", default=1):
        mode = constants.HT_MIGRATION_LIVE
      else:
        mode = constants.HT_MIGRATION_NONLIVE
    else:
      mode = self._checkStringVariable("mode", default=None)

    op = opcodes.OpMigrateNode(node_name=node_name, mode=mode)

    return baserlib.SubmitJob([op])


class R_2_nodes_name_storage(baserlib.R_Generic):
  """/2/nodes/[node_name]/storage resource.

  """
  # LUQueryNodeStorage acquires locks, hence restricting access to GET
  GET_ACCESS = [rapi.RAPI_ACCESS_WRITE]

  def GET(self):
    node_name = self.items[0]

    storage_type = self._checkStringVariable("storage_type", None)
    if not storage_type:
      raise http.HttpBadRequest("Missing the required 'storage_type'"
                                " parameter")

    output_fields = self._checkStringVariable("output_fields", None)
    if not output_fields:
      raise http.HttpBadRequest("Missing the required 'output_fields'"
                                " parameter")

    op = opcodes.OpQueryNodeStorage(nodes=[node_name],
                                    storage_type=storage_type,
                                    output_fields=output_fields.split(","))
    return baserlib.SubmitJob([op])


class R_2_nodes_name_storage_modify(baserlib.R_Generic):
  """/2/nodes/[node_name]/storage/modify resource.

  """
  def PUT(self):
    node_name = self.items[0]

    storage_type = self._checkStringVariable("storage_type", None)
    if not storage_type:
      raise http.HttpBadRequest("Missing the required 'storage_type'"
                                " parameter")

    name = self._checkStringVariable("name", None)
    if not name:
      raise http.HttpBadRequest("Missing the required 'name'"
                                " parameter")

    changes = {}

    if "allocatable" in self.queryargs:
      changes[constants.SF_ALLOCATABLE] = \
        bool(self._checkIntVariable("allocatable", default=1))

    op = opcodes.OpModifyNodeStorage(node_name=node_name,
                                     storage_type=storage_type,
                                     name=name,
                                     changes=changes)
    return baserlib.SubmitJob([op])


class R_2_nodes_name_storage_repair(baserlib.R_Generic):
  """/2/nodes/[node_name]/storage/repair resource.

  """
  def PUT(self):
    node_name = self.items[0]

    storage_type = self._checkStringVariable("storage_type", None)
    if not storage_type:
      raise http.HttpBadRequest("Missing the required 'storage_type'"
                                " parameter")

    name = self._checkStringVariable("name", None)
    if not name:
      raise http.HttpBadRequest("Missing the required 'name'"
                                " parameter")

    op = opcodes.OpRepairNodeStorage(node_name=node_name,
                                     storage_type=storage_type,
                                     name=name)
    return baserlib.SubmitJob([op])


def _ParseCreateGroupRequest(data, dry_run):
  """Parses a request for creating a node group.

  @rtype: L{opcodes.OpGroupAdd}
  @return: Group creation opcode

  """
  group_name = baserlib.CheckParameter(data, "name")
  alloc_policy = baserlib.CheckParameter(data, "alloc_policy", default=None)

  return opcodes.OpGroupAdd(group_name=group_name,
                            alloc_policy=alloc_policy,
                            dry_run=dry_run)


class R_2_groups(baserlib.R_Generic):
  """/2/groups resource.

  """
  def GET(self):
    """Returns a list of all node groups.

    """
    client = baserlib.GetClient()

    if self.useBulk():
      bulkdata = client.QueryGroups([], G_FIELDS, False)
      return baserlib.MapBulkFields(bulkdata, G_FIELDS)
    else:
      data = client.QueryGroups([], ["name"], False)
      groupnames = [row[0] for row in data]
      return baserlib.BuildUriList(groupnames, "/2/groups/%s",
                                   uri_fields=("name", "uri"))

  def POST(self):
    """Create a node group.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")
    op = _ParseCreateGroupRequest(self.request_body, self.dryRun())
    return baserlib.SubmitJob([op])


class R_2_groups_name(baserlib.R_Generic):
  """/2/groups/[group_name] resource.

  """
  def GET(self):
    """Send information about a node group.

    """
    group_name = self.items[0]
    client = baserlib.GetClient()

    result = baserlib.HandleItemQueryErrors(client.QueryGroups,
                                            names=[group_name], fields=G_FIELDS,
                                            use_locking=self.useLocking())

    return baserlib.MapFields(G_FIELDS, result[0])

  def DELETE(self):
    """Delete a node group.

    """
    op = opcodes.OpRemoveGroup(group_name=self.items[0],
                               dry_run=bool(self.dryRun()))

    return baserlib.SubmitJob([op])


def _ParseModifyGroupRequest(name, data):
  """Parses a request for modifying a node group.

  @rtype: L{opcodes.OpSetGroupParams}
  @return: Group modify opcode

  """
  alloc_policy = baserlib.CheckParameter(data, "alloc_policy", default=None)
  return opcodes.OpSetGroupParams(group_name=name, alloc_policy=alloc_policy)


class R_2_groups_name_modify(baserlib.R_Generic):
  """/2/groups/[group_name]/modify resource.

  """
  def PUT(self):
    """Changes some parameters of node group.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")

    op = _ParseModifyGroupRequest(self.items[0], self.request_body)

    return baserlib.SubmitJob([op])


def _ParseRenameGroupRequest(name, data, dry_run):
  """Parses a request for renaming a node group.

  @type name: string
  @param name: name of the node group to rename
  @type data: dict
  @param data: the body received by the rename request
  @type dry_run: bool
  @param dry_run: whether to perform a dry run

  @rtype: L{opcodes.OpRenameGroup}
  @return: Node group rename opcode

  """
  old_name = name
  new_name = baserlib.CheckParameter(data, "new_name")

  return opcodes.OpRenameGroup(old_name=old_name, new_name=new_name,
                               dry_run=dry_run)


class R_2_groups_name_rename(baserlib.R_Generic):
  """/2/groups/[group_name]/rename resource.

  """
  def PUT(self):
    """Changes the name of a node group.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")
    op = _ParseRenameGroupRequest(self.items[0], self.request_body,
                                  self.dryRun())
    return baserlib.SubmitJob([op])


class R_2_groups_name_assign_nodes(baserlib.R_Generic):
  """/2/groups/[group_name]/assign-nodes resource.

  """
  def PUT(self):
    """Assigns nodes to a group.

    @return: a job id

    """
    op = baserlib.FillOpcode(opcodes.OpAssignGroupNodes, self.request_body, {
      "group_name": self.items[0],
      "dry_run": self.dryRun(),
      "force": self.useForce(),
      })

    return baserlib.SubmitJob([op])


def _ParseInstanceCreateRequestVersion1(data, dry_run):
  """Parses an instance creation request version 1.

  @rtype: L{opcodes.OpCreateInstance}
  @return: Instance creation opcode

  """
  # Disks
  disks_input = baserlib.CheckParameter(data, "disks", exptype=list)

  disks = []
  for idx, i in enumerate(disks_input):
    baserlib.CheckType(i, dict, "Disk %d specification" % idx)

    # Size is mandatory
    try:
      size = i[constants.IDISK_SIZE]
    except KeyError:
      raise http.HttpBadRequest("Disk %d specification wrong: missing disk"
                                " size" % idx)

    disk = {
      constants.IDISK_SIZE: size,
      }

    # Optional disk access mode
    try:
      disk_access = i[constants.IDISK_MODE]
    except KeyError:
      pass
    else:
      disk[constants.IDISK_MODE] = disk_access

    disks.append(disk)

  assert len(disks_input) == len(disks)

  # Network interfaces
  nics_input = baserlib.CheckParameter(data, "nics", exptype=list)

  nics = []
  for idx, i in enumerate(nics_input):
    baserlib.CheckType(i, dict, "NIC %d specification" % idx)

    nic = {}

    for field in constants.INIC_PARAMS:
      try:
        value = i[field]
      except KeyError:
        continue

      nic[field] = value

    nics.append(nic)

  assert len(nics_input) == len(nics)

  # HV/BE parameters
  hvparams = baserlib.CheckParameter(data, "hvparams", default={})
  utils.ForceDictType(hvparams, constants.HVS_PARAMETER_TYPES)

  beparams = baserlib.CheckParameter(data, "beparams", default={})
  utils.ForceDictType(beparams, constants.BES_PARAMETER_TYPES)

  return opcodes.OpCreateInstance(
    mode=baserlib.CheckParameter(data, "mode"),
    instance_name=baserlib.CheckParameter(data, "name"),
    os_type=baserlib.CheckParameter(data, "os"),
    osparams=baserlib.CheckParameter(data, "osparams", default={}),
    force_variant=baserlib.CheckParameter(data, "force_variant",
                                          default=False),
    no_install=baserlib.CheckParameter(data, "no_install", default=False),
    pnode=baserlib.CheckParameter(data, "pnode", default=None),
    snode=baserlib.CheckParameter(data, "snode", default=None),
    disk_template=baserlib.CheckParameter(data, "disk_template"),
    disks=disks,
    nics=nics,
    src_node=baserlib.CheckParameter(data, "src_node", default=None),
    src_path=baserlib.CheckParameter(data, "src_path", default=None),
    start=baserlib.CheckParameter(data, "start", default=True),
    wait_for_sync=True,
    ip_check=baserlib.CheckParameter(data, "ip_check", default=True),
    name_check=baserlib.CheckParameter(data, "name_check", default=True),
    file_storage_dir=baserlib.CheckParameter(data, "file_storage_dir",
                                             default=None),
    file_driver=baserlib.CheckParameter(data, "file_driver",
                                        default=constants.FD_LOOP),
    source_handshake=baserlib.CheckParameter(data, "source_handshake",
                                             default=None),
    source_x509_ca=baserlib.CheckParameter(data, "source_x509_ca",
                                           default=None),
    source_instance_name=baserlib.CheckParameter(data, "source_instance_name",
                                                 default=None),
    iallocator=baserlib.CheckParameter(data, "iallocator", default=None),
    hypervisor=baserlib.CheckParameter(data, "hypervisor", default=None),
    hvparams=hvparams,
    beparams=beparams,
    dry_run=dry_run,
    )


class R_2_instances(baserlib.R_Generic):
  """/2/instances resource.

  """
  def GET(self):
    """Returns a list of all available instances.

    """
    client = baserlib.GetClient()

    use_locking = self.useLocking()
    if self.useBulk():
      bulkdata = client.QueryInstances([], I_FIELDS, use_locking)
      return baserlib.MapBulkFields(bulkdata, I_FIELDS)
    else:
      instancesdata = client.QueryInstances([], ["name"], use_locking)
      instanceslist = [row[0] for row in instancesdata]
      return baserlib.BuildUriList(instanceslist, "/2/instances/%s",
                                   uri_fields=("id", "uri"))

  def _ParseVersion0CreateRequest(self):
    """Parses an instance creation request version 0.

    Request data version 0 is deprecated and should not be used anymore.

    @rtype: L{opcodes.OpCreateInstance}
    @return: Instance creation opcode

    """
    # Do not modify anymore, request data version 0 is deprecated
    beparams = baserlib.MakeParamsDict(self.request_body,
                                       constants.BES_PARAMETERS)
    hvparams = baserlib.MakeParamsDict(self.request_body,
                                       constants.HVS_PARAMETERS)
    fn = self.getBodyParameter

    # disk processing
    disk_data = fn('disks')
    if not isinstance(disk_data, list):
      raise http.HttpBadRequest("The 'disks' parameter should be a list")
    disks = []
    for idx, d in enumerate(disk_data):
      if not isinstance(d, int):
        raise http.HttpBadRequest("Disk %d specification wrong: should"
                                  " be an integer" % idx)
      disks.append({"size": d})

    # nic processing (one nic only)
    nics = [{"mac": fn("mac", constants.VALUE_AUTO)}]
    if fn("ip", None) is not None:
      nics[0]["ip"] = fn("ip")
    if fn("mode", None) is not None:
      nics[0]["mode"] = fn("mode")
    if fn("link", None) is not None:
      nics[0]["link"] = fn("link")
    if fn("bridge", None) is not None:
      nics[0]["bridge"] = fn("bridge")

    # Do not modify anymore, request data version 0 is deprecated
    return opcodes.OpCreateInstance(
      mode=constants.INSTANCE_CREATE,
      instance_name=fn('name'),
      disks=disks,
      disk_template=fn('disk_template'),
      os_type=fn('os'),
      pnode=fn('pnode', None),
      snode=fn('snode', None),
      iallocator=fn('iallocator', None),
      nics=nics,
      start=fn('start', True),
      ip_check=fn('ip_check', True),
      name_check=fn('name_check', True),
      wait_for_sync=True,
      hypervisor=fn('hypervisor', None),
      hvparams=hvparams,
      beparams=beparams,
      file_storage_dir=fn('file_storage_dir', None),
      file_driver=fn('file_driver', constants.FD_LOOP),
      dry_run=bool(self.dryRun()),
      )

  def POST(self):
    """Create an instance.

    @return: a job id

    """
    if not isinstance(self.request_body, dict):
      raise http.HttpBadRequest("Invalid body contents, not a dictionary")

    # Default to request data version 0
    data_version = self.getBodyParameter(_REQ_DATA_VERSION, 0)

    if data_version == 0:
      op = self._ParseVersion0CreateRequest()
    elif data_version == 1:
      op = _ParseInstanceCreateRequestVersion1(self.request_body,
                                               self.dryRun())
    else:
      raise http.HttpBadRequest("Unsupported request data version %s" %
                                data_version)

    return baserlib.SubmitJob([op])


class R_2_instances_name(baserlib.R_Generic):
  """/2/instances/[instance_name] resource.

  """
  def GET(self):
    """Send information about an instance.

    """
    client = baserlib.GetClient()
    instance_name = self.items[0]

    result = baserlib.HandleItemQueryErrors(client.QueryInstances,
                                            names=[instance_name],
                                            fields=I_FIELDS,
                                            use_locking=self.useLocking())

    return baserlib.MapFields(I_FIELDS, result[0])

  def DELETE(self):
    """Delete an instance.

    """
    op = opcodes.OpRemoveInstance(instance_name=self.items[0],
                                  ignore_failures=False,
                                  dry_run=bool(self.dryRun()))
    return baserlib.SubmitJob([op])


class R_2_instances_name_info(baserlib.R_Generic):
  """/2/instances/[instance_name]/info resource.

  """
  def GET(self):
    """Request detailed instance information.

    """
    instance_name = self.items[0]
    static = bool(self._checkIntVariable("static", default=0))

    op = opcodes.OpQueryInstanceData(instances=[instance_name],
                                     static=static)
    return baserlib.SubmitJob([op])


class R_2_instances_name_reboot(baserlib.R_Generic):
  """/2/instances/[instance_name]/reboot resource.

  Implements an instance reboot.

  """
  def POST(self):
    """Reboot an instance.

    The URI takes type=[hard|soft|full] and
    ignore_secondaries=[False|True] parameters.

    """
    instance_name = self.items[0]
    reboot_type = self.queryargs.get('type',
                                     [constants.INSTANCE_REBOOT_HARD])[0]
    ignore_secondaries = bool(self._checkIntVariable('ignore_secondaries'))
    op = opcodes.OpRebootInstance(instance_name=instance_name,
                                  reboot_type=reboot_type,
                                  ignore_secondaries=ignore_secondaries,
                                  dry_run=bool(self.dryRun()))

    return baserlib.SubmitJob([op])


class R_2_instances_name_startup(baserlib.R_Generic):
  """/2/instances/[instance_name]/startup resource.

  Implements an instance startup.

  """
  def PUT(self):
    """Startup an instance.

    The URI takes force=[False|True] parameter to start the instance
    if even if secondary disks are failing.

    """
    instance_name = self.items[0]
    force_startup = bool(self._checkIntVariable('force'))
    op = opcodes.OpStartupInstance(instance_name=instance_name,
                                   force=force_startup,
                                   dry_run=bool(self.dryRun()))

    return baserlib.SubmitJob([op])


class R_2_instances_name_shutdown(baserlib.R_Generic):
  """/2/instances/[instance_name]/shutdown resource.

  Implements an instance shutdown.

  """
  def PUT(self):
    """Shutdown an instance.

    """
    instance_name = self.items[0]
    op = opcodes.OpShutdownInstance(instance_name=instance_name,
                                    dry_run=bool(self.dryRun()))

    return baserlib.SubmitJob([op])


def _ParseInstanceReinstallRequest(name, data):
  """Parses a request for reinstalling an instance.

  """
  if not isinstance(data, dict):
    raise http.HttpBadRequest("Invalid body contents, not a dictionary")

  ostype = baserlib.CheckParameter(data, "os")
  start = baserlib.CheckParameter(data, "start", exptype=bool,
                                  default=True)
  osparams = baserlib.CheckParameter(data, "osparams", default=None)

  ops = [
    opcodes.OpShutdownInstance(instance_name=name),
    opcodes.OpReinstallInstance(instance_name=name, os_type=ostype,
                                osparams=osparams),
    ]

  if start:
    ops.append(opcodes.OpStartupInstance(instance_name=name, force=False))

  return ops


class R_2_instances_name_reinstall(baserlib.R_Generic):
  """/2/instances/[instance_name]/reinstall resource.

  Implements an instance reinstall.

  """
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
    else:
      if not self.queryargs:
        raise http.HttpBadRequest("Missing query parameters")
      # Legacy interface, do not modify/extend
      body = {
        "os": self._checkStringVariable("os"),
        "start": not self._checkIntVariable("nostartup"),
        }

    ops = _ParseInstanceReinstallRequest(self.items[0], body)

    return baserlib.SubmitJob(ops)


class R_2_instances_name_replace_disks(baserlib.R_Generic):
  """/2/instances/[instance_name]/replace-disks resource.

  """
  def POST(self):
    """Replaces disks on an instance.

    """
    instance_name = self.items[0]
    remote_node = self._checkStringVariable("remote_node", default=None)
    mode = self._checkStringVariable("mode", default=None)
    raw_disks = self._checkStringVariable("disks", default=None)
    iallocator = self._checkStringVariable("iallocator", default=None)

    if raw_disks:
      try:
        disks = [int(part) for part in raw_disks.split(",")]
      except ValueError, err:
        raise http.HttpBadRequest("Invalid disk index passed: %s" % str(err))
    else:
      disks = []

    op = opcodes.OpReplaceDisks(instance_name=instance_name,
                                remote_node=remote_node,
                                mode=mode,
                                disks=disks,
                                iallocator=iallocator)

    return baserlib.SubmitJob([op])


class R_2_instances_name_activate_disks(baserlib.R_Generic):
  """/2/instances/[instance_name]/activate-disks resource.

  """
  def PUT(self):
    """Activate disks for an instance.

    The URI might contain ignore_size to ignore current recorded size.

    """
    instance_name = self.items[0]
    ignore_size = bool(self._checkIntVariable('ignore_size'))

    op = opcodes.OpActivateInstanceDisks(instance_name=instance_name,
                                         ignore_size=ignore_size)

    return baserlib.SubmitJob([op])


class R_2_instances_name_deactivate_disks(baserlib.R_Generic):
  """/2/instances/[instance_name]/deactivate-disks resource.

  """
  def PUT(self):
    """Deactivate disks for an instance.

    """
    instance_name = self.items[0]

    op = opcodes.OpDeactivateInstanceDisks(instance_name=instance_name)

    return baserlib.SubmitJob([op])


class R_2_instances_name_prepare_export(baserlib.R_Generic):
  """/2/instances/[instance_name]/prepare-export resource.

  """
  def PUT(self):
    """Prepares an export for an instance.

    @return: a job id

    """
    instance_name = self.items[0]
    mode = self._checkStringVariable("mode")

    op = opcodes.OpBackupPrepare(instance_name=instance_name,
                                 mode=mode)

    return baserlib.SubmitJob([op])


def _ParseExportInstanceRequest(name, data):
  """Parses a request for an instance export.

  @rtype: L{opcodes.OpBackupExport}
  @return: Instance export opcode

  """
  mode = baserlib.CheckParameter(data, "mode",
                                 default=constants.EXPORT_MODE_LOCAL)
  target_node = baserlib.CheckParameter(data, "destination")
  shutdown = baserlib.CheckParameter(data, "shutdown", exptype=bool)
  remove_instance = baserlib.CheckParameter(data, "remove_instance",
                                            exptype=bool, default=False)
  x509_key_name = baserlib.CheckParameter(data, "x509_key_name", default=None)
  destination_x509_ca = baserlib.CheckParameter(data, "destination_x509_ca",
                                                default=None)

  return opcodes.OpBackupExport(instance_name=name,
                                mode=mode,
                                target_node=target_node,
                                shutdown=shutdown,
                                remove_instance=remove_instance,
                                x509_key_name=x509_key_name,
                                destination_x509_ca=destination_x509_ca)


class R_2_instances_name_export(baserlib.R_Generic):
  """/2/instances/[instance_name]/export resource.

  """
  def PUT(self):
    """Exports an instance.

    @return: a job id

    """
    if not isinstance(self.request_body, dict):
      raise http.HttpBadRequest("Invalid body contents, not a dictionary")

    op = _ParseExportInstanceRequest(self.items[0], self.request_body)

    return baserlib.SubmitJob([op])


def _ParseMigrateInstanceRequest(name, data):
  """Parses a request for an instance migration.

  @rtype: L{opcodes.OpMigrateInstance}
  @return: Instance migration opcode

  """
  mode = baserlib.CheckParameter(data, "mode", default=None)
  cleanup = baserlib.CheckParameter(data, "cleanup", exptype=bool,
                                    default=False)

  return opcodes.OpMigrateInstance(instance_name=name, mode=mode,
                                   cleanup=cleanup)


class R_2_instances_name_migrate(baserlib.R_Generic):
  """/2/instances/[instance_name]/migrate resource.

  """
  def PUT(self):
    """Migrates an instance.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")

    op = _ParseMigrateInstanceRequest(self.items[0], self.request_body)

    return baserlib.SubmitJob([op])


def _ParseRenameInstanceRequest(name, data):
  """Parses a request for renaming an instance.

  @rtype: L{opcodes.OpRenameInstance}
  @return: Instance rename opcode

  """
  new_name = baserlib.CheckParameter(data, "new_name")
  ip_check = baserlib.CheckParameter(data, "ip_check", default=True)
  name_check = baserlib.CheckParameter(data, "name_check", default=True)

  return opcodes.OpRenameInstance(instance_name=name, new_name=new_name,
                                  name_check=name_check, ip_check=ip_check)


class R_2_instances_name_rename(baserlib.R_Generic):
  """/2/instances/[instance_name]/rename resource.

  """
  def PUT(self):
    """Changes the name of an instance.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")

    op = _ParseRenameInstanceRequest(self.items[0], self.request_body)

    return baserlib.SubmitJob([op])


def _ParseModifyInstanceRequest(name, data):
  """Parses a request for modifying an instance.

  @rtype: L{opcodes.OpSetInstanceParams}
  @return: Instance modify opcode

  """
  osparams = baserlib.CheckParameter(data, "osparams", default={})
  force = baserlib.CheckParameter(data, "force", default=False)
  nics = baserlib.CheckParameter(data, "nics", default=[])
  disks = baserlib.CheckParameter(data, "disks", default=[])
  disk_template = baserlib.CheckParameter(data, "disk_template", default=None)
  remote_node = baserlib.CheckParameter(data, "remote_node", default=None)
  os_name = baserlib.CheckParameter(data, "os_name", default=None)
  force_variant = baserlib.CheckParameter(data, "force_variant", default=False)

  # HV/BE parameters
  hvparams = baserlib.CheckParameter(data, "hvparams", default={})
  utils.ForceDictType(hvparams, constants.HVS_PARAMETER_TYPES,
                      allowed_values=[constants.VALUE_DEFAULT])

  beparams = baserlib.CheckParameter(data, "beparams", default={})
  utils.ForceDictType(beparams, constants.BES_PARAMETER_TYPES,
                      allowed_values=[constants.VALUE_DEFAULT])

  return opcodes.OpSetInstanceParams(instance_name=name, hvparams=hvparams,
                                     beparams=beparams, osparams=osparams,
                                     force=force, nics=nics, disks=disks,
                                     disk_template=disk_template,
                                     remote_node=remote_node, os_name=os_name,
                                     force_variant=force_variant)


class R_2_instances_name_modify(baserlib.R_Generic):
  """/2/instances/[instance_name]/modify resource.

  """
  def PUT(self):
    """Changes some parameters of an instance.

    @return: a job id

    """
    baserlib.CheckType(self.request_body, dict, "Body contents")

    op = _ParseModifyInstanceRequest(self.items[0], self.request_body)

    return baserlib.SubmitJob([op])


class R_2_instances_name_disk_grow(baserlib.R_Generic):
  """/2/instances/[instance_name]/disk/[disk_index]/grow resource.

  """
  def POST(self):
    """Increases the size of an instance disk.

    @return: a job id

    """
    op = baserlib.FillOpcode(opcodes.OpGrowDisk, self.request_body, {
      "instance_name": self.items[0],
      "disk": int(self.items[1]),
      })

    return baserlib.SubmitJob([op])


class _R_Tags(baserlib.R_Generic):
  """ Quasiclass for tagging resources

  Manages tags. When inheriting this class you must define the
  TAG_LEVEL for it.

  """
  TAG_LEVEL = None

  def __init__(self, items, queryargs, req):
    """A tag resource constructor.

    We have to override the default to sort out cluster naming case.

    """
    baserlib.R_Generic.__init__(self, items, queryargs, req)

    if self.TAG_LEVEL == constants.TAG_CLUSTER:
      self.name = None
    else:
      self.name = items[0]

  def GET(self):
    """Returns a list of tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    # pylint: disable-msg=W0212
    return baserlib._Tags_GET(self.TAG_LEVEL, name=self.name)

  def PUT(self):
    """Add a set of tags.

    The request as a list of strings should be PUT to this URI. And
    you'll have back a job id.

    """
    # pylint: disable-msg=W0212
    if 'tag' not in self.queryargs:
      raise http.HttpBadRequest("Please specify tag(s) to add using the"
                                " the 'tag' parameter")
    return baserlib._Tags_PUT(self.TAG_LEVEL,
                              self.queryargs['tag'], name=self.name,
                              dry_run=bool(self.dryRun()))

  def DELETE(self):
    """Delete a tag.

    In order to delete a set of tags, the DELETE
    request should be addressed to URI like:
    /tags?tag=[tag]&tag=[tag]

    """
    # pylint: disable-msg=W0212
    if 'tag' not in self.queryargs:
      # no we not gonna delete all tags
      raise http.HttpBadRequest("Cannot delete all tags - please specify"
                                " tag(s) using the 'tag' parameter")
    return baserlib._Tags_DELETE(self.TAG_LEVEL,
                                 self.queryargs['tag'],
                                 name=self.name,
                                 dry_run=bool(self.dryRun()))


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


class R_2_tags(_R_Tags):
  """ /2/tags resource.

  Manages cluster tags.

  """
  TAG_LEVEL = constants.TAG_CLUSTER
