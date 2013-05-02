==================
Partitioned Ganeti
==================

.. contents:: :depth: 4

Current state and shortcomings
==============================

Currently Ganeti can be used to easily share a node between multiple
virtual instances. While it's easy to do a completely "best effort"
sharing it's quite harder to completely reserve resources for the use of
a particular instance. In particular this has to be done manually for
CPUs and disk, is implemented for RAM under Xen, but not under KVM, and
there's no provision for network level QoS.

Proposed changes
================

We want to make it easy to partition a node between machines with
exclusive use of hardware resources. While some sharing will anyway need
to happen (e.g. for operations that use the host domain, or use
resources, like buses, which are unique or very scarce on host systems)
we'll strive to maintain contention at a minimum, but won't try to avoid
all possible sources of it.

Exclusive use of disks
----------------------

``exclusive_storage`` is a new node parameter. When it's enabled, Ganeti
will allocate entire disks to instances. Though it's possible to think
of ways of doing something similar for other storage back-ends, this
design targets only ``plain`` and ``drbd``. The name is generic enough
in case the feature will be extended to other back-ends. The flag value
should be homogeneous within a node-group; ``cluster-verify`` will report
any violation of this condition.

Ganeti will consider each physical volume in the destination volume
group as a host disk (for proper isolation, an administrator should
make sure that there aren't multiple PVs on the same physical
disk). When ``exclusive_storage`` is enabled in a node group, all PVs
in the node group must have the same size (within a certain margin, say
1%, defined through a new parameter). Ganeti will check this condition
when the ``exclusive_storage`` flag is set, whenever a new node is added
and as part of ``cluster-verify``.

When creating a new disk for an instance, Ganeti will allocate the
minimum number of PVs to hold the disk, and those PVs will be excluded
from the pool of available PVs for further disk creations. The
underlying LV will be striped, when striping is allowed by the current
configuration. Ganeti will continue to track only the LVs, and query the
LVM layer to figure out which PVs are available and how much space is
free. Yet, creation, disk growing, and free-space reporting will ignore
any partially allocated PVs, so that PVs won't be shared between
instance disks.

For compatibility with the DRBD template and to take into account disk
variability, Ganeti will always subtract 2% (this will be a parameter)
from the PV space when calculating how many PVs are needed to allocate
an instance and when nodes report free space.

The obvious target for this option is plain disk template, which doesn't
provide redundancy. An administrator can still provide resilience
against disk failures by setting up RAID under PVs, but this is
transparent to Ganeti.

Spindles as a resource
~~~~~~~~~~~~~~~~~~~~~~

When resources are dedicated and there are more spindles than instances
on a node, it is natural to assign more spindles to instances than what
is strictly needed. For this reason, we introduce a new resource:
spindles. A spindle is a PV in LVM. The number of spindles required for
a disk of an instance is specified together with the size. Specifying
the number of spindles is possible only when ``exclusive_storage`` is
enabled. It is an error to specify a number of spindles insufficient to
contain the requested disk size.

When ``exclusive_storage`` is not enabled, spindles are not used in free
space calculation, in allocation algorithms, and policies. When it's
enabled, ``hspace``, ``hbal``, and allocators will use spindles instead
of disk size for their computation. For each node, the number of all the
spindles in every LVM group is recorded, and different LVM groups are
accounted separately in allocation and balancing.

There is already a concept of spindles in Ganeti. It's not related to
any actual spindle or volume count, but it's used in ``spindle_use`` to
measure the pressure of an instance on the storage system and in
``spindle_ratio`` to balance the I/O load on the nodes. When
``exclusive_storage`` is enabled, these parameters as currently defined
won't make any sense, so their meaning will be changed in this way:

- ``spindle_use`` refers to the resource, hence to the actual spindles
  (PVs in LVM), used by an instance. The values specified in the instance
  policy specifications are compared to the run-time numbers of spindle
  used by an instance. The ``spindle_use`` back-end parameter will be
  ignored.
- ``spindle_ratio`` in instance policies and ``spindle_count`` in node
  parameters are ignored, as the exclusive assignment of PVs already
  implies a value of 1.0 for the first, and the second is replaced by
  the actual number of spindles.

When ``exclusive_storage`` is disabled, the existing spindle parameters
behave as before.

Dedicated CPUs
--------------

``vpcu_ratio`` can be used to tie the number of VCPUs to the number of
CPUs provided by the hardware. We need to take into account the CPU
usage of the hypervisor. For Xen, this means counting the number of
VCPUs assigned to ``Domain-0``.

For KVM, it's more difficult to limit the number of CPUs used by the
node OS. ``cgroups`` could be a solution to restrict the node OS to use
some of the CPUs, leaving the other ones to instances and KVM processes.
For KVM, the number of CPUs for the host system should also be a
hypervisor parameter (set at the node group level).

Dedicated RAM
-------------

Instances should not compete for RAM. This is easily done on Xen, but it
is tricky on KVM.

Xen
~~~

Memory is already fully segregated under Xen, if sharing mechanisms
(transcendent memory, auto ballooning, etc) are not in use.

KVM
~~~
Under KVM or LXC memory is fully shared between the host system and all
the guests, and instances can even be swapped out by the host OS.

It's not clear if the problem can be solved by limiting the size of the
instances, so that there is plenty of room for the host OS.

We could implement segregation using cgroups to limit the memory used by
the host OS. This requires finishing the implementation of the memory
hypervisor status (set at the node group level) that changes how free
memory is computed under KVM systems. Then we have to add a way to
enforce this limit on the host system itself, rather than leaving it as
a calculation tool only.

Another problem for KVM is that we need to decide about the size of the
cgroup versus the size of the VM: some overhead will in particular
exist, due to the fact that an instance and its encapsulating KVM
process share the same space. For KVM systems the physical memory
allocatable to instances should be computed by subtracting an overhead
for the KVM processes, whose value can be either statically configured
or set in a hypervisor status parameter.

NUMA
~~~~

If instances are pinned to CPUs, and the amount of memory used for every
instance is proportionate to the number of VCPUs, NUMA shouldn't be a
problem, as the hypervisors allocate memory in the appropriate NUMA
node. Work is in progress in Xen and the Linux kernel to always allocate
memory correctly even without pinning. Therefore, we don't need to
address this problem specifically; it will be solved by future versions
of the hypervisors or by implementing CPU pinning.

Constrained instance sizes
--------------------------

In order to simplify allocation and resource provisioning we want to
limit the possible sizes of instances to a finite set of specifications,
defined at node-group level.

Currently it's possible to define an instance policy that limits the
minimum and maximum value for CPU, memory, and disk usage (and spindles
and any other resource, when implemented), independently from each other. We
extend the policy by allowing it to contain more occurrences of the
specifications for both the limits for the instance resources. Each
specification pair (minimum and maximum) has a unique priority
associated to it (or in other words, specifications are ordered), which
is used by ``hspace`` (see below). The standard specification doesn't
change: there is one for the whole cluster.

For example, a policy could be set up to allow instances with this
constraints:

- between 1 and 2 CPUs, 2 GB of RAM, and between 10 GB and 400 GB of
  disk space;
- 4 CPUs, 4 GB of RAM, and between 10 GB and 800 GB of disk space.

Then, an instance using 1 CPU, 2 GB of RAM and 50 GB of disk would be
legal, as an instance using 4 CPUs, 4 GB of RAM, and 20 GB of disk,
while an instance using 2 CPUs, 4 GB of RAM and 40 GB of disk would be
illegal.

Ganeti will refuse to create (or modify) instances that violate instance
policy constraints, unless the flag ``--ignore-ipolicy`` is passed.

While the changes needed to check constraint violations are
straightforward, ``hspace`` behavior needs some adjustments for tiered
allocation. ``hspace`` will start to allocate instances using the
maximum specification with the highest priority, then it will try to
lower the most constrained resources (without breaking the policy)
before moving to the second highest priority, and so on.

For consistent results in capacity calculation, the specifications
inside a policy should be ordered so that the biggest specifications
have the highest priorities. Also, specifications should not overlap.
Ganeti won't check nor enforce such constraints, though.

Implementation order
====================

We will implement this design in the following order:

- Exclusive use of disks (without spindles as a resource)
- Constrained instance sizes
- Spindles as a resource
- Dedicated CPU and memory

In this way have always new features that are immediately useful.
Spindles as a resource are not needed for correct capacity calculation,
as long as allowed disk sizes are multiples of spindle size, so it's
been moved after constrained instance sizes. If it turns out that it's
easier to implement dedicated disks with spindles as a resource, then we
will do that.

Possible future enhancements
============================

This section briefly describes some enhancements to the current design.
They may require their own design document, and must be re-evaluated
when considered for implementation, as Ganeti and the hypervisors may
change substantially in the meantime.

Network bandwidth
-----------------

A new resource is introduced: network bandwidth. An administrator must
be able to assign some network bandwidth to the virtual interfaces of an
instance, and set limits in instance policies. Also, a list of the
physical network interfaces available for Ganeti use and their maximum
bandwidth must be kept at node-group or node level. This information
will be taken into account for allocation, balancing, and free-space
calculation.

An additional enhancement is Ganeti enforcing the values set in the
bandwidth resource. This can be done by configuring limits for example
via openvswitch or normal QoS for bridging or routing. The bandwidth
resource represents the average bandwidth usage, so a few new back-end
parameters are needed to configure how to deal with bursts (they depend
on the actual way used to enforce the limit).

CPU pinning
-----------

In order to avoid unwarranted migrations between CPUs and to deal with
NUMA effectively we may need CPU pinning. CPU scheduling is a complex
topic and still under active development in Xen and the Linux kernel, so
we wont' try to outsmart their developers. If we need pinning it's more
to have predictable performance than to get the maximum performance
(which is best done by the hypervisor), so we'll implement a very simple
algorithm that allocates CPUs when an instance is assigned to a node
(either when it's created or when it's moved) and takes into account
NUMA and maybe CPU multithreading. A more refined version might run also
when an instance is deleted, but that would involve reassigning CPUs,
which could be bad with NUMA.

Overcommit for RAM and disks
----------------------------

Right now it is possible to assign more VCPUs to the instances running
on a node than there are CPU available. This works as normally CPU usage
on average is way below 100%. There are ways to share memory pages
(e.g. KSM, transcendent memory) and disk blocks, so we could add new
parameters to overcommit memory and disks, similar to ``vcpu_ratio``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
