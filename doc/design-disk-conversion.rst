=================================
Conversion between disk templates
=================================

.. contents:: :depth: 4

This design document describes the support for generic disk template
conversion in Ganeti. The logic used is disk template agnostic and
targets to cover the majority of conversions among the supported disk
templates.


Current state and shortcomings
==============================

Currently, Ganeti supports choosing among different disk templates when
creating an instance. However, converting the disk template of an
existing instance is possible only between the ``plain`` and ``drbd``
templates. This feature was added in Ganeti since its early versions
when the number of supported disk templates was limited. Now that Ganeti
supports plenty of choices, this feature should be extended to provide
more flexibility to the user.

The procedure for converting from the plain to the drbd disk template
works as follows. Firstly, a completely new disk template is generated
matching the size, mode, and the count of the current instance's disks.
The missing volumes are created manually both in the primary (meta disk)
and the secondary node. The original LVs running on the primary node are
renamed to match the new names. The last step is to manually associate
the DRBD devices with their mirror block device pairs. The conversion
from the drbd to the plain disk template is much simpler than the
opposite. Firstly, the DRBD mirroring is manually disabled. Then the
unnecessary volumes including the meta disk(s) of the primary node, and
the meta and data disk(s) from the previously secondary node are
removed.


Proposed changes
================

This design proposes the creation of a unified interface for handling
the disk template conversions in Ganeti. Currently, there is no such
interface and each one of the supported conversions uses a separate code
path.

This proposal introduces a single, disk-agnostic interface for handling
the disk template conversions in Ganeti, keeping in mind that we want it
to be as generic as possible. An exception case will be the currently
supported conversions between the LVM-based disk templates. Their basic
functionality will not be affected and will diverge from the rest disk
template conversions. The target is to provide support for conversions
among the majority of the available disk templates, and also creating
a mechanism that will easily support any new templates that may be
probably added in Ganeti, at a future point.


Design decisions
================

Currently, the supported conversions for the LVM-based templates are
handled by the ``LUInstanceSetParams`` LU. Our implementation will
follow the same approach. From a high-level point-of-view this design
can be split in two parts:

* The extension of the LU's checks to cover all the supported template
  conversions

* The new functionality which will be introduced to provide the new
  feature

The instance must be stopped before starting the disk template
conversion, as it currently is, otherwise the operation will fail. The
new mechanism will need to copy the disk's data for the conversion to be
possible. We propose using the Unix ``dd`` command to copy the
instance's data. It can be used to copy data from source to destination,
block-by-block, regardless of their filesystem types, making it a
convenient tool for the case. Since the conversion will be done via data
copy it will take a long time for bigger disks to copy their data and
consequently for the instance to switch to the new template.

Some template conversions can be done faster without copying explicitly
their disks' data. A use case is the conversions between the LVM-based
templates, i.e., ``drbd`` and ``plain`` which will be done as happens
now and not using the ``dd`` command. Also, this implementation will
provide partial support for the ``blockdev`` disk template which will
act only as a source template. Since those volumes are adopted
pre-existent block devices we will not support conversions targeting
this template. Another exception case will be the ``diskless`` template.
Since it is a testing template that creates instances with no disks we
will not provide support for conversions that include this template
type.


We divide the design into the following parts:

* Block device changes, that include the new methods which will be
  introduced and will be responsible for building the commands for the
  data copy from/to the requested devices

* Backend changes, that include a new RPC call which will concatenate
  the output of the above two methods and will execute the data copy
  command

* Core changes, that include the modifications in the Logical Unit

* User interface changes, i.e., command line changes


Block device changes
--------------------

The block device abstract class will be extended with two new methods,
named ``Import`` and ``Export``. Those methods will be responsible for
building the commands that will be used for the data copy between the
corresponding devices. The ``Export`` method will build the command
which will export the data from the source device, while the ``Import``
method will do the opposite. It will import the data to the newly
created target device. Those two methods will not perform the actual
data copy; they will simply return the requested commands for
transferring the data from/to the individual devices. The output of the
two methods will be combined using a pipe ("|") by the caller method in
the backend level.

By default the data import and export will be done using the ``dd``
command. All the inherited classes will use the base functionality
unless there is a faster way to convert to. In that case the underlying
block device will overwrite those methods with its specific
functionality. A use case will be the Ceph/RADOS block devices which
will make use of the ``rbd import`` and ``rbd export`` commands to copy
their data instead of using the default ``dd`` command.

Keeping the data copy functionality in the block device layer, provides
us with a generic mechanism that works between almost all conversions
and furthermore can be easily extended for new disk templates. It also
covers the devices that support the ``access=userspace`` parameter and
solves this problem in a generic way, by implementing the logic in the
right level where we know what is the best to do for each device.


Backend changes
---------------

Introduce a new RPC call:

* blockdev_convert(src_disk, dest_disk)

where ``src_disk`` and ``dest_disk`` are the original and the new disk
objects respectively. First, the actual device instances will be
computed and then they will be used to build the export and import
commands for the data copy. The output of those methods will be
concatenated using a pipe, following a similar approach with the impexp
daemon. Finally, the unified data copy command will be executed, at this
level, by the ``nodeD``.


Core changes
------------

The main modifications will be made in the ``LUInstanceSetParams`` LU.
The implementation of the conversion mechanism will be split into the
following parts:

* The generation of the new disk template for the instance. The new
  disks will match the size, mode, and name of the original volumes.
  Those parameters and any other needed, .i.e., the provider's name for
  the ExtStorage conversions, will be computed by a new method which we
  will introduce, named ``ComputeDisksInfo``. The output of that
  function will be used as the ``disk_info`` argument of the
  ``GenerateDiskTemplate`` method.

* The creation of the new block devices. We will make use of the
  ``CreateDisks`` method which creates and attaches the new block
  devices.

* The data copy for each disk of the instance from the original to the
  newly created volume. The data copy will be made by the ``nodeD`` with
  the rpc call we have introduced earlier in this design. In case some
  disks fail to copy their data the operation will fail and the newly
  created disks will be removed. The instance will remain intact.

* The detachment of the original disks of the instance when the data
  copy operation successfully completes by calling the
  ``RemoveInstanceDisk`` method for each instance's disk.

* The attachment of the new disks to the instance by calling the
  ``AddInstanceDisk`` method for each disk we have created.

* The update of the configuration file with the new values.

* The removal of the original block devices from the node using the
  ``BlockdevRemove`` method for each one of the old disks.


User interface changes
----------------------

The ``-t`` (``--disk-template``) option from the gnt-instance modify
command will specify the disk template to convert *to*, as it happens
now. The rest disk options such as its size, its mode, and its name will
be computed from the original volumes by the conversion mechanism, and
the user will not explicitly provide them.


ExtStorage conversions
~~~~~~~~~~~~~~~~~~~~~~

When converting to an ExtStorage disk template the
``provider=*PROVIDER*`` option which specifies the ExtStorage provider
will be mandatory. Also, arbitrary parameters can be passed to the
ExtStorage provider. Those parameters will be optional and could be
passed as additional comma separated options. Since it is not allowed to
convert the disk template of an instance and make use of the ``--disk``
option at the same time, we propose to introduce a new option named
``--ext-params`` to handle the ``ext`` template conversions.

::

  gnt-instance modify -t ext --ext-params provider=pvdr1 test_vm
  gnt-instance modify -t ext --ext-params provider=pvdr1,param1=val1,param2=val2 test_vm


File-based conversions
~~~~~~~~~~~~~~~~~~~~~~

For conversions *to* a file-based template the ``--file-storage-dir``
and the ``--file-driver`` options could be used, similarly to the
**add** command, to manually configure the storage directory and the
preferred driver for the file-based disks.

::

  gnt-instance modify -t file --file-storage-dir=mysubdir test_vm


Supported template conversions
==============================

This is a summary of the disk template conversions that the conversion
mechanism will support:

+--------------+-----------------------------------------------------------------------------------+
| Source       |                                 Target Disk Template                              |
| Disk         +---------+-------+------+------------+---------+------+------+----------+----------+
| Template     |  Plain  |  DRBD | File | Sharedfile | Gluster | RBD  | Ext  | BlockDev | Diskless |
+==============+=========+=======+======+============+=========+======+======+==========+==========+
| Plain        |    -    |  Yes. | Yes. |    Yes.    |   Yes.  | Yes. | Yes. |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| DRBD         |   Yes.  |   -   | Yes. |    Yes.    |   Yes.  | Yes. | Yes. |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| File         |   Yes.  |  Yes. |   -  |    Yes.    |   Yes.  | Yes. | Yes. |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| Sharedfile   |   Yes.  |  Yes. | Yes. |     -      |   Yes.  | Yes. | Yes. |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| Gluster      |   Yes.  |  Yes. | Yes. |    Yes.    |    -    | Yes. | Yes. |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| RBD          |   Yes.  |  Yes. | Yes. |    Yes.    |   Yes.  |  -   | Yes. |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| Ext          |   Yes.  |  Yes. | Yes. |    Yes.    |   Yes.  | Yes. |  -   |    No.   |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| BlockDev     |   Yes.  |  Yes. | Yes. |    Yes.    |   Yes.  | Yes. | Yes. |     -    |   No.    |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+
| Diskless     |   No.   |  No.  | No.  |    No.     |   No.   | No.  | No.  |    No.   |    -     |
+--------------+---------+-------+------+------------+---------+------+------+----------+----------+


Future Work
===========

Expand the conversion mechanism to provide a visual indication of the
data copy operation. We could monitor the progress of the data sent via
a pipe, and provide to the user information such as the time elapsed,
percentage completed (probably with a progress bar), total data
transferred, and so on, similar to the progress tracking that is
currently done by the impexp daemon.


.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
