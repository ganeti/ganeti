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

**cancel** {*id*}

Cancel the job identified by the given *id*. Only jobs that have
not yet started to run can be canceled; that is, jobs in either the
*queued* or *waiting* state.

INFO
~~~~

**info** {*id*...}

Show detailed information about the given job id(s). If no job id
is given, all jobs are examined (warning, this is a lot of
information).

LIST
~~~~

**list** [\--no-headers] [\--separator=*SEPARATOR*]
[-o *[+]FIELD,...*]

Lists the jobs and their status. By default, the job id, job
status, and a small job description is listed, but additional
parameters can be selected.

The ``--no-headers`` option will skip the initial header line. The
``--separator`` option takes an argument which denotes what will be
used between the output fields. Both these options are to help
scripting.

The ``-o`` option takes a comma-separated list of output fields.
The available fields and their meaning are:



id
    the job id

status
    the status of the job

priority
    current priority of the job

received_ts
    the timestamp the job was received

start_ts
    the timestamp when the job was started

end_ts
    the timestamp when the job was ended

summary
    a summary of the opcodes that define the job

ops
    the list of opcodes defining the job

opresult
    the list of opcode results

opstatus
    the list of opcode statuses

oplog
    the list of opcode logs

opstart
    the list of opcode start times (before acquiring locks)

opexec
    the list of opcode execution start times (after acquiring any
    necessary locks)

opend
    the list of opcode end times

oppriority
    the priority of each opcode


If the value of the option starts with the character ``+``, the new
fields will be added to the default list. This allows one to quickly
see the default list plus a few other fields, instead of retyping
the entire list of fields.

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
