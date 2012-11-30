Design for parallelized instance creations and opportunistic locking
====================================================================

.. contents:: :depth: 3


Current state and shortcomings
------------------------------

As of Ganeti 2.6, instance creations acquire all node locks when an
:doc:`instance allocator <iallocator>` (henceforth "iallocator") is
used. In situations where many instance should be created in a short
timeframe, there is a lot of congestion on node locks. Effectively all
instance creations are serialized, even on big clusters with multiple
groups.

The situation gets worse when disk wiping is enabled (see
:manpage:`gnt-cluster(8)`) as that can take, depending on disk size and
hardware performance, from minutes to hours. Not waiting for DRBD disks
to synchronize (``wait_for_sync=false``) makes instance creations
slightly faster, but there's a risk of impacting I/O of other instances.


Proposed changes
----------------

The target is to speed up instance creations in combination with an
iallocator even when the cluster's balance is sacrificed in the process.
The cluster can later be re-balanced using ``hbal``. The main objective
is to reduce the number of node locks acquired for creation and to
release un-used locks as fast as possible (the latter is already being
done). To do this safely, several changes are necessary.

Locking library
~~~~~~~~~~~~~~~

Instead of forcibly acquiring all node locks for creating an instance
using an iallocator, only those currently available will be acquired.

To this end, the locking library must be extended to implement
opportunistic locking. Lock sets must be able to only acquire all locks
available at the time, ignoring and not waiting for those held by
another thread.

Locks (``SharedLock``) already support a timeout of zero. The latter is
different from a blocking acquisition, in which case the timeout would
be ``None``.

Lock sets can essentially be acquired in two different modes. One is to
acquire the whole set, which in turn will also block adding new locks
from other threads, and the other is to acquire specific locks by name.
The function to acquire locks in a set accepts a timeout which, if not
``None`` for blocking acquisitions, counts for the whole duration of
acquiring, if necessary, the lock set's internal lock, as well as the
member locks. For opportunistic acquisitions the timeout is only
meaningful when acquiring the whole set, in which case it is only used
for acquiring the set's internal lock (used to block lock additions).
For acquiring member locks the timeout is effectively zero to make them
opportunistic.

A new and optional boolean parameter named ``opportunistic`` is added to
``LockSet.acquire`` and re-exported through
``GanetiLockManager.acquire`` for use by ``mcpu``. Internally, lock sets
do the lock acquisition using a helper function, ``__acquire_inner``. It
will be extended to support opportunistic acquisitions. The algorithm is
very similar to acquiring the whole set with the difference that
acquisitions timing out will be ignored (the timeout in this case is
zero).


New lock level
~~~~~~~~~~~~~~

With opportunistic locking used for instance creations (controlled by a
parameter), multiple such requests can start at (essentially) the same
time and compete for node locks. Some logical units, such as
``LUClusterVerifyGroup``, need to acquire all node locks. In the latter
case all instance allocations would fail to get their locks. This also
applies when multiple instance creations are started at roughly the same
time.

To avoid situations where an opcode holding all or many node locks
causes allocations to fail, a new lock level must be added to control
allocations. The logical units for instance failover and migration can
only safely determine whether they need all node locks after the
instance lock has been acquired. Therefore the new lock level, named
"node-alloc" (shorthand for "node-allocation") will be inserted after
instances (``LEVEL_INSTANCE``) and before node groups
(``LEVEL_NODEGROUP``). Similar to the "big cluster lock" ("BGL") there
is only a single lock at this level whose name is "node allocation lock"
("NAL").

As a rule-of-thumb, the node allocation lock must be acquired in the
same mode as nodes and/or node resources. If all or a large number of
node locks are acquired, the node allocation lock should be acquired as
well. Special attention should be given to logical units started for all
node groups, such as ``LUGroupVerifyDisks``, as they also block many
nodes over a short amount of time.


iallocator
~~~~~~~~~~

The :doc:`iallocator interface <iallocator>` does not need any
modification. When an instance is created, the information for all nodes
is passed to the iallocator plugin. Nodes for which the lock couldn't be
acquired and therefore shouldn't be used for the instance in question,
will be shown as offline.


Opcodes
~~~~~~~

The opcodes ``OpInstanceCreate`` and ``OpInstanceMultiAlloc`` will gain
a new parameter to enable opportunistic locking. By default this mode is
disabled as to not break backwards compatibility.

A new error type is added to describe a temporary lack of resources. Its
name will be ``ECODE_TEMP_NORES``. With opportunistic locks the opcodes
mentioned before only have a partial view of the cluster and can no
longer decide if an instance could not be allocated due to the locks it
has been given or whether the whole cluster is lacking resources.
Therefore it is required, upon encountering the error code for a
temporary lack of resources, for the job submitter to make this decision
by re-submitting the job or by re-directing it to another cluster.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
