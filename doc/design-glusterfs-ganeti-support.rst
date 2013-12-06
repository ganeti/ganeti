========================
GlusterFS Ganeti support
========================

This document describes the plan for adding GlusterFS support inside Ganeti.

.. contents:: :depth: 4
.. highlight:: shell-example

Gluster overview
================

Gluster is a "brick" "translation" service that can turn a number of LVM logical
volume or disks (so-called "bricks") into an unified "volume" that can be
mounted over the network through FUSE or NFS.

This is a simplified view of what components are at play and how they
interconnect as data flows from the actual disks to the instances. The parts in
grey are available for Ganeti to use and included for completeness but not
targeted for implementation at this stage.

.. digraph:: "gluster-ganeti-overview"

  graph [ spline=ortho ]
  node [ shape=rect ]

  {

    node [ shape=none ]
    _volume [ label=volume ]

    bricks -> translators -> _volume
    _volume -> network [label=transport]
    network -> instances
  }

  { rank=same; brick1 [ shape=oval ]
               brick2 [ shape=oval ]
               brick3 [ shape=oval ]
               bricks }
  { rank=same; translators distribute }
  { rank=same; volume [ shape=oval ]
               _volume }
  { rank=same; instances instanceA instanceB instanceC instanceD }
  { rank=same; network FUSE NFS QEMUC QEMUD }

  {
    node [ shape=oval ]
    brick1 [ label=brick ]
    brick2 [ label=brick ]
    brick3 [ label=brick ]
  }

  {
    node [ shape=oval ]
    volume
  }

  brick1 -> distribute
  brick2 -> distribute
  brick3 -> distribute -> volume
  volume -> FUSE [ label=<TCP<br/><font color="grey">UDP</font>>
                   color="black:grey" ]

  NFS [ color=grey fontcolor=grey ]
  volume -> NFS [ label="TCP" color=grey fontcolor=grey ]
  NFS -> mountpoint [ color=grey fontcolor=grey ]

  mountpoint [ shape=oval ]

  FUSE -> mountpoint

  instanceA [ label=instances ]
  instanceB [ label=instances ]

  mountpoint -> instanceA
  mountpoint -> instanceB

  mountpoint [ shape=oval ]

  QEMUC [ label=QEMU ]
  QEMUD [ label=QEMU ]

  {
    instanceC [ label=instances ]
    instanceD [ label=instances ]
  }

  volume -> QEMUC [ label=<TCP<br/><font color="grey">UDP</font>>
                    color="black:grey" ]
  volume -> QEMUD [ label=<TCP<br/><font color="grey">UDP</font>>
                    color="black:grey" ]
  QEMUC -> instanceC
  QEMUD -> instanceD

brick:
  The unit of storage in gluster. Typically a drive or LVM logical volume
  formatted using, for example, XFS.

distribute:
  One of the translators in Gluster, it assigns files to bricks based on the
  hash of their full path inside the volume.

volume:
  A filesystem you can mount on multiple machines; all machines see the same
  directory tree and files.

FUSE/NFS:
  Gluster offers two ways to mount volumes: through FUSE or a custom NFS server
  that is incompatible with other NFS servers. FUSE is more compatible with
  other services running on the storage nodes; NFS gives better performance.
  For now, FUSE is a priority.

QEMU:
  QEMU 1.3 has the ability to use Gluster volumes directly in userspace without
  the need for mounting anything. Ganeti still needs kernelspace access at disk
  creation and OS install time.

transport:
  FUSE and QEMU allow you to connect using TCP and UDP, whereas NFS only
  supports TCP. Those protocols are called transports in Gluster. For now, TCP
  is a priority.

It is the administrator's duty to set up the bricks, the translators and thus
the volume as they see fit. Ganeti will take care of connecting the instances to
a given volume.

.. note::

  The gluster mountpoint must be whitelisted by the administrator in
  ``/etc/ganeti/file-storage-paths`` for security reasons in order to allow
  Ganeti to modify the filesystem.

Why not use a ``sharedfile`` disk template?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Gluster volumes `can` be used by Ganeti using the generic shared file disk
template. There is a number of reasons why that is probably not a good idea,
however:

* Shared file, being a generic solution, cannot offer userspace access support.
* Even with userspace support, Ganeti still needs kernelspace access in order to
  create disks and install OSes on them. Ganeti can manage the mounting for you
  so that the Gluster servers only have as many connections as necessary.
* Experiments showed that you can't trust ``mount.glusterfs`` to give useful
  return codes or error messages. Ganeti can work around its oddities so
  administrators don't have to.
* The shared file folder scheme (``../{instance.name}/disk{disk.id}``) does not
  work well with Gluster. The ``distribute`` translator distributes files across
  bricks, but directories need to be replicated on `all` bricks. As a result, if
  we have a dozen hundred instances, that means a dozen hundred folders being
  replicated on all bricks. This does not scale well.
* This frees up the shared file disk template to use a different, unsupported
  replication scheme together with Gluster. (Storage pools are the long term
  solution for this, however.)

So, while gluster `is` a shared file disk template, essentially, Ganeti can
provide better support for it than that.

Implementation strategy
=======================

Working with GlusterFS in kernel space essentially boils down to:

1. Ask FUSE to mount the Gluster volume.
2. Check that the mount succeeded.
3. Use files stored in the volume as instance disks, just like sharedfile does.
4. When the instances are spun down, attempt unmounting the volume. If the
   gluster connection is still required, the mountpoint is allowed to remain.

Since it is not strictly necessary for Gluster to mount the disk if all that's
needed is userspace access, however, it is inappropriate for the Gluster storage
class to inherit from FileStorage. So the implementation should resort to
composition rather than inheritance:

1. Extract the ``FileStorage`` disk-facing logic into a ``FileDeviceHelper``
   class.

 * In order not to further inflate bdev.py, Filestorage should join its helper
   functions in filestorage.py (thus reducing their visibility) and add Gluster
   to its own file, gluster.py. Moving the other classes to their own files
   like it's been done in ``lib/hypervisor/``) is not addressed as part of this
   design.

2. Use the ``FileDeviceHelper`` class to implement a ``GlusterStorage`` class in
   much the same way.
3. Add Gluster as a disk template that behaves like SharedFile in every way.
4. Provide Ganeti knowledge about what a ``GlusterVolume`` is and how to mount,
   unmount and reference them.

 * Before attempting a mount, we should check if the volume is not mounted
   already. Linux allows mounting partitions multiple times, but then you also
   have to unmount them as many times as you mounted them to actually free the
   resources; this also makes the output of commands such as ``mount`` less
   useful.
 * Every time the device could be released (after instance shutdown, OS
   installation scripts or file creation), a single unmount is attempted. If
   the device is still busy (e.g. from other instances, jobs or open
   administrator shells), the failure is ignored.

5. Modify ``GlusterStorage`` and customize the disk template behavior to fit
   Gluster's needs.

Directory structure
~~~~~~~~~~~~~~~~~~~

In order to address the shortcomings of the generic shared file handling of
instance disk directory structure, Gluster uses a different scheme for
determining a disk's logical id and therefore path on the file system.

The naming scheme is::

    /ganeti/{instance.uuid}.{disk.id}

...bringing the actual path on a node's file system to::

    /var/run/ganeti/gluster/ganeti/{instance.uuid}.{disk.id}

This means Ganeti only uses one folder on the Gluster volume (allowing other
uses of the Gluster volume in the meantime) and works better with how Gluster
distributes storage over its bricks.

Changes to the storage types system
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ganeti has a number of storage types that abstract over disk templates. This
matters mainly in terms of disk space reporting. Gluster support is improved by
a rethinking of how disk templates are assigned to storage types in Ganeti.

This is the summary of the changes:

+--------------+---------+---------+-------------------------------------------+
| Disk         | Current | New     | Does it report storage information to...  |
| template     | storage | storage +-------------+----------------+------------+
|              | type    | type    | ``gnt-node  | ``gnt-node     | iallocator |
|              |         |         | list``      | list-storage`` |            |
+==============+=========+=========+=============+================+============+
| File         | File    | File    | Yes.        | Yes.           | Yes.       |
+--------------+---------+---------+-------------+----------------+------------+
| Shared file  | File    | Shared  | No.         | Yes.           | No.        |
+--------------+---------+ file    |             |                |            |
| Gluster (new)| N/A     | (new)   |             |                |            |
+--------------+---------+---------+-------------+----------------+------------+
| RBD (for     | RBD               | No.         | No.            | No.        |
| reference)   |                   |             |                |            |
+--------------+-------------------+-------------+----------------+------------+

Gluster or Shared File should not, like RBD, report storage information to
gnt-node list or to IAllocators. Regrettably, the simplest way to do so right
now is by claiming that storage reporting for the relevant storage type is not
implemented. An effort was made to claim that the shared storage type did support
disk reporting while refusing to provide any value, but it was not successful
(``hail`` does not support this combination.)

To do so without breaking the File disk template, a new storage type must be
added. Like RBD, it does not claim to support disk reporting. However, we can
still make an effort of reporting stats to ``gnt-node list-storage``.

The rationale is simple. For shared file and gluster storage, disk space is not
a function of any one node. If storage types with disk space reporting are used,
Hail expects them to give useful numbers for allocation purposes, but a shared
storage system means disk balancing is not affected by node-instance allocation
any longer. Moreover, it would be wasteful to mount a Gluster volume on each
node just for running statvfs() if no machine was actually running gluster VMs.

As a result, Gluster support for gnt-node list-storage is necessarily limited
and nodes on which Gluster is available but not in use will report failures.
Additionally, running ``gnt-node list`` will give an output like this::

  Node              DTotal DFree MTotal MNode MFree Pinst Sinst
  node1.example.com      ?     ?   744M  273M  477M     0     0
  node2.example.com      ?     ?   744M  273M  477M     0     0

This is expected and consistent with behaviour in RBD.

An alternative would have been to report DTotal and DFree as 0 in order to allow
``hail`` to ignore the disk information, but this incorrectly populates the
``gnt-node list`` DTotal and DFree fields with 0s as well.

New configuration switches
~~~~~~~~~~~~~~~~~~~~~~~~~~

Configurable at the cluster and node group level (``gnt-cluster modify``,
``gnt-group modify`` and other commands that support the `-D` switch to edit
disk parameters):

``gluster:host``
  The IP address or hostname of the Gluster server to connect to. In the default
  deployment of Gluster, that is any machine that is hosting a brick.

  Default: ``"127.0.0.1"``

``gluster:port``
  The port where the Gluster server is listening to.

  Default: ``24007``

``gluster:volume``
  The volume Ganeti should use.

  Default: ``"gv0"``

Configurable at the cluster level only (``gnt-cluster init``) and stored in
ssconf for all nodes to read (just like shared file):

``--gluster-dir``
  Where the Gluster volume should be mounted.

  Default: ``/var/run/ganeti/gluster``

The default values work if all of the Ganeti nodes also host Gluster bricks.
This is possible, but `not` recommended as it can cause the host to hardlock due
to deadlocks in the kernel memory (much in the same way RBD works).

Future work
===========

In no particular order:

* Support the UDP transport.
* Support mounting through NFS.
* Filter ``gnt-node list`` so DTotal and DFree are not shown for RBD and shared
  file disk types, or otherwise report the disk storage values as "-" or some
  other special value to clearly distinguish it from the result of a
  communication failure between nodes.
* Allow configuring the in-volume path Ganeti uses.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
