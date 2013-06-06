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


"""Logical units dealing with instance operations (start/stop/...).

Those operations have in common that they affect the operating system in a
running instance directly.

"""

import logging

from ganeti import constants
from ganeti import errors
from ganeti import hypervisor
from ganeti import locking
from ganeti import objects
from ganeti import utils
from ganeti.cmdlib.base import LogicalUnit, NoHooksLU
from ganeti.cmdlib.common import INSTANCE_ONLINE, INSTANCE_DOWN, \
  CheckHVParams, CheckInstanceState, CheckNodeOnline, ExpandNodeName, \
  GetUpdatedParams, CheckOSParams, ShareAll
from ganeti.cmdlib.instance_storage import StartInstanceDisks, \
  ShutdownInstanceDisks
from ganeti.cmdlib.instance_utils import BuildInstanceHookEnvByObject, \
  CheckInstanceBridgesExist, CheckNodeFreeMemory, CheckNodeHasOS


class LUInstanceStartup(LogicalUnit):
  """Starts an instance.

  """
  HPATH = "instance-start"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    # extra beparams
    if self.op.beparams:
      # fill the beparams dict
      objects.UpgradeBeParams(self.op.beparams)
      utils.ForceDictType(self.op.beparams, constants.BES_PARAMETER_TYPES)

  def ExpandNames(self):
    self._ExpandAndLockInstance()
    self.recalculate_locks[locking.LEVEL_NODE_RES] = constants.LOCKS_REPLACE

  def DeclareLocks(self, level):
    if level == locking.LEVEL_NODE_RES:
      self._LockInstancesNodes(primary_only=True, level=locking.LEVEL_NODE_RES)

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "FORCE": self.op.force,
      }

    env.update(BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    cluster = self.cfg.GetClusterInfo()
    # extra hvparams
    if self.op.hvparams:
      # check hypervisor parameter syntax (locally)
      utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
      filled_hvp = cluster.FillHV(instance)
      filled_hvp.update(self.op.hvparams)
      hv_type = hypervisor.GetHypervisorClass(instance.hypervisor)
      hv_type.CheckParameterSyntax(filled_hvp)
      CheckHVParams(self, instance.all_nodes, instance.hypervisor, filled_hvp)

    CheckInstanceState(self, instance, INSTANCE_ONLINE)

    self.primary_offline = self.cfg.GetNodeInfo(instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")

      if self.op.hvparams or self.op.beparams:
        self.LogWarning("Overridden parameters are ignored")
    else:
      CheckNodeOnline(self, instance.primary_node)

      bep = self.cfg.GetClusterInfo().FillBE(instance)
      bep.update(self.op.beparams)

      # check bridges existence
      CheckInstanceBridgesExist(self, instance)

      remote_info = self.rpc.call_instance_info(
          instance.primary_node, instance.name, instance.hypervisor,
          cluster.hvparams[instance.hypervisor])
      remote_info.Raise("Error checking node %s" % instance.primary_node,
                        prereq=True, ecode=errors.ECODE_ENVIRON)
      if not remote_info.payload: # not running already
        CheckNodeFreeMemory(
            self, instance.primary_node, "starting instance %s" % instance.name,
            bep[constants.BE_MINMEM], instance.hypervisor,
            self.cfg.GetClusterInfo().hvparams[instance.hypervisor])

  def Exec(self, feedback_fn):
    """Start the instance.

    """
    instance = self.instance
    force = self.op.force
    reason = self.op.reason

    if not self.op.no_remember:
      self.cfg.MarkInstanceUp(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as started")
    else:
      node_current = instance.primary_node

      StartInstanceDisks(self, instance, force)

      result = \
        self.rpc.call_instance_start(node_current,
                                     (instance, self.op.hvparams,
                                      self.op.beparams),
                                     self.op.startup_paused, reason)
      msg = result.fail_msg
      if msg:
        ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance: %s" % msg)


class LUInstanceShutdown(LogicalUnit):
  """Shutdown an instance.

  """
  HPATH = "instance-stop"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = BuildInstanceHookEnvByObject(self, self.instance)
    env["TIMEOUT"] = self.op.timeout
    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if not self.op.force:
      CheckInstanceState(self, self.instance, INSTANCE_ONLINE)
    else:
      self.LogWarning("Ignoring offline instance check")

    self.primary_offline = \
      self.cfg.GetNodeInfo(self.instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")
    else:
      CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Shutdown the instance.

    """
    instance = self.instance
    node_current = instance.primary_node
    timeout = self.op.timeout
    reason = self.op.reason

    # If the instance is offline we shouldn't mark it as down, as that
    # resets the offline flag.
    if not self.op.no_remember and instance.admin_state in INSTANCE_ONLINE:
      self.cfg.MarkInstanceDown(instance.name)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as stopped")
    else:
      result = self.rpc.call_instance_shutdown(node_current, instance, timeout,
                                               reason)
      msg = result.fail_msg
      if msg:
        self.LogWarning("Could not shutdown instance: %s", msg)

      ShutdownInstanceDisks(self, instance)


class LUInstanceReinstall(LogicalUnit):
  """Reinstall an instance.

  """
  HPATH = "instance-reinstall"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    return BuildInstanceHookEnvByObject(self, self.instance)

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, instance.primary_node, "Instance primary node"
                    " offline, cannot reinstall")

    if instance.disk_template == constants.DT_DISKLESS:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name,
                                 errors.ECODE_INVAL)
    CheckInstanceState(self, instance, INSTANCE_DOWN, msg="cannot reinstall")

    if self.op.os_type is not None:
      # OS verification
      pnode = ExpandNodeName(self.cfg, instance.primary_node)
      CheckNodeHasOS(self, pnode, self.op.os_type, self.op.force_variant)
      instance_os = self.op.os_type
    else:
      instance_os = instance.os

    nodelist = list(instance.all_nodes)

    if self.op.osparams:
      i_osdict = GetUpdatedParams(instance.osparams, self.op.osparams)
      CheckOSParams(self, True, nodelist, instance_os, i_osdict)
      self.os_inst = i_osdict # the new dict (without defaults)
    else:
      self.os_inst = None

    self.instance = instance

  def Exec(self, feedback_fn):
    """Reinstall the instance.

    """
    inst = self.instance

    if self.op.os_type is not None:
      feedback_fn("Changing OS to '%s'..." % self.op.os_type)
      inst.os = self.op.os_type
      # Write to configuration
      self.cfg.Update(inst, feedback_fn)

    StartInstanceDisks(self, inst, None)
    try:
      feedback_fn("Running the instance OS create scripts...")
      # FIXME: pass debug option from opcode to backend
      result = self.rpc.call_instance_os_add(inst.primary_node,
                                             (inst, self.os_inst), True,
                                             self.op.debug_level)
      result.Raise("Could not install OS for instance %s on node %s" %
                   (inst.name, inst.primary_node))
    finally:
      ShutdownInstanceDisks(self, inst)


class LUInstanceReboot(LogicalUnit):
  """Reboot an instance.

  """
  HPATH = "instance-reboot"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def BuildHooksEnv(self):
    """Build hooks env.

    This runs on master, primary and secondary nodes of the instance.

    """
    env = {
      "IGNORE_SECONDARIES": self.op.ignore_secondaries,
      "REBOOT_TYPE": self.op.reboot_type,
      "SHUTDOWN_TIMEOUT": self.op.shutdown_timeout,
      }

    env.update(BuildInstanceHookEnvByObject(self, self.instance))

    return env

  def BuildHooksNodes(self):
    """Build hooks nodes.

    """
    nl = [self.cfg.GetMasterNode()] + list(self.instance.all_nodes)
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckInstanceState(self, instance, INSTANCE_ONLINE)
    CheckNodeOnline(self, instance.primary_node)

    # check bridges existence
    CheckInstanceBridgesExist(self, instance)

  def Exec(self, feedback_fn):
    """Reboot the instance.

    """
    instance = self.instance
    ignore_secondaries = self.op.ignore_secondaries
    reboot_type = self.op.reboot_type
    reason = self.op.reason

    cluster = self.cfg.GetClusterInfo()
    remote_info = self.rpc.call_instance_info(
        instance.primary_node, instance.name, instance.hypervisor,
        cluster.hvparams[instance.hypervisor])
    remote_info.Raise("Error checking node %s" % instance.primary_node)
    instance_running = bool(remote_info.payload)

    node_current = instance.primary_node

    if instance_running and reboot_type in [constants.INSTANCE_REBOOT_SOFT,
                                            constants.INSTANCE_REBOOT_HARD]:
      for disk in instance.disks:
        self.cfg.SetDiskID(disk, node_current)
      result = self.rpc.call_instance_reboot(node_current, instance,
                                             reboot_type,
                                             self.op.shutdown_timeout, reason)
      result.Raise("Could not reboot instance")
    else:
      if instance_running:
        result = self.rpc.call_instance_shutdown(node_current, instance,
                                                 self.op.shutdown_timeout,
                                                 reason)
        result.Raise("Could not shutdown instance for full reboot")
        ShutdownInstanceDisks(self, instance)
      else:
        self.LogInfo("Instance %s was already stopped, starting now",
                     instance.name)
      StartInstanceDisks(self, instance, ignore_secondaries)
      result = self.rpc.call_instance_start(node_current,
                                            (instance, None, None), False,
                                            reason)
      msg = result.fail_msg
      if msg:
        ShutdownInstanceDisks(self, instance)
        raise errors.OpExecError("Could not start instance for"
                                 " full reboot: %s" % msg)

    self.cfg.MarkInstanceUp(instance.name)


def GetInstanceConsole(cluster, instance):
  """Returns console information for an instance.

  @type cluster: L{objects.Cluster}
  @type instance: L{objects.Instance}
  @rtype: dict

  """
  hyper = hypervisor.GetHypervisorClass(instance.hypervisor)
  # beparams and hvparams are passed separately, to avoid editing the
  # instance and then saving the defaults in the instance itself.
  hvparams = cluster.FillHV(instance)
  beparams = cluster.FillBE(instance)
  console = hyper.GetInstanceConsole(instance, hvparams, beparams)

  assert console.instance == instance.name
  assert console.Validate()

  return console.ToDict()


class LUInstanceConsole(NoHooksLU):
  """Connect to an instance's console.

  This is somewhat special in that it returns the command line that
  you need to run on the master node in order to connect to the
  console.

  """
  REQ_BGL = False

  def ExpandNames(self):
    self.share_locks = ShareAll()
    self._ExpandAndLockInstance()

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_name)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Connect to the console of an instance

    """
    instance = self.instance
    node = instance.primary_node

    cluster_hvparams = self.cfg.GetClusterInfo().hvparams
    node_insts = self.rpc.call_instance_list([node],
                                             [instance.hypervisor],
                                             cluster_hvparams)[node]
    node_insts.Raise("Can't get node information from %s" % node)

    if instance.name not in node_insts.payload:
      if instance.admin_state == constants.ADMINST_UP:
        state = constants.INSTST_ERRORDOWN
      elif instance.admin_state == constants.ADMINST_DOWN:
        state = constants.INSTST_ADMINDOWN
      else:
        state = constants.INSTST_ADMINOFFLINE
      raise errors.OpExecError("Instance %s is not running (state %s)" %
                               (instance.name, state))

    logging.debug("Connecting to console of %s on %s", instance.name, node)

    return GetInstanceConsole(self.cfg.GetClusterInfo(), instance)
