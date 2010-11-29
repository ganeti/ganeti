#
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


"""Daemon related QA tests.

"""

import time

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertMatch, AssertCommand, StartSSH, GetCommandOutput


def _InstanceRunning(node, name):
  """Checks whether an instance is running.

  @param node: node the instance runs on
  @param name: full name of the Xen instance

  """
  cmd = utils.ShellQuoteArgs(['xm', 'list', name]) + ' >/dev/null'
  ret = StartSSH(node['primary'], cmd).wait()
  return ret == 0


def _XmShutdownInstance(node, name):
  """Shuts down instance using "xm" and waits for completion.

  @param node: node the instance runs on
  @param name: full name of Xen instance

  """
  AssertCommand(["xm", "shutdown", name], node=node)

  # Wait up to a minute
  end = time.time() + 60
  while time.time() <= end:
    if not _InstanceRunning(node, name):
      break
    time.sleep(5)
  else:
    raise qa_error.Error("xm shutdown failed")


def _ResetWatcherDaemon():
  """Removes the watcher daemon's state file.

  """
  AssertCommand(["rm", "-f", constants.WATCHER_STATEFILE])


def _RunWatcherDaemon():
  """Runs the ganeti-watcher daemon on the master node.

  """
  AssertCommand(["ganeti-watcher", "-d", "--ignore-pause"])


def TestPauseWatcher():
  """Tests and pauses the watcher.

  """
  master = qa_config.GetMasterNode()

  AssertCommand(["gnt-cluster", "watcher", "pause", "4h"])

  cmd = ["gnt-cluster", "watcher", "info"]
  output = GetCommandOutput(master["primary"],
                            utils.ShellQuoteArgs(cmd))
  AssertMatch(output, r"^.*\bis paused\b.*")


def TestResumeWatcher():
  """Tests and unpauses the watcher.

  """
  master = qa_config.GetMasterNode()

  AssertCommand(["gnt-cluster", "watcher", "continue"])

  cmd = ["gnt-cluster", "watcher", "info"]
  output = GetCommandOutput(master["primary"],
                            utils.ShellQuoteArgs(cmd))
  AssertMatch(output, r"^.*\bis not paused\b.*")


def TestInstanceAutomaticRestart(node, instance):
  """Test automatic restart of instance by ganeti-watcher.

  """
  inst_name = qa_utils.ResolveInstanceName(instance["name"])

  _ResetWatcherDaemon()
  _XmShutdownInstance(node, inst_name)

  _RunWatcherDaemon()
  time.sleep(5)

  if not _InstanceRunning(node, inst_name):
    raise qa_error.Error("Daemon didn't restart instance")

  AssertCommand(["gnt-instance", "info", inst_name])


def TestInstanceConsecutiveFailures(node, instance):
  """Test five consecutive instance failures.

  """
  inst_name = qa_utils.ResolveInstanceName(instance["name"])

  _ResetWatcherDaemon()

  for should_start in ([True] * 5) + [False]:
    _XmShutdownInstance(node, inst_name)
    _RunWatcherDaemon()
    time.sleep(5)

    if bool(_InstanceRunning(node, inst_name)) != should_start:
      if should_start:
        msg = "Instance not started when it should"
      else:
        msg = "Instance started when it shouldn't"
      raise qa_error.Error(msg)

  AssertCommand(["gnt-instance", "info", inst_name])
