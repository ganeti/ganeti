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
