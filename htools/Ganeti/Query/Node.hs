{-| Implementation of the Ganeti Query2 node queries.

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

module Ganeti.Query.Node
  ( NodeRuntime
  , nodeFieldsMap
  ) where

import Control.Applicative
import Data.List
import qualified Data.Map as Map
import qualified Text.JSON as J

import Ganeti.Config
import Ganeti.Objects
import Ganeti.JSON
import Ganeti.Rpc
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types

-- | NodeRuntime is the resulting type for NodeInfo call.
type NodeRuntime = Either RpcError RpcResultNodeInfo

-- | List of node live fields.
nodeLiveFieldsDefs :: [(FieldName, FieldTitle, FieldType, String, FieldDoc)]
nodeLiveFieldsDefs =
  [ ("bootid", "BootID", QFTText, "bootid",
     "Random UUID renewed for each system reboot, can be used\
     \ for detecting reboots by tracking changes")
  , ("cnodes", "CNodes", QFTNumber, "cpu_nodes",
     "Number of NUMA domains on node (if exported by hypervisor)")
  , ("csockets", "CSockets", QFTNumber, "cpu_sockets",
     "Number of physical CPU sockets (if exported by hypervisor)")
  , ("ctotal", "CTotal", QFTNumber, "cpu_total",
     "Number of logical processors")
  , ("dfree", "DFree", QFTUnit, "vg_free",
     "Available disk space in volume group")
  , ("dtotal", "DTotal", QFTUnit, "vg_size",
     "Total disk space in volume group used for instance disk allocation")
  , ("mfree", "MFree", QFTUnit, "memory_free",
     "Memory available for instance allocations")
  , ("mnode", "MNode", QFTUnit, "memory_dom0",
     "Amount of memory used by node (dom0 for Xen)")
  , ("mtotal", "MTotal", QFTUnit, "memory_total",
     "Total amount of memory of physical machine")
  ]

-- | Map each name to a function that extracts that value from
-- the RPC result.
nodeLiveFieldExtract :: FieldName -> RpcResultNodeInfo -> J.JSValue
nodeLiveFieldExtract "bootid" res =
  J.showJSON $ rpcResNodeInfoBootId res
nodeLiveFieldExtract "cnodes" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuNodes
nodeLiveFieldExtract "csockets" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuSockets
nodeLiveFieldExtract "ctotal" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoCpuTotal
nodeLiveFieldExtract "dfree" res =
  jsonHead (rpcResNodeInfoVgInfo res) vgInfoVgFree
nodeLiveFieldExtract "dtotal" res =
  jsonHead (rpcResNodeInfoVgInfo res) vgInfoVgSize
nodeLiveFieldExtract "mfree" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoMemoryFree
nodeLiveFieldExtract "mnode" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoMemoryDom0
nodeLiveFieldExtract "mtotal" res =
  jsonHead (rpcResNodeInfoHvInfo res) hvInfoMemoryTotal
nodeLiveFieldExtract _ _ = J.JSNull

-- | Helper for extracting field from RPC result.
nodeLiveRpcCall :: FieldName -> NodeRuntime -> Node -> ResultEntry
nodeLiveRpcCall fname (Right res) _ =
  case nodeLiveFieldExtract fname res of
    J.JSNull -> rsNoData
    x -> rsNormal x
nodeLiveRpcCall _ (Left err) _ =
    ResultEntry (rpcErrorToStatus err) Nothing

-- | Builder for node live fields.
nodeLiveFieldBuilder :: (FieldName, FieldTitle, FieldType, String, FieldDoc)
                     -> FieldData Node NodeRuntime
nodeLiveFieldBuilder (fname, ftitle, ftype, _, fdoc) =
  ( FieldDefinition fname ftitle ftype fdoc
  , FieldRuntime $ nodeLiveRpcCall fname)

-- | The docstring for the node role. Note that we use 'reverse in
-- order to keep the same order as Python.
nodeRoleDoc :: String
nodeRoleDoc =
  "Node role; " ++
  intercalate ", "
   (map (\role ->
          "\"" ++ nodeRoleToRaw role ++ "\" for " ++ roleDescription role)
   (reverse [minBound..maxBound]))

-- | List of all node fields.
nodeFields :: FieldList Node NodeRuntime
nodeFields =
  [ (FieldDefinition "drained" "Drained" QFTBool "Whether node is drained",
     FieldSimple (rsNormal . nodeDrained))
  , (FieldDefinition "master_candidate" "MasterC" QFTBool
       "Whether node is a master candidate",
     FieldSimple (rsNormal . nodeMasterCandidate))
  , (FieldDefinition "master_capable" "MasterCapable" QFTBool
       "Whether node can become a master candidate",
     FieldSimple (rsNormal . nodeMasterCapable))
  , (FieldDefinition "name" "Node" QFTText "Node name",
     FieldSimple (rsNormal . nodeName))
  , (FieldDefinition "offline" "Offline" QFTBool
       "Whether node is marked offline",
     FieldSimple (rsNormal . nodeOffline))
  , (FieldDefinition "vm_capable" "VMCapable" QFTBool
       "Whether node can host instances",
     FieldSimple (rsNormal . nodeVmCapable))
  , (FieldDefinition "pip" "PrimaryIP" QFTText "Primary IP address",
     FieldSimple (rsNormal . nodePrimaryIp))
  , (FieldDefinition "sip" "SecondaryIP" QFTText "Secondary IP address",
     FieldSimple (rsNormal . nodeSecondaryIp))
  , (FieldDefinition "master" "IsMaster" QFTBool "Whether node is master",
     FieldConfig (\cfg node ->
                    rsNormal (nodeName node ==
                              clusterMasterNode (configCluster cfg))))
  , (FieldDefinition "group" "Group" QFTText "Node group",
     FieldConfig (\cfg node ->
                    rsMaybe (groupName <$> getGroupOfNode cfg node)))
  , (FieldDefinition "group.uuid" "GroupUUID" QFTText "UUID of node group",
     FieldSimple (rsNormal . nodeGroup))
  ,  (FieldDefinition "ndparams" "NodeParameters" QFTOther
        "Merged node parameters",
      FieldConfig ((rsMaybe .) . getNodeNdParams))
  , (FieldDefinition "custom_ndparams" "CustomNodeParameters" QFTOther
                       "Custom node parameters",
     FieldSimple (rsNormal . nodeNdparams))
  -- FIXME: the below could be generalised a bit, like in Python
  , (FieldDefinition "pinst_cnt" "Pinst" QFTNumber
       "Number of instances with this node as primary",
     FieldConfig (\cfg ->
                    rsNormal . length . fst . getNodeInstances cfg . nodeName))
  , (FieldDefinition "sinst_cnt" "Sinst" QFTNumber
       "Number of instances with this node as secondary",
     FieldConfig (\cfg ->
                    rsNormal . length . snd . getNodeInstances cfg . nodeName))
  , (FieldDefinition "pinst_list" "PriInstances" QFTOther
       "List of instances with this node as primary",
     FieldConfig (\cfg -> rsNormal . map instName . fst .
                          getNodeInstances cfg . nodeName))
  , (FieldDefinition "sinst_list" "SecInstances" QFTOther
       "List of instances with this node as secondary",
     FieldConfig (\cfg -> rsNormal . map instName . snd .
                          getNodeInstances cfg . nodeName))
  , (FieldDefinition "role" "Role" QFTText nodeRoleDoc,
     FieldConfig ((rsNormal .) . getNodeRole))
  -- FIXME: the powered state is special (has an different context,
  -- not runtime) in Python
  , (FieldDefinition "powered" "Powered" QFTBool
       "Whether node is thought to be powered on",
     missingRuntime)
  -- FIXME: the two fields below are incomplete in Python, part of the
  -- non-implemented node resource model; they are declared just for
  -- parity, but are not functional
  , (FieldDefinition "hv_state" "HypervisorState" QFTOther "Hypervisor state",
     missingRuntime)
  , (FieldDefinition "disk_state" "DiskState" QFTOther "Disk state",
     missingRuntime)
  ] ++
  map nodeLiveFieldBuilder nodeLiveFieldsDefs ++
  map buildNdParamField allNDParamFields ++
  timeStampFields ++
  uuidFields "Node" ++
  serialFields "Node" ++
  tagsFields

-- | The node fields map.
nodeFieldsMap :: FieldMap Node NodeRuntime
nodeFieldsMap = Map.fromList $ map (\v -> (fdefName (fst v), v)) nodeFields
