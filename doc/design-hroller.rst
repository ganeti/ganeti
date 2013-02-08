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


Calculating rolling maintenances
--------------------------------

In order to perform rolling maintenance we need to migrate instances off
the nodes before a reboot. How this can be done depends on the
instance's disk template and status:

Down instances
++++++++++++++

If an instance was shutdown when the maintenance started it will be
ignored. This allows avoiding needlessly moving its primary around,
since it won't suffer a downtime anyway.


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
secondary for any instance. This can be done already by the current
hroller graph coloring algorithm: nodes are in the same set (color) if
and only if no edge (instance) exists between them (see the
:manpage:`hroller(1)` manpage for more details).
2) Inside each node set calculate subsets that don't have any secondary
node in common (this can be done by creating a graph of nodes that are
connected if and only if an instance on both has the same secondary
node, and coloring that graph)
3) It is then possible to migrate in parallel all nodes in a subset
created at step 2, and then reboot/perform maintenance on them, and
migrate back their original primaries, which allows the computation
above to be reused for each following subset without N+1 failures being
triggered, if none were present before. See below about the actual
execution of the maintenance.

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

Executing rolling maintenances
------------------------------

Hroller accepts commands to run to do maintenance automatically. These
are going to be run on the machine hroller runs on, and take a node name
as input. They have then to gain access to the target node (via ssh,
restricted commands, or some other means) and perform their duty.

1) A command (--check-cmd) will be called on all selected online nodes
to check whether a node needs maintenance. Hroller will proceed only on
nodes that respond positively to this invocation.
FIXME: decide about -D
2) Hroller will evacuate the node of all primary instances.
3) A command (--maint-cmd) will be called on a node to do the actual
maintenance operation.  It should do any operation needed to perform the
maintenance including triggering the actual reboot.
3) A command (--verify-cmd) will be called to check that the operation
was successful, it has to wait until the target node is back up (and
decide after how long it should give up) and perform the verification.
If it's not successful hroller will stop and not proceed with other
nodes.
4) The master node will be kept last, but will not otherwise be treated
specially. If hroller was running on the master node, care must be
exercised as its maintenance will have interrupted the software itself,
and as such the verification step will not happen. This will not
automatically be taken care of, in the first version. An additional flag
to just skip the master node will be present as well, in case that's
preferred.


Future work
===========

DRBD nodes' ``replace-disks``' functionality should be implemented. Note
that when we will support a DRBD version that allows multi-secondary
this can be done safely, without losing replication at any time, by
adding a temporary secondary and only when the sync is finished dropping
the previous one.

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
