#!/usr/bin/python -u
#

# Copyright (C) 2013 Google Inc.
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


"""Manipulates nodes using `iptables` to simulate non-standard network
conditions.

"""

import uuid

from qa_utils import AssertCommand

# String used as a comment for produced `iptables` results
IPTABLES_COMMENT_MARKER = "ganeti_qa_script"


class RulesContext(object):
  def __init__(self):
    self._nodes = set()

  def __enter__(self):
    self.marker = IPTABLES_COMMENT_MARKER + "_" + str(uuid.uuid4())
    return Rules(self)

  def __exit__(self, ext_type, exc_val, exc_tb):
    CleanRules(self._nodes, self.marker)

  def AddNode(self, node):
    self._nodes.add(node)


class Rules(object):
  """Allows to introduce iptable rules and dispose them at the end of a block.

  Don't instantiate this class directly. Use `with RulesContext() as r` instead.
  """

  def __init__(self, ctx=None):
    self._ctx = ctx
    if self._ctx is not None:
      self.marker = self._ctx.marker
    else:
      self.marker = IPTABLES_COMMENT_MARKER

  def AddNode(self, node):
    if self._ctx is not None:
      self._ctx.AddNode(node)

  def AppendRule(self, node, chain, rule, table="filter"):
    """Appends an `iptables` rule to a given node
    """
    AssertCommand(["iptables", "-t", table, "-A", chain] +
                  rule +
                  ["-m", "comment",
                   "--comment", self.marker],
                  node=node)
    self.AddNode(node)

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
