===================
Systemd integration
===================

.. contents:: :depth: 4

This design document outlines the implementation of native systemd
support in Ganeti by providing systemd unit files. It also briefly
discusses the possibility of supporting socket activation.


Current state and shortcomings
==============================

Ganeti currently ships an example init script, compatible with Debian
(and derivatives) and RedHat/Fedora (and derivatives). The initscript
treats the whole Ganeti system as a single service wrt. starting and
stopping (but allows starting/stopping/restarting individual daemons).

The initscript is aided by ``daemon-util``, which takes care of correctly
ordering the startup/shutdown of daemons using an explicit order.

Finally, process supervision is achieved by (optionally) running
``ganeti-watcher`` via cron every 5 minutes. ``ganeti-watcher`` will - among
other things - try to start services that should be running but are not.

The example initscript currently shipped with Ganeti will work with
systemd's LSB compatibility wrappers out of the box, however there are
a number of areas where we can benefit from providing native systemd
unit files:

  - systemd is the `de-facto choice`_ of almost all major Linux
    distributions. Since it offers a stable API for service control,
    providing our own systemd unit files means that Ganeti will run
    out-of-the-box and in a predictable way in all distributions using
    systemd.

  - systemd performs constant process supervision with immediate
    service restarts and configurable back-off. Ganeti currently offers
    supervision only via ganeti-watcher, running via cron in 5-minute
    intervals and unconditionally starting missing daemons even if they
    have been manually stopped.

  - systemd offers `socket activation`_ support, which may be of
    interest for use at least with masterd, luxid and noded. Socket
    activation offers two main advantages: no explicit service
    dependencies or ordering needs to be defined as services will be
    activated when needed; and seamless restarts / upgrades are possible
    without rejecting new client connections.

  - systemd offers a number of `security features`_, primarily using
    the Linux kernel's namespace support, which may be of interest to
    better restrict daemons running as root (noded and mond).

.. _de-facto choice: https://en.wikipedia.org/wiki/Systemd#Adoption
.. _socket activation: http://0pointer.de/blog/projects/socket-activation.html
.. _security features: http://0pointer.de/blog/projects/security.html

Proposed changes
================

We propose to extend Ganeti to natively support systemd, in addition to
shipping the init-script as is. This requires the addition of systemd
unit files, as well as some changes in daemon-util and ganeti-watcher to
use ``systemctl`` on systems where Ganeti is managed by systemd.

systemd unit files
------------------

Systemd uses unit files to store information about a service, device,
mount point, or other resource it controls. Each unit file contains
exactly one unit definition, consisting of a ``Unit`` an (optional)
``Install`` section and an (optional) type-specific section (e.g.
``Service``). Unit files are dropped in pre-determined locations in the
system, where systemd is configured to read them from. Systemd allows
complete or partial overrides of the unit files, using overlay
directories. For more information, see `systemd.unit(5)`_.

.. _systemd.unit(5): http://www.freedesktop.org/software/systemd/man/systemd.unit.html

We will create one systemd `service unit`_ per daemon (masterd, noded,
mond, luxid, confd, rapi) and an additional oneshot service for
ensure-dirs (``ganeti-common.service``). All services will ``Require``
``ganeti-common.service``, which will thus run exactly once per
transaction (regardless of starting one or all daemons).

.. _service unit: http://www.freedesktop.org/software/systemd/man/systemd.service.html

All daemons will run in the foreground (already implemented by the
``-f`` flag), directly supervised by systemd, using
``Restart=on-failure`` in the respective units. Master role units will
also treat ``EXIT_NOTMASTER`` as a successful exit and not trigger
restarts. Additionally, systemd's conditional directives will be used to
avoid starting daemons when they will certainly fail (e.g. because of
missing configuration).

Apart from the individual daemon units, we will also provide three
`target units`_ as synchronization points:

  - ``ganeti-node.target``: Regular node/master candidate functionality,
    including ``ganeti-noded.service``, ``ganeti-mond.service`` and
    ``ganeti-confd.service``.

  - ``ganeti-master.target``: Master node functionality, including
    ``ganeti-masterd.service``, ``ganeti-luxid.service`` and
    ``ganeti-rapi.service``.

  - ``ganeti.target``: A "meta-target" depending on
    ``ganeti-node.target`` and ``ganti-master.target``.
    ``ganeti.target`` itself will be ``WantedBy`` ``multi-user.target``,
    so that Ganeti starts automatically on boot.

.. _target units: http://www.freedesktop.org/software/systemd/man/systemd.target.html

To allow starting/stopping/restarting the different roles, all units
will include a ``PartOf`` directive referencing their direct ancestor
target. In this way ``systemctl restart ganeti-node.target`` or ``systemctl
restart ganeti.target`` will work as expected, i.e. restart only the node
daemons or all daemons respectively.

The full dependency tree is as follows:

::

    ganeti.target
    ├─ganeti-master.target
    │ ├─ganeti-luxid.service
    │ │ └─ganeti-common.service
    │ ├─ganeti-masterd.service
    │ │ └─ganeti-common.service
    │ └─ganeti-rapi.service
    │   └─ganeti-common.service
    └─ganeti-node.target
      ├─ganeti-confd.service
      │ └─ganeti-common.service
      ├─ganeti-mond.service
      │ └─ganeti-common.service
      └─ganeti-noded.service
        └─ganeti-common.service

Installation
~~~~~~~~~~~~
The systemd unit files will be built from templates under
doc/examples/systemd, much like what is currently done for the
initscript. They will not be installed with ``make install``, but left
up to the distribution packagers to ship them at the appropriate
locations.

SysV compatibility
~~~~~~~~~~~~~~~~~~
Systemd automatically creates a service for each SysV initscript on the
system, appending ``.service`` to the initscript name, except if a
service with the given name already exists. In our case however, the
initscript's functionality is implemented by ``ganeti.target``.

Systemd provides the ability to *mask* a given service, rendering it
unusable, but in the case of SysV services this also results in
failure to use tools like ``invoke-rc.d`` or ``service``. Thus we have
to ship a ``ganeti.service`` (calling ``/bin/true``) of type
``oneshot``, that depends on ``ganeti.target`` for these tools to
continue working as expected.  ``ganeti.target`` on the other hand will
be marked as ``PartOf = ganeti.service`` for stop and restart to be
propagated to the whole service.

The ``ganeti.service`` unit will not be marked to be enabled by systemd
(i.e. will not be started at boot), but will be available for manual
invocation and only be used for compatibility purposes.

Changes to daemon-util
----------------------

``daemon-util`` is used wherever daemon control is required:

  - In the sample initscript, to start and stop all daemons.
  - In ``ganeti.backend`` to start the master daemons on master failover and
    to stop confd when leaving the cluster.
  - In ``ganeti.bootstrap``, to start the daemons on cluster initialization.
  - In ``ganeti.cli``, to control the daemon run state during certain
    operations (e.g. renew-crypto).

Currently, ``daemon-util`` uses two auxiliary tools for managing daemons
``start-stop-daemon`` and ``daemon``, in this order of preference.  In
order not to confuse systemd in its process supervision, ``daemon-util``
will have to be modified to start and stop the daemons via ``systemctl``
in preference to ``start-stop-daemon`` and ``daemon``. This
will require a basic check against run-time environment integrity:

  - Make sure that ``systemd`` runs as PID 1, which is a `simple
    check`_ against the existence of ``/run/systemd/system``.
  - Make sure ``systemd`` knows how to handle Ganeti natively. This can
    be a check against the ``LoadState`` of the ``ganeti.target`` unit.

Unless both of these checks pass, ``daemon-util`` will fall back to its
current behavior.

.. _simple check: http://www.freedesktop.org/software/systemd/man/sd_booted.html

Changes to ganeti-watcher
-------------------------

Since the daemon process supervision will be systemd's responsibility,
the watcher must detect systemd's presence and not attempt to start any
missing services. Again, systemd can be detected by the existence of
``/run/systemd/system``.

Future work
===========

Socket activation
-----------------

Systemd offers support for `socket activation`_. A daemon supporting
socket-based activation, can inherit its listening socket(s) by systemd.
This in turn means that the socket can be created and bound by systemd
during early boot and it can be used to provide implicit startup
ordering; as soon as a client connects to the listening socket, the
respective service (and all its dependencies) will be started and the
client will wait until its connection is accepted.

Also, because the socket remains bound even if the service is
restarting, new client connections will never be rejected, making
service restarts and upgrades seamless.

Socket activation support is trivial to implement (see
`sd_listen_fds(3)`_) and relies on information passed by systemd via
environment variables to the started processes.

.. _sd_listen_fds(3): http://www.freedesktop.org/software/systemd/man/sd_listen_fds.html

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
