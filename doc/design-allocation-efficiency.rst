=========================================================================
Improving allocation efficiency by considering the total reserved memory
=========================================================================

This document describes a change to the cluster metric to enhance
the allocation efficiency of Ganeti's ``htools``.

.. contents:: :depth: 4


Current state and shortcomings
==============================

Ganeti's ``htools``, which typically make all allocation and balancing
decisions, greedily try to improve the cluster metric. So it is important
that the cluster metric faithfully reflects the objectives of these operations.
Currently the cluster metric is composed of counting violations (instances on
offline nodes, nodes that are not N+1 redundant, etc) and the sum of standard
deviations of relative resource usage of the individual nodes. The latter
component is to ensure that all nodes equally bear the load of the instances.
This is reasonable for resources where the total usage is independent of
its distribution, as it is the case for CPU, disk, and total RAM. It is,
however, not true for reserved memory. By distributing its secondaries
more widespread over the cluster, a node can reduce its reserved memory
without increasing it on other nodes. Not taking this aspect into account
has lead to quite inefficient allocation of instances on the cluster (see
example below).

Proposed changes
================

A new additive component is added to the cluster metric. It is the sum over
all nodes of the fraction of reserved memory. This way, moves and allocations
that reduce the amount of memory reserved to ensure N+1 redundancy are favored.

Note that this component does not have the scaling of standard deviations of
fractions, but, instead counts nodes reserved for N+1 redundancy. In an ideal
allocation, this will not exceed 1. But bad allocations will violate this
property. As waste of reserved memory is a more future-oriented problem than,
e.g., current N+1 violations, we give the new component a relatively small
weight of 0.25, so that counting current violations still dominate.

Another consequence of this metric change is that the value 0 is no longer
obtainable: as soon as we have DRBD instance, we have to reserve memory.
However, in most cases only differences of scores influence decissions made.
In the few cases, were absolute values of the cluster score are specified,
they are interpreted as relative to the theoretical minimum of the reserved
memory score.


Example
=======

Consider the capacity of an empty cluster of 6 nodes, each capable of holding
10 instances; this can be measured, e.g., by
``hspace --simulate=p,6,204801,10241,21 --disk-template=drbd
--standard-alloc=10240,1024,2``. Without the metric change 34 standard
instances are allocated. With the metric change, 48 standard instances
are allocated. This is a 41% increase in utilization.
