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
