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


def main():
  """Main program.

  """
  parser = OptionParser(usage="%prog [options] <config-file> "
                              "<known-hosts-file>")
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

  RunTest(qa_other.TestUploadKnownHostsFile, known_hosts_file)

  if qa_config.TestEnabled('env'):
    RunTest(qa_env.TestSshConnection)
    RunTest(qa_env.TestIcmpPing)
    RunTest(qa_env.TestGanetiCommands)

  RunTest(qa_cluster.TestClusterInit)

  RunTest(qa_node.TestNodeAddAll)

  if qa_config.TestEnabled('cluster-verify'):
    RunTest(qa_cluster.TestClusterVerify)

  if qa_config.TestEnabled('cluster-info'):
    RunTest(qa_cluster.TestClusterInfo)

  if qa_config.TestEnabled('cluster-getmaster'):
    RunTest(qa_cluster.TestClusterGetmaster)

  if qa_config.TestEnabled('cluster-version'):
    RunTest(qa_cluster.TestClusterVersion)

  if qa_config.TestEnabled('cluster-copyfile'):
    RunTest(qa_cluster.TestClusterCopyfile)

  if qa_config.TestEnabled('node-info'):
    RunTest(qa_node.TestNodeInfo)

  if qa_config.TestEnabled('cluster-burnin'):
    RunTest(qa_cluster.TestClusterBurnin)

  if qa_config.TestEnabled('cluster-master-failover'):
    RunTest(qa_cluster.TestClusterMasterFailover)

  if qa_config.TestEnabled('os'):
    RunTest(qa_os.TestOsList)
    RunTest(qa_os.TestOsDiagnose)
    RunTest(qa_os.TestOsValid)
    RunTest(qa_os.TestOsInvalid)
    RunTest(qa_os.TestOsPartiallyValid)

  node = qa_config.AcquireNode()
  try:
    if qa_config.TestEnabled('instance-add-plain-disk'):
      instance = RunTest(qa_instance.TestInstanceAddWithPlainDisk, node)

      if qa_config.TestEnabled('instance-shutdown'):
        RunTest(qa_instance.TestInstanceShutdown, instance)
        RunTest(qa_instance.TestInstanceStartup, instance)

      if qa_config.TestEnabled('instance-list'):
        RunTest(qa_instance.TestInstanceList)

      if qa_config.TestEnabled('instance-info'):
        RunTest(qa_instance.TestInstanceInfo, instance)

      automatic_restart = \
        qa_config.TestEnabled('instance-automatic-restart')
      consecutive_failures = \
        qa_config.TestEnabled('instance-consecutive-failures')

      if automatic_restart or consecutive_failures:
        qa_daemon.PrintCronWarning()

        if automatic_restart:
          RunTest(qa_daemon.TestInstanceAutomaticRestart, node, instance)

        if consecutive_failures:
          RunTest(qa_daemon.TestInstanceConsecutiveFailures, node, instance)

      if qa_config.TestEnabled('instance-export'):
        expnode = qa_config.AcquireNode(exclude=node)
        try:
          name = RunTest(qa_instance.TestInstanceExport, instance, expnode)

          RunTest(qa_instance.TestBackupList, expnode)

          if qa_config.TestEnabled('instance-import'):
            newinst = qa_config.AcquireInstance()
            try:
              RunTest(qa_instance.TestInstanceImport, node, newinst,
                      expnode, name)
              RunTest(qa_instance.TestInstanceRemove, newinst)
            finally:
              qa_config.ReleaseInstance(newinst)
        finally:
          qa_config.ReleaseNode(expnode)

      if qa_config.TestEnabled('instance-reinstall'):
        RunTest(qa_instance.TestInstanceShutdown, instance)
        RunTest(qa_instance.TestInstanceReinstall, instance)
        RunTest(qa_instance.TestInstanceStartup, instance)

      if qa_config.TestEnabled('node-volumes'):
        RunTest(qa_node.TestNodeVolumes)

      RunTest(qa_instance.TestInstanceRemove, instance)
      del instance

    if qa_config.TestEnabled('instance-add-local-mirror-disk'):
      instance = RunTest(qa_instance.TestInstanceAddWithLocalMirrorDisk, node)

      if qa_config.TestEnabled('instance-shutdown'):
        RunTest(qa_instance.TestInstanceShutdown, instance)
        RunTest(qa_instance.TestInstanceStartup, instance)

      if qa_config.TestEnabled('instance-info'):
        RunTest(qa_instance.TestInstanceInfo, instance)

      if qa_config.TestEnabled('node-volumes'):
        RunTest(qa_node.TestNodeVolumes)

      RunTest(qa_instance.TestInstanceRemove, instance)
      del instance

    if qa_config.TestEnabled('instance-add-remote-raid-disk'):
      node2 = qa_config.AcquireNode(exclude=node)
      try:
        instance = RunTest(qa_instance.TestInstanceAddWithRemoteRaidDisk,
                           node, node2)

        if qa_config.TestEnabled('instance-shutdown'):
          RunTest(qa_instance.TestInstanceShutdown, instance)
          RunTest(qa_instance.TestInstanceStartup, instance)

        if qa_config.TestEnabled('instance-info'):
          RunTest(qa_instance.TestInstanceInfo, instance)

        if qa_config.TestEnabled('instance-failover'):
          RunTest(qa_instance.TestInstanceFailover, instance)

        if qa_config.TestEnabled('node-evacuate'):
          RunTest(qa_node.TestNodeEvacuate, node, node2)

        if qa_config.TestEnabled('node-failover'):
          RunTest(qa_node.TestNodeFailover, node, node2)

        if qa_config.TestEnabled('node-volumes'):
          RunTest(qa_node.TestNodeVolumes)

        if qa_config.TestEnabled('instance-disk-failure'):
          RunTest(qa_instance.TestInstanceMasterDiskFailure,
                  instance, node, node2)
          RunTest(qa_instance.TestInstanceSecondaryDiskFailure,
                  instance, node, node2)

        RunTest(qa_instance.TestInstanceRemove, instance)
        del instance
      finally:
        qa_config.ReleaseNode(node2)

  finally:
    qa_config.ReleaseNode(node)

  RunTest(qa_node.TestNodeRemoveAll)

  if qa_config.TestEnabled('cluster-destroy'):
    RunTest(qa_cluster.TestClusterDestroy)


if __name__ == '__main__':
  main()
