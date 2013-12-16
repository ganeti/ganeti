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


"""Module that defines a transport for RPC connections.

A transport can send to and receive messages from some endpoint.

"""

from ganeti.errors import LuxiError


class ProtocolError(LuxiError):
  """Denotes an error in the LUXI protocol."""


class ConnectionClosedError(ProtocolError):
  """Connection closed error."""


class TimeoutError(ProtocolError):
  """Operation timeout error."""


class RequestError(ProtocolError):
  """Error on request.

  This signifies an error in the request format or request handling,
  but not (e.g.) an error in starting up an instance.

  Some common conditions that can trigger this exception:
    - job submission failed because the job data was wrong
    - query failed because required fields were missing

  """


class NoMasterError(ProtocolError):
  """The master cannot be reached.

  This means that the master daemon is not running or the socket has
  been removed.

  """


class PermissionError(ProtocolError):
  """Permission denied while connecting to the master socket.

  This means the user doesn't have the proper rights.

  """
