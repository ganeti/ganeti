ganeti-confd(8) Ganeti | Version @GANETI_VERSION@
=================================================

Name
----

ganeti-confd - Ganeti conf daemon

Synopsis
--------

**ganeti-confd** [-f] [-d]  [--syslog] [-p *PORT*] [-b *ADDRESS*]
[--no-user-checks]

DESCRIPTION
-----------

**ganeti-confd** is a daemon used to answer queries related to the
configuration of a Ganeti cluster.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

Logging to syslog, rather than its own log file, can be enabled by
passing in the ``--syslog`` option.

The **ganeti-confd** daemon listens to port 1814 UDP, on all interfaces,
by default. The port can be overridden by an entry the services database
(usually ``/etc/services``) or by passing the ``-p`` option.  The ``-b``
option can be used to specify the address to bind to (defaults to
``0.0.0.0``).

The daemon will refuse to start if the user and group do not match the
one defined at build time; this behaviour can be overridden by the
``--no-user-checks`` option.

ROLE
~~~~

The role of the conf daemon is to make sure we have a highly available
and very fast way to query cluster configuration values.  This daemon
is automatically active on all master candidates, and so has no single
point of failure. It communicates via UDP so each query can easily be
sent to multiple servers, and it answers queries from a cached copy of
the config it keeps in memory, so no disk access is required to get an
answer.

The config is reloaded from disk automatically when it changes, with a
rate limit of once per second.

If the conf daemon is stopped on all nodes, its clients won't be able
to get query answers.

COMMUNICATION PROTOCOL
~~~~~~~~~~~~~~~~~~~~~~

The confd protocol is an HMAC authenticated json-encoded custom
format, over UDP. A client library is provided to make it easy to
write software to query confd. More information can be found in the
Ganeti 2.1 design doc, and an example usage can be seen in the
(external) NBMA daemon for Ganeti.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
