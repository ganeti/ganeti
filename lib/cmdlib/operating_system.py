#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Logical units dealing with OS."""

from ganeti import locking
from ganeti import qlang
from ganeti import query
from ganeti.cmdlib.base import QueryBase, NoHooksLU


class OsQuery(QueryBase):
  FIELDS = query.OS_FIELDS

  def ExpandNames(self, lu):
    # Lock all nodes in shared mode
    # Temporary removal of locks, should be reverted later
    # TODO: reintroduce locks when they are lighter-weight
    lu.needed_locks = {}
    #self.share_locks[locking.LEVEL_NODE] = 1
    #self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

    # The following variables interact with _QueryBase._GetNames
    if self.names:
      self.wanted = self.names
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

  def DeclareLocks(self, lu, level):
    pass

  @staticmethod
  def _DiagnoseByOS(rlist):
    """Remaps a per-node return list into a per-os per-node dictionary

    @param rlist: a map with node names as keys and OS objects as values

    @rtype: dict
    @return: a dictionary with osnames as keys and as value another
        map, with node UUIDs as keys and tuples of (path, status, diagnose,
        variants, parameters, api_versions) as values, eg::

          {"debian-etch": {"node1-uuid": [(/usr/lib/..., True, "", [], []),
                                          (/srv/..., False, "invalid api")],
                           "node2-uuid": [(/srv/..., True, "", [], [])]}
          }

    """
    all_os = {}
    # we build here the list of nodes that didn't fail the RPC (at RPC
    # level), so that nodes with a non-responding node daemon don't
    # make all OSes invalid
    good_node_uuids = [node_uuid for node_uuid in rlist
                       if not rlist[node_uuid].fail_msg]
    for node_uuid, nr in rlist.items():
      if nr.fail_msg or not nr.payload:
        continue
      for (name, path, status, diagnose, variants,
           params, api_versions, trusted) in nr.payload:
        if name not in all_os:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_os[name] = {}
          for nuuid in good_node_uuids:
            all_os[name][nuuid] = []
        # convert params from [name, help] to (name, help)
        params = [tuple(v) for v in params]
        all_os[name][node_uuid].append((path, status, diagnose, variants,
                                        params, api_versions, trusted))
    return all_os

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    valid_node_uuids = [node.uuid
                        for node in lu.cfg.GetAllNodesInfo().values()
                        if not node.offline and node.vm_capable]
    pol = self._DiagnoseByOS(lu.rpc.call_os_diagnose(valid_node_uuids))
    cluster = lu.cfg.GetClusterInfo()

    data = {}

    for (os_name, os_data) in pol.items():
      info = query.OsInfo(name=os_name, valid=True, node_status=os_data,
                          hidden=(os_name in cluster.hidden_os),
                          blacklisted=(os_name in cluster.blacklisted_os),
                          os_hvp={}, osparams={})

      variants = set()
      parameters = set()
      api_versions = set()
      trusted = True

      for idx, osl in enumerate(os_data.values()):
        info.valid = bool(info.valid and osl and osl[0][1])
        if not info.valid:
          break

        (node_variants, node_params, node_api, node_trusted) = osl[0][3:7]
        if idx == 0:
          # First entry
          variants.update(node_variants)
          parameters.update(node_params)
          api_versions.update(node_api)
        else:
          # Filter out inconsistent values
          variants.intersection_update(node_variants)
          parameters.intersection_update(node_params)
          api_versions.intersection_update(node_api)

        if not node_trusted:
          trusted = False

      info.variants = list(variants)
      info.parameters = list(parameters)
      info.api_versions = list(api_versions)
      info.trusted = trusted

      for variant in variants:
        name = "+".join([os_name, variant])
        if name in cluster.os_hvp:
          info.os_hvp[name] = cluster.os_hvp.get(name)
        if name in cluster.osparams:
          info.osparams[name] = cluster.osparams.get(name)

      data[os_name] = info

    # Prepare data in requested order
    return [data[name] for name in self._GetNames(lu, list(pol), None)
            if name in data]


class LUOsDiagnose(NoHooksLU):
  """Logical unit for OS diagnose/query.

  """
  REQ_BGL = False

  @staticmethod
  def _BuildFilter(fields, names):
    """Builds a filter for querying OSes.

    """
    name_filter = qlang.MakeSimpleFilter("name", names)

    # Legacy behaviour: Hide hidden, blacklisted or invalid OSes if the
    # respective field is not requested
    status_filter = [[qlang.OP_NOT, [qlang.OP_TRUE, fname]]
                     for fname in ["hidden", "blacklisted"]
                     if fname not in fields]
    if "valid" not in fields:
      status_filter.append([qlang.OP_TRUE, "valid"])

    if status_filter:
      status_filter.insert(0, qlang.OP_AND)
    else:
      status_filter = None

    if name_filter and status_filter:
      return [qlang.OP_AND, name_filter, status_filter]
    elif name_filter:
      return name_filter
    else:
      return status_filter

  def CheckArguments(self):
    self.oq = OsQuery(self._BuildFilter(self.op.output_fields, self.op.names),
                      self.op.output_fields, False)

  def ExpandNames(self):
    self.oq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.oq.OldStyleQuery(self)
