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

"""Module used during the Ganeti build process"""

import imp
import os


def LoadModule(filename):
  """Loads an external module by filename.

  Use this function with caution. Python will always write the compiled source
  to a file named "${filename}c".

  @type filename: string
  @param filename: Path to module

  """
  (name, ext) = os.path.splitext(filename)

  fh = open(filename, "U")
  try:
    return imp.load_module(name, fh, filename, (ext, "U", imp.PY_SOURCE))
  finally:
    fh.close()
