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

ADD-TAGS
~~~~~~~~

**add-tags** [--from *file*] {*tag*...}

Add tags to the cluster. If any of the tags contains invalid
characters, the entire operation will abort.

If the ``--from`` option is given, the list of tags will be
extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line
(if you do, both sources will be used). A file name of - will be
interpreted as stdin.

COMMAND
~~~~~~~

**command** [-n *node*] {*command*}

Executes a command on all nodes. If the option ``-n`` is not given,
the command will be executed on all nodes, otherwise it will be
executed only on the node(s) specified. Use the option multiple
times for running it on multiple nodes, like::

    # gnt-cluster command -n node1.example.com -n node2.example.com date

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

**copyfile** [--use-replication-network] [-n *node*] {*file*}

Copies a file to all or to some nodes. The argument specifies the
source file (on the current system), the ``-n`` argument specifies
the target node, or nodes if the option is given multiple times. If
``-n`` is not given at all, the file will be copied to all nodes.
Passing the ``--use-replication-network`` option will cause the
copy to be done over the replication network (only matters if the
primary/secondary IPs are different). Example::

    # gnt-cluster -n node1.example.com -n node2.example.com copyfile /tmp/test

This will copy the file /tmp/test from the current node to the two
named nodes.

DESTROY
~~~~~~~

**destroy** {--yes-do-it}

Remove all configuration files related to the cluster, so that a
**gnt-cluster init** can be done again afterwards.

Since this is a dangerous command, you are required to pass the
argument *--yes-do-it.*

EPO
~~~

**epo** [--on] [--groups|--all] [--power-delay] *arguments*

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

**info** [--roman]

Shows runtime cluster information: cluster name, architecture (32
or 64 bit), master node, node list and instance list.

Passing the ``--roman`` option gnt-cluster info will try to print
its integer fields in a latin friendly way. This allows further
diffusion of Ganeti among ancient cultures.

INIT
~~~~

| **init**
| [{-s|--secondary-ip} *secondary\_ip*]
| [--vg-name *vg-name*]
| [--master-netdev *interface-name*]
| [{-m|--mac-prefix} *mac-prefix*]
| [--no-lvm-storage]
| [--no-etc-hosts]
| [--no-ssh-init]
| [--file-storage-dir *dir*]
| [--enabled-hypervisors *hypervisors*]
| [-t *hypervisor name*]
| [{-H|--hypervisor-parameters} *hypervisor*:*hv-param*=*value*[,*hv-param*=*value*...]]
| [{-B|--backend-parameters} *be-param*=*value* [,*be-param*=*value*...]]
| [{-N|--nic-parameters} *nic-param*=*value* [,*nic-param*=*value*...]]
| [--maintain-node-health {yes \| no}]
| [--uid-pool *user-id pool definition*]
| [{-I|--default-iallocator} *default instance allocator*]
| [--primary-ip-version *version*]
| [--prealloc-wipe-disks {yes \| no}]
| [--node-parameters *ndparams*]
| [{-C|--candidate-pool-size} *candidate\_pool\_size*]
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
**modify** command. If you don't want to use lvm storage at all use
the ``--no-lvm-storage`` option. Once the cluster is initialized
you can change this setup with the **modify** command.

The ``--master-netdev`` option is useful for specifying a different
interface on which the master will activate its IP address. It's
important that all nodes have this interface because you'll need it
for a master failover.

The ``-m (--mac-prefix)`` option will let you specify a three byte
prefix under which the virtual MAC addresses of your instances will be
generated. The prefix must be specified in the format ``XX:XX:XX`` and
the default is ``aa:00:00``.

The ``--no-lvm-storage`` option allows you to initialize the
cluster without lvm support. This means that only instances using
files as storage backend will be possible to create. Once the
cluster is initialized you can change this setup with the
**modify** command.

The ``--no-etc-hosts`` option allows you to initialize the cluster
without modifying the /etc/hosts file.

The ``--no-ssh-init`` option allows you to initialize the cluster
without creating or distributing SSH key pairs.

The ``--file-storage-dir`` option allows you set the directory to
use for storing the instance disk files when using file storage as
backend for instance disks.

The ``--prealloc-wipe-disks`` sets a cluster wide configuration
value for wiping disks prior to allocation. This increases security
on instance level as the instance can't access untouched data from
it's underlying storage.

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
hypervisors are detailed in the gnt-instance(8) man page, in the
**add** command plus the following parameters which are only
configurable globally (at cluster level):

migration\_port
    Valid for the Xen PVM and KVM hypervisors.

    This options specifies the TCP port to use for live-migration. For
    Xen, the same port should be configured on all nodes in the
    ``/etc/xen/xend-config.sxp`` file, under the key
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

memory
    Amount of memory to allocate for an instance by default, can be
    either an integer or an integer followed by a unit (M for mebibytes
    and G for gibibytes are supported), will be set to 128M if not
    specified.

auto\_balance
    Value of the auto\_balance flag for instances to use by default,
    will be set to true if not specified.


The ``-N (--nic-parameters)`` option allows you to set the default nic
parameters for the cluster. The parameter format is a comma-separated
list of key=value pairs with the following supported keys:

mode
    The default nic mode, 'routed' or 'bridged'.

link
    In bridged mode the default NIC bridge. In routed mode it
    represents an hypervisor-vif-script dependent value to allow
    different instance groups. For example under the KVM default
    network script it is interpreted as a routing table number or
    name.

The option ``--maintain-node-health`` allows to enable/disable
automatic maintenance actions on nodes. Currently these include
automatic shutdown of instances and deactivation of DRBD devices on
offline nodes; in the future it might be extended to automatic
removal of unknown LVM volumes, etc.

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
the default iallocator will be **hail**(1) (assuming it can be found
on disk). The default iallocator can be changed later using the
**modify** command.

The ``--primary-ip-version`` option specifies the IP version used
for the primary address. Possible values are 4 and 6 for IPv4 and
IPv6, respectively. This option is used when resolving node names
and the cluster name.

The ``--node-parameters`` option allows you to set default node
parameters for the cluster. Please see **ganeti**(7) for more
information about supported key=value pairs.

The ``-C (--candidate-pool-size)`` option specifies the
``candidate_pool_size`` cluster parameter. This is the number of nodes
that the master will try to keep as master\_candidates. For more
details about this role and other node roles, see the ganeti(7).

LIST-TAGS
~~~~~~~~~

**list-tags**

List the tags of the cluster.

MASTER-FAILOVER
~~~~~~~~~~~~~~~

**master-failover** [--no-voting]

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

| **modify**
| [--vg-name *vg-name*]
| [--no-lvm-storage]
| [--enabled-hypervisors *hypervisors*]
| [{-H|--hypervisor-parameters} *hypervisor*:*hv-param*=*value*[,*hv-param*=*value*...]]
| [{-B|--backend-parameters} *be-param*=*value* [,*be-param*=*value*...]]
| [{-N|--nic-parameters} *nic-param*=*value* [,*nic-param*=*value*...]]
| [--uid-pool *user-id pool definition*]
| [--add-uids *user-id pool definition*]
| [--remove-uids *user-id pool definition*]
| [{-C|--candidate-pool-size} *candidate\_pool\_size*]
| [--maintain-node-health {yes \| no}]
| [--prealloc-wipe-disks {yes \| no}]
| [{-I|--default-iallocator} *default instance allocator*]
| [--reserved-lvs=*NAMES*]
| [--node-parameters *ndparams*]
| [--master-netdev *interface-name*]

Modify the options for the cluster.

The ``--vg-name``, ``--no-lvm-storarge``, ``--enabled-hypervisors``,
``-H (--hypervisor-parameters)``, ``-B (--backend-parameters)``,
``--nic-parameters``, ``-C (--candidate-pool-size)``,
``--maintain-node-health``, ``--prealloc-wipe-disks``, ``--uid-pool``,
``--node-parameters``, ``--master-netdev`` options are described in
the **init** command.

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

redist-conf
~~~~~~~~~~~

**redist-conf** [--submit]

This command forces a full push of configuration files from the
master node to the other nodes in the cluster. This is normally not
needed, but can be run if the **verify** complains about
configuration mismatches.

The ``--submit`` option is used to send the job to the master
daemon but not wait for its completion. The job ID will be shown so
that it can be examined via **gnt-job info**.

REMOVE-TAGS
~~~~~~~~~~~

**remove-tags** [--from *file*] {*tag*...}

Remove tags from the cluster. If any of the tags are not existing
on the cluster, the entire operation will abort.

If the ``--from`` option is given, the list of tags to be removed will
be extended with the contents of that file (each line becomes a tag).
In this case, there is not need to pass tags on the command line (if
you do, tags from both sources will be removed). A file name of - will
be interpreted as stdin.

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
| [--new-cluster-certificate] [--new-confd-hmac-key]
| [--new-rapi-certificate] [--rapi-certificate *rapi-cert*]
| [--new-cluster-domain-secret] [--cluster-domain-secret *filename*]

This command will stop all Ganeti daemons in the cluster and start
them again once the new certificates and keys are replicated. The
options ``--new-cluster-certificate`` and ``--new-confd-hmac-key``
can be used to regenerate the cluster-internal SSL certificate
respective the HMAC key used by ganeti-confd(8).

To generate a new self-signed RAPI certificate (used by
ganeti-rapi(8)) specify ``--new-rapi-certificate``. If you want to
use your own certificate, e.g. one signed by a certificate
authority (CA), pass its filename to ``--rapi-certificate``.

``--new-cluster-domain-secret`` generates a new, random cluster
domain secret. ``--cluster-domain-secret`` reads the secret from a
file. The cluster domain secret is used to sign information
exchanged between separate clusters via a third party.

REPAIR-DISK-SIZES
~~~~~~~~~~~~~~~~~

**repair-disk-sizes** [instance...]

This command checks that the recorded size of the given instance's
disks matches the actual size and updates any mismatches found.
This is needed if the Ganeti configuration is no longer consistent
with reality, as it will impact some disk operations. If no
arguments are given, all instances will be checked.

Note that only active disks can be checked by this command; in case
a disk cannot be activated it's advised to use
**gnt-instance activate-disks --ignore-size ...** to force
activation without regard to the current size.

When the all disk sizes are consistent, the command will return no
output. Otherwise it will log details about the inconsistencies in
the configuration.

SEARCH-TAGS
~~~~~~~~~~~

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

VERIFY
~~~~~~

**verify** [--no-nplus1-mem] [--node-group *nodegroup*]

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

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
