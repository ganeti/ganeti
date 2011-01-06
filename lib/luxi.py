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

This module implements the local unix socket protocol. You only need
this module and the opcodes module in the client program in order to
communicate with the master.

The module is also used by the master daemon.

"""

import socket
import collections
import time
import errno
import logging
import warnings

from ganeti import serializer
from ganeti import constants
from ganeti import errors
from ganeti import utils
from ganeti import objects


KEY_METHOD = "method"
KEY_ARGS = "args"
KEY_SUCCESS = "success"
KEY_RESULT = "result"
KEY_VERSION = "version"

REQ_SUBMIT_JOB = "SubmitJob"
REQ_SUBMIT_MANY_JOBS = "SubmitManyJobs"
REQ_WAIT_FOR_JOB_CHANGE = "WaitForJobChange"
REQ_CANCEL_JOB = "CancelJob"
REQ_ARCHIVE_JOB = "ArchiveJob"
REQ_AUTOARCHIVE_JOBS = "AutoArchiveJobs"
REQ_QUERY = "Query"
REQ_QUERY_FIELDS = "QueryFields"
REQ_QUERY_JOBS = "QueryJobs"
REQ_QUERY_INSTANCES = "QueryInstances"
REQ_QUERY_NODES = "QueryNodes"
REQ_QUERY_GROUPS = "QueryGroups"
REQ_QUERY_EXPORTS = "QueryExports"
REQ_QUERY_CONFIG_VALUES = "QueryConfigValues"
REQ_QUERY_CLUSTER_INFO = "QueryClusterInfo"
REQ_QUERY_TAGS = "QueryTags"
REQ_QUERY_LOCKS = "QueryLocks"
REQ_QUEUE_SET_DRAIN_FLAG = "SetDrainFlag"
REQ_SET_WATCHER_PAUSE = "SetWatcherPause"

DEF_CTMO = 10
DEF_RWTO = 60

# WaitForJobChange timeout
WFJC_TIMEOUT = (DEF_RWTO - 1) / 2


class ProtocolError(errors.LuxiError):
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


class Transport:
  """Low-level transport class.

  This is used on the client side.

  This could be replace by any other class that provides the same
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
        raise TimeoutError("Connect timed out")

      self.socket.settimeout(self._rwtimeout)
    except (socket.error, NoMasterError):
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
      raise TimeoutError("Connect timed out: %s" % str(err))
    except socket.error, err:
      error_code = err.args[0]
      if error_code in (errno.ENOENT, errno.ECONNREFUSED):
        raise NoMasterError(address)
      elif error_code in (errno.EPERM, errno.EACCES):
        raise PermissionError(address)
      elif error_code == errno.EAGAIN:
        # Server's socket backlog is full at the moment
        raise utils.RetryAgain()
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
    if constants.LUXI_EOM in msg:
      raise ProtocolError("Message terminator found in payload")

    self._CheckSocket()
    try:
      # TODO: sendall is not guaranteed to send everything
      self.socket.sendall(msg + constants.LUXI_EOM)
    except socket.timeout, err:
      raise TimeoutError("Sending timeout: %s" % str(err))

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
        raise TimeoutError("Extended receive timeout")
      while True:
        try:
          data = self.socket.recv(4096)
        except socket.timeout, err:
          raise TimeoutError("Receive timeout: %s" % str(err))
        except socket.error, err:
          if err.args and err.args[0] == errno.EAGAIN:
            continue
          raise
        break
      if not data:
        raise ConnectionClosedError("Connection closed while reading")
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
    if self.socket is not None:
      self.socket.close()
      self.socket = None


def ParseRequest(msg):
  """Parses a LUXI request message.

  """
  try:
    request = serializer.LoadJson(msg)
  except ValueError, err:
    raise ProtocolError("Invalid LUXI request (parsing error): %s" % err)

  logging.debug("LUXI request: %s", request)

  if not isinstance(request, dict):
    logging.error("LUXI request not a dict: %r", msg)
    raise ProtocolError("Invalid LUXI request (not a dict)")

  method = request.get(KEY_METHOD, None) # pylint: disable-msg=E1103
  args = request.get(KEY_ARGS, None) # pylint: disable-msg=E1103
  version = request.get(KEY_VERSION, None) # pylint: disable-msg=E1103

  if method is None or args is None:
    logging.error("LUXI request missing method or arguments: %r", msg)
    raise ProtocolError(("Invalid LUXI request (no method or arguments"
                         " in request): %r") % msg)

  return (method, args, version)


def ParseResponse(msg):
  """Parses a LUXI response message.

  """
  # Parse the result
  try:
    data = serializer.LoadJson(msg)
  except Exception, err:
    raise ProtocolError("Error while deserializing response: %s" % str(err))

  # Validate response
  if not (isinstance(data, dict) and
          KEY_SUCCESS in data and
          KEY_RESULT in data):
    raise ProtocolError("Invalid response from server: %r" % data)

  return (data[KEY_SUCCESS], data[KEY_RESULT],
          data.get(KEY_VERSION, None)) # pylint: disable-msg=E1103


def FormatResponse(success, result, version=None):
  """Formats a LUXI response message.

  """
  response = {
    KEY_SUCCESS: success,
    KEY_RESULT: result,
    }

  if version is not None:
    response[KEY_VERSION] = version

  logging.debug("LUXI response: %s", response)

  return serializer.DumpJson(response)


def FormatRequest(method, args, version=None):
  """Formats a LUXI request message.

  """
  # Build request
  request = {
    KEY_METHOD: method,
    KEY_ARGS: args,
    }

  if version is not None:
    request[KEY_VERSION] = version

  # Serialize the request
  return serializer.DumpJson(request, indent=False)


def CallLuxiMethod(transport_cb, method, args, version=None):
  """Send a LUXI request via a transport and return the response.

  """
  assert callable(transport_cb)

  request_msg = FormatRequest(method, args, version=version)

  # Send request and wait for response
  response_msg = transport_cb(request_msg)

  (success, result, resp_version) = ParseResponse(response_msg)

  # Verify version if there was one in the response
  if resp_version is not None and resp_version != version:
    raise errors.LuxiError("LUXI version mismatch, client %s, response %s" %
                           (version, resp_version))

  if success:
    return result

  errors.MaybeRaise(result)
  raise RequestError(result)


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
    self.address = address
    self.timeouts = timeouts
    self.transport_class = transport
    self.transport = None
    self._InitTransport()

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
    except Exception: # pylint: disable-msg=W0703
      pass

  def _SendMethodCall(self, data):
    # Send request and wait for response
    try:
      self._InitTransport()
      return self.transport.Call(data)
    except Exception:
      self._CloseTransport()
      raise

  def CallMethod(self, method, args):
    """Send a generic request and return the response.

    """
    return CallLuxiMethod(self._SendMethodCall, method, args,
                          version=constants.LUXI_VERSION)

  def SetQueueDrainFlag(self, drain_flag):
    return self.CallMethod(REQ_QUEUE_SET_DRAIN_FLAG, drain_flag)

  def SetWatcherPause(self, until):
    return self.CallMethod(REQ_SET_WATCHER_PAUSE, [until])

  def SubmitJob(self, ops):
    ops_state = map(lambda op: op.__getstate__(), ops)
    return self.CallMethod(REQ_SUBMIT_JOB, ops_state)

  def SubmitManyJobs(self, jobs):
    jobs_state = []
    for ops in jobs:
      jobs_state.append([op.__getstate__() for op in ops])
    return self.CallMethod(REQ_SUBMIT_MANY_JOBS, jobs_state)

  def CancelJob(self, job_id):
    return self.CallMethod(REQ_CANCEL_JOB, job_id)

  def ArchiveJob(self, job_id):
    return self.CallMethod(REQ_ARCHIVE_JOB, job_id)

  def AutoArchiveJobs(self, age):
    timeout = (DEF_RWTO - 1) / 2
    return self.CallMethod(REQ_AUTOARCHIVE_JOBS, (age, timeout))

  def WaitForJobChangeOnce(self, job_id, fields,
                           prev_job_info, prev_log_serial,
                           timeout=WFJC_TIMEOUT):
    """Waits for changes on a job.

    @param job_id: Job ID
    @type fields: list
    @param fields: List of field names to be observed
    @type prev_job_info: None or list
    @param prev_job_info: Previously received job information
    @type prev_log_serial: None or int/long
    @param prev_log_serial: Highest log serial number previously received
    @type timeout: int/float
    @param timeout: Timeout in seconds (values larger than L{WFJC_TIMEOUT} will
                    be capped to that value)

    """
    assert timeout >= 0, "Timeout can not be negative"
    return self.CallMethod(REQ_WAIT_FOR_JOB_CHANGE,
                           (job_id, fields, prev_job_info,
                            prev_log_serial,
                            min(WFJC_TIMEOUT, timeout)))

  def WaitForJobChange(self, job_id, fields, prev_job_info, prev_log_serial):
    while True:
      result = self.WaitForJobChangeOnce(job_id, fields,
                                         prev_job_info, prev_log_serial)
      if result != constants.JOB_NOTCHANGED:
        break
    return result

  def Query(self, what, fields, filter_):
    """Query for resources/items.

    @param what: One of L{constants.QR_OP_LUXI}
    @type fields: List of strings
    @param fields: List of requested fields
    @type filter_: None or list
    @param filter_: Query filter
    @rtype: L{objects.QueryResponse}

    """
    req = objects.QueryRequest(what=what, fields=fields, filter=filter_)
    result = self.CallMethod(REQ_QUERY, req.ToDict())
    return objects.QueryResponse.FromDict(result)

  def QueryFields(self, what, fields):
    """Query for available fields.

    @param what: One of L{constants.QR_OP_LUXI}
    @type fields: None or list of strings
    @param fields: List of requested fields
    @rtype: L{objects.QueryFieldsResponse}

    """
    req = objects.QueryFieldsRequest(what=what, fields=fields)
    result = self.CallMethod(REQ_QUERY_FIELDS, req.ToDict())
    return objects.QueryFieldsResponse.FromDict(result)

  def QueryJobs(self, job_ids, fields):
    return self.CallMethod(REQ_QUERY_JOBS, (job_ids, fields))

  def QueryInstances(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_INSTANCES, (names, fields, use_locking))

  def QueryNodes(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_NODES, (names, fields, use_locking))

  def QueryGroups(self, names, fields, use_locking):
    return self.CallMethod(REQ_QUERY_GROUPS, (names, fields, use_locking))

  def QueryExports(self, nodes, use_locking):
    return self.CallMethod(REQ_QUERY_EXPORTS, (nodes, use_locking))

  def QueryClusterInfo(self):
    return self.CallMethod(REQ_QUERY_CLUSTER_INFO, ())

  def QueryConfigValues(self, fields):
    return self.CallMethod(REQ_QUERY_CONFIG_VALUES, fields)

  def QueryTags(self, kind, name):
    return self.CallMethod(REQ_QUERY_TAGS, (kind, name))

  def QueryLocks(self, fields, sync):
    warnings.warn("This LUXI call is deprecated and will be removed, use"
                  " Query(\"%s\", ...) instead" % constants.QR_LOCK)
    return self.CallMethod(REQ_QUERY_LOCKS, (fields, sync))
