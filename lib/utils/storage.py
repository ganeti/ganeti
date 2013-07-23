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
from ganeti import pathutils


def GetDiskTemplatesOfStorageType(storage_type):
  """Given the storage type, returns a list of disk templates based on that
     storage type."""
  return [dt for dt in constants.DISK_TEMPLATES
          if constants.DISK_TEMPLATES_STORAGE_TYPE[dt] == storage_type]


def GetLvmDiskTemplates():
  """Returns all disk templates that use LVM."""
  return GetDiskTemplatesOfStorageType(constants.ST_LVM_VG)


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
  return len(set(GetLvmDiskTemplates())
             .intersection(set(enabled_disk_templates))) != 0


def LvmGetsEnabled(enabled_disk_templates, new_enabled_disk_templates):
  """Checks whether lvm was not enabled before, but will be enabled after
     the operation.

  """
  if IsLvmEnabled(enabled_disk_templates):
    return False
  return set(GetLvmDiskTemplates()).intersection(
      set(new_enabled_disk_templates))


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
  storage_type = constants.DISK_TEMPLATES_STORAGE_TYPE[disk_template]
  cluster = cfg.GetClusterInfo()
  if disk_template in GetLvmDiskTemplates():
    return (storage_type, cfg.GetVGName())
  elif disk_template == constants.DT_FILE:
    return (storage_type, cluster.file_storage_dir)
  # FIXME: Adjust this, once SHARED_FILE_STORAGE_DIR
  # is not in autoconf anymore.
  elif disk_template == constants.DT_SHARED_FILE:
    return (storage_type, pathutils.DEFAULT_SHARED_FILE_STORAGE_DIR)
  else:
    return (storage_type, None)


def _GetDefaultStorageUnitForSpindles(cfg):
  """Creates a 'spindle' storage unit, by retrieving the volume group
  name and associating it to the lvm-pv storage type.

  @rtype: (string, string)
  @return: tuple (storage_type, storage_key), where storage type is
    'lvm-pv' and storage_key the name of the default volume group

  """
  return (constants.ST_LVM_PV, cfg.GetVGName())


def GetStorageUnitsOfCluster(cfg, include_spindles=False):
  """Examines the cluster's configuration and returns a list of storage
  units and their storage keys, ordered by the order in which they
  are enabled.

  @type cfg: L{config.ConfigWriter}
  @param cfg: Cluster configuration
  @type include_spindles: boolean
  @param include_spindles: flag to include an extra storage unit for physical
    volumes
  @rtype: list of tuples (string, string)
  @return: list of storage units, each storage unit being a tuple of
    (storage_type, storage_key); storage_type is in
    C{constants.VALID_STORAGE_TYPES} and the storage_key a string to
    identify an entity of that storage type, for example a volume group
    name for LVM storage or a file for file storage.

  """
  cluster_config = cfg.GetClusterInfo()
  storage_units = []
  for disk_template in cluster_config.enabled_disk_templates:
    if constants.DISK_TEMPLATES_STORAGE_TYPE[disk_template]\
        in constants.STS_REPORT:
      storage_units.append(
          _GetDefaultStorageUnitForDiskTemplate(cfg, disk_template))
  if include_spindles:
    included_storage_types = set([st for (st, _) in storage_units])
    if not constants.ST_LVM_PV in included_storage_types:
      storage_units.append(
          _GetDefaultStorageUnitForSpindles(cfg))

  return storage_units


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
