#
#

# Copyright (C) 2006, 2007, 2010, 2011 Google Inc.
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


"""Module encapsulating ssh functionality.

"""


import os
import logging

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import netutils
from ganeti import pathutils
from ganeti import vcluster
from ganeti import compat


def GetUserFiles(user, mkdir=False, dircheck=True, kind=constants.SSHK_DSA,
                 _homedir_fn=None):
  """Return the paths of a user's SSH files.

  @type user: string
  @param user: Username
  @type mkdir: bool
  @param mkdir: Whether to create ".ssh" directory if it doesn't exist
  @type dircheck: bool
  @param dircheck: Whether to check if ".ssh" directory exists
  @type kind: string
  @param kind: One of L{constants.SSHK_ALL}
  @rtype: tuple; (string, string, string)
  @return: Tuple containing three file system paths; the private SSH key file,
    the public SSH key file and the user's C{authorized_keys} file
  @raise errors.OpExecError: When home directory of the user can not be
    determined
  @raise errors.OpExecError: Regardless of the C{mkdir} parameters, this
    exception is raised if C{~$user/.ssh} is not a directory and C{dircheck}
    is set to C{True}

  """
  if _homedir_fn is None:
    _homedir_fn = utils.GetHomeDir

  user_dir = _homedir_fn(user)
  if not user_dir:
    raise errors.OpExecError("Cannot resolve home of user '%s'" % user)

  if kind == constants.SSHK_DSA:
    suffix = "dsa"
  elif kind == constants.SSHK_RSA:
    suffix = "rsa"
  else:
    raise errors.ProgrammerError("Unknown SSH key kind '%s'" % kind)

  ssh_dir = utils.PathJoin(user_dir, ".ssh")
  if mkdir:
    utils.EnsureDirs([(ssh_dir, constants.SECURE_DIR_MODE)])
  elif dircheck and not os.path.isdir(ssh_dir):
    raise errors.OpExecError("Path %s is not a directory" % ssh_dir)

  return [utils.PathJoin(ssh_dir, base)
          for base in ["id_%s" % suffix, "id_%s.pub" % suffix,
                       "authorized_keys"]]


def GetAllUserFiles(user, mkdir=False, dircheck=True, _homedir_fn=None):
  """Wrapper over L{GetUserFiles} to retrieve files for all SSH key types.

  See L{GetUserFiles} for details.

  @rtype: tuple; (string, dict with string as key, tuple of (string, string) as
    value)

  """
  helper = compat.partial(GetUserFiles, user, mkdir=mkdir, dircheck=dircheck,
                          _homedir_fn=_homedir_fn)
  result = [(kind, helper(kind=kind)) for kind in constants.SSHK_ALL]

  authorized_keys = [i for (_, (_, _, i)) in result]

  assert len(frozenset(authorized_keys)) == 1, \
    "Different paths for authorized_keys were returned"

  return (authorized_keys[0],
          dict((kind, (privkey, pubkey))
               for (kind, (privkey, pubkey, _)) in result))


def InitSSHSetup(error_fn=errors.OpPrereqError):
  """Setup the SSH configuration for the node.

  This generates a dsa keypair for root, adds the pub key to the
  permitted hosts and adds the hostkey to its own known hosts.

  """
  priv_key, pub_key, auth_keys = GetUserFiles(constants.SSH_LOGIN_USER)

  for name in priv_key, pub_key:
    if os.path.exists(name):
      utils.CreateBackup(name)
    utils.RemoveFile(name)

  result = utils.RunCmd(["ssh-keygen", "-t", "dsa",
                         "-f", priv_key,
                         "-q", "-N", ""])
  if result.failed:
    raise error_fn("Could not generate ssh keypair, error %s" %
                   result.output)

  utils.AddAuthorizedKey(auth_keys, utils.ReadFile(pub_key))


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
                       strict_host_check, private_key=None, quiet=True,
                       port=None):
    """Builds a list with needed SSH options.

    @param batch: same as ssh's batch option
    @param ask_key: allows ssh to ask for key confirmation; this
        parameter conflicts with the batch one
    @param use_cluster_key: if True, use the cluster name as the
        HostKeyAlias name
    @param strict_host_check: this makes the host key checking strict
    @param private_key: use this private key instead of the default
    @param quiet: whether to enable -q to ssh
    @param port: the SSH port to use, or None to use the default

    @rtype: list
    @return: the list of options ready to use in L{utils.process.RunCmd}

    """
    options = [
      "-oEscapeChar=none",
      "-oHashKnownHosts=no",
      "-oGlobalKnownHostsFile=%s" % pathutils.SSH_KNOWN_HOSTS_FILE,
      "-oUserKnownHostsFile=/dev/null",
      "-oCheckHostIp=no",
      ]

    if use_cluster_key:
      options.append("-oHostKeyAlias=%s" % self.cluster_name)

    if quiet:
      options.append("-q")

    if private_key:
      options.append("-i%s" % private_key)

    if port:
      options.append("-oPort=%d" % port)

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
    else:
      options.append("-4")

    return options

  def BuildCmd(self, hostname, user, command, batch=True, ask_key=False,
               tty=False, use_cluster_key=True, strict_host_check=True,
               private_key=None, quiet=True, port=None):
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
    @param port: the SSH port on which the node's daemon is running

    @return: the ssh call to run 'command' on the remote host.

    """
    argv = [constants.SSH]
    argv.extend(self._BuildSshOptions(batch, ask_key, use_cluster_key,
                                      strict_host_check, private_key,
                                      quiet=quiet, port=port))
    if tty:
      argv.extend(["-t", "-t"])

    argv.append("%s@%s" % (user, hostname))

    # Insert variables for virtual nodes
    argv.extend("export %s=%s;" %
                (utils.ShellQuote(name), utils.ShellQuote(value))
                for (name, value) in
                  vcluster.EnvironmentForHost(hostname).items())

    argv.append(command)

    return argv

  def Run(self, *args, **kwargs):
    """Runs a command on a remote node.

    This method has the same return value as `utils.RunCmd()`, which it
    uses to launch ssh.

    Args: see SshRunner.BuildCmd.

    @rtype: L{utils.process.RunResult}
    @return: the result as from L{utils.process.RunCmd()}

    """
    return utils.RunCmd(self.BuildCmd(*args, **kwargs))

  def CopyFileToNode(self, node, port, filename):
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
    command.extend(self._BuildSshOptions(True, False, True, True, port=port))
    command.append(filename)
    if netutils.IP6Address.IsValid(node):
      node = netutils.FormatAddress((node, None))

    command.append("%s:%s" % (node, vcluster.ExchangeNodeRoot(node, filename)))

    result = utils.RunCmd(command)

    if result.failed:
      logging.error("Copy to node %s failed (%s) error '%s',"
                    " command was '%s'",
                    node, result.fail_reason, result.output, result.cmd)

    return not result.failed

  def VerifyNodeHostname(self, node, ssh_port):
    """Verify hostname consistency via SSH.

    This functions connects via ssh to a node and compares the hostname
    reported by the node to the name with have (the one that we
    connected to).

    This is used to detect problems in ssh known_hosts files
    (conflicting known hosts) and inconsistencies between dns/hosts
    entries and local machine names

    @param node: nodename of a host to check; can be short or
        full qualified hostname
    @param ssh_port: the port of a SSH daemon running on the node

    @return: (success, detail), where:
        - success: True/False
        - detail: string with details

    """
    cmd = ("if test -z \"$GANETI_HOSTNAME\"; then"
           "  hostname --fqdn;"
           "else"
           "  echo \"$GANETI_HOSTNAME\";"
           "fi")
    retval = self.Run(node, constants.SSH_LOGIN_USER, cmd,
                      quiet=False, port=ssh_port)

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
  data = ""
  if cfg.GetRsaHostKey():
    data += "%s ssh-rsa %s\n" % (cfg.GetClusterName(), cfg.GetRsaHostKey())
  if cfg.GetDsaHostKey():
    data += "%s ssh-dss %s\n" % (cfg.GetClusterName(), cfg.GetDsaHostKey())

  utils.WriteFile(file_name, mode=0600, data=data)
