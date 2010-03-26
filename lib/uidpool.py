#
#

# Copyright (C) 2010 Google Inc.
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


"""User-id pool related functions.

The user-id pool is cluster-wide configuration option.
It is stored as a list of user-id ranges.
This module contains functions used for manipulating the
user-id pool parameter and for requesting/returning user-ids
from the pool.

"""

from ganeti import errors
from ganeti import constants
from ganeti import utils


def ParseUidPool(value, separator=None):
  """Parse a user-id pool definition.

  @param value: string representation of the user-id pool.
                The accepted input format is a list of integer ranges.
                The boundaries are inclusive.
                Example: '1000-5000,8000,9000-9010'.
  @param separator: the separator character between the uids/uid-ranges.
                    Defaults to a comma.
  @return: a list of integer pairs (lower, higher range boundaries)

  """
  if separator is None:
    separator = ","

  ranges = []
  for range_def in value.split(separator):
    if not range_def:
      # Skip empty strings
      continue
    boundaries = range_def.split("-")
    n_elements = len(boundaries)
    if n_elements > 2:
      raise errors.OpPrereqError(
          "Invalid user-id range definition. Only one hyphen allowed: %s"
          % boundaries)
    try:
      lower = int(boundaries[0])
    except (ValueError, TypeError), err:
      raise errors.OpPrereqError("Invalid user-id value for lower boundary of"
                                 " user-id range: %s"
                                 % str(err), errors.ECODE_INVAL)
    try:
      higher = int(boundaries[n_elements - 1])
    except (ValueError, TypeError), err:
      raise errors.OpPrereqError("Invalid user-id value for higher boundary of"
                                 " user-id range: %s"
                                 % str(err), errors.ECODE_INVAL)

    ranges.append((lower, higher))

  ranges.sort()
  return ranges


def AddToUidPool(uid_pool, add_uids):
  """Add a list of user-ids/user-id ranges to a user-id pool.

  @param uid_pool: a user-id pool (list of integer tuples)
  @param add_uids: user-id ranges to be added to the pool
                   (list of integer tuples)

  """
  for uid_range in add_uids:
    if uid_range not in uid_pool:
      uid_pool.append(uid_range)
  uid_pool.sort()


def RemoveFromUidPool(uid_pool, remove_uids):
  """Remove a list of user-ids/user-id ranges from a user-id pool.

  @param uid_pool: a user-id pool (list of integer tuples)
  @param remove_uids: user-id ranges to be removed from the pool
                      (list of integer tuples)

  """
  for uid_range in remove_uids:
    if uid_range not in uid_pool:
      raise errors.OpPrereqError(
          "User-id range to be removed is not found in the current"
          " user-id pool: %s" % uid_range, errors.ECODE_INVAL)
    uid_pool.remove(uid_range)


def _FormatUidRange(lower, higher):
  """Convert a user-id range definition into a string.

  """
  if lower == higher:
    return str(lower)
  return "%s-%s" % (lower, higher)


def FormatUidPool(uid_pool):
  """Convert the internal representation of the user-id pool into a string.

  The output format is also accepted by ParseUidPool()

  @param uid_pool: a list of integer pairs representing UID ranges
  @return: a string with the formatted results

  """
  return utils.CommaJoin([_FormatUidRange(lower, higher)
                          for lower, higher in uid_pool])


def CheckUidPool(uid_pool):
  """Sanity check user-id pool range definition values.

  @param uid_pool: a list of integer pairs (lower, higher range boundaries)

  """
  for lower, higher in uid_pool:
    if lower > higher:
      raise errors.OpPrereqError(
          "Lower user-id range boundary value (%s)"
          " is larger than higher boundary value (%s)" %
          (lower, higher), errors.ECODE_INVAL)
    if lower < constants.UIDPOOL_UID_MIN:
      raise errors.OpPrereqError(
          "Lower user-id range boundary value (%s)"
          " is smaller than UIDPOOL_UID_MIN (%s)." %
          (lower, constants.UIDPOOL_UID_MIN),
          errors.ECODE_INVAL)
    if higher > constants.UIDPOOL_UID_MAX:
      raise errors.OpPrereqError(
          "Higher user-id boundary value (%s)"
          " is larger than UIDPOOL_UID_MAX (%s)." %
          (higher, constants.UIDPOOL_UID_MAX),
          errors.ECODE_INVAL)


def ExpandUidPool(uid_pool):
  """Expands a uid-pool definition to a list of uids.

  @param uid_pool: a list of integer pairs (lower, higher range boundaries)
  @return: a list of integers

  """
  uids = set()
  for lower, higher in uid_pool:
    uids.update(range(lower, higher + 1))
  return list(uids)
