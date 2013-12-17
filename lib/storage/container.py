#
#

# Copyright (C) 2009, 2011, 2012 Google Inc.
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

# pylint: disable=W0232,R0201

# W0232, since we use these as singletons rather than object holding
# data

# R0201, for the same reason

# TODO: FileStorage initialised with paths whereas the others not

import logging

from ganeti import errors
from ganeti import constants
from ganeti import utils


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

  def Modify(self, name, changes): # pylint: disable=W0613
    """Modifies an entity within the storage unit.

    @type name: string
    @param name: Entity name
    @type changes: dict
    @param changes: New field values

    """
    # Don't raise an error if no changes are requested
    if changes:
      raise errors.ProgrammerError("Unable to modify the following"
                                   "fields: %r" % (changes.keys(), ))

  def Execute(self, name, op):
    """Executes an operation on an entity within the storage unit.

    @type name: string
    @param name: Entity name
    @type op: string
    @param op: Operation name

    """
    raise NotImplementedError()


class FileStorage(_Base): # pylint: disable=W0223
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
    if constants.SF_USED in fields:
      dirsize = utils.CalculateDirectorySize(path)
    else:
      dirsize = None

    if constants.SF_FREE in fields or constants.SF_SIZE in fields:
      fsstats = utils.GetFilesystemStats(path)
    else:
      fsstats = None

    # Make sure to update constants.VALID_STORAGE_FIELDS when changing fields.
    for field_name in fields:
      if field_name == constants.SF_NAME:
        values.append(path)

      elif field_name == constants.SF_USED:
        values.append(dirsize)

      elif field_name == constants.SF_FREE:
        values.append(fsstats[1])

      elif field_name == constants.SF_SIZE:
        values.append(fsstats[0])

      elif field_name == constants.SF_ALLOCATABLE:
        values.append(True)

      else:
        raise errors.StorageError("Unknown field: %r" % field_name)

    return values


class _LvmBase(_Base): # pylint: disable=W0223
  """Base class for LVM storage containers.

  @cvar LIST_FIELDS: list of tuples consisting of three elements: SF_*
      constants, lvm command output fields (list), and conversion
      function or static value (for static value, the lvm output field
      can be an empty list)

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
                         for (idx, (field_name, _, _)) in
                         enumerate(fields_def)])

    lvm_fields = []

    for field_name in wanted_field_names:
      try:
        idx = field_to_idx[field_name]
      except IndexError:
        raise errors.StorageError("Unknown field: %r" % field_name)

      (_, lvm_names, _) = fields_def[idx]

      lvm_fields.extend(lvm_names)

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
                         for (idx, (field_name, _, _)) in
                         enumerate(fields_def)])

    data = []
    for raw_data in cmd_result:
      row = []

      for field_name in wanted_field_names:
        (_, lvm_names, mapper) = fields_def[field_to_idx[field_name]]

        values = [raw_data[lvm_name_to_idx[i]] for i in lvm_names]

        if callable(mapper):
          # we got a function, call it with all the declared fields
          val = mapper(*values) # pylint: disable=W0142
        elif len(values) == 1:
          assert mapper is None, ("Invalid mapper value (neither callable"
                                  " nor None) for one-element fields")
          # we don't have a function, but we had a single field
          # declared, pass it unchanged
          val = values[0]
        else:
          # let's make sure there are no fields declared (cannot map >
          # 1 field without a function)
          assert not values, "LVM storage has multi-fields without a function"
          val = mapper

        row.append(val)

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
        logging.warning("Invalid line returned from lvm command: %s", line)
        continue

      yield fields


def _LvmPvGetAllocatable(attr):
  """Determines whether LVM PV is allocatable.

  @rtype: bool

  """
  if attr:
    return (attr[0] == "a")
  else:
    logging.warning("Invalid PV attribute: %r", attr)
    return False


class LvmPvStorage(_LvmBase): # pylint: disable=W0223
  """LVM Physical Volume storage unit.

  """
  LIST_COMMAND = "pvs"

  # Make sure to update constants.VALID_STORAGE_FIELDS when changing field
  # definitions.
  LIST_FIELDS = [
    (constants.SF_NAME, ["pv_name"], None),
    (constants.SF_SIZE, ["pv_size"], _ParseSize),
    (constants.SF_USED, ["pv_used"], _ParseSize),
    (constants.SF_FREE, ["pv_free"], _ParseSize),
    (constants.SF_ALLOCATABLE, ["pv_attr"], _LvmPvGetAllocatable),
    ]

  def _SetAllocatable(self, name, allocatable):
    """Sets the "allocatable" flag on a physical volume.

    @type name: string
    @param name: Physical volume name
    @type allocatable: bool
    @param allocatable: Whether to set the "allocatable" flag

    """
    args = ["pvchange", "--allocatable"]

    if allocatable:
      args.append("y")
    else:
      args.append("n")

    args.append(name)

    result = utils.RunCmd(args)
    if result.failed:
      raise errors.StorageError("Failed to modify physical volume,"
                                " pvchange output: %s" %
                                result.output)

  def Modify(self, name, changes):
    """Modifies flags on a physical volume.

    See L{_Base.Modify}.

    """
    if constants.SF_ALLOCATABLE in changes:
      self._SetAllocatable(name, changes[constants.SF_ALLOCATABLE])
      del changes[constants.SF_ALLOCATABLE]

    # Other changes will be handled (and maybe refused) by the base class.
    return _LvmBase.Modify(self, name, changes)


class LvmVgStorage(_LvmBase):
  """LVM Volume Group storage unit.

  """
  LIST_COMMAND = "vgs"
  VGREDUCE_COMMAND = "vgreduce"

  # Make sure to update constants.VALID_STORAGE_FIELDS when changing field
  # definitions.
  LIST_FIELDS = [
    (constants.SF_NAME, ["vg_name"], None),
    (constants.SF_SIZE, ["vg_size"], _ParseSize),
    (constants.SF_FREE, ["vg_free"], _ParseSize),
    (constants.SF_USED, ["vg_size", "vg_free"],
     lambda x, y: _ParseSize(x) - _ParseSize(y)),
    (constants.SF_ALLOCATABLE, [], True),
    ]

  def _RemoveMissing(self, name, _runcmd_fn=utils.RunCmd):
    """Runs "vgreduce --removemissing" on a volume group.

    @type name: string
    @param name: Volume group name

    """
    # Ignoring vgreduce exit code. Older versions exit with an error even tough
    # the VG is already consistent. This was fixed in later versions, but we
    # cannot depend on it.
    result = _runcmd_fn([self.VGREDUCE_COMMAND, "--removemissing", name])

    # Keep output in case something went wrong
    vgreduce_output = result.output

    # work around newer LVM version
    if ("Wrote out consistent volume group" not in vgreduce_output or
        "vgreduce --removemissing --force" in vgreduce_output):
      # we need to re-run with --force
      result = _runcmd_fn([self.VGREDUCE_COMMAND, "--removemissing",
                           "--force", name])
      vgreduce_output += "\n" + result.output

    result = _runcmd_fn([self.LIST_COMMAND, "--noheadings",
                         "--nosuffix", name])
    # we also need to check the output
    if result.failed or "Couldn't find device with uuid" in result.output:
      raise errors.StorageError(("Volume group '%s' still not consistent,"
                                 " 'vgreduce' output: %r,"
                                 " 'vgs' output: %r") %
                                (name, vgreduce_output, result.output))

  def Execute(self, name, op):
    """Executes an operation on a virtual volume.

    See L{_Base.Execute}.

    """
    if op == constants.SO_FIX_CONSISTENCY:
      return self._RemoveMissing(name)

    return _LvmBase.Execute(self, name, op)


# Lookup table for storage types
_STORAGE_TYPES = {
  constants.ST_FILE: FileStorage,
  constants.ST_LVM_PV: LvmPvStorage,
  constants.ST_LVM_VG: LvmVgStorage,
  constants.ST_SHARED_FILE: FileStorage,
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
