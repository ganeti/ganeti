HROLLER(1) Ganeti | Version @GANETI_VERSION@
============================================

NAME
----

hroller \- Cluster rolling maintenance scheduler for Ganeti

SYNOPSIS
--------

**hroller** {backend options...} [algorithm options...] [reporting options...]

**hroller** \--version


Backend options:

{ **-m** *cluster* | **-L[** *path* **]** | **-t** *data-file* |
**-I** *path* }

Algorithm options:

**[ -O *name...* ]**

Reporting options:

**[ -v... | -q ]**
**[ -S *file* ]**

DESCRIPTION
-----------

hroller is a cluster maintenance reboot scheduler. It can calculate
which set of nodes can be rebooted at the same time while avoiding
having both primary and secondary nodes being rebooted at the same time.

ALGORITHM FOR CALCULATING OFFLINE REBOOT GROUPS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

hroller will view the nodes as vertices of an undirected graph,
connecting by instances which have both a primary and a secondary node.
It will then color the graph using a few different heuristics, and
return the minimum-size color set found. Node with the same color don't
share an edge, and as such don't have an instance with both primary and
secondary node on them, so they are safe to be rebooted concurrently.

OPTIONS
-------

Currently only standard htools options are supported. For a description of them
check **htools**\(7) and **hbal**\(1).

BUGS
----

The master node should be always the last node of the last group, or anyway
somehow easily identifiable. Right now this is not done.

Offline nodes should be ignored.

Filtering by nodegroup should be allowed.

If instances are online the tool should refuse to do offline rolling
maintenances, unless explicitly requested.

End-to-end shelltests should be provided.

Online rolling maintenances (where instance need not be shut down, but
are migrated from node to node) are not supported yet. Hroller by design
should support them both with and without secondary node replacement.

EXAMPLE
-------

Note that these examples may not for the latest version.

Offline Rolling node reboot output
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the default options, the program shows one reboot group per line as
a comma-separated list.

    $ hroller
    'Node Reboot Groups'
    node1.example.com,node3.example.com,node5.example.com
    node8.example.com,node6.example.com,node2.example.com
    node7.example.com,node4.example.com

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
