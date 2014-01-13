============================================================
Detection of user-initiated shutdown from inside an instance
============================================================

.. contents:: :depth: 2

This is a design document detailing the implementation of a way for Ganeti to
detect whether an instance marked as up but not running was shutdown gracefully
by the user from inside the instance itself.

Current state and shortcomings
==============================

Ganeti keeps track of the desired status of instances in order to be able to
take proper action (e.g.: reboot) on the instances that happen to crash.
Currently, the only way to properly shut down an instance is through Ganeti's
own commands, which can be used to mark an instance as ``ADMIN_down``.

If a user shuts down an instance from inside, through the proper command of the
operating system it is running, the instance will be shutdown gracefully, but
Ganeti is not aware of that: the desired status of the instance will still be
marked as ``running``, so when the watcher realises that the instance is down,
it will restart it. This behaviour is usually not what the user expects.

Proposed changes
================

We propose to modify Ganeti in such a way that it will detect when an instance
was shutdown as a result of an explicit request from the user. When such a
situation is detected, instead of presenting an error as it happens now, either
the state of the instance will be set to ``ADMIN_down``, or the instance will be
automatically rebooted, depending on an instance-specific configuration value.
The default behavior in case no such parameter is found will be to follow the
apparent will of the user, and setting to ``ADMIN_down`` an instance that was
shut down correctly from inside.

The rest of this design document details the implementation of instance shutdown
detection for Xen.  The KVM implementation is detailed in :doc:`design-kvmd`.

Implementation
==============

Xen knows why a domain is being shut down (a crash or an explicit shutdown
or poweroff request), but such information is not usually readily available
externally, because all such cases lead to the virtual machine being destroyed
immediately after the event is detected.

Still, Xen allows the instance configuration file to define what action to be
taken in all those cases through the ``on_poweroff``, ``on_shutdown`` and
``on_crash`` variables. By setting them to ``preserve``, Xen will avoid
destroying the domains automatically.

When the domain is not destroyed, it can be viewed by using ``xm list`` (or ``xl
list`` in newer Xen versions), and the ``State`` field of the output will
provide useful information.

If the state is ``----c-`` it means the instance has crashed.

If the state is ``---s--`` it means the instance was properly shutdown.

If the instance was properly shutdown and it is still marked as ``running`` by
Ganeti, it means that it was shutdown from inside by the user, and the Ganeti
status of the instance needs to be changed to ``ADMIN_down``.

This will be done at regular intervals by the group watcher, just before
deciding which instances to reboot.

On top of that, at the same time, the watcher will also need to issue ``xm
destroy`` commands for all the domains that are in a crashed or shutdown state,
since this will not be done automatically by Xen anymore because of the
``preserve`` setting in their config files.

This behavior will be limited to the domains shut down from inside, because it
will actually keep the resources of the domain busy until the watcher will do
the cleaning job (that, with the default setting, is up to every 5 minutes).
Still, this is considered acceptable, because it is not frequent for a domain to
be shut down this way. The cleanup function will be also run automatically just
before performing any job that requires resources to be available (such as when
creating a new instance), in order to ensure that the new resource allocation
happens starting from a clean state. Functionalities that only query the state
of instances will not run the cleanup function.

The cleanup operation includes both node-specific operations (the actual
destruction of the stopped domains) and configuration changes, to be performed
on the master node (marking as offline an instance that was shut down
internally). The watcher, on the master node, will fetch the list of instances
that have been shutdown from inside (recognizable by their ``oper_state``
as described below). It will then submit a series of ``InstanceShutdown`` jobs
that will mark such instances as ``ADMIN_down`` and clean them up (after
the functionality of ``InstanceShutdown`` will have been extended as specified
in the rest of this design document).

LUs performing operations other than an explicit cleanup will have to be
modified to perform the cleanup as well, either by submitting a job to perform
the cleanup (to be completed before actually performing the task at hand) or by
explicitly performing the cleanup themselves through the RPC calls.

Other required changes
++++++++++++++++++++++

The implementation of this design document will require some commands to be
changed in order to cope with the new shutdown procedure.

With the default shutdown action in Xen set to ``preserve``, the Ganeti
command for shutting down instances would leave them in a shutdown but
preserved state. Therefore, it will have to be changed in such a way to
immediately perform the cleanup of the instance after verifying its correct
shutdown. Also, it will correctly deal with instances that have been shutdown
from inside but are still active according to Ganeti, by detecting this
situation, destroying the instance and carrying out the rest of the Ganeti
shutdown procedure as usual.

The ``gnt-instance list`` command will need to be able to handle the situation
where an instance was shutdown internally but not yet cleaned up.  The
``admin_state`` field will maintain the current meaning unchanged. The
``oper_state`` field will get a new possible state, ``S``, meaning that the
instance was shutdown internally.

The ``gnt-instance info`` command ``State`` field, in such case, will show a
message stating that the instance was supposed to be run but was shut down
internally.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
