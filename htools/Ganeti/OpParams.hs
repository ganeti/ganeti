{-# LANGUAGE TemplateHaskell #-}

{-| Implementation of opcodes parameters.

These are defined in a separate module only due to TemplateHaskell
stage restrictions - expressions defined in the current module can't
be passed to splices. So we have to either parameters/repeat each
parameter definition multiple times, or separate them into this
module.

-}

{-

Copyright (C) 2012 Google Inc.

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

module Ganeti.OpParams
  ( TagType(..)
  , TagObject(..)
  , tagObjectFrom
  , decodeTagObject
  , encodeTagObject
  , ReplaceDisksMode(..)
  , DiskIndex
  , mkDiskIndex
  , unDiskIndex
  , DiskAccess(..)
  , INicParams(..)
  , IDiskParams(..)
  , RecreateDisksInfo(..)
  , DdmOldChanges(..)
  , SetParamsMods(..)
  , pInstanceName
  , pInstances
  , pName
  , pTagsList
  , pTagsObject
  , pOutputFields
  , pShutdownTimeout
  , pShutdownTimeout'
  , pForce
  , pIgnoreOfflineNodes
  , pNodeName
  , pNodeNames
  , pGroupName
  , pMigrationMode
  , pMigrationLive
  , pForceVariant
  , pWaitForSync
  , pWaitForSyncFalse
  , pIgnoreConsistency
  , pStorageName
  , pUseLocking
  , pNameCheck
  , pNodeGroupAllocPolicy
  , pGroupNodeParams
  , pQueryWhat
  , pEarlyRelease
  , pIpCheck
  , pIpConflictsCheck
  , pNoRemember
  , pMigrationTargetNode
  , pMoveTargetNode
  , pStartupPaused
  , pVerbose
  , pDebugSimulateErrors
  , pErrorCodes
  , pSkipChecks
  , pIgnoreErrors
  , pOptGroupName
  , pDiskParams
  , pHvState
  , pDiskState
  , pIgnoreIpolicy
  , pAllowRuntimeChgs
  , pInstDisks
  , pDiskTemplate
  , pFileDriver
  , pFileStorageDir
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
  , pInstOsParams
  , pCandidatePoolSize
  , pUidPool
  , pAddUids
  , pRemoveUids
  , pMaintainNodeHealth
  , pPreallocWipeDisks
  , pNicParams
  , pInstNics
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
  , pQueryFields
  , pQueryFilter
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
  , pStorageType
  , pStorageChanges
  , pMasterCandidate
  , pOffline
  , pDrained
  , pAutoPromote
  , pPowered
  , pIallocator
  , pRemoteNode
  , pEvacMode
  , pInstCreateMode
  , pNoInstall
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
  , pMultiAllocInstances
  , pTempOsParams
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
  ) where

import Control.Monad (liftM)
import qualified Data.Set as Set
import Text.JSON (readJSON, showJSON, JSON, JSValue(..), fromJSString,
                  JSObject, toJSObject)
import qualified Text.JSON
import Text.JSON.Pretty (pp_value)

import Ganeti.BasicTypes
import qualified Ganeti.Constants as C
import Ganeti.THH
import Ganeti.JSON
import Ganeti.Types
import qualified Ganeti.Query.Language as Qlang

-- * Helper functions and types

-- * Type aliases

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

--- | Unchecked value, should be replaced by a better definition.
--- type UncheckedValue = JSValue

-- | Unchecked dict, should be replaced by a better definition.
type UncheckedDict = JSObject JSValue

-- | Unchecked list, shoild be replaced by a better definition.
type UncheckedList = [JSValue]

-- | Function to force a non-negative value, without returning via a
-- monad. This is needed for, and should be used /only/ in the case of
-- forcing constants. In case the constant is wrong (< 0), this will
-- become a runtime error.
forceNonNeg :: (Num a, Ord a, Show a) => a -> NonNegative a
forceNonNeg i = case mkNonNegative i of
                  Ok n -> n
                  Bad msg -> error msg

-- ** Tags

-- | Data type representing what items do the tag operations apply to.
$(declareSADT "TagType"
  [ ("TagTypeInstance", 'C.tagInstance)
  , ("TagTypeNode",     'C.tagNode)
  , ("TagTypeGroup",    'C.tagNodegroup)
  , ("TagTypeCluster",  'C.tagCluster)
  ])
$(makeJSONInstance ''TagType)

-- | Data type holding a tag object (type and object name).
data TagObject = TagInstance String
               | TagNode     String
               | TagGroup    String
               | TagCluster
               deriving (Show, Read, Eq)

-- | Tag type for a given tag object.
tagTypeOf :: TagObject -> TagType
tagTypeOf (TagInstance {}) = TagTypeInstance
tagTypeOf (TagNode     {}) = TagTypeNode
tagTypeOf (TagGroup    {}) = TagTypeGroup
tagTypeOf (TagCluster  {}) = TagTypeCluster

-- | Gets the potential tag object name.
tagNameOf :: TagObject -> Maybe String
tagNameOf (TagInstance s) = Just s
tagNameOf (TagNode     s) = Just s
tagNameOf (TagGroup    s) = Just s
tagNameOf  TagCluster     = Nothing

-- | Builds a 'TagObject' from a tag type and name.
tagObjectFrom :: (Monad m) => TagType -> JSValue -> m TagObject
tagObjectFrom TagTypeInstance (JSString s) =
  return . TagInstance $ fromJSString s
tagObjectFrom TagTypeNode     (JSString s) = return . TagNode $ fromJSString s
tagObjectFrom TagTypeGroup    (JSString s) = return . TagGroup $ fromJSString s
tagObjectFrom TagTypeCluster   JSNull      = return TagCluster
tagObjectFrom t v =
  fail $ "Invalid tag type/name combination: " ++ show t ++ "/" ++
         show (pp_value v)

-- | Name of the tag \"name\" field.
tagNameField :: String
tagNameField = "name"

-- | Custom encoder for 'TagObject' as represented in an opcode.
encodeTagObject :: TagObject -> (JSValue, [(String, JSValue)])
encodeTagObject t = ( showJSON (tagTypeOf t)
                    , [(tagNameField, maybe JSNull showJSON (tagNameOf t))] )

-- | Custom decoder for 'TagObject' as represented in an opcode.
decodeTagObject :: (Monad m) => [(String, JSValue)] -> JSValue -> m TagObject
decodeTagObject obj kind = do
  ttype <- fromJVal kind
  tname <- fromObj obj tagNameField
  tagObjectFrom ttype tname

-- ** Disks

-- | Replace disks type.
$(declareSADT "ReplaceDisksMode"
  [ ("ReplaceOnPrimary",    'C.replaceDiskPri)
  , ("ReplaceOnSecondary",  'C.replaceDiskSec)
  , ("ReplaceNewSecondary", 'C.replaceDiskChg)
  , ("ReplaceAuto",         'C.replaceDiskAuto)
  ])
$(makeJSONInstance ''ReplaceDisksMode)

-- | Disk index type (embedding constraints on the index value via a
-- smart constructor).
newtype DiskIndex = DiskIndex { unDiskIndex :: Int }
  deriving (Show, Read, Eq, Ord)

-- | Smart constructor for 'DiskIndex'.
mkDiskIndex :: (Monad m) => Int -> m DiskIndex
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
  [ optionalField $ simpleField C.inicMac  [t| NonEmptyString |]
  , optionalField $ simpleField C.inicIp   [t| String         |]
  , optionalField $ simpleField C.inicMode [t| NonEmptyString |]
  , optionalField $ simpleField C.inicLink [t| NonEmptyString |]
  ])

-- | Disk modification definition. FIXME: disksize should be VTYPE_UNIT.
$(buildObject "IDiskParams" "idisk"
  [ optionalField $ simpleField C.idiskSize   [t| Int            |]
  , optionalField $ simpleField C.idiskMode   [t| DiskAccess     |]
  , optionalField $ simpleField C.idiskAdopt  [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskVg     [t| NonEmptyString |]
  , optionalField $ simpleField C.idiskMetavg [t| NonEmptyString |]
  ])

-- | Disk changes type for OpInstanceRecreateDisks. This is a bit
-- strange, because the type in Python is something like Either
-- [DiskIndex] [DiskChanges], but we can't represent the type of an
-- empty list in JSON, so we have to add a custom case for the empty
-- list.
data RecreateDisksInfo
  = RecreateDisksAll
  | RecreateDisksIndices (NonEmpty DiskIndex)
  | RecreateDisksParams (NonEmpty (DiskIndex, IDiskParams))
    deriving (Eq, Read, Show)

readRecreateDisks :: JSValue -> Text.JSON.Result RecreateDisksInfo
readRecreateDisks (JSArray []) = return RecreateDisksAll
readRecreateDisks v =
  case readJSON v::Text.JSON.Result [DiskIndex] of
    Text.JSON.Ok indices -> liftM RecreateDisksIndices (mkNonEmpty indices)
    _ -> case readJSON v::Text.JSON.Result [(DiskIndex, IDiskParams)] of
           Text.JSON.Ok params -> liftM RecreateDisksParams (mkNonEmpty params)
           _ -> fail $ "Can't parse disk information as either list of disk"
                ++ " indices or list of disk parameters; value recevied:"
                ++ show (pp_value v)

instance JSON RecreateDisksInfo where
  readJSON = readRecreateDisks
  showJSON  RecreateDisksAll            = showJSON ()
  showJSON (RecreateDisksIndices idx)   = showJSON idx
  showJSON (RecreateDisksParams params) = showJSON params

-- | Simple type for old-style ddm changes.
data DdmOldChanges = DdmOldIndex (NonNegative Int)
                   | DdmOldMod DdmSimple
                     deriving (Eq, Read, Show)

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
    deriving (Eq, Read, Show)

-- | Custom deserialiser for 'SetParamsMods'.
readSetParams :: (JSON a) => JSValue -> Text.JSON.Result (SetParamsMods a)
readSetParams (JSArray []) = return SetParamsEmpty
readSetParams v =
  case readJSON v::Text.JSON.Result [(DdmOldChanges, JSValue)] of
    Text.JSON.Ok _ -> liftM SetParamsDeprecated $ readJSON v
    _ -> liftM SetParamsNew $ readJSON v

instance (JSON a) => JSON (SetParamsMods a) where
  showJSON SetParamsEmpty = showJSON ()
  showJSON (SetParamsDeprecated v) = showJSON v
  showJSON (SetParamsNew v) = showJSON v
  readJSON = readSetParams

-- * Parameters

-- | A required instance name (for single-instance LUs).
pInstanceName :: Field
pInstanceName = simpleField "instance_name" [t| String |]

-- | A list of instances.
pInstances :: Field
pInstances = defaultField [| [] |] $
             simpleField "instances" [t| [NonEmptyString] |]

-- | A generic name.
pName :: Field
pName = simpleField "name" [t| NonEmptyString |]

-- | Tags list.
pTagsList :: Field
pTagsList = simpleField "tags" [t| [String] |]

-- | Tags object.
pTagsObject :: Field
pTagsObject = customField 'decodeTagObject 'encodeTagObject $
              simpleField "kind" [t| TagObject |]

-- | Selected output fields.
pOutputFields :: Field
pOutputFields = simpleField "output_fields" [t| [NonEmptyString] |]

-- | How long to wait for instance to shut down.
pShutdownTimeout :: Field
pShutdownTimeout = defaultField [| forceNonNeg C.defaultShutdownTimeout |] $
                   simpleField "shutdown_timeout" [t| NonNegative Int |]

-- | Another name for the shutdown timeout, because we like to be
-- inconsistent.
pShutdownTimeout' :: Field
pShutdownTimeout' =
  renameField "InstShutdownTimeout" .
  defaultField [| forceNonNeg C.defaultShutdownTimeout |] $
  simpleField "timeout" [t| NonNegative Int |]

-- | Whether to force the operation.
pForce :: Field
pForce = defaultFalse "force"

-- | Whether to ignore offline nodes.
pIgnoreOfflineNodes :: Field
pIgnoreOfflineNodes = defaultFalse "ignore_offline_nodes"

-- | A required node name (for single-node LUs).
pNodeName :: Field
pNodeName = simpleField "node_name" [t| NonEmptyString |]

-- | List of nodes.
pNodeNames :: Field
pNodeNames =
  defaultField [| [] |] $ simpleField "node_names" [t| [NonEmptyString] |]

-- | A required node group name (for single-group LUs).
pGroupName :: Field
pGroupName = simpleField "group_name" [t| NonEmptyString |]

-- | Migration type (live\/non-live).
pMigrationMode :: Field
pMigrationMode =
  renameField "MigrationMode" .
  optionalField $
  simpleField "mode" [t| MigrationMode |]

-- | Obsolete \'live\' migration mode (boolean).
pMigrationLive :: Field
pMigrationLive =
  renameField "OldLiveMode" . optionalField $ booleanField "live"

-- | Whether to force an unknown OS variant.
pForceVariant :: Field
pForceVariant = defaultFalse "force_variant"

-- | Whether to wait for the disk to synchronize.
pWaitForSync :: Field
pWaitForSync = defaultTrue "wait_for_sync"

-- | Whether to wait for the disk to synchronize (defaults to false).
pWaitForSyncFalse :: Field
pWaitForSyncFalse = defaultField [| False |] pWaitForSync

-- | Whether to ignore disk consistency
pIgnoreConsistency :: Field
pIgnoreConsistency = defaultFalse "ignore_consistency"

-- | Storage name.
pStorageName :: Field
pStorageName =
  renameField "StorageName" $ simpleField "name" [t| NonEmptyString |]

-- | Whether to use synchronization.
pUseLocking :: Field
pUseLocking = defaultFalse "use_locking"

-- | Whether to check name.
pNameCheck :: Field
pNameCheck = defaultTrue "name_check"

-- | Instance allocation policy.
pNodeGroupAllocPolicy :: Field
pNodeGroupAllocPolicy = optionalField $
                        simpleField "alloc_policy" [t| AllocPolicy |]

-- | Default node parameters for group.
pGroupNodeParams :: Field
pGroupNodeParams = optionalField $ simpleField "ndparams" [t| UncheckedDict |]

-- | Resource(s) to query for.
pQueryWhat :: Field
pQueryWhat = simpleField "what" [t| Qlang.QueryTypeOp |]

-- | Whether to release locks as soon as possible.
pEarlyRelease :: Field
pEarlyRelease = defaultFalse "early_release"

-- | Whether to ensure instance's IP address is inactive.
pIpCheck :: Field
pIpCheck = defaultTrue "ip_check"

-- | Check for conflicting IPs.
pIpConflictsCheck :: Field
pIpConflictsCheck = defaultTrue "conflicts_check"

-- | Do not remember instance state changes.
pNoRemember :: Field
pNoRemember = defaultFalse "no_remember"

-- | Target node for instance migration/failover.
pMigrationTargetNode :: Field
pMigrationTargetNode = optionalNEStringField "target_node"

-- | Target node for instance move (required).
pMoveTargetNode :: Field
pMoveTargetNode =
  renameField "MoveTargetNode" $
  simpleField "target_node" [t| NonEmptyString |]

-- | Pause instance at startup.
pStartupPaused :: Field
pStartupPaused = defaultFalse "startup_paused"

-- | Verbose mode.
pVerbose :: Field
pVerbose = defaultFalse "verbose"

-- ** Parameters for cluster verification

-- | Whether to simulate errors (useful for debugging).
pDebugSimulateErrors :: Field
pDebugSimulateErrors = defaultFalse "debug_simulate_errors"

-- | Error codes.
pErrorCodes :: Field
pErrorCodes = defaultFalse "error_codes"

-- | Which checks to skip.
pSkipChecks :: Field
pSkipChecks = defaultField [| Set.empty |] $
              simpleField "skip_checks" [t| Set.Set VerifyOptionalChecks |]

-- | List of error codes that should be treated as warnings.
pIgnoreErrors :: Field
pIgnoreErrors = defaultField [| Set.empty |] $
                simpleField "ignore_errors" [t| Set.Set CVErrorCode |]

-- | Optional group name.
pOptGroupName :: Field
pOptGroupName = renameField "OptGroupName" .
                optionalField $ simpleField "group_name" [t| NonEmptyString |]

-- | Disk templates' parameter defaults.
pDiskParams :: Field
pDiskParams = optionalField $
              simpleField "diskparams" [t| GenericContainer DiskTemplate
                                           UncheckedDict |]

-- * Parameters for node resource model

-- | Set hypervisor states.
pHvState :: Field
pHvState = optionalField $ simpleField "hv_state" [t| UncheckedDict |]

-- | Set disk states.
pDiskState :: Field
pDiskState = optionalField $ simpleField "disk_state" [t| UncheckedDict |]

-- | Whether to ignore ipolicy violations.
pIgnoreIpolicy :: Field
pIgnoreIpolicy = defaultFalse "ignore_ipolicy"

-- | Allow runtime changes while migrating.
pAllowRuntimeChgs :: Field
pAllowRuntimeChgs = defaultTrue "allow_runtime_changes"

-- | Utility type for OpClusterSetParams.
type TestClusterOsListItem = (DdmSimple, NonEmptyString)

-- | Utility type of OsList.
type TestClusterOsList = [TestClusterOsListItem]

-- Utility type for NIC definitions.
--type TestNicDef = INicParams

-- | List of instance disks.
pInstDisks :: Field
pInstDisks = renameField "instDisks" $ simpleField "disks" [t| [IDiskParams] |]

-- | Instance disk template.
pDiskTemplate :: Field
pDiskTemplate = simpleField "disk_template" [t| DiskTemplate |]

-- | File driver.
pFileDriver :: Field
pFileDriver = optionalField $ simpleField "file_driver" [t| FileDriver |]

-- | Directory for storing file-backed disks.
pFileStorageDir :: Field
pFileStorageDir = optionalNEStringField "file_storage_dir"

-- | Volume group name.
pVgName :: Field
pVgName = optionalStringField "vg_name"

-- | List of enabled hypervisors.
pEnabledHypervisors :: Field
pEnabledHypervisors =
  optionalField $
  simpleField "enabled_hypervisors" [t| NonEmpty Hypervisor |]

-- | Selected hypervisor for an instance.
pHypervisor :: Field
pHypervisor =
  optionalField $
  simpleField "hypervisor" [t| Hypervisor |]

-- | Cluster-wide hypervisor parameters, hypervisor-dependent.
pClusterHvParams :: Field
pClusterHvParams =
  renameField "ClusterHvParams" .
  optionalField $
  simpleField "hvparams" [t| Container UncheckedDict |]

-- | Instance hypervisor parameters.
pInstHvParams :: Field
pInstHvParams =
  renameField "InstHvParams" .
  defaultField [| toJSObject [] |] $
  simpleField "hvparams" [t| UncheckedDict |]

-- | Cluster-wide beparams.
pClusterBeParams :: Field
pClusterBeParams =
  renameField "ClusterBeParams" .
  optionalField $ simpleField "beparams" [t| UncheckedDict |]

-- | Instance beparams.
pInstBeParams :: Field
pInstBeParams =
  renameField "InstBeParams" .
  defaultField [| toJSObject [] |] $
  simpleField "beparams" [t| UncheckedDict |]

-- | Reset instance parameters to default if equal.
pResetDefaults :: Field
pResetDefaults = defaultFalse "identify_defaults"

-- | Cluster-wide per-OS hypervisor parameter defaults.
pOsHvp :: Field
pOsHvp = optionalField $ simpleField "os_hvp" [t| Container UncheckedDict |]

-- | Cluster-wide OS parameter defaults.
pClusterOsParams :: Field
pClusterOsParams =
  renameField "ClusterOsParams" .
  optionalField $ simpleField "osparams" [t| Container UncheckedDict |]

-- | Instance OS parameters.
pInstOsParams :: Field
pInstOsParams =
  renameField "InstOsParams" . defaultField [| toJSObject [] |] $
  simpleField "osparams" [t| UncheckedDict |]

-- | Temporary OS parameters (currently only in reinstall, might be
-- added to install as well).
pTempOsParams :: Field
pTempOsParams =
  renameField "TempOsParams" .
  optionalField $ simpleField "osparams" [t| UncheckedDict |]

-- | Temporary hypervisor parameters, hypervisor-dependent.
pTempHvParams :: Field
pTempHvParams =
  renameField "TempHvParams" .
  defaultField [| toJSObject [] |] $
  simpleField "hvparams" [t| UncheckedDict |]

-- | Temporary backend parameters.
pTempBeParams :: Field
pTempBeParams =
  renameField "TempBeParams" .
  defaultField [| toJSObject [] |] $
  simpleField "beparams" [t| UncheckedDict |]

-- | Candidate pool size.
pCandidatePoolSize :: Field
pCandidatePoolSize =
  optionalField $ simpleField "candidate_pool_size" [t| Positive Int |]

-- | Set UID pool, must be list of lists describing UID ranges (two
-- items, start and end inclusive.
pUidPool :: Field
pUidPool = optionalField $ simpleField "uid_pool" [t| [[(Int, Int)]] |]

-- | Extend UID pool, must be list of lists describing UID ranges (two
-- items, start and end inclusive.
pAddUids :: Field
pAddUids = optionalField $ simpleField "add_uids" [t| [[(Int, Int)]] |]

-- | Shrink UID pool, must be list of lists describing UID ranges (two
-- items, start and end inclusive) to be removed.
pRemoveUids :: Field
pRemoveUids = optionalField $ simpleField "remove_uids" [t| [[(Int, Int)]] |]

-- | Whether to automatically maintain node health.
pMaintainNodeHealth :: Field
pMaintainNodeHealth = optionalField $ booleanField "maintain_node_health"

-- | Whether to wipe disks before allocating them to instances.
pPreallocWipeDisks :: Field
pPreallocWipeDisks = optionalField $ booleanField "prealloc_wipe_disks"

-- | Cluster-wide NIC parameter defaults.
pNicParams :: Field
pNicParams = optionalField $ simpleField "nicparams" [t| INicParams |]

-- | Instance NIC definitions.
pInstNics :: Field
pInstNics = simpleField "nics" [t| [INicParams] |]

-- | Cluster-wide node parameter defaults.
pNdParams :: Field
pNdParams = optionalField $ simpleField "ndparams" [t| UncheckedDict |]

-- | Cluster-wipe ipolict specs.
pIpolicy :: Field
pIpolicy = optionalField $ simpleField "ipolicy" [t| UncheckedDict |]

-- | DRBD helper program.
pDrbdHelper :: Field
pDrbdHelper = optionalStringField "drbd_helper"

-- | Default iallocator for cluster.
pDefaultIAllocator :: Field
pDefaultIAllocator = optionalStringField "default_iallocator"

-- | Master network device.
pMasterNetdev :: Field
pMasterNetdev = optionalStringField "master_netdev"

-- | Netmask of the master IP.
pMasterNetmask :: Field
pMasterNetmask = optionalField $ simpleField "master_netmask" [t| Int |]

-- | List of reserved LVs.
pReservedLvs :: Field
pReservedLvs =
  optionalField $ simpleField "reserved_lvs" [t| [NonEmptyString] |]

-- | Modify list of hidden operating systems: each modification must
-- have two items, the operation and the OS name; the operation can be
-- add or remove.
pHiddenOs :: Field
pHiddenOs = optionalField $ simpleField "hidden_os" [t| TestClusterOsList |]

-- | Modify list of blacklisted operating systems: each modification
-- must have two items, the operation and the OS name; the operation
-- can be add or remove.
pBlacklistedOs :: Field
pBlacklistedOs =
  optionalField $ simpleField "blacklisted_os" [t| TestClusterOsList |]

-- | Whether to use an external master IP address setup script.
pUseExternalMipScript :: Field
pUseExternalMipScript = optionalField $ booleanField "use_external_mip_script"

-- | Requested fields.
pQueryFields :: Field
pQueryFields = simpleField "fields" [t| [NonEmptyString] |]

-- | Query filter.
pQueryFilter :: Field
pQueryFilter = simpleField "qfilter" [t| Qlang.Filter String |]

-- | OOB command to run.
pOobCommand :: Field
pOobCommand = simpleField "command" [t| OobCommand |]

-- | Timeout before the OOB helper will be terminated.
pOobTimeout :: Field
pOobTimeout =
  defaultField [| C.oobTimeout |] $ simpleField "timeout" [t| Int |]

-- | Ignores the node offline status for power off.
pIgnoreStatus :: Field
pIgnoreStatus = defaultFalse "ignore_status"

-- | Time in seconds to wait between powering on nodes.
pPowerDelay :: Field
pPowerDelay =
  -- FIXME: we can't use the proper type "NonNegative Double", since
  -- the default constant is a plain Double, not a non-negative one.
  defaultField [| C.oobPowerDelay |] $
  simpleField "power_delay" [t| Double |]

-- | Primary IP address.
pPrimaryIp :: Field
pPrimaryIp = optionalStringField "primary_ip"

-- | Secondary IP address.
pSecondaryIp :: Field
pSecondaryIp = optionalNEStringField "secondary_ip"

-- | Whether node is re-added to cluster.
pReadd :: Field
pReadd = defaultFalse "readd"

-- | Initial node group.
pNodeGroup :: Field
pNodeGroup = optionalNEStringField "group"

-- | Whether node can become master or master candidate.
pMasterCapable :: Field
pMasterCapable = optionalField $ booleanField "master_capable"

-- | Whether node can host instances.
pVmCapable :: Field
pVmCapable = optionalField $ booleanField "vm_capable"

-- | List of names.
pNames :: Field
pNames = defaultField [| [] |] $ simpleField "names" [t| [NonEmptyString] |]

-- | List of node names.
pNodes :: Field
pNodes = defaultField [| [] |] $ simpleField "nodes" [t| [NonEmptyString] |]

-- | Storage type.
pStorageType :: Field
pStorageType = simpleField "storage_type" [t| StorageType |]

-- | Storage changes (unchecked).
pStorageChanges :: Field
pStorageChanges = simpleField "changes" [t| UncheckedDict |]

-- | Whether the node should become a master candidate.
pMasterCandidate :: Field
pMasterCandidate = optionalField $ booleanField "master_candidate"

-- | Whether the node should be marked as offline.
pOffline :: Field
pOffline = optionalField $ booleanField "offline"

-- | Whether the node should be marked as drained.
pDrained ::Field
pDrained = optionalField $ booleanField "drained"

-- | Whether node(s) should be promoted to master candidate if necessary.
pAutoPromote :: Field
pAutoPromote = defaultFalse "auto_promote"

-- | Whether the node should be marked as powered
pPowered :: Field
pPowered = optionalField $ booleanField "powered"

-- | Iallocator for deciding the target node for shared-storage
-- instances during migrate and failover.
pIallocator :: Field
pIallocator = optionalNEStringField "iallocator"

-- | New secondary node.
pRemoteNode :: Field
pRemoteNode = optionalNEStringField "remote_node"

-- | Node evacuation mode.
pEvacMode :: Field
pEvacMode = renameField "EvacMode" $ simpleField "mode" [t| NodeEvacMode |]

-- | Instance creation mode.
pInstCreateMode :: Field
pInstCreateMode =
  renameField "InstCreateMode" $ simpleField "mode" [t| InstCreateMode |]

-- | Do not install the OS (will disable automatic start).
pNoInstall :: Field
pNoInstall = optionalField $ booleanField "no_install"

-- | OS type for instance installation.
pInstOs :: Field
pInstOs = optionalNEStringField "os_type"

-- | Primary node for an instance.
pPrimaryNode :: Field
pPrimaryNode = optionalNEStringField "pnode"

-- | Secondary node for an instance.
pSecondaryNode :: Field
pSecondaryNode = optionalNEStringField "snode"

-- | Signed handshake from source (remote import only).
pSourceHandshake :: Field
pSourceHandshake =
  optionalField $ simpleField "source_handshake" [t| UncheckedList |]

-- | Source instance name (remote import only).
pSourceInstance :: Field
pSourceInstance = optionalNEStringField "source_instance_name"

-- | How long source instance was given to shut down (remote import only).
-- FIXME: non-negative int, whereas the constant is a plain int.
pSourceShutdownTimeout :: Field
pSourceShutdownTimeout =
  defaultField [| forceNonNeg C.defaultShutdownTimeout |] $
  simpleField "source_shutdown_timeout" [t| NonNegative Int |]

-- | Source X509 CA in PEM format (remote import only).
pSourceX509Ca :: Field
pSourceX509Ca = optionalNEStringField "source_x509_ca"

-- | Source node for import.
pSrcNode :: Field
pSrcNode = optionalNEStringField "src_node"

-- | Source directory for import.
pSrcPath :: Field
pSrcPath = optionalNEStringField "src_path"

-- | Whether to start instance after creation.
pStartInstance :: Field
pStartInstance = defaultTrue "start"

-- | Instance tags. FIXME: unify/simplify with pTags, once that
-- migrates to NonEmpty String.
pInstTags :: Field
pInstTags =
  renameField "InstTags" .
  defaultField [| [] |] $
  simpleField "tags" [t| [NonEmptyString] |]

-- | Unchecked list of OpInstanceCreate, used in OpInstanceMultiAlloc.
pMultiAllocInstances :: Field
pMultiAllocInstances =
  renameField "InstMultiAlloc" .
  defaultField [| [] |] $
  simpleField "instances"[t| UncheckedList |]

-- | Ignore failures parameter.
pIgnoreFailures :: Field
pIgnoreFailures = defaultFalse "ignore_failures"

-- | New instance or cluster name.
pNewName :: Field
pNewName = simpleField "new_name" [t| NonEmptyString |]

-- | Whether to start the instance even if secondary disks are failing.
pIgnoreSecondaries :: Field
pIgnoreSecondaries = defaultFalse "ignore_secondaries"

-- | How to reboot the instance.
pRebootType :: Field
pRebootType = simpleField "reboot_type" [t| RebootType |]

-- | Whether to ignore recorded disk size.
pIgnoreDiskSize :: Field
pIgnoreDiskSize = defaultFalse "ignore_size"

-- | Disk list for recreate disks.
pRecreateDisksInfo :: Field
pRecreateDisksInfo =
  renameField "RecreateDisksInfo" .
  defaultField [| RecreateDisksAll |] $
  simpleField "disks" [t| RecreateDisksInfo |]

-- | Whether to only return configuration data without querying nodes.
pStatic :: Field
pStatic = defaultFalse "static"

-- | InstanceSetParams NIC changes.
pInstParamsNicChanges :: Field
pInstParamsNicChanges =
  renameField "InstNicChanges" .
  defaultField [| SetParamsEmpty |] $
  simpleField "nics" [t| SetParamsMods INicParams |]

-- | InstanceSetParams Disk changes.
pInstParamsDiskChanges :: Field
pInstParamsDiskChanges =
  renameField "InstDiskChanges" .
  defaultField [| SetParamsEmpty |] $
  simpleField "disks" [t| SetParamsMods IDiskParams |]

-- | New runtime memory.
pRuntimeMem :: Field
pRuntimeMem = optionalField $ simpleField "runtime_mem" [t| Positive Int |]

-- | Change the instance's OS without reinstalling the instance
pOsNameChange :: Field
pOsNameChange = optionalNEStringField "os_name"

-- | Disk index for e.g. grow disk.
pDiskIndex :: Field
pDiskIndex = renameField "DiskIndex " $ simpleField "disk" [t| DiskIndex |]

-- | Disk amount to add or grow to.
pDiskChgAmount :: Field
pDiskChgAmount =
  renameField "DiskChgAmount" $ simpleField "amount" [t| NonNegative Int |]

-- | Whether the amount parameter is an absolute target or a relative one.
pDiskChgAbsolute :: Field
pDiskChgAbsolute = renameField "DiskChkAbsolute" $ defaultFalse "absolute"

-- | Destination group names or UUIDs (defaults to \"all but current group\".
pTargetGroups :: Field
pTargetGroups =
  optionalField $ simpleField "target_groups" [t| [NonEmptyString] |]
