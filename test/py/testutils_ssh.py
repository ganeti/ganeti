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
from ganeti import errors

from collections import namedtuple


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
    # are a named tuple of (node_uuid, ssh_key, is_potential_master_candidate,
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
    # Dictionary mapping nodes by name to number of retries where 'RunCommand'
    # succeeds. For example if set to '3', RunCommand will fail two times when
    # called for this node before it succeeds in the 3rd retry.
    self._max_retries = {}
    # Dictionary mapping nodes by name to number of retries which
    # 'RunCommand' has already carried out.
    self._retries = {}

    self._AssertTypePublicKeys()
    self._AssertTypeAuthorizedKeys()

  _NodeInfo = namedtuple(
      "NodeInfo",
      ["uuid",
       "key",
       "is_potential_master_candidate",
       "is_master_candidate",
       "is_master"])

  def _SetMasterNodeName(self):
    self._master_node_name = [name for name, node_info
                              in self._all_node_data.items()
                              if node_info.is_master][0]

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
      master = i == num_mcs // 2

      self._all_node_data[name] = self._NodeInfo(uuid, key, pot_mc, mc, master)

    self._AssertTypePublicKeys()
    self._AssertTypeAuthorizedKeys()

  def _FillPublicKeyOfOneNode(self, receiving_node_name):
    node_info = self._all_node_data[receiving_node_name]
    # Nodes which are not potential master candidates receive no keys
    if not node_info.is_potential_master_candidate:
      return
    for node_info in self._all_node_data.values():
      if node_info.is_potential_master_candidate:
        self._public_keys[receiving_node_name][node_info.uuid] = [node_info.key]

  def _FillAuthorizedKeyOfOneNode(self, receiving_node_name):
    for node_name, node_info in self._all_node_data.items():
      if node_info.is_master_candidate \
          or node_name == receiving_node_name:
        self._authorized_keys[receiving_node_name].add(node_info.key)

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
    self._AssertTypePublicKeys()
    self._AssertTypeAuthorizedKeys()

  def SetMaxRetries(self, node_name, retries):
    """Set the number of unsuccessful retries of 'RunCommand' per node.

    @type node_name: string
    @param node_name: name of the node
    @type retries: integer
    @param retries: number of unsuccessful retries

    """
    self._max_retries[node_name] = retries

  def GetSshPortMap(self, port):
    """Creates a SSH port map with all nodes mapped to the given port.

    @type port: int
    @param port: SSH port number for all nodes

    """
    port_map = {}
    for node in self._all_node_data:
      port_map[node] = port
    return port_map

  def GetAllNodeNames(self):
    """Returns all node names of the cluster.

    @rtype: list of str
    @returns: list of all node names
    """
    return list(self._all_node_data)

  def GetAllPotentialMasterCandidateNodeNames(self):
    return [name for name, node_info
            in self._all_node_data.items()
            if node_info.is_potential_master_candidate]

  def GetAllMasterCandidateUuids(self):
    return [node_info.uuid for node_info
            in self._all_node_data.values() if node_info.is_master_candidate]

  def GetAllPurePotentialMasterCandidates(self):
    """Get the potential master candidates which are not master candidates.

    @rtype: list of tuples (string, C{_NodeInfo})
    @returns: list of tuples of node name and node information of nodes
              which are potential master candidates but not master
              candidates
    """
    return [(name, node_info) for name, node_info
            in self._all_node_data.items()
            if node_info.is_potential_master_candidate and
            not node_info.is_master_candidate]

  def GetAllMasterCandidates(self):
    """Get all master candidate nodes.

    @rtype: list of tuples (string, C{_NodeInfo})
    @returns: list of tuples of node name and node information of master
              candidate nodes.
    """
    # Sort MCs so that the master node comes last
    # This is implicitly relied upon by the backend unittests
    # TODO: refine the test infrastructure so that this is not necessary
    keyfunc = lambda n_ni: n_ni[1].is_master

    return [(name, node_info) for name, node_info
            in sorted(self._all_node_data.items(), key=keyfunc)
            if node_info.is_master_candidate]

  def GetAllNormalNodes(self):
    """Get all normal nodes.

    Normal nodes are nodes that are neither master, master candidate nor
    potential master candidate.

    @rtype: list of tuples (string, C{_NodeInfo})
    @returns: list of tuples of node name and node information of normal
              nodes
    """
    return [(name, node_info) for name, node_info
            in self._all_node_data.items() if not node_info.is_master_candidate
            and not node_info.is_potential_master_candidate]

  def GetAllNodesDiverse(self):
    """This returns all nodes in a diverse order.

    This will return all nodes, but makes sure that they are ordered so that
    the list will contain in a round-robin fashion, a master candidate,
    a potential master candidate, a normal node, then again a master
    candidate, etc.

    @rtype: list of tuples (string, C{_NodeInfo})
    @returns: list of tuples of node name and node information

    """
    master_candidates = self.GetAllMasterCandidates()
    potential_master_candidates = self.GetAllPurePotentialMasterCandidates()
    normal_nodes = self.GetAllNormalNodes()

    mixed_list = []

    i = 0

    assert (len(self._all_node_data) == len(master_candidates)
            + len(potential_master_candidates) + len(normal_nodes))

    while len(mixed_list) < len(self._all_node_data):
      if i % 3 == 0:
        if master_candidates:
          mixed_list.append(master_candidates[0])
          master_candidates = master_candidates[1:]
      elif i % 3 == 1:
        if potential_master_candidates:
          mixed_list.append(potential_master_candidates[0])
          potential_master_candidates = potential_master_candidates[1:]
      else:  # i % 3 == 2
        if normal_nodes:
          mixed_list.append(normal_nodes[0])
          normal_nodes = normal_nodes[1:]
      i += 1

    return mixed_list

  def GetPublicKeysOfNode(self, node):
    """Returns the public keys that are stored on the given node.

    @rtype: dict of str to list of str
    @returns: a mapping of node names to a list of public keys

    """
    return self._public_keys[node]

  def GetAuthorizedKeysOfNode(self, node):
    """Returns the authorized keys of the given node.

    @rtype: list of str
    @returns: a list of authorized keys that are stored on that node

    """
    return self._authorized_keys[node]

  def SetOrAddNode(self, name, uuid, key, pot_mc, mc, master):
    """Adds a new node to the state of the file manager.

    This is necessary when testing to add new nodes to the cluster. Otherwise
    this new node's state would not be evaluated properly with the assertion
    functions.

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
    self._all_node_data[name] = self._NodeInfo(uuid, key, pot_mc, mc, master)
    if name not in self._authorized_keys:
      self._authorized_keys[name] = set()
    if mc:
      self._authorized_keys[name].add(key)
    if name not in self._public_keys:
      self._public_keys[name] = {}
    self._AssertTypePublicKeys()
    self._AssertTypeAuthorizedKeys()

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

  def AssertNodeSetOnlyHasAuthorizedKey(self, node_set, query_node_key):
    """Check if nodes in the given set only have a particular authorized key.

    @type node_set: list of strings
    @param node_set: list of nodes who are supposed to have the key
    @type query_node_key: string
    @param query_node_key: key which is looked for

    """
    assert isinstance(node_set, list)
    for node_name in self._all_node_data:
      if node_name in node_set:
        if not self.NodeHasAuthorizedKey(node_name, query_node_key):
          raise Exception("Node '%s' does not have authorized key '%s'."
                          % (node_name, query_node_key))
      else:
        if self.NodeHasAuthorizedKey(node_name, query_node_key):
          raise Exception("Node '%s' has authorized key '%s' although it"
                          " should not." % (node_name, query_node_key))

  def AssertAllNodesHaveAuthorizedKey(self, key):
    """Check if all nodes have a particular key in their auth. keys file.

    @type key: string
    @param key: key exptected to be present in all node's authorized_keys file
    @raise Exception: if a node does not have the authorized key.

    """
    self.AssertNodeSetOnlyHasAuthorizedKey(list(self._all_node_data), key)

  def AssertNoNodeHasAuthorizedKey(self, key):
    """Check if none of the nodes has a particular key in their auth. keys file.

    @type key: string
    @param key: key exptected to be present in all node's authorized_keys file
    @raise Exception: if a node *does* have the authorized key.

    """
    self.AssertNodeSetOnlyHasAuthorizedKey([], key)

  def AssertNodeSetOnlyHasPublicKey(self, node_set, query_node_uuid,
                                    query_node_key):
    """Check if nodes in the given set only have a particular public key.

    @type node_set: list of strings
    @param node_set: list of nodes who are supposed to have the key
    @type query_node_uuid: string
    @param query_node_uuid: uuid of the node whose key is looked for
    @type query_node_key: string
    @param query_node_key: key which is looked for

    """
    for node_name in self._all_node_data:
      if node_name in node_set:
        if not self.NodeHasPublicKey(node_name, query_node_uuid,
                                     query_node_key):
          raise Exception("Node '%s' does not have public key '%s' of node"
                          " '%s'." % (node_name, query_node_key,
                                      query_node_uuid))
      else:
        if self.NodeHasPublicKey(node_name, query_node_uuid, query_node_key):
          raise Exception("Node '%s' has public key '%s' of node"
                          " '%s' although it should not."
                          % (node_name, query_node_key, query_node_uuid))

  def AssertNoNodeHasPublicKey(self, uuid, key):
    """Check if none of the nodes have the given public key in their file.

    @type uuid: string
    @param uuid: UUID of the node whose key is looked for
    @raise Exception: if a node *does* have the public key.

    """
    self.AssertNodeSetOnlyHasPublicKey([], uuid, key)

  def AssertPotentialMasterCandidatesOnlyHavePublicKey(self, query_node_name):
    """Checks if the node's key is on all potential master candidates only.

    This ensures that the node's key is in all public key files of all
    potential master candidates, and it also checks whether the key is
    *not* in all other nodes's key files.

    @param query_node_name: name of the node whose key is expected to be
                            in the public key file of all potential master
                            candidates
    @type query_node_name: string
    @raise Exception: when a potential master candidate does not have
                      the public key or a normal node *does* have a public key.

    """
    query_node_uuid, query_node_key, _, _, _ = \
        self._all_node_data[query_node_name]
    potential_master_candidates = self.GetAllPotentialMasterCandidateNodeNames()
    self.AssertNodeSetOnlyHasPublicKey(
        potential_master_candidates, query_node_uuid, query_node_key)

  def _AssertTypePublicKeys(self):
    """Asserts that the public key dictionary has the right types.

    This is helpful as an invariant that shall not be violated during the
    tests due to type errors.

    """
    assert isinstance(self._public_keys, dict)
    for node_file, pub_keys in self._public_keys.items():
      assert isinstance(node_file, str)
      assert isinstance(pub_keys, dict)
      for node_key, keys in pub_keys.items():
        assert isinstance(node_key, str)
        assert isinstance(keys, list)
        for key in keys:
          assert isinstance(key, str)

  def _AssertTypeAuthorizedKeys(self):
    """Asserts that the authorized keys dictionary has the right types.

    This is useful to check as an invariant that is not supposed to be violated
    during the tests.

    """
    assert isinstance(self._authorized_keys, dict)
    for node_file, auth_keys in self._authorized_keys.items():
      assert isinstance(node_file, str)
      assert isinstance(auth_keys, set)
      for key in auth_keys:
        assert isinstance(key, str)

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
    if node in self._max_retries:
      if node not in self._retries:
        self._retries[node] = 0
      self._retries[node] += 1
      if self._retries[node] < self._max_retries[node]:
        raise errors.OpExecError("(Fake) SSH connection to node '%s' failed."
                                 % node)

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
    self._AssertTypePublicKeys()
    self._AssertTypeAuthorizedKeys()

  def _AddAuthorizedKeys(self, file_node_name, ssh_keys):
    """Mocks adding the given keys to the authorized_keys file."""
    assert isinstance(ssh_keys, list)
    self._EnsureAuthKeyFile(file_node_name)
    for key in ssh_keys:
      self._authorized_keys[file_node_name].add(key)
    self._AssertTypePublicKeys()
    self._AssertTypeAuthorizedKeys()

  def _RemoveAuthorizedKeys(self, file_node_name, keys):
    """Mocks removing the keys from authorized_keys on the given node.

    @param keys: list of ssh keys
    @type keys: list of strings

    """
    self._EnsureAuthKeyFile(file_node_name)
    self._authorized_keys[file_node_name] = \
        set([k for k in self._authorized_keys[file_node_name] if k not in keys])
    self._AssertTypeAuthorizedKeys()

  def _HandleAuthorizedKeys(self, instructions, node):
    (action, authorized_keys) = instructions
    ssh_key_sets = list(authorized_keys.values())
    if action == constants.SSHS_ADD:
      for ssh_keys in ssh_key_sets:
        self._AddAuthorizedKeys(node, ssh_keys)
    elif action == constants.SSHS_REMOVE:
      for ssh_keys in ssh_key_sets:
        self._RemoveAuthorizedKeys(node, ssh_keys)
    else:
      raise Exception("Unsupported action: %s" % action)
    self._AssertTypeAuthorizedKeys()

  def _EnsurePublicKeyFile(self, file_node_name):
    if file_node_name not in self._public_keys:
      self._public_keys[file_node_name] = {}
    self._AssertTypePublicKeys()

  def _ClearPublicKeys(self, file_node_name):
    self._public_keys[file_node_name] = {}
    self._AssertTypePublicKeys()

  def _OverridePublicKeys(self, ssh_keys, file_node_name):
    assert isinstance(ssh_keys, dict)
    self._ClearPublicKeys(file_node_name)
    for key_node_uuid, node_keys in ssh_keys.items():
      assert isinstance(node_keys, list)
      if key_node_uuid in self._public_keys[file_node_name]:
        raise Exception("Duplicate node in ssh_update data.")
      self._public_keys[file_node_name][key_node_uuid] = node_keys
    self._AssertTypePublicKeys()

  def _ReplaceOrAddPublicKeys(self, public_keys, file_node_name):
    assert isinstance(public_keys, dict)
    self._EnsurePublicKeyFile(file_node_name)
    for key_node_uuid, keys in public_keys.items():
      assert isinstance(keys, list)
      self._public_keys[file_node_name][key_node_uuid] = keys
    self._AssertTypePublicKeys()

  def _RemovePublicKeys(self, public_keys, file_node_name):
    assert isinstance(public_keys, dict)
    self._EnsurePublicKeyFile(file_node_name)
    for key_node_uuid in public_keys:
      if key_node_uuid in self._public_keys[file_node_name]:
        self._public_keys[file_node_name][key_node_uuid] = []
    self._AssertTypePublicKeys()

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
    self._AssertTypePublicKeys()

  # pylint: disable=W0613
  def AddAuthorizedKeys(self, file_obj, keys):
    """Emulates ssh.AddAuthorizedKeys on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.AddAuthorizedKeys}

    """
    assert isinstance(keys, list)
    assert self._master_node_name
    self._AddAuthorizedKeys(self._master_node_name, keys)
    self._AssertTypeAuthorizedKeys()

  def RemoveAuthorizedKeys(self, file_name, keys):
    """Emulates ssh.RemoveAuthorizeKeys on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.RemoveAuthorizedKeys}

    """
    assert isinstance(keys, list)
    assert self._master_node_name
    self._RemoveAuthorizedKeys(self._master_node_name, keys)
    self._AssertTypeAuthorizedKeys()

  def AddPublicKey(self, new_uuid, new_key, **kwargs):
    """Emulates ssh.AddPublicKey on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.AddPublicKey}

    """
    assert self._master_node_name
    assert isinstance(new_key, str)
    key_dict = {new_uuid: [new_key]}
    self._ReplaceOrAddPublicKeys(key_dict, self._master_node_name)
    self._AssertTypePublicKeys()

  def RemovePublicKey(self, target_uuid, **kwargs):
    """Emulates ssh.RemovePublicKey on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: {ssh.RemovePublicKey}

    """
    assert self._master_node_name
    key_dict = {target_uuid: []}
    self._RemovePublicKeys(key_dict, self._master_node_name)
    self._AssertTypePublicKeys()

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
    for key_node_uuid, keys in \
        self._public_keys[self._master_node_name].items():
      if key_node_uuid in target_uuids:
        result_dict[key_node_uuid] = keys
    self._AssertTypePublicKeys()
    return result_dict

  def ReplaceNameByUuid(self, node_uuid, node_name, **kwargs):
    """Emulates ssh.ReplaceNameByUuid on the master node.

    Instead of actually mainpulating the authorized_keys file, this method
    keeps the state of the file in a dictionary in memory.

    @see: C{ssh.ReplacenameByUuid}

    """
    assert isinstance(node_uuid, str)
    assert isinstance(node_name, str)
    assert self._master_node_name
    if node_name in self._public_keys[self._master_node_name]:
      self._public_keys[self._master_node_name][node_uuid] = \
        self._public_keys[self._master_node_name][node_name][:]
      del self._public_keys[self._master_node_name][node_name]
    self._AssertTypePublicKeys()
  # pylint: enable=W0613
