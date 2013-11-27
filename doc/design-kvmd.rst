==========
KVM daemon
==========

.. toctree::
   :maxdepth: 2

This design document describes the KVM daemon, which is responsible for
determining whether a given KVM instance was shutdown by an
administrator or a user.


Current state and shortcomings
==============================

This design document describes the KVM daemon which addresses the KVM
side of the user-initiated shutdown problem introduced in
:doc:`design-internal-shutdown`.  We are also interested in keeping this
functionality optional.  That is, an administrator does not necessarily
have to run the KVM daemon if either he is running Xen or even, if he
is running KVM, he is not interested in instance shutdown detection.
This requirement is important because it means the KVM daemon should
be a modular component in the overall Ganeti design, i.e., it should
be easy to enable and disable it.

Proposed changes
================

The instance shutdown feature for KVM requires listening on events from
the Qemu Machine Protocol (QMP) Unix socket, which is created together
with a KVM instance.  A QMP socket typically looks like
``/var/run/ganeti/kvm-hypervisor/ctrl/<instance>.qmp`` and implements
the QMP protocol.  This is a bidirectional protocol that allows Ganeti
to send commands, such as, system powerdown, as well as, receive events,
such as, the powerdown and shutdown events.

Listening in on these events allows Ganeti to determine whether a given
KVM instance was shutdown by an administrator, either through
``gnt-instance stop|remove <instance>`` or ``kill -KILL
<instance-pid>``, or by a user, through ``poweroff`` from inside the
instance.  Upon an administrator powerdown, the QMP protocol sends two
events, namely, a powerdown event and a shutdown event, whereas upon a
user shutdown only the shutdown event is sent.  This is enough to
distinguish between an administrator and a user shutdown.  However,
there is one limitation, which is, ``kill -TERM <instance-pid>``.  Even
though this is an action performed by the administrator, it will be
considered a user shutdown by the approach described in this document.

Several design strategies were considered.  Most of these strategies
consisted of spawning some process listening on the QMP socket when a
KVM instance is created.  However, having a listener process per KVM
instance is not scalable.  Therefore, a different strategy is proposed,
namely, having a single process, called the KVM daemon, listening on the
QMP sockets of all KVM instances within a node.  That also means there
is an instance of the KVM daemon on each node.

In order to implement the KVM daemon, two problems need to be addressed,
namely, how the KVM daemon knows when to open a connection to a given
QMP socket and how the KVM daemon communicates with Ganeti whether a
given instance was shutdown by an administrator or a user.

QMP connections management
--------------------------

As mentioned before, the QMP sockets reside in the KVM control
directory, which is usually located under
``/var/run/ganeti/kvm-hypervisor/ctrl/``.  When a KVM instance is
created, a new QMP socket for this instance is also created in this
directory.

In order to simplify the design of the KVM daemon, instead of having
Ganeti communicate to this daemon through a pipe or socket the creation
of a new KVM instance, and thus a new QMP socket, this daemon will
monitor the KVM control directory using ``inotify``.  As a result, the
daemon is not only able to deal with KVM instances being created and
removed, but also capable of overcoming other problematic situations
concerning the filesystem, such as, the case when the KVM control
directory does not exist because, for example, Ganeti was not yet
started, or the KVM control directory was removed, for example, as a
result of a Ganeti reinstallation.

Shutdown detection
------------------

As mentioned before, the KVM daemon is responsible for opening a
connection to the QMP socket of a given instance and listening in on the
shutdown and powerdown events, which allow the KVM daemon to determine
whether the instance stopped because of an administrator or user
shutdown.  Once the instance is stopped, the KVM daemon needs to
communicate to Ganeti whether the user was responsible for shutting down
the instance.

In order to achieve this, the KVM daemon writes an empty file, called
the shutdown file, in the KVM control directory with a name similar to
the QMP socket file but with the extension ``.qmp`` replaced with
``.shutdown``.  The presence of this file indicates that the shutdown
was initiated by a user, whereas the absence of this file indicates that
the shutdown was caused by an administrator.  This strategy also handles
crashes and signals, such as, ``SIGKILL``, to be handled correctly,
given that in these cases the KVM daemon never receives the powerdown
and shutdown events and, therefore, never creates the shutdown file.

KVM daemon launch
-----------------

With the above issues addressed, a question remains as to when the KVM
daemon should be started.  The KVM daemon is different from other Ganeti
daemons, which start together with the Ganeti service, because the KVM
daemon is optional, given that it is specific to KVM and should not be
run on installations containing only Xen, and, even in a KVM
installation, the user might still choose not to enable it.  And finally
because the KVM daemon is not really necessary until the first KVM
instance is started.  For these reasons, the KVM daemon is started from
within Ganeti when a KVM instance is started.  And the job process
spawned by the node daemon is responsible for starting the KVM daemon.

Given the current design of Ganeti, in which the node daemon spawns a
job process to handle the creation of the instance, when launching the
KVM daemon it is necessary to first check whether an instance of this
daemon is already running and, if this is not the case, then the KVM
daemon can be safely started.

Design alternatives
===================

At first, it might seem natural to include the instance shutdown
detection for KVM in the node daemon.  After all, the node daemon is
already responsible for managing instances, for example, starting and
stopping an instance.  Nevertheless, the node daemon is more complicated
than it might seem at first.

The node daemon is composed of the main loop, which runs in the main
thread and is responsible for receiving requests and spawning jobs for
handling these requests, and the jobs, which are independent processes
spawned for executing the actual tasks, such as, creating an instance.

Including instance shutdown detection in the node daemon is not viable
because adding it to the main loop would cause KVM specific code to
taint the generality of the node daemon.  In order to add it to the job
processes, it would be possible to spawn either a foreground or a
background process.  However, these options are also not viable because
they would lead to the situation described before where there would be a
monitoring process per instance, which is not scalable.  Moreover, the
foreground process has an additional disadvantage: it would require
modifications the node daemon in order not to expect a terminating job,
which is the current node daemon design.

There is another design issue to have in mind.  We could reconsider the
place where to write the data that tell Ganeti whether an instance was
shutdown by an administrator or the user.  Instead of using the KVM
shutdown files presented above, in which the presence of the file
indicates a user shutdown and its absence an administrator shutdown, we
could store a value in the KVM runtime state file, which is where the
relevant KVM state information is.  The advantage of this approach is
that it would keep the KVM related information in one place, thus making
it easier to manage.  However, it would lead to a more complex
implementation and, in the context of the general transition in Ganeti
from Python to Haskell, a simpler implementation is preferred.

Finally, it should be noted that the KVM runtime state file benefits
from automatic migration.  That is, when an instance is migrated so is
the KVM state file.  However, the instance shutdown detection for KVM
does not require this feature and, in fact, migrating the instance
shutdown state would be incorrect.

Further considerations
======================

There are potential race conditions between Ganeti and the KVM daemon,
however, in practice they seem unlikely.  For example, the KVM daemon
needs to add and remove watches to the parent directories of the KVM
control directory until this directory is finally created.  It is
possible that Ganeti creates this directory and a KVM instance before
the KVM daemon has a chance to add a watch to the KVM control directory,
thus causing this daemon to miss the ``inotify`` creation event for the
QMP socket.

There are other problems which arise from the limitations of
``inotify``.  For example, if the KVM daemon is started after the first
Ganeti instance has been created, then the ``inotify`` will not produce
any event for the creation of the QMP socket.  This can happen, for
example, if the KVM daemon needs to be restarted or upgraded.  As a
result, it might be necessary to have an additional mechanism that runs
at KVM daemon startup or at regular intervals to ensure that the current
KVM internal state is consistent with the actual contents of the KVM
control directory.

Another race condition occurs when Ganeti shuts down a KVM instance
using force.  Ganeti uses ``TERM`` signals to stop KVM instances when
force is specified or ACPI is not enabled.  However, as mentioned
before, ``TERM`` signals are interpreted by the KVM daemon as a user
shutdown.  As a result, the KVM daemon creates a shutdown file which
then must be removed by Ganeti.  The race condition occurs because the
KVM daemon might create the shutdown file after the hypervisor code that
tries to remove this file has already run.  In practice, the race
condition seems unlikely because Ganeti stops the KVM instance in a
retry loop, which allows Ganeti to stop the instance and cleanup its
runtime information.

It is possible to determine if a process, in this particular case the
KVM process, was terminated by a ``TERM`` signal, using the `proc
connector and socket filters
<https://web.archive.org/web/20121025062848/http://netsplit.com/2011/02/09/the-proc-connector-and-socket-filters/>`_.
The proc connector is a socket connected between a userspace process and
the kernel through the netlink protocol and can be used to receive
notifications of process events, and the socket filters is a mechanism
for subscribing only to events that are relevant.  There are several
`process events <http://lwn.net/Articles/157150/>`_ which can be
subscribed to, however, in this case, we are interested only in the exit
event, which carries information about the exit signal.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
