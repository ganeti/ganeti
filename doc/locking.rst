Ganeti locking
==============

Introduction
------------

This document describes lock order dependencies in Ganeti.
It is divided by functional sections


Opcode Execution Locking
------------------------

These locks are declared by Logical Units (LUs) (in cmdlib.py) and
acquired by the Processor (in mcpu.py) with the aid of the Ganeti
Locking Library (locking.py). They are acquired in the following order:

  * BGL: this is the Big Ganeti Lock, it exists for retrocompatibility.
    New LUs acquire it in a shared fashion, and are able to execute all
    toghether (baring other lock waits) while old LUs acquire it
    exclusively and can only execute one at a time, and not at the same
    time with new LUs.
  * Instance locks: can be declared in ExpandNames() or DeclareLocks()
    by an LU, and have the same name as the instance itself. They are
    acquired as a set.  Internally the locking library acquired them in
    alphabetical order.
  * Node locks: can be declared in ExpandNames() or DeclareLocks() by an
    LU, and have the same name as the node itself. They are acquired as
    a set.  Internally the locking library acquired them in alphabetical
    order. Given this order it's possible to safely acquire a set of
    instances, and then the nodes they reside on.

The ConfigWriter (in config.py) is also protected by a SharedLock, which
is shared by functions that read the config and acquired exclusively by
functions that modify it. Since the ConfigWriter calls
rpc.call_upload_file to all nodes to distribute the config without
holding the node locks, this call must be able to execute on the nodes
in parallel with other operations (but not necessarily concurrently with
itself on the same file, as inside the ConfigWriter this is called with
the internal config lock held.


Job Queue Locking
-----------------

The job queue is designed to be thread-safe. This means that its public
functions can be called from any thread. The job queue can be called
from functions called by the queue itself (e.g. logical units), but
special attention must be paid not to create deadlocks or an invalid
state.

The single queue lock is used from all classes involved in the queue
handling.  During development we tried to split locks, but deemed it to
be too dangerous and difficult at the time. Job queue functions
acquiring the lock can be safely called from all the rest of the code,
as the lock is released before leaving the job queue again. Unlocked
functions should only be called from job queue related classes (e.g. in
jqueue.py) and the lock must be acquired beforehand.

In the job queue worker (``_JobQueueWorker``), the lock must be released
before calling the LU processor. Otherwise a deadlock can occur when log
messages are added to opcode results.


Node Daemon Locking
-------------------

The node daemon contains a lock for the job queue. In order to avoid
conflicts and/or corruption when an eventual master daemon or another
node daemon is running, it must be held for all job queue operations

There's one special case for the node daemon running on the master node.
If grabbing the lock in exclusive fails on startup, the code assumes all
checks have been done by the process keeping the lock.

.. vim: set textwidth=72 :
