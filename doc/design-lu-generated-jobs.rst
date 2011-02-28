==================================
Submitting jobs from logical units
==================================

.. contents:: :depth: 4

This is a design document about the innards of Ganeti's job processing.
Readers are advised to study previous design documents on the topic:

- :ref:`Original job queue <jqueue-original-design>`
- :ref:`Job priorities <jqueue-job-priority-design>`


Current state and shortcomings
==============================

Some Ganeti operations want to execute as many operations in parallel as
possible. Examples are evacuating or failing over a node (``gnt-node
evacuate``/``gnt-node failover``). Without changing large parts of the
code, e.g. the RPC layer, to be asynchronous, or using threads inside a
logical unit, only a single operation can be executed at a time per job.

Currently clients work around this limitation by retrieving the list of
desired targets and then re-submitting a number of jobs. This requires
logic to be kept in the client, in some cases leading to duplication
(e.g. CLI and RAPI).


Proposed changes
================

The job queue lock is guaranteed to be released while executing an
opcode/logical unit. This means an opcode can talk to the job queue and
submit more jobs. It then receives the job IDs, like any job submitter
using the LUXI interface would. These job IDs are returned to the
client, who then will then proceed to wait for the jobs to finish.

Technically, the job queue already passes a number of callbacks to the
opcode processor. These are used for giving user feedback, notifying the
job queue of an opcode having gotten its locks, and checking whether the
opcode has been cancelled. A new callback function is added to submit
jobs. Its signature and result will be equivalent to the job queue's
existing ``SubmitManyJobs`` function.

Logical units can submit jobs by returning an instance of a special
container class with a list of jobs, each of which is a list of opcodes
(e.g.  ``[[op1, op2], [op3]]``). The opcode processor will recognize
instances of the special class when used a return value and will submit
the contained jobs. The submission status and job IDs returned by the
submission callback are used as the opcode's result. It should be
encapsulated in a dictionary allowing for future extensions.

.. highlight:: javascript

Example::

  {
    "jobs": [
      (True, "8149"),
      (True, "21019"),
      (False, "Submission failed"),
      (True, "31594"),
      ],
  }

Job submissions can fail for variety of reasons, e.g. a full or drained
job queue. Lists of jobs can not be submitted atomically, meaning some
might fail while others succeed. The client is responsible for handling
such cases.


Other discussed solutions
=========================

Instead of requiring the client to wait for the returned jobs, another
idea was to do so from within the submitting opcode in the master
daemon. While technically possible, doing so would have two major
drawbacks:

- Opcodes waiting for other jobs to finish block one job queue worker
  thread
- All locks must be released before starting the waiting process,
  failure to do so can lead to deadlocks

Instead of returning the job IDs as part of the normal opcode result,
introducing a new opcode field, e.g. ``op_jobids``, was discussed and
dismissed. A new field would touch many areas and possibly break some
assumptions. There were also questions about the semantics.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
