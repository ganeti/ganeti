ganeti-rapi(8) Ganeti | Version @GANETI_VERSION@
================================================

Name
----

ganeti-rapi - Ganeti remote API daemon

Synopsis
--------

**ganeti-rapi** [-d] [-f] [--no-ssl] [-K *SSL_KEY_FILE*] [-C
*SSL_CERT_FILE*]

DESCRIPTION
-----------

**ganeti-rapi** is the daemon providing a remote API for Ganeti
clusters.

It is automatically started on the master node, and by default it
uses SSL encryption. This can be disabled by passing the
``--no-ssl`` option, or alternatively the certificate used can be
changed via the ``-C`` option and the key via the ``-K`` option.

The daemon will listen to the "ganeti-rapi" tcp port, as listed in the
system services database, or if not defined, to port 5080 by default.

See the *Ganeti remote API* documentation for further information.

Requests are logged to ``@LOCALSTATEDIR@/log/ganeti/rapi-daemon.log``,
in the same format as for the node and master daemon.

ACCESS CONTROLS
---------------

All query operations are allowed without authentication. Only the
modification operations require authentication, in the form of basic
authentication.

The users and their rights are defined in the
``@LOCALSTATEDIR@/lib/ganeti/rapi/users`` file. The users
should be listed one per line, in the following format::

    username password options

Currently the *options* field should equal the string ``write`` in
order to actually give write permission for the given users. Example::

    rclient   secret    write
    guest     testpw

The first user (*rclient*) has read-write rights, whereas the second
user (*guest*) only has read (query) rights, and as such is no
different than not using authentication at all.

More details (including on how to use hashed passwords) can be found
in the Ganeti documentation.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
