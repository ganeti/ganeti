{-| Implementation of the Ganeti Query2 node group queries.

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

module Ganeti.Query.Group
  (fieldsMap) where

import Data.Maybe (mapMaybe)

import Ganeti.Config
import Ganeti.Objects
import Ganeti.Query.Language
import Ganeti.Query.Common
import Ganeti.Query.Types
import Ganeti.Utils (niceSort)

groupFields :: FieldList NodeGroup NoDataRuntime
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
     FieldConfig (\cfg -> rsNormal . length . getGroupNodes cfg . uuidOf),
     QffNormal)
  , (FieldDefinition "node_list" "NodeList" QFTOther "List of nodes",
     FieldConfig (\cfg -> rsNormal . map nodeName .
                          getGroupNodes cfg . uuidOf), QffNormal)
  , (FieldDefinition "pinst_cnt" "Instances" QFTNumber
       "Number of primary instances",
     FieldConfig
       (\cfg -> rsNormal . length . fst . getGroupInstances cfg . uuidOf),
     QffNormal)
  , (FieldDefinition "pinst_list" "InstanceList" QFTOther
       "List of primary instances",
     FieldConfig (\cfg -> rsNormal . niceSort . mapMaybe instName . fst .
                          getGroupInstances cfg . uuidOf), QffNormal)
  ] ++
  map buildNdParamField allNDParamFields ++
  timeStampFields ++
  uuidFields "Group" ++
  serialFields "Group" ++
  tagsFields

-- | The group fields map.
fieldsMap :: FieldMap NodeGroup NoDataRuntime
fieldsMap = fieldListToFieldMap groupFields
