========================================
Automatized Upgrade Procedure for Ganeti
========================================

.. contents:: :depth: 4

This is a design document detailing the proposed changes to the
upgrade process, in order to allow it to be more automatic.


Current state and shortcomings
==============================

Ganeti requires to run the same version of Ganeti to be run on all
nodes of a cluster and this requirement is unlikely to go away in the
foreseeable future. Also, the configuration may change between minor
versions (and in the past has proven to do so). This requires a quite
involved manual upgrade process of draining the queue, stopping
ganeti, changing the binaries, upgrading the configuration, starting
ganeti, distributing the configuration, and undraining the queue.


Proposed changes
================

While we will not remove the requirement of the same Ganeti
version running on all nodes, the transition from one version
to the other will be made more automatic. It will be possible
to install new binaries ahead of time, and the actual switch
between versions will be a single command.

While changing the file layout anyway, we install the python
code, which is architecture independent, under ``${prefix}/share``,
in a way that properly separates the Ganeti libraries of the
various versions. 

Path changes to allow multiple versions installed
-------------------------------------------------

Currently, Ganeti installs to ``${PREFIX}/bin``, ``${PREFIX}/sbin``,
and so on, as well as to ``${pythondir}/ganeti``.

These paths will be changed in the following way.

- The python package will be installed to
  ``${PREFIX}/share/ganeti/${VERSION}/ganeti``.
  Here ${VERSION} is, depending on configure options, either the full qualified
  version number, consisting of major, minor, revision, and suffix, or it is
  just a major.minor pair. All python executables will be installed under
  ``${PREFIX}/share/ganeti/${VERSION}`` so that they see their respective
  Ganeti library. ``${PREFIX}/share/ganeti/default`` is a symbolic link to
  ``${sysconfdir}/ganeti/share`` which, in turn, is a symbolic link to
  ``${PREFIX}/share/ganeti/${VERSION}``. For all python executatables (like
  ``gnt-cluster``, ``gnt-node``, etc) symbolic links going through
  ``${PREFIX}/share/ganeti/default`` are added under ``${PREFIX}/sbin``.

- All other files will be installed to the corresponding path under
  ``${libdir}/ganeti/${VERSION}`` instead of under ``${PREFIX}``
  directly, where ``${libdir}`` defaults to ``${PREFIX}/lib``.
  ``${libdir}/ganeti/default`` will be a symlink to ``${sysconfdir}/ganeti/lib``
  which, in turn, is a symlink to ``${libdir}/ganeti/${VERSION}``.
  Symbolic links to the files installed under ``${libdir}/ganeti/${VERSION}``
  will be added under ``${PREFIX}/bin``, ``${PREFIX}/sbin``, and so on. These
  symbolic links will go through ``${libdir}/ganeti/default`` so that the
  version can easily be changed by updating the symbolic link in
  ``${sysconfdir}``.

The set of links for ganeti binaries might change between the versions.
However, as the file structure under ``${libdir}/ganeti/${VERSION}`` reflects
that of ``/``, two links of differnt versions will never conflict. Similarly,
the symbolic links for the python executables will never conflict, as they
always point to a file with the same basename directly under
``${PREFIX}/share/ganeti/default``. Therefore, each version will make sure that
enough symbolic links are present in ``${PREFIX}/bin``, ``${PREFIX}/sbin`` and
so on, even though some might be dangling, if a differnt version of ganeti is
currently active.

The extra indirection through ``${sysconfdir}`` allows installations that choose
to have ``${sysconfdir}`` and ``${localstatedir}`` outside ``${PREFIX}`` to
mount ``${PREFIX}`` read-only. The latter is important for systems that choose
``/usr`` as ``${PREFIX}`` and are following the Filesystem Hierarchy Standard.
For example, choosing ``/usr`` as ``${PREFIX}`` and ``/etc`` as ``${sysconfdir}``,
the layout for version 2.10 will look as follows.
::

   /
   |
   +-- etc
   |   |
   |   +-- ganeti 
   |         |
   |         +-- lib -> /usr/lib/ganeti/2.10
   |         |
   |         +-- share  -> /usr/share/ganeti/2.10
   +-- usr
        |
        +-- bin
        |   |
        |   +-- harep -> /usr/lib/ganeti/default/usr/bin/harep
        |   |
        |   ...  
        |
        +-- sbin
        |   |
        |   +-- gnt-cluster -> /usr/share/ganeti/default/gnt-cluster
        |   |
        |   ...  
        |
        +-- ...
        |
        +-- lib
        |   |
        |   +-- ganeti
        |       |
        |       +-- default -> /etc/ganeti/lib
        |       |
        |       +-- 2.10
        |           |
        |           +-- usr
        |               |
        |               +-- bin
        |               |    |
        |               |    +-- htools
        |               |    |
        |               |    +-- harep -> htools
        |               |    |
        |               |    ...
        |               ...
        |
        +-- share
             |
             +-- ganeti
                 |
                 +-- default -> /etc/ganeti/share
                 |
                 +-- 2.10
                     |
                     + -- gnt-cluster
                     |
                     + -- gnt-node
                     |
                     + -- ...
                     |
                     + -- ganeti
                          |
                          +-- backend.py
                          |
                          +-- ...
                          |
                          +-- cmdlib
                          |   |
                          |   ...
                          ...



gnt-cluster upgrade
-------------------

The actual upgrade process will be done by a new command ``upgrade`` to
``gnt-cluster``. If called with the option ``--to`` which take precisely
one argument, the version to
upgrade (or downgrade) to, given as full string with major, minor, revision,
and suffix. To be compatible with current configuration upgrade and downgrade
procedures, the new version must be of the same major version and
either an equal or higher minor version, or precisely the previous
minor version.

When executed, ``gnt-cluster upgrade --to=<version>`` will perform the
following actions.

- It verifies that the version to change to is installed on all nodes
  of the cluster that are not marked as offline. If this is not the
  case it aborts with an error. This initial testing is an
  optimization to allow for early feedback.

- An intent-to-upgrade file is created that contains the current
  version of ganeti, the version to change to, and the process ID of
  the ``gnt-cluster upgrade`` process. The latter is not used automatically,
  but allows manual detection if the upgrade process died
  unintentionally. The intend-to-upgrade file is persisted to disk
  before continuing.

- The Ganeti job queue is drained, and the executable waits till there
  are no more jobs in the queue. Once :doc:`design-optables` is
  implemented, for upgrades, and only for upgrades, all jobs are paused
  instead (in the sense that the currently running opcode continues,
  but the next opcode is not started) and it is continued once all
  jobs are fully paused.

- All ganeti daemons on the master node are stopped.

- It is verified again that all nodes at this moment not marked as
  offline have the new version installed. If this is not the case,
  then all changes so far (stopping ganeti daemons and draining the
  queue) are undone and failure is reported. This second verification
  is necessary, as the set of online nodes might have changed during
  the draining period.

- All ganeti daemons on all remaining (non-offline) nodes are stopped.

- A backup of all Ganeti-related status information is created for
  manual rollbacks. While the normal way of rolling back after an
  upgrade should be calling ``gnt-clsuter upgrade`` from the newer version
  with the older version as argument, a full backup provides an
  additional safety net, especially for jump-upgrades (skipping
  intermediate minor versions).

- If the action is a downgrade to the previous minor version, the
  configuration is downgraded now, using ``cfgupgrade --downgrade``.

- If the action is downgrade, any version-specific additional downgrade
  actions are carried out.

- The ``${sysconfdir}/ganeti/lib`` and ``${sysconfdir}/ganeti/share``
  symbolic links are updated.

- If the action is an upgrade to a higher minor version, the configuration
  is upgraded now, using ``cfgupgrade``.

- ``ensure-dirs --full-run`` is run on all nodes.

- All daemons are started on all nodes.

- ``gnt-cluster redist-conf`` is run on the master node. 

- All daemons are restarted on all nodes.

- The Ganeti job queue is undrained.

- The intent-to-upgrade file is removed.

- ``post-upgrade`` is run with the original version as argument.

- ``gnt-cluster verify`` is run and the result reported.


Considerations on unintended reboots of the master node
=======================================================
 
During the upgrade procedure, the only ganeti process still running is
the one instance of ``gnt-cluster upgrade``. This process is also responsible
for eventually removing the queue drain. Therefore, we have to provide
means to resume this process, if it dies unintentionally. The process
itself will handle SIGTERM gracefully by either undoing all changes
done so far, or by ignoring the signal all together and continuing to
the end; the choice between these behaviors depends on whether change
of the configuration has already started (in which case it goes
through to the end), or not (in which case the actions done so far are
rolled back).

To achieve this, ``gnt-cluster upgrade`` will support a ``--resume``
option. It is recommended
to have ``gnt-cluster upgrade --resume`` as an at-reboot task in the crontab.
The ``gnt-cluster upgrade --resume`` comand first verifies that
it is running on the master node, using the same requirement as for
starting the master daemon, i.e., confirmed by a majority of all
nodes. If it is not the master node, it will remove any possibly
existing intend-to-upgrade file and exit. If it is running on the
master node, it will check for the existence of an intend-to-upgrade
file. If no such file is found, it will simply exit. If found, it will
resume at the appropriate stage.

- If the configuration file still is at the initial version,
  ``gnt-cluster upgrade`` is resumed at the step immediately following the
  writing of the intend-to-upgrade file. It should be noted that
  all steps before changing the configuration are idempotent, so
  redoing them does not do any harm.

- If the configuration is already at the new version, all daemons on
  all nodes are stopped (as they might have been started again due
  to a reboot) and then it is resumed at the step immediately
  following the configuration change. All actions following the
  configuration change can be repeated without bringing the cluster
  into a worse state.


Caveats
=======

Since ``gnt-cluster upgrade`` drains the queue and undrains it later, so any
information about a previous drain gets lost. This problem will
disappear, once :doc:`design-optables` is implemented, as then the
undrain will then be restricted to filters by gnt-upgrade.


Requirement of job queue update
===============================

Since for upgrades we only pause jobs and do not fully drain the
queue, we need to be able to transform the job queue into a queue for
the new version. The preferred way to obtain this is to keep the
serialization format backwards compatible, i.e., only adding new
opcodes and new optional fields.

However, even with soft drain, no job is running at the moment `cfgupgrade`
is running. So, if we change the queue representation, including the
representation of individual opcodes in any way, `cfgupgrade` will also
modify the queue accordingly. In a jobs-as-processes world, pausing a job
will be implemented in such a way that the corresponding process stops after
finishing the current opcode, and a new process is created if and when the
job is unpaused again.
