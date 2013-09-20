#
#

# Copyright (C) 2007, 2011, 2012, 2013 Google Inc.
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
