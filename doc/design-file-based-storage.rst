==================
File-based Storage
==================

This page describes the proposed file-based storage for the 2.0 version
of Ganeti. The project consists in extending Ganeti in order to support
a filesystem image as Virtual Block Device (VBD) in Dom0 as the primary
storage for a VM.

Objective
=========

Goals:

* file-based storage for virtual machines running in a Xen-based
  Ganeti cluster

* failover of file-based virtual machines between cluster-nodes

* export/import file-based virtual machines

* reuse existing image files

* allow Ganeti to initialize the cluster without checking for a volume
  group (e.g. xenvg)

Non Goals:

* any kind of data mirroring between clusters for file-based instances
  (this should be achieved by using shared storage)

* special support for live-migration

* encryption of VBDs

* compression of VBDs

Background
==========

Ganeti is a virtual server management software tool built on top of Xen
VM monitor and other Open Source software.

Since Ganeti currently supports only block devices as storage backend
for virtual machines, the wish came up to provide a file-based backend.
Using this file-based option provides the possibility to store the VBDs
on basically every filesystem and therefore allows to deploy external
data storages (e.g. SAN, NAS, etc.) in clusters.

Overview
========

Introduction
++++++++++++

Xen (and other hypervisors) provide(s) the possibility to use a file as
the primary storage for a VM. One file represents one VBD.

Advantages/Disadvantages
++++++++++++++++++++++++

Advantages of file-backed VBD:

* support of sparse allocation

* easy from a management/backup point of view (e.g. you can just copy
  the files around)

* external storage (e.g. SAN, NAS) can be used to store VMs

Disadvantages of file-backed VBD:
* possible performance loss for I/O-intensive workloads

* using sparse files requires care to ensure the sparseness is
  preserved when copying, and there is no header in which metadata
  relating back to the VM can be stored

Xen-related specifications
++++++++++++++++++++++++++

Driver
~~~~~~

There are several ways to realize the required functionality with an
underlying Xen hypervisor.

1) loopback driver
^^^^^^^^^^^^^^^^^^

Advantages:
* available in most precompiled kernels
* stable, since it is in kernel tree for a long time
* easy to set up

Disadvantages:

* buffer writes very aggressively, which can affect guest filesystem
  correctness in the event of a host crash

* can even cause out-of-memory kernel crashes in Dom0 under heavy
  write load

* substantial slowdowns under heavy I/O workloads

* the default number of supported loopdevices is only 8

* doesn't support QCOW files

``blktap`` driver
^^^^^^^^^^^^^^^^^

Advantages:

* higher performance than loopback driver

* more scalable

* better safety properties for VBD data

* Xen-team strongly encourages use

* already in Xen tree

* supports QCOW files

* asynchronous driver (i.e. high performance)

Disadvantages:

* not enabled in most precompiled kernels

* stable, but not as much tested as loopback driver

3) ubklback driver
^^^^^^^^^^^^^^^^^^

The Xen Roadmap states "Work is well under way to implement a
``ublkback`` driver that supports all of the various qemu file format
plugins".

Furthermore, the Roadmap includes the following:

  "... A special high-performance qcow plugin is also under
  development, that supports better metadata caching, asynchronous IO,
  and allows request reordering with appropriate safety barriers to
  enforce correctness. It remains both forward and backward compatible
  with existing qcow disk images, but makes adjustments to qemu's
  default allocation policy when creating new disks such as to
  optimize performance."

File types
~~~~~~~~~~

Raw disk image file
^^^^^^^^^^^^^^^^^^^

Advantages:
* Resizing supported
* Sparse file (filesystem dependend)
* simple and easily exportable

Disadvantages:

* Underlying filesystem needs to support sparse files (most
  filesystems do, though)

QCOW disk image file
^^^^^^^^^^^^^^^^^^^^

Advantages:

* Smaller file size, even on filesystems which don't support holes
  (i.e. sparse files)

* Snapshot support, where the image only represents changes made to an
  underlying disk image

* Optional zlib based compression

* Optional AES encryption

Disadvantages:
* Resizing not supported yet (it's on the way)

VMDK disk image file
^^^^^^^^^^^^^^^^^^^^

This file format is directly based on the qemu vmdk driver, which is
synchronous and thus slow.

Detailed Design
===============

Terminology
+++++++++++

* **VBD** (Virtual Block Device): Persistent storage available to a
  virtual machine, providing the abstraction of an actual block
  storage device. VBDs may be actual block devices, filesystem images,
  or remote/network storage.

* **Dom0** (Domain 0): The first domain to be started on a Xen
  machine.  Domain 0 is responsible for managing the system.

* **VM** (Virtual Machine): The environment in which a hosted
  operating system runs, providing the abstraction of a dedicated
  machine. A VM may be identical to the underlying hardware (as in
  full virtualization, or it may differ, as in paravirtualization). In
  the case of Xen the domU (unprivileged domain) instance is meant.

* **QCOW**: QEMU (a processor emulator) image format.


Implementation
++++++++++++++

Managing file-based instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The option for file-based storage will be added to the 'gnt-instance'
utility.

Add Instance
^^^^^^^^^^^^

Example:

  gnt-instance add -t file:[path\ =[,driver=loop[,reuse[,...]]]] \
  --disk 0:size=5G --disk 1:size=10G -n node -o debian-etch instance2

This will create a file-based instance with e.g. the following files:
* ``/sda`` -> 5GB
* ``/sdb`` -> 10GB

The default directory where files will be stored is
``/srv/ganeti/file-storage/``. This can be changed by setting the
``<path>`` option. This option denotes the full path to the directory
where the files are stored. The filetype will be "raw" for the first
release of Ganeti 2.0. However, the code will be extensible to more
file types, since Ganeti will store information about the file type of
each image file. Internally Ganeti will keep track of the used driver,
the file-type and the full path to the file for every VBD. Example:
"logical_id" : ``[FD_LOOP, FT_RAW, "/instance1/sda"]`` If the
``--reuse`` flag is set, Ganeti checks for existing files in the
corresponding directory (e.g. ``/xen/instance2/``). If one or more
files in this directory are present and correctly named (the naming
conventions will be defined in Ganeti version 2.0) Ganeti will set a
VM up with these. If no file can be found or the names or invalid the
operation will be aborted.

Remove instance
^^^^^^^^^^^^^^^

The instance removal will just differ from the actual one by deleting
the VBD-files instead of the corresponding block device (e.g. a logical
volume).

Starting/Stopping Instance
^^^^^^^^^^^^^^^^^^^^^^^^^^

Here nothing has to be changed, as the xen tools don't differentiate
between file-based or blockdevice-based instances in this case.

Export/Import instance
^^^^^^^^^^^^^^^^^^^^^^

Provided "dump/restore" is used in the "export" and "import" guest-os
scripts, there are no modifications needed when file-based instances are
exported/imported. If any other backup-tool (which requires access to
the mounted file-system) is used then the image file can be temporarily
mounted. This can be done in different ways:

Mount a raw image file via loopback driver::

  mount -o loop /srv/ganeti/file-storage/instance1/sda1 /mnt/disk\

Mount a raw image file via blkfront driver (Dom0 kernel needs this
module to do the following operation)::

  xm block-attach 0 tap:aio:/srv/ganeti/file-storage/instance1/sda1 /dev/xvda1 w 0\

  mount /dev/xvda1 /mnt/disk

Mount a qcow image file via blkfront driver (Dom0 kernel needs this
module to do the following operation)

  xm block-attach 0 tap:qcow:/srv/ganeti/file-storage/instance1/sda1 /dev/xvda1 w 0

  mount /dev/xvda1 /mnt/disk

High availability features with file-based instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Failing over an instance
^^^^^^^^^^^^^^^^^^^^^^^^

Failover is done in the same way as with block device backends. The
instance gets stopped on the primary node and started on the secondary.
The roles of primary and secondary get swapped. Note: If a failover is
done, Ganeti will assume that the corresponding VBD(s) location (i.e.
directory) is the same on the source and destination node. In case one
or more corresponding file(s) are not present on the destination node,
Ganeti will abort the operation.

Replacing an instance disks
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Since there is no data mirroring for file-backed VM there is no such
operation.

Evacuation of a node
^^^^^^^^^^^^^^^^^^^^

Since there is no data mirroring for file-backed VMs there is no such
operation.

Live migration
^^^^^^^^^^^^^^

Live migration is possible using file-backed VBDs. However, the
administrator has to make sure that the corresponding files are exactly
the same on the source and destination node.

Xen Setup
+++++++++

File creation
~~~~~~~~~~~~~

Creation of a raw file is simple. Example of creating a sparse file of 2
Gigabytes. The option "seek" instructs "dd" to create a sparse file::

  dd if=/dev/zero of=vm1disk bs=1k seek=2048k count=1

Creation of QCOW image files can be done with the "qemu-img" utility (in
debian it comes with the "qemu" package).

Config file
~~~~~~~~~~~

The Xen config file will have the following modification if one chooses
the file-based disk-template.

1) loopback driver and raw file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

::

  disk = ['file:</path/to/file>,sda1,w']

2) blktap driver and raw file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

::

  disk = ['tap:aio:,sda1,w']

3) blktap driver and qcow file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

::

  disk = ['tap:qcow:,sda1,w']

Other hypervisors
+++++++++++++++++

Other hypervisors have mostly differnet ways to make storage available
to their virtual instances/machines. This is beyond the scope of this
document.
