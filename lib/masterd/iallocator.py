#
#

# Copyright (C) 2012, 2013 Google Inc.
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


"""Module implementing the iallocator code."""

import logging

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import ht
from ganeti import outils
from ganeti import opcodes
from ganeti import serializer
from ganeti import utils

import ganeti.rpc.node as rpc
import ganeti.masterd.instance as gmi

_STRING_LIST = ht.TListOf(ht.TString)
_JOB_LIST = ht.TListOf(ht.TListOf(ht.TStrictDict(True, False, {
   # pylint: disable=E1101
   # Class '...' has no 'OP_ID' member
   "OP_ID": ht.TElemOf([opcodes.OpInstanceFailover.OP_ID,
                        opcodes.OpInstanceMigrate.OP_ID,
                        opcodes.OpInstanceReplaceDisks.OP_ID]),
   })))

_NEVAC_MOVED = \
  ht.TListOf(ht.TAnd(ht.TIsLength(3),
                     ht.TItems([ht.TNonEmptyString,
                                ht.TNonEmptyString,
                                ht.TListOf(ht.TNonEmptyString),
                                ])))
_NEVAC_FAILED = \
  ht.TListOf(ht.TAnd(ht.TIsLength(2),
                     ht.TItems([ht.TNonEmptyString,
                                ht.TMaybeString,
                                ])))
_NEVAC_RESULT = ht.TAnd(ht.TIsLength(3),
                        ht.TItems([_NEVAC_MOVED, _NEVAC_FAILED, _JOB_LIST]))

_INST_NAME = ("name", ht.TNonEmptyString)
_INST_UUID = ("inst_uuid", ht.TNonEmptyString)


class _AutoReqParam(outils.AutoSlots):
  """Meta class for request definitions.

  """
  @classmethod
  def _GetSlots(mcs, attrs):
    """Extract the slots out of REQ_PARAMS.

    """
    params = attrs.setdefault("REQ_PARAMS", [])
    return [slot for (slot, _) in params]


class IARequestBase(outils.ValidatedSlots, metaclass=_AutoReqParam):
  """A generic IAllocator request object.

  """

  MODE = NotImplemented
  REQ_PARAMS = []
  REQ_RESULT = NotImplemented

  def __init__(self, **kwargs):
    """Constructor for IARequestBase.

    The constructor takes only keyword arguments and will set
    attributes on this object based on the passed arguments. As such,
    it means that you should not pass arguments which are not in the
    REQ_PARAMS attribute for this class.

    """
    outils.ValidatedSlots.__init__(self, **kwargs)

    self.Validate()

  def Validate(self):
    """Validates all parameters of the request.


    This method returns L{None} if the validation succeeds, or raises
    an exception otherwise.

    @rtype: NoneType
    @return: L{None}, if the validation succeeds

    @raise Exception: validation fails

    """
    assert self.MODE in constants.VALID_IALLOCATOR_MODES

    for (param, validator) in self.REQ_PARAMS:
      if not hasattr(self, param):
        raise errors.OpPrereqError("Request is missing '%s' parameter" % param,
                                   errors.ECODE_INVAL)

      value = getattr(self, param)
      if not validator(value):
        raise errors.OpPrereqError(("Request parameter '%s' has invalid"
                                    " type %s/value %s") %
                                    (param, type(value), value),
                                    errors.ECODE_INVAL)

  def GetRequest(self, cfg):
    """Gets the request data dict.

    @param cfg: The configuration instance

    """
    raise NotImplementedError

  def GetExtraParams(self): # pylint: disable=R0201
    """Gets extra parameters to the IAllocator call.

    """
    return {}

  def ValidateResult(self, ia, result):
    """Validates the result of an request.

    @param ia: The IAllocator instance
    @param result: The IAllocator run result
    @raises ResultValidationError: If validation fails

    """
    if ia.success and not self.REQ_RESULT(result): # pylint: disable=E1102
      raise errors.ResultValidationError("iallocator returned invalid result,"
                                         " expected %s, got %s" %
                                         (self.REQ_RESULT, result))


class IAReqInstanceAlloc(IARequestBase):
  """An instance allocation request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_ALLOC
  REQ_PARAMS = [
    _INST_NAME,
    ("memory", ht.TNonNegativeInt),
    ("spindle_use", ht.TNonNegativeInt),
    ("disks", ht.TListOf(ht.TDict)),
    ("disk_template", ht.TString),
    ("group_name", ht.TMaybe(ht.TNonEmptyString)),
    ("os", ht.TString),
    ("tags", _STRING_LIST),
    ("nics", ht.TListOf(ht.TDict)),
    ("vcpus", ht.TInt),
    ("hypervisor", ht.TString),
    ("node_whitelist", ht.TMaybeListOf(ht.TNonEmptyString)),
    ]
  REQ_RESULT = ht.TList

  def RequiredNodes(self):
    """Calculates the required nodes based on the disk_template.

    """
    if self.disk_template in constants.DTS_INT_MIRROR:
      return 2
    else:
      return 1

  def GetRequest(self, cfg):
    """Requests a new instance.

    The checks for the completeness of the opcode must have already been
    done.

    """
    for d in self.disks:
      d[constants.IDISK_TYPE] = self.disk_template
    disk_space = gmi.ComputeDiskSize(self.disks)

    return {
      "name": self.name,
      "disk_template": self.disk_template,
      "group_name": self.group_name,
      "tags": self.tags,
      "os": self.os,
      "vcpus": self.vcpus,
      "memory": self.memory,
      "spindle_use": self.spindle_use,
      "disks": self.disks,
      "disk_space_total": disk_space,
      "nics": self.nics,
      "required_nodes": self.RequiredNodes(),
      "hypervisor": self.hypervisor,
      }

  def ValidateResult(self, ia, result):
    """Validates an single instance allocation request.

    """
    IARequestBase.ValidateResult(self, ia, result)

    if ia.success and len(result) != self.RequiredNodes():
      raise errors.ResultValidationError("iallocator returned invalid number"
                                         " of nodes (%s), required %s" %
                                         (len(result), self.RequiredNodes()))


class IAReqInstanceAllocateSecondary(IARequestBase):
  """Request to find a secondary node for plain to DRBD conversion.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_ALLOCATE_SECONDARY
  REQ_PARAMS = [
    _INST_NAME,
    ]
  REQ_RESULT = ht.TString

  def GetRequest(self, cfg):
    return {
      "name": self.name
    }


class IAReqMultiInstanceAlloc(IARequestBase):
  """An multi instance allocation request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_MULTI_ALLOC
  REQ_PARAMS = [
    ("instances", ht.TListOf(ht.TInstanceOf(IAReqInstanceAlloc))),
    ]
  _MASUCCESS = \
    ht.TListOf(ht.TAnd(ht.TIsLength(2),
                       ht.TItems([ht.TNonEmptyString,
                                  ht.TListOf(ht.TNonEmptyString),
                                  ])))
  _MAFAILED = ht.TListOf(ht.TNonEmptyString)
  REQ_RESULT = ht.TAnd(ht.TList, ht.TIsLength(2),
                       ht.TItems([_MASUCCESS, _MAFAILED]))

  def GetRequest(self, cfg):
    return {
      "instances": [iareq.GetRequest(cfg) for iareq in self.instances],
      }


class IAReqRelocate(IARequestBase):
  """A relocation request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_RELOC
  REQ_PARAMS = [
    _INST_UUID,
    ("relocate_from_node_uuids", _STRING_LIST),
    ]
  REQ_RESULT = ht.TList

  def GetRequest(self, cfg):
    """Request an relocation of an instance

    The checks for the completeness of the opcode must have already been
    done.

    """
    instance = cfg.GetInstanceInfo(self.inst_uuid)
    disks = cfg.GetInstanceDisks(self.inst_uuid)
    if instance is None:
      raise errors.ProgrammerError("Unknown instance '%s' passed to"
                                   " IAllocator" % self.inst_uuid)

    if not utils.AllDiskOfType(disks, constants.DTS_MIRRORED):
      raise errors.OpPrereqError("Can't relocate non-mirrored instances",
                                 errors.ECODE_INVAL)

    secondary_nodes = cfg.GetInstanceSecondaryNodes(instance.uuid)
    if (utils.AnyDiskOfType(disks, constants.DTS_INT_MIRROR) and
        len(secondary_nodes) != 1):
      raise errors.OpPrereqError("Instance has not exactly one secondary node",
                                 errors.ECODE_STATE)

    disk_sizes = [{constants.IDISK_SIZE: disk.size,
                   constants.IDISK_TYPE: disk.dev_type} for disk in disks]
    disk_space = gmi.ComputeDiskSize(disk_sizes)

    return {
      "name": instance.name,
      "disk_space_total": disk_space,
      "required_nodes": 1,
      "relocate_from": cfg.GetNodeNames(self.relocate_from_node_uuids),
      }

  def ValidateResult(self, ia, result):
    """Validates the result of an relocation request.

    """
    IARequestBase.ValidateResult(self, ia, result)

    node2group = dict((name, ndata["group"])
                      for (name, ndata) in ia.in_data["nodes"].items())

    fn = compat.partial(self._NodesToGroups, node2group,
                        ia.in_data["nodegroups"])

    instance = ia.cfg.GetInstanceInfo(self.inst_uuid)
    request_groups = fn(ia.cfg.GetNodeNames(self.relocate_from_node_uuids) +
                        ia.cfg.GetNodeNames([instance.primary_node]))
    result_groups = fn(result + ia.cfg.GetNodeNames([instance.primary_node]))

    if ia.success and not set(result_groups).issubset(request_groups):
      raise errors.ResultValidationError("Groups of nodes returned by"
                                         " iallocator (%s) differ from original"
                                         " groups (%s)" %
                                         (utils.CommaJoin(result_groups),
                                          utils.CommaJoin(request_groups)))

  @staticmethod
  def _NodesToGroups(node2group, groups, nodes):
    """Returns a list of unique group names for a list of nodes.

    @type node2group: dict
    @param node2group: Map from node name to group UUID
    @type groups: dict
    @param groups: Group information
    @type nodes: list
    @param nodes: Node names

    """
    result = set()

    for node in nodes:
      try:
        group_uuid = node2group[node]
      except KeyError:
        # Ignore unknown node
        pass
      else:
        try:
          group = groups[group_uuid]
        except KeyError:
          # Can't find group, let's use UUID
          group_name = group_uuid
        else:
          group_name = group["name"]

        result.add(group_name)

    return sorted(result)


class IAReqNodeEvac(IARequestBase):
  """A node evacuation request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_NODE_EVAC
  REQ_PARAMS = [
    ("instances", _STRING_LIST),
    ("evac_mode", ht.TEvacMode),
    ("ignore_soft_errors", ht.TMaybe(ht.TBool)),
    ]
  REQ_RESULT = _NEVAC_RESULT

  def GetRequest(self, cfg):
    """Get data for node-evacuate requests.

    """
    return {
      "instances": self.instances,
      "evac_mode": self.evac_mode,
      }

  def GetExtraParams(self):
    """Get extra iallocator command line options for
    node-evacuate requests.

    """
    if self.ignore_soft_errors:
      return {"ignore-soft-errors": None}
    else:
      return {}


class IAReqGroupChange(IARequestBase):
  """A group change request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_CHG_GROUP
  REQ_PARAMS = [
    ("instances", _STRING_LIST),
    ("target_groups", _STRING_LIST),
    ]
  REQ_RESULT = _NEVAC_RESULT

  def GetRequest(self, cfg):
    """Get data for node-evacuate requests.

    """
    return {
      "instances": self.instances,
      "target_groups": self.target_groups,
      }


class IAllocator(object):
  """IAllocator framework.

  An IAllocator instance has three sets of attributes:
    - cfg that is needed to query the cluster
    - input data (all members of the _KEYS class attribute are required)
    - four buffer attributes (in|out_data|text), that represent the
      input (to the external script) in text and data structure format,
      and the output from it, again in two formats
    - the result variables from the script (success, info, nodes) for
      easy usage

  """
  # pylint: disable=R0902
  # lots of instance attributes

  def __init__(self, cfg, rpc_runner, req):
    self.cfg = cfg
    self.rpc = rpc_runner
    self.req = req
    # init buffer variables
    self.in_text = self.out_text = self.in_data = self.out_data = None
    # init result fields
    self.success = self.info = self.result = None

    self._BuildInputData(req)

  def _ComputeClusterDataNodeInfo(self, disk_templates, node_list,
                                  cluster_info, hypervisor_name):
    """Prepare and execute node info call.

    @type disk_templates: list of string
    @param disk_templates: the disk templates of the instances to be allocated
    @type node_list: list of strings
    @param node_list: list of nodes' UUIDs
    @type cluster_info: L{objects.Cluster}
    @param cluster_info: the cluster's information from the config
    @type hypervisor_name: string
    @param hypervisor_name: the hypervisor name
    @rtype: same as the result of the node info RPC call
    @return: the result of the node info RPC call

    """
    storage_units_raw = utils.storage.GetStorageUnits(self.cfg, disk_templates)
    storage_units = rpc.PrepareStorageUnitsForNodes(self.cfg, storage_units_raw,
                                                    node_list)
    hvspecs = [(hypervisor_name, cluster_info.hvparams[hypervisor_name])]
    return self.rpc.call_node_info(node_list, storage_units, hvspecs)

  def _ComputeClusterData(self, disk_template=None):
    """Compute the generic allocator input data.

    @type disk_template: list of string
    @param disk_template: the disk templates of the instances to be allocated

    """
    cfg = self.cfg.GetDetachedConfig()
    cluster_info = cfg.GetClusterInfo()
    # cluster data
    data = {
      "version": constants.IALLOCATOR_VERSION,
      "cluster_name": cluster_info.cluster_name,
      "cluster_tags": list(cluster_info.GetTags()),
      "enabled_hypervisors": list(cluster_info.enabled_hypervisors),
      "ipolicy": cluster_info.ipolicy,
      }
    ginfo = cfg.GetAllNodeGroupsInfo()
    ninfo = cfg.GetAllNodesInfo()
    iinfo = cfg.GetAllInstancesInfo()
    i_list = [(inst, cluster_info.FillBE(inst)) for inst in iinfo.values()]

    # node data
    node_list = [n.uuid for n in ninfo.values() if n.vm_capable]

    if isinstance(self.req, IAReqInstanceAlloc):
      hypervisor_name = self.req.hypervisor
    elif isinstance(self.req, IAReqRelocate):
      hypervisor_name = iinfo[self.req.inst_uuid].hypervisor
    else:
      hypervisor_name = cluster_info.primary_hypervisor

    if not disk_template:
      disk_template = cluster_info.enabled_disk_templates[0]

    node_data = self._ComputeClusterDataNodeInfo([disk_template], node_list,
                                                 cluster_info, hypervisor_name)

    node_iinfo = \
      self.rpc.call_all_instances_info(node_list,
                                       cluster_info.enabled_hypervisors,
                                       cluster_info.hvparams)

    data["nodegroups"] = self._ComputeNodeGroupData(cluster_info, ginfo)

    config_ndata = self._ComputeBasicNodeData(cfg, ninfo)
    data["nodes"] = self._ComputeDynamicNodeData(
        ninfo, node_data, node_iinfo, i_list, config_ndata, disk_template)
    assert len(data["nodes"]) == len(ninfo), \
        "Incomplete node data computed"

    data["instances"] = self._ComputeInstanceData(cfg, cluster_info, i_list)

    self.in_data = data

  @staticmethod
  def _ComputeNodeGroupData(cluster, ginfo):
    """Compute node groups data.

    """
    ng = dict((guuid, {
      "name": gdata.name,
      "alloc_policy": gdata.alloc_policy,
      "networks": list(gdata.networks),
      "ipolicy": gmi.CalculateGroupIPolicy(cluster, gdata),
      "tags": list(gdata.GetTags()),
      })
      for guuid, gdata in ginfo.items())

    return ng

  @staticmethod
  def _ComputeBasicNodeData(cfg, node_cfg):
    """Compute global node data.

    @rtype: dict
    @returns: a dict of name: (node dict, node config)

    """
    # fill in static (config-based) values
    node_results = dict((ninfo.name, {
      "tags": list(ninfo.GetTags()),
      "primary_ip": ninfo.primary_ip,
      "secondary_ip": ninfo.secondary_ip,
      "offline": ninfo.offline,
      "drained": ninfo.drained,
      "master_candidate": ninfo.master_candidate,
      "group": ninfo.group,
      "master_capable": ninfo.master_capable,
      "vm_capable": ninfo.vm_capable,
      "ndparams": cfg.GetNdParams(ninfo),
      })
      for ninfo in node_cfg.values())

    return node_results

  @staticmethod
  def _GetAttributeFromHypervisorNodeData(hv_info, node_name, attr):
    """Extract an attribute from the hypervisor's node information.

    This is a helper function to extract data from the hypervisor's information
    about the node, as part of the result of a node_info query.

    @type hv_info: dict of strings
    @param hv_info: dictionary of node information from the hypervisor
    @type node_name: string
    @param node_name: name of the node
    @type attr: string
    @param attr: key of the attribute in the hv_info dictionary
    @rtype: integer
    @return: the value of the attribute
    @raises errors.OpExecError: if key not in dictionary or value not
      integer

    """
    if attr not in hv_info:
      raise errors.OpExecError("Node '%s' didn't return attribute"
                               " '%s'" % (node_name, attr))
    value = hv_info[attr]
    if not isinstance(value, int):
      raise errors.OpExecError("Node '%s' returned invalid value"
                               " for '%s': %s" %
                               (node_name, attr, value))
    return value

  @staticmethod
  def _ComputeStorageDataFromSpaceInfoByTemplate(
      space_info, node_name, disk_template):
    """Extract storage data from node info.

    @type space_info: see result of the RPC call node info
    @param space_info: the storage reporting part of the result of the RPC call
      node info
    @type node_name: string
    @param node_name: the node's name
    @type disk_template: string
    @param disk_template: the disk template to report space for
    @rtype: 4-tuple of integers
    @return: tuple of storage info (total_disk, free_disk, total_spindles,
       free_spindles)

    """
    storage_type = constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template]
    if storage_type not in constants.STS_REPORT:
      total_disk = total_spindles = 0
      free_disk = free_spindles = 0
    else:
      template_space_info = utils.storage.LookupSpaceInfoByDiskTemplate(
          space_info, disk_template)
      if not template_space_info:
        raise errors.OpExecError("Node '%s' didn't return space info for disk"
                                   "template '%s'" % (node_name, disk_template))
      total_disk = template_space_info["storage_size"]
      free_disk = template_space_info["storage_free"]

      total_spindles = 0
      free_spindles = 0
      if disk_template in constants.DTS_LVM:
        lvm_pv_info = utils.storage.LookupSpaceInfoByStorageType(
           space_info, constants.ST_LVM_PV)
        if lvm_pv_info:
          total_spindles = lvm_pv_info["storage_size"]
          free_spindles = lvm_pv_info["storage_free"]
    return (total_disk, free_disk, total_spindles, free_spindles)

  @staticmethod
  def _ComputeStorageDataFromSpaceInfo(space_info, node_name, has_lvm):
    """Extract storage data from node info.

    @type space_info: see result of the RPC call node info
    @param space_info: the storage reporting part of the result of the RPC call
      node info
    @type node_name: string
    @param node_name: the node's name
    @type has_lvm: boolean
    @param has_lvm: whether or not LVM storage information is requested
    @rtype: 4-tuple of integers
    @return: tuple of storage info (total_disk, free_disk, total_spindles,
       free_spindles)

    """
    # TODO: replace this with proper storage reporting
    if has_lvm:
      lvm_vg_info = utils.storage.LookupSpaceInfoByStorageType(
         space_info, constants.ST_LVM_VG)
      if not lvm_vg_info:
        raise errors.OpExecError("Node '%s' didn't return LVM vg space info."
                                 % (node_name))
      total_disk = lvm_vg_info["storage_size"]
      free_disk = lvm_vg_info["storage_free"]
      lvm_pv_info = utils.storage.LookupSpaceInfoByStorageType(
         space_info, constants.ST_LVM_PV)
      if not lvm_pv_info:
        raise errors.OpExecError("Node '%s' didn't return LVM pv space info."
                                 % (node_name))
      total_spindles = lvm_pv_info["storage_size"]
      free_spindles = lvm_pv_info["storage_free"]
    else:
      # we didn't even ask the node for VG status, so use zeros
      total_disk = free_disk = 0
      total_spindles = free_spindles = 0
    return (total_disk, free_disk, total_spindles, free_spindles)

  @staticmethod
  def _ComputeInstanceMemory(instance_list, node_instances_info, node_uuid,
                             input_mem_free):
    """Compute memory used by primary instances.

    @rtype: tuple (int, int, int)
    @returns: A tuple of three integers: 1. the sum of memory used by primary
      instances on the node (including the ones that are currently down), 2.
      the sum of memory used by primary instances of the node that are up, 3.
      the amount of memory that is free on the node considering the current
      usage of the instances.

    """
    i_p_mem = i_p_up_mem = 0
    mem_free = input_mem_free
    for iinfo, beinfo in instance_list:
      if iinfo.primary_node == node_uuid:
        i_p_mem += beinfo[constants.BE_MAXMEM]
        if iinfo.name not in node_instances_info[node_uuid].payload:
          i_used_mem = 0
        else:
          i_used_mem = int(node_instances_info[node_uuid]
                           .payload[iinfo.name]["memory"])
        i_mem_diff = beinfo[constants.BE_MAXMEM] - i_used_mem
        if iinfo.admin_state == constants.ADMINST_UP \
            and not iinfo.forthcoming:
          mem_free -= max(0, i_mem_diff)
          i_p_up_mem += beinfo[constants.BE_MAXMEM]
    return (i_p_mem, i_p_up_mem, mem_free)

  def _ComputeDynamicNodeData(self, node_cfg, node_data, node_iinfo, i_list,
                              node_results, disk_template):
    """Compute global node data.

    @param node_results: the basic node structures as filled from the config

    """
    #TODO(dynmem): compute the right data on MAX and MIN memory
    # make a copy of the current dict
    node_results = dict(node_results)
    for nuuid, nresult in node_data.items():
      ninfo = node_cfg[nuuid]
      assert ninfo.name in node_results, "Missing basic data for node %s" % \
                                         ninfo.name

      if not ninfo.offline:
        nresult.Raise("Can't get data for node %s" % ninfo.name)
        node_iinfo[nuuid].Raise("Can't get node instance info from node %s" %
                                ninfo.name)
        (_, space_info, (hv_info, )) = nresult.payload

        mem_free = self._GetAttributeFromHypervisorNodeData(hv_info, ninfo.name,
                                                            "memory_free")

        (i_p_mem, i_p_up_mem, mem_free) = self._ComputeInstanceMemory(
             i_list, node_iinfo, nuuid, mem_free)
        (total_disk, free_disk, total_spindles, free_spindles) = \
            self._ComputeStorageDataFromSpaceInfoByTemplate(
                space_info, ninfo.name, disk_template)

        # compute memory used by instances
        pnr_dyn = {
          "total_memory": self._GetAttributeFromHypervisorNodeData(
              hv_info, ninfo.name, "memory_total"),
          "reserved_memory": self._GetAttributeFromHypervisorNodeData(
              hv_info, ninfo.name, "memory_dom0"),
          "free_memory": mem_free,
          "total_disk": total_disk,
          "free_disk": free_disk,
          "total_spindles": total_spindles,
          "free_spindles": free_spindles,
          "total_cpus": self._GetAttributeFromHypervisorNodeData(
              hv_info, ninfo.name, "cpu_total"),
          "reserved_cpus": self._GetAttributeFromHypervisorNodeData(
            hv_info, ninfo.name, "cpu_dom0"),
          "i_pri_memory": i_p_mem,
          "i_pri_up_memory": i_p_up_mem,
          }
        pnr_dyn.update(node_results[ninfo.name])
        node_results[ninfo.name] = pnr_dyn

    return node_results

  @staticmethod
  def _ComputeInstanceData(cfg, cluster_info, i_list):
    """Compute global instance data.

    """
    instance_data = {}
    for iinfo, beinfo in i_list:
      nic_data = []
      for nic in iinfo.nics:
        filled_params = cluster_info.SimpleFillNIC(nic.nicparams)
        nic_dict = {
          "mac": nic.mac,
          "ip": nic.ip,
          "mode": filled_params[constants.NIC_MODE],
          "link": filled_params[constants.NIC_LINK],
          }
        if filled_params[constants.NIC_MODE] == constants.NIC_MODE_BRIDGED:
          nic_dict["bridge"] = filled_params[constants.NIC_LINK]
        nic_data.append(nic_dict)
      inst_disks = cfg.GetInstanceDisks(iinfo.uuid)
      inst_disktemplate = cfg.GetInstanceDiskTemplate(iinfo.uuid)
      pir = {
        "tags": list(iinfo.GetTags()),
        "admin_state": iinfo.admin_state,
        "vcpus": beinfo[constants.BE_VCPUS],
        "memory": beinfo[constants.BE_MAXMEM],
        "spindle_use": beinfo[constants.BE_SPINDLE_USE],
        "os": iinfo.os,
        "nodes": [cfg.GetNodeName(iinfo.primary_node)] +
                 cfg.GetNodeNames(
                   cfg.GetInstanceSecondaryNodes(iinfo.uuid)),
        "nics": nic_data,
        "disks": [{constants.IDISK_TYPE: dsk.dev_type,
                   constants.IDISK_SIZE: dsk.size,
                   constants.IDISK_MODE: dsk.mode,
                   constants.IDISK_SPINDLES: dsk.spindles}
                  for dsk in inst_disks],
        "disk_template": inst_disktemplate,
        "disks_active": iinfo.disks_active,
        "hypervisor": iinfo.hypervisor,
        }
      pir["disk_space_total"] = gmi.ComputeDiskSize(pir["disks"])
      instance_data[iinfo.name] = pir

    return instance_data

  def _BuildInputData(self, req):
    """Build input data structures.

    """
    request = req.GetRequest(self.cfg)
    disk_template = None
    if request.get("disk_template") is not None:
      disk_template = request["disk_template"]
    elif isinstance(req, IAReqRelocate):
      disk_template = self.cfg.GetInstanceDiskTemplate(self.req.inst_uuid)
    self._ComputeClusterData(disk_template=disk_template)

    request["type"] = req.MODE

    if isinstance(self.req, IAReqInstanceAlloc):
      node_whitelist = self.req.node_whitelist
    else:
      node_whitelist = None
    if node_whitelist is not None:
      request["restrict-to-nodes"] = node_whitelist

    self.in_data["request"] = request

    self.in_text = serializer.Dump(self.in_data)
    logging.debug("IAllocator request: %s", self.in_text)

  def Run(self, name, validate=True, call_fn=None):
    """Run an instance allocator and return the results.

    """
    if call_fn is None:
      call_fn = self.rpc.call_iallocator_runner

    ial_params = self.cfg.GetDefaultIAllocatorParameters()

    for ial_param in self.req.GetExtraParams().items():
      ial_params[ial_param[0]] = ial_param[1]

    result = call_fn(self.cfg.GetMasterNode(), name, self.in_text, ial_params)
    result.Raise("Failure while running the iallocator script")

    self.out_text = result.payload
    if validate:
      self._ValidateResult()

  def _ValidateResult(self):
    """Process the allocator results.

    This will process and if successful save the result in
    self.out_data and the other parameters.

    """
    try:
      rdict = serializer.Load(self.out_text)
    except Exception as err:
      raise errors.OpExecError("Can't parse iallocator results: %s" % str(err))

    if not isinstance(rdict, dict):
      raise errors.OpExecError("Can't parse iallocator results: not a dict")

    # TODO: remove backwards compatiblity in later versions
    if "nodes" in rdict and "result" not in rdict:
      rdict["result"] = rdict["nodes"]
      del rdict["nodes"]

    for key in "success", "info", "result":
      if key not in rdict:
        raise errors.OpExecError("Can't parse iallocator results:"
                                 " missing key '%s'" % key)
      setattr(self, key, rdict[key])

    self.req.ValidateResult(self, self.result)
    self.out_data = rdict
