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


"""Ganeti confd client/server library

"""

from ganeti import constants
from ganeti import errors


_FOURCC_LEN = 4


def PackMagic(payload):
  """Prepend the confd magic fourcc to a payload.

  """
  return ''.join([constants.CONFD_MAGIC_FOURCC, payload])


def UnpackMagic(payload):
  """Unpack and check the confd magic fourcc from a payload.

  """
  if len(payload) < _FOURCC_LEN:
    raise errors.ConfdMagicError("UDP payload too short to contain the"
                                 " fourcc code")

  magic_number = payload[:_FOURCC_LEN]
  if magic_number != constants.CONFD_MAGIC_FOURCC:
    raise errors.ConfdMagicError("UDP payload contains an unkown fourcc")

  return payload[_FOURCC_LEN:]
