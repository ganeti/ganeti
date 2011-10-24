#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011 Google Inc.
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

"""RPC definitions for communication between master and node daemons.

"""


# Various time constants for the timeout table
TMO_URGENT = 60 # one minute
TMO_FAST = 5 * 60 # five minutes
TMO_NORMAL = 15 * 60 # 15 minutes
TMO_SLOW = 3600 # one hour
TMO_4HRS = 4 * 3600
TMO_1DAY = 86400

SINGLE = "single-node"
MULTI = "multi-node"

OBJECT_TO_DICT = "%s.ToDict()"
OBJECT_LIST_TO_DICT = "map(lambda d: d.ToDict(), %s)"
INST_TO_DICT = "self._InstDict(%s)"

NODE_TO_DISK_DICT = \
  ("dict((name, %s) for name, disks in %%s.items())" %
   (OBJECT_LIST_TO_DICT % "disks"))

CALLS = {
  "RpcClientDefault": [
    ],
  }
