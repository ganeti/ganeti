ganeti-maintd(8) Ganeti | Version @GANETI_VERSION@
==================================================

Name
----

ganeti-maintd - Ganeti maintenance daemon

Synopsis
--------
**ganeti-maintd** [-f] [-d] [-p *PORT*] [-b *ADDRESS*] [--no-voting --yes-do-it]

DESCRIPTION
-----------

**ganeti-maintd** is the the daemon carrying out regular maintenance
of the cluster.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

The **ganeti-maintd** daemon listens to port 1816 TCP, on all interfaces,
by default. The port can be overridden by an entry the services database
by passing the ``-p`` option.
The ``-b`` option can be used to specify the address to bind to
(defaults to ``0.0.0.0``).

The daemon will refuse to start if it cannot verify that the majority
of cluster nodes believes that it is running on the master node. To
allow failover in a two-node cluster, this can be overridden by the
``--no-voting`` option. In this case, the ``--yes-do-it`` option has
to be given as well.

Operation
~~~~~~~~~

The maintenance daemon will carry out precisely the same jobs that
**harep**\(1) would do if continously run. In particular, it can
be controlled by the same set of opt-in tags.

Communication
~~~~~~~~~~~~~

The daemon will expose its internal state via HTTP. The answer is
encoded in JSON format and is specific to the particular request.

``/``
+++++
The root resource. It will return the list of supported protocol
versions. At the moment, only version ``1`` is supported.

``1/status``
++++++++++++

List of all currently ongoing incidents. This is a list of JSON
objects, each containing at least the following information.

- ``uuid`` The unique identifier assigned to the event.

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


``/1/jobs``
+++++++++++
The list of jobs the daemon will wait for to finish, before starting
the next round of maintenance.

``/1/evacuated``
++++++++++++++++
The list of instance names the daemon does not expect to have load
data available because they have been recently evacuated from an
offline (or drained) node. Currently, this affects only Xen instances,
as for other hypervisors the overall CPU load on the node is taken
as balancing measure.
