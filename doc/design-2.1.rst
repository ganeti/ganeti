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

