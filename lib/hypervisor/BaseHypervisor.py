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


"""Base class for all hypervisors

"""

class BaseHypervisor(object):
  """Abstract virtualisation technology interface

  The goal is that all aspects of the virtualisation technology must
  be abstracted away from the rest of code.

  """
  def __init__(self):
    pass

  def StartInstance(self, instance, block_devices, extra_args):
    """Start an instance."""
    raise NotImplementedError

  def StopInstance(self, instance, force=False):
    """Stop an instance."""
    raise NotImplementedError

  def RebootInstance(self, instance):
    """Reboot an instance."""
    raise NotImplementedError

  def ListInstances(self):
    """Get the list of running instances."""
    raise NotImplementedError

  def GetInstanceInfo(self, instance_name):
    """Get instance properties.

    Args:
      instance_name: the instance name

    Returns:
      (name, id, memory, vcpus, state, times)

    """
    raise NotImplementedError

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    Returns:
      [(name, id, memory, vcpus, stat, times),...]
    """
    raise NotImplementedError

  def GetNodeInfo(self):
    """Return information about the node.

    The return value is a dict, which has to have the following items:
      (all values in MiB)
      - memory_total: the total memory size on the node
      - memory_free: the available memory on the node for instances
      - memory_dom0: the memory used by the node itself, if available

    """
    raise NotImplementedError

  @staticmethod
  def GetShellCommandForConsole(instance):
    """Return a command for connecting to the console of an instance.

    """
    raise NotImplementedError

  def Verify(self):
    """Verify the hypervisor.

    """
    raise NotImplementedError
