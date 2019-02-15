#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Module implementing the master-side code.

This file only imports all LU's (and other classes) in order to re-export them
to clients of cmdlib.

"""

from ganeti.cmdlib.base import \
  LogicalUnit, \
  NoHooksLU, \
  ResultWithJobs

from ganeti.cmdlib.cluster import \
  LUClusterActivateMasterIp, \
  LUClusterDeactivateMasterIp, \
  LUClusterConfigQuery, \
  LUClusterDestroy, \
  LUClusterPostInit, \
  LUClusterQuery, \
  LUClusterRedistConf, \
  LUClusterRename, \
  LUClusterRepairDiskSizes, \
  LUClusterSetParams, \
  LUClusterRenewCrypto
from ganeti.cmdlib.cluster.verify import \
  LUClusterVerify, \
  LUClusterVerifyConfig, \
  LUClusterVerifyGroup, \
  LUClusterVerifyDisks
from ganeti.cmdlib.group import \
  LUGroupAdd, \
  LUGroupAssignNodes, \
  LUGroupSetParams, \
  LUGroupRemove, \
  LUGroupRename, \
  LUGroupEvacuate, \
  LUGroupVerifyDisks
from ganeti.cmdlib.node import \
  LUNodeAdd, \
  LUNodeSetParams, \
  LUNodePowercycle, \
  LUNodeEvacuate, \
  LUNodeMigrate, \
  LUNodeModifyStorage, \
  LUNodeQueryvols, \
  LUNodeQueryStorage, \
  LUNodeRemove, \
  LURepairNodeStorage
from ganeti.cmdlib.instance import \
  LUInstanceRename, \
  LUInstanceRemove, \
  LUInstanceMove, \
  LUInstanceMultiAlloc, \
  LUInstanceChangeGroup
from ganeti.cmdlib.instance_create import \
  LUInstanceCreate
from ganeti.cmdlib.instance_storage import \
  LUInstanceRecreateDisks, \
  LUInstanceGrowDisk, \
  LUInstanceReplaceDisks, \
  LUInstanceActivateDisks, \
  LUInstanceDeactivateDisks
from ganeti.cmdlib.instance_migration import \
  LUInstanceFailover, \
  LUInstanceMigrate
from ganeti.cmdlib.instance_operation import \
  LUInstanceStartup, \
  LUInstanceShutdown, \
  LUInstanceReinstall, \
  LUInstanceReboot, \
  LUInstanceConsole
from ganeti.cmdlib.instance_set_params import \
  LUInstanceSetParams
from ganeti.cmdlib.instance_query import \
  LUInstanceQueryData
from ganeti.cmdlib.backup import \
  LUBackupPrepare, \
  LUBackupExport, \
  LUBackupRemove
from ganeti.cmdlib.query import \
  LUQuery, \
  LUQueryFields
from ganeti.cmdlib.operating_system import \
  LUOsDiagnose
from ganeti.cmdlib.tags import \
  LUTagsGet, \
  LUTagsSearch, \
  LUTagsSet, \
  LUTagsDel
from ganeti.cmdlib.network import \
  LUNetworkAdd, \
  LUNetworkRemove, \
  LUNetworkSetParams, \
  LUNetworkConnect, \
  LUNetworkDisconnect
from ganeti.cmdlib.misc import \
  LUOobCommand, \
  LUExtStorageDiagnose, \
  LURestrictedCommand
from ganeti.cmdlib.test import \
  LUTestOsParams, \
  LUTestDelay, \
  LUTestJqueue, \
  LUTestAllocator
