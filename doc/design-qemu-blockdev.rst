======================================
Implementing the qemu blockdev backend
======================================

:Created: 2022-Apr-20
:Status: Implemented
:Ganeti-Version: 3.1

.. contents:: :depth: 2

This is a design document explaining the changes inside Ganeti while
transitioning to the blockdev backend of QEMU, making the currently used
`-drive` parameter obsolete.


Current state and shortcomings
==============================

Ganeti's KVM/QEMU code currently uses the `-drive` commandline parameter to add
virtual hard-disks, floppy or CD drives to instances. This approach has been
deprecated and superseded by the newer `-blockdev` parameter which has been
considered stable with the 2.9 release of QEMU.

Furthermore, the use of `-drive` blocks the transition from QEMU's human
monitor to QMP, as the latter has never seen an implementation of the relevant
methods to hot-add/hot-remove storage devices configured through `-drive`.

Currently, Ganeti QEMU/KVM instances support the following storage devices:

``Virtual Hard-disks``
  An instance can have none to many disks which are represented to guests as the
  selected `disk_type`. Ganeti supports various device types like `paravirtual`
  (VirtIO), `scsi-hd` (along with an emulated SCSI controller), `ide` and the
  like. The disk type can only be set per instance, not per disk.

  A disk's backing storage may be file- or block-based, depending on the
  available disk templates on the node.

  Disks can be hot-added to or hot-removed from running instances.

  An instance may boot off the first disk when not using direct kernel boot,
  specified through the `boot_order` parameter.

  Ganeti allows tweaking of various disk related parameters like AIO modes,
  caching, discard settings etc.
  Recent versions of QEMU (5.0+) have introduced the `io_uring` AIO mode which
  is currently not configurable through Ganeti.

``Virtual CD Drives``
  Ganeti allows for up to two virtual CD drives to be attached to an instance.
  The backing storage to a CD drive must be an ISO image, which needs to be
  either a file accessible locally on the node or remotely through a HTTP(S)
  URL. Different bus types (e.g. `ide`, `scsi`, or `paravirtual`) are supported.

  CD drives can not be hot-added to or hot-removed from running instances.

  Instances not using direct kernel boot may boot from the first CD drive, when
  specified through the `boot_order` parameter. If the `boot_order` is set to
  CD, the bus type will silently be overridden to `ide`.

``Virtual Floppy Drive``
  An instance can be configured to provide access to a virtual floppy drive
  using an image file present on the node.

  Floppy drives can not be hot-added to or hot-removed from running instances.

  Instances not using direct kernel boot may boot from the floppy drive, when
  specified through the `boot_order` parameter.


Proposed changes
================

We have to eliminate all uses of the `-drive` parameter from the Ganeti codebase
to ensure compatibility with future versions of QEMU. With this, we can also
switch all hotplugging-related methods to use QMP and drop all code relating to
the human monitor interface.

Ganeti should support the AIO mode `io_uring` as long as the QEMU version on
the node is recent enough.

Implementation
==============

I/O Methods
+++++++++++

With QEMU 5.0, support for `io_uring` has been introduced. This should be
supported by Ganeti as well, given a recent enough QEMU version is present on
the node. Ganeti will still default to using the `threads` mode on new
installations.

Disk Cache
++++++++++

Using the following table found in `man 1 qemu-system-x86_64` we can translate
the disk cache modes known to Ganeti into the settings required by `-blockdev`:

  .. code-block:: none

    ┌─────────────┬─────────────────┬──────────────┬────────────────┐
    │             │ cache.writeback │ cache.direct │ cache.no-flush │
    ├─────────────┼─────────────────┼──────────────┼────────────────┤
    │writeback    │ on              │ off          │ off            │
    ├─────────────┼─────────────────┼──────────────┼────────────────┤
    │none         │ on              │ on           │ off            │
    ├─────────────┼─────────────────┼──────────────┼────────────────┤
    │writethrough │ off             │ off          │ off            │
    ├─────────────┼─────────────────┼──────────────┼────────────────┤
    │directsync   │ off             │ on           │ off            │
    ├─────────────┼─────────────────┼──────────────┼────────────────┤
    │unsafe       │ on              │ off          │ on             │
    └─────────────┴─────────────────┴──────────────┴────────────────┘

The table also shows `directsync` and `unsafe`, which are currently not
implemented by Ganeti and may be addressed in future changes. The Ganeti value
of `default` should internally be mapped to `writeback`, as that reflects the
values which QEMU assumes when not given explicitly according to the
documentation.

Construction of the command line parameters
+++++++++++++++++++++++++++++++++++++++++++

The code responsible for generating the commandline parameters to add disks,
cdroms and floppies needs to be changed to use the combination of `-blockdev`
and `-device`. This will not change they way a disk is actually presented to
the virtual guest.
A small exception will be cdrom: Ganeti used to overwrite the cdrom disk type to
`ide` when `boot_order` is set to `cdrom`. This is not required any more - QEMU
will also boot off VirtIO or SCSI CD drives.

Hot-Adding Disks
++++++++++++++++++

The code needs to be refactored to make use of the QMP method "blockdev-add",
using the same parameters as for its commandline counterpart (e.g. blockdev node
id, caching, aio-mode).

Hot-Removing Disks
++++++++++++++++++

Hot-removing a disk consists of two steps:

- removing the virtual device (or rather: ask the guest to release it)
- releasing the storage backend

The first step always returns immediately (QMP request `device_del`) but signals
its `actual` result asynchronously through the QMP event `DEVICE_DELETED`.
Ganeti currently does not support receiving QMP events - implementing this will
be out of scope for this change.

In Ganeti releases up to 3.0 the human monitor was used to delete the device.
Executing commands through that interface was very slow (500ms to 1s) and
seemingly slow enough to let the following request to remove the drive succeed
as the guest had enough time to actually release the device.
With the switch to QMP, both requests will fire in direct succession. Since QEMU
cannot release a block device (`blockdev-del` through QMP) which is still in use
by a device inside the guest, hot-removing disks will always fail.

Without support for QMP events, the only feasible way will be to mimic the slow
human monitor interface and block for one second after sending the `device_del`
request to the guest.

On upgraded clusters it will **not** be possible to hot-remove a disk before the
instance has been either restarted or live-migrated (thus "upgrading" all disk
related parameters to `-blockdev`). Disks added with `-drive` can not be removed
using `blockdev-dev`.



.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
