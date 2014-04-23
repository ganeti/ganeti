======================================
Taking relative CPU speed into account
======================================

.. contents:: :depth: 4

This document describes the suggested addition of a new
node-parameter, describing the CPU speed of a node,
relative to that of a normal node in the node group.


Current state and shortcomings
==============================

Currently, for balancing a cluster, for most resources (disk, memory),
the ratio between the amount used and the amount available is taken as
a measure of load for that resources. As ``hbal`` tries to even out the
load in terms of these measures, larger nodes get a larger share of the
instances, even for a cluster not running at full capacity.

For for one resources, however, hardware differences are not taken into
account: CPU speed. For CPU, the load is measured by the ratio of used virtual
to physical CPUs on the node. Balancing this measure implictly assumes
equal speed of all CPUs.


Proposed changes
================

It is proposed to add a new node parameter, ``cpu_speed``, that is a
floating-point number, with default value ``1.0``. It can be modified in the
same ways, as all other node parameters.

The cluster metric used by ``htools`` will be changed to use the ratio
of virtual to physical cpus weighted by speed, rather than the plain
virtual-to-physical ratio. So, when balancing, nodes will be
considered as if they had physical cpus equal to ``cpu_speed`` times
the actual number.

Finally, it should be noted that for IO load, in non-dedicated Ganeti, the
``spindle_count`` already serves the same purpose as the newly proposed
``cpu_speed``. It is a parameter to measure the amount of IO a node can handle
in arbitrary units.
