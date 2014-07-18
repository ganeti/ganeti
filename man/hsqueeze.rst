HSQUEEZE(1) Ganeti | Version @GANETI_VERSION@
=============================================

NAME
----

hsqueeze \- Dynamic power management

SYNOPSIS
--------

**hsqueeze** {backend options...} [algorithm options...] [reporting options...]

**hsqueeze** \--version

Backend options:

{ **-L[** *path* **]** [-X]** | **-t** *data-file* }

Algorithm options:

**[ \--minimal-resources=*factor* ]**
**[ \--target-resources=*factor* ]**

Reporting options:

**[ -S *file* ]**
**[ -C[*file*] ]**


DESCRIPTION
-----------

hsqueeze does dynamic power management, by powering up or shutting down nodes,
depending on the current load of the cluster. Currently, only suggesting nodes
is implemented.

ALGORITHM
~~~~~~~~~

hsqueeze considers all online non-master nodes with only externally mirrored
instances as candidates for being taken offline. These nodes are iteratively,
starting from the node with the least number of instances, added to the set
of nodes to be put offline, if possible. A set of nodes is considered as suitable
for being taken offline, if, after marking these nodes as offline, balancing the
cluster by the algorithm used by **hbal**\(1) yields a situation where all instances
are located on online nodes, and each node has at least the target resources free
for new instances.

All offline nodes with a tag starting with ``htools:standby`` are
considered candidates for being taken online. Those nodes are taken online
till balancing the cluster by the algorithm used by **hbal**\(1) yields a
situation where each node has at least the minimal resources free for new
instances.

OPTIONS
-------

-L [*path*]
  Backend specification: collect data directly from the master daemon,
  which is to be contacted via LUXI (an internal Ganeti protocol). The
  option is described in the man page **htools**\(1).

-X
  When using the Luxi backend, hsqueeze can also execute the given
  commands.

  The execution of the job series can be interrupted, see below for
  signal handling.

-S *filename*, \--save-cluster=*filename*
  If given, the state of the cluster before the squeezing is saved to
  the given file plus the extension "original"
  (i.e. *filename*.original), and the state at the end of the
  squeezing operation is saved to the given file plus the extension "squeezed"
  (i.e. *filename*.squeezed).

-C[*filename*], \--print-commands[=*filename*]
  If given, a shell script containing the commands to squeeze or unsqueeze
  the cluster are saved in a file with the given name; if no name is provided,
  they are printed to stdout.

-t *datafile*, \--text-data=*datafile*
  Backend specification: the name of the file holding node and instance
  information (if not collecting LUXI). This or one of the
  other backends must be selected. The option is described in the man
  page **htools**\(1).

\--minimal-resources=*factor*
  Specify the amount of resources to be free on each node for hsqueeze not to
  consider onlining additional nodes. The value is reported a multiple of the
  standard instance specification, as taken from the instance policy.

\--target-resources=*factor*
  Specify the amount of resources to remain free on any node after squeezing.
  The value is reported a multiple of the standard instance specification, as
  taken from the instance policy.
