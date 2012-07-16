#
#

# Copyright (C) 2009, 2012 Google Inc.
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
QUERY_ARGUMENT_ERROR = (constants.CONFD_REPL_STATUS_ERROR,
                        constants.CONFD_ERROR_ARGUMENT)


class ConfdQuery(object):
  """Confd Query base class.

  """
  def __init__(self, reader):
    """Constructor for Confd Query

    @type reader: L{ssconf.SimpleConfigReader}
    @param reader: ConfigReader to use to access the config

    """
    self.reader = reader

  def Exec(self, query): # pylint: disable=R0201,W0613
    """Process a single UDP request from a client.

    Different queries should override this function, which by defaults returns
    a "non-implemented" answer.

    @type query: (undefined)
    @param query: ConfdRequest 'query' field
    @rtype: (integer, undefined)
    @return: status and answer to give to the client

    """
    status = constants.CONFD_REPL_STATUS_NOTIMPLEMENTED
    answer = "not implemented"
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
      answer = "ok"
    else:
      status = constants.CONFD_REPL_STATUS_ERROR
      answer = "non-empty ping query"

    return status, answer


class ClusterMasterQuery(ConfdQuery):
  """Cluster master query.

  It accepts no arguments, and returns the current cluster master.

  """
  def _GetMasterNode(self):
    return self.reader.GetMasterNode()

  def Exec(self, query):
    """ClusterMasterQuery main execution

    """
    if isinstance(query, dict):
      if constants.CONFD_REQQ_FIELDS in query:
        status = constants.CONFD_REPL_STATUS_OK
        req_fields = query[constants.CONFD_REQQ_FIELDS]
        if not isinstance(req_fields, (list, tuple)):
          logging.debug("FIELDS request should be a list")
          return QUERY_ARGUMENT_ERROR

        answer = []
        for field in req_fields:
          if field == constants.CONFD_REQFIELD_NAME:
            answer.append(self._GetMasterNode())
          elif field == constants.CONFD_REQFIELD_IP:
            answer.append(self.reader.GetMasterIP())
          elif field == constants.CONFD_REQFIELD_MNODE_PIP:
            answer.append(self.reader.GetNodePrimaryIp(self._GetMasterNode()))
      else:
        logging.debug("missing FIELDS in query dict")
        return QUERY_ARGUMENT_ERROR
    elif not query:
      status = constants.CONFD_REPL_STATUS_OK
      answer = self.reader.GetMasterNode()
    else:
      logging.debug("Invalid master query argument: not dict or empty")
      return QUERY_ARGUMENT_ERROR

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
  """A query for the location of one or more instance's ips.

  """
  def Exec(self, query):
    """InstanceIpToNodePrimaryIpQuery main execution.

    @type query: string or dict
    @param query: instance ip or dict containing:
                  constants.CONFD_REQQ_LINK: nic link (optional)
                  constants.CONFD_REQQ_IPLIST: list of ips
                  constants.CONFD_REQQ_IP: single ip
                  (one IP type request is mandatory)
    @rtype: (integer, ...)
    @return: ((status, answer) or (success, [(status, answer)...])

    """
    if isinstance(query, dict):
      if constants.CONFD_REQQ_IP in query:
        instances_list = [query[constants.CONFD_REQQ_IP]]
        mode = constants.CONFD_REQQ_IP
      elif constants.CONFD_REQQ_IPLIST in query:
        instances_list = query[constants.CONFD_REQQ_IPLIST]
        mode = constants.CONFD_REQQ_IPLIST
      else:
        logging.debug("missing IP or IPLIST in query dict")
        return QUERY_ARGUMENT_ERROR

      if constants.CONFD_REQQ_LINK in query:
        network_link = query[constants.CONFD_REQQ_LINK]
      else:
        network_link = None # default will be used
    else:
      logging.debug("Invalid query argument type for: %s", query)
      return QUERY_ARGUMENT_ERROR

    pnodes_list = []

    for instance_ip in instances_list:
      if not isinstance(instance_ip, basestring):
        logging.debug("Invalid IP type for: %s", instance_ip)
        return QUERY_ARGUMENT_ERROR

      instance = self.reader.GetInstanceByLinkIp(instance_ip, network_link)
      if not instance:
        logging.debug("Unknown instance IP: %s", instance_ip)
        pnodes_list.append(QUERY_UNKNOWN_ENTRY_ERROR)
        continue

      pnode = self.reader.GetInstancePrimaryNode(instance)
      if not pnode:
        logging.error("Instance '%s' doesn't have an associated primary"
                      " node", instance)
        pnodes_list.append(QUERY_INTERNAL_ERROR)
        continue

      pnode_primary_ip = self.reader.GetNodePrimaryIp(pnode)
      if not pnode_primary_ip:
        logging.error("Primary node '%s' doesn't have an associated"
                      " primary IP", pnode)
        pnodes_list.append(QUERY_INTERNAL_ERROR)
        continue

      pnodes_list.append((constants.CONFD_REPL_STATUS_OK, pnode_primary_ip))

    # If a single ip was requested, return a single answer, otherwise
    # the whole list, with a success status (since each entry has its
    # own success/failure)
    if mode == constants.CONFD_REQQ_IP:
      return pnodes_list[0]

    return constants.CONFD_REPL_STATUS_OK, pnodes_list


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


class NodeDrbdQuery(ConfdQuery):
  """A query for node drbd minors.

  This is not implemented in the Python confd.

  """
