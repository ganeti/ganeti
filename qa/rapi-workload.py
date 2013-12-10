#!/usr/bin/python -u
#

# Copyright (C) 2013 Google Inc.
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


"""Script for providing a large amount of RAPI calls to Ganeti.

"""

# pylint: disable=C0103
# due to invalid name

import inspect
import sys
import types

import ganeti.constants as constants
from ganeti.rapi.client import GanetiApiError

import qa_config
import qa_node
import qa_rapi


# The purpose of this file is to provide a stable and extensive RAPI workload
# that manipulates the cluster only using RAPI commands, with the assumption
# that an empty cluster was set up beforehand. All the nodes that can be added
# to the cluster should be a part of it, and no instances should be present.
#
# Its intended use is in RAPI compatibility tests, where different versions with
# possibly vastly different QAs must be compared. Running the QA on both
# versions of the cluster will produce RAPI calls, but there is no guarantee
# that they will match, or that functions invoked in between will not change the
# results.
#
# By using only RAPI functions, we are sure to be able to capture and log all
# the changes in cluster state, and be able to compare them afterwards.
#
# The functionality of the QA is still used to generate a functioning,
# RAPI-enabled cluster, and to set up a C{GanetiRapiClient} capable of issuing
# commands to the cluster.
#
# Due to the fact that not all calls issued as a part of the workload might be
# implemented in the different versions of Ganeti, the client does not halt or
# produce a non-zero exit code upon encountering a RAPI error. Instead, it
# reports it and moves on. Any utility comparing the requests should account for
# this.


def MockMethod(*_args, **_kwargs):
  """ Absorbs all arguments, does nothing, returns None.

  """
  return None


RAPI_USERNAME = "ganeti-qa"


class GanetiRapiClientWrapper(object):
  """ Creates and initializes a GanetiRapiClient, and acts as a wrapper invoking
  only the methods that the version of the client actually uses.

  """
  def __init__(self):
    self._client = qa_rapi.Setup(RAPI_USERNAME,
                                 qa_rapi.LookupRapiSecret(RAPI_USERNAME))

    self._method_invocations = {}

  def _RecordMethodInvocation(self, name, arg_dict):
    """ Records the invocation of a C{GanetiRAPIClient} method, noting the
    argument and the method names.

    """
    if name not in self._method_invocations:
      self._method_invocations[name] = set()

    for named_arg in arg_dict:
      self._method_invocations[name].add(named_arg)

  def _InvokerCreator(self, fn, name):
    """ Returns an invoker function that will invoke the given function
    with any arguments passed to the invoker at a later time, while
    catching any specific non-fatal errors we would like to know more
    about.

    @type fn arbitrary function
    @param fn The function to invoke later.
    @type name string
    @param name The name of the function, for debugging purposes.
    @rtype function

    """
    def decoratedFn(*args, **kwargs):
      result = None
      try:
        print "Using method %s" % name
        self._RecordMethodInvocation(name, kwargs)
        result = fn(*args, **kwargs)
      except GanetiApiError as e:
        print "RAPI error while performing function %s : %s" % \
              (name, str(e))
      return result

    return decoratedFn

  def __getattr__(self, attr):
    """ Fetches an attribute from the underlying client if necessary.

    """
    # Assuming that this method exposes no public methods of its own,
    # and that any private methods are named according to the style
    # guide, this will stop infinite loops in attribute fetches.
    if attr.startswith("_"):
      return self.__getattribute__(attr)

    # We also want to expose non-methods
    if hasattr(self._client, attr) and \
       not isinstance(getattr(self._client, attr), types.MethodType):
      return getattr(self._client, attr)

    try:
      return self._InvokerCreator(self._client.__getattribute__(attr), attr)
    except AttributeError:
      print "Missing method %s; supplying mock method" % attr
      return MockMethod

  def _OutputMethodInvocationDetails(self):
    """ Attempts to output as much information as possible about the methods
    that have and have not been invoked, including which arguments have not
    been used.

    """
    print "\nMethod usage:\n"
    for method in [n for n in dir(self._client)
                     if not n.startswith('_') and
                        isinstance(self.__getattr__(n), types.FunctionType)]:
      if method not in self._method_invocations:
        print "Method unused: %s" % method
      else:
        arg_spec, _, _, default_arg_spec = \
          inspect.getargspec(getattr(self._client, method))
        default_args = []
        if default_arg_spec is not None:
          default_args = arg_spec[-len(default_arg_spec):]
        used_arg_set = self._method_invocations[method]
        unused_args = [arg for arg in default_args if arg not in used_arg_set]
        if unused_args:
          print "Method %s used, but arguments unused: %s" % \
                (method, ", ".join(unused_args))


def Finish(client, fn, *args, **kwargs):
  """ When invoked with a job-starting RAPI client method, it passes along any
  additional arguments and waits until its completion.

  @type client C{GanetiRapiClientWrapper}
  @param client The client wrapper.
  @type fn function
  @param fn A client method returning a job id.

  """
  possible_job_id = fn(*args, **kwargs)
  try:
    # The job ids are returned as both ints and ints represented by strings.
    # This is a pythonic check to see if the content is an int.
    int(possible_job_id)
  except (ValueError, TypeError):
    # As a rule of thumb, failures will return None, and other methods are
    # expected to return at least something
    if possible_job_id is not None:
      print ("Finish called with a method not producing a job id, "
             "returning %s" % possible_job_id)
    return possible_job_id

  success = client.WaitForJobCompletion(possible_job_id)

  result = client.GetJobStatus(possible_job_id)["opresult"][0]
  if success:
    return result
  else:
    print "Error encountered while performing operation: "
    print result
    return None


def TestTags(client, get_fn, add_fn, delete_fn, *args):
  """ Tests whether tagging works.

  @type client C{GanetiRapiClientWrapper}
  @param client The client wrapper.
  @type get_fn function
  @param get_fn A Get*Tags function of the client.
  @type add_fn function
  @param add_fn An Add*Tags function of the client.
  @type delete_fn function
  @param delete_fn A Delete*Tags function of the client.

  To allow this method to work for all tagging functions of the client, use
  named methods.

  """
  get_fn(*args)

  tags = ["tag1", "tag2", "tag3"]
  Finish(client, add_fn, *args, tags=tags, dry_run=True)
  Finish(client, add_fn, *args, tags=tags)

  get_fn(*args)

  Finish(client, delete_fn, *args, tags=tags[:1], dry_run=True)
  Finish(client, delete_fn, *args, tags=tags[:1])

  get_fn(*args)

  Finish(client, delete_fn, *args, tags=tags[1:])

  get_fn(*args)


def TestGetters(client):
  """ Tests the various get functions which only retrieve information about the
  cluster.

  @type client C{GanetiRapiClientWrapper}

  """
  client.GetVersion()
  client.GetFeatures()
  client.GetOperatingSystems()
  client.GetInfo()
  client.GetClusterTags()
  client.GetInstances()
  client.GetInstances(bulk=True)
  client.GetJobs()
  client.GetJobs(bulk=True)
  client.GetNodes()
  client.GetNodes(bulk=True)
  client.GetNetworks()
  client.GetNetworks(bulk=True)
  client.GetGroups()
  client.GetGroups(bulk=True)


def TestQueries(client, resource_name):
  """ Finds out which fields are present for a given resource type, and attempts
  to retrieve their values for all present resources.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.
  @type resource_name string
  @param resource_name The name of the resource to use.

  """

  FIELDS_KEY = "fields"

  query_res = client.QueryFields(resource_name)

  if query_res is None or FIELDS_KEY not in query_res or \
    len(query_res[FIELDS_KEY]) == 0:
    return

  field_entries = query_res[FIELDS_KEY]

  fields = map(lambda e: e["name"], field_entries)

  client.Query(resource_name, fields)


def TestQueryFiltering(client, master_name):
  """ Performs queries by playing around with the only guaranteed resource, the
  master node.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.
  @type master_name string
  @param master_name The hostname of the master node.

  """
  client.Query("node", ["name"],
               ["|",
                ["=", "name", master_name],
                [">", "dtotal", 0],
               ])

  client.Query("instance", ["name"],
               ["|",
                ["=", "name", "NonexistentInstance"],
                [">", "oper_ram", 0],
               ])


def RemoveAllInstances(client):
  """ Queries for a list of instances, then removes them all.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.

  """
  instances = client.GetInstances()
  for inst in instances:
    Finish(client, client.DeleteInstance, inst)

  instances = client.GetInstances()
  assert len(instances) == 0


def TestSingleInstance(client, instance_name, alternate_name, node_one,
                       node_two):
  """ Creates an instance, performs operations involving it, and then deletes
  it.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.
  @type instance_name string
  @param instance_name The hostname to use.
  @type instance_name string
  @param instance_name Another valid hostname to use.
  @type node_one string
  @param node_one A node on which an instance can be added.
  @type node_two string
  @param node_two A node on which an instance can be added.

  """

  # Check that a dry run works, use string with size and unit
  Finish(client, client.CreateInstance,
         "create", instance_name, "plain", [{"size":"1gb"}], [], dry_run=True,
          os="debian-image", pnode=node_one)

  # Another dry run, numeric size, should work, but still a dry run
  Finish(client, client.CreateInstance,
         "create", instance_name, "plain", [{"size": "1000"}], [{}],
         dry_run=True, os="debian-image", pnode=node_one)

  # Create a smaller instance, and delete it immediately
  Finish(client, client.CreateInstance,
         "create", instance_name, "plain", [{"size":800}], [{}],
         os="debian-image", pnode=node_one)

  Finish(client, client.DeleteInstance, instance_name)

  # Create one instance to use in further tests
  Finish(client, client.CreateInstance,
         "create", instance_name, "plain", [{"size":1200}], [{}],
         os="debian-image", pnode=node_one)

  client.GetInstance(instance_name)

  Finish(client, client.GetInstanceInfo, instance_name)

  Finish(client, client.GetInstanceInfo, instance_name, static=True)

  TestQueries(client, "instance")

  TestTags(client, client.GetInstanceTags, client.AddInstanceTags,
           client.DeleteInstanceTags, instance_name)

  Finish(client, client.GrowInstanceDisk,
         instance_name, 0, 100, wait_for_sync=True)

  Finish(client, client.RebootInstance,
         instance_name, "soft", ignore_secondaries=True, dry_run=True,
         reason="Hulk smash gently!")

  Finish(client, client.ShutdownInstance,
         instance_name, dry_run=True, no_remember=False,
         reason="Hulk smash hard!")

  Finish(client, client.StartupInstance,
         instance_name, dry_run=True, no_remember=False,
         reason="Not hard enough!")

  Finish(client, client.RebootInstance,
         instance_name, "soft", ignore_secondaries=True, dry_run=False)

  Finish(client, client.ShutdownInstance,
         instance_name, dry_run=False, no_remember=False)

  Finish(client, client.ModifyInstance,
         instance_name, disk_template="drbd", remote_node=node_two)

  Finish(client, client.ModifyInstance,
         instance_name, disk_template="plain")

  Finish(client, client.RenameInstance,
         instance_name, alternate_name, ip_check=True, name_check=True)

  Finish(client, client.RenameInstance, alternate_name, instance_name)

  Finish(client, client.DeactivateInstanceDisks, instance_name)

  Finish(client, client.ActivateInstanceDisks, instance_name)

  # Note that the RecreateInstanceDisks command will always fail, as there is
  # no way to induce the necessary prerequisites (removal of LV) via RAPI.
  # Keeping it around allows us to at least know that it still exists.
  Finish(client, client.RecreateInstanceDisks,
         instance_name, [0], [node_one])

  Finish(client, client.StartupInstance,
         instance_name, dry_run=False, no_remember=False)

  client.GetInstanceConsole(instance_name)

  Finish(client, client.ReinstallInstance,
         instance_name, os=None, no_startup=False, osparams={})

  Finish(client, client.DeleteInstance, instance_name, dry_run=True)

  Finish(client, client.DeleteInstance, instance_name)


def MarkUnmarkNode(client, node, state):
  """ Given a certain node state, marks a node as being in that state, and then
  unmarks it.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.
  @type node string
  @type state string

  """
  # pylint: disable=W0142
  Finish(client, client.ModifyNode, node, **{state: True})
  Finish(client, client.ModifyNode, node, **{state: False})
  # pylint: enable=W0142


def TestNodeOperations(client, non_master_node):
  """ Tests various operations related to nodes only

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.
  @type non_master_node string
  @param non_master_node The name of a non-master node in the cluster.

  """

  client.GetNode(non_master_node)

  old_role = client.GetNodeRole(non_master_node)

  # Should fail
  Finish(client, client.SetNodeRole,
         non_master_node, "master", False, auto_promote=True)

  Finish(client, client.SetNodeRole,
         non_master_node, "regular", False, auto_promote=True)

  Finish(client, client.SetNodeRole,
         non_master_node, "master-candidate", False, auto_promote=True)

  Finish(client, client.SetNodeRole,
         non_master_node, "drained", False, auto_promote=True)

  Finish(client, client.SetNodeRole,
         non_master_node, old_role, False, auto_promote=True)

  Finish(client, client.PowercycleNode,
         non_master_node, force=False)

  storage_units_fields = [
    "name", "allocatable", "free", "node", "size", "type", "used",
  ]

  for storage_type in constants.STS_REPORT:
    storage_units = Finish(client, client.GetNodeStorageUnits,
                           non_master_node, storage_type,
                           ",".join(storage_units_fields))

    if len(storage_units) > 0 and len(storage_units[0]) > 0:
      # Name is the first entry of the first result, allocatable the other
      unit_name = storage_units[0][0]
      Finish(client, client.ModifyNodeStorageUnits,
             non_master_node, storage_type, unit_name,
             allocatable=not storage_units[0][1])
      Finish(client, client.ModifyNodeStorageUnits,
             non_master_node, storage_type, unit_name,
             allocatable=storage_units[0][1])
      Finish(client, client.RepairNodeStorageUnits,
             non_master_node, storage_type, unit_name)

  MarkUnmarkNode(client, non_master_node, "drained")
  MarkUnmarkNode(client, non_master_node, "powered")
  MarkUnmarkNode(client, non_master_node, "offline")

  TestQueries(client, "node")


def TestGroupOperations(client, node, another_node):
  """ Tests various operations related to groups only.

  @type client C{GanetiRapiClientWrapper}
  @param client A Ganeti RAPI client to use.
  @type node string
  @param node The name of a node in the cluster.
  @type another_node string
  @param another_node The name of another node in the cluster.

  """

  DEFAULT_GROUP_NAME = constants.INITIAL_NODE_GROUP_NAME
  TEST_GROUP_NAME = "TestGroup"
  ALTERNATE_GROUP_NAME = "RenamedTestGroup"

  Finish(client, client.CreateGroup,
         TEST_GROUP_NAME, alloc_policy=constants.ALLOC_POLICY_PREFERRED,
         dry_run=True)

  Finish(client, client.CreateGroup,
         TEST_GROUP_NAME, alloc_policy=constants.ALLOC_POLICY_PREFERRED)

  client.GetGroup(TEST_GROUP_NAME)

  TestQueries(client, "group")

  TestTags(client, client.GetGroupTags, client.AddGroupTags,
           client.DeleteGroupTags, TEST_GROUP_NAME)

  Finish(client, client.ModifyGroup,
         TEST_GROUP_NAME, alloc_policy=constants.ALLOC_POLICY_PREFERRED,
         depends=None)

  Finish(client, client.AssignGroupNodes,
         TEST_GROUP_NAME, [node, another_node], force=False, dry_run=True)

  Finish(client, client.AssignGroupNodes,
         TEST_GROUP_NAME, [another_node], force=False)

  Finish(client, client.RenameGroup,
         TEST_GROUP_NAME, ALTERNATE_GROUP_NAME)

  Finish(client, client.RenameGroup,
         ALTERNATE_GROUP_NAME, TEST_GROUP_NAME)

  Finish(client, client.AssignGroupNodes,
         DEFAULT_GROUP_NAME, [another_node], force=False)

  Finish(client, client.DeleteGroup, TEST_GROUP_NAME, dry_run=True)

  Finish(client, client.DeleteGroup, TEST_GROUP_NAME)


def TestNetworkConnectDisconnect(client, network_name, mode, link):
  """ Test connecting and disconnecting the network to a new node group.

  @type network_name string
  @param network_name The name of an existing and unconnected network.
  @type mode string
  @param mode The network mode.
  @type link string
  @param link The network link.

  """
  # For testing the connect/disconnect calls, a group is needed
  TEST_GROUP_NAME = "TestGroup"
  Finish(client, client.CreateGroup,
         TEST_GROUP_NAME, alloc_policy=constants.ALLOC_POLICY_PREFERRED)

  Finish(client, client.ConnectNetwork,
         network_name, TEST_GROUP_NAME, mode, link, dry_run=True)

  Finish(client, client.ConnectNetwork,
         network_name, TEST_GROUP_NAME, mode, link)

  Finish(client, client.DisconnectNetwork,
         network_name, TEST_GROUP_NAME, dry_run=True)

  Finish(client, client.DisconnectNetwork,
         network_name, TEST_GROUP_NAME)

  # Clean up the group
  Finish(client, client.DeleteGroup, TEST_GROUP_NAME)


def TestNetworks(client):
  """ Add some networks of different sizes, using RFC5737 addresses like in the
  QA.

  """

  NETWORK_NAME = "SurelyCertainlyNonexistentNetwork"

  Finish(client, client.CreateNetwork,
         NETWORK_NAME, "192.0.2.0/30", tags=[], dry_run=True)

  Finish(client, client.CreateNetwork,
         NETWORK_NAME, "192.0.2.0/30", tags=[])

  client.GetNetwork(NETWORK_NAME)

  TestTags(client, client.GetNetworkTags, client.AddNetworkTags,
           client.DeleteNetworkTags, NETWORK_NAME)

  Finish(client, client.ModifyNetwork,
         NETWORK_NAME, mac_prefix=None)

  TestQueries(client, "network")

  default_nicparams = qa_config.get("default-nicparams", None)

  # The entry might not be present in the QA config
  if default_nicparams is not None:
    mode = default_nicparams.get("mode", None)
    link = default_nicparams.get("link", None)
    if mode is not None and link is not None:
      TestNetworkConnectDisconnect(client, NETWORK_NAME, mode, link)

  # Clean up the network
  Finish(client, client.DeleteNetwork,
         NETWORK_NAME, dry_run=True)

  Finish(client, client.DeleteNetwork, NETWORK_NAME)


def Workload(client):
  """ The actual RAPI workload used for tests.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.

  """

  # First just the simple information retrievals
  TestGetters(client)

  # Then the only remaining function which is parameter-free
  Finish(client, client.RedistributeConfig)

  TestTags(client, client.GetClusterTags, client.AddClusterTags,
           client.DeleteClusterTags)

  # Generously assume the master is present
  node = qa_config.AcquireNode()
  TestTags(client, client.GetNodeTags, client.AddNodeTags,
           client.DeleteNodeTags, node.primary)
  node.Release()

  # Instance tests

  # First remove all instances the QA might have created
  RemoveAllInstances(client)

  nodes = qa_config.AcquireManyNodes(2)
  instance_one = qa_config.AcquireInstance()
  instance_two = qa_config.AcquireInstance()
  TestSingleInstance(client, instance_one.name, instance_two.name,
                     nodes[0].primary, nodes[1].primary)
  instance_two.Release()
  instance_one.Release()
  qa_config.ReleaseManyNodes(nodes)

  # Test all the queries which involve resources that do not have functions
  # of their own
  TestQueries(client, "lock")
  TestQueries(client, "job")
  TestQueries(client, "export")

  node = qa_config.AcquireNode(exclude=qa_config.GetMasterNode())
  TestNodeOperations(client, node.primary)
  TestQueryFiltering(client, node.primary)
  node.Release()

  nodes = qa_config.AcquireManyNodes(2)
  TestGroupOperations(client, nodes[0].primary, nodes[1].primary)
  qa_config.ReleaseManyNodes(nodes)

  TestNetworks(client)


def Usage():
  sys.stderr.write("Usage:\n\trapi-workload.py qa-config-file")


def Main():
  if len(sys.argv) < 2:
    Usage()

  qa_config.Load(sys.argv[1])

  # Only the master will be present after a fresh QA cluster setup, so we have
  # to invoke this to get all the other nodes.
  qa_node.TestNodeAddAll()

  client = GanetiRapiClientWrapper()

  Workload(client)

  qa_node.TestNodeRemoveAll()

  # The method invoked has the naming of the protected method, and pylint does
  # not like this. Disabling the warning is healthier than explicitly adding and
  # maintaining an exception for this method in the wrapper.
  # pylint: disable=W0212
  client._OutputMethodInvocationDetails()
  # pylint: enable=W0212

if __name__ == "__main__":
  Main()
