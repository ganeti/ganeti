===================================
Removal of the Config Lock Overhead
===================================

.. contents:: :depth: 4

This is a design document detailing how the adverse effect of
the config lock can be removed in an incremental way.

Current state and shortcomings
==============================

As a result of the :doc:`design-daemons`, the configuration is held
in a proccess different from the processes carrying out the Ganeti
jobs. Therefore, job processes have to contact WConfD in order to
change the configuration. Of course, these modifications of the
configuration need to be synchronised.

The current form of synchronisation is via ``ConfigLock``. Exclusive
possession of this lock guarantees that no one else modifies the
configuration. In other words, the current procedure for a job to
update the configuration is to

- acquire the ``ConfigLock`` from WConfD,

- read the configration,

- write the modified configuration, and

- release ``ConfigLock``.

The current procedure has some drawbacks. These also affect the
overall throughput of jobs in a Ganeti cluster.

- At each configuration update, the whole configuration is
  transferred between the job and WConfD.

- More importantly, however, jobs can only release the ``ConfigLock`` after
  the write; the write, in turn, is only confirmed once the configuration
  is written on disk. In particular, we can only have one update per
  configuration write. Also, having the ``ConfigLock`` is only confirmed
  to the job, once the new lock status is written to disk.

Additional overhead is caused by the fact that reads are synchronised over
a shared config lock. This used to make sense when the configuration was
modifiable in the same process to ensure consistent read. With the new
structure, all access to the configuration via WConfD are consistent
anyway, and local modifications by other jobs do not happen.


Proposed changes for an incremental improvement
===============================================

Ideally, jobs would just send patches for the configuration to WConfD
that are applied by means of atomically updating the respective ``IORef``.
This, however, would require chaning all of Ganeti's logical units in
one big change. Therefore, we propose to keep the ``ConfigLock`` and,
step by step, reduce its impact till it eventually will be just used
internally in the WConfD process.

Unlocked Reads
--------------

In a first step, all configuration operations that are synchronised over
a shared config lock, and therefore necessarily read-only, will instead
use WConfD's ``readConfig`` used to obtain a snapshot of the configuration.
This will be done without modifying the locks. It is sound, as reads to
a Haskell ``IORef`` always yield a consistent value. From that snapshot
the required view is computed locally. This saves two lock-configurtion
write cycles per read and, additionally, does not block any concurrent
modifications.

In a second step, more specialised read functions will be added to ``WConfD``.
This will reduce the traffic for reads.

Cached Reads
------------

As jobs synchronize with each other by means of regular locks, the parts
of the configuration relevant for a job can only change while a job waits
for new locks. So, if a job has a copy of the configuration and not asked
for locks afterwards, all read-only access can be done from that copy. While
this will not affect the ``ConfigLock``, it saves traffic.

Set-and-release action
----------------------

As a typical pattern is to change the configuration and afterwards release
the ``ConfigLock``. To avoid unnecessary RPC call overhead, WConfD will offer
a combined call. To make that call retryable, it will do nothing if the the
``ConfigLock`` is not held by the caller; in the return value, it will indicate
if the config lock was held when the call was made.

Short-lived ``ConfigLock``
--------------------------

For a lot of operations, the regular locks already ensure that only
one job can modify a certain part of the configuration. For example,
only jobs with an exclusive lock on an instance will modify that
instance. Therefore, it can update that entity atomically,
without relying on the configuration lock to achive consistency.
``WConfD`` will provide such operations. To
avoid interference with non-atomic operations that still take the
config lock and write the configuration as a whole, this operation
will only be carried out at times the config lock is not taken. To
ensure this, the thread handling the request will take the config lock
itself (hence no one else has it, if that succeeds) before the change
and release afterwards; both operations will be done without
triggering a writeout of the lock status.

Note that the thread handling the request has to take the lock in its
own name and not in that of the requesting job. A writeout of the lock
status can still happen, triggered by other requests. Now, if
``WConfD`` gets restarted after the lock acquisition, if that happend
in the name of the job, it would own a lock without knowing about it,
and hence that lock would never get released.


Approaches considered, but not working
======================================

Set-and-release action with asynchronous writes
-----------------------------------------------

Approach
~~~~~~~~

As a typical pattern is to change the configuration and afterwards release
the ``ConfigLock``. To avoid unnecessary delay in this operation (the next
modification of the configuration can already happen while the last change
is written out), WConfD will offer a combined command that will

- set the configuration to the specified value,

- release the config lock,

- and only then wait for the configuration write to finish; it will not
  wait for confirmation of the lock-release write.

If jobs use this combined command instead of the sequential set followed
by release, new configuration changes can come in during writeout of the
current change; in particular, a writeout can contain more than one change.

Problem
~~~~~~~

This approach works fine, as long as always either ``WConfD`` can do an ordered
shutdown or the calling process dies as well. If however, we allow random kill
signals to be sent to individual daemons (e.g., by an out-of-memory killer),
the following race occurs. A process can ask for a combined write-and-unlock
operation; while the configuration is still written out, the write out of the
updated lock status already finishes. Now, if ``WConfD`` forcefully gets killed
in that very moment, a restarted ``WConfD`` will read the old configuration but
the new lock status. This will make the calling process believe that its call,
while it didn't get an answer, succeeded nevertheless, thus resulting in a
wrong configuration state.
