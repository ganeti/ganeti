======================================
Ganeti shared storage support for 2.3+
======================================

This document describes the changes in Ganeti 2.3+ compared to Ganeti
2.3 storage model.

.. contents:: :depth: 4

Objective
=========

The aim is to introduce support for externally mirrored, shared storage.
This includes two distinct disk templates:

- A shared filesystem containing instance disks as regular files
  typically residing on a networked or cluster filesystem (e.g. NFS,
  AFS, Ceph, OCFS2, etc.).
- Instance images being shared block devices, typically LUNs residing on
  a SAN appliance.

Background
==========
DRBD is currently the only shared storage backend supported by Ganeti.
DRBD offers the advantages of high availability while running on
commodity hardware at the cost of high network I/O for block-level
synchronization between hosts. DRBD's master-slave model has greatly
influenced Ganeti's design, primarily by introducing the concept of
primary and secondary nodes and thus defining an instance's “mobility
domain”.

Although DRBD has many advantages, many sites choose to use networked
storage appliances for Virtual Machine hosting, such as SAN and/or NAS,
which provide shared storage without the administrative overhead of DRBD
nor the limitation of a 1:1 master-slave setup. Furthermore, new
distributed filesystems such as Ceph are becoming viable alternatives to
expensive storage appliances. Support for both modes of operation, i.e.
shared block storage and shared file storage backend would make Ganeti a
robust choice for high-availability virtualization clusters.

Throughout this document, the term “externally mirrored storage” will
refer to both modes of shared storage, suggesting that Ganeti does not
need to take care about the mirroring process from one host to another.

Use cases
=========
We consider the following use cases:

- A virtualization cluster with FibreChannel shared storage, mapping at
  least one LUN per instance, accessible by the whole cluster.
- A virtualization cluster with instance images stored as files on an
  NFS server.
- A virtualization cluster storing instance images on a Ceph volume.

Design Overview
===============

The design addresses the following procedures:

- Refactoring of all code referring to constants.DTS_NET_MIRROR.
- Obsolescence of the primary-secondary concept for externally mirrored
  storage.
- Introduction of a shared file storage disk template for use with networked
  filesystems.
- Introduction of shared block device disk template with device
  adoption.

Additionally, mid- to long-term goals include:

- Support for external “storage pools”.
- Introduction of an interface for communicating with external scripts,
  providing methods for the various stages of a block device's and
  instance's life-cycle. In order to provide storage provisioning
  capabilities for various SAN appliances, external helpers in the form
  of a “storage driver” will be possibly introduced as well.

Refactoring of all code referring to constants.DTS_NET_MIRROR
=============================================================

Currently, all storage-related decision-making depends on a number of
frozensets in lib/constants.py, typically constants.DTS_NET_MIRROR.
However, constants.DTS_NET_MIRROR is used to signify two different
attributes:

- A storage device that is shared
- A storage device whose mirroring is supervised by Ganeti

We propose the introduction of two new frozensets to ease
decision-making:

- constants.DTS_EXT_MIRROR, holding externally mirrored disk templates
- constants.DTS_MIRRORED, being a union of constants.DTS_EXT_MIRROR and
  DTS_NET_MIRROR.

Additionally, DTS_NET_MIRROR will be renamed to DTS_INT_MIRROR to reflect
the status of the storage as internally mirrored by Ganeti.

Thus, checks could be grouped into the following categories:

- Mobility checks, like whether an instance failover or migration is
  possible should check against constants.DTS_MIRRORED
- Syncing actions should be performed only for templates in
  constants.DTS_NET_MIRROR

Obsolescence of the primary-secondary node model
================================================

The primary-secondary node concept has primarily evolved through the use
of DRBD. In a globally shared storage framework without need for
external sync (e.g. SAN, NAS, etc.), such a notion does not apply for the
following reasons:

1. Access to the storage does not necessarily imply different roles for
   the nodes (e.g. primary vs secondary).
2. The same storage is available to potentially more than 2 nodes. Thus,
   an instance backed by a SAN LUN for example may actually migrate to
   any of the other nodes and not just a pre-designated failover node.

The proposed solution is using the iallocator framework for run-time
decision making during migration and failover, for nodes with disk
templates in constants.DTS_EXT_MIRROR. Modifications to gnt-instance and
gnt-node will be required to accept target node and/or iallocator
specification for these operations. Modifications of the iallocator
protocol will be required to address at least the following needs:

- Allocation tools must be able to distinguish between internal and
  external storage
- Migration/failover decisions must take into account shared storage
  availability

Introduction of a shared file disk template
===========================================

Basic shared file storage support can be implemented by creating a new
disk template based on the existing FileStorage class, with only minor
modifications in lib/bdev.py. The shared file disk template relies on a
shared filesystem (e.g. NFS, AFS, Ceph, OCFS2 over SAN or DRBD) being
mounted on all nodes under the same path, where instance images will be
saved.

A new cluster initialization option is added to specify the mountpoint
of the shared filesystem.

The remainder of this document deals with shared block storage.

Introduction of a shared block device template
==============================================

Basic shared block device support will be implemented with an additional
disk template. This disk template will not feature any kind of storage
control (provisioning, removal, resizing, etc.), but will instead rely
on the adoption of already-existing block devices (e.g. SAN LUNs, NBD
devices, remote iSCSI targets, etc.).

The shared block device template will make the following assumptions:

- The adopted block device has a consistent name across all nodes,
  enforced e.g. via udev rules.
- The device will be available with the same path under all nodes in the
  node group.

Long-term shared storage goals
==============================
Storage pool handling
---------------------

A new cluster configuration attribute will be introduced, named
“storage_pools”, modeled as a dictionary mapping storage pools to
external storage drivers (see below), e.g.::

 {
  "nas1": "foostore",
  "nas2": "foostore",
  "cloud1": "barcloud",
 }

Ganeti will not interpret the contents of this dictionary, although it
will provide methods for manipulating them under some basic constraints
(pool identifier uniqueness, driver existence). The manipulation of
storage pools will be performed by implementing new options to the
`gnt-cluster` command::

 gnt-cluster modify --add-pool nas1 foostore
 gnt-cluster modify --remove-pool nas1 # There may be no instances using
                                       # the pool to remove it

Furthermore, the storage pools will be used to indicate the availability
of storage pools to different node groups, thus specifying the
instances' “mobility domain”.

New disk templates will also be necessary to facilitate the use of external
storage. The proposed addition is a whole template namespace created by
prefixing the pool names with a fixed string, e.g. “ext:”, forming names
like “ext:nas1”, “ext:foo”.

Interface to the external storage drivers
-----------------------------------------

In addition to external storage pools, a new interface will be
introduced to allow external scripts to provision and manipulate shared
storage.

In order to provide storage provisioning and manipulation (e.g. growing,
renaming) capabilities, each instance's disk template can possibly be
associated with an external “storage driver” which, based on the
instance's configuration and tags, will perform all supported storage
operations using auxiliary means (e.g. XML-RPC, ssh, etc.).

A “storage driver” will have to provide the following methods:

- Create a disk
- Remove a disk
- Rename a disk
- Resize a disk
- Attach a disk to a given node
- Detach a disk from a given node

The proposed storage driver architecture borrows heavily from the OS
interface and follows a one-script-per-function approach. A storage
driver is expected to provide the following scripts:

- `create`
- `resize`
- `rename`
- `remove`
- `attach`
- `detach`

These executables will be called once for each disk with no arguments
and all required information will be passed through environment
variables. The following environment variables will always be present on
each invocation:

- `INSTANCE_NAME`: The instance's name
- `INSTANCE_UUID`: The instance's UUID
- `INSTANCE_TAGS`: The instance's tags
- `DISK_INDEX`: The current disk index.
- `LOGICAL_ID`: The disk's logical id (if existing)
- `POOL`: The storage pool the instance belongs to.

Additional variables may be available in a per-script context (see
below).

Of particular importance is the disk's logical ID, which will act as
glue between Ganeti and the external storage drivers; there are two
possible ways of using a disk's logical ID in a storage driver:

1. Simply use it as a unique identifier (e.g. UUID) and keep a separate,
   external database linking it to the actual storage.
2. Encode all useful storage information in the logical ID and have the
   driver decode it at runtime.

All scripts should return 0 on success and non-zero on error accompanied by
an appropriate error message on stderr. Furthermore, the following
special cases are defined:

1. `create` In case of success, a string representing the disk's logical
   id must be returned on stdout, which will be saved in the instance's
   configuration and can be later used by the other scripts of the same
   storage driver. The logical id may be based on instance name,
   instance uuid and/or disk index.

   Additional environment variables present:
     - `DISK_SIZE`: The requested disk size in MiB

2. `resize` In case of success, output the new disk size.

   Additional environment variables present:
     - `DISK_SIZE`: The requested disk size in MiB

3. `rename` On success, a new logical id should be returned, which will
   replace the old one. This script is meant to rename the instance's
   backing store and update the disk's logical ID in case one of them is
   bound to the instance name.

   Additional environment variables present:
     - `NEW_INSTANCE_NAME`: The instance's new name.


.. vim: set textwidth=72 :
