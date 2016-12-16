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


import logging
import os
import tempfile

from collections import namedtuple
from functools import partial

from ganeti import utils
from ganeti import errors
from ganeti import constants
from ganeti import netutils
from ganeti import pathutils
from ganeti import vcluster
from ganeti import compat
from ganeti import serializer
from ganeti import ssconf


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
  elif kind == constants.SSHK_ECDSA:
    suffix = "ecdsa"
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


def _SplitSshKey(key):
  """Splits a line for SSH's C{authorized_keys} file.

  If the line has no options (e.g. no C{command="..."}), only the significant
  parts, the key type and its hash, are used. Otherwise the whole line is used
  (split at whitespace).

  @type key: string
  @param key: Key line
  @rtype: tuple

  """
  parts = key.split()

  if parts and parts[0] in constants.SSHAK_ALL:
    # If the key has no options in front of it, we only want the significant
    # fields
    return (False, parts[:2])
  else:
    # Can't properly split the line, so use everything
    return (True, parts)


def AddAuthorizedKeys(file_obj, keys):
  """Adds a list of SSH public key to an authorized_keys file.

  @type file_obj: str or file handle
  @param file_obj: path to authorized_keys file
  @type keys: list of str
  @param keys: list of strings containing keys

  """
  key_field_list = [(key, _SplitSshKey(key)) for key in keys]

  if isinstance(file_obj, basestring):
    f = open(file_obj, "a+")
  else:
    f = file_obj

  try:
    nl = True
    for line in f:
      # Ignore whitespace changes
      line_key = _SplitSshKey(line)
      key_field_list[:] = [(key, split_key) for (key, split_key)
                           in key_field_list
                           if split_key != line_key]
      nl = line.endswith("\n")

    if not nl:
      f.write("\n")
    for (key, _) in key_field_list:
      f.write(key.rstrip("\r\n"))
      f.write("\n")
    f.flush()
  finally:
    f.close()


def HasAuthorizedKey(file_obj, key):
  """Check if a particular key is in the 'authorized_keys' file.

  @type file_obj: str or file handle
  @param file_obj: path to authorized_keys file
  @type key: str
  @param key: string containing key

  """
  key_fields = _SplitSshKey(key)

  if isinstance(file_obj, basestring):
    f = open(file_obj, "r")
  else:
    f = file_obj

  try:
    for line in f:
      # Ignore whitespace changes
      line_key = _SplitSshKey(line)
      if line_key == key_fields:
        return True
  finally:
    f.close()

  return False


def CheckForMultipleKeys(file_obj, node_names):
  """Check if there is at most one key per host in 'authorized_keys' file.

  @type file_obj: str or file handle
  @param file_obj: path to authorized_keys file
  @type node_names: list of str
  @param node_names: list of names of nodes of the cluster
  @returns: a dictionary with hostnames which occur more than once

  """

  if isinstance(file_obj, basestring):
    f = open(file_obj, "r")
  else:
    f = file_obj

  occurrences = {}

  try:
    index = 0
    for line in f:
      index += 1
      if line.startswith("#"):
        continue
      chunks = line.split()
      # find the chunk with user@hostname
      user_hostname = [chunk.strip() for chunk in chunks if "@" in chunk][0]
      if not user_hostname in occurrences:
        occurrences[user_hostname] = []
      occurrences[user_hostname].append(index)
  finally:
    f.close()

  bad_occurrences = {}
  for user_hostname, occ in occurrences.items():
    _, hostname = user_hostname.split("@")
    if hostname in node_names and len(occ) > 1:
      bad_occurrences[user_hostname] = occ

  return bad_occurrences


def AddAuthorizedKey(file_obj, key):
  """Adds an SSH public key to an authorized_keys file.

  @type file_obj: str or file handle
  @param file_obj: path to authorized_keys file
  @type key: str
  @param key: string containing key

  """
  AddAuthorizedKeys(file_obj, [key])


def RemoveAuthorizedKeys(file_name, keys):
  """Removes public SSH keys from an authorized_keys file.

  @type file_name: str
  @param file_name: path to authorized_keys file
  @type keys: list of str
  @param keys: list of strings containing keys

  """
  key_field_list = [_SplitSshKey(key) for key in keys]

  fd, tmpname = tempfile.mkstemp(dir=os.path.dirname(file_name))
  try:
    out = os.fdopen(fd, "w")
    try:
      f = open(file_name, "r")
      try:
        for line in f:
          # Ignore whitespace changes while comparing lines
          if _SplitSshKey(line) not in key_field_list:
            out.write(line)

        out.flush()
        os.rename(tmpname, file_name)
      finally:
        f.close()
    finally:
      out.close()
  except:
    utils.RemoveFile(tmpname)
    raise


def RemoveAuthorizedKey(file_name, key):
  """Removes an SSH public key from an authorized_keys file.

  @type file_name: str
  @param file_name: path to authorized_keys file
  @type key: str
  @param key: string containing key

  """
  RemoveAuthorizedKeys(file_name, [key])


def _AddPublicKeyProcessLine(new_uuid, new_key, line_uuid, line_key, found):
  """Processes one line of the public key file when adding a key.

  This is a sub function that can be called within the
  C{_ManipulatePublicKeyFile} function. It processes one line of the public
  key file, checks if this line contains the key to add already and if so,
  notes the occurrence in the return value.

  @type new_uuid: string
  @param new_uuid: the node UUID of the node whose key is added
  @type new_key: string
  @param new_key: the SSH key to be added
  @type line_uuid: the UUID of the node whose line in the public key file
    is processed in this function call
  @param line_key: the SSH key of the node whose line in the public key
    file is processed in this function call
  @type found: boolean
  @param found: whether or not the (UUID, key) pair of the node whose key
    is being added was found in the public key file already.
  @rtype: (boolean, string)
  @return: a possibly updated value of C{found} and the processed line

  """
  if line_uuid == new_uuid and line_key == new_key:
    logging.debug("SSH key of node '%s' already in key file.", new_uuid)
    found = True
  return (found, "%s %s\n" % (line_uuid, line_key))


def _AddPublicKeyElse(new_uuid, new_key):
  """Adds a new SSH key to the key file if it did not exist already.

  This is an auxiliary function for C{_ManipulatePublicKeyFile} which
  is carried out when a new key is added to the public key file and
  after processing the whole file, we found out that the key does
  not exist in the file yet but needs to be appended at the end.

  @type new_uuid: string
  @param new_uuid: the UUID of the node whose key is added
  @type new_key: string
  @param new_key: the SSH key to be added
  @rtype: string
  @return: a new line to be added to the file

  """
  return "%s %s\n" % (new_uuid, new_key)


def _RemovePublicKeyProcessLine(
    target_uuid, _target_key,
    line_uuid, line_key, found):
  """Processes a line in the public key file when aiming for removing a key.

  This is an auxiliary function for C{_ManipulatePublicKeyFile} when we
  are removing a key from the public key file. This particular function
  only checks if the current line contains the UUID of the node in
  question and writes the line to the temporary file otherwise.

  @type target_uuid: string
  @param target_uuid: UUID of the node whose key is being removed
  @type _target_key: string
  @param _target_key: SSH key of the node (not used)
  @type line_uuid: string
  @param line_uuid: UUID of the node whose line is processed in this call
  @type line_key: string
  @param line_key: SSH key of the nodes whose line is processed in this call
  @type found: boolean
  @param found: whether or not the UUID was already found.
  @rtype: (boolean, string)
  @return: a tuple, indicating if the target line was found and the processed
    line; the line is 'None', if the original line is removed

  """
  if line_uuid != target_uuid:
    return (found, "%s %s\n" % (line_uuid, line_key))
  else:
    return (True, None)


def _RemovePublicKeyElse(
    target_uuid, _target_key):
  """Logs when we tried to remove a key that does not exist.

  This is an auxiliary function for C{_ManipulatePublicKeyFile} which is
  run after we have processed the complete public key file and did not find
  the key to be removed.

  @type target_uuid: string
  @param target_uuid: the UUID of the node whose key was supposed to be removed
  @type _target_key: string
  @param _target_key: the key of the node which was supposed to be removed
    (not used)
  @rtype: string
  @return: in this case, always None

  """
  logging.debug("Trying to remove key of node '%s' which is not in list"
                " of public keys.", target_uuid)
  return None


def _ReplaceNameByUuidProcessLine(
    node_name, _key, line_identifier, line_key, found, node_uuid=None):
  """Replaces a node's name with its UUID on a matching line in the key file.

  This is an auxiliary function for C{_ManipulatePublicKeyFile} which processes
  a line of the ganeti public key file. If the line in question matches the
  node's name, the name will be replaced by the node's UUID.

  @type node_name: string
  @param node_name: name of the node to be replaced by the UUID
  @type _key: string
  @param _key: SSH key of the node (not used)
  @type line_identifier: string
  @param line_identifier: an identifier of a node in a line of the public key
    file. This can be either a node name or a node UUID, depending on if it
    got replaced already or not.
  @type line_key: string
  @param line_key: SSH key of the node whose line is processed
  @type found: boolean
  @param found: whether or not the line matches the node's name
  @type node_uuid: string
  @param node_uuid: the node's UUID which will replace the node name
  @rtype: (boolean, string)
  @return: a tuple indicating whether the target line was found and the
    processed line

  """
  if node_name == line_identifier:
    return (True, "%s %s\n" % (node_uuid, line_key))
  else:
    return (found, "%s %s\n" % (line_identifier, line_key))


def _ReplaceNameByUuidElse(
    node_uuid, node_name, _key):
  """Logs a debug message when we try to replace a key that is not there.

  This is an implementation of the auxiliary C{process_else_fn} function for
  the C{_ManipulatePubKeyFile} function when we use it to replace a line
  in the public key file that is indexed by the node's name instead of the
  node's UUID.

  @type node_uuid: string
  @param node_uuid: the node's UUID
  @type node_name: string
  @param node_name: the node's UUID
  @type _key: string (not used)
  @param _key: the node's SSH key (not used)
  @rtype: string
  @return: in this case, always None

  """
  logging.debug("Trying to replace node name '%s' with UUID '%s', but"
                " no line with that name was found.", node_name, node_uuid)
  return None


def _ParseKeyLine(line, error_fn):
  """Parses a line of the public key file.

  @type line: string
  @param line: line of the public key file
  @type error_fn: function
  @param error_fn: function to process error messages
  @rtype: tuple (string, string)
  @return: a tuple containing the UUID of the node and a string containing
    the SSH key and possible more parameters for the key

  """
  if len(line.rstrip()) == 0:
    return (None, None)
  chunks = line.split(" ")
  if len(chunks) < 2:
    raise error_fn("Error parsing public SSH key file. Line: '%s'"
                   % line)
  uuid = chunks[0]
  key = " ".join(chunks[1:]).rstrip()
  return (uuid, key)


def _ManipulatePubKeyFile(target_identifier, target_key,
                          key_file=pathutils.SSH_PUB_KEYS,
                          error_fn=errors.ProgrammerError,
                          process_line_fn=None, process_else_fn=None):
  """Manipulates the list of public SSH keys of the cluster.

  This is a general function to manipulate the public key file. It needs
  two auxiliary functions C{process_line_fn} and C{process_else_fn} to
  work. Generally, the public key file is processed as follows:
  1) The function processes each line of the original ganeti public key file,
  applies the C{process_line_fn} function on it, which returns a possibly
  manipulated line and an indicator whether the line in question was found.
  If a line is returned, it is added to a list of lines for later writing
  to the file.
  2) If all lines are processed and the 'found' variable is False, the
  seconds auxiliary function C{process_else_fn} is called to possibly
  add more lines to the list of lines.
  3) Finally, the list of lines is assembled to a string and written
  atomically to the public key file, thereby overriding it.

  If the public key file does not exist, we create it. This is necessary for
  a smooth transition after an upgrade.

  @type target_identifier: str
  @param target_identifier: identifier of the node whose key is added; in most
    cases this is the node's UUID, but in some it is the node's host name
  @type target_key: str
  @param target_key: string containing a public SSH key (a complete line
    possibly including more parameters than just the key)
  @type key_file: str
  @param key_file: filename of the file of public node keys (optional
    parameter for testing)
  @type error_fn: function
  @param error_fn: Function that returns an exception, used to customize
    exception types depending on the calling context
  @type process_line_fn: function
  @param process_line_fn: function to process one line of the public key file
  @type process_else_fn: function
  @param process_else_fn: function to be called if no line of the key file
    matches the target uuid

  """
  assert process_else_fn is not None
  assert process_line_fn is not None

  old_lines = []
  f_orig = None
  if os.path.exists(key_file):
    try:
      f_orig = open(key_file, "r")
      old_lines = f_orig.readlines()
    finally:
      f_orig.close()
  else:
    try:
      f_orig = open(key_file, "w")
      f_orig.close()
    except IOError as e:
      raise errors.SshUpdateError("Cannot create public key file: %s" % e)

  found = False
  new_lines = []
  for line in old_lines:
    (uuid, key) = _ParseKeyLine(line, error_fn)
    if not uuid:
      continue
    (new_found, new_line) = process_line_fn(target_identifier, target_key,
                                            uuid, key, found)
    if new_found:
      found = True
    if new_line is not None:
      new_lines.append(new_line)
  if not found:
    new_line = process_else_fn(target_identifier, target_key)
    if new_line is not None:
      new_lines.append(new_line)
  new_file_content = "".join(new_lines)
  utils.WriteFile(key_file, data=new_file_content)


def AddPublicKey(new_uuid, new_key, key_file=pathutils.SSH_PUB_KEYS,
                 error_fn=errors.ProgrammerError):
  """Adds a new key to the list of public keys.

  @see: _ManipulatePubKeyFile for parameter descriptions.

  """
  _ManipulatePubKeyFile(new_uuid, new_key, key_file=key_file,
                        process_line_fn=_AddPublicKeyProcessLine,
                        process_else_fn=_AddPublicKeyElse,
                        error_fn=error_fn)


def RemovePublicKey(target_uuid, key_file=pathutils.SSH_PUB_KEYS,
                    error_fn=errors.ProgrammerError):
  """Removes a key from the list of public keys.

  @see: _ManipulatePubKeyFile for parameter descriptions.

  """
  _ManipulatePubKeyFile(target_uuid, None, key_file=key_file,
                        process_line_fn=_RemovePublicKeyProcessLine,
                        process_else_fn=_RemovePublicKeyElse,
                        error_fn=error_fn)


def ReplaceNameByUuid(node_uuid, node_name, key_file=pathutils.SSH_PUB_KEYS,
                      error_fn=errors.ProgrammerError):
  """Replaces a host name with the node's corresponding UUID.

  When a node is added to the cluster, we don't know it's UUID yet. So first
  its SSH key gets added to the public key file and in a second step, the
  node's name gets replaced with the node's UUID as soon as we know the UUID.

  @type node_uuid: string
  @param node_uuid: the node's UUID to replace the node's name
  @type node_name: string
  @param node_name: the node's name to be replaced by the node's UUID

  @see: _ManipulatePubKeyFile for the other parameter descriptions.

  """
  process_line_fn = partial(_ReplaceNameByUuidProcessLine, node_uuid=node_uuid)
  process_else_fn = partial(_ReplaceNameByUuidElse, node_uuid=node_uuid)
  _ManipulatePubKeyFile(node_name, None, key_file=key_file,
                        process_line_fn=process_line_fn,
                        process_else_fn=process_else_fn,
                        error_fn=error_fn)


def ClearPubKeyFile(key_file=pathutils.SSH_PUB_KEYS, mode=0600):
  """Resets the content of the public key file.

  """
  utils.WriteFile(key_file, data="", mode=mode)


def OverridePubKeyFile(key_map, key_file=pathutils.SSH_PUB_KEYS):
  """Overrides the public key file with a list of given keys.

  @type key_map: dict from str to list of str
  @param key_map: dictionary mapping uuids to lists of SSH keys

  """
  new_lines = []
  for (uuid, keys) in key_map.items():
    for key in keys:
      new_lines.append("%s %s\n" % (uuid, key))
  new_file_content = "".join(new_lines)
  utils.WriteFile(key_file, data=new_file_content)


def QueryPubKeyFile(target_uuids, key_file=pathutils.SSH_PUB_KEYS,
                    error_fn=errors.ProgrammerError):
  """Retrieves a map of keys for the requested node UUIDs.

  @type target_uuids: str or list of str
  @param target_uuids: UUID of the node to retrieve the key for or a list
    of UUIDs of nodes to retrieve the keys for
  @type key_file: str
  @param key_file: filename of the file of public node keys (optional
    parameter for testing)
  @type error_fn: function
  @param error_fn: Function that returns an exception, used to customize
    exception types depending on the calling context
  @rtype: dict mapping strings to list of strings
  @return: dictionary mapping node uuids to their ssh keys

  """
  all_keys = target_uuids is None
  if isinstance(target_uuids, str):
    target_uuids = [target_uuids]
  result = {}
  f = open(key_file, "r")
  try:
    for line in f:
      (uuid, key) = _ParseKeyLine(line, error_fn)
      if not uuid:
        continue
      if all_keys or (uuid in target_uuids):
        if uuid not in result:
          result[uuid] = []
        result[uuid].append(key)
  finally:
    f.close()
  return result


def InitSSHSetup(key_type, key_bits, error_fn=errors.OpPrereqError,
                 _homedir_fn=None, _suffix=""):
  """Setup the SSH configuration for the node.

  This generates a dsa keypair for root, adds the pub key to the
  permitted hosts and adds the hostkey to its own known hosts.

  @param key_type: the type of SSH keypair to be generated
  @param key_bits: the key length, in bits, to be used

  """
  priv_key, _, auth_keys = GetUserFiles(constants.SSH_LOGIN_USER, kind=key_type,
                                        mkdir=True, _homedir_fn=_homedir_fn)

  new_priv_key_name = priv_key + _suffix
  new_pub_key_name = priv_key + _suffix + ".pub"

  for name in new_priv_key_name, new_pub_key_name:
    if os.path.exists(name):
      utils.CreateBackup(name)
    utils.RemoveFile(name)

  result = utils.RunCmd(["ssh-keygen", "-b", str(key_bits), "-t", key_type,
                         "-f", new_priv_key_name,
                         "-q", "-N", ""])
  if result.failed:
    raise error_fn("Could not generate ssh keypair, error %s" %
                   result.output)

  AddAuthorizedKey(auth_keys, utils.ReadFile(new_pub_key_name))


def InitPubKeyFile(master_uuid, key_type, key_file=pathutils.SSH_PUB_KEYS):
  """Creates the public key file and adds the master node's SSH key.

  @type master_uuid: str
  @param master_uuid: the master node's UUID
  @type key_type: one of L{constants.SSHK_ALL}
  @param key_type: the type of ssh key to be used
  @type key_file: str
  @param key_file: name of the file containing the public keys

  """
  _, pub_key, _ = GetUserFiles(constants.SSH_LOGIN_USER, kind=key_type)
  ClearPubKeyFile(key_file=key_file)
  key = utils.ReadFile(pub_key)
  AddPublicKey(master_uuid, key, key_file=key_file)


class SshRunner(object):
  """Wrapper for SSH commands.

  """
  def __init__(self, cluster_name):
    """Initializes this class.

    @type cluster_name: str
    @param cluster_name: name of the cluster

    """
    self.cluster_name = cluster_name
    family = ssconf.SimpleStore().GetPrimaryIPFamily()
    self.ipv6 = (family == netutils.IP6Address.family)

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


def _EnsureCorrectGanetiVersion(cmd):
  """Ensured the correct Ganeti version before running a command via SSH.

  Before a command is run on a node via SSH, it makes sense in some
  situations to ensure that this node is indeed running the correct
  version of Ganeti like the rest of the cluster.

  @type cmd: string
  @param cmd: string
  @rtype: list of strings
  @return: a list of commands with the newly added ones at the beginning

  """
  logging.debug("Ensure correct Ganeti version: %s", cmd)

  version = constants.DIR_VERSION
  all_cmds = [["test", "-d", os.path.join(pathutils.PKGLIBDIR, version)]]
  if constants.HAS_GNU_LN:
    all_cmds.extend([["ln", "-s", "-f", "-T",
                      os.path.join(pathutils.PKGLIBDIR, version),
                      os.path.join(pathutils.SYSCONFDIR, "ganeti/lib")],
                     ["ln", "-s", "-f", "-T",
                      os.path.join(pathutils.SHAREDIR, version),
                      os.path.join(pathutils.SYSCONFDIR, "ganeti/share")]])
  else:
    all_cmds.extend([["rm", "-f",
                      os.path.join(pathutils.SYSCONFDIR, "ganeti/lib")],
                     ["ln", "-s", "-f",
                      os.path.join(pathutils.PKGLIBDIR, version),
                      os.path.join(pathutils.SYSCONFDIR, "ganeti/lib")],
                     ["rm", "-f",
                      os.path.join(pathutils.SYSCONFDIR, "ganeti/share")],
                     ["ln", "-s", "-f",
                      os.path.join(pathutils.SHAREDIR, version),
                      os.path.join(pathutils.SYSCONFDIR, "ganeti/share")]])
  all_cmds.append(cmd)
  return all_cmds


def RunSshCmdWithStdin(cluster_name, node, basecmd, port, data,
                       debug=False, verbose=False, use_cluster_key=False,
                       ask_key=False, strict_host_check=False,
                       ensure_version=False):
  """Runs a command on a remote machine via SSH and provides input in stdin.

  @type cluster_name: string
  @param cluster_name: Cluster name
  @type node: string
  @param node: Node name
  @type basecmd: string
  @param basecmd: Base command (path on the remote machine)
  @type port: int
  @param port: The SSH port of the remote machine or None for the default
  @param data: JSON-serializable input data for script (passed to stdin)
  @type debug: bool
  @param debug: Enable debug output
  @type verbose: bool
  @param verbose: Enable verbose output
  @type use_cluster_key: bool
  @param use_cluster_key: See L{ssh.SshRunner.BuildCmd}
  @type ask_key: bool
  @param ask_key: See L{ssh.SshRunner.BuildCmd}
  @type strict_host_check: bool
  @param strict_host_check: See L{ssh.SshRunner.BuildCmd}

  """
  cmd = [basecmd]

  # Pass --debug/--verbose to the external script if set on our invocation
  if debug:
    cmd.append("--debug")

  if verbose:
    cmd.append("--verbose")

  if ensure_version:
    all_cmds = _EnsureCorrectGanetiVersion(cmd)
  else:
    all_cmds = [cmd]

  if port is None:
    port = netutils.GetDaemonPort(constants.SSH)

  srun = SshRunner(cluster_name)
  scmd = srun.BuildCmd(node, constants.SSH_LOGIN_USER,
                       utils.ShellQuoteArgs(
                           utils.ShellCombineCommands(all_cmds)),
                       batch=False, ask_key=ask_key, quiet=False,
                       strict_host_check=strict_host_check,
                       use_cluster_key=use_cluster_key,
                       port=port)

  tempfh = tempfile.TemporaryFile()
  try:
    tempfh.write(serializer.DumpJson(data))
    tempfh.seek(0)

    result = utils.RunCmd(scmd, interactive=True, input_fd=tempfh)
  finally:
    tempfh.close()

  if result.failed:
    raise errors.OpExecError("Command '%s' failed: %s" %
                             (result.cmd, result.fail_reason))


def ReadRemoteSshPubKeys(pub_key_file, node, cluster_name, port, ask_key,
                         strict_host_check):
  """Fetches a public SSH key from a node via SSH.

  @type pub_key_file: string
  @param pub_key_file: a tuple consisting of the file name of the public DSA key

  """
  ssh_runner = SshRunner(cluster_name)

  cmd = ["cat", pub_key_file]
  ssh_cmd = ssh_runner.BuildCmd(node, constants.SSH_LOGIN_USER,
                                utils.ShellQuoteArgs(cmd),
                                batch=False, ask_key=ask_key, quiet=False,
                                strict_host_check=strict_host_check,
                                use_cluster_key=False,
                                port=port)

  result = utils.RunCmd(ssh_cmd)
  if result.failed:
    raise errors.OpPrereqError("Could not fetch a public SSH key (%s) from node"
                               " '%s': ran command '%s', failure reason: '%s'."
                               % (pub_key_file, node, cmd, result.fail_reason),
                               errors.ECODE_INVAL)
  return result.stdout


# Update gnt-cluster.rst when changing which combinations are valid.
KeyBitInfo = namedtuple('KeyBitInfo', ['default', 'validation_fn'])
SSH_KEY_VALID_BITS = {
  constants.SSHK_DSA: KeyBitInfo(1024, lambda b: b == 1024),
  constants.SSHK_RSA: KeyBitInfo(2048, lambda b: b >= 768),
  constants.SSHK_ECDSA: KeyBitInfo(384, lambda b: b in [256, 384, 521]),
}


def DetermineKeyBits(key_type, key_bits, old_key_type, old_key_bits):
  """Checks the key bits to be used for a given key type, or provides defaults.

  @type key_type: one of L{constants.SSHK_ALL}
  @param key_type: The key type to use.
  @type key_bits: positive int or None
  @param key_bits: The number of bits to use, if supplied by user.
  @type old_key_type: one of L{constants.SSHK_ALL} or None
  @param old_key_type: The previously used key type, if any.
  @type old_key_bits: positive int or None
  @param old_key_bits: The previously used number of bits, if any.

  @rtype: positive int
  @return: The number of bits to use.

  """
  if key_bits is None:
    if old_key_type is not None and old_key_type == key_type:
      key_bits = old_key_bits
    else:
      key_bits = SSH_KEY_VALID_BITS[key_type].default

  if not SSH_KEY_VALID_BITS[key_type].validation_fn(key_bits):
    raise errors.OpPrereqError("Invalid key type and bit size combination:"
                               " %s with %s bits" % (key_type, key_bits),
                               errors.ECODE_INVAL)

  return key_bits
