{-| Implementation of the Ganeti Query2 node queries.

 -}

{-

Copyright (C) 2012, 2013 Google Inc.
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

module Ganeti.Query.Node
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import Control.Applicative
import Data.List
import Data.Maybe
import qualified Text.JSON as J

import Ganeti.Config
import Ganeti.Common
import Ganeti.Objects
import Ganeti.JSON (jsonHead)
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
   (map (\nrole ->
          "\"" ++ nodeRoleToRaw nrole ++ "\" for " ++ roleDescription nrole)
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
                    rsNormal (uuidOf node ==
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
     FieldConfig (\cfg -> rsNormal . getNumInstances fst cfg), QffNormal)
  , (FieldDefinition "sinst_cnt" "Sinst" QFTNumber
       "Number of instances with this node as secondary",
     FieldConfig (\cfg -> rsNormal . getNumInstances snd cfg), QffNormal)
  , (FieldDefinition "pinst_list" "PriInstances" QFTOther
       "List of instances with this node as primary",
     FieldConfig (\cfg -> rsNormal . niceSort . mapMaybe instName . fst .
                          getNodeInstances cfg . uuidOf), QffNormal)
  , (FieldDefinition "sinst_list" "SecInstances" QFTOther
       "List of instances with this node as secondary",
     FieldConfig (\cfg -> rsNormal . niceSort . mapMaybe instName . snd .
                          getNodeInstances cfg . uuidOf), QffNormal)
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

-- | Helper function to retrieve the number of (primary or secondary) instances
getNumInstances :: (([Instance], [Instance]) -> [Instance])
                -> ConfigData -> Node -> Int
getNumInstances get_fn cfg = length . get_fn . getNodeInstances cfg . uuidOf

-- | The node fields map.
fieldsMap :: FieldMap Node Runtime
fieldsMap = fieldListToFieldMap nodeFields

-- | Create an RPC result for a broken node
rpcResultNodeBroken :: Node -> (Node, Runtime)
rpcResultNodeBroken node = (node, Left (RpcResultError "Broken configuration"))

-- | Storage-related query fields
storageFields :: [String]
storageFields = ["dtotal", "dfree", "spfree", "sptotal"]

-- | Hypervisor-related query fields
hypervisorFields :: [String]
hypervisorFields = ["mnode", "mfree", "mtotal",
                    "cnodes", "csockets", "cnos", "ctotal"]

-- | Check if it is required to include domain-specific entities (for example
-- storage units for storage info, hypervisor specs for hypervisor info)
-- in the node_info call
queryDomainRequired :: -- domain-specific fields to look for (storage, hv)
                      [String]
                      -- list of requested fields
                   -> [String]
                   -> Bool
queryDomainRequired domain_fields fields = any (`elem` fields) domain_fields

-- | Collect live data from RPC query if enabled.
collectLiveData :: Bool
                -> ConfigData
                -> [String]
                -> [Node]
                -> IO [(Node, Runtime)]
collectLiveData False _ _ nodes =
  return $ zip nodes (repeat $ Left (RpcResultError "Live data disabled"))
collectLiveData True cfg fields nodes = do
  let hvs = [getDefaultHypervisorSpec cfg |
             queryDomainRequired hypervisorFields fields]
      good_nodes = nodesWithValidConfig cfg nodes
      storage_units n = if queryDomainRequired storageFields fields
                        then getStorageUnitsOfNode cfg n
                        else []
  rpcres <- executeRpcCalls
      [(n, RpcCallNodeInfo (storage_units n) hvs) | n <- good_nodes]
  return $ fillUpList (fillPairFromMaybe rpcResultNodeBroken pickPairUnique)
      nodes rpcres
