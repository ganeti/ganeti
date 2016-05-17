======================
Query version 2 design
======================

.. contents:: :depth: 4
.. highlight:: python

Current state and shortcomings
==============================

Queries are used to retrieve information about the cluster, e.g. a list
of instances or nodes. For historical reasons they use a simple data
structure for their result. The client submits the fields it would like
to receive and the query returns a list for each item (instance, node,
etc.) available. Each item consists of another list representing the
fields' values.

This data structure has a few drawbacks. It can't associate a status
(e.g. “node offline”) with fields as using special values can lead to
ambiguities. Additionally it can't mark fields as “not found” as the
list of returned columns must match the fields requested.

Example::

  >>> cli.GetClient().QueryNodes([], ["name", "pip", "mfree"], False)
  [
    ['node1.example.com', '192.0.2.18', 14800],
    ['node2.example.com', '192.0.2.19', 31280]
  ]

There is no way for clients to determine the list of possible fields,
meaning they have to be hardcoded. Selecting unknown fields raises
an exception::

  >>> cli.GetClient().QueryNodes([], ["name", "UnknownField"], False)
  ganeti.errors.OpPrereqError: (u'Unknown output fields selected: UnknownField', u'wrong_input')

The client must also know each fields' kind, that is whether a field is
numeric, boolean, describes a storage size, etc. Centralizing this
information in one place, the master daemon, is desirable.


Proposed changes
----------------

The current query result format can not be changed as it's being used in
various places. Changing the format from one Ganeti version to another
would cause too much disruption. For this reason the ability to
explicitly request a new result format must be added while the old
format stays the default.

The implementation of query filters is planned for the future. To avoid
having to change the calls again, a (hopefully) future-compatible
interface will be implemented now.

In Python code, the objects described below will be implemented using
subclasses of ``objects.ConfigObject``, providing existing facilities
for de-/serializing.

Regular expressions
+++++++++++++++++++

As it turned out, only very few fields for instances used regular
expressions, all of which can easily be turned into static field names.
Therefore their use in field names is dropped. Reasons:

- When regexps are used and a field name is not listed as a simple
  string in the field dictionary, all keys in the field dictionary have
  to be checked whether they're a regular expression object and if so,
  matched (see ``utils.FindMatch``).
- Code becomes simpler. There would be no need anymore to care about
  regular expressions as field names—they'd all be simple strings, even
  if there are many more. The list of field names would be static once
  built at module-load time.
- There's the issue of formatting titles for the clients. Should it be
  done in the server? In the client? The field definition's title would
  contain backreferences to the regexp groups in the field name
  (``re.MatchObject.expand`` can be used). With just strings, the field
  definitions can be passed directly to the client. They're static.
- Only a side note: In the memory consumed for 1'000
  ``_sre.SRE_Pattern`` objects (as returned by ``re.compile`` for an
  expression with one group) one can easily store 10'000 strings of the
  same length (the regexp objects keep the expression string around, so
  compiling the expression always uses more memory).


.. _item-types:

Item types
++++++++++

The proposal is to implement this new interface for the following
items:

``instance``
  Instances
``node``
  Nodes
``job``
  Jobs
``lock``
  Locks
``os``
  Operating systems

.. _data-query:

Data query
++++++++++

.. _data-query-request:

Request
^^^^^^^

The request is a dictionary with the following entries:

``what`` (string, required)
  An :ref:`item type <item-types>`.
``fields`` (list of strings, required)
  List of names of fields to return. Example::

    ["name", "mem", "nic0.ip", "disk0.size", "disk1.size"]

``filter`` (optional)
  This will be used to filter queries. In this implementation only names
  can be filtered to replace the previous ``names`` parameter to
  queries. An empty filter (``None``) will return all items. To retrieve
  specific names, the filter must be specified as follows, with the
  inner part repeated for each name::

    ["|", ["=", "name", "node1"], ["=", "name", "node2"], …]

  Filters consist of S-expressions (``["operator", <operands…>]``) and
  extensions will be made in the future to allow for more operators and
  fields. Such extensions might include a Python-style "in" operator,
  but for simplicity only "=" is supported in this implementation.

  To reiterate: Filters for this implementation must consist of exactly
  one OR expression (``["|", …]``) and one or more name equality filters
  (``["=", "name", "…"]``).

Support for synchronous queries, currently available in the interface
but disabled in the master daemon, will be dropped. Direct calls to
opcodes have to be used instead.

.. _data-query-response:

Response
^^^^^^^^

The result is a dictionary with the following entries:

``fields`` (list of :ref:`field definitions <field-def>`)
  In-order list of a :ref:`field definition <field-def>` for each
  requested field, unknown fields are returned with the kind
  ``unknown``. Length must be equal to number of requested fields.
``data`` (list of lists of tuples)
  List of lists, one list for each item found. Each item's list must
  have one entry for each field listed in ``fields`` (meaning their
  length is equal). Each field entry is a tuple of ``(status, value)``.
  ``status`` must be one of the following values:

  Normal (numeric 0)
    Value is available and matches the kind in the :ref:`field
    definition <field-def>`.
  Unknown field (numeric 1)
    Field for this column is not known. Value must be ``None``.
  No data (numeric 2)
    Exact meaning depends on query, e.g. node is unreachable or marked
    offline. Value must be ``None``.
  Value unavailable for item (numeric 3)
    Used if, for example, NIC 3 is requested for an instance with only
    one network interface. Value must be ``None``.
  Resource offline (numeric 4)
    Used if resource is marked offline. Value must be ``None``.

Example response after requesting the fields ``name``, ``mfree``,
``xyz``, ``mtotal``, ``nic0.ip``, ``nic1.ip`` and ``nic2.ip``::

  {
    "fields": [
      { "name": "name", "title": "Name", "kind": "text", },
      { "name": "mfree", "title": "MemFree", "kind": "unit", },
      # Unknown field
      { "name": "xyz", "title": None, "kind": "unknown", },
      { "name": "mtotal", "title": "MemTotal", "kind": "unit", },
      { "name": "nic0.ip", "title": "Nic.IP/0", "kind": "text", },
      { "name": "nic1.ip", "title": "Nic.IP/1", "kind": "text", },
      { "name": "nic2.ip", "title": "Nic.IP/2", "kind": "text", },
      ],

    "data": [
      [(0, "node1"), (0, 128), (1, None), (0, 4096),
       (0, "192.0.2.1"), (0, "192.0.2.2"), (3, None)],
      [(0, "node2"), (0, 96), (1, None), (0, 5000),
       (0, "192.0.2.21"), (0, "192.0.2.39"), (3, "192.0.2.90")],
      # Node not available, can't get "mfree" or "mtotal"
      [(0, "node3"), (2, None), (1, None), (2, None),
       (0, "192.0.2.30"), (3, None), (3, None)],
      ],
  }

.. _fields-query:

Fields query
++++++++++++

.. _fields-query-request:

Request
^^^^^^^

The request is a dictionary with the following entries:

``what`` (string, required)
  An :ref:`item type <item-types>`.
``fields`` (list of strings, optional)
  List of names of fields to return. If not set, all fields are
  returned. Example::

    ["name", "mem", "nic0.ip", "disk0.size", "disk1.size"]

.. _fields-query-response:

Response
^^^^^^^^

The result is a dictionary with the following entries:

``fields`` (list of :ref:`field definitions <field-def>`)
  List of a :ref:`field definition <field-def>` for each field. If
  ``fields`` was set in the request and contained an unknown field, it
  is returned as type ``unknown``.

Example::

  {
    "fields": [
      { "name": "name", "title": "Name", "kind": "text", },
      { "name": "mfree", "title": "MemFree", "kind": "unit", },
      { "name": "mtotal", "title": "MemTotal", "kind": "unit", },
      { "name": "nic0.ip", "title": "Nic.IP/0", "kind": "text", },
      { "name": "nic1.ip", "title": "Nic.IP/1", "kind": "text", },
      { "name": "nic2.ip", "title": "Nic.IP/2", "kind": "text", },
      { "name": "nic3.ip", "title": "Nic.IP/3", "kind": "text", },
      # …
      { "name": "disk0.size", "title": "Disk.Size/0", "kind": "unit", },
      { "name": "disk1.size", "title": "Disk.Size/1", "kind": "unit", },
      { "name": "disk2.size", "title": "Disk.Size/2", "kind": "unit", },
      { "name": "disk3.size", "title": "Disk.Size/3", "kind": "unit", },
      # …
      ]
  }

.. _field-def:

Field definition
++++++++++++++++

A field definition is a dictionary with the following entries:

``name`` (string)
  Field name. Must only contain characters matching ``[a-z0-9/._]``.
``title`` (string)
  Human-readable title to use in output. Must not contain whitespace.
``kind`` (string)
  Field type, one of the following:

  ``unknown``
    Unknown field
  ``text``
    String
  ``bool``
    Boolean, true/false
  ``number``
    Numeric
  ``unit``
    Numeric, in megabytes
  ``timestamp``
    Unix timestamp in seconds since the epoch
  ``other``
    Free-form type, depending on query

  More types can be added in the future, so clients should default to
  formatting any unknown types the same way as "other", which should be
  a string representation in most cases.

``doc`` (string)
  Human-readable description. Must start with uppercase character and
  must not end with punctuation or contain newlines.

.. TODO: Investigate whether there are fields with floating point
.. numbers

Example 1 (item name)::

  {
    "name": "name",
    "title": "Name",
    "kind": "text",
  }

Example 2 (free memory)::

  {
    "name": "mfree",
    "title": "MemFree",
    "kind": "unit",
  }

Example 3 (list of primary instances)::

  {
    "name": "pinst",
    "title": "PrimaryInstances",
    "kind": "other",
  }

.. _old-result-format:

Old result format
+++++++++++++++++

To limit the amount of code necessary, the :ref:`new result format
<data-query-response>` will be converted for clients calling the old
methods.  Unavailable values are set to ``None``. If unknown fields were
requested, the whole query fails as the client expects exactly the
fields it requested.

.. _query2-luxi:

LUXI
++++

Currently query calls take a number of parameters, e.g. names, fields
and whether to use locking. These will continue to work and return the
:ref:`old result format <old-result-format>`. Only clients using the
new calls described below will be able to make use of new features such
as filters. Two new calls are introduced:

``Query``
  Execute a query on items, optionally filtered. Takes a single
  parameter, a :ref:`query object <data-query-request>` encoded as a
  dictionary and returns a :ref:`data query response
  <data-query-response>`.
``QueryFields``
  Return list of supported fields as :ref:`field definitions
  <field-def>`. Takes a single parameter, a :ref:`fields query object
  <fields-query-request>` encoded as a dictionary and returns a
  :ref:`fields query response <fields-query-response>`.


Python
++++++

The LUXI API is more or less mapped directly into Python. In addition to
the existing stub functions new ones will be added for the new query
requests.

RAPI
++++

The RAPI interface already returns dictionaries for each item, but to
not break compatibility no changes should be made to the structure (e.g.
to include field definitions). The proposal here is to add a new
parameter to allow clients to execute the requests described in this
proposal directly and to receive the unmodified result. The new formats
are a lot more verbose, flexible and extensible.

.. _cli-programs:

CLI programs
++++++++++++

Command line programs might have difficulties to display the verbose
status data to the user. There are several options:

- Use colours to indicate missing values
- Display status as value in parentheses, e.g. "(unavailable)"
- Hide unknown columns from the result table and print a warning
- Exit with non-zero code to indicate failures and/or missing data

Some are better for interactive usage, some better for use by other
programs. It is expected that a combination will be used. The column
separator (``--separator=…``) can be used to differentiate between
interactive and programmatic usage.


Other discussed solutions
-------------------------

Another solution discussed was to add an additional column for each
non-static field containing the status. Clients interested in the status
could explicitly query for it.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
