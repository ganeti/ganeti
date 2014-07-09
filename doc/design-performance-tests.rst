========================
Performance tests for QA
========================

.. contents:: :depth: 4

This design document describes performance tests to be added to QA in
order to measure performance changes over time.

Current state and shortcomings
==============================

Currently, only functional QA tests are performed. Those tests verify
the correct behaviour of Ganeti in various configurations, but are not
designed to continuously monitor the performance of Ganeti.

The current QA tests don't execute multiple tasks/jobs in parallel.
Therefore, the locking part of Ganeti does not really receive any
testing, neither functional nor performance wise.

On the plus side, Ganeti's QA code does already measure the runtime of
individual tests, which is leveraged in this design.

Proposed changes
================

The tests to be added in the context of this design document focus on
two areas:

  * Job queue performance. How does Ganeti handle a lot of submitted
    jobs?
  * Parallel job execution performance. How well does Ganeti
    parallelize jobs?

Jobs are submitted to the job queue in sequential order, but the
execution of the jobs runs in parallel. All job submissions must
complete within a reasonable timeout.

In order to make it easier to recognize performance related tests, all
tests added in the context of this design get a description with a
"PERFORMANCE: " prefix.

Job queue performance
---------------------

Tests targeting the job queue should eliminate external factors (like
network/disk performance or hypervisor delays) as much as possible, so
they are designed to run in a vcluster QA environment.

The following tests are added to the QA:

  * Submit the maximum amount of instance create jobs in parallel. As
    soon as a creation job succeeds, submit a removal job for this
    instance.
  * Submit as many instance create jobs as there are nodes in the
    cluster in parallel (for non-redundant instances). Removal jobs
    as above.
  * For the maximum amount of instances in the cluster, submit modify
    jobs (modify hypervisor and backend parameters) in parallel.
  * For the maximum amount of instances in the cluster, submit stop,
    start, reboot and reinstall jobs in parallel.
  * For the maximum amount of instances in the cluster, submit multiple
    list and info jobs in parallel.
  * For the maximum amount of instances in the cluster, submit move
    jobs in parallel. While the move operations are running, get
    instance information using info jobs. Those jobs are required to
    return within a reasonable low timeout.
  * For the maximum amount of instances in the cluster, submit add-,
    remove- and list-tags jobs.
  * Submit 200 `gnt-debug delay` jobs with a delay of 0.1 seconds. To
    speed up submission, perform multiple job submissions in parallel.
    Verify that submitting jobs doesn't significantly slow down during
    the process. Verify that querying cluster information over CLI and
    RAPI succeeds in a timely fashion with the delay jobs
    running/queued.

Parallel job execution performance
----------------------------------

Tests targeting the performance of parallel execution of "real" jobs
in close-to-production clusters should actually perform all operations,
such as creating disks and starting instances. This way, real world
locking or waiting issues can be reproduced. Performing all those
operations does requires quite some time though, so only a smaller
number of instances and parallel jobs can be tested realistically.

The following tests are added to the QA:

  * Submitting twice as many instance creation request as there are
    nodes in the cluster, using DRBD as disk template.
    The job parameters are chosen according to best practice for
    parallel instance creation without running the risk of instance
    creation failing for too many parallel creation attempts.
    As soon as a creation job succeeds, submit a removal job for
    this instance.
  * Submitting twice as many instance creation request as there are
    nodes in the cluster, using Plain as disk template. As soon as a
    creation job succeeds, submit a removal job for this instance.
    This test can make better use of parallelism because only one
    node must be locked for an instance creation.
  * Create an instance using DRBD. Fail it over, migrate it, change
    its secondary node, reboot it and reinstall it while creating an
    additional instance in parallel to each of those operations.

Future work
===========

Based on test results of the tests listed above, additional tests can
be added to cover more real-world use-cases. Also, based on user
requests, specially crafted performance tests modeling those workloads
can be added too.

Additionally, the correlations between job submission time and job
queue size could be detected. Therefore, a snapshot of the job queue
before job submission could be taken to measure job submission time
based on the jobs in the queue.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
