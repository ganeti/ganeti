#
#

# Copyright (C) 2012 Google Inc.
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


"""Module implementing the iallocator code."""

from ganeti import compat
from ganeti import constants
from ganeti import errors
from ganeti import ht
from ganeti import objectutils
from ganeti import opcodes
from ganeti import rpc
from ganeti import serializer
from ganeti import utils

import ganeti.masterd.instance as gmi


_STRING_LIST = ht.TListOf(ht.TString)
_JOB_LIST = ht.TListOf(ht.TListOf(ht.TStrictDict(True, False, {
   # pylint: disable=E1101
   # Class '...' has no 'OP_ID' member
   "OP_ID": ht.TElemOf([opcodes.OpInstanceFailover.OP_ID,
                        opcodes.OpInstanceMigrate.OP_ID,
                        opcodes.OpInstanceReplaceDisks.OP_ID])
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


class _AutoReqParam(objectutils.AutoSlots):
  """Meta class for request definitions.

  """
  @classmethod
  def _GetSlots(mcs, attrs):
    """Extract the slots out of REQ_PARAMS.

    """
    params = attrs.setdefault("REQ_PARAMS", [])
    return [slot for (slot, _) in params]


class IARequestBase(objectutils.ValidatedSlots):
  """A generic IAllocator request object.

  """
  __metaclass__ = _AutoReqParam

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
    objectutils.ValidatedSlots.__init__(self, **kwargs)

    self.Validate()

  def Validate(self):
    """Validates all parameters of the request.

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

  def ValidateResult(self, ia, result):
    """Validates the result of an request.

    @param ia: The IAllocator instance
    @param result: The IAllocator run result
    @raises ResultValidationError: If validation fails

    """
    if ia.success and not self.REQ_RESULT(result):
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
    ("memory", ht.TPositiveInt),
    ("spindle_use", ht.TPositiveInt),
    ("disks", ht.TListOf(ht.TDict)),
    ("disk_template", ht.TString),
    ("os", ht.TString),
    ("tags", _STRING_LIST),
    ("nics", ht.TListOf(ht.TDict)),
    ("vcpus", ht.TInt),
    ("hypervisor", ht.TString),
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
    disk_space = gmi.ComputeDiskSize(self.disk_template, self.disks)

    return {
      "name": self.name,
      "disk_template": self.disk_template,
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


class IAReqMultiInstanceAlloc(IARequestBase):
  """An multi instance allocation request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_MULTI_ALLOC
  REQ_PARAMS = [
    ("instances", ht.TListOf(ht.TInstanceOf(IAReqInstanceAlloc)))
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
      "instances": [iareq.GetRequest(cfg) for iareq in self.instances]
      }


class IAReqRelocate(IARequestBase):
  """A relocation request.

  """
  # pylint: disable=E1101
  MODE = constants.IALLOCATOR_MODE_RELOC
  REQ_PARAMS = [
    _INST_NAME,
    ("relocate_from", _STRING_LIST),
    ]
  REQ_RESULT = ht.TList

  def GetRequest(self, cfg):
    """Request an relocation of an instance

    The checks for the completeness of the opcode must have already been
    done.

    """
    instance = cfg.GetInstanceInfo(self.name)
    if instance is None:
      raise errors.ProgrammerError("Unknown instance '%s' passed to"
                                   " IAllocator" % self.name)

    if instance.disk_template not in constants.DTS_MIRRORED:
      raise errors.OpPrereqError("Can't relocate non-mirrored instances",
                                 errors.ECODE_INVAL)

    if (instance.disk_template in constants.DTS_INT_MIRROR and
        len(instance.secondary_nodes) != 1):
      raise errors.OpPrereqError("Instance has not exactly one secondary node",
                                 errors.ECODE_STATE)

    disk_sizes = [{constants.IDISK_SIZE: disk.size} for disk in instance.disks]
    disk_space = gmi.ComputeDiskSize(instance.disk_template, disk_sizes)

    return {
      "name": self.name,
      "disk_space_total": disk_space,
      "required_nodes": 1,
      "relocate_from": self.relocate_from,
      }

  def ValidateResult(self, ia, result):
    """Validates the result of an relocation request.

    """
    IARequestBase.ValidateResult(self, ia, result)

    node2group = dict((name, ndata["group"])
                      for (name, ndata) in ia.in_data["nodes"].items())

    fn = compat.partial(self._NodesToGroups, node2group,
                        ia.in_data["nodegroups"])

    instance = ia.cfg.GetInstanceInfo(self.name)
    request_groups = fn(self.relocate_from + [instance.primary_node])
    result_groups = fn(result + [instance.primary_node])

    if ia.success and not set(result_groups).issubset(request_groups):
      raise errors.ResultValidationError("Groups of nodes returned by"
                                         "iallocator (%s) differ from original"
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
    ("evac_mode", ht.TElemOf(constants.IALLOCATOR_NEVAC_MODES)),
    ]
  REQ_RESULT = _NEVAC_RESULT

  def GetRequest(self, cfg):
    """Get data for node-evacuate requests.

    """
    return {
      "instances": self.instances,
      "evac_mode": self.evac_mode,
      }


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

  def _ComputeClusterData(self):
    """Compute the generic allocator input data.

    This is the data that is independent of the actual operation.

    """
    cfg = self.cfg
    cluster_info = cfg.GetClusterInfo()
    # cluster data
    data = {
      "version": constants.IALLOCATOR_VERSION,
      "cluster_name": cfg.GetClusterName(),
      "cluster_tags": list(cluster_info.GetTags()),
      "enabled_hypervisors": list(cluster_info.enabled_hypervisors),
      "ipolicy": cluster_info.ipolicy,
      }
    ninfo = cfg.GetAllNodesInfo()
    iinfo = cfg.GetAllInstancesInfo().values()
    i_list = [(inst, cluster_info.FillBE(inst)) for inst in iinfo]

    # node data
    node_list = [n.name for n in ninfo.values() if n.vm_capable]

    if isinstance(self.req, IAReqInstanceAlloc):
      hypervisor_name = self.req.hypervisor
    elif isinstance(self.req, IAReqRelocate):
      hypervisor_name = cfg.GetInstanceInfo(self.req.name).hypervisor
    else:
      hypervisor_name = cluster_info.primary_hypervisor

    node_data = self.rpc.call_node_info(node_list, [cfg.GetVGName()],
                                        [hypervisor_name])
    node_iinfo = \
      self.rpc.call_all_instances_info(node_list,
                                       cluster_info.enabled_hypervisors)

    data["nodegroups"] = self._ComputeNodeGroupData(cfg)

    config_ndata = self._ComputeBasicNodeData(cfg, ninfo)
    data["nodes"] = self._ComputeDynamicNodeData(ninfo, node_data, node_iinfo,
                                                 i_list, config_ndata)
    assert len(data["nodes"]) == len(ninfo), \
        "Incomplete node data computed"

    data["instances"] = self._ComputeInstanceData(cluster_info, i_list)

    self.in_data = data

  @staticmethod
  def _ComputeNodeGroupData(cfg):
    """Compute node groups data.

    """
    cluster = cfg.GetClusterInfo()
    ng = dict((guuid, {
      "name": gdata.name,
      "alloc_policy": gdata.alloc_policy,
      "ipolicy": gmi.CalculateGroupIPolicy(cluster, gdata),
      })
      for guuid, gdata in cfg.GetAllNodeGroupsInfo().items())

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
  def _ComputeDynamicNodeData(node_cfg, node_data, node_iinfo, i_list,
                              node_results):
    """Compute global node data.

    @param node_results: the basic node structures as filled from the config

    """
    #TODO(dynmem): compute the right data on MAX and MIN memory
    # make a copy of the current dict
    node_results = dict(node_results)
    for nname, nresult in node_data.items():
      assert nname in node_results, "Missing basic data for node %s" % nname
      ninfo = node_cfg[nname]

      if not (ninfo.offline or ninfo.drained):
        nresult.Raise("Can't get data for node %s" % nname)
        node_iinfo[nname].Raise("Can't get node instance info from node %s" %
                                nname)
        remote_info = rpc.MakeLegacyNodeInfo(nresult.payload)

        for attr in ["memory_total", "memory_free", "memory_dom0",
                     "vg_size", "vg_free", "cpu_total"]:
          if attr not in remote_info:
            raise errors.OpExecError("Node '%s' didn't return attribute"
                                     " '%s'" % (nname, attr))
          if not isinstance(remote_info[attr], int):
            raise errors.OpExecError("Node '%s' returned invalid value"
                                     " for '%s': %s" %
                                     (nname, attr, remote_info[attr]))
        # compute memory used by primary instances
        i_p_mem = i_p_up_mem = 0
        for iinfo, beinfo in i_list:
          if iinfo.primary_node == nname:
            i_p_mem += beinfo[constants.BE_MAXMEM]
            if iinfo.name not in node_iinfo[nname].payload:
              i_used_mem = 0
            else:
              i_used_mem = int(node_iinfo[nname].payload[iinfo.name]["memory"])
            i_mem_diff = beinfo[constants.BE_MAXMEM] - i_used_mem
            remote_info["memory_free"] -= max(0, i_mem_diff)

            if iinfo.admin_state == constants.ADMINST_UP:
              i_p_up_mem += beinfo[constants.BE_MAXMEM]

        # compute memory used by instances
        pnr_dyn = {
          "total_memory": remote_info["memory_total"],
          "reserved_memory": remote_info["memory_dom0"],
          "free_memory": remote_info["memory_free"],
          "total_disk": remote_info["vg_size"],
          "free_disk": remote_info["vg_free"],
          "total_cpus": remote_info["cpu_total"],
          "i_pri_memory": i_p_mem,
          "i_pri_up_memory": i_p_up_mem,
          }
        pnr_dyn.update(node_results[nname])
        node_results[nname] = pnr_dyn

    return node_results

  @staticmethod
  def _ComputeInstanceData(cluster_info, i_list):
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
      pir = {
        "tags": list(iinfo.GetTags()),
        "admin_state": iinfo.admin_state,
        "vcpus": beinfo[constants.BE_VCPUS],
        "memory": beinfo[constants.BE_MAXMEM],
        "spindle_use": beinfo[constants.BE_SPINDLE_USE],
        "os": iinfo.os,
        "nodes": [iinfo.primary_node] + list(iinfo.secondary_nodes),
        "nics": nic_data,
        "disks": [{constants.IDISK_SIZE: dsk.size,
                   constants.IDISK_MODE: dsk.mode}
                  for dsk in iinfo.disks],
        "disk_template": iinfo.disk_template,
        "hypervisor": iinfo.hypervisor,
        }
      pir["disk_space_total"] = gmi.ComputeDiskSize(iinfo.disk_template,
                                                    pir["disks"])
      instance_data[iinfo.name] = pir

    return instance_data

  def _BuildInputData(self, req):
    """Build input data structures.

    """
    self._ComputeClusterData()

    request = req.GetRequest(self.cfg)
    request["type"] = req.MODE
    self.in_data["request"] = request

    self.in_text = serializer.Dump(self.in_data)

  def Run(self, name, validate=True, call_fn=None):
    """Run an instance allocator and return the results.

    """
    if call_fn is None:
      call_fn = self.rpc.call_iallocator_runner

    result = call_fn(self.cfg.GetMasterNode(), name, self.in_text)
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
    except Exception, err:
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
