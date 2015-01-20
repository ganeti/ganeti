=================================
Ganeti file-based disks ownership
=================================

.. contents:: :depth: 2

This design document explains the issue that emerges from the usage of the
`detach` operation to file-based disks and provides a simple solution to it.
Note that this design document applies only to disks of template `file` and
`sharedfile`, but not `gluster`. However, for brevity reasons these templates
will go under the umbrella term `file-based`.

Current state and shortcomings
==============================

When creating a file-based disk, Ganeti stores it inside a specific directory,
called `file_storage_dir`. Inside this directory, there is a folder for each
file-based instance and inside each folder are the files for the instance's
disks (e.g. ``<file_storage_dir>/<instance_name>/<disk_name>``). This way of
storing disks seems simple enough, but the
`detach` operation does not work well with it. The reason is that if a disk is
detached from an instance and attached to another one, the file will remain to
the folder of the original instance.

This means that if we try to destroy an instance with detached disks, Ganeti
will correctly complain that the instance folder still has disk data. In more
high-level terms, we need to find a way to resolve the issue of disk ownership
at the filesystem level for file-based instances.

Proposed changes
================

The change we propose is simple. Once a disk is detached from an instance, it
will be moved out of the instance's folder. The new location will be the
`file_storage_dir`, i.e. the disk will reside on the same level as the instance
folders. In order to maintain a consistent configuration, the logical_id of the
disk will be updated to point to the new path.

Similarly, on the `attach` operation, the file name and logical id will change
and the disk will be moved under the new instance's directory.

Implementation details
======================

Detach operation
~~~~~~~~~~~~~~~~

Before detaching a disk from an instance, we do the following:

1. Transform the current path to the new one.

   <file_storage_dir>/<instance_name>/<disk_name> --> <file_storage_dir>/<disk_name>

2. Use the rpc call ``call_blockdev_rename`` to move the disk to the new path.
3. Store the new ``logical_id`` to the configuration.

Attach operation
~~~~~~~~~~~~~~~~

Before attaching a disk to an instance, we do the following:

1. Create the new path for the file disk. In order to construct it properly,
   use the ``GenerateDiskTemplate`` function to create a dummy disk template
   and get its ``logical_id``. The new ``logical_id`` contains the new path for
   the file disk.
2. Use the rpc call ``call_blockdev_rename`` to move the disk to the new path.
3. Store the new ``logical_id`` to the configuration.
