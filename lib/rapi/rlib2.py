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

    Returns:
      A dictionary with jobs id and uri.

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

    Returns:
      A dictionary with job parameters.

    The result includes:
      id - job ID as a number
      status - current job status as a string
      ops - involved OpCodes as a list of dictionaries for each opcodes in
        the job
      opstatus - OpCodes status as a list
      opresult - OpCodes results as a list of lists

    """
    fields = ["id", "ops", "status", "opstatus", "opresult"]
    job_id = self.items[0]
    result = luxi.Client().QueryJobs([job_id, ], fields)[0]
    return baserlib.MapFields(fields, result)


class R_2_nodes(baserlib.R_Generic):
  """/2/nodes resource.

  """
  DOC_URI = "/2/nodes"

  def GET(self):
    """Returns a list of all nodes.

    Returns:
      A dictionary with 'name' and 'uri' keys for each of them.

    Example: [
        {
          "id": "node1.example.com",
          "uri": "\/instances\/node1.example.com"
        },
        {
          "id": "node2.example.com",
          "uri": "\/instances\/node2.example.com"
        }]

    If the optional 'bulk' argument is provided and set to 'true'
    value (i.e '?bulk=1'), the output contains detailed
    information about nodes as a list.

    Example: [
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

    """
    op = ganeti.opcodes.OpQueryNodes(output_fields=["name"], names=[])
    nodeslist = baserlib.ExtractField(ganeti.cli.SubmitOpCode(op), 0)

    if 'bulk' in self.queryargs:
      op = ganeti.opcodes.OpQueryNodes(output_fields=N_FIELDS,
                                       names=nodeslist)
      result = ganeti.cli.SubmitOpCode(op)
      return baserlib.MapBulkFields(result, N_FIELDS)

    return baserlib.BuildUriList(nodeslist, "/2/nodes/%s",
                                 uri_fields=("id", "uri"))


class R_2_instances(baserlib.R_Generic):
  """/2/instances resource.

  """
  DOC_URI = "/2/instances"


  def GET(self):
    """Returns a list of all available instances.

    Returns:
       A dictionary with 'name' and 'uri' keys for each of them.

    Example: [
        {
          "name": "web.example.com",
          "uri": "\/instances\/web.example.com"
        },
        {
          "name": "mail.example.com",
          "uri": "\/instances\/mail.example.com"
        }]

    If the optional 'bulk' argument is provided and set to 'true'
    value (i.e '?bulk=1'), the output contains detailed
    information about instances as a list.

    Example: [
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

    """
    op = ganeti.opcodes.OpQueryInstances(output_fields=["name"], names=[])
    instanceslist = baserlib.ExtractField(ganeti.cli.SubmitOpCode(op), 0)

    if 'bulk' in self.queryargs:
      op = ganeti.opcodes.OpQueryInstances(output_fields=I_FIELDS,
                                           names=instanceslist)
      result = ganeti.cli.SubmitOpCode(op)
      return baserlib.MapBulkFields(result, I_FIELDS)


    else:
      return baserlib.BuildUriList(instanceslist, "/2/instances/%s",
                                   uri_fields=("id", "uri"))


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

  def POST(self):
    """Add a set of tags to the instance.

    The reqest as a list of strings should be POST to this URI. And you'll have
    back a job id.

    """
    return baserlib._Tags_POST(constants.TAG_INSTANCE,
                               self.post_data, name=self.items[0])

  def DELETE(self):
    """Delete a tag.

    In order to delete a set of tags from a instance, DELETE request should be
    addressed to URI like: /2/instances/[instance_name]/tags?tag=[tag]&tag=[tag]

    """
    if 'tag' not in self.queryargs:
      # no we not gonna delete all tags from an instance
      raise http.HTTPNotImplemented
    return baserlib._Tags_DELETE(constants.TAG_INSTANCE,
                                 self.queryargs['tag'],
                                 name=self.items[0])
