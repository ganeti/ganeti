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
  CheckDiskAccessModeConsistency, CreateNewClientCert

import ganeti.masterd.instance


def _UpdateMasterClientCert(
    lu, master_uuid, cluster, feedback_fn,
    client_cert=pathutils.NODED_CLIENT_CERT_FILE,
    client_cert_tmp=pathutils.NODED_CLIENT_CERT_FILE_TMP):
  """Renews the master's client certificate and propagates the config.

  @type lu: C{LogicalUnit}
  @param lu: the logical unit holding the config
  @type master_uuid: string
  @param master_uuid: the master node's UUID
  @type cluster: C{objects.Cluster}
  @param cluster: the cluster's configuration
  @type feedback_fn: function
  @param feedback_fn: feedback functions for config updates
  @type client_cert: string
  @param client_cert: the path of the client certificate
  @type client_cert_tmp: string
  @param client_cert_tmp: the temporary path of the client certificate
  @rtype: string
  @return: the digest of the newly created client certificate

  """
  client_digest = CreateNewClientCert(lu, master_uuid, filename=client_cert_tmp)
  utils.AddNodeToCandidateCerts(master_uuid, client_digest,
                                cluster.candidate_certs)
  # This triggers an update of the config and distribution of it with the old
  # SSL certificate
  lu.cfg.Update(cluster, feedback_fn)

  utils.RemoveFile(client_cert)
  utils.RenameFile(client_cert_tmp, client_cert)
  return client_digest


class LUClusterRenewCrypto(NoHooksLU):
  """Renew the cluster's crypto tokens.

  Note that most of this operation is done in gnt_cluster.py, this LU only
  takes care of the renewal of the client SSL certificates.

  """
  def Exec(self, feedback_fn):
    master_uuid = self.cfg.GetMasterNode()
    cluster = self.cfg.GetClusterInfo()

    server_digest = utils.GetCertificateDigest(
      cert_filename=pathutils.NODED_CERT_FILE)
    utils.AddNodeToCandidateCerts("%s-SERVER" % master_uuid,
                                  server_digest,
                                  cluster.candidate_certs)
    new_master_digest = _UpdateMasterClientCert(self, master_uuid, cluster,
                                                feedback_fn)

    cluster.candidate_certs = {master_uuid: new_master_digest}
    nodes = self.cfg.GetAllNodesInfo()
    for (node_uuid, node_info) in nodes.items():
      if node_uuid != master_uuid:
        new_digest = CreateNewClientCert(self, node_uuid)
        if node_info.master_candidate:
          cluster.candidate_certs[node_uuid] = new_digest
    # Trigger another update of the config now with the new master cert
    self.cfg.Update(cluster, feedback_fn)


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

    cluster = self.cfg.GetClusterInfo()
    _UpdateMasterClientCert(self, self.master_uuid, cluster, feedback_fn)

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
    # Locking is not used
    assert not (compat.any(lu.glm.is_owned(level)
                           for level in locking.LEVELS
                           if level != locking.LEVEL_CLUSTER) or
                self.do_locking or self.use_locking)

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
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
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

        # This opcode is acquires the node locks for all instances
        locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
        }

    self.share_locks = {
      locking.LEVEL_NODE_RES: 1,
      locking.LEVEL_INSTANCE: 0,
      locking.LEVEL_NODE_ALLOC: 1,
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

    self.wanted_instances = \
        map(compat.snd, self.cfg.GetMultiInstanceInfoByName(self.wanted_names))

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
      for idx, disk in enumerate(instance.disks):
        per_node_disks[pnode].append((instance, idx, disk))

    assert not (frozenset(per_node_disks.keys()) -
                self.owned_locks(locking.LEVEL_NODE_RES)), \
      "Not owning correct locks"
    assert not self.owned_locks(locking.LEVEL_NODE)

    es_flags = rpc.GetExclusiveStorageForNodes(self.cfg,
                                               per_node_disks.keys())

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
          self.cfg.Update(instance, feedback_fn)
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
            self.cfg.Update(instance, feedback_fn)
            changed.append((instance.name, idx, "spindles", disk.spindles))
        if self._EnsureChildSizes(disk):
          self.cfg.Update(instance, feedback_fn)
          changed.append((instance.name, idx, "size", disk.size))
    return changed


def _ValidateNetmask(cfg, netmask):
  """Checks if a netmask is valid.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type netmask: int
  @param netmask: the netmask to be verified
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
            constants.ST_FILE, constants.ST_SHARED_FILE
         ))
  file_storage_enabled = file_disk_template in enabled_disk_templates
  if file_storage_dir is not None:
    if file_storage_dir == "":
      if file_storage_enabled:
        raise errors.OpPrereqError(
            "Unsetting the '%s' storage directory while having '%s' storage"
            " enabled is not permitted." %
            (file_disk_template, file_disk_template))
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

    if self.op.master_netmask is not None:
      _ValidateNetmask(self.cfg, self.op.master_netmask)

    if self.op.diskparams:
      for dt_params in self.op.diskparams.values():
        utils.ForceDictType(dt_params, constants.DISK_DT_TYPES)
      try:
        utils.VerifyDictOptions(self.op.diskparams, constants.DISK_DT_DEFAULTS)
        CheckDiskAccessModeValidity(self.op.diskparams)
      except errors.OpPrereqError, err:
        raise errors.OpPrereqError("While verify diskparams options: %s" % err,
                                   errors.ECODE_INVAL)

  def ExpandNames(self):
    # FIXME: in the future maybe other cluster params won't require checking on
    # all nodes to be modified.
    # FIXME: This opcode changes cluster-wide settings. Is acquiring all
    # resource locks the right thing, shouldn't it be the BGL instead?
    self.needed_locks = {
      locking.LEVEL_NODE: locking.ALL_SET,
      locking.LEVEL_INSTANCE: locking.ALL_SET,
      locking.LEVEL_NODEGROUP: locking.ALL_SET,
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
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
                                   " disk templates are or get enabled.")

    if self.op.vg_name is None:
      if current_vg_name is None and lvm_is_enabled:
        raise errors.OpPrereqError("Please specify a volume group when"
                                   " enabling lvm-based disk-templates.")

    if self.op.vg_name is not None and not self.op.vg_name:
      if self.cfg.HasAnyDiskOfType(constants.DT_PLAIN):
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
        instances = frozenset([inst for inst in all_instances
                               if compat.any(nuuid in group.members
                                             for nuuid in inst.all_nodes)])
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
                                   " DRBD is enabled.")
      if self.cfg.HasAnyDiskOfType(constants.DT_DRBD8):
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
                                       " DRBD usermode helper set.")

  def _CheckInstancesOfDisabledDiskTemplates(
      self, disabled_disk_templates):
    """Check whether we try to disable a disk template that is in use.

    @type disabled_disk_templates: list of string
    @param disabled_disk_templates: list of disk templates that are going to
      be disabled by this operation

    """
    for disk_template in disabled_disk_templates:
      if self.cfg.HasAnyDiskOfType(disk_template):
        raise errors.OpPrereqError(
            "Cannot disable disk template '%s', because there is at least one"
            " instance using it." % disk_template)

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
    self._CheckDrbdHelper(node_uuids, drbd_enabled, drbd_gets_enabled)

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
          except errors.ConfigurationError, err:
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

    # os parameters
    self._BuildOSParams(cluster)

    # changes to the hypervisor list
    if self.op.enabled_hypervisors is not None:
      self.hv_list = self.op.enabled_hypervisors
      for hv in self.hv_list:
        # if the hypervisor doesn't already exist in the cluster
        # hvparams, we initialize it to empty, and then (in both
        # cases) we make sure to fill the defaults, as we might not
        # have a complete defaults list if the hypervisor wasn't
        # enabled before
        if hv not in new_hvp:
          new_hvp[hv] = {}
        new_hvp[hv] = objects.FillDict(constants.HVC_DEFAULTS[hv], new_hvp[hv])
        utils.ForceDictType(new_hvp[hv], constants.HVS_PARAMETER_TYPES)
    else:
      self.hv_list = cluster.enabled_hypervisors

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

    self._CheckDiskTemplateConsistency()

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
                    os_name, os_params)

  def _CheckDiskTemplateConsistency(self):
    """Check whether the disk templates that are going to be disabled
       are still in use by some instances.

    """
    if self.op.enabled_disk_templates:
      cluster = self.cfg.GetClusterInfo()
      instances = self.cfg.GetAllInstancesInfo()

      disk_templates_to_remove = set(cluster.enabled_disk_templates) \
        - set(self.op.enabled_disk_templates)
      for instance in instances.itervalues():
        if instance.disk_template in disk_templates_to_remove:
          raise errors.OpPrereqError("Cannot disable disk template '%s',"
                                     " because instance '%s' is using it." %
                                     (instance.disk_template, instance.name))

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

  def Exec(self, feedback_fn):
    """Change the parameters of the cluster.

    """
    if self.op.enabled_disk_templates:
      self.cluster.enabled_disk_templates = \
        list(self.op.enabled_disk_templates)

    self._SetVgName(feedback_fn)
    self._SetFileStorageDir(feedback_fn)
    self._SetDrbdHelper(feedback_fn)

    if self.op.hvparams:
      self.cluster.hvparams = self.new_hvparams
    if self.op.os_hvp:
      self.cluster.os_hvp = self.new_os_hvp
    if self.op.enabled_hypervisors is not None:
      self.cluster.hvparams = self.new_hvparams
      self.cluster.enabled_hypervisors = self.op.enabled_hypervisors
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
      AdjustCandidatePool(self, [], feedback_fn)

    if self.op.max_running_jobs is not None:
      self.cluster.max_running_jobs = self.op.max_running_jobs

    if self.op.maintain_node_health is not None:
      if self.op.maintain_node_health and not constants.ENABLE_CONFD:
        feedback_fn("Note: CONFD was disabled at build time, node health"
                    " maintenance is not useful (still enabling it)")
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
                                    depends=depends_fn())]
      for group in groups)

    # Fix up all parameters
    for op in itertools.chain(*jobs): # pylint: disable=W0142
      op.debug_simulate_errors = self.op.debug_simulate_errors
      op.verbose = self.op.verbose
      op.error_codes = self.op.error_codes
      try:
        op.skip_checks = self.op.skip_checks
      except AttributeError:
        assert not isinstance(op, opcodes.OpClusterVerifyGroup)

    return ResultWithJobs(jobs)


class _VerifyErrors(object):
  """Mix-in for cluster/group verify LUs.

  It provides _Error and _ErrorIf, and updates the self.bad boolean. (Expects
  self.op and self._feedback_fn to be available.)

  """

  ETYPE_FIELD = "code"
  ETYPE_ERROR = constants.CV_ERROR
  ETYPE_WARNING = constants.CV_WARNING

  def _Error(self, ecode, item, msg, *args, **kwargs):
    """Format an error message.

    Based on the opcode's error_codes parameter, either format a
    parseable error code, or a simpler error string.

    This must be called only from Exec and functions called from Exec.

    """
    ltype = kwargs.get(self.ETYPE_FIELD, self.ETYPE_ERROR)
    itype, etxt, _ = ecode
    # If the error code is in the list of ignored errors, demote the error to a
    # warning
    if etxt in self.op.ignore_errors:     # pylint: disable=E1101
      ltype = self.ETYPE_WARNING
    # first complete the msg
    if args:
      msg = msg % args
    # then format the whole message
    if self.op.error_codes: # This is a mix-in. pylint: disable=E1101
      msg = "%s:%s:%s:%s:%s" % (ltype, etxt, itype, item, msg)
    else:
      if item:
        item = " " + item
      else:
        item = ""
      msg = "%s: %s%s: %s" % (ltype, itype, item, msg)
    # and finally report it via the feedback_fn
    self._feedback_fn("  - %s" % msg) # Mix-in. pylint: disable=E1101
    # do not mark the operation as failed for WARN cases only
    if ltype == self.ETYPE_ERROR:
      self.bad = True

  def _ErrorIf(self, cond, *args, **kwargs):
    """Log an error message if the passed condition is True.

    """
    if (bool(cond)
        or self.op.debug_simulate_errors): # pylint: disable=E1101
      self._Error(*args, **kwargs)


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

    for msg in self.cfg.VerifyConfig():
      self._ErrorIf(True, constants.CV_ECLUSTERCFG, None, msg)

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

      # This opcode is run by watcher every five minutes and acquires all nodes
      # for a group. It doesn't run for a long time, so it's better to acquire
      # the node allocation lock as well.
      locking.LEVEL_NODE_ALLOC: locking.ALL_SET,
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
        if instance.disk_template in constants.DTS_INT_MIRROR:
          nodes.update(instance.secondary_nodes)

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

    self.my_node_uuids = group_node_uuids
    self.my_node_info = dict((node_uuid, self.all_node_info[node_uuid])
                             for node_uuid in group_node_uuids)

    self.my_inst_uuids = group_inst_uuids
    self.my_inst_info = dict((inst_uuid, self.all_inst_info[inst_uuid])
                             for inst_uuid in group_inst_uuids)

    # We detect here the nodes that will need the extra RPC calls for verifying
    # split LV volumes; they should be locked.
    extra_lv_nodes = set()

    for inst in self.my_inst_info.values():
      if inst.disk_template in constants.DTS_INT_MIRROR:
        for nuuid in inst.all_nodes:
          if self.all_node_info[nuuid].group != self.group_uuid:
            extra_lv_nodes.add(nuuid)

    unlocked_lv_nodes = \
        extra_lv_nodes.difference(self.owned_locks(locking.LEVEL_NODE))

    if unlocked_lv_nodes:
      raise errors.OpPrereqError("Missing node locks for LV check: %s" %
                                 utils.CommaJoin(unlocked_lv_nodes),
                                 errors.ECODE_STATE)
    self.extra_lv_nodes = list(extra_lv_nodes)

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
        version = nresult.get(constants.NV_DRBDVERSION, "Missing DRBD version")
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
    vals = filter((lambda ni: ni.pv_min is not None), node_image.values())
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

    test = constants.NV_NODENETTEST not in nresult
    self._ErrorIf(test, constants.CV_ENODENET, ninfo.name,
                  "node hasn't returned node tcp connectivity data")
    if not test:
      if nresult[constants.NV_NODENETTEST]:
        nlist = utils.NiceSort(nresult[constants.NV_NODENETTEST].keys())
        for anode in nlist:
          self._ErrorIf(True, constants.CV_ENODENET, ninfo.name,
                        "tcp communication with node '%s': %s",
                        anode, nresult[constants.NV_NODENETTEST][anode])

    test = constants.NV_MASTERIP not in nresult
    self._ErrorIf(test, constants.CV_ENODENET, ninfo.name,
                  "node hasn't returned node master IP reachability data")
    if not test:
      if not nresult[constants.NV_MASTERIP]:
        if ninfo.uuid == self.master_node:
          msg = "the master node cannot reach the master IP (not configured?)"
        else:
          msg = "cannot reach the master IP"
        self._ErrorIf(True, constants.CV_ENODENET, ninfo.name, msg)

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
    instance.MapLVsByNode(node_vol_should)

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

      if instance.disks_active and success and \
         (bdev_status.is_degraded or
          bdev_status.ldisk_status != constants.LDS_OKAY):
        msg = "disk/%s on %s" % (idx, self.cfg.GetNodeName(nname))
        if bdev_status.is_degraded:
          msg += " is degraded"
        if bdev_status.ldisk_status != constants.LDS_OKAY:
          msg += "; state is '%s'" % \
                 constants.LDS_NAMES[bdev_status.ldisk_status]

        self._Error(constants.CV_EINSTANCEFAULTYDISK, instance.name, msg)

    self._ErrorIf(pnode_img.rpc_fail and not pnode_img.offline,
                  constants.CV_ENODERPC, self.cfg.GetNodeName(pnode_uuid),
                  "instance %s, connection to primary node failed",
                  instance.name)

    self._ErrorIf(len(instance.secondary_nodes) > 1,
                  constants.CV_EINSTANCELAYOUT, instance.name,
                  "instance has multiple secondary nodes: %s",
                  utils.CommaJoin(instance.secondary_nodes),
                  code=self.ETYPE_WARNING)

    es_flags = rpc.GetExclusiveStorageForNodes(self.cfg, instance.all_nodes)
    if any(es_flags.values()):
      if instance.disk_template not in constants.DTS_EXCL_STORAGE:
        # Disk template not compatible with exclusive_storage: no instance
        # node should have the flag set
        es_nodes = [n
                    for (n, es) in es_flags.items()
                    if es]
        self._Error(constants.CV_EINSTANCEUNSUITABLENODE, instance.name,
                    "instance has template %s, which is not supported on nodes"
                    " that have exclusive storage set: %s",
                    instance.disk_template,
                    utils.CommaJoin(self.cfg.GetNodeNames(es_nodes)))
      for (idx, disk) in enumerate(instance.disks):
        self._ErrorIf(disk.spindles is None,
                      constants.CV_EINSTANCEMISSINGCFGPARAMETER, instance.name,
                      "number of spindles not configured for disk %s while"
                      " exclusive storage is enabled, try running"
                      " gnt-cluster repair-disk-sizes", idx)

    if instance.disk_template in constants.DTS_INT_MIRROR:
      instance_nodes = utils.NiceSort(instance.all_nodes)
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
    for snode in instance.secondary_nodes:
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
    for node_uuid in instance.all_nodes:
      self._ErrorIf(node_image[node_uuid].ghost, constants.CV_EINSTANCEBADNODE,
                    instance.name, "instance lives on ghost node %s",
                    self.cfg.GetNodeName(node_uuid))
      self._ErrorIf(not node_image[node_uuid].vm_capable,
                    constants.CV_EINSTANCEBADNODE, instance.name,
                    "instance lives on non-vm_capable node %s",
                    self.cfg.GetNodeName(node_uuid))

  def _VerifyOrphanVolumes(self, node_vol_should, node_image, reserved):
    """Verify if there are any unknown volumes in the cluster.

    The .os, .swap and backup volumes are ignored. All other volumes are
    reported as unknown.

    @type reserved: L{ganeti.utils.FieldSet}
    @param reserved: a FieldSet of reserved volume names

    """
    for node_uuid, n_img in node_image.items():
      if (n_img.offline or n_img.rpc_fail or n_img.lvm_fail or
          self.all_node_info[node_uuid].group != self.group_uuid):
        # skip non-healthy nodes
        continue
      for volume in n_img.volumes:
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
    candidate_certs = self.cfg.GetClusterInfo().candidate_certs
    if candidate_certs is None or len(candidate_certs) == 0:
      self._ErrorIf(
        True, constants.CV_ECLUSTERCLIENTCERT, None,
        "The cluster's list of master candidate certificates is empty."
        "If you just updated the cluster, please run"
        " 'gnt-cluster renew-crypto --new-node-certificates'.")
      return

    self._ErrorIf(
      len(candidate_certs) != len(set(candidate_certs.values())),
      constants.CV_ECLUSTERCLIENTCERT, None,
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

      self._ErrorIf(
        errcode is not None, constants.CV_ECLUSTERCLIENTCERT, None,
        "Client certificate of node '%s' failed validation: %s (code '%s')",
        node.uuid, msg, errcode)

      if not errcode:
        digest = msg
        if node.master_candidate:
          if node.uuid in candidate_certs:
            self._ErrorIf(
              digest != candidate_certs[node.uuid],
              constants.CV_ECLUSTERCLIENTCERT, None,
              "Client certificate digest of master candidate '%s' does not"
              " match its entry in the cluster's map of master candidate"
              " certificates. Expected: %s Got: %s", node.uuid,
              digest, candidate_certs[node.uuid])
          else:
            self._ErrorIf(
              True, constants.CV_ECLUSTERCLIENTCERT, None,
              "The master candidate '%s' does not have an entry in the"
              " map of candidate certificates.", node.uuid)
            self._ErrorIf(
              digest in candidate_certs.values(),
              constants.CV_ECLUSTERCLIENTCERT, None,
              "Master candidate '%s' is using a certificate of another node.",
              node.uuid)
        else:
          self._ErrorIf(
            node.uuid in candidate_certs,
            constants.CV_ECLUSTERCLIENTCERT, None,
            "Node '%s' is not a master candidate, but still listed in the"
            " map of master candidate certificates.", node.uuid)
          self._ErrorIf(
            (node.uuid not in candidate_certs) and
              (digest in candidate_certs.values()),
            constants.CV_ECLUSTERCLIENTCERT, None,
            "Node '%s' is not a master candidate and is incorrectly using a"
            " certificate of another node which is master candidate.",
            node.uuid)

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
      nodefiles.update((filename,
                        frozenset(map(operator.attrgetter("uuid"), filenodes)))
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
                      utils.CommaJoin(
                        utils.NiceSort(
                          map(self.cfg.GetNodeName, missing_file))))
      else:
        self._ErrorIf(missing_file, constants.CV_ECLUSTERFILECHECK, None,
                      "File %s is missing from node(s) %s", filename,
                      utils.CommaJoin(
                        utils.NiceSort(
                          map(self.cfg.GetNodeName, missing_file))))

        # Warn if a node has a file it shouldn't
        unexpected = with_file - expected_nodes
        self._ErrorIf(unexpected,
                      constants.CV_ECLUSTERFILECHECK, None,
                      "File %s should not exist on node(s) %s",
                      filename, utils.CommaJoin(
                        utils.NiceSort(map(self.cfg.GetNodeName, unexpected))))

      # See if there are multiple versions of the file
      test = len(checksums) > 1
      if test:
        variants = ["variant %s on %s" %
                    (idx + 1,
                     utils.CommaJoin(utils.NiceSort(
                       map(self.cfg.GetNodeName, node_uuids))))
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

  def _VerifyNodeDrbd(self, ninfo, nresult, instanceinfo, drbd_helper,
                      drbd_map):
    """Verifies and the node DRBD status.

    @type ninfo: L{objects.Node}
    @param ninfo: the node to check
    @param nresult: the remote results for the node
    @param instanceinfo: the dict of instances
    @param drbd_helper: the configured DRBD usermode helper
    @param drbd_map: the DRBD map as returned by
        L{ganeti.config.ConfigWriter.ComputeDRBDMap}

    """
    self._VerifyNodeDrbdHelper(ninfo, nresult, drbd_helper)

    # compute the DRBD minors
    node_drbd = {}
    for minor, inst_uuid in drbd_map[ninfo.uuid].items():
      test = inst_uuid not in instanceinfo
      self._ErrorIf(test, constants.CV_ECLUSTERCFG, None,
                    "ghost instance '%s' in temporary DRBD map", inst_uuid)
        # ghost instance should not be running, but otherwise we
        # don't give double warnings (both ghost instance and
        # unallocated minor in use)
      if test:
        node_drbd[minor] = (inst_uuid, False)
      else:
        instance = instanceinfo[inst_uuid]
        node_drbd[minor] = (inst_uuid, instance.disks_active)

    # and now check them
    used_minors = nresult.get(constants.NV_DRBDLIST, [])
    test = not isinstance(used_minors, (tuple, list))
    self._ErrorIf(test, constants.CV_ENODEDRBD, ninfo.name,
                  "cannot parse drbd status file: %s", str(used_minors))
    if test:
      # we cannot check drbd status
      return

    for minor, (inst_uuid, must_exist) in node_drbd.items():
      test = minor not in used_minors and must_exist
      self._ErrorIf(test, constants.CV_ENODEDRBD, ninfo.name,
                    "drbd minor %d of instance %s is not active", minor,
                    self.cfg.GetInstanceName(inst_uuid))
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
            not compat.all(isinstance(v, list) and len(v) == 7
                           for v in remote_os))

    self._ErrorIf(test, constants.CV_ENODEOS, ninfo.name,
                  "node hasn't returned valid OS data")

    nimg.os_fail = test

    if test:
      return

    os_dict = {}

    for (name, os_path, status, diagnose,
         variants, parameters, api_ver) in nresult[constants.NV_OSLIST]:

      if name not in os_dict:
        os_dict[name] = []

      # parameters is a list of lists instead of list of tuples due to
      # JSON lacking a real tuple type, fix it:
      parameters = [tuple(v) for v in parameters]
      os_dict[name].append((os_path, status, diagnose,
                            set(variants), set(parameters), set(api_ver)))

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
      f_path, f_status, f_diag, f_var, f_param, f_api = os_data[0]
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
      _, b_status, _, b_var, b_param, b_api = base.oslist[os_name][0]
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
              constants.ST_FILE, constants.ST_SHARED_FILE
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
      nimg.instances = [inst.uuid for (_, inst) in
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
    diskless = constants.DT_DISKLESS

    for nuuid in node_uuids:
      node_inst_uuids = list(itertools.chain(node_image[nuuid].pinst,
                                             node_image[nuuid].sinst))
      diskless_instances.update(uuid for uuid in node_inst_uuids
                                if instanceinfo[uuid].disk_template == diskless)
      disks = [(inst_uuid, disk)
               for inst_uuid in node_inst_uuids
               for disk in instanceinfo[inst_uuid].disks]

      if not disks:
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

    assert compat.all(len(statuses) == len(instanceinfo[inst].disks) and
                      len(nuuids) <= len(instanceinfo[inst].all_nodes) and
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
               [sorted(map(operator.attrgetter("name"), names))
                for _, names in itertools.groupby(sorted(nodes, key=keyfunc),
                                                  keyfunc)])

  @classmethod
  def _SelectSshCheckNodes(cls, group_nodes, group_uuid, all_nodes):
    """Choose which nodes should talk to which other nodes.

    We will make nodes contact all nodes in their group, and one node from
    every other group.

    @warning: This algorithm has a known issue if one node group is much
      smaller than others (e.g. just one node). In such a case all other
      nodes will talk to the single node.

    """
    online_nodes = sorted(node.name for node in group_nodes if not node.offline)
    sel = cls._SshNodeSelector(group_uuid, all_nodes)

    return (online_nodes,
            dict((name, sorted([i.next() for i in sel]))
                 for name in online_nodes))

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

  def Exec(self, feedback_fn):
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

    feedback_fn("* Gathering data (%d nodes)" % len(self.my_node_uuids))

    user_scripts = []
    if self.cfg.GetUseExternalMipScript():
      user_scripts.append(pathutils.EXTERNAL_MASTER_SETUP_SCRIPT)

    node_verify_param = {
      constants.NV_FILELIST:
        map(vcluster.MakeVirtualPath,
            utils.UniqueSequence(filename
                                 for files in filemap
                                 for filename in files)),
      constants.NV_NODELIST:
        self._SelectSshCheckNodes(node_data_list, self.group_uuid,
                                  self.all_node_info.values()),
      constants.NV_HYPERVISOR: hypervisors,
      constants.NV_HVPARAMS:
        _GetAllHypervisorParameters(cluster, self.all_inst_info.values()),
      constants.NV_NODENETTEST: [(node.name, node.primary_ip, node.secondary_ip)
                                 for node in node_data_list
                                 if not node.offline],
      constants.NV_INSTANCELIST: hypervisors,
      constants.NV_VERSION: None,
      constants.NV_HVINFO: self.cfg.GetHypervisorType(),
      constants.NV_NODESETUP: None,
      constants.NV_TIME: None,
      constants.NV_MASTERIP: (self.cfg.GetMasterNodeName(), master_ip),
      constants.NV_OSLIST: None,
      constants.NV_VMNODES: self.cfg.GetNonVmCapableNodeList(),
      constants.NV_USERSCRIPTS: user_scripts,
      constants.NV_CLIENT_CERT: None,
      }

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

      for nuuid in instance.all_nodes:
        if nuuid not in node_image:
          gnode = self.NodeImage(uuid=nuuid)
          gnode.ghost = (nuuid not in self.all_node_info)
          node_image[nuuid] = gnode

      instance.MapLVsByNode(node_vol_should)

      pnode = instance.primary_node
      node_image[pnode].pinst.append(instance.uuid)

      for snode in instance.secondary_nodes:
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

    node_group_uuids = dict(map(lambda n: (n.name, n.group),
                                self.cfg.GetAllNodesInfo().values()))
    groups_config = self.cfg.GetAllNodeGroupsInfoDict()

    # At this point, we have the in-memory data structures complete,
    # except for the runtime information, which we'll gather next

    # Due to the way our RPC system works, exact response times cannot be
    # guaranteed (e.g. a broken node could run into a timeout). By keeping the
    # time before and after executing the request, we can at least have a time
    # window.
    nvinfo_starttime = time.time()
    all_nvinfo = self.rpc.call_node_verify(self.my_node_uuids,
                                           node_verify_param,
                                           self.cfg.GetClusterName(),
                                           self.cfg.GetClusterInfo().hvparams,
                                           node_group_uuids,
                                           groups_config)
    nvinfo_endtime = time.time()

    if self.extra_lv_nodes and vg_name is not None:
      extra_lv_nvinfo = \
          self.rpc.call_node_verify(self.extra_lv_nodes,
                                    {constants.NV_LVLIST: vg_name},
                                    self.cfg.GetClusterName(),
                                    self.cfg.GetClusterInfo().hvparams,
                                    node_group_uuids,
                                    groups_config)
    else:
      extra_lv_nvinfo = {}

    all_drbd_map = self.cfg.ComputeDRBDMap()

    feedback_fn("* Gathering disk information (%s nodes)" %
                len(self.my_node_uuids))
    instdisk = self._CollectDiskInfo(self.my_node_info.keys(), node_image,
                                     self.my_inst_info)

    feedback_fn("* Verifying configuration file consistency")

    # If not all nodes are being checked, we need to make sure the master node
    # and a non-checked vm_capable node are in the list.
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
      vf_nvinfo.update(self.rpc.call_node_verify(
         additional_node_uuids, {key: node_verify_param[key]},
         self.cfg.GetClusterName(), self.cfg.GetClusterInfo().hvparams,
         node_group_uuids,
         groups_config))
    else:
      vf_nvinfo = all_nvinfo
      vf_node_info = self.my_node_info.values()

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

      if nimg.vm_capable:
        self._UpdateVerifyNodeLVM(node_i, nresult, vg_name, nimg)
        self._VerifyNodeDrbd(node_i, nresult, self.all_inst_info, drbd_helper,
                             all_drbd_map)

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

      # If the instance is non-redundant we cannot survive losing its primary
      # node, so we are not N+1 compliant.
      if instance.disk_template not in constants.DTS_MIRRORED:
        i_non_redundant.append(instance)

      if not cluster.FillBE(instance)[constants.BE_AUTO_BALANCE]:
        i_non_a_balanced.append(instance)

    feedback_fn("* Verifying orphan volumes")
    reserved = utils.FieldSet(*cluster.reserved_lvs)

    # We will get spurious "unknown volume" warnings if any node of this group
    # is secondary for an instance whose primary is in another group. To avoid
    # them, we find these instances and add their volumes to node_vol_should.
    for instance in self.all_inst_info.values():
      for secondary in instance.secondary_nodes:
        if (secondary in self.my_node_info
            and instance.name not in self.my_inst_info):
          instance.MapLVsByNode(node_vol_should)
          break

    self._VerifyOrphanVolumes(node_vol_should, node_image, reserved)

    if constants.VERIFY_NPLUSONE_MEM not in self.op.skip_checks:
      feedback_fn("* Verifying N+1 Memory redundancy")
      self._VerifyNPlusOneMemory(node_image, self.my_inst_info)

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
        if res.offline or msg:
          # No need to investigate payload if node is offline or gave
          # an error.
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


class LUClusterVerifyDisks(NoHooksLU):
  """Verifies the cluster disks status.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = ShareAll()
    self.needed_locks = {
      locking.LEVEL_NODEGROUP: locking.ALL_SET,
      }

  def Exec(self, feedback_fn):
    group_names = self.owned_locks(locking.LEVEL_NODEGROUP)

    # Submit one instance of L{opcodes.OpGroupVerifyDisks} per node group
    return ResultWithJobs([[opcodes.OpGroupVerifyDisks(group_name=group)]
                           for group in group_names])
