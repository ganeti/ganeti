#
#

# Copyright (C) 2014 Google Inc.
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

  def __str__(self):
    return "LiveLockName(" + self.GetPath() + ")"


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

  def __str__(self):
    return "LiveLock(" + self.GetPath() + ")"


def GuessLockfileFor(name):
  """For a given name, take the latest file matching.

  @return: the file with the latest name matching the given
      prefix in LIVELOCK_DIR, or the plain name, if none
      exists.
  """
  lockfiles = [n for n in os.listdir(pathutils.LIVELOCK_DIR)
               if n.startswith(name)]
  if len(lockfiles) > 0:
    lockfile = NiceSort(lockfiles)[-1]
  else:
    lockfile = name

  return os.path.join(pathutils.LIVELOCK_DIR, lockfile)
