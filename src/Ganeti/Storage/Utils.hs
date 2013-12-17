{-| Implementation of Utility functions for storage

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

module Ganeti.Storage.Utils
  ( getStorageUnitsOfNodes
  , nodesWithValidConfig
  ) where

import Ganeti.Config
import Ganeti.Objects
import Ganeti.Types
import qualified Ganeti.Types as T

import Control.Monad
import Data.List (nub)
import Data.Maybe
import qualified Data.Map as M

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

-- | Get the storage unit map for all nodes
getStorageUnitsOfNodes :: ConfigData -> [Node] -> M.Map String [StorageUnit]
getStorageUnitsOfNodes cfg ns =
  M.fromList (map (\n -> (nodeUuid n, getStorageUnitsOfNode cfg n)) ns)
