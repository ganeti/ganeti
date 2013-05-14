#
#

# Copyright (C) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013 Google Inc.
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


"""Module implementing the master-side code."""

# pylint: disable=W0201,C0302

# W0201 since most LU attributes are defined in CheckPrereq or similar
# functions

# C0302: since we have waaaay too many lines in this module

from ganeti.cmdlib.base import ResultWithJobs, LogicalUnit, NoHooksLU, \
  Tasklet, _QueryBase
from ganeti.cmdlib.common import INSTANCE_DOWN, INSTANCE_ONLINE, \
  INSTANCE_NOT_RUNNING, CAN_CHANGE_INSTANCE_OFFLINE, \
  _ExpandInstanceName, _ExpandItemName, \
  _ExpandNodeName, _ShareAll, _CheckNodeGroupInstances, _GetWantedNodes, \
  _GetWantedInstances, _RunPostHook, _RedistributeAncillaryFiles, \
  _MergeAndVerifyHvState, _MergeAndVerifyDiskState, _GetUpdatedIPolicy, \
  _ComputeNewInstanceViolations, _GetUpdatedParams, _CheckOSParams, \
  _CheckHVParams, _AdjustCandidatePool, _CheckNodePVs, \
  _ComputeIPolicyInstanceViolation, _AnnotateDiskParams, _SupportsOob, \
  _ComputeIPolicySpecViolation, _GetDefaultIAllocator, \
  _CheckInstancesNodeGroups, _LoadNodeEvacResult, _MapInstanceDisksToNodes, \
  _CheckInstanceNodeGroups, _CheckParamsNotGlobal, \
  _IsExclusiveStorageEnabledNode, _CheckInstanceState, \
  _CheckIAllocatorOrNode, _FindFaultyInstanceDisks, _CheckNodeOnline
from ganeti.cmdlib.instance_utils import _AssembleInstanceDisks, \
  _BuildInstanceHookEnvByObject, _GetClusterDomainSecret, \
  _CheckNodeNotDrained, _RemoveDisks, _ShutdownInstanceDisks, \
  _StartInstanceDisks, _RemoveInstance

from ganeti.cmdlib.cluster import LUClusterActivateMasterIp, \
  LUClusterDeactivateMasterIp, LUClusterConfigQuery, LUClusterDestroy, \
  LUClusterPostInit, LUClusterQuery, LUClusterRedistConf, LUClusterRename, \
  LUClusterRepairDiskSizes, LUClusterSetParams, LUClusterVerify, \
  LUClusterVerifyConfig, LUClusterVerifyGroup, LUClusterVerifyDisks
from ganeti.cmdlib.group import LUGroupAdd, LUGroupAssignNodes, \
  LUGroupQuery, LUGroupSetParams, LUGroupRemove, LUGroupRename, \
  LUGroupEvacuate, LUGroupVerifyDisks
from ganeti.cmdlib.node import LUNodeAdd, LUNodeSetParams, \
  LUNodePowercycle, LUNodeEvacuate, LUNodeMigrate, LUNodeModifyStorage, \
  LUNodeQuery, LUNodeQueryvols, LUNodeQueryStorage, LUNodeRemove, \
  LURepairNodeStorage
from ganeti.cmdlib.instance import LUInstanceCreate, LUInstanceRename, \
  LUInstanceRemove, LUInstanceMove, LUInstanceQuery, LUInstanceQueryData, \
  LUInstanceRecreateDisks, LUInstanceGrowDisk, LUInstanceReplaceDisks, \
  LUInstanceActivateDisks, LUInstanceDeactivateDisks, LUInstanceStartup, \
  LUInstanceShutdown, LUInstanceReinstall, LUInstanceReboot, \
  LUInstanceConsole, LUInstanceFailover, LUInstanceMigrate, \
  LUInstanceMultiAlloc, LUInstanceSetParams, LUInstanceChangeGroup
from ganeti.cmdlib.backup import LUBackupQuery, LUBackupPrepare, \
  LUBackupExport, LUBackupRemove
from ganeti.cmdlib.query import LUQuery, LUQueryFields
from ganeti.cmdlib.operating_system import LUOsDiagnose
from ganeti.cmdlib.tags import LUTagsGet, LUTagsSearch, LUTagsSet, LUTagsDel
from ganeti.cmdlib.network import LUNetworkAdd, LUNetworkRemove, \
  LUNetworkSetParams, LUNetworkQuery, LUNetworkConnect, LUNetworkDisconnect
from ganeti.cmdlib.misc import LUOobCommand, LUExtStorageDiagnose, \
  LURestrictedCommand
from ganeti.cmdlib.test import LUTestDelay, LUTestJqueue, LUTestAllocator
