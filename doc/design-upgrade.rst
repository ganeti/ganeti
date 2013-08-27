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

Path changes to allow multiple versions installed
-------------------------------------------------

Currently, Ganeti installs to ``${PREFIX}/bin``, ``${PREFIX}/sbin``,
and so on, as well as to ``${pythondir}/ganeti``.

These paths will be changed in the following way.

- The python package will be installed to ``${pythondir}/ganeti-${VERSION}``.
  Here ${VERSION} is the full qualified version number, consisting of
  major, minor, revision, and suffix. All python executables will be changed
  to import the correct version of the ganeti package.

- All other files will be installed to the corresponding path under
  ``${libdir}/ganeti-${VERSION}`` instead of under ``${PREFIX}``
  directly, where ${libdir} defaults to ${PREFIX}/lib. Symbolic links
  to these files will be added under ``${PREFIX}/bin``,
  ``${PREFIX}/sbin``, and so on.

As only each version itself has the authoritative knowledge of which
files belong to it, each version provides two executables ``install``
and ``uninstall`` that add and remove the symbolic links,
respectively. Both executables will be idempotent and only touch
symbolic links that are outside the directory for their version of
Ganeti and point into this directory. In particular, an ``uninstall``
of one version will not interfere with an ``install`` of a different
version.

gnt-upgrade
-----------

The actual upgrade process will be done by a new binary,
``gnt-upgrade``. It will take precisely one argument, the version to
upgrade (or downgrade) to, given as full string with major, minor, suffix,
and suffix. To be compatible with current configuration upgrade and downgrade
procedures, the new version must be of the same major version and
either an equal or higher minor version, or precisely the previous
minor version.

When executed, ``gnt-upgrade`` will perform the following actions.

- It verifies that the version to change to is installed on all nodes
  of the cluster that are not marked as offline. If this is not the
  case it aborts with an error. This initial testing is an
  optimization to allow for early feedback.

- An intent-to-upgrade file is created that contains the current
  version of ganeti, the version to change to, and the process ID of
  the ``gnt-upgrade`` process. The latter is not used automatically,
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
  upgrade should be calling ``gnt-upgrade`` from the newer version
  with the older version as argument, a full backup provides an
  additional safety net, especially for jump-upgrades (skipping
  intermediate minor versions).

- If the action is a downgrade to the previous minor version, the
  configuration is downgraded now, using ``cfgupgrade --downgrade``.

- The current version of ganeti is deactivated on all nodes, using the
  ``uninstall`` executable described earlier.

- The new version of ganeti is activated on all nodes, using the
  ``install`` executable described earlier.

- If the action is an upgrade to a higher minor version, the configuration
  is upgraded now, using ``cfgupgrade``.

- All daemons are started on all nodes.

- ``ensure-dirs --full-run`` is run on all nodes.

- ``gnt-cluster redist-conf`` is run on the master node. 

- All daemons are restarted on all nodes.

- The Ganeti job queue is undrained.

- The intent-to-upgrade file is removed.

- ``gnt-cluster verify`` is run and the result reported.


Considerations on unintended reboots of the master node
=======================================================
 
During the upgrade procedure, the only ganeti process still running is
the one instance of ``gnt-upgrade``. This process is also responsible
for eventually removing the queue drain. Therefore, we have to provide
means to resume this process, if it dies unintentionally. The process
itself will handle SIGTERM gracefully by either undoing all changes
done so far, or by ignoring the signal all together and continuing to
the end; the choice between these behaviors depends on whether change
of the configuration has already started (in which case it goes
through to the end), or not (in which case the actions done so far are
rolled back).

To achieve this, ``gnt-upgrade`` will support a ``--resume``
option. It is recommended to have ``gnt-upgrade --resume`` as an
at-reboot task in the crontab. If started with this option,
``gnt-upgrade`` does not accept any arguments. It first verifies that
it is running on the master node, using the same requirement as for
starting the master daemon, i.e., confirmed by a majority of all
nodes. If it is not the master node, it will remove any possibly
existing intend-to-upgrade file and exit. If it is running on the
master node, it will check for the existence of an intend-to-upgrade
file. If no such file is found, it will simply exit. If found, it will
resume at the appropriate stage.

- If the configuration file still is at the initial version,
  ``gnt-upgrade`` is resumed at the step immediately following the
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

Since ``gnt-upgrade`` drains the queue and undrains it later, so any
information about a previous drain gets lost. This problem will
disappear, once :doc:`design-optables` is implemented, as then the
undrain will then be restricted to filters by gnt-upgrade.


Requirement of opcode backwards compatibility
==============================================

Since for upgrades we only pause jobs and do not fully drain the
queue, we need to be able to transform the job queue into a queue for
the new version. The way this is achieved is by keeping the
serialization format backwards compatible. This is in line with
current practice that opcodes do not change between versions, and at
most new fields are added. Whenever we add a new field to an opcode,
we will make sure that the deserialization function will provide a
default value if the field is not present.


