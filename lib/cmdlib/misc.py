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


"""Miscellaneous logical units that don't fit into any category."""

import logging
import time

from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import qlang
from ganeti import query
from ganeti import utils
from ganeti.cmdlib.base import NoHooksLU, QueryBase
from ganeti.cmdlib.common import GetWantedNodes, SupportsOob


class LUOobCommand(NoHooksLU):
  """Logical unit for OOB handling.

  """
  REQ_BGL = False
  _SKIP_MASTER = (constants.OOB_POWER_OFF, constants.OOB_POWER_CYCLE)

  def ExpandNames(self):
    """Gather locks we need.

    """
    if self.op.node_names:
      (self.op.node_uuids, self.op.node_names) = \
        GetWantedNodes(self, self.op.node_names)
      lock_node_uuids = self.op.node_uuids
    else:
      lock_node_uuids = locking.ALL_SET

    self.needed_locks = {
      locking.LEVEL_NODE: lock_node_uuids,
      }

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the node exists in the configuration
     - OOB is supported

    Any errors are signaled by raising errors.OpPrereqError.

    """
    self.nodes = []
    self.master_node_uuid = self.cfg.GetMasterNode()
    master_node_obj = self.cfg.GetNodeInfo(self.master_node_uuid)

    assert self.op.power_delay >= 0.0

    if self.op.node_uuids:
      if (self.op.command in self._SKIP_MASTER and
          master_node_obj.uuid in self.op.node_uuids):
        master_oob_handler = SupportsOob(self.cfg, master_node_obj)

        if master_oob_handler:
          additional_text = ("run '%s %s %s' if you want to operate on the"
                             " master regardless") % (master_oob_handler,
                                                      self.op.command,
                                                      master_node_obj.name)
        else:
          additional_text = "it does not support out-of-band operations"

        raise errors.OpPrereqError(("Operating on the master node %s is not"
                                    " allowed for %s; %s") %
                                   (master_node_obj.name, self.op.command,
                                    additional_text), errors.ECODE_INVAL)
    else:
      self.op.node_uuids = self.cfg.GetNodeList()
      if self.op.command in self._SKIP_MASTER:
        self.op.node_uuids.remove(master_node_obj.uuid)

    if self.op.command in self._SKIP_MASTER:
      assert master_node_obj.uuid not in self.op.node_uuids

    for node_uuid in self.op.node_uuids:
      node = self.cfg.GetNodeInfo(node_uuid)
      if node is None:
        raise errors.OpPrereqError("Node %s not found" % node_uuid,
                                   errors.ECODE_NOENT)

      self.nodes.append(node)

      if (not self.op.ignore_status and
          (self.op.command == constants.OOB_POWER_OFF and not node.offline)):
        raise errors.OpPrereqError(("Cannot power off node %s because it is"
                                    " not marked offline") % node.name,
                                   errors.ECODE_STATE)

  def Exec(self, feedback_fn):
    """Execute OOB and return result if we expect any.

    """
    ret = []

    for idx, node in enumerate(utils.NiceSort(self.nodes,
                                              key=lambda node: node.name)):
      node_entry = [(constants.RS_NORMAL, node.name)]
      ret.append(node_entry)

      oob_program = SupportsOob(self.cfg, node)

      if not oob_program:
        node_entry.append((constants.RS_UNAVAIL, None))
        continue

      logging.info("Executing out-of-band command '%s' using '%s' on %s",
                   self.op.command, oob_program, node.name)
      result = self.rpc.call_run_oob(self.master_node_uuid, oob_program,
                                     self.op.command, node.name,
                                     self.op.timeout)

      if result.fail_msg:
        self.LogWarning("Out-of-band RPC failed on node '%s': %s",
                        node.name, result.fail_msg)
        node_entry.append((constants.RS_NODATA, None))
        continue

      try:
        self._CheckPayload(result)
      except errors.OpExecError as err:
        self.LogWarning("Payload returned by node '%s' is not valid: %s",
                        node.name, err)
        node_entry.append((constants.RS_NODATA, None))
      else:
        if self.op.command == constants.OOB_HEALTH:
          # For health we should log important events
          for item, status in result.payload:
            if status in [constants.OOB_STATUS_WARNING,
                          constants.OOB_STATUS_CRITICAL]:
              self.LogWarning("Item '%s' on node '%s' has status '%s'",
                              item, node.name, status)

        if self.op.command == constants.OOB_POWER_ON:
          node.powered = True
        elif self.op.command == constants.OOB_POWER_OFF:
          node.powered = False
        elif self.op.command == constants.OOB_POWER_STATUS:
          powered = result.payload[constants.OOB_POWER_STATUS_POWERED]
          if powered != node.powered:
            logging.warning(("Recorded power state (%s) of node '%s' does not"
                             " match actual power state (%s)"), node.powered,
                            node.name, powered)

        # For configuration changing commands we should update the node
        if self.op.command in (constants.OOB_POWER_ON,
                               constants.OOB_POWER_OFF):
          self.cfg.Update(node, feedback_fn)

        node_entry.append((constants.RS_NORMAL, result.payload))

        if (self.op.command == constants.OOB_POWER_ON and
            idx < len(self.nodes) - 1):
          time.sleep(self.op.power_delay)

    return ret

  def _CheckPayload(self, result):
    """Checks if the payload is valid.

    @param result: RPC result
    @raises errors.OpExecError: If payload is not valid

    """
    errs = []
    if self.op.command == constants.OOB_HEALTH:
      if not isinstance(result.payload, list):
        errs.append("command 'health' is expected to return a list but got %s" %
                    type(result.payload))
      else:
        for item, status in result.payload:
          if status not in constants.OOB_STATUSES:
            errs.append("health item '%s' has invalid status '%s'" %
                        (item, status))

    if self.op.command == constants.OOB_POWER_STATUS:
      if not isinstance(result.payload, dict):
        errs.append("power-status is expected to return a dict but got %s" %
                    type(result.payload))

    if self.op.command in [
      constants.OOB_POWER_ON,
      constants.OOB_POWER_OFF,
      constants.OOB_POWER_CYCLE,
      ]:
      if result.payload is not None:
        errs.append("%s is expected to not return payload but got '%s'" %
                    (self.op.command, result.payload))

    if errs:
      raise errors.OpExecError("Check of out-of-band payload failed due to %s" %
                               utils.CommaJoin(errs))


class ExtStorageQuery(QueryBase):
  FIELDS = query.EXTSTORAGE_FIELDS

  def ExpandNames(self, lu):
    # Lock all nodes in shared mode
    # Temporary removal of locks, should be reverted later
    # TODO: reintroduce locks when they are lighter-weight
    lu.needed_locks = {}
    #self.share_locks[locking.LEVEL_NODE] = 1
    #self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

    # The following variables interact with _QueryBase._GetNames
    if self.names:
      self.wanted = [lu.cfg.GetNodeInfoByName(name).uuid for name in self.names]
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

  def DeclareLocks(self, lu, level):
    pass

  @staticmethod
  def _DiagnoseByProvider(rlist):
    """Remaps a per-node return list into an a per-provider per-node dictionary

    @param rlist: a map with node uuids as keys and ExtStorage objects as values

    @rtype: dict
    @return: a dictionary with extstorage providers as keys and as
        value another map, with node uuids as keys and tuples of
        (path, status, diagnose, parameters) as values, eg::

          {"provider1": {"node_uuid1": [(/usr/lib/..., True, "", [])]
                         "node_uuid2": [(/srv/..., False, "missing file")]
                         "node_uuid3": [(/srv/..., True, "", [])]
          }

    """
    all_es = {}
    # we build here the list of nodes that didn't fail the RPC (at RPC
    # level), so that nodes with a non-responding node daemon don't
    # make all OSes invalid
    good_nodes = [node_uuid for node_uuid in rlist
                  if not rlist[node_uuid].fail_msg]
    for node_uuid, nr in rlist.items():
      if nr.fail_msg or not nr.payload:
        continue
      for (name, path, status, diagnose, params) in nr.payload:
        if name not in all_es:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_es[name] = {}
          for nuuid in good_nodes:
            all_es[name][nuuid] = []
        # convert params from [name, help] to (name, help)
        params = [tuple(v) for v in params]
        all_es[name][node_uuid].append((path, status, diagnose, params))
    return all_es

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    valid_nodes = [node.uuid
                   for node in lu.cfg.GetAllNodesInfo().values()
                   if not node.offline and node.vm_capable]
    pol = self._DiagnoseByProvider(lu.rpc.call_extstorage_diagnose(valid_nodes))

    data = {}

    nodegroup_list = lu.cfg.GetNodeGroupList()

    for (es_name, es_data) in pol.items():
      # For every provider compute the nodegroup validity.
      # To do this we need to check the validity of each node in es_data
      # and then construct the corresponding nodegroup dict:
      #      { nodegroup1: status
      #        nodegroup2: status
      #      }
      ndgrp_data = {}
      for nodegroup in nodegroup_list:
        ndgrp = lu.cfg.GetNodeGroup(nodegroup)

        nodegroup_nodes = ndgrp.members
        nodegroup_name = ndgrp.name
        node_statuses = []

        for node in nodegroup_nodes:
          if node in valid_nodes:
            if es_data[node] != []:
              node_status = es_data[node][0][1]
              node_statuses.append(node_status)
            else:
              node_statuses.append(False)

        if False in node_statuses:
          ndgrp_data[nodegroup_name] = False
        else:
          ndgrp_data[nodegroup_name] = True

      # Compute the provider's parameters
      parameters = set()
      for idx, esl in enumerate(es_data.values()):
        valid = bool(esl and esl[0][1])
        if not valid:
          break

        node_params = esl[0][3]
        if idx == 0:
          # First entry
          parameters.update(node_params)
        else:
          # Filter out inconsistent values
          parameters.intersection_update(node_params)

      params = list(parameters)

      # Now fill all the info for this provider
      info = query.ExtStorageInfo(name=es_name, node_status=es_data,
                                  nodegroup_status=ndgrp_data,
                                  parameters=params)

      data[es_name] = info

    # Prepare data in requested order
    return [data[name] for name in self._GetNames(lu, list(pol), None)
            if name in data]


class LUExtStorageDiagnose(NoHooksLU):
  """Logical unit for ExtStorage diagnose/query.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.eq = ExtStorageQuery(qlang.MakeSimpleFilter("name", self.op.names),
                               self.op.output_fields, False)

  def ExpandNames(self):
    self.eq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.eq.OldStyleQuery(self)


class LURestrictedCommand(NoHooksLU):
  """Logical unit for executing restricted commands.

  """
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.nodes:
      (self.op.node_uuids, self.op.nodes) = GetWantedNodes(self, self.op.nodes)

    self.needed_locks = {
      locking.LEVEL_NODE: self.op.node_uuids,
      }
    self.share_locks = {
      locking.LEVEL_NODE: not self.op.use_locking,
      }

  def CheckPrereq(self):
    """Check prerequisites.

    """

  def Exec(self, feedback_fn):
    """Execute restricted command and return output.

    """
    owned_nodes = frozenset(self.owned_locks(locking.LEVEL_NODE))

    # Check if correct locks are held
    assert set(self.op.node_uuids).issubset(owned_nodes)

    rpcres = self.rpc.call_restricted_command(self.op.node_uuids,
                                              self.op.command)

    result = []

    for node_uuid in self.op.node_uuids:
      nres = rpcres[node_uuid]
      if nres.fail_msg:
        msg = ("Command '%s' on node '%s' failed: %s" %
               (self.op.command, self.cfg.GetNodeName(node_uuid),
                nres.fail_msg))
        result.append((False, msg))
      else:
        result.append((True, nres.payload))

    return result
