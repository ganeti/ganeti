#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Module implementing the master-side code."""

# pylint: disable=W0201,C0302

# W0201 since most LU attributes are defined in CheckPrereq or similar
# functions

# C0302: since we have waaaay too many lines in this module

import time
import logging
import OpenSSL

from ganeti import utils
from ganeti import errors
from ganeti import locking
from ganeti import constants
from ganeti import compat
from ganeti import masterd
from ganeti import query
from ganeti import qlang

from ganeti.cmdlib.base import ResultWithJobs, LogicalUnit, NoHooksLU, \
  Tasklet, _QueryBase
from ganeti.cmdlib.common import INSTANCE_DOWN, INSTANCE_ONLINE, \
  INSTANCE_NOT_RUNNING, CAN_CHANGE_INSTANCE_OFFLINE, \
  _ExpandInstanceName, _ExpandItemName, \
  _ExpandNodeName, _ShareAll, _CheckNodeGroupInstances, _GetWantedNodes, \
  _GetWantedInstances, _RunPostHook, _RedistributeAncillaryFiles, \
  _MergeAndVerifyHvState, _MergeAndVerifyDiskState, _GetUpdatedIPolicy, \
  _ComputeNewInstanceViolations, _GetUpdatedParams, _CheckOSParams, \
  _CheckHVParams, _AdjustCandidatePool, _CheckNodePVs, \
  _ComputeIPolicyInstanceViolation, _AnnotateDiskParams, _SupportsOob, \
  _ComputeIPolicySpecViolation, _GetDefaultIAllocator, \
  _CheckInstancesNodeGroups, _LoadNodeEvacResult, _MapInstanceDisksToNodes, \
  _CheckInstanceNodeGroups, _CheckParamsNotGlobal, \
  _IsExclusiveStorageEnabledNode, _CheckInstanceState, \
  _CheckIAllocatorOrNode, _FindFaultyInstanceDisks, _CheckNodeOnline
from ganeti.cmdlib.instance_utils import _AssembleInstanceDisks, \
  _BuildInstanceHookEnvByObject, _GetClusterDomainSecret, \
  _CheckNodeNotDrained, _RemoveDisks, _ShutdownInstanceDisks, \
  _StartInstanceDisks, _RemoveInstance

from ganeti.cmdlib.cluster import LUClusterActivateMasterIp, \
  LUClusterDeactivateMasterIp, LUClusterConfigQuery, LUClusterDestroy, \
  LUClusterPostInit, _ClusterQuery, LUClusterQuery, LUClusterRedistConf, \
  LUClusterRename, LUClusterRepairDiskSizes, LUClusterSetParams, \
  LUClusterVerify, LUClusterVerifyConfig, LUClusterVerifyGroup, \
  LUClusterVerifyDisks
from ganeti.cmdlib.group import LUGroupAdd, LUGroupAssignNodes, \
  _GroupQuery, LUGroupQuery, LUGroupSetParams, LUGroupRemove, \
  LUGroupRename, LUGroupEvacuate, LUGroupVerifyDisks
from ganeti.cmdlib.node import LUNodeAdd, LUNodeSetParams, \
  LUNodePowercycle, LUNodeEvacuate, LUNodeMigrate, LUNodeModifyStorage, \
  _NodeQuery, LUNodeQuery, LUNodeQueryvols, LUNodeQueryStorage, \
  LUNodeRemove, LURepairNodeStorage
from ganeti.cmdlib.instance import LUInstanceCreate, LUInstanceRename, \
  LUInstanceRemove, LUInstanceMove, _InstanceQuery, LUInstanceQuery, \
  LUInstanceQueryData, LUInstanceRecreateDisks, LUInstanceGrowDisk, \
  LUInstanceReplaceDisks, LUInstanceActivateDisks, \
  LUInstanceDeactivateDisks, LUInstanceStartup, LUInstanceShutdown, \
  LUInstanceReinstall, LUInstanceReboot, LUInstanceConsole, \
  LUInstanceFailover, LUInstanceMigrate, LUInstanceMultiAlloc, \
  LUInstanceSetParams, LUInstanceChangeGroup
from ganeti.cmdlib.tags import LUTagsGet, LUTagsSearch, LUTagsSet, LUTagsDel
from ganeti.cmdlib.network import LUNetworkAdd, LUNetworkRemove, \
  LUNetworkSetParams, _NetworkQuery, LUNetworkQuery, LUNetworkConnect, \
  LUNetworkDisconnect
from ganeti.cmdlib.test import LUTestDelay, LUTestJqueue, LUTestAllocator


class LUOobCommand(NoHooksLU):
  """Logical unit for OOB handling.

  """
  REQ_BGL = False
  _SKIP_MASTER = (constants.OOB_POWER_OFF, constants.OOB_POWER_CYCLE)

  def ExpandNames(self):
    """Gather locks we need.

    """
    if self.op.node_names:
      self.op.node_names = _GetWantedNodes(self, self.op.node_names)
      lock_names = self.op.node_names
    else:
      lock_names = locking.ALL_SET

    self.needed_locks = {
      locking.LEVEL_NODE: lock_names,
      }

    self.share_locks[locking.LEVEL_NODE_ALLOC] = 1

    if not self.op.node_names:
      # Acquire node allocation lock only if all nodes are affected
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def CheckPrereq(self):
    """Check prerequisites.

    This checks:
     - the node exists in the configuration
     - OOB is supported

    Any errors are signaled by raising errors.OpPrereqError.

    """
    self.nodes = []
    self.master_node = self.cfg.GetMasterNode()

    assert self.op.power_delay >= 0.0

    if self.op.node_names:
      if (self.op.command in self._SKIP_MASTER and
          self.master_node in self.op.node_names):
        master_node_obj = self.cfg.GetNodeInfo(self.master_node)
        master_oob_handler = _SupportsOob(self.cfg, master_node_obj)

        if master_oob_handler:
          additional_text = ("run '%s %s %s' if you want to operate on the"
                             " master regardless") % (master_oob_handler,
                                                      self.op.command,
                                                      self.master_node)
        else:
          additional_text = "it does not support out-of-band operations"

        raise errors.OpPrereqError(("Operating on the master node %s is not"
                                    " allowed for %s; %s") %
                                   (self.master_node, self.op.command,
                                    additional_text), errors.ECODE_INVAL)
    else:
      self.op.node_names = self.cfg.GetNodeList()
      if self.op.command in self._SKIP_MASTER:
        self.op.node_names.remove(self.master_node)

    if self.op.command in self._SKIP_MASTER:
      assert self.master_node not in self.op.node_names

    for (node_name, node) in self.cfg.GetMultiNodeInfo(self.op.node_names):
      if node is None:
        raise errors.OpPrereqError("Node %s not found" % node_name,
                                   errors.ECODE_NOENT)
      else:
        self.nodes.append(node)

      if (not self.op.ignore_status and
          (self.op.command == constants.OOB_POWER_OFF and not node.offline)):
        raise errors.OpPrereqError(("Cannot power off node %s because it is"
                                    " not marked offline") % node_name,
                                   errors.ECODE_STATE)

  def Exec(self, feedback_fn):
    """Execute OOB and return result if we expect any.

    """
    master_node = self.master_node
    ret = []

    for idx, node in enumerate(utils.NiceSort(self.nodes,
                                              key=lambda node: node.name)):
      node_entry = [(constants.RS_NORMAL, node.name)]
      ret.append(node_entry)

      oob_program = _SupportsOob(self.cfg, node)

      if not oob_program:
        node_entry.append((constants.RS_UNAVAIL, None))
        continue

      logging.info("Executing out-of-band command '%s' using '%s' on %s",
                   self.op.command, oob_program, node.name)
      result = self.rpc.call_run_oob(master_node, oob_program,
                                     self.op.command, node.name,
                                     self.op.timeout)

      if result.fail_msg:
        self.LogWarning("Out-of-band RPC failed on node '%s': %s",
                        node.name, result.fail_msg)
        node_entry.append((constants.RS_NODATA, None))
      else:
        try:
          self._CheckPayload(result)
        except errors.OpExecError, err:
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


class _OsQuery(_QueryBase):
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
    """Remaps a per-node return list into an a per-os per-node dictionary

    @param rlist: a map with node names as keys and OS objects as values

    @rtype: dict
    @return: a dictionary with osnames as keys and as value another
        map, with nodes as keys and tuples of (path, status, diagnose,
        variants, parameters, api_versions) as values, eg::

          {"debian-etch": {"node1": [(/usr/lib/..., True, "", [], []),
                                     (/srv/..., False, "invalid api")],
                           "node2": [(/srv/..., True, "", [], [])]}
          }

    """
    all_os = {}
    # we build here the list of nodes that didn't fail the RPC (at RPC
    # level), so that nodes with a non-responding node daemon don't
    # make all OSes invalid
    good_nodes = [node_name for node_name in rlist
                  if not rlist[node_name].fail_msg]
    for node_name, nr in rlist.items():
      if nr.fail_msg or not nr.payload:
        continue
      for (name, path, status, diagnose, variants,
           params, api_versions) in nr.payload:
        if name not in all_os:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_os[name] = {}
          for nname in good_nodes:
            all_os[name][nname] = []
        # convert params from [name, help] to (name, help)
        params = [tuple(v) for v in params]
        all_os[name][node_name].append((path, status, diagnose,
                                        variants, params, api_versions))
    return all_os

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    valid_nodes = [node.name
                   for node in lu.cfg.GetAllNodesInfo().values()
                   if not node.offline and node.vm_capable]
    pol = self._DiagnoseByOS(lu.rpc.call_os_diagnose(valid_nodes))
    cluster = lu.cfg.GetClusterInfo()

    data = {}

    for (os_name, os_data) in pol.items():
      info = query.OsInfo(name=os_name, valid=True, node_status=os_data,
                          hidden=(os_name in cluster.hidden_os),
                          blacklisted=(os_name in cluster.blacklisted_os))

      variants = set()
      parameters = set()
      api_versions = set()

      for idx, osl in enumerate(os_data.values()):
        info.valid = bool(info.valid and osl and osl[0][1])
        if not info.valid:
          break

        (node_variants, node_params, node_api) = osl[0][3:6]
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

      info.variants = list(variants)
      info.parameters = list(parameters)
      info.api_versions = list(api_versions)

      data[os_name] = info

    # Prepare data in requested order
    return [data[name] for name in self._GetNames(lu, pol.keys(), None)
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
    self.oq = _OsQuery(self._BuildFilter(self.op.output_fields, self.op.names),
                       self.op.output_fields, False)

  def ExpandNames(self):
    self.oq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.oq.OldStyleQuery(self)


class _ExtStorageQuery(_QueryBase):
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
      self.wanted = self.names
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

  def DeclareLocks(self, lu, level):
    pass

  @staticmethod
  def _DiagnoseByProvider(rlist):
    """Remaps a per-node return list into an a per-provider per-node dictionary

    @param rlist: a map with node names as keys and ExtStorage objects as values

    @rtype: dict
    @return: a dictionary with extstorage providers as keys and as
        value another map, with nodes as keys and tuples of
        (path, status, diagnose, parameters) as values, eg::

          {"provider1": {"node1": [(/usr/lib/..., True, "", [])]
                         "node2": [(/srv/..., False, "missing file")]
                         "node3": [(/srv/..., True, "", [])]
          }

    """
    all_es = {}
    # we build here the list of nodes that didn't fail the RPC (at RPC
    # level), so that nodes with a non-responding node daemon don't
    # make all OSes invalid
    good_nodes = [node_name for node_name in rlist
                  if not rlist[node_name].fail_msg]
    for node_name, nr in rlist.items():
      if nr.fail_msg or not nr.payload:
        continue
      for (name, path, status, diagnose, params) in nr.payload:
        if name not in all_es:
          # build a list of nodes for this os containing empty lists
          # for each node in node_list
          all_es[name] = {}
          for nname in good_nodes:
            all_es[name][nname] = []
        # convert params from [name, help] to (name, help)
        params = [tuple(v) for v in params]
        all_es[name][node_name].append((path, status, diagnose, params))
    return all_es

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    valid_nodes = [node.name
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
    return [data[name] for name in self._GetNames(lu, pol.keys(), None)
            if name in data]


class LUExtStorageDiagnose(NoHooksLU):
  """Logical unit for ExtStorage diagnose/query.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.eq = _ExtStorageQuery(qlang.MakeSimpleFilter("name", self.op.names),
                               self.op.output_fields, False)

  def ExpandNames(self):
    self.eq.ExpandNames(self)

  def Exec(self, feedback_fn):
    return self.eq.OldStyleQuery(self)


class LUQuery(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    qcls = _GetQueryImplementation(self.op.what)

    self.impl = qcls(self.op.qfilter, self.op.fields, self.op.use_locking)

  def ExpandNames(self):
    self.impl.ExpandNames(self)

  def DeclareLocks(self, level):
    self.impl.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    return self.impl.NewStyleQuery(self)


class LUQueryFields(NoHooksLU):
  """Query for resources/items of a certain kind.

  """
  # pylint: disable=W0142
  REQ_BGL = False

  def CheckArguments(self):
    self.qcls = _GetQueryImplementation(self.op.what)

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    return query.QueryFields(self.qcls.FIELDS, self.op.fields)


class LUBackupQuery(NoHooksLU):
  """Query the exports list

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.expq = _ExportQuery(qlang.MakeSimpleFilter("node", self.op.nodes),
                             ["node", "export"], self.op.use_locking)

  def ExpandNames(self):
    self.expq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.expq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    result = {}

    for (node, expname) in self.expq.OldStyleQuery(self):
      if expname is None:
        result[node] = False
      else:
        result.setdefault(node, []).append(expname)

    return result


class _ExportQuery(_QueryBase):
  FIELDS = query.EXPORT_FIELDS

  #: The node name is not a unique key for this query
  SORT_FIELD = "node"

  def ExpandNames(self, lu):
    lu.needed_locks = {}

    # The following variables interact with _QueryBase._GetNames
    if self.names:
      self.wanted = _GetWantedNodes(lu, self.names)
    else:
      self.wanted = locking.ALL_SET

    self.do_locking = self.use_locking

    if self.do_locking:
      lu.share_locks = _ShareAll()
      lu.needed_locks = {
        locking.LEVEL_NODE: self.wanted,
        }

      if not self.names:
        lu.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    # Locking is not used
    # TODO
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

    nodes = self._GetNames(lu, lu.cfg.GetNodeList(), locking.LEVEL_NODE)

    result = []

    for (node, nres) in lu.rpc.call_export_list(nodes).items():
      if nres.fail_msg:
        result.append((node, None))
      else:
        result.extend((node, expname) for expname in nres.payload)

    return result


class LUBackupPrepare(NoHooksLU):
  """Prepares an instance for an export and returns useful information.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def CheckPrereq(self):
    """Check prerequisites.

    """
    instance_name = self.op.instance_name

    self.instance = self.cfg.GetInstanceInfo(instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

    self._cds = _GetClusterDomainSecret()

  def Exec(self, feedback_fn):
    """Prepares an instance for an export.

    """
    instance = self.instance

    if self.op.mode == constants.EXPORT_MODE_REMOTE:
      salt = utils.GenerateSecret(8)

      feedback_fn("Generating X509 certificate on %s" % instance.primary_node)
      result = self.rpc.call_x509_cert_create(instance.primary_node,
                                              constants.RIE_CERT_VALIDITY)
      result.Raise("Can't create X509 key and certificate on %s" % result.node)

      (name, cert_pem) = result.payload

      cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                             cert_pem)

      return {
        "handshake": masterd.instance.ComputeRemoteExportHandshake(self._cds),
        "x509_key_name": (name, utils.Sha1Hmac(self._cds, name, salt=salt),
                          salt),
        "x509_ca": utils.SignX509Certificate(cert, self._cds, salt),
        }

    return None


class LUBackupExport(LogicalUnit):
  """Export an instance to an image in the cluster.

  """
  HPATH = "instance-export"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    """Check the arguments.

    """
    self.x509_key_name = self.op.x509_key_name
    self.dest_x509_ca_pem = self.op.destination_x509_ca

    if self.op.mode == constants.EXPORT_MODE_REMOTE:
      if not self.x509_key_name:
        raise errors.OpPrereqError("Missing X509 key name for encryption",
                                   errors.ECODE_INVAL)

      if not self.dest_x509_ca_pem:
        raise errors.OpPrereqError("Missing destination X509 CA",
                                   errors.ECODE_INVAL)

  def ExpandNames(self):
    self._ExpandAndLockInstance()

    # Lock all nodes for local exports
    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      # FIXME: lock only instance primary and destination node
      #
      # Sad but true, for now we have do lock all nodes, as we don't know where
      # the previous export might be, and in this LU we search for it and
      # remove it from its current node. In the future we could fix this by:
      #  - making a tasklet to search (share-lock all), then create the
      #    new one, then one to remove, after
      #  - removing the removal operation altogether
      self.needed_locks[locking.LEVEL_NODE] = locking.ALL_SET

      # Allocations should be stopped while this LU runs with node locks, but
      # it doesn't have to be exclusive
      self.share_locks[locking.LEVEL_NODE_ALLOC] = 1
      self.needed_locks[locking.LEVEL_NODE_ALLOC] = locking.ALL_SET

  def DeclareLocks(self, level):
    """Last minute lock declaration."""
    # All nodes are locked anyway, so nothing to do here.

  def BuildHooksEnv(self):
    """Build hooks env.

    This will run on the master, primary node and target node.

    """
    env = {
      "EXPORT_MODE": self.op.mode,
      "EXPORT_NODE": self.op.target_node,
      "EXPORT_DO_SHUTDOWN": self.op.shutdown,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      # TODO: Generic function for boolean env variables
      "REMOVE_INSTANCE": str(bool(self.op.remove_instance)),
      }

    env.update(_BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode(), self.instance.primary_node]

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      nl.append(self.op.target_node)

    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance and node names are valid.

    """
    instance_name = self.op.instance_name

    self.instance = self.cfg.GetInstanceInfo(instance_name)
    assert self.instance is not None, \
          "Cannot retrieve locked instance %s" % self.op.instance_name
    _CheckNodeOnline(self, self.instance.primary_node)

    if (self.op.remove_instance and
        self.instance.admin_state == constants.ADMINST_UP and
        not self.op.shutdown):
      raise errors.OpPrereqError("Can not remove instance without shutting it"
                                 " down before", errors.ECODE_STATE)

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      self.op.target_node = _ExpandNodeName(self.cfg, self.op.target_node)
      self.dst_node = self.cfg.GetNodeInfo(self.op.target_node)
      assert self.dst_node is not None

      _CheckNodeOnline(self, self.dst_node.name)
      _CheckNodeNotDrained(self, self.dst_node.name)

      self._cds = None
      self.dest_disk_info = None
      self.dest_x509_ca = None

    elif self.op.mode == constants.EXPORT_MODE_REMOTE:
      self.dst_node = None

      if len(self.op.target_node) != len(self.instance.disks):
        raise errors.OpPrereqError(("Received destination information for %s"
                                    " disks, but instance %s has %s disks") %
                                   (len(self.op.target_node), instance_name,
                                    len(self.instance.disks)),
                                   errors.ECODE_INVAL)

      cds = _GetClusterDomainSecret()

      # Check X509 key name
      try:
        (key_name, hmac_digest, hmac_salt) = self.x509_key_name
      except (TypeError, ValueError), err:
        raise errors.OpPrereqError("Invalid data for X509 key name: %s" % err,
                                   errors.ECODE_INVAL)

      if not utils.VerifySha1Hmac(cds, key_name, hmac_digest, salt=hmac_salt):
        raise errors.OpPrereqError("HMAC for X509 key name is wrong",
                                   errors.ECODE_INVAL)

      # Load and verify CA
      try:
        (cert, _) = utils.LoadSignedX509Certificate(self.dest_x509_ca_pem, cds)
      except OpenSSL.crypto.Error, err:
        raise errors.OpPrereqError("Unable to load destination X509 CA (%s)" %
                                   (err, ), errors.ECODE_INVAL)

      (errcode, msg) = utils.VerifyX509Certificate(cert, None, None)
      if errcode is not None:
        raise errors.OpPrereqError("Invalid destination X509 CA (%s)" %
                                   (msg, ), errors.ECODE_INVAL)

      self.dest_x509_ca = cert

      # Verify target information
      disk_info = []
      for idx, disk_data in enumerate(self.op.target_node):
        try:
          (host, port, magic) = \
            masterd.instance.CheckRemoteExportDiskInfo(cds, idx, disk_data)
        except errors.GenericError, err:
          raise errors.OpPrereqError("Target info for disk %s: %s" %
                                     (idx, err), errors.ECODE_INVAL)

        disk_info.append((host, port, magic))

      assert len(disk_info) == len(self.op.target_node)
      self.dest_disk_info = disk_info

    else:
      raise errors.ProgrammerError("Unhandled export mode %r" %
                                   self.op.mode)

    # instance disk type verification
    # TODO: Implement export support for file-based disks
    for disk in self.instance.disks:
      if disk.dev_type == constants.LD_FILE:
        raise errors.OpPrereqError("Export not supported for instances with"
                                   " file-based disks", errors.ECODE_INVAL)

  def _CleanupExports(self, feedback_fn):
    """Removes exports of current instance from all other nodes.

    If an instance in a cluster with nodes A..D was exported to node C, its
    exports will be removed from the nodes A, B and D.

    """
    assert self.op.mode != constants.EXPORT_MODE_REMOTE

    nodelist = self.cfg.GetNodeList()
    nodelist.remove(self.dst_node.name)

    # on one-node clusters nodelist will be empty after the removal
    # if we proceed the backup would be removed because OpBackupQuery
    # substitutes an empty list with the full cluster node list.
    iname = self.instance.name
    if nodelist:
      feedback_fn("Removing old exports for instance %s" % iname)
      exportlist = self.rpc.call_export_list(nodelist)
      for node in exportlist:
        if exportlist[node].fail_msg:
          continue
        if iname in exportlist[node].payload:
          msg = self.rpc.call_export_remove(node, iname).fail_msg
          if msg:
            self.LogWarning("Could not remove older export for instance %s"
                            " on node %s: %s", iname, node, msg)

  def Exec(self, feedback_fn):
    """Export an instance to an image in the cluster.

    """
    assert self.op.mode in constants.EXPORT_MODES

    instance = self.instance
    src_node = instance.primary_node

    if self.op.shutdown:
      # shutdown the instance, but not the disks
      feedback_fn("Shutting down instance %s" % instance.name)
      result = self.rpc.call_instance_shutdown(src_node, instance,
                                               self.op.shutdown_timeout,
                                               self.op.reason)
      # TODO: Maybe ignore failures if ignore_remove_failures is set
      result.Raise("Could not shutdown instance %s on"
                   " node %s" % (instance.name, src_node))

    # set the disks ID correctly since call_instance_start needs the
    # correct drbd minor to create the symlinks
    for disk in instance.disks:
      self.cfg.SetDiskID(disk, src_node)

    activate_disks = (instance.admin_state != constants.ADMINST_UP)

    if activate_disks:
      # Activate the instance disks if we'exporting a stopped instance
      feedback_fn("Activating disks for %s" % instance.name)
      _StartInstanceDisks(self, instance, None)

    try:
      helper = masterd.instance.ExportInstanceHelper(self, feedback_fn,
                                                     instance)

      helper.CreateSnapshots()
      try:
        if (self.op.shutdown and
            instance.admin_state == constants.ADMINST_UP and
            not self.op.remove_instance):
          assert not activate_disks
          feedback_fn("Starting instance %s" % instance.name)
          result = self.rpc.call_instance_start(src_node,
                                                (instance, None, None), False,
                                                 self.op.reason)
          msg = result.fail_msg
          if msg:
            feedback_fn("Failed to start instance: %s" % msg)
            _ShutdownInstanceDisks(self, instance)
            raise errors.OpExecError("Could not start instance: %s" % msg)

        if self.op.mode == constants.EXPORT_MODE_LOCAL:
          (fin_resu, dresults) = helper.LocalExport(self.dst_node)
        elif self.op.mode == constants.EXPORT_MODE_REMOTE:
          connect_timeout = constants.RIE_CONNECT_TIMEOUT
          timeouts = masterd.instance.ImportExportTimeouts(connect_timeout)

          (key_name, _, _) = self.x509_key_name

          dest_ca_pem = \
            OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM,
                                            self.dest_x509_ca)

          (fin_resu, dresults) = helper.RemoteExport(self.dest_disk_info,
                                                     key_name, dest_ca_pem,
                                                     timeouts)
      finally:
        helper.Cleanup()

      # Check for backwards compatibility
      assert len(dresults) == len(instance.disks)
      assert compat.all(isinstance(i, bool) for i in dresults), \
             "Not all results are boolean: %r" % dresults

    finally:
      if activate_disks:
        feedback_fn("Deactivating disks for %s" % instance.name)
        _ShutdownInstanceDisks(self, instance)

    if not (compat.all(dresults) and fin_resu):
      failures = []
      if not fin_resu:
        failures.append("export finalization")
      if not compat.all(dresults):
        fdsk = utils.CommaJoin(idx for (idx, dsk) in enumerate(dresults)
                               if not dsk)
        failures.append("disk export: disk(s) %s" % fdsk)

      raise errors.OpExecError("Export failed, errors in %s" %
                               utils.CommaJoin(failures))

    # At this point, the export was successful, we can cleanup/finish

    # Remove instance if requested
    if self.op.remove_instance:
      feedback_fn("Removing instance %s" % instance.name)
      _RemoveInstance(self, feedback_fn, instance,
                      self.op.ignore_remove_failures)

    if self.op.mode == constants.EXPORT_MODE_LOCAL:
      self._CleanupExports(feedback_fn)

    return fin_resu, dresults


class LUBackupRemove(NoHooksLU):
  """Remove exports related to the named instance.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      # We need all nodes to be locked in order for RemoveExport to work, but
      # we don't need to lock the instance itself, as nothing will happen to it
      # (and we can remove exports also for a removed instance)
      locking.LEVEL_NODE: locking.ALL_SET,

      # Removing backups is quick, so blocking allocations is justified
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
      }

    # Allocations should be stopped while this LU runs with node locks, but it
    # doesn't have to be exclusive
    self.share_locks[locking.LEVEL_NODE_ALLOC] = 1

  def Exec(self, feedback_fn):
    """Remove any export.

    """
    instance_name = self.cfg.ExpandInstanceName(self.op.instance_name)
    # If the instance was not found we'll try with the name that was passed in.
    # This will only work if it was an FQDN, though.
    fqdn_warn = False
    if not instance_name:
      fqdn_warn = True
      instance_name = self.op.instance_name

    locked_nodes = self.owned_locks(locking.LEVEL_NODE)
    exportlist = self.rpc.call_export_list(locked_nodes)
    found = False
    for node in exportlist:
      msg = exportlist[node].fail_msg
      if msg:
        self.LogWarning("Failed to query node %s (continuing): %s", node, msg)
        continue
      if instance_name in exportlist[node].payload:
        found = True
        result = self.rpc.call_export_remove(node, instance_name)
        msg = result.fail_msg
        if msg:
          logging.error("Could not remove export for instance %s"
                        " on node %s: %s", instance_name, node, msg)

    if fqdn_warn and not found:
      feedback_fn("Export not found. If trying to remove an export belonging"
                  " to a deleted instance please use its Fully Qualified"
                  " Domain Name.")


class LURestrictedCommand(NoHooksLU):
  """Logical unit for executing restricted commands.

  """
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.nodes:
      self.op.nodes = _GetWantedNodes(self, self.op.nodes)

    self.needed_locks = {
      locking.LEVEL_NODE: self.op.nodes,
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
    assert set(self.op.nodes).issubset(owned_nodes)

    rpcres = self.rpc.call_restricted_command(self.op.nodes, self.op.command)

    result = []

    for node_name in self.op.nodes:
      nres = rpcres[node_name]
      if nres.fail_msg:
        msg = ("Command '%s' on node '%s' failed: %s" %
               (self.op.command, node_name, nres.fail_msg))
        result.append((False, msg))
      else:
        result.append((True, nres.payload))

    return result


#: Query type implementations
_QUERY_IMPL = {
  constants.QR_CLUSTER: _ClusterQuery,
  constants.QR_INSTANCE: _InstanceQuery,
  constants.QR_NODE: _NodeQuery,
  constants.QR_GROUP: _GroupQuery,
  constants.QR_NETWORK: _NetworkQuery,
  constants.QR_OS: _OsQuery,
  constants.QR_EXTSTORAGE: _ExtStorageQuery,
  constants.QR_EXPORT: _ExportQuery,
  }

assert set(_QUERY_IMPL.keys()) == constants.QR_VIA_OP


def _GetQueryImplementation(name):
  """Returns the implemtnation for a query type.

  @param name: Query type, must be one of L{constants.QR_VIA_OP}

  """
  try:
    return _QUERY_IMPL[name]
  except KeyError:
    raise errors.OpPrereqError("Unknown query resource '%s'" % name,
                               errors.ECODE_INVAL)
