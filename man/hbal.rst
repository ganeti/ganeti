HBAL(1) htools | Ganeti H-tools
===============================

NAME
----

hbal \- Cluster balancer for Ganeti

SYNOPSIS
--------

**hbal** {backend options...} [algorithm options...] [reporting options...]

**hbal** --version


Backend options:

{ **-m** *cluster* | **-L[** *path* **] [-X]** | **-t** *data-file* }

Algorithm options:

**[ --max-cpu *cpu-ratio* ]**
**[ --min-disk *disk-ratio* ]**
**[ -l *limit* ]**
**[ -e *score* ]**
**[ -g *delta* ]** **[ --min-gain-limit *threshold* ]**
**[ -O *name...* ]**
**[ --no-disk-moves ]**
**[ -U *util-file* ]**
**[ --evac-mode ]**
**[ --exclude-instances *inst...* ]**

Reporting options:

**[ -C[ *file* ] ]**
**[ -p[ *fields* ] ]**
**[ --print-instances ]**
**[ -o ]**
**[ -v... | -q ]**


DESCRIPTION
-----------

hbal is a cluster balancer that looks at the current state of the
cluster (nodes with their total and free disk, memory, etc.) and
instance placement and computes a series of steps designed to bring
the cluster into a better state.

The algorithm used is designed to be stable (i.e. it will give you the
same results when restarting it from the middle of the solution) and
reasonably fast. It is not, however, designed to be a perfect
algorithm--it is possible to make it go into a corner from which
it can find no improvement, because it looks only one "step" ahead.

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
  read from the cluster or declared with *-O*)
- an exclusion-tag based conflict (exclusion tags are read from the
  cluster and/or defined via the *--exclusion-tags* option)
- a max vcpu/pcpu ratio to be exceeded (configured via *--max-cpu*)
- min disk free percentage to go below the configured limit
  (configured via *--min-disk*)

CLUSTER SCORING
~~~~~~~~~~~~~~~

As said before, the algorithm tries to minimise the cluster score at
each step. Currently this score is computed as a sum of the following
components:

- standard deviation of the percent of free memory
- standard deviation of the percent of reserved memory
- standard deviation of the percent of free disk
- count of nodes failing N+1 check
- count of instances living (either as primary or secondary) on
  offline nodes
- count of instances living (as primary) on offline nodes; this
  differs from the above metric by helping failover of such instances
  in 2-node clusters
- standard deviation of the ratio of virtual-to-physical cpus (for
  primary instances of the node)
- standard deviation of the dynamic load on the nodes, for cpus,
  memory, disk and network

The free memory and free disk values help ensure that all nodes are
somewhat balanced in their resource usage. The reserved memory helps
to ensure that nodes are somewhat balanced in holding secondary
instances, and that no node keeps too much memory reserved for
N+1. And finally, the N+1 percentage helps guide the algorithm towards
eliminating N+1 failures, if possible.

Except for the N+1 failures and offline instances counts, we use the
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

On a perfectly balanced cluster (all nodes the same size, all
instances the same size and spread across the nodes equally), the
values for all metrics would be zero. This doesn't happen too often in
practice :)

OFFLINE INSTANCES
~~~~~~~~~~~~~~~~~

Since current Ganeti versions do not report the memory used by offline
(down) instances, ignoring the run status of instances will cause
wrong calculations. For this reason, the algorithm subtracts the
memory size of down instances from the free node memory of their
primary node, in effect simulating the startup of such instances.

EXCLUSION TAGS
~~~~~~~~~~~~~~

The exclusion tags mechanism is designed to prevent instances which
run the same workload (e.g. two DNS servers) to land on the same node,
which would make the respective node a SPOF for the given service.

It works by tagging instances with certain tags and then building
exclusion maps based on these. Which tags are actually used is
configured either via the command line (option *--exclusion-tags*)
or via adding them to the cluster tags:

--exclusion-tags=a,b
  This will make all instance tags of the form *a:\**, *b:\** be
  considered for the exclusion map

cluster tags *htools:iextags:a*, *htools:iextags:b*
  This will make instance tags *a:\**, *b:\** be considered for the
  exclusion map. More precisely, the suffix of cluster tags starting
  with *htools:iextags:* will become the prefix of the exclusion tags.

Both the above forms mean that two instances both having (e.g.) the
tag *a:foo* or *b:bar* won't end on the same node.

OPTIONS
-------

The options that can be passed to the program are as follows:

-C, --print-commands
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

-p, --print-nodes
  Prints the before and after node status, in a format designed to
  allow the user to understand the node's most important parameters.

  It is possible to customise the listed information by passing a
  comma-separated list of field names to this option (the field list
  is currently undocumented), or to extend the default field list by
  prefixing the additional field list with a plus sign. By default,
  the node list will contain the following information:

  F
    a character denoting the status of the node, with '-' meaning an
    offline node, '*' meaning N+1 failure and blank meaning a good
    node

  Name
    the node name

  t_mem
    the total node memory

  n_mem
    the memory used by the node itself

  i_mem
    the memory used by instances

  x_mem
    amount memory which seems to be in use but cannot be determined
    why or by which instance; usually this means that the hypervisor
    has some overhead or that there are other reporting errors

  f_mem
    the free node memory

  r_mem
    the reserved node memory, which is the amount of free memory
    needed for N+1 compliance

  t_dsk
    total disk

  f_dsk
    free disk

  pcpu
    the number of physical cpus on the node

  vcpu
    the number of virtual cpus allocated to primary instances

  pcnt
    number of primary instances

  scnt
    number of secondary instances

  p_fmem
    percent of free memory

  p_fdsk
    percent of free disk

  r_cpu
    ratio of virtual to physical cpus

  lCpu
    the dynamic CPU load (if the information is available)

  lMem
    the dynamic memory load (if the information is available)

  lDsk
    the dynamic disk load (if the information is available)

  lNet
    the dynamic net load (if the information is available)

--print-instances
  Prints the before and after instance map. This is less useful as the
  node status, but it can help in understanding instance moves.

-o, --oneline
  Only shows a one-line output from the program, designed for the case
  when one wants to look at multiple clusters at once and check their
  status.

  The line will contain four fields:

  - initial cluster score
  - number of steps in the solution
  - final cluster score
  - improvement in the cluster score

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

-e *score*, --min-score=*score*
  This parameter denotes the minimum score we are happy with and alters
  the computation in two ways:

  - if the cluster has the initial score lower than this value, then we
    don't enter the algorithm at all, and exit with success
  - during the iterative process, if we reach a score lower than this
    value, we exit the algorithm

  The default value of the parameter is currently ``1e-9`` (chosen
  empirically).

-g *delta*, --min-gain=*delta*
  Since the balancing algorithm can sometimes result in just very tiny
  improvements, that bring less gain that they cost in relocation
  time, this parameter (defaulting to 0.01) represents the minimum
  gain we require during a step, to continue balancing.

--min-gain-limit=*threshold*
  The above min-gain option will only take effect if the cluster score
  is already below *threshold* (defaults to 0.1). The rationale behind
  this setting is that at high cluster scores (badly balanced
  clusters), we don't want to abort the rebalance too quickly, as
  later gains might still be significant. However, under the
  threshold, the total gain is only the threshold value, so we can
  exit early.

--no-disk-moves
  This parameter prevents hbal from using disk move
  (i.e. "gnt-instance replace-disks") operations. This will result in
  a much quicker balancing, but of course the improvements are
  limited. It is up to the user to decide when to use one or another.

--evac-mode
  This parameter restricts the list of instances considered for moving
  to the ones living on offline/drained nodes. It can be used as a
  (bulk) replacement for Ganeti's own *gnt-node evacuate*, with the
  note that it doesn't guarantee full evacuation.

--exclude-instances=*instances*
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

-t *datafile*, --text-data=*datafile*
  The name of the file holding node and instance information (if not
  collecting via RAPI or LUXI). This or one of the other backends must
  be selected.

-S *filename*, --save-cluster=*filename*
  If given, the state of the cluster before the balancing is saved to
  the given file plus the extension "original"
  (i.e. *filename*.original), and the state at the end of the
  balancing is saved to the given file plus the extension "balanced"
  (i.e. *filename*.balanced). This allows re-feeding the cluster state
  to either hbal itself or for example hspace.

-m *cluster*
 Collect data directly from the *cluster* given as an argument via
 RAPI. If the argument doesn't contain a colon (:), then it is
 converted into a fully-built URL via prepending ``https://`` and
 appending the default RAPI port, otherwise it's considered a
 fully-specified URL and is used as-is.

-L [*path*]
  Collect data directly from the master daemon, which is to be
  contacted via the luxi (an internal Ganeti protocol). An optional
  *path* argument is interpreted as the path to the unix socket on
  which the master daemon listens; otherwise, the default path used by
  ganeti when installed with *--localstatedir=/var* is used.

-X
  When using the Luxi backend, hbal can also execute the given
  commands. The execution method is to execute the individual jobsets
  (see the *-C* option for details) in separate stages, aborting if at
  any time a jobset doesn't have all jobs successful. Each step in the
  balancing solution will be translated into exactly one Ganeti job
  (having between one and three OpCodes), and all the steps in a
  jobset will be executed in parallel. The jobsets themselves are
  executed serially.

-l *N*, --max-length=*N*
  Restrict the solution to this length. This can be used for example
  to automate the execution of the balancing.

--max-cpu=*cpu-ratio*
  The maximum virtual to physical cpu ratio, as a floating point
  number between zero and one. For example, specifying *cpu-ratio* as
  **2.5** means that, for a 4-cpu machine, a maximum of 10 virtual
  cpus should be allowed to be in use for primary instances. A value
  of one doesn't make sense though, as that means no disk space can be
  used on it.

--min-disk=*disk-ratio*
  The minimum amount of free disk space remaining, as a floating point
  number. For example, specifying *disk-ratio* as **0.25** means that
  at least one quarter of disk space should be left free on nodes.

-G *uuid*, --group=*uuid*
  On an multi-group cluster, select this group for
  processing. Otherwise hbal will abort, since it cannot balance
  multiple groups at the same time.

-v, --verbose
  Increase the output verbosity. Each usage of this option will
  increase the verbosity (currently more than 2 doesn't make sense)
  from the default of one.

-q, --quiet
  Decrease the output verbosity. Each usage of this option will
  decrease the verbosity (less than zero doesn't make sense) from the
  default of one.

-V, --version
  Just show the program version and exit.

EXIT STATUS
-----------

The exit status of the command will be zero, unless for some reason
the algorithm fatally failed (e.g. wrong node or instance data), or
(in case of job execution) any job has failed.

ENVIRONMENT
-----------

If the variables **HTOOLS_NODES** and **HTOOLS_INSTANCES** are present
in the environment, they will override the default names for the nodes
and instances files. These will have of course no effect when the RAPI
or Luxi backends are used.

BUGS
----

The program does not check its input data for consistency, and aborts
with cryptic errors messages in this case.

The algorithm is not perfect.

The output format is not easily scriptable, and the program should
feed moves directly into Ganeti (either via RAPI or via a gnt-debug
input file).

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

SEE ALSO
--------

**hspace**(1), **hscan**(1), **hail**(1), **ganeti**(7),
**gnt-instance**(8), **gnt-node**(8)

COPYRIGHT
---------

Copyright (C) 2009, 2010 Google Inc. Permission is granted to copy,
distribute and/or modify under the terms of the GNU General Public
License as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

On Debian systems, the complete text of the GNU General Public License
can be found in /usr/share/common-licenses/GPL.
