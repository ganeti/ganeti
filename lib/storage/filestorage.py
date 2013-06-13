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


"""File storage functions.

"""

import os

from ganeti import constants
from ganeti import errors


def GetFileStorageSpaceInfo(path):
  """Retrieves the free and total space of the device where the file is
     located.

     @type path: string
     @param path: Path of the file whose embracing device's capacity is
       reported.
     @return: a dictionary containing 'vg_size' and 'vg_free' given in MebiBytes

  """
  try:
    result = os.statvfs(path)
    free = (result.f_frsize * result.f_bavail) / (1024 * 1024)
    size = (result.f_frsize * result.f_blocks) / (1024 * 1024)
    return {"type": constants.ST_FILE,
            "name": path,
            "storage_size": size,
            "storage_free": free}
  except OSError, e:
    raise errors.CommandError("Failed to retrieve file system information about"
                              " path: %s - %s" % (path, e.strerror))
