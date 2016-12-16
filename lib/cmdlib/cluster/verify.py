#
#

# Copyright (C) 2014 Google Inc.
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

"""Logical units for cluster verification."""

import itertools
import logging
import operator
import re
import time
import ganeti.masterd.instance
import ganeti.rpc.node as rpc

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import pathutils
from ganeti import utils
from ganeti import vcluster
from ganeti import hypervisor
from ganeti import opcodes

from ganeti.cmdlib.base import LogicalUnit, NoHooksLU, ResultWithJobs
from ganeti.cmdlib.common import ShareAll, ComputeAncillaryFiles, \
    CheckNodePVs, ComputeIPolicyInstanceViolation, AnnotateDiskParams, \
    SupportsOob


def _GetAllHypervisorParameters(cluster, instances):
  """Compute the set of all hypervisor parameters.

  @type cluster: L{objects.Cluster}
  @param cluster: the cluster object
  @param instances: list of L{objects.Instance}
  @param instances: additional instances from which to obtain parameters
  @rtype: list of (origin, hypervisor, parameters)
  @return: a list with all parameters found, indicating the hypervisor they
       apply to, and the origin (can be "cluster", "os X", or "instance Y")

  """
  hvp_data = []

  for hv_name in cluster.enabled_hypervisors:
    hvp_data.append(("cluster", hv_name, cluster.GetHVDefaults(hv_name)))

  for os_name, os_hvp in cluster.os_hvp.items():
    for hv_name, hv_params in os_hvp.items():
      if hv_params:
        full_params = cluster.GetHVDefaults(hv_name, os_name=os_name)
        hvp_data.append(("os %s" % os_name, hv_name, full_params))

  # TODO: collapse identical parameter values in a single one
  for instance in instances:
    if instance.hvparams:
      hvp_data.append(("instance %s" % instance.name, instance.hypervisor,
                       cluster.FillHV(instance)))

  return hvp_data


class _VerifyErrors(object):
  """Mix-in for cluster/group verify LUs.

  It provides _Error and _ErrorIf, and updates the self.bad boolean. (Expects
  self.op and self._feedback_fn to be available.)

  """

  ETYPE_ERROR = constants.CV_ERROR
  ETYPE_WARNING = constants.CV_WARNING

  def _ErrorMsgList(self, error_descriptor, object_name, message_list,
                    log_type=ETYPE_ERROR):
    """Format multiple error messages.

    Based on the opcode's error_codes parameter, either format a
    parseable error code, or a simpler error string.

    This must be called only from Exec and functions called from Exec.


    @type error_descriptor: tuple (string, string, string)
    @param error_descriptor: triplet describing the error (object_type,
        code, description)
    @type object_name: string
    @param object_name: name of object (instance, node ..) the error relates to
    @type message_list: list of strings
    @param message_list: body of error messages
    @type log_type: string
    @param log_type: log message type (WARNING, ERROR ..)
    """
    # Called with empty list - nothing to do
    if not message_list:
      return

    object_type, error_code, _ = error_descriptor
    # If the error code is in the list of ignored errors, demote the error to a
    # warning
    if error_code in self.op.ignore_errors:     # pylint: disable=E1101
      log_type = self.ETYPE_WARNING

    prefixed_list = []
    if self.op.error_codes: # This is a mix-in. pylint: disable=E1101
      for msg in message_list:
        prefixed_list.append("  - %s:%s:%s:%s:%s" % (
            log_type, error_code, object_type, object_name, msg))
    else:
      if not object_name:
        object_name = ""
      for msg in message_list:
        prefixed_list.append("  - %s: %s %s: %s" % (
            log_type, object_type, object_name, msg))

    # Report messages via the feedback_fn
    # pylint: disable=E1101
    self._feedback_fn(constants.ELOG_MESSAGE_LIST, prefixed_list)

    # do not mark the operation as failed for WARN cases only
    if log_type == self.ETYPE_ERROR:
      self.bad = True

  def _ErrorMsg(self, error_descriptor, object_name, message,
                log_type=ETYPE_ERROR):
    """Log a single error message.

    """
    self._ErrorMsgList(error_descriptor, object_name, [message], log_type)

  # TODO: Replace this method with a cleaner interface, get rid of the if
  # condition as it only rarely saves lines, but makes things less readable.
  def _ErrorIf(self, cond, *args, **kwargs):
    """Log an error message if the passed condition is True.

    """
    if (bool(cond)
        or self.op.debug_simulate_errors): # pylint: disable=E1101
      self._Error(*args, **kwargs)

  # TODO: Replace this method with a cleaner interface
  def _Error(self, ecode, item, message, *args, **kwargs):
    """Log an error message if the passed condition is True.

    """
    #TODO: Remove 'code' argument in favour of using log_type
    log_type = kwargs.get('code', self.ETYPE_ERROR)
    if args:
      message = message % args
    self._ErrorMsgList(ecode, item, [message], log_type=log_type)


class LUClusterVerify(NoHooksLU):
  """Submits all jobs necessary to verify the cluster.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    jobs = []

    if self.op.group_name:
      groups = [self.op.group_name]
      depends_fn = lambda: None
    else:
      groups = self.cfg.GetNodeGroupList()

      # Verify global configuration
      jobs.append([
        opcodes.OpClusterVerifyConfig(ignore_errors=self.op.ignore_errors),
        ])

      # Always depend on global verification
      depends_fn = lambda: [(-len(jobs), [])]

    jobs.extend(
      [opcodes.OpClusterVerifyGroup(group_name=group,
                                    ignore_errors=self.op.ignore_errors,
                                    depends=depends_fn(),
                                    verify_clutter=self.op.verify_clutter)]
      for group in groups)

    # Fix up all parameters
    for op in itertools.chain(*jobs):
      op.debug_simulate_errors = self.op.debug_simulate_errors
      op.verbose = self.op.verbose
      op.error_codes = self.op.error_codes
      try:
        op.skip_checks = self.op.skip_checks
      except AttributeError:
        assert not isinstance(op, opcodes.OpClusterVerifyGroup)

    return ResultWithJobs(jobs)


class LUClusterVerifyDisks(NoHooksLU):
  """Verifies the cluster disks status.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = ShareAll()
    if self.op.group_name:
      self.needed_locks = {
        locking.LEVEL_NODEGROUP: [self.cfg.LookupNodeGroup(self.op.group_name)]
        }
    else:
      self.needed_locks = {
        locking.LEVEL_NODEGROUP: locking.ALL_SET,
        }

  def Exec(self, feedback_fn):
    group_names = self.owned_locks(locking.LEVEL_NODEGROUP)
    instances = self.cfg.GetInstanceList()

    only_ext = compat.all(
        self.cfg.GetInstanceDiskTemplate(i) == constants.DT_EXT
        for i in instances)

    # We skip current NodeGroup verification if there are only external storage
    # devices. Currently we provide an interface for external storage provider
    # for disk verification implementations, however current ExtStorageDevice
    # does not provide an API for this yet.
    #
    # This check needs to be revisited if ES_ACTION_VERIFY on ExtStorageDevice
    # is implemented.
    if only_ext:
      logging.info("All instances have ext storage, skipping verify disks.")
      return ResultWithJobs([])
    else:
      # Submit one instance of L{opcodes.OpGroupVerifyDisks} per node group
      return ResultWithJobs([[opcodes.OpGroupVerifyDisks(group_name=group)]
                             for group in group_names])


class LUClusterVerifyConfig(NoHooksLU, _VerifyErrors):
  """Verifies the cluster config.

  """
  REQ_BGL = False

  def _VerifyHVP(self, hvp_data):
    """Verifies locally the syntax of the hypervisor parameters.

    """
    for item, hv_name, hv_params in hvp_data:
      msg = ("hypervisor %s parameters syntax check (source %s): %%s" %
             (item, hv_name))
      try:
        hv_class = hypervisor.GetHypervisorClass(hv_name)
        utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
        hv_class.CheckParameterSyntax(hv_params)
      except errors.GenericError, err:
        self._ErrorIf(True, constants.CV_ECLUSTERCFG, None, msg % str(err))

  def ExpandNames(self):
    self.needed_locks = dict.fromkeys(locking.LEVELS, locking.ALL_SET)
    self.share_locks = ShareAll()

  def CheckPrereq(self):
    """Check prerequisites.

    """
    # Retrieve all information
    self.all_group_info = self.cfg.GetAllNodeGroupsInfo()
    self.all_node_info = self.cfg.GetAllNodesInfo()
    self.all_inst_info = self.cfg.GetAllInstancesInfo()

  def Exec(self, feedback_fn):
    """Verify integrity of cluster, performing various test on nodes.

    """
    self.bad = False
    self._feedback_fn = feedback_fn

    feedback_fn("* Verifying cluster config")

    msg_list = self.cfg.VerifyConfig()
    self._ErrorMsgList(constants.CV_ECLUSTERCFG, None, msg_list)

    feedback_fn("* Verifying cluster certificate files")

    for cert_filename in pathutils.ALL_CERT_FILES:
      (errcode, msg) = utils.VerifyCertificate(cert_filename)
      self._ErrorIf(errcode, constants.CV_ECLUSTERCERT, None, msg, code=errcode)

    self._ErrorIf(not utils.CanRead(constants.LUXID_USER,
                                    pathutils.NODED_CERT_FILE),
                  constants.CV_ECLUSTERCERT,
                  None,
                  pathutils.NODED_CERT_FILE + " must be accessible by the " +
                    constants.LUXID_USER + " user")

    feedback_fn("* Verifying hypervisor parameters")

    self._VerifyHVP(_GetAllHypervisorParameters(self.cfg.GetClusterInfo(),
                                                self.all_inst_info.values()))

    feedback_fn("* Verifying all nodes belong to an existing group")

    # We do this verification here because, should this bogus circumstance
    # occur, it would never be caught by VerifyGroup, which only acts on
    # nodes/instances reachable from existing node groups.

    dangling_nodes = set(node for node in self.all_node_info.values()
                         if node.group not in self.all_group_info)

    dangling_instances = {}
    no_node_instances = []

    for inst in self.all_inst_info.values():
      if inst.primary_node in [node.uuid for node in dangling_nodes]:
        dangling_instances.setdefault(inst.primary_node, []).append(inst)
      elif inst.primary_node not in self.all_node_info:
        no_node_instances.append(inst)

    pretty_dangling = [
        "%s (%s)" %
        (node.name,
         utils.CommaJoin(inst.name for
                         inst in dangling_instances.get(node.uuid, [])))
        for node in dangling_nodes]

    self._ErrorIf(bool(dangling_nodes), constants.CV_ECLUSTERDANGLINGNODES,
                  None,
                  "the following nodes (and their instances) belong to a non"
                  " existing group: %s", utils.CommaJoin(pretty_dangling))

    self._ErrorIf(bool(no_node_instances), constants.CV_ECLUSTERDANGLINGINST,
                  None,
                  "the following instances have a non-existing primary-node:"
                  " %s", utils.CommaJoin(inst.name for
                                         inst in no_node_instances))

    return not self.bad


class LUClusterVerifyGroup(LogicalUnit, _VerifyErrors):
  """Verifies the status of a node group.

  """
  HPATH = "cluster-verify"
  HTYPE = constants.HTYPE_CLUSTER
  REQ_BGL = False

  _HOOKS_INDENT_RE = re.compile("^", re.M)

  class NodeImage(object):
    """A class representing the logical and physical status of a node.

    @type uuid: string
    @ivar uuid: the node UUID to which this object refers
    @ivar volumes: a structure as returned from
        L{ganeti.backend.GetVolumeList} (runtime)
    @ivar instances: a list of running instances (runtime)
    @ivar pinst: list of configured primary instances (config)
    @ivar sinst: list of configured secondary instances (config)
    @ivar sbp: dictionary of {primary-node: list of instances} for all
        instances for which this node is secondary (config)
    @ivar mfree: free memory, as reported by hypervisor (runtime)
    @ivar dfree: free disk, as reported by the node (runtime)
    @ivar offline: the offline status (config)
    @type rpc_fail: boolean
    @ivar rpc_fail: whether the RPC verify call was successfull (overall,
        not whether the individual keys were correct) (runtime)
    @type lvm_fail: boolean
    @ivar lvm_fail: whether the RPC call didn't return valid LVM data
    @type hyp_fail: boolean
    @ivar hyp_fail: whether the RPC call didn't return the instance list
    @type ghost: boolean
    @ivar ghost: whether this is a known node or not (config)
    @type os_fail: boolean
    @ivar os_fail: whether the RPC call didn't return valid OS data
    @type oslist: list
    @ivar oslist: list of OSes as diagnosed by DiagnoseOS
    @type vm_capable: boolean
    @ivar vm_capable: whether the node can host instances
    @type pv_min: float
    @ivar pv_min: size in MiB of the smallest PVs
    @type pv_max: float
    @ivar pv_max: size in MiB of the biggest PVs

    """
    def __init__(self, offline=False, uuid=None, vm_capable=True):
      self.uuid = uuid
      self.volumes = {}
      self.instances = []
      self.pinst = []
      self.sinst = []
      self.sbp = {}
      self.mfree = 0
      self.dfree = 0
      self.offline = offline
      self.vm_capable = vm_capable
      self.rpc_fail = False
      self.lvm_fail = False
      self.hyp_fail = False
      self.ghost = False
      self.os_fail = False
      self.oslist = {}
      self.pv_min = None
      self.pv_max = None

  def ExpandNames(self):
    # This raises errors.OpPrereqError on its own:
    self.group_uuid = self.cfg.LookupNodeGroup(self.op.group_name)

    # Get instances in node group; this is unsafe and needs verification later
    inst_uuids = \
      self.cfg.GetNodeGroupInstances(self.group_uuid, primary_only=True)

    self.needed_locks = {
      locking.LEVEL_INSTANCE: self.cfg.GetInstanceNames(inst_uuids),
      locking.LEVEL_NODEGROUP: [self.group_uuid],
      locking.LEVEL_NODE: [],
      }

    self.share_locks = ShareAll()

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE:
      # Get members of node group; this is unsafe and needs verification later
      nodes = set(self.cfg.GetNodeGroup(self.group_uuid).members)

      # In Exec(), we warn about mirrored instances that have primary and
      # secondary living in separate node groups. To fully verify that
      # volumes for these instances are healthy, we will need to do an
      # extra call to their secondaries. We ensure here those nodes will
      # be locked.
      for inst_name in self.owned_locks(locking.LEVEL_INSTANCE):
        # Important: access only the instances whose lock is owned
        instance = self.cfg.GetInstanceInfoByName(inst_name)
        disks = self.cfg.GetInstanceDisks(instance.uuid)
        if utils.AnyDiskOfType(disks, constants.DTS_INT_MIRROR):
          nodes.update(self.cfg.GetInstanceSecondaryNodes(instance.uuid))

      self.needed_locks[locking.LEVEL_NODE] = nodes

  def CheckPrereq(self):
    assert self.group_uuid in self.owned_locks(locking.LEVEL_NODEGROUP)
    self.group_info = self.cfg.GetNodeGroup(self.group_uuid)

    group_node_uuids = set(self.group_info.members)
    group_inst_uuids = \
      self.cfg.GetNodeGroupInstances(self.group_uuid, primary_only=True)

    unlocked_node_uuids = \
        group_node_uuids.difference(self.owned_locks(locking.LEVEL_NODE))

    unlocked_inst_uuids = \
        group_inst_uuids.difference(
          [self.cfg.GetInstanceInfoByName(name).uuid
           for name in self.owned_locks(locking.LEVEL_INSTANCE)])

    if unlocked_node_uuids:
      raise errors.OpPrereqError(
        "Missing lock for nodes: %s" %
        utils.CommaJoin(self.cfg.GetNodeNames(unlocked_node_uuids)),
        errors.ECODE_STATE)

    if unlocked_inst_uuids:
      raise errors.OpPrereqError(
        "Missing lock for instances: %s" %
        utils.CommaJoin(self.cfg.GetInstanceNames(unlocked_inst_uuids)),
        errors.ECODE_STATE)

    self.all_node_info = self.cfg.GetAllNodesInfo()
    self.all_inst_info = self.cfg.GetAllInstancesInfo()
    self.all_disks_info = self.cfg.GetAllDisksInfo()

    self.my_node_uuids = group_node_uuids
    self.my_node_info = dict((node_uuid, self.all_node_info[node_uuid])
                             for node_uuid in group_node_uuids)

    self.my_inst_uuids = group_inst_uuids
    self.my_inst_info = dict((inst_uuid, self.all_inst_info[inst_uuid])
                             for inst_uuid in group_inst_uuids)

    # We detect here the nodes that will need the extra RPC calls for verifying
    # split LV volumes; they should be locked.
    extra_lv_nodes = {}

    for inst in self.my_inst_info.values():
      disks = self.cfg.GetInstanceDisks(inst.uuid)
      if utils.AnyDiskOfType(disks, constants.DTS_INT_MIRROR):
        inst_nodes = self.cfg.GetInstanceNodes(inst.uuid)
        for nuuid in inst_nodes:
          if self.all_node_info[nuuid].group != self.group_uuid:
            if nuuid in extra_lv_nodes:
              extra_lv_nodes[nuuid].append(inst.name)
            else:
              extra_lv_nodes[nuuid] = [inst.name]

    extra_lv_nodes_set = set(extra_lv_nodes.iterkeys())
    unlocked_lv_nodes = \
        extra_lv_nodes_set.difference(self.owned_locks(locking.LEVEL_NODE))

    if unlocked_lv_nodes:
      node_strings = ['%s: [%s]' % (
          self.cfg.GetNodeName(node), utils.CommaJoin(extra_lv_nodes[node]))
            for node in unlocked_lv_nodes]
      raise errors.OpPrereqError("Missing node locks for LV check: %s" %
                                 utils.CommaJoin(node_strings),
                                 errors.ECODE_STATE)
    self.extra_lv_nodes = list(extra_lv_nodes_set)

  def _VerifyNode(self, ninfo, nresult):
    """Perform some basic validation on data returned from a node.

      - check the result data structure is well formed and has all the
        mandatory fields
      - check ganeti version

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the results from the node
    @rtype: boolean
    @return: whether overall this call was successful (and we can expect
         reasonable values in the respose)

    """
    # main result, nresult should be a non-empty dict
    test = not nresult or not isinstance(nresult, dict)
    self._ErrorIf(test, constants.CV_ENODERPC, ninfo.name,
                  "unable to verify node: no data returned")
    if test:
      return False

    # compares ganeti version
    local_version = constants.PROTOCOL_VERSION
    remote_version = nresult.get("version", None)
    test = not (remote_version and
                isinstance(remote_version, (list, tuple)) and
                len(remote_version) == 2)
    self._ErrorIf(test, constants.CV_ENODERPC, ninfo.name,
                  "connection to node returned invalid data")
    if test:
      return False

    test = local_version != remote_version[0]
    self._ErrorIf(test, constants.CV_ENODEVERSION, ninfo.name,
                  "incompatible protocol versions: master %s,"
                  " node %s", local_version, remote_version[0])
    if test:
      return False

    # node seems compatible, we can actually try to look into its results

    # full package version
    self._ErrorIf(constants.RELEASE_VERSION != remote_version[1],
                  constants.CV_ENODEVERSION, ninfo.name,
                  "software version mismatch: master %s, node %s",
                  constants.RELEASE_VERSION, remote_version[1],
                  code=self.ETYPE_WARNING)

    hyp_result = nresult.get(constants.NV_HYPERVISOR, None)
    if ninfo.vm_capable and isinstance(hyp_result, dict):
      for hv_name, hv_result in hyp_result.iteritems():
        test = hv_result is not None
        self._ErrorIf(test, constants.CV_ENODEHV, ninfo.name,
                      "hypervisor %s verify failure: '%s'", hv_name, hv_result)

    hvp_result = nresult.get(constants.NV_HVPARAMS, None)
    if ninfo.vm_capable and isinstance(hvp_result, list):
      for item, hv_name, hv_result in hvp_result:
        self._ErrorIf(True, constants.CV_ENODEHV, ninfo.name,
                      "hypervisor %s parameter verify failure (source %s): %s",
                      hv_name, item, hv_result)

    test = nresult.get(constants.NV_NODESETUP,
                       ["Missing NODESETUP results"])
    self._ErrorIf(test, constants.CV_ENODESETUP, ninfo.name,
                  "node setup error: %s", "; ".join(test))

    return True

  def _VerifyNodeTime(self, ninfo, nresult,
                      nvinfo_starttime, nvinfo_endtime):
    """Check the node time.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nvinfo_starttime: the start time of the RPC call
    @param nvinfo_endtime: the end time of the RPC call

    """
    ntime = nresult.get(constants.NV_TIME, None)
    try:
      ntime_merged = utils.MergeTime(ntime)
    except (ValueError, TypeError):
      self._ErrorIf(True, constants.CV_ENODETIME, ninfo.name,
                    "Node returned invalid time")
      return

    if ntime_merged < (nvinfo_starttime - constants.NODE_MAX_CLOCK_SKEW):
      ntime_diff = "%.01fs" % abs(nvinfo_starttime - ntime_merged)
    elif ntime_merged > (nvinfo_endtime + constants.NODE_MAX_CLOCK_SKEW):
      ntime_diff = "%.01fs" % abs(ntime_merged - nvinfo_endtime)
    else:
      ntime_diff = None

    self._ErrorIf(ntime_diff is not None, constants.CV_ENODETIME, ninfo.name,
                  "Node time diverges by at least %s from master node time",
                  ntime_diff)

  def _UpdateVerifyNodeLVM(self, ninfo, nresult, vg_name, nimg):
    """Check the node LVM results and update info for cross-node checks.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param vg_name: the configured VG name
    @type nimg: L{NodeImage}
    @param nimg: node image

    """
    if vg_name is None:
      return

    # checks vg existence and size > 20G
    vglist = nresult.get(constants.NV_VGLIST, None)
    test = not vglist
    self._ErrorIf(test, constants.CV_ENODELVM, ninfo.name,
                  "unable to check volume groups")
    if not test:
      vgstatus = utils.CheckVolumeGroupSize(vglist, vg_name,
                                            constants.MIN_VG_SIZE)
      self._ErrorIf(vgstatus, constants.CV_ENODELVM, ninfo.name, vgstatus)

    # Check PVs
    (errmsgs, pvminmax) = CheckNodePVs(nresult, self._exclusive_storage)
    for em in errmsgs:
      self._Error(constants.CV_ENODELVM, ninfo.name, em)
    if pvminmax is not None:
      (nimg.pv_min, nimg.pv_max) = pvminmax

  def _VerifyGroupDRBDVersion(self, node_verify_infos):
    """Check cross-node DRBD version consistency.

    @type node_verify_infos: dict
    @param node_verify_infos: infos about nodes as returned from the
      node_verify call.

    """
    node_versions = {}
    for node_uuid, ndata in node_verify_infos.items():
      nresult = ndata.payload
      if nresult:
        version = nresult.get(constants.NV_DRBDVERSION, None)
        if version:
          node_versions[node_uuid] = version

    if len(set(node_versions.values())) > 1:
      for node_uuid, version in sorted(node_versions.items()):
        msg = "DRBD version mismatch: %s" % version
        self._Error(constants.CV_ENODEDRBDHELPER, node_uuid, msg,
                    code=self.ETYPE_WARNING)

  def _VerifyGroupLVM(self, node_image, vg_name):
    """Check cross-node consistency in LVM.

    @type node_image: dict
    @param node_image: info about nodes, mapping from node to names to
      L{NodeImage} objects
    @param vg_name: the configured VG name

    """
    if vg_name is None:
      return

    # Only exclusive storage needs this kind of checks
    if not self._exclusive_storage:
      return

    # exclusive_storage wants all PVs to have the same size (approximately),
    # if the smallest and the biggest ones are okay, everything is fine.
    # pv_min is None iff pv_max is None
    vals = [ni for ni in node_image.values() if ni.pv_min is not None]
    if not vals:
      return
    (pvmin, minnode_uuid) = min((ni.pv_min, ni.uuid) for ni in vals)
    (pvmax, maxnode_uuid) = max((ni.pv_max, ni.uuid) for ni in vals)
    bad = utils.LvmExclusiveTestBadPvSizes(pvmin, pvmax)
    self._ErrorIf(bad, constants.CV_EGROUPDIFFERENTPVSIZE, self.group_info.name,
                  "PV sizes differ too much in the group; smallest (%s MB) is"
                  " on %s, biggest (%s MB) is on %s",
                  pvmin, self.cfg.GetNodeName(minnode_uuid),
                  pvmax, self.cfg.GetNodeName(maxnode_uuid))

  def _VerifyNodeBridges(self, ninfo, nresult, bridges):
    """Check the node bridges.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param bridges: the expected list of bridges

    """
    if not bridges:
      return

    missing = nresult.get(constants.NV_BRIDGES, None)
    test = not isinstance(missing, list)
    self._ErrorIf(test, constants.CV_ENODENET, ninfo.name,
                  "did not return valid bridge information")
    if not test:
      self._ErrorIf(bool(missing), constants.CV_ENODENET, ninfo.name,
                    "missing bridges: %s" % utils.CommaJoin(sorted(missing)))

  def _VerifyNodeUserScripts(self, ninfo, nresult):
    """Check the results of user scripts presence and executability on the node

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    test = not constants.NV_USERSCRIPTS in nresult
    self._ErrorIf(test, constants.CV_ENODEUSERSCRIPTS, ninfo.name,
                  "did not return user scripts information")

    broken_scripts = nresult.get(constants.NV_USERSCRIPTS, None)
    if not test:
      self._ErrorIf(broken_scripts, constants.CV_ENODEUSERSCRIPTS, ninfo.name,
                    "user scripts not present or not executable: %s" %
                    utils.CommaJoin(sorted(broken_scripts)))

  def _VerifyNodeNetwork(self, ninfo, nresult):
    """Check the node network connectivity results.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    test = constants.NV_NODELIST not in nresult
    self._ErrorIf(test, constants.CV_ENODESSH, ninfo.name,
                  "node hasn't returned node ssh connectivity data")
    if not test:
      if nresult[constants.NV_NODELIST]:
        for a_node, a_msg in nresult[constants.NV_NODELIST].items():
          self._ErrorIf(True, constants.CV_ENODESSH, ninfo.name,
                        "ssh communication with node '%s': %s", a_node, a_msg)

    if constants.NV_NODENETTEST not in nresult:
      self._ErrorMsg(constants.CV_ENODENET, ninfo.name,
                     "node hasn't returned node tcp connectivity data")
    elif nresult[constants.NV_NODENETTEST]:
      nlist = utils.NiceSort(nresult[constants.NV_NODENETTEST].keys())
      msglist = []
      for node in nlist:
        msglist.append("tcp communication with node '%s': %s" %
                       (node, nresult[constants.NV_NODENETTEST][node]))
      self._ErrorMsgList(constants.CV_ENODENET, ninfo.name, msglist)

    if constants.NV_MASTERIP not in nresult:
      self._ErrorMsg(constants.CV_ENODENET, ninfo.name,
                     "node hasn't returned node master IP reachability data")
    elif nresult[constants.NV_MASTERIP] is False:  # be explicit, could be None
      if ninfo.uuid == self.master_node:
        msg = "the master node cannot reach the master IP (not configured?)"
      else:
        msg = "cannot reach the master IP"
      self._ErrorMsg(constants.CV_ENODENET, ninfo.name, msg)

  def _VerifyInstance(self, instance, node_image, diskstatus):
    """Verify an instance.

    This function checks to see if the required block devices are
    available on the instance's node, and that the nodes are in the correct
    state.

    """
    pnode_uuid = instance.primary_node
    pnode_img = node_image[pnode_uuid]
    groupinfo = self.cfg.GetAllNodeGroupsInfo()

    node_vol_should = {}
    self.cfg.GetInstanceLVsByNode(instance.uuid, lvmap=node_vol_should)

    cluster = self.cfg.GetClusterInfo()
    ipolicy = ganeti.masterd.instance.CalculateGroupIPolicy(cluster,
                                                            self.group_info)
    err = ComputeIPolicyInstanceViolation(ipolicy, instance, self.cfg)
    self._ErrorIf(err, constants.CV_EINSTANCEPOLICY, instance.name,
                  utils.CommaJoin(err), code=self.ETYPE_WARNING)

    for node_uuid in node_vol_should:
      n_img = node_image[node_uuid]
      if n_img.offline or n_img.rpc_fail or n_img.lvm_fail:
        # ignore missing volumes on offline or broken nodes
        continue
      for volume in node_vol_should[node_uuid]:
        test = volume not in n_img.volumes
        self._ErrorIf(test, constants.CV_EINSTANCEMISSINGDISK, instance.name,
                      "volume %s missing on node %s", volume,
                      self.cfg.GetNodeName(node_uuid))

    if instance.admin_state == constants.ADMINST_UP:
      test = instance.uuid not in pnode_img.instances and not pnode_img.offline
      self._ErrorIf(test, constants.CV_EINSTANCEDOWN, instance.name,
                    "instance not running on its primary node %s",
                     self.cfg.GetNodeName(pnode_uuid))
      self._ErrorIf(pnode_img.offline, constants.CV_EINSTANCEBADNODE,
                    instance.name, "instance is marked as running and lives on"
                    " offline node %s", self.cfg.GetNodeName(pnode_uuid))

    diskdata = [(nname, success, status, idx)
                for (nname, disks) in diskstatus.items()
                for idx, (success, status) in enumerate(disks)]

    for nname, success, bdev_status, idx in diskdata:
      # the 'ghost node' construction in Exec() ensures that we have a
      # node here
      snode = node_image[nname]
      bad_snode = snode.ghost or snode.offline
      self._ErrorIf(instance.disks_active and
                    not success and not bad_snode,
                    constants.CV_EINSTANCEFAULTYDISK, instance.name,
                    "couldn't retrieve status for disk/%s on %s: %s",
                    idx, self.cfg.GetNodeName(nname), bdev_status)

      if instance.disks_active and success and bdev_status.is_degraded:
        msg = "disk/%s on %s is degraded" % (idx, self.cfg.GetNodeName(nname))

        code = self.ETYPE_ERROR
        accepted_lds = [constants.LDS_OKAY, constants.LDS_SYNC]

        if bdev_status.ldisk_status in accepted_lds:
          code = self.ETYPE_WARNING

        msg += "; local disk state is '%s'" % \
                 constants.LDS_NAMES[bdev_status.ldisk_status]

        self._Error(constants.CV_EINSTANCEFAULTYDISK, instance.name, msg,
                    code=code)

    self._ErrorIf(pnode_img.rpc_fail and not pnode_img.offline,
                  constants.CV_ENODERPC, self.cfg.GetNodeName(pnode_uuid),
                  "instance %s, connection to primary node failed",
                  instance.name)

    secondary_nodes = self.cfg.GetInstanceSecondaryNodes(instance.uuid)
    self._ErrorIf(len(secondary_nodes) > 1,
                  constants.CV_EINSTANCELAYOUT, instance.name,
                  "instance has multiple secondary nodes: %s",
                  utils.CommaJoin(secondary_nodes),
                  code=self.ETYPE_WARNING)

    inst_nodes = self.cfg.GetInstanceNodes(instance.uuid)
    es_flags = rpc.GetExclusiveStorageForNodes(self.cfg, inst_nodes)
    disks = self.cfg.GetInstanceDisks(instance.uuid)
    if any(es_flags.values()):
      if not utils.AllDiskOfType(disks, constants.DTS_EXCL_STORAGE):
        # Disk template not compatible with exclusive_storage: no instance
        # node should have the flag set
        es_nodes = [n
                    for (n, es) in es_flags.items()
                    if es]
        unsupported = [d.dev_type for d in disks
                       if d.dev_type not in constants.DTS_EXCL_STORAGE]
        self._Error(constants.CV_EINSTANCEUNSUITABLENODE, instance.name,
                    "instance uses disk types %s, which are not supported on"
                    " nodes that have exclusive storage set: %s",
                    utils.CommaJoin(unsupported),
                    utils.CommaJoin(self.cfg.GetNodeNames(es_nodes)))
      for (idx, disk) in enumerate(disks):
        self._ErrorIf(disk.spindles is None,
                      constants.CV_EINSTANCEMISSINGCFGPARAMETER, instance.name,
                      "number of spindles not configured for disk %s while"
                      " exclusive storage is enabled, try running"
                      " gnt-cluster repair-disk-sizes", idx)

    if utils.AnyDiskOfType(disks, constants.DTS_INT_MIRROR):
      instance_nodes = utils.NiceSort(inst_nodes)
      instance_groups = {}

      for node_uuid in instance_nodes:
        instance_groups.setdefault(self.all_node_info[node_uuid].group,
                                   []).append(node_uuid)

      pretty_list = [
        "%s (group %s)" % (utils.CommaJoin(self.cfg.GetNodeNames(nodes)),
                           groupinfo[group].name)
        # Sort so that we always list the primary node first.
        for group, nodes in sorted(instance_groups.items(),
                                   key=lambda (_, nodes): pnode_uuid in nodes,
                                   reverse=True)]

      self._ErrorIf(len(instance_groups) > 1,
                    constants.CV_EINSTANCESPLITGROUPS,
                    instance.name, "instance has primary and secondary nodes in"
                    " different groups: %s", utils.CommaJoin(pretty_list),
                    code=self.ETYPE_WARNING)

    inst_nodes_offline = []
    for snode in secondary_nodes:
      s_img = node_image[snode]
      self._ErrorIf(s_img.rpc_fail and not s_img.offline, constants.CV_ENODERPC,
                    self.cfg.GetNodeName(snode),
                    "instance %s, connection to secondary node failed",
                    instance.name)

      if s_img.offline:
        inst_nodes_offline.append(snode)

    # warn that the instance lives on offline nodes
    self._ErrorIf(inst_nodes_offline, constants.CV_EINSTANCEBADNODE,
                  instance.name, "instance has offline secondary node(s) %s",
                  utils.CommaJoin(self.cfg.GetNodeNames(inst_nodes_offline)))
    # ... or ghost/non-vm_capable nodes
    for node_uuid in inst_nodes:
      self._ErrorIf(node_image[node_uuid].ghost, constants.CV_EINSTANCEBADNODE,
                    instance.name, "instance lives on ghost node %s",
                    self.cfg.GetNodeName(node_uuid))
      self._ErrorIf(not node_image[node_uuid].vm_capable,
                    constants.CV_EINSTANCEBADNODE, instance.name,
                    "instance lives on non-vm_capable node %s",
                    self.cfg.GetNodeName(node_uuid))

  def _VerifyOrphanVolumes(self, vg_name, node_vol_should, node_image,
                           reserved):
    """Verify if there are any unknown volumes in the cluster.

    The .os, .swap and backup volumes are ignored. All other volumes are
    reported as unknown.

    @type vg_name: string
    @param vg_name: the name of the Ganeti-administered volume group
    @type node_vol_should: dict
    @param node_vol_should: mapping of node UUIDs to expected LVs on each node
    @type node_image: dict
    @param node_image: mapping of node UUIDs to L{NodeImage} objects
    @type reserved: L{ganeti.utils.FieldSet}
    @param reserved: a FieldSet of reserved volume names

    """
    for node_uuid, n_img in node_image.items():
      if (n_img.offline or n_img.rpc_fail or n_img.lvm_fail or
          self.all_node_info[node_uuid].group != self.group_uuid):
        # skip non-healthy nodes
        continue
      for volume in n_img.volumes:
        # skip volumes not belonging to the ganeti-administered volume group
        if volume.split('/')[0] != vg_name:
          continue

        test = ((node_uuid not in node_vol_should or
                volume not in node_vol_should[node_uuid]) and
                not reserved.Matches(volume))
        self._ErrorIf(test, constants.CV_ENODEORPHANLV,
                      self.cfg.GetNodeName(node_uuid),
                      "volume %s is unknown", volume,
                      code=_VerifyErrors.ETYPE_WARNING)

  def _VerifyNPlusOneMemory(self, node_image, all_insts):
    """Verify N+1 Memory Resilience.

    Check that if one single node dies we can still start all the
    instances it was primary for.

    """
    cluster_info = self.cfg.GetClusterInfo()
    for node_uuid, n_img in node_image.items():
      # This code checks that every node which is now listed as
      # secondary has enough memory to host all instances it is
      # supposed to should a single other node in the cluster fail.
      # FIXME: not ready for failover to an arbitrary node
      # FIXME: does not support file-backed instances
      # WARNING: we currently take into account down instances as well
      # as up ones, considering that even if they're down someone
      # might want to start them even in the event of a node failure.
      if n_img.offline or \
         self.all_node_info[node_uuid].group != self.group_uuid:
        # we're skipping nodes marked offline and nodes in other groups from
        # the N+1 warning, since most likely we don't have good memory
        # information from them; we already list instances living on such
        # nodes, and that's enough warning
        continue
      #TODO(dynmem): also consider ballooning out other instances
      for prinode, inst_uuids in n_img.sbp.items():
        needed_mem = 0
        for inst_uuid in inst_uuids:
          bep = cluster_info.FillBE(all_insts[inst_uuid])
          if bep[constants.BE_AUTO_BALANCE]:
            needed_mem += bep[constants.BE_MINMEM]
        test = n_img.mfree < needed_mem
        self._ErrorIf(test, constants.CV_ENODEN1,
                      self.cfg.GetNodeName(node_uuid),
                      "not enough memory to accomodate instance failovers"
                      " should node %s fail (%dMiB needed, %dMiB available)",
                      self.cfg.GetNodeName(prinode), needed_mem, n_img.mfree)

  def _CertError(self, *args):
    """Helper function for _VerifyClientCertificates."""
    self._Error(constants.CV_ECLUSTERCLIENTCERT, None, *args)
    self._cert_error_found = True

  def _VerifyClientCertificates(self, nodes, all_nvinfo):
    """Verifies the consistency of the client certificates.

    This includes several aspects:
      - the individual validation of all nodes' certificates
      - the consistency of the master candidate certificate map
      - the consistency of the master candidate certificate map with the
        certificates that the master candidates are actually using.

    @param nodes: the list of nodes to consider in this verification
    @param all_nvinfo: the map of results of the verify_node call to
      all nodes

    """

    rebuild_certs_msg = (
        "To rebuild node certificates, please run"
        " 'gnt-cluster renew-crypto --new-node-certificates'.")

    self._cert_error_found = False

    candidate_certs = self.cfg.GetClusterInfo().candidate_certs
    if not candidate_certs:
      self._CertError(
        "The cluster's list of master candidate certificates is empty."
        " This may be because you just updated the cluster. " +
        rebuild_certs_msg)
      return

    if len(candidate_certs) != len(set(candidate_certs.values())):
      self._CertError(
        "There are at least two master candidates configured to use the same"
        " certificate.")

    # collect the client certificate
    for node in nodes:
      if node.offline:
        continue

      nresult = all_nvinfo[node.uuid]
      if nresult.fail_msg or not nresult.payload:
        continue

      (errcode, msg) = nresult.payload.get(constants.NV_CLIENT_CERT, None)

      if errcode is not None:
        self._CertError(
          "Client certificate of node '%s' failed validation: %s (code '%s')",
          node.uuid, msg, errcode)
      if not errcode:
        digest = msg
        if node.master_candidate:
          if node.uuid in candidate_certs:
            if digest != candidate_certs[node.uuid]:
              self._CertError(
                "Client certificate digest of master candidate '%s' does not"
                " match its entry in the cluster's map of master candidate"
                " certificates. Expected: %s Got: %s", node.uuid,
                digest, candidate_certs[node.uuid])
          else:
            self._CertError(
              "The master candidate '%s' does not have an entry in the"
              " map of candidate certificates.", node.uuid)
            if digest in candidate_certs.values():
              self._CertError(
                "Master candidate '%s' is using a certificate of another node.",
                node.uuid)
        else:
          if node.uuid in candidate_certs:
            self._CertError(
              "Node '%s' is not a master candidate, but still listed in the"
              " map of master candidate certificates.", node.uuid)
          if (node.uuid not in candidate_certs and
              digest in candidate_certs.values()):
            self._CertError(
              "Node '%s' is not a master candidate and is incorrectly using a"
              " certificate of another node which is master candidate.",
              node.uuid)

    if self._cert_error_found:
      self._CertError(rebuild_certs_msg)

  def _VerifySshSetup(self, nodes, all_nvinfo):
    """Evaluates the verification results of the SSH setup and clutter test.

    @param nodes: List of L{objects.Node} objects
    @param all_nvinfo: RPC results

    """
    for node in nodes:
      if not node.offline:
        nresult = all_nvinfo[node.uuid]
        if nresult.fail_msg or not nresult.payload:
          self._ErrorIf(True, constants.CV_ENODESSH, node.name,
                        "Could not verify the SSH setup of this node.")
          return
        for ssh_test in [constants.NV_SSH_SETUP, constants.NV_SSH_CLUTTER]:
          result = nresult.payload.get(ssh_test, None)
          error_msg = ""
          if isinstance(result, list):
            error_msg = " ".join(result)
          self._ErrorIf(result,
                        constants.CV_ENODESSH, None, error_msg)

  def _VerifyFiles(self, nodes, master_node_uuid, all_nvinfo,
                   (files_all, files_opt, files_mc, files_vm)):
    """Verifies file checksums collected from all nodes.

    @param nodes: List of L{objects.Node} objects
    @param master_node_uuid: UUID of master node
    @param all_nvinfo: RPC results

    """
    # Define functions determining which nodes to consider for a file
    files2nodefn = [
      (files_all, None),
      (files_mc, lambda node: (node.master_candidate or
                               node.uuid == master_node_uuid)),
      (files_vm, lambda node: node.vm_capable),
      ]

    # Build mapping from filename to list of nodes which should have the file
    nodefiles = {}
    for (files, fn) in files2nodefn:
      if fn is None:
        filenodes = nodes
      else:
        filenodes = filter(fn, nodes)
      nodefiles.update((filename, frozenset(fn.uuid for fn in filenodes))
                       for filename in files)

    assert set(nodefiles) == (files_all | files_mc | files_vm)

    fileinfo = dict((filename, {}) for filename in nodefiles)
    ignore_nodes = set()

    for node in nodes:
      if node.offline:
        ignore_nodes.add(node.uuid)
        continue

      nresult = all_nvinfo[node.uuid]

      if nresult.fail_msg or not nresult.payload:
        node_files = None
      else:
        fingerprints = nresult.payload.get(constants.NV_FILELIST, {})
        node_files = dict((vcluster.LocalizeVirtualPath(key), value)
                          for (key, value) in fingerprints.items())
        del fingerprints

      test = not (node_files and isinstance(node_files, dict))
      self._ErrorIf(test, constants.CV_ENODEFILECHECK, node.name,
                    "Node did not return file checksum data")
      if test:
        ignore_nodes.add(node.uuid)
        continue

      # Build per-checksum mapping from filename to nodes having it
      for (filename, checksum) in node_files.items():
        assert filename in nodefiles
        fileinfo[filename].setdefault(checksum, set()).add(node.uuid)

    for (filename, checksums) in fileinfo.items():
      assert compat.all(len(i) > 10 for i in checksums), "Invalid checksum"

      # Nodes having the file
      with_file = frozenset(node_uuid
                            for node_uuids in fileinfo[filename].values()
                            for node_uuid in node_uuids) - ignore_nodes

      expected_nodes = nodefiles[filename] - ignore_nodes

      # Nodes missing file
      missing_file = expected_nodes - with_file

      if filename in files_opt:
        # All or no nodes
        self._ErrorIf(missing_file and missing_file != expected_nodes,
                      constants.CV_ECLUSTERFILECHECK, None,
                      "File %s is optional, but it must exist on all or no"
                      " nodes (not found on %s)",
                      filename,
                      utils.CommaJoin(utils.NiceSort(
                        self.cfg.GetNodeName(n) for n in missing_file)))
      else:
        self._ErrorIf(missing_file, constants.CV_ECLUSTERFILECHECK, None,
                      "File %s is missing from node(s) %s", filename,
                      utils.CommaJoin(utils.NiceSort(
                        self.cfg.GetNodeName(n) for n in missing_file)))

        # Warn if a node has a file it shouldn't
        unexpected = with_file - expected_nodes
        self._ErrorIf(unexpected,
                      constants.CV_ECLUSTERFILECHECK, None,
                      "File %s should not exist on node(s) %s",
                      filename,
                      utils.CommaJoin(utils.NiceSort(
                        self.cfg.GetNodeName(n) for n in unexpected)))

      # See if there are multiple versions of the file
      test = len(checksums) > 1
      if test:
        variants = ["variant %s on %s" %
                    (idx + 1,
                     utils.CommaJoin(utils.NiceSort(
                       self.cfg.GetNodeName(n) for n in node_uuids)))
                    for (idx, (checksum, node_uuids)) in
                      enumerate(sorted(checksums.items()))]
      else:
        variants = []

      self._ErrorIf(test, constants.CV_ECLUSTERFILECHECK, None,
                    "File %s found with %s different checksums (%s)",
                    filename, len(checksums), "; ".join(variants))

  def _VerifyNodeDrbdHelper(self, ninfo, nresult, drbd_helper):
    """Verify the drbd helper.

    """
    if drbd_helper:
      helper_result = nresult.get(constants.NV_DRBDHELPER, None)
      test = (helper_result is None)
      self._ErrorIf(test, constants.CV_ENODEDRBDHELPER, ninfo.name,
                    "no drbd usermode helper returned")
      if helper_result:
        status, payload = helper_result
        test = not status
        self._ErrorIf(test, constants.CV_ENODEDRBDHELPER, ninfo.name,
                      "drbd usermode helper check unsuccessful: %s", payload)
        test = status and (payload != drbd_helper)
        self._ErrorIf(test, constants.CV_ENODEDRBDHELPER, ninfo.name,
                      "wrong drbd usermode helper: %s", payload)

  @staticmethod
  def _ComputeDrbdMinors(ninfo, instanceinfo, disks_info, drbd_map, error_if):
    """Gives the DRBD information in a map for a node.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param instanceinfo: the dict of instances
    @param disks_info: the dict of disks
    @param drbd_map: the DRBD map as returned by
        L{ganeti.config.ConfigWriter.ComputeDRBDMap}
    @type error_if: callable like L{_ErrorIf}
    @param error_if: The error reporting function
    @return: dict from minor number to (disk_uuid, instance_uuid, active)

    """
    node_drbd = {}
    for minor, disk_uuid in drbd_map[ninfo.uuid].items():
      test = disk_uuid not in disks_info
      error_if(test, constants.CV_ECLUSTERCFG, None,
               "ghost disk '%s' in temporary DRBD map", disk_uuid)
        # ghost disk should not be active, but otherwise we
        # don't give double warnings (both ghost disk and
        # unallocated minor in use)
      if test:
        node_drbd[minor] = (disk_uuid, None, False)
      else:
        disk_active = False
        disk_instance = None
        for (inst_uuid, inst) in instanceinfo.items():
          if disk_uuid in inst.disks:
            disk_active = inst.disks_active
            disk_instance = inst_uuid
            break
        node_drbd[minor] = (disk_uuid, disk_instance, disk_active)
    return node_drbd

  def _VerifyNodeDrbd(self, ninfo, nresult, instanceinfo, disks_info,
                      drbd_helper, drbd_map):
    """Verifies and the node DRBD status.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param instanceinfo: the dict of instances
    @param disks_info: the dict of disks
    @param drbd_helper: the configured DRBD usermode helper
    @param drbd_map: the DRBD map as returned by
        L{ganeti.config.ConfigWriter.ComputeDRBDMap}

    """
    self._VerifyNodeDrbdHelper(ninfo, nresult, drbd_helper)

    # compute the DRBD minors
    node_drbd = self._ComputeDrbdMinors(ninfo, instanceinfo, disks_info,
                                        drbd_map, self._ErrorIf)

    # and now check them
    used_minors = nresult.get(constants.NV_DRBDLIST, [])
    test = not isinstance(used_minors, (tuple, list))
    self._ErrorIf(test, constants.CV_ENODEDRBD, ninfo.name,
                  "cannot parse drbd status file: %s", str(used_minors))
    if test:
      # we cannot check drbd status
      return

    for minor, (disk_uuid, inst_uuid, must_exist) in node_drbd.items():
      test = minor not in used_minors and must_exist
      if inst_uuid is not None:
        attached = "(attached in instance '%s')" % \
          self.cfg.GetInstanceName(inst_uuid)
      else:
        attached = "(detached)"
      self._ErrorIf(test, constants.CV_ENODEDRBD, ninfo.name,
                    "drbd minor %d of disk %s %s is not active",
                    minor, disk_uuid, attached)
    for minor in used_minors:
      test = minor not in node_drbd
      self._ErrorIf(test, constants.CV_ENODEDRBD, ninfo.name,
                    "unallocated drbd minor %d is in use", minor)

  def _UpdateNodeOS(self, ninfo, nresult, nimg):
    """Builds the node OS structures.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object

    """
    remote_os = nresult.get(constants.NV_OSLIST, None)
    test = (not isinstance(remote_os, list) or
            not compat.all(isinstance(v, list) and len(v) == 8
                           for v in remote_os))

    self._ErrorIf(test, constants.CV_ENODEOS, ninfo.name,
                  "node hasn't returned valid OS data")

    nimg.os_fail = test

    if test:
      return

    os_dict = {}

    for (name, os_path, status, diagnose,
         variants, parameters, api_ver,
         trusted) in nresult[constants.NV_OSLIST]:

      if name not in os_dict:
        os_dict[name] = []

      # parameters is a list of lists instead of list of tuples due to
      # JSON lacking a real tuple type, fix it:
      parameters = [tuple(v) for v in parameters]
      os_dict[name].append((os_path, status, diagnose,
                            set(variants), set(parameters), set(api_ver),
                            trusted))

    nimg.oslist = os_dict

  def _VerifyNodeOS(self, ninfo, nimg, base):
    """Verifies the node OS list.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nimg: the node image object
    @param base: the 'template' node we match against (e.g. from the master)

    """
    assert not nimg.os_fail, "Entered _VerifyNodeOS with failed OS rpc?"

    beautify_params = lambda l: ["%s: %s" % (k, v) for (k, v) in l]
    for os_name, os_data in nimg.oslist.items():
      assert os_data, "Empty OS status for OS %s?!" % os_name
      f_path, f_status, f_diag, f_var, f_param, f_api, f_trusted = os_data[0]
      self._ErrorIf(not f_status, constants.CV_ENODEOS, ninfo.name,
                    "Invalid OS %s (located at %s): %s",
                    os_name, f_path, f_diag)
      self._ErrorIf(len(os_data) > 1, constants.CV_ENODEOS, ninfo.name,
                    "OS '%s' has multiple entries"
                    " (first one shadows the rest): %s",
                    os_name, utils.CommaJoin([v[0] for v in os_data]))
      # comparisons with the 'base' image
      test = os_name not in base.oslist
      self._ErrorIf(test, constants.CV_ENODEOS, ninfo.name,
                    "Extra OS %s not present on reference node (%s)",
                    os_name, self.cfg.GetNodeName(base.uuid))
      if test:
        continue
      assert base.oslist[os_name], "Base node has empty OS status?"
      _, b_status, _, b_var, b_param, b_api, b_trusted = base.oslist[os_name][0]
      if not b_status:
        # base OS is invalid, skipping
        continue
      for kind, a, b in [("API version", f_api, b_api),
                         ("variants list", f_var, b_var),
                         ("parameters", beautify_params(f_param),
                          beautify_params(b_param))]:
        self._ErrorIf(a != b, constants.CV_ENODEOS, ninfo.name,
                      "OS %s for %s differs from reference node %s:"
                      " [%s] vs. [%s]", kind, os_name,
                      self.cfg.GetNodeName(base.uuid),
                      utils.CommaJoin(sorted(a)), utils.CommaJoin(sorted(b)))
      for kind, a, b in [("trusted", f_trusted, b_trusted)]:
        self._ErrorIf(a != b, constants.CV_ENODEOS, ninfo.name,
                      "OS %s for %s differs from reference node %s:"
                      " %s vs. %s", kind, os_name,
                      self.cfg.GetNodeName(base.uuid), a, b)

    # check any missing OSes
    missing = set(base.oslist.keys()).difference(nimg.oslist.keys())
    self._ErrorIf(missing, constants.CV_ENODEOS, ninfo.name,
                  "OSes present on reference node %s"
                  " but missing on this node: %s",
                  self.cfg.GetNodeName(base.uuid), utils.CommaJoin(missing))

  def _VerifyAcceptedFileStoragePaths(self, ninfo, nresult, is_master):
    """Verifies paths in L{pathutils.FILE_STORAGE_PATHS_FILE}.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @type is_master: bool
    @param is_master: Whether node is the master node

    """
    cluster = self.cfg.GetClusterInfo()
    if (is_master and
        (cluster.IsFileStorageEnabled() or
         cluster.IsSharedFileStorageEnabled())):
      try:
        fspaths = nresult[constants.NV_ACCEPTED_STORAGE_PATHS]
      except KeyError:
        # This should never happen
        self._ErrorIf(True, constants.CV_ENODEFILESTORAGEPATHS, ninfo.name,
                      "Node did not return forbidden file storage paths")
      else:
        self._ErrorIf(fspaths, constants.CV_ENODEFILESTORAGEPATHS, ninfo.name,
                      "Found forbidden file storage paths: %s",
                      utils.CommaJoin(fspaths))
    else:
      self._ErrorIf(constants.NV_ACCEPTED_STORAGE_PATHS in nresult,
                    constants.CV_ENODEFILESTORAGEPATHS, ninfo.name,
                    "Node should not have returned forbidden file storage"
                    " paths")

  def _VerifyStoragePaths(self, ninfo, nresult, file_disk_template,
                          verify_key, error_key):
    """Verifies (file) storage paths.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @type file_disk_template: string
    @param file_disk_template: file-based disk template, whose directory
        is supposed to be verified
    @type verify_key: string
    @param verify_key: key for the verification map of this file
        verification step
    @param error_key: error key to be added to the verification results
        in case something goes wrong in this verification step

    """
    assert (file_disk_template in utils.storage.GetDiskTemplatesOfStorageTypes(
              constants.ST_FILE, constants.ST_SHARED_FILE, constants.ST_GLUSTER
           ))

    cluster = self.cfg.GetClusterInfo()
    if cluster.IsDiskTemplateEnabled(file_disk_template):
      self._ErrorIf(
          verify_key in nresult,
          error_key, ninfo.name,
          "The configured %s storage path is unusable: %s" %
          (file_disk_template, nresult.get(verify_key)))

  def _VerifyFileStoragePaths(self, ninfo, nresult):
    """Verifies (file) storage paths.

    @see: C{_VerifyStoragePaths}

    """
    self._VerifyStoragePaths(
        ninfo, nresult, constants.DT_FILE,
        constants.NV_FILE_STORAGE_PATH,
        constants.CV_ENODEFILESTORAGEPATHUNUSABLE)

  def _VerifySharedFileStoragePaths(self, ninfo, nresult):
    """Verifies (file) storage paths.

    @see: C{_VerifyStoragePaths}

    """
    self._VerifyStoragePaths(
        ninfo, nresult, constants.DT_SHARED_FILE,
        constants.NV_SHARED_FILE_STORAGE_PATH,
        constants.CV_ENODESHAREDFILESTORAGEPATHUNUSABLE)

  def _VerifyGlusterStoragePaths(self, ninfo, nresult):
    """Verifies (file) storage paths.

    @see: C{_VerifyStoragePaths}

    """
    self._VerifyStoragePaths(
        ninfo, nresult, constants.DT_GLUSTER,
        constants.NV_GLUSTER_STORAGE_PATH,
        constants.CV_ENODEGLUSTERSTORAGEPATHUNUSABLE)

  def _VerifyOob(self, ninfo, nresult):
    """Verifies out of band functionality of a node.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node

    """
    # We just have to verify the paths on master and/or master candidates
    # as the oob helper is invoked on the master
    if ((ninfo.master_candidate or ninfo.master_capable) and
        constants.NV_OOB_PATHS in nresult):
      for path_result in nresult[constants.NV_OOB_PATHS]:
        self._ErrorIf(path_result, constants.CV_ENODEOOBPATH,
                      ninfo.name, path_result)

  def _UpdateNodeVolumes(self, ninfo, nresult, nimg, vg_name):
    """Verifies and updates the node volume data.

    This function will update a L{NodeImage}'s internal structures
    with data from the remote call.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object
    @param vg_name: the configured VG name

    """
    nimg.lvm_fail = True
    lvdata = nresult.get(constants.NV_LVLIST, "Missing LV data")
    if vg_name is None:
      pass
    elif isinstance(lvdata, basestring):
      self._ErrorIf(True, constants.CV_ENODELVM, ninfo.name,
                    "LVM problem on node: %s", utils.SafeEncode(lvdata))
    elif not isinstance(lvdata, dict):
      self._ErrorIf(True, constants.CV_ENODELVM, ninfo.name,
                    "rpc call to node failed (lvlist)")
    else:
      nimg.volumes = lvdata
      nimg.lvm_fail = False

  def _UpdateNodeInstances(self, ninfo, nresult, nimg):
    """Verifies and updates the node instance list.

    If the listing was successful, then updates this node's instance
    list. Otherwise, it marks the RPC call as failed for the instance
    list key.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object

    """
    idata = nresult.get(constants.NV_INSTANCELIST, None)
    test = not isinstance(idata, list)
    self._ErrorIf(test, constants.CV_ENODEHV, ninfo.name,
                  "rpc call to node failed (instancelist): %s",
                  utils.SafeEncode(str(idata)))
    if test:
      nimg.hyp_fail = True
    else:
      nimg.instances = [uuid for (uuid, _) in
                        self.cfg.GetMultiInstanceInfoByName(idata)]

  def _UpdateNodeInfo(self, ninfo, nresult, nimg, vg_name):
    """Verifies and computes a node information map

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param nimg: the node image object
    @param vg_name: the configured VG name

    """
    # try to read free memory (from the hypervisor)
    hv_info = nresult.get(constants.NV_HVINFO, None)
    test = not isinstance(hv_info, dict) or "memory_free" not in hv_info
    self._ErrorIf(test, constants.CV_ENODEHV, ninfo.name,
                  "rpc call to node failed (hvinfo)")
    if not test:
      try:
        nimg.mfree = int(hv_info["memory_free"])
      except (ValueError, TypeError):
        self._ErrorIf(True, constants.CV_ENODERPC, ninfo.name,
                      "node returned invalid nodeinfo, check hypervisor")

    # FIXME: devise a free space model for file based instances as well
    if vg_name is not None:
      test = (constants.NV_VGLIST not in nresult or
              vg_name not in nresult[constants.NV_VGLIST])
      self._ErrorIf(test, constants.CV_ENODELVM, ninfo.name,
                    "node didn't return data for the volume group '%s'"
                    " - it is either missing or broken", vg_name)
      if not test:
        try:
          nimg.dfree = int(nresult[constants.NV_VGLIST][vg_name])
        except (ValueError, TypeError):
          self._ErrorIf(True, constants.CV_ENODERPC, ninfo.name,
                        "node returned invalid LVM info, check LVM status")

  def _CollectDiskInfo(self, node_uuids, node_image, instanceinfo):
    """Gets per-disk status information for all instances.

    @type node_uuids: list of strings
    @param node_uuids: Node UUIDs
    @type node_image: dict of (UUID, L{objects.Node})
    @param node_image: Node objects
    @type instanceinfo: dict of (UUID, L{objects.Instance})
    @param instanceinfo: Instance objects
    @rtype: {instance: {node: [(succes, payload)]}}
    @return: a dictionary of per-instance dictionaries with nodes as
        keys and disk information as values; the disk information is a
        list of tuples (success, payload)

    """
    node_disks = {}
    node_disks_dev_inst_only = {}
    diskless_instances = set()
    nodisk_instances = set()

    for nuuid in node_uuids:
      node_inst_uuids = list(itertools.chain(node_image[nuuid].pinst,
                                             node_image[nuuid].sinst))
      diskless_instances.update(uuid for uuid in node_inst_uuids
                                if not instanceinfo[uuid].disks)
      disks = [(inst_uuid, disk)
               for inst_uuid in node_inst_uuids
               for disk in self.cfg.GetInstanceDisks(inst_uuid)]

      if not disks:
        nodisk_instances.update(uuid for uuid in node_inst_uuids
                                if instanceinfo[uuid].disks)
        # No need to collect data
        continue

      node_disks[nuuid] = disks

      # _AnnotateDiskParams makes already copies of the disks
      dev_inst_only = []
      for (inst_uuid, dev) in disks:
        (anno_disk,) = AnnotateDiskParams(instanceinfo[inst_uuid], [dev],
                                          self.cfg)
        dev_inst_only.append((anno_disk, instanceinfo[inst_uuid]))

      node_disks_dev_inst_only[nuuid] = dev_inst_only

    assert len(node_disks) == len(node_disks_dev_inst_only)

    # Collect data from all nodes with disks
    result = self.rpc.call_blockdev_getmirrorstatus_multi(
               node_disks.keys(), node_disks_dev_inst_only)

    assert len(result) == len(node_disks)

    instdisk = {}

    for (nuuid, nres) in result.items():
      node = self.cfg.GetNodeInfo(nuuid)
      disks = node_disks[node.uuid]

      if nres.offline:
        # No data from this node
        data = len(disks) * [(False, "node offline")]
      else:
        msg = nres.fail_msg
        self._ErrorIf(msg, constants.CV_ENODERPC, node.name,
                      "while getting disk information: %s", msg)
        if msg:
          # No data from this node
          data = len(disks) * [(False, msg)]
        else:
          data = []
          for idx, i in enumerate(nres.payload):
            if isinstance(i, (tuple, list)) and len(i) == 2:
              data.append(i)
            else:
              logging.warning("Invalid result from node %s, entry %d: %s",
                              node.name, idx, i)
              data.append((False, "Invalid result from the remote node"))

      for ((inst_uuid, _), status) in zip(disks, data):
        instdisk.setdefault(inst_uuid, {}).setdefault(node.uuid, []) \
          .append(status)

    # Add empty entries for diskless instances.
    for inst_uuid in diskless_instances:
      assert inst_uuid not in instdisk
      instdisk[inst_uuid] = {}
    # ...and disk-full instances that happen to have no disks
    for inst_uuid in nodisk_instances:
      assert inst_uuid not in instdisk
      instdisk[inst_uuid] = {}

    assert compat.all(len(statuses) == len(instanceinfo[inst].disks) and
                      len(nuuids) <= len(
                        self.cfg.GetInstanceNodes(instanceinfo[inst].uuid)) and
                      compat.all(isinstance(s, (tuple, list)) and
                                 len(s) == 2 for s in statuses)
                      for inst, nuuids in instdisk.items()
                      for nuuid, statuses in nuuids.items())
    if __debug__:
      instdisk_keys = set(instdisk)
      instanceinfo_keys = set(instanceinfo)
      assert instdisk_keys == instanceinfo_keys, \
        ("instdisk keys (%s) do not match instanceinfo keys (%s)" %
         (instdisk_keys, instanceinfo_keys))

    return instdisk

  @staticmethod
  def _SshNodeSelector(group_uuid, all_nodes):
    """Create endless iterators for all potential SSH check hosts.

    """
    nodes = [node for node in all_nodes
             if (node.group != group_uuid and
                 not node.offline)]
    keyfunc = operator.attrgetter("group")

    return map(itertools.cycle,
               [sorted(n.name for n in names)
                for _, names in itertools.groupby(sorted(nodes, key=keyfunc),
                                                  keyfunc)])

  @classmethod
  def _SelectSshCheckNodes(cls, group_nodes, group_uuid, all_nodes):
    """Choose which nodes should talk to which other nodes.

    We will make nodes contact all nodes in their group, and one node from
    every other group.

    @rtype: tuple of (string, dict of strings to list of strings, string)
    @return: a tuple containing the list of all online nodes, a dictionary
      mapping node names to additional nodes of other node groups to which
      connectivity should be tested, and a list of all online master
      candidates

    @warning: This algorithm has a known issue if one node group is much
      smaller than others (e.g. just one node). In such a case all other
      nodes will talk to the single node.

    """
    online_nodes = sorted(node.name for node in group_nodes if not node.offline)
    online_mcs = sorted(node.name for node in group_nodes
                        if (node.master_candidate and not node.offline))
    sel = cls._SshNodeSelector(group_uuid, all_nodes)

    return (online_nodes,
            dict((name, sorted([i.next() for i in sel]))
                 for name in online_nodes),
            online_mcs)

  def _PrepareSshSetupCheck(self):
    """Prepare the input data for the SSH setup verification.

    """
    all_nodes_info = self.cfg.GetAllNodesInfo()
    potential_master_candidates = self.cfg.GetPotentialMasterCandidates()
    node_status = [
      (uuid, node_info.name, node_info.master_candidate,
       node_info.name in potential_master_candidates, not node_info.offline)
      for (uuid, node_info) in all_nodes_info.items()]
    return node_status

  def BuildHooksEnv(self):
    """Build hooks env.

    Cluster-Verify hooks just ran in the post phase and their failure makes
    the output be logged in the verify output and the verification to fail.

    """
    env = {
      "CLUSTER_TAGS": " ".join(self.cfg.GetClusterInfo().GetTags()),
      }

    env.update(("NODE_TAGS_%s" % node.name, " ".join(node.GetTags()))
               for node in self.my_node_info.values())

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([], list(self.my_node_info.keys()))

  @staticmethod
  def _VerifyOtherNotes(feedback_fn, i_non_redundant, i_non_a_balanced,
                        i_offline, n_offline, n_drained):
    feedback_fn("* Other Notes")
    if i_non_redundant:
      feedback_fn("  - NOTICE: %d non-redundant instance(s) found."
                  % len(i_non_redundant))

    if i_non_a_balanced:
      feedback_fn("  - NOTICE: %d non-auto-balanced instance(s) found."
                  % len(i_non_a_balanced))

    if i_offline:
      feedback_fn("  - NOTICE: %d offline instance(s) found." % i_offline)

    if n_offline:
      feedback_fn("  - NOTICE: %d offline node(s) found." % n_offline)

    if n_drained:
      feedback_fn("  - NOTICE: %d drained node(s) found." % n_drained)

  def _VerifyExclusionTags(self, nodename, pinst, ctags):
    """Verify that all instances have different exclusion tags.

    @type nodename: string
    @param nodename: the name of the node for which the check is done
    @type pinst: list of string
    @param pinst: list of UUIDs of those instances having the given node
        as primary node
    @type ctags: list of string
    @param ctags: tags of the cluster

    """
    exclusion_prefixes = utils.GetExclusionPrefixes(ctags)
    tags_seen = set([])
    conflicting_tags = set([])
    for iuuid in pinst:
      allitags = self.my_inst_info[iuuid].tags
      if allitags is None:
        allitags = []
      itags = set([tag for tag in allitags
                   if utils.IsGoodTag(exclusion_prefixes, tag)])
      conflicts = itags.intersection(tags_seen)
      if len(conflicts) > 0:
        conflicting_tags = conflicting_tags.union(conflicts)
      tags_seen = tags_seen.union(itags)

    self._ErrorIf(len(conflicting_tags) > 0, constants.CV_EEXTAGS, nodename,
                  "Tags where there is more than one instance: %s",
                  list(conflicting_tags), code=constants.CV_WARNING)

  def Exec(self, feedback_fn): # pylint: disable=R0915
    """Verify integrity of the node group, performing various test on nodes.

    """
    # This method has too many local variables. pylint: disable=R0914
    feedback_fn("* Verifying group '%s'" % self.group_info.name)

    if not self.my_node_uuids:
      # empty node group
      feedback_fn("* Empty node group, skipping verification")
      return True

    self.bad = False
    verbose = self.op.verbose
    self._feedback_fn = feedback_fn

    vg_name = self.cfg.GetVGName()
    drbd_helper = self.cfg.GetDRBDHelper()
    cluster = self.cfg.GetClusterInfo()
    hypervisors = cluster.enabled_hypervisors
    node_data_list = self.my_node_info.values()

    i_non_redundant = [] # Non redundant instances
    i_non_a_balanced = [] # Non auto-balanced instances
    i_offline = 0 # Count of offline instances
    n_offline = 0 # Count of offline nodes
    n_drained = 0 # Count of nodes being drained
    node_vol_should = {}

    # FIXME: verify OS list

    # File verification
    filemap = ComputeAncillaryFiles(cluster, False)

    # do local checksums
    master_node_uuid = self.master_node = self.cfg.GetMasterNode()
    master_ip = self.cfg.GetMasterIP()

    online_master_candidates = sorted(
        node.name for node in node_data_list
        if (node.master_candidate and not node.offline))

    feedback_fn("* Gathering data (%d nodes)" % len(self.my_node_uuids))

    user_scripts = []
    if self.cfg.GetUseExternalMipScript():
      user_scripts.append(pathutils.EXTERNAL_MASTER_SETUP_SCRIPT)

    online_nodes = [(node.name, node.primary_ip, node.secondary_ip)
                    for node in node_data_list if not node.offline]
    node_nettest_params = (online_nodes, online_master_candidates)

    node_verify_param = {
      constants.NV_FILELIST:
        [vcluster.MakeVirtualPath(f)
         for f in utils.UniqueSequence(filename
                                       for files in filemap
                                       for filename in files)],
      constants.NV_NODELIST:
        self._SelectSshCheckNodes(node_data_list, self.group_uuid,
                                  self.all_node_info.values()),
      constants.NV_HYPERVISOR: hypervisors,
      constants.NV_HVPARAMS:
        _GetAllHypervisorParameters(cluster, self.all_inst_info.values()),
      constants.NV_NODENETTEST: node_nettest_params,
      constants.NV_INSTANCELIST: hypervisors,
      constants.NV_VERSION: None,
      constants.NV_HVINFO: self.cfg.GetHypervisorType(),
      constants.NV_NODESETUP: None,
      constants.NV_TIME: None,
      constants.NV_MASTERIP: (self.cfg.GetMasterNodeName(), master_ip,
                              online_master_candidates),
      constants.NV_OSLIST: None,
      constants.NV_NONVMNODES: self.cfg.GetNonVmCapableNodeNameList(),
      constants.NV_USERSCRIPTS: user_scripts,
      constants.NV_CLIENT_CERT: None,
      }

    if self.cfg.GetClusterInfo().modify_ssh_setup:
      node_verify_param[constants.NV_SSH_SETUP] = \
        (self._PrepareSshSetupCheck(), self.cfg.GetClusterInfo().ssh_key_type)
      if self.op.verify_clutter:
        node_verify_param[constants.NV_SSH_CLUTTER] = True

    if vg_name is not None:
      node_verify_param[constants.NV_VGLIST] = None
      node_verify_param[constants.NV_LVLIST] = vg_name
      node_verify_param[constants.NV_PVLIST] = [vg_name]

    if cluster.IsDiskTemplateEnabled(constants.DT_DRBD8):
      if drbd_helper:
        node_verify_param[constants.NV_DRBDVERSION] = None
        node_verify_param[constants.NV_DRBDLIST] = None
        node_verify_param[constants.NV_DRBDHELPER] = drbd_helper

    if cluster.IsFileStorageEnabled() or \
        cluster.IsSharedFileStorageEnabled():
      # Load file storage paths only from master node
      node_verify_param[constants.NV_ACCEPTED_STORAGE_PATHS] = \
        self.cfg.GetMasterNodeName()
      if cluster.IsFileStorageEnabled():
        node_verify_param[constants.NV_FILE_STORAGE_PATH] = \
          cluster.file_storage_dir
      if cluster.IsSharedFileStorageEnabled():
        node_verify_param[constants.NV_SHARED_FILE_STORAGE_PATH] = \
          cluster.shared_file_storage_dir

    # bridge checks
    # FIXME: this needs to be changed per node-group, not cluster-wide
    bridges = set()
    default_nicpp = cluster.nicparams[constants.PP_DEFAULT]
    if default_nicpp[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
      bridges.add(default_nicpp[constants.NIC_LINK])
    for inst_uuid in self.my_inst_info.values():
      for nic in inst_uuid.nics:
        full_nic = cluster.SimpleFillNIC(nic.nicparams)
        if full_nic[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
          bridges.add(full_nic[constants.NIC_LINK])

    if bridges:
      node_verify_param[constants.NV_BRIDGES] = list(bridges)

    # Build our expected cluster state
    node_image = dict((node.uuid, self.NodeImage(offline=node.offline,
                                                 uuid=node.uuid,
                                                 vm_capable=node.vm_capable))
                      for node in node_data_list)

    # Gather OOB paths
    oob_paths = []
    for node in self.all_node_info.values():
      path = SupportsOob(self.cfg, node)
      if path and path not in oob_paths:
        oob_paths.append(path)

    if oob_paths:
      node_verify_param[constants.NV_OOB_PATHS] = oob_paths

    for inst_uuid in self.my_inst_uuids:
      instance = self.my_inst_info[inst_uuid]
      if instance.admin_state == constants.ADMINST_OFFLINE:
        i_offline += 1

      inst_nodes = self.cfg.GetInstanceNodes(instance.uuid)
      for nuuid in inst_nodes:
        if nuuid not in node_image:
          gnode = self.NodeImage(uuid=nuuid)
          gnode.ghost = (nuuid not in self.all_node_info)
          node_image[nuuid] = gnode

      self.cfg.GetInstanceLVsByNode(instance.uuid, lvmap=node_vol_should)

      pnode = instance.primary_node
      node_image[pnode].pinst.append(instance.uuid)

      for snode in self.cfg.GetInstanceSecondaryNodes(instance.uuid):
        nimg = node_image[snode]
        nimg.sinst.append(instance.uuid)
        if pnode not in nimg.sbp:
          nimg.sbp[pnode] = []
        nimg.sbp[pnode].append(instance.uuid)

    es_flags = rpc.GetExclusiveStorageForNodes(self.cfg,
                                               self.my_node_info.keys())
    # The value of exclusive_storage should be the same across the group, so if
    # it's True for at least a node, we act as if it were set for all the nodes
    self._exclusive_storage = compat.any(es_flags.values())
    if self._exclusive_storage:
      node_verify_param[constants.NV_EXCLUSIVEPVS] = True

    # At this point, we have the in-memory data structures complete,
    # except for the runtime information, which we'll gather next

    # NOTE: Here we lock the configuration for the duration of RPC calls,
    # which means that the cluster configuration changes are blocked during
    # this period.
    # This is something that should be done only exceptionally and only for
    # justified cases!
    # In this case, we need the lock as we can only verify the integrity of
    # configuration files on MCs only if we know nobody else is modifying it.
    # FIXME: The check for integrity of config.data should be moved to
    # WConfD, which is the only one who can otherwise ensure nobody
    # will modify the configuration during the check.
    with self.cfg.GetConfigManager(shared=True, forcelock=True):
      feedback_fn("* Gathering information about nodes (%s nodes)" %
                  len(self.my_node_uuids))
      # Force the configuration to be fully distributed before doing any tests
      self.cfg.FlushConfigGroup(self.group_uuid)
      # Due to the way our RPC system works, exact response times cannot be
      # guaranteed (e.g. a broken node could run into a timeout). By keeping
      # the time before and after executing the request, we can at least have
      # a time window.
      nvinfo_starttime = time.time()
      # Get lock on the configuration so that nobody modifies it concurrently.
      # Otherwise it can be modified by other jobs, failing the consistency
      # test.
      # NOTE: This is an exceptional situation, we should otherwise avoid
      # locking the configuration for something but very fast, pure operations.
      cluster_name = self.cfg.GetClusterName()
      hvparams = self.cfg.GetClusterInfo().hvparams

      all_nvinfo = self.rpc.call_node_verify(self.my_node_uuids,
                                             node_verify_param,
                                             cluster_name,
                                             hvparams)
      nvinfo_endtime = time.time()

      if self.extra_lv_nodes and vg_name is not None:
        feedback_fn("* Gathering information about extra nodes (%s nodes)" %
                    len(self.extra_lv_nodes))
        extra_lv_nvinfo = \
            self.rpc.call_node_verify(self.extra_lv_nodes,
                                      {constants.NV_LVLIST: vg_name},
                                      self.cfg.GetClusterName(),
                                      self.cfg.GetClusterInfo().hvparams)
      else:
        extra_lv_nvinfo = {}

      # If not all nodes are being checked, we need to make sure the master
      # node and a non-checked vm_capable node are in the list.
      absent_node_uuids = set(self.all_node_info).difference(self.my_node_info)
      if absent_node_uuids:
        vf_nvinfo = all_nvinfo.copy()
        vf_node_info = list(self.my_node_info.values())
        additional_node_uuids = []
        if master_node_uuid not in self.my_node_info:
          additional_node_uuids.append(master_node_uuid)
          vf_node_info.append(self.all_node_info[master_node_uuid])
        # Add the first vm_capable node we find which is not included,
        # excluding the master node (which we already have)
        for node_uuid in absent_node_uuids:
          nodeinfo = self.all_node_info[node_uuid]
          if (nodeinfo.vm_capable and not nodeinfo.offline and
              node_uuid != master_node_uuid):
            additional_node_uuids.append(node_uuid)
            vf_node_info.append(self.all_node_info[node_uuid])
            break
        key = constants.NV_FILELIST

        feedback_fn("* Gathering information about the master node")
        vf_nvinfo.update(self.rpc.call_node_verify(
           additional_node_uuids, {key: node_verify_param[key]},
           self.cfg.GetClusterName(), self.cfg.GetClusterInfo().hvparams))
      else:
        vf_nvinfo = all_nvinfo
        vf_node_info = self.my_node_info.values()

    all_drbd_map = self.cfg.ComputeDRBDMap()

    feedback_fn("* Gathering disk information (%s nodes)" %
                len(self.my_node_uuids))
    instdisk = self._CollectDiskInfo(self.my_node_info.keys(), node_image,
                                     self.my_inst_info)

    feedback_fn("* Verifying configuration file consistency")

    self._VerifyClientCertificates(self.my_node_info.values(), all_nvinfo)
    if self.cfg.GetClusterInfo().modify_ssh_setup:
      self._VerifySshSetup(self.my_node_info.values(), all_nvinfo)
    self._VerifyFiles(vf_node_info, master_node_uuid, vf_nvinfo, filemap)

    feedback_fn("* Verifying node status")

    refos_img = None

    for node_i in node_data_list:
      nimg = node_image[node_i.uuid]

      if node_i.offline:
        if verbose:
          feedback_fn("* Skipping offline node %s" % (node_i.name,))
        n_offline += 1
        continue

      if node_i.uuid == master_node_uuid:
        ntype = "master"
      elif node_i.master_candidate:
        ntype = "master candidate"
      elif node_i.drained:
        ntype = "drained"
        n_drained += 1
      else:
        ntype = "regular"
      if verbose:
        feedback_fn("* Verifying node %s (%s)" % (node_i.name, ntype))

      msg = all_nvinfo[node_i.uuid].fail_msg
      self._ErrorIf(msg, constants.CV_ENODERPC, node_i.name,
                    "while contacting node: %s", msg)
      if msg:
        nimg.rpc_fail = True
        continue

      nresult = all_nvinfo[node_i.uuid].payload

      nimg.call_ok = self._VerifyNode(node_i, nresult)
      self._VerifyNodeTime(node_i, nresult, nvinfo_starttime, nvinfo_endtime)
      self._VerifyNodeNetwork(node_i, nresult)
      self._VerifyNodeUserScripts(node_i, nresult)
      self._VerifyOob(node_i, nresult)
      self._VerifyAcceptedFileStoragePaths(node_i, nresult,
                                           node_i.uuid == master_node_uuid)
      self._VerifyFileStoragePaths(node_i, nresult)
      self._VerifySharedFileStoragePaths(node_i, nresult)
      self._VerifyGlusterStoragePaths(node_i, nresult)

      if nimg.vm_capable:
        self._UpdateVerifyNodeLVM(node_i, nresult, vg_name, nimg)
        if constants.DT_DRBD8 in cluster.enabled_disk_templates:
          self._VerifyNodeDrbd(node_i, nresult, self.all_inst_info,
                               self.all_disks_info, drbd_helper, all_drbd_map)

        if (constants.DT_PLAIN in cluster.enabled_disk_templates) or \
            (constants.DT_DRBD8 in cluster.enabled_disk_templates):
          self._UpdateNodeVolumes(node_i, nresult, nimg, vg_name)
        self._UpdateNodeInstances(node_i, nresult, nimg)
        self._UpdateNodeInfo(node_i, nresult, nimg, vg_name)
        self._UpdateNodeOS(node_i, nresult, nimg)

        if not nimg.os_fail:
          if refos_img is None:
            refos_img = nimg
          self._VerifyNodeOS(node_i, nimg, refos_img)
        self._VerifyNodeBridges(node_i, nresult, bridges)

        # Check whether all running instances are primary for the node. (This
        # can no longer be done from _VerifyInstance below, since some of the
        # wrong instances could be from other node groups.)
        non_primary_inst_uuids = set(nimg.instances).difference(nimg.pinst)

        for inst_uuid in non_primary_inst_uuids:
          test = inst_uuid in self.all_inst_info
          self._ErrorIf(test, constants.CV_EINSTANCEWRONGNODE,
                        self.cfg.GetInstanceName(inst_uuid),
                        "instance should not run on node %s", node_i.name)
          self._ErrorIf(not test, constants.CV_ENODEORPHANINSTANCE, node_i.name,
                        "node is running unknown instance %s", inst_uuid)

        self._VerifyExclusionTags(node_i.name, nimg.pinst, cluster.tags)

    self._VerifyGroupDRBDVersion(all_nvinfo)
    self._VerifyGroupLVM(node_image, vg_name)

    for node_uuid, result in extra_lv_nvinfo.items():
      self._UpdateNodeVolumes(self.all_node_info[node_uuid], result.payload,
                              node_image[node_uuid], vg_name)

    feedback_fn("* Verifying instance status")
    for inst_uuid in self.my_inst_uuids:
      instance = self.my_inst_info[inst_uuid]
      if verbose:
        feedback_fn("* Verifying instance %s" % instance.name)
      self._VerifyInstance(instance, node_image, instdisk[inst_uuid])

      # If the instance is not fully redundant we cannot survive losing its
      # primary node, so we are not N+1 compliant.
      inst_disks = self.cfg.GetInstanceDisks(instance.uuid)
      if not utils.AllDiskOfType(inst_disks, constants.DTS_MIRRORED):
        i_non_redundant.append(instance)

      if not cluster.FillBE(instance)[constants.BE_AUTO_BALANCE]:
        i_non_a_balanced.append(instance)

    feedback_fn("* Verifying orphan volumes")
    reserved = utils.FieldSet(*cluster.reserved_lvs)

    # We will get spurious "unknown volume" warnings if any node of this group
    # is secondary for an instance whose primary is in another group. To avoid
    # them, we find these instances and add their volumes to node_vol_should.
    for instance in self.all_inst_info.values():
      for secondary in self.cfg.GetInstanceSecondaryNodes(instance.uuid):
        if (secondary in self.my_node_info
            and instance.uuid not in self.my_inst_info):
          self.cfg.GetInstanceLVsByNode(instance.uuid, lvmap=node_vol_should)
          break

    self._VerifyOrphanVolumes(vg_name, node_vol_should, node_image, reserved)

    if constants.VERIFY_NPLUSONE_MEM not in self.op.skip_checks:
      feedback_fn("* Verifying N+1 Memory redundancy")
      self._VerifyNPlusOneMemory(node_image, self.my_inst_info)

    self._VerifyOtherNotes(feedback_fn, i_non_redundant, i_non_a_balanced,
                           i_offline, n_offline, n_drained)

    return not self.bad

  def HooksCallBack(self, phase, hooks_results, feedback_fn, lu_result):
    """Analyze the post-hooks' result

    This method analyses the hook result, handles it, and sends some
    nicely-formatted feedback back to the user.

    @param phase: one of L{constants.HOOKS_PHASE_POST} or
        L{constants.HOOKS_PHASE_PRE}; it denotes the hooks phase
    @param hooks_results: the results of the multi-node hooks rpc call
    @param feedback_fn: function used send feedback back to the caller
    @param lu_result: previous Exec result
    @return: the new Exec result, based on the previous result
        and hook results

    """
    # We only really run POST phase hooks, only for non-empty groups,
    # and are only interested in their results
    if not self.my_node_uuids:
      # empty node group
      pass
    elif phase == constants.HOOKS_PHASE_POST:
      # Used to change hooks' output to proper indentation
      feedback_fn("* Hooks Results")
      assert hooks_results, "invalid result from hooks"

      for node_name in hooks_results:
        res = hooks_results[node_name]
        msg = res.fail_msg
        test = msg and not res.offline
        self._ErrorIf(test, constants.CV_ENODEHOOKS, node_name,
                      "Communication failure in hooks execution: %s", msg)
        if test:
          lu_result = False
          continue
        if res.offline:
          # No need to investigate payload if node is offline
          continue
        for script, hkr, output in res.payload:
          test = hkr == constants.HKR_FAIL
          self._ErrorIf(test, constants.CV_ENODEHOOKS, node_name,
                        "Script %s failed, output:", script)
          if test:
            output = self._HOOKS_INDENT_RE.sub("      ", output)
            feedback_fn("%s" % output)
            lu_result = False

    return lu_result
