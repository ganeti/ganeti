{-| Implementation of the Ganeti Query2 node group queries.

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

module Ganeti.Query.Group
  ( Runtime
  , fieldsMap
  , collectLiveData
  ) where

import qualified Data.Map as Map

import Ganeti.Config
import Ganeti.Objects
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types

-- | There is no runtime.
data Runtime = Runtime

groupFields :: FieldList NodeGroup Runtime
groupFields =
  [ (FieldDefinition "alloc_policy" "AllocPolicy" QFTText
       "Allocation policy for group",
     FieldSimple (rsNormal . groupAllocPolicy), QffNormal)
  , (FieldDefinition "custom_diskparams" "CustomDiskParameters" QFTOther
       "Custom disk parameters",
     FieldSimple (rsNormal . groupDiskparams), QffNormal)
  , (FieldDefinition "custom_ipolicy" "CustomInstancePolicy" QFTOther
       "Custom instance policy limitations",
     FieldSimple (rsNormal . groupIpolicy), QffNormal)
  , (FieldDefinition "custom_ndparams" "CustomNDParams" QFTOther
       "Custom node parameters",
     FieldSimple (rsNormal . groupNdparams), QffNormal)
  , (FieldDefinition "diskparams" "DiskParameters" QFTOther
       "Disk parameters (merged)",
     FieldConfig (\cfg -> rsNormal . getGroupDiskParams cfg), QffNormal)
  , (FieldDefinition "ipolicy" "InstancePolicy" QFTOther
       "Instance policy limitations (merged)",
     FieldConfig (\cfg ng -> rsNormal (getGroupIpolicy cfg ng)), QffNormal)
  , (FieldDefinition "name" "Group" QFTText "Group name",
     FieldSimple (rsNormal . groupName), QffNormal)
  , (FieldDefinition "ndparams" "NDParams" QFTOther "Node parameters",
     FieldConfig (\cfg ng -> rsNormal (getGroupNdParams cfg ng)), QffNormal)
  , (FieldDefinition "node_cnt" "Nodes" QFTNumber "Number of nodes",
     FieldConfig (\cfg -> rsNormal . length . getGroupNodes cfg . groupName),
     QffNormal)
  , (FieldDefinition "node_list" "NodeList" QFTOther "List of nodes",
     FieldConfig (\cfg -> rsNormal . map nodeName .
                          getGroupNodes cfg . groupName), QffNormal)
  , (FieldDefinition "pinst_cnt" "Instances" QFTNumber
       "Number of primary instances",
     FieldConfig
       (\cfg -> rsNormal . length . fst . getGroupInstances cfg . groupName),
     QffNormal)
  , (FieldDefinition "pinst_list" "InstanceList" QFTOther
       "List of primary instances",
     FieldConfig (\cfg -> rsNormal . map instName . fst .
                          getGroupInstances cfg . groupName), QffNormal)
  ] ++
  map buildNdParamField allNDParamFields ++
  timeStampFields ++
  uuidFields "Group" ++
  serialFields "Group" ++
  tagsFields

-- | The group fields map.
fieldsMap :: FieldMap NodeGroup Runtime
fieldsMap =
  Map.fromList $ map (\v@(f, _, _) -> (fdefName f, v)) groupFields

-- | Dummy function for collecting live data (which groups don't have).
collectLiveData :: Bool -> ConfigData -> [NodeGroup]
                -> IO [(NodeGroup, Runtime)]
collectLiveData _ _ = return . map (\n -> (n, Runtime))
