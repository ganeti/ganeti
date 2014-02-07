{-# LANGUAGE ExistentialQuantification, TemplateHaskell #-}
{-# OPTIONS_GHC -fno-warn-orphans #-}

{-| Implementation of the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.

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
  ( pyClasses
  , OpCode(..)
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
  , resolveDependencies
  , wrapOpCode
  , setOpComment
  , setOpPriority
  ) where

import Text.JSON (readJSON, JSObject, JSON, JSValue(..), makeObj, fromJSObject)
import qualified Text.JSON

import Ganeti.THH

import qualified Ganeti.Hs2Py.OpDoc as OpDoc
import Ganeti.OpParams
import Ganeti.PyValue ()
import Ganeti.Types
import Ganeti.Query.Language (queryTypeOpToRaw)

import Data.List (intercalate)
import Data.Map (Map)

import qualified Ganeti.Constants as C

instance PyValue DiskIndex where
  showValue = showValue . unDiskIndex

instance PyValue IDiskParams where
  showValue _ = error "OpCodes.showValue(IDiskParams): unhandled case"

instance PyValue RecreateDisksInfo where
  showValue RecreateDisksAll = "[]"
  showValue (RecreateDisksIndices is) = showValue is
  showValue (RecreateDisksParams is) = showValue is

instance PyValue a => PyValue (SetParamsMods a) where
  showValue SetParamsEmpty = "[]"
  showValue _ = error "OpCodes.showValue(SetParamsMods): unhandled case"

instance PyValue a => PyValue (NonNegative a) where
  showValue = showValue . fromNonNegative

instance PyValue a => PyValue (NonEmpty a) where
  showValue = showValue . fromNonEmpty

-- FIXME: should use the 'toRaw' function instead of being harcoded or
-- perhaps use something similar to the NonNegative type instead of
-- using the declareSADT
instance PyValue ExportMode where
  showValue ExportModeLocal = show C.exportModeLocal
  showValue ExportModeRemote = show C.exportModeLocal

instance PyValue CVErrorCode where
  showValue = cVErrorCodeToRaw

instance PyValue VerifyOptionalChecks where
  showValue = verifyOptionalChecksToRaw

instance PyValue INicParams where
  showValue = error "instance PyValue INicParams: not implemented"

instance PyValue a => PyValue (JSObject a) where
  showValue obj =
    "{" ++ intercalate ", " (map showPair (fromJSObject obj)) ++ "}"
    where showPair (k, v) = show k ++ ":" ++ showValue v

instance PyValue JSValue where
  showValue (JSObject obj) = showValue obj
  showValue x = show x

type JobIdListOnly = [(Bool, Either String JobId)]

type InstanceMultiAllocResponse =
  ([(Bool, Either String JobId)], NonEmptyString)

type QueryFieldDef =
  (NonEmptyString, NonEmptyString, TagKind, NonEmptyString)

type QueryResponse =
  ([QueryFieldDef], [[(QueryResultCode, JSValue)]])

type QueryFieldsResponse = [QueryFieldDef]

-- | OpCode representation.
--
-- We only implement a subset of Ganeti opcodes: those which are actually used
-- in the htools codebase.
$(genOpCode "OpCode"
  [ ("OpClusterPostInit",
     [t| Bool |],
     OpDoc.opClusterPostInit,
     [],
     [])
  , ("OpClusterDestroy",
     [t| NonEmptyString |],
     OpDoc.opClusterDestroy,
     [],
     [])
  , ("OpClusterQuery",
     [t| JSObject JSValue |],
     OpDoc.opClusterQuery,
     [],
     [])
  , ("OpClusterVerify",
     [t| JobIdListOnly |],
     OpDoc.opClusterVerify,
     [ pDebugSimulateErrors
     , pErrorCodes
     , pSkipChecks
     , pIgnoreErrors
     , pVerbose
     , pOptGroupName
     ],
     [])
  , ("OpClusterVerifyConfig",
     [t| Bool |],
     OpDoc.opClusterVerifyConfig,
     [ pDebugSimulateErrors
     , pErrorCodes
     , pIgnoreErrors
     , pVerbose
     ],
     [])
  , ("OpClusterVerifyGroup",
     [t| Bool |],
     OpDoc.opClusterVerifyGroup,
     [ pGroupName
     , pDebugSimulateErrors
     , pErrorCodes
     , pSkipChecks
     , pIgnoreErrors
     , pVerbose
     ],
     "group_name")
  , ("OpClusterVerifyDisks",
     [t| JobIdListOnly |],
     OpDoc.opClusterVerifyDisks,
     [],
     [])
  , ("OpGroupVerifyDisks",
     [t| (Map String String, [String], Map String [[String]]) |],
     OpDoc.opGroupVerifyDisks,
     [ pGroupName
     ],
     "group_name")
  , ("OpClusterRepairDiskSizes",
     [t| [(NonEmptyString, NonNegative Int, NonEmptyString, NonNegative Int)]|],
     OpDoc.opClusterRepairDiskSizes,
     [ pInstances
     ],
     [])
  , ("OpClusterConfigQuery",
     [t| [JSValue] |],
     OpDoc.opClusterConfigQuery,
     [ pOutputFields
     ],
     [])
  , ("OpClusterRename",
      [t| NonEmptyString |],
      OpDoc.opClusterRename,
     [ pName
     ],
     "name")
  , ("OpClusterSetParams",
     [t| () |],
     OpDoc.opClusterSetParams,
     [ pForce
     , pHvState
     , pDiskState
     , pVgName
     , pEnabledHypervisors
     , pClusterHvParams
     , pClusterBeParams
     , pOsHvp
     , pClusterOsParams
     , pClusterOsParamsPrivate
     , pDiskParams
     , pCandidatePoolSize
     , pMaxRunningJobs
     , pUidPool
     , pAddUids
     , pRemoveUids
     , pMaintainNodeHealth
     , pPreallocWipeDisks
     , pNicParams
     , withDoc "Cluster-wide node parameter defaults" pNdParams
     , withDoc "Cluster-wide ipolicy specs" pIpolicy
     , pDrbdHelper
     , pDefaultIAllocator
     , pDefaultIAllocatorParams
     , pMasterNetdev
     , pMasterNetmask
     , pReservedLvs
     , pHiddenOs
     , pBlacklistedOs
     , pUseExternalMipScript
     , pEnabledDiskTemplates
     , pModifyEtcHosts
     , pClusterFileStorageDir
     , pClusterSharedFileStorageDir
     , pClusterGlusterStorageDir
     ],
     [])
  , ("OpClusterRedistConf",
     [t| () |],
     OpDoc.opClusterRedistConf,
     [],
     [])
  , ("OpClusterActivateMasterIp",
     [t| () |],
     OpDoc.opClusterActivateMasterIp,
     [],
     [])
  , ("OpClusterDeactivateMasterIp",
     [t| () |],
     OpDoc.opClusterDeactivateMasterIp,
     [],
     [])
  , ("OpClusterRenewCrypto",
     [t| () |],
     OpDoc.opClusterRenewCrypto,
     [],
     [])
  , ("OpQuery",
     [t| QueryResponse |],
     OpDoc.opQuery,
     [ pQueryWhat
     , pUseLocking
     , pQueryFields
     , pQueryFilter
     ],
     "what")
  , ("OpQueryFields",
     [t| QueryFieldsResponse |],
     OpDoc.opQueryFields,
     [ pQueryWhat
     , pQueryFieldsFields
     ],
     "what")
  , ("OpOobCommand",
     [t| [[(QueryResultCode, JSValue)]] |],
     OpDoc.opOobCommand,
     [ pNodeNames
     , withDoc "List of node UUIDs to run the OOB command against" pNodeUuids
     , pOobCommand
     , pOobTimeout
     , pIgnoreStatus
     , pPowerDelay
     ],
     [])
  , ("OpRestrictedCommand",
     [t| [(Bool, String)] |],
     OpDoc.opRestrictedCommand,
     [ pUseLocking
     , withDoc
       "Nodes on which the command should be run (at least one)"
       pRequiredNodes
     , withDoc
       "Node UUIDs on which the command should be run (at least one)"
       pRequiredNodeUuids
     , pRestrictedCommand
     ],
     [])
  , ("OpNodeRemove",
     [t| () |],
      OpDoc.opNodeRemove,
     [ pNodeName
     , pNodeUuid
     ],
     "node_name")
  , ("OpNodeAdd",
     [t| () |],
      OpDoc.opNodeAdd,
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
     ],
     "node_name")
  , ("OpNodeQueryvols",
     [t| [JSValue] |],
     OpDoc.opNodeQueryvols,
     [ pOutputFields
     , withDoc "Empty list to query all nodes, node names otherwise" pNodes
     ],
     [])
  , ("OpNodeQueryStorage",
     [t| [[JSValue]] |],
     OpDoc.opNodeQueryStorage,
     [ pOutputFields
     , pStorageTypeOptional
     , withDoc
       "Empty list to query all, list of names to query otherwise"
       pNodes
     , pStorageName
     ],
     [])
  , ("OpNodeModifyStorage",
     [t| () |],
     OpDoc.opNodeModifyStorage,
     [ pNodeName
     , pNodeUuid
     , pStorageType
     , pStorageName
     , pStorageChanges
     ],
     "node_name")
  , ("OpRepairNodeStorage",
      [t| () |],
      OpDoc.opRepairNodeStorage,
     [ pNodeName
     , pNodeUuid
     , pStorageType
     , pStorageName
     , pIgnoreConsistency
     ],
     "node_name")
  , ("OpNodeSetParams",
     [t| [(NonEmptyString, JSValue)] |],
     OpDoc.opNodeSetParams,
     [ pNodeName
     , pNodeUuid
     , pForce
     , pHvState
     , pDiskState
     , pMasterCandidate
     , withDoc "Whether to mark the node offline" pOffline
     , pDrained
     , pAutoPromote
     , pMasterCapable
     , pVmCapable
     , pSecondaryIp
     , pNdParams
     , pPowered
     ],
     "node_name")
  , ("OpNodePowercycle",
     [t| Maybe NonEmptyString |],
     OpDoc.opNodePowercycle,
     [ pNodeName
     , pNodeUuid
     , pForce
     ],
     "node_name")
  , ("OpNodeMigrate",
     [t| JobIdListOnly |],
     OpDoc.opNodeMigrate,
     [ pNodeName
     , pNodeUuid
     , pMigrationMode
     , pMigrationLive
     , pMigrationTargetNode
     , pMigrationTargetNodeUuid
     , pAllowRuntimeChgs
     , pIgnoreIpolicy
     , pIallocator
     ],
     "node_name")
  , ("OpNodeEvacuate",
     [t| JobIdListOnly |],
     OpDoc.opNodeEvacuate,
     [ pEarlyRelease
     , pNodeName
     , pNodeUuid
     , pRemoteNode
     , pRemoteNodeUuid
     , pIallocator
     , pEvacMode
     ],
     "node_name")
  , ("OpInstanceCreate",
     [t| [NonEmptyString] |],
     OpDoc.opInstanceCreate,
     [ pInstanceName
     , pForceVariant
     , pWaitForSync
     , pNameCheck
     , pIgnoreIpolicy
     , pOpportunisticLocking
     , pInstBeParams
     , pInstDisks
     , pOptDiskTemplate
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
     , pBackupCompress
     , pStartInstance
     , pInstTags
     , pInstanceCommunication
     ],
     "instance_name")
  , ("OpInstanceMultiAlloc",
     [t| InstanceMultiAllocResponse |],
     OpDoc.opInstanceMultiAlloc,
     [ pOpportunisticLocking
     , pIallocator
     , pMultiAllocInstances
     ],
     [])
  , ("OpInstanceReinstall",
     [t| () |],
     OpDoc.opInstanceReinstall,
     [ pInstanceName
     , pInstanceUuid
     , pForceVariant
     , pInstOs
     , pTempOsParams
     ],
     "instance_name")
  , ("OpInstanceRemove",
     [t| () |],
     OpDoc.opInstanceRemove,
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreFailures
     ],
     "instance_name")
  , ("OpInstanceRename",
     [t| NonEmptyString |],
     OpDoc.opInstanceRename,
     [ pInstanceName
     , pInstanceUuid
     , withDoc "New instance name" pNewName
     , pNameCheck
     , pIpCheck
     ],
     [])
  , ("OpInstanceStartup",
     [t| () |],
     OpDoc.opInstanceStartup,
     [ pInstanceName
     , pInstanceUuid
     , pForce
     , pIgnoreOfflineNodes
     , pTempHvParams
     , pTempBeParams
     , pNoRemember
     , pStartupPaused
     ],
     "instance_name")
  , ("OpInstanceShutdown",
     [t| () |],
     OpDoc.opInstanceShutdown,
     [ pInstanceName
     , pInstanceUuid
     , pForce
     , pIgnoreOfflineNodes
     , pShutdownTimeout'
     , pNoRemember
     ],
     "instance_name")
  , ("OpInstanceReboot",
     [t| () |],
     OpDoc.opInstanceReboot,
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreSecondaries
     , pRebootType
     ],
     "instance_name")
  , ("OpInstanceReplaceDisks",
     [t| () |],
     OpDoc.opInstanceReplaceDisks,
     [ pInstanceName
     , pInstanceUuid
     , pEarlyRelease
     , pIgnoreIpolicy
     , pReplaceDisksMode
     , pReplaceDisksList
     , pRemoteNode
     , pRemoteNodeUuid
     , pIallocator
     ],
     "instance_name")
  , ("OpInstanceFailover",
     [t| () |],
     OpDoc.opInstanceFailover,
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreConsistency
     , pMigrationTargetNode
     , pMigrationTargetNodeUuid
     , pIgnoreIpolicy
     , pMigrationCleanup
     , pIallocator
     ],
     "instance_name")
  , ("OpInstanceMigrate",
     [t| () |],
     OpDoc.opInstanceMigrate,
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
     ],
     "instance_name")
  , ("OpInstanceMove",
     [t| () |],
     OpDoc.opInstanceMove,
     [ pInstanceName
     , pInstanceUuid
     , pShutdownTimeout
     , pIgnoreIpolicy
     , pMoveTargetNode
     , pMoveTargetNodeUuid
     , pMoveCompress
     , pIgnoreConsistency
     ],
     "instance_name")
  , ("OpInstanceConsole",
     [t| JSObject JSValue |],
     OpDoc.opInstanceConsole,
     [ pInstanceName
     , pInstanceUuid
     ],
     "instance_name")
  , ("OpInstanceActivateDisks",
     [t| [(NonEmptyString, NonEmptyString, NonEmptyString)] |],
     OpDoc.opInstanceActivateDisks,
     [ pInstanceName
     , pInstanceUuid
     , pIgnoreDiskSize
     , pWaitForSyncFalse
     ],
     "instance_name")
  , ("OpInstanceDeactivateDisks",
     [t| () |],
     OpDoc.opInstanceDeactivateDisks,
     [ pInstanceName
     , pInstanceUuid
     , pForce
     ],
     "instance_name")
  , ("OpInstanceRecreateDisks",
     [t| () |],
     OpDoc.opInstanceRecreateDisks,
     [ pInstanceName
     , pInstanceUuid
     , pRecreateDisksInfo
     , withDoc "New instance nodes, if relocation is desired" pNodes
     , withDoc "New instance node UUIDs, if relocation is desired" pNodeUuids
     , pIallocator
     ],
     "instance_name")
  , ("OpInstanceQueryData",
     [t| JSObject (JSObject JSValue) |],
     OpDoc.opInstanceQueryData,
     [ pUseLocking
     , pInstances
     , pStatic
     ],
     [])
  , ("OpInstanceSetParams",
      [t| [(NonEmptyString, JSValue)] |],
      OpDoc.opInstanceSetParams,
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
     , withDoc "Secondary node (used when changing disk template)" pRemoteNode
     , withDoc
       "Secondary node UUID (used when changing disk template)"
       pRemoteNodeUuid
     , pOsNameChange
     , pInstOsParams
     , pInstOsParamsPrivate
     , pWaitForSync
     , withDoc "Whether to mark the instance as offline" pOffline
     , pIpConflictsCheck
     , pHotplug
     , pHotplugIfPossible
     ],
     "instance_name")
  , ("OpInstanceGrowDisk",
     [t| () |],
     OpDoc.opInstanceGrowDisk,
     [ pInstanceName
     , pInstanceUuid
     , pWaitForSync
     , pDiskIndex
     , pDiskChgAmount
     , pDiskChgAbsolute
     ],
     "instance_name")
  , ("OpInstanceChangeGroup",
     [t| JobIdListOnly |],
     OpDoc.opInstanceChangeGroup,
     [ pInstanceName
     , pInstanceUuid
     , pEarlyRelease
     , pIallocator
     , pTargetGroups
     ],
     "instance_name")
  , ("OpGroupAdd",
     [t| () |],
     OpDoc.opGroupAdd,
     [ pGroupName
     , pNodeGroupAllocPolicy
     , pGroupNodeParams
     , pDiskParams
     , pHvState
     , pDiskState
     , withDoc "Group-wide ipolicy specs" pIpolicy
     ],
     "group_name")
  , ("OpGroupAssignNodes",
     [t| () |],
     OpDoc.opGroupAssignNodes,
     [ pGroupName
     , pForce
     , withDoc "List of nodes to assign" pRequiredNodes
     , withDoc "List of node UUIDs to assign" pRequiredNodeUuids
     ],
     "group_name")
  , ("OpGroupSetParams",
     [t| [(NonEmptyString, JSValue)] |],
     OpDoc.opGroupSetParams,
     [ pGroupName
     , pNodeGroupAllocPolicy
     , pGroupNodeParams
     , pDiskParams
     , pHvState
     , pDiskState
     , withDoc "Group-wide ipolicy specs" pIpolicy
     ],
     "group_name")
  , ("OpGroupRemove",
     [t| () |],
     OpDoc.opGroupRemove,
     [ pGroupName
     ],
     "group_name")
  , ("OpGroupRename",
     [t| NonEmptyString |],
     OpDoc.opGroupRename,
     [ pGroupName
     , withDoc "New group name" pNewName
     ],
     [])
  , ("OpGroupEvacuate",
     [t| JobIdListOnly |],
     OpDoc.opGroupEvacuate,
     [ pGroupName
     , pEarlyRelease
     , pIallocator
     , pTargetGroups
     ],
     "group_name")
  , ("OpOsDiagnose",
     [t| [[JSValue]] |],
     OpDoc.opOsDiagnose,
     [ pOutputFields
     , withDoc "Which operating systems to diagnose" pNames
     ],
     [])
  , ("OpExtStorageDiagnose",
     [t| [[JSValue]] |],
     OpDoc.opExtStorageDiagnose,
     [ pOutputFields
     , withDoc "Which ExtStorage Provider to diagnose" pNames
     ],
     [])
  , ("OpBackupPrepare",
     [t| Maybe (JSObject JSValue) |],
     OpDoc.opBackupPrepare,
     [ pInstanceName
     , pInstanceUuid
     , pExportMode
     ],
     "instance_name")
  , ("OpBackupExport",
     [t| (Bool, [Bool]) |],
     OpDoc.opBackupExport,
     [ pInstanceName
     , pInstanceUuid
     , pBackupCompress
     , pShutdownTimeout
     , pExportTargetNode
     , pExportTargetNodeUuid
     , pShutdownInstance
     , pRemoveInstance
     , pIgnoreRemoveFailures
     , defaultField [| ExportModeLocal |] pExportMode
     , pX509KeyName
     , pX509DestCA
     ],
     "instance_name")
  , ("OpBackupRemove",
     [t| () |],
     OpDoc.opBackupRemove,
     [ pInstanceName
     , pInstanceUuid
     ],
     "instance_name")
  , ("OpTagsGet",
     [t| [NonEmptyString] |],
     OpDoc.opTagsGet,
     [ pTagsObject
     , pUseLocking
     , withDoc "Name of object to retrieve tags from" pTagsName
     ],
     "name")
  , ("OpTagsSearch",
     [t| [(NonEmptyString, NonEmptyString)] |],
     OpDoc.opTagsSearch,
     [ pTagSearchPattern
     ],
     "pattern")
  , ("OpTagsSet",
     [t| () |],
     OpDoc.opTagsSet,
     [ pTagsObject
     , pTagsList
     , withDoc "Name of object where tag(s) should be added" pTagsName
     ],
     [])
  , ("OpTagsDel",
     [t| () |],
     OpDoc.opTagsDel,
     [ pTagsObject
     , pTagsList
     , withDoc "Name of object where tag(s) should be deleted" pTagsName
     ],
     [])
  , ("OpTestDelay",
     [t| () |],
     OpDoc.opTestDelay,
     [ pDelayDuration
     , pDelayOnMaster
     , pDelayOnNodes
     , pDelayOnNodeUuids
     , pDelayRepeat
     ],
     "duration")
  , ("OpTestAllocator",
     [t| String |],
     OpDoc.opTestAllocator,
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
     ],
     "iallocator")
  , ("OpTestJqueue",
     [t| Bool |],
     OpDoc.opTestJqueue,
     [ pJQueueNotifyWaitLock
     , pJQueueNotifyExec
     , pJQueueLogMessages
     , pJQueueFail
     ],
     [])
  , ("OpTestDummy",
     [t| () |],
     OpDoc.opTestDummy,
     [ pTestDummyResult
     , pTestDummyMessages
     , pTestDummyFail
     , pTestDummySubmitJobs
     ],
     [])
  , ("OpNetworkAdd",
     [t| () |],
     OpDoc.opNetworkAdd,
     [ pNetworkName
     , pNetworkAddress4
     , pNetworkGateway4
     , pNetworkAddress6
     , pNetworkGateway6
     , pNetworkMacPrefix
     , pNetworkAddRsvdIps
     , pIpConflictsCheck
     , withDoc "Network tags" pInstTags
     ],
     "network_name")
  , ("OpNetworkRemove",
     [t| () |],
     OpDoc.opNetworkRemove,
     [ pNetworkName
     , pForce
     ],
     "network_name")
  , ("OpNetworkSetParams",
     [t| () |],
     OpDoc.opNetworkSetParams,
     [ pNetworkName
     , pNetworkGateway4
     , pNetworkAddress6
     , pNetworkGateway6
     , pNetworkMacPrefix
     , withDoc "Which external IP addresses to reserve" pNetworkAddRsvdIps
     , pNetworkRemoveRsvdIps
     ],
     "network_name")
  , ("OpNetworkConnect",
     [t| () |],
     OpDoc.opNetworkConnect,
     [ pGroupName
     , pNetworkName
     , pNetworkMode
     , pNetworkLink
     , pIpConflictsCheck
     ],
     "network_name")
  , ("OpNetworkDisconnect",
     [t| () |],
     OpDoc.opNetworkDisconnect,
     [ pGroupName
     , pNetworkName
     ],
     "network_name")
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
opSummaryVal OpTagsGet { opKind = s } = Just (show s)
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

-- | Resolve relative dependencies to absolute ones, given the job ID.
resolveDependsCommon :: (Monad m) => CommonOpParams -> JobId -> m CommonOpParams
resolveDependsCommon p@(CommonOpParams { opDepends = Just deps}) jid = do
  deps' <- mapM (`absoluteJobDependency` jid) deps
  return p { opDepends = Just deps' }
resolveDependsCommon p _ = return p

-- | The top-level opcode type.
data MetaOpCode = MetaOpCode { metaParams :: CommonOpParams
                             , metaOpCode :: OpCode
                             } deriving (Show, Eq)

-- | Resolve relative dependencies to absolute ones, given the job Id.
resolveDependencies :: (Monad m) => MetaOpCode -> JobId -> m MetaOpCode
resolveDependencies mopc jid = do
  mpar <- resolveDependsCommon (metaParams mopc) jid
  return (mopc { metaParams = mpar })

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
