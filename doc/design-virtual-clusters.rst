===================================
Design for virtual clusters support
===================================


Introduction
============

Currently there are two ways to test the Ganeti (including HTools) code
base:

- unittests, which run using mocks as normal user and test small bits of
  the code
- QA/burnin/live-test, which require actual hardware (either physical or
  virtual) and will build an actual cluster, with one machine to one
  node correspondence

The difference in time between these two is significant:

- the unittests run in about 1-2 minutes
- a so-called ‘quick’ QA (without burnin) runs in about an hour, and a
  full QA could be double that time

On one hand, the unittests have a clear advantage: quick to run, not
requiring many machines, but on the other hand QA is actually able to
run end-to-end tests (including HTools, for example).

Ideally, we would have an intermediate step between these two extremes:
be able to test most, if not all, of Ganeti's functionality but without
requiring actual hardware, full machine ownership or root access.


Current situation
=================

Ganeti
------

It is possible, given a manually built ``config.data`` and
``_autoconf.py``, to run the masterd under the current user as a
single-node cluster master. However, the node daemon and related
functionality (cluster initialisation, master failover, etc.) are not
directly runnable in this model.

Also, masterd only works as a master of a single node cluster, due to
our current “hostname” method of identifying nodes, which results in a
limit of maximum one node daemon per machine, unless we use multiple
name and IP aliases.

HTools
------

In HTools the situation is better, since it doesn't have to deal with
actual machine management: all tools can use a custom LUXI path, and can
even load RAPI data from the filesystem (so the RAPI backend can be
tested), and both the ‘text’ backend for hbal/hspace and the input files
for hail are text-based, loaded from the file-system.

Proposed changes
================

The end-goal is to have full support for “virtual clusters”, i.e. be
able to run a “big” (hundreds of virtual nodes and towards thousands of
virtual instances) on a reasonably powerful, but single machine, under a
single user account and without any special privileges.

This would have significant advantages:

- being able to test end-to-end certain changes, without requiring a
  complicated setup
- better able to estimate Ganeti's behaviour and performance as the
  cluster size grows; this is something that we haven't been able to
  test reliably yet, and as such we still have not yet diagnosed
  scaling problems
- easier integration with external tools (and even with HTools)

``masterd``
-----------

As described above, ``masterd`` already works reasonably well in a
virtual setup, as it won't execute external programs and it shouldn't
directly read files from the local filesystem (or at least not
virtualisation-related, as the master node can be a non-vm_capable
node).

``noded``
---------

The node daemon executes many privileged operations, but they can be
split in a few general categories:

+---------------+-----------------------+------------------------------------+
|Category       |Description            |Solution                            |
+===============+=======================+====================================+
|disk operations|Disk creation and      |Use only diskless or file-based     |
|               |removal                |instances                           |
+---------------+-----------------------+------------------------------------+
|disk query     |Node disk total/free,  |Not supported currently, could use  |
|               |used in node listing   |file-based                          |
|               |and htools             |                                    |
+---------------+-----------------------+------------------------------------+
|hypervisor     |Instance start, stop   |Use the *fake* hypervisor           |
|operations     |and query              |                                    |
+---------------+-----------------------+------------------------------------+
|instance       |Bridge existence query |Unprivileged operation, can be used |
|networking     |                       |with an existing bridge at system   |
|               |                       |level or use NIC-less instances     |
+---------------+-----------------------+------------------------------------+
|instance OS    |OS add, OS rename,     |Only used with non-diskless         |
|operations     |export and import      |instances; could work with custom OS|
|               |                       |scripts that just ``dd`` without    |
|               |                       |mounting filesystems                |
+---------------+-----------------------+------------------------------------+
|node networking|IP address management  |Not supported; Ganeti will need to  |
|               |(master ip), IP query, |work without a master IP; for the IP|
|               |etc.                   |query operations the test machine   |
|               |                       |would need externally-configured IPs|
+---------------+-----------------------+------------------------------------+
|node add       |-                      |SSH command must be adjusted        |
+---------------+-----------------------+------------------------------------+
|node setup     |ssh, /etc/hosts, so on |Can already be disabled from the    |
|               |                       |cluster config                      |
+---------------+-----------------------+------------------------------------+
|master failover|start/stop the master  |Doable (as long as we use a single  |
|               |daemon                 |user), might get tricky w.r.t. paths|
|               |                       |to executables                      |
+---------------+-----------------------+------------------------------------+
|file upload    |Uploading of system    |The only issue could be with system |
|               |files, job queue files |files, which are not owned by the   |
|               |and ganeti config      |current user; internal ganeti files |
|               |                       |should be working fine              |
+---------------+-----------------------+------------------------------------+
|node oob       |Out-of-band commands   |Since these are user-defined, we can|
|               |                       |mock them easily                    |
+---------------+-----------------------+------------------------------------+
|node OS        |List the existing OSes |No special privileges needed, so    |
|discovery      |and their properties   |works fine as-is                    |
+---------------+-----------------------+------------------------------------+
|hooks          |Running hooks for given|No special privileges needed        |
|               |operations             |                                    |
+---------------+-----------------------+------------------------------------+
|iallocator     |Calling an iallocator  |No special privileges needed        |
|               |script                 |                                    |
+---------------+-----------------------+------------------------------------+
|export/import  |Exporting and importing|When exporting/importing file-based |
|               |instances              |instances, this should work, as the |
|               |                       |listening ports are dynamically     |
|               |                       |chosen                              |
+---------------+-----------------------+------------------------------------+
|hypervisor     |The validation of      |As long as the hypervisors don't    |
|validation     |hypervisor parameters  |call to privileged commands, it     |
|               |                       |should work                         |
+---------------+-----------------------+------------------------------------+
|node powercycle|The ability to power   |Privileged, so not supported, but   |
|               |cycle a node remotely  |anyway not very interesting for     |
|               |                       |testing                             |
+---------------+-----------------------+------------------------------------+

It seems that much of the functionality works as is, or could work with
small adjustments, even in a non-privileged setup. The bigger problem is
the actual use of multiple node daemons per machine.

Multiple ``noded`` per machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Currently Ganeti identifies node simply by their hostname. Since
changing this method would imply significant changes to tracking the
nodes, the proposal is to simply have as many IPs per the (single)
machine that is used for tests as nodes, and have each IP correspond to
a different name, and thus no changes are needed to the core RPC
library. Unfortunately this has the downside of requiring root rights
for setting up the extra IPs and hostnames.

An alternative option is to implement per-node IP/port support in Ganeti
(especially in the RPC layer), which would eliminate the root rights. We
expect that this will get implemented as a second step of this design,
but as the port is currently static will require changes in many places.

The only remaining problem is with sharing the ``localstatedir``
structure (lib, run, log) amongst the daemons, for which we propose to
introduce an environment variable (``GANETI_ROOTDIR``) acting as a
prefix for essentially all paths. An environment variable is easier to
transport through several levels of programs (shell scripts, Python,
etc.) than a command line parameter. In Python code this prefix will be
applied to all paths in ``constants.py``. Every virtual node will get
its own root directory. The rationale for this is two-fold:

- having two or more node daemons writing to the same directory might
  introduce artificial scenarios not existent in real life; currently
  noded either owns the entire ``/var/lib/ganeti`` directory or shares
  it with masterd, but never with another noded
- having separate directories allows cluster verify to check correctly
  consistency of file upload operations; otherwise, as long as one node
  daemon wrote a file successfully, the results from all others are
  “lost”

In case the use of an environment variable turns out to be too difficult
a compile-time prefix path could be used. This would then require one
Ganeti installation per virtual node, but it might be good enough.

``rapi``
--------

The RAPI daemon is not privileged and furthermore we only need one per
cluster, so it presents no issues.

``confd``
---------

``confd`` has somewhat the same issues as the node daemon regarding
multiple daemons per machine, but the per-address binding still works.

``ganeti-watcher``
------------------

Since the startup of daemons will be customised with per-IP binds, the
watcher either has to be modified to not activate the daemons, or the
start-stop tool has to take this into account. Due to watcher's use of
the hostname, it's recommended that the master node is set to the
machine hostname (also a requirement for the master daemon).

CLI scripts
-----------

As long as the master node is set to the machine hostname, these should
work fine.

Cluster initialisation
----------------------

It could be possible that the cluster initialisation procedure is a bit
more involved (this was not tried yet). A script will be used to set up
all necessary IP addresses and hostnames, as well as creating the
initial directory structure. Building ``config.data`` manually should
not be necessary.

Needed tools
============

With the above investigation results in mind, the only thing we need
are:

- a tool to setup per-virtual node tree structure of ``localstatedir``
  (with the help of ``ensure-dirs``) and setup correctly the extra
  IP/hostnames
- changes to the startup daemon tools to launch correctly the daemons
  per virtual node
- changes to ``constants.py`` to override the ``localstatedir`` path
- documentation for running such a virtual cluster
- and eventual small fixes to the node daemon backend functionality, to
  better separate privileged and non-privileged code

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
