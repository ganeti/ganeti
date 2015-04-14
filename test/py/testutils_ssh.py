#!/usr/bin/python
#

# Copyright (C) 2010, 2013, 2015 Google Inc.
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


"""Helper class to test ssh-related code."""

from ganeti import constants
from ganeti import pathutils


class FakeSshFileManager(object):
  """Class which 'fakes' the lowest layer of SSH key manipulation.

  There are various operations which touch the nodes' SSH keys and their
  respective key files (authorized_keys and ganeti_pub_keys). Those are
  tedious to test as file operations have to be mocked on different levels
  (direct access to the authorized_keys and ganeti_pub_keys) of the master
  node, indirect access to those files of the non-master nodes (via the
  ssh_update tool). In order to make unit tests of those operations more
  readable and managable, we introduce this class, which mocks all
  direct and indirect access to SSH key files on all nodes. This way,
  the state of this FakeSshFileManager represents the state of a cluster's
  nodes' SSH key files in a consise and easily accessible way.

  """
  def __init__(self):
    # Dictionary mapping node name to node properties. The properties
    # are a tuple of (node_uuid, ssh_key, is_potential_master_candidate,
    # is_master_candidate, is_master).
    self._all_node_data = {}
    # Dictionary emulating the authorized keys files of all nodes. The
    # indices of the dictionary are the node names, the values are sets
    # of keys (strings).
    self._authorized_keys = {}
    # Dictionary emulating the public keys file of all nodes. The indices
    # of the dictionary are the node names where the public key file is
    # 'located' (if it wasn't faked). The values of the dictionary are
    # dictionaries itself. Each of those dictionaries is indexed by the
    # node UUIDs mapping to a list of public keys.
    self._public_keys = {} # dict of dicts
    # Node name of the master node
    self._master_node_name = None

  def _SetMasterNodeName(self):
    self._master_node_name = [name for name, (_, _, _, _, master)
                              in self._all_node_data.items() if master][0]

  def GetMasterNodeName(self):
    return self._master_node_name

  def _CreateNodeDict(self, num_nodes, num_pot_mcs, num_mcs):
    """Creates a dictionary of all nodes and their properties."""

    self._all_node_data = {}
    for i in range(num_nodes):
      name = "node_name_%i" % i
      uuid = "node_uuid_%i" % i
      key = "key%s" % i
      self._public_keys[name] = {}
      self._authorized_keys[name] = set()

      pot_mc = i < num_pot_mcs
      mc = i < num_mcs
      master = i == num_mcs / 2

      self._all_node_data[name] = (uuid, key, pot_mc, mc, master)

  def _FillPublicKeyOfOneNode(self, receiving_node_name):
    _, _, is_pot_mc, _, _ = self._all_node_data[receiving_node_name]
    # Nodes which are not potential master candidates receive no keys
    if not is_pot_mc:
      return
    for uuid, key, pot_mc, _, _ in self._all_node_data.values():
      if pot_mc:
        self._public_keys[receiving_node_name][uuid] = key

  def _FillAuthorizedKeyOfOneNode(self, receiving_node_name):
    for _, key, _, mc, _ in self._all_node_data.values():
      if mc:
        self._authorized_keys[receiving_node_name].add(key)

  def InitAllNodes(self, num_nodes, num_pot_mcs, num_mcs):
    """Initializes the entire state of the cluster wrt SSH keys.

    @type num_nodes: int
    @param num_nodes: number of nodes in the cluster
    @type num_pot_mcs: int
    @param num_pot_mcs: number of potential master candidates in the cluster
    @type num_mcs: in
    @param num_mcs: number of master candidates in the cluster.

    """
    self._public_keys = {}
    self._authorized_keys = {}
    self._CreateNodeDict(num_nodes, num_pot_mcs, num_mcs)
    for node in self._all_node_data.keys():
      self._FillPublicKeyOfOneNode(node)
      self._FillAuthorizedKeyOfOneNode(node)
    self._SetMasterNodeName()

  def GetSshPortMap(self, port):
    """Creates a SSH port map with all nodes mapped to the given port.

    @type port: int
    @param port: SSH port number for all nodes

    """
    port_map = {}
    for node in self._all_node_data.keys():
      port_map[node] = port
    return port_map

  def GetAllNodeNames(self):
    return self._all_node_data.keys()

  def GetAllPotentialMasterCandidateNodeNames(self):
    return [name for name, (_, _, pot_mc, _, _)
            in self._all_node_data.items() if pot_mc]

  def GetAllMasterCandidateUuids(self):
    return [uuid for uuid, _, _, mc, _
            in self._all_node_data.values() if mc]

  def GetAllPotentialMasterCandidates(self):
    return [(name, uuid, key, pot_mc, mc, master)
            for name, (uuid, key, pot_mc, mc, master)
            in self._all_node_data.items() if pot_mc]

  def SetOrAddNode(self, name, uuid, key, pot_mc, mc, master):
    """Adds a new node to the state of the file manager.

    This is necessary when testing to add new nodes to the cluster. Otherwise
    this new node's state would not be evaluated properly with the assertion
    fuctions.

    @type name: string
    @param name: name of the new node
    @type uuid: string
    @param uuid: UUID of the new node
    @type key: string
    @param key: SSH key of the new node
    @type pot_mc: boolean
    @param pot_mc: whether the new node is a potential master candidate
    @type mc: boolean
    @param mc: whether the new node is a master candidate
    @type master: boolean
    @param master: whether the new node is the master

    """
    self._all_node_data[name] = (uuid, key, pot_mc, mc, master)
    if name not in self._authorized_keys:
      self._authorized_keys[name] = set()
    if mc:
      self._authorized_keys[name].add(key)
    if name not in self._public_keys:
      self._public_keys[name] = {}

  def NodeHasPublicKey(self, file_node_name, key_node_uuid, key):
    """Checks whether a node has another node's public key.

    @type file_node_name: string
    @param file_node_name: name of the node whose public key file is inspected
    @type key_node_uuid: string
    @param key_node_uuid: UUID of the node whose key is checked for
    @rtype: boolean
    @return: True if the key_node's UUID is found with the machting key 'key'

    """
    for (node_uuid, pub_keys) in self._public_keys[file_node_name].items():
      if key in pub_keys and key_node_uuid == node_uuid:
        return True
    return False

  def NodeHasAuthorizedKey(self, file_node_name, key):
    """Checks whether a node has a particular key in its authorized_keys file.

    @type file_node_name: string
    @param file_node_name: name of the node whose authorized_key file is
      inspected
    @type key: string
    @param key: key which is expected to be found in the node's authorized_key
      file
    @rtype: boolean
    @return: True if the key is found in the node's authorized_key file

    """
    return key in self._authorized_keys[file_node_name]

  def AllNodesHaveAuthorizedKey(self, key):
    """Check if all nodes have a particular key in their auth. keys file.

    @type key: string
    @param key: key exptected to be present in all node's authorized_keys file
    @rtype: boolean
    @return: True if key is present in all node's authorized_keys file

    """
    for name in self._all_node_data.keys():
      if key not in self._authorized_keys[name]:
        raise Exception("Node '%s' does not have the key '%s' in its"
                        " 'authorized_keys' file." % (name, key))
    return True

  def NoNodeHasAuthorizedKey(self, key):
    """Check if none of the nodes has a particular key in their auth. keys file.

    @type key: string
    @param key: key exptected to be present in all node's authorized_keys file
    @rtype: boolean
    @return: True if key is not present in all node's authorized_keys file

    """
    for name in self._all_node_data.keys():
      node_auth_keys = self._authorized_keys[name]
      if key in node_auth_keys:
        return False
    return True

  def NoNodeHasPublicKey(self, uuid, key):
    """Check if none of the nodes have the given public key in their file.

    @type uuid: string
    @param uuid: UUID of the node whose key is looked for
    @type key: string
    @param key: SSH key to be looked for

    """
    for name in self._all_node_data.keys():
      node_pub_keys = self._public_keys[name]
      if (uuid, key) in node_pub_keys.items():
        return False
    return True

  def PotentialMasterCandidatesOnlyHavePublicKey(self, query_node_name):
    """Checks if the node's key is on all potential master candidates only.

    This ensures that the node's key is in all public key files of all
    potential master candidates, and it also checks whether the key is
    *not* in all other nodes's key files.

    @param query_node_name: name of the node whose key is expected to be
                            in the public key file of all potential master
                            candidates
    @type query_node_name: string

    """
    query_node_uuid, query_node_key, _, _, _ = \
        self._all_node_data[query_node_name]
    for name, (_, _, pot_mc, _, _) in self._all_node_data.items():
      has_key = self.NodeHasPublicKey(name, query_node_uuid, query_node_key)
      if pot_mc:
        if not has_key:
          raise Exception("Potential master candidate '%s' does not have the"
                          " key.")
      else:
        if has_key:
          raise Exception("Normal node (not potential master candidate) '%s'"
                          " does have the key, although it should not have.")

  # Disabling a pylint warning about unused parameters. Those need
  # to be here to properly mock the real methods.
  # pylint: disable=W0613
  def RunCommand(self, cluster_name, node, base_cmd, port, data,
                 debug=False, verbose=False, use_cluster_key=False,
                 ask_key=False, strict_host_check=False,
                 ensure_version=False):
    """This emulates ssh.RunSshCmdWithStdin calling ssh_update.

    While in real SSH operations, ssh.RunSshCmdWithStdin is called
    with the command ssh_update to manipulate a remote node's SSH
    key files (authorized_keys and ganeti_pub_key) file, this method
    emulates the operation by manipulating only its internal dictionaries
    of SSH keys. No actual key files of any node is touched.

    """
    assert base_cmd == pathutils.SSH_UPDATE

    if constants.SSHS_SSH_AUTHORIZED_KEYS in data:
      instructions_auth = data[constants.SSHS_SSH_AUTHORIZED_KEYS]
      self._HandleAuthorizedKeys(instructions_auth, node)
    if constants.SSHS_SSH_PUBLIC_KEYS in data:
      instructions_pub = data[constants.SSHS_SSH_PUBLIC_KEYS]
      self._HandlePublicKeys(instructions_pub, node)
  # pylint: enable=W0613

  def _EnsureAuthKeyFile(self, file_node_name):
    if file_node_name not in self._authorized_keys:
      self._authorized_keys[file_node_name] = set()

  def _AddAuthorizedKey(self, file_node_name, ssh_key):
    self._EnsureAuthKeyFile(file_node_name)
    self._authorized_keys[file_node_name].add(ssh_key)

  def _RemoveAuthorizedKey(self, file_node_name, key):
    self._EnsureAuthKeyFile(file_node_name)
    self._authorized_keys[file_node_name] = \
        set([k for k in self._authorized_keys[file_node_name] if k != key])

  def _HandleAuthorizedKeys(self, instructions, node):
    (action, authorized_keys) = instructions
    ssh_keys = authorized_keys.values()
    if action == constants.SSHS_ADD:
      for ssh_key in ssh_keys:
        self._AddAuthorizedKey(node, ssh_key)
    elif action == constants.SSHS_REMOVE:
      for ssh_key in ssh_keys:
        self._RemoveAuthorizedKey(node, ssh_key)
    else:
      raise Exception("Unsupported action: %s" % action)

  def _EnsurePublicKeyFile(self, file_node_name):
    if file_node_name not in self._public_keys:
      self._public_keys[file_node_name] = {}

  def _ClearPublicKeys(self, file_node_name):
    self._public_keys[file_node_name] = {}

  def _OverridePublicKeys(self, ssh_keys, file_node_name):
    self._ClearPublicKeys(file_node_name)
    for key_node_uuid, node_keys in ssh_keys.items():
      if key_node_uuid in self._public_keys[file_node_name]:
        raise Exception("Duplicate node in ssh_update data.")
      self._public_keys[file_node_name][key_node_uuid] = node_keys

  def _ReplaceOrAddPublicKeys(self, public_keys, file_node_name):
    self._EnsurePublicKeyFile(file_node_name)
    for key_node_uuid, keys in public_keys.items():
      self._public_keys[file_node_name][key_node_uuid] = keys

  def _RemovePublicKeys(self, public_keys, file_node_name):
    self._EnsurePublicKeyFile(file_node_name)
    for key_node_uuid, _ in public_keys.items():
      if key_node_uuid in self._public_keys[file_node_name]:
        self._public_keys[file_node_name][key_node_uuid] = []

  def _HandlePublicKeys(self, instructions, node):
    (action, public_keys) = instructions
    if action == constants.SSHS_OVERRIDE:
      self._OverridePublicKeys(public_keys, node)
    elif action == constants.SSHS_ADD:
      self._ReplaceOrAddPublicKeys(public_keys, node)
    elif action == constants.SSHS_REPLACE_OR_ADD:
      self._ReplaceOrAddPublicKeys(public_keys, node)
    elif action == constants.SSHS_REMOVE:
      self._RemovePublicKeys(public_keys, node)
    elif action == constants.SSHS_CLEAR:
      self._ClearPublicKeys(node)
    else:
      raise Exception("Unsupported action: %s." % action)

  # pylint: disable=W0613
  def AddAuthorizedKeys(self, file_obj, keys):
    """Emulates ssh.AddAuthorizedKeys on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.AddAuthorizedKeys}

    """
    assert self._master_node_name
    for key in keys:
      self._AddAuthorizedKey(self._master_node_name, key)

  def RemoveAuthorizedKeys(self, file_name, keys):
    """Emulates ssh.RemoveAuthorizeKeys on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.RemoveAuthorizedKeys}

    """
    assert self._master_node_name
    for key in keys:
      self._RemoveAuthorizedKey(self._master_node_name, key)

  def AddPublicKey(self, new_uuid, new_key, **kwargs):
    """Emulates ssh.AddPublicKey on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.AddPublicKey}

    """
    assert self._master_node_name
    key_dict = {new_uuid: new_key}
    self._ReplaceOrAddPublicKeys(key_dict, self._master_node_name)

  def RemovePublicKey(self, target_uuid, **kwargs):
    """Emulates ssh.RemovePublicKey on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: {ssh.RemovePublicKey}

    """
    assert self._master_node_name
    key_dict = {target_uuid: []}
    self._RemovePublicKeys(key_dict, self._master_node_name)

  def QueryPubKeyFile(self, target_uuids, **kwargs):
    """Emulates ssh.QueryPubKeyFile on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.QueryPubKey}

    """
    assert self._master_node_name
    all_keys = target_uuids is None
    if all_keys:
      return self._public_keys[self._master_node_name]

    if isinstance(target_uuids, str):
      target_uuids = [target_uuids]
    result_dict = {}
    for key_node_uuid, key in \
        self._public_keys[self._master_node_name].items():
      if key_node_uuid in target_uuids:
        result_dict[key_node_uuid] = key
    return result_dict

  def ReplaceNameByUuid(self, node_uuid, node_name, **kwargs):
    """Emulates ssh.ReplaceNameByUuid on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.ReplacenameByUuid}

    """
    assert self._master_node_name
    if node_name in self._public_keys[self._master_node_name]:
      self._public_keys[self._master_node_name][node_uuid] = \
        self._public_keys[self._master_node_name][node_name][:]
      del self._public_keys[self._master_node_name][node_name]
  # pylint: enable=W0613
