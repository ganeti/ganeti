{-# LANGUAGE TemplateHaskell, StandaloneDeriving #-}

{-| Implementation of opcodes parameters.

These are defined in a separate module only due to TemplateHaskell
stage restrictions - expressions defined in the current module can't
be passed to splices. So we have to either parameters/repeat each
parameter definition multiple times, or separate them into this
module.

-}

{-

Copyright (C) 2012, 2014 Google Inc.
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

module Ganeti.OpParams
  ( ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , DiskAccess(..)
  , INicParams(..)
  , IDiskParams(..)
  , RecreateDisksInfo(..)
  , DdmOldChanges(..)
  , SetParamsMods(..)
  , ExportTarget(..)
  , pInstanceName
  , pInstallImage
  , pInstanceCommunication
  , pOptInstanceCommunication
  , pInstanceUuid
  , pInstances
  , pName
  , pTagsList
  , pTagsObject
  , pTagsName
  , pOutputFields
  , pShutdownTimeout
  , pShutdownTimeout'
  , pShutdownInstance
  , pForce
  , pIgnoreOfflineNodes
  , pIgnoreHVVersions
  , pNodeName
  , pNodeUuid
  , pNodeNames
  , pNodeUuids
  , pGroupName
  , pMigrationMode
  , pMigrationLive
  , pMigrationCleanup
  , pForceVariant
  , pWaitForSync
  , pWaitForSyncFalse
  , pIgnoreConsistency
  , pStorageName
  , pUseLocking
  , pOpportunisticLocking
  , pNameCheck
  , pNodeGroupAllocPolicy
  , pGroupNodeParams
  , pQueryWhat
  , pEarlyRelease
  , pIpCheck
  , pIpConflictsCheck
  , pNoRemember
  , pMigrationTargetNode
  , pMigrationTargetNodeUuid
  , pMoveTargetNode
  , pMoveTargetNodeUuid
  , pMoveCompress
  , pBackupCompress
  , pStartupPaused
  , pVerbose
  , pDebug
  , pDebugSimulateErrors
  , pErrorCodes
  , pSkipChecks
  , pIgnoreErrors
  , pOptGroupName
  , pGroupDiskParams
  , pHvState
  , pDiskState
  , pIgnoreIpolicy
  , pHotplug
  , pAllowRuntimeChgs
  , pInstDisks
  , pDiskTemplate
  , pOptDiskTemplate
  , pExtParams
  , pFileDriver
  , pFileStorageDir
  , pClusterFileStorageDir
  , pClusterSharedFileStorageDir
  , pClusterGlusterStorageDir
  , pInstanceCommunicationNetwork
  , pZeroingImage
  , pCompressionTools
  , pVgName
  , pEnabledHypervisors
  , pHypervisor
  , pClusterHvParams
  , pInstHvParams
  , pClusterBeParams
  , pInstBeParams
  , pResetDefaults
  , pOsHvp
  , pClusterOsParams
  , pClusterOsParamsPrivate
  , pInstOsParams
  , pInstOsParamsPrivate
  , pInstOsParamsSecret
  , pCandidatePoolSize
  , pMaxRunningJobs
  , pMaxTrackedJobs
  , pUidPool
  , pAddUids
  , pRemoveUids
  , pMaintainNodeHealth
  , pModifyEtcHosts
  , pPreallocWipeDisks
  , pNicParams
  , pInstNics
  , pNdParams
  , pIpolicy
  , pDrbdHelper
  , pDefaultIAllocator
  , pDefaultIAllocatorParams
  , pMasterNetdev
  , pMasterNetmask
  , pReservedLvs
  , pHiddenOs
  , pBlacklistedOs
  , pUseExternalMipScript
  , pQueryFields
  , pQueryFilter
  , pQueryFieldsFields
  , pOobCommand
  , pOobTimeout
  , pIgnoreStatus
  , pPowerDelay
  , pPrimaryIp
  , pSecondaryIp
  , pReadd
  , pNodeGroup
  , pMasterCapable
  , pVmCapable
  , pNames
  , pNodes
  , pRequiredNodes
  , pRequiredNodeUuids
  , pStorageType
  , pOptStorageType
  , pStorageChanges
  , pMasterCandidate
  , pOffline
  , pDrained
  , pAutoPromote
  , pPowered
  , pIallocator
  , pRemoteNode
  , pRemoteNodeUuid
  , pEvacMode
  , pIgnoreSoftErrors
  , pInstCreateMode
  , pNoInstall
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
  , pForthcoming
  , pCommit
  , pInstTags
  , pMultiAllocInstances
  , pTempOsParams
  , pTempOsParamsPrivate
  , pTempOsParamsSecret
  , pTempHvParams
  , pTempBeParams
  , pIgnoreFailures
  , pNewName
  , pIgnoreSecondaries
  , pRebootType
  , pIgnoreDiskSize
  , pRecreateDisksInfo
  , pStatic
  , pInstParamsNicChanges
  , pInstParamsDiskChanges
  , pRuntimeMem
  , pOsNameChange
  , pDiskIndex
  , pDiskChgAmount
  , pDiskChgAbsolute
  , pTargetGroups
  , pExportMode
  , pExportTargetNode
  , pExportTargetNodeUuid
  , pRemoveInstance
  , pIgnoreRemoveFailures
  , pX509KeyName
  , pX509DestCA
  , pZeroFreeSpace
  , pHelperStartupTimeout
  , pHelperShutdownTimeout
  , pZeroingTimeoutFixed
  , pZeroingTimeoutPerMiB
  , pTagSearchPattern
  , pRestrictedCommand
  , pReplaceDisksMode
  , pReplaceDisksList
  , pAllowFailover
  , pForceFailover
  , pDelayDuration
  , pDelayOnMaster
  , pDelayOnNodes
  , pDelayOnNodeUuids
  , pDelayRepeat
  , pDelayInterruptible
  , pDelayNoLocks
  , pIAllocatorDirection
  , pIAllocatorMode
  , pIAllocatorReqName
  , pIAllocatorNics
  , pIAllocatorDisks
  , pIAllocatorMemory
  , pIAllocatorVCpus
  , pIAllocatorOs
  , pIAllocatorInstances
  , pIAllocatorEvacMode
  , pIAllocatorSpindleUse
  , pIAllocatorCount
  , pJQueueNotifyWaitLock
  , pJQueueNotifyExec
  , pJQueueLogMessages
  , pJQueueFail
  , pTestDummyResult
  , pTestDummyMessages
  , pTestDummyFail
  , pTestDummySubmitJobs
  , pNetworkName
  , pNetworkAddress4
  , pNetworkGateway4
  , pNetworkAddress6
  , pNetworkGateway6
  , pNetworkMacPrefix
  , pNetworkAddRsvdIps
  , pNetworkRemoveRsvdIps
  , pNetworkMode
  , pNetworkLink
  , pNetworkVlan
  , pDryRun
  , pDebugLevel
  , pOpPriority
  , pDependencies
  , pComment
  , pReason
  , pSequential
  , pEnabledDiskTemplates
  , pEnabledUserShutdown
  , pAdminStateSource
  , pEnabledDataCollectors
  , pDataCollectorInterval
  , pNodeSslCerts
  , pSshKeyBits
  , pSshKeyType
  , pRenewSshKeys
  , pNodeSetup
  , pVerifyClutter
  , pLongSleep
  , pIsStrict
  ) where

import Control.Monad (liftM, mplus)
import Control.Monad.Fail (MonadFail)
import Text.JSON (JSON, JSValue(..), JSObject (..), readJSON, showJSON,
                  fromJSString, toJSObject)
import qualified Text.JSON
import Text.JSON.Pretty (pp_value)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.THH
import Ganeti.THH.Field
import Ganeti.Utils
import Ganeti.JSON (GenericContainer)
import Ganeti.Types
import qualified Ganeti.Query.Language as Qlang

-- * Helper functions and types

-- | Build a boolean field.
booleanField :: String -> Field
booleanField = flip simpleField [t| Bool |]

-- | Default a field to 'False'.
defaultFalse :: String -> Field
defaultFalse = defaultField [| False |] . booleanField

-- | Default a field to 'True'.
defaultTrue :: String -> Field
defaultTrue = defaultField [| True |] . booleanField

-- | An alias for a 'String' field.
stringField :: String -> Field
stringField = flip simpleField [t| String |]

-- | An alias for an optional string field.
optionalStringField :: String -> Field
optionalStringField = optionalField . stringField

-- | An alias for an optional non-empty string field.
optionalNEStringField :: String -> Field
optionalNEStringField = optionalField . flip simpleField [t| NonEmptyString |]

-- | Function to force a non-negative value, without returning via a
-- monad. This is needed for, and should be used /only/ in the case of
-- forcing constants. In case the constant is wrong (< 0), this will
-- become a runtime error.
forceNonNeg :: (Num a, Ord a, Show a) => a -> NonNegative a
forceNonNeg i = case mkNonNegative i of
                  Ok n -> n
                  Bad msg -> error msg

-- ** Disks

-- | Disk index type (embedding constraints on the index value via a
-- smart constructor).
newtype DiskIndex = DiskIndex { unDiskIndex :: Int }
  deriving (Show, Eq, Ord)

-- | Smart constructor for 'DiskIndex'.
mkDiskIndex :: (MonadFail m) => Int -> m DiskIndex
mkDiskIndex i | i >= 0 && i < C.maxDisks = return (DiskIndex i)
              | otherwise = fail $ "Invalid value for disk index '" ++
                            show i ++ "', required between 0 and " ++
                            show C.maxDisks

instance JSON DiskIndex where
  readJSON v = readJSON v >>= mkDiskIndex
  showJSON = showJSON . unDiskIndex

-- ** I* param types

-- | Type holding disk access modes.
$(declareSADT "DiskAccess"
  [ ("DiskReadOnly",  'C.diskRdonly)
  , ("DiskReadWrite", 'C.diskRdwr)
  ])
$(makeJSONInstance ''DiskAccess)

-- | NIC modification definition.
$(buildObject "INicParams" "inic"
  [ optionalField $ simpleField C.inicMac    [t| NonEmptyString |]
  , optionalField $ simpleField C.inicIp     [t| String         |]
  , optionalField $ simpleField C.inicMode   [t| NonEmptyString |]
  , optionalField $ simpleField C.inicLink   [t| NonEmptyString |]
  , optionalField $ simpleField C.inicName   [t| NonEmptyString |]
  , optionalField $ simpleField C.inicVlan   [t| String         |]
  , optionalField $ simpleField C.inicBridge [t| NonEmptyString |]
  , optionalField $ simpleField C.inicNetwork [t| NonEmptyString |]
  ])

deriving instance Ord INicParams

-- | Disk modification definition.
$(buildObject "IDiskParams" "idisk"
  [ specialNumericalField 'parseUnitAssumeBinary . optionalField
      $ simpleField C.idiskSize               [t| Int            |]
  , optionalField $ simpleField C.idiskMode   [t| DiskAccess     |]
  , optionalField $ simpleField C.idiskAdopt  [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskVg     [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskMetavg [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskName   [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskProvider [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskSpindles [t| Int          |]
  , optionalField $ simpleField C.idiskAccess   [t| NonEmptyString |]
  , andRestArguments "opaque"
  ])

deriving instance Ord IDiskParams

-- | Disk changes type for OpInstanceRecreateDisks. This is a bit
-- strange, because the type in Python is something like Either
-- [DiskIndex] [DiskChanges], but we can't represent the type of an
-- empty list in JSON, so we have to add a custom case for the empty
-- list.
data RecreateDisksInfo
  = RecreateDisksAll
  | RecreateDisksIndices (NonEmpty DiskIndex)
  | RecreateDisksParams (NonEmpty (DiskIndex, IDiskParams))
    deriving (Eq, Show, Ord)

readRecreateDisks :: JSValue -> Text.JSON.Result RecreateDisksInfo
readRecreateDisks (JSArray []) = return RecreateDisksAll
readRecreateDisks v =
  case readJSON v::Text.JSON.Result [DiskIndex] of
    Text.JSON.Ok indices -> liftM RecreateDisksIndices (mkNonEmpty indices)
    _ -> case readJSON v::Text.JSON.Result [(DiskIndex, IDiskParams)] of
           Text.JSON.Ok params -> liftM RecreateDisksParams (mkNonEmpty params)
           _ -> fail $ "Can't parse disk information as either list of disk"
                ++ " indices or list of disk parameters; value received:"
                ++ show (pp_value v)

instance JSON RecreateDisksInfo where
  readJSON = readRecreateDisks
  showJSON  RecreateDisksAll            = showJSON ()
  showJSON (RecreateDisksIndices idx)   = showJSON idx
  showJSON (RecreateDisksParams params) = showJSON params

-- | Simple type for old-style ddm changes.
data DdmOldChanges = DdmOldIndex (NonNegative Int)
                   | DdmOldMod DdmSimple
                     deriving (Eq, Show, Ord)

readDdmOldChanges :: JSValue -> Text.JSON.Result DdmOldChanges
readDdmOldChanges v =
  case readJSON v::Text.JSON.Result (NonNegative Int) of
    Text.JSON.Ok nn -> return $ DdmOldIndex nn
    _ -> case readJSON v::Text.JSON.Result DdmSimple of
           Text.JSON.Ok ddms -> return $ DdmOldMod ddms
           _ -> fail $ "Can't parse value '" ++ show (pp_value v) ++ "' as"
                ++ " either index or modification"

instance JSON DdmOldChanges where
  showJSON (DdmOldIndex i) = showJSON i
  showJSON (DdmOldMod m)   = showJSON m
  readJSON = readDdmOldChanges

-- | Instance disk or nic modifications.
data SetParamsMods a
  = SetParamsEmpty
  | SetParamsDeprecated (NonEmpty (DdmOldChanges, a))
  | SetParamsNew (NonEmpty (DdmFull, Int, a))
  | SetParamsNewName (NonEmpty (DdmFull, String, a))
    deriving (Eq, Show, Ord)

-- | Custom deserialiser for 'SetParamsMods'.
readSetParams :: (JSON a) => JSValue -> Text.JSON.Result (SetParamsMods a)
readSetParams (JSArray []) = return SetParamsEmpty
readSetParams v =
  liftM SetParamsDeprecated (readJSON v)
  `mplus` liftM SetParamsNew (readJSON v)
  `mplus` liftM SetParamsNewName (readJSON v)

instance (JSON a) => JSON (SetParamsMods a) where
  showJSON SetParamsEmpty = showJSON ()
  showJSON (SetParamsDeprecated v) = showJSON v
  showJSON (SetParamsNew v) = showJSON v
  showJSON (SetParamsNewName v) = showJSON v
  readJSON = readSetParams

-- | Custom type for target_node parameter of OpBackupExport, which
-- varies depending on mode. FIXME: this uses an [JSValue] since
-- we don't care about individual rows (just like the Python code
-- tests). But the proper type could be parsed if we wanted.
data ExportTarget = ExportTargetLocal NonEmptyString
                  | ExportTargetRemote [JSValue]
                    deriving (Eq, Show, Ord)

-- | Custom reader for 'ExportTarget'.
readExportTarget :: JSValue -> Text.JSON.Result ExportTarget
readExportTarget (JSString s) = liftM ExportTargetLocal $
                                mkNonEmpty (fromJSString s)
readExportTarget (JSArray arr) = return $ ExportTargetRemote arr
readExportTarget v = fail $ "Invalid value received for 'target_node': " ++
                     show (pp_value v)

instance JSON ExportTarget where
  showJSON (ExportTargetLocal s)  = showJSON s
  showJSON (ExportTargetRemote l) = showJSON l
  readJSON = readExportTarget

-- * Common opcode parameters

pDryRun :: Field
pDryRun =
  withDoc "Run checks only, don't execute" .
  optionalField $ booleanField "dry_run"

pDebugLevel :: Field
pDebugLevel =
  withDoc "Debug level" .
  optionalField $ simpleField "debug_level" [t| NonNegative Int |]

pOpPriority :: Field
pOpPriority =
  withDoc "Opcode priority. Note: python uses a separate constant,\
          \ we're using the actual value we know it's the default" .
  defaultField [| OpPrioNormal |] $
  simpleField "priority" [t| OpSubmitPriority |]

pDependencies :: Field
pDependencies =
  withDoc "Job dependencies" .
  optionalNullSerField $ simpleField "depends" [t| [JobDependency] |]

pComment :: Field
pComment =
  withDoc "Comment field" .
  optionalNullSerField $ stringField "comment"

pReason :: Field
pReason =
  withDoc "Reason trail field" $
  simpleField C.opcodeReason [t| ReasonTrail |]

pSequential :: Field
pSequential =
  withDoc "Sequential job execution" $
  defaultFalse C.opcodeSequential

-- * Parameters

pDebugSimulateErrors :: Field
pDebugSimulateErrors =
  withDoc "Whether to simulate errors (useful for debugging)" $
  defaultFalse "debug_simulate_errors"

pErrorCodes :: Field
pErrorCodes =
  withDoc "Error codes" $
  defaultFalse "error_codes"

pSkipChecks :: Field
pSkipChecks =
  withDoc "Which checks to skip" .
  defaultField [| emptyListSet |] $
  simpleField "skip_checks" [t| ListSet VerifyOptionalChecks |]

pIgnoreErrors :: Field
pIgnoreErrors =
  withDoc "List of error codes that should be treated as warnings" .
  defaultField [| emptyListSet |] $
  simpleField "ignore_errors" [t| ListSet CVErrorCode |]

pVerbose :: Field
pVerbose =
  withDoc "Verbose mode" $
  defaultFalse "verbose"

pDebug :: Field
pDebug =
  withDoc "Debug mode" $
  defaultFalse "debug"

pOptGroupName :: Field
pOptGroupName =
  withDoc "Optional group name" .
  renameField "OptGroupName" .
  optionalField $ simpleField "group_name" [t| NonEmptyString |]

pGroupName :: Field
pGroupName =
  withDoc "Group name" $
  simpleField "group_name" [t| NonEmptyString |]

-- | Whether to hotplug device.
pHotplug :: Field
pHotplug = defaultTrue "hotplug"

pInstances :: Field
pInstances =
  withDoc "List of instances" .
  defaultField [| [] |] $
  simpleField "instances" [t| [NonEmptyString] |]

pOutputFields :: Field
pOutputFields =
  withDoc "Selected output fields" $
  simpleField "output_fields" [t| [NonEmptyString] |]

pName :: Field
pName =
  withDoc "A generic name" $
  simpleField "name" [t| NonEmptyString |]

pForce :: Field
pForce =
  withDoc "Whether to force the operation" $
  defaultFalse "force"

pHvState :: Field
pHvState =
  withDoc "Set hypervisor states" .
  optionalField $ simpleField "hv_state" [t| JSObject JSValue |]

pDiskState :: Field
pDiskState =
  withDoc "Set disk states" .
  optionalField $ simpleField "disk_state" [t| JSObject JSValue |]

-- | Cluster-wide default directory for storing file-backed disks.
pClusterFileStorageDir :: Field
pClusterFileStorageDir =
  renameField "ClusterFileStorageDir" $
  optionalStringField "file_storage_dir"

-- | Cluster-wide default directory for storing shared-file-backed disks.
pClusterSharedFileStorageDir :: Field
pClusterSharedFileStorageDir =
  renameField "ClusterSharedFileStorageDir" $
  optionalStringField "shared_file_storage_dir"

-- | Cluster-wide default directory for storing Gluster-backed disks.
pClusterGlusterStorageDir :: Field
pClusterGlusterStorageDir =
  renameField "ClusterGlusterStorageDir" $
  optionalStringField "gluster_storage_dir"

pInstallImage :: Field
pInstallImage =
  withDoc "OS image for running OS scripts in a safe environment" $
  optionalStringField "install_image"

pInstanceCommunicationNetwork :: Field
pInstanceCommunicationNetwork =
  optionalStringField "instance_communication_network"

-- | The OS to use when zeroing instance disks.
pZeroingImage :: Field
pZeroingImage =
  optionalStringField "zeroing_image"

-- | The additional tools that can be used to compress data in transit
pCompressionTools :: Field
pCompressionTools =
  withDoc "List of enabled compression tools" . optionalField $
  simpleField "compression_tools" [t| [NonEmptyString] |]

-- | Volume group name.
pVgName :: Field
pVgName =
  withDoc "Volume group name" $
  optionalStringField "vg_name"

pEnabledHypervisors :: Field
pEnabledHypervisors =
  withDoc "List of enabled hypervisors" .
  optionalField $
  simpleField "enabled_hypervisors" [t| [Hypervisor] |]

pClusterHvParams :: Field
pClusterHvParams =
  withDoc "Cluster-wide hypervisor parameters, hypervisor-dependent" .
  renameField "ClusterHvParams" .
  optionalField $
  simpleField "hvparams" [t| GenericContainer String (JSObject JSValue) |]

pClusterBeParams :: Field
pClusterBeParams =
  withDoc "Cluster-wide backend parameter defaults" .
  renameField "ClusterBeParams" .
  optionalField $ simpleField "beparams" [t| JSObject JSValue |]

pOsHvp :: Field
pOsHvp =
  withDoc "Cluster-wide per-OS hypervisor parameter defaults" .
  optionalField $
  simpleField "os_hvp" [t| GenericContainer String (JSObject JSValue) |]

pClusterOsParams :: Field
pClusterOsParams =
  withDoc "Cluster-wide OS parameter defaults" .
  renameField "ClusterOsParams" .
  optionalField $
  simpleField "osparams" [t| GenericContainer String (JSObject JSValue) |]

pClusterOsParamsPrivate :: Field
pClusterOsParamsPrivate =
  withDoc "Cluster-wide private OS parameter defaults" .
  renameField "ClusterOsParamsPrivate" .
  optionalField $
  -- This field needs an unique name to aid Python deserialization
  simpleField "osparams_private_cluster"
    [t| GenericContainer String (JSObject (Private JSValue)) |]

pGroupDiskParams :: Field
pGroupDiskParams =
  withDoc "Disk templates' parameter defaults" .
  optionalField $
  simpleField "diskparams"
              [t| GenericContainer DiskTemplate (JSObject JSValue) |]

pCandidatePoolSize :: Field
pCandidatePoolSize =
  withDoc "Master candidate pool size" .
  optionalField $ simpleField "candidate_pool_size" [t| Positive Int |]

pMaxRunningJobs :: Field
pMaxRunningJobs =
  withDoc "Maximal number of jobs to run simultaneously" .
  optionalField $ simpleField "max_running_jobs" [t| Positive Int |]

pMaxTrackedJobs :: Field
pMaxTrackedJobs =
  withDoc "Maximal number of jobs tracked in the job queue" .
  optionalField $ simpleField "max_tracked_jobs" [t| Positive Int |]


pUidPool :: Field
pUidPool =
  withDoc "Set UID pool, must be list of lists describing UID ranges\
          \ (two items, start and end inclusive)" .
  optionalField $ simpleField "uid_pool" [t| [(Int, Int)] |]

pAddUids :: Field
pAddUids =
  withDoc "Extend UID pool, must be list of lists describing UID\
          \ ranges (two items, start and end inclusive)" .
  optionalField $ simpleField "add_uids" [t| [(Int, Int)] |]

pRemoveUids :: Field
pRemoveUids =
  withDoc "Shrink UID pool, must be list of lists describing UID\
          \ ranges (two items, start and end inclusive) to be removed" .
  optionalField $ simpleField "remove_uids" [t| [(Int, Int)] |]

pMaintainNodeHealth :: Field
pMaintainNodeHealth =
  withDoc "Whether to automatically maintain node health" .
  optionalField $ booleanField "maintain_node_health"

-- | Whether to modify and keep in sync the @/etc/hosts@ files of nodes.
pModifyEtcHosts :: Field
pModifyEtcHosts = optionalField $ booleanField "modify_etc_hosts"

-- | Whether to wipe disks before allocating them to instances.
pPreallocWipeDisks :: Field
pPreallocWipeDisks =
  withDoc "Whether to wipe disks before allocating them to instances" .
  optionalField $ booleanField "prealloc_wipe_disks"

pNicParams :: Field
pNicParams =
  withDoc "Cluster-wide NIC parameter defaults" .
  optionalField $ simpleField "nicparams" [t| INicParams |]

pIpolicy :: Field
pIpolicy =
  withDoc "Ipolicy specs" .
  optionalField $ simpleField "ipolicy" [t| JSObject JSValue |]

pDrbdHelper :: Field
pDrbdHelper =
  withDoc "DRBD helper program" $
  optionalStringField "drbd_helper"

pDefaultIAllocator :: Field
pDefaultIAllocator =
  withDoc "Default iallocator for cluster" $
  optionalStringField "default_iallocator"

pDefaultIAllocatorParams :: Field
pDefaultIAllocatorParams =
  withDoc "Default iallocator parameters for cluster" . optionalField
    $ simpleField "default_iallocator_params" [t| JSObject JSValue |]

pMasterNetdev :: Field
pMasterNetdev =
  withDoc "Master network device" $
  optionalStringField "master_netdev"

pMasterNetmask :: Field
pMasterNetmask =
  withDoc "Netmask of the master IP" .
  optionalField $ simpleField "master_netmask" [t| NonNegative Int |]

pReservedLvs :: Field
pReservedLvs =
  withDoc "List of reserved LVs" .
  optionalField $ simpleField "reserved_lvs" [t| [NonEmptyString] |]

pHiddenOs :: Field
pHiddenOs =
  withDoc "Modify list of hidden operating systems: each modification\
          \ must have two items, the operation and the OS name; the operation\
          \ can be add or remove" .
  optionalField $ simpleField "hidden_os" [t| [(DdmSimple, NonEmptyString)] |]

pBlacklistedOs :: Field
pBlacklistedOs =
  withDoc "Modify list of blacklisted operating systems: each\
          \ modification must have two items, the operation and the OS name;\
          \ the operation can be add or remove" .
  optionalField $
  simpleField "blacklisted_os" [t| [(DdmSimple, NonEmptyString)] |]

pUseExternalMipScript :: Field
pUseExternalMipScript =
  withDoc "Whether to use an external master IP address setup script" .
  optionalField $ booleanField "use_external_mip_script"

pEnabledDiskTemplates :: Field
pEnabledDiskTemplates =
  withDoc "List of enabled disk templates" .
  optionalField $
  simpleField "enabled_disk_templates" [t| [DiskTemplate] |]

pEnabledUserShutdown :: Field
pEnabledUserShutdown =
  withDoc "Whether user shutdown is enabled cluster wide" .
  optionalField $
  simpleField "enabled_user_shutdown" [t| Bool |]

pQueryWhat :: Field
pQueryWhat =
  withDoc "Resource(s) to query for" $
  simpleField "what" [t| Qlang.QueryTypeOp |]

pUseLocking :: Field
pUseLocking =
  withDoc "Whether to use synchronization" $
  defaultFalse "use_locking"

pQueryFields :: Field
pQueryFields =
  withDoc "Requested fields" $
  simpleField "fields" [t| [NonEmptyString] |]

pQueryFilter :: Field
pQueryFilter =
  withDoc "Query filter" .
  optionalField $ simpleField "qfilter" [t| [JSValue] |]

pQueryFieldsFields :: Field
pQueryFieldsFields =
  withDoc "Requested fields; if not given, all are returned" .
  renameField "QueryFieldsFields" $
  optionalField pQueryFields

pNodeNames :: Field
pNodeNames =
  withDoc "List of node names to run the OOB command against" .
  defaultField [| [] |] $ simpleField "node_names" [t| [NonEmptyString] |]

pNodeUuids :: Field
pNodeUuids =
  withDoc "List of node UUIDs" .
  optionalField $ simpleField "node_uuids" [t| [NonEmptyString] |]

pOobCommand :: Field
pOobCommand =
  withDoc "OOB command to run" .
  renameField "OobCommand" $ simpleField "command" [t| OobCommand |]

pOobTimeout :: Field
pOobTimeout =
  withDoc "Timeout before the OOB helper will be terminated" .
  defaultField [| C.oobTimeout |] .
  renameField "OobTimeout" $ simpleField "timeout" [t| Int |]

pIgnoreStatus :: Field
pIgnoreStatus =
  withDoc "Ignores the node offline status for power off" $
  defaultFalse "ignore_status"

pPowerDelay :: Field
pPowerDelay =
  -- FIXME: we can't use the proper type "NonNegative Double", since
  -- the default constant is a plain Double, not a non-negative one.
  -- And trying to fix the constant introduces a cyclic import.
  withDoc "Time in seconds to wait between powering on nodes" .
  defaultField [| C.oobPowerDelay |] $
  simpleField "power_delay" [t| Double |]

pRequiredNodes :: Field
pRequiredNodes =
  withDoc "Required list of node names" .
  renameField "ReqNodes" $ simpleField "nodes" [t| [NonEmptyString] |]

pRequiredNodeUuids :: Field
pRequiredNodeUuids =
  withDoc "Required list of node UUIDs" .
  renameField "ReqNodeUuids" . optionalField $
  simpleField "node_uuids" [t| [NonEmptyString] |]

pRestrictedCommand :: Field
pRestrictedCommand =
  withDoc "Restricted command name" .
  renameField "RestrictedCommand" $
  simpleField "command" [t| NonEmptyString |]

pNodeName :: Field
pNodeName =
  withDoc "A required node name (for single-node LUs)" $
  simpleField "node_name" [t| NonEmptyString |]

pNodeUuid :: Field
pNodeUuid =
  withDoc "A node UUID (for single-node LUs)" .
  optionalField $ simpleField "node_uuid" [t| NonEmptyString |]

pPrimaryIp :: Field
pPrimaryIp =
  withDoc "Primary IP address" .
  optionalField $
  simpleField "primary_ip" [t| NonEmptyString |]

pSecondaryIp :: Field
pSecondaryIp =
  withDoc "Secondary IP address" $
  optionalNEStringField "secondary_ip"

pReadd :: Field
pReadd =
  withDoc "Whether node is re-added to cluster" $
  defaultFalse "readd"

pNodeGroup :: Field
pNodeGroup =
  withDoc "Initial node group" $
  optionalNEStringField "group"

pMasterCapable :: Field
pMasterCapable =
  withDoc "Whether node can become master or master candidate" .
  optionalField $ booleanField "master_capable"

pVmCapable :: Field
pVmCapable =
  withDoc "Whether node can host instances" .
  optionalField $ booleanField "vm_capable"

pNdParams :: Field
pNdParams =
  withDoc "Node parameters" .
  renameField "genericNdParams" .
  optionalField $ simpleField "ndparams" [t| JSObject JSValue |]

pNames :: Field
pNames =
  withDoc "List of names" .
  defaultField [| [] |] $ simpleField "names" [t| [NonEmptyString] |]

pNodes :: Field
pNodes =
  withDoc "List of nodes" .
  defaultField [| [] |] $ simpleField "nodes" [t| [NonEmptyString] |]

pStorageType :: Field
pStorageType =
  withDoc "Storage type" $ simpleField "storage_type" [t| StorageType |]

pOptStorageType :: Field
pOptStorageType =
  withDoc "Storage type" .
  renameField "OptStorageType" .
  optionalField $ simpleField "storage_type" [t| StorageType |]

pStorageName :: Field
pStorageName =
  withDoc "Storage name" .
  renameField "StorageName" .
  optionalField $ simpleField "name" [t| NonEmptyString |]

pStorageChanges :: Field
pStorageChanges =
  withDoc "Requested storage changes" $
  simpleField "changes" [t| JSObject JSValue |]

pIgnoreConsistency :: Field
pIgnoreConsistency =
  withDoc "Whether to ignore disk consistency" $
  defaultFalse "ignore_consistency"

pIgnoreHVVersions :: Field
pIgnoreHVVersions =
  withDoc "Whether to ignore incompatible Hypervisor versions" $
  defaultFalse "ignore_hvversions"

pMasterCandidate :: Field
pMasterCandidate =
  withDoc "Whether the node should become a master candidate" .
  optionalField $ booleanField "master_candidate"

pOffline :: Field
pOffline =
  withDoc "Whether to mark the node or instance offline" .
  optionalField $ booleanField "offline"

pDrained ::Field
pDrained =
  withDoc "Whether to mark the node as drained" .
  optionalField $ booleanField "drained"

pAutoPromote :: Field
pAutoPromote =
  withDoc "Whether node(s) should be promoted to master candidate if\
          \ necessary" $
  defaultFalse "auto_promote"

pPowered :: Field
pPowered =
  withDoc "Whether the node should be marked as powered" .
  optionalField $ booleanField "powered"

pMigrationMode :: Field
pMigrationMode =
  withDoc "Migration type (live/non-live)" .
  renameField "MigrationMode" .
  optionalField $
  simpleField "mode" [t| MigrationMode |]

pMigrationLive :: Field
pMigrationLive =
  withDoc "Obsolete \'live\' migration mode (do not use)" .
  renameField "OldLiveMode" . optionalField $ booleanField "live"

pMigrationTargetNode :: Field
pMigrationTargetNode =
  withDoc "Target node for instance migration/failover" $
  optionalNEStringField "target_node"

pMigrationTargetNodeUuid :: Field
pMigrationTargetNodeUuid =
  withDoc "Target node UUID for instance migration/failover" $
  optionalNEStringField "target_node_uuid"

pAllowRuntimeChgs :: Field
pAllowRuntimeChgs =
  withDoc "Whether to allow runtime changes while migrating" $
  defaultTrue "allow_runtime_changes"

pIgnoreIpolicy :: Field
pIgnoreIpolicy =
  withDoc "Whether to ignore ipolicy violations" $
  defaultFalse "ignore_ipolicy"

pIallocator :: Field
pIallocator =
  withDoc "Iallocator for deciding the target node for shared-storage\
          \ instances" $
  optionalNEStringField "iallocator"

pEarlyRelease :: Field
pEarlyRelease =
  withDoc "Whether to release locks as soon as possible" $
  defaultFalse "early_release"

pRemoteNode :: Field
pRemoteNode =
  withDoc "New secondary node" $
  optionalNEStringField "remote_node"

pRemoteNodeUuid :: Field
pRemoteNodeUuid =
  withDoc "New secondary node UUID" $
  optionalNEStringField "remote_node_uuid"

pEvacMode :: Field
pEvacMode =
  withDoc "Node evacuation mode" .
  renameField "EvacMode" $ simpleField "mode" [t| EvacMode |]

pIgnoreSoftErrors :: Field
pIgnoreSoftErrors =
  withDoc "Ignore soft htools errors" .
  optionalField $
  booleanField "ignore_soft_errors"

pInstanceName :: Field
pInstanceName =
  withDoc "A required instance name (for single-instance LUs)" $
  simpleField "instance_name" [t| String |]

pInstanceCommunication :: Field
pInstanceCommunication =
  withDoc C.instanceCommunicationDoc $
  defaultFalse "instance_communication"

pOptInstanceCommunication :: Field
pOptInstanceCommunication =
  withDoc C.instanceCommunicationDoc .
  renameField "OptInstanceCommunication" .
  optionalField $
  booleanField "instance_communication"

pForceVariant :: Field
pForceVariant =
  withDoc "Whether to force an unknown OS variant" $
  defaultFalse "force_variant"

pWaitForSync :: Field
pWaitForSync =
  withDoc "Whether to wait for the disk to synchronize" $
  defaultTrue "wait_for_sync"

pNameCheck :: Field
pNameCheck =
  withDoc "Whether to check name" $
  defaultFalse "name_check"

pInstBeParams :: Field
pInstBeParams =
  withDoc "Backend parameters for instance" .
  renameField "InstBeParams" .
  defaultField [| toJSObject [] |] $
  simpleField "beparams" [t| JSObject JSValue |]

pInstDisks :: Field
pInstDisks =
  withDoc "List of instance disks" .
  renameField "instDisks" $ simpleField "disks" [t| [IDiskParams] |]

pDiskTemplate :: Field
pDiskTemplate =
  withDoc "Disk template" $
  simpleField "disk_template" [t| DiskTemplate |]

pExtParams :: Field
pExtParams =
  withDoc "List of ExtStorage parameters" .
  renameField "InstExtParams" .
  defaultField [| toJSObject [] |] $
  simpleField "ext_params" [t| JSObject JSValue |]

pFileDriver :: Field
pFileDriver =
  withDoc "Driver for file-backed disks" .
  optionalField $ simpleField "file_driver" [t| FileDriver |]

pFileStorageDir :: Field
pFileStorageDir =
  withDoc "Directory for storing file-backed disks" $
  optionalNEStringField "file_storage_dir"

pInstHvParams :: Field
pInstHvParams =
  withDoc "Hypervisor parameters for instance, hypervisor-dependent" .
  renameField "InstHvParams" .
  defaultField [| toJSObject [] |] $
  simpleField "hvparams" [t| JSObject JSValue |]

pHypervisor :: Field
pHypervisor =
  withDoc "Selected hypervisor for an instance" .
  optionalField $
  simpleField "hypervisor" [t| Hypervisor |]

pResetDefaults :: Field
pResetDefaults =
  withDoc "Reset instance parameters to default if equal" $
  defaultFalse "identify_defaults"

pIpCheck :: Field
pIpCheck =
  withDoc "Whether to ensure instance's IP address is inactive" $
  defaultFalse "ip_check"

pIpConflictsCheck :: Field
pIpConflictsCheck =
  withDoc "Whether to check for conflicting IP addresses" $
  defaultTrue "conflicts_check"

pInstCreateMode :: Field
pInstCreateMode =
  withDoc "Instance creation mode" .
  renameField "InstCreateMode" $ simpleField "mode" [t| InstCreateMode |]

pInstNics :: Field
pInstNics =
  withDoc "List of NIC (network interface) definitions" $
  simpleField "nics" [t| [INicParams] |]

pNoInstall :: Field
pNoInstall =
  withDoc "Do not install the OS (will disable automatic start)" .
  optionalField $ booleanField "no_install"

pInstOs :: Field
pInstOs =
  withDoc "OS type for instance installation" $
  optionalNEStringField "os_type"

pInstOsParams :: Field
pInstOsParams =
  withDoc "OS parameters for instance" .
  renameField "InstOsParams" .
  defaultField [| toJSObject [] |] $
  simpleField "osparams" [t| JSObject JSValue |]

pInstOsParamsPrivate :: Field
pInstOsParamsPrivate =
  withDoc "Private OS parameters for instance" .
  optionalField $
  simpleField "osparams_private" [t| JSObject (Private JSValue) |]

pInstOsParamsSecret :: Field
pInstOsParamsSecret =
  withDoc "Secret OS parameters for instance" .
  optionalField $
  simpleField "osparams_secret" [t| JSObject (Secret JSValue) |]

pPrimaryNode :: Field
pPrimaryNode =
  withDoc "Primary node for an instance" $
  optionalNEStringField "pnode"

pPrimaryNodeUuid :: Field
pPrimaryNodeUuid =
  withDoc "Primary node UUID for an instance" $
  optionalNEStringField "pnode_uuid"

pSecondaryNode :: Field
pSecondaryNode =
  withDoc "Secondary node for an instance" $
  optionalNEStringField "snode"

pSecondaryNodeUuid :: Field
pSecondaryNodeUuid =
  withDoc "Secondary node UUID for an instance" $
  optionalNEStringField "snode_uuid"

pSourceHandshake :: Field
pSourceHandshake =
  withDoc "Signed handshake from source (remote import only)" .
  optionalField $ simpleField "source_handshake" [t| [JSValue] |]

pSourceInstance :: Field
pSourceInstance =
  withDoc "Source instance name (remote import only)" $
  optionalNEStringField "source_instance_name"

-- FIXME: non-negative int, whereas the constant is a plain int.
pSourceShutdownTimeout :: Field
pSourceShutdownTimeout =
  withDoc "How long source instance was given to shut down (remote import\
          \ only)" .
  defaultField [| forceNonNeg C.defaultShutdownTimeout |] $
  simpleField "source_shutdown_timeout" [t| NonNegative Int |]

pSourceX509Ca :: Field
pSourceX509Ca =
  withDoc "Source X509 CA in PEM format (remote import only)" $
  optionalNEStringField "source_x509_ca"

pSrcNode :: Field
pSrcNode =
  withDoc "Source node for import" $
  optionalNEStringField "src_node"

pSrcNodeUuid :: Field
pSrcNodeUuid =
  withDoc "Source node UUID for import" $
  optionalNEStringField "src_node_uuid"

pSrcPath :: Field
pSrcPath =
  withDoc "Source directory for import" $
  optionalNEStringField "src_path"

pStartInstance :: Field
pStartInstance =
  withDoc "Whether to start instance after creation" $
  defaultTrue "start"

pForthcoming :: Field
pForthcoming =
  withDoc "Whether to only reserve resources" $
  defaultFalse "forthcoming"

pCommit :: Field
pCommit =
  withDoc "Commit the already reserved instance" $
  defaultFalse "commit"

-- FIXME: unify/simplify with pTags, once that migrates to NonEmpty String"
pInstTags :: Field
pInstTags =
  withDoc "Instance tags" .
  renameField "InstTags" .
  defaultField [| [] |] $
  simpleField "tags" [t| [NonEmptyString] |]

pMultiAllocInstances :: Field
pMultiAllocInstances =
  withDoc "List of instance create opcodes describing the instances to\
          \ allocate" .
  renameField "InstMultiAlloc" .
  defaultField [| [] |] $
  simpleField "instances"[t| [JSValue] |]

pOpportunisticLocking :: Field
pOpportunisticLocking =
  withDoc "Whether to employ opportunistic locking for nodes, meaning\
          \ nodes already locked by another opcode won't be considered for\
          \ instance allocation (only when an iallocator is used)" $
  defaultFalse "opportunistic_locking"

pInstanceUuid :: Field
pInstanceUuid =
  withDoc "An instance UUID (for single-instance LUs)" .
  optionalField $ simpleField "instance_uuid" [t| NonEmptyString |]

pTempOsParams :: Field
pTempOsParams =
  withDoc "Temporary OS parameters (currently only in reinstall, might be\
          \ added to install as well)" .
  renameField "TempOsParams" .
  optionalField $ simpleField "osparams" [t| JSObject JSValue |]

pTempOsParamsPrivate :: Field
pTempOsParamsPrivate =
  withDoc "Private OS parameters for instance reinstalls" .
  optionalField $
  simpleField "osparams_private" [t| JSObject (Private JSValue) |]

pTempOsParamsSecret :: Field
pTempOsParamsSecret =
  withDoc "Secret OS parameters for instance reinstalls" .
  optionalField $
  simpleField "osparams_secret" [t| JSObject (Secret JSValue) |]

pShutdownTimeout :: Field
pShutdownTimeout =
  withDoc "How long to wait for instance to shut down" .
  defaultField [| forceNonNeg C.defaultShutdownTimeout |] $
  simpleField "shutdown_timeout" [t| NonNegative Int |]

-- | Another name for the shutdown timeout, because we like to be
-- inconsistent.
pShutdownTimeout' :: Field
pShutdownTimeout' =
  withDoc "How long to wait for instance to shut down" .
  renameField "InstShutdownTimeout" .
  defaultField [| forceNonNeg C.defaultShutdownTimeout |] $
  simpleField "timeout" [t| NonNegative Int |]

pIgnoreFailures :: Field
pIgnoreFailures =
  withDoc "Whether to ignore failures during removal" $
  defaultFalse "ignore_failures"

pNewName :: Field
pNewName =
  withDoc "New group or instance name" $
  simpleField "new_name" [t| NonEmptyString |]

pIgnoreOfflineNodes :: Field
pIgnoreOfflineNodes =
  withDoc "Whether to ignore offline nodes" $
  defaultFalse "ignore_offline_nodes"

pTempHvParams :: Field
pTempHvParams =
  withDoc "Temporary hypervisor parameters, hypervisor-dependent" .
  renameField "TempHvParams" .
  defaultField [| toJSObject [] |] $
  simpleField "hvparams" [t| JSObject JSValue |]

pTempBeParams :: Field
pTempBeParams =
  withDoc "Temporary backend parameters" .
  renameField "TempBeParams" .
  defaultField [| toJSObject [] |] $
  simpleField "beparams" [t| JSObject JSValue |]

pNoRemember :: Field
pNoRemember =
  withDoc "Do not remember instance state changes" $
  defaultFalse "no_remember"

pStartupPaused :: Field
pStartupPaused =
  withDoc "Pause instance at startup" $
  defaultFalse "startup_paused"

pIgnoreSecondaries :: Field
pIgnoreSecondaries =
  withDoc "Whether to start the instance even if secondary disks are failing" $
  defaultFalse "ignore_secondaries"

pRebootType :: Field
pRebootType =
  withDoc "How to reboot the instance" $
  simpleField "reboot_type" [t| RebootType |]

pReplaceDisksMode :: Field
pReplaceDisksMode =
  withDoc "Replacement mode" .
  renameField "ReplaceDisksMode" $ simpleField "mode" [t| ReplaceDisksMode |]

pReplaceDisksList :: Field
pReplaceDisksList =
  withDoc "List of disk indices" .
  renameField "ReplaceDisksList" .
  defaultField [| [] |] $
  simpleField "disks" [t| [DiskIndex] |]

pMigrationCleanup :: Field
pMigrationCleanup =
  withDoc "Whether a previously failed migration should be cleaned up" .
  renameField "MigrationCleanup" $ defaultFalse "cleanup"

pAllowFailover :: Field
pAllowFailover =
  withDoc "Whether we can fallback to failover if migration is not possible" $
  defaultFalse "allow_failover"

pForceFailover :: Field
pForceFailover =
  withDoc "Disallow migration moves and always use failovers" $
  defaultFalse "force_failover"

pMoveTargetNode :: Field
pMoveTargetNode =
  withDoc "Target node for instance move" .
  renameField "MoveTargetNode" $
  simpleField "target_node" [t| NonEmptyString |]

pMoveTargetNodeUuid :: Field
pMoveTargetNodeUuid =
  withDoc "Target node UUID for instance move" .
  renameField "MoveTargetNodeUuid" . optionalField $
  simpleField "target_node_uuid" [t| NonEmptyString |]

pMoveCompress :: Field
pMoveCompress =
  withDoc "Compression mode to use during instance moves" .
  defaultField [| C.iecNone |] $
  simpleField "compress" [t| String |]

pBackupCompress :: Field
pBackupCompress =
  withDoc "Compression mode to use for moves during backups/imports" .
  defaultField [| C.iecNone |] $
  simpleField "compress" [t| String |]

pIgnoreDiskSize :: Field
pIgnoreDiskSize =
  withDoc "Whether to ignore recorded disk size" $
  defaultFalse "ignore_size"

pWaitForSyncFalse :: Field
pWaitForSyncFalse =
  withDoc "Whether to wait for the disk to synchronize (defaults to false)" $
  defaultField [| False |] pWaitForSync

pRecreateDisksInfo :: Field
pRecreateDisksInfo =
  withDoc "Disk list for recreate disks" .
  renameField "RecreateDisksInfo" .
  defaultField [| RecreateDisksAll |] $
  simpleField "disks" [t| RecreateDisksInfo |]

pStatic :: Field
pStatic =
  withDoc "Whether to only return configuration data without querying nodes" $
  defaultFalse "static"

pInstParamsNicChanges :: Field
pInstParamsNicChanges =
  withDoc "List of NIC changes" .
  renameField "InstNicChanges" .
  defaultField [| SetParamsEmpty |] $
  simpleField "nics" [t| SetParamsMods INicParams |]

pInstParamsDiskChanges :: Field
pInstParamsDiskChanges =
  withDoc "List of disk changes" .
  renameField "InstDiskChanges" .
  defaultField [| SetParamsEmpty |] $
  simpleField "disks" [t| SetParamsMods IDiskParams |]

pRuntimeMem :: Field
pRuntimeMem =
  withDoc "New runtime memory" .
  optionalField $ simpleField "runtime_mem" [t| Positive Int |]

pOptDiskTemplate :: Field
pOptDiskTemplate =
  withDoc "Instance disk template" .
  optionalField .
  renameField "OptDiskTemplate" $
  simpleField "disk_template" [t| DiskTemplate |]

pOsNameChange :: Field
pOsNameChange =
  withDoc "Change the instance's OS without reinstalling the instance" $
  optionalNEStringField "os_name"

pDiskIndex :: Field
pDiskIndex =
  withDoc "Disk index for e.g. grow disk" .
  renameField "DiskIndex" $ simpleField "disk" [t| DiskIndex |]

pDiskChgAmount :: Field
pDiskChgAmount =
  withDoc "Disk amount to add or grow to" .
  renameField "DiskChgAmount" $ simpleField "amount" [t| NonNegative Int |]

pDiskChgAbsolute :: Field
pDiskChgAbsolute =
  withDoc
    "Whether the amount parameter is an absolute target or a relative one" .
  renameField "DiskChkAbsolute" $ defaultFalse "absolute"

pTargetGroups :: Field
pTargetGroups =
  withDoc
    "Destination group names or UUIDs (defaults to \"all but current group\")" .
  optionalField $ simpleField "target_groups" [t| [NonEmptyString] |]

pNodeGroupAllocPolicy :: Field
pNodeGroupAllocPolicy =
  withDoc "Instance allocation policy" .
  optionalField $
  simpleField "alloc_policy" [t| AllocPolicy |]

pGroupNodeParams :: Field
pGroupNodeParams =
  withDoc "Default node parameters for group" .
  optionalField $ simpleField "ndparams" [t| JSObject JSValue |]

pExportMode :: Field
pExportMode =
  withDoc "Export mode" .
  renameField "ExportMode" $ simpleField "mode" [t| ExportMode |]

-- FIXME: Rename target_node as it changes meaning for different
-- export modes (e.g. "destination")
pExportTargetNode :: Field
pExportTargetNode =
  withDoc "Target node (depends on export mode)" .
  renameField "ExportTarget" $
  simpleField "target_node" [t| ExportTarget |]

pExportTargetNodeUuid :: Field
pExportTargetNodeUuid =
  withDoc "Target node UUID (if local export)" .
  renameField "ExportTargetNodeUuid" . optionalField $
  simpleField "target_node_uuid" [t| NonEmptyString |]

pShutdownInstance :: Field
pShutdownInstance =
  withDoc "Whether to shutdown the instance before export" $
  defaultTrue "shutdown"

pRemoveInstance :: Field
pRemoveInstance =
  withDoc "Whether to remove instance after export" $
  defaultFalse "remove_instance"

pIgnoreRemoveFailures :: Field
pIgnoreRemoveFailures =
  withDoc "Whether to ignore failures while removing instances" $
  defaultFalse "ignore_remove_failures"

pX509KeyName :: Field
pX509KeyName =
  withDoc "Name of X509 key (remote export only)" .
  optionalField $ simpleField "x509_key_name" [t| [JSValue] |]

pX509DestCA :: Field
pX509DestCA =
  withDoc "Destination X509 CA (remote export only)" $
  optionalNEStringField "destination_x509_ca"

pZeroFreeSpace :: Field
pZeroFreeSpace =
  withDoc "Whether to zero the free space on the disks of the instance" $
  defaultFalse "zero_free_space"

pHelperStartupTimeout :: Field
pHelperStartupTimeout =
  withDoc "Startup timeout for the helper VM" .
  optionalField $ simpleField "helper_startup_timeout" [t| Int |]

pHelperShutdownTimeout :: Field
pHelperShutdownTimeout =
  withDoc "Shutdown timeout for the helper VM" .
  optionalField $ simpleField "helper_shutdown_timeout" [t| Int |]

pZeroingTimeoutFixed :: Field
pZeroingTimeoutFixed =
  withDoc "The fixed part of time to wait before declaring the zeroing\
           \ operation to have failed" .
  optionalField $ simpleField "zeroing_timeout_fixed" [t| Int |]

pZeroingTimeoutPerMiB :: Field
pZeroingTimeoutPerMiB =
  withDoc "The variable part of time to wait before declaring the zeroing\
           \ operation to have failed, dependent on total size of disks" .
  optionalField $ simpleField "zeroing_timeout_per_mib" [t| Double |]

pTagsObject :: Field
pTagsObject =
  withDoc "Tag kind" $
  simpleField "kind" [t| TagKind |]

pTagsName :: Field
pTagsName =
  withDoc "Name of object" .
  renameField "TagsGetName" .
  optionalField $ simpleField "name" [t| String |]

pTagsList :: Field
pTagsList =
  withDoc "List of tag names" .
  renameField "TagsList" $
  simpleField "tags" [t| [String] |]

-- FIXME: this should be compiled at load time?
pTagSearchPattern :: Field
pTagSearchPattern =
  withDoc "Search pattern (regular expression)" .
  renameField "TagSearchPattern" $
  simpleField "pattern" [t| NonEmptyString |]

pDelayDuration :: Field
pDelayDuration =
  withDoc "Duration parameter for 'OpTestDelay'" .
  renameField "DelayDuration" $
  simpleField "duration" [t| Double |]

pDelayOnMaster :: Field
pDelayOnMaster =
  withDoc "on_master field for 'OpTestDelay'" .
  renameField "DelayOnMaster" $
  defaultTrue "on_master"

pDelayOnNodes :: Field
pDelayOnNodes =
  withDoc "on_nodes field for 'OpTestDelay'" .
  renameField "DelayOnNodes" .
  defaultField [| [] |] $
  simpleField "on_nodes" [t| [NonEmptyString] |]

pDelayOnNodeUuids :: Field
pDelayOnNodeUuids =
  withDoc "on_node_uuids field for 'OpTestDelay'" .
  renameField "DelayOnNodeUuids" . optionalField $
  simpleField "on_node_uuids" [t| [NonEmptyString] |]

pDelayRepeat :: Field
pDelayRepeat =
  withDoc "Repeat parameter for OpTestDelay" .
  renameField "DelayRepeat" .
  defaultField [| forceNonNeg (0::Int) |] $
  simpleField "repeat" [t| NonNegative Int |]

pDelayInterruptible :: Field
pDelayInterruptible =
  withDoc "Allows socket-based interruption of a running OpTestDelay" .
  renameField "DelayInterruptible" .
  defaultField [| False |] $
  simpleField "interruptible" [t| Bool |]

pDelayNoLocks :: Field
pDelayNoLocks =
  withDoc "Don't take locks during the delay" .
  renameField "DelayNoLocks" $
  defaultTrue "no_locks"

pIAllocatorDirection :: Field
pIAllocatorDirection =
  withDoc "IAllocator test direction" .
  renameField "IAllocatorDirection" $
  simpleField "direction" [t| IAllocatorTestDir |]

pIAllocatorMode :: Field
pIAllocatorMode =
  withDoc "IAllocator test mode" .
  renameField "IAllocatorMode" $
  simpleField "mode" [t| IAllocatorMode |]

pIAllocatorReqName :: Field
pIAllocatorReqName =
  withDoc "IAllocator target name (new instance, node to evac, etc.)" .
  renameField "IAllocatorReqName" $ simpleField "name" [t| NonEmptyString |]

pIAllocatorNics :: Field
pIAllocatorNics =
  withDoc "Custom OpTestIAllocator nics" .
  renameField "IAllocatorNics" .
  optionalField $ simpleField "nics" [t| [INicParams] |]

pIAllocatorDisks :: Field
pIAllocatorDisks =
  withDoc "Custom OpTestAllocator disks" .
  renameField "IAllocatorDisks" .
  optionalField $ simpleField "disks" [t| [JSValue] |]

pIAllocatorMemory :: Field
pIAllocatorMemory =
  withDoc "IAllocator memory field" .
  renameField "IAllocatorMem" .
  optionalField $
  simpleField "memory" [t| NonNegative Int |]

pIAllocatorVCpus :: Field
pIAllocatorVCpus =
  withDoc "IAllocator vcpus field" .
  renameField "IAllocatorVCpus" .
  optionalField $
  simpleField "vcpus" [t| NonNegative Int |]

pIAllocatorOs :: Field
pIAllocatorOs =
  withDoc "IAllocator os field" .
  renameField "IAllocatorOs" $ optionalNEStringField "os"

pIAllocatorInstances :: Field
pIAllocatorInstances =
  withDoc "IAllocator instances field" .
  renameField "IAllocatorInstances" .
  optionalField $
  simpleField "instances" [t| [NonEmptyString] |]

pIAllocatorEvacMode :: Field
pIAllocatorEvacMode =
  withDoc "IAllocator evac mode" .
  renameField "IAllocatorEvacMode" .
  optionalField $
  simpleField "evac_mode" [t| EvacMode |]

pIAllocatorSpindleUse :: Field
pIAllocatorSpindleUse =
  withDoc "IAllocator spindle use" .
  renameField "IAllocatorSpindleUse" .
  defaultField [| forceNonNeg (1::Int) |] $
  simpleField "spindle_use" [t| NonNegative Int |]

pIAllocatorCount :: Field
pIAllocatorCount =
  withDoc "IAllocator count field" .
  renameField "IAllocatorCount" .
  defaultField [| forceNonNeg (1::Int) |] $
  simpleField "count" [t| NonNegative Int |]

pJQueueNotifyWaitLock :: Field
pJQueueNotifyWaitLock =
  withDoc "'OpTestJqueue' notify_waitlock" $
  defaultFalse "notify_waitlock"

pJQueueNotifyExec :: Field
pJQueueNotifyExec =
  withDoc "'OpTestJQueue' notify_exec" $
  defaultFalse "notify_exec"

pJQueueLogMessages :: Field
pJQueueLogMessages =
  withDoc "'OpTestJQueue' log_messages" .
  defaultField [| [] |] $ simpleField "log_messages" [t| [String] |]

pJQueueFail :: Field
pJQueueFail =
  withDoc "'OpTestJQueue' fail attribute" .
  renameField "JQueueFail" $ defaultFalse "fail"

pTestDummyResult :: Field
pTestDummyResult =
  withDoc "'OpTestDummy' result field" .
  renameField "TestDummyResult" $ simpleField "result" [t| JSValue |]

pTestDummyMessages :: Field
pTestDummyMessages =
  withDoc "'OpTestDummy' messages field" .
  renameField "TestDummyMessages" $
  simpleField "messages" [t| JSValue |]

pTestDummyFail :: Field
pTestDummyFail =
  withDoc "'OpTestDummy' fail field" .
  renameField "TestDummyFail" $ simpleField "fail" [t| JSValue |]

pTestDummySubmitJobs :: Field
pTestDummySubmitJobs =
  withDoc "'OpTestDummy' submit_jobs field" .
  renameField "TestDummySubmitJobs" $
  simpleField "submit_jobs" [t| JSValue |]

pNetworkName :: Field
pNetworkName =
  withDoc "Network name" $
  simpleField "network_name" [t| NonEmptyString |]

pNetworkAddress4 :: Field
pNetworkAddress4 =
  withDoc "Network address (IPv4 subnet)" .
  renameField "NetworkAddress4" $
  simpleField "network" [t| IPv4Network |]

pNetworkGateway4 :: Field
pNetworkGateway4 =
  withDoc "Network gateway (IPv4 address)" .
  renameField "NetworkGateway4" .
  optionalField $ simpleField "gateway" [t| IPv4Address |]

pNetworkAddress6 :: Field
pNetworkAddress6 =
  withDoc "Network address (IPv6 subnet)" .
  renameField "NetworkAddress6" .
  optionalField $ simpleField "network6" [t| IPv6Network |]

pNetworkGateway6 :: Field
pNetworkGateway6 =
  withDoc "Network gateway (IPv6 address)" .
  renameField "NetworkGateway6" .
  optionalField $ simpleField "gateway6" [t| IPv6Address |]

pNetworkMacPrefix :: Field
pNetworkMacPrefix =
  withDoc "Network specific mac prefix (that overrides the cluster one)" .
  renameField "NetMacPrefix" $
  optionalNEStringField "mac_prefix"

pNetworkAddRsvdIps :: Field
pNetworkAddRsvdIps =
  withDoc "Which IP addresses to reserve" .
  renameField "NetworkAddRsvdIps" .
  optionalField $
  simpleField "add_reserved_ips" [t| [IPv4Address] |]

pNetworkRemoveRsvdIps :: Field
pNetworkRemoveRsvdIps =
  withDoc "Which external IP addresses to release" .
  renameField "NetworkRemoveRsvdIps" .
  optionalField $
  simpleField "remove_reserved_ips" [t| [IPv4Address] |]

pNetworkMode :: Field
pNetworkMode =
  withDoc "Network mode when connecting to a group" $
  simpleField "network_mode" [t| NICMode |]

pNetworkLink :: Field
pNetworkLink =
  withDoc "Network link when connecting to a group" $
  simpleField "network_link" [t| NonEmptyString |]

pAdminStateSource :: Field
pAdminStateSource =
  withDoc "Who last changed the instance admin state" .
  optionalField $
  simpleField "admin_state_source" [t| AdminStateSource |]

pNetworkVlan :: Field
pNetworkVlan =
  withDoc "Network vlan when connecting to a group" .
  defaultField [| "" |] $ stringField "network_vlan"

pEnabledDataCollectors :: Field
pEnabledDataCollectors =
  withDoc "Set the active data collectors" .
  optionalField $
  simpleField C.dataCollectorsEnabledName [t| GenericContainer String Bool |]

pDataCollectorInterval :: Field
pDataCollectorInterval =
  withDoc "Sets the interval in that data collectors are run" .
  optionalField $
  simpleField C.dataCollectorsIntervalName [t| GenericContainer String Int |]

pNodeSslCerts :: Field
pNodeSslCerts =
  withDoc "Whether to renew node SSL certificates" .
  defaultField [| False |] $
  simpleField "node_certificates" [t| Bool |]

pSshKeyBits :: Field
pSshKeyBits =
  withDoc "The number of bits of the SSH key Ganeti uses" .
  optionalField $ simpleField "ssh_key_bits" [t| Positive Int |]

pSshKeyType :: Field
pSshKeyType =
  withDoc "The type of the SSH key Ganeti uses" .
  optionalField $ simpleField "ssh_key_type" [t| SshKeyType |]

pRenewSshKeys :: Field
pRenewSshKeys =
  withDoc "Whether to renew SSH keys" .
  defaultField [| False |] $
  simpleField "renew_ssh_keys" [t| Bool |]

pNodeSetup :: Field
pNodeSetup =
  withDoc "Whether to perform a SSH setup on the new node" .
  defaultField [| False |] $
  simpleField "node_setup" [t| Bool |]

pVerifyClutter :: Field
pVerifyClutter =
  withDoc "Whether to check for clutter in the 'authorized_keys' file." .
  defaultField [| False |] $
  simpleField "verify_clutter" [t| Bool |]

pLongSleep :: Field
pLongSleep =
  withDoc "Whether to allow long instance shutdowns during exports" .
  defaultField [| False |] $
  simpleField "long_sleep" [t| Bool |]

pIsStrict :: Field
pIsStrict =
  withDoc "Whether the operation is in strict mode or not." .
  defaultField [| True |] $
  simpleField "is_strict" [t| Bool |]
