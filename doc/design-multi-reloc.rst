====================================
Moving instances accross node groups
====================================

This design document explains the changes needed in Ganeti to perform
instance moves across node groups. Reader familiarity with the following
existing documents is advised:

- :doc:`Current IAllocator specification <iallocator>`
- :doc:`Shared storage model in 2.3+ <design-shared-storage>`

Motivation and and design proposal
==================================

At the moment, moving instances away from their primary or secondary
nodes with the ``relocate`` and ``multi-evacuate`` IAllocator calls
restricts target nodes to those on the same node group. This ensures a
mobility domain is never crossed, and allows normal operation of each
node group to be confined within itself.

It is desirable, however, to have a way of moving instances across node
groups so that, for example, it is possible to move a set of instances
to another group for policy reasons, or completely empty a given group
to perform maintenance operations.

To implement this, we propose the addition of new IAllocator calls to
compute inter-group instance moves and group-aware node evacuation,
taking into account mobility domains as appropriate. The interface
proposed below should be enough to cover the use cases mentioned above.

With the implementation of this design proposal, the previous
``multi-evacuate`` mode will be deprecated.

.. _multi-reloc-detailed-design:

Detailed design
===============

All requests honor the groups' ``alloc_policy`` attribute.

Changing instance's groups
--------------------------

Takes a list of instances and a list of node group UUIDs; the instances
will be moved away from their current group, to any of the groups in the
target list. All instances need to have their primary node in the same
group, which may not be a target group. If the target group list is
empty, the request is simply "change group" and the instances are placed
in any group but their original one.

Node evacuation
---------------

Evacuates instances off their primary nodes. The evacuation mode
can be given as ``primary-only``, ``secondary-only`` or
``all``. The call is given a list of instances whose primary nodes need
to be in the same node group. The returned nodes need to be in the same
group as the original primary node.

.. _multi-reloc-result:

Result
------

In all storage models, an inter-group move can be modeled as a sequence
of **replace secondary**, **migration** and **failover** operations
(when shared storage is used, they will all be failover or migration
operations within the corresponding mobility domain).

The result of the operations described above must contain two lists of
instances and a list of jobs (each of which is a list of serialized
opcodes) to actually execute the operation. :doc:`Job dependencies
<design-chained-jobs>` can be used to force jobs to run in a certain
order while still making use of parallelism.

The two lists of instances describe which instances could be
moved/migrated and which couldn't for some reason ("unsuccessful"). The
union of the instances in the two lists must be equal to the set of
instances given in the original request. The successful list of
instances contains elements as follows::

  (instance name, target group name, [chosen node names])

The choice of names is simply for readability reasons (for example,
Ganeti could log the computed solution in the job information) and for
being able to check (manually) for consistency that the generated
opcodes match the intended target groups/nodes. Note that for the
node-evacuate operation, the group is not changed, but it should still
be returned as such (as it's easier to have the same return type for
both operations).

The unsuccessful list of instances contains elements as follows::

  (instance name, explanation)

where ``explanation`` is a string describing why the plugin was not able
to relocate the instance.

The client is given a list of job IDs (see the :doc:`design for
LU-generated jobs <design-lu-generated-jobs>`) which it can watch.
Failures should be reported to the user.

.. highlight:: python

Example job list::

  [
    # First job
    [
      { "OP_ID": "OP_INSTANCE_MIGRATE",
        "instance_name": "inst1.example.com",
      },
      { "OP_ID": "OP_INSTANCE_MIGRATE",
        "instance_name": "inst2.example.com",
      },
    ],
    # Second job
    [
      { "OP_ID": "OP_INSTANCE_REPLACE_DISKS",
        "depends": [
          [-1, ["success"]],
          ],
        "instance_name": "inst2.example.com",
        "mode": "replace_new_secondary",
        "remote_node": "node4.example.com",
      },
    ],
    # Third job
    [
      { "OP_ID": "OP_INSTANCE_FAILOVER",
        "depends": [
          [-2, []],
          ],
        "instance_name": "inst8.example.com",
      },
    ],
  ]

Accepted opcodes:

- ``OP_INSTANCE_FAILOVER``
- ``OP_INSTANCE_MIGRATE``
- ``OP_INSTANCE_REPLACE_DISKS``

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
