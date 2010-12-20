HSPACE(1) htools | Ganeti H-tools
=================================

NAME
----

hspace - Cluster space analyzer for Ganeti

SYNOPSIS
--------

**hspace** {backend options...} [algorithm options...] [request options...]
[ -p [*fields*] ] [-v... | -q]

**hspace** --version

Backend options:

{ **-m** *cluster* | **-L[** *path* **] [-X]** | **-t** *data-file* |
**--simulate** *spec* }


Algorithm options:

**[ --max-cpu *cpu-ratio* ]**
**[ --min-disk *disk-ratio* ]**
**[ -O *name...* ]**


Request options:

**[--memory** *mem* **]**
**[--disk** *disk* **]**
**[--req-nodes** *req-nodes* **]**
**[--vcpus** *vcpus* **]**
**[--tiered-alloc** *spec* **]**


DESCRIPTION
-----------


hspace computes how many additional instances can be fit on a cluster,
while maintaining N+1 status.

The program will try to place instances, all of the same size, on the
cluster, until the point where we don't have any N+1 possible
allocation. It uses the exact same allocation algorithm as the hail
iallocator plugin.

The output of the program is designed to interpreted as a shell
fragment (or parsed as a *key=value* file). Options which extend the
output (e.g. -p, -v) will output the additional information on stderr
(such that the stdout is still parseable).

The following keys are available in the output of the script (all
prefixed with *HTS_*):

SPEC_MEM, SPEC_DSK, SPEC_CPU, SPEC_RQN
  These represent the specifications of the instance model used for
  allocation (the memory, disk, cpu, requested nodes).

CLUSTER_MEM, CLUSTER_DSK, CLUSTER_CPU, CLUSTER_NODES
  These represent the total memory, disk, CPU count and total nodes in
  the cluster.

INI_SCORE, FIN_SCORE
  These are the initial (current) and final cluster score (see the hbal
  man page for details about the scoring algorithm).

INI_INST_CNT, FIN_INST_CNT
  The initial and final instance count.

INI_MEM_FREE, FIN_MEM_FREE
  The initial and final total free memory in the cluster (but this
  doesn't necessarily mean available for use).

INI_MEM_AVAIL, FIN_MEM_AVAIL
  The initial and final total available memory for allocation in the
  cluster. If allocating redundant instances, new instances could
  increase the reserved memory so it doesn't necessarily mean the
  entirety of this memory can be used for new instance allocations.

INI_MEM_RESVD, FIN_MEM_RESVD
  The initial and final reserved memory (for redundancy/N+1 purposes).

INI_MEM_INST, FIN_MEM_INST
  The initial and final memory used for instances (actual runtime used
  RAM).

INI_MEM_OVERHEAD, FIN_MEM_OVERHEAD
  The initial and final memory overhead--memory used for the node
  itself and unacounted memory (e.g. due to hypervisor overhead).

INI_MEM_EFF, HTS_INI_MEM_EFF
  The initial and final memory efficiency, represented as instance
  memory divided by total memory.

INI_DSK_FREE, INI_DSK_AVAIL, INI_DSK_RESVD, INI_DSK_INST, INI_DSK_EFF
  Initial disk stats, similar to the memory ones.

FIN_DSK_FREE, FIN_DSK_AVAIL, FIN_DSK_RESVD, FIN_DSK_INST, FIN_DSK_EFF
  Final disk stats, similar to the memory ones.

INI_CPU_INST, FIN_CPU_INST
  Initial and final number of virtual CPUs used by instances.

INI_CPU_EFF, FIN_CPU_EFF
  The initial and final CPU efficiency, represented as the count of
  virtual instance CPUs divided by the total physical CPU count.

INI_MNODE_MEM_AVAIL, FIN_MNODE_MEM_AVAIL
  The initial and final maximum per-node available memory. This is not
  very useful as a metric but can give an impression of the status of
  the nodes; as an example, this value restricts the maximum instance
  size that can be still created on the cluster.

INI_MNODE_DSK_AVAIL, FIN_MNODE_DSK_AVAIL
  Like the above but for disk.

TSPEC
  If the tiered allocation mode has been enabled, this parameter holds
  the pairs of specifications and counts of instances that can be
  created in this mode. The value of the key is a space-separated list
  of values; each value is of the form *memory,disk,vcpu=count* where
  the memory, disk and vcpu are the values for the current spec, and
  count is how many instances of this spec can be created. A complete
  value for this variable could be: **4096,102400,2=225
  2560,102400,2=20 512,102400,2=21**.

KM_USED_CPU, KM_USED_NPU, KM_USED_MEM, KM_USED_DSK
  These represents the metrics of used resources at the start of the
  computation (only for tiered allocation mode). The NPU value is
  "normalized" CPU count, i.e. the number of virtual CPUs divided by
  the maximum ratio of the virtual to physical CPUs.

KM_POOL_CPU, KM_POOL_NPU, KM_POOL_MEM, KM_POOL_DSK
  These represents the total resources allocated during the tiered
  allocation process. In effect, they represent how much is readily
  available for allocation.

KM_UNAV_CPU, KM_POOL_NPU, KM_UNAV_MEM, KM_UNAV_DSK
  These represents the resources left over (either free as in
  unallocable or allocable on their own) after the tiered allocation
  has been completed. They represent better the actual unallocable
  resources, because some other resource has been exhausted. For
  example, the cluster might still have 100GiB disk free, but with no
  memory left for instances, we cannot allocate another instance, so
  in effect the disk space is unallocable. Note that the CPUs here
  represent instance virtual CPUs, and in case the *--max-cpu* option
  hasn't been specified this will be -1.

ALLOC_USAGE
  The current usage represented as initial number of instances divided
  per final number of instances.

ALLOC_COUNT
  The number of instances allocated (delta between FIN_INST_CNT and
  INI_INST_CNT).

ALLOC_FAIL*_CNT
  For the last attemp at allocations (which would have increased
  FIN_INST_CNT with one, if it had succeeded), this is the count of
  the failure reasons per failure type; currently defined are FAILMEM,
  FAILDISK and FAILCPU which represent errors due to not enough
  memory, disk and CPUs, and FAILN1 which represents a non N+1
  compliant cluster on which we can't allocate instances at all.

ALLOC_FAIL_REASON
  The reason for most of the failures, being one of the above FAIL*
  strings.

OK
  A marker representing the successful end of the computation, and
  having value "1". If this key is not present in the output it means
  that the computation failed and any values present should not be
  relied upon.

If the tiered allocation mode is enabled, then many of the INI_/FIN_
metrics will be also displayed with a TRL_ prefix, and denote the
cluster status at the end of the tiered allocation run.

OPTIONS
-------

The options that can be passed to the program are as follows:

--memory *mem*
  The memory size of the instances to be placed (defaults to 4GiB).

--disk *disk*
  The disk size of the instances to be placed (defaults to 100GiB).

--req-nodes *num-nodes*
  The number of nodes for the instances; the default of two means
  mirrored instances, while passing one means plain type instances.

--vcpus *vcpus*
  The number of VCPUs of the instances to be placed (defaults to 1).

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

-O *name*
  This option (which can be given multiple times) will mark nodes as
  being *offline*. This means a couple of things:

  - instances won't be placed on these nodes, not even temporarily;
    e.g. the *replace primary* move is not available if the secondary
    node is offline, since this move requires a failover.
  - these nodes will not be included in the score calculation (except
    for the percentage of instances on offline nodes)

  Note that the algorithm will also mark as offline any nodes which
  are reported by RAPI as such, or that have "?" in file-based input
  in any numeric fields.

-t *datafile*, --text-data=*datafile*
  The name of the file holding node and instance information (if not
  collecting via RAPI or LUXI). This or one of the other backends must
  be selected.

-S *filename*, --save-cluster=*filename*
  If given, the state of the cluster at the end of the allocation is
  saved to a file named *filename.alloc*, and if tiered allocation is
  enabled, the state after tiered allocation will be saved to
  *filename.tiered*. This allows re-feeding the cluster state to
  either hspace itself (with different parameters) or for example
  hbal.

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

--simulate *description*
  Instead of using actual data, build an empty cluster given a node
  description. The *description* parameter must be a comma-separated
  list of five elements, describing in order:

  - the allocation policy for this node group
  - the number of nodes in the cluster
  - the disk size of the nodes, in mebibytes
  - the memory size of the nodes, in mebibytes
  - the cpu core count for the nodes

  An example description would be **preferred,B20,102400,16384,4**
  describing a 20-node cluster where each node has 100GiB of disk
  space, 16GiB of memory and 4 CPU cores. Note that all nodes must
  have the same specs currently.

  This option can be given multiple times, and each new use defines a
  new node group. Hence different node groups can have different
  allocation policies and node count/specifications.

--tiered-alloc *spec*
  Besides the standard, fixed-size allocation, also do a tiered
  allocation scheme where the algorithm starts from the given
  specification and allocates until there is no more space; then it
  decreases the specification and tries the allocation again. The
  decrease is done on the matric that last failed during
  allocation. The specification given is similar to the *--simulate*
  option and it holds:

  - the disk size of the instance
  - the memory size of the instance
  - the vcpu count for the insance

  An example description would be *10240,8192,2* describing an initial
  starting specification of 10GiB of disk space, 4GiB of memory and 2
  VCPUs.

  Also note that the normal allocation and the tiered allocation are
  independent, and both start from the initial cluster state; as such,
  the instance count for these two modes are not related one to
  another.

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

The exist status of the command will be zero, unless for some reason
the algorithm fatally failed (e.g. wrong node or instance data).

BUGS
----

The algorithm is highly dependent on the number of nodes; its runtime
grows exponentially with this number, and as such is impractical for
really big clusters.

The algorithm doesn't rebalance the cluster or try to get the optimal
fit; it just allocates in the best place for the current step, without
taking into consideration the impact on future placements.

ENVIRONMENT
-----------

If the variables **HTOOLS_NODES** and **HTOOLS_INSTANCES** are present
in the environment, they will override the default names for the nodes
and instances files. These will have of course no effect when the RAPI
or Luxi backends are used.

SEE ALSO
--------

**hbal**(1), **hscan**(1), **hail**(1), **ganeti**(7),
**gnt-instance**(8), **gnt-node**(8)

COPYRIGHT
---------

Copyright (C) 2009, 2010 Google Inc. Permission is granted to copy,
distribute and/or modify under the terms of the GNU General Public
License as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

On Debian systems, the complete text of the GNU General Public License
can be found in /usr/share/common-licenses/GPL.
