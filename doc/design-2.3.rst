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

Job priorities
--------------

Current state and shortcomings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. TODO: Describe current situation

Proposed changes
~~~~~~~~~~~~~~~~

.. TODO: Describe changes to job queue and potentially client programs

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
