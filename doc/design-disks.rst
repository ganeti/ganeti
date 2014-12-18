=====
Disks
=====

.. contents:: :depth: 4

This is a design document detailing the implementation of disks as a new
top-level citizen in the config file (just like instances, nodes etc).


Current state and shortcomings
==============================

Currently, Disks are stored in Ganeti's config file as a list
(container) of Disk objects under the Instance in which they belong.
This implementation imposes a number of limitations:

* A Disk object cannot live outside an Instance. This means that one
  cannot detach a disk from an instance (without destroying the disk)
  and then reattach it (to the same or even to a different instance).

* Disks are not taggable objects, as only top-level citizens of the
  config file can be made taggable. Having taggable disks will allow for
  further customizations.

* All disks of an instance have to be of the same template. Dropping
  this constraint would allow mixing different kinds of storage (e.g. an
  instance might have a local ``plain`` storage for the OS and a
  remotely replicated ``sharedstorage`` for the data).


Proposed changes
================

The implementation is going to be split in four parts:

* Make disks a top-level citizen in config file. The Instance object
  will no longer contain a list of Disk objects, but a list of disk
  UUIDs.

* Add locks for Disk objects and make them taggable.

* Allow to attach/detach an existing disk to/from an instance.

* Allow creation/modification/deletion of disks that are not attached to
  any instance (requires new LUs for disks).

* Allow disks of a single instance to be of different templates.

* Remove all unnecessary distinction between disk templates and disk
  types.


Design decisions
================

Disks as config top-level citizens
----------------------------------

The first patch-series is going to add a new top-level citizen in the
config object (namely ``disks``) and separate the disk objects from the
instances. In doing so there are a number of problems that we have to
overcome:

* How the Disk object will be represented in the config file and how it
  is going to be connected with the instance it belongs to.

* How the existing code will get the disks belonging to an instance.

* What it means for a disk to be attached/detached to/from an instance.

* How disks are going to be created/deleted, attached/detached using
  the existing code.


Disk representation
~~~~~~~~~~~~~~~~~~~

The ``Disk`` object gets two extra slots, ``_TIMESTAMPS`` and
``serial_no``.

The ``Instance`` object will no longer contain the list of disk objects
that are attached to it or a disk template.
Instead, an Instance object will refer to its
disks using their UUIDs and the disks will contain their own template.
Since the order in which the disks are attached
to an instance is important we are going to have a list of disk UUIDs
under the Instance object which will denote the disks attached to the
instance and their order at the same time. So the Instance's ``disks``
slot is going to be a list of disk UUIDs. The `Disk` object is not going
to have a slot pointing to the `Instance` in which it belongs since this
is redundant.


Get instance's disks
~~~~~~~~~~~~~~~~~~~~

A new function ``GetInstanceDisks`` will be added to the config that given an
instance will return a list of Disk objects with the disks attached to this
instance. This list will be exactly the same as 'instance.disks' was before.
Everywhere in the code we are going to replace the 'instance.disks' (which from
now one will contain a list of disk UUIDs) with the function
``GetInstanceDisks``.

Since disks will not be part of the `Instance` object any more, 'all_nodes' and
'secondary_nodes' can not be `Instance`'s properties. Instead we will use the
functions ``GetInstanceNodes`` and ``GetInstanceSecondaryNodes`` from the
config to compute these values.


Configuration changes
~~~~~~~~~~~~~~~~~~~~~

The ``ConfigData`` object gets one extra slot: ``disks``. Also there
will be two new functions, ``AddDisk`` and ``RemoveDisk`` that will
create/remove a disk objects from the config.

The ``VerifyConfig`` function will be changed so it can check that there
are no dangling pointers from instances to disks (i.e. an instance
points to a disk that doesn't exist in the config).

The 'upgrade' operation for the config should check if disks are top level
citizens and if not it has to extract the disk objects from the instances,
replace them with their uuids, and copy the disk template. In case of the 'downgrade' operation (where
disks will be made again part of the `Instance` object) all disks that are not
attached to any instance at all will be ignored (removed from config).
The disk template of the
instance is set to the disk template of any disk attached to it. If
there are multiple disk templates present, the downgrade fails and the
user is requested to detach disks from the instances.


Apply Disk modifications
~~~~~~~~~~~~~~~~~~~~~~~~

There are four operations that can be performed to a `Disk` object:

* Create a new `Disk` object of a given template and save it to the
  config.

* Remove an existing `Disk` object from the config.

* Attach an existing `Disk` to an existing `Instance`.

* Detach an existing `Disk` from an existing `Instance`.

The first two operations will be performed using the config functions
``AddDisk`` and ``RemoveDisk`` respectively where the last two operations
will be performed using the functions ``AttachInstanceDisk`` and
``DetachInstanceDisk``.

More specifically, the `add` operation will add and attach a disk at the same
time, using a wrapper that calls the ``AddDisk`` and ``AttachInstanceDisk``
functions. On the same vein, the `remove` operation will detach and remove a
disk using a wrapper that calls the ``DetachInstanceDisk`` and
``RemoveInstanceDisk``. The `attach` and `detach` operations are simpler, in
the sense that they only call the ``AttachInstanceDisk`` and
``DetachInstanceDisk`` functions respectively.

It is important to note that the `detach` operation introduces the notion of
disks that are not attached to any instance. For this reason, the configuration
checks for detached disks will be removed, as the detached disks can be handled
by the code.

In addition since Ganeti doesn't allow for a `Disk` object to be attached to
more than one `Instance` at once, when attaching a disk to an instance we have
to make sure that the disk is not attached anywhere else.


Backend changes
~~~~~~~~~~~~~~~

The backend needs access to the disks of an `Instance` but doesn't have access to
the `GetInstanceDisks` function from the config file. Thus we will create a new
`Instance` slot (namely ``disks_info``) that will get annotated (during RPC)
with the instance's disk objects. So in the backend we will only have to
replace the ``disks`` slot with ``disks_info``.


Supporting the old interface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The current interface is designed with a uniform disk type in mind and
this interface should still be supported to not break tools and
workflows downstream.

The behaviour is fully compatible for instances with constantly
attached, uniform disks.

Whenever an operation operates on an instance, the operation will only
consider the disks attached. If the operation is specific to a disk
type, it will throw an error if any disks of a type not supported are
attached.

When setting the disk template of an instance, we convert all currently
attached disks to that template. This means that all disk types
currently attached must be convertible to the new template.

Since the disk template as a configuration value is going away, it needs
to be replaced for queries. If the instance has no disks, the
disk_template will be 'diskless', if it has disks of a single type, its
disk_template will be that type, and if it has disks of multiple types,
the new disk template 'mixed' will be returned.


Eliminating the disk template from the instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In order to remove the disk template from the instance model, all
current uses of the disk template there need to be replaced. These uses
fall into the following general categories:

1. The configuration needs to reflect the new model. `cfgupgrade` and
   `bootstrap` need to be fixed, creating and modifying instances and
   disks for instances needs to be fixed.
2. The query interface will no longer be able to return an instance disk
   template.
3. Several checks for the DISKLESS template will be replaced by checking
   if any disks are attached.
4. If an operation works disk by disk, the operation will dispatch for
   the functionality by disk instead of by instance. If an operation
   requires that all disks are of the same kind (e.g. a query if the
   instance is DRBD backed) then the assumption is checked beforehand.
   Since this is a user visible change, it will have to be announced in
   the NEWS file specifying the calls changed.
5. Operations that operate on the instance and extract the disk template
   e.g. for creation of a new disk will require an additional parameter
   for the disk template. Several instances already provide an optional
   parameter to override the instance setting, those will become
   required. This is incompatible as well and will need to be listed in
   the NEWS file.

Attach/Detach disks from cli
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The `attach`/`detach` options should be available through the command
``gnt-instance modify``. Like the `add`/`remove` options, the `attach`/`detach`
options can be invoked using the legacy syntax or the new syntax that supports
indexes. For the attach option, we can refer to the disk using either its
`name` or `uuid`. The detach option on the other hand has the same syntax as
the remove option, and we can refer to a disk by its `name`, `uuid` or `index`
in the instance.

The attach/detach syntax can be seen below:

* **Legacy syntax**

  .. code-block:: bash

    gnt-instance modify --disk attach,name=*NAME* *INSTANCE*
    gnt-instance modify --disk attach,uuid=*UUID* *INSTANCE*
    gnt-instance modify --disk detach *INSTANCE*

* **New syntax**

  .. code-block:: bash

    gnt-instance modify --disk *N*:attach,name=*NAME* *INSTANCE*
    gnt-instance modify --disk *N*:attach,uuid=*UUID* *INSTANCE*
    gnt-instance modify --disk *N*:detach *INSTANCE*
    gnt-instance modify --disk *NAME*:detach *INSTANCE*
    gnt-instance modify --disk *UUID*:detach *INSTANCE*


.. TODO: Locks for Disk objects

.. TODO: LUs for disks


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
