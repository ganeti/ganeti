ganeti-masterd(8) Ganeti | Version @GANETI_VERSION@
===================================================

Name
----

ganeti-masterd - Ganeti master daemon

Synopsis
--------

**ganeti-masterd** [-f] [-d] [--no-voting]

DESCRIPTION
-----------

The **ganeti-masterd** is the daemon which is responsible for the
overall cluster coordination. Without it, no change can be
performed on the cluster.

For testing purposes, you can give the ``-f`` option and the
program won't detach from the running terminal.

Debug-level message can be activated by giving the ``-d`` option.

ROLE
~~~~

The role of the master daemon is to coordinate all the actions that
change the state of the cluster. Things like accepting new jobs,
coordinating the changes on nodes (via RPC calls to the respective
node daemons), maintaining the configuration and so on are done via
this daemon.

The only action that can be done without the master daemon is the
failover of the master role to another node in the cluster, via the
**gnt-cluster master-failover** command.

If the master daemon is stopped, the instances are not affected,
but they won't be restarted automatically in case of failure.

STARTUP
~~~~~~~

At startup, the master daemon will confirm with the node daemons
that the node it is running is indeed the master node of the
cluster. It will abort if it doesn't get half plus one positive
answers (offline nodes are queried too, just in case our
configuration is stale).

For small clusters with a number of nodes down, and especially for
two-node clusters where the other has gone done, this creates a
problem. In this case the ``--no-voting`` option can be used to
skip this process. The option requires interactive confirmation, as
having two masters on the same cluster is a very dangerous
situation and will most likely lead to data loss.

JOB QUEUE
~~~~~~~~~

The master daemon maintains a job queue (located under the directory
``@LOCALSTATEDIR@/lib/ganeti/queue``) in which all current jobs are
stored, one job per file serialized in JSON format; in this directory
a subdirectory called ``archive`` holds archived job files.

The moving of jobs from the current to the queue directory is done
via a request to the master; this can be accomplished from the
command line with the **gnt-job archive** or
**gnt-job autoarchive** commands. In case of problems with the
master, a job file can simply be moved away or deleted (but this
might leave the cluster inconsistent).

COMMUNICATION PROTOCOL
~~~~~~~~~~~~~~~~~~~~~~

The master accepts commands over a Unix socket, using JSON
serialized messages separated by a specific byte sequence. For more
details, see the design documentation supplied with Ganeti.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
