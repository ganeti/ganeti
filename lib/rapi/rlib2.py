#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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

"""

from ganeti import opcodes
from ganeti import http
from ganeti import constants
from ganeti import cli
from ganeti import rapi
from ganeti.rapi import baserlib


I_FIELDS = ["name", "admin_state", "os",
            "pnode", "snodes",
            "disk_template",
            "nic.ips", "nic.macs", "nic.modes", "nic.links",
            "network_port",
            "disk.sizes", "disk_usage",
            "beparams", "hvparams",
            "oper_state", "oper_ram", "status",
            "tags"]

N_FIELDS = ["name", "offline", "master_candidate", "drained",
            "dtotal", "dfree",
            "mtotal", "mnode", "mfree",
            "pinst_cnt", "sinst_cnt", "tags",
            "ctotal", "cnodes", "csockets",
            "pip", "sip", "serial_no", "role",
            "pinst_list", "sinst_list",
            ]

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


class R_version(baserlib.R_Generic):
  """/version resource.

  This resource should be used to determine the remote API version and
  to adapt clients accordingly.

  """
  def GET(self):
    """Returns the remote API version.

    """
    return constants.RAPI_VERSION


class R_2_info(baserlib.R_Generic):
  """Cluster info.

  """
  def GET(self):
    """Returns cluster information.

    """
    client = baserlib.GetClient()
    return client.QueryClusterInfo()


class R_2_os(baserlib.R_Generic):
  """/2/os resource.

  """
  def GET(self):
    """Return a list of all OSes.

    Can return error 500 in case of a problem.

    Example: ["debian-etch"]

    """
    cl = baserlib.GetClient()
    op = opcodes.OpDiagnoseOS(output_fields=["name", "valid"], names=[])
    job_id = baserlib.SubmitJob([op], cl)
    # we use custom feedback function, instead of print we log the status
    result = cli.PollJob(job_id, cl, feedback_fn=baserlib.FeedbackFn)
    diagnose_data = result[0]

    if not isinstance(diagnose_data, list):
      raise http.HttpBadGateway(message="Can't get OS list")

    return [row[0] for row in diagnose_data if row[1]]


class R_2_jobs(baserlib.R_Generic):
  """/2/jobs resource.

  """
  def GET(self):
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
  """/2/nodes/[node_name] resources.

  """
  def GET(self):
    """Send information about a node.

    """
    node_name = self.items[0]
    client = baserlib.GetClient()
    result = client.QueryNodes(names=[node_name], fields=N_FIELDS,
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
    if not isinstance(self.req.request_body, basestring):
      raise http.HttpBadRequest("Invalid body contents, not a string")

    node_name = self.items[0]
    role = self.req.request_body

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

    op = opcodes.OpEvacuateNode(node_name=node_name,
                                remote_node=remote_node,
                                iallocator=iallocator)

    return baserlib.SubmitJob([op])


class R_2_nodes_name_migrate(baserlib.R_Generic):
  """/2/nodes/[node_name]/migrate resource.

  """
  def POST(self):
    """Migrate all primary instances from a node.

    """
    node_name = self.items[0]
    live = bool(self._checkIntVariable("live", default=1))

    op = opcodes.OpMigrateNode(node_name=node_name, live=live)

    return baserlib.SubmitJob([op])


class R_2_nodes_name_storage(baserlib.R_Generic):
  """/2/nodes/[node_name]/storage ressource.

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
  """/2/nodes/[node_name]/storage/modify ressource.

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
  """/2/nodes/[node_name]/storage/repair ressource.

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

  def POST(self):
    """Create an instance.

    @return: a job id

    """
    if not isinstance(self.req.request_body, dict):
      raise http.HttpBadRequest("Invalid body contents, not a dictionary")

    beparams = baserlib.MakeParamsDict(self.req.request_body,
                                       constants.BES_PARAMETERS)
    hvparams = baserlib.MakeParamsDict(self.req.request_body,
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
                                  " be an integer")
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

    op = opcodes.OpCreateInstance(
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
      wait_for_sync=True,
      hypervisor=fn('hypervisor', None),
      hvparams=hvparams,
      beparams=beparams,
      file_storage_dir=fn('file_storage_dir', None),
      file_driver=fn('file_driver', 'loop'),
      dry_run=bool(self.dryRun()),
      )

    return baserlib.SubmitJob([op])


class R_2_instances_name(baserlib.R_Generic):
  """/2/instances/[instance_name] resources.

  """
  def GET(self):
    """Send information about an instance.

    """
    client = baserlib.GetClient()
    instance_name = self.items[0]
    result = client.QueryInstances(names=[instance_name], fields=I_FIELDS,
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
    instance_name = self.items[0]
    ostype = self._checkStringVariable('os')
    nostartup = self._checkIntVariable('nostartup')
    ops = [
      opcodes.OpShutdownInstance(instance_name=instance_name),
      opcodes.OpReinstallInstance(instance_name=instance_name, os_type=ostype),
      ]
    if not nostartup:
      ops.append(opcodes.OpStartupInstance(instance_name=instance_name,
                                           force=False))
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

    if self.TAG_LEVEL != constants.TAG_CLUSTER:
      self.name = items[0]
    else:
      self.name = ""

  def GET(self):
    """Returns a list of tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return baserlib._Tags_GET(self.TAG_LEVEL, name=self.name)

  def PUT(self):
    """Add a set of tags.

    The request as a list of strings should be PUT to this URI. And
    you'll have back a job id.

    """
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
  """ /2/instances/tags resource.

  Manages cluster tags.

  """
  TAG_LEVEL = constants.TAG_CLUSTER
