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


"""Support for mocking the live locks"""

import os


class Mockfile(object):
  """Mock an opaque file.

  Only the name field is provided.

  """
  def __init__(self, fname):
    self.name = fname


class LiveLockMock(object):
  """Lock version of a live lock.

  Does not actually touch the file system.

  """
  def __init__(self, name=None):
    if name is None:
      name = "pid4711"
    name = "%s_123456" % name
    fname = os.path.join("/tmp/mock", name)
    self.lockfile = Mockfile(fname)
