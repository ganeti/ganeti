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


"""Inter-node RPC library.

"""

# pylint: disable=C0103,R0201,R0904
# C0103: Invalid name, since call_ are not valid
# R0201: Method could be a function, we keep all rpcs instance methods
# as not to change them back and forth between static/instance methods
# if they need to start using instance attributes
# R0904: Too many public methods

import os
import logging
import zlib
import base64
import pycurl
import threading

from ganeti import utils
from ganeti import objects
from ganeti import http
from ganeti import serializer
from ganeti import constants
from ganeti import errors
from ganeti import netutils
from ganeti import ssconf
from ganeti import runtime
from ganeti import compat

# Special module generated at build time
from ganeti import _generated_rpc

# pylint has a bug here, doesn't see this import
import ganeti.http.client  # pylint: disable=W0611


# Timeout for connecting to nodes (seconds)
_RPC_CONNECT_TIMEOUT = 5

_RPC_CLIENT_HEADERS = [
  "Content-type: %s" % http.HTTP_APP_JSON,
  "Expect:",
  ]

# Various time constants for the timeout table
_TMO_URGENT = 60 # one minute
_TMO_FAST = 5 * 60 # five minutes
_TMO_NORMAL = 15 * 60 # 15 minutes
_TMO_SLOW = 3600 # one hour
_TMO_4HRS = 4 * 3600
_TMO_1DAY = 86400

# Timeout table that will be built later by decorators
# Guidelines for choosing timeouts:
# - call used during watcher: timeout -> 1min, _TMO_URGENT
# - trivial (but be sure it is trivial) (e.g. reading a file): 5min, _TMO_FAST
# - other calls: 15 min, _TMO_NORMAL
# - special calls (instance add, etc.): either _TMO_SLOW (1h) or huge timeouts

_TIMEOUTS = {
}

#: Special value to describe an offline host
_OFFLINE = object()


def Init():
  """Initializes the module-global HTTP client manager.

  Must be called before using any RPC function and while exactly one thread is
  running.

  """
  # curl_global_init(3) and curl_global_cleanup(3) must be called with only
  # one thread running. This check is just a safety measure -- it doesn't
  # cover all cases.
  assert threading.activeCount() == 1, \
         "Found more than one active thread when initializing pycURL"

  logging.info("Using PycURL %s", pycurl.version)

  pycurl.global_init(pycurl.GLOBAL_ALL)


def Shutdown():
  """Stops the module-global HTTP client manager.

  Must be called before quitting the program and while exactly one thread is
  running.

  """
  pycurl.global_cleanup()


def _ConfigRpcCurl(curl):
  noded_cert = str(constants.NODED_CERT_FILE)

  curl.setopt(pycurl.FOLLOWLOCATION, False)
  curl.setopt(pycurl.CAINFO, noded_cert)
  curl.setopt(pycurl.SSL_VERIFYHOST, 0)
  curl.setopt(pycurl.SSL_VERIFYPEER, True)
  curl.setopt(pycurl.SSLCERTTYPE, "PEM")
  curl.setopt(pycurl.SSLCERT, noded_cert)
  curl.setopt(pycurl.SSLKEYTYPE, "PEM")
  curl.setopt(pycurl.SSLKEY, noded_cert)
  curl.setopt(pycurl.CONNECTTIMEOUT, _RPC_CONNECT_TIMEOUT)


def _RpcTimeout(secs):
  """Timeout decorator.

  When applied to a rpc call_* function, it updates the global timeout
  table with the given function/timeout.

  """
  def decorator(f):
    name = f.__name__
    assert name.startswith("call_")
    _TIMEOUTS[name[len("call_"):]] = secs
    return f
  return decorator


def RunWithRPC(fn):
  """RPC-wrapper decorator.

  When applied to a function, it runs it with the RPC system
  initialized, and it shutsdown the system afterwards. This means the
  function must be called without RPC being initialized.

  """
  def wrapper(*args, **kwargs):
    Init()
    try:
      return fn(*args, **kwargs)
    finally:
      Shutdown()
  return wrapper


def _Compress(data):
  """Compresses a string for transport over RPC.

  Small amounts of data are not compressed.

  @type data: str
  @param data: Data
  @rtype: tuple
  @return: Encoded data to send

  """
  # Small amounts of data are not compressed
  if len(data) < 512:
    return (constants.RPC_ENCODING_NONE, data)

  # Compress with zlib and encode in base64
  return (constants.RPC_ENCODING_ZLIB_BASE64,
          base64.b64encode(zlib.compress(data, 3)))


class RpcResult(object):
  """RPC Result class.

  This class holds an RPC result. It is needed since in multi-node
  calls we can't raise an exception just because one one out of many
  failed, and therefore we use this class to encapsulate the result.

  @ivar data: the data payload, for successful results, or None
  @ivar call: the name of the RPC call
  @ivar node: the name of the node to which we made the call
  @ivar offline: whether the operation failed because the node was
      offline, as opposed to actual failure; offline=True will always
      imply failed=True, in order to allow simpler checking if
      the user doesn't care about the exact failure mode
  @ivar fail_msg: the error message if the call failed

  """
  def __init__(self, data=None, failed=False, offline=False,
               call=None, node=None):
    self.offline = offline
    self.call = call
    self.node = node

    if offline:
      self.fail_msg = "Node is marked offline"
      self.data = self.payload = None
    elif failed:
      self.fail_msg = self._EnsureErr(data)
      self.data = self.payload = None
    else:
      self.data = data
      if not isinstance(self.data, (tuple, list)):
        self.fail_msg = ("RPC layer error: invalid result type (%s)" %
                         type(self.data))
        self.payload = None
      elif len(data) != 2:
        self.fail_msg = ("RPC layer error: invalid result length (%d), "
                         "expected 2" % len(self.data))
        self.payload = None
      elif not self.data[0]:
        self.fail_msg = self._EnsureErr(self.data[1])
        self.payload = None
      else:
        # finally success
        self.fail_msg = None
        self.payload = data[1]

    for attr_name in ["call", "data", "fail_msg",
                      "node", "offline", "payload"]:
      assert hasattr(self, attr_name), "Missing attribute %s" % attr_name

  @staticmethod
  def _EnsureErr(val):
    """Helper to ensure we return a 'True' value for error."""
    if val:
      return val
    else:
      return "No error information"

  def Raise(self, msg, prereq=False, ecode=None):
    """If the result has failed, raise an OpExecError.

    This is used so that LU code doesn't have to check for each
    result, but instead can call this function.

    """
    if not self.fail_msg:
      return

    if not msg: # one could pass None for default message
      msg = ("Call '%s' to node '%s' has failed: %s" %
             (self.call, self.node, self.fail_msg))
    else:
      msg = "%s: %s" % (msg, self.fail_msg)
    if prereq:
      ec = errors.OpPrereqError
    else:
      ec = errors.OpExecError
    if ecode is not None:
      args = (msg, ecode)
    else:
      args = (msg, )
    raise ec(*args) # pylint: disable=W0142


def _SsconfResolver(node_list,
                    ssc=ssconf.SimpleStore,
                    nslookup_fn=netutils.Hostname.GetIP):
  """Return addresses for given node names.

  @type node_list: list
  @param node_list: List of node names
  @type ssc: class
  @param ssc: SimpleStore class that is used to obtain node->ip mappings
  @type nslookup_fn: callable
  @param nslookup_fn: function use to do NS lookup
  @rtype: list of tuple; (string, string)
  @return: List of tuples containing node name and IP address

  """
  ss = ssc()
  iplist = ss.GetNodePrimaryIPList()
  family = ss.GetPrimaryIPFamily()
  ipmap = dict(entry.split() for entry in iplist)

  result = []
  for node in node_list:
    ip = ipmap.get(node)
    if ip is None:
      ip = nslookup_fn(node, family=family)
    result.append((node, ip))

  return result


class _StaticResolver:
  def __init__(self, addresses):
    """Initializes this class.

    """
    self._addresses = addresses

  def __call__(self, hosts):
    """Returns static addresses for hosts.

    """
    assert len(hosts) == len(self._addresses)
    return zip(hosts, self._addresses)


def _CheckConfigNode(name, node):
  """Checks if a node is online.

  @type name: string
  @param name: Node name
  @type node: L{objects.Node} or None
  @param node: Node object

  """
  if node is None:
    # Depend on DNS for name resolution
    ip = name
  elif node.offline:
    ip = _OFFLINE
  else:
    ip = node.primary_ip
  return (name, ip)


def _NodeConfigResolver(single_node_fn, all_nodes_fn, hosts):
  """Calculate node addresses using configuration.

  """
  # Special case for single-host lookups
  if len(hosts) == 1:
    (name, ) = hosts
    return [_CheckConfigNode(name, single_node_fn(name))]
  else:
    all_nodes = all_nodes_fn()
    return [_CheckConfigNode(name, all_nodes.get(name, None))
            for name in hosts]


class _RpcProcessor:
  def __init__(self, resolver, port, lock_monitor_cb=None):
    """Initializes this class.

    @param resolver: callable accepting a list of hostnames, returning a list
      of tuples containing name and IP address (IP address can be the name or
      the special value L{_OFFLINE} to mark offline machines)
    @type port: int
    @param port: TCP port
    @param lock_monitor_cb: Callable for registering with lock monitor

    """
    self._resolver = resolver
    self._port = port
    self._lock_monitor_cb = lock_monitor_cb

  @staticmethod
  def _PrepareRequests(hosts, port, procedure, body, read_timeout):
    """Prepares requests by sorting offline hosts into separate list.

    """
    results = {}
    requests = {}

    for (name, ip) in hosts:
      if ip is _OFFLINE:
        # Node is marked as offline
        results[name] = RpcResult(node=name, offline=True, call=procedure)
      else:
        requests[name] = \
          http.client.HttpClientRequest(str(ip), port,
                                        http.HTTP_PUT, str("/%s" % procedure),
                                        headers=_RPC_CLIENT_HEADERS,
                                        post_data=body,
                                        read_timeout=read_timeout,
                                        nicename="%s/%s" % (name, procedure),
                                        curl_config_fn=_ConfigRpcCurl)

    return (results, requests)

  @staticmethod
  def _CombineResults(results, requests, procedure):
    """Combines pre-computed results for offline hosts with actual call results.

    """
    for name, req in requests.items():
      if req.success and req.resp_status_code == http.HTTP_OK:
        host_result = RpcResult(data=serializer.LoadJson(req.resp_body),
                                node=name, call=procedure)
      else:
        # TODO: Better error reporting
        if req.error:
          msg = req.error
        else:
          msg = req.resp_body

        logging.error("RPC error in %s on node %s: %s", procedure, name, msg)
        host_result = RpcResult(data=msg, failed=True, node=name,
                                call=procedure)

      results[name] = host_result

    return results

  def __call__(self, hosts, procedure, body, read_timeout=None,
               _req_process_fn=http.client.ProcessRequests):
    """Makes an RPC request to a number of nodes.

    @type hosts: sequence
    @param hosts: Hostnames
    @type procedure: string
    @param procedure: Request path
    @type body: string
    @param body: Request body
    @type read_timeout: int or None
    @param read_timeout: Read timeout for request

    """
    if read_timeout is None:
      read_timeout = _TIMEOUTS.get(procedure, None)

    assert read_timeout is not None, \
      "Missing RPC read timeout for procedure '%s'" % procedure

    (results, requests) = \
      self._PrepareRequests(self._resolver(hosts), self._port, procedure,
                            str(body), read_timeout)

    _req_process_fn(requests.values(), lock_monitor_cb=self._lock_monitor_cb)

    assert not frozenset(results).intersection(requests)

    return self._CombineResults(results, requests, procedure)


class RpcRunner(_generated_rpc.RpcClientDefault,
                _generated_rpc.RpcClientBootstrap,
                _generated_rpc.RpcClientConfig):
  """RPC runner class.

  """
  def __init__(self, context):
    """Initialized the RPC runner.

    @type context: C{masterd.GanetiContext}
    @param context: Ganeti context

    """
    # Pylint doesn't recognize multiple inheritance properly, see
    # <http://www.logilab.org/ticket/36586> and
    # <http://www.logilab.org/ticket/35642>
    # pylint: disable=W0233
    _generated_rpc.RpcClientConfig.__init__(self)
    _generated_rpc.RpcClientBootstrap.__init__(self)
    _generated_rpc.RpcClientDefault.__init__(self)

    self._cfg = context.cfg
    self._proc = _RpcProcessor(compat.partial(_NodeConfigResolver,
                                              self._cfg.GetNodeInfo,
                                              self._cfg.GetAllNodesInfo),
                               netutils.GetDaemonPort(constants.NODED),
                               lock_monitor_cb=context.glm.AddToLockMonitor)

  def _InstDict(self, instance, hvp=None, bep=None, osp=None):
    """Convert the given instance to a dict.

    This is done via the instance's ToDict() method and additionally
    we fill the hvparams with the cluster defaults.

    @type instance: L{objects.Instance}
    @param instance: an Instance object
    @type hvp: dict or None
    @param hvp: a dictionary with overridden hypervisor parameters
    @type bep: dict or None
    @param bep: a dictionary with overridden backend parameters
    @type osp: dict or None
    @param osp: a dictionary with overridden os parameters
    @rtype: dict
    @return: the instance dict, with the hvparams filled with the
        cluster defaults

    """
    idict = instance.ToDict()
    cluster = self._cfg.GetClusterInfo()
    idict["hvparams"] = cluster.FillHV(instance)
    if hvp is not None:
      idict["hvparams"].update(hvp)
    idict["beparams"] = cluster.FillBE(instance)
    if bep is not None:
      idict["beparams"].update(bep)
    idict["osparams"] = cluster.SimpleFillOS(instance.os, instance.osparams)
    if osp is not None:
      idict["osparams"].update(osp)
    for nic in idict["nics"]:
      nic['nicparams'] = objects.FillDict(
        cluster.nicparams[constants.PP_DEFAULT],
        nic['nicparams'])
    return idict

  def _InstDictHvpBep(self, (instance, hvp, bep)):
    """Wrapper for L{_InstDict}.

    """
    return self._InstDict(instance, hvp=hvp, bep=bep)

  def _InstDictOsp(self, (instance, osparams)):
    """Wrapper for L{_InstDict}.

    """
    return self._InstDict(instance, osp=osparams)

  def _Call(self, node_list, procedure, timeout, args):
    """Entry point for automatically generated RPC wrappers.

    """
    body = serializer.DumpJson(args, indent=False)

    return self._proc(node_list, procedure, body, read_timeout=timeout)

  @staticmethod
  def _BlockdevFindPostProc(result):
    if not result.fail_msg and result.payload is not None:
      result.payload = objects.BlockDevStatus.FromDict(result.payload)
    return result

  @staticmethod
  def _BlockdevGetMirrorStatusPostProc(result):
    if not result.fail_msg:
      result.payload = [objects.BlockDevStatus.FromDict(i)
                        for i in result.payload]
    return result

  @staticmethod
  def _BlockdevGetMirrorStatusMultiPostProc(result):
    for nres in result.values():
      if nres.fail_msg:
        continue

      for idx, (success, status) in enumerate(nres.payload):
        if success:
          nres.payload[idx] = (success, objects.BlockDevStatus.FromDict(status))

    return result

  @staticmethod
  def _OsGetPostProc(result):
    if not result.fail_msg and isinstance(result.payload, dict):
      result.payload = objects.OS.FromDict(result.payload)
    return result

  @staticmethod
  def _PrepareFinalizeExportDisks(snap_disks):
    flat_disks = []

    for disk in snap_disks:
      if isinstance(disk, bool):
        flat_disks.append(disk)
      else:
        flat_disks.append(disk.ToDict())

    return flat_disks

  @staticmethod
  def _ImpExpStatusPostProc(result):
    """Post-processor for import/export status.

    @rtype: Payload containing list of L{objects.ImportExportStatus} instances
    @return: Returns a list of the state of each named import/export or None if
             a status couldn't be retrieved

    """
    if not result.fail_msg:
      decoded = []

      for i in result.payload:
        if i is None:
          decoded.append(None)
          continue
        decoded.append(objects.ImportExportStatus.FromDict(i))

      result.payload = decoded

    return result

  @staticmethod
  def _EncodeImportExportIO(ieio, ieioargs):
    """Encodes import/export I/O information.

    """
    if ieio == constants.IEIO_RAW_DISK:
      assert len(ieioargs) == 1
      return (ieioargs[0].ToDict(), )

    if ieio == constants.IEIO_SCRIPT:
      assert len(ieioargs) == 2
      return (ieioargs[0].ToDict(), ieioargs[1])

    return ieioargs

  @staticmethod
  def _PrepareFileUpload(filename):
    """Loads a file and prepares it for an upload to nodes.

    """
    data = _Compress(utils.ReadFile(filename))
    st = os.stat(filename)
    getents = runtime.GetEnts()
    return [filename, data, st.st_mode, getents.LookupUid(st.st_uid),
            getents.LookupGid(st.st_gid), st.st_atime, st.st_mtime]

  #
  # Begin RPC calls
  #

  def call_test_delay(self, node_list, duration, read_timeout=None):
    """Sleep for a fixed time on given node(s).

    This is a multi-node call.

    """
    assert read_timeout is None
    return self.call_test_delay(node_list, duration,
                                read_timeout=int(duration + 5))


class JobQueueRunner(_generated_rpc.RpcClientJobQueue):
  """RPC wrappers for job queue.

  """
  _Compress = staticmethod(_Compress)

  def __init__(self, context, address_list):
    """Initializes this class.

    """
    _generated_rpc.RpcClientJobQueue.__init__(self)

    if address_list is None:
      resolver = _SsconfResolver
    else:
      # Caller provided an address list
      resolver = _StaticResolver(address_list)

    self._proc = _RpcProcessor(resolver,
                               netutils.GetDaemonPort(constants.NODED),
                               lock_monitor_cb=context.glm.AddToLockMonitor)

  def _Call(self, node_list, procedure, timeout, args):
    """Entry point for automatically generated RPC wrappers.

    """
    body = serializer.DumpJson(args, indent=False)

    return self._proc(node_list, procedure, body, read_timeout=timeout)


class BootstrapRunner(_generated_rpc.RpcClientBootstrap):
  """RPC wrappers for bootstrapping.

  """
  def __init__(self):
    """Initializes this class.

    """
    _generated_rpc.RpcClientBootstrap.__init__(self)

    self._proc = _RpcProcessor(_SsconfResolver,
                               netutils.GetDaemonPort(constants.NODED))

  def _Call(self, node_list, procedure, timeout, args):
    """Entry point for automatically generated RPC wrappers.

    """
    body = serializer.DumpJson(args, indent=False)

    return self._proc(node_list, procedure, body, read_timeout=timeout)


class ConfigRunner(_generated_rpc.RpcClientConfig):
  """RPC wrappers for L{config}.

  """
  _PrepareFileUpload = \
    staticmethod(RpcRunner._PrepareFileUpload) # pylint: disable=W0212

  def __init__(self, address_list):
    """Initializes this class.

    """
    _generated_rpc.RpcClientConfig.__init__(self)

    if address_list is None:
      resolver = _SsconfResolver
    else:
      # Caller provided an address list
      resolver = _StaticResolver(address_list)

    self._proc = _RpcProcessor(resolver,
                               netutils.GetDaemonPort(constants.NODED))

  def _Call(self, node_list, procedure, timeout, args):
    """Entry point for automatically generated RPC wrappers.

    """
    body = serializer.DumpJson(args, indent=False)

    return self._proc(node_list, procedure, body, read_timeout=timeout)
