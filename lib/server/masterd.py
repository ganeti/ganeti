#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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


"""Master daemon program.

Some classes deviates from the standard style guide since the
inheritance from parent classes requires it.

"""

# pylint: disable=C0103
# C0103: Invalid name ganeti-masterd

import os
import sys
import socket
import time
import tempfile
import logging


from ganeti import config
from ganeti import constants
from ganeti import daemon
from ganeti import jqueue
from ganeti import luxi
import ganeti.rpc.errors as rpcerr
from ganeti import utils
from ganeti import errors
from ganeti import workerpool
import ganeti.rpc.node as rpc
import ganeti.rpc.client as rpccl
from ganeti import ht


CLIENT_REQUEST_WORKERS = 16

EXIT_NOTMASTER = constants.EXIT_NOTMASTER
EXIT_NODESETUP_ERROR = constants.EXIT_NODESETUP_ERROR


def _LogNewJob(status, info, ops):
  """Log information about a recently submitted job.

  """
  op_summary = utils.CommaJoin(op.Summary() for op in ops)

  if status:
    logging.info("New job with id %s, summary: %s", info, op_summary)
  else:
    logging.info("Failed to submit job, reason: '%s', summary: %s",
                 info, op_summary)


class ClientRequestWorker(workerpool.BaseWorker):
  # pylint: disable=W0221
  def RunTask(self, server, message, client):
    """Process the request.

    """
    client_ops = ClientOps(server)

    try:
      (method, args, ver) = rpccl.ParseRequest(message)
    except rpcerr.ProtocolError, err:
      logging.error("Protocol Error: %s", err)
      client.close_log()
      return

    success = False
    try:
      # Verify client's version if there was one in the request
      if ver is not None and ver != constants.LUXI_VERSION:
        raise errors.LuxiError("LUXI version mismatch, server %s, request %s" %
                               (constants.LUXI_VERSION, ver))

      result = client_ops.handle_request(method, args)
      success = True
    except errors.GenericError, err:
      logging.exception("Unexpected exception")
      success = False
      result = errors.EncodeException(err)
    except:
      logging.exception("Unexpected exception")
      err = sys.exc_info()
      result = "Caught exception: %s" % str(err[1])

    try:
      reply = rpccl.FormatResponse(success, result)
      client.send_message(reply)
      # awake the main thread so that it can write out the data.
      server.awaker.signal()
    except: # pylint: disable=W0702
      logging.exception("Send error")
      client.close_log()


class MasterClientHandler(daemon.AsyncTerminatedMessageStream):
  """Handler for master peers.

  """
  _MAX_UNHANDLED = 1

  def __init__(self, server, connected_socket, client_address, family):
    daemon.AsyncTerminatedMessageStream.__init__(self, connected_socket,
                                                 client_address,
                                                 constants.LUXI_EOM,
                                                 family, self._MAX_UNHANDLED)
    self.server = server

  def handle_message(self, message, _):
    self.server.request_workers.AddTask((self.server, message, self))


class _MasterShutdownCheck(object):
  """Logic for master daemon shutdown.

  """
  #: How long to wait between checks
  _CHECK_INTERVAL = 5.0

  #: How long to wait after all jobs are done (e.g. to give clients time to
  #: retrieve the job status)
  _SHUTDOWN_LINGER = 5.0

  def __init__(self):
    """Initializes this class.

    """
    self._had_active_jobs = None
    self._linger_timeout = None

  def __call__(self, jq_prepare_result):
    """Determines if master daemon is ready for shutdown.

    @param jq_prepare_result: Result of L{jqueue.JobQueue.PrepareShutdown}
    @rtype: None or number
    @return: None if master daemon is ready, timeout if the check must be
             repeated

    """
    if jq_prepare_result:
      # Check again shortly
      logging.info("Job queue has been notified for shutdown but is still"
                   " busy; next check in %s seconds", self._CHECK_INTERVAL)
      self._had_active_jobs = True
      return self._CHECK_INTERVAL

    if not self._had_active_jobs:
      # Can shut down as there were no active jobs on the first check
      return None

    # No jobs are running anymore, but maybe some clients want to collect some
    # information. Give them a short amount of time.
    if self._linger_timeout is None:
      self._linger_timeout = utils.RunningTimeout(self._SHUTDOWN_LINGER, True)

    remaining = self._linger_timeout.Remaining()

    logging.info("Job queue no longer busy; shutting down master daemon"
                 " in %s seconds", remaining)

    # TODO: Should the master daemon socket be closed at this point? Doing so
    # wouldn't affect existing connections.

    if remaining < 0:
      return None
    else:
      return remaining


class MasterServer(daemon.AsyncStreamServer):
  """Master Server.

  This is the main asynchronous master server. It handles connections to the
  master socket.

  """
  family = socket.AF_UNIX

  def __init__(self, address, uid, gid):
    """MasterServer constructor

    @param address: the unix socket address to bind the MasterServer to
    @param uid: The uid of the owner of the socket
    @param gid: The gid of the owner of the socket

    """
    temp_name = tempfile.mktemp(dir=os.path.dirname(address))
    daemon.AsyncStreamServer.__init__(self, self.family, temp_name)
    os.chmod(temp_name, 0770)
    os.chown(temp_name, uid, gid)
    os.rename(temp_name, address)

    self.awaker = daemon.AsyncAwaker()

    # We'll only start threads once we've forked.
    self.context = None
    self.request_workers = None

    self._shutdown_check = None

  def handle_connection(self, connected_socket, client_address):
    # TODO: add connection count and limit the number of open connections to a
    # maximum number to avoid breaking for lack of file descriptors or memory.
    MasterClientHandler(self, connected_socket, client_address, self.family)

  def setup_context(self):
    self.context = GanetiContext()
    self.request_workers = workerpool.WorkerPool("ClientReq",
                                                 CLIENT_REQUEST_WORKERS,
                                                 ClientRequestWorker)

  def WaitForShutdown(self):
    """Prepares server for shutdown.

    """
    if self._shutdown_check is None:
      self._shutdown_check = _MasterShutdownCheck()

    return self._shutdown_check(self.context.jobqueue.PrepareShutdown())

  def server_cleanup(self):
    """Cleanup the server.

    This involves shutting down the processor threads and the master
    socket.

    """
    try:
      self.close()
    finally:
      if self.request_workers:
        self.request_workers.TerminateWorkers()
      if self.context:
        self.context.jobqueue.Shutdown()
        self.context.livelock.close()


class ClientOps(object):
  """Class holding high-level client operations."""
  def __init__(self, server):
    self.server = server

  @staticmethod
  def _PickupJob(args, queue):
    logging.info("Picking up new job from queue")
    (job_id, ) = args
    queue.PickupJob(job_id)
    return job_id

  @staticmethod
  def _ChangeJobPriority(args, queue):
    (job_id, priority) = args
    logging.info("Received request to change priority for job %s to %s",
                 job_id, priority)
    return queue.ChangeJobPriority(job_id, priority)

  def handle_request(self, method, args): # pylint: disable=R0911
    context = self.server.context
    queue = context.jobqueue

    # TODO: Parameter validation
    if not isinstance(args, (tuple, list)):
      logging.info("Received invalid arguments of type '%s'", type(args))
      raise ValueError("Invalid arguments type '%s'" % type(args))

    if method not in luxi.REQ_ALL:
      logging.info("Received invalid request '%s'", method)
      raise ValueError("Invalid operation '%s'" % method)

    job_id = None
    if method == luxi.REQ_PICKUP_JOB:
      job_id = self._PickupJob(args, queue)
    elif method == luxi.REQ_CHANGE_JOB_PRIORITY:
      job_id = self._ChangeJobPriority(args, queue)
    else:
      logging.info("Request '%s' not supported by masterd", method)
      raise ValueError("Unsupported operation '%s'" % method)

    return job_id


class GanetiContext(object):
  """Context common to all ganeti threads.

  This class creates and holds common objects shared by all threads.

  """
  # pylint: disable=W0212
  # we do want to ensure a singleton here
  _instance = None

  def __init__(self, livelock=None):
    """Constructs a new GanetiContext object.

    There should be only a GanetiContext object at any time, so this
    function raises an error if this is not the case.

    """
    assert self.__class__._instance is None, "double GanetiContext instance"

    # Create a livelock file
    if livelock is None:
      self.livelock = utils.livelock.LiveLock("masterd")
    else:
      self.livelock = livelock

    # Job queue
    cfg = self.GetConfig(None)
    logging.debug("Creating the job queue")
    self.jobqueue = jqueue.JobQueue(self, cfg)

    # setting this also locks the class against attribute modifications
    self.__class__._instance = self

  def __setattr__(self, name, value):
    """Setting GanetiContext attributes is forbidden after initialization.

    """
    assert self.__class__._instance is None, "Attempt to modify Ganeti Context"
    object.__setattr__(self, name, value)

  def GetWConfdContext(self, ec_id):
    return config.GetWConfdContext(ec_id, self.livelock)

  def GetConfig(self, ec_id):
    return config.GetConfig(ec_id, self.livelock)

  # pylint: disable=R0201
  # method could be a function, but keep interface backwards compatible
  def GetRpc(self, cfg):
    return rpc.RpcRunner(cfg, lambda _: None)

  def AddNode(self, cfg, node, ec_id):
    """Adds a node to the configuration.

    """
    # Add it to the configuration
    cfg.AddNode(node, ec_id)

    # If preseeding fails it'll not be added
    self.jobqueue.AddNode(node)

  def ReaddNode(self, node):
    """Updates a node that's already in the configuration

    """
    # Synchronize the queue again
    self.jobqueue.AddNode(node)

  def RemoveNode(self, cfg, node):
    """Removes a node from the configuration and lock manager.

    """
    # Remove node from configuration
    cfg.RemoveNode(node.uuid)

    # Notify job queue
    self.jobqueue.RemoveNode(node.name)


def _SetWatcherPause(context, ec_id, until):
  """Creates or removes the watcher pause file.

  @type context: L{GanetiContext}
  @param context: Global Ganeti context
  @type until: None or int
  @param until: Unix timestamp saying until when the watcher shouldn't run

  """
  node_names = context.GetConfig(ec_id).GetNodeList()

  if until is None:
    logging.info("Received request to no longer pause watcher")
  else:
    if not ht.TNumber(until):
      raise TypeError("Duration must be numeric")

    if until < time.time():
      raise errors.GenericError("Unable to set pause end time in the past")

    logging.info("Received request to pause watcher until %s", until)

  result = context.rpc.call_set_watcher_pause(node_names, until)

  errmsg = utils.CommaJoin("%s (%s)" % (node_name, nres.fail_msg)
                           for (node_name, nres) in result.items()
                           if nres.fail_msg and not nres.offline)
  if errmsg:
    raise errors.OpExecError("Watcher pause was set where possible, but failed"
                             " on the following node(s): %s" % errmsg)

  return until
