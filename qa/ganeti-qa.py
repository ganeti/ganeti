#!/usr/bin/python
#

# Copyright (C) 2007, 2008, 2009, 2010 Google Inc.
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

import sys
import datetime
import optparse

import qa_cluster
import qa_config
import qa_daemon
import qa_env
import qa_instance
import qa_node
import qa_os
import qa_rapi
import qa_tags
import qa_utils

from ganeti import utils
from ganeti import rapi

import ganeti.rapi.client


def RunTest(fn, *args):
  """Runs a test after printing a header.

  """
  if fn.__doc__:
    desc = fn.__doc__.splitlines()[0].strip()
  else:
    desc = '%r' % fn

  now = str(datetime.datetime.now())

  print
  print '---', now, ('-' * (55 - len(now)))
  print desc
  print '-' * 60

  return fn(*args)


def RunEnvTests():
  """Run several environment tests.

  """
  if not qa_config.TestEnabled('env'):
    return

  RunTest(qa_env.TestSshConnection)
  RunTest(qa_env.TestIcmpPing)
  RunTest(qa_env.TestGanetiCommands)


def SetupCluster(rapi_user, rapi_secret):
  """Initializes the cluster.

  @param rapi_user: Login user for RAPI
  @param rapi_secret: Login secret for RAPI

  """
  if qa_config.TestEnabled('create-cluster'):
    RunTest(qa_cluster.TestClusterInit, rapi_user, rapi_secret)
    RunTest(qa_node.TestNodeAddAll)
    RunTest(qa_cluster.TestJobqueue)
  else:
    # consider the nodes are already there
    qa_node.MarkNodeAddedAll()
  if qa_config.TestEnabled('node-info'):
    RunTest(qa_node.TestNodeInfo)


def RunClusterTests():
  """Runs tests related to gnt-cluster.

  """
  if qa_config.TestEnabled("cluster-renew-crypto"):
    RunTest(qa_cluster.TestClusterRenewCrypto)

  if qa_config.TestEnabled('cluster-verify'):
    RunTest(qa_cluster.TestClusterVerify)

  if qa_config.TestEnabled('cluster-reserved-lvs'):
    RunTest(qa_cluster.TestClusterReservedLvs)

  if qa_config.TestEnabled('cluster-rename'):
    RunTest(qa_cluster.TestClusterRename)

  if qa_config.TestEnabled('cluster-info'):
    RunTest(qa_cluster.TestClusterVersion)
    RunTest(qa_cluster.TestClusterInfo)
    RunTest(qa_cluster.TestClusterGetmaster)

  if qa_config.TestEnabled('cluster-copyfile'):
    RunTest(qa_cluster.TestClusterCopyfile)

  if qa_config.TestEnabled('cluster-command'):
    RunTest(qa_cluster.TestClusterCommand)

  if qa_config.TestEnabled('cluster-burnin'):
    RunTest(qa_cluster.TestClusterBurnin)

  if qa_config.TestEnabled('cluster-master-failover'):
    RunTest(qa_cluster.TestClusterMasterFailover)

  if qa_rapi.Enabled():
    RunTest(qa_rapi.TestVersion)
    RunTest(qa_rapi.TestEmptyCluster)


def RunOsTests():
  """Runs all tests related to gnt-os.

  """
  if not qa_config.TestEnabled('os'):
    return

  RunTest(qa_os.TestOsList)
  RunTest(qa_os.TestOsDiagnose)
  RunTest(qa_os.TestOsValid)
  RunTest(qa_os.TestOsInvalid)
  RunTest(qa_os.TestOsPartiallyValid)
  RunTest(qa_os.TestOsModifyValid)
  RunTest(qa_os.TestOsModifyInvalid)
  RunTest(qa_os.TestOsStates)


def RunCommonInstanceTests(instance):
  """Runs a few tests that are common to all disk types.

  """
  if qa_config.TestEnabled('instance-shutdown'):
    RunTest(qa_instance.TestInstanceShutdown, instance)
    RunTest(qa_instance.TestInstanceStartup, instance)

  if qa_config.TestEnabled('instance-list'):
    RunTest(qa_instance.TestInstanceList)

  if qa_config.TestEnabled('instance-info'):
    RunTest(qa_instance.TestInstanceInfo, instance)

  if qa_config.TestEnabled('instance-modify'):
    RunTest(qa_instance.TestInstanceModify, instance)
    if qa_rapi.Enabled():
      RunTest(qa_rapi.TestRapiInstanceModify, instance)

  if qa_config.TestEnabled('instance-console'):
    RunTest(qa_instance.TestInstanceConsole, instance)

  if qa_config.TestEnabled('instance-reinstall'):
    RunTest(qa_instance.TestInstanceShutdown, instance)
    RunTest(qa_instance.TestInstanceReinstall, instance)
    RunTest(qa_instance.TestInstanceStartup, instance)

  if qa_config.TestEnabled('instance-reboot'):
    RunTest(qa_instance.TestInstanceReboot, instance)

  if qa_config.TestEnabled('instance-rename'):
    rename_target = qa_config.get("rename", None)
    if rename_target is None:
      print qa_utils.FormatError("Can rename instance, 'rename' entry is"
                                 " missing from configuration")
    else:
      RunTest(qa_instance.TestInstanceShutdown, instance)
      RunTest(qa_instance.TestInstanceRename, instance, rename_target)
      if qa_rapi.Enabled():
        RunTest(qa_rapi.TestRapiInstanceRename, instance, rename_target)
      RunTest(qa_instance.TestInstanceStartup, instance)

  if qa_config.TestEnabled('tags'):
    RunTest(qa_tags.TestInstanceTags, instance)

  if qa_config.TestEnabled('node-volumes'):
    RunTest(qa_node.TestNodeVolumes)

  if qa_config.TestEnabled("node-storage"):
    RunTest(qa_node.TestNodeStorage)

  if qa_rapi.Enabled():
    RunTest(qa_rapi.TestInstance, instance)


def RunExportImportTests(instance, pnode):
  """Tries to export and import the instance.

  """
  if qa_config.TestEnabled('instance-export'):
    RunTest(qa_instance.TestInstanceExportNoTarget, instance)

    expnode = qa_config.AcquireNode(exclude=pnode)
    try:
      name = RunTest(qa_instance.TestInstanceExport, instance, expnode)

      RunTest(qa_instance.TestBackupList, expnode)

      if qa_config.TestEnabled('instance-import'):
        newinst = qa_config.AcquireInstance()
        try:
          RunTest(qa_instance.TestInstanceImport, pnode, newinst,
                  expnode, name)
          RunTest(qa_instance.TestInstanceRemove, newinst)
        finally:
          qa_config.ReleaseInstance(newinst)
    finally:
      qa_config.ReleaseNode(expnode)

  if (qa_rapi.Enabled() and
      qa_config.TestEnabled("inter-cluster-instance-move")):
    newinst = qa_config.AcquireInstance()
    try:
      pnode2 = qa_config.AcquireNode(exclude=pnode)
      try:
        RunTest(qa_rapi.TestInterClusterInstanceMove, instance, newinst,
                pnode2, pnode)
      finally:
        qa_config.ReleaseNode(pnode2)
    finally:
      qa_config.ReleaseInstance(newinst)


def RunDaemonTests(instance, pnode):
  """Test the ganeti-watcher script.

  """
  automatic_restart = \
    qa_config.TestEnabled('instance-automatic-restart')
  consecutive_failures = \
    qa_config.TestEnabled('instance-consecutive-failures')

  if automatic_restart or consecutive_failures:
    qa_daemon.PrintCronWarning()

    if automatic_restart:
      RunTest(qa_daemon.TestInstanceAutomaticRestart, pnode, instance)

    if consecutive_failures:
      RunTest(qa_daemon.TestInstanceConsecutiveFailures, pnode, instance)


def RunHardwareFailureTests(instance, pnode, snode):
  """Test cluster internal hardware failure recovery.

  """
  if qa_config.TestEnabled('instance-failover'):
    RunTest(qa_instance.TestInstanceFailover, instance)

  if qa_config.TestEnabled("instance-migrate"):
    RunTest(qa_instance.TestInstanceMigrate, instance)

    if qa_rapi.Enabled():
      RunTest(qa_rapi.TestRapiInstanceMigrate, instance)

  if qa_config.TestEnabled('instance-replace-disks'):
    othernode = qa_config.AcquireNode(exclude=[pnode, snode])
    try:
      RunTest(qa_instance.TestReplaceDisks,
              instance, pnode, snode, othernode)
    finally:
      qa_config.ReleaseNode(othernode)

  if qa_config.TestEnabled('node-evacuate'):
    RunTest(qa_node.TestNodeEvacuate, pnode, snode)

  if qa_config.TestEnabled('node-failover'):
    RunTest(qa_node.TestNodeFailover, pnode, snode)

  if qa_config.TestEnabled('instance-disk-failure'):
    RunTest(qa_instance.TestInstanceMasterDiskFailure,
            instance, pnode, snode)
    RunTest(qa_instance.TestInstanceSecondaryDiskFailure,
            instance, pnode, snode)


@rapi.client.UsesRapiClient
def main():
  """Main program.

  """
  parser = optparse.OptionParser(usage="%prog [options] <config-file>")
  parser.add_option('--yes-do-it', dest='yes_do_it',
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

  rapi_user = "ganeti-qa"
  rapi_secret = utils.GenerateSecret()

  RunEnvTests()
  SetupCluster(rapi_user, rapi_secret)

  # Load RAPI certificate
  qa_rapi.Setup(rapi_user, rapi_secret)

  RunClusterTests()
  RunOsTests()

  if qa_config.TestEnabled('tags'):
    RunTest(qa_tags.TestClusterTags)

  if qa_config.TestEnabled('node-readd'):
    master = qa_config.GetMasterNode()
    pnode = qa_config.AcquireNode(exclude=master)
    try:
      RunTest(qa_node.TestNodeReadd, pnode)
    finally:
      qa_config.ReleaseNode(pnode)

  pnode = qa_config.AcquireNode()
  try:
    if qa_config.TestEnabled('tags'):
      RunTest(qa_tags.TestNodeTags, pnode)

    if qa_rapi.Enabled():
      RunTest(qa_rapi.TestNode, pnode)

      if qa_config.TestEnabled("instance-add-plain-disk"):
        for use_client in [True, False]:
          rapi_instance = RunTest(qa_rapi.TestRapiInstanceAdd, pnode,
                                  use_client)
          RunCommonInstanceTests(rapi_instance)
          RunTest(qa_rapi.TestRapiInstanceRemove, rapi_instance, use_client)
          del rapi_instance

    if qa_config.TestEnabled('instance-add-plain-disk'):
      instance = RunTest(qa_instance.TestInstanceAddWithPlainDisk, pnode)
      RunCommonInstanceTests(instance)
      RunExportImportTests(instance, pnode)
      RunDaemonTests(instance, pnode)
      RunTest(qa_instance.TestInstanceRemove, instance)
      del instance

    multinode_tests = [
      ('instance-add-drbd-disk',
       qa_instance.TestInstanceAddWithDrbdDisk),
    ]

    for name, func in multinode_tests:
      if qa_config.TestEnabled(name):
        snode = qa_config.AcquireNode(exclude=pnode)
        try:
          instance = RunTest(func, pnode, snode)
          RunCommonInstanceTests(instance)
          if qa_config.TestEnabled('instance-convert-disk'):
            RunTest(qa_instance.TestInstanceShutdown, instance)
            RunTest(qa_instance.TestInstanceConvertDisk, instance, snode)
            RunTest(qa_instance.TestInstanceStartup, instance)
          RunExportImportTests(instance, pnode)
          RunHardwareFailureTests(instance, pnode, snode)
          RunTest(qa_instance.TestInstanceRemove, instance)
          del instance
        finally:
          qa_config.ReleaseNode(snode)

    if (qa_config.TestEnabled('instance-add-plain-disk') and
        qa_config.TestEnabled("instance-export")):
      instance = RunTest(qa_instance.TestInstanceAddWithPlainDisk, pnode)
      expnode = qa_config.AcquireNode(exclude=pnode)
      try:
        RunTest(qa_instance.TestInstanceExportWithRemove, instance, expnode)
        RunTest(qa_instance.TestBackupList, expnode)
      finally:
        qa_config.ReleaseNode(expnode)
      del expnode
      del instance

  finally:
    qa_config.ReleaseNode(pnode)

  if qa_config.TestEnabled('create-cluster'):
    RunTest(qa_node.TestNodeRemoveAll)

  if qa_config.TestEnabled('cluster-destroy'):
    RunTest(qa_cluster.TestClusterDestroy)


if __name__ == '__main__':
  main()
