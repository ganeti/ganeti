===========================================
KVM machine type: q35 (PCI Express) support
===========================================

:Created: 2026-05-09
:Status: Draft

.. contents:: :depth: 4

This document describes the intent, caveats and limitations of
supporting QEMU's ``q35`` (PCI Express + ICH9) machine type as an
alternative to the historic ``pc`` (i440FX) machine type for KVM
instances managed by Ganeti.

Current state
=============

Up to and including Ganeti 3.1, the KVM hypervisor pinned every
guest-visible PCI device (NICs, virtio disks, SCSI controllers, USB
controllers) to QEMU's flat PCI bus ``pci.0``. ``pci.0`` is the bus
the i440FX-based ``pc`` machine creates by default; the only viable
``machine_version`` choice was therefore one of the ``pc-i440fx-*``
variants (or its ``pc`` alias).

Setting ``machine_version`` to a ``q35`` variant was accepted by
parameter validation but failed to boot, because Ganeti then attempted
to attach all devices to ``pci.0`` which does not exist on ``q35``.

Goals
=====

- Treat ``pc-q35-*`` as a first-class supported ``machine_version`` in
  Ganeti, on equal footing with ``pc-i440fx-*``.
- Keep the legacy ``pc`` path untouched and immune to regressions
  introduced by q35 support.
- Enable predictable network interface names (``eno<N>``) inside
  systemd-aware guests on q35, and make this one of the user incentives
  to move away from i440fx.
- Make sub-optimal q35 configurations visible to operators rather than
  silently working but giving worse results than i440fx.

Unsupported combinations
========================

The following hvparam combinations are rejected with a
``HypervisorError`` on the q35 path:

- ``disk_type=ide`` - ``ide-hd`` maps to the internal 6-channel S-ATA
  controller of the q35 chipset. This does not align with the maximum
  of 16 disks which Ganeti allows the user to attach to a single instance.
  Use ``paravirtual`` (virtio) or ``scsi`` for regular disks.
- ``cdrom_disk_type=paravirtual`` - virtio-blk-pci CD-ROMs are not
  bootable from SeaBIOS and there is no real performance benefit for
  optical media. Use ``cdrom_disk_type=ide`` (available through the chipset's
  S-ATA controller) or ``scsi-cd`` instead. See *CD-ROMs on q35* below.
- ``floppy_image_path`` set - q35 has no ISA DMA controller; floppy
  devices cannot be attached.
- ``nic_type=ne2k_isa`` - the ISA NE2000 model does not enumerate on
  q35; every other KVM NIC type works. Use ``paravirtual`` (virtio),
  ``e1000``, ``rtl8139``, ``ne2k_pci``, or one of the i825xx variants.
- ``soundhw`` set to anything other than ``ac97`` or ``hda`` (or unset).
  Both supported models are PCI(e)-compatible and pin cleanly into the
  static-device multifunction group; the remaining ISA models
  (``sb16``, ``adlib``, ``gus``, ``cs4231a``, ``pcspk``) and PCI
  outliers like ``es1370`` are intentionally not wired up on q35. If
  you need one of them, use a ``pc-i440fx-*`` ``machine_version``.

Approach
========

q35's PCIe root complex differs from i440fx's ``pci.0`` in two
practically important ways:

- Leaf devices cannot be directly attached to the root complex and
  removed at runtime - hot-plug requires an intermediate hot-pluggable
  bus.
- The legacy ``-usb`` / ``-usbdevice`` shorthand does not work because
  there is no implicit UHCI controller.

Ganeti's q35 path therefore differs from the i440fx path in three
places:

1. **PCIe topology.** Ganeti splits the cold-boot static-device set
   from the hot-pluggable dynamic device set:

   - Cold-boot fixed PCI devices (balloon, SCSI controller,
     ``qemu-xhci`` USB controller, ``virtio-serial`` channels for SPICE
     vdagent and the QEMU guest agent) all land as separate functions of
     a single multifunction slot on ``pcie.0`` - mirroring how the q35
     chipset itself packs LPC / SATA / SMBus into the functions of slot
     ``0x1f``. As we do not support ``paravirtual`` for CD ROMs, we can
     save two slots on the PCIe bus.
   - Hot-pluggable leaf devices (NICs, virtio disks) attach as leafs
     to a pre-allocated pool of empty ``pcie-root-port`` shims emitted at
     cold boot. Cold-boot allocations and hot-add allocations both pick
     the lowest free pool slot and emit a single
     ``device_add <leaf>,bus=rp<N>,addr=0x0``; hot-del is a single
     ``device_del`` of the leaf, returning the pool slot to the free
     set. The pool's root-ports are never themselves added or removed
     at runtime.

   Pre-allocation is required because ``pcie.0`` itself is not
   hot-pluggable in QEMU - the PCIe root complex accepts cold-attached
   devices only. Hot-add can therefore only attach a leaf to a bus
   that already exists at machine start, which is exactly what the
   pool provides.

   The full slot map is in the *PCIe topology* section below.
2. **USB controller.** QEMU's q35 machine type does not include any
   implicit USB controller. Whenever Ganeti needs a USB bus - for the
   VNC pointer device, an explicitly configured ``usb_mouse``, or any
   entry in ``usb_devices`` - it emits a single ``qemu-xhci``
   controller in the static-device multifunction group and attaches
   the USB device(s) to it, replacing the legacy ``-usb`` /
   ``-usbdevice`` shorthand used on i440fx.
3. **Interface naming.** Each NIC carries an ACPI index so systemd
   assigns predictable ``eno<N>`` names; see *Guest interface naming*
   below.

SCSI bus addressing is unaffected - Ganeti still places SCSI disks on
their own SCSI bus; only the SCSI controller that the SCSI bus sits on
moves from ``pci.0`` (where it auto-placed) to a fixed function of the
static-device multifunction slot on ``pcie.0``.

PCIe topology
-------------

QEMU's ``pc-q35-*`` machine type only auto-instantiates a minimal
subset of the ICH9 chipset on ``pcie.0``: the MCH host bridge at
``0x00`` and the LPC / SATA / SMBus functions at ``0x1f``. The
integrated VGA at ``0x01`` is built from the ``-vga`` option. Other
devices like the SCSI or USB controllers are explicetly created by
Ganeti if any code paths require their presence.

The full ``pcie.0`` layout for a q35 instance is::

  pcie.0
   ├─ 0x00          MCH host bridge                       (chipset)
   ├─ 0x01          integrated VGA                        (-vga)
   ├─ 0x02.0        virtio-balloon-pci, multifunction=on  (always present)
   ├─ 0x02.1        <scsi controller>                     (if SCSI in use)
   ├─ 0x02.2        qemu-xhci                             (if USB in use)
   ├─ 0x02.3        virtio-serial-pci (SPICE vdagent)     (if SPICE+vdagent)
   ├─ 0x02.4        virtio-serial (QEMU guest agent)      (if guest agent)
   ├─ 0x02.5        AC97 / intel-hda                      (if soundhw)
   ├─ 0x02.6        (reserved, free for future use)
   ├─ 0x02.7        (reserved, free for future use)
   ├─ 0x03..0x0a    8 pre-allocated pcie-root-ports       (NIC pool)
   ├─ 0x0b..0x1a    16 pre-allocated pcie-root-ports      (disk pool)
   ├─ 0x1b..0x1e    (free for future use)
   └─ 0x1f          ICH9 LPC / SATA / SMBus               (chipset)

CD-ROMs (when configured) attach to the chipset ich9-ahci controller at
``0x1f.2`` rather than to ``pcie.0``: ``ide-cd,bus=ide.0,drive=cdrom1``
for cdrom1 and ``ide-cd,bus=ide.1,drive=cdrom2`` for cdrom2. The
remaining four AHCI channels (``ide.2``..``ide.5``) are unused.

The hot-plug pool is split into two separate ranges:

- The **NIC pool** at ``0x03..0x0a`` holds ``MAX_NICS = 8`` root-ports.
  NICs attached here carry an ``acpi-index`` (1..8) on the ``-device``
  line, giving stable ``eno<N>`` names (see *Guest interface naming*).
- The **disk pool** at ``0x0b..0x1a`` holds ``MAX_DISKS = 16``
  root-ports. Disks carry no ``acpi-index``.

The two pools are disjoint and sized to Ganeti's per-instance hard caps,
so an instance can never exhaust either pool, and disk allocations can
never consume a NIC slot (and thus its ACPI index). SCSI disks have
their own bus (see above) and do not consume PCIe pool slots.

Known cosmetic side effect: q35's legacy I/O space is 64KB (~60KB
usable). The Linux PCI subsystem asks for 4KB of I/O behind every
hot-plug-capable bridge, so 24 pre-allocated root-ports overflow the
budget; ~14 ports get I/O windows and the rest log
``bridge window [io  size 0x1000]: failed to assign`` during guest
boot. This is harmless for ``virtio`` devices (no I/O BARs) and the
kernel does an internal rebalance that still produces a working
topology. QEMU's ``io-reserve`` property only controls firmware-side
reservation and does not affect the kernel's realloc behaviour.
Guests that want a clean ``dmesg`` can boot with ``pci=hpiosize=0``.

Function-number assignments inside slot ``0x02`` are stable across
hvparam changes: a conditional device that's not emitted simply leaves
its function number empty (e.g. an instance without SPICE has no
``00:02.3``). The function-0 device must always be present and must
carry ``multifunction=on`` so QEMU recognises the slot as
multifunction; ``virtio-balloon-pci`` is unconditional on q35 and is
the natural anchor.

Why one multifunction slot for static devices rather than per-device
slots:

- It separates concerns. The PCIe pool allocators only manage the
  hot-plug pools; they don't need to know about cold-boot devices, and
  there is no per-device reserved-slot map to maintain as new fixed
  devices are added.
- It mirrors how real q35 silicon presents its own integrated devices
  (LPC / SATA / SMBus as functions of slot ``0x1f``). Guests have no
  trouble enumerating it.
- ``pcie.0`` offers 32 slots in total; 24 are used by the NIC and disk
  section, 6 are used by q35 chipset itself, one is reserved for VGA and
  with that there is only one slot left for all other devices; Increasing
  the number of PCIe slots either introduces more complexity (PCIe switches),
  confuses guests (a second ``pcie.1`` bus seems to indicate NUMA topologies),
  reducing the number of allocatable disks or NICs will confuse users and
  break compatibility with ``pc``/``i440fx`` instances.

The cap is 8 functions per slot. Today the group uses fn=0..4 for the
unconditional/optional cold-boot devices and fn=5 for the ``soundhw``
PCI device (``AC97`` or ``intel-hda``) when one is configured. fn=6 and
fn=7 are intentionally free and available for the next cold-boot fixed
PCI devices without spilling onto a second multifunction slot.

CD-ROMs on q35
--------------

q35 has no legacy IDE controller in QEMU; the only ATAPI host on
the chipset is the integrated ``ich9-ahci`` controller at slot
``0x1f.2``. QEMU's ``ide-cd`` device is the universal ATAPI CD-ROM
frontend - the same device works on either PIIX3-IDE (i440fx) or
ich9-ahci (q35), because QEMU exposes q35's 6 S-ATA channels as
``ide.0``..``ide.5``.

Ganeti pins CD-ROMs to deterministic AHCI channels:

- ``cdrom1`` → ``ide-cd,bus=ide.0``
- ``cdrom2`` → ``ide-cd,bus=ide.1``

so the layout is stable across reboots and SeaBIOS can list them as
boot targets (the firmware can boot from any AHCI-attached ATAPI
device). The remaining channels ``ide.2``..``ide.5`` are left
unallocated.

Supported and default ``cdrom_disk_type`` values on q35:

- ``ide`` (default when ``cdrom_disk_type`` is unset on q35) - using the
  SATA controller, as described above. SeaBIOS-bootable.
- ``scsi-cd`` - attaches to Ganeti's SCSI controller on its own
  ``scsi.0`` bus; SeaBIOS-bootable.
- ``paravirtual`` - **rejected** on q35. ``virtio-blk-pci`` cannot be
  booted from by SeaBIOS, and the performance argument that justifies
  virtio for regular disks doesn't apply to optical media. Also this
  leaves us with two more PCIe multifunction slots which would otherwise
  be reserved for use by ``virtio-blk-pci``.

The default-override is important: the inherit-from-``disk_type``
fallback used on i440fx would resolve to ``paravirtual`` for a default
KVM instance (since ``disk_type`` defaults to ``paravirtual``), which
is then forbidden on q35. Defaulting to ``ide`` on q35 keeps the
out-of-the-box experience working without making users think about
``cdrom_disk_type``.

Chipset detection
=================

Ganeti decides whether an instance is q35 by substring-matching
``"q35"`` against ``machine_version``: the versioned names
(``pc-q35-X.Y``) and the bare ``q35`` alias both match; ``pc-i440fx-*``
and the bare ``pc`` alias both do not. This mirrors how
``AssessParameters`` and other consumers already treat
``machine_version`` as a literal token, and assumes QEMU keeps the
``pc`` / ``q35`` aliases pointed at their historic chipsets.

If ``machine_version`` is unset, Ganeti queries the QEMU binary for
its default (``_GetDefaultMachineVersion``) and stores that value back
into the instance's hvparams snapshot in the runtime file, so that
hot-add operations see the same string the kvm_cmd was built with.

Capability gate and validation
------------------------------

When ``machine_version`` names a q35 machine type:

- If the QEMU build exposes no ``pc-q35-*`` machine type at all,
  Ganeti refuses to start the instance with a clear error rather than
  letting QEMU fail later with a less-actionable message. The presence
  of any ``pc-q35-*`` entry is sufficient evidence that the
  ``pcie-root-port`` device model is also available - it has been
  shipping with q35 since QEMU 4.0.
- The combinations listed under *Unsupported combinations* above are
  rejected with a ``HypervisorError`` before QEMU is invoked.
- Suboptimal but accepted combinations (``lsi`` SCSI controller,
  cirrus/default VGA) emit warnings so operators can act on them.

These checks deliberately live in the validation pass that has the
QEMU binary on hand (and can therefore consult ``-machine help``), not
in ``AssessParameters``, which is a classmethod with no access to the
kvm binary.

Guest interface naming (``eno<N>``)
===================================

systemd-udev's ``net_id`` builtin assigns the ``eno<N>`` form only
when firmware exposes an ACPI ``_DSM`` (Method 0x07) onboard index for
the NIC device. QEMU emits that ``_DSM`` for any PCI device whose
``acpi-index`` property is non-zero, and the kernel surfaces it as
``/sys/class/net/<dev>/device/acpi_index``.

Without an ACPI index, each NIC ends up on its own secondary PCI bus
number (one per root-port) and systemd falls back to ``enp<X>s0`` -
stable but not friendly to operators, and the bus number can
shift between machine versions or after hot add/remove cycles.

Ganeti therefore opts in to ACPI indexes **for NICs only** on q35:

- Disks (virtio/SCSI) and the USB controller do not benefit from
  ``acpi-index``. Block devices are addressed by serial /
  by-id, and the USB tablet has a fixed role. Tagging every device
  would consume the ACPI index namespace and clutter QMP output for no
  payoff.
- On i440fx the ``_DSM`` plumbing is not wired, so this whole
  mechanism is a no-op there.
- ``net.ifnames=0`` on the guest kernel cmdline disables predictable
  naming entirely; in that case the guest gets ``eth0``, ``eth1`` ...
  regardless of chipset.

Index assignment and reuse
--------------------------

Each NIC-pool slot has a fixed ACPI index equal to its 1-based
position in the pool: a NIC on slot ``0x03`` gets ``acpi-index=1``,
``0x04`` gets ``acpi-index=2``, and so on up to ``MAX_NICS = 8``. The
property is set on the NIC ``-device`` line; the ``pcie-root-port``
lines on ``pcie.0`` carry no ``acpi-index``. Disk-pool slots and disk
leaves carry none either.

A NIC therefore takes its name from whichever NIC-pool slot it lands
on - and because disks are allocated from a separate pool, disks can
never consume a NIC's slot or shift the mapping:

- **Cold-boot.** NICs are allocated from the lowest free NIC-pool slot
  upwards in ``instance.nics`` order, so the first cold-boot NIC ends
  up on slot ``0x03`` with ``acpi-index=1`` and is named ``eno1``,
  the second is ``eno2``, and so on - regardless of how many disks
  the instance has.
- **Hot-add NIC.** A hot-added NIC also lands on the lowest free
  NIC-pool slot, picking up that slot's index.
- **Hot-add disk.** A paravirtual disk is allocated from the disk
  pool and never touches a NIC slot, so existing NICs keep their
  ``eno<N>`` names.
- **Hot-remove.** Removing a NIC frees its NIC-pool slot but does not
  change any other NIC's slot; surviving NICs keep their slot and
  therefore their ``eno<N>`` name. This is the property ``eno<N>`` is
  meant to provide and we preserve it strictly.
- **Hot-add after hot-remove.** A new NIC hot-added into a slot freed
  by an earlier hot-remove inherits *that* slot's index, and
  therefore the same ``eno<N>`` the removed NIC had. The kernel sees
  it as a fresh device (different MAC, different driver state, new
  ``ifindex``); the name is reused but no in-guest name conflict
  occurs because the previous ``eno<N>`` device already left the
  kernel before the new one appeared.
- **Hot-remove followed by instance cold-boot**: Removing the second
  out of three NICs will leave the running instance with ``eno1`` and
  ``eno3``. On the next cold-boot, ``eno3`` will be named ``eno2`` as
  it moves up one slot. We'll accept this behavior for now but ack-
  knowledge we break our "stable names" promise here. In future versions
  Ganeti could e.g. track the NIC/slot map in the configuration database
  and guarantee stable NIC positions and names in all cases.

Hot-unplug semantics
====================

On i440fx all leaf devices sit directly on ``pci.0``.  When Ganeti
issues ``device_del`` the device is detached synchronously from QEMU's
side: the QMP reply arrives only after the device has been removed from
``query-pci``.

On q35 leaf devices sit behind a ``pcie-root-port`` and detach via
ACPI-native PCIe hotplug (``pciehp`` in the guest kernel).  ``device_del``
is a *request*: the device stays visible in ``query-pci`` until the
guest's ``pciehp`` driver acks the removal.  QEMU signals completion with a
``DEVICE_DELETED`` QMP event (or ``DEVICE_UNPLUG_GUEST_ERROR`` on
failure).

Ganeti therefore waits for ``DEVICE_DELETED`` / ``DEVICE_UNPLUG_GUEST_ERROR``
before considering a hot-del done, instead of polling ``query-pci``.
The netdev backend (for NICs) is only torn down after the event arrives,
because QEMU rejects ``netdev_del`` while a frontend is still live.

Guest requirement: the kernel must have ``CONFIG_HOTPLUG_PCI_PCIE``
(``pciehp``) built in or loaded as a module.  Without it hot-unplug will
always time out on q35.

Future work
===========

The following items are explicitly out of scope here but are natural
follow-ups:

- Default/cirrus VGA on q35: surfaced as a warning today; a future
  change could auto-select ``std`` or ``virtio`` as the q35 default.
- Persist the NIC/PCIe slot map in the configuration database to
  guarantee stable NIC interface names even if NICs are hot-removed
  and the instance is later cold-booted.
- PCI passthrough / SR-IOV on q35. The bus-addressing model differs
  enough from leaf-on-root-port that it warrants its own design.

Live migration between ``pc`` and ``q35`` is a permanent limitation
(QEMU itself does not support it) and is not addressable here.

