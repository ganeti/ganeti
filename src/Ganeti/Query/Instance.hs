{-| Implementation of the Ganeti Query2 instance queries.

-}

{-

Copyright (C) 2013 Google Inc.

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

module Ganeti.Query.Instance
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import Control.Applicative
import Data.List
import Data.Maybe
import Data.Monoid
import qualified Data.Map as Map
import qualified Text.JSON as J
import Text.Printf

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.Config
import qualified Ganeti.Constants as C
import qualified Ganeti.ConstantUtils as C
import Ganeti.Errors
import Ganeti.JSON
import Ganeti.Objects
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types
import Ganeti.Rpc
import Ganeti.Storage.Utils
import Ganeti.Types
import Ganeti.Utils (formatOrdinal)

-- | The LiveInfo structure packs additional information beside the
-- 'InstanceInfo'. We also need to know whether the instance information was
-- found on the primary node, and encode this as a Bool.
type LiveInfo = (InstanceInfo, Bool)

-- | Runtime possibly containing the 'LiveInfo'. See the genericQuery function
-- in the Query.hs file for an explanation of the terms used.
type Runtime = Either RpcError (Maybe LiveInfo)

-- | The instance fields map.
fieldsMap :: FieldMap Instance Runtime
fieldsMap = Map.fromList [(fdefName f, v) | v@(f, _, _) <- instanceFields]

-- | The instance fields
instanceFields :: FieldList Instance Runtime
instanceFields =
  -- Simple fields
  [ (FieldDefinition "admin_state" "InstanceState" QFTText
     "Desired state of instance",
     FieldSimple (rsNormal . adminStateToRaw . instAdminState), QffNormal)
  , (FieldDefinition "admin_up" "Autostart" QFTBool
     "Desired state of instance",
     FieldSimple (rsNormal . (== AdminUp) . instAdminState), QffNormal)
  , (FieldDefinition "disk_template" "Disk_template" QFTText
     "Instance disk template",
     FieldSimple (rsNormal . instDiskTemplate), QffNormal)
  , (FieldDefinition "disks_active" "DisksActive" QFTBool
     "Desired state of instance disks",
     FieldSimple (rsNormal . instDisksActive), QffNormal)
  , (FieldDefinition "name" "Instance" QFTText
     "Instance name",
     FieldSimple (rsNormal . instName), QffHostname)
  , (FieldDefinition "hypervisor" "Hypervisor" QFTText
     "Hypervisor name",
     FieldSimple (rsNormal . instHypervisor), QffNormal)
  , (FieldDefinition "network_port" "Network_port" QFTOther
     "Instance network port if available (e.g. for VNC console)",
     FieldSimple (rsMaybeUnavail . instNetworkPort), QffNormal)
  , (FieldDefinition "os" "OS" QFTText
     "Operating system",
     FieldSimple (rsNormal . instOs), QffNormal)
  , (FieldDefinition "pnode" "Primary_node" QFTText
     "Primary node",
     FieldConfig getPrimaryNodeName, QffHostname)
  , (FieldDefinition "pnode.group" "PrimaryNodeGroup" QFTText
     "Primary node's group",
     FieldConfig getPrimaryNodeGroup, QffNormal)
  , (FieldDefinition "snodes" "Secondary_Nodes" QFTOther
     "Secondary nodes; usually this will just be one node",
     FieldConfig (getSecondaryNodeAttribute nodeName), QffNormal)
  , (FieldDefinition "snodes.group" "SecondaryNodesGroups" QFTOther
     "Node groups of secondary nodes",
     FieldConfig (getSecondaryNodeGroupAttribute groupName), QffNormal)
  , (FieldDefinition "snodes.group.uuid" "SecondaryNodesGroupsUUID" QFTOther
     "Node group UUIDs of secondary nodes",
     FieldConfig (getSecondaryNodeGroupAttribute groupUuid), QffNormal)
  ] ++

  -- Instance parameter fields, whole
  [ (FieldDefinition "hvparams" "HypervisorParameters" QFTOther
     "Hypervisor parameters (merged)",
     FieldConfig ((rsNormal .) . getFilledInstHvParams), QffNormal)
  , (FieldDefinition "beparams" "BackendParameters" QFTOther
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
  ] ++

  -- Instance parameter fields, generated
  map (buildBeParamField beParamGetter) allBeParamFields ++
  map (buildHvParamField hvParamGetter) (C.toList C.hvsParameters) ++

  -- Aggregate disk parameter fields
  [ (FieldDefinition "disk_usage" "DiskUsage" QFTUnit
     "Total disk space used by instance on each of its nodes; this is not the\
     \ disk size visible to the instance, but the usage on the node",
     FieldSimple (rsNormal . getDiskSizeRequirements), QffNormal)
  , (FieldDefinition "disk.count" "Disks" QFTNumber
     "Number of disks",
     FieldSimple (rsNormal . length . instDisks), QffNormal)
  , (FieldDefinition "disk.sizes" "Disk_sizes" QFTOther
     "List of disk sizes",
     FieldSimple (rsNormal . map diskSize . instDisks), QffNormal)
  , (FieldDefinition "disk.spindles" "Disk_spindles" QFTOther
     "List of disk spindles",
     FieldSimple (rsNormal . map (MaybeForJSON . diskSpindles) .
                  instDisks),
     QffNormal)
  , (FieldDefinition "disk.names" "Disk_names" QFTOther
     "List of disk names",
     FieldSimple (rsNormal . map (MaybeForJSON . diskName) .
                  instDisks),
     QffNormal)
  , (FieldDefinition "disk.uuids" "Disk_UUIDs" QFTOther
     "List of disk UUIDs",
     FieldSimple (rsNormal . map diskUuid . instDisks), QffNormal)
  ] ++

  -- Per-disk parameter fields
  fillNumberFields C.maxDisks
  [ (fieldDefinitionCompleter "disk.size/%d" "Disk/%d" QFTUnit
     "Disk size of %s disk",
     getFillableField instDisks diskSize, QffNormal)
  , (fieldDefinitionCompleter "disk.spindles/%d" "DiskSpindles/%d" QFTNumber
     "Spindles of %s disk",
     getFillableOptionalField instDisks diskSpindles, QffNormal)
  , (fieldDefinitionCompleter "disk.name/%d" "DiskName/%d" QFTText
     "Name of %s disk",
     getFillableOptionalField instDisks diskName, QffNormal)
  , (fieldDefinitionCompleter "disk.uuid/%d" "DiskUUID/%d" QFTText
     "UUID of %s disk",
     getFillableField instDisks diskUuid, QffNormal)
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
     FieldSimple (rsNormal . map nicUuid . instNics), QffNormal)
  , (FieldDefinition "nic.modes" "NIC_modes" QFTOther
     (nicAggDescPrefix ++ "mode"),
     FieldConfig (\cfg -> rsNormal . map
       (nicpMode . fillNicParamsFromConfig cfg . nicNicparams)
       . instNics),
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
       . instNics),
     QffNormal)
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
  fillNumberFields C.maxNics
  [ (fieldDefinitionCompleter "nic.ip/%d" "NicIP/%d" QFTText
     ("IP address" ++ nicDescSuffix),
     getFillableOptionalField instNics nicIp, QffNormal)
  , (fieldDefinitionCompleter "nic.uuid/%d" "NicUUID/%d" QFTText
     ("UUID address" ++ nicDescSuffix),
     getFillableField instNics nicUuid, QffNormal)
  , (fieldDefinitionCompleter "nic.mac/%d" "NicMAC/%d" QFTText
     ("MAC address" ++ nicDescSuffix),
     getFillableField instNics nicMac, QffNormal)
  , (fieldDefinitionCompleter "nic.name/%d" "NicName/%d" QFTText
     ("Name address" ++ nicDescSuffix),
     getFillableOptionalField instNics nicName, QffNormal)
  , (fieldDefinitionCompleter "nic.network/%d" "NicNetwork/%d" QFTText
     ("Network" ++ nicDescSuffix),
     getFillableOptionalField instNics nicNetwork, QffNormal)
  , (fieldDefinitionCompleter "nic.mode/%d" "NicMode/%d" QFTText
     ("Mode" ++ nicDescSuffix),
     getFillableNicField nicpMode, QffNormal)
  , (fieldDefinitionCompleter "nic.link/%d" "NicLink/%d" QFTText
     ("Link" ++ nicDescSuffix),
     getFillableNicField nicpLink, QffNormal)
  , (fieldDefinitionCompleter "nic.network.name/%d" "NicNetworkName/%d" QFTText
     ("Network name" ++ nicDescSuffix),
     getFillableNicNetworkNameField, QffNormal)
  , (fieldDefinitionCompleter "nic.bridge/%d" "NicBridge/%d" QFTText
     ("Bridge" ++ nicDescSuffix),
     getOptionalFillableNicField getNicBridge, QffNormal)
  ] ++

  -- Live fields using special getters
  [ (FieldDefinition "status" "Status" QFTText
     statusDocText,
     FieldConfigRuntime statusExtract, QffNormal)
  , (FieldDefinition "oper_state" "Running" QFTBool
     "Actual state of instance",
     FieldRuntime operStatusExtract, QffNormal)
  ] ++

  -- Simple live fields
  map instanceLiveFieldBuilder instanceLiveFieldsDefs ++

  -- Generated fields
  serialFields "Instance" ++
  uuidFields "Instance" ++
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

-- | Gets the bridge of a NIC.
getNicBridge :: FilledNicParams -> Maybe String
getNicBridge nicParams
  | nicpMode nicParams == NMBridged = Just $ nicpLink nicParams
  | otherwise                       = Nothing

-- | Fill partial NIC params by using the defaults from the configuration.
fillNicParamsFromConfig :: ConfigData -> PartialNicParams -> FilledNicParams
fillNicParamsFromConfig cfg = fillNicParams (getDefaultNicParams cfg)

-- | Retrieves the default network interface parameters.
getDefaultNicParams :: ConfigData -> FilledNicParams
getDefaultNicParams cfg =
  (Map.!) (fromContainer . clusterNicparams . configCluster $ cfg) C.ppDefault

-- | Returns a field that retrieves a given NIC's network name.
getFillableNicNetworkNameField :: Int -> FieldGetter Instance Runtime
getFillableNicNetworkNameField index =
  FieldConfig (\cfg inst -> rsMaybeUnavail $ do
    nicObj <- maybeAt index $ instNics inst
    nicNetworkId <- nicNetwork nicObj
    return $ getNetworkName cfg nicNetworkId)

-- | Gets a fillable NIC field.
getFillableNicField :: (J.JSON a)
                    => (FilledNicParams -> a)
                    -> Int
                    -> FieldGetter Instance Runtime
getFillableNicField getter =
  getOptionalFillableNicField (\x -> Just . getter $ x)

-- | Gets an optional fillable NIC field.
getOptionalFillableNicField :: (J.JSON a)
                            => (FilledNicParams -> Maybe a)
                            -> Int
                            -> FieldGetter Instance Runtime
getOptionalFillableNicField =
  getFillableFieldWithDefault
    (map nicNicparams . instNics) (\x _ -> getDefaultNicParams x) fillNicParams

-- | Creates a function which produces a 'FieldGetter' when fed an index. Works
-- for fields that should be filled out through the use of a default.
getFillableFieldWithDefault :: (J.JSON c)
  => (Instance -> [a])             -- ^ Extracts a list of incomplete objects
  -> (ConfigData -> Instance -> b) -- ^ Extracts the default object
  -> (b -> a -> b)                 -- ^ Fills the default object
  -> (b -> Maybe c)                -- ^ Extracts an obj property
  -> Int                           -- ^ Index in list to use
  -> FieldGetter Instance Runtime  -- ^ Result
getFillableFieldWithDefault
  listGetter defaultGetter fillFn propertyGetter index =
  FieldConfig (\cfg inst -> rsMaybeUnavail $ do
                              incompleteObj <- maybeAt index $ listGetter inst
                              let defaultObj = defaultGetter cfg inst
                                  completeObj = fillFn defaultObj incompleteObj
                              propertyGetter completeObj)

-- | Creates a function which produces a 'FieldGetter' when fed an index. Works
-- for fields that may not return a value, expressed through the Maybe monad.
getFillableOptionalField :: (J.JSON b)
                         => (Instance -> [a]) -- ^ Extracts a list of objects
                         -> (a -> Maybe b)    -- ^ Possibly gets a property
                                              -- from an object
                         -> Int               -- ^ Index in list to use
                         -> FieldGetter Instance Runtime -- ^ Result
getFillableOptionalField extractor optPropertyGetter index =
  FieldSimple(\inst -> rsMaybeUnavail $ do
                         obj <- maybeAt index $ extractor inst
                         optPropertyGetter obj)

-- | Creates a function which produces a 'FieldGetter' when fed an index.
-- Works only for fields that surely return a value.
getFillableField :: (J.JSON b)
                 => (Instance -> [a]) -- ^ Extracts a list of objects
                 -> (a -> b)          -- ^ Gets a property from an object
                 -> Int               -- ^ Index in list to use
                 -> FieldGetter Instance Runtime -- ^ Result
getFillableField extractor propertyGetter index =
  let optPropertyGetter = Just . propertyGetter
  in getFillableOptionalField extractor optPropertyGetter index

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

-- | Given fields that describe lists, fill their definitions with appropriate
-- index representations.
fillNumberFields :: (Integral t1)
                 => Int
                 -> [(t1 -> String -> FieldDefinition,
                      t1 -> FieldGetter a b,
                      QffMode)]
                 -> FieldList a b
fillNumberFields numFills fieldsToFill = do
  index <- take numFills [0..]
  field <- fieldsToFill
  return . fillIncompleteFields field index . formatOrdinal $ index + 1

-- * Various helper functions for property retrieval

-- | Helper function for primary node retrieval
getPrimaryNode :: ConfigData -> Instance -> ErrorResult Node
getPrimaryNode cfg = getInstPrimaryNode cfg . instName

-- | Get primary node hostname
getPrimaryNodeName :: ConfigData -> Instance -> ResultEntry
getPrimaryNodeName cfg inst =
  rsErrorNoData $ nodeName <$> getPrimaryNode cfg inst

-- | Get primary node hostname
getPrimaryNodeGroup :: ConfigData -> Instance -> ResultEntry
getPrimaryNodeGroup cfg inst =
  rsErrorNoData $ (J.showJSON . groupName) <$>
    (getPrimaryNode cfg inst >>=
    maybeToError "Configuration missing" . getGroupOfNode cfg)

-- | Get secondary nodes - the configuration objects themselves
getSecondaryNodes :: ConfigData -> Instance -> ErrorResult [Node]
getSecondaryNodes cfg inst = do
  pNode <- getPrimaryNode cfg inst
  allNodes <- getInstAllNodes cfg $ instName inst
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
  rsMaybeUnavail . Map.lookup field . fromContainer $
                                        getFilledInstHvParams cfg inst

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

-- | Helper for extracting field from RPC result.
instanceLiveRpcCall :: FieldName -> Runtime -> Instance -> ResultEntry
instanceLiveRpcCall fname (Right (Just (res, _))) inst =
  case instanceLiveFieldExtract fname res inst of
    J.JSNull -> rsNoData
    x        -> rsNormal x
instanceLiveRpcCall _ (Right Nothing) _ = rsUnavail
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
  let pNodeResult = getNode cfg $ instPrimaryNode inst
  in case pNodeResult of
     Ok pNode -> nodeOffline pNode
     Bad    _ -> error "Programmer error - result assumed to be OK is Bad!"

-- | Determines the status of a live instance
liveInstanceStatus :: LiveInfo -> Instance -> InstanceStatus
liveInstanceStatus (_, foundOnPrimary) inst
  | not foundOnPrimary    = WrongNode
  | adminState == AdminUp = Running
  | otherwise             = ErrorUp
  where adminState = instAdminState inst

-- | Determines the status of a dead instance.
deadInstanceStatus :: Instance -> InstanceStatus
deadInstanceStatus inst =
  case instAdminState inst of
    AdminUp      -> ErrorDown
    AdminDown    -> StatusDown
    AdminOffline -> StatusOffline

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
                  Left _                -> NodeDown
                  Right (Just liveData) -> liveInstanceStatus liveData inst
                  Right Nothing         -> deadInstanceStatus inst

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
      Left  _ -> Nothing
      Right x -> Just $ isJust x

-- * Helper functions extracting information as necessary for the generic query
-- interfaces

-- | Finds information about the instance in the info delivered by a node
findInstanceInfo :: Instance
                 -> ERpcError RpcResultAllInstancesInfo
                 -> Maybe InstanceInfo
findInstanceInfo inst nodeResponse =
  case nodeResponse of
    Left  _err    -> Nothing
    Right allInfo ->
      let instances = rpcResAllInstInfoInstances allInfo
          maybeMatch = pickPairUnique (instName inst) instances
      in snd <$> maybeMatch

-- | Finds the node information ('RPCResultError') or the instance information
-- (Maybe 'LiveInfo').
extractLiveInfo :: [(Node, ERpcError RpcResultAllInstancesInfo)]
                -> Instance
                -> Runtime
extractLiveInfo nodeResultList inst =
  let uuidResultList = [(nodeUuid x, y) | (x, y) <- nodeResultList]
      pNodeUuid = instPrimaryNode inst
      maybeRPCError = getNodeStatus uuidResultList pNodeUuid
  in case maybeRPCError of
       Just err -> Left err
       Nothing  -> Right $ getInstanceStatus uuidResultList pNodeUuid inst

-- | Tries to find out if the node given by the uuid is bad - unreachable or
-- returning errors, does not mather for the purpose of this call.
getNodeStatus :: [(String, ERpcError RpcResultAllInstancesInfo)]
              -> String
              -> Maybe RpcError
getNodeStatus uuidList uuid =
  case snd <$> pickPairUnique uuid uuidList of
    Just (Left err) -> Just err
    Just (Right _)  -> Nothing
    Nothing         -> Just . RpcResultError $
                         "Primary node response not present"

-- | Retrieves the instance information if it is present anywhere in the all
-- instances RPC result. Notes if it originates from the primary node.
-- All nodes are represented as UUID's for ease of use.
getInstanceStatus :: [(String, ERpcError RpcResultAllInstancesInfo)]
                  -> String
                  -> Instance
                  -> Maybe LiveInfo
getInstanceStatus uuidList pNodeUuid inst =
  let primarySearchResult =
        snd <$> pickPairUnique pNodeUuid uuidList >>= findInstanceInfo inst
  in case primarySearchResult of
       Just instInfo -> Just (instInfo, True)
       Nothing       ->
         let allSearchResult =
               getFirst . mconcat $ map
               (First . findInstanceInfo inst . snd) uuidList
         in case allSearchResult of
              Just liveInfo -> Just (liveInfo, False)
              Nothing       -> Nothing

-- | Collect live data from RPC query if enabled.
collectLiveData :: Bool -> ConfigData -> [Instance] -> IO [(Instance, Runtime)]
collectLiveData liveDataEnabled cfg instances
  | not liveDataEnabled = return . zip instances . repeat . Left .
                            RpcResultError $ "Live data disabled"
  | otherwise = do
      let hvSpec = getDefaultHypervisorSpec cfg
          instance_nodes = nub . justOk $
                             map (getNode cfg . instPrimaryNode) instances
          good_nodes = nodesWithValidConfig cfg instance_nodes
      rpcres <- executeRpcCall good_nodes $ RpcCallAllInstancesInfo [hvSpec]
      return . zip instances . map (extractLiveInfo rpcres) $ instances
