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


"""Utility function mainly, but not only used by instance LU's."""

import logging
import os

from ganeti import constants
from ganeti import errors
from ganeti import locking
from ganeti import network
from ganeti import objects
from ganeti import pathutils
from ganeti import utils

from ganeti.cmdlib.common import _AnnotateDiskParams


def _BuildInstanceHookEnv(name, primary_node, secondary_nodes, os_type, status,
                          minmem, maxmem, vcpus, nics, disk_template, disks,
                          bep, hvp, hypervisor_name, tags):
  """Builds instance related env variables for hooks

  This builds the hook environment from individual variables.

  @type name: string
  @param name: the name of the instance
  @type primary_node: string
  @param primary_node: the name of the instance's primary node
  @type secondary_nodes: list
  @param secondary_nodes: list of secondary nodes as strings
  @type os_type: string
  @param os_type: the name of the instance's OS
  @type status: string
  @param status: the desired status of the instance
  @type minmem: string
  @param minmem: the minimum memory size of the instance
  @type maxmem: string
  @param maxmem: the maximum memory size of the instance
  @type vcpus: string
  @param vcpus: the count of VCPUs the instance has
  @type nics: list
  @param nics: list of tuples (name, uuid, ip, mac, mode, link, net, netinfo)
      representing the NICs the instance has
  @type disk_template: string
  @param disk_template: the disk template of the instance
  @type disks: list
  @param disks: list of tuples (name, uuid, size, mode)
  @type bep: dict
  @param bep: the backend parameters for the instance
  @type hvp: dict
  @param hvp: the hypervisor parameters for the instance
  @type hypervisor_name: string
  @param hypervisor_name: the hypervisor for the instance
  @type tags: list
  @param tags: list of instance tags as strings
  @rtype: dict
  @return: the hook environment for this instance

  """
  env = {
    "OP_TARGET": name,
    "INSTANCE_NAME": name,
    "INSTANCE_PRIMARY": primary_node,
    "INSTANCE_SECONDARIES": " ".join(secondary_nodes),
    "INSTANCE_OS_TYPE": os_type,
    "INSTANCE_STATUS": status,
    "INSTANCE_MINMEM": minmem,
    "INSTANCE_MAXMEM": maxmem,
    # TODO(2.9) remove deprecated "memory" value
    "INSTANCE_MEMORY": maxmem,
    "INSTANCE_VCPUS": vcpus,
    "INSTANCE_DISK_TEMPLATE": disk_template,
    "INSTANCE_HYPERVISOR": hypervisor_name,
    }
  if nics:
    nic_count = len(nics)
    for idx, (name, _, ip, mac, mode, link, net, netinfo) in enumerate(nics):
      if ip is None:
        ip = ""
      env["INSTANCE_NIC%d_NAME" % idx] = name
      env["INSTANCE_NIC%d_IP" % idx] = ip
      env["INSTANCE_NIC%d_MAC" % idx] = mac
      env["INSTANCE_NIC%d_MODE" % idx] = mode
      env["INSTANCE_NIC%d_LINK" % idx] = link
      if netinfo:
        nobj = objects.Network.FromDict(netinfo)
        env.update(nobj.HooksDict("INSTANCE_NIC%d_" % idx))
      elif network:
        # FIXME: broken network reference: the instance NIC specifies a
        # network, but the relevant network entry was not in the config. This
        # should be made impossible.
        env["INSTANCE_NIC%d_NETWORK_NAME" % idx] = net
      if mode == constants.NIC_MODE_BRIDGED:
        env["INSTANCE_NIC%d_BRIDGE" % idx] = link
  else:
    nic_count = 0

  env["INSTANCE_NIC_COUNT"] = nic_count

  if disks:
    disk_count = len(disks)
    for idx, (name, size, mode) in enumerate(disks):
      env["INSTANCE_DISK%d_NAME" % idx] = name
      env["INSTANCE_DISK%d_SIZE" % idx] = size
      env["INSTANCE_DISK%d_MODE" % idx] = mode
  else:
    disk_count = 0

  env["INSTANCE_DISK_COUNT"] = disk_count

  if not tags:
    tags = []

  env["INSTANCE_TAGS"] = " ".join(tags)

  for source, kind in [(bep, "BE"), (hvp, "HV")]:
    for key, value in source.items():
      env["INSTANCE_%s_%s" % (kind, key)] = value

  return env


def _BuildInstanceHookEnvByObject(lu, instance, override=None):
  """Builds instance related env variables for hooks from an object.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance for which we should build the
      environment
  @type override: dict
  @param override: dictionary with key/values that will override
      our values
  @rtype: dict
  @return: the hook environment dictionary

  """
  cluster = lu.cfg.GetClusterInfo()
  bep = cluster.FillBE(instance)
  hvp = cluster.FillHV(instance)
  args = {
    "name": instance.name,
    "primary_node": instance.primary_node,
    "secondary_nodes": instance.secondary_nodes,
    "os_type": instance.os,
    "status": instance.admin_state,
    "maxmem": bep[constants.BE_MAXMEM],
    "minmem": bep[constants.BE_MINMEM],
    "vcpus": bep[constants.BE_VCPUS],
    "nics": _NICListToTuple(lu, instance.nics),
    "disk_template": instance.disk_template,
    "disks": [(disk.name, disk.size, disk.mode)
              for disk in instance.disks],
    "bep": bep,
    "hvp": hvp,
    "hypervisor_name": instance.hypervisor,
    "tags": instance.tags,
  }
  if override:
    args.update(override)
  return _BuildInstanceHookEnv(**args) # pylint: disable=W0142


def _GetClusterDomainSecret():
  """Reads the cluster domain secret.

  """
  return utils.ReadOneLineFile(pathutils.CLUSTER_DOMAIN_SECRET_FILE,
                               strict=True)


def _CheckNodeNotDrained(lu, node):
  """Ensure that a given node is not drained.

  @param lu: the LU on behalf of which we make the check
  @param node: the node to check
  @raise errors.OpPrereqError: if the node is drained

  """
  if lu.cfg.GetNodeInfo(node).drained:
    raise errors.OpPrereqError("Can't use drained node %s" % node,
                               errors.ECODE_STATE)


def _StartInstanceDisks(lu, instance, force):
  """Start the disks of an instance.

  """
  disks_ok, _ = _AssembleInstanceDisks(lu, instance,
                                           ignore_secondaries=force)
  if not disks_ok:
    _ShutdownInstanceDisks(lu, instance)
    if force is not None and not force:
      lu.LogWarning("",
                    hint=("If the message above refers to a secondary node,"
                          " you can retry the operation using '--force'"))
    raise errors.OpExecError("Disk consistency error")


def _ShutdownInstanceDisks(lu, instance, disks=None, ignore_primary=False):
  """Shutdown block devices of an instance.

  This does the shutdown on all nodes of the instance.

  If the ignore_primary is false, errors on the primary node are
  ignored.

  """
  all_result = True
  disks = _ExpandCheckDisks(instance, disks)

  for disk in disks:
    for node, top_disk in disk.ComputeNodeTree(instance.primary_node):
      lu.cfg.SetDiskID(top_disk, node)
      result = lu.rpc.call_blockdev_shutdown(node, (top_disk, instance))
      msg = result.fail_msg
      if msg:
        lu.LogWarning("Could not shutdown block device %s on node %s: %s",
                      disk.iv_name, node, msg)
        if ((node == instance.primary_node and not ignore_primary) or
            (node != instance.primary_node and not result.offline)):
          all_result = False
  return all_result


def _RemoveInstance(lu, feedback_fn, instance, ignore_failures):
  """Utility function to remove an instance.

  """
  logging.info("Removing block devices for instance %s", instance.name)

  if not _RemoveDisks(lu, instance, ignore_failures=ignore_failures):
    if not ignore_failures:
      raise errors.OpExecError("Can't remove instance's disks")
    feedback_fn("Warning: can't remove instance's disks")

  logging.info("Removing instance %s out of cluster config", instance.name)

  lu.cfg.RemoveInstance(instance.name)

  assert not lu.remove_locks.get(locking.LEVEL_INSTANCE), \
    "Instance lock removal conflict"

  # Remove lock for the instance
  lu.remove_locks[locking.LEVEL_INSTANCE] = instance.name


def _AssembleInstanceDisks(lu, instance, disks=None, ignore_secondaries=False,
                           ignore_size=False):
  """Prepare the block devices for an instance.

  This sets up the block devices on all nodes.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance for whose disks we assemble
  @type disks: list of L{objects.Disk} or None
  @param disks: which disks to assemble (or all, if None)
  @type ignore_secondaries: boolean
  @param ignore_secondaries: if true, errors on secondary nodes
      won't result in an error return from the function
  @type ignore_size: boolean
  @param ignore_size: if true, the current known size of the disk
      will not be used during the disk activation, useful for cases
      when the size is wrong
  @return: False if the operation failed, otherwise a list of
      (host, instance_visible_name, node_visible_name)
      with the mapping from node devices to instance devices

  """
  device_info = []
  disks_ok = True
  iname = instance.name
  disks = _ExpandCheckDisks(instance, disks)

  # With the two passes mechanism we try to reduce the window of
  # opportunity for the race condition of switching DRBD to primary
  # before handshaking occured, but we do not eliminate it

  # The proper fix would be to wait (with some limits) until the
  # connection has been made and drbd transitions from WFConnection
  # into any other network-connected state (Connected, SyncTarget,
  # SyncSource, etc.)

  # 1st pass, assemble on all nodes in secondary mode
  for idx, inst_disk in enumerate(disks):
    for node, node_disk in inst_disk.ComputeNodeTree(instance.primary_node):
      if ignore_size:
        node_disk = node_disk.Copy()
        node_disk.UnsetSize()
      lu.cfg.SetDiskID(node_disk, node)
      result = lu.rpc.call_blockdev_assemble(node, (node_disk, instance), iname,
                                             False, idx)
      msg = result.fail_msg
      if msg:
        is_offline_secondary = (node in instance.secondary_nodes and
                                result.offline)
        lu.LogWarning("Could not prepare block device %s on node %s"
                      " (is_primary=False, pass=1): %s",
                      inst_disk.iv_name, node, msg)
        if not (ignore_secondaries or is_offline_secondary):
          disks_ok = False

  # FIXME: race condition on drbd migration to primary

  # 2nd pass, do only the primary node
  for idx, inst_disk in enumerate(disks):
    dev_path = None

    for node, node_disk in inst_disk.ComputeNodeTree(instance.primary_node):
      if node != instance.primary_node:
        continue
      if ignore_size:
        node_disk = node_disk.Copy()
        node_disk.UnsetSize()
      lu.cfg.SetDiskID(node_disk, node)
      result = lu.rpc.call_blockdev_assemble(node, (node_disk, instance), iname,
                                             True, idx)
      msg = result.fail_msg
      if msg:
        lu.LogWarning("Could not prepare block device %s on node %s"
                      " (is_primary=True, pass=2): %s",
                      inst_disk.iv_name, node, msg)
        disks_ok = False
      else:
        dev_path = result.payload

    device_info.append((instance.primary_node, inst_disk.iv_name, dev_path))

  # leave the disks configured for the primary node
  # this is a workaround that would be fixed better by
  # improving the logical/physical id handling
  for disk in disks:
    lu.cfg.SetDiskID(disk, instance.primary_node)

  return disks_ok, device_info


def _RemoveDisks(lu, instance, target_node=None, ignore_failures=False):
  """Remove all disks for an instance.

  This abstracts away some work from `AddInstance()` and
  `RemoveInstance()`. Note that in case some of the devices couldn't
  be removed, the removal will continue with the other ones.

  @type lu: L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type instance: L{objects.Instance}
  @param instance: the instance whose disks we should remove
  @type target_node: string
  @param target_node: used to override the node on which to remove the disks
  @rtype: boolean
  @return: the success of the removal

  """
  logging.info("Removing block devices for instance %s", instance.name)

  all_result = True
  ports_to_release = set()
  anno_disks = _AnnotateDiskParams(instance, instance.disks, lu.cfg)
  for (idx, device) in enumerate(anno_disks):
    if target_node:
      edata = [(target_node, device)]
    else:
      edata = device.ComputeNodeTree(instance.primary_node)
    for node, disk in edata:
      lu.cfg.SetDiskID(disk, node)
      result = lu.rpc.call_blockdev_remove(node, disk)
      if result.fail_msg:
        lu.LogWarning("Could not remove disk %s on node %s,"
                      " continuing anyway: %s", idx, node, result.fail_msg)
        if not (result.offline and node != instance.primary_node):
          all_result = False

    # if this is a DRBD disk, return its port to the pool
    if device.dev_type in constants.LDS_DRBD:
      ports_to_release.add(device.logical_id[2])

  if all_result or ignore_failures:
    for port in ports_to_release:
      lu.cfg.AddTcpUdpPort(port)

  if instance.disk_template in constants.DTS_FILEBASED:
    file_storage_dir = os.path.dirname(instance.disks[0].logical_id[1])
    if target_node:
      tgt = target_node
    else:
      tgt = instance.primary_node
    result = lu.rpc.call_file_storage_dir_remove(tgt, file_storage_dir)
    if result.fail_msg:
      lu.LogWarning("Could not remove directory '%s' on node %s: %s",
                    file_storage_dir, instance.primary_node, result.fail_msg)
      all_result = False

  return all_result


def _ExpandCheckDisks(instance, disks):
  """Return the instance disks selected by the disks list

  @type disks: list of L{objects.Disk} or None
  @param disks: selected disks
  @rtype: list of L{objects.Disk}
  @return: selected instance disks to act on

  """
  if disks is None:
    return instance.disks
  else:
    if not set(disks).issubset(instance.disks):
      raise errors.ProgrammerError("Can only act on disks belonging to the"
                                   " target instance")
    return disks


def _NICToTuple(lu, nic):
  """Build a tupple of nic information.

  @type lu:  L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type nic: L{objects.NIC}
  @param nic: nic to convert to hooks tuple

  """
  cluster = lu.cfg.GetClusterInfo()
  filled_params = cluster.SimpleFillNIC(nic.nicparams)
  mode = filled_params[constants.NIC_MODE]
  link = filled_params[constants.NIC_LINK]
  netinfo = None
  if nic.network:
    nobj = lu.cfg.GetNetwork(nic.network)
    netinfo = objects.Network.ToDict(nobj)
  return (nic.name, nic.uuid, nic.ip, nic.mac, mode, link, nic.network, netinfo)


def _NICListToTuple(lu, nics):
  """Build a list of nic information tuples.

  This list is suitable to be passed to _BuildInstanceHookEnv or as a return
  value in LUInstanceQueryData.

  @type lu:  L{LogicalUnit}
  @param lu: the logical unit on whose behalf we execute
  @type nics: list of L{objects.NIC}
  @param nics: list of nics to convert to hooks tuples

  """
  hooks_nics = []
  for nic in nics:
    hooks_nics.append(_NICToTuple(lu, nic))
  return hooks_nics
