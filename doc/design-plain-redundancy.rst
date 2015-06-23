======================================
Redundancy for the plain disk template
======================================

.. contents:: :depth: 4

This document describes how N+1 redundancy is achieved
for instanes using the plain disk template.


Current state and shortcomings
==============================

Ganeti has long considered N+1 redundancy for DRBD, making sure that
on the secondary nodes enough memory is reserved to host the instances,
should one node fail. Recently, ``htools`` have been extended to
also take :doc:`design-shared-storage-redundancy` into account.

For plain instances, there is no direct notion of redundancy: if the
node the instance is running on dies, the instance is lost. However,
if the instance can be reinstalled (e.g, because it is providing a
stateless service), it does make sense to ask if the remaining nodes
have enough free capacity for the instances to be recreated. This
form of capacity planning is currently not addressed by current
Ganeti.


Proposed changes
================

The basic considerations follow those of :doc:`design-shared-storage-redundancy`.
Also, the changes to the tools follow the same pattern.

Definition of N+1 redundancy in the presence of shared and plain storage
------------------------------------------------------------------------

A cluster is considered N+1 redundant, if, for every node, the following
steps can be carried out. First all DRBD instances are migrated out. Then,
all shared-storage instances of that node are relocated to another node in
the same node group. Finally, all plain instances of that node are reinstalled
on a different node in the same node group; in the search for a new nodes for
the plain instances, they will be recreated in order of decreasing memory
size.

Note that the first two setps are those in the definition of N+1 redundancy
for shared storage. In particular, this notion of redundancy strictly extends
the one for shared storage. Again, checking this notion of redundancy is
computationally expensive and the non-DRBD part is mainly a capacity property
in the sense that we expect the majority of instance moves that are fine
from a DRBD point of view will not lead from a redundant to a non-redundant
situation.

Modifications to existing tools
-------------------------------

The changes to the exisiting tools are literally the same as
for :doc:`design-shared-storage-redundancy` with the above definition of
N+1 redundancy substituted in for that of redundancy for shared storage.
In particular, ``gnt-cluster verify`` will not be changed and ``hbal``
will use N+1 redundancy as a final filter step to disallow moves
that lead from a redundant to a non-redundant situation.
