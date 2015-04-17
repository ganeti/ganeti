HCHECK(1) Ganeti | Version @GANETI_VERSION@
===========================================

NAME
----

hcheck \- Cluster checker

SYNOPSIS
--------

**hcheck** {backend options...} [algorithm options...] [reporting options...]

**hcheck** \--version


Backend options:

{ **-m** *cluster* | **-L[** *path* **] | **-t** *data-file* |
**-I** *path* }

Algorithm options:

**[ \--no-simulation ]**
**[ \--max-cpu *cpu-ratio* ]**
**[ \--min-disk *disk-ratio* ]**
**[ -l *limit* ]**
**[ -e *score* ]**
**[ -g *delta* ]** **[ \--min-gain-limit *threshold* ]**
**[ -O *name...* ]**
**[ \--no-disk-moves ]**
**[ \--no-instance-moves ]**
**[ -U *util-file* ]**
**[ \--ignore-dynu ]**
**[ \--ignore-soft-errors ]**
**[ \--evac-mode ]**
**[ \--select-instances *inst...* ]**
**[ \--exclude-instances *inst...* ]**
**[ \--no-capacity-checks ]**

Reporting options:

**[\--machine-readable**[=*CHOICE*] **]**
**[ -p[ *fields* ] ]**
**[ \--print-instances ]**
**[ -v... | -q ]**


DESCRIPTION
-----------

hcheck is the cluster checker. It prints information about cluster's
health and checks whether a rebalance done using **hbal** would help.

This information can be presented in both human-readable and
machine-readable way.

Note that it does not take any action, only performs a rebalance
simulation if necessary.

For more information about the algorithm details check **hbal**\(1).

Additionally, hcheck also checks if the cluster is globally N+1 redundant.
That is, it checks for every node, if after failing over the DRBD instances
all instances on that node that with disks externally stored can be restarted
on some other node.

OPTIONS
-------

\--no-simulation
  Only perform checks based on current cluster state, without trying
  to simulate rebalancing.

\--no-capacity-checks
  Do not check for global N+1 redundancy, i.e., do not warn if the
  shared-storage instances of one node cannot be moved to the others
  should that node fail.

For a detailed description about the options listed above have a look at
**htools**\(1), **hspace**\(1) and **hbal**\(1).

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
