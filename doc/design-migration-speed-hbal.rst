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
