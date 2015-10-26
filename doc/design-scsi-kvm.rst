==========
KVM + SCSI
==========

.. contents:: :depth: 4

This is a design document detailing the refactoring of device
handling in the KVM Hypervisor. More specifically, it will use
the latest QEMU device model and modify the hotplug implementation
so that both PCI and SCSI devices can be managed.


Current state and shortcomings
==============================

Ganeti currently supports SCSI virtual devices in the KVM hypervisor by
setting the `disk_type` hvparam to `scsi`. Ganeti will eventually
instruct QEMU to use the deprecated device model (i.e. -drive if=scsi),
which will expose the backing store as an emulated SCSI device. This
means that currently SCSI pass-through is not supported.

On the other hand, the current hotplug implementation
:doc:`design-hotplug` uses the latest QEMU
device model (via the -device option) and is tailored to paravirtual
devices, which leads to buggy behavior: if we hotplug a disk to an
instance that is configured with disk_type=scsi hvparam, the
disk which will get hot-plugged eventually will be a VirtIO device
(i.e., virtio-blk-pci) on the PCI bus.

The current implementation of creating the QEMU command line is
error-prone, since an instance might not be able to boot due to PCI slot
congestion.


Proposed changes
================

We change the way that the KVM hypervisor handles block devices by
introducing latest QEMU device model for SCSI devices as well, so that
scsi-cd, scsi-hd, scsi-block, and scsi-generic device drivers are
supported too. Additionally we refactor the hotplug implementation in
order to support hotplugging of SCSI devices too. Finally, we change the
way we keep track of device info inside runtime files, and the way we
place each device upon instance startup.

Design decisions
================

How to identify each device?

Currently KVM does not support arbitrary IDs for devices; supported are
only names starting with a letter, with max 32 chars length, and only
including the '.', '_', '-' special chars. Currently we generate an ID
with the following format: <device type>-<part of uuid>-pci-<slot>.
This assumes that the device will be plugged in a certain slot on the
PCI bus. Since we want to support devices on a SCSI bus too and adding
the PCI slot to the ID is redundant, we dump the last two parts of the
existing ID. Additionally we get rid of the 'hot' prefix of device type,
and we add the next two parts of the UUID so the chance of collitions
is reduced significantly. So, as an example, the device ID of a disk
with UUID '9e7c85f6-b6e5-4243-b27d-680b78c6d203' would be now
'disk-9e7c85f6-b6e5-4243'.


Which buses does the guest eventually see?

By default QEMU starts with a single PCI bus named "pci.0". In case a
SCSI controller is added on this bus, a SCSI bus is created with
the corresponding name: "scsi.0".
Any SCSI disks will be attached on this SCSI bus. Currently Ganeti does
not explicitly use a SCSI controller via a command line option, but lets
QEMU add one automatically if needed. Here, in case we have a SCSI disk,
a SCSI controller is explicitly added via the -device option. For the
SCSI controller, we do not specify the PCI slot to use, but let QEMU find
the first available (see below).


What type of SCSI controller to use?

QEMU uses the `lsi` controller by default. To make this configurable we
add a new hvparam, `scsi_controller_type`. The available types will be
`lsi`, `megasas`, and `virtio-scsi-pci`.


Where to place the devices upon instance startup?

The default QEMU machine type, `pc`, adds a `i440FX-pcihost`
controller on the root bus that creates a PCI bus with `pci.0` alias.
By default the first three slots of this bus are occupied: slot 0
for Host bridge, slot 1 for ISA bridge, and slot 2 for VGA controller.
Thereafter, the slots depend on the QEMU options passed in the command
line.

The main reason that we want to be fully aware of the configuration of a
running instance (machine type, PCI and SCSI bus state, devices, etc.)
is that in case of migration a QEMU process with the exact same
configuration should be created on the target node. The configuration is
kept in the runtime file created just before starting the instance.
Since hotplug has been introduced, the only thing that can change after
starting an instance is the configuration related to NICs and Disks.

Before implementing hotplug, Ganeti did not specify PCI slots
explicitly, but let QEMU decide how to place the devices on the
corresponding bus. This does not work if we want to have hotplug-able
devices and migrate-able VMs. Currently, upon runtime file creation, we
try to reserve PCI slots based on the hvparams, the disks, and the NICs
of the instance. This has three major shortcomings: first, we have to be
aware which options modify the PCI bus which is practically impossible
due to the huge amount of QEMU options, second, QEMU may change the
default PCI configuration from version to version, and third, we cannot
know if the extra options passed by the user via the `kvm_extra` hvparam
modify the PCI bus.

All the above makes the current implementation error prone: an instance
might not be able to boot if we explicitly add a NIC/Disk on a specific
PCI slot that QEMU has already used for another device while parsing
its command line options. Besides that, now, we want to use the SCSI bus
as well so the above mechanism is insufficient. Here, we decide to put
only disks and NICs on specific slots on the corresponding bus, and let
QEMU put everything else automatically. To this end, we decide to let
the first 12 PCI slots be managed by QEMU, and we start adding PCI
devices (VirtIO block and network devices) from the 13th slot onwards.
As far as the SCSI bus is concerned, we decide to put each SCSI
disk on a different scsi-id (which corresponds to a different target
number in SCSI terminology). The SCSI bus will not have any default
reservations.


How to support the theoretical maximum of devices, 16 disks and 8 NICs?

By default, one could add up to 20 devices on the PCI bus; that is the
32 slots of the PCI bus, minus the starting 12 slots that Ganeti
allows QEMU to manage on its own. In order to by able to add
more PCI devices, we add the new `kvm_pci_reservations` hvparam to
denote how many PCI slots QEMU will handle implicitly. The rest will be
available for disk and NICs inserted explicitly by Ganeti. By default
the default PCI reservations will be 12 as explained above.


How to keep track of the bus state of a running instance?

To be able to hotplug a device, we need to know which slot is
available on the desired bus. Until now, we were using the ``query-pci``
QMP command that returns the state of the PCI buses (i.e., which devices
occupy which slots). Unfortunately, there is no equivalent for the SCSI
buses. We could use the ``info qtree`` HMP command that practically
dumps in plain text the whole device tree. This makes it really hard to
parse. So we decide to generate the bus state of a running instance
through our local runtime files.


What info should be kept in runtime files?

Runtime files are used for instance migration (to run a QEMU process on
the target node with the same configuration) and for hotplug actions (to
update the configuration of a running instance so that it can be
migrated). Until now we were using devices only on the PCI bus, so only
each device's PCI slot should be kept in the runtime file. This is
obviously not enough. We decide to replace the `pci` slot of Disk and
NIC configuration objects, with an `hvinfo` dict. It will contain all
necessary info for constructing the appropriate -device QEMU option.
Specifically the `driver`, `id`, and `bus` parameters will be present to
all kind of devices. PCI devices will have the `addr` parameter, SCSI
devices will have `channel`, `scsi-id`, and `lun`. NICs and Disks will
have the extra `netdev` and `drive` parameters correspondingly.


How to deal with existing instances?

Only existing instances with paravirtual devices (configured via the
disk_type and nic_type hvparam) use the latest QEMU device model. Only
these have the `pci` slot filled. We will use the existing
_UpgradeSerializedRuntime() method to migrate the old runtime format
with `pci` slot in Disk and NIC configuration objects to the new one
with `hvinfo` instead. The new hvinfo will contain the old driver
(either virtio-blk-pci or virtio-net-pci), the old id
(hotdisk-123456-pci-4), the default PCI bus (pci.0), and the old PCI
slot (addr=4). This way those devices will still be hotplug-able, and
the instance will still be migrate-able. When those instances are
rebooted, the hvinfo will be re-generated.


How to support downgrades?

There are two possible ways, both not very pretty. The first one is to
use _UpgradeSerializedRuntime() to remove the hvinfo slot. This would
require the patching of all Ganeti versions down to 2.10 which is practically
imposible. Another way is to ssh to all nodes and remove this slot upon
a cluster downgrade. This ugly hack would go away on 2.17 since we support
downgrades only to the previous minor version.


Configuration changes
---------------------

The ``NIC`` and ``Disk`` objects get one extra slot: ``hvinfo``. It is
hypervisor-specific and will never reach config.data. In case of the KVM
Hypervisor it will contain all necessary info for constructing the -device
QEMU option. Existing entries in runtime files that had a `pci` slot
will be upgraded to have the corresponding `hvinfo` (see above).

The new `scsi_controller_type` hvparam is added to denote what type of
SCSI controller should be added to PCI bus if we have a SCSI disk.
Allowed values will be `lsi`, `virtio-scsi-pci`, and `megasas`.
We decide to use `lsi` by default since this is the one that QEMU
adds automatically if not specified explicitly by an option.


Hypervisor changes
------------------

The current implementation verifies if a hotplug action has succeeded
by scanning the PCI bus and searching for a specific device ID. This
will change, and we will use the ``query-block`` along with the
``query-pci`` QMP command to find block devices that are attached to the
SCSI bus as well.

Up until now, if `disk_type` hvparam was set to `scsi`, QEMU would use the
deprecated device model and end up using SCSI emulation, e.g.:

  ::

    -drive file=/var/run/ganeti/instance-disks/test:0,if=scsi,format=raw

Now the equivalent, which will also enable hotplugging, will be to set
disk_type to `scsi-hd`. The QEMU command line will include:

  ::

    -drive file=/var/run/ganeti/instance-disks/test:0,if=none,format=raw,id=disk-9e7c85f6-b6e5-4243
    -device scsi-hd,id=disk-9e7c85f6-b6e5-4243,drive=disk-9e7c85f6-b6e5-4243,bus=scsi.0,channel=0,scsi-id=0,lun=0


User interface
--------------

The `disk_type` hvparam will additionally support the `scsi-hd`,
`scsi-block`, and `scsi-generic` values. The first one is equivalent to
the existing `scsi` value and will make QEMU emulate a SCSI device,
while the last two will add support for SCSI pass-through and will
require a real SCSI device on the host.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
