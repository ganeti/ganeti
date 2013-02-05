#
#

# Copyright (C) 2007, 2010, 2011, 2012 Google Inc.
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
          ["gnt-node", "--version"],
          ["gnt-os", "--version"],
          ["ganeti-masterd", "--version"],
          ["ganeti-noded", "--version"],
          ["ganeti-rapi", "--version"],
          ["ganeti-watcher", "--version"],
          ["ganeti-confd", "--version"],
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
