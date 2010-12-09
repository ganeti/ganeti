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

# pylint: disable-msg=C0103

# C0103: Invalid name, since the R_* names are not conforming

import cgi
import re

from ganeti import constants
from ganeti import http
from ganeti import utils

from ganeti.rapi import baserlib
from ganeti.rapi import rlib2


_NAME_PATTERN = r"[\w\._-]+"

# the connection map is created at the end of this file
CONNECTOR = {}


class Mapper:
  """Map resource to method.

  """
  def __init__(self, connector=None):
    """Resource mapper constructor.

    @param connector: a dictionary, mapping method name with URL path regexp

    """
    if connector is None:
      connector = CONNECTOR
    self._connector = connector

  def getController(self, uri):
    """Find method for a given URI.

    @param uri: string with URI

    @return: None if no method is found or a tuple containing
        the following fields:
            - method: name of method mapped to URI
            - items: a list of variable intems in the path
            - args: a dictionary with additional parameters from URL

    """
    if '?' in uri:
      (path, query) = uri.split('?', 1)
      args = cgi.parse_qs(query)
    else:
      path = uri
      query = None
      args = {}

    # Try to find handler for request path
    result = utils.FindMatch(self._connector, path)

    if result is None:
      raise http.HttpNotFound()

    (handler, groups) = result

    return (handler, groups, args)


class R_root(baserlib.R_Generic):
  """/ resource.

  """
  _ROOT_PATTERN = re.compile("^R_([a-zA-Z0-9]+)$")

  @classmethod
  def GET(cls):
    """Show the list of mapped resources.

    @return: a dictionary with 'name' and 'uri' keys for each of them.

    """
    rootlist = []
    for handler in CONNECTOR.values():
      m = cls._ROOT_PATTERN.match(handler.__name__)
      if m:
        name = m.group(1)
        if name != 'root':
          rootlist.append(name)

    return baserlib.BuildUriList(rootlist, "/%s")


def _getResources(id_):
  """Return a list of resources underneath given id.

  This is to generalize querying of version resources lists.

  @return: a list of resources names.

  """
  r_pattern = re.compile('^R_%s_([a-zA-Z0-9]+)$' % id_)

  rlist = []
  for handler in CONNECTOR.values():
    m = r_pattern.match(handler.__name__)
    if m:
      name = m.group(1)
      rlist.append(name)

  return rlist


class R_2(baserlib.R_Generic):
  """ /2 resource, the root of the version 2 API.

  """
  @staticmethod
  def GET():
    """Show the list of mapped resources.

    @return: a dictionary with 'name' and 'uri' keys for each of them.

    """
    return baserlib.BuildUriList(_getResources("2"), "/2/%s")


def GetHandlers(node_name_pattern, instance_name_pattern,
                group_name_pattern, job_id_pattern):
  """Returns all supported resources and their handlers.

  """
  # Important note: New resources should always be added under /2. During a
  # discussion in July 2010 it was decided that having per-resource versions
  # is more flexible and future-compatible than versioning the whole remote
  # API.
  return {
    "/": R_root,

    "/version": rlib2.R_version,

    "/2": R_2,

    "/2/nodes": rlib2.R_2_nodes,
    re.compile(r'^/2/nodes/(%s)$' % node_name_pattern):
      rlib2.R_2_nodes_name,
    re.compile(r'^/2/nodes/(%s)/tags$' % node_name_pattern):
      rlib2.R_2_nodes_name_tags,
    re.compile(r'^/2/nodes/(%s)/role$' % node_name_pattern):
      rlib2.R_2_nodes_name_role,
    re.compile(r'^/2/nodes/(%s)/evacuate$' % node_name_pattern):
      rlib2.R_2_nodes_name_evacuate,
    re.compile(r'^/2/nodes/(%s)/migrate$' % node_name_pattern):
      rlib2.R_2_nodes_name_migrate,
    re.compile(r'^/2/nodes/(%s)/storage$' % node_name_pattern):
      rlib2.R_2_nodes_name_storage,
    re.compile(r'^/2/nodes/(%s)/storage/modify$' % node_name_pattern):
      rlib2.R_2_nodes_name_storage_modify,
    re.compile(r'^/2/nodes/(%s)/storage/repair$' % node_name_pattern):
      rlib2.R_2_nodes_name_storage_repair,

    "/2/instances": rlib2.R_2_instances,
    re.compile(r'^/2/instances/(%s)$' % instance_name_pattern):
      rlib2.R_2_instances_name,
    re.compile(r'^/2/instances/(%s)/info$' % instance_name_pattern):
      rlib2.R_2_instances_name_info,
    re.compile(r'^/2/instances/(%s)/tags$' % instance_name_pattern):
      rlib2.R_2_instances_name_tags,
    re.compile(r'^/2/instances/(%s)/reboot$' % instance_name_pattern):
      rlib2.R_2_instances_name_reboot,
    re.compile(r'^/2/instances/(%s)/reinstall$' % instance_name_pattern):
      rlib2.R_2_instances_name_reinstall,
    re.compile(r'^/2/instances/(%s)/replace-disks$' % instance_name_pattern):
      rlib2.R_2_instances_name_replace_disks,
    re.compile(r'^/2/instances/(%s)/shutdown$' % instance_name_pattern):
      rlib2.R_2_instances_name_shutdown,
    re.compile(r'^/2/instances/(%s)/startup$' % instance_name_pattern):
      rlib2.R_2_instances_name_startup,
    re.compile(r'^/2/instances/(%s)/activate-disks$' % instance_name_pattern):
      rlib2.R_2_instances_name_activate_disks,
    re.compile(r'^/2/instances/(%s)/deactivate-disks$' % instance_name_pattern):
      rlib2.R_2_instances_name_deactivate_disks,
    re.compile(r'^/2/instances/(%s)/prepare-export$' % instance_name_pattern):
      rlib2.R_2_instances_name_prepare_export,
    re.compile(r'^/2/instances/(%s)/export$' % instance_name_pattern):
      rlib2.R_2_instances_name_export,
    re.compile(r'^/2/instances/(%s)/migrate$' % instance_name_pattern):
      rlib2.R_2_instances_name_migrate,
    re.compile(r'^/2/instances/(%s)/rename$' % instance_name_pattern):
      rlib2.R_2_instances_name_rename,
    re.compile(r'^/2/instances/(%s)/modify$' % instance_name_pattern):
      rlib2.R_2_instances_name_modify,

    "/2/groups": rlib2.R_2_groups,
    re.compile(r'^/2/groups/(%s)$' % group_name_pattern):
      rlib2.R_2_groups_name,
    re.compile(r'^/2/groups/(%s)/modify$' % group_name_pattern):
      rlib2.R_2_groups_name_modify,
    re.compile(r'^/2/groups/(%s)/rename$' % group_name_pattern):
      rlib2.R_2_groups_name_rename,

    "/2/jobs": rlib2.R_2_jobs,
    re.compile(r"^/2/jobs/(%s)$" % job_id_pattern):
      rlib2.R_2_jobs_id,
    re.compile(r"^/2/jobs/(%s)/wait$" % job_id_pattern):
      rlib2.R_2_jobs_id_wait,

    "/2/tags": rlib2.R_2_tags,
    "/2/info": rlib2.R_2_info,
    "/2/os": rlib2.R_2_os,
    "/2/redistribute-config": rlib2.R_2_redist_config,
    "/2/features": rlib2.R_2_features,
    }


CONNECTOR.update(GetHandlers(_NAME_PATTERN, _NAME_PATTERN, _NAME_PATTERN,
                             constants.JOB_ID_TEMPLATE))
