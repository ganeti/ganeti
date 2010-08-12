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

"""Module implementing configuration details at runtime.

"""


import grp
import pwd
import threading

from ganeti import constants
from ganeti import errors


_priv = None
_priv_lock = threading.Lock()


def GetUid(user, _getpwnam):
  """Retrieve the uid from the database.

  @type user: string
  @param user: The username to retrieve
  @return: The resolved uid

  """
  try:
    return _getpwnam(user).pw_uid
  except KeyError, err:
    raise errors.ConfigurationError("User '%s' not found (%s)" % (user, err))


def GetGid(group, _getgrnam):
  """Retrieve the gid from the database.

  @type group: string
  @param group: The group name to retrieve
  @return: The resolved gid

  """
  try:
    return _getgrnam(group).gr_gid
  except KeyError, err:
    raise errors.ConfigurationError("Group '%s' not found (%s)" % (group, err))


class GetentResolver:
  """Resolves Ganeti uids and gids by name.

  @ivar masterd_uid: The resolved uid of the masterd user
  @ivar masterd_gid: The resolved gid of the masterd group
  @ivar confd_uid: The resolved uid of the confd user
  @ivar confd_gid: The resolved gid of the confd group
  @ivar rapi_uid: The resolved uid of the rapi user
  @ivar rapi_gid: The resolved gid of the rapi group
  @ivar noded_uid: The resolved uid of the noded user

  @ivar daemons_gid: The resolved gid of the daemons group
  @ivar admin_gid: The resolved gid of the admin group
  """
  def __init__(self, _getpwnam=pwd.getpwnam, _getgrnam=grp.getgrnam):
    """Initialize the resolver.

    """
    # Daemon pairs
    self.masterd_uid = GetUid(constants.MASTERD_USER, _getpwnam)
    self.masterd_gid = GetGid(constants.MASTERD_GROUP, _getgrnam)

    self.confd_uid = GetUid(constants.CONFD_USER, _getpwnam)
    self.confd_gid = GetGid(constants.CONFD_GROUP, _getgrnam)

    self.rapi_uid = GetUid(constants.RAPI_USER, _getpwnam)
    self.rapi_gid = GetGid(constants.RAPI_GROUP, _getgrnam)

    self.noded_uid = GetUid(constants.NODED_USER, _getpwnam)

    # Misc Ganeti groups
    self.daemons_gid = GetGid(constants.DAEMONS_GROUP, _getgrnam)
    self.admin_gid = GetGid(constants.ADMIN_GROUP, _getgrnam)


def GetEnts(resolver=GetentResolver):
  """Singleton wrapper around resolver instance.

  As this method is accessed by multiple threads at the same time
  we need to take thread-safty carefully

  """
  # We need to use the global keyword here
  global _priv # pylint: disable-msg=W0603

  if not _priv:
    _priv_lock.acquire()
    try:
      if not _priv:
        # W0621: Redefine '_priv' from outer scope (used for singleton)
        _priv = resolver() # pylint: disable-msg=W0621
    finally:
      _priv_lock.release()

  return _priv

