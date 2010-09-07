=================
Ganeti 2.3 design
=================

This document describes the major changes in Ganeti 2.3 compared to
the 2.2 version.

.. contents:: :depth: 4

As for 2.1 and 2.2 we divide the 2.3 design into three areas:

- core changes, which affect the master daemon/job queue/locking or
  all/most logical units
- logical unit/feature changes
- external interface changes (e.g. command line, os api, hooks, ...)

Core changes
============

Node Groups
-----------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently all nodes of a Ganeti cluster are considered as part of the
same pool, for allocation purposes: DRBD instances for example can be
allocated on any two nodes.

This does cause a problem in cases where nodes are not all equally
connected to each other. For example if a cluster is created over two
set of machines, each connected to its own switch, the internal bandwidth
between machines connected to the same switch might be bigger than the
bandwidth for inter-switch connections.

Moreover some operations inside a cluster require all nodes to be locked
together for inter-node consistency, and won't scale if we increase the
number of nodes to a few hundreds.

Proposed changes
~~~~~~~~~~~~~~~~

With this change we'll divide Ganeti nodes into groups. Nothing will
change for clusters with only one node group, the default one. Bigger
cluster instead will be able to have more than one group, and each node
will belong to exactly one.

Node group management
+++++++++++++++++++++

To manage node groups and the nodes belonging to them, the following new
commands/flags will be introduced::

  gnt-node group-add <group> # add a new node group
  gnt-node group-del <group> # delete an empty group
  gnt-node group-list # list node groups
  gnt-node group-rename <oldname> <newname> # rename a group
  gnt-node list/info -g <group> # list only nodes belongin to a group
  gnt-node add -g <group> # add a node to a certain group
  gnt-node modify -g <group> # move a node to a new group

Instance level changes
++++++++++++++++++++++

Instances will be able to live in only one group at a time. This is
mostly important for DRBD instances, in which case both their primary
and secondary nodes will need to be in the same group. To support this
we envision the following changes:

  - The cluster will have a default group, which will initially be
  - Instance allocation will happen to the cluster's default group
    (which will be changable via gnt-cluster modify or RAPI) unless a
    group is explicitely specified in the creation job (with -g or via
    RAPI). Iallocator will be only passed the nodes belonging to that
    group.
  - Moving an instance between groups can only happen via an explicit
    operation, which for example in the case of DRBD will work by
    performing internally a replace-disks, a migration, and a second
    replace-disks. It will be possible to cleanup an interrupted
    group-move operation.
  - Cluster verify will signal an error if an instance has been left
    mid-transition between groups.
  - Intra-group instance migration/failover will check that the target
    group will be able to accept the instance network/storage wise, and
    fail otherwise. In the future we may be able to make some parameter
    changed during the move, but in the first version we expect an
    import/export if this is not possible.
  - From an allocation point of view, inter-group movements will be
    shown to a iallocator as a new allocation over the target group.
    Only in a future version we may add allocator extensions to decide
    which group the instance should be in. In the meantime we expect
    Ganeti administrators to either put instances on different groups by
    filling all groups first, or to have their own strategy based on the
    instance needs.

Cluster/Internal/Config level changes
+++++++++++++++++++++++++++++++++++++

We expect the following changes for cluster management:

  - Frequent multinode operations, such as os-diagnose or cluster-verify
    will act one group at a time. The default group will be used if none
    is passed. Command line tools will have a way to easily target all
    groups, by generating one job per group.
  - Groups will have a human-readable name, but will internally always
    be referenced by a UUID, which will be immutable. For example the
    cluster object will contain the UUID of the default group, each node
    will contain the UUID of the group it belongs to, etc. This is done
    to simplify referencing while keeping it easy to handle renames and
    movements. If we see that this works well, we'll transition other
    config objects (instances, nodes) to the same model.
  - The addition of a new per-group lock will be evaluated, if we can
    transition some operations now requiring the BGL to it.
  - Master candidate status will be allowed to be spread among groups.
    For the first version we won't add any restriction over how this is
    done, although in the future we may have a minimum number of master
    candidates which Ganeti will try to keep in each group, for example.

Other work and future changes
+++++++++++++++++++++++++++++

Commands like gnt-cluster command/copyfile will continue to work on the
whole cluster, but it will be possible to target one group only by
specifying it.

Commands which allow selection of sets of resources (for example
gnt-instance start/stop) will be able to select them by node group as
well.

Initially node groups won't be taggable objects, to simplify the first
implementation, but we expect this to be easy to add in a future version
should we see it's useful.

We envision groups as a good place to enhance cluster scalability. In
the future we may want to use them ad units for configuration diffusion,
to allow a better master scalability. For example it could be possible
to change some all-nodes RPCs to contact each group once, from the
master, and make one node in the group perform internal diffusion. We
won't implement this in the first version, but we'll evaluate it for the
future, if we see scalability problems on big multi-group clusters.

When Ganeti will support more storage models (eg. SANs, sheepdog, ceph)
we expect groups to be the basis for this, allowing for example a
different sheepdog/ceph cluster, or a different SAN to be connected to
each group. In some cases this will mean that inter-group move operation
will be necessarily performed with instance downtime, unless the
hypervisor has block-migrate functionality, and we implement support for
it (this would be theoretically possible, today, with KVM, for example).


Job priorities
--------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently all jobs and opcodes have the same priority. Once a job
started executing, its thread won't be released until all opcodes got
their locks and did their work. When a job is finished, the next job is
selected strictly by its incoming order. This does not mean jobs are run
in their incoming order—locks and other delays can cause them to be
stalled for some time.

In some situations, e.g. an emergency shutdown, one may want to run a
job as soon as possible. This is not possible currently if there are
pending jobs in the queue.

Proposed changes
~~~~~~~~~~~~~~~~

Each opcode will be assigned a priority on submission. Opcode priorities
are integers and the lower the number, the higher the opcode's priority
is. Within the same priority, jobs and opcodes are initially processed
in their incoming order.

Submitted opcodes can have one of the priorities listed below. Other
priorities are reserved for internal use. The absolute range is
-20..+19. Opcodes submitted without a priority (e.g. by older clients)
are assigned the default priority.

  - High (-10)
  - Normal (0, default)
  - Low (+10)

As a change from the current model where executing a job blocks one
thread for the whole duration, the new job processor must return the job
to the queue after each opcode and also if it can't get all locks in a
reasonable timeframe. This will allow opcodes of higher priority
submitted in the meantime to be processed or opcodes of the same
priority to try to get their locks. When added to the job queue's
workerpool, the priority is determined by the first unprocessed opcode
in the job.

If an opcode is deferred, the job will go back to the "queued" status,
even though it's just waiting to try to acquire its locks again later.

If an opcode can not be processed after a certain number of retries or a
certain amount of time, it should increase its priority. This will avoid
starvation.

A job's priority can never go below -20. If a job hits priority -20, it
must acquire its locks in blocking mode.

Opcode priorities are synchronized to disk in order to be restored after
a restart or crash of the master daemon.

Priorities also need to be considered inside the locking library to
ensure opcodes with higher priorities get locks first. See
:ref:`locking priorities <locking-priorities>` for more details.

Worker pool
+++++++++++

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

.. _locking-priorities:

Locking
+++++++

In order to support priorities in Ganeti's own lock classes,
``locking.SharedLock`` and ``locking.LockSet``, the internal structure
of the former class needs to be changed. The last major change in this
area was done for Ganeti 2.1 and can be found in the respective
:doc:`design document <design-2.1>`.

The plain list (``[]``) used as a queue is replaced by a heap queue,
similar to the `worker pool`_. The heap or priority queue does automatic
sorting, thereby automatically taking care of priorities. For each
priority there's a plain list with pending acquires, like the single
queue of pending acquires before this change.

When the lock is released, the code locates the list of pending acquires
for the highest priority waiting. The first condition (index 0) is
notified. Once all waiting threads received the notification, the
condition is removed from the list. If the list of conditions is empty
it's removed from the heap queue.

Like before, shared acquires are grouped and skip ahead of exclusive
acquires if there's already an existing shared acquire for a priority.
To accomplish this, a separate dictionary of shared acquires per
priority is maintained.

To simplify the code and reduce memory consumption, the concept of the
"active" and "inactive" condition for shared acquires is abolished. The
lock can't predict what priorities the next acquires will use and even
keeping a cache can become computationally expensive for arguable
benefit (the underlying POSIX pipe, see ``pipe(2)``, needs to be
re-created for each notification anyway).

The following diagram shows a possible state of the internal queue from
a high-level view. Conditions are shown as (waiting) threads. Assuming
no modifications are made to the queue (e.g. more acquires or timeouts),
the lock would be acquired by the threads in this order (concurrent
acquires in parentheses): ``threadE1``, ``threadE2``, (``threadS1``,
``threadS2``, ``threadS3``), (``threadS4``, ``threadS5``), ``threadE3``,
``threadS6``, ``threadE4``, ``threadE5``.

::

  [
    (0, [exc/threadE1, exc/threadE2, shr/threadS1/threadS2/threadS3]),
    (2, [shr/threadS4/threadS5]),
    (10, [exc/threadE3]),
    (33, [shr/threadS6, exc/threadE4, exc/threadE5]),
  ]


IPv6 support
------------

Currently Ganeti does not support IPv6. This is true for nodes as well
as instances. Due to the fact that IPv4 exhaustion is threateningly near
the need of using IPv6 is increasing, especially given that bigger and
bigger clusters are supported.

Supported IPv6 setup
~~~~~~~~~~~~~~~~~~~~

In Ganeti 2.3 we introduce additionally to the ordinary pure IPv4
setup a hybrid IPv6/IPv4 mode. The latter works as follows:

- all nodes in a cluster have a primary IPv6 address
- the master has a IPv6 address
- all nodes **must** have a secondary IPv4 address

The reason for this hybrid setup is that key components that Ganeti
depends on do not or only partially support IPv6. More precisely, Xen
does not support instance migration via IPv6 in version 3.4 and 4.0.
Similarly, KVM does not support instance migration nor VNC access for
IPv6 at the time of this writing.

This led to the decision of not supporting pure IPv6 Ganeti clusters, as
very important cluster operations would not have been possible. Using
IPv4 as secondary address does not affect any of the goals
of the IPv6 support: since secondary addresses do not need to be
publicly accessible, they need not be globally unique. In other words,
one can practically use private IPv4 secondary addresses just for
intra-cluster communication without propagating them across layer 3
boundaries.

netutils: Utilities for handling common network tasks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently common util functions are kept in the utils modules. Since
this module grows bigger and bigger network-related functions are moved
to a separate module named *netutils*. Additionally all these utilities
will be IPv6-enabled.

Cluster initialization
~~~~~~~~~~~~~~~~~~~~~~

As mentioned above there will be two different setups in terms of IP
addressing: pure IPv4 and hybrid IPv6/IPv4 address. To choose that a
new cluster init parameter *--primary-ip-version* is introduced. This is
needed as a given name can resolve to both an IPv4 and IPv6 address on a
dual-stack host effectively making it impossible to infer that bit.

Once a cluster is initialized and the primary IP version chosen all
nodes that join have to conform to that setup. In the case of our
IPv6/IPv4 setup all nodes *must* have a secondary IPv4 address.

Furthermore we store the primary IP version in ssconf which is consulted
every time a daemon starts to determine the default bind address (either
*0.0.0.0* or *::*. In a IPv6/IPv4 setup we need to bind the Ganeti
daemon listening on network sockets to the IPv6 address.

Node addition
~~~~~~~~~~~~~

When adding a new node to a IPv6/IPv4 cluster it must have a IPv6
address to be used as primary and a IPv4 address used as secondary. As
explained above, every time a daemon is started we use the cluster
primary IP version to determine to which any address to bind to. The
only exception to this is when a node is added to the cluster. In this
case there is no ssconf available when noded is started and therefore
the correct address needs to be passed to it.

Name resolution
~~~~~~~~~~~~~~~

Since the gethostbyname*() functions do not support IPv6 name resolution
will be done by using the recommended getaddrinfo().

IPv4-only components
~~~~~~~~~~~~~~~~~~~~

============================  ===================  ====================
Component                     IPv6 Status          Planned Version
============================  ===================  ====================
Xen instance migration        Not supported        Xen 4.1: libxenlight
KVM instance migration        Not supported        Unknown
KVM VNC access                Not supported        Unknown
============================  ===================  ====================


Feature changes
===============


External interface changes
==========================


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
