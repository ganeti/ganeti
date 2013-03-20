============================
Storage free space reporting
============================

.. contents:: :depth: 4

Background
==========

Currently Space reporting is broken for all storage types except drbd or
lvm (plain). This design looks at the root causes and proposes a way to
fix it.

Proposed changes
================

The changes below will streamline Ganeti to properly support
interaction with different storage types.

Configuration changes
---------------------

Add a new attribute "enabled_storage_types" (type: list of strings) to the
cluster config which holds the types of storages, for example, "file", "rados",
or "ext". We consider the first one of the list as the default type.

For file storage, we'll report the storage space on the file storage dir,
which is currently limited to one directory. In the future, if we'll have
support for more directories, or for per-nodegroup directories this can be
changed.

Note that the abovementioned enabled_storage_types are just "mechanisms"
parameters that define which storage types the cluster can use. Further
filtering about what's allowed can go in the ipolicy, but these changes are
not covered in this design doc.

Since the ipolicy currently has a list of enabled storage types, we'll
use that to decide which storage type is the default, and to self-select
it for new instance creations, and reporting.

Enabling/disabling of storage types at ``./configure`` time will be
eventually removed.

RPC changes
-----------

The noded RPC call that reports node storage space will be changed to
accept a list of <type>,<key> string tuples. For each of them, it will
report the free amount of storage space found on storage <key> as known
by the requested storage type types. For example types are ``lvm``,
``filesystem``, or ``rados``, and the key would be a volume group name, in
the case of lvm, a directory name for the filesystem and a rados pool name
for rados storage.

For now, we will implement only the storage reporting for non-shared storage,
that is ``filesystem`` and ``lvm``. For shared storage types like ``rados``
and ``ext`` we will not implement a free space calculation, because it does
not make sense to query each node for the free space of a commonly used
storage.

Masterd will know (through a constant map) which storage type uses which
type for storage calculation (i.e. ``plain`` and ``drbd`` use ``lvm``,
``file`` uses ``filesystem``, etc) and query the one needed (or all of the
needed ones).

Note that for file and sharedfile the node knows which directories are
allowed and won't allow any other directory to be queried for security
reasons. The actual path still needs to be passed to distinguish the
two, as the type will be the same for both.

These calculations will be implemented in the node storage system
(currently lib/storage.py) but querying will still happen through the
``node info`` call, to avoid requiring an extra RPC each time.

Ganeti reporting
----------------

`gnt-node list`` can be queried for the different storage types, if they
are enabled. By default, it will just report information about the default
storage type. Examples::

  > gnt-node list
  Node                       DTotal DFree MTotal MNode MFree Pinst Sinst
  mynode1                      3.6T  3.6T  64.0G 1023M 62.2G     1     0
  mynode2                      3.6T  3.6T  64.0G 1023M 62.0G     2     1
  mynode3                      3.6T  3.6T  64.0G 1023M 62.3G     0     2

  > gnt-node list -o dtotal/lvm,dfree/rados
  Node      DTotal (Lvm, myvg) DFree (Rados, myrados)
  mynode1                 3.6T                      -
  mynode2                 3.6T                      -

Note that for drbd, we only report the space of the vg and only if it was not
renamed to something different than the default volume group name. With this
design, there is also no possibility to ask about the meta volume group. We
restrict the design here to make the transition to storage pools easier (as it
is an interim state only). It is the administrator's responsibility to ensure
that there is enough space for the meta volume group.

When storage pools are implemented, we switch from referencing the storage
type to referencing the storage pool name. For that, of course, the pool
names need to be unique over all storage types. For drbd, we will use the
default 'lvm' storage pool and possibly a second lvm-based storage pool for
the metavg. It will be possible to rename storage pools (thus also the default
lvm storage pool). There will be new functionality to ask about what storage
pools are available and of what type.

``gnt-cluster info`` will report which storage types are enabled, i.e.
which ones are supported according to the cluster configuration. Example
output::

  > gnt-cluster info
  [...]
  Cluster parameters:
    - [...]
    - enabled storage types: plain (default), drbd, lvm, rados
    - [...]

``gnt-node list-storage`` will not be affected by any changes, since this design
describes only free storage reporting for non-shared storage types.

Allocator changes
-----------------

The iallocator protocol doesn't need to change: since we know which
storage type an instance has, we'll pass only the "free" value for that
storage type to the iallocator, when asking for an allocation to be
made. Note that for DRBD nowadays we ignore the case when vg and metavg
are different, and we only consider the main VG. Fixing this is outside
the scope of this design.

With this design, we ensure forward-compatibility with respect to storage
pools. For now, we'll report space for all available (non-shared) storage
types, in the future, for all available storage pools.

Rebalancing changes
-------------------

Hbal will not need changes, as it handles it already. We don't forecast
any changes needed to it.

Space reporting changes
-----------------------

Hspace will by default report by assuming the allocation will happen on
the default storage for the cluster/nodegroup. An option will be added
to manually specify a different storage.

Interactions with Partitioned Ganeti
------------------------------------

Also the design for :doc:`Partitioned Ganeti <design-partitioned>` deals
with reporting free space. Partitioned Ganeti has a different way to
report free space for LVM on nodes where the ``exclusive_storage`` flag
is set. That doesn't interact directly with this design, as the specific
of how the free space is computed is not in the scope of this design.
But the ``node info`` call contains the value of the
``exclusive_storage`` flag, which is currently only meaningful for the
LVM back-end. Additional flags like the ``exclusive_storage`` flag
for lvm might be useful for other storage types as well. We therefore
extend the RPC call with <type>,<key> to <type>,<key>,<params> to
include any storage-type specific parameters in the RPC call.

The reporting of free spindles, also part of Partitioned Ganeti, is not
concerned with this design doc, as those are seen as a separate resource.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
