#
#

# Copyright (C) 2007, 2010, 2011, 2012 Google Inc.
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


"""Cluster environment related QA tests.

"""

from ganeti import utils

import qa_config

from qa_utils import AssertCommand


def TestSshConnection():
  """Test SSH connection.

  """
  for node in qa_config.get("nodes"):
    AssertCommand("exit", node=node)


def TestGanetiCommands():
  """Test availibility of Ganeti commands.

  """
  cmds = (["gnt-backup", "--version"],
          ["gnt-cluster", "--version"],
          ["gnt-debug", "--version"],
          ["gnt-instance", "--version"],
          ["gnt-job", "--version"],
          ["gnt-network", "--version"],
          ["gnt-node", "--version"],
          ["gnt-os", "--version"],
          ["gnt-storage", "--version"],
          ["gnt-filter", "--version"],
          ["ganeti-noded", "--version"],
          ["ganeti-rapi", "--version"],
          ["ganeti-watcher", "--version"],
          ["ganeti-confd", "--version"],
          ["ganeti-luxid", "--version"],
          ["ganeti-wconfd", "--version"],
          )

  cmd = " && ".join([utils.ShellQuoteArgs(i) for i in cmds])

  for node in qa_config.get("nodes"):
    AssertCommand(cmd, node=node)


def TestIcmpPing():
  """ICMP ping each node.

  """
  nodes = qa_config.get("nodes")

  pingprimary = pingsecondary = "fping"
  if qa_config.get("primary_ip_version") == 6:
    pingprimary = "fping6"

  pricmd = [pingprimary, "-e"]
  seccmd = [pingsecondary, "-e"]
  for i in nodes:
    pricmd.append(i.primary)
    if i.secondary:
      seccmd.append(i.secondary)

  pristr = utils.ShellQuoteArgs(pricmd)
  if seccmd:
    cmdall = "%s && %s" % (pristr, utils.ShellQuoteArgs(seccmd))
  else:
    cmdall = pristr

  for node in nodes:
    AssertCommand(cmdall, node=node)
