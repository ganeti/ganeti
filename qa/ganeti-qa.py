#!/usr/bin/python
#

# Copyright (C) 2007 Google Inc.
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

You can create the required known_hosts file using ssh-keyscan. It's mandatory
to use the full name of a node (FQDN). For security reasons, verify the keys
before using them.
Example: ssh-keyscan -t rsa node{1,2,3,4}.example.com > known_hosts
"""

import sys
from datetime import datetime
from optparse import OptionParser

import qa_cluster
import qa_config
import qa_daemon
import qa_env
import qa_instance
import qa_node
import qa_os
import qa_other
import qa_tags
import qa_utils


def RunTest(fn, *args):
  """Runs a test after printing a header.

  """
  if fn.__doc__:
    desc = fn.__doc__.splitlines()[0].strip()
  else:
    desc = '%r' % fn

  now = str(datetime.now())

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


def SetupCluster():
  """Initializes the cluster.

  """
  RunTest(qa_cluster.TestClusterInit)
  RunTest(qa_node.TestNodeAddAll)
  if qa_config.TestEnabled('node-info'):
    RunTest(qa_node.TestNodeInfo)


def RunClusterTests():
  """Runs tests related to gnt-cluster.

  """
  if qa_config.TestEnabled('cluster-verify'):
    RunTest(qa_cluster.TestClusterVerify)

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

  if qa_config.TestEnabled('instance-reinstall'):
    RunTest(qa_instance.TestInstanceShutdown, instance)
    RunTest(qa_instance.TestInstanceReinstall, instance)
    RunTest(qa_instance.TestInstanceStartup, instance)

  if qa_config.TestEnabled('tags'):
    RunTest(qa_tags.TestInstanceTags, instance)

  if qa_config.TestEnabled('node-volumes'):
    RunTest(qa_node.TestNodeVolumes)


def RunExportImportTests(instance, pnode):
  """Tries to export and import the instance.

  """
  if qa_config.TestEnabled('instance-export'):
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

  if qa_config.TestEnabled('node-evacuate'):
    RunTest(qa_node.TestNodeEvacuate, pnode, snode)

  if qa_config.TestEnabled('node-failover'):
    RunTest(qa_node.TestNodeFailover, pnode, snode)

  if qa_config.TestEnabled('instance-disk-failure'):
    RunTest(qa_instance.TestInstanceMasterDiskFailure,
            instance, pnode, snode)
    RunTest(qa_instance.TestInstanceSecondaryDiskFailure,
            instance, pnode, snode)


def main():
  """Main program.

  """
  parser = OptionParser(usage="%prog [options] <config-file>"
                              " <known-hosts-file>")
  parser.add_option('--dry-run', dest='dry_run',
      action="store_true",
      help="Show what would be done")
  parser.add_option('--yes-do-it', dest='yes_do_it',
      action="store_true",
      help="Really execute the tests")
  (qa_config.options, args) = parser.parse_args()

  if len(args) == 2:
    (config_file, known_hosts_file) = args
  else:
    parser.error("Not enough arguments.")

  if not qa_config.options.yes_do_it:
    print ("Executing this script irreversibly destroys any Ganeti\n"
           "configuration on all nodes involved. If you really want\n"
           "to start testing, supply the --yes-do-it option.")
    sys.exit(1)

  qa_config.Load(config_file)
  qa_utils.LoadHooks()

  RunTest(qa_other.UploadKnownHostsFile, known_hosts_file)

  RunEnvTests()
  SetupCluster()
  RunClusterTests()
  RunOsTests()

  if qa_config.TestEnabled('tags'):
    RunTest(qa_tags.TestClusterTags)

  pnode = qa_config.AcquireNode()
  try:
    if qa_config.TestEnabled('tags'):
      RunTest(qa_tags.TestNodeTags, pnode)

    if qa_config.TestEnabled('instance-add-plain-disk'):
      instance = RunTest(qa_instance.TestInstanceAddWithPlainDisk, pnode)
      RunCommonInstanceTests(instance)
      RunExportImportTests(instance, pnode)
      RunDaemonTests(instance, pnode)
      RunTest(qa_instance.TestInstanceRemove, instance)
      del instance

    if qa_config.TestEnabled('instance-add-local-mirror-disk'):
      instance = RunTest(qa_instance.TestInstanceAddWithLocalMirrorDisk, pnode)
      RunCommonInstanceTests(instance)
      RunExportImportTests(instance, pnode)
      RunTest(qa_instance.TestInstanceRemove, instance)
      del instance

    multinode_tests = [
      ('instance-add-remote-raid-disk',
       qa_instance.TestInstanceAddWithRemoteRaidDisk),
      ('instance-add-drbd-disk',
       qa_instance.TestInstanceAddWithDrbdDisk),
    ]

    for name, func in multinode_tests:
      if qa_config.TestEnabled(name):
        snode = qa_config.AcquireNode(exclude=pnode)
        try:
          instance = RunTest(func, pnode, snode)
          RunCommonInstanceTests(instance)
          RunExportImportTests(instance, pnode)
          RunHardwareFailureTests(instance, pnode, snode)
          RunTest(qa_instance.TestInstanceRemove, instance)
          del instance
        finally:
          qa_config.ReleaseNode(snode)

  finally:
    qa_config.ReleaseNode(pnode)

  RunTest(qa_node.TestNodeRemoveAll)

  if qa_config.TestEnabled('cluster-destroy'):
    RunTest(qa_cluster.TestClusterDestroy)


if __name__ == '__main__':
  main()
