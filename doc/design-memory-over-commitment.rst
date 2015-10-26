======================
Memory Over Commitment
======================

.. contents:: :depth: 4

This document describes the proposed changes to support memory
overcommitment in Ganeti.

Background
==========

Memory is a non-preemptable resource, and thus cannot be shared, e.g.,
in a round-robin fashion. Therefore, Ganeti is very careful to make
sure there is always enough physical memory for the memory promised
to the instances. In fact, even in an N+1 redundant way: should one
node fail, its instances can be relocated to other nodes while still
having enough physical memory for the memory promised to all instances.

Overview over the current memory model
--------------------------------------

To make decisions, ``htools`` query the following parameters from Ganeti.

- The amount of memory used by each instance. This is the state-of-record
  backend parameter ``maxmem`` for that instance (maybe inherited from
  group-level or cluster-level backend paramters). It tells the hypervisor
  the maximal amount of memory that instance may use.

- The state-of-world parameters for the node memory. They are collected
  live and are hypervisor specific. The following parameters are collected.

  - memory_total: the total memory size on the node

  - memory_free: the available memory on the node for instances

  - memory_dom0: the memory used by the node itself, if available

  For Xen, the amount of total and free memory are obtained by parsing
  the output of Xen ``info`` command (e.g., ``xm info``). The dom0
  memory is obtained by looking in the output of the ``list`` command
  for ``Domain-0``.

  For the ``kvm`` hypervisor, all these paramters are obtained by
  reading ``/proc/memstate``, where the entries ``MemTotal`` and
  ``Active`` are considered the values for ``memory_total`` and
  ``memory_dom0``, respectively. The value for ``memory_free`` is
  taken as the sum of the entries ``MemFree``, ``Buffers``, and ``Cached``.


Current state and shortcomings
==============================

While the current model of never over committing memory serves well
to provide reliability guarantees to instances, it does not suit well
situations were the actual use of memory in the instances is spiky. Consider
a scenario where instances only touch a small portion of their memory most
of the time, but occasionally use a large amount of memory. Then, at any moment,
a large fraction of the memory used for the instances sits around without
being actively used. By swapping out the not actively used memory, resources
can be used more efficiently.

Proposed changes
================

We propose to support over commitment of memory if desired by the
administrator. Memory will change from being a hard constraint to
being a question of policy. The default will be not to over commit
memory.

Extension of the policy by a new parameter
------------------------------------------

The instance policy is extended by a new real-number field ``memory-ratio``.
Policies on groups inherit this parameter from the cluster wide policy in the
same way as all other parameters of the instance policy.

When a cluster is upgraded from an earlier version not containing
``memory-ratio``, the value ``1.0`` is inserted for this new field in
the cluster-level ``ipolicy``; in this way, the status quo of not over
committing memory is preserved via upgrades. The ``gnt-cluster
modify`` and ``gnt-group modify`` commands are extended to allow
setting of the ``memory-ratio``.

The ``htools`` text format is extended to also contain this new
ipolicy parameter. It is added as an optional entry at the end of the
parameter list of an ipolicy line, to remain backwards compatible.
If the paramter is missing, the value ``1.0`` is assumed.

Changes to the memory reporting on non ``xen-hvm`` and ``xen-pvm``
------------------------------------------------------------------

For all hypervisors ``memory_dom0`` corresponds to the amount of memory used
by Ganeti itself and all other non-hypervisor processes running on this node.
The amount of memory currently reported for ``memory_dom0`` on hypervisors
other than ``xen-hvm`` and ``xen-pvm``, however, includes the amount of active
memory of the hypervisor processes. This is in conflict with the underlying
assumption ``memory_dom0`` memory is not available for instance.

Therefore, for hypervisors other than ``xen-pvm`` and ``xen-hvm`` we will use
a new state-of-recored hypervisor paramter called ``mem_node`` in htools
instead of the reported ``memory_dom0``. As a hypervisor state parameter, it is
run-time tunable and inheritable at group and cluster levels. If this paramter
is not present, a default value of ``1024M`` will be used, which is a
conservative estimate of the amount of memory used by Ganeti on a medium-sized
cluster. The reason for using a state-of-record value is to have a stable
amount of reserved memory, irrespective of the current activity of Ganeti.

Currently, hypervisor state parameters are partly implemented but not used
by ganeti.

Changes to the memory policy
----------------------------

The memory policy will be changed in that we assume that one byte
of physical node memory can hold ``memory-ratio`` bytes of instance
memory, but still only one byte of Ganeti memory. Of course, in practise
this has to be backed by swap space; it is the administrator's responsibility
to ensure that each node has swap of at
least ``(memory-ratio - 1.0) * (memory_total - memory_dom0)``. Ganeti
will warn if the amount of swap space is not big enough.


The new memory policy will be as follows.

- The difference between the total memory of a node and its dom0
  memory will be considered the amount of *available memory*.

- The amount of *used memory* will be (as is now) the sum of
  the memory of all instance and the reserved memory.

- The *relative memory usage* is the fraction of used and available
  memory. Note that the relative usage can be bigger than ``1.0``.

- The memory-related constraint for instance placement is that
  afterwards the relative memory usage be at most the
  memory-ratio. Again, if the ratio of the memory of the real
  instances on the node to available memory is bigger than the
  memory-ratio this is considered a hard violation, otherwise
  it is considered a soft violation.

- The definition of N+1 redundancy (including
  :doc:`design-shared-storage-redundancy`) is kept literally as is.
  Note, however, that the meaning does change, as the definition depends
  on the notion of allowed moves, which is changed by this proposal.


Changes to cluster verify
-------------------------

The only place where the Ganeti core handles memory is
when ``gnt-cluster verify`` verifies N+1 redundancy. This code will be changed
to follow the new memory model.

Additionally, ``gnt-cluster verify`` will warn if the sum of available memory
and swap space is not at least as big as the used memory.

Changes to ``htools``
---------------------

The underlying model of the cluster will be changed in accordance with
the suggested change of the memory policy. As all higher-level ``htools``
operations go through only the primitives of adding/moving an instance
if possible, and inspecting the cluster metrics, changing the base
model will make all ``htools`` compliant with the new memory model.

Balancing
---------

The cluster metric components will not be changed. Note the standard
deviation of relative memory usage is already one of the components.
For dynamic (load-based) balancing, the amount of not immediately
discardable memory will serve as an indication of memory activity;
as usual, the measure will be the standard deviation of the relative
value (i.e., the ratio of non-discardable memory to available
memory). The weighting for this metric component will have to be
determined by experimentation and will depend on the memory ratio;
for a memory ratio of ``1.0`` the weight will be ``0.0``, as memory
need not be taken into account if no over-commitment is in place.
For memory ratios bigger than ``1.0``, the weight will be positive
and grow with the ratio.
