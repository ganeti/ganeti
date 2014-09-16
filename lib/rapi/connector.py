#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Remote API connection map.

"""

# pylint: disable=C0103

# C0103: Invalid name, since the R_* names are not conforming

import re
import urlparse

from ganeti import constants
from ganeti import http
from ganeti import utils

from ganeti.rapi import rlib2


_NAME_PATTERN = r"[\w\._-]+"
_DISK_PATTERN = r"\d+"

# the connection map is created at the end of this file
CONNECTOR = {}


class Mapper(object):
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
    if "?" in uri:
      (path, query) = uri.split("?", 1)
      args = urlparse.parse_qs(query)
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


def _ConvertPattern(value):
  """Converts URI pattern into a regular expression group.

  Used by L{_CompileHandlerPath}.

  """
  if isinstance(value, UriPattern):
    return "(%s)" % value.content
  else:
    return value


def _CompileHandlerPath(*args):
  """Compiles path for RAPI resource into regular expression.

  @return: Compiled regular expression object

  """
  return re.compile("^%s$" % "".join(map(_ConvertPattern, args)))


class UriPattern(object):
  __slots__ = [
    "content",
    ]

  def __init__(self, content):
    self.content = content


def GetHandlers(node_name_pattern, instance_name_pattern,
                group_name_pattern, network_name_pattern,
                job_id_pattern, disk_pattern, filter_pattern,
                query_res_pattern,
                translate=None):
  """Returns all supported resources and their handlers.

  C{node_name_pattern} and the other C{*_pattern} parameters are wrapped in
  L{UriPattern} and, if used in a URI, passed to the function specified using
  C{translate}. C{translate} receives 1..N parameters which are either plain
  strings or instances of L{UriPattern} and returns a dictionary key suitable
  for the caller of C{GetHandlers}. The default implementation in
  L{_CompileHandlerPath} returns a compiled regular expression in which each
  pattern is a group.

  @rtype: dict

  """
  if translate is None:
    translate_fn = _CompileHandlerPath
  else:
    translate_fn = translate

  node_name = UriPattern(node_name_pattern)
  instance_name = UriPattern(instance_name_pattern)
  group_name = UriPattern(group_name_pattern)
  network_name = UriPattern(network_name_pattern)
  job_id = UriPattern(job_id_pattern)
  disk = UriPattern(disk_pattern)
  filter_uuid = UriPattern(filter_pattern)
  query_res = UriPattern(query_res_pattern)

  # Important note: New resources should always be added under /2. During a
  # discussion in July 2010 it was decided that having per-resource versions
  # is more flexible and future-compatible than versioning the whole remote
  # API.
  # TODO: Consider a different data structure where all keys are of the same
  # type. Strings are faster to look up in a dictionary than iterating and
  # matching regular expressions, therefore maybe two separate dictionaries
  # should be used.
  return {
    "/": rlib2.R_root,
    "/2": rlib2.R_2,

    "/version": rlib2.R_version,

    "/2/nodes": rlib2.R_2_nodes,

    translate_fn("/2/nodes/", node_name):
      rlib2.R_2_nodes_name,
    translate_fn("/2/nodes/", node_name, "/powercycle"):
      rlib2.R_2_nodes_name_powercycle,
    translate_fn("/2/nodes/", node_name, "/tags"):
      rlib2.R_2_nodes_name_tags,
    translate_fn("/2/nodes/", node_name, "/role"):
      rlib2.R_2_nodes_name_role,
    translate_fn("/2/nodes/", node_name, "/evacuate"):
      rlib2.R_2_nodes_name_evacuate,
    translate_fn("/2/nodes/", node_name, "/migrate"):
      rlib2.R_2_nodes_name_migrate,
    translate_fn("/2/nodes/", node_name, "/modify"):
      rlib2.R_2_nodes_name_modify,
    translate_fn("/2/nodes/", node_name, "/storage"):
      rlib2.R_2_nodes_name_storage,
    translate_fn("/2/nodes/", node_name, "/storage/modify"):
      rlib2.R_2_nodes_name_storage_modify,
    translate_fn("/2/nodes/", node_name, "/storage/repair"):
      rlib2.R_2_nodes_name_storage_repair,

    "/2/instances": rlib2.R_2_instances,
    translate_fn("/2/instances/", instance_name):
      rlib2.R_2_instances_name,
    translate_fn("/2/instances/", instance_name, "/info"):
      rlib2.R_2_instances_name_info,
    translate_fn("/2/instances/", instance_name, "/tags"):
      rlib2.R_2_instances_name_tags,
    translate_fn("/2/instances/", instance_name, "/reboot"):
      rlib2.R_2_instances_name_reboot,
    translate_fn("/2/instances/", instance_name, "/reinstall"):
      rlib2.R_2_instances_name_reinstall,
    translate_fn("/2/instances/", instance_name, "/replace-disks"):
      rlib2.R_2_instances_name_replace_disks,
    translate_fn("/2/instances/", instance_name, "/shutdown"):
      rlib2.R_2_instances_name_shutdown,
    translate_fn("/2/instances/", instance_name, "/startup"):
      rlib2.R_2_instances_name_startup,
    translate_fn("/2/instances/", instance_name, "/activate-disks"):
      rlib2.R_2_instances_name_activate_disks,
    translate_fn("/2/instances/", instance_name, "/deactivate-disks"):
      rlib2.R_2_instances_name_deactivate_disks,
    translate_fn("/2/instances/", instance_name, "/recreate-disks"):
      rlib2.R_2_instances_name_recreate_disks,
    translate_fn("/2/instances/", instance_name, "/prepare-export"):
      rlib2.R_2_instances_name_prepare_export,
    translate_fn("/2/instances/", instance_name, "/export"):
      rlib2.R_2_instances_name_export,
    translate_fn("/2/instances/", instance_name, "/migrate"):
      rlib2.R_2_instances_name_migrate,
    translate_fn("/2/instances/", instance_name, "/failover"):
      rlib2.R_2_instances_name_failover,
    translate_fn("/2/instances/", instance_name, "/rename"):
      rlib2.R_2_instances_name_rename,
    translate_fn("/2/instances/", instance_name, "/modify"):
      rlib2.R_2_instances_name_modify,
    translate_fn("/2/instances/", instance_name, "/disk/", disk, "/grow"):
      rlib2.R_2_instances_name_disk_grow,
    translate_fn("/2/instances/", instance_name, "/console"):
      rlib2.R_2_instances_name_console,

    "/2/networks": rlib2.R_2_networks,
    translate_fn("/2/networks/", network_name):
      rlib2.R_2_networks_name,
    translate_fn("/2/networks/", network_name, "/connect"):
      rlib2.R_2_networks_name_connect,
    translate_fn("/2/networks/", network_name, "/disconnect"):
      rlib2.R_2_networks_name_disconnect,
    translate_fn("/2/networks/", network_name, "/modify"):
      rlib2.R_2_networks_name_modify,
    translate_fn("/2/networks/", network_name, "/tags"):
      rlib2.R_2_networks_name_tags,

    "/2/groups": rlib2.R_2_groups,
    translate_fn("/2/groups/", group_name):
      rlib2.R_2_groups_name,
    translate_fn("/2/groups/", group_name, "/modify"):
      rlib2.R_2_groups_name_modify,
    translate_fn("/2/groups/", group_name, "/rename"):
      rlib2.R_2_groups_name_rename,
    translate_fn("/2/groups/", group_name, "/assign-nodes"):
      rlib2.R_2_groups_name_assign_nodes,
    translate_fn("/2/groups/", group_name, "/tags"):
      rlib2.R_2_groups_name_tags,

    "/2/jobs": rlib2.R_2_jobs,
    translate_fn("/2/jobs/", job_id):
      rlib2.R_2_jobs_id,
    translate_fn("/2/jobs/", job_id, "/wait"):
      rlib2.R_2_jobs_id_wait,

    "/2/instances-multi-alloc": rlib2.R_2_instances_multi_alloc,
    "/2/tags": rlib2.R_2_tags,
    "/2/info": rlib2.R_2_info,
    "/2/os": rlib2.R_2_os,
    "/2/redistribute-config": rlib2.R_2_redist_config,
    "/2/features": rlib2.R_2_features,
    "/2/modify": rlib2.R_2_cluster_modify,

    translate_fn("/2/query/", query_res):
      rlib2.R_2_query,
    translate_fn("/2/query/", query_res, "/fields"):
      rlib2.R_2_query_fields,

    "/2/filters": rlib2.R_2_filters,
    translate_fn("/2/filters/", filter_uuid):
      rlib2.R_2_filters_uuid,
    }


CONNECTOR.update(GetHandlers(_NAME_PATTERN, _NAME_PATTERN,
                             _NAME_PATTERN, _NAME_PATTERN,
                             constants.JOB_ID_TEMPLATE, _DISK_PATTERN,
                             _NAME_PATTERN, _NAME_PATTERN))
