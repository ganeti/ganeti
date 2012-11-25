{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012 Google Inc.

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301, USA.

-}

module Ganeti.OpCodes
  ( OpCode(..)
  , TagObject(..)
  , tagObjectFrom
  , encodeTagObject
  , decodeTagObject
  , ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , opID
  , allOpIDs
  ) where

import Text.JSON (readJSON, showJSON, JSON())

import Ganeti.THH

import Ganeti.OpParams

-- | OpCode representation.
--
-- We only implement a subset of Ganeti opcodes: those which are actually used
-- in the htools codebase.
$(genOpCode "OpCode"
  [ ("OpTestDelay",
     [ pDelayDuration
     , pDelayOnMaster
     , pDelayOnNodes
     , pDelayRepeat
     ])
  , ("OpInstanceReplaceDisks",
     [ pInstanceName
     , pRemoteNode
     , pReplaceDisksMode
     , pReplaceDisksList
     , pIallocator
     ])
  , ("OpInstanceFailover",
     [ pInstanceName
     , pIgnoreConsistency
     , pMigrationTargetNode
     ])
  , ("OpInstanceMigrate",
     [ pInstanceName
     , simpleField "live"           [t| Bool   |]
     , pMigrationCleanup
     , pAllowFailover
     , pMigrationTargetNode
     ])
  , ("OpTagsGet",
     [ pTagsObject
     , pUseLocking
     ])
  , ("OpTagsSearch",
     [ pTagSearchPattern ])
  , ("OpTagsSet",
     [ pTagsObject
     , pTagsList
     ])
  , ("OpTagsDel",
     [ pTagsObject
     , pTagsList
     ])
  , ("OpClusterPostInit", [])
  , ("OpClusterDestroy", [])
  , ("OpClusterQuery", [])
  , ("OpClusterVerify",
     [ pDebugSimulateErrors
     , pErrorCodes
     , pSkipChecks
     , pIgnoreErrors
     , pVerbose
     , pOptGroupName
     ])
  , ("OpClusterVerifyConfig",
     [ pDebugSimulateErrors
     , pErrorCodes
     , pIgnoreErrors
     , pVerbose
     ])
  , ("OpClusterVerifyGroup",
     [ pGroupName
     , pDebugSimulateErrors
     , pErrorCodes
     , pSkipChecks
     , pIgnoreErrors
     , pVerbose
     ])
  , ("OpClusterVerifyDisks", [])
  , ("OpGroupVerifyDisks",
     [ pGroupName
     ])
  , ("OpClusterRepairDiskSizes",
     [ pInstances
     ])
  , ("OpClusterConfigQuery",
     [ pOutputFields
     ])
  , ("OpClusterRename",
     [ pName
     ])
  , ("OpClusterSetParams",
     [ pHvState
     , pDiskState
     , pVgName
     , pEnabledHypervisors
     , pClusterHvParams
     , pClusterBeParams
     , pOsHvp
     , pClusterOsParams
     , pDiskParams
     , pCandidatePoolSize
     , pUidPool
     , pAddUids
     , pRemoveUids
     , pMaintainNodeHealth
     , pPreallocWipeDisks
     , pNicParams
     , pNdParams
     , pIpolicy
     , pDrbdHelper
     , pDefaultIAllocator
     , pMasterNetdev
     , pReservedLvs
     , pHiddenOs
     , pBlacklistedOs
     , pUseExternalMipScript
     ])
  , ("OpClusterRedistConf", [])
  , ("OpClusterActivateMasterIp", [])
  , ("OpClusterDeactivateMasterIp", [])
  , ("OpQuery",
     [ pQueryWhat
     , pUseLocking
     , pQueryFields
     , pQueryFilter
     ])
  , ("OpQueryFields",
     [ pQueryWhat
     , pQueryFields
     ])
  , ("OpOobCommand",
     [ pNodeNames
     , pOobCommand
     , pOobTimeout
     , pIgnoreStatus
     , pPowerDelay
     ])
  , ("OpNodeRemove", [ pNodeName ])
  , ("OpNodeAdd",
     [ pNodeName
     , pHvState
     , pDiskState
     , pPrimaryIp
     , pSecondaryIp
     , pReadd
     , pNodeGroup
     , pMasterCapable
     , pVmCapable
     , pNdParams
    ])
  , ("OpNodeQuery", dOldQuery)
  , ("OpNodeQueryvols",
     [ pOutputFields
     , pNodes
     ])
  , ("OpNodeQueryStorage",
     [ pOutputFields
     , pStorageType
     , pNodes
     , pStorageName
     ])
  , ("OpNodeModifyStorage",
     [ pNodeName
     , pStorageType
     , pStorageName
     , pStorageChanges
     ])
  , ("OpRepairNodeStorage",
     [ pNodeName
     , pStorageType
     , pStorageName
     , pIgnoreConsistency
     ])
  , ("OpNodeSetParams",
     [ pNodeName
     , pForce
     , pHvState
     , pDiskState
     , pMasterCandidate
     , pOffline
     , pDrained
     , pAutoPromote
     , pMasterCapable
     , pVmCapable
     , pSecondaryIp
     , pNdParams
     ])
  , ("OpNodePowercycle",
     [ pNodeName
     , pForce
     ])
  , ("OpNodeMigrate",
     [ pNodeName
     , pMigrationMode
     , pMigrationLive
     , pMigrationTargetNode
     , pAllowRuntimeChgs
     , pIgnoreIpolicy
     , pIallocator
     ])
  , ("OpNodeEvacuate",
     [ pEarlyRelease
     , pNodeName
     , pRemoteNode
     , pIallocator
     , pEvacMode
     ])
  , ("OpInstanceCreate",
     [ pInstanceName
     , pForceVariant
     , pWaitForSync
     , pNameCheck
     , pIgnoreIpolicy
     , pInstBeParams
     , pInstDisks
     , pDiskTemplate
     , pFileDriver
     , pFileStorageDir
     , pInstHvParams
     , pHypervisor
     , pIallocator
     , pResetDefaults
     , pIpCheck
     , pIpConflictsCheck
     , pInstCreateMode
     , pInstNics
     , pNoInstall
     , pInstOsParams
     , pInstOs
     , pPrimaryNode
     , pSecondaryNode
     , pSourceHandshake
     , pSourceInstance
     , pSourceShutdownTimeout
     , pSourceX509Ca
     , pSrcNode
     , pSrcPath
     , pStartInstance
     , pInstTags
     ])
  , ("OpInstanceMultiAlloc",
     [ pIallocator
     , pMultiAllocInstances
     ])
  , ("OpInstanceReinstall",
     [ pInstanceName
     , pForceVariant
     , pInstOs
     , pTempOsParams
     ])
  , ("OpInstanceRemove",
     [ pInstanceName
     , pShutdownTimeout
     , pIgnoreFailures
     ])
  , ("OpInstanceRename",
     [ pInstanceName
     , pNewName
     , pNameCheck
     , pIpCheck
     ])
  , ("OpInstanceStartup",
     [ pInstanceName
     , pForce
     , pIgnoreOfflineNodes
     , pTempHvParams
     , pTempBeParams
     , pNoRemember
     , pStartupPaused
     ])
  , ("OpInstanceShutdown",
     [ pInstanceName
     , pIgnoreOfflineNodes
     , pShutdownTimeout'
     , pNoRemember
     ])
  , ("OpInstanceReboot",
     [ pInstanceName
     , pShutdownTimeout
     , pIgnoreSecondaries
     , pRebootType
     ])
  , ("OpInstanceMove",
     [ pInstanceName
     , pShutdownTimeout
     , pIgnoreIpolicy
     , pMoveTargetNode
     , pIgnoreConsistency
     ])
  , ("OpInstanceConsole",
     [ pInstanceName ])
  , ("OpInstanceActivateDisks",
     [ pInstanceName
     , pIgnoreDiskSize
     , pWaitForSyncFalse
     ])
  , ("OpInstanceDeactivateDisks",
     [ pInstanceName
     , pForce
     ])
  , ("OpInstanceRecreateDisks",
     [ pInstanceName
     , pRecreateDisksInfo
     , pNodes
     , pIallocator
     ])
  , ("OpInstanceQuery", dOldQuery)
  , ("OpInstanceQueryData",
     [ pUseLocking
     , pInstances
     , pStatic
     ])
  , ("OpInstanceSetParams",
     [ pInstanceName
     , pForce
     , pForceVariant
     , pIgnoreIpolicy
     , pInstParamsNicChanges
     , pInstParamsDiskChanges
     , pInstBeParams
     , pRuntimeMem
     , pInstHvParams
     , pDiskTemplate
     , pRemoteNode
     , pOsNameChange
     , pInstOsParams
     , pWaitForSync
     , pOffline
     , pIpConflictsCheck
     ])
  , ("OpInstanceGrowDisk",
     [ pInstanceName
     , pWaitForSync
     , pDiskIndex
     , pDiskChgAmount
     , pDiskChgAbsolute
     ])
  , ("OpInstanceChangeGroup",
     [ pInstanceName
     , pEarlyRelease
     , pIallocator
     , pTargetGroups
     ])
  , ("OpGroupAdd",
     [ pGroupName
     , pNodeGroupAllocPolicy
     , pGroupNodeParams
     , pDiskParams
     , pHvState
     , pDiskState
     , pIpolicy
     ])
  , ("OpGroupAssignNodes",
     [ pGroupName
     , pForce
     , pRequiredNodes
     ])
  , ("OpGroupQuery", dOldQueryNoLocking)
  , ("OpGroupSetParams",
     [ pGroupName
     , pNodeGroupAllocPolicy
     , pGroupNodeParams
     , pDiskParams
     , pHvState
     , pDiskState
     , pIpolicy
     ])
  , ("OpGroupRemove",
     [ pGroupName ])
  , ("OpGroupRename",
     [ pGroupName
     , pNewName
     ])
  , ("OpGroupEvacuate",
     [ pGroupName
     , pEarlyRelease
     , pIallocator
     , pTargetGroups
     ])
  , ("OpOsDiagnose",
     [ pOutputFields
     , pNames ])
  , ("OpBackupQuery",
     [ pUseLocking
     , pNodes
     ])
  , ("OpBackupPrepare",
     [ pInstanceName
     , pExportMode
     ])
  , ("OpBackupExport",
     [ pInstanceName
     , pShutdownTimeout
     , pExportTargetNode
     , pRemoveInstance
     , pIgnoreRemoveFailures
     , pExportMode
     , pX509KeyName
     , pX509DestCA
     ])
  , ("OpBackupRemove",
     [ pInstanceName ])
  , ("OpTestAllocator",
     [ pIAllocatorDirection
     , pIAllocatorMode
     , pIAllocatorReqName
     , pIAllocatorNics
     , pIAllocatorDisks
     , pHypervisor
     , pIallocator
     , pInstTags
     , pIAllocatorMemory
     , pIAllocatorVCpus
     , pIAllocatorOs
     , pDiskTemplate
     , pIAllocatorInstances
     , pIAllocatorEvacMode
     , pTargetGroups
     , pIAllocatorSpindleUse
     , pIAllocatorCount
     ])
  , ("OpTestJqueue",
     [ pJQueueNotifyWaitLock
     , pJQueueNotifyExec
     , pJQueueLogMessages
     , pJQueueFail
     ])
  , ("OpTestDummy",
     [ pTestDummyResult
     , pTestDummyMessages
     , pTestDummyFail
     , pTestDummySubmitJobs
     ])
  , ("OpNetworkAdd",
     [ pNetworkName
     , pNetworkType
     , pNetworkAddress4
     , pNetworkGateway4
     , pNetworkAddress6
     , pNetworkGateway6
     , pNetworkMacPrefix
     , pNetworkAddRsvdIps
     , pInstTags
     ])
  , ("OpNetworkRemove",
     [ pNetworkName
     , pForce
     ])
  , ("OpNetworkSetParams",
     [ pNetworkName
     , pNetworkType
     , pNetworkGateway4
     , pNetworkAddress6
     , pNetworkGateway6
     , pNetworkMacPrefix
     , pNetworkAddRsvdIps
     , pNetworkRemoveRsvdIps
     ])
  , ("OpNetworkConnect",
     [ pGroupName
     , pNetworkName
     , pNetworkMode
     , pNetworkLink
     , pIpConflictsCheck
     ])
  , ("OpNetworkDisconnect",
     [ pGroupName
     , pNetworkName
     , pIpConflictsCheck
     ])
  , ("OpNetworkQuery", dOldQueryNoLocking)
  , ("OpRestrictedCommand",
     [ pUseLocking
     , pRequiredNodes
     , pRestrictedCommand
     ])
  ])

-- | Returns the OP_ID for a given opcode value.
$(genOpID ''OpCode "opID")

-- | A list of all defined/supported opcode IDs.
$(genAllOpIDs ''OpCode "allOpIDs")

instance JSON OpCode where
  readJSON = loadOpCode
  showJSON = saveOpCode
