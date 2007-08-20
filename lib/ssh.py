#!/usr/bin/python
#

# Copyright (C) 2006, 2007 Google Inc.
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


"""Module encapsulating ssh functionality.

"""


import os

from ganeti import logger
from ganeti import utils
from ganeti import errors

def SSHCall(hostname, user, command, batch=True, ask_key=False):
  """Execute a command on a remote node.

  This method has the same return value as `utils.RunCmd()`, which it
  uses to launch ssh.

  Args:
    hostname: the target host, string
    user: user to auth as
    command: the command

  Returns:
    `utils.RunResult` as for `utils.RunCmd()`

  """
  argv = ["ssh", "-q", "-oEscapeChar=none"]
  if batch:
    argv.append("-oBatchMode=yes")
    # if we are in batch mode, we can't ask the key
    if ask_key:
      raise errors.ProgrammerError("SSH call requested conflicting options")
  if ask_key:
    argv.append("-oStrictHostKeyChecking=ask")
    argv.append("-oHashKnownHosts=no")
  else:
    argv.append("-oStrictHostKeyChecking=yes")
  argv.extend(["%s@%s" % (user, hostname), command])
  return utils.RunCmd(argv)


def CopyFileToNode(node, filename):
  """Copy a file to another node with scp.

  Args:
    node: node in the cluster
    filename: absolute pathname of a local file

  Returns:
    success: True/False

  """
  if not os.path.isfile(filename):
    logger.Error("file %s does not exist" % (filename))
    return False

  if not os.path.isabs(filename):
    logger.Error("file %s must be an absolute path" % (filename))
    return False

  command = ["scp", "-q", "-p", "-oStrictHostKeyChecking=yes",
             "-oBatchMode=yes", filename, "%s:%s" % (node, filename)]

  result = utils.RunCmd(command)

  if result.failed:
    logger.Error("copy to node %s failed (%s) error %s,"
                 " command was %s" %
                 (node, result.fail_reason, result.output, result.cmd))

  return not result.failed


def VerifyNodeHostname(node):
  """Verify hostname consistency via SSH.


  This functions connects via ssh to a node and compares the hostname
  reported by the node to the name with have (the one that we
  connected to).

  This is used to detect problems in ssh known_hosts files
  (conflicting known hosts) and incosistencies between dns/hosts
  entries and local machine names

  Args:
    node: nodename of a host to check. can be short or full qualified hostname

  Returns:
    (success, detail)
    where
      success: True/False
      detail: String with details

  """
  retval = SSHCall(node, 'root', 'hostname')

  if retval.failed:
    msg = "ssh problem"
    output = retval.output
    if output:
      msg += ": %s" % output
    return False, msg

  remotehostname = retval.stdout.strip()

  if not remotehostname or remotehostname != node:
    return False, "hostname mismatch, got %s" % remotehostname

  return True, "host matches"
