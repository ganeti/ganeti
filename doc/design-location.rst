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
1.0 each. In this way, any common-failure violations are less important than
any hard constraints missed (like instances on offline nodes) so that
the hard constraints will be restored first when balancing a cluster.
Nevertheless, with weight 1.0 the new common-failure components will
still be significantly more important than all the balancedness components
(cpu, disk, memory), as the latter are standard deviations of fractions.
It will also dominate the disk load component which, which, when only taking
static information into account, essentially amounts to counting disks. In
this way, Ganeti will be willing to sacrifice equal numbers of disks on every
node in order to fulfill location requirements.

Appart from changing the balancedness metric, common-failure tags will
not have any other effect. In particular, as opposed to exclusion tags,
no hard guarantees are made: ``hail`` will try allocate an instance in
a common-failure avoiding way if possible, but still allocate the instance
if not.

Additional migration restrictions
=================================

Inequality between nodes can also restrict the set of instance migrations
possible. Here, the most prominent example is updating the hypervisor where
usually migrations from the new to the old hypervisor version is not possible.

Migration tags
--------------

As for exclusion tags, cluster tags will determine which tags are considered
restricting migration. More precisely, a cluster tag of the form
*htools:migration:x* will make node tags starting with *x:* a migration relevant
node property. Additionally, cluster tags of the form
*htools:allowmigration:y::z* where *y* and *z* are migration tags not containing
*::* specify a unidirectional migration possibility from *y* to *z*.

Restriction
-----------

An instance migration will only be considered by ``htools``, if for all
migration tags *y* present on the node migrated from, either the tag
is also present on the node migrated to or there is a cluster tag
*htools::allowmigration:y::z* and the target node is tagged *z* (or both).

Example
-------

For the simple hypervisor upgrade, where migration from old to new is possible,
but not the other way round, tagging all already upgraded nodes suffices.


Advise only
-----------

These tags are of advisory nature only. That is, all ``htools`` will strictly
obey the restrictions imposed by those tags, but Ganeti will not prevent users
from manually instructing other migrations.


Instance pinning
================

Sometimes, administrators want specific instances located in a particular,
typically geographic, location. To support these kind of requests, instances
can be assigned tags of the form *htools:desiredlocation:x* where *x* is a
failure tag. Those tags indicate the the instance wants to be placed on a
node tagged *x*. To make ``htools`` honor those desires, the metric is extended,
appropriately weighted, by the following component.

- Sum of dissatisfied desired locations number among all cluster instances.
  An instance desired location is dissatisfied when the instance is assigned
  a desired-location tag *x* where the node is not tagged with the location
  tag *x*.

Such metric extension allows to specify multiple desired locations for each
instance. These desired locations may be contradictive as well. Contradictive
desired locations mean that we don't care which one of desired locations will
be satisfied.

Again, instance pinning is just heuristics, not a hard enforced requirement;
it will only be achieved by the cluster metrics favouring such placements.

