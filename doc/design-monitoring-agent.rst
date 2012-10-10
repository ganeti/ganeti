=======================
Ganeti monitoring agent
=======================

.. contents:: :depth: 4

This is a design document detailing the implementation of a Ganeti
monitoring agent report system, that can be queried by a monitoring
system to calculate health information for a Ganeti cluster.

Current state and shortcomings
==============================

There is currently no monitoring support in Ganeti. While we don't want
to build something like Nagios or Pacemaker as part of Ganeti, it would
be useful if such tools could easily extract information from a Ganeti
machine in order to take actions (example actions include logging an
outage for future reporting or alerting a person or system about it).

Proposed changes
================

Each Ganeti node should export a status page that can be queried by a
monitoring system. Such status page will be exported on a network port
and will be encoded in JSON (simple text) over HTTP.

The choice of json is obvious as we already depend on it in Ganeti and
thus we don't need to add extra libraries to use it, as opposed to what
would happen for XML or some other markup format.

Location of agent report
------------------------

The report will be available from all nodes, and be concerned for all
node-local resources. This allows more real-time information to be
available, at the cost of querying all nodes.

Information reported
--------------------

The monitoring agent system will report on the following basic information:

- Instance status
- Instance disk status
- Status of storage for instances
- Ganeti daemons status, CPU usage, memory footprint
- Hypervisor resources report (memory, CPU, network interfaces)
- Node OS resources report (memory, CPU, network interfaces)
- Information from a plugin system

Instance status
+++++++++++++++

At the moment each node knows which instances are running on it, which
instances it is primary for, but not the cause why an instance might not
be running. On the other hand we don't want to distribute full instance
"admin" status information to all nodes, because of the performance
impact this would have.

As such we propose that:

- Any operation that can affect instance status will have an optional
  "reason" attached to it (at opcode level). This can be used for
  example to distinguish an admin request, from a scheduled maintenance
  or an automated tool's work. If this reason is not passed, Ganeti will
  just use the information it has about the source of the request: for
  example a cli shutdown operation will have "cli:shutdown" as a reason,
  a cli failover operation will have "cli:failover". Operations coming
  from the remote API will use "rapi" instead of "cli". Of course
  setting a real site-specific reason is still preferred.
- RPCs that affect the instance status will be changed so that the
  "reason" and the version of the config object they ran on is passed to
  them. They will then export the new expected instance status, together
  with the associated reason and object version to the status report
  system, which then will export those themselves.

Monitoring and auditing systems can then use the reason to understand
the cause of an instance status, and they can use the object version to
understand the freshness of their data even in the absence of an atomic
cross-node reporting: for example if they see an instance "up" on a node
after seeing it running on a previous one, they can compare these values
to understand which data is freshest, and repoll the "older" node. Of
course if they keep seeing this status this represents an error (either
an instance continuously "flapping" between nodes, or an instance is
constantly up on more than one), which should be reported and acted
upon.

The instance status will be on each node, for the instances it is
primary for and will contain at least:

- The instance name
- The instance UUID (stable on name change)
- The instance running status (up or down)
- The timestamp of last known change
- The timestamp of when the status was last checked (see caching, below)
- The last known reason for change, if any

More information about all the fields and their type will be available
in the "Format of the report" section.

Note that as soon as a node knows it's not the primary anymore for an
instance it will stop reporting status for it: this means the instance
will either disappear, if it has been deleted, or appear on another
node, if it's been moved.

Instance Disk status
++++++++++++++++++++

As for the instance status Ganeti has now only partial information about
its instance disks: in particular each node is unaware of the disk to
instance mapping, that exists only on the master.

For this design doc we plan to fix this by changing all RPCs that create
a backend storage or that put an already existing one in use and passing
the relevant instance to the node. The node can then export these to the
status reporting tool.

While we haven't implemented these RPC changes yet, we'll use confd to
fetch this information in the data collector.

Since Ganeti supports many type of disks for instances (drbd, rbd,
plain, file) we will export both a "generic" status which will work for
any type of disk and will be very opaque (at minimum just an "healthy"
or "error" state, plus perhaps some human readable comment and a
"per-type" status which will explain more about the internal details but
will not be compatible between different storage types (and will for
example export the drbd connection status, sync, and so on).

Status of storage for instances
+++++++++++++++++++++++++++++++

The node will also be reporting on all storage types it knows about for
the current node (this is right now hardcoded to the enabled storage
types, and in the future tied to the enabled storage pools for the
nodegroup). For this kind of information also we will report both a
generic health status (healthy or error) for each type of storage, and
some more generic statistics (free space, used space, total visible
space). In addition type specific information can be exported: for
example, in case of error, the nature of the error can be disclosed as a
type specific information. Examples of these are "backend pv
unavailable" for lvm storage, "unreachable" for network based storage or
"filesystem error" for filesystem based implementations.

Ganeti daemons status
+++++++++++++++++++++

Ganeti will report what information it has about its own daemons: this
includes memory usage, uptime, CPU usage. This should allow identifying
possible problems with the Ganeti system itself: for example memory
leaks, crashes and high resource utilization should be evident by
analyzing this information.

Ganeti daemons will also be able to export extra internal information to
the status reporting, through the plugin system (see below).

Hypervisor resources report
+++++++++++++++++++++++++++

Each hypervisor has a view of system resources that sometimes is
different than the one the OS sees (for example in Xen the Node OS,
running as Dom0, has access to only part of those resources). In this
section we'll report all information we can in a "non hypervisor
specific" way. Each hypervisor can then add extra specific information
that is not generic enough be abstracted.

Node OS resources report
++++++++++++++++++++++++

Since Ganeti assumes it's running on Linux, it's useful to export some
basic information as seen by the host system. This includes number and
status of CPUs, memory, filesystems and network intefaces as well as the
version of components Ganeti interacts with (Linux, drbd, hypervisor,
etc).

Note that we won't go into any hardware specific details (e.g. querying a
node RAID is outside the scope of this, and can be implemented as a
plugin) but we can easily just report the information above, since it's
standard enough across all systems.

Plugin system
+++++++++++++

The monitoring system will be equipped with a plugin system that can
export specific local information through it. The plugin system will be
in the form of either scripts whose output will be inserted in the
report, plain text files which will be inserted into the report, or
local unix or network sockets from which the information has to be read.
This should allow most flexibility for implementing an efficient system,
while being able to keep it as simple as possible.

The plugin system is expected to be used by local installations to
export any installation specific information that they want to be
monitored, about either hardware or software on their systems.


Format of the query
-------------------

The query will be an HTTP GET request on a particular port. At the
beginning it will only be possible to query the full status report.


Format of the report
--------------------

TBD (this part needs to be completed with the format of the JSON and the
types of the various variables exported, as they get evaluated and
decided)


Data collectors
---------------

In order to ease testing as well as to make it simple to reuse this
subsystem it will be possible to run just the "data collectors" on each
node without passing through the agent daemon. Each data collector will
report specific data about its subsystem and will be documented
separately.


Mode of operation
-----------------

In order to be able to report information fast the monitoring agent
daemon will keep an in-memory or on-disk cache of the status, which will
be returned when queries are made. The status system will then
periodically check resources to make sure the status is up to date.

Different parts of the report will be queried at different speeds. These
will depend on:
- how often they vary (or we expect them to vary)
- how fast they are to query
- how important their freshness is

Of course the last parameter is installation specific, and while we'll
try to have defaults, it will be configurable. The first two instead we
can use adaptively to query a certain resource faster or slower
depending on those two parameters.


Implementation place
--------------------

The status daemon will be implemented as a standalone Haskell daemon. In
the future it should be easy to merge multiple daemons into one with
multiple entry points, should we find out it saves resources and doesn't
impact functionality.

The libekg library should be looked at for easily providing metrics in
json format.


Implementation order
--------------------

We will implement the agent system in this order:

- initial example data collectors (eg. for drbd and instance status)
- initial daemon for exporting data
- RPC updates for instance status reasons and disk to instance mapping
- more data collectors
- cache layer for the daemon (if needed)


Future work
===========

As a future step it can be useful to "centralize" all this reporting
data on a single place. This for example can be just the master node, or
all the master candidates. We will evaluate doing this after the first
node-local version has been developed and tested.

Another possible change is replacing the "read-only" RPCs with queries
to the agent system, thus having only one way of collecting information
from the nodes from a monitoring system and for Ganeti itself.

One extra feature we may need is a way to query for only sub-parts of
the report (eg. instances status only). This can be done by passing
arguments to the HTTP GET, which will be defined when we get to this
funtionality.

Finally the :doc:`autorepair system design <design-autorepair>`. system
(see its design) can be expanded to use the monitoring agent system as a
source of information to decide which repairs it can perform.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
