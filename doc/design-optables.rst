==========================================
Filtering of jobs for the Ganeti job queue
==========================================

.. contents:: :depth: 4

This is a design document detailing the semantics of the fine-grained control
of jobs in Ganeti. For the implementation there will be a separate
design document that also describes the vision for the Ganeti daemon
structure.


Current state and shortcomings
==============================

Control of the Ganeti job queue is quite limited. There is a single
status bit, the "drained flag". If set, no new jobs are accepted to
the queue. This is too coarse for some use cases.

- The queue might be required to be drained for several reasons,
  initiated by different persons or automatic programs. Each one
  should be able to indicate that his reasons for draining are over
  without affecting the others.

- There is no support for partial drains. For example, one might want
  to allow all jobs belonging to a manual (or externally coordinated)
  maintenance, while disallowing all other jobs.

- There is no support for blocking jobs by their op-codes, e.g.,
  disallowing all jobs that bring new instances to a cluster. This might
  be part of a maintenance preparation.

- There is no support for a soft version of draining, where all
  jobs currently in the queue are finished, while new jobs entering
  the queue are delayed until the drain is over.


Proposed changes
================

We propose to add filters on the job queue. These will be part of the
configuration and as such are persisted with it. Conceptionally, the
filters are always processed when a job enters the queue and while it
is still in the queue. Of course, in the implementation, reevaluation
is only carried out, if something could make the result change, e.g.,
a new job is entered to the queue, or the filter rules are changed.
There is no distinction between filter processing when a job is about
to enter the queue and while it is in the queue, as this can be
expressed by the filter rules themselves (see predicates below).

Format of a Filter rule
-----------------------

Filter rules are given by the following data.

- A UUID. This ensures that there can be different filter rules
  that otherwise have all parameters equal. In this way, multiple
  drains for different reasons are possible. The UUID is used to
  address the filter rule, in particular for deletion.

  If no UUID is provided at rule addition, Ganeti will create one.

- The watermark. This is the highest job id ever used, as valid in
  the moment when the filter was added. This data will be added
  automatically upon addition of the filter.

- A priority. This is a non-negative integer. Filters are processed
  in order of increasing priority until a rule applies. While there
  is a well-defined order in which rules of the same priority are
  evaluated (increasing watermark, then the uuid, are taken as tie
  breakers), it is not recommended to have rules of the same priority
  that overlap and have different actions associated.

- A list of predicates. The rule fires, if all of them hold true
  for the job.

- An action. For the time being, one of the following, but more
  actions might be added in the future (in particular, future
  implementations might add an action making filtering continue with
  a different filter chain).

  - ACCEPT. The job will be accepted; no further filter rules
    are applied.
  - PAUSE. The job will be accepted to the queue and remain there;
    however, it is not executed. If an opcode is currently running,
    it continues, but the next opcode will not be started. For a paused
    job all locks it might have acquired will be released as soon as
    possible, at the latest when the currently running opcode has
    finished. The job queue will take care of this.
  - REJECT. The job is rejected. If it is already in the queue,
    it will be marked as cancelled.
  - CONTINUE. The filtering continues processing with the next
    rule. Such a rule will never have any direct or indirect effect,
    but it can serve as documentation for a "normally present, but
    currently disabled" rule.

- A reason trail, in the same format as reason trails for opcodes. 
  This allows to find out, which maintenance (or other reason) caused
  the addition of this filter rule.

Predicates available for the filter rules
-----------------------------------------

A predicate is a list, with the first element being the name of the
predicate and the rest being parameters suitable for that predicate.
In most cases, the name of the predicate will be a field of a job,
and there will be a single parameter, which is a boolean expression
(``filter``) in the sense
of the Ganeti query language. However, no assumption should be made
that all predicates are of this shape. More predicates may be added
in the future.

- ``jobid``. Only parameter is a boolean expression. For this expression,
  there is only one field available, ``id``, which represents the id the job to be
  filtered. In all value positions, the string ``watermark`` will be
  replaced by the value of the watermark.

- ``opcode``. Only parameter is boolean expresion. For this expression, ``OP_ID``
  and all other fields present in the opcode are available. This predicate
  will hold true, if the expression is true for at least one opcode in
  the job.

- ``reason``. Only parameter is a boolean expression. For this expression, the three
  fields ``source``, ``reason``, ``timestamp`` of reason trail entries
  are available. This predicate is true, if one of the entries of one
  of the opcodes in this job satisfies the expression.


Examples
========

Draining the queue.
::

   {'priority': 0,
    'predicates': [['jobid', ['>', 'id', 'watermark']]],
    'action': 'REJECT'}

Soft draining could be achieved by replacing ``REJECT`` by ``PAUSE`` in the
above example.

Pausing all new jobs not belonging to a specific maintenance.
::

   {'priority': 1,
    'predicates': [['jobid', ['>', 'id', 'watermark']],
                   ['reason', ['!', ['=~', 'reason', 'maintenance pink bunny']]]],
    'action': 'PAUSE'}

Canceling all queued instance creations and disallowing new such jobs.
::

  {'priority': 1,
   'predicates': [['opcode', ['=', 'OP_ID', 'OP_INSTANCE_CREATE']]],
   'action': 'REJECT'}



Interface
=========

Since queue control is intended to be used by external maintenance-handling
tools as well, the primary interface for manipulating queue filters is the
:doc:`rapi`. For convenience, a command-line interface will be added as well.

The following resources will be added.

- /2/filters/

  - GET returns the list of all currently set filters

  - POST adds a new filter

- /2/filters/[uuid]

  - GET returns the description of the specified filter

  - DELETE removes the specified filter

  - PUT replaces the specified filter rule, or creates it,
    if it doesn't exist already.

Security considerations
=======================

Filtering of jobs is not a security feature. It merely serves the purpose
of coordinating efforts and avoiding accidental conflicting
jobs. Everybody with appropriate credentials can modify the filter
rules, not just the originator of a rule. To avoid accidental
lock-out, requests modifying the queue are executed directly and not
going through the queue themselves.
