ganeti-noded(8) Ganeti | Version @GANETI_VERSION@
=================================================

Name
----

ganeti-noded - Ganeti node daemon

Synopsis
--------

**ganeti-noded** [-f] [-d]

DESCRIPTION
-----------

The **ganeti-noded** is the daemon which is responsible for the
node functions in the Ganeti system.

By default, in order to be able to support features such as node
powercycling even on systems with a very damaged root disk,
**ganeti-noded** locks itself in RAM using **mlockall**\(2). You can
disable this feature by passing in the ``--no-mlock`` to the daemon.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

Logging to syslog, rather than its own log file, can be enabled by
passing in the ``--syslog`` option.

The **ganeti-noded** daemon listens to port 1811 TCP, on all
interfaces, by default. The port can be overridden by an entry the
services database (usually ``/etc/services``) or by passing the ``-p``
option.  The ``-b`` option can be used to specify the address to bind
to (defaults to ``0.0.0.0``).

Ganeti noded communication is protected via SSL, with a key
generated at cluster init time. This can be disabled with the
``--no-ssl`` option, or a different SSL key and certificate can be
specified using the ``-K`` and ``-C`` options.

ROLE
~~~~

The role of the node daemon is to do almost all the actions that
change the state of the node. Things like creating disks for
instances, activating disks, starting/stopping instance and so on
are done via the node daemon.

Also, in some cases the startup/shutdown of the master daemon are
done via the node daemon, and the cluster IP address is also
added/removed to the master node via it.

If the node daemon is stopped, the instances are not affected, but
the master won't be able to talk to that node.

COMMUNICATION PROTOCOL
~~~~~~~~~~~~~~~~~~~~~~

Currently the master-node RPC is done using a simple RPC protocol
built using JSON over HTTP(S).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
