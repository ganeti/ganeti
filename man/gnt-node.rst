gnt-node(8) Ganeti | Version @GANETI_VERSION@
=============================================

Name
----

gnt-node - Node administration

Synopsis
--------

**gnt-node** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-node** is used for managing the (physical) nodes in the
Ganeti system.

COMMANDS
--------

ADD
~~~

| **add** [\--readd] [{-s|\--secondary-ip} *secondary\_ip*]
| [{-g|\--node-group} *nodegroup*]
| [\--master-capable=``yes|no``] [\--vm-capable=``yes|no``]
| [\--node-parameters *ndparams*]
| [\--disk-state *diskstate*]
| [\--hypervisor-state *hvstate*]
| {*nodename*}

Adds the given node to the cluster.

This command is used to join a new node to the cluster. You will
have to provide the password for root of the node to be able to add
the node in the cluster. The command needs to be run on the Ganeti
master.

Note that the command is potentially destructive, as it will
forcibly join the specified host the cluster, not paying attention
to its current status (it could be already in a cluster, etc.)

The ``-s (--secondary-ip)`` is used in dual-home clusters and
specifies the new node's IP in the secondary network. See the
discussion in **gnt-cluster**(8) for more information.

In case you're readding a node after hardware failure, you can use
the ``--readd`` parameter. In this case, you don't need to pass the
secondary IP again, it will reused from the cluster. Also, the
drained and offline flags of the node will be cleared before
re-adding it.

The ``--force-join`` option is to proceed with adding a node even if it already
appears to belong to another cluster. This is used during cluster merging, for
example.

The ``-g (--node-group)`` option is used to add the new node into a
specific node group, specified by UUID or name. If only one node group
exists you can skip this option, otherwise it's mandatory.

The ``vm_capable``, ``master_capable``, ``ndparams``, ``diskstate`` and
``hvstate`` options are described in **ganeti**(7), and are used to set
the properties of the new node.

The command performs some operations that change the state of the master
and the new node, like copying certificates and starting the node daemon
on the new node, or updating ``/etc/hosts`` on the master node.  If the
command fails at a later stage, it doesn't undo such changes.  This
should not be a problem, as a successful run of ``gnt-node add`` will
bring everything back in sync.

Example::

    # gnt-node add node5.example.com
    # gnt-node add -s 192.0.2.5 node5.example.com
    # gnt-node add -g group2 -s 192.0.2.9 node9.group2.example.com


ADD-TAGS
~~~~~~~~

**add-tags** [\--from *file*] {*nodename*} {*tag*...}

Add tags to the given node. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be
extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line
(if you do, both sources will be used). A file name of - will be
interpreted as stdin.

EVACUATE
~~~~~~~~

| **evacuate** [-f] [\--early-release]
| [{-I|\--iallocator} *NAME* \| {-n|\--new-secondary} *destination\_node*]
| [{-p|\--primary-only} \| {-s|\--secondary-only} ]
|  {*node*}

This command will move instances away from the given node. If
``--primary-only`` is given, only primary instances are evacuated, with
``--secondary-only`` only secondaries. If neither is given, all
instances are evacuated. It works only for instances having a drbd disk
template.

The new location for the instances can be specified in two ways:

- as a single node for all instances, via the ``-n (--new-secondary)``
  option

- or via the ``-I (--iallocator)`` option, giving a script name as
  parameter, so each instance will be in turn placed on the (per the
  script) optimal node

The ``--early-release`` changes the code so that the old storage on
node being evacuated is removed early (before the resync is
completed) and the internal Ganeti locks are also released for both
the current secondary and the new secondary, thus allowing more
parallelism in the cluster operation. This should be used only when
recovering from a disk failure on the current secondary (thus the
old storage is already broken) or when the storage on the primary
node is known to be fine (thus we won't need the old storage for
potential recovery).

Note that this command is equivalent to using per-instance commands for
each affected instance individually:

- ``--primary-only`` is equivalent to ``gnt-instance
  failover/migration`` for non-DRBD instances, but for DRBD instances
  it's different, and usually is a slow process (it will change the
  primary to another node while keeping the secondary, this requiring
  data copies, whereas failover/migrate will only toggle the
  primary/secondary roles, a fast process)
- ``--secondary-only`` is equivalent to ``gnt-instance replace-disks``
  in the secondary node change mode (only valid for DRBD instances)
- when neither of the above is done a combination of the two cases is run

Example::

    # gnt-node evacuate -I hail node3.example.com


FAILOVER
~~~~~~~~

**failover** [-f] [\--ignore-consistency] {*node*}

This command will fail over all instances having the given node as
primary to their secondary nodes. This works only for instances having
a drbd disk template.

Normally the failover will check the consistency of the disks before
failing over the instance. If you are trying to migrate instances off
a dead node, this will fail. Use the ``--ignore-consistency`` option
for this purpose.

Example::

    # gnt-node failover node1.example.com


INFO
~~~~

**info** [*node*...]

Show detailed information about the nodes in the cluster. If you
don't give any arguments, all nodes will be shows, otherwise the
output will be restricted to the given names.

LIST
~~~~

| **list**
| [\--no-headers] [\--separator=*SEPARATOR*]
| [\--units=*UNITS*] [-v] [{-o|\--output} *[+]FIELD,...*]
| [\--filter]
| [node...]

Lists the nodes in the cluster.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The units used to display the numeric values in the output varies,
depending on the options given. By default, the values will be
formatted in the most appropriate unit. If the ``--separator``
option is given, then the values are shown in mebibytes to allow
parsing by scripts. In both cases, the ``--units`` option can be
used to enforce a given output unit.

Queries of nodes will be done in parallel with any running jobs. This might
give inconsistent results for the free disk/memory.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti(7)**).

The ``-o (--output)`` option takes a comma-separated list of output
fields. The available fields and their meaning are:

@QUERY_FIELDS_NODE@

If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

Note that some of these fields are known from the configuration of the
cluster (e.g. ``name``, ``pinst``, ``sinst``, ``pip``, ``sip``) and thus
the master does not need to contact the node for this data (making the
listing fast if only fields from this set are selected), whereas the
other fields are "live" fields and require a query to the cluster nodes.

Depending on the virtualization type and implementation details, the
``mtotal``, ``mnode`` and ``mfree`` fields may have slighly varying
meanings. For example, some solutions share the node memory with the
pool of memory used for instances (KVM), whereas others have separate
memory for the node and for the instances (Xen).

If exactly one argument is given and it appears to be a query filter
(see **ganeti(7)**), the query result is filtered accordingly. For
ambiguous cases (e.g. a single field name as a filter) the ``--filter``
(``-F``) option forces the argument to be treated as a filter (e.g.
``gnt-node list -F master_candidate``).

If no node names are given, then all nodes are queried. Otherwise,
only the given nodes will be listed.


LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

Lists available fields for nodes.


LIST-TAGS
~~~~~~~~~

**list-tags** {*nodename*}

List the tags of the given node.

MIGRATE
~~~~~~~

**migrate** [-f] [\--non-live] [\--migration-mode=live\|non-live]
[\--ignore-ipolicy] {*node*}

This command will migrate all instances having the given node as
primary to their secondary nodes. This works only for instances
having a drbd disk template.

As for the **gnt-instance migrate** command, the options
``--no-live``, ``--migration-mode`` and ``--no-runtime-changes``
can be given to influence the migration type.

If ``--ignore-ipolicy`` is given any instance policy violations occuring
during this operation are ignored.

Example::

    # gnt-node migrate node1.example.com


MODIFY
~~~~~~

| **modify** [-f] [\--submit]
| [{-C|\--master-candidate} ``yes|no``]
| [{-D|\--drained} ``yes|no``] [{-O|\--offline} ``yes|no``]
| [\--master-capable=``yes|no``] [\--vm-capable=``yes|no``] [\--auto-promote]
| [{-s|\--secondary-ip} *secondary_ip*]
| [\--node-parameters *ndparams*]
| [\--node-powered=``yes|no``]
| [\--hypervisor-state *hvstate*]
| [\--disk-state *diskstate*]
| {*node*}

This command changes the role of the node. Each options takes
either a literal yes or no, and only one option should be given as
yes. The meaning of the roles and flags are described in the
manpage **ganeti**(7).

The option ``--node-powered`` can be used to modify state-of-record if
it doesn't reflect the reality anymore.

In case a node is demoted from the master candidate role, the
operation will be refused unless you pass the ``--auto-promote``
option. This option will cause the operation to lock all cluster nodes
(thus it will not be able to run in parallel with most other jobs),
but it allows automated maintenance of the cluster candidate pool. If
locking all cluster node is too expensive, another option is to
promote manually another node to master candidate before demoting the
current one.

Example (setting a node offline, which will demote it from master
candidate role if is in that role)::

    # gnt-node modify --offline=yes node1.example.com

The ``-s (--secondary-ip)`` option can be used to change the node's
secondary ip. No drbd instances can be running on the node, while this
operation is taking place.

Example (setting the node back to online and master candidate)::

    # gnt-node modify --offline=no --master-candidate=yes node1.example.com


REMOVE
~~~~~~

**remove** {*nodename*}

Removes a node from the cluster. Instances must be removed or
migrated to another cluster before.

Example::

    # gnt-node remove node5.example.com


REMOVE-TAGS
~~~~~~~~~~~

**remove-tags** [\--from *file*] {*nodename*} {*tag*...}

Remove tags from the given node. If any of the tags are not
existing on the node, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line (if
you do, tags from both sources will be removed). A file name of - will
be interpreted as stdin.

VOLUMES
~~~~~~~

| **volumes** [\--no-headers] [\--human-readable]
| [\--separator=*SEPARATOR*] [{-o|\--output} *FIELDS*]
| [*node*...]

Lists all logical volumes and their physical disks from the node(s)
provided.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The units used to display the numeric values in the output varies,
depending on the options given. By default, the values will be
formatted in the most appropriate unit. If the ``--separator``
option is given, then the values are shown in mebibytes to allow
parsing by scripts. In both cases, the ``--units`` option can be
used to enforce a given output unit.

The ``-o (--output)`` option takes a comma-separated list of output
fields. The available fields and their meaning are:

node
    the node name on which the volume exists

phys
    the physical drive (on which the LVM physical volume lives)

vg
    the volume group name

name
    the logical volume name

size
    the logical volume size

instance
    The name of the instance to which this volume belongs, or (in case
    it's an orphan volume) the character "-"


Example::

    # gnt-node volumes node5.example.com
    Node              PhysDev   VG    Name                                 Size Instance
    node1.example.com /dev/hdc1 xenvg instance1.example.com-sda_11000.meta 128  instance1.example.com
    node1.example.com /dev/hdc1 xenvg instance1.example.com-sda_11001.data 256  instance1.example.com


LIST-STORAGE
~~~~~~~~~~~~

| **list-storage** [\--no-headers] [\--human-readable]
| [\--separator=*SEPARATOR*] [\--storage-type=*STORAGE\_TYPE*]
| [{-o|\--output} *FIELDS*]
| [*node*...]

Lists the available storage units and their details for the given
node(s).

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The units used to display the numeric values in the output varies,
depending on the options given. By default, the values will be
formatted in the most appropriate unit. If the ``--separator``
option is given, then the values are shown in mebibytes to allow
parsing by scripts. In both cases, the ``--units`` option can be
used to enforce a given output unit.

The ``--storage-type`` option can be used to choose a storage unit
type. Possible choices are lvm-pv, lvm-vg or file.

The ``-o (--output)`` option takes a comma-separated list of output
fields. The available fields and their meaning are:

node
    the node name on which the volume exists

type
    the type of the storage unit (currently just what is passed in via
    ``--storage-type``)

name
    the path/identifier of the storage unit

size
    total size of the unit; for the file type see a note below

used
    used space in the unit; for the file type see a note below

free
    available disk space

allocatable
    whether we the unit is available for allocation (only lvm-pv can
    change this setting, the other types always report true)


Note that for the "file" type, the total disk space might not equal
to the sum of used and free, due to the method Ganeti uses to
compute each of them. The total and free values are computed as the
total and free space values for the filesystem to which the
directory belongs, but the used space is computed from the used
space under that directory *only*, which might not be necessarily
the root of the filesystem, and as such there could be files
outside the file storage directory using disk space and causing a
mismatch in the values.

Example::

    node1# gnt-node list-storage node2
    Node  Type   Name        Size Used   Free Allocatable
    node2 lvm-pv /dev/sda7 673.8G 1.5G 672.3G Y
    node2 lvm-pv /dev/sdb1 698.6G   0M 698.6G Y


MODIFY-STORAGE
~~~~~~~~~~~~~~

**modify-storage** [``--allocatable=yes|no``]
{*node*} {*storage-type*} {*volume-name*}

Modifies storage volumes on a node. Only LVM physical volumes can
be modified at the moment. They have a storage type of "lvm-pv".

Example::

    # gnt-node modify-storage --allocatable no node5.example.com lvm-pv /dev/sdb1


REPAIR-STORAGE
~~~~~~~~~~~~~~

**repair-storage** [\--ignore-consistency] {*node*} {*storage-type*}
{*volume-name*}

Repairs a storage volume on a node. Only LVM volume groups can be
repaired at this time. They have the storage type "lvm-vg".

On LVM volume groups, **repair-storage** runs ``vgreduce
--removemissing``.



**Caution:** Running this command can lead to data loss. Use it with
care.

The ``--ignore-consistency`` option will ignore any inconsistent
disks (on the nodes paired with this one). Use of this option is
most likely to lead to data-loss.

Example::

    # gnt-node repair-storage node5.example.com lvm-vg xenvg


POWERCYCLE
~~~~~~~~~~

**powercycle** [``--yes``] [``--force``] {*node*}

This command (tries to) forcefully reboot a node. It is a command
that can be used if the node environment is broken, such that the
admin can no longer login over SSH, but the Ganeti node daemon is
still working.

Note that this command is not guaranteed to work; it depends on the
hypervisor how effective is the reboot attempt. For Linux, this
command requires the kernel option ``CONFIG_MAGIC_SYSRQ`` to be
enabled.

The ``--yes`` option can be used to skip confirmation, while the
``--force`` option is needed if the target node is the master
node.

POWER
~~~~~

**power** [``--force``] [``--ignore-status``] [``--all``]
[``--power-delay``] on|off|cycle|status [*nodes*]

This command calls out to out-of-band management to change the power
state of given node. With ``status`` you get the power status as reported
by the out-of-band managment script.

Note that this command will only work if the out-of-band functionality
is configured and enabled on the cluster. If this is not the case,
please use the **powercycle** command above.

Using ``--force`` you skip the confirmation to do the operation.
Currently this only has effect on ``off`` and ``cycle``. On those two
you can *not* operate on the master. However, the command will provide
you with the command to invoke to operate on the master nerver-mind.
This is considered harmful and Ganeti does not support the use of it.

Providing ``--ignore-status`` will ignore the offline=N state of a node
and continue with power off.

``--power-delay`` specifies the time in seconds (factions allowed)
waited between powering on the next node. This is by default 2 seconds
but can increased if needed with this option.

*nodes* are optional. If not provided it will call out for every node in
the cluster. Except for the ``off`` and ``cycle`` command where you've
to explicit use ``--all`` to select all.


HEALTH
~~~~~~

**health** [*nodes*]

This command calls out to out-of-band management to ask for the health status
of all or given nodes. The health contains the node name and then the items
element with their status in a ``item=status`` manner. Where ``item`` is script
specific and ``status`` can be one of ``OK``, ``WARNING``, ``CRITICAL`` or
``UNKNOWN``. Items with status ``WARNING`` or ``CRITICAL`` are logged and
annotated in the command line output.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
