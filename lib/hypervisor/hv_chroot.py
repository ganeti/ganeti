#
#

# Copyright (C) 2006, 2007, 2008, 2009 Google Inc.
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


"""Chroot manager hypervisor

"""

import os
import os.path
import time
import logging
from cStringIO import StringIO

from ganeti import constants
from ganeti import errors
from ganeti import utils
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
  _ROOT_DIR = constants.RUN_GANETI_DIR + "/chroot-hypervisor"

  PARAMETERS = {
    constants.HV_INIT_SCRIPT: (True, utils.IsNormAbsPath,
                               "must be an absolute normalized path",
                               None, None)
    }

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    if not os.path.exists(self._ROOT_DIR):
      os.mkdir(self._ROOT_DIR)
    if not os.path.isdir(self._ROOT_DIR):
      raise HypervisorError("Needed path %s is not a directory" %
                            self._ROOT_DIR)

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

    This function is Linux-specific.

    """
    #TODO(iustin): investigate and document non-linux options
    #(e.g. via mount output)
    data = []
    fh = open("/proc/mounts", "r")
    try:
      for line in fh:
        fstype, mountpoint, rest = line.split(" ", 2)
        if (mountpoint.startswith(path) and
            mountpoint != path):
          data.append(mountpoint)
    finally:
      fh.close()
    data.sort(key=lambda x: x.count("/"), reverse=True)
    return data

  def ListInstances(self):
    """Get the list of running instances.

    """
    return [name for name in os.listdir(self._ROOT_DIR)
            if self._IsDirLive(os.path.join(self._ROOT_DIR, name))]

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    Args:
      instance_name: the instance name

    Returns:
      (name, id, memory, vcpus, stat, times)
    """
    dir_name = "%s/%s" % (self._ROOT_DIR, instance_name)
    if not self._IsDirLive(dir_name):
      raise HypervisorError("Instance %s is not running" % instance_name)
    return (instance_name, 0, 0, 0, 0, 0)

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    Returns:
      [(name, id, memory, vcpus, stat, times),...]
    """
    data = []
    for file_name in os.listdir(self._ROOT_DIR):
      path = os.path.join(self._ROOT_DIR, file_name)
      if self._IsDirLive(path):
        data.append((file_name, 0, 0, 0, 0, 0))
    return data

  def StartInstance(self, instance, block_devices):
    """Start an instance.

    For the chroot manager, we try to mount the block device and
    execute '/ganeti-chroot start'.

    """
    root_dir = "%s/%s" % (self._ROOT_DIR, instance.name)
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

  def StopInstance(self, instance, force=False):
    """Stop an instance.

    This method has complicated cleanup tests, as we must:
      - try to kill all leftover processes
      - try to unmount any additional sub-mountpoints
      - finally unmount the instance dir

    """
    root_dir = "%s/%s" % (self._ROOT_DIR, instance.name)
    if not os.path.exists(root_dir):
      return

    if self._IsDirLive(root_dir):
      result = utils.RunCmd(["chroot", root_dir, "/ganeti-chroot", "stop"])
      if result.failed:
        raise HypervisorError("Can't run the chroot stop script: %s" %
                              result.output)
      retry = 20
      while not force and self._IsDirLive(root_dir) and retry > 0:
        time.sleep(1)
        retry -= 1
        if retry < 10:
          result = utils.RunCmd(["fuser", "-k", "-TERM", "-m", root_dir])
      retry = 5
      while force and self._IsDirLive(root_dir) and retry > 0:
        time.sleep(1)
        retry -= 1
        utils.RunCmd(["fuser", "-k", "-KILL", "-m", root_dir])
      if self._IsDirLive(root_dir):
        raise HypervisorError("Can't stop the processes using the chroot")
    for mpath in self._GetMountSubdirs(root_dir):
      utils.RunCmd(["umount", mpath])
    retry = 10
    while retry > 0:
      result = utils.RunCmd(["umount", root_dir])
      if not result.failed:
        break
      retry -= 1
      time.sleep(1)
    if result.failed:
      logging.error("Processes still alive in the chroot: %s",
                    utils.RunCmd("fuser -vm %s" % root_dir).output)
      raise HypervisorError("Can't umount the chroot dir: %s" % result.output)

  def RebootInstance(self, instance):
    """Reboot an instance.

    This is not (yet) implemented for the chroot manager.

    """
    raise HypervisorError("The chroot manager doesn't implement the"
                          " reboot functionality")

  def GetNodeInfo(self):
    """Return information about the node.

    This is just a wrapper over the base GetLinuxNodeInfo method.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available

    """
    return self.GetLinuxNodeInfo()

  @classmethod
  def GetShellCommandForConsole(cls, instance, hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    root_dir = "%s/%s" % (cls._ROOT_DIR, instance.name)
    if not os.path.ismount(root_dir):
      raise HypervisorError("Instance %s is not running" % instance.name)

    return "chroot %s" % root_dir

  def Verify(self):
    """Verify the hypervisor.

    For the chroot manager, it just checks the existence of the base
    dir.

    """
    if not os.path.exists(self._ROOT_DIR):
      return "The required directory '%s' does not exist." % self._ROOT_DIR
