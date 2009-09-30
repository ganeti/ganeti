#
#

# Copyright (C) 2009, Google Inc.
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


"""Ganeti configuration daemon queries library.

"""

import logging

from ganeti import constants


# constants for some common errors to return from a query
QUERY_UNKNOWN_ENTRY_ERROR = (constants.CONFD_REPL_STATUS_ERROR,
                             constants.CONFD_ERROR_UNKNOWN_ENTRY)
QUERY_INTERNAL_ERROR = (constants.CONFD_REPL_STATUS_ERROR,
                        constants.CONFD_ERROR_INTERNAL)


class ConfdQuery(object):
  """Confd Query base class.

  """
  def __init__(self, reader):
    """Constructor for Confd Query

    @type reader: L{ssconf.SimpleConfigReader}
    @param reader: ConfigReader to use to access the config

    """
    self.reader = reader

  def Exec(self, query):
    """Process a single UDP request from a client.

    Different queries should override this function, which by defaults returns
    a "non-implemented" answer.

    @type query: (undefined)
    @param query: ConfdRequest 'query' field
    @rtype: (integer, undefined)
    @return: status and answer to give to the client

    """
    status = constants.CONFD_REPL_STATUS_NOTIMPLEMENTED
    answer = 'not implemented'
    return status, answer


class PingQuery(ConfdQuery):
  """An empty confd query.

  It will return success on an empty argument, and an error on any other
  argument.

  """
  def Exec(self, query):
    """PingQuery main execution.

    """
    if query is None:
      status = constants.CONFD_REPL_STATUS_OK
      answer = 'ok'
    else:
      status = constants.CONFD_REPL_STATUS_ERROR
      answer = 'non-empty ping query'

    return status, answer


class ClusterMasterQuery(ConfdQuery):
  """Cluster master query.

  It accepts no arguments, and returns the current cluster master.

  """
  def Exec(self, query):
    """ClusterMasterQuery main execution

    """
    if query is None:
      status = constants.CONFD_REPL_STATUS_OK
      answer = self.reader.GetMasterNode()
    else:
      status = constants.CONFD_REPL_STATUS_ERROR
      answer = 'master query accepts no query argument'

    return status, answer


class NodeRoleQuery(ConfdQuery):
  """A query for the role of a node.

  It will return one of CONFD_NODE_ROLE_*, or an error for non-existing nodes.

  """
  def Exec(self, query):
    """EmptyQuery main execution

    """
    node = query
    if self.reader.GetMasterNode() == node:
      status = constants.CONFD_REPL_STATUS_OK
      answer = constants.CONFD_NODE_ROLE_MASTER
      return status, answer
    flags = self.reader.GetNodeStatusFlags(node)
    if flags is None:
      return QUERY_UNKNOWN_ENTRY_ERROR

    master_candidate, drained, offline = flags
    if master_candidate:
      answer = constants.CONFD_NODE_ROLE_CANDIDATE
    elif drained:
      answer = constants.CONFD_NODE_ROLE_DRAINED
    elif offline:
      answer = constants.CONFD_NODE_ROLE_OFFLINE
    else:
      answer = constants.CONFD_NODE_ROLE_REGULAR

    return constants.CONFD_REPL_STATUS_OK, answer


class InstanceIpToNodePrimaryIpQuery(ConfdQuery):
  """A query for the location of an instance's ip.

  It returns the primary ip of the node hosting the instance having the
  requested ip address, or an error if no such address is known.

  """
  def Exec(self, query):
    """InstanceIpToNodePrimaryIpQuery main execution.

    """
    instance_ip = query
    instance = self.reader.GetInstanceByIp(instance_ip)
    if instance is None:
      return QUERY_UNKNOWN_ENTRY_ERROR

    pnode = self.reader.GetInstancePrimaryNode(instance)
    if pnode is None:
      # this shouldn't happen
      logging.error("Internal configuration inconsistent (instance-to-pnode)")
      return QUERY_INTERNAL_ERROR

    pnode_primary_ip = self.reader.GetNodePrimaryIp(pnode)
    if pnode_primary_ip is None:
      # this shouldn't happen
      logging.error("Internal configuration inconsistent (node-to-primary-ip)")
      return QUERY_INTERNAL_ERROR

    return constants.CONFD_REPL_STATUS_OK, pnode_primary_ip


class NodesPipsQuery(ConfdQuery):
  """A query for nodes primary IPs.

  It returns the list of nodes primary IPs.

  """
  def Exec(self, query):
    """NodesPipsQuery main execution.

    """
    if query is None:
      status = constants.CONFD_REPL_STATUS_OK
      answer = self.reader.GetNodesPrimaryIps()
    else:
      status = constants.CONFD_REPL_STATUS_ERROR
      answer = "non-empty node primary IPs query"

    return status, answer


class MasterCandidatesPipsQuery(ConfdQuery):
  """A query for master candidates primary IPs.

  It returns the list of master candidates primary IPs.

  """
  def Exec(self, query):
    """MasterCandidatesPipsQuery main execution.

    """
    if query is None:
      status = constants.CONFD_REPL_STATUS_OK
      answer = self.reader.GetMasterCandidatesPrimaryIps()
    else:
      status = constants.CONFD_REPL_STATUS_ERROR
      answer = "non-empty master candidates primary IPs query"

    return status, answer


class InstancesIpsQuery(ConfdQuery):
  """A query for instances IPs.

  It returns the list of IPs of NICs connected to the requested link or all the
  instances IPs if no link is submitted.

  """
  def Exec(self, query):
    """InstancesIpsQuery main execution.

    """
    link = query
    status = constants.CONFD_REPL_STATUS_OK
    answer = self.reader.GetInstancesIps(link)

    return status, answer

