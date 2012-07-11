==================
Ganeti Bulk Create
==================

.. contents:: :depth: 4
.. highlight:: python

Current state and shortcomings
==============================

Creation of instances happens a lot. A fair load is done by just
creating instances and due to bad allocation shifting them around later
again. Additionally, if you turn up a new cluster you already know a
bunch of instances, which need to exists on the cluster. Doing this
one-by-one is not only cumbersome but might also fail, due to lack of
resources or lead to badly balanced clusters.

Since the early Ganeti 2.0 alpha version there is a ``gnt-instance
batch-create`` command to allocate a bunch of instances based on a json
file. This feature, however, doesn't take any advantages of iallocator
and submits jobs in a serialized manner.


Proposed changes
----------------

To overcome this shortcoming we would extend the current iallocator
interface to allow bulk requests. On the Ganeti side, a new opcode is
introduced to handle the bulk creation and returning the resulting
placement from the IAllocator_.


Problems
--------

Due to the design of chained jobs, we can guarantee, that with the state
at which the ``multi-alloc`` opcode is run, all of the instances will
fit (or all won't). But we can't guarantee that once the instance
creation requests were submit, no other jobs have sneaked in between.
This might still lead to failing jobs because the resources have changed
in the meantime.


Implementation
==============


IAllocator
----------

A new additional ``type`` will be added called ``multi-allocate`` to
distinguish between normal and bulk operation. For the bulk operation
the ``request`` will be a finite list of request dicts.

If ``multi-allocate`` is declared, ``request`` must exist and is a list
of ``request`` dicts as described in :doc:`Operation specific input
<iallocator>`. The ``result`` then is a list of instance name and node
placements in the order of the ``request`` field.

In addition, the old ``allocate`` request type will be deprecated and at
latest in Ganeti 2.8 incooperated into this new request. Current code
will need slight adaption to work with the new request. This needs
careful testing.


OpInstanceBulkAdd
-----------------

We add a new opcode ``OpInstanceBulkAdd``. It receives a list of
``OpInstanceCreate`` on the ``instances`` field. This is done to make
sure, that these two loosely coupled opcodes do not get out of sync. On
the RAPI side, however, this just is a list of instance create
definitions. And the client is adapted accordingly.

The opcode itself does some sanity checks on the instance creation
opcodes which includes:

* ``mode`` is not set
* ``pnode`` and ``snodes`` is not set
* ``iallocator`` is not set

Any of the above error will be aborted with ``OpPrereqError``. Once the
list has been verified it is handed to the ``iallocator`` as described
in IAllocator_. Upon success we then return the result of the
IAllocator_ call.

At this point the current instance allocation would work with the
resources available on the cluster as perceived upon
``OpInstanceBulkAdd`` invocation. However, there might be corner cases
where this is not true as described in Problems_.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
