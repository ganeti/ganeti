================
Merging clusters
================

With ``cluster-merge`` from the ``tools`` directory it is possible to
merge two or more clusters into one single cluster.

If anything goes wrong at any point the script suggests you rollback
steps you've to perform *manually* if there are any. The point of no
return is when the master daemon is started the first time after merging
the configuration files. A rollback at this point would involve a lot of
manual work.

For the internal design of this tool have a look at the `Automated
Ganeti Cluster Merger <design-2.1.rst>` document.


Merge Clusters
==============

The tool has to be invoked on the cluster you like to merge the other
clusters into.

The usage of ``cluster-merge`` is as follows::

  cluster-merge [--debug|--verbose] [--watcher-pause-period SECONDS] <cluster> \
  <cluster...>

You can provide multiple clusters. The tool will then go over every
cluster in serial and perform the steps to merge it into the invoking
cluster.

These options can be used to control the behaviour of the tool:

``--debug``/``--verbose``
  These options are mutually exclusive and increase the level of output
  to either debug output or just more verbose output like action
  performed right now.
``--watcher-pause-period``
  Define the period of time in seconds the watcher shall be disabled,
  default is 1800 seconds (30 minutes).


Rollback
========

If for any reason something in the merge doesn't work the way it should
``cluster-merge`` will abort, provide an error message and optionally
rollback steps. Please be aware that after a certain point there's no
easy way to rollback the cluster to its previous state. If you've
reached that point the tool will not provide any rollback steps.

If you end up with rollback steps, please perform them before invoking
the tool again. It doesn't keep state over invokations.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
