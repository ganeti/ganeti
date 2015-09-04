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
  in order of increasing priority. While there
  is a well-defined order in which rules of the same priority are
  evaluated (increasing watermark, then the UUID, are taken as tie
  breakers), it is not recommended to have rules of the same priority
  that overlap and have different actions associated.

- A list of predicates to be matched against the job.

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
    it will be cancelled.
  - CONTINUE. The filtering continues processing with the next
    rule. Such a rule will never have any direct or indirect effect,
    but it can serve as documentation for a "normally present, but
    currently disabled" rule.
  - RATE_LIMIT ``n``, where ``n`` is a positive integer. The job will
    be held in the queue while ``n`` or more jobs where this rule
    applies are running. Jobs that are forked off from luxid are
    considered running. Jobs already running when this rule is added
    are not changed. Logically, this rule is applied job by job
    sequentially, so that the number of jobs where this rule applies
    is limited to ``n`` once the jobs running at rule addition have
    finished.

- A reason trail, in the same format as reason trails for opcodes.
  This allows to find out, which maintenance (or other reason) caused
  the addition of this filter rule.

When a filter rule applies
--------------------------

A filter rule in a filter chain *applies* to a job if it is the first rule
in the chain of which all predicates *match* the job, and if its action is not
CONTINUE.

Filter chains are processed in increasing order of priority (lowest number
means highest priority), then watermark, then UUID.

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

- ``opcode``. Only parameter is a boolean expression. For this expression, ``OP_ID``
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

  {"priority": 0,
   "predicates": [["jobid", [">", "id", "watermark"]]],
   "action": "REJECT"}

Soft draining could be achieved by replacing ``REJECT`` by ``PAUSE`` in the
above example.

Pausing all new jobs not belonging to a specific maintenance.
::

  {"priority": 0,
   "predicates": [["reason", ["=~", "reason", "maintenance pink bunny"]]],
   "action": "ACCEPT"}
  {"priority": 1,
   "predicates": [["jobid", [">", "id", "watermark"]]],
   "action": "PAUSE"}

Cancelling all queued instance creations and disallowing new such jobs.
::

  {"priority": 1,
   "predicates": [["opcode", ["=", "OP_ID", "OP_INSTANCE_CREATE"]]],
   "action": "REJECT"}

Limiting the number of simultaneous instance disk replacements to 10 in order
to throttle replication traffic.
::

  {"priority": 99,
   "predicates": [["opcode", ["=", "OP_ID", "OP_INSTANCE_REPLACE_DISKS"]]],
   "action": ["RATE_LIMIT", 10]}



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


Additional Ad-Hoc Rate Limiting
===============================

Besides a general policy to control the job queue, it is often very
useful to have a lightweight way for one-off rate-limiting. One
example would be evacuating a node but limiting the number of
simultaneous instance moves to no overload the replication network.

Therefore, an additional rate limiting is done over the
:doc:`design-reason-trail` as follows. ``reason`` fields in a reason
3-tuple starting with ``rate-limit:n:`` where ``n`` is a positive
integer are considered rate-limiting buckets. A job belongs to a
rate-limiting bucket if it contains at least one op-code with at least
one reason-trail 3-tuple with that particular ``reason`` field. The
scheduler will ensure that, for each rate-limiting bucket, there are
at most ``n`` jobs belonging to that bucket that are running in
parallel.

The limiting in the initial example can then be done as follows.
::

  # gnt-node evacuate --reason='rate-limit:7:operation pink bunny' node1
