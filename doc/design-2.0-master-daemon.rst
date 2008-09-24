Ganeti 2.0 Master daemon
========================

Objective
---------

Many of the important features of Ganeti 2.0 — job queue, granular
locking, external API, etc. — will be integrated via a master
daemon. While not absolutely necessary, it is the best way to
integrate all these components.

Background
----------

Currently there is no "master" daemon in Ganeti (1.2). Each command
tries to acquire the so called *cmd* lock and when it succeeds, it
takes complete ownership of the cluster configuration and state. The
scheduled improvements to Ganeti require or can use a daemon that
coordinates the activities/jobs scheduled/etc.

Overview
--------

The master daemon will be the central point of the cluster; command
line tools and the external API will interact with the cluster via
this daemon; it will be one coordinating the node daemons.

This design doc is best read in the context of the accompanying design
docs for Ganeti 2.0: Granular locking design and Job queue design.


Detailed Design
---------------

In Ganeti 2.0, we will have the following *entities*:

- the master daemon (on master node)
- the node daemon (all nodes)
- the command line tools (master node)
- the RAPI daemon (master node)

Interaction paths are between:

- (CLI tools/RAPI daemon) and the master daemon, via the so called *luxi* API
- the master daemon and the node daemons, via the node RPC

The protocol between the master daemon and the node daemons will be
changed to HTTP(S), using a simple PUT/GET of JSON-encoded
messages. This is done due to difficulties in working with the twisted
protocols in a multithreaded environment, which we can overcome by
using a simpler stack (see the caveats section). The protocol between
the CLI/RAPI and the master daemon will be a custom one: on a UNIX
socket on the master node, with rights restricted by filesystem
permissions, the CLI/API will speak HTTP to the master daemon.

The operations supported over this internal protocol will be encoded
via a python library that will expose a simple API for its
users. Internally, the protocol will simply encode all objects in JSON
format and decode them on the receiver side.

The LUXI protocol
~~~~~~~~~~~~~~~~~

We will have two main classes of operations over the master daemon API:

- cluster query functions
- job related functions

The cluster query functions are usually short-duration, and are the
equivalent of the OP_QUERY_* opcodes in ganeti 1.2 (and they are
internally implemented still with these opcodes). The clients are
guaranteed to receive the response in a reasonable time via a timeout.

The job-related functions will be:

- submit job
- query job (which could also be categorized in the query-functions)
- archive job (see the job queue design doc)
- wait for job change, which allows a client to wait without polling

Daemon implementation
~~~~~~~~~~~~~~~~~~~~~

The daemon will be based around a main I/O thread that will wait for
new requests from the clients, and that does the setup/shutdown of the
other thread (pools).


There will two other classes of threads in the daemon:

- job processing threads, part of a thread pool, and which are
  long-lived, started at daemon startup and terminated only at shutdown
  time
- client I/O threads, which are the ones that talk the local protocol
  to the clients

Master startup/failover
~~~~~~~~~~~~~~~~~~~~~~~

In Ganeti 1.x there is no protection against failing over the master
to a node with stale configuration. In effect, the responsibility of
correct failovers falls on the admin. This is true both for the new
master and for when an old, offline master startup.

Since in 2.x we are extending the cluster state to cover the job queue
and have a daemon that will execute by itself the job queue, we want
to have more resilience for the master role.

The following algorithm will happen whenever a node is ready to
transition to the master role, either at startup time or at node
failover:

#. read the configuration file and parse the node list
   contained within

#. query all the nodes and make sure we obtain an agreement via
   a quorum of at least half plus one nodes for the following:

    - we have the latest configuration and job list (as
      determined by the serial number on the configuration and
      highest job ID on the job queue)

    - there is not even a single node having a newer
      configuration file

    - if we are not failing over (but just starting), the
      quorum agrees that we are the designated master

#. at this point, the node transitions to the master role

#. for all the in-progress jobs, mark them as failed, with
   reason unknown or something similar (master failed, etc.)


Logging
~~~~~~~

The logging system will be switched completely to the logging module;
currently it's logging-based, but exposes a different API, which is
just overhead. As such, the code will be switched over to standard
logging calls, and only the setup will be custom.

With this change, we will remove the separate debug/info/error logs,
and instead have always one logfile per daemon model:

- master-daemon.log for the master daemon
- node-daemon.log for the node daemon (this is the same as in 1.2)
- rapi-daemon.log for the RAPI daemon logs
- rapi-access.log, an additional log file for the RAPI that will be
  in the standard http log format for possible parsing by other tools

Since the watcher will only submit jobs to the master for startup of
the instances, its log file will contain less information than before,
mainly that it will start the instance, but not the results.

Caveats
-------

A discussed alternative is to keep the current individual processes
touching the cluster configuration model. The reasons we have not
chosen this approach is:

- the speed of reading and unserializing the cluster state
  today is not small enough that we can ignore it; the addition of
  the job queue will make the startup cost even higher. While this
  runtime cost is low, it can be on the order of a few seconds on
  bigger clusters, which for very quick commands is comparable to
  the actual duration of the computation itself

- individual commands would make it harder to implement a
  fire-and-forget job request, along the lines "start this
  instance but do not wait for it to finish"; it would require a
  model of backgrounding the operation and other things that are
  much better served by a daemon-based model

Another area of discussion is moving away from Twisted in this new
implementation. While Twisted hase its advantages, there are also many
disatvantanges to using it:

- first and foremost, it's not a library, but a framework; thus, if
  you use twisted, all the code needs to be 'twiste-ized'; we were able
  to keep the 1.x code clean by hacking around twisted in an
  unsupported, unrecommended way, and the only alternative would have
  been to make all the code be written for twisted
- it has some weaknesses in working with multiple threads, since its base
  model is designed to replace thread usage by the deffered, so while it can
  use threads, it's not less flexible in doing so

And, since we already have an http server library (for the RAPI), we
can just reuse that for inter-node communication.
