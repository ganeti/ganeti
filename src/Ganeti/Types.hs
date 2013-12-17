{-# LANGUAGE TemplateHaskell #-}

{-| Some common Ganeti types.

This holds types common to both core work, and to htools. Types that
are very core specific (e.g. configuration objects) should go in
'Ganeti.Objects', while types that are specific to htools in-memory
representation should go into 'Ganeti.HTools.Types'.

-}

{-

Copyright (C) 2012, 2013 Google Inc.

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

module Ganeti.Types
  ( AllocPolicy(..)
  , allocPolicyFromRaw
  , allocPolicyToRaw
  , InstanceStatus(..)
  , instanceStatusFromRaw
  , instanceStatusToRaw
  , DiskTemplate(..)
  , diskTemplateToRaw
  , diskTemplateFromRaw
  , TagKind(..)
  , tagKindToRaw
  , tagKindFromRaw
  , NonNegative
  , fromNonNegative
  , mkNonNegative
  , Positive
  , fromPositive
  , mkPositive
  , Negative
  , fromNegative
  , mkNegative
  , NonEmpty
  , fromNonEmpty
  , mkNonEmpty
  , NonEmptyString
  , QueryResultCode
  , IPv4Address
  , mkIPv4Address
  , IPv4Network
  , mkIPv4Network
  , IPv6Address
  , mkIPv6Address
  , IPv6Network
  , mkIPv6Network
  , MigrationMode(..)
  , migrationModeToRaw
  , VerifyOptionalChecks(..)
  , verifyOptionalChecksToRaw
  , DdmSimple(..)
  , DdmFull(..)
  , ddmFullToRaw
  , CVErrorCode(..)
  , cVErrorCodeToRaw
  , Hypervisor(..)
  , hypervisorToRaw
  , OobCommand(..)
  , oobCommandToRaw
  , OobStatus(..)
  , oobStatusToRaw
  , StorageType(..)
  , storageTypeToRaw
  , EvacMode(..)
  , evacModeToRaw
  , FileDriver(..)
  , fileDriverToRaw
  , InstCreateMode(..)
  , instCreateModeToRaw
  , RebootType(..)
  , rebootTypeToRaw
  , ExportMode(..)
  , exportModeToRaw
  , IAllocatorTestDir(..)
  , iAllocatorTestDirToRaw
  , IAllocatorMode(..)
  , iAllocatorModeToRaw
  , NICMode(..)
  , nICModeToRaw
  , JobStatus(..)
  , jobStatusToRaw
  , jobStatusFromRaw
  , FinalizedJobStatus(..)
  , finalizedJobStatusToRaw
  , JobId
  , fromJobId
  , makeJobId
  , makeJobIdS
  , RelativeJobId
  , JobIdDep(..)
  , JobDependency(..)
  , absoluteJobDependency
  , OpSubmitPriority(..)
  , opSubmitPriorityToRaw
  , parseSubmitPriority
  , fmtSubmitPriority
  , OpStatus(..)
  , opStatusToRaw
  , opStatusFromRaw
  , ELogType(..)
  , eLogTypeToRaw
  , ReasonElem
  , ReasonTrail
  , StorageUnit(..)
  , StorageUnitRaw(..)
  , StorageKey
  , addParamsToStorageUnit
  , diskTemplateToStorageType
  , VType(..)
  , vTypeFromRaw
  , vTypeToRaw
  , NodeRole(..)
  , nodeRoleToRaw
  , roleDescription
  , DiskMode(..)
  , diskModeToRaw
  , BlockDriver(..)
  , blockDriverToRaw
  , AdminState(..)
  , adminStateFromRaw
  , adminStateToRaw
  , StorageField(..)
  , storageFieldToRaw
  , DiskAccessMode(..)
  , diskAccessModeToRaw
  , LocalDiskStatus(..)
  , localDiskStatusFromRaw
  , localDiskStatusToRaw
  , localDiskStatusName
  , ReplaceDisksMode(..)
  , replaceDisksModeToRaw
  , RpcTimeout(..)
  , rpcTimeoutFromRaw -- FIXME: no used anywhere
  , rpcTimeoutToRaw
  , ImportExportCompression(..)
  , importExportCompressionToRaw
  , HotplugTarget(..)
  , hotplugTargetToRaw
  , HotplugAction(..)
  , hotplugActionToRaw
  ) where

import Control.Monad (liftM)
import qualified Text.JSON as JSON
import Text.JSON (JSON, readJSON, showJSON)
import Data.Ratio (numerator, denominator)

import qualified Ganeti.ConstantUtils as ConstantUtils
import Ganeti.JSON
import qualified Ganeti.THH as THH
import Ganeti.Utils

-- * Generic types

-- | Type that holds a non-negative value.
newtype NonNegative a = NonNegative { fromNonNegative :: a }
  deriving (Show, Eq)

-- | Smart constructor for 'NonNegative'.
mkNonNegative :: (Monad m, Num a, Ord a, Show a) => a -> m (NonNegative a)
mkNonNegative i | i >= 0 = return (NonNegative i)
                | otherwise = fail $ "Invalid value for non-negative type '" ++
                              show i ++ "'"

instance (JSON.JSON a, Num a, Ord a, Show a) => JSON.JSON (NonNegative a) where
  showJSON = JSON.showJSON . fromNonNegative
  readJSON v = JSON.readJSON v >>= mkNonNegative

-- | Type that holds a positive value.
newtype Positive a = Positive { fromPositive :: a }
  deriving (Show, Eq)

-- | Smart constructor for 'Positive'.
mkPositive :: (Monad m, Num a, Ord a, Show a) => a -> m (Positive a)
mkPositive i | i > 0 = return (Positive i)
             | otherwise = fail $ "Invalid value for positive type '" ++
                           show i ++ "'"

instance (JSON.JSON a, Num a, Ord a, Show a) => JSON.JSON (Positive a) where
  showJSON = JSON.showJSON . fromPositive
  readJSON v = JSON.readJSON v >>= mkPositive

-- | Type that holds a negative value.
newtype Negative a = Negative { fromNegative :: a }
  deriving (Show, Eq)

-- | Smart constructor for 'Negative'.
mkNegative :: (Monad m, Num a, Ord a, Show a) => a -> m (Negative a)
mkNegative i | i < 0 = return (Negative i)
             | otherwise = fail $ "Invalid value for negative type '" ++
                           show i ++ "'"

instance (JSON.JSON a, Num a, Ord a, Show a) => JSON.JSON (Negative a) where
  showJSON = JSON.showJSON . fromNegative
  readJSON v = JSON.readJSON v >>= mkNegative

-- | Type that holds a non-null list.
newtype NonEmpty a = NonEmpty { fromNonEmpty :: [a] }
  deriving (Show, Eq)

-- | Smart constructor for 'NonEmpty'.
mkNonEmpty :: (Monad m) => [a] -> m (NonEmpty a)
mkNonEmpty [] = fail "Received empty value for non-empty list"
mkNonEmpty xs = return (NonEmpty xs)

instance (Eq a, Ord a) => Ord (NonEmpty a) where
  NonEmpty { fromNonEmpty = x1 } `compare` NonEmpty { fromNonEmpty = x2 } =
    x1 `compare` x2

instance (JSON.JSON a) => JSON.JSON (NonEmpty a) where
  showJSON = JSON.showJSON . fromNonEmpty
  readJSON v = JSON.readJSON v >>= mkNonEmpty

-- | A simple type alias for non-empty strings.
type NonEmptyString = NonEmpty Char

type QueryResultCode = Int

newtype IPv4Address = IPv4Address { fromIPv4Address :: String }
  deriving (Show, Eq)

-- FIXME: this should check that 'address' is a valid ip
mkIPv4Address :: Monad m => String -> m IPv4Address
mkIPv4Address address =
  return IPv4Address { fromIPv4Address = address }

instance JSON.JSON IPv4Address where
  showJSON = JSON.showJSON . fromIPv4Address
  readJSON v = JSON.readJSON v >>= mkIPv4Address

newtype IPv4Network = IPv4Network { fromIPv4Network :: String }
  deriving (Show, Eq)

-- FIXME: this should check that 'address' is a valid ip
mkIPv4Network :: Monad m => String -> m IPv4Network
mkIPv4Network address =
  return IPv4Network { fromIPv4Network = address }

instance JSON.JSON IPv4Network where
  showJSON = JSON.showJSON . fromIPv4Network
  readJSON v = JSON.readJSON v >>= mkIPv4Network

newtype IPv6Address = IPv6Address { fromIPv6Address :: String }
  deriving (Show, Eq)

-- FIXME: this should check that 'address' is a valid ip
mkIPv6Address :: Monad m => String -> m IPv6Address
mkIPv6Address address =
  return IPv6Address { fromIPv6Address = address }

instance JSON.JSON IPv6Address where
  showJSON = JSON.showJSON . fromIPv6Address
  readJSON v = JSON.readJSON v >>= mkIPv6Address

newtype IPv6Network = IPv6Network { fromIPv6Network :: String }
  deriving (Show, Eq)

-- FIXME: this should check that 'address' is a valid ip
mkIPv6Network :: Monad m => String -> m IPv6Network
mkIPv6Network address =
  return IPv6Network { fromIPv6Network = address }

instance JSON.JSON IPv6Network where
  showJSON = JSON.showJSON . fromIPv6Network
  readJSON v = JSON.readJSON v >>= mkIPv6Network

-- * Ganeti types

-- | Instance disk template type.
$(THH.declareLADT ''String "DiskTemplate"
       [ ("DTDiskless",   "diskless")
       , ("DTFile",       "file")
       , ("DTSharedFile", "sharedfile")
       , ("DTPlain",      "plain")
       , ("DTBlock",      "blockdev")
       , ("DTDrbd8",      "drbd")
       , ("DTRbd",        "rbd")
       , ("DTExt",        "ext")
       , ("DTGluster",    "gluster")
       ])
$(THH.makeJSONInstance ''DiskTemplate)

instance THH.PyValue DiskTemplate where
  showValue = show . diskTemplateToRaw

instance HasStringRepr DiskTemplate where
  fromStringRepr = diskTemplateFromRaw
  toStringRepr = diskTemplateToRaw

-- | Data type representing what items the tag operations apply to.
$(THH.declareLADT ''String "TagKind"
  [ ("TagKindInstance", "instance")
  , ("TagKindNode",     "node")
  , ("TagKindGroup",    "nodegroup")
  , ("TagKindCluster",  "cluster")
  , ("TagKindNetwork",  "network")
  ])
$(THH.makeJSONInstance ''TagKind)

-- | The Group allocation policy type.
--
-- Note that the order of constructors is important as the automatic
-- Ord instance will order them in the order they are defined, so when
-- changing this data type be careful about the interaction with the
-- desired sorting order.
$(THH.declareLADT ''String "AllocPolicy"
       [ ("AllocPreferred",   "preferred")
       , ("AllocLastResort",  "last_resort")
       , ("AllocUnallocable", "unallocable")
       ])
$(THH.makeJSONInstance ''AllocPolicy)

-- | The Instance real state type.
$(THH.declareLADT ''String "InstanceStatus"
       [ ("StatusDown",    "ADMIN_down")
       , ("StatusOffline", "ADMIN_offline")
       , ("ErrorDown",     "ERROR_down")
       , ("ErrorUp",       "ERROR_up")
       , ("NodeDown",      "ERROR_nodedown")
       , ("NodeOffline",   "ERROR_nodeoffline")
       , ("Running",       "running")
       , ("UserDown",      "USER_down")
       , ("WrongNode",     "ERROR_wrongnode")
       ])
$(THH.makeJSONInstance ''InstanceStatus)

-- | Migration mode.
$(THH.declareLADT ''String "MigrationMode"
     [ ("MigrationLive",    "live")
     , ("MigrationNonLive", "non-live")
     ])
$(THH.makeJSONInstance ''MigrationMode)

-- | Verify optional checks.
$(THH.declareLADT ''String "VerifyOptionalChecks"
     [ ("VerifyNPlusOneMem", "nplusone_mem")
     ])
$(THH.makeJSONInstance ''VerifyOptionalChecks)

-- | Cluster verify error codes.
$(THH.declareLADT ''String "CVErrorCode"
  [ ("CvECLUSTERCFG",                  "ECLUSTERCFG")
  , ("CvECLUSTERCERT",                 "ECLUSTERCERT")
  , ("CvECLUSTERFILECHECK",            "ECLUSTERFILECHECK")
  , ("CvECLUSTERDANGLINGNODES",        "ECLUSTERDANGLINGNODES")
  , ("CvECLUSTERDANGLINGINST",         "ECLUSTERDANGLINGINST")
  , ("CvEINSTANCEBADNODE",             "EINSTANCEBADNODE")
  , ("CvEINSTANCEDOWN",                "EINSTANCEDOWN")
  , ("CvEINSTANCELAYOUT",              "EINSTANCELAYOUT")
  , ("CvEINSTANCEMISSINGDISK",         "EINSTANCEMISSINGDISK")
  , ("CvEINSTANCEFAULTYDISK",          "EINSTANCEFAULTYDISK")
  , ("CvEINSTANCEWRONGNODE",           "EINSTANCEWRONGNODE")
  , ("CvEINSTANCESPLITGROUPS",         "EINSTANCESPLITGROUPS")
  , ("CvEINSTANCEPOLICY",              "EINSTANCEPOLICY")
  , ("CvEINSTANCEUNSUITABLENODE",      "EINSTANCEUNSUITABLENODE")
  , ("CvEINSTANCEMISSINGCFGPARAMETER", "EINSTANCEMISSINGCFGPARAMETER")
  , ("CvENODEDRBD",                    "ENODEDRBD")
  , ("CvENODEDRBDVERSION",             "ENODEDRBDVERSION")
  , ("CvENODEDRBDHELPER",              "ENODEDRBDHELPER")
  , ("CvENODEFILECHECK",               "ENODEFILECHECK")
  , ("CvENODEHOOKS",                   "ENODEHOOKS")
  , ("CvENODEHV",                      "ENODEHV")
  , ("CvENODELVM",                     "ENODELVM")
  , ("CvENODEN1",                      "ENODEN1")
  , ("CvENODENET",                     "ENODENET")
  , ("CvENODEOS",                      "ENODEOS")
  , ("CvENODEORPHANINSTANCE",          "ENODEORPHANINSTANCE")
  , ("CvENODEORPHANLV",                "ENODEORPHANLV")
  , ("CvENODERPC",                     "ENODERPC")
  , ("CvENODESSH",                     "ENODESSH")
  , ("CvENODEVERSION",                 "ENODEVERSION")
  , ("CvENODESETUP",                   "ENODESETUP")
  , ("CvENODETIME",                    "ENODETIME")
  , ("CvENODEOOBPATH",                 "ENODEOOBPATH")
  , ("CvENODEUSERSCRIPTS",             "ENODEUSERSCRIPTS")
  , ("CvENODEFILESTORAGEPATHS",        "ENODEFILESTORAGEPATHS")
  , ("CvENODEFILESTORAGEPATHUNUSABLE", "ENODEFILESTORAGEPATHUNUSABLE")
  , ("CvENODESHAREDFILESTORAGEPATHUNUSABLE",
     "ENODESHAREDFILESTORAGEPATHUNUSABLE")
  , ("CvEGROUPDIFFERENTPVSIZE",        "EGROUPDIFFERENTPVSIZE")
  ])
$(THH.makeJSONInstance ''CVErrorCode)

-- | Dynamic device modification, just add\/remove version.
$(THH.declareLADT ''String "DdmSimple"
     [ ("DdmSimpleAdd",    "add")
     , ("DdmSimpleRemove", "remove")
     ])
$(THH.makeJSONInstance ''DdmSimple)

-- | Dynamic device modification, all operations version.
--
-- TODO: DDM_SWAP, DDM_MOVE?
$(THH.declareLADT ''String "DdmFull"
     [ ("DdmFullAdd",    "add")
     , ("DdmFullRemove", "remove")
     , ("DdmFullModify", "modify")
     ])
$(THH.makeJSONInstance ''DdmFull)

-- | Hypervisor type definitions.
$(THH.declareLADT ''String "Hypervisor"
  [ ("Kvm",    "kvm")
  , ("XenPvm", "xen-pvm")
  , ("Chroot", "chroot")
  , ("XenHvm", "xen-hvm")
  , ("Lxc",    "lxc")
  , ("Fake",   "fake")
  ])
$(THH.makeJSONInstance ''Hypervisor)

instance THH.PyValue Hypervisor where
  showValue = show . hypervisorToRaw

instance HasStringRepr Hypervisor where
  fromStringRepr = hypervisorFromRaw
  toStringRepr = hypervisorToRaw

-- | Oob command type.
$(THH.declareLADT ''String "OobCommand"
  [ ("OobHealth",      "health")
  , ("OobPowerCycle",  "power-cycle")
  , ("OobPowerOff",    "power-off")
  , ("OobPowerOn",     "power-on")
  , ("OobPowerStatus", "power-status")
  ])
$(THH.makeJSONInstance ''OobCommand)

-- | Oob command status
$(THH.declareLADT ''String "OobStatus"
  [ ("OobStatusCritical", "CRITICAL")
  , ("OobStatusOk",       "OK")
  , ("OobStatusUnknown",  "UNKNOWN")
  , ("OobStatusWarning",  "WARNING")
  ])
$(THH.makeJSONInstance ''OobStatus)

-- | Storage type.
$(THH.declareLADT ''String "StorageType"
  [ ("StorageFile", "file")
  , ("StorageSharedFile", "sharedfile")
  , ("StorageLvmPv", "lvm-pv")
  , ("StorageLvmVg", "lvm-vg")
  , ("StorageDiskless", "diskless")
  , ("StorageBlock", "blockdev")
  , ("StorageRados", "rados")
  , ("StorageExt", "ext")
  ])
$(THH.makeJSONInstance ''StorageType)

-- | Storage keys are identifiers for storage units. Their content varies
-- depending on the storage type, for example a storage key for LVM storage
-- is the volume group name.
type StorageKey = String

-- | Storage parameters
type SPExclusiveStorage = Bool

-- | Storage units without storage-type-specific parameters
data StorageUnitRaw = SURaw StorageType StorageKey

-- | Full storage unit with storage-type-specific parameters
data StorageUnit = SUFile StorageKey
                 | SUSharedFile StorageKey
                 | SULvmPv StorageKey SPExclusiveStorage
                 | SULvmVg StorageKey SPExclusiveStorage
                 | SUDiskless StorageKey
                 | SUBlock StorageKey
                 | SURados StorageKey
                 | SUExt StorageKey
                 deriving (Eq)

instance Show StorageUnit where
  show (SUFile key) = showSUSimple StorageFile key
  show (SUSharedFile key) = showSUSimple StorageSharedFile key
  show (SULvmPv key es) = showSULvm StorageLvmPv key es
  show (SULvmVg key es) = showSULvm StorageLvmVg key es
  show (SUDiskless key) = showSUSimple StorageDiskless key
  show (SUBlock key) = showSUSimple StorageBlock key
  show (SURados key) = showSUSimple StorageRados key
  show (SUExt key) = showSUSimple StorageExt key

instance JSON StorageUnit where
  showJSON (SUFile key) = showJSON (StorageFile, key, []::[String])
  showJSON (SUSharedFile key) = showJSON (StorageSharedFile, key, []::[String])
  showJSON (SULvmPv key es) = showJSON (StorageLvmPv, key, [es])
  showJSON (SULvmVg key es) = showJSON (StorageLvmVg, key, [es])
  showJSON (SUDiskless key) = showJSON (StorageDiskless, key, []::[String])
  showJSON (SUBlock key) = showJSON (StorageBlock, key, []::[String])
  showJSON (SURados key) = showJSON (StorageRados, key, []::[String])
  showJSON (SUExt key) = showJSON (StorageExt, key, []::[String])
-- FIXME: add readJSON implementation
  readJSON = fail "Not implemented"

-- | Composes a string representation of storage types without
-- storage parameters
showSUSimple :: StorageType -> StorageKey -> String
showSUSimple st sk = show (storageTypeToRaw st, sk, []::[String])

-- | Composes a string representation of the LVM storage types
showSULvm :: StorageType -> StorageKey -> SPExclusiveStorage -> String
showSULvm st sk es = show (storageTypeToRaw st, sk, [es])

-- | Mapping from disk templates to storage types
-- FIXME: This is semantically the same as the constant
-- C.diskTemplatesStorageType, remove this when python constants
-- are generated from haskell constants
diskTemplateToStorageType :: DiskTemplate -> StorageType
diskTemplateToStorageType DTExt = StorageExt
diskTemplateToStorageType DTFile = StorageFile
diskTemplateToStorageType DTSharedFile = StorageSharedFile
diskTemplateToStorageType DTDrbd8 = StorageLvmVg
diskTemplateToStorageType DTPlain = StorageLvmVg
diskTemplateToStorageType DTRbd = StorageRados
diskTemplateToStorageType DTDiskless = StorageDiskless
diskTemplateToStorageType DTBlock = StorageBlock
diskTemplateToStorageType DTGluster = StorageSharedFile

-- | Equips a raw storage unit with its parameters
addParamsToStorageUnit :: SPExclusiveStorage -> StorageUnitRaw -> StorageUnit
addParamsToStorageUnit _ (SURaw StorageBlock key) = SUBlock key
addParamsToStorageUnit _ (SURaw StorageDiskless key) = SUDiskless key
addParamsToStorageUnit _ (SURaw StorageExt key) = SUExt key
addParamsToStorageUnit _ (SURaw StorageFile key) = SUFile key
addParamsToStorageUnit _ (SURaw StorageSharedFile key) = SUSharedFile key
addParamsToStorageUnit es (SURaw StorageLvmPv key) = SULvmPv key es
addParamsToStorageUnit es (SURaw StorageLvmVg key) = SULvmVg key es
addParamsToStorageUnit _ (SURaw StorageRados key) = SURados key

-- | Node evac modes.
--
-- This is part of the 'IAllocator' interface and it is used, for
-- example, in 'Ganeti.HTools.Loader.RqType'.  However, it must reside
-- in this module, and not in 'Ganeti.HTools.Types', because it is
-- also used by 'Ganeti.Constants'.
$(THH.declareLADT ''String "EvacMode"
  [ ("ChangePrimary",   "primary-only")
  , ("ChangeSecondary", "secondary-only")
  , ("ChangeAll",       "all")
  ])
$(THH.makeJSONInstance ''EvacMode)

-- | The file driver type.
$(THH.declareLADT ''String "FileDriver"
  [ ("FileLoop",   "loop")
  , ("FileBlktap", "blktap")
  ])
$(THH.makeJSONInstance ''FileDriver)

-- | The instance create mode.
$(THH.declareLADT ''String "InstCreateMode"
  [ ("InstCreate",       "create")
  , ("InstImport",       "import")
  , ("InstRemoteImport", "remote-import")
  ])
$(THH.makeJSONInstance ''InstCreateMode)

-- | Reboot type.
$(THH.declareLADT ''String "RebootType"
  [ ("RebootSoft", "soft")
  , ("RebootHard", "hard")
  , ("RebootFull", "full")
  ])
$(THH.makeJSONInstance ''RebootType)

-- | Export modes.
$(THH.declareLADT ''String "ExportMode"
  [ ("ExportModeLocal",  "local")
  , ("ExportModeRemote", "remote")
  ])
$(THH.makeJSONInstance ''ExportMode)

-- | IAllocator run types (OpTestIAllocator).
$(THH.declareLADT ''String "IAllocatorTestDir"
  [ ("IAllocatorDirIn",  "in")
  , ("IAllocatorDirOut", "out")
  ])
$(THH.makeJSONInstance ''IAllocatorTestDir)

-- | IAllocator mode. FIXME: use this in "HTools.Backend.IAlloc".
$(THH.declareLADT ''String "IAllocatorMode"
  [ ("IAllocatorAlloc",       "allocate")
  , ("IAllocatorMultiAlloc",  "multi-allocate")
  , ("IAllocatorReloc",       "relocate")
  , ("IAllocatorNodeEvac",    "node-evacuate")
  , ("IAllocatorChangeGroup", "change-group")
  ])
$(THH.makeJSONInstance ''IAllocatorMode)

-- | Network mode.
$(THH.declareLADT ''String "NICMode"
  [ ("NMBridged", "bridged")
  , ("NMRouted",  "routed")
  , ("NMOvs",     "openvswitch")
  , ("NMPool",    "pool")
  ])
$(THH.makeJSONInstance ''NICMode)

-- | The JobStatus data type. Note that this is ordered especially
-- such that greater\/lesser comparison on values of this type makes
-- sense.
$(THH.declareLADT ''String "JobStatus"
  [ ("JOB_STATUS_QUEUED",    "queued")
  , ("JOB_STATUS_WAITING",   "waiting")
  , ("JOB_STATUS_CANCELING", "canceling")
  , ("JOB_STATUS_RUNNING",   "running")
  , ("JOB_STATUS_CANCELED",  "canceled")
  , ("JOB_STATUS_SUCCESS",   "success")
  , ("JOB_STATUS_ERROR",     "error")
  ])
$(THH.makeJSONInstance ''JobStatus)

-- | Finalized job status.
$(THH.declareLADT ''String "FinalizedJobStatus"
  [ ("JobStatusCanceled",   "canceled")
  , ("JobStatusSuccessful", "success")
  , ("JobStatusFailed",     "error")
  ])
$(THH.makeJSONInstance ''FinalizedJobStatus)

-- | The Ganeti job type.
newtype JobId = JobId { fromJobId :: Int }
  deriving (Show, Eq)

-- | Builds a job ID.
makeJobId :: (Monad m) => Int -> m JobId
makeJobId i | i >= 0 = return $ JobId i
            | otherwise = fail $ "Invalid value for job ID ' " ++ show i ++ "'"

-- | Builds a job ID from a string.
makeJobIdS :: (Monad m) => String -> m JobId
makeJobIdS s = tryRead "parsing job id" s >>= makeJobId

-- | Parses a job ID.
parseJobId :: (Monad m) => JSON.JSValue -> m JobId
parseJobId (JSON.JSString x) = makeJobIdS $ JSON.fromJSString x
parseJobId (JSON.JSRational _ x) =
  if denominator x /= 1
    then fail $ "Got fractional job ID from master daemon?! Value:" ++ show x
    -- FIXME: potential integer overflow here on 32-bit platforms
    else makeJobId . fromIntegral . numerator $ x
parseJobId x = fail $ "Wrong type/value for job id: " ++ show x

instance JSON.JSON JobId where
  showJSON = JSON.showJSON . fromJobId
  readJSON = parseJobId

-- | Relative job ID type alias.
type RelativeJobId = Negative Int

-- | Job ID dependency.
data JobIdDep = JobDepRelative RelativeJobId
              | JobDepAbsolute JobId
                deriving (Show, Eq)

instance JSON.JSON JobIdDep where
  showJSON (JobDepRelative i) = showJSON i
  showJSON (JobDepAbsolute i) = showJSON i
  readJSON v =
    case JSON.readJSON v::JSON.Result (Negative Int) of
      -- first try relative dependency, usually most common
      JSON.Ok r -> return $ JobDepRelative r
      JSON.Error _ -> liftM JobDepAbsolute (parseJobId v)

-- | From job ID dependency and job ID, compute the absolute dependency.
absoluteJobIdDep :: (Monad m) => JobIdDep -> JobId -> m JobIdDep
absoluteJobIdDep (JobDepAbsolute jid) _ = return $ JobDepAbsolute jid
absoluteJobIdDep (JobDepRelative rjid) jid =
  liftM JobDepAbsolute . makeJobId $ fromJobId jid + fromNegative rjid 

-- | Job Dependency type.
data JobDependency = JobDependency JobIdDep [FinalizedJobStatus]
                     deriving (Show, Eq)

instance JSON JobDependency where
  showJSON (JobDependency dep status) = showJSON (dep, status)
  readJSON = liftM (uncurry JobDependency) . readJSON

-- | From job dependency and job id compute an absolute job dependency.
absoluteJobDependency :: (Monad m) => JobDependency -> JobId -> m JobDependency
absoluteJobDependency (JobDependency jdep fstats) jid =
  liftM (flip JobDependency fstats) $ absoluteJobIdDep jdep jid 

-- | Valid opcode priorities for submit.
$(THH.declareIADT "OpSubmitPriority"
  [ ("OpPrioLow",    'ConstantUtils.priorityLow)
  , ("OpPrioNormal", 'ConstantUtils.priorityNormal)
  , ("OpPrioHigh",   'ConstantUtils.priorityHigh)
  ])
$(THH.makeJSONInstance ''OpSubmitPriority)

-- | Parse submit priorities from a string.
parseSubmitPriority :: (Monad m) => String -> m OpSubmitPriority
parseSubmitPriority "low"    = return OpPrioLow
parseSubmitPriority "normal" = return OpPrioNormal
parseSubmitPriority "high"   = return OpPrioHigh
parseSubmitPriority str      = fail $ "Unknown priority '" ++ str ++ "'"

-- | Format a submit priority as string.
fmtSubmitPriority :: OpSubmitPriority -> String
fmtSubmitPriority OpPrioLow    = "low"
fmtSubmitPriority OpPrioNormal = "normal"
fmtSubmitPriority OpPrioHigh   = "high"

-- | Our ADT for the OpCode status at runtime (while in a job).
$(THH.declareLADT ''String "OpStatus"
  [ ("OP_STATUS_QUEUED",    "queued")
  , ("OP_STATUS_WAITING",   "waiting")
  , ("OP_STATUS_CANCELING", "canceling")
  , ("OP_STATUS_RUNNING",   "running")
  , ("OP_STATUS_CANCELED",  "canceled")
  , ("OP_STATUS_SUCCESS",   "success")
  , ("OP_STATUS_ERROR",     "error")
  ])
$(THH.makeJSONInstance ''OpStatus)

-- | Type for the job message type.
$(THH.declareLADT ''String "ELogType"
  [ ("ELogMessage",      "message")
  , ("ELogRemoteImport", "remote-import")
  , ("ELogJqueueTest",   "jqueue-test")
  ])
$(THH.makeJSONInstance ''ELogType)

-- | Type of one element of a reason trail.
type ReasonElem = (String, String, Integer)

-- | Type representing a reason trail.
type ReasonTrail = [ReasonElem]

-- | The VTYPES, a mini-type system in Python.
$(THH.declareLADT ''String "VType"
  [ ("VTypeString",      "string")
  , ("VTypeMaybeString", "maybe-string")
  , ("VTypeBool",        "bool")
  , ("VTypeSize",        "size")
  , ("VTypeInt",         "int")
  ])
$(THH.makeJSONInstance ''VType)

instance THH.PyValue VType where
  showValue = THH.showValue . vTypeToRaw

-- * Node role type

$(THH.declareLADT ''String "NodeRole"
  [ ("NROffline",   "O")
  , ("NRDrained",   "D")
  , ("NRRegular",   "R")
  , ("NRCandidate", "C")
  , ("NRMaster",    "M")
  ])
$(THH.makeJSONInstance ''NodeRole)

-- | The description of the node role.
roleDescription :: NodeRole -> String
roleDescription NROffline   = "offline"
roleDescription NRDrained   = "drained"
roleDescription NRRegular   = "regular"
roleDescription NRCandidate = "master candidate"
roleDescription NRMaster    = "master"

-- * Disk types

$(THH.declareLADT ''String "DiskMode"
  [ ("DiskRdOnly", "ro")
  , ("DiskRdWr",   "rw")
  ])
$(THH.makeJSONInstance ''DiskMode)

-- | The persistent block driver type. Currently only one type is allowed.
$(THH.declareLADT ''String "BlockDriver"
  [ ("BlockDrvManual", "manual")
  ])
$(THH.makeJSONInstance ''BlockDriver)

-- * Instance types

$(THH.declareLADT ''String "AdminState"
  [ ("AdminOffline", "offline")
  , ("AdminDown",    "down")
  , ("AdminUp",      "up")
  ])
$(THH.makeJSONInstance ''AdminState)

-- * Storage field type

$(THH.declareLADT ''String "StorageField"
  [ ( "SFUsed",        "used")
  , ( "SFName",        "name")
  , ( "SFAllocatable", "allocatable")
  , ( "SFFree",        "free")
  , ( "SFSize",        "size")
  ])
$(THH.makeJSONInstance ''StorageField)

-- * Disk access protocol

$(THH.declareLADT ''String "DiskAccessMode"
  [ ( "DiskUserspace",   "userspace")
  , ( "DiskKernelspace", "kernelspace")
  ])
$(THH.makeJSONInstance ''DiskAccessMode)

-- | Local disk status
--
-- Python code depends on:
--   DiskStatusOk < DiskStatusUnknown < DiskStatusFaulty
$(THH.declareILADT "LocalDiskStatus"
  [ ("DiskStatusFaulty",  3)
  , ("DiskStatusOk",      1)
  , ("DiskStatusUnknown", 2)
  ])

localDiskStatusName :: LocalDiskStatus -> String
localDiskStatusName DiskStatusFaulty = "faulty"
localDiskStatusName DiskStatusOk = "ok"
localDiskStatusName DiskStatusUnknown = "unknown"

-- | Replace disks type.
$(THH.declareLADT ''String "ReplaceDisksMode"
  [ -- Replace disks on primary
    ("ReplaceOnPrimary",    "replace_on_primary")
    -- Replace disks on secondary
  , ("ReplaceOnSecondary",  "replace_on_secondary")
    -- Change secondary node
  , ("ReplaceNewSecondary", "replace_new_secondary")
  , ("ReplaceAuto",         "replace_auto")
  ])
$(THH.makeJSONInstance ''ReplaceDisksMode)

-- | Basic timeouts for RPC calls.
$(THH.declareILADT "RpcTimeout"
  [ ("Urgent",    60)       -- 1 minute
  , ("Fast",      5 * 60)   -- 5 minutes
  , ("Normal",    15 * 60)  -- 15 minutes
  , ("Slow",      3600)     -- 1 hour
  , ("FourHours", 4 * 3600) -- 4 hours
  , ("OneDay",    86400)    -- 1 day
  ])

$(THH.declareLADT ''String "ImportExportCompression"
  [ -- No compression
    ("None", "none")
    -- gzip compression
  , ("GZip", "gzip")
  ])
$(THH.makeJSONInstance ''ImportExportCompression)

instance THH.PyValue ImportExportCompression where
  showValue = THH.showValue . importExportCompressionToRaw

-- | Hotplug action.

$(THH.declareLADT ''String "HotplugAction"
  [ ("HAAdd", "hotadd")
  , ("HARemove",  "hotremove")
  , ("HAMod",     "hotmod")
  ])
$(THH.makeJSONInstance ''HotplugAction)

-- | Hotplug Device Target.

$(THH.declareLADT ''String "HotplugTarget"
  [ ("HTDisk", "hotdisk")
  , ("HTNic",  "hotnic")
  ])
$(THH.makeJSONInstance ''HotplugTarget)
