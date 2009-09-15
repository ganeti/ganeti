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


"""Ganeti confd client

"""
import socket
import time
import random

from ganeti import utils
from ganeti import constants
from ganeti import objects
from ganeti import serializer
from ganeti import daemon # contains AsyncUDPSocket
from ganeti import errors
from ganeti import confd


class ConfdAsyncUDPClient(daemon.AsyncUDPSocket):
  """Confd udp asyncore client

  This is kept separate from the main ConfdClient to make sure it's easy to
  implement a non-asyncore based client library.

  """
  def __init__(self, client):
    """Constructor for ConfdAsyncUDPClient

    @type client: L{ConfdClient}
    @param client: client library, to pass the datagrams to

    """
    daemon.AsyncUDPSocket.__init__(self)
    self.client = client

  # this method is overriding a daemon.AsyncUDPSocket method
  def handle_datagram(self, payload, ip, port):
    self.client.HandleResponse(payload, ip, port)


class ConfdClient:
  """Send queries to confd, and get back answers.

  Since the confd model works by querying multiple master candidates, and
  getting back answers, this is an asynchronous library. It can either work
  through asyncore or with your own handling.

  """
  def __init__(self, hmac_key, peers):
    """Constructor for ConfdClient

    @type hmac_key: string
    @param hmac_key: hmac key to talk to confd
    @type peers: list
    @param peers: list of peer nodes

    """
    if not isinstance(peers, list):
      raise errors.ProgrammerError("peers must be a list")

    self._peers = peers
    self._hmac_key = hmac_key
    self._socket = ConfdAsyncUDPClient(self)
    self._callbacks = {}
    self._expire_callbacks = []
    self._confd_port = utils.GetDaemonPort(constants.CONFD)

  def _PackRequest(self, request, now=None):
    """Prepare a request to be sent on the wire.

    This function puts a proper salt in a confd request, puts the proper salt,
    and adds the correct magic number.

    """
    if now is None:
      now = time.time()
    tstamp = '%d' % now
    req = serializer.DumpSignedJson(request.ToDict(), self._hmac_key, tstamp)
    return confd.PackMagic(req)

  def _UnpackReply(self, payload):
    in_payload = confd.UnpackMagic(payload)
    (answer, salt) = serializer.LoadSignedJson(in_payload, self._hmac_key)
    return answer, salt

  def _ExpireCallbacks(self):
    """Delete all the expired callbacks.

    """
    now = time.time()
    while self._expire_callbacks:
      expire_time, rsalt = self._expire_callbacks[0]
      if now >= expire_time:
        self._expire_callbacks.pop()
        del self._callbacks[rsalt]
      else:
        break

  def SendRequest(self, request, callback, args, coverage=None):
    """Send a confd request to some MCs

    @type request: L{objects.ConfdRequest}
    @param request: the request to send
    @type callback: f(answer, req_type, req_query, salt, ip, port, args)
    @param callback: answer callback
    @type args: tuple
    @param args: additional callback arguments
    @type coverage: integer
    @keyword coverage: number of remote nodes to contact

    """
    if coverage is None:
      coverage = min(len(self._peers), constants.CONFD_DEFAULT_REQ_COVERAGE)

    if not callable(callback):
      raise errors.ConfdClientError("callback must be callable")

    if coverage > len(self._peers):
      raise errors.ConfdClientError("Not enough MCs known to provide the"
                                    " desired coverage")

    if not request.rsalt:
      raise errors.ConfdClientError("Missing request rsalt")

    self._ExpireCallbacks()
    if request.rsalt in self._callbacks:
      raise errors.ConfdClientError("Duplicate request rsalt")

    if request.type not in constants.CONFD_REQS:
      raise errors.ConfdClientError("Invalid request type")

    random.shuffle(self._peers)
    targets = self._peers[:coverage]

    now = time.time()
    payload = self._PackRequest(request, now=now)

    for target in targets:
      try:
        self._socket.enqueue_send(target, self._confd_port, payload)
      except errors.UdpDataSizeError:
        raise errors.ConfdClientError("Request too big")

    self._callbacks[request.rsalt] = (callback, request.type,
                                      request.query, args)
    expire_time = now + constants.CONFD_CLIENT_EXPIRE_TIMEOUT
    self._expire_callbacks.append((expire_time, request.rsalt))

  def HandleResponse(self, payload, ip, port):
    """Asynchronous handler for a confd reply

    Call the relevant callback associated to the current request.

    """
    try:
      try:
        answer, salt = self._UnpackReply(payload)
      except (errors.SignatureError, errors.ConfdMagicError):
        return

      try:
        (callback, type, query, args) = self._callbacks[salt]
      except KeyError:
        # If the salt is unkown the answer is probably a replay of an old
        # expired query. Ignoring it.
        pass
      else:
        callback(answer, type, query, salt, ip, port, args)

    finally:
      self._ExpireCallbacks()


class ConfdClientRequest(objects.ConfdRequest):
  """This is the client-side version of ConfdRequest.

  This version of the class helps creating requests, on the client side, by
  filling in some default values.

  """
  def __init__(self, **kwargs):
    objects.ConfdRequest.__init__(self, **kwargs)
    if not self.rsalt:
      self.rsalt = utils.NewUUID()
    if not self.protocol:
      self.protocol = constants.CONFD_PROTOCOL_VERSION
    if self.type not in constants.CONFD_REQS:
      raise errors.ConfdClientError("Invalid request type")

