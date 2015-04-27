=================================
N+1 redundancy for shared storage
=================================

.. contents:: :depth: 4

This document describes how N+1 redundancy is achieved
for instanes using shared storage.


Current state and shortcomings
==============================

For instances with DRBD as disk template, in case of failures
of their primary node, there is only one node where the instance
can be restarted immediately. Therefore, ``htools`` reserve enough
memory on that node to cope with failure of a single node.
For instances using shared storage, however, they can be restarted
on any node---implying that on no particular node memory has to
be reserved. This, however, motivated the current state where no
memory is reserved at all. And even a large cluster can run out
of capacity.

Proposed changes
================

Definition on N+1 redundancy in the presence of shared storage
--------------------------------------------------------------

A cluster is considered N+1 redundant, if, for every node, all
DRBD instances can be migrated out and then all shared-storage
instances can be relocated to a different node without moving
instances on other nodes. This is precisely the operation done
after a node breaking. Obviously, simulating failure and evacuation
for every single node is an expensive operation.

Basic Considerations
--------------------

For DRBD, keeping N+1 redundancy is affected by moving instances and
balancing the cluster. Moreover, taking is into account for balancing
can help :doc:`design-allocation-efficiency`. Hence, N+1 redundancy
for DRBD is to be taken into account for all choices affecting instance
location, including instance allocation and balancing.

For shared-storage instances, they can move everywhere within the
node group. So, in practise, this is mainly a question of capacity
planing, especially is most instances have the same size. Nevertheless,
offcuts if instances don't fill a node entirely may not be ignored.


Modifications to existing tools
-------------------------------

- ``hail`` will compute and rank possible allocations as usual. However,
  before returing a choice it will filter out allocations that are
  not N+1 redundant.

- Normal ``gnt-cluster verify`` will not be changed; in particular,
  it will still check for DRBD N+1 redundancy, but not for shared
  storage N+1 redundancy. However, ``hcheck`` will verify shared storage
  N+1 redundancy and report it that fails.

- ``hbal`` will consider and rank moves as usual. However, before deciding
  on the next move, it will filter out those moves that lead from a
  shared storage N+1 redundant configuration into one that isn't.

- ``hspace`` computing the capacity for DRBD instances will be unchanged;
  In particular, the options ``--accept-exisiting`` and ``--independent-groups``
  will continue to work. For shared storage instances, however, will strictly
  iterate over the same allocation step as hail does.


Other modifications related to opportunistic locking
----------------------------------------------------

To allow parallel instance creation, instance creation jobs can be instructed
to run with just whatever node locks currently available. In this case, an
allocation has to be chosen from that restricted set of nodes. Currently, this
is achieved by sending ``hail`` a cluster description where all other nodes
are marked offline; that works as long as only local properties are considered.
With global properties, however, the capacity of the cluster is materially
underestimated, causing spurious global N+1 failures.

Therefore, we conservatively extend the request format of ``hail`` by an
optional parameter ``restrict-to-nodes``. If that parameter is given, only
allocations on those nodes will be considered. This will be an additional
restriction to ones currently considered (e.g., node must be online, a
particular group might have been requested). If opportunistic locking is
enabled, calls to the IAllocator will use this extension to signal which
nodes to restrict to, instead of marking other nodes offline.

It should be noted that this change brings a race. Two concurrent allocations
might bring the cluster over the global N+1 capacity limit. As, however, the
reason for opportunistic locking is an urgent need for instances, this seems
acceptable; Ganeti generally follows the guideline that current problems are
more important than future ones. Also, even with that change allocation is
more careful than the current approach of completely ignoring N+1 redundancy
for shared storage.

