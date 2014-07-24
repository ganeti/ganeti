#
#

# Copyright (C) 2014 Google Inc.
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


"""Module for the WConfd protocol

"""

import logging
import random
import time

import ganeti.rpc.client as cl
import ganeti.rpc.stub.wconfd as stub
from ganeti.rpc.transport import Transport
from ganeti.rpc import errors


class Client(cl.AbstractStubClient, stub.ClientRpcStub):
  """High-level WConfD client implementation.

  This uses a backing Transport-like class on top of which it
  implements data serialization/deserialization.

  """
  def __init__(self, timeouts=None, transport=Transport):
    """Constructor for the Client class.

    Arguments are the same as for L{AbstractClient}.

    """
    cl.AbstractStubClient.__init__(self, timeouts, transport)
    stub.ClientRpcStub.__init__(self)

    retries = 10
    for try_no in range(0, retries):
      try:
        self._InitTransport()
        return
      except errors.TimeoutError:
        logging.debug("Timout trying to connect to WConfD")
        if try_no == retries -1:
          raise
        logging.debug("Will retry")
        time.sleep(10 * random.random())
