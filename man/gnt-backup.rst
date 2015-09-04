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

| **export** {-n *node*}
| [\--shutdown-timeout=*N*] [\--noshutdown] [\--remove-instance]
| [\--ignore-remove-failures] [\--submit] [\--print-jobid]
| [\--transport-compression=*compression-mode*]
| [\--zero-free-space] [\--zeroing-timeout-fixed]
| [\--zeroing-timeout-per-mib] [\--long-sleep]
| {*instance*}

Exports an instance to the target node. All the instance data and
its configuration will be exported under the
``@CUSTOM_EXPORT_DIR@/$instance`` directory on the target node.

The ``--transport-compression`` option is used to specify which
compression mode is used to try and speed up moves during the export.
Valid values are 'none', and any values defined in the
'compression_tools' cluster parameter.

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

The ``--zero-free-space`` option can be used to zero the free space
of the instance prior to exporting it, saving space if compression
is used. The ``--zeroing-timeout-fixed`` and
``--zeroing-timeout-per-mib`` options control the timeout, the former
determining the minimum time to wait, and the latter how much longer
to wait per MiB of data the instance has.

The ``--long-sleep`` option allows Ganeti to keep the instance shut
down for the entire duration of the export if necessary. This is
needed if snapshots are not supported by the underlying storage type,
or if the creation of snapshots fails for some reason - e.g. lack of
space.

Should the snapshotting or transfer of any of the instance disks
fail, the backup will not complete and any previous backups will be
preserved. The exact details of the failures will be shown during the
command execution (and will be stored in the job log). It is
recommended that for any non-zero exit code, the backup is considered
invalid, and retried.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-backup export -n node1.example.com instance3.example.com


IMPORT
~~~~~~

| **import**
| {-n *node[:secondary-node]* | \--iallocator *name*}
| [\--compress=*compression-mode*]
| [\--disk *N*:size=*VAL* [,vg=*VG*], [,mode=*ro|rw*]...]
| [\--net *N* [:options...] | \--no-nics]
| [-B *BEPARAMS*]
| [-H *HYPERVISOR* [: option=*value*... ]]
| [\--src-node=*source-node*] [\--src-dir=*source-dir*]
| [-t [diskless | plain | drbd | file]]
| [\--identify-defaults]
| [\--ignore-ipolicy]
| [\--submit] [\--print-jobid]
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
    specifies the connection mode for this NIC: ``routed``,
    ``bridged`` or ``openvswitch``

link
    in bridged and openvswitch mode specifies the interface to attach
    this NIC to, in routed mode it's intended to differentiate between
    different routing tables/instance groups (but the meaning is
    dependent on the network script in use, see **gnt-cluster**\(8) for
    more details)

Of these ``mode`` and ``link`` are NIC parameters, and inherit their
default at cluster level.

If no network is desired for the instance, you should create a single
empty NIC and delete it afterwards via **gnt-instance modify \--net
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

always\_failover
    ``True`` or ``False``, whether the instance must be failed over
    (shut down and rebooted) always or it may be migrated (briefly
    suspended)


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
    Disk devices will be backed up by files, under the cluster's
    default file storage directory. By default, each instance will
    get a directory (as its own name) under this path, and each disk
    is stored as individual files in this (instance-specific) directory.

The ``--iallocator`` option specifies the instance allocator plugin
to use. If you pass in this option the allocator will select nodes
for this instance automatically, so you don't need to pass them
with the ``-n`` option. For more information please refer to the
instance allocator documentation.

The optional second value of the ``--node`` is used for the drbd
template and specifies the remote node.

The ``--compress`` option is used to specify which compression mode
is used for moves during the import. Valid values are 'none'
(the default) and 'gzip'.

The ``--src-dir`` option allows importing instances from a directory
below ``@CUSTOM_EXPORT_DIR@``.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

Since many of the parameters are by default read from the exported
instance information and used as such, the new instance will have
all parameters explicitly specified, the opposite of a newly added
instance which has most parameters specified via cluster defaults.
To change the import behaviour to recognize parameters whose saved
value matches the current cluster default and mark it as such
(default value), pass the ``--identify-defaults`` option. This will
affect the hypervisor, backend and NIC parameters, both read from
the export file and passed in via the command line.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example for identical instance import::

    # gnt-backup import -n node1.example.com instance3.example.com


Explicit configuration example::

    # gnt-backup import -t plain --disk 0:size=1G -B memory=512 \
    > -n node1.example.com \
    > instance3.example.com


LIST
~~~~

| **list** [\--node=*NODE*] [\--no-headers] [\--separator=*SEPARATOR*]
| [-o *[+]FIELD,...*]

Lists the exports currently available in the default directory in
all the nodes of the current cluster, or optionally only a subset
of them specified using the ``--node`` option (which can be used
multiple times)

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-o`` option takes a comma-separated list of output fields.
The available fields and their meaning are:

@QUERY_FIELDS_EXPORT@

If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

Example::

    # gnt-backup list --node node1 --node node2


LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

Lists available fields for exports.


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
