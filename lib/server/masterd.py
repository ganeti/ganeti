#
#

# Copyright (C) 2006, 2007, 2010, 2011, 2012 Google Inc.
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


"""Master daemon program.

Some classes deviates from the standard style guide since the
inheritance from parent classes requires it.

"""

# pylint: disable=C0103
# C0103: Invalid name ganeti-masterd

import logging

from ganeti import config
from ganeti import constants
from ganeti import jqueue
from ganeti import utils
import ganeti.rpc.node as rpc


CLIENT_REQUEST_WORKERS = 16

EXIT_NOTMASTER = constants.EXIT_NOTMASTER
EXIT_NODESETUP_ERROR = constants.EXIT_NODESETUP_ERROR


class GanetiContext(object):
  """Context common to all ganeti threads.

  This class creates and holds common objects shared by all threads.

  """
  # pylint: disable=W0212
  # we do want to ensure a singleton here
  _instance = None

  def __init__(self, livelock=None):
    """Constructs a new GanetiContext object.

    There should be only a GanetiContext object at any time, so this
    function raises an error if this is not the case.

    """
    assert self.__class__._instance is None, "double GanetiContext instance"

    # Create a livelock file
    if livelock is None:
      self.livelock = utils.livelock.LiveLock("masterd")
    else:
      self.livelock = livelock

    # Job queue
    cfg = self.GetConfig(None)
    logging.debug("Creating the job queue")
    self.jobqueue = jqueue.JobQueue(self, cfg)

    # setting this also locks the class against attribute modifications
    self.__class__._instance = self

  def __setattr__(self, name, value):
    """Setting GanetiContext attributes is forbidden after initialization.

    """
    assert self.__class__._instance is None, "Attempt to modify Ganeti Context"
    object.__setattr__(self, name, value)

  def GetWConfdContext(self, ec_id):
    return config.GetWConfdContext(ec_id, self.livelock)

  def GetConfig(self, ec_id):
    return config.GetConfig(ec_id, self.livelock)

  # pylint: disable=R0201
  # method could be a function, but keep interface backwards compatible
  def GetRpc(self, cfg):
    return rpc.RpcRunner(cfg, lambda _: None)

  def AddNode(self, cfg, node, ec_id):
    """Adds a node to the configuration.

    """
    # Add it to the configuration
    cfg.AddNode(node, ec_id)

  def RemoveNode(self, cfg, node):
    """Removes a node from the configuration and lock manager.

    """
    # Remove node from configuration
    cfg.RemoveNode(node.uuid)
