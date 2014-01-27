{-| Implementation of the Ganeti Query2 node queries.

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

module Ganeti.Query.Node
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import Control.Applicative
import Data.List
import Data.Maybe
import qualified Data.Map as Map
import qualified Text.JSON as J

import Ganeti.Config
import Ganeti.Common
import Ganeti.Objects
import Ganeti.JSON
import Ganeti.Rpc
import Ganeti.Types
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types
import Ganeti.Storage.Utils
import Ganeti.Utils (niceSort)

-- | Runtime is the resulting type for NodeInfo call.
type Runtime = Either RpcError RpcResultNodeInfo

-- | List of node live fields.
nodeLiveFieldsDefs :: [(FieldName, FieldTitle, FieldType, String, FieldDoc)]
nodeLiveFieldsDefs =
  [ ("bootid", "BootID", QFTText, "bootid",
     "Random UUID renewed for each system reboot, can be used\
     \ for detecting reboots by tracking changes")
  , ("cnodes", "CNodes", QFTNumber, "cpu_nodes",
     "Number of NUMA domains on node (if exported by hypervisor)")
  , ("cnos", "CNOs", QFTNumber, "cpu_dom0",
     "Number of logical processors used by the node OS (dom0 for Xen)")
  , ("csockets", "CSockets", QFTNumber, "cpu_sockets",
     "Number of physical CPU sockets (if exported by hypervisor)")
  , ("ctotal", "CTotal", QFTNumber, "cpu_total",
     "Number of logical processors")
  , ("dfree", "DFree", QFTUnit, "storage_free",
     "Available storage space on storage unit")
  , ("dtotal", "DTotal", QFTUnit, "storage_size",
     "Total storage space on storage unit for instance disk allocation")
  , ("spfree", "SpFree", QFTNumber, "spindles_free",
     "Available spindles in volume group (exclusive storage only)")
  , ("sptotal", "SpTotal", QFTNumber, "spindles_total",
     "Total spindles in volume group (exclusive storage only)")
  , ("mfree", "MFree", QFTUnit, "memory_free",
     "Memory available for instance allocations")
  , ("mnode", "MNode", QFTUnit, "memory_dom0",
     "Amount of memory used by node (dom0 for Xen)")
  , ("mtotal", "MTotal", QFTUnit, "memory_total",
     "Total amount of memory of physical machine")
  ]

-- | Helper function to extract an attribute from a maybe StorageType
getAttrFromStorageInfo :: (J.JSON a) => (StorageInfo -> Maybe a)
                       -> Maybe StorageInfo -> J.JSValue
getAttrFromStorageInfo attr_fn (Just info) =
  case attr_fn info of
    Just val -> J.showJSON val
    Nothing -> J.JSNull
getAttrFromStorageInfo _ Nothing = J.JSNull

-- | Check whether the given storage info fits to the given storage type
isStorageInfoOfType :: StorageType -> StorageInfo -> Bool
isStorageInfoOfType stype sinfo = storageInfoType sinfo ==
    storageTypeToRaw stype

-- | Get storage info for the default storage unit
getStorageInfoForDefault :: [StorageInfo] -> Maybe StorageInfo
getStorageInfoForDefault sinfos = listToMaybe $ filter
    (not . isStorageInfoOfType StorageLvmPv) sinfos

-- | Gets the storage info for a storage type
-- FIXME: This needs to be extended when storage pools are implemented,
-- because storage types are not necessarily unique then
getStorageInfoForType :: [StorageInfo] -> StorageType -> Maybe StorageInfo
getStorageInfoForType sinfos stype = listToMaybe $ filter
    (isStorageInfoOfType stype) sinfos

-- | Map each name to a function that extracts that value from
-- the RPC result.
nodeLiveFieldExtract :: FieldName -> RpcResultNodeInfo -> J.JSValue
nodeLiveFieldExtract "bootid" res =
  J.showJSON $ rpcResNodeInfoBootId res
nodeLiveFieldExtract "cnodes" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuNodes
nodeLiveFieldExtract "cnos" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuDom0
nodeLiveFieldExtract "csockets" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuSockets
nodeLiveFieldExtract "ctotal" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuTotal
nodeLiveFieldExtract "dfree" res =
  getAttrFromStorageInfo storageInfoStorageFree (getStorageInfoForDefault
      (rpcResNodeInfoStorageInfo res))
nodeLiveFieldExtract "dtotal" res =
  getAttrFromStorageInfo storageInfoStorageSize (getStorageInfoForDefault
      (rpcResNodeInfoStorageInfo res))
nodeLiveFieldExtract "spfree" res =
  getAttrFromStorageInfo storageInfoStorageFree (getStorageInfoForType
      (rpcResNodeInfoStorageInfo res) StorageLvmPv)
nodeLiveFieldExtract "sptotal" res =
  getAttrFromStorageInfo storageInfoStorageSize (getStorageInfoForType
      (rpcResNodeInfoStorageInfo res) StorageLvmPv)
nodeLiveFieldExtract "mfree" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoMemoryFree
nodeLiveFieldExtract "mnode" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoMemoryDom0
nodeLiveFieldExtract "mtotal" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoMemoryTotal
nodeLiveFieldExtract _ _ = J.JSNull

-- | Helper for extracting field from RPC result.
nodeLiveRpcCall :: FieldName -> Runtime -> Node -> ResultEntry
nodeLiveRpcCall fname (Right res) _ =
  case nodeLiveFieldExtract fname res of
    J.JSNull -> rsNoData
    x -> rsNormal x
nodeLiveRpcCall _ (Left err) _ =
    ResultEntry (rpcErrorToStatus err) Nothing

-- | Builder for node live fields.
nodeLiveFieldBuilder :: (FieldName, FieldTitle, FieldType, String, FieldDoc)
                     -> FieldData Node Runtime
nodeLiveFieldBuilder (fname, ftitle, ftype, _, fdoc) =
  ( FieldDefinition fname ftitle ftype fdoc
  , FieldRuntime $ nodeLiveRpcCall fname
  , QffNormal)

-- | The docstring for the node role. Note that we use 'reverse' in
-- order to keep the same order as Python.
nodeRoleDoc :: String
nodeRoleDoc =
  "Node role; " ++
  intercalate ", "
   (map (\role ->
          "\"" ++ nodeRoleToRaw role ++ "\" for " ++ roleDescription role)
   (reverse [minBound..maxBound]))

-- | Get node powered status.
getNodePower :: ConfigData -> Node -> ResultEntry
getNodePower cfg node =
  case getNodeNdParams cfg node of
    Nothing -> rsNoData
    Just ndp -> if null (ndpOobProgram ndp)
                  then rsUnavail
                  else rsNormal (nodePowered node)

-- | List of all node fields.
nodeFields :: FieldList Node Runtime
nodeFields =
  [ (FieldDefinition "drained" "Drained" QFTBool "Whether node is drained",
     FieldSimple (rsNormal . nodeDrained), QffNormal)
  , (FieldDefinition "master_candidate" "MasterC" QFTBool
       "Whether node is a master candidate",
     FieldSimple (rsNormal . nodeMasterCandidate), QffNormal)
  , (FieldDefinition "master_capable" "MasterCapable" QFTBool
       "Whether node can become a master candidate",
     FieldSimple (rsNormal . nodeMasterCapable), QffNormal)
  , (FieldDefinition "name" "Node" QFTText "Node name",
     FieldSimple (rsNormal . nodeName), QffHostname)
  , (FieldDefinition "offline" "Offline" QFTBool
       "Whether node is marked offline",
     FieldSimple (rsNormal . nodeOffline), QffNormal)
  , (FieldDefinition "vm_capable" "VMCapable" QFTBool
       "Whether node can host instances",
     FieldSimple (rsNormal . nodeVmCapable), QffNormal)
  , (FieldDefinition "pip" "PrimaryIP" QFTText "Primary IP address",
     FieldSimple (rsNormal . nodePrimaryIp), QffNormal)
  , (FieldDefinition "sip" "SecondaryIP" QFTText "Secondary IP address",
     FieldSimple (rsNormal . nodeSecondaryIp), QffNormal)
  , (FieldDefinition "master" "IsMaster" QFTBool "Whether node is master",
     FieldConfig (\cfg node ->
                    rsNormal (nodeUuid node ==
                              clusterMasterNode (configCluster cfg))),
     QffNormal)
  , (FieldDefinition "group" "Group" QFTText "Node group",
     FieldConfig (\cfg node ->
                    rsMaybeNoData (groupName <$> getGroupOfNode cfg node)),
     QffNormal)
  , (FieldDefinition "group.uuid" "GroupUUID" QFTText "UUID of node group",
     FieldSimple (rsNormal . nodeGroup), QffNormal)
  ,  (FieldDefinition "ndparams" "NodeParameters" QFTOther
        "Merged node parameters",
      FieldConfig ((rsMaybeNoData .) . getNodeNdParams), QffNormal)
  , (FieldDefinition "custom_ndparams" "CustomNodeParameters" QFTOther
                       "Custom node parameters",
     FieldSimple (rsNormal . nodeNdparams), QffNormal)
  -- FIXME: the below could be generalised a bit, like in Python
  , (FieldDefinition "pinst_cnt" "Pinst" QFTNumber
       "Number of instances with this node as primary",
     FieldConfig (\cfg ->
                    rsNormal . length . fst . getNodeInstances cfg . nodeUuid),
     QffNormal)
  , (FieldDefinition "sinst_cnt" "Sinst" QFTNumber
       "Number of instances with this node as secondary",
     FieldConfig (\cfg ->
                    rsNormal . length . snd . getNodeInstances cfg . nodeUuid),
     QffNormal)
  , (FieldDefinition "pinst_list" "PriInstances" QFTOther
       "List of instances with this node as primary",
     FieldConfig (\cfg -> rsNormal . niceSort . map instName . fst .
                          getNodeInstances cfg . nodeUuid), QffNormal)
  , (FieldDefinition "sinst_list" "SecInstances" QFTOther
       "List of instances with this node as secondary",
     FieldConfig (\cfg -> rsNormal . niceSort . map instName . snd .
                          getNodeInstances cfg . nodeUuid), QffNormal)
  , (FieldDefinition "role" "Role" QFTText nodeRoleDoc,
     FieldConfig ((rsNormal .) . getNodeRole), QffNormal)
  , (FieldDefinition "powered" "Powered" QFTBool
       "Whether node is thought to be powered on",
     FieldConfig getNodePower, QffNormal)
  -- FIXME: the two fields below are incomplete in Python, part of the
  -- non-implemented node resource model; they are declared just for
  -- parity, but are not functional
  , (FieldDefinition "hv_state" "HypervisorState" QFTOther "Hypervisor state",
     FieldSimple (const rsUnavail), QffNormal)
  , (FieldDefinition "disk_state" "DiskState" QFTOther "Disk state",
     FieldSimple (const rsUnavail), QffNormal)
  ] ++
  map nodeLiveFieldBuilder nodeLiveFieldsDefs ++
  map buildNdParamField allNDParamFields ++
  timeStampFields ++
  uuidFields "Node" ++
  serialFields "Node" ++
  tagsFields

-- | The node fields map.
fieldsMap :: FieldMap Node Runtime
fieldsMap =
  Map.fromList $ map (\v@(f, _, _) -> (fdefName f, v)) nodeFields

-- | Create an RPC result for a broken node
rpcResultNodeBroken :: Node -> (Node, Runtime)
rpcResultNodeBroken node = (node, Left (RpcResultError "Broken configuration"))

-- | Collect live data from RPC query if enabled.
--
-- FIXME: Check which fields we actually need and possibly send empty
-- hvs\/vgs if no info from hypervisor\/volume group respectively is
-- required
collectLiveData:: Bool -> ConfigData -> [Node] -> IO [(Node, Runtime)]
collectLiveData False _ nodes =
  return $ zip nodes (repeat $ Left (RpcResultError "Live data disabled"))
collectLiveData True cfg nodes = do
  let hvs = [getDefaultHypervisorSpec cfg]
      good_nodes = nodesWithValidConfig cfg nodes
      -- FIXME: use storage units from calling code
      storage_units = getStorageUnitsOfNodes cfg good_nodes
  rpcres <- executeRpcCall good_nodes (RpcCallNodeInfo storage_units hvs)
  return $ fillUpList (fillPairFromMaybe rpcResultNodeBroken pickPairUnique)
      nodes rpcres

-- | Looks up the default hypervisor and it's hvparams
getDefaultHypervisorSpec :: ConfigData -> (Hypervisor, HvParams)
getDefaultHypervisorSpec cfg = (hv, getHvParamsFromCluster cfg hv)
  where hv = getDefaultHypervisor cfg

-- | Looks up the cluster's hvparams of the given hypervisor
getHvParamsFromCluster :: ConfigData -> Hypervisor -> HvParams
getHvParamsFromCluster cfg hv =
  fromMaybe (GenericContainer (Map.fromList []))
    (Map.lookup (hypervisorToRaw hv)
       (fromContainer (clusterHvparams (configCluster cfg))))
