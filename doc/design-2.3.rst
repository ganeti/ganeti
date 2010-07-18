=================
Ganeti 2.3 design
=================

This document describes the major changes in Ganeti 2.3 compared to
the 2.2 version.

.. contents:: :depth: 4

Detailed design
===============

As for 2.1 and 2.2 we divide the 2.3 design into three areas:

- core changes, which affect the master daemon/job queue/locking or
  all/most logical units
- logical unit/feature changes
- external interface changes (eg. command line, os api, hooks, ...)

Core changes
------------

Job priorities
~~~~~~~~~~~~~~

Current state and shortcomings
++++++++++++++++++++++++++++++

.. TODO: Describe current situation

Proposed changes
++++++++++++++++

.. TODO: Describe changes to job queue and potentially client programs

Worker pool
^^^^^^^^^^^

To support job priorities in the job queue, the worker pool underlying
the job queue must be enhanced to support task priorities. Currently
tasks are processed in the order they are added to the queue (but, due
to their nature, they don't necessarily finish in that order). All tasks
are equal. To support tasks with higher or lower priority, a few changes
have to be made to the queue inside a worker pool.

Each task is assigned a priority when added to the queue. This priority
can not be changed until the task is executed (this is fine as in all
current use-cases, tasks are added to a pool and then forgotten about
until they're done).

A task's priority can be compared to Unix' process priorities. The lower
the priority number, the closer to the queue's front it is. A task with
priority 0 is going to be run before one with priority 10. Tasks with
the same priority are executed in the order in which they were added.

While a task is running it can query its own priority. If it's not ready
yet for finishing, it can raise an exception to defer itself, optionally
changing its own priority. This is useful for the following cases:

- A task is trying to acquire locks, but those locks are still held by
  other tasks. By deferring itself, the task gives others a chance to
  run. This is especially useful when all workers are busy.
- If a task decides it hasn't gotten its locks in a long time, it can
  start to increase its own priority.
- Tasks waiting for long-running operations running asynchronously could
  defer themselves while waiting for a long-running operation.

With these changes, the job queue will be able to implement per-job
priorities.


Feature changes
---------------


External interface changes
--------------------------


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
