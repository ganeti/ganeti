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

import Ganeti.BasicTypes
import Ganeti.Common
import Ganeti.Config
import Ganeti.Objects
import Ganeti.Query.Common
import Ganeti.Query.Language
import Ganeti.Query.Types
import Ganeti.Rpc
import Ganeti.Storage.Utils
import Ganeti.Types

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
  [ (FieldDefinition "disk_template" "Disk_template" QFTText
     "Instance disk template",
     FieldSimple (rsNormal . instDiskTemplate), QffNormal)
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


-- Functionality related to status and operational status extraction

-- | The documentation text for the instance status field
statusDocText :: String
statusDocText =
  let si = show . instanceStatusToRaw :: InstanceStatus -> String
  in "Instance status; " ++
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
  let pNode = optimisticUnwrapper . getNode cfg $ instPrimaryNode inst
  in nodeOffline pNode

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
-- | to communicate with its primary node, on which node it is, and its
-- | configuration.
determineInstanceStatus :: ConfigData -- ^ The configuration data
                        -> Runtime    -- ^ All the data from the live call
                        -> Instance   -- ^ The static instance configuration
                        -> InstanceStatus -- ^ Result
determineInstanceStatus cfg res inst =
  if isPrimaryOffline cfg inst
    then NodeOffline
    else case res of
      Left _                -> NodeDown
      Right (Just liveData) -> liveInstanceStatus liveData inst
      Right Nothing         -> deadInstanceStatus inst

-- | Extracts the status, doing necessary transformations but once
statusExtract :: ConfigData -> Runtime -> Instance -> ResultEntry
statusExtract cfg res inst =
  rsNormal . J.showJSON . instanceStatusToRaw $
    determineInstanceStatus cfg res inst

-- | Extracts the operational status
operStatusExtract :: Runtime -> Instance -> ResultEntry
operStatusExtract res _ =
  rsMaybeNoData $ J.showJSON <$> case res of
    Left _  -> Nothing
    Right x -> Just $ isJust x


-- Helper functions extracting information as necessary for the generic query
-- interfaces

-- | A function removing the GenericResult wrapper from assuredly OK values
optimisticUnwrapper :: GenericResult a b -> b
optimisticUnwrapper (Ok x) = x
optimisticUnwrapper (Bad _) = error "Programmer error: assumptions are wrong!"

-- | Simple filter of OK results only
okNodesOnly :: [GenericResult a Node] -> [Node]
okNodesOnly = map optimisticUnwrapper . filter isOk

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
          instance_nodes = nub . okNodesOnly $
                             map (getNode cfg . instPrimaryNode) instances
          good_nodes = nodesWithValidConfig cfg instance_nodes
      rpcres <- executeRpcCall good_nodes $ RpcCallAllInstancesInfo [hvSpec]
      return . zip instances . map (extractLiveInfo rpcres) $ instances
