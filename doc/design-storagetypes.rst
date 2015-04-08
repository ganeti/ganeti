=============================================================================
Management of storage types and disk templates, incl. storage space reporting
=============================================================================

.. contents:: :depth: 4

Background
==========

Currently, there is no consistent management of different variants of storage
in Ganeti. One direct consequence is that storage space reporting is currently
broken for all storage that is not based on lvm technology. This design looks at
the root causes and proposes a way to fix it.

Proposed changes
================

We propose to streamline handling of different storage types and disk templates.
Currently, there is no consistent implementation for dis/enabling of disk
templates and/or storage types.

Our idea is to introduce a list of enabled disk templates, which can be
used by instances in the cluster. Based on this list, we want to provide
storage reporting mechanisms for the available disk templates. Since some
disk templates share the same underlying storage technology (for example
``drbd`` and ``plain`` are based on ``lvm``), we map disk templates to storage
types and implement storage space reporting for each storage type.

Configuration changes
---------------------

Add a new attribute "enabled_disk_templates" (type: list of strings) to the
cluster config which holds disk templates, for example, "drbd", "file",
or "ext". This attribute represents the list of disk templates that are enabled
cluster-wide for usage by the instances. It will not be possible to create
instances with a disk template that is not enabled, as well as it will not be
possible to remove a disk template from the list if there are still instances
using it.

The list of enabled disk templates can contain any non-empty subset of
the currently implemented disk templates: ``blockdev``, ``diskless``, ``drbd``,
``ext``, ``file``, ``plain``, ``rbd``, and ``sharedfile``. See
``DISK_TEMPLATES`` in ``constants.py``.

Note that the abovementioned list of enabled disk types is just a "mechanism"
parameter that defines which disk templates the cluster can use. Further
filtering about what's allowed can go in the ipolicy, which is not covered in
this design doc. Note that it is possible to force an instance to use a disk
template that is not allowed by the ipolicy. This is not possible if the
template is not enabled by the cluster.

The ipolicy also contains a list of enabled disk templates. Since the cluster-
wide enabled disk templates should be a stronger constraint, the list of
enabled disk templates in the ipolicy should be a subset of those. In case the
user tries to create an inconsistent situation here, gnt-cluster should
display this as an error.

We consider the first disk template in the list to be the default template for
instance creation and storage reporting. This will remove the need to specify
the disk template with ``-t`` on instance creation. Note: It would be
better to take the default disk template from the node-group-specific
ipolicy. However, when using the iallocator, the nodegroup can only be
determined from the node which is determined by the iallocator, which in
turn needs the disk-template first. To solve this
chicken-and-egg-problem we first need to extend 'gnt-instance add' to
accept a nodegroup in the first place.

Currently, cluster-wide dis/enabling of disk templates is not implemented
consistently. ``lvm`` based disk templates are enabled by specifying a volume
group name on cluster initialization and can only be disabled by explicitly
using the option ``--no-lvm-storage``. This will be replaced by adding/removing
``drbd`` and ``plain`` from the set of enabled disk templates.

The option ``--no-drbd-storage`` is also subsumed by dis/enabling the
disk template ``drbd`` on the cluster.

Up till now, file storage and shared file storage could be dis/enabled at
``./configure`` time. This will also be replaced by adding/removing the
respective disk templates from the set of enabled disk templates.

There is currently no possibility to dis/enable the disk templates
``diskless``, ``blockdev``, ``ext``, and ``rdb``. By introducing the set of
enabled disk templates, we will require these disk templates to be explicitly
enabled in order to be used. The idea is that the administrator of the cluster
can tailor the cluster configuration to what is actually needed in the cluster.
There is hope that this will lead to cleaner code, better performance and fewer
bugs.

When upgrading the configuration from a version that did not have the list
of enabled disk templates, we have to decide which disk templates are enabled
based on the current configuration of the cluster. We propose the following
update logic to be implemented in the online update of the config in
the ``Cluster`` class in ``objects.py``:
- If a ``volume_group_name`` is existing, then enable ``drbd`` and ``plain``.
- If ``file`` or ``sharedfile`` was enabled at configure time, add the
respective disk template to the list of enabled disk templates.
- For disk templates ``diskless``, ``blockdev``, ``ext``, and ``rbd``, we
inspect the current cluster configuration regarding whether or not there
are instances that use one of those disk templates. We will add only those
that are currently in use.
The order in which the list of enabled disk templates is built up will be
determined by a preference order based on when in the history of Ganeti the
disk templates were introduced (thus being a heuristic for which are used
more than others).

The list of enabled disk templates can be specified on cluster initialization
with ``gnt-cluster init`` using the optional parameter
``--enabled-disk-templates``. If it is not set, it will be set to a default
set of enabled disk templates, which includes the following disk templates:
``drbd`` and ``plain``. The list can be shrunk or extended by
``gnt-cluster modify`` using the same parameter.

Storage reporting
-----------------

The storage reporting in ``gnt-node list`` will be the first user of the
newly introduced list of enabled disk templates. Currently, storage reporting
works only for lvm-based storage. We want to extend that and report storage
for the enabled disk templates. The default of ``gnt-node list`` will only
report on storage of the default disk template (the first in the list of enabled
disk templates). One can explicitly ask for storage reporting on the other
enabled disk templates with the ``-o`` option.

Some of the currently implemented disk templates share the same base storage
technology. Since the storage reporting is based on the underlying technology
rather than on the user-facing disk templates, we introduce storage types to
represent the underlying technology. There will be a mapping from disk templates
to storage types, which will be used by the storage reporting backend to pick
the right method for estimating the storage for the different disk templates.

The proposed storage types are ``blockdev``, ``diskless``, ``ext``, ``file``,
``lvm-pv``, ``lvm-vg``, ``rados``.

The mapping from disk templates to storage types will be: ``drbd`` and ``plain``
to ``lvm-vg``, ``file`` and ``sharedfile`` to ``file``, and all others to their
obvious counterparts.

Note that there is no disk template mapping to ``lvm-pv``, because this storage
type is currently only used to enable the user to mark it as (un)allocatable.
(See ``man gnt-node``.) It is not possible to create an instance on a storage
unit that is of type ``lvm-pv`` directly, therefore it is not included in the
mapping.

The storage reporting for file and sharedfile storage will report space
on the file storage dir, which is currently limited to one directory.
In the future, if we'll have support for more directories, or for per-nodegroup
directories this can be changed.

For now, we will implement only the storage reporting for lvm-based and
file-based storage, that is disk templates ``file``, ``sharedfile``, ``lvm``,
and ``drbd``. For disk template ``diskless``, there is obviously nothing to
report about. When implementing storage reporting for file, we can also use
it for ``sharedfile``, since it uses the same file system mechanisms to
determine the free space. In the future, we can optimize storage reporting
for shared storage by not querying all nodes that use a common shared file
for the same space information.

In the future, we extend storage reporting for shared storage types like
``rados`` and ``ext``. Note that it will not make sense to query each node for
storage reporting on a storage unit that is used by several nodes.

We will not implement storage reporting for the ``blockdev`` disk template,
because block devices are always adopted after being provided by the system
administrator, thus coming from outside Ganeti. There is no point in storage
reporting for block devices, because Ganeti will never try to allocate storage
inside a block device.

RPC changes
-----------

The noded RPC call that reports node storage space will be changed to
accept a list of <storage_type>,<key> string tuples. For each of them, it will
report the free amount of storage space found on storage <key> as known
by the requested storage_type. Depending on the storage_type, the key would
be a volume group name in case of lvm, a directory name for the file-based
storage, and a rados pool name for rados storage.

Masterd will know through the mapping of storage types to storage calculation
functions which storage type uses which mechanism for storage calculation
and invoke only the needed ones.

Note that for file and sharedfile the node knows which directories are allowed
and won't allow any other directory to be queried for security reasons. The
actual path still needs to be passed to distinguish the two, as the type will
be the same for both.

These calculations will be implemented in the node storage system
(currently lib/storage.py) but querying will still happen through the
``node info`` call, to avoid requiring an extra RPC each time.

Ganeti reporting
----------------

`gnt-node list`` can be queried for the different disk templates, if they
are enabled. By default, it will just report information about the default
disk template. Examples::

  > gnt-node list
  Node                       DTotal DFree MTotal MNode MFree Pinst Sinst
  mynode1                      3.6T  3.6T  64.0G 1023M 62.2G     1     0
  mynode2                      3.6T  3.6T  64.0G 1023M 62.0G     2     1
  mynode3                      3.6T  3.6T  64.0G 1023M 62.3G     0     2

  > gnt-node list -o dtotal/drbd,dfree/file
  Node      DTotal (drbd, myvg) DFree (file, mydir)
  mynode1                 3.6T                    -
  mynode2                 3.6T                    -

Note that for drbd, we only report the space of the vg and only if it was not
renamed to something different than the default volume group name. With this
design, there is also no possibility to ask about the meta volume group. We
restrict the design here to make the transition to storage pools easier (as it
is an interim state only). It is the administrator's responsibility to ensure
that there is enough space for the meta volume group.

When storage pools are implemented, we switch from referencing the disk template
to referencing the storage pool name. For that, of course, the pool names need
to be unique over all storage types. For drbd, we will use the default 'drbd'
storage pool and possibly a second lvm-based storage pool for the metavg. It
will be possible to rename storage pools (thus also the default lvm storage
pool). There will be new functionality to ask about what storage pools are
available and of what type. Storage pools will have a storage pool type which is
one of the disk templates. There can be more than one storage pool based on the
same disk template, therefore we will then start referencing the storage pool
name instead of the disk template.

Note: As of version 2.10, ``gnt-node list`` only reports storage space
information for the default disk template, as supporting more options
turned out to be not feasible without storage pools.

Besides in ``gnt-node list``, storage space information is also
displayed in ``gnt-node list-storage``. This will also adapt to the
extended storage reporting capabilities. The user can specify a storage
type using ``--storage-type``. If he requests storage information about
a storage type which does not support space reporting, a warning is
emitted. If no storage type is specified explicitly, ``gnt-node
list-storage`` will try to report storage on the storage type of the
default disk template. If the default disk template's storage type does
not support space reporting, an error message is emitted.

``gnt-cluster info`` will report which disk templates are enabled, i.e.
which ones are supported according to the cluster configuration. Example
output::

  > gnt-cluster info
  [...]
  Cluster parameters:
    - [...]
    - enabled disk templates: plain, drbd, sharedfile, rados
    - [...]

``gnt-node list-storage`` will not be affected by any changes, since this design
is restricted only to free storage reporting for non-shared storage types.

Allocator changes
-----------------

The iallocator protocol doesn't need to change: since we know which
disk template an instance has, we'll pass only the "free" value for that
disk template to the iallocator, when asking for an allocation to be
made. Note that for DRBD nowadays we ignore the case when vg and metavg
are different, and we only consider the main volume group. Fixing this is
outside the scope of this design.

Although the iallocator protocol itself does not need change, the
invocation of the iallocator needs quite some adaption. So far, it
always requested LVM storage information no matter if that was the
disk template to be considered for the allocation. For instance
allocation, this is the disk template of the instance.
TODO: consider other allocator requests.

With this design, we ensure forward-compatibility with respect to storage
pools. For now, we'll report space for all available disk templates that
are based on non-shared storage types, in the future, for all available
storage pools.

Rebalancing changes
-------------------

Hbal will not need changes, as it handles it already. We don't forecast
any changes needed to it.

Space reporting changes
-----------------------

Hspace will by default report by assuming the allocation will happen on
the default disk template for the cluster/nodegroup. An option will be added
to manually specify a different storage.

Interactions with Partitioned Ganeti
------------------------------------

Also the design for :doc:`Partitioned Ganeti <design-partitioned>` deals
with reporting free space. Partitioned Ganeti has a different way to
report free space for LVM on nodes where the ``exclusive_storage`` flag
is set. That doesn't interact directly with this design, as the specifics
of how the free space is computed is not in the scope of this design.
But the ``node info`` call contains the value of the
``exclusive_storage`` flag, which is currently only meaningful for the
LVM storage type. Additional flags like the ``exclusive_storage`` flag
for lvm might be useful for other disk templates / storage types as well.
We therefore extend the RPC call with <storage_type>,<key> to
<storage_type>,<key>,[<param>] to include any disk-template-specific
(or storage-type specific) parameters in the RPC call.

The reporting of free spindles, also part of Partitioned Ganeti, is not
concerned with this design doc, as those are seen as a separate resource.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
