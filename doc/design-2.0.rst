=================
Ganeti 2.0 design
=================

This document describes the major changes in Ganeti 2.0 compared to
the 1.2 version.

The 2.0 version will constitute a rewrite of the 'core' architecture,
paving the way for additional features in future 2.x versions.

.. contents::

Objective
=========

Ganeti 1.2 has many scalability issues and restrictions due to its
roots as software for managing small and 'static' clusters.

Version 2.0 will attempt to remedy first the scalability issues and
then the restrictions.

Background
==========

While Ganeti 1.2 is usable, it severly limits the flexibility of the
cluster administration and imposes a very rigid model. It has the
following main scalability issues:

- only one operation at a time on the cluster [#]_
- poor handling of node failures in the cluster
- mixing hypervisors in a cluster not allowed

It also has a number of artificial restrictions, due to historical design:

- fixed number of disks (two) per instance
- fixed number of nics

.. [#] Replace disks will release the lock, but this is an exception
       and not a recommended way to operate

The 2.0 version is intended to address some of these problems, and
create a more flexible codebase for future developments.

Scalability problems
--------------------

Ganeti 1.2 has a single global lock, which is used for all cluster
operations.  This has been painful at various times, for example:

- It is impossible for two people to efficiently interact with a cluster
  (for example for debugging) at the same time.
- When batch jobs are running it's impossible to do other work (for example
  failovers/fixes) on a cluster.

This poses scalability problems: as clusters grow in node and instance
size it's a lot more likely that operations which one could conceive
should run in parallel (for example because they happen on different
nodes) are actually stalling each other while waiting for the global
lock, without a real reason for that to happen.

One of the main causes of this global lock (beside the higher
difficulty of ensuring data consistency in a more granular lock model)
is the fact that currently there is no "master" daemon in Ganeti. Each
command tries to acquire the so called *cmd* lock and when it
succeeds, it takes complete ownership of the cluster configuration and
state.

Other scalability problems are due the design of the DRBD device
model, which assumed at its creation a low (one to four) number of
instances per node, which is no longer true with today's hardware.

Artificial restrictions
-----------------------

Ganeti 1.2 (and previous versions) have a fixed two-disks, one-NIC per
instance model. This is a purely artificial restrictions, but it
touches multiple areas (configuration, import/export, command line)
that it's more fitted to a major release than a minor one.

Overview
========

In order to solve the scalability problems, a rewrite of the core
design of Ganeti is required. While the cluster operations themselves
won't change (e.g. start instance will do the same things, the way
these operations are scheduled internally will change radically.

The new design will change the cluster architecture to:

.. image:: arch-2.0.png

This differs from the 1.2 architecture by the addition of the master
daemon, which will be the only entity to talk to the node daemons.


Detailed design
===============

The changes for 2.0 can be split into roughly three areas:

- core changes that affect the design of the software
- features (or restriction removals) but which do not have a wide
  impact on the design
- user-level and API-level changes which translate into differences for
  the operation of the cluster

Core changes
------------

The main changes will be switching from a per-process model to a
daemon based model, where the individual gnt-* commands will be
clients that talk to this daemon (see the design-2.0-master-daemon
document). This will allow us to get rid of the global cluster lock
for most operations, having instead a per-object lock (see
design-2.0-granular-locking). Also, the daemon will be able to queue
jobs, and this will allow the invidual clients to submit jobs without
waiting for them to finish, and also see the result of old requests
(see design-2.0-job-queue).

Beside these major changes, another 'core' change but that will not be
as visible to the users will be changing the model of object attribute
storage, and separate that into namespaces (such that an Xen PVM
instance will not have the Xen HVM parameters). This will allow future
flexibility in defining additional parameters. More details in the
design-2.0-cluster-parameters document.

The various changes brought in by the master daemon model and the
read-write RAPI will require changes to the cluster security; we move
away from Twisted and use http(s) for intra- and extra-cluster
communications. For more details, see the security document in the
doc/ directory.

Master daemon
~~~~~~~~~~~~~

In Ganeti 2.0, we will have the following *entities*:

- the master daemon (on the master node)
- the node daemon (on all nodes)
- the command line tools (on the master node)
- the RAPI daemon (on the master node)

Interaction paths are between:

- (CLI tools/RAPI daemon) and the master daemon, via the so called *luxi* API
- the master daemon and the node daemons, via the node RPC

The protocol between the master daemon and the node daemons will be
changed to HTTP(S), using a simple PUT/GET of JSON-encoded
messages. This is done due to difficulties in working with the Twisted
framework and its protocols in a multithreaded environment, which we
can overcome by using a simpler stack (see the caveats section). The
protocol between the CLI/RAPI and the master daemon will be a custom
one (called *luxi*): on a UNIX socket on the master node, with rights
restricted by filesystem permissions, the CLI/RAPI will talk to the
master daemon using JSON-encoded messages.

The operations supported over this internal protocol will be encoded
via a python library that will expose a simple API for its
users. Internally, the protocol will simply encode all objects in JSON
format and decode them on the receiver side.

The LUXI protocol
+++++++++++++++++

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

For more details, see the job queue design document.

Daemon implementation
+++++++++++++++++++++

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
+++++++++++++++++++++++

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
+++++++

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
+++++++

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
  model is designed to replace thread usage by using deferred calls, so while
  it can use threads, it's not less flexible in doing so

And, since we already have an HTTP server library for the RAPI, we
can just reuse that for inter-node communication.


Granular locking
~~~~~~~~~~~~~~~~

We want to make sure that multiple operations can run in parallel on a Ganeti
Cluster. In order for this to happen we need to make sure concurrently run
operations don't step on each other toes and break the cluster.

This design addresses how we are going to deal with locking so that:

- high urgency operations are not stopped by long length ones
- long length operations can run in parallel
- we preserve safety (data coherency) and liveness (no deadlock, no work
  postponed indefinitely) on the cluster

Reaching the maximum possible parallelism is a Non-Goal. We have identified a
set of operations that are currently bottlenecks and need to be parallelised
and have worked on those. In the future it will be possible to address other
needs, thus making the cluster more and more parallel one step at a time.

This document only talks about parallelising Ganeti level operations, aka
Logical Units, and the locking needed for that. Any other synchronisation lock
needed internally by the code is outside its scope.

Ganeti 1.2
++++++++++

We intend to implement a Ganeti locking library, which can be used by the
various ganeti code components in order to easily, efficiently and correctly
grab the locks they need to perform their function.

The proposed library has these features:

- Internally managing all the locks, making the implementation transparent
  from their usage
- Automatically grabbing multiple locks in the right order (avoid deadlock)
- Ability to transparently handle conversion to more granularity
- Support asynchronous operation (future goal)

Locking will be valid only on the master node and will not be a distributed
operation. In case of master failure, though, if some locks were held it means
some opcodes were in progress, so when recovery of the job queue is done it
will be possible to determine by the interrupted opcodes which operations could
have been left half way through and thus which locks could have been held. It
is then the responsibility either of the master failover code, of the cluster
verification code, or of the admin to do what's necessary to make sure that any
leftover state is dealt with. This is not an issue from a locking point of view
because the fact that the previous master has failed means that it cannot do
any job.

A corollary of this is that a master-failover operation with both masters alive
needs to happen while no other locks are held.

The Locks
+++++++++

At the first stage we have decided to provide the following locks:

- One "config file" lock
- One lock per node in the cluster
- One lock per instance in the cluster

All the instance locks will need to be taken before the node locks, and the
node locks before the config lock. Locks will need to be acquired at the same
time for multiple instances and nodes, and internal ordering will be dealt
within the locking library, which, for simplicity, will just use alphabetical
order.

Handling conversion to more granularity
+++++++++++++++++++++++++++++++++++++++

In order to convert to a more granular approach transparently each time we
split a lock into more we'll create a "metalock", which will depend on those
sublocks and live for the time necessary for all the code to convert (or
forever, in some conditions). When a metalock exists all converted code must
acquire it in shared mode, so it can run concurrently, but still be exclusive
with old code, which acquires it exclusively.

In the beginning the only such lock will be what replaces the current "command"
lock, and will acquire all the locks in the system, before proceeding. This
lock will be called the "Big Ganeti Lock" because holding that one will avoid
any other concurrent ganeti operations.

We might also want to devise more metalocks (eg. all nodes, all nodes+config)
in order to make it easier for some parts of the code to acquire what it needs
without specifying it explicitly.

In the future things like the node locks could become metalocks, should we
decide to split them into an even more fine grained approach, but this will
probably be only after the first 2.0 version has been released.

Library API
+++++++++++

All the locking will be its own class, and the locks will be created at
initialisation time, from the config file.

The API will have a way to grab one or more than one locks at the same time.
Any attempt to grab a lock while already holding one in the wrong order will be
checked for, and fail.

Adding/Removing locks
+++++++++++++++++++++

When a new instance or a new node is created an associated lock must be added
to the list. The relevant code will need to inform the locking library of such
a change.

This needs to be compatible with every other lock in the system, especially
metalocks that guarantee to grab sets of resources without specifying them
explicitly. The implementation of this will be handled in the locking library
itself.

Of course when instances or nodes disappear from the cluster the relevant locks
must be removed. This is easier than adding new elements, as the code which
removes them must own them exclusively or can queue for their ownership, and
thus deals with metalocks exactly as normal code acquiring those locks. Any
operation queueing on a removed lock will fail after its removal.

Asynchronous operations
+++++++++++++++++++++++

For the first version the locking library will only export synchronous
operations, which will block till the needed lock are held, and only fail if
the request is impossible or somehow erroneous.

In the future we may want to implement different types of asynchronous
operations such as:

- Try to acquire this lock set and fail if not possible
- Try to acquire one of these lock sets and return the first one you were
  able to get (or after a timeout) (select/poll like)

These operations can be used to prioritize operations based on available locks,
rather than making them just blindly queue for acquiring them. The inherent
risk, though, is that any code using the first operation, or setting a timeout
for the second one, is susceptible to starvation and thus may never be able to
get the required locks and complete certain tasks. Considering this
providing/using these operations should not be among our first priorities.

Locking granularity
+++++++++++++++++++

For the first version of this code we'll convert each Logical Unit to
acquire/release the locks it needs, so locking will be at the Logical Unit
level.  In the future we may want to split logical units in independent
"tasklets" with their own locking requirements. A different design doc (or mini
design doc) will cover the move from Logical Units to tasklets.

Lock acquisition code path
++++++++++++++++++++++++++

In general when acquiring locks we should use a code path equivalent to::

  lock.acquire()
  try:
    ...
    # other code
  finally:
    lock.release()

This makes sure we release all locks, and avoid possible deadlocks. Of course
extra care must be used not to leave, if possible locked structures in an
unusable state.

In order to avoid this extra indentation and code changes everywhere in the
Logical Units code, we decided to allow LUs to declare locks, and then execute
their code with their locks acquired. In the new world LUs are called like
this::

  # user passed names are expanded to the internal lock/resource name,
  # then known needed locks are declared
  lu.ExpandNames()
  ... some locking/adding of locks may happen ...
  # late declaration of locks for one level: this is useful because sometimes
  # we can't know which resource we need before locking the previous level
  lu.DeclareLocks() # for each level (cluster, instance, node)
  ... more locking/adding of locks can happen ...
  # these functions are called with the proper locks held
  lu.CheckPrereq()
  lu.Exec()
  ... locks declared for removal are removed, all acquired locks released ...

The Processor and the LogicalUnit class will contain exact documentation on how
locks are supposed to be declared.

Caveats
+++++++

This library will provide an easy upgrade path to bring all the code to
granular locking without breaking everything, and it will also guarantee
against a lot of common errors. Code switching from the old "lock everything"
lock to the new system, though, needs to be carefully scrutinised to be sure it
is really acquiring all the necessary locks, and none has been overlooked or
forgotten.

The code can contain other locks outside of this library, to synchronise other
threaded code (eg for the job queue) but in general these should be leaf locks
or carefully structured non-leaf ones, to avoid deadlock race conditions.


Job Queue
~~~~~~~~~

Granular locking is not enough to speed up operations, we also need a
queue to store these and to be able to process as many as possible in
parallel.

A ganeti job will consist of multiple ``OpCodes`` which are the basic
element of operation in Ganeti 1.2 (and will remain as such). Most
command-level commands are equivalent to one OpCode, or in some cases
to a sequence of opcodes, all of the same type (e.g. evacuating a node
will generate N opcodes of type replace disks).


Job execution—“Life of a Ganeti job”
++++++++++++++++++++++++++++++++++++

#. Job gets submitted by the client. A new job identifier is generated and
   assigned to the job. The job is then automatically replicated [#replic]_
   to all nodes in the cluster. The identifier is returned to the client.
#. A pool of worker threads waits for new jobs. If all are busy, the job has
   to wait and the first worker finishing its work will grab it. Otherwise any
   of the waiting threads will pick up the new job.
#. Client waits for job status updates by calling a waiting RPC function.
   Log message may be shown to the user. Until the job is started, it can also
   be cancelled.
#. As soon as the job is finished, its final result and status can be retrieved
   from the server.
#. If the client archives the job, it gets moved to a history directory.
   There will be a method to archive all jobs older than a a given age.

.. [#replic] We need replication in order to maintain the consistency across
   all nodes in the system; the master node only differs in the fact that
   now it is running the master daemon, but it if fails and we do a master
   failover, the jobs are still visible on the new master (though marked as
   failed).

Failures to replicate a job to other nodes will be only flagged as
errors in the master daemon log if more than half of the nodes failed,
otherwise we ignore the failure, and rely on the fact that the next
update (for still running jobs) will retry the update. For finished
jobs, it is less of a problem.

Future improvements will look into checking the consistency of the job
list and jobs themselves at master daemon startup.


Job storage
+++++++++++

Jobs are stored in the filesystem as individual files, serialized
using JSON (standard serialization mechanism in Ganeti).

The choice of storing each job in its own file was made because:

- a file can be atomically replaced
- a file can easily be replicated to other nodes
- checking consistency across nodes can be implemented very easily, since
  all job files should be (at a given moment in time) identical

The other possible choices that were discussed and discounted were:

- single big file with all job data: not feasible due to difficult updates
- in-process databases: hard to replicate the entire database to the
  other nodes, and replicating individual operations does not mean wee keep
  consistency


Queue structure
+++++++++++++++

All file operations have to be done atomically by writing to a temporary file
and subsequent renaming. Except for log messages, every change in a job is
stored and replicated to other nodes.

::

  /var/lib/ganeti/queue/
    job-1 (JSON encoded job description and status)
    […]
    job-37
    job-38
    job-39
    lock (Queue managing process opens this file in exclusive mode)
    serial (Last job ID used)
    version (Queue format version)


Locking
+++++++

Locking in the job queue is a complicated topic. It is called from more than
one thread and must be thread-safe. For simplicity, a single lock is used for
the whole job queue.

A more detailed description can be found in doc/locking.txt.


Internal RPC
++++++++++++

RPC calls available between Ganeti master and node daemons:

jobqueue_update(file_name, content)
  Writes a file in the job queue directory.
jobqueue_purge()
  Cleans the job queue directory completely, including archived job.
jobqueue_rename(old, new)
  Renames a file in the job queue directory.


Client RPC
++++++++++

RPC between Ganeti clients and the Ganeti master daemon supports the following
operations:

SubmitJob(ops)
  Submits a list of opcodes and returns the job identifier. The identifier is
  guaranteed to be unique during the lifetime of a cluster.
WaitForJobChange(job_id, fields, […], timeout)
  This function waits until a job changes or a timeout expires. The condition
  for when a job changed is defined by the fields passed and the last log
  message received.
QueryJobs(job_ids, fields)
  Returns field values for the job identifiers passed.
CancelJob(job_id)
  Cancels the job specified by identifier. This operation may fail if the job
  is already running, canceled or finished.
ArchiveJob(job_id)
  Moves a job into the …/archive/ directory. This operation will fail if the
  job has not been canceled or finished.


Job and opcode status
+++++++++++++++++++++

Each job and each opcode has, at any time, one of the following states:

Queued
  The job/opcode was submitted, but did not yet start.
Waiting
  The job/opcode is waiting for a lock to proceed.
Running
  The job/opcode is running.
Canceled
  The job/opcode was canceled before it started.
Success
  The job/opcode ran and finished successfully.
Error
  The job/opcode was aborted with an error.

If the master is aborted while a job is running, the job will be set to the
Error status once the master started again.


History
+++++++

Archived jobs are kept in a separate directory,
/var/lib/ganeti/queue/archive/.  This is done in order to speed up the
queue handling: by default, the jobs in the archive are not touched by
any functions. Only the current (unarchived) jobs are parsed, loaded,
and verified (if implemented) by the master daemon.


Ganeti updates
++++++++++++++

The queue has to be completely empty for Ganeti updates with changes
in the job queue structure. In order to allow this, there will be a
way to prevent new jobs entering the queue.



Object parameters
~~~~~~~~~~~~~~~~~

Across all cluster configuration data, we have multiple classes of
parameters:

A. cluster-wide parameters (e.g. name of the cluster, the master);
   these are the ones that we have today, and are unchanged from the
   current model

#. node parameters

#. instance specific parameters, e.g. the name of disks (LV), that
   cannot be shared with other instances

#. instance parameters, that are or can be the same for many
   instances, but are not hypervisor related; e.g. the number of VCPUs,
   or the size of memory

#. instance parameters that are hypervisor specific (e.g. kernel_path
   or PAE mode)


The following definitions for instance parameters will be used below:

:hypervisor parameter:
  a hypervisor parameter (or hypervisor specific parameter) is defined
  as a parameter that is interpreted by the hypervisor support code in
  Ganeti and usually is specific to a particular hypervisor (like the
  kernel path for PVM which makes no sense for HVM).

:backend parameter:
  a backend parameter is defined as an instance parameter that can be
  shared among a list of instances, and is either generic enough not
  to be tied to a given hypervisor or cannot influence at all the
  hypervisor behaviour.

  For example: memory, vcpus, auto_balance

  All these parameters will be encoded into constants.py with the prefix "BE\_"
  and the whole list of parameters will exist in the set "BES_PARAMETERS"

:proper parameter:
  a parameter whose value is unique to the instance (e.g. the name of a LV,
  or the MAC of a NIC)

As a general rule, for all kind of parameters, “None” (or in
JSON-speak, “nil”) will no longer be a valid value for a parameter. As
such, only non-default parameters will be saved as part of objects in
the serialization step, reducing the size of the serialized format.

Cluster parameters
++++++++++++++++++

Cluster parameters remain as today, attributes at the top level of the
Cluster object. In addition, two new attributes at this level will
hold defaults for the instances:

- hvparams, a dictionary indexed by hypervisor type, holding default
  values for hypervisor parameters that are not defined/overrided by
  the instances of this hypervisor type

- beparams, a dictionary holding (for 2.0) a single element 'default',
  which holds the default value for backend parameters

Node parameters
+++++++++++++++

Node-related parameters are very few, and we will continue using the
same model for these as previously (attributes on the Node object).

Instance parameters
+++++++++++++++++++

As described before, the instance parameters are split in three:
instance proper parameters, unique to each instance, instance
hypervisor parameters and instance backend parameters.

The “hvparams” and “beparams” are kept in two dictionaries at instance
level. Only non-default parameters are stored (but once customized, a
parameter will be kept, even with the same value as the default one,
until reset).

The names for hypervisor parameters in the instance.hvparams subtree
should be choosen as generic as possible, especially if specific
parameters could conceivably be useful for more than one hypervisor,
e.g. instance.hvparams.vnc_console_port instead of using both
instance.hvparams.hvm_vnc_console_port and
instance.hvparams.kvm_vnc_console_port.

There are some special cases related to disks and NICs (for example):
a disk has both ganeti-related parameters (e.g. the name of the LV)
and hypervisor-related parameters (how the disk is presented to/named
in the instance). The former parameters remain as proper-instance
parameters, while the latter value are migrated to the hvparams
structure. In 2.0, we will have only globally-per-instance such
hypervisor parameters, and not per-disk ones (e.g. all NICs will be
exported as of the same type).

Starting from the 1.2 list of instance parameters, here is how they
will be mapped to the three classes of parameters:

- name (P)
- primary_node (P)
- os (P)
- hypervisor (P)
- status (P)
- memory (BE)
- vcpus (BE)
- nics (P)
- disks (P)
- disk_template (P)
- network_port (P)
- kernel_path (HV)
- initrd_path (HV)
- hvm_boot_order (HV)
- hvm_acpi (HV)
- hvm_pae (HV)
- hvm_cdrom_image_path (HV)
- hvm_nic_type (HV)
- hvm_disk_type (HV)
- vnc_bind_address (HV)
- serial_no (P)


Parameter validation
++++++++++++++++++++

To support the new cluster parameter design, additional features will
be required from the hypervisor support implementations in Ganeti.

The hypervisor support  implementation API will be extended with the
following features:

:PARAMETERS: class-level attribute holding the list of valid parameters
  for this hypervisor
:CheckParamSyntax(hvparams): checks that the given parameters are
  valid (as in the names are valid) for this hypervisor; usually just
  comparing hvparams.keys() and cls.PARAMETERS; this is a class method
  that can be called from within master code (i.e. cmdlib) and should
  be safe to do so
:ValidateParameters(hvparams): verifies the values of the provided
  parameters against this hypervisor; this is a method that will be
  called on the target node, from backend.py code, and as such can
  make node-specific checks (e.g. kernel_path checking)

Default value application
+++++++++++++++++++++++++

The application of defaults to an instance is done in the Cluster
object, via two new methods as follows:

- ``Cluster.FillHV(instance)``, returns 'filled' hvparams dict, based on
  instance's hvparams and cluster's ``hvparams[instance.hypervisor]``

- ``Cluster.FillBE(instance, be_type="default")``, which returns the
  beparams dict, based on the instance and cluster beparams

The FillHV/BE transformations will be used, for example, in the RpcRunner
when sending an instance for activation/stop, and the sent instance
hvparams/beparams will have the final value (noded code doesn't know
about defaults).

LU code will need to self-call the transformation, if needed.

Opcode changes
++++++++++++++

The parameter changes will have impact on the OpCodes, especially on
the following ones:

- OpCreateInstance, where the new hv and be parameters will be sent as
  dictionaries; note that all hv and be parameters are now optional, as
  the values can be instead taken from the cluster
- OpQueryInstances, where we have to be able to query these new
  parameters; the syntax for names will be ``hvparam/$NAME`` and
  ``beparam/$NAME`` for querying an individual parameter out of one
  dictionary, and ``hvparams``, respectively ``beparams``, for the whole
  dictionaries
- OpModifyInstance, where the the modified parameters are sent as
  dictionaries

Additionally, we will need new OpCodes to modify the cluster-level
defaults for the be/hv sets of parameters.

Caveats
+++++++

One problem that might appear is that our classification is not
complete or not good enough, and we'll need to change this model. As
the last resort, we will need to rollback and keep 1.2 style.

Another problem is that classification of one parameter is unclear
(e.g. ``network_port``, is this BE or HV?); in this case we'll take
the risk of having to move parameters later between classes.

Security
++++++++

The only security issue that we foresee is if some new parameters will
have sensitive value. If so, we will need to have a way to export the
config data while purging the sensitive value.

E.g. for the drbd shared secrets, we could export these with the
values replaced by an empty string.

Feature changes
---------------

The main feature-level changes will be:

- a number of disk related changes
- removal of fixed two-disk, one-nic per instance limitation

Disk handling changes
~~~~~~~~~~~~~~~~~~~~~

The storage options available in Ganeti 1.x were introduced based on
then-current software (first DRBD 0.7 then later DRBD 8) and the
estimated usage patters. However, experience has later shown that some
assumptions made initially are not true and that more flexibility is
needed.

One main assupmtion made was that disk failures should be treated as 'rare'
events, and that each of them needs to be manually handled in order to ensure
data safety; however, both these assumptions are false:

- disk failures can be a common occurence, based on usage patterns or cluster
  size
- our disk setup is robust enough (referring to DRBD8 + LVM) that we could
  automate more of the recovery

Note that we still don't have fully-automated disk recovery as a goal, but our
goal is to reduce the manual work needed.

As such, we plan the following main changes:

- DRBD8 is much more flexible and stable than its previous version (0.7),
  such that removing the support for the ``remote_raid1`` template and
  focusing only on DRBD8 is easier

- dynamic discovery of DRBD devices is not actually needed in a cluster that
  where the DRBD namespace is controlled by Ganeti; switching to a static
  assignment (done at either instance creation time or change secondary time)
  will change the disk activation time from O(n) to O(1), which on big
  clusters is a significant gain

- remove the hard dependency on LVM (currently all available storage types are
  ultimately backed by LVM volumes) by introducing file-based storage

Additionally, a number of smaller enhancements are also planned:
- support variable number of disks
- support read-only disks

Future enhancements in the 2.x series, which do not require base design
changes, might include:

- enhancement of the LVM allocation method in order to try to keep
  all of an instance's virtual disks on the same physical
  disks

- add support for DRBD8 authentication at handshake time in
  order to ensure each device connects to the correct peer

- remove the restrictions on failover only to the secondary
  which creates very strict rules on cluster allocation

DRBD minor allocation
+++++++++++++++++++++

Currently, when trying to identify or activate a new DRBD (or MD)
device, the code scans all in-use devices in order to see if we find
one that looks similar to our parameters and is already in the desired
state or not. Since this needs external commands to be run, it is very
slow when more than a few devices are already present.

Therefore, we will change the discovery model from dynamic to
static. When a new device is logically created (added to the
configuration) a free minor number is computed from the list of
devices that should exist on that node and assigned to that
device.

At device activation, if the minor is already in use, we check if
it has our parameters; if not so, we just destroy the device (if
possible, otherwise we abort) and start it with our own
parameters.

This means that we in effect take ownership of the minor space for
that device type; if there's a user-created drbd minor, it will be
automatically removed.

The change will have the effect of reducing the number of external
commands run per device from a constant number times the index of the
first free DRBD minor to just a constant number.

Removal of obsolete device types (md, drbd7)
++++++++++++++++++++++++++++++++++++++++++++

We need to remove these device types because of two issues. First,
drbd7 has bad failure modes in case of dual failures (both network and
disk - it cannot propagate the error up the device stack and instead
just panics. Second, due to the assymetry between primary and
secondary in md+drbd mode, we cannot do live failover (not even if we
had md+drbd8).

File-based storage support
++++++++++++++++++++++++++

This is covered by a separate design doc (<em>Vinales</em>) and
would allow us to get rid of the hard requirement for testing
clusters; it would also allow people who have SAN storage to do live
failover taking advantage of their storage solution.

Better LVM allocation
+++++++++++++++++++++

Currently, the LV to PV allocation mechanism is a very simple one: at
each new request for a logical volume, tell LVM to allocate the volume
in order based on the amount of free space. This is good for
simplicity and for keeping the usage equally spread over the available
physical disks, however it introduces a problem that an instance could
end up with its (currently) two drives on two physical disks, or
(worse) that the data and metadata for a DRBD device end up on
different drives.

This is bad because it causes unneeded ``replace-disks`` operations in
case of a physical failure.

The solution is to batch allocations for an instance and make the LVM
handling code try to allocate as close as possible all the storage of
one instance. We will still allow the logical volumes to spill over to
additional disks as needed.

Note that this clustered allocation can only be attempted at initial
instance creation, or at change secondary node time. At add disk time,
or at replacing individual disks, it's not easy enough to compute the
current disk map so we'll not attempt the clustering.

DRBD8 peer authentication at handshake
++++++++++++++++++++++++++++++++++++++

DRBD8 has a new feature that allow authentication of the peer at
connect time. We can use this to prevent connecting to the wrong peer
more that securing the connection. Even though we never had issues
with wrong connections, it would be good to implement this.


LVM self-repair (optional)
++++++++++++++++++++++++++

The complete failure of a physical disk is very tedious to
troubleshoot, mainly because of the many failure modes and the many
steps needed. We can safely automate some of the steps, more
specifically the ``vgreduce --removemissing`` using the following
method:

#. check if all nodes have consistent volume groups
#. if yes, and previous status was yes, do nothing
#. if yes, and previous status was no, save status and restart
#. if no, and previous status was no, do nothing
#. if no, and previous status was yes:
    #. if more than one node is inconsistent, do nothing
    #. if only one node is incosistent:
        #. run ``vgreduce --removemissing``
        #. log this occurence in the ganeti log in a form that
           can be used for monitoring
        #. [FUTURE] run ``replace-disks`` for all
           instances affected

Failover to any node
++++++++++++++++++++

With a modified disk activation sequence, we can implement the
*failover to any* functionality, removing many of the layout
restrictions of a cluster:

- the need to reserve memory on the current secondary: this gets reduced to
  a must to reserve memory anywhere on the cluster

- the need to first failover and then replace secondary for an
  instance: with failover-to-any, we can directly failover to
  another node, which also does the replace disks at the same
  step

In the following, we denote the current primary by P1, the current
secondary by S1, and the new primary and secondaries by P2 and S2. P2
is fixed to the node the user chooses, but the choice of S2 can be
made between P1 and S1. This choice can be constrained, depending on
which of P1 and S1 has failed.

- if P1 has failed, then S1 must become S2, and live migration is not possible
- if S1 has failed, then P1 must become S2, and live migration could be
  possible (in theory, but this is not a design goal for 2.0)

The algorithm for performing the failover is straightforward:

- verify that S2 (the node the user has chosen to keep as secondary) has
  valid data (is consistent)

- tear down the current DRBD association and setup a drbd pairing between
  P2 (P2 is indicated by the user) and S2; since P2 has no data, it will
  start resyncing from S2

- as soon as P2 is in state SyncTarget (i.e. after the resync has started
  but before it has finished), we can promote it to primary role (r/w)
  and start the instance on P2

- as soon as the P2?S2 sync has finished, we can remove
  the old data on the old node that has not been chosen for
  S2

Caveats: during the P2?S2 sync, a (non-transient) network error
will cause I/O errors on the instance, so (if a longer instance
downtime is acceptable) we can postpone the restart of the instance
until the resync is done. However, disk I/O errors on S2 will cause
dataloss, since we don't have a good copy of the data anymore, so in
this case waiting for the sync to complete is not an option. As such,
it is recommended that this feature is used only in conjunction with
proper disk monitoring.


Live migration note: While failover-to-any is possible for all choices
of S2, migration-to-any is possible only if we keep P1 as S2.

Caveats
+++++++

The dynamic device model, while more complex, has an advantage: it
will not reuse by mistake another's instance DRBD device, since it
always looks for either our own or a free one.

The static one, in contrast, will assume that given a minor number N,
it's ours and we can take over. This needs careful implementation such
that if the minor is in use, either we are able to cleanly shut it
down, or we abort the startup. Otherwise, it could be that we start
syncing between two instance's disks, causing dataloss.


Variable number of disk/NICs per instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Variable number of disks
++++++++++++++++++++++++

In order to support high-security scenarios (for example read-only sda
and read-write sdb), we need to make a fully flexibly disk
definition. This has less impact that it might look at first sight:
only the instance creation has hardcoded number of disks, not the disk
handling code. The block device handling and most of the instance
handling code is already working with "the instance's disks" as
opposed to "the two disks of the instance", but some pieces are not
(e.g. import/export) and the code needs a review to ensure safety.

The objective is to be able to specify the number of disks at
instance creation, and to be able to toggle from read-only to
read-write a disk afterwards.

Variable number of NICs
+++++++++++++++++++++++

Similar to the disk change, we need to allow multiple network
interfaces per instance. This will affect the internal code (some
function will have to stop assuming that ``instance.nics`` is a list
of length one), the OS api which currently can export/import only one
instance, and the command line interface.

Interface changes
-----------------

There are two areas of interface changes: API-level changes (the OS
interface and the RAPI interface) and the command line interface
changes.

OS interface
~~~~~~~~~~~~

The current Ganeti OS interface, version 5, is tailored for Ganeti 1.2. The
interface is composed by a series of scripts which get called with certain
parameters to perform OS-dependent operations on the cluster. The current
scripts are:

create
  called when a new instance is added to the cluster
export
  called to export an instance disk to a stream
import
  called to import from a stream to a new instance
rename
  called to perform the os-specific operations necessary for renaming an
  instance

Currently these scripts suffer from the limitations of Ganeti 1.2: for example
they accept exactly one block and one swap devices to operate on, rather than
any amount of generic block devices, they blindly assume that an instance will
have just one network interface to operate, they can not be configured to
optimise the instance for a particular hypervisor.

Since in Ganeti 2.0 we want to support multiple hypervisors, and a non-fixed
number of network and disks the OS interface need to change to transmit the
appropriate amount of information about an instance to its managing operating
system, when operating on it. Moreover since some old assumptions usually used
in OS scripts are no longer valid we need to re-establish a common knowledge on
what can be assumed and what cannot be regarding Ganeti environment.


When designing the new OS API our priorities are:
- ease of use
- future extensibility
- ease of porting from the old api
- modularity

As such we want to limit the number of scripts that must be written to support
an OS, and make it easy to share code between them by uniforming their input.
We also will leave the current script structure unchanged, as far as we can,
and make a few of the scripts (import, export and rename) optional. Most
information will be passed to the script through environment variables, for
ease of access and at the same time ease of using only the information a script
needs.


The Scripts
+++++++++++

As in Ganeti 1.2, every OS which wants to be installed in Ganeti needs to
support the following functionality, through scripts:

create:
  used to create a new instance running that OS. This script should prepare the
  block devices, and install them so that the new OS can boot under the
  specified hypervisor.
export (optional):
  used to export an installed instance using the given OS to a format which can
  be used to import it back into a new instance.
import (optional):
  used to import an exported instance into a new one. This script is similar to
  create, but the new instance should have the content of the export, rather
  than contain a pristine installation.
rename (optional):
  used to perform the internal OS-specific operations needed to rename an
  instance.

If any optional script is not implemented Ganeti will refuse to perform the
given operation on instances using the non-implementing OS. Of course the
create script is mandatory, and it doesn't make sense to support the either the
export or the import operation but not both.

Incompatibilities with 1.2
__________________________

We expect the following incompatibilities between the OS scripts for 1.2 and
the ones for 2.0:

- Input parameters: in 1.2 those were passed on the command line, in 2.0 we'll
  use environment variables, as there will be a lot more information and not
  all OSes may care about all of it.
- Number of calls: export scripts will be called once for each device the
  instance has, and import scripts once for every exported disk. Imported
  instances will be forced to have a number of disks greater or equal to the
  one of the export.
- Some scripts are not compulsory: if such a script is missing the relevant
  operations will be forbidden for instances of that os. This makes it easier
  to distinguish between unsupported operations and no-op ones (if any).


Input
_____

Rather than using command line flags, as they do now, scripts will accept
inputs from environment variables.  We expect the following input values:

OS_API_VERSION
  The version of the OS api that the following parameters comply with;
  this is used so that in the future we could have OSes supporting
  multiple versions and thus Ganeti send the proper version in this
  parameter
INSTANCE_NAME
  Name of the instance acted on
HYPERVISOR
  The hypervisor the instance should run on (eg. 'xen-pvm', 'xen-hvm', 'kvm')
DISK_COUNT
  The number of disks this instance will have
NIC_COUNT
  The number of nics this instance will have
DISK_<N>_PATH
  Path to the Nth disk.
DISK_<N>_ACCESS
  W if read/write, R if read only. OS scripts are not supposed to touch
  read-only disks, but will be passed them to know.
DISK_<N>_FRONTEND_TYPE
  Type of the disk as seen by the instance. Can be 'scsi', 'ide', 'virtio'
DISK_<N>_BACKEND_TYPE
  Type of the disk as seen from the node. Can be 'block', 'file:loop' or
  'file:blktap'
NIC_<N>_MAC
  Mac address for the Nth network interface
NIC_<N>_IP
  Ip address for the Nth network interface, if available
NIC_<N>_BRIDGE
  Node bridge the Nth network interface will be connected to
NIC_<N>_FRONTEND_TYPE
  Type of the Nth nic as seen by the instance. For example 'virtio', 'rtl8139', etc.
DEBUG_LEVEL
  Whether more out should be produced, for debugging purposes. Currently the
  only valid values are 0 and 1.

These are only the basic variables we are thinking of now, but more may come
during the implementation and they will be documented in the ganeti-os-api man
page. All these variables will be available to all scripts.

Some scripts will need a few more information to work. These will have
per-script variables, such as for example:

OLD_INSTANCE_NAME
  rename: the name the instance should be renamed from.
EXPORT_DEVICE
  export: device to be exported, a snapshot of the actual device. The data must be exported to stdout.
EXPORT_INDEX
  export: sequential number of the instance device targeted.
IMPORT_DEVICE
  import: device to send the data to, part of the new instance. The data must be imported from stdin.
IMPORT_INDEX
  import: sequential number of the instance device targeted.

(Rationale for INSTANCE_NAME as an environment variable: the instance name is
always needed and we could pass it on the command line. On the other hand,
though, this would force scripts to both access the environment and parse the
command line, so we'll move it for uniformity.)


Output/Behaviour
________________

As discussed scripts should only send user-targeted information to stderr. The
create and import scripts are supposed to format/initialise the given block
devices and install the correct instance data. The export script is supposed to
export instance data to stdout in a format understandable by the the import
script. The data will be compressed by ganeti, so no compression should be
done. The rename script should only modify the instance's knowledge of what
its name is.

Other declarative style features
++++++++++++++++++++++++++++++++

Similar to Ganeti 1.2, OS specifications will need to provide a
'ganeti_api_version' containing list of numbers matching the version(s) of the
api they implement. Ganeti itself will always be compatible with one version of
the API and may maintain retrocompatibility if it's feasible to do so. The
numbers are one-per-line, so an OS supporting both version 5 and version 20
will have a file containing two lines. This is different from Ganeti 1.2, which
only supported one version number.

In addition to that an OS will be able to declare that it does support only a
subset of the ganeti hypervisors, by declaring them in the 'hypervisors' file.


Caveats/Notes
+++++++++++++

We might want to have a "default" import/export behaviour that just dumps all
disks and restores them. This can save work as most systems will just do this,
while allowing flexibility for different systems.

Environment variables are limited in size, but we expect that there will be
enough space to store the information we need. If we discover that this is not
the case we may want to go to a more complex API such as storing those
information on the filesystem and providing the OS script with the path to a
file where they are encoded in some format.



Remote API changes
~~~~~~~~~~~~~~~~~~

The first Ganeti RAPI was designed and deployed with the Ganeti 1.2.5 release.
That version provide Read-Only access to a cluster state. Fully functional
read-write API demand significant internal changes which are in a pipeline for
Ganeti 2.0 release.

We decided to go with implementing the Ganeti RAPI in a RESTful way, which is
aligned with key features we looking. It is simple, stateless, scalable and
extensible paradigm of API implementation. As transport it uses HTTP over SSL,
and we are implementing it in JSON encoding, but in a way it possible to extend
and provide any other one.

Design
++++++

The Ganeti API implemented as independent daemon, running on the same node
with the same permission level as Ganeti master daemon. Communication done
through unix socket protocol provided by Ganeti luxi library.
In order to keep communication asynchronous RAPI process two types of client
requests:

- queries: sever able to answer immediately
- jobs: some time needed.

In the query case requested data send back to client in http body. Typical
examples of queries would be list of nodes, instances, cluster info, etc.
Dealing with jobs client instead of waiting until job completes receive a job
id, the identifier which allows to query the job progress in the job queue.
(See job queue design doc for details)

Internally, each exported object has an version identifier, which is used as a
state stamp in the http header E-Tag field for request/response to avoid a race
condition.


Resource representation
+++++++++++++++++++++++

The key difference of REST approach from others API is instead having one URI
for all our requests, REST demand separate service by resources with unique
URI. Each of them should have limited amount of stateless and standard HTTP
methods: GET, POST, DELETE, PUT.

For example in Ganeti case we can have a set of URI:
 - /{clustername}/instances
 - /{clustername}/instances/{instancename}
 - /{clustername}/instances/{instancename}/tag
 - /{clustername}/tag

A GET request to /{clustername}/instances will return list of instances, a POST
to /{clustername}/instances should create new instance, a DELETE
/{clustername}/instances/{instancename} should delete instance, a GET
/{clustername}/tag get cluster tag

Each resource URI has a version prefix. The complete list of resources id TBD.

Internal encoding might be JSON, XML, or any other. The JSON encoding fits
nicely in Ganeti RAPI needs. Specific representation client can request with
Accept field in the HTTP header.

The REST uses standard HTTP as application protocol (not just as a transport)
for resources access. Set of possible result codes is a subset of standard HTTP
results. The stateless provide additional reliability and transparency to
operations.


Security
++++++++

With the write functionality security becomes much bigger an issue.  The Ganeti
RAPI uses basic HTTP authentication on top of SSL connection to grant access to
an exported resource. The password stores locally in Apache-style .htpasswd
file. Only one level of privileges is supported.


Command line changes
~~~~~~~~~~~~~~~~~~~~

Ganeti 2.0 introduces several new features as well as new ways to
handle instance resources like disks or network interfaces. This
requires some noticable changes in the way commandline arguments are
handled.

- extend and modify commandline syntax to support new features
- ensure consistent patterns in commandline arguments to reduce cognitive load

The design changes that require these changes are, in no particular
order:

- flexible instance disk handling: support a variable number of disks
  with varying properties per instance,
- flexible instance network interface handling: support a variable
  number of network interfaces with varying properties per instance
- multiple hypervisors: multiple hypervisors can be active on the same
  cluster, each supporting different parameters,
- support for device type CDROM (via ISO image)

As such, there are several areas of Ganeti where the commandline
arguments will change:

- Cluster configuration

  - cluster initialization
  - cluster default configuration

- Instance configuration

  - handling of network cards for instances,
  - handling of disks for instances,
  - handling of CDROM devices and
  - handling of hypervisor specific options.

There are several areas of Ganeti where the commandline arguments will change:

- Cluster configuration

  - cluster initialization
  - cluster default configuration

- Instance configuration

  - handling of network cards for instances,
  - handling of disks for instances,
  - handling of CDROM devices and
  - handling of hypervisor specific options.

Notes about device removal/addition
+++++++++++++++++++++++++++++++++++

To avoid problems with device location changes (e.g. second network
interface of the instance becoming the first or third and the like)
the list of network/disk devices is treated as a stack, i.e. devices
can only be added/removed at the end of the list of devices of each
class (disk or network) for each instance.

gnt-instance commands
+++++++++++++++++++++

The commands for gnt-instance will be modified and extended to allow
for the new functionality:

- the add command will be extended to support the new device and
  hypervisor options,
- the modify command continues to handle all modifications to
  instances, but will be extended with new arguments for handling
  devices.

Network Device Options
++++++++++++++++++++++

The generic format of the network device option is:

  --net $DEVNUM[:$OPTION=$VALUE][,$OPTION=VALUE]

:$DEVNUM: device number, unsigned integer, starting at 0,
:$OPTION: device option, string,
:$VALUE: device option value, string.

Currently, the following device options will be defined (open to
further changes):

:mac: MAC address of the network interface, accepts either a valid
  MAC address or the string 'auto'. If 'auto' is specified, a new MAC
  address will be generated randomly. If the mac device option is not
  specified, the default value 'auto' is assumed.
:bridge: network bridge the network interface is connected
  to. Accepts either a valid bridge name (the specified bridge must
  exist on the node(s)) as string or the string 'auto'. If 'auto' is
  specified, the default brigde is used. If the bridge option is not
  specified, the default value 'auto' is assumed.

Disk Device Options
+++++++++++++++++++

The generic format of the disk device option is:

  --disk $DEVNUM[:$OPTION=$VALUE][,$OPTION=VALUE]

:$DEVNUM: device number, unsigned integer, starting at 0,
:$OPTION: device option, string,
:$VALUE: device option value, string.

Currently, the following device options will be defined (open to
further changes):

:size: size of the disk device, either a positive number, specifying
  the disk size in mebibytes, or a number followed by a magnitude suffix
  (M for mebibytes, G for gibibytes). Also accepts the string 'auto' in
  which case the default disk size will be used. If the size option is
  not specified, 'auto' is assumed. This option is not valid for all
  disk layout types.
:access: access mode of the disk device, a single letter, valid values
  are:

  - *w*: read/write access to the disk device or
  - *r*: read-only access to the disk device.

  If the access mode is not specified, the default mode of read/write
  access will be configured.
:path: path to the image file for the disk device, string. No default
  exists. This option is not valid for all disk layout types.

Adding devices
++++++++++++++

To add devices to an already existing instance, use the device type
specific option to gnt-instance modify. Currently, there are two
device type specific options supported:

:--net: for network interface cards
:--disk: for disk devices

The syntax to the device specific options is similiar to the generic
device options, but instead of specifying a device number like for
gnt-instance add, you specify the magic string add. The new device
will always be appended at the end of the list of devices of this type
for the specified instance, e.g. if the instance has disk devices 0,1
and 2, the newly added disk device will be disk device 3.

Example: gnt-instance modify --net add:mac=auto test-instance

Removing devices
++++++++++++++++

Removing devices from and instance is done via gnt-instance
modify. The same device specific options as for adding instances are
used. Instead of a device number and further device options, only the
magic string remove is specified. It will always remove the last
device in the list of devices of this type for the instance specified,
e.g. if the instance has disk devices 0, 1, 2 and 3, the disk device
number 3 will be removed.

Example: gnt-instance modify --net remove test-instance

Modifying devices
+++++++++++++++++

Modifying devices is also done with device type specific options to
the gnt-instance modify command. There are currently two device type
options supported:

:--net: for network interface cards
:--disk: for disk devices

The syntax to the device specific options is similiar to the generic
device options. The device number you specify identifies the device to
be modified.

Example: gnt-instance modify --disk 2:access=r

Hypervisor Options
++++++++++++++++++

Ganeti 2.0 will support more than one hypervisor. Different
hypervisors have various options that only apply to a specific
hypervisor. Those hypervisor specific options are treated specially
via the --hypervisor option. The generic syntax of the hypervisor
option is as follows:

  --hypervisor $HYPERVISOR:$OPTION=$VALUE[,$OPTION=$VALUE]

:$HYPERVISOR: symbolic name of the hypervisor to use, string,
  has to match the supported hypervisors. Example: xen-pvm

:$OPTION: hypervisor option name, string
:$VALUE: hypervisor option value, string

The hypervisor option for an instance can be set on instance creation
time via the gnt-instance add command. If the hypervisor for an
instance is not specified upon instance creation, the default
hypervisor will be used.

Modifying hypervisor parameters
+++++++++++++++++++++++++++++++

The hypervisor parameters of an existing instance can be modified
using --hypervisor option of the gnt-instance modify command. However,
the hypervisor type of an existing instance can not be changed, only
the particular hypervisor specific option can be changed. Therefore,
the format of the option parameters has been simplified to omit the
hypervisor name and only contain the comma separated list of
option-value pairs.

Example: gnt-instance modify --hypervisor
cdrom=/srv/boot.iso,boot_order=cdrom:network test-instance

gnt-cluster commands
++++++++++++++++++++

The command for gnt-cluster will be extended to allow setting and
changing the default parameters of the cluster:

- The init command will be extend to support the defaults option to
  set the cluster defaults upon cluster initialization.
- The modify command will be added to modify the cluster
  parameters. It will support the --defaults option to change the
  cluster defaults.

Cluster defaults

The generic format of the cluster default setting option is:

  --defaults $OPTION=$VALUE[,$OPTION=$VALUE]

:$OPTION: cluster default option, string,
:$VALUE: cluster default option value, string.

Currently, the following cluster default options are defined (open to
further changes):

:hypervisor: the default hypervisor to use for new instances,
  string. Must be a valid hypervisor known to and supported by the
  cluster.
:disksize: the disksize for newly created instance disks, where
  applicable. Must be either a positive number, in which case the unit
  of megabyte is assumed, or a positive number followed by a supported
  magnitude symbol (M for megabyte or G for gigabyte).
:bridge: the default network bridge to use for newly created instance
  network interfaces, string. Must be a valid bridge name of a bridge
  existing on the node(s).

Hypervisor cluster defaults
+++++++++++++++++++++++++++

The generic format of the hypervisor clusterwide default setting option is:

  --hypervisor-defaults $HYPERVISOR:$OPTION=$VALUE[,$OPTION=$VALUE]

:$HYPERVISOR: symbolic name of the hypervisor whose defaults you want
  to set, string
:$OPTION: cluster default option, string,
:$VALUE: cluster default option value, string.


Functionality changes
---------------------

The disk storage will receive some changes, and will also remove
support for the drbd7 and md disk types. See the
design-2.0-disk-changes document.

The configuration storage will be changed, with the effect that more
data will be available on the nodes for access from outside ganeti
(e.g. from shell scripts) and that nodes will get slightly more
awareness of the cluster configuration.

The RAPI will enable modify operations (beside the read-only queries
that are available today), so in effect almost all the operations
available today via the ``gnt-*`` commands will be available via the
remote API.

A change in the hypervisor support area will be that we will support
multiple hypervisors in parallel in the same cluster, so one could run
Xen HVM side-by-side with Xen PVM on the same cluster.

New features
------------

There will be a number of minor feature enhancements targeted to
either 2.0 or subsequent 2.x releases:

- multiple disks, with custom properties (read-only/read-write, exportable,
  etc.)
- multiple NICs

These changes will require OS API changes, details are in the
design-2.0-os-interface document. And they will also require many
command line changes, see the design-2.0-commandline-parameters
document.
