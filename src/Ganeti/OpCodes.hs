{-# LANGUAGE ExistentialQuantification, TemplateHaskell, StandaloneDeriving #-}
{-# OPTIONS_GHC -fno-warn-orphans -O0 #-}
-- We have to disable optimisation here, as some versions of ghc otherwise
-- fail to compile this code, at least within reasonable memory limits (40g).

{-| Implementation of the opcodes.

-}

{-

Copyright (C) 2009, 2010, 2011, 2012, 2013, 2014 Google Inc.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
notice, this list of conditions and the following disclaimer in the
documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

-}

module Ganeti.OpCodes
  ( pyClasses
  , OpCode(..)
  , ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , opID
  , opReasonSrcID
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

import Control.Monad.Fail (MonadFail)
import Data.List (intercalate)
import Data.Map (Map)
import qualified Text.JSON
import Text.JSON (readJSON, JSObject, JSON, JSValue(..), fromJSObject)

import qualified Ganeti.Constants as C
import qualified Ganeti.Hs2Py.OpDoc as OpDoc
import Ganeti.JSON (DictObject(..), readJSONfromDict, showJSONtoDict)
import Ganeti.OpParams
import Ganeti.PyValue ()
import Ganeti.Query.Language (queryTypeOpToRaw)
import Ganeti.THH
import Ganeti.Types

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

type JobIdListOnly = Map String [(Bool, Either String JobId)]

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
     , pVerifyClutter
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
     , pVerifyClutter
     ],
     "group_name")
  , ("OpClusterVerifyDisks",
     [t| JobIdListOnly |],
     OpDoc.opClusterVerifyDisks,
     [ pOptGroupName
     , pIsStrict
     ],
     [])
  , ("OpGroupVerifyDisks",
     [t| (Map String String, [String], Map String [[String]]) |],
     OpDoc.opGroupVerifyDisks,
     [ pGroupName
     , pIsStrict
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
     [t| Either () JobIdListOnly |],
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
     , pGroupDiskParams
     , pCandidatePoolSize
     , pMaxRunningJobs
     , pMaxTrackedJobs
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
     , pNetworkMacPrefix
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
     , pInstallImage
     , pInstanceCommunicationNetwork
     , pZeroingImage
     , pCompressionTools
     , pEnabledUserShutdown
     , pEnabledDataCollectors
     , pDataCollectorInterval
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
     [ pNodeSslCerts
     , pRenewSshKeys
     , pSshKeyType
     , pSshKeyBits
     , pVerbose
     , pDebug
     ],
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
     , pNodeSetup
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
     , pOptStorageType
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
     , pIgnoreSoftErrors
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
     , pOptGroupName
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
     , pInstOsParamsPrivate
     , pInstOsParamsSecret
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
     , pForthcoming
     , pCommit
     , pInstTags
     , pInstanceCommunication
     , pHelperStartupTimeout
     , pHelperShutdownTimeout
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
     , pTempOsParamsPrivate
     , pTempOsParamsSecret
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
       -- timeout to cleanup a user down instance
     , pShutdownTimeout
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
     , pAdminStateSource
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
     , pIgnoreHVVersions
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
     [t| [(NonEmptyString, NonEmptyString, Maybe NonEmptyString)] |],
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
     , pExtParams
     , pFileDriver
     , pFileStorageDir
     , pPrimaryNode
     , pPrimaryNodeUuid
     , withDoc "Secondary node (used when changing disk template)" pRemoteNode
     , withDoc
       "Secondary node UUID (used when changing disk template)"
       pRemoteNodeUuid
     , pIallocator
     , pOsNameChange
     , pInstOsParams
     , pInstOsParamsPrivate
     , pWaitForSync
     , withDoc "Whether to mark the instance as offline" pOffline
     , pIpConflictsCheck
     , pHotplug
     , pOptInstanceCommunication
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
     , pIgnoreIpolicy
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
     [t| Either () JobIdListOnly |],
     OpDoc.opGroupAdd,
     [ pGroupName
     , pNodeGroupAllocPolicy
     , pGroupNodeParams
     , pGroupDiskParams
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
     , pGroupDiskParams
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
     , pSequential
     , pForceFailover
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
     , pZeroFreeSpace
     , pZeroingTimeoutFixed
     , pZeroingTimeoutPerMiB
     , pLongSleep
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
     , pDelayInterruptible
     , pDelayNoLocks
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
     , pOptDiskTemplate
     , pIAllocatorInstances
     , pIAllocatorEvacMode
     , pTargetGroups
     , pIAllocatorSpindleUse
     , pIAllocatorCount
     , pOptGroupName
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
  , ("OpTestOsParams",
     [t| () |],
     OpDoc.opTestOsParams,
     [ pInstOsParamsSecret
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
  , ("OpNetworkRename",
     [t| NonEmptyString |],
     OpDoc.opNetworkRename,
     [ pNetworkName
     , withDoc "New network name" pNewName
     ],
     [])
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
     , pNetworkVlan
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

deriving instance Ord OpCode

-- | Returns the OP_ID for a given opcode value.
$(genOpID ''OpCode "opID")

-- | A list of all defined/supported opcode IDs.
$(genAllOpIDs ''OpCode "allOpIDs")

-- | Convert the opcode name to lowercase with underscores and strip
-- the @Op@ prefix.
$(genOpLowerStrip (C.opcodeReasonSrcOpcode ++ ":") ''OpCode "opReasonSrcID")

instance JSON OpCode where
  readJSON = readJSONfromDict
  showJSON = showJSONtoDict

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

deriving instance Ord CommonOpParams

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
resolveDependsCommon :: (MonadFail m) =>
  CommonOpParams -> JobId -> m CommonOpParams
resolveDependsCommon p@(CommonOpParams { opDepends = Just deps}) jid = do
  deps' <- mapM (`absoluteJobDependency` jid) deps
  return p { opDepends = Just deps' }
resolveDependsCommon p _ = return p

-- | The top-level opcode type.
data MetaOpCode = MetaOpCode { metaParams :: CommonOpParams
                             , metaOpCode :: OpCode
                             } deriving (Show, Eq, Ord)

-- | Resolve relative dependencies to absolute ones, given the job Id.
resolveDependencies :: (MonadFail m) => MetaOpCode -> JobId -> m MetaOpCode
resolveDependencies mopc jid = do
  mpar <- resolveDependsCommon (metaParams mopc) jid
  return (mopc { metaParams = mpar })

instance DictObject MetaOpCode where
  toDict (MetaOpCode meta op) = toDict meta ++ toDict op
  fromDictWKeys dict = MetaOpCode <$> fromDictWKeys dict
                                  <*> fromDictWKeys dict

instance JSON MetaOpCode where
  readJSON = readJSONfromDict
  showJSON = showJSONtoDict

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
