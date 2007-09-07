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
from ganeti import constants


__all__ = ["SSHCall", "CopyFileToNode", "VerifyNodeHostname",
           "KNOWN_HOSTS_OPTS", "BATCH_MODE_OPTS", "ASK_KEY_OPTS"]


KNOWN_HOSTS_OPTS = [
  "-oGlobalKnownHostsFile=%s" % constants.SSH_KNOWN_HOSTS_FILE,
  "-oUserKnownHostsFile=/dev/null",
  ]

# Note: BATCH_MODE conflicts with ASK_KEY
BATCH_MODE_OPTS = [
  "-oEscapeChar=none",
  "-oBatchMode=yes",
  "-oStrictHostKeyChecking=yes",
  ]

ASK_KEY_OPTS = [
  "-oStrictHostKeyChecking=ask",
  "-oEscapeChar=none",
  "-oHashKnownHosts=no",
  ]

def BuildSSHCmd(hostname, user, command, batch=True, ask_key=False):
  """Build an ssh string to execute a command on a remote node.

  Args:
    hostname: the target host, string
    user: user to auth as
    command: the command
    batch: if true, ssh will run in batch mode with no prompting
    ask_key: if true, ssh will run with StrictHostKeyChecking=ask, so that
             we can connect to an unknown host (not valid in batch mode)

  Returns:
    The ssh call to run 'command' on the remote host.

  """
  argv = ["ssh", "-q"]
  argv.extend(KNOWN_HOSTS_OPTS)
  if batch:
    # if we are in batch mode, we can't ask the key
    if ask_key:
      raise errors.ProgrammerError("SSH call requested conflicting options")
    argv.extend(BATCH_MODE_OPTS)
  elif ask_key:
    argv.extend(ASK_KEY_OPTS)
  argv.extend(["%s@%s" % (user, hostname), "'%s'" % command])
  return argv


def SSHCall(hostname, user, command, batch=True, ask_key=False):
  """Execute a command on a remote node.

  This method has the same return value as `utils.RunCmd()`, which it
  uses to launch ssh.

  Args:
    hostname: the target host, string
    user: user to auth as
    command: the command
    batch: if true, ssh will run in batch mode with no prompting
    ask_key: if true, ssh will run with StrictHostKeyChecking=ask, so that
             we can connect to an unknown host (not valid in batch mode)

  Returns:
    `utils.RunResult` as for `utils.RunCmd()`

  """
  return utils.RunCmd(BuildSSHCmd(hostname, user, command, batch=batch, ask_key=ask_key))


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

  command = ["scp", "-q", "-p"]
  command.extend(KNOWN_HOSTS_OPTS)
  command.extend(BATCH_MODE_OPTS)
  command.append(filename)
  command.append("%s:%s" % (node, filename))

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
