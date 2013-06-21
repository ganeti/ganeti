========================
GlusterFS Ganeti support
========================

This document describes the plan for adding GlusterFS support inside Ganeti.

.. contents:: :depth: 4
.. highlight:: shell-example

Objective
=========

The aim is to let Ganeti support GlusterFS as one of its backend storage.
This includes three aspects to finish:

- Add Gluster as a storage backend.
- Make sure Ganeti VMs can use GlusterFS backends in userspace mode (for
  newer QEMU/KVM which has this support) and otherwise, if possible, through
  some kernel exported block device.
- Make sure Ganeti can configure GlusterFS by itself, by just joining
  storage space on new nodes to a GlusterFS nodes pool. Note that this
  may need another design document that explains how it interacts with
  storage pools, and that the node might or might not host VMs as well.

Background
==========

There are two possible ways to implement "GlusterFS Ganeti Support". One is
GlusterFS as one of external backend storage, the other one is realizing
GlusterFS inside Ganeti, that is, as a new disk type for Ganeti. The benefit
of the latter one is that it would not be opaque but fully supported and
integrated in Ganeti, which would not need to add infrastructures for
testing/QAing and such. Having it internal we can also provide a monitoring
agent for it and more visibility into what's going on. For these reasons,
GlusterFS support will be added directly inside Ganeti.

Implementation Plan
===================

Ganeti Side
-----------

To realize an internal storage backend for Ganeti, one should realize
BlockDev class in `ganeti/lib/storage/base.py` that is a specific
class including create, remove and such. These functions should be
realized in `ganeti/lib/storage/bdev.py`. Actually, the differences
between implementing inside and outside (external) Ganeti are how to
finish these functions in BlockDev class and how to combine with Ganeti
itself. The internal implementation is not based on external scripts
and combines with Ganeti in a more compact way. RBD patches may be a
good reference here. Adding a backend storage steps are as follows:

- Implement the BlockDev interface in bdev.py.
- Add the logic in cmdlib (eg, migration, verify).
- Add the new storage type name to constants.
- Modify objects.Disk to support GlusterFS storage type.
- The implementation will be performed similarly to the RBD one (see
  commit 7181fba).

GlusterFS side
--------------

GlusterFS is a distributed file system implemented in user space.
The way to access GlusterFS namespace is via FUSE based Gluster native
client except NFS and CIFS. The efficiency of this way is lower because
the data would be pass the kernel space and then come to user space.
Now, there are two specific enhancements:

- A new library called libgfapi is now available as part of GlusterFS
  that provides POSIX-like C APIs for accessing Gluster volumes.
  libgfapi support will be available from GlusterFS-3.4 release.
- QEMU/KVM (starting from QEMU-1.3) will have GlusterFS block driver that
  uses libgfapi and hence there is no FUSE overhead any longer when QEMU/KVM
  works with VM images on Gluster volumes.

There are two possible ways to implement "GlusterFS Ganeti Support" inside
Ganeti. One is based on libgfapi, which call APIs by libgfapi to realize
GlusterFS interfaces in bdev.py. The other way is based on QEMU/KVM. Since
QEMU/KVM has supported for GlusterFS and Ganeti could support for GlusterFS
by QEMU/KVM. However, the latter way can just let VMs of QEMU/KVM use GlusterFS
backend storage but other VMs like XEN and such. So the first way is more
suitable for us.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
