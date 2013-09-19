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

**[ --force ]**

Algorithm options:

**[ -G *name* ]**
**[ -O *name...* ]**
**[ --node-tags** *tag,..* **]**
**[ --skip-non-redundant ]**

**[ --offline-maintenance ]**
**[ --ignore-non-redundant ]**

Reporting options:

**[ -v... | -q ]**
**[ -S *file* ]**
**[ --one-step-only ]**
**[ --print-moves ]**

DESCRIPTION
-----------

hroller is a cluster maintenance reboot scheduler. It can calculate
which set of nodes can be rebooted at the same time while avoiding
having both primary and secondary nodes being rebooted at the same time.

For backends that support identifying the master node (currently
RAPI and LUXI), the master node is scheduled as the last node
in the last reboot group. Apart from this restriction, larger reboot
groups are put first.

ALGORITHM FOR CALCULATING OFFLINE REBOOT GROUPS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

hroller will view the nodes as vertices of an undirected graph,
with two kind of edges. Firstly, there are edges from the primary
to the secondary node of every instance. Secondly, two nodes are connected
by an edge if they are the primary nodes of two instances that have the
same secondary node. It will then color the graph using a few different
heuristics, and return the minimum-size color set found. Node with the same
color can then simultaneously migrate all instance off to their respective
secondary nodes, and it is safe to reboot them simultaneously.

OPTIONS
-------

For a description of the standard options check **htools**\(1) and
**hbal**\(1).

\--force
  Do not fail, even if the master node cannot be determined.

\--node-tags *tag,...*
  Restrict to nodes having at least one of the given tags.

\--full-evacuation
  Also plan moving secondaries out of the nodes to be rebooted. For
  each instance the move is at most a migrate (if it was primary
  on that node) followed by a replace secondary.

\--skip-non-redundant
  Restrict to nodes not hosting any non-redundant instance.

\--offline-maintenance
  Pretend that all instances are shutdown before the reboots are carried
  out. I.e., only edges from the primary to the secondary node of an instance
  are considered.

\--ignore-non-redundnant
  Pretend that the non-redundant instances do not exist, and only take
  instances with primary and secondary node into account.

\--one-step-only
  Restrict to the first reboot group. Output the group one node per line.

\--print-moves
  After each group list for each affected instance a node
  where it can be evacuated to. The moves are computed under the assumption
  that after each reboot group, all instances are moved back to their
  initial position.

BUGS
----

If instances are online the tool should refuse to do offline rolling
maintenances, unless explicitly requested.

End-to-end shelltests should be provided.

EXAMPLES
--------

Online Rolling reboots, using tags
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Selecting by tags and getting output for one step only can be used for
planing the next maintenance step.
::

   $ hroller --node-tags needsreboot --one-step-only -L
   'First Reboot Group'
    node1.example.com
    node3.example.com

Typically these nodes would be drained and migrated.
::

   $ GROUP=`hroller --node-tags needsreboot --one-step-only --no-headers -L`
   $ for node in $GROUP; do gnt-node modify -D yes $node; done
   $ for node in $GROUP; do gnt-node migrate -f --submit $node; done

After maintenance, the tags would be removed and the nodes undrained.


Offline Rolling node reboot output
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If all instances are shut down, usually larger node groups can be found.
::

    $ hroller --offline-maintainance -L
    'Node Reboot Groups'
    node1.example.com,node3.example.com,node5.example.com
    node8.example.com,node6.example.com,node2.example.com
    node7.example.com,node4.example.com

Rolling reboots with non-redundant instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, hroller plans capacity to move the non-redundant instances
out of the nodes to be rebooted. If requested, apropriate locations for
the non-redundant instances can be shown. The assumption is that instances
are moved back to their original node after each reboot; these back moves
are not part of the output.
::

    $ hroller --print-moves -L
    'Node Reboot Groups'
    node-01-002,node-01-003
      inst-20 node-01-001
      inst-21 node-01-000
      inst-30 node-01-005
      inst-31 node-01-004
    node-01-004,node-01-005
      inst-40 node-01-001
      inst-41 node-01-000
      inst-50 node-01-003
      inst-51 node-01-002
    node-01-001,node-01-000
      inst-00 node-01-002
      inst-01 node-01-003
      inst-10 node-01-005
      inst-11 node-01-004



.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
