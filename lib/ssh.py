#
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

from ganeti import utils
from ganeti import errors
from ganeti import constants


def GetUserFiles(user, mkdir=False):
  """Return the paths of a user's ssh files.

  The function will return a triplet (priv_key_path, pub_key_path,
  auth_key_path) that are used for ssh authentication. Currently, the
  keys used are DSA keys, so this function will return:
  (~user/.ssh/id_dsa, ~user/.ssh/id_dsa.pub,
  ~user/.ssh/authorized_keys).

  If the optional parameter mkdir is True, the ssh directory will be
  created if it doesn't exist.

  Regardless of the mkdir parameters, the script will raise an error
  if ~user/.ssh is not a directory.

  """
  user_dir = utils.GetHomeDir(user)
  if not user_dir:
    raise errors.OpExecError("Cannot resolve home of user %s" % user)

  ssh_dir = os.path.join(user_dir, ".ssh")
  if not os.path.lexists(ssh_dir):
    if mkdir:
      try:
        os.mkdir(ssh_dir, 0700)
      except EnvironmentError, err:
        raise errors.OpExecError("Can't create .ssh dir for user %s: %s" %
                                 (user, str(err)))
  elif not os.path.isdir(ssh_dir):
    raise errors.OpExecError("path ~%s/.ssh is not a directory" % user)

  return [os.path.join(ssh_dir, base)
          for base in ["id_dsa", "id_dsa.pub", "authorized_keys"]]


class SshRunner:
  """Wrapper for SSH commands.

  """
  def __init__(self, cluster_name):
    self.cluster_name = cluster_name

  def _BuildSshOptions(self, batch, ask_key, use_cluster_key,
                       strict_host_check):
    options = [
      "-oEscapeChar=none",
      "-oHashKnownHosts=no",
      "-oGlobalKnownHostsFile=%s" % constants.SSH_KNOWN_HOSTS_FILE,
      "-oUserKnownHostsFile=/dev/null",
      ]

    if use_cluster_key:
      options.append("-oHostKeyAlias=%s" % self.cluster_name)

    # TODO: Too many boolean options, maybe convert them to more descriptive
    # constants.

    # Note: ask_key conflicts with batch mode
    if batch:
      if ask_key:
        raise errors.ProgrammerError("SSH call requested conflicting options")

      options.append("-oBatchMode=yes")

      if strict_host_check:
        options.append("-oStrictHostKeyChecking=yes")
      else:
        options.append("-oStrictHostKeyChecking=no")

    elif ask_key:
      options.extend([
        "-oStrictHostKeyChecking=ask",
        ])

    return options

  def BuildCmd(self, hostname, user, command, batch=True, ask_key=False,
               tty=False, use_cluster_key=True, strict_host_check=True):
    """Build an ssh command to execute a command on a remote node.

    Args:
      hostname: the target host, string
      user: user to auth as
      command: the command
      batch: if true, ssh will run in batch mode with no prompting
      ask_key: if true, ssh will run with StrictHostKeyChecking=ask, so that
               we can connect to an unknown host (not valid in batch mode)
      use_cluster_key: Whether to expect and use the cluster-global SSH key
      strict_host_check: Whether to check the host's SSH key at all

    Returns:
      The ssh call to run 'command' on the remote host.

    """
    argv = [constants.SSH, "-q"]
    argv.extend(self._BuildSshOptions(batch, ask_key, use_cluster_key,
                                      strict_host_check))
    if tty:
      argv.append("-t")
    argv.extend(["%s@%s" % (user, hostname), command])
    return argv

  def Run(self, *args, **kwargs):
    """Runs a command on a remote node.

    This method has the same return value as `utils.RunCmd()`, which it
    uses to launch ssh.

    Args:
      See SshRunner.BuildCmd.

    Returns:
      `utils.RunResult` like `utils.RunCmd()`

    """
    return utils.RunCmd(self.BuildCmd(*args, **kwargs))

  def CopyFileToNode(self, node, filename):
    """Copy a file to another node with scp.

    Args:
      node: node in the cluster
      filename: absolute pathname of a local file

    Returns:
      success: True/False

    """
    if not os.path.isabs(filename):
      logging.error("File %s must be an absolute path", filename)
      return False

    if not os.path.isfile(filename):
      logging.error("File %s does not exist", filename)
      return False

    command = [constants.SCP, "-q", "-p"]
    command.extend(self._BuildSshOptions(True, False, True, True))
    command.append(filename)
    command.append("%s:%s" % (node, filename))

    result = utils.RunCmd(command)

    if result.failed:
      logging.error("Copy to node %s failed (%s) error %s,"
                    " command was %s",
                    node, result.fail_reason, result.output, result.cmd)

    return not result.failed

  def VerifyNodeHostname(self, node):
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
    retval = self.Run(node, 'root', 'hostname')

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


def WriteKnownHostsFile(cfg, file_name):
  """Writes the cluster-wide equally known_hosts file.

  """
  utils.WriteFile(file_name, mode=0700,
                  data="%s ssh-rsa %s\n" % (cfg.GetClusterName(),
                                            cfg.GetHostKey()))
