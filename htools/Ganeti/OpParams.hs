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
  , INicParams(..)
  , IDiskParams(..)
  , pInstanceName
  , pInstances
  , pName
  , pTagsList
  , pTagsObject
  , pOutputFields
  , pShutdownTimeout
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
  , pNoRemember
  , pMigrationTargetNode
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
  , pVgName
  , pEnabledHypervisors
  , pClusterHvParams
  , pClusterBeParams
  , pOsHvp
  , pOsParams
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
  ) where

import qualified Data.Set as Set
import Text.JSON (readJSON, showJSON, JSON, JSValue(..), fromJSString,
                  JSObject)
import Text.JSON.Pretty (pp_value)

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

-- | Disk modification definition.
$(buildObject "IDiskParams" "idisk"
  [ simpleField C.idiskSize   [t| Int            |] -- FIXME: VTYPE_UNIT
  , simpleField C.idiskMode   [t| DiskAccess     |]
  , simpleField C.idiskAdopt  [t| NonEmptyString |]
  , simpleField C.idiskVg     [t| NonEmptyString |]
  , simpleField C.idiskMetavg [t| NonEmptyString |]
  ])

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
pShutdownTimeout = defaultField [| C.defaultShutdownTimeout |] $
                   simpleField "shutdown_timeout" [t| NonNegative Int |]

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
  renameField "MigrationMode" $
  optionalField $
  simpleField "mode" [t| MigrationMode |]

-- | Obsolete \'live\' migration mode (boolean).
pMigrationLive :: Field
pMigrationLive =
  renameField "OldLiveMode" $ optionalField $ booleanField "live"

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

-- _PIpCheckDoc = "Whether to ensure instance's IP address is inactive"

-- | Do not remember instance state changes.
pNoRemember :: Field
pNoRemember = defaultFalse "no_remember"

-- | Target node for instance migration/failover.
pMigrationTargetNode :: Field
pMigrationTargetNode = optionalNEStringField "target_node"

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
pOptGroupName = renameField "OptGroupName" $
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
--type TDiskParams = IDiskParams

-- | Volume group name.
pVgName :: Field
pVgName = optionalStringField "vg_name"

-- | List of enabled hypervisors.
pEnabledHypervisors :: Field
pEnabledHypervisors =
  optionalField $
  simpleField "enabled_hypervisors" [t| NonEmpty Hypervisor |]

-- | Cluster-wide hypervisor parameters, hypervisor-dependent.
pClusterHvParams :: Field
pClusterHvParams =
  optionalField $
  simpleField "hvparams" [t| Container UncheckedDict |]

-- | Cluster-wide beparams.
pClusterBeParams :: Field
pClusterBeParams = optionalField $ simpleField "beparams" [t| UncheckedDict |]

-- | Cluster-wide per-OS hypervisor parameter defaults.
pOsHvp :: Field
pOsHvp = optionalField $ simpleField "os_hvp" [t| Container UncheckedDict |]

-- | Cluster-wide OS parameter defaults.
pOsParams :: Field
pOsParams =
  optionalField $ simpleField "osparams" [t| Container UncheckedDict |]

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
