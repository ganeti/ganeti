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

OS Parameters
+++++++++++++

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

In order to avoid this we plan to make OSes more customizable, by allowing
arbitrary flags to be passed to them. These will be special "OS parameters"
which will be handled by Ganeti mostly as hypervisor or be parameters. This
slightly complicates the interface, but allows one OS (for example
"debootstrap" to be customizable and not require copies to perform different
cations).

Each OS will be able to declare which parameters it supports by listing them
one per line in a special "parameters" file in the OS dir. The parameters can
have a per-os cluster default, or be specified at instance creation time.  They
will then be passed to the OS scripts as: INSTANCE_OS_PARAMETER_<NAME> with
their specified value. The only value checking that will be performed is that
the os parameter value is a string, with only "normal" characters in it.

It will be impossible to change parameters for an instance, except at reinstall
time. Upon reinstall with a different OS the parameters will be by default
discarded and reset to the default (or passed) values, unless a special
--keep-known-os-parameters flag is passed.

