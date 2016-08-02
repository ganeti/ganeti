==================================
Migration speed accounting in Hbal
==================================

.. contents:: :depth: 2

Hbal usually performs complex sequence of moves during cluster balancing in
order to achieve local optimal cluster state. Unfortunately, each move may take
significant amount of time. Thus, during the sequence of moves the situation on
cluster may change (e.g., because of adding new instance or because of instance
or node parameters change) and desired moves can become unprofitable.

Usually disk moves become a bottleneck and require sufficient amount of time.
:ref:`Instance move improvements <move-performance>` considers
disk moves speed in more details. Currently, ``hbal`` has a ``--no-disk-moves``
option preventing disk moves during cluster balancing in order to perform fast
(but of course non optimal) balancing. It may be useful, but ideally we need to
find a balance between optimal configuration and time to reach this
configuration.

Avoiding insignificant disk moves
=================================

Allowing only profitable enough disk moves may become a first step to reach
a compromise between moves speed and optimal scoring. This can be implemented
by introducing ``--avoid-disk-moves *FACTOR*`` option which will admit disk
moves only if the gain in the cluster metrics is *FACTOR* times
higher than the gain achievable by non disk moves.

Avoiding insignificant long-time solutions
==========================================

The next step is to estimate an amount of time required to perform a balancing
step and to introduce a new term: ``long-time`` solution.

``--long-solution-threshold`` option will specify a duration in seconds.
A solution exceeding the duration is a ``long-time`` solution by definition.

With time estimations we will be able to filter Hbal's sequences and
eliminating long-time solutions which don't lead to a sufficient cluster metric
improvement. This can be done by the ``--avoid-long-solutions *FACTOR*`` option
which will allow only long solutions, whose K/N metrics are more than *FACTOR*,
where K is the number of times cluster metric has increased and N is an
estimated time to perform this solution divided by the threshold.

The default values for the new options are:

``--long-solution-threshold`` = 1000 seconds
(all adequate solutions are not ``long-time``)

``--avoid-long-solutions`` = 0.0
(no filtering by time estimations, feature disabled)

Network bandwidth cluster tags
==============================

The bandwidth between nodes, node groups and within whole cluster could be
specified "by hand" with the cluster tags.

Every node contains its own set of bandwidth tags. Tags from higher level are
inherited by lower levels: nodegroups inherit cluster tags and nodes inherit
nodegroups tags. Tags from lower level (if exist) override higher level tags
with the same bandwidth prefixes: node tags override nodegroup tags as well as
nodegroup tags override cluster tags.

Below are some examples of using bandwidth tags:
(The examples are provided using in the Htools Text backend format)

1) single nodegroup with 5 nodes, all bandwidths symmetric.

group-01|...|nic:100MBit|

*no* node-level bandwidth tags (they are inherited by group tags)

htools:bandwidth:nic
htools:bandwidth:nic:100MBit::nic:100MBit::100


2) 3 nodegroups, within each nodegroup symmetric bandwidths,
between nodegroups different bandwidths.

group-01|...|nic:1000MBit (overrides cluster tags)|
group-02|...|nic:100MBit (overrides cluster tags)|
group-03|...|inherited by cluster tags (nic:10MBit)|

*no* node-level bandwidth tags (they are inherited by group tags)

htools:bandwidth:nic
nic:10MBit
htools:bandwidth:nic:10MBit::nic:10MBit::10
htools:bandwidth:nic:100MBit::nic:100MBit::100
htools:bandwidth:nic:1000MBit::nic:1000MBit::1000
htools:bandwidth:nic:10MBit::nic:100MBit::10
htools:bandwidth:nic:10MBit::nic:1000MBit::10
htools:bandwidth:nic:100MBit::nic:1000MBit::100


Network bandwidth estimation
============================

Balancing time can be estimated by dividing the amount of data to be moved by
the current network bandwidth between the affected nodes.

We propose to add a new data collector, that will gather information about
network speed by sending a test file between between nodes. Accounting the
time, we can estimate average network speed between nodegroups in a cluster.

DataCollector implementation details
====================================

The new bandwidth data collector introduces an ability to collect actual
information about network speed between nodegroups in a cluster. We assume,
that the network bandwidth between any nodes within one nodegroup is almost the
same unlike the network speed between different nodegroups. So the proposed
data collector will provide the most necessary data for time estimations.

For sending packets *scp* utility will be used. The default size of file
to send is 5Mbyte in order to obtain adequate values of the network speed.

During *dcUpdate* every data collector sends a file with known size to a node
from another nodegroup (chosen randomly) and measures time to perform it. MonD
receives the response of *dcReport* from collectors, it fills nodegroup
bandwidth map in nodes. The information collected will be used to estimate the
time of balancing steps. In the case of existing network speed information for
some node from bandwidth tags as well as from bandwidth data collector the last
one will be chosen.
