============
Chained jobs
============

.. contents:: :depth: 4

This is a design document about the innards of Ganeti's job processing.
Readers are advised to study previous design documents on the topic:

- :ref:`Original job queue <jqueue-original-design>`
- :ref:`Job priorities <jqueue-job-priority-design>`
- :doc:`LU-generated jobs <design-lu-generated-jobs>`


Current state and shortcomings
==============================

Ever since the introduction of the job queue with Ganeti 2.0 there have
been situations where we wanted to run several jobs in a specific order.
Due to the job queue's current design, such a guarantee can not be
given. Jobs are run according to their priority, their ability to
acquire all necessary locks and other factors.

One way to work around this limitation is to do some kind of job
grouping in the client code. Once all jobs of a group have finished, the
next group is submitted and waited for. There are different kinds of
clients for Ganeti, some of which don't share code (e.g. Python clients
vs. htools). This design proposes a solution which would be implemented
as part of the job queue in the master daemon.


Proposed changes
================

With the implementation of :ref:`job priorities
<jqueue-job-priority-design>` the processing code was re-architectured
and became a lot more versatile. It now returns jobs to the queue in
case the locks for an opcode can't be acquired, allowing other
jobs/opcodes to be run in the meantime.

The proposal is to add a new, optional property to opcodes to define
dependencies on other jobs. Job X could define opcodes with a dependency
on the success of job Y and would only be run once job Y is finished. If
there's a dependency on success and job Y failed, job X would fail as
well. Since such dependencies would use job IDs, the jobs still need to
be submitted in the right order.

.. pyassert::

   # Update description below if finalized job status change
   constants.JOBS_FINALIZED == frozenset([
     constants.JOB_STATUS_CANCELED,
     constants.JOB_STATUS_SUCCESS,
     constants.JOB_STATUS_ERROR,
     ])

The new attribute's value would be a list of two-valued tuples. Each
tuple contains a job ID and a list of requested status for the job
depended upon. Only final status are accepted
(:pyeval:`utils.CommaJoin(constants.JOBS_FINALIZED)`). An empty list is
equivalent to specifying all final status (except
:pyeval:`constants.JOB_STATUS_CANCELED`, which is treated specially).
An opcode runs only once all its dependency requirements have been
fulfilled.

Any job referring to a cancelled job is also cancelled unless it
explicitely lists :pyeval:`constants.JOB_STATUS_CANCELED` as a requested
status.

In case a referenced job can not be found in the normal queue or the
archive, referring jobs fail as the status of the referenced job can't
be determined.

With this change, clients can submit all wanted jobs in the right order
and proceed to wait for changes on all these jobs (see
``cli.JobExecutor``). The master daemon will take care of executing them
in the right order, while still presenting the client with a simple
interface.

Clients using the ``SubmitManyJobs`` interface can use relative job IDs
(negative integers) to refer to jobs in the same submission.

.. highlight:: javascript

Example data structures::

  # First job
  {
    "job_id": "6151",
    "ops": [
      { "OP_ID": "OP_INSTANCE_REPLACE_DISKS", ..., },
      { "OP_ID": "OP_INSTANCE_FAILOVER", ..., },
      ],
  }

  # Second job, runs in parallel with first job
  {
    "job_id": "7687",
    "ops": [
      { "OP_ID": "OP_INSTANCE_MIGRATE", ..., },
      ],
  }

  # Third job, depending on success of previous jobs
  {
    "job_id": "9218",
    "ops": [
      { "OP_ID": "OP_NODE_SET_PARAMS",
        "depend": [
          [6151, ["success"]],
          [7687, ["success"]],
          ],
        "offline": True, },
      ],
  }


Other discussed solutions
=========================

Job-level attribute
-------------------

At a first look it might seem to be better to put dependencies on
previous jobs at a job level. However, it turns out that having the
option of defining only a single opcode in a job as having such a
dependency can be useful as well. The code complexity in the job queue
is equivalent if not simpler.

Since opcodes are guaranteed to run in order, clients can just define
the dependency on the first opcode.

Another reason for the choice of an opcode-level attribute is that the
current LUXI interface for submitting jobs is a bit restricted and would
need to be changed to allow the addition of job-level attributes,
potentially requiring changes in all LUXI clients and/or breaking
backwards compatibility.


Client-side logic
-----------------

There's at least one implementation of a batched job executor twisted
into the ``burnin`` tool's code. While certainly possible, a client-side
solution should be avoided due to the different clients already in use.
For one, the :doc:`remote API <rapi>` client shouldn't import
non-standard modules. htools are written in Haskell and can't use Python
modules. A batched job executor contains quite some logic. Even if
cleanly abstracted in a (Python) library, sharing code between different
clients is difficult if not impossible.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
