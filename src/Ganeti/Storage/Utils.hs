{-| Implementation of Utility functions for storage

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

module Ganeti.Storage.Utils
  ( getStorageUnitsOfNode
  , nodesWithValidConfig
  ) where

import Ganeti.Config
import Ganeti.Objects
import Ganeti.Types
import qualified Ganeti.Types as T

import Control.Monad
import Data.List (nub)
import Data.Maybe

-- | Get the cluster's default storage unit for a given disk template
getDefaultStorageKey :: ConfigData -> DiskTemplate -> Maybe StorageKey
getDefaultStorageKey cfg T.DTDrbd8 = clusterVolumeGroupName $ configCluster cfg
getDefaultStorageKey cfg T.DTPlain = clusterVolumeGroupName $ configCluster cfg
getDefaultStorageKey cfg T.DTFile =
    Just (clusterFileStorageDir $ configCluster cfg)
getDefaultStorageKey _ _ = Nothing

-- | Get the cluster's default spindle storage unit
getDefaultSpindleSU :: ConfigData -> (StorageType, Maybe StorageKey)
getDefaultSpindleSU cfg =
    (T.StorageLvmPv, clusterVolumeGroupName $ configCluster cfg)

-- | Get the cluster's storage units from the configuration
getClusterStorageUnitRaws :: ConfigData -> [StorageUnitRaw]
getClusterStorageUnitRaws cfg =
    foldSUs (nub (maybe_units ++ [spindle_unit]))
  where disk_templates = clusterEnabledDiskTemplates $ configCluster cfg
        storage_types = map diskTemplateToStorageType disk_templates
        maybe_units = zip storage_types (map (getDefaultStorageKey cfg)
            disk_templates)
        spindle_unit = getDefaultSpindleSU cfg

-- | fold the storage unit list by sorting out the ones without keys
foldSUs :: [(StorageType, Maybe StorageKey)] -> [StorageUnitRaw]
foldSUs = foldr ff []
  where ff (st, Just sk) acc = SURaw st sk : acc
        ff (_, Nothing) acc = acc

-- | Gets the value of the 'exclusive storage' flag of the node
getExclusiveStorage :: ConfigData -> Node -> Maybe Bool
getExclusiveStorage cfg n = liftM ndpExclusiveStorage (getNodeNdParams cfg n)

-- | Determines whether a node's config contains an 'exclusive storage' flag
hasExclusiveStorageFlag :: ConfigData -> Node -> Bool
hasExclusiveStorageFlag cfg = isJust . getExclusiveStorage cfg

-- | Filter for nodes with a valid config
nodesWithValidConfig :: ConfigData -> [Node] -> [Node]
nodesWithValidConfig cfg = filter (hasExclusiveStorageFlag cfg)

-- | Get the storage units of the node
getStorageUnitsOfNode :: ConfigData -> Node -> [StorageUnit]
getStorageUnitsOfNode cfg n =
  let clusterSUs = getClusterStorageUnitRaws cfg
      es = fromJust (getExclusiveStorage cfg n)
  in  map (addParamsToStorageUnit es) clusterSUs
