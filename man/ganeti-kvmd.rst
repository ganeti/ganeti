ganeti-kvmd(8) Ganeti | Version @GANETI_VERSION@
================================================

Name
----

ganeti-kvmd - Ganeti KVM daemon

Synopsis
--------

**ganeti-kvmd**

DESCRIPTION
-----------

The KVM daemon is responsible for determining whether a given KVM
instance was shutdown by an administrator or a user.

The KVM daemon monitors, using ``inotify``, KVM instances through
their QMP sockets, which are provided by KVM.  Using the QMP sockets,
the KVM daemon listens for particular shutdown, powerdown, and stop
events which will determine if a given instance was shutdown by the
user or Ganeti, and this result is communicated to Ganeti via a
special file in the filesystem.

FILES
-----

The KVM daemon monitors Qmp sockets of KVM instances, which are created
in the KVM control directory, located under
``@LOCALSTATEDIR@/run/ganeti/kvm-hypervisor/ctrl/``.  The KVM daemon
also creates shutdown files in this directory.  Finally, the KVM
daemon's log file is located under
``@LOCALSTATEDIR@/log/ganeti/ganeti-kvmd.log``.  Removal of the KVM
control directory, the shutdown files, or the log file, will lead to no
errors on the KVM daemon.
