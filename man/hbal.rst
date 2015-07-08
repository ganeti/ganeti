HBAL(1) Ganeti | Version @GANETI_VERSION@
=========================================

NAME
----

hbal \- Cluster balancer for Ganeti

SYNOPSIS
--------

**hbal** {backend options...} [algorithm options...] [reporting options...]

**hbal** \--version


Backend options:

{ **-m** *cluster* | **-L[** *path* **] [-X]** | **-t** *data-file* |
**-I** *path* }

Algorithm options:

**[ \--max-cpu *cpu-ratio* ]**
**[ \--min-disk *disk-ratio* ]**
**[ -l *limit* ]**
**[ -e *score* ]**
**[ -g *delta* ]** **[ \--min-gain-limit *threshold* ]**
**[ -O *name...* ]**
**[ \--no-disk-moves ]**
**[ \--no-instance-moves ]**
**[ -U *util-file* ]**
**[ \--ignore-dynu ]**
**[ \--ignore-soft-errors ]**
**[ \--mond *yes|no* ]**
**[ \--mond-xen ]**
**[ \--exit-on-missing-mond-data ]**
**[ \--evac-mode ]**
**[ \--restricted-migration ]**
**[ \--select-instances *inst...* ]**
**[ \--exclude-instances *inst...* ]**

Reporting options:

**[ -C[ *file* ] ]**
**[ -p[ *fields* ] ]**
**[ \--print-instances ]**
**[ -S *file* ]**
**[ -v... | -q ]**


DESCRIPTION
-----------

hbal is a cluster balancer that looks at the current state of the
cluster (nodes with their total and free disk, memory, etc.) and
instance placement and computes a series of steps designed to bring
the cluster into a better state.

The algorithm used is designed to be stable (i.e. it will give you the
same results when restarting it from the middle of the solution) and
reasonably fast. It is not, however, designed to be a perfect algorithm:
it is possible to make it go into a corner from which it can find no
improvement, because it looks only one "step" ahead.

The program accesses the cluster state via Rapi or Luxi. It also
requests data over the network from all MonDs with the --mond option.
Currently it uses only data produced by CPUload collector.

By default, the program will show the solution incrementally as it is
computed, in a somewhat cryptic format; for getting the actual Ganeti
command list, use the **-C** option.

ALGORITHM
~~~~~~~~~

The program works in independent steps; at each step, we compute the
best instance move that lowers the cluster score.

The possible move type for an instance are combinations of
failover/migrate and replace-disks such that we change one of the
instance nodes, and the other one remains (but possibly with changed
role, e.g. from primary it becomes secondary). The list is:

- failover (f)
- replace secondary (r)
- replace primary, a composite move (f, r, f)
- failover and replace secondary, also composite (f, r)
- replace secondary and failover, also composite (r, f)

We don't do the only remaining possibility of replacing both nodes
(r,f,r,f or the equivalent f,r,f,r) since these move needs an
exhaustive search over both candidate primary and secondary nodes, and
is O(n*n) in the number of nodes. Furthermore, it doesn't seems to
give better scores but will result in more disk replacements.

PLACEMENT RESTRICTIONS
~~~~~~~~~~~~~~~~~~~~~~

At each step, we prevent an instance move if it would cause:

- a node to go into N+1 failure state
- an instance to move onto an offline node (offline nodes are either
  read from the cluster or declared with *-O*; drained nodes are
  considered offline)
- an exclusion-tag based conflict (exclusion tags are read from the
  cluster and/or defined via the *\--exclusion-tags* option)
- a max vcpu/pcpu ratio to be exceeded (configured via *\--max-cpu*)
- min disk free percentage to go below the configured limit
  (configured via *\--min-disk*)

CLUSTER SCORING
~~~~~~~~~~~~~~~

As said before, the algorithm tries to minimise the cluster score at
each step. Currently this score is computed as a weighted sum of the
following components:

- standard deviation of the percent of free memory
- standard deviation of the percent of reserved memory
- the sum of the percentages of reserved memory
- standard deviation of the percent of free disk
- count of nodes failing N+1 check
- count of instances living (either as primary or secondary) on
  offline nodes; in the sense of hbal (and the other htools) drained
  nodes are considered offline
- count of instances living (as primary) on offline nodes; this
  differs from the above metric by helping failover of such instances
  in 2-node clusters
- standard deviation of the ratio of virtual-to-physical cpus (for
  primary instances of the node)
- standard deviation of the fraction of the available spindles
  (in dedicated mode, spindles represent physical spindles; otherwise
  this oversubscribable measure for IO load, and the oversubscription
  factor is taken into account when computing the number of available
  spindles)
- standard deviation of the dynamic load on the nodes, for cpus,
  memory, disk and network
- standard deviation of the CPU load provided by MonD
- the count of instances with primary and secondary in the same failure
  domain
- the count of instances sharing the same exclusion tags which primary
  instances placed in the same failure domain
- the overall sum of dissatisfied desired locations among all cluster
  instances

The free memory and free disk values help ensure that all nodes are
somewhat balanced in their resource usage. The reserved memory helps
to ensure that nodes are somewhat balanced in holding secondary
instances, and that no node keeps too much memory reserved for
N+1. And finally, the N+1 percentage helps guide the algorithm towards
eliminating N+1 failures, if possible.

Except for the N+1 failures, offline instances counts, failure
domain violation counts and desired locations count, we use the
standard deviation since when used with values within a fixed range
(we use percents expressed as values between zero and one) it gives
consistent results across all metrics (there are some small issues
related to different means, but it works generally well). The 'count'
type values will have higher score and thus will matter more for
balancing; thus these are better for hard constraints (like evacuating
nodes and fixing N+1 failures). For example, the offline instances
count (i.e. the number of instances living on offline nodes) will
cause the algorithm to actively move instances away from offline
nodes. This, coupled with the restriction on placement given by
offline nodes, will cause evacuation of such nodes.

The dynamic load values need to be read from an external file (Ganeti
doesn't supply them), and are computed for each node as: sum of
primary instance cpu load, sum of primary instance memory load, sum of
primary and secondary instance disk load (as DRBD generates write load
on secondary nodes too in normal case and in degraded scenarios also
read load), and sum of primary instance network load. An example of
how to generate these values for input to hbal would be to track ``xm
list`` for instances over a day and by computing the delta of the cpu
values, and feed that via the *-U* option for all instances (and keep
the other metrics as one). For the algorithm to work, all that is
needed is that the values are consistent for a metric across all
instances (e.g. all instances use cpu% to report cpu usage, and not
something related to number of CPU seconds used if the CPUs are
different), and that they are normalised to between zero and one. Note
that it's recommended to not have zero as the load value for any
instance metric since then secondary instances are not well balanced.

The CPUload from MonD's data collector will be used only if all MonDs
are running, otherwise it won't affect the cluster score. Since we can't
find the CPU load of each instance, we can assume that the CPU load of
an instance is proportional to the number of its vcpus. With this
heuristic, instances from nodes with high CPU load will tend to move to
nodes with less CPU load.

On a perfectly balanced cluster (all nodes the same size, all
instances the same size and spread across the nodes equally,
all desired locations satisfied), the values for all metrics
would be zero, with the exception of the total percentage of
reserved memory. This doesn't happen too often in practice :)

OFFLINE INSTANCES
~~~~~~~~~~~~~~~~~

Since current Ganeti versions do not report the memory used by offline
(down) instances, ignoring the run status of instances will cause
wrong calculations. For this reason, the algorithm subtracts the
memory size of down instances from the free node memory of their
primary node, in effect simulating the startup of such instances.

DESIRED LOCATION TAGS
~~~~~~~~~~~~~~~~~~~~~

Sometimes, administrators want specific instances located in a particular,
typically geographic, location. To suppoer this desired location tags are
introduced.

If the cluster is tagged *htools:desiredlocation:x* then tags starting with
*x* are desired location tags. Instances can be assigned tags of the form *x*
that means that instance wants to be placed on a node tagged with a location
tag *x*. (That means that cluster should be tagged *htools:nlocation:x* too).

Instance pinning is just heuristics, not a hard enforced requirement;
it will only be achieved by the cluster metrics favouring such placements.

EXCLUSION TAGS
~~~~~~~~~~~~~~

The exclusion tags mechanism is designed to prevent instances which
run the same workload (e.g. two DNS servers) to land on the same node,
which would make the respective node a SPOF for the given service.

It works by tagging instances with certain tags and then building
exclusion maps based on these. Which tags are actually used is
configured either via the command line (option *\--exclusion-tags*)
or via adding them to the cluster tags:

\--exclusion-tags=a,b
  This will make all instance tags of the form *a:\**, *b:\** be
  considered for the exclusion map

cluster tags *htools:iextags:a*, *htools:iextags:b*
  This will make instance tags *a:\**, *b:\** be considered for the
  exclusion map. More precisely, the suffix of cluster tags starting
  with *htools:iextags:* will become the prefix of the exclusion tags.

Both the above forms mean that two instances both having (e.g.) the
tag *a:foo* or *b:bar* won't end on the same node.

MIGRATION TAGS
~~~~~~~~~~~~~~

If Ganeti is deployed on a heterogeneous cluster, migration might
not be possible between all nodes of a node group. One example of
such a situation is upgrading the hypervisor node by node. To make
hbal aware of those restrictions, the following cluster tags are used.

cluster tags *htools:migration:a*, *htools:migration:b*, etc
  This make make node tags of the form *a:\**, *b:\**, etc be considered
  migration restriction. More precisely, the suffix of cluster tags starting
  with *htools:migration:* will become the prefix of the migration tags.
  Only those migrations will be taken into consideration where all migration
  tags of the source node are also present on the target node.

cluster tags *htools:allowmigration:x::y* for migration tags *x* and *y*
  This asserts that a node taged *y* is able to receive instances in
  the same way as if they had an *x* tag.

So in the simple case of a hypervisor upgrade, tagging all the nodes
that have been upgraded with a migration tag suffices. In more complicated
situations, it is always possible to use a different migration tag for
each hypervisor used and explictly state the allowed migration directions
by means of *htools:allowmigration:* tags.

LOCATION TAGS
~~~~~~~~~~~~~

Within a node group, certain nodes might be more likely to fail simultaneously
due to a common cause of error (e.g., if they share the same power supply unit).
Ganeti can be made aware of thos common causes of failure by means of tags.

cluster tags *htools:nlocation:a*, *htools:nlocation:b*, etc
  This make make node tags of the form *a:\**, *b:\**, etc be considered
  to have a common cause of failure.

Instances with primary and secondary node having a common cause of failure and
instances sharing the same exclusion tag with primary nodes having a common
failure are considered badly placed. While such placements are always allowed,
they count heavily towards the cluster score.

OPTIONS
-------

The options that can be passed to the program are as follows:

-C, \--print-commands
  Print the command list at the end of the run. Without this, the
  program will only show a shorter, but cryptic output.

  Note that the moves list will be split into independent steps,
  called "jobsets", but only for visual inspection, not for actually
  parallelisation. It is not possible to parallelise these directly
  when executed via "gnt-instance" commands, since a compound command
  (e.g. failover and replace-disks) must be executed
  serially. Parallel execution is only possible when using the Luxi
  backend and the *-L* option.

  The algorithm for splitting the moves into jobsets is by
  accumulating moves until the next move is touching nodes already
  touched by the current moves; this means we can't execute in
  parallel (due to resource allocation in Ganeti) and thus we start a
  new jobset.

-p, \--print-nodes
  Prints the before and after node status, in a format designed to allow
  the user to understand the node's most important parameters. See the
  man page **htools**\(1) for more details about this option.

\--print-instances
  Prints the before and after instance map. This is less useful as the
  node status, but it can help in understanding instance moves.

-O *name*
  This option (which can be given multiple times) will mark nodes as
  being *offline*. This means a couple of things:

  - instances won't be placed on these nodes, not even temporarily;
    e.g. the *replace primary* move is not available if the secondary
    node is offline, since this move requires a failover.
  - these nodes will not be included in the score calculation (except
    for the percentage of instances on offline nodes)

  Note that algorithm will also mark as offline any nodes which are
  reported by RAPI as such, or that have "?" in file-based input in
  any numeric fields.

-e *score*, \--min-score=*score*
  This parameter denotes how much above the N+1 bound the cluster score
  can for us to be happy with and alters the computation in two ways:

  - if the cluster has the initial score lower than this value, then we
    don't enter the algorithm at all, and exit with success
  - during the iterative process, if we reach a score lower than this
    value, we exit the algorithm

  The default value of the parameter is currently ``1e-9`` (chosen
  empirically).

-g *delta*, \--min-gain=*delta*
  Since the balancing algorithm can sometimes result in just very tiny
  improvements, that bring less gain that they cost in relocation
  time, this parameter (defaulting to 0.01) represents the minimum
  gain we require during a step, to continue balancing.

\--min-gain-limit=*threshold*
  The above min-gain option will only take effect if the cluster score
  is already below *threshold* (defaults to 0.1). The rationale behind
  this setting is that at high cluster scores (badly balanced
  clusters), we don't want to abort the rebalance too quickly, as
  later gains might still be significant. However, under the
  threshold, the total gain is only the threshold value, so we can
  exit early.

\--no-disk-moves
  This parameter prevents hbal from using disk move
  (i.e. "gnt-instance replace-disks") operations. This will result in
  a much quicker balancing, but of course the improvements are
  limited. It is up to the user to decide when to use one or another.

\--no-instance-moves
  This parameter prevents hbal from using instance moves
  (i.e. "gnt-instance migrate/failover") operations. This will only use
  the slow disk-replacement operations, and will also provide a worse
  balance, but can be useful if moving instances around is deemed unsafe
  or not preferred.

\--evac-mode
  This parameter restricts the list of instances considered for moving
  to the ones living on offline/drained nodes. It can be used as a
  (bulk) replacement for Ganeti's own *gnt-node evacuate*, with the
  note that it doesn't guarantee full evacuation.

\--restricted-migration
  This parameter disallows any replace-primary moves (frf), as well as
  those replace-and-failover moves (rf) where the primary node of the
  instance is not drained. If used together with the ``--evac-mode``
  option, the only migrations that hbal will do are migrations of
  instances off a drained node. This can be useful if during a reinstall
  of the base operating system migration is only possible from the old
  OS to the new OS. Note, however, that usually the use of migration
  tags is the better choice.

\--select-instances=*instances*
  This parameter marks the given instances (as a comma-separated list)
  as the only ones being moved during the rebalance.

\--exclude-instances=*instances*
  This parameter marks the given instances (as a comma-separated list)
  from being moved during the rebalance.

-U *util-file*
  This parameter specifies a file holding instance dynamic utilisation
  information that will be used to tweak the balancing algorithm to
  equalise load on the nodes (as opposed to static resource
  usage). The file is in the format "instance_name cpu_util mem_util
  disk_util net_util" where the "_util" parameters are interpreted as
  numbers and the instance name must match exactly the instance as
  read from Ganeti. In case of unknown instance names, the program
  will abort.

  If not given, the default values are one for all metrics and thus
  dynamic utilisation has only one effect on the algorithm: the
  equalisation of the secondary instances across nodes (this is the
  only metric that is not tracked by another, dedicated value, and
  thus the disk load of instances will cause secondary instance
  equalisation). Note that value of one will also influence slightly
  the primary instance count, but that is already tracked via other
  metrics and thus the influence of the dynamic utilisation will be
  practically insignificant.

\--ignore-dynu
  If given, all dynamic utilisation information will be ignored by
  assuming it to be 0. This option will take precedence over any data
  passed by the ``-U`` option or by the MonDs with the ``--mond`` and
  the ``--mond-data`` option.

\--ignore-soft-errors
  If given, all checks for soft errors will be ommitted when considering
  balancing moves. In this way, progress can be made in a cluster where
  all nodes are in a policy-wise bad state, like exceeding oversubscription
  ratios on CPU or spindles.

-S *filename*, \--save-cluster=*filename*
  If given, the state of the cluster before the balancing is saved to
  the given file plus the extension "original"
  (i.e. *filename*.original), and the state at the end of the
  balancing is saved to the given file plus the extension "balanced"
  (i.e. *filename*.balanced). This allows re-feeding the cluster state
  to either hbal itself or for example hspace via the ``-t`` option.

-t *datafile*, \--text-data=*datafile*
  Backend specification: the name of the file holding node and instance
  information (if not collecting via RAPI or LUXI). This or one of the
  other backends must be selected. The option is described in the man
  page **htools**\(1).

\--mond=*yes|no*
  If given the program will query all MonDs to fetch data from the
  supported data collectors over the network.

\--mond-xen
  If given, also query Xen-specific collectors from MonD, provided
  that monitoring daemons are queried at all.

\--exit-on-missing-mond-data
  If given, abort if the data obtainable from querying MonDs is incomplete.
  The default behavior is to continue with a best guess based on the static
  information.

\--mond-data *datafile*
  The name of the file holding the data provided by MonD, to override
  quering MonDs over the network. This is mostly used for debugging. The
  file must be in JSON format and present an array of JSON objects ,
  one for every node, with two members. The first member named ``node``
  is the name of the node and the second member named ``reports`` is an
  array of report objects. The report objects must be in the same format
  as produced by the monitoring agent.

-m *cluster*
  Backend specification: collect data directly from the *cluster* given
  as an argument via RAPI. The option is described in the man page
  **htools**\(1).

-L [*path*]
  Backend specification: collect data directly from the master daemon,
  which is to be contacted via LUXI (an internal Ganeti protocol). The
  option is described in the man page **htools**\(1).

-X
  When using the Luxi backend, hbal can also execute the given
  commands. The execution method is to execute the individual jobsets
  (see the *-C* option for details) in separate stages, aborting if at
  any time a jobset doesn't have all jobs successful. Each step in the
  balancing solution will be translated into exactly one Ganeti job
  (having between one and three OpCodes), and all the steps in a
  jobset will be executed in parallel. The jobsets themselves are
  executed serially.

  The execution of the job series can be interrupted, see below for
  signal handling.

-l *N*, \--max-length=*N*
  Restrict the solution to this length. This can be used for example
  to automate the execution of the balancing.

\--max-cpu=*cpu-ratio*
  The maximum virtual to physical cpu ratio, as a floating point number
  greater than or equal to one. For example, specifying *cpu-ratio* as
  **2.5** means that, for a 4-cpu machine, a maximum of 10 virtual cpus
  should be allowed to be in use for primary instances. A value of
  exactly one means there will be no over-subscription of CPU (except
  for the CPU time used by the node itself), and values below one do not
  make sense, as that means other resources (e.g. disk) won't be fully
  utilised due to CPU restrictions.

\--min-disk=*disk-ratio*
  The minimum amount of free disk space remaining, as a floating point
  number. For example, specifying *disk-ratio* as **0.25** means that
  at least one quarter of disk space should be left free on nodes.

-G *uuid*, \--group=*uuid*
  On an multi-group cluster, select this group for
  processing. Otherwise hbal will abort, since it cannot balance
  multiple groups at the same time.

-v, \--verbose
  Increase the output verbosity. Each usage of this option will
  increase the verbosity (currently more than 2 doesn't make sense)
  from the default of one.

-q, \--quiet
  Decrease the output verbosity. Each usage of this option will
  decrease the verbosity (less than zero doesn't make sense) from the
  default of one.

-V, \--version
  Just show the program version and exit.

SIGNAL HANDLING
---------------

When executing jobs via LUXI (using the ``-X`` option), normally hbal
will execute all jobs until either one errors out or all the jobs finish
successfully.

Since balancing can take a long time, it is possible to stop hbal early
in two ways:

- by sending a ``SIGINT`` (``^C``), hbal will register the termination
  request, and will wait until the currently submitted jobs finish, at
  which point it will exit (with exit code 0 if all jobs finished
  correctly, otherwise with exit code 1 as usual)

- by sending a ``SIGTERM``, hbal will immediately exit (with exit code
  2\); it is the responsibility of the user to follow up with Ganeti
  and check the result of the currently-executing jobs

Note that in any situation, it's perfectly safe to kill hbal, either via
the above signals or via any other signal (e.g. ``SIGQUIT``,
``SIGKILL``), since the jobs themselves are processed by Ganeti whereas
hbal (after submission) only watches their progression. In this case,
the user will have to query Ganeti for job results.

EXIT STATUS
-----------

The exit status of the command will be zero, unless for some reason the
algorithm failed (e.g. wrong node or instance data), invalid command
line options, or (in case of job execution) one of the jobs has failed.

Once job execution via Luxi has started (``-X``), if the balancing was
interrupted early (via *SIGINT*, or via ``--max-length``) but all jobs
executed successfully, then the exit status is zero; a non-zero exit
code means that the cluster state should be investigated, since a job
failed or we couldn't compute its status and this can also point to a
problem on the Ganeti side.

BUGS
----

The program does not check all its input data for consistency, and
sometime aborts with cryptic errors messages with invalid data.

The algorithm is not perfect.

EXAMPLE
-------

Note that these examples are not for the latest version (they don't
have full node data).

Default output
~~~~~~~~~~~~~~

With the default options, the program shows each individual step and
the improvements it brings in cluster score::

    $ hbal
    Loaded 20 nodes, 80 instances
    Cluster is not N+1 happy, continuing but no guarantee that the cluster will end N+1 happy.
    Initial score: 0.52329131
    Trying to minimize the CV...
        1. instance14  node1:node10  => node16:node10 0.42109120 a=f r:node16 f
        2. instance54  node4:node15  => node16:node15 0.31904594 a=f r:node16 f
        3. instance4   node5:node2   => node2:node16  0.26611015 a=f r:node16
        4. instance48  node18:node20 => node2:node18  0.21361717 a=r:node2 f
        5. instance93  node19:node18 => node16:node19 0.16166425 a=r:node16 f
        6. instance89  node3:node20  => node2:node3   0.11005629 a=r:node2 f
        7. instance5   node6:node2   => node16:node6  0.05841589 a=r:node16 f
        8. instance94  node7:node20  => node20:node16 0.00658759 a=f r:node16
        9. instance44  node20:node2  => node2:node15  0.00438740 a=f r:node15
       10. instance62  node14:node18 => node14:node16 0.00390087 a=r:node16
       11. instance13  node11:node14 => node11:node16 0.00361787 a=r:node16
       12. instance19  node10:node11 => node10:node7  0.00336636 a=r:node7
       13. instance43  node12:node13 => node12:node1  0.00305681 a=r:node1
       14. instance1   node1:node2   => node1:node4   0.00263124 a=r:node4
       15. instance58  node19:node20 => node19:node17 0.00252594 a=r:node17
    Cluster score improved from 0.52329131 to 0.00252594

In the above output, we can see:

- the input data (here from files) shows a cluster with 20 nodes and
  80 instances
- the cluster is not initially N+1 compliant
- the initial score is 0.52329131

The step list follows, showing the instance, its initial
primary/secondary nodes, the new primary secondary, the cluster list,
and the actions taken in this step (with 'f' denoting failover/migrate
and 'r' denoting replace secondary).

Finally, the program shows the improvement in cluster score.

A more detailed output is obtained via the *-C* and *-p* options::

    $ hbal
    Loaded 20 nodes, 80 instances
    Cluster is not N+1 happy, continuing but no guarantee that the cluster will end N+1 happy.
    Initial cluster status:
    N1 Name   t_mem f_mem r_mem t_dsk f_dsk pri sec  p_fmem  p_fdsk
     * node1  32762  1280  6000  1861  1026   5   3 0.03907 0.55179
       node2  32762 31280 12000  1861  1026   0   8 0.95476 0.55179
     * node3  32762  1280  6000  1861  1026   5   3 0.03907 0.55179
     * node4  32762  1280  6000  1861  1026   5   3 0.03907 0.55179
     * node5  32762  1280  6000  1861   978   5   5 0.03907 0.52573
     * node6  32762  1280  6000  1861  1026   5   3 0.03907 0.55179
     * node7  32762  1280  6000  1861  1026   5   3 0.03907 0.55179
       node8  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node9  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
     * node10 32762  7280 12000  1861  1026   4   4 0.22221 0.55179
       node11 32762  7280  6000  1861   922   4   5 0.22221 0.49577
       node12 32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node13 32762  7280  6000  1861   922   4   5 0.22221 0.49577
       node14 32762  7280  6000  1861   922   4   5 0.22221 0.49577
     * node15 32762  7280 12000  1861  1131   4   3 0.22221 0.60782
       node16 32762 31280     0  1861  1860   0   0 0.95476 1.00000
       node17 32762  7280  6000  1861  1106   5   3 0.22221 0.59479
     * node18 32762  1280  6000  1396   561   5   3 0.03907 0.40239
     * node19 32762  1280  6000  1861  1026   5   3 0.03907 0.55179
       node20 32762 13280 12000  1861   689   3   9 0.40535 0.37068

    Initial score: 0.52329131
    Trying to minimize the CV...
        1. instance14  node1:node10  => node16:node10 0.42109120 a=f r:node16 f
        2. instance54  node4:node15  => node16:node15 0.31904594 a=f r:node16 f
        3. instance4   node5:node2   => node2:node16  0.26611015 a=f r:node16
        4. instance48  node18:node20 => node2:node18  0.21361717 a=r:node2 f
        5. instance93  node19:node18 => node16:node19 0.16166425 a=r:node16 f
        6. instance89  node3:node20  => node2:node3   0.11005629 a=r:node2 f
        7. instance5   node6:node2   => node16:node6  0.05841589 a=r:node16 f
        8. instance94  node7:node20  => node20:node16 0.00658759 a=f r:node16
        9. instance44  node20:node2  => node2:node15  0.00438740 a=f r:node15
       10. instance62  node14:node18 => node14:node16 0.00390087 a=r:node16
       11. instance13  node11:node14 => node11:node16 0.00361787 a=r:node16
       12. instance19  node10:node11 => node10:node7  0.00336636 a=r:node7
       13. instance43  node12:node13 => node12:node1  0.00305681 a=r:node1
       14. instance1   node1:node2   => node1:node4   0.00263124 a=r:node4
       15. instance58  node19:node20 => node19:node17 0.00252594 a=r:node17
    Cluster score improved from 0.52329131 to 0.00252594

    Commands to run to reach the above solution:
      echo step 1
      echo gnt-instance migrate instance14
      echo gnt-instance replace-disks -n node16 instance14
      echo gnt-instance migrate instance14
      echo step 2
      echo gnt-instance migrate instance54
      echo gnt-instance replace-disks -n node16 instance54
      echo gnt-instance migrate instance54
      echo step 3
      echo gnt-instance migrate instance4
      echo gnt-instance replace-disks -n node16 instance4
      echo step 4
      echo gnt-instance replace-disks -n node2 instance48
      echo gnt-instance migrate instance48
      echo step 5
      echo gnt-instance replace-disks -n node16 instance93
      echo gnt-instance migrate instance93
      echo step 6
      echo gnt-instance replace-disks -n node2 instance89
      echo gnt-instance migrate instance89
      echo step 7
      echo gnt-instance replace-disks -n node16 instance5
      echo gnt-instance migrate instance5
      echo step 8
      echo gnt-instance migrate instance94
      echo gnt-instance replace-disks -n node16 instance94
      echo step 9
      echo gnt-instance migrate instance44
      echo gnt-instance replace-disks -n node15 instance44
      echo step 10
      echo gnt-instance replace-disks -n node16 instance62
      echo step 11
      echo gnt-instance replace-disks -n node16 instance13
      echo step 12
      echo gnt-instance replace-disks -n node7 instance19
      echo step 13
      echo gnt-instance replace-disks -n node1 instance43
      echo step 14
      echo gnt-instance replace-disks -n node4 instance1
      echo step 15
      echo gnt-instance replace-disks -n node17 instance58

    Final cluster status:
    N1 Name   t_mem f_mem r_mem t_dsk f_dsk pri sec  p_fmem  p_fdsk
       node1  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node2  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node3  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node4  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node5  32762  7280  6000  1861  1078   4   5 0.22221 0.57947
       node6  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node7  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node8  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node9  32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node10 32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node11 32762  7280  6000  1861  1022   4   4 0.22221 0.54951
       node12 32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node13 32762  7280  6000  1861  1022   4   4 0.22221 0.54951
       node14 32762  7280  6000  1861  1022   4   4 0.22221 0.54951
       node15 32762  7280  6000  1861  1031   4   4 0.22221 0.55408
       node16 32762  7280  6000  1861  1060   4   4 0.22221 0.57007
       node17 32762  7280  6000  1861  1006   5   4 0.22221 0.54105
       node18 32762  7280  6000  1396   761   4   2 0.22221 0.54570
       node19 32762  7280  6000  1861  1026   4   4 0.22221 0.55179
       node20 32762 13280  6000  1861  1089   3   5 0.40535 0.58565

Here we see, beside the step list, the initial and final cluster
status, with the final one showing all nodes being N+1 compliant, and
the command list to reach the final solution. In the initial listing,
we see which nodes are not N+1 compliant.

The algorithm is stable as long as each step above is fully completed,
e.g. in step 8, both the migrate and the replace-disks are
done. Otherwise, if only the migrate is done, the input data is
changed in a way that the program will output a different solution
list (but hopefully will end in the same state).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
