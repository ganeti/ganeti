#
#

# Copyright (C) 2006, 2007, 2008 Google Inc.
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


"""Fake hypervisor

"""

import os
import os.path
import re

from ganeti import utils
from ganeti import constants
from ganeti import errors
from ganeti.hypervisor import hv_base


class FakeHypervisor(hv_base.BaseHypervisor):
  """Fake hypervisor interface.

  This can be used for testing the ganeti code without having to have
  a real virtualisation software installed.

  """
  _ROOT_DIR = constants.RUN_DIR + "/ganeti-fake-hypervisor"

  def __init__(self):
    hv_base.BaseHypervisor.__init__(self)
    if not os.path.exists(self._ROOT_DIR):
      os.mkdir(self._ROOT_DIR)

  def ListInstances(self):
    """Get the list of running instances.

    """
    return os.listdir(self._ROOT_DIR)

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    @param instance_name: the instance name

    @return: tuple of (name, id, memory, vcpus, stat, times)

    """
    file_name = "%s/%s" % (self._ROOT_DIR, instance_name)
    if not os.path.exists(file_name):
      return None
    try:
      fh = open(file_name, "r")
      try:
        inst_id = fh.readline().strip()
        memory = utils.TryConvert(int, fh.readline().strip())
        vcpus = utils.TryConvert(fh.readline().strip())
        stat = "---b-"
        times = "0"
        return (instance_name, inst_id, memory, vcpus, stat, times)
      finally:
        fh.close()
    except IOError, err:
      raise errors.HypervisorError("Failed to list instance %s: %s" %
                                   (instance_name, err))

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    data = []
    for file_name in os.listdir(self._ROOT_DIR):
      try:
        fh = open(self._ROOT_DIR+"/"+file_name, "r")
        inst_id = "-1"
        memory = 0
        vcpus = 1
        stat = "-----"
        times = "-1"
        try:
          inst_id = fh.readline().strip()
          memory = utils.TryConvert(int, fh.readline().strip())
          vcpus = utils.TryConvert(int, fh.readline().strip())
          stat = "---b-"
          times = "0"
        finally:
          fh.close()
        data.append((file_name, inst_id, memory, vcpus, stat, times))
      except IOError, err:
        raise errors.HypervisorError("Failed to list instances: %s" % err)
    return data

  def StartInstance(self, instance, block_devices):
    """Start an instance.

    For the fake hypervisor, it just creates a file in the base dir,
    creating an exception if it already exists. We don't actually
    handle race conditions properly, since these are *FAKE* instances.

    """
    file_name = self._ROOT_DIR + "/%s" % instance.name
    if os.path.exists(file_name):
      raise errors.HypervisorError("Failed to start instance %s: %s" %
                                   (instance.name, "already running"))
    try:
      fh = file(file_name, "w")
      try:
        fh.write("0\n%d\n%d\n" %
                 (instance.beparams[constants.BE_MEMORY],
                  instance.beparams[constants.BE_VCPUS]))
      finally:
        fh.close()
    except IOError, err:
      raise errors.HypervisorError("Failed to start instance %s: %s" %
                                   (instance.name, err))

  def StopInstance(self, instance, force=False):
    """Stop an instance.

    For the fake hypervisor, this just removes the file in the base
    dir, if it exist, otherwise we raise an exception.

    """
    file_name = self._ROOT_DIR + "/%s" % instance.name
    if not os.path.exists(file_name):
      raise errors.HypervisorError("Failed to stop instance %s: %s" %
                                   (instance.name, "not running"))
    utils.RemoveFile(file_name)

  def RebootInstance(self, instance):
    """Reboot an instance.

    For the fake hypervisor, this does nothing.

    """
    return

  def GetNodeInfo(self):
    """Return information about the node.

    This is just a wrapper over the base GetLinuxNodeInfo method.

    @return: a dict with the following keys (values in MiB):
          - memory_total: the total memory size on the node
          - memory_free: the available memory on the node for instances
          - memory_dom0: the memory used by the node itself, if available

    """
    result = self.GetLinuxNodeInfo()
    # substract running instances
    all_instances = self.GetAllInstancesInfo()
    result['memory_free'] -= min(result['memory_free'],
                                 sum([row[2] for row in all_instances]))
    return result

  @classmethod
  def GetShellCommandForConsole(cls, instance, hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    return "echo Console not available for fake hypervisor"

  def Verify(self):
    """Verify the hypervisor.

    For the fake hypervisor, it just checks the existence of the base
    dir.

    """
    if not os.path.exists(self._ROOT_DIR):
      return "The required directory '%s' does not exist." % self._ROOT_DIR

  @classmethod
  def PowercycleNode(cls):
    """Fake hypervisor powercycle, just a wrapper over Linux powercycle.

    """
    cls.LinuxPowercycle()
