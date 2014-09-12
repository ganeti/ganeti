#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
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


"""Monitoring related QA tests.

"""

from ganeti import _constants
from ganeti import constants

import qa_config

from qa_utils import AssertCommand
from qa_instance_utils import CreateInstanceByDiskTemplate, \
                              RemoveInstance

MON_COLLECTOR = _constants.PKGLIBDIR + "/mon-collector"


def TestInstStatusCollector():
  """Test the Xen instance status collector.

  """
  enabled_hypervisors = qa_config.GetEnabledHypervisors()

  is_xen = (constants.HT_XEN_PVM in enabled_hypervisors or
            constants.HT_XEN_HVM in enabled_hypervisors)
  if not is_xen:
    return

  # Execute on master on an empty cluster
  AssertCommand([MON_COLLECTOR, "inst-status-xen"])

  #Execute on cluster with instances
  node1 = qa_config.AcquireNode()
  node2 = qa_config.AcquireNode()
  template = qa_config.GetDefaultDiskTemplate()

  instance = CreateInstanceByDiskTemplate([node1, node2], template)
  AssertCommand([MON_COLLECTOR, "inst-status-xen"], node=node1)
  AssertCommand([MON_COLLECTOR, "inst-status-xen"], node=node2)
  RemoveInstance(instance)

  node1.Release()
  node2.Release()
