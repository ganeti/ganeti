#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""
resources.py

"""

import simplejson
import cgi
import sys
import os
import re

import ganeti.opcodes
import ganeti.errors
import ganeti.cli

CONNECTOR = {
    'R_instances_name':'^/instances/([\w\._-]+)$',
    'R_tags':'^/tags$',
    'R_status':'^/status$',
    'R_os':'^/os$',
    'R_info':'^/info$',

    'R_instances':'^/instances$',
    'R_instances_name_tags':'^/instances/([\w\._-]+)/tags$',

    'R_nodes':'^/nodes$',
    'R_nodes_name':'^/nodes/([\w\._-]+)$',
    'R_nodes_name_tags':'^/nodes/([\w\._-]+)/tags$',

    'R_jobs':'^/jobs$',
    'R_jobs_id':'^/jobs/([\w\._-]+)$',

    'R_index_html':'^/index.html$',
}


class RemoteAPIError(ganeti.errors.GenericError):
  """ Remote API exception."""
  pass


class Mapper:
  """Map resource to method."""

  def __init__(self, con=CONNECTOR):
    """Resource mapper constructor.

    Args:
      con - a dictionary, mapping method name with URL path regexp.
    """
    self._map = {}
    for methd in con:
      self._map[methd] = re.compile(con[methd])

  def getController(self, uri):
    """Loking for a map of given path.

    Args:
      uri - string with URI.

    Returns:
      A tuple with following fields:
        methd - name of method mapped to URI.
        items - a list of variable intems in the path.
        args - a dictionary with additional parameters from URL.
      None, if no method found.
    """
    result = None
    args = {}
    d_uri = uri.split('?', 1)
    if len(d_uri) > 1:
      args = cgi.parse_qs(d_uri[1])
    path = d_uri[0]
    for methd in self._map:
      items = self._map[methd].findall(path)
      if items:
        result = (methd, items, args)
        break
    return result


class R_Generic(object):
  """Generic class for resources.

  """

  def __init__(self, dispatcher, items, args):
    """ Gentric resource constructor.

    Args:
      dispatcher - HTTPRequestHandler object.
      items - a list with variables encoded in the URL.
      args - a dictionary with additional options from URL.
    """
    self.dispatcher = dispatcher
    self.items = items
    self.args = args
    self.code = 200
    self.result = None

  def do_Request(self, request):
    """Default request flow.

    """
    try:
      disp = getattr(self, '_%s' % request.lower())
      disp()
      self.send(self.code, self.result)
    except RemoteAPIError, msg:
      self.send_error(self.code, str(msg))
    except ganeti.errors.OpPrereqError, msg:
      self.send_error(404, str(msg))
    except AttributeError, msg:
      self.send_error(405, 'Method Not Implemented: %s' % msg)
    except Exception, msg:
      self.send_error(500, 'Internal Server Error: %s' % msg)

  def send(self, code, data=None):
    """ Printout data.

    Args:
      code - int, the HTTP response code.
      data - message body.
    """
    self.dispatcher.send_response(code)
    # rfc4627.txt
    self.dispatcher.send_header("Content-type", "application/json")
    self.dispatcher.end_headers()
    if data:
      self.dispatcher.wfile.write(simplejson.dumps(data))

  def send_error(self, code, message):
    self.dispatcher.send_error(code, message)


class R_instances(R_Generic):
  """Implementation of /instances resource"""

  def _get(self):
    """ Send back to client list of available instances.
    """
    result = []
    request = ganeti.opcodes.OpQueryInstances(output_fields=["name"], names=[])
    instancelist = ganeti.cli.SubmitOpCode(request)
    for instance in instancelist:
      result.append({
        'name':instance[0],
        'uri':'/instances/%s' % instance[0]})
    self.result = result


class R_tags(R_Generic):
  """docstring for R_tag."""

  def _get(self):
    """docstring for _get."""
    request = ganeti.opcodes.OpDumpClusterConfig()
    config = ganeti.cli.SubmitOpCode(request)
    self.result = list(config.cluster.tags)


class R_status(R_Generic):
  """Docstring for R_status."""

  def _get(self):
    """docstring for _get"""
    self.result = '{status}'


class R_info(R_Generic):
  """Cluster Info.
  """

  def _get(self):
    request = ganeti.opcodes.OpQueryClusterInfo()
    self.result = ganeti.cli.SubmitOpCode(request)


class R_nodes(R_Generic):
  """Class to dispatch /nodes requests."""

  def _get(self):
    """Send back to cliet list of cluster nodes."""
    result = []
    request = ganeti.opcodes.OpQueryNodes(output_fields=["name"], names=[])
    nodelist = ganeti.cli.SubmitOpCode(request)
    for node in nodelist:
      result.append({
        'name':node[0],
        'uri':'/nodes/%s' % node[0]})
    self.result = result


class R_nodes_name(R_Generic):
  """Class to dispatch /nodes/[node_name] requests."""

  def _get(self):
    result = {}
    fields = ["dtotal", "dfree",
              "mtotal", "mnode", "mfree",
              "pinst_cnt", "sinst_cnt"]

    request = ganeti.opcodes.OpQueryNodes(output_fields=fields,
                                          names=self.items)
    [r_list] = ganeti.cli.SubmitOpCode(request)

    for i in range(len(fields)):
      result[fields[i]] = r_list[i]

    self.result = result


class R_nodes_name_tags(R_Generic):
  """docstring for R_nodes_name_tags."""

  def _get(self):
    """docstring for _get."""
    op = ganeti.opcodes.OpGetTags(kind='node', name=self.items[0])
    tags = ganeti.cli.SubmitOpCode(op)
    self.result = list(tags)


class R_instances_name(R_Generic):

  def _get(self):
    fields = ["name", "os", "pnode", "snodes",
              "admin_state", "admin_ram",
              "disk_template", "ip", "mac", "bridge",
              "sda_size", "sdb_size", "vcpus"]

    request = ganeti.opcodes.OpQueryInstances(output_fields=fields,
                                              names=self.items)
    data = ganeti.cli.SubmitOpCode(request)

    result = {}
    for i in range(len(fields)):
      result[fields[i]] = data[0][i]
    self.result = result


class R_instances_name_tags(R_Generic):
  """docstring for R_instances_name_tags."""

  def _get(self):
    """docstring for _get."""
    op = ganeti.opcodes.OpGetTags(kind='instance', name=self.items[0])
    tags = ganeti.cli.SubmitOpCode(op)
    self.result = list(tags)


class R_os(R_Generic):
  """Class to povide list of valid OS."""

  def _get(self):
    request = ganeti.opcodes.OpDiagnoseOS(output_fields=["name", "valid"],
                                          names=[])
    diagnose_data = ganeti.cli.SubmitOpCode(request)

    if not isinstance(diagnose_data, list):
      self.code = 500
      raise RemoteAPIError("Can't get the OS list")

    self.result = [row[0] for row in diagnose_data if row[1]]


def main():
  pass


if __name__ == '__main__':
  main()
