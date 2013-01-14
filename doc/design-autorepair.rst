====================
Instance auto-repair
====================

.. contents:: :depth: 4

This is a design document detailing the implementation of self-repair and
recreation of instances in Ganeti. It also discusses ideas that might be useful
for more future self-repair situations.

Current state and shortcomings
==============================

Ganeti currently doesn't do any sort of self-repair or self-recreate of
instances:

- If a drbd instance is broken (its primary of secondary nodes go
  offline or need to be drained) an admin or an external tool must fail
  it over if necessary, and then trigger a disk replacement.
- If a plain instance is broken (or both nodes of a drbd instance are)
  an admin or an external tool must recreate its disk and reinstall it.

Moreover in an oversubscribed cluster operations mentioned above might
fail for lack of capacity until a node is repaired or a new one added.
In this case an external tool would also need to go through any
"pending-recreate" or "pending-repair" instances and fix them.

Proposed changes
================

We'd like to increase the self-repair capabilities of Ganeti, at least
with regards to instances. In order to do so we plan to add mechanisms
to mark an instance as "due for being repaired" and then the relevant
repair to be performed as soon as it's possible, on the cluster.

The self repair will be written as part of ganeti-watcher or as an extra
watcher component that is called less often.

As the first version we'll only handle the case in which an instance
lives on an offline or drained node. In the future we may add more
self-repair capabilities for errors ganeti can detect.

New attributes (or tags)
------------------------

In order to know when to perform a self-repair operation we need to know
whether they are allowed by the cluster administrator.

This can be implemented as either new attributes or tags. Tags could be
acceptable as they would only be read and interpreted by the self-repair tool
(part of the watcher), and not by the ganeti core opcodes and node rpcs. The
following tags would be needed:

ganeti:watcher:autorepair:<type>
++++++++++++++++++++++++++++++++

(instance/nodegroup/cluster)
Allow repairs to happen on an instance that has the tag, or that lives
in a cluster or nodegroup which does. Types of repair are in order of
perceived risk, lower to higher, and each type includes allowing the
operations in the lower ones:

- ``fix-storage`` allows a disk replacement or another operation that
  fixes the instance backend storage without affecting the instance
  itself. This can for example recover from a broken drbd secondary, but
  risks data loss if something is wrong on the primary but the secondary
  was somehow recoverable.
- ``migrate`` allows an instance migration. This can recover from a
  drained primary, but can cause an instance crash in some cases (bugs).
- ``failover`` allows instance reboot on the secondary. This can recover
  from an offline primary, but the instance will lose its running state.
- ``reinstall`` allows disks to be recreated and an instance to be
  reinstalled. This can recover from primary&secondary both being
  offline, or from an offline primary in the case of non-redundant
  instances. It causes data loss.

Each repair type allows all the operations in the previous types, in the
order above, in order to ensure a repair can be completed fully. As such
a repair of a lower type might not be able to proceed if it detects an
error condition that requires a more risky or drastic solution, but
never vice versa (if a worse solution is allowed then so is a better
one).

If there are multiple ``ganeti:watcher:autorepair:<type>`` tags in an
object (cluster, node group or instance), the least destructive tag
takes precedence. When multiplicity happens across objects, the nearest
tag wins. For example, if in a cluster with two instances, *I1* and
*I2*, *I1* has ``failover``, and the cluster itself has both
``fix-storage`` and ``reinstall``, *I1* will end up with ``failover``
and *I2* with ``fix-storage``.

ganeti:watcher:autorepair:suspend[:<timestamp>]
+++++++++++++++++++++++++++++++++++++++++++++++

(instance/nodegroup/cluster)
If this tag is encountered no autorepair operations will start for the
instance (or for any instance, if present at the cluster or group
level). Any job which already started will be allowed to finish, but
then the autorepair system will not proceed further until this tag is
removed, or the timestamp passes (in which case the tag will be removed
automatically by the watcher).

Note that depending on how this tag is used there might still be race
conditions related to it for an external tool that uses it
programmatically, as no "lock tag" or tag "test-and-set" operation is
present at this time. While this is known we won't solve these race
conditions in the first version.

It might also be useful to easily have an operation that tags all
instances matching a  filter on some charateristic. But again, this
wouldn't be specific to this tag.

If there are multiple
``ganeti:watcher:autorepair:suspend[:<timestamp>]`` tags in an object,
the form without timestamp takes precedence (permanent suspension); or,
if all object tags have a timestamp, the one with the highest timestamp.
When multiplicity happens across objects, the nearest tag wins, as
above. This makes it possible to suspend cluster-enabled repairs with a
single tag in the cluster object; or to suspend them only for a certain
node group or instance. At the same time, it is possible to re-enable
cluster-suspended repairs in a particular instance or group by applying
an enable tag to them.

ganeti:watcher:autorepair:pending:<type>:<id>:<timestamp>:<jobs>
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

(instance)
If this tag is present a repair of type ``type`` is pending on the
target instance. This means that either jobs are being run, or it's
waiting for resource availability. ``id`` is the unique id identifying
this repair, ``timestamp`` is the time when this tag was first applied
to this instance for this ``id`` (we will "update" the tag by adding a
"new copy" of it and removing the old version as we run more jobs, but
the timestamp will never change for the same repair)

``jobs`` is the list of jobs already run or being run to repair the
instance (separated by a plus sign, *+*). If the instance has just
been put in pending state but no job has run yet, this list is empty.

This tag will be set by ganeti if an equivalent autorepair tag is
present and a a repair is needed, or can be set by an external tool to
request a repair as a "once off".

If multiple instances of this tag are present they will be handled in
order of timestamp.

ganeti:watcher:autorepair:result:<type>:<id>:<timestamp>:<result>:<jobs>
++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

(instance)
If this tag is present a repair of type ``type`` has been performed on
the instance and has been completed by ``timestamp``. The result is
either ``success``, ``failure`` or ``enoperm``, and jobs is a
*+*-separated list of jobs that were executed for this repair.

An ``enoperm`` result is returned when the repair was brought on until
possible, but the repair type doesn't consent to proceed further.

Possible states, and transitions
--------------------------------

At any point an instance can be in one of the following health states:

Healthy
+++++++

The instance lives on only online nodes. The autorepair system will
never touch these instances. Any ``repair:pending`` tags will be removed
and marked ``success`` with no jobs attached to them.

This state can transition to:

- Needs-repair, repair disallowed (node offlined or drained, no
  autorepair tag)
- Needs-repair, autorepair allowed (node offlined or drained, autorepair
  tag present)
- Suspended (a suspend tag is added)

Suspended
+++++++++

Whenever a ``repair:suspend`` tag is added the autorepair code won't
touch the instance until the timestamp on the tag has passed, if
present. The tag will be removed afterwards (and the instance will
transition to its correct state, depending on its health and other
tags).

Note that when an instance is suspended any pending repair is
interrupted, but jobs which were submitted before the suspension are
allowed to finish.

Needs-repair, repair disallowed
+++++++++++++++++++++++++++++++

The instance lives on an offline or drained node, but no autorepair tag
is set, or the autorepair tag set is of a type not powerful enough to
finish the repair. The autorepair system will never touch these
instances, and they can transition to:

- Healthy (manual repair)
- Pending repair (a ``repair:pending`` tag is added)
- Needs-repair, repair allowed always (an autorepair always tag is added)
- Suspended (a suspend tag is added)

Needs-repair, repair allowed always
+++++++++++++++++++++++++++++++++++

A ``repair:pending`` tag is added, and the instance transitions to the
Pending Repair state. The autorepair tag is preserved.

Of course if a ``repair:suspended`` tag is found no pending tag will be
added, and the instance will instead transition to the Suspended state.

Pending repair
++++++++++++++

When an instance is in this stage the following will happen:

If a ``repair:suspended`` tag is found the instance won't be touched and
moved to the Suspended state. Any jobs which were already running will
be left untouched.

If there are still jobs running related to the instance and scheduled by
this repair they will be given more time to run, and the instance will
be checked again later.  The state transitions to itself.

If no jobs are running and the instance is detected to be healthy, the
``repair:result`` tag will be added, and the current active
``repair:pending`` tag will be removed. It will then transition to the
Healthy state if there are no ``repair:pending`` tags, or to the Pending
state otherwise: there, the instance being healthy, those tags will be
resolved without any operation as well (note that this is the same as
transitioning to the Healthy state, where ``repair:pending`` tags would
also be resolved).

If no jobs are running and the instance still has issues:

- if the last job(s) failed it can either be retried a few times, if
  deemed to be safe, or the repair can transition to the Failed state.
  The ``repair:result`` tag will be added, and the active
  ``repair:pending`` tag will be removed (further ``repair:pending``
  tags will not be able to proceed, as explained by the Failed state,
  until the failure state is cleared)
- if the last job(s) succeeded but there are not enough resources to
  proceed, the state will transition to itself and no jobs are
  scheduled. The tag is left untouched (and later checked again). This
  basically just delays any repairs, the current ``pending`` tag stays
  active, and any others are untouched).
- if the last job(s) succeeded but the repair type cannot allow to
  proceed any further the ``repair:result`` tag is added with an
  ``enoperm`` result, and the current ``repair:pending`` tag is removed.
  The instance is now back to "Needs-repair, repair disallowed",
  "Needs-repair, autorepair allowed", or "Pending" if there is already a
  future tag that can repair the instance.
- if the last job(s) succeeded and the repair can continue new job(s)
  can be submitted, and the ``repair:pending`` tag can be updated.

Failed
++++++

If repairing an instance has failed a ``repair:result:failure`` is
added. The presence of this tag is used to detect that an instance is in
this state, and it will not be touched until the failure is investigated
and the tag is removed.

An external tool or person needs to investigate the state of the
instance and remove this tag when he is sure the instance is repaired
and safe to turn back to the normal autorepair system.

(Alternatively we can use the suspended state (indefinitely or
temporarily) to mark the instance as "not touch" when we think a human
needs to look at it. To be decided).

A graph with the possible transitions follows; note that in the graph,
following the implementation, the two ``Needs repair`` states have been
coalesced into one; and the ``Suspended`` state disapears, for it
becames an attribute of the instance object (its auto-repair policy).

.. digraph:: "auto-repair-states"

  node     [shape=circle, style=filled, fillcolor="#BEDEF1",
            width=2, fixedsize=true];
  healthy  [label="Healthy"];
  needsrep [label="Needs repair"];
  pendrep  [label="Pending repair"];
  failed   [label="Failed repair"];
  disabled [label="(no state)", width=1.25];

  {rank=same; needsrep}
  {rank=same; healthy}
  {rank=same; pendrep}
  {rank=same; failed}
  {rank=same; disabled}

  // These nodes are needed to be the "origin" of the "initial state" arrows.
  node [width=.5, label="", style=invis];
  inih;
  inin;
  inip;
  inif;
  inix;

  edge [fontsize=10, fontname="Arial Bold", fontcolor=blue]

  inih -> healthy  [label="No tags or\nresult:success"];
  inip -> pendrep  [label="Tag:\nautorepair:pending"];
  inif -> failed   [label="Tag:\nresult:failure"];
  inix -> disabled [fontcolor=black, label="ArNotEnabled"];

  edge [fontcolor="orange"];

  healthy -> healthy [label="No problems\ndetected"];

  healthy -> needsrep [
             label="Brokeness\ndetected in\nfirst half of\nthe tool run"];

  pendrep -> healthy [
             label="All jobs\ncompleted\nsuccessfully /\ninstance healthy"];

  pendrep -> failed [label="Some job(s)\nfailed"];

  edge [fontcolor="red"];

  needsrep -> pendrep [
              label="Repair\nallowed and\ninitial job(s)\nsubmitted"];

  needsrep -> needsrep [
              label="Repairs suspended\n(no-op) or enabled\nbut not powerful enough\n(result: enoperm)"];

  pendrep -> pendrep [label="More jobs\nsubmitted"];


Repair operation
----------------

Possible repairs are:

- Replace-disks (drbd, if the secondary is down), (or other storage
  specific fixes)
- Migrate (shared storage, rbd, drbd, if the primary is drained)
- Failover (shared storage, rbd, drbd, if the primary is down)
- Recreate disks + reinstall (all nodes down, plain, files or drbd)

Note that more than one of these operations may need to happen before a
full repair is completed (eg. if a drbd primary goes offline first a
failover will happen, then a replce-disks).

The self-repair tool will first take care of all needs-repair instance
that can be brought into ``pending`` state, and transition them as
described above.

Then it will go through any ``repair:pending`` instances and handle them
as described above.

Note that the repair tool MAY "group" instances by performing common
repair jobs for them (eg: node evacuate).

Staging of work
---------------

First version: recreate-disks + reinstall (2.6.1)
Second version: failover and migrate repairs (2.7)
Third version: replace disks repair (2.7 or 2.8)

Future work
===========

One important piece of work will be reporting what the autorepair system
is "thinking" and exporting this in a form that can be read by an
outside user or system. In order to do this we need a better
communication system than embedding this information into tags. This
should be thought in an extensible way that can be used in general for
Ganeti to provide "advisory" information about entities it manages, and
for an external system to "advise" ganeti over what it can do, but in a
less direct manner than submitting individual jobs.

Note that cluster verify checks some errors that are actually instance
specific, (eg. a missing backend disk on a drbd node) or node-specific
(eg. an extra lvm device). If we were to split these into "instance
verify", "node verify" and "cluster verify", then we could easily use
this tool to perform some of those repairs as well.

Finally self-repairs could also be extended to the cluster level, for
example concepts like "N+1 failures", missing master candidates, etc. or
node level for some specific types of errors.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
