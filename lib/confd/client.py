#
#

# Copyright (C) 2009, 2010, 2012 Google Inc.
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


"""Ganeti confd client

Clients can use the confd client library to send requests to a group of master
candidates running confd. The expected usage is through the asyncore framework,
by sending queries, and asynchronously receiving replies through a callback.

This way the client library doesn't ever need to "wait" on a particular answer,
and can proceed even if some udp packets are lost. It's up to the user to
reschedule queries if they haven't received responses and they need them.

Example usage::

  client = ConfdClient(...) # includes callback specification
  req = confd_client.ConfdClientRequest(type=constants.CONFD_REQ_PING)
  client.SendRequest(req)
  # then make sure your client calls asyncore.loop() or daemon.Mainloop.Run()
  # ... wait ...
  # And your callback will be called by asyncore, when your query gets a
  # response, or when it expires.

You can use the provided ConfdFilterCallback to act as a filter, only passing
"newer" answer to your callback, and filtering out outdated ones, or ones
confirming what you already got.

"""

# pylint: disable=E0203

# E0203: Access to member %r before its definition, since we use
# objects.py which doesn't explicitly initialise its members

import time
import random

from ganeti import utils
from ganeti import constants
from ganeti import objects
from ganeti import serializer
from ganeti import daemon # contains AsyncUDPSocket
from ganeti import errors
from ganeti import confd
from ganeti import ssconf
from ganeti import compat
from ganeti import netutils
from ganeti import pathutils


class ConfdAsyncUDPClient(daemon.AsyncUDPSocket):
  """Confd udp asyncore client

  This is kept separate from the main ConfdClient to make sure it's easy to
  implement a non-asyncore based client library.

  """
  def __init__(self, client, family):
    """Constructor for ConfdAsyncUDPClient

    @type client: L{ConfdClient}
    @param client: client library, to pass the datagrams to

    """
    daemon.AsyncUDPSocket.__init__(self, family)
    self.client = client

  # this method is overriding a daemon.AsyncUDPSocket method
  def handle_datagram(self, payload, ip, port):
    self.client.HandleResponse(payload, ip, port)


class _Request(object):
  """Request status structure.

  @ivar request: the request data
  @ivar args: any extra arguments for the callback
  @ivar expiry: the expiry timestamp of the request
  @ivar sent: the set of contacted peers
  @ivar rcvd: the set of peers who replied

  """
  def __init__(self, request, args, expiry, sent):
    self.request = request
    self.args = args
    self.expiry = expiry
    self.sent = frozenset(sent)
    self.rcvd = set()


class ConfdClient(object):
  """Send queries to confd, and get back answers.

  Since the confd model works by querying multiple master candidates, and
  getting back answers, this is an asynchronous library. It can either work
  through asyncore or with your own handling.

  @type _requests: dict
  @ivar _requests: dictionary indexes by salt, which contains data
      about the outstanding requests; the values are objects of type
      L{_Request}

  """
  def __init__(self, hmac_key, peers, callback, port=None, logger=None):
    """Constructor for ConfdClient

    @type hmac_key: string
    @param hmac_key: hmac key to talk to confd
    @type peers: list
    @param peers: list of peer nodes
    @type callback: f(L{ConfdUpcallPayload})
    @param callback: function to call when getting answers
    @type port: integer
    @param port: confd port (default: use GetDaemonPort)
    @type logger: logging.Logger
    @param logger: optional logger for internal conditions

    """
    if not callable(callback):
      raise errors.ProgrammerError("callback must be callable")

    self.UpdatePeerList(peers)
    self._SetPeersAddressFamily()
    self._hmac_key = hmac_key
    self._socket = ConfdAsyncUDPClient(self, self._family)
    self._callback = callback
    self._confd_port = port
    self._logger = logger
    self._requests = {}

    if self._confd_port is None:
      self._confd_port = netutils.GetDaemonPort(constants.CONFD)

  def UpdatePeerList(self, peers):
    """Update the list of peers

    @type peers: list
    @param peers: list of peer nodes

    """
    # we are actually called from init, so:
    # pylint: disable=W0201
    if not isinstance(peers, list):
      raise errors.ProgrammerError("peers must be a list")
    # make a copy of peers, since we're going to shuffle the list, later
    self._peers = list(peers)

  def _PackRequest(self, request, now=None):
    """Prepare a request to be sent on the wire.

    This function puts a proper salt in a confd request, puts the proper salt,
    and adds the correct magic number.

    """
    if now is None:
      now = time.time()
    tstamp = "%d" % now
    req = serializer.DumpSignedJson(request.ToDict(), self._hmac_key, tstamp)
    return confd.PackMagic(req)

  def _UnpackReply(self, payload):
    in_payload = confd.UnpackMagic(payload)
    (dict_answer, salt) = serializer.LoadSignedJson(in_payload, self._hmac_key)
    answer = objects.ConfdReply.FromDict(dict_answer)
    return answer, salt

  def ExpireRequests(self):
    """Delete all the expired requests.

    """
    now = time.time()
    for rsalt, rq in list(self._requests.items()):
      if now >= rq.expiry:
        del self._requests[rsalt]
        client_reply = ConfdUpcallPayload(salt=rsalt,
                                          type=UPCALL_EXPIRE,
                                          orig_request=rq.request,
                                          extra_args=rq.args,
                                          client=self,
                                          )
        self._callback(client_reply)

  def SendRequest(self, request, args=None, coverage=0, async_=True):
    """Send a confd request to some MCs

    @type request: L{objects.ConfdRequest}
    @param request: the request to send
    @type args: tuple
    @param args: additional callback arguments
    @type coverage: integer
    @param coverage: number of remote nodes to contact; if default
        (0), it will use a reasonable default
        (L{ganeti.constants.CONFD_DEFAULT_REQ_COVERAGE}), if -1 is
        passed, it will use the maximum number of peers, otherwise the
        number passed in will be used
    @type async_: boolean
    @param async_: handle the write asynchronously

    """
    if coverage == 0:
      coverage = min(len(self._peers), constants.CONFD_DEFAULT_REQ_COVERAGE)
    elif coverage == -1:
      coverage = len(self._peers)

    if coverage > len(self._peers):
      raise errors.ConfdClientError("Not enough MCs known to provide the"
                                    " desired coverage")

    if not request.rsalt:
      raise errors.ConfdClientError("Missing request rsalt")

    self.ExpireRequests()
    if request.rsalt in self._requests:
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

    expire_time = now + constants.CONFD_CLIENT_EXPIRE_TIMEOUT
    self._requests[request.rsalt] = _Request(request, args, expire_time,
                                             targets)

    if not async_:
      self.FlushSendQueue()

  def HandleResponse(self, payload, ip, port):
    """Asynchronous handler for a confd reply

    Call the relevant callback associated to the current request.

    """
    try:
      try:
        answer, salt = self._UnpackReply(payload)
      except (errors.SignatureError, errors.ConfdMagicError) as err:
        if self._logger:
          self._logger.debug("Discarding broken package: %s" % err)
        return

      try:
        rq = self._requests[salt]
      except KeyError:
        if self._logger:
          self._logger.debug("Discarding unknown (expired?) reply: %s" % err)
        return

      rq.rcvd.add(ip)

      client_reply = ConfdUpcallPayload(salt=salt,
                                        type=UPCALL_REPLY,
                                        server_reply=answer,
                                        orig_request=rq.request,
                                        server_ip=ip,
                                        server_port=port,
                                        extra_args=rq.args,
                                        client=self,
                                        )
      self._callback(client_reply)

    finally:
      self.ExpireRequests()

  def FlushSendQueue(self):
    """Send out all pending requests.

    Can be used for synchronous client use.

    """
    while self._socket.writable():
      self._socket.handle_write()

  def ReceiveReply(self, timeout=1):
    """Receive one reply.

    @type timeout: float
    @param timeout: how long to wait for the reply
    @rtype: boolean
    @return: True if some data has been handled, False otherwise

    """
    return self._socket.process_next_packet(timeout=timeout)

  @staticmethod
  def _NeededReplies(peer_cnt):
    """Compute the minimum safe number of replies for a query.

    The algorithm is designed to work well for both small and big
    number of peers:
        - for less than three, we require all responses
        - for less than five, we allow one miss
        - otherwise, half the number plus one

    This guarantees that we progress monotonically: 1->1, 2->2, 3->2,
    4->2, 5->3, 6->3, 7->4, etc.

    @type peer_cnt: int
    @param peer_cnt: the number of peers contacted
    @rtype: int
    @return: the number of replies which should give a safe coverage

    """
    if peer_cnt < 3:
      return peer_cnt
    elif peer_cnt < 5:
      return peer_cnt - 1
    else:
      return int(peer_cnt / 2) + 1

  def WaitForReply(self, salt, timeout=constants.CONFD_CLIENT_EXPIRE_TIMEOUT):
    """Wait for replies to a given request.

    This method will wait until either the timeout expires or a
    minimum number (computed using L{_NeededReplies}) of replies are
    received for the given salt. It is useful when doing synchronous
    calls to this library.

    @param salt: the salt of the request we want responses for
    @param timeout: the maximum timeout (should be less or equal to
        L{ganeti.constants.CONFD_CLIENT_EXPIRE_TIMEOUT}
    @rtype: tuple
    @return: a tuple of (timed_out, sent_cnt, recv_cnt); if the
        request is unknown, timed_out will be true and the counters
        will be zero

    """
    def _CheckResponse():
      if salt not in self._requests:
        # expired?
        if self._logger:
          self._logger.debug("Discarding unknown/expired request: %s" % salt)
        return MISSING
      rq = self._requests[salt]
      if len(rq.rcvd) >= expected:
        # already got all replies
        return (False, len(rq.sent), len(rq.rcvd))
      # else wait, using default timeout
      self.ReceiveReply()
      raise utils.RetryAgain()

    MISSING = (True, 0, 0)

    if salt not in self._requests:
      return MISSING
    # extend the expire time with the current timeout, so that we
    # don't get the request expired from under us
    rq = self._requests[salt]
    rq.expiry += timeout
    sent = len(rq.sent)
    expected = self._NeededReplies(sent)

    try:
      return utils.Retry(_CheckResponse, 0, timeout)
    except utils.RetryTimeout:
      if salt in self._requests:
        rq = self._requests[salt]
        return (True, len(rq.sent), len(rq.rcvd))
      else:
        return MISSING

  def _SetPeersAddressFamily(self):
    if not self._peers:
      raise errors.ConfdClientError("Peer list empty")
    try:
      peer = self._peers[0]
      self._family = netutils.IPAddress.GetAddressFamily(peer)
      for peer in self._peers[1:]:
        if netutils.IPAddress.GetAddressFamily(peer) != self._family:
          raise errors.ConfdClientError("Peers must be of same address family")
    except errors.IPAddressError:
      raise errors.ConfdClientError("Peer address %s invalid" % peer)


# UPCALL_REPLY: server reply upcall
# has all ConfdUpcallPayload fields populated
UPCALL_REPLY = 1
# UPCALL_EXPIRE: internal library request expire
# has only salt, type, orig_request and extra_args
UPCALL_EXPIRE = 2
CONFD_UPCALL_TYPES = compat.UniqueFrozenset([
  UPCALL_REPLY,
  UPCALL_EXPIRE,
  ])


class ConfdUpcallPayload(objects.ConfigObject):
  """Callback argument for confd replies

  @type salt: string
  @ivar salt: salt associated with the query
  @type type: one of confd.client.CONFD_UPCALL_TYPES
  @ivar type: upcall type (server reply, expired request, ...)
  @type orig_request: L{objects.ConfdRequest}
  @ivar orig_request: original request
  @type server_reply: L{objects.ConfdReply}
  @ivar server_reply: server reply
  @type server_ip: string
  @ivar server_ip: answering server ip address
  @type server_port: int
  @ivar server_port: answering server port
  @type extra_args: any
  @ivar extra_args: 'args' argument of the SendRequest function
  @type client: L{ConfdClient}
  @ivar client: current confd client instance

  """
  __slots__ = [
    "salt",
    "type",
    "orig_request",
    "server_reply",
    "server_ip",
    "server_port",
    "extra_args",
    "client",
    ]


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


class ConfdFilterCallback(object):
  """Callback that calls another callback, but filters duplicate results.

  @ivar consistent: a dictionary indexed by salt; for each salt, if
      all responses ware identical, this will be True; this is the
      expected state on a healthy cluster; on inconsistent or
      partitioned clusters, this might be False, if we see answers
      with the same serial but different contents

  """
  def __init__(self, callback, logger=None):
    """Constructor for ConfdFilterCallback

    @type callback: f(L{ConfdUpcallPayload})
    @param callback: function to call when getting answers
    @type logger: logging.Logger
    @param logger: optional logger for internal conditions

    """
    if not callable(callback):
      raise errors.ProgrammerError("callback must be callable")

    self._callback = callback
    self._logger = logger
    # answers contains a dict of salt -> answer
    self._answers = {}
    self.consistent = {}

  def _LogFilter(self, salt, new_reply, old_reply):
    if not self._logger:
      return

    if new_reply.serial > old_reply.serial:
      self._logger.debug("Filtering confirming answer, with newer"
                         " serial for query %s" % salt)
    elif new_reply.serial == old_reply.serial:
      if new_reply.answer != old_reply.answer:
        self._logger.warning("Got incoherent answers for query %s"
                             " (serial: %s)" % (salt, new_reply.serial))
      else:
        self._logger.debug("Filtering confirming answer, with same"
                           " serial for query %s" % salt)
    else:
      self._logger.debug("Filtering outdated answer for query %s"
                         " serial: (%d < %d)" % (salt, old_reply.serial,
                                                 new_reply.serial))

  def _HandleExpire(self, up):
    # if we have no answer we have received none, before the expiration.
    if up.salt in self._answers:
      del self._answers[up.salt]
    if up.salt in self.consistent:
      del self.consistent[up.salt]

  def _HandleReply(self, up):
    """Handle a single confd reply, and decide whether to filter it.

    @rtype: boolean
    @return: True if the reply should be filtered, False if it should be passed
             on to the up-callback

    """
    filter_upcall = False
    salt = up.salt
    if salt not in self.consistent:
      self.consistent[salt] = True
    if salt not in self._answers:
      # first answer for a query (don't filter, and record)
      self._answers[salt] = up.server_reply
    elif up.server_reply.serial > self._answers[salt].serial:
      # newer answer (record, and compare contents)
      old_answer = self._answers[salt]
      self._answers[salt] = up.server_reply
      if up.server_reply.answer == old_answer.answer:
        # same content (filter) (version upgrade was unrelated)
        filter_upcall = True
        self._LogFilter(salt, up.server_reply, old_answer)
      # else: different content, pass up a second answer
    else:
      # older or same-version answer (duplicate or outdated, filter)
      if (up.server_reply.serial == self._answers[salt].serial and
          up.server_reply.answer != self._answers[salt].answer):
        self.consistent[salt] = False
      filter_upcall = True
      self._LogFilter(salt, up.server_reply, self._answers[salt])

    return filter_upcall

  def __call__(self, up):
    """Filtering callback

    @type up: L{ConfdUpcallPayload}
    @param up: upper callback

    """
    filter_upcall = False
    if up.type == UPCALL_REPLY:
      filter_upcall = self._HandleReply(up)
    elif up.type == UPCALL_EXPIRE:
      self._HandleExpire(up)

    if not filter_upcall:
      self._callback(up)


class ConfdCountingCallback(object):
  """Callback that calls another callback, and counts the answers

  """
  def __init__(self, callback, logger=None):
    """Constructor for ConfdCountingCallback

    @type callback: f(L{ConfdUpcallPayload})
    @param callback: function to call when getting answers
    @type logger: logging.Logger
    @param logger: optional logger for internal conditions

    """
    if not callable(callback):
      raise errors.ProgrammerError("callback must be callable")

    self._callback = callback
    self._logger = logger
    # answers contains a dict of salt -> count
    self._answers = {}

  def RegisterQuery(self, salt):
    if salt in self._answers:
      raise errors.ProgrammerError("query already registered")
    self._answers[salt] = 0

  def AllAnswered(self):
    """Have all the registered queries received at least an answer?

    """
    return compat.all(self._answers.values())

  def _HandleExpire(self, up):
    # if we have no answer we have received none, before the expiration.
    if up.salt in self._answers:
      del self._answers[up.salt]

  def _HandleReply(self, up):
    """Handle a single confd reply, and decide whether to filter it.

    @rtype: boolean
    @return: True if the reply should be filtered, False if it should be passed
             on to the up-callback

    """
    if up.salt in self._answers:
      self._answers[up.salt] += 1

  def __call__(self, up):
    """Filtering callback

    @type up: L{ConfdUpcallPayload}
    @param up: upper callback

    """
    if up.type == UPCALL_REPLY:
      self._HandleReply(up)
    elif up.type == UPCALL_EXPIRE:
      self._HandleExpire(up)
    self._callback(up)


class StoreResultCallback(object):
  """Callback that simply stores the most recent answer.

  @ivar _answers: dict of salt to (have_answer, reply)

  """
  _NO_KEY = (False, None)

  def __init__(self):
    """Constructor for StoreResultCallback

    """
    # answers contains a dict of salt -> best result
    self._answers = {}

  def GetResponse(self, salt):
    """Return the best match for a salt

    """
    return self._answers.get(salt, self._NO_KEY)

  def _HandleExpire(self, up):
    """Expiration handler.

    """
    if up.salt in self._answers and self._answers[up.salt] == self._NO_KEY:
      del self._answers[up.salt]

  def _HandleReply(self, up):
    """Handle a single confd reply, and decide whether to filter it.

    """
    self._answers[up.salt] = (True, up)

  def __call__(self, up):
    """Filtering callback

    @type up: L{ConfdUpcallPayload}
    @param up: upper callback

    """
    if up.type == UPCALL_REPLY:
      self._HandleReply(up)
    elif up.type == UPCALL_EXPIRE:
      self._HandleExpire(up)


def GetConfdClient(callback):
  """Return a client configured using the given callback.

  This is handy to abstract the MC list and HMAC key reading.

  @attention: This should only be called on nodes which are part of a
      cluster, since it depends on a valid (ganeti) data directory;
      for code running outside of a cluster, you need to create the
      client manually

  """
  ss = ssconf.SimpleStore()
  mc_file = ss.KeyToFilename(constants.SS_MASTER_CANDIDATES_IPS)
  mc_list = utils.ReadFile(mc_file).splitlines()
  hmac_key = utils.ReadFile(pathutils.CONFD_HMAC_KEY)
  return ConfdClient(hmac_key, mc_list, callback)
