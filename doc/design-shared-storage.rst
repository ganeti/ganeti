=============================
Ganeti shared storage support
=============================

This document describes the changes in Ganeti 2.3+ compared to Ganeti
2.3 storage model. It also documents the ExtStorage Interface.

.. contents:: :depth: 4
.. highlight:: shell-example

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
- Introduction of a shared block device disk template with device
  adoption.
- Introduction of the External Storage Interface.

Additionally, mid- to long-term goals include:

- Support for external “storage pools”.

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

Introduction of the External Storage Interface
==============================================

Overview
--------

To extend the shared block storage template and give Ganeti the ability
to control and manipulate external storage (provisioning, removal,
growing, etc.) we need a more generic approach. The generic method for
supporting external shared storage in Ganeti will be to have an
ExtStorage provider for each external shared storage hardware type. The
ExtStorage provider will be a set of files (executable scripts and text
files), contained inside a directory which will be named after the
provider. This directory must be present across all nodes of a nodegroup
(Ganeti doesn't replicate it), in order for the provider to be usable by
Ganeti for this nodegroup (valid). The external shared storage hardware
should also be accessible by all nodes of this nodegroup too.

An “ExtStorage provider” will have to provide the following methods:

- Create a disk
- Remove a disk
- Grow a disk
- Attach a disk to a given node
- Detach a disk from a given node
- SetInfo to a disk (add metadata)
- Verify its supported parameters
- Snapshot a disk (optional)
- Open a disk (optional)
- Close a disk (optional)

The proposed ExtStorage interface borrows heavily from the OS
interface and follows a one-script-per-function approach. An ExtStorage
provider is expected to provide the following scripts:

- ``create``
- ``remove``
- ``grow``
- ``attach``
- ``detach``
- ``setinfo``
- ``verify``
- ``snapshot`` (optional)
- ``open`` (optional)
- ``close`` (optional)

All scripts will be called with no arguments and get their input via
environment variables. A common set of variables will be exported for
all commands, and some commands might have extra variables.

``VOL_NAME``
  The name of the volume. This is unique for Ganeti and it
  uses it to refer to a specific volume inside the external storage.
``VOL_SIZE``
  The volume's size in mebibytes.
  Available only to the `create` and `grow` scripts.
``VOL_NEW_SIZE``
  Available only to the `grow` script. It declares the
  new size of the volume after grow (in mebibytes).
``EXTP_name``
  ExtStorage parameter, where `name` is the parameter in
  upper-case (same as OS interface's ``OSP_*`` parameters).
``VOL_METADATA``
  A string containing metadata to be set for the volume.
  This is exported only to the ``setinfo`` script.
``VOL_CNAME``
  The human readable name of the disk (if any).
``VOL_SNAPSHOT_NAME``
  The name of the volume's snapshot.
  Available only to the `snapshot` script.
``VOL_SNAPSHOT_SIZE``
  The size of the volume's snapshot.
  Available only to the `snapshot` script.
``VOL_OPEN_EXCLUSIVE``
  Whether the volume will be accessed exclusively or not.
  Available only to the `open` script.

All scripts except `attach` should return 0 on success and non-zero on
error, accompanied by an appropriate error message on stderr. The
`attach` script should return a string on stdout on success, which is
the block device's full path, after it has been successfully attached to
the host node. On error it should return non-zero.

The ``snapshot``, ``open`` and ``close`` scripts are introduced after
the first implementation of the ExtStorage Interface. To keep backwards
compatibility with the first implementation, we make these scripts
optional.

The ``snapshot`` script, if present, will be used for instance backup
export. The ``open`` script makes the device ready for I/O. The ``close``
script disables the I/O on the device.

Implementation
--------------

To support the ExtStorage interface, we will introduce a new disk
template called `ext`. This template will implement the existing Ganeti
disk interface in `lib/bdev.py` (create, remove, attach, assemble,
shutdown, grow, setinfo, open, close),
and will simultaneously pass control to the
external scripts to actually handle the above actions. The `ext` disk
template will act as a translation layer between the current Ganeti disk
interface and the ExtStorage providers.

We will also introduce a new IDISK_PARAM called `IDISK_PROVIDER =
provider`, which will be used at the command line to select the desired
ExtStorage provider. This parameter will be valid only for template
`ext` e.g.::

  $ gnt-instance add -t ext --disk=0:size=2G,provider=sample_provider1

The Extstorage interface will support different disks to be created by
different providers. e.g.::

  $ gnt-instance add -t ext --disk=0:size=2G,provider=sample_provider1 \
                            --disk=1:size=1G,provider=sample_provider2 \
                            --disk=2:size=3G,provider=sample_provider1

Finally, the ExtStorage interface will support passing of parameters to
the ExtStorage provider. This will also be done per disk, from the
command line::

 $ gnt-instance add -t ext --disk=0:size=1G,provider=sample_provider1,\
                                            param1=value1,param2=value2

The above parameters will be exported to the ExtStorage provider's
scripts as the enviromental variables:

- `EXTP_PARAM1 = str(value1)`
- `EXTP_PARAM2 = str(value2)`

We will also introduce a new Ganeti client called `gnt-storage` which
will be used to diagnose ExtStorage providers and show information about
them, similarly to the way  `gnt-os diagose` and `gnt-os info` handle OS
definitions.

ExtStorage Interface support for userspace access
=================================================

Overview
--------

The ExtStorage Interface gets extended to cater for ExtStorage providers
that support userspace access. This will allow the instances to access
their external storage devices directly without going through a block
device, avoiding expensive context switches with kernel space and the
potential for deadlocks in low memory scenarios. The implementation
should be backwards compatible and allow existing ExtStorage
providers to work as is.

Implementation
--------------

Since the implementation should be backwards compatible we are not going
to add a new script in the set of scripts an ExtStorage provider should
ship with. Instead, the 'attach' script, which is currently responsible
to map the block device and return a valid device path, should also be
responsible for providing the URIs that will be used by each
hypervisor. Even though Ganeti currently allows userspace access only
for the KVM hypervisor, we want the implementation to enable the
extstorage providers to support more than one hypervisors for future
compliance.

More specifically, the 'attach' script will be allowed to return more
than one line. The first line will contain as always the block device
path. Each one of the extra lines will contain a URI to be used for the
userspace access by a specific hypervisor. Each URI should be prefixed
with the hypervisor it corresponds to (e.g. kvm:<uri>). The prefix will
be case insensitive. If the 'attach' script doesn't return any extra
lines, we assume that the ExtStorage provider doesn't support userspace
access (this way we maintain backward compatibility with the existing
'attach' scripts). In case the provider supports *only* userspace
access and thus a local block device is not available, then the first
line should be an empty line.

The 'GetUserspaceAccessUri' method of the 'ExtStorageDevice' class will
parse the output of the 'attach' script and if the provider supports
userspace access for the requested hypervisor, it will use the
corresponding URI instead of the block device itself.

Long-term shared storage goals
==============================

Storage pool handling
---------------------

A new cluster configuration attribute will be introduced, named
“storage_pools”, modeled as a dictionary mapping storage pools to
external storage providers (see below), e.g.::

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

 $ gnt-cluster modify --add-pool nas1 foostore
 $ gnt-cluster modify --remove-pool nas1 # There must be no instances using
                                         # the pool to remove it

Furthermore, the storage pools will be used to indicate the availability
of storage pools to different node groups, thus specifying the
instances' “mobility domain”.

The pool, in which to put the new instance's disk, will be defined at
the command line during `instance add`. This will become possible by
replacing the IDISK_PROVIDER parameter with a new one, called `IDISK_POOL
= pool`. The cmdlib logic will then look at the cluster-level mapping
dictionary to determine the ExtStorage provider for the given pool.

gnt-storage
-----------

The ``gnt-storage`` client can be extended to support pool management
(creation/modification/deletion of pools, connection/disconnection of
pools to nodegroups, etc.). It can also be extended to diagnose and
provide information for internal disk templates too, such as lvm and
drbd.

.. vim: set textwidth=72 :
