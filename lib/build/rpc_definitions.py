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
    - Wrapper code ("%s" is replaced with argument name, see L{OBJECT_TO_DICT})
    - Description for docstring (can be C{None})

  - Return value wrapper (e.g. for deserializing into L{objects}-based objects)
  - Short call description for docstring

"""


# Various time constants for the timeout table
TMO_URGENT = 60 # one minute
TMO_FAST = 5 * 60 # five minutes
TMO_NORMAL = 15 * 60 # 15 minutes
TMO_SLOW = 3600 # one hour
TMO_4HRS = 4 * 3600
TMO_1DAY = 86400

SINGLE = "single-node"
MULTI = "multi-node"

OBJECT_TO_DICT = "%s.ToDict()"
OBJECT_LIST_TO_DICT = "map(lambda d: d.ToDict(), %s)"
INST_TO_DICT = "self._InstDict(%s)"

NODE_TO_DISK_DICT = \
  ("dict((name, %s) for name, disks in %%s.items())" %
   (OBJECT_LIST_TO_DICT % "disks"))

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
    ("inst", INST_TO_DICT, "Instance object"),
    ("reboot_type", None, None),
    ("shutdown_timeout", None, None),
    ], None, "Returns the list of running instances on the given nodes"),
  ("instance_shutdown", SINGLE, TMO_NORMAL, [
    ("instance", INST_TO_DICT, "Instance object"),
    ("timeout", None, None),
    ], None, "Stops an instance"),
  ("instance_run_rename", SINGLE, TMO_SLOW, [
    ("instance", INST_TO_DICT, "Instance object"),
    ("old_name", None, None),
    ("debug", None, None),
    ], None, "Run the OS rename script for an instance"),
  ("instance_migratable", SINGLE, TMO_NORMAL, [
    ("instance", INST_TO_DICT, "Instance object"),
    ], None, "Checks whether the given instance can be migrated"),
  ("migration_info", SINGLE, TMO_NORMAL, [
    ("instance", INST_TO_DICT, "Instance object"),
    ], None,
    "Gather the information necessary to prepare an instance migration"),
  ("accept_instance", SINGLE, TMO_NORMAL, [
    ("instance", INST_TO_DICT, "Instance object"),
    ("info", None, "Result for the call_migration_info call"),
    ("target", None, "Target hostname (usually an IP address)"),
    ], None, "Prepare a node to accept an instance"),
  ("instance_finalize_migration_dst", SINGLE, TMO_NORMAL, [
    ("instance", INST_TO_DICT, "Instance object"),
    ("info", None, "Result for the call_migration_info call"),
    ("success", None, "Whether the migration was a success or failure"),
    ], None, "Finalize any target-node migration specific operation"),
  ("instance_migrate", SINGLE, TMO_SLOW, [
    ("instance", INST_TO_DICT, "Instance object"),
    ("target", None, "Target node name"),
    ("live", None, "Whether the migration should be done live or not"),
    ], None, "Migrate an instance"),
  ("instance_finalize_migration_src", SINGLE, TMO_SLOW, [
    ("instance", INST_TO_DICT, "Instance object"),
    ("success", None, "Whether the migration succeeded or not"),
    ("live", None, "Whether the user requested a live migration or not"),
    ], None, "Finalize the instance migration on the source node"),
  ]

_IMPEXP_CALLS = [
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
    ("instance", INST_TO_DICT, None),
    ("snap_disks", "self._PrepareFinalizeExportDisks(%s)", None),
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
    ("bdev", OBJECT_TO_DICT, None),
    ("size", None, None),
    ("owner", None, None),
    ("on_primary", None, None),
    ("info", None, None),
    ], None, "Request creation of a given block device"),
  ("blockdev_wipe", SINGLE, TMO_SLOW, [
    ("bdev", OBJECT_TO_DICT, None),
    ("offset", None, None),
    ("size", None, None),
    ], None,
    "Request wipe at given offset with given size of a block device"),
  ("blockdev_remove", SINGLE, TMO_NORMAL, [
    ("bdev", OBJECT_TO_DICT, None),
    ], None, "Request removal of a given block device"),
  ("blockdev_pause_resume_sync", SINGLE, TMO_NORMAL, [
    ("disks", OBJECT_LIST_TO_DICT, None),
    ("pause", None, None),
    ], None, "Request a pause/resume of given block device"),
  ("blockdev_assemble", SINGLE, TMO_NORMAL, [
    ("disk", OBJECT_TO_DICT, None),
    ("owner", None, None),
    ("on_primary", None, None),
    ("idx", None, None),
    ], None, "Request assembling of a given block device"),
  ("blockdev_shutdown", SINGLE, TMO_NORMAL, [
    ("disk", OBJECT_TO_DICT, None),
    ], None, "Request shutdown of a given block device"),
  ("blockdev_addchildren", SINGLE, TMO_NORMAL, [
    ("bdev", OBJECT_TO_DICT, None),
    ("ndevs", OBJECT_LIST_TO_DICT, None),
    ], None, "Request adding a list of children to a (mirroring) device"),
  ("blockdev_removechildren", SINGLE, TMO_NORMAL, [
    ("bdev", OBJECT_TO_DICT, None),
    ("ndevs", OBJECT_LIST_TO_DICT, None),
    ], None, "Request removing a list of children from a (mirroring) device"),
  ("blockdev_close", SINGLE, TMO_NORMAL, [
    ("instance_name", None, None),
    ("disks", OBJECT_LIST_TO_DICT, None),
    ], None, "Closes the given block devices"),
  ("blockdev_getsize", SINGLE, TMO_NORMAL, [
    ("disks", OBJECT_LIST_TO_DICT, None),
    ], None, "Returns the size of the given disks"),
  ("drbd_disconnect_net", MULTI, TMO_NORMAL, [
    ("nodes_ip", None, None),
    ("disks", OBJECT_LIST_TO_DICT, None),
    ], None, "Disconnects the network of the given drbd devices"),
  ("drbd_attach_net", MULTI, TMO_NORMAL, [
    ("nodes_ip", None, None),
    ("disks", OBJECT_LIST_TO_DICT, None),
    ("instance_name", None, None),
    ("multimaster", None, None),
    ], None, "Connects the given DRBD devices"),
  ("drbd_wait_sync", MULTI, TMO_SLOW, [
    ("nodes_ip", None, None),
    ("disks", OBJECT_LIST_TO_DICT, None),
    ], None, "Waits for the synchronization of drbd devices is complete"),
  ("blockdev_grow", SINGLE, TMO_NORMAL, [
    ("cf_bdev", OBJECT_TO_DICT, None),
    ("amount", None, None),
    ("dryrun", None, None),
    ], None, "Request a snapshot of the given block device"),
  ("blockdev_export", SINGLE, TMO_1DAY, [
    ("cf_bdev", OBJECT_TO_DICT, None),
    ("dest_node", None, None),
    ("dest_path", None, None),
    ("cluster_name", None, None),
    ], None, "Export a given disk to another node"),
  ("blockdev_snapshot", SINGLE, TMO_NORMAL, [
    ("cf_bdev", OBJECT_TO_DICT, None),
    ], None, "Export a given disk to another node"),
  ("blockdev_rename", SINGLE, TMO_NORMAL, [
    ("devlist", "[(d.ToDict(), uid) for d, uid in %s]", None),
    ], None, "Request rename of the given block devices"),
  ("blockdev_find", SINGLE, TMO_NORMAL, [
    ("disk", OBJECT_TO_DICT, None),
    ], "self._BlockdevFindPostProc",
    "Request identification of a given block device"),
  ("blockdev_getmirrorstatus", SINGLE, TMO_NORMAL, [
    ("disks", OBJECT_LIST_TO_DICT, None),
    ], "self._BlockdevGetMirrorStatusPostProc",
    "Request status of a (mirroring) device"),
  ("blockdev_getmirrorstatus_multi", MULTI, TMO_NORMAL, [
    ("node_disks", NODE_TO_DISK_DICT, None),
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
  ]

CALLS = {
  "RpcClientDefault": _IMPEXP_CALLS,
  }
