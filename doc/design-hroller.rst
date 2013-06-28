============
HRoller tool
============

.. contents:: :depth: 4

This is a design document detailing the cluster maintenance scheduler,
HRoller.


Current state and shortcomings
==============================

To enable automating cluster-wide reboots a new htool, called HRoller,
was added to Ganeti starting from version 2.7. This tool helps
parallelizing cluster offline maintenances by calculating which nodes
are not both primary and secondary for a DRBD instance, and thus can be
rebooted at the same time, when all instances are down.

The way this is done is documented in the :manpage:`hroller(1)` manpage.

We would now like to perform online maintenance on the cluster by
rebooting nodes after evacuating their primary instances (rolling
reboots).

Proposed changes
================

New options
-----------

- HRoller should be able to operate on single nodegroups (-G flag) or
  select its target node through some other mean (eg. via a tag, or a
  regexp). (Note that individual node selection is already possible via
  the -O flag, that makes hroller ignore a node altogether).
- HRoller should handle non redundant instances: currently these are
  ignored but there should be a way to select its behavior between "it's
  ok to reboot a node when a non-redundant instance is on it" or "skip
  nodes with non-redundant instances". This will only be selectable
  globally, and not per instance.
- Hroller will make sure to keep any instance which is up in its current
  state, via live migrations, unless explicitly overridden. The
  algorithm that will be used calculate the rolling reboot with live
  migrations is described below, and any override on considering the
  instance status will only be possible on the whole run, and not
  per-instance.


Calculating rolling maintenances
--------------------------------

In order to perform rolling maintenance we need to migrate instances off
the nodes before a reboot. How this can be done depends on the
instance's disk template and status:

Down instances
++++++++++++++

If an instance was shutdown when the maintenance started it will be
considered for avoiding contemporary reboot of its primary and secondary
nodes, but will *not* be considered as a target for the node evacuation.
This allows avoiding needlessly moving its primary around, since it
won't suffer a downtime anyway.

Note that a node with non-redundant instances will only ever be
considered good for rolling-reboot if these are down (or the checking of
status is overridden) *and* an explicit option to allow it is set.

DRBD
++++

Each node must migrate all instances off to their secondaries, and then
can either be rebooted, or the secondaries can be evacuated as well.

Since currently doing a ``replace-disks`` on DRBD breaks redundancy,
it's not any safer than temporarily rebooting a node with secondaries on
them (citation needed). As such we'll implement for now just the
"migrate+reboot" mode, and focus later on replace-disks as well.

In order to do that we can use the following algorithm:

1) Compute node sets that don't contain both the primary and the
   secondary of any instance, and also don't contain the primary
   nodes of two instances that have the same node as secondary. These
   can be obtained by computing a coloring of the graph with nodes
   as vertexes and an edge between two nodes, if either condition
   prevents simultaneous maintenance. (This is the current algorithm of
   :manpage:`hroller(1)` with the extension that the graph to be colored
   has additional edges between the primary nodes of two instances sharing
   their secondary node.)
2) It is then possible to migrate in parallel all nodes in a set
   created at step 1, and then reboot/perform maintenance on them, and
   migrate back their original primaries, which allows the computation
   above to be reused for each following set without N+1 failures
   being triggered, if none were present before. See below about the
   actual execution of the maintenance.

Non-DRBD
++++++++

All non-DRBD disk templates that can be migrated have no "secondary"
concept. As such instances can be migrated to any node (in the same
nodegroup). In order to do the job we can either:

- Perform migrations on one node at a time, perform the maintenance on
  that node, and proceed (the node will then be targeted again to host
  instances automatically, as hail chooses targets for the instances
  between all nodes in a group. Nodes in different nodegroups can be
  handled in parallel.
- Perform migrations on one node at a time, but without waiting for the
  first node to come back before proceeding. This allows us to continue,
  restricting the cluster, until no more capacity in the nodegroup is
  available, and then having to wait for some nodes to come back so that
  capacity is available again for the last few nodes.
- Pre-Calculate sets of nodes that can be migrated together (probably
  with a greedy algorithm) and parallelize between them, with the
  migrate-back approach discussed for DRBD to perform the calculation
  only once.

Note that for non-DRBD disks that still use local storage (eg. RBD and
plain) redundancy might break anyway, and nothing except the first
algorithm might be safe. This perhaps would be a good reason to consider
managing better RBD pools, if those are implemented on top of nodes
storage, rather than on dedicated storage machines.

Full-Evacuation
+++++++++++++++

If full evacuation of the nodes to be rebooted is desired, a simple
migration is not enough for the DRBD instances. To keep the number of
disk operations small, we restrict moves to ``migrate, replace-secondary``.
That is, after migrating instances out of the nodes to be rebooted,
replacement secondaries are searched for, for all instances that have
their then secondary on one of the rebooted nodes. This is done by a
greedy algorithm, refining the initial reboot partition, if necessary.

Future work
===========

Hroller should become able to execute rolling maintenances, rather than
just calculate them. For this to succeed properly one of the following
must happen:

- HRoller handles rolling maintenances that happen at the same time as
  unrelated cluster jobs, and thus recalculates the maintenance at each
  step
- HRoller can selectively drain the cluster so it's sure that only the
  rolling maintenance can be going on

DRBD nodes' ``replace-disks``' functionality should be implemented. Note
that when we will support a DRBD version that allows multi-secondary
this can be done safely, without losing replication at any time, by
adding a temporary secondary and only when the sync is finished dropping
the previous one.

Non-redundant (plain or file) instances should have a way to be moved
off as well via plain storage live migration or ``gnt-instance move``
(which requires downtime).

If/when RBD pools can be managed inside Ganeti, care can be taken so
that the pool is evacuated as well from a node before it's put into
maintenance. This is equivalent to evacuating DRBD secondaries.

Master failovers during the maintenance should be performed by hroller.
This requires RPC/RAPI support for master failover. Hroller should also
be modified to better support running on the master itself and
continuing on the new master.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
