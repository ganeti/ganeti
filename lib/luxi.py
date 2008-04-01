#
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Module for the unix socket protocol

This module implements the local unix socket protocl. You only need
this module and the opcodes module in the client program in order to
communicate with the master.

The module is also be used by the master daemon.

"""

import socket
import collections
import simplejson
import time

from ganeti import opcodes
from ganeti import constants


KEY_REQUEST = 'request'
KEY_DATA = 'data'
REQ_SUBMIT = 'submit'
REQ_ABORT = 'abort'
REQ_QUERY = 'query'

DEF_CTMO = 10
DEF_RWTO = 60


class ProtocolError(Exception):
  """Denotes an error in the server communication"""


class ConnectionClosedError(ProtocolError):
  """Connection closed error"""


class TimeoutError(ProtocolError):
  """Operation timeout error"""


class EncodingError(ProtocolError):
  """Encoding failure on the sending side"""


class DecodingError(ProtocolError):
  """Decoding failure on the receiving side"""


def SerializeJob(job):
  """Convert a job description to a string format.

  """
  return simplejson.dumps(job.__getstate__())


def UnserializeJob(data):
  """Load a job from a string format"""
  try:
    new_data = simplejson.loads(data)
  except Exception, err:
    raise DecodingError("Error while unserializing: %s" % str(err))
  job = opcodes.Job()
  job.__setstate__(new_data)
  return job


class Transport:
  """Low-level transport class.

  This is used on the client side.

  This could be replace by any other class that provides the same
  semantics to the Client. This means:
    - can send messages and receive messages
    - safe for multithreading

  """

  def __init__(self, address, timeouts=None, eom=None):
    """Constructor for the Client class.

    Arguments:
      - address: a valid address the the used transport class
      - timeout: a list of timeouts, to be used on connect and read/write
      - eom: an identifier to be used as end-of-message which the
        upper-layer will guarantee that this identifier will not appear
        in any message

    There are two timeouts used since we might want to wait for a long
    time for a response, but the connect timeout should be lower.

    If not passed, we use a default of 10 and respectively 60 seconds.

    Note that on reading data, since the timeout applies to an
    invidual receive, it might be that the total duration is longer
    than timeout value passed (we make a hard limit at twice the read
    timeout).

    """
    self.address = address
    if timeouts is None:
      self._ctimeout, self._rwtimeout = DEF_CTMO, DEF_RWTO
    else:
      self._ctimeout, self._rwtimeout = timeouts

    self.socket = None
    self._buffer = ""
    self._msgs = collections.deque()

    if eom is None:
      self.eom = '\3'
    else:
      self.eom = eom

    try:
      self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      self.socket.settimeout(self._ctimeout)
      try:
        self.socket.connect(address)
      except socket.timeout, err:
        raise TimeoutError("Connection timed out: %s" % str(err))
      self.socket.settimeout(self._rwtimeout)
    except socket.error:
      if self.socket is not None:
        self.socket.close()
      self.socket = None
      raise

  def _CheckSocket(self):
    """Make sure we are connected.

    """
    if self.socket is None:
      raise ProtocolError("Connection is closed")

  def Send(self, msg):
    """Send a message.

    This just sends a message and doesn't wait for the response.

    """
    if self.eom in msg:
      raise EncodingError("Message terminator found in payload")
    self._CheckSocket()
    try:
      self.socket.sendall(msg + self.eom)
    except socket.timeout, err:
      raise TimeoutError("Sending timeout: %s" % str(err))

  def Recv(self):
    """Try to receive a messae from the socket.

    In case we already have messages queued, we just return from the
    queue. Otherwise, we try to read data with a _rwtimeout network
    timeout, and making sure we don't go over 2x_rwtimeout as a global
    limit.

    """
    self._CheckSocket()
    etime = time.time() + self._rwtimeout
    while not self._msgs:
      if time.time() > etime:
        raise TimeoutError("Extended receive timeout")
      try:
        data = self.socket.recv(4096)
      except socket.timeout, err:
        raise TimeoutError("Receive timeout: %s" % str(err))
      if not data:
        raise ConnectionClosedError("Connection closed while reading")
      new_msgs = (self._buffer + data).split(self.eom)
      self._buffer = new_msgs.pop()
      self._msgs.extend(new_msgs)
    return self._msgs.popleft()

  def Call(self, msg):
    """Send a message and wait for the response.

    This is just a wrapper over Send and Recv.

    """
    self.Send(msg)
    return self.Recv()

  def Close(self):
    """Close the socket"""
    if self.socket is not None:
      self.socket.close()
      self.socket = None


class Client(object):
  """High-level client implementation.

  This uses a backing Transport-like class on top of which it
  implements data serialization/deserialization.

  """
  def __init__(self, address=None, timeouts=None, transport=Transport):
    """Constructor for the Client class.

    Arguments:
      - address: a valid address the the used transport class
      - timeout: a list of timeouts, to be used on connect and read/write
      - transport: a Transport-like class


    If timeout is not passed, the default timeouts of the transport
    class are used.

    """
    if address is None:
      address = constants.MASTER_SOCKET
    self.transport = transport(address, timeouts=timeouts)

  def SendRequest(self, request, data):
    """Send a generic request and return the response.

    """
    msg = {KEY_REQUEST: request, KEY_DATA: data}
    result = self.transport.Call(simplejson.dumps(msg))
    try:
      data = simplejson.loads(result)
    except Exception, err:
      raise ProtocolError("Error while deserializing response: %s" % str(err))
    return data

  def SubmitJob(self, job):
    """Submit a job"""
    return self.SendRequest(REQ_SUBMIT, SerializeJob(job))

  def Query(self, data):
    """Make a query"""
    return self.SendRequest(REQ_QUERY, data)
