{-| Implementation of the doc strings for the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}

module Ganeti.Hs2Py.OpDoc where


opClusterPostInit :: String
opClusterPostInit =
  "Post cluster initialization.\n\
\\n\
\  This opcode does not touch the cluster at all. Its purpose is to run hooks\n\
\  after the cluster has been initialized."

opClusterDestroy :: String
opClusterDestroy =
  "Destroy the cluster.\n\
\\n\
\  This opcode has no other parameters. All the state is irreversibly\n\
\  lost after the execution of this opcode."

opClusterQuery :: String
opClusterQuery =
  "Query cluster information."

opClusterVerify :: String
opClusterVerify =
  "Submits all jobs necessary to verify the cluster."

opClusterVerifyConfig :: String
opClusterVerifyConfig =
  "Verify the cluster config."

opClusterVerifyGroup :: String
opClusterVerifyGroup =
  "Run verify on a node group from the cluster.\n\
\\n\
\  @type skip_checks: C{list}\n\
\  @ivar skip_checks: steps to be skipped from the verify process; this\n\
\                     needs to be a subset of\n\
\                     L{constants.VERIFY_OPTIONAL_CHECKS}; currently\n\
\                     only L{constants.VERIFY_NPLUSONE_MEM} can be passed"

opClusterVerifyDisks :: String
opClusterVerifyDisks =
  "Verify the cluster disks."

opGroupVerifyDisks :: String
opGroupVerifyDisks =
  "Verifies the status of all disks in a node group.\n\
\\n\
\  Result: a tuple of three elements:\n\
\    - dict of node names with issues (values: error msg)\n\
\    - list of instances with degraded disks (that should be activated)\n\
\    - dict of instances with missing logical volumes (values: (node, vol)\n\
\      pairs with details about the missing volumes)\n\
\\n\
\  In normal operation, all lists should be empty. A non-empty instance\n\
\  list (3rd element of the result) is still ok (errors were fixed) but\n\
\  non-empty node list means some node is down, and probably there are\n\
\  unfixable drbd errors.\n\
\\n\
\  Note that only instances that are drbd-based are taken into\n\
\  consideration. This might need to be revisited in the future."

opClusterRepairDiskSizes :: String
opClusterRepairDiskSizes =
  "Verify the disk sizes of the instances and fixes configuration\n\
\  mismatches.\n\
\\n\
\  Parameters: optional instances list, in case we want to restrict the\n\
\  checks to only a subset of the instances.\n\
\\n\
\  Result: a list of tuples, (instance, disk, parameter, new-size) for\n\
\  changed configurations.\n\
\\n\
\  In normal operation, the list should be empty.\n\
\\n\
\  @type instances: list\n\
\  @ivar instances: the list of instances to check, or empty for all instances"

opClusterConfigQuery :: String
opClusterConfigQuery =
  "Query cluster configuration values."

opClusterRename :: String
opClusterRename =
  "Rename the cluster.\n\
\\n\
\  @type name: C{str}\n\
\  @ivar name: The new name of the cluster. The name and/or the master IP\n\
\              address will be changed to match the new name and its IP\n\
\              address."

opClusterSetParams :: String
opClusterSetParams =
  "Change the parameters of the cluster.\n\
\\n\
\  @type vg_name: C{str} or C{None}\n\
\  @ivar vg_name: The new volume group name or None to disable LVM usage."

opClusterRedistConf :: String
opClusterRedistConf =
  "Force a full push of the cluster configuration."

opClusterActivateMasterIp :: String
opClusterActivateMasterIp =
  "Activate the master IP on the master node."

opClusterDeactivateMasterIp :: String
opClusterDeactivateMasterIp =
  "Deactivate the master IP on the master node."

opClusterRenewCrypto :: String
opClusterRenewCrypto =
  "Renews the cluster node's SSL client certificates."

opQuery :: String
opQuery =
  "Query for resources/items.\n\
\\n\
\  @ivar what: Resources to query for, must be one of L{constants.QR_VIA_OP}\n\
\  @ivar fields: List of fields to retrieve\n\
\  @ivar qfilter: Query filter"

opQueryFields :: String
opQueryFields =
  "Query for available resource/item fields.\n\
\\n\
\  @ivar what: Resources to query for, must be one of L{constants.QR_VIA_OP}\n\
\  @ivar fields: List of fields to retrieve"

opOobCommand :: String
opOobCommand =
  "Interact with OOB."

opRestrictedCommand :: String
opRestrictedCommand =
  "Runs a restricted command on node(s)."

opNodeRemove :: String
opNodeRemove =
  "Remove a node.\n\
\\n\
\  @type node_name: C{str}\n\
\  @ivar node_name: The name of the node to remove. If the node still has\n\
\                   instances on it, the operation will fail."

opNodeAdd :: String
opNodeAdd =
  "Add a node to the cluster.\n\
\\n\
\  @type node_name: C{str}\n\
\  @ivar node_name: The name of the node to add. This can be a short name,\n\
\                   but it will be expanded to the FQDN.\n\
\  @type primary_ip: IP address\n\
\  @ivar primary_ip: The primary IP of the node. This will be ignored when\n\
\                    the opcode is submitted, but will be filled during the\n\
\                    node add (so it will be visible in the job query).\n\
\  @type secondary_ip: IP address\n\
\  @ivar secondary_ip: The secondary IP of the node. This needs to be passed\n\
\                      if the cluster has been initialized in 'dual-network'\n\
\                      mode, otherwise it must not be given.\n\
\  @type readd: C{bool}\n\
\  @ivar readd: Whether to re-add an existing node to the cluster. If\n\
\               this is not passed, then the operation will abort if the node\n\
\               name is already in the cluster; use this parameter to\n\
\               'repair' a node that had its configuration broken, or was\n\
\               reinstalled without removal from the cluster.\n\
\  @type group: C{str}\n\
\  @ivar group: The node group to which this node will belong.\n\
\  @type vm_capable: C{bool}\n\
\  @ivar vm_capable: The vm_capable node attribute\n\
\  @type master_capable: C{bool}\n\
\  @ivar master_capable: The master_capable node attribute"

opNodeQuery :: String
opNodeQuery =
  "Compute the list of nodes."

opNodeQueryvols :: String
opNodeQueryvols =
  "Get list of volumes on node."

opNodeQueryStorage :: String
opNodeQueryStorage =
  "Get information on storage for node(s)."

opNodeModifyStorage :: String
opNodeModifyStorage =
  "Modifies the properies of a storage unit"

opRepairNodeStorage :: String
opRepairNodeStorage =
  "Repairs the volume group on a node."

opNodeSetParams :: String
opNodeSetParams =
  "Change the parameters of a node."

opNodePowercycle :: String
opNodePowercycle =
  "Tries to powercycle a node."

opNodeMigrate :: String
opNodeMigrate =
  "Migrate all instances from a node."

opNodeEvacuate :: String
opNodeEvacuate =
  "Evacuate instances off a number of nodes."

opInstanceCreate :: String
opInstanceCreate =
  "Create an instance.\n\
\\n\
\  @ivar instance_name: Instance name\n\
\  @ivar mode: Instance creation mode (one of\
\ L{constants.INSTANCE_CREATE_MODES})\n\
\  @ivar source_handshake: Signed handshake from source (remote import only)\n\
\  @ivar source_x509_ca: Source X509 CA in PEM format (remote import only)\n\
\  @ivar source_instance_name: Previous name of instance (remote import only)\n\
\  @ivar source_shutdown_timeout: Shutdown timeout used for source instance\n\
\    (remote import only)"

opInstanceMultiAlloc :: String
opInstanceMultiAlloc =
  "Allocates multiple instances."

opInstanceReinstall :: String
opInstanceReinstall =
  "Reinstall an instance's OS."

opInstanceRemove :: String
opInstanceRemove =
  "Remove an instance."

opInstanceRename :: String
opInstanceRename =
  "Rename an instance."

opInstanceStartup :: String
opInstanceStartup =
  "Startup an instance."

opInstanceShutdown :: String
opInstanceShutdown =
  "Shutdown an instance."

opInstanceReboot :: String
opInstanceReboot =
  "Reboot an instance."

opInstanceReplaceDisks :: String
opInstanceReplaceDisks =
  "Replace the disks of an instance."

opInstanceFailover :: String
opInstanceFailover =
  "Failover an instance."

opInstanceMigrate :: String
opInstanceMigrate =
  "Migrate an instance.\n\
\\n\
\  This migrates (without shutting down an instance) to its secondary\n\
\  node.\n\
\\n\
\  @ivar instance_name: the name of the instance\n\
\  @ivar mode: the migration mode (live, non-live or None for auto)"

opInstanceMove :: String
opInstanceMove =
  "Move an instance.\n\
\\n\
\  This move (with shutting down an instance and data copying) to an\n\
\  arbitrary node.\n\
\\n\
\  @ivar instance_name: the name of the instance\n\
\  @ivar target_node: the destination node"

opInstanceConsole :: String
opInstanceConsole =
  "Connect to an instance's console."

opInstanceActivateDisks :: String
opInstanceActivateDisks =
  "Activate an instance's disks."

opInstanceDeactivateDisks :: String
opInstanceDeactivateDisks =
  "Deactivate an instance's disks."

opInstanceRecreateDisks :: String
opInstanceRecreateDisks =
  "Recreate an instance's disks."

opInstanceQuery :: String
opInstanceQuery =
  "Compute the list of instances."

opInstanceQueryData :: String
opInstanceQueryData =
  "Compute the run-time status of instances."

opInstanceSetParams :: String
opInstanceSetParams =
  "Change the parameters of an instance."

opInstanceGrowDisk :: String
opInstanceGrowDisk =
  "Grow a disk of an instance."

opInstanceChangeGroup :: String
opInstanceChangeGroup =
  "Moves an instance to another node group."

opGroupAdd :: String
opGroupAdd =
  "Add a node group to the cluster."

opGroupAssignNodes :: String
opGroupAssignNodes =
  "Assign nodes to a node group."

opGroupQuery :: String
opGroupQuery =
  "Compute the list of node groups."

opGroupSetParams :: String
opGroupSetParams =
  "Change the parameters of a node group."

opGroupRemove :: String
opGroupRemove =
  "Remove a node group from the cluster."

opGroupRename :: String
opGroupRename =
  "Rename a node group in the cluster."

opGroupEvacuate :: String
opGroupEvacuate =
  "Evacuate a node group in the cluster."

opOsDiagnose :: String
opOsDiagnose =
  "Compute the list of guest operating systems."

opExtStorageDiagnose :: String
opExtStorageDiagnose =
  "Compute the list of external storage providers."

opBackupQuery :: String
opBackupQuery =
  "Compute the list of exported images."

opBackupPrepare :: String
opBackupPrepare =
  "Prepares an instance export.\n\
\\n\
\  @ivar instance_name: Instance name\n\
\  @ivar mode: Export mode (one of L{constants.EXPORT_MODES})"

opBackupExport :: String
opBackupExport =
  "Export an instance.\n\
\\n\
\  For local exports, the export destination is the node name. For\n\
\  remote exports, the export destination is a list of tuples, each\n\
\  consisting of hostname/IP address, port, magic, HMAC and HMAC\n\
\  salt. The HMAC is calculated using the cluster domain secret over\n\
\  the value \"${index}:${hostname}:${port}\". The destination X509 CA\n\
\  must be a signed certificate.\n\
\\n\
\  @ivar mode: Export mode (one of L{constants.EXPORT_MODES})\n\
\  @ivar target_node: Export destination\n\
\  @ivar x509_key_name: X509 key to use (remote export only)\n\
\  @ivar destination_x509_ca: Destination X509 CA in PEM format (remote\n\
\                             export only)"

opBackupRemove :: String
opBackupRemove =
  "Remove an instance's export."

opTagsGet :: String
opTagsGet =
  "Returns the tags of the given object."

opTagsSearch :: String
opTagsSearch =
  "Searches the tags in the cluster for a given pattern."

opTagsSet :: String
opTagsSet =
  "Add a list of tags on a given object."

opTagsDel :: String
opTagsDel =
  "Remove a list of tags from a given object."

opTestDelay :: String
opTestDelay =
  "Sleeps for a configured amount of time.\n\
\\n\
\  This is used just for debugging and testing.\n\
\\n\
\  Parameters:\n\
\    - duration: the time to sleep, in seconds\n\
\    - on_master: if true, sleep on the master\n\
\    - on_nodes: list of nodes in which to sleep\n\
\\n\
\  If the on_master parameter is true, it will execute a sleep on the\n\
\  master (before any node sleep).\n\
\\n\
\  If the on_nodes list is not empty, it will sleep on those nodes\n\
\  (after the sleep on the master, if that is enabled).\n\
\\n\
\  As an additional feature, the case of duration < 0 will be reported\n\
\  as an execution error, so this opcode can be used as a failure\n\
\  generator. The case of duration == 0 will not be treated specially."

opTestAllocator :: String
opTestAllocator =
  "Allocator framework testing.\n\
\\n\
\  This opcode has two modes:\n\
\    - gather and return allocator input for a given mode (allocate new\n\
\      or replace secondary) and a given instance definition (direction\n\
\      'in')\n\
\    - run a selected allocator for a given operation (as above) and\n\
\      return the allocator output (direction 'out')"

opTestJqueue :: String
opTestJqueue =
  "Utility opcode to test some aspects of the job queue."

opTestOsParams :: String
opTestOsParams =
  "Utility opcode to test secret os parameter transmission."

opTestDummy :: String
opTestDummy =
  "Utility opcode used by unittests."

opNetworkAdd :: String
opNetworkAdd =
  "Add an IP network to the cluster."

opNetworkRemove :: String
opNetworkRemove =
  "Remove an existing network from the cluster.\n\
\     Must not be connected to any nodegroup."

opNetworkSetParams :: String
opNetworkSetParams =
  "Modify Network's parameters except for IPv4 subnet"

opNetworkConnect :: String
opNetworkConnect =
  "Connect a Network to a specific Nodegroup with the defined netparams\n\
\     (mode, link). Nics in this Network will inherit those params.\n\
\     Produce errors if a NIC (that its not already assigned to a network)\n\
\     has an IP that is contained in the Network this will produce error\
\ unless\n\
\     --no-conflicts-check is passed."

opNetworkDisconnect :: String
opNetworkDisconnect =
  "Disconnect a Network from a Nodegroup. Produce errors if NICs are\n\
\     present in the Network unless --no-conficts-check option is passed."

opNetworkQuery :: String
opNetworkQuery =
  "Compute the list of networks."
