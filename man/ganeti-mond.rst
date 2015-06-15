ganeti-mond(8) Ganeti | Version @GANETI_VERSION@
=================================================

Name
----

ganeti-mond - Ganeti monitoring daemon

Synopsis
--------

**ganeti-mond** [-f] [-d] [-p *PORT*] [-b *ADDRESS*] [--no-user-checks]

DESCRIPTION
-----------

**ganeti-mond** is the daemon providing the Ganeti monitoring
functionality. It is responsible for running the data collectors and to
provide the collected information through a HTTP interface.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

The **ganeti-mond** daemon listens to port 1815 TCP, on all interfaces,
by default. The port can be overridden by an entry the services database
by passing the ``-p`` option.
The ``-b`` option can be used to specify the address to bind to
(defaults to ``0.0.0.0``).
The daemon will refuse to start if the user and group do not match the
one defined at build time; this behaviour can be overridden by the
``--no-user-checks`` option.

COMMUNICATION PROTOCOL
~~~~~~~~~~~~~~~~~~~~~~

The queries to the monitoring agent will be HTTP GET requests on port 1815.
The answer will be encoded in JSON format and will depend on the specific
accessed resource.

If a request is sent to a non-existing resource, a 404 error will be returned by
the HTTP server.

``/``
+++++
The root resource. It will return the list of the supported protocol version
numbers.

``/1/list/collectors``
++++++++++++++++++++++
Returns a list of tuples (kind, category, name) showing all the collectors
available in the system.

``/1/report/all``
+++++++++++++++++
A list of the reports of all the data collectors.

`Status reporting collectors` will provide their output in non-verbose format.
The verbose format can be requested by adding the parameter ``verbose=1`` to the
request.

``/1/report/[category]/[collector_name]``
+++++++++++++++++++++++++++++++++++++++++
Returns the report of the collector ``[collector_name]`` that belongs to the
specified ``[category]``.

If a collector does not belong to any category, ``collector`` will be used as
the value for ``[category]``.

`Status reporting collectors` will provide their output in non-verbose format.
The verbose format can be requested by adding the parameter ``verbose=1`` to the
request.

Further information can be found in the Ganeti Monitoring Agent
design document.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
