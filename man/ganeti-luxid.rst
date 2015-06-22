ganeti-luxid(8) Ganeti | Version @GANETI_VERSION@
=================================================

Name
----

ganeti-luxid - Ganeti query daemon

Synopsis
--------

**ganeti-luxid** [-f] [-d] [--syslog] [--no-user-checks]
[--no-voting --yes-do-it]

DESCRIPTION
-----------

**ganeti-luxid** is a daemon used to answer queries related to the
configuration and the current live state of a Ganeti cluster. Additionally,
it is the autorative daemon for the Ganeti job queue. Jobs can be
submitted via this daemon and it schedules and starts them.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

Logging to syslog, rather than its own log file, can be enabled by
passing in the ``--syslog`` option.

The **ganeti-luxid** daemon listens on a Unix socket
(``@LOCALSTATEDIR@/run/ganeti/socket/ganeti-query``) on which it exports
a ``Luxi`` endpoint supporting the full set of commands.

The daemon will refuse to start if the user and group do not match the
one defined at build time; this behaviour can be overridden by the
``--no-user-checks`` option.

The daemon will refuse to start if it cannot verify that the majority
of cluster nodes believes that it is running on the master node. To
allow failover in a two-node cluster, this can be overridden by the
``--no-voting`` option. As it this is dangerous, the ``--yes-do-it``
option has to be given as well.


Only queries which don't require locks can be handled by the luxi daemon,
which might lead to slightly outdated results in some cases.

The config is reloaded from disk automatically when it changes, with a
rate limit of once per second.

COMMUNICATION PROTOCOL
~~~~~~~~~~~~~~~~~~~~~~

See **gnt-master**\(8).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
