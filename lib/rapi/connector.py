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

"""Remote API connection map.

"""

import cgi
import re

from ganeti import constants
from ganeti import http

from ganeti.rapi import baserlib
from ganeti.rapi import rlib1
from ganeti.rapi import rlib2

# the connection map is created at the end of this file
CONNECTOR = {}


class Mapper:
  """Map resource to method.

  """
  def __init__(self, connector=CONNECTOR):
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

    if result:
      return result
    else:
      raise http.HttpNotFound()


class R_root(baserlib.R_Generic):
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
    for handler in CONNECTOR.values():
      m = root_pattern.match(handler.__name__)
      if m:
        name = m.group(1)
        if name != 'root':
          rootlist.append(name)

    return baserlib.BuildUriList(rootlist, "/%s")


CONNECTOR.update({
  "/": R_root,

  "/version": rlib1.R_version,

  "/tags": rlib1.R_tags,
  "/info": rlib1.R_info,

  "/nodes": rlib2.R_nodes,
  re.compile(r'^/nodes/([\w\._-]+)$'): rlib1.R_nodes_name,
  re.compile(r'^/nodes/([\w\._-]+)/tags$'): rlib1.R_nodes_name_tags,

  "/instances": rlib2.R_instances,
  re.compile(r'^/instances/([\w\._-]+)$'): rlib1.R_instances_name,
  re.compile(r'^/instances/([\w\._-]+)/tags$'): rlib1.R_instances_name_tags,

  "/os": rlib1.R_os,

  "/2/jobs": rlib2.R_2_jobs,
  "/2/nodes": rlib2.R_2_nodes,
  "/2/instances": rlib2.R_2_instances,
  re.compile(r'^/2/instances/([\w\._-]+)$'): rlib1.R_instances_name,
  re.compile(r'^/2/instances/([\w\._-]+)/tags$'): rlib2.R_2_instances_name_tags,
  re.compile(r'^/2/instances/([\w\._-]+)/reboot$'):
      rlib2.R_2_instances_name_reboot,
  re.compile(r'^/2/instances/([\w\._-]+)/shutdown$'):
      rlib2.R_2_instances_name_shutdown,
  re.compile(r'^/2/instances/([\w\._-]+)/startup$'):
      rlib2.R_2_instances_name_startup,
  re.compile(r'/2/jobs/(%s)$' % constants.JOB_ID_TEMPLATE): rlib2.R_2_jobs_id,
  })
