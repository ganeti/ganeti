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

"""Utility functions for storage.

"""

import logging

from ganeti import constants


def GetDiskTemplatesOfStorageType(storage_type):
  """Given the storage type, returns a list of disk templates based on that
     storage type."""
  return [dt for dt in constants.DISK_TEMPLATES
          if constants.MAP_DISK_TEMPLATE_STORAGE_TYPE[dt] == storage_type]


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
    return (storage_type, constants.GLUSTER_MOUNTPOINT)
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
