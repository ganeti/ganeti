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

- ``hspace`` computing the capacity for DRBD instances will be unchanged.
  For shared storage instances, however, it will first evacuate one node
  and then compute capacity as normal pretending that node was offline.
  While this technically deviates from interatively doing what hail does,
  it should still give a reasonable estimate of the cluster capacity without
  significantly increasing the algorithmic complexity.
