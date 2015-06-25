=========================
Ganeti Maintenance Daemon
=========================

.. contents:: :depth: 4

This design document outlines the implementation of a new Ganeti
daemon coordinating all maintenance operations on a cluster
(rebalancing, activate disks, ERROR_down handling, node repairs
actions).


Current state and shortcomings
==============================

With ``harep``, Ganeti has a basic mechanism for repairs of instances
in a cluster. The ``harep`` tool can fix a broken DRBD status, migrate,
failover, and reinstall instances. It is intended to be run regularly,
e.g., via a cron job. It will submit appropriate Ganeti jobs to take
action within the range allowed by instance tags and keep track
of them by recoding the job ids in appropriate tags.

Besides ``harep``, Ganeti offers no further support for repair automation.
While useful, this setup can be insufficient in some situations.

Failures in actual hardware, e.g., a physical disk, currently requires
coordination around Ganeti: the hardware failure is detected on the node,
Ganeti needs to be told to evacuate the node, and, once this is done, some
other entity needs to coordinate the actual physical repair. Currently there
is no support by Ganeti to automatically prepare everything for a hardware
swap.


Proposed changes
================

We propose the addition of an additional daemon, called ``maintd``
that will coordinate cluster balance actions, instance repair actions,
and work for hardware repair needs of individual nodes. The information
about the work to be done will be obtained from a dedicated data collector
via the :doc:`design-monitoring-agent`.

Self-diagnose data collector
----------------------------

The monitoring daemon will get one additional dedicated data collector for
node health. The collector will call an external command supposed to do
any hardware-specific diagnose for the node it is running on. That command
is configurable, but needs to be white-listed ahead of time by the node.
For convenience, the empty string will stand for a build-in diagnose that
always reports that everything is OK; this will also be the default value
for this collector.

Note that the self-diagnose data collector itself can, and usually will,
call separate diagnose tools for separate subsystems. However, it always
has to provide a consolidated description of the overall health state
of the node.

Protocol
~~~~~~~~

The collector script takes no arguments and is supposed to output the string
representation of a single JSON object where the individual fields have the
following meaning. Note that, if several things are broken on that node, the
self-diagnose collector script has to merge them into a single repair action.

status
......

This is a JSON string where the value is one of ``Ok``, ``live-repair``,
``evacuate``, ``evacuate-failover``. This indicates the overall need for
repair and Ganeti actions to be taken. The meaning of these states are
no action needed, some action is needed that can be taken while instances
continue to run on that node, it is necessary to evacuate and offline
the node, and it is necessary to evacuate and offline the node without
attempting live migrations, respectively.

command
.......

If the status is ``live-repair``, a repair command can be specified.
This command will be executed as repair action following the
:doc:`design-restricted-commands`, however extended to read information
on ``stdin``. The whole diagnose JSON object will be provided as ``stdin``
to those commands.

details
.......

An opaque JSON value that the repair daemon will just pass through and
export. It is intended to contain information about the type of repair
that needs to be done after the respective Ganeti action is finished.
E.g., it might contain information which piece of hardware is to be
swapped, once the node is fully evacuated and offlined.

As two failures are considered different, if the output of the script
encodes a different JSON object, the collector script should ensure
that as long as the hardware status does not change, the output of the
script is stable; otherwise this would cause various events reported for
the same failure.

Security considerations
~~~~~~~~~~~~~~~~~~~~~~~

Command execution
.................

Obviously, running arbitrary commands that are part of the configuration
poses a security risk. Note that an underlying design goal of Ganeti is
that even with RAPI credentials known to the attacker, he still cannot
obtain data from within the instances. As monitoring, however, is configurable
via RAPI, we require the node to white-list the command using a mechanism
similar to the :doc:`design-restricted-commands`; in our case, the white-listing
directory will be ``/etc/ganeti/node-diagnose-commands``.

For the repair-commands, as mentioned, we extend the
:doc:`design-restricted-commands` by allowing input on ``stdin``. All other
restrictions, in particular the white-listing requirement, remain. The
white-listing directory will be ``/etc/ganeti/node-repair-commands``.

Result forging
..............

As the repair daemon will take real Ganeti actions based on the diagnose
reported by the self-diagnose script through the monitoring daemon, we
need to verify integrity of such reports to avoid denial-of-service by
fraudaulent error reports. Therefore, the monitoring daemon will sign
the result by an hmac signature with the cluster hmac key, in the same
way as it is done in the ``confd`` wire protocol (see :doc:`design-2.1`).

Repair-event life cycle
-----------------------

Once a repair event is detected, a unique identifier is assigned to it.
As long as the node-health collector returns the same output (as JSON
object), this is still considered the same event.
This identifier can be used to cancel an observed event at any time; for
this an appropriate command-line and RAPI endpoint will be provided. Cancelling
an event tells the repair daemon not to take any actions (despite them
being requested) for this event and forget about it, as soon as it is
no longer observed.

Corresponding Ganeti actions will be initiated and success or failure of
these Ganeti jobs monitored. All jobs submitted by the repair daemon
will have the string ``gnt:daemon:maintd`` and the event identifier
in the reason trail, so that :doc:`design-optables` is possible.
Once a job fails, no further jobs will be submitted for this event
to avoid further damage; the repair action is considered failed in this case.

Once all requested actions succeeded, or one failed, the node where the
event as observed will be tagged by a tag starting with ``maintd:repairready:``
or ``maintd:repairfailed:``, respectively, where the event identifier is
encoded in the rest of the tag. On the one hand, it can be used as an
additional verification whether a node is ready for a specific repair.
However, the main purpose is to provide a simple and uniform interface
to acknowledge an event. Once a ``maintd:repairready`` tag is removed,
the maintenance daemon will forget about this event, as soon as it is no
longer observed by any monitoring daemon. Removing a ``maintd:repairfailed:``
tag will make the maintenance daemon to unconditionally forget the event;
note that, if the underlying problem is not fixed yet, this provides an
easy way of restarting a repair flow.


Repair daemon
-------------

The new daemon ``maintd`` will be running on the master node only. It will
verify the master status of its node by popular vote in the same way as all the
other master-only daemons. If started on a non-master node, it will exit
immediately with exit code ``exitNotmaster``, i.e., 11.

External Reporting Protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Upon successful start, the daemon will bind to a port overridable at
command-line, by default 1816, on the master network device. There it will
serve the current repair state via HTTP. All queries will be HTTP GET
requests and all answers will be encoded in JSON format. Initially, the
following requests will be supported.

``/``
.....

Returns the list of supported protocol versions, initially just ``[1]``.

``/1/status``
.............

Returns a list of all non-cleared incidents. Each incident is reported
as a JSON object with at least the following information.

- ``id`` The unique identifier assigned to the event.

- ``node`` The UUID of the node on which the even was observed.

- ``original`` The very JSON object reported by self-diagnose data collector.

- ``repair-status`` A string describing the progress made on this event so
  far. It is one of the following.

  + ``noted`` The event has been observed, but no action has been taken yet

  + ``pending`` At least one job has been submitted in reaction to the event
    and none of the submitted jobs has failed so far.

  + ``canceled`` The event has been canceled, i.e., ordered to be ignored, but
    is still observed.

  + ``failed`` At least one of the submitted jobs has failed. To avoid further
    damage, the repair daemon will not take any further action for this event.

  + ``completed`` All Ganeti actions associated with this event have been
    completed successfully, including tagging the node.

- ``jobs`` The list of the numbers of ganeti jobs submitted in response to
  this event.

- ``tag`` A string that is the tag that either has been added to the node, or,
  if the repair event is not yet finalized, will be added in case of success.

State
~~~~~

As repairs, especially those involving physically swapping hardware, can take
a long time, the repair daemon needs to store its state persistently. As we
cannot exclude master-failovers during a repair cycle, it does so by storing
it as part of the Ganeti configuration.

This will be done by adding a new top-level entry to the Ganeti configuration.
The SSConf will not be changed.

Superseeding ``harep`` and implicit balancing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To have a single point coordinating all repair actions, the new repair daemon
will also have the ability to take over the work currently done by ``harep``.
To allow a smooth transition, ``maintd`` when carrying out ``harep``'s duties
will add tags in precisely the same way as ``harep`` does.
As the new daemon will have to move instances, it will also have the ability
to balance the cluster in a way coordinated with the necessary evacuation
options; dynamic load information can be taken into account.

The question on whether to do ``harep``'s work and whether to balance the
cluster and if so using which strategy (e.g., taking dynamic load information
into account or not, allowing disk moves or not) are configurable via the Ganeti
configuration. The default will be to do neither of those tasks. ``harep`` will
continue to exist unchanged as part of the ``htools``.

Mode of operation
~~~~~~~~~~~~~~~~~

The repair daemon will poll the monitoring daemons for
the value of the self-diagnose data collector at the same (configurable)
rate the monitoring daemon collects this collector; if load-based balancing is
enabled, it will also collect for the the load data needed.

Repair events will be exposed on the web status page as soon as observed.
The Ganeti jobs doing the actual maintenance will be submitted in rounds.
A new round will be started if all jobs of the old round have finished, and
there is an unhandled repair event or the cluster is unbalanced enough (provided
that autobalancing is enabled).

In each round, ``maintd`` will first determine the most invasive action for
each node; despite the self-diagnose collector summing observations in a single
action recommendation, a new, more invasive recommendation can be issued before
the handling of the first recommendation is finished. For all nodes to be
evacuated, the first evacuation task is scheduled, in a way that these tasks do
not conflict with each other. Then, for all instances on a non-affected node,
that need ``harep``-style repair (if enabled) those jobs are scheduled to the
extend of not conflicting with each other. Then on the remaining nodes that
are not part of a failed repair event either, the jobs
of the first balancing step are scheduled. All those jobs of a round are
submitted at once. As they do not conflict they will be able to run in parallel.
