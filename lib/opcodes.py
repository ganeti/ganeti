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


This module implements the logic for doing operations in the cluster. There
are two kinds of classes defined:
  - opcodes, which are small classes only holding data for the task at hand
  - logical units, which know how to deal with their specific opcode only

"""

# this are practically structures, so disable the message about too
# few public methods:
# pylint: disable-msg=R0903


class BaseJO(object):
  """A simple serializable object.

  This object serves as a parent class for both OpCode and Job since
  they are serialized in the same way.

  """
  __slots__ = []

  def __init__(self, **kwargs):
    for key in kwargs:
      if key not in self.__slots__:
        raise TypeError("Object %s doesn't support the parameter '%s'" %
                        (self.__class__.__name__, key))
      setattr(self, key, kwargs[key])

  def __getstate__(self):
    state = {}
    for name in self.__slots__:
      if hasattr(self, name):
        state[name] = getattr(self, name)
    return state

  def __setstate__(self, state):
    if not isinstance(state, dict):
      raise ValueError("Invalid data to __setstate__: expected dict, got %s" %
                       type(state))

    for name in self.__slots__:
      if name not in state:
        delattr(self, name)

    for name in state:
      setattr(self, name, state[name])


class Job(BaseJO):
  """Job definition structure"""
  STATUS_PENDING = 1
  STATUS_RUNNING = 2
  STATUS_FINISHED = 3
  RESULT_OK = 1
  RESULT_FAIL = 2
  RESULT_ABORT = 3

  __slots__ = ["job_id", "op_list", "status", "result"]

  def __getstate__(self):
    """Specialized getstate for jobs

    """
    data = BaseJO.__getstate__(self)
    if "op_list" in data:
      data["op_list"] = [op.__getstate__() for op in data["op_list"]]
    return data

  def __setstate__(self, state):
    """Specialized setstate for jobs

    """
    BaseJO.__setstate__(self, state)
    if "op_list" in state:
      self.op_list = [OpCode.LoadOpcode(op) for op in state["op_list"]]


class OpCode(BaseJO):
  """Abstract OpCode"""
  OP_ID = "OP_ABSTRACT"
  __slots__ = []

  def __getstate__(self):
    """Specialized getstate for opcodes.

    """
    data = BaseJO.__getstate__(self)
    data["OP_ID"] = self.OP_ID
    return data

  @classmethod
  def LoadOpcode(cls, data):
    """Generic load opcode method.

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


class OpInitCluster(OpCode):
  """Initialise the cluster."""
  OP_ID = "OP_CLUSTER_INIT"
  __slots__ = ["cluster_name", "secondary_ip", "hypervisor_type",
               "vg_name", "mac_prefix", "def_bridge", "master_netdev",
               "file_storage_dir"]


class OpDestroyCluster(OpCode):
  """Destroy the cluster."""
  OP_ID = "OP_CLUSTER_DESTROY"
  __slots__ = []


class OpQueryClusterInfo(OpCode):
  """Query cluster information."""
  OP_ID = "OP_CLUSTER_QUERY"
  __slots__ = []


class OpClusterCopyFile(OpCode):
  """Copy a file to multiple nodes."""
  OP_ID = "OP_CLUSTER_COPYFILE"
  __slots__ = ["nodes", "filename"]


class OpRunClusterCommand(OpCode):
  """Run a command on multiple nodes."""
  OP_ID = "OP_CLUSTER_RUNCOMMAND"
  __slots__ = ["nodes", "command"]


class OpVerifyCluster(OpCode):
  """Verify the cluster state."""
  OP_ID = "OP_CLUSTER_VERIFY"
  __slots__ = []


class OpVerifyDisks(OpCode):
  """Verify the cluster disks.

  Parameters: none

  Result: two lists:
    - list of node names with bad data returned (unreachable, etc.)
    - dist of node names with broken volume groups (values: error msg)
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


class OpMasterFailover(OpCode):
  """Do a master failover."""
  OP_ID = "OP_CLUSTER_MASTERFAILOVER"
  __slots__ = []


class OpDumpClusterConfig(OpCode):
  """Dump the cluster configuration."""
  OP_ID = "OP_CLUSTER_DUMPCONFIG"
  __slots__ = []


class OpRenameCluster(OpCode):
  """Rename the cluster."""
  OP_ID = "OP_CLUSTER_RENAME"
  __slots__ = ["name"]


class OpSetClusterParams(OpCode):
  """Change the parameters of the cluster."""
  OP_ID = "OP_CLUSTER_SET_PARAMS"
  __slots__ = ["vg_name"]


# node opcodes

class OpRemoveNode(OpCode):
  """Remove a node."""
  OP_ID = "OP_NODE_REMOVE"
  __slots__ = ["node_name"]


class OpAddNode(OpCode):
  """Add a node."""
  OP_ID = "OP_NODE_ADD"
  __slots__ = ["node_name", "primary_ip", "secondary_ip"]


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
  __slots__ = [
    "instance_name", "mem_size", "disk_size", "os_type", "pnode",
    "disk_template", "snode", "swap_size", "mode",
    "vcpus", "ip", "bridge", "src_node", "src_path", "start",
    "wait_for_sync", "ip_check", "mac",
    "kernel_path", "initrd_path", "hvm_boot_order",
    ]


class OpReinstallInstance(OpCode):
  """Reinstall an instance's OS."""
  OP_ID = "OP_INSTANCE_REINSTALL"
  __slots__ = ["instance_name", "os_type"]


class OpRemoveInstance(OpCode):
  """Remove an instance."""
  OP_ID = "OP_INSTANCE_REMOVE"
  __slots__ = ["instance_name", "ignore_failures"]


class OpRenameInstance(OpCode):
  """Rename an instance."""
  OP_ID = "OP_INSTANCE_RENAME"
  __slots__ = ["instance_name", "ignore_ip", "new_name"]


class OpStartupInstance(OpCode):
  """Startup an instance."""
  OP_ID = "OP_INSTANCE_STARTUP"
  __slots__ = ["instance_name", "force", "extra_args"]


class OpShutdownInstance(OpCode):
  """Shutdown an instance."""
  OP_ID = "OP_INSTANCE_SHUTDOWN"
  __slots__ = ["instance_name"]


class OpRebootInstance(OpCode):
  """Reboot an instance."""
  OP_ID = "OP_INSTANCE_REBOOT"
  __slots__ = ["instance_name", "reboot_type", "extra_args",
               "ignore_secondaries" ]


class OpReplaceDisks(OpCode):
  """Replace the disks of an instance."""
  OP_ID = "OP_INSTANCE_REPLACE_DISKS"
  __slots__ = ["instance_name", "remote_node", "mode", "disks"]


class OpFailoverInstance(OpCode):
  """Failover an instance."""
  OP_ID = "OP_INSTANCE_FAILOVER"
  __slots__ = ["instance_name", "ignore_consistency"]


class OpConnectConsole(OpCode):
  """Connect to an instance's console."""
  OP_ID = "OP_INSTANCE_CONSOLE"
  __slots__ = ["instance_name"]


class OpActivateInstanceDisks(OpCode):
  """Activate an instance's disks."""
  OP_ID = "OP_INSTANCE_ACTIVATE_DISKS"
  __slots__ = ["instance_name"]


class OpDeactivateInstanceDisks(OpCode):
  """Deactivate an instance's disks."""
  OP_ID = "OP_INSTANCE_DEACTIVATE_DISKS"
  __slots__ = ["instance_name"]


class OpQueryInstances(OpCode):
  """Compute the list of instances."""
  OP_ID = "OP_INSTANCE_QUERY"
  __slots__ = ["output_fields", "names"]


class OpQueryInstanceData(OpCode):
  """Compute the run-time status of instances."""
  OP_ID = "OP_INSTANCE_QUERY_DATA"
  __slots__ = ["instances"]


class OpSetInstanceParms(OpCode):
  """Change the parameters of an instance."""
  OP_ID = "OP_INSTANCE_SET_PARMS"
  __slots__ = [
    "instance_name", "mem", "vcpus", "ip", "bridge", "mac",
    "kernel_path", "initrd_path", "hvm_boot_order",
    ]


# OS opcodes
class OpDiagnoseOS(OpCode):
  """Compute the list of guest operating systems."""
  OP_ID = "OP_OS_DIAGNOSE"
  __slots__ = []


# Exports opcodes
class OpQueryExports(OpCode):
  """Compute the list of exported images."""
  OP_ID = "OP_BACKUP_QUERY"
  __slots__ = ["nodes"]


class OpExportInstance(OpCode):
  """Export an instance."""
  OP_ID = "OP_BACKUP_EXPORT"
  __slots__ = ["instance_name", "target_node", "shutdown"]


# Tags opcodes
class OpGetTags(OpCode):
  """Returns the tags of the given object."""
  OP_ID = "OP_TAGS_GET"
  __slots__ = ["kind", "name"]


class OpSearchTags(OpCode):
  """Searches the tags in the cluster for a given pattern."""
  OP_ID = "OP_TAGS_SEARCH"
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
  __slots__ = ["duration", "on_master", "on_nodes"]
