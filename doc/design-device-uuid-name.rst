==========================================
Design for adding UUID and name to devices
==========================================

.. contents:: :depth: 4

This is a design document about adding UUID and name to instance devices
(Disks/NICs) and the ability to reference them by those identifiers.


Current state and shortcomings
==============================

Currently, the only way to refer to a device (Disk/NIC) is by its index
inside the VM (e.g. gnt-instance modify --disk 2:remove).

Using indices as identifiers has the drawback that addition/removal of a
device results in changing the identifiers(indices) of other devices and
makes the net effect of commands depend on their strict ordering. A
device reference is not absolute, meaning an external entity controlling
Ganeti, e.g., over RAPI, cannot keep permanent identifiers for referring
to devices, nor can it have more than one outstanding commands, since
their order of execution is not guaranteed.


Proposed Changes
================

To be able to reference a device in a unique way, we propose to extend
Disks and NICs by assigning to them a UUID and a name. The UUID will be
assigned by Ganeti upon creation, while the name will be an optional
user parameter. Renaming a device will also be supported.

Commands (e.g. `gnt-instance modify`) will be able to reference each
device by its index, UUID, or name. To be able to refer to devices by
name, we must guarantee that device names are unique. Unlike other
objects (instances, networks, nodegroups, etc.), NIC and Disk objects
will not have unique names across the cluster, since they are still not
independent entities, but rather part of the instance object. This makes
global uniqueness of names hard to achieve at this point. Instead their
names will be unique at instance level.

Apart from unique device names, we must also guarantee that a device
name can not be the UUID of another device. Also, to remove ambiguity
while supporting both indices and names as identifiers, we forbid purely
numeric device names.


Implementation Details
======================

Modify OpInstanceSetParams to accept not only indexes, but also device
names and UUIDs. So, the accepted NIC and disk modifications will have
the following format:

identifier:action,key=value

where, from now on, identifier can be an index (-1 for the last device),
UUID, or name and action should be add, modify, or remove.

Configuration Changes
~~~~~~~~~~~~~~~~~~~~~

Disk and NIC config objects get two extra slots:

- uuid
- name

Instance Queries
~~~~~~~~~~~~~~~~~

We will extend the query mechanism to expose names and UUIDs of NICs and
Disks.

Hook Variables
~~~~~~~~~~~~~~

We will expose the name of NICs and Disks to the hook environment of
instance-related operations:

``INSTANCE_NIC%d_NAME``
``INSTANCE_DISK%d_NAME``

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
