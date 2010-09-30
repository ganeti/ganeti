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
- external interface changes (e.g. command line, OS API, hooks, ...)

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
  gnt-node list/info -g <group> # list only nodes belonging to a group
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
    (which will be changeable via ``gnt-cluster modify`` or RAPI) unless
    a group is explicitly specified in the creation job (with -g or via
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

Internal changes
++++++++++++++++

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

Commands like ``gnt-cluster command``/``gnt-cluster copyfile`` will
continue to work on the whole cluster, but it will be possible to target
one group only by specifying it.

Commands which allow selection of sets of resources (for example
``gnt-instance start``/``gnt-instance stop``) will be able to select
them by node group as well.

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

When Ganeti will support more storage models (e.g. SANs, Sheepdog, Ceph)
we expect groups to be the basis for this, allowing for example a
different Sheepdog/Ceph cluster, or a different SAN to be connected to
each group. In some cases this will mean that inter-group move operation
will be necessarily performed with instance downtime, unless the
hypervisor has block-migrate functionality, and we implement support for
it (this would be theoretically possible, today, with KVM, for example).

Scalability issues with big clusters
------------------------------------

Current and future issues
~~~~~~~~~~~~~~~~~~~~~~~~~

Assuming the node groups feature will enable bigger clusters, other
parts of Ganeti will be impacted even more by the (in effect) bigger
clusters.

While many areas will be impacted, one is the most important: the fact
that the watcher still needs to be able to repair instance data on the
current 5 minutes time-frame (a shorter time-frame would be even
better). This means that the watcher itself needs to have parallelism
when dealing with node groups.

Also, the iallocator plugins are being fed data from Ganeti but also
need access to the full cluster state, and in general we still rely on
being able to compute the full cluster state somewhat “cheaply” and
on-demand. This conflicts with the goal of disconnecting the different
node groups, and to keep the same parallelism while growing the cluster
size.

Another issue is that the current capacity calculations are done
completely outside Ganeti (and they need access to the entire cluster
state), and this prevents keeping the capacity numbers in sync with the
cluster state. While this is still acceptable for smaller clusters where
a small number of allocations/removal are presumed to occur between two
periodic capacity calculations, on bigger clusters where we aim to
parallelize heavily between node groups this is no longer true.



As proposed changes, the main change is introducing a cluster state
cache (not serialised to disk), and to update many of the LUs and
cluster operations to account for it. Furthermore, the capacity
calculations will be integrated via a new OpCode/LU, so that we have
faster feedback (instead of periodic computation).

Cluster state cache
~~~~~~~~~~~~~~~~~~~

A new cluster state cache will be introduced. The cache relies on two
main ideas:

- the total node memory, CPU count are very seldom changing; the total
  node disk space is also slow changing, but can change at runtime; the
  free memory and free disk will change significantly for some jobs, but
  on a short timescale; in general, these values will mostly “constant”
  during the lifetime of a job
- we already have a periodic set of jobs that query the node and
  instance state, driven the by :command:`ganeti-watcher` command, and
  we're just discarding the results after acting on them

Given the above, it makes sense to cache inside the master daemon the
results of node and instance state (with a focus on the node state).

The cache will not be serialised to disk, and will be for the most part
transparent to the outside of the master daemon.

Cache structure
+++++++++++++++

The cache will be oriented with a focus on node groups, so that it will
be easy to invalidate an entire node group, or a subset of nodes, or the
entire cache. The instances will be stored in the node group of their
primary node.

Furthermore, since the node and instance properties determine the
capacity statistics in a deterministic way, the cache will also hold, at
each node group level, the total capacity as determined by the new
capacity iallocator mode.

Cache updates
+++++++++++++

The cache will be updated whenever a query for a node state returns
“full” node information (so as to keep the cache state for a given node
consistent). Partial results will not update the cache (see next
paragraph).

Since the there will be no way to feed the cache from outside, and we
would like to have a consistent cache view when driven by the watcher,
we'll introduce a new OpCode/LU for the watcher to run, instead of the
current separate opcodes (see below in the watcher section).

Updates to a node that change a node's specs “downward” (e.g. less
memory) will invalidate the capacity data. Updates that increase the
node will not invalidate the capacity, as we're more interested in “at
least available” correctness, not “at most available”.

Cache invalidation
++++++++++++++++++

If a partial node query is done (e.g. just for the node free space), and
the returned values don't match with the cache, then the entire node
state will be invalidated.

By default, all LUs will invalidate the caches for all nodes and
instances they lock. If an LU uses the BGL, then it will invalidate the
entire cache. In time, it is expected that LUs will be modified to not
invalidate, if they are not expected to change the node's and/or
instance's state (e.g. ``LUConnectConsole``, or
``LUActivateInstanceDisks``).

Invalidation of a node's properties will also invalidate the capacity
data associated with that node.

Cache lifetime
++++++++++++++

The cache elements will have an upper bound on their lifetime; the
proposal is to make this an hour, which should be a high enough value to
cover the watcher being blocked by a medium-term job (e.g. 20-30
minutes).

Cache usage
+++++++++++

The cache will be used by default for most queries (e.g. a Luxi call,
without locks, for the entire cluster). Since this will be a change from
the current behaviour, we'll need to allow non-cached responses,
e.g. via a ``--cache=off`` or similar argument (which will force the
query).

The cache will also be used for the iallocator runs, so that computing
allocation solution can proceed independent from other jobs which lock
parts of the cluster. This is important as we need to separate
allocation on one group from exclusive blocking jobs on other node
groups.

The capacity calculations will also use the cache—this is detailed in
the respective sections.

Watcher operation
~~~~~~~~~~~~~~~~~

As detailed in the cluster cache section, the watcher also needs
improvements in order to scale with the the cluster size.

As a first improvement, the proposal is to introduce a new OpCode/LU
pair that runs with locks held over the entire query sequence (the
current watcher runs a job with two opcodes, which grab and release the
locks individually). The new opcode will be called
``OpUpdateNodeGroupCache`` and will do the following:

- try to acquire all node/instance locks (to examine in more depth, and
  possibly alter) in the given node group
- invalidate the cache for the node group
- acquire node and instance state (possibly via a new single RPC call
  that combines node and instance information)
- update cache
- return the needed data

The reason for the per-node group query is that we don't want a busy
node group to prevent instance maintenance in other node
groups. Therefore, the watcher will introduce parallelism across node
groups, and it will possible to have overlapping watcher runs. The new
execution sequence will be:

- the parent watcher process acquires global watcher lock
- query the list of node groups (lockless or very short locks only)
- fork N children, one for each node group
- release the global lock
- poll/wait for the children to finish

Each forked children will do the following:

- try to acquire the per-node group watcher lock
- if fail to acquire, exit with special code telling the parent that the
  node group is already being managed by a watcher process
- otherwise, submit a OpUpdateNodeGroupCache job
- get results (possibly after a long time, due to busy group)
- run the needed maintenance operations for the current group

This new mode of execution means that the master watcher processes might
overlap in running, but not the individual per-node group child
processes.

This change allows us to keep (almost) the same parallelism when using a
bigger cluster with node groups versus two separate clusters.


Cost of periodic cache updating
+++++++++++++++++++++++++++++++

Currently the watcher only does “small” queries for the node and
instance state, and at first sight changing it to use the new OpCode
which populates the cache with the entire state might introduce
additional costs, which must be payed every five minutes.

However, the OpCodes that the watcher submits are using the so-called
dynamic fields (need to contact the remote nodes), and the LUs are not
selective—they always grab all the node and instance state. So in the
end, we have the same cost, it just becomes explicit rather than
implicit.

This ‘grab all node state’ behaviour is what makes the cache worth
implementing.

Intra-node group scalability
++++++++++++++++++++++++++++

The design above only deals with inter-node group issues. It still makes
sense to run instance maintenance for nodes A and B if only node C is
locked (all being in the same node group).

This problem is commonly encountered in previous Ganeti versions, and it
should be handled similarly, by tweaking lock lifetime in long-duration
jobs.

TODO: add more ideas here.


State file maintenance
++++++++++++++++++++++

The splitting of node group maintenance to different children which will
run in parallel requires that the state file handling changes from
monolithic updates to partial ones.

There are two file that the watcher maintains:

- ``$LOCALSTATEDIR/lib/ganeti/watcher.data``, its internal state file,
  used for deciding internal actions
- ``$LOCALSTATEDIR/run/ganeti/instance-status``, a file designed for
  external consumption

For the first file, since it's used only internally to the watchers, we
can move to a per node group configuration.

For the second file, even if it's used as an external interface, we will
need to make some changes to it: because the different node groups can
return results at different times, we need to either split the file into
per-group files or keep the single file and add a per-instance timestamp
(currently the file holds only the instance name and state).

The proposal is that each child process maintains its own node group
file, and the master process will, right after querying the node group
list, delete any extra per-node group state file. This leaves the
consumers to run a simple ``cat instance-status.group-*`` to obtain the
entire list of instance and their states. If needed, the modify
timestamp of each file can be used to determine the age of the results.


Capacity calculations
~~~~~~~~~~~~~~~~~~~~~

Currently, the capacity calculations are done completely outside
Ganeti. As explained in the current problems section, this needs to
account better for the cluster state changes.

Therefore a new OpCode will be introduced, ``OpComputeCapacity``, that
will either return the current capacity numbers (if available), or
trigger a new capacity calculation, via the iallocator framework, which
will get a new method called ``capacity``.

This method will feed the cluster state (for the complete set of node
group, or alternative just a subset) to the iallocator plugin (either
the specified one, or the default is none is specified), and return the
new capacity in the format currently exported by the htools suite and
known as the “tiered specs” (see :manpage:`hspace(1)`).

tspec cluster parameters
++++++++++++++++++++++++

Currently, the “tspec” calculations done in :command:`hspace` require
some additional parameters:

- maximum instance size
- type of instance storage
- maximum ratio of virtual CPUs per physical CPUs
- minimum disk free

For the integration in Ganeti, there are multiple ways to pass these:

- ignored by Ganeti, and being the responsibility of the iallocator
  plugin whether to use these at all or not
- as input to the opcode
- as proper cluster parameters

Since the first option is not consistent with the intended changes, a
combination of the last two is proposed:

- at cluster level, we'll have cluster-wide defaults
- at node groups, we'll allow overriding the cluster defaults
- and if they are passed in via the opcode, they will override for the
  current computation the values

Whenever the capacity is requested via different parameters, it will
invalidate the cache, even if otherwise the cache is up-to-date.

The new parameters are:

- max_inst_spec: (int, int, int), the maximum instance specification
  accepted by this cluster or node group, in the order of memory, disk,
  vcpus;
- default_template: string, the default disk template to use
- max_cpu_ratio: double, the maximum ratio of VCPUs/PCPUs
- max_disk_usage: double, the maximum disk usage (as a ratio)

These might also be used in instance creations (to be determined later,
after they are introduced).

OpCode details
++++++++++++++

Input:

- iallocator: string (optional, otherwise uses the cluster default)
- cached: boolean, optional, defaults to true, and denotes whether we
  accept cached responses
- the above new parameters, optional; if they are passed, they will
  overwrite all node group's parameters

Output:

- cluster: list of tuples (memory, disk, vcpu, count), in decreasing
  order of specifications; the first three members represent the
  instance specification, the last one the count of how many instances
  of this specification can be created on the cluster
- node_groups: a dictionary keyed by node group UUID, with values a
  dictionary:

  - tspecs: a list like the cluster one
  - additionally, the new cluster parameters, denoting the input
    parameters that were used for this node group

- ctime: the date the result has been computed; this represents the
  oldest creation time amongst all node groups (so as to accurately
  represent how much out-of-date the global response is)

Note that due to the way the tspecs are computed, for any given
specification, the total available count is the count for the given
entry, plus the sum of counts for higher specifications.

Also note that the node group information is provided just
informationally, not for allocation decisions.


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

Opcode priorities are synchronised to disk in order to be restored after
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

Currently common utility functions are kept in the ``utils`` module.
Since this module grows bigger and bigger network-related functions are
moved to a separate module named *netutils*. Additionally all these
utilities will be IPv6-enabled.

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


Privilege Separation
--------------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In Ganeti 2.2 we introduced privilege separation for the RAPI daemon.
This was done directly in the daemon's code in the process of
daemonizing itself. Doing so leads to several potential issues. For
example, a file could be opened while the code is still running as
``root`` and for some reason not be closed again. Even after changing
the user ID, the file descriptor can be written to.

Implementation
~~~~~~~~~~~~~~

To address these shortcomings, daemons will be started under the target
user right away. The ``start-stop-daemon`` utility used to start daemons
supports the ``--chuid`` option to change user and group ID before
starting the executable.

The intermediate solution for the RAPI daemon from Ganeti 2.2 will be
removed again.

Files written by the daemons may need to have an explicit owner and
group set (easily done through ``utils.WriteFile``).

All SSH-related code is removed from the ``ganeti.bootstrap`` module and
core components and moved to a separate script. The core code will
simply assume a working SSH setup to be in place.

Security Domains
~~~~~~~~~~~~~~~~

In order to separate the permissions of file sets we separate them
into the following 3 overall security domain chunks:

1. Public: ``0755`` respectively ``0644``
2. Ganeti wide: shared between the daemons (gntdaemons)
3. Secret files: shared among a specific set of daemons/users

So for point 3 this tables shows the correlation of the sets to groups
and their users:

=== ========== ============================== ==========================
Set Group      Users                          Description
=== ========== ============================== ==========================
A   gntrapi    gntrapi, gntmasterd            Share data between
                                              gntrapi and gntmasterd
B   gntadmins  gntrapi, gntmasterd, *users*   Shared between users who
                                              needs to call gntmasterd
C   gntconfd   gntconfd, gntmasterd           Share data between
                                              gntconfd and gntmasterd
D   gntmasterd gntmasterd                     masterd only; Currently
                                              only to redistribute the
                                              configuration, has access
                                              to all files under
                                              ``lib/ganeti``
E   gntdaemons gntmasterd, gntrapi, gntconfd  Shared between the various
                                              Ganeti daemons to exchange
                                              data
=== ========== ============================== ==========================

Restricted commands
~~~~~~~~~~~~~~~~~~~

The following commands needs still root to fulfill their functions:

::

  gnt-cluster {init|destroy|command|copyfile|rename|masterfailover|renew-crypto}
  gnt-node {add|remove}
  gnt-instance {console}

Directory structure and permissions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Here's how we propose to change the filesystem hierarchy and their
permissions.

Assuming it follows the defaults: ``gnt${daemon}`` for user and
the groups from the section `Security Domains`_::

  ${localstatedir}/lib/ganeti/ (0755; gntmasterd:gntmasterd)
     cluster-domain-secret (0600; gntmasterd:gntmasterd)
     config.data (0640; gntmasterd:gntconfd)
     hmac.key (0440; gntmasterd:gntconfd)
     known_host (0644; gntmasterd:gntmasterd)
     queue/ (0700; gntmasterd:gntmasterd)
       archive/ (0700; gntmasterd:gntmasterd)
         * (0600; gntmasterd:gntmasterd)
       * (0600; gntmasterd:gntmasterd)
     rapi.pem (0440; gntrapi:gntrapi)
     rapi_users (0640; gntrapi:gntrapi)
     server.pem (0440; gntmasterd:gntmasterd)
     ssconf_* (0444; root:gntmasterd)
     uidpool/ (0750; root:gntmasterd)
     watcher.data (0600; root:gntmasterd)
  ${localstatedir}/run/ganeti/ (0770; gntmasterd:gntdaemons)
     socket/ (0750; gntmasterd:gntadmins)
       ganeti-master (0770; gntmasterd:gntadmins)
  ${localstatedir}/log/ganeti/ (0770; gntmasterd:gntdaemons)
     master-daemon.log (0600; gntmasterd:gntdaemons)
     rapi-daemon.log (0600; gntrapi:gntdaemons)
     conf-daemon.log (0600; gntconfd:gntdaemons)
     node-daemon.log (0600; gntnoded:gntdaemons)


Feature changes
===============


External interface changes
==========================


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
