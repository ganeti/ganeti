{-| Implementation of the Ganeti Query2 instance queries.

-}

{-

Copyright (C) 2013 Google Inc.
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

module Ganeti.Query.Instance
  ( Runtime
  , fieldsMap
  , collectLiveData
  , getInstanceInfo
  , instanceFields
  , instanceAliases
  ) where

import Control.Applicative
import Control.Monad (liftM, (>=>))
import qualified Data.ByteString.UTF8 as UTF8
import Data.Either
import Data.List
import Data.Maybe
import Data.Monoid
import qualified Data.Map as Map
import Data.Ord (comparing)
import qualified Text.JSON as J
import Text.Printf

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.Config
import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as C
import Ganeti.Errors
import Ganeti.JSON (MaybeForJSON(..), fromContainer)
import Ganeti.Objects
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types
import Ganeti.Rpc
import Ganeti.Storage.Utils
import Ganeti.Types
import Ganeti.Utils (formatOrdinal)

-- | The LiveInfo consists of two entries whose presence is independent.
-- The 'InstanceInfo' is the live instance information, accompanied by a bool
-- signifying if it was found on its designated primary node or not.
-- The 'InstanceConsoleInfo' describes how to connect to an instance.
-- Any combination of these may or may not be present, depending on node and
-- instance availability.
type LiveInfo = (Maybe (InstanceInfo, Bool), Maybe InstanceConsoleInfo)

-- | Runtime containing the 'LiveInfo'. See the genericQuery function in
-- the Query.hs file for an explanation of the terms used.
type Runtime = Either RpcError LiveInfo

-- | The instance fields map.
fieldsMap :: FieldMap Instance Runtime
fieldsMap = fieldListToFieldMap aliasedFields

-- | The instance aliases.
instanceAliases :: [(FieldName, FieldName)]
instanceAliases =
  [ ("vcpus", "be/vcpus")
  , ("be/memory", "be/maxmem")
  , ("sda_size", "disk.size/0")
  , ("sdb_size", "disk.size/1")
  , ("ip", "nic.ip/0")
  , ("mac", "nic.mac/0")
  , ("bridge", "nic.bridge/0")
  , ("nic_mode", "nic.mode/0")
  , ("nic_link", "nic.link/0")
  , ("nic_network", "nic.network/0")
  ]

-- | The aliased instance fields.
aliasedFields :: FieldList Instance Runtime
aliasedFields = aliasFields instanceAliases instanceFields

-- | The instance fields.
instanceFields :: FieldList Instance Runtime
instanceFields =
  -- Simple fields
  [ (FieldDefinition "admin_state" "InstanceState" QFTText
     "Desired state of instance",
     FieldSimple (rsMaybeNoData . liftM adminStateToRaw . instAdminState),
     QffNormal)
  , (FieldDefinition "admin_state_source" "InstanceStateSource" QFTText
     "Who last changed the desired state of the instance",
     FieldSimple (rsMaybeNoData . liftM adminStateSourceToRaw
                  . instAdminStateSource),
     QffNormal)
  , (FieldDefinition "admin_up" "Autostart" QFTBool
     "Desired state of instance",
     FieldSimple (rsMaybeNoData . liftM (== AdminUp) . instAdminState),
     QffNormal)
  , (FieldDefinition "disks_active" "DisksActive" QFTBool
     "Desired state of instance disks",
     FieldSimple (rsMaybeNoData . instDisksActive), QffNormal)
  , (FieldDefinition "name" "Instance" QFTText
     "Instance name",
     FieldSimple (rsMaybeNoData . instName), QffHostname)
  , (FieldDefinition "hypervisor" "Hypervisor" QFTText
     "Hypervisor name",
     FieldSimple (rsMaybeNoData . instHypervisor), QffNormal)
  , (FieldDefinition "network_port" "Network_port" QFTOther
     "Instance network port if available (e.g. for VNC console)",
     FieldSimple (rsMaybeUnavail . instNetworkPort), QffNormal)
  , (FieldDefinition "os" "OS" QFTText
     "Operating system",
     FieldSimple (rsMaybeNoData . instOs), QffNormal)
  , (FieldDefinition "pnode" "Primary_node" QFTText
     "Primary node",
     FieldConfig getPrimaryNodeName, QffHostname)
  , (FieldDefinition "pnode.group" "PrimaryNodeGroup" QFTText
     "Primary node's group",
     FieldConfig getPrimaryNodeGroupName, QffNormal)
  , (FieldDefinition "pnode.group.uuid" "PrimaryNodeGroupUUID" QFTText
     "Primary node's group UUID",
     FieldConfig getPrimaryNodeGroupUuid, QffNormal)
  , (FieldDefinition "snodes" "Secondary_Nodes" QFTOther
     "Secondary nodes; usually this will just be one node",
     FieldConfig (getSecondaryNodeAttribute nodeName), QffNormal)
  , (FieldDefinition "snodes.group" "SecondaryNodesGroups" QFTOther
     "Node groups of secondary nodes",
     FieldConfig (getSecondaryNodeGroupAttribute groupName), QffNormal)
  , (FieldDefinition "snodes.group.uuid" "SecondaryNodesGroupsUUID" QFTOther
     "Node group UUIDs of secondary nodes",
     FieldConfig (getSecondaryNodeGroupAttribute uuidOf), QffNormal)
  ] ++

  -- Instance parameter fields, whole
  [ (FieldDefinition "hvparams" "HypervisorParameters" QFTOther
     "Hypervisor parameters (merged)",
     FieldConfig
       ((rsNormal .) . getFilledInstHvParams (C.toList C.hvcGlobals)),
     QffNormal),

    (FieldDefinition "beparams" "BackendParameters" QFTOther
     "Backend parameters (merged)",
     FieldConfig ((rsErrorNoData .) . getFilledInstBeParams), QffNormal)
  , (FieldDefinition "osparams" "OpSysParameters" QFTOther
     "Operating system parameters (merged)",
     FieldConfig ((rsNormal .) . getFilledInstOsParams), QffNormal)
  , (FieldDefinition "custom_hvparams" "CustomHypervisorParameters" QFTOther
     "Custom hypervisor parameters",
     FieldSimple (rsNormal . instHvparams), QffNormal)
  , (FieldDefinition "custom_beparams" "CustomBackendParameters" QFTOther
     "Custom backend parameters",
     FieldSimple (rsNormal . instBeparams), QffNormal)
  , (FieldDefinition "custom_osparams" "CustomOpSysParameters" QFTOther
     "Custom operating system parameters",
     FieldSimple (rsNormal . instOsparams), QffNormal)
  , (FieldDefinition "custom_nicparams" "CustomNicParameters" QFTOther
     "Custom network interface parameters",
     FieldSimple (rsNormal . map nicNicparams . instNics), QffNormal)
  ] ++

  -- Instance parameter fields, generated
  map (buildBeParamField beParamGetter) allBeParamFields ++
  map (buildHvParamField hvParamGetter)
      (C.toList C.hvsParameters \\ C.toList C.hvcGlobals) ++

  -- disk parameter fields
  [ (FieldDefinition "disk_usage" "DiskUsage" QFTUnit
     "Total disk space used by instance on each of its nodes; this is not the\
     \ disk size visible to the instance, but the usage on the node",
     FieldConfig getDiskSizeRequirements, QffNormal)
  , (FieldDefinition "disk.count" "Disks" QFTNumber
     "Number of disks",
     FieldSimple (rsNormal . length . instDisks), QffNormal)
  , (FieldDefinition "disk.sizes" "Disk_sizes" QFTOther
     "List of disk sizes", FieldConfig getDiskSizes, QffNormal)
  , (FieldDefinition "disk.spindles" "Disk_spindles" QFTOther
     "List of disk spindles",
     FieldConfig getDiskSpindles, QffNormal)
  , (FieldDefinition "disk.names" "Disk_names" QFTOther
     "List of disk names",
     FieldConfig getDiskNames, QffNormal)
  , (FieldDefinition "disk.uuids" "Disk_UUIDs" QFTOther
     "List of disk UUIDs",
     FieldConfig getDiskUuids, QffNormal)
    -- For pre-2.14 backwards compatibility
  , (FieldDefinition "disk_template" "Disk_template" QFTText
     "Instance disk template",
     FieldConfig getDiskTemplate, QffNormal)
  ] ++

  -- Per-disk parameter fields
  instantiateIndexedFields C.maxDisks
  [ (fieldDefinitionCompleter "disk.size/%d" "Disk/%d" QFTUnit
    "Disk size of %s disk",
    getIndexedOptionalConfField getInstDisksFromObj diskSize,
    QffNormal)
  , (fieldDefinitionCompleter "disk.spindles/%d" "DiskSpindles/%d" QFTNumber
    "Spindles of %s disk",
    getIndexedOptionalConfField getInstDisksFromObj diskSpindles,
    QffNormal)
  , (fieldDefinitionCompleter "disk.name/%d" "DiskName/%d" QFTText
    "Name of %s disk",
    getIndexedOptionalConfField getInstDisksFromObj diskName, QffNormal)
  , (fieldDefinitionCompleter "disk.uuid/%d" "DiskUUID/%d" QFTText
    "UUID of %s disk",
    getIndexedConfField getInstDisksFromObj uuidOf, QffNormal)
  ] ++

  -- Aggregate nic parameter fields
  [ (FieldDefinition "nic.count" "NICs" QFTNumber
     "Number of network interfaces",
     FieldSimple (rsNormal . length . instNics), QffNormal)
  , (FieldDefinition "nic.macs" "NIC_MACs" QFTOther
     (nicAggDescPrefix ++ "MAC address"),
     FieldSimple (rsNormal . map nicMac . instNics), QffNormal)
  , (FieldDefinition "nic.ips" "NIC_IPs" QFTOther
     (nicAggDescPrefix ++ "IP address"),
     FieldSimple (rsNormal . map (MaybeForJSON . nicIp) . instNics),
     QffNormal)
  , (FieldDefinition "nic.names" "NIC_Names" QFTOther
     (nicAggDescPrefix ++ "name"),
     FieldSimple (rsNormal . map (MaybeForJSON . nicName) . instNics),
     QffNormal)
  , (FieldDefinition "nic.uuids" "NIC_UUIDs" QFTOther
     (nicAggDescPrefix ++ "UUID"),
     FieldSimple (rsNormal . map uuidOf . instNics), QffNormal)
  , (FieldDefinition "nic.modes" "NIC_modes" QFTOther
     (nicAggDescPrefix ++ "mode"),
     FieldConfig (\cfg -> rsNormal . map
       (nicpMode . fillNicParamsFromConfig cfg . nicNicparams)
       . instNics),
     QffNormal)
  , (FieldDefinition "nic.vlans" "NIC_VLANs" QFTOther
     (nicAggDescPrefix ++ "VLAN"),
     FieldConfig (\cfg -> rsNormal . map (MaybeForJSON . getNicVlan .
       fillNicParamsFromConfig cfg . nicNicparams) . instNics),
     QffNormal)
  , (FieldDefinition "nic.bridges" "NIC_bridges" QFTOther
     (nicAggDescPrefix ++ "bridge"),
     FieldConfig (\cfg -> rsNormal . map (MaybeForJSON . getNicBridge .
       fillNicParamsFromConfig cfg . nicNicparams) . instNics),
     QffNormal)
  , (FieldDefinition "nic.links" "NIC_links" QFTOther
     (nicAggDescPrefix ++ "link"),
     FieldConfig (\cfg -> rsNormal . map
       (nicpLink . fillNicParamsFromConfig cfg . nicNicparams)
       . instNics), QffNormal)
  , (FieldDefinition "nic.networks" "NIC_networks" QFTOther
     "List containing each interface's network",
     FieldSimple (rsNormal . map (MaybeForJSON . nicNetwork) . instNics),
     QffNormal)
  , (FieldDefinition "nic.networks.names" "NIC_networks_names" QFTOther
     "List containing the name of each interface's network",
     FieldConfig (\cfg -> rsNormal . map
       (\x -> MaybeForJSON (getNetworkName cfg <$> nicNetwork x))
       . instNics),
     QffNormal)
  ] ++

  -- Per-nic parameter fields
  instantiateIndexedFields C.maxNics
  [ (fieldDefinitionCompleter "nic.ip/%d" "NicIP/%d" QFTText
     ("IP address" ++ nicDescSuffix),
     getIndexedOptionalField instNics nicIp, QffNormal)
  , (fieldDefinitionCompleter "nic.uuid/%d" "NicUUID/%d" QFTText
     ("UUID address" ++ nicDescSuffix),
     getIndexedField instNics uuidOf, QffNormal)
  , (fieldDefinitionCompleter "nic.mac/%d" "NicMAC/%d" QFTText
     ("MAC address" ++ nicDescSuffix),
     getIndexedField instNics nicMac, QffNormal)
  , (fieldDefinitionCompleter "nic.name/%d" "NicName/%d" QFTText
     ("Name address" ++ nicDescSuffix),
     getIndexedOptionalField instNics nicName, QffNormal)
  , (fieldDefinitionCompleter "nic.network/%d" "NicNetwork/%d" QFTText
     ("Network" ++ nicDescSuffix),
     getIndexedOptionalField instNics nicNetwork, QffNormal)
  , (fieldDefinitionCompleter "nic.mode/%d" "NicMode/%d" QFTText
     ("Mode" ++ nicDescSuffix),
     getIndexedNicField nicpMode, QffNormal)
  , (fieldDefinitionCompleter "nic.link/%d" "NicLink/%d" QFTText
     ("Link" ++ nicDescSuffix),
     getIndexedNicField nicpLink, QffNormal)
  , (fieldDefinitionCompleter "nic.vlan/%d" "NicVLAN/%d" QFTText
     ("VLAN" ++ nicDescSuffix),
     getOptionalIndexedNicField getNicVlan, QffNormal)
  , (fieldDefinitionCompleter "nic.network.name/%d" "NicNetworkName/%d" QFTText
     ("Network name" ++ nicDescSuffix),
     getIndexedNicNetworkNameField, QffNormal)
  , (fieldDefinitionCompleter "nic.bridge/%d" "NicBridge/%d" QFTText
     ("Bridge" ++ nicDescSuffix),
     getOptionalIndexedNicField getNicBridge, QffNormal)
  ] ++

  -- Live fields using special getters
  [ (FieldDefinition "status" "Status" QFTText
     statusDocText,
     FieldConfigRuntime statusExtract, QffNormal)
  , (FieldDefinition "oper_state" "Running" QFTBool
     "Actual state of instance",
     FieldRuntime operStatusExtract, QffNormal),

    (FieldDefinition "console" "Console" QFTOther
     "Instance console information",
     FieldRuntime consoleExtract, QffNormal)
  ] ++

  -- Simple live fields
  map instanceLiveFieldBuilder instanceLiveFieldsDefs ++

  -- Common fields
  timeStampFields ++
  serialFields "Instance" ++
  uuidFields "Instance" ++
  forthcomingFields "Instance" ++
  tagsFields

-- * Helper functions for node property retrieval

-- | Constant suffix of network interface field descriptions.
nicDescSuffix ::String
nicDescSuffix = " of %s network interface"

-- | Almost-constant suffix of aggregate network interface field descriptions.
nicAggDescPrefix ::String
nicAggDescPrefix = "List containing each network interface's "

-- | Given a network name id, returns the network's name.
getNetworkName :: ConfigData -> String -> NonEmptyString
getNetworkName cfg = networkName . (Map.!) (fromContainer $ configNetworks cfg)
                     . UTF8.fromString

-- | Gets the bridge of a NIC.
getNicBridge :: FilledNicParams -> Maybe String
getNicBridge nicParams
  | nicpMode nicParams == NMBridged = Just $ nicpLink nicParams
  | otherwise                       = Nothing

-- | Gets the VLAN of a NIC.
getNicVlan :: FilledNicParams -> Maybe String
getNicVlan params
  | nicpMode params == NMOvs = Just $ nicpVlan params
  | otherwise                = Nothing

-- | Fill partial NIC params by using the defaults from the configuration.
fillNicParamsFromConfig :: ConfigData -> PartialNicParams -> FilledNicParams
fillNicParamsFromConfig cfg = fillParams (getDefaultNicParams cfg)

-- | Retrieves the default network interface parameters.
getDefaultNicParams :: ConfigData -> FilledNicParams
getDefaultNicParams cfg =
  (Map.!) (fromContainer . clusterNicparams . configCluster $ cfg)
    $ UTF8.fromString C.ppDefault

-- | Retrieves the real disk size requirements for all the disks of the
-- instance. This includes the metadata etc. and is different from the values
-- visible to the instance.
getDiskSizeRequirements :: ConfigData -> Instance -> ResultEntry
getDiskSizeRequirements cfg inst =
  rsErrorNoData . liftA (sum . map getSize) . getInstDisksFromObj cfg $ inst
 where
  diskType x = lidDiskType <$> diskLogicalId x
  getSize :: Disk -> Int
  getSize disk =
    let dt = diskType disk
    in case dt of
         Just DTDrbd8    -> fromMaybe 0 (diskSize disk) + C.drbdMetaSize
         Just DTDiskless -> 0
         Just DTBlock    -> 0
         _               -> fromMaybe 0 (diskSize disk)

-- | Get a list of disk sizes for an instance
getDiskSizes :: ConfigData -> Instance -> ResultEntry
getDiskSizes cfg =
  rsErrorNoData . liftA (map $ MaybeForJSON . diskSize)
  . getInstDisksFromObj cfg

-- | Get a list of disk spindles
getDiskSpindles :: ConfigData -> Instance -> ResultEntry
getDiskSpindles cfg =
  rsErrorNoData . liftA (map (MaybeForJSON . diskSpindles)) .
    getInstDisksFromObj cfg

-- | Get a list of disk names for an instance
getDiskNames :: ConfigData -> Instance -> ResultEntry
getDiskNames cfg =
  rsErrorNoData . liftA (map (MaybeForJSON . diskName)) .
    getInstDisksFromObj cfg

-- | Get a list of disk UUIDs for an instance
getDiskUuids :: ConfigData -> Instance -> ResultEntry
getDiskUuids cfg =
  rsErrorNoData . liftA (map uuidOf) . getInstDisksFromObj cfg

-- | Creates a functions which produces a FieldConfig 'FieldGetter' when fed
-- an index. Works for fields that may not return a value, expressed through
-- the Maybe monad.
getIndexedOptionalConfField :: (J.JSON b)
                            => (ConfigData -> Instance -> ErrorResult [a])
                                              -- ^ Extracts a list of objects
                            -> (a -> Maybe b) -- ^ Possibly gets a property
                                              -- from an object
                            -> Int            -- ^ Index in list to use
                            -> FieldGetter Instance Runtime -- ^ Result
getIndexedOptionalConfField extractor optPropertyGetter index =
  let getProperty x = maybeAt index x >>= optPropertyGetter
  in FieldConfig (\cfg ->
    rsErrorMaybeUnavail . liftA getProperty . extractor cfg)

-- | Creates a function which produces a FieldConfig 'FieldGetter' when fed
-- an index. Works only for fields that surely return a value.
getIndexedConfField :: (J.JSON b)
                    => (ConfigData -> Instance -> ErrorResult [a])
                                  -- ^ Extracts a list of objects
                    -> (a -> b)   -- ^ Gets a property from an object
                    -> Int        -- ^ Index in list to use
                    -> FieldGetter Instance Runtime -- ^ Result
getIndexedConfField extractor propertyGetter index =
  let optPropertyGetter = Just . propertyGetter
  in getIndexedOptionalConfField extractor optPropertyGetter index

-- | Returns a field that retrieves a given NIC's network name.
getIndexedNicNetworkNameField :: Int -> FieldGetter Instance Runtime
getIndexedNicNetworkNameField index =
  FieldConfig (\cfg inst -> rsMaybeUnavail $ do
    nicObj <- maybeAt index $ instNics inst
    nicNetworkId <- nicNetwork nicObj
    return $ getNetworkName cfg nicNetworkId)

-- | Gets a fillable NIC field.
getIndexedNicField :: (J.JSON a)
                   => (FilledNicParams -> a)
                   -> Int
                   -> FieldGetter Instance Runtime
getIndexedNicField getter =
  getOptionalIndexedNicField (\x -> Just . getter $ x)

-- | Gets an optional fillable NIC field.
getOptionalIndexedNicField :: (J.JSON a)
                           => (FilledNicParams -> Maybe a)
                           -> Int
                           -> FieldGetter Instance Runtime
getOptionalIndexedNicField =
  getIndexedFieldWithDefault
    (map nicNicparams . instNics) (\x _ -> getDefaultNicParams x) fillParams

-- | Creates a function which produces a 'FieldGetter' when fed an index. Works
-- for fields that should be filled out through the use of a default.
getIndexedFieldWithDefault :: (J.JSON c)
  => (Instance -> [a])             -- ^ Extracts a list of incomplete objects
  -> (ConfigData -> Instance -> b) -- ^ Extracts the default object
  -> (b -> a -> b)                 -- ^ Fills the default object
  -> (b -> Maybe c)                -- ^ Extracts an obj property
  -> Int                           -- ^ Index in list to use
  -> FieldGetter Instance Runtime  -- ^ Result
getIndexedFieldWithDefault
  listGetter defaultGetter fillFn propertyGetter index =
  FieldConfig (\cfg inst -> rsMaybeUnavail $ do
                              incompleteObj <- maybeAt index $ listGetter inst
                              let defaultObj = defaultGetter cfg inst
                                  completeObj = fillFn defaultObj incompleteObj
                              propertyGetter completeObj)

-- | Creates a function which produces a 'FieldGetter' when fed an index. Works
-- for fields that may not return a value, expressed through the Maybe monad.
getIndexedOptionalField :: (J.JSON b)
                        => (Instance -> [a]) -- ^ Extracts a list of objects
                        -> (a -> Maybe b)    -- ^ Possibly gets a property
                                             -- from an object
                        -> Int               -- ^ Index in list to use
                        -> FieldGetter Instance Runtime -- ^ Result
getIndexedOptionalField extractor optPropertyGetter index =
  FieldSimple(\inst -> rsMaybeUnavail $ do
                         obj <- maybeAt index $ extractor inst
                         optPropertyGetter obj)

-- | Creates a function which produces a 'FieldGetter' when fed an index.
-- Works only for fields that surely return a value.
getIndexedField :: (J.JSON b)
                => (Instance -> [a]) -- ^ Extracts a list of objects
                -> (a -> b)          -- ^ Gets a property from an object
                -> Int               -- ^ Index in list to use
                -> FieldGetter Instance Runtime -- ^ Result
getIndexedField extractor propertyGetter index =
  let optPropertyGetter = Just . propertyGetter
  in getIndexedOptionalField extractor optPropertyGetter index

-- | Retrieves a value from an array at an index, using the Maybe monad to
-- indicate failure.
maybeAt :: Int -> [a] -> Maybe a
maybeAt index list
  | index >= length list = Nothing
  | otherwise            = Just $ list !! index

-- | Primed with format strings for everything but the type, it consumes two
-- values and uses them to complete the FieldDefinition.
-- Warning: a bit unsafe as it uses printf. Handle with care.
fieldDefinitionCompleter :: (PrintfArg t1) => (PrintfArg t2)
                         => FieldName
                         -> FieldTitle
                         -> FieldType
                         -> FieldDoc
                         -> t1
                         -> t2
                         -> FieldDefinition
fieldDefinitionCompleter fName fTitle fType fDoc firstVal secondVal =
  FieldDefinition (printf fName firstVal)
                  (printf fTitle firstVal)
                  fType
                  (printf fDoc secondVal)

-- | Given an incomplete field definition and values that can complete it,
-- return a fully functional FieldData. Cannot work for all cases, should be
-- extended as necessary.
fillIncompleteFields :: (t1 -> t2 -> FieldDefinition,
                         t1 -> FieldGetter a b,
                         QffMode)
                     -> t1
                     -> t2
                     -> FieldData a b
fillIncompleteFields (iDef, iGet, mode) firstVal secondVal =
  (iDef firstVal secondVal, iGet firstVal, mode)

-- | Given indexed fields that describe lists, complete / instantiate them for
-- a given list size.
instantiateIndexedFields :: (Show t1, Integral t1)
                         => Int            -- ^ The size of the list
                         -> [(t1 -> String -> FieldDefinition,
                              t1 -> FieldGetter a b,
                              QffMode)]    -- ^ The indexed fields
                         -> FieldList a b  -- ^ A list of complete fields
instantiateIndexedFields listSize fields = do
  index <- take listSize [0..]
  field <- fields
  return . fillIncompleteFields field index . formatOrdinal $ index + 1

-- * Various helper functions for property retrieval

-- | Helper function for primary node retrieval
getPrimaryNode :: ConfigData -> Instance -> ErrorResult Node
getPrimaryNode cfg = maybe (Bad $ ParameterError "no primary node") return
                       . instName
                     >=> getInstPrimaryNode cfg

-- | Get primary node hostname
getPrimaryNodeName :: ConfigData -> Instance -> ResultEntry
getPrimaryNodeName cfg inst =
  rsErrorNoData $ nodeName <$> getPrimaryNode cfg inst

-- | Get primary node group
getPrimaryNodeGroup :: ConfigData -> Instance -> ErrorResult NodeGroup
getPrimaryNodeGroup cfg inst = do
  pNode <- getPrimaryNode cfg inst
  maybeToError "Configuration missing" $ getGroupOfNode cfg pNode

-- | Get primary node group name
getPrimaryNodeGroupName :: ConfigData -> Instance -> ResultEntry
getPrimaryNodeGroupName cfg inst =
  rsErrorNoData $ groupName <$> getPrimaryNodeGroup cfg inst

-- | Get primary node group uuid
getPrimaryNodeGroupUuid :: ConfigData -> Instance -> ResultEntry
getPrimaryNodeGroupUuid cfg inst =
  rsErrorNoData $ uuidOf <$> getPrimaryNodeGroup cfg inst

-- | Get secondary nodes - the configuration objects themselves
getSecondaryNodes :: ConfigData -> Instance -> ErrorResult [Node]
getSecondaryNodes cfg inst = do
  pNode <- getPrimaryNode cfg inst
  iname <- maybe (Bad $ ParameterError "no name") return $ instName inst
  allNodes <- getInstAllNodes cfg iname
  return $ delete pNode allNodes

-- | Get attributes of the secondary nodes
getSecondaryNodeAttribute :: (J.JSON a)
                          => (Node -> a)
                          -> ConfigData
                          -> Instance
                          -> ResultEntry
getSecondaryNodeAttribute getter cfg inst =
  rsErrorNoData $ map (J.showJSON . getter) <$> getSecondaryNodes cfg inst

-- | Get secondary node groups
getSecondaryNodeGroups :: ConfigData -> Instance -> ErrorResult [NodeGroup]
getSecondaryNodeGroups cfg inst = do
  sNodes <- getSecondaryNodes cfg inst
  return . catMaybes $ map (getGroupOfNode cfg) sNodes

-- | Get attributes of secondary node groups
getSecondaryNodeGroupAttribute :: (J.JSON a)
                               => (NodeGroup -> a)
                               -> ConfigData
                               -> Instance
                               -> ResultEntry
getSecondaryNodeGroupAttribute getter cfg inst =
  rsErrorNoData $ map (J.showJSON . getter) <$> getSecondaryNodeGroups cfg inst

-- | Beparam getter builder: given a field, it returns a FieldConfig
-- getter, that is a function that takes the config and the object and
-- returns the Beparam field specified when the getter was built.
beParamGetter :: String       -- ^ The field we are building the getter for
              -> ConfigData   -- ^ The configuration object
              -> Instance     -- ^ The instance configuration object
              -> ResultEntry  -- ^ The result
beParamGetter field config inst =
  case getFilledInstBeParams config inst of
    Ok beParams -> dictFieldGetter field $ Just beParams
    Bad       _ -> rsNoData

-- | Hvparam getter builder: given a field, it returns a FieldConfig
-- getter, that is a function that takes the config and the object and
-- returns the Hvparam field specified when the getter was built.
hvParamGetter :: String -- ^ The field we're building the getter for
              -> ConfigData -> Instance -> ResultEntry
hvParamGetter field cfg inst =
  rsMaybeUnavail . Map.lookup (UTF8.fromString field) . fromContainer $
    getFilledInstHvParams (C.toList C.hvcGlobals) cfg inst

-- * Live fields functionality

-- | List of node live fields.
instanceLiveFieldsDefs :: [(FieldName, FieldTitle, FieldType, String, FieldDoc)]
instanceLiveFieldsDefs =
  [ ("oper_ram", "Memory", QFTUnit, "oper_ram",
     "Actual memory usage as seen by hypervisor")
  , ("oper_vcpus", "VCPUs", QFTNumber, "oper_vcpus",
     "Actual number of VCPUs as seen by hypervisor")
  ]

-- | Map each name to a function that extracts that value from the RPC result.
instanceLiveFieldExtract :: FieldName -> InstanceInfo -> Instance -> J.JSValue
instanceLiveFieldExtract "oper_ram"   info _ = J.showJSON $ instInfoMemory info
instanceLiveFieldExtract "oper_vcpus" info _ = J.showJSON $ instInfoVcpus info
instanceLiveFieldExtract n _ _ = J.showJSON $
  "The field " ++ n ++ " is not an expected or extractable live field!"

-- | Helper for extracting an instance live field from the RPC results.
instanceLiveRpcCall :: FieldName -> Runtime -> Instance -> ResultEntry
instanceLiveRpcCall fname (Right (Just (res, _), _)) inst =
  case instanceLiveFieldExtract fname res inst of
    J.JSNull -> rsNoData
    x        -> rsNormal x
instanceLiveRpcCall _ (Right (Nothing, _)) _ = rsUnavail
instanceLiveRpcCall _ (Left err) _ =
  ResultEntry (rpcErrorToStatus err) Nothing

-- | Builder for node live fields.
instanceLiveFieldBuilder :: (FieldName, FieldTitle, FieldType, String, FieldDoc)
                         -> FieldData Instance Runtime
instanceLiveFieldBuilder (fname, ftitle, ftype, _, fdoc) =
  ( FieldDefinition fname ftitle ftype fdoc
  , FieldRuntime $ instanceLiveRpcCall fname
  , QffNormal)

-- * Functionality related to status and operational status extraction

-- | The documentation text for the instance status field
statusDocText :: String
statusDocText =
  let si = show . instanceStatusToRaw :: InstanceStatus -> String
  in  "Instance status; " ++
      si Running ++
      " if instance is set to be running and actually is, " ++
      si StatusDown ++
      " if instance is stopped and is not running, " ++
      si WrongNode ++
      " if instance running, but not on its designated primary node, " ++
      si ErrorUp ++
      " if instance should be stopped, but is actually running, " ++
      si ErrorDown ++
      " if instance should run, but doesn't, " ++
      si NodeDown ++
      " if instance's primary node is down, " ++
      si NodeOffline ++
      " if instance's primary node is marked offline, " ++
      si StatusOffline ++
      " if instance is offline and does not use dynamic resources"

-- | Checks if the primary node of an instance is offline
isPrimaryOffline :: ConfigData -> Instance -> Bool
isPrimaryOffline cfg inst =
  let pNodeResult = maybe (Bad $ ParameterError "no primary node") return
                          (instPrimaryNode inst)
                    >>= getNode cfg
  in case pNodeResult of
     Ok pNode -> nodeOffline pNode
     Bad    _ -> error "Programmer error - result assumed to be OK is Bad!"

-- | Determines if user shutdown reporting is enabled
userShutdownEnabled :: ConfigData -> Bool
userShutdownEnabled = clusterEnabledUserShutdown . configCluster

-- | Determines the status of a live instance
liveInstanceStatus :: ConfigData
                   -> (InstanceInfo, Bool)
                   -> Instance
                   -> InstanceStatus
liveInstanceStatus cfg (instInfo, foundOnPrimary) inst
  | not foundOnPrimary = WrongNode
  | otherwise =
    case instanceState of
      InstanceStateRunning
        | adminState == Just AdminUp -> Running
        | otherwise -> ErrorUp
      InstanceStateShutdown
        | adminState == Just AdminUp && allowDown -> UserDown
        | adminState == Just AdminUp -> ErrorDown
        | otherwise -> StatusDown
  where adminState = instAdminState inst
        instanceState = instInfoState instInfo

        hvparams =
          fromContainer $ getFilledInstHvParams (C.toList C.hvcGlobals) cfg inst

        allowDown =
          userShutdownEnabled cfg &&
          (instHypervisor inst /= Just Kvm ||
           (Map.member (UTF8.fromString C.hvKvmUserShutdown) hvparams &&
            hvparams Map.! UTF8.fromString C.hvKvmUserShutdown
              == J.JSBool True))

-- | Determines the status of a dead instance.
deadInstanceStatus :: ConfigData -> Instance -> InstanceStatus
deadInstanceStatus cfg inst =
  case instAdminState inst of
    Just AdminUp -> ErrorDown
    Just AdminDown | wasCleanedUp && userShutdownEnabled cfg -> UserDown
                   | otherwise -> StatusDown
    Just AdminOffline -> StatusOffline
    Nothing -> StatusDown
  where wasCleanedUp = instAdminStateSource inst == Just UserSource

-- | Determines the status of the instance, depending on whether it is possible
-- to communicate with its primary node, on which node it is, and its
-- configuration.
determineInstanceStatus :: ConfigData      -- ^ The configuration data
                        -> Runtime         -- ^ All the data from the live call
                        -> Instance        -- ^ Static instance configuration
                        -> InstanceStatus  -- ^ Result
determineInstanceStatus cfg res inst
  | isPrimaryOffline cfg inst = NodeOffline
  | otherwise = case res of
      Left _                   -> NodeDown
      Right (Just liveData, _) -> liveInstanceStatus cfg liveData inst
      Right (Nothing, _)       -> deadInstanceStatus cfg inst

-- | Extracts the instance status, retrieving it using the functions above and
-- transforming it into a 'ResultEntry'.
statusExtract :: ConfigData -> Runtime -> Instance -> ResultEntry
statusExtract cfg res inst =
  rsNormal . J.showJSON . instanceStatusToRaw $
    determineInstanceStatus cfg res inst

-- | Extracts the operational status of the instance.
operStatusExtract :: Runtime -> Instance -> ResultEntry
operStatusExtract res _ =
  rsMaybeNoData $ J.showJSON <$>
    case res of
      Left _       -> Nothing
      Right (x, _) -> Just $ isJust x

-- | Extracts the console connection information
consoleExtract :: Runtime -> Instance -> ResultEntry
consoleExtract (Left err) _ = ResultEntry (rpcErrorToStatus err) Nothing
consoleExtract (Right (_, val)) _ = rsMaybeNoData val

-- * Helper functions extracting information as necessary for the generic query
-- interfaces

-- | This function checks if a node with a given uuid has experienced an error
-- or not.
checkForNodeError :: [(String, ERpcError a)]
                  -> String
                  -> Maybe RpcError
checkForNodeError uuidList uuid =
  case snd <$> pickPairUnique uuid uuidList of
    Just (Left err) -> Just err
    Just (Right _)  -> Nothing
    Nothing         -> Just . RpcResultError $
                         "Node response not present"

-- | Finds information about the instance in the info delivered by a node
findInfoInNodeResult :: Instance
                     -> ERpcError RpcResultAllInstancesInfo
                     -> Maybe InstanceInfo
findInfoInNodeResult inst nodeResponse =
  case nodeResponse of
    Left  _err    -> Nothing
    Right allInfo ->
      let instances = rpcResAllInstInfoInstances allInfo
          maybeMatch = instName inst >>= (`pickPairUnique` instances)
      in snd <$> maybeMatch

-- | Retrieves the instance information if it is present anywhere in the all
-- instances RPC result. Notes if it originates from the primary node.
-- An error is delivered if there is no result, and the primary node is down.
getInstanceInfo :: [(String, ERpcError RpcResultAllInstancesInfo)]
                -> Instance
                -> ERpcError (Maybe (InstanceInfo, Bool))
getInstanceInfo uuidList inst =
  case instPrimaryNode inst of
    Nothing -> Right Nothing
    Just pNodeUuid ->
      let primarySearchResult =
            pickPairUnique pNodeUuid uuidList >>= findInfoInNodeResult inst
                                                    . snd
      in case primarySearchResult of
           Just instInfo -> Right . Just $ (instInfo, True)
           Nothing       ->
             let allSearchResult =
                   getFirst . mconcat $ map
                   (First . findInfoInNodeResult inst . snd) uuidList
             in case allSearchResult of
                  Just instInfo -> Right . Just $ (instInfo, False)
                  Nothing       ->
                    case checkForNodeError uuidList pNodeUuid of
                      Just err -> Left err
                      Nothing  -> Right Nothing

-- | Retrieves the console information if present anywhere in the given results
getConsoleInfo :: [(String, ERpcError RpcResultInstanceConsoleInfo)]
               -> Instance
               -> Maybe InstanceConsoleInfo
getConsoleInfo uuidList inst =
  let allValidResults = concatMap rpcResInstConsInfoInstancesInfo .
                        rights . map snd $ uuidList
  in snd <$> (instName inst >>= flip pickPairUnique allValidResults)

-- | Extracts all the live information that can be extracted.
extractLiveInfo :: [(Node, ERpcError RpcResultAllInstancesInfo)]
                -> [(Node, ERpcError RpcResultInstanceConsoleInfo)]
                -> Instance
                -> Runtime
extractLiveInfo nodeResultList nodeConsoleList inst =
  let uuidConvert     = map (\(x, y) -> (uuidOf x, y))
      uuidResultList  = uuidConvert nodeResultList
      uuidConsoleList = uuidConvert nodeConsoleList
  in case getInstanceInfo uuidResultList inst of
    -- If we can't get the instance info, we can't get the console info either.
    -- Best to propagate the error further.
    Left err  -> Left err
    Right res -> Right (res, getConsoleInfo uuidConsoleList inst)

-- | Retrieves all the parameters for the console calls.
getAllConsoleParams :: ConfigData
                    -> [Instance]
                    -> ErrorResult [InstanceConsoleInfoParams]
getAllConsoleParams cfg = mapM $ \i ->
  InstanceConsoleInfoParams i
    <$> getPrimaryNode cfg i
    <*> getPrimaryNodeGroup cfg i
    <*> pure (getFilledInstHvParams [] cfg i)
    <*> getFilledInstBeParams cfg i

-- | Compares two params according to their node, needed for grouping.
compareParamsByNode :: InstanceConsoleInfoParams
                    -> InstanceConsoleInfoParams
                    -> Bool
compareParamsByNode x y = instConsInfoParamsNode x == instConsInfoParamsNode y

-- | Groups instance information calls heading out to the same nodes.
consoleParamsToCalls :: [InstanceConsoleInfoParams]
                     -> [(Node, RpcCallInstanceConsoleInfo)]
consoleParamsToCalls params =
  let sortedParams = sortBy
        (comparing (instPrimaryNode . instConsInfoParamsInstance)) params
      groupedParams = groupBy compareParamsByNode sortedParams
  in map (\x -> case x of
            [] -> error "Programmer error: group must have one or more members"
            paramGroup@(y:_) ->
              let node = instConsInfoParamsNode y
                  packer z = do
                              name <- instName $ instConsInfoParamsInstance z
                              return (name, z)
              in (node, RpcCallInstanceConsoleInfo . mapMaybe packer
                          $ paramGroup)
         ) groupedParams

-- | Retrieves a list of all the hypervisors and params used by the given
-- instances.
getHypervisorSpecs :: ConfigData -> [Instance] -> [(Hypervisor, HvParams)]
getHypervisorSpecs cfg instances =
  let hvs = nub . mapMaybe instHypervisor $ instances
      hvParamMap = (fromContainer . clusterHvparams . configCluster $ cfg)
  in zip hvs . map ((Map.!) hvParamMap) $ hvs

-- | Collect live data from RPC query if enabled.
collectLiveData :: Bool        -- ^ Live queries allowed
                -> ConfigData  -- ^ The cluster config
                -> [String]    -- ^ The requested fields
                -> [Instance]  -- ^ The instance objects
                -> IO [(Instance, Runtime)]
collectLiveData liveDataEnabled cfg fields instances
  | not liveDataEnabled = return . zip instances . repeat . Left .
                            RpcResultError $ "Live data disabled"
  | otherwise = do
      let hvSpecs = getHypervisorSpecs cfg instances
          instanceNodes =
            nub . justOk
                $ map ( maybe (Bad $ ParameterError "no primary node") return
                       . instPrimaryNode
                       >=> getNode cfg) instances
          goodNodes = nodesWithValidConfig cfg instanceNodes
      instInfoRes <- executeRpcCall goodNodes (RpcCallAllInstancesInfo hvSpecs)
      consInfoRes <-
        if "console" `elem` fields
          then case getAllConsoleParams cfg instances of
            Ok  p -> executeRpcCalls $ consoleParamsToCalls p
            Bad _ -> return . zip goodNodes . repeat . Left $
              RpcResultError "Cannot construct parameters for console info call"
          else return [] -- The information is not necessary
      return . zip instances .
        map (extractLiveInfo instInfoRes consInfoRes) $ instances

-- | An aggregate disk attribute for backward compatibility.
getDiskTemplate :: ConfigData -> Instance -> ResultEntry
getDiskTemplate cfg inst =
  let disks = getInstDisksFromObj cfg inst
      getDt x = lidDiskType <$> diskLogicalId x
      disk_types :: ErrorResult [DiskTemplate]
      disk_types = nub <$> catMaybes <$> map getDt <$> disks
      mix :: [DiskTemplate] -> J.JSValue
      mix []  = J.showJSON C.dtDiskless
      mix [t] = J.showJSON t
      mix _   = J.showJSON C.dtMixed
  in case mix <$> disk_types of
       Ok t -> rsNormal t
       Bad _ -> rsNoData
