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

  def StartInstance(self, instance, block_devices):
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

    @type instance_name: string
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

  @classmethod
  def GetShellCommandForConsole(cls, instance, hvparams, beparams):
    """Return a command for connecting to the console of an instance.

    """
    raise NotImplementedError

  def Verify(self):
    """Verify the hypervisor.

    """
    raise NotImplementedError

  def MigrationInfo(self, instance):
    """Get instance information to perform a migration.

    By default assume no information is needed.

    @type instance: L{objects.Instance}
    @param instance: instance to be migrated
    @rtype: string/data (opaque)
    @return: instance migration information - serialized form

    """
    return ''

  def AcceptInstance(self, instance, info, target):
    """Prepare to accept an instance.

    By default assume no preparation is needed.

    @type instance: L{objects.Instance}
    @param instance: instance to be accepted
    @type info: string/data (opaque)
    @param info: migration information, from the source node
    @type target: string
    @param target: target host (usually ip), on this node

    """
    pass

  def FinalizeMigration(self, instance, info, success):
    """Finalized an instance migration.

    Should finalize or revert any preparation done to accept the instance.
    Since by default we do no preparation, we also don't have anything to do

    @type instance: L{objects.Instance}
    @param instance: instance whose migration is being aborted
    @type info: string/data (opaque)
    @param info: migration information, from the source node
    @type success: boolean
    @param success: whether the migration was a success or a failure

    """
    pass

  def MigrateInstance(self, name, target, live):
    """Migrate an instance.

    @type name: string
    @param name: name of the instance to be migrated
    @type target: string
    @param target: hostname (usually ip) of the target node
    @type live: boolean
    @param live: whether to do a live or non-live migration

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
