ganeti-queryd(8) Ganeti | Version @GANETI_VERSION@
==================================================

Name
----

ganeti-queryd - Ganeti query daemon

Synopsis
--------

**ganeti-queryd** [-f] [-d]

DESCRIPTION
-----------

**ganeti-queryd** is a daemon used to answer queries related to the
configuration and the current live state of a Ganeti cluster.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

Logging to syslog, rather than its own log file, can be enabled by
passing in the ``--syslog`` option.

The **ganeti-queryd** daemon listens on a Unix socket
(``@LOCALSTATEDIR@/run/ganeti/socket/ganeti-query``) on which it exports
a ``Luxi`` endpoint, serving query operations only. Commands and tools
use this socket if the build-time option for split queries has been
enabled.

The daemon will refuse to start if the user and group do not match the
one defined at build time; this behaviour can be overridden by the
``--no-user-checks`` option.

ROLE
~~~~

The role of the query daemon is to answer queries about the (live)
cluster state without going through the master daemon. Only queries
which don't require locks can be handles by the query daemon, which
might lead to slightly outdated results in some cases.

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
