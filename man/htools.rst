HTOOLS(1) Ganeti | Version @GANETI_VERSION@
===========================================

NAME
----

htools - Cluster allocation and placement tools for Ganeti

SYNOPSIS
--------

**hbal**
  cluster balancer

**hcheck**
  cluster checker

**hspace**
  cluster capacity computation

**hail**
  IAllocator plugin

**hscan**
  saves cluster state for later reuse

**hinfo**
  cluster information printer

**hroller**
  cluster rolling maintenance scheduler

DESCRIPTION
-----------

``htools`` is a suite of tools designed to help with allocation/movement
of instances and balancing of Ganeti clusters. ``htools`` is also the
generic binary that must be symlinked or hardlinked under each tool's
name in order to perform the different functions. Alternatively, the
environment variable HTOOLS can be used to set the desired role.

Installed as ``hbal``, it computes and optionally executes a suite of
instance moves in order to balance the cluster.

Installed as ``hcheck``, it preforms cluster checks and optionally
simulates rebalancing with all the ``hbal`` options available.

Installed as ``hspace``, it computes how many additional instances can
be fit on a cluster, while maintaining N+1 status. It can run on models
of existing clusters or of simulated clusters.

Installed as ``hail``, it acts as an IAllocator plugin, i.e. it is used
by Ganeti to compute new instance allocations and instance moves.

Installed as ``hscan``, it scans the local or remote cluster state and
saves it to files which can later be reused by the other roles.

Installed as ``hinfo``, it prints information about the current cluster
state.

Installed as ``hroller``, it helps scheduling maintenances that require
node reboots on a cluster.

COMMON OPTIONS
--------------

Options behave the same in all program modes, but not all program modes
support all options. Some common options are:

-p, \--print-nodes
  Prints the node status, in a format designed to allow the user to
  understand the node's most important parameters. If the command in
  question makes a cluster transition (e.g. balancing or allocation),
  then usually both the initial and final node status is printed.

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

-t *datafile*, \--text-data=*datafile*
  Backend specification: the name of the file holding node and instance
  information (if not collecting via RAPI or LUXI). This or one of the
  other backends must be selected. The option is described in the man
  page **htools**\(1).

  The file should contain text data, line-based, with two empty lines
  separating sections. The lines themselves are column-based, with the
  pipe symbol (``|``) acting as separator.

  The first section contains group data, with two columns:

  - group name
  - group uuid

  The second sections contains node data, with the following columns:

  - node name
  - node total memory
  - node free memory
  - node total disk
  - node free disk
  - node physical cores
  - offline field (as ``Y`` or ``N``)
  - group UUID
  - node spindle count

  The third section contains instance data, with the fields:

  - instance name
  - instance memory
  - instance disk size
  - instance vcpus
  - instance status (in Ganeti's format, e.g. ``running`` or ``ERROR_down``)
  - instance ``auto_balance`` flag (see man page **gnt-instance** (7))
  - instance primary node
  - instance secondary node(s), if any
  - instance disk type (e.g. ``plain`` or ``drbd``)
  - instance tags

  The fourth section contains the cluster tags, with one tag per line
  (no columns/no column processing).

  The fifth section contains the ipolicies of the cluster and the node
  groups, in the following format (separated by ``|``):

  - owner (empty if cluster, group name otherwise)
  - standard, min, max instance specs, containing the following values
    separated by commas:
    - memory size
    - cpu count
    - disk size
    - disk count
    - nic count
  - disk templates
  - vcpu ratio
  - spindle ratio

-m *cluster*
  Backend specification: collect data directly from the *cluster* given
  as an argument via RAPI. If the argument doesn't contain a colon (:),
  then it is converted into a fully-built URL via prepending
  ``https://`` and appending the default RAPI port, otherwise it is
  considered a fully-specified URL and used as-is.

-L [*path*]
  Backend specification: collect data directly from the master daemon,
  which is to be contacted via LUXI (an internal Ganeti protocol). An
  optional *path* argument is interpreted as the path to the unix socket
  on which the master daemon listens; otherwise, the default path used
  by Ganeti (configured at build time) is used.

-I|\--ialloc-src *path*
  Backend specification: load data directly from an iallocator request
  (as produced by Ganeti when doing an iallocator call).  The iallocator
  request is read from specified path.

\--simulate *description*
  Backend specification: instead of using actual data, build an empty
  cluster given a node description. The *description* parameter must be
  a comma-separated list of five elements, describing in order:

  - the allocation policy for this node group (*preferred*, *allocable*
    or *unallocable*, or alternatively the short forms *p*, *a* or *u*)
  - the number of nodes in the cluster
  - the disk size of the nodes (default in mebibytes, units can be used)
  - the memory size of the nodes (default in mebibytes, units can be used)
  - the cpu core count for the nodes
  - the spindle count for the nodes

  An example description would be **preferred,20,100G,16g,4,2**
  describing a 20-node cluster where each node has 100GB of disk space,
  16GiB of memory, 4 CPU cores and 2 disk spindles. Note that all nodes
  must have the same specs currently.

  This option can be given multiple times, and each new use defines a
  new node group. Hence different node groups can have different
  allocation policies and node count/specifications.

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

Some options accept not simply numerical values, but numerical values
together with a unit. By default, such unit-accepting options use
mebibytes. Using the lower-case letters of *m*, *g* and *t* (or their
longer equivalents of *mib*, *gib*, *tib*, for which case doesn't
matter) explicit binary units can be selected. Units in the SI system
can be selected using the upper-case letters of *M*, *G* and *T* (or
their longer equivalents of *MB*, *GB*, *TB*, for which case doesn't
matter).

More details about the difference between the SI and binary systems can
be read in the **units**\(7) man page.

ENVIRONMENT
-----------

The environment variable ``HTOOLS`` can be used instead of
renaming/symlinking the programs; simply set it to the desired role and
then the name of the program is no longer used.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
