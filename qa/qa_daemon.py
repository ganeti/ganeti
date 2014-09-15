#
#

# Copyright (C) 2007, 2008, 2009, 2010, 2011 Google Inc.
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


"""Daemon related QA tests.

"""

import time

from ganeti import utils
from ganeti import pathutils

import qa_config
import qa_utils
import qa_error

from qa_utils import AssertMatch, AssertCommand, StartSSH, GetCommandOutput


def _InstanceRunning(name):
  """Checks whether an instance is running.

  @param name: full name of the instance

  """
  master = qa_config.GetMasterNode()

  cmd = (utils.ShellQuoteArgs(["gnt-instance", "list", "-o", "status", name]) +
         ' | grep running')
  ret = StartSSH(master.primary, cmd).wait()
  return ret == 0


def _ShutdownInstance(name):
  """Shuts down instance without recording state and waits for completion.

  @param name: full name of the instance

  """
  AssertCommand(["gnt-instance", "shutdown", "--no-remember", name])

  if _InstanceRunning(name):
    raise qa_error.Error("instance shutdown failed")


def _StartInstance(name):
  """Starts instance and waits for completion.

  @param name: full name of the instance

  """
  AssertCommand(["gnt-instance", "start", name])

  if not bool(_InstanceRunning(name)):
    raise qa_error.Error("instance start failed")


def _ResetWatcherDaemon():
  """Removes the watcher daemon's state file.

  """
  path = \
    qa_utils.MakeNodePath(qa_config.GetMasterNode(),
                          pathutils.WATCHER_GROUP_STATE_FILE % "*-*-*-*")

  AssertCommand(["bash", "-c", "rm -vf %s" % path])


def RunWatcherDaemon():
  """Runs the ganeti-watcher daemon on the master node.

  """
  AssertCommand(["ganeti-watcher", "-d", "--ignore-pause", "--wait-children"])


def TestPauseWatcher():
  """Tests and pauses the watcher.

  """
  master = qa_config.GetMasterNode()

  AssertCommand(["gnt-cluster", "watcher", "pause", "4h"])

  cmd = ["gnt-cluster", "watcher", "info"]
  output = GetCommandOutput(master.primary,
                            utils.ShellQuoteArgs(cmd))
  AssertMatch(output, r"^.*\bis paused\b.*")


def TestResumeWatcher():
  """Tests and unpauses the watcher.

  """
  master = qa_config.GetMasterNode()

  AssertCommand(["gnt-cluster", "watcher", "continue"])

  cmd = ["gnt-cluster", "watcher", "info"]
  output = GetCommandOutput(master.primary,
                            utils.ShellQuoteArgs(cmd))
  AssertMatch(output, r"^.*\bis not paused\b.*")


def TestInstanceAutomaticRestart(instance):
  """Test automatic restart of instance by ganeti-watcher.

  """
  inst_name = qa_utils.ResolveInstanceName(instance.name)

  _ResetWatcherDaemon()
  _ShutdownInstance(inst_name)

  RunWatcherDaemon()
  time.sleep(5)

  if not _InstanceRunning(inst_name):
    raise qa_error.Error("Daemon didn't restart instance")

  AssertCommand(["gnt-instance", "info", inst_name])


def TestInstanceConsecutiveFailures(instance):
  """Test five consecutive instance failures.

  """
  inst_name = qa_utils.ResolveInstanceName(instance.name)
  inst_was_running = bool(_InstanceRunning(inst_name))

  _ResetWatcherDaemon()

  for should_start in ([True] * 5) + [False]:
    _ShutdownInstance(inst_name)
    RunWatcherDaemon()
    time.sleep(5)

    if bool(_InstanceRunning(inst_name)) != should_start:
      if should_start:
        msg = "Instance not started when it should"
      else:
        msg = "Instance started when it shouldn't"
      raise qa_error.Error(msg)

  AssertCommand(["gnt-instance", "info", inst_name])

  if inst_was_running:
    _StartInstance(inst_name)
