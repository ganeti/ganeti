#
#

# Copyright (C) 2013 Google Inc.
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


"""Module for generic RPC clients.

"""

import logging

from ganeti import pathutils
import ganeti.rpc.transport as t

from ganeti import constants
from ganeti import errors
from ganeti.rpc.errors import (ProtocolError, RequestError, LuxiError)
from ganeti import serializer

KEY_METHOD = constants.LUXI_KEY_METHOD
KEY_ARGS = constants.LUXI_KEY_ARGS
KEY_SUCCESS = constants.LUXI_KEY_SUCCESS
KEY_RESULT = constants.LUXI_KEY_RESULT
KEY_VERSION = constants.LUXI_KEY_VERSION


def ParseRequest(msg):
  """Parses a request message.

  """
  try:
    request = serializer.LoadJson(msg)
  except ValueError, err:
    raise ProtocolError("Invalid RPC request (parsing error): %s" % err)

  logging.debug("RPC request: %s", request)

  if not isinstance(request, dict):
    logging.error("RPC request not a dict: %r", msg)
    raise ProtocolError("Invalid RPC request (not a dict)")

  method = request.get(KEY_METHOD, None) # pylint: disable=E1103
  args = request.get(KEY_ARGS, None) # pylint: disable=E1103
  version = request.get(KEY_VERSION, None) # pylint: disable=E1103

  if method is None or args is None:
    logging.error("RPC request missing method or arguments: %r", msg)
    raise ProtocolError(("Invalid RPC request (no method or arguments"
                         " in request): %r") % msg)

  return (method, args, version)


def ParseResponse(msg):
  """Parses a response message.

  """
  # Parse the result
  try:
    data = serializer.LoadJson(msg)
  except KeyboardInterrupt:
    raise
  except Exception, err:
    raise ProtocolError("Error while deserializing response: %s" % str(err))

  # Validate response
  if not (isinstance(data, dict) and
          KEY_SUCCESS in data and
          KEY_RESULT in data):
    raise ProtocolError("Invalid response from server: %r" % data)

  return (data[KEY_SUCCESS], data[KEY_RESULT],
          data.get(KEY_VERSION, None)) # pylint: disable=E1103


def FormatResponse(success, result, version=None):
  """Formats a response message.

  """
  response = {
    KEY_SUCCESS: success,
    KEY_RESULT: result,
    }

  if version is not None:
    response[KEY_VERSION] = version

  logging.debug("RPC response: %s", response)

  return serializer.DumpJson(response)


def FormatRequest(method, args, version=None):
  """Formats a request message.

  """
  # Build request
  request = {
    KEY_METHOD: method,
    KEY_ARGS: args,
    }

  if version is not None:
    request[KEY_VERSION] = version

  # Serialize the request
  return serializer.DumpJson(request)


def CallRPCMethod(transport_cb, method, args, version=None):
  """Send a RPC request via a transport and return the response.

  """
  assert callable(transport_cb)

  request_msg = FormatRequest(method, args, version=version)

  # Send request and wait for response
  response_msg = transport_cb(request_msg)

  (success, result, resp_version) = ParseResponse(response_msg)

  # Verify version if there was one in the response
  if resp_version is not None and resp_version != version:
    raise LuxiError("RPC version mismatch, client %s, response %s" %
                    (version, resp_version))

  if success:
    return result

  errors.MaybeRaise(result)
  raise RequestError(result)


class AbstractClient(object):
  """High-level client abstraction.

  This uses a backing Transport-like class on top of which it
  implements data serialization/deserialization.

  """

  def __init__(self, address=None, timeouts=None,
               transport=t.Transport):
    """Constructor for the Client class.

    Arguments:
      - address: a valid address the the used transport class
      - timeout: a list of timeouts, to be used on connect and read/write
      - transport: a Transport-like class


    If timeout is not passed, the default timeouts of the transport
    class are used.

    """
    if address is None:
      address = pathutils.MASTER_SOCKET
    self.address = address
    self.timeouts = timeouts
    self.transport_class = transport
    self.transport = None
    self._InitTransport()
    # The version used in RPC communication, by default unused:
    self.version = None

  def _InitTransport(self):
    """(Re)initialize the transport if needed.

    """
    if self.transport is None:
      self.transport = self.transport_class(self.address,
                                            timeouts=self.timeouts)

  def _CloseTransport(self):
    """Close the transport, ignoring errors.

    """
    if self.transport is None:
      return
    try:
      old_transp = self.transport
      self.transport = None
      old_transp.Close()
    except Exception: # pylint: disable=W0703
      pass

  def _SendMethodCall(self, data):
    # Send request and wait for response
    try:
      self._InitTransport()
      return self.transport.Call(data)
    except Exception:
      self._CloseTransport()
      raise

  def Close(self):
    """Close the underlying connection.

    """
    self._CloseTransport()

  def close(self):
    """Same as L{Close}, to be used with contextlib.closing(...).

    """
    self.Close()

  def CallMethod(self, method, args):
    """Send a generic request and return the response.

    """
    if not isinstance(args, (list, tuple)):
      raise errors.ProgrammerError("Invalid parameter passed to CallMethod:"
                                   " expected list, got %s" % type(args))
    return CallRPCMethod(self._SendMethodCall, method, args,
                         version=self.version)
