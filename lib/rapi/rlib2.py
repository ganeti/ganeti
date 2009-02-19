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

import ganeti.opcodes
from ganeti import http
from ganeti import luxi
from ganeti import constants
from ganeti.rapi import baserlib


I_FIELDS = ["name", "admin_state", "os",
            "pnode", "snodes",
            "disk_template",
            "nic.ips", "nic.macs", "nic.bridges",
            "disk.sizes", "disk_usage",
            "beparams", "hvparams",
            "oper_state", "oper_ram", "status",
            "tags"]

N_FIELDS = ["name", "offline", "master_candidate", "drained",
            "dtotal", "dfree",
            "mtotal", "mnode", "mfree",
            "pinst_cnt", "sinst_cnt", "tags",
            "ctotal", "cnodes", "csockets",
            ]


class R_version(baserlib.R_Generic):
  """/version resource.

  This resource should be used to determine the remote API version and
  to adapt clients accordingly.

  """
  DOC_URI = "/version"

  def GET(self):
    """Returns the remote API version.

    """
    return constants.RAPI_VERSION


class R_2_info(baserlib.R_Generic):
  """Cluster info.

  """
  DOC_URI = "/2/info"

  def GET(self):
    """Returns cluster information.

    Example::

    {
      "config_version": 2000000,
      "name": "cluster",
      "software_version": "2.0.0~beta2",
      "os_api_version": 10,
      "export_version": 0,
      "candidate_pool_size": 10,
      "enabled_hypervisors": [
        "fake"
      ],
      "hvparams": {
        "fake": {}
       },
      "default_hypervisor": "fake",
      "master": "node1.example.com",
      "architecture": [
        "64bit",
        "x86_64"
      ],
      "protocol_version": 20,
      "beparams": {
        "default": {
          "auto_balance": true,
          "vcpus": 1,
          "memory": 128
         }
        }
      }

    """
    client = luxi.Client()
    return client.QueryClusterInfo()


class R_2_os(baserlib.R_Generic):
  """/2/os resource.

  """
  DOC_URI = "/2/os"

  def GET(self):
    """Return a list of all OSes.

    Can return error 500 in case of a problem.

    Example: ["debian-etch"]

    """
    op = ganeti.opcodes.OpDiagnoseOS(output_fields=["name", "valid"],
                                     names=[])
    diagnose_data = ganeti.cli.SubmitOpCode(op)

    if not isinstance(diagnose_data, list):
      raise http.HttpInternalServerError(message="Can't get OS list")

    return [row[0] for row in diagnose_data if row[1]]


class R_2_jobs(baserlib.R_Generic):
  """/2/jobs resource.

  """
  DOC_URI = "/2/jobs"

  def GET(self):
    """Returns a dictionary of jobs.

    @return: a dictionary with jobs id and uri.

    """
    fields = ["id"]
    # Convert the list of lists to the list of ids
    result = [job_id for [job_id] in luxi.Client().QueryJobs(None, fields)]
    return baserlib.BuildUriList(result, "/2/jobs/%s",
                                 uri_fields=("id", "uri"))


class R_2_jobs_id(baserlib.R_Generic):
  """/2/jobs/[job_id] resource.

  """
  DOC_URI = "/2/jobs/[job_id]"

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
    result = luxi.Client().QueryJobs([job_id, ], fields)[0]
    if result is None:
      raise http.HttpNotFound()
    return baserlib.MapFields(fields, result)

  def DELETE(self):
    """Cancel not-yet-started job.

    """
    job_id = self.items[0]
    result = luxi.Client().CancelJob(job_id)
    return result


class R_2_nodes(baserlib.R_Generic):
  """/2/nodes resource.

  """
  DOC_URI = "/2/nodes"

  def GET(self):
    """Returns a list of all nodes.

    Example::

      [
        {
          "id": "node1.example.com",
          "uri": "\/instances\/node1.example.com"
        },
        {
          "id": "node2.example.com",
          "uri": "\/instances\/node2.example.com"
        }
      ]

    If the optional 'bulk' argument is provided and set to 'true'
    value (i.e '?bulk=1'), the output contains detailed
    information about nodes as a list.

    Example::

      [
        {
          "pinst_cnt": 1,
          "mfree": 31280,
          "mtotal": 32763,
          "name": "www.example.com",
          "tags": [],
          "mnode": 512,
          "dtotal": 5246208,
          "sinst_cnt": 2,
          "dfree": 5171712,
          "offline": false
        },
        ...
      ]

    @return: a dictionary with 'name' and 'uri' keys for each of them

    """
    client = luxi.Client()

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
  DOC_URI = "/nodes/[node_name]"

  def GET(self):
    """Send information about a node.

    """
    node_name = self.items[0]
    client = luxi.Client()
    result = client.QueryNodes(names=[node_name], fields=N_FIELDS,
                               use_locking=self.useLocking())

    return baserlib.MapFields(N_FIELDS, result[0])


class R_2_instances(baserlib.R_Generic):
  """/2/instances resource.

  """
  DOC_URI = "/2/instances"

  def GET(self):
    """Returns a list of all available instances.


    Example::

      [
        {
          "name": "web.example.com",
          "uri": "\/instances\/web.example.com"
        },
        {
          "name": "mail.example.com",
          "uri": "\/instances\/mail.example.com"
        }
      ]

    If the optional 'bulk' argument is provided and set to 'true'
    value (i.e '?bulk=1'), the output contains detailed
    information about instances as a list.

    Example::

      [
        {
           "status": "running",
           "disk_usage": 20480,
           "nic.bridges": [
             "xen-br0"
            ],
           "name": "web.example.com",
           "tags": ["tag1", "tag2"],
           "beparams": {
             "vcpus": 2,
             "memory": 512
           },
           "disk.sizes": [
               20480
           ],
           "pnode": "node1.example.com",
           "nic.macs": ["01:23:45:67:89:01"],
           "snodes": ["node2.example.com"],
           "disk_template": "drbd",
           "admin_state": true,
           "os": "debian-etch",
           "oper_state": true
        },
        ...
      ]

    @returns: a dictionary with 'name' and 'uri' keys for each of them.

    """
    client = luxi.Client()

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

    @returns: a job id

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
    nics = [{"mac": fn("mac", constants.VALUE_AUTO),
             "ip": fn("ip", None),
             "bridge": fn("bridge", None)}]

    op = ganeti.opcodes.OpCreateInstance(
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
        )

    job_id = ganeti.cli.SendJob([op])
    return job_id


class R_2_instances_name(baserlib.R_Generic):
  """/2/instances/[instance_name] resources.

  """
  DOC_URI = "/2/instances/[instance_name]"

  def GET(self):
    """Send information about an instance.

    """
    client = luxi.Client()
    instance_name = self.items[0]
    result = client.QueryInstances(names=[instance_name], fields=I_FIELDS,
                                   use_locking=self.useLocking())

    return baserlib.MapFields(I_FIELDS, result[0])

  def DELETE(self):
    """Delete an instance.

    """
    op = ganeti.opcodes.OpRemoveInstance(instance_name=self.items[0],
                                         ignore_failures=False)
    job_id = ganeti.cli.SendJob([op])
    return job_id


class R_2_instances_name_reboot(baserlib.R_Generic):
  """/2/instances/[instance_name]/reboot resource.

  Implements an instance reboot.

  """

  DOC_URI = "/2/instances/[instance_name]/reboot"

  def POST(self):
    """Reboot an instance.

    The URI takes type=[hard|soft|full] and
    ignore_secondaries=[False|True] parameters.

    """
    instance_name = self.items[0]
    reboot_type = self.queryargs.get('type',
                                     [constants.INSTANCE_REBOOT_HARD])[0]
    ignore_secondaries = bool(self.queryargs.get('ignore_secondaries',
                                                 [False])[0])
    op = ganeti.opcodes.OpRebootInstance(
        instance_name=instance_name,
        reboot_type=reboot_type,
        ignore_secondaries=ignore_secondaries)

    job_id = ganeti.cli.SendJob([op])

    return job_id


class R_2_instances_name_startup(baserlib.R_Generic):
  """/2/instances/[instance_name]/startup resource.

  Implements an instance startup.

  """

  DOC_URI = "/2/instances/[instance_name]/startup"

  def PUT(self):
    """Startup an instance.

    The URI takes force=[False|True] parameter to start the instance
    if even if secondary disks are failing.

    """
    instance_name = self.items[0]
    force_startup = bool(self.queryargs.get('force', [False])[0])
    op = ganeti.opcodes.OpStartupInstance(instance_name=instance_name,
                                          force=force_startup)

    job_id = ganeti.cli.SendJob([op])

    return job_id


class R_2_instances_name_shutdown(baserlib.R_Generic):
  """/2/instances/[instance_name]/shutdown resource.

  Implements an instance shutdown.

  """

  DOC_URI = "/2/instances/[instance_name]/shutdown"

  def PUT(self):
    """Shutdown an instance.

    """
    instance_name = self.items[0]
    op = ganeti.opcodes.OpShutdownInstance(instance_name=instance_name)

    job_id = ganeti.cli.SendJob([op])

    return job_id


class _R_Tags(baserlib.R_Generic):
  """ Quasiclass for tagging resources

  Manages tags. Inheriting this class you suppose to define DOC_URI and
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
                              self.queryargs['tag'], name=self.name)

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
                                 name=self.name)


class R_2_instances_name_tags(_R_Tags):
  """ /2/instances/[instance_name]/tags resource.

  Manages per-instance tags.

  """
  DOC_URI = "/2/instances/[instance_name]/tags"
  TAG_LEVEL = constants.TAG_INSTANCE


class R_2_nodes_name_tags(_R_Tags):
  """ /2/nodes/[node_name]/tags resource.

  Manages per-node tags.

  """
  DOC_URI = "/2/nodes/[node_name]/tags"
  TAG_LEVEL = constants.TAG_NODE


class R_2_tags(_R_Tags):
  """ /2/instances/tags resource.

  Manages cluster tags.

  """
  DOC_URI = "/2/tags"
  TAG_LEVEL = constants.TAG_CLUSTER
