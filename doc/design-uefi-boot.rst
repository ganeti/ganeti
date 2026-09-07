=========================================
KVM boot modes and UEFI/OVMF boot support
=========================================

:Created: 2026-06-27
:Status: Partially Implemented

.. contents:: :depth: 4

This document describes the ``boot_type`` KVM hypervisor parameter and
the UEFI/OVMF boot mode it introduces, including how the per-instance
OVMF firmware (code + NVRAM) is stored, moved and protected.

Current state
=============

Up to and including Ganeti 3.1 the KVM hypervisor selects the boot mode
*implicitly* from ``kernel_path``:

- a non-empty ``kernel_path`` triggers direct-kernel boot
  (``-kernel`` / ``-initrd`` / ``-append``);
- an empty ``kernel_path`` falls back to legacy BIOS (SeaBIOS) boot
  driven by ``boot_order``.

There is no UEFI support at all, and the boot mode is a side effect of a
path parameter rather than a first-class choice.

Goals
=====

- Make the boot mode an explicit, single-source-of-truth parameter
  (``boot_type``) instead of an implicit consequence of ``kernel_path``.
- Add real UEFI/OVMF boot, with full support for the movement and
  failure paths that matter in production (live migration, failover,
  cold move, disk-template conversion).
- Treat the OVMF NVRAM as **precious data**. Losing it can leave an
  instance unbootable, so it must be stored, mirrored and moved with the
  same guarantees as an instance's data disks - never silently
  regenerated or dropped.
- Preserve pre-4.0 behaviour on upgrade with no operator action.

The ``boot_type`` parameter
============================

``boot_type`` is a per-instance KVM hvparam with three values:

direct_kernel
    Direct-kernel boot. ``kernel_path`` / ``initrd_path`` /
    ``kernel_args`` drive the boot; ``boot_order`` is ignored. This is
    the cluster default for new clusters and preserves the historical
    behaviour (``kernel_path`` keeps its non-empty ``kvmKernel``
    default).

bios
    Legacy BIOS (SeaBIOS) boot driven by ``boot_order``.

uefi
    UEFI/OVMF boot driven by ``boot_order`` (see below).

``boot_type`` is authoritative: ``kernel_path`` / ``initrd_path`` /
``kernel_args`` are honored only under ``direct_kernel``, and
``boot_order`` only under ``bios`` / ``uefi``. Using an empty
``kernel_path`` to toggle disk boot is **deprecated** and documented as
such in the man page, but not enforced with a runtime warning - because
``kernel_path`` has a non-empty default, such a warning would fire for
essentially every ``bios``/``uefi`` instance.

The valid-set constant is deliberately named ``HT_KVM_VALID_BOOT_MODES``
(``htKvmValidBootModes``), not ``BootTypes``, to avoid confusion with the
pre-existing ``htKvmValidBoTypes`` (the boot *order* set) which is one
letter away.

Upgrade inheritance
-------------------

UEFI is new in 4.0, so no pre-existing instance has a firmware disk and
``boot_type`` only ever resolves to ``direct_kernel`` or ``bios`` on
upgrade, synthesized from the literal state of ``kernel_path``
(non-empty → ``direct_kernel``, empty → ``bios``). This synthesis lives
in three places, each acting on the data it actually has:

- ``cfgupgrade`` (``UpgradeCluster`` / ``UpgradeInstances``): the on-disk
  config upgrade. Cluster KVM defaults get ``boot_type`` unconditionally;
  instances get it **only when ``kernel_path`` is an explicit
  instance-level override**, so that instances without an override keep
  inheriting the cluster value rather than freezing it. A matching
  ``DowngradeBootType`` strips ``boot_type`` and ``ovmf_code`` for
  downgrades to 3.1.
- ``objects.Instance.UpgradeConfig``: the same override-aware synthesis
  for a config loaded directly (not via cfgupgrade).
- ``kvm_runtime._upgrade_serialized_runtime``: the serialized runtime is
  read verbatim by ``AcceptInstance`` during live migration from a 3.1
  node. Here ``up_hvp`` is fully merged (``kernel_path`` always present),
  so a plain ``kernel_path`` test suffices.


The firmware disk
=================

The central design decision is how to store the OVMF firmware. OVMF has
two parts: a read-only **code** image and a writable **vars**/NVRAM store
(boot entries and other firmware state). The vars is precious: in a
cluster of hundreds of instances, silently losing or regenerating it is
intolerable as it may render all instances unbootable.

The firmware is therefore stored as a **real ``Disk`` in
``inst.disks``** with a new non-overridable ``Disk.role`` field
(``data`` / ``firmware``), using the **same ``dev_type`` as the
instance's data disks** - mirrored ``DT_DRBD8`` on DRBD instances, and so
on. Because it lives in ``inst.disks``, every movement and failure path
that iterates ``cfg.GetInstanceDisks`` carries it automatically through
already-battle-tested code. There is no bespoke movement code and
therefore no "forgot a path" risk - which is exactly the surface where
data loss would brick an instance.

The firmware code is pinned per-instance at creation, so updating the
node's OVMF package does **not** change a running instance's firmware
(no silent change that could alter boot behaviour).

On-disk layout
--------------

The firmware disk is one raw volume of fixed size
(``OVMF_FIRMWARE_DISK_SIZE`` = 32 MiB - enough for code + vars plus
headroom for future blobs, without oversizing the mirrored volume) laid
out as:

- a small self-describing **superblock** in sector 0 (magic string, version,
  a region table of ``name → (offset, size)``);
- the **code** region (read-only, seeded from ``OVMF_CODE_TEMPLATE``);
- the **vars** region (writable, seeded from ``OVMF_VARS_TEMPLATE``).

Region starts are aligned to 1 MiB. The exact sizes come from the seed
template files and are recorded in the superblock at seed time; the disk
size stays a fixed constant. The layout logic lives in an I/O-free module
(``hv_kvm/firmware.py``) usable both master-side (to size the disk) and
node-side (to seed and to expose the regions).

The layout is designed to hold additional firmware/UEFI-related data regions
in the future (e.g. swtpm).

Configure-time templates
-------------------------

Two templates seed the regions, handled asymmetrically to match their
lifecycle:

- ``--with-ovmf-code-template`` (default ``/usr/share/OVMF/OVMF_CODE.fd``)
  doubles as the cluster-wide default for the per-instance ``ovmf_code``
  hvparam, so an operator can pin an alternative OVMF build on a single
  instance at ``gnt-instance add -H ovmf_code=/path``.
- ``--with-ovmf-vars-template`` (default ``/usr/share/OVMF/OVMF_VARS.fd``)
  is a configure-time constant only, with **no** hvparam: the vars is
  seeded once and never rewritten, so a per-instance override has no
  value.

Both follow the existing ``kvmKernel``/``kvmPath`` pattern (configure
value → ``AutoConf`` → Haskell constant → generated Python constant).

Creation and seeding
---------------------

On a UEFI ``gnt-instance add``, after the data disks are generated, a
firmware ``Disk`` is appended at the **tail** of ``inst.disks``
(``disk/<N>``) via ``GenerateFirmwareDisk`` - same ``dev_type`` as the
data disks, ``role=firmware``, fixed size, and ``LDP_ACCESS`` forced to
``kernelspace`` regardless of the data disks' access mode (see *pflash
attachment* for why). It is created through the normal ``bdev.Create``
path and then seeded by a new node-side RPC, ``blockdev_seed_firmware``
(``backend.BlockdevSeedFirmware``), which writes the superblock and both
regions directly onto the freshly created volume (the DRBD primary
replicates to the secondary). The **existence check** for the OVMF
templates happens here, on the node that seeds the disk - it cannot be
done master-side (``ValidateParameters`` sees only hvparams, and the
master cannot see the node's files). The firmware disk is excluded from
disk wiping (seeding, not wiping, is what initializes it).

Appending at the tail keeps existing data-disk indices (``disk/0..N-1``)
unchanged, so ``grow-disk 0`` and friends behave exactly as before.
Later-added data disks land after the firmware disk, making data indices
non-contiguous - harmless, since indices are opaque handles and the
``role`` field disambiguates in ``gnt-instance info``. This mirrors how
the instance-communication NIC is auto-appended to ``instance.nics``.

Disk adoption (``--disk N:adopt=...``) reuses pre-existing volumes and
never allocates new ones, which is incompatible with a firmware disk
Ganeti must allocate and seed itself; the combination is rejected up
front.

pflash attachment
=================

QEMU's ``-drive if=pflash`` is deprecated, so the firmware is attached
via ``-blockdev`` backing nodes referenced by the ``-machine``
``pflash0=`` / ``pflash1=`` properties (pflash is the CFI flash device
and has no ``-device`` counterpart). The code region is ``pflash0``
(read-only), the vars region ``pflash1`` (writable).

The obstacle is that QEMU pflash maps the *entire* backing node and
requires it to be exactly the flash size, and the ``-blockdev`` ``file``
driver has no offset/size option - yet code and vars are two regions of
one disk. Each region is therefore presented as a standalone whole
device via a device-mapper ``linear`` target
(``dmsetup create <name> --table "0 <sectors> linear <base> <offset>"``,
``--readonly`` for the code region):

- **block-backed templates** (drbd/plain/rbd/ext): the firmware disk's
  node-local symlink already is a ``/dev`` block node, mapped directly -
  no loop devices. For RBD this requires the firmware volume to be
  ``rbd map``-ed, which is why access is forced to kernelspace.
- **file-backed templates** (file/sharedfile/gluster): the firmware disk
  is a local file, so one ``losetup`` over the whole disk provides the
  ``base``, with the dm regions on top.

This is the reason the firmware disk is pinned to **local (kernelspace)
access** independent of the data disks: the dm/loop mechanism needs a
local kernel block node or file to target. The data disks keep whatever
access mode the operator chose (including userspace rbd/gluster). This is
new code - the codebase previously used only ``losetup``/``kpartx`` (for
LXC), never ``dmsetup``.

Command generation vs. side effects
-----------------------------------

``_GenerateKVMRuntime`` stays side-effect-free: it only emits the two
``-blockdev`` nodes (before the ``-machine`` line that references them)
and the ``pflash0``/``pflash1`` machine properties, pointing at
**deterministic** dm paths (``<instance>-ovmf-code`` /
``<instance>-ovmf-vars``). The actual ``dmsetup``/``losetup`` happens in
``_ExecuteKVMRuntime`` (at start) and its cleanup counterpart. Because
the serialized ``kvm_cmd`` references only the stable node-names /
dm paths and never node-specific handles, it is node-portable:
``AcceptInstance`` re-runs the same path on the migration target,
re-exposing the regions from the target's own firmware-disk symlink
before launching the incoming QEMU, which then migrates the pflash device
state onto the target's mirrored/shared vars region.

Setup reads the superblock to learn the geometry, tears down any stale
mapping first (idempotent), and exposes both regions. Cleanup
(``_CleanupFirmwareDisk``, run on every stop) removes the dm devices and
detaches any loop device; it is a no-op for non-UEFI instances. The
firmware **volume itself is never deleted on stop** - only on instance
removal - so NVRAM survives stop/start.

The firmware disk is excluded from the normal guest block-device path in
two places, since it is pflash and occupies no PCI slot: the
``block_devices`` → ``kvm_disks`` loop (no ``hvinfo``/bus allocation) and
``_GenerateKVMBlockDevicesOptions`` (no virtio/ide ``-device``). It is
still kept in ``kvm_disks`` so it is serialized and re-exposed on every
node.

Defensive runtime assertions guard both generation and execution: under
``boot_type=uefi`` a firmware-role disk must be present and must use
kernelspace access, else ``HypervisorError`` before launch.

Movement and failure paths
===========================

Most paths carry the firmware disk **for free** because they iterate
``cfg.GetInstanceDisks`` generically:

- **Live migration** - ``_OpenInstanceDisks`` / ``CheckDiskConsistency`` /
  the DRBD standalone/reconnect/sync dance all include it; QEMU migrates
  the pflash state to the target's vars region. Full support for DRBD and
  shared-storage templates.
- **Failover** - the mirrored DRBD firmware disk fails over with the
  instance.
- **Cold move** - for ``DTS_COPYABLE`` templates the firmware disk is
  copyable and byte-copied like a data disk.
- **Start/stop** - symlinked and cleaned up like a data disk; the volume
  is never deleted on stop.

Three paths do **not** carry it generically and are the real
"forgot a path → brick the instance" risks this design must close:

Disk-template conversion
    ``_ConvertInstanceDisks`` regenerates disks from the *data*-disk
    specs and copies old→new positionally. Left alone it would drop the
    firmware disk (``zip`` truncation) and then remove it. Instead,
    ``_PreserveDiskRoles`` carries each non-data role across by position,
    at all three conversion sub-paths (generic, plain→drbd, drbd→plain).
    The firmware disk thereby inherits the new ``dev_type`` (plain→drbd
    makes it mirrored too) and re-forces kernelspace access. Correctness
    relies on old/new being aligned 1:1 - the firmware disk may sit at
    **any** index (tail only on a fresh instance; adding data disks later
    moves it into the middle), so this must never assume a tail position.

Recreate-disks
    A bare ``gnt-instance recreate-disks`` defaults to *every* index and
    recreates each as an **empty** volume, which would blank the firmware
    (including the read-only code region). ``CheckPrereq`` therefore
    excludes firmware-role indices from the default set and rejects an
    explicit ``--disk <firmware-idx>``. Firmware loss is a separate,
    documented recovery procedure, never an accidental regenerate.

Export/import
    Export/import does not round-trip the firmware disk in this initial
    implementation (the export metadata allow-list omits ``role``, and
    import regenerates every disk as a plain data disk). Rather than ship
    a backup that would restore as a bricked instance, **exporting a UEFI
    instance is rejected** with a clear error. Full round-trip is a
    tracked follow-up (see *Future work*).

The zeroing-image backup check (previously "``boot_order`` must be
disk") is re-expressed in terms of ``boot_type``: the zeroing image boots
from disk via firmware, so ``direct_kernel`` is rejected and
``bios``/``uefi`` must set ``boot_order=disk``.

ipolicy exemption
=================

The firmware disk is a small (32 MiB), fixed-size, system-managed volume.
Checked against the user-facing ipolicy it would violate a disk-size
*minimum* on most clusters, so it is exempted from the
disk-size/disk-count/spindle limits everywhere those are evaluated:

- master-side ``ComputeIPolicyInstanceViolation`` and the
  ``instance_set_params`` disk-spec pre-check filter it out;
- the iallocator request reports each disk's ``role`` so htools can do
  the same;
- htools' ``policyDisks`` filters the firmware disk out of
  ``instCompareISpec`` (disk-size/count) and the exclusive-storage
  spindle sum, while it still counts towards raw capacity.

``Disk.role`` is therefore threaded through the HTools ``Disk`` type and
all its backends (Luxi, RAPI, IAlloc; the text backend has no per-disk
role and defaults to ``data``), and surfaced as the ``disk.roles`` query
field.

User-facing behaviour
=====================

- **``gnt-instance info``** shows non-data disks with their ``role`` - the
  firmware disk is never hidden, since silent loss is a brick risk.
- **grow-disk** on a firmware disk is rejected (fixed size).
- **``modify --disk <idx> remove``/``detach``** of the firmware disk is
  rejected while ``boot_type=uefi`` (would brick the instance).
- **``MAX_DISKS`` (16) counts the firmware disk**, so a UEFI instance
  supports at most 15 data disks. It consumes no PCI slot (pflash is a
  machine property), so only the config-DB count is affected.
- **Switching ``boot_type``** is a disk lifecycle transition, modeled on
  the instance-communication NIC DDM. Switching a **stopped** instance to
  ``uefi`` creates and seeds a firmware disk (node resource locks are
  acquired for it, as for a template change). Switching **away** from
  ``uefi`` keeps the firmware disk in place but inert (no pflash emitted);
  it is never silently destroyed, and can be removed explicitly later.

Invariants
==========

One firmware disk per instance
    The ``firmware`` role is category-level, not blob-specific. All
    precious per-instance firmware state lives in **regions of this one
    disk**; future blobs (vTPM/swtpm state, secure-boot data) become
    additional regions, never additional disks. The driver is **DRBD-minor
    scarcity**: code+vars already cost one mirrored disk per UEFI instance
    (2 minors + 1 port), and per-blob disks would multiply that. The
    dm-``linear`` region split is the accepted price of keeping the cost
    flat.

Raw block only (DRBD dual-primary safety)
    During live migration a DRBD device is briefly dual-primary. This is
    safe only when the device is consumed as a **raw block region** (which
    is what QEMU pflash and swtpm do). A host-side filesystem mounted on a
    dual-primary device would corrupt. Therefore nothing on a firmware
    disk must ever be consumed through a host-side filesystem - this is the
    rule that governs what any future region may do.

Future work
===========

Explicitly out of scope for the initial implementation, but designed for:

- **UEFI export/import round-trip** - add ``role`` to the export
  allow-list and import read-list; on import, recreate the firmware disk
  tagged ``firmware`` and suppress the auto-create; restore vars from the
  exported raw bytes. Removes the export block above. This is the main
  tracked follow-up.
- **OVMF drift audit** - because code is pinned per-instance at creation,
  the cluster can drift from the node's OVMF package over time. A
  ``gnt-cluster verify`` check (or dedicated command) could compare each
  instance's on-disk code region against its resolved ``ovmf_code`` path.
- **``ovmf-instance update``** - operator-triggered re-seed of the
  **code** region only (never the vars). ``ovmf_code`` is already an
  hvparam to make this possible.
- **``direct_kernel_efi`` / ``-shim``** - a possible future boot variant;
  the ``boot_type`` enum is category-level so an additive value fits.
- **TPM / secure boot** - future firmware blobs as additional *regions*
  of the same firmware disk (never additional disks), consumed raw.

TPM and secure boot are out of scope for now. Live migration between
different machine types remains a QEMU-level limitation, unaffected here.
