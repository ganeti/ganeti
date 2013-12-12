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
definition is a set of scripts (``create``, ``export``, ``import``, ``rename``)
that are executed with root privileges on the primary host of the instance to
perform all the OS-related functionality (setting up an operating system inside
the disks of the instance being created, exporting/importing the instance,
renaming it).

These scripts receive, as environment variables, a fixed set of parameters
related to the instance (such as the hypervisor, the name of the instance, the
number of disks, and their location) and a set of user defined parameters.
These parameters are also written in the configuration file of Ganeti, to allow
future reinstalls of the instance, and in various log files, namely:

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

* Having the installation scripts run as root on the nodes doesn't allow
  user-defined OS scripts, as they would pose a huge security issue.
  Furthermore, even a script without malicious intentions might end up
  distrupting a node because of a bug in it.

* Ganeti cannot be used to create instances starting from user provided disk
  images: even in the (hypothetical) case where the scripts are completely
  secure and run not by root but by an unprivileged user with only the power to
  mount arbitrary files as disk images, this is a security issue. It has been
  proven that a carefully crafted file system might exploit kernel
  vulnerabilities to gain control of the system. Therefore, directly mounting
  images on the Ganeti nodes is not an option.

* There is no way to inject files into an existing disk image. A common use case
  is for the system administrator to provide a standard image of the system, to
  be later personalized with the network configuration, private keys identifying
  the machine, ssh keys of the users and so on. A possible workaround would be
  for the scripts to mount the image (only if this is trusted!) and to receive
  the configurations and ssh keys as user defined OS parameters. Unfortunately,
  this is also not an option for security sensitive material (such as the ssh
  keys) because the OS parameters are stored in many places on the system, as
  already described above.

* Most other virtualization software simply work with instance images, not with
  installation scripts. This difference makes the interaction of Ganeti with
  other software difficult.

Proposed changes
================

In order to fix the shortcomings of the current state, we plan to introduce the
following changes:

* Change the OS parameters to have three categories:

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
   serialized. As a result, the job cannot be taken over by the new master.
   This is an expected and accepted side effect of jobs with secret parameters:
   if they fail, they'll have to be restarted manually.

* A new OS installation procedure, based on a safe virtualized environment.
  This virtualized environment will run with the same hardware parameter as the
  actual instance being installed, as much as possible. This will also allow to
  reduce the memory usage in the host (specifically, in Dom0 for Xen
  installations). Each instance will have these possible execution modes:

  * ``run``: the default mode, used when the machine is running normally and
    the OS installation procedure is run before starting the instance for the
    first time.

  * ``self_install``: the first run of the instance will be with a different set
    of parameters w.r.t. all the successive runs. This set of "install
    parameters" will allow, e.g., to attach an installation
    floppy/cdrom/network, change the boot device order, or specify an OS image
    to be used. Through this set of parameters, the administrator will have to
    provide the hypervisor a way to find an installation medium for the instance
    (e.g., a boot disk, a network image, etc). This medium will then install the
    instance itself on the disks and will then be responsible to get the
    parameters for configuring it (its network interfaces, IP address, hostname,
    etc.) from a set of metadata provided by Ganeti (e.g.: using an approach
    comparable to the one of the ``cloud-init`` tool). When this installation
    mode is used, no OS installation script is required.  In order for the
    installation of an OS from an image to be possible, the ``--os-type``
    parameter will be extended to support a new additional format: ``--os-type
    image:<URL>`` will instruct Ganeti to take an image from the specified
    position. For the initial implementation, URL can be either a filename or a
    publically accessible HTTP or FTP resource. Once the instance image is
    received, it will be dd-ed onto the first disk of the instance.  When an
    image is specified, ``--os-parameters`` can still be used, and its content
    will be passed to the instance as part of the metadata. Note that, as part
    of the OS scripts, there is a file specifying what parameters are
    expected. With OS images, though, none of the traditional structure of OS
    scripts is in place, so there will be no check regarding what parameters can
    be specified: they will all be passed, as long as the ``--os-parameters``
    string is syntactically valid.  The set of ``self_install`` parameters will
    be stored as part of the instance configuration, so that they can be used to
    reinstall the instance.  It will be the user's responsibility to ensure that
    the OS image or any installation media is still available in the proper
    position when a reinstall happens. After the first run, the instance will
    revert to ``run`` mode.

  * ``install``: Ganeti will start the instance using a virtual appliance
    specifically made for installing Ganeti instances. Scripts analogous to the
    current ones will run inside this instance. The disks of the instance being
    installed will be connected to this virtual appliance, so that the scripts
    can mount them and modify them as needed, as currently happens, but with the
    additional protection given by this happening in a VM. The disk of the
    virtual appliance will be read only, so that a pristine copy of the
    appliance can be started every time a new instance needs to be created, to
    further increase security. The data the instance needs to write at runtime
    will only be stored in RAM, and disappear as soon as the instance is
    stopped. Metadata will be provided also to this virtual applicance, that
    will take care of converting them to environment variables for the
    installation scripts. After the first run, the instance will revert to
    ``run`` mode.

* In order to allow for the metadata to be sent inside the instance, a
  communication mechanism between the instance and the host will be created.
  This mechanism will be bidirectional (e.g.: to allow the setup process going
  on inside the instance to communicate its progress to the host). Each instance
  will have access exclusively to its own metadata, and it will be only able to
  communicate with its host over this channel. More details will be provided in
  the `Communication mechanism and metadata service`_ section.

* As part of the instance creation command it will be possible to indicate a URL
  for a "personalization package", that is an archive containing a set of files
  meant to be overlayed on top of the operating system file system at the end of
  the setup process, before the VM is started for the first time in ``run``
  mode.  Ganeti will provide a mechanism for receiving and unpacking this
  archive as part of the ``install`` execution mode, whereas in ``self_install``
  mode it will only be provided as a metadata for the instance to use.  The
  archive will be in TAR-GZIP format (with extension ``.tar.gz`` or ``.tgz``)
  and will contain the files according to the directory structure that will be
  recreated on the installation disk. Files contained in this archive will
  overwrite files with the same path created during the install procedure (if
  any).  The URL of the "personalization package" will have to specify an
  extesion to identify the file format (in order to allow for more formats to be
  supported in the future).  The URL will be stored as part of the configuration
  of the instance (therefore, the URL should not contain confidential
  information, but the files there available can). It is up to the system
  administrator to ensure that a package is actually available at that URL at
  install and reinstall time.  The content of the package is allowed to change.
  E.g.: a system administrator might create a package containing the private
  keys of the instance being created. When the instance is reinstalled, a new
  package with new keys can be made available there, therefore allowing instance
  reinstall without the need to store keys.  Together with the URL, a username
  and a password can be specified to. If the URL is a HTTP(S) URL, they will be
  used as basic access authentication credentials to access that URL. The
  username and password will not be saved in the config, and will have to be
  provided again in case a reinstall is requested.  The downloaded
  personalization package will not be stored locally on the node for longer than
  it is needed while unpacking it and adding its files to the instance being
  created.  The personalization package will be overlayed on top of the instance
  filesystem after the scripts that created it have been executed.  In order for
  the files in the package to be automatically overlayed on top of the instance
  filesystem it is required that the appliance is actually able to mount the
  instance disks, therefore this will not work for every filesystem.

Implementation
==============

The implementation of this design will happen as an ordered sequence of steps,
of increasing impact on the system and, in some cases, dependent on each other:

#. Private and secret instance parameters
#. Communication mechanism between host and instance
#. Metadata service
#. Personalization package (inside a virtualization environment)
#. ``self_install`` mode
#. ``install`` mode (inside a virtualization environment)

Some of these steps need to be more deeply specified w.r.t. what is already
written in the `Proposed changes`_ Section. Extra details will be provided in
the following subsections.

Communication mechanism and metadata service
++++++++++++++++++++++++++++++++++++++++++++

The communication mechanism and the metadata service are described together
because they are deeply tied. On the other hand, the communication mechanism
will need to be more generic because it can be used for other reasons in the
future (like allowing instances to explicitly send commands to Ganeti, or to let
Ganeti control a helper instance, like the one hereby introduced for performing
OS installs inside a safe environment).

The communication mechanism will be enabled automatically when the instance is
in ``self_install`` or ``install`` mode, but for backwards compatibility it will
be disabled when the instance is in ``run`` mode unless it is explicitly
requested. Specifically, a new parameter ``--communication`` (short version:
``-C``), with possible values ``true`` or ``false`` will be added to
``gnt-instance add`` and ``gnt-instance modify``. It will determine whether the
instance will have a communication channel set up to interact with the host and
to receive metadata. The value of this parameter will be saved as part of the
configuration of the instance.

When the communication mechanism is enabled, Ganeti will create a new network
interface inside the instance. This additional network interface will be the
last one in the instance, after all the user defined ones. On the host side,
this interface will only be accessible to the host itself, and not routed
outside the machine.
On this network interface, the instance will connect using the IP:
169.254.169.253 and netmask 255.255.255.0.
The host will be on the same network, with the IP address: 169.254.169.254.

The way to create this interface depends on the specific hypervisor being used.
In KVM, it is possible to create a network interface inside the instance without
having a corresponding interface created on the host. Using a command like::

  kvm -net nic -net \
    user,restrict=on,net=169.254.169.0/24,host=169.254.169.253,
    guestfwd=tcp:169.254.169.254:80-tcp:127.0.0.1:8080

a network interface will be created inside the VM, part of the 169.254.169.0/24
network, where the VM will have IP address .253 and the host port 8080 will be
reachable on port 80.

In Xen, unfortunately, such a capability is not present, and an actual network
interface has to be created on the host (using the ``vif`` parameter of the Xen
configuration file). Each instance will have its corresponding ``vif`` network
interface on the host. These interfaces will not be connected to each other in
any way, and Ganeti will not configure them to allow traffic to be forwarded
beyond the host machine. The ``vif-route`` script of Xen might be helpful in
implementing this.
It will be the system administrator's responsibility to ensure that the extra
firewalling and routing rules specified on the host don't allow this
accidentally.

The instance will be able to connect to 169.254.169.254:80, and issue GET
requests to an HTTP server that will provide the instance metadata.

The choice of this IP address and port for accessing the metadata is done for
compatibility reasons with OpenStack's and Amazon EC2's ways of providing
metadata to the instance. The metadata will be provided by a single daemon,
which will determine what instance the request comes from and reply with the
metadata specific for that instance.

Where possible, the metadata will be provided in a way compatible with Amazon
EC2, at::

  http://169.254.169.254/<version>/meta-data/*

If some metadata are Ganeti-specific and don't fit this structure, they will be
provided at::

  http://169.254.169.254/ganeti/<version>/meta_data.json

``<version>`` is either a date in YYYY-MM-DD format, or ``latest`` to indicate
the most recent available protocol version.

If needed in the future, this structure also allows us to support OpenStack's
metadata at::

  http://169.254.169.254/openstack/<version>/meta_data.json

A bi-directional, pipe-like communication channel will be provided. The instance
will be able to receive data from the host by a GET request at::

  http://169.254.169.254/ganeti/<version>/read

and to send data to the host by a POST request at::

  http://169.254.169.254/ganeti/<version>/write

As in a pipe, once the data are read, they will not be in the buffer anymore, so
subsequent GET requests to ``read`` will not return the same data twice.
Unlike a pipe, though, it will not be possible to perform blocking I/O
operations.

The OS parameters will be accessible through a GET
request at::

  http://169.254.169.254/ganeti/<version>/os/parameters.json

as a JSON serialized dictionary having the parameter name as the key, and the
pair ``(<value>, <visibility>)`` as the value, where ``<value>`` is the
user-provided value of the parameter, and ``<visibility>`` is either ``public``,
``private`` or ``secret``.

The installation scripts to be run inside the virtualized environment while the
instance is run in ``install`` mode will be available at::

  http://169.254.169.254/<version>/ganeti/os/scripts/<script_name>

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
This script will build a debootstrapped basic debian system including a software
that will read the metadata, setup the environment variables and launch the
installation scripts inside the virtualized environment. The script will also
provide hooks for personalization.

It will also be possible to use other self-made virtualized environments, as
long as they connect to Ganeti over the described communication mechanism and
they know how to read and use the provided metadata to create a new instance.

While performing an installation in the virtualized environment, a
personalizable timeout will be used to detect possible problems with the
installation process, and to kill the virtualized environment. The timeout will
be optional and set on a cluster basis by the administrator. If set, it will be
the total time allowed to setup an instance inside the appliance. It is mainly
meant as a safety measure to prevent an instance taken over by malicious scripts
to be available for a long time.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
