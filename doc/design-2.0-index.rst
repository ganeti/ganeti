Ganeti 2.0 design documents
===========================


The 2.x versions of Ganeti will constitute a rewrite of the 'core'
architecture, plus some additional features (however 2.0 is geared
toward the core changes).

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
