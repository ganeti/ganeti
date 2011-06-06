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
instances and a list of jobsets.

The two lists of instances describe which instances could be
moved/migrated and which couldn't for some reason ("unsuccessful"). The
union of the two lists must be equal to the set of instances given in
the original request.

The list of jobsets contained in the result describe how to actually
execute the operation. Each jobset contains lists of serialized opcodes.
Example::

  [
    [
      { "OP_ID": "OP_INSTANCE_MIGRATE",
        "instance_name": "inst1.example.com",
      },
      { "OP_ID": "OP_INSTANCE_MIGRATE",
        "instance_name": "inst2.example.com",
      },
    ],
    [
      { "OP_ID": "OP_INSTANCE_REPLACE_DISKS",
        "instance_name": "inst2.example.com",
        "mode": "replace_new_secondary",
        "remote_node": "node4.example.com"
      },
    ],
    [
      { "OP_ID": "OP_INSTANCE_FAILOVER",
        "instance_name": "inst8.example.com",
      },
    ]
  ]

Accepted opcodes:

- ``OP_INSTANCE_FAILOVER``
- ``OP_INSTANCE_MIGRATE``
- ``OP_INSTANCE_REPLACE_DISKS``

Starting with the first set, Ganeti will submit all jobs of a set at the
same time, enabling execution in parallel. Upon completion of all jobs
in a set, the process is repeated for the next one. Ganeti is at liberty
to abort the execution after any jobset. In such a case the user is
notified and can restart the operation.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
