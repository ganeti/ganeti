Ganeti 2.0 Granular Locking
===========================

Objective
---------

We want to make sure that multiple operations can run in parallel on a Ganeti
Cluster. In order for this to happen we need to make sure concurrently run
operations don't step on each other toes and break the cluster.

This design addresses how we are going to deal with locking so that:

- high urgency operations are not stopped by long length ones
- long length operations can run in parallel
- we preserve safety (data coherency) and liveness (no deadlock, no work
  postponed indefinitely) on the cluster

Reaching the maximum possible parallelism is a Non-Goal. We have identified a
set of operations that are currently bottlenecks and need to be parallelised
and have worked on those. In the future it will be possible to address other
needs, thus making the cluster more and more parallel one step at a time.

This document only talks about parallelising Ganeti level operations, aka
Logical Units, and the locking needed for that. Any other synchronisation lock
needed internally by the code is outside its scope.

Background
----------

Ganeti 1.2 has a single global lock, which is used for all cluster operations.
This has been painful at various times, for example:

- It is impossible for two people to efficiently interact with a cluster
  (for example for debugging) at the same time.
- When batch jobs are running it's impossible to do other work (for example
  failovers/fixes) on a cluster.

This also poses scalability problems: as clusters grow in node and instance
size it's a lot more likely that operations which one could conceive should run
in parallel (for example because they happen on different nodes) are actually
stalling each other while waiting for the global lock, without a real reason
for that to happen.

Overview
--------

This design doc is best read in the context of the accompanying design
docs for Ganeti 2.0: Master daemon design and Job queue design.

We intend to implement a Ganeti locking library, which can be used by the
various ganeti code components in order to easily, efficiently and correctly
grab the locks they need to perform their function.

The proposed library has these features:

- Internally managing all the locks, making the implementation transparent
  from their usage
- Automatically grabbing multiple locks in the right order (avoid deadlock)
- Ability to transparently handle conversion to more granularity
- Support asynchronous operation (future goal)

Locking will be valid only on the master node and will not be a distributed
operation. In case of master failure, though, if some locks were held it means
some opcodes were in progress, so when recovery of the job queue is done it
will be possible to determine by the interrupted opcodes which operations could
have been left half way through and thus which locks could have been held. It
is then the responsibility either of the master failover code, of the cluster
verification code, or of the admin to do what's necessary to make sure that any
leftover state is dealt with. This is not an issue from a locking point of view
because the fact that the previous master has failed means that it cannot do
any job.

A corollary of this is that a master-failover operation with both masters alive
needs to happen while no other locks are held.

Detailed Design
---------------

The Locks
~~~~~~~~~
At the first stage we have decided to provide the following locks:

- One "config file" lock
- One lock per node in the cluster
- One lock per instance in the cluster

All the instance locks will need to be taken before the node locks, and the
node locks before the config lock. Locks will need to be acquired at the same
time for multiple instances and nodes, and internal ordering will be dealt
within the locking library, which, for simplicity, will just use alphabetical
order.

Handling conversion to more granularity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to convert to a more granular approach transparently each time we
split a lock into more we'll create a "metalock", which will depend on those
sublocks and live for the time necessary for all the code to convert (or
forever, in some conditions). When a metalock exists all converted code must
acquire it in shared mode, so it can run concurrently, but still be exclusive
with old code, which acquires it exclusively.

In the beginning the only such lock will be what replaces the current "command"
lock, and will acquire all the locks in the system, before proceeding. This
lock will be called the "Big Ganeti Lock" because holding that one will avoid
any other concurrent ganeti operations.

We might also want to devise more metalocks (eg. all nodes, all nodes+config)
in order to make it easier for some parts of the code to acquire what it needs
without specifying it explicitly.

In the future things like the node locks could become metalocks, should we
decide to split them into an even more fine grained approach, but this will
probably be only after the first 2.0 version has been released.

Library API
~~~~~~~~~~~

All the locking will be its own class, and the locks will be created at
initialisation time, from the config file.

The API will have a way to grab one or more than one locks at the same time.
Any attempt to grab a lock while already holding one in the wrong order will be
checked for, and fail.

Adding/Removing locks
~~~~~~~~~~~~~~~~~~~~~

When a new instance or a new node is created an associated lock must be added
to the list. The relevant code will need to inform the locking library of such
a change.

This needs to be compatible with every other lock in the system, especially
metalocks that guarantee to grab sets of resources without specifying them
explicitly. The implementation of this will be handled in the locking library
itself.

Of course when instances or nodes disappear from the cluster the relevant locks
must be removed. This is easier than adding new elements, as the code which
removes them must own them exclusively or can queue for their ownership, and
thus deals with metalocks exactly as normal code acquiring those locks. Any
operation queueing on a removed lock will fail after its removal.

Asynchronous operations
~~~~~~~~~~~~~~~~~~~~~~~

For the first version the locking library will only export synchronous
operations, which will block till the needed lock are held, and only fail if
the request is impossible or somehow erroneous.

In the future we may want to implement different types of asynchronous
operations such as:

- Try to acquire this lock set and fail if not possible
- Try to acquire one of these lock sets and return the first one you were
  able to get (or after a timeout) (select/poll like)

Keep in mind, though, that any operation using the first operation, or setting
a timeout for the second one, is susceptible to starvation and thus may never
be able to get the required locks and succeed. Considering this providing/using
these operations should not be among our first priorities

Locking granularity
~~~~~~~~~~~~~~~~~~~

For the first version of this code we'll convert each Logical Unit to
acquire/release the locks it needs, so locking will be at the Logical Unit
level.  In the future we may want to split logical units in independent
"tasklets" with their own locking requirements. A different design doc (or mini
design doc) will cover the move from Logical Units to tasklets.

Caveats
-------

This library will provide an easy upgrade path to bring all the code to
granular locking without breaking everything, and it will also guarantee
against a lot of common errors. Code switching from the old "lock everything"
lock to the new system, though, needs to be carefully scrutinised to be sure it
is really acquiring all the necessary locks, and none has been overlooked or
forgotten.

The code can contain other locks outside of this library, to synchronise other
threaded code (eg for the job queue) but in general these should be leaf locks
or carefully structured non-leaf ones, to avoid deadlock race conditions.

