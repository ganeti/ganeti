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
| [\--no-node-setup]
| {*nodename*}

Adds the given node to the cluster.

This command is used to join a new node to the cluster. You will
have to provide credentials to ssh as root to the node to be added.
Forwarding of an ssh agent (the ``-A`` option of ssh) works, if an
appropriate authorized key is set up on the node to be added. If
the other node allows password authentication for root, another
way of providing credentials is to provide the root password once
asked for it. The command needs to be run on the Ganeti master.

Note that the command is potentially destructive, as it will
forcibly join the specified host to the cluster, not paying attention
to its current status (it could be already in a cluster, etc.)

The ``-s (--secondary-ip)`` is used in dual-home clusters and
specifies the new node's IP in the secondary network. See the
discussion in **gnt-cluster**\(8) for more information.

In case you're re-adding a node after hardware failure, you can use
the ``--readd`` parameter. In this case, you don't need to pass the
secondary IP again, it will be reused from the cluster. Also, the
drained and offline flags of the node will be cleared before
re-adding it. Note that even for re-added nodes, a new SSH key is
generated and distributed and previous Ganeti keys are removed
from the machine.

The ``-g (--node-group)`` option is used to add the new node into a
specific node group, specified by UUID or name. If only one node group
exists you can skip this option, otherwise it's mandatory.

The ``--no-node-setup`` option that used to prevent Ganeti from performing
the initial SSH setup on the new node is no longer valid. Instead,
Ganeti considers the ``modify ssh setup`` configuration parameter
(which is set using ``--no-ssh-init`` during cluster initialization)
to determine whether or not to do the SSH setup on a new node or not.
If this parameter is set to ``False``, Ganeti will not touch the SSH
keys or the ``authorized_keys`` file of the node at all. Using this option,
it lies in the administrators responsibility to ensure SSH connectivity
between the hosts by other means.

The ``vm_capable``, ``master_capable``, ``ndparams``, ``diskstate`` and
``hvstate`` options are described in **ganeti**\(7), and are used to set
the properties of the new node.

The command performs some operations that change the state of the master
and the new node, like copying certificates and starting the node daemon
on the new node, or updating ``/etc/hosts`` on the master node.  If the
command fails at a later stage, it doesn't undo such changes.  This
should not be a problem, as a successful run of ``gnt-node add`` will
bring everything back in sync.

If the node was previously part of another cluster and still has daemons
running, the ``node-cleanup`` tool can be run on the machine to be added
to clean remains of the previous cluster from the node.

Example::

    # gnt-node add node5.example.com
    # gnt-node add -s 192.0.2.5 node5.example.com
    # gnt-node add -g group2 -s 192.0.2.9 node9.group2.example.com


EVACUATE
~~~~~~~~

| **evacuate** [-f] [\--early-release] [\--submit] [\--print-jobid]
| [{-I|\--iallocator} *NAME* \| {-n|\--new-secondary} *destination\_node*]
| [--ignore-soft-errors]
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
  parameter (or ``.`` to use the default allocator), so each instance
  will be in turn placed on the (per the script) optimal node

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

- ``--primary-only`` is equivalent to performing ``gnt-instance
  migrate`` for every primary instance running on the node that can be
  migrated and ``gnt-instance failover`` for every primary instance that
  cannot be migrated.
- ``--secondary-only`` is equivalent to ``gnt-instance replace-disks``
  in secondary node change mode (``--new-secondary``) for every DRBD
  instance that the node is a secondary for.
- when neither of the above is done a combination of the two cases is run

Note that the iallocator currently only considers disk information of
the default disk template, even if the instance's disk templates differ
from that.

The ``--ignore-soft-errors`` option is passed through to the allocator.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-node evacuate -I hail node3.example.com

Note that, due to an issue with the iallocator interface, evacuation of
all instances at once is not yet implemented. Full evacuation can
currently be achieved by sequentially evacuating primaries and
secondaries.
::

    # gnt-node evacuate -p node3.example.com
    # gnt-node evacuate -s node3.example.com


FAILOVER
~~~~~~~~

**failover** [-f] [\--ignore-consistency] {*node*}

This command will fail over all instances having the given node as
primary to their secondary nodes. This works only for instances having
a drbd disk template.

Note that failover will stop any running instances on the given node and
restart them again on the new primary.
See also FAILOVER in **gnt-instance**\(8).

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
special field states (see **ganeti**\(7)).

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
``mtotal``, ``mnode`` and ``mfree`` fields may have slightly varying
meanings. For example, some solutions share the node memory with the
pool of memory used for instances (KVM), whereas others have separate
memory for the node and for the instances (Xen).

Note that the field 'dtotal' and 'dfree' refer to the storage type
that is defined by the default disk template. The default disk template
is the first on in the list of cluster-wide enabled disk templates and
can be set with ``gnt-cluster modify``. Currently, only the disk
templates 'plain', 'drbd', 'file', and 'sharedfile' support storage
reporting, for all others '0' is displayed.

If exactly one argument is given and it appears to be a query filter
(see **ganeti**\(7)), the query result is filtered accordingly. For
ambiguous cases (e.g. a single field name as a filter) the ``--filter``
(``-F``) option forces the argument to be treated as a filter (e.g.
``gnt-node list -F master_candidate``).

If no node names are given, then all nodes are queried. Otherwise,
only the given nodes will be listed.


LIST-DRBD
~~~~~~~~~

**list-drbd** [\--no-headers] [\--separator=*SEPARATOR*] node

Lists the mapping of DRBD minors for a given node. This outputs a static
list of fields (it doesn't accept the ``--output`` option), as follows:

``Node``
  The (full) name of the node we are querying
``Minor``
  The DRBD minor
``Instance``
  The instance the DRBD minor belongs to
``Disk``
  The disk index that the DRBD minor belongs to
``Role``
  Either ``primary`` or ``secondary``, denoting the role of the node for
  the instance (note: this is not the live status of the DRBD device,
  but the configuration value)
``PeerNode``
  The node that the minor is connected to on the other end

This command can be used as a reverse lookup (from node and minor) to a
given instance, which can be useful when debugging DRBD issues.

Note that this command queries Ganeti via **ganeti-confd**\(8), so
it won't be available if support for ``confd`` has not been enabled at
build time; furthermore, in Ganeti 2.6 this is only available via the
Haskell version of confd (again selected at build time).

LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

Lists available fields for nodes.


MIGRATE
~~~~~~~

| **migrate** [-f] [\--non-live] [\--migration-mode=live\|non-live]
| [\--ignore-ipolicy] [\--submit] [\--print-jobid] {*node*}

This command will migrate all instances having the given node as
primary to their secondary nodes. This works only for instances
having a drbd disk template.

As for the **gnt-instance migrate** command, the options
``--no-live``, ``--migration-mode`` and ``--no-runtime-changes``
can be given to influence the migration type.

If ``--ignore-ipolicy`` is given any instance policy violations
occurring during this operation are ignored.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example::

    # gnt-node migrate node1.example.com


MODIFY
~~~~~~

| **modify** [-f] [\--submit] [\--print-jobid]
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
manpage **ganeti**\(7).

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
operation is taking place. Remember that the secondary ip must be
reachable from the master secondary ip, when being changed, so be sure
that the node has the new IP already configured and active. In order to
convert a cluster from single homed to multi-homed or vice versa
``--force`` is needed as well, and the target node for the first change
must be the master.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

Example (setting the node back to online and master candidate)::

    # gnt-node modify --offline=no --master-candidate=yes node1.example.com


REMOVE
~~~~~~

**remove** {*nodename*}

Removes a node from the cluster. Instances must be removed or
migrated to another cluster before.

Example::

    # gnt-node remove node5.example.com


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
type. Possible choices are lvm-pv, lvm-vg, file, sharedfile and gluster.

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

| **modify-storage** [\--allocatable={yes|no}] [\--submit] [\--print-jobid]
| {*node*} {*storage-type*} {*volume-name*}

Modifies storage volumes on a node. Only LVM physical volumes can
be modified at the moment. They have a storage type of "lvm-pv".

Example::

    # gnt-node modify-storage --allocatable no node5.example.com lvm-pv /dev/sdb1


REPAIR-STORAGE
~~~~~~~~~~~~~~

| **repair-storage** [\--ignore-consistency] ]\--submit]
| {*node*} {*storage-type*} {*volume-name*}

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

**powercycle** [\--yes] [\--force] [\--submit] [\--print-jobid] {*node*}

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

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

POWER
~~~~~

**power** [``--force``] [``--ignore-status``] [``--all``]
[``--power-delay``] on|off|cycle|status [*nodes*]

This command calls out to out-of-band management to change the power
state of given node. With ``status`` you get the power status as reported
by the out-of-band management script.

Note that this command will only work if the out-of-band functionality
is configured and enabled on the cluster. If this is not the case,
please use the **powercycle** command above.

Currently this only has effect for ``off`` and ``cycle``.  For safety,
Ganeti will not allow either of these operations to be run on the master
node. However, it will print a command line which can then be run
manually on the master. Note that powering off the master is potentially
dangerous, and Ganeti does not support doing this.

Providing ``--force`` will skip confirmations for the operation.

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


RESTRICTED-COMMAND
~~~~~~~~~~~~~~~~~~

| **restricted-command** [-M] [\--sync]
| { -g *group* *command* | *command* *nodes*... }

Executes a restricted command on the specified nodes. Restricted commands are
not arbitrary, but must reside in
``@SYSCONFDIR@/ganeti/restricted-commands`` on a node, either as a regular
file or as a symlink. The directory must be owned by root and not be
world- or group-writable. If a command fails verification or otherwise
fails to start, the node daemon log must be consulted for more detailed
information.

Example for running a command on two nodes::

    # gnt-node restricted-command mycommand \
      node1.example.com node2.example.com

The ``-g`` option can be used to run a command only on a specific node
group, e.g.::

    # gnt-node restricted-command -g default mycommand

The ``-M`` option can be used to prepend the node name to all command
output lines. ``--sync`` forces the opcode to acquire the node lock(s)
in exclusive mode.

Tags
~~~~

ADD-TAGS
^^^^^^^^

**add-tags** [\--from *file*] {*nodename*} {*tag*...}

Add tags to the given node. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be
extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line
(if you do, both sources will be used). A file name of - will be
interpreted as stdin.

LIST-TAGS
^^^^^^^^^

**list-tags** {*nodename*}

List the tags of the given node.

REMOVE-TAGS
^^^^^^^^^^^

**remove-tags** [\--from *file*] {*nodename*} {*tag*...}

Remove tags from the given node. If any of the tags are not
existing on the node, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line (if
you do, tags from both sources will be removed). A file name of - will
be interpreted as stdin.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
