ganeti-watcher(8) Ganeti | Version @GANETI_VERSION@
===================================================

Name
----

ganeti-watcher - Ganeti cluster watcher

Synopsis
--------

**ganeti-watcher** [\--debug] [\--job-age=*age* ] [\--ignore-pause]
[\--rapi-ip=*IP*] [\--no-verify-disks]

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

The ``--rapi-ip`` option needs to be set if the RAPI daemon was
started with a particular IP (using the ``-b`` option). The two
options need to be exactly the same to ensure that the watcher
can reach the RAPI interface.

Master operations
~~~~~~~~~~~~~~~~~

Its primary function is to try to keep running all instances which
are marked as *up* in the configuration file, by trying to start
them a limited number of times.

Another function is to "repair" DRBD links by reactivating the
block devices of instances which have secondaries on nodes that
have been rebooted.

Additionally, it will verify and repair degraded DRBD disks; this
will not happen, if the ``--no-verify-disks`` option is given.

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

The command has a set of state files (one per group) located at
``@LOCALSTATEDIR@/lib/ganeti/watcher.GROUP-UUID.data`` (only used on the
master) and a log file at
``@LOCALSTATEDIR@/log/ganeti/watcher.log``. Removal of either file(s)
will not affect correct operation; the removal of the state file will
just cause the restart counters for the instances to reset to zero, and
mark nodes as freshly rebooted (so for example DRBD minors will be
re-activated).

In some cases, it's even desirable to reset the watcher state, for
example after maintenance actions, or when you want to simulate the
reboot of all nodes, so in this case, you can remove all state files:

.. code-block:: bash

    rm -f @LOCALSTATEDIR@/lib/ganeti/watcher.*.data
    rm -f @LOCALSTATEDIR@/lib/ganeti/watcher.*.instance-status
    rm -f @LOCALSTATEDIR@/lib/ganeti/instance-status

And then re-run the watcher.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
