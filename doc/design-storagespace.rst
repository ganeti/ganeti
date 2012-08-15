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

Each storage type will have a new "pools" parameter added (type list of
strings). This will be list of vgs for plain and drbd (note that we make
no distinction at this level between allowed vgs and metavgs), the list
of rados pools for rados, or the storage directory for file and
sharedfile. The parameters already present in the cluster config object
will be moved to the storage parameters.

Since currently file and sharedfile only support a single directory this
list will be limited to one. In the future if we'll have support for
more directories, or for per-nodegroup directories this can be changed.

Note that these are just "mechanisms" parameters that define which
storage pools the cluster can use. Further filtering about what's
allowed can go in the ipolicy, but these changes are not covered in this
design doc.

Since the ipolicy currently has a list of enabled storage types, we'll
use that to decide which storage type is the default, and to self-select
it for new instance creations, and reporting.

Enabling/disabling of storage types at ``./configure`` time will be
eventually removed.

RPC changes
-----------

The noded RPC call that reports node storage space will be changed to
accept a list of <method>,<key> string tuples. For each of them it will
report the free amount of space found on storage <key> as known by the
requested method. Methods are for example ``lvm``, ``filesystem``,
``rados``, and the key would be a volume group name in the case of lvm,
a directory name for the filesystem and a rados pool name, for
rados_pool.

Masterd will know (through a constant map) which storage type uses which
method for storage calculation (i.e. ``plain`` and ``drbd`` use ``lvm``,
``file`` and ``sharedfile`` use ``filesystem``, etc) and query the one
needed (or all of the needed ones).

Note that for file and sharedfile the node knows which directories are
allowed and won't allow any other directory to be queried for security
reasons. The actual path still needs to be passed to distinguish the
two, as the method will be the same for both.

These calculations will be implemented in the node storage system
(currently lib/storage.py) but querying will still happen through the
``node info`` call, to avoid requiring an extra RPC each time.

Ganeti reporting
----------------

``gnt-node list`` will by default report information just about the
default storage type. It will be possible to add fields to ask about
other ones, if they're enabled.

``gnt-node info`` will report information about all enabled storage
types, without querying them (just say which ones are supported
according to the cluster configuration).

``gnt-node list-storage`` will change to report information about all
available storage pools in each storage type. An extra flag will be
added to filter by storage pool name (alternatively we can implement
this by allowing to query by a list of ``type:pool`` string tuples to
have a more comprehensive filter).


Allocator changes
-----------------

The iallocator protocol doesn't need to change: since we know which
storage type an instance has, we'll pass only the "free" value for that
storage type to the iallocator, when asking for an allocation to be
made. Note that for DRBD nowadays we ignore the case when vg and metavg
are different, and we only consider the main VG. Fixing this is outside
the scope of this design.

Rebalancing changes
-------------------

Hbal will not need changes, as it handles it already. We don't forecast
any changes needed to it.

Space reporting changes
-----------------------

Hspace will by default report by assuming the allocation will happen on
the default storage for the cluster/nodegroup. An option will be added
to manually specify a different storage.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
