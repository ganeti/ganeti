#
#

# Copyright (C) 2013, 2014 Google Inc.
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

import collections
import errno
import io
import socket
import time

from ganeti import constants
from ganeti import utils
from ganeti.rpc import errors


DEF_CTMO = constants.LUXI_DEF_CTMO
DEF_RWTO = constants.LUXI_DEF_RWTO


class Transport:
  """Low-level transport class.

  This is used on the client side.

  This could be replaced by any other class that provides the same
  semantics to the Client. This means:
    - can send messages and receive messages
    - safe for multithreading

  """

  def __init__(self, address, timeouts=None):
    """Constructor for the Client class.

    Arguments:
      - address: a valid address the the used transport class
      - timeout: a list of timeouts, to be used on connect and read/write

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

    try:
      self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

      # Try to connect
      try:
        utils.Retry(self._Connect, 1.0, self._ctimeout,
                    args=(self.socket, address, self._ctimeout))
      except utils.RetryTimeout:
        raise errors.TimeoutError("Connect timed out")

      self.socket.settimeout(self._rwtimeout)
    except (socket.error, errors.NoMasterError):
      if self.socket is not None:
        self.socket.close()
      self.socket = None
      raise

  @staticmethod
  def _Connect(sock, address, timeout):
    sock.settimeout(timeout)
    try:
      sock.connect(address)
    except socket.timeout, err:
      raise errors.TimeoutError("Connect timed out: %s" % str(err))
    except socket.error, err:
      error_code = err.args[0]
      if error_code in (errno.ENOENT, errno.ECONNREFUSED):
        raise errors.NoMasterError(address)
      elif error_code in (errno.EPERM, errno.EACCES):
        raise errors.PermissionError(address)
      elif error_code == errno.EAGAIN:
        # Server's socket backlog is full at the moment
        raise utils.RetryAgain()
      raise

  def _CheckSocket(self):
    """Make sure we are connected.

    """
    if self.socket is None:
      raise errors.ProtocolError("Connection is closed")

  def Send(self, msg):
    """Send a message.

    This just sends a message and doesn't wait for the response.

    """
    if constants.LUXI_EOM in msg:
      raise errors.ProtocolError("Message terminator found in payload")

    self._CheckSocket()
    try:
      # TODO: sendall is not guaranteed to send everything
      self.socket.sendall(msg + constants.LUXI_EOM)
    except socket.timeout, err:
      raise errors.TimeoutError("Sending timeout: %s" % str(err))

  def Recv(self):
    """Try to receive a message from the socket.

    In case we already have messages queued, we just return from the
    queue. Otherwise, we try to read data with a _rwtimeout network
    timeout, and making sure we don't go over 2x_rwtimeout as a global
    limit.

    """
    self._CheckSocket()
    etime = time.time() + self._rwtimeout
    while not self._msgs:
      if time.time() > etime:
        raise errors.TimeoutError("Extended receive timeout")
      while True:
        try:
          data = self.socket.recv(4096)
        except socket.timeout, err:
          raise errors.TimeoutError("Receive timeout: %s" % str(err))
        except socket.error, err:
          if err.args and err.args[0] == errno.EAGAIN:
            continue
          raise
        break
      if not data:
        raise errors.ConnectionClosedError("Connection closed while reading")
      new_msgs = (self._buffer + data).split(constants.LUXI_EOM)
      self._buffer = new_msgs.pop()
      self._msgs.extend(new_msgs)
    return self._msgs.popleft()

  def Call(self, msg):
    """Send a message and wait for the response.

    This is just a wrapper over Send and Recv.

    """
    self.Send(msg)
    return self.Recv()

  @staticmethod
  def RetryOnBrokenPipe(fn, on_error):
    """Calls a given function, retrying if it fails on the 'Broken pipe' IO
    exception.

    This allows to re-establish a broken connection and retry an IO operation.

    The function receives one an integer argument stating the current retry
    number, 0 being the first call, 1 being the retry.

    If any exception occurs, on_error is invoked first with the exception given
    as an argument. Then, if the exception is 'Broken pipe', the function call
    is retried once more.

    """
    retries = 2
    for try_no in range(0, retries):
      try:
        return fn(try_no)
      except socket.error, ex:
        on_error(ex)
        # we retry on "Broken pipe", unless it's the last try
        if try_no == retries - 1:
          raise
        elif not (isinstance(ex.args, tuple) and (ex[0] == errno.EPIPE)):
          raise
      except Exception, ex:
        on_error(ex)
        raise
    assert False # we should never get here

  def Close(self):
    """Close the socket"""
    if self.socket is not None:
      self.socket.close()
      self.socket = None


class FdTransport:
  """Low-level transport class that works on arbitrary file descriptors.

  Unlike L{Transport}, this doesn't use timeouts.
  """

  def __init__(self, fds, timeouts=None): # pylint: disable=W0613
    """Constructor for the Client class.

    @type fds: pair of file descriptors
    @param fds: the file descriptor for reading (the first in the pair)
        and the file descriptor for writing (the second)
    @type timeouts: int
    @param timeouts: unused

    """
    self._rstream = io.open(fds[0], 'rb', 0)
    self._wstream = io.open(fds[1], 'wb', 0)

    self._buffer = ""
    self._msgs = collections.deque()

  def _CheckSocket(self):
    """Make sure we are connected.

    """
    if self._rstream is None or self._wstream is None:
      raise errors.ProtocolError("Connection is closed")

  def Send(self, msg):
    """Send a message.

    This just sends a message and doesn't wait for the response.

    """
    if constants.LUXI_EOM in msg:
      raise errors.ProtocolError("Message terminator found in payload")

    self._CheckSocket()
    self._wstream.write(msg + constants.LUXI_EOM)
    self._wstream.flush()

  def Recv(self):
    """Try to receive a message from the read part of the socket.

    In case we already have messages queued, we just return from the
    queue.

    """
    self._CheckSocket()
    while not self._msgs:
      data = self._rstream.read(4096)
      if not data:
        raise errors.ConnectionClosedError("Connection closed while reading")
      new_msgs = (self._buffer + data).split(constants.LUXI_EOM)
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
    if self._rstream is not None:
      self._rstream.close()
      self._rstream = None
    if self._wstream is not None:
      self._wstream.close()
      self._wstream = None

  def close(self):
    self.Close()
