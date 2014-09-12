#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2013 Google Inc.
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


"""Chroot manager hypervisor

"""

import os
import os.path
import time
import logging

from ganeti import constants
from ganeti import errors # pylint: disable=W0611
from ganeti import utils
from ganeti import objects
from ganeti import pathutils
from ganeti.hypervisor import hv_base
from ganeti.errors import HypervisorError


class ChrootManager(hv_base.BaseHypervisor):
  """Chroot manager.

  This not-really hypervisor allows ganeti to manage chroots. It has
  special behaviour and requirements on the OS definition and the node
  environemnt:
    - the start and stop of the chroot environment are done via a
      script called ganeti-chroot located in the root directory of the
      first drive, which should be created by the OS definition
    - this script must accept the start and stop argument and, on
      shutdown, it should cleanly shutdown the daemons/processes
      using the chroot
    - the daemons run in chroot should only bind to the instance IP
      (to which the OS create script has access via the instance name)
    - since some daemons in the node could be listening on the wildcard
      address, some ports might be unavailable
    - the instance listing will show no memory usage
    - on shutdown, the chroot manager will try to find all mountpoints
      under the root dir of the instance and unmount them
    - instance alive check is based on whether any process is using the chroot

  """
  _ROOT_DIR = pathutils.RUN_DIR + "/chroot-hypervisor"

  PARAMETERS = {
    constants.HV_INIT_SCRIPT: (True, utils.IsNormAbsPath,
                               "must be an absolute normalized path",
                               None, None),
    }

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    utils.EnsureDirs([(self._ROOT_DIR, constants.RUN_DIRS_MODE)])

  @staticmethod
  def _IsDirLive(path):
    """Check if a directory looks like a live chroot.

    """
    if not os.path.ismount(path):
      return False
    result = utils.RunCmd(["fuser", "-m", path])
    return not result.failed

  @staticmethod
  def _GetMountSubdirs(path):
    """Return the list of mountpoints under a given path.

    """
    result = []
    for _, mountpoint, _, _ in utils.GetMounts():
      if (mountpoint.startswith(path) and
          mountpoint != path):
        result.append(mountpoint)

    result.sort(key=lambda x: x.count("/"), reverse=True)
    return result

  @classmethod
  def _InstanceDir(cls, instance_name):
    """Return the root directory for an instance.

    """
    return utils.PathJoin(cls._ROOT_DIR, instance_name)

  def ListInstances(self, hvparams=None):
    """Get the list of running instances.

    """
    return [name for name in os.listdir(self._ROOT_DIR)
            if self._IsDirLive(utils.PathJoin(self._ROOT_DIR, name))]

  def GetInstanceInfo(self, instance_name, hvparams=None):
    """Get instance properties.

    @type instance_name: string
    @param instance_name: the instance name
    @type hvparams: dict of strings
    @param hvparams: hvparams to be used with this instance

    @return: (name, id, memory, vcpus, stat, times)

    """
    dir_name = self._InstanceDir(instance_name)
    if not self._IsDirLive(dir_name):
      raise HypervisorError("Instance %s is not running" % instance_name)
    return (instance_name, 0, 0, 0, hv_base.HvInstanceState.RUNNING, 0)

  def GetAllInstancesInfo(self, hvparams=None):
    """Get properties of all instances.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameter
    @return: [(name, id, memory, vcpus, stat, times),...]

    """
    data = []
    for file_name in os.listdir(self._ROOT_DIR):
      path = utils.PathJoin(self._ROOT_DIR, file_name)
      if self._IsDirLive(path):
        data.append((file_name, 0, 0, 0, 0, 0))
    return data

  def StartInstance(self, instance, block_devices, startup_paused):
    """Start an instance.

    For the chroot manager, we try to mount the block device and
    execute '/ganeti-chroot start'.

    """
    root_dir = self._InstanceDir(instance.name)
    if not os.path.exists(root_dir):
      try:
        os.mkdir(root_dir)
      except IOError, err:
        raise HypervisorError("Failed to start instance %s: %s" %
                              (instance.name, err))
      if not os.path.isdir(root_dir):
        raise HypervisorError("Needed path %s is not a directory" % root_dir)

    if not os.path.ismount(root_dir):
      if not block_devices:
        raise HypervisorError("The chroot manager needs at least one disk")

      sda_dev_path = block_devices[0][1]
      result = utils.RunCmd(["mount", sda_dev_path, root_dir])
      if result.failed:
        raise HypervisorError("Can't mount the chroot dir: %s" % result.output)
    init_script = instance.hvparams[constants.HV_INIT_SCRIPT]
    result = utils.RunCmd(["chroot", root_dir, init_script, "start"])
    if result.failed:
      raise HypervisorError("Can't run the chroot start script: %s" %
                            result.output)

  def StopInstance(self, instance, force=False, retry=False, name=None,
                   timeout=None):
    """Stop an instance.

    This method has complicated cleanup tests, as we must:
      - try to kill all leftover processes
      - try to unmount any additional sub-mountpoints
      - finally unmount the instance dir

    """
    assert(timeout is None or force is not None)

    if name is None:
      name = instance.name

    root_dir = self._InstanceDir(name)
    if not os.path.exists(root_dir) or not self._IsDirLive(root_dir):
      return

    timeout_cmd = []
    if timeout is not None:
      timeout_cmd.extend(["timeout", str(timeout)])

    # Run the chroot stop script only once
    if not retry and not force:
      result = utils.RunCmd(timeout_cmd.extend(["chroot", root_dir,
                                                "/ganeti-chroot", "stop"]))
      if result.failed:
        raise HypervisorError("Can't run the chroot stop script: %s" %
                              result.output)

    if not force:
      utils.RunCmd(["fuser", "-k", "-TERM", "-m", root_dir])
    else:
      utils.RunCmd(["fuser", "-k", "-KILL", "-m", root_dir])
      # 2 seconds at most should be enough for KILL to take action
      time.sleep(2)

    if self._IsDirLive(root_dir):
      if force:
        raise HypervisorError("Can't stop the processes using the chroot")
      return

  def CleanupInstance(self, instance_name):
    """Cleanup after a stopped instance

    """
    root_dir = self._InstanceDir(instance_name)

    if not os.path.exists(root_dir):
      return

    if self._IsDirLive(root_dir):
      raise HypervisorError("Processes are still using the chroot")

    for mpath in self._GetMountSubdirs(root_dir):
      utils.RunCmd(["umount", mpath])

    result = utils.RunCmd(["umount", root_dir])
    if result.failed:
      msg = ("Processes still alive in the chroot: %s" %
             utils.RunCmd("fuser -vm %s" % root_dir).output)
      logging.error(msg)
      raise HypervisorError("Can't umount the chroot dir: %s (%s)" %
                            (result.output, msg))

  def RebootInstance(self, instance):
    """Reboot an instance.

    This is not (yet) implemented for the chroot manager.

    """
    raise HypervisorError("The chroot manager doesn't implement the"
                          " reboot functionality")

  def BalloonInstanceMemory(self, instance, mem):
    """Balloon an instance memory to a certain value.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type mem: int
    @param mem: actual memory size to use for instance runtime

    """
    # Currently chroots don't have memory limits
    pass

  def GetNodeInfo(self, hvparams=None):
    """Return information about the node.

    See L{BaseHypervisor.GetLinuxNodeInfo}.

    """
    return self.GetLinuxNodeInfo()

  @classmethod
  def GetInstanceConsole(cls, instance, primary_node, # pylint: disable=W0221
                         node_group, hvparams, beparams, root_dir=None):
    """Return information for connecting to the console of an instance.

    """
    if root_dir is None:
      root_dir = cls._InstanceDir(instance.name)
      if not os.path.ismount(root_dir):
        raise HypervisorError("Instance %s is not running" % instance.name)

    ndparams = node_group.FillND(primary_node)
    return objects.InstanceConsole(instance=instance.name,
                                   kind=constants.CONS_SSH,
                                   host=primary_node.name,
                                   port=ndparams.get(constants.ND_SSH_PORT),
                                   user=constants.SSH_CONSOLE_USER,
                                   command=["chroot", root_dir])

  def Verify(self, hvparams=None):
    """Verify the hypervisor.

    For the chroot manager, it just checks the existence of the base dir.

    @type hvparams: dict of strings
    @param hvparams: hypervisor parameters to be verified against, not used
      in for chroot

    @return: Problem description if something is wrong, C{None} otherwise

    """
    if os.path.exists(self._ROOT_DIR):
      return None
    else:
      return "The required directory '%s' does not exist" % self._ROOT_DIR

  @classmethod
  def PowercycleNode(cls, hvparams=None):
    """Chroot powercycle, just a wrapper over Linux powercycle.

    @type hvparams: dict of strings
    @param hvparams: hypervisor params to be used on this node

    """
    cls.LinuxPowercycle()

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
    raise HypervisorError("Migration not supported by the chroot hypervisor")

  def GetMigrationStatus(self, instance):
    """Get the migration status

    @type instance: L{objects.Instance}
    @param instance: the instance that is being migrated
    @rtype: L{objects.MigrationStatus}
    @return: the status of the current migration (one of
             L{constants.HV_MIGRATION_VALID_STATUSES}), plus any additional
             progress info that can be retrieved from the hypervisor

    """
    raise HypervisorError("Migration not supported by the chroot hypervisor")
