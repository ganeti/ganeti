=================================
Allocation for Partitioned Ganeti
=================================

.. contents:: :depth: 4


Current state and shortcomings
==============================

The introduction of :doc:`design-partitioned` allowed to
dedicate resources, in particular storage, exclusively to
an instance. The advantage is that such instances have
guaranteed latency that is not affected by other
instances. Typically, those instances are created once
and never moved. Also, typically large chunks (full, half,
or quarter) of a node are handed out to individual
partitioned instances.

Ganeti's allocation strategy is to keep the cluster as
balanced as possible. In particular, as long as empty nodes
are available, new instances, regardless of their size,
will be placed there. Therefore, if a couple of small
instances are placed on the cluster first, it will no longer
be possible to place a big instance on the cluster despite
the total usage of the cluster being low.


Proposed changes
================

We propose to change the allocation strategy of hail for
node groups that have the ``exclusive_storage`` flag set,
as detailed below; nothing will be changed for non-exclusive
node groups. The new strategy will try to keep the cluster
as available for new instances as possible.

Dedicated Allocation Metric
---------------------------

The instance policy is a set of intervals in which the resources
of the instance have to be. Typical choices for dedicated clusters
have disjoint intervals with the same monotonicity in every dimension.
In this case, the order is obvious. In order to make it well-defined
in every case, we specify that we sort the intervals by the lower
bound of the disk size. This is motivated by the fact that disk is
the most critical aspect of partitioned Ganeti.

For a node the *allocation vector* is the vector of, for each
instance policy interval in decreasing order, the number of
instances minimally compliant with that interval that still
can be placed on that node. For the drbd template, it is assumed
that all newly placed instances have new secondaries.

The *lost-allocations vector* for an instance on a node is the
difference of the allocation vectors for that node before and
after placing that instance on that node. Lost-allocation vectors
are ordered lexicographically, i.e., a loss of an allocation
larger instance size dominates loss of allocations of smaller
instance sizes.

If allocating in a node group with ``exclusive_storage`` set
to true, hail will try to minimise the pair of the lost-allocations
vector and the remaining disk space on the node afer, ordered
lexicographically.

Example
-------

Consider the already mentioned scenario were only full, half, and quarter
nodes are given to instances. Here, for the placement of a
quarter-node--sized instance we would prefer a three-quarter-filled node (lost
allocations: 0, 0, 1 and no left overs) over a quarter-filled node (lost
allocations: 0, 0, 1 and half a node left over)
over a half-filled node (lost allocations: 0, 1, 1) over an empty
node (lost allocations: 1, 1, 1). A half-node sized instance, however,
would prefer a half-filled node (lost allocations: 0, 1, 2 and no left-overs)
over a quarter-filled node (lost allocations: 0, 1, 2 and a quarter node left
over) over an empty node (lost allocations: 1, 1, 2).

Note that the presence of additional policy intervals affects the preferences
of instances of other sizes as well. This is by design, as additional available
instance sizes make additional remaining node sizes attractive. If, in the
given example, we would also allow three-quarter-node--sized instances, for
a quarter-node--sized instance it would now be better to be placed on a
half-full node (lost allocations: 0, 0, 1, 1) than on a quarter-filled
node (lost allocations: 0, 1, 0, 1).
