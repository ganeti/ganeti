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
  CheckHVParams, CheckInstanceState, CheckNodeOnline, GetUpdatedParams, \
  CheckOSParams, CheckOSImage, ShareAll
from ganeti.cmdlib.instance_storage import StartInstanceDisks, \
  ShutdownInstanceDisks, ImageDisks
from ganeti.cmdlib.instance_utils import BuildInstanceHookEnvByObject, \
  CheckInstanceBridgesExist, CheckNodeFreeMemory, UpdateMetadata
from ganeti.hypervisor import hv_base


def _IsInstanceUserDown(cluster, instance, instance_info):
  hvparams = cluster.FillHV(instance, skip_globals=True)
  return instance_info and \
      "state" in instance_info and \
      hv_base.HvInstanceState.IsShutdown(instance_info["state"]) and \
      (instance.hypervisor != constants.HT_KVM or
       hvparams[constants.HV_KVM_USER_SHUTDOWN])


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
    nl = [self.cfg.GetMasterNode()] + \
        list(self.cfg.GetInstanceNodes(self.instance.uuid))
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    cluster = self.cfg.GetClusterInfo()
    # extra hvparams
    if self.op.hvparams:
      # check hypervisor parameter syntax (locally)
      utils.ForceDictType(self.op.hvparams, constants.HVS_PARAMETER_TYPES)
      filled_hvp = cluster.FillHV(self.instance)
      filled_hvp.update(self.op.hvparams)
      hv_type = hypervisor.GetHypervisorClass(self.instance.hypervisor)
      hv_type.CheckParameterSyntax(filled_hvp)
      CheckHVParams(self, self.cfg.GetInstanceNodes(self.instance.uuid),
                    self.instance.hypervisor, filled_hvp)

    CheckInstanceState(self, self.instance, INSTANCE_ONLINE)

    self.primary_offline = \
      self.cfg.GetNodeInfo(self.instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")

      if self.op.hvparams or self.op.beparams:
        self.LogWarning("Overridden parameters are ignored")
    else:
      CheckNodeOnline(self, self.instance.primary_node)

      bep = self.cfg.GetClusterInfo().FillBE(self.instance)
      bep.update(self.op.beparams)

      # check bridges existence
      CheckInstanceBridgesExist(self, self.instance)

      remote_info = self.rpc.call_instance_info(
          self.instance.primary_node, self.instance.name,
          self.instance.hypervisor, cluster.hvparams[self.instance.hypervisor])
      remote_info.Raise("Error checking node %s" %
                        self.cfg.GetNodeName(self.instance.primary_node),
                        prereq=True, ecode=errors.ECODE_ENVIRON)

      self.requires_cleanup = False

      if remote_info.payload:
        if _IsInstanceUserDown(self.cfg.GetClusterInfo(),
                               self.instance,
                               remote_info.payload):
          self.requires_cleanup = True
      else: # not running already
        CheckNodeFreeMemory(
            self, self.instance.primary_node,
            "starting instance %s" % self.instance.name,
            bep[constants.BE_MINMEM], self.instance.hypervisor,
            self.cfg.GetClusterInfo().hvparams[self.instance.hypervisor])

  def Exec(self, feedback_fn):
    """Start the instance.

    """
    if not self.op.no_remember:
      self.instance = self.cfg.MarkInstanceUp(self.instance.uuid)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as started")
    else:
      if self.requires_cleanup:
        result = self.rpc.call_instance_shutdown(
          self.instance.primary_node,
          self.instance,
          self.op.shutdown_timeout, self.op.reason)
        result.Raise("Could not shutdown instance '%s'" % self.instance.name)

        ShutdownInstanceDisks(self, self.instance)

      StartInstanceDisks(self, self.instance, self.op.force)
      self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)

      result = \
        self.rpc.call_instance_start(self.instance.primary_node,
                                     (self.instance, self.op.hvparams,
                                      self.op.beparams),
                                     self.op.startup_paused, self.op.reason)
      if result.fail_msg:
        ShutdownInstanceDisks(self, self.instance)
        result.Raise("Could not start instance '%s'" % self.instance.name)


class LUInstanceShutdown(LogicalUnit):
  """Shutdown an instance.

  """
  HPATH = "instance-stop"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def ExpandNames(self):
    self._ExpandAndLockInstance()

  def CheckArguments(self):
    """Check arguments.

    """
    if self.op.no_remember and self.op.admin_state_source is not None:
      self.LogWarning("Parameter 'admin_state_source' has no effect if used"
                      " with parameter 'no_remember'")

    if self.op.admin_state_source is None:
      self.op.admin_state_source = constants.ADMIN_SOURCE

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
    nl = [self.cfg.GetMasterNode()] + \
      list(self.cfg.GetInstanceNodes(self.instance.uuid))
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name

    if self.op.force:
      self.LogWarning("Ignoring offline instance check")
    else:
      CheckInstanceState(self, self.instance, INSTANCE_ONLINE)

    self.primary_offline = \
      self.cfg.GetNodeInfo(self.instance.primary_node).offline

    if self.primary_offline and self.op.ignore_offline_nodes:
      self.LogWarning("Ignoring offline primary node")
    else:
      CheckNodeOnline(self, self.instance.primary_node)

    if self.op.admin_state_source == constants.USER_SOURCE:
      cluster = self.cfg.GetClusterInfo()

      result = self.rpc.call_instance_info(
        self.instance.primary_node,
        self.instance.name,
        self.instance.hypervisor,
        cluster.hvparams[self.instance.hypervisor])
      result.Raise("Error checking instance '%s'" % self.instance.name,
                   prereq=True)

      if not _IsInstanceUserDown(cluster,
                                 self.instance,
                                 result.payload):
        raise errors.OpPrereqError("Instance '%s' was not shutdown by the user"
                                   % self.instance.name)

  def Exec(self, feedback_fn):
    """Shutdown the instance.

    """
    # If the instance is offline we shouldn't mark it as down, as that
    # resets the offline flag.
    if not self.op.no_remember and self.instance.admin_state in INSTANCE_ONLINE:
      self.instance = self.cfg.MarkInstanceDown(self.instance.uuid)

      if self.op.admin_state_source == constants.ADMIN_SOURCE:
        self.cfg.MarkInstanceDown(self.instance.uuid)
      elif self.op.admin_state_source == constants.USER_SOURCE:
        self.cfg.MarkInstanceUserDown(self.instance.uuid)

    if self.primary_offline:
      assert self.op.ignore_offline_nodes
      self.LogInfo("Primary node offline, marked instance as stopped")
    else:
      result = self.rpc.call_instance_shutdown(
        self.instance.primary_node,
        self.instance,
        self.op.timeout, self.op.reason)
      result.Raise("Could not shutdown instance '%s'" % self.instance.name)

      ShutdownInstanceDisks(self, self.instance)


class LUInstanceReinstall(LogicalUnit):
  """Reinstall an instance.

  """
  HPATH = "instance-reinstall"
  HTYPE = constants.HTYPE_INSTANCE
  REQ_BGL = False

  def CheckArguments(self):
    CheckOSImage(self.op)

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
    nl = [self.cfg.GetMasterNode()] + \
      list(self.cfg.GetInstanceNodes(self.instance.uuid))
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster and is not running.

    """
    instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, instance.primary_node, "Instance primary node"
                    " offline, cannot reinstall")

    if not instance.disks:
      raise errors.OpPrereqError("Instance '%s' has no disks" %
                                 self.op.instance_name,
                                 errors.ECODE_INVAL)
    CheckInstanceState(self, instance, INSTANCE_DOWN, msg="cannot reinstall")

    # Handle OS parameters
    self._MergeValidateOsParams(instance)

    self.instance = instance

  def _MergeValidateOsParams(self, instance):
    "Handle the OS parameter merging and validation for the target instance."
    node_uuids = list(self.cfg.GetInstanceNodes(instance.uuid))

    self.op.osparams = self.op.osparams or {}
    self.op.osparams_private = self.op.osparams_private or {}
    self.op.osparams_secret = self.op.osparams_secret or {}

    # Handle the use of 'default' values.
    params_public = GetUpdatedParams(instance.osparams, self.op.osparams)
    params_private = GetUpdatedParams(instance.osparams_private,
                                        self.op.osparams_private)
    params_secret = self.op.osparams_secret

    # Handle OS parameters
    if self.op.os_type is not None:
      instance_os = self.op.os_type
    else:
      instance_os = instance.os

    cluster = self.cfg.GetClusterInfo()
    self.osparams = cluster.SimpleFillOS(
      instance_os,
      params_public,
      os_params_private=params_private,
      os_params_secret=params_secret
    )

    self.osparams_private = params_private
    self.osparams_secret = params_secret

    CheckOSParams(self, True, node_uuids, instance_os, self.osparams,
                  self.op.force_variant)

  def _ReinstallOSScripts(self, instance, osparams, debug_level):
    """Reinstall OS scripts on an instance.

    @type instance: L{objects.Instance}
    @param instance: instance of which the OS scripts should run

    @type osparams: L{dict}
    @param osparams: OS parameters

    @type debug_level: non-negative int
    @param debug_level: debug level

    @rtype: NoneType
    @return: None
    @raise errors.OpExecError: in case of failure

    """
    self.LogInfo("Running instance OS create scripts...")
    result = self.rpc.call_instance_os_add(instance.primary_node,
                                           (instance, osparams),
                                           True,
                                           debug_level)
    result.Raise("Could not install OS for instance '%s' on node '%s'" %
                 (instance.name, self.cfg.GetNodeName(instance.primary_node)))

  def Exec(self, feedback_fn):
    """Reinstall the instance.

    """
    os_image = objects.GetOSImage(self.op.osparams)

    if os_image is not None:
      feedback_fn("Using OS image '%s'" % os_image)
    else:
      os_image = objects.GetOSImage(self.instance.osparams)

    os_type = self.op.os_type

    if os_type is not None:
      feedback_fn("Changing OS scripts to '%s'..." % os_type)
      self.instance.os = os_type
      self.cfg.Update(self.instance, feedback_fn)
    else:
      os_type = self.instance.os

    if not os_image and not os_type:
      self.LogInfo("No OS scripts or OS image specified or found in the"
                   " instance's configuration, nothing to install")
    else:
      if self.op.osparams is not None:
        self.instance.osparams = self.op.osparams
      if self.op.osparams_private is not None:
        self.instance.osparams_private = self.op.osparams_private
      self.cfg.Update(self.instance, feedback_fn)
      StartInstanceDisks(self, self.instance, None)
      self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)
      try:
        if os_image:
          ImageDisks(self, self.instance, os_image)

        if os_type:
          self._ReinstallOSScripts(self.instance, self.osparams,
                                   self.op.debug_level)

        UpdateMetadata(feedback_fn, self.rpc, self.instance,
                       osparams_public=self.osparams,
                       osparams_private=self.osparams_private,
                       osparams_secret=self.osparams_secret)
      finally:
        ShutdownInstanceDisks(self, self.instance)


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
    nl = [self.cfg.GetMasterNode()] + \
      list(self.cfg.GetInstanceNodes(self.instance.uuid))
    return (nl, nl)

  def CheckPrereq(self):
    """Check prerequisites.

    This checks that the instance is in the cluster.

    """
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckInstanceState(self, self.instance, INSTANCE_ONLINE)
    CheckNodeOnline(self, self.instance.primary_node)

    # check bridges existence
    CheckInstanceBridgesExist(self, self.instance)

  def Exec(self, feedback_fn):
    """Reboot the instance.

    """
    cluster = self.cfg.GetClusterInfo()
    remote_info = self.rpc.call_instance_info(
        self.instance.primary_node, self.instance.name,
        self.instance.hypervisor, cluster.hvparams[self.instance.hypervisor])
    remote_info.Raise("Error checking node %s" %
                      self.cfg.GetNodeName(self.instance.primary_node))
    instance_running = bool(remote_info.payload)

    current_node_uuid = self.instance.primary_node

    if instance_running and \
        self.op.reboot_type in [constants.INSTANCE_REBOOT_SOFT,
                                constants.INSTANCE_REBOOT_HARD]:
      result = self.rpc.call_instance_reboot(current_node_uuid, self.instance,
                                             self.op.reboot_type,
                                             self.op.shutdown_timeout,
                                             self.op.reason)
      result.Raise("Could not reboot instance")
    else:
      if instance_running:
        result = self.rpc.call_instance_shutdown(current_node_uuid,
                                                 self.instance,
                                                 self.op.shutdown_timeout,
                                                 self.op.reason)
        result.Raise("Could not shutdown instance for full reboot")
        ShutdownInstanceDisks(self, self.instance)
        self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)
      else:
        self.LogInfo("Instance %s was already stopped, starting now",
                     self.instance.name)
      StartInstanceDisks(self, self.instance, self.op.ignore_secondaries)
      self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)
      result = self.rpc.call_instance_start(current_node_uuid,
                                            (self.instance, None, None), False,
                                            self.op.reason)
      msg = result.fail_msg
      if msg:
        ShutdownInstanceDisks(self, self.instance)
        self.instance = self.cfg.GetInstanceInfo(self.instance.uuid)
        raise errors.OpExecError("Could not start instance for"
                                 " full reboot: %s" % msg)

    self.cfg.MarkInstanceUp(self.instance.uuid)


def GetInstanceConsole(cluster, instance, primary_node, node_group):
  """Returns console information for an instance.

  @type cluster: L{objects.Cluster}
  @type instance: L{objects.Instance}
  @type primary_node: L{objects.Node}
  @type node_group: L{objects.NodeGroup}
  @rtype: dict

  """
  hyper = hypervisor.GetHypervisorClass(instance.hypervisor)
  # beparams and hvparams are passed separately, to avoid editing the
  # instance and then saving the defaults in the instance itself.
  hvparams = cluster.FillHV(instance)
  beparams = cluster.FillBE(instance)
  console = hyper.GetInstanceConsole(instance, primary_node, node_group,
                                     hvparams, beparams)

  assert console.instance == instance.name
  console.Validate()

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
    self.instance = self.cfg.GetInstanceInfo(self.op.instance_uuid)
    assert self.instance is not None, \
      "Cannot retrieve locked instance %s" % self.op.instance_name
    CheckNodeOnline(self, self.instance.primary_node)

  def Exec(self, feedback_fn):
    """Connect to the console of an instance

    """
    node_uuid = self.instance.primary_node

    cluster_hvparams = self.cfg.GetClusterInfo().hvparams
    node_insts = self.rpc.call_instance_list(
                   [node_uuid], [self.instance.hypervisor],
                   cluster_hvparams)[node_uuid]
    node_insts.Raise("Can't get node information from %s" %
                     self.cfg.GetNodeName(node_uuid))

    if self.instance.name not in node_insts.payload:
      if self.instance.admin_state == constants.ADMINST_UP:
        state = constants.INSTST_ERRORDOWN
      elif self.instance.admin_state == constants.ADMINST_DOWN:
        state = constants.INSTST_ADMINDOWN
      else:
        state = constants.INSTST_ADMINOFFLINE
      raise errors.OpExecError("Instance %s is not running (state %s)" %
                               (self.instance.name, state))

    logging.debug("Connecting to console of %s on %s", self.instance.name,
                  self.cfg.GetNodeName(node_uuid))

    node = self.cfg.GetNodeInfo(self.instance.primary_node)
    group = self.cfg.GetNodeGroup(node.group)
    return GetInstanceConsole(self.cfg.GetClusterInfo(),
                              self.instance, node, group)
