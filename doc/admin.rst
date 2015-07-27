Ganeti administrator's guide
============================

Documents Ganeti version |version|

.. contents::

.. highlight:: shell-example

Introduction
------------

Ganeti is a virtualization cluster management software. You are expected
to be a system administrator familiar with your Linux distribution and
the Xen or KVM virtualization environments before using it.

The various components of Ganeti all have man pages and interactive
help. This manual though will help you getting familiar with the system
by explaining the most common operations, grouped by related use.

After a terminology glossary and a section on the prerequisites needed
to use this manual, the rest of this document is divided in sections
for the different targets that a command affects: instance, nodes, etc.

.. _terminology-label:

Ganeti terminology
++++++++++++++++++

This section provides a small introduction to Ganeti terminology, which
might be useful when reading the rest of the document.

Cluster
~~~~~~~

A set of machines (nodes) that cooperate to offer a coherent, highly
available virtualization service under a single administration domain.

Node
~~~~

A physical machine which is member of a cluster.  Nodes are the basic
cluster infrastructure, and they don't need to be fault tolerant in
order to achieve high availability for instances.

Node can be added and removed (if they host no instances) at will from
the cluster. In a HA cluster and only with HA instances, the loss of any
single node will not cause disk data loss for any instance; of course,
a node crash will cause the crash of its primary instances.

A node belonging to a cluster can be in one of the following roles at a
given time:

- *master* node, which is the node from which the cluster is controlled
- *master candidate* node, only nodes in this role have the full cluster
  configuration and knowledge, and only master candidates can become the
  master node
- *regular* node, which is the state in which most nodes will be on
  bigger clusters (>20 nodes)
- *drained* node, nodes in this state are functioning normally but the
  cannot receive new instances; the intention is that nodes in this role
  have some issue and they are being evacuated for hardware repairs
- *offline* node, in which there is a record in the cluster
  configuration about the node, but the daemons on the master node will
  not talk to this node; any instances declared as having an offline
  node as either primary or secondary will be flagged as an error in the
  cluster verify operation

Depending on the role, each node will run a set of daemons:

- the :command:`ganeti-noded` daemon, which controls the manipulation of
  this node's hardware resources; it runs on all nodes which are in a
  cluster
- the :command:`ganeti-confd` daemon (Ganeti 2.1+) which runs on all
  nodes, but is only functional on master candidate nodes; this daemon
  can be disabled at configuration time if you don't need its
  functionality
- the :command:`ganeti-rapi` daemon which runs on the master node and
  offers an HTTP-based API for the cluster
- the :command:`ganeti-masterd` daemon which runs on the master node and
  allows control of the cluster

Beside the node role, there are other node flags that influence its
behaviour:

- the *master_capable* flag denotes whether the node can ever become a
  master candidate; setting this to 'no' means that auto-promotion will
  never make this node a master candidate; this flag can be useful for a
  remote node that only runs local instances, and having it become a
  master is impractical due to networking or other constraints
- the *vm_capable* flag denotes whether the node can host instances or
  not; for example, one might use a non-vm_capable node just as a master
  candidate, for configuration backups; setting this flag to no
  disallows placement of instances of this node, deactivates hypervisor
  and related checks on it (e.g. bridge checks, LVM check, etc.), and
  removes it from cluster capacity computations


Instance
~~~~~~~~

A virtual machine which runs on a cluster. It can be a fault tolerant,
highly available entity.

An instance has various parameters, which are classified in three
categories: hypervisor related-parameters (called ``hvparams``), general
parameters (called ``beparams``) and per network-card parameters (called
``nicparams``). All these parameters can be modified either at instance
level or via defaults at cluster level.

Disk template
~~~~~~~~~~~~~

The are multiple options for the storage provided to an instance; while
the instance sees the same virtual drive in all cases, the node-level
configuration varies between them.

There are several disk templates you can choose from:

``diskless``
  The instance has no disks. Only used for special purpose operating
  systems or for testing.

``file`` *****
  The instance will use plain files as backend for its disks. No
  redundancy is provided, and this is somewhat more difficult to
  configure for high performance.

``sharedfile`` *****
  The instance will use plain files as backend, but Ganeti assumes that
  those files will be available and in sync automatically on all nodes.
  This allows live migration and failover of instances using this
  method.

``plain``
  The instance will use LVM devices as backend for its disks. No
  redundancy is provided.

``drbd``
  .. note:: This is only valid for multi-node clusters using DRBD 8.0+

  A mirror is set between the local node and a remote one, which must be
  specified with the second value of the --node option. Use this option
  to obtain a highly available instance that can be failed over to a
  remote node should the primary one fail.

  .. note:: Ganeti does not support DRBD stacked devices:
     DRBD stacked setup is not fully symmetric and as such it is
     not working with live migration.

``rbd``
  The instance will use Volumes inside a RADOS cluster as backend for its
  disks. It will access them using the RADOS block device (RBD).

``gluster`` *****
  The instance will use a Gluster volume for instance storage. Disk
  images will be stored in the top-level ``ganeti/`` directory of the
  volume. This directory will be created automatically for you.

``ext``
  The instance will use an external storage provider. See
  :manpage:`ganeti-extstorage-interface(7)` for how to implement one.

.. note::
  Disk templates marked with an asterisk require Ganeti to access the
  file system. Ganeti will refuse to do so unless you whitelist the
  relevant paths in the file storage paths configuration which,
  with default configure-time paths is located
  in :pyeval:`pathutils.FILE_STORAGE_PATHS_FILE`.

  The default paths used by Ganeti are:

  =============== ===================================================
  Disk template   Default path
  =============== ===================================================
  ``file``        :pyeval:`pathutils.DEFAULT_FILE_STORAGE_DIR`
  ``sharedfile``  :pyeval:`pathutils.DEFAULT_SHARED_FILE_STORAGE_DIR`
  ``gluster``     :pyeval:`pathutils.DEFAULT_GLUSTER_STORAGE_DIR`
  =============== ===================================================

  Those paths can be changed at ``gnt-cluster init`` time. See
  :manpage:`gnt-cluster(8)` for details.


IAllocator
~~~~~~~~~~

A framework for using external (user-provided) scripts to compute the
placement of instances on the cluster nodes. This eliminates the need to
manually specify nodes in instance add, instance moves, node evacuate,
etc.

In order for Ganeti to be able to use these scripts, they must be place
in the iallocator directory (usually ``lib/ganeti/iallocators`` under
the installation prefix, e.g. ``/usr/local``).

“Primary” and “secondary” concepts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An instance has a primary and depending on the disk configuration, might
also have a secondary node. The instance always runs on the primary node
and only uses its secondary node for disk replication.

Similarly, the term of primary and secondary instances when talking
about a node refers to the set of instances having the given node as
primary, respectively secondary.

Tags
~~~~

Tags are short strings that can be attached to either to cluster itself,
or to nodes or instances. They are useful as a very simplistic
information store for helping with cluster administration, for example
by attaching owner information to each instance after it's created::

  $ gnt-instance add … %instance1%
  $ gnt-instance add-tags %instance1% %owner:user2%

And then by listing each instance and its tags, this information could
be used for contacting the users of each instance.

Jobs and OpCodes
~~~~~~~~~~~~~~~~

While not directly visible by an end-user, it's useful to know that a
basic cluster operation (e.g. starting an instance) is represented
internally by Ganeti as an *OpCode* (abbreviation from operation
code). These OpCodes are executed as part of a *Job*. The OpCodes in a
single Job are processed serially by Ganeti, but different Jobs will be
processed (depending on resource availability) in parallel. They will
not be executed in the submission order, but depending on resource
availability, locks and (starting with Ganeti 2.3) priority. An earlier
job may have to wait for a lock while a newer job doesn't need any locks
and can be executed right away. Operations requiring a certain order
need to be submitted as a single job, or the client must submit one job
at a time and wait for it to finish before continuing.

For example, shutting down the entire cluster can be done by running the
command ``gnt-instance shutdown --all``, which will submit for each
instance a separate job containing the “shutdown instance” OpCode.


Prerequisites
+++++++++++++

You need to have your Ganeti cluster installed and configured before you
try any of the commands in this document. Please follow the
:doc:`install` for instructions on how to do that.

Instance management
-------------------

Adding an instance
++++++++++++++++++

The add operation might seem complex due to the many parameters it
accepts, but once you have understood the (few) required parameters and
the customisation capabilities you will see it is an easy operation.

The add operation requires at minimum five parameters:

- the OS for the instance
- the disk template
- the disk count and size
- the node specification or alternatively the iallocator to use
- and finally the instance name

The OS for the instance must be visible in the output of the command
``gnt-os list`` and specifies which guest OS to install on the instance.

The disk template specifies what kind of storage to use as backend for
the (virtual) disks presented to the instance; note that for instances
with multiple virtual disks, they all must be of the same type.

The node(s) on which the instance will run can be given either manually,
via the ``-n`` option, or computed automatically by Ganeti, if you have
installed any iallocator script.

With the above parameters in mind, the command is::

  $ gnt-instance add \
    -n %TARGET_NODE%:%SECONDARY_NODE% \
    -o %OS_TYPE% \
    -t %DISK_TEMPLATE% -s %DISK_SIZE% \
    %INSTANCE_NAME%

The instance name must be resolvable (e.g. exist in DNS) and usually
points to an address in the same subnet as the cluster itself.

The above command has the minimum required options; other options you
can give include, among others:

- The maximum/minimum memory size (``-B maxmem``, ``-B minmem``)
  (``-B memory`` can be used to specify only one size)

- The number of virtual CPUs (``-B vcpus``)

- Arguments for the NICs of the instance; by default, a single-NIC
  instance is created. The IP and/or bridge of the NIC can be changed
  via ``--net 0:ip=IP,link=BRIDGE``

See :manpage:`ganeti-instance(8)` for the detailed option list.

For example if you want to create an highly available instance, with a
single disk of 50GB and the default memory size, having primary node
``node1`` and secondary node ``node3``, use the following command::

  $ gnt-instance add -n node1:node3 -o debootstrap -t drbd -s 50G \
    instance1

There is a also a command for batch instance creation from a
specification file, see the ``batch-create`` operation in the
gnt-instance manual page.

Regular instance operations
+++++++++++++++++++++++++++

Removal
~~~~~~~

Removing an instance is even easier than creating one. This operation is
irreversible and destroys all the contents of your instance. Use with
care::

  $ gnt-instance remove %INSTANCE_NAME%

.. _instance-startup-label:

Startup/shutdown
~~~~~~~~~~~~~~~~

Instances are automatically started at instance creation time. To
manually start one which is currently stopped you can run::

  $ gnt-instance startup %INSTANCE_NAME%

Ganeti will start an instance with up to its maximum instance memory. If
not enough memory is available Ganeti will use all the available memory
down to the instance minimum memory. If not even that amount of memory
is free Ganeti will refuse to start the instance.

Note, that this will not work when an instance is in a permanently
stopped state ``offline``. In this case, you will first have to
put it back to online mode by running::

  $ gnt-instance modify --online %INSTANCE_NAME%

The command to stop the running instance is::

  $ gnt-instance shutdown %INSTANCE_NAME%

If you want to shut the instance down more permanently, so that it
does not require dynamically allocated resources (memory and vcpus),
after shutting down an instance, execute the following::

  $ gnt-instance modify --offline %INSTANCE_NAME%

.. warning:: Do not use the Xen or KVM commands directly to stop
   instances. If you run for example ``xm shutdown`` or ``xm destroy``
   on an instance Ganeti will automatically restart it (via
   the :command:`ganeti-watcher(8)` command which is launched via cron).

Instances can also be shutdown by the user from within the instance, in
which case they will marked accordingly and the
:command:`ganeti-watcher(8)` will not restart them.  See
:manpage:`gnt-cluster(8)` for details.

Querying instances
~~~~~~~~~~~~~~~~~~

There are two ways to get information about instances: listing
instances, which does a tabular output containing a given set of fields
about each instance, and querying detailed information about a set of
instances.

The command to see all the instances configured and their status is::

  $ gnt-instance list

The command can return a custom set of information when using the ``-o``
option (as always, check the manpage for a detailed specification). Each
instance will be represented on a line, thus making it easy to parse
this output via the usual shell utilities (grep, sed, etc.).

To get more detailed information about an instance, you can run::

  $ gnt-instance info %INSTANCE%

which will give a multi-line block of information about the instance,
it's hardware resources (especially its disks and their redundancy
status), etc. This is harder to parse and is more expensive than the
list operation, but returns much more detailed information.

Changing an instance's runtime memory
+++++++++++++++++++++++++++++++++++++

Ganeti will always make sure an instance has a value between its maximum
and its minimum memory available as runtime memory. As of version 2.6
Ganeti will only choose a size different than the maximum size when
starting up, failing over, or migrating an instance on a node with less
than the maximum memory available. It won't resize other instances in
order to free up space for an instance.

If you find that you need more memory on a node any instance can be
manually resized without downtime, with the command::

  $ gnt-instance modify -m %SIZE% %INSTANCE_NAME%

The same command can also be used to increase the memory available on an
instance, provided that enough free memory is available on its node, and
the specified size is not larger than the maximum memory size the
instance had when it was first booted (an instance will be unable to see
new memory above the maximum that was specified to the hypervisor at its
boot time, if it needs to grow further a reboot becomes necessary).

Export/Import
+++++++++++++

You can create a snapshot of an instance disk and its Ganeti
configuration, which then you can backup, or import into another
cluster. The way to export an instance is::

  $ gnt-backup export -n %TARGET_NODE% %INSTANCE_NAME%


The target node can be any node in the cluster with enough space under
``/srv/ganeti`` to hold the instance image. Use the ``--noshutdown``
option to snapshot an instance without rebooting it. Note that Ganeti
only keeps one snapshot for an instance - any previous snapshot of the
same instance existing cluster-wide under ``/srv/ganeti`` will be
removed by this operation: if you want to keep them, you need to move
them out of the Ganeti exports directory.

Importing an instance is similar to creating a new one, but additionally
one must specify the location of the snapshot. The command is::

  $ gnt-backup import -n %TARGET_NODE% \
    --src-node=%NODE% --src-dir=%DIR% %INSTANCE_NAME%

By default, parameters will be read from the export information, but you
can of course pass them in via the command line - most of the options
available for the command :command:`gnt-instance add` are supported here
too.

Import of foreign instances
+++++++++++++++++++++++++++

There is a possibility to import a foreign instance whose disk data is
already stored as LVM volumes without going through copying it: the disk
adoption mode.

For this, ensure that the original, non-managed instance is stopped,
then create a Ganeti instance in the usual way, except that instead of
passing the disk information you specify the current volumes::

  $ gnt-instance add -t plain -n %HOME_NODE% ... \
    --disk 0:adopt=%lv_name%[,vg=%vg_name%] %INSTANCE_NAME%

This will take over the given logical volumes, rename them to the Ganeti
standard (UUID-based), and without installing the OS on them start
directly the instance. If you configure the hypervisor similar to the
non-managed configuration that the instance had, the transition should
be seamless for the instance. For more than one disk, just pass another
disk parameter (e.g. ``--disk 1:adopt=...``).

Instance kernel selection
+++++++++++++++++++++++++

The kernel that instances uses to bootup can come either from the node,
or from instances themselves, depending on the setup.

Xen-PVM
~~~~~~~

With Xen PVM, there are three options.

First, you can use a kernel from the node, by setting the hypervisor
parameters as such:

- ``kernel_path`` to a valid file on the node (and appropriately
  ``initrd_path``)
- ``kernel_args`` optionally set to a valid Linux setting (e.g. ``ro``)
- ``root_path`` to a valid setting (e.g. ``/dev/xvda1``)
- ``bootloader_path`` and ``bootloader_args`` to empty

Alternatively, you can delegate the kernel management to instances, and
use either ``pvgrub`` or the deprecated ``pygrub``. For this, you must
install the kernels and initrds in the instance and create a valid GRUB
v1 configuration file.

For ``pvgrub`` (new in version 2.4.2), you need to set:

- ``kernel_path`` to point to the ``pvgrub`` loader present on the node
  (e.g. ``/usr/lib/xen/boot/pv-grub-x86_32.gz``)
- ``kernel_args`` to the path to the GRUB config file, relative to the
  instance (e.g. ``(hd0,0)/grub/menu.lst``)
- ``root_path`` **must** be empty
- ``bootloader_path`` and ``bootloader_args`` to empty

While ``pygrub`` is deprecated, here is how you can configure it:

- ``bootloader_path`` to the pygrub binary (e.g. ``/usr/bin/pygrub``)
- the other settings are not important

More information can be found in the Xen wiki pages for `pvgrub
<http://wiki.xensource.com/xenwiki/PvGrub>`_ and `pygrub
<http://wiki.xensource.com/xenwiki/PyGrub>`_.

KVM
~~~

For KVM also the kernel can be loaded either way.

For loading the kernels from the node, you need to set:

- ``kernel_path`` to a valid value
- ``initrd_path`` optionally set if you use an initrd
- ``kernel_args`` optionally set to a valid value (e.g. ``ro``)

If you want instead to have the instance boot from its disk (and execute
its bootloader), simply set the ``kernel_path`` parameter to an empty
string, and all the others will be ignored.

Instance HA features
--------------------

.. note:: This section only applies to multi-node clusters

.. _instance-change-primary-label:

Changing the primary node
+++++++++++++++++++++++++

There are three ways to exchange an instance's primary and secondary
nodes; the right one to choose depends on how the instance has been
created and the status of its current primary node. See
:ref:`rest-redundancy-label` for information on changing the secondary
node. Note that it's only possible to change the primary node to the
secondary and vice-versa; a direct change of the primary node with a
third node, while keeping the current secondary is not possible in a
single step, only via multiple operations as detailed in
:ref:`instance-relocation-label`.

Failing over an instance
~~~~~~~~~~~~~~~~~~~~~~~~

If an instance is built in highly available mode you can at any time
fail it over to its secondary node, even if the primary has somehow
failed and it's not up anymore. Doing it is really easy, on the master
node you can just run::

  $ gnt-instance failover %INSTANCE_NAME%

That's it. After the command completes the secondary node is now the
primary, and vice-versa.

The instance will be started with an amount of memory between its
``maxmem`` and its ``minmem`` value, depending on the free memory on its
target node, or the operation will fail if that's not possible. See
:ref:`instance-startup-label` for details.

If the instance's disk template is of type rbd, then you can specify
the target node (which can be any node) explicitly, or specify an
iallocator plugin. If you omit both, the default iallocator will be
used to determine the target node::

  $ gnt-instance failover -n %TARGET_NODE% %INSTANCE_NAME%

Live migrating an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~

If an instance is built in highly available mode, it currently runs and
both its nodes are running fine, you can migrate it over to its
secondary node, without downtime. On the master node you need to run::

  $ gnt-instance migrate %INSTANCE_NAME%

The current load on the instance and its memory size will influence how
long the migration will take. In any case, for both KVM and Xen
hypervisors, the migration will be transparent to the instance.

If the destination node has less memory than the instance's current
runtime memory, but at least the instance's minimum memory available
Ganeti will automatically reduce the instance runtime memory before
migrating it, unless the ``--no-runtime-changes`` option is passed, in
which case the target node should have at least the instance's current
runtime memory free.

If the instance's disk template is of type rbd, then you can specify
the target node (which can be any node) explicitly, or specify an
iallocator plugin. If you omit both, the default iallocator will be
used to determine the target node::

   $ gnt-instance migrate -n %TARGET_NODE% %INSTANCE_NAME%

Moving an instance (offline)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If an instance has not been create as mirrored, then the only way to
change its primary node is to execute the move command::

  $ gnt-instance move -n %NEW_NODE% %INSTANCE%

This has a few prerequisites:

- the instance must be stopped
- its current primary node must be on-line and healthy
- the disks of the instance must not have any errors

Since this operation actually copies the data from the old node to the
new node, expect it to take proportional to the size of the instance's
disks and the speed of both the nodes' I/O system and their networking.

Disk operations
+++++++++++++++

Disk failures are a common cause of errors in any server
deployment. Ganeti offers protection from single-node failure if your
instances were created in HA mode, and it also offers ways to restore
redundancy after a failure.

Preparing for disk operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It is important to note that for Ganeti to be able to do any disk
operation, the Linux machines on top of which Ganeti runs must be
consistent; for LVM, this means that the LVM commands must not return
failures; it is common that after a complete disk failure, any LVM
command aborts with an error similar to::

  $ vgs
  /dev/sdb1: read failed after 0 of 4096 at 0: Input/output error
  /dev/sdb1: read failed after 0 of 4096 at 750153695232: Input/output error
  /dev/sdb1: read failed after 0 of 4096 at 0: Input/output error
  Couldn't find device with uuid 't30jmN-4Rcf-Fr5e-CURS-pawt-z0jU-m1TgeJ'.
  Couldn't find all physical volumes for volume group xenvg.

Before restoring an instance's disks to healthy status, it's needed to
fix the volume group used by Ganeti so that we can actually create and
manage the logical volumes. This is usually done in a multi-step
process:

#. first, if the disk is completely gone and LVM commands exit with
   “Couldn't find device with uuid…” then you need to run the command::

    $ vgreduce --removemissing %VOLUME_GROUP%

#. after the above command, the LVM commands should be executing
   normally (warnings are normal, but the commands will not fail
   completely).

#. if the failed disk is still visible in the output of the ``pvs``
   command, you need to deactivate it from allocations by running::

    $ pvs -x n /dev/%DISK%

At this point, the volume group should be consistent and any bad
physical volumes should not longer be available for allocation.

Note that since version 2.1 Ganeti provides some commands to automate
these two operations, see :ref:`storage-units-label`.

.. _rest-redundancy-label:

Restoring redundancy for DRBD-based instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A DRBD instance has two nodes, and the storage on one of them has
failed. Depending on which node (primary or secondary) has failed, you
have three options at hand:

- if the storage on the primary node has failed, you need to re-create
  the disks on it
- if the storage on the secondary node has failed, you can either
  re-create the disks on it or change the secondary and recreate
  redundancy on the new secondary node

Of course, at any point it's possible to force re-creation of disks even
though everything is already fine.

For all three cases, the ``replace-disks`` operation can be used::

  # re-create disks on the primary node
  $ gnt-instance replace-disks -p %INSTANCE_NAME%
  # re-create disks on the current secondary
  $ gnt-instance replace-disks -s %INSTANCE_NAME%
  # change the secondary node, via manual specification
  $ gnt-instance replace-disks -n %NODE% %INSTANCE_NAME%
  # change the secondary node, via an iallocator script
  $ gnt-instance replace-disks -I %SCRIPT% %INSTANCE_NAME%
  # since Ganeti 2.1: automatically fix the primary or secondary node
  $ gnt-instance replace-disks -a %INSTANCE_NAME%

Since the process involves copying all data from the working node to the
target node, it will take a while, depending on the instance's disk
size, node I/O system and network speed. But it is (barring any network
interruption) completely transparent for the instance.

Re-creating disks for non-redundant instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 2.1

For non-redundant instances, there isn't a copy (except backups) to
re-create the disks. But it's possible to at-least re-create empty
disks, after which a reinstall can be run, via the ``recreate-disks``
command::

  $ gnt-instance recreate-disks %INSTANCE%

Note that this will fail if the disks already exists. The instance can
be assigned to new nodes automatically by specifying an iallocator
through the ``--iallocator`` option.

Conversion of an instance's disk type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It is possible to convert between a non-redundant instance of type
``plain`` (LVM storage) and redundant ``drbd`` via the ``gnt-instance
modify`` command::

  # start with a non-redundant instance
  $ gnt-instance add -t plain ... %INSTANCE%

  # later convert it to redundant
  $ gnt-instance stop %INSTANCE%
  $ gnt-instance modify -t drbd -n %NEW_SECONDARY% %INSTANCE%
  $ gnt-instance start %INSTANCE%

  # and convert it back
  $ gnt-instance stop %INSTANCE%
  $ gnt-instance modify -t plain %INSTANCE%
  $ gnt-instance start %INSTANCE%

The conversion must be done while the instance is stopped, and
converting from plain to drbd template presents a small risk, especially
if the instance has multiple disks and/or if one node fails during the
conversion procedure). As such, it's recommended (as always) to make
sure that downtime for manual recovery is acceptable and that the
instance has up-to-date backups.

Debugging instances
+++++++++++++++++++

Accessing an instance's disks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

From an instance's primary node you can have access to its disks. Never
ever mount the underlying logical volume manually on a fault tolerant
instance, or will break replication and your data will be
inconsistent. The correct way to access an instance's disks is to run
(on the master node, as usual) the command::

  $ gnt-instance activate-disks %INSTANCE%

And then, *on the primary node of the instance*, access the device that
gets created. For example, you could mount the given disks, then edit
files on the filesystem, etc.

Note that with partitioned disks (as opposed to whole-disk filesystems),
you will need to use a tool like :manpage:`kpartx(8)`::

  # on node1
  $ gnt-instance activate-disks %instance1%
  node3:disk/0:…
  $ ssh node3
  # on node 3
  $ kpartx -l /dev/…
  $ kpartx -a /dev/…
  $ mount /dev/mapper/… /mnt/
  # edit files under mnt as desired
  $ umount /mnt/
  $ kpartx -d /dev/…
  $ exit
  # back to node 1

After you've finished you can deactivate them with the deactivate-disks
command, which works in the same way::

  $ gnt-instance deactivate-disks %INSTANCE%

Note that if any process started by you is still using the disks, the
above command will error out, and you **must** cleanup and ensure that
the above command runs successfully before you start the instance,
otherwise the instance will suffer corruption.

Accessing an instance's console
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The command to access a running instance's console is::

  $ gnt-instance console %INSTANCE_NAME%

Use the console normally and then type ``^]`` when done, to exit.

Other instance operations
+++++++++++++++++++++++++

Reboot
~~~~~~

There is a wrapper command for rebooting instances::

  $ gnt-instance reboot %instance2%

By default, this does the equivalent of shutting down and then starting
the instance, but it accepts parameters to perform a soft-reboot (via
the hypervisor), a hard reboot (hypervisor shutdown and then startup) or
a full one (the default, which also de-configures and then configures
again the disks of the instance).

Instance OS definitions debugging
+++++++++++++++++++++++++++++++++

Should you have any problems with instance operating systems the command
to see a complete status for all your nodes is::

   $ gnt-os diagnose

.. _instance-relocation-label:

Instance relocation
~~~~~~~~~~~~~~~~~~~

While it is not possible to move an instance from nodes ``(A, B)`` to
nodes ``(C, D)`` in a single move, it is possible to do so in a few
steps::

  # instance is located on A, B
  $ gnt-instance replace-disks -n %nodeC% %instance1%
  # instance has moved from (A, B) to (A, C)
  # we now flip the primary/secondary nodes
  $ gnt-instance migrate %instance1%
  # instance lives on (C, A)
  # we can then change A to D via:
  $ gnt-instance replace-disks -n %nodeD% %instance1%

Which brings it into the final configuration of ``(C, D)``. Note that we
needed to do two replace-disks operation (two copies of the instance
disks), because we needed to get rid of both the original nodes (A and
B).

Network Management
------------------

Ganeti used to describe NICs of an Instance with an IP, a MAC, a connectivity
link and mode. This had three major shortcomings:

  * there was no easy way to assign a unique IP to an instance
  * network info (subnet, gateway, domain, etc.) was not available on target
    node (kvm-ifup, hooks, etc)
  * one should explicitly pass L2 info (mode, and link) to every NIC

Plus there was no easy way to get the current networking overview (which
instances are on the same L2 or L3 network, which IPs are reserved, etc).

All the above required an external management tool that has an overall view
and provides the corresponding info to Ganeti.

gnt-network aims to support a big part of this functionality inside Ganeti and
abstract the network as a separate entity. Currently, a Ganeti network
provides the following:

  * A single IPv4 pool, subnet and gateway
  * Connectivity info per nodegroup (mode, link)
  * MAC prefix for each NIC inside the network
  * IPv6 prefix/Gateway related to this network
  * Tags

IP pool management ensures IP uniqueness inside this network. The user can
pass `ip=pool,network=test` and will:

1. Get the first available IP in the pool
2. Inherit the connectivity mode and link of the network's netparams
3. NIC will obtain the MAC prefix of the network
4. All network related info will be available as environment variables in
   kvm-ifup scripts and hooks, so that they can dynamically manage all
   networking-related setup on the host.

Hands on with gnt-network
+++++++++++++++++++++++++

To create a network do::

  # gnt-network add --network=192.0.2.0/24 --gateway=192.0.2.1 test

Please see all other available options (--add-reserved-ips, --mac-prefix,
--network6, --gateway6, --tags).

Currently, IPv6 info is not used by Ganeti itself. It only gets exported
to NIC configuration scripts and hooks via environment variables.

To make this network available on a nodegroup you should specify the
connectivity mode and link during connection::

  # gnt-network connect --nic-parameters mode=bridged,link=br100 test default nodegroup1

To add a NIC inside this network::

  # gnt-instance modify --net -1:add,ip=pool,network=test inst1

This will let a NIC obtain a unique IP inside this network, and inherit the
nodegroup's netparams (bridged, br100). IP here is optional. If missing the
NIC will just get the L2 info.

To move an existing NIC from a network to another and remove its IP::

  # gnt-instance modify --net -1:ip=none,network=test1 inst1

This will release the old IP from the old IP pool and the NIC will inherit the
new nicparams.

On the above actions there is a extra option `--no-conflicts-ckeck`. This
does not check for conflicting setups. Specifically:

1. When a network is added, IPs of nodes and master are not being checked.
2. When connecting a network on a nodegroup, IPs of instances inside this
   nodegroup are not checked whether they reside inside the subnet or not.
3. When specifying explicitly a IP without passing a network, Ganeti will not
   check if this IP is included inside any available network on the nodegroup.

External components
+++++++++++++++++++

All the aforementioned steps assure NIC configuration from the Ganeti
perspective. Of course this has nothing to do, how the instance eventually will
get the desired connectivity (IPv4, IPv6, default routes, DNS info, etc) and
where will the IP resolve.  This functionality is managed by the external
components.

Let's assume that the VM will need to obtain a dynamic IP via DHCP, get a SLAAC
address, and use DHCPv6 for other configuration information (in case RFC-6106
is not supported by the client, e.g.  Windows).  This means that the following
external services are needed:

1. A DHCP server
2. An IPv6 router sending Router Advertisements
3. A DHCPv6 server exporting DNS info
4. A dynamic DNS server

These components must be configured dynamically and on a per NIC basis.
The way to do this is by using custom kvm-ifup scripts and hooks.

snf-network
~~~~~~~~~~~

The snf-network package [1,3] includes custom scripts that will provide the
aforementioned functionality. `kvm-vif-bridge` and `vif-custom` is an
alternative to `kvm-ifup` and `vif-ganeti` that take into account all network
info being exported. Their actions depend on network tags. Specifically:

`dns`: will update an external DDNS server (nsupdate on a bind server)

`ip-less-routed`: will setup routes, rules and proxy ARP
This setup assumes a pre-existing routing table along with some local
configuration and provides connectivity to instances via an external
gateway/router without requiring nodes to have an IP inside this network.

`private-filtered`: will setup ebtables rules to ensure L2 isolation on a
common bridge. Only packets with the same MAC prefix will be forwarded to the
corresponding virtual interface.

`nfdhcpd`: will update an external DHCP server

nfdhcpd
~~~~~~~

snf-network works with nfdhcpd [2,3]: a custom user space DHCP
server based on NFQUEUE. Currently, nfdhcpd replies on BOOTP/DHCP requests
originating from a tap or a bridge. Additionally in case of a routed setup it
provides a ra-stateless configuration by responding to router and neighbour
solicitations along with DHCPv6 requests for DNS options.  Its db is
dynamically updated using text files inside a local dir with inotify
(snf-network just adds a per NIC binding file with all relevant info if the
corresponding network tag is found). Still we need to mangle all these
packets and send them to the corresponding NFQUEUE.

Known shortcomings
++++++++++++++++++

Currently the following things are some know weak points of the gnt-network
design and implementation:

 * Cannot define a network without an IP pool
 * The pool defines the size of the network
 * Reserved IPs must be defined explicitly (inconvenient for a big range)
 * Cannot define an IPv6 only network

Future work
+++++++++++

Any upcoming patches should target:

 * Separate L2, L3, IPv6, IP pool info
 * Support a set of IP pools per network
 * Make IP/network in NIC object take a list of entries
 * Introduce external scripts for node configuration
   (dynamically create/destroy bridges/routes upon network connect/disconnect)

[1] https://code.grnet.gr/git/snf-network
[2] https://code.grnet.gr/git/snf-nfdhcpd
[3] deb http:/apt.dev.grnet.gr/ wheezy/

Node operations
---------------

There are much fewer node operations available than for instances, but
they are equivalently important for maintaining a healthy cluster.

Add/readd
+++++++++

It is at any time possible to extend the cluster with one more node, by
using the node add operation::

  $ gnt-node add %NEW_NODE%

If the cluster has a replication network defined, then you need to pass
the ``-s REPLICATION_IP`` parameter to this option.

A variation of this command can be used to re-configure a node if its
Ganeti configuration is broken, for example if it has been reinstalled
by mistake::

  $ gnt-node add --readd %EXISTING_NODE%

This will reinitialise the node as if it's been newly added, but while
keeping its existing configuration in the cluster (primary/secondary IP,
etc.), in other words you won't need to use ``-s`` here.

Changing the node role
++++++++++++++++++++++

A node can be in different roles, as explained in the
:ref:`terminology-label` section. Promoting a node to the master role is
special, while the other roles are handled all via a single command.

Failing over the master node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you want to promote a different node to the master role (for whatever
reason), run on any other master-candidate node the command::

  $ gnt-cluster master-failover

and the node you ran it on is now the new master. In case you try to run
this on a non master-candidate node, you will get an error telling you
which nodes are valid.

Changing between the other roles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The ``gnt-node modify`` command can be used to select a new role::

  # change to master candidate
  $ gnt-node modify -C yes %NODE%
  # change to drained status
  $ gnt-node modify -D yes %NODE%
  # change to offline status
  $ gnt-node modify -O yes %NODE%
  # change to regular mode (reset all flags)
  $ gnt-node modify -O no -D no -C no %NODE%

Note that the cluster requires that at any point in time, a certain
number of nodes are master candidates, so changing from master candidate
to other roles might fail. It is recommended to either force the
operation (via the ``--force`` option) or first change the number of
master candidates in the cluster - see :ref:`cluster-config-label`.

Evacuating nodes
++++++++++++++++

There are two steps of moving instances off a node:

- moving the primary instances (actually converting them into secondary
  instances)
- moving the secondary instances (including any instances converted in
  the step above)

Primary instance conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~

For this step, you can use either individual instance move
commands (as seen in :ref:`instance-change-primary-label`) or the bulk
per-node versions; these are::

  $ gnt-node migrate %NODE%
  $ gnt-node evacuate -s %NODE%

Note that the instance “move” command doesn't currently have a node
equivalent.

Both these commands, or the equivalent per-instance command, will make
this node the secondary node for the respective instances, whereas their
current secondary node will become primary. Note that it is not possible
to change in one step the primary node to another node as primary, while
keeping the same secondary node.

Secondary instance evacuation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For the evacuation of secondary instances, a command called
:command:`gnt-node evacuate` is provided and its syntax is::

  $ gnt-node evacuate -I %IALLOCATOR_SCRIPT% %NODE%
  $ gnt-node evacuate -n %DESTINATION_NODE% %NODE%

The first version will compute the new secondary for each instance in
turn using the given iallocator script, whereas the second one will
simply move all instances to DESTINATION_NODE.

Removal
+++++++

Once a node no longer has any instances (neither primary nor secondary),
it's easy to remove it from the cluster::

  $ gnt-node remove %NODE_NAME%

This will deconfigure the node, stop the ganeti daemons on it and leave
it hopefully like before it joined to the cluster.

Replication network changes
+++++++++++++++++++++++++++

The :command:`gnt-node modify -s` command can be used to change the
secondary IP of a node. This operation can only be performed if:

- No instance is active on the target node
- The new target IP is reachable from the master's secondary IP

Also this operation will not allow to change a node from single-homed
(same primary and secondary ip) to multi-homed (separate replication
network) or vice versa, unless:

- The target node is the master node and `--force` is passed.
- The target cluster is single-homed and the new primary ip is a change
  to single homed for a particular node.
- The target cluster is multi-homed and the new primary ip is a change
  to multi homed for a particular node.

For example to do a single-homed to multi-homed conversion::

  $ gnt-node modify --force -s %SECONDARY_IP% %MASTER_NAME%
  $ gnt-node modify -s %SECONDARY_IP% %NODE1_NAME%
  $ gnt-node modify -s %SECONDARY_IP% %NODE2_NAME%
  $ gnt-node modify -s %SECONDARY_IP% %NODE3_NAME%
  ...

The same commands can be used for multi-homed to single-homed except the
secondary IPs should be the same as the primaries for each node, for
that case.

Storage handling
++++++++++++++++

When using LVM (either standalone or with DRBD), it can become tedious
to debug and fix it in case of errors. Furthermore, even file-based
storage can become complicated to handle manually on many hosts. Ganeti
provides a couple of commands to help with automation.

Logical volumes
~~~~~~~~~~~~~~~

This is a command specific to LVM handling. It allows listing the
logical volumes on a given node or on all nodes and their association to
instances via the ``volumes`` command::

  $ gnt-node volumes
  Node  PhysDev   VG    Name             Size Instance
  node1 /dev/sdb1 xenvg e61fbc97-….disk0 512M instance17
  node1 /dev/sdb1 xenvg ebd1a7d1-….disk0 512M instance19
  node2 /dev/sdb1 xenvg 0af08a3d-….disk0 512M instance20
  node2 /dev/sdb1 xenvg cc012285-….disk0 512M instance16
  node2 /dev/sdb1 xenvg f0fac192-….disk0 512M instance18

The above command maps each logical volume to a volume group and
underlying physical volume and (possibly) to an instance.

.. _storage-units-label:

Generalized storage handling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 2.1

Starting with Ganeti 2.1, a new storage framework has been implemented
that tries to abstract the handling of the storage type the cluster
uses.

First is listing the backend storage and their space situation::

  $ gnt-node list-storage
  Node  Type   Name  Size Used Free Allocatable
  node1 lvm-vg xenvg 3.6T   0M 3.6T Y
  node2 lvm-vg xenvg 3.6T   0M 3.6T Y
  node3 lvm-vg xenvg 3.6T 2.0G 3.6T Y

The default is to list LVM physical volumes. It's also possible to list
the LVM volume groups::

  $ gnt-node list-storage -t lvm-vg
  Node  Type   Name  Size Used Free Allocatable
  node1 lvm-vg xenvg 3.6T   0M 3.6T Y
  node2 lvm-vg xenvg 3.6T   0M 3.6T Y
  node3 lvm-vg xenvg 3.6T 2.0G 3.6T Y

Next is repairing storage units, which is currently only implemented for
volume groups and does the equivalent of ``vgreduce --removemissing``::

  $ gnt-node repair-storage %node2% lvm-vg xenvg
  Sun Oct 25 22:21:45 2009 Repairing storage unit 'xenvg' on node2 ...

Last is the modification of volume properties, which is (again) only
implemented for LVM physical volumes and allows toggling the
``allocatable`` value::

  $ gnt-node modify-storage --allocatable=no %node2% lvm-pv /dev/%sdb1%

Use of the storage commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~

All these commands are needed when recovering a node from a disk
failure:

- first, we need to recover from complete LVM failure (due to missing
  disk), by running the ``repair-storage`` command
- second, we need to change allocation on any partially-broken disk
  (i.e. LVM still sees it, but it has bad blocks) by running
  ``modify-storage``
- then we can evacuate the instances as needed


Cluster operations
------------------

Beside the cluster initialisation command (which is detailed in the
:doc:`install` document) and the master failover command which is
explained under node handling, there are a couple of other cluster
operations available.

.. _cluster-config-label:

Standard operations
+++++++++++++++++++

One of the few commands that can be run on any node (not only the
master) is the ``getmaster`` command::

  # on node2
  $ gnt-cluster getmaster
  node1.example.com

It is possible to query and change global cluster parameters via the
``info`` and ``modify`` commands::

  $ gnt-cluster info
  Cluster name: cluster.example.com
  Cluster UUID: 07805e6f-f0af-4310-95f1-572862ee939c
  Creation time: 2009-09-25 05:04:15
  Modification time: 2009-10-18 22:11:47
  Master node: node1.example.com
  Architecture (this node): 64bit (x86_64)
  …
  Tags: foo
  Default hypervisor: xen-pvm
  Enabled hypervisors: xen-pvm
  Hypervisor parameters:
    - xen-pvm:
        root_path: /dev/sda1
        …
  Cluster parameters:
    - candidate pool size: 10
      …
  Default instance parameters:
    - default:
        memory: 128
        …
  Default nic parameters:
    - default:
        link: xen-br0
        …

There various parameters above can be changed via the ``modify``
commands as follows:

- the hypervisor parameters can be changed via ``modify -H
  xen-pvm:root_path=…``, and so on for other hypervisors/key/values
- the "default instance parameters" are changeable via ``modify -B
  parameter=value…`` syntax
- the cluster parameters are changeable via separate options to the
  modify command (e.g. ``--candidate-pool-size``, etc.)

For detailed option list see the :manpage:`gnt-cluster(8)` man page.

The cluster version can be obtained via the ``version`` command::

  $ gnt-cluster version
  Software version: 2.1.0
  Internode protocol: 20
  Configuration format: 2010000
  OS api version: 15
  Export interface: 0

This is not very useful except when debugging Ganeti.

Global node commands
++++++++++++++++++++

There are two commands provided for replicating files to all nodes of a
cluster and for running commands on all the nodes::

  $ gnt-cluster copyfile %/path/to/file%
  $ gnt-cluster command %ls -l /path/to/file%

These are simple wrappers over scp/ssh and more advanced usage can be
obtained using :manpage:`dsh(1)` and similar commands. But they are
useful to update an OS script from the master node, for example.

Cluster verification
++++++++++++++++++++

There are three commands that relate to global cluster checks. The first
one is ``verify`` which gives an overview on the cluster state,
highlighting any issues. In normal operation, this command should return
no ``ERROR`` messages::

  $ gnt-cluster verify
  Sun Oct 25 23:08:58 2009 * Verifying global settings
  Sun Oct 25 23:08:58 2009 * Gathering data (2 nodes)
  Sun Oct 25 23:09:00 2009 * Verifying node status
  Sun Oct 25 23:09:00 2009 * Verifying instance status
  Sun Oct 25 23:09:00 2009 * Verifying orphan volumes
  Sun Oct 25 23:09:00 2009 * Verifying remaining instances
  Sun Oct 25 23:09:00 2009 * Verifying N+1 Memory redundancy
  Sun Oct 25 23:09:00 2009 * Other Notes
  Sun Oct 25 23:09:00 2009   - NOTICE: 5 non-redundant instance(s) found.
  Sun Oct 25 23:09:00 2009 * Hooks Results

The second command is ``verify-disks``, which checks that the instance's
disks have the correct status based on the desired instance state
(up/down)::

  $ gnt-cluster verify-disks

Note that this command will show no output when disks are healthy.

The last command is used to repair any discrepancies in Ganeti's
recorded disk size and the actual disk size (disk size information is
needed for proper activation and growth of DRBD-based disks)::

  $ gnt-cluster repair-disk-sizes
  Sun Oct 25 23:13:16 2009  - INFO: Disk 0 of instance instance1 has mismatched size, correcting: recorded 512, actual 2048
  Sun Oct 25 23:13:17 2009  - WARNING: Invalid result from node node4, ignoring node results

The above shows one instance having wrong disk size, and a node which
returned invalid data, and thus we ignored all primary instances of that
node.

Configuration redistribution
++++++++++++++++++++++++++++

If the verify command complains about file mismatches between the master
and other nodes, due to some node problems or if you manually modified
configuration files, you can force an push of the master configuration
to all other nodes via the ``redist-conf`` command::

  $ gnt-cluster redist-conf

This command will be silent unless there are problems sending updates to
the other nodes.


Cluster renaming
++++++++++++++++

It is possible to rename a cluster, or to change its IP address, via the
``rename`` command. If only the IP has changed, you need to pass the
current name and Ganeti will realise its IP has changed::

  $ gnt-cluster rename %cluster.example.com%
  This will rename the cluster to 'cluster.example.com'. If
  you are connected over the network to the cluster name, the operation
  is very dangerous as the IP address will be removed from the node and
  the change may not go through. Continue?
  y/[n]/?: %y%
  Failure: prerequisites not met for this operation:
  Neither the name nor the IP address of the cluster has changed

In the above output, neither value has changed since the cluster
initialisation so the operation is not completed.

Queue operations
++++++++++++++++

The job queue execution in Ganeti 2.0 and higher can be inspected,
suspended and resumed via the ``queue`` command::

  $ gnt-cluster queue info
  The drain flag is unset
  $ gnt-cluster queue drain
  $ gnt-instance stop %instance1%
  Failed to submit job for instance1: Job queue is drained, refusing job
  $ gnt-cluster queue info
  The drain flag is set
  $ gnt-cluster queue undrain

This is most useful if you have an active cluster and you need to
upgrade the Ganeti software, or simply restart the software on any node:

#. suspend the queue via ``queue drain``
#. wait until there are no more running jobs via ``gnt-job list``
#. restart the master or another node, or upgrade the software
#. resume the queue via ``queue undrain``

.. note:: this command only stores a local flag file, and if you
   failover the master, it will not have effect on the new master.


Watcher control
+++++++++++++++

The :manpage:`ganeti-watcher(8)` is a program, usually scheduled via
``cron``, that takes care of cluster maintenance operations (restarting
downed instances, activating down DRBD disks, etc.). However, during
maintenance and troubleshooting, this can get in your way; disabling it
via commenting out the cron job is not so good as this can be
forgotten. Thus there are some commands for automated control of the
watcher: ``pause``, ``info`` and ``continue``::

  $ gnt-cluster watcher info
  The watcher is not paused.
  $ gnt-cluster watcher pause %1h%
  The watcher is paused until Mon Oct 26 00:30:37 2009.
  $ gnt-cluster watcher info
  The watcher is paused until Mon Oct 26 00:30:37 2009.
  $ ganeti-watcher -d
  2009-10-25 23:30:47,984:  pid=28867 ganeti-watcher:486 DEBUG Pause has been set, exiting
  $ gnt-cluster watcher continue
  The watcher is no longer paused.
  $ ganeti-watcher -d
  2009-10-25 23:31:04,789:  pid=28976 ganeti-watcher:345 DEBUG Archived 0 jobs, left 0
  2009-10-25 23:31:05,884:  pid=28976 ganeti-watcher:280 DEBUG Got data from cluster, writing instance status file
  2009-10-25 23:31:06,061:  pid=28976 ganeti-watcher:150 DEBUG Data didn't change, just touching status file
  $ gnt-cluster watcher info
  The watcher is not paused.

The exact details of the argument to the ``pause`` command are available
in the manpage.

.. note:: this command only stores a local flag file, and if you
   failover the master, it will not have effect on the new master.

Node auto-maintenance
+++++++++++++++++++++

If the cluster parameter ``maintain_node_health`` is enabled (see the
manpage for :command:`gnt-cluster`, the init and modify subcommands),
then the following will happen automatically:

- the watcher will shutdown any instances running on offline nodes
- the watcher will deactivate any DRBD devices on offline nodes

In the future, more actions are planned, so only enable this parameter
if the nodes are completely dedicated to Ganeti; otherwise it might be
possible to lose data due to auto-maintenance actions.

Removing a cluster entirely
+++++++++++++++++++++++++++

The usual method to cleanup a cluster is to run ``gnt-cluster destroy``
however if the Ganeti installation is broken in any way then this will
not run.

It is possible in such a case to cleanup manually most if not all traces
of a cluster installation by following these steps on all of the nodes:

1. Shutdown all instances. This depends on the virtualisation method
   used (Xen, KVM, etc.):

  - Xen: run ``xm list`` and ``xm destroy`` on all the non-Domain-0
    instances
  - KVM: kill all the KVM processes
  - chroot: kill all processes under the chroot mountpoints

2. If using DRBD, shutdown all DRBD minors (which should by at this time
   no-longer in use by instances); on each node, run ``drbdsetup
   /dev/drbdN down`` for each active DRBD minor.

3. If using LVM, cleanup the Ganeti volume group; if only Ganeti created
   logical volumes (and you are not sharing the volume group with the
   OS, for example), then simply running ``lvremove -f xenvg`` (replace
   'xenvg' with your volume group name) should do the required cleanup.

4. If using file-based storage, remove recursively all files and
   directories under your file-storage directory: ``rm -rf
   /srv/ganeti/file-storage/*`` replacing the path with the correct path
   for your cluster.

5. Stop the ganeti daemons (``/etc/init.d/ganeti stop``) and kill any
   that remain alive (``pgrep ganeti`` and ``pkill ganeti``).

6. Remove the ganeti state directory (``rm -rf /var/lib/ganeti/*``),
   replacing the path with the correct path for your installation.

7. If using RBD, run ``rbd unmap /dev/rbdN`` to unmap the RBD disks.
   Then remove the RBD disk images used by Ganeti, identified by their
   UUIDs (``rbd rm uuid.rbd.diskN``).

On the master node, remove the cluster from the master-netdev (usually
``xen-br0`` for bridged mode, otherwise ``eth0`` or similar), by running
``ip a del $clusterip/32 dev xen-br0`` (use the correct cluster ip and
network device name).

At this point, the machines are ready for a cluster creation; in case
you want to remove Ganeti completely, you need to also undo some of the
SSH changes and log directories:

- ``rm -rf /var/log/ganeti /srv/ganeti`` (replace with the correct
  paths)
- remove from ``/root/.ssh`` the keys that Ganeti added (check the
  ``authorized_keys`` and ``id_dsa`` files)
- regenerate the host's SSH keys (check the OpenSSH startup scripts)
- uninstall Ganeti

Otherwise, if you plan to re-create the cluster, you can just go ahead
and rerun ``gnt-cluster init``.

Replacing the SSH and SSL keys
++++++++++++++++++++++++++++++

Ganeti uses both SSL and SSH keys, and actively modifies the SSH keys on
the nodes.  As result, in order to replace these keys, a few extra steps
need to be followed: :doc:`cluster-keys-replacement`

Monitoring the cluster
----------------------

Starting with Ganeti 2.8, a monitoring daemon is available, providing
information about the status and the performance of the system.

The monitoring daemon runs on every node, listening on TCP port 1815. Each
instance of the daemon provides information related to the node it is running
on.

.. include:: monitoring-query-format.rst

Tags handling
-------------

The tags handling (addition, removal, listing) is similar for all the
objects that support it (instances, nodes, and the cluster).

Limitations
+++++++++++

Note that the set of characters present in a tag and the maximum tag
length are restricted. Currently the maximum length is 128 characters,
there can be at most 4096 tags per object, and the set of characters is
comprised by alphanumeric characters and additionally ``.+*/:@-_``.

Operations
++++++++++

Tags can be added via ``add-tags``::

  $ gnt-instance add-tags %INSTANCE% %a% %b% %c%
  $ gnt-node add-tags %INSTANCE% %a% %b% %c%
  $ gnt-cluster add-tags %a% %b% %c%


The above commands add three tags to an instance, to a node and to the
cluster. Note that the cluster command only takes tags as arguments,
whereas the node and instance commands first required the node and
instance name.

Tags can also be added from a file, via the ``--from=FILENAME``
argument. The file is expected to contain one tag per line.

Tags can also be remove via a syntax very similar to the add one::

  $ gnt-instance remove-tags %INSTANCE% %a% %b% %c%

And listed via::

  $ gnt-instance list-tags
  $ gnt-node list-tags
  $ gnt-cluster list-tags

Global tag search
+++++++++++++++++

It is also possible to execute a global search on the all tags defined
in the cluster configuration, via a cluster command::

  $ gnt-cluster search-tags %REGEXP%

The parameter expected is a regular expression (see
:manpage:`regex(7)`). This will return all tags that match the search,
together with the object they are defined in (the names being show in a
hierarchical kind of way)::

  $ gnt-cluster search-tags %o%
  /cluster foo
  /instances/instance1 owner:bar

Autorepair
----------

The tool ``harep`` can be used to automatically fix some problems that are
present in the cluster.

It is mainly meant to be regularly and automatically executed
as a cron job. This is quite evident by considering that, when executed, it does
not immediately fix all the issues of the instances of the cluster, but it
cycles the instances through a series of states, one at every ``harep``
execution. Every state performs a step towards the resolution of the problem.
This process goes on until the instance is brought back to the healthy state,
or the tool realizes that it is not able to fix the instance, and
therefore marks it as in failure state.

Allowing harep to act on the cluster
++++++++++++++++++++++++++++++++++++

By default, ``harep`` checks the status of the cluster but it is not allowed to
perform any modification. Modification must be explicitly allowed by an
appropriate use of tags. Tagging can be applied at various levels, and can
enable different kinds of autorepair, as hereafter described.

All the tags that authorize ``harep`` to perform modifications follow this
syntax::

  ganeti:watcher:autorepair:<type>

where ``<type>`` indicates the kind of intervention that can be performed. Every
possible value of ``<type>`` includes at least all the authorization of the
previous one, plus its own. The possible values, in increasing order of
severity, are:

- ``fix-storage`` allows a disk replacement or another operation that
  fixes the instance backend storage without affecting the instance
  itself. This can for example recover from a broken drbd secondary, but
  risks data loss if something is wrong on the primary but the secondary
  was somehow recoverable.
- ``migrate`` allows an instance migration. This can recover from a
  drained primary, but can cause an instance crash in some cases (bugs).
- ``failover`` allows instance reboot on the secondary. This can recover
  from an offline primary, but the instance will lose its running state.
- ``reinstall`` allows disks to be recreated and an instance to be
  reinstalled. This can recover from primary&secondary both being
  offline, or from an offline primary in the case of non-redundant
  instances. It causes data loss.

These autorepair tags can be applied to a cluster, a nodegroup or an instance,
and will act where they are applied and to everything in the entities sub-tree
(e.g. a tag applied to a nodegroup will apply to all the instances contained in
that nodegroup, but not to the rest of the cluster).

If there are multiple ``ganeti:watcher:autorepair:<type>`` tags in an
object (cluster, node group or instance), the least destructive tag
takes precedence. When multiplicity happens across objects, the nearest
tag wins. For example, if in a cluster with two instances, *I1* and
*I2*, *I1* has ``failover``, and the cluster itself has both
``fix-storage`` and ``reinstall``, *I1* will end up with ``failover``
and *I2* with ``fix-storage``.

Limiting harep
++++++++++++++

Sometimes it is useful to stop harep from performing its task temporarily,
and it is useful to be able to do so without distrupting its configuration, that
is, without removing the authorization tags. In order to do this, suspend tags
are provided.

Suspend tags can be added to cluster, nodegroup or instances, and act on the
entire entities sub-tree. No operation will be performed by ``harep`` on the
instances protected by a suspend tag. Their syntax is as follows::

  ganeti:watcher:autorepair:suspend[:<timestamp>]

If there are multiple suspend tags in an object, the form without timestamp
takes precedence (permanent suspension); or, if all object tags have a
timestamp, the one with the highest timestamp.

Tags with a timestamp will be automatically removed when the time indicated by
the timestamp is passed. Indefinite suspension tags have to be removed manually.

Result reporting
++++++++++++++++

Harep will report about the result of its actions both through its CLI, and by
adding tags to the instances it operated on. Such tags will follow the syntax
hereby described::

  ganeti:watcher:autorepair:result:<type>:<id>:<timestamp>:<result>:<jobs>

If this tag is present a repair of type ``type`` has been performed on
the instance and has been completed by ``timestamp``. The result is
either ``success``, ``failure`` or ``enoperm``, and jobs is a
*+*-separated list of jobs that were executed for this repair.

An ``enoperm`` result is an error state due to permission problems. It
is returned when the repair cannot proceed because it would require to perform
an operation that is not allowed by the ``ganeti:watcher:autorepair:<type>`` tag
that is defining the instance autorepair permissions.

NB: if an instance repair ends up in a failure state, it will not be touched
again by ``harep`` until it has been manually fixed by the system administrator
and the ``ganeti:watcher:autorepair:result:failure:*`` tag has been manually
removed.

Job operations
--------------

The various jobs submitted by the instance/node/cluster commands can be
examined, canceled and archived by various invocations of the
``gnt-job`` command.

First is the job list command::

  $ gnt-job list
  17771 success INSTANCE_QUERY_DATA
  17773 success CLUSTER_VERIFY_DISKS
  17775 success CLUSTER_REPAIR_DISK_SIZES
  17776 error   CLUSTER_RENAME(cluster.example.com)
  17780 success CLUSTER_REDIST_CONF
  17792 success INSTANCE_REBOOT(instance1.example.com)

More detailed information about a job can be found via the ``info``
command::

  $ gnt-job info %17776%
  Job ID: 17776
    Status: error
    Received:         2009-10-25 23:18:02.180569
    Processing start: 2009-10-25 23:18:02.200335 (delta 0.019766s)
    Processing end:   2009-10-25 23:18:02.279743 (delta 0.079408s)
    Total processing time: 0.099174 seconds
    Opcodes:
      OP_CLUSTER_RENAME
        Status: error
        Processing start: 2009-10-25 23:18:02.200335
        Processing end:   2009-10-25 23:18:02.252282
        Input fields:
          name: cluster.example.com
        Result:
          OpPrereqError
          [Neither the name nor the IP address of the cluster has changed]
        Execution log:

During the execution of a job, it's possible to follow the output of a
job, similar to the log that one get from the ``gnt-`` commands, via the
watch command::

  $ gnt-instance add --submit … %instance1%
  JobID: 17818
  $ gnt-job watch %17818%
  Output from job 17818 follows
  -----------------------------
  Mon Oct 26 00:22:48 2009  - INFO: Selected nodes for instance instance1 via iallocator dumb: node1, node2
  Mon Oct 26 00:22:49 2009 * creating instance disks...
  Mon Oct 26 00:22:52 2009 adding instance instance1 to cluster config
  Mon Oct 26 00:22:52 2009  - INFO: Waiting for instance instance1 to sync disks.
  …
  Mon Oct 26 00:23:03 2009 creating os for instance instance1 on node node1
  Mon Oct 26 00:23:03 2009 * running the instance OS create scripts...
  Mon Oct 26 00:23:13 2009 * starting instance...
  $

This is useful if you need to follow a job's progress from multiple
terminals.

A job that has not yet started to run can be canceled::

  $ gnt-job cancel %17810%

But not one that has already started execution::

  $ gnt-job cancel %17805%
  Job 17805 is no longer waiting in the queue

There are two queues for jobs: the *current* and the *archive*
queue. Jobs are initially submitted to the current queue, and they stay
in that queue until they have finished execution (either successfully or
not). At that point, they can be moved into the archive queue using e.g.
``gnt-job autoarchive all``. The ``ganeti-watcher`` script will do this
automatically 6 hours after a job is finished. The ``ganeti-cleaner``
script will then remove archived the jobs from the archive directory
after three weeks.

Note that ``gnt-job list`` only shows jobs in the current queue.
Archived jobs can be viewed using ``gnt-job info <id>``.

Special Ganeti deployments
--------------------------

Since Ganeti 2.4, it is possible to extend the Ganeti deployment with
two custom scenarios: Ganeti inside Ganeti and multi-site model.

Running Ganeti under Ganeti
+++++++++++++++++++++++++++

It is sometimes useful to be able to use a Ganeti instance as a Ganeti
node (part of another cluster, usually). One example scenario is two
small clusters, where we want to have an additional master candidate
that holds the cluster configuration and can be used for helping with
the master voting process.

However, these Ganeti instance should not host instances themselves, and
should not be considered in the normal capacity planning, evacuation
strategies, etc. In order to accomplish this, mark these nodes as
non-``vm_capable``::

  $ gnt-node modify --vm-capable=no %node3%

The vm_capable status can be listed as usual via ``gnt-node list``::

  $ gnt-node list -oname,vm_capable
  Node  VMCapable
  node1 Y
  node2 Y
  node3 N

When this flag is set, the cluster will not do any operations that
relate to instances on such nodes, e.g. hypervisor operations,
disk-related operations, etc. Basically they will just keep the ssconf
files, and if master candidates the full configuration.

Multi-site model
++++++++++++++++

If Ganeti is deployed in multi-site model, with each site being a node
group (so that instances are not relocated across the WAN by mistake),
it is conceivable that either the WAN latency is high or that some sites
have a lower reliability than others. In this case, it doesn't make
sense to replicate the job information across all sites (or even outside
of a “central” node group), so it should be possible to restrict which
nodes can become master candidates via the auto-promotion algorithm.

Ganeti 2.4 introduces for this purpose a new ``master_capable`` flag,
which (when unset) prevents nodes from being marked as master
candidates, either manually or automatically.

As usual, the node modify operation can change this flag::

  $ gnt-node modify --auto-promote --master-capable=no %node3%
  Fri Jan  7 06:23:07 2011  - INFO: Demoting from master candidate
  Fri Jan  7 06:23:08 2011  - INFO: Promoted nodes to master candidate role: node4
  Modified node node3
   - master_capable -> False
   - master_candidate -> False

And the node list operation will list this flag::

  $ gnt-node list -oname,master_capable %node1% %node2% %node3%
  Node  MasterCapable
  node1 Y
  node2 Y
  node3 N

Note that marking a node both not ``vm_capable`` and not
``master_capable`` makes the node practically unusable from Ganeti's
point of view. Hence these two flags should be used probably in
contrast: some nodes will be only master candidates (master_capable but
not vm_capable), and other nodes will only hold instances (vm_capable
but not master_capable).


Ganeti tools
------------

Beside the usual ``gnt-`` and ``ganeti-`` commands which are provided
and installed in ``$prefix/sbin`` at install time, there are a couple of
other tools installed which are used seldom but can be helpful in some
cases.

lvmstrap
++++++++

The ``lvmstrap`` tool, introduced in :ref:`configure-lvm-label` section,
has two modes of operation:

- ``diskinfo`` shows the discovered disks on the system and their status
- ``create`` takes all not-in-use disks and creates a volume group out
  of them

.. warning:: The ``create`` argument to this command causes data-loss!

cfgupgrade
++++++++++

The ``cfgupgrade`` tools is used to upgrade between major (and minor)
Ganeti versions, and to roll back. Point-releases are usually
transparent for the admin.

More information about the upgrade procedure is listed on the wiki at
http://code.google.com/p/ganeti/wiki/UpgradeNotes.

There is also a script designed to upgrade from Ganeti 1.2 to 2.0,
called ``cfgupgrade12``.

cfgshell
++++++++

.. note:: This command is not actively maintained; make sure you backup
   your configuration before using it

This can be used as an alternative to direct editing of the
main configuration file if Ganeti has a bug and prevents you, for
example, from removing an instance or a node from the configuration
file.

.. _burnin-label:

burnin
++++++

.. warning:: This command will erase existing instances if given as
   arguments!

This tool is used to exercise either the hardware of machines or
alternatively the Ganeti software. It is safe to run on an existing
cluster **as long as you don't pass it existing instance names**.

The command will, by default, execute a comprehensive set of operations
against a list of instances, these being:

- creation
- disk replacement (for redundant instances)
- failover and migration (for redundant instances)
- move (for non-redundant instances)
- disk growth
- add disks, remove disk
- add NICs, remove NICs
- export and then import
- rename
- reboot
- shutdown/startup
- and finally removal of the test instances

Executing all these operations will test that the hardware performs
well: the creation, disk replace, disk add and disk growth will exercise
the storage and network; the migrate command will test the memory of the
systems. Depending on the passed options, it can also test that the
instance OS definitions are executing properly the rename, import and
export operations.

sanitize-config
+++++++++++++++

This tool takes the Ganeti configuration and outputs a "sanitized"
version, by randomizing or clearing:

- DRBD secrets and cluster public key (always)
- host names (optional)
- IPs (optional)
- OS names (optional)
- LV names (optional, only useful for very old clusters which still have
  instances whose LVs are based on the instance name)

By default, all optional items are activated except the LV name
randomization. When passing ``--no-randomization``, which disables the
optional items (i.e. just the DRBD secrets and cluster public keys are
randomized), the resulting file can be used as a safety copy of the
cluster config - while not trivial, the layout of the cluster can be
recreated from it and if the instance disks have not been lost it
permits recovery from the loss of all master candidates.

move-instance
+++++++++++++

See :doc:`separate documentation for move-instance <move-instance>`.

users-setup
+++++++++++

Ganeti can either be run entirely as root, or with every daemon running as
its own specific user (if the parameters ``--with-user-prefix`` and/or
``--with-group-prefix`` have been specified at ``./configure``-time).

In case split users are activated, they are required to exist on the system,
and they need to belong to the proper groups in order for the access
permissions to files and programs to be correct.

The ``users-setup`` tool, when run, takes care of setting up the proper
users and groups.

When invoked without parameters, the tool runs in interactive mode, showing the
list of actions it will perform and asking for confirmation before proceeding.

Providing the ``--yes-do-it`` parameter to the tool prevents the confirmation
from being asked, and the users and groups will be created immediately.

.. TODO: document cluster-merge tool


Other Ganeti projects
---------------------

Below is a list (which might not be up-to-date) of additional projects
that can be useful in a Ganeti deployment. They can be downloaded from
the project site (http://code.google.com/p/ganeti/) and the repositories
are also on the project git site (http://git.ganeti.org).

NBMA tools
++++++++++

The ``ganeti-nbma`` software is designed to allow instances to live on a
separate, virtual network from the nodes, and in an environment where
nodes are not guaranteed to be able to reach each other via multicasting
or broadcasting. For more information see the README in the source
archive.

ganeti-htools
+++++++++++++

Before Ganeti version 2.5, this was a standalone project; since that
version it is integrated into the Ganeti codebase (see
:doc:`install-quick` for instructions on how to enable it). If you run
an older Ganeti version, you will have to download and build it
separately.

For more information and installation instructions, see the README file
in the source archive.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
