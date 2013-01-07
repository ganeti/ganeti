HSCAN(1) Ganeti | Version @GANETI_VERSION@
==========================================

NAME
----

hscan - Scan clusters via RAPI and save node/instance data

SYNOPSIS
--------

**hscan** [-p] [\--no-headers] [-d *path* ] *cluster...*

**hscan** \--version

DESCRIPTION
-----------

hscan is a tool for scanning clusters via RAPI and saving their data
in the input format used by **hbal**\(1) and **hspace**\(1). It will
also show a one-line score for each cluster scanned or, if desired,
the cluster state as show by the **-p** option to the other tools.

For each cluster, one file named *cluster***.data** will be generated
holding the node and instance data. This file can then be used in
**hbal**\(1) or **hspace**\(1) via the *-t* option. In case the
cluster name contains slashes (as it can happen when the cluster is a
fully-specified URL), these will be replaced with underscores.

The one-line output for each cluster will show the following:

Name
  The name of the cluster (or the IP address that was given, etc.)

Nodes
  The number of nodes in the cluster

Inst
  The number of instances in the cluster

BNode
  The number of nodes failing N+1

BInst
  The number of instances living on N+1-failed nodes

t_mem
  Total memory in the cluster

f_mem
  Free memory in the cluster

t_disk
  Total disk in the cluster

f_disk
  Free disk space in the cluster

Score
  The score of the cluster, as would be reported by **hbal**\(1) if run
  on the generated data files.

In case of errors while collecting data, all fields after the name of
the cluster are replaced with the error display.

**Note:** this output format is not yet final so it should not be used
for scripting yet.

OPTIONS
-------

The options that can be passed to the program are as follows:

-p, \--print-nodes
  Prints the node status for each cluster after the cluster's one-line
  status display, in a format designed to allow the user to understand
  the node's most important parameters. For details, see the man page
  for **htools**\(1).

-d *path*
  Save the node and instance data for each cluster under *path*,
  instead of the current directory.

-V, \--version
  Just show the program version and exit.

EXIT STATUS
-----------

The exist status of the command will be zero, unless for some reason
loading the input data failed fatally (e.g. wrong node or instance
data).

BUGS
----

The program does not check its input data for consistency, and aborts
with cryptic errors messages in this case.

EXAMPLE
-------

::

    $ hscan cluster1
    Name     Nodes  Inst BNode BInst  t_mem  f_mem t_disk f_disk      Score
    cluster1     2     2     0     0   1008    652    255    253 0.24404762
    $ ls -l cluster1.data
    -rw-r--r-- 1 root root 364 2009-03-23 07:26 cluster1.data

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
