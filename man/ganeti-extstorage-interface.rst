ganeti-extstorage-interface(7) Ganeti | Version @GANETI_VERSION@
================================================================

Name
----

ganeti-extstorage-interface - Specifications for ExtStorage providers

DESCRIPTION
-----------

The method for supporting external shared storage in Ganeti is to have
an ExtStorage provider for each external shared storage hardware type.
The ExtStorage provider is a set of files (executable scripts and text
files), contained inside a directory which is named after the provider.
This directory must be present across all nodes of a nodegroup (Ganeti
doesn't replicate it), in order for the provider to be usable by Ganeti
for this nodegroup (valid). The external shared storage hardware should
also be accessible by all nodes of this nodegroup too.

REFERENCE
---------

There are eight required files: *create*, *attach*, *detach*, *remove*,
*grow*, *setinfo*, *verify*, (executables) and *parameters.list*
(text file).

There are also three optional files: *open*, *close*, and
*snapshot* (executables).

Common environment
~~~~~~~~~~~~~~~~~~

All commands will get their input via environment variables. A common
set of variables will be exported for all commands, and some commands
might have extra variables. Note that all counts are zero-based.

Since Ganeti version 2.5, the environment will be cleaned up before
being passed to scripts, therefore they will not inherit the environment
in with which the ganeti node daemon was started. If you depend on any
environment variables (non-Ganeti), then you will need to define or
source them appropriately.

VOL_NAME
    The name of the volume. This is unique for Ganeti and it uses it
    to refer to a specific volume inside the external storage. Its
    format is ``UUID.ext.diskX`` where ``UUID`` is produced by Ganeti
    and is unique inside the Ganeti context. ``X`` is the number of the
    disk count.

VOL_SIZE
    Available only to the **create** and **grow** scripts. The volume's
    size in mebibytes.

VOL_NEW_SIZE
    Available only to the **grow** script. It declares the new size of
    the volume after grow (in mebibytes). To find the amount of grow,
    the scipt should calculate the number VOL_NEW_SIZE - VOL_SIZE.

EXTP_*name*
    Each ExtStorage parameter (see below) will be exported in its own
    variable, prefixed with ``EXTP_``, and upper-cased. For example, a
    ``fromsnap`` parameter will be exported as ``EXTP_FROMSNAP``.

VOL_METADATA
    Available only to the **setinfo** script. A string containing
    metadata to be associated with the volume. Currently, Ganeti sets
    this value to ``originstname+X`` where ``X`` is the instance's name.

VOL_CNAME
    The human-readable name of the Disk config object (optional).

VOL_UUID
    The uuid of the Disk config object.

VOL_SNAPSHOT_NAME
    The name of the volume's snapshot.

VOL_SNAPSHOT_SIZE
    The size of the volume's snapshot.

VOL_OPEN_EXCLUSIVE
    Whether the volume will be opened for exclusive access or not.
    This will be False (denoting shared access) during migration.

EXECUTABLE SCRIPTS
------------------

create
~~~~~~

The **create** command is used for creating a new volume inside the
external storage. The ``VOL_NAME`` denotes the volume's name, which
should be unique. After creation, Ganeti will refer to this volume by
this name for all other actions.

Ganeti produces this name dynamically and ensures its uniqueness inside
the Ganeti context. Therefore, you should make sure not to provision
manually additional volumes inside the external storage with this type
of name, because this will lead to conflicts and possible loss of data.

The ``VOL_SIZE`` variable denotes the size of the new volume to be
created in mebibytes.

If the script ends successfully, a new volume of size ``VOL_SIZE``
should exist inside the external storage. e.g:: a lun inside a NAS
appliance.

The script returns ``0`` on success.

attach
~~~~~~

This command is used in order to make an already created volume visible
to the physical node which will host the instance. This is done by
mapping the already provisioned volume to a block device inside the host
node.

The ``VOL_NAME`` variable denotes the volume to be mapped.

After successful attachment the script returns to its stdout a string,
which is the full path of the block device to which the volume is
mapped.  e.g:: /dev/dummy1

When attach returns, this path should be a valid block device on the
host node.

The attach script should be idempotent if the volume is already mapped.
If the requested volume is already mapped, then the script should just
return to its stdout the path which is already mapped to.

In case the storage technology supports userspace access to volumes as
well, e.g. the QEMU Hypervisor can see an RBD volume using its embedded
driver for the RBD protocol, then the provider can return extra lines
denoting the available userspace access URIs per hypervisor. The URI
should be in the following format: <hypervisor>:<uri>. For example, a
RADOS provider should return kvm:rbd:<pool>/<volume name> in the second
line of stdout after the local block device path (e.g. /dev/rbd1).

So, if the ``access`` disk parameter is ``userspace`` for the ext disk
template, then the QEMU command will end up having file=<URI> in
the ``-drive`` option.

In case the storage technology supports *only* userspace access to
volumes, then the first line of stdout should be an empty line, denoting
that a local block device is not available. If neither a block device
nor a URI is returned, then Ganeti will complain.

detach
~~~~~~

This command is used in order to unmap an already mapped volume from the
host node. Detach undoes everything attach did. This is done by
unmapping the requested volume from the block device it is mapped to.

The ``VOL_NAME`` variable denotes the volume to be unmapped.

``detach`` doesn't affect the volume itself. It just unmaps it from the
host node. The volume continues to exist inside the external storage.
It's just not accessible by the node anymore. This script doesn't return
anything to its stdout.

The detach script should be idempotent if the volume is already
unmapped. If the volume is not mapped, the script doesn't perform any
action at all.

The script returns ``0`` on success.

remove
~~~~~~

This command is used to remove an existing volume from the external
storage. The volume is permanently removed from inside the external
storage along with all its data.

The ``VOL_NAME`` variable denotes the volume to be removed.

The script returns ``0`` on success.

grow
~~~~

This command is used to grow an existing volume of the external storage.

The ``VOL_NAME`` variable denotes the volume to grow.

The ``VOL_SIZE`` variable denotes the current volume's size (in
mebibytes). The ``VOL_NEW_SIZE`` variable denotes the final size after
the volume has been grown (in mebibytes).

The amount of grow can be easily calculated by the scipt and is:

grow_amount = VOL_NEW_SIZE - VOL_SIZE (in mebibytes)

Ganeti ensures that: ``VOL_NEW_SIZE`` > ``VOL_SIZE``

If the script returns successfully, then the volume inside the external
storage will have a new size of ``VOL_NEW_SIZE``. This isn't immediately
reflected to the instance's disk. See ``gnt-instance grow`` for more
details on when the running instance becomes aware of its grown disk.

The script returns ``0`` on success.

setinfo
~~~~~~~

This script is used to add metadata to an existing volume. It is helpful
when we need to keep an external, Ganeti-independent mapping between
instances and volumes; primarily for recovery reasons. This is provider
specific and the author of the provider chooses whether/how to implement
this. You can just exit with ``0``, if you do not want to implement this
feature, without harming the overall functionality of the provider.

The ``VOL_METADATA`` variable contains the metadata of the volume.

Currently, Ganeti sets this value to ``originstname+X`` where ``X`` is
the instance's name.

The script returns ``0`` on success.

verify
~~~~~~

The *verify* script is used to verify consistency of the external
parameters (ext-params) (see below). The command should take one or more
arguments denoting what checks should be performed, and return a proper
exit code depending on whether the validation failed or succeeded.

Currently, the script is not invoked by Ganeti, but should be present
for future use and consistency with gnt-os-interface's verify script.

The script should return ``0`` on success.

snapshot
~~~~~~~~

The *snapshot* script is used to take a snapshot of the given volume.

The ``VOL_SNAPSHOT_NAME`` and ``VOL_SNAPSHOT_SIZE`` variables contain
the name and size of the snapshot we are about to create.

Currently this operation is used only during gnt-backup export and
Ganeti sets those values to ``VOL_NAME.snap`` and ``VOL_SIZE``
respectively (see above).

The script returns ``0`` on success.

Please note that this script is optional and not all providers should
implement it. Of course if it is not present, instance backup export
will not be supported for the given provider.

open
~~~~

The *open* script is used to open the given volume.

This makes the volume ready for I/O.

The ``VOL_OPEN_EXCLUSIVE`` variable denotes whether the volume will be
opened for exclusive access or not. It is True by default and
False (denoting shared access) during migration.

The script returns ``0`` on success.

Please note that this script is optional and not all providers should
implement it.

close
~~~~~

The *close* script is used to close the given volume.

This disables I/O on the volume.

The script returns ``0`` on success.

Please note that this script is optional and not all providers should
implement it.

TEXT FILES
----------

parameters.list
~~~~~~~~~~~~~~~

This file declares the parameters supported by the ExtStorage provider,
one parameter per line, with name and description (space and/or tab
separated). For example::

    fromsnap Snapshot name to create the volume from
    nas_ip The IP of the NAS appliance

The parameters can then be used during instance add as follows::

    # gnt-instance add --disk=0:fromsnap="file_name",nas_ip="1.2.3.4" ...

EXAMPLES
--------

In the following examples we assume that you have already installed
successfully two ExtStorage providers: ``pvdr1`` and ``pvdr2``

Add a new instance with a 10G first disk provided by ``pvdr1`` and a 20G
second disk provided by ``pvdr2``::

    # gnt-instance add -t ext --disk=0:size=10G,provider=pvdr1
                              --disk=1:size=20G,provider=pvdr2

Add a new instance with a 5G first disk provided by provider ``pvdr1``
and also pass the ``prm1``, ``prm2`` parameters to the provider, with
the corresponding values ``val1``, ``val2``::

   # gnt-instance add -t ext
                      --disk=0:size=5G,provider=pvdr1,prm1=val1,prm2=val2

Modify an existing instance of disk type ``ext`` by adding a new 30G
disk provided by provider ``pvdr2``::

   # gnt-instance modify --disk 1:add,size=30G,provider=pvdr2 <instance>

Modify an existing instance of disk type ``ext`` by adding 2 new disks,
of different providers, passing one parameter for the first one::

   # gnt-instance modify --disk 2:add,size=3G,provider=pvdr1,prm1=val1
                         --disk 3:add,size=5G,provider=pvdr2
                         <instance>

NOTES
-----

Backwards compatibility
~~~~~~~~~~~~~~~~~~~~~~~

The ExtStorage Interface was introduced in Ganeti 2.7.
Ganeti 2.7 and up is compatible with the ExtStorage Interface.

Common behaviour
~~~~~~~~~~~~~~~~

All the scripts should display an usage message when called with a wrong
number of arguments or when the first argument is ``-h`` or ``--help``.

.. vim: set textwidth=72 :
.. Local Variables:
.. mode: rst
.. fill-column: 72
.. End:
