#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012 Google Inc.
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

"""RPC definitions for communication between master and node daemons.

RPC definition fields:

  - Name as string
  - L{SINGLE} for single-node calls, L{MULTI} for multi-node
  - Name resolver option(s), can be callable receiving all arguments in a tuple
  - Timeout (e.g. L{constants.RPC_TMO_NORMAL}), or callback receiving all
    arguments in a tuple to calculate timeout
  - List of arguments as tuples

    - Name as string
    - Argument kind used for encoding/decoding
    - Description for docstring (can be C{None})

  - Custom body encoder (e.g. for preparing per-node bodies)
  - Return value wrapper (e.g. for deserializing into L{objects}-based objects)
  - Short call description for docstring

"""

from ganeti import constants
from ganeti import utils
from ganeti import objects


# Guidelines for choosing timeouts:
# - call used during watcher: timeout of 1min, constants.RPC_TMO_URGENT
# - trivial (but be sure it is trivial)
#     (e.g. reading a file): 5min, constants.RPC_TMO_FAST
# - other calls: 15 min, constants.RPC_TMO_NORMAL
# - special calls (instance add, etc.):
#     either constants.RPC_TMO_SLOW (1h) or huge timeouts

SINGLE = "single-node"
MULTI = "multi-node"

ACCEPT_OFFLINE_NODE = object()

# Constants for encoding/decoding
(ED_OBJECT_DICT,
 ED_OBJECT_DICT_LIST,
 ED_INST_DICT,
 ED_INST_DICT_HVP_BEP_DP,
 ED_NODE_TO_DISK_DICT_DP,
 ED_INST_DICT_OSP_DP,
 ED_IMPEXP_IO,
 ED_FILE_DETAILS,
 ED_FINALIZE_EXPORT_DISKS,
 ED_COMPRESS,
 ED_BLOCKDEV_RENAME,
 ED_DISKS_DICT_DP,
 ED_MULTI_DISKS_DICT_DP,
 ED_SINGLE_DISK_DICT_DP,
 ED_NIC_DICT,
 ED_DEVICE_DICT) = range(1, 17)


def _Prepare(calls):
  """Converts list of calls to dictionary.

  """
  return utils.SequenceToDict(calls)


def _MigrationStatusPostProc(result):
  """Post-processor for L{RpcRunner.call_instance_get_migration_status}.

  """
  if not result.fail_msg and result.payload is not None:
    result.payload = objects.MigrationStatus.FromDict(result.payload)
  return result


def _BlockdevFindPostProc(result):
  """Post-processor for L{rpc.node.RpcRunner.call_blockdev_find}.

  """
  if not result.fail_msg and result.payload is not None:
    result.payload = objects.BlockDevStatus.FromDict(result.payload)
  return result


def _BlockdevGetMirrorStatusPostProc(result):
  """Post-processor for call_blockdev_getmirrorstatus.

  """
  if not result.fail_msg:
    result.payload = map(objects.BlockDevStatus.FromDict, result.payload)
  return result


def _BlockdevGetMirrorStatusMultiPreProc(node, args):
  """Prepares the appropriate node values for blockdev_getmirrorstatus_multi.

  """
  # there should be only one argument to this RPC, already holding a
  # node->disks dictionary, we just need to extract the value for the
  # current node
  assert len(args) == 1
  return [args[0][node]]


def _BlockdevGetMirrorStatusMultiPostProc(result):
  """Post-processor for call_blockdev_getmirrorstatus_multi.

  """
  if not result.fail_msg:
    for idx, (success, status) in enumerate(result.payload):
      if success:
        result.payload[idx] = (success, objects.BlockDevStatus.FromDict(status))

  return result


def _NodeInfoPreProc(node, args):
  """Prepare the storage_units argument for node_info calls."""
  assert len(args) == 2
  # The storage_units argument is either a dictionary with one value for each
  # node, or a fixed value to be used for all the nodes
  if type(args[0]) is dict:
    return [args[0][node], args[1]]
  else:
    return args


def _OsGetPostProc(result):
  """Post-processor for L{rpc.node.RpcRunner.call_os_get}.

  """
  if not result.fail_msg and isinstance(result.payload, dict):
    result.payload = objects.OS.FromDict(result.payload)
  return result


def _ImpExpStatusPostProc(result):
  """Post-processor for import/export status.

  @rtype: Payload containing list of L{objects.ImportExportStatus} instances
  @return: Returns a list of the state of each named import/export or None if
           a status couldn't be retrieved

  """
  if not result.fail_msg:
    decoded = []

    for i in result.payload:
      if i is None:
        decoded.append(None)
        continue
      decoded.append(objects.ImportExportStatus.FromDict(i))

    result.payload = decoded

  return result


def _TestDelayTimeout((duration, )):
  """Calculate timeout for "test_delay" RPC.

  """
  return int(duration + 5)


_FILE_STORAGE_CALLS = [
  ("file_storage_dir_create", SINGLE, None, constants.RPC_TMO_FAST, [
    ("file_storage_dir", None, "File storage directory"),
    ], None, None, "Create the given file storage directory"),
  ("file_storage_dir_remove", SINGLE, None, constants.RPC_TMO_FAST, [
    ("file_storage_dir", None, "File storage directory"),
    ], None, None, "Remove the given file storage directory"),
  ("file_storage_dir_rename", SINGLE, None, constants.RPC_TMO_FAST, [
    ("old_file_storage_dir", None, "Old name"),
    ("new_file_storage_dir", None, "New name"),
    ], None, None, "Rename file storage directory"),
  ]

_STORAGE_CALLS = [
  ("storage_list", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("su_name", None, None),
    ("su_args", None, None),
    ("name", None, None),
    ("fields", None, None),
    ], None, None, "Get list of storage units"),
  ("storage_modify", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("su_name", None, None),
    ("su_args", None, None),
    ("name", None, None),
    ("changes", None, None),
    ], None, None, "Modify a storage unit"),
  ("storage_execute", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("su_name", None, None),
    ("su_args", None, None),
    ("name", None, None),
    ("op", None, None),
    ], None, None, "Executes an operation on a storage unit"),
  ]

_INSTANCE_CALLS = [
  ("instance_info", SINGLE, None, constants.RPC_TMO_URGENT, [
    ("instance", None, "Instance name"),
    ("hname", None, "Hypervisor type"),
    ("hvparams", None, "Hypervisor parameters"),
    ], None, None, "Returns information about a single instance"),
  ("all_instances_info", MULTI, None, constants.RPC_TMO_URGENT, [
    ("hypervisor_list", None, "Hypervisors to query for instances"),
    ("all_hvparams", None, "Dictionary mapping hypervisor names to hvparams"),
    ], None, None,
   "Returns information about all instances on the given nodes"),
  ("instance_list", MULTI, None, constants.RPC_TMO_URGENT, [
    ("hypervisor_list", None, "Hypervisors to query for instances"),
    ("hvparams", None, "Hvparams of all hypervisors"),
    ], None, None, "Returns the list of running instances on the given nodes"),
  ("instance_reboot", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("inst", ED_INST_DICT, "Instance object"),
    ("reboot_type", None, None),
    ("shutdown_timeout", None, None),
    ("reason", None, "The reason for the reboot"),
    ], None, None, "Returns the list of running instances on the given nodes"),
  ("instance_shutdown", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("timeout", None, None),
    ("reason", None, "The reason for the shutdown"),
    ], None, None, "Stops an instance"),
  ("instance_balloon_memory", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("memory", None, None),
    ], None, None, "Modify the amount of an instance's runtime memory"),
  ("instance_run_rename", SINGLE, None, constants.RPC_TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("old_name", None, None),
    ("debug", None, None),
    ], None, None, "Run the OS rename script for an instance"),
  ("instance_migratable", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], None, None, "Checks whether the given instance can be migrated"),
  ("migration_info", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], None, None,
    "Gather the information necessary to prepare an instance migration"),
  ("accept_instance", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("info", None, "Result for the call_migration_info call"),
    ("target", None, "Target hostname (usually an IP address)"),
    ], None, None, "Prepare a node to accept an instance"),
  ("instance_finalize_migration_dst", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("info", None, "Result for the call_migration_info call"),
    ("success", None, "Whether the migration was a success or failure"),
    ], None, None, "Finalize any target-node migration specific operation"),
  ("instance_migrate", SINGLE, None, constants.RPC_TMO_SLOW, [
    ("cluster_name", None, "Cluster name"),
    ("instance", ED_INST_DICT, "Instance object"),
    ("target", None, "Target node name"),
    ("live", None, "Whether the migration should be done live or not"),
    ], None, None, "Migrate an instance"),
  ("instance_finalize_migration_src", SINGLE, None, constants.RPC_TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("success", None, "Whether the migration succeeded or not"),
    ("live", None, "Whether the user requested a live migration or not"),
    ], None, None, "Finalize the instance migration on the source node"),
  ("instance_get_migration_status", SINGLE, None, constants.RPC_TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], None, _MigrationStatusPostProc, "Report migration status"),
  ("instance_start", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance_hvp_bep", ED_INST_DICT_HVP_BEP_DP, None),
    ("startup_paused", None, None),
    ("reason", None, "The reason for the startup"),
    ], None, None, "Starts an instance"),
  ("instance_os_add", SINGLE, None, constants.RPC_TMO_1DAY, [
    ("instance_osp", ED_INST_DICT_OSP_DP, None),
    ("reinstall", None, None),
    ("debug", None, None),
    ], None, None, "Starts an instance"),
  ("hotplug_device", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("action", None, "Hotplug Action"),
    ("dev_type", None, "Device type"),
    ("device", ED_DEVICE_DICT, "Device dict"),
    ("extra", None, "Extra info for device (dev_path for disk)"),
    ("seq", None, "Device seq"),
    ], None, None, "Hoplug a device to a running instance"),
  ("hotplug_supported", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], None, None, "Check if hotplug is supported"),
  ]

_IMPEXP_CALLS = [
  ("import_start", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("opts", ED_OBJECT_DICT, None),
    ("instance", ED_INST_DICT, None),
    ("component", None, None),
    ("dest", ED_IMPEXP_IO, "Import destination"),
    ], None, None, "Starts an import daemon"),
  ("export_start", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("opts", ED_OBJECT_DICT, None),
    ("host", None, None),
    ("port", None, None),
    ("instance", ED_INST_DICT, None),
    ("component", None, None),
    ("source", ED_IMPEXP_IO, "Export source"),
    ], None, None, "Starts an export daemon"),
  ("impexp_status", SINGLE, None, constants.RPC_TMO_FAST, [
    ("names", None, "Import/export names"),
    ], None, _ImpExpStatusPostProc, "Gets the status of an import or export"),
  ("impexp_abort", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("name", None, "Import/export name"),
    ], None, None, "Aborts an import or export"),
  ("impexp_cleanup", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("name", None, "Import/export name"),
    ], None, None, "Cleans up after an import or export"),
  ("export_info", SINGLE, None, constants.RPC_TMO_FAST, [
    ("path", None, None),
    ], None, None, "Queries the export information in a given path"),
  ("finalize_export", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance", ED_INST_DICT, None),
    ("snap_disks", ED_FINALIZE_EXPORT_DISKS, None),
    ], None, None, "Request the completion of an export operation"),
  ("export_list", MULTI, None, constants.RPC_TMO_FAST, [], None, None,
   "Gets the stored exports list"),
  ("export_remove", SINGLE, None, constants.RPC_TMO_FAST, [
    ("export", None, None),
    ], None, None, "Requests removal of a given export"),
  ]

_X509_CALLS = [
  ("x509_cert_create", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("validity", None, "Validity in seconds"),
    ], None, None, "Creates a new X509 certificate for SSL/TLS"),
  ("x509_cert_remove", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("name", None, "Certificate name"),
    ], None, None, "Removes a X509 certificate"),
  ]

_BLOCKDEV_CALLS = [
  ("bdev_sizes", MULTI, None, constants.RPC_TMO_URGENT, [
    ("devices", None, None),
    ], None, None,
   "Gets the sizes of requested block devices present on a node"),
  ("blockdev_create", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("bdev", ED_SINGLE_DISK_DICT_DP, None),
    ("size", None, None),
    ("owner", None, None),
    ("on_primary", None, None),
    ("info", None, None),
    ("exclusive_storage", None, None),
    ], None, None, "Request creation of a given block device"),
  ("blockdev_wipe", SINGLE, None, constants.RPC_TMO_SLOW, [
    ("bdev", ED_SINGLE_DISK_DICT_DP, None),
    ("offset", None, None),
    ("size", None, None),
    ], None, None,
    "Request wipe at given offset with given size of a block device"),
  ("blockdev_remove", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("bdev", ED_SINGLE_DISK_DICT_DP, None),
    ], None, None, "Request removal of a given block device"),
  ("blockdev_pause_resume_sync", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disks", ED_DISKS_DICT_DP, None),
    ("pause", None, None),
    ], None, None, "Request a pause/resume of given block device"),
  ("blockdev_assemble", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disk", ED_SINGLE_DISK_DICT_DP, None),
    ("owner", None, None),
    ("on_primary", None, None),
    ("idx", None, None),
    ], None, None, "Request assembling of a given block device"),
  ("blockdev_shutdown", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disk", ED_SINGLE_DISK_DICT_DP, None),
    ], None, None, "Request shutdown of a given block device"),
  ("blockdev_addchildren", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("bdev", ED_SINGLE_DISK_DICT_DP, None),
    ("ndevs", ED_DISKS_DICT_DP, None),
    ], None, None,
   "Request adding a list of children to a (mirroring) device"),
  ("blockdev_removechildren", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("bdev", ED_SINGLE_DISK_DICT_DP, None),
    ("ndevs", ED_DISKS_DICT_DP, None),
    ], None, None,
   "Request removing a list of children from a (mirroring) device"),
  ("blockdev_close", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("instance_name", None, None),
    ("disks", ED_DISKS_DICT_DP, None),
    ], None, None, "Closes the given block devices"),
  ("blockdev_getdimensions", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disks", ED_MULTI_DISKS_DICT_DP, None),
    ], None, None, "Returns size and spindles of the given disks"),
  ("drbd_disconnect_net", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("disks", ED_DISKS_DICT_DP, None),
    ], None, None,
   "Disconnects the network of the given drbd devices"),
  ("drbd_attach_net", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("disks", ED_DISKS_DICT_DP, None),
    ("instance_name", None, None),
    ("multimaster", None, None),
    ], None, None, "Connects the given DRBD devices"),
  ("drbd_wait_sync", MULTI, None, constants.RPC_TMO_SLOW, [
    ("disks", ED_DISKS_DICT_DP, None),
    ], None, None,
   "Waits for the synchronization of drbd devices is complete"),
  ("drbd_needs_activation", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disks", ED_MULTI_DISKS_DICT_DP, None),
    ], None, None,
   "Returns the drbd disks which need activation"),
  ("blockdev_grow", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("cf_bdev", ED_SINGLE_DISK_DICT_DP, None),
    ("amount", None, None),
    ("dryrun", None, None),
    ("backingstore", None, None),
    ("es_flag", None, None),
    ], None, None, "Request growing of the given block device by a"
   " given amount"),
  ("blockdev_snapshot", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("cf_bdev", ED_SINGLE_DISK_DICT_DP, None),
    ], None, None, "Export a given disk to another node"),
  ("blockdev_rename", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("devlist", ED_BLOCKDEV_RENAME, None),
    ], None, None, "Request rename of the given block devices"),
  ("blockdev_find", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disk", ED_SINGLE_DISK_DICT_DP, None),
    ], None, _BlockdevFindPostProc,
    "Request identification of a given block device"),
  ("blockdev_getmirrorstatus", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disks", ED_DISKS_DICT_DP, None),
    ], None, _BlockdevGetMirrorStatusPostProc,
    "Request status of a (mirroring) device"),
  ("blockdev_getmirrorstatus_multi", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("node_disks", ED_NODE_TO_DISK_DICT_DP, None),
    ], _BlockdevGetMirrorStatusMultiPreProc,
   _BlockdevGetMirrorStatusMultiPostProc,
    "Request status of (mirroring) devices from multiple nodes"),
  ("blockdev_setinfo", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("disk", ED_SINGLE_DISK_DICT_DP, None),
    ("info", None, None),
    ], None, None, "Sets metadata information on a given block device"),
  ]

_OS_CALLS = [
  ("os_diagnose", MULTI, None, constants.RPC_TMO_FAST, [], None, None,
   "Request a diagnose of OS definitions"),
  ("os_validate", MULTI, None, constants.RPC_TMO_FAST, [
    ("required", None, None),
    ("name", None, None),
    ("checks", None, None),
    ("params", None, None),
    ], None, None, "Run a validation routine for a given OS"),
  ("os_get", SINGLE, None, constants.RPC_TMO_FAST, [
    ("name", None, None),
    ], None, _OsGetPostProc, "Returns an OS definition"),
  ]

_EXTSTORAGE_CALLS = [
  ("extstorage_diagnose", MULTI, None, constants.RPC_TMO_FAST, [], None, None,
   "Request a diagnose of ExtStorage Providers"),
  ]

_NODE_CALLS = [
  ("node_has_ip_address", SINGLE, None, constants.RPC_TMO_FAST, [
    ("address", None, "IP address"),
    ], None, None, "Checks if a node has the given IP address"),
  ("node_info", MULTI, None, constants.RPC_TMO_URGENT, [
    ("storage_units", None,
     "List of tuples '<storage_type>,<key>,[<param>]' to ask for disk space"
     " information; the parameter list varies depending on the storage_type"),
    ("hv_specs", None,
     "List of hypervisor specification (name, hvparams) to ask for node "
     "information"),
    ], _NodeInfoPreProc, None, "Return node information"),
  ("node_verify", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("checkdict", None, "What to verify"),
    ("cluster_name", None, "Cluster name"),
    ("all_hvparams", None, "Dictionary mapping hypervisor names to hvparams"),
    ("node_groups", None, "node names mapped to their group uuids"),
    ("groups_cfg", None,
      "a dictionary mapping group uuids to their configuration"),
    ], None, None, "Request verification of given parameters"),
  ("node_volumes", MULTI, None, constants.RPC_TMO_FAST, [], None, None,
   "Gets all volumes on node(s)"),
  ("node_demote_from_mc", SINGLE, None, constants.RPC_TMO_FAST, [], None, None,
   "Demote a node from the master candidate role"),
  ("node_powercycle", SINGLE, ACCEPT_OFFLINE_NODE, constants.RPC_TMO_NORMAL, [
    ("hypervisor", None, "Hypervisor type"),
    ("hvparams", None, "Hypervisor parameters"),
    ], None, None, "Tries to powercycle a node"),
  ("node_configure_ovs", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("ovs_name", None, "Name of the OpenvSwitch to create"),
    ("ovs_link", None, "Link of the OpenvSwitch to the outside"),
    ], None, None, "This will create and setup the OpenvSwitch"),
  ]

_MISC_CALLS = [
  ("lv_list", MULTI, None, constants.RPC_TMO_URGENT, [
    ("vg_name", None, None),
    ], None, None, "Gets the logical volumes present in a given volume group"),
  ("vg_list", MULTI, None, constants.RPC_TMO_URGENT, [], None, None,
   "Gets the volume group list"),
  ("bridges_exist", SINGLE, None, constants.RPC_TMO_URGENT, [
    ("bridges_list", None, "Bridges which must be present on remote node"),
    ], None, None, "Checks if a node has all the bridges given"),
  ("etc_hosts_modify", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("mode", None,
     "Mode to operate; currently L{constants.ETC_HOSTS_ADD} or"
     " L{constants.ETC_HOSTS_REMOVE}"),
    ("name", None, "Hostname to be modified"),
    ("ip", None, "IP address (L{constants.ETC_HOSTS_ADD} only)"),
    ], None, None, "Modify hosts file with name"),
  ("drbd_helper", MULTI, None, constants.RPC_TMO_URGENT, [],
   None, None, "Gets DRBD helper"),
  ("restricted_command", MULTI, None, constants.RPC_TMO_SLOW, [
    ("cmd", None, "Command name"),
    ], None, None, "Runs restricted command"),
  ("run_oob", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("oob_program", None, None),
    ("command", None, None),
    ("remote_node", None, None),
    ("timeout", None, None),
    ], None, None, "Runs out-of-band command"),
  ("hooks_runner", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("hpath", None, None),
    ("phase", None, None),
    ("env", None, None),
    ], None, None, "Call the hooks runner"),
  ("iallocator_runner", SINGLE, None, constants.RPC_TMO_NORMAL, [
    ("name", None, "Iallocator name"),
    ("idata", None, "JSON-encoded input string"),
    ("default_iallocator_params", None, "Additional iallocator parameters"),
    ], None, None, "Call an iallocator on a remote node"),
  ("test_delay", MULTI, None, _TestDelayTimeout, [
    ("duration", None, None),
    ], None, None, "Sleep for a fixed time on given node(s)"),
  ("hypervisor_validate_params", MULTI, None, constants.RPC_TMO_NORMAL, [
    ("hvname", None, "Hypervisor name"),
    ("hvfull", None, "Parameters to be validated"),
    ], None, None, "Validate hypervisor params"),
  ("get_watcher_pause", SINGLE, None, constants.RPC_TMO_URGENT, [],
    None, None, "Get watcher pause end"),
  ("set_watcher_pause", MULTI, None, constants.RPC_TMO_URGENT, [
    ("until", None, None),
    ], None, None, "Set watcher pause end"),
  ]

CALLS = {
  "RpcClientDefault":
    _Prepare(_IMPEXP_CALLS + _X509_CALLS + _OS_CALLS + _NODE_CALLS +
             _FILE_STORAGE_CALLS + _MISC_CALLS + _INSTANCE_CALLS +
             _BLOCKDEV_CALLS + _STORAGE_CALLS + _EXTSTORAGE_CALLS),
  "RpcClientJobQueue": _Prepare([
    ("jobqueue_update", MULTI, None, constants.RPC_TMO_URGENT, [
      ("file_name", None, None),
      ("content", ED_COMPRESS, None),
      ], None, None, "Update job queue file"),
    ("jobqueue_purge", SINGLE, None, constants.RPC_TMO_NORMAL, [], None, None,
     "Purge job queue"),
    ("jobqueue_rename", MULTI, None, constants.RPC_TMO_URGENT, [
      ("rename", None, None),
      ], None, None, "Rename job queue file"),
    ("jobqueue_set_drain_flag", MULTI, None, constants.RPC_TMO_URGENT, [
      ("flag", None, None),
      ], None, None, "Set job queue drain flag"),
    ]),
  "RpcClientBootstrap": _Prepare([
    ("node_start_master_daemons", SINGLE, None, constants.RPC_TMO_FAST, [
      ("no_voting", None, None),
      ], None, None, "Starts master daemons on a node"),
    ("node_activate_master_ip", SINGLE, None, constants.RPC_TMO_FAST, [
      ("master_params", ED_OBJECT_DICT, "Network parameters of the master"),
      ("use_external_mip_script", None,
       "Whether to use the user-provided master IP address setup script"),
      ], None, None,
      "Activates master IP on a node"),
    ("node_stop_master", SINGLE, None, constants.RPC_TMO_FAST, [], None, None,
     "Deactivates master IP and stops master daemons on a node"),
    ("node_deactivate_master_ip", SINGLE, None, constants.RPC_TMO_FAST, [
      ("master_params", ED_OBJECT_DICT, "Network parameters of the master"),
      ("use_external_mip_script", None,
       "Whether to use the user-provided master IP address setup script"),
      ], None, None,
     "Deactivates master IP on a node"),
    ("node_change_master_netmask", SINGLE, None, constants.RPC_TMO_FAST, [
      ("old_netmask", None, "The old value of the netmask"),
      ("netmask", None, "The new value of the netmask"),
      ("master_ip", None, "The master IP"),
      ("master_netdev", None, "The master network device"),
      ], None, None, "Change master IP netmask"),
    ("node_leave_cluster", SINGLE, None, constants.RPC_TMO_NORMAL, [
      ("modify_ssh_setup", None, None),
      ], None, None,
     "Requests a node to clean the cluster information it has"),
    ("master_info", MULTI, None, constants.RPC_TMO_URGENT, [], None, None,
     "Query master info"),
    ]),
  "RpcClientDnsOnly": _Prepare([
    ("version", MULTI, ACCEPT_OFFLINE_NODE, constants.RPC_TMO_URGENT, [], None,
     None, "Query node version"),
    ("node_verify_light", MULTI, None, constants.RPC_TMO_NORMAL, [
      ("checkdict", None, "What to verify"),
      ("cluster_name", None, "Cluster name"),
      ("hvparams", None, "Dictionary mapping hypervisor names to hvparams"),
      ("node_groups", None, "node names mapped to their group uuids"),
      ("groups_cfg", None,
       "a dictionary mapping group uuids to their configuration"),
      ], None, None, "Request verification of given parameters"),
    ]),
  "RpcClientConfig": _Prepare([
    ("upload_file", MULTI, None, constants.RPC_TMO_NORMAL, [
      ("file_name", ED_FILE_DETAILS, None),
      ], None, None, "Upload a file"),
    ("write_ssconf_files", MULTI, None, constants.RPC_TMO_NORMAL, [
      ("values", None, None),
      ], None, None, "Write ssconf files"),
    ]),
  }
