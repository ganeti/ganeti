#
#

# Copyright (C) 2009 Google Inc.
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


"""Storage container abstraction.

"""


import logging

from ganeti import errors
from ganeti import constants
from ganeti import utils


COL_NAME = "name"
COL_SIZE = "size"
COL_FREE = "free"
COL_USED = "used"
COL_ALLOCATABLE = "allocatable"


def _ParseSize(value):
  return int(round(float(value), 0))


class _Base:
  """Base class for storage abstraction.

  """
  def List(self, name, fields):
    """Returns a list of all entities within the storage unit.

    @type name: string or None
    @param name: Entity name or None for all
    @type fields: list
    @param fields: List with all requested result fields (order is preserved)

    """
    raise NotImplementedError()


class FileStorage(_Base):
  """File storage unit.

  """
  def __init__(self, paths):
    """Initializes this class.

    @type paths: list
    @param paths: List of file storage paths

    """
    self._paths = paths

  def List(self, name, fields):
    """Returns a list of all entities within the storage unit.

    See L{_Base.List}.

    """
    rows = []

    if name is None:
      paths = self._paths
    else:
      paths = [name]

    for path in paths:
      rows.append(self._ListInner(path, fields))

    return rows

  @staticmethod
  def _ListInner(path, fields):
    """Gathers requested information from directory.

    @type path: string
    @param path: Path to directory
    @type fields: list
    @param fields: Requested fields

    """
    values = []

    # Pre-calculate information in case it's requested more than once
    if COL_SIZE in fields:
      dirsize = utils.CalculateDirectorySize(path)
    else:
      dirsize = None

    if COL_FREE in fields:
      fsfree = utils.GetFreeFilesystemSpace(path)
    else:
      fsfree = None

    for field_name in fields:
      if field_name == COL_NAME:
        values.append(path)

      elif field_name == COL_SIZE:
        values.append(dirsize)

      elif field_name == COL_FREE:
        values.append(fsfree)

      else:
        raise errors.StorageError("Unknown field: %r" % field_name)

    return values


class _LvmBase(_Base):
  """Base class for LVM storage containers.

  """
  LIST_SEP = "|"
  LIST_COMMAND = None
  LIST_FIELDS = None

  def List(self, name, wanted_field_names):
    """Returns a list of all entities within the storage unit.

    See L{_Base.List}.

    """
    # Get needed LVM fields
    lvm_fields = self._GetLvmFields(self.LIST_FIELDS, wanted_field_names)

    # Build LVM command
    cmd_args = self._BuildListCommand(self.LIST_COMMAND, self.LIST_SEP,
                                      lvm_fields, name)

    # Run LVM command
    cmd_result = self._RunListCommand(cmd_args)

    # Split and rearrange LVM command output
    return self._BuildList(self._SplitList(cmd_result, self.LIST_SEP,
                                           len(lvm_fields)),
                           self.LIST_FIELDS,
                           wanted_field_names,
                           lvm_fields)

  @staticmethod
  def _GetLvmFields(fields_def, wanted_field_names):
    """Returns unique list of fields wanted from LVM command.

    @type fields_def: list
    @param fields_def: Field definitions
    @type wanted_field_names: list
    @param wanted_field_names: List of requested fields

    """
    field_to_idx = dict([(field_name, idx)
                         for (idx, (field_name, _, _)) in enumerate(fields_def)])

    lvm_fields = []

    for field_name in wanted_field_names:
      try:
        idx = field_to_idx[field_name]
      except IndexError:
        raise errors.StorageError("Unknown field: %r" % field_name)

      (_, lvm_name, _) = fields_def[idx]

      lvm_fields.append(lvm_name)

    return utils.UniqueSequence(lvm_fields)

  @classmethod
  def _BuildList(cls, cmd_result, fields_def, wanted_field_names, lvm_fields):
    """Builds the final result list.

    @type cmd_result: iterable
    @param cmd_result: Iterable of LVM command output (iterable of lists)
    @type fields_def: list
    @param fields_def: Field definitions
    @type wanted_field_names: list
    @param wanted_field_names: List of requested fields
    @type lvm_fields: list
    @param lvm_fields: LVM fields

    """
    lvm_name_to_idx = dict([(lvm_name, idx)
                           for (idx, lvm_name) in enumerate(lvm_fields)])
    field_to_idx = dict([(field_name, idx)
                         for (idx, (field_name, _, _)) in enumerate(fields_def)])

    data = []
    for raw_data in cmd_result:
      row = []

      for field_name in wanted_field_names:
        (_, lvm_name, convert_fn) = fields_def[field_to_idx[field_name]]

        value = raw_data[lvm_name_to_idx[lvm_name]]

        if convert_fn:
          value = convert_fn(value)

        row.append(value)

      data.append(row)

    return data

  @staticmethod
  def _BuildListCommand(cmd, sep, options, name):
    """Builds LVM command line.

    @type cmd: string
    @param cmd: Command name
    @type sep: string
    @param sep: Field separator character
    @type options: list of strings
    @param options: Wanted LVM fields
    @type name: name or None
    @param name: Name of requested entity

    """
    args = [cmd,
            "--noheadings", "--units=m", "--nosuffix",
            "--separator", sep,
            "--options", ",".join(options)]

    if name is not None:
      args.append(name)

    return args

  @staticmethod
  def _RunListCommand(args):
    """Run LVM command.

    """
    result = utils.RunCmd(args)

    if result.failed:
      raise errors.StorageError("Failed to run %r, command output: %s" %
                                (args[0], result.output))

    return result.stdout

  @staticmethod
  def _SplitList(data, sep, fieldcount):
    """Splits LVM command output into rows and fields.

    @type data: string
    @param data: LVM command output
    @type sep: string
    @param sep: Field separator character
    @type fieldcount: int
    @param fieldcount: Expected number of fields

    """
    for line in data.splitlines():
      fields = line.strip().split(sep)

      if len(fields) != fieldcount:
        continue

      yield fields


class LvmPvStorage(_LvmBase):
  """LVM Physical Volume storage unit.

  """
  def _GetAllocatable(attr):
    if attr:
      return (attr[0] == "a")
    else:
      logging.warning("Invalid PV attribute: %r", attr)
      return False

  LIST_COMMAND = "pvs"
  LIST_FIELDS = [
    (COL_NAME, "pv_name", None),
    (COL_SIZE, "pv_size", _ParseSize),
    (COL_USED, "pv_used", _ParseSize),
    (COL_FREE, "pv_free", _ParseSize),
    (COL_ALLOCATABLE, "pv_attr", _GetAllocatable),
    ]


class LvmVgStorage(_LvmBase):
  """LVM Volume Group storage unit.

  """
  LIST_COMMAND = "vgs"
  LIST_FIELDS = [
    (COL_NAME, "vg_name", None),
    (COL_SIZE, "vg_size", _ParseSize),
    ]


# Lookup table for storage types
_STORAGE_TYPES = {
  constants.ST_FILE: FileStorage,
  constants.ST_LVM_PV: LvmPvStorage,
  constants.ST_LVM_VG: LvmVgStorage,
  }


def GetStorageClass(name):
  """Returns the class for a storage type.

  @type name: string
  @param name: Storage type

  """
  try:
    return _STORAGE_TYPES[name]
  except KeyError:
    raise errors.StorageError("Unknown storage type: %r" % name)


def GetStorage(name, *args):
  """Factory function for storage methods.

  @type name: string
  @param name: Storage type

  """
  return GetStorageClass(name)(*args)
