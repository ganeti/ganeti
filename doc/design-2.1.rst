=================
Ganeti 2.1 design
=================

This document describes the major changes in Ganeti 2.1 compared to
the 2.0 version.

The 2.1 version will be a relatively small release. Its main aim is to avoid
changing too much of the core code, while addressing issues and adding new
features and improvements over 2.0, in a timely fashion.

.. contents:: :depth: 3

Objective
=========

Ganeti 2.1 will add features to help further automatization of cluster
operations, further improbe scalability to even bigger clusters, and make it
easier to debug the Ganeti core.

Background
==========

Overview
========

Detailed design
===============

As for 2.0 we divide the 2.1 design into three areas:

- core changes, which affect the master daemon/job queue/locking or all/most
  logical units
- logical unit/feature changes
- external interface changes (eg. command line, os api, hooks, ...)

Core changes
------------

Feature changes
---------------

Redistribute Config
~~~~~~~~~~~~~~~~~~~

Current State and shortcomings
++++++++++++++++++++++++++++++
Currently LURedistributeConfig triggers a copy of the updated configuration
file to all master candidates and of the ssconf files to all nodes. There are
other files which are maintained manually but which are important to keep in
sync. These are:

- rapi SSL key certificate file (rapi.pem) (on master candidates)
- rapi user/password file rapi_users (on master candidates)

Furthermore there are some files which are hypervisor specific but we may want
to keep in sync:

- the xen-hvm hypervisor uses one shared file for all vnc passwords, and copies
  the file once, during node add. This design is subject to revision to be able
  to have different passwords for different groups of instances via the use of
  hypervisor parameters, and to allow xen-hvm and kvm to use an equal system to
  provide password-protected vnc sessions. In general, though, it would be
  useful if the vnc password files were copied as well, to avoid unwanted vnc
  password changes on instance failover/migrate.

Optionally the admin may want to also ship files such as the global xend.conf
file, and the network scripts to all nodes.

Proposed changes
++++++++++++++++

RedistributeConfig will be changed to copy also the rapi files, and to call
every enabled hypervisor asking for a list of additional files to copy. We also
may want to add a global list of files on the cluster object, which will be
propagated as well, or a hook to calculate them. If we implement this feature
there should be a way to specify whether a file must be shipped to all nodes or
just master candidates.

This code will be also shared (via tasklets or by other means, if tasklets are
not ready for 2.1) with the AddNode and SetNodeParams LUs (so that the relevant
files will be automatically shipped to new master candidates as they are set).

VNC Console Password
~~~~~~~~~~~~~~~~~~~~

Current State and shortcomings
++++++++++++++++++++++++++++++

Currently just the xen-hvm hypervisor supports setting a password to connect
the the instances' VNC console, and has one common password stored in a file.

This doesn't allow different passwords for different instances/groups of
instances, and makes it necessary to remember to copy the file around the
cluster when the password changes.

Proposed changes
++++++++++++++++

We'll change the VNC password file to a vnc_password_file hypervisor parameter.
This way it can have a cluster default, but also a different value for each
instance. The VNC enabled hypervisors (xen and kvm) will publish all the
password files in use through the cluster so that a redistribute-config will
ship them to all nodes (see the Redistribute Config proposed changes above).

The current VNC_PASSWORD_FILE constant will be removed, but its value will be
used as the default HV_VNC_PASSWORD_FILE value, thus retaining backwards
compatibility with 2.0.

The code to export the list of VNC password files from the hypervisors to
RedistributeConfig will be shared between the KVM and xen-hvm hypervisors.

Disk/Net parameters
~~~~~~~~~~~~~~~~~~~

Current State and shortcomings
++++++++++++++++++++++++++++++

Currently disks and network interfaces have a few tweakable options and all the
rest is left to a default we chose. We're finding that we need more and more to
tweak some of these parameters, for example to disable barriers for DRBD
devices, or allow striping for the LVM volumes.

Moreover for many of these parameters it will be nice to have cluster-wide
defaults, and then be able to change them per disk/interface.

Proposed changes
++++++++++++++++

We will add new cluster level diskparams and netparams, which will contain all
the tweakable parameters. All values which have a sensible cluster-wide default
will go into this new structure while parameters which have unique values will not.

Example of network parameters:
  - mode: bridge/route
  - link: for mode "bridge" the bridge to connect to, for mode route it can
    contain the routing table, or the destination interface

Example of disk parameters:
  - stripe: lvm stripes
  - stripe_size: lvm stripe size
  - meta_flushes: drbd, enable/disable metadata "barriers"
  - data_flushes: drbd, enable/disable data "barriers"

Some parameters are bound to be disk-type specific (drbd, vs lvm, vs files) or
hypervisor specific (nic models for example), but for now they will all live in
the same structure. Each component is supposed to validate only the parameters
it knows about, and ganeti itself will make sure that no "globally unknown"
parameters are added, and that no parameters have overridden meanings for
different components.

The parameters will be kept, as for the BEPARAMS into a "default" category,
which will allow us to expand on by creating instance "classes" in the future.
Instance classes is not a feature we plan implementing in 2.1, though.

Non bridged instances support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Current State and shortcomings
++++++++++++++++++++++++++++++

Currently each instance NIC must be connected to a bridge, and if the bridge is
not specified the default cluster one is used. This makes it impossible to use
the vif-route xen network scripts, or other alternative mechanisms that don't
need a bridge to work.

Proposed changes
++++++++++++++++

The new "mode" network parameter will distinguish between bridged interfaces
and routed ones.

When mode is "bridge" the "link" parameter will contain the bridge the instance
should be connected to, effectively making things as today. The value has been
migrated from a nic field to a parameter to allow for an easier manipulation of
the cluster default.

When mode is "route" the ip field of the interface will become mandatory, to
allow for a route to be set. In the future we may want also to accept multiple
IPs or IP/mask values for this purpose. We will evaluate possible meanings of
the link parameter to signify a routing table to be used, which would allow for
insulation between instance groups (as today happens for different bridges).

For now we won't add a parameter to specify which network script gets called
for which instance, so in a mixed cluster the network script must be able to
handle both cases. The default kvm vif script will be changed to do so. (Xen
doesn't have a ganeti provided script, so nothing will be done for that
hypervisor)

External interface changes
--------------------------

OS API
~~~~~~

The OS API of Ganeti 2.0 has been built with extensibility in mind. Since we
pass everything as environment variables it's a lot easier to send new
information to the OSes without breaking retrocompatibility. This section of
the design outlines the proposed extensions to the API and their
implementation.

API Version Compatibility Handling
++++++++++++++++++++++++++++++++++

In 2.1 there will be a new OS API version (eg. 15), which should be mostly
compatible with api 10, except for some new added variables. Since it's easy
not to pass some variables we'll be able to handle Ganeti 2.0 OSes by just
filtering out the newly added piece of information. We will still encourage
OSes to declare support for the new API after checking that the new variables
don't provide any conflict for them, and we will drop api 10 support after
ganeti 2.1 has released.

New Environment variables
+++++++++++++++++++++++++

Some variables have never been added to the OS api but would definitely be
useful for the OSes. We plan to add an INSTANCE_HYPERVISOR variable to allow
the OS to make changes relevant to the virtualization the instance is going to
use. Since this field is immutable for each instance, the os can tight the
install without caring of making sure the instance can run under any
virtualization technology.

We also want the OS to know the particular hypervisor parameters, to be able to
customize the install even more.  Since the parameters can change, though, we
will pass them only as an "FYI": if an OS ties some instance functionality to
the value of a particular hypervisor parameter manual changes or a reinstall
may be needed to adapt the instance to the new environment. This is not a
regression as of today, because even if the OSes are left blind about this
information, sometimes they still need to make compromises and cannot satisfy
all possible parameter values.

OS Flavours
+++++++++++

Currently we are assisting to some degree of "os proliferation" just to change
a simple installation behavior. This means that the same OS gets installed on
the cluster multiple times, with different names, to customize just one
installation behavior. Usually such OSes try to share as much as possible
through symlinks, but this still causes complications on the user side,
especially when multiple parameters must be cross-matched.

For example today if you want to install debian etch, lenny or squeeze you
probably need to install the debootstrap OS multiple times, changing its
configuration file, and calling it debootstrap-etch, debootstrap-lenny or
debootstrap-squeeze. Furthermore if you have for example a "server" and a
"development" environment which installs different packages/configuration files
and must be available for all installs you'll probably end  up with
deboostrap-etch-server, debootstrap-etch-dev, debootrap-lenny-server,
debootstrap-lenny-dev, etc. Crossing more than two parameters quickly becomes
not manageable.

In order to avoid this we plan to make OSes more customizable, by allowing each
OS to declare a list of flavours which can be used to customize it. The
flavours list is mandatory for new API OSes and must contain at least one
supported flavour. When choosing the OS exactly one flavour will have to be
specified, and will be encoded in the os name as <OS-name>+<flavour>. As for
today it will be possible to change an instance's OS at creation or install
time.

The 2.1 OS list will be the combination of each OS, plus its supported
flavours. This will cause the name name proliferation to remain, but at least
the internal OS code will be simplified to just parsing the passed flavour,
without the need for symlinks or code duplication.

Also we expect the OSes to declare only "interesting" flavours, but to accept
some non-declared ones which a user will be able to pass in by overriding the
checks ganeti does. This will be useful for allowing some variations to be used
without polluting the OS list (per-OS documentation should list all supported
flavours). If a flavour which is not internally supported is forced through,
the OS scripts should abort.

In the future (post 2.1) we may want to move to full fledged orthogonal
parameters for the OSes. In this case we envision the flavours to be moved
inside of Ganeti and be associated with lists parameter->values associations,
which will then be passed to the OS.

IAllocator changes
~~~~~~~~~~~~~~~~~~

Current State and shortcomings
++++++++++++++++++++++++++++++

The iallocator interface allows creation of instances without manually
specifying nodes, but instead by specifying plugins which will do the
required computations and produce a valid node list.

However, the interface is quite akward to use:

- one cannot set a 'default' iallocator script
- one cannot use it to easily test if allocation would succeed
- some new functionality, such as rebalancing clusters and calculating
  capacity estimates is needed

Proposed changes
++++++++++++++++

There are two area of improvements proposed:

- improving the use of the current interface
- extending the IAllocator API to cover more automation


Default iallocator names
^^^^^^^^^^^^^^^^^^^^^^^^

The cluster will hold, for each type of iallocator, a (possibly empty)
list of modules that will be used automatically.

If the list is empty, the behaviour will remain the same.

If the list has one entry, then ganeti will behave as if
'--iallocator' was specifyed on the command line. I.e. use this
allocator by default. If the user however passed nodes, those will be
used in preference.

If the list has multiple entries, they will be tried in order until
one gives a successful answer.

Dry-run allocation
^^^^^^^^^^^^^^^^^^

The create instance LU will get a new 'dry-run' option that will just
simulate the placement, and return the chosen node-lists after running
all the usual checks.

Cluster balancing
^^^^^^^^^^^^^^^^^

Instance add/removals/moves can create a situation where load on the
nodes is not spread equally. For this, a new iallocator mode will be
implemented called ``balance`` in which the plugin, given the current
cluster state, and a maximum number of operations, will need to
compute the instance relocations needed in order to achieve a "better"
(for whatever the script believes it's better) cluster.

Cluster capacity calculation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In this mode, called ``capacity``, given an instance specification and
the current cluster state (similar to the ``allocate`` mode), the
plugin needs to return:

- how many instances can be allocated on the cluster with that specification
- on which nodes these will be allocated (in order)
