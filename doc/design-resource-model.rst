========================
 Resource model changes
========================


Introduction
============

In order to manage virtual machines across the cluster, Ganeti needs to
understand the resources present on the nodes, the hardware and software
limitations of the nodes, and how much can be allocated safely on each
node. Some of these decisions are delegated to IAllocator plugins, for
easier site-level customisation.

Similarly, the HTools suite has an internal model that simulates the
hardware resource changes in response to Ganeti operations, in order to
provide both an iallocator plugin and for balancing the
cluster.

While currently the HTools model is much more advanced than Ganeti's,
neither one is flexible enough and both are heavily geared toward a
specific Xen model; they fail to work well with (e.g.) KVM or LXC, or
with Xen when :term:`tmem` is enabled. Furthermore, the set of metrics
contained in the models is limited to historic requirements and fails to
account for (e.g.)  heterogeneity in the I/O performance of the nodes.

Current situation
=================

Ganeti
------

At this moment, Ganeti itself doesn't do any static modelling of the
cluster resources. It only does some runtime checks:

- when creating instances, for the (current) free disk space
- when starting instances, for the (current) free memory
- during cluster verify, for enough N+1 memory on the secondaries, based
  on the (current) free memory

Basically this model is a pure :term:`SoW` one, and it works well when
there are other instances/LVs on the nodes, as it allows Ganeti to deal
with ‘orphan’ resource usage, but on the other hand it has many issues,
described below.

HTools
------

Since HTools does an pure in-memory modelling of the cluster changes as
it executes the balancing or allocation steps, it had to introduce a
static (:term:`SoR`) cluster model.

The model is constructed based on the received node properties from
Ganeti (hence it basically is constructed on what Ganeti can export).

Disk
~~~~

For disk it consists of just the total (``tdsk``) and the free disk
space (``fdsk``); we don't directly track the used disk space. On top of
this, we compute and warn if the sum of disk sizes used by instance does
not match with ``tdsk - fdsk``, but otherwise we do not track this
separately.

Memory
~~~~~~

For memory, the model is more complex and tracks some variables that
Ganeti itself doesn't compute. We start from the total (``tmem``), free
(``fmem``) and node memory (``nmem``) as supplied by Ganeti, and
additionally we track:

instance memory (``imem``)
    the total memory used by primary instances on the node, computed
    as the sum of instance memory

reserved memory (``rmem``)
    the memory reserved by peer nodes for N+1 redundancy; this memory is
    tracked per peer-node, and the maximum value out of the peer memory
    lists is the node's ``rmem``; when not using DRBD, this will be
    equal to zero

unaccounted memory (``xmem``)
    memory that cannot be unaccounted for via the Ganeti model; this is
    computed at startup as::

        tmem - imem - nmem - fmem

    and is presumed to remain constant irrespective of any instance
    moves

available memory (``amem``)
    this is simply ``fmem - rmem``, so unless we use DRBD, this will be
    equal to ``fmem``

``tmem``, ``nmem`` and ``xmem`` are presumed constant during the
instance moves, whereas the ``fmem``, ``imem``, ``rmem`` and ``amem``
values are updated according to the executed moves.

CPU
~~~

The CPU model is different than the disk/memory models, since it's the
only one where:

#. we do oversubscribe physical CPUs
#. and there is no natural limit for the number of VCPUs we can allocate

We therefore track the total number of VCPUs used on the node and the
number of physical CPUs, and we cap the vcpu-to-cpu ratio in order to
make this somewhat more similar to the other resources which are
limited.

Dynamic load
~~~~~~~~~~~~

There is also a model that deals with *dynamic load* values in
htools. As far as we know, it is not currently used actually with load
values, but it is active by default with unitary values for all
instances; it currently tracks these metrics:

- disk load
- memory load
- cpu load
- network load

Even though we do not assign real values to these load values, the fact
that we at least sum them means that the algorithm tries to equalise
these loads, and especially the network load, which is otherwise not
tracked at all. The practical result (due to a combination of these four
metrics) is that the number of secondaries will be balanced.

Limitations
-----------


There are unfortunately many limitations to the current model.

Memory
~~~~~~

The memory model doesn't work well in case of KVM. For Xen, the memory
for the node (i.e. ``dom0``) can be static or dynamic; we don't support
the latter case, but for the former case, the static value is configured
in Xen/kernel command line, and can be queried from Xen
itself. Therefore, Ganeti can query the hypervisor for the memory used
for the node; the same model was adopted for the chroot/KVM/LXC
hypervisors, but in these cases there's no natural value for the memory
used by the base OS/kernel, and we currently try to compute a value for
the node memory based on current consumption. This, being variable,
breaks the assumptions in both Ganeti and HTools.

This problem also shows for the free memory: if the free memory on the
node is not constant (Xen with :term:`tmem` auto-ballooning enabled), or
if the node and instance memory are pooled together (Linux-based
hypervisors like KVM and LXC), the current value of the free memory is
meaningless and cannot be used for instance checks.

A separate issue related to the free memory tracking is that since we
don't track memory use but rather memory availability, an instance that
is temporary down changes Ganeti's understanding of the memory status of
the node. This can lead to problems such as:

.. digraph:: "free-mem-issue"

  node  [shape=box];
  inst1 [label="instance1"];
  inst2 [label="instance2"];

  node  [shape=note];
  nodeA [label="fmem=0"];
  nodeB [label="fmem=1"];
  nodeC [label="fmem=0"];

  node  [shape=ellipse, style=filled, fillcolor=green]

  {rank=same; inst1 inst2}

  stop    [label="crash!", fillcolor=orange];
  migrate [label="migrate/ok"];
  start   [style=filled, fillcolor=red, label="start/fail"];
  inst1   -> stop -> start;
  stop    -> migrate -> start [style=invis, weight=0];
  inst2   -> migrate;

  {rank=same; inst1 inst2 nodeA}
  {rank=same; stop nodeB}
  {rank=same; migrate nodeC}

  nodeA -> nodeB -> nodeC [style=invis, weight=1];

The behaviour here is wrong; the migration of *instance2* to the node in
question will succeed or fail depending on whether *instance1* is
running or not. And for *instance1*, it can lead to cases where it if
crashes, it cannot restart anymore.

Finally, not a problem but rather a missing important feature is support
for memory over-subscription: both Xen and KVM support memory
ballooning, even automatic memory ballooning, for a while now. The
entire memory model is based on a fixed memory size for instances, and
if memory ballooning is enabled, it will “break” the HTools
algorithm. Even the fact that KVM instances do not use all memory from
the start creates problems (although not as high, since it will grow and
stabilise in the end).

Disks
~~~~~

Because we only track disk space currently, this means if we have a
cluster of ``N`` otherwise identical nodes but half of them have 10
drives of size ``X`` and the other half 2 drives of size ``5X``, HTools
will consider them exactly the same. However, in the case of mechanical
drives at least, the I/O performance will differ significantly based on
spindle count, and a “fair” load distribution should take this into
account (a similar comment can be made about processor/memory/network
speed).

Another problem related to the spindle count is the LVM allocation
algorithm. Currently, the algorithm always creates (or tries to create)
striped volumes, with the stripe count being hard-coded to the
``./configure`` parameter ``--with-lvm-stripecount``. This creates
problems like:

- when installing from a distribution package, all clusters will be
  either limited or overloaded due to this fixed value
- it is not possible to mix heterogeneous nodes (even in different node
  groups) and have optimal settings for all nodes
- the striping value applies both to LVM/DRBD data volumes (which are on
  the order of gigabytes to hundreds of gigabytes) and to DRBD metadata
  volumes (whose size is always fixed at 128MB); when stripping such
  small volumes over many PVs, their size will increase needlessly (and
  this can confuse HTools' disk computation algorithm)

Moreover, the allocation currently allocates based on a ‘most free
space’ algorithm. This balances the free space usage on disks, but on
the other hand it tends to mix rather badly the data and metadata
volumes of different instances. For example, it cannot do the following:

- keep DRBD data and metadata volumes on the same drives, in order to
  reduce exposure to drive failure in a many-drives system
- keep DRBD data and metadata volumes on different drives, to reduce
  performance impact of metadata writes

Additionally, while Ganeti supports setting the volume separately for
data and metadata volumes at instance creation, there are no defaults
for this setting.

Similar to the above stripe count problem (which is about not good
enough customisation of Ganeti's behaviour), we have limited
pass-through customisation of the various options of our storage
backends; while LVM has a system-wide configuration file that can be
used to tweak some of its behaviours, for DRBD we don't use the
:command:`drbdadmin` tool, and instead we call :command:`drbdsetup`
directly, with a fixed/restricted set of options; so for example one
cannot tweak the buffer sizes.

Another current problem is that the support for shared storage in HTools
is still limited, but this problem is outside of this design document.

Locking
~~~~~~~

A further problem generated by the “current free” model is that during a
long operation which affects resource usage (e.g. disk replaces,
instance creations) we have to keep the respective objects locked
(sometimes even in exclusive mode), since we don't want any concurrent
modifications to the *free* values.

A classic example of the locking problem is the following:

.. digraph:: "iallocator-lock-issues"

  rankdir=TB;

  start [style=invis];
  node  [shape=box,width=2];
  job1  [label="add instance\niallocator run\nchoose A,B"];
  job1e [label="finish add"];
  job2  [label="add instance\niallocator run\nwait locks"];
  job2s [label="acquire locks\nchoose C,D"];
  job2e [label="finish add"];

  job1  -> job1e;
  job2  -> job2s -> job2e;
  edge [style=invis,weight=0];
  start -> {job1; job2}
  job1  -> job2;
  job2  -> job1e;
  job1e -> job2s [style=dotted,label="release locks"];

In the above example, the second IAllocator run will wait for locks for
nodes ``A`` and ``B``, even though in the end the second instance will
be placed on another set of nodes (``C`` and ``D``). This wait shouldn't
be needed, since right after the first IAllocator run has finished,
:command:`hail` knows the status of the cluster after the allocation,
and it could answer the question for the second run too; however, Ganeti
doesn't have such visibility into the cluster state and thus it is
forced to wait with the second job.

Similar examples can be made about replace disks (another long-running
opcode).

.. _label-policies:

Policies
~~~~~~~~

For most of the resources, we have metrics defined by policy: e.g. the
over-subscription ratio for CPUs, the amount of space to reserve,
etc. Furthermore, although there are no such definitions in Ganeti such
as minimum/maximum instance size, a real deployment will need to have
them, especially in a fully-automated workflow where end-users can
request instances via an automated interface (that talks to the cluster
via RAPI, LUXI or command line). However, such an automated interface
will need to also take into account cluster capacity, and if the
:command:`hspace` tool is used for the capacity computation, it needs to
be told the maximum instance size, however it has a built-in minimum
instance size which is not customisable.

It is clear that this situation leads to duplicate definition of
resource policies which makes it hard to easily change per-cluster (or
globally) the respective policies, and furthermore it creates
inconsistencies if such policies are not enforced at the source (i.e. in
Ganeti).

Balancing algorithm
~~~~~~~~~~~~~~~~~~~

The balancing algorithm, as documented in the HTools ``README`` file,
tries to minimise the cluster score; this score is based on a set of
metrics that describe both exceptional conditions and how spread the
instances are across the nodes. In order to achieve this goal, it moves
the instances around, with a series of moves of various types:

- disk replaces (for DRBD-based instances)
- instance failover/migrations (for all types)

However, the algorithm only looks at the cluster score, and not at the
*“cost”* of the moves. In other words, the following can and will happen
on a cluster:

.. digraph:: "balancing-cost-issues"

  rankdir=LR;
  ranksep=1;

  start     [label="score α", shape=hexagon];

  node      [shape=box, width=2];
  replace1  [label="replace_disks 500G\nscore α-3ε\ncost 3"];
  replace2a [label="replace_disks 20G\nscore α-2ε\ncost 2"];
  migrate1  [label="migrate\nscore α-ε\ncost 1"];

  choose    [shape=ellipse,label="choose min(score)=α-3ε\ncost 3"];

  start -> {replace1; replace2a; migrate1} -> choose;

Even though a migration is much, much cheaper than a disk replace (in
terms of network and disk traffic on the cluster), if the disk replace
results in a score infinitesimally smaller, then it will be
chosen. Similarly, between two disk replaces, one moving e.g. ``500GiB``
and one moving ``20GiB``, the first one will be chosen if it results in
a score smaller than the second one. Furthermore, even if the resulting
scores are equal, the first computed solution will be kept, whichever it
is.

Fixing this algorithmic problem is doable, but currently Ganeti doesn't
export enough information about nodes to make an informed decision; in
the above example, if the ``500GiB`` move is between nodes having fast
I/O (both disks and network), it makes sense to execute it over a disk
replace of ``100GiB`` between nodes with slow I/O, so simply relating to
the properties of the move itself is not enough; we need more node
information for cost computation.

Allocation algorithm
~~~~~~~~~~~~~~~~~~~~

.. note:: This design document will not address this limitation, but it
  is worth mentioning as it directly related to the resource model.

The current allocation/capacity algorithm works as follows (per
node-group)::

    repeat:
        allocate instance without failing N+1

This simple algorithm, and its use of ``N+1`` criterion, has a built-in
limit of 1 machine failure in case of DRBD. This means the algorithm
guarantees that, if using DRBD storage, there are enough resources to
(re)start all affected instances in case of one machine failure. This
relates mostly to memory; there is no account for CPU over-subscription
(i.e. in case of failure, make sure we can failover while still not
going over CPU limits), or for any other resource.

In case of shared storage, there's not even the memory guarantee, as the
N+1 protection doesn't work for shared storage.

If a given cluster administrator wants to survive up to two machine
failures, or wants to ensure CPU limits too for DRBD, there is no
possibility to configure this in HTools (neither in :command:`hail` nor
in :command:`hspace`). Current workaround employ for example deducting a
certain number of instances from the size computed by :command:`hspace`,
but this is a very crude method, and requires that instance creations
are limited before Ganeti (otherwise :command:`hail` would allocate
until the cluster is full).

Proposed architecture
=====================


There are two main changes proposed:

- changing the resource model from a pure :term:`SoW` to a hybrid
  :term:`SoR`/:term:`SoW` one, where the :term:`SoR` component is
  heavily emphasised
- extending the resource model to cover additional properties,
  completing the “holes” in the current coverage

The second change is rather straightforward, but will add more
complexity in the modelling of the cluster. The first change, however,
represents a significant shift from the current model, which Ganeti had
from its beginnings.

Lock-improved resource model
----------------------------

Hybrid SoR/SoW model
~~~~~~~~~~~~~~~~~~~~

The resources of a node can be characterised in two broad classes:

- mostly static resources
- dynamically changing resources

In the first category, we have things such as total core count, total
memory size, total disk size, number of network interfaces etc. In the
second category we have things such as free disk space, free memory, CPU
load, etc. Note that nowadays we don't have (anymore) fully-static
resources: features like CPU and memory hot-plug, online disk replace,
etc. mean that theoretically all resources can change (there are some
practical limitations, of course).

Even though the rate of change of the two resource types is wildly
different, right now Ganeti handles both the same. Given that the
interval of change of the semi-static ones is much bigger than most
Ganeti operations, even more than lengthy sequences of Ganeti jobs, it
makes sense to treat them separately.

The proposal is then to move the following resources into the
configuration and treat the configuration as the authoritative source
for them (a :term:`SoR` model):

- CPU resources:
    - total core count
    - node core usage (*new*)
- memory resources:
    - total memory size
    - node memory size
    - hypervisor overhead (*new*)
- disk resources:
    - total disk size
    - disk overhead (*new*)

Since these resources can though change at run-time, we will need
functionality to update the recorded values.

Pre-computing dynamic resource values
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Remember that the resource model used by HTools models the clusters as
obeying the following equations:

  disk\ :sub:`free` = disk\ :sub:`total` - ∑ disk\ :sub:`instances`

  mem\ :sub:`free` = mem\ :sub:`total` - ∑ mem\ :sub:`instances` - mem\
  :sub:`node` - mem\ :sub:`overhead`

As this model worked fine for HTools, we can consider it valid and adopt
it in Ganeti. Furthermore, note that all values in the right-hand side
come now from the configuration:

- the per-instance usage values were already stored in the configuration
- the other values will are moved to the configuration per the previous
  section

This means that we can now compute the free values without having to
actually live-query the nodes, which brings a significant advantage.

There are a couple of caveats to this model though. First, as the
run-time state of the instance is no longer taken into consideration, it
means that we have to introduce a new *offline* state for an instance
(similar to the node one). In this state, the instance's runtime
resources (memory and VCPUs) are no longer reserved for it, and can be
reused by other instances. Static resources like disk and MAC addresses
are still reserved though. Transitioning into and out of this reserved
state will be more involved than simply stopping/starting the instance
(e.g. de-offlining can fail due to missing resources). This complexity
is compensated by the increased consistency of what guarantees we have
in the stopped state (we always guarantee resource reservation), and the
potential for management tools to restrict which users can transition
into/out of this state separate from which users can stop/start the
instance.

Separating per-node resource locks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Many of the current node locks in Ganeti exist in order to guarantee
correct resource state computation, whereas others are designed to
guarantee reasonable run-time performance of nodes (e.g. by not
overloading the I/O subsystem). This is an unfortunate coupling, since
it means for example that the following two operations conflict in
practice even though they are orthogonal:

- replacing a instance's disk on a node
- computing node disk/memory free for an IAllocator run

This conflict increases significantly the lock contention on a big/busy
cluster and at odds with the goal of increasing the cluster size.

The proposal is therefore to add a new level of locking that is only
used to prevent concurrent modification to the resource states (either
node properties or instance properties) and not for long-term
operations:

- instance creation needs to acquire and keep this lock until adding the
  instance to the configuration
- instance modification needs to acquire and keep this lock until
  updating the instance
- node property changes will need to acquire this lock for the
  modification

The new lock level will sit before the instance level (right after BGL)
and could either be single-valued (like the “Big Ganeti Lock”), in which
case we won't be able to modify two nodes at the same time, or per-node,
in which case the list of locks at this level needs to be synchronised
with the node lock level. To be determined.

Lock contention reduction
~~~~~~~~~~~~~~~~~~~~~~~~~

Based on the above, the locking contention will be reduced as follows:
IAllocator calls will no longer need the ``LEVEL_NODE: ALL_SET`` lock,
only the resource lock (in exclusive mode). Hence allocating/computing
evacuation targets will no longer conflict for longer than the time to
compute the allocation solution.

The remaining long-running locks will be the DRBD replace-disks ones
(exclusive mode). These can also be removed, or changed into shared
locks, but that is a separate design change.

.. admonition:: FIXME

  Need to rework instance replace disks. I don't think we need exclusive
  locks for replacing disks: it is safe to stop/start the instance while
  it's doing a replace disks. Only modify would need exclusive, and only
  for transitioning into/out of offline state.

Instance memory model
---------------------

In order to support ballooning, the instance memory model needs to be
changed from a “memory size” one to a “min/max memory size”. This
interacts with the new static resource model, however, and thus we need
to declare a-priori the expected oversubscription ratio on the cluster.

The new minimum memory size parameter will be similar to the current
memory size; the cluster will guarantee that in all circumstances, all
instances will have available their minimum memory size. The maximum
memory size will permit burst usage of more memory by instances, with
the restriction that the sum of maximum memory usage will not be more
than the free memory times the oversubscription factor:

    ∑ memory\ :sub:`min` ≤ memory\ :sub:`available`

    ∑ memory\ :sub:`max` ≤ memory\ :sub:`free` * oversubscription_ratio

The hypervisor will have the possibility of adjusting the instance's
memory size dynamically between these two boundaries.

Note that the minimum memory is related to the available memory on the
node, whereas the maximum memory is related to the free memory. On
DRBD-enabled clusters, this will have the advantage of using the
reserved memory for N+1 failover for burst usage, instead of having it
completely idle.

.. admonition:: FIXME

  Need to document how Ganeti forces minimum size at runtime, overriding
  the hypervisor, in cases of failover/lack of resources.

New parameters
--------------

Unfortunately the design will add a significant number of new
parameters, and change the meaning of some of the current ones.

Instance size limits
~~~~~~~~~~~~~~~~~~~~

As described in :ref:`label-policies`, we currently lack a clear
definition of the support instance sizes (minimum, maximum and
standard). As such, we will add the following structure to the cluster
parameters:

- ``min_ispec``, ``max_ispec``: minimum and maximum acceptable instance
  specs
- ``std_ispec``: standard instance size, which will be used for capacity
  computations and for default parameters on the instance creation
  request

Ganeti will by default reject non-standard instance sizes (lower than
``min_ispec`` or greater than ``max_ispec``), but as usual a
``--ignore-ipolicy`` option on the command line or in the RAPI request
will override these constraints. The ``std_spec`` structure will be used
to fill in missing instance specifications on create.

Each of the ispec structures will be a dictionary, since the contents
can change over time. Initially, we will define the following variables
in these structures:

+---------------+----------------------------------+--------------+
|Name           |Description                       |Type          |
+===============+==================================+==============+
|mem_size       |Allowed memory size               |int           |
+---------------+----------------------------------+--------------+
|cpu_count      |Allowed vCPU count                |int           |
+---------------+----------------------------------+--------------+
|disk_count     |Allowed disk count                |int           |
+---------------+----------------------------------+--------------+
|disk_size      |Allowed disk size                 |int           |
+---------------+----------------------------------+--------------+
|nic_count      |Alowed NIC count                  |int           |
+---------------+----------------------------------+--------------+

Inheritance
+++++++++++

In a single-group cluster, the above structure is sufficient. However,
on a multi-group cluster, it could be that the hardware specifications
differ across node groups, and thus the following problem appears: how
can Ganeti present unified specifications over RAPI?

Since the set of instance specs is only partially ordered (as opposed to
the sets of values of individual variable in the spec, which are totally
ordered), it follows that we can't present unified specs. As such, the
proposed approach is to allow the ``min_ispec`` and ``max_ispec`` to be
customised per node-group (and export them as a list of specifications),
and a single ``std_spec`` at cluster level (exported as a single value).


Allocation parameters
~~~~~~~~~~~~~~~~~~~~~

Beside the limits of min/max instance sizes, there are other parameters
related to capacity and allocation limits. These are mostly related to
the problems related to over allocation.

+-----------------+----------+---------------------------+----------+------+
| Name            |Level(s)  |Description                |Current   |Type  |
|                 |          |                           |value     |      |
+=================+==========+===========================+==========+======+
|vcpu_ratio       |cluster,  |Maximum ratio of virtual to|64 (only  |float |
|                 |node group|physical CPUs              |in htools)|      |
+-----------------+----------+---------------------------+----------+------+
|spindle_ratio    |cluster,  |Maximum ratio of instances |none      |float |
|                 |node group|to spindles; when the I/O  |          |      |
|                 |          |model doesn't map directly |          |      |
|                 |          |to spindles, another       |          |      |
|                 |          |measure of I/O should be   |          |      |
|                 |          |used instead               |          |      |
+-----------------+----------+---------------------------+----------+------+
|max_node_failures|cluster,  |Cap allocation/capacity so |1         |int   |
|                 |node group|that the cluster can       |(hardcoded|      |
|                 |          |survive this many node     |in htools)|      |
|                 |          |failures                   |          |      |
+-----------------+----------+---------------------------+----------+------+

Since these are used mostly internally (in htools), they will be
exported as-is from Ganeti, without explicit handling of node-groups
grouping.

Regarding ``spindle_ratio``, in this context spindles do not necessarily
have to mean actual mechanical hard-drivers; it's rather a measure of
I/O performance for internal storage.

Disk parameters
~~~~~~~~~~~~~~~

The proposed model for the new disk parameters is a simple free-form one
based on dictionaries, indexed per disk template and parameter name.
Only the disk template parameters are visible to the user, and those are
internally translated to logical disk level parameters.

This is a simplification, because each parameter is applied to a whole
nested structure and there is no way of fine-tuning each level's
parameters, but it is good enough for the current parameter set. This
model could need to be expanded, e.g., if support for three-nodes stacked
DRBD setups is added to Ganeti.

At JSON level, since the object key has to be a string, the keys can be
encoded via a separator (e.g. slash), or by having two dict levels.

When needed, the unit of measurement is expressed inside square
brackets.

+--------+--------------+-------------------------+---------------------+------+
|Disk    |Name          |Description              |Current status       |Type  |
|template|              |                         |                     |      |
+========+==============+=========================+=====================+======+
|plain   |stripes       |How many stripes to use  |Configured at        |int   |
|        |              |for newly created (plain)|./configure time, not|      |
|        |              |logical voumes           |overridable at       |      |
|        |              |                         |runtime              |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |data-stripes  |How many stripes to use  |Same as for          |int   |
|        |              |for data volumes         |plain/stripes        |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |metavg        |Default volume group for |Same as the main     |string|
|        |              |the metadata LVs         |volume group,        |      |
|        |              |                         |overridable via      |      |
|        |              |                         |'metavg' key         |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |meta-stripes  |How many stripes to use  |Same as for lvm      |int   |
|        |              |for meta volumes         |'stripes', suboptimal|      |
|        |              |                         |as the meta LVs are  |      |
|        |              |                         |small                |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |disk-barriers |What kind of barriers to |Either all enabled or|string|
|        |              |*disable* for disks;     |all disabled, per    |      |
|        |              |either "n" or a string   |./configure time     |      |
|        |              |containing a subset of   |option               |      |
|        |              |"bfd"                    |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |meta-barriers |Whether to disable or not|Handled together with|bool  |
|        |              |the barriers for the meta|disk-barriers        |      |
|        |              |volume                   |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |resync-rate   |The (static) resync rate |Hardcoded in         |int   |
|        |              |for drbd, when using the |constants.py, not    |      |
|        |              |static syncer, in KiB/s  |changeable via Ganeti|      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |dynamic-resync|Whether to use the       |Not supported.       |bool  |
|        |              |dynamic resync speed     |                     |      |
|        |              |controller or not. If    |                     |      |
|        |              |enabled, c-plan-ahead    |                     |      |
|        |              |must be non-zero and all |                     |      |
|        |              |the c-* parameters will  |                     |      |
|        |              |be used by DRBD.         |                     |      |
|        |              |Otherwise, the value of  |                     |      |
|        |              |resync-rate will be used |                     |      |
|        |              |as a static resync speed.|                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |c-plan-ahead  |Agility factor of the    |Not supported.       |int   |
|        |              |dynamic resync speed     |                     |      |
|        |              |controller. (the higher, |                     |      |
|        |              |the slower the algorithm |                     |      |
|        |              |will adapt the resync    |                     |      |
|        |              |speed). A value of 0     |                     |      |
|        |              |(that is the default)    |                     |      |
|        |              |disables the controller  |                     |      |
|        |              |[ds]                     |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |c-fill-target |Maximum amount of        |Not supported.       |int   |
|        |              |in-flight resync data    |                     |      |
|        |              |for the dynamic resync   |                     |      |
|        |              |speed controller         |                     |      |
|        |              |[sectors]                |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |c-delay-target|Maximum estimated peer   |Not supported.       |int   |
|        |              |response latency for the |                     |      |
|        |              |dynamic resync speed     |                     |      |
|        |              |controller [ds]          |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |c-max-rate    |Upper bound on resync    |Not supported.       |int   |
|        |              |speed for the dynamic    |                     |      |
|        |              |resync speed controller  |                     |      |
|        |              |[KiB/s]                  |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |c-min-rate    |Minimum resync speed for |Not supported.       |int   |
|        |              |the dynamic resync speed |                     |      |
|        |              |controller [KiB/s]       |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |disk-custom   |Free-form string that    |Not supported        |string|
|        |              |will be appended to the  |                     |      |
|        |              |drbdsetup disk command   |                     |      |
|        |              |line, for custom options |                     |      |
|        |              |not supported by Ganeti  |                     |      |
|        |              |itself                   |                     |      |
+--------+--------------+-------------------------+---------------------+------+
|drbd    |net-custom    |Free-form string for     |Not supported        |string|
|        |              |custom net setup options |                     |      |
+--------+--------------+-------------------------+---------------------+------+

Currently Ganeti supports only DRBD 8.0.x, 8.2.x, 8.3.x.  It will refuse
to work with DRBD 8.4 since the :command:`drbdsetup` syntax has changed
significantly.

The barriers-related parameters have been introduced in different DRBD
versions; please make sure that your version supports all the barrier
parameters that you pass to Ganeti. Any version later than 8.3.0
implements all of them.

The minimum DRBD version for using the dynamic resync speed controller
is 8.3.9, since previous versions implement different parameters.

A more detailed discussion of the dynamic resync speed controller
parameters is outside the scope of the present document. Please refer to
the ``drbdsetup`` man page
(`8.3 <http://www.drbd.org/users-guide-8.3/re-drbdsetup.html>`_ and 
`8.4 <http://www.drbd.org/users-guide/re-drbdsetup.html>`_). An
interesting discussion about them can also be found in a
`drbd-user mailing list post
<http://lists.linbit.com/pipermail/drbd-user/2011-August/016739.html>`_.

All the above parameters are at cluster and node group level; as in
other parts of the code, the intention is that all nodes in a node group
should be equal. It will later be decided to which node group give
precedence in case of instances split over node groups.

.. admonition:: FIXME

   Add details about when each parameter change takes effect (device
   creation vs. activation)

Node parameters
~~~~~~~~~~~~~~~

For the new memory model, we'll add the following parameters, in a
dictionary indexed by the hypervisor name (node attribute
``hv_state``). The rationale is that, even though multi-hypervisor
clusters are rare, they make sense sometimes, and thus we need to
support multipe node states (one per hypervisor).

Since usually only one of the multiple hypervisors is the 'main' one
(and the others used sparringly), capacity computation will still only
use the first hypervisor, and not all of them. Thus we avoid possible
inconsistencies.

+----------+-----------------------------------+---------------+-------+
|Name      |Description                        |Current state  |Type   |
|          |                                   |               |       |
+==========+===================================+===============+=======+
|mem_total |Total node memory, as discovered by|Queried at     |int    |
|          |this hypervisor                    |runtime        |       |
+----------+-----------------------------------+---------------+-------+
|mem_node  |Memory used by, or reserved for,   |Queried at     |int    |
|          |the node itself; not that some     |runtime        |       |
|          |hypervisors can report this in an  |               |       |
|          |authoritative way, other not       |               |       |
+----------+-----------------------------------+---------------+-------+
|mem_hv    |Memory used either by the          |Not used,      |int    |
|          |hypervisor itself or lost due to   |htools computes|       |
|          |instance allocation rounding;      |it internally  |       |
|          |usually this cannot be precisely   |               |       |
|          |computed, but only roughly         |               |       |
|          |estimated                          |               |       |
+----------+-----------------------------------+---------------+-------+
|cpu_total |Total node cpu (core) count;       |Queried at     |int    |
|          |usually this can be discovered     |runtime        |       |
|          |automatically                      |               |       |
|          |                                   |               |       |
|          |                                   |               |       |
|          |                                   |               |       |
+----------+-----------------------------------+---------------+-------+
|cpu_node  |Number of cores reserved for the   |Not used at all|int    |
|          |node itself; this can either be    |               |       |
|          |discovered or set manually. Only   |               |       |
|          |used for estimating how many VCPUs |               |       |
|          |are left for instances             |               |       |
|          |                                   |               |       |
+----------+-----------------------------------+---------------+-------+

Of the above parameters, only ``_total`` ones are straight-forward. The
others have sometimes strange semantics:

- Xen can report ``mem_node``, if configured statically (as we
  recommend); but Linux-based hypervisors (KVM, chroot, LXC) do not, and
  this needs to be configured statically for these values
- ``mem_hv``, representing unaccounted for memory, is not directly
  computable; on Xen, it can be seen that on a N GB machine, with 1 GB
  for dom0 and N-2 GB for instances, there's just a few MB left, instead
  fo a full 1 GB of RAM; however, the exact value varies with the total
  memory size (at least)
- ``cpu_node`` only makes sense on Xen (currently), in the case when we
  restrict dom0; for Linux-based hypervisors, the node itself cannot be
  easily restricted, so it should be set as an estimate of how "heavy"
  the node loads will be

Since these two values cannot be auto-computed from the node, we need to
be able to declare a default at cluster level (debatable how useful they
are at node group level); the proposal is to do this via a cluster-level
``hv_state`` dict (per hypervisor).

Beside the per-hypervisor attributes, we also have disk attributes,
which are queried directly on the node (without hypervisor
involvment). The are stored in a separate attribute (``disk_state``),
which is indexed per storage type and name; currently this will be just
``DT_PLAIN`` and the volume name as key.

+-------------+-------------------------+--------------------+--------+
|Name         |Description              |Current state       |Type    |
|             |                         |                    |        |
+=============+=========================+====================+========+
|disk_total   |Total disk size          |Queried at runtime  |int     |
|             |                         |                    |        |
+-------------+-------------------------+--------------------+--------+
|disk_reserved|Reserved disk size; this |None used in Ganeti;|int     |
|             |is a lower limit on the  |htools has a        |        |
|             |free space, if such a    |parameter for this  |        |
|             |limit is desired         |                    |        |
+-------------+-------------------------+--------------------+--------+
|disk_overhead|Disk that is expected to |None used in Ganeti;|int     |
|             |be used by other volumes |htools detects this |        |
|             |(set via                 |at runtime          |        |
|             |``reserved_lvs``);       |                    |        |
|             |usually should be zero   |                    |        |
+-------------+-------------------------+--------------------+--------+


Instance parameters
~~~~~~~~~~~~~~~~~~~

New instance parameters, needed especially for supporting the new memory
model:

+--------------+----------------------------------+-----------------+------+
|Name          |Description                       |Current status   |Type  |
|              |                                  |                 |      |
+==============+==================================+=================+======+
|offline       |Whether the instance is in        |Not supported    |bool  |
|              |“permanent” offline mode; this is |                 |      |
|              |stronger than the "admin_down”    |                 |      |
|              |state, and is similar to the node |                 |      |
|              |offline attribute                 |                 |      |
+--------------+----------------------------------+-----------------+------+
|be/max_memory |The maximum memory the instance is|Not existent, but|int   |
|              |allowed                           |virtually        |      |
|              |                                  |identical to     |      |
|              |                                  |memory           |      |
+--------------+----------------------------------+-----------------+------+

HTools changes
--------------

All the new parameters (node, instance, cluster, not so much disk) will
need to be taken into account by HTools, both in balancing and in
capacity computation.

Since the Ganeti's cluster model is much enhanced, Ganeti can also
export its own reserved/overhead variables, and as such HTools can make
less “guesses” as to the difference in values.

.. admonition:: FIXME

   Need to detail more the htools changes; the model is clear to me, but
   need to write it down.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
