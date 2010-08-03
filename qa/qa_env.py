#
#

# Copyright (C) 2007, 2010 Google Inc.
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
import qa_utils

from qa_utils import AssertEqual, StartSSH


def TestSshConnection():
  """Test SSH connection.

  """
  for node in qa_config.get('nodes'):
    AssertEqual(StartSSH(node['primary'], 'exit').wait(), 0)


def TestGanetiCommands():
  """Test availibility of Ganeti commands.

  """
  cmds = ( ['gnt-backup', '--version'],
           ['gnt-cluster', '--version'],
           ['gnt-debug', '--version'],
           ['gnt-instance', '--version'],
           ['gnt-job', '--version'],
           ['gnt-node', '--version'],
           ['gnt-os', '--version'],
           ['ganeti-masterd', '--version'],
           ['ganeti-noded', '--version'],
           ['ganeti-rapi', '--version'],
           ['ganeti-watcher', '--version'],
           ['ganeti-confd', '--version'],
           )

  cmd = ' && '.join([utils.ShellQuoteArgs(i) for i in cmds])

  for node in qa_config.get('nodes'):
    AssertEqual(StartSSH(node['primary'], cmd).wait(), 0)


def TestIcmpPing():
  """ICMP ping each node.

  """
  nodes = qa_config.get('nodes')

  pingargs = ['-w', '3', '-c', '1 ']
  pingprimary = "ping"
  if qa_config.get("primary_ip_version") == 6:
    pingprimary = "ping6"

  for node in nodes:
    check = []
    for i in nodes:
      cmd = [pingprimary] + pingargs + [i['primary']]
      check.append(utils.ShellQuoteArgs(cmd))
      if i.has_key('secondary'):
        cmd = ["ping"] + pingargs + [i["secondary"]]
        check.append(utils.ShellQuoteArgs(cmd))

    cmdall = ' && '.join(check)
    AssertEqual(StartSSH(node['primary'], cmdall).wait(), 0)
