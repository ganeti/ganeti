Ganeti customisation using hooks
================================

Documents Ganeti version 2.16

.. contents::

Introduction
------------

In order to allow customisation of operations, Ganeti runs scripts in
sub-directories of ``@SYSCONFDIR@/ganeti/hooks``. These sub-directories
are named ``$hook-$phase.d``, where ``$phase`` is either ``pre`` or
``post`` and ``$hook`` matches the directory name given for a hook (e.g.
``cluster-verify-post.d`` or ``node-add-pre.d``).

This is similar to the ``/etc/network/`` structure present in Debian
for network interface handling.

Organisation
------------

For every operation, two sets of scripts are run:

- pre phase (for authorization/checking)
- post phase (for logging)

Also, for each operation, the scripts are run on one or more nodes,
depending on the operation type.

Note that, even though we call them scripts, we are actually talking
about any executable.

*pre* scripts
~~~~~~~~~~~~~

The *pre* scripts have a definite target: to check that the operation
is allowed given the site-specific constraints. You could have, for
example, a rule that says every new instance is required to exists in
a database; to implement this, you could write a script that checks
the new instance parameters against your database.

The objective of these scripts should be their return code (zero or
non-zero for success and failure). However, if they modify the
environment in any way, they should be idempotent, as failed
executions could be restarted and thus the script(s) run again with
exactly the same parameters.

Note that if a node is unreachable at the time a hooks is run, this
will not be interpreted as a deny for the execution. In other words,
only an actual error returned from a script will cause abort, and not
an unreachable node.

Therefore, if you want to guarantee that a hook script is run and
denies an action, it's best to put it on the master node.

*post* scripts
~~~~~~~~~~~~~~

These scripts should do whatever you need as a reaction to the
completion of an operation. Their return code is not checked (but
logged), and they should not depend on the fact that the *pre* scripts
have been run.

Naming
~~~~~~

The allowed names for the scripts consist of (similar to *run-parts*)
upper and lower case, digits, underscores and hyphens. In other words,
the regexp ``^[a-zA-Z0-9_-]+$``. Also, non-executable scripts will be
ignored.


Order of execution
~~~~~~~~~~~~~~~~~~

On a single node, the scripts in a directory are run in lexicographic
order (more exactly, the python string comparison order). It is
advisable to implement the usual *NN-name* convention where *NN* is a
two digit number.

For an operation whose hooks are run on multiple nodes, there is no
specific ordering of nodes with regard to hooks execution; you should
assume that the scripts are run in parallel on the target nodes
(keeping on each node the above specified ordering).  If you need any
kind of inter-node synchronisation, you have to implement it yourself
in the scripts.

Execution environment
~~~~~~~~~~~~~~~~~~~~~

The scripts will be run as follows:

- no command line arguments

- no controlling *tty*

- stdin is actually */dev/null*

- stdout and stderr are directed to files

- PATH is reset to :pyeval:`constants.HOOKS_PATH`

- the environment is cleared, and only ganeti-specific variables will
  be left


All information about the cluster is passed using environment
variables. Different operations will have sligthly different
environments, but most of the variables are common.

Operation list
--------------

Node operations
~~~~~~~~~~~~~~~

OP_NODE_ADD
+++++++++++

Adds a node to the cluster.

:directory: node-add
:env. vars: NODE_NAME, NODE_PIP, NODE_SIP, MASTER_CAPABLE, VM_CAPABLE
:pre-execution: all existing nodes
:post-execution: all nodes plus the new node


OP_NODE_REMOVE
++++++++++++++

Removes a node from the cluster. On the removed node the hooks are
called during the execution of the operation and not after its
completion.

:directory: node-remove
:env. vars: NODE_NAME
:pre-execution: all existing nodes except the removed node
:post-execution: all existing nodes

OP_NODE_SET_PARAMS
++++++++++++++++++

Changes a node's parameters.

:directory: node-modify
:env. vars: MASTER_CANDIDATE, OFFLINE, DRAINED, MASTER_CAPABLE, VM_CAPABLE
:pre-execution: master node, the target node
:post-execution: master node, the target node

OP_NODE_MIGRATE
++++++++++++++++

Relocate secondary instances from a node.

:directory: node-migrate
:env. vars: NODE_NAME
:pre-execution: master node
:post-execution: master node


Node group operations
~~~~~~~~~~~~~~~~~~~~~

OP_GROUP_ADD
++++++++++++

Adds a node group to the cluster.

:directory: group-add
:env. vars: GROUP_NAME
:pre-execution: master node
:post-execution: master node

OP_GROUP_SET_PARAMS
+++++++++++++++++++

Changes a node group's parameters.

:directory: group-modify
:env. vars: GROUP_NAME, NEW_ALLOC_POLICY
:pre-execution: master node
:post-execution: master node

OP_GROUP_REMOVE
+++++++++++++++

Removes a node group from the cluster. Since the node group must be
empty for removal to succeed, the concept of "nodes in the group" does
not exist, and the hook is only executed in the master node.

:directory: group-remove
:env. vars: GROUP_NAME
:pre-execution: master node
:post-execution: master node

OP_GROUP_RENAME
+++++++++++++++

Renames a node group.

:directory: group-rename
:env. vars: OLD_NAME, NEW_NAME
:pre-execution: master node and all nodes in the group
:post-execution: master node and all nodes in the group

OP_GROUP_EVACUATE
+++++++++++++++++

Evacuates a node group.

:directory: group-evacuate
:env. vars: GROUP_NAME, TARGET_GROUPS
:pre-execution: master node and all nodes in the group
:post-execution: master node and all nodes in the group

Network operations
~~~~~~~~~~~~~~~~~~

OP_NETWORK_ADD
++++++++++++++

Adds a network to the cluster.

:directory: network-add
:env. vars: NETWORK_NAME, NETWORK_SUBNET, NETWORK_GATEWAY, NETWORK_SUBNET6,
            NETWORK_GATEWAY6, NETWORK_MAC_PREFIX, NETWORK_TAGS
:pre-execution: master node
:post-execution: master node

OP_NETWORK_REMOVE
+++++++++++++++++

Removes a network from the cluster.

:directory: network-remove
:env. vars: NETWORK_NAME
:pre-execution: master node
:post-execution: master node

OP_NETWORK_CONNECT
++++++++++++++++++

Connects a network to a nodegroup.

:directory: network-connect
:env. vars: GROUP_NAME, NETWORK_NAME,
            GROUP_NETWORK_MODE, GROUP_NETWORK_LINK, GROUP_NETWORK_VLAN,
            NETWORK_SUBNET, NETWORK_GATEWAY, NETWORK_SUBNET6,
            NETWORK_GATEWAY6, NETWORK_MAC_PREFIX, NETWORK_TAGS
:pre-execution: nodegroup nodes
:post-execution: nodegroup nodes


OP_NETWORK_DISCONNECT
+++++++++++++++++++++

Disconnects a network from a nodegroup.

:directory: network-disconnect
:env. vars: GROUP_NAME, NETWORK_NAME,
            GROUP_NETWORK_MODE, GROUP_NETWORK_LINK, GROUP_NETWORK_VLAN,
            NETWORK_SUBNET, NETWORK_GATEWAY, NETWORK_SUBNET6,
            NETWORK_GATEWAY6, NETWORK_MAC_PREFIX, NETWORK_TAGS
:pre-execution: nodegroup nodes
:post-execution: nodegroup nodes


OP_NETWORK_SET_PARAMS
+++++++++++++++++++++

Modifies a network.

:directory: network-modify
:env. vars: NETWORK_NAME, NETWORK_SUBNET, NETWORK_GATEWAY, NETWORK_SUBNET6,
            NETWORK_GATEWAY6, NETWORK_MAC_PREFIX, NETWORK_TAGS
:pre-execution: master node
:post-execution: master node


Instance operations
~~~~~~~~~~~~~~~~~~~

All instance operations take at least the following variables:
INSTANCE_NAME, INSTANCE_PRIMARY, INSTANCE_SECONDARY,
INSTANCE_OS_TYPE, INSTANCE_DISK_TEMPLATE, INSTANCE_MEMORY,
INSTANCE_DISK_SIZES, INSTANCE_VCPUS, INSTANCE_NIC_COUNT,
INSTANCE_NICn_IP, INSTANCE_NICn_BRIDGE, INSTANCE_NICn_MAC,
INSTANCE_NICn_NETWORK,
INSTANCE_NICn_NETWORK_UUID, INSTANCE_NICn_NETWORK_SUBNET,
INSTANCE_NICn_NETWORK_GATEWAY, INSTANCE_NICn_NETWORK_SUBNET6,
INSTANCE_NICn_NETWORK_GATEWAY6, INSTANCE_NICn_NETWORK_MAC_PREFIX,
INSTANCE_DISK_COUNT, INSTANCE_DISKn_SIZE, INSTANCE_DISKn_MODE,
INSTANCE_DISKn_NAME, INSTANCE_DISKn_UUID, INSTANCE_DISKn_DEV_TYPE.

The INSTANCE_NICn_* and INSTANCE_DISKn_* variables represent the
properties of the *n* -th NIC and disk, and are zero-indexed.
Depending on the disk template, Ganeti exports some info related to
the logical id of the disk, that is basically its driver and id.

The INSTANCE_NICn_NETWORK_* variables are only passed if a NIC's network
parameter is set (that is if the NIC is associated to a network defined
via ``gnt-network``)


OP_INSTANCE_CREATE
++++++++++++++++++

Creates a new instance.

:directory: instance-add
:env. vars: ADD_MODE, SRC_NODE, SRC_PATH, SRC_IMAGES
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_REINSTALL
+++++++++++++++++++++

Reinstalls an instance.

:directory: instance-reinstall
:env. vars: only the standard instance vars
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_BACKUP_EXPORT
++++++++++++++++

Exports the instance.

:directory: instance-export
:env. vars: EXPORT_MODE, EXPORT_NODE, EXPORT_DO_SHUTDOWN, REMOVE_INSTANCE
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_STARTUP
+++++++++++++++++++

Starts an instance.

:directory: instance-start
:env. vars: FORCE
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_SHUTDOWN
++++++++++++++++++++

Stops an instance.

:directory: instance-stop
:env. vars: TIMEOUT
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_REBOOT
++++++++++++++++++

Reboots an instance.

:directory: instance-reboot
:env. vars: IGNORE_SECONDARIES, REBOOT_TYPE, SHUTDOWN_TIMEOUT
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_SET_PARAMS
++++++++++++++++++++++

Modifies the instance parameters.

:directory: instance-modify
:env. vars: NEW_DISK_TEMPLATE, RUNTIME_MEMORY
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_FAILOVER
++++++++++++++++++++

Failovers an instance. In the post phase INSTANCE_PRIMARY and
INSTANCE_SECONDARY refer to the nodes that were repectively primary
and secondary before failover.

:directory: instance-failover
:env. vars: IGNORE_CONSISTENCY, SHUTDOWN_TIMEOUT, OLD_PRIMARY, OLD_SECONDARY, NEW_PRIMARY, NEW_SECONDARY
:pre-execution: master node, secondary (target) node
:post-execution: master node, primary (source) and secondary (target) nodes

OP_INSTANCE_MIGRATE
++++++++++++++++++++

Migrates an instance. In the post phase INSTANCE_PRIMARY and
INSTANCE_SECONDARY refer to the nodes that were repectively primary
and secondary before migration.

:directory: instance-migrate
:env. vars: MIGRATE_LIVE, MIGRATE_CLEANUP, OLD_PRIMARY, OLD_SECONDARY, NEW_PRIMARY, NEW_SECONDARY
:pre-execution: master node, primary (source) and secondary (target) nodes
:post-execution: master node, primary (source) and secondary (target) nodes


OP_INSTANCE_REMOVE
++++++++++++++++++

Remove an instance.

:directory: instance-remove
:env. vars: SHUTDOWN_TIMEOUT
:pre-execution: master node
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_GROW_DISK
+++++++++++++++++++++

Grows the disk of an instance.

:directory: disk-grow
:env. vars: DISK, AMOUNT
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_RENAME
++++++++++++++++++

Renames an instance.

:directory: instance-rename
:env. vars: INSTANCE_NEW_NAME
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_MOVE
++++++++++++++++

Move an instance by data-copying.

:directory: instance-move
:env. vars: TARGET_NODE, SHUTDOWN_TIMEOUT
:pre-execution: master node, primary and target nodes
:post-execution: master node, primary and target nodes

OP_INSTANCE_RECREATE_DISKS
++++++++++++++++++++++++++

Recreate an instance's missing disks.

:directory: instance-recreate-disks
:env. vars: only the standard instance vars
:pre-execution: master node, primary and secondary nodes
:post-execution: master node, primary and secondary nodes

OP_INSTANCE_REPLACE_DISKS
+++++++++++++++++++++++++

Replace the disks of an instance.

:directory: mirrors-replace
:env. vars: MODE, NEW_SECONDARY, OLD_SECONDARY
:pre-execution: master node, primary and new secondary nodes
:post-execution: master node, primary and new secondary nodes

OP_INSTANCE_CHANGE_GROUP
++++++++++++++++++++++++

Moves an instance to another group.

:directory: instance-change-group
:env. vars: TARGET_GROUPS
:pre-execution: master node
:post-execution: master node


Cluster operations
~~~~~~~~~~~~~~~~~~

OP_CLUSTER_POST_INIT
++++++++++++++++++++

This hook is called via a special "empty" LU right after cluster
initialization.

:directory: cluster-init
:env. vars: none
:pre-execution: none
:post-execution: master node

OP_CLUSTER_DESTROY
++++++++++++++++++

The post phase of this hook is called during the execution of destroy
operation and not after its completion.

:directory: cluster-destroy
:env. vars: none
:pre-execution: none
:post-execution: master node

OP_CLUSTER_VERIFY_GROUP
+++++++++++++++++++++++

Verifies all nodes in a group. This is a special LU with regard to
hooks, as the result of the opcode will be combined with the result of
post-execution hooks, in order to allow administrators to enhance the
cluster verification procedure.

:directory: cluster-verify
:env. vars: CLUSTER, MASTER, CLUSTER_TAGS, NODE_TAGS_<name>
:pre-execution: none
:post-execution: all nodes in a group

OP_CLUSTER_RENAME
+++++++++++++++++

Renames the cluster.

:directory: cluster-rename
:env. vars: NEW_NAME
:pre-execution: master-node
:post-execution: master-node

OP_CLUSTER_SET_PARAMS
+++++++++++++++++++++

Modifies the cluster parameters.

:directory: cluster-modify
:env. vars: NEW_VG_NAME
:pre-execution: master node
:post-execution: master node

Virtual operation :pyeval:`constants.FAKE_OP_MASTER_TURNUP`
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

This doesn't correspond to an actual op-code, but it is called when the
master IP is activated.

:directory: master-ip-turnup
:env. vars: MASTER_NETDEV, MASTER_IP, MASTER_NETMASK, CLUSTER_IP_VERSION
:pre-execution: master node
:post-execution: master node

Virtual operation :pyeval:`constants.FAKE_OP_MASTER_TURNDOWN`
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

This doesn't correspond to an actual op-code, but it is called when the
master IP is deactivated.

:directory: master-ip-turndown
:env. vars: MASTER_NETDEV, MASTER_IP, MASTER_NETMASK, CLUSTER_IP_VERSION
:pre-execution: master node
:post-execution: master node


Obsolete operations
~~~~~~~~~~~~~~~~~~~

The following operations are no longer present or don't execute hooks
anymore in Ganeti 2.0:

- OP_INIT_CLUSTER
- OP_MASTER_FAILOVER
- OP_INSTANCE_ADD_MDDRBD
- OP_INSTANCE_REMOVE_MDDRBD


Environment variables
---------------------

Note that all variables listed here are actually prefixed with *GANETI_*
in order to provide a clear namespace. In addition, post-execution
scripts receive another set of variables, prefixed with *GANETI_POST_*,
representing the status after the opcode executed.

Common variables
~~~~~~~~~~~~~~~~

This is the list of environment variables supported by all operations:

HOOKS_VERSION
  Documents the hooks interface version. In case this doesnt match
  what the script expects, it should not run. The documents conforms
  to the version 2.

HOOKS_PHASE
  One of *PRE* or *POST* denoting which phase are we in.

CLUSTER
  The cluster name.

MASTER
  The master node.

OP_CODE
  One of the *OP_* values from the list of operations.

OBJECT_TYPE
  One of ``INSTANCE``, ``NODE``, ``CLUSTER``.

DATA_DIR
  The path to the Ganeti configuration directory (to read, for
  example, the *ssconf* files).


Specialised variables
~~~~~~~~~~~~~~~~~~~~~

This is the list of variables which are specific to one or more
operations.

CLUSTER_IP_VERSION
  IP version of the master IP (4 or 6)

INSTANCE_NAME
  The name of the instance which is the target of the operation.

INSTANCE_BE_x,y,z,...
  Instance BE params. There is one variable per BE param. For instance, GANETI_INSTANCE_BE_auto_balance

INSTANCE_DISK_TEMPLATE
  The disk type for the instance.

NEW_DISK_TEMPLATE
  The new disk type for the instance.

INSTANCE_DISK_COUNT
  The number of disks for the instance.

INSTANCE_DISKn_SIZE
  The size of disk *n* for the instance.

INSTANCE_DISKn_MODE
  Either *rw* for a read-write disk or *ro* for a read-only one.

INSTANCE_HV_x,y,z,...
  Instance hypervisor options. There is one variable per option. For instance, GANETI_INSTANCE_HV_use_bootloader

INSTANCE_HYPERVISOR
  The instance hypervisor.

INSTANCE_NIC_COUNT
  The number of NICs for the instance.

INSTANCE_NICn_BRIDGE
  The bridge to which the *n* -th NIC of the instance is attached.

INSTANCE_NICn_IP
  The IP (if any) of the *n* -th NIC of the instance.

INSTANCE_NICn_MAC
  The MAC address of the *n* -th NIC of the instance.

INSTANCE_NICn_MODE
  The mode of the *n* -th NIC of the instance.

INSTANCE_OS_TYPE
  The name of the instance OS.

INSTANCE_PRIMARY
  The name of the node which is the primary for the instance. Note that
  for migrations/failovers, you shouldn't rely on this variable since
  the nodes change during the exectution, but on the
  OLD_PRIMARY/NEW_PRIMARY values.

INSTANCE_SECONDARY
  Space-separated list of secondary nodes for the instance. Note that
  for migrations/failovers, you shouldn't rely on this variable since
  the nodes change during the exectution, but on the
  OLD_SECONDARY/NEW_SECONDARY values.

INSTANCE_MEMORY
  The memory size (in MiBs) of the instance.

INSTANCE_VCPUS
  The number of virtual CPUs for the instance.

INSTANCE_STATUS
  The run status of the instance.

MASTER_CAPABLE
  Whether a node is capable of being promoted to master.

VM_CAPABLE
  Whether the node can host instances.

MASTER_NETDEV
  Network device of the master IP

MASTER_IP
  The master IP

MASTER_NETMASK
  Netmask of the master IP

INSTANCE_TAGS
  A space-delimited list of the instance's tags.

NODE_NAME
  The target node of this operation (not the node on which the hook
  runs).

NODE_PIP
  The primary IP of the target node (the one over which inter-node
  communication is done).

NODE_SIP
  The secondary IP of the target node (the one over which drbd
  replication is done). This can be equal to the primary ip, in case
  the cluster is not dual-homed.

FORCE
  This is provided by some operations when the user gave this flag.

IGNORE_CONSISTENCY
  The user has specified this flag. It is used when failing over
  instances in case the primary node is down.

ADD_MODE
  The mode of the instance create: either *create* for create from
  scratch or *import* for restoring from an exported image.

SRC_NODE, SRC_PATH, SRC_IMAGE
  In case the instance has been added by import, these variables are
  defined and point to the source node, source path (the directory
  containing the image and the config file) and the source disk image
  file.

NEW_SECONDARY
  The name of the node on which the new mirror component is being
  added (for replace disk). This can be the name of the current
  secondary, if the new mirror is on the same secondary. For
  migrations/failovers, this is the old primary node.

OLD_SECONDARY
  The name of the old secondary in the replace-disks command. Note that
  this can be equal to the new secondary if the secondary node hasn't
  actually changed. For migrations/failovers, this is the new primary
  node.

OLD_PRIMARY, NEW_PRIMARY
  For migrations/failovers, the old and respectively new primary
  nodes. These two mirror the NEW_SECONDARY/OLD_SECONDARY variables

EXPORT_MODE
  The instance export mode. Either "remote" or "local".

EXPORT_NODE
  The node on which the exported image of the instance was done.

EXPORT_DO_SHUTDOWN
  This variable tells if the instance has been shutdown or not while
  doing the export. In the "was shutdown" case, it's likely that the
  filesystem is consistent, whereas in the "did not shutdown" case,
  the filesystem would need a check (journal replay or full fsck) in
  order to guarantee consistency.

REMOVE_INSTANCE
  Whether the instance was removed from the node.

SHUTDOWN_TIMEOUT
  Amount of time to wait for the instance to shutdown.

TIMEOUT
  Amount of time to wait before aborting the op.

OLD_NAME, NEW_NAME
  Old/new name of the node group.

GROUP_NAME
  The name of the node group.

NEW_ALLOC_POLICY
  The new allocation policy for the node group.

CLUSTER_TAGS
  The list of cluster tags, space separated.

NODE_TAGS_<name>
  The list of tags for node *<name>*, space separated.

Examples
--------

The startup of an instance will pass this environment to the hook
script::

  GANETI_CLUSTER=cluster1.example.com
  GANETI_DATA_DIR=/var/lib/ganeti
  GANETI_FORCE=False
  GANETI_HOOKS_PATH=instance-start
  GANETI_HOOKS_PHASE=post
  GANETI_HOOKS_VERSION=2
  GANETI_INSTANCE_DISK0_MODE=rw
  GANETI_INSTANCE_DISK0_SIZE=128
  GANETI_INSTANCE_DISK_COUNT=1
  GANETI_INSTANCE_DISK_TEMPLATE=drbd
  GANETI_INSTANCE_MEMORY=128
  GANETI_INSTANCE_NAME=instance2.example.com
  GANETI_INSTANCE_NIC0_BRIDGE=xen-br0
  GANETI_INSTANCE_NIC0_IP=
  GANETI_INSTANCE_NIC0_MAC=aa:00:00:a5:91:58
  GANETI_INSTANCE_NIC_COUNT=1
  GANETI_INSTANCE_OS_TYPE=debootstrap
  GANETI_INSTANCE_PRIMARY=node3.example.com
  GANETI_INSTANCE_SECONDARY=node5.example.com
  GANETI_INSTANCE_STATUS=down
  GANETI_INSTANCE_VCPUS=1
  GANETI_MASTER=node1.example.com
  GANETI_OBJECT_TYPE=INSTANCE
  GANETI_OP_CODE=OP_INSTANCE_STARTUP
  GANETI_OP_TARGET=instance2.example.com

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
