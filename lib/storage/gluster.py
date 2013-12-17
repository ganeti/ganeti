#
#

# Copyright (C) 2013 Google Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.

"""Gluster storage class.

This class is very similar to FileStorage, given that Gluster when mounted
behaves essentially like a regular file system. Unlike RBD, there are no
special provisions for block device abstractions (yet).

"""
from ganeti import errors

from ganeti.storage import base
from ganeti.storage.filestorage import FileDeviceHelper


class GlusterStorage(base.BlockDev):
  """File device using the Gluster backend.

  This class represents a file storage backend device stored on Gluster. The
  system administrator must mount the Gluster device himself at boot time before
  Ganeti is run.

  The unique_id for the file device is a (file_driver, file_path) tuple.

  """
  def __init__(self, unique_id, children, size, params, dyn_params):
    """Initalizes a file device backend.

    """
    if children:
      base.ThrowError("Invalid setup for file device")
    super(GlusterStorage, self).__init__(unique_id, children, size, params,
                                         dyn_params)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self.driver = unique_id[0]
    self.dev_path = unique_id[1]

    self.file = FileDeviceHelper(self.dev_path)

    self.Attach()

  def Assemble(self):
    """Assemble the device.

    Checks whether the file device exists, raises BlockDeviceError otherwise.

    """
    assert self.attached, "Gluster file assembled without being attached"
    self.file.Exists(assert_exists=True)

  def Shutdown(self):
    """Shutdown the device.

    """

    self.file = None
    self.dev_path = None
    self.attached = False

  def Open(self, force=False):
    """Make the device ready for I/O.

    This is a no-op for the file type.

    """
    assert self.attached, "Gluster file opened without being attached"

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    This is a no-op for the file type.
    """
    pass

  def Remove(self):
    """Remove the file backing the block device.

    @rtype: boolean
    @return: True if the removal was successful

    """
    return self.file.Remove()

  def Rename(self, new_id):
    """Renames the file.

    """
    # TODO: implement rename for file-based storage
    base.ThrowError("Rename is not supported for Gluster storage")

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the file

    @param amount: the amount (in mebibytes) to grow with

    """
    self.file.Grow(amount, dryrun, backingstore, excl_stor)

  def Attach(self):
    """Attach to an existing file.

    Check if this file already exists.

    @rtype: boolean
    @return: True if file exists

    """
    self.attached = self.file.Exists()
    return self.attached

  def GetActualSize(self):
    """Return the actual disk size.

    @note: the device needs to be active when this is called

    """
    return self.file.Size()

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params):
    """Create a new file.

    @param size: the size of file in MiB

    @rtype: L{bdev.FileStorage}
    @return: an instance of FileStorage

    """
    if excl_stor:
      raise errors.ProgrammerError("FileStorage device requested with"
                                   " exclusive_storage")
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    dev_path = unique_id[1]

    FileDeviceHelper.Create(dev_path, size)
    return GlusterStorage(unique_id, children, size, params, dyn_params)
