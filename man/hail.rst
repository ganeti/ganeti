HAIL(1) Ganeti | Version @GANETI_VERSION@
=========================================

NAME
----

hail - Ganeti IAllocator plugin

SYNOPSIS
--------

**hail** [ **-t** *file* | **\--simulate** *spec* ] [options...] *input-file*

**hail** \--version

DESCRIPTION
-----------

hail is a Ganeti IAllocator plugin that implements the instance
placement and movement using the same algorithm as **hbal**\(1).

The program takes input via a JSON-file containing current cluster
state and the request details, and output (on stdout) a JSON-formatted
response. In case of critical failures, the error message is printed
on stderr and the exit code is changed to show failure.

If the input file name is ``-`` (a single minus sign), then the request
data will be read from *stdin*.

Apart from input data, hail collects data over the network from all
MonDs with the --mond option. Currently it uses only data produced by
the CPUload collector.

ALGORITHM
~~~~~~~~~

On regular node groups, the program uses a simplified version of
the hbal algorithm; for allocation on node groups with exclusive
storage see below.

For single-node allocations (non-mirrored instances), again we
select the node which, when chosen as the primary node, gives the best
score.

For dual-node allocations (mirrored instances), we chose the best
pair; this is the only choice where the algorithm is non-trivial
with regard to cluster size.

For relocations, we try to change the secondary node of the instance to
all the valid other nodes; the node which results in the best cluster
score is chosen.

For node changes (*change-node* mode), we currently support DRBD
instances only, and all three modes (primary changes, secondary changes
and all node changes).

For group moves (*change-group* mode), again only DRBD is supported, and
we compute the correct sequence that will result in a group change; job
failure mid-way will result in a split instance. The choice of node(s)
on the target group is based on the group score, and the choice of group
is based on the same algorithm as allocations (group with lowest score
after placement).

The deprecated *multi-evacuate* modes is no longer supported.

In all cases, the cluster (or group) scoring is identical to the hbal
algorithm.

For allocation on node groups with exclusive storage, the lost-allocations
metrics is used instead to determine which node to allocate an instance
on. For a node the allocation vector is the vector of, for each instance
policy interval in decreasing order, the number of instances minimally
compliant with that interval that still can be placed on that node. The
lost-allocations vector for an instance on a node is the difference of
the allocation vectors for that node before and after placing the
instance on that node. The lost-allocations metrics is the lost allocation
vector followed by the remaining disk space on the chosen node, all
compared lexicographically.

OPTIONS
-------

The options that can be passed to the program are as follows:

-p, \--print-nodes
  Prints the before and after node status, in a format designed to allow
  the user to understand the node's most important parameters. See the
  man page **htools**\(1) for more details about this option.

-t *datafile*, \--text-data=*datafile*
  The name of the file holding cluster information, to override the data
  in the JSON request itself. This is mostly used for debugging. The
  format of the file is described in the man page **htools**\(1).

\--mond=*yes|no*
  If given the program will query all MonDs to fetch data from the
  supported data collectors over the network.

\--mond-data *datafile*
  The name of the file holding the data provided by MonD, to override
  quering MonDs over the network. This is mostly used for debugging. The
  file must be in JSON format and present an array of JSON objects ,
  one for every node, with two members. The first member named ``node``
  is the name of the node and the second member named ``reports`` is an
  array of report objects. The report objects must be in the same format
  as produced by the monitoring agent.

\--ignore-dynu
  If given, all dynamic utilisation information will be ignored by
  assuming it to be 0. This option will take precedence over any data
  passed by the MonDs with the ``--mond`` and the ``--mond-data``
  option.

\--ignore-soft-errors
  If given, all checks for soft errors will be ommitted when searching
  for possible allocations. In this way a useful decission can be made
  even in overloaded clusters.

\--no-capacity-checks
  Normally, hail will only consider those allocations where all instances
  of a node can immediately restarted should that node fail. With this
  option given, hail will check only N+1 redundancy for DRBD instances.

\--restrict-allocation-to
  Only consider alloctions on the specified nodes. This overrides any
  restrictions given in the allocation request.

\--simulate *description*
  Backend specification: similar to the **-t** option, this allows
  overriding the cluster data with a simulated cluster. For details
  about the description, see the man page **htools**\(1).

-S *filename*, \--save-cluster=*filename*
  If given, the state of the cluster before and the iallocator run is
  saved to a file named *filename.pre-ialloc*, respectively
  *filename.post-ialloc*. This allows re-feeding the cluster state to
  any of the htools utilities via the ``-t`` option.

-v
  This option increases verbosity and can be used for debugging in order
  to understand how the IAllocator request is parsed; it can be passed
  multiple times for successively more information.


CONFIGURATION
-------------

For the tag-exclusion configuration (see the manpage of hbal for more
details), the list of which instance tags to consider as exclusion
tags will be read from the cluster tags, configured as follows:

- get all cluster tags starting with **htools:iextags:**
- use their suffix as the prefix for exclusion tags

For example, given a cluster tag like **htools:iextags:service**,
all instance tags of the form **service:X** will be considered as
exclusion tags, meaning that (e.g.) two instances which both have a
tag **service:foo** will not be placed on the same primary node.

OPTIONS
-------

The options that can be passed to the program are as follows:

EXIT STATUS
-----------

The exist status of the command will be zero, unless for some reason
the algorithm fatally failed (e.g. wrong node or instance data).

BUGS
----

Networks (as configured by **gnt-network**\(8)) are not taken into
account in Ganeti 2.7. The only way to guarantee that they work
correctly is having your networks connected to all nodegroups. This will
be fixed in a future version.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
