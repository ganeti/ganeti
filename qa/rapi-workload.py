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


import sys

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


def InvokerCreator(fn, name):
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
      result = fn(*args, **kwargs)
    except GanetiApiError as e:
      print "RAPI error while performing function %s : %s" % \
            (name, str(e))
    return result

  return decoratedFn


RAPI_USERNAME = "ganeti-qa"


class GanetiRapiClientWrapper(object):
  """ Creates and initializes a GanetiRapiClient, and acts as a wrapper invoking
  only the methods that the version of the client actually uses.

  """
  def __init__(self):
    self._client = qa_rapi.Setup(RAPI_USERNAME,
                                 qa_rapi.LookupRapiSecret(RAPI_USERNAME))

  def __getattr__(self, attr):
    """ Fetches an attribute from the underlying client if necessary.

    """
    # Assuming that this method exposes no public methods of its own,
    # and that any private methods are named according to the style
    # guide, this will stop infinite loops in attribute fetches.
    if attr.startswith("_"):
      return self.__getattribute__(attr)
    try:
      return InvokerCreator(self._client.__getattribute__(attr), attr)
    except AttributeError:
      print "Missing method %s; supplying mock method" % attr
      return MockMethod


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


def Workload(client):
  """ The actual RAPI workload used for tests.

  @type client C{GanetiRapiClientWrapper}
  @param client A wrapped RAPI client.

  """

  # First just the simple information retrievals
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

  Finish(client, client.RedistributeConfig)


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


if __name__ == "__main__":
  Main()
