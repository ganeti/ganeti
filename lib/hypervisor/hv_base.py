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

from ganeti import errors


class BaseHypervisor(object):
  """Abstract virtualisation technology interface

  The goal is that all aspects of the virtualisation technology are
  abstracted away from the rest of code.

  """
  PARAMETERS = []

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

    @param instance_name: the instance name

    @return: tuple (name, id, memory, vcpus, state, times)

    """
    raise NotImplementedError

  def GetAllInstancesInfo(self):
    """Get properties of all instances.

    @return: list of tuples (name, id, memory, vcpus, stat, times)

    """
    raise NotImplementedError

  def GetNodeInfo(self):
    """Return information about the node.

    @return: a dict with the following keys (values in MiB):
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

  def MigrateInstance(self, name, target, live):
    """Migrate an instance.

    Arguments:
      - name: the name of the instance
      - target: the target of the migration (usually will be IP and not name)
      - live: whether to do live migration or not

    Returns: none, errors will be signaled by exception.

    """
    raise NotImplementedError


  @classmethod
  def CheckParameterSyntax(cls, hvparams):
    """Check the given parameters for validity.

    This should check the passed set of parameters for
    validity. Classes should extend, not replace, this function.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    for key in hvparams:
      if key not in cls.PARAMETERS:
        raise errors.HypervisorError("Hypervisor parameter '%s'"
                                     " not supported" % key)
    for key in cls.PARAMETERS:
      if key not in hvparams:
        raise errors.HypervisorError("Hypervisor parameter '%s'"
                                     " missing" % key)

  def ValidateParameters(self, hvparams):
    """Check the given parameters for validity.

    This should check the passed set of parameters for
    validity. Classes should extend, not replace, this function.

    @type hvparams:  dict
    @param hvparams: dictionary with parameter names/value
    @raise errors.HypervisorError: when a parameter is not valid

    """
    pass
