#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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
import shlex
import stat
import pyparsing as pyp
import os
import logging

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import objects
from ganeti import compat
from ganeti import netutils


# Size of reads in _CanReadDevice
_DEVICE_READ_SIZE = 128 * 1024


def _IgnoreError(fn, *args, **kwargs):
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


def _ThrowError(msg, *args):
  """Log an error to the node daemon and the raise an exception.

  @type msg: string
  @param msg: the text of the exception
  @raise errors.BlockDeviceError

  """
  if args:
    msg = msg % args
  logging.error(msg)
  raise errors.BlockDeviceError(msg)


def _CanReadDevice(path):
  """Check if we can read from the given device.

  This tries to read the first 128k of the device.

  """
  try:
    utils.ReadFile(path, size=_DEVICE_READ_SIZE)
    return True
  except EnvironmentError:
    logging.warning("Can't read from device %s", path, exc_info=True)
    return False


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

  The second point, the attachement to a device, is different
  depending on whether the device is assembled or not. At init() time,
  we search for a device with the same unique_id as us. If found,
  good. It also means that the device is already assembled. If not,
  after assembly we'll have our correct major/minor.

  """
  def __init__(self, unique_id, children, size, params):
    self._children = children
    self.dev_path = None
    self.unique_id = unique_id
    self.major = None
    self.minor = None
    self.attached = False
    self.size = size
    self.params = params

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
  def Create(cls, unique_id, children, size, params):
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

  def Grow(self, amount, dryrun):
    """Grow the block device.

    @type amount: integer
    @param amount: the amount (in mebibytes) to grow with
    @type dryrun: boolean
    @param dryrun: whether to execute the operation in simulation mode
        only, without actually increasing the size

    """
    raise NotImplementedError

  def GetActualSize(self):
    """Return the actual disk size.

    @note: the device needs to be active when this is called

    """
    assert self.attached, "BlockDevice not attached in GetActualSize()"
    result = utils.RunCmd(["blockdev", "--getsize64", self.dev_path])
    if result.failed:
      _ThrowError("blockdev failed (%s): %s",
                  result.fail_reason, result.output)
    try:
      sz = int(result.output.strip())
    except (ValueError, TypeError), err:
      _ThrowError("Failed to parse blockdev output: %s", str(err))
    return sz

  def __repr__(self):
    return ("<%s: unique_id: %s, children: %s, %s:%s, %s>" %
            (self.__class__, self.unique_id, self._children,
             self.major, self.minor, self.dev_path))


class LogicalVolume(BlockDev):
  """Logical Volume block device.

  """
  _VALID_NAME_RE = re.compile("^[a-zA-Z0-9+_.-]*$")
  _INVALID_NAMES = frozenset([".", "..", "snapshot", "pvmove"])
  _INVALID_SUBSTRINGS = frozenset(["_mlog", "_mimage"])

  def __init__(self, unique_id, children, size, params):
    """Attaches to a LV device.

    The unique_id is a tuple (vg_name, lv_name)

    """
    super(LogicalVolume, self).__init__(unique_id, children, size, params)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self._vg_name, self._lv_name = unique_id
    self._ValidateName(self._vg_name)
    self._ValidateName(self._lv_name)
    self.dev_path = utils.PathJoin("/dev", self._vg_name, self._lv_name)
    self._degraded = True
    self.major = self.minor = self.pe_size = self.stripe_count = None
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size, params):
    """Create a new logical volume.

    """
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise errors.ProgrammerError("Invalid configuration data %s" %
                                   str(unique_id))
    vg_name, lv_name = unique_id
    cls._ValidateName(vg_name)
    cls._ValidateName(lv_name)
    pvs_info = cls.GetPVInfo([vg_name])
    if not pvs_info:
      _ThrowError("Can't compute PV info for vg %s", vg_name)
    pvs_info.sort()
    pvs_info.reverse()

    pvlist = [pv[1] for pv in pvs_info]
    if compat.any(":" in v for v in pvlist):
      _ThrowError("Some of your PVs have the invalid character ':' in their"
                  " name, this is not supported - please filter them out"
                  " in lvm.conf using either 'filter' or 'preferred_names'")
    free_size = sum([pv[0] for pv in pvs_info])
    current_pvs = len(pvlist)
    desired_stripes = params[constants.LDP_STRIPES]
    stripes = min(current_pvs, desired_stripes)
    if stripes < desired_stripes:
      logging.warning("Could not use %d stripes for VG %s, as only %d PVs are"
                      " available.", desired_stripes, vg_name, current_pvs)

    # The size constraint should have been checked from the master before
    # calling the create function.
    if free_size < size:
      _ThrowError("Not enough free space: required %s,"
                  " available %s", size, free_size)
    cmd = ["lvcreate", "-L%dm" % size, "-n%s" % lv_name]
    # If the free space is not well distributed, we won't be able to
    # create an optimally-striped volume; in that case, we want to try
    # with N, N-1, ..., 2, and finally 1 (non-stripped) number of
    # stripes
    for stripes_arg in range(stripes, 0, -1):
      result = utils.RunCmd(cmd + ["-i%d" % stripes_arg] + [vg_name] + pvlist)
      if not result.failed:
        break
    if result.failed:
      _ThrowError("LV create failed (%s): %s",
                  result.fail_reason, result.output)
    return LogicalVolume(unique_id, children, size, params)

  @staticmethod
  def _GetVolumeInfo(lvm_cmd, fields):
    """Returns LVM Volumen infos using lvm_cmd

    @param lvm_cmd: Should be one of "pvs", "vgs" or "lvs"
    @param fields: Fields to return
    @return: A list of dicts each with the parsed fields

    """
    if not fields:
      raise errors.ProgrammerError("No fields specified")

    sep = "|"
    cmd = [lvm_cmd, "--noheadings", "--nosuffix", "--units=m", "--unbuffered",
           "--separator=%s" % sep, "-o%s" % ",".join(fields)]

    result = utils.RunCmd(cmd)
    if result.failed:
      raise errors.CommandError("Can't get the volume information: %s - %s" %
                                (result.fail_reason, result.output))

    data = []
    for line in result.stdout.splitlines():
      splitted_fields = line.strip().split(sep)

      if len(fields) != len(splitted_fields):
        raise errors.CommandError("Can't parse %s output: line '%s'" %
                                  (lvm_cmd, line))

      data.append(splitted_fields)

    return data

  @classmethod
  def GetPVInfo(cls, vg_names, filter_allocatable=True):
    """Get the free space info for PVs in a volume group.

    @param vg_names: list of volume group names, if empty all will be returned
    @param filter_allocatable: whether to skip over unallocatable PVs

    @rtype: list
    @return: list of tuples (free_space, name) with free_space in mebibytes

    """
    try:
      info = cls._GetVolumeInfo("pvs", ["pv_name", "vg_name", "pv_free",
                                        "pv_attr"])
    except errors.GenericError, err:
      logging.error("Can't get PV information: %s", err)
      return None

    data = []
    for pv_name, vg_name, pv_free, pv_attr in info:
      # (possibly) skip over pvs which are not allocatable
      if filter_allocatable and pv_attr[0] != "a":
        continue
      # (possibly) skip over pvs which are not in the right volume group(s)
      if vg_names and vg_name not in vg_names:
        continue
      data.append((float(pv_free), pv_name, vg_name))

    return data

  @classmethod
  def GetVGInfo(cls, vg_names, filter_readonly=True):
    """Get the free space info for specific VGs.

    @param vg_names: list of volume group names, if empty all will be returned
    @param filter_readonly: whether to skip over readonly VGs

    @rtype: list
    @return: list of tuples (free_space, total_size, name) with free_space in
             MiB

    """
    try:
      info = cls._GetVolumeInfo("vgs", ["vg_name", "vg_free", "vg_attr",
                                        "vg_size"])
    except errors.GenericError, err:
      logging.error("Can't get VG information: %s", err)
      return None

    data = []
    for vg_name, vg_free, vg_attr, vg_size in info:
      # (possibly) skip over vgs which are not writable
      if filter_readonly and vg_attr[0] == "r":
        continue
      # (possibly) skip over vgs which are not in the right volume group(s)
      if vg_names and vg_name not in vg_names:
        continue
      data.append((float(vg_free), float(vg_size), vg_name))

    return data

  @classmethod
  def _ValidateName(cls, name):
    """Validates that a given name is valid as VG or LV name.

    The list of valid characters and restricted names is taken out of
    the lvm(8) manpage, with the simplification that we enforce both
    VG and LV restrictions on the names.

    """
    if (not cls._VALID_NAME_RE.match(name) or
        name in cls._INVALID_NAMES or
        compat.any(substring in name for substring in cls._INVALID_SUBSTRINGS)):
      _ThrowError("Invalid LVM name '%s'", name)

  def Remove(self):
    """Remove this logical volume.

    """
    if not self.minor and not self.Attach():
      # the LV does not exist
      return
    result = utils.RunCmd(["lvremove", "-f", "%s/%s" %
                           (self._vg_name, self._lv_name)])
    if result.failed:
      _ThrowError("Can't lvremove: %s - %s", result.fail_reason, result.output)

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
      _ThrowError("Failed to rename the logical volume: %s", result.output)
    self._lv_name = new_name
    self.dev_path = utils.PathJoin("/dev", self._vg_name, self._lv_name)

  def Attach(self):
    """Attach to an existing LV.

    This method will try to see if an existing and active LV exists
    which matches our name. If so, its major/minor will be
    recorded.

    """
    self.attached = False
    result = utils.RunCmd(["lvs", "--noheadings", "--separator=,",
                           "--units=m", "--nosuffix",
                           "-olv_attr,lv_kernel_major,lv_kernel_minor,"
                           "vg_extent_size,stripes", self.dev_path])
    if result.failed:
      logging.error("Can't find LV %s: %s, %s",
                    self.dev_path, result.fail_reason, result.output)
      return False
    # the output can (and will) have multiple lines for multi-segment
    # LVs, as the 'stripes' parameter is a segment one, so we take
    # only the last entry, which is the one we're interested in; note
    # that with LVM2 anyway the 'stripes' value must be constant
    # across segments, so this is a no-op actually
    out = result.stdout.splitlines()
    if not out: # totally empty result? splitlines() returns at least
                # one line for any non-empty string
      logging.error("Can't parse LVS output, no lines? Got '%s'", str(out))
      return False
    out = out[-1].strip().rstrip(",")
    out = out.split(",")
    if len(out) != 5:
      logging.error("Can't parse LVS output, len(%s) != 5", str(out))
      return False

    status, major, minor, pe_size, stripes = out
    if len(status) < 6:
      logging.error("lvs lv_attr is not at least 6 characters (%s)", status)
      return False

    try:
      major = int(major)
      minor = int(minor)
    except (TypeError, ValueError), err:
      logging.error("lvs major/minor cannot be parsed: %s", str(err))

    try:
      pe_size = int(float(pe_size))
    except (TypeError, ValueError), err:
      logging.error("Can't parse vg extent size: %s", err)
      return False

    try:
      stripes = int(stripes)
    except (TypeError, ValueError), err:
      logging.error("Can't parse the number of stripes: %s", err)
      return False

    self.major = major
    self.minor = minor
    self.pe_size = pe_size
    self.stripe_count = stripes
    self._degraded = status[0] == "v" # virtual volume, i.e. doesn't backing
                                      # storage
    self.attached = True
    return True

  def Assemble(self):
    """Assemble the device.

    We always run `lvchange -ay` on the LV to ensure it's active before
    use, as there were cases when xenvg was not active after boot
    (also possibly after disk issues).

    """
    result = utils.RunCmd(["lvchange", "-ay", self.dev_path])
    if result.failed:
      _ThrowError("Can't activate lv %s: %s", self.dev_path, result.output)

  def Shutdown(self):
    """Shutdown the device.

    This is a no-op for the LV device type, as we don't deactivate the
    volumes on shutdown.

    """
    pass

  def GetSyncStatus(self):
    """Returns the sync status of the device.

    If this device is a mirroring device, this function returns the
    status of the mirror.

    For logical volumes, sync_percent and estimated_time are always
    None (no recovery in progress, as we don't handle the mirrored LV
    case). The is_degraded parameter is the inverse of the ldisk
    parameter.

    For the ldisk parameter, we check if the logical volume has the
    'virtual' type, which means it's not backed by existing storage
    anymore (read from it return I/O error). This happens after a
    physical disk failure and subsequent 'vgreduce --removemissing' on
    the volume group.

    The status was already read in Attach, so we just return it.

    @rtype: objects.BlockDevStatus

    """
    if self._degraded:
      ldisk_status = constants.LDS_FAULTY
    else:
      ldisk_status = constants.LDS_OKAY

    return objects.BlockDevStatus(dev_path=self.dev_path,
                                  major=self.major,
                                  minor=self.minor,
                                  sync_percent=None,
                                  estimated_time=None,
                                  is_degraded=self._degraded,
                                  ldisk_status=ldisk_status)

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

    @returns: tuple (vg, lv)

    """
    snap_name = self._lv_name + ".snap"

    # remove existing snapshot if found
    snap = LogicalVolume((self._vg_name, snap_name), None, size, self.params)
    _IgnoreError(snap.Remove)

    vg_info = self.GetVGInfo([self._vg_name])
    if not vg_info:
      _ThrowError("Can't compute VG info for vg %s", self._vg_name)
    free_size, _, _ = vg_info[0]
    if free_size < size:
      _ThrowError("Not enough free space: required %s,"
                  " available %s", size, free_size)

    result = utils.RunCmd(["lvcreate", "-L%dm" % size, "-s",
                           "-n%s" % snap_name, self.dev_path])
    if result.failed:
      _ThrowError("command: %s error: %s - %s",
                  result.cmd, result.fail_reason, result.output)

    return (self._vg_name, snap_name)

  def SetInfo(self, text):
    """Update metadata with info text.

    """
    BlockDev.SetInfo(self, text)

    # Replace invalid characters
    text = re.sub("^[^A-Za-z0-9_+.]", "_", text)
    text = re.sub("[^-A-Za-z0-9_+.]", "_", text)

    # Only up to 128 characters are allowed
    text = text[:128]

    result = utils.RunCmd(["lvchange", "--addtag", text,
                           self.dev_path])
    if result.failed:
      _ThrowError("Command: %s error: %s - %s", result.cmd, result.fail_reason,
                  result.output)

  def Grow(self, amount, dryrun):
    """Grow the logical volume.

    """
    if self.pe_size is None or self.stripe_count is None:
      if not self.Attach():
        _ThrowError("Can't attach to LV during Grow()")
    full_stripe_size = self.pe_size * self.stripe_count
    rest = amount % full_stripe_size
    if rest != 0:
      amount += full_stripe_size - rest
    cmd = ["lvextend", "-L", "+%dm" % amount]
    if dryrun:
      cmd.append("--test")
    # we try multiple algorithms since the 'best' ones might not have
    # space available in the right place, but later ones might (since
    # they have less constraints); also note that only recent LVM
    # supports 'cling'
    for alloc_policy in "contiguous", "cling", "normal":
      result = utils.RunCmd(cmd + ["--alloc", alloc_policy, self.dev_path])
      if not result.failed:
        return
    _ThrowError("Can't grow LV %s: %s", self.dev_path, result.output)


class DRBD8Status(object):
  """A DRBD status representation class.

  Note that this doesn't support unconfigured devices (cs:Unconfigured).

  """
  UNCONF_RE = re.compile(r"\s*[0-9]+:\s*cs:Unconfigured$")
  LINE_RE = re.compile(r"\s*[0-9]+:\s*cs:(\S+)\s+(?:st|ro):([^/]+)/(\S+)"
                       "\s+ds:([^/]+)/(\S+)\s+.*$")
  SYNC_RE = re.compile(r"^.*\ssync'ed:\s*([0-9.]+)%.*"
                       # Due to a bug in drbd in the kernel, introduced in
                       # commit 4b0715f096 (still unfixed as of 2011-08-22)
                       "(?:\s|M)"
                       "finish: ([0-9]+):([0-9]+):([0-9]+)\s.*$")

  CS_UNCONFIGURED = "Unconfigured"
  CS_STANDALONE = "StandAlone"
  CS_WFCONNECTION = "WFConnection"
  CS_WFREPORTPARAMS = "WFReportParams"
  CS_CONNECTED = "Connected"
  CS_STARTINGSYNCS = "StartingSyncS"
  CS_STARTINGSYNCT = "StartingSyncT"
  CS_WFBITMAPS = "WFBitMapS"
  CS_WFBITMAPT = "WFBitMapT"
  CS_WFSYNCUUID = "WFSyncUUID"
  CS_SYNCSOURCE = "SyncSource"
  CS_SYNCTARGET = "SyncTarget"
  CS_PAUSEDSYNCS = "PausedSyncS"
  CS_PAUSEDSYNCT = "PausedSyncT"
  CSET_SYNC = frozenset([
    CS_WFREPORTPARAMS,
    CS_STARTINGSYNCS,
    CS_STARTINGSYNCT,
    CS_WFBITMAPS,
    CS_WFBITMAPT,
    CS_WFSYNCUUID,
    CS_SYNCSOURCE,
    CS_SYNCTARGET,
    CS_PAUSEDSYNCS,
    CS_PAUSEDSYNCT,
    ])

  DS_DISKLESS = "Diskless"
  DS_ATTACHING = "Attaching" # transient state
  DS_FAILED = "Failed" # transient state, next: diskless
  DS_NEGOTIATING = "Negotiating" # transient state
  DS_INCONSISTENT = "Inconsistent" # while syncing or after creation
  DS_OUTDATED = "Outdated"
  DS_DUNKNOWN = "DUnknown" # shown for peer disk when not connected
  DS_CONSISTENT = "Consistent"
  DS_UPTODATE = "UpToDate" # normal state

  RO_PRIMARY = "Primary"
  RO_SECONDARY = "Secondary"
  RO_UNKNOWN = "Unknown"

  def __init__(self, procline):
    u = self.UNCONF_RE.match(procline)
    if u:
      self.cstatus = self.CS_UNCONFIGURED
      self.lrole = self.rrole = self.ldisk = self.rdisk = None
    else:
      m = self.LINE_RE.match(procline)
      if not m:
        raise errors.BlockDeviceError("Can't parse input data '%s'" % procline)
      self.cstatus = m.group(1)
      self.lrole = m.group(2)
      self.rrole = m.group(3)
      self.ldisk = m.group(4)
      self.rdisk = m.group(5)

    # end reading of data from the LINE_RE or UNCONF_RE

    self.is_standalone = self.cstatus == self.CS_STANDALONE
    self.is_wfconn = self.cstatus == self.CS_WFCONNECTION
    self.is_connected = self.cstatus == self.CS_CONNECTED
    self.is_primary = self.lrole == self.RO_PRIMARY
    self.is_secondary = self.lrole == self.RO_SECONDARY
    self.peer_primary = self.rrole == self.RO_PRIMARY
    self.peer_secondary = self.rrole == self.RO_SECONDARY
    self.both_primary = self.is_primary and self.peer_primary
    self.both_secondary = self.is_secondary and self.peer_secondary

    self.is_diskless = self.ldisk == self.DS_DISKLESS
    self.is_disk_uptodate = self.ldisk == self.DS_UPTODATE

    self.is_in_resync = self.cstatus in self.CSET_SYNC
    self.is_in_use = self.cstatus != self.CS_UNCONFIGURED

    m = self.SYNC_RE.match(procline)
    if m:
      self.sync_percent = float(m.group(1))
      hours = int(m.group(2))
      minutes = int(m.group(3))
      seconds = int(m.group(4))
      self.est_time = hours * 3600 + minutes * 60 + seconds
    else:
      # we have (in this if branch) no percent information, but if
      # we're resyncing we need to 'fake' a sync percent information,
      # as this is how cmdlib determines if it makes sense to wait for
      # resyncing or not
      if self.is_in_resync:
        self.sync_percent = 0
      else:
        self.sync_percent = None
      self.est_time = None


class BaseDRBD(BlockDev): # pylint: disable=W0223
  """Base DRBD class.

  This class contains a few bits of common functionality between the
  0.7 and 8.x versions of DRBD.

  """
  _VERSION_RE = re.compile(r"^version: (\d+)\.(\d+)\.(\d+)(?:\.\d+)?"
                           r" \(api:(\d+)/proto:(\d+)(?:-(\d+))?\)")
  _VALID_LINE_RE = re.compile("^ *([0-9]+): cs:([^ ]+).*$")
  _UNUSED_LINE_RE = re.compile("^ *([0-9]+): cs:Unconfigured$")

  _DRBD_MAJOR = 147
  _ST_UNCONFIGURED = "Unconfigured"
  _ST_WFCONNECTION = "WFConnection"
  _ST_CONNECTED = "Connected"

  _STATUS_FILE = "/proc/drbd"
  _USERMODE_HELPER_FILE = "/sys/module/drbd/parameters/usermode_helper"

  @staticmethod
  def _GetProcData(filename=_STATUS_FILE):
    """Return data from /proc/drbd.

    """
    try:
      data = utils.ReadFile(filename).splitlines()
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        _ThrowError("The file %s cannot be opened, check if the module"
                    " is loaded (%s)", filename, str(err))
      else:
        _ThrowError("Can't read the DRBD proc file %s: %s", filename, str(err))
    if not data:
      _ThrowError("Can't read any data from %s", filename)
    return data

  @classmethod
  def _MassageProcData(cls, data):
    """Transform the output of _GetProdData into a nicer form.

    @return: a dictionary of minor: joined lines from /proc/drbd
        for that minor

    """
    results = {}
    old_minor = old_line = None
    for line in data:
      if not line: # completely empty lines, as can be returned by drbd8.0+
        continue
      lresult = cls._VALID_LINE_RE.match(line)
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
  def _GetVersion(cls, proc_data):
    """Return the DRBD version.

    This will return a dict with keys:
      - k_major
      - k_minor
      - k_point
      - api
      - proto
      - proto2 (only on drbd > 8.2.X)

    """
    first_line = proc_data[0].strip()
    version = cls._VERSION_RE.match(first_line)
    if not version:
      raise errors.BlockDeviceError("Can't parse DRBD version from '%s'" %
                                    first_line)

    values = version.groups()
    retval = {"k_major": int(values[0]),
              "k_minor": int(values[1]),
              "k_point": int(values[2]),
              "api": int(values[3]),
              "proto": int(values[4]),
             }
    if values[5] is not None:
      retval["proto2"] = values[5]

    return retval

  @staticmethod
  def GetUsermodeHelper(filename=_USERMODE_HELPER_FILE):
    """Returns DRBD usermode_helper currently set.

    """
    try:
      helper = utils.ReadFile(filename).splitlines()[0]
    except EnvironmentError, err:
      if err.errno == errno.ENOENT:
        _ThrowError("The file %s cannot be opened, check if the module"
                    " is loaded (%s)", filename, str(err))
      else:
        _ThrowError("Can't read DRBD helper file %s: %s", filename, str(err))
    if not helper:
      _ThrowError("Can't read any data from %s", filename)
    return helper

  @staticmethod
  def _DevPath(minor):
    """Return the path to a drbd device for a given minor.

    """
    return "/dev/drbd%d" % minor

  @classmethod
  def GetUsedDevs(cls):
    """Compute the list of used DRBD devices.

    """
    data = cls._GetProcData()

    used_devs = {}
    for line in data:
      match = cls._VALID_LINE_RE.match(line)
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
      self.attached = False
    else:
      self.minor = minor
      self.dev_path = self._DevPath(minor)
      self.attached = True

  @staticmethod
  def _CheckMetaSize(meta_device):
    """Check if the given meta device looks like a valid one.

    This currently only checks the size, which must be around
    128MiB.

    """
    result = utils.RunCmd(["blockdev", "--getsize", meta_device])
    if result.failed:
      _ThrowError("Failed to get device size: %s - %s",
                  result.fail_reason, result.output)
    try:
      sectors = int(result.stdout)
    except (TypeError, ValueError):
      _ThrowError("Invalid output from blockdev: '%s'", result.stdout)
    num_bytes = sectors * 512
    if num_bytes < 128 * 1024 * 1024: # less than 128MiB
      _ThrowError("Meta device too small (%.2fMib)", (num_bytes / 1024 / 1024))
    # the maximum *valid* size of the meta device when living on top
    # of LVM is hard to compute: it depends on the number of stripes
    # and the PE size; e.g. a 2-stripe, 64MB PE will result in a 128MB
    # (normal size), but an eight-stripe 128MB PE will result in a 1GB
    # size meta device; as such, we restrict it to 1GB (a little bit
    # too generous, but making assumptions about PE size is hard)
    if num_bytes > 1024 * 1024 * 1024:
      _ThrowError("Meta device too big (%.2fMiB)", (num_bytes / 1024 / 1024))

  def Rename(self, new_id):
    """Rename a device.

    This is not supported for drbd devices.

    """
    raise errors.ProgrammerError("Can't rename a drbd device")


class DRBD8(BaseDRBD):
  """DRBD v8.x block device.

  This implements the local host part of the DRBD device, i.e. it
  doesn't do anything to the supposed peer. If you need a fully
  connected DRBD pair, you need to use this class on both hosts.

  The unique_id for the drbd device is a (local_ip, local_port,
  remote_ip, remote_port, local_minor, secret) tuple, and it must have
  two children: the data device and the meta_device. The meta device
  is checked for valid size and is zeroed on create.

  """
  _MAX_MINORS = 255
  _PARSE_SHOW = None

  # timeout constants
  _NET_RECONFIG_TIMEOUT = 60

  # command line options for barriers
  _DISABLE_DISK_OPTION = "--no-disk-barrier"  # -a
  _DISABLE_DRAIN_OPTION = "--no-disk-drain"   # -D
  _DISABLE_FLUSH_OPTION = "--no-disk-flushes" # -i
  _DISABLE_META_FLUSH_OPTION = "--no-md-flushes"  # -m

  def __init__(self, unique_id, children, size, params):
    if children and children.count(None) > 0:
      children = []
    if len(children) not in (0, 2):
      raise ValueError("Invalid configuration data %s" % str(children))
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 6:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    (self._lhost, self._lport,
     self._rhost, self._rport,
     self._aminor, self._secret) = unique_id
    if children:
      if not _CanReadDevice(children[1].dev_path):
        logging.info("drbd%s: Ignoring unreadable meta device", self._aminor)
        children = []
    super(DRBD8, self).__init__(unique_id, children, size, params)
    self.major = self._DRBD_MAJOR
    version = self._GetVersion(self._GetProcData())
    if version["k_major"] != 8:
      _ThrowError("Mismatch in DRBD kernel version and requested ganeti"
                  " usage: kernel is %s.%s, ganeti wants 8.x",
                  version["k_major"], version["k_minor"])

    if (self._lhost is not None and self._lhost == self._rhost and
        self._lport == self._rport):
      raise ValueError("Invalid configuration data, same local/remote %s" %
                       (unique_id,))
    self.Attach()

  @classmethod
  def _InitMeta(cls, minor, dev_path):
    """Initialize a meta device.

    This will not work if the given minor is in use.

    """
    # Zero the metadata first, in order to make sure drbdmeta doesn't
    # try to auto-detect existing filesystems or similar (see
    # http://code.google.com/p/ganeti/issues/detail?id=182); we only
    # care about the first 128MB of data in the device, even though it
    # can be bigger
    result = utils.RunCmd([constants.DD_CMD,
                           "if=/dev/zero", "of=%s" % dev_path,
                           "bs=1048576", "count=128", "oflag=direct"])
    if result.failed:
      _ThrowError("Can't wipe the meta device: %s", result.output)

    result = utils.RunCmd(["drbdmeta", "--force", cls._DevPath(minor),
                           "v08", dev_path, "0", "create-md"])
    if result.failed:
      _ThrowError("Can't initialize meta device: %s", result.output)

  @classmethod
  def _FindUnusedMinor(cls):
    """Find an unused DRBD device.

    This is specific to 8.x as the minors are allocated dynamically,
    so non-existing numbers up to a max minor count are actually free.

    """
    data = cls._GetProcData()

    highest = None
    for line in data:
      match = cls._UNUSED_LINE_RE.match(line)
      if match:
        return int(match.group(1))
      match = cls._VALID_LINE_RE.match(line)
      if match:
        minor = int(match.group(1))
        highest = max(highest, minor)
    if highest is None: # there are no minors in use at all
      return 0
    if highest >= cls._MAX_MINORS:
      logging.error("Error: no free drbd minors!")
      raise errors.BlockDeviceError("Can't find a free DRBD minor")
    return highest + 1

  @classmethod
  def _GetShowParser(cls):
    """Return a parser for `drbd show` output.

    This will either create or return an already-created parser for the
    output of the command `drbd show`.

    """
    if cls._PARSE_SHOW is not None:
      return cls._PARSE_SHOW

    # pyparsing setup
    lbrace = pyp.Literal("{").suppress()
    rbrace = pyp.Literal("}").suppress()
    lbracket = pyp.Literal("[").suppress()
    rbracket = pyp.Literal("]").suppress()
    semi = pyp.Literal(";").suppress()
    colon = pyp.Literal(":").suppress()
    # this also converts the value to an int
    number = pyp.Word(pyp.nums).setParseAction(lambda s, l, t: int(t[0]))

    comment = pyp.Literal("#") + pyp.Optional(pyp.restOfLine)
    defa = pyp.Literal("_is_default").suppress()
    dbl_quote = pyp.Literal('"').suppress()

    keyword = pyp.Word(pyp.alphanums + "-")

    # value types
    value = pyp.Word(pyp.alphanums + "_-/.:")
    quoted = dbl_quote + pyp.CharsNotIn('"') + dbl_quote
    ipv4_addr = (pyp.Optional(pyp.Literal("ipv4")).suppress() +
                 pyp.Word(pyp.nums + ".") + colon + number)
    ipv6_addr = (pyp.Optional(pyp.Literal("ipv6")).suppress() +
                 pyp.Optional(lbracket) + pyp.Word(pyp.hexnums + ":") +
                 pyp.Optional(rbracket) + colon + number)
    # meta device, extended syntax
    meta_value = ((value ^ quoted) + lbracket + number + rbracket)
    # device name, extended syntax
    device_value = pyp.Literal("minor").suppress() + number

    # a statement
    stmt = (~rbrace + keyword + ~lbrace +
            pyp.Optional(ipv4_addr ^ ipv6_addr ^ value ^ quoted ^ meta_value ^
                         device_value) +
            pyp.Optional(defa) + semi +
            pyp.Optional(pyp.restOfLine).suppress())

    # an entire section
    section_name = pyp.Word(pyp.alphas + "_")
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
      logging.error("Can't display the drbd config: %s - %s",
                    result.fail_reason, result.output)
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
      _ThrowError("Can't parse drbdsetup show output: %s", str(err))

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

  def _AssembleLocal(self, minor, backend, meta, size):
    """Configure the local part of a DRBD device.

    """
    args = ["drbdsetup", self._DevPath(minor), "disk",
            backend, meta, "0",
            "-e", "detach",
            "--create-device"]
    if size:
      args.extend(["-d", "%sm" % size])

    version = self._GetVersion(self._GetProcData())
    vmaj = version["k_major"]
    vmin = version["k_minor"]
    vrel = version["k_point"]

    barrier_args = \
      self._ComputeDiskBarrierArgs(vmaj, vmin, vrel,
                                   self.params[constants.LDP_BARRIERS],
                                   self.params[constants.LDP_NO_META_FLUSH])
    args.extend(barrier_args)

    if self.params[constants.LDP_DISK_CUSTOM]:
      args.extend(shlex.split(self.params[constants.LDP_DISK_CUSTOM]))

    result = utils.RunCmd(args)
    if result.failed:
      _ThrowError("drbd%d: can't attach local disk: %s", minor, result.output)

  @classmethod
  def _ComputeDiskBarrierArgs(cls, vmaj, vmin, vrel, disabled_barriers,
      disable_meta_flush):
    """Compute the DRBD command line parameters for disk barriers

    Returns a list of the disk barrier parameters as requested via the
    disabled_barriers and disable_meta_flush arguments, and according to the
    supported ones in the DRBD version vmaj.vmin.vrel

    If the desired option is unsupported, raises errors.BlockDeviceError.

    """
    disabled_barriers_set = frozenset(disabled_barriers)
    if not disabled_barriers_set in constants.DRBD_VALID_BARRIER_OPT:
      raise errors.BlockDeviceError("%s is not a valid option set for DRBD"
                                    " barriers" % disabled_barriers)

    args = []

    # The following code assumes DRBD 8.x, with x < 4 and x != 1 (DRBD 8.1.x
    # does not exist)
    if not vmaj == 8 and vmin in (0, 2, 3):
      raise errors.BlockDeviceError("Unsupported DRBD version: %d.%d.%d" %
                                    (vmaj, vmin, vrel))

    def _AppendOrRaise(option, min_version):
      """Helper for DRBD options"""
      if min_version is not None and vrel >= min_version:
        args.append(option)
      else:
        raise errors.BlockDeviceError("Could not use the option %s as the"
                                      " DRBD version %d.%d.%d does not support"
                                      " it." % (option, vmaj, vmin, vrel))

    # the minimum version for each feature is encoded via pairs of (minor
    # version -> x) where x is version in which support for the option was
    # introduced.
    meta_flush_supported = disk_flush_supported = {
      0: 12,
      2: 7,
      3: 0,
      }

    disk_drain_supported = {
      2: 7,
      3: 0,
      }

    disk_barriers_supported = {
      3: 0,
      }

    # meta flushes
    if disable_meta_flush:
      _AppendOrRaise(cls._DISABLE_META_FLUSH_OPTION,
                     meta_flush_supported.get(vmin, None))

    # disk flushes
    if constants.DRBD_B_DISK_FLUSH in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_FLUSH_OPTION,
                     disk_flush_supported.get(vmin, None))

    # disk drain
    if constants.DRBD_B_DISK_DRAIN in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_DRAIN_OPTION,
                     disk_drain_supported.get(vmin, None))

    # disk barriers
    if constants.DRBD_B_DISK_BARRIERS in disabled_barriers_set:
      _AppendOrRaise(cls._DISABLE_DISK_OPTION,
                     disk_barriers_supported.get(vmin, None))

    return args

  def _AssembleNet(self, minor, net_info, protocol,
                   dual_pri=False, hmac=None, secret=None):
    """Configure the network part of the device.

    """
    lhost, lport, rhost, rport = net_info
    if None in net_info:
      # we don't want network connection and actually want to make
      # sure its shutdown
      self._ShutdownNet(minor)
      return

    # Workaround for a race condition. When DRBD is doing its dance to
    # establish a connection with its peer, it also sends the
    # synchronization speed over the wire. In some cases setting the
    # sync speed only after setting up both sides can race with DRBD
    # connecting, hence we set it here before telling DRBD anything
    # about its peer.
    sync_errors = self._SetMinorSyncParams(minor, self.params)
    if sync_errors:
      _ThrowError("drbd%d: can't set the synchronization parameters: %s" %
                  (minor, utils.CommaJoin(sync_errors)))

    if netutils.IP6Address.IsValid(lhost):
      if not netutils.IP6Address.IsValid(rhost):
        _ThrowError("drbd%d: can't connect ip %s to ip %s" %
                    (minor, lhost, rhost))
      family = "ipv6"
    elif netutils.IP4Address.IsValid(lhost):
      if not netutils.IP4Address.IsValid(rhost):
        _ThrowError("drbd%d: can't connect ip %s to ip %s" %
                    (minor, lhost, rhost))
      family = "ipv4"
    else:
      _ThrowError("drbd%d: Invalid ip %s" % (minor, lhost))

    args = ["drbdsetup", self._DevPath(minor), "net",
            "%s:%s:%s" % (family, lhost, lport),
            "%s:%s:%s" % (family, rhost, rport), protocol,
            "-A", "discard-zero-changes",
            "-B", "consensus",
            "--create-device",
            ]
    if dual_pri:
      args.append("-m")
    if hmac and secret:
      args.extend(["-a", hmac, "-x", secret])

    if self.params[constants.LDP_NET_CUSTOM]:
      args.extend(shlex.split(self.params[constants.LDP_NET_CUSTOM]))

    result = utils.RunCmd(args)
    if result.failed:
      _ThrowError("drbd%d: can't setup network: %s - %s",
                  minor, result.fail_reason, result.output)

    def _CheckNetworkConfig():
      info = self._GetDevInfo(self._GetShowData(minor))
      if not "local_addr" in info or not "remote_addr" in info:
        raise utils.RetryAgain()

      if (info["local_addr"] != (lhost, lport) or
          info["remote_addr"] != (rhost, rport)):
        raise utils.RetryAgain()

    try:
      utils.Retry(_CheckNetworkConfig, 1.0, 10.0)
    except utils.RetryTimeout:
      _ThrowError("drbd%d: timeout while configuring network", minor)

  def AddChildren(self, devices):
    """Add a disk to the DRBD device.

    """
    if self.minor is None:
      _ThrowError("drbd%d: can't attach to dbrd8 during AddChildren",
                  self._aminor)
    if len(devices) != 2:
      _ThrowError("drbd%d: need two devices for AddChildren", self.minor)
    info = self._GetDevInfo(self._GetShowData(self.minor))
    if "local_dev" in info:
      _ThrowError("drbd%d: already attached to a local disk", self.minor)
    backend, meta = devices
    if backend.dev_path is None or meta.dev_path is None:
      _ThrowError("drbd%d: children not ready during AddChildren", self.minor)
    backend.Open()
    meta.Open()
    self._CheckMetaSize(meta.dev_path)
    self._InitMeta(self._FindUnusedMinor(), meta.dev_path)

    self._AssembleLocal(self.minor, backend.dev_path, meta.dev_path, self.size)
    self._children = devices

  def RemoveChildren(self, devices):
    """Detach the drbd device from local storage.

    """
    if self.minor is None:
      _ThrowError("drbd%d: can't attach to drbd8 during RemoveChildren",
                  self._aminor)
    # early return if we don't actually have backing storage
    info = self._GetDevInfo(self._GetShowData(self.minor))
    if "local_dev" not in info:
      return
    if len(self._children) != 2:
      _ThrowError("drbd%d: we don't have two children: %s", self.minor,
                  self._children)
    if self._children.count(None) == 2: # we don't actually have children :)
      logging.warning("drbd%d: requested detach while detached", self.minor)
      return
    if len(devices) != 2:
      _ThrowError("drbd%d: we need two children in RemoveChildren", self.minor)
    for child, dev in zip(self._children, devices):
      if dev != child.dev_path:
        _ThrowError("drbd%d: mismatch in local storage (%s != %s) in"
                    " RemoveChildren", self.minor, dev, child.dev_path)

    self._ShutdownLocal(self.minor)
    self._children = []

  @classmethod
  def _SetMinorSyncParams(cls, minor, params):
    """Set the parameters of the DRBD syncer.

    This is the low-level implementation.

    @type minor: int
    @param minor: the drbd minor whose settings we change
    @type params: dict
    @param params: LD level disk parameters related to the synchronization
    @rtype: list
    @return: a list of error messages

    """

    args = ["drbdsetup", cls._DevPath(minor), "syncer"]
    if params[constants.LDP_DYNAMIC_RESYNC]:
      version = cls._GetVersion(cls._GetProcData())
      vmin = version["k_minor"]
      vrel = version["k_point"]

      # By definition we are using 8.x, so just check the rest of the version
      # number
      if vmin != 3 or vrel < 9:
        msg = ("The current DRBD version (8.%d.%d) does not support the "
               "dynamic resync speed controller" % (vmin, vrel))
        logging.error(msg)
        return [msg]

      if params[constants.LDP_PLAN_AHEAD] == 0:
        msg = ("A value of 0 for c-plan-ahead disables the dynamic sync speed"
               " controller at DRBD level. If you want to disable it, please"
               " set the dynamic-resync disk parameter to False.")
        logging.error(msg)
        return [msg]

      # add the c-* parameters to args
      args.extend(["--c-plan-ahead", params[constants.LDP_PLAN_AHEAD],
                   "--c-fill-target", params[constants.LDP_FILL_TARGET],
                   "--c-delay-target", params[constants.LDP_DELAY_TARGET],
                   "--c-max-rate", params[constants.LDP_MAX_RATE],
                   "--c-min-rate", params[constants.LDP_MIN_RATE],
                  ])

    else:
      args.extend(["-r", "%d" % params[constants.LDP_RESYNC_RATE]])

    args.append("--create-device")
    result = utils.RunCmd(args)
    if result.failed:
      msg = ("Can't change syncer rate: %s - %s" %
             (result.fail_reason, result.output))
      logging.error(msg)
      return [msg]

    return []

  def SetSyncParams(self, params):
    """Set the synchronization parameters of the DRBD syncer.

    @type params: dict
    @param params: LD level disk parameters related to the synchronization
    @rtype: list
    @return: a list of error messages, emitted both by the current node and by
    children. An empty list means no errors

    """
    if self.minor is None:
      err = "Not attached during SetSyncParams"
      logging.info(err)
      return [err]

    children_result = super(DRBD8, self).SetSyncParams(params)
    children_result.extend(self._SetMinorSyncParams(self.minor, params))
    return children_result

  def PauseResumeSync(self, pause):
    """Pauses or resumes the sync of a DRBD device.

    @param pause: Wether to pause or resume
    @return: the success of the operation

    """
    if self.minor is None:
      logging.info("Not attached during PauseSync")
      return False

    children_result = super(DRBD8, self).PauseResumeSync(pause)

    if pause:
      cmd = "pause-sync"
    else:
      cmd = "resume-sync"

    result = utils.RunCmd(["drbdsetup", self.dev_path, cmd])
    if result.failed:
      logging.error("Can't %s: %s - %s", cmd,
                    result.fail_reason, result.output)
    return not result.failed and children_result

  def GetProcStatus(self):
    """Return device data from /proc.

    """
    if self.minor is None:
      _ThrowError("drbd%d: GetStats() called while not attached", self._aminor)
    proc_info = self._MassageProcData(self._GetProcData())
    if self.minor not in proc_info:
      _ThrowError("drbd%d: can't find myself in /proc", self.minor)
    return DRBD8Status(proc_info[self.minor])

  def GetSyncStatus(self):
    """Returns the sync status of the device.


    If sync_percent is None, it means all is ok
    If estimated_time is None, it means we can't estimate
    the time needed, otherwise it's the time left in seconds.


    We set the is_degraded parameter to True on two conditions:
    network not connected or local disk missing.

    We compute the ldisk parameter based on whether we have a local
    disk or not.

    @rtype: objects.BlockDevStatus

    """
    if self.minor is None and not self.Attach():
      _ThrowError("drbd%d: can't Attach() in GetSyncStatus", self._aminor)

    stats = self.GetProcStatus()
    is_degraded = not stats.is_connected or not stats.is_disk_uptodate

    if stats.is_disk_uptodate:
      ldisk_status = constants.LDS_OKAY
    elif stats.is_diskless:
      ldisk_status = constants.LDS_FAULTY
    else:
      ldisk_status = constants.LDS_UNKNOWN

    return objects.BlockDevStatus(dev_path=self.dev_path,
                                  major=self.major,
                                  minor=self.minor,
                                  sync_percent=stats.sync_percent,
                                  estimated_time=stats.est_time,
                                  is_degraded=is_degraded,
                                  ldisk_status=ldisk_status)

  def Open(self, force=False):
    """Make the local state primary.

    If the 'force' parameter is given, the '-o' option is passed to
    drbdsetup. Since this is a potentially dangerous operation, the
    force flag should be only given after creation, when it actually
    is mandatory.

    """
    if self.minor is None and not self.Attach():
      logging.error("DRBD cannot attach to a device during open")
      return False
    cmd = ["drbdsetup", self.dev_path, "primary"]
    if force:
      cmd.append("-o")
    result = utils.RunCmd(cmd)
    if result.failed:
      _ThrowError("drbd%d: can't make drbd device primary: %s", self.minor,
                  result.output)

  def Close(self):
    """Make the local state secondary.

    This will, of course, fail if the device is in use.

    """
    if self.minor is None and not self.Attach():
      _ThrowError("drbd%d: can't Attach() in Close()", self._aminor)
    result = utils.RunCmd(["drbdsetup", self.dev_path, "secondary"])
    if result.failed:
      _ThrowError("drbd%d: can't switch drbd device to secondary: %s",
                  self.minor, result.output)

  def DisconnectNet(self):
    """Removes network configuration.

    This method shutdowns the network side of the device.

    The method will wait up to a hardcoded timeout for the device to
    go into standalone after the 'disconnect' command before
    re-configuring it, as sometimes it takes a while for the
    disconnect to actually propagate and thus we might issue a 'net'
    command while the device is still connected. If the device will
    still be attached to the network and we time out, we raise an
    exception.

    """
    if self.minor is None:
      _ThrowError("drbd%d: disk not attached in re-attach net", self._aminor)

    if None in (self._lhost, self._lport, self._rhost, self._rport):
      _ThrowError("drbd%d: DRBD disk missing network info in"
                  " DisconnectNet()", self.minor)

    class _DisconnectStatus:
      def __init__(self, ever_disconnected):
        self.ever_disconnected = ever_disconnected

    dstatus = _DisconnectStatus(_IgnoreError(self._ShutdownNet, self.minor))

    def _WaitForDisconnect():
      if self.GetProcStatus().is_standalone:
        return

      # retry the disconnect, it seems possible that due to a well-time
      # disconnect on the peer, my disconnect command might be ignored and
      # forgotten
      dstatus.ever_disconnected = \
        _IgnoreError(self._ShutdownNet, self.minor) or dstatus.ever_disconnected

      raise utils.RetryAgain()

    # Keep start time
    start_time = time.time()

    try:
      # Start delay at 100 milliseconds and grow up to 2 seconds
      utils.Retry(_WaitForDisconnect, (0.1, 1.5, 2.0),
                  self._NET_RECONFIG_TIMEOUT)
    except utils.RetryTimeout:
      if dstatus.ever_disconnected:
        msg = ("drbd%d: device did not react to the"
               " 'disconnect' command in a timely manner")
      else:
        msg = "drbd%d: can't shutdown network, even after multiple retries"

      _ThrowError(msg, self.minor)

    reconfig_time = time.time() - start_time
    if reconfig_time > (self._NET_RECONFIG_TIMEOUT * 0.25):
      logging.info("drbd%d: DisconnectNet: detach took %.3f seconds",
                   self.minor, reconfig_time)

  def AttachNet(self, multimaster):
    """Reconnects the network.

    This method connects the network side of the device with a
    specified multi-master flag. The device needs to be 'Standalone'
    but have valid network configuration data.

    Args:
      - multimaster: init the network in dual-primary mode

    """
    if self.minor is None:
      _ThrowError("drbd%d: device not attached in AttachNet", self._aminor)

    if None in (self._lhost, self._lport, self._rhost, self._rport):
      _ThrowError("drbd%d: missing network info in AttachNet()", self.minor)

    status = self.GetProcStatus()

    if not status.is_standalone:
      _ThrowError("drbd%d: device is not standalone in AttachNet", self.minor)

    self._AssembleNet(self.minor,
                      (self._lhost, self._lport, self._rhost, self._rport),
                      constants.DRBD_NET_PROTOCOL, dual_pri=multimaster,
                      hmac=constants.DRBD_HMAC_ALG, secret=self._secret)

  def Attach(self):
    """Check if our minor is configured.

    This doesn't do any device configurations - it only checks if the
    minor is in a state different from Unconfigured.

    Note that this function will not change the state of the system in
    any way (except in case of side-effects caused by reading from
    /proc).

    """
    used_devs = self.GetUsedDevs()
    if self._aminor in used_devs:
      minor = self._aminor
    else:
      minor = None

    self._SetFromMinor(minor)
    return minor is not None

  def Assemble(self):
    """Assemble the drbd.

    Method:
      - if we have a configured device, we try to ensure that it matches
        our config
      - if not, we create it from zero
      - anyway, set the device parameters

    """
    super(DRBD8, self).Assemble()

    self.Attach()
    if self.minor is None:
      # local device completely unconfigured
      self._FastAssemble()
    else:
      # we have to recheck the local and network status and try to fix
      # the device
      self._SlowAssemble()

    sync_errors = self.SetSyncParams(self.params)
    if sync_errors:
      _ThrowError("drbd%d: can't set the synchronization parameters: %s" %
                  (self.minor, utils.CommaJoin(sync_errors)))

  def _SlowAssemble(self):
    """Assembles the DRBD device from a (partially) configured device.

    In case of partially attached (local device matches but no network
    setup), we perform the network attach. If successful, we re-test
    the attach if can return success.

    """
    # TODO: Rewrite to not use a for loop just because there is 'break'
    # pylint: disable=W0631
    net_data = (self._lhost, self._lport, self._rhost, self._rport)
    for minor in (self._aminor,):
      info = self._GetDevInfo(self._GetShowData(minor))
      match_l = self._MatchesLocal(info)
      match_r = self._MatchesNet(info)

      if match_l and match_r:
        # everything matches
        break

      if match_l and not match_r and "local_addr" not in info:
        # disk matches, but not attached to network, attach and recheck
        self._AssembleNet(minor, net_data, constants.DRBD_NET_PROTOCOL,
                          hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
        if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
          break
        else:
          _ThrowError("drbd%d: network attach successful, but 'drbdsetup"
                      " show' disagrees", minor)

      if match_r and "local_dev" not in info:
        # no local disk, but network attached and it matches
        self._AssembleLocal(minor, self._children[0].dev_path,
                            self._children[1].dev_path, self.size)
        if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
          break
        else:
          _ThrowError("drbd%d: disk attach successful, but 'drbdsetup"
                      " show' disagrees", minor)

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
        try:
          self._ShutdownNet(minor)
        except errors.BlockDeviceError, err:
          _ThrowError("drbd%d: device has correct local storage, wrong"
                      " remote peer and is unable to disconnect in order"
                      " to attach to the correct peer: %s", minor, str(err))
        # note: _AssembleNet also handles the case when we don't want
        # local storage (i.e. one or more of the _[lr](host|port) is
        # None)
        self._AssembleNet(minor, net_data, constants.DRBD_NET_PROTOCOL,
                          hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
        if self._MatchesNet(self._GetDevInfo(self._GetShowData(minor))):
          break
        else:
          _ThrowError("drbd%d: network attach successful, but 'drbdsetup"
                      " show' disagrees", minor)

    else:
      minor = None

    self._SetFromMinor(minor)
    if minor is None:
      _ThrowError("drbd%d: cannot activate, unknown or unhandled reason",
                  self._aminor)

  def _FastAssemble(self):
    """Assemble the drbd device from zero.

    This is run when in Assemble we detect our minor is unused.

    """
    minor = self._aminor
    if self._children and self._children[0] and self._children[1]:
      self._AssembleLocal(minor, self._children[0].dev_path,
                          self._children[1].dev_path, self.size)
    if self._lhost and self._lport and self._rhost and self._rport:
      self._AssembleNet(minor,
                        (self._lhost, self._lport, self._rhost, self._rport),
                        constants.DRBD_NET_PROTOCOL,
                        hmac=constants.DRBD_HMAC_ALG, secret=self._secret)
    self._SetFromMinor(minor)

  @classmethod
  def _ShutdownLocal(cls, minor):
    """Detach from the local device.

    I/Os will continue to be served from the remote device. If we
    don't have a remote device, this operation will fail.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "detach"])
    if result.failed:
      _ThrowError("drbd%d: can't detach local disk: %s", minor, result.output)

  @classmethod
  def _ShutdownNet(cls, minor):
    """Disconnect from the remote peer.

    This fails if we don't have a local device.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "disconnect"])
    if result.failed:
      _ThrowError("drbd%d: can't shutdown network: %s", minor, result.output)

  @classmethod
  def _ShutdownAll(cls, minor):
    """Deactivate the device.

    This will, of course, fail if the device is in use.

    """
    result = utils.RunCmd(["drbdsetup", cls._DevPath(minor), "down"])
    if result.failed:
      _ThrowError("drbd%d: can't shutdown drbd device: %s",
                  minor, result.output)

  def Shutdown(self):
    """Shutdown the DRBD device.

    """
    if self.minor is None and not self.Attach():
      logging.info("drbd%d: not attached during Shutdown()", self._aminor)
      return
    minor = self.minor
    self.minor = None
    self.dev_path = None
    self._ShutdownAll(minor)

  def Remove(self):
    """Stub remove for DRBD devices.

    """
    self.Shutdown()

  @classmethod
  def Create(cls, unique_id, children, size, params):
    """Create a new DRBD8 device.

    Since DRBD devices are not created per se, just assembled, this
    function only initializes the metadata.

    """
    if len(children) != 2:
      raise errors.ProgrammerError("Invalid setup for the drbd device")
    # check that the minor is unused
    aminor = unique_id[4]
    proc_info = cls._MassageProcData(cls._GetProcData())
    if aminor in proc_info:
      status = DRBD8Status(proc_info[aminor])
      in_use = status.is_in_use
    else:
      in_use = False
    if in_use:
      _ThrowError("drbd%d: minor is already in use at Create() time", aminor)
    meta = children[1]
    meta.Assemble()
    if not meta.Attach():
      _ThrowError("drbd%d: can't attach to meta device '%s'",
                  aminor, meta)
    cls._CheckMetaSize(meta.dev_path)
    cls._InitMeta(aminor, meta.dev_path)
    return cls(unique_id, children, size, params)

  def Grow(self, amount, dryrun):
    """Resize the DRBD device and its backing storage.

    """
    if self.minor is None:
      _ThrowError("drbd%d: Grow called while not attached", self._aminor)
    if len(self._children) != 2 or None in self._children:
      _ThrowError("drbd%d: cannot grow diskless device", self.minor)
    self._children[0].Grow(amount, dryrun)
    if dryrun:
      # DRBD does not support dry-run mode, so we'll return here
      return
    result = utils.RunCmd(["drbdsetup", self.dev_path, "resize", "-s",
                           "%dm" % (self.size + amount)])
    if result.failed:
      _ThrowError("drbd%d: resize failed: %s", self.minor, result.output)


class FileStorage(BlockDev):
  """File device.

  This class represents the a file storage backend device.

  The unique_id for the file device is a (file_driver, file_path) tuple.

  """
  def __init__(self, unique_id, children, size, params):
    """Initalizes a file device backend.

    """
    if children:
      raise errors.BlockDeviceError("Invalid setup for file device")
    super(FileStorage, self).__init__(unique_id, children, size, params)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self.driver = unique_id[0]
    self.dev_path = unique_id[1]
    self.Attach()

  def Assemble(self):
    """Assemble the device.

    Checks whether the file device exists, raises BlockDeviceError otherwise.

    """
    if not os.path.exists(self.dev_path):
      _ThrowError("File device '%s' does not exist" % self.dev_path)

  def Shutdown(self):
    """Shutdown the device.

    This is a no-op for the file type, as we don't deactivate
    the file on shutdown.

    """
    pass

  def Open(self, force=False):
    """Make the device ready for I/O.

    This is a no-op for the file type.

    """
    pass

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
    try:
      os.remove(self.dev_path)
    except OSError, err:
      if err.errno != errno.ENOENT:
        _ThrowError("Can't remove file '%s': %s", self.dev_path, err)

  def Rename(self, new_id):
    """Renames the file.

    """
    # TODO: implement rename for file-based storage
    _ThrowError("Rename is not supported for file-based storage")

  def Grow(self, amount, dryrun):
    """Grow the file

    @param amount: the amount (in mebibytes) to grow with

    """
    # Check that the file exists
    self.Assemble()
    current_size = self.GetActualSize()
    new_size = current_size + amount * 1024 * 1024
    assert new_size > current_size, "Cannot Grow with a negative amount"
    # We can't really simulate the growth
    if dryrun:
      return
    try:
      f = open(self.dev_path, "a+")
      f.truncate(new_size)
      f.close()
    except EnvironmentError, err:
      _ThrowError("Error in file growth: %", str(err))

  def Attach(self):
    """Attach to an existing file.

    Check if this file already exists.

    @rtype: boolean
    @return: True if file exists

    """
    self.attached = os.path.exists(self.dev_path)
    return self.attached

  def GetActualSize(self):
    """Return the actual disk size.

    @note: the device needs to be active when this is called

    """
    assert self.attached, "BlockDevice not attached in GetActualSize()"
    try:
      st = os.stat(self.dev_path)
      return st.st_size
    except OSError, err:
      _ThrowError("Can't stat %s: %s", self.dev_path, err)

  @classmethod
  def Create(cls, unique_id, children, size, params):
    """Create a new file.

    @param size: the size of file in MiB

    @rtype: L{bdev.FileStorage}
    @return: an instance of FileStorage

    """
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    dev_path = unique_id[1]
    try:
      fd = os.open(dev_path, os.O_RDWR | os.O_CREAT | os.O_EXCL)
      f = os.fdopen(fd, "w")
      f.truncate(size * 1024 * 1024)
      f.close()
    except EnvironmentError, err:
      if err.errno == errno.EEXIST:
        _ThrowError("File already existing: %s", dev_path)
      _ThrowError("Error in file creation: %", str(err))

    return FileStorage(unique_id, children, size, params)


class PersistentBlockDevice(BlockDev):
  """A block device with persistent node

  May be either directly attached, or exposed through DM (e.g. dm-multipath).
  udev helpers are probably required to give persistent, human-friendly
  names.

  For the time being, pathnames are required to lie under /dev.

  """
  def __init__(self, unique_id, children, size, params):
    """Attaches to a static block device.

    The unique_id is a path under /dev.

    """
    super(PersistentBlockDevice, self).__init__(unique_id, children, size,
                                                params)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self.dev_path = unique_id[1]
    if not os.path.realpath(self.dev_path).startswith("/dev/"):
      raise ValueError("Full path '%s' lies outside /dev" %
                              os.path.realpath(self.dev_path))
    # TODO: this is just a safety guard checking that we only deal with devices
    # we know how to handle. In the future this will be integrated with
    # external storage backends and possible values will probably be collected
    # from the cluster configuration.
    if unique_id[0] != constants.BLOCKDEV_DRIVER_MANUAL:
      raise ValueError("Got persistent block device of invalid type: %s" %
                       unique_id[0])

    self.major = self.minor = None
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size, params):
    """Create a new device

    This is a noop, we only return a PersistentBlockDevice instance

    """
    return PersistentBlockDevice(unique_id, children, 0, params)

  def Remove(self):
    """Remove a device

    This is a noop

    """
    pass

  def Rename(self, new_id):
    """Rename this device.

    """
    _ThrowError("Rename is not supported for PersistentBlockDev storage")

  def Attach(self):
    """Attach to an existing block device.


    """
    self.attached = False
    try:
      st = os.stat(self.dev_path)
    except OSError, err:
      logging.error("Error stat()'ing %s: %s", self.dev_path, str(err))
      return False

    if not stat.S_ISBLK(st.st_mode):
      logging.error("%s is not a block device", self.dev_path)
      return False

    self.major = os.major(st.st_rdev)
    self.minor = os.minor(st.st_rdev)
    self.attached = True

    return True

  def Assemble(self):
    """Assemble the device.

    """
    pass

  def Shutdown(self):
    """Shutdown the device.

    """
    pass

  def Open(self, force=False):
    """Make the device ready for I/O.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    pass

  def Grow(self, amount, dryrun):
    """Grow the logical volume.

    """
    _ThrowError("Grow is not supported for PersistentBlockDev storage")


class RADOSBlockDevice(BlockDev):
  """A RADOS Block Device (rbd).

  This class implements the RADOS Block Device for the backend. You need
  the rbd kernel driver, the RADOS Tools and a working RADOS cluster for
  this to be functional.

  """
  def __init__(self, unique_id, children, size, params):
    """Attaches to an rbd device.

    """
    super(RADOSBlockDevice, self).__init__(unique_id, children, size, params)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    self.driver, self.rbd_name = unique_id

    self.major = self.minor = None
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size, params):
    """Create a new rbd device.

    Provision a new rbd volume inside a RADOS pool.

    """
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise errors.ProgrammerError("Invalid configuration data %s" %
                                   str(unique_id))
    rbd_pool = params[constants.LDP_POOL]
    rbd_name = unique_id[1]

    # Provision a new rbd volume (Image) inside the RADOS cluster.
    cmd = [constants.RBD_CMD, "create", "-p", rbd_pool,
           rbd_name, "--size", "%s" % size]
    result = utils.RunCmd(cmd)
    if result.failed:
      _ThrowError("rbd creation failed (%s): %s",
                  result.fail_reason, result.output)

    return RADOSBlockDevice(unique_id, children, size, params)

  def Remove(self):
    """Remove the rbd device.

    """
    rbd_pool = self.params[constants.LDP_POOL]
    rbd_name = self.unique_id[1]

    if not self.minor and not self.Attach():
      # The rbd device doesn't exist.
      return

    # First shutdown the device (remove mappings).
    self.Shutdown()

    # Remove the actual Volume (Image) from the RADOS cluster.
    cmd = [constants.RBD_CMD, "rm", "-p", rbd_pool, rbd_name]
    result = utils.RunCmd(cmd)
    if result.failed:
      _ThrowError("Can't remove Volume from cluster with rbd rm: %s - %s",
                  result.fail_reason, result.output)

  def Rename(self, new_id):
    """Rename this device.

    """
    pass

  def Attach(self):
    """Attach to an existing rbd device.

    This method maps the rbd volume that matches our name with
    an rbd device and then attaches to this device.

    """
    self.attached = False

    # Map the rbd volume to a block device under /dev
    self.dev_path = self._MapVolumeToBlockdev(self.unique_id)

    try:
      st = os.stat(self.dev_path)
    except OSError, err:
      logging.error("Error stat()'ing %s: %s", self.dev_path, str(err))
      return False

    if not stat.S_ISBLK(st.st_mode):
      logging.error("%s is not a block device", self.dev_path)
      return False

    self.major = os.major(st.st_rdev)
    self.minor = os.minor(st.st_rdev)
    self.attached = True

    return True

  def _MapVolumeToBlockdev(self, unique_id):
    """Maps existing rbd volumes to block devices.

    This method should be idempotent if the mapping already exists.

    @rtype: string
    @return: the block device path that corresponds to the volume

    """
    pool = self.params[constants.LDP_POOL]
    name = unique_id[1]

    # Check if the mapping already exists.
    showmap_cmd = [constants.RBD_CMD, "showmapped", "-p", pool]
    result = utils.RunCmd(showmap_cmd)
    if result.failed:
      _ThrowError("rbd showmapped failed (%s): %s",
                  result.fail_reason, result.output)

    rbd_dev = self._ParseRbdShowmappedOutput(result.output, name)

    if rbd_dev:
      # The mapping exists. Return it.
      return rbd_dev

    # The mapping doesn't exist. Create it.
    map_cmd = [constants.RBD_CMD, "map", "-p", pool, name]
    result = utils.RunCmd(map_cmd)
    if result.failed:
      _ThrowError("rbd map failed (%s): %s",
                  result.fail_reason, result.output)

    # Find the corresponding rbd device.
    showmap_cmd = [constants.RBD_CMD, "showmapped", "-p", pool]
    result = utils.RunCmd(showmap_cmd)
    if result.failed:
      _ThrowError("rbd map succeeded, but showmapped failed (%s): %s",
                  result.fail_reason, result.output)

    rbd_dev = self._ParseRbdShowmappedOutput(result.output, name)

    if not rbd_dev:
      _ThrowError("rbd map succeeded, but could not find the rbd block"
                  " device in output of showmapped, for volume: %s", name)

    # The device was successfully mapped. Return it.
    return rbd_dev

  @staticmethod
  def _ParseRbdShowmappedOutput(output, volume_name):
    """Parse the output of `rbd showmapped'.

    This method parses the output of `rbd showmapped' and returns
    the rbd block device path (e.g. /dev/rbd0) that matches the
    given rbd volume.

    @type output: string
    @param output: the whole output of `rbd showmapped'
    @type volume_name: string
    @param volume_name: the name of the volume whose device we search for
    @rtype: string or None
    @return: block device path if the volume is mapped, else None

    """
    allfields = 5
    volumefield = 2
    devicefield = 4

    field_sep = "\t"

    lines = output.splitlines()
    splitted_lines = map(lambda l: l.split(field_sep), lines)

    # Check empty output.
    if not splitted_lines:
      _ThrowError("rbd showmapped returned empty output")

    # Check showmapped header line, to determine number of fields.
    field_cnt = len(splitted_lines[0])
    if field_cnt != allfields:
      _ThrowError("Cannot parse rbd showmapped output because its format"
                  " seems to have changed; expected %s fields, found %s",
                  allfields, field_cnt)

    matched_lines = \
      filter(lambda l: len(l) == allfields and l[volumefield] == volume_name,
             splitted_lines)

    if len(matched_lines) > 1:
      _ThrowError("The rbd volume %s is mapped more than once."
                  " This shouldn't happen, try to unmap the extra"
                  " devices manually.", volume_name)

    if matched_lines:
      # rbd block device found. Return it.
      rbd_dev = matched_lines[0][devicefield]
      return rbd_dev

    # The given volume is not mapped.
    return None

  def Assemble(self):
    """Assemble the device.

    """
    pass

  def Shutdown(self):
    """Shutdown the device.

    """
    if not self.minor and not self.Attach():
      # The rbd device doesn't exist.
      return

    # Unmap the block device from the Volume.
    self._UnmapVolumeFromBlockdev(self.unique_id)

    self.minor = None
    self.dev_path = None

  def _UnmapVolumeFromBlockdev(self, unique_id):
    """Unmaps the rbd device from the Volume it is mapped.

    Unmaps the rbd device from the Volume it was previously mapped to.
    This method should be idempotent if the Volume isn't mapped.

    """
    pool = self.params[constants.LDP_POOL]
    name = unique_id[1]

    # Check if the mapping already exists.
    showmap_cmd = [constants.RBD_CMD, "showmapped", "-p", pool]
    result = utils.RunCmd(showmap_cmd)
    if result.failed:
      _ThrowError("rbd showmapped failed [during unmap](%s): %s",
                  result.fail_reason, result.output)

    rbd_dev = self._ParseRbdShowmappedOutput(result.output, name)

    if rbd_dev:
      # The mapping exists. Unmap the rbd device.
      unmap_cmd = [constants.RBD_CMD, "unmap", "%s" % rbd_dev]
      result = utils.RunCmd(unmap_cmd)
      if result.failed:
        _ThrowError("rbd unmap failed (%s): %s",
                    result.fail_reason, result.output)

  def Open(self, force=False):
    """Make the device ready for I/O.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    pass

  def Grow(self, amount, dryrun):
    """Grow the Volume.

    @type amount: integer
    @param amount: the amount (in mebibytes) to grow with
    @type dryrun: boolean
    @param dryrun: whether to execute the operation in simulation mode
        only, without actually increasing the size

    """
    if not self.Attach():
      _ThrowError("Can't attach to rbd device during Grow()")

    if dryrun:
      # the rbd tool does not support dry runs of resize operations.
      # Since rbd volumes are thinly provisioned, we assume
      # there is always enough free space for the operation.
      return

    rbd_pool = self.params[constants.LDP_POOL]
    rbd_name = self.unique_id[1]
    new_size = self.size + amount

    # Resize the rbd volume (Image) inside the RADOS cluster.
    cmd = [constants.RBD_CMD, "resize", "-p", rbd_pool,
           rbd_name, "--size", "%s" % new_size]
    result = utils.RunCmd(cmd)
    if result.failed:
      _ThrowError("rbd resize failed (%s): %s",
                  result.fail_reason, result.output)


DEV_MAP = {
  constants.LD_LV: LogicalVolume,
  constants.LD_DRBD8: DRBD8,
  constants.LD_BLOCKDEV: PersistentBlockDevice,
  constants.LD_RBD: RADOSBlockDevice,
  }

if constants.ENABLE_FILE_STORAGE or constants.ENABLE_SHARED_FILE_STORAGE:
  DEV_MAP[constants.LD_FILE] = FileStorage


def _VerifyDiskType(dev_type):
  if dev_type not in DEV_MAP:
    raise errors.ProgrammerError("Invalid block device type '%s'" % dev_type)


def _VerifyDiskParams(disk):
  """Verifies if all disk parameters are set.

  """
  missing = set(constants.DISK_LD_DEFAULTS[disk.dev_type]) - set(disk.params)
  if missing:
    raise errors.ProgrammerError("Block device is missing disk parameters: %s" %
                                 missing)


def FindDevice(disk, children):
  """Search for an existing, assembled device.

  This will succeed only if the device exists and is assembled, but it
  does not do any actions in order to activate the device.

  @type disk: L{objects.Disk}
  @param disk: the disk object to find
  @type children: list of L{bdev.BlockDev}
  @param children: the list of block devices that are children of the device
                  represented by the disk parameter

  """
  _VerifyDiskType(disk.dev_type)
  device = DEV_MAP[disk.dev_type](disk.physical_id, children, disk.size,
                                  disk.params)
  if not device.attached:
    return None
  return device


def Assemble(disk, children):
  """Try to attach or assemble an existing device.

  This will attach to assemble the device, as needed, to bring it
  fully up. It must be safe to run on already-assembled devices.

  @type disk: L{objects.Disk}
  @param disk: the disk object to assemble
  @type children: list of L{bdev.BlockDev}
  @param children: the list of block devices that are children of the device
                  represented by the disk parameter

  """
  _VerifyDiskType(disk.dev_type)
  _VerifyDiskParams(disk)
  device = DEV_MAP[disk.dev_type](disk.physical_id, children, disk.size,
                                  disk.params)
  device.Assemble()
  return device


def Create(disk, children):
  """Create a device.

  @type disk: L{objects.Disk}
  @param disk: the disk object to create
  @type children: list of L{bdev.BlockDev}
  @param children: the list of block devices that are children of the device
                  represented by the disk parameter

  """
  _VerifyDiskType(disk.dev_type)
  _VerifyDiskParams(disk)
  device = DEV_MAP[disk.dev_type].Create(disk.physical_id, children, disk.size,
                                         disk.params)
  return device
