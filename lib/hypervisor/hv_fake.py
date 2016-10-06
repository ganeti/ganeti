#
#

# Copyright (C) 2006, 2007, 2008, 2013 Google Inc.
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


"""Fake hypervisor

"""

import os
import os.path
import logging

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti import objects
from ganeti import pathutils
from ganeti.hypervisor import hv_base


class FakeHypervisor(hv_base.BaseHypervisor):
  """Fake hypervisor interface.

  This can be used for testing the ganeti code without having to have
  a real virtualisation software installed.

  """
  PARAMETERS = {
    constants.HV_MIGRATION_MODE: hv_base.MIGRATION_MODE_CHECK,
    }

  CAN_MIGRATE = True

  _ROOT_DIR = pathutils.RUN_DIR + "/fake-hypervisor"

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    utils.EnsureDirs([(self._ROOT_DIR, constants.RUN_DIRS_MODE)])

  def ListInstances(self, hvparams=None):
    """Get the list of running instances.

    """
    return os.listdir(self._ROOT_DIR)

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: hvparams to be used with this instance

    @return: tuple of (name, id, memory, vcpus, stat, times)

    """
    file_name = self._InstanceFile(instance_name)
    if not os.path.exists(file_name):
      return None
    try:
      fh = open(file_name, "r")
      try:
        inst_id = fh.readline().strip()
        memory = utils.TryConvert(int, fh.readline().strip())
        vcpus = utils.TryConvert(int, fh.readline().strip())
        stat = hv_base.HvInstanceState.RUNNING
        times = 0
        return (instance_name, inst_id, memory, vcpus, stat, times)
      finally:
        fh.close()
    except IOError, err:
      raise errors.HypervisorError("Failed to list instance %s: %s" %
                                   (instance_name, err))

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameter
    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    data = []
    for file_name in os.listdir(self._ROOT_DIR):
      try:
        fh = open(utils.PathJoin(self._ROOT_DIR, file_name), "r")
        inst_id = "-1"
        memory = 0
        vcpus = 1
        stat = hv_base.HvInstanceState.SHUTDOWN
        times = -1
        try:
          inst_id = fh.readline().strip()
          memory = utils.TryConvert(int, fh.readline().strip())
          vcpus = utils.TryConvert(int, fh.readline().strip())
          stat = hv_base.HvInstanceState.RUNNING
          times = 0
        finally:
          fh.close()
        data.append((file_name, inst_id, memory, vcpus, stat, times))
      except IOError, err:
        raise errors.HypervisorError("Failed to list instances: %s" % err)
    return data

  @classmethod
  def _InstanceFile(cls, instance_name):
    """Compute the instance file for an instance name.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name)

  def _IsAlive(self, instance_name):
    """Checks if an instance is alive.

    """
    file_name = self._InstanceFile(instance_name)
    return os.path.exists(file_name)

  def _MarkUp(self, instance, memory):
    """Mark the instance as running.

    This does no checks, which should be done by its callers.

    """
    file_name = self._InstanceFile(instance.name)
    fh = file(file_name, "w")
    try:
      fh.write("0\n%d\n%d\n" %
               (memory,
                instance.beparams[constants.BE_VCPUS]))
    finally:
      fh.close()

  def _MarkDown(self, instance_name):
    """Mark the instance as running.

    This does no checks, which should be done by its callers.

    """
    file_name = self._InstanceFile(instance_name)
    utils.RemoveFile(file_name)

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    For the fake hypervisor, it just creates a file in the base dir,
    creating an exception if it already exists. We don't actually
    handle race conditions properly, since these are *FAKE* instances.

    """
    if self._IsAlive(instance.name):
      raise errors.HypervisorError("Failed to start instance %s: %s" %
                                   (instance.name, "already running"))
    try:
      self._MarkUp(instance, self._InstanceStartupMemory(instance))
    except IOError, err:
      raise errors.HypervisorError("Failed to start instance %s: %s" %
                                   (instance.name, err))

  def StopInstance(self, instance, force=False, retry=False, name=None,
                   timeout=None):
    """Stop an instance.

    For the fake hypervisor, this just removes the file in the base
    dir, if it exist, otherwise we raise an exception.

    """
    assert(timeout is None or force is not None)

    if name is None:
      name = instance.name
    if not self._IsAlive(name):
      raise errors.HypervisorError("Failed to stop instance %s: %s" %
                                   (name, "not running"))
    self._MarkDown(name)

  def RebootInstance(self, instance):
    """Reboot an instance.

    For the fake hypervisor, this does nothing.

    """
    return

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    if not self._IsAlive(instance.name):
      raise errors.HypervisorError("Failed to balloon memory for %s: %s" %
                                   (instance.name, "not running"))
    try:
      self._MarkUp(instance, mem)
    except EnvironmentError, err:
      raise errors.HypervisorError("Failed to balloon memory for %s: %s" %
                                   (instance.name, utils.ErrnoOrStr(err)))

  def GetNodeInfo(self, hvparams=None):
    """Return information about the node.

    See L{BaseHypervisor.GetLinuxNodeInfo}.

    """
    result = self.GetLinuxNodeInfo()
    # substract running instances
    all_instances = self.GetAllInstancesInfo()
    result["memory_free"] -= min(result["memory_free"],
                                 sum([row[2] for row in all_instances]))
    return result

  @classmethod
  def GetInstanceConsole(cls, instance, primary_node, node_group,
                         hvparams, beparams):
    """Return information for connecting to the console of an instance.

    """
    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_MESSAGE,
                                   message=("Console not available for fake"
                                            " hypervisor"))

  def Verify(self, hvparams=None):
    """Verify the hypervisor.

    For the fake hypervisor, it just checks the existence of the base
    dir.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be verified against; not used
      for fake hypervisors

    @return: Problem description if something is wrong, C{None} otherwise

    """
    if os.path.exists(self._ROOT_DIR):
      return None
    else:
      return "The required directory '%s' does not exist" % self._ROOT_DIR

  @classmethod
  def PowercycleNode(cls, hvparams=None):
    """Fake hypervisor powercycle, just a wrapper over Linux powercycle.

    @type hvparams: dict of strings
    @param hvparams: hypervisor params to be used on this node

    """
    cls.LinuxPowercycle()

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string
    @param info: instance info, not used
    @type target: string
    @param target: target host (usually ip), on this node

    """
    if self._IsAlive(instance.name):
      raise errors.HypervisorError("Can't accept instance, already running")

  def MigrateInstance(self, cluster_name, instance, target, live):
    """Migrate an instance.

    @type cluster_name: string
    @param cluster_name: name of the cluster
    @type instance: L{objects.Instance}
    @param instance: the instance to be migrated
    @type target: string
    @param target: hostname (usually ip) of the target node
    @type live: boolean
    @param live: whether to do a live or non-live migration

    """
    logging.debug("Fake hypervisor migrating %s to %s (live=%s)",
                  instance, target, live)

  def FinalizeMigrationDst(self, instance, info, success):
    """Finalize the instance migration on the target node.

    For the fake hv, this just marks the instance up.

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being finalized
    @type info: string/data (opaque)
    @param info: migration information, from the source node
    @type success: boolean
    @param success: whether the migration was a success or a failure

    """
    if success:
      self._MarkUp(instance, self._InstanceStartupMemory(instance))
    else:
      # ensure it's down
      self._MarkDown(instance.name)

  def FinalizeMigrationSource(self, instance, success, live):
    """Finalize the instance migration on the source node.

    @type instance: L{objects.Instance}
    @param instance: the instance that was migrated
    @type success: bool
    @param success: whether the migration succeeded or not
    @type live: bool
    @param live: whether the user requested a live migration or not

    """
    # pylint: disable=W0613
    if success:
      self._MarkDown(instance.name)

  def GetMigrationStatus(self, instance):
    """Get the migration status

    The fake hypervisor migration always succeeds.

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    return objects.MigrationStatus(status=constants.HV_MIGRATION_COMPLETED)
