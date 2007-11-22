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


"""Daemon related QA tests.

"""

import time

from ganeti import utils
from ganeti import constants

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertEqual, StartSSH


def _InstanceRunning(node, name):
  """Checks whether an instance is running.

  Args:
    node: Node the instance runs on
    name: Full name of Xen instance
  """
  cmd = utils.ShellQuoteArgs(['xm', 'list', name]) + ' >/dev/null'
  ret = StartSSH(node['primary'], cmd).wait()
  return ret == 0


def _XmShutdownInstance(node, name):
  """Shuts down instance using "xm" and waits for completion.

  Args:
    node: Node the instance runs on
    name: Full name of Xen instance
  """
  master = qa_config.GetMasterNode()

  cmd = ['xm', 'shutdown', name]
  AssertEqual(StartSSH(node['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)

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

  Args:
    node: Node to be reset
  """
  master = qa_config.GetMasterNode()

  cmd = ['rm', '-f', constants.WATCHER_STATEFILE]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def _RunWatcherDaemon():
  """Runs the ganeti-watcher daemon on the master node.

  """
  master = qa_config.GetMasterNode()

  cmd = ['ganeti-watcher', '-d']
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


def PrintCronWarning():
  """Shows a warning about the cron job.

  """
  msg = ("For the following tests it's recommended to turn off the "
         "ganeti-watcher cronjob.")
  print
  print qa_utils.FormatWarning(msg)


@qa_utils.DefineHook('daemon-automatic-restart')
def TestInstanceAutomaticRestart(node, instance):
  """Test automatic restart of instance by ganeti-watcher.

  """
  master = qa_config.GetMasterNode()
  inst_name = qa_utils.ResolveInstanceName(instance)

  _ResetWatcherDaemon()
  _XmShutdownInstance(node, inst_name)

  _RunWatcherDaemon()
  time.sleep(5)

  if not _InstanceRunning(node, inst_name):
    raise qa_error.Error("Daemon didn't restart instance")

  cmd = ['gnt-instance', 'info', inst_name]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)


@qa_utils.DefineHook('daemon-consecutive-failures')
def TestInstanceConsecutiveFailures(node, instance):
  """Test five consecutive instance failures.

  """
  master = qa_config.GetMasterNode()
  inst_name = qa_utils.ResolveInstanceName(instance)

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

  cmd = ['gnt-instance', 'info', inst_name]
  AssertEqual(StartSSH(master['primary'],
                       utils.ShellQuoteArgs(cmd)).wait(), 0)
