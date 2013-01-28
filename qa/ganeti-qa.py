#!/usr/bin/python -u
#

# Copyright (C) 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Script for doing QA on Ganeti.

"""

# pylint: disable=C0103
# due to invalid name

import sys
import datetime
import optparse

import qa_cluster
import qa_config
import qa_daemon
import qa_env
import qa_error
import qa_group
import qa_instance
import qa_node
import qa_os
import qa_job
import qa_rapi
import qa_tags
import qa_utils

from ganeti import utils
from ganeti import rapi # pylint: disable=W0611
from ganeti import constants

import ganeti.rapi.client # pylint: disable=W0611
from ganeti.rapi.client import UsesRapiClient


def _FormatHeader(line, end=72):
  """Fill a line up to the end column.

  """
  line = "---- " + line + " "
  line += "-" * (end - len(line))
  line = line.rstrip()
  return line


def _DescriptionOf(fn):
  """Computes the description of an item.

  """
  if fn.__doc__:
    desc = fn.__doc__.splitlines()[0].strip()
  else:
    desc = "%r" % fn

  return desc.rstrip(".")


def RunTest(fn, *args, **kwargs):
  """Runs a test after printing a header.

  """

  tstart = datetime.datetime.now()

  desc = _DescriptionOf(fn)

  print
  print _FormatHeader("%s start %s" % (tstart, desc))

  try:
    retval = fn(*args, **kwargs)
    return retval
  finally:
    tstop = datetime.datetime.now()
    tdelta = tstop - tstart
    print _FormatHeader("%s time=%s %s" % (tstop, tdelta, desc))


def RunTestIf(testnames, fn, *args, **kwargs):
  """Runs a test conditionally.

  @param testnames: either a single test name in the configuration
      file, or a list of testnames (which will be AND-ed together)

  """
  if qa_config.TestEnabled(testnames):
    RunTest(fn, *args, **kwargs)
  else:
    tstart = datetime.datetime.now()
    desc = _DescriptionOf(fn)
    print _FormatHeader("%s skipping %s, test(s) %s disabled" %
                        (tstart, desc, testnames))


def RunEnvTests():
  """Run several environment tests.

  """
  RunTestIf("env", qa_env.TestSshConnection)
  RunTestIf("env", qa_env.TestIcmpPing)
  RunTestIf("env", qa_env.TestGanetiCommands)


def SetupCluster(rapi_user, rapi_secret):
  """Initializes the cluster.

  @param rapi_user: Login user for RAPI
  @param rapi_secret: Login secret for RAPI

  """
  RunTestIf("create-cluster", qa_cluster.TestClusterInit,
            rapi_user, rapi_secret)
  if not qa_config.TestEnabled("create-cluster"):
    # If the cluster is already in place, we assume that exclusive-storage is
    # already set according to the configuration
    qa_config.SetExclusiveStorage(qa_config.get("exclusive-storage", False))

  # Test on empty cluster
  RunTestIf("node-list", qa_node.TestNodeList)
  RunTestIf("instance-list", qa_instance.TestInstanceList)
  RunTestIf("job-list", qa_job.TestJobList)

  RunTestIf("create-cluster", qa_node.TestNodeAddAll)
  if not qa_config.TestEnabled("create-cluster"):
    # consider the nodes are already there
    qa_node.MarkNodeAddedAll()

  RunTestIf("test-jobqueue", qa_cluster.TestJobqueue)

  # enable the watcher (unconditionally)
  RunTest(qa_daemon.TestResumeWatcher)

  RunTestIf("node-list", qa_node.TestNodeList)

  # Test listing fields
  RunTestIf("node-list", qa_node.TestNodeListFields)
  RunTestIf("instance-list", qa_instance.TestInstanceListFields)
  RunTestIf("job-list", qa_job.TestJobListFields)
  RunTestIf("instance-export", qa_instance.TestBackupListFields)

  RunTestIf("node-info", qa_node.TestNodeInfo)


def RunClusterTests():
  """Runs tests related to gnt-cluster.

  """
  for test, fn in [
    ("create-cluster", qa_cluster.TestClusterInitDisk),
    ("cluster-renew-crypto", qa_cluster.TestClusterRenewCrypto),
    ("cluster-verify", qa_cluster.TestClusterVerify),
    ("cluster-reserved-lvs", qa_cluster.TestClusterReservedLvs),
    # TODO: add more cluster modify tests
    ("cluster-modify", qa_cluster.TestClusterModifyEmpty),
    ("cluster-modify", qa_cluster.TestClusterModifyBe),
    ("cluster-modify", qa_cluster.TestClusterModifyDisk),
    ("cluster-rename", qa_cluster.TestClusterRename),
    ("cluster-info", qa_cluster.TestClusterVersion),
    ("cluster-info", qa_cluster.TestClusterInfo),
    ("cluster-info", qa_cluster.TestClusterGetmaster),
    ("cluster-redist-conf", qa_cluster.TestClusterRedistConf),
    ("cluster-copyfile", qa_cluster.TestClusterCopyfile),
    ("cluster-command", qa_cluster.TestClusterCommand),
    ("cluster-burnin", qa_cluster.TestClusterBurnin),
    ("cluster-master-failover", qa_cluster.TestClusterMasterFailover),
    ("cluster-master-failover",
     qa_cluster.TestClusterMasterFailoverWithDrainedQueue),
    ("cluster-oob", qa_cluster.TestClusterOob),
    ("rapi", qa_rapi.TestVersion),
    ("rapi", qa_rapi.TestEmptyCluster),
    ("rapi", qa_rapi.TestRapiQuery),
    ]:
    RunTestIf(test, fn)


def RunRepairDiskSizes():
  """Run the repair disk-sizes test.

  """
  RunTestIf("cluster-repair-disk-sizes", qa_cluster.TestClusterRepairDiskSizes)


def RunOsTests():
  """Runs all tests related to gnt-os.

  """
  if qa_config.TestEnabled("rapi"):
    rapi_getos = qa_rapi.GetOperatingSystems
  else:
    rapi_getos = None

  for fn in [
    qa_os.TestOsList,
    qa_os.TestOsDiagnose,
    ]:
    RunTestIf("os", fn)

  for fn in [
    qa_os.TestOsValid,
    qa_os.TestOsInvalid,
    qa_os.TestOsPartiallyValid,
    ]:
    RunTestIf("os", fn, rapi_getos)

  for fn in [
    qa_os.TestOsModifyValid,
    qa_os.TestOsModifyInvalid,
    qa_os.TestOsStatesNonExisting,
    ]:
    RunTestIf("os", fn)


def RunCommonInstanceTests(instance):
  """Runs a few tests that are common to all disk types.

  """
  RunTestIf("instance-shutdown", qa_instance.TestInstanceShutdown, instance)
  RunTestIf(["instance-shutdown", "instance-console", "rapi"],
            qa_rapi.TestRapiStoppedInstanceConsole, instance)
  RunTestIf(["instance-shutdown", "instance-modify"],
            qa_instance.TestInstanceStoppedModify, instance)
  RunTestIf("instance-shutdown", qa_instance.TestInstanceStartup, instance)

  # Test shutdown/start via RAPI
  RunTestIf(["instance-shutdown", "rapi"],
            qa_rapi.TestRapiInstanceShutdown, instance)
  RunTestIf(["instance-shutdown", "rapi"],
            qa_rapi.TestRapiInstanceStartup, instance)

  RunTestIf("instance-list", qa_instance.TestInstanceList)

  RunTestIf("instance-info", qa_instance.TestInstanceInfo, instance)

  RunTestIf("instance-modify", qa_instance.TestInstanceModify, instance)
  RunTestIf(["instance-modify", "rapi"],
            qa_rapi.TestRapiInstanceModify, instance)

  RunTestIf("instance-console", qa_instance.TestInstanceConsole, instance)
  RunTestIf(["instance-console", "rapi"],
            qa_rapi.TestRapiInstanceConsole, instance)

  DOWN_TESTS = qa_config.Either([
    "instance-reinstall",
    "instance-rename",
    "instance-grow-disk",
    ])

  # shutdown instance for any 'down' tests
  RunTestIf(DOWN_TESTS, qa_instance.TestInstanceShutdown, instance)

  # now run the 'down' state tests
  RunTestIf("instance-reinstall", qa_instance.TestInstanceReinstall, instance)
  RunTestIf(["instance-reinstall", "rapi"],
            qa_rapi.TestRapiInstanceReinstall, instance)

  if qa_config.TestEnabled("instance-rename"):
    tgt_instance = qa_config.AcquireInstance()
    try:
      rename_source = instance["name"]
      rename_target = tgt_instance["name"]
      # perform instance rename to the same name
      RunTest(qa_instance.TestInstanceRenameAndBack,
              rename_source, rename_source)
      RunTestIf("rapi", qa_rapi.TestRapiInstanceRenameAndBack,
                rename_source, rename_source)
      if rename_target is not None:
        # perform instance rename to a different name, if we have one configured
        RunTest(qa_instance.TestInstanceRenameAndBack,
                rename_source, rename_target)
        RunTestIf("rapi", qa_rapi.TestRapiInstanceRenameAndBack,
                  rename_source, rename_target)
    finally:
      qa_config.ReleaseInstance(tgt_instance)

  RunTestIf(["instance-grow-disk"], qa_instance.TestInstanceGrowDisk, instance)

  # and now start the instance again
  RunTestIf(DOWN_TESTS, qa_instance.TestInstanceStartup, instance)

  RunTestIf("instance-reboot", qa_instance.TestInstanceReboot, instance)

  RunTestIf("tags", qa_tags.TestInstanceTags, instance)

  RunTestIf("cluster-verify", qa_cluster.TestClusterVerify)

  RunTestIf("rapi", qa_rapi.TestInstance, instance)

  # Lists instances, too
  RunTestIf("node-list", qa_node.TestNodeList)

  # Some jobs have been run, let's test listing them
  RunTestIf("job-list", qa_job.TestJobList)


def RunCommonNodeTests():
  """Run a few common node tests.

  """
  RunTestIf("node-volumes", qa_node.TestNodeVolumes)
  RunTestIf("node-storage", qa_node.TestNodeStorage)
  RunTestIf("node-oob", qa_node.TestOutOfBand)


def RunGroupListTests():
  """Run tests for listing node groups.

  """
  RunTestIf("group-list", qa_group.TestGroupList)
  RunTestIf("group-list", qa_group.TestGroupListFields)


def RunGroupRwTests():
  """Run tests for adding/removing/renaming groups.

  """
  RunTestIf("group-rwops", qa_group.TestGroupAddRemoveRename)
  RunTestIf("group-rwops", qa_group.TestGroupAddWithOptions)
  RunTestIf("group-rwops", qa_group.TestGroupModify)
  RunTestIf(["group-rwops", "rapi"], qa_rapi.TestRapiNodeGroups)
  RunTestIf(["group-rwops", "tags"], qa_tags.TestGroupTags,
            qa_group.GetDefaultGroup())


def RunExportImportTests(instance, inodes):
  """Tries to export and import the instance.

  @type inodes: list of nodes
  @param inodes: current nodes of the instance

  """
  if qa_config.TestEnabled("instance-export"):
    RunTest(qa_instance.TestInstanceExportNoTarget, instance)

    pnode = inodes[0]
    expnode = qa_config.AcquireNode(exclude=pnode)
    try:
      name = RunTest(qa_instance.TestInstanceExport, instance, expnode)

      RunTest(qa_instance.TestBackupList, expnode)

      if qa_config.TestEnabled("instance-import"):
        newinst = qa_config.AcquireInstance()
        try:
          RunTest(qa_instance.TestInstanceImport, newinst, pnode,
                  expnode, name)
          # Check if starting the instance works
          RunTest(qa_instance.TestInstanceStartup, newinst)
          RunTest(qa_instance.TestInstanceRemove, newinst)
        finally:
          qa_config.ReleaseInstance(newinst)
    finally:
      qa_config.ReleaseNode(expnode)

  if qa_config.TestEnabled(["rapi", "inter-cluster-instance-move"]):
    newinst = qa_config.AcquireInstance()
    try:
      tnode = qa_config.AcquireNode(exclude=inodes)
      try:
        RunTest(qa_rapi.TestInterClusterInstanceMove, instance, newinst,
                inodes, tnode)
      finally:
        qa_config.ReleaseNode(tnode)
    finally:
      qa_config.ReleaseInstance(newinst)


def RunDaemonTests(instance):
  """Test the ganeti-watcher script.

  """
  RunTest(qa_daemon.TestPauseWatcher)

  RunTestIf("instance-automatic-restart",
            qa_daemon.TestInstanceAutomaticRestart, instance)
  RunTestIf("instance-consecutive-failures",
            qa_daemon.TestInstanceConsecutiveFailures, instance)

  RunTest(qa_daemon.TestResumeWatcher)


def RunHardwareFailureTests(instance, inodes):
  """Test cluster internal hardware failure recovery.

  """
  RunTestIf("instance-failover", qa_instance.TestInstanceFailover, instance)
  RunTestIf(["instance-failover", "rapi"],
            qa_rapi.TestRapiInstanceFailover, instance)

  RunTestIf("instance-migrate", qa_instance.TestInstanceMigrate, instance)
  RunTestIf(["instance-migrate", "rapi"],
            qa_rapi.TestRapiInstanceMigrate, instance)

  if qa_config.TestEnabled("instance-replace-disks"):
    # We just need alternative secondary nodes, hence "- 1"
    othernodes = qa_config.AcquireManyNodes(len(inodes) - 1, exclude=inodes)
    try:
      RunTestIf("rapi", qa_rapi.TestRapiInstanceReplaceDisks, instance)
      RunTest(qa_instance.TestReplaceDisks,
              instance, inodes, othernodes)
    finally:
      qa_config.ReleaseManyNodes(othernodes)
    del othernodes

  if qa_config.TestEnabled("instance-recreate-disks"):
    try:
      acquirednodes = qa_config.AcquireManyNodes(len(inodes), exclude=inodes)
      othernodes = acquirednodes
    except qa_error.OutOfNodesError:
      if len(inodes) > 1:
        # If the cluster is not big enough, let's reuse some of the nodes, but
        # with different roles. In this way, we can test a DRBD instance even on
        # a 3-node cluster.
        acquirednodes = [qa_config.AcquireNode(exclude=inodes)]
        othernodes = acquirednodes + inodes[:-1]
      else:
        raise
    try:
      RunTest(qa_instance.TestRecreateDisks,
              instance, inodes, othernodes)
    finally:
      qa_config.ReleaseManyNodes(acquirednodes)

  if len(inodes) >= 2:
    RunTestIf("node-evacuate", qa_node.TestNodeEvacuate, inodes[0], inodes[1])
    RunTestIf("node-failover", qa_node.TestNodeFailover, inodes[0], inodes[1])


def RunExclusiveStorageTests():
  """Test exclusive storage."""
  if not qa_config.TestEnabled("cluster-exclusive-storage"):
    return

  node = qa_config.AcquireNode()
  try:
    old_es = qa_cluster.TestSetExclStorCluster(False)
    qa_cluster.TestExclStorSingleNode(node)

    qa_cluster.TestSetExclStorCluster(True)
    qa_cluster.TestExclStorSharedPv(node)

    if qa_config.TestEnabled("instance-add-plain-disk"):
      # Make sure that the cluster doesn't have any pre-existing problem
      qa_cluster.AssertClusterVerify()
      instance1 = qa_instance.TestInstanceAddWithPlainDisk([node])
      instance2 = qa_instance.TestInstanceAddWithPlainDisk([node])
      # cluster-verify checks that disks are allocated correctly
      qa_cluster.AssertClusterVerify()
      qa_instance.TestInstanceRemove(instance1)
      qa_instance.TestInstanceRemove(instance2)
    if qa_config.TestEnabled("instance-add-drbd-disk"):
      snode = qa_config.AcquireNode()
      try:
        qa_cluster.TestSetExclStorCluster(False)
        instance = qa_instance.TestInstanceAddWithDrbdDisk([node, snode])
        qa_cluster.TestSetExclStorCluster(True)
        exp_err = [constants.CV_EINSTANCEUNSUITABLENODE]
        qa_cluster.AssertClusterVerify(fail=True, errors=exp_err)
        qa_instance.TestInstanceRemove(instance)
      finally:
        qa_config.ReleaseNode(snode)
    qa_cluster.TestSetExclStorCluster(old_es)
  finally:
    qa_config.ReleaseNode(node)


def RunInstanceTests():
  """Create and exercise instances."""
  instance_tests = [
    ("instance-add-plain-disk", constants.DT_PLAIN,
     qa_instance.TestInstanceAddWithPlainDisk, 1),
    ("instance-add-drbd-disk", constants.DT_DRBD8,
     qa_instance.TestInstanceAddWithDrbdDisk, 2),
  ]

  for (test_name, templ, create_fun, num_nodes) in instance_tests:
    if (qa_config.TestEnabled(test_name) and
        qa_config.IsTemplateSupported(templ)):
      inodes = qa_config.AcquireManyNodes(num_nodes)
      try:
        instance = RunTest(create_fun, inodes)

        RunTestIf("cluster-epo", qa_cluster.TestClusterEpo)
        RunDaemonTests(instance)
        for node in inodes:
          RunTestIf("haskell-confd", qa_node.TestNodeListDrbd, node)
        if len(inodes) > 1:
          RunTestIf("group-rwops", qa_group.TestAssignNodesIncludingSplit,
                    constants.INITIAL_NODE_GROUP_NAME,
                    inodes[0]["primary"], inodes[1]["primary"])
        if qa_config.TestEnabled("instance-convert-disk"):
          RunTest(qa_instance.TestInstanceShutdown, instance)
          RunTest(qa_instance.TestInstanceConvertDiskToPlain, instance, inodes)
          RunTest(qa_instance.TestInstanceStartup, instance)
        RunCommonInstanceTests(instance)
        RunGroupListTests()
        RunExportImportTests(instance, inodes)
        RunHardwareFailureTests(instance, inodes)
        RunRepairDiskSizes()
        RunTest(qa_instance.TestInstanceRemove, instance)
        del instance
      finally:
        qa_config.ReleaseManyNodes(inodes)
      qa_cluster.AssertClusterVerify()


def RunQa():
  """Main QA body.

  """
  rapi_user = "ganeti-qa"
  rapi_secret = utils.GenerateSecret()

  RunEnvTests()
  SetupCluster(rapi_user, rapi_secret)

  # Load RAPI certificate
  qa_rapi.Setup(rapi_user, rapi_secret)

  RunClusterTests()
  RunOsTests()

  RunTestIf("tags", qa_tags.TestClusterTags)

  RunCommonNodeTests()
  RunGroupListTests()
  RunGroupRwTests()

  # The master shouldn't be readded or put offline; "delay" needs a non-master
  # node to test
  pnode = qa_config.AcquireNode(exclude=qa_config.GetMasterNode())
  try:
    RunTestIf("node-readd", qa_node.TestNodeReadd, pnode)
    RunTestIf("node-modify", qa_node.TestNodeModify, pnode)
    RunTestIf("delay", qa_cluster.TestDelay, pnode)
  finally:
    qa_config.ReleaseNode(pnode)

  # Make sure the cluster is clean before running instance tests
  qa_cluster.AssertClusterVerify()

  pnode = qa_config.AcquireNode()
  try:
    RunTestIf("tags", qa_tags.TestNodeTags, pnode)

    if qa_rapi.Enabled():
      RunTest(qa_rapi.TestNode, pnode)

      if qa_config.TestEnabled("instance-add-plain-disk"):
        for use_client in [True, False]:
          rapi_instance = RunTest(qa_rapi.TestRapiInstanceAdd, pnode,
                                  use_client)
          if qa_config.TestEnabled("instance-plain-rapi-common-tests"):
            RunCommonInstanceTests(rapi_instance)
          RunTest(qa_rapi.TestRapiInstanceRemove, rapi_instance, use_client)
          del rapi_instance

  finally:
    qa_config.ReleaseNode(pnode)

  config_list = [
    ("default-instance-tests", lambda: None, lambda _: None),
    ("exclusive-storage-instance-tests",
     lambda: qa_cluster.TestSetExclStorCluster(True),
     qa_cluster.TestSetExclStorCluster),
  ]
  for (conf_name, setup_conf_f, restore_conf_f) in config_list:
    if qa_config.TestEnabled(conf_name):
      oldconf = setup_conf_f()
      RunInstanceTests()
      restore_conf_f(oldconf)

  pnode = qa_config.AcquireNode()
  try:
    if qa_config.TestEnabled(["instance-add-plain-disk", "instance-export"]):
      for shutdown in [False, True]:
        instance = RunTest(qa_instance.TestInstanceAddWithPlainDisk, [pnode])
        expnode = qa_config.AcquireNode(exclude=pnode)
        try:
          if shutdown:
            # Stop instance before exporting and removing it
            RunTest(qa_instance.TestInstanceShutdown, instance)
          RunTest(qa_instance.TestInstanceExportWithRemove, instance, expnode)
          RunTest(qa_instance.TestBackupList, expnode)
        finally:
          qa_config.ReleaseNode(expnode)
        del expnode
        del instance
      qa_cluster.AssertClusterVerify()

  finally:
    qa_config.ReleaseNode(pnode)

  RunExclusiveStorageTests()

  # Test removing instance with offline drbd secondary
  if qa_config.TestEnabled("instance-remove-drbd-offline"):
    # Make sure the master is not put offline
    snode = qa_config.AcquireNode(exclude=qa_config.GetMasterNode())
    try:
      pnode = qa_config.AcquireNode(exclude=snode)
      try:
        instance = qa_instance.TestInstanceAddWithDrbdDisk([pnode, snode])
        qa_node.MakeNodeOffline(snode, "yes")
        try:
          RunTest(qa_instance.TestInstanceRemove, instance)
        finally:
          qa_node.MakeNodeOffline(snode, "no")
      finally:
        qa_config.ReleaseNode(pnode)
    finally:
      qa_config.ReleaseNode(snode)
    # FIXME: This test leaves a DRBD device and two LVs behind
    # Cluster-verify would fail

  RunTestIf("create-cluster", qa_node.TestNodeRemoveAll)

  RunTestIf("cluster-destroy", qa_cluster.TestClusterDestroy)


@UsesRapiClient
def main():
  """Main program.

  """
  parser = optparse.OptionParser(usage="%prog [options] <config-file>")
  parser.add_option("--yes-do-it", dest="yes_do_it",
                    action="store_true",
                    help="Really execute the tests")
  (qa_config.options, args) = parser.parse_args()

  if len(args) == 1:
    (config_file, ) = args
  else:
    parser.error("Wrong number of arguments.")

  if not qa_config.options.yes_do_it:
    print ("Executing this script irreversibly destroys any Ganeti\n"
           "configuration on all nodes involved. If you really want\n"
           "to start testing, supply the --yes-do-it option.")
    sys.exit(1)

  qa_config.Load(config_file)

  primary = qa_config.GetMasterNode()["primary"]
  qa_utils.StartMultiplexer(primary)
  print ("SSH command for primary node: %s" %
         utils.ShellQuoteArgs(qa_utils.GetSSHCommand(primary, "")))
  print ("SSH command for other nodes: %s" %
         utils.ShellQuoteArgs(qa_utils.GetSSHCommand("NODE", "")))
  try:
    RunQa()
  finally:
    qa_utils.CloseMultiplexers()

if __name__ == "__main__":
  main()
