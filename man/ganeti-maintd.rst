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
