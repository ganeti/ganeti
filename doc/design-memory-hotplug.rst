===================
Memory Hotplug
===================

:Created: 2026-09-16
:Status: Draft

.. contents:: :depth: 4

This is a design document for hot-adding RAM to running KVM instances
without a guest reboot. The initial implementation targets the KVM
hypervisor only and uses the ``virtio-mem`` mechanism.

Current state
=============

The maximum guest memory currently requires a reboot because the
QEMU memory topology is static after startup. Ganeti already exposes
``minmem``, ``memory`` and ``maxmem`` as backend parameters. These are
exclusively used for ballooning: the balloon driver adjusts the
guest-visible memory within the ``minmem``..``maxmem`` range at runtime.
Ballooning, however, only changes how much of the already available
memory the guest actually uses — it cannot make *additional*
guest-usable memory available beyond the original ``-m`` value. To
provide more guest-visible memory, Ganeti needs memory hotplug.

QEMU/KVM provides two mechanisms for memory hotplug:

1. **pc-dimm** — Uses discrete memory devices (DAX devices on Windows)
   that are hotplugged as individual DIMMs with fixed sizes. Requires
   PCI slot reservation, explicit slot assignment, and the hypervisor
   must persist DIMM device IDs and slot mappings for migration.

2. **virtio-mem** — Uses a single sparse memory backend that exposes a
   configurable amount of memory to the VM. Memory is managed in blocks
   controlled by the ``requested-size`` property of the device. The
   hypervisor adjusts ``requested-size`` via QMP to request the guest
   to plug or unplug blocks. A single virtio-mem device covers the
   entire hotpluggable range.

The initial implementation chooses **virtio-mem** as described below.

Goals
=====

- Allow increasing the guest-visible memory of a running KVM instance
  without a reboot, as long as the ``memory_hotplug_method`` hvparam
  is set to ``virtio-mem`` and the new memory does not exceed the
  node's hotplug ceiling (a fixed Python constant).
- For increases beyond the ceiling: the modification is still
  performed (the new value is stored in the configuration) and the
  job output carries a warning that the change takes effect only
  after a reboot. Ganeti does not reboot the instance on its own.
- Stay consistent with live migration — QEMU migrates virtio-mem state
  transparently.

Non-goals
=========

- Memory hot-unplug (removing memory from a running instance).
- NUMA-aware memory hotplug. Ganeti does not use vNUMA currently.
- A configurable ``block-size`` hypervisor parameter; the initial
  implementation uses a fixed block size.
- pc-dimm support in this design (see Future work).
- Automatic coordination between virtio-balloon and virtio-mem.
  The two mechanisms solve different problems and may interact in
  unexpected ways when both are used aggressively. In the initial
  implementation they operate independently and the operator is
  responsible for avoiding conflicting pressure.

Choosing virtio-mem over pc-dimm
================================

Two memory hotplug mechanisms exist in QEMU/KVM.
Here a comparison:

================== ================================== =========================
Aspect             pc-dimm                            virtio-mem
================== ================================== =========================
Device model       Multiple fixed-size DIMMs          Single expandable device
Hot-unplug         Supported (remove DIMM device)     Possible (reduce
                                                      requested-size)
PCI slot usage     One slot per DIMM; slots must be   One slot for the
                   pre-reserved at boot time          virtio-mem-pci device
Migration state    DIMM devices, IDs, and slot        virtio-mem is migrated
                   mappings must be persisted by      natively since QEMU 6.2;
                   Ganeti and rebuilt on target       no Ganeti-side state needed
Guest requirements ACPI is enabled.                   Guest must have a virtio-mem
                                                      driver.
                                                      Linux: fully supported
                                                      since kernel 5.8.
                                                      Windows: experimental.
Sizing granularity Fixed sizes (must plan ahead)      Arbitrary (multiple of
                                                      block-size)
Complexity         Requires slot reservation,         Simpler: one device, change
                   device persistence, migration      one property
================== ================================== =========================

Rationale for virtio-mem
------------------------

Virtio-mem is the preferred approach for the initial implementation
for the following reasons:

1. **Simpler implementation** — Only one device is needed at boot.
   Memory growth is a single QMP call to adjust ``requested-size``.
   No PCI slot reservation beyond one slot is required.

2. **No Ganeti-side migration state** — QEMU migrates virtio-mem
   state (size, requested-size, block-size, plugged state)
   transparently since QEMU 6.2. Ganeti does not need to persist
   device IDs, slot mappings, or DIMM configurations in the runtime
   file. The migration path is identical to cold-boot: the target
   QEMU re-creates the device and restores its state from the migration
   stream.

3. **Future-proof for hot-unplug** — virtio-mem supports memory
   shrinking by reducing ``requested-size``. When hot-unplug is
   needed in the future, virtio-mem can implement it without
   unplugging PCI devices. pc-dimm hot-unplug is more complex as it
   requires guest cooperation and device removal.

4. **Flexible sizing** — virtio-mem grows in block-size increments,
   allowing fine-grained memory adjustments without pre-planning
   fixed DIMM sizes.

5. **Fits Ganeti's data model** — Ganeti already tracks
   ``memory``. virtio-mem maps naturally: the
   base memory is provided via ``-m memory`` and the hotpluggable
   headroom is controlled by a single virtio-mem device. pc-dimm would
   require tracking DIMM inventories, slot assignments, device IDs,
   and migration state.

The main consideration is Windows guest support: Windows support for
virtio-mem is currently experimental (technology preview). Linux
guests (kernel 5.8+) have fully supported in-kernel virtio-mem
drivers. Block-size limitations apply when VFIO passthrough is used.
For Ganeti's initial deployment, the trade-off is acceptable.

Configuration
=============

New hvparam: ``memory_hotplug_method``
---------------------------------------

A new hypervisor parameter controls whether memory hotplug is enabled
per instance:

``memory_hotplug_method``
   One of ``none``, ``virtio-mem``. Default: ``none``.

   This is a per-instance hvparam. It
   defaults to ``none`` for existing instances
   on cluster upgrade, making the feature opt-in. The default
   ensures backward compatibility: instances are unaffected until the
   operator explicitly enables hotplug.

   This parameter also enables future extensibility: additional
   hotplug methods (e.g. ``pc-dimm``) can be added without changing
   the enable/disable semantics.

New constant
--------------

A new Python constant defines the node's hotplug ceiling:

``KVM_VIRTIO_MEM_MAX_SIZE``
   The maximum amount of memory (in MiB) that can be provided via
   virtio-mem on this node. This is a fixed value, analogous to
   ``maxcpus`` for vCPU hotplug. All instances on a node share the
   same ceiling.

   For the initial implementation, the ceiling is fixed (e.g.
   ``65536`` for 64 GiB). Per-instance ceilings can be added later
   if needed.

   This is a Python constant, not a hypervisor parameter. It is not
   stored in ``hvparams`` — it is defined in the KVM hypervisor
   module directly.

Backend parameter separation
----------------------------

Hotplug is **not** driven by ``maxmem`` — that parameter is exclusively
for ballooning. Hotplug is triggered by modifying the ``memory``
parameter (see Behavior section).

QEMU mapping
~~~~~~~~~~~~

When ``memory_hotplug_method`` is set to ``virtio-mem``, the backend
parameters map to QEMU as follows:

- ``memory`` → ``-m <memory>`` (base memory)
- memory-backend-ram object ``size`` → ``KVM_VIRTIO_MEM_MAX_SIZE`` (the
  node's hotplug ceiling)
- virtio-mem device ``requested-size`` → ``memory - base_memory``
  (how much of the ceiling is currently requested)

The ``requested-size`` starts at ``0`` at boot time: the guest sees
exactly ``memory`` bytes. When the operator increases ``memory``,
``requested-size`` is increased to expose more of the ceiling.

Concrete example: node with ``KVM_VIRTIO_MEM_MAX_SIZE = 64G``,
instance with ``memory = 8192``:

- QEMU boot: ``-m 8192`` + virtio-mem device with
  ``requested-size = 0``
- Guest initially sees **8 GiB**.
- When the operator increases ``memory`` to ``24G``, Ganeti adjusts
  ``requested-size`` to ``16384``. The guest now sees **24 GiB**.
- The maximum guest-visible memory is ``KVM_VIRTIO_MEM_MAX_SIZE``.

Choosing the block size
-----------------------

The virtio-mem device uses a ``block-size`` parameter that determines
the granularity of memory plug/unplug operations. The initial
implementation uses a fixed block size of 1 MiB.

Behavior
========

Hotplug is triggered exclusively via the ``memory`` backend parameter
and the ``memory_hotplug_method`` hypervisor parameter:

::

   gnt-instance modify -B memory=X instance-name

This is distinct from the existing ballooning path which uses
``maxmem``:

::

   gnt-instance modify -B maxmem=X instance-name

When ``memory_hotplug_method`` is ``virtio-mem``,
``gnt-instance modify -B memory=X`` on a running KVM instance:

- ``X`` equal to the current ``memory`` value: no action is taken.
- ``X > memory`` (growth within the ceiling): the difference
  ``X - memory`` is requested as ``requested-size`` from the
  virtio-mem device via QMP, and the additional memory becomes
  available in the running instance.
- ``X > memory`` but the total ``X`` would exceed
  ``KVM_VIRTIO_MEM_MAX_SIZE``: the modification is still performed
  (the new ``memory`` value is stored in the configuration) and the
  job output carries a warning that the full amount is not
  available, which requires a reboot.
  Ganeti does not reboot the instance on its own.
- ``X < memory`` (reduction): the running instance is not modified
  (hot-unplug is out of scope); the new value applies at the next
  cold boot.

When ``memory_hotplug_method`` is ``none``, ``memory`` modifications
are handled as before (no hotplug, only ballooning via ``maxmem``).

Instances that are not running are updated as today.

``gnt-instance modify -B maxmem=X`` continues to work as before
and the instances are not available for that mechanism.

Mechanism
=========

Cold boot
---------

When ``memory_hotplug_method`` is set to ``virtio-mem``, the KVM
command generation is extended to create a virtio-mem device at
boot time:

1. A memory backend is created using ``memory-backend-ram`` (or
   ``memory-backend-file`` / ``memory-backend-memfd`` depending on
   the ``mem_path`` hvparam):

   ::

     -object memory-backend-ram,id=vmem0,\
     size=``KVM_VIRTIO_MEM_MAX_SIZE``

   The ``size`` is the fixed ``KVM_VIRTIO_MEM_MAX_SIZE`` value
   (the node's hotplug ceiling).

   The ``reserve=off`` property is critical: it allows sparse
   allocation, meaning memory is only consumed as the guest actually
   plugs blocks. Without it, the full ``size`` would be immediately
   committed.

   The ``dump=off`` property prevents sparse unplugged memory from
   being included in crash dumps.

2. A virtio-mem-pci device is added, referencing the backend:

   ::

     -device virtio-mem-pci,id=vmem0,\
     requested-size=0,block-size=1M

   The device is placed on a free PCI slot by the existing bus
   allocator (following the pattern used for NICs and disks).

3. The ``-m`` parameter equals the current ``memory`` value.

When ``memory_hotplug_method`` is ``none``, no virtio-mem device is
created.

Concrete example: node with ``KVM_VIRTIO_MEM_MAX_SIZE = 64G``,
instance with ``memory_hotplug_method = virtio-mem``,
``memory = 8192``:

::

  -m 8192
  -object memory-backend-ram,id=vmem0,size=64G,reserve=off,dump=off
  -device virtio-mem-pci,id=vmem0,requested-size=0,block-size=1M

The guest initially sees exactly 8 GiB (from ``-m``). The virtio-mem
device can provide up to 64 GiB more.

Hot add (resize)
----------------

The hotplug machinery is extended with a memory resize operation:

- The KVM hypervisor gains a ``HotAddMemory`` method (analogous to
  ``HotAddDisk``/``HotAddNic`` in
  ``lib/hypervisor/hv_kvm/__init__.py``) which:

  1. Checks that ``memory_hotplug_method`` is set to ``virtio-mem``
     (if ``none``, the operation is rejected or falls back to
     ballooning depending on cmdlib logic).
  2. Reads the current ``memory`` value from the instance
     configuration.
  3. Computes the new ``requested-size``:
     ``new_requested_size = X - memory`` (where ``X`` is the
     requested ``memory`` value from the ``modify`` command).
  4. Verifies that the computed ``requested-size`` does not exceed
     the virtio-mem device's ``size`` (i.e.
     ``X - memory <= KVM_VIRTIO_MEM_MAX_SIZE``).
  5. Opens a QMP connection to the running instance.
  6. Discovers the virtio-mem device's QOM path by listing devices
     via ``qom-list`` and finding the device with the matching ``id``.
  7. Issues the QMP ``qom-set`` command to update the device's
     ``requested-size`` property:

     ::

       { "execute": "qom-set",
         "arguments": {
           "path": "<discovered-path>",
           "property": "requested-size",
           "value": <new-requested-size>
         }
       }

     The exact QOM path is determined at runtime via ``qom-list``
     rather than being hard-coded, because paths differ across
     QEMU versions and machine types.

- The ``VerifyHotplugSupport`` / ``HotplugSupported`` methods
  (``hv_base`` and the KVM override) are extended so that the
  cmdlib layer can check virtio-mem support before attempting the
  resize, as for the existing device types.

- The operation requires the virtio-mem device to exist (i.e.,
  ``memory_hotplug_method`` was set to ``virtio-mem`` at boot).

Guest-side behavior
-------------------

When ``requested-size`` is increased, QEMU sends a request to the
guest to plug more memory blocks. The guest kernel must have a
virtio-mem driver to handle these requests:

- **Linux (kernel 5.8+)**: The in-kernel virtio-mem driver handles
  plug requests automatically. Memory becomes available to the guest
  without any guest-side configuration.

- **Windows**: Support is currently experimental (technology preview)
  and not validated by this design. Windows guest support should be
  considered unsupported in the initial implementation. Ganeti does
  not provide or ship a virtio-mem driver for Windows.

Ganeti does not bring the memory online; this is a guest-side concern.

In the future, Ganeti could report the memory hotplug status through
the QEMU guest agent (QGA) — whether the guest has actually consumed
the requested memory — but this is not part of the initial
implementation.

Runtime file and migration
--------------------------

The runtime file stores the virtio-mem device's static configuration
(device ID, ``size``, ``block-size``) so that live migration can
recreate the device with the same parameters on the target node.

The ``requested-size`` is **not** stored in the runtime file. Instead,
at migration time Ganeti derives it from the instance's current
``memory`` value. The ``requested-size`` is **always 0** at boot — no
virtio-mem blocks are plugged initially, the guest sees exactly the
``-m`` memory alone. It is only increased during a hotplug operation
when the operator explicitly requests more memory:

::

  requested-size = memory_at_modify - base_memory_at_boot

This keeps the cluster configuration as the single source of truth
and avoids stale state in the runtime file.

**Migration behavior**: QEMU handles virtio-mem state migration
transparently since QEMU 6.2. The migration stream includes the
memory backend configuration, the virtio-mem device state (size,
requested-size, block-size), and the current plugged/unplugged state
of memory blocks. Ganeti does not need to reconstruct virtio-mem
state on the target — the source QEMU sends the configuration and
state during the migration precopy/postcopy phases.

This is a key advantage over pc-dimm: pc-dimm requires Ganeti to
persist device IDs, slot mappings, and DIMM configurations in the
runtime file and rebuild them on the target, because each DIMM is a
separate QEMU device that must be re-added during migration. With
virtio-mem, the device is simply recreated with the same parameters
and QEMU restores its internal state from the migration stream.

Existing instances
------------------

On cluster upgrade, all existing instances are set to
``memory_hotplug_method = none`` explicitly. This ensures that:

1. The feature is opt-in — no existing instance is affected by
   default.
2. The setting is visible in the instance configuration, making the
   operator's intent explicit.
3. There is no ambiguity about whether an instance should use hotplug
   or not — the value is always known.

New instances also default to ``none``. To enable memory hotplug on
an instance, the operator must explicitly set
``memory_hotplug_method = virtio-mem`` via ``gnt-instance modify``
or instance creation parameters.

Interactions
============

virtio-balloon
   Ganeti already uses the virtio-balloon driver for memory pressure
   management (balloon up/down). virtio-mem and virtio-balloon solve
   different problems and may interact in unexpected ways when both
   are used aggressively. In the initial implementation, they operate
   independently: the balloon manages the reserved vs. guest-visible
   memory ratio within the ``minmem``..``maxmem`` range, while
   virtio-mem changes the total available memory beyond that range.
   The operator should avoid conflicting pressure on guest memory
   management; future work may coordinate the two mechanisms.

Monitoring (QMP)
   The QMP interface already exposes ``info memory-size-summary``
   which shows virtio-mem memory as "plugged". The ``qom-get``
   command can query the current ``requested-size`` and ``size``
   (actual plugged amount) of the virtio-mem device.

VFIO / vIOMMU
   When VFIO passthrough is used with virtio-mem, the block size
   affects the number of DMA mappings: each plugged block requires
   one mapping, and VFIO has a limit on distinct DMA mappings
   (approximately 64k by default). With a 1 MiB block size and a
   64 GiB virtio-mem device, up to 64k blocks could be needed,
   which approaches the default limit. For large devices with VFIO,
   a larger block size (e.g. 8 MiB) or increased
   ``dma_entry_limit`` in the host kernel is recommended. This is
   a configuration consideration for operators, not a runtime check
   in the initial implementation.

Other hypervisors
   KVM only. Xen and LXC raise ``NotImplementedError`` when hotplug
   is requested.

Future work
===========

- pc-dimm support — Implement pc-dimm as an alternative to virtio-mem.
  The ``memory_hotplug_method`` hvparam already supports additional
  values; a new option (e.g. ``pc-dimm``) would enable pc-dimm-based
  hotplug. pc-dimm is needed for scenarios where virtio-mem is not
  suitable (e.g., guests without a virtio-mem driver, or when
  discrete DIMM boundaries are required). pc-dimm requires PCI slot
  reservation, device persistence in the runtime file, and migration
  state reconstruction.

- Memory hot-unplug — Support reducing the ``requested-size`` of the
  virtio-mem device to free memory. Shrinking may fail if the guest
  cannot reclaim memory.

- Per-instance hotplug ceiling — Currently
  ``KVM_VIRTIO_MEM_MAX_SIZE`` is a fixed node-level ceiling
  (analogous to the fixed ``maxcpus`` in the initial vCPU hotplug
  design). A per-instance ceiling could be added as a BE parameter
  (e.g. ``BE_MAX_HOTPLUG_MEMORY``) in the future, allowing different
  hotplug capacities per instance.

- NUMA-aware hotplug — When vNUMA support is added to Ganeti, each
  vNUMA node would need its own virtio-mem device with the ``node``
  property set to the corresponding NUMA node ID.

