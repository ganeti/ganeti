Ganeti administrator's guide
============================

Documents Ganeti version |version|

.. contents::

Introduction
------------

Ganeti is a virtualization cluster management software. You are
expected to be a system administrator familiar with your Linux
distribution and the Xen or KVM virtualization environments before
using it.


The various components of Ganeti all have man pages and interactive
help. This manual though will help you getting familiar with the
system by explaining the most common operations, grouped by related
use.

After a terminology glossary and a section on the prerequisites needed
to use this manual, the rest of this document is divided in three main
sections, which group different features of Ganeti:

- Instance Management
- High Availability Features
- Debugging Features

Ganeti terminology
~~~~~~~~~~~~~~~~~~

This section provides a small introduction to Ganeti terminology,
which might be useful to read the rest of the document.

Cluster
  A set of machines (nodes) that cooperate to offer a coherent
  highly available virtualization service.

Node
  A physical machine which is member of a cluster.
  Nodes are the basic cluster infrastructure, and are
  not fault tolerant.

Master node
  The node which controls the Cluster, from which all
  Ganeti commands must be given.

Instance
  A virtual machine which runs on a cluster. It can be a
  fault tolerant highly available entity.

Pool
  A pool is a set of clusters sharing the same network.

Meta-Cluster
  Anything that concerns more than one cluster.

Prerequisites
~~~~~~~~~~~~~

You need to have your Ganeti cluster installed and configured before
you try any of the commands in this document. Please follow the
*Ganeti installation tutorial* for instructions on how to do that.

Managing Instances
------------------

Adding/Removing an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adding a new virtual instance to your Ganeti cluster is really easy.
The command is::

  gnt-instance add \
    -n TARGET_NODE:SECONDARY_NODE -o OS_TYPE -t DISK_TEMPLATE \
    INSTANCE_NAME

The instance name must be resolvable (e.g. exist in DNS) and usually
to an address in the same subnet as the cluster itself. Options you
can give to this command include:

- The disk size (``-s``) for a single-disk instance, or multiple
  ``--disk N:size=SIZE`` options for multi-instance disks

- The memory size (``-B memory``)

- The number of virtual CPUs (``-B vcpus``)

- Arguments for the NICs of the instance; by default, a single-NIC
  instance is created. The IP and/or bridge of the NIC can be changed
  via ``--nic 0:ip=IP,bridge=BRIDGE``


There are four types of disk template you can choose from:

diskless
  The instance has no disks. Only used for special purpouse operating
  systems or for testing.

file
  The instance will use plain files as backend for its disks. No
  redundancy is provided, and this is somewhat more difficult to
  configure for high performance.

plain
  The instance will use LVM devices as backend for its disks. No
  redundancy is provided.

drbd
  .. note:: This is only valid for multi-node clusters using DRBD 8.0.x

  A mirror is set between the local node and a remote one, which must
  be specified with the second value of the --node option. Use this
  option to obtain a highly available instance that can be failed over
  to a remote node should the primary one fail.

For example if you want to create an highly available instance use the
drbd disk templates::

  gnt-instance add -n TARGET_NODE:SECONDARY_NODE -o OS_TYPE -t drbd \
    INSTANCE_NAME

To know which operating systems your cluster supports you can use
the command::

  gnt-os list

Removing an instance is even easier than creating one. This operation
is irrereversible and destroys all the contents of your instance. Use
with care::

  gnt-instance remove INSTANCE_NAME

Starting/Stopping an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Instances are automatically started at instance creation time. To
manually start one which is currently stopped you can run::

  gnt-instance startup INSTANCE_NAME

While the command to stop one is::

  gnt-instance shutdown INSTANCE_NAME

The command to see all the instances configured and their status is::

  gnt-instance list

Do not use the Xen commands to stop instances. If you run for example
xm shutdown or xm destroy on an instance Ganeti will automatically
restart it (via the ``ganeti-watcher``).

Exporting/Importing an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can create a snapshot of an instance disk and Ganeti
configuration, which then you can backup, or import into another
cluster. The way to export an instance is::

  gnt-backup export -n TARGET_NODE INSTANCE_NAME

The target node can be any node in the cluster with enough space under
``/srv/ganeti`` to hold the instance image. Use the *--noshutdown*
option to snapshot an instance without rebooting it. Any previous
snapshot of the same instance existing cluster-wide under
``/srv/ganeti`` will be removed by this operation: if you want to keep
them move them out of the Ganeti exports directory.

Importing an instance is similar to creating a new one. The command is::

  gnt-backup import -n TARGET_NODE -t DISK_TEMPLATE \
    --src-node=NODE --src-dir=DIR INSTANCE_NAME

Most of the options available for the command :command:`gnt-instance
add` are supported here too.

High availability features
--------------------------

.. note:: This section only applies to multi-node clusters

Failing over an instance
~~~~~~~~~~~~~~~~~~~~~~~~

If an instance is built in highly available mode you can at any time
fail it over to its secondary node, even if the primary has somehow
failed and it's not up anymore. Doing it is really easy, on the master
node you can just run::

  gnt-instance failover INSTANCE_NAME

That's it. After the command completes the secondary node is now the
primary, and vice versa.

Live migrating an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~

If an instance is built in highly available mode, it currently runs
and both its nodes are running fine, you can at migrate it over to its
secondary node, without dowtime. On the master node you need to run::

  gnt-instance migrate INSTANCE_NAME

Replacing an instance disks
~~~~~~~~~~~~~~~~~~~~~~~~~~~

So what if instead the secondary node for an instance has failed, or
you plan to remove a node from your cluster, and you failed over all
its instances, but it's still secondary for some? The solution here is
to replace the instance disks, changing the secondary node::

  gnt-instance replace-disks -n NODE INSTANCE_NAME

This process is a bit long, but involves no instance downtime, and at
the end of it the instance has changed its secondary node, to which it
can if necessary be failed over.

Failing over the master node
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is all good as long as the Ganeti Master Node is up. Should it go
down, or should you wish to decommission it, just run on any other
node the command::

  gnt-cluster masterfailover

and the node you ran it on is now the new master.

Adding/Removing nodes
~~~~~~~~~~~~~~~~~~~~~

And of course, now that you know how to move instances around, it's
easy to free up a node, and then you can remove it from the cluster::

  gnt-node remove NODE_NAME

and maybe add a new one::

  gnt-node add --secondary-ip=ADDRESS NODE_NAME

Debugging Features
------------------

At some point you might need to do some debugging operations on your
cluster or on your instances. This section will help you with the most
used debugging functionalities.

Accessing an instance's disks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

From an instance's primary node you have access to its disks. Never
ever mount the underlying logical volume manually on a fault tolerant
instance, or you risk breaking replication. The correct way to access
them is to run the command::

  gnt-instance activate-disks INSTANCE_NAME

And then access the device that gets created.  After you've finished
you can deactivate them with the deactivate-disks command, which works
in the same way.

Accessing an instance's console
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The command to access a running instance's console is::

  gnt-instance console INSTANCE_NAME

Use the console normally and then type ``^]`` when
done, to exit.

Instance OS definitions Debugging
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Should you have any problems with operating systems support the
command to ran to see a complete status for all your nodes is::

   gnt-os diagnose

Cluster-wide debugging
~~~~~~~~~~~~~~~~~~~~~~

The :command:`gnt-cluster` command offers several options to run tests
or execute cluster-wide operations. For example::

  gnt-cluster command
  gnt-cluster copyfile
  gnt-cluster verify
  gnt-cluster verify-disks
  gnt-cluster getmaster
  gnt-cluster version

See the man page :manpage:`gnt-cluster` to know more about their usage.

Removing a cluster entirely
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The usual method to cleanup a cluster is to run ``gnt-cluster
destroy`` however if the Ganeti installation is broken in any way then
this will not run.

It is possible in such a case to cleanup manually most if not all
traces of a cluster installation by following these steps on all of
the nodes:

1. Shutdown all instances. This depends on the virtualisation
   method used (Xen, KVM, etc.):

  - Xen: run ``xm list`` and ``xm destroy`` on all the non-Domain-0
    instances
  - KVM: kill all the KVM processes
  - chroot: kill all processes under the chroot mountpoints

2. If using DRBD, shutdown all DRBD minors (which should by at this
   time no-longer in use by instances); on each node, run ``drbdsetup
   /dev/drbdN down`` for each active DRBD minor.

3. If using LVM, cleanup the Ganeti volume group; if only Ganeti
   created logical volumes (and you are not sharing the volume group
   with the OS, for example), then simply running ``lvremove -f
   xenvg`` (replace 'xenvg' with your volume group name) should do the
   required cleanup.

4. If using file-based storage, remove recursively all files and
   directories under your file-storage directory: ``rm -rf
   /srv/ganeti/file-storage/*`` replacing the path with the correct
   path for your cluster.

5. Stop the ganeti daemons (``/etc/init.d/ganeti stop``) and kill any
   that remain alive (``pgrep ganeti`` and ``pkill ganeti``).

6. Remove the ganeti state directory (``rm -rf /var/lib/ganeti/*``),
   replacing the path with the correct path for your installation.

On the master node, remove the cluster from the master-netdev (usually
``xen-br0`` for bridged mode, otherwise ``eth0`` or similar), by
running ``ip a del $clusterip/32 dev xen-br0`` (use the correct
cluster ip and network device name).

At this point, the machines are ready for a cluster creation; in case
you want to remove Ganeti completely, you need to also undo some of
the SSH changes and log directories:

- ``rm -rf /var/log/ganeti /srv/ganeti`` (replace with the correct paths)
- remove from ``/root/.ssh`` the keys that Ganeti added (check
  the ``authorized_keys`` and ``id_dsa`` files)
- regenerate the host's SSH keys (check the OpenSSH startup scripts)
- uninstall Ganeti

Otherwise, if you plan to re-create the cluster, you can just go ahead
and rerun ``gnt-cluster init``.
