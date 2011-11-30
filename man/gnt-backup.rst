gnt-backup(8) Ganeti | Version @GANETI_VERSION@
===============================================

Name
----

gnt-backup - Ganeti instance import/export

Synopsis
--------

**gnt-backup** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-backup** is used for importing and exporting instances
and their configuration from a Ganeti system. It is useful for
backing up instances and also to migrate them between clusters.

COMMANDS
--------

EXPORT
~~~~~~

**export** {-n *node*} [--shutdown-timeout=*N*] [--noshutdown]
[--remove-instance] [--ignore-remove-failures] {*instance*}

Exports an instance to the target node. All the instance data and
its configuration will be exported under the
``@CUSTOM_EXPORT_DIR@/``*instance* directory on the target node.

The ``--shutdown-timeout`` is used to specify how much time to wait
before forcing the shutdown (xm destroy in xen, killing the kvm
process, for kvm). By default two minutes are given to each
instance to stop.

The ``--noshutdown`` option will create a snapshot disk of the
instance without shutting it down first. While this is faster and
involves no downtime, it cannot be guaranteed that the instance
data will be in a consistent state in the exported dump.

The ``--remove`` option can be used to remove the instance after it
was exported. This is useful to make one last backup before
removing the instance.

The exit code of the command is 0 if all disks were backed up
successfully, 1 if no data was backed up or if the configuration
export failed, and 2 if just some of the disks failed to backup.
The exact details of the failures will be shown during the command
execution (and will be stored in the job log). It is recommended
that for any non-zero exit code, the backup is considered invalid,
and retried.

Example::

    # gnt-backup export -n node1.example.com instance3.example.com


IMPORT
~~~~~~

| **import**
| {-n *node[:secondary-node]* | --iallocator *name*}
| [--disk *N*:size=*VAL* [,vg=*VG*], [,mode=*ro|rw*]...]
| [--net *N* [:options...] | --no-nics]
| [-B *BEPARAMS*]
| [-H *HYPERVISOR* [: option=*value*... ]]
| [--src-node=*source-node*] [--src-dir=*source-dir*]
| [-t [diskless | plain | drbd | file]]
| [--identify-defaults]
| {*instance*}

Imports a new instance from an export residing on *source-node* in
*source-dir*. *instance* must be in DNS and resolve to a IP in the
same network as the nodes in the cluster. If the source node and
directory are not passed, the last backup in the cluster is used,
as visible with the **list** command.

The ``disk`` option specifies the parameters for the disks of the
instance. The numbering of disks starts at zero. For each disk, at
least the size needs to be given, and optionally the access mode
(read-only or the default of read-write) and LVM volume group can also
be specified. The size is interpreted (when no unit is given) in
mebibytes. You can also use one of the suffixes m, g or t to specificy
the exact the units used; these suffixes map to mebibytes, gibibytes
and tebibytes.

Alternatively, a single-disk instance can be created via the ``-s``
option which takes a single argument, the size of the disk. This is
similar to the Ganeti 1.2 version (but will only create one disk).

If no disk information is passed, the disk configuration saved at
export time will be used.

The minimum disk specification is therefore empty (export information
will be used), a single disk can be specified as ``--disk 0:size=20G``
(or ``-s 20G`` when using the ``-s`` option), and a three-disk
instance can be specified as ``--disk 0:size=20G --disk 1:size=4G
--disk 2:size=100G``.

The NICs of the instances can be specified via the ``--net``
option. By default, the NIC configuration of the original
(exported) instance will be reused. Each NIC can take up to three
parameters (all optional):

mac
    either a value or ``generate`` to generate a new unique MAC, or
    ``auto`` to reuse the old MAC

ip
    specifies the IP address assigned to the instance from the Ganeti
    side (this is not necessarily what the instance will use, but what
    the node expects the instance to use)

mode
    specifies the connection mode for this nic: ``routed`` or
    ``bridged``.

link
    in bridged mode specifies the bridge to attach this NIC to, in
    routed mode it's intended to differentiate between different
    routing tables/instance groups (but the meaning is dependent on
    the network script in use, see **gnt-cluster**(8) for more
    details)

Of these ``mode`` and ``link`` are nic parameters, and inherit their
default at cluster level.

If no network is desired for the instance, you should create a single
empty NIC and delete it afterwards via **gnt-instance modify --net
delete**.

The ``-B`` option specifies the backend parameters for the
instance. If no such parameters are specified, the values are
inherited from the export. Possible parameters are:

maxmem
    the maximum memory size of the instance; as usual, suffixes can be
    used to denote the unit, otherwise the value is taken in mebibytes

minmem
    the minimum memory size of the instance; as usual, suffixes can be
    used to denote the unit, otherwise the value is taken in mebibytes

vcpus
    the number of VCPUs to assign to the instance (if this value makes
    sense for the hypervisor)

auto_balance
    whether the instance is considered in the N+1 cluster checks
    (enough redundancy in the cluster to survive a node failure)


The ``-t`` options specifies the disk layout type for the instance.
If not passed, the configuration of the original instance is used.
The available choices are:

diskless
    This creates an instance with no disks. Its useful for testing only
    (or other special cases).

plain
    Disk devices will be logical volumes.

drbd
    Disk devices will be drbd (version 8.x) on top of lvm volumes.

file
    Disk devices will be backed up by files, under the directory
    ``@RPL_FILE_STORAGE_DIR@``. By default, each instance will get a
    directory (as its own name) under this path, and each disk is
    stored as individual files in this (instance-specific) directory.


The ``--iallocator`` option specifies the instance allocator plugin
to use. If you pass in this option the allocator will select nodes
for this instance automatically, so you don't need to pass them
with the ``-n`` option. For more information please refer to the
instance allocator documentation.

The optional second value of the ``--node`` is used for the drbd
template and specifies the remote node.

The ``--src-dir`` option allows importing instances from a directory
below ``@CUSTOM_EXPORT_DIR@``.

Since many of the parameters are by default read from the exported
instance information and used as such, the new instance will have
all parameters explicitly specified, the opposite of a newly added
instance which has most parameters specified via cluster defaults.
To change the import behaviour to recognize parameters whose saved
value matches the current cluster default and mark it as such
(default value), pass the ``--identify-defaults`` option. This will
affect the hypervisor, backend and NIC parameters, both read from
the export file and passed in via the command line.

Example for identical instance import::

    # gnt-backup import -n node1.example.com instance3.example.com


Explicit configuration example::

    # gnt-backup import -t plain --disk 0:size=1G -B memory=512 \
    > -n node1.example.com \
    > instance3.example.com


LIST
~~~~

**list** [--node=*NODE*]

Lists the exports currently available in the default directory in
all the nodes of the current cluster, or optionally only a subset
of them specified using the ``--node`` option (which can be used
multiple times)

Example::

    # gnt-backup list --nodes node1 --nodes node2


REMOVE
~~~~~~

**remove** {instance_name}

Removes the backup for the given instance name, if any. If the backup
was for a deleted instance, it is needed to pass the FQDN of the
instance, and not only the short hostname.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
