#
#

# Copyright (C) 2014 Google Inc.
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

"""Lockfiles to prove liveliness

When requesting resources, like locks, from wconfd, requesters have
to provide the name of a file they own an exclusive lock on, to prove
that they are still alive. Provide methods to obtain such a file.
"""

import fcntl
import os
import struct
import time

from ganeti.utils.algo import NiceSort
from ganeti import pathutils


class LiveLockName(object):
  def __init__(self, name):
    self._name = name

  def GetPath(self):
    return self._name

  def close(self):
    """Clean up the lockfile.

    """
    os.remove(self._name)


class LiveLock(object):
  """Utility for a lockfile needed to request resources from WconfD.

  """
  def __init__(self, name=None):
    if name is None:
      name = "pid%d_" % os.getpid()
    # to avoid reusing existing lock files, extend name
    # by the current time
    name = "%s_%d" % (name, int(time.time()))
    fname = os.path.join(pathutils.LIVELOCK_DIR, name)
    self.lockfile = open(fname, 'w')
    fcntl.fcntl(self.lockfile, fcntl.F_SETLKW,
                struct.pack('hhllhh', fcntl.F_WRLCK, 0, 0, 0, 0, 0))

  def GetPath(self):
    return self.lockfile.name

  def close(self):
    """Close the lockfile and clean it up.

    """
    self.lockfile.close()
    os.remove(self.lockfile.name)


def GuessLockfileFor(name):
  """For a given name, take the latest file matching.

  @return: the file with the latest name matching the given
      prefix in LIVELOCK_DIR, or the plain name, if none
      exists.
  """
  lockfiles = filter(lambda n: n.startswith(name),
                     os.listdir(pathutils.LIVELOCK_DIR))
  if len(lockfiles) > 0:
    lockfile = NiceSort(lockfiles)[-1]
  else:
    lockfile = name

  return os.path.join(pathutils.LIVELOCK_DIR, lockfile)
