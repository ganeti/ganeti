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


"""Remote API version 1 resources library.

"""

import ganeti.cli
import ganeti.errors
import ganeti.opcodes

from ganeti import constants
from ganeti import http

from ganeti.rapi import baserlib


I_FIELDS = ["name", "os", "pnode", "snodes", "admin_state", "disk_template",
            "ip", "mac", "bridge", "sda_size", "sdb_size", "beparams",
            "oper_state", "status", "tags"]

N_FIELDS = ["name", "dtotal", "dfree",
            "mtotal", "mnode", "mfree",
            "pinst_cnt", "sinst_cnt", "tags"]


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


class R_tags(baserlib.R_Generic):
  """/tags resource.

  Manages cluster tags.

  """
  DOC_URI = "/tags"

  def GET(self):
    """Returns a list of all cluster tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return baserlib._Tags_GET(constants.TAG_CLUSTER)


class R_info(baserlib.R_Generic):
  """Cluster info.

  """
  DOC_URI = "/info"

  def GET(self):
    """Returns cluster information.

    Example::

      {
        "config_version": 3,
        "name": "cluster1.example.com",
        "software_version": "1.2.4",
        "os_api_version": 5,
        "export_version": 0,
        "master": "node1.example.com",
        "architecture": [
          "64bit",
          "x86_64"
        ],
        "hypervisor_type": "xen-pvm",
        "protocol_version": 12
      }

    """
    op = ganeti.opcodes.OpQueryClusterInfo()
    return ganeti.cli.SubmitOpCode(op)


class R_nodes_name(baserlib.R_Generic):
  """/nodes/[node_name] resources.

  """
  DOC_URI = "/nodes/[node_name]"

  def GET(self):
    """Send information about a node.

    """
    node_name = self.items[0]
    op = ganeti.opcodes.OpQueryNodes(output_fields=N_FIELDS,
                                     names=[node_name])
    result = ganeti.cli.SubmitOpCode(op)

    return baserlib.MapFields(N_FIELDS, result[0])


class R_nodes_name_tags(baserlib.R_Generic):
  """/nodes/[node_name]/tags resource.

  Manages per-node tags.

  """
  DOC_URI = "/nodes/[node_name]/tags"

  def GET(self):
    """Returns a list of node tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return baserlib._Tags_GET(constants.TAG_NODE, name=self.items[0])


class R_instances_name(baserlib.R_Generic):
  """/instances/[instance_name] resources.

  """
  DOC_URI = "/instances/[instance_name]"

  def GET(self):
    """Send information about an instance.

    """
    instance_name = self.items[0]
    op = ganeti.opcodes.OpQueryInstances(output_fields=I_FIELDS,
                                         names=[instance_name])
    result = ganeti.cli.SubmitOpCode(op)

    return baserlib.MapFields(I_FIELDS, result[0])

  def DELETE(self):
    """Removes an instance.

    """
    instance_name = self.items[0]
    op = ganeti.opcodes.OpRemoveInstance(instance_name=instance_name,
                                         ignore_failures=True)
    job_id = ganeti.cli.SendJob([op])

    return job_id

  def PUT(self):
    """Modify an instance.

    """
    instance_name = self.items[0]
    opts = {}

    for key in self.queryargs:
      opts[key] = self.queryargs[key][0]

    beparams = baserlib.MakeParamsDict(opts, constants.BES_PARAMETERS)
    hvparams = baserlib.MakeParamsDict(opts, constants.HVS_PARAMETERS)

    op = ganeti.opcodes.OpSetInstanceParams(
        instance_name=instance_name,
        ip=opts.get('ip', None),
        bridge=opts.get('bridge', None),
        mac=opts.get('mac', None),
        hvparams=hvparams,
        beparams=beparams,
        force=opts.get('force', None))

    job_id = ganeti.cli.SendJob([op])

    return job_id


class R_instances_name_tags(baserlib.R_Generic):
  """/instances/[instance_name]/tags resource.

  Manages per-instance tags.

  """
  DOC_URI = "/instances/[instance_name]/tags"

  def GET(self):
    """Returns a list of instance tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return baserlib._Tags_GET(constants.TAG_INSTANCE, name=self.items[0])


class R_os(baserlib.R_Generic):
  """/os resource.

  """
  DOC_URI = "/os"

  def GET(self):
    """Return a list of all OSes.

    Can return error 500 in case of a problem.

    Example: ["debian-etch"]

    """
    op = ganeti.opcodes.OpDiagnoseOS(output_fields=["name", "valid"],
                                     names=[])
    diagnose_data = ganeti.cli.SubmitOpCode(op)

    if not isinstance(diagnose_data, list):
      raise http.HttpInternalError(message="Can't get OS list")

    return [row[0] for row in diagnose_data if row[1]]
