gnt-filter(8) Ganeti | Version @GANETI_VERSION@
===============================================

Name
----

gnt-filter - Ganeti job filter rule administration

Synopsis
--------

**gnt-filter** {command} [options...] [arguments...]

DESCRIPTION
-----------

The **gnt-filter** command is used for managing job filter rules in the
Ganeti system. Filter rules are used by the Ganeti job scheduler to
determine which jobs should be accepted, rejected, paused or
rate-limited.

Filter rules consist of the following:

- A ``UUID``, used to refer to existing filters.

- A ``watermark``. This is the highest job id ever used, as valid in
  the moment when the filter was added or replaced.

- A ``priority``. This is a non-negative integer. Filters are processed
  in order of increasing priority. While there
  is a well-defined order in which rules of the same priority are
  evaluated (increasing watermark, then the UUID, are taken as tie
  breakers), it is not recommended to have rules of the same priority
  that overlap and have different actions associated.

- A list of ``predicates`` to be matched against the job.

  A predicate is a list, with the first element being the name of the
  predicate and the rest being parameters suitable for that predicate.
  Most predicates take a single parameter, which is a boolean expression
  formulated in the of the Ganeti query language.
  The currently supported predicate names are:

  - ``jobid``. Only parameter is a boolean expression.
    For this expression, there is only one field available, ``id``,
    which represents the id the job to be filtered.
    In all value positions, the string ``watermark`` is replaced by
    the value of the watermark of the filter rule.

  - ``opcode``. Only parameter is a boolean expression.
    For this expression, ``OP_ID`` and all other fields present in the
    opcode are available. This predicate will hold true, if the
    expression is true for at least one opcode in the job.

  - ``reason``. Only parameter is a boolean expression.
    For this expression, the three fields ``source``, ``reason``,
    ``timestamp`` of reason trail entries are available.
    This predicate is true, if one of the entries of one of the opcodes
    in this job satisfies the expression.

- An ``action``. One of:

  - ACCEPT. The job will be accepted; no further filter rules
    are applied.
  - PAUSE. The job will be accepted to the queue and remain there;
    however, it is not executed.
    Has no effect if the job is already running.
  - REJECT. The job is rejected. If it is already in the queue,
    it will be cancelled.
  - CONTINUE. The filtering continues processing with the next
    rule. Such a rule will never have any direct or indirect effect,
    but it can serve as documentation for a "normally present, but
    currently disabled" rule.
  - RATE_LIMIT ``n``, where ``n`` is a positive integer. The job will
    be held in the queue while ``n`` or more jobs where this rule
    applies are running. Jobs already running when this rule is added
    are not changed. Logically, this rule is applied job by job
    sequentially, so that the number of jobs where this rule applies
    is limited to ``n`` once the jobs running at rule addition have
    finished.

- A reason trail, in the same format as reason trails for job opcodes
  (see the ``--reason`` option in **ganeti**\(7)).
  This allows to find out which maintenance (or other reason) caused
  the addition of this filter rule.

COMMANDS
--------

ADD
~~~

| **add**
| [\--priority=*PRIORITY*]
| [\--predicates=*PREDICATES*]
| [\--action=*ACTION*]

Creates a new filter rule. A UUID is automatically assigned.

The ``--priority`` option sets the priority of the filter.
It is a non-negative integer.
Default: 0 (the highest possible priority).

The ``--predicates`` option sets the predicates of the filter.
It is a list of predicates in the format described in the
**DESCRIPTION** above.
Default: [] (no predicate, filter always matches).

The ``--action`` option sets the action of the filter.
It is one of the strings ``ACCEPT``, ``PAUSE``, ``REJECT``,
``CONTINUE``, or ``RATE_LIMIT n`` (see the **DESCRIPTION** above).
Default: ``CONTINUE``.

See **ganeti**\(7) for a description of ``--reason`` and other common
options.

REPLACE
~~~~~~~

| **replace**
| [\--priority=*PRIORITY*]
| [\--predicates=*PREDICATES*]
| [\--action=*ACTION*]
| [\--reason=*REASON*]
| {*filter_uuid*}

Replaces a filter rule, or creates one if it doesn't already exist.

Accepts all options described above in ``ADD``.

When being replaced, the filter will be assigned an updated watermark.

See **ganeti**\(7) for a description of ``--reason`` and other common
options.

DELETE
~~~~~~

| **delete** {*filter_uuid*}

Deletes the indicated filter rule.

LIST
~~~~

| **list** [\--no-headers] [\--separator=*SEPARATOR*] [-v]
| [-o *[+]FIELD,...*] [filter_uuid...]

Lists all existing filters in the cluster. If no filter UUIDs are given,
then all filters are included. Otherwise, only the given filters will be
listed.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be used
between the output fields. Both these options are to help scripting.

The ``-v`` option activates verbose mode, which changes the display of
special field states (see **ganeti**\(7)).

The ``-o`` option takes a comma-separated list of output fields. If the
value of the option starts with the character ``+``, the new fields will
be added to the default list. This allows to quickly see the default
list plus a few other fields, instead of retyping the entire list of
fields.

The available fields and their meaning are:

@QUERY_FIELDS_FILTER@

LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

List available fields for filters.

INFO
~~~~

| **info** [filter_uuid...]

Displays information about a given filter.


EXAMPLES
--------

Draining the queue.
::

  gnt-filter add '--predicates=[["jobid", [">", "id", "watermark"]]]' --action=REJECT

Soft draining could be achieved by replacing ``REJECT`` by ``PAUSE`` in
the above example.


Pausing all new jobs not belonging to a specific maintenance.
::

  gnt-filter add --priority=0 '--predicates=[["reason", ["=~", "reason", "maintenance pink bunny"]]]' --action=ACCEPT
  gnt-filter add --priority=1 '--predicates=[["jobid", [">", "id", "watermark"]]]' --action=PAUSE


Cancelling all queued instance creations and disallowing new such jobs.
::

  gnt-filter add '--predicates=[["opcode", ["=", "OP_ID", "OP_INSTANCE_CREATE"]]]' --action=REJECT


Limiting the number of simultaneous instance disk replacements to 10 in
order to throttle replication traffic.
::

  gnt-filter add '--predicates=[["opcode", ["=", "OP_ID", "OP_INSTANCE_REPLACE_DISKS"]]]' '--action=RATE_LIMIT 10'

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
