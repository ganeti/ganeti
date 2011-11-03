#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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
  - Timeout (e.g. L{TMO_NORMAL})
  - List of arguments as tuples

    - Name as string
    - Argument kind used for encoding/decoding
    - Description for docstring (can be C{None})

  - Return value wrapper (e.g. for deserializing into L{objects}-based objects)
  - Short call description for docstring

"""

from ganeti import utils


# Guidelines for choosing timeouts:
# - call used during watcher: timeout of 1min, _TMO_URGENT
# - trivial (but be sure it is trivial) (e.g. reading a file): 5min, _TMO_FAST
# - other calls: 15 min, _TMO_NORMAL
# - special calls (instance add, etc.): either _TMO_SLOW (1h) or huge timeouts
TMO_URGENT = 60 # one minute
TMO_FAST = 5 * 60 # five minutes
TMO_NORMAL = 15 * 60 # 15 minutes
TMO_SLOW = 3600 # one hour
TMO_4HRS = 4 * 3600
TMO_1DAY = 86400

SINGLE = "single-node"
MULTI = "multi-node"

# Constants for encoding/decoding
(ED_OBJECT_DICT,
 ED_OBJECT_DICT_LIST,
 ED_INST_DICT,
 ED_INST_DICT_HVP_BEP,
 ED_NODE_TO_DISK_DICT,
 ED_INST_DICT_OSP,
 ED_IMPEXP_IO,
 ED_FILE_DETAILS,
 ED_FINALIZE_EXPORT_DISKS,
 ED_COMPRESS,
 ED_BLOCKDEV_RENAME) = range(1, 12)


def _Prepare(calls):
  """Converts list of calls to dictionary.

  """
  return utils.SequenceToDict(calls)


_FILE_STORAGE_CALLS = [
  ("file_storage_dir_create", SINGLE, TMO_FAST, [
    ("file_storage_dir", None, "File storage directory"),
    ], None, "Create the given file storage directory"),
  ("file_storage_dir_remove", SINGLE, TMO_FAST, [
    ("file_storage_dir", None, "File storage directory"),
    ], None, "Remove the given file storage directory"),
  ("file_storage_dir_rename", SINGLE, TMO_FAST, [
    ("old_file_storage_dir", None, "Old name"),
    ("new_file_storage_dir", None, "New name"),
    ], None, "Rename file storage directory"),
  ]

_STORAGE_CALLS = [
  ("storage_list", MULTI, TMO_NORMAL, [
    ("su_name", None, None),
    ("su_args", None, None),
    ("name", None, None),
    ("fields", None, None),
    ], None, "Get list of storage units"),
  ("storage_modify", SINGLE, TMO_NORMAL, [
    ("su_name", None, None),
    ("su_args", None, None),
    ("name", None, None),
    ("changes", None, None),
    ], None, "Modify a storage unit"),
  ("storage_execute", SINGLE, TMO_NORMAL, [
    ("su_name", None, None),
    ("su_args", None, None),
    ("name", None, None),
    ("op", None, None),
    ], None, "Executes an operation on a storage unit"),
  ]

_INSTANCE_CALLS = [
  ("instance_info", SINGLE, TMO_URGENT, [
    ("instance", None, "Instance name"),
    ("hname", None, "Hypervisor type"),
    ], None, "Returns information about a single instance"),
  ("all_instances_info", MULTI, TMO_URGENT, [
    ("hypervisor_list", None, "Hypervisors to query for instances"),
    ], None, "Returns information about all instances on the given nodes"),
  ("instance_list", MULTI, TMO_URGENT, [
    ("hypervisor_list", None, "Hypervisors to query for instances"),
    ], None, "Returns the list of running instances on the given nodes"),
  ("instance_reboot", SINGLE, TMO_NORMAL, [
    ("inst", ED_INST_DICT, "Instance object"),
    ("reboot_type", None, None),
    ("shutdown_timeout", None, None),
    ], None, "Returns the list of running instances on the given nodes"),
  ("instance_shutdown", SINGLE, TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("timeout", None, None),
    ], None, "Stops an instance"),
  ("instance_run_rename", SINGLE, TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("old_name", None, None),
    ("debug", None, None),
    ], None, "Run the OS rename script for an instance"),
  ("instance_migratable", SINGLE, TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], None, "Checks whether the given instance can be migrated"),
  ("migration_info", SINGLE, TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], None,
    "Gather the information necessary to prepare an instance migration"),
  ("accept_instance", SINGLE, TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("info", None, "Result for the call_migration_info call"),
    ("target", None, "Target hostname (usually an IP address)"),
    ], None, "Prepare a node to accept an instance"),
  ("instance_finalize_migration_dst", SINGLE, TMO_NORMAL, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("info", None, "Result for the call_migration_info call"),
    ("success", None, "Whether the migration was a success or failure"),
    ], None, "Finalize any target-node migration specific operation"),
  ("instance_migrate", SINGLE, TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("target", None, "Target node name"),
    ("live", None, "Whether the migration should be done live or not"),
    ], None, "Migrate an instance"),
  ("instance_finalize_migration_src", SINGLE, TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ("success", None, "Whether the migration succeeded or not"),
    ("live", None, "Whether the user requested a live migration or not"),
    ], None, "Finalize the instance migration on the source node"),
  ("instance_get_migration_status", SINGLE, TMO_SLOW, [
    ("instance", ED_INST_DICT, "Instance object"),
    ], "self._MigrationStatusPostProc", "Report migration status"),
  ("instance_start", SINGLE, TMO_NORMAL, [
    ("instance_hvp_bep", ED_INST_DICT_HVP_BEP, None),
    ("startup_paused", None, None),
    ], None, "Starts an instance"),
  ("instance_os_add", SINGLE, TMO_1DAY, [
    ("instance_osp", ED_INST_DICT_OSP, None),
    ("reinstall", None, None),
    ("debug", None, None),
    ], None, "Starts an instance"),
  ]

_IMPEXP_CALLS = [
  ("import_start", SINGLE, TMO_NORMAL, [
    ("opts", ED_OBJECT_DICT, None),
    ("instance", ED_INST_DICT, None),
    ("component", None, None),
    ("dest", ED_IMPEXP_IO, "Import destination"),
    ], None, "Starts an import daemon"),
  ("export_start", SINGLE, TMO_NORMAL, [
    ("opts", ED_OBJECT_DICT, None),
    ("host", None, None),
    ("port", None, None),
    ("instance", ED_INST_DICT, None),
    ("component", None, None),
    ("source", ED_IMPEXP_IO, "Export source"),
    ], None, "Starts an export daemon"),
  ("impexp_status", SINGLE, TMO_FAST, [
    ("names", None, "Import/export names"),
    ], "self._ImpExpStatusPostProc", "Gets the status of an import or export"),
  ("impexp_abort", SINGLE, TMO_NORMAL, [
    ("name", None, "Import/export name"),
    ], None, "Aborts an import or export"),
  ("impexp_cleanup", SINGLE, TMO_NORMAL, [
    ("name", None, "Import/export name"),
    ], None, "Cleans up after an import or export"),
  ("export_info", SINGLE, TMO_FAST, [
    ("path", None, None),
    ], None, "Queries the export information in a given path"),
  ("finalize_export", SINGLE, TMO_NORMAL, [
    ("instance", ED_INST_DICT, None),
    ("snap_disks", ED_FINALIZE_EXPORT_DISKS, None),
    ], None, "Request the completion of an export operation"),
  ("export_list", MULTI, TMO_FAST, [], None, "Gets the stored exports list"),
  ("export_remove", SINGLE, TMO_FAST, [
    ("export", None, None),
    ], None, "Requests removal of a given export"),
  ]

_X509_CALLS = [
  ("x509_cert_create", SINGLE, TMO_NORMAL, [
    ("validity", None, "Validity in seconds"),
    ], None, "Creates a new X509 certificate for SSL/TLS"),
  ("x509_cert_remove", SINGLE, TMO_NORMAL, [
    ("name", None, "Certificate name"),
    ], None, "Removes a X509 certificate"),
  ]

_BLOCKDEV_CALLS = [
  ("bdev_sizes", MULTI, TMO_URGENT, [
    ("devices", None, None),
    ], None, "Gets the sizes of requested block devices present on a node"),
  ("blockdev_create", SINGLE, TMO_NORMAL, [
    ("bdev", ED_OBJECT_DICT, None),
    ("size", None, None),
    ("owner", None, None),
    ("on_primary", None, None),
    ("info", None, None),
    ], None, "Request creation of a given block device"),
  ("blockdev_wipe", SINGLE, TMO_SLOW, [
    ("bdev", ED_OBJECT_DICT, None),
    ("offset", None, None),
    ("size", None, None),
    ], None,
    "Request wipe at given offset with given size of a block device"),
  ("blockdev_remove", SINGLE, TMO_NORMAL, [
    ("bdev", ED_OBJECT_DICT, None),
    ], None, "Request removal of a given block device"),
  ("blockdev_pause_resume_sync", SINGLE, TMO_NORMAL, [
    ("disks", ED_OBJECT_DICT_LIST, None),
    ("pause", None, None),
    ], None, "Request a pause/resume of given block device"),
  ("blockdev_assemble", SINGLE, TMO_NORMAL, [
    ("disk", ED_OBJECT_DICT, None),
    ("owner", None, None),
    ("on_primary", None, None),
    ("idx", None, None),
    ], None, "Request assembling of a given block device"),
  ("blockdev_shutdown", SINGLE, TMO_NORMAL, [
    ("disk", ED_OBJECT_DICT, None),
    ], None, "Request shutdown of a given block device"),
  ("blockdev_addchildren", SINGLE, TMO_NORMAL, [
    ("bdev", ED_OBJECT_DICT, None),
    ("ndevs", ED_OBJECT_DICT_LIST, None),
    ], None, "Request adding a list of children to a (mirroring) device"),
  ("blockdev_removechildren", SINGLE, TMO_NORMAL, [
    ("bdev", ED_OBJECT_DICT, None),
    ("ndevs", ED_OBJECT_DICT_LIST, None),
    ], None, "Request removing a list of children from a (mirroring) device"),
  ("blockdev_close", SINGLE, TMO_NORMAL, [
    ("instance_name", None, None),
    ("disks", ED_OBJECT_DICT_LIST, None),
    ], None, "Closes the given block devices"),
  ("blockdev_getsize", SINGLE, TMO_NORMAL, [
    ("disks", ED_OBJECT_DICT_LIST, None),
    ], None, "Returns the size of the given disks"),
  ("drbd_disconnect_net", MULTI, TMO_NORMAL, [
    ("nodes_ip", None, None),
    ("disks", ED_OBJECT_DICT_LIST, None),
    ], None, "Disconnects the network of the given drbd devices"),
  ("drbd_attach_net", MULTI, TMO_NORMAL, [
    ("nodes_ip", None, None),
    ("disks", ED_OBJECT_DICT_LIST, None),
    ("instance_name", None, None),
    ("multimaster", None, None),
    ], None, "Connects the given DRBD devices"),
  ("drbd_wait_sync", MULTI, TMO_SLOW, [
    ("nodes_ip", None, None),
    ("disks", ED_OBJECT_DICT_LIST, None),
    ], None, "Waits for the synchronization of drbd devices is complete"),
  ("blockdev_grow", SINGLE, TMO_NORMAL, [
    ("cf_bdev", ED_OBJECT_DICT, None),
    ("amount", None, None),
    ("dryrun", None, None),
    ], None, "Request a snapshot of the given block device"),
  ("blockdev_export", SINGLE, TMO_1DAY, [
    ("cf_bdev", ED_OBJECT_DICT, None),
    ("dest_node", None, None),
    ("dest_path", None, None),
    ("cluster_name", None, None),
    ], None, "Export a given disk to another node"),
  ("blockdev_snapshot", SINGLE, TMO_NORMAL, [
    ("cf_bdev", ED_OBJECT_DICT, None),
    ], None, "Export a given disk to another node"),
  ("blockdev_rename", SINGLE, TMO_NORMAL, [
    ("devlist", ED_BLOCKDEV_RENAME, None),
    ], None, "Request rename of the given block devices"),
  ("blockdev_find", SINGLE, TMO_NORMAL, [
    ("disk", ED_OBJECT_DICT, None),
    ], "self._BlockdevFindPostProc",
    "Request identification of a given block device"),
  ("blockdev_getmirrorstatus", SINGLE, TMO_NORMAL, [
    ("disks", ED_OBJECT_DICT_LIST, None),
    ], "self._BlockdevGetMirrorStatusPostProc",
    "Request status of a (mirroring) device"),
  ("blockdev_getmirrorstatus_multi", MULTI, TMO_NORMAL, [
    ("node_disks", ED_NODE_TO_DISK_DICT, None),
    ], "self._BlockdevGetMirrorStatusMultiPostProc",
    "Request status of (mirroring) devices from multiple nodes"),
  ]

_OS_CALLS = [
  ("os_diagnose", MULTI, TMO_FAST, [], None,
   "Request a diagnose of OS definitions"),
  ("os_validate", MULTI, TMO_FAST, [
    ("required", None, None),
    ("name", None, None),
    ("checks", None, None),
    ("params", None, None),
    ], None, "Run a validation routine for a given OS"),
  ("os_get", SINGLE, TMO_FAST, [
    ("name", None, None),
    ], "self._OsGetPostProc", "Returns an OS definition"),
  ]

_NODE_CALLS = [
  ("node_has_ip_address", SINGLE, TMO_FAST, [
    ("address", None, "IP address"),
    ], None, "Checks if a node has the given IP address"),
  ("node_info", MULTI, TMO_URGENT, [
    ("vg_name", None,
     "Name of the volume group to ask for disk space information"),
    ("hypervisor_type", None,
     "Name of the hypervisor to ask for memory information"),
    ], None, "Return node information"),
  ("node_verify", MULTI, TMO_NORMAL, [
    ("checkdict", None, None),
    ("cluster_name", None, None),
    ], None, "Request verification of given parameters"),
  ("node_volumes", MULTI, TMO_FAST, [], None, "Gets all volumes on node(s)"),
  ("node_demote_from_mc", SINGLE, TMO_FAST, [], None,
   "Demote a node from the master candidate role"),
  ("node_powercycle", SINGLE, TMO_NORMAL, [
    ("hypervisor", None, "Hypervisor type"),
    ], None, "Tries to powercycle a node"),
  ]

_MISC_CALLS = [
  ("lv_list", MULTI, TMO_URGENT, [
    ("vg_name", None, None),
    ], None, "Gets the logical volumes present in a given volume group"),
  ("vg_list", MULTI, TMO_URGENT, [], None, "Gets the volume group list"),
  ("bridges_exist", SINGLE, TMO_URGENT, [
    ("bridges_list", None, "Bridges which must be present on remote node"),
    ], None, "Checks if a node has all the bridges given"),
  ("etc_hosts_modify", SINGLE, TMO_NORMAL, [
    ("mode", None,
     "Mode to operate; currently L{constants.ETC_HOSTS_ADD} or"
     " L{constants.ETC_HOSTS_REMOVE}"),
    ("name", None, "Hostname to be modified"),
    ("ip", None, "IP address (L{constants.ETC_HOSTS_ADD} only)"),
    ], None, "Modify hosts file with name"),
  ("drbd_helper", MULTI, TMO_URGENT, [], None, "Gets DRBD helper"),
  ("run_oob", SINGLE, TMO_NORMAL, [
    ("oob_program", None, None),
    ("command", None, None),
    ("remote_node", None, None),
    ("timeout", None, None),
    ], None, "Runs out-of-band command"),
  ("hooks_runner", MULTI, TMO_NORMAL, [
    ("hpath", None, None),
    ("phase", None, None),
    ("env", None, None),
    ], None, "Call the hooks runner"),
  ("iallocator_runner", SINGLE, TMO_NORMAL, [
    ("name", None, "Iallocator name"),
    ("idata", None, "JSON-encoded input string"),
    ], None, "Call an iallocator on a remote node"),
  ("test_delay", MULTI, None, [
    ("duration", None, None),
    ], None, "Sleep for a fixed time on given node(s)"),
  ("hypervisor_validate_params", MULTI, TMO_NORMAL, [
    ("hvname", None, "Hypervisor name"),
    ("hvfull", None, "Parameters to be validated"),
    ], None, "Validate hypervisor params"),
  ]

CALLS = {
  "RpcClientDefault": \
    _Prepare(_IMPEXP_CALLS + _X509_CALLS + _OS_CALLS + _NODE_CALLS +
             _FILE_STORAGE_CALLS + _MISC_CALLS + _INSTANCE_CALLS +
             _BLOCKDEV_CALLS + _STORAGE_CALLS),
  "RpcClientJobQueue": _Prepare([
    ("jobqueue_update", MULTI, TMO_URGENT, [
      ("file_name", None, None),
      ("content", ED_COMPRESS, None),
      ], None, "Update job queue file"),
    ("jobqueue_purge", SINGLE, TMO_NORMAL, [], None, "Purge job queue"),
    ("jobqueue_rename", MULTI, TMO_URGENT, [
      ("rename", None, None),
      ], None, "Rename job queue file"),
    ]),
  "RpcClientBootstrap": _Prepare([
    ("node_start_master_daemons", SINGLE, TMO_FAST, [
      ("no_voting", None, None),
      ], None, "Starts master daemons on a node"),
    ("node_activate_master_ip", SINGLE, TMO_FAST, [
      ("master_params", ED_OBJECT_DICT, "Network parameters of the master"),
      ], None,
      "Activates master IP on a node"),
    ("node_stop_master", SINGLE, TMO_FAST, [], None,
     "Deactivates master IP and stops master daemons on a node"),
    ("node_deactivate_master_ip", SINGLE, TMO_FAST, [
      ("master_params", ED_OBJECT_DICT, "Network parameters of the master"),
      ], None,
     "Deactivates master IP on a node"),
    ("node_change_master_netmask", SINGLE, TMO_FAST, [
      ("old_netmask", None, "The old value of the netmask"),
      ("netmask", None, "The new value of the netmask"),
      ("master_ip", None, "The master IP"),
      ("master_netdev", None, "The master network device"),
      ], None, "Change master IP netmask"),
    ("node_leave_cluster", SINGLE, TMO_NORMAL, [
      ("modify_ssh_setup", None, None),
      ], None, "Requests a node to clean the cluster information it has"),
    ("master_info", MULTI, TMO_URGENT, [], None, "Query master info"),
    ("version", MULTI, TMO_URGENT, [], None, "Query node version"),
    ]),
  "RpcClientConfig": _Prepare([
    ("upload_file", MULTI, TMO_NORMAL, [
      ("file_name", ED_FILE_DETAILS, None),
      ], None, "Upload a file"),
    ("write_ssconf_files", MULTI, TMO_NORMAL, [
      ("values", None, None),
      ], None, "Write ssconf files"),
    ]),
  }
