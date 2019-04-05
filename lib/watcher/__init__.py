#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Tool to restart erroneously downed virtual machines.

This program and set of classes implement a watchdog to restart
virtual machines in a Ganeti cluster that have crashed or been killed
by a node reboot.  Run from cron or similar.

"""

import os
import os.path
import sys
import signal
import time
import logging
import errno
from optparse import OptionParser

from ganeti import utils
from ganeti import wconfd
from ganeti import constants
from ganeti import compat
from ganeti import errors
from ganeti import opcodes
from ganeti import cli
import ganeti.rpc.errors as rpcerr
from ganeti import rapi
from ganeti import netutils
from ganeti import qlang
from ganeti import ssconf
from ganeti import ht
from ganeti import pathutils

import ganeti.rapi.client # pylint: disable=W0611
from ganeti.rapi.client import UsesRapiClient

from ganeti.watcher import nodemaint
from ganeti.watcher import state


MAXTRIES = 5
BAD_STATES = compat.UniqueFrozenset([
  constants.INSTST_ERRORDOWN,
  ])
HELPLESS_STATES = compat.UniqueFrozenset([
  constants.INSTST_NODEDOWN,
  constants.INSTST_NODEOFFLINE,
  ])
NOTICE = "NOTICE"
ERROR = "ERROR"

#: Number of seconds to wait between starting child processes for node groups
CHILD_PROCESS_DELAY = 1.0

#: How many seconds to wait for instance status file lock
INSTANCE_STATUS_LOCK_TIMEOUT = 10.0


class NotMasterError(errors.GenericError):
  """Exception raised when this host is not the master."""


def ShouldPause():
  """Check whether we should pause.

  """
  return bool(utils.ReadWatcherPauseFile(pathutils.WATCHER_PAUSEFILE))


def StartNodeDaemons():
  """Start all the daemons that should be running on all nodes.

  """
  # on master or not, try to start the node daemon
  utils.EnsureDaemon(constants.NODED)
  # start confd as well. On non candidates it will be in disabled mode.
  utils.EnsureDaemon(constants.CONFD)
  # start mond as well: all nodes need monitoring
  if constants.ENABLE_MOND:
    utils.EnsureDaemon(constants.MOND)
  # start kvmd, which will quit if not needed to run
  utils.EnsureDaemon(constants.KVMD)


def RunWatcherHooks():
  """Run the watcher hooks.

  """
  hooks_dir = utils.PathJoin(pathutils.HOOKS_BASE_DIR,
                             constants.HOOKS_NAME_WATCHER)
  if not os.path.isdir(hooks_dir):
    return

  try:
    results = utils.RunParts(hooks_dir)
  except Exception as err: # pylint: disable=W0703
    logging.exception("RunParts %s failed: %s", hooks_dir, err)
    return

  for (relname, status, runresult) in results:
    if status == constants.RUNPARTS_SKIP:
      logging.debug("Watcher hook %s: skipped", relname)
    elif status == constants.RUNPARTS_ERR:
      logging.warning("Watcher hook %s: error (%s)", relname, runresult)
    elif status == constants.RUNPARTS_RUN:
      if runresult.failed:
        logging.warning("Watcher hook %s: failed (exit: %d) (output: %s)",
                        relname, runresult.exit_code, runresult.output)
      else:
        logging.debug("Watcher hook %s: success (output: %s)", relname,
                      runresult.output)
    else:
      raise errors.ProgrammerError("Unknown status %s returned by RunParts",
                                   status)


class Instance(object):
  """Abstraction for a Virtual Machine instance.

  """
  def __init__(self, name, status, config_state, config_state_source,
               disks_active, snodes, disk_template):
    self.name = name
    self.status = status
    self.config_state = config_state
    self.config_state_source = config_state_source
    self.disks_active = disks_active
    self.snodes = snodes
    self.disk_template = disk_template

  def Restart(self, cl):
    """Encapsulates the start of an instance.

    """
    op = opcodes.OpInstanceStartup(instance_name=self.name, force=False)
    op.reason = [(constants.OPCODE_REASON_SRC_WATCHER,
                  "Restarting instance %s" % self.name,
                  utils.EpochNano())]
    cli.SubmitOpCode(op, cl=cl)

  def ActivateDisks(self, cl):
    """Encapsulates the activation of all disks of an instance.

    """
    op = opcodes.OpInstanceActivateDisks(instance_name=self.name)
    op.reason = [(constants.OPCODE_REASON_SRC_WATCHER,
                  "Activating disks for instance %s" % self.name,
                  utils.EpochNano())]
    cli.SubmitOpCode(op, cl=cl)

  def NeedsCleanup(self):
    """Determines whether the instance needs cleanup.

    Determines whether the instance needs cleanup after having been
    shutdown by the user.

    @rtype: bool
    @return: True if the instance needs cleanup, False otherwise.

    """
    return self.status == constants.INSTST_USERDOWN and \
        self.config_state != constants.ADMINST_DOWN


class Node(object):
  """Data container representing cluster node.

  """
  def __init__(self, name, bootid, offline, secondaries):
    """Initializes this class.

    """
    self.name = name
    self.bootid = bootid
    self.offline = offline
    self.secondaries = secondaries


def _CleanupInstance(cl, notepad, inst, locks):
  n = notepad.NumberOfCleanupAttempts(inst.name)

  if inst.name in locks:
    logging.info("Not cleaning up instance '%s', instance is locked",
                 inst.name)
    return

  if n > MAXTRIES:
    logging.warning("Not cleaning up instance '%s', retries exhausted",
                    inst.name)
    return

  logging.info("Instance '%s' was shutdown by the user, cleaning up instance",
               inst.name)
  op = opcodes.OpInstanceShutdown(instance_name=inst.name,
                                  admin_state_source=constants.USER_SOURCE)

  op.reason = [(constants.OPCODE_REASON_SRC_WATCHER,
                "Cleaning up instance %s" % inst.name,
                utils.EpochNano())]
  try:
    cli.SubmitOpCode(op, cl=cl)
    if notepad.NumberOfCleanupAttempts(inst.name):
      notepad.RemoveInstance(inst.name)
  except Exception: # pylint: disable=W0703
    logging.exception("Error while cleaning up instance '%s'", inst.name)
    notepad.RecordCleanupAttempt(inst.name)


def _CheckInstances(cl, notepad, instances, locks):
  """Make a pass over the list of instances, restarting downed ones.

  """
  notepad.MaintainInstanceList(list(instances))

  started = set()

  for inst in instances.values():
    if inst.NeedsCleanup():
      _CleanupInstance(cl, notepad, inst, locks)
    elif inst.status in BAD_STATES:
      n = notepad.NumberOfRestartAttempts(inst.name)

      if n > MAXTRIES:
        logging.warning("Not restarting instance '%s', retries exhausted",
                        inst.name)
        continue

      if n == MAXTRIES:
        notepad.RecordRestartAttempt(inst.name)
        logging.error("Could not restart instance '%s' after %s attempts,"
                      " giving up", inst.name, MAXTRIES)
        continue

      try:
        logging.info("Restarting instance '%s' (attempt #%s)",
                     inst.name, n + 1)
        inst.Restart(cl)
      except Exception: # pylint: disable=W0703
        logging.exception("Error while restarting instance '%s'", inst.name)
      else:
        started.add(inst.name)

      notepad.RecordRestartAttempt(inst.name)

    else:
      if notepad.NumberOfRestartAttempts(inst.name):
        notepad.RemoveInstance(inst.name)
        if inst.status not in HELPLESS_STATES:
          logging.info("Restart of instance '%s' succeeded", inst.name)

  return started


def _CheckDisks(cl, notepad, nodes, instances, started):
  """Check all nodes for restarted ones.

  """
  check_nodes = []

  for node in nodes.values():
    old = notepad.GetNodeBootID(node.name)
    if not node.bootid:
      # Bad node, not returning a boot id
      if not node.offline:
        logging.debug("Node '%s' missing boot ID, skipping secondary checks",
                      node.name)
      continue

    if old != node.bootid:
      # Node's boot ID has changed, probably through a reboot
      check_nodes.append(node)

  if check_nodes:
    # Activate disks for all instances with any of the checked nodes as a
    # secondary node.
    for node in check_nodes:
      for instance_name in node.secondaries:
        try:
          inst = instances[instance_name]
        except KeyError:
          logging.info("Can't find instance '%s', maybe it was ignored",
                       instance_name)
          continue

        if not inst.disks_active:
          logging.info("Skipping disk activation for instance with not"
                       " activated disks '%s'", inst.name)
          continue

        if inst.name in started:
          # we already tried to start the instance, which should have
          # activated its drives (if they can be at all)
          logging.debug("Skipping disk activation for instance '%s' as"
                        " it was already started", inst.name)
          continue

        try:
          logging.info("Activating disks for instance '%s'", inst.name)
          inst.ActivateDisks(cl)
        except Exception: # pylint: disable=W0703
          logging.exception("Error while activating disks for instance '%s'",
                            inst.name)

    # Keep changed boot IDs
    for node in check_nodes:
      notepad.SetNodeBootID(node.name, node.bootid)


def _CheckForOfflineNodes(nodes, instance):
  """Checks if given instances has any secondary in offline status.

  @param instance: The instance object
  @return: True if any of the secondary is offline, False otherwise

  """
  return compat.any(nodes[node_name].offline for node_name in instance.snodes)


def _VerifyDisks(cl, uuid, nodes, instances):
  """Run a per-group "gnt-cluster verify-disks".

  """
  op = opcodes.OpGroupVerifyDisks(
    group_name=uuid, priority=constants.OP_PRIO_LOW)
  op.reason = [(constants.OPCODE_REASON_SRC_WATCHER,
                "Verifying disks of group %s" % uuid,
                utils.EpochNano())]
  job_id = cl.SubmitJob([op])
  ((_, offline_disk_instances, _), ) = \
    cli.PollJob(job_id, cl=cl, feedback_fn=logging.debug)
  cl.ArchiveJob(job_id)

  if not offline_disk_instances:
    # nothing to do
    logging.debug("Verify-disks reported no offline disks, nothing to do")
    return

  logging.debug("Will activate disks for instance(s) %s",
                utils.CommaJoin(offline_disk_instances))

  # We submit only one job, and wait for it. Not optimal, but this puts less
  # load on the job queue.
  job = []
  for name in offline_disk_instances:
    try:
      inst = instances[name]
    except KeyError:
      logging.info("Can't find instance '%s', maybe it was ignored", name)
      continue

    if inst.status in HELPLESS_STATES or _CheckForOfflineNodes(nodes, inst):
      logging.info("Skipping instance '%s' because it is in a helpless state"
                   " or has offline secondaries", name)
      continue

    op = opcodes.OpInstanceActivateDisks(instance_name=name)
    op.reason = [(constants.OPCODE_REASON_SRC_WATCHER,
                  "Activating disks for instance %s" % name,
                  utils.EpochNano())]
    job.append(op)

  if job:
    job_id = cli.SendJob(job, cl=cl)

    try:
      cli.PollJob(job_id, cl=cl, feedback_fn=logging.debug)
    except Exception: # pylint: disable=W0703
      logging.exception("Error while activating disks")


def IsRapiResponding(hostname):
  """Connects to RAPI port and does a simple test.

  Connects to RAPI port of hostname and does a simple test. At this time, the
  test is GetVersion.

  If RAPI responds with error code "401 Unauthorized", the test is successful,
  because the aim of this function is to assess whether RAPI is responding, not
  if it is accessible.

  @type hostname: string
  @param hostname: hostname of the node to connect to.
  @rtype: bool
  @return: Whether RAPI is working properly

  """
  curl_config = rapi.client.GenericCurlConfig()
  rapi_client = rapi.client.GanetiRapiClient(hostname,
                                             curl_config_fn=curl_config)
  try:
    master_version = rapi_client.GetVersion()
  except rapi.client.CertificateError as err:
    logging.warning("RAPI certificate error: %s", err)
    return False
  except rapi.client.GanetiApiError as err:
    if err.code == 401:
      # Unauthorized, but RAPI is alive and responding
      return True
    else:
      logging.warning("RAPI error: %s", err)
      return False
  else:
    logging.debug("Reported RAPI version %s", master_version)
    return master_version == constants.RAPI_VERSION


def IsWconfdResponding():
  """Probes an echo RPC to WConfD.

  """
  probe_string = "ganeti watcher probe %d" % time.time()

  try:
    result = wconfd.Client().Echo(probe_string)
  except Exception as err: # pylint: disable=W0703
    logging.warning("WConfd connection error: %s", err)
    return False

  if result != probe_string:
    logging.warning("WConfd echo('%s') returned '%s'", probe_string, result)
    return False

  return True


def ParseOptions():
  """Parse the command line options.

  @return: (options, args) as from OptionParser.parse_args()

  """
  parser = OptionParser(description="Ganeti cluster watcher",
                        usage="%prog [-d]",
                        version="%%prog (ganeti) %s" %
                        constants.RELEASE_VERSION)

  parser.add_option(cli.DEBUG_OPT)
  parser.add_option(cli.NODEGROUP_OPT)
  parser.add_option("-A", "--job-age", dest="job_age", default=6 * 3600,
                    help="Autoarchive jobs older than this age (default"
                          " 6 hours)")
  parser.add_option("--ignore-pause", dest="ignore_pause", default=False,
                    action="store_true", help="Ignore cluster pause setting")
  parser.add_option("--wait-children", dest="wait_children",
                    action="store_true", help="Wait for child processes")
  parser.add_option("--no-wait-children", dest="wait_children",
                    action="store_false",
                    help="Don't wait for child processes")
  parser.add_option("--no-verify-disks", dest="no_verify_disks", default=False,
                    action="store_true", help="Do not verify disk status")
  parser.add_option("--rapi-ip", dest="rapi_ip",
                    default=constants.IP4_ADDRESS_LOCALHOST,
                    help="Use this IP to talk to RAPI.")
  # See optparse documentation for why default values are not set by options
  parser.set_defaults(wait_children=True)
  options, args = parser.parse_args()
  options.job_age = cli.ParseTimespec(options.job_age)

  if args:
    parser.error("No arguments expected")

  return (options, args)


def _WriteInstanceStatus(filename, data):
  """Writes the per-group instance status file.

  The entries are sorted.

  @type filename: string
  @param filename: Path to instance status file
  @type data: list of tuple; (instance name as string, status as string)
  @param data: Instance name and status

  """
  logging.debug("Updating instance status file '%s' with %s instances",
                filename, len(data))

  utils.WriteFile(filename,
                  data="\n".join("%s %s" % (n, s) for (n, s) in sorted(data)))


def _UpdateInstanceStatus(filename, instances):
  """Writes an instance status file from L{Instance} objects.

  @type filename: string
  @param filename: Path to status file
  @type instances: list of L{Instance}

  """
  _WriteInstanceStatus(filename, [(inst.name, inst.status)
                                  for inst in instances])


def _ReadInstanceStatus(filename):
  """Reads an instance status file.

  @type filename: string
  @param filename: Path to status file
  @rtype: tuple; (None or number, list of lists containing instance name and
    status)
  @return: File's mtime and instance status contained in the file; mtime is
    C{None} if file can't be read

  """
  logging.debug("Reading per-group instance status from '%s'", filename)

  statcb = utils.FileStatHelper()
  try:
    content = utils.ReadFile(filename, preread=statcb)
  except EnvironmentError as err:
    if err.errno == errno.ENOENT:
      logging.error("Can't read '%s', does not exist (yet)", filename)
    else:
      logging.exception("Unable to read '%s', ignoring", filename)
    return (None, None)
  else:
    return (statcb.st.st_mtime, [line.split(None, 1)
                                 for line in content.splitlines()])


def _MergeInstanceStatus(filename, pergroup_filename, groups):
  """Merges all per-group instance status files into a global one.

  @type filename: string
  @param filename: Path to global instance status file
  @type pergroup_filename: string
  @param pergroup_filename: Path to per-group status files, must contain "%s"
    to be replaced with group UUID
  @type groups: sequence
  @param groups: UUIDs of known groups

  """
  # Lock global status file in exclusive mode
  lock = utils.FileLock.Open(filename)
  try:
    lock.Exclusive(blocking=True, timeout=INSTANCE_STATUS_LOCK_TIMEOUT)
  except errors.LockError as err:
    # All per-group processes will lock and update the file. None of them
    # should take longer than 10 seconds (the value of
    # INSTANCE_STATUS_LOCK_TIMEOUT).
    logging.error("Can't acquire lock on instance status file '%s', not"
                  " updating: %s", filename, err)
    return

  logging.debug("Acquired exclusive lock on '%s'", filename)

  data = {}

  # Load instance status from all groups
  for group_uuid in groups:
    (mtime, instdata) = _ReadInstanceStatus(pergroup_filename % group_uuid)

    if mtime is not None:
      for (instance_name, status) in instdata:
        data.setdefault(instance_name, []).append((mtime, status))

  # Select last update based on file mtime
  inststatus = [(instance_name, sorted(status, reverse=True)[0][1])
                for (instance_name, status) in data.items()]

  # Write the global status file. Don't touch file after it's been
  # updated--there is no lock anymore.
  _WriteInstanceStatus(filename, inststatus)


def GetLuxiClient(try_restart):
  """Tries to connect to the luxi daemon.

  @type try_restart: bool
  @param try_restart: Whether to attempt to restart the master daemon

  """
  try:
    return cli.GetClient()
  except errors.OpPrereqError as err:
    # this is, from cli.GetClient, a not-master case
    raise NotMasterError("Not on master node (%s)" % err)

  except (rpcerr.NoMasterError, rpcerr.TimeoutError) as err:
    if not try_restart:
      raise

    logging.warning("Luxi daemon seems to be down (%s), trying to restart",
                    err)

    if not utils.EnsureDaemon(constants.LUXID):
      raise errors.GenericError("Can't start the master daemon")

    # Retry the connection
    return cli.GetClient()


def _StartGroupChildren(cl, wait):
  """Starts a new instance of the watcher for every node group.

  """
  assert not compat.any(arg.startswith(cli.NODEGROUP_OPT_NAME)
                        for arg in sys.argv)

  result = cl.QueryGroups([], ["name", "uuid"], False)

  children = []

  for (idx, (name, uuid)) in enumerate(result):
    if idx > 0:
      # Let's not kill the system
      time.sleep(CHILD_PROCESS_DELAY)

    logging.debug("Spawning child for group %r (%s).", name, uuid)

    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    try:
      pid = os.fork()
    except OSError:
      logging.exception("Failed to fork for group %r (%s)", name, uuid)

    if pid == 0:
      (options, _) = ParseOptions()
      options.nodegroup = uuid
      _GroupWatcher(options)
      return
    else:
      logging.debug("Started with PID %s", pid)
      children.append(pid)

  if wait:
    for child in children:
      logging.debug("Waiting for child PID %s", child)
      try:
        result = utils.RetryOnSignal(os.waitpid, child, 0)
      except EnvironmentError as err:
        result = str(err)
      logging.debug("Child PID %s exited with status %s", child, result)


def _ArchiveJobs(cl, age):
  """Archives old jobs.

  """
  (arch_count, left_count) = cl.AutoArchiveJobs(age)
  logging.debug("Archived %s jobs, left %s", arch_count, left_count)


def _CheckMaster(cl):
  """Ensures current host is master node.

  """
  (master, ) = cl.QueryConfigValues(["master_node"])
  if master != netutils.Hostname.GetSysName():
    raise NotMasterError("This is not the master node")


@UsesRapiClient
def _GlobalWatcher(opts):
  """Main function for global watcher.

  At the end child processes are spawned for every node group.

  """
  StartNodeDaemons()
  RunWatcherHooks()

  # Run node maintenance in all cases, even if master, so that old masters can
  # be properly cleaned up
  if nodemaint.NodeMaintenance.ShouldRun(): # pylint: disable=E0602
    nodemaint.NodeMaintenance().Exec() # pylint: disable=E0602

  try:
    client = GetLuxiClient(True)
  except NotMasterError:
    # Don't proceed on non-master nodes
    return constants.EXIT_SUCCESS

  # we are on master now
  utils.EnsureDaemon(constants.RAPI)
  utils.EnsureDaemon(constants.WCONFD)

  # If RAPI isn't responding to queries, try one restart
  logging.debug("Attempting to talk to remote API on %s",
                opts.rapi_ip)
  if not IsRapiResponding(opts.rapi_ip):
    logging.warning("Couldn't get answer from remote API, restaring daemon")
    utils.StopDaemon(constants.RAPI)
    utils.EnsureDaemon(constants.RAPI)
    logging.debug("Second attempt to talk to remote API")
    if not IsRapiResponding(opts.rapi_ip):
      logging.fatal("RAPI is not responding")
  logging.debug("Successfully talked to remote API")

  # If WConfD isn't responding to queries, try one restart
  logging.debug("Attempting to talk to WConfD")
  if not IsWconfdResponding():
    logging.warning("WConfD not responsive, restarting daemon")
    utils.StopDaemon(constants.WCONFD)
    utils.EnsureDaemon(constants.WCONFD)
    logging.debug("Second attempt to talk to WConfD")
    if not IsWconfdResponding():
      logging.fatal("WConfD is not responding")

  _CheckMaster(client)
  _ArchiveJobs(client, opts.job_age)

  # Spawn child processes for all node groups
  _StartGroupChildren(client, opts.wait_children)

  return constants.EXIT_SUCCESS


def _GetGroupData(qcl, uuid):
  """Retrieves instances and nodes per node group.

  """
  locks = qcl.Query(constants.QR_LOCK, ["name", "mode"], None)

  prefix = "instance/"
  prefix_len = len(prefix)

  locked_instances = set()

  for [[_, name], [_, lock]] in locks.data:
    if name.startswith(prefix) and lock:
      locked_instances.add(name[prefix_len:])

  queries = [
      (constants.QR_INSTANCE,
       ["name", "status", "admin_state", "admin_state_source", "disks_active",
        "snodes", "pnode.group.uuid", "snodes.group.uuid", "disk_template"],
       [qlang.OP_EQUAL, "pnode.group.uuid", uuid]),
      (constants.QR_NODE,
       ["name", "bootid", "offline"],
       [qlang.OP_EQUAL, "group.uuid", uuid]),
      ]

  results_data = [
    qcl.Query(what, field, qfilter).data
    for (what, field, qfilter) in queries
  ]

  # Ensure results are tuples with two values
  assert compat.all(
      ht.TListOf(ht.TListOf(ht.TIsLength(2)))(d) for d in results_data)

  # Extract values ignoring result status
  (raw_instances, raw_nodes) = [[map(compat.snd, values)
                                 for values in res]
                                for res in results_data]

  secondaries = {}
  instances = []

  # Load all instances
  for (name, status, config_state, config_state_source, disks_active, snodes,
       pnode_group_uuid, snodes_group_uuid, disk_template) in raw_instances:
    if snodes and set([pnode_group_uuid]) != set(snodes_group_uuid):
      logging.error("Ignoring split instance '%s', primary group %s, secondary"
                    " groups %s", name, pnode_group_uuid,
                    utils.CommaJoin(snodes_group_uuid))
    else:
      instances.append(Instance(name, status, config_state, config_state_source,
                                disks_active, snodes, disk_template))

      for node in snodes:
        secondaries.setdefault(node, set()).add(name)

  # Load all nodes
  nodes = [Node(name, bootid, offline, secondaries.get(name, set()))
           for (name, bootid, offline) in raw_nodes]

  return (dict((node.name, node) for node in nodes),
          dict((inst.name, inst) for inst in instances),
          locked_instances)


def _LoadKnownGroups():
  """Returns a list of all node groups known by L{ssconf}.

  """
  groups = ssconf.SimpleStore().GetNodegroupList()

  result = list(line.split(None, 1)[0] for line in groups
                if line.strip())

  if not compat.all(utils.UUID_RE.match(r) for r in result):
    raise errors.GenericError("Ssconf contains invalid group UUID")

  return result


def _GroupWatcher(opts):
  """Main function for per-group watcher process.

  """
  group_uuid = opts.nodegroup.lower()

  if not utils.UUID_RE.match(group_uuid):
    raise errors.GenericError("Node group parameter (%s) must be given a UUID,"
                              " got '%s'" %
                              (cli.NODEGROUP_OPT_NAME, group_uuid))

  logging.info("Watcher for node group '%s'", group_uuid)

  known_groups = _LoadKnownGroups()

  # Check if node group is known
  if group_uuid not in known_groups:
    raise errors.GenericError("Node group '%s' is not known by ssconf" %
                              group_uuid)

  # Group UUID has been verified and should not contain any dangerous
  # characters
  state_path = pathutils.WATCHER_GROUP_STATE_FILE % group_uuid
  inst_status_path = pathutils.WATCHER_GROUP_INSTANCE_STATUS_FILE % group_uuid

  logging.debug("Using state file %s", state_path)

  # Global watcher
  statefile = state.OpenStateFile(state_path) # pylint: disable=E0602
  if not statefile:
    return constants.EXIT_FAILURE

  notepad = state.WatcherState(statefile) # pylint: disable=E0602
  try:
    # Connect to master daemon
    client = GetLuxiClient(False)

    _CheckMaster(client)

    (nodes, instances, locks) = _GetGroupData(client, group_uuid)

    # Update per-group instance status file
    _UpdateInstanceStatus(inst_status_path, list(instances.values()))

    _MergeInstanceStatus(pathutils.INSTANCE_STATUS_FILE,
                         pathutils.WATCHER_GROUP_INSTANCE_STATUS_FILE,
                         known_groups)

    started = _CheckInstances(client, notepad, instances, locks)
    _CheckDisks(client, notepad, nodes, instances, started)

    # Check if the nodegroup only has ext storage type
    only_ext = compat.all(i.disk_template == constants.DT_EXT
                          for i in instances.values())

    # We skip current NodeGroup verification if there are only external storage
    # devices. Currently we provide an interface for external storage provider
    # for disk verification implementations, however current ExtStorageDevice
    # does not provide an API for this yet.
    #
    # This check needs to be revisited if ES_ACTION_VERIFY on ExtStorageDevice
    # is implemented.
    if not opts.no_verify_disks and not only_ext:
      _VerifyDisks(client, group_uuid, nodes, instances)
  except Exception as err:
    logging.info("Not updating status file due to failure: %s", err)
    raise
  else:
    # Save changes for next run
    notepad.Save(state_path)

  return constants.EXIT_SUCCESS


def Main():
  """Main function.

  """
  (options, _) = ParseOptions()

  utils.SetupLogging(pathutils.LOG_WATCHER, sys.argv[0],
                     debug=options.debug, stderr_logging=options.debug)

  if ShouldPause() and not options.ignore_pause:
    logging.debug("Pause has been set, exiting")
    return constants.EXIT_SUCCESS

  # Try to acquire global watcher lock in shared mode.
  # In case we are in the global watcher process, this lock will be held by all
  # children processes (one for each nodegroup) and will only be released when
  # all of them have finished running.
  lock = utils.FileLock.Open(pathutils.WATCHER_LOCK_FILE)
  try:
    lock.Shared(blocking=False)
  except (EnvironmentError, errors.LockError) as err:
    logging.error("Can't acquire lock on %s: %s",
                  pathutils.WATCHER_LOCK_FILE, err)
    return constants.EXIT_SUCCESS
  if options.nodegroup is None:
    fn = _GlobalWatcher
  else:
    # Per-nodegroup watcher
    fn = _GroupWatcher

  try:
    return fn(options)
  except (SystemExit, KeyboardInterrupt):
    raise
  except NotMasterError:
    logging.debug("Not master, exiting")
    return constants.EXIT_NOTMASTER
  except errors.ResolverError as err:
    logging.error("Cannot resolve hostname '%s', exiting", err.args[0])
    return constants.EXIT_NODESETUP_ERROR
  except errors.JobQueueFull:
    logging.error("Job queue is full, can't query cluster state")
  except errors.JobQueueDrainError:
    logging.error("Job queue is drained, can't maintain cluster state")
  except Exception as err: # pylint: disable=W0703
    logging.exception(str(err))
    return constants.EXIT_FAILURE

  return constants.EXIT_SUCCESS
