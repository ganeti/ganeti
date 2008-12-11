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

from ganeti.rapi.rlib1 import I_FIELDS, N_FIELDS


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
    return baserlib.BuildUriList(result, "/2/jobs/%s", uri_fields=("id", "uri"))


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
    fields = ["id", "ops", "status", "opstatus", "opresult"]
    job_id = self.items[0]
    result = luxi.Client().QueryJobs([job_id, ], fields)[0]
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
          "dfree": 5171712
        },
        ...
      ]

    @return: a dictionary with 'name' and 'uri' keys for each of them

    """
    client = luxi.Client()
    nodesdata = client.QueryNodes([], ["name"])
    nodeslist = [row[0] for row in nodesdata]

    if 'bulk' in self.queryargs:
      bulkdata = client.QueryNodes(nodeslist, N_FIELDS)
      return baserlib.MapBulkFields(bulkdata, N_FIELDS)

    return baserlib.BuildUriList(nodeslist, "/2/nodes/%s",
                                 uri_fields=("id", "uri"))


class R_nodes(R_2_nodes):
  """/nodes resource

  """
  # TODO: Temporary resource will be deprecated
  DOC_URI = "/nodes"


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
           "bridge": "xen-br0",
           "name": "web.example.com",
           "tags": ["tag1", "tag2"],
           "admin_ram": 512,
           "sda_size": 20480,
           "pnode": "node1.example.com",
           "mac": "01:23:45:67:89:01",
           "sdb_size": 4096,
           "snodes": ["node2.example.com"],
           "disk_template": "drbd",
           "ip": null,
           "admin_state": true,
           "os": "debian-etch",
           "vcpus": 2,
           "oper_state": true
        },
        ...
      ]

    @returns: a dictionary with 'name' and 'uri' keys for each of them.

    """
    client = luxi.Client()
    instancesdata = client.QueryInstances([], ["name"])
    instanceslist = [row[0] for row in instancesdata]


    if 'bulk' in self.queryargs:
      bulkdata = client.QueryInstances(instanceslist, I_FIELDS)
      return baserlib.MapBulkFields(bulkdata, I_FIELDS)

    else:
      return baserlib.BuildUriList(instanceslist, "/2/instances/%s",
                                   uri_fields=("id", "uri"))

  def POST(self):
    """Create an instance.

    @returns: a job id

    """
    opts = self.req.request_post_data

    beparams = baserlib.MakeParamsDict(opts, constants.BES_PARAMETERS)
    hvparams = baserlib.MakeParamsDict(opts, constants.HVS_PARAMETERS)

    op = ganeti.opcodes.OpCreateInstance(
        instance_name=opts.get('name'),
        disk_size=opts.get('size', 20 * 1024),
        swap_size=opts.get('swap', 4 * 1024),
        disk_template=opts.get('disk_template', None),
        mode=constants.INSTANCE_CREATE,
        os_type=opts.get('os'),
        pnode=opts.get('pnode'),
        snode=opts.get('snode'),
        ip=opts.get('ip', 'none'),
        bridge=opts.get('bridge', None),
        start=opts.get('start', True),
        ip_check=opts.get('ip_check', True),
        wait_for_sync=opts.get('wait_for_sync', True),
        mac=opts.get('mac', 'auto'),
        hypervisor=opts.get('hypervisor', None),
        hvparams=hvparams,
        beparams=beparams,
        iallocator=opts.get('iallocator', None),
        file_storage_dir=opts.get('file_storage_dir', None),
        file_driver=opts.get('file_driver', 'loop'),
        )

    job_id = ganeti.cli.SendJob([op])
    return job_id


class R_instances(R_2_instances):
  """/instances resource.

  """
  # TODO: Temporary resource will be deprecated
  DOC_URI = "/instances"


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


class R_2_instances_name_tags(baserlib.R_Generic):
  """/2/instances/[instance_name]/tags resource.

  Manages per-instance tags.

  """
  DOC_URI = "/2/instances/[instance_name]/tags"

  def GET(self):
    """Returns a list of instance tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return baserlib._Tags_GET(constants.TAG_INSTANCE, name=self.items[0])

  def PUT(self):
    """Add a set of tags to the instance.

    The request as a list of strings should be PUT to this URI. And
    you'll have back a job id.

    """
    return baserlib._Tags_PUT(constants.TAG_INSTANCE,
                               self.post_data, name=self.items[0])

  def DELETE(self):
    """Delete a tag.

    In order to delete a set of tags from a instance, the DELETE
    request should be addressed to URI like:
    /2/instances/[instance_name]/tags?tag=[tag]&tag=[tag]

    """
    if 'tag' not in self.queryargs:
      # no we not gonna delete all tags from an instance
      raise http.HttpNotImplemented()
    return baserlib._Tags_DELETE(constants.TAG_INSTANCE,
                                 self.queryargs['tag'],
                                 name=self.items[0])
