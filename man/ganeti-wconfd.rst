ganeti-wconfd(8) Ganeti | Version @GANETI_VERSION@
==================================================

Name
----

ganeti-wconfd - Ganeti configuration writing daemon

Synopsis
--------

**ganeti-wcond** [-f] [-d] [--syslog] [--no-user-checks]
[--no-voting --yes-do-it] [--force-node]

DESCRIPTION
-----------

**ganeti-wconfd** is the daemon that has authoritative knowledge
about the configuration and is the only entity that can accept
changes to it. All jobs that need to modify the configuration will
do so by sending appropriate requests to this daemon.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

Logging to syslog, rather than its own log file, can be enabled by
passing in the ``--syslog`` option.

The **ganeti-wconfd** daemon listens on a Unix socket
(``@LOCALSTATEDIR@/run/ganeti/socket/ganeti-query``) on which it accepts all
requests in an internal protocol format, used by Ganeti jobs.

The daemon will refuse to start if the user and group do not match the
one defined at build time; this behaviour can be overridden by the
``--no-user-checks`` option.

The daemon will refuse to start if it cannot verify that the majority
of cluster nodes believes that it is running on the master node. To
allow failover in a two-node cluster, this can be overridden by the
``--no-voting`` option. As it this is dangerous, the ``--yes-do-it``
option has to be given as well. Also, if the option ``--force-node``
is given, it will accept to run on a non-master node; it should not
be necessary to give this option manually, but
``gnt-cluster masterfailover`` will use it internally to start
the daemon in order to update the master-node information in the
configuration.
