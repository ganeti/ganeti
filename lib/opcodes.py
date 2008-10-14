#
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""OpCodes module

This module implements the data structures which define the cluster
operations - the so-called opcodes.

Every operation which modifies the cluster state is expressed via
opcodes.

"""

# this are practically structures, so disable the message about too
# few public methods:
# pylint: disable-msg=R0903


class BaseOpCode(object):
  """A simple serializable object.

  This object serves as a parent class for OpCode without any custom
  field handling.

  """
  __slots__ = []

  def __init__(self, **kwargs):
    """Constructor for BaseOpCode.

    The constructor takes only keyword arguments and will set
    attributes on this object based on the passed arguments. As such,
    it means that you should not pass arguments which are not in the
    __slots__ attribute for this class.

    """
    for key in kwargs:
      if key not in self.__slots__:
        raise TypeError("Object %s doesn't support the parameter '%s'" %
                        (self.__class__.__name__, key))
      setattr(self, key, kwargs[key])

  def __getstate__(self):
    """Generic serializer.

    This method just returns the contents of the instance as a
    dictionary.

    @rtype:  C{dict}
    @return: the instance attributes and their values

    """
    state = {}
    for name in self.__slots__:
      if hasattr(self, name):
        state[name] = getattr(self, name)
    return state

  def __setstate__(self, state):
    """Generic unserializer.

    This method just restores from the serialized state the attributes
    of the current instance.

    @param state: the serialized opcode data
    @type state:  C{dict}

    """
    if not isinstance(state, dict):
      raise ValueError("Invalid data to __setstate__: expected dict, got %s" %
                       type(state))

    for name in self.__slots__:
      if name not in state:
        delattr(self, name)

    for name in state:
      setattr(self, name, state[name])


class OpCode(BaseOpCode):
  """Abstract OpCode.

  This is the root of the actual OpCode hierarchy. All clases derived
  from this class should override OP_ID.

  @cvar OP_ID: The ID of this opcode. This should be unique amongst all
               childre of this class.

  """
  OP_ID = "OP_ABSTRACT"
  __slots__ = []

  def __getstate__(self):
    """Specialized getstate for opcodes.

    This method adds to the state dictionary the OP_ID of the class,
    so that on unload we can identify the correct class for
    instantiating the opcode.

    @rtype:   C{dict}
    @return:  the state as a dictionary

    """
    data = BaseOpCode.__getstate__(self)
    data["OP_ID"] = self.OP_ID
    return data

  @classmethod
  def LoadOpCode(cls, data):
    """Generic load opcode method.

    The method identifies the correct opcode class from the dict-form
    by looking for a OP_ID key, if this is not found, or its value is
    not available in this module as a child of this class, we fail.

    @type data:  C{dict}
    @param data: the serialized opcode

    """
    if not isinstance(data, dict):
      raise ValueError("Invalid data to LoadOpCode (%s)" % type(data))
    if "OP_ID" not in data:
      raise ValueError("Invalid data to LoadOpcode, missing OP_ID")
    op_id = data["OP_ID"]
    op_class = None
    for item in globals().values():
      if (isinstance(item, type) and
          issubclass(item, cls) and
          hasattr(item, "OP_ID") and
          getattr(item, "OP_ID") == op_id):
        op_class = item
        break
    if op_class is None:
      raise ValueError("Invalid data to LoadOpCode: OP_ID %s unsupported" %
                       op_id)
    op = op_class()
    new_data = data.copy()
    del new_data["OP_ID"]
    op.__setstate__(new_data)
    return op

  def Summary(self):
    """Generates a summary description of this opcode.

    """
    # all OP_ID start with OP_, we remove that
    txt = self.OP_ID[3:]
    field_name = getattr(self, "OP_DSC_FIELD", None)
    if field_name:
      field_value = getattr(self, field_name, None)
      txt = "%s(%s)" % (txt, field_value)
    return txt


class OpDestroyCluster(OpCode):
  """Destroy the cluster.

  This opcode has no other parameters. All the state is irreversibly
  lost after the execution of this opcode.

  """
  OP_ID = "OP_CLUSTER_DESTROY"
  __slots__ = []


class OpQueryClusterInfo(OpCode):
  """Query cluster information."""
  OP_ID = "OP_CLUSTER_QUERY"
  __slots__ = []


class OpVerifyCluster(OpCode):
  """Verify the cluster state.

  @type skip_checks: C{list}
  @ivar skip_checks: steps to be skipped from the verify process; this
                     needs to be a subset of
                     L{constants.VERIFY_OPTIONAL_CHECKS}; currently
                     only L{constants.VERIFY_NPLUSONE_MEM} can be passed

  """
  OP_ID = "OP_CLUSTER_VERIFY"
  __slots__ = ["skip_checks"]


class OpVerifyDisks(OpCode):
  """Verify the cluster disks.

  Parameters: none

  Result: a tuple of four elements:
    - list of node names with bad data returned (unreachable, etc.)
    - dict of node names with broken volume groups (values: error msg)
    - list of instances with degraded disks (that should be activated)
    - dict of instances with missing logical volumes (values: (node, vol)
      pairs with details about the missing volumes)

  In normal operation, all lists should be empty. A non-empty instance
  list (3rd element of the result) is still ok (errors were fixed) but
  non-empty node list means some node is down, and probably there are
  unfixable drbd errors.

  Note that only instances that are drbd-based are taken into
  consideration. This might need to be revisited in the future.

  """
  OP_ID = "OP_CLUSTER_VERIFY_DISKS"
  __slots__ = []


class OpQueryConfigValues(OpCode):
  """Query cluster configuration values."""
  OP_ID = "OP_CLUSTER_CONFIG_QUERY"
  __slots__ = ["output_fields"]


class OpRenameCluster(OpCode):
  """Rename the cluster.

  @type name: C{str}
  @ivar name: The new name of the cluster. The name and/or the master IP
              address will be changed to match the new name and its IP
              address.

  """
  OP_ID = "OP_CLUSTER_RENAME"
  OP_DSC_FIELD = "name"
  __slots__ = ["name"]


class OpSetClusterParams(OpCode):
  """Change the parameters of the cluster.

  @type vg_name: C{str} or C{None}
  @ivar vg_name: The new volume group name or None to disable LVM usage.

  """
  OP_ID = "OP_CLUSTER_SET_PARAMS"
  __slots__ = ["vg_name"]


# node opcodes

class OpRemoveNode(OpCode):
  """Remove a node.

  @type node_name: C{str}
  @ivar node_name: The name of the node to remove. If the node still has
                   instances on it, the operation will fail.

  """
  OP_ID = "OP_NODE_REMOVE"
  OP_DSC_FIELD = "node_name"
  __slots__ = ["node_name"]


class OpAddNode(OpCode):
  """Add a node to the cluster.

  @type node_name: C{str}
  @ivar node_name: The name of the node to add. This can be a short name,
                   but it will be expanded to the FQDN.
  @type primary_ip: IP address
  @ivar primary_ip: The primary IP of the node. This will be ignored when the
                    opcode is submitted, but will be filled during the node
                    add (so it will be visible in the job query).
  @type secondary_ip: IP address
  @ivar secondary_ip: The secondary IP of the node. This needs to be passed
                      if the cluster has been initialized in 'dual-network'
                      mode, otherwise it must not be given.
  @type readd: C{bool}
  @ivar readd: Whether to re-add an existing node to the cluster. If
               this is not passed, then the operation will abort if the node
               name is already in the cluster; use this parameter to 'repair'
               a node that had its configuration broken, or was reinstalled
               without removal from the cluster.

  """
  OP_ID = "OP_NODE_ADD"
  OP_DSC_FIELD = "node_name"
  __slots__ = ["node_name", "primary_ip", "secondary_ip", "readd"]


class OpQueryNodes(OpCode):
  """Compute the list of nodes."""
  OP_ID = "OP_NODE_QUERY"
  __slots__ = ["output_fields", "names"]


class OpQueryNodeVolumes(OpCode):
  """Get list of volumes on node."""
  OP_ID = "OP_NODE_QUERYVOLS"
  __slots__ = ["nodes", "output_fields"]


# instance opcodes

class OpCreateInstance(OpCode):
  """Create an instance."""
  OP_ID = "OP_INSTANCE_CREATE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "disk_size", "os_type", "pnode",
    "disk_template", "snode", "swap_size", "mode",
    "ip", "bridge", "src_node", "src_path", "start",
    "wait_for_sync", "ip_check", "mac",
    "file_storage_dir", "file_driver",
    "iallocator",
    "hypervisor", "hvparams", "beparams",
    ]


class OpReinstallInstance(OpCode):
  """Reinstall an instance's OS."""
  OP_ID = "OP_INSTANCE_REINSTALL"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "os_type"]


class OpRemoveInstance(OpCode):
  """Remove an instance."""
  OP_ID = "OP_INSTANCE_REMOVE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "ignore_failures"]


class OpRenameInstance(OpCode):
  """Rename an instance."""
  OP_ID = "OP_INSTANCE_RENAME"
  __slots__ = ["instance_name", "ignore_ip", "new_name"]


class OpStartupInstance(OpCode):
  """Startup an instance."""
  OP_ID = "OP_INSTANCE_STARTUP"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "force", "extra_args"]


class OpShutdownInstance(OpCode):
  """Shutdown an instance."""
  OP_ID = "OP_INSTANCE_SHUTDOWN"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


class OpRebootInstance(OpCode):
  """Reboot an instance."""
  OP_ID = "OP_INSTANCE_REBOOT"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "reboot_type", "extra_args",
               "ignore_secondaries" ]


class OpReplaceDisks(OpCode):
  """Replace the disks of an instance."""
  OP_ID = "OP_INSTANCE_REPLACE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "remote_node", "mode", "disks", "iallocator"]


class OpFailoverInstance(OpCode):
  """Failover an instance."""
  OP_ID = "OP_INSTANCE_FAILOVER"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "ignore_consistency"]


class OpConnectConsole(OpCode):
  """Connect to an instance's console."""
  OP_ID = "OP_INSTANCE_CONSOLE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


class OpActivateInstanceDisks(OpCode):
  """Activate an instance's disks."""
  OP_ID = "OP_INSTANCE_ACTIVATE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


class OpDeactivateInstanceDisks(OpCode):
  """Deactivate an instance's disks."""
  OP_ID = "OP_INSTANCE_DEACTIVATE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


class OpQueryInstances(OpCode):
  """Compute the list of instances."""
  OP_ID = "OP_INSTANCE_QUERY"
  __slots__ = ["output_fields", "names"]


class OpQueryInstanceData(OpCode):
  """Compute the run-time status of instances."""
  OP_ID = "OP_INSTANCE_QUERY_DATA"
  __slots__ = ["instances", "static"]


class OpSetInstanceParams(OpCode):
  """Change the parameters of an instance."""
  OP_ID = "OP_INSTANCE_SET_PARAMS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "ip", "bridge", "mac",
    "hvparams", "beparams", "force",
    ]


class OpGrowDisk(OpCode):
  """Grow a disk of an instance."""
  OP_ID = "OP_INSTANCE_GROW_DISK"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "disk", "amount"]


# OS opcodes
class OpDiagnoseOS(OpCode):
  """Compute the list of guest operating systems."""
  OP_ID = "OP_OS_DIAGNOSE"
  __slots__ = ["output_fields", "names"]


# Exports opcodes
class OpQueryExports(OpCode):
  """Compute the list of exported images."""
  OP_ID = "OP_BACKUP_QUERY"
  __slots__ = ["nodes"]


class OpExportInstance(OpCode):
  """Export an instance."""
  OP_ID = "OP_BACKUP_EXPORT"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "target_node", "shutdown"]


class OpRemoveExport(OpCode):
  """Remove an instance's export."""
  OP_ID = "OP_BACKUP_REMOVE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


# Tags opcodes
class OpGetTags(OpCode):
  """Returns the tags of the given object."""
  OP_ID = "OP_TAGS_GET"
  OP_DSC_FIELD = "name"
  __slots__ = ["kind", "name"]


class OpSearchTags(OpCode):
  """Searches the tags in the cluster for a given pattern."""
  OP_ID = "OP_TAGS_SEARCH"
  OP_DSC_FIELD = "pattern"
  __slots__ = ["pattern"]


class OpAddTags(OpCode):
  """Add a list of tags on a given object."""
  OP_ID = "OP_TAGS_SET"
  __slots__ = ["kind", "name", "tags"]


class OpDelTags(OpCode):
  """Remove a list of tags from a given object."""
  OP_ID = "OP_TAGS_DEL"
  __slots__ = ["kind", "name", "tags"]


# Test opcodes
class OpTestDelay(OpCode):
  """Sleeps for a configured amount of time.

  This is used just for debugging and testing.

  Parameters:
    - duration: the time to sleep
    - on_master: if true, sleep on the master
    - on_nodes: list of nodes in which to sleep

  If the on_master parameter is true, it will execute a sleep on the
  master (before any node sleep).

  If the on_nodes list is not empty, it will sleep on those nodes
  (after the sleep on the master, if that is enabled).

  As an additional feature, the case of duration < 0 will be reported
  as an execution error, so this opcode can be used as a failure
  generator. The case of duration == 0 will not be treated specially.

  """
  OP_ID = "OP_TEST_DELAY"
  OP_DSC_FIELD = "duration"
  __slots__ = ["duration", "on_master", "on_nodes"]


class OpTestAllocator(OpCode):
  """Allocator framework testing.

  This opcode has two modes:
    - gather and return allocator input for a given mode (allocate new
      or replace secondary) and a given instance definition (direction
      'in')
    - run a selected allocator for a given operation (as above) and
      return the allocator output (direction 'out')

  """
  OP_ID = "OP_TEST_ALLOCATOR"
  OP_DSC_FIELD = "allocator"
  __slots__ = [
    "direction", "mode", "allocator", "name",
    "mem_size", "disks", "disk_template",
    "os", "tags", "nics", "vcpus",
    ]
