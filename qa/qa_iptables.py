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


"""Manipulates nodes using `iptables` to simulate non-standard network
conditions.

"""

import uuid

import qa_config
import qa_utils

from qa_utils import AssertCommand

# String used as a comment for produced `iptables` results
IPTABLES_COMMENT_MARKER = "ganeti_qa_script"


class RulesContext(object):
  def __init__(self, nodes):
    self._nodes = set()

  def __enter__(self):
    self._marker = IPTABLES_COMMENT_MARKER + "_" + str(uuid.uuid4())
    return Rules(self)

  def __exit__(self, ext_type, exc_val, exc_tb):
    CleanRules(self._nodes, self._marker)

  def _AddNode(self, node):
    self._nodes.add(node)


class Rules(object):
  """Allows to introduce iptable rules and dispose them at the end of a block.

  Don't instantiate this class directly. Use `with RulesContext() as r` instead.
  """

  def __init__(self, ctx=None):
    self._ctx = ctx
    if self._ctx is not None:
      self._marker = self._ctx._marker
    else:
      self._marker = IPTABLES_COMMENT_MARKER

  def _AddNode(self, node):
    if self._ctx is not None:
      self._ctx._AddNode(node)

  def AppendRule(self, node, chain, rule, table="filter"):
    """Appends an `iptables` rule to a given node
    """
    AssertCommand(["iptables", "-t", table, "-A", chain] +
                  rule +
                  ["-m", "comment",
                   "--comment", self._marker],
                  node=node)
    self._AddNode(node)

  def RedirectPort(self, node, host, port, new_port):
    """Adds a rule to a master node that makes a destination host+port visible
    under a different port number.

    """
    self.AppendRule(node, "OUTPUT",
                    ["--protocol", "tcp",
                     "--destination", host, "--dport", str(port),
                     "--jump", "DNAT",
                     "--to-destination", ":" + str(new_port)],
                    table="nat")


GLOBAL_RULES = Rules()


def CleanRules(nodes, marker=IPTABLES_COMMENT_MARKER):
  """Removes all QA `iptables` rules matching a given marker from a given node.

  If no marker is given, the global default is used, which clean all custom
  markers.
  """
  if not hasattr(nodes, '__iter__'):
    nodes = [nodes]
  for node in nodes:
    AssertCommand(("iptables-save | grep -v '%s' | iptables-restore" %
                    (marker, )),
                  node=node)
