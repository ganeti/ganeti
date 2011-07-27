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


"""Tool to restart erroneously downed virtual machines.

This program and set of classes implement a watchdog to restart
virtual machines in a Ganeti cluster that have crashed or been killed
by a node reboot.  Run from cron or similar.

"""

import os
import os.path
import sys
import time
import logging
from optparse import OptionParser

from ganeti import utils
from ganeti import constants
from ganeti import compat
from ganeti import errors
from ganeti import opcodes
from ganeti import cli
from ganeti import luxi
from ganeti import rapi
from ganeti import netutils

import ganeti.rapi.client # pylint: disable-msg=W0611

from ganeti.watcher import nodemaint
from ganeti.watcher import state


MAXTRIES = 5
BAD_STATES = [constants.INSTST_ERRORDOWN]
HELPLESS_STATES = [constants.INSTST_NODEDOWN, constants.INSTST_NODEOFFLINE]
NOTICE = 'NOTICE'
ERROR = 'ERROR'


# Global LUXI client object
client = None


class NotMasterError(errors.GenericError):
  """Exception raised when this host is not the master."""


def ShouldPause():
  """Check whether we should pause.

  """
  return bool(utils.ReadWatcherPauseFile(constants.WATCHER_PAUSEFILE))


def StartNodeDaemons():
  """Start all the daemons that should be running on all nodes.

  """
  # on master or not, try to start the node daemon
  utils.EnsureDaemon(constants.NODED)
  # start confd as well. On non candidates it will be in disabled mode.
  utils.EnsureDaemon(constants.CONFD)


def RunWatcherHooks():
  """Run the watcher hooks.

  """
  hooks_dir = utils.PathJoin(constants.HOOKS_BASE_DIR,
                             constants.HOOKS_NAME_WATCHER)
  if not os.path.isdir(hooks_dir):
    return

  try:
    results = utils.RunParts(hooks_dir)
  except Exception: # pylint: disable-msg=W0703
    logging.exception("RunParts %s failed: %s", hooks_dir)
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


class Instance(object):
  """Abstraction for a Virtual Machine instance.

  """
  def __init__(self, name, status, autostart, snodes):
    self.name = name
    self.status = status
    self.autostart = autostart
    self.snodes = snodes

  def Restart(self):
    """Encapsulates the start of an instance.

    """
    op = opcodes.OpInstanceStartup(instance_name=self.name, force=False)
    cli.SubmitOpCode(op, cl=client)

  def ActivateDisks(self):
    """Encapsulates the activation of all disks of an instance.

    """
    op = opcodes.OpInstanceActivateDisks(instance_name=self.name)
    cli.SubmitOpCode(op, cl=client)


def GetClusterData():
  """Get a list of instances on this cluster.

  """
  op1_fields = ["name", "status", "admin_state", "snodes"]
  op1 = opcodes.OpInstanceQuery(output_fields=op1_fields, names=[],
                                use_locking=True)
  op2_fields = ["name", "bootid", "offline"]
  op2 = opcodes.OpNodeQuery(output_fields=op2_fields, names=[],
                            use_locking=True)

  job_id = client.SubmitJob([op1, op2])

  all_results = cli.PollJob(job_id, cl=client, feedback_fn=logging.debug)

  logging.debug("Got data from cluster, writing instance status file")

  result = all_results[0]
  smap = {}

  instances = {}

  # write the instance status file
  up_data = "".join(["%s %s\n" % (fields[0], fields[1]) for fields in result])
  utils.WriteFile(file_name=constants.INSTANCE_STATUS_FILE, data=up_data)

  for fields in result:
    (name, status, autostart, snodes) = fields

    # update the secondary node map
    for node in snodes:
      if node not in smap:
        smap[node] = []
      smap[node].append(name)

    instances[name] = Instance(name, status, autostart, snodes)

  nodes =  dict([(name, (bootid, offline))
                 for name, bootid, offline in all_results[1]])

  client.ArchiveJob(job_id)

  return instances, nodes, smap


class Watcher(object):
  """Encapsulate the logic for restarting erroneously halted virtual machines.

  The calling program should periodically instantiate me and call Run().
  This will traverse the list of instances, and make up to MAXTRIES attempts
  to restart machines that are down.

  """
  def __init__(self, opts, notepad):
    self.notepad = notepad
    master = client.QueryConfigValues(["master_node"])[0]
    if master != netutils.Hostname.GetSysName():
      raise NotMasterError("This is not the master node")
    # first archive old jobs
    self.ArchiveJobs(opts.job_age)
    # and only then submit new ones
    self.instances, self.bootids, self.smap = GetClusterData()
    self.started_instances = set()
    self.opts = opts

  def Run(self):
    """Watcher run sequence.

    """
    notepad = self.notepad
    self.CheckInstances(notepad)
    self.CheckDisks(notepad)
    self.VerifyDisks()

  @staticmethod
  def ArchiveJobs(age):
    """Archive old jobs.

    """
    arch_count, left_count = client.AutoArchiveJobs(age)
    logging.debug("Archived %s jobs, left %s", arch_count, left_count)

  def CheckDisks(self, notepad):
    """Check all nodes for restarted ones.

    """
    check_nodes = []
    for name, (new_id, offline) in self.bootids.iteritems():
      old = notepad.GetNodeBootID(name)
      if new_id is None:
        # Bad node, not returning a boot id
        if not offline:
          logging.debug("Node %s missing boot id, skipping secondary checks",
                        name)
        continue
      if old != new_id:
        # Node's boot ID has changed, proably through a reboot.
        check_nodes.append(name)

    if check_nodes:
      # Activate disks for all instances with any of the checked nodes as a
      # secondary node.
      for node in check_nodes:
        if node not in self.smap:
          continue
        for instance_name in self.smap[node]:
          instance = self.instances[instance_name]
          if not instance.autostart:
            logging.info(("Skipping disk activation for non-autostart"
                          " instance %s"), instance.name)
            continue
          if instance.name in self.started_instances:
            # we already tried to start the instance, which should have
            # activated its drives (if they can be at all)
            logging.debug("Skipping disk activation for instance %s, as"
                          " it was already started", instance.name)
            continue
          try:
            logging.info("Activating disks for instance %s", instance.name)
            instance.ActivateDisks()
          except Exception: # pylint: disable-msg=W0703
            logging.exception("Error while activating disks for instance %s",
                              instance.name)

      # Keep changed boot IDs
      for name in check_nodes:
        notepad.SetNodeBootID(name, self.bootids[name][0])

  def CheckInstances(self, notepad):
    """Make a pass over the list of instances, restarting downed ones.

    """
    notepad.MaintainInstanceList(self.instances.keys())

    for instance in self.instances.values():
      if instance.status in BAD_STATES:
        n = notepad.NumberOfRestartAttempts(instance)

        if n > MAXTRIES:
          logging.warning("Not restarting instance %s, retries exhausted",
                          instance.name)
          continue
        elif n < MAXTRIES:
          last = " (Attempt #%d)" % (n + 1)
        else:
          notepad.RecordRestartAttempt(instance)
          logging.error("Could not restart %s after %d attempts, giving up",
                        instance.name, MAXTRIES)
          continue
        try:
          logging.info("Restarting %s%s", instance.name, last)
          instance.Restart()
          self.started_instances.add(instance.name)
        except Exception: # pylint: disable-msg=W0703
          logging.exception("Error while restarting instance %s",
                            instance.name)

        notepad.RecordRestartAttempt(instance)
      elif instance.status in HELPLESS_STATES:
        if notepad.NumberOfRestartAttempts(instance):
          notepad.RemoveInstance(instance)
      else:
        if notepad.NumberOfRestartAttempts(instance):
          notepad.RemoveInstance(instance)
          logging.info("Restart of %s succeeded", instance.name)

  def _CheckForOfflineNodes(self, instance):
    """Checks if given instances has any secondary in offline status.

    @param instance: The instance object
    @return: True if any of the secondary is offline, False otherwise

    """
    bootids = []
    for node in instance.snodes:
      bootids.append(self.bootids[node])

    return compat.any(offline for (_, offline) in bootids)

  def VerifyDisks(self):
    """Run gnt-cluster verify-disks.

    """
    job_id = client.SubmitJob([opcodes.OpClusterVerifyDisks()])
    result = cli.PollJob(job_id, cl=client, feedback_fn=logging.debug)[0]
    client.ArchiveJob(job_id)

    # Keep track of submitted jobs
    jex = cli.JobExecutor(cl=client, feedback_fn=logging.debug)

    archive_jobs = set()
    for (status, job_id) in result[constants.JOB_IDS_KEY]:
      jex.AddJobId(None, status, job_id)
      if status:
        archive_jobs.add(job_id)

    offline_disk_instances = set()

    for (status, result) in jex.GetResults():
      if not status:
        logging.error("Verify-disks job failed: %s", result)
        continue

      ((_, instances, _), ) = result

      offline_disk_instances.update(instances)

    for job_id in archive_jobs:
      client.ArchiveJob(job_id)

    if not offline_disk_instances:
      # nothing to do
      logging.debug("verify-disks reported no offline disks, nothing to do")
      return

    logging.debug("Will activate disks for instance(s) %s",
                  utils.CommaJoin(offline_disk_instances))

    # we submit only one job, and wait for it. not optimal, but spams
    # less the job queue
    job = []
    for name in offline_disk_instances:
      instance = self.instances[name]
      if (instance.status in HELPLESS_STATES or
          self._CheckForOfflineNodes(instance)):
        logging.info("Skip instance %s because it is in helpless state or has"
                     " one offline secondary", name)
        continue
      job.append(opcodes.OpInstanceActivateDisks(instance_name=name))

    if job:
      job_id = cli.SendJob(job, cl=client)

      try:
        cli.PollJob(job_id, cl=client, feedback_fn=logging.debug)
      except Exception: # pylint: disable-msg=W0703
        logging.exception("Error while activating disks")


def IsRapiResponding(hostname):
  """Connects to RAPI port and does a simple test.

  Connects to RAPI port of hostname and does a simple test. At this time, the
  test is GetVersion.

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
  except rapi.client.CertificateError, err:
    logging.warning("RAPI Error: CertificateError (%s)", err)
    return False
  except rapi.client.GanetiApiError, err:
    logging.warning("RAPI Error: GanetiApiError (%s)", err)
    return False
  logging.debug("RAPI Result: master_version is %s", master_version)
  return master_version == constants.RAPI_VERSION


def ParseOptions():
  """Parse the command line options.

  @return: (options, args) as from OptionParser.parse_args()

  """
  parser = OptionParser(description="Ganeti cluster watcher",
                        usage="%prog [-d]",
                        version="%%prog (ganeti) %s" %
                        constants.RELEASE_VERSION)

  parser.add_option(cli.DEBUG_OPT)
  parser.add_option("-A", "--job-age", dest="job_age", default=6 * 3600,
                    help="Autoarchive jobs older than this age (default"
                          " 6 hours)")
  parser.add_option("--ignore-pause", dest="ignore_pause", default=False,
                    action="store_true", help="Ignore cluster pause setting")
  options, args = parser.parse_args()
  options.job_age = cli.ParseTimespec(options.job_age)

  if args:
    parser.error("No arguments expected")

  return (options, args)


@rapi.client.UsesRapiClient
def Main():
  """Main function.

  """
  global client # pylint: disable-msg=W0603

  (options, _) = ParseOptions()

  utils.SetupLogging(constants.LOG_WATCHER, sys.argv[0],
                     debug=options.debug, stderr_logging=options.debug)

  if ShouldPause() and not options.ignore_pause:
    logging.debug("Pause has been set, exiting")
    return constants.EXIT_SUCCESS

  statefile = \
    state.OpenStateFile(constants.WATCHER_STATEFILE)
  if not statefile:
    return constants.EXIT_FAILURE

  update_file = False
  try:
    StartNodeDaemons()
    RunWatcherHooks()
    # run node maintenance in all cases, even if master, so that old
    # masters can be properly cleaned up too
    if nodemaint.NodeMaintenance.ShouldRun():
      nodemaint.NodeMaintenance().Exec()

    notepad = state.WatcherState(statefile)
    try:
      try:
        client = cli.GetClient()
      except errors.OpPrereqError:
        # this is, from cli.GetClient, a not-master case
        logging.debug("Not on master, exiting")
        update_file = True
        return constants.EXIT_SUCCESS
      except luxi.NoMasterError, err:
        logging.warning("Master seems to be down (%s), trying to restart",
                        str(err))
        if not utils.EnsureDaemon(constants.MASTERD):
          logging.critical("Can't start the master, exiting")
          return constants.EXIT_FAILURE
        # else retry the connection
        client = cli.GetClient()

      # we are on master now
      utils.EnsureDaemon(constants.RAPI)

      # If RAPI isn't responding to queries, try one restart.
      logging.debug("Attempting to talk with RAPI.")
      if not IsRapiResponding(constants.IP4_ADDRESS_LOCALHOST):
        logging.warning("Couldn't get answer from Ganeti RAPI daemon."
                        " Restarting Ganeti RAPI.")
        utils.StopDaemon(constants.RAPI)
        utils.EnsureDaemon(constants.RAPI)
        logging.debug("Second attempt to talk with RAPI")
        if not IsRapiResponding(constants.IP4_ADDRESS_LOCALHOST):
          logging.fatal("RAPI is not responding. Please investigate.")
      logging.debug("Successfully talked to RAPI.")

      try:
        watcher = Watcher(options, notepad)
      except errors.ConfigurationError:
        # Just exit if there's no configuration
        update_file = True
        return constants.EXIT_SUCCESS

      watcher.Run()
      update_file = True

    finally:
      if update_file:
        notepad.Save()
      else:
        logging.debug("Not updating status file due to failure")
  except SystemExit:
    raise
  except NotMasterError:
    logging.debug("Not master, exiting")
    return constants.EXIT_NOTMASTER
  except errors.ResolverError, err:
    logging.error("Cannot resolve hostname '%s', exiting.", err.args[0])
    return constants.EXIT_NODESETUP_ERROR
  except errors.JobQueueFull:
    logging.error("Job queue is full, can't query cluster state")
  except errors.JobQueueDrainError:
    logging.error("Job queue is drained, can't maintain cluster state")
  except Exception, err:
    logging.exception(str(err))
    return constants.EXIT_FAILURE

  return constants.EXIT_SUCCESS
