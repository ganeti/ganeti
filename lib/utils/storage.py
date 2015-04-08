#
#

# Copyright (C) 2013 Google Inc.
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

"""Utility functions for storage.

"""

import logging

from ganeti import constants


def GetDiskTemplatesOfStorageTypes(*storage_types):
  """Given the storage type, returns a list of disk templates based on that
     storage type."""
  return [dt for dt in constants.DISK_TEMPLATES
          if constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[dt] in storage_types]


def IsDiskTemplateEnabled(disk_template, enabled_disk_templates):
  """Checks if a particular disk template is enabled.

  """
  return disk_template in enabled_disk_templates


def IsFileStorageEnabled(enabled_disk_templates):
  """Checks if file storage is enabled.

  """
  return IsDiskTemplateEnabled(constants.DT_FILE, enabled_disk_templates)


def IsSharedFileStorageEnabled(enabled_disk_templates):
  """Checks if shared file storage is enabled.

  """
  return IsDiskTemplateEnabled(constants.DT_SHARED_FILE, enabled_disk_templates)


def IsLvmEnabled(enabled_disk_templates):
  """Check whether or not any lvm-based disk templates are enabled."""
  return len(constants.DTS_LVM & set(enabled_disk_templates)) != 0


def LvmGetsEnabled(enabled_disk_templates, new_enabled_disk_templates):
  """Checks whether lvm was not enabled before, but will be enabled after
     the operation.

  """
  if IsLvmEnabled(enabled_disk_templates):
    return False
  return len(constants.DTS_LVM & set(new_enabled_disk_templates)) != 0


def _GetDefaultStorageUnitForDiskTemplate(cfg, disk_template):
  """Retrieves the identifier of the default storage entity for the given
  storage type.

  @type cfg: C{objects.ConfigData}
  @param cfg: the configuration data
  @type disk_template: string
  @param disk_template: a disk template, for example 'drbd'
  @rtype: string
  @return: identifier for a storage unit, for example the vg_name for lvm
     storage

  """
  storage_type = constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template]
  cluster = cfg.GetClusterInfo()
  if disk_template in constants.DTS_LVM:
    return (storage_type, cfg.GetVGName())
  elif disk_template == constants.DT_FILE:
    return (storage_type, cluster.file_storage_dir)
  elif disk_template == constants.DT_SHARED_FILE:
    return (storage_type, cluster.shared_file_storage_dir)
  elif disk_template == constants.DT_GLUSTER:
    return (storage_type, cluster.gluster_storage_dir)
  else:
    return (storage_type, None)


def DiskTemplateSupportsSpaceReporting(disk_template):
  """Check whether the disk template supports storage space reporting."""
  return (constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template]
          in constants.STS_REPORT)


def GetStorageUnits(cfg, disk_templates):
  """Get the cluster's storage units for the given disk templates.

  If any lvm-based disk template is requested, spindle information
  is added to the request.

  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @type disk_templates: list of string
  @param disk_templates: list of disk templates for which the storage
    units will be computed
  @rtype: list of tuples (string, string)
  @return: list of storage units, each storage unit being a tuple of
    (storage_type, storage_key); storage_type is in
    C{constants.STORAGE_TYPES} and the storage_key a string to
    identify an entity of that storage type, for example a volume group
    name for LVM storage or a file for file storage.

  """
  storage_units = []
  for disk_template in disk_templates:
    if DiskTemplateSupportsSpaceReporting(disk_template):
      storage_units.append(
          _GetDefaultStorageUnitForDiskTemplate(cfg, disk_template))
  return storage_units


def LookupSpaceInfoByDiskTemplate(storage_space_info, disk_template):
  """Looks up the storage space info for a given disk template.

  @type storage_space_info: list of dicts
  @param storage_space_info: result of C{GetNodeInfo}
  @type disk_template: string
  @param disk_template: disk template to get storage space info
  @rtype: tuple
  @return: returns the element of storage_space_info that matches the given
    disk template

  """
  storage_type = constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[disk_template]
  return LookupSpaceInfoByStorageType(storage_space_info, storage_type)


def LookupSpaceInfoByStorageType(storage_space_info, storage_type):
  """Looks up the storage space info for a given storage type.

  Note that this lookup can be ambiguous if storage space reporting for several
  units of the same storage type was requested. This function is only supposed
  to be used for legacy code in situations where it actually is unambiguous.

  @type storage_space_info: list of dicts
  @param storage_space_info: result of C{GetNodeInfo}
  @type storage_type: string
  @param storage_type: a storage type, which is included in the storage_units
    list
  @rtype: tuple
  @return: returns the element of storage_space_info that matches the given
    storage type

  """
  result = None
  for unit_info in storage_space_info:
    if unit_info["type"] == storage_type:
      if result is None:
        result = unit_info
      else:
        # There is more than one storage type in the query, log a warning
        logging.warning("Storage space information requested for"
                        " ambiguous storage type '%s'.", storage_type)
  return result


def GetDiskLabels(prefix, num_disks, start=0):
  """Generate disk labels for a number of disks

  Note that disk labels are generated in the range [start..num_disks[
  (e.g., as in range(start, num_disks))

  @type prefix: string
  @param prefix: disk label prefix (e.g., "/dev/sd")

  @type num_disks: int
  @param num_disks: number of disks (i.e., disk labels)

  @type start: int
  @param start: optional start index

  @rtype: generator
  @return: generator for the disk labels

  """
  def _GetDiskSuffix(i):
    n = ord('z') - ord('a') + 1
    if i < n:
      return chr(ord('a') + i)
    else:
      mod = int(i % n)
      pref = _GetDiskSuffix((i - mod) / (n + 1))
      suf = _GetDiskSuffix(mod)
      return pref + suf

  for i in range(start, num_disks):
    yield prefix + _GetDiskSuffix(i)


def osminor(dev):
  """Return the device minor number from a raw device number.

  This is a replacement for os.minor working around the issue that
  Python's os.minor still has the old definition. See Ganeti issue
  1058 for more details.
  """
  return (dev & 0xff) | ((dev >> 12) & ~0xff)
