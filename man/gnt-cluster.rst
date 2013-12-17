gnt-cluster(8) Ganeti | Version @GANETI_VERSION@
================================================

Name
----

gnt-cluster - Ganeti administration, cluster-wide

Synopsis
--------

**gnt-cluster** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-cluster** is used for cluster-wide administration in the
Ganeti system.

COMMANDS
--------

ACTIVATE-MASTER-IP
~~~~~~~~~~~~~~~~~~

**activate-master-ip**

Activates the master IP on the master node.

COMMAND
~~~~~~~

**command** [-n *node*] [-g *group*] [-M] {*command*}

Executes a command on all nodes. This command is designed for simple
usage. For more complex use cases the commands **dsh**\(1) or **cssh**\(1)
should be used instead.

If the option ``-n`` is not given, the command will be executed on all
nodes, otherwise it will be executed only on the node(s) specified. Use
the option multiple times for running it on multiple nodes, like::

    # gnt-cluster command -n node1.example.com -n node2.example.com date

The ``-g`` option can be used to run a command only on a specific node
group, e.g.::

    # gnt-cluster command -g default date

The ``-M`` option can be used to prepend the node name to all output
lines. The ``--failure-only`` option hides successful commands, making
it easier to see failures.

The command is executed serially on the selected nodes. If the
master node is present in the list, the command will be executed
last on the master. Regarding the other nodes, the execution order
is somewhat alphabetic, so that node2.example.com will be earlier
than node10.example.com but after node1.example.com.

So given the node names node1, node2, node3, node10, node11, with
node3 being the master, the order will be: node1, node2, node10,
node11, node3.

The command is constructed by concatenating all other command line
arguments. For example, to list the contents of the /etc directory
on all nodes, run::

    # gnt-cluster command ls -l /etc

and the command which will be executed will be ``ls -l /etc``.

COPYFILE
~~~~~~~~

| **copyfile** [\--use-replication-network] [-n *node*] [-g *group*]
| {*file*}

Copies a file to all or to some nodes. The argument specifies the
source file (on the current system), the ``-n`` argument specifies
the target node, or nodes if the option is given multiple times. If
``-n`` is not given at all, the file will be copied to all nodes. The
``-g`` option can be used to only select nodes in a specific node group.
Passing the ``--use-replication-network`` option will cause the
copy to be done over the replication network (only matters if the
primary/secondary IPs are different). Example::

    # gnt-cluster -n node1.example.com -n node2.example.com copyfile /tmp/test

This will copy the file /tmp/test from the current node to the two
named nodes.

DEACTIVATE-MASTER-IP
~~~~~~~~~~~~~~~~~~~~

**deactivate-master-ip** [\--yes]

Deactivates the master IP on the master node.

This should be run only locally or on a connection to the node ip
directly, as a connection to the master ip will be broken by this
operation. Because of this risk it will require user confirmation
unless the ``--yes`` option is passed.

DESTROY
~~~~~~~

**destroy** {\--yes-do-it}

Remove all configuration files related to the cluster, so that a
**gnt-cluster init** can be done again afterwards.

Since this is a dangerous command, you are required to pass the
argument *\--yes-do-it.*

EPO
~~~

**epo** [\--on] [\--groups|\--all] [\--power-delay] *arguments*

Performs an emergency power-off on nodes given as arguments. If
``--groups`` is given, arguments are node groups. If ``--all`` is
provided, the whole cluster will be shut down.

The ``--on`` flag recovers the cluster after an emergency power-off.
When powering on the cluster you can use ``--power-delay`` to define the
time in seconds (fractions allowed) waited between powering on
individual nodes.

Please note that the master node will not be turned down or up
automatically.  It will just be left in a state, where you can manully
perform the shutdown of that one node. If the master is in the list of
affected nodes and this is not a complete cluster emergency power-off
(e.g. using ``--all``), you're required to do a master failover to
another node not affected.

GETMASTER
~~~~~~~~~

**getmaster**

Displays the current master node.

INFO
~~~~

**info** [\--roman]

Shows runtime cluster information: cluster name, architecture (32
or 64 bit), master node, node list and instance list.

Passing the ``--roman`` option gnt-cluster info will try to print
its integer fields in a latin friendly way. This allows further
diffusion of Ganeti among ancient cultures.

SHOW-ISPECS-CMD
~~~~~~~~~~~~~~~

**show-ispecs-cmd**

Shows the command line that can be used to recreate the cluster with the
same options relative to specs in the instance policies.

INIT
~~~~

| **init**
| [{-s|\--secondary-ip} *secondary\_ip*]
| [\--vg-name *vg-name*]
| [\--master-netdev *interface-name*]
| [\--master-netmask *netmask*]
| [\--use-external-mip-script {yes \| no}]
| [{-m|\--mac-prefix} *mac-prefix*]
| [\--no-etc-hosts]
| [\--no-ssh-init]
| [\--file-storage-dir *dir*]
| [\--shared-file-storage-dir *dir*]
| [\--gluster-storage-dir *dir*]
| [\--enabled-hypervisors *hypervisors*]
| [{-H|\--hypervisor-parameters} *hypervisor*:*hv-param*=*value*[,*hv-param*=*value*...]]
| [{-B|\--backend-parameters} *be-param*=*value*[,*be-param*=*value*...]]
| [{-N|\--nic-parameters} *nic-param*=*value*[,*nic-param*=*value*...]]
| [{-D|\--disk-parameters} *disk-template*:*disk-param*=*value*[,*disk-param*=*value*...]]
| [\--maintain-node-health {yes \| no}]
| [\--uid-pool *user-id pool definition*]
| [{-I|\--default-iallocator} *default instance allocator*]
| [\--default-iallocator-params *ial-param*=*value*,*ial-param*=*value*]
| [\--primary-ip-version *version*]
| [\--prealloc-wipe-disks {yes \| no}]
| [\--node-parameters *ndparams*]
| [{-C|\--candidate-pool-size} *candidate\_pool\_size*]
| [\--specs-cpu-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [\--specs-disk-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [\--specs-disk-size *spec-param*=*value* [,*spec-param*=*value*...]]
| [\--specs-mem-size *spec-param*=*value* [,*spec-param*=*value*...]]
| [\--specs-nic-count *spec-param*=*value* [,*spec-param*=*value*...]]
| [\--ipolicy-std-specs *spec*=*value* [,*spec*=*value*...]]
| [\--ipolicy-bounds-specs *bounds_ispecs*]
| [\--ipolicy-disk-templates *template* [,*template*...]]
| [\--ipolicy-spindle-ratio *ratio*]
| [\--ipolicy-vcpu-ratio *ratio*]
| [\--disk-state *diskstate*]
| [\--hypervisor-state *hvstate*]
| [\--drbd-usermode-helper *helper*]
| [\--enabled-disk-templates *template* [,*template*...]]
| {*clustername*}

This commands is only run once initially on the first node of the
cluster. It will initialize the cluster configuration, setup the
ssh-keys, start the daemons on the master node, etc. in order to have
a working one-node cluster.

Note that the *clustername* is not any random name. It has to be
resolvable to an IP address using DNS, and it is best if you give the
fully-qualified domain name. This hostname must resolve to an IP
address reserved exclusively for this purpose, i.e. not already in
use.

The cluster can run in two modes: single-home or dual-homed. In the
first case, all traffic (both public traffic, inter-node traffic and
data replication traffic) goes over the same interface. In the
dual-homed case, the data replication traffic goes over the second
network. The ``-s (--secondary-ip)`` option here marks the cluster as
dual-homed and its parameter represents this node's address on the
second network.  If you initialise the cluster with ``-s``, all nodes
added must have a secondary IP as well.

Note that for Ganeti it doesn't matter if the secondary network is
actually a separate physical network, or is done using tunneling,
etc. For performance reasons, it's recommended to use a separate
network, of course.

The ``--vg-name`` option will let you specify a volume group
different than "xenvg" for Ganeti to use when creating instance
disks. This volume group must have the same name on all nodes. Once
the cluster is initialized this can be altered by using the
**modify** command. Note that if the volume group name is modified after
the cluster creation and DRBD support is enabled you might have to
manually modify the metavg as well.

If you don't want to use lvm storage at all use
the ``--enabled-disk-templates`` option to restrict the set of enabled
disk templates. Once the cluster is initialized
you can change this setup with the **modify** command.

The ``--master-netdev`` option is useful for specifying a different
interface on which the master will activate its IP address. It's
important that all nodes have this interface because you'll need it
for a master failover.

The ``--master-netmask`` option allows to specify a netmask for the
master IP. The netmask must be specified as an integer, and will be
interpreted as a CIDR netmask. The default value is 32 for an IPv4
address and 128 for an IPv6 address.

The ``--use-external-mip-script`` option allows to specify whether to
use an user-supplied master IP address setup script, whose location is
``@SYSCONFDIR@/ganeti/scripts/master-ip-setup``. If the option value is
set to False, the default script (located at
``@PKGLIBDIR@/tools/master-ip-setup``) will be executed.

The ``-m (--mac-prefix)`` option will let you specify a three byte
prefix under which the virtual MAC addresses of your instances will be
generated. The prefix must be specified in the format ``XX:XX:XX`` and
the default is ``aa:00:00``.

The ``--no-etc-hosts`` option allows you to initialize the cluster
without modifying the /etc/hosts file.

The ``--no-ssh-init`` option allows you to initialize the cluster
without creating or distributing SSH key pairs.

The ``--file-storage-dir``, ``--shared-file-storage-dir`` and
``--gluster-storage-dir`` options allow you set the directory to use for
storing the instance disk files when using respectively the file storage
backend, the shared file storage backend and the gluster storage
backend. Note that these directories must be an allowed directory for
file storage. Those directories are specified in the
``@SYSCONFDIR@/ganeti/file-storage-paths`` file.
The file storage directory can also be a subdirectory of an allowed one.
The file storage directory should be present on all nodes.

The ``--prealloc-wipe-disks`` sets a cluster wide configuration value
for wiping disks prior to allocation and size changes (``gnt-instance
grow-disk``). This increases security on instance level as the instance
can't access untouched data from its underlying storage.

The ``--enabled-hypervisors`` option allows you to set the list of
hypervisors that will be enabled for this cluster. Instance
hypervisors can only be chosen from the list of enabled
hypervisors, and the first entry of this list will be used by
default. Currently, the following hypervisors are available:

xen-pvm
    Xen PVM hypervisor

xen-hvm
    Xen HVM hypervisor

kvm
    Linux KVM hypervisor

chroot
    a simple chroot manager that starts chroot based on a script at the
    root of the filesystem holding the chroot

fake
    fake hypervisor for development/testing

Either a single hypervisor name or a comma-separated list of
hypervisor names can be specified. If this option is not specified,
only the xen-pvm hypervisor is enabled by default.

The ``-H (--hypervisor-parameters)`` option allows you to set default
hypervisor specific parameters for the cluster. The format of this
option is the name of the hypervisor, followed by a colon and a
comma-separated list of key=value pairs. The keys available for each
hypervisors are detailed in the **gnt-instance**\(8) man page, in the
**add** command plus the following parameters which are only
configurable globally (at cluster level):

migration\_port
    Valid for the Xen PVM and KVM hypervisors.

    This options specifies the TCP port to use for live-migration. For
    Xen, the same port should be configured on all nodes in the
    ``@XEN_CONFIG_DIR@/xend-config.sxp`` file, under the key
    "xend-relocation-port".

migration\_bandwidth
    Valid for the KVM hypervisor.

    This option specifies the maximum bandwidth that KVM will use for
    instance live migrations. The value is in MiB/s.

    This option is only effective with kvm versions >= 78 and qemu-kvm
    versions >= 0.10.0.

The ``-B (--backend-parameters)`` option allows you to set the default
backend parameters for the cluster. The parameter format is a
comma-separated list of key=value pairs with the following supported
keys:

vcpus
    Number of VCPUs to set for an instance by default, must be an
    integer, will be set to 1 if no specified.

maxmem
    Maximum amount of memory to allocate for an instance by default, can
    be either an integer or an integer followed by a unit (M for
    mebibytes and G for gibibytes are supported), will be set to 128M if
    not specified.

minmem
    Minimum amount of memory to allocate for an instance by default, can
    be either an integer or an integer followed by a unit (M for
    mebibytes and G for gibibytes are supported), will be set to 128M if
    not specified.

auto\_balance
    Value of the auto\_balance flag for instances to use by default,
    will be set to true if not specified.

always\_failover
    Default value for the ``always_failover`` flag for instances; if
    not set, ``False`` is used.


The ``-N (--nic-parameters)`` option allows you to set the default
network interface parameters for the cluster. The parameter format is a
comma-separated list of key=value pairs with the following supported
keys:

mode
    The default NIC mode, one of ``routed``, ``bridged`` or
    ``openvswitch``.

link
    In ``bridged`` or ``openvswitch`` mode the default interface where
    to attach NICs. In ``routed`` mode it represents an
    hypervisor-vif-script dependent value to allow different instance
    groups. For example under the KVM default network script it is
    interpreted as a routing table number or name. Openvswitch support
    is also hypervisor dependent and currently works for the default KVM
    network script. Under Xen a custom network script must be provided.

The ``-D (--disk-parameters)`` option allows you to set the default disk
template parameters at cluster level. The format used for this option is
similar to the one use by the  ``-H`` option: the disk template name
must be specified first, followed by a colon and by a comma-separated
list of key-value pairs. These parameters can only be specified at
cluster and node group level; the cluster-level parameter are inherited
by the node group at the moment of its creation, and can be further
modified at node group level using the **gnt-group**\(8) command.

The following is the list of disk parameters available for the **drbd**
template, with measurement units specified in square brackets at the end
of the description (when applicable):

resync-rate
    Static re-synchronization rate. [KiB/s]

data-stripes
    Number of stripes to use for data LVs.

meta-stripes
    Number of stripes to use for meta LVs.

disk-barriers
    What kind of barriers to **disable** for disks. It can either assume
    the value "n", meaning no barrier disabled, or a non-empty string
    containing a subset of the characters "bfd". "b" means disable disk
    barriers, "f" means disable disk flushes, "d" disables disk drains.

meta-barriers
    Boolean value indicating whether the meta barriers should be
    disabled (True) or not (False).

metavg
    String containing the name of the default LVM volume group for DRBD
    metadata. By default, it is set to ``xenvg``. It can be overridden
    during the instance creation process by using the ``metavg`` key of
    the ``--disk`` parameter.

disk-custom
    String containing additional parameters to be appended to the
    arguments list of ``drbdsetup disk``.

net-custom
    String containing additional parameters to be appended to the
    arguments list of ``drbdsetup net``.

protocol
    Replication protocol for the DRBD device. Has to be either "A", "B"
    or "C". Refer to the DRBD documentation for further information
    about the differences between the protocols.

dynamic-resync
    Boolean indicating whether to use the dynamic resync speed
    controller or not. If enabled, c-plan-ahead must be non-zero and all
    the c-* parameters will be used by DRBD. Otherwise, the value of
    resync-rate will be used as a static resync speed.

c-plan-ahead
    Agility factor of the dynamic resync speed controller. (the higher,
    the slower the algorithm will adapt the resync speed). A value of 0
    (that is the default) disables the controller. [ds]

c-fill-target
    Maximum amount of in-flight resync data for the dynamic resync speed
    controller. [sectors]

c-delay-target
    Maximum estimated peer response latency for the dynamic resync speed
    controller. [ds]

c-min-rate
    Minimum resync speed for the dynamic resync speed controller. [KiB/s]

c-max-rate
    Upper bound on resync speed for the dynamic resync speed controller.
    [KiB/s]

List of parameters available for the **plain** template:

stripes
    Number of stripes to use for new LVs.

List of parameters available for the **rbd** template:

pool
    The RADOS cluster pool, inside which all rbd volumes will reside.
    When a new RADOS cluster is deployed, the default pool to put rbd
    volumes (Images in RADOS terminology) is 'rbd'.

access
    If 'userspace', instances will access their disks directly without
    going through a block device, avoiding expensive context switches
    with kernel space and the potential for deadlocks_ in low memory
    scenarios.

    The default value is 'kernelspace' and it disables this behaviour.
    This setting may only be changed to 'userspace' if all instance
    disks in the affected group or cluster can be accessed in userspace.

    Attempts to use this feature without rbd support compiled in KVM
    result in a "no such file or directory" error messages.

.. _deadlocks: http://tracker.ceph.com/issues/3076

The option ``--maintain-node-health`` allows one to enable/disable
automatic maintenance actions on nodes. Currently these include
automatic shutdown of instances and deactivation of DRBD devices on
offline nodes; in the future it might be extended to automatic
removal of unknown LVM volumes, etc. Note that this option is only
useful if the use of ``ganeti-confd`` was enabled at compilation.

The ``--uid-pool`` option initializes the user-id pool. The
*user-id pool definition* can contain a list of user-ids and/or a
list of user-id ranges. The parameter format is a comma-separated
list of numeric user-ids or user-id ranges. The ranges are defined
by a lower and higher boundary, separated by a dash. The boundaries
are inclusive. If the ``--uid-pool`` option is not supplied, the
user-id pool is initialized to an empty list. An empty list means
that the user-id pool feature is disabled.

The ``-I (--default-iallocator)`` option specifies the default
instance allocator. The instance allocator will be used for operations
like instance creation, instance and node migration, etc. when no
manual override is specified. If this option is not specified and
htools was not enabled at build time, the default instance allocator
will be blank, which means that relevant operations will require the
administrator to manually specify either an instance allocator, or a
set of nodes. If the option is not specified but htools was enabled,
the default iallocator will be **hail**\(1) (assuming it can be found
on disk). The default iallocator can be changed later using the
**modify** command.

The option ``--default-iallocator-params`` sets the cluster-wide
iallocator parameters used by the default iallocator only on instance
allocations.

The ``--primary-ip-version`` option specifies the IP version used
for the primary address. Possible values are 4 and 6 for IPv4 and
IPv6, respectively. This option is used when resolving node names
and the cluster name.

The ``--node-parameters`` option allows you to set default node
parameters for the cluster. Please see **ganeti**\(7) for more
information about supported key=value pairs.

The ``-C (--candidate-pool-size)`` option specifies the
``candidate_pool_size`` cluster parameter. This is the number of nodes
that the master will try to keep as master\_candidates. For more
details about this role and other node roles, see the **ganeti**\(7).

The ``--specs-...`` and ``--ipolicy-...`` options specify the instance
policy on the cluster. The ``--ipolicy-bounds-specs`` option sets the
minimum and maximum specifications for instances. The format is:
min:*param*=*value*,.../max:*param*=*value*,... and further
specifications pairs can be added by using ``//`` as a separator. The
``--ipolicy-std-specs`` option takes a list of parameter/value pairs.
For both options, *param* can be:

- ``cpu-count``: number of VCPUs for an instance
- ``disk-count``: number of disk for an instance
- ``disk-size``: size of each disk
- ``memory-size``: instance memory
- ``nic-count``: number of network interface
- ``spindle-use``: spindle usage for an instance

For the ``--specs-...`` options, each option can have three values:
``min``, ``max`` and ``std``, which can also be modified on group level
(except for ``std``, which is defined once for the entire cluster).
Please note, that ``std`` values are not the same as defaults set by
``--beparams``, but they are used for the capacity calculations.

- ``--specs-cpu-count`` limits the number of VCPUs that can be used by an
  instance.
- ``--specs-disk-count`` limits the number of disks
- ``--specs-disk-size`` limits the disk size for every disk used
- ``--specs-mem-size`` limits the amount of memory available
- ``--specs-nic-count`` sets limits on the number of NICs used

The ``--ipolicy-spindle-ratio`` option takes a decimal number. The
``--ipolicy-disk-templates`` option takes a comma-separated list of disk
templates. This list of disk templates must be a subset of the list
of cluster-wide enabled disk templates (which can be set with
``--enabled-disk-templates``).

- ``--ipolicy-spindle-ratio`` limits the instances-spindles ratio
- ``--ipolicy-vcpu-ratio`` limits the vcpu-cpu ratio

All the instance policy elements can be overridden at group level. Group
level overrides can be removed by specifying ``default`` as the value of
an item.

The ``--drbd-usermode-helper`` option can be used to specify a usermode
helper. Check that this string is the one used by the DRBD kernel.

For details about how to use ``--hypervisor-state`` and ``--disk-state``
have a look at **ganeti**\(7).

The ``--enabled-disk-templates`` option specifies a list of disk templates
that can be used by instances of the cluster. For the possible values in
this list, see **gnt-instance**\(8). Note that in contrast to the list of
disk templates in the ipolicy, this list is a hard restriction. It is not
possible to create instances with disk templates that are not enabled in
the cluster. It is also not possible to disable a disk template when there
are still instances using it. The first disk template in the list of
enabled disk template is the default disk template. It will be used for
instance creation, if no disk template is requested explicitely.

MASTER-FAILOVER
~~~~~~~~~~~~~~~

**master-failover** [\--no-voting] [\--yes-do-it]

Failover the master role to the current node.

The ``--no-voting`` option skips the remote node agreement checks.
This is dangerous, but necessary in some cases (for example failing
over the master role in a 2 node cluster with the original master
down). If the original master then comes up, it won't be able to
start its master daemon because it won't have enough votes, but so
won't the new master, if the master daemon ever needs a restart.
You can pass ``--no-voting`` to **ganeti-masterd** on the new
master to solve this problem, and run **gnt-cluster redist-conf**
to make sure the cluster is consistent again.

The option ``--yes-do-it`` is used together with ``--no-voting``, for
skipping the interactive checks. This is even more dangerous, and should
only be used in conjunction with other means (e.g. a HA suite) to
confirm that the operation is indeed safe.

MASTER-PING
~~~~~~~~~~~

**master-ping**

Checks if the master daemon is alive.

If the master daemon is alive and can respond to a basic query (the
equivalent of **gnt-cluster info**), then the exit code of the
command will be 0. If the master daemon is not alive (either due to
a crash or because this is not the master node), the exit code will
be 1.

MODIFY
~~~~~~

| **modify** [\--submit] [\--print-job-id]
| [\--force]
| [\--vg-name *vg-name*]
| [\--enabled-hypervisors *hypervisors*]
| [{-H|\--hypervisor-parameters} *hypervisor*:*hv-param*=*value*[,*hv-param*=*value*...]]
| [{-B|\--backend-parameters} *be-param*=*value*[,*be-param*=*value*...]]
| [{-N|\--nic-parameters} *nic-param*=*value*[,*nic-param*=*value*...]]
| [{-D|\--disk-parameters} *disk-template*:*disk-param*=*value*[,*disk-param*=*value*...]]
| [\--uid-pool *user-id pool definition*]
| [\--add-uids *user-id pool definition*]
| [\--remove-uids *user-id pool definition*]
| [{-C|\--candidate-pool-size} *candidate\_pool\_size*]
| [\--maintain-node-health {yes \| no}]
| [\--prealloc-wipe-disks {yes \| no}]
| [{-I|\--default-iallocator} *default instance allocator*]
| [\--default-iallocator-params *ial-param*=*value*,*ial-param*=*value*]
| [\--reserved-lvs=*NAMES*]
| [\--node-parameters *ndparams*]
| [\--master-netdev *interface-name*]
| [\--master-netmask *netmask*]
| [\--use-external-mip-script {yes \| no}]
| [\--hypervisor-state *hvstate*]
| [\--disk-state *diskstate*]
| [\--ipolicy-std-specs *spec*=*value* [,*spec*=*value*...]]
| [\--ipolicy-bounds-specs *bounds_ispecs*]
| [\--ipolicy-disk-templates *template* [,*template*...]]
| [\--ipolicy-spindle-ratio *ratio*]
| [\--ipolicy-vcpu-ratio *ratio*]
| [\--enabled-disk-templates *template* [,*template*...]]
| [\--drbd-usermode-helper *helper*]
| [\--file-storage-dir *dir*]
| [\--shared-file-storage-dir *dir*]


Modify the options for the cluster.

The ``--vg-name``, ``--enabled-hypervisors``, ``-H (--hypervisor-parameters)``,
``-B (--backend-parameters)``, ``-D (--disk-parameters)``, ``--nic-parameters``,
``-C (--candidate-pool-size)``, ``--maintain-node-health``,
``--prealloc-wipe-disks``, ``--uid-pool``, ``--node-parameters``,
``--master-netdev``, ``--master-netmask``, ``--use-external-mip-script``,
``--drbd-usermode-helper``, ``--file-storage-dir``,
``--shared-file-storage-dir``, and ``--enabled-disk-templates`` options are
described in the **init** command.

The ``--hypervisor-state`` and ``--disk-state`` options are described in
detail in **ganeti**\(7).

The ``--add-uids`` and ``--remove-uids`` options can be used to
modify the user-id pool by adding/removing a list of user-ids or
user-id ranges.

The option ``--reserved-lvs`` specifies a list (comma-separated) of
logical volume group names (regular expressions) that will be
ignored by the cluster verify operation. This is useful if the
volume group used for Ganeti is shared with the system for other
uses. Note that it's not recommended to create and mark as ignored
logical volume names which match Ganeti's own name format (starting
with UUID and then .diskN), as this option only skips the
verification, but not the actual use of the names given.

To remove all reserved logical volumes, pass in an empty argument
to the option, as in ``--reserved-lvs=`` or ``--reserved-lvs ''``.

The ``-I (--default-iallocator)`` is described in the **init**
command. To clear the default iallocator, just pass an empty string
('').

The option ``--default-iallocator-params`` is described in the **init**
command. To clear the default iallocator parameters, just pass an empty
string ('').

The ``--ipolicy-...`` options are described in the **init** command.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

QUEUE
~~~~~

**queue** {drain | undrain | info}

Change job queue properties.

The ``drain`` option sets the drain flag on the job queue. No new
jobs will be accepted, but jobs already in the queue will be
processed.

The ``undrain`` will unset the drain flag on the job queue. New
jobs will be accepted.

The ``info`` option shows the properties of the job queue.

WATCHER
~~~~~~~

**watcher** {pause *duration* | continue | info}

Make the watcher pause or let it continue.

The ``pause`` option causes the watcher to pause for *duration*
seconds.

The ``continue`` option will let the watcher continue.

The ``info`` option shows whether the watcher is currently paused.

REDIST-CONF
~~~~~~~~~~~

**redist-conf** [\--submit] [\--print-job-id]

This command forces a full push of configuration files from the
master node to the other nodes in the cluster. This is normally not
needed, but can be run if the **verify** complains about
configuration mismatches.

See **ganeti**\(7) for a description of ``--submit`` and other common
options.

RENAME
~~~~~~

**rename** [-f] {*name*}

Renames the cluster and in the process updates the master IP
address to the one the new name resolves to. At least one of either
the name or the IP address must be different, otherwise the
operation will be aborted.

Note that since this command can be dangerous (especially when run
over SSH), the command will require confirmation unless run with
the ``-f`` option.

RENEW-CRYPTO
~~~~~~~~~~~~

| **renew-crypto** [-f]
| [\--new-cluster-certificate] [\--new-confd-hmac-key]
| [\--new-rapi-certificate] [\--rapi-certificate *rapi-cert*]
| [\--new-spice-certificate | \--spice-certificate *spice-cert*
| \--spice-ca-certificate *spice-ca-cert*]
| [\--new-cluster-domain-secret] [\--cluster-domain-secret *filename*]

This command will stop all Ganeti daemons in the cluster and start
them again once the new certificates and keys are replicated. The
options ``--new-cluster-certificate`` and ``--new-confd-hmac-key``
can be used to regenerate respectively the cluster-internal SSL
certificate and the HMAC key used by **ganeti-confd**\(8).

To generate a new self-signed RAPI certificate (used by
**ganeti-rapi**\(8)) specify ``--new-rapi-certificate``. If you want to
use your own certificate, e.g. one signed by a certificate
authority (CA), pass its filename to ``--rapi-certificate``.

To generate a new self-signed SPICE certificate, used for SPICE
connections to the KVM hypervisor, specify the
``--new-spice-certificate`` option. If you want to provide a
certificate, pass its filename to ``--spice-certificate`` and pass the
signing CA certificate to ``--spice-ca-certificate``.

Finally ``--new-cluster-domain-secret`` generates a new, random
cluster domain secret, and ``--cluster-domain-secret`` reads the
secret from a file. The cluster domain secret is used to sign
information exchanged between separate clusters via a third party.

REPAIR-DISK-SIZES
~~~~~~~~~~~~~~~~~

**repair-disk-sizes** [instance...]

This command checks that the recorded size of the given instance's
disks matches the actual size and updates any mismatches found.
This is needed if the Ganeti configuration is no longer consistent
with reality, as it will impact some disk operations. If no
arguments are given, all instances will be checked. When exclusive
storage is active, also spindles are updated.

Note that only active disks can be checked by this command; in case
a disk cannot be activated it's advised to use
**gnt-instance activate-disks \--ignore-size ...** to force
activation without regard to the current size.

When all the disk sizes are consistent, the command will return no
output. Otherwise it will log details about the inconsistencies in
the configuration.

UPGRADE
~~~~~~~

**upgrade** {--to *version* | --resume}

This command safely switches all nodes of the cluster to a new Ganeti
version. It is a prerequisite that the new version is already installed,
albeit not activated, on all nodes; this requisite is checked before any
actions are done.

If called with the ``--resume`` option, any pending upgrade is
continued, that was interrupted by a power failure or similar on
master. It will do nothing, if not run on the master node, or if no
upgrade was in progress.


VERIFY
~~~~~~

| **verify** [\--no-nplus1-mem] [\--node-group *nodegroup*]
| [\--error-codes] [{-I|\--ignore-errors} *errorcode*]
| [{-I|\--ignore-errors} *errorcode*...]

Verify correctness of cluster configuration. This is safe with
respect to running instances, and incurs no downtime of the
instances.

If the ``--no-nplus1-mem`` option is given, Ganeti won't check
whether if it loses a node it can restart all the instances on
their secondaries (and report an error otherwise).

With ``--node-group``, restrict the verification to those nodes and
instances that live in the named group. This will not verify global
settings, but will allow to perform verification of a group while other
operations are ongoing in other groups.

The ``--error-codes`` option outputs each error in the following
parseable format: *ftype*:*ecode*:*edomain*:*name*:*msg*.
These fields have the following meaning:

ftype
    Failure type. Can be *WARNING* or *ERROR*.

ecode
    Error code of the failure. See below for a list of error codes.

edomain
    Can be *cluster*, *node* or *instance*.

name
    Contains the name of the item that is affected from the failure.

msg
    Contains a descriptive error message about the error

``gnt-cluster verify`` will have a non-zero exit code if at least one of
the failures that are found are of type *ERROR*.

The ``--ignore-errors`` option can be used to change this behaviour,
because it demotes the error represented by the error code received as a
parameter to a warning. The option must be repeated for each error that
should be ignored (e.g.: ``-I ENODEVERSION -I ENODEORPHANLV``). The
``--error-codes`` option can be used to determine the error code of a
given error.

List of error codes:

@CONSTANTS_ECODES@

VERIFY-DISKS
~~~~~~~~~~~~

**verify-disks**

The command checks which instances have degraded DRBD disks and
activates the disks of those instances.

This command is run from the **ganeti-watcher** tool, which also
has a different, complementary algorithm for doing this check.
Together, these two should ensure that DRBD disks are kept
consistent.

VERSION
~~~~~~~

**version**

Show the cluster version.

Tags
~~~~

ADD-TAGS
^^^^^^^^

**add-tags** [\--from *file*] {*tag*...}

Add tags to the cluster. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be
extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line
(if you do, both sources will be used). A file name of - will be
interpreted as stdin.

LIST-TAGS
^^^^^^^^^

**list-tags**

List the tags of the cluster.

REMOVE-TAGS
^^^^^^^^^^^

**remove-tags** [\--from *file*] {*tag*...}

Remove tags from the cluster. If any of the tags are not existing
on the cluster, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line (if
you do, tags from both sources will be removed). A file name of - will
be interpreted as stdin.

SEARCH-TAGS
^^^^^^^^^^^

**search-tags** {*pattern*}

Searches the tags on all objects in the cluster (the cluster
itself, the nodes and the instances) for a given pattern. The
pattern is interpreted as a regular expression and a search will be
done on it (i.e. the given pattern is not anchored to the beggining
of the string; if you want that, prefix the pattern with ^).

If no tags are matching the pattern, the exit code of the command
will be one. If there is at least one match, the exit code will be
zero. Each match is listed on one line, the object and the tag
separated by a space. The cluster will be listed as /cluster, a
node will be listed as /nodes/*name*, and an instance as
/instances/*name*. Example:

::

    # gnt-cluster search-tags time
    /cluster ctime:2007-09-01
    /nodes/node1.example.com mtime:2007-10-04

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
