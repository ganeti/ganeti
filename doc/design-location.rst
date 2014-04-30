======================================
Improving location awareness of Ganeti
======================================

This document describes an enhancement of Ganeti's instance
placement by taking into account that some nodes are vulnerable
to common failures.

.. contents:: :depth: 4


Current state and shortcomings
==============================

Currently, Ganeti considers all nodes in a single node group as
equal. However, this is not true in some setups. Nodes might share
common causes of failure or be even located in different places
with spacial redundancy being a desired feature.

The similar problem for instances, i.e., instances providing the
same external service should not placed on the same nodes, is
solved by means of exclusion tags. However, there is no mechanism
for a good choice of node pairs for a single instance. Moreover,
while instances providing the same service run on different nodes,
they are not spread out location wise.


Proposed changes
================

We propose to the cluster metric (as used, e.g., by ``hbal`` and ``hail``)
to honor additional node tags indicating nodes that might have a common
cause of failure.

Failure tags
------------

As for exclusion tags, cluster tags will determine which tags are considered
to denote a source of common failure. More precisely, a cluster tag of the
form *htools:nlocation:x* will make node tags starting with *x:* indicate a
common cause of failure, that redundant instances should avoid.

Metric changes
--------------

The following components will be added cluster metric, weighed appropriately.

- The number of pairs of an instance and a common-failure tag, where primary
  and secondary node both have this tag.

- The number of pairs of exclusion tags and common-failure tags where there
  exist at least two instances with the given exclusion tag with the primary
  node having the given common-failure tag.

The weights for these components might have to be tuned as experience with these
setups grows, but as a starting point, both components will have a weight of
0.5 each. In this way, any common-failure violations are less important than
any hard constraints missed (instances on offline nodes, N+1 redundancy,
exclusion tags) so that the hard constraints will be restored first when
balancing a cluster. Nevertheless, with weight 0.5 the new common-failure
components will still be significantly more important than all the balancedness
components (cpu, disk, memory), as the latter are standard deviations of
fractions.

Appart from changing the balancedness metric, common-failure tags will
not have any other effect. In particular, as opposed to exclusion tags,
no hard guarantees are made: ``hail`` will try allocate an instance in
a common-failure avoiding way if possible, but still allocate the instance
if not.
