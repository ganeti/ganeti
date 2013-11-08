================================================
Design for supporting custom SSH ports for nodes
================================================

.. contents:: :depth: 4

This design document describes the intention of supporting running SSH servers
on nodes with non-standard port numbers.


Current state and shortcomings
==============================

All SSH deamons are expected to be running on the default port 22. It has been
requested by Ganeti users (`Issue 235`_) to allow SSH daemons run on
non-standard ports as well.

.. _`Issue 235`: https://code.google.com/p/ganeti/issues/detail?id=235


Proposed Changes
================

Allow users to configure groups with custom SSH ports. All nodes in such a
group will then be using its configured SSH port.

The configuration will be on the group level only as we expect all nodes in a group
to have identical configurations.

Users will be responsible for configuring the SSH daemons on machines before
adding them as nodes to a group with a non-standard port number, or when
modifying the port number of an existing group. Ganeti will not update SSH
configuration by itself.


Implementation Details
======================

We must ensure that all operations that use SSH will use custom ports as configured. This includes:

- gnt-cluster verify
- gnt-cluster renew-crypto
- gnt-cluster upgrade
- gnt-node add
- gnt-instance console

Configuration Changes
~~~~~~~~~~~~~~~~~~~~~

The node group *ndparams* will get an additional integer valued parameter *ssh_port*.

Upgrades/downgrades
~~~~~~~~~~~~~~~~~~~

To/from version 2.10
--------------------

During upgrade from 2.10, the default value 22 will be supplemented.

During downgrade to 2.10 the downgrading script will check that there are no
configured ports other than 22 (because this would result in a broken cluster)
and then will remove the corresponding key/value pairs from the configuration.

Future versions
---------------

For future versions the up/downgrade operation will need to know the configured
SSH ports. Because all daemons are stopped during the process, it will be
necessary to include SSH ports in *ssconf*.
