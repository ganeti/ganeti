#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012, 2013 Google Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
# IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
# TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Block device abstraction.

"""

import re
import stat
import os
import logging
import math

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import objects
from ganeti import compat
from ganeti import serializer
from ganeti.storage import base
from ganeti.storage import drbd
from ganeti.storage.filestorage import FileStorage
from ganeti.storage.gluster import GlusterStorage
from ganeti.storage.extstorage import ExtStorageDevice


class RbdShowmappedJsonError(Exception):
  """`rbd showmmapped' JSON formatting error Exception class.

  """
  pass


def _CheckResult(result):
  """Throws an error if the given result is a failed one.

  @param result: result from RunCmd

  """
  if result.failed:
    base.ThrowError("Command: %s error: %s - %s",
                    result.cmd, result.fail_reason, result.output)


class LogicalVolume(base.BlockDev):
  """Logical Volume block device.

  """
  _VALID_NAME_RE = re.compile("^[a-zA-Z0-9+_.-]*$")
  _PARSE_PV_DEV_RE = re.compile(r"^([^ ()]+)\([0-9]+\)$")
  _INVALID_NAMES = compat.UniqueFrozenset([".", "..", "snapshot", "pvmove"])
  _INVALID_SUBSTRINGS = compat.UniqueFrozenset(["_mlog", "_mimage"])

  def __init__(self, unique_id, children, size, params, dyn_params, **kwargs):
    """Attaches to a LV device.

    The unique_id is a tuple (vg_name, lv_name)

    """
    super(LogicalVolume, self).__init__(unique_id, children, size, params,
                                        dyn_params, **kwargs)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))
    self._vg_name, self._lv_name = unique_id
    self._ValidateName(self._vg_name)
    self._ValidateName(self._lv_name)
    self.dev_path = utils.PathJoin("/dev", self._vg_name, self._lv_name)
    self._degraded = True
    self.major = self.minor = self.pe_size = self.stripe_count = None
    self.pv_names = None
    lvs_cache = kwargs.get("lvs_cache")
    if lvs_cache:
      lv_info = lvs_cache.get(self.dev_path)
      self.Attach(lv_info=lv_info)
    else:
      self.Attach()

  @staticmethod
  def _GetStdPvSize(pvs_info):
    """Return the the standard PV size (used with exclusive storage).

    @param pvs_info: list of objects.LvmPvInfo, cannot be empty
    @rtype: float
    @return: size in MiB

    """
    assert len(pvs_info) > 0
    smallest = min([pv.size for pv in pvs_info])
    return smallest // (1 + constants.PART_MARGIN + constants.PART_RESERVED)

  @staticmethod
  def _ComputeNumPvs(size, pvs_info):
    """Compute the number of PVs needed for an LV (with exclusive storage).

    @type size: float
    @param size: LV size in MiB
    @param pvs_info: list of objects.LvmPvInfo, cannot be empty
    @rtype: integer
    @return: number of PVs needed
    """
    assert len(pvs_info) > 0
    pv_size = float(LogicalVolume._GetStdPvSize(pvs_info))
    return int(math.ceil(float(size) / pv_size))

  @staticmethod
  def _GetEmptyPvNames(pvs_info, max_pvs=None):
    """Return a list of empty PVs, by name.

    """
    empty_pvs = filter(objects.LvmPvInfo.IsEmpty, pvs_info)
    if max_pvs is not None:
      empty_pvs = empty_pvs[:max_pvs]
    return [pv.name for pv in empty_pvs]

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, **kwargs):
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
      if excl_stor:
        msg = "No (empty) PVs found"
      else:
        msg = "Can't compute PV info for vg %s" % vg_name
      base.ThrowError(msg)
    pvs_info.sort(key=(lambda pv: pv.free), reverse=True)

    pvlist = [pv.name for pv in pvs_info]
    if compat.any(":" in v for v in pvlist):
      base.ThrowError("Some of your PVs have the invalid character ':' in their"
                      " name, this is not supported - please filter them out"
                      " in lvm.conf using either 'filter' or 'preferred_names'")

    current_pvs = len(pvlist)
    desired_stripes = params[constants.LDP_STRIPES]
    stripes = min(current_pvs, desired_stripes)

    if excl_stor:
      if spindles is None:
        base.ThrowError("Unspecified number of spindles: this is required"
                        "when exclusive storage is enabled, try running"
                        " gnt-cluster repair-disk-sizes")
      (err_msgs, _) = utils.LvmExclusiveCheckNodePvs(pvs_info)
      if err_msgs:
        for m in err_msgs:
          logging.warning(m)
      req_pvs = cls._ComputeNumPvs(size, pvs_info)
      if spindles < req_pvs:
        base.ThrowError("Requested number of spindles (%s) is not enough for"
                        " a disk of %d MB (at least %d spindles needed)",
                        spindles, size, req_pvs)
      else:
        req_pvs = spindles
      pvlist = cls._GetEmptyPvNames(pvs_info, req_pvs)
      current_pvs = len(pvlist)
      if current_pvs < req_pvs:
        base.ThrowError("Not enough empty PVs (spindles) to create a disk of %d"
                        " MB: %d available, %d needed",
                        size, current_pvs, req_pvs)
      assert current_pvs == len(pvlist)
      # We must update stripes to be sure to use all the desired spindles
      stripes = current_pvs
      if stripes > desired_stripes:
        # Don't warn when lowering stripes, as it's no surprise
        logging.warning("Using %s stripes instead of %s, to be able to use"
                        " %s spindles", stripes, desired_stripes, current_pvs)

    else:
      if stripes < desired_stripes:
        logging.warning("Could not use %d stripes for VG %s, as only %d PVs are"
                        " available.", desired_stripes, vg_name, current_pvs)
      free_size = sum([pv.free for pv in pvs_info])
      # The size constraint should have been checked from the master before
      # calling the create function.
      if free_size < size:
        base.ThrowError("Not enough free space: required %s,"
                        " available %s", size, free_size)

    # If the free space is not well distributed, we won't be able to
    # create an optimally-striped volume; in that case, we want to try
    # with N, N-1, ..., 2, and finally 1 (non-stripped) number of
    # stripes
    cmd = ["lvcreate", "-L%dm" % size, "-n%s" % lv_name]
    for stripes_arg in range(stripes, 0, -1):
      result = utils.RunCmd(cmd + ["-i%d" % stripes_arg] + [vg_name] + pvlist)
      if not result.failed:
        break
    if result.failed:
      base.ThrowError("LV create failed (%s): %s",
                      result.fail_reason, result.output)
    return LogicalVolume(unique_id, children, size, params,
                         dyn_params, **kwargs)

  @staticmethod
  def _GetVolumeInfo(lvm_cmd, fields):
    """Returns LVM Volume infos using lvm_cmd

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
  def GetPVInfo(cls, vg_names, filter_allocatable=True, include_lvs=False):
    """Get the free space info for PVs in a volume group.

    @param vg_names: list of volume group names, if empty all will be returned
    @param filter_allocatable: whether to skip over unallocatable PVs
    @param include_lvs: whether to include a list of LVs hosted on each PV

    @rtype: list
    @return: list of objects.LvmPvInfo objects

    """
    # We request "lv_name" field only if we care about LVs, so we don't get
    # a long list of entries with many duplicates unless we really have to.
    # The duplicate "pv_name" field will be ignored.
    if include_lvs:
      lvfield = "lv_name"
    else:
      lvfield = "pv_name"
    try:
      info = cls._GetVolumeInfo("pvs", ["pv_name", "vg_name", "pv_free",
                                        "pv_attr", "pv_size", lvfield])
    except errors.GenericError as err:
      logging.error("Can't get PV information: %s", err)
      return None

    # When asked for LVs, "pvs" may return multiple entries for the same PV-LV
    # pair. We sort entries by PV name and then LV name, so it's easy to weed
    # out duplicates.
    if include_lvs:
      info.sort(key=(lambda i: (i[0], i[5])))
    data = []
    lastpvi = None
    for (pv_name, vg_name, pv_free, pv_attr, pv_size, lv_name) in info:
      # (possibly) skip over pvs which are not allocatable
      if filter_allocatable and pv_attr[0] != "a":
        continue
      # (possibly) skip over pvs which are not in the right volume group(s)
      if vg_names and vg_name not in vg_names:
        continue
      # Beware of duplicates (check before inserting)
      if lastpvi and lastpvi.name == pv_name:
        if include_lvs and lv_name:
          if not lastpvi.lv_list or lastpvi.lv_list[-1] != lv_name:
            lastpvi.lv_list.append(lv_name)
      else:
        if include_lvs and lv_name:
          lvl = [lv_name]
        else:
          lvl = []
        lastpvi = objects.LvmPvInfo(name=pv_name, vg_name=vg_name,
                                    size=float(pv_size), free=float(pv_free),
                                    attributes=pv_attr, lv_list=lvl)
        data.append(lastpvi)

    return data

  @classmethod
  def _GetRawFreePvInfo(cls, vg_name):
    """Return info (size/free) about PVs.

    @type vg_name: string
    @param vg_name: VG name
    @rtype: tuple
    @return: (standard_pv_size_in_MiB, number_of_free_pvs, total_number_of_pvs)

    """
    pvs_info = cls.GetPVInfo([vg_name])
    if not pvs_info:
      pv_size = 0.0
      free_pvs = 0
      num_pvs = 0
    else:
      pv_size = cls._GetStdPvSize(pvs_info)
      free_pvs = len(cls._GetEmptyPvNames(pvs_info))
      num_pvs = len(pvs_info)
    return (pv_size, free_pvs, num_pvs)

  @classmethod
  def _GetExclusiveStorageVgFree(cls, vg_name):
    """Return the free disk space in the given VG, in exclusive storage mode.

    @type vg_name: string
    @param vg_name: VG name
    @rtype: float
    @return: free space in MiB
    """
    (pv_size, free_pvs, _) = cls._GetRawFreePvInfo(vg_name)
    return pv_size * free_pvs

  @classmethod
  def GetVgSpindlesInfo(cls, vg_name):
    """Get the free space info for specific VGs.

    @param vg_name: volume group name
    @rtype: tuple
    @return: (free_spindles, total_spindles)

    """
    (_, free_pvs, num_pvs) = cls._GetRawFreePvInfo(vg_name)
    return (free_pvs, num_pvs)

  @classmethod
  def GetVGInfo(cls, vg_names, excl_stor, filter_readonly=True):
    """Get the free space info for specific VGs.

    @param vg_names: list of volume group names, if empty all will be returned
    @param excl_stor: whether exclusive_storage is enabled
    @param filter_readonly: whether to skip over readonly VGs

    @rtype: list
    @return: list of tuples (free_space, total_size, name) with free_space in
             MiB

    """
    try:
      info = cls._GetVolumeInfo("vgs", ["vg_name", "vg_free", "vg_attr",
                                        "vg_size"])
    except errors.GenericError as err:
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
      # Exclusive storage needs a different concept of free space
      if excl_stor:
        es_free = cls._GetExclusiveStorageVgFree(vg_name)
        assert es_free <= vg_free
        vg_free = es_free
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
      base.ThrowError("Invalid LVM name '%s'", name)

  def Remove(self):
    """Remove this logical volume.

    """
    if not self.minor and not self.Attach():
      # the LV does not exist
      return
    result = utils.RunCmd(["lvremove", "-f", "%s/%s" %
                           (self._vg_name, self._lv_name)])
    if result.failed:
      base.ThrowError("Can't lvremove: %s - %s",
                      result.fail_reason, result.output)

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
      base.ThrowError("Failed to rename the logical volume: %s", result.output)
    self._lv_name = new_name
    self.dev_path = utils.PathJoin("/dev", self._vg_name, self._lv_name)

  @staticmethod
  def _ParseLvInfoLine(line, sep):
    """Parse one line of the lvs output used in L{GetLvGlobalInfo}.

    """
    elems = line.strip().split(sep)

    # The previous iteration of code here assumed that LVM might put another
    # separator to the right of the output. The PV info might be empty for
    # thin volumes, so stripping off the separators might cut off the last
    # empty element - do this instead.
    if len(elems) == 9 and elems[-1] == "":
      elems.pop()

    if len(elems) != 8:
      base.ThrowError("Can't parse LVS output, len(%s) != 8", str(elems))

    (vg_name, lv_name, status, major, minor, pe_size, stripes, pvs) = elems
    path = os.path.join(os.environ.get('DM_DEV_DIR', '/dev'), vg_name, lv_name)
    if len(status) < 6:
      base.ThrowError("lvs lv_attr is not at least 6 characters (%s)", status)

    try:
      major = int(major)
      minor = int(minor)
    except (TypeError, ValueError) as err:
      base.ThrowError("lvs major/minor cannot be parsed: %s", str(err))

    try:
      pe_size = int(float(pe_size))
    except (TypeError, ValueError) as err:
      base.ThrowError("Can't parse vg extent size: %s", err)

    try:
      stripes = int(stripes)
    except (TypeError, ValueError) as err:
      base.ThrowError("Can't parse the number of stripes: %s", err)

    pv_names = []
    if pvs != "":
      for pv in pvs.split(","):
        m = re.match(LogicalVolume._PARSE_PV_DEV_RE, pv)
        if not m:
          base.ThrowError("Can't parse this device list: %s", pvs)
        pv_names.append(m.group(1))

    return (path, (status, major, minor, pe_size, stripes, pv_names))

  @staticmethod
  def GetLvGlobalInfo(_run_cmd=utils.RunCmd):
    """Obtain the current state of the existing LV disks.

    @return: a dict containing the state of each disk with the disk path as key

    """
    sep = "|"
    result = _run_cmd(["lvs", "--noheadings", "--separator=%s" % sep,
                       "--units=k", "--nosuffix",
                       "-ovg_name,lv_name,lv_attr,lv_kernel_major,"
                       "lv_kernel_minor,vg_extent_size,stripes,devices"])
    if result.failed:
      logging.warning("lvs command failed, the LV cache will be empty!")
      logging.info("lvs failure: %r", result.stderr)
      return {}
    out = result.stdout.splitlines()
    if not out:
      logging.warning("lvs command returned an empty output, the LV cache will"
                      "be empty!")
      return {}
    return dict([LogicalVolume._ParseLvInfoLine(line, sep) for line in out])

  def Attach(self, lv_info=None, **kwargs):
    """Attach to an existing LV.

    This method will try to see if an existing and active LV exists
    which matches our name. If so, its major/minor will be
    recorded.

    """
    self.attached = False
    if not lv_info:
      lv_info = LogicalVolume.GetLvGlobalInfo().get(self.dev_path)
    if not lv_info:
      return False
    (status, major, minor, pe_size, stripes, pv_names) = lv_info

    self.major = major
    self.minor = minor
    self.pe_size = pe_size
    self.stripe_count = stripes
    self._degraded = status[0] == "v" # virtual volume, i.e. doesn't backing
                                      # storage
    self.pv_names = pv_names
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
      base.ThrowError("Can't activate lv %s: %s", self.dev_path, result.output)

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

  def Open(self, force=False, exclusive=True):
    """Make the device ready for I/O.

    This is a no-op for the LV device type.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    This is a no-op for the LV device type.

    """
    pass

  def Snapshot(self, snap_name=None, snap_size=None):
    """Create a snapshot copy of an lvm block device.

    @returns: tuple (vg, lv)

    """
    if not snap_name:
      snap_name = self._lv_name + ".snap"

    if not snap_size:
      # FIXME: choose a saner value for the snapshot size
      # let's stay on the safe side and ask for the full size, for now
      snap_size = self.size

    # remove existing snapshot if found
    snap = LogicalVolume((self._vg_name, snap_name), None, snap_size,
                         self.params, self.dyn_params)
    base.IgnoreError(snap.Remove)

    vg_info = self.GetVGInfo([self._vg_name], False)
    if not vg_info:
      base.ThrowError("Can't compute VG info for vg %s", self._vg_name)
    free_size, _, _ = vg_info[0]
    if free_size < snap_size:
      base.ThrowError("Not enough free space: required %s,"
                      " available %s", snap_size, free_size)

    _CheckResult(utils.RunCmd(["lvcreate", "-L%dm" % snap_size, "-s",
                               "-n%s" % snap_name, self.dev_path]))

    return (self._vg_name, snap_name)

  def _RemoveOldInfo(self):
    """Try to remove old tags from the lv.

    """
    result = utils.RunCmd(["lvs", "-o", "tags", "--noheadings", "--nosuffix",
                           self.dev_path])
    _CheckResult(result)

    raw_tags = result.stdout.strip()
    if raw_tags:
      for tag in raw_tags.split(","):
        _CheckResult(utils.RunCmd(["lvchange", "--deltag",
                                   tag.strip(), self.dev_path]))

  def SetInfo(self, text):
    """Update metadata with info text.

    """
    base.BlockDev.SetInfo(self, text)

    self._RemoveOldInfo()

    # Replace invalid characters
    text = re.sub("^[^A-Za-z0-9_+.]", "_", text)
    text = re.sub("[^-A-Za-z0-9_+.]", "_", text)

    # Only up to 128 characters are allowed
    text = text[:128]

    _CheckResult(utils.RunCmd(["lvchange", "--addtag", text, self.dev_path]))

  def _GetGrowthAvaliabilityExclStor(self):
    """Return how much the disk can grow with exclusive storage.

    @rtype: float
    @return: available space in Mib

    """
    pvs_info = self.GetPVInfo([self._vg_name])
    if not pvs_info:
      base.ThrowError("Cannot get information about PVs for %s", self.dev_path)
    std_pv_size = self._GetStdPvSize(pvs_info)
    free_space = sum(pvi.free - (pvi.size - std_pv_size)
                        for pvi in pvs_info
                        if pvi.name in self.pv_names)
    return free_space

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the logical volume.

    """
    if not backingstore:
      return
    if self.pe_size is None or self.stripe_count is None:
      if not self.Attach():
        base.ThrowError("Can't attach to LV during Grow()")
    full_stripe_size = self.pe_size * self.stripe_count
    # pe_size is in KB
    amount *= 1024
    rest = amount % full_stripe_size
    if rest != 0:
      amount += full_stripe_size - rest
    cmd = ["lvextend", "-L", "+%dk" % amount]
    if dryrun:
      cmd.append("--test")
    if excl_stor:
      free_space = self._GetGrowthAvaliabilityExclStor()
      # amount is in KiB, free_space in MiB
      if amount > free_space * 1024:
        base.ThrowError("Not enough free space to grow %s: %d MiB required,"
                        " %d available", self.dev_path, amount // 1024,
                        free_space)
      # Disk growth doesn't grow the number of spindles, so we must stay within
      # our assigned volumes
      pvlist = list(self.pv_names)
    else:
      pvlist = []
    # we try multiple algorithms since the 'best' ones might not have
    # space available in the right place, but later ones might (since
    # they have less constraints); also note that only recent LVM
    # supports 'cling'
    for alloc_policy in "contiguous", "cling", "normal":
      result = utils.RunCmd(cmd + ["--alloc", alloc_policy, self.dev_path] +
                            pvlist)
      if not result.failed:
        return
    base.ThrowError("Can't grow LV %s: %s", self.dev_path, result.output)

  def GetActualSpindles(self):
    """Return the number of spindles used.

    """
    assert self.attached, "BlockDevice not attached in GetActualSpindles()"
    return len(self.pv_names)


class PersistentBlockDevice(base.BlockDev):
  """A block device with persistent node

  May be either directly attached, or exposed through DM (e.g. dm-multipath).
  udev helpers are probably required to give persistent, human-friendly
  names.

  For the time being, pathnames are required to lie under /dev.

  """
  def __init__(self, unique_id, children, size, params, dyn_params, **kwargs):
    """Attaches to a static block device.

    The unique_id is a path under /dev.

    """
    super(PersistentBlockDevice, self).__init__(unique_id, children, size,
                                                params, dyn_params, **kwargs)
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
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, **kwargs):
    """Create a new device

    This is a noop, we only return a PersistentBlockDevice instance

    """
    if excl_stor:
      raise errors.ProgrammerError("Persistent block device requested with"
                                   " exclusive_storage")
    return PersistentBlockDevice(unique_id, children, 0, params, dyn_params,
                                 **kwargs)

  def Remove(self):
    """Remove a device

    This is a noop

    """
    pass

  def Rename(self, new_id):
    """Rename this device.

    """
    base.ThrowError("Rename is not supported for PersistentBlockDev storage")

  def Attach(self):
    """Attach to an existing block device.

    """
    self.attached = False
    try:
      st = os.stat(self.dev_path)
    except OSError as err:
      logging.error("Error stat()'ing %s: %s", self.dev_path, str(err))
      return False

    if not stat.S_ISBLK(st.st_mode):
      logging.error("%s is not a block device", self.dev_path)
      return False

    self.major = os.major(st.st_rdev)
    self.minor = utils.osminor(st.st_rdev)
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

  def Open(self, force=False, exclusive=True):
    """Make the device ready for I/O.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    pass

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the logical volume.

    """
    base.ThrowError("Grow is not supported for PersistentBlockDev storage")

  def Import(self):
    """Builds the shell command for importing data to device.

    @see: L{BlockDev.Import} for details

    """
    base.ThrowError("Importing data is not supported for the"
                    " PersistentBlockDevice template")


class RADOSBlockDevice(base.BlockDev):
  """A RADOS Block Device (rbd).

  This class implements the RADOS Block Device for the backend. You need
  the rbd kernel driver, the RADOS Tools and a working RADOS cluster for
  this to be functional.

  """
  def __init__(self, unique_id, children, size, params, dyn_params, **kwargs):
    """Attaches to an rbd device.

    """
    super(RADOSBlockDevice, self).__init__(unique_id, children, size, params,
                                           dyn_params, **kwargs)
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise ValueError("Invalid configuration data %s" % str(unique_id))

    self.driver, self.rbd_name = unique_id
    self.rbd_pool = params[constants.LDP_POOL]

    self.major = self.minor = None
    self.Attach()

  @classmethod
  def Create(cls, unique_id, children, size, spindles, params, excl_stor,
             dyn_params, **kwargs):
    """Create a new rbd device.

    Provision a new rbd volume inside a RADOS pool.

    """
    if not isinstance(unique_id, (tuple, list)) or len(unique_id) != 2:
      raise errors.ProgrammerError("Invalid configuration data %s" %
                                   str(unique_id))
    if excl_stor:
      raise errors.ProgrammerError("RBD device requested with"
                                   " exclusive_storage")
    rbd_pool = params[constants.LDP_POOL]
    rbd_name = unique_id[1]

    # Provision a new rbd volume (Image) inside the RADOS cluster.
    cmd = [constants.RBD_CMD, "create", "-p", rbd_pool,
           rbd_name, "--size", "%s" % size]
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("rbd creation failed (%s): %s",
                      result.fail_reason, result.output)

    return RADOSBlockDevice(unique_id, children, size, params, dyn_params,
                            **kwargs)

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
      base.ThrowError("Can't remove Volume from cluster with rbd rm: %s - %s",
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
    except OSError as err:
      logging.error("Error stat()'ing %s: %s", self.dev_path, str(err))
      return False

    if not stat.S_ISBLK(st.st_mode):
      logging.error("%s is not a block device", self.dev_path)
      return False

    self.major = os.major(st.st_rdev)
    self.minor = utils.osminor(st.st_rdev)
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
    rbd_dev = self._VolumeToBlockdev(pool, name)
    if rbd_dev:
      # The mapping exists. Return it.
      return rbd_dev

    # The mapping doesn't exist. Create it.
    map_cmd = [constants.RBD_CMD, "map", "-p", pool, name]
    result = utils.RunCmd(map_cmd)
    if result.failed:
      base.ThrowError("rbd map failed (%s): %s",
                      result.fail_reason, result.output)

    # Find the corresponding rbd device.
    rbd_dev = self._VolumeToBlockdev(pool, name)
    if not rbd_dev:
      base.ThrowError("rbd map succeeded, but could not find the rbd block"
                      " device in output of showmapped, for volume: %s", name)

    # The device was successfully mapped. Return it.
    return rbd_dev

  @classmethod
  def _VolumeToBlockdev(cls, pool, volume_name):
    """Do the 'volume name'-to-'rbd block device' resolving.

    @type pool: string
    @param pool: RADOS pool to use
    @type volume_name: string
    @param volume_name: the name of the volume whose device we search for
    @rtype: string or None
    @return: block device path if the volume is mapped, else None

    """
    try:
      # Newer versions of the rbd tool support json output formatting. Use it
      # if available.
      showmap_cmd = [
        constants.RBD_CMD,
        "showmapped",
        "--format",
        "json"
        ]
      result = utils.RunCmd(showmap_cmd)
      if result.failed:
        logging.error("rbd JSON output formatting returned error (%s): %s,"
                      "falling back to plain output parsing",
                      result.fail_reason, result.output)
        raise RbdShowmappedJsonError

      return cls._ParseRbdShowmappedJson(result.output, pool, volume_name)
    except RbdShowmappedJsonError:
      # For older versions of rbd, we have to parse the plain / text output
      # manually.
      showmap_cmd = [constants.RBD_CMD, "showmapped", "-p", pool]
      result = utils.RunCmd(showmap_cmd)
      if result.failed:
        base.ThrowError("rbd showmapped failed (%s): %s",
                        result.fail_reason, result.output)

      return cls._ParseRbdShowmappedPlain(result.output, volume_name)

  @staticmethod
  def _ParseRbdShowmappedJson(output, volume_pool, volume_name):
    """Parse the json output of `rbd showmapped'.

    This method parses the json output of `rbd showmapped' and returns the rbd
    block device path (e.g. /dev/rbd0) that matches the given rbd volume.

    @type output: string
    @param output: the json output of `rbd showmapped'
    @type volume_pool: string
    @param volume_pool: name of the volume whose device we search for
    @type volume_name: string
    @param volume_name: name of the pool in which we search
    @rtype: string or None
    @return: block device path if the volume is mapped, else None

    """
    try:
      devices = serializer.LoadJson(output)
    except ValueError as err:
      base.ThrowError("Unable to parse JSON data: %s" % err)

    # since ceph mimic the json output changed from dict to list
    if isinstance(devices, dict):
      devices = list(devices.values())

    rbd_dev = None
    for d in devices:
      try:
        name = d["name"]
      except KeyError:
        base.ThrowError("'name' key missing from json object %s", devices)

      try:
        pool = d["pool"]
      except KeyError:
        base.ThrowError("'pool' key missing from json object %s", devices)

      if name == volume_name and pool == volume_pool:
        if rbd_dev is not None:
          base.ThrowError("rbd volume %s is mapped more than once", volume_name)

        rbd_dev = d["device"]

    return rbd_dev

  @staticmethod
  def _ParseRbdShowmappedPlain(output, volume_name):
    """Parse the (plain / text) output of `rbd showmapped'.

    This method parses the output of `rbd showmapped' and returns
    the rbd block device path (e.g. /dev/rbd0) that matches the
    given rbd volume.

    @type output: string
    @param output: the plain text output of `rbd showmapped'
    @type volume_name: string
    @param volume_name: the name of the volume whose device we search for
    @rtype: string or None
    @return: block device path if the volume is mapped, else None

    """
    allfields = 5
    volumefield = 2
    devicefield = 4

    lines = output.splitlines()

    # Try parsing the new output format (ceph >= 0.55).
    splitted_lines = [l.split() for l in lines]

    # Check for empty output.
    if not splitted_lines:
      return None

    # Check showmapped output, to determine number of fields.
    field_cnt = len(splitted_lines[0])
    if field_cnt != allfields:
      # Parsing the new format failed. Fallback to parsing the old output
      # format (< 0.55).
      splitted_lines = [l.split("\t") for l in lines]
      if field_cnt != allfields:
        base.ThrowError("Cannot parse rbd showmapped output expected %s fields,"
                        " found %s", allfields, field_cnt)

    matched_lines = [l for l in splitted_lines
                     if len(l) == allfields and l[volumefield] == volume_name]

    if len(matched_lines) > 1:
      base.ThrowError("rbd volume %s mapped more than once", volume_name)

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
    rbd_dev = self._VolumeToBlockdev(pool, name)

    if rbd_dev:
      # The mapping exists. Unmap the rbd device.
      unmap_cmd = [constants.RBD_CMD, "unmap", "%s" % rbd_dev]
      result = utils.RunCmd(unmap_cmd)
      if result.failed:
        base.ThrowError("rbd unmap failed (%s): %s",
                        result.fail_reason, result.output)

  def Open(self, force=False, exclusive=True):
    """Make the device ready for I/O.

    """
    pass

  def Close(self):
    """Notifies that the device will no longer be used for I/O.

    """
    pass

  def Grow(self, amount, dryrun, backingstore, excl_stor):
    """Grow the Volume.

    @type amount: integer
    @param amount: the amount (in mebibytes) to grow with
    @type dryrun: boolean
    @param dryrun: whether to execute the operation in simulation mode
        only, without actually increasing the size

    """
    if not backingstore:
      return
    if not self.Attach():
      base.ThrowError("Can't attach to rbd device during Grow()")

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
      base.ThrowError("rbd resize failed (%s): %s",
                      result.fail_reason, result.output)

  def Import(self):
    """Builds the shell command for importing data to device.

    @see: L{BlockDev.Import} for details

    """
    if not self.minor and not self.Attach():
      # The rbd device doesn't exist.
      base.ThrowError("Can't attach to rbd device during Import()")

    rbd_pool = self.params[constants.LDP_POOL]
    rbd_name = self.unique_id[1]

    # Currently, the 'rbd import' command imports data only to non-existing
    # volumes. If the rbd volume exists the command will fail.
    # The disk conversion mechanism though, has already created the new rbd
    # volume at the time we perform the data copy, so we have to first remove
    # the volume before starting to import its data. The 'rbd import' will
    # re-create the rbd volume. We choose to remove manually the rbd device
    # instead of calling its 'Remove()' method to avoid affecting the 'self.'
    # parameters of the device. Also, this part of the removal code will go
    # away once 'rbd import' has support for importing into an existing volume.
    # TODO: update this method when the 'rbd import' command supports the
    # '--force' option, which will allow importing to an existing volume.

    # Unmap the block device from the Volume.
    self._UnmapVolumeFromBlockdev(self.unique_id)

    # Remove the actual Volume (Image) from the RADOS cluster.
    cmd = [constants.RBD_CMD, "rm", "-p", rbd_pool, rbd_name]
    result = utils.RunCmd(cmd)
    if result.failed:
      base.ThrowError("Can't remove Volume from cluster with rbd rm: %s - %s",
                      result.fail_reason, result.output)

    # We use "-" for importing from stdin
    return [constants.RBD_CMD, "import",
            "-p", rbd_pool,
            "-", rbd_name]

  def Export(self):
    """Builds the shell command for exporting data from device.

    @see: L{BlockDev.Export} for details

    """
    if not self.minor and not self.Attach():
      # The rbd device doesn't exist.
      base.ThrowError("Can't attach to rbd device during Export()")

    rbd_pool = self.params[constants.LDP_POOL]
    rbd_name = self.unique_id[1]

    # We use "-" for exporting to stdout.
    return [constants.RBD_CMD, "export",
            "-p", rbd_pool,
            rbd_name, "-"]

  def GetUserspaceAccessUri(self, hypervisor):
    """Generate KVM userspace URIs to be used as `-drive file` settings.

    @see: L{BlockDev.GetUserspaceAccessUri}

    """
    if hypervisor == constants.HT_KVM:
      return "rbd:" + self.rbd_pool + "/" + self.rbd_name
    else:
      base.ThrowError("Hypervisor %s doesn't support RBD userspace access" %
                      hypervisor)


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


def FindDevice(disk, children, **kwargs):
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
  device = DEV_MAP[disk.dev_type](disk.logical_id, children, disk.size,
                                  disk.params, disk.dynamic_params,
                                  name=disk.name, uuid=disk.uuid, **kwargs)
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
  device = DEV_MAP[disk.dev_type](disk.logical_id, children, disk.size,
                                  disk.params, disk.dynamic_params,
                                  name=disk.name, uuid=disk.uuid)
  device.Assemble()
  return device


def Create(disk, children, excl_stor):
  """Create a device.

  @type disk: L{objects.Disk}
  @param disk: the disk object to create
  @type children: list of L{bdev.BlockDev}
  @param children: the list of block devices that are children of the device
                  represented by the disk parameter
  @type excl_stor: boolean
  @param excl_stor: Whether exclusive_storage is active
  @rtype: L{bdev.BlockDev}
  @return: the created device, or C{None} in case of an error

  """
  _VerifyDiskType(disk.dev_type)
  _VerifyDiskParams(disk)
  device = DEV_MAP[disk.dev_type].Create(disk.logical_id, children, disk.size,
                                         disk.spindles, disk.params, excl_stor,
                                         disk.dynamic_params,
                                         name=disk.name, uuid=disk.uuid)
  return device

# Please keep this at the bottom of the file for visibility.
DEV_MAP = {
  constants.DT_PLAIN: LogicalVolume,
  constants.DT_DRBD8: drbd.DRBD8Dev,
  constants.DT_BLOCK: PersistentBlockDevice,
  constants.DT_RBD: RADOSBlockDevice,
  constants.DT_EXT: ExtStorageDevice,
  constants.DT_FILE: FileStorage,
  constants.DT_SHARED_FILE: FileStorage,
  constants.DT_GLUSTER: GlusterStorage,
}
"""Map disk types to disk type classes.

@see: L{Assemble}, L{FindDevice}, L{Create}.""" # pylint: disable=W0105
