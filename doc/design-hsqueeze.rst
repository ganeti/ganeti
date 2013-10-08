=============
HSqueeze tool
=============

.. contents:: :depth: 4

This is a design document detailing the node-freeing scheduler, HSqueeze.


Current state and shortcomings
==============================

Externally-mirrored instances can be moved between nodes at low
cost. Therefore, it is attractive to free up nodes and power them down
at times of low usage, even for small periods of time, like nights or
weekends.

Currently, the best way to find out a suitable set of nodes to shut down
is to use the property of our balancedness metric to move instances
away from drained nodes. So, one would manually drain more and more
nodes and see, if `hbal` could find a solution freeing up all those
drained nodes.


Proposed changes
================

We propose the addition of a new htool command-line tool, called
`hsqueeze`, that aims at keeping resource usage at a constant high
level by evacuating and powering down nodes, or powering up nodes and
rebalancing, as appropriate. By default, only externally-mirrored
instances are moved, but options are provided to additionally take
DRBD instances (which can be moved without downtimes), or even all
instances into consideration.

Tagging of standy nodes
-----------------------

Powering down nodes that are technically healthy effectively creates a
new node state: nodes on standby. To avoid further state
proliferation, and as this information is only used by `hsqueeze`,
this information is recorded in node tags. `hsqueeze` will assume
that offline nodes having a tag with prefix `htools:standby:` can
easily be powered on at any time.

Minimum available resources
---------------------------

To keep the squeezed cluster functional, a minimal amount of resources
will be left available on every node. While the precise amount will
be specifiable via command-line options, a sensible default is chosen,
like enough resource to start an additional instance at standard
allocation on each node. If the available resources fall below this
limit, `hsqueeze` will, in fact, try to power on more nodes, till
enough resources are available, or all standy nodes are online.

To avoid flapping behavior, a second, higher, amount of reserve
resources can be specified, and `hsqueeze` will only power down nodes,
if after the power down this higher amount of reserve resources is
still available.

Computation of the set to free up
---------------------------------

To determine which nodes can be powered down, `hsqueeze` basically
follows the same algorithm as the manual process. It greedily goes
through all non-master nodes and tries if the algorithm used by `hbal`
would find a solution (with the appropriate move restriction) that
frees up the extended set of nodes to be drained, while keeping enough
resources free. Being based on the algorithm used by `hbal`, all
restrictions respected by `hbal`, in particular memory reservation
for N+1 redundancy, are also respected by `hsqueeze`.
The order in which the nodes are tried is choosen by a
suitable heuristics, like trying the nodes in order of increasing
number of instances; the hope is that this reduces the number of
instances that actually have to be moved.

If the amount of free resources has fallen below the lower limit,
`hsqueeze` will determine the set of nodes to power up in a similar
way; it will hypothetically add more and more of the standby
nodes (in some suitable order) till the algorithm used by `hbal` will
finally balance the cluster in a way that enough resources are available,
or all standy nodes are online.


Instance moves and execution
----------------------------

Once the final set of nodes to power down is determined, the instance
moves are determined by the algorithm used by `hbal`. If
requested by the `-X` option, the nodes freed up are drained, and the
instance moves are executed in the same way as `hbal` does. Finally,
those of the freed-up nodes that do not already have a
`htools:standby:` tag are tagged as `htools:standby:auto`, all free-up
nodes are marked as offline and powered down via the
:doc:`design-oob`.

Similarly, if it is determined that nodes need to be added, then first
the nodes are powered up via the :doc:`design-oob`, then they're marked
as online and finally,
the cluster is balanced in the same way, as `hbal` would do. For the
newly powered up nodes, the `htools:standby:auto` tag, if present, is
removed, but no other tags are removed (including other
`htools:standby:` tags).


Design choices
==============

The proposed algorithm builds on top of the already present balancing
algorithm, instead of greedily packing nodes as full as possible. The
reason is, that in the end, a balanced cluster is needed anyway;
therefore, basing on the balancing algorithm reduces the number of
instance moves. Additionally, the final configuration will also
benefit from all improvements to the balancing algorithm, like taking
dynamic CPU data into account.

We decided to have a separate program instead of adding an option to
`hbal` to keep the interfaces, especially that of `hbal`, cleaner. It is
not unlikely that, over time, additional `hsqueeze`-specific options
might be added, specifying, e.g., which nodes to prefer for
shutdown. With the approach of the `htools` of having a single binary
showing different behaviors, having an additional program also does not
introduce significant additional cost.

We decided to have a whole prefix instead of a single tag reserved
for marking standby nodes (we consider all tags starting with
`htools:standby:` as serving only this purpose). This is not only in
accordance with the tag
reservations for other tools, but it also allows for further extension
(like specifying priorities on which nodes to power up first) without
changing name spaces.
