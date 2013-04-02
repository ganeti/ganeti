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

from ganeti import constants


def GetDiskTemplatesOfStorageType(storage_type):
  """Given the storage type, returns a list of disk templates based on that
     storage type."""
  return [dt for dt in constants.DISK_TEMPLATES
          if constants.DISK_TEMPLATES_STORAGE_TYPE[dt] == storage_type]


def GetLvmDiskTemplates():
  """Returns all disk templates that use LVM."""
  return GetDiskTemplatesOfStorageType(constants.ST_LVM_VG)


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
