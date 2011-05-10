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

To implement this, we propose a new ``multi-relocate`` IAllocator call
that will be able to compute inter-group instance moves, taking into
account mobility domains as appropriate. The interface proposed below
should be enough to cover the use cases mentioned above.

.. _multi-reloc-detailed-design:

Detailed design
===============

We introduce a new ``multi-relocate`` IAllocator call whose input will
be a list of instances to move, and a "mode of operation" that will
determine what groups will be candidates to receive the new instances.

The mode of operation will be one of:

- *Stay in group*: the instances will be moved off their current nodes,
  but will stay in the same group; this is what the ``relocate`` call
  does, but here it can act on multiple instances. (Typically, the
  source nodes will be marked as drained, to avoid just exchanging
  instances among them.)

- *Change group*: this mode accepts one extra parameter, a list of node
  group UUIDs; the instances will be moved away from their current
  group, to any of the groups in this list. If the list is empty, the
  request is, simply, "change group": the instances are placed in any
  group but their original one.

- *Any*: for each instance, any group is valid, including its current
  one.

In all modes, the groups' ``alloc_policy`` attribute will be honored.

.. _multi-reloc-result:

Result
------

In all storage models, an inter-group move can be modeled as a sequence
of **replace secondary**, **migration** and **failover** operations
(when shared storage is used, they will all be failover or migration
operations within the corresponding mobility domain).

The result is expected to be a list of jobsets. Each jobset contains
lists of serialized opcodes. Example::

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
to abort the execution of the relocation after any jobset. In such a
case the user is notified and can restart the relocation.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
