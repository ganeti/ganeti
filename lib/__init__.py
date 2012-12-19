#
#

# Copyright (C) 2006, 2007, 2012 Google Inc.
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


# empty file for package definition

"""Ganeti python modules"""

try:
  from ganeti import ganeti
except ImportError:
  pass
else:
  raise Exception("A module named \"ganeti.ganeti\" was successfully imported"
                  " and should be removed as it can lead to importing the"
                  " wrong module(s) in other parts of the code, consequently"
                  " leading to failures which are difficult to debug")
