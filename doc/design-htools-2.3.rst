====================================
 Synchronising htools to Ganeti 2.3
====================================

Ganeti 2.3 introduces a number of new features that change the cluster
internals significantly enough that the htools suite needs to be
updated accordingly in order to function correctly.

Shared storage support
======================

Currently, the htools algorithms presume a model where all of an
instance's resources is served from within the cluster, more
specifically from the nodes comprising the cluster. While is this
usual for memory and CPU, deployments which use shared storage will
invalidate this assumption for storage.

To account for this, we need to move some assumptions from being
implicit (and hardcoded) to being explicitly exported from Ganeti.


New instance parameters
-----------------------

It is presumed that Ganeti will export for all instances a new
``storage_type`` parameter, that will denote either internal storage
(e.g. *plain* or *drbd*), or external storage.

Furthermore, a new ``storage_pool`` parameter will classify, for both
internal and external storage, the pool out of which the storage is
allocated. For internal storage, this will be either ``lvm`` (the pool
that provides space to both ``plain`` and ``drbd`` instances) or
``file`` (for file-storage-based instances). For external storage,
this will be the respective NAS/SAN/cloud storage that backs up the
instance. Note that for htools, external storage pools are opaque; we
only care that they have an identifier, so that we can distinguish
between two different pools.

If these two parameters are not present, the instances will be
presumed to be ``internal/lvm``.

New node parameters
-------------------

For each node, it is expected that Ganeti will export what storage
types it supports and pools it has access to. So a classic 2.2 cluster
will have all nodes supporting ``internal/lvm`` and/or
``internal/file``, whereas a new shared storage only 2.3 cluster could
have ``external/my-nas`` storage.

Whatever the mechanism that Ganeti will use internally to configure
the associations between nodes and storage pools, we consider that
we'll have available two node attributes inside htools: the list of internal
and external storage pools.

External storage and instances
------------------------------

Currently, for an instance we allow one cheap move type: failover to
the current secondary, if it is a healthy node, and four other
“expensive” (as in, including data copies) moves that involve changing
either the secondary or the primary node or both.

In presence of an external storage type, the following things will
change:

- the disk-based moves will be disallowed; this is already a feature
  in the algorithm, controlled by a boolean switch, so adapting
  external storage here will be trivial
- instead of the current one secondary node, the secondaries will
  become a list of potential secondaries, based on access to the
  instance's storage pool

Except for this, the basic move algorithm remains unchanged.

External storage and nodes
--------------------------

Two separate areas will have to change for nodes and external storage.

First, then allocating instances (either as part of a move or a new
allocation), if the instance is using external storage, then the
internal disk metrics should be ignored (for both the primary and
secondary cases).

Second, the per-node metrics used in the cluster scoring must take
into account that nodes might not have internal storage at all, and
handle this as a well-balanced case (score 0).

N+1 status
----------

Currently, computing the N+1 status of a node is simple:

- group the current secondary instances by their primary node, and
  compute the sum of each instance group memory
- choose the maximum sum, and check if it's smaller than the current
  available memory on this node

In effect, computing the N+1 status is a per-node matter. However,
with shared storage, we don't have secondary nodes, just potential
secondaries. Thus computing the N+1 status will be a cluster-level
matter, and much more expensive.

A simple version of the N+1 checks would be that for each instance
having said node as primary, we have enough memory in the cluster for
relocation. This means we would actually need to run allocation
checks, and update the cluster status from within allocation on one
node, while being careful that we don't recursively check N+1 status
during this relocation, which is too expensive.

However, the shared storage model has some properties that changes the
rules of the computation. Speaking broadly (and ignoring hard
restrictions like tag based exclusion and CPU limits), the exact
location of an instance in the cluster doesn't matter as long as
memory is available. This results in two changes:

- simply tracking the amount of free memory buckets is enough,
  cluster-wide
- moving an instance from one node to another would not change the N+1
  status of any node, and only allocation needs to deal with N+1
  checks

Unfortunately, this very cheap solution fails in case of any other
exclusion or prevention factors.

TODO: find a solution for N+1 checks.


Node groups support
===================

The addition of node groups has a small impact on the actual
algorithms, which will simply operate at node group level instead of
cluster level, but it requires the addition of new algorithms for
inter-node group operations.

The following two definitions will be used in the following
paragraphs:

local group
  The local group refers to a node's own node group, or when speaking
  about an instance, the node group of its primary node

regular cluster
  A cluster composed of a single node group, or pre-2.3 cluster

super cluster
  This term refers to a cluster which comprises multiple node groups,
  as opposed to a 2.2 and earlier cluster with a single node group

In all the below operations, it's assumed that Ganeti can gather the
entire super cluster state cheaply.


Balancing changes
-----------------

Balancing will move from cluster-level balancing to group
balancing. In order to achieve a reasonable improvement in a super
cluster, without needing to keep state of what groups have been
already balanced previously, the balancing algorithm will run as
follows:

#. the cluster data is gathered
#. if this is a regular cluster, as opposed to a super cluster,
   balancing will proceed normally as previously
#. otherwise, compute the cluster scores for all groups
#. choose the group with the worst score and see if we can improve it;
   if not choose the next-worst group, so on
#. once a group has been identified, run the balancing for it

Of course, explicit selection of a group will be allowed.

Super cluster operations
++++++++++++++++++++++++

Beside the regular group balancing, in a super cluster we have more
operations.


Redistribution
^^^^^^^^^^^^^^

In a regular cluster, once we run out of resources (offline nodes
which can't be fully evacuated, N+1 failures, etc.) there is nothing
we can do unless nodes are added or instances are removed.

In a super cluster however, there might be resources available in
another group, so there is the possibility of relocating instances
between groups to re-establish N+1 success within each group.

One difficulty in the presence of both super clusters and shared
storage is that the move paths of instances are quite complicated;
basically an instance can move inside its local group, and to any
other groups which have access to the same storage type and storage
pool pair. In effect, the super cluster is composed of multiple
‘partitions’, each containing one or more groups, but a node is
simultaneously present in multiple partitions, one for each storage
type and storage pool it supports. As such, the interactions between
the individual partitions are too complex for non-trivial clusters to
assume we can compute a perfect solution: we might need to move some
instances using shared storage pool ‘A’ in order to clear some more
memory to accept an instance using local storage, which will further
clear more VCPUs in a third partition, etc. As such, we'll limit
ourselves at simple relocation steps within a single partition.

Algorithm:

#. read super cluster data, and exit if cluster doesn't allow
   inter-group moves
#. filter out any groups that are “alone” in their partition
   (i.e. no other group sharing at least one storage method)
#. determine list of healthy versus unhealthy groups:

    #. a group which contains offline nodes still hosting instances is
       definitely not healthy
    #. a group which has nodes failing N+1 is ‘weakly’ unhealthy

#. if either list is empty, exit (no work to do, or no way to fix problems)
#. for each unhealthy group:

    #. compute the instances that are causing the problems: all
       instances living on offline nodes, all instances living as
       secondary on N+1 failing nodes, all instances living as primaries
       on N+1 failing nodes (in this order)
    #. remove instances, one by one, until the source group is healthy
       again
    #. try to run a standard allocation procedure for each instance on
       all potential groups in its partition
    #. if all instances were relocated successfully, it means we have a
       solution for repairing the original group

Compression
^^^^^^^^^^^

In a super cluster which has had many instance reclamations, it is
possible that while none of the groups is empty, overall there is
enough empty capacity that an entire group could be removed.

The algorithm for “compressing” the super cluster is as follows:

#. read super cluster data
#. compute total *(memory, disk, cpu)*, and free *(memory, disk, cpu)*
   for the super-cluster
#. computer per-group used and free *(memory, disk, cpu)*
#. select candidate groups for evacuation:

    #. they must be connected to other groups via a common storage type
       and pool
    #. they must have fewer used resources than the global free
       resources (minus their own free resources)

#. for each of these groups, try to relocate all its instances to
   connected peer groups
#. report the list of groups that could be evacuated, or if instructed
   so, perform the evacuation of the group with the largest free
   resources (i.e. in order to reclaim the most capacity)

Load balancing
^^^^^^^^^^^^^^

Assuming a super cluster using shared storage, where instance failover
is cheap, it should be possible to do a load-based balancing across
groups.

As opposed to the normal balancing, where we want to balance on all
node attributes, here we should look only at the load attributes; in
other words, compare the available (total) node capacity with the
(total) load generated by instances in a given group, and computing
such scores for all groups, trying to see if we have any outliers.

Once a reliable load-weighting method for groups exists, we can apply
a modified version of the cluster scoring method to score not
imbalances across nodes, but imbalances across groups which result in
a super cluster load-related score.

Allocation changes
------------------

It is important to keep the allocation method across groups internal
(in the Ganeti/Iallocator combination), instead of delegating it to an
external party (e.g. a RAPI client). For this, the IAllocator protocol
should be extended to provide proper group support.

For htools, the new algorithm will work as follows:

#. read/receive cluster data from Ganeti
#. filter out any groups that do not supports the requested storage
   method
#. for remaining groups, try allocation and compute scores after
   allocation
#. sort valid allocation solutions accordingly and return the entire
   list to Ganeti

The rationale for returning the entire group list, and not only the
best choice, is that we anyway have the list, and Ganeti might have
other criteria (e.g. the best group might be busy/locked down, etc.)
so even if from the point of view of resources it is the best choice,
it might not be the overall best one.

Node evacuation changes
-----------------------

While the basic concept in the ``multi-evac`` iallocator
mode remains unchanged (it's a simple local group issue), when failing
to evacuate and running in a super cluster, we could have resources
available elsewhere in the cluster for evacuation.

The algorithm for computing this will be the same as the one for super
cluster compression and redistribution, except that the list of
instances is fixed to the ones living on the nodes to-be-evacuated.

If the inter-group relocation is successful, the result to Ganeti will
not be a local group evacuation target, but instead (for each
instance) a pair *(remote group, nodes)*. Ganeti itself will have to
decide (based on user input) whether to continue with inter-group
evacuation or not.

In case that Ganeti doesn't provide complete cluster data, just the
local group, the inter-group relocation won't be attempted.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
