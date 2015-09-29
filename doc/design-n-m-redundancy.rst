===========================
Checking for N+M redundancy
===========================

.. contents:: :depth: 4

This document describes how the level of redundancy is estimated
in Ganeti.


Current state and shortcomings
==============================

Ganeti keeps the cluster N+1 redundant, also taking into account
:doc:`design-shared-storage-redundancy`. In other words, Ganeti
tries to keep the cluster in a state, where after failure of a single
node, no matter which one, all instances can be started immediately.
However, e.g., for planning
maintenance, it is sometimes desirable to know from how many node
losses the cluster can recover from. This is also useful information,
when operating big clusters and expecting long times for hardware repair.


Proposed changes
================

Higher redundancy as a sequential concept
-----------------------------------------

The intuitive meaning of an N+M redundant cluster is that M nodes can
fail without instances being lost. However, when DRBD is used, already
failure of 2 nodes can cause complete loss of an instance. Therefore, the
best we can hope for, is to be able to recover from M sequential failures.
This intuition that a cluster is N+M redundant, if M nodes can fail one-by-one,
leaving enough time for a rebalance in between, without losing instances, is
formalized in the next definition.

Definition of N+M redundancy
----------------------------

We keep the definition of :doc:`design-shared-storage-redundancy`. Moreover,
for M a non-negative integer, we define a cluster to be N+(M+2) redundant,
if after draining any node the standard rebalancing procedure (as, e.g.,
provided by `hbal`) will fully evacuate that node and result in an N+(M+1)
redundant cluster.

Independence of Groups
----------------------

Immediately from the definition, we see that the redundancy level, i.e.,
the maximal M such that the cluster is N+M redundant, can be computed
in a group-by-group manner: the standard balancing algorithm will never
move instances between node groups. The redundancy level of the cluster
is then the minimum of the redundancy level of the independent groups.

Estimation of the redundancy level
----------------------------------

The definition of N+M redundancy requires to consider M failures in
arbitrary order, thus considering super-exponentially many cases for
large M. As, however, balancing moves instances anyway, the redundancy
level mainly depends on the amount of node resources available to the
instances in a node group. So we can get a good approximation of the
redundancy level of a node group by only considering draining one largest
node in that group. This is how Ganeti will estimate the redundancy level.

Modifications to existing tools
-------------------------------

As redundancy levels higher than N+1 are mainly about planning capacity,
they level of redundancy only needs to be computed on demand. Hence, we
keep the tool changes minimal.

- ``hcheck`` will report the level of redundancy for each node group as
  a new output parameter

The rest of Ganeti will not be changed.
