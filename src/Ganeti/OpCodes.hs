{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013 Google Inc.

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
  , allOpFields
  , opSummary
  , CommonOpParams(..)
  , defOpParams
  , MetaOpCode(..)
  , wrapOpCode
  , setOpComment
  , setOpPriority
  ) where

import Data.Maybe (fromMaybe)
import Text.JSON (readJSON, JSON, JSValue, makeObj)
import qualified Text.JSON

import Ganeti.THH

import Ganeti.OpParams
import Ganeti.Types (OpSubmitPriority(..), fromNonEmpty)
import Ganeti.Query.Language (queryTypeOpToRaw)

-- | OpCode representation.
--
-- We only implement a subset of Ganeti opcodes: those which are actually used
-- in the htools codebase.
$(genOpCode "OpCode"
  [ ("OpTestDelay",
     [ pDelayDuration
     , pDelayOnMaster
     , pDelayOnNodes
     , pDelayOnNodeUuids
     , pDelayRepeat
     ])
  , ("OpInstanceReplaceDisks",
     [ pInstanceName
     , pInstanceUuid
     , pEarlyRelease
     , pIgnoreIpolicy
     , pReplaceDisksMode
     , pReplaceDisksList
     , pRemoteNode
     , pRemoteNodeUuid
     , pIallocator
     ])
  , ("OpInstanceFailover",
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreConsistency
     , pMigrationTargetNode
     , pMigrationTargetNodeUuid
     , pIgnoreIpolicy
     , pIallocator
     ])
  , ("OpInstanceMigrate",
     [ pInstanceName
     , pInstanceUuid
     , pMigrationMode
     , pMigrationLive
     , pMigrationTargetNode
     , pMigrationTargetNodeUuid
     , pAllowRuntimeChgs
     , pIgnoreIpolicy
     , pMigrationCleanup
     , pIallocator
     , pAllowFailover
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
     [ pForce
     , pHvState
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
     , pMasterNetmask
     , pReservedLvs
     , pHiddenOs
     , pBlacklistedOs
     , pUseExternalMipScript
     , pEnabledDiskTemplates
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
     , pNodeUuids
     , pOobCommand
     , pOobTimeout
     , pIgnoreStatus
     , pPowerDelay
     ])
  , ("OpNodeRemove",
     [ pNodeName
     , pNodeUuid
     ])
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
     , pNodeUuid
     , pStorageType
     , pStorageName
     , pStorageChanges
     ])
  , ("OpRepairNodeStorage",
     [ pNodeName
     , pNodeUuid
     , pStorageType
     , pStorageName
     , pIgnoreConsistency
     ])
  , ("OpNodeSetParams",
     [ pNodeName
     , pNodeUuid
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
     , pPowered
     ])
  , ("OpNodePowercycle",
     [ pNodeName
     , pNodeUuid
     , pForce
     ])
  , ("OpNodeMigrate",
     [ pNodeName
     , pNodeUuid
     , pMigrationMode
     , pMigrationLive
     , pMigrationTargetNode
     , pMigrationTargetNodeUuid
     , pAllowRuntimeChgs
     , pIgnoreIpolicy
     , pIallocator
     ])
  , ("OpNodeEvacuate",
     [ pEarlyRelease
     , pNodeName
     , pNodeUuid
     , pRemoteNode
     , pRemoteNodeUuid
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
     , pPrimaryNodeUuid
     , pSecondaryNode
     , pSecondaryNodeUuid
     , pSourceHandshake
     , pSourceInstance
     , pSourceShutdownTimeout
     , pSourceX509Ca
     , pSrcNode
     , pSrcNodeUuid
     , pSrcPath
     , pStartInstance
     , pOpportunisticLocking
     , pInstTags
     ])
  , ("OpInstanceMultiAlloc",
     [ pIallocator
     , pMultiAllocInstances
     , pOpportunisticLocking
     ])
  , ("OpInstanceReinstall",
     [ pInstanceName
     , pInstanceUuid
     , pForceVariant
     , pInstOs
     , pTempOsParams
     ])
  , ("OpInstanceRemove",
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreFailures
     ])
  , ("OpInstanceRename",
     [ pInstanceName
     , pInstanceUuid
     , pNewName
     , pNameCheck
     , pIpCheck
     ])
  , ("OpInstanceStartup",
     [ pInstanceName
     , pInstanceUuid
     , pForce
     , pIgnoreOfflineNodes
     , pTempHvParams
     , pTempBeParams
     , pNoRemember
     , pStartupPaused
     ])
  , ("OpInstanceShutdown",
     [ pInstanceName
     , pInstanceUuid
     , pForce
     , pIgnoreOfflineNodes
     , pShutdownTimeout'
     , pNoRemember
     ])
  , ("OpInstanceReboot",
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreSecondaries
     , pRebootType
     ])
  , ("OpInstanceMove",
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreIpolicy
     , pMoveTargetNode
     , pMoveTargetNodeUuid
     , pIgnoreConsistency
     ])
  , ("OpInstanceConsole",
     [ pInstanceName
     , pInstanceUuid
     ])
  , ("OpInstanceActivateDisks",
     [ pInstanceName
     , pInstanceUuid
     , pIgnoreDiskSize
     , pWaitForSyncFalse
     ])
  , ("OpInstanceDeactivateDisks",
     [ pInstanceName
     , pInstanceUuid
     , pForce
     ])
  , ("OpInstanceRecreateDisks",
     [ pInstanceName
     , pInstanceUuid
     , pRecreateDisksInfo
     , pNodes
     , pNodeUuids
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
     , pInstanceUuid
     , pForce
     , pForceVariant
     , pIgnoreIpolicy
     , pInstParamsNicChanges
     , pInstParamsDiskChanges
     , pInstBeParams
     , pRuntimeMem
     , pInstHvParams
     , pOptDiskTemplate
     , pPrimaryNode
     , pPrimaryNodeUuid
     , pRemoteNode
     , pRemoteNodeUuid
     , pOsNameChange
     , pInstOsParams
     , pWaitForSync
     , pOffline
     , pIpConflictsCheck
     ])
  , ("OpInstanceGrowDisk",
     [ pInstanceName
     , pInstanceUuid
     , pWaitForSync
     , pDiskIndex
     , pDiskChgAmount
     , pDiskChgAbsolute
     ])
  , ("OpInstanceChangeGroup",
     [ pInstanceName
     , pInstanceUuid
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
     , pRequiredNodeUuids
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
  , ("OpExtStorageDiagnose",
     [ pOutputFields
     , pNames ])
  , ("OpBackupQuery",
     [ pUseLocking
     , pNodes
     ])
  , ("OpBackupPrepare",
     [ pInstanceName
     , pInstanceUuid
     , pExportMode
     ])
  , ("OpBackupExport",
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pExportTargetNode
     , pExportTargetNodeUuid
     , pShutdownInstance
     , pRemoveInstance
     , pIgnoreRemoveFailures
     , pExportMode
     , pX509KeyName
     , pX509DestCA
     ])
  , ("OpBackupRemove",
     [ pInstanceName
     , pInstanceUuid
     ])
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
     , pNetworkAddress4
     , pNetworkGateway4
     , pNetworkAddress6
     , pNetworkGateway6
     , pNetworkMacPrefix
     , pNetworkAddRsvdIps
     , pIpConflictsCheck
     , pInstTags
     ])
  , ("OpNetworkRemove",
     [ pNetworkName
     , pForce
     ])
  , ("OpNetworkSetParams",
     [ pNetworkName
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
     ])
  , ("OpNetworkQuery", dOldQuery)
  , ("OpRestrictedCommand",
     [ pUseLocking
     , pRequiredNodes
     , pRequiredNodeUuids
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

-- | Generates the summary value for an opcode.
opSummaryVal :: OpCode -> Maybe String
opSummaryVal OpClusterVerifyGroup { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpGroupVerifyDisks { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpClusterRename { opName = s } = Just (fromNonEmpty s)
opSummaryVal OpQuery { opWhat = s } = Just (queryTypeOpToRaw s)
opSummaryVal OpQueryFields { opWhat = s } = Just (queryTypeOpToRaw s)
opSummaryVal OpNodeRemove { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpNodeAdd { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpNodeModifyStorage { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpRepairNodeStorage  { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpNodeSetParams { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpNodePowercycle { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpNodeMigrate { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpNodeEvacuate { opNodeName = s } = Just (fromNonEmpty s)
opSummaryVal OpInstanceCreate { opInstanceName = s } = Just s
opSummaryVal OpInstanceReinstall { opInstanceName = s } = Just s
opSummaryVal OpInstanceRemove { opInstanceName = s } = Just s
-- FIXME: instance rename should show both names; currently it shows none
-- opSummaryVal OpInstanceRename { opInstanceName = s } = Just s
opSummaryVal OpInstanceStartup { opInstanceName = s } = Just s
opSummaryVal OpInstanceShutdown { opInstanceName = s } = Just s
opSummaryVal OpInstanceReboot { opInstanceName = s } = Just s
opSummaryVal OpInstanceReplaceDisks { opInstanceName = s } = Just s
opSummaryVal OpInstanceFailover { opInstanceName = s } = Just s
opSummaryVal OpInstanceMigrate { opInstanceName = s } = Just s
opSummaryVal OpInstanceMove { opInstanceName = s } = Just s
opSummaryVal OpInstanceConsole { opInstanceName = s } = Just s
opSummaryVal OpInstanceActivateDisks { opInstanceName = s } = Just s
opSummaryVal OpInstanceDeactivateDisks { opInstanceName = s } = Just s
opSummaryVal OpInstanceRecreateDisks { opInstanceName = s } = Just s
opSummaryVal OpInstanceSetParams { opInstanceName = s } = Just s
opSummaryVal OpInstanceGrowDisk { opInstanceName = s } = Just s
opSummaryVal OpInstanceChangeGroup { opInstanceName = s } = Just s
opSummaryVal OpGroupAdd { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpGroupAssignNodes { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpGroupSetParams { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpGroupRemove { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpGroupEvacuate { opGroupName = s } = Just (fromNonEmpty s)
opSummaryVal OpBackupPrepare { opInstanceName = s } = Just s
opSummaryVal OpBackupExport { opInstanceName = s } = Just s
opSummaryVal OpBackupRemove { opInstanceName = s } = Just s
opSummaryVal OpTagsGet { opKind = k } =
  Just . fromMaybe "None" $ tagNameOf k
opSummaryVal OpTagsSearch { opTagSearchPattern = s } = Just (fromNonEmpty s)
opSummaryVal OpTestDelay { opDelayDuration = d } = Just (show d)
opSummaryVal OpTestAllocator { opIallocator = s } =
  -- FIXME: Python doesn't handle None fields well, so we have behave the same
  Just $ maybe "None" fromNonEmpty s
opSummaryVal OpNetworkAdd { opNetworkName = s} = Just (fromNonEmpty s)
opSummaryVal OpNetworkRemove { opNetworkName = s} = Just (fromNonEmpty s)
opSummaryVal OpNetworkSetParams { opNetworkName = s} = Just (fromNonEmpty s)
opSummaryVal OpNetworkConnect { opNetworkName = s} = Just (fromNonEmpty s)
opSummaryVal OpNetworkDisconnect { opNetworkName = s} = Just (fromNonEmpty s)
opSummaryVal _ = Nothing

-- | Computes the summary of the opcode.
opSummary :: OpCode -> String
opSummary op =
  case opSummaryVal op of
    Nothing -> op_suffix
    Just s -> op_suffix ++ "(" ++ s ++ ")"
  where op_suffix = drop 3 $ opID op

-- | Generic\/common opcode parameters.
$(buildObject "CommonOpParams" "op"
  [ pDryRun
  , pDebugLevel
  , pOpPriority
  , pDependencies
  , pComment
  , pReason
  ])

-- | Default common parameter values.
defOpParams :: CommonOpParams
defOpParams =
  CommonOpParams { opDryRun     = Nothing
                 , opDebugLevel = Nothing
                 , opPriority   = OpPrioNormal
                 , opDepends    = Nothing
                 , opComment    = Nothing
                 , opReason     = []
                 }

-- | The top-level opcode type.
data MetaOpCode = MetaOpCode { metaParams :: CommonOpParams
                             , metaOpCode :: OpCode
                             } deriving (Show, Eq)

-- | JSON serialisation for 'MetaOpCode'.
showMeta :: MetaOpCode -> JSValue
showMeta (MetaOpCode params op) =
  let objparams = toDictCommonOpParams params
      objop = toDictOpCode op
  in makeObj (objparams ++ objop)

-- | JSON deserialisation for 'MetaOpCode'
readMeta :: JSValue -> Text.JSON.Result MetaOpCode
readMeta v = do
  meta <- readJSON v
  op <- readJSON v
  return $ MetaOpCode meta op

instance JSON MetaOpCode where
  showJSON = showMeta
  readJSON = readMeta

-- | Wraps an 'OpCode' with the default parameters to build a
-- 'MetaOpCode'.
wrapOpCode :: OpCode -> MetaOpCode
wrapOpCode = MetaOpCode defOpParams

-- | Sets the comment on a meta opcode.
setOpComment :: String -> MetaOpCode -> MetaOpCode
setOpComment comment (MetaOpCode common op) =
  MetaOpCode (common { opComment = Just comment}) op

-- | Sets the priority on a meta opcode.
setOpPriority :: OpSubmitPriority -> MetaOpCode -> MetaOpCode
setOpPriority prio (MetaOpCode common op) =
  MetaOpCode (common { opPriority = prio }) op
