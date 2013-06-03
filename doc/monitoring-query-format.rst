The queries to the monitoring agent will be HTTP GET requests on port 1815.
The answer will be encoded in JSON format and will depend on the specific
accessed resource.

If a request is sent to a non-existing resource, a 404 error will be returned by
the HTTP server.

The following paragraphs will present the existing resources supported by the
current protocol version, that is version 1.

``/``
+++++
The root resource. It will return the list of the supported protocol version
numbers.

Currently, this will include only version 1.

``/1``
++++++
Not an actual resource per-se, it is the root of all the resources of protocol
version 1.

If requested through GET, the null JSON value will be returned.

``/1/list/collectors``
++++++++++++++++++++++
Returns a list of tuples (kind, category, name) showing all the collectors
available in the system.

``/1/report/all``
+++++++++++++++++
A list of the reports of all the data collectors, as a JSON list.

Status reporting collectors will provide their output in non-verbose format.
The verbose format can be requested by adding the parameter ``verbose=1`` to the
request.

``/1/report/[category]/[collector_name]``
+++++++++++++++++++++++++++++++++++++++++
Returns the report of the collector ``[collector_name]`` that belongs to the
specified ``[category]``.

The ``category`` has to be written in lowercase.

If a collector does not belong to any category, ``default`` will have to be
used as the value for ``[category]``.

Status reporting collectors will provide their output in non-verbose format.
The verbose format can be requested by adding the parameter ``verbose=1`` to the
request.
