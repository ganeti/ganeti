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
import time

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
  return serializer.DumpJson(request,
                             private_encoder=serializer.EncodeWithPrivateFields)


def CallRPCMethod(transport_cb, method, args, version=None):
  """Send a RPC request via a transport and return the response.

  """
  assert callable(transport_cb)
  t1 = time.time() * 1000
  request_msg = FormatRequest(method, args, version=version)
  t2 = time.time() * 1000
  # Send request and wait for response
  response_msg = transport_cb(request_msg)
  t3 = time.time() * 1000
  (success, result, resp_version) = ParseResponse(response_msg)
  t4 = time.time() * 1000
  logging.debug("CallRPCMethod %s: format: %dms, sock: %dms, parse: %dms",
                method, int(t2 - t1), int(t3 - t2), int(t4 - t3))
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

  def __init__(self, timeouts=None, transport=t.Transport,
               allow_non_master=False):
    """Constructor for the Client class.

    If timeout is not passed, the default timeouts of the transport
    class are used.

    @type timeouts: list of ints
    @param timeouts: timeouts to be used on connect and read/write
    @type transport: L{Transport} or another compatible class
    @param transport: the underlying transport to use for the RPC calls
    @type allow_non_master: bool
    @param allow_non_master: skip checks for the master node on errors

    """
    self.timeouts = timeouts
    self.transport_class = transport
    self.allow_non_master = allow_non_master
    self.transport = None
    # The version used in RPC communication, by default unused:
    self.version = None

  def _GetAddress(self):
    """Returns the socket address

    """
    raise NotImplementedError

  def _InitTransport(self):
    """(Re)initialize the transport if needed.

    """
    if self.transport is None:
      self.transport = \
        self.transport_class(self._GetAddress(),
                             timeouts=self.timeouts,
                             allow_non_master=self.allow_non_master)

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
    def send(try_no):
      if try_no:
        logging.debug("RPC peer disconnected, retrying")
      self._InitTransport()
      return self.transport.Call(data)
    return t.Transport.RetryOnNetworkError(send,
                                           lambda _: self._CloseTransport())

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


class AbstractStubClient(AbstractClient):
  """An abstract Client that connects a generated stub client to a L{Transport}.

  Subclasses should inherit from this class (first) as well and a designated
  stub (second).
  """

  def __init__(self, timeouts=None, transport=t.Transport,
               allow_non_master=None):
    """Constructor for the class.

    Arguments are the same as for L{AbstractClient}. Checks that SOCKET_PATH
    attribute is defined (in the stub class).

    @type timeouts: list of ints
    @param timeouts: timeouts to be used on connect and read/write
    @type transport: L{Transport} or another compatible class
    @param transport: the underlying transport to use for the RPC calls
    @type allow_non_master: bool
    @param allow_non_master: skip checks for the master node on errors
    """

    super(AbstractStubClient, self).__init__(timeouts=timeouts,
                                             transport=transport,
                                             allow_non_master=allow_non_master)

  def _GenericInvoke(self, method, *args):
    return self.CallMethod(method, args)

  def _GetAddress(self):
    return self._GetSocketPath() # pylint: disable=E1101
