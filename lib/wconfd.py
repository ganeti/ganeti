#
#

# Copyright (C) 2014 Google Inc.
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
  # R0904: Too many public methods
  # pylint: disable=R0904
  """High-level WConfD client implementation.

  This uses a backing Transport-like class on top of which it
  implements data serialization/deserialization.

  """
  def __init__(self, timeouts=None, transport=Transport, allow_non_master=None):
    """Constructor for the Client class.

    Arguments are the same as for L{AbstractClient}.

    """
    cl.AbstractStubClient.__init__(self,
                                   timeouts=timeouts,
                                   transport=transport,
                                   allow_non_master=allow_non_master)
    stub.ClientRpcStub.__init__(self)

    retries = 12
    for try_no in range(0, retries):
      try:
        self._InitTransport()
        return
      except errors.TimeoutError:
        logging.debug("Timout trying to connect to WConfD")
        if try_no == retries -1:
          raise
        logging.debug("Will retry")
        time.sleep(try_no * 10 + 10 * random.random())
