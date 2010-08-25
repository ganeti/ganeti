#
#

# Copyright (C) 2006, 2007, 2010 Google Inc.
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
import logging
import re

from ganeti import utils
from ganeti import errors
from ganeti import constants


def FormatParamikoFingerprint(fingerprint):
  """Formats the fingerprint of L{paramiko.PKey.get_fingerprint()}

  @type fingerprint: str
  @param fingerprint: PKey fingerprint
  @return The string hex representation of the fingerprint

  """
  assert len(fingerprint) % 2 == 0
  return ":".join(re.findall(r"..", fingerprint.lower()))


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

  ssh_dir = utils.PathJoin(user_dir, ".ssh")
  if mkdir:
    utils.EnsureDirs([(ssh_dir, constants.SECURE_DIR_MODE)])
  elif not os.path.isdir(ssh_dir):
    raise errors.OpExecError("Path %s is not a directory" % ssh_dir)

  return [utils.PathJoin(ssh_dir, base)
          for base in ["id_dsa", "id_dsa.pub", "authorized_keys"]]


class SshRunner:
  """Wrapper for SSH commands.

  """
  def __init__(self, cluster_name, ipv6=False):
    """Initializes this class.

    @type cluster_name: str
    @param cluster_name: name of the cluster
    @type ipv6: bool
    @param ipv6: If true, force ssh to use IPv6 addresses only

    """
    self.cluster_name = cluster_name
    self.ipv6 = ipv6

  def _BuildSshOptions(self, batch, ask_key, use_cluster_key,
                       strict_host_check, private_key=None, quiet=True):
    """Builds a list with needed SSH options.

    @param batch: same as ssh's batch option
    @param ask_key: allows ssh to ask for key confirmation; this
        parameter conflicts with the batch one
    @param use_cluster_key: if True, use the cluster name as the
        HostKeyAlias name
    @param strict_host_check: this makes the host key checking strict
    @param private_key: use this private key instead of the default
    @param quiet: whether to enable -q to ssh

    @rtype: list
    @return: the list of options ready to use in L{utils.RunCmd}

    """
    options = [
      "-oEscapeChar=none",
      "-oHashKnownHosts=no",
      "-oGlobalKnownHostsFile=%s" % constants.SSH_KNOWN_HOSTS_FILE,
      "-oUserKnownHostsFile=/dev/null",
      "-oCheckHostIp=no",
      ]

    if use_cluster_key:
      options.append("-oHostKeyAlias=%s" % self.cluster_name)

    if quiet:
      options.append("-q")

    if private_key:
      options.append("-i%s" % private_key)

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

    else:
      # non-batch mode

      if ask_key:
        options.append("-oStrictHostKeyChecking=ask")
      elif strict_host_check:
        options.append("-oStrictHostKeyChecking=yes")
      else:
        options.append("-oStrictHostKeyChecking=no")

    if self.ipv6:
      options.append("-6")

    return options

  def BuildCmd(self, hostname, user, command, batch=True, ask_key=False,
               tty=False, use_cluster_key=True, strict_host_check=True,
               private_key=None, quiet=True):
    """Build an ssh command to execute a command on a remote node.

    @param hostname: the target host, string
    @param user: user to auth as
    @param command: the command
    @param batch: if true, ssh will run in batch mode with no prompting
    @param ask_key: if true, ssh will run with
        StrictHostKeyChecking=ask, so that we can connect to an
        unknown host (not valid in batch mode)
    @param use_cluster_key: whether to expect and use the
        cluster-global SSH key
    @param strict_host_check: whether to check the host's SSH key at all
    @param private_key: use this private key instead of the default
    @param quiet: whether to enable -q to ssh

    @return: the ssh call to run 'command' on the remote host.

    """
    argv = [constants.SSH]
    argv.extend(self._BuildSshOptions(batch, ask_key, use_cluster_key,
                                      strict_host_check, private_key,
                                      quiet=quiet))
    if tty:
      argv.extend(["-t", "-t"])
    argv.extend(["%s@%s" % (user, hostname), command])
    return argv

  def Run(self, *args, **kwargs):
    """Runs a command on a remote node.

    This method has the same return value as `utils.RunCmd()`, which it
    uses to launch ssh.

    Args: see SshRunner.BuildCmd.

    @rtype: L{utils.RunResult}
    @return: the result as from L{utils.RunCmd()}

    """
    return utils.RunCmd(self.BuildCmd(*args, **kwargs))

  def CopyFileToNode(self, node, filename):
    """Copy a file to another node with scp.

    @param node: node in the cluster
    @param filename: absolute pathname of a local file

    @rtype: boolean
    @return: the success of the operation

    """
    if not os.path.isabs(filename):
      logging.error("File %s must be an absolute path", filename)
      return False

    if not os.path.isfile(filename):
      logging.error("File %s does not exist", filename)
      return False

    command = [constants.SCP, "-p"]
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
    (conflicting known hosts) and inconsistencies between dns/hosts
    entries and local machine names

    @param node: nodename of a host to check; can be short or
        full qualified hostname

    @return: (success, detail), where:
        - success: True/False
        - detail: string with details

    """
    retval = self.Run(node, 'root', 'hostname --fqdn')

    if retval.failed:
      msg = "ssh problem"
      output = retval.output
      if output:
        msg += ": %s" % output
      else:
        msg += ": %s (no output)" % retval.fail_reason
      logging.error("Command %s failed: %s", retval.cmd, msg)
      return False, msg

    remotehostname = retval.stdout.strip()

    if not remotehostname or remotehostname != node:
      if node.startswith(remotehostname + "."):
        msg = "hostname not FQDN"
      else:
        msg = "hostname mismatch"
      return False, ("%s: expected %s but got %s" %
                     (msg, node, remotehostname))

    return True, "host matches"


def WriteKnownHostsFile(cfg, file_name):
  """Writes the cluster-wide equally known_hosts file.

  """
  utils.WriteFile(file_name, mode=0600,
                  data="%s ssh-rsa %s\n" % (cfg.GetClusterName(),
                                            cfg.GetHostKey()))
