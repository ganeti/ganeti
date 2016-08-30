==================================
Predictive Queue System for Ganeti
==================================

.. contents:: :depth: 4

This design document describes the introduction of a new queue scheduling
system for Ganeti jobs based on the amount of contention and resources
needed by each newly submitted job.

Current State and shortcomings
==============================

Currently, jobs in the Ganeti system are placed in a queue and subsequently
set to run by the job scheduler. A job can be in different states such as
QUEUED, WAITING, or RUNNING depending on its position in the scheduling
pipeline. Jobs can also reach the final state of SUCCESS, ERROR or CANCELED,
but that is not relevant for the scope of this document. Among the jobs that
are QUEUED, WAITING or RUNNING, the latter two states are considered by the
system as 'running', while the former as 'pending'.

Ganeti has an option to limit the amount of parallel running jobs (either
WAITING or RUNNING), and when such a limit is reached, all the newly submitted
ones will get stuck in the queue waiting for their turn to be executed. As each
job transitions from RUNNING to a final state, a new spot in the running job
queue opens and the job scheduler is tasked to pick one of the pending ones
to be started next.

As a job transitions from the pending to the running queue, it gets started by
the job executor which initializes the logical unit mcpu, which in turn tries
to acquire the necessary locks on shared resources. If the lock acquisition
fails because the locks are already held by other jobs, the opcode transitions
into a WAITING state and gets stuck until such locks are released.

At the time of writing, the queue scheduler picks which pending job to execute
next based on the following parameters: a priority value, a reason rate limiter,
an eligibility status based on dependencies on other jobs, and a series of
filters. After all these checks are performed, the first job on the list is
picked on a first-come-first-serve basis. On a typical usage scenario, without
any special cases, the first job to be scheduled to run is usually the first
job that was put in the queue. Each job is executed in order.

A small inefficiency of this system is that jobs are not scheduled to run based
on the resources they need, but rather in the order of submission. This means
that in many cases, jobs from the pending queue transition to a WAITING state
and then are blocked again waiting for locks.  Meanwhile, other jobs in the
pending queue could be eligible to run without any additional resources, but
cannot because the running queue is full already.

Proposed changes
================

This design proposes a new way of choosing which jobs to run from the pending
queue based on the resources currently held by all the other running jobs and
the locks required by each new yet-to-be-executed job. On top of the
already-existing filtering parameters, the scheduler will also sort the queue
of pending jobs based on a heuristic value calculated by comparing each job in
the queue with the sum of all the other jobs already running in the system.

Since this change introduces a more unpredictable queue system, there may be
cases where queued jobs fall into starvation as less resource-intensive jobs
get scheduled in front of them and take their spot in the queue. To solve this
problem, we also introduce a customizable parameter that determines the aging
of a pending job which will then affect the heuristic calculations.

Design decisions
================

The addition of a predictive scheduler is a small change on top of the
already-existing queue. It will be sitting right inbetween the priority and
filtering parameters for the queue and it is a simple sort operation which will
not impact the current codebase by a lot. For all intents and purposes, this
change will not impact any of the previously existing filtering parameters
such as reason rate limiting, job filtering, priority values or eligibility
checks.

The algorithm relies on a list of static resource declarations for each opcode.
Each job is assigned a weight by comparing its own locks to those currently
being held by the system. The higher the value, the higher the chance that
the job will be stuck in WAITING over some shared resource. Due to how the
locking system is implemented in Ganeti, it is currently impossible to know
with certainty the exact amount of resources that each job will request
before its transition from the pending to the running queue. As a solution to
this problem, we define a level of uncertainty and a heuristic function to
guesstimate the likelihood of a job to not get blocked. The more knowledge we
have about the jobs being submitted and their parameters, the higher the
accuracy of the heuristic value we'll get for them. This should be taken in
consideration when submitting future jobs after this design is properly
implemented, to improve the performance of Ganeti.

Job Promotion Algorithm
-----------------------

The job locks in Ganeti are separated into 5 different levels (plus the Big
Ganeti Lock): NodeGroup, Instance, Node, NodeRes, and Network. For each of these
levels, jobs can take however many locks they need, in an independent way from
each other, as either shared or exclusive mode. The following are the possible
lock types a job can declare for each level:

 * None: No locks are required at this level at all;

 * Shared(k): The system is aware of which locks are being requested in shared
   mode. K is the list of all the resource names.

 * UnknownShared: The system knows that there is at least one lock requested
   as shared, but it has no way of knowing which or how many.

 * AllShared: All locks at this level are required as shared.

 * Exclusive(k) : The system is aware of which locks are being requested in
   exclusive mode. K is the list of all resource names.

 * UnknownExclusive: The system knowes that there is at least one lock
   requested as excusive, but it has no way of knowing which or how many.

 * AllExclusive: All locks at this level are required as exclusive.

In the case of those few jobs that require the BGL, they are considered
as the absolute worst weight scenario possible and will most likely be
scheduled at the back of the queue as they require the entire set of resources.

We define a comparison operation between two lock types. The first operand is
the lock of a job in a pending queue, whereas the second operand is the
currently-existing lock already taken by a running job. The operation behaves
as follows:

+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
|                  |  None   |  Shared(j)             | UnknownShared | AllShared | Exclusive(j)           | UnknownExclusive | AllExclusive |
+==================+=========+========================+===============+===========+========================+==================+==============+
| None             |    0    |      0                 |       0       |     0     |      0                 |        0         |       0      |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
| Shared(i)        |   0.3   |      0                 |       0       |     0     | if j=i then 3 else 0.3 |        1.5       |       3      |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
| UnknownShared    |   0.3   |     0.3                |      0.3      |    0.3    |      1.5               |        1.5       |       3      |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
| AllShared        |   0.3   |     0.3                |      0.3      |    0.3    |           3            |        3         |       3      |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
|  Exclusive(i)    |   0.5   | if j=i then 3 else 0.5 |    1.5        |   3       | if j=i then 3 else 0.5 |       1.5        |      3       |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
| UnknownExclusive |   0.5   |      1.5               |       1.5     |     3     |         1.5            |        1.5       |       3      |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+
| AllExclusive     |   0.5   |      3                 |       3       |     3     |      3                 |        3         |       3      |
+------------------+---------+------------------------+---------------+-----------+------------------------+------------------+--------------+

The weight values are defined as such:

  * 0: There is no contention, and no contention is added to the state of the
    cluster.

  * 0.3: There should be no contention, however the likelihood for future
    contention of resources in the cluster is increased.

  * 0.5: There should be no contention, however the likelihood for future
    contention of resources in the cluster is greatly increased.

  * 1.5: There is a chance that the job will get stuck but there is no certain
    way of knowing it.

  * 3: The job will surely get stuck in WAITING.

For each of the pending jobs, their locks are compared using this operation
with each of the locks of the running jobs. After this comparison, for each
level the largest number is picked as the "worst case" for that specific level
and used in the heuristic formula to calculate the final weight of the job.

The heuristic algorithm is approximately defined as such::

  if job.hasBGL():
    return base_value+15
  value=base_value
  for level in lock_levels:
    value+=max(measure_lock_contention(job[level], running_jobs[level]))
  return value

The number 15 is obtained by multiplying the worst case lock weight (3) by
the amount of levels (5), the BGL should never have more or less than this
value, in weight. Furthermore, the base_value parameter is a customizable
constant that provides a base value (default is 1) which can be useful when
used with the anti-starvation measures. The 'measure_lock_contention' function
is the comparison operation explained above, where we measure two locks and
against each other and obtain a guesstimate weight for their level of
contention.

As previously specified, to prevent starvation we introduce an aging system
for queued jobs that keeps the queue fair. Each job in the queue will have an
'Age' parameter based on how long it has been sitting in the pending queue.
The greater the age, the smaller the job's static lock weight, the likelier the
job will be to be scheduled for execution next. The age is calculated on the
delta between a job enqueue time and the current time, quantized to a common
unit. This quantization will be adjustable as a constant in the Ganeti code to
something similar to, for example, 1 tick every 30 seconds. Using the current
formula, we can define the actual job weight in the queue::

  weight = spv(job)*max(0, 1 - job.Age()/K)

Where spv(job) is the value obtained by the heuristic algorithm (Static
Predictive Value), Age is the given job's quantized age, and k is an aging
coefficient value that roughly means "the amount of ticks of age to wait
before getting the smallest weight". To explain, K means that regardless of the
measured SPV, the weight of a job will always equal 0 after K ticks of time have
passed.


Static Lock Declaration
-----------------------

As already explained, unfortunately it is not possible to 100% accurately
predict the exact amount of resources that a job will require before it is
executed and enters the running queue. To solve this problem, we decided to
implement an ad-hoc static mapping of opcode:locks declaration.

Given each job, we try to infer as much information as possible from its
opcode parameters, and then deduce which locks are most likely to be requested
as the job transitions into running. Because of the high and varied combinations
of parameters, it is not a simple process and more often than not we simply
have to declare a lock request as "Unknown" (either shared or exclusive, as
defined in the previous section). Luckily, for the currently running opcodes,
it is possible to query the system for the state of the locks and we can
achieve a more accurate map, which helps improving the accuracy of the
heuristic function.

