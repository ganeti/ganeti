================
vCPU Hotplug
================

:Created: 2026-09-08
:Status: Draft

.. contents:: :depth: 4

This is a design document for hot-adding vCPUs to running KVM
instances without a guest reboot. The initial implementation
targets the KVM hypervisor only.

Current state
=============

The vCPU count of an instance (``vcpus``) is currently a cold-boot
parameter. The KVM command line is generated with
``-smp cpus=<vcpus>`` (plus optional ``cores``, ``threads`` and
``sockets`` entries) and without a ``maxcpus`` entry
(``lib/hypervisor/hv_kvm/__init__.py``). Increasing the configured
vCPU count of a running instance therefore requires a full restart
of the instance.

QEMU/KVM can add CPUs to a running guest: the machine is started
with a maximum number of CPUs (``-smp cpus=N,maxcpus=M``) and the
additional CPUs are enabled at runtime through the QEMU monitor
(QMP); the guest kernel must bring the new CPUs online itself;
Ganeti does not do this.

Ganeti already has a generic hotplug machinery for NICs and disks
(:doc:`design-hotplug`): the cmdlib layer checks hypervisor support
over RPC, the noded side dispatches to the hypervisor, and the KVM
hypervisor talks to QEMU over QMP. This design extends that machinery
with a vCPU target.

Goals
=====

- Allow increasing the vCPU count of a running KVM instance without
  a reboot, as long as the new count does not exceed the maximum
  number of CPUs the instance was started with.
- For increases beyond that maximum, keep the modification working
  (the new value is stored in the configuration) and inform the
  operator that a reboot is required. No automatic reboot.
- Stay consistent with live migration and monitoring.

Non-goals
=========

- vCPU hot-unplug (removing CPUs from a running instance).
- A user-configurable ``maxcpus`` hypervisor parameter; the initial
  implementation uses a fixed value.
- Memory hotplug. Ganeti already adjusts guest memory at runtime
  through the balloon driver (``maxmem``); growing the memory limit
  beyond the balloon range is a separate feature.
- Automatically bring hot-added CPUs online using the
  Qemu Guest Agent (QGA)
- CPU pinning (``cpu_mask``). Pinning hot-added vCPUs requires
  updating the CPU mask after a hot add, which is non-trivial
  because the mask must be extended to cover the additional vCPU
  indices. ``cpu_mask`` is not supported for vCPU hotplug in this
  design. If this is configured, hotplug will not be executed.

Choosing maxcpus
================

CPU hotplug in QEMU requires a ``maxcpus`` value at startup.
Several approaches are possible:

1. ``maxcpus = vcpus * X``

   Scales with the initial instance size, but limits future growth
   according to the vCPU count at boot time.

2. Fixed value (e.g. ``128``)

   Simple implementation with no additional configuration and
   sufficient headroom for most workloads.

3. Cluster policy based

   Derive the value from the cluster's maximum permitted vCPU count.
   This keeps runtime limits aligned with cluster policy, but adds
   a dependency on policy configuration.

The initial implementation uses option 2 and starts all KVM
instances with ``maxcpus = 128``. This is the simplest
implementation, requires no additional configuration,
and provides sufficient headroom for typical
vCPU growth scenarios. More sophisticated approaches can be
added later without affecting the basic hotplug mechanism.

If the instance uses an explicit CPU topology (``cpu_cores``,
``cpu_threads``, ``cpu_sockets``), QEMU requires ``maxcpus`` to be
a multiple of ``sockets * cores * threads``. Ganeti therefore rounds
the fixed value up to the next multiple of the topology product.
Instances without explicit topology parameters use ``128``
unchanged.

Behavior
========

``gnt-instance modify -B vcpus=M`` on a running KVM instance:

- ``M`` above the current count and ``M <= maxcpus``: the CPUs are
  hot-added to the running instance, no reboot.
- ``M`` above ``maxcpus``: the modification is still performed (the
  new value is stored in the configuration) and the job output
  carries a warning that the change takes effect only after a
  reboot. Ganeti does not reboot the instance on its own.
- ``M`` below the current count: the running instance is not
  modified (hot-unplug is out of scope); the new value applies at
  the next cold boot.

Instances that are not running are updated as today.

Mechanism
=========

Cold boot
---------

The KVM command generation appends ``maxcpus=<value>`` to the
existing ``-smp`` entry, computed as described above. The KVM
runtime file stores the full KVM command line, so the maximum is
automatically part of the runtime state.

Hot add
-------

The hotplug machinery is extended with a vCPU target:

- The KVM hypervisor gains a hot-add operation (alongside
  ``HotAddNic``/``HotAddDisk`` in ``lib/hypervisor/hv_kvm/``) which
  issues the QMP ``device-add`` command with the instance's CPU
  model (derived from the ``query-hotpluggable-cpus``)
  for every CPU to be added.
- The operation requires ACPI to be enabled (``acpi`` hvparam, on
  by default for KVM) and works on both the ``pc`` (i440fx) and
  ``q35`` machine types.
- ``HotplugSupported``/``VerifyHotplugSupport`` (``hv_base`` and the
  KVM override) are extended so that the cmdlib layer can check vCPU
  hotplug support before attempting it, as for the existing device
  types.

Bringing CPUs online in the guest
---------------------------------

Hot-adding a CPU only makes it *present* in the guest: QEMU notifies
the guest through ACPI and the guest kernel registers the CPU, but
it starts out *offline* (``/sys/devices/system/cpu/cpu<N>/online``
reads ``0``). Ganeti does not bring the CPU online; that is a
guest-side concern.

To enable the CPU automatically, the guest needs a udev rule, e.g.
``/lib/udev/rules.d/99-hotplug-cpu.rules``::

  SUBSYSTEM=="cpu", ACTION=="add", ATTR{online}=="0", ATTR{online}="1"

Without such a rule (or an equivalent mechanism), a hot-added CPU
stays offline until it is enabled manually inside the guest: the
job succeeds, but the guest does not see more available CPUs.

In the future Ganeti could bring the CPUs online on behalf of the
operator through the QEMU guest agent (QGA), once QGA support has
been implemented; this is not part of the initial implementation.

Runtime file and migration
--------------------------

After a successful hot add, Ganeti must record the new CPU count
and the details of every hot-added CPU so that a live migration
starts the target with an identical CPU configuration. At the
target side the ``-smp xx,...`` parameter must match the source
exactly, and the hot-added CPUs must be appended to the end of
the command line with ``-device`` options that carry the same
properties that were used for the original hotplug.
This properties can be persisted in the KVM runtime
file (analogous to hotplugged NICs and disks).

Existing instances
------------------

Instances whose runtime file predates this feature have no
``maxcpus`` in their KVM command line. For those, vCPU hotplug is
not available: a warning is shown and the new value takes effect
after the next reboot, at which point the regenerated runtime file
carries ``maxcpus``.

Interactions
============

virtio-net queues
   The virtio-net queue count (``virtio_net_queues``, auto mode) is
   derived from the vCPU count at cold boot. Hot-added CPUs do not
   reconfigure existing NICs; they keep the queue count from start.

Monitoring(QMP)
   The monitoring agent already reports the live vCPU count via
   ``query-cpus-fast``; no change is required.

Other hypervisors
   KVM only. Xen and LXC raising ``NotImplementedError`` when hotplug
   is requested.


Future work
===========

- vCPU hot-unplug. As noted in the issue discussion, removing CPUs
  from a running instance may require cooperation from the guest
  (the guest kernel has to take the CPUs offline before the
  hypervisor can remove them) and may disturb vCPU-dependent
  runtime parameters such as the virtio-net queue count, which is
  derived from the vCPU count at cold boot.
- A configurable ``maxcpus`` value (per-instance hypervisor
  parameter or ipolicy-based) replacing the fixed ``128``.
- Bringing hot-added CPUs online automatically from the master side
  via the QEMU guest agent (QGA), once QGA support is implemented in
  Ganeti, instead of relying on a guest-side udev rule.
- CPU pinning for hot-added vCPUs (``cpu_mask``): the mask must be
  extended to cover the newly hot-added vCPU indices.
