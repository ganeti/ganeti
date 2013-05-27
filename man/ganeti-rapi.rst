ganeti-rapi(8) Ganeti | Version @GANETI_VERSION@
================================================

Name
----

ganeti-rapi - Ganeti remote API daemon

Synopsis
--------

| **ganeti-rapi** [-d] [-f] [-p *PORT] [-b *ADDRESS*] [-i *INTERFACE*]
| [\--no-ssl] [-K *SSL_KEY_FILE*] [-C *SSL_CERT_FILE*]
| [\--require-authentication]

DESCRIPTION
-----------

**ganeti-rapi** is the daemon providing a remote API for Ganeti
clusters.

It is automatically started on the master node, and by default it
uses SSL encryption. This can be disabled by passing the
``--no-ssl`` option, or alternatively the certificate used can be
changed via the ``-C`` option and the key via the ``-K`` option.

The daemon will listen to the "ganeti-rapi" TCP port, as listed in the
system services database, or if not defined, to port 5080 by default.
The port can be overridded by passing the ``-p`` option. The ``-b``
option can be used to specify the address to bind to (defaults to
``0.0.0.0``); alternatively, the ``-i`` option can be used to specify
the interface to bind do.

See the *Ganeti remote API* documentation for further information.

Requests are logged to ``@LOCALSTATEDIR@/log/ganeti/rapi-daemon.log``,
in the same format as for the node and master daemon.

ACCESS CONTROLS
---------------

Most query operations are allowed without authentication. Only the
modification operations require authentication, in the form of basic
authentication. Specify the ``--require-authentication`` command line
flag to always require authentication.

The users and their rights are defined in the
``@LOCALSTATEDIR@/lib/ganeti/rapi/users`` file. The format of this file
is described in the Ganeti documentation (``rapi.html``).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
