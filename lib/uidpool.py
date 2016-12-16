#
#

# Copyright (C) 2010, 2012 Google Inc.
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


"""User-id pool related functions.

The user-id pool is cluster-wide configuration option.
It is stored as a list of user-id ranges.
This module contains functions used for manipulating the
user-id pool parameter and for requesting/returning user-ids
from the pool.

"""

import errno
import logging
import os
import random

from ganeti import errors
from ganeti import constants
from ganeti import utils
from ganeti import pathutils


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
          % boundaries, errors.ECODE_INVAL)
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
          " user-id pool: %s" % str(uid_range), errors.ECODE_INVAL)
    uid_pool.remove(uid_range)


def _FormatUidRange(lower, higher):
  """Convert a user-id range definition into a string.

  """
  if lower == higher:
    return str(lower)

  return "%s-%s" % (lower, higher)


def FormatUidPool(uid_pool, separator=None):
  """Convert the internal representation of the user-id pool into a string.

  The output format is also accepted by ParseUidPool()

  @param uid_pool: a list of integer pairs representing UID ranges
  @param separator: the separator character between the uids/uid-ranges.
                    Defaults to ", ".
  @return: a string with the formatted results

  """
  if separator is None:
    separator = ", "
  return separator.join([_FormatUidRange(lower, higher)
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


def _IsUidUsed(uid):
  """Check if there is any process in the system running with the given user-id

  @type uid: integer
  @param uid: the user-id to be checked.

  """
  pgrep_command = [constants.PGREP, "-u", uid]
  result = utils.RunCmd(pgrep_command)

  if result.exit_code == 0:
    return True
  elif result.exit_code == 1:
    return False
  else:
    raise errors.CommandError("Running pgrep failed. exit code: %s"
                              % result.exit_code)


class LockedUid(object):
  """Class representing a locked user-id in the uid-pool.

  This binds together a userid and a lock.

  """
  def __init__(self, uid, lock):
    """Constructor

    @param uid: a user-id
    @param lock: a utils.FileLock object

    """
    self._uid = uid
    self._lock = lock

  def Unlock(self):
    # Release the exclusive lock and close the filedescriptor
    self._lock.Close()

  def GetUid(self):
    return self._uid

  def AsStr(self):
    return "%s" % self._uid


def RequestUnusedUid(all_uids):
  """Tries to find an unused uid from the uid-pool, locks it and returns it.

  Usage pattern
  =============

  1. When starting a process::

      from ganeti import ssconf
      from ganeti import uidpool

      # Get list of all user-ids in the uid-pool from ssconf
      ss = ssconf.SimpleStore()
      uid_pool = uidpool.ParseUidPool(ss.GetUidPool(), separator="\\n")
      all_uids = set(uidpool.ExpandUidPool(uid_pool))

      uid = uidpool.RequestUnusedUid(all_uids)
      try:
        <start a process with the UID>
        # Once the process is started, we can release the file lock
        uid.Unlock()
      except ..., err:
        # Return the UID to the pool
        uidpool.ReleaseUid(uid)

  2. Stopping a process::

      from ganeti import uidpool

      uid = <get the UID the process is running under>
      <stop the process>
      uidpool.ReleaseUid(uid)

  @type all_uids: set of integers
  @param all_uids: a set containing all the user-ids in the user-id pool
  @return: a LockedUid object representing the unused uid. It's the caller's
           responsibility to unlock the uid once an instance is started with
           this uid.

  """
  # Create the lock dir if it's not yet present
  try:
    utils.EnsureDirs([(pathutils.UIDPOOL_LOCKDIR, 0755)])
  except errors.GenericError, err:
    raise errors.LockError("Failed to create user-id pool lock dir: %s" % err)

  # Get list of currently used uids from the filesystem
  try:
    taken_uids = set()
    for taken_uid in os.listdir(pathutils.UIDPOOL_LOCKDIR):
      try:
        taken_uid = int(taken_uid)
      except ValueError, err:
        # Skip directory entries that can't be converted into an integer
        continue
      taken_uids.add(taken_uid)
  except OSError, err:
    raise errors.LockError("Failed to get list of used user-ids: %s" % err)

  # Filter out spurious entries from the directory listing
  taken_uids = all_uids.intersection(taken_uids)

  # Remove the list of used uids from the list of all uids
  unused_uids = list(all_uids - taken_uids)
  if not unused_uids:
    logging.info("All user-ids in the uid-pool are marked 'taken'")

  # Randomize the order of the unused user-id list
  random.shuffle(unused_uids)

  # Randomize the order of the unused user-id list
  taken_uids = list(taken_uids)
  random.shuffle(taken_uids)

  for uid in unused_uids + taken_uids:
    try:
      # Create the lock file
      # Note: we don't care if it exists. Only the fact that we can
      # (or can't) lock it later is what matters.
      uid_path = utils.PathJoin(pathutils.UIDPOOL_LOCKDIR, str(uid))
      lock = utils.FileLock.Open(uid_path)
    except OSError, err:
      raise errors.LockError("Failed to create lockfile for user-id %s: %s"
                             % (uid, err))
    try:
      # Try acquiring an exclusive lock on the lock file
      lock.Exclusive()
      # Check if there is any process running with this user-id
      if _IsUidUsed(uid):
        logging.debug("There is already a process running under"
                      " user-id %s", uid)
        lock.Unlock()
        continue
      return LockedUid(uid, lock)
    except IOError, err:
      if err.errno == errno.EAGAIN:
        # The file is already locked, let's skip it and try another unused uid
        logging.debug("Lockfile for user-id is already locked %s: %s", uid, err)
        continue
    except errors.LockError, err:
      # There was an unexpected error while trying to lock the file
      logging.error("Failed to lock the lockfile for user-id %s: %s", uid, err)
      raise

  raise errors.LockError("Failed to find an unused user-id")


def ReleaseUid(uid):
  """This should be called when the given user-id is no longer in use.

  @type uid: LockedUid or integer
  @param uid: the uid to release back to the pool

  """
  if isinstance(uid, LockedUid):
    # Make sure we release the exclusive lock, if there is any
    uid.Unlock()
    uid_filename = uid.AsStr()
  else:
    uid_filename = str(uid)

  try:
    uid_path = utils.PathJoin(pathutils.UIDPOOL_LOCKDIR, uid_filename)
    os.remove(uid_path)
  except OSError, err:
    raise errors.LockError("Failed to remove user-id lockfile"
                           " for user-id %s: %s" % (uid_filename, err))


def ExecWithUnusedUid(fn, all_uids, *args, **kwargs):
  """Execute a callable and provide an unused user-id in its kwargs.

  This wrapper function provides a simple way to handle the requesting,
  unlocking and releasing a user-id.
  "fn" is called by passing a "uid" keyword argument that
  contains an unused user-id (as an integer) selected from the set of user-ids
  passed in all_uids.
  If there is an error while executing "fn", the user-id is returned
  to the pool.

  @param fn: a callable that accepts a keyword argument called "uid"
  @type all_uids: a set of integers
  @param all_uids: a set containing all user-ids in the user-id pool

  """
  uid = RequestUnusedUid(all_uids)
  kwargs["uid"] = uid.GetUid()
  try:
    return_value = fn(*args, **kwargs)
  except:
    # The failure of "callabe" means that starting a process with the uid
    # failed, so let's put the uid back into the pool.
    ReleaseUid(uid)
    raise
  uid.Unlock()
  return return_value
