gnt-job(8) Ganeti | Version @GANETI_VERSION@
============================================

Name
----

gnt-job - Job commands

Synopsis
--------

**gnt-job** {command} [arguments...]

DESCRIPTION
-----------

The **gnt-job** is used for examining and manipulating the job
queue.

COMMANDS
--------

ARCHIVE
~~~~~~~

**archive** {id...}

This command can be used to archive job by their IDs. Only jobs
that have finished execution (i.e either *success*, *error* or
*canceled* jobs).

AUTOARCHIVE
~~~~~~~~~~~

**autoarchive** {*age* | ``all``}

Archive jobs by their age. This command can archive jobs older than
*age* seconds, or alternatively all finished jobs can be archived
if the string all is passed.

CANCEL
~~~~~~

| **cancel**
| {[\--force] [\--kill] {\--pending | \--queued | \--waiting} |
|  *job-id* ...}

Cancel the job(s) identified by the given *job id*. Only jobs that have
not yet started to run can be canceled; that is, jobs in either the
*queued* or *waiting* state. To skip a confirmation, pass ``--force``.
``--queued`` and ``waiting`` can be used to cancel all jobs in the
respective state, ``--pending`` includes both.

If the ``--kill`` option is given, jobs will be killed, even if in *running*
state, using SIGKILL in the latter case. This is dangerous, as the job will
not have the chance to do any clean up; so it will most likely leave any
objects it touched in an inconsistent state.

CHANGE-PRIORITY
~~~~~~~~~~~~~~~

| **change-priority** \--priority {low | normal | high}
| {[\--force] {\--pending | \--queued | \--waiting} |
|  *job-id* ...}

Changes the priority of one or multiple pending jobs. Jobs currently
running have only the priority of remaining opcodes changed.
``--priority`` must be specified. ``--queued`` and ``waiting`` can be
used to re-prioritize all jobs in the respective state, ``--pending``
includes both. To skip a confirmation, pass ``--force``.

INFO
~~~~

**info** {*id*...}

Show detailed information about the given job id(s). If no job id
is given, all jobs are examined (warning, this is a lot of
information).

LIST
~~~~

| **list** [\--no-headers] [\--separator=*SEPARATOR*]
| [-o *[+]FIELD,...*] [\--filter] [job-id...]

Lists the jobs and their status. By default, the job id, job
status, and a small job description is listed, but additional
parameters can be selected.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-o`` option takes a comma-separated list of output fields.
The available fields and their meaning are:

@QUERY_FIELDS_JOB@

If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

To include archived jobs in the list the ``--archived`` option can be
used.

The following options can be used to show only specific jobs:

``--pending``
  Show only jobs pending execution.
``--running``
  Show jobs currently running only.
``--error``
  Show failed jobs only.
``--finished``
  Show finished jobs only.

If exactly one argument is given and it appears to be a query filter
(see **ganeti**\(7)), the query result is filtered accordingly. For
ambiguous cases (e.g. a single field name as a filter) the ``--filter``
(``-F``) option forces the argument to be treated as a filter.


LIST-FIELDS
~~~~~~~~~~~

**list-fields** [field...]

Lists available fields for jobs.


WAIT
~~~~~

**wait** {id}

Wait for the job by the given *id* to finish; do not produce
any output.

WATCH
~~~~~

**watch** {id}

This command follows the output of the job by the given *id* and
prints it.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
