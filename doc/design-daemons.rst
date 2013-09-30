==========================
Ganeti daemons refactoring
==========================

.. contents:: :depth: 2

This is a design document detailing the plan for refactoring the internal
structure of Ganeti, and particularly the set of daemons it is divided into.


Current state and shortcomings
==============================

Ganeti is comprised of a growing number of daemons, each dealing with part of
the tasks the cluster has to face, and communicating with the other daemons
using a variety of protocols.

Specifically, as of Ganeti 2.8, the situation is as follows:

``Master daemon (MasterD)``
  It is responsible for managing the entire cluster, and it's written in Python.
  It is executed on a single node (the master node). It receives the commands
  given by the cluster administrator (through the remote API daemon or the
  command line tools) over the LUXI protocol.  The master daemon is responsible
  for creating and managing the jobs that will execute such commands, and for
  managing the locks that ensure the cluster will not incur in race conditions.

  Each job is managed by a separate Python thread, that interacts with the node
  daemons via RPC calls.

  The master daemon is also responsible for managing the configuration of the
  cluster, changing it when required by some job. It is also responsible for
  copying the configuration to the other master candidates after updating it.

``RAPI daemon (RapiD)``
  It is written in Python and runs on the master node only. It waits for
  requests issued remotely through the remote API protocol. Then, it forwards
  them, using the LUXI protocol, to the master daemon (if they are commands) or
  to the query daemon if they are queries about the configuration (including
  live status) of the cluster.

``Node daemon (NodeD)``
  It is written in Python. It runs on all the nodes. It is responsible for
  receiving the master requests over RPC and execute them, using the appropriate
  backend (hypervisors, DRBD, LVM, etc.). It also receives requests over RPC for
  the execution of queries gathering live data on behalf of the query daemon.

``Configuration daemon (ConfD)``
  It is written in Haskell. It runs on all the master candidates. Since the
  configuration is replicated only on the master node, this daemon exists in
  order to provide information about the configuration to nodes needing them.
  The requests are done through ConfD's own protocol, HMAC signed,
  implemented over UDP, and meant to be used by parallely querying all the
  master candidates (or a subset thereof) and getting the most up to date
  answer. This is meant as a way to provide a robust service even in case master
  is temporarily unavailable.

``Query daemon (QueryD)``
  It is written in Haskell. It runs on all the master candidates. It replies
  to Luxi queries about the current status of the system, including live data it
  obtains by querying the node daemons through RPCs.

``Monitoring daemon (MonD)``
  It is written in Haskell. It runs on all nodes, including the ones that are
  not vm-capable. It is meant to provide information on the status of the
  system. Such information is related only to the specific node the daemon is
  running on, and it is provided as JSON encoded data over HTTP, to be easily
  readable by external tools.
  The monitoring daemon communicates with ConfD to get information about the
  configuration of the cluster. The choice of communicating with ConfD instead
  of MasterD allows it to obtain configuration information even when the cluster
  is heavily degraded (e.g.: when master and some, but not all, of the master
  candidates are unreachable).

The current structure of the Ganeti daemons is inefficient because there are
many different protocols involved, and each daemon needs to be able to use
multiple ones, and has to deal with doing different things, thus making
sometimes unclear which daemon is responsible for performing a specific task.

Also, with the current configuration, jobs are managed by the master daemon
using python threads. This makes terminating a job after it has started a
difficult operation, and it is the main reason why this is not possible yet.

The master daemon currently has too many different tasks, that could be handled
better if split among different daemons.


Proposed changes
================

In order to improve on the current situation, a new daemon subdivision is
proposed, and presented hereafter.

.. digraph:: "new-daemons-structure"

  {rank=same; RConfD LuxiD;}
  {rank=same; Jobs rconfigdata;}
  node [shape=box]
  RapiD [label="RapiD [M]"]
  LuxiD [label="LuxiD [M]"]
  WConfD [label="WConfD [M]"]
  Jobs [label="Jobs [M]"]
  RConfD [label="RConfD [MC]"]
  MonD [label="MonD [All]"]
  NodeD [label="NodeD [All]"]
  Clients [label="gnt-*\nclients [M]"]
  p1 [shape=none, label=""]
  p2 [shape=none, label=""]
  p3 [shape=none, label=""]
  p4 [shape=none, label=""]
  configdata [shape=none, label="config.data"]
  rconfigdata [shape=none, label="config.data\n[MC copy]"]
  locksdata [shape=none, label="locks.data"]

  RapiD -> LuxiD [label="LUXI"]
  LuxiD -> WConfD [label="WConfD\nproto"]
  LuxiD -> Jobs [label="fork/exec"]
  Jobs -> WConfD [label="WConfD\nproto"]
  Jobs -> NodeD [label="RPC"]
  LuxiD -> NodeD [label="RPC"]
  rconfigdata -> RConfD
  configdata -> rconfigdata [label="sync via\nNodeD RPC"]
  WConfD -> NodeD [label="RPC"]
  WConfD -> configdata
  WConfD -> locksdata
  MonD -> RConfD [label="RConfD\nproto"]
  Clients -> LuxiD [label="LUXI"]
  p1 -> MonD [label="MonD proto"]
  p2 -> RapiD [label="RAPI"]
  p3 -> RConfD [label="RConfD\nproto"]
  p4 -> Clients [label="CLI"]

``LUXI daemon (LuxiD)``
  It will be written in Haskell. It will run on the master node and it will be
  the only LUXI server, replying to all the LUXI queries. These includes both
  the queries about the live configuration of the cluster, previously served by
  QueryD, and the commands actually changing the status of the cluster by
  submitting jobs. Therefore, this daemon will also be the one responsible with
  managing the job queue. When a job needs to be executed, the LuxiD will spawn
  a separate process tasked with the execution of that specific job, thus making
  it easier to terminate the job itself, if needeed.  When a job requires locks,
  LuxiD will request them from WConfD.
  In order to keep availability of the cluster in case of failure of the master
  node, LuxiD will replicate the job queue to the other master candidates, by
  RPCs to the NodeD running there (the choice of RPCs for this task might be
  reviewed at a second time, after implementing this design).

``Configuration management daemon (WConfD)``
  It will run on the master node and it will be responsible for the management
  of the authoritative copy of the cluster configuration (that is, it will be
  the daemon actually modifying the ``config.data`` file). All the requests of
  configuration changes will have to pass through this daemon, and will be
  performed using a LUXI-like protocol ("WConfD proto" in the graph. The exact
  protocol will be defined in the separate design document that will detail the
  WConfD separation).  Having a single point of configuration management will
  also allow Ganeti to get rid of possible race conditions due to concurrent
  modifications of the configuration.  When the configuration is updated, it
  will have to push the received changes to the other master candidates, via
  RPCs, so that RConfD daemons and (in case of a failure on the master node)
  the WConfD daemon on the new master can access an up-to-date version of it
  (the choice of RPCs for this task might be reviewed at a second time). This
  daemon will also be the one responsible for managing the locks, granting them
  to the jobs requesting them, and taking care of freeing them up if the jobs
  holding them crash or are terminated before releasing them.  In order to do
  this, each job, after being spawned by LuxiD, will open a local unix socket
  that will be used to communicate with it, and will be destroyed when the job
  terminates.  LuxiD will be able to check, after a timeout, whether the job is
  still running by connecting here, and to ask WConfD to forcefully remove the
  locks if the socket is closed.
  Also, WConfD should hold a serialized list of the locks and their owners in a
  file (``locks.data``), so that it can keep track of their status in case it
  crashes and needs to be restarted (by asking LuxiD which of them are still
  running).
  Interaction with this daemon will be performed using Unix sockets.

``Configuration query daemon (RConfD)``
  It is written in Haskell, and it corresponds to the old ConfD. It will run on
  all the master candidates and it will serve information about the the static
  configuration of the cluster (the one contained in ``config.data``). The
  provided information will be highly available (as in: a response will be
  available as long as a stable-enough connection between the client and at
  least one working master candidate is available) and its freshness will be
  best effort (the most recent reply from any of the master candidates will be
  returned, but it might still be older than the one available through WConfD).
  The information will be served through the ConfD protocol.

``Rapi daemon (RapiD)``
  It remains basically unchanged, with the only difference that all of its LUXI
  query are directed towards LuxiD instead of being split between MasterD and
  QueryD.

``Monitoring daemon (MonD)``
  It remains unaffected by the changes in this design document. It will just get
  some of the data it needs from RConfD instead of the old ConfD, but the
  interfaces of the two are identical.

``Node daemon (NodeD)``
  It remains unaffected by the changes proposed in the design document. The only
  difference being that it will receive its RPCs from LuxiD (for job queue
  replication), from WConfD (for configuration replication) and for the
  processes executing single jobs (for all the operations to be performed by
  nodes) instead of receiving them just from MasterD.

This restructuring will allow us to reorganize and improve the codebase,
introducing cleaner interfaces and giving well defined and more restricted tasks
to each daemon.

Furthermore, having more well-defined interfaces will allow us to have easier
upgrade procedures, and to work towards the possibility of upgrading single
components of a cluster one at a time, without the need for immediately
upgrading the entire cluster in a single step.


Implementation
==============

While performing this refactoring, we aim to increase the amount of
Haskell code, thus benefiting from the additional type safety provided by its
wide compile-time checks. In particular, all the job queue management and the
configuration management daemon will be written in Haskell, taking over the role
currently fulfilled by Python code executed as part of MasterD.

The changes describe by this design document are quite extensive, therefore they
will not be implemented all at the same time, but through a sequence of steps,
leaving the codebase in a consistent and usable state.

#. Rename QueryD to LuxiD.
   A part of LuxiD, the one replying to configuration
   queries including live information about the system, already exists in the
   form of QueryD. This is being renamed to LuxiD, and will form the first part
   of the new daemon. NB: this is happening starting from Ganeti 2.8. At the
   beginning, only the already existing queries will be replied to by LuxiD.
   More queries will be implemented in the next versions.

#. Let LuxiD be the interface for the queries and MasterD be their executor.
   Currently, MasterD is the only responsible for receiving and executing LUXI
   queries, and for managing the jobs they create.
   Receiving the queries and managing the job queue will be extracted from
   MasterD into LuxiD.
   Actually executing jobs will still be done by MasterD, that contains all the
   logic for doing that and for properly managing locks and the configuration.
   A separate design document will detail how the system will decide which jobs
   to send over for execution, and how to rate-limit them.

#. Extract WConfD from MasterD.
   The logic for managing the configuration file is factored out to the
   dedicated WConfD daemon. All configuration changes, currently executed
   directly by MasterD, will be changed to be IPC requests sent to the new
   daemon.

#. Extract locking management from MasterD.
   The logic for managing and granting locks is extracted to WConfD as well.
   Locks will not be taken directly anymore, but asked via IPC to WConfD.
   This step can be executed on its own or at the same time as the previous one.

#. Jobs are executed as processes.
   The logic for running jobs is rewritten so that each job can be managed by an
   independent process. LuxiD will spawn a new (Python) process for every single
   job. The RPCs will remain unchanged, and the LU code will stay as is as much
   as possible.
   MasterD will cease to exist as a deamon on its own at this point, but not
   before.

Further considerations
======================

There is a possibility that a job will finish performing its task while LuxiD
and/or WConfD will not be available.
In order to deal with this situation, each job will write the results of its
execution on a file. The name of this file will be known to LuxiD before
starting the job, and will be stored together with the job ID, and the
name of the job-unique socket.

The job, upon ending its execution, will signal LuxiD (through the socket), so
that it can read the result of the execution and release the locks as needed.

In case LuxiD is not available at that time, the job will just terminate without
signalling it, and writing the results on file as usual. When a new LuxiD
becomes available, it will have the most up-to-date list of running jobs
(received via replication from the former LuxiD), and go through it, cleaning up
all the terminated jobs.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
