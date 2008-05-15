#
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Block device abstraction"""

import re
import time
import errno
import pyparsing as pyp

from ganeti import utils
from ganeti import logger
from ganeti import errors
from ganeti import constants


class BlockDev(object):
  """Block device abstract class.

  A block device can be in the following states:
    - not existing on the system, and by `Create()` it goes into:
    - existing but not setup/not active, and by `Assemble()` goes into:
    - active read-write and by `Open()` it goes into
    - online (=used, or ready for use)

  A device can also be online but read-only, however we are not using
  the readonly state (MD and LV have it, if needed in the future)
  and we are usually looking at this like at a stack, so it's easier
  to conceptualise the transition from not-existing to online and back
  like a linear one.

  The many different states of the device are due to the fact that we
  need to cover many device types:
    - logical volumes are created, lvchange -a y $lv, and used
    - md arrays are created or assembled and used
    - drbd devices are attached to a local disk/remote peer and made primary

  The status of the device can be examined by `GetStatus()`, which
  returns a numerical value, depending on the position in the
  transition stack of the device.

  A block device is identified by three items:
    - the /dev path of the device (dynamic)
    - a unique ID of the device (static)
    - it's major/minor pair (dynamic)

  Not all devices implement both the first two as distinct items. LVM
  logical volumes have their unique ID (the pair volume group, logical
  volume name) in a 1-to-1 relation to the dev path. For MD devices,
  the /dev path is dynamic and the unique ID is the UUID generated at
  array creation plus the slave list. For DRBD devices, the /dev path
  is again dynamic and the unique id is the pair (host1, dev1),
  (host2, dev2).

  You can get to a device in two ways:
    - creating the (real) device, which returns you
      an attached instance (lvcreate, mdadm --create)
    - attaching of a python instance to an existing (real) device

  The second point, the attachement to a device, is different
  depending on whether the device is assembled or not. At init() time,
  we search for a device with the same unique_id as us. If found,
  good. It also means that the device is already assembled. If not,
  after assembly we'll have our correct major/minor.

  """
  STATUS_UNKNOWN = 0
  STATUS_EXISTING = 1
  STATUS_STANDBY = 2
  STATUS_ONLINE = 3

  STATUS_MAP = {
    STATUS_UNKNOWN: "unknown",
    STATUS_EXISTING: "existing",
    STATUS_STANDBY: "ready for use",
    STATUS_ONLINE: "online",
    }

  def __init__(self, unique_id, children):
    self._children = children
    self.dev_path = None
    self.unique_id = unique_id
    self.major = None
    self.minor = None

  def Assemble(self):
    """Assemble the device from its components.

    If this is a plain block device (e.g. LVM) than assemble does
    nothing, as the LVM has no children and we don't put logical
    volumes offline.

    One guarantee is that after the device has been assembled, it
    knows its major/minor numbers. This allows other devices (usually
    parents) to probe correctly for their children.

    """
    status = True
    for child in self._children:
      if not isinstance(child, BlockDev):
        raise TypeError("Invalid child passed of type '%s'" % type(child))
      if not status:
        break
      status = status and child.Assemble()
      if not status:
        break

      try:
        child.Open()
      except errors.BlockDeviceError:
        for child in self._children:
          child.Shutdown()
        raise

    if not status:
      for child in self._children:
        child.Shutdown()
    return status

  def Attach(self):
    """Find a device which matches our config and attach to it.

    """
    raise NotImplementedError

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    raise NotImplementedError

  @classmethod
  def Create(cls, unique_id, children, size):
    """Create the device.

    If the device cannot be created, it will return None
    instead. Error messages go to the logging system.

    Note that for some devices, the unique_id is used, and for other,
    the children. The idea is that these two, taken together, are
    enough for both creation and assembly (later).

    """
    raise NotImplementedError

  def Remove(self):
    """Remove this device.

    This makes sense only for some of the device types: LV and to a
    lesser degree, md devices. Also note that if the device can't
    attach, the removal can't be completed.

    """
    raise NotImplementedError

  def Rename(self, new_id):
    """Rename this device.

    This may or may not make sense for a given device type.

    """
    raise NotImplementedError

  def GetStatus(self):
    """Return the status of the device.

    """
    raise NotImplementedError

  def Open(self, force=False):
    """Make the device ready for use.

    This makes the device ready for I/O. For now, just the DRBD
    devices need this.

    The force parameter signifies that if the device has any kind of
    --force thing, it should be used, we know what we are doing.

    """
    raise NotImplementedError

  def Shutdown(self):
    """Shut down the device, freeing its children.

    This undoes the `Assemble()` work, except for the child
    assembling; as such, the children on the device are still
    assembled after this call.

    """
    raise NotImplementedError

  def SetSyncSpeed(self, speed):
    """Adjust the sync speed of the mirror.

    In case this is not a mirroring device, this is no-op.

    """
    result = True
    if self._children:
      for child in self._children:
        result = result and child.SetSyncSpeed(speed)
    return result

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    If this device is a mirroring device, this function returns the
    status of the mirror.

    Returns:
     (sync_percent, estimated_time, is_degraded, ldisk)

    If sync_percent is None, it means the device is not syncing.

    If estimated_time is None, it means we can't estimate
    the time needed, otherwise it's the time left in seconds.

    If is_degraded is True, it means the device is missing
    redundancy. This is usually a sign that something went wrong in
    the device setup, if sync_percent is None.

    The ldisk parameter represents the degradation of the local
    data. This is only valid for some devices, the rest will always
    return False (not degraded).

    """
    return None, None, False, False


  def CombinedSyncStatus(self):
    """Calculate the mirror status recursively for our children.

    The return value is the same as for `GetSyncStatus()` except the
    minimum percent and maximum time are calculated across our
    children.

    """
    min_percent, max_time, is_degraded, ldisk = self.GetSyncStatus()
    if self._children:
      for child in self._children:
        c_percent, c_time, c_degraded, c_ldisk = child.GetSyncStatus()
        if min_percent is None:
          min_percent = c_percent
        elif c_percent is not None:
          min_percent = min(min_percent, c_percent)
        if max_time is None:
          max_time = c_time
        elif c_time is not None:
          max_time = max(max_time, c_time)
        is_degraded = is_degraded or c_degraded
        ldisk = ldisk or c_ldisk
    return min_percent, max_time, is_degraded, ldisk


  def SetInfo(self, text):
    """Update metadata with info text.

    Only supported for some device types.

    """
    for child in self._children:
      child.SetInfo(text)


  def __repr__(self):
    return ("<%s: unique_id: %s, children: %s, %s:%s, %s>" %
            (self.__class__, self.unique_id, self._children,
             self.major, self.minor, self.dev_path))


class LogicalVolume(BlockDev):
  """Logical Volume block device.

  """
  def __init__(self, unique_id, children):
    """Attaches to a LV device.

    The unique_id is a tuple (vg_name, lv_name)

    """
    super(LogicalVolume, self).__init__(unique_id, children)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self._vg_name, self._lv_name = unique_id
    self.dev_path = "/dev/%s/%s" % (self._vg_name, self._lv_name)
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size):
    """Create a new logical volume.

    """
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    vg_name, lv_name = unique_id
    pvs_info = cls.GetPVInfo(vg_name)
    if not pvs_info:
      raise errors.BlockDeviceError("Can't compute PV info for vg %s" %
                                    vg_name)
    pvs_info.sort()
    pvs_info.reverse()

    pvlist = [ pv[1] for pv in pvs_info ]
    free_size = sum([ pv[0] for pv in pvs_info ])

    # The size constraint should have been checked from the master before
    # calling the create function.
    if free_size < size:
      raise errors.BlockDeviceError("Not enough free space: required %s,"
                                    " available %s" % (size, free_size))
    result = utils.RunCmd(["lvcreate", "-L%dm" % size, "-n%s" % lv_name,
                           vg_name] + pvlist)
    if result.failed:
      raise errors.BlockDeviceError("%s - %s" % (result.fail_reason,
                                                result.output))
    return LogicalVolume(unique_id, children)

  @staticmethod
  def GetPVInfo(vg_name):
    """Get the free space info for PVs in a volume group.

    Args:
      vg_name: the volume group name

    Returns:
      list of (free_space, name) with free_space in mebibytes

    """
    command = ["pvs", "--noheadings", "--nosuffix", "--units=m",
               "-opv_name,vg_name,pv_free,pv_attr", "--unbuffered",
               "--separator=:"]
    result = utils.RunCmd(command)
    if result.failed:
      logger.Error("Can't get the PV information: %s - %s" %
                   (result.fail_reason, result.output))
      return None
    data = []
    for line in result.stdout.splitlines():
      fields = line.strip().split(':')
      if len(fields) != 4:
        logger.Error("Can't parse pvs output: line '%s'" % line)
        return None
      # skip over pvs from another vg or ones which are not allocatable
      if fields[1] != vg_name or fields[3][0] != 'a':
        continue
      data.append((float(fields[2]), fields[0]))

    return data

  def Remove(self):
    """Remove this logical volume.

    """
    if not self.minor and not self.Attach():
      # the LV does not exist
      return True
    result = utils.RunCmd(["lvremove", "-f", "%s/%s" %
                           (self._vg_name, self._lv_name)])
    if result.failed:
      logger.Error("Can't lvremove: %s - %s" %
                   (result.fail_reason, result.output))

    return not result.failed

  def Rename(self, new_id):
    """Rename this logical volume.

    """
    if not isinstance(new_id, (tuple, list)) or len(new_id) != 2:
      raise errors.ProgrammerError("Invalid new logical id '%s'" % new_id)
    new_vg, new_name = new_id
    if new_vg != self._vg_name:
      raise errors.ProgrammerError("Can't move a logical volume across"
                                   " volume groups (from %s to to %s)" %
                                   (self._vg_name, new_vg))
    result = utils.RunCmd(["lvrename", new_vg, self._lv_name, new_name])
    if result.failed:
      raise errors.BlockDeviceError("Failed to rename the logical volume: %s" %
                                    result.output)
    self._lv_name = new_name
    self.dev_path = "/dev/%s/%s" % (self._vg_name, self._lv_name)

  def Attach(self):
    """Attach to an existing LV.

    This method will try to see if an existing and active LV exists
    which matches our name. If so, its major/minor will be
    recorded.

    """
    result = utils.RunCmd(["lvdisplay", self.dev_path])
    if result.failed:
      logger.Error("Can't find LV %s: %s, %s" %
                   (self.dev_path, result.fail_reason, result.output))
      return False
    match = re.compile("^ *Block device *([0-9]+):([0-9]+).*$")
    for line in result.stdout.splitlines():
      match_result = match.match(line)
      if match_result:
        self.major = int(match_result.group(1))
        self.minor = int(match_result.group(2))
        return True
    return False

  def Assemble(self):
    """Assemble the device.

    We alway run `lvchange -ay` on the LV to ensure it's active before
    use, as there were cases when xenvg was not active after boot
    (also possibly after disk issues).

    """
    result = utils.RunCmd(["lvchange", "-ay", self.dev_path])
    if result.failed:
      logger.Error("Can't activate lv %s: %s" % (self.dev_path, result.output))
    return not result.failed

  def Shutdown(self):
    """Shutdown the device.

    This is a no-op for the LV device type, as we don't deactivate the
    volumes on shutdown.

    """
    return True

  def GetStatus(self):
    """Return the status of the device.

    Logical volumes will can be in all four states, although we don't
    deactivate (lvchange -an) them when shutdown, so STATUS_EXISTING
    should not be seen for our devices.

    """
    result = utils.RunCmd(["lvs", "--noheadings", "-olv_attr", self.dev_path])
    if result.failed:
      logger.Error("Can't display lv: %s - %s" %
                   (result.fail_reason, result.output))
      return self.STATUS_UNKNOWN
    out = result.stdout.strip()
    # format: type/permissions/alloc/fixed_minor/state/open
    if len(out) != 6:
      return self.STATUS_UNKNOWN
    #writable = (out[1] == "w")
    active = (out[4] == "a")
    online = (out[5] == "o")
    if online:
      retval = self.STATUS_ONLINE
    elif active:
      retval = self.STATUS_STANDBY
    else:
      retval = self.STATUS_EXISTING

    return retval

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    If this device is a mirroring device, this function returns the
    status of the mirror.

    Returns:
     (sync_percent, estimated_time, is_degraded, ldisk)

    For logical volumes, sync_percent and estimated_time are always
    None (no recovery in progress, as we don't handle the mirrored LV
    case). The is_degraded parameter is the inverse of the ldisk
    parameter.

    For the ldisk parameter, we check if the logical volume has the
    'virtual' type, which means it's not backed by existing storage
    anymore (read from it return I/O error). This happens after a
    physical disk failure and subsequent 'vgreduce --removemissing' on
    the volume group.

    """
    result = utils.RunCmd(["lvs", "--noheadings", "-olv_attr", self.dev_path])
    if result.failed:
      logger.Error("Can't display lv: %s - %s" %
                   (result.fail_reason, result.output))
      return None, None, True, True
    out = result.stdout.strip()
    # format: type/permissions/alloc/fixed_minor/state/open
    if len(out) != 6:
      logger.Debug("Error in lvs output: attrs=%s, len != 6" % out)
      return None, None, True, True
    ldisk = out[0] == 'v' # virtual volume, i.e. doesn't have
                          # backing storage
    return None, None, ldisk, ldisk

  def Open(self, force=False):
    """Make the device ready for I/O.

    This is a no-op for the LV device type.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    This is a no-op for the LV device type.

    """
    pass

  def Snapshot(self, size):
    """Create a snapshot copy of an lvm block device.

    """
    snap_name = self._lv_name + ".snap"

    # remove existing snapshot if found
    snap = LogicalVolume((self._vg_name, snap_name), None)
    snap.Remove()

    pvs_info = self.GetPVInfo(self._vg_name)
    if not pvs_info:
      raise errors.BlockDeviceError("Can't compute PV info for vg %s" %
                                    self._vg_name)
    pvs_info.sort()
    pvs_info.reverse()
    free_size, pv_name = pvs_info[0]
    if free_size < size:
      raise errors.BlockDeviceError("Not enough free space: required %s,"
                                    " available %s" % (size, free_size))

    result = utils.RunCmd(["lvcreate", "-L%dm" % size, "-s",
                           "-n%s" % snap_name, self.dev_path])
    if result.failed:
      raise errors.BlockDeviceError("command: %s error: %s - %s" %
                                    (result.cmd, result.fail_reason,
                                     result.output))

    return snap_name

  def SetInfo(self, text):
    """Update metadata with info text.

    """
    BlockDev.SetInfo(self, text)

    # Replace invalid characters
    text = re.sub('^[^A-Za-z0-9_+.]', '_', text)
    text = re.sub('[^-A-Za-z0-9_+.]', '_', text)

    # Only up to 128 characters are allowed
    text = text[:128]

    result = utils.RunCmd(["lvchange", "--addtag", text,
                           self.dev_path])
    if result.failed:
      raise errors.BlockDeviceError("Command: %s error: %s - %s" %
                                    (result.cmd, result.fail_reason,
                                     result.output))


class MDRaid1(BlockDev):
  """raid1 device implemented via md.

  """
  def __init__(self, unique_id, children):
    super(MDRaid1, self).__init__(unique_id, children)
    self.major = 9
    self.Attach()

  def Attach(self):
    """Find an array which matches our config and attach to it.

    This tries to find a MD array which has the same UUID as our own.

    """
    minor = self._FindMDByUUID(self.unique_id)
    if minor is not None:
      self._SetFromMinor(minor)
    else:
      self.minor = None
      self.dev_path = None

    return (minor is not None)

  @staticmethod
  def _GetUsedDevs():
    """Compute the list of in-use MD devices.

    It doesn't matter if the used device have other raid level, just
    that they are in use.

    """
    mdstat = open("/proc/mdstat", "r")
    data = mdstat.readlines()
    mdstat.close()

    used_md = {}
    valid_line = re.compile("^md([0-9]+) : .*$")
    for line in data:
      match = valid_line.match(line)
      if match:
        md_no = int(match.group(1))
        used_md[md_no] = line

    return used_md

  @staticmethod
  def _GetDevInfo(minor):
    """Get info about a MD device.

    Currently only uuid is returned.

    """
    result = utils.RunCmd(["mdadm", "-D", "/dev/md%d" % minor])
    if result.failed:
      logger.Error("Can't display md: %s - %s" %
                   (result.fail_reason, result.output))
      return None
    retval = {}
    for line in result.stdout.splitlines():
      line = line.strip()
      kv = line.split(" : ", 1)
      if kv:
        if kv[0] == "UUID":
          retval["uuid"] = kv[1].split()[0]
        elif kv[0] == "State":
          retval["state"] = kv[1].split(", ")
    return retval

  @staticmethod
  def _FindUnusedMinor():
    """Compute an unused MD minor.

    This code assumes that there are 256 minors only.

    """
    used_md = MDRaid1._GetUsedDevs()
    i = 0
    while i < 256:
      if i not in used_md:
        break
      i += 1
    if i == 256:
      logger.Error("Critical: Out of md minor numbers.")
      raise errors.BlockDeviceError("Can't find a free MD minor")
    return i

  @classmethod
  def _FindMDByUUID(cls, uuid):
    """Find the minor of an MD array with a given UUID.

    """
    md_list = cls._GetUsedDevs()
    for minor in md_list:
      info = cls._GetDevInfo(minor)
      if info and info["uuid"] == uuid:
        return minor
    return None

  @staticmethod
  def _ZeroSuperblock(dev_path):
    """Zero the possible locations for an MD superblock.

    The zero-ing can't be done via ``mdadm --zero-superblock`` as that
    fails in versions 2.x with the same error code as non-writable
    device.

    The superblocks are located at (negative values are relative to
    the end of the block device):
      - -128k to end for version 0.90 superblock
      - -8k to -12k for version 1.0 superblock (included in the above)
      - 0k to 4k for version 1.1 superblock
      - 4k to 8k for version 1.2 superblock

    To cover all situations, the zero-ing will be:
      - 0k to 128k
      - -128k to end

    As such, the minimum device size must be 128k, otherwise we'll get
    I/O errors.

    Note that this function depends on the fact that one can open,
    read and write block devices normally.

    """
    overwrite_size = 128 * 1024
    empty_buf = '\0' * overwrite_size
    fd = open(dev_path, "r+")
    try:
      fd.seek(0, 0)
      p1 = fd.tell()
      fd.write(empty_buf)
      p2 = fd.tell()
      logger.Debug("Zeroed %s from %d to %d" % (dev_path, p1, p2))
      fd.seek(-overwrite_size, 2)
      p1 = fd.tell()
      fd.write(empty_buf)
      p2 = fd.tell()
      logger.Debug("Zeroed %s from %d to %d" % (dev_path, p1, p2))
    finally:
      fd.close()

  @classmethod
  def Create(cls, unique_id, children, size):
    """Create a new MD raid1 array.

    """
    if not isinstance(children, (tuple, list)):
      raise ValueError("Invalid setup data for MDRaid1 dev: %s" %
                       str(children))
    for i in children:
      if not isinstance(i, BlockDev):
        raise ValueError("Invalid member in MDRaid1 dev: %s" % type(i))
    for i in children:
      try:
        cls._ZeroSuperblock(i.dev_path)
      except EnvironmentError, err:
        logger.Error("Can't zero superblock for %s: %s" %
                     (i.dev_path, str(err)))
        return None
    minor = cls._FindUnusedMinor()
    result = utils.RunCmd(["mdadm", "--create", "/dev/md%d" % minor,
                           "--auto=yes", "--force", "-l1",
                           "-n%d" % len(children)] +
                          [dev.dev_path for dev in children])

    if result.failed:
      logger.Error("Can't create md: %s: %s" % (result.fail_reason,
                                                result.output))
      return None
    info = cls._GetDevInfo(minor)
    if not info or not "uuid" in info:
      logger.Error("Wrong information returned from mdadm -D: %s" % str(info))
      return None
    return MDRaid1(info["uuid"], children)

  def Remove(self):
    """Stub remove function for MD RAID 1 arrays.

    We don't remove the superblock right now. Mark a to do.

    """
    #TODO: maybe zero superblock on child devices?
    return self.Shutdown()

  def Rename(self, new_id):
    """Rename a device.

    This is not supported for md raid1 devices.

    """
    raise errors.ProgrammerError("Can't rename a md raid1 device")

  def AddChildren(self, devices):
    """Add new member(s) to the md raid1.

    """
    if self.minor is None and not self.Attach():
      raise errors.BlockDeviceError("Can't attach to device")

    args = ["mdadm", "-a", self.dev_path]
    for dev in devices:
      if dev.dev_path is None:
        raise errors.BlockDeviceError("Child '%s' is not initialised" % dev)
      dev.Open()
      args.append(dev.dev_path)
    result = utils.RunCmd(args)
    if result.failed:
      raise errors.BlockDeviceError("Failed to add new device to array: %s" %
                                    result.output)
    new_len = len(self._children) + len(devices)
    result = utils.RunCmd(["mdadm", "--grow", self.dev_path, "-n", new_len])
    if result.failed:
      raise errors.BlockDeviceError("Can't grow md array: %s" %
                                    result.output)
    self._children.extend(devices)

  def RemoveChildren(self, devices):
    """Remove member(s) from the md raid1.

    """
    if self.minor is None and not self.Attach():
      raise errors.BlockDeviceError("Can't attach to device")
    new_len = len(self._children) - len(devices)
    if new_len < 1:
      raise errors.BlockDeviceError("Can't reduce to less than one child")
    args = ["mdadm", "-f", self.dev_path]
    orig_devs = []
    for dev in devices:
      args.append(dev)
      for c in self._children:
        if c.dev_path == dev:
          orig_devs.append(c)
          break
      else:
        raise errors.BlockDeviceError("Can't find device '%s' for removal" %
                                      dev)
    result = utils.RunCmd(args)
    if result.failed:
      raise errors.BlockDeviceError("Failed to mark device(s) as failed: %s" %
                                    result.output)

    # it seems here we need a short delay for MD to update its
    # superblocks
    time.sleep(0.5)
    args[1] = "-r"
    result = utils.RunCmd(args)
    if result.failed:
      raise errors.BlockDeviceError("Failed to remove device(s) from array:"
                                    " %s" % result.output)
    result = utils.RunCmd(["mdadm", "--grow", "--force", self.dev_path,
                           "-n", new_len])
    if result.failed:
      raise errors.BlockDeviceError("Can't shrink md array: %s" %
                                    result.output)
    for dev in orig_devs:
      self._children.remove(dev)

  def GetStatus(self):
    """Return the status of the device.

    """
    self.Attach()
    if self.minor is None:
      retval = self.STATUS_UNKNOWN
    else:
      retval = self.STATUS_ONLINE
    return retval

  def _SetFromMinor(self, minor):
    """Set our parameters based on the given minor.

    This sets our minor variable and our dev_path.

    """
    self.minor = minor
    self.dev_path = "/dev/md%d" % minor

  def Assemble(self):
    """Assemble the MD device.

    At this point we should have:
      - list of children devices
      - uuid

    """
    result = super(MDRaid1, self).Assemble()
    if not result:
      return result
    md_list = self._GetUsedDevs()
    for minor in md_list:
      info = self._GetDevInfo(minor)
      if info and info["uuid"] == self.unique_id:
        self._SetFromMinor(minor)
        logger.Info("MD array %s already started" % str(self))
        return True
    free_minor = self._FindUnusedMinor()
    result = utils.RunCmd(["mdadm", "-A", "--auto=yes", "--uuid",
                           self.unique_id, "/dev/md%d" % free_minor] +
                          [bdev.dev_path for bdev in self._children])
    if result.failed:
      logger.Error("Can't assemble MD array: %s: %s" %
                   (result.fail_reason, result.output))
      self.minor = None
    else:
      self.minor = free_minor
    return not result.failed

  def Shutdown(self):
    """Tear down the MD array.

    This does a 'mdadm --stop' so after this command, the array is no
    longer available.

    """
    if self.minor is None and not self.Attach():
      logger.Info("MD object not attached to a device")
      return True

    result = utils.RunCmd(["mdadm", "--stop", "/dev/md%d" % self.minor])
    if result.failed:
      logger.Error("Can't stop MD array: %s - %s" %
                   (result.fail_reason, result.output))
      return False
    self.minor = None
    self.dev_path = None
    return True

  def SetSyncSpeed(self, kbytes):
    """Set the maximum sync speed for the MD array.

    """
    result = super(MDRaid1, self).SetSyncSpeed(kbytes)
    if self.minor is None:
      logger.Error("MD array not attached to a device")
      return False
    f = open("/sys/block/md%d/md/sync_speed_max" % self.minor, "w")
    try:
      f.write("%d" % kbytes)
    finally:
      f.close()
    f = open("/sys/block/md%d/md/sync_speed_min" % self.minor, "w")
    try:
      f.write("%d" % (kbytes/2))
    finally:
      f.close()
    return result

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    Returns:
     (sync_percent, estimated_time, is_degraded, ldisk)

    If sync_percent is None, it means all is ok
    If estimated_time is None, it means we can't esimate
    the time needed, otherwise it's the time left in seconds.

    The ldisk parameter is always true for MD devices.

    """
    if self.minor is None and not self.Attach():
      raise errors.BlockDeviceError("Can't attach to device in GetSyncStatus")
    dev_info = self._GetDevInfo(self.minor)
    is_clean = ("state" in dev_info and
                len(dev_info["state"]) == 1 and
                dev_info["state"][0] in ("clean", "active"))
    sys_path = "/sys/block/md%s/md/" % self.minor
    f = file(sys_path + "sync_action")
    sync_status = f.readline().strip()
    f.close()
    if sync_status == "idle":
      return None, None, not is_clean, False
    f = file(sys_path + "sync_completed")
    sync_completed = f.readline().strip().split(" / ")
    f.close()
    if len(sync_completed) != 2:
      return 0, None, not is_clean, False
    sync_done, sync_total = [float(i) for i in sync_completed]
    sync_percent = 100.0*sync_done/sync_total
    f = file(sys_path + "sync_speed")
    sync_speed_k = int(f.readline().strip())
    if sync_speed_k == 0:
      time_est = None
    else:
      time_est = (sync_total - sync_done) / 2 / sync_speed_k
    return sync_percent, time_est, not is_clean, False

  def Open(self, force=False):
    """Make the device ready for I/O.

    This is a no-op for the MDRaid1 device type, although we could use
    the 2.6.18's new array_state thing.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    This is a no-op for the MDRaid1 device type, but see comment for
    `Open()`.

    """
    pass


class BaseDRBD(BlockDev):
  """Base DRBD class.

  This class contains a few bits of common functionality between the
  0.7 and 8.x versions of DRBD.

  """
  _VERSION_RE = re.compile(r"^version: (\d+)\.(\d+)\.(\d+)"
                           r" \(api:(\d+)/proto:(\d+)(?:-(\d+))?\)")

  _DRBD_MAJOR = 147
  _ST_UNCONFIGURED = "Unconfigured"
  _ST_WFCONNECTION = "WFConnection"
  _ST_CONNECTED = "Connected"

  @staticmethod
  def _GetProcData():
    """Return data from /proc/drbd.

    """
    stat = open("/proc/drbd", "r")
    try:
      data = stat.read().splitlines()
    finally:
      stat.close()
    if not data:
      raise errors.BlockDeviceError("Can't read any data from /proc/drbd")
    return data

  @staticmethod
  def _MassageProcData(data):
    """Transform the output of _GetProdData into a nicer form.

    Returns:
      a dictionary of minor: joined lines from /proc/drbd for that minor

    """
    lmatch = re.compile("^ *([0-9]+):.*$")
    results = {}
    old_minor = old_line = None
    for line in data:
      lresult = lmatch.match(line)
      if lresult is not None:
        if old_minor is not None:
          results[old_minor] = old_line
        old_minor = int(lresult.group(1))
        old_line = line
      else:
        if old_minor is not None:
          old_line += " " + line.strip()
    # add last line
    if old_minor is not None:
      results[old_minor] = old_line
    return results

  @classmethod
  def _GetVersion(cls):
    """Return the DRBD version.

    This will return a dict with keys:
      k_major,
      k_minor,
      k_point,
      api,
      proto,
      proto2 (only on drbd > 8.2.X)

    """
    proc_data = cls._GetProcData()
    first_line = proc_data[0].strip()
    version = cls._VERSION_RE.match(first_line)
    if not version:
      raise errors.BlockDeviceError("Can't parse DRBD version from '%s'" %
                                    first_line)

    values = version.groups()
    retval = {'k_major': int(values[0]),
              'k_minor': int(values[1]),
              'k_point': int(values[2]),
              'api': int(values[3]),
              'proto': int(values[4]),
             }
    if values[5] is not None:
      retval['proto2'] = values[5]

    return retval

  @staticmethod
  def _DevPath(minor):
    """Return the path to a drbd device for a given minor.

    """
    return "/dev/drbd%d" % minor

  @classmethod
  def _GetUsedDevs(cls):
    """Compute the list of used DRBD devices.

    """
    data = cls._GetProcData()

    used_devs = {}
    valid_line = re.compile("^ *([0-9]+): cs:([^ ]+).*$")
    for line in data:
      match = valid_line.match(line)
      if not match:
        continue
      minor = int(match.group(1))
      state = match.group(2)
      if state == cls._ST_UNCONFIGURED:
        continue
      used_devs[minor] = state, line

    return used_devs

  def _SetFromMinor(self, minor):
    """Set our parameters based on the given minor.

    This sets our minor variable and our dev_path.

    """
    if minor is None:
      self.minor = self.dev_path = None
    else:
      self.minor = minor
      self.dev_path = self._DevPath(minor)

  @staticmethod
  def _CheckMetaSize(meta_device):
    """Check if the given meta device looks like a valid one.

    This currently only check the size, which must be around
    128MiB.

    """
    result = utils.RunCmd(["blockdev", "--getsize", meta_device])
    if result.failed:
      logger.Error("Failed to get device size: %s - %s" %
                   (result.fail_reason, result.output))
      return False
    try:
      sectors = int(result.stdout)
    except ValueError:
      logger.Error("Invalid output from blockdev: '%s'" % result.stdout)
      return False
    bytes = sectors * 512
    if bytes < 128 * 1024 * 1024: # less than 128MiB
      logger.Error("Meta device too small (%.2fMib)" % (bytes / 1024 / 1024))
      return False
    if bytes > (128 + 32) * 1024 * 1024: # account for an extra (big) PE on LVM
      logger.Error("Meta device too big (%.2fMiB)" % (bytes / 1024 / 1024))
      return False
    return True

  def Rename(self, new_id):
    """Rename a device.

    This is not supported for drbd devices.

    """
    raise errors.ProgrammerError("Can't rename a drbd device")


class DRBDev(BaseDRBD):
  """DRBD block device.

  This implements the local host part of the DRBD device, i.e. it
  doesn't do anything to the supposed peer. If you need a fully
  connected DRBD pair, you need to use this class on both hosts.

  The unique_id for the drbd device is the (local_ip, local_port,
  remote_ip, remote_port) tuple, and it must have two children: the
  data device and the meta_device. The meta device is checked for
  valid size and is zeroed on create.

  """
  def __init__(self, unique_id, children):
    super(DRBDev, self).__init__(unique_id, children)
    self.major = self._DRBD_MAJOR
    version = self._GetVersion()
    if version['k_major'] != 0 and version['k_minor'] != 7:
      raise errors.BlockDeviceError("Mismatch in DRBD kernel version and"
                                    " requested ganeti usage: kernel is"
                                    " %s.%s, ganeti wants 0.7" %
                                    (version['k_major'], version['k_minor']))
    if len(children) != 2:
      raise ValueError("Invalid configuration data %s" % str(children))
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 4:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self._lhost, self._lport, self._rhost, self._rport = unique_id
    self.Attach()

  @classmethod
  def _FindUnusedMinor(cls):
    """Find an unused DRBD device.

    """
    data = cls._GetProcData()

    valid_line = re.compile("^ *([0-9]+): cs:Unconfigured$")
    for line in data:
      match = valid_line.match(line)
      if match:
        return int(match.group(1))
    logger.Error("Error: no free drbd minors!")
    raise errors.BlockDeviceError("Can't find a free DRBD minor")

  @classmethod
  def _GetDevInfo(cls, minor):
    """Get details about a given DRBD minor.

    This return, if available, the local backing device in (major,
    minor) formant and the local and remote (ip, port) information.

    """
    data = {}
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "show"])
    if result.failed:
      logger.Error("Can't display the drbd config: %s - %s" %
                   (result.fail_reason, result.output))
      return data
    out = result.stdout
    if out == "Not configured\n":
      return data
    for line in out.splitlines():
      if "local_dev" not in data:
        match = re.match("^Lower device: ([0-9]+):([0-9]+) .*$", line)
        if match:
          data["local_dev"] = (int(match.group(1)), int(match.group(2)))
          continue
      if "meta_dev" not in data:
        match = re.match("^Meta device: (([0-9]+):([0-9]+)|internal).*$", line)
        if match:
          if match.group(2) is not None and match.group(3) is not None:
            # matched on the major/minor
            data["meta_dev"] = (int(match.group(2)), int(match.group(3)))
          else:
            # matched on the "internal" string
            data["meta_dev"] = match.group(1)
            # in this case, no meta_index is in the output
            data["meta_index"] = -1
          continue
      if "meta_index" not in data:
        match = re.match("^Meta index: ([0-9]+).*$", line)
        if match:
          data["meta_index"] = int(match.group(1))
          continue
      if "local_addr" not in data:
        match = re.match("^Local address: ([0-9.]+):([0-9]+)$", line)
        if match:
          data["local_addr"] = (match.group(1), int(match.group(2)))
          continue
      if "remote_addr" not in data:
        match = re.match("^Remote address: ([0-9.]+):([0-9]+)$", line)
        if match:
          data["remote_addr"] = (match.group(1), int(match.group(2)))
          continue
    return data

  def _MatchesLocal(self, info):
    """Test if our local config matches with an existing device.

    The parameter should be as returned from `_GetDevInfo()`. This
    method tests if our local backing device is the same as the one in
    the info parameter, in effect testing if we look like the given
    device.

    """
    if not ("local_dev" in info and "meta_dev" in info and
            "meta_index" in info):
      return False

    backend = self._children[0]
    if backend is not None:
      retval = (info["local_dev"] == (backend.major, backend.minor))
    else:
      retval = (info["local_dev"] == (0, 0))
    meta = self._children[1]
    if meta is not None:
      retval = retval and (info["meta_dev"] == (meta.major, meta.minor))
      retval = retval and (info["meta_index"] == 0)
    else:
      retval = retval and (info["meta_dev"] == "internal" and
                           info["meta_index"] == -1)
    return retval

  def _MatchesNet(self, info):
    """Test if our network config matches with an existing device.

    The parameter should be as returned from `_GetDevInfo()`. This
    method tests if our network configuration is the same as the one
    in the info parameter, in effect testing if we look like the given
    device.

    """
    if (((self._lhost is None and not ("local_addr" in info)) and
         (self._rhost is None and not ("remote_addr" in info)))):
      return True

    if self._lhost is None:
      return False

    if not ("local_addr" in info and
            "remote_addr" in info):
      return False

    retval = (info["local_addr"] == (self._lhost, self._lport))
    retval = (retval and
              info["remote_addr"] == (self._rhost, self._rport))
    return retval

  @classmethod
  def _AssembleLocal(cls, minor, backend, meta):
    """Configure the local part of a DRBD device.

    This is the first thing that must be done on an unconfigured DRBD
    device. And it must be done only once.

    """
    if not cls._CheckMetaSize(meta):
      return False
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "disk",
                           backend, meta, "0", "-e", "detach"])
    if result.failed:
      logger.Error("Can't attach local disk: %s" % result.output)
    return not result.failed

  @classmethod
  def _ShutdownLocal(cls, minor):
    """Detach from the local device.

    I/Os will continue to be served from the remote device. If we
    don't have a remote device, this operation will fail.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "detach"])
    if result.failed:
      logger.Error("Can't detach local device: %s" % result.output)
    return not result.failed

  @staticmethod
  def _ShutdownAll(minor):
    """Deactivate the device.

    This will, of course, fail if the device is in use.

    """
    result = utils.RunCmd(["drbdsetup", DRBDev._DevPath(minor), "down"])
    if result.failed:
      logger.Error("Can't shutdown drbd device: %s" % result.output)
    return not result.failed

  @classmethod
  def _AssembleNet(cls, minor, net_info, protocol):
    """Configure the network part of the device.

    This operation can be, in theory, done multiple times, but there
    have been cases (in lab testing) in which the network part of the
    device had become stuck and couldn't be shut down because activity
    from the new peer (also stuck) triggered a timer re-init and
    needed remote peer interface shutdown in order to clear. So please
    don't change online the net config.

    """
    lhost, lport, rhost, rport = net_info
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "net",
                           "%s:%s" % (lhost, lport), "%s:%s" % (rhost, rport),
                           protocol])
    if result.failed:
      logger.Error("Can't setup network for dbrd device: %s - %s" %
                   (result.fail_reason, result.output))
      return False

    timeout = time.time() + 10
    ok = False
    while time.time() < timeout:
      info = cls._GetDevInfo(minor)
      if not "local_addr" in info or not "remote_addr" in info:
        time.sleep(1)
        continue
      if (info["local_addr"] != (lhost, lport) or
          info["remote_addr"] != (rhost, rport)):
        time.sleep(1)
        continue
      ok = True
      break
    if not ok:
      logger.Error("Timeout while configuring network")
      return False
    return True

  @classmethod
  def _ShutdownNet(cls, minor):
    """Disconnect from the remote peer.

    This fails if we don't have a local device.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "disconnect"])
    if result.failed:
      logger.Error("Can't shutdown network: %s" % result.output)
    return not result.failed

  def Assemble(self):
    """Assemble the drbd.

    Method:
      - if we have a local backing device, we bind to it by:
        - checking the list of used drbd devices
        - check if the local minor use of any of them is our own device
        - if yes, abort?
        - if not, bind
      - if we have a local/remote net info:
        - redo the local backing device step for the remote device
        - check if any drbd device is using the local port,
          if yes abort
        - check if any remote drbd device is using the remote
          port, if yes abort (for now)
        - bind our net port
        - bind the remote net port

    """
    self.Attach()
    if self.minor is not None:
      logger.Info("Already assembled")
      return True

    result = super(DRBDev, self).Assemble()
    if not result:
      return result

    minor = self._FindUnusedMinor()
    need_localdev_teardown = False
    if self._children[0]:
      result = self._AssembleLocal(minor, self._children[0].dev_path,
                                   self._children[1].dev_path)
      if not result:
        return False
      need_localdev_teardown = True
    if self._lhost and self._lport and self._rhost and self._rport:
      result = self._AssembleNet(minor,
                                 (self._lhost, self._lport,
                                  self._rhost, self._rport),
                                 "C")
      if not result:
        if need_localdev_teardown:
          # we will ignore failures from this
          logger.Error("net setup failed, tearing down local device")
          self._ShutdownAll(minor)
        return False
    self._SetFromMinor(minor)
    return True

  def Shutdown(self):
    """Shutdown the DRBD device.

    """
    if self.minor is None and not self.Attach():
      logger.Info("DRBD device not attached to a device during Shutdown")
      return True
    if not self._ShutdownAll(self.minor):
      return False
    self.minor = None
    self.dev_path = None
    return True

  def Attach(self):
    """Find a DRBD device which matches our config and attach to it.

    In case of partially attached (local device matches but no network
    setup), we perform the network attach. If successful, we re-test
    the attach if can return success.

    """
    for minor in self._GetUsedDevs():
      info = self._GetDevInfo(minor)
      match_l = self._MatchesLocal(info)
      match_r = self._MatchesNet(info)
      if match_l and match_r:
        break
      if match_l and not match_r and "local_addr" not in info:
        res_r = self._AssembleNet(minor,
                                  (self._lhost, self._lport,
                                   self._rhost, self._rport),
                                  "C")
        if res_r and self._MatchesNet(self._GetDevInfo(minor)):
          break
    else:
      minor = None

    self._SetFromMinor(minor)
    return minor is not None

  def Open(self, force=False):
    """Make the local state primary.

    If the 'force' parameter is given, the '--do-what-I-say' option is
    is passed to drbdsetup. Since this is a potentially dangerous operation,
    the force flag should be only given after creation, when it actually
    is mandatory.

    """
    if self.minor is None and not self.Attach():
      logger.Error("DRBD cannot attach to a device during open")
      return False
    cmd = ["drbdsetup", self.dev_path, "primary"]
    if force:
      cmd.append("--do-what-I-say")
    result = utils.RunCmd(cmd)
    if result.failed:
      msg = ("Can't make drbd device primary: %s" % result.output)
      logger.Error(msg)
      raise errors.BlockDeviceError(msg)

  def Close(self):
    """Make the local state secondary.

    This will, of course, fail if the device is in use.

    """
    if self.minor is None and not self.Attach():
      logger.Info("Instance not attached to a device")
      raise errors.BlockDeviceError("Can't find device")
    result = utils.RunCmd(["drbdsetup", self.dev_path, "secondary"])
    if result.failed:
      msg = ("Can't switch drbd device to"
             " secondary: %s" % result.output)
      logger.Error(msg)
      raise errors.BlockDeviceError(msg)

  def SetSyncSpeed(self, kbytes):
    """Set the speed of the DRBD syncer.

    """
    children_result = super(DRBDev, self).SetSyncSpeed(kbytes)
    if self.minor is None:
      logger.Info("Instance not attached to a device")
      return False
    result = utils.RunCmd(["drbdsetup", self.dev_path, "syncer", "-r", "%d" %
                           kbytes])
    if result.failed:
      logger.Error("Can't change syncer rate: %s - %s" %
                   (result.fail_reason, result.output))
    return not result.failed and children_result

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    Returns:
     (sync_percent, estimated_time, is_degraded, ldisk)

    If sync_percent is None, it means all is ok
    If estimated_time is None, it means we can't esimate
    the time needed, otherwise it's the time left in seconds.

    The ldisk parameter will be returned as True, since the DRBD7
    devices have not been converted.

    """
    if self.minor is None and not self.Attach():
      raise errors.BlockDeviceError("Can't attach to device in GetSyncStatus")
    proc_info = self._MassageProcData(self._GetProcData())
    if self.minor not in proc_info:
      raise errors.BlockDeviceError("Can't find myself in /proc (minor %d)" %
                                    self.minor)
    line = proc_info[self.minor]
    match = re.match("^.*sync'ed: *([0-9.]+)%.*"
                     " finish: ([0-9]+):([0-9]+):([0-9]+) .*$", line)
    if match:
      sync_percent = float(match.group(1))
      hours = int(match.group(2))
      minutes = int(match.group(3))
      seconds = int(match.group(4))
      est_time = hours * 3600 + minutes * 60 + seconds
    else:
      sync_percent = None
      est_time = None
    match = re.match("^ *[0-9]+: cs:([^ ]+).*$", line)
    if not match:
      raise errors.BlockDeviceError("Can't find my data in /proc (minor %d)" %
                                    self.minor)
    client_state = match.group(1)
    is_degraded = client_state != "Connected"
    return sync_percent, est_time, is_degraded, False

  def GetStatus(self):
    """Compute the status of the DRBD device

    Note that DRBD devices don't have the STATUS_EXISTING state.

    """
    if self.minor is None and not self.Attach():
      return self.STATUS_UNKNOWN

    data = self._GetProcData()
    match = re.compile("^ *%d: cs:[^ ]+ st:(Primary|Secondary)/.*$" %
                       self.minor)
    for line in data:
      mresult = match.match(line)
      if mresult:
        break
    else:
      logger.Error("Can't find myself!")
      return self.STATUS_UNKNOWN

    state = mresult.group(2)
    if state == "Primary":
      result = self.STATUS_ONLINE
    else:
      result = self.STATUS_STANDBY

    return result

  @staticmethod
  def _ZeroDevice(device):
    """Zero a device.

    This writes until we get ENOSPC.

    """
    f = open(device, "w")
    buf = "\0" * 1048576
    try:
      while True:
        f.write(buf)
    except IOError, err:
      if err.errno != errno.ENOSPC:
        raise

  @classmethod
  def Create(cls, unique_id, children, size):
    """Create a new DRBD device.

    Since DRBD devices are not created per se, just assembled, this
    function just zeroes the meta device.

    """
    if len(children) != 2:
      raise errors.ProgrammerError("Invalid setup for the drbd device")
    meta = children[1]
    meta.Assemble()
    if not meta.Attach():
      raise errors.BlockDeviceError("Can't attach to meta device")
    if not cls._CheckMetaSize(meta.dev_path):
      raise errors.BlockDeviceError("Invalid meta device")
    logger.Info("Started zeroing device %s" % meta.dev_path)
    cls._ZeroDevice(meta.dev_path)
    logger.Info("Done zeroing device %s" % meta.dev_path)
    return cls(unique_id, children)

  def Remove(self):
    """Stub remove for DRBD devices.

    """
    return self.Shutdown()


class DRBD8(BaseDRBD):
  """DRBD v8.x block device.

  This implements the local host part of the DRBD device, i.e. it
  doesn't do anything to the supposed peer. If you need a fully
  connected DRBD pair, you need to use this class on both hosts.

  The unique_id for the drbd device is the (local_ip, local_port,
  remote_ip, remote_port) tuple, and it must have two children: the
  data device and the meta_device. The meta device is checked for
  valid size and is zeroed on create.

  """
  _MAX_MINORS = 255
  _PARSE_SHOW = None

  def __init__(self, unique_id, children):
    if children and children.count(None) > 0:
      children = []
    super(DRBD8, self).__init__(unique_id, children)
    self.major = self._DRBD_MAJOR
    version = self._GetVersion()
    if version['k_major'] != 8 :
      raise errors.BlockDeviceError("Mismatch in DRBD kernel version and"
                                    " requested ganeti usage: kernel is"
                                    " %s.%s, ganeti wants 8.x" %
                                    (version['k_major'], version['k_minor']))

    if len(children) not in (0, 2):
      raise ValueError("Invalid configuration data %s" % str(children))
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 4:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self._lhost, self._lport, self._rhost, self._rport = unique_id
    self.Attach()

  @classmethod
  def _InitMeta(cls, minor, dev_path):
    """Initialize a meta device.

    This will not work if the given minor is in use.

    """
    result = utils.RunCmd(["drbdmeta", "--force", cls._DevPath(minor),
                           "v08", dev_path, "0", "create-md"])
    if result.failed:
      raise errors.BlockDeviceError("Can't initialize meta device: %s" %
                                    result.output)

  @classmethod
  def _FindUnusedMinor(cls):
    """Find an unused DRBD device.

    This is specific to 8.x as the minors are allocated dynamically,
    so non-existing numbers up to a max minor count are actually free.

    """
    data = cls._GetProcData()

    unused_line = re.compile("^ *([0-9]+): cs:Unconfigured$")
    used_line = re.compile("^ *([0-9]+): cs:")
    highest = None
    for line in data:
      match = unused_line.match(line)
      if match:
        return int(match.group(1))
      match = used_line.match(line)
      if match:
        minor = int(match.group(1))
        highest = max(highest, minor)
    if highest is None: # there are no minors in use at all
      return 0
    if highest >= cls._MAX_MINORS:
      logger.Error("Error: no free drbd minors!")
      raise errors.BlockDeviceError("Can't find a free DRBD minor")
    return highest + 1

  @classmethod
  def _IsValidMeta(cls, meta_device):
    """Check if the given meta device looks like a valid one.

    """
    minor = cls._FindUnusedMinor()
    minor_path = cls._DevPath(minor)
    result = utils.RunCmd(["drbdmeta", minor_path,
                           "v08", meta_device, "0",
                           "dstate"])
    if result.failed:
      logger.Error("Invalid meta device %s: %s" % (meta_device, result.output))
      return False
    return True

  @classmethod
  def _GetShowParser(cls):
    """Return a parser for `drbd show` output.

    This will either create or return an already-create parser for the
    output of the command `drbd show`.

    """
    if cls._PARSE_SHOW is not None:
      return cls._PARSE_SHOW

    # pyparsing setup
    lbrace = pyp.Literal("{").suppress()
    rbrace = pyp.Literal("}").suppress()
    semi = pyp.Literal(";").suppress()
    # this also converts the value to an int
    number = pyp.Word(pyp.nums).setParseAction(lambda s, l, t: int(t[0]))

    comment = pyp.Literal ("#") + pyp.Optional(pyp.restOfLine)
    defa = pyp.Literal("_is_default").suppress()
    dbl_quote = pyp.Literal('"').suppress()

    keyword = pyp.Word(pyp.alphanums + '-')

    # value types
    value = pyp.Word(pyp.alphanums + '_-/.:')
    quoted = dbl_quote + pyp.CharsNotIn('"') + dbl_quote
    addr_port = (pyp.Word(pyp.nums + '.') + pyp.Literal(':').suppress() +
                 number)
    # meta device, extended syntax
    meta_value = ((value ^ quoted) + pyp.Literal('[').suppress() +
                  number + pyp.Word(']').suppress())

    # a statement
    stmt = (~rbrace + keyword + ~lbrace +
            (addr_port ^ value ^ quoted ^ meta_value) +
            pyp.Optional(defa) + semi +
            pyp.Optional(pyp.restOfLine).suppress())

    # an entire section
    section_name = pyp.Word(pyp.alphas + '_')
    section = section_name + lbrace + pyp.ZeroOrMore(pyp.Group(stmt)) + rbrace

    bnf = pyp.ZeroOrMore(pyp.Group(section ^ stmt))
    bnf.ignore(comment)

    cls._PARSE_SHOW = bnf

    return bnf

  @classmethod
  def _GetShowData(cls, minor):
    """Return the `drbdsetup show` data for a minor.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "show"])
    if result.failed:
      logger.Error("Can't display the drbd config: %s - %s" %
                   (result.fail_reason, result.output))
      return None
    return result.stdout

  @classmethod
  def _GetDevInfo(cls, out):
    """Parse details about a given DRBD minor.

    This return, if available, the local backing device (as a path)
    and the local and remote (ip, port) information from a string
    containing the output of the `drbdsetup show` command as returned
    by _GetShowData.

    """
    data = {}
    if not out:
      return data

    bnf = cls._GetShowParser()
    # run pyparse

    try:
      results = bnf.parseString(out)
    except pyp.ParseException, err:
      raise errors.BlockDeviceError("Can't parse drbdsetup show output: %s" %
                                    str(err))

    # and massage the results into our desired format
    for section in results:
      sname = section[0]
      if sname == "_this_host":
        for lst in section[1:]:
          if lst[0] == "disk":
            data["local_dev"] = lst[1]
          elif lst[0] == "meta-disk":
            data["meta_dev"] = lst[1]
            data["meta_index"] = lst[2]
          elif lst[0] == "address":
            data["local_addr"] = tuple(lst[1:])
      elif sname == "_remote_host":
        for lst in section[1:]:
          if lst[0] == "address":
            data["remote_addr"] = tuple(lst[1:])
    return data

  def _MatchesLocal(self, info):
    """Test if our local config matches with an existing device.

    The parameter should be as returned from `_GetDevInfo()`. This
    method tests if our local backing device is the same as the one in
    the info parameter, in effect testing if we look like the given
    device.

    """
    if self._children:
      backend, meta = self._children
    else:
      backend = meta = None

    if backend is not None:
      retval = ("local_dev" in info and info["local_dev"] == backend.dev_path)
    else:
      retval = ("local_dev" not in info)

    if meta is not None:
      retval = retval and ("meta_dev" in info and
                           info["meta_dev"] == meta.dev_path)
      retval = retval and ("meta_index" in info and
                           info["meta_index"] == 0)
    else:
      retval = retval and ("meta_dev" not in info and
                           "meta_index" not in info)
    return retval

  def _MatchesNet(self, info):
    """Test if our network config matches with an existing device.

    The parameter should be as returned from `_GetDevInfo()`. This
    method tests if our network configuration is the same as the one
    in the info parameter, in effect testing if we look like the given
    device.

    """
    if (((self._lhost is None and not ("local_addr" in info)) and
         (self._rhost is None and not ("remote_addr" in info)))):
      return True

    if self._lhost is None:
      return False

    if not ("local_addr" in info and
            "remote_addr" in info):
      return False

    retval = (info["local_addr"] == (self._lhost, self._lport))
    retval = (retval and
              info["remote_addr"] == (self._rhost, self._rport))
    return retval

  @classmethod
  def _AssembleLocal(cls, minor, backend, meta):
    """Configure the local part of a DRBD device.

    This is the first thing that must be done on an unconfigured DRBD
    device. And it must be done only once.

    """
    if not cls._IsValidMeta(meta):
      return False
    args = ["drbdsetup", cls._DevPath(minor), "disk",
            backend, meta, "0", "-e", "detach", "--create-device"]
    result = utils.RunCmd(args)
    if result.failed:
      logger.Error("Can't attach local disk: %s" % result.output)
    return not result.failed

  @classmethod
  def _AssembleNet(cls, minor, net_info, protocol,
                   dual_pri=False, hmac=None, secret=None):
    """Configure the network part of the device.

    """
    lhost, lport, rhost, rport = net_info
    if None in net_info:
      # we don't want network connection and actually want to make
      # sure its shutdown
      return cls._ShutdownNet(minor)

    args = ["drbdsetup", cls._DevPath(minor), "net",
            "%s:%s" % (lhost, lport), "%s:%s" % (rhost, rport), protocol,
            "-A", "discard-zero-changes",
            "-B", "consensus",
            "--create-device",
            ]
    if dual_pri:
      args.append("-m")
    if hmac and secret:
      args.extend(["-a", hmac, "-x", secret])
    result = utils.RunCmd(args)
    if result.failed:
      logger.Error("Can't setup network for dbrd device: %s - %s" %
                   (result.fail_reason, result.output))
      return False

    timeout = time.time() + 10
    ok = False
    while time.time() < timeout:
      info = cls._GetDevInfo(cls._GetShowData(minor))
      if not "local_addr" in info or not "remote_addr" in info:
        time.sleep(1)
        continue
      if (info["local_addr"] != (lhost, lport) or
          info["remote_addr"] != (rhost, rport)):
        time.sleep(1)
        continue
      ok = True
      break
    if not ok:
      logger.Error("Timeout while configuring network")
      return False
    return True

  def AddChildren(self, devices):
    """Add a disk to the DRBD device.

    """
    if self.minor is None:
      raise errors.BlockDeviceError("Can't attach to dbrd8 during AddChildren")
    if len(devices) != 2:
      raise errors.BlockDeviceError("Need two devices for AddChildren")
    info = self._GetDevInfo(self._GetShowData(self.minor))
    if "local_dev" in info:
      raise errors.BlockDeviceError("DRBD8 already attached to a local disk")
    backend, meta = devices
    if backend.dev_path is None or meta.dev_path is None:
      raise errors.BlockDeviceError("Children not ready during AddChildren")
    backend.Open()
    meta.Open()
    if not self._CheckMetaSize(meta.dev_path):
      raise errors.BlockDeviceError("Invalid meta device size")
    self._InitMeta(self._FindUnusedMinor(), meta.dev_path)
    if not self._IsValidMeta(meta.dev_path):
      raise errors.BlockDeviceError("Cannot initalize meta device")

    if not self._AssembleLocal(self.minor, backend.dev_path, meta.dev_path):
      raise errors.BlockDeviceError("Can't attach to local storage")
    self._children = devices

  def RemoveChildren(self, devices):
    """Detach the drbd device from local storage.

    """
    if self.minor is None:
      raise errors.BlockDeviceError("Can't attach to drbd8 during"
                                    " RemoveChildren")
    # early return if we don't actually have backing storage
    info = self._GetDevInfo(self._GetShowData(self.minor))
    if "local_dev" not in info:
      return
    if len(self._children) != 2:
      raise errors.BlockDeviceError("We don't have two children: %s" %
                                    self._children)
    if self._children.count(None) == 2: # we don't actually have children :)
      logger.Error("Requested detach while detached")
      return
    if len(devices) != 2:
      raise errors.BlockDeviceError("We need two children in RemoveChildren")
    for child, dev in zip(self._children, devices):
      if dev != child.dev_path:
        raise errors.BlockDeviceError("Mismatch in local storage"
                                      " (%s != %s) in RemoveChildren" %
                                      (dev, child.dev_path))

    if not self._ShutdownLocal(self.minor):
      raise errors.BlockDeviceError("Can't detach from local storage")
    self._children = []

  def SetSyncSpeed(self, kbytes):
    """Set the speed of the DRBD syncer.

    """
    children_result = super(DRBD8, self).SetSyncSpeed(kbytes)
    if self.minor is None:
      logger.Info("Instance not attached to a device")
      return False
    result = utils.RunCmd(["drbdsetup", self.dev_path, "syncer", "-r", "%d" %
                           kbytes])
    if result.failed:
      logger.Error("Can't change syncer rate: %s - %s" %
                   (result.fail_reason, result.output))
    return not result.failed and children_result

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    Returns:
     (sync_percent, estimated_time, is_degraded)

    If sync_percent is None, it means all is ok
    If estimated_time is None, it means we can't esimate
    the time needed, otherwise it's the time left in seconds.


    We set the is_degraded parameter to True on two conditions:
    network not connected or local disk missing.

    We compute the ldisk parameter based on wheter we have a local
    disk or not.

    """
    if self.minor is None and not self.Attach():
      raise errors.BlockDeviceError("Can't attach to device in GetSyncStatus")
    proc_info = self._MassageProcData(self._GetProcData())
    if self.minor not in proc_info:
      raise errors.BlockDeviceError("Can't find myself in /proc (minor %d)" %
                                    self.minor)
    line = proc_info[self.minor]
    match = re.match("^.*sync'ed: *([0-9.]+)%.*"
                     " finish: ([0-9]+):([0-9]+):([0-9]+) .*$", line)
    if match:
      sync_percent = float(match.group(1))
      hours = int(match.group(2))
      minutes = int(match.group(3))
      seconds = int(match.group(4))
      est_time = hours * 3600 + minutes * 60 + seconds
    else:
      sync_percent = None
      est_time = None
    match = re.match("^ *\d+: cs:(\w+).*ds:(\w+)/(\w+).*$", line)
    if not match:
      raise errors.BlockDeviceError("Can't find my data in /proc (minor %d)" %
                                    self.minor)
    client_state = match.group(1)
    local_disk_state = match.group(2)
    ldisk = local_disk_state != "UpToDate"
    is_degraded = client_state != "Connected"
    return sync_percent, est_time, is_degraded or ldisk, ldisk

  def GetStatus(self):
    """Compute the status of the DRBD device

    Note that DRBD devices don't have the STATUS_EXISTING state.

    """
    if self.minor is None and not self.Attach():
      return self.STATUS_UNKNOWN

    data = self._GetProcData()
    match = re.compile("^ *%d: cs:[^ ]+ st:(Primary|Secondary)/.*$" %
                       self.minor)
    for line in data:
      mresult = match.match(line)
      if mresult:
        break
    else:
      logger.Error("Can't find myself!")
      return self.STATUS_UNKNOWN

    state = mresult.group(2)
    if state == "Primary":
      result = self.STATUS_ONLINE
    else:
      result = self.STATUS_STANDBY

    return result

  def Open(self, force=False):
    """Make the local state primary.

    If the 'force' parameter is given, the '-o' option is passed to
    drbdsetup. Since this is a potentially dangerous operation, the
    force flag should be only given after creation, when it actually
    is mandatory.

    """
    if self.minor is None and not self.Attach():
      logger.Error("DRBD cannot attach to a device during open")
      return False
    cmd = ["drbdsetup", self.dev_path, "primary"]
    if force:
      cmd.append("-o")
    result = utils.RunCmd(cmd)
    if result.failed:
      msg = ("Can't make drbd device primary: %s" % result.output)
      logger.Error(msg)
      raise errors.BlockDeviceError(msg)

  def Close(self):
    """Make the local state secondary.

    This will, of course, fail if the device is in use.

    """
    if self.minor is None and not self.Attach():
      logger.Info("Instance not attached to a device")
      raise errors.BlockDeviceError("Can't find device")
    result = utils.RunCmd(["drbdsetup", self.dev_path, "secondary"])
    if result.failed:
      msg = ("Can't switch drbd device to"
             " secondary: %s" % result.output)
      logger.Error(msg)
      raise errors.BlockDeviceError(msg)

  def Attach(self):
    """Find a DRBD device which matches our config and attach to it.

    In case of partially attached (local device matches but no network
    setup), we perform the network attach. If successful, we re-test
    the attach if can return success.

    """
    for minor in self._GetUsedDevs():
      info = self._GetDevInfo(self._GetShowData(minor))
      match_l = self._MatchesLocal(info)
      match_r = self._MatchesNet(info)
      if match_l and match_r:
        break
      if match_l and not match_r and "local_addr" not in info:
        res_r = self._AssembleNet(minor,
                                  (self._lhost, self._lport,
                                   self._rhost, self._rport),
                                  "C")
        if res_r:
          if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
            break
      # the weakest case: we find something that is only net attached
      # even though we were passed some children at init time
      if match_r and "local_dev" not in info:
        break

      # this case must be considered only if we actually have local
      # storage, i.e. not in diskless mode, because all diskless
      # devices are equal from the point of view of local
      # configuration
      if (match_l and "local_dev" in info and
          not match_r and "local_addr" in info):
        # strange case - the device network part points to somewhere
        # else, even though its local storage is ours; as we own the
        # drbd space, we try to disconnect from the remote peer and
        # reconnect to our correct one
        if not self._ShutdownNet(minor):
          raise errors.BlockDeviceError("Device has correct local storage,"
                                        " wrong remote peer and is unable to"
                                        " disconnect in order to attach to"
                                        " the correct peer")
        # note: _AssembleNet also handles the case when we don't want
        # local storage (i.e. one or more of the _[lr](host|port) is
        # None)
        if (self._AssembleNet(minor, (self._lhost, self._lport,
                                      self._rhost, self._rport), "C") and
            self._MatchesNet(self._GetDevInfo(self._GetShowData(minor)))):
          break

    else:
      minor = None

    self._SetFromMinor(minor)
    return minor is not None

  def Assemble(self):
    """Assemble the drbd.

    Method:
      - if we have a local backing device, we bind to it by:
        - checking the list of used drbd devices
        - check if the local minor use of any of them is our own device
        - if yes, abort?
        - if not, bind
      - if we have a local/remote net info:
        - redo the local backing device step for the remote device
        - check if any drbd device is using the local port,
          if yes abort
        - check if any remote drbd device is using the remote
          port, if yes abort (for now)
        - bind our net port
        - bind the remote net port

    """
    self.Attach()
    if self.minor is not None:
      logger.Info("Already assembled")
      return True

    result = super(DRBD8, self).Assemble()
    if not result:
      return result

    minor = self._FindUnusedMinor()
    need_localdev_teardown = False
    if self._children and self._children[0] and self._children[1]:
      result = self._AssembleLocal(minor, self._children[0].dev_path,
                                   self._children[1].dev_path)
      if not result:
        return False
      need_localdev_teardown = True
    if self._lhost and self._lport and self._rhost and self._rport:
      result = self._AssembleNet(minor,
                                 (self._lhost, self._lport,
                                  self._rhost, self._rport),
                                 "C")
      if not result:
        if need_localdev_teardown:
          # we will ignore failures from this
          logger.Error("net setup failed, tearing down local device")
          self._ShutdownAll(minor)
        return False
    self._SetFromMinor(minor)
    return True

  @classmethod
  def _ShutdownLocal(cls, minor):
    """Detach from the local device.

    I/Os will continue to be served from the remote device. If we
    don't have a remote device, this operation will fail.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "detach"])
    if result.failed:
      logger.Error("Can't detach local device: %s" % result.output)
    return not result.failed

  @classmethod
  def _ShutdownNet(cls, minor):
    """Disconnect from the remote peer.

    This fails if we don't have a local device.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "disconnect"])
    if result.failed:
      logger.Error("Can't shutdown network: %s" % result.output)
    return not result.failed

  @classmethod
  def _ShutdownAll(cls, minor):
    """Deactivate the device.

    This will, of course, fail if the device is in use.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "down"])
    if result.failed:
      logger.Error("Can't shutdown drbd device: %s" % result.output)
    return not result.failed

  def Shutdown(self):
    """Shutdown the DRBD device.

    """
    if self.minor is None and not self.Attach():
      logger.Info("DRBD device not attached to a device during Shutdown")
      return True
    if not self._ShutdownAll(self.minor):
      return False
    self.minor = None
    self.dev_path = None
    return True

  def Remove(self):
    """Stub remove for DRBD devices.

    """
    return self.Shutdown()

  @classmethod
  def Create(cls, unique_id, children, size):
    """Create a new DRBD8 device.

    Since DRBD devices are not created per se, just assembled, this
    function only initializes the metadata.

    """
    if len(children) != 2:
      raise errors.ProgrammerError("Invalid setup for the drbd device")
    meta = children[1]
    meta.Assemble()
    if not meta.Attach():
      raise errors.BlockDeviceError("Can't attach to meta device")
    if not cls._CheckMetaSize(meta.dev_path):
      raise errors.BlockDeviceError("Invalid meta device size")
    cls._InitMeta(cls._FindUnusedMinor(), meta.dev_path)
    if not cls._IsValidMeta(meta.dev_path):
      raise errors.BlockDeviceError("Cannot initalize meta device")
    return cls(unique_id, children)


DEV_MAP = {
  constants.LD_LV: LogicalVolume,
  constants.LD_MD_R1: MDRaid1,
  constants.LD_DRBD7: DRBDev,
  constants.LD_DRBD8: DRBD8,
  }


def FindDevice(dev_type, unique_id, children):
  """Search for an existing, assembled device.

  This will succeed only if the device exists and is assembled, but it
  does not do any actions in order to activate the device.

  """
  if dev_type not in DEV_MAP:
    raise errors.ProgrammerError("Invalid block device type '%s'" % dev_type)
  device = DEV_MAP[dev_type](unique_id, children)
  if not device.Attach():
    return None
  return  device


def AttachOrAssemble(dev_type, unique_id, children):
  """Try to attach or assemble an existing device.

  This will attach to an existing assembled device or will assemble
  the device, as needed, to bring it fully up.

  """
  if dev_type not in DEV_MAP:
    raise errors.ProgrammerError("Invalid block device type '%s'" % dev_type)
  device = DEV_MAP[dev_type](unique_id, children)
  if not device.Attach():
    device.Assemble()
    if not device.Attach():
      raise errors.BlockDeviceError("Can't find a valid block device for"
                                    " %s/%s/%s" %
                                    (dev_type, unique_id, children))
  return device


def Create(dev_type, unique_id, children, size):
  """Create a device.

  """
  if dev_type not in DEV_MAP:
    raise errors.ProgrammerError("Invalid block device type '%s'" % dev_type)
  device = DEV_MAP[dev_type].Create(unique_id, children, size)
  return device
