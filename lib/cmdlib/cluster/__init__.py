#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
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


"""Logical units dealing with the cluster."""

import copy
import itertools
import logging
import operator
import os
import re
import time

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti import masterd
from ganeti import netutils
from ganeti import objects
from ganeti import opcodes
from ganeti import pathutils
from ganeti import query
import ganeti.rpc.node as rpc
from ganeti import runtime
from ganeti import ssh
from ganeti import uidpool
from ganeti import utils
from ganeti import vcluster

from ganeti.cmdlib.base import NoHooksLU, QueryBase, LogicalUnit, \
  ResultWithJobs
from ganeti.cmdlib.common import ShareAll, RunPostHook, \
  ComputeAncillaryFiles, RedistributeAncillaryFiles, UploadHelper, \
  GetWantedInstances, MergeAndVerifyHvState, MergeAndVerifyDiskState, \
  GetUpdatedIPolicy, ComputeNewInstanceViolations, GetUpdatedParams, \
  CheckOSParams, CheckHVParams, AdjustCandidatePool, CheckNodePVs, \
  ComputeIPolicyInstanceViolation, AnnotateDiskParams, SupportsOob, \
  CheckIpolicyVsDiskTemplates, CheckDiskAccessModeValidity, \
  CheckDiskAccessModeConsistency, GetClientCertDigest, \
  AddInstanceCommunicationNetworkOp, ConnectInstanceCommunicationNetworkOp, \
  CheckImageValidity, EnsureKvmdOnNodes

import ganeti.masterd.instance


class LUClusterRenewCrypto(NoHooksLU):
  """Renew the cluster's crypto tokens.

  """

  _MAX_NUM_RETRIES = 3
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
    }
    self.share_locks = ShareAll()
    self.share_locks[locking.LEVEL_NODE] = 0

  def CheckPrereq(self):
    """Check prerequisites.

    Notably the compatibility of specified key bits and key type.

    """
    cluster_info = self.cfg.GetClusterInfo()

    self.ssh_key_type = self.op.ssh_key_type
    if self.ssh_key_type is None:
      self.ssh_key_type = cluster_info.ssh_key_type

    self.ssh_key_bits = ssh.DetermineKeyBits(self.ssh_key_type,
                                             self.op.ssh_key_bits,
                                             cluster_info.ssh_key_type,
                                             cluster_info.ssh_key_bits)

  def _RenewNodeSslCertificates(self, feedback_fn):
    """Renews the nodes' SSL certificates.

    Note that most of this operation is done in gnt_cluster.py, this LU only
    takes care of the renewal of the client SSL certificates.

    """
    master_uuid = self.cfg.GetMasterNode()
    cluster = self.cfg.GetClusterInfo()

    logging.debug("Renewing the master's SSL node certificate."
                  " Master's UUID: %s.", master_uuid)

    # mapping node UUIDs to client certificate digests
    digest_map = {}
    master_digest = utils.GetCertificateDigest(
        cert_filename=pathutils.NODED_CLIENT_CERT_FILE)
    digest_map[master_uuid] = master_digest
    logging.debug("Adding the master's SSL node certificate digest to the"
                  " configuration. Master's UUID: %s, Digest: %s",
                  master_uuid, master_digest)

    node_errors = {}
    nodes = self.cfg.GetAllNodesInfo()
    logging.debug("Renewing non-master nodes' node certificates.")
    for (node_uuid, node_info) in nodes.items():
      if node_info.offline:
        logging.info("* Skipping offline node %s", node_info.name)
        continue
      if node_uuid != master_uuid:
        logging.debug("Adding certificate digest of node '%s'.", node_uuid)
        last_exception = None
        for i in range(self._MAX_NUM_RETRIES):
          try:
            if node_info.master_candidate:
              node_digest = GetClientCertDigest(self, node_uuid)
              digest_map[node_uuid] = node_digest
              logging.debug("Added the node's certificate to candidate"
                            " certificate list. Current list: %s.",
                            str(cluster.candidate_certs))
            break
          except errors.OpExecError as e:
            last_exception = e
            logging.error("Could not fetch a non-master node's SSL node"
                          " certificate at attempt no. %s. The node's UUID"
                          " is %s, and the error was: %s.",
                          str(i), node_uuid, e)
        else:
          if last_exception:
            node_errors[node_uuid] = last_exception

    if node_errors:
      msg = ("Some nodes' SSL client certificates could not be fetched."
             " Please make sure those nodes are reachable and rerun"
             " the operation. The affected nodes and their errors are:\n")
      for uuid, e in node_errors.items():
        msg += "Node %s: %s\n" % (uuid, e)
      feedback_fn(msg)

    self.cfg.SetCandidateCerts(digest_map)

  def _RenewSshKeys(self, feedback_fn):
    """Renew all nodes' SSH keys.

    @type feedback_fn: function
    @param feedback_fn: logging function, see L{ganeti.cmdlist.base.LogicalUnit}

    """
    master_uuid = self.cfg.GetMasterNode()

    nodes = self.cfg.GetAllNodesInfo()
    nodes_uuid_names = [(node_uuid, node_info.name) for (node_uuid, node_info)
                        in nodes.items() if not node_info.offline]
    node_names = [name for (_, name) in nodes_uuid_names]
    node_uuids = [uuid for (uuid, _) in nodes_uuid_names]
    potential_master_candidates = self.cfg.GetPotentialMasterCandidates()
    master_candidate_uuids = self.cfg.GetMasterCandidateUuids()

    cluster_info = self.cfg.GetClusterInfo()

    result = self.rpc.call_node_ssh_keys_renew(
      [master_uuid],
      node_uuids, node_names,
      master_candidate_uuids,
      potential_master_candidates,
      cluster_info.ssh_key_type, # Old key type
      self.ssh_key_type,         # New key type
      self.ssh_key_bits)         # New key bits
    result[master_uuid].Raise("Could not renew the SSH keys of all nodes")

    # After the keys have been successfully swapped, time to commit the change
    # in key type
    cluster_info.ssh_key_type = self.ssh_key_type
    cluster_info.ssh_key_bits = self.ssh_key_bits
    self.cfg.Update(cluster_info, feedback_fn)

  def Exec(self, feedback_fn):
    if self.op.node_certificates:
      feedback_fn("Renewing Node SSL certificates")
      self._RenewNodeSslCertificates(feedback_fn)

    if self.op.renew_ssh_keys:
      if self.cfg.GetClusterInfo().modify_ssh_setup:
        feedback_fn("Renewing SSH keys")
        self._RenewSshKeys(feedback_fn)
      else:
        feedback_fn("Cannot renew SSH keys if the cluster is configured to not"
                    " modify the SSH setup.")


class LUClusterActivateMasterIp(NoHooksLU):
  """Activate the master IP on the master node.

  """
  def Exec(self, feedback_fn):
    """Activate the master IP.

    """
    master_params = self.cfg.GetMasterNetworkParameters()
    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_activate_master_ip(master_params.uuid,
                                                   master_params, ems)
    result.Raise("Could not activate the master IP")


class LUClusterDeactivateMasterIp(NoHooksLU):
  """Deactivate the master IP on the master node.

  """
  def Exec(self, feedback_fn):
    """Deactivate the master IP.

    """
    master_params = self.cfg.GetMasterNetworkParameters()
    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_deactivate_master_ip(master_params.uuid,
                                                     master_params, ems)
    result.Raise("Could not deactivate the master IP")


class LUClusterConfigQuery(NoHooksLU):
  """Return configuration values.

  """
  REQ_BGL = False

  def CheckArguments(self):
    self.cq = ClusterQuery(None, self.op.output_fields, False)

  def ExpandNames(self):
    self.cq.ExpandNames(self)

  def DeclareLocks(self, level):
    self.cq.DeclareLocks(self, level)

  def Exec(self, feedback_fn):
    result = self.cq.OldStyleQuery(self)

    assert len(result) == 1

    return result[0]


class LUClusterDestroy(LogicalUnit):
  """Logical unit for destroying the cluster.

  """
  HPATH = "cluster-destroy"
  HTYPE = constants.HTYPE_CLUSTER

  # Read by the job queue to detect when the cluster is gone and job files will
  # never be available.
  # FIXME: This variable should be removed together with the Python job queue.
  clusterHasBeenDestroyed = False

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([], [])

  def CheckPrereq(self):
    """Check prerequisites.

    This checks whether the cluster is empty.

    Any errors are signaled by raising errors.OpPrereqError.

    """
    master = self.cfg.GetMasterNode()

    nodelist = self.cfg.GetNodeList()
    if len(nodelist) != 1 or nodelist[0] != master:
      raise errors.OpPrereqError("There are still %d node(s) in"
                                 " this cluster." % (len(nodelist) - 1),
                                 errors.ECODE_INVAL)
    instancelist = self.cfg.GetInstanceList()
    if instancelist:
      raise errors.OpPrereqError("There are still %d instance(s) in"
                                 " this cluster." % len(instancelist),
                                 errors.ECODE_INVAL)

  def Exec(self, feedback_fn):
    """Destroys the cluster.

    """
    master_params = self.cfg.GetMasterNetworkParameters()

    # Run post hooks on master node before it's removed
    RunPostHook(self, self.cfg.GetNodeName(master_params.uuid))

    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_deactivate_master_ip(master_params.uuid,
                                                     master_params, ems)
    result.Warn("Error disabling the master IP address", self.LogWarning)

    self.wconfd.Client().PrepareClusterDestruction(self.wconfdcontext)

    # signal to the job queue that the cluster is gone
    LUClusterDestroy.clusterHasBeenDestroyed = True

    return master_params.uuid


class LUClusterPostInit(LogicalUnit):
  """Logical unit for running hooks after cluster initialization.

  """
  HPATH = "cluster-init"
  HTYPE = constants.HTYPE_CLUSTER

  def CheckArguments(self):
    self.master_uuid = self.cfg.GetMasterNode()
    self.master_ndparams = self.cfg.GetNdParams(self.cfg.GetMasterNodeInfo())

    # TODO: When Issue 584 is solved, and None is properly parsed when used
    # as a default value, ndparams.get(.., None) can be changed to
    # ndparams[..] to access the values directly

    # OpenvSwitch: Warn user if link is missing
    if (self.master_ndparams[constants.ND_OVS] and not
        self.master_ndparams.get(constants.ND_OVS_LINK, None)):
      self.LogInfo("No physical interface for OpenvSwitch was given."
                   " OpenvSwitch will not have an outside connection. This"
                   " might not be what you want.")

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([], [self.cfg.GetMasterNode()])

  def Exec(self, feedback_fn):
    """Create and configure Open vSwitch

    """
    if self.master_ndparams[constants.ND_OVS]:
      result = self.rpc.call_node_configure_ovs(
                 self.master_uuid,
                 self.master_ndparams[constants.ND_OVS_NAME],
                 self.master_ndparams.get(constants.ND_OVS_LINK, None))
      result.Raise("Could not successully configure Open vSwitch")

    return True


class ClusterQuery(QueryBase):
  FIELDS = query.CLUSTER_FIELDS

  #: Do not sort (there is only one item)
  SORT_FIELD = None

  def ExpandNames(self, lu):
    lu.needed_locks = {}

    # The following variables interact with _QueryBase._GetNames
    self.wanted = locking.ALL_SET
    self.do_locking = self.use_locking

    if self.do_locking:
      raise errors.OpPrereqError("Can not use locking for cluster queries",
                                 errors.ECODE_INVAL)

  def DeclareLocks(self, lu, level):
    pass

  def _GetQueryData(self, lu):
    """Computes the list of nodes and their attributes.

    """
    if query.CQ_CONFIG in self.requested_data:
      cluster = lu.cfg.GetClusterInfo()
      nodes = lu.cfg.GetAllNodesInfo()
    else:
      cluster = NotImplemented
      nodes = NotImplemented

    if query.CQ_QUEUE_DRAINED in self.requested_data:
      drain_flag = os.path.exists(pathutils.JOB_QUEUE_DRAIN_FILE)
    else:
      drain_flag = NotImplemented

    if query.CQ_WATCHER_PAUSE in self.requested_data:
      master_node_uuid = lu.cfg.GetMasterNode()

      result = lu.rpc.call_get_watcher_pause(master_node_uuid)
      result.Raise("Can't retrieve watcher pause from master node '%s'" %
                   lu.cfg.GetMasterNodeName())

      watcher_pause = result.payload
    else:
      watcher_pause = NotImplemented

    return query.ClusterQueryData(cluster, nodes, drain_flag, watcher_pause)


class LUClusterQuery(NoHooksLU):
  """Query cluster configuration.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {}

  def Exec(self, feedback_fn):
    """Return cluster config.

    """
    cluster = self.cfg.GetClusterInfo()
    os_hvp = {}

    # Filter just for enabled hypervisors
    for os_name, hv_dict in cluster.os_hvp.items():
      os_hvp[os_name] = {}
      for hv_name, hv_params in hv_dict.items():
        if hv_name in cluster.enabled_hypervisors:
          os_hvp[os_name][hv_name] = hv_params

    # Convert ip_family to ip_version
    primary_ip_version = constants.IP4_VERSION
    if cluster.primary_ip_family == netutils.IP6Address.family:
      primary_ip_version = constants.IP6_VERSION

    result = {
      "software_version": constants.RELEASE_VERSION,
      "protocol_version": constants.PROTOCOL_VERSION,
      "config_version": constants.CONFIG_VERSION,
      "os_api_version": max(constants.OS_API_VERSIONS),
      "export_version": constants.EXPORT_VERSION,
      "vcs_version": constants.VCS_VERSION,
      "architecture": runtime.GetArchInfo(),
      "name": cluster.cluster_name,
      "master": self.cfg.GetMasterNodeName(),
      "default_hypervisor": cluster.primary_hypervisor,
      "enabled_hypervisors": cluster.enabled_hypervisors,
      "hvparams": dict([(hypervisor_name, cluster.hvparams[hypervisor_name])
                        for hypervisor_name in cluster.enabled_hypervisors]),
      "os_hvp": os_hvp,
      "beparams": cluster.beparams,
      "osparams": cluster.osparams,
      "ipolicy": cluster.ipolicy,
      "nicparams": cluster.nicparams,
      "ndparams": cluster.ndparams,
      "diskparams": cluster.diskparams,
      "candidate_pool_size": cluster.candidate_pool_size,
      "max_running_jobs": cluster.max_running_jobs,
      "max_tracked_jobs": cluster.max_tracked_jobs,
      "mac_prefix": cluster.mac_prefix,
      "master_netdev": cluster.master_netdev,
      "master_netmask": cluster.master_netmask,
      "use_external_mip_script": cluster.use_external_mip_script,
      "volume_group_name": cluster.volume_group_name,
      "drbd_usermode_helper": cluster.drbd_usermode_helper,
      "file_storage_dir": cluster.file_storage_dir,
      "shared_file_storage_dir": cluster.shared_file_storage_dir,
      "maintain_node_health": cluster.maintain_node_health,
      "ctime": cluster.ctime,
      "mtime": cluster.mtime,
      "uuid": cluster.uuid,
      "tags": list(cluster.GetTags()),
      "uid_pool": cluster.uid_pool,
      "default_iallocator": cluster.default_iallocator,
      "default_iallocator_params": cluster.default_iallocator_params,
      "reserved_lvs": cluster.reserved_lvs,
      "primary_ip_version": primary_ip_version,
      "prealloc_wipe_disks": cluster.prealloc_wipe_disks,
      "hidden_os": cluster.hidden_os,
      "blacklisted_os": cluster.blacklisted_os,
      "enabled_disk_templates": cluster.enabled_disk_templates,
      "install_image": cluster.install_image,
      "instance_communication_network": cluster.instance_communication_network,
      "compression_tools": cluster.compression_tools,
      "enabled_user_shutdown": cluster.enabled_user_shutdown,
      }

    return result


class LUClusterRedistConf(NoHooksLU):
  """Force the redistribution of cluster configuration.

  This is a very simple LU.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
    }
    self.share_locks = ShareAll()

  def Exec(self, feedback_fn):
    """Redistribute the configuration.

    """
    self.cfg.Update(self.cfg.GetClusterInfo(), feedback_fn)
    RedistributeAncillaryFiles(self)


class LUClusterRename(LogicalUnit):
  """Rename the cluster.

  """
  HPATH = "cluster-rename"
  HTYPE = constants.HTYPE_CLUSTER

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_NAME": self.op.name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    return ([self.cfg.GetMasterNode()], self.cfg.GetNodeList())

  def CheckPrereq(self):
    """Verify that the passed name is a valid one.

    """
    hostname = netutils.GetHostname(name=self.op.name,
                                    family=self.cfg.GetPrimaryIPFamily())

    new_name = hostname.name
    self.ip = new_ip = hostname.ip
    old_name = self.cfg.GetClusterName()
    old_ip = self.cfg.GetMasterIP()
    if new_name == old_name and new_ip == old_ip:
      raise errors.OpPrereqError("Neither the name nor the IP address of the"
                                 " cluster has changed",
                                 errors.ECODE_INVAL)
    if new_ip != old_ip:
      if netutils.TcpPing(new_ip, constants.DEFAULT_NODED_PORT):
        raise errors.OpPrereqError("The given cluster IP address (%s) is"
                                   " reachable on the network" %
                                   new_ip, errors.ECODE_NOTUNIQUE)

    self.op.name = new_name

  def Exec(self, feedback_fn):
    """Rename the cluster.

    """
    clustername = self.op.name
    new_ip = self.ip

    # shutdown the master IP
    master_params = self.cfg.GetMasterNetworkParameters()
    ems = self.cfg.GetUseExternalMipScript()
    result = self.rpc.call_node_deactivate_master_ip(master_params.uuid,
                                                     master_params, ems)
    result.Raise("Could not disable the master role")

    try:
      cluster = self.cfg.GetClusterInfo()
      cluster.cluster_name = clustername
      cluster.master_ip = new_ip
      self.cfg.Update(cluster, feedback_fn)

      # update the known hosts file
      ssh.WriteKnownHostsFile(self.cfg, pathutils.SSH_KNOWN_HOSTS_FILE)
      node_list = self.cfg.GetOnlineNodeList()
      try:
        node_list.remove(master_params.uuid)
      except ValueError:
        pass
      UploadHelper(self, node_list, pathutils.SSH_KNOWN_HOSTS_FILE)
    finally:
      master_params.ip = new_ip
      result = self.rpc.call_node_activate_master_ip(master_params.uuid,
                                                     master_params, ems)
      result.Warn("Could not re-enable the master role on the master,"
                  " please restart manually", self.LogWarning)

    return clustername


class LUClusterRepairDiskSizes(NoHooksLU):
  """Verifies the cluster disks sizes.

  """
  REQ_BGL = False

  def ExpandNames(self):
    if self.op.instances:
      (_, self.wanted_names) = GetWantedInstances(self, self.op.instances)
      # Not getting the node allocation lock as only a specific set of
      # instances (and their nodes) is going to be acquired
      self.needed_locks = {
        locking.LEVEL_NODE_RES: [],
        locking.LEVEL_INSTANCE: self.wanted_names,
        }
      self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE
    else:
      self.wanted_names = None
      self.needed_locks = {
        locking.LEVEL_NODE_RES: locking.ALL_SET,
        locking.LEVEL_INSTANCE: locking.ALL_SET,
        }

    self.share_locks = {
      locking.LEVEL_NODE_RES: 1,
      locking.LEVEL_INSTANCE: 0,
      }

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE_RES and self.wanted_names is not None:
      self._LockInstancesNodes(primary_only=True, level=level)

  def CheckPrereq(self):
    """Check prerequisites.

    This only checks the optional instance list against the existing names.

    """
    if self.wanted_names is None:
      self.wanted_names = self.owned_locks(locking.LEVEL_INSTANCE)

    self.wanted_instances = [
      info
      for (_, info) in self.cfg.GetMultiInstanceInfoByName(self.wanted_names)
    ]

  def _EnsureChildSizes(self, disk):
    """Ensure children of the disk have the needed disk size.

    This is valid mainly for DRBD8 and fixes an issue where the
    children have smaller disk size.

    @param disk: an L{ganeti.objects.Disk} object

    """
    if disk.dev_type == constants.DT_DRBD8:
      assert disk.children, "Empty children for DRBD8?"
      fchild = disk.children[0]
      mismatch = fchild.size < disk.size
      if mismatch:
        self.LogInfo("Child disk has size %d, parent %d, fixing",
                     fchild.size, disk.size)
        fchild.size = disk.size

      # and we recurse on this child only, not on the metadev
      return self._EnsureChildSizes(fchild) or mismatch
    else:
      return False

  def Exec(self, feedback_fn):
    """Verify the size of cluster disks.

    """
    # TODO: check child disks too
    # TODO: check differences in size between primary/secondary nodes
    per_node_disks = {}
    for instance in self.wanted_instances:
      pnode = instance.primary_node
      if pnode not in per_node_disks:
        per_node_disks[pnode] = []
      for idx, disk in enumerate(self.cfg.GetInstanceDisks(instance.uuid)):
        per_node_disks[pnode].append((instance, idx, disk))

    assert not (frozenset(per_node_disks) -
                frozenset(self.owned_locks(locking.LEVEL_NODE_RES))), \
      "Not owning correct locks"
    assert not self.owned_locks(locking.LEVEL_NODE)

    es_flags = rpc.GetExclusiveStorageForNodes(self.cfg,
                                               list(per_node_disks))

    changed = []
    for node_uuid, dskl in per_node_disks.items():
      if not dskl:
        # no disks on the node
        continue

      newl = [([v[2].Copy()], v[0]) for v in dskl]
      node_name = self.cfg.GetNodeName(node_uuid)
      result = self.rpc.call_blockdev_getdimensions(node_uuid, newl)
      if result.fail_msg:
        self.LogWarning("Failure in blockdev_getdimensions call to node"
                        " %s, ignoring", node_name)
        continue
      if len(result.payload) != len(dskl):
        logging.warning("Invalid result from node %s: len(dksl)=%d,"
                        " result.payload=%s", node_name, len(dskl),
                        result.payload)
        self.LogWarning("Invalid result from node %s, ignoring node results",
                        node_name)
        continue
      for ((instance, idx, disk), dimensions) in zip(dskl, result.payload):
        if dimensions is None:
          self.LogWarning("Disk %d of instance %s did not return size"
                          " information, ignoring", idx, instance.name)
          continue
        if not isinstance(dimensions, (tuple, list)):
          self.LogWarning("Disk %d of instance %s did not return valid"
                          " dimension information, ignoring", idx,
                          instance.name)
          continue
        (size, spindles) = dimensions
        if not isinstance(size, (int, long)):
          self.LogWarning("Disk %d of instance %s did not return valid"
                          " size information, ignoring", idx, instance.name)
          continue
        size = size >> 20
        if size != disk.size:
          self.LogInfo("Disk %d of instance %s has mismatched size,"
                       " correcting: recorded %d, actual %d", idx,
                       instance.name, disk.size, size)
          disk.size = size
          self.cfg.Update(disk, feedback_fn)
          changed.append((instance.name, idx, "size", size))
        if es_flags[node_uuid]:
          if spindles is None:
            self.LogWarning("Disk %d of instance %s did not return valid"
                            " spindles information, ignoring", idx,
                            instance.name)
          elif disk.spindles is None or disk.spindles != spindles:
            self.LogInfo("Disk %d of instance %s has mismatched spindles,"
                         " correcting: recorded %s, actual %s",
                         idx, instance.name, disk.spindles, spindles)
            disk.spindles = spindles
            self.cfg.Update(disk, feedback_fn)
            changed.append((instance.name, idx, "spindles", disk.spindles))
        if self._EnsureChildSizes(disk):
          self.cfg.Update(disk, feedback_fn)
          changed.append((instance.name, idx, "size", disk.size))
    return changed


def _ValidateNetmask(cfg, netmask):
  """Checks if a netmask is valid.

  @type cfg: L{config.ConfigWriter}
  @param cfg: cluster configuration
  @type netmask: int
  @param netmask: netmask to be verified
  @raise errors.OpPrereqError: if the validation fails

  """
  ip_family = cfg.GetPrimaryIPFamily()
  try:
    ipcls = netutils.IPAddress.GetClassFromIpFamily(ip_family)
  except errors.ProgrammerError:
    raise errors.OpPrereqError("Invalid primary ip family: %s." %
                               ip_family, errors.ECODE_INVAL)
  if not ipcls.ValidateNetmask(netmask):
    raise errors.OpPrereqError("CIDR netmask (%s) not valid" %
                               (netmask), errors.ECODE_INVAL)


def CheckFileBasedStoragePathVsEnabledDiskTemplates(
    logging_warn_fn, file_storage_dir, enabled_disk_templates,
    file_disk_template):
  """Checks whether the given file-based storage directory is acceptable.

  Note: This function is public, because it is also used in bootstrap.py.

  @type logging_warn_fn: function
  @param logging_warn_fn: function which accepts a string and logs it
  @type file_storage_dir: string
  @param file_storage_dir: the directory to be used for file-based instances
  @type enabled_disk_templates: list of string
  @param enabled_disk_templates: the list of enabled disk templates
  @type file_disk_template: string
  @param file_disk_template: the file-based disk template for which the
      path should be checked

  """
  assert (file_disk_template in utils.storage.GetDiskTemplatesOfStorageTypes(
            constants.ST_FILE, constants.ST_SHARED_FILE, constants.ST_GLUSTER
         ))

  file_storage_enabled = file_disk_template in enabled_disk_templates
  if file_storage_dir is not None:
    if file_storage_dir == "":
      if file_storage_enabled:
        raise errors.OpPrereqError(
            "Unsetting the '%s' storage directory while having '%s' storage"
            " enabled is not permitted." %
            (file_disk_template, file_disk_template),
            errors.ECODE_INVAL)
    else:
      if not file_storage_enabled:
        logging_warn_fn(
            "Specified a %s storage directory, although %s storage is not"
            " enabled." % (file_disk_template, file_disk_template))
  else:
    raise errors.ProgrammerError("Received %s storage dir with value"
                                 " 'None'." % file_disk_template)


def CheckFileStoragePathVsEnabledDiskTemplates(
    logging_warn_fn, file_storage_dir, enabled_disk_templates):
  """Checks whether the given file storage directory is acceptable.

  @see: C{CheckFileBasedStoragePathVsEnabledDiskTemplates}

  """
  CheckFileBasedStoragePathVsEnabledDiskTemplates(
      logging_warn_fn, file_storage_dir, enabled_disk_templates,
      constants.DT_FILE)


def CheckSharedFileStoragePathVsEnabledDiskTemplates(
    logging_warn_fn, file_storage_dir, enabled_disk_templates):
  """Checks whether the given shared file storage directory is acceptable.

  @see: C{CheckFileBasedStoragePathVsEnabledDiskTemplates}

  """
  CheckFileBasedStoragePathVsEnabledDiskTemplates(
      logging_warn_fn, file_storage_dir, enabled_disk_templates,
      constants.DT_SHARED_FILE)


def CheckGlusterStoragePathVsEnabledDiskTemplates(
    logging_warn_fn, file_storage_dir, enabled_disk_templates):
  """Checks whether the given gluster storage directory is acceptable.

  @see: C{CheckFileBasedStoragePathVsEnabledDiskTemplates}

  """
  CheckFileBasedStoragePathVsEnabledDiskTemplates(
      logging_warn_fn, file_storage_dir, enabled_disk_templates,
      constants.DT_GLUSTER)


def CheckCompressionTools(tools):
  """Check whether the provided compression tools look like executables.

  @type tools: list of string
  @param tools: The tools provided as opcode input

  """
  regex = re.compile('^[-_a-zA-Z0-9]+$')
  illegal_tools = [t for t in tools if not regex.match(t)]

  if illegal_tools:
    raise errors.OpPrereqError(
      "The tools '%s' contain illegal characters: only alphanumeric values,"
      " dashes, and underscores are allowed" % ", ".join(illegal_tools),
      errors.ECODE_INVAL
    )

  if constants.IEC_GZIP not in tools:
    raise errors.OpPrereqError("For compatibility reasons, the %s utility must"
                               " be present among the compression tools" %
                               constants.IEC_GZIP, errors.ECODE_INVAL)

  if constants.IEC_NONE in tools:
    raise errors.OpPrereqError("%s is a reserved value used for no compression,"
                               " and cannot be used as the name of a tool" %
                               constants.IEC_NONE, errors.ECODE_INVAL)


class LUClusterSetParams(LogicalUnit):
  """Change the parameters of the cluster.

  """
  HPATH = "cluster-modify"
  HTYPE = constants.HTYPE_CLUSTER
  REQ_BGL = False

  def CheckArguments(self):
    """Check parameters

    """
    if self.op.uid_pool:
      uidpool.CheckUidPool(self.op.uid_pool)

    if self.op.add_uids:
      uidpool.CheckUidPool(self.op.add_uids)

    if self.op.remove_uids:
      uidpool.CheckUidPool(self.op.remove_uids)

    if self.op.mac_prefix:
      self.op.mac_prefix = \
          utils.NormalizeAndValidateThreeOctetMacPrefix(self.op.mac_prefix)

    if self.op.master_netmask is not None:
      _ValidateNetmask(self.cfg, self.op.master_netmask)

    if self.op.diskparams:
      for dt_params in self.op.diskparams.values():
        utils.ForceDictType(dt_params, constants.DISK_DT_TYPES)
      try:
        utils.VerifyDictOptions(self.op.diskparams, constants.DISK_DT_DEFAULTS)
        CheckDiskAccessModeValidity(self.op.diskparams)
      except errors.OpPrereqError as err:
        raise errors.OpPrereqError("While verify diskparams options: %s" % err,
                                   errors.ECODE_INVAL)

    if self.op.install_image is not None:
      CheckImageValidity(self.op.install_image,
                         "Install image must be an absolute path or a URL")

  def ExpandNames(self):
    # FIXME: in the future maybe other cluster params won't require checking on
    # all nodes to be modified.
    # FIXME: This opcode changes cluster-wide settings. Is acquiring all
    # resource locks the right thing, shouldn't it be the BGL instead?
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
      locking.LEVEL_NODEGROUP: locking.ALL_SET,
    }
    self.share_locks = ShareAll()

  def BuildHooksEnv(self):
    """Build hooks env.

    """
    return {
      "OP_TARGET": self.cfg.GetClusterName(),
      "NEW_VG_NAME": self.op.vg_name,
      }

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    mn = self.cfg.GetMasterNode()
    return ([mn], [mn])

  def _CheckVgName(self, node_uuids, enabled_disk_templates,
                   new_enabled_disk_templates):
    """Check the consistency of the vg name on all nodes and in case it gets
       unset whether there are instances still using it.

    """
    lvm_is_enabled = utils.IsLvmEnabled(enabled_disk_templates)
    lvm_gets_enabled = utils.LvmGetsEnabled(enabled_disk_templates,
                                            new_enabled_disk_templates)
    current_vg_name = self.cfg.GetVGName()

    if self.op.vg_name == '':
      if lvm_is_enabled:
        raise errors.OpPrereqError("Cannot unset volume group if lvm-based"
                                   " disk templates are or get enabled.",
                                   errors.ECODE_INVAL)

    if self.op.vg_name is None:
      if current_vg_name is None and lvm_is_enabled:
        raise errors.OpPrereqError("Please specify a volume group when"
                                   " enabling lvm-based disk-templates.",
                                   errors.ECODE_INVAL)

    if self.op.vg_name is not None and not self.op.vg_name:
      if self.cfg.DisksOfType(constants.DT_PLAIN):
        raise errors.OpPrereqError("Cannot disable lvm storage while lvm-based"
                                   " instances exist", errors.ECODE_INVAL)

    if (self.op.vg_name is not None and lvm_is_enabled) or \
        (self.cfg.GetVGName() is not None and lvm_gets_enabled):
      self._CheckVgNameOnNodes(node_uuids)

  def _CheckVgNameOnNodes(self, node_uuids):
    """Check the status of the volume group on each node.

    """
    vglist = self.rpc.call_vg_list(node_uuids)
    for node_uuid in node_uuids:
      msg = vglist[node_uuid].fail_msg
      if msg:
        # ignoring down node
        self.LogWarning("Error while gathering data on node %s"
                        " (ignoring node): %s",
                        self.cfg.GetNodeName(node_uuid), msg)
        continue
      vgstatus = utils.CheckVolumeGroupSize(vglist[node_uuid].payload,
                                            self.op.vg_name,
                                            constants.MIN_VG_SIZE)
      if vgstatus:
        raise errors.OpPrereqError("Error on node '%s': %s" %
                                   (self.cfg.GetNodeName(node_uuid), vgstatus),
                                   errors.ECODE_ENVIRON)

  @staticmethod
  def _GetDiskTemplateSetsInner(op_enabled_disk_templates,
                                old_enabled_disk_templates):
    """Computes three sets of disk templates.

    @see: C{_GetDiskTemplateSets} for more details.

    """
    enabled_disk_templates = None
    new_enabled_disk_templates = []
    disabled_disk_templates = []
    if op_enabled_disk_templates:
      enabled_disk_templates = op_enabled_disk_templates
      new_enabled_disk_templates = \
        list(set(enabled_disk_templates)
             - set(old_enabled_disk_templates))
      disabled_disk_templates = \
        list(set(old_enabled_disk_templates)
             - set(enabled_disk_templates))
    else:
      enabled_disk_templates = old_enabled_disk_templates
    return (enabled_disk_templates, new_enabled_disk_templates,
            disabled_disk_templates)

  def _GetDiskTemplateSets(self, cluster):
    """Computes three sets of disk templates.

    The three sets are:
      - disk templates that will be enabled after this operation (no matter if
        they were enabled before or not)
      - disk templates that get enabled by this operation (thus haven't been
        enabled before.)
      - disk templates that get disabled by this operation

    """
    return self._GetDiskTemplateSetsInner(self.op.enabled_disk_templates,
                                          cluster.enabled_disk_templates)

  def _CheckIpolicy(self, cluster, enabled_disk_templates):
    """Checks the ipolicy.

    @type cluster: C{objects.Cluster}
    @param cluster: the cluster's configuration
    @type enabled_disk_templates: list of string
    @param enabled_disk_templates: list of (possibly newly) enabled disk
      templates

    """
    # FIXME: write unit tests for this
    if self.op.ipolicy:
      self.new_ipolicy = GetUpdatedIPolicy(cluster.ipolicy, self.op.ipolicy,
                                           group_policy=False)

      CheckIpolicyVsDiskTemplates(self.new_ipolicy,
                                  enabled_disk_templates)

      all_instances = self.cfg.GetAllInstancesInfo().values()
      violations = set()
      for group in self.cfg.GetAllNodeGroupsInfo().values():
        instances = frozenset(
          inst for inst in all_instances
          if compat.any(nuuid in group.members
          for nuuid in self.cfg.GetInstanceNodes(inst.uuid)))
        new_ipolicy = objects.FillIPolicy(self.new_ipolicy, group.ipolicy)
        ipol = masterd.instance.CalculateGroupIPolicy(cluster, group)
        new = ComputeNewInstanceViolations(ipol, new_ipolicy, instances,
                                           self.cfg)
        if new:
          violations.update(new)

      if violations:
        self.LogWarning("After the ipolicy change the following instances"
                        " violate them: %s",
                        utils.CommaJoin(utils.NiceSort(violations)))
    else:
      CheckIpolicyVsDiskTemplates(cluster.ipolicy,
                                  enabled_disk_templates)

  def _CheckDrbdHelperOnNodes(self, drbd_helper, node_uuids):
    """Checks whether the set DRBD helper actually exists on the nodes.

    @type drbd_helper: string
    @param drbd_helper: path of the drbd usermode helper binary
    @type node_uuids: list of strings
    @param node_uuids: list of node UUIDs to check for the helper

    """
    # checks given drbd helper on all nodes
    helpers = self.rpc.call_drbd_helper(node_uuids)
    for (_, ninfo) in self.cfg.GetMultiNodeInfo(node_uuids):
      if ninfo.offline:
        self.LogInfo("Not checking drbd helper on offline node %s",
                     ninfo.name)
        continue
      msg = helpers[ninfo.uuid].fail_msg
      if msg:
        raise errors.OpPrereqError("Error checking drbd helper on node"
                                   " '%s': %s" % (ninfo.name, msg),
                                   errors.ECODE_ENVIRON)
      node_helper = helpers[ninfo.uuid].payload
      if node_helper != drbd_helper:
        raise errors.OpPrereqError("Error on node '%s': drbd helper is %s" %
                                   (ninfo.name, node_helper),
                                   errors.ECODE_ENVIRON)

  def _CheckDrbdHelper(self, node_uuids, drbd_enabled, drbd_gets_enabled):
    """Check the DRBD usermode helper.

    @type node_uuids: list of strings
    @param node_uuids: a list of nodes' UUIDs
    @type drbd_enabled: boolean
    @param drbd_enabled: whether DRBD will be enabled after this operation
      (no matter if it was disabled before or not)
    @type drbd_gets_enabled: boolen
    @param drbd_gets_enabled: true if DRBD was disabled before this
      operation, but will be enabled afterwards

    """
    if self.op.drbd_helper == '':
      if drbd_enabled:
        raise errors.OpPrereqError("Cannot disable drbd helper while"
                                   " DRBD is enabled.", errors.ECODE_STATE)
      if self.cfg.DisksOfType(constants.DT_DRBD8):
        raise errors.OpPrereqError("Cannot disable drbd helper while"
                                   " drbd-based instances exist",
                                   errors.ECODE_INVAL)

    else:
      if self.op.drbd_helper is not None and drbd_enabled:
        self._CheckDrbdHelperOnNodes(self.op.drbd_helper, node_uuids)
      else:
        if drbd_gets_enabled:
          current_drbd_helper = self.cfg.GetClusterInfo().drbd_usermode_helper
          if current_drbd_helper is not None:
            self._CheckDrbdHelperOnNodes(current_drbd_helper, node_uuids)
          else:
            raise errors.OpPrereqError("Cannot enable DRBD without a"
                                       " DRBD usermode helper set.",
                                       errors.ECODE_STATE)

  def _CheckInstancesOfDisabledDiskTemplates(
      self, disabled_disk_templates):
    """Check whether we try to disable a disk template that is in use.

    @type disabled_disk_templates: list of string
    @param disabled_disk_templates: list of disk templates that are going to
      be disabled by this operation

    """
    for disk_template in disabled_disk_templates:
      disks_with_type = self.cfg.DisksOfType(disk_template)
      if disks_with_type:
        disk_desc = []
        for disk in disks_with_type:
          instance_uuid = self.cfg.GetInstanceForDisk(disk.uuid)
          instance = self.cfg.GetInstanceInfo(instance_uuid)
          if instance:
            instance_desc = "on " + instance.name
          else:
            instance_desc = "detached"
          disk_desc.append("%s (%s)" % (disk, instance_desc))
        raise errors.OpPrereqError(
            "Cannot disable disk template '%s', because there is at least one"
            " disk using it:\n * %s" % (disk_template, "\n * ".join(disk_desc)),
            errors.ECODE_STATE)
    if constants.DT_DISKLESS in disabled_disk_templates:
      instances = self.cfg.GetAllInstancesInfo()
      for inst in instances.values():
        if not inst.disks:
          raise errors.OpPrereqError(
              "Cannot disable disk template 'diskless', because there is at"
              " least one instance using it:\n * %s" % inst.name,
              errors.ECODE_STATE)

  @staticmethod
  def _CheckInstanceCommunicationNetwork(network, warning_fn):
    """Check whether an existing network is configured for instance
    communication.

    Checks whether an existing network is configured with the
    parameters that are advisable for instance communication, and
    otherwise issue security warnings.

    @type network: L{ganeti.objects.Network}
    @param network: L{ganeti.objects.Network} object whose
                    configuration is being checked
    @type warning_fn: function
    @param warning_fn: function used to print warnings
    @rtype: None
    @return: None

    """
    def _MaybeWarn(err, val, default):
      if val != default:
        warning_fn("Supplied instance communication network '%s' %s '%s',"
                   " this might pose a security risk (default is '%s').",
                   network.name, err, val, default)

    if network.network is None:
      raise errors.OpPrereqError("Supplied instance communication network '%s'"
                                 " must have an IPv4 network address.",
                                 network.name)

    _MaybeWarn("has an IPv4 gateway", network.gateway, None)
    _MaybeWarn("has a non-standard IPv4 network address", network.network,
               constants.INSTANCE_COMMUNICATION_NETWORK4)
    _MaybeWarn("has an IPv6 gateway", network.gateway6, None)
    _MaybeWarn("has a non-standard IPv6 network address", network.network6,
               constants.INSTANCE_COMMUNICATION_NETWORK6)
    _MaybeWarn("has a non-standard MAC prefix", network.mac_prefix,
               constants.INSTANCE_COMMUNICATION_MAC_PREFIX)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks whether the given params don't conflict and
    if the given volume group is valid.

    """
    node_uuids = self.owned_locks(locking.LEVEL_NODE)
    self.cluster = cluster = self.cfg.GetClusterInfo()

    vm_capable_node_uuids = [node.uuid
                             for node in self.cfg.GetAllNodesInfo().values()
                             if node.uuid in node_uuids and node.vm_capable]

    (enabled_disk_templates, new_enabled_disk_templates,
      disabled_disk_templates) = self._GetDiskTemplateSets(cluster)
    self._CheckInstancesOfDisabledDiskTemplates(disabled_disk_templates)

    self._CheckVgName(vm_capable_node_uuids, enabled_disk_templates,
                      new_enabled_disk_templates)

    if self.op.file_storage_dir is not None:
      CheckFileStoragePathVsEnabledDiskTemplates(
          self.LogWarning, self.op.file_storage_dir, enabled_disk_templates)

    if self.op.shared_file_storage_dir is not None:
      CheckSharedFileStoragePathVsEnabledDiskTemplates(
          self.LogWarning, self.op.shared_file_storage_dir,
          enabled_disk_templates)

    drbd_enabled = constants.DT_DRBD8 in enabled_disk_templates
    drbd_gets_enabled = constants.DT_DRBD8 in new_enabled_disk_templates
    self._CheckDrbdHelper(vm_capable_node_uuids,
                          drbd_enabled, drbd_gets_enabled)

    # validate params changes
    if self.op.beparams:
      objects.UpgradeBeParams(self.op.beparams)
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)
      self.new_beparams = cluster.SimpleFillBE(self.op.beparams)

    if self.op.ndparams:
      utils.ForceDictType(self.op.ndparams, constants.NDS_PARAMETER_TYPES)
      self.new_ndparams = cluster.SimpleFillND(self.op.ndparams)

      # TODO: we need a more general way to handle resetting
      # cluster-level parameters to default values
      if self.new_ndparams["oob_program"] == "":
        self.new_ndparams["oob_program"] = \
            constants.NDC_DEFAULTS[constants.ND_OOB_PROGRAM]

    if self.op.hv_state:
      new_hv_state = MergeAndVerifyHvState(self.op.hv_state,
                                           self.cluster.hv_state_static)
      self.new_hv_state = dict((hv, cluster.SimpleFillHvState(values))
                               for hv, values in new_hv_state.items())

    if self.op.disk_state:
      new_disk_state = MergeAndVerifyDiskState(self.op.disk_state,
                                               self.cluster.disk_state_static)
      self.new_disk_state = \
        dict((storage, dict((name, cluster.SimpleFillDiskState(values))
                            for name, values in svalues.items()))
             for storage, svalues in new_disk_state.items())

    self._CheckIpolicy(cluster, enabled_disk_templates)

    if self.op.nicparams:
      utils.ForceDictType(self.op.nicparams, constants.NICS_PARAMETER_TYPES)
      self.new_nicparams = cluster.SimpleFillNIC(self.op.nicparams)
      objects.NIC.CheckParameterSyntax(self.new_nicparams)
      nic_errors = []

      # check all instances for consistency
      for instance in self.cfg.GetAllInstancesInfo().values():
        for nic_idx, nic in enumerate(instance.nics):
          params_copy = copy.deepcopy(nic.nicparams)
          params_filled = objects.FillDict(self.new_nicparams, params_copy)

          # check parameter syntax
          try:
            objects.NIC.CheckParameterSyntax(params_filled)
          except errors.ConfigurationError as err:
            nic_errors.append("Instance %s, nic/%d: %s" %
                              (instance.name, nic_idx, err))

          # if we're moving instances to routed, check that they have an ip
          target_mode = params_filled[constants.NIC_MODE]
          if target_mode == constants.NIC_MODE_ROUTED and not nic.ip:
            nic_errors.append("Instance %s, nic/%d: routed NIC with no ip"
                              " address" % (instance.name, nic_idx))
      if nic_errors:
        raise errors.OpPrereqError("Cannot apply the change, errors:\n%s" %
                                   "\n".join(nic_errors), errors.ECODE_INVAL)

    # hypervisor list/parameters
    self.new_hvparams = new_hvp = objects.FillDict(cluster.hvparams, {})
    if self.op.hvparams:
      for hv_name, hv_dict in self.op.hvparams.items():
        if hv_name not in self.new_hvparams:
          self.new_hvparams[hv_name] = hv_dict
        else:
          self.new_hvparams[hv_name].update(hv_dict)

    # disk template parameters
    self.new_diskparams = objects.FillDict(cluster.diskparams, {})
    if self.op.diskparams:
      for dt_name, dt_params in self.op.diskparams.items():
        if dt_name not in self.new_diskparams:
          self.new_diskparams[dt_name] = dt_params
        else:
          self.new_diskparams[dt_name].update(dt_params)
      CheckDiskAccessModeConsistency(self.op.diskparams, self.cfg)

    # os hypervisor parameters
    self.new_os_hvp = objects.FillDict(cluster.os_hvp, {})
    if self.op.os_hvp:
      for os_name, hvs in self.op.os_hvp.items():
        if os_name not in self.new_os_hvp:
          self.new_os_hvp[os_name] = hvs
        else:
          for hv_name, hv_dict in hvs.items():
            if hv_dict is None:
              # Delete if it exists
              self.new_os_hvp[os_name].pop(hv_name, None)
            elif hv_name not in self.new_os_hvp[os_name]:
              self.new_os_hvp[os_name][hv_name] = hv_dict
            else:
              self.new_os_hvp[os_name][hv_name].update(hv_dict)

      # Cleanup any OS that has an empty hypervisor parameter list, as we don't
      # need them in the cluster config anymore.
      for os_name, hvs in list(self.new_os_hvp.items()):
        if not hvs:
          self.new_os_hvp.pop(os_name, None)

    # os parameters
    self._BuildOSParams(cluster)

    # changes to the hypervisor list
    if self.op.enabled_hypervisors is not None:
      for hv in self.op.enabled_hypervisors:
        # if the hypervisor doesn't already exist in the cluster
        # hvparams, we initialize it to empty, and then (in both
        # cases) we make sure to fill the defaults, as we might not
        # have a complete defaults list if the hypervisor wasn't
        # enabled before
        if hv not in new_hvp:
          new_hvp[hv] = {}
        new_hvp[hv] = objects.FillDict(constants.HVC_DEFAULTS[hv], new_hvp[hv])
        utils.ForceDictType(new_hvp[hv], constants.HVS_PARAMETER_TYPES)

    if self.op.hvparams or self.op.enabled_hypervisors is not None:
      # either the enabled list has changed, or the parameters have, validate
      for hv_name, hv_params in self.new_hvparams.items():
        if ((self.op.hvparams and hv_name in self.op.hvparams) or
            (self.op.enabled_hypervisors and
             hv_name in self.op.enabled_hypervisors)):
          # either this is a new hypervisor, or its parameters have changed
          hv_class = hypervisor.GetHypervisorClass(hv_name)
          utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
          hv_class.CheckParameterSyntax(hv_params)
          CheckHVParams(self, node_uuids, hv_name, hv_params)

    if self.op.os_hvp:
      # no need to check any newly-enabled hypervisors, since the
      # defaults have already been checked in the above code-block
      for os_name, os_hvp in self.new_os_hvp.items():
        for hv_name, hv_params in os_hvp.items():
          utils.ForceDictType(hv_params, constants.HVS_PARAMETER_TYPES)
          # we need to fill in the new os_hvp on top of the actual hv_p
          cluster_defaults = self.new_hvparams.get(hv_name, {})
          new_osp = objects.FillDict(cluster_defaults, hv_params)
          hv_class = hypervisor.GetHypervisorClass(hv_name)
          hv_class.CheckParameterSyntax(new_osp)
          CheckHVParams(self, node_uuids, hv_name, new_osp)

    if self.op.default_iallocator:
      alloc_script = utils.FindFile(self.op.default_iallocator,
                                    constants.IALLOCATOR_SEARCH_PATH,
                                    os.path.isfile)
      if alloc_script is None:
        raise errors.OpPrereqError("Invalid default iallocator script '%s'"
                                   " specified" % self.op.default_iallocator,
                                   errors.ECODE_INVAL)

    if self.op.instance_communication_network:
      network_name = self.op.instance_communication_network

      try:
        network_uuid = self.cfg.LookupNetwork(network_name)
      except errors.OpPrereqError:
        network_uuid = None

      if network_uuid is not None:
        network = self.cfg.GetNetwork(network_uuid)
        self._CheckInstanceCommunicationNetwork(network, self.LogWarning)

    if self.op.compression_tools:
      CheckCompressionTools(self.op.compression_tools)

  def _BuildOSParams(self, cluster):
    "Calculate the new OS parameters for this operation."

    def _GetNewParams(source, new_params):
      "Wrapper around GetUpdatedParams."
      if new_params is None:
        return source
      result = objects.FillDict(source, {}) # deep copy of source
      for os_name in new_params:
        result[os_name] = GetUpdatedParams(result.get(os_name, {}),
                                           new_params[os_name],
                                           use_none=True)
        if not result[os_name]:
          del result[os_name] # we removed all parameters
      return result

    self.new_osp = _GetNewParams(cluster.osparams,
                                 self.op.osparams)
    self.new_osp_private = _GetNewParams(cluster.osparams_private_cluster,
                                         self.op.osparams_private_cluster)

    # Remove os validity check
    changed_oses = (set(self.new_osp.keys()) | set(self.new_osp_private.keys()))
    for os_name in changed_oses:
      os_params = cluster.SimpleFillOS(
        os_name,
        self.new_osp.get(os_name, {}),
        os_params_private=self.new_osp_private.get(os_name, {})
      )
      # check the parameter validity (remote check)
      CheckOSParams(self, False, [self.cfg.GetMasterNode()],
                    os_name, os_params, False)

  def _SetVgName(self, feedback_fn):
    """Determines and sets the new volume group name.

    """
    if self.op.vg_name is not None:
      new_volume = self.op.vg_name
      if not new_volume:
        new_volume = None
      if new_volume != self.cfg.GetVGName():
        self.cfg.SetVGName(new_volume)
      else:
        feedback_fn("Cluster LVM configuration already in desired"
                    " state, not changing")

  def _SetFileStorageDir(self, feedback_fn):
    """Set the file storage directory.

    """
    if self.op.file_storage_dir is not None:
      if self.cluster.file_storage_dir == self.op.file_storage_dir:
        feedback_fn("Global file storage dir already set to value '%s'"
                    % self.cluster.file_storage_dir)
      else:
        self.cluster.file_storage_dir = self.op.file_storage_dir

  def _SetSharedFileStorageDir(self, feedback_fn):
    """Set the shared file storage directory.

    """
    if self.op.shared_file_storage_dir is not None:
      if self.cluster.shared_file_storage_dir == \
          self.op.shared_file_storage_dir:
        feedback_fn("Global shared file storage dir already set to value '%s'"
                    % self.cluster.shared_file_storage_dir)
      else:
        self.cluster.shared_file_storage_dir = self.op.shared_file_storage_dir

  def _SetDrbdHelper(self, feedback_fn):
    """Set the DRBD usermode helper.

    """
    if self.op.drbd_helper is not None:
      if not constants.DT_DRBD8 in self.cluster.enabled_disk_templates:
        feedback_fn("Note that you specified a drbd user helper, but did not"
                    " enable the drbd disk template.")
      new_helper = self.op.drbd_helper
      if not new_helper:
        new_helper = None
      if new_helper != self.cfg.GetDRBDHelper():
        self.cfg.SetDRBDHelper(new_helper)
      else:
        feedback_fn("Cluster DRBD helper already in desired state,"
                    " not changing")

  @staticmethod
  def _EnsureInstanceCommunicationNetwork(cfg, network_name):
    """Ensure that the instance communication network exists and is
    connected to all groups.

    The instance communication network given by L{network_name} it is
    created, if necessary, via the opcode 'OpNetworkAdd'.  Also, the
    instance communication network is connected to all existing node
    groups, if necessary, via the opcode 'OpNetworkConnect'.

    @type cfg: L{config.ConfigWriter}
    @param cfg: cluster configuration

    @type network_name: string
    @param network_name: instance communication network name

    @rtype: L{ganeti.cmdlib.ResultWithJobs} or L{None}
    @return: L{ganeti.cmdlib.ResultWithJobs} if the instance
             communication needs to be created or it needs to be
             connected to a group, otherwise L{None}

    """
    jobs = []

    try:
      network_uuid = cfg.LookupNetwork(network_name)
      network_exists = True
    except errors.OpPrereqError:
      network_exists = False

    if not network_exists:
      jobs.append(AddInstanceCommunicationNetworkOp(network_name))

    for group_uuid in cfg.GetNodeGroupList():
      group = cfg.GetNodeGroup(group_uuid)

      if network_exists:
        network_connected = network_uuid in group.networks
      else:
        # The network was created asynchronously by the previous
        # opcode and, therefore, we don't have access to its
        # network_uuid.  As a result, we assume that the network is
        # not connected to any group yet.
        network_connected = False

      if not network_connected:
        op = ConnectInstanceCommunicationNetworkOp(group_uuid, network_name)
        jobs.append(op)

    if jobs:
      return ResultWithJobs([jobs])
    else:
      return None

  @staticmethod
  def _ModifyInstanceCommunicationNetwork(cfg, network_name, feedback_fn):
    """Update the instance communication network stored in the cluster
    configuration.

    Compares the user-supplied instance communication network against
    the one stored in the Ganeti cluster configuration.  If there is a
    change, the instance communication network may be possibly created
    and connected to all groups (see
    L{LUClusterSetParams._EnsureInstanceCommunicationNetwork}).

    @type cfg: L{config.ConfigWriter}
    @param cfg: cluster configuration

    @type network_name: string
    @param network_name: instance communication network name

    @type feedback_fn: function
    @param feedback_fn: see L{ganeti.cmdlist.base.LogicalUnit}

    @rtype: L{LUClusterSetParams._EnsureInstanceCommunicationNetwork} or L{None}
    @return: see L{LUClusterSetParams._EnsureInstanceCommunicationNetwork}

    """
    config_network_name = cfg.GetInstanceCommunicationNetwork()

    if network_name == config_network_name:
      feedback_fn("Instance communication network already is '%s', nothing to"
                  " do." % network_name)
    else:
      try:
        cfg.LookupNetwork(config_network_name)
        feedback_fn("Previous instance communication network '%s'"
                    " should be removed manually." % config_network_name)
      except errors.OpPrereqError:
        pass

      if network_name:
        feedback_fn("Changing instance communication network to '%s', only new"
                    " instances will be affected."
                    % network_name)
      else:
        feedback_fn("Disabling instance communication network, only new"
                    " instances will be affected.")

      cfg.SetInstanceCommunicationNetwork(network_name)

      if network_name:
        return LUClusterSetParams._EnsureInstanceCommunicationNetwork(
          cfg,
          network_name)
      else:
        return None

  def Exec(self, feedback_fn):
    """Change the parameters of the cluster.

    """
    # re-read the fresh configuration
    self.cluster = self.cfg.GetClusterInfo()
    if self.op.enabled_disk_templates:
      self.cluster.enabled_disk_templates = \
        list(self.op.enabled_disk_templates)
    # save the changes
    self.cfg.Update(self.cluster, feedback_fn)

    self._SetVgName(feedback_fn)

    self.cluster = self.cfg.GetClusterInfo()
    self._SetFileStorageDir(feedback_fn)
    self._SetSharedFileStorageDir(feedback_fn)
    self.cfg.Update(self.cluster, feedback_fn)
    self._SetDrbdHelper(feedback_fn)

    # re-read the fresh configuration again
    self.cluster = self.cfg.GetClusterInfo()

    ensure_kvmd = False
    stop_kvmd_silently = not (
        constants.HT_KVM in self.cluster.enabled_hypervisors or
        (self.op.enabled_hypervisors is not None and
         constants.HT_KVM in self.op.enabled_hypervisors))

    active = constants.DATA_COLLECTOR_STATE_ACTIVE
    if self.op.enabled_data_collectors is not None:
      for name, val in self.op.enabled_data_collectors.items():
        self.cluster.data_collectors[name][active] = val

    if self.op.data_collector_interval:
      internal = constants.DATA_COLLECTOR_PARAMETER_INTERVAL
      for name, val in self.op.data_collector_interval.items():
        self.cluster.data_collectors[name][internal] = int(val)

    if self.op.hvparams:
      self.cluster.hvparams = self.new_hvparams
    if self.op.os_hvp:
      self.cluster.os_hvp = self.new_os_hvp
    if self.op.enabled_hypervisors is not None:
      self.cluster.hvparams = self.new_hvparams
      self.cluster.enabled_hypervisors = self.op.enabled_hypervisors
      ensure_kvmd = True
    if self.op.beparams:
      self.cluster.beparams[constants.PP_DEFAULT] = self.new_beparams
    if self.op.nicparams:
      self.cluster.nicparams[constants.PP_DEFAULT] = self.new_nicparams
    if self.op.ipolicy:
      self.cluster.ipolicy = self.new_ipolicy
    if self.op.osparams:
      self.cluster.osparams = self.new_osp
    if self.op.osparams_private_cluster:
      self.cluster.osparams_private_cluster = self.new_osp_private
    if self.op.ndparams:
      self.cluster.ndparams = self.new_ndparams
    if self.op.diskparams:
      self.cluster.diskparams = self.new_diskparams
    if self.op.hv_state:
      self.cluster.hv_state_static = self.new_hv_state
    if self.op.disk_state:
      self.cluster.disk_state_static = self.new_disk_state

    if self.op.candidate_pool_size is not None:
      self.cluster.candidate_pool_size = self.op.candidate_pool_size
      # we need to update the pool size here, otherwise the save will fail
      master_node = self.cfg.GetMasterNode()
      potential_master_candidates = self.cfg.GetPotentialMasterCandidates()
      modify_ssh_setup = self.cfg.GetClusterInfo().modify_ssh_setup
      AdjustCandidatePool(
          self, [], master_node, potential_master_candidates, feedback_fn,
          modify_ssh_setup)

    if self.op.max_running_jobs is not None:
      self.cluster.max_running_jobs = self.op.max_running_jobs

    if self.op.max_tracked_jobs is not None:
      self.cluster.max_tracked_jobs = self.op.max_tracked_jobs

    if self.op.maintain_node_health is not None:
      self.cluster.maintain_node_health = self.op.maintain_node_health

    if self.op.modify_etc_hosts is not None:
      self.cluster.modify_etc_hosts = self.op.modify_etc_hosts

    if self.op.prealloc_wipe_disks is not None:
      self.cluster.prealloc_wipe_disks = self.op.prealloc_wipe_disks

    if self.op.add_uids is not None:
      uidpool.AddToUidPool(self.cluster.uid_pool, self.op.add_uids)

    if self.op.remove_uids is not None:
      uidpool.RemoveFromUidPool(self.cluster.uid_pool, self.op.remove_uids)

    if self.op.uid_pool is not None:
      self.cluster.uid_pool = self.op.uid_pool

    if self.op.default_iallocator is not None:
      self.cluster.default_iallocator = self.op.default_iallocator

    if self.op.default_iallocator_params is not None:
      self.cluster.default_iallocator_params = self.op.default_iallocator_params

    if self.op.reserved_lvs is not None:
      self.cluster.reserved_lvs = self.op.reserved_lvs

    if self.op.use_external_mip_script is not None:
      self.cluster.use_external_mip_script = self.op.use_external_mip_script

    if self.op.enabled_user_shutdown is not None and \
          self.cluster.enabled_user_shutdown != self.op.enabled_user_shutdown:
      self.cluster.enabled_user_shutdown = self.op.enabled_user_shutdown
      ensure_kvmd = True

    def helper_os(aname, mods, desc):
      desc += " OS list"
      lst = getattr(self.cluster, aname)
      for key, val in mods:
        if key == constants.DDM_ADD:
          if val in lst:
            feedback_fn("OS %s already in %s, ignoring" % (val, desc))
          else:
            lst.append(val)
        elif key == constants.DDM_REMOVE:
          if val in lst:
            lst.remove(val)
          else:
            feedback_fn("OS %s not found in %s, ignoring" % (val, desc))
        else:
          raise errors.ProgrammerError("Invalid modification '%s'" % key)

    if self.op.hidden_os:
      helper_os("hidden_os", self.op.hidden_os, "hidden")

    if self.op.blacklisted_os:
      helper_os("blacklisted_os", self.op.blacklisted_os, "blacklisted")

    if self.op.mac_prefix:
      self.cluster.mac_prefix = self.op.mac_prefix

    if self.op.master_netdev:
      master_params = self.cfg.GetMasterNetworkParameters()
      ems = self.cfg.GetUseExternalMipScript()
      feedback_fn("Shutting down master ip on the current netdev (%s)" %
                  self.cluster.master_netdev)
      result = self.rpc.call_node_deactivate_master_ip(master_params.uuid,
                                                       master_params, ems)
      if not self.op.force:
        result.Raise("Could not disable the master ip")
      else:
        if result.fail_msg:
          msg = ("Could not disable the master ip (continuing anyway): %s" %
                 result.fail_msg)
          feedback_fn(msg)
      feedback_fn("Changing master_netdev from %s to %s" %
                  (master_params.netdev, self.op.master_netdev))
      self.cluster.master_netdev = self.op.master_netdev

    if self.op.master_netmask:
      master_params = self.cfg.GetMasterNetworkParameters()
      feedback_fn("Changing master IP netmask to %s" % self.op.master_netmask)
      result = self.rpc.call_node_change_master_netmask(
                 master_params.uuid, master_params.netmask,
                 self.op.master_netmask, master_params.ip,
                 master_params.netdev)
      result.Warn("Could not change the master IP netmask", feedback_fn)
      self.cluster.master_netmask = self.op.master_netmask

    if self.op.install_image:
      self.cluster.install_image = self.op.install_image

    if self.op.zeroing_image is not None:
      CheckImageValidity(self.op.zeroing_image,
                         "Zeroing image must be an absolute path or a URL")
      self.cluster.zeroing_image = self.op.zeroing_image

    self.cfg.Update(self.cluster, feedback_fn)

    if self.op.master_netdev:
      master_params = self.cfg.GetMasterNetworkParameters()
      feedback_fn("Starting the master ip on the new master netdev (%s)" %
                  self.op.master_netdev)
      ems = self.cfg.GetUseExternalMipScript()
      result = self.rpc.call_node_activate_master_ip(master_params.uuid,
                                                     master_params, ems)
      result.Warn("Could not re-enable the master ip on the master,"
                  " please restart manually", self.LogWarning)

    # Even though 'self.op.enabled_user_shutdown' is being tested
    # above, the RPCs can only be done after 'self.cfg.Update' because
    # this will update the cluster object and sync 'Ssconf', and kvmd
    # uses 'Ssconf'.
    if ensure_kvmd:
      EnsureKvmdOnNodes(self, feedback_fn, silent_stop=stop_kvmd_silently)

    if self.op.compression_tools is not None:
      self.cfg.SetCompressionTools(self.op.compression_tools)

    network_name = self.op.instance_communication_network
    if network_name is not None:
      return self._ModifyInstanceCommunicationNetwork(self.cfg,
                                                      network_name, feedback_fn)
    else:
      return None
