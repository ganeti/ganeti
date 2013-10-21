#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
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


"""Block device abstraction - base class and utility functions"""

import logging

from ganeti import objects
from ganeti import constants
from ganeti import utils
from ganeti import errors


class BlockDev(object):
  """Block device abstract class.

  A block device can be in the following states:
    - not existing on the system, and by `Create()` it goes into:
    - existing but not setup/not active, and by `Assemble()` goes into:
    - active read-write and by `Open()` it goes into
    - online (=used, or ready for use)

  A device can also be online but read-only, however we are not using
  the readonly state (LV has it, if needed in the future) and we are
  usually looking at this like at a stack, so it's easier to
  conceptualise the transition from not-existing to online and back
  like a linear one.

  The many different states of the device are due to the fact that we
  need to cover many device types:
    - logical volumes are created, lvchange -a y $lv, and used
    - drbd devices are attached to a local disk/remote peer and made primary

  A block device is identified by three items:
    - the /dev path of the device (dynamic)
    - a unique ID of the device (static)
    - it's major/minor pair (dynamic)

  Not all devices implement both the first two as distinct items. LVM
  logical volumes have their unique ID (the pair volume group, logical
  volume name) in a 1-to-1 relation to the dev path. For DRBD devices,
  the /dev path is again dynamic and the unique id is the pair (host1,
  dev1), (host2, dev2).

  You can get to a device in two ways:
    - creating the (real) device, which returns you
      an attached instance (lvcreate)
    - attaching of a python instance to an existing (real) device

  The second point, the attachment to a device, is different
  depending on whether the device is assembled or not. At init() time,
  we search for a device with the same unique_id as us. If found,
  good. It also means that the device is already assembled. If not,
  after assembly we'll have our correct major/minor.

  """
  def __init__(self, unique_id, children, size, params, dyn_params):
    self._children = children
    self.dev_path = None
    self.unique_id = unique_id
    self.major = None
    self.minor = None
    self.attached = False
    self.size = size
    self.params = params
    self.dyn_params = dyn_params

  def Assemble(self):
    """Assemble the device from its components.

    Implementations of this method by child classes must ensure that:
      - after the device has been assembled, it knows its major/minor
        numbers; this allows other devices (usually parents) to probe
        correctly for their children
      - calling this method on an existing, in-use device is safe
      - if the device is already configured (and in an OK state),
        this method is idempotent

    """
    pass

  def Attach(self):
    """Find a device which matches our config and attach to it.

    """
    raise NotImplementedError

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    raise NotImplementedError

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params):
    """Create the device.

    If the device cannot be created, it will return None
    instead. Error messages go to the logging system.

    Note that for some devices, the unique_id is used, and for other,
    the children. The idea is that these two, taken together, are
    enough for both creation and assembly (later).

    @type unique_id: 2-element tuple or list
    @param unique_id: unique identifier; the details depend on the actual device
        type
    @type children: list of L{BlockDev}
    @param children: for hierarchical devices, the child devices
    @type size: float
    @param size: size in MiB
    @type spindles: int
    @param spindles: number of physical disk to dedicate to the device
    @type params: dict
    @param params: device-specific options/parameters
    @type excl_stor: bool
    @param excl_stor: whether exclusive_storage is active
    @type dyn_params: dict
    @param dyn_params: dynamic parameters of the disk only valid for this node.
        As set by L{objects.Disk.UpdateDynamicDiskParams}.
    @rtype: L{BlockDev}
    @return: the created device, or C{None} in case of an error

    """
    raise NotImplementedError

  def Remove(self):
    """Remove this device.

    This makes sense only for some of the device types: LV and file
    storage. Also note that if the device can't attach, the removal
    can't be completed.

    """
    raise NotImplementedError

  def Rename(self, new_id):
    """Rename this device.

    This may or may not make sense for a given device type.

    """
    raise NotImplementedError

  def Open(self, force=False):
    """Make the device ready for use.

    This makes the device ready for I/O. For now, just the DRBD
    devices need this.

    The force parameter signifies that if the device has any kind of
    --force thing, it should be used, we know what we are doing.

    @type force: boolean

    """
    raise NotImplementedError

  def Shutdown(self):
    """Shut down the device, freeing its children.

    This undoes the `Assemble()` work, except for the child
    assembling; as such, the children on the device are still
    assembled after this call.

    """
    raise NotImplementedError

  def SetSyncParams(self, params):
    """Adjust the synchronization parameters of the mirror.

    In case this is not a mirroring device, this is no-op.

    @param params: dictionary of LD level disk parameters related to the
    synchronization.
    @rtype: list
    @return: a list of error messages, emitted both by the current node and by
    children. An empty list means no errors.

    """
    result = []
    if self._children:
      for child in self._children:
        result.extend(child.SetSyncParams(params))
    return result

  def PauseResumeSync(self, pause):
    """Pause/Resume the sync of the mirror.

    In case this is not a mirroring device, this is no-op.

    @type pause: boolean
    @param pause: Whether to pause or resume

    """
    result = True
    if self._children:
      for child in self._children:
        result = result and child.PauseResumeSync(pause)
    return result

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    If this device is a mirroring device, this function returns the
    status of the mirror.

    If sync_percent is None, it means the device is not syncing.

    If estimated_time is None, it means we can't estimate
    the time needed, otherwise it's the time left in seconds.

    If is_degraded is True, it means the device is missing
    redundancy. This is usually a sign that something went wrong in
    the device setup, if sync_percent is None.

    The ldisk parameter represents the degradation of the local
    data. This is only valid for some devices, the rest will always
    return False (not degraded).

    @rtype: objects.BlockDevStatus

    """
    return objects.BlockDevStatus(dev_path=self.dev_path,
                                  major=self.major,
                                  minor=self.minor,
                                  sync_percent=None,
                                  estimated_time=None,
                                  is_degraded=False,
                                  ldisk_status=constants.LDS_OKAY)

  def CombinedSyncStatus(self):
    """Calculate the mirror status recursively for our children.

    The return value is the same as for `GetSyncStatus()` except the
    minimum percent and maximum time are calculated across our
    children.

    @rtype: objects.BlockDevStatus

    """
    status = self.GetSyncStatus()

    min_percent = status.sync_percent
    max_time = status.estimated_time
    is_degraded = status.is_degraded
    ldisk_status = status.ldisk_status

    if self._children:
      for child in self._children:
        child_status = child.GetSyncStatus()

        if min_percent is None:
          min_percent = child_status.sync_percent
        elif child_status.sync_percent is not None:
          min_percent = min(min_percent, child_status.sync_percent)

        if max_time is None:
          max_time = child_status.estimated_time
        elif child_status.estimated_time is not None:
          max_time = max(max_time, child_status.estimated_time)

        is_degraded = is_degraded or child_status.is_degraded

        if ldisk_status is None:
          ldisk_status = child_status.ldisk_status
        elif child_status.ldisk_status is not None:
          ldisk_status = max(ldisk_status, child_status.ldisk_status)

    return objects.BlockDevStatus(dev_path=self.dev_path,
                                  major=self.major,
                                  minor=self.minor,
                                  sync_percent=min_percent,
                                  estimated_time=max_time,
                                  is_degraded=is_degraded,
                                  ldisk_status=ldisk_status)

  def SetInfo(self, text):
    """Update metadata with info text.

    Only supported for some device types.

    """
    for child in self._children:
      child.SetInfo(text)

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the block device.

    @type amount: integer
    @param amount: the amount (in mebibytes) to grow with
    @type dryrun: boolean
    @param dryrun: whether to execute the operation in simulation mode
        only, without actually increasing the size
    @param backingstore: whether to execute the operation on backing storage
        only, or on "logical" storage only; e.g. DRBD is logical storage,
        whereas LVM, file, RBD are backing storage
    @type excl_stor: boolean
    @param excl_stor: Whether exclusive_storage is active

    """
    raise NotImplementedError

  def GetActualSize(self):
    """Return the actual disk size.

    @note: the device needs to be active when this is called

    """
    assert self.attached, "BlockDevice not attached in GetActualSize()"
    result = utils.RunCmd(["blockdev", "--getsize64", self.dev_path])
    if result.failed:
      ThrowError("blockdev failed (%s): %s",
                  result.fail_reason, result.output)
    try:
      sz = int(result.output.strip())
    except (ValueError, TypeError), err:
      ThrowError("Failed to parse blockdev output: %s", str(err))
    return sz

  def GetActualSpindles(self):
    """Return the actual number of spindles used.

    This is not supported by all devices; if not supported, C{None} is returned.

    @note: the device needs to be active when this is called

    """
    assert self.attached, "BlockDevice not attached in GetActualSpindles()"
    return None

  def GetActualDimensions(self):
    """Return the actual disk size and number of spindles used.

    @rtype: tuple
    @return: (size, spindles); spindles is C{None} when they are not supported

    @note: the device needs to be active when this is called

    """
    return (self.GetActualSize(), self.GetActualSpindles())

  def GetUserspaceAccessUri(self, hypervisor):
    """Return URIs hypervisors can use to access disks in userspace mode.

    @rtype: string
    @return: userspace device URI
    @raise errors.BlockDeviceError: if userspace access is not supported

    """
    ThrowError("Userspace access with %s block device and %s hypervisor is not "
               "supported." % (self.__class__.__name__,
                               hypervisor))

  def __repr__(self):
    return ("<%s: unique_id: %s, children: %s, %s:%s, %s>" %
            (self.__class__, self.unique_id, self._children,
             self.major, self.minor, self.dev_path))


def ThrowError(msg, *args):
  """Log an error to the node daemon and the raise an exception.

  @type msg: string
  @param msg: the text of the exception
  @raise errors.BlockDeviceError

  """
  if args:
    msg = msg % args
  logging.error(msg)
  raise errors.BlockDeviceError(msg)


def IgnoreError(fn, *args, **kwargs):
  """Executes the given function, ignoring BlockDeviceErrors.

  This is used in order to simplify the execution of cleanup or
  rollback functions.

  @rtype: boolean
  @return: True when fn didn't raise an exception, False otherwise

  """
  try:
    fn(*args, **kwargs)
    return True
  except errors.BlockDeviceError, err:
    logging.warning("Caught BlockDeviceError but ignoring: %s", str(err))
    return False
