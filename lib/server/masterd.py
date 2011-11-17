#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Master daemon program.

Some classes deviates from the standard style guide since the
inheritance from parent classes requires it.

"""

# pylint: disable=C0103
# C0103: Invalid name ganeti-masterd

import grp
import os
import pwd
import sys
import socket
import time
import tempfile
import logging

from optparse import OptionParser

from ganeti import config
from ganeti import constants
from ganeti import daemon
from ganeti import mcpu
from ganeti import opcodes
from ganeti import jqueue
from ganeti import locking
from ganeti import luxi
from ganeti import utils
from ganeti import errors
from ganeti import ssconf
from ganeti import workerpool
from ganeti import rpc
from ganeti import bootstrap
from ganeti import netutils
from ganeti import objects
from ganeti import query


CLIENT_REQUEST_WORKERS = 16

EXIT_NOTMASTER = constants.EXIT_NOTMASTER
EXIT_NODESETUP_ERROR = constants.EXIT_NODESETUP_ERROR


class ClientRequestWorker(workerpool.BaseWorker):
  # pylint: disable=W0221
  def RunTask(self, server, message, client):
    """Process the request.

    """
    client_ops = ClientOps(server)

    try:
      (method, args, version) = luxi.ParseRequest(message)
    except luxi.ProtocolError, err:
      logging.error("Protocol Error: %s", err)
      client.close_log()
      return

    success = False
    try:
      # Verify client's version if there was one in the request
      if version is not None and version != constants.LUXI_VERSION:
        raise errors.LuxiError("LUXI version mismatch, server %s, request %s" %
                               (constants.LUXI_VERSION, version))

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
      reply = luxi.FormatResponse(success, result)
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


class _MasterShutdownCheck:
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

  def setup_queue(self):
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


class ClientOps:
  """Class holding high-level client operations."""
  def __init__(self, server):
    self.server = server

  def handle_request(self, method, args): # pylint: disable=R0911
    queue = self.server.context.jobqueue

    # TODO: Parameter validation
    if not isinstance(args, (tuple, list)):
      logging.info("Received invalid arguments of type '%s'", type(args))
      raise ValueError("Invalid arguments type '%s'" % type(args))

    # TODO: Rewrite to not exit in each 'if/elif' branch

    if method == luxi.REQ_SUBMIT_JOB:
      logging.info("Received new job")
      ops = [opcodes.OpCode.LoadOpCode(state) for state in args]
      return queue.SubmitJob(ops)

    if method == luxi.REQ_SUBMIT_MANY_JOBS:
      logging.info("Received multiple jobs")
      jobs = []
      for ops in args:
        jobs.append([opcodes.OpCode.LoadOpCode(state) for state in ops])
      return queue.SubmitManyJobs(jobs)

    elif method == luxi.REQ_CANCEL_JOB:
      (job_id, ) = args
      logging.info("Received job cancel request for %s", job_id)
      return queue.CancelJob(job_id)

    elif method == luxi.REQ_ARCHIVE_JOB:
      (job_id, ) = args
      logging.info("Received job archive request for %s", job_id)
      return queue.ArchiveJob(job_id)

    elif method == luxi.REQ_AUTOARCHIVE_JOBS:
      (age, timeout) = args
      logging.info("Received job autoarchive request for age %s, timeout %s",
                   age, timeout)
      return queue.AutoArchiveJobs(age, timeout)

    elif method == luxi.REQ_WAIT_FOR_JOB_CHANGE:
      (job_id, fields, prev_job_info, prev_log_serial, timeout) = args
      logging.info("Received job poll request for %s", job_id)
      return queue.WaitForJobChanges(job_id, fields, prev_job_info,
                                     prev_log_serial, timeout)

    elif method == luxi.REQ_QUERY:
      (what, fields, qfilter) = args
      req = objects.QueryRequest(what=what, fields=fields, qfilter=qfilter)

      if req.what in constants.QR_VIA_OP:
        result = self._Query(opcodes.OpQuery(what=req.what, fields=req.fields,
                                             qfilter=req.qfilter))
      elif req.what == constants.QR_LOCK:
        if req.qfilter is not None:
          raise errors.OpPrereqError("Lock queries can't be filtered")
        return self.server.context.glm.QueryLocks(req.fields)
      elif req.what in constants.QR_VIA_LUXI:
        raise NotImplementedError
      else:
        raise errors.OpPrereqError("Resource type '%s' unknown" % req.what,
                                   errors.ECODE_INVAL)

      return result

    elif method == luxi.REQ_QUERY_FIELDS:
      (what, fields) = args
      req = objects.QueryFieldsRequest(what=what, fields=fields)

      try:
        fielddefs = query.ALL_FIELDS[req.what]
      except KeyError:
        raise errors.OpPrereqError("Resource type '%s' unknown" % req.what,
                                   errors.ECODE_INVAL)

      return query.QueryFields(fielddefs, req.fields)

    elif method == luxi.REQ_QUERY_JOBS:
      (job_ids, fields) = args
      if isinstance(job_ids, (tuple, list)) and job_ids:
        msg = utils.CommaJoin(job_ids)
      else:
        msg = str(job_ids)
      logging.info("Received job query request for %s", msg)
      return queue.QueryJobs(job_ids, fields)

    elif method == luxi.REQ_QUERY_INSTANCES:
      (names, fields, use_locking) = args
      logging.info("Received instance query request for %s", names)
      if use_locking:
        raise errors.OpPrereqError("Sync queries are not allowed",
                                   errors.ECODE_INVAL)
      op = opcodes.OpInstanceQuery(names=names, output_fields=fields,
                                   use_locking=use_locking)
      return self._Query(op)

    elif method == luxi.REQ_QUERY_NODES:
      (names, fields, use_locking) = args
      logging.info("Received node query request for %s", names)
      if use_locking:
        raise errors.OpPrereqError("Sync queries are not allowed",
                                   errors.ECODE_INVAL)
      op = opcodes.OpNodeQuery(names=names, output_fields=fields,
                               use_locking=use_locking)
      return self._Query(op)

    elif method == luxi.REQ_QUERY_GROUPS:
      (names, fields, use_locking) = args
      logging.info("Received group query request for %s", names)
      if use_locking:
        raise errors.OpPrereqError("Sync queries are not allowed",
                                   errors.ECODE_INVAL)
      op = opcodes.OpGroupQuery(names=names, output_fields=fields)
      return self._Query(op)

    elif method == luxi.REQ_QUERY_EXPORTS:
      (nodes, use_locking) = args
      if use_locking:
        raise errors.OpPrereqError("Sync queries are not allowed",
                                   errors.ECODE_INVAL)
      logging.info("Received exports query request")
      op = opcodes.OpBackupQuery(nodes=nodes, use_locking=use_locking)
      return self._Query(op)

    elif method == luxi.REQ_QUERY_CONFIG_VALUES:
      (fields, ) = args
      logging.info("Received config values query request for %s", fields)
      op = opcodes.OpClusterConfigQuery(output_fields=fields)
      return self._Query(op)

    elif method == luxi.REQ_QUERY_CLUSTER_INFO:
      logging.info("Received cluster info query request")
      op = opcodes.OpClusterQuery()
      return self._Query(op)

    elif method == luxi.REQ_QUERY_TAGS:
      (kind, name) = args
      logging.info("Received tags query request")
      op = opcodes.OpTagsGet(kind=kind, name=name)
      return self._Query(op)

    elif method == luxi.REQ_QUERY_LOCKS:
      (fields, sync) = args
      logging.info("Received locks query request")
      if sync:
        raise NotImplementedError("Synchronous queries are not implemented")
      return self.server.context.glm.OldStyleQueryLocks(fields)

    elif method == luxi.REQ_QUEUE_SET_DRAIN_FLAG:
      (drain_flag, ) = args
      logging.info("Received queue drain flag change request to %s",
                   drain_flag)
      return queue.SetDrainFlag(drain_flag)

    elif method == luxi.REQ_SET_WATCHER_PAUSE:
      (until, ) = args

      if until is None:
        logging.info("Received request to no longer pause the watcher")
      else:
        if not isinstance(until, (int, float)):
          raise TypeError("Duration must be an integer or float")

        if until < time.time():
          raise errors.GenericError("Unable to set pause end time in the past")

        logging.info("Received request to pause the watcher until %s", until)

      return _SetWatcherPause(until)

    else:
      logging.info("Received invalid request '%s'", method)
      raise ValueError("Invalid operation '%s'" % method)

  def _Query(self, op):
    """Runs the specified opcode and returns the result.

    """
    # Queries don't have a job id
    proc = mcpu.Processor(self.server.context, None)

    # TODO: Executing an opcode using locks will acquire them in blocking mode.
    # Consider using a timeout for retries.
    return proc.ExecOpCode(op, None)


class GanetiContext(object):
  """Context common to all ganeti threads.

  This class creates and holds common objects shared by all threads.

  """
  # pylint: disable=W0212
  # we do want to ensure a singleton here
  _instance = None

  def __init__(self):
    """Constructs a new GanetiContext object.

    There should be only a GanetiContext object at any time, so this
    function raises an error if this is not the case.

    """
    assert self.__class__._instance is None, "double GanetiContext instance"

    # Create global configuration object
    self.cfg = config.ConfigWriter()

    # Locking manager
    self.glm = locking.GanetiLockManager(
                self.cfg.GetNodeList(),
                self.cfg.GetNodeGroupList(),
                self.cfg.GetInstanceList())

    self.cfg.SetContext(self)

    # RPC runner
    self.rpc = rpc.RpcRunner(self)

    # Job queue
    self.jobqueue = jqueue.JobQueue(self)

    # setting this also locks the class against attribute modifications
    self.__class__._instance = self

  def __setattr__(self, name, value):
    """Setting GanetiContext attributes is forbidden after initialization.

    """
    assert self.__class__._instance is None, "Attempt to modify Ganeti Context"
    object.__setattr__(self, name, value)

  def AddNode(self, node, ec_id):
    """Adds a node to the configuration and lock manager.

    """
    # Add it to the configuration
    self.cfg.AddNode(node, ec_id)

    # If preseeding fails it'll not be added
    self.jobqueue.AddNode(node)

    # Add the new node to the Ganeti Lock Manager
    self.glm.add(locking.LEVEL_NODE, node.name)
    self.glm.add(locking.LEVEL_NODE_RES, node.name)

  def ReaddNode(self, node):
    """Updates a node that's already in the configuration

    """
    # Synchronize the queue again
    self.jobqueue.AddNode(node)

  def RemoveNode(self, name):
    """Removes a node from the configuration and lock manager.

    """
    # Remove node from configuration
    self.cfg.RemoveNode(name)

    # Notify job queue
    self.jobqueue.RemoveNode(name)

    # Remove the node from the Ganeti Lock Manager
    self.glm.remove(locking.LEVEL_NODE, name)
    self.glm.remove(locking.LEVEL_NODE_RES, name)


def _SetWatcherPause(until):
  """Creates or removes the watcher pause file.

  @type until: None or int
  @param until: Unix timestamp saying until when the watcher shouldn't run

  """
  if until is None:
    utils.RemoveFile(constants.WATCHER_PAUSEFILE)
  else:
    utils.WriteFile(constants.WATCHER_PAUSEFILE,
                    data="%d\n" % (until, ))

  return until


@rpc.RunWithRPC
def CheckAgreement():
  """Check the agreement on who is the master.

  The function uses a very simple algorithm: we must get more positive
  than negative answers. Since in most of the cases we are the master,
  we'll use our own config file for getting the node list. In the
  future we could collect the current node list from our (possibly
  obsolete) known nodes.

  In order to account for cold-start of all nodes, we retry for up to
  a minute until we get a real answer as the top-voted one. If the
  nodes are more out-of-sync, for now manual startup of the master
  should be attempted.

  Note that for a even number of nodes cluster, we need at least half
  of the nodes (beside ourselves) to vote for us. This creates a
  problem on two-node clusters, since in this case we require the
  other node to be up too to confirm our status.

  """
  myself = netutils.Hostname.GetSysName()
  #temp instantiation of a config writer, used only to get the node list
  cfg = config.ConfigWriter()
  node_list = cfg.GetNodeList()
  del cfg
  retries = 6
  while retries > 0:
    votes = bootstrap.GatherMasterVotes(node_list)
    if not votes:
      # empty node list, this is a one node cluster
      return True
    if votes[0][0] is None:
      retries -= 1
      time.sleep(10)
      continue
    break
  if retries == 0:
    logging.critical("Cluster inconsistent, most of the nodes didn't answer"
                     " after multiple retries. Aborting startup")
    logging.critical("Use the --no-voting option if you understand what"
                     " effects it has on the cluster state")
    return False
  # here a real node is at the top of the list
  all_votes = sum(item[1] for item in votes)
  top_node, top_votes = votes[0]

  result = False
  if top_node != myself:
    logging.critical("It seems we are not the master (top-voted node"
                     " is %s with %d out of %d votes)", top_node, top_votes,
                     all_votes)
  elif top_votes < all_votes - top_votes:
    logging.critical("It seems we are not the master (%d votes for,"
                     " %d votes against)", top_votes, all_votes - top_votes)
  else:
    result = True

  return result


@rpc.RunWithRPC
def ActivateMasterIP():
  # activate ip
  cfg = config.ConfigWriter()
  master_params = cfg.GetMasterNetworkParameters()
  ems = cfg.GetUseExternalMipScript()
  runner = rpc.BootstrapRunner()
  result = runner.call_node_activate_master_ip(master_params.name,
                                               master_params, ems)

  msg = result.fail_msg
  if msg:
    logging.error("Can't activate master IP address: %s", msg)


def CheckMasterd(options, args):
  """Initial checks whether to run or exit with a failure.

  """
  if args: # masterd doesn't take any arguments
    print >> sys.stderr, ("Usage: %s [-f] [-d]" % sys.argv[0])
    sys.exit(constants.EXIT_FAILURE)

  ssconf.CheckMaster(options.debug)

  try:
    options.uid = pwd.getpwnam(constants.MASTERD_USER).pw_uid
    options.gid = grp.getgrnam(constants.DAEMONS_GROUP).gr_gid
  except KeyError:
    print >> sys.stderr, ("User or group not existing on system: %s:%s" %
                          (constants.MASTERD_USER, constants.DAEMONS_GROUP))
    sys.exit(constants.EXIT_FAILURE)

  # Check the configuration is sane before anything else
  try:
    config.ConfigWriter()
  except errors.ConfigVersionMismatch, err:
    v1 = "%s.%s.%s" % constants.SplitVersion(err.args[0])
    v2 = "%s.%s.%s" % constants.SplitVersion(err.args[1])
    print >> sys.stderr,  \
        ("Configuration version mismatch. The current Ganeti software"
         " expects version %s, but the on-disk configuration file has"
         " version %s. This is likely the result of upgrading the"
         " software without running the upgrade procedure. Please contact"
         " your cluster administrator or complete the upgrade using the"
         " cfgupgrade utility, after reading the upgrade notes." %
         (v1, v2))
    sys.exit(constants.EXIT_FAILURE)
  except errors.ConfigurationError, err:
    print >> sys.stderr, \
        ("Configuration error while opening the configuration file: %s\n"
         "This might be caused by an incomplete software upgrade or"
         " by a corrupted configuration file. Until the problem is fixed"
         " the master daemon cannot start." % str(err))
    sys.exit(constants.EXIT_FAILURE)

  # If CheckMaster didn't fail we believe we are the master, but we have to
  # confirm with the other nodes.
  if options.no_voting:
    if not options.yes_do_it:
      sys.stdout.write("The 'no voting' option has been selected.\n")
      sys.stdout.write("This is dangerous, please confirm by"
                       " typing uppercase 'yes': ")
      sys.stdout.flush()

      confirmation = sys.stdin.readline().strip()
      if confirmation != "YES":
        print >> sys.stderr, "Aborting."
        sys.exit(constants.EXIT_FAILURE)

  else:
    # CheckAgreement uses RPC and threads, hence it needs to be run in
    # a separate process before we call utils.Daemonize in the current
    # process.
    if not utils.RunInSeparateProcess(CheckAgreement):
      sys.exit(constants.EXIT_FAILURE)

  # ActivateMasterIP also uses RPC/threads, so we run it again via a
  # separate process.

  # TODO: decide whether failure to activate the master IP is a fatal error
  utils.RunInSeparateProcess(ActivateMasterIP)


def PrepMasterd(options, _):
  """Prep master daemon function, executed with the PID file held.

  """
  # This is safe to do as the pid file guarantees against
  # concurrent execution.
  utils.RemoveFile(constants.MASTER_SOCKET)

  mainloop = daemon.Mainloop()
  master = MasterServer(constants.MASTER_SOCKET, options.uid, options.gid)
  return (mainloop, master)


def ExecMasterd(options, args, prep_data): # pylint: disable=W0613
  """Main master daemon function, executed with the PID file held.

  """
  (mainloop, master) = prep_data
  try:
    rpc.Init()
    try:
      master.setup_queue()
      try:
        mainloop.Run(shutdown_wait_fn=master.WaitForShutdown)
      finally:
        master.server_cleanup()
    finally:
      rpc.Shutdown()
  finally:
    utils.RemoveFile(constants.MASTER_SOCKET)

  logging.info("Clean master daemon shutdown")


def Main():
  """Main function"""
  parser = OptionParser(description="Ganeti master daemon",
                        usage="%prog [-f] [-d]",
                        version="%%prog (ganeti) %s" %
                        constants.RELEASE_VERSION)
  parser.add_option("--no-voting", dest="no_voting",
                    help="Do not check that the nodes agree on this node"
                    " being the master and start the daemon unconditionally",
                    default=False, action="store_true")
  parser.add_option("--yes-do-it", dest="yes_do_it",
                    help="Override interactive check for --no-voting",
                    default=False, action="store_true")
  daemon.GenericMain(constants.MASTERD, parser, CheckMasterd, PrepMasterd,
                     ExecMasterd, multithreaded=True)
