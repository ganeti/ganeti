===============================
Ganeti OS installation redesign
===============================

.. contents:: :depth: 3

This is a design document detailing a new OS installation procedure, which is
more secure, able to provide more features and easier to use for many common
tasks w.r.t. the current one.

Current state and shortcomings
==============================

As of Ganeti 2.10, each instance is associated with an OS definition. An OS
definition is a set of scripts (i.e., ``create``, ``export``, ``import``,
``rename``) that are executed with root privileges on the primary host of the
instance.  These scripts are responsible for performing all the OS-related
tasks, namely, create an instance, setup an operating system on the instance's
disks, export/import the instance, and rename the instance.

These scripts receive, through environment variables, a fixed set of instance
parameters (such as, the hypervisor, the name of the instance, the number of
disks and their location) and a set of user defined parameters.  Both the
instance and user defined parameters are written in the configuration file of
Ganeti, to allow future reinstalls of the instance, and in various log files,
namely:

* node daemon log file: contains DEBUG strings of the ``/os_validate``,
  ``/instance_os_add`` and ``/instance_start`` RPC calls.

* master daemon log file: DEBUG strings related to the same RPC calls are stored
  here as well.

* commands log: the CLI commands that create a new instance, including their
  parameters, are logged here.

* RAPI log: the RAPI commands that create a new instance, including their
  parameters, are logged here.

* job logs: the job files stored in the job queue, or in its archive, contain
  the parameters.

The current situation presents a number of shortcomings:

* Having the installation scripts run as root on the nodes does not allow
  user-defined OS scripts, as they would pose a huge security risk.
  Furthermore, even a script without malicious intentions might end up
  disrupting a node because of due to a bug.

* Ganeti cannot be used to create instances starting from user provided disk
  images: even in the (hypothetical) case in which the scripts are completely
  secure and run not by root but by an unprivileged user with only the power to
  mount arbitrary files as disk images, this is still a security issue. It has
  been proven that a carefully crafted file system might exploit kernel
  vulnerabilities to gain control of the system. Therefore, directly mounting
  images on the Ganeti nodes is not an option.

* There is no way to inject files into an existing disk image. A common use case
  is for the system administrator to provide a standard image of the system, to
  be later personalized with the network configuration, private keys identifying
  the machine, ssh keys of the users, and so on. A possible workaround would be
  for the scripts to mount the image (only if this is trusted!) and to receive
  the configurations and ssh keys as user defined OS parameters. Unfortunately,
  this is also not an option for security sensitive material (such as the ssh
  keys) because the OS parameters are stored in many places on the system, as
  already described above.

* Most other virtualization software allow only instance images, but no
  installation scripts. This difference makes the interaction between Ganeti and
  other software difficult.

Proposed changes
================

In order to fix the shortcomings of the current state, we plan to introduce the
following changes.

OS parameter categories
+++++++++++++++++++++++

Change the OS parameters to have three categories:

* ``public``: the current behavior. The parameter is logged and stored freely.

* ``private``: the parameter is saved inside the Ganeti configuration (to allow
  for instance reinstall) but it is not shown in logs, job logs, or passed back
  via RAPI.

* ``secret``: the parameter is not saved inside the Ganeti configuration.
  Reinstalls are impossible unless the data is passed again. The parameter will
  not appear in any log file. When a functionality is performed jointly by
  multiple daemons (such as MasterD and LuxiD), currently Ganeti sometimes
  serializes jobs on disk and later reloads them. Secret parameters will not be
  serialized to disk. They will be passed around as part of the LUXI calls
  exchanged by the daemons, and only kept in memory, in order to reduce their
  accessibility as much as possible. In case of failure of the master node,
  these parameters will be lost and cannot be recovered because they are not
  serialized. As a result, the job cannot be taken over by the new master.  This
  is an expected and accepted side effect of jobs with secret parameters: if
  they fail, they'll have to be restarted manually.

Metadata
++++++++

In order to allow metadata to be sent inside the instance, a communication
mechanism between the instance and the host will be created.  This mechanism
will be bidirectional (e.g.: to allow the setup process going on inside the
instance to communicate its progress to the host). Each instance will have
access exclusively to its own metadata, and it will be only able to communicate
with its host over this channel.  This is the approach followed the
``cloud-init`` tool and more details will be provided in the `Communication
mechanism`_ and `Metadata service`_ sections.

Installation procedure
++++++++++++++++++++++

A new installation procedure will be introduced.  There will be two sets of
parameters, namely, installation parameters, which are used mainly for installs
and reinstalls, and execution parameters, which are used in all the other runs
that are not part of an installation procedure.  Also, it will be possible to
use an installation medium and/or run the OS scripts in an optional virtualized
environment, and optionally use a personalization package.  This section details
all of these options.

The set of installation parameters will allow, for example, to attach an
installation floppy/cdrom/network, change the boot device order, or specify a
disk image to be used.  Through this set of parameters, the administrator will
have to provide the hypervisor a location for an installation medium for the
instance (e.g., a boot disk, a network image, etc).  This medium will carry out
the installation of the instance onto the instance's disks and will then be
responsible for getting the parameters for configuring the instance, such as,
network interfaces, IP address, and hostname.  These parameters are taken from
the metadata.  The installation parameters will be stored in the configuration
of Ganeti and used in future reinstalls, but not during normal execution.

The instance is reinstalled using the same installation parameters from the
first installation.  However, it will be the administrator's responsibility to
ensure that the installation media is still available at the proper location
when a reinstall occurs.

The parameter ``--os-parameters`` can still be used to specify the OS
parameters.  However, without OS scripts, Ganeti cannot do more than a syntactic
check to validate the supplied OS parameter string.  As a result, this string
will be passed directly to the instance as part of the metadata.  If OS scripts
are used and the installation procedure is running inside a virtualized
environment, Ganeti will take these parameters from the metadata and pass them
to the OS scripts as environment variables.

Ganeti allows the following installation options:

* Use a disk image:

  Currently, it is already possible to specify an installation medium, such as,
  a cdrom, but not a disk image.  Therefore, a new parameter ``--os-image`` will
  be used to specify the location of a disk image which will be dumped to the
  instance's first disk before the instance is started.  The location of the
  image can be a URL and, if this is the case, Ganeti will download this image.

* Run OS scripts:

  The parameter ``--os-type`` (short version: ``-o``), is currently used to
  specify the OS scripts.  This parameter will still be used to specify the OS
  scripts with the difference that these scripts may optionally run inside a
  virtualized environment for safety reasons, depending on whether they are
  trusted or not.  For more details on trusted and untrusted OS scripts, refer
  to the `Installation process in a virtualized environment`_ section.  Note
  that this parameter will become optional thus allowing a user to create an
  instance specifying only, for example, a disk image or a cdrom image to boot
  from.

* Personalization package

  As part of the instance creation command, it will be possible to indicate a
  URL for a "personalization package", which is an archive containing a set of
  files meant to be overlayed on top of the OS file system at the end of the
  setup process and before the VM is started for the first time in normal mode.
  Ganeti will provide a mechanism for receiving and unpacking this archive,
  independently of whether the installation is being performed inside the
  virtualized environment or not.

  The archive will be in TAR-GZIP format (with extension ``.tar.gz`` or
  ``.tgz``) and contain the files according to the directory structure that will
  be recreated on the installation disk.  Files contained in this archive will
  overwrite files with the same path created during the installation procedure
  (if any).  The URL of the "personalization package" will have to specify an
  extension to identify the file format (in order to allow for more formats to
  be supported in the future).  The URL will be stored as part of the
  configuration of the instance (therefore, the URL should not contain
  confidential information, but the files there available can).

  It is up to the system administrator to ensure that a package is actually
  available at that URL at install and reinstall time.  The contents of the
  package are allowed to change.  E.g.: a system administrator might create a
  package containing the private keys of the instance being created.  When the
  instance is reinstalled, a new package with new keys can be made available
  there, thus allowing instance reinstall without the need to store keys.  A
  username and a password can be specified together with the URL.  If the URL is
  a HTTP(S) URL, they will be used as basic access authentication credentials to
  access that URL.  The username and password will not be saved in the config,
  and will have to be provided again in case a reinstall is requested.

  The downloaded personalization package will not be stored locally on the node
  for longer than it is needed while unpacking it and adding its files to the
  instance being created.  The personalization package will be overlayed on top
  of the instance filesystem after the scripts that created it have been
  executed.  In order for the files in the package to be automatically overlayed
  on top of the instance filesystem, it is required that the appliance is
  actually able to mount the instance's disks.  As a result, this will not work
  for every filesystem.

* Combine a disk image, OS scripts, and a personalization package

  It will possible to combine a disk image, OS scripts, and a personalization
  package, both with or without a virtualized environment (see the exception
  below). At least, an installation medium or OS scripts should be specified.

  The disk image of the actual virtual appliance, which bootstraps the virtual
  environment used in the installation procedure, will be read only, so that a
  pristine copy of the appliance can be started every time a new instance needs
  to be created and to further increase security.  The data the instance needs
  to write at runtime will only be stored in RAM and disappear as soon as the
  instance is stopped.

  The parameter ``--enable-safe-install=yes|no`` will be used to give the
  administrator control over whether to use a virtualized environment for the
  installation procedure.  By default, a virtualized environment will be used.
  Note that some feature combinations, such as, using untrusted scripts, will
  require the virtualized environment.  In this case, Ganeti will not allow
  disabling the virtualized environment.

Implementation
==============

The implementation of this design will happen as an ordered sequence of steps,
of increasing impact on the system and, in some cases, dependent on each other:

#. Private and secret instance parameters
#. Communication mechanism between host and instance
#. Metadata service
#. Personalization package (inside a virtualization environment)
#. Instance creation via a disk image
#. Instance creation inside a virtualized environment

Some of these steps need to be more deeply specified w.r.t. what is already
written in the `Proposed changes`_ Section. Extra details will be provided in
the following subsections.

Communication mechanism
+++++++++++++++++++++++

The communication mechanism will be an exclusive, generic, bidirectional
communication channel between Ganeti hosts and guests.

exclusive
  The communication mechanism allows communication between a guest and its host,
  but it does not allow a guest to communicate with other guests or reach the
  outside world.

generic
  The communication mechanism allows a guest to reach any service on the host,
  not just the metadata service.  Examples of valid communication include, but
  are not limited to, access to the metadata service, send commands to Ganeti,
  request changes to parameters, such as, those related to the distribution
  upgrades, and let Ganeti control a helper instance, such as, the one for
  performing OS installs inside a safe environment.

bidirectional
  The communication mechanism allows communication to be initiated from either
  party, namely, from a host to a guest or guest to host.

Note that Ganeti will allow communication with any service (e.g., daemon) running
on the host and, as a result, Ganeti will not be responsible for ensuring that
only the metadata service is reachable.  It is the responsibility of each system
administrator to ensure that the extra firewalling and routing rules specified
on the host provide the necessary protection on a given Ganeti installation and,
at the same time, do not accidentally override the behaviour hereby described
which makes the communication between the host and the guest exclusive, generic,
and bidirectional, unless intended.

The communication mechanism will be enabled automatically during an installation
procedure that requires a virtualized environment, but, for backwards
compatibility, it will be disabled when the instance is running normally, unless
explicitly requested.  Specifically, a new parameter ``--communication=yes|no``
(short version: ``-C``) will be added to ``gnt-instance add`` and ``gnt-instance
modify``.  This parameter will determine whether the communication mechanism is
enabled for a particular instance.  The value of this parameter will be saved as
part of the instance's configuration.

The communication mechanism will be implemented through network interfaces on
the host and the guest, and Ganeti will be responsible for the host side,
namely, creating a TAP interface for each guest and configuring these interfaces
to have name ``gnt.com.%d``, where ``%d`` is a unique number within the host
(e.g., ``gnt.com.0`` and ``gnt.com.1``), IP address ``169.254.169.254``, and
netmask ``255.255.255.255``.  The interface's name allows DHCP servers to
recognize which interfaces are part of the communication mechanism.

This network interface will be connected to the guest's last network interface,
which is meant to be used exclusively for the communication mechanism and is
defined after all the used-defined interfaces.  The last interface was chosen
(as opposed to the first one, for example) because the first interface is
generally understood and the main gateway out, and also because it minimizes the
impact on existing systems, for example, in a scenario where the system
administrator has a running cluster and wants to enable the communication
mechanism for already existing instances, which might have been created with
older versions of Ganeti.  Further, DBus should assist in keeping the guest
network interfaces more stable.

On the guest side, each instance will have its own MAC address and IP address.
Both the guest's MAC address and IP address must be unique within a single
cluster.  An IP is unique within a single cluster, and not within a single host,
in order to minimize disruption of connectivity, for example, during live
migration, in particular since an instance is not aware when it changes host.
Unfortunately, a side-effect of this decision is that a cluster can have a
maximum of a ``/16`` network allowed instances (with communication enabled).  If
necessary to overcome this limit, it should be possible to allow different
networks to be configured link-local only.

The guest will use the DHCP protocol on its last network interface to contact a
DHCP server running on the host and thus determine its IP address.  The DHCP
server is configured, started, and stopped, by Ganeti and it will be listening
exclusively on the TAP network interfaces of the guests in order not to
interfere with a potential DHCP server running on the same host.  Furthermore,
the DHCP server will only recognize MAC and IP address pairs that have been
approved by Ganeti.

The TAP network interfaces created for each guest share the same IP address.
Therefore, it will be necessary to extend the routing table with rules specific
to each guest.  This can be achieved with the following command, which takes the
guest's unique IP address and its TAP interface::

  route add -host <ip> dev <ifname>

This rule has the additional advantage of preventing guests from trying to lease
IP addresses from the DHCP server other than the own that has been assigned to
them by Ganeti.  The guest could lie about its MAC address to the DHCP server
and try to steal another guest's IP address, however, this routing rule will
block traffic (i.e., IP packets carrying the wrong IP) from the DHCP server to
the malicious guest.  Similarly, the guest could lie about its IP address (i.e.,
simply assign a predefined IP address, perhaps from another guest), however,
replies from the host will not be routed to the malicious guest.

This routing rule ensures that the communication channel is exclusive but, as
mentioned before, it will not prevent guests from accessing any service on the
host.  It is the system administrator's responsibility to employ the necessary
``iptables`` rules.  In order to achieve this, Ganeti will provide ``ifup``
hooks associated with the guest network interfaces which will give system
administrator's the opportunity to customize their own ``iptables``, if
necessary.  Ganeti will also provide examples of such hooks.  However, these are
meant to personalized to each Ganeti installation and not to be taken as
production ready scripts.

For KVM, an instance will be started with a unique MAC address and the file
descriptor for the TAP network interface meant to be used by the communication
mechanism.  Ganeti will be responsible for generating a unique MAC address for
the guest, opening the TAP interface, and passing its file descriptor to KVM::

  kvm -net nic,macaddr=<mac> -net tap,fd=<tap-fd> ...

For Xen, a network interface will be created on the host (using the ``vif``
parameter of the Xen configuration file).  Each instance will have its
corresponding ``vif`` network interface on the host.  The ``vif-route`` script
of Xen might be helpful in implementing this.

dnsmasq
+++++++

The previous section describes the communication mechanism and explains the role
of the DHCP server.  Note that any DHCP server can be used in the implementation
of the communication mechanism.  However, the DHCP server employed should not
violate the properties described in the previous section, which state that the
communication mechanism should be exclusive, generic, and bidirectional, unless
this is intentional.

In our experiments, we have used dnsmasq.  In this section, we describe how to
properly configure dnsmasq to work on a given Ganeti installation.  This is
particularly important if, in this Ganeti installation, dnsmasq will share the
node with one or more DHCP servers running in parallel.

First, it is important to become familiar with the operational modes of dnsmasq,
which are well explained in the `FAQ
<http://www.thekelleys.org.uk/dnsmasq/docs/FAQ>`_ under the question ``What are
these strange "bind-interface" and "bind-dynamic" options?``.  The rest of this
section assumes the reader is familiar with these operational modes.

bind-dynamic
  dnsmasq SHOULD be configured in the ``bind-dynamic`` mode (if supported) in
  order to allow other DHCP servers to run on the same node.  In this mode,
  dnsmasq can listen on the TAP interfaces for the communication mechanism by
  listening on the TAP interfaces that match the pattern ``gnt.com.*`` (e.g.,
  ``interface=gnt.com.*``).  For extra safety, interfaces matching the pattern
  ``eth*`` and the name ``lo`` should be configured such that dnsmasq will
  always ignore them (e.g., ``except-interface=eth*`` and
  ``except-interface=lo``).

bind-interfaces
  dnsmasq MAY be configured in the ``bind-interfaces`` mode (if supported) in
  order to allow other DHCP servers to run on the same node.  Unfortunately,
  because dnsmasq cannot dynamically adjust to TAP interfaces that are created
  and destroyed by the system, dnsmasq must be restarted with a new
  configuration file each time an instance is created or destroyed.

  Also, the interfaces cannot be patterns, such as, ``gnt.com.*``.  Instead, the
  interfaces must be explictly specified, for example,
  ``interface=gnt.com.0,gnt.com.1``.  Moreover, dnsmasq cannot bind to the TAP
  interfaces if they have all the same IPv4 address.  As a result, it is
  necessary to configure these TAP interfaces to enable IPv6 and an IPv6 address
  must be assigned to them.

wildcard
  dnsmasq CANNOT be configured in the ``wildcard`` mode if there is
  (at least) another DHCP server running on the same node.

Metadata service
++++++++++++++++

An instance will be able to reach metadata service on ``169.254.169.254:80`` in
order to, for example, retrieve its metadata.  This IP address and port were
chosen for compatibility with the OpenStack and Amazon EC2 metadata service.
The metadata service will be provided by a single daemon, which will determine
the source instance for a given request and reply with the metadata pertaining
to that instance.

Where possible, the metadata will be provided in a way compatible with Amazon
EC2, at::

  http://169.254.169.254/<version>/meta-data/*

Ganeti-specific metadata, that does not fit this structure, will be provided
at::

  http://169.254.169.254/ganeti/<version>/meta_data.json

where ``<version>`` is either a date in YYYY-MM-DD format, or ``latest`` to
indicate the most recent available protocol version.

If needed in the future, this structure also allows us to support OpenStack's
metadata at::

  http://169.254.169.254/openstack/<version>/meta_data.json

A bi-directional, pipe-like communication channel will also be provided.  The
instance will be able to receive data from the host by a GET request at::

  http://169.254.169.254/ganeti/<version>/read

and to send data to the host by a POST request at::

  http://169.254.169.254/ganeti/<version>/write

As in a pipe, once the data are read, they will not be in the buffer anymore, so
subsequent GET requests to ``read`` will not return the same data.  However,
unlike a pipe, it will not be possible to perform blocking I/O operations.

The OS parameters will be accessible through a GET request at::

  http://169.254.169.254/ganeti/<version>/os/parameters.json

as a JSON serialized dictionary having the parameter name as the key, and the
pair ``(<value>, <visibility>)`` as the value, where ``<value>`` is the
user-provided value of the parameter, and ``<visibility>`` is either ``public``,
``private`` or ``secret``.

The installation scripts to be run inside the virtualized environment will be
available at::

  http://169.254.169.254/ganeti/<version>/os/scripts/<script_name>

where ``<script_name>`` is the name of the script.

Rationale
---------

The choice of using a network interface for instance-host communication, as
opposed to VirtIO, XenBus or other methods, is due to the will of having a
generic, hypervisor-independent way of creating a communication channel, that
doesn't require unusual (para)virtualization drivers.
At the same time, a network interface was preferred over solutions involving
virtual floppy or USB devices because the latter tend to be detected and
configured by the guest operating systems, sometimes even in prominent positions
in the user interface, whereas it is fairly common to have an unconfigured
network interface in a system, usually without any negative side effects.

Installation process in a virtualized environment
+++++++++++++++++++++++++++++++++++++++++++++++++

In the new OS installation scenario, we distinguish between trusted and
untrusted code.

The trusted installation code maintains the behavior of the current one and
requires no modifications, with the scripts running on the node the instance is
being created on. The untrusted code is stored in a subdirectory of the OS
definition called ``untrusted``.  This directory contains scripts that are
equivalent to the already existing ones (``create``, ``export``, ``import``,
``rename``) but that will be run inside an virtualized environment, to protect
the host from malicious tampering.

The ``untrusted`` code is meant to either be untrusted itself, or to be trusted
code running operations that might be dangerous (such as mounting a
user-provided image).

By default, all new OS definitions will have to be explicitly marked as trusted
by the cluster administrator (with a new ``gnt-os modify`` command) before they
can run code on the host. Otherwise, only the untrusted part of the code will be
allowed to run, inside the virtual appliance. For backwards compatibility
reasons, when upgrading an existing cluster, all the installed OSes will be
marked as trusted, so that they can keep running with no changes.

In order to allow for the highest flexibility, if both a trusted and an
untrusted script are provided for the same operation (i.e. ``create``), both of
them will be executed at the same time, one on the host, and one inside the
installation appliance. They will be allowed to communicate with each other
through the already described communication mechanism, in order to orchestrate
their execution (e.g.: the untrusted code might execute the installation, while
the trusted one receives status updates from it and delivers them to a user
interface).

The cluster administrator will have an option to completely disable scripts
running on the host, leaving only the ones running in the VM.

Ganeti will provide a script to be run at install time that can be used to
create the virtualized environment that will perform the OS installation of new
instances.
This script will build a debootstrapped basic Debian system including a software
that will read the metadata, setup the environment variables and launch the
installation scripts inside the virtualized environment. The script will also
provide hooks for personalization.

It will also be possible to use other self-made virtualized environments, as
long as they connect to Ganeti over the described communication mechanism and
they know how to read and use the provided metadata to create a new instance.

While performing an installation in the virtualized environment, a customizable
timeout will be used to detect possible problems with the installation process,
and to kill the virtualized environment. The timeout will be optional and set on
a cluster basis by the administrator. If set, it will be the total time allowed
to setup an instance inside the appliance. It is mainly meant as a safety
measure to prevent an instance taken over by malicious scripts to be available
for a long time.

Alternatives to design and implementation
=========================================

This section lists alternatives to design and implementation, which came up
during the development of this design document, that will not be implemented.
Please read carefully through the limitations and security concerns of each of
these alternatives.

Port forwarding in KVM
++++++++++++++++++++++

The communication mechanism could have been implemented in KVM using guest port
forwarding, as opposed to network interfaces.  There are two alternatives in
KVM's guest port forwarding, namely, creating a forwarding device, such as, a
TCP/IP connection, or executing a command.  However, we have determined that
both of these options are not viable.

A TCP/IP forwarding device can be created through the following KVM invocation::

  kvm -net nic -net \
    user,restrict=on,net=169.254.0.0/16,host=169.254.169.253,
    guestfwd=tcp:169.254.169.254:80-tcp:127.0.0.1:8080 ...

This invocation even has the advantage that it can block undesired traffic
(i.e., traffic that is not explicitly specified in the arguments) and it can
remap ports, which would have allowed the metadata service daemon to run in port
8080 instead of 80.  However, in this scheme, KVM opens the TCP connection only
once, when it is started, and, if the connection breaks, KVM will not
reestablish the connection.  Furthermore, opening the TCP connection only once
interferes with the HTTP protocol, which needs to dynamically establish and
close connections.

The alternative to the TCP/IP forwarding device is to execute a command.  The
KVM invocation for this is, for example, the following::

  kvm -net nic -net \
    "user,restrict=on,net=169.254.0.0/16,host=169.254.169.253,
    guestfwd=tcp:169.254.169.254:80-netcat 127.0.0.1 8080" ...

The advantage of this approach is that the command is executed each time the
guest initiates a connection.  This is the ideal situation, however, it is only
supported in KVM 1.2 and above, and, therefore, not viable because we want to
provide support for at least KVM version 1.0, which is the version provided by
Ubuntu LTS.

Alternatives to the DHCP server
+++++++++++++++++++++++++++++++

There are alternatives to using the DHCP server, for example, by assigning a
fixed IP address to guests, such as, the IP address ``169.254.169.253``.
However, this introduces a routing problem, namely, how to route incoming
packets from the same source IP to the host.  This problem can be overcome in a
number of ways.

The first solution is to use NAT to translate the incoming guest IP address, for
example, ``169.254.169.253``, to a unique IP address, for example,
``169.254.0.1``.  Given that NAT through ``ip rule`` is deprecated, users can
resort to ``iptables``.  Note that this has not yet been tested.

Another option, which has been tested, but only in a prototype, is to connect
the TAP network interfaces of the guests to a bridge.  The bridge takes the
configuration from the TAP network interfaces, namely, IP address
``169.254.169.254`` and netmask ``255.255.255.255``, thus leaving those
interfaces without an IP address.  Note that in this setting, guests will be
able to reach each other, therefore, if necessary, additional ``iptables`` rules
can be put in place to prevent it.
