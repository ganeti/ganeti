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

import copy
import datetime
import optparse
import sys

import colors
import qa_cluster
import qa_config
import qa_daemon
import qa_env
import qa_error
import qa_group
import qa_instance
import qa_monitoring
import qa_network
import qa_node
import qa_os
import qa_job
import qa_rapi
import qa_tags
import qa_utils

from ganeti import utils
from ganeti import rapi # pylint: disable=W0611
from ganeti import constants
from ganeti import pathutils

from ganeti.http.auth import ParsePasswordFile
import ganeti.rapi.client # pylint: disable=W0611
from ganeti.rapi.client import UsesRapiClient


def _FormatHeader(line, end=72, mark="-", color=None):
  """Fill a line up to the end column.

  """
  line = (mark * 4) + " " + line + " "
  line += "-" * (end - len(line))
  line = line.rstrip()
  line = colors.colorize(line, color)
  return line


def _DescriptionOf(fn):
  """Computes the description of an item.

  """
  if fn.__doc__:
    desc = fn.__doc__.splitlines()[0].strip()
    desc = desc.rstrip(".")
    if fn.__name__:
      desc = "[" + fn.__name__ + "] " + desc
  else:
    desc = "%r" % fn

  return desc


def RunTest(fn, *args, **kwargs):
  """Runs a test after printing a header.

  """

  tstart = datetime.datetime.now()

  desc = _DescriptionOf(fn)

  print
  print _FormatHeader("%s start %s" % (tstart, desc),
                      color=colors.YELLOW, mark="<")

  try:
    retval = fn(*args, **kwargs)
    print _FormatHeader("PASSED %s" % (desc, ), color=colors.GREEN)
    return retval
  except Exception, e:
    print _FormatHeader("FAILED %s: %s" % (desc, e), color=colors.RED)
    raise
  finally:
    tstop = datetime.datetime.now()
    tdelta = tstop - tstart
    print _FormatHeader("%s time=%s %s" % (tstop, tdelta, desc),
                        color=colors.MAGENTA, mark=">")


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
    # TODO: Formatting test names when non-string names are involved
    print _FormatHeader("%s skipping %s, test(s) %s disabled" %
                        (tstart, desc, testnames),
                        color=colors.BLUE, mark="*")


def RunEnvTests():
  """Run several environment tests.

  """
  RunTestIf("env", qa_env.TestSshConnection)
  RunTestIf("env", qa_env.TestIcmpPing)
  RunTestIf("env", qa_env.TestGanetiCommands)


def _LookupRapiSecret(rapi_user):
  """Find the RAPI secret for the given user.

  @param rapi_user: Login user
  @return: Login secret for the user

  """
  CTEXT = "{CLEARTEXT}"
  master = qa_config.GetMasterNode()
  cmd = ["cat", qa_utils.MakeNodePath(master, pathutils.RAPI_USERS_FILE)]
  file_content = qa_utils.GetCommandOutput(master.primary,
                                           utils.ShellQuoteArgs(cmd))
  users = ParsePasswordFile(file_content)
  entry = users.get(rapi_user)
  if not entry:
    raise qa_error.Error("User %s not found in RAPI users file" % rapi_user)
  secret = entry.password
  if secret.upper().startswith(CTEXT):
    secret = secret[len(CTEXT):]
  elif secret.startswith("{"):
    raise qa_error.Error("Unsupported password schema for RAPI user %s:"
                         " not a clear text password" % rapi_user)
  return secret


def SetupCluster(rapi_user):
  """Initializes the cluster.

  @param rapi_user: Login user for RAPI
  @return: Login secret for RAPI

  """
  rapi_secret = utils.GenerateSecret()
  RunTestIf("create-cluster", qa_cluster.TestClusterInit,
            rapi_user, rapi_secret)
  if not qa_config.TestEnabled("create-cluster"):
    # If the cluster is already in place, we assume that exclusive-storage is
    # already set according to the configuration
    qa_config.SetExclusiveStorage(qa_config.get("exclusive-storage", False))
    if qa_rapi.Enabled():
      # To support RAPI on an existing cluster we have to find out the secret
      rapi_secret = _LookupRapiSecret(rapi_user)

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

  return rapi_secret


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
    ("cluster-modify", qa_cluster.TestClusterModifyIPolicy),
    ("cluster-modify", qa_cluster.TestClusterModifyISpecs),
    ("cluster-modify", qa_cluster.TestClusterModifyBe),
    ("cluster-modify", qa_cluster.TestClusterModifyDisk),
    ("cluster-modify", qa_cluster.TestClusterModifyDiskTemplates),
    ("cluster-modify", qa_cluster.TestClusterModifyFileStorageDir),
    ("cluster-modify", qa_cluster.TestClusterModifySharedFileStorageDir),
    ("cluster-rename", qa_cluster.TestClusterRename),
    ("cluster-info", qa_cluster.TestClusterVersion),
    ("cluster-info", qa_cluster.TestClusterInfo),
    ("cluster-info", qa_cluster.TestClusterGetmaster),
    ("cluster-redist-conf", qa_cluster.TestClusterRedistConf),
    (["cluster-copyfile", qa_config.NoVirtualCluster],
     qa_cluster.TestClusterCopyfile),
    ("cluster-command", qa_cluster.TestClusterCommand),
    ("cluster-burnin", qa_cluster.TestClusterBurnin),
    ("cluster-master-failover", qa_cluster.TestClusterMasterFailover),
    ("cluster-master-failover",
     qa_cluster.TestClusterMasterFailoverWithDrainedQueue),
    (["cluster-oob", qa_config.NoVirtualCluster],
     qa_cluster.TestClusterOob),
    (qa_rapi.Enabled, qa_rapi.TestVersion),
    (qa_rapi.Enabled, qa_rapi.TestEmptyCluster),
    (qa_rapi.Enabled, qa_rapi.TestRapiQuery),
    ]:
    RunTestIf(test, fn)


def RunRepairDiskSizes():
  """Run the repair disk-sizes test.

  """
  RunTestIf("cluster-repair-disk-sizes", qa_cluster.TestClusterRepairDiskSizes)


def RunOsTests():
  """Runs all tests related to gnt-os.

  """
  os_enabled = ["os", qa_config.NoVirtualCluster]

  if qa_config.TestEnabled(qa_rapi.Enabled):
    rapi_getos = qa_rapi.GetOperatingSystems
  else:
    rapi_getos = None

  for fn in [
    qa_os.TestOsList,
    qa_os.TestOsDiagnose,
    ]:
    RunTestIf(os_enabled, fn)

  for fn in [
    qa_os.TestOsValid,
    qa_os.TestOsInvalid,
    qa_os.TestOsPartiallyValid,
    ]:
    RunTestIf(os_enabled, fn, rapi_getos)

  for fn in [
    qa_os.TestOsModifyValid,
    qa_os.TestOsModifyInvalid,
    qa_os.TestOsStatesNonExisting,
    ]:
    RunTestIf(os_enabled, fn)


def RunCommonInstanceTests(instance, inst_nodes):
  """Runs a few tests that are common to all disk types.

  """
  RunTestIf("instance-shutdown", qa_instance.TestInstanceShutdown, instance)
  RunTestIf(["instance-shutdown", "instance-console", qa_rapi.Enabled],
            qa_rapi.TestRapiStoppedInstanceConsole, instance)
  RunTestIf(["instance-shutdown", "instance-modify"],
            qa_instance.TestInstanceStoppedModify, instance)
  RunTestIf("instance-shutdown", qa_instance.TestInstanceStartup, instance)

  # Test shutdown/start via RAPI
  RunTestIf(["instance-shutdown", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceShutdown, instance)
  RunTestIf(["instance-shutdown", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceStartup, instance)

  RunTestIf("instance-list", qa_instance.TestInstanceList)

  RunTestIf("instance-info", qa_instance.TestInstanceInfo, instance)

  RunTestIf("instance-modify", qa_instance.TestInstanceModify, instance)
  RunTestIf(["instance-modify", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceModify, instance)

  RunTestIf("instance-console", qa_instance.TestInstanceConsole, instance)
  RunTestIf(["instance-console", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceConsole, instance)

  RunTestIf("instance-device-names", qa_instance.TestInstanceDeviceNames,
            instance)
  DOWN_TESTS = qa_config.Either([
    "instance-reinstall",
    "instance-rename",
    "instance-grow-disk",
    ])

  # shutdown instance for any 'down' tests
  RunTestIf(DOWN_TESTS, qa_instance.TestInstanceShutdown, instance)

  # now run the 'down' state tests
  RunTestIf("instance-reinstall", qa_instance.TestInstanceReinstall, instance)
  RunTestIf(["instance-reinstall", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceReinstall, instance)

  if qa_config.TestEnabled("instance-rename"):
    tgt_instance = qa_config.AcquireInstance()
    try:
      rename_source = instance.name
      rename_target = tgt_instance.name
      # perform instance rename to the same name
      RunTest(qa_instance.TestInstanceRenameAndBack,
              rename_source, rename_source)
      RunTestIf(qa_rapi.Enabled, qa_rapi.TestRapiInstanceRenameAndBack,
                rename_source, rename_source)
      if rename_target is not None:
        # perform instance rename to a different name, if we have one configured
        RunTest(qa_instance.TestInstanceRenameAndBack,
                rename_source, rename_target)
        RunTestIf(qa_rapi.Enabled, qa_rapi.TestRapiInstanceRenameAndBack,
                  rename_source, rename_target)
    finally:
      tgt_instance.Release()

  RunTestIf(["instance-grow-disk"], qa_instance.TestInstanceGrowDisk, instance)

  # and now start the instance again
  RunTestIf(DOWN_TESTS, qa_instance.TestInstanceStartup, instance)

  RunTestIf("instance-reboot", qa_instance.TestInstanceReboot, instance)

  RunTestIf("tags", qa_tags.TestInstanceTags, instance)

  if instance.disk_template == constants.DT_DRBD8:
    RunTestIf("cluster-verify",
              qa_cluster.TestClusterVerifyDisksBrokenDRBD, instance, inst_nodes)
  RunTestIf("cluster-verify", qa_cluster.TestClusterVerify)

  RunTestIf(qa_rapi.Enabled, qa_rapi.TestInstance, instance)

  # Lists instances, too
  RunTestIf("node-list", qa_node.TestNodeList)

  # Some jobs have been run, let's test listing them
  RunTestIf("job-list", qa_job.TestJobList)


def RunCommonNodeTests():
  """Run a few common node tests.

  """
  RunTestIf("node-volumes", qa_node.TestNodeVolumes)
  RunTestIf("node-storage", qa_node.TestNodeStorage)
  RunTestIf(["node-oob", qa_config.NoVirtualCluster], qa_node.TestOutOfBand)


def RunGroupListTests():
  """Run tests for listing node groups.

  """
  RunTestIf("group-list", qa_group.TestGroupList)
  RunTestIf("group-list", qa_group.TestGroupListFields)


def RunNetworkTests():
  """Run tests for network management.

  """
  RunTestIf("network", qa_network.TestNetworkAddRemove)
  RunTestIf("network", qa_network.TestNetworkConnect)


def RunGroupRwTests():
  """Run tests for adding/removing/renaming groups.

  """
  RunTestIf("group-rwops", qa_group.TestGroupAddRemoveRename)
  RunTestIf("group-rwops", qa_group.TestGroupAddWithOptions)
  RunTestIf("group-rwops", qa_group.TestGroupModify)
  RunTestIf(["group-rwops", qa_rapi.Enabled], qa_rapi.TestRapiNodeGroups)
  RunTestIf(["group-rwops", "tags"], qa_tags.TestGroupTags,
            qa_group.GetDefaultGroup())


def RunExportImportTests(instance, inodes):
  """Tries to export and import the instance.

  @type inodes: list of nodes
  @param inodes: current nodes of the instance

  """
  # FIXME: export explicitly bails out on file based storage. other non-lvm
  # based storage types are untested, though. Also note that import could still
  # work, but is deeply embedded into the "export" case.
  if (qa_config.TestEnabled("instance-export") and
      instance.disk_template not in constants.DTS_FILEBASED):
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
          newinst.Release()
    finally:
      expnode.Release()

  # FIXME: inter-cluster-instance-move crashes on file based instances :/
  # See Issue 414.
  if (qa_config.TestEnabled([qa_rapi.Enabled, "inter-cluster-instance-move"])
      and (instance.disk_template not in constants.DTS_FILEBASED)):
    newinst = qa_config.AcquireInstance()
    try:
      tnode = qa_config.AcquireNode(exclude=inodes)
      try:
        RunTest(qa_rapi.TestInterClusterInstanceMove, instance, newinst,
                inodes, tnode)
      finally:
        tnode.Release()
    finally:
      newinst.Release()


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
  RunTestIf(["instance-failover", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceFailover, instance)

  RunTestIf("instance-migrate", qa_instance.TestInstanceMigrate, instance)
  RunTestIf(["instance-migrate", qa_rapi.Enabled],
            qa_rapi.TestRapiInstanceMigrate, instance)

  if qa_config.TestEnabled("instance-replace-disks"):
    # We just need alternative secondary nodes, hence "- 1"
    othernodes = qa_config.AcquireManyNodes(len(inodes) - 1, exclude=inodes)
    try:
      RunTestIf(qa_rapi.Enabled, qa_rapi.TestRapiInstanceReplaceDisks, instance)
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
    RunTestIf("node-migrate", qa_node.TestNodeMigrate, inodes[0], inodes[1])


def RunExclusiveStorageTests():
  """Test exclusive storage."""
  if not qa_config.TestEnabled("cluster-exclusive-storage"):
    return

  node = qa_config.AcquireNode()
  try:
    old_es = qa_cluster.TestSetExclStorCluster(False)
    qa_node.TestExclStorSingleNode(node)

    qa_cluster.TestSetExclStorCluster(True)
    qa_cluster.TestExclStorSharedPv(node)

    if qa_config.TestEnabled("instance-add-plain-disk"):
      # Make sure that the cluster doesn't have any pre-existing problem
      qa_cluster.AssertClusterVerify()

      # Create and allocate instances
      instance1 = qa_instance.TestInstanceAddWithPlainDisk([node])
      try:
        instance2 = qa_instance.TestInstanceAddWithPlainDisk([node])
        try:
          # cluster-verify checks that disks are allocated correctly
          qa_cluster.AssertClusterVerify()

          # Remove instances
          qa_instance.TestInstanceRemove(instance2)
          qa_instance.TestInstanceRemove(instance1)
        finally:
          instance2.Release()
      finally:
        instance1.Release()

    if qa_config.TestEnabled("instance-add-drbd-disk"):
      snode = qa_config.AcquireNode()
      try:
        qa_cluster.TestSetExclStorCluster(False)
        instance = qa_instance.TestInstanceAddWithDrbdDisk([node, snode])
        try:
          qa_cluster.TestSetExclStorCluster(True)
          exp_err = [constants.CV_EINSTANCEUNSUITABLENODE]
          qa_cluster.AssertClusterVerify(fail=True, errors=exp_err)
          qa_instance.TestInstanceRemove(instance)
        finally:
          instance.Release()
      finally:
        snode.Release()
    qa_cluster.TestSetExclStorCluster(old_es)
  finally:
    node.Release()


def _BuildSpecDict(par, mn, st, mx):
  return {
    constants.ISPECS_MINMAX: [{
      constants.ISPECS_MIN: {par: mn},
      constants.ISPECS_MAX: {par: mx},
      }],
    constants.ISPECS_STD: {par: st},
    }


def _BuildDoubleSpecDict(index, par, mn, st, mx):
  new_spec = {
    constants.ISPECS_MINMAX: [{}, {}],
    }
  if st is not None:
    new_spec[constants.ISPECS_STD] = {par: st}
  new_spec[constants.ISPECS_MINMAX][index] = {
    constants.ISPECS_MIN: {par: mn},
    constants.ISPECS_MAX: {par: mx},
    }
  return new_spec


def TestIPolicyPlainInstance():
  """Test instance policy interaction with instances"""
  params = ["memory-size", "cpu-count", "disk-count", "disk-size", "nic-count"]
  if not qa_config.IsTemplateSupported(constants.DT_PLAIN):
    print "Template %s not supported" % constants.DT_PLAIN
    return

  # This test assumes that the group policy is empty
  (_, old_specs) = qa_cluster.TestClusterSetISpecs()
  # We also assume to have only one min/max bound
  assert len(old_specs[constants.ISPECS_MINMAX]) == 1
  node = qa_config.AcquireNode()
  try:
    # Log of policy changes, list of tuples:
    # (full_change, incremental_change, policy_violated)
    history = []
    instance = qa_instance.TestInstanceAddWithPlainDisk([node])
    try:
      policyerror = [constants.CV_EINSTANCEPOLICY]
      for par in params:
        (iminval, imaxval) = qa_instance.GetInstanceSpec(instance.name, par)
        # Some specs must be multiple of 4
        new_spec = _BuildSpecDict(par, imaxval + 4, imaxval + 4, imaxval + 4)
        history.append((None, new_spec, True))
        if iminval > 0:
          # Some specs must be multiple of 4
          if iminval >= 4:
            upper = iminval - 4
          else:
            upper = iminval - 1
          new_spec = _BuildSpecDict(par, 0, upper, upper)
          history.append((None, new_spec, True))
        history.append((old_specs, None, False))

      # Test with two instance specs
      double_specs = copy.deepcopy(old_specs)
      double_specs[constants.ISPECS_MINMAX] = \
          double_specs[constants.ISPECS_MINMAX] * 2
      (par1, par2) = params[0:2]
      (_, imaxval1) = qa_instance.GetInstanceSpec(instance.name, par1)
      (_, imaxval2) = qa_instance.GetInstanceSpec(instance.name, par2)
      old_minmax = old_specs[constants.ISPECS_MINMAX][0]
      history.extend([
        (double_specs, None, False),
        # The first min/max limit is being violated
        (None,
         _BuildDoubleSpecDict(0, par1, imaxval1 + 4, imaxval1 + 4,
                              imaxval1 + 4),
         False),
        # Both min/max limits are being violated
        (None,
         _BuildDoubleSpecDict(1, par2, imaxval2 + 4, None, imaxval2 + 4),
         True),
        # The second min/max limit is being violated
        (None,
         _BuildDoubleSpecDict(0, par1,
                              old_minmax[constants.ISPECS_MIN][par1],
                              old_specs[constants.ISPECS_STD][par1],
                              old_minmax[constants.ISPECS_MAX][par1]),
         False),
        (old_specs, None, False),
        ])

      # Apply the changes, and check policy violations after each change
      qa_cluster.AssertClusterVerify()
      for (new_specs, diff_specs, failed) in history:
        qa_cluster.TestClusterSetISpecs(new_specs=new_specs,
                                        diff_specs=diff_specs)
        if failed:
          qa_cluster.AssertClusterVerify(warnings=policyerror)
        else:
          qa_cluster.AssertClusterVerify()

      qa_instance.TestInstanceRemove(instance)
    finally:
      instance.Release()

    # Now we replay the same policy changes, and we expect that the instance
    # cannot be created for the cases where we had a policy violation above
    for (new_specs, diff_specs, failed) in history:
      qa_cluster.TestClusterSetISpecs(new_specs=new_specs,
                                      diff_specs=diff_specs)
      if failed:
        qa_instance.TestInstanceAddWithPlainDisk([node], fail=True)
      # Instance creation with no policy violation has been tested already
  finally:
    node.Release()


def IsExclusiveStorageInstanceTestEnabled():
  test_name = "exclusive-storage-instance-tests"
  if qa_config.TestEnabled(test_name):
    vgname = qa_config.get("vg-name", constants.DEFAULT_VG)
    vgscmd = utils.ShellQuoteArgs([
      "vgs", "--noheadings", "-o", "pv_count", vgname,
      ])
    nodes = qa_config.GetConfig()["nodes"]
    for node in nodes:
      try:
        pvnum = int(qa_utils.GetCommandOutput(node.primary, vgscmd))
      except Exception, e:
        msg = ("Cannot get the number of PVs on %s, needed by '%s': %s" %
               (node.primary, test_name, e))
        raise qa_error.Error(msg)
      if pvnum < 2:
        raise qa_error.Error("Node %s has not enough PVs (%s) to run '%s'" %
                             (node.primary, pvnum, test_name))
    res = True
  else:
    res = False
  return res


def RunInstanceTests():
  """Create and exercise instances."""

  for (test_name, templ, create_fun, num_nodes) in \
      qa_instance.available_instance_tests:
    if (qa_config.TestEnabled(test_name) and
        qa_config.IsTemplateSupported(templ)):
      inodes = qa_config.AcquireManyNodes(num_nodes)
      try:
        instance = RunTest(create_fun, inodes)
        try:
          RunTestIf("cluster-epo", qa_cluster.TestClusterEpo)
          RunDaemonTests(instance)
          for node in inodes:
            RunTestIf("haskell-confd", qa_node.TestNodeListDrbd, node)
          if len(inodes) > 1:
            RunTestIf("group-rwops", qa_group.TestAssignNodesIncludingSplit,
                      constants.INITIAL_NODE_GROUP_NAME,
                      inodes[0].primary, inodes[1].primary)
          if qa_config.TestEnabled("instance-convert-disk"):
            RunTest(qa_instance.TestInstanceShutdown, instance)
            RunTest(qa_instance.TestInstanceConvertDiskToPlain,
                    instance, inodes)
            RunTest(qa_instance.TestInstanceStartup, instance)
          RunTestIf("instance-modify-disks",
                    qa_instance.TestInstanceModifyDisks, instance)
          RunCommonInstanceTests(instance, inodes)
          if qa_config.TestEnabled("instance-modify-primary"):
            othernode = qa_config.AcquireNode()
            RunTest(qa_instance.TestInstanceModifyPrimaryAndBack,
                    instance, inodes[0], othernode)
            othernode.Release()
          RunGroupListTests()
          RunExportImportTests(instance, inodes)
          RunHardwareFailureTests(instance, inodes)
          RunRepairDiskSizes()
          RunTest(qa_instance.TestInstanceRemove, instance)
        finally:
          instance.Release()
        del instance
      finally:
        qa_config.ReleaseManyNodes(inodes)
      qa_cluster.AssertClusterVerify()


def RunMonitoringTests():
  if qa_config.TestEnabled("mon-collector"):
    RunTest(qa_monitoring.TestInstStatusCollector)


def RunQa():
  """Main QA body.

  """
  rapi_user = "ganeti-qa"

  RunEnvTests()
  rapi_secret = SetupCluster(rapi_user)

  if qa_rapi.Enabled():
    # Load RAPI certificate
    qa_rapi.Setup(rapi_user, rapi_secret)

  RunClusterTests()
  RunOsTests()

  RunTestIf("tags", qa_tags.TestClusterTags)

  RunCommonNodeTests()
  RunGroupListTests()
  RunGroupRwTests()
  RunNetworkTests()

  # The master shouldn't be readded or put offline; "delay" needs a non-master
  # node to test
  pnode = qa_config.AcquireNode(exclude=qa_config.GetMasterNode())
  try:
    RunTestIf("node-readd", qa_node.TestNodeReadd, pnode)
    RunTestIf("node-modify", qa_node.TestNodeModify, pnode)
    RunTestIf("delay", qa_cluster.TestDelay, pnode)
  finally:
    pnode.Release()

  # Make sure the cluster is clean before running instance tests
  qa_cluster.AssertClusterVerify()

  pnode = qa_config.AcquireNode()
  try:
    RunTestIf("tags", qa_tags.TestNodeTags, pnode)

    if qa_rapi.Enabled():
      RunTest(qa_rapi.TestNode, pnode)

      if (qa_config.TestEnabled("instance-add-plain-disk")
          and qa_config.IsTemplateSupported(constants.DT_PLAIN)):
        for use_client in [True, False]:
          rapi_instance = RunTest(qa_rapi.TestRapiInstanceAdd, pnode,
                                  use_client)
          try:
            if qa_config.TestEnabled("instance-plain-rapi-common-tests"):
              RunCommonInstanceTests(rapi_instance, [pnode])
            RunTest(qa_rapi.TestRapiInstanceRemove, rapi_instance, use_client)
          finally:
            rapi_instance.Release()
          del rapi_instance

  finally:
    pnode.Release()

  config_list = [
    ("default-instance-tests", lambda: None, lambda _: None),
    (IsExclusiveStorageInstanceTestEnabled,
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
        try:
          expnode = qa_config.AcquireNode(exclude=pnode)
          try:
            if shutdown:
              # Stop instance before exporting and removing it
              RunTest(qa_instance.TestInstanceShutdown, instance)
            RunTest(qa_instance.TestInstanceExportWithRemove, instance, expnode)
            RunTest(qa_instance.TestBackupList, expnode)
          finally:
            expnode.Release()
        finally:
          instance.Release()
        del expnode
        del instance
      qa_cluster.AssertClusterVerify()

  finally:
    pnode.Release()

  RunTestIf("cluster-upgrade", qa_cluster.TestUpgrade)

  RunExclusiveStorageTests()
  RunTestIf(["cluster-instance-policy", "instance-add-plain-disk"],
            TestIPolicyPlainInstance)

  RunTestIf(
    "instance-add-restricted-by-disktemplates",
    qa_instance.TestInstanceCreationRestrictedByDiskTemplates)

  # Test removing instance with offline drbd secondary
  if qa_config.TestEnabled(["instance-remove-drbd-offline",
                            "instance-add-drbd-disk"]):
    # Make sure the master is not put offline
    snode = qa_config.AcquireNode(exclude=qa_config.GetMasterNode())
    try:
      pnode = qa_config.AcquireNode(exclude=snode)
      try:
        instance = qa_instance.TestInstanceAddWithDrbdDisk([pnode, snode])
        set_offline = lambda node: qa_node.MakeNodeOffline(node, "yes")
        set_online = lambda node: qa_node.MakeNodeOffline(node, "no")
        RunTest(qa_instance.TestRemoveInstanceOfflineNode, instance, snode,
                set_offline, set_online)
      finally:
        pnode.Release()
    finally:
      snode.Release()
    qa_cluster.AssertClusterVerify()

  RunMonitoringTests()

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
  (opts, args) = parser.parse_args()

  if len(args) == 1:
    (config_file, ) = args
  else:
    parser.error("Wrong number of arguments.")

  if not opts.yes_do_it:
    print ("Executing this script irreversibly destroys any Ganeti\n"
           "configuration on all nodes involved. If you really want\n"
           "to start testing, supply the --yes-do-it option.")
    sys.exit(1)

  qa_config.Load(config_file)

  primary = qa_config.GetMasterNode().primary
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
