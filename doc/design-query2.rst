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

.. _query-request:

Query request
+++++++++++++

Each query operation will take a single parameter, a query request
dictionary with the following properties:

``kind``
  Denotes request kind. One of the following strings:

  ``query``
    Execute a query on items, optionally filtered (see below). For a
    description of the result see :ref:`query-result`.
  ``fields``
    Return list of supported fields as :ref:`field definitions
    <field-def>`. For a complete description of the result see
    :ref:`fields-result`.

``filter``
  This will be used to filter queries. In this implementation only names
  can be filtered to replace the previous ``names`` parameter to
  queries. An empty filter (``None``) will return all items. To retrieve
  specific names, the filter must be specified as follows, with the
  inner part repeated for each name::

    ["|", ["=", "name", "node1"], ["=", "name", "node2"], …]

  Filters consist of S-expressions (``["operator", <operants…>]``) and
  extensions will be made in the future to allow for more operators and
  fields. Such extensions might include a Python-style "in" operator,
  but for simplicity only "=" is supported in this implementation.

  To reiterate: Filters for this implementation must consist of exactly
  one OR expression (``["|", …]``) and one or more name equality filters
  (``["=", "name", "…"]``).

Support for synchronous queries, currently available in the interface
but disabled in the master daemon, will be dropped. Direct calls to
opcodes have to be used instead.

.. _query-result:

New query result format
+++++++++++++++++++++++

The result is a dictionary with the following entries:

``fields``
  In-order list of a :ref:`field definition <field-def>` for each
  requested field, unknown fields are returned with the kind
  ``unknown``. Length must be equal to number of requested fields.
``data``
  A list of lists, one list for each item found. Each item's list must
  have one entry for each field listed in ``fields``. Each field entry
  is a tuple of ``(status, value)``. ``status`` must be one of the
  following values:

  Normal (numeric 0)
    Value is available and matches the kind in the :ref:`field
    definition <field-def>`.
  Value unavailable (numeric 1)
    Exact meaning depends on query, e.g. node is unreachable or marked
    offline. Value must be ``None``.
  Unknown field (numeric 2)
    Field for this column is not known. Value must be ``None``.

Example::

  {
    "fields": [
      { "name": "name", "title": "Name", "kind": "text", },
      { "name": "mfree", "title": "MemFree", "kind": "unit", },
      # Unknown field
      { "name": "xyz", "title": None, "kind": "unknown", },
      { "name": "mtotal", "title": "MemTotal", "kind": "unit", },
      ],

    "data": [
      [(0, "node1"), (0, 128), (2, None), (0, 4096)],
      # Node not available
      [(0, "node2"), (1, None), (2, None), (1, None)],
      ],
  }

.. _fields-result:

Field query result format
+++++++++++++++++++++++++

The result is a dictionary with the following entries:

``fields``
  List of :ref:`field definitions <field-def>` for each available field.

Example::

  {
    "fields": [
      { "name": "name", "title": "Name", "kind": "text", },
      { "name": "mfree", "title": "MemFree", "kind": "unit", },
      { "name": "mtotal", "title": "MemTotal", "kind": "unit", },
      ]
  }

.. _field-def:

Field definition
++++++++++++++++

A field definition is a dictionary with the following entries:

``name``
  The field name as a regular expression. The latter is necessary to
  represent dynamic fields (e.g. NIC 3 of an instance).
``title``
  Human-readable title to use in output. Must not contain whitespace.
``kind``
  Field type, one of the following:

.. TODO: Investigate whether there are fields with floating point
.. numbers

  ``unknown``
    Unknown field (only used for :ref:`data queries <query-request>`)
  ``text``
    String
  ``bool``
    Boolean, true/false
  ``number``
    Numeric
  ``unit``
    Numeric, in megabytes
  ``other``
    Free-form type, depending on query

  More types can be added in the future, so clients should default to
  formatting any unknown types the same way as "other", which should be
  a string representation in most cases.

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
<query-result>` will be converted for older clients. Unavailable values
are set to ``None``. If unknown fields were requested, the whole query
fails as the client expects exactly the fields it requested.

LUXI
++++

Currently query calls take a number of parameters, e.g. names, fields
and whether to use locking. These will continue to work and return the
:ref:`old result format <old-result-format>`. To use the new query
requests, the same calls must be invoked with a single parameter as the
:ref:`query object <query-request>`. Only clients using the new call
syntax will be able to make use of new features such as filters.

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


Other discussed solutions
-------------------------

Another solution discussed was to add an additional column for each
non-static field containing the status. Clients interested in the status
could explicitely query for it.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
