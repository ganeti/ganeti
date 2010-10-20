#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010 Google Inc.
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
    slots = self._all_slots()
    for key in kwargs:
      if key not in slots:
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
    for name in self._all_slots():
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

    for name in self._all_slots():
      if name not in state and hasattr(self, name):
        delattr(self, name)

    for name in state:
      setattr(self, name, state[name])

  @classmethod
  def _all_slots(cls):
    """Compute the list of all declared slots for a class.

    """
    slots = []
    for parent in cls.__mro__:
      slots.extend(getattr(parent, "__slots__", []))
    return slots


class OpCode(BaseOpCode):
  """Abstract OpCode.

  This is the root of the actual OpCode hierarchy. All clases derived
  from this class should override OP_ID.

  @cvar OP_ID: The ID of this opcode. This should be unique amongst all
               children of this class.
  @ivar dry_run: Whether the LU should be run in dry-run mode, i.e. just
                 the check steps
  @ivar priority: Opcode priority for queue

  """
  OP_ID = "OP_ABSTRACT"
  __slots__ = ["dry_run", "debug_level", "priority"]

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
    if op_id in OP_MAPPING:
      op_class = OP_MAPPING[op_id]
    else:
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
      if isinstance(field_value, (list, tuple)):
        field_value = ",".join(str(i) for i in field_value)
      txt = "%s(%s)" % (txt, field_value)
    return txt


# cluster opcodes

class OpPostInitCluster(OpCode):
  """Post cluster initialization.

  This opcode does not touch the cluster at all. Its purpose is to run hooks
  after the cluster has been initialized.

  """
  OP_ID = "OP_CLUSTER_POST_INIT"
  __slots__ = []


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
  __slots__ = ["skip_checks", "verbose", "error_codes",
               "debug_simulate_errors"]


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


class OpRepairDiskSizes(OpCode):
  """Verify the disk sizes of the instances and fixes configuration
  mimatches.

  Parameters: optional instances list, in case we want to restrict the
  checks to only a subset of the instances.

  Result: a list of tuples, (instance, disk, new-size) for changed
  configurations.

  In normal operation, the list should be empty.

  @type instances: list
  @ivar instances: the list of instances to check, or empty for all instances

  """
  OP_ID = "OP_CLUSTER_REPAIR_DISK_SIZES"
  __slots__ = ["instances"]


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
  __slots__ = [
    "vg_name",
    "drbd_helper",
    "enabled_hypervisors",
    "hvparams",
    "os_hvp",
    "beparams",
    "osparams",
    "nicparams",
    "candidate_pool_size",
    "maintain_node_health",
    "uid_pool",
    "add_uids",
    "remove_uids",
    "default_iallocator",
    "reserved_lvs",
    "hidden_os",
    "blacklisted_os",
    ]


class OpRedistributeConfig(OpCode):
  """Force a full push of the cluster configuration.

  """
  OP_ID = "OP_CLUSTER_REDIST_CONF"
  __slots__ = []

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
  __slots__ = ["node_name", "primary_ip", "secondary_ip", "readd", "nodegroup"]


class OpQueryNodes(OpCode):
  """Compute the list of nodes."""
  OP_ID = "OP_NODE_QUERY"
  __slots__ = ["output_fields", "names", "use_locking"]


class OpQueryNodeVolumes(OpCode):
  """Get list of volumes on node."""
  OP_ID = "OP_NODE_QUERYVOLS"
  __slots__ = ["nodes", "output_fields"]


class OpQueryNodeStorage(OpCode):
  """Get information on storage for node(s)."""
  OP_ID = "OP_NODE_QUERY_STORAGE"
  __slots__ = [
    "nodes",
    "storage_type",
    "name",
    "output_fields",
    ]


class OpModifyNodeStorage(OpCode):
  """Modifies the properies of a storage unit"""
  OP_ID = "OP_NODE_MODIFY_STORAGE"
  __slots__ = [
    "node_name",
    "storage_type",
    "name",
    "changes",
    ]


class OpRepairNodeStorage(OpCode):
  """Repairs the volume group on a node."""
  OP_ID = "OP_REPAIR_NODE_STORAGE"
  OP_DSC_FIELD = "node_name"
  __slots__ = [
    "node_name",
    "storage_type",
    "name",
    "ignore_consistency",
    ]


class OpSetNodeParams(OpCode):
  """Change the parameters of a node."""
  OP_ID = "OP_NODE_SET_PARAMS"
  OP_DSC_FIELD = "node_name"
  __slots__ = [
    "node_name",
    "force",
    "master_candidate",
    "offline",
    "drained",
    "auto_promote",
    ]


class OpPowercycleNode(OpCode):
  """Tries to powercycle a node."""
  OP_ID = "OP_NODE_POWERCYCLE"
  OP_DSC_FIELD = "node_name"
  __slots__ = [
    "node_name",
    "force",
    ]


class OpMigrateNode(OpCode):
  """Migrate all instances from a node."""
  OP_ID = "OP_NODE_MIGRATE"
  OP_DSC_FIELD = "node_name"
  __slots__ = [
    "node_name",
    "mode",
    "live",
    ]


class OpNodeEvacuationStrategy(OpCode):
  """Compute the evacuation strategy for a list of nodes."""
  OP_ID = "OP_NODE_EVAC_STRATEGY"
  OP_DSC_FIELD = "nodes"
  __slots__ = ["nodes", "iallocator", "remote_node"]


# instance opcodes

class OpCreateInstance(OpCode):
  """Create an instance.

  @ivar instance_name: Instance name
  @ivar mode: Instance creation mode (one of L{constants.INSTANCE_CREATE_MODES})
  @ivar source_handshake: Signed handshake from source (remote import only)
  @ivar source_x509_ca: Source X509 CA in PEM format (remote import only)
  @ivar source_instance_name: Previous name of instance (remote import only)

  """
  OP_ID = "OP_INSTANCE_CREATE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name",
    "os_type", "force_variant", "no_install",
    "pnode", "disk_template", "snode", "mode",
    "disks", "nics",
    "src_node", "src_path", "start", "identify_defaults",
    "wait_for_sync", "ip_check", "name_check",
    "file_storage_dir", "file_driver",
    "iallocator",
    "hypervisor", "hvparams", "beparams", "osparams",
    "source_handshake",
    "source_x509_ca",
    "source_instance_name",
    ]


class OpReinstallInstance(OpCode):
  """Reinstall an instance's OS."""
  OP_ID = "OP_INSTANCE_REINSTALL"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "os_type", "force_variant", "osparams"]


class OpRemoveInstance(OpCode):
  """Remove an instance."""
  OP_ID = "OP_INSTANCE_REMOVE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name",
    "ignore_failures",
    "shutdown_timeout",
    ]


class OpRenameInstance(OpCode):
  """Rename an instance."""
  OP_ID = "OP_INSTANCE_RENAME"
  __slots__ = [
    "instance_name", "ip_check", "new_name", "name_check",
    ]


class OpStartupInstance(OpCode):
  """Startup an instance."""
  OP_ID = "OP_INSTANCE_STARTUP"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "force", "hvparams", "beparams", "ignore_offline_nodes",
    ]


class OpShutdownInstance(OpCode):
  """Shutdown an instance."""
  OP_ID = "OP_INSTANCE_SHUTDOWN"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "timeout", "ignore_offline_nodes",
    ]


class OpRebootInstance(OpCode):
  """Reboot an instance."""
  OP_ID = "OP_INSTANCE_REBOOT"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "reboot_type", "ignore_secondaries", "shutdown_timeout",
    ]


class OpReplaceDisks(OpCode):
  """Replace the disks of an instance."""
  OP_ID = "OP_INSTANCE_REPLACE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "remote_node", "mode", "disks", "iallocator",
    "early_release",
    ]


class OpFailoverInstance(OpCode):
  """Failover an instance."""
  OP_ID = "OP_INSTANCE_FAILOVER"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "ignore_consistency", "shutdown_timeout",
    ]


class OpMigrateInstance(OpCode):
  """Migrate an instance.

  This migrates (without shutting down an instance) to its secondary
  node.

  @ivar instance_name: the name of the instance
  @ivar mode: the migration mode (live, non-live or None for auto)

  """
  OP_ID = "OP_INSTANCE_MIGRATE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "mode", "cleanup", "live"]


class OpMoveInstance(OpCode):
  """Move an instance.

  This move (with shutting down an instance and data copying) to an
  arbitrary node.

  @ivar instance_name: the name of the instance
  @ivar target_node: the destination node

  """
  OP_ID = "OP_INSTANCE_MOVE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "target_node", "shutdown_timeout",
    ]


class OpConnectConsole(OpCode):
  """Connect to an instance's console."""
  OP_ID = "OP_INSTANCE_CONSOLE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


class OpActivateInstanceDisks(OpCode):
  """Activate an instance's disks."""
  OP_ID = "OP_INSTANCE_ACTIVATE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "ignore_size"]


class OpDeactivateInstanceDisks(OpCode):
  """Deactivate an instance's disks."""
  OP_ID = "OP_INSTANCE_DEACTIVATE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name"]


class OpRecreateInstanceDisks(OpCode):
  """Deactivate an instance's disks."""
  OP_ID = "OP_INSTANCE_RECREATE_DISKS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = ["instance_name", "disks"]


class OpQueryInstances(OpCode):
  """Compute the list of instances."""
  OP_ID = "OP_INSTANCE_QUERY"
  __slots__ = ["output_fields", "names", "use_locking"]


class OpQueryInstanceData(OpCode):
  """Compute the run-time status of instances."""
  OP_ID = "OP_INSTANCE_QUERY_DATA"
  __slots__ = ["instances", "static"]


class OpSetInstanceParams(OpCode):
  """Change the parameters of an instance."""
  OP_ID = "OP_INSTANCE_SET_PARAMS"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name",
    "hvparams", "beparams", "osparams", "force",
    "nics", "disks", "disk_template",
    "remote_node", "os_name", "force_variant",
    ]


class OpGrowDisk(OpCode):
  """Grow a disk of an instance."""
  OP_ID = "OP_INSTANCE_GROW_DISK"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "disk", "amount", "wait_for_sync",
    ]


# OS opcodes
class OpDiagnoseOS(OpCode):
  """Compute the list of guest operating systems."""
  OP_ID = "OP_OS_DIAGNOSE"
  __slots__ = ["output_fields", "names"]


# Exports opcodes
class OpQueryExports(OpCode):
  """Compute the list of exported images."""
  OP_ID = "OP_BACKUP_QUERY"
  __slots__ = ["nodes", "use_locking"]


class OpPrepareExport(OpCode):
  """Prepares an instance export.

  @ivar instance_name: Instance name
  @ivar mode: Export mode (one of L{constants.EXPORT_MODES})

  """
  OP_ID = "OP_BACKUP_PREPARE"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    "instance_name", "mode",
    ]


class OpExportInstance(OpCode):
  """Export an instance.

  For local exports, the export destination is the node name. For remote
  exports, the export destination is a list of tuples, each consisting of
  hostname/IP address, port, HMAC and HMAC salt. The HMAC is calculated using
  the cluster domain secret over the value "${index}:${hostname}:${port}". The
  destination X509 CA must be a signed certificate.

  @ivar mode: Export mode (one of L{constants.EXPORT_MODES})
  @ivar target_node: Export destination
  @ivar x509_key_name: X509 key to use (remote export only)
  @ivar destination_x509_ca: Destination X509 CA in PEM format (remote export
                             only)

  """
  OP_ID = "OP_BACKUP_EXPORT"
  OP_DSC_FIELD = "instance_name"
  __slots__ = [
    # TODO: Rename target_node as it changes meaning for different export modes
    # (e.g. "destination")
    "instance_name", "target_node", "shutdown", "shutdown_timeout",
    "remove_instance",
    "ignore_remove_failures",
    "mode",
    "x509_key_name",
    "destination_x509_ca",
    ]


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
  __slots__ = ["duration", "on_master", "on_nodes", "repeat"]


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
    "os", "tags", "nics", "vcpus", "hypervisor",
    "evac_nodes",
    ]


class OpTestJobqueue(OpCode):
  """Utility opcode to test some aspects of the job queue.

  """
  OP_ID = "OP_TEST_JQUEUE"
  __slots__ = [
    "notify_waitlock",
    "notify_exec",
    "log_messages",
    "fail",
    ]


class OpTestDummy(OpCode):
  """Utility opcode used by unittests.

  """
  OP_ID = "OP_TEST_DUMMY"
  __slots__ = [
    "result",
    "messages",
    "fail",
    ]


OP_MAPPING = dict([(v.OP_ID, v) for v in globals().values()
                   if (isinstance(v, type) and issubclass(v, OpCode) and
                       hasattr(v, "OP_ID"))])
