ganeti-watcher(8) Ganeti | Version @GANETI_VERSION@
===================================================

Name
----

ganeti-watcher - Ganeti cluster watcher

Synopsis
--------

**ganeti-watcher** [``--debug``]
[``--job-age=``*age*]
[``--ignore-pause``]

DESCRIPTION
-----------

The **ganeti-watcher** is a periodically run script which is
responsible for keeping the instances in the correct status. It has
two separate functions, one for the master node and another one
that runs on every node.

If the watcher is disabled at cluster level (via the
**gnt-cluster watcher pause** command), it will exit without doing
anything. The cluster-level pause can be overridden via the
``--ignore-pause`` option, for example if during a maintenance the
watcher needs to be disabled in general, but the administrator
wants to run it just once.

The ``--debug`` option will increase the verbosity of the watcher
and also activate logging to the standard error.

Master operations
~~~~~~~~~~~~~~~~~

Its primary function is to try to keep running all instances which
are marked as *up* in the configuration file, by trying to start
them a limited number of times.

Another function is to "repair" DRBD links by reactivating the
block devices of instances which have secondaries on nodes that
have been rebooted.

The watcher will also archive old jobs (older than the age given
via the ``--job-age`` option, which defaults to 6 hours), in order
to keep the job queue manageable.

Node operations
~~~~~~~~~~~~~~~

The watcher will restart any down daemons that are appropriate for
the current node.

In addition, it will execute any scripts which exist under the
"watcher" directory in the Ganeti hooks directory
(``@SYSCONFDIR@/ganeti/hooks``). This should be used for lightweight
actions, like starting any extra daemons.

If the cluster parameter ``maintain_node_health`` is enabled, then the
watcher will also shutdown instances and DRBD devices if the node is
declared as offline by known master candidates.

The watcher does synchronous queries but will submit jobs for
executing the changes. Due to locking, it could be that the jobs
execute much later than the watcher submits them.

FILES
-----

The command has a state file located at
``@LOCALSTATEDIR@/lib/ganeti/watcher.data`` (only used on the master)
and a log file at ``@LOCALSTATEDIR@/log/ganeti/watcher.log``. Removal
of either file will not affect correct operation; the removal of the
state file will just cause the restart counters for the instances to
reset to zero.
