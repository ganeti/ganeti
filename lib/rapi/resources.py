#!/usr/bin/python
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


"""Remote API resources.

"""

import cgi
import re

import ganeti.opcodes
import ganeti.errors
import ganeti.cli

from ganeti import constants
from ganeti import utils
from ganeti.rapi import httperror


# Initialized at the end of this file.
_CONNECTOR = {}


def BuildUriList(names, uri_format):
  """Builds a URI list as used by index resources.

  Args:
  - names: List of names as strings
  - uri_format: Format to be applied for URI

  """
  def _MapName(name):
    return { "name": name, "uri": uri_format % name, }

  # Make sure the result is sorted, makes it nicer to look at and simplifies
  # unittests.
  names.sort()

  return map(_MapName, names)


def ExtractField(sequence, index):
  """Creates a list containing one column out of a list of lists.

  Args:
  - sequence: Sequence of lists
  - index: Index of field

  """
  return map(lambda item: item[index], sequence)


def MapFields(names, data):
  """Maps two lists into one dictionary.

  Args:
  - names: Field names (list of strings)
  - data: Field data (list)

  Example:
  >>> MapFields(["a", "b"], ["foo", 123])
  {'a': 'foo', 'b': 123}

  """
  if len(names) != len(data):
    raise AttributeError("Names and data must have the same length")
  return dict([(names[i], data[i]) for i in range(len(names))])


def RequireLock(name='cmd'):
  """Function decorator to automatically acquire locks.

  PEP-318 style function decorator.

  """
  def wrapper(fn):
    def new_f(*args, **kwargs):
      try:
        utils.Lock(name, max_retries=15)
        try:
          # Call real function
          return fn(*args, **kwargs)
        finally:
          utils.Unlock(name)
          utils.LockCleanup()
      except ganeti.errors.LockError, err:
        raise httperror.HTTPServiceUnavailable(message=str(err))

    # Override function metadata
    new_f.func_name = fn.func_name
    new_f.func_doc = fn.func_doc

    return new_f

  return wrapper


def _Tags_GET(kind, name=None):
  """Helper function to retrieve tags.

  """
  if name is None:
    # Do not cause "missing parameter" error, which happens if a parameter
    # is None.
    name = ""
  op = ganeti.opcodes.OpGetTags(kind=kind, name=name)
  tags = ganeti.cli.SubmitOpCode(op)
  return list(tags)


class Mapper:
  """Map resource to method.

  """
  def __init__(self, connector=_CONNECTOR):
    """Resource mapper constructor.

    Args:
      con: a dictionary, mapping method name with URL path regexp

    """
    self._connector = connector

  def getController(self, uri):
    """Find method for a given URI.

    Args:
      uri: string with URI

    Returns:
      None if no method is found or a tuple containing the following fields:
        methd: name of method mapped to URI
        items: a list of variable intems in the path
        args: a dictionary with additional parameters from URL

    """
    if '?' in uri:
      (path, query) = uri.split('?', 1)
      args = cgi.parse_qs(query)
    else:
      path = uri
      query = None
      args = {}

    result = None

    for key, handler in self._connector.iteritems():
      # Regex objects
      if hasattr(key, "match"):
        m = key.match(path)
        if m:
          result = (handler, list(m.groups()), args)
          break

      # String objects
      elif key == path:
        result = (handler, [], args)
        break

    if result is not None:
      return result
    else:
      raise httperror.HTTPNotFound()


class R_Generic(object):
  """Generic class for resources.

  """
  def __init__(self, request, items, queryargs):
    """Generic resource constructor.

    Args:
      request: HTTPRequestHandler object
      items: a list with variables encoded in the URL
      queryargs: a dictionary with additional options from URL

    """
    self.request = request
    self.items = items
    self.queryargs = queryargs


class R_root(R_Generic):
  """/ resource.

  """
  DOC_URI = "/"

  def GET(self):
    """Show the list of mapped resources.
    
    Returns:
      A dictionary with 'name' and 'uri' keys for each of them.

    """
    root_pattern = re.compile('^R_([a-zA-Z0-9]+)$')

    rootlist = []
    for handler in _CONNECTOR.values():
      m = root_pattern.match(handler.__name__)
      if m:
        name = m.group(1)
        if name != 'root':
          rootlist.append(name)

    return BuildUriList(rootlist, "/%s")


class R_version(R_Generic):
  """/version resource.

  This resource should be used to determine the remote API version and to adapt
  clients accordingly.

  """
  DOC_URI = "/version"

  def GET(self):
    """Returns the remote API version.

    """
    return constants.RAPI_VERSION


class R_tags(R_Generic):
  """/tags resource.

  Manages cluster tags.

  """
  DOC_URI = "/tags"

  def GET(self):
    """Returns a list of all cluster tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return _Tags_GET(constants.TAG_CLUSTER)


class R_info(R_Generic):
  """Cluster info.

  """
  DOC_URI = "/info"

  def GET(self):
    """Returns cluster information.

    Example: {
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
      "hypervisor_type": "xen-3.0",
      "protocol_version": 12
    }

    """
    op = ganeti.opcodes.OpQueryClusterInfo()
    return ganeti.cli.SubmitOpCode(op)


class R_nodes(R_Generic):
  """/nodes resource.

  """
  DOC_URI = "/nodes"

  @RequireLock()
  def _GetDetails(self, nodeslist):
    """Returns detailed instance data for bulk output.

    Args:
      instance: A list of nodes names.

    Returns:
      A list of nodes properties

    """
    fields = ["name","dtotal", "dfree",
              "mtotal", "mnode", "mfree",
              "pinst_cnt", "sinst_cnt", "tags"]

    op = ganeti.opcodes.OpQueryNodes(output_fields=fields,
                                     names=nodeslist)
    result = ganeti.cli.SubmitOpCode(op)

    nodes_details = []
    for node in result:
      mapped = MapFields(fields, node)
      nodes_details.append(mapped)
    return nodes_details
 
  def GET(self):
    """Returns a list of all nodes.
    
    Returns:
      A dictionary with 'name' and 'uri' keys for each of them.

    Example: [
        {
          "name": "node1.example.com",
          "uri": "\/instances\/node1.example.com"
        },
        {
          "name": "node2.example.com",
          "uri": "\/instances\/node2.example.com"
        }]

    If the optional 'bulk' argument is provided and set to 'true' 
    value (i.e '?bulk=1'), the output contains detailed
    information about nodes as a list. Note: Lock required.

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
    nodeslist = ExtractField(ganeti.cli.SubmitOpCode(op), 0)
    
    if 'bulk' in self.queryargs:
      return self._GetDetails(nodeslist)

    return BuildUriList(nodeslist, "/nodes/%s")


class R_nodes_name(R_Generic):
  """/nodes/[node_name] resources.

  """
  DOC_URI = "/nodes/[node_name]"

  @RequireLock()
  def GET(self):
    """Send information about a node. 

    """
    node_name = self.items[0]
    fields = ["name","dtotal", "dfree",
              "mtotal", "mnode", "mfree",
              "pinst_cnt", "sinst_cnt", "tags"]

    op = ganeti.opcodes.OpQueryNodes(output_fields=fields,
                                     names=[node_name])
    result = ganeti.cli.SubmitOpCode(op)

    return MapFields(fields, result[0])


class R_nodes_name_tags(R_Generic):
  """/nodes/[node_name]/tags resource.

  Manages per-node tags.

  """
  DOC_URI = "/nodes/[node_name]/tags"

  def GET(self):
    """Returns a list of node tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return _Tags_GET(constants.TAG_NODE, name=self.items[0])


class R_instances(R_Generic):
  """/instances resource.

  """
  DOC_URI = "/instances"

  @RequireLock()
  def _GetDetails(self, instanceslist):
    """Returns detailed instance data for bulk output.

    Args:
      instance: A list of instances names.

    Returns:
      A list with instances properties.

    """
    fields = ["name", "os", "pnode", "snodes",
              "admin_state", "admin_ram",
              "disk_template", "ip", "mac", "bridge",
              "sda_size", "sdb_size", "vcpus",
              "oper_state", "status", "tags"]

    op = ganeti.opcodes.OpQueryInstances(output_fields=fields,
                                         names=instanceslist)
    result = ganeti.cli.SubmitOpCode(op)

    instances_details = []
    for instance in result:
      mapped = MapFields(fields, instance)
      instances_details.append(mapped)
    return instances_details
   
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
    information about instances as a list. Note: Lock required.

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
    instanceslist = ExtractField(ganeti.cli.SubmitOpCode(op), 0)
    
    if 'bulk' in self.queryargs:
      return self._GetDetails(instanceslist)  

    else:
      return BuildUriList(instanceslist, "/instances/%s")


class R_instances_name(R_Generic):
  """/instances/[instance_name] resources.

  """
  DOC_URI = "/instances/[instance_name]"

  @RequireLock()
  def GET(self):
    """Send information about an instance.

    """
    instance_name = self.items[0]
    fields = ["name", "os", "pnode", "snodes",
              "admin_state", "admin_ram",
              "disk_template", "ip", "mac", "bridge",
              "sda_size", "sdb_size", "vcpus",
              "oper_state", "status", "tags"]

    op = ganeti.opcodes.OpQueryInstances(output_fields=fields,
                                         names=[instance_name])
    result = ganeti.cli.SubmitOpCode(op)

    return MapFields(fields, result[0])


class R_instances_name_tags(R_Generic):
  """/instances/[instance_name]/tags resource.

  Manages per-instance tags.

  """
  DOC_URI = "/instances/[instance_name]/tags"

  def GET(self):
    """Returns a list of instance tags.

    Example: ["tag1", "tag2", "tag3"]

    """
    return _Tags_GET(constants.TAG_INSTANCE, name=self.items[0])


class R_os(R_Generic):
  """/os resource.

  """
  DOC_URI = "/os"

  @RequireLock()
  def GET(self):
    """Return a list of all OSes.

    Can return error 500 in case of a problem.

    Example: ["debian-etch"]

    """
    op = ganeti.opcodes.OpDiagnoseOS(output_fields=["name", "valid"],
                                     names=[])
    diagnose_data = ganeti.cli.SubmitOpCode(op)

    if not isinstance(diagnose_data, list):
      raise httperror.HTTPInternalError(message="Can't get OS list")

    return [row[0] for row in diagnose_data if row[1]]


_CONNECTOR.update({
  "/": R_root,

  "/version": R_version,

  "/tags": R_tags,
  "/info": R_info,

  "/nodes": R_nodes,
  re.compile(r'^/nodes/([\w\._-]+)$'): R_nodes_name,
  re.compile(r'^/nodes/([\w\._-]+)/tags$'): R_nodes_name_tags,

  "/instances": R_instances,
  re.compile(r'^/instances/([\w\._-]+)$'): R_instances_name,
  re.compile(r'^/instances/([\w\._-]+)/tags$'): R_instances_name_tags,

  "/os": R_os,
  })
