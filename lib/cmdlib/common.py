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


"""Common functions used by multiple logical units."""

import copy
import os

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti import objects
from ganeti import opcodes
from ganeti import pathutils
from ganeti import rpc
from ganeti import ssconf
from ganeti import utils


# States of instance
INSTANCE_DOWN = [constants.ADMINST_DOWN]
INSTANCE_ONLINE = [constants.ADMINST_DOWN, constants.ADMINST_UP]
INSTANCE_NOT_RUNNING = [constants.ADMINST_DOWN, constants.ADMINST_OFFLINE]

#: Instance status in which an instance can be marked as offline/online
CAN_CHANGE_INSTANCE_OFFLINE = (frozenset(INSTANCE_DOWN) | frozenset([
  constants.ADMINST_OFFLINE,
  ]))


def _ExpandItemName(expand_fn, name, kind):
  """Expand an item name.

  @param expand_fn: the function to use for expansion
  @param name: requested item name
  @param kind: text description ('Node' or 'Instance')
  @return: the result of the expand_fn, if successful
  @raise errors.OpPrereqError: if the item is not found

  """
  (uuid, full_name) = expand_fn(name)
  if uuid is None or full_name is None:
    raise errors.OpPrereqError("%s '%s' not known" % (kind, name),
                               errors.ECODE_NOENT)
  return (uuid, full_name)


def ExpandInstanceUuidAndName(cfg, expected_uuid, name):
  """Wrapper over L{_ExpandItemName} for instance."""
  (uuid, full_name) = _ExpandItemName(cfg.ExpandInstanceName, name, "Instance")
  if expected_uuid is not None and uuid != expected_uuid:
    raise errors.OpPrereqError(
      "The instances UUID '%s' does not match the expected UUID '%s' for"
      " instance '%s'. Maybe the instance changed since you submitted this"
      " job." % (uuid, expected_uuid, full_name), errors.ECODE_NOTUNIQUE)
  return (uuid, full_name)


def ExpandNodeUuidAndName(cfg, expected_uuid, name):
  """Expand a short node name into the node UUID and full name.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type expected_uuid: string
  @param expected_uuid: expected UUID for the node (or None if there is no
        expectation). If it does not match, a L{errors.OpPrereqError} is
        raised.
  @type name: string
  @param name: the short node name

  """
  (uuid, full_name) = _ExpandItemName(cfg.ExpandNodeName, name, "Node")
  if expected_uuid is not None and uuid != expected_uuid:
    raise errors.OpPrereqError(
      "The nodes UUID '%s' does not match the expected UUID '%s' for node"
      " '%s'. Maybe the node changed since you submitted this job." %
      (uuid, expected_uuid, full_name), errors.ECODE_NOTUNIQUE)
  return (uuid, full_name)


def ShareAll():
  """Returns a dict declaring all lock levels shared.

  """
  return dict.fromkeys(locking.LEVELS, 1)


def CheckNodeGroupInstances(cfg, group_uuid, owned_instance_names):
  """Checks if the instances in a node group are still correct.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type group_uuid: string
  @param group_uuid: Node group UUID
  @type owned_instance_names: set or frozenset
  @param owned_instance_names: List of currently owned instances

  """
  wanted_instances = frozenset(cfg.GetInstanceNames(
                                 cfg.GetNodeGroupInstances(group_uuid)))
  if owned_instance_names != wanted_instances:
    raise errors.OpPrereqError("Instances in node group '%s' changed since"
                               " locks were acquired, wanted '%s', have '%s';"
                               " retry the operation" %
                               (group_uuid,
                                utils.CommaJoin(wanted_instances),
                                utils.CommaJoin(owned_instance_names)),
                               errors.ECODE_STATE)

  return wanted_instances


def GetWantedNodes(lu, short_node_names):
  """Returns list of checked and expanded node names.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type short_node_names: list
  @param short_node_names: list of node names or None for all nodes
  @rtype: tuple of lists
  @return: tupe with (list of node UUIDs, list of node names)
  @raise errors.ProgrammerError: if the nodes parameter is wrong type

  """
  if short_node_names:
    node_uuids = [ExpandNodeUuidAndName(lu.cfg, None, name)[0]
                  for name in short_node_names]
  else:
    node_uuids = lu.cfg.GetNodeList()

  return (node_uuids, [lu.cfg.GetNodeName(uuid) for uuid in node_uuids])


def GetWantedInstances(lu, short_inst_names):
  """Returns list of checked and expanded instance names.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type short_inst_names: list
  @param short_inst_names: list of instance names or None for all instances
  @rtype: tuple of lists
  @return: tuple of (instance UUIDs, instance names)
  @raise errors.OpPrereqError: if the instances parameter is wrong type
  @raise errors.OpPrereqError: if any of the passed instances is not found

  """
  if short_inst_names:
    inst_uuids = [ExpandInstanceUuidAndName(lu.cfg, None, name)[0]
                  for name in short_inst_names]
  else:
    inst_uuids = lu.cfg.GetInstanceList()
  return (inst_uuids, [lu.cfg.GetInstanceName(uuid) for uuid in inst_uuids])


def RunPostHook(lu, node_name):
  """Runs the post-hook for an opcode on a single node.

  """
  hm = lu.proc.BuildHooksManager(lu)
  try:
    hm.RunPhase(constants.HOOKS_PHASE_POST, node_names=[node_name])
  except Exception, err: # pylint: disable=W0703
    lu.LogWarning("Errors occurred running hooks on %s: %s",
                  node_name, err)


def RedistributeAncillaryFiles(lu):
  """Distribute additional files which are part of the cluster configuration.

  ConfigWriter takes care of distributing the config and ssconf files, but
  there are more files which should be distributed to all nodes. This function
  makes sure those are copied.

  """
  # Gather target nodes
  cluster = lu.cfg.GetClusterInfo()
  master_info = lu.cfg.GetMasterNodeInfo()

  online_node_uuids = lu.cfg.GetOnlineNodeList()
  online_node_uuid_set = frozenset(online_node_uuids)
  vm_node_uuids = list(online_node_uuid_set.intersection(
                         lu.cfg.GetVmCapableNodeList()))

  # Never distribute to master node
  for node_uuids in [online_node_uuids, vm_node_uuids]:
    if master_info.uuid in node_uuids:
      node_uuids.remove(master_info.uuid)

  # Gather file lists
  (files_all, _, files_mc, files_vm) = \
    ComputeAncillaryFiles(cluster, True)

  # Never re-distribute configuration file from here
  assert not (pathutils.CLUSTER_CONF_FILE in files_all or
              pathutils.CLUSTER_CONF_FILE in files_vm)
  assert not files_mc, "Master candidates not handled in this function"

  filemap = [
    (online_node_uuids, files_all),
    (vm_node_uuids, files_vm),
    ]

  # Upload the files
  for (node_uuids, files) in filemap:
    for fname in files:
      UploadHelper(lu, node_uuids, fname)


def ComputeAncillaryFiles(cluster, redist):
  """Compute files external to Ganeti which need to be consistent.

  @type redist: boolean
  @param redist: Whether to include files which need to be redistributed

  """
  # Compute files for all nodes
  files_all = set([
    pathutils.SSH_KNOWN_HOSTS_FILE,
    pathutils.CONFD_HMAC_KEY,
    pathutils.CLUSTER_DOMAIN_SECRET_FILE,
    pathutils.SPICE_CERT_FILE,
    pathutils.SPICE_CACERT_FILE,
    pathutils.RAPI_USERS_FILE,
    ])

  if redist:
    # we need to ship at least the RAPI certificate
    files_all.add(pathutils.RAPI_CERT_FILE)
  else:
    files_all.update(pathutils.ALL_CERT_FILES)
    files_all.update(ssconf.SimpleStore().GetFileList())

  if cluster.modify_etc_hosts:
    files_all.add(pathutils.ETC_HOSTS)

  if cluster.use_external_mip_script:
    files_all.add(pathutils.EXTERNAL_MASTER_SETUP_SCRIPT)

  # Files which are optional, these must:
  # - be present in one other category as well
  # - either exist or not exist on all nodes of that category (mc, vm all)
  files_opt = set([
    pathutils.RAPI_USERS_FILE,
    ])

  # Files which should only be on master candidates
  files_mc = set()

  if not redist:
    files_mc.add(pathutils.CLUSTER_CONF_FILE)

  # File storage
  if (not redist and (cluster.IsFileStorageEnabled() or
                        cluster.IsSharedFileStorageEnabled())):
    files_all.add(pathutils.FILE_STORAGE_PATHS_FILE)
    files_opt.add(pathutils.FILE_STORAGE_PATHS_FILE)

  # Files which should only be on VM-capable nodes
  files_vm = set(
    filename
    for hv_name in cluster.enabled_hypervisors
    for filename in
    hypervisor.GetHypervisorClass(hv_name).GetAncillaryFiles()[0])

  files_opt |= set(
    filename
    for hv_name in cluster.enabled_hypervisors
    for filename in
    hypervisor.GetHypervisorClass(hv_name).GetAncillaryFiles()[1])

  # Filenames in each category must be unique
  all_files_set = files_all | files_mc | files_vm
  assert (len(all_files_set) ==
          sum(map(len, [files_all, files_mc, files_vm]))), \
    "Found file listed in more than one file list"

  # Optional files must be present in one other category
  assert all_files_set.issuperset(files_opt), \
    "Optional file not in a different required list"

  # This one file should never ever be re-distributed via RPC
  assert not (redist and
              pathutils.FILE_STORAGE_PATHS_FILE in all_files_set)

  return (files_all, files_opt, files_mc, files_vm)


def UploadHelper(lu, node_uuids, fname):
  """Helper for uploading a file and showing warnings.

  """
  if os.path.exists(fname):
    result = lu.rpc.call_upload_file(node_uuids, fname)
    for to_node_uuids, to_result in result.items():
      msg = to_result.fail_msg
      if msg:
        msg = ("Copy of file %s to node %s failed: %s" %
               (fname, lu.cfg.GetNodeName(to_node_uuids), msg))
        lu.LogWarning(msg)


def MergeAndVerifyHvState(op_input, obj_input):
  """Combines the hv state from an opcode with the one of the object

  @param op_input: The input dict from the opcode
  @param obj_input: The input dict from the objects
  @return: The verified and updated dict

  """
  if op_input:
    invalid_hvs = set(op_input) - constants.HYPER_TYPES
    if invalid_hvs:
      raise errors.OpPrereqError("Invalid hypervisor(s) in hypervisor state:"
                                 " %s" % utils.CommaJoin(invalid_hvs),
                                 errors.ECODE_INVAL)
    if obj_input is None:
      obj_input = {}
    type_check = constants.HVSTS_PARAMETER_TYPES
    return _UpdateAndVerifySubDict(obj_input, op_input, type_check)

  return None


def MergeAndVerifyDiskState(op_input, obj_input):
  """Combines the disk state from an opcode with the one of the object

  @param op_input: The input dict from the opcode
  @param obj_input: The input dict from the objects
  @return: The verified and updated dict
  """
  if op_input:
    invalid_dst = set(op_input) - constants.DS_VALID_TYPES
    if invalid_dst:
      raise errors.OpPrereqError("Invalid storage type(s) in disk state: %s" %
                                 utils.CommaJoin(invalid_dst),
                                 errors.ECODE_INVAL)
    type_check = constants.DSS_PARAMETER_TYPES
    if obj_input is None:
      obj_input = {}
    return dict((key, _UpdateAndVerifySubDict(obj_input.get(key, {}), value,
                                              type_check))
                for key, value in op_input.items())

  return None


def CheckOSParams(lu, required, node_uuids, osname, osparams):
  """OS parameters validation.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit for which we check
  @type required: boolean
  @param required: whether the validation should fail if the OS is not
      found
  @type node_uuids: list
  @param node_uuids: the list of nodes on which we should check
  @type osname: string
  @param osname: the name of the hypervisor we should use
  @type osparams: dict
  @param osparams: the parameters which we need to check
  @raise errors.OpPrereqError: if the parameters are not valid

  """
  node_uuids = _FilterVmNodes(lu, node_uuids)
  result = lu.rpc.call_os_validate(node_uuids, required, osname,
                                   [constants.OS_VALIDATE_PARAMETERS],
                                   osparams)
  for node_uuid, nres in result.items():
    # we don't check for offline cases since this should be run only
    # against the master node and/or an instance's nodes
    nres.Raise("OS Parameters validation failed on node %s" %
               lu.cfg.GetNodeName(node_uuid))
    if not nres.payload:
      lu.LogInfo("OS %s not found on node %s, validation skipped",
                 osname, lu.cfg.GetNodeName(node_uuid))


def CheckHVParams(lu, node_uuids, hvname, hvparams):
  """Hypervisor parameter validation.

  This function abstract the hypervisor parameter validation to be
  used in both instance create and instance modify.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit for which we check
  @type node_uuids: list
  @param node_uuids: the list of nodes on which we should check
  @type hvname: string
  @param hvname: the name of the hypervisor we should use
  @type hvparams: dict
  @param hvparams: the parameters which we need to check
  @raise errors.OpPrereqError: if the parameters are not valid

  """
  node_uuids = _FilterVmNodes(lu, node_uuids)

  cluster = lu.cfg.GetClusterInfo()
  hvfull = objects.FillDict(cluster.hvparams.get(hvname, {}), hvparams)

  hvinfo = lu.rpc.call_hypervisor_validate_params(node_uuids, hvname, hvfull)
  for node_uuid in node_uuids:
    info = hvinfo[node_uuid]
    if info.offline:
      continue
    info.Raise("Hypervisor parameter validation failed on node %s" %
               lu.cfg.GetNodeName(node_uuid))


def AdjustCandidatePool(lu, exceptions):
  """Adjust the candidate pool after node operations.

  """
  mod_list = lu.cfg.MaintainCandidatePool(exceptions)
  if mod_list:
    lu.LogInfo("Promoted nodes to master candidate role: %s",
               utils.CommaJoin(node.name for node in mod_list))
    for node in mod_list:
      lu.context.ReaddNode(node)
  mc_now, mc_max, _ = lu.cfg.GetMasterCandidateStats(exceptions)
  if mc_now > mc_max:
    lu.LogInfo("Note: more nodes are candidates (%d) than desired (%d)" %
               (mc_now, mc_max))


def CheckNodePVs(nresult, exclusive_storage):
  """Check node PVs.

  """
  pvlist_dict = nresult.get(constants.NV_PVLIST, None)
  if pvlist_dict is None:
    return (["Can't get PV list from node"], None)
  pvlist = map(objects.LvmPvInfo.FromDict, pvlist_dict)
  errlist = []
  # check that ':' is not present in PV names, since it's a
  # special character for lvcreate (denotes the range of PEs to
  # use on the PV)
  for pv in pvlist:
    if ":" in pv.name:
      errlist.append("Invalid character ':' in PV '%s' of VG '%s'" %
                     (pv.name, pv.vg_name))
  es_pvinfo = None
  if exclusive_storage:
    (errmsgs, es_pvinfo) = utils.LvmExclusiveCheckNodePvs(pvlist)
    errlist.extend(errmsgs)
    shared_pvs = nresult.get(constants.NV_EXCLUSIVEPVS, None)
    if shared_pvs:
      for (pvname, lvlist) in shared_pvs:
        # TODO: Check that LVs are really unrelated (snapshots, DRBD meta...)
        errlist.append("PV %s is shared among unrelated LVs (%s)" %
                       (pvname, utils.CommaJoin(lvlist)))
  return (errlist, es_pvinfo)


def _ComputeMinMaxSpec(name, qualifier, ispecs, value):
  """Computes if value is in the desired range.

  @param name: name of the parameter for which we perform the check
  @param qualifier: a qualifier used in the error message (e.g. 'disk/1',
      not just 'disk')
  @param ispecs: dictionary containing min and max values
  @param value: actual value that we want to use
  @return: None or an error string

  """
  if value in [None, constants.VALUE_AUTO]:
    return None
  max_v = ispecs[constants.ISPECS_MAX].get(name, value)
  min_v = ispecs[constants.ISPECS_MIN].get(name, value)
  if value > max_v or min_v > value:
    if qualifier:
      fqn = "%s/%s" % (name, qualifier)
    else:
      fqn = name
    return ("%s value %s is not in range [%s, %s]" %
            (fqn, value, min_v, max_v))
  return None


def ComputeIPolicySpecViolation(ipolicy, mem_size, cpu_count, disk_count,
                                nic_count, disk_sizes, spindle_use,
                                disk_template,
                                _compute_fn=_ComputeMinMaxSpec):
  """Verifies ipolicy against provided specs.

  @type ipolicy: dict
  @param ipolicy: The ipolicy
  @type mem_size: int
  @param mem_size: The memory size
  @type cpu_count: int
  @param cpu_count: Used cpu cores
  @type disk_count: int
  @param disk_count: Number of disks used
  @type nic_count: int
  @param nic_count: Number of nics used
  @type disk_sizes: list of ints
  @param disk_sizes: Disk sizes of used disk (len must match C{disk_count})
  @type spindle_use: int
  @param spindle_use: The number of spindles this instance uses
  @type disk_template: string
  @param disk_template: The disk template of the instance
  @param _compute_fn: The compute function (unittest only)
  @return: A list of violations, or an empty list of no violations are found

  """
  assert disk_count == len(disk_sizes)

  test_settings = [
    (constants.ISPEC_MEM_SIZE, "", mem_size),
    (constants.ISPEC_CPU_COUNT, "", cpu_count),
    (constants.ISPEC_NIC_COUNT, "", nic_count),
    (constants.ISPEC_SPINDLE_USE, "", spindle_use),
    ] + [(constants.ISPEC_DISK_SIZE, str(idx), d)
         for idx, d in enumerate(disk_sizes)]
  if disk_template != constants.DT_DISKLESS:
    # This check doesn't make sense for diskless instances
    test_settings.append((constants.ISPEC_DISK_COUNT, "", disk_count))
  ret = []
  allowed_dts = ipolicy[constants.IPOLICY_DTS]
  if disk_template not in allowed_dts:
    ret.append("Disk template %s is not allowed (allowed templates: %s)" %
               (disk_template, utils.CommaJoin(allowed_dts)))

  min_errs = None
  for minmax in ipolicy[constants.ISPECS_MINMAX]:
    errs = filter(None,
                  (_compute_fn(name, qualifier, minmax, value)
                   for (name, qualifier, value) in test_settings))
    if min_errs is None or len(errs) < len(min_errs):
      min_errs = errs
  assert min_errs is not None
  return ret + min_errs


def ComputeIPolicyInstanceViolation(ipolicy, instance, cfg,
                                    _compute_fn=ComputeIPolicySpecViolation):
  """Compute if instance meets the specs of ipolicy.

  @type ipolicy: dict
  @param ipolicy: The ipolicy to verify against
  @type instance: L{objects.Instance}
  @param instance: The instance to verify
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @param _compute_fn: The function to verify ipolicy (unittest only)
  @see: L{ComputeIPolicySpecViolation}

  """
  ret = []
  be_full = cfg.GetClusterInfo().FillBE(instance)
  mem_size = be_full[constants.BE_MAXMEM]
  cpu_count = be_full[constants.BE_VCPUS]
  es_flags = rpc.GetExclusiveStorageForNodes(cfg, instance.all_nodes)
  if any(es_flags.values()):
    # With exclusive storage use the actual spindles
    try:
      spindle_use = sum([disk.spindles for disk in instance.disks])
    except TypeError:
      ret.append("Number of spindles not configured for disks of instance %s"
                 " while exclusive storage is enabled, try running gnt-cluster"
                 " repair-disk-sizes" % instance.name)
      # _ComputeMinMaxSpec ignores 'None's
      spindle_use = None
  else:
    spindle_use = be_full[constants.BE_SPINDLE_USE]
  disk_count = len(instance.disks)
  disk_sizes = [disk.size for disk in instance.disks]
  nic_count = len(instance.nics)
  disk_template = instance.disk_template

  return ret + _compute_fn(ipolicy, mem_size, cpu_count, disk_count, nic_count,
                           disk_sizes, spindle_use, disk_template)


def _ComputeViolatingInstances(ipolicy, instances, cfg):
  """Computes a set of instances who violates given ipolicy.

  @param ipolicy: The ipolicy to verify
  @type instances: L{objects.Instance}
  @param instances: List of instances to verify
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @return: A frozenset of instance names violating the ipolicy

  """
  return frozenset([inst.name for inst in instances
                    if ComputeIPolicyInstanceViolation(ipolicy, inst, cfg)])


def ComputeNewInstanceViolations(old_ipolicy, new_ipolicy, instances, cfg):
  """Computes a set of any instances that would violate the new ipolicy.

  @param old_ipolicy: The current (still in-place) ipolicy
  @param new_ipolicy: The new (to become) ipolicy
  @param instances: List of instances to verify
  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @return: A list of instances which violates the new ipolicy but
      did not before

  """
  return (_ComputeViolatingInstances(new_ipolicy, instances, cfg) -
          _ComputeViolatingInstances(old_ipolicy, instances, cfg))


def GetUpdatedParams(old_params, update_dict,
                      use_default=True, use_none=False):
  """Return the new version of a parameter dictionary.

  @type old_params: dict
  @param old_params: old parameters
  @type update_dict: dict
  @param update_dict: dict containing new parameter values, or
      constants.VALUE_DEFAULT to reset the parameter to its default
      value
  @param use_default: boolean
  @type use_default: whether to recognise L{constants.VALUE_DEFAULT}
      values as 'to be deleted' values
  @param use_none: boolean
  @type use_none: whether to recognise C{None} values as 'to be
      deleted' values
  @rtype: dict
  @return: the new parameter dictionary

  """
  params_copy = copy.deepcopy(old_params)
  for key, val in update_dict.iteritems():
    if ((use_default and val == constants.VALUE_DEFAULT) or
          (use_none and val is None)):
      try:
        del params_copy[key]
      except KeyError:
        pass
    else:
      params_copy[key] = val
  return params_copy


def GetUpdatedIPolicy(old_ipolicy, new_ipolicy, group_policy=False):
  """Return the new version of an instance policy.

  @param group_policy: whether this policy applies to a group and thus
    we should support removal of policy entries

  """
  ipolicy = copy.deepcopy(old_ipolicy)
  for key, value in new_ipolicy.items():
    if key not in constants.IPOLICY_ALL_KEYS:
      raise errors.OpPrereqError("Invalid key in new ipolicy: %s" % key,
                                 errors.ECODE_INVAL)
    if (not value or value == [constants.VALUE_DEFAULT] or
            value == constants.VALUE_DEFAULT):
      if group_policy:
        if key in ipolicy:
          del ipolicy[key]
      else:
        raise errors.OpPrereqError("Can't unset ipolicy attribute '%s'"
                                   " on the cluster'" % key,
                                   errors.ECODE_INVAL)
    else:
      if key in constants.IPOLICY_PARAMETERS:
        # FIXME: we assume all such values are float
        try:
          ipolicy[key] = float(value)
        except (TypeError, ValueError), err:
          raise errors.OpPrereqError("Invalid value for attribute"
                                     " '%s': '%s', error: %s" %
                                     (key, value, err), errors.ECODE_INVAL)
      elif key == constants.ISPECS_MINMAX:
        for minmax in value:
          for k in minmax.keys():
            utils.ForceDictType(minmax[k], constants.ISPECS_PARAMETER_TYPES)
        ipolicy[key] = value
      elif key == constants.ISPECS_STD:
        if group_policy:
          msg = "%s cannot appear in group instance specs" % key
          raise errors.OpPrereqError(msg, errors.ECODE_INVAL)
        ipolicy[key] = GetUpdatedParams(old_ipolicy.get(key, {}), value,
                                        use_none=False, use_default=False)
        utils.ForceDictType(ipolicy[key], constants.ISPECS_PARAMETER_TYPES)
      else:
        # FIXME: we assume all others are lists; this should be redone
        # in a nicer way
        ipolicy[key] = list(value)
  try:
    objects.InstancePolicy.CheckParameterSyntax(ipolicy, not group_policy)
  except errors.ConfigurationError, err:
    raise errors.OpPrereqError("Invalid instance policy: %s" % err,
                               errors.ECODE_INVAL)
  return ipolicy


def AnnotateDiskParams(instance, devs, cfg):
  """Little helper wrapper to the rpc annotation method.

  @param instance: The instance object
  @type devs: List of L{objects.Disk}
  @param devs: The root devices (not any of its children!)
  @param cfg: The config object
  @returns The annotated disk copies
  @see L{rpc.AnnotateDiskParams}

  """
  return rpc.AnnotateDiskParams(devs, cfg.GetInstanceDiskParams(instance))


def SupportsOob(cfg, node):
  """Tells if node supports OOB.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type node: L{objects.Node}
  @param node: The node
  @return: The OOB script if supported or an empty string otherwise

  """
  return cfg.GetNdParams(node)[constants.ND_OOB_PROGRAM]


def _UpdateAndVerifySubDict(base, updates, type_check):
  """Updates and verifies a dict with sub dicts of the same type.

  @param base: The dict with the old data
  @param updates: The dict with the new data
  @param type_check: Dict suitable to ForceDictType to verify correct types
  @returns: A new dict with updated and verified values

  """
  def fn(old, value):
    new = GetUpdatedParams(old, value)
    utils.ForceDictType(new, type_check)
    return new

  ret = copy.deepcopy(base)
  ret.update(dict((key, fn(base.get(key, {}), value))
                  for key, value in updates.items()))
  return ret


def _FilterVmNodes(lu, node_uuids):
  """Filters out non-vm_capable nodes from a list.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit for which we check
  @type node_uuids: list
  @param node_uuids: the list of nodes on which we should check
  @rtype: list
  @return: the list of vm-capable nodes

  """
  vm_nodes = frozenset(lu.cfg.GetNonVmCapableNodeList())
  return [uuid for uuid in node_uuids if uuid not in vm_nodes]


def GetDefaultIAllocator(cfg, ialloc):
  """Decides on which iallocator to use.

  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration object
  @type ialloc: string or None
  @param ialloc: Iallocator specified in opcode
  @rtype: string
  @return: Iallocator name

  """
  if not ialloc:
    # Use default iallocator
    ialloc = cfg.GetDefaultIAllocator()

  if not ialloc:
    raise errors.OpPrereqError("No iallocator was specified, neither in the"
                               " opcode nor as a cluster-wide default",
                               errors.ECODE_INVAL)

  return ialloc


def CheckInstancesNodeGroups(cfg, instances, owned_groups, owned_node_uuids,
                             cur_group_uuid):
  """Checks if node groups for locked instances are still correct.

  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @type instances: dict; string as key, L{objects.Instance} as value
  @param instances: Dictionary, instance UUID as key, instance object as value
  @type owned_groups: iterable of string
  @param owned_groups: List of owned groups
  @type owned_node_uuids: iterable of string
  @param owned_node_uuids: List of owned nodes
  @type cur_group_uuid: string or None
  @param cur_group_uuid: Optional group UUID to check against instance's groups

  """
  for (uuid, inst) in instances.items():
    assert owned_node_uuids.issuperset(inst.all_nodes), \
      "Instance %s's nodes changed while we kept the lock" % inst.name

    inst_groups = CheckInstanceNodeGroups(cfg, uuid, owned_groups)

    assert cur_group_uuid is None or cur_group_uuid in inst_groups, \
      "Instance %s has no node in group %s" % (inst.name, cur_group_uuid)


def CheckInstanceNodeGroups(cfg, inst_uuid, owned_groups, primary_only=False):
  """Checks if the owned node groups are still correct for an instance.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type inst_uuid: string
  @param inst_uuid: Instance UUID
  @type owned_groups: set or frozenset
  @param owned_groups: List of currently owned node groups
  @type primary_only: boolean
  @param primary_only: Whether to check node groups for only the primary node

  """
  inst_groups = cfg.GetInstanceNodeGroups(inst_uuid, primary_only)

  if not owned_groups.issuperset(inst_groups):
    raise errors.OpPrereqError("Instance %s's node groups changed since"
                               " locks were acquired, current groups are"
                               " are '%s', owning groups '%s'; retry the"
                               " operation" %
                               (cfg.GetInstanceName(inst_uuid),
                                utils.CommaJoin(inst_groups),
                                utils.CommaJoin(owned_groups)),
                               errors.ECODE_STATE)

  return inst_groups


def LoadNodeEvacResult(lu, alloc_result, early_release, use_nodes):
  """Unpacks the result of change-group and node-evacuate iallocator requests.

  Iallocator modes L{constants.IALLOCATOR_MODE_NODE_EVAC} and
  L{constants.IALLOCATOR_MODE_CHG_GROUP}.

  @type lu: L{LogicalUnit}
  @param lu: Logical unit instance
  @type alloc_result: tuple/list
  @param alloc_result: Result from iallocator
  @type early_release: bool
  @param early_release: Whether to release locks early if possible
  @type use_nodes: bool
  @param use_nodes: Whether to display node names instead of groups

  """
  (moved, failed, jobs) = alloc_result

  if failed:
    failreason = utils.CommaJoin("%s (%s)" % (name, reason)
                                 for (name, reason) in failed)
    lu.LogWarning("Unable to evacuate instances %s", failreason)
    raise errors.OpExecError("Unable to evacuate instances %s" % failreason)

  if moved:
    lu.LogInfo("Instances to be moved: %s",
               utils.CommaJoin(
                 "%s (to %s)" %
                 (name, _NodeEvacDest(use_nodes, group, node_names))
                 for (name, group, node_names) in moved))

  return [map(compat.partial(_SetOpEarlyRelease, early_release),
              map(opcodes.OpCode.LoadOpCode, ops))
          for ops in jobs]


def _NodeEvacDest(use_nodes, group, node_names):
  """Returns group or nodes depending on caller's choice.

  """
  if use_nodes:
    return utils.CommaJoin(node_names)
  else:
    return group


def _SetOpEarlyRelease(early_release, op):
  """Sets C{early_release} flag on opcodes if available.

  """
  try:
    op.early_release = early_release
  except AttributeError:
    assert not isinstance(op, opcodes.OpInstanceReplaceDisks)

  return op


def MapInstanceLvsToNodes(instances):
  """Creates a map from (node, volume) to instance name.

  @type instances: list of L{objects.Instance}
  @rtype: dict; tuple of (node uuid, volume name) as key, L{objects.Instance}
          object as value

  """
  return dict(((node_uuid, vol), inst)
              for inst in instances
              for (node_uuid, vols) in inst.MapLVsByNode().items()
              for vol in vols)


def CheckParamsNotGlobal(params, glob_pars, kind, bad_levels, good_levels):
  """Make sure that none of the given paramters is global.

  If a global parameter is found, an L{errors.OpPrereqError} exception is
  raised. This is used to avoid setting global parameters for individual nodes.

  @type params: dictionary
  @param params: Parameters to check
  @type glob_pars: dictionary
  @param glob_pars: Forbidden parameters
  @type kind: string
  @param kind: Kind of parameters (e.g. "node")
  @type bad_levels: string
  @param bad_levels: Level(s) at which the parameters are forbidden (e.g.
      "instance")
  @type good_levels: strings
  @param good_levels: Level(s) at which the parameters are allowed (e.g.
      "cluster or group")

  """
  used_globals = glob_pars.intersection(params)
  if used_globals:
    msg = ("The following %s parameters are global and cannot"
           " be customized at %s level, please modify them at"
           " %s level: %s" %
           (kind, bad_levels, good_levels, utils.CommaJoin(used_globals)))
    raise errors.OpPrereqError(msg, errors.ECODE_INVAL)


def IsExclusiveStorageEnabledNode(cfg, node):
  """Whether exclusive_storage is in effect for the given node.

  @type cfg: L{config.ConfigWriter}
  @param cfg: The cluster configuration
  @type node: L{objects.Node}
  @param node: The node
  @rtype: bool
  @return: The effective value of exclusive_storage

  """
  return cfg.GetNdParams(node)[constants.ND_EXCLUSIVE_STORAGE]


def CheckInstanceState(lu, instance, req_states, msg=None):
  """Ensure that an instance is in one of the required states.

  @param lu: the LU on behalf of which we make the check
  @param instance: the instance to check
  @param msg: if passed, should be a message to replace the default one
  @raise errors.OpPrereqError: if the instance is not in the required state

  """
  if msg is None:
    msg = ("can't use instance from outside %s states" %
           utils.CommaJoin(req_states))
  if instance.admin_state not in req_states:
    raise errors.OpPrereqError("Instance '%s' is marked to be %s, %s" %
                               (instance.name, instance.admin_state, msg),
                               errors.ECODE_STATE)

  if constants.ADMINST_UP not in req_states:
    pnode_uuid = instance.primary_node
    if not lu.cfg.GetNodeInfo(pnode_uuid).offline:
      all_hvparams = lu.cfg.GetClusterInfo().hvparams
      ins_l = lu.rpc.call_instance_list(
                [pnode_uuid], [instance.hypervisor], all_hvparams)[pnode_uuid]
      ins_l.Raise("Can't contact node %s for instance information" %
                  lu.cfg.GetNodeName(pnode_uuid),
                  prereq=True, ecode=errors.ECODE_ENVIRON)
      if instance.name in ins_l.payload:
        raise errors.OpPrereqError("Instance %s is running, %s" %
                                   (instance.name, msg), errors.ECODE_STATE)
    else:
      lu.LogWarning("Primary node offline, ignoring check that instance"
                     " is down")


def CheckIAllocatorOrNode(lu, iallocator_slot, node_slot):
  """Check the sanity of iallocator and node arguments and use the
  cluster-wide iallocator if appropriate.

  Check that at most one of (iallocator, node) is specified. If none is
  specified, or the iallocator is L{constants.DEFAULT_IALLOCATOR_SHORTCUT},
  then the LU's opcode's iallocator slot is filled with the cluster-wide
  default iallocator.

  @type iallocator_slot: string
  @param iallocator_slot: the name of the opcode iallocator slot
  @type node_slot: string
  @param node_slot: the name of the opcode target node slot

  """
  node = getattr(lu.op, node_slot, None)
  ialloc = getattr(lu.op, iallocator_slot, None)
  if node == []:
    node = None

  if node is not None and ialloc is not None:
    raise errors.OpPrereqError("Do not specify both, iallocator and node",
                               errors.ECODE_INVAL)
  elif ((node is None and ialloc is None) or
        ialloc == constants.DEFAULT_IALLOCATOR_SHORTCUT):
    default_iallocator = lu.cfg.GetDefaultIAllocator()
    if default_iallocator:
      setattr(lu.op, iallocator_slot, default_iallocator)
    else:
      raise errors.OpPrereqError("No iallocator or node given and no"
                                 " cluster-wide default iallocator found;"
                                 " please specify either an iallocator or a"
                                 " node, or set a cluster-wide default"
                                 " iallocator", errors.ECODE_INVAL)


def FindFaultyInstanceDisks(cfg, rpc_runner, instance, node_uuid, prereq):
  faulty = []

  result = rpc_runner.call_blockdev_getmirrorstatus(
             node_uuid, (instance.disks, instance))
  result.Raise("Failed to get disk status from node %s" %
               cfg.GetNodeName(node_uuid),
               prereq=prereq, ecode=errors.ECODE_ENVIRON)

  for idx, bdev_status in enumerate(result.payload):
    if bdev_status and bdev_status.ldisk_status == constants.LDS_FAULTY:
      faulty.append(idx)

  return faulty


def CheckNodeOnline(lu, node_uuid, msg=None):
  """Ensure that a given node is online.

  @param lu: the LU on behalf of which we make the check
  @param node_uuid: the node to check
  @param msg: if passed, should be a message to replace the default one
  @raise errors.OpPrereqError: if the node is offline

  """
  if msg is None:
    msg = "Can't use offline node"
  if lu.cfg.GetNodeInfo(node_uuid).offline:
    raise errors.OpPrereqError("%s: %s" % (msg, lu.cfg.GetNodeName(node_uuid)),
                               errors.ECODE_STATE)


def CheckDiskTemplateEnabled(cluster, disk_template):
  """Helper function to check if a disk template is enabled.

  @type cluster: C{objects.Cluster}
  @param cluster: the cluster's configuration
  @type disk_template: str
  @param disk_template: the disk template to be checked

  """
  assert disk_template is not None
  if disk_template not in constants.DISK_TEMPLATES:
    raise errors.OpPrereqError("'%s' is not a valid disk template."
                               " Valid disk templates are: %s" %
                               (disk_template,
                                ",".join(constants.DISK_TEMPLATES)))
  if not disk_template in cluster.enabled_disk_templates:
    raise errors.OpPrereqError("Disk template '%s' is not enabled in cluster."
                               " Enabled disk templates are: %s" %
                               (disk_template,
                                ",".join(cluster.enabled_disk_templates)))


def CheckStorageTypeEnabled(cluster, storage_type):
  """Helper function to check if a storage type is enabled.

  @type cluster: C{objects.Cluster}
  @param cluster: the cluster's configuration
  @type storage_type: str
  @param storage_type: the storage type to be checked

  """
  assert storage_type is not None
  assert storage_type in constants.STORAGE_TYPES
  # special case for lvm-pv, because it cannot be enabled
  # via disk templates
  if storage_type == constants.ST_LVM_PV:
    CheckStorageTypeEnabled(cluster, constants.ST_LVM_VG)
  else:
    possible_disk_templates = \
        utils.storage.GetDiskTemplatesOfStorageType(storage_type)
    for disk_template in possible_disk_templates:
      if disk_template in cluster.enabled_disk_templates:
        return
    raise errors.OpPrereqError("No disk template of storage type '%s' is"
                               " enabled in this cluster. Enabled disk"
                               " templates are: %s" % (storage_type,
                               ",".join(cluster.enabled_disk_templates)))


def CheckIpolicyVsDiskTemplates(ipolicy, enabled_disk_templates):
  """Checks ipolicy disk templates against enabled disk tempaltes.

  @type ipolicy: dict
  @param ipolicy: the new ipolicy
  @type enabled_disk_templates: list of string
  @param enabled_disk_templates: list of enabled disk templates on the
    cluster
  @raises errors.OpPrereqError: if there is at least one allowed disk
    template that is not also enabled.

  """
  assert constants.IPOLICY_DTS in ipolicy
  allowed_disk_templates = ipolicy[constants.IPOLICY_DTS]
  not_enabled = set(allowed_disk_templates) - set(enabled_disk_templates)
  if not_enabled:
    raise errors.OpPrereqError("The following disk template are allowed"
                               " by the ipolicy, but not enabled on the"
                               " cluster: %s" % utils.CommaJoin(not_enabled))


def CheckDiskAccessModeValidity(parameters):
  """Checks if the access parameter is legal.

  @see: L{CheckDiskAccessModeConsistency} for cluster consistency checks.
  @raise errors.OpPrereqError: if the check fails.

  """
  for disk_template in parameters:
    access = parameters[disk_template].get(constants.LDP_ACCESS,
                                           constants.DISK_KERNELSPACE)
    if access not in constants.DISK_VALID_ACCESS_MODES:
      valid_vals_str = utils.CommaJoin(constants.DISK_VALID_ACCESS_MODES)
      raise errors.OpPrereqError("Invalid value of '{d}:{a}': '{v}' (expected"
                                 " one of {o})".format(d=disk_template,
                                                       a=constants.LDP_ACCESS,
                                                       v=access,
                                                       o=valid_vals_str))


def CheckDiskAccessModeConsistency(parameters, cfg, group=None):
  """Checks if the access param is consistent with the cluster configuration.

  @note: requires a configuration lock to run.
  @param parameters: the parameters to validate
  @param cfg: the cfg object of the cluster
  @param group: if set, only check for consistency within this group.
  @raise errors.OpPrereqError: if the LU attempts to change the access parameter
                               to an invalid value, such as "pink bunny".
  @raise errors.OpPrereqError: if the LU attempts to change the access parameter
                               to an inconsistent value, such as asking for RBD
                               userspace access to the chroot hypervisor.

  """
  CheckDiskAccessModeValidity(parameters)

  for disk_template in parameters:
    access = parameters[disk_template].get(constants.LDP_ACCESS,
                                           constants.DISK_KERNELSPACE)

    if dt not in constants.DTS_HAVE_ACCESS
      continue

    #Check the combination of instance hypervisor, disk template and access
    #protocol is sane.
    inst_uuids = cfg.GetNodeGroupInstances(group) if group else \
                 cfg.GetInstanceList()

    for entry in inst_uuids:
      inst = cfg.GetInstanceInfo(entry)
      hv = inst.hypervisor
      dt = inst.disk_template

      if not IsValidDiskAccessModeCombination(hv, dt, access):
        raise errors.OpPrereqError("Instance {i}: cannot use '{a}' access"
                                   " setting with {h} hypervisor and {d} disk"
                                   " type.".format(i=inst.name,
                                                   a=access,
                                                   h=hv,
                                                   d=dt))


def IsValidDiskAccessModeCombination(hv, disk_template, mode):
  """Checks if an hypervisor can read a disk template with given mode.

  @param hv: the hypervisor that will access the data
  @param disk_template: the disk template the data is stored as
  @param mode: how the hypervisor should access the data
  @return: True if the hypervisor can read a given read disk_template
           in the specified mode.

  """
  if mode == constants.DISK_KERNELSPACE:
    return True

  if (hv == constants.HT_KVM and
      disk_template in (constants.DT_RBD, constants.DT_GLUSTER) and
      mode == constants.DISK_USERSPACE):
    return True

  # Everything else:
  return False
