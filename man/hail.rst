HAIL(1) Ganeti | Version @GANETI_VERSION@
=========================================

NAME
----

hail - Ganeti IAllocator plugin

SYNOPSIS
--------

**hail** [ **-t** *datafile* | **--simulate** *spec* ] *input-file*

**hail** --version

DESCRIPTION
-----------

hail is a Ganeti IAllocator plugin that allows automatic instance
placement and automatic instance secondary node replacement using the
same algorithm as **hbal**(1).

The program takes input via a JSON-file containing current cluster
state and the request details, and output (on stdout) a JSON-formatted
response. In case of critical failures, the error message is printed
on stderr and the exit code is changed to show failure.

ALGORITHM
~~~~~~~~~

The program uses a simplified version of the hbal algorithm.

For relocations, we try to change the secondary node of the instance
to all the valid other nodes; the node which results in the best
cluster score is chosen.

For single-node allocations (non-mirrored instances), again we
select the node which, when chosen as the primary node, gives the best
score.

For dual-node allocations (mirrored instances), we chose the best
pair; this is the only choice where the algorithm is non-trivial
with regard to cluster size.

For node evacuations (*multi-evacuate* mode), we iterate over all
instances which live as secondaries on those nodes and try to relocate
them using the single-instance relocation algorithm.

In all cases, the cluster scoring is identical to the hbal algorithm.

OPTIONS
-------

The options that can be passed to the program are as follows:

-p, --print-nodes
  Prints the before and after node status, in a format designed to
  allow the user to understand the node's most important
  parameters. See the man page **hbal**(1) for more details about this
  field.

-t *datafile*, --text-data=*datafile*
  The name of the file holding cluster information, to override the
  data in the JSON request itself. This is mostly used for debugging.

--simulate *description*
  Similar to the **-t** option, this allows overriding the cluster
  data with a simulated cluster. For details about the description,
  see the man page **hspace**(1).

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

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
