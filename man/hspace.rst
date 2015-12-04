HSPACE(1) Ganeti | Version @GANETI_VERSION@
===========================================

NAME
----

hspace - Cluster space analyzer for Ganeti

SYNOPSIS
--------

**hspace** {backend options...} [algorithm options...] [request options...]
[output options...] [-v... | -q]

**hspace** \--version

Backend options:

{ **-m** *cluster* | **-L[** *path* **]** | **-t** *data-file* |
**\--simulate** *spec* | **-I** *path* }


Algorithm options:

**[ \--max-cpu *cpu-ratio* ]**
**[ \--min-disk *disk-ratio* ]**
**[ -O *name...* ]**
**[ \--independent-groups ]**
**[ \--no-capacity-checks ]**

Request options:

**[\--disk-template** *template* **]**

**[\--standard-alloc** *disk,ram,cpu*  **]**

**[\--tiered-alloc** *disk,ram,cpu* **]**

Output options:

**[\--machine-readable**[=*CHOICE*] **]**
**[-p**[*fields*]**]**


DESCRIPTION
-----------

hspace computes how many additional instances can be fit on a cluster,
while maintaining N+1 status.

The program will try to place instances, all of the same size, on the
cluster, until the point where we don't have any N+1 possible
allocation. It uses the exact same allocation algorithm as the hail
iallocator plugin in *allocate* mode.

The output of the program is designed either for human consumption (the
default) or, when enabled with the ``--machine-readable`` option
(described further below), for machine consumption. In the latter case,
it is intended to interpreted as a shell fragment (or parsed as a
*key=value* file). Options which extend the output (e.g. -p, -v) will
output the additional information on stderr (such that the stdout is
still parseable).

By default, the instance specifications will be read from the cluster;
the options ``--standard-alloc`` and ``--tiered-alloc`` can be used to
override them.

The following keys are available in the machine-readable output of the
script (all prefixed with *HTS_*):

SPEC_MEM, SPEC_DSK, SPEC_CPU, SPEC_RQN, SPEC_DISK_TEMPLATE, SPEC_SPN
  These represent the specifications of the instance model used for
  allocation (the memory, disk, cpu, requested nodes, disk template,
  spindles).

TSPEC_INI_MEM, TSPEC_INI_DSK, TSPEC_INI_CPU, ...
  Only defined when the tiered mode allocation is enabled, these are
  similar to the above specifications but show the initial starting spec
  for tiered allocation.

CLUSTER_MEM, CLUSTER_DSK, CLUSTER_CPU, CLUSTER_NODES, CLUSTER_SPN
  These represent the total memory, disk, CPU count, total nodes, and
  total spindles in the cluster.

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
  The initial and final memory overhead, i.e. memory used for the node
  itself and unaccounted memory (e.g. due to hypervisor overhead).

INI_MEM_EFF, HTS_INI_MEM_EFF
  The initial and final memory efficiency, represented as instance
  memory divided by total memory.

INI_DSK_FREE, INI_DSK_AVAIL, INI_DSK_RESVD, INI_DSK_INST, INI_DSK_EFF
  Initial disk stats, similar to the memory ones.

FIN_DSK_FREE, FIN_DSK_AVAIL, FIN_DSK_RESVD, FIN_DSK_INST, FIN_DSK_EFF
  Final disk stats, similar to the memory ones.

INI_SPN_FREE, ..., FIN_SPN_FREE, ..
  Initial and final spindles stats, similar to memory ones.

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
  This parameter holds the pairs of specifications and counts of
  instances that can be created in the *tiered allocation* mode. The
  value of the key is a space-separated list of values; each value is of
  the form *memory,disk,vcpu,spindles=count* where the memory, disk and vcpu are
  the values for the current spec, and count is how many instances of
  this spec can be created. A complete value for this variable could be:
  **4096,102400,2,1=225 2560,102400,2,1=20 512,102400,2,1=21**.

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
  represent instance virtual CPUs, and in case the *\--max-cpu* option
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

Many of the ``INI_``/``FIN_`` metrics will be also displayed with a
``TRL_`` prefix, and denote the cluster status at the end of the tiered
allocation run.

The human output format should be self-explanatory, so it is not
described further.

OPTIONS
-------

The options that can be passed to the program are as follows:

\--disk-template *template*
  Overrides the disk template for the instance read from the cluster;
  one of the Ganeti disk templates (e.g. plain, drbd, so on) should be
  passed in.

\--spindle-use *spindles*
  Override the spindle use for the instance read from the cluster. The
  value can be 0 (for example for instances that use very low I/O), but not
  negative. For shared storage the value is ignored.

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

\--independent-groups
  Consider all groups independent. That is, if a node that is not N+1
  happy is found, ignore its group, but still do allocation in the other
  groups. The default is to not try allocation at all, if some not N+1
  happy node is found.

\--accept-existing-errors
  This is a strengthened form of \--independent-groups. It tells hspace
  to ignore the presence of not N+1 happy nodes and just allocate on
  all other nodes without introducing new N+1 violations. Note that this
  tends to overestimate the capacity, as instances still have to be
  moved away from the existing not N+1 happy nodes.

\--no-capacity-checks
  Normally, hspace will only consider those allocations where all instances
  of a node can immediately restarted should that node fail. With this
  option given, hspace will check only N+1 redundancy for DRBD instances.

-l *rounds*, \--max-length=*rounds*
  Restrict the number of instance allocations to this length. This is
  not very useful in practice, but can be used for testing hspace
  itself, or to limit the runtime for very big clusters.

-p, \--print-nodes
  Prints the before and after node status, in a format designed to allow
  the user to understand the node's most important parameters. See the
  man page **htools**\(1) for more details about this option.

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

-S *filename*, \--save-cluster=*filename*
  If given, the state of the cluster at the end of the allocation is
  saved to a file named *filename.alloc*, and if tiered allocation is
  enabled, the state after tiered allocation will be saved to
  *filename.tiered*. This allows re-feeding the cluster state to
  either hspace itself (with different parameters) or for example
  hbal, via the ``-t`` option.

-t *datafile*, \--text-data=*datafile*
  Backend specification: the name of the file holding node and instance
  information (if not collecting via RAPI or LUXI). This or one of the
  other backends must be selected. The option is described in the man
  page **htools**\(1).

-m *cluster*
  Backend specification: collect data directly from the *cluster* given
  as an argument via RAPI. The option is described in the man page
  **htools**\(1).

-L [*path*]
  Backend specification: collect data directly from the master daemon,
  which is to be contacted via LUXI (an internal Ganeti protocol). The
  option is described in the man page **htools**\(1).

\--simulate *description*
  Backend specification: similar to the **-t** option, this allows
  overriding the cluster data with a simulated cluster. For details
  about the description, see the man page **htools**\(1).

\--standard-alloc *disk,ram,cpu*
  This option overrides the instance size read from the cluster for the
  *standard* allocation mode, where we simply allocate instances of the
  same, fixed size until the cluster runs out of space.

  The specification given is similar to the *\--simulate* option and it
  holds:

  - the disk size of the instance (units can be used)
  - the memory size of the instance (units can be used)
  - the vcpu count for the insance

  An example description would be *100G,4g,2* describing an instance
  specification of 100GB of disk space, 4GiB of memory and 2 VCPUs.

\--tiered-alloc *disk,ram,cpu*
  This option overrides the instance size for the *tiered* allocation
  mode. In this mode, the algorithm starts from the given specification
  and allocates until there is no more space; then it decreases the
  specification and tries the allocation again. The decrease is done on
  the metric that last failed during allocation. The argument should
  have the same format as for ``--standard-alloc``.

  Also note that the normal allocation and the tiered allocation are
  independent, and both start from the initial cluster state; as such,
  the instance count for these two modes are not related one to
  another.

\--machine-readable[=*choice*]
  By default, the output of the program is in "human-readable" format,
  i.e. text descriptions. By passing this flag you can either enable
  (``--machine-readable`` or ``--machine-readable=yes``) or explicitly
  disable (``--machine-readable=no``) the machine readable format
  described above.

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

UNITS
~~~~~

By default, all unit-accepting options use mebibytes. Using the
lower-case letters of *m*, *g* and *t* (or their longer equivalents of
*mib*, *gib*, *tib*, for which case doesn't matter) explicit binary
units can be selected. Units in the SI system can be selected using the
upper-case letters of *M*, *G* and *T* (or their longer equivalents of
*MB*, *GB*, *TB*, for which case doesn't matter).

More details about the difference between the SI and binary systems can
be read in the **units**\(7) man page.

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

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
